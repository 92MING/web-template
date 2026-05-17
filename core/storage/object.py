import asyncio
import copy
import json
import threading
import mimetypes
import tempfile
import logging

from io import BytesIO
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, AsyncIterable, Iterable, Iterator, Mapping, Self, TypeAlias, TypedDict, cast
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator
from typing_extensions import Unpack

from ..utils.concurrent_utils import get_async_generator, run_async_in_sync as _run_async_in_sync

from .base import (
    StorageClientBase,
    StorageClientInitParams,
    _default_local_storage_root,
    _ensure_dir,
    _normalize_expire_at,
    _now_ts,
    _ttl_from_expire_at,
)
from .kv import KVClientBase, SQLiteKVClient

if TYPE_CHECKING:
    from .config import KV_DB_ConfigBase
    from miniopy_async.api import Minio as _AsyncMinioClient

_logger = logging.getLogger(__name__)

type ObjectMetadataValue = (
    str | int | float | bool | None | list[ObjectMetadataValue] | dict[str, ObjectMetadataValue]
)
ObjectMetadataMapping: TypeAlias = Mapping[str, ObjectMetadataValue]


class ObjectMetadata(TypedDict, total=False):
    object_id: str
    name: str
    path: str
    size: int
    content_type: str | None
    created_at: float | None
    updated_at: float | None
    accessed_at: float | None
    expire_at: float | None
    metadata: dict[str, ObjectMetadataValue]

ObjectDataSource = bytes | bytearray | memoryview | Iterable[bytes] | AsyncIterable[bytes]


class OBS_Object(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    storage_name: str = "default"
    object_id: str = ""
    name: str = ""
    path: str = ""
    size: int = 0
    content_type: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
    accessed_at: float | None = None
    expire_at: float | None = None
    metadata: dict[str, ObjectMetadataValue] = Field(default_factory=dict)

    _object_client: "ObjectClientBase | None" = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, data: object) -> object:
        if isinstance(data, OBS_Object):
            return data.model_dump(mode="python")
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        path = str(normalized.get("path") or normalized.get("object_id") or "").strip()
        if path:
            normalized["path"] = path
            normalized.setdefault("object_id", path)
            normalized.setdefault("name", Path(path).name)
        elif normalized.get("object_id"):
            object_id = str(normalized["object_id"]).strip()
            normalized["object_id"] = object_id
            normalized.setdefault("path", object_id)
            normalized.setdefault("name", Path(object_id).name)

        if normalized.get("storage_name") is None:
            for alias in ("client_name", "object_storage", "object_storage_name", "storage"):
                alias_value = normalized.get(alias)
                if alias_value:
                    normalized["storage_name"] = alias_value
                    break
        normalized.setdefault("storage_name", "default")
        if not isinstance(normalized.get("metadata"), dict):
            normalized["metadata"] = {}
        return normalized

    def bind_client(self, client: "ObjectClientBase") -> Self:
        self._object_client = client
        if getattr(client, "_name", None):
            self.storage_name = str(client._name)
        return self

    def _resolve_client(self) -> "ObjectClientBase":
        if self._object_client is not None:
            return self._object_client
        from .config import StorageConfig

        client = StorageConfig.Global().get_object_client(self.storage_name or "default")
        self._object_client = client
        return client

    async def _get_bytes(self) -> bytes | None:
        return await self._resolve_client().get_bytes(self.path)

    def get(self, key: str | None = None, default: Any = None) -> Any:
        if key is not None:
            return self.model_dump(mode="python").get(key, default)
        return self._get_bytes()

    async def get_stream(self, *, chunk_size: int = 65536) -> AsyncGenerator[bytes, None]:
        async for chunk in self._resolve_client().get(self.path, chunk_size=chunk_size):
            yield chunk

    async def get_text(self, *, encoding: str = "utf-8", errors: str = "strict") -> str | None:
        data = await self._get_bytes()
        if data is None:
            return None
        return data.decode(encoding, errors=errors)

    async def get_json(self) -> Any:
        text = await self.get_text()
        if text is None:
            return None
        return json.loads(text)

    async def exists(self) -> bool:
        return await self._resolve_client()._get_metadata(self.path) is not None

    async def delete(self) -> bool:
        return await self._resolve_client().delete(self.path)

    async def set_expire(self, expire: float | int | None) -> bool:
        updated = await self._resolve_client().set_expire(self.path, expire)
        if updated:
            self.expire_at = _normalize_expire_at(expire)
        return updated

    def to_metadata_dict(self) -> ObjectMetadata:
        return cast(ObjectMetadata, self.model_dump(mode="python", exclude={"storage_name"}))

    def __getitem__(self, key: str) -> Any:
        return self.model_dump(mode="python")[key]

    def __iter__(self) -> Iterator[tuple[str, Any]]:
        return iter(self.model_dump(mode="python").items())

