"""Portable file-source loader (ported from thinkthinksyn)."""



import time
import base64
import fnmatch

from collections.abc import AsyncGenerator as AsyncGeneratorABC, AsyncIterable as AsyncIterableABC, Generator as GeneratorABC, Iterable as IterableABC, Mapping as MappingABC
from io import BytesIO
from pathlib import Path
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterable,
    BinaryIO,
    Generator,
    Iterable,
    Sequence,
    TypeVar,
    overload,
    TYPE_CHECKING,
)
from typing_extensions import TypeAliasType

if TYPE_CHECKING:
    from ..base import FileID

_T = TypeVar('_T')
_IO = TypeVar('_IO', bound=BinaryIO)
_Generator = TypeAliasType(
    "_Generator",
    Generator[_T, None, None] | AsyncGenerator[_T, None] | AsyncIterable[_T] | Iterable[_T],
    type_params=(_T,),
)

AcceptableFileSource = TypeAliasType(
    "AcceptableFileSource",
    "str | bytes | BytesIO | Path | FileID | _Generator[bytes] | _Generator[str]",
)

_DEFAULT_MAX_SIZE = 256 * 1024 * 1024  # 256 MB
_DEFAULT_TIMEOUT = 120  # seconds


# ── helpers ──────────────────────────────────────────────────────────────────
def is_acceptable_file_source(value: Any) -> bool:
    """Quick check whether *value* looks like a valid file source."""
    if isinstance(value, (str, bytes, Path, BytesIO)):
        return True
    if isinstance(value, MappingABC):
        return False
    if isinstance(value, (GeneratorABC, AsyncGeneratorABC, AsyncIterableABC, IterableABC)):
        return True
    file_id_cls = globals().get('FileID')
    if file_id_cls is not None and isinstance(value, file_id_cls):
        return True
    return False

# ── stream core ──────────────────────────────────────────────────────────────
async def _save_get_stream(
    stream: _Generator[bytes],  # type: ignore[type-arg]
    out: _IO | None = None,
    max_size: int | None = _DEFAULT_MAX_SIZE,
    timeout: int | float | None = _DEFAULT_TIMEOUT,
) -> _IO:
    total_size = 0
    output: BinaryIO = BytesIO() if out is None else out

    start = time.time()
    if isinstance(stream, (Generator, Iterable)):
        for chunk in stream:
            total_size += len(chunk)
            if max_size is not None and total_size > max_size:
                raise ValueError("Data exceeds maximum allowed size")
            if timeout is not None and (time.time() - start) > timeout:
                raise TimeoutError("Data retrieval timed out")
            output.write(chunk)
    else:
        async for chunk in stream:
            total_size += len(chunk)
            if max_size is not None and total_size > max_size:
                raise ValueError("Data exceeds maximum allowed size")
            if timeout is not None and (time.time() - start) > timeout:
                raise TimeoutError("Data retrieval timed out")
            output.write(chunk)

    if isinstance(output, BytesIO):
        output.seek(0)
    return output  # type: ignore[return-value]

# ── path ─────────────────────────────────────────────────────────────────────
async def save_get_path(
    path: str | Path,
    out: BinaryIO | None = None,
    max_size: int | None = _DEFAULT_MAX_SIZE,
    timeout: int | float | None = _DEFAULT_TIMEOUT,
    whitelist_dirs: Sequence[str | Path] | None = None,
    blacklist_dirs: Sequence[str | Path] | None = None,
) -> BinaryIO:
    import aiofiles

    path = Path(path).resolve()

    if whitelist_dirs is not None:
        if not any(fnmatch.fnmatch(str(path.parent), str(p)) for p in whitelist_dirs):
            raise ValueError("Directory not in whitelist")
    if blacklist_dirs is not None:
        if any(fnmatch.fnmatch(str(path.parent), str(p)) for p in blacklist_dirs):
            raise ValueError("Directory is in blacklist")

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    async def file_stream():
        async with aiofiles.open(path, 'rb') as f:
            while True:
                chunk = await f.read(1024)
                if not chunk:
                    break
                yield chunk

    return await _save_get_stream(file_stream(), out, max_size, timeout)

