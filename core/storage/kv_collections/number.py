from __future__ import annotations

from typing import Any, cast

from ..base import _now_ts
from ..kv import EtcdKVClient, KVClientBase, RedisKVClient, SQLiteKVClient, _safe_pickle_loads
from .lock import (
    KvRWLock,
    _MISSING,
    _coerce_number,
    _etcd_lease_for_expire,
    _etcd_txn,
    _pickle_blob,
    _result_number,
    _redis_apply_expire,
    _sqlite_delete_value,
    _sqlite_entry_value,
    _sqlite_expire_at,
    _sqlite_get_value,
    _sqlite_set_value,
)


class KvNumber:
    def __init__(self, client: KVClientBase, key_prefix: str | None = None, expire: float | None = None) -> None:
        self._client = client
        self._key_prefix = str(key_prefix or "kvnumber")
        self._expire = expire
        self._rw_lock = KvRWLock(client, f"{self._key_prefix}:rwlock", expire=30.0)

    def _value_key(self) -> str:
        return f"{self._key_prefix}:value"

    def _redis_key(self) -> str:
        client = cast(RedisKVClient, self._client)
        return f"{client._prefix}:number:{client._namespace}:{self._key_prefix}"

    async def _redis_client(self):
        client = cast(RedisKVClient, self._client)
        return await client._ensure_ready()

    def _etcd_value_key(self) -> str:
        client = cast(EtcdKVClient, self._client)
        return client._value_key(self._value_key())

    def _etcd_meta_key(self) -> str:
        client = cast(EtcdKVClient, self._client)
        return client._meta_key(self._value_key())

    async def _etcd_get_row(self) -> dict[str, object] | None:
        client = cast(EtcdKVClient, self._client)
        payload = {"key": client._b64e(self._etcd_value_key())}
        raw = await client._post("kv/range", payload=cast(Any, payload))
        if not isinstance(raw, dict):
            return None
        rows = raw.get("kvs")
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        return row if isinstance(row, dict) else None

    def _etcd_decode_row_value(self, row: dict[str, object] | None, default: int | float = 0) -> int | float:
        if row is None:
            return default
        value = row.get("value")
        if not isinstance(value, str):
            return default
        try:
            client = cast(EtcdKVClient, self._client)
            return _coerce_number(_safe_pickle_loads(client._b64d(value)), default=default)
        except Exception:
            return default

    async def _etcd_put_number(self, value: int | float) -> int | float:
        client = cast(EtcdKVClient, self._client)
        blob = _pickle_blob(value)
        lease_id = await _etcd_lease_for_expire(client, self._expire)
        put_value: dict[str, object] = {
            "key": client._b64e(self._etcd_value_key()),
            "value": client._b64e(blob),
        }
        put_meta: dict[str, object] = {
            "key": client._b64e(self._etcd_meta_key()),
            "value": client._b64e(client._meta_blob(size=len(blob), accessed_at=_now_ts())),
        }
        if lease_id:
            put_value["lease"] = str(lease_id)
            put_meta["lease"] = str(lease_id)
        await client._post("kv/put", payload=cast(Any, put_value))
        await client._post("kv/put", payload=cast(Any, put_meta))
        return value

    async def _etcd_add(self, delta: int | float) -> int | float:
        client = cast(EtcdKVClient, self._client)
        for _ in range(32):
            row = await self._etcd_get_row()
            current = self._etcd_decode_row_value(row, default=0)
            next_value = _result_number(
                current + delta,
                "float" if isinstance(current, float) or isinstance(delta, float) else "int",
            )
            blob = _pickle_blob(next_value)
            lease_id = await _etcd_lease_for_expire(client, self._expire)
            if not lease_id and row is not None:
                lease_id = int(row.get("lease", 0) or 0)
            put_value: dict[str, object] = {
                "key": client._b64e(self._etcd_value_key()),
                "value": client._b64e(blob),
            }
            put_meta: dict[str, object] = {
                "key": client._b64e(self._etcd_meta_key()),
                "value": client._b64e(client._meta_blob(size=len(blob), accessed_at=_now_ts())),
            }
            if lease_id:
                put_value["lease"] = str(lease_id)
                put_meta["lease"] = str(lease_id)
            if row is None:
                compare = {"key": client._b64e(self._etcd_value_key()), "target": "VERSION", "result": "EQUAL", "version": "0"}
            else:
                compare = {
                    "key": client._b64e(self._etcd_value_key()),
                    "target": "MOD",
                    "result": "EQUAL",
                    "mod_revision": str(row.get("mod_revision", "0")),
                }
            result = await _etcd_txn(
                client,
                {
                    "compare": [compare],
                    "success": [{"request_put": put_value}, {"request_put": put_meta}],
                    "failure": [],
                },
            )
            if result.get("succeeded"):
                return next_value
        raise RuntimeError("KvNumber etcd compare-and-swap failed after retries")

    async def get(self, default: int | float = 0) -> int | float:
        if isinstance(self._client, SQLiteKVClient):
            return _coerce_number(_sqlite_get_value(self._client, self._value_key(), default=default), default=default)
        async with self._rw_lock.read_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                raw = await redis_client.get(self._redis_key())
                if raw is None:
                    return default
                text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                return _coerce_number(text, default=default)
            if isinstance(self._client, EtcdKVClient):
                return self._etcd_decode_row_value(await self._etcd_get_row(), default=default)
            return _coerce_number(await self._client.get(self._value_key(), default=default), default=default)

    async def set(self, value: int | float) -> int | float:
        if isinstance(self._client, SQLiteKVClient):
            normalized = _result_number(value, "float" if isinstance(value, float) else "int")
            _sqlite_set_value(self._client, self._value_key(), normalized, expire=self._expire)
            return normalized
        async with self._rw_lock.write_lock():
            normalized = _result_number(value, "float" if isinstance(value, float) else "int")
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                await redis_client.set(self._redis_key(), str(normalized))
                await _redis_apply_expire(redis_client, self._redis_key(), self._expire)
                return normalized
            if isinstance(self._client, EtcdKVClient):
                return await self._etcd_put_number(normalized)
            await self._client.set(self._value_key(), normalized, expire=self._expire)
            return normalized

    async def add(self, delta: int | float = 1) -> int | float:
        if isinstance(self._client, SQLiteKVClient):
            client = self._client
            if not client.started:
                client.start()
            with client._process_lock:
                with client._stash_lock:
                    stash = client._get_stash()
                    current = _coerce_number(_sqlite_entry_value(client, stash, self._value_key(), default=0))
                    normalized = _result_number(
                        current + delta,
                        "float" if isinstance(current, float) or isinstance(delta, float) else "int",
                    )
                    stash[self._value_key()] = client._make_entry(normalized, _sqlite_expire_at(client, self._expire))
                    return normalized
        async with self._rw_lock.write_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                if isinstance(delta, int) and not isinstance(delta, bool):
                    value = int(await redis_client.incrby(self._redis_key(), int(delta)))
                else:
                    value = float(await redis_client.incrbyfloat(self._redis_key(), float(delta)))
                await _redis_apply_expire(redis_client, self._redis_key(), self._expire)
                return _result_number(value, "float" if isinstance(delta, float) else None)
            if isinstance(self._client, EtcdKVClient):
                return await self._etcd_add(delta)
            current = _coerce_number(await self._client.get(self._value_key(), default=0))
            value = current + delta
            normalized = _result_number(value, "float" if isinstance(current, float) or isinstance(delta, float) else "int")
            await self._client.set(self._value_key(), normalized, expire=self._expire)
            return normalized

    async def sub(self, delta: int | float = 1) -> int | float:
        return await self.add(-delta)

    async def incr(self, step: int = 1) -> int:
        return int(await self.add(step))

    async def decr(self, step: int = 1) -> int:
        return int(await self.add(-step))

    async def clear(self) -> None:
        if isinstance(self._client, SQLiteKVClient):
            _sqlite_delete_value(self._client, self._value_key())
            return
        async with self._rw_lock.write_lock():
            if isinstance(self._client, RedisKVClient):
                redis_client = await self._redis_client()
                await redis_client.delete(self._redis_key())
                return
            if isinstance(self._client, EtcdKVClient):
                client = cast(EtcdKVClient, self._client)
                await client._etcd_delete(self._etcd_value_key())
                await client._etcd_delete(self._etcd_meta_key())
                return
            await self._client.delete(self._value_key())


__all__ = ["KvNumber"]