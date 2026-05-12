from __future__ import annotations

import asyncio
import base64 as _b64
import pickle
import threading

from collections.abc import AsyncIterator, Iterable
from typing import TypedDict, cast

from ...utils.type_utils import recursive_dump_to_basic_types
from ..base import _normalize_expire_at
from ..kv import EtcdKVClient, KVClientBase, RedisKVClient, SQLiteKVClient, _async_owner_key, _safe_pickle_loads
from .lock import (
    _sqlite_delete_prefix,
    _sqlite_delete_value,
    _sqlite_get_value,
    _sqlite_items_with_prefix,
    _sqlite_set_value,
    _sqlite_values_for_keys,
)


_INDEX_OFFSET = 1 << 63
_INDEX_HEX_WIDTH = 16
_MISSING = object()

_REDIS_INSERT_SCRIPT = """
local key = KEYS[1]
local idx = tonumber(ARGV[1])
local value = ARGV[2]
local size = redis.call('LLEN', key)

if idx <= 0 then
    redis.call('LPUSH', key, value)
    return redis.call('LLEN', key)
end

if idx >= size then
    redis.call('RPUSH', key, value)
    return redis.call('LLEN', key)
end

local tail = redis.call('LRANGE', key, idx, -1)
redis.call('LTRIM', key, 0, idx - 1)
redis.call('RPUSH', key, value)
for i = 1, #tail do
    redis.call('RPUSH', key, tail[i])
end
return redis.call('LLEN', key)
"""

_REDIS_POP_SCRIPT = """
local key = KEYS[1]
local idx = tonumber(ARGV[1])
local size = redis.call('LLEN', key)

if size == 0 then
    return false
end

if idx < 0 then
    idx = size + idx
end

if idx < 0 or idx >= size then
    return false
end

if idx == 0 then
    return redis.call('LPOP', key)
end

if idx == size - 1 then
    return redis.call('RPOP', key)
end

local value = redis.call('LINDEX', key, idx)
local tail = redis.call('LRANGE', key, idx + 1, -1)
redis.call('LTRIM', key, 0, idx - 1)
for i = 1, #tail do
    redis.call('RPUSH', key, tail[i])
end
return value
"""


class _KvListMeta(TypedDict):
    size: int
    head: int
    tail: int
    expire_at: float | None


def _encode_index(raw_index: int) -> str:
    unsigned_index = raw_index + _INDEX_OFFSET
    if unsigned_index < 0 or unsigned_index >= (1 << 64):
        raise OverflowError(f"KvList index out of supported range: {raw_index}")
    return f"{unsigned_index:0{_INDEX_HEX_WIDTH}x}"


def _decode_index(encoded_index: str) -> int:
    return int(encoded_index, 16) - _INDEX_OFFSET


def _normalize_access_index(index: int, size: int) -> int:
    resolved = size + index if index < 0 else index
    if resolved < 0 or resolved >= size:
        raise IndexError("KvList index out of range")
    return resolved


def _normalize_insert_index(index: int, size: int) -> int:
    if index < 0:
        return max(size + index, 0)
    return min(index, size)


