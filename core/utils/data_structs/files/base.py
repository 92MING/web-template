

import json5
import zipfile
import tomllib
import csv as csv_mod
import yaml as yaml_lib
    
from io import BytesIO
from pathlib import Path
from pydantic_core import core_schema
from typing import Any, AsyncGenerator, ClassVar, Literal, Protocol, Self, TYPE_CHECKING, cast, overload, runtime_checkable

from .medias._utils import _dump_media_dict, _get_media_json_schema
from .medias.loader import AcceptableFileSource, save_get_file_source
from ...concurrent_utils import run_any_func
from ...type_utils import AdvancedBaseModel
from .medias import Image, Audio, Video

class FileTypeMetaProtocol(Protocol):
    '''文件类型元数据协议。(deprecated, 使用 File 协议)'''
    Abstract: ClassVar[bool]
    Type: ClassVar[str]
    TypeNames: ClassVar[tuple[str, ...]]
    Suffixes: ClassVar[tuple[str, ...]] = ()
    MimePrefixes: ClassVar[tuple[str, ...]] = ()
    MimeTypes: ClassVar[tuple[str, ...]] = ()

def _iter_subclasses(root_cls: type[Any]) -> tuple[type[Any], ...]:
    discovered: list[type[Any]] = []
    seen: set[type[Any]] = set()

    def _walk(current_cls: type[Any]) -> None:
        for sub_cls in current_cls.__subclasses__():
            if sub_cls in seen:
                continue
            seen.add(sub_cls)
            discovered.append(sub_cls)
            _walk(sub_cls)

    _walk(root_cls)
    return tuple(discovered)


def _iter_file_classes() -> tuple[type[FileTypeMetaProtocol], ...]:
    from . import documents as _documents
    from .documents.base import BaseDocument

    del _documents

    document_classes = tuple(
        file_cls
        for file_cls in _iter_subclasses(BaseDocument)
        if not getattr(file_cls, 'Abstract', False)
    )
    return cast(tuple[type[FileTypeMetaProtocol], ...], (Image, Audio, Video, *document_classes))

def _class_type_tokens(file_cls: type[FileTypeMetaProtocol]) -> set[str]:
    tokens = {str(getattr(file_cls, 'Type', '')).strip().lower()}
    tokens.update(
        str(name).strip().lower()
        for name in getattr(file_cls, 'TypeNames', ())
        if str(name).strip()
    )
    return {token for token in tokens if token}

def _class_suffixes(file_cls: type[FileTypeMetaProtocol]) -> tuple[str, ...]:
    return tuple(str(suffix).lower() for suffix in getattr(file_cls, 'Suffixes', ()) if str(suffix).strip())

def _class_mime_prefixes(file_cls: type[FileTypeMetaProtocol]) -> tuple[str, ...]:
    mime_prefixes = tuple(str(prefix).lower() for prefix in getattr(file_cls, 'MimePrefixes', ()) if str(prefix).strip())
    if mime_prefixes:
        return mime_prefixes
    return tuple(f'data:{mime.lower()}' for mime in getattr(file_cls, 'MimeTypes', ()) if str(mime).strip())

def _class_source_keys(file_cls: type[FileTypeMetaProtocol]) -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()

    candidates = (
        str(getattr(file_cls, 'Type', '')).strip().lower(),
        str(getattr(file_cls, '__name__', '')).strip().lower(),
        *(str(name).strip().lower() for name in getattr(file_cls, 'TypeNames', ()) if str(name).strip()),
    )
    for key in candidates:
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return tuple(keys)


def _iter_source_field_names() -> tuple[str, ...]:
    names = ['data', 'content', 'source', 'url', 'file', 'media', 'document']
    seen = set(names)
    for file_cls in _iter_file_classes():
        for key in _class_source_keys(file_cls):
            if key in seen:
                continue
            seen.add(key)
            names.append(key)
    return tuple(names)


def _extract_source_from_dict(value: dict[Any, Any]) -> Any:
    for key in _iter_source_field_names():
        if key in value:
            return value.get(key)
    return None


def _supported_file_type_names() -> tuple[str, ...]:
    names: set[str] = set()
    for file_cls in _iter_file_classes():
        names.update(_class_source_keys(file_cls))
    return tuple(sorted(names))

