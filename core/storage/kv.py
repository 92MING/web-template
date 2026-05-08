import io
import os
import hashlib
import pickle
import inspect
import asyncio
import logging
import threading
import base64 as _b64
import json as _json
import httpx as _httpx

from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Self, TYPE_CHECKING, TypedDict, overload
from typing_extensions import Unpack

if TYPE_CHECKING:
    import pica
    from redis.asyncio import Redis as _AioRedis

from ..utils.concurrent_utils import run_any_func
from ..utils.concurrent_utils.file_lock import FileCrossProcessLock
from ..utils.type_utils import deserialize, recursive_dump_to_basic_types
from .base import (
    StorageClientBase,
    StorageClientInitParams,
    _default_local_storage_root,
    _ensure_parent_dir,
    _in_uvicorn_process,
    _normalize_expire_at,
    _now_ts,
    _ttl_from_expire_at,
)

_logger = logging.getLogger(__name__)


def _async_owner_key() -> tuple[int, int]:
    return (threading.get_ident(), id(asyncio.get_running_loop()))


class _KVEntry(TypedDict):
    v: object
    e: float | None
    a: float
    s: int


class _EtcdMetaRecord(TypedDict, total=False):
    size: int
    accessed_at: float


class _EtcdEmptyRequest(TypedDict):
    pass


class _EtcdPutRequest(TypedDict, total=False):
    key: str
    value: str
    lease: str


class _EtcdRangeRequest(TypedDict, total=False):
    key: str
    range_end: str


class _EtcdDeleteRangeRequest(TypedDict):
    key: str


class _EtcdLeaseGrantRequest(TypedDict):
    TTL: int
    ID: int


class _EtcdLeaseTimeToLiveRequest(TypedDict):
    ID: str


class _EtcdKVRow(TypedDict, total=False):
    key: str
    value: str
    lease: int


class _EtcdRangeResponse(TypedDict, total=False):
    kvs: list[_EtcdKVRow]


class _EtcdDeleteRangeResponse(TypedDict, total=False):
    deleted: int


class _EtcdLeaseGrantResponse(TypedDict, total=False):
    ID: int
    TTL: int


class _EtcdLeaseTimeToLiveResponse(TypedDict, total=False):
    TTL: int


class _EtcdVersionResponse(TypedDict, total=False):
    etcdserver: str


type _EtcdRequest = (
    _EtcdEmptyRequest
    | _EtcdPutRequest
    | _EtcdRangeRequest
    | _EtcdDeleteRangeRequest
    | _EtcdLeaseGrantRequest
    | _EtcdLeaseTimeToLiveRequest
)

# ---------------------------------------------------------------------------
# Restricted unpickler to mitigate arbitrary-code-execution via pickle.loads
# ---------------------------------------------------------------------------
_SAFE_PICKLE_MODULES: frozenset[str] = frozenset({
    "builtins", "collections", "datetime", "decimal",
    "fractions", "numbers", "operator", "functools",
    "re", "uuid", "pathlib", "enum",
    "collections.abc", "types",
})


class _RestrictedUnpickler(pickle.Unpickler):
    """Only allow classes from a known-safe set of modules."""

    def find_class(self, module: str, name: str) -> object:
        if module in _SAFE_PICKLE_MODULES:
            return super().find_class(module, name)
        # Allow numpy/pandas scalars that are common in data pipelines
        if module.startswith(("numpy", "pandas")):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"Restricted unpickle: {module}.{name} is not in the allow-list"
        )

def _safe_pickle_loads(data: bytes) -> object:
    """Deserialize *data* using the restricted unpickler.

    Raises ``pickle.UnpicklingError`` if the payload contains classes outside
    the allow-list.  The previous fallback to unrestricted ``pickle.loads``
    has been **removed** to prevent arbitrary-code-execution.
    """
    try:
        return _RestrictedUnpickler(io.BytesIO(data)).load()
    except pickle.UnpicklingError as exc:
        _logger.warning("Restricted unpickle rejected payload: %s", exc)
        raise

class KVClientInitParams(StorageClientInitParams, total=False):
    namespace: str
    default_expire: float | None

class SQLiteKVClientInitParams(KVClientInitParams, total=False):
    db_path: str | Path
    start_cleanup_thread: bool

class RedisKVClientInitParams(KVClientInitParams, total=False):
    url: str
    prefix: str
    db: int
    decode_responses: bool

class EtcdKVClientInitParams(KVClientInitParams, total=False):
    host: str
    port: int
    protocol: str
    prefix: str
    timeout: float | int | None
    api_path: str | None

