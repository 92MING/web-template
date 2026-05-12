from __future__ import annotations

import asyncio
import base64 as _b64
import pickle
import threading
import time
import uuid

from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from typing import Any, Literal, Self, cast

from ...utils.type_utils import recursive_dump_to_basic_types
from ..base import _normalize_expire_at, _now_ts
from ..kv import EtcdKVClient, KVClientBase, RedisKVClient, SQLiteKVClient, _async_owner_key, _safe_pickle_loads


_MISSING = object()


class _AsyncOperationLockMixin:
    def _init_operation_lock(self) -> None:
        self._operation_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._operation_lock_guard = threading.RLock()

    def _operation_lock(self) -> asyncio.Lock:
        owner = _async_owner_key()
        with self._operation_lock_guard:
            lock = self._operation_locks.get(owner)
            if lock is None:
                lock = asyncio.Lock()
                self._operation_locks[owner] = lock
            return lock


def _normalize_value(value: object) -> object:
    if isinstance(value, bytes):
        return value
    return recursive_dump_to_basic_types(value, ignore_err=True)


def _pickle_blob(value: object) -> bytes:
    return pickle.dumps(_normalize_value(value), protocol=pickle.HIGHEST_PROTOCOL)


def _redis_encode_value(value: object, *, decode_responses: bool = False) -> bytes | str:
    blob = _pickle_blob(value)
    if decode_responses:
        return _b64.b64encode(blob).decode("ascii")
    return blob


def _redis_decode_value(raw: object) -> object:
    if raw is None:
        return _MISSING
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


def _component_encode(value: str) -> str:
    raw = value.encode("utf-8")
    return _b64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _component_decode(value: str) -> str:
    padded = value + ("=" * (-len(value) % 4))
    return _b64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _resolve_expire_at(expire: float | int | None) -> float | None:
    if expire is None:
        return None
    return _normalize_expire_at(expire)


async def _redis_apply_expire(redis_client: object, key: str, expire: float | int | None) -> None:
    expire_at = _resolve_expire_at(expire)
    if expire_at is None:
        return
    ttl = int(await redis_client.ttl(key))
    if ttl == -1:
        await redis_client.expireat(key, int(expire_at))


async def _etcd_lease_for_expire(client: EtcdKVClient, expire: float | int | None) -> int:
    expire_at = _resolve_expire_at(expire)
    if expire_at is None:
        return 0
    return await client._etcd_lease_grant(max(1, int(expire_at - _now_ts())))


async def _etcd_txn(client: EtcdKVClient, payload: dict[str, object]) -> dict[str, object]:
    raw = await client._post("kv/txn", payload=cast(Any, payload))
    return raw if isinstance(raw, dict) else {}


def _sqlite_expire_at(client: SQLiteKVClient, expire: float | int | None) -> float | None:
    return _normalize_expire_at(expire if expire is not None else client._default_expire)


def _sqlite_entry_value(client: SQLiteKVClient, stash: object, key: str, default: object = _MISSING) -> object:
    try:
        entry = stash[key]
    except KeyError:
        return default
    if not isinstance(entry, dict):
        return default
    expire_at = entry.get("e")
    if expire_at is not None and float(expire_at) <= _now_ts():
        try:
            del stash[key]
        except KeyError:
            pass
        return default
    entry["a"] = _now_ts()
    stash[key] = entry
    return entry.get("v", default)


def _sqlite_get_value(client: SQLiteKVClient, key: str, default: object = _MISSING) -> object:
    if not client.started:
        client.start()
    with client._process_lock:
        with client._stash_lock:
            return _sqlite_entry_value(client, client._get_stash(), key, default=default)


def _sqlite_set_value(client: SQLiteKVClient, key: str, value: object, *, expire: float | int | None = None) -> None:
    if not client.started:
        client.start()
    normalized = _normalize_value(value)
    expire_at = _sqlite_expire_at(client, expire)
    with client._process_lock:
        with client._stash_lock:
            client._get_stash()[key] = client._make_entry(normalized, expire_at)


