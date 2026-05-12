from __future__ import annotations

import hashlib

from collections.abc import AsyncIterator, Iterable
from typing import cast

from ..kv import EtcdKVClient, KVClientBase, RedisKVClient, SQLiteKVClient, _safe_pickle_loads
from .lock import (
    _AsyncOperationLockMixin,
    _MISSING,
    _normalize_value,
    _pickle_blob,
    _redis_apply_expire,
    _redis_decode_value,
    _redis_encode_value,
    _sqlite_count_prefix,
    _sqlite_delete_prefix,
    _sqlite_delete_value,
    _sqlite_get_value,
    _sqlite_items_with_prefix,
    _sqlite_set_many,
    _sqlite_set_value,
)


class KvSet(_AsyncOperationLockMixin):
    def __init__(self, client: KVClientBase, key_prefix: str | None = None, expire: float | None = None) -> None:
        self._client = client
        self._key_prefix = str(key_prefix or "kvset")
        self._expire = expire
        self._init_operation_lock()

    def __aiter__(self) -> AsyncIterator[object]:
        return self.iter()

    def _item_prefix(self) -> str:
        return f"{self._key_prefix}:item:"

    def _item_key(self, value: object) -> str:
        digest = hashlib.sha256(_pickle_blob(value)).hexdigest()
        return f"{self._item_prefix()}{digest}"

    def _redis_key(self) -> str:
        client = cast(RedisKVClient, self._client)
        return f"{client._prefix}:set:{client._namespace}:{self._key_prefix}"

    async def _redis_client(self):
        client = cast(RedisKVClient, self._client)
        return await client._ensure_ready()

    async def _generic_values(self) -> list[object]:
        if isinstance(self._client, SQLiteKVClient):
            return [value for _, value in _sqlite_items_with_prefix(self._client, self._item_prefix())]
        if isinstance(self._client, EtcdKVClient):
            client = cast(EtcdKVClient, self._client)
            rows = await client._etcd_get_prefix(client._value_prefix(self._item_prefix()))
            values: list[object] = []
            for row in rows:
                try:
                    values.append(_safe_pickle_loads(client._b64d(row.get("value", ""))))
                except Exception:
                    continue
            return values
        keys = await self._client.keys(prefix=self._item_prefix())
        values = await self._client.raw_mget(keys, default=_MISSING)
        return [value for value in values if value is not _MISSING]

    async def add(self, value: object) -> bool:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                encoded = _redis_encode_value(value, decode_responses=cast(RedisKVClient, self._client)._decode_responses)
                added = bool(await redis_client.sadd(self._redis_key(), encoded))
                await _redis_apply_expire(redis_client, self._redis_key(), self._expire)
                return added
            if isinstance(self._client, SQLiteKVClient):
                key = self._item_key(value)
                existed = _sqlite_get_value(self._client, key, default=_MISSING) is not _MISSING
                _sqlite_set_value(self._client, key, value, expire=self._expire)
                return not existed
            existed = await self.contains(value)
            await self._client.set(self._item_key(value), _normalize_value(value), expire=self._expire)
            return not existed

    async def update(self, values: Iterable[object]) -> int:
        materialized = list(values)
        if not materialized:
            return 0
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                payloads = [
                    _redis_encode_value(value, decode_responses=cast(RedisKVClient, self._client)._decode_responses)
                    for value in materialized
                ]
                added = int(await redis_client.sadd(self._redis_key(), *payloads))
                await _redis_apply_expire(redis_client, self._redis_key(), self._expire)
                return added
            if isinstance(self._client, SQLiteKVClient):
                keys = [self._item_key(value) for value in materialized]
                added = sum(
                    1
                    for key in keys
                    if _sqlite_get_value(self._client, key, default=_MISSING) is _MISSING
                )
                _sqlite_set_many(self._client, zip(keys, materialized, strict=False), expire=self._expire)
                return added
            added = 0
            for value in materialized:
                key = self._item_key(value)
                if await self._client.get(key, default=_MISSING) is _MISSING:
                    added += 1
                await self._client.set(key, _normalize_value(value), expire=self._expire)
            return added

    async def contains(self, value: object) -> bool:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            encoded = _redis_encode_value(value, decode_responses=cast(RedisKVClient, self._client)._decode_responses)
            return bool(await redis_client.sismember(self._redis_key(), encoded))
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_get_value(self._client, self._item_key(value), default=_MISSING) is not _MISSING
        return await self._client.get(self._item_key(value), default=_MISSING) is not _MISSING

    async def discard(self, value: object) -> bool:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                encoded = _redis_encode_value(value, decode_responses=cast(RedisKVClient, self._client)._decode_responses)
                return bool(await redis_client.srem(self._redis_key(), encoded))
            if isinstance(self._client, SQLiteKVClient):
                return _sqlite_delete_value(self._client, self._item_key(value))
            return await self._client.delete(self._item_key(value))

    async def remove(self, value: object) -> None:
        if not await self.discard(value):
            raise KeyError(value)

    async def pop(self) -> object:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                raw = await redis_client.spop(self._redis_key())
                if raw is None:
                    raise KeyError("pop from an empty KvSet")
                value = _redis_decode_value(raw)
                if value is _MISSING:
                    raise KeyError("pop from an empty KvSet")
                return value
            if isinstance(self._client, SQLiteKVClient):
                items = _sqlite_items_with_prefix(self._client, self._item_prefix())
                if not items:
                    raise KeyError("pop from an empty KvSet")
                key, value = items[0]
                _sqlite_delete_value(self._client, key)
                return value
            keys = await self._client.keys(prefix=self._item_prefix())
            if not keys:
                raise KeyError("pop from an empty KvSet")
            key = keys[0]
            value = await self._client.get(key, default=_MISSING)
            await self._client.delete(key)
            if value is _MISSING:
                raise KeyError("pop from an empty KvSet")
            return value

    async def len(self) -> int:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            return int(await redis_client.scard(self._redis_key()))
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_count_prefix(self._client, self._item_prefix())
        return len(await self._client.keys(prefix=self._item_prefix()))

    async def to_list(self) -> list[object]:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            return [_redis_decode_value(raw) for raw in await redis_client.smembers(self._redis_key())]
        return await self._generic_values()

    async def to_set(self) -> set[object]:
        return set(await self.to_list())

    async def iter(self) -> AsyncIterator[object]:
        for value in await self.to_list():
            yield value

    async def clear(self) -> None:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                await redis_client.delete(self._redis_key())
                return
            if isinstance(self._client, SQLiteKVClient):
                _sqlite_delete_prefix(self._client, self._item_prefix())
                return
            for key in await self._client.keys(prefix=self._item_prefix()):
                await self._client.delete(key)


__all__ = ["KvSet"]