class KvList:
    def __init__(self, client: KVClientBase, key_prefix: str | None = None, expire: float | None = None) -> None:
        self._client = client
        self._key_prefix = str(key_prefix or "kvlist")
        self._expire = expire
        self._operation_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._operation_lock_guard = threading.RLock()

    def __aiter__(self) -> AsyncIterator[object]:
        return self.iter()

    def _operation_lock(self) -> asyncio.Lock:
        owner = _async_owner_key()
        with self._operation_lock_guard:
            lock = self._operation_locks.get(owner)
            if lock is None:
                lock = asyncio.Lock()
                self._operation_locks[owner] = lock
            return lock

    def _meta_key(self) -> str:
        return f"{self._key_prefix}:meta"

    def _item_prefix(self) -> str:
        return f"{self._key_prefix}:item:"

    def _item_key(self, raw_index: int) -> str:
        return f"{self._item_prefix()}{_encode_index(raw_index)}"

    def _empty_meta(self) -> _KvListMeta:
        return {"size": 0, "head": 0, "tail": -1, "expire_at": None}

    def _normalize_value(self, value: object) -> object:
        if isinstance(value, bytes):
            return value
        return recursive_dump_to_basic_types(value, ignore_err=True)

    def _resolve_new_expire_at(self) -> float | None:
        if self._expire is None:
            return None
        return _normalize_expire_at(self._expire)

    async def _load_meta(self) -> _KvListMeta:
        raw = (
            _sqlite_get_value(self._client, self._meta_key(), default=None)
            if isinstance(self._client, SQLiteKVClient)
            else await self._client.get(self._meta_key(), default=None)
        )
        if not isinstance(raw, dict):
            return self._empty_meta()
        size = int(raw.get("size", 0) or 0)
        if size <= 0:
            return self._empty_meta()
        return {
            "size": size,
            "head": int(raw.get("head", 0) or 0),
            "tail": int(raw.get("tail", size - 1) or (size - 1)),
            "expire_at": cast(float | None, raw.get("expire_at", None)),
        }

    async def _store_meta(self, meta: _KvListMeta) -> None:
        if meta["size"] <= 0:
            if isinstance(self._client, SQLiteKVClient):
                _sqlite_delete_value(self._client, self._meta_key())
            else:
                await self._client.delete(self._meta_key())
            return
        if isinstance(self._client, SQLiteKVClient):
            _sqlite_set_value(
                self._client,
                self._meta_key(),
                {
                    "size": int(meta["size"]),
                    "head": int(meta["head"]),
                    "tail": int(meta["tail"]),
                    "expire_at": meta["expire_at"],
                },
                expire=meta["expire_at"],
            )
            return
        await self._client.set(
            self._meta_key(),
            {
                "size": int(meta["size"]),
                "head": int(meta["head"]),
                "tail": int(meta["tail"]),
                "expire_at": meta["expire_at"],
            },
            expire=meta["expire_at"],
        )

    async def _generic_get_raw(self, raw_index: int, default: object = _MISSING) -> object:
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_get_value(self._client, self._item_key(raw_index), default=default)
        return await self._client.get(self._item_key(raw_index), default=default)

    async def _generic_set_raw(self, raw_index: int, value: object, *, expire_at: float | None) -> None:
        if isinstance(self._client, SQLiteKVClient):
            _sqlite_set_value(self._client, self._item_key(raw_index), self._normalize_value(value), expire=expire_at)
            return
        await self._client.set(self._item_key(raw_index), self._normalize_value(value), expire=expire_at)

    async def _generic_delete_raw(self, raw_index: int) -> bool:
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_delete_value(self._client, self._item_key(raw_index))
        return await self._client.delete(self._item_key(raw_index))

    async def _generic_raw_values(self, raw_indices: list[int]) -> list[object]:
        if not raw_indices:
            return []
        keys = [self._item_key(raw_index) for raw_index in raw_indices]
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_values_for_keys(self._client, keys, default=_MISSING)
        return await self._client.raw_mget(keys, default=_MISSING)

    async def _snapshot_sqlite_values(self, meta: _KvListMeta) -> list[object]:
        values: list[tuple[int, object]] = []
        for storage_key, value in _sqlite_items_with_prefix(self._client, self._item_prefix()):
            suffix = storage_key[len(self._item_prefix()):]
            try:
                raw_index = _decode_index(suffix)
            except Exception:
                continue
            if meta["head"] <= raw_index <= meta["tail"]:
                values.append((raw_index, value))
        values.sort(key=lambda item: item[0])
        return [value for _, value in values[: meta["size"]]]

    async def _snapshot_etcd_values(self, meta: _KvListMeta) -> list[object]:
        client = cast(EtcdKVClient, self._client)
        rows = await client._etcd_get_prefix(client._value_prefix(self._item_prefix()))
        values: list[tuple[int, object]] = []
        for row in rows:
            raw_storage_key = client._b64d(row.get("key", "")).decode("utf-8")
            logical_key = client._external_key(raw_storage_key, kind="value")
            if not logical_key.startswith(self._item_prefix()):
                continue
            suffix = logical_key[len(self._item_prefix()):]
            try:
                raw_index = _decode_index(suffix)
            except Exception:
                continue
            if raw_index < meta["head"] or raw_index > meta["tail"]:
                continue
            try:
                values.append((raw_index, _safe_pickle_loads(client._b64d(row.get("value", "")))))
            except Exception:
                continue
        values.sort(key=lambda item: item[0])
        return [value for _, value in values[: meta["size"]]]

    async def _generic_snapshot(self) -> list[object]:
        meta = await self._load_meta()
        if meta["size"] <= 0:
            return []
        if isinstance(self._client, SQLiteKVClient):
            return await self._snapshot_sqlite_values(meta)
        if isinstance(self._client, EtcdKVClient):
            return await self._snapshot_etcd_values(meta)
        raw_indices = list(range(meta["head"], meta["tail"] + 1))
        values = await self._generic_raw_values(raw_indices)
        return [value for value in values if value is not _MISSING][: meta["size"]]

    def _redis_key(self) -> str:
        client = cast(RedisKVClient, self._client)
        return f"{client._prefix}:list:{client._namespace}:{self._key_prefix}"

    async def _redis_client(self):
        client = cast(RedisKVClient, self._client)
        return await client._ensure_ready()

    def _redis_encode(self, value: object) -> bytes | str:
        client = cast(RedisKVClient, self._client)
        normalized = self._normalize_value(value)
        blob = pickle.dumps(normalized, protocol=pickle.HIGHEST_PROTOCOL)
        if client._decode_responses:
            return _b64.b64encode(blob).decode("ascii")
        return blob

    def _redis_decode(self, raw: object) -> object:
        if raw is None:
            raise IndexError("KvList index out of range")
        if isinstance(raw, str):
            blob = _b64.b64decode(raw.encode("ascii"))
        elif isinstance(raw, memoryview):
            blob = bytes(raw)
        elif isinstance(raw, bytearray):
            blob = bytes(raw)
        elif isinstance(raw, bytes):
            blob = raw
        else:
            blob = str(raw).encode("utf-8")
        return _safe_pickle_loads(blob)

    async def _redis_apply_expire(self, redis_client) -> None:
        expire_at = self._resolve_new_expire_at()
        if expire_at is None:
            return
        ttl = await redis_client.ttl(self._redis_key())
        if int(ttl) == -1:
            await redis_client.expireat(self._redis_key(), int(expire_at))

    async def len(self) -> int:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            return int(await redis_client.llen(self._redis_key()))
        return int((await self._load_meta())["size"])

    async def append(self, value: object) -> None:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                await redis_client.rpush(self._redis_key(), self._redis_encode(value))
                await self._redis_apply_expire(redis_client)
                return
            meta = await self._load_meta()
            raw_index = 0 if meta["size"] <= 0 else meta["tail"] + 1
            expire_at = meta["expire_at"] if meta["size"] > 0 else self._resolve_new_expire_at()
            await self._generic_set_raw(raw_index, value, expire_at=expire_at)
            if meta["size"] <= 0:
                meta["head"] = raw_index
            meta["tail"] = raw_index
            meta["size"] += 1
            meta["expire_at"] = expire_at
            await self._store_meta(meta)

    async def extend(self, values: Iterable[object]) -> None:
        materialized = [self._normalize_value(value) for value in values]
        if not materialized:
            return
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                payloads = [self._redis_encode(value) for value in materialized]
                await redis_client.rpush(self._redis_key(), *payloads)
                await self._redis_apply_expire(redis_client)
                return
            meta = await self._load_meta()
            expire_at = meta["expire_at"] if meta["size"] > 0 else self._resolve_new_expire_at()
            start_raw_index = 0 if meta["size"] <= 0 else meta["tail"] + 1
            for offset, value in enumerate(materialized):
                await self._generic_set_raw(start_raw_index + offset, value, expire_at=expire_at)
            if meta["size"] <= 0:
                meta["head"] = start_raw_index
            meta["tail"] = start_raw_index + len(materialized) - 1
            meta["size"] += len(materialized)
            meta["expire_at"] = expire_at
            await self._store_meta(meta)

    async def get(self, index: int) -> object:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            raw = await redis_client.lindex(self._redis_key(), index)
            if raw is None:
                raise IndexError("KvList index out of range")
            return self._redis_decode(raw)

        meta = await self._load_meta()
        logical_index = _normalize_access_index(index, meta["size"])
        raw_index = meta["head"] + logical_index
        value = await self._generic_get_raw(raw_index, default=_MISSING)
        if value is _MISSING:
            raise IndexError("KvList index out of range")
        return value

    async def set(self, index: int, value: object) -> None:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                size = int(await redis_client.llen(self._redis_key()))
                resolved = _normalize_access_index(index, size)
                await redis_client.lset(self._redis_key(), resolved, self._redis_encode(value))
                return

            meta = await self._load_meta()
            logical_index = _normalize_access_index(index, meta["size"])
            expire_at = meta["expire_at"]
            await self._generic_set_raw(meta["head"] + logical_index, value, expire_at=expire_at)

    async def insert(self, index: int, value: object) -> None:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                size = int(await redis_client.llen(self._redis_key()))
                resolved = _normalize_insert_index(index, size)
                await redis_client.eval(_REDIS_INSERT_SCRIPT, 1, self._redis_key(), resolved, self._redis_encode(value))
                await self._redis_apply_expire(redis_client)
                return

            meta = await self._load_meta()
            size = meta["size"]
            resolved = _normalize_insert_index(index, size)
            expire_at = meta["expire_at"] if size > 0 else self._resolve_new_expire_at()
            if size <= 0:
                await self._generic_set_raw(0, value, expire_at=expire_at)
                meta.update(size=1, head=0, tail=0, expire_at=expire_at)
                await self._store_meta(meta)
                return
            if resolved == 0:
                raw_index = meta["head"] - 1
                await self._generic_set_raw(raw_index, value, expire_at=expire_at)
                meta["head"] = raw_index
            elif resolved == size:
                raw_index = meta["tail"] + 1
                await self._generic_set_raw(raw_index, value, expire_at=expire_at)
                meta["tail"] = raw_index
            elif resolved <= size // 2:
                source_indices = list(range(meta["head"], meta["head"] + resolved))
                source_values = await self._generic_raw_values(source_indices)
                for source_index, source_value in zip(source_indices, source_values, strict=False):
                    if source_value is _MISSING:
                        continue
                    await self._generic_set_raw(source_index - 1, source_value, expire_at=expire_at)
                insert_raw_index = meta["head"] + resolved - 1
                await self._generic_set_raw(insert_raw_index, value, expire_at=expire_at)
                meta["head"] -= 1
            else:
                source_indices = list(range(meta["head"] + resolved, meta["tail"] + 1))
                source_values = await self._generic_raw_values(source_indices)
                for source_index, source_value in zip(source_indices, source_values, strict=False):
                    if source_value is _MISSING:
                        continue
                    await self._generic_set_raw(source_index + 1, source_value, expire_at=expire_at)
                insert_raw_index = meta["head"] + resolved
                await self._generic_set_raw(insert_raw_index, value, expire_at=expire_at)
                meta["tail"] += 1
            meta["size"] += 1
            meta["expire_at"] = expire_at
            await self._store_meta(meta)

    async def pop(self, index: int = -1) -> object:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                raw = await redis_client.eval(_REDIS_POP_SCRIPT, 1, self._redis_key(), index)
                if raw is False or raw is None:
                    raise IndexError("pop from empty KvList")
                return self._redis_decode(raw)

            meta = await self._load_meta()
            size = meta["size"]
            resolved = _normalize_access_index(index, size)
            raw_index = meta["head"] + resolved
            value = await self._generic_get_raw(raw_index, default=_MISSING)
            if value is _MISSING:
                raise IndexError("pop from empty KvList")
            if size == 1:
                await self._generic_delete_raw(raw_index)
                await self._store_meta(self._empty_meta())
                return value
            expire_at = meta["expire_at"]
            if resolved < size // 2:
                source_indices = list(range(meta["head"], raw_index))
                source_values = await self._generic_raw_values(source_indices)
                for source_index, source_value in zip(source_indices, source_values, strict=False):
                    if source_value is _MISSING:
                        continue
                    await self._generic_set_raw(source_index + 1, source_value, expire_at=expire_at)
                await self._generic_delete_raw(meta["head"])
                meta["head"] += 1
            else:
                source_indices = list(range(raw_index + 1, meta["tail"] + 1))
                source_values = await self._generic_raw_values(source_indices)
                for source_index, source_value in zip(source_indices, source_values, strict=False):
                    if source_value is _MISSING:
                        continue
                    await self._generic_set_raw(source_index - 1, source_value, expire_at=expire_at)
                await self._generic_delete_raw(meta["tail"])
                meta["tail"] -= 1
            meta["size"] -= 1
            await self._store_meta(meta)
            return value

    async def clear(self) -> None:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                await redis_client.delete(self._redis_key())
                return
            if isinstance(self._client, SQLiteKVClient):
                _sqlite_delete_prefix(self._client, self._item_prefix())
                _sqlite_delete_value(self._client, self._meta_key())
                return

            meta = await self._load_meta()
            if meta["size"] > 0:
                for raw_index in range(meta["head"], meta["tail"] + 1):
                    await self._generic_delete_raw(raw_index)
            await self._client.delete(self._meta_key())

    async def to_list(self) -> list[object]:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            raw_items = await redis_client.lrange(self._redis_key(), 0, -1)
            return [self._redis_decode(raw_item) for raw_item in raw_items]
        return await self._generic_snapshot()

    async def iter(self, *, batch_size: int = 128) -> AsyncIterator[object]:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            total = int(await redis_client.llen(self._redis_key()))
            for start in range(0, total, batch_size):
                raw_items = await redis_client.lrange(self._redis_key(), start, min(total - 1, start + batch_size - 1))
                for raw_item in raw_items:
                    yield self._redis_decode(raw_item)
            return

        meta = await self._load_meta()
        if meta["size"] <= 0:
            return
        if isinstance(self._client, SQLiteKVClient):
            for value in await self._snapshot_sqlite_values(meta):
                yield value
            return
        if isinstance(self._client, EtcdKVClient):
            for value in await self._snapshot_etcd_values(meta):
                yield value
            return
        for start_offset in range(0, meta["size"], batch_size):
            chunk_size = min(batch_size, meta["size"] - start_offset)
            raw_indices = [meta["head"] + start_offset + offset for offset in range(chunk_size)]
            values = await self._generic_raw_values(raw_indices)
            for value in values:
                if value is not _MISSING:
                    yield value

    async def remove(self, value: object) -> None:
        if isinstance(self._client, RedisKVClient):
            async with self._operation_lock():
                redis_client = await self._redis_client()
                removed = await redis_client.lrem(self._redis_key(), 1, self._redis_encode(value))
                if int(removed) <= 0:
                    raise ValueError("KvList.remove(x): x not in list")
                return
        try:
            remove_index = await self.index(value)
        except ValueError as exc:
            raise ValueError("KvList.remove(x): x not in list") from exc
        await self.pop(remove_index)

    async def index(self, value: object, start: int = 0, stop: int | None = None) -> int:
        values = await self.to_list()
        resolved_stop = len(values) if stop is None else stop
        for idx in range(max(start, 0), min(resolved_stop, len(values))):
            if values[idx] == value:
                return idx
        raise ValueError("KvList.index(x): x not in list")

    async def count(self, value: object) -> int:
        return (await self.to_list()).count(value)


__all__ = ["KvList"]