def _sqlite_set_many(client: SQLiteKVClient, items: Iterable[tuple[str, object]], *, expire: float | int | None = None) -> None:
    if not client.started:
        client.start()
    expire_at = _sqlite_expire_at(client, expire)
    materialized = [(key, _normalize_value(value)) for key, value in items]
    with client._process_lock:
        with client._stash_lock:
            stash = client._get_stash()
            for key, value in materialized:
                stash[key] = client._make_entry(value, expire_at)


def _sqlite_delete_value(client: SQLiteKVClient, key: str) -> bool:
    if not client.started:
        client.start()
    with client._process_lock:
        with client._stash_lock:
            stash = client._get_stash()
            try:
                del stash[key]
                return True
            except KeyError:
                return False


def _sqlite_items_with_prefix(client: SQLiteKVClient, prefix: str) -> list[tuple[str, object]]:
    if not client.started:
        client.start()
    ts = _now_ts()
    items: list[tuple[str, object]] = []
    with client._process_lock:
        with client._stash_lock:
            stash = client._get_stash()
            for key, entry in list(stash.items()):
                if not isinstance(entry, dict):
                    continue
                expire_at = entry.get("e")
                if expire_at is not None and float(expire_at) <= ts:
                    try:
                        del stash[key]
                    except KeyError:
                        pass
                    continue
                if str(key).startswith(prefix):
                    entry["a"] = ts
                    stash[key] = entry
                    items.append((str(key), entry.get("v", _MISSING)))
    return [(key, value) for key, value in items if value is not _MISSING]


def _sqlite_values_for_keys(client: SQLiteKVClient, keys: Iterable[str], default: object = _MISSING) -> list[object]:
    if not client.started:
        client.start()
    materialized = list(keys)
    with client._process_lock:
        with client._stash_lock:
            stash = client._get_stash()
            return [_sqlite_entry_value(client, stash, key, default=default) for key in materialized]


def _sqlite_count_prefix(client: SQLiteKVClient, prefix: str) -> int:
    return len(_sqlite_items_with_prefix(client, prefix))


def _sqlite_delete_prefix(client: SQLiteKVClient, prefix: str) -> int:
    if not client.started:
        client.start()
    removed = 0
    with client._process_lock:
        with client._stash_lock:
            stash = client._get_stash()
            for key in list(stash.keys()):
                if str(key).startswith(prefix):
                    try:
                        del stash[key]
                        removed += 1
                    except KeyError:
                        pass
    return removed


def _sqlite_update_value(
    client: SQLiteKVClient,
    key: str,
    updater: Callable[[object], object],
    *,
    default: object = _MISSING,
    expire: float | int | None = None,
) -> object:
    if not client.started:
        client.start()
    with client._process_lock:
        with client._stash_lock:
            stash = client._get_stash()
            current = _sqlite_entry_value(client, stash, key, default=default)
            updated = updater(current)
            if updated is _MISSING:
                try:
                    del stash[key]
                except KeyError:
                    pass
                return updated
            stash[key] = client._make_entry(_normalize_value(updated), _sqlite_expire_at(client, expire))
            return updated


