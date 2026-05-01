# -*- coding: utf-8 -*-
"""
KV-backed shared context for AI services.

Provides AIServiceSharedContext, which stores cross-server concurrent request
counts and client runtime status in the storage KV backend. Resolution prefers a
named KV client ai_services_context and falls back to the default KV client when
that slot is not configured.

A process-local in-memory backup is always kept. When KV is temporarily
unavailable, reads and writes degrade to the local backup so service scheduling
continues to work. Dirty local state is flushed back to KV automatically on
later successful operations.
"""
import os
import json
import time
import socket
import hashlib
import threading

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, Sequence, cast

from core.utils.concurrent_utils import async_run_any_func

if TYPE_CHECKING:
    from .base import ServiceClientBase
    from ..storage.kv import KVClientBase


AIServiceKind = Literal['completion', 'embedding', 's2t', 't2s']
'''AI 服务的四种预定义 kind。'''

ClientStatusValue = str | int | float | bool | None
ClientStatusRecord = dict[str, ClientStatusValue]


class _LockLike(Protocol):
    def __enter__(self) -> object: ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None: ...


class AIServiceSharedContext:
    """AI 服务共享上下文。

    共享信息分两类：
    1. concurrent_pool: 当前进程的本地并发计数备份。
    2. client_status: 当前进程看到的最新客户端状态缓存。

    实际跨 server 共享使用 KV 存储，按 instance_id 拆分写入，避免多个
    server 同时覆盖同一份共享状态；读取时聚合所有未过期的远端记录。
    """

    __singleton__: ClassVar['AIServiceSharedContext']

    _KV_CLIENT_NAME: ClassVar[str] = 'ai_services_context'
    _KV_PREFIX: ClassVar[str] = 'ai_services_context'
    _KV_RETRY_COOLDOWN: ClassVar[float] = 5.0
    _REMOTE_POOL_CACHE_TTL: ClassVar[float] = 1.0
    _REMOTE_STATUS_CACHE_TTL: ClassVar[float] = 5.0
    _CONCURRENT_RECORD_STALE_AFTER: ClassVar[float] = 180.0
    _STATUS_RECORD_STALE_AFTER: ClassVar[float] = 300.0

    if TYPE_CHECKING:
        concurrent_pool: dict[str, dict[str, int]]
        client_status: dict[str, ClientStatusRecord]

    def __init__(self, id: str, /):
        self._id = id
        self._instance_id = self._build_instance_id(id)
        self.concurrent_pool: dict[str, dict[str, int]] = {}
        self.client_status: dict[str, ClientStatusRecord] = {}
        self._lock: _LockLike = threading.RLock()
        self._kv_client: KVClientBase | None = None
        self._kv_retry_after: float = 0.0
        self._dirty_pool_categories: set[str] = set()
        self._dirty_status_hashes: set[str] = set()
        self._remote_pool_cache: dict[str, tuple[float, dict[str, int]]] = {}
        self._remote_status_cache: dict[str, tuple[float, ClientStatusRecord | None]] = {}
        self._is_flushing = False

    @staticmethod
    def _build_instance_id(scope: str) -> str:
        server_id = os.environ.get('__SERVER_INSTANCE_ID__') or os.environ.get('SERVER_INSTANCE_ID') or socket.gethostname()
        return f'{scope}:{server_id}:{os.getpid()}:{int(time.time() * 1000)}'

    def _pool_kv_key(self, category: str) -> str:
        return f'{self._KV_PREFIX}:concurrent_pool:{category}:{self._instance_id}'

    def _pool_kv_prefix(self, category: str) -> str:
        return f'{self._KV_PREFIX}:concurrent_pool:{category}:'

    def _status_kv_key(self, client_hash: str) -> str:
        return f'{self._KV_PREFIX}:client_status:{client_hash}:{self._instance_id}'

    def _status_kv_prefix(self, client_hash: str) -> str:
        return f'{self._KV_PREFIX}:client_status:{client_hash}:'

    def _get_kv_client(self, *, force: bool = False) -> "KVClientBase | None":
        now = time.time()
        if self._kv_client is not None:
            return self._kv_client
        if not force and now < self._kv_retry_after:
            return None
        try:
            from ..storage.config import StorageConfig
            cfg = StorageConfig.Global()
            try:
                client = cfg.kv.get_client(self._KV_CLIENT_NAME, fallback='default')
            except Exception:
                client = cfg.get_kv_client()
            self._kv_client = client  # type: ignore[assignment]
            self._kv_retry_after = 0.0
            return self._kv_client
        except Exception:
            self._kv_client = None
            self._kv_retry_after = now + self._KV_RETRY_COOLDOWN
            return None

    def _mark_kv_failure(self) -> None:
        self._kv_client = None
        self._kv_retry_after = time.time() + self._KV_RETRY_COOLDOWN

    async def _kv_call(
        self,
        method_name: str,
        *args: object,
        default: object = None,
        force: bool = False,
        **kwargs: object,
    ) -> tuple[object, bool]:
        client = self._get_kv_client(force=force)
        if client is None:
            return default, False
        try:
            method = getattr(client, method_name)
            result = await async_run_any_func(method, *args, **kwargs)
            self._kv_retry_after = 0.0
            return result, True
        except Exception:
            self._mark_kv_failure()
            return default, False

    async def _flush_dirty(self) -> None:
        if self._is_flushing:
            return
        if time.time() < self._kv_retry_after and not (self._dirty_pool_categories or self._dirty_status_hashes):
            return
        self._is_flushing = True
        force = bool(self._dirty_pool_categories or self._dirty_status_hashes)
        try:
            for category in list(self._dirty_pool_categories):
                if not await self._persist_pool_category(category, force=force):
                    break
            for client_hash in list(self._dirty_status_hashes):
                if not await self._persist_client_status(client_hash, force=force):
                    break
        finally:
            self._is_flushing = False

    async def _persist_pool_category(self, category: str, *, force: bool = False) -> bool:
        with self._lock:
            counts = dict(self.concurrent_pool.get(category, {}))
        key = self._pool_kv_key(category)
        if counts:
            payload = {
                'instance_id': self._instance_id,
                'updated_at': time.time(),
                'counts': counts,
            }
            _, ok = await self._kv_call('set', key, payload, force=force)
        else:
            _, ok = await self._kv_call('delete', key, default=False, force=force)
        if ok:
            with self._lock:
                self._dirty_pool_categories.discard(category)
        return ok

    async def _persist_client_status(self, client_hash: str, *, force: bool = False) -> bool:
        with self._lock:
            payload = self.client_status.get(client_hash)
            payload_copy = dict(payload) if payload is not None else None
        key = self._status_kv_key(client_hash)
        if payload_copy:
            _, ok = await self._kv_call('set', key, payload_copy, force=force)
        else:
            _, ok = await self._kv_call('delete', key, default=False, force=force)
        if ok:
            with self._lock:
                self._dirty_status_hashes.discard(client_hash)
        return ok

    async def _best_effort_delete_keys(self, keys: Sequence[str]) -> None:
        for key in keys:
            await self._kv_call('delete', key, default=False)

    @staticmethod
    def _record_updated_at(record: ClientStatusRecord | None) -> float:
        if not record:
            return 0.0
        try:
            return float(record.get('_updated_at', record.get('updated_at', 0.0)) or 0.0)
        except Exception:
            return 0.0

    async def _load_remote_pool_counts(self, category: str) -> dict[str, int]:
        now = time.time()
        cached = self._remote_pool_cache.get(category)
        if cached is not None and (now - cached[0]) < self._REMOTE_POOL_CACHE_TTL:
            return dict(cached[1])

        keys, ok = await self._kv_call('keys', prefix=self._pool_kv_prefix(category), default=[])
        if not ok:
            if cached is not None and (now - cached[0]) < self._REMOTE_POOL_CACHE_TTL:
                return dict(cached[1])
            return {}

        aggregate: dict[str, int] = {}
        stale_keys: list[str] = []
        for key in cast(list[str], keys or []):
            payload, got = await self._kv_call('get', key, default=None)
            if not got:
                if cached is not None and (now - cached[0]) < self._REMOTE_POOL_CACHE_TTL:
                    return dict(cached[1])
                return {}
            if not isinstance(payload, dict):
                stale_keys.append(key)
                continue
            updated_at = self._record_updated_at(payload)
            if updated_at <= 0 or (now - updated_at) > self._CONCURRENT_RECORD_STALE_AFTER:
                stale_keys.append(key)
                continue
            if payload.get('instance_id') == self._instance_id:
                continue
            counts = payload.get('counts', {})
            if not isinstance(counts, dict):
                continue
            for client_key, count in counts.items():
                try:
                    count_int = max(0, int(count))
                except Exception:
                    continue
                if count_int > 0:
                    aggregate[str(client_key)] = aggregate.get(str(client_key), 0) + count_int

        self._remote_pool_cache[category] = (now, aggregate)
        if stale_keys:
            await self._best_effort_delete_keys(stale_keys)
        return dict(aggregate)

    async def _load_remote_client_status(self, client_hash: str) -> ClientStatusRecord | None:
        now = time.time()
        cached = self._remote_status_cache.get(client_hash)
        if cached is not None and (now - cached[0]) < self._REMOTE_STATUS_CACHE_TTL:
            return dict(cached[1]) if cached[1] is not None else None

        keys, ok = await self._kv_call('keys', prefix=self._status_kv_prefix(client_hash), default=[])
        if not ok:
            if cached is not None and (now - cached[0]) < self._REMOTE_STATUS_CACHE_TTL:
                return dict(cached[1]) if cached[1] is not None else None
            return None

        best_status: ClientStatusRecord | None = None
        best_updated_at = 0.0
        stale_keys: list[str] = []
        for key in cast(list[str], keys or []):
            payload, got = await self._kv_call('get', key, default=None)
            if not got:
                if cached is not None and (now - cached[0]) < self._REMOTE_STATUS_CACHE_TTL:
                    return dict(cached[1]) if cached[1] is not None else None
                return None
            if not isinstance(payload, dict):
                stale_keys.append(key)
                continue
            updated_at = self._record_updated_at(payload)
            if updated_at <= 0 or (now - updated_at) > self._STATUS_RECORD_STALE_AFTER:
                stale_keys.append(key)
                continue
            if updated_at > best_updated_at:
                best_status = cast(ClientStatusRecord, dict(payload))
                best_updated_at = updated_at

        self._remote_status_cache[client_hash] = (now, best_status)
        if stale_keys:
            await self._best_effort_delete_keys(stale_keys)
        return dict(best_status) if best_status is not None else None

    # pool operations
    async def acquire(self, category: str, key: str) -> int:
        await self._flush_dirty()
        with self._lock:
            bucket = self.concurrent_pool.setdefault(category, {})
            count = max(0, int(bucket.get(key, 0))) + 1
            bucket[key] = count
            self._dirty_pool_categories.add(category)
            self._remote_pool_cache.pop(category, None)
        await self._persist_pool_category(category)
        return await self.get_count(category, key)

    async def release(self, category: str, key: str) -> int:
        await self._flush_dirty()
        with self._lock:
            bucket = self.concurrent_pool.get(category)
            if bucket is None:
                return 0
            count = max(0, int(bucket.get(key, 0)) - 1)
            if count == 0:
                bucket.pop(key, None)
            else:
                bucket[key] = count
            if not bucket:
                self.concurrent_pool.pop(category, None)
            self._dirty_pool_categories.add(category)
            self._remote_pool_cache.pop(category, None)
        await self._persist_pool_category(category)
        return await self.get_count(category, key)

    async def get_count(self, category: str, key: str) -> int:
        await self._flush_dirty()
        with self._lock:
            local_count = int(self.concurrent_pool.get(category, {}).get(key, 0))
        remote_counts = await self._load_remote_pool_counts(category)
        return local_count + int(remote_counts.get(key, 0))

    async def get_total(self, category: str) -> int:
        await self._flush_dirty()
        with self._lock:
            local_total = sum(self.concurrent_pool.get(category, {}).values())
        remote_total = sum((await self._load_remote_pool_counts(category)).values())
        return int(local_total + remote_total)

    # client status operations
    async def update_client_status(self, client_hash: str, status: ClientStatusRecord) -> None:
        await self._flush_dirty()
        with self._lock:
            existing = dict(self.client_status.get(client_hash, {}))
            existing.update(status)
            existing['_updated_at'] = time.time()
            existing['_instance_id'] = self._instance_id
            self.client_status[client_hash] = existing
            self._dirty_status_hashes.add(client_hash)
            self._remote_status_cache.pop(client_hash, None)
        await self._persist_client_status(client_hash)

    async def get_client_status(self, client_hash: str) -> ClientStatusRecord | None:
        await self._flush_dirty()
        with self._lock:
            local_status = dict(self.client_status.get(client_hash, {})) if client_hash in self.client_status else None
        remote_status = await self._load_remote_client_status(client_hash)

        local_updated = self._record_updated_at(local_status)
        remote_updated = self._record_updated_at(remote_status)
        best = local_status if local_updated >= remote_updated else remote_status
        if best is None:
            return None
        with self._lock:
            self.client_status[client_hash] = dict(best)
        return dict(best)

    async def is_client_status_fresh(self, client_hash: str, max_age: float = 30.0) -> bool:
        status = await self.get_client_status(client_hash)
        if status is None:
            return False
        updated_at = self._record_updated_at(status)
        return updated_at > 0 and (time.time() - updated_at) < max_age

    @classmethod
    def Get(cls) -> 'AIServiceSharedContext':
        singleton = cls.__dict__.get('__singleton__', None)
        if singleton is None:
            cls.__singleton__ = cls('ai_services')
            singleton = cls.__singleton__
        return cast('AIServiceSharedContext', singleton)