def _match_file_class_by_type_name(type_name: str) -> type[FileTypeMetaProtocol] | None:
    normalized = _normalize_type_name(type_name)
    if not normalized:
        return None
    for file_cls in _iter_file_classes():
        if normalized in {token.replace('-', '').replace('_', '') for token in _class_type_tokens(file_cls)}:
            return file_cls
    return None

def _infer_file_class_from_bytes(source: bytes) -> type[FileTypeMetaProtocol] | None:
    from .documents._legacy_office import infer_legacy_ole_kind, is_ole_container
    from .documents.csv import CSV as CSVDocument
    from .documents.json import JSON
    from .documents.plain_text import PlainText
    from .documents.toml import TOML
    from .documents.tsv import TSV
    from .documents.xml import XML
    from .documents.yaml import YAML
    from .documents._utils import _probe_text_bytes

    stripped = source.lstrip().lower()
    preview = source[:512].lstrip().lower()

    if source.startswith(b'\x89PNG\r\n\x1a\n'):
        return Image
    if source.startswith(b'\xff\xd8\xff'):
        return Image
    if source.startswith((b'GIF87a', b'GIF89a')):
        return Image
    if source.startswith(b'BM'):
        return Image
    if source.startswith((b'II*\x00', b'MM\x00*')):
        return Image
    if len(source) >= 12 and source[:4] == b'RIFF' and source[8:12] == b'WEBP':
        return Image
    if preview.startswith(b'<svg') or (preview.startswith(b'<?xml') and b'<svg' in preview):
        return Image

    if len(source) >= 12 and source[:4] == b'RIFF' and source[8:12] == b'WAVE':
        return Audio
    if source.startswith(b'fLaC'):
        return Audio
    if source.startswith(b'OggS'):
        return Audio
    if source.startswith(b'ID3'):
        return Audio
    if len(source) >= 2 and source[0] == 0xFF and (source[1] & 0xE0) == 0xE0:
        return Audio

    if len(source) >= 12 and source[:4] == b'RIFF' and source[8:12] == b'AVI ':
        return Video
    if len(source) >= 12 and source[4:8] == b'ftyp':
        brand = source[8:16].lower()
        if b'm4a' in brand or b'm4b' in brand:
            return Audio
        return Video
    if source.startswith(b'\x1aE\xdf\xa3'):
        return Video
    if source.startswith(b'FLV'):
        return Video

    if stripped.startswith(b'%pdf-'):
        return _match_file_class_by_type_name('pdf')
    if stripped.startswith(b'{\\rtf'):
        return _match_file_class_by_type_name('rtf')
    if stripped.startswith(b'<!doctype html') or stripped.startswith(b'<html'):
        return _match_file_class_by_type_name('html')
    if is_ole_container(source):
        legacy_kind = infer_legacy_ole_kind(source)
        if legacy_kind == 'doc':
            return _match_file_class_by_type_name('doc')
        if legacy_kind == 'ppt':
            return _match_file_class_by_type_name('ppt')
    if zipfile.is_zipfile(BytesIO(source)):
        try:
            with zipfile.ZipFile(BytesIO(source)) as zf:
                names = zf.namelist()
                mimetype = zf.read('mimetype').decode('utf-8', errors='ignore').strip().lower() if 'mimetype' in names else ''
            if any(name.startswith('ppt/') for name in names):
                return _match_file_class_by_type_name('ppt')
            if any(name.startswith('word/') for name in names) or 'opendocument.text' in mimetype:
                return _match_file_class_by_type_name('doc')
            if any(name.lower().startswith('contents/section') for name in names) or 'application/hwp+zip' in mimetype:
                return _match_file_class_by_type_name('doc')
            if any(name.startswith('xl/') for name in names) or 'opendocument.spreadsheet' in mimetype or any(name.startswith('Index/') or name.startswith('Metadata/') for name in names):
                return _match_file_class_by_type_name('excel')
        except Exception:
            return None

    is_text, text, _encoding = _probe_text_bytes(source)
    if not is_text:
        return None

    stripped_text = text.lstrip()
    lower_text = stripped_text.lower()
    if not stripped_text:
        return PlainText

    if lower_text.startswith('<!doctype html') or lower_text.startswith('<html'):
        return _match_file_class_by_type_name('html')
    if stripped_text.startswith('<'):
        try:
            from xml.etree import ElementTree as ET
            ET.fromstring(stripped_text)
            return XML
        except Exception:
            ...
    if stripped_text.startswith(('{', '[')):
        try:
            json5.loads(text)
            return JSON
        except Exception:
            ...
    if tomllib is not None and '=' in text and ('\n[' in text or text.strip().startswith('[') or '.' in text.split('=', 1)[0]):
        try:
            tomllib.loads(text)
            return TOML
        except Exception:
            ...
    if ':' in text and ('\n-' in text or '\n' in text):
        try:
            parsed_yaml = yaml_lib.safe_load(text)
            if isinstance(parsed_yaml, (dict, list)):
                return YAML
        except Exception:
            ...
    try:
        dialect = csv_mod.Sniffer().sniff(text[:4096], delimiters=',\t;|')
        sample_rows = [row for row in csv_mod.reader(text.splitlines()[:8], dialect=dialect) if row]
        if len(sample_rows) >= 2 and all(len(row) == len(sample_rows[0]) for row in sample_rows[: min(len(sample_rows), 6)]):
            return TSV if dialect.delimiter == '\t' else CSVDocument
    except Exception:
        ...
    return PlainText