class KvLock:
    def __init__(self, client: KVClientBase, key_prefix: str | None = None, expire: float | None = 30.0) -> None:
        self._client = client
        self._key_prefix = str(key_prefix or "kvlock")
        self._expire = expire
        self._owner_token: str | None = None

    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.release()

    def _key(self) -> str:
        return f"{self._key_prefix}:lock"

    def _redis_key(self) -> str:
        client = cast(RedisKVClient, self._client)
        return f"{client._prefix}:lock:{client._namespace}:{self._key_prefix}"

    async def _redis_client(self):
        client = cast(RedisKVClient, self._client)
        return await client._ensure_ready()

    async def _try_acquire_redis(self, token: str) -> bool:
        redis_client = await self._redis_client()
        kwargs: dict[str, object] = {"nx": True}
        if self._expire is not None:
            kwargs["ex"] = max(1, int(self._expire))
        ok = await redis_client.set(self._redis_key(), token, **kwargs)
        return bool(ok)

    async def _try_acquire_etcd(self, token: str) -> bool:
        client = cast(EtcdKVClient, self._client)
        key = client._value_key(self._key())
        blob = _pickle_blob(token)
        put: dict[str, object] = {
            "key": client._b64e(key),
            "value": client._b64e(blob),
        }
        lease_id = await _etcd_lease_for_expire(client, self._expire)
        if lease_id:
            put["lease"] = str(lease_id)
        result = await _etcd_txn(
            client,
            {
                "compare": [
                    {"key": client._b64e(key), "target": "VERSION", "result": "EQUAL", "version": "0"}
                ],
                "success": [{"request_put": put}],
                "failure": [],
            },
        )
        return bool(result.get("succeeded"))

    async def _try_acquire_generic(self, token: str) -> bool:
        existing = await self._client.get(self._key(), default=None)
        if existing is not None:
            return existing == token
        await self._client.set(self._key(), token, expire=self._expire)
        return await self._client.get(self._key(), default=None) == token

    async def acquire(self, *, timeout: float | None = None, retry_interval: float = 0.05) -> bool:
        if self._owner_token is not None:
            return True
        token = uuid.uuid4().hex
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            acquired = await (
                self._try_acquire_redis(token)
                if isinstance(self._client, RedisKVClient)
                else self._try_acquire_etcd(token)
                if isinstance(self._client, EtcdKVClient)
                else self._try_acquire_sqlite(token)
                if isinstance(self._client, SQLiteKVClient)
                else self._try_acquire_generic(token)
            )
            if acquired:
                self._owner_token = token
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(max(0.001, retry_interval))

    async def release(self) -> bool:
        token = self._owner_token
        if token is None:
            return False
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            script = """
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('DEL', KEYS[1])
            end
            return 0
            """
            removed = await redis_client.eval(script, 1, self._redis_key(), token)
            ok = int(removed or 0) > 0
        elif isinstance(self._client, EtcdKVClient):
            client = cast(EtcdKVClient, self._client)
            key = client._value_key(self._key())
            result = await _etcd_txn(
                client,
                {
                    "compare": [
                        {
                            "key": client._b64e(key),
                            "target": "VALUE",
                            "result": "EQUAL",
                            "value": client._b64e(_pickle_blob(token)),
                        }
                    ],
                    "success": [{"request_delete_range": {"key": client._b64e(key)}}],
                    "failure": [],
                },
            )
            ok = bool(result.get("succeeded"))
        elif isinstance(self._client, SQLiteKVClient):
            client = cast(SQLiteKVClient, self._client)
            if not client.started:
                client.start()
            with client._process_lock:
                with client._stash_lock:
                    stash = client._get_stash()
                    ok = _sqlite_entry_value(client, stash, self._key(), default=_MISSING) == token
                    if ok:
                        try:
                            del stash[self._key()]
                        except KeyError:
                            pass
        else:
            ok = await self._client.get(self._key(), default=None) == token
            if ok:
                await self._client.delete(self._key())
        if ok:
            self._owner_token = None
        return ok

    async def locked(self) -> bool:
        if isinstance(self._client, RedisKVClient):
            redis_client = await self._redis_client()
            return bool(await redis_client.exists(self._redis_key()))
        if isinstance(self._client, EtcdKVClient):
            client = cast(EtcdKVClient, self._client)
            return bool(await client._etcd_get(client._value_key(self._key())))
        if isinstance(self._client, SQLiteKVClient):
            return _sqlite_get_value(cast(SQLiteKVClient, self._client), self._key(), default=_MISSING) is not _MISSING
        return await self._client.get(self._key(), default=None) is not None

    async def _try_acquire_sqlite(self, token: str) -> bool:
        client = cast(SQLiteKVClient, self._client)
        if not client.started:
            client.start()
        key = self._key()
        with client._process_lock:
            with client._stash_lock:
                stash = client._get_stash()
                existing = _sqlite_entry_value(client, stash, key, default=_MISSING)
                if existing is not _MISSING:
                    return existing == token
                stash[key] = client._make_entry(token, _sqlite_expire_at(client, self._expire))
                return True