class ConcurrentPool:
    """基于 AIServiceSharedContext 的并发限制器。

    并发计数通过共享上下文聚合本地内存与 KV 中的远端实例记录。KV
    异常时会自动退化到本地内存计数，不阻断服务请求调度。
    """

    __slots__ = ('category', 'max_concurrent', '_parents')

    def __init__(
        self,
        category: str | None = None,
        max_concurrent: int = 1,
        *,
        _parent: 'ConcurrentPool | None' = None,
        _parents: 'Sequence[ConcurrentPool] | None' = None,
    ):
        self.category = category
        self.max_concurrent: int = max(1, int(max_concurrent))
        if _parents is not None:
            self._parents: tuple[ConcurrentPool, ...] = tuple(_parents)
        elif _parent is not None:
            self._parents = (_parent,)
        else:
            self._parents = ()

    def create_sub_pool(self, max_concurrent: int) -> 'ConcurrentPool':
        sub_category = f'{self.category}:sub:{id(self):x}'
        return ConcurrentPool(sub_category, max_concurrent, _parent=self)

    async def can_accept(self, key: str) -> bool:
        ctx = AIServiceSharedContext.Get()
        try:
            if await async_run_any_func(ctx.get_count, self.category, key) >= self.max_concurrent:  # type: ignore[call-arg]
                return False
        except Exception:
            return True
        for parent in self._parents:
            if not await parent.can_accept(key):
                return False
        return True

    async def acquire(self, key: str) -> int:
        for parent in self._parents:
            await parent.acquire(key)
        ctx = AIServiceSharedContext.Get()
        try:
            return await async_run_any_func(ctx.acquire, self.category, key)    # type: ignore[call-arg]
        except Exception:
            return 0

    async def release(self, key: str) -> int:
        for parent in self._parents:
            await parent.release(key)
        ctx = AIServiceSharedContext.Get()
        try:
            return await async_run_any_func(ctx.release, self.category, key)    # type: ignore[call-arg]
        except Exception:
            return 0

    async def get_count(self, key: str) -> int:
        ctx = AIServiceSharedContext.Get()
        try:
            return await async_run_any_func(ctx.get_count, self.category, key)  # type: ignore[call-arg]
        except Exception:
            return 0

    @asynccontextmanager
    async def semaphore(self, key: str):
        await self.acquire(key)
        try:
            yield
        finally:
            await self.release(key)

    def __repr__(self) -> str:
        parent_info = f', parents={self._parents!r}' if self._parents else ''
        return f'ConcurrentPool({self.category!r}, {self.max_concurrent}{parent_info})'

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ConcurrentPool):
            return self.category == other.category and self.max_concurrent == other.max_concurrent
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.category, self.max_concurrent))