class KVClientBase(StorageClientBase, ABC, storage_kind="kv"):

    def __init__(self, _parent: "KVClientBase | None" = None, _parent_key_prefix: str = "", **kwargs: Unpack[KVClientInitParams]) -> None:
        super().__init__(**kwargs)
        self._parent = _parent
        self._parent_key_prefix = _parent_key_prefix
        self._namespace = kwargs.get("namespace", "default")
        self._default_expire = kwargs.get("default_expire", None)
        if self._auto_start:
            self.start()

    @abstractmethod
    def start(self) -> Self:
        '''Start the client. Called automatically if *auto_start* is ``True`` (default).'''
        ...
        
    def open_namespace(self, namespace: str, splitter: str=':') -> Self:
        child_namespace = f"{self._namespace}{splitter}{namespace}" if self._namespace else str(namespace)
        child_kwargs = self.metadata()
        child_kwargs.pop("started", None)
        child_kwargs["namespace"] = child_namespace
        child_kwargs["auto_start"] = bool(self.started or child_kwargs.get("auto_start", False))
        return self.__class__(
            _parent=self,
            _parent_key_prefix=f"{namespace}{splitter}",
            **child_kwargs,
        )

    def _child_key(self, key: str) -> str:
        return f"{self._parent_key_prefix}{key}" if self._parent is not None else key

    async def set(self, key: str, value: object, *, expire: float | int | None = None) -> None:
        '''Persist *value* under *key*.

        Args:
            key: Storage key.
            value: Arbitrary pickle-serializable object.
            expire: Optional TTL in seconds from now (or absolute UNIX timestamp
                when > current time by more than 1e9).
        '''
        if self._parent is not None:
            await self._parent.set(self._child_key(key), value, expire=expire)
            return
        await self._set_value(key, value, expire=expire)

    @overload
    async def get(self, key: str, default: object = None) -> object: ...
    @overload
    async def get[T](self, key: str, default: object = None, *, target_type: type[T]) -> T: ...
    async def get(self, key: str, default: object = None, *, target_type: type | None = None) -> object:
        '''Retrieve the value stored under *key*, or *default* if missing / expired.

        Args:
            key: Storage key.
            default: Fallback value when the key does not exist.
            target_type: When given, attempts to deserialize the stored value into this
                type using ``utils.type_utils.deserialize``.  If deserialization fails
                the raw stored value is returned instead.

        Returns:
            Deserialized value (optionally cast to *target_type*) or *default*.
        '''
        if self._parent is not None:
            return await self._parent.get(self._child_key(key), default=default, target_type=target_type)
        value = await self._get_value(key, default=default)
        if target_type is None or value is default:
            return value
        try:
            json_str = value if isinstance(value, str) else _json.dumps(value)
            return deserialize(json_str, target_type)
        except Exception:
            return value

    @abstractmethod
    async def set_expire(self, key: str, expire: float | int | None) -> bool:
        '''Update the expiry of an existing key without changing its value.

        Args:
            key: Storage key.
            expire: New TTL in seconds, absolute UNIX timestamp, or ``None`` to
                make the key permanent.

        Returns:
            ``True`` if the key existed and was updated, ``False`` otherwise.
        '''
        ...

    @abstractmethod
    async def get_expire(self, key: str) -> float | None:
        '''Return the absolute UNIX expiry timestamp for *key*, or ``None`` if
        the key does not exist or has no expiry.
        '''
        ...

    async def mget(self, keys: list[str], default: object = None) -> list[object]:
        '''Batch retrieve values for *keys*. Returns a list aligned with *keys*.
        Falls back to asyncio.gather if the backend does not implement true batching.'''
        if self._parent is not None:
            parent_keys = [self._child_key(k) for k in keys]
            return await self._parent.mget(parent_keys, default=default)
        raw_batch = await self._mget_values(keys, default=default)
        results: list[object] = []
        for value in raw_batch:
            if value is default:
                results.append(default)
                continue
            try:
                json_str = value if isinstance(value, str) else _json.dumps(value)
                results.append(deserialize(json_str, type(None)))
            except Exception:
                results.append(value)
        return results

    async def raw_mget(self, keys: list[str], default: object = None) -> list[object]:
        '''Batch retrieve raw storage-layer values (skip target_type deserialization).'''
        if self._parent is not None:
            parent_keys = [self._child_key(k) for k in keys]
            return await self._parent.raw_mget(parent_keys, default=default)
        return await self._mget_values(keys, default=default)

    async def mttl(self, keys: list[str]) -> list[float | None]:
        '''Batch retrieve TTLs for *keys*. Returns a list aligned with *keys*.'''
        if self._parent is not None:
            parent_keys = [self._child_key(k) for k in keys]
            return await self._parent.mttl(parent_keys)
        return await self._mget_expires(keys)

    async def _mget_values(self, keys: list[str], default: object = None) -> list[object]:
        '''Fallback: gather single-gets. Subclasses may override for true batch.'''
        return await asyncio.gather(*[self._get_value(k, default=default) for k in keys])

    async def _mget_expires(self, keys: list[str]) -> list[float | None]:
        '''Fallback: gather single-expire queries. Subclasses may override.'''
        return await asyncio.gather(*[self.get_expire(k) for k in keys])

    async def delete(self, key: str) -> bool:
        '''Delete *key* and its value.

        Returns:
            ``True`` if the key existed and was removed, ``False`` otherwise.
        '''
        if self._parent is not None:
            return await self._parent.delete(self._child_key(key))
        return await self._delete_value(key)

    @abstractmethod
    async def cleanup(self, *, force: bool = False) -> int:
        '''Remove all expired entries.

        Args:
            force: When ``True``, clean up regardless of the internal throttle.

        Returns:
            Number of entries removed.
        '''
        ...

    async def keys(self, prefix: str | None = None) -> list[str]:
        '''List all non-expired keys.

        Args:
            prefix: Optional prefix filter; only keys that start with *prefix*
                are included.

        Returns:
            Sorted list of matching key strings.
        '''
        if self._parent is not None:
            parent_prefix = self._parent_key_prefix if prefix is None else f"{self._parent_key_prefix}{prefix}"
            keys = await self._parent.keys(prefix=parent_prefix)
            return [key[len(self._parent_key_prefix):] for key in keys if key.startswith(self._parent_key_prefix)]
        return await self._list_keys(prefix=prefix)

    @abstractmethod
    async def _set_value(self, key: str, value: object, *, expire: float | int | None = None) -> None:
        '''Persist a value under *key*.'''
        ...

    @abstractmethod
    async def _get_value(self, key: str, default: object = None) -> object:
        '''Retrieve the stored value, or *default* if missing / expired.'''
        ...

    @abstractmethod
    async def _list_keys(self, prefix: str | None = None) -> list[str]:
        '''List matching keys.'''
        ...

    @abstractmethod
    async def _delete_value(self, key: str) -> bool:
        '''Delete the stored value under *key*.'''
        ...


