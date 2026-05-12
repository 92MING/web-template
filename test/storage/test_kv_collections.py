from __future__ import annotations

import os
import tempfile
import time
import unittest

from pathlib import Path

from core.storage.kv import EtcdKVClient, RedisKVClient, SQLiteKVClient
from core.storage.kv_collections import KvDict, KvList, KvLock, KvNumber, KvSet


_SUFFIX = str(time.time_ns())[-10:]
_ETCD_PORT = int(os.getenv("TEST_ETCD_PORT", "23791"))


class TestSQLiteKvList(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_kv_list_behaves_like_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3", auto_start=True)
            items = KvList(client, key_prefix="numbers")
            try:
                await items.append(1)
                await items.append(3)
                await items.insert(1, 2)

                self.assertEqual(await items.len(), 3)
                self.assertEqual(await items.get(1), 2)

                await items.set(1, 20)
                self.assertEqual(await items.to_list(), [1, 20, 3])
                self.assertEqual([value async for value in items], [1, 20, 3])

                self.assertEqual(await items.pop(1), 20)
                self.assertEqual(await items.to_list(), [1, 3])

                await items.remove(1)
                self.assertEqual(await items.to_list(), [3])
                self.assertEqual(await items.index(3), 0)
                self.assertEqual(await items.count(3), 1)

                await items.clear()
                self.assertEqual(await items.len(), 0)
                self.assertEqual(await items.to_list(), [])
            finally:
                client.close()

    async def test_sqlite_kv_collections_behave_like_builtin_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3", auto_start=True)
            data = KvDict(client, key_prefix="dict-values")
            tags = KvSet(client, key_prefix="set-values")
            counter = KvNumber(client, key_prefix="counter")
            try:
                await data.update({"a": 1, "b": {"nested": True}})
                self.assertEqual(await data.len(), 2)
                self.assertEqual(await data.get("b"), {"nested": True})
                self.assertTrue(await data.contains("a"))
                self.assertEqual(await data.pop("a"), 1)
                self.assertEqual(await data.to_dict(), {"b": {"nested": True}})

                self.assertTrue(await tags.add("red"))
                self.assertFalse(await tags.add("red"))
                self.assertEqual(await tags.update(["green", "blue"]), 2)
                self.assertTrue(await tags.contains("green"))
                await tags.remove("red")
                self.assertEqual(await tags.to_set(), {"blue", "green"})

                self.assertEqual(await counter.set(10), 10)
                self.assertEqual(await counter.incr(), 11)
                self.assertEqual(await counter.add(0.5), 11.5)
                self.assertEqual(await counter.sub(1.5), 10)
            finally:
                await data.clear()
                await tags.clear()
                await counter.clear()
                client.close()

    async def test_sqlite_kv_lock_blocks_competing_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3", auto_start=True)
            first = KvLock(client, key_prefix="shared-lock")
            second = KvLock(client, key_prefix="shared-lock")
            try:
                self.assertTrue(await first.acquire())
                self.assertFalse(await second.acquire(timeout=0.05, retry_interval=0.01))
                self.assertTrue(await first.release())
                self.assertTrue(await second.acquire(timeout=0.5, retry_interval=0.01))
                self.assertTrue(await second.release())
            finally:
                client.close()

    async def test_sqlite_kv_list_uses_multiple_internal_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3", auto_start=True)
            items = KvList(client, key_prefix="segments")
            try:
                await items.extend(["a", "b", "c"])
                keys = await client.keys(prefix="segments:")
                self.assertIn("segments:meta", keys)
                self.assertGreaterEqual(len([key for key in keys if key.startswith("segments:item:")]), 3)
            finally:
                client.close()


class TestRedisKvList(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import redis

            redis.Redis.from_url("redis://127.0.0.1:6379/0").ping()
        except Exception as exc:
            raise unittest.SkipTest(f"Redis not available for KvList tests: {exc}") from exc
        super().setUpClass()

    async def test_redis_kv_list_uses_native_list(self) -> None:
        client = RedisKVClient(
            url="redis://127.0.0.1:6379/0",
            prefix=f"test:kvlist:redis:{_SUFFIX}",
            namespace="redis-kv-list",
            auto_start=True,
        )
        items = KvList(client, key_prefix="values")
        try:
            await items.extend([1, 2, 4])
            await items.insert(2, 3)
            self.assertEqual(await items.to_list(), [1, 2, 3, 4])
            self.assertEqual(await items.pop(0), 1)
            self.assertEqual(await items.get(-1), 4)

            redis_client = await client._ensure_ready()
            raw_type = await redis_client.type(items._redis_key())
            key_type = raw_type.decode("utf-8") if isinstance(raw_type, bytes) else str(raw_type)
            self.assertEqual(key_type, "list")
        finally:
            await items.clear()
            client.close()

    async def test_redis_kv_collections_use_native_types(self) -> None:
        client = RedisKVClient(
            url="redis://127.0.0.1:6379/0",
            prefix=f"test:kvcollections:redis:{_SUFFIX}",
            namespace="redis-kv-collections",
            auto_start=True,
        )
        data = KvDict(client, key_prefix="data")
        tags = KvSet(client, key_prefix="tags")
        counter = KvNumber(client, key_prefix="counter")
        try:
            await data.update({"a": 1, "b": 2})
            await tags.update(["x", "y", "x"])
            self.assertEqual(await counter.set(1), 1)
            self.assertEqual(await counter.incr(4), 5)

            self.assertEqual(await data.to_dict(), {"a": 1, "b": 2})
            self.assertEqual(await tags.to_set(), {"x", "y"})
            self.assertEqual(await counter.get(), 5)

            redis_client = await client._ensure_ready()
            raw_types = await redis_client.pipeline(transaction=False).type(data._redis_key()).type(tags._redis_key()).type(counter._redis_key()).execute()
            key_types = [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in raw_types]
            self.assertEqual(key_types, ["hash", "set", "string"])
        finally:
            await data.clear()
            await tags.clear()
            await counter.clear()
            client.close()

    async def test_redis_kv_lock_blocks_competing_owner(self) -> None:
        client = RedisKVClient(
            url="redis://127.0.0.1:6379/0",
            prefix=f"test:kvlock:redis:{_SUFFIX}",
            namespace="redis-kv-lock",
            auto_start=True,
        )
        first = KvLock(client, key_prefix="shared-lock")
        second = KvLock(client, key_prefix="shared-lock")
        try:
            self.assertTrue(await first.acquire())
            self.assertFalse(await second.acquire(timeout=0.05, retry_interval=0.01))
            self.assertTrue(await first.release())
            self.assertTrue(await second.acquire(timeout=0.5, retry_interval=0.01))
            self.assertTrue(await second.release())
        finally:
            client.close()


class TestEtcdKvList(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import httpx

            resp = httpx.post(
                f"http://127.0.0.1:{_ETCD_PORT}/v3/maintenance/status",
                json={},
                timeout=5,
                trust_env=False,
            )
            resp.raise_for_status()
        except Exception as exc:
            raise unittest.SkipTest(f"etcd not available for KvList tests: {exc}") from exc
        super().setUpClass()

    async def test_etcd_kv_list_round_trip(self) -> None:
        client = EtcdKVClient(
            host="127.0.0.1",
            port=_ETCD_PORT,
            protocol="http",
            prefix=f"test:kvlist:etcd:{_SUFFIX}",
            namespace="etcd-kv-list",
            auto_start=True,
        )
        items = KvList(client, key_prefix="values")
        try:
            await items.extend(["a", "c"])
            await items.insert(1, "b")
            self.assertEqual(await items.to_list(), ["a", "b", "c"])
            self.assertEqual([value async for value in items], ["a", "b", "c"])
            self.assertEqual(await items.pop(), "c")

            keys = await client.keys(prefix="values:")
            self.assertIn("values:meta", keys)
            self.assertGreaterEqual(len([key for key in keys if key.startswith("values:item:")]), 2)
        finally:
            await items.clear()
            client.close()

    async def test_etcd_kv_collections_round_trip(self) -> None:
        client = EtcdKVClient(
            host="127.0.0.1",
            port=_ETCD_PORT,
            protocol="http",
            prefix=f"test:kvcollections:etcd:{_SUFFIX}",
            namespace="etcd-kv-collections",
            auto_start=True,
        )
        data = KvDict(client, key_prefix="data")
        tags = KvSet(client, key_prefix="tags")
        counter = KvNumber(client, key_prefix="counter")
        try:
            await data.update({"a": 1, "b": 2})
            await tags.update(["x", "y", "x"])
            self.assertEqual(await counter.set(2), 2)
            self.assertEqual(await counter.add(0.25), 2.25)

            self.assertEqual(await data.items(), [("a", 1), ("b", 2)])
            self.assertEqual(await tags.to_set(), {"x", "y"})
            self.assertEqual(await counter.get(), 2.25)

            keys = await client.keys(prefix="data:item:")
            self.assertEqual(len(keys), 2)
        finally:
            await data.clear()
            await tags.clear()
            await counter.clear()
            client.close()

    async def test_etcd_kv_lock_blocks_competing_owner(self) -> None:
        client = EtcdKVClient(
            host="127.0.0.1",
            port=_ETCD_PORT,
            protocol="http",
            prefix=f"test:kvlock:etcd:{_SUFFIX}",
            namespace="etcd-kv-lock",
            auto_start=True,
        )
        first = KvLock(client, key_prefix="shared-lock")
        second = KvLock(client, key_prefix="shared-lock")
        try:
            self.assertTrue(await first.acquire())
            self.assertFalse(await second.acquire(timeout=0.05, retry_interval=0.01))
            self.assertTrue(await first.release())
            self.assertTrue(await second.acquire(timeout=0.5, retry_interval=0.01))
            self.assertTrue(await second.release())
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()