# ── url ──────────────────────────────────────────────────────────────────────
async def save_get_url(
    url: str,
    out: BinaryIO | None = None,
    max_size: int | None = _DEFAULT_MAX_SIZE,
    timeout: int | float | None = _DEFAULT_TIMEOUT,
    whitelist_domains: Sequence[str] | None = None,
    blacklist_domains: Sequence[str] | None = None,
) -> BinaryIO:
    import aiohttp
    from urllib.parse import urlparse

    url = url.strip()
    parsed = urlparse(url)
    host = parsed.netloc or (parsed.path.split('/')[0] if parsed.path else '')

    if parsed.scheme not in ('http', 'https', 'ftp', 'ftps'):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

    if whitelist_domains is not None:
        if not any(fnmatch.fnmatch(host, p) for p in whitelist_domains):
            raise ValueError("Domain not in whitelist")
    if blacklist_domains is not None:
        if any(fnmatch.fnmatch(host, p) for p in blacklist_domains):
            raise ValueError("Domain is in blacklist")

    if parsed.scheme in ('ftp', 'ftps'):
        import aioftp
        ftp_host = parsed.hostname or host
        ftp_port = parsed.port or aioftp.DEFAULT_PORT
        ftp_user = parsed.username or aioftp.DEFAULT_USER
        ftp_pass = parsed.password or aioftp.DEFAULT_PASSWORD
        ftp_path = parsed.path or '/'
        async with aioftp.Client.context(ftp_host, ftp_port, ftp_user, ftp_pass) as client:
            stream = await client.download_stream(ftp_path)

            async def ftp_stream():
                async for chunk in stream.iter_by_block(1024):
                    yield chunk

            return await _save_get_stream(ftp_stream(), out, max_size, timeout)

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise ValueError(f"Failed to retrieve URL: {response.status}")

            async def http_stream():
                async for chunk in response.content.iter_chunked(1024):
                    yield chunk

            return await _save_get_stream(http_stream(), out, max_size, timeout)

# ── base64 ───────────────────────────────────────────────────────────────────
async def save_get_base64(
    b64_string: str | _Generator[str],  # type: ignore[type-arg]
    out: BinaryIO | None = None,
    max_size: int | None = _DEFAULT_MAX_SIZE,
    timeout: int | float | None = _DEFAULT_TIMEOUT,
) -> BinaryIO:
    if isinstance(b64_string, str):
        if not b64_string:
            return BytesIO() if out is None else out  # type: ignore[return-value]
        if b64_string.startswith("data:"):
            b64_string = b64_string.split("base64,", 1)[1]

        async def b64_stream():
            yield base64.b64decode(b64_string)
    else:
        async def b64_stream():  # type: ignore[no-redef]
            is_first = True
            buf = ''
            if isinstance(b64_string, (Generator, Iterable)):
                for chunk in b64_string:
                    if is_first:
                        is_first = False
                        if chunk.startswith("data:"):
                            chunk = chunk.split("base64,", 1)[1]
                            if not chunk:
                                continue
                    buf += chunk
                    remainder = len(buf) % 4
                    to_decode = buf[:-remainder] if remainder else buf
                    buf = buf[-remainder:] if remainder else ''
                    if to_decode:
                        yield base64.b64decode(to_decode)
            else:
                async for chunk in b64_string:  # type: ignore[union-attr]
                    if is_first:
                        is_first = False
                        if chunk.startswith("data:"):
                            chunk = chunk.split("base64,", 1)[1]
                            if not chunk:
                                continue
                    buf += chunk
                    remainder = len(buf) % 4
                    to_decode = buf[:-remainder] if remainder else buf
                    buf = buf[-remainder:] if remainder else ''
                    if to_decode:
                        yield base64.b64decode(to_decode)
            if buf:
                yield base64.b64decode(buf)

    return await _save_get_stream(b64_stream(), out, max_size, timeout)

# ── bytes ────────────────────────────────────────────────────────────────────
async def save_get_bytes(
    byte_data: bytes | _Generator[bytes],  # type: ignore[type-arg]
    out: BinaryIO | None = None,
    max_size: int | None = _DEFAULT_MAX_SIZE,
    timeout: int | float | None = _DEFAULT_TIMEOUT,
) -> BinaryIO:
    if isinstance(byte_data, bytes):
        async def _single():
            yield byte_data
        return await _save_get_stream(_single(), out, max_size, timeout)
    return await _save_get_stream(byte_data, out, max_size, timeout)  # type: ignore[arg-type]


