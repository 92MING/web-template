from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import cast

from ..kv import EtcdKVClient, KVClientBase, RedisKVClient, SQLiteKVClient, _safe_pickle_loads
from .lock import (
    _AsyncOperationLockMixin,
    _MISSING,
    _component_decode,
    _component_encode,
    _normalize_value,
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


class KvDict(_AsyncOperationLockMixin):
    def __init__(self, client: KVClientBase, key_prefix: str | None = None, expire: float | None = None) -> None:
        self._client = client
        self._key_prefix = str(key_prefix or "kvdict")
        self._expire = expire
        self._init_operation_lock()

    def __aiter__(self) -> AsyncIterator[tuple[str, object]]:
        return self.iter()

    def _item_prefix(self) -> str:
        return f"{self._key_prefix}:item:"

    def _item_key(self, key: str) -> str:
        return f"{self._item_prefix()}{_component_encode(str(key))}"

    def _decode_item_key(self, key: str) -> str | None:
        if not key.startswith(self._item_prefix()):
            return None
        try:
            return _component_decode(key[len(self._item_prefix()):])
        except Exception:
            return None

    def _redis_key(self) -> str:
        client = cast(RedisKVClient, self._client)
        return f"{client._prefix}:dict:{client._namespace}:{self._key_prefix}"

    async def _redis_client(self):
        client = cast(RedisKVClient, self._client)
        return await client._ensure_ready()

    def _redis_field(self, key: str) -> str:
        return str(key)

    async def _generic_items(self) -> list[tuple[str, object]]:
        if isinstance(self._client, SQLiteKVClient):
            items = []
            for storage_key, value in _sqlite_items_with_prefix(self._client, self._item_prefix()):
                key = self._decode_item_key(storage_key)
                if key is not None:
                    items.append((key, value))
            return sorted(items, key=lambda item: item[0])
        if isinstance(self._client, EtcdKVClient):
            client = cast(EtcdKVClient, self._client)
            rows = await client._etcd_get_prefix(client._value_prefix(self._item_prefix()))
            items: list[tuple[str, object]] = []
            for row in rows:
                raw_storage_key = client._b64d(row.get("key", "")).decode("utf-8")
                logical_key = client._external_key(raw_storage_key, kind="value")
                key = self._decode_item_key(logical_key)
                if key is None:
                    continue
                try:
                    items.append((key, _safe_pickle_loads(client._b64d(row.get("value", "")))))
                except Exception:
                    continue
            return sorted(items, key=lambda item: item[0])
        keys = await self._client.keys(prefix=self._item_prefix())
        values = await self._client.raw_mget(keys, default=_MISSING)
        items = []
        for storage_key, value in zip(keys, values, strict=False):
            key = self._decode_item_key(storage_key)
            if key is not None and value is not _MISSING:
                items.append((key, value))
        return sorted(items, key=lambda item: item[0])

    async def len(self) -> int:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            return int(await redis_client.hlen(self._redis_key()))
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_count_prefix(self._client, self._item_prefix())
        return len(await self._client.keys(prefix=self._item_prefix()))

    async def set(self, key: str, value: object) -> None:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                encoded = _redis_encode_value(value, decode_responses=cast(RedisKVClient, self._client)._decode_responses)
                await redis_client.hset(self._redis_key(), self._redis_field(key), encoded)
                await _redis_apply_expire(redis_client, self._redis_key(), self._expire)
                return
            if isinstance(self._client, SQLiteKVClient):
                _sqlite_set_value(self._client, self._item_key(key), value, expire=self._expire)
                return
            await self._client.set(self._item_key(key), _normalize_value(value), expire=self._expire)

    async def update(self, values: Mapping[str, object] | None = None, **kwargs: object) -> None:
        merged: dict[str, object] = {}
        if values:
            merged.update({str(key): value for key, value in values.items()})
        merged.update(kwargs)
        if not merged:
            return
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                mapping = {
                    self._redis_field(key): _redis_encode_value(value, decode_responses=cast(RedisKVClient, self._client)._decode_responses)
                    for key, value in merged.items()
                }
                await redis_client.hset(self._redis_key(), mapping=mapping)
                await _redis_apply_expire(redis_client, self._redis_key(), self._expire)
                return
            if isinstance(self._client, SQLiteKVClient):
                _sqlite_set_many(
                    self._client,
                    ((self._item_key(key), value) for key, value in merged.items()),
                    expire=self._expire,
                )
                return
            for key, value in merged.items():
                await self._client.set(self._item_key(key), _normalize_value(value), expire=self._expire)

    async def get(self, key: str, default: object = None) -> object:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            raw = await redis_client.hget(self._redis_key(), self._redis_field(key))
            if raw is None:
                return default
            value = _redis_decode_value(raw)
            return default if value is _MISSING else value
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_get_value(self._client, self._item_key(key), default=default)
        return await self._client.get(self._item_key(key), default=default)

    async def contains(self, key: str) -> bool:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            return bool(await redis_client.hexists(self._redis_key(), self._redis_field(key)))
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_get_value(self._client, self._item_key(key), default=_MISSING) is not _MISSING
        return await self._client.get(self._item_key(key), default=_MISSING) is not _MISSING

    async def delete(self, key: str) -> bool:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                return bool(await redis_client.hdel(self._redis_key(), self._redis_field(key)))
            if isinstance(self._client, SQLiteKVClient):
                return _sqlite_delete_value(self._client, self._item_key(key))
            return await self._client.delete(self._item_key(key))

    async def pop(self, key: str, default: object = _MISSING) -> object:
        async with self._operation_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                raw = await redis_client.hget(self._redis_key(), self._redis_field(key))
                if raw is None:
                    if default is _MISSING:
                        raise KeyError(key)
                    return default
                await redis_client.hdel(self._redis_key(), self._redis_field(key))
                value = _redis_decode_value(raw)
                if value is _MISSING:
                    if default is _MISSING:
                        raise KeyError(key)
                    return default
                return value
            if isinstance(self._client, SQLiteKVClient):
                value = _sqlite_get_value(self._client, self._item_key(key), default=_MISSING)
                if value is _MISSING:
                    if default is _MISSING:
                        raise KeyError(key)
                    return default
                _sqlite_delete_value(self._client, self._item_key(key))
                return value
            value = await self._client.get(self._item_key(key), default=_MISSING)
            if value is _MISSING:
                if default is _MISSING:
                    raise KeyError(key)
                return default
            await self._client.delete(self._item_key(key))
            return value

    async def keys(self) -> list[str]:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            raw_keys = await redis_client.hkeys(self._redis_key())
            return sorted(key.decode("utf-8") if isinstance(key, bytes) else str(key) for key in raw_keys)
        return [key for key, _ in await self._generic_items()]

    async def values(self) -> list[object]:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            return [_redis_decode_value(raw) for raw in await redis_client.hvals(self._redis_key())]
        return [value for _, value in await self._generic_items()]

    async def items(self) -> list[tuple[str, object]]:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            raw_items = await redis_client.hgetall(self._redis_key())
            items: list[tuple[str, object]] = []
            for raw_key, raw_value in raw_items.items():
                key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
                value = _redis_decode_value(raw_value)
                if value is not _MISSING:
                    items.append((key, value))
            return sorted(items, key=lambda item: item[0])
        return await self._generic_items()

    async def to_dict(self) -> dict[str, object]:
        return dict(await self.items())

    async def iter(self) -> AsyncIterator[tuple[str, object]]:
        for item in await self.items():
            yield item

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


__all__ = ["KvDict"]