def _read_source_probe_bytes(source: Any, *, size: int = 8192) -> bytes | None:
    if isinstance(source, bytes):
        return source[:size]
    if not isinstance(source, (str, Path)):
        return None
    try:
        handler = run_any_func(save_get_file_source, source)
        data = handler.read(size)
        return data if isinstance(data, bytes) else None
    except Exception:
        return None

def _infer_file_type_by_source(source: Any) -> str | None:
    if isinstance(source, BytesIO):
        return _infer_file_type_by_source(source.getvalue())

    if _is_file_id_value(source):
        return _canonical_file_type(getattr(source, 'type', None))

    if isinstance(source, File):
        return _canonical_file_type(getattr(source, 'Type', None))

    if isinstance(source, bytes):
        if file_cls := _infer_file_class_from_bytes(source):
            return str(getattr(file_cls, 'Type', '')).lower() or None
        return None

    if isinstance(source, Path):
        suffix = source.suffix.lower()
    elif isinstance(source, str):
        value = source.strip().lower()
        for file_cls in _iter_file_classes():
            if any(value.startswith(prefix) for prefix in _class_mime_prefixes(file_cls)):
                return str(getattr(file_cls, 'Type', '')).lower() or None
        if value.startswith('{\\rtf') or value.startswith('<!doctype html') or value.startswith('<html') or value.startswith('%pdf-'):
            return _infer_file_type_by_source(value.encode('utf-8', errors='ignore'))
        suffix = Path(value).suffix.lower()
    else:
        return None

    for file_cls in _iter_file_classes():
        if suffix in _class_suffixes(file_cls):
            return str(getattr(file_cls, 'Type', '')).lower() or None

    probed = _read_source_probe_bytes(source)
    if probed and (file_cls := _infer_file_class_from_bytes(probed)) is not None:
        return str(getattr(file_cls, 'Type', '')).lower() or None
    return None

def _normalize_type_name(type_name: Any) -> str:
    if not isinstance(type_name, str):
        return ''
    return type_name.strip().lower().replace('-', '').replace('_', '')


def _canonical_file_type(type_name: Any) -> str | None:
    normalized = _normalize_type_name(type_name)
    if not normalized:
        return None
    file_cls = _match_file_class_by_type_name(normalized)
    if file_cls is not None:
        canonical = str(getattr(file_cls, 'Type', '')).strip().lower()
        return canonical or None
    return str(type_name).strip().lower()

def _is_file_id_value(value: Any, *, require_context: bool = False, require_type: bool = False) -> bool:
    file_id_cls = globals().get('FileID')
    if file_id_cls is None or not isinstance(value, file_id_cls):
        return False
    has_id = bool(getattr(value, 'id', None))
    has_category = getattr(value, 'category', None) is not None
    has_type = getattr(value, 'type', None) is not None
    if not has_id:
        return False
    if require_context and not (has_category or has_type):
        return False
    if require_type and not has_type:
        return False
    return True