class SQLiteKVClient(KVClientBase, type="sqlite"):
    """Local SQLite KV client backed by ``pica.Stash``.

    Each entry is stored as a metadata dict so that TTL and LRU eviction can be
    implemented on top of the bare key/value schema.  The dict has the following
    fields:

    * ``v`` – the actual value object.
    * ``e`` – absolute UNIX expiry timestamp (``float``) or ``None``.
    * ``a`` – last-accessed timestamp (used for LRU eviction).
    * ``s`` – serialized size in bytes (used for max-total-size enforcement).
    """

    __CleanupThreads__: ClassVar[dict[tuple[int, str], threading.Thread]] = {}

    def __init__(self, _parent: KVClientBase | None = None, _parent_key_prefix: str = "", **kwargs: Unpack[SQLiteKVClientInitParams]) -> None:
        self._db_path = _ensure_parent_dir(
            kwargs.get("db_path") or (_default_local_storage_root("kv") / "local_kv.sqlite3")
        )
        self._start_cleanup_thread = bool(kwargs.get("start_cleanup_thread", False))
        self._stashes: dict[int, "pica.Stash"] = {}
        self._stash_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._closing = False
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        lock_name = f"sqlite-kv-{hashlib.sha1(str(self._db_path).encode('utf-8')).hexdigest()[:16]}"
        self._process_lock = FileCrossProcessLock(lock_name, default_timeout=10)
        super().__init__(_parent=_parent, _parent_key_prefix=_parent_key_prefix, **kwargs)

    def start(self) -> Self:
        if self._parent is not None:
            self._parent.start()
            self._mark_started()
            return self
        if self._closing:
            return self
        if self._started:
            return self
        self._mark_started()
        if self._start_cleanup_thread and _in_uvicorn_process():
            key = (os.getpid(), str(self._db_path))
            if key not in self.__CleanupThreads__:
                thread = threading.Thread(
                    target=self._cleanup_loop,
                    name=f"LocalKVClient[{self._db_path.name}]",
                    daemon=True,
                )
                self.__CleanupThreads__[key] = thread
                thread.start()
        return self

    def close(self) -> None:
        if self._parent is not None:
            self._mark_stopped()
            return
        if self._closing:
            return
        self._closing = True
        self._stop_event.set()
        cleanup_task = self._cleanup_task
        self._cleanup_task = None
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
        key = (os.getpid(), str(self._db_path))
        cleanup_thread = self.__CleanupThreads__.pop(key, None)
        if cleanup_thread is not None and cleanup_thread.is_alive() and cleanup_thread is not threading.current_thread():
            cleanup_thread.join(timeout=max(0.2, self._cleanup_interval + 0.2))

        with self._stash_lock:
            stashes = list(self._stashes.values())
            self._stashes.clear()
            self._cleanup_async_locks.clear()
            self._mark_stopped()
        if not stashes:
            return

        for stash in stashes:
            try:
                close_func = getattr(stash, 'close', None)
                if callable(close_func):
                    close_func()
            except Exception as e:
                _logger.warning('LocalKVClient.close() failed for %s: %s', self._db_path, e)

    def __del__(self):
        try:
            self.close()
        except Exception as e:
            _logger.warning('LocalKVClient.__del__() failed for %s: %s', getattr(self, '_db_path', 'unknown'), e)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_stash(self) -> "pica.Stash":
        if not self._started:
            self.start()
        if self._closing:
            raise RuntimeError(f"LocalKVClient for {self._db_path} is closed.")
        owner = threading.get_ident()
        stash = self._stashes.get(owner)
        if stash is not None:
            return stash
        import pica  # type: ignore  — lazy import
        with self._process_lock:
            stash = self._stashes.get(owner)
            if stash is None:
                stash = pica.Stash(self._db_path)
                self._stashes[owner] = stash
        return stash

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = (threading.get_ident(), id(asyncio.get_running_loop()))
        with self._stash_lock:
            lock = self._cleanup_async_locks.get(owner)
            if lock is None:
                lock = asyncio.Lock()
                self._cleanup_async_locks[owner] = lock
            return lock

    def _schedule_cleanup(self) -> None:
        if self._closing or not self._should_cleanup():
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

    @staticmethod
    def _make_entry(value: object, expire_at: float | None) -> _KVEntry:
        """Wrap *value* together with metadata into a single storable dict."""
        ts = _now_ts()
        size = len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
        return {"v": value, "e": expire_at, "a": ts, "s": size}

    # ------------------------------------------------------------------
    # KVClientBase interface
    # ------------------------------------------------------------------
    async def _set_value(self, key: str, value: object, *, expire: float | int | None = None) -> None:
        if not self._started:
            self.start()
        if not isinstance(value, bytes):
            value = recursive_dump_to_basic_types(value, ignore_err=True)
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        entry = self._make_entry(value, expire_at)
        with self._process_lock:
            with self._stash_lock:
                self._get_stash()[key] = entry
        self._schedule_cleanup()

    async def _get_value(self, key: str, default: object = None) -> object:  # type: ignore[override]
        if not self._started:
            self.start()
        with self._process_lock:
            with self._stash_lock:
                stash = self._get_stash()
                try:
                    entry = stash[key]
                except KeyError:
                    return default
                expire_at = entry.get("e")
                if expire_at is not None and expire_at <= _now_ts():
                    try:
                        del stash[key]
                    except KeyError:
                        pass
                    return default
                entry["a"] = _now_ts()
                stash[key] = entry
        try:
            val = entry["v"]
        except Exception:
            return default
        return val

    async def set_expire(self, key: str, expire: float | int | None) -> bool:
        if self._parent is not None:
            return await self._parent.set_expire(self._child_key(key), expire)
        if not self._started:
            self.start()
        expire_at = _normalize_expire_at(expire)
        with self._process_lock:
            with self._stash_lock:
                stash = self._get_stash()
                try:
                    entry = stash[key]
                except KeyError:
                    return False
                entry["e"] = expire_at
                stash[key] = entry
        return True

    async def get_expire(self, key: str) -> float | None:
        if self._parent is not None:
            return await self._parent.get_expire(self._child_key(key))
        if not self._started:
            self.start()
        with self._process_lock:
            with self._stash_lock:
                stash = self._get_stash()
                try:
                    entry = stash[key]
                except KeyError:
                    return None
                expire_at = entry.get("e")
                ttl = _ttl_from_expire_at(expire_at)
                if ttl == 0.0:
                    try:
                        del stash[key]
                    except KeyError:
                        pass
        return ttl

    async def _mget_values(self, keys: list[str], default: object = None) -> list[object]:
        if not self._started:
            self.start()
        ts = _now_ts()
        results: list[object] = []
        with self._process_lock:
            with self._stash_lock:
                stash = self._get_stash()
                for key in keys:
                    try:
                        entry = stash[key]
                    except KeyError:
                        results.append(default)
                        continue
                    expire_at = entry.get("e")
                    if expire_at is not None and expire_at <= ts:
                        try:
                            del stash[key]
                        except KeyError:
                            pass
                        results.append(default)
                        continue
                    entry["a"] = ts
                    stash[key] = entry
                    try:
                        val = entry["v"]
                    except Exception:
                        val = default
                    results.append(val)
        return results

    async def _mget_expires(self, keys: list[str]) -> list[float | None]:
        if not self._started:
            self.start()
        ts = _now_ts()
        results: list[float | None] = []
        with self._process_lock:
            with self._stash_lock:
                stash = self._get_stash()
                for key in keys:
                    try:
                        entry = stash[key]
                    except KeyError:
                        results.append(None)
                        continue
                    expire_at = entry.get("e")
                    ttl = _ttl_from_expire_at(expire_at)
                    if ttl == 0.0:
                        try:
                            del stash[key]
                        except KeyError:
                            pass
                    results.append(ttl)
        return results

    async def _delete_value(self, key: str) -> bool:
        if not self._started:
            self.start()
        with self._process_lock:
            with self._stash_lock:
                stash = self._get_stash()
                try:
                    del stash[key]
                    return True
                except KeyError:
                    return False

    async def cleanup(self, *, force: bool = False) -> int:
        if self._parent is not None:
            return await self._parent.cleanup(force=force)
        if self._closing:
            return 0
        if not self._started:
            self.start()
        if self._closing:
            return 0
        if not await self._should_cleanup_async(force=force):
            return 0
        async with self._cleanup_async_lock():
            if self._closing:
                return 0
            if not await self._should_cleanup_async(force=force):
                return 0
            removed = 0
            try:
                with self._process_lock:
                    with self._cleanup_lock:
                        with self._stash_lock:
                            if self._closing:
                                return 0
                            stash = self._get_stash()
                            ts = _now_ts()
                            all_entries: list[tuple[str, _KVEntry]] = list(stash.items())
                            expired: set[str] = {
                                k for k, e in all_entries
                                if e.get("e") is not None and e["e"] <= ts  # type: ignore[union-attr]
                            }
                            for k in expired:
                                try:
                                    del stash[k]
                                    removed += 1
                                except KeyError:
                                    pass
                            if self._max_size is not None:
                                live = [(k, e) for k, e in all_entries if k not in expired]
                                if len(live) > self._max_size:
                                    target = max(0, int(self._max_size * 0.9))
                                    live.sort(key=lambda x: x[1].get("a", 0.0))
                                    total_count = len(live)
                                    for k, e in live:
                                        if total_count <= target:
                                            break
                                        try:
                                            del stash[k]
                                            total_count -= 1
                                            removed += 1
                                        except KeyError:
                                            pass
                await self._mark_cleanup_async()
            except Exception as e:
                if self._closing:
                    _logger.warning('Skipping LocalKVClient.cleanup() during shutdown for %s: %s', self._db_path, e)
                    return 0
                raise
            return removed

    async def _list_keys(self, prefix: str | None = None) -> list[str]:
        if not self._started:
            self.start()
        ts = _now_ts()
        with self._process_lock:
            with self._stash_lock:
                all_entries: list[tuple[str, dict]] = list(self._get_stash().items())
        result: list[str] = []
        for k, entry in all_entries:
            expire_at = entry.get("e")
            if expire_at is not None and expire_at <= ts:
                continue
            if prefix is None or k.startswith(prefix):
                result.append(k)
        return sorted(result)

    def _cleanup_loop(self) -> None:
        while not self._stop_event.wait(self._cleanup_interval):
            if self._closing:
                break
            try:
                run_any_func(self.cleanup, force=True)
            except Exception as e:
                if self._closing:
                    _logger.warning('LocalKVClient cleanup loop stopped for %s: %s', self._db_path, e)
                    break
                continue