class ObjectClientInitParams(StorageClientInitParams, total=False):
    namespace: str
    folder: str | None
    default_expire: float | None
    metadata_kv: KVClientBase | None
    metadata_db: "KV_DB_ConfigBase | str | None"
    metadata_db_path: str | Path | None

class LocalObjectClientInitParams(ObjectClientInitParams, total=False):
    root_path: str | Path

class MinIOObjectClientInitParams(ObjectClientInitParams, total=False):
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool
    region: str | None


class ObjectClientBase(StorageClientBase, ABC, storage_kind="object"):

    def __init__(self, **kwargs: Unpack[ObjectClientInitParams]) -> None:
        super().__init__(**kwargs)
        self._namespace = kwargs.get("namespace", "default")
        self._folder_prefix = _normalize_folder_prefix(kwargs.get("folder", None))
        self._default_expire = kwargs.get("default_expire", None)
        self._metadata_db: "KV_DB_ConfigBase | str | None" = kwargs.get("metadata_db", None)
        self._metadata_db_path = kwargs.get("metadata_db_path", None)
        self._metadata_kv: KVClientBase | None = kwargs.get("metadata_kv", None)
        self._owns_metadata_kv = self._metadata_kv is not None and kwargs.get("metadata_kv", None) is not None
        self._is_view = False
        self._metadata_lock = threading.RLock()
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        if self._auto_start:
            self.start()

    @abstractmethod
    def start(self) -> Self:
        '''Start the client. Called automatically if *auto_start* is ``True`` (default).'''
        ...

    async def put_bytes(self, data: bytes, *, object_name: str, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        '''Store raw bytes as a new or replacement object.

        Args:
            data: Raw byte content to store.
            object_name: Unique name / path for the object within the namespace.
            metadata: Optional key-value metadata to attach.
            expire: Optional TTL in seconds or absolute UNIX timestamp.
            content_type: MIME type; inferred from *object_name* when ``None``.

        Returns:
            :class:`OBS_Object` describing the stored object.
        '''
        return await self._put_bytes(
            object_name,
            data,
            metadata=metadata,
            expire=expire,
            content_type=content_type,
        )

    @abstractmethod
    async def put_file(self, source: str | Path, *, object_name: str | None = None, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        '''Store a local file as a new or replacement object.

        Args:
            source: Path to the local file to upload.
            object_name: Target name in the store; defaults to the file\'s
                basename when ``None``.
            metadata: Optional key-value metadata to attach.
            expire: Optional TTL in seconds or absolute UNIX timestamp.
            content_type: MIME type; inferred from *source* when ``None``.

        Returns:
            :class:`OBS_Object` describing the stored object.
        '''
        ...

    async def get_bytes(self, object_name: str) -> bytes | None:
        '''Retrieve the raw bytes of an object.

        Returns:
            Raw bytes of the stored object, or ``None`` if not found / expired.
        '''
        return await self._get_bytes(object_name)

    async def put(self, data: ObjectDataSource, *, object_name: str, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        '''Default streaming put: spills chunks to a temp file then delegates to :meth:`put_file`.

        Subclasses may override for backend-native streaming (avoiding the temp-file hop).
        '''
        if isinstance(data, (bytes, bytearray, memoryview)):
            return await self.put_bytes(bytes(data), object_name=object_name, metadata=metadata, expire=expire, content_type=content_type)
        import aiofiles  # type: ignore
        with tempfile.NamedTemporaryFile(delete=False) as tmp_sync:
            tmp_path = Path(tmp_sync.name)
        try:
            async with aiofiles.open(tmp_path, 'wb') as tmp:
                async for chunk in get_async_generator(data):
                    await tmp.write(chunk)
            return await self.put_file(tmp_path, object_name=object_name, metadata=metadata, expire=expire, content_type=content_type)
        finally:
            tmp_path.unlink(missing_ok=True)

    async def get(self, object_name: str, *, chunk_size: int = 65536) -> AsyncGenerator[bytes, None]:
        data = await self.get_bytes(object_name)
        if data is None:
            return
        for index in range(0, len(data), max(1, chunk_size)):
            yield data[index:index + max(1, chunk_size)]

    @abstractmethod
    async def _put_bytes(
        self,
        object_name: str,
        data: bytes | bytearray | memoryview,
        *,
        metadata: ObjectMetadataMapping | None = None,
        expire: float | int | None = None,
        content_type: str | None = None,
    ) -> OBS_Object:
        '''Store object bytes and return metadata.'''
        ...

    @abstractmethod
    async def _get_bytes(self, object_name: str) -> bytes | None:
        '''Retrieve object bytes.'''
        ...

    async def _iter_metadata(
        self,
        *,
        name: str | None = None,
        path_prefix: str | None = None,
        created_from: datetime | float | None = None,
        created_to: datetime | float | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        metadata: ObjectMetadataMapping | None = None,
    ) -> AsyncGenerator[OBS_Object, None]:
        _ = (name, path_prefix, created_from, created_to, min_size, max_size, metadata)
        self._ensure_metadata_store()
        metadata_kv = self._metadata_kv
        if metadata_kv is None:
            return
        prefix = self._meta_prefix("")
        for key in await metadata_kv.keys(prefix=prefix):
            meta = await metadata_kv.get(key)
            if meta is None:
                continue
            meta = cast(ObjectMetadata, meta)
            expire_at = meta.get("expire_at")
            object_name = str(meta.get("path") or meta.get("object_id") or key.removeprefix(f"{self._namespace}:meta:"))
            if self._folder_prefix and object_name and not object_name.startswith(self._folder_prefix):
                continue
            if expire_at is not None and expire_at <= _now_ts():
                await self.delete(self._logical_object_name(object_name))
                continue
            yield self._present_metadata(meta)

    @abstractmethod
    async def _delete_object(self, object_name: str) -> bool:
        '''Delete the stored object bytes and metadata.'''
        ...

    async def list_objects(self, prefix: str = "") -> AsyncGenerator[str, None]:
        normalized_prefix = _normalize_object_name(prefix) if prefix else ""
        async for item in self.list_metadata():
            path = str(item.path or item.object_id or "")
            if normalized_prefix and not path.startswith(normalized_prefix):
                continue
            yield path

    async def delete(self, object_name: str) -> bool:
        '''Delete the named object.

        Returns:
            ``True`` if the object existed and was removed, ``False`` otherwise.
        '''
        return await self._delete_object(object_name)

    @abstractmethod
    async def cleanup(self, *, force: bool = False) -> int:
        '''Remove all expired objects.

        Args:
            force: When ``True``, clean up regardless of the internal throttle.

        Returns:
            Number of objects removed.
        '''
        ...

    async def set_expire(self, object_name: str, expire: float | int | None) -> bool:
        meta = await self._get_metadata(object_name)
        if meta is None:
            return False
        meta.expire_at = _normalize_expire_at(expire)
        await self._set_metadata(object_name, meta)
        return True

    async def get_expire(self, object_name: str) -> float | None:
        meta = await self._get_metadata(object_name)
        if meta is None:
            return None
        ttl = _ttl_from_expire_at(meta.expire_at)
        if ttl == 0.0:
            await self.delete(object_name)
        return ttl

    async def search(
        self,
        *,
        name: str | None = None,
        path_prefix: str | None = None,
        created_from: datetime | float | None = None,
        created_to: datetime | float | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        metadata: ObjectMetadataMapping | None = None,
    ) -> AsyncGenerator[OBS_Object, None]:
        async for item in self._iter_metadata():
            if name and name not in item.name:
                continue
            if path_prefix and not item.path.startswith(path_prefix):
                continue
            created_at = float(item.created_at or item.accessed_at or 0.0)
            if created_from is not None and created_at < _to_ts(created_from):
                continue
            if created_to is not None and created_at > _to_ts(created_to):
                continue
            size = int(item.size)
            if min_size is not None and size < min_size:
                continue
            if max_size is not None and size > max_size:
                continue
            meta = item.metadata or {}
            if metadata:
                if any(meta.get(k) != v for k, v in metadata.items()):
                    continue
            yield item

    async def list_metadata(self) -> AsyncGenerator[OBS_Object, None]:
        async for item in self._iter_metadata():
            yield item

    def _ensure_metadata_store(self) -> None:
        if self._metadata_kv is not None:
            return
        if self._metadata_db is not None:
            metadata_db = self._metadata_db
            if isinstance(metadata_db, str):
                from .config import StorageConfig
                metadata_name = str(metadata_db or "").strip()
                section = StorageConfig.Global().kv
                resolved_name = metadata_name or "default"
                if resolved_name != "default":
                    has_named_client = (
                        resolved_name in type(section).model_fields and getattr(section, resolved_name, None) is not None
                    ) or resolved_name in section.extra
                    if not has_named_client:
                        raise ValueError(f"Unknown KV metadata store client: {resolved_name}")
                self._metadata_kv = section.get_client(resolved_name)
                self._owns_metadata_kv = False
            elif hasattr(metadata_db, "create_client"):
                self._metadata_kv = metadata_db.create_client()
                self._owns_metadata_kv = True
            else:
                raise TypeError(f"Unsupported metadata_db value: {type(metadata_db).__name__}")
        elif self._metadata_db_path is not None:
            self._metadata_kv = SQLiteKVClient(
                db_path=self._metadata_db_path,
                namespace=f"{self._namespace}:objects",
                cleanup_interval=self._cleanup_interval,
                max_size=self._max_size,
                default_expire=self._default_expire,
            )
            self._owns_metadata_kv = True
        else:
            self._metadata_kv = cast(KVClientBase, KVClientBase.Default())
            self._owns_metadata_kv = False
        metadata_kv = self._metadata_kv
        if metadata_kv is not None and not metadata_kv.started:
            metadata_kv.start()

    def close(self) -> None:
        if self._is_view:
            self._mark_stopped()
            return
        cleanup_task = self._cleanup_task
        self._cleanup_task = None
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
        metadata_kv = self._metadata_kv
        owns_metadata_kv = bool(getattr(self, '_owns_metadata_kv', False))
        self._metadata_kv = None
        self._owns_metadata_kv = False
        with self._metadata_lock:
            self._cleanup_async_locks.clear()
        self._mark_stopped()
        if not owns_metadata_kv or metadata_kv is None:
            return
        try:
            close_func = getattr(metadata_kv, 'close', None)
            if callable(close_func):
                close_func()
        except Exception as e:
            _logger.warning('%s.close() failed to close metadata KV: %s', self.__class__.__name__, e)

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = (threading.get_ident(), id(asyncio.get_running_loop()))
        with self._metadata_lock:
            lock = self._cleanup_async_locks.get(owner)
            if lock is None:
                lock = asyncio.Lock()
                self._cleanup_async_locks[owner] = lock
            return lock

    def _schedule_cleanup(self) -> None:
        if not self._should_cleanup():
            return
        task = self._cleanup_task
        if task is not None and not task.done():
            return
        self._cleanup_task = asyncio.create_task(self._background_cleanup())

    async def _background_cleanup(self) -> None:
        try:
            await self.cleanup()
        except Exception:
            pass

    def _meta_prefix(self, object_name: str) -> str:
        full_name = self._resolve_object_name(object_name) if object_name else self._folder_prefix
        return f"{self._namespace}:meta:{full_name}"

    def _resolve_object_name(self, object_name: str) -> str:
        normalized = _normalize_object_name(object_name)
        if self._folder_prefix:
            if normalized.startswith(self._folder_prefix):
                return normalized
            return f"{self._folder_prefix}{normalized}"
        return normalized

    def _logical_object_name(self, object_name: str) -> str:
        if self._folder_prefix and object_name.startswith(self._folder_prefix):
            return object_name[len(self._folder_prefix):]
        return object_name

    def _present_metadata(self, metadata: ObjectMetadata | OBS_Object) -> OBS_Object:
        payload = metadata.to_metadata_dict() if isinstance(metadata, OBS_Object) else dict(metadata)
        full_path = str(payload.get("path") or payload.get("object_id") or "")
        logical_path = self._logical_object_name(full_path)
        payload["path"] = logical_path
        payload["object_id"] = logical_path
        payload["name"] = Path(logical_path).name if logical_path else ""
        return OBS_Object.model_validate({
            **payload,
            "storage_name": getattr(self, "_name", "default") or "default",
        }).bind_client(self)

    def open_folder(self, folder: str | None) -> Self:
        normalized = _normalize_folder_prefix(folder)
        if not normalized:
            return self
        clone = copy.copy(self)
        clone._folder_prefix = _join_folder_prefix(self._folder_prefix, normalized)
        clone._is_view = True
        clone._owns_metadata_kv = False
        return clone

    async def _set_metadata(self, object_name: str, metadata: ObjectMetadata | OBS_Object) -> None:
        self._ensure_metadata_store()
        metadata_kv = self._metadata_kv
        if metadata_kv is None:
            raise RuntimeError("Metadata KV store is not initialized.")
        resolved_name = self._resolve_object_name(object_name)
        payload = metadata.to_metadata_dict() if isinstance(metadata, OBS_Object) else dict(metadata)
        payload["path"] = resolved_name
        payload["object_id"] = resolved_name
        payload["name"] = Path(resolved_name).name
        await metadata_kv.set(self._meta_prefix(object_name), payload)

    async def _get_metadata(self, object_name: str) -> OBS_Object | None:
        self._ensure_metadata_store()
        metadata_kv = self._metadata_kv
        if metadata_kv is None:
            return None
        meta = await metadata_kv.get(self._meta_prefix(object_name))
        if meta is None:
            return None
        if not isinstance(meta, dict):
            return None
        expire_at = meta.get("expire_at")
        if expire_at is not None and expire_at <= _now_ts():
            await self.delete(object_name)
            return None
        return self._present_metadata(cast(ObjectMetadata, meta))

    async def _delete_metadata(self, object_name: str) -> bool:
        self._ensure_metadata_store()
        metadata_kv = self._metadata_kv
        if metadata_kv is None:
            return False
        return await metadata_kv.delete(self._meta_prefix(object_name))

    def _make_metadata(self, *, object_name: str, size: int, metadata: ObjectMetadataMapping | None, expire: float | int | None, content_type: str | None = None) -> ObjectMetadata:
        now_ts = _now_ts()
        return {
            "object_id": object_name,
            "name": Path(object_name).name,
            "path": object_name,
            "size": int(size),
            "content_type": content_type,
            "created_at": now_ts,
            "updated_at": now_ts,
            "accessed_at": now_ts,
            "expire_at": _normalize_expire_at(expire if expire is not None else self._default_expire),
            "metadata": dict(metadata or {}),
        }


class LocalObjectClient(ObjectClientBase, type="local"):
    def __init__(self, **kwargs: Unpack[LocalObjectClientInitParams]) -> None:
        self._root_path = _ensure_dir(kwargs.get("root_path") or _default_local_storage_root("object", "files"))
        if kwargs.get("metadata_db", None) is None and kwargs.get("metadata_db_path", None) is None:
            kwargs = {
                **kwargs,
                "metadata_db_path": self._root_path.parent / f".{self._root_path.name}_meta.sqlite3",
            }
        super().__init__(**kwargs)

    def start(self) -> Self:
        _ensure_dir(self._root_path)
        self._ensure_metadata_store()
        self._mark_started()
        return self

    def _full_path(self, object_name: str) -> Path:
        target = (self._root_path / object_name).resolve()
        if not target.is_relative_to(self._root_path):
            raise ValueError(f"Path traversal detected: {object_name!r} resolves outside root.")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    async def _put_bytes(self, object_name: str, data: bytes | bytearray | memoryview, *, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        if not self._started:
            self.start()
        import aiofiles  # type: ignore
        resolved_name = self._resolve_object_name(object_name)
        target = self._full_path(resolved_name)
        raw_data = bytes(data)
        async with aiofiles.open(target, "wb") as fh:
            await fh.write(raw_data)
        meta = self._make_metadata(object_name=resolved_name, size=len(raw_data), metadata=metadata, expire=expire, content_type=content_type or mimetypes.guess_type(target.name)[0])
        await self._set_metadata(object_name, meta)
        self._schedule_cleanup()
        return self._present_metadata(meta)

    async def put_file(self, source: str | Path, *, object_name: str | None = None, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        import aiofiles  # type: ignore
        source_path = Path(source).expanduser().resolve()
        name = object_name or source_path.name
        resolved_name = self._resolve_object_name(name)
        target = self._full_path(resolved_name)
        total_size = 0
        async with aiofiles.open(source_path, "rb") as src, aiofiles.open(target, "wb") as dst:
            while chunk := await src.read(65536):
                await dst.write(chunk)
                total_size += len(chunk)
        meta = self._make_metadata(object_name=resolved_name, size=total_size, metadata=metadata, expire=expire, content_type=content_type or mimetypes.guess_type(target.name)[0])
        await self._set_metadata(name, meta)
        self._schedule_cleanup()
        return self._present_metadata(meta)

    async def get(self, object_name: str, *, chunk_size: int = 65536) -> AsyncGenerator[bytes, None]:
        import aiofiles  # type: ignore
        meta = await self._get_metadata(object_name)
        if meta is None:
            return
        target = self._full_path(self._resolve_object_name(object_name))
        if not target.exists():
            await self._delete_metadata(object_name)
            return
        async with aiofiles.open(target, "rb") as fh:
            while chunk := await fh.read(max(1, chunk_size)):
                yield chunk

    async def put(self, data: ObjectDataSource, *, object_name: str, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        """Stream-aware put: writes chunks directly to disk via aiofiles."""
        if isinstance(data, (bytes, bytearray, memoryview)):
            return await self.put_bytes(bytes(data), object_name=object_name, metadata=metadata, expire=expire, content_type=content_type)
        import aiofiles  # type: ignore
        if not self._started:
            self.start()
        resolved_name = self._resolve_object_name(object_name)
        target = self._full_path(resolved_name)
        total_size = 0
        async with aiofiles.open(target, "wb") as fh:
            async for chunk in get_async_generator(data):
                await fh.write(chunk)
                total_size += len(chunk)
        meta = self._make_metadata(object_name=resolved_name, size=total_size, metadata=metadata, expire=expire, content_type=content_type or mimetypes.guess_type(target.name)[0])
        await self._set_metadata(object_name, meta)
        self._schedule_cleanup()
        return self._present_metadata(meta)

    async def _get_bytes(self, object_name: str) -> bytes | None:
        import aiofiles  # type: ignore
        meta = await self._get_metadata(object_name)
        if meta is None:
            return None
        target = self._full_path(self._resolve_object_name(object_name))
        if not target.exists():
            await self._delete_metadata(object_name)
            return None
        async with aiofiles.open(target, "rb") as fh:
            return await fh.read()

    async def _delete_object(self, object_name: str) -> bool:
        target = self._full_path(self._resolve_object_name(object_name))
        removed = False
        if target.exists():
            await asyncio.to_thread(target.unlink)
            removed = True
        await self._delete_metadata(object_name)
        return removed

    async def cleanup(self, *, force: bool = False) -> int:
        if not await self._should_cleanup_async(force=force):
            return 0
        async with self._cleanup_async_lock():
            if not await self._should_cleanup_async(force=force):
                return 0
            removed = 0
            total_size = 0
            live_items: list[tuple[str, int, float]] = []
            expired_names: list[str] = []
            orphaned_names: list[str] = []
            async for meta in self.list_metadata():
                object_name = meta.path
                expire_at = meta.expire_at
                target = self._full_path(self._resolve_object_name(object_name))
                if expire_at is not None and expire_at <= _now_ts():
                    expired_names.append(object_name)
                    continue
                if not target.exists():
                    orphaned_names.append(object_name)
                    continue
                size = int(meta.size)
                total_size += size
                live_items.append((object_name, size, float(meta.accessed_at or 0.0)))
            for name in expired_names:
                if await self.delete(name):
                    removed += 1
            for name in orphaned_names:
                await self._delete_metadata(name)
            if self._max_size is not None and total_size > self._max_size:
                target_size = max(0, int(self._max_size * 0.9))
                for object_name, size, _ in sorted(live_items, key=lambda item: item[2]):
                    if total_size <= target_size:
                        break
                    if await self.delete(object_name):
                        total_size -= size
                        removed += 1
            await self._mark_cleanup_async()
            return removed


class MinIOObjectClient(ObjectClientBase, type="minio"):
    def __init__(self, **kwargs: Unpack[MinIOObjectClientInitParams]) -> None:
        self._endpoint = kwargs.get("endpoint", "127.0.0.1:9000")
        self._access_key = kwargs.get("access_key", "minioadmin")
        self._secret_key = kwargs.get("secret_key", "minioadmin")
        self._bucket = str(kwargs.get("bucket", "app-backend") or "app-backend").strip().lower()
        self._secure = bool(kwargs.get("secure", False))
        self._region = kwargs.get("region", None)
        self._client: "_AsyncMinioClient | None" = None
        self._bucket_ensured = False
        self._bucket_ensure_lock = asyncio.Lock()
        super().__init__(**kwargs)

    def start(self) -> Self:
        if self._started:
            return self
        from miniopy_async.api import Minio
        self._client = Minio(self._endpoint, access_key=self._access_key, secret_key=self._secret_key, secure=self._secure, region=self._region)
        self._bucket_ensured = False
        self._ensure_metadata_store()
        self._mark_started()
        return self

    async def _ensure_bucket(self) -> None:
        if self._bucket_ensured:
            return
        async with self._bucket_ensure_lock:
            if self._bucket_ensured:
                return
            assert self._client is not None
            if not await self._client.bucket_exists(self._bucket):
                try:
                    await self._client.make_bucket(self._bucket)
                except Exception:
                    if not await self._client.bucket_exists(self._bucket):
                        raise
            self._bucket_ensured = True

    async def aclose(self) -> None:
        if self._is_view:
            self._mark_stopped()
            return
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client._session.close()  # type: ignore[union-attr]
            except Exception as e:
                _logger.warning('MinIOObjectClient.aclose() failed for bucket %s: %s', self._bucket, e)
        super().close()

    def close(self) -> None:
        if self._is_view:
            self._mark_stopped()
            return
        client = self._client
        self._client = None
        if client is not None:
            try:
                _run_async_in_sync(client._session.close)  # type: ignore[union-attr]
            except Exception as e:
                _logger.warning('MinIOObjectClient.close() failed for bucket %s: %s', self._bucket, e)
        super().close()

    async def _put_bytes(self, object_name: str, data: bytes | bytearray | memoryview, *, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        if not self._started:
            self.start()
        await self._ensure_bucket()
        assert self._client is not None

        resolved_name = self._resolve_object_name(object_name)
        raw_data = bytes(data)
        stream = BytesIO(raw_data)
        await self._client.put_object(self._bucket, resolved_name, stream, length=len(raw_data), content_type=content_type or "application/octet-stream")
        meta = self._make_metadata(object_name=resolved_name, size=len(raw_data), metadata=metadata, expire=expire, content_type=content_type)
        await self._set_metadata(object_name, meta)
        self._schedule_cleanup()
        return self._present_metadata(meta)

    async def put_file(self, source: str | Path, *, object_name: str | None = None, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        if not self._started:
            self.start()
        await self._ensure_bucket()
        assert self._client is not None
        source_path = Path(source).expanduser().resolve()
        name = object_name or source_path.name
        resolved_name = self._resolve_object_name(name)
        await self._client.fput_object(self._bucket, resolved_name, str(source_path), content_type=content_type or mimetypes.guess_type(source_path.name)[0] or "application/octet-stream")
        meta = self._make_metadata(object_name=resolved_name, size=source_path.stat().st_size, metadata=metadata, expire=expire, content_type=content_type or mimetypes.guess_type(source_path.name)[0])
        await self._set_metadata(name, meta)
        self._schedule_cleanup()
        return self._present_metadata(meta)

    async def get(self, object_name: str, *, chunk_size: int = 65536) -> AsyncGenerator[bytes, None]:
        if not self._started:
            self.start()
        await self._ensure_bucket()
        assert self._client is not None
        meta = await self._get_metadata(object_name)
        if meta is None:
            return
        response = await self._client.get_object(self._bucket, self._resolve_object_name(object_name))
        try:
            async for chunk in response.content.iter_chunked(max(1, chunk_size)):
                yield chunk
        finally:
            response.close()

    async def put(self, data: ObjectDataSource, *, object_name: str, metadata: ObjectMetadataMapping | None = None, expire: float | int | None = None, content_type: str | None = None) -> OBS_Object:
        """Stream-aware put: spills to temp file then uses async fput_object."""
        if isinstance(data, (bytes, bytearray, memoryview)):
            return await self.put_bytes(bytes(data), object_name=object_name, metadata=metadata, expire=expire, content_type=content_type)
        if not self._started:
            self.start()
        await self._ensure_bucket()
        assert self._client is not None
        resolved_name = self._resolve_object_name(object_name)

        import aiofiles  # type: ignore
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp_sync:
                tmp_path = Path(tmp_sync.name)
            total_size = 0
            async with aiofiles.open(tmp_path, "wb") as tmp:
                async for chunk in get_async_generator(data):
                    await tmp.write(chunk)
                    total_size += len(chunk)
            await self._client.fput_object(
                self._bucket, resolved_name, str(tmp_path),
                content_type=content_type or mimetypes.guess_type(resolved_name)[0] or "application/octet-stream",
            )
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        meta = self._make_metadata(object_name=resolved_name, size=total_size, metadata=metadata, expire=expire, content_type=content_type)
        await self._set_metadata(object_name, meta)
        self._schedule_cleanup()
        return self._present_metadata(meta)

    async def _get_bytes(self, object_name: str) -> bytes | None:
        if not self._started:
            self.start()
        await self._ensure_bucket()
        assert self._client is not None
        meta = await self._get_metadata(object_name)
        if meta is None:
            return None
        response = await self._client.get_object(self._bucket, self._resolve_object_name(object_name))
        try:
            return await response.content.read()
        finally:
            response.close()

    async def _delete_object(self, object_name: str) -> bool:
        if not self._started:
            self.start()
        await self._ensure_bucket()
        assert self._client is not None
        try:
            await self._client.remove_object(self._bucket, self._resolve_object_name(object_name))
            removed = True
        except Exception:
            removed = False
        await self._delete_metadata(object_name)
        return removed

    async def cleanup(self, *, force: bool = False) -> int:
        if not await self._should_cleanup_async(force=force):
            return 0
        async with self._cleanup_async_lock():
            if not await self._should_cleanup_async(force=force):
                return 0
            removed = 0
            total_size = 0
            live_items: list[tuple[str, int, float]] = []
            expired_names: list[str] = []
            async for meta in self.list_metadata():
                object_name = meta.path
                expire_at = meta.expire_at
                if expire_at is not None and expire_at <= _now_ts():
                    expired_names.append(object_name)
                    continue
                size = int(meta.size)
                total_size += size
                live_items.append((object_name, size, float(meta.accessed_at or 0.0)))
            for name in expired_names:
                if await self.delete(name):
                    removed += 1
            if self._max_size is not None and total_size > self._max_size:
                target_size = max(0, int(self._max_size * 0.9))
                for object_name, size, _ in sorted(live_items, key=lambda item: item[2]):
                    if total_size <= target_size:
                        break
                    if await self.delete(object_name):
                        total_size -= size
                        removed += 1
            await self._mark_cleanup_async()
            return removed


def _to_ts(value: datetime | float) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def _normalize_object_name(path: str) -> str:
    raw = str(path or "").replace("\\", "/").strip().lstrip("/")
    if not raw:
        raise ValueError("Object path is required.")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise ValueError(f"Invalid object path: {path!r}")
    normalized = "/".join(parts)
    if not normalized:
        raise ValueError("Object path is required.")
    return normalized


def _normalize_folder_prefix(folder: str | None) -> str:
    if folder is None:
        return ""
    raw = str(folder).replace("\\", "/").strip().lstrip("/")
    if not raw:
        return ""
    return _normalize_object_name(raw.rstrip("/")) + "/"


def _join_folder_prefix(base: str, child: str | None) -> str:
    child_normalized = _normalize_folder_prefix(child)
    if not base:
        return child_normalized
    if not child_normalized:
        return base
    return base + child_normalized


__all__ = [
    "LocalObjectClient",
    "LocalObjectClientInitParams",
    "MinIOObjectClient",
    "MinIOObjectClientInitParams",
    "OBS_Object",
    "ObjectClientBase",
    "ObjectClientInitParams",
    "ObjectDataSource",
    "ObjectMetadata",
]