def _infer_filename_from_source(source: Any) -> str | None:
    if isinstance(source, Path):
        return source.name or None
    if isinstance(source, str):
        source_text = source.strip()
        if source_text.startswith(('http://', 'https://', 'ftp://', 'ftps://')):
            return Path(source_text.split('?', 1)[0]).name or None
        if len(source_text) <= 2048:
            maybe_path = Path(source_text)
            if maybe_path.exists():
                return maybe_path.name or None
    return None

def _check_source_file_type_compat(
    cls_type: str,
    cls_type_names: tuple[str, ...],
    source: Any,
    cls_suffixes: tuple[str, ...] = (),
    extra_acceptable_types: tuple[str, ...] = (),
) -> str | None:
    if not _is_file_id_value(source, require_type=True):
        return None
    raw_source_type = getattr(source, 'type', None)
    ft = _canonical_file_type(raw_source_type)
    if not ft:
        return None
    # Build the set of tokens this class accepts (Type + TypeNames + suffix stems)
    accepted = {cls_type.strip().lower().replace('-', '').replace('_', '')}
    accepted.update(
        str(n).strip().lower().replace('-', '').replace('_', '')
        for n in cls_type_names if str(n).strip()
    )
    accepted.update(
        str(sfx).lstrip('.').lower().replace('-', '').replace('_', '')
        for sfx in cls_suffixes if str(sfx).strip()
    )
    accepted.update(
        str(t).strip().lower().replace('-', '').replace('_', '')
        for t in extra_acceptable_types if str(t).strip()
    )

    if ft in accepted:
        return ft
    # Also accept if _match_file_class_by_type_name resolves ft to the same class
    resolved_cls = _match_file_class_by_type_name(ft)
    if resolved_cls is not None:
        resolved_type = _normalize_type_name(getattr(resolved_cls, 'Type', ''))
        if resolved_type == _normalize_type_name(cls_type):
            return ft
    raise ValueError(
        f"Source file type '{raw_source_type}' is incompatible "
        f"with {cls_type}; expected one of {sorted(accepted)}."
    )


def _prevalidate_file(value: Any) -> Any:
    if isinstance(value, _iter_file_classes()):
        return value

    if _is_file_id_value(value, require_context=True):
        return FileID.Get(value)

    if isinstance(value, dict):
        source = _extract_source_from_dict(value)
        if source is None and 'id' in value and ('category' in value or 'filename' in value or 'type' in value):
            raise ValueError('FileID dict payloads are no longer supported; pass a FileID instance.')
        type_name = _normalize_type_name(value.get('type'))
        if not type_name:
            type_name = _normalize_type_name(value.get('media_type'))
        if not type_name:
            type_name = _infer_file_type_by_source(source) or ''

        file_cls = _match_file_class_by_type_name(type_name) if type_name else None
        if file_cls is None and source is not None:
            inferred = _infer_file_type_by_source(source)
            file_cls = _match_file_class_by_type_name(inferred) if inferred else None
        if file_cls is not None and source is not None:
            return file_cls(source)  # type: ignore
        if source is not None:
            raise ValueError('Unsupported file source; unable to infer a known file/document type.')
        return value

    inferred = _infer_file_type_by_source(value)
    if inferred and (file_cls := _match_file_class_by_type_name(inferred)) is not None:
        return file_cls(value)  # type: ignore

    supported_types = '/'.join(_supported_file_type_names())
    raise ValueError(f'Unsupported file data. Expected one of {supported_types} or a valid source dict.')