class RedisKVClient(KVClientBase, type="redis"):
    def __init__(self, _parent: KVClientBase | None = None, _parent_key_prefix: str = "", **kwargs: Unpack[RedisKVClientInitParams]) -> None:
        self._url = kwargs.get("url", "redis://127.0.0.1:6379/0")
        self._prefix = kwargs.get("prefix", "kv")
        self._db = int(kwargs.get("db", 0))
        self._decode_responses = bool(kwargs.get("decode_responses", False))
        self._redis: "_AioRedis | None" = None
        self._redis_by_owner: dict[tuple[int, int], _AioRedis] = {}
        self._ready_owners: set[tuple[int, int]] = set()
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._redis_lock = threading.RLock()
        super().__init__(_parent=_parent, _parent_key_prefix=_parent_key_prefix, **kwargs)

    def start(self) -> Self:
        if self._parent is not None:
            self._parent.start()
            self._mark_started()
            return self
        if self._started:
            return self
        self._mark_started()
        return self

    async def _ensure_ready(self) -> "_AioRedis":
        if not self._started:
            self.start()
        owner = _async_owner_key()
        with self._redis_lock:
            client = self._redis_by_owner.get(owner)
            if client is None:
                import redis.asyncio as aioredis  # type: ignore

                client = aioredis.Redis.from_url(
                    self._url, db=self._db, decode_responses=self._decode_responses,
                )
                self._redis_by_owner[owner] = client
            self._redis = client
            ready = owner in self._ready_owners
        if not ready:
            await client.ping()
            with self._redis_lock:
                self._ready_owners.add(owner)
        return client

    def close(self) -> None:
        if self._parent is not None:
            self._mark_stopped()
            return
        with self._redis_lock:
            redis_clients = list(self._redis_by_owner.values())
            self._redis_by_owner.clear()
            self._ready_owners.clear()
            self._cleanup_async_locks.clear()
        self._redis = None
        self._mark_stopped()
        if not redis_clients:
            return
        for redis_client in redis_clients:
            try:
                close_func = getattr(redis_client, 'aclose', None) or getattr(redis_client, 'close', None)
                if callable(close_func):
                    if inspect.iscoroutinefunction(close_func):
                        try:
                            asyncio.get_running_loop().create_task(close_func())  # type: ignore[misc]
                        except RuntimeError:
                            run_any_func(close_func)
                    else:
                        close_func()
            except Exception as e:
                _logger.warning('RedisKVClient.close() failed for %s: %s', self._url, e)

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = _async_owner_key()
        with self._redis_lock:
            lock = self._cleanup_async_locks.get(owner)
            if lock is None:
                lock = asyncio.Lock()
                self._cleanup_async_locks[owner] = lock
            return lock

    def _value_key(self, key: str) -> str:
        return f"{self._prefix}:value:{key}"

    def _meta_key(self, key: str) -> str:
        return f"{self._prefix}:meta:{key}"

    def _lru_key(self) -> str:
        return f"{self._prefix}:lru"

    def _keys_key(self) -> str:
        return f"{self._prefix}:keys"

    async def _set_value(self, key: str, value: object, *, expire: float | int | None = None) -> None:
        if not isinstance(value, bytes):
            value = recursive_dump_to_basic_types(value, ignore_err=True)
        client = await self._ensure_ready()
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        ttl = None if expire_at is None else max(1, int(expire_at - _now_ts()))
        async with client.pipeline() as pipe:
            pipe.set(self._value_key(key), blob, ex=ttl)
            pipe.hset(
                self._meta_key(key),
                mapping={
                    "size": len(blob),
                    "expire_at": "" if expire_at is None else expire_at,
                },
            )
            pipe.zadd(self._lru_key(), {key: _now_ts()})
            pipe.sadd(self._keys_key(), key)
            await pipe.execute()
        await self.cleanup()

    async def _get_value(self, key: str, default: object = None) -> object:  # type: ignore[override]
        client = await self._ensure_ready()
        blob = await client.get(self._value_key(key))
        if blob is None:
            await self.delete(key)
            return default
        await client.zadd(self._lru_key(), {key: _now_ts()})
        try:
            val = _safe_pickle_loads(blob)
        except Exception:
            return default
        return val

    async def set_expire(self, key: str, expire: float | int | None) -> bool:
        if self._parent is not None:
            return await self._parent.set_expire(self._child_key(key), expire)
        client = await self._ensure_ready()
        expire_at = _normalize_expire_at(expire)
        ttl = None if expire_at is None else max(1, int(expire_at - _now_ts()))
        if ttl is None:
            ok = await client.persist(self._value_key(key))
            await client.hset(self._meta_key(key), mapping={"expire_at": ""})
            return bool(ok)
        ok = await client.expire(self._value_key(key), ttl)
        await client.hset(self._meta_key(key), mapping={"expire_at": expire_at})    # type: ignore
        return bool(ok)

    async def get_expire(self, key: str) -> float | None:
        if self._parent is not None:
            return await self._parent.get_expire(self._child_key(key))
        client = await self._ensure_ready()
        ttl = await client.ttl(self._value_key(key))
        if ttl < 0:
            if ttl == -1:
                return None
            return 0.0
        return float(ttl)

    async def _mget_values(self, keys: list[str], default: object = None) -> list[object]:
        client = await self._ensure_ready()
        value_keys = [self._value_key(k) for k in keys]
        blobs = await client.mget(value_keys)
        results: list[object] = []
        for blob in blobs:
            if blob is None:
                results.append(default)
                continue
            try:
                val = _safe_pickle_loads(blob) if isinstance(blob, bytes) else blob
            except Exception:
                val = default
            results.append(val)
        return results

    async def _mget_expires(self, keys: list[str]) -> list[float | None]:
        client = await self._ensure_ready()
        pipe = client.pipeline(transaction=False)
        for key in keys:
            pipe.ttl(self._value_key(key))
        raw_ttls = await pipe.execute()
        results: list[float | None] = []
        for ttl in raw_ttls:
            ttl_value = int(ttl) if isinstance(ttl, (int, float)) else -2
            if ttl_value in {-2, -1}:
                results.append(None)
            elif ttl_value < 0:
                results.append(0.0)
            else:
                results.append(float(ttl_value))
        return results

    async def _delete_value(self, key: str) -> bool:
        client = await self._ensure_ready()
        async with client.pipeline() as pipe:
            pipe.delete(self._value_key(key))
            pipe.delete(self._meta_key(key))
            pipe.zrem(self._lru_key(), key)
            pipe.srem(self._keys_key(), key)
            result = await pipe.execute()
        return bool(result and result[0])

    async def cleanup(self, *, force: bool = False) -> int:
        if self._parent is not None:
            return await self._parent.cleanup(force=force)
        if not await self._should_cleanup_async(force=force):
            return 0
        removed = 0
        async with self._cleanup_async_lock():
            if not await self._should_cleanup_async(force=force):
                return 0
            client = await self._ensure_ready()
            raw_keys = await client.smembers(self._keys_key())
            keys = [k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in raw_keys]
            total_size = 0
            live_keys: list[str] = []
            orphaned_keys: list[str] = []
            if keys:
                # Batch EXISTS + HGETALL via pipeline instead of N+1 round trips.
                pipe = client.pipeline(transaction=False)
                for key in keys:
                    pipe.exists(self._value_key(key))
                    pipe.hgetall(self._meta_key(key))
                results = await pipe.execute()
                for i, key in enumerate(keys):
                    exists_val = results[i * 2]
                    meta = results[i * 2 + 1] or {}
                    if not exists_val:
                        orphaned_keys.append(key)
                        continue
                    raw_size = meta.get(b"size") if b"size" in meta else meta.get("size", 0)
                    total_size += int(raw_size or 0)
                    live_keys.append(key)
            # Batch-delete orphaned keys via pipeline.
            if orphaned_keys:
                async with client.pipeline() as pipe:
                    for key in orphaned_keys:
                        pipe.delete(self._value_key(key))
                        pipe.delete(self._meta_key(key))
                        pipe.zrem(self._lru_key(), key)
                        pipe.srem(self._keys_key(), key)
                    await pipe.execute()
                removed += len(orphaned_keys)
            total_count = len(live_keys)
            if self._max_size is not None and total_count > self._max_size:
                target = max(0, int(self._max_size * 0.9))
                victims = await client.zrange(self._lru_key(), 0, max(0, len(live_keys) - 1))
                evict_keys: list[str] = []
                for victim in victims:
                    if total_count <= target:
                        break
                    evict_keys.append(victim.decode("utf-8") if isinstance(victim, bytes) else str(victim))
                    total_count -= 1
                if evict_keys:
                    async with client.pipeline() as pipe:
                        for key in evict_keys:
                            pipe.delete(self._value_key(key))
                            pipe.delete(self._meta_key(key))
                            pipe.zrem(self._lru_key(), key)
                            pipe.srem(self._keys_key(), key)
                        await pipe.execute()
                    removed += len(evict_keys)
            await self._mark_cleanup_async()
        return removed

    async def _list_keys(self, prefix: str | None = None) -> list[str]:
        client = await self._ensure_ready()
        raw_keys = await client.smembers(self._keys_key())
        keys = [k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in raw_keys]
        if prefix is not None:
            keys = [key for key in keys if key.startswith(prefix)]
        return sorted(keys)