# ── all-in-one ───────────────────────────────────────────────────────────────
@overload
async def save_get_file_source(
    source: AcceptableFileSource,  # type: ignore[type-arg]
    out: None = None,
    max_size: int | None = _DEFAULT_MAX_SIZE,
    timeout: int | float | None = _DEFAULT_TIMEOUT,
    /,
    **kwargs: Any,
) -> BytesIO: ...

@overload
async def save_get_file_source(
    source: AcceptableFileSource,  # type: ignore[type-arg]
    out: _IO = ...,  # type: ignore[assignment]
    max_size: int | None = _DEFAULT_MAX_SIZE,
    timeout: int | float | None = _DEFAULT_TIMEOUT,
    /,
    **kwargs: Any,
) -> _IO: ...

async def save_get_file_source(
    source: AcceptableFileSource,  # type: ignore[type-arg]
    out: BinaryIO | None = None,
    max_size: int | None = _DEFAULT_MAX_SIZE,
    timeout: int | float | None = _DEFAULT_TIMEOUT,
    /,
    **kwargs: Any,
) -> BinaryIO:
    """Universal interface to retrieve data from various sources.

    Supports: URL, file path, bytes, base64 string, byte/str generators, FileID.
    """
    from ..base import FileID

    if isinstance(source, MappingABC):
        raise TypeError('Plain dict FileID payloads are no longer supported; pass FileID(...).')

    if isinstance(source, FileID):
        source = FileID.GetData(source)   # type: ignore[arg-type]

    if isinstance(source, bytes):
        return await save_get_bytes(source, out, max_size, timeout)

    if isinstance(source, BytesIO):
        source.seek(0)
        return await save_get_bytes(source.read(), out, max_size, timeout)

    if isinstance(source, str):
        if source.startswith(('http://', 'https://', 'ftp://', 'ftps://')):
            return await save_get_url(source, out, max_size, timeout, **kwargs)
        if source.startswith('data:') and ';base64,' in source[:64]:
            b64_data = source.split('base64,', 1)[1]
            return await save_get_base64(b64_data, out, max_size, timeout)
        # Try base64 decode
        if len(source) % 4 == 0 and len(source) > 0:
            try:
                base64.b64decode(source, validate=True)
                return await save_get_base64(source, out, max_size, timeout)
            except Exception:
                pass
        if len(source) <= 2048:
            source_path = Path(source)
            if source_path.exists():
                return await save_get_path(source_path, out, max_size, timeout, **kwargs)
        raise ValueError(
            f"Unknown source type: string is not a URL, valid base64, or existing file path (len={len(source)})"
        )

    if isinstance(source, Path):
        return await save_get_path(source, out, max_size, timeout, **kwargs)

    if isinstance(source, (GeneratorABC, AsyncGeneratorABC, AsyncIterableABC, IterableABC)):
        try:
            if isinstance(source, GeneratorABC):
                first_item = next(source)
            elif isinstance(source, IterableABC):
                first_item = next(iter(source))
            elif isinstance(source, AsyncGeneratorABC):
                first_item = await source.__anext__()
            else:
                source = source.__aiter__()
                first_item = await source.__anext__()
        except (StopIteration, StopAsyncIteration):
            return BytesIO() if out is None else out  # type: ignore[return-value]

        if isinstance(first_item, bytes):
            async def byte_gen():
                yield first_item
                if isinstance(source, (GeneratorABC, IterableABC)):
                    for item in source:
                        yield item
                else:
                    async for item in source:  # type: ignore[union-attr]
                        yield item
            return await save_get_bytes(byte_gen(), out, max_size, timeout)  # type: ignore[arg-type]
        else:
            async def str_gen():
                yield first_item
                if isinstance(source, (GeneratorABC, IterableABC)):
                    for item in source:
                        yield item
                else:
                    async for item in source:  # type: ignore[union-attr]
                        yield item
            return await save_get_base64(str_gen(), out, max_size, timeout)  # type: ignore[arg-type]

    raise TypeError(f"Unsupported source type: {type(source)}")


__all__ = [
    "AcceptableFileSource", 
    "is_acceptable_file_source", 
    'save_get_file_source'
]