@runtime_checkable
class File(Protocol):
    '''
    文件协议, 用于概括 `Image/Audio/Video` 与各类文档对象的共通能力。

    约定实现者至少提供:
    - `__init__`: 从 source 构造, 不立即加载。
    - `load`: 异步加载实际数据 (幂等)。
    - `to_bytes`: 导出二进制字节。
    - `to_base64`: 导出 base64 字符串。
    - `to_md5_hash`: 导出内容哈希, 便于缓存与去重。
    - `save`: 将媒体保存到本地路径。
    '''

    Abstract: ClassVar[bool]
    Type: ClassVar[str]
    TypeNames: ClassVar[tuple[str, ...]]
    Suffixes: ClassVar[tuple[str, ...]]
    MimePrefixes: ClassVar[tuple[str, ...]]

    async def load(self) -> Self:
        '''异步加载实际数据。幂等。'''
        ...

    def to_bytes(self, *args, **kwargs) -> bytes:
        '''导出媒体原始字节。'''
        ...

    def to_base64(self, *args, **kwargs) -> str:
        '''导出媒体内容为 base64 字符串。'''
        ...

    def to_md5_hash(self, *args, **kwargs) -> str:
        '''导出媒体内容 md5 哈希。'''
        ...

    def save(self, path: str | Path, *args, **kwargs) -> str | Path | None:
        '''将媒体保存到指定路径。'''
        ...
        
    def pydantic_dump(self) -> dict[str, Any]:
        '''导出适合 Pydantic 序列化的 dict。'''
        ...

    @classmethod
    def __get_pydantic_core_schema__(cls, _source: Any, _handler: Any):
        def validator(data: Any) -> Any:
            return _prevalidate_file(data)
            
        def serializer(file_obj: Any):
            if hasattr(file_obj, 'pydantic_dump') and callable(file_obj.pydantic_dump):
                return file_obj.pydantic_dump()    # type: ignore
            return _dump_media_dict(file_obj.to_base64(), type(file_obj))
            
        validate_schema = core_schema.no_info_after_validator_function(validator, core_schema.any_schema())
        serialize_schema = core_schema.plain_serializer_function_ser_schema(serializer)
        return core_schema.json_or_python_schema(
            json_schema=validate_schema,
            python_schema=validate_schema,
            serialization=serialize_schema,
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, cs: Any, handler: Any):
        return _get_media_json_schema(cls)

# ── FileStorageProtocol & FileID ──────────────────────────────────────────────
@runtime_checkable
class FileStorageProtocol(Protocol):
    '''Protocol for a file storage backend.

    Implementations wrap an object-storage client (local, MinIO, etc.) and
    expose a minimal async interface used by :class:`FileID`.
    '''

    def get_file(self, object_id: str, *, chunk_size: int = 65536) -> AsyncGenerator[bytes, None]:
        '''Stream raw bytes for *object_id* in chunks.'''
        ...

    async def put_file(
        self,
        data: bytes,
        category: str,
        expire: float | None,
        type: str | None = None,
        *,
        object_name: str | None = None,
    ) -> str:
        '''Store *data* and return the assigned *object_id*.

        Args:
            data: Raw file bytes.
            category: Logical grouping (e.g. ``"cache"``, ``"upload"``).
            expire: Optional TTL in seconds from now; ``None`` = permanent.
            type: Optional human-readable file type hint (e.g. ``"image"``,
                ``"audio"``, ``"pdf"``).  May be embedded in the object name for
                easier inspection but is not required for retrieval.
            object_name: When given, use this exact name as the storage key
                instead of auto-generating one.  Used by content-addressable
                storage (FileID CAS).

        Returns:
            Unique object identifier that can be passed to :meth:`get_file` /
            :meth:`delete_file`.
        '''
        ...

    async def delete_file(self, object_id: str) -> bool:
        '''Delete the object identified by *object_id*.

        Returns:
            ``True`` if the object existed and was removed.
        '''
        ...