class EtcdKVClient(KVClientBase, type="etcd"):
    """Async etcd v3 KV client using httpx against the gRPC-gateway REST API."""

    # ── helpers: base64 encode / decode for etcd REST payloads ─────────────
    @staticmethod
    def _b64e(data: str | bytes) -> str:
        raw = data if isinstance(data, (bytes, bytearray, memoryview)) else data.encode("utf-8")
        return _b64.b64encode(raw).decode("utf-8")

    @staticmethod
    def _b64d(data: str | bytes) -> bytes:
        raw = data if isinstance(data, (bytes, bytearray, memoryview)) else data.encode("utf-8")
        return _b64.b64decode(raw)

    @staticmethod
    def _inc_last_byte(data: str | bytes) -> str:
        raw = data.encode("utf-8") if isinstance(data, str) else data
        buf = bytearray(raw)
        buf[-1] += 1
        return bytes(buf).decode("utf-8")

    @staticmethod
    def _json_int(value: object, *, default: int = 0) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _json_float(value: object, *, default: float = 0.0) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        return default

    @classmethod
    def _parse_version_response(cls, data: object) -> _EtcdVersionResponse:
        if not isinstance(data, dict):
            return {}
        version = data.get("etcdserver")
        if isinstance(version, str):
            return {"etcdserver": version}
        return {}

    @classmethod
    def _parse_kv_row(cls, data: object) -> _EtcdKVRow | None:
        if not isinstance(data, dict):
            return None
        row: _EtcdKVRow = {}
        key = data.get("key")
        if isinstance(key, str):
            row["key"] = key
        value = data.get("value")
        if isinstance(value, str):
            row["value"] = value
        lease_id = cls._json_int(data.get("lease"), default=0)
        if lease_id > 0:
            row["lease"] = lease_id
        return row or None

    @classmethod
    def _parse_range_response(cls, data: object) -> _EtcdRangeResponse:
        if not isinstance(data, dict):
            return {}
        raw_rows = data.get("kvs")
        if not isinstance(raw_rows, list):
            return {}
        rows: list[_EtcdKVRow] = []
        for raw_row in raw_rows:
            row = cls._parse_kv_row(raw_row)
            if row is not None:
                rows.append(row)
        return {"kvs": rows}

    @classmethod
    def _parse_delete_response(cls, data: object) -> _EtcdDeleteRangeResponse:
        if not isinstance(data, dict):
            return {}
        return {"deleted": cls._json_int(data.get("deleted"), default=0)}

    @classmethod
    def _parse_lease_grant_response(cls, data: object) -> _EtcdLeaseGrantResponse:
        if not isinstance(data, dict):
            return {}
        payload: _EtcdLeaseGrantResponse = {}
        lease_id = cls._json_int(data.get("ID"), default=0)
        if lease_id > 0:
            payload["ID"] = lease_id
        ttl = cls._json_int(data.get("TTL"), default=0)
        if ttl > 0:
            payload["TTL"] = ttl
        return payload

    @classmethod
    def _parse_lease_ttl_response(cls, data: object) -> _EtcdLeaseTimeToLiveResponse:
        if not isinstance(data, dict):
            return {}
        return {"TTL": cls._json_int(data.get("TTL"), default=0)}

    @classmethod
    def _parse_meta_record(cls, data: object) -> _EtcdMetaRecord:
        if not isinstance(data, dict):
            return {}
        meta: _EtcdMetaRecord = {}
        size = data.get("size")
        if size is not None:
            meta["size"] = cls._json_int(size, default=0)
        accessed_at = data.get("accessed_at")
        if accessed_at is not None:
            meta["accessed_at"] = cls._json_float(accessed_at, default=0.0)
        return meta

    # ── lifecycle ──────────────────────────────────────────────────────────
    def __init__(self, _parent: KVClientBase | None = None, _parent_key_prefix: str = "", **kwargs: Unpack[EtcdKVClientInitParams]) -> None:
        self._host = kwargs.get("host", "127.0.0.1")
        self._port = int(kwargs.get("port", 2379))
        self._protocol = kwargs.get("protocol", "http")
        self._prefix = kwargs.get("prefix", "kv")
        self._timeout = kwargs.get("timeout", 5.0)
        self._api_path: str | None = kwargs.get("api_path", None)
        self._http: "_httpx.AsyncClient | None" = None
        self._http_by_owner: dict[tuple[int, int], _httpx.AsyncClient] = {}
        self._http_lock = threading.RLock()
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        super().__init__(_parent=_parent, _parent_key_prefix=_parent_key_prefix, **kwargs)

    @property
    def _base_url(self) -> str:
        host = f"[{self._host}]" if ":" in self._host else self._host
        return f"{self._protocol}://{host}:{self._port}"

    async def _ensure_api_path(self) -> str:
        if self._api_path is not None:
            return self._api_path
        http = self._client()
        resp = await http.get(f"{self._base_url}/version", timeout=self._timeout)
        resp.raise_for_status()
        version_payload = self._parse_version_response(resp.json())
        version_str = version_payload.get("etcdserver")
        if not version_str:
            raise ValueError("Invalid etcd version response: missing etcdserver")
        parts = tuple(int(p) for p in version_str.split(".", 2))
        if parts >= (3, 4):
            self._api_path = "/v3/"
        elif parts >= (3, 3):
            self._api_path = "/v3beta/"
        else:
            self._api_path = "/v3alpha/"
        return self._api_path

    def _url(self, path: str) -> str:
        api = self._api_path or "/v3/"
        return f"{self._base_url}{api}{path.lstrip('/')}"

    async def _post(self, path: str, *, payload: _EtcdRequest) -> object:
        http = self._client()
        resp = await http.post(self._url(path), json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def start(self) -> Self:
        if self._parent is not None:
            self._parent.start()
            self._mark_started()
            return self
        if self._started:
            return self
        # Validate connection synchronously (start() is sync in the protocol)
        async def _probe() -> None:
            payload: _EtcdEmptyRequest = {}
            await self._ensure_api_path()
            await self._post("maintenance/status", payload=payload)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # We're inside an already-running loop (e.g. during test setup).
            # Defer the probe to first use.
            pass
        else:
            run_any_func(_probe)

        self._mark_started()
        return self

    def close(self) -> None:
        if self._parent is not None:
            self._mark_stopped()
            return
        with self._http_lock:
            http_clients = list(self._http_by_owner.values())
            self._http_by_owner.clear()
            self._cleanup_async_locks.clear()
        self._http = None
        self._mark_stopped()
        if not http_clients:
            return
        for http in http_clients:
            try:
                run_any_func(http.aclose)
            except Exception as e:
                _logger.warning("EtcdKVClient.close() failed for %s:%s: %s", self._host, self._port, e)

    def _client(self) -> "_httpx.AsyncClient":
        if not self._started:
            self.start()
        owner = _async_owner_key()
        with self._http_lock:
            client = self._http_by_owner.get(owner)
            if client is None:
                client = _httpx.AsyncClient(trust_env=False)
                self._http_by_owner[owner] = client
            self._http = client
            return client

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = _async_owner_key()
        with self._http_lock:
            lock = self._cleanup_async_locks.get(owner)
            if lock is None:
                lock = asyncio.Lock()
                self._cleanup_async_locks[owner] = lock
            return lock

    # ── key helpers ────────────────────────────────────────────────────────
    def _base_prefix(self) -> str:
        return f"{self._prefix}:{self._namespace}"

    def _value_prefix(self, key_prefix: str | None = None) -> str:
        base = f"{self._base_prefix()}:value:"
        return base if key_prefix is None else f"{base}{key_prefix}"

    def _meta_prefix(self, key_prefix: str | None = None) -> str:
        base = f"{self._base_prefix()}:meta:"
        return base if key_prefix is None else f"{base}{key_prefix}"

    def _value_key(self, key: str) -> str:
        return self._value_prefix(str(key))

    def _meta_key(self, key: str) -> str:
        return self._meta_prefix(str(key))

    def _external_key(self, raw_key: bytes | str, *, kind: str) -> str:
        text = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
        prefix = self._value_prefix() if kind == "value" else self._meta_prefix()
        if text.startswith(prefix):
            return text[len(prefix):]
        return text

    # ── low-level etcd REST wrappers ──────────────────────────────────────
    async def _etcd_put(self, key: str, value: bytes | str, *, lease_id: int = 0) -> None:
        payload: _EtcdPutRequest = {
            "key": self._b64e(key),
            "value": self._b64e(value if isinstance(value, (bytes, bytearray, memoryview)) else value.encode("utf-8")),
        }
        if lease_id:
            payload["lease"] = str(lease_id)
        await self._post("kv/put", payload=payload)

    async def _etcd_get(self, key: str) -> list[_EtcdKVRow]:
        payload: _EtcdRangeRequest = {"key": self._b64e(key)}
        result = self._parse_range_response(await self._post("kv/range", payload=payload))
        return result.get("kvs", [])

    async def _etcd_get_prefix(self, prefix: str) -> list[_EtcdKVRow]:
        payload: _EtcdRangeRequest = {
            "key": self._b64e(prefix),
            "range_end": self._b64e(self._inc_last_byte(prefix)),
        }
        result = self._parse_range_response(await self._post("kv/range", payload=payload))
        return result.get("kvs", [])

    async def _etcd_delete(self, key: str) -> bool:
        payload: _EtcdDeleteRangeRequest = {"key": self._b64e(key)}
        result = self._parse_delete_response(await self._post("kv/deleterange", payload=payload))
        return result.get("deleted", 0) > 0

    async def _etcd_lease_grant(self, ttl: int) -> int:
        payload: _EtcdLeaseGrantRequest = {"TTL": ttl, "ID": 0}
        result = self._parse_lease_grant_response(await self._post("lease/grant", payload=payload))
        lease_id = result.get("ID", 0)
        if lease_id <= 0:
            raise ValueError(f"Invalid etcd lease/grant response: {result!r}")
        return lease_id

    async def _etcd_lease_ttl(self, lease_id: int) -> int:
        payload: _EtcdLeaseTimeToLiveRequest = {"ID": str(lease_id)}
        result = self._parse_lease_ttl_response(await self._post("kv/lease/timetolive", payload=payload))
        return result.get("TTL", 0)

    # ── metadata helpers ──────────────────────────────────────────────────
    async def _load_meta(self, key: str) -> _EtcdMetaRecord:
        rows = await self._etcd_get(self._meta_key(key))
        if not rows:
            return {}
        payload_b64 = rows[0].get("value", "")
        try:
            raw = self._b64d(payload_b64).decode("utf-8")
            data = _json.loads(raw)
        except Exception:
            return {}
        return self._parse_meta_record(data)

    def _meta_blob(self, *, size: int, accessed_at: float) -> str:
        return _json.dumps(
            {"size": int(size), "accessed_at": float(accessed_at)},
            ensure_ascii=False,
        )

    async def _get_value_row(self, key: str) -> tuple[bytes, _EtcdKVRow] | None:
        rows = await self._etcd_get(self._value_key(key))
        if not rows:
            return None
        kv = rows[0]
        value = self._b64d(kv.get("value", ""))
        return value, kv

    # ── public API ────────────────────────────────────────────────────────
    async def _set_value(self, key: str, value: object, *, expire: float | int | None = None) -> None:
        if not isinstance(value, bytes):
            value = recursive_dump_to_basic_types(value, ignore_err=True)
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        lease_id = 0
        if expire_at is not None:
            lease_id = await self._etcd_lease_grant(max(1, int(expire_at - _now_ts())))
        ts = _now_ts()
        await self._etcd_put(self._value_key(key), blob, lease_id=lease_id)
        await self._etcd_put(self._meta_key(key), self._meta_blob(size=len(blob), accessed_at=ts), lease_id=lease_id)
        await self.cleanup()

    async def _get_value(self, key: str, default: object = None) -> object:  # type: ignore[override]
        row = await self._get_value_row(key)
        if row is None:
            await self.delete(key)
            return default
        blob, kv_meta = row
        try:
            value = _safe_pickle_loads(blob)
        except Exception:
            return default

        meta = await self._load_meta(key)
        if meta:
            # Preserve lease so that updated meta has the same TTL
            lease_id = kv_meta.get("lease", 0)
            ts = _now_ts()
            meta["accessed_at"] = ts
            await self._etcd_put(self._meta_key(key), _json.dumps(meta, ensure_ascii=False), lease_id=lease_id)
        return value

    async def set_expire(self, key: str, expire: float | int | None) -> bool:
        if self._parent is not None:
            return await self._parent.set_expire(self._child_key(key), expire)
        row = await self._get_value_row(key)
        if row is None:
            await self.delete(key)
            return False
        blob, _ = row
        expire_at = _normalize_expire_at(expire)
        lease_id = 0
        if expire_at is not None:
            lease_id = await self._etcd_lease_grant(max(1, int(expire_at - _now_ts())))
        await self._etcd_put(self._value_key(key), blob, lease_id=lease_id)
        meta = await self._load_meta(key)
        ts = _now_ts()
        size = meta.get("size", len(blob))
        accessed_at = meta.get("accessed_at", ts)
        await self._etcd_put(self._meta_key(key), self._meta_blob(size=size, accessed_at=accessed_at), lease_id=lease_id)
        return True

    async def get_expire(self, key: str) -> float | None:
        if self._parent is not None:
            return await self._parent.get_expire(self._child_key(key))
        row = await self._get_value_row(key)
        if row is None:
            await self.delete(key)
            return None
        _, kv_meta = row
        lease_id = kv_meta.get("lease", 0)
        if lease_id <= 0:
            return None
        try:
            ttl = await self._etcd_lease_ttl(lease_id)
            return float(max(ttl, 0))
        except Exception:
            return 0.0

    async def _delete_value(self, key: str) -> bool:
        value_deleted = await self._etcd_delete(self._value_key(key))
        meta_deleted = await self._etcd_delete(self._meta_key(key))
        return bool(value_deleted or meta_deleted)

    async def _cleanup_async_impl(self) -> int:
        """Async cleanup logic — native async, no thread wrapper."""
        removed = 0
        meta_rows = await self._etcd_get_prefix(self._meta_prefix())
        total_size = 0
        live_items: list[tuple[str, int, float]] = []
        for kv in meta_rows:
            raw_key = self._b64d(kv.get("key", "")).decode("utf-8")
            key = self._external_key(raw_key, kind="meta")
            if not key:
                continue
            if await self._get_value_row(key) is None:
                if await self._etcd_delete(self._meta_key(key)):
                    removed += 1
                continue
            try:
                parsed = self._parse_meta_record(_json.loads(self._b64d(kv.get("value", "")).decode("utf-8")))
            except Exception:
                parsed = {}
            size = parsed.get("size", 0)
            accessed_at = parsed.get("accessed_at", 0.0)
            total_size += size
            live_items.append((key, size, accessed_at))
        total_count = len(live_items)
        if self._max_size is not None and total_count > self._max_size:
            target = max(0, int(self._max_size * 0.9))
            evict_keys: list[str] = []
            for key, size, _ in sorted(live_items, key=lambda item: item[2]):
                if total_count <= target:
                    break
                evict_keys.append(key)
                total_count -= 1
            for key in evict_keys:
                await self._etcd_delete(self._value_key(key))
                await self._etcd_delete(self._meta_key(key))
            removed += len(evict_keys)
        return removed

    async def cleanup(self, *, force: bool = False) -> int:
        if self._parent is not None:
            return await self._parent.cleanup(force=force)
        if not await self._should_cleanup_async(force=force):
            return 0
        async with self._cleanup_async_lock():
            if not await self._should_cleanup_async(force=force):
                return 0
            removed = await self._cleanup_async_impl()
            await self._mark_cleanup_async()
        return removed

    async def _list_keys(self, prefix: str | None = None) -> list[str]:
        rows = await self._etcd_get_prefix(self._value_prefix(prefix))
        keys: list[str] = []
        for kv in rows:
            raw_key = self._b64d(kv.get("key", "")).decode("utf-8")
            key = self._external_key(raw_key, kind="value")
            if key and key not in keys:
                keys.append(key)
        return sorted(keys)


__all__ = [
    "KVClientBase",
    "KVClientInitParams",
    "SQLiteKVClient",
    "SQLiteKVClientInitParams",
    "RedisKVClient",
    "RedisKVClientInitParams",
    "EtcdKVClient",
    "EtcdKVClientInitParams",
]