class CompletionConcurrentPool(ConcurrentPool):
    """面向 Completion 服务的并发池，额外限制多模态并发。"""

    __slots__ = ('_images_pool', '_videos_pool', '_audios_pool')

    def __init__(
        self,
        category: str | None = None,
        max_concurrent: int = 1,
        *,
        max_images: int | ConcurrentPool,
        max_videos: int | ConcurrentPool,
        max_audios: int | ConcurrentPool,
        _parent: ConcurrentPool | None = None,
    ):
        super().__init__(category, max_concurrent, _parent=_parent)
        if isinstance(max_images, ConcurrentPool):
            self._images_pool = max_images
        else:
            self._images_pool = ConcurrentPool(
                f'{category}:images',
                max_images,
            )

        if isinstance(max_audios, ConcurrentPool):
            self._audios_pool = max_audios
        else:
            self._audios_pool = ConcurrentPool(
                f'{category}:audios',
                max_audios,
            )

        if isinstance(max_videos, ConcurrentPool):
            self._videos_pool = max_videos
        else:
            self._videos_pool = ConcurrentPool(
                f'{category}:videos',
                max_videos,
            )

    @property
    def images_pool(self) -> ConcurrentPool:
        return self._images_pool

    @property
    def videos_pool(self) -> ConcurrentPool:
        return self._videos_pool

    @property
    def audios_pool(self) -> ConcurrentPool:
        return self._audios_pool

    def create_sub_pool(  # type: ignore[override]
        self,
        max_concurrent: int,
        *,
        max_images: int | ConcurrentPool | None = None,
        max_videos: int | ConcurrentPool | None = None,
        max_audios: int | ConcurrentPool | None = None,
    ) -> 'CompletionConcurrentPool':
        sub_category = f'{self.category}:sub:{id(self):x}'
        return CompletionConcurrentPool(
            sub_category,
            max_concurrent,
            max_images=max_images if max_images is not None else self._images_pool,
            max_videos=max_videos if max_videos is not None else self._videos_pool,
            max_audios=max_audios if max_audios is not None else self._audios_pool,
            _parent=self,
        )

    def __repr__(self) -> str:
        return (
            f'CompletionConcurrentPool({self.category!r}, {self.max_concurrent}, '
            f'images={self._images_pool!r}, videos={self._videos_pool!r}, audios={self._audios_pool!r})'
        )


def compute_client_hash(client: "ServiceClientBase") -> str:
    """计算客户端 init 参数的 MD5 哈希（结果缓存在客户端实例上）。"""
    cached = getattr(client, '_cached_client_hash', None)
    if cached is not None:
        return cached  # type: ignore[return-value]

    params: dict[str, object] = {'__class__': type(client).__qualname__}
    for k in sorted(vars(client)):
        if k.startswith('_'):
            continue
        v = getattr(client, k, None)
        if isinstance(v, ConcurrentPool) or callable(v):
            continue
        try:
            json.dumps(v, default=str)
            params[k] = v
        except (TypeError, ValueError, OverflowError):
            params[k] = repr(v)

    data = json.dumps(params, sort_keys=True, default=str, ensure_ascii=False)
    h = hashlib.md5(data.encode()).hexdigest()

    try:
        object.__setattr__(client, '_cached_client_hash', h)
    except (AttributeError, TypeError):
        pass

    return h


__all__ = [
    'AIServiceKind',
    'AIServiceSharedContext',
    'ConcurrentPool',
    'CompletionConcurrentPool',
    'compute_client_hash',
]