class FileID(AdvancedBaseModel):
    '''Stored-file identifier with explicit file metadata.

    Uses content-addressable storage: ``id`` is the SHA-256 hex digest of the
    file bytes.  Reference counting via KV (``fileref:{category}:{hash}``)
    ensures the actual object is only deleted when no references remain.
    '''

    _protocols: ClassVar[dict[str, FileStorageProtocol]] = {}

    id: str
    '''Content hash (SHA-256 hex) for CAS files, or legacy object-id.'''
    category: str
    '''Storage category / backend bucket.'''
    type: str
    '''Canonical file type; maps to a specific File class.'''
    filename: str | None = None
    '''Original filename when known.'''

    def __str__(self) -> str:
        return self.id

    @classmethod
    def AddProtocol(cls, category: str, protocol: FileStorageProtocol) -> None:
        '''Register a storage *protocol* for *category*.'''
        cls._protocols[category] = protocol

    @classmethod
    def _get_protocol(cls, category: str) -> FileStorageProtocol:
        proto = cls._protocols.get(category) or cls._protocols.get('default')
        if proto is None:
            raise RuntimeError(
                f"No FileStorageProtocol registered for category '{category}'. "
                "Call FileID.AddProtocol('default', ...) to configure a backend."
            )
        return proto

    # ── Content-Addressable Storage helpers ──────────────────────────────

    @staticmethod
    def _storage_object_name(object_id: str) -> str:
        '''Map a FileID.id → actual object-storage key (``_fileid/{hash}``).'''
        return f'_fileid/{object_id}'

    @staticmethod
    def _kv_ref_key(category: str, file_hash: str) -> str:
        return f'fileref:{category}:{file_hash}'

    @classmethod
    def _get_kv_client(cls):
        '''Lazy-import and return the KV client for file metadata / ref counting.'''
        from core.storage.config import StorageConfig
        return StorageConfig.Global().kv.get_client('file_metadata', fallback='default')

    @classmethod
    async def _incr_ref(cls, category: str, file_hash: str) -> int:
        '''Increment the reference count for a CAS file and return the new count.'''
        kv = cls._get_kv_client()
        key = cls._kv_ref_key(category, file_hash)
        count = await kv.get(key, default=0, target_type=int)
        count = (count or 0) + 1
        await kv.set(key, count)
        return count

    @classmethod
    async def _decr_ref_and_cleanup(cls, category: str, file_hash: str) -> int:
        '''Decrement the reference count.  If it reaches zero, delete the
        actual object from storage and remove the KV key.  Returns the new count.
        '''
        kv = cls._get_kv_client()
        key = cls._kv_ref_key(category, file_hash)
        count = await kv.get(key, default=0, target_type=int)
        count = (count or 0) - 1
        if count <= 0:
            # Remove the real object + the KV counter
            try:
                await cls._delete_target(category, file_hash)
            except Exception:
                pass  # best-effort; object may already be gone
            await kv.delete(key)
            return 0
        await kv.set(key, count)
        return count

    @classmethod
    def _require_instance(cls, file_id: 'FileID') -> 'FileID':
        if isinstance(file_id, cls):
            return file_id
        if isinstance(file_id, dict):
            raise TypeError('Plain dict FileID payloads are no longer supported; pass FileID(...).')
        raise TypeError(f'Expected FileID instance, got {type(file_id).__name__}.')

    @classmethod
    async def _iter_stored_chunks(
        cls,
        category: str,
        object_id: str,
        *,
        chunk_size: int = 65536,
    ) -> AsyncGenerator[bytes, None]:
        proto = cls._get_protocol(category)
        storage_name = cls._storage_object_name(object_id)
        try:
            result = proto.get_file(storage_name, chunk_size=max(1, chunk_size))
        except TypeError:
            result = proto.get_file(storage_name)  # type: ignore[call-arg]

        if hasattr(result, '__aiter__'):
            async for chunk in result:  # type: ignore[union-attr]
                if chunk:
                    yield bytes(chunk)
            return

        data = await result  # type: ignore[misc]
        if not data:
            return
        for index in range(0, len(data), max(1, chunk_size)):
            yield bytes(data[index:index + max(1, chunk_size)])

    @classmethod
    async def _peek_target(
        cls,
        category: str,
        object_id: str,
        *,
        size: int = 8192,
        chunk_size: int = 65536,
    ) -> bytes:
        remaining = max(0, size)
        if remaining == 0:
            return b''

        chunks: list[bytes] = []
        async for chunk in cls._iter_stored_chunks(category, object_id, chunk_size=chunk_size):
            if not chunk:
                continue
            if len(chunk) >= remaining:
                chunks.append(bytes(chunk[:remaining]))
                break
            chunks.append(chunk)
            remaining -= len(chunk)
            if remaining <= 0:
                break
        return b''.join(chunks)

    @classmethod
    async def _delete_target(cls, category: str, object_id: str) -> bool:
        proto = cls._get_protocol(str(category))
        storage_name = cls._storage_object_name(str(object_id))
        return await proto.delete_file(storage_name)

    @classmethod
    async def Create(
        cls,
        data: 'AcceptableFileSource | BytesIO | File',
        category: str = 'default',
        expire: float | None = None,
        type: str | None = None,
        filename: str | None = None,
    ) -> 'FileID':
        '''Upload data to storage and return a content-addressed FileID.

        The ``id`` is the SHA-256 hex digest of the raw bytes.  The actual
        object is uploaded via the registered protocol with a deterministic
        storage key (``_fileid/{hash}``).  Uploading the same content twice
        is idempotent — the object is overwritten with identical bytes.
        '''
        import hashlib
        payload: bytes
        inferred_type = _canonical_file_type(type)
        resolved_filename = str(filename) if filename else None

        if isinstance(data, File):
            file_obj = cast(File, data)
            payload = bytes(file_obj.to_bytes())
            if inferred_type is None:
                inferred_type = _canonical_file_type(getattr(file_obj, 'Type', None))
        else:
            payload = bytes((await save_get_file_source(data)).read())
            if resolved_filename is None:
                resolved_filename = _infer_filename_from_source(data)

        if inferred_type is None and resolved_filename is not None:
            inferred_type = _canonical_file_type(_infer_file_type_by_source(resolved_filename))
        if inferred_type is None:
            inferred_type = _canonical_file_type(_infer_file_type_by_source(data))
        if inferred_type is None:
            inferred_type = _canonical_file_type(_infer_file_type_by_source(payload))
        if inferred_type is None:
            raise ValueError('Cannot determine file type for FileID.Create input; provide `type`.')

        # Content-addressable: id = SHA-256 hex, storage key = _fileid/{hash}
        file_hash = hashlib.sha256(payload).hexdigest()
        storage_name = cls._storage_object_name(file_hash)

        proto = cls._get_protocol(category)
        await proto.put_file(payload, category, expire, inferred_type, object_name=storage_name)

        # Increment reference count
        try:
            await cls._incr_ref(category, file_hash)
        except Exception:
            pass  # KV not available (e.g. unit tests) — degrade gracefully

        return cls(id=file_hash, category=category, type=inferred_type, filename=resolved_filename)

    @classmethod
    def GetData(
        cls,
        file_id: 'FileID',
        *,
        chunk_size: int = 65536,
    ) -> AsyncGenerator[bytes, None]:
        '''Stream raw bytes for the given file target.'''
        target = cls._require_instance(file_id)
        return cls._iter_stored_chunks(target.category, target.id, chunk_size=chunk_size)

    @classmethod
    def Get(cls, file_id: 'FileID') -> File:
        '''Return the deferred File object represented by *file_id*.'''
        typed_file_id = cls._require_instance(file_id)
        file_cls = _match_file_class_by_type_name(typed_file_id.type)
        if file_cls is None:
            raise ValueError(f"Unsupported file type: {typed_file_id.type}")
        return cast(File, file_cls(typed_file_id))  # type: ignore

    @classmethod
    async def GetBytes(
        cls,
        file_id: 'FileID',
        *,
        chunk_size: int = 65536,
    ) -> bytes:
        '''Retrieve all bytes for the given *file_id*.'''
        target = cls._require_instance(file_id)
        chunks: list[bytes] = []
        async for chunk in cls._iter_stored_chunks(target.category, target.id, chunk_size=chunk_size):
            chunks.append(chunk)
        return b''.join(chunks)

    @classmethod
    async def Peek(
        cls,
        file_id: 'FileID',
        *,
        size: int = 8192,
        chunk_size: int = 65536,
    ) -> bytes:
        '''Read up to *size* bytes from the beginning of the file stream.'''
        target = cls._require_instance(file_id)
        return await cls._peek_target(target.category, target.id, size=size, chunk_size=chunk_size)

    @classmethod
    async def Delete(cls, file_id: 'FileID') -> bool:
        '''Decrement the reference count for *file_id*.

        If the count reaches zero (or the id is not a CAS hash), the
        underlying object is deleted from storage.
        '''
        target = cls._require_instance(file_id)
        remaining = await cls._decr_ref_and_cleanup(target.category, target.id)
        return remaining <= 0

    def __repr__(self) -> str:
        return (
            f"FileID(id={self.id!r}, category={self.category!r}, "
            f"type={self.type!r}, filename={self.filename!r})"
        )


__all__ = [
    'FileTypeMetaProtocol',
    'File',
    'FileStorageProtocol',
    'FileID',
]