class KvRWLock:
    def __init__(self, client: KVClientBase, key_prefix: str | None = None, expire: float | None = 30.0) -> None:
        self._client = client
        self._key_prefix = str(key_prefix or "kvrwlock")
        self._expire = expire
        self._local_lock = asyncio.Lock()
        self._writer_token: str | None = None

    def _guard(self) -> KvLock:
        return KvLock(self._client, f"{self._key_prefix}:guard", expire=self._expire)

    def _reader_key(self) -> str:
        return f"{self._key_prefix}:readers"

    def _writer_key(self) -> str:
        return f"{self._key_prefix}:writer"

    async def _reader_count(self) -> int:
        raw = await self._client.get(self._reader_key(), default=0)
        try:
            return max(0, int(cast(int | float | str, raw)))
        except Exception:
            return 0

    async def _set_reader_count(self, count: int) -> None:
        if count <= 0:
            await self._client.delete(self._reader_key())
            return
        await self._client.set(self._reader_key(), count, expire=self._expire)

    async def acquire_read(self, *, timeout: float | None = None, retry_interval: float = 0.05) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            async with self._local_lock:
                guard = self._guard()
                if await guard.acquire(timeout=timeout, retry_interval=retry_interval):
                    try:
                        writer = await self._client.get(self._writer_key(), default=None)
                        if writer is None:
                            await self._set_reader_count(await self._reader_count() + 1)
                            return True
                    finally:
                        await guard.release()
            if deadline is not None and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(max(0.001, retry_interval))

    async def release_read(self) -> None:
        async with self._local_lock:
            guard = self._guard()
            await guard.acquire()
            try:
                await self._set_reader_count(await self._reader_count() - 1)
            finally:
                await guard.release()

    async def acquire_write(self, *, timeout: float | None = None, retry_interval: float = 0.05) -> bool:
        if self._writer_token is not None:
            return True
        token = uuid.uuid4().hex
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            async with self._local_lock:
                guard = self._guard()
                if await guard.acquire(timeout=timeout, retry_interval=retry_interval):
                    try:
                        writer = await self._client.get(self._writer_key(), default=None)
                        if writer is None and await self._reader_count() <= 0:
                            await self._client.set(self._writer_key(), token, expire=self._expire)
                            self._writer_token = token
                            return True
                    finally:
                        await guard.release()
            if deadline is not None and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(max(0.001, retry_interval))

    async def release_write(self) -> None:
        token = self._writer_token
        if token is None:
            return
        async with self._local_lock:
            guard = self._guard()
            await guard.acquire()
            try:
                if await self._client.get(self._writer_key(), default=None) == token:
                    await self._client.delete(self._writer_key())
                self._writer_token = None
            finally:
                await guard.release()

    @asynccontextmanager
    async def read_lock(self) -> AsyncIterator[None]:
        await self.acquire_read()
        try:
            yield
        finally:
            await self.release_read()

    @asynccontextmanager
    async def write_lock(self) -> AsyncIterator[None]:
        await self.acquire_write()
        try:
            yield
        finally:
            await self.release_write()


type _NumberKind = Literal["int", "float"]


def _coerce_number(value: object, *, default: int | float = 0) -> int | float:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return default
    return default


def _result_number(value: int | float, kind: _NumberKind | None = None) -> int | float:
    if kind == "float":
        return float(value)
    if kind == "int":
        return int(value)
    if isinstance(value, float) and not value.is_integer():
        return value
    return int(value)


__all__ = [
    "KvLock",
    "KvRWLock",
]