from __future__ import annotations

import os
import time
import unittest

from core.storage.kv import EtcdKVClient, RedisKVClient


_SUFFIX = str(time.time_ns())[-10:]
_ETCD_PORT = int(os.getenv("TEST_ETCD_PORT", "23791"))


def _make_redis_client(namespace: str) -> RedisKVClient:
    return RedisKVClient(
        url="redis://127.0.0.1:6379/0",
        prefix=f"test:open-namespace:redis:{_SUFFIX}:{namespace}",
        namespace=namespace,
        auto_start=True,
    )


def _make_etcd_client(namespace: str) -> EtcdKVClient:
    return EtcdKVClient(
        host="127.0.0.1",
        port=_ETCD_PORT,
        protocol="http",
        prefix=f"test:open-namespace:etcd:{_SUFFIX}:{namespace}",
        namespace=namespace,
        auto_start=True,
    )


class _NamespaceBehaviorMixin:
    make_client: classmethod

    async def test_open_namespace_uses_parent_backend(self) -> None:
        root_namespace = f"root-{time.time_ns()}"
        parent = self.make_client(root_namespace)
        child = parent.open_namespace("child")
        sibling = parent.open_namespace("sibling")
        try:
            self.assertIsInstance(child, type(parent))
            self.assertIs(child._parent, parent)
            self.assertEqual(child._namespace, f"{root_namespace}:child")

            await child.set("alpha", {"source": "child"})

            self.assertEqual(await child.get("alpha"), {"source": "child"})
            self.assertEqual(await parent.get("child:alpha"), {"source": "child"})
            self.assertIsNone(await sibling.get("alpha"))
            self.assertEqual(await child.keys(), ["alpha"])
            self.assertEqual(await parent.keys(prefix="child:"), ["child:alpha"])
            self.assertTrue(await child.delete("alpha"))
            self.assertIsNone(await parent.get("child:alpha"))
        finally:
            parent.close()
            child.close()
            sibling.close()

    async def test_nested_namespace_lifecycle_and_ttl(self) -> None:
        root_namespace = f"root-nested-{time.time_ns()}"
        parent = self.make_client(root_namespace)
        child = parent.open_namespace("child")
        grandchild = child.open_namespace("nested")
        try:
            parent.close()
            child.close()
            grandchild.close()

            self.assertFalse(parent.started)
            self.assertFalse(child.started)
            self.assertFalse(grandchild.started)

            grandchild.start()

            self.assertTrue(parent.started)
            self.assertTrue(child.started)
            self.assertTrue(grandchild.started)

            await grandchild.set("beta", "value", expire=1)
            ttl = await grandchild.get_expire("beta")
            self.assertIsNotNone(ttl)
            self.assertGreater(ttl, 0)
            self.assertEqual(await parent.get("child:nested:beta"), "value")

            grandchild.close()
            self.assertTrue(parent.started)
            self.assertFalse(grandchild.started)
            self.assertEqual(await child.keys(prefix="nested:"), ["nested:beta"])

        finally:
            parent.close()
            child.close()
            grandchild.close()


class TestRedisNamespaceBehavior(_NamespaceBehaviorMixin, unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_client(namespace: str) -> RedisKVClient:
        return _make_redis_client(namespace)

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import redis

            redis.Redis.from_url("redis://127.0.0.1:6379/0").ping()
        except Exception as exc:
            raise unittest.SkipTest(f"Redis not available for namespace tests: {exc}") from exc
        super().setUpClass()


class TestEtcdNamespaceBehavior(_NamespaceBehaviorMixin, unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_client(namespace: str) -> EtcdKVClient:
        return _make_etcd_client(namespace)

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
            raise unittest.SkipTest(f"etcd not available for namespace tests: {exc}") from exc
        super().setUpClass()


if __name__ == "__main__":
    unittest.main()