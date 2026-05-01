"""
Direct integration tests for ``EtcdKVClient`` against a **real** etcd Docker
container (proj-etcd-test, 127.0.0.1:23791 → 2379).

Run::

    python -m pytest test/storage/test_etcd_kv_integration.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import os
import time
import unittest

# ---------------------------------------------------------------------------
# Connection parameters
# ---------------------------------------------------------------------------
ETCD_HOST = os.getenv("TEST_ETCD_HOST", "127.0.0.1")
ETCD_PORT = int(os.getenv("TEST_ETCD_PORT", "23791"))

_TS = str(int(time.time() * 1000))[-8:]  # unique suffix per run


def _make_client(namespace: str = "test") -> "EtcdKVClient":
    from core.storage.kv import EtcdKVClient

    return EtcdKVClient(
        host=ETCD_HOST,
        port=ETCD_PORT,
        prefix=f"proj_test_{_TS}",
        namespace=namespace,
        auto_start=True,
    )


def setUpModule():
    """Skip entire module if etcd not reachable."""
    try:
        c = _make_client("probe")
        c.close()
    except Exception as exc:
        raise unittest.SkipTest(f"etcd not reachable at {ETCD_HOST}:{ETCD_PORT}: {exc}")


# ── helpers ────────────────────────────────────────────────────────────────
from core.storage.kv import EtcdKVClient


class _EtcdTestBase(unittest.IsolatedAsyncioTestCase):
    """Common setUp/tearDown — fresh client per test, track keys for cleanup."""

    _ns: str = "default"
    _cleanup_keys: list[str]

    async def asyncSetUp(self):
        self.client = _make_client(self._ns)
        self._cleanup_keys = []

    async def asyncTearDown(self):
        for key in self._cleanup_keys:
            try:
                await self.client.delete(key)
            except Exception:
                pass
        self.client.close()

    def _track(self, key: str) -> str:
        self._cleanup_keys.append(key)
        return key


# ═══════════════════════════════════════════════════════════════════════════
# 1. CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestEtcdCRUD(_EtcdTestBase):
    _ns = "crud"

    async def test_set_and_get_string(self):
        k = self._track("str1")
        await self.client.set(k, "hello etcd")
        val = await self.client.get(k)
        self.assertEqual(val, "hello etcd")

    async def test_set_and_get_int(self):
        k = self._track("int1")
        await self.client.set(k, 42)
        val = await self.client.get(k)
        self.assertEqual(val, 42)

    async def test_set_and_get_float(self):
        k = self._track("f1")
        await self.client.set(k, 3.14)
        val = await self.client.get(k)
        self.assertAlmostEqual(val, 3.14, places=5)

    async def test_set_and_get_dict(self):
        k = self._track("dict1")
        payload = {"a": 1, "b": [2, 3], "c": {"nested": True}}
        await self.client.set(k, payload)
        val = await self.client.get(k)
        self.assertEqual(val, payload)

    async def test_set_and_get_list(self):
        k = self._track("list1")
        payload = [1, "two", 3.0, None]
        await self.client.set(k, payload)
        val = await self.client.get(k)
        self.assertEqual(val, payload)

    async def test_set_and_get_none(self):
        k = self._track("none1")
        await self.client.set(k, None)
        val = await self.client.get(k)
        self.assertIsNone(val)

    async def test_set_and_get_bool(self):
        k = self._track("bool1")
        await self.client.set(k, True)
        val = await self.client.get(k)
        self.assertTrue(val)

    async def test_set_and_get_bytes(self):
        k = self._track("bytes1")
        await self.client.set(k, b"\x00\x01\xff")
        val = await self.client.get(k)
        self.assertEqual(val, b"\x00\x01\xff")

    async def test_get_nonexistent_returns_default(self):
        val = await self.client.get("nonexistent_key_xyz", default="fallback")
        self.assertEqual(val, "fallback")

    async def test_get_nonexistent_returns_none(self):
        val = await self.client.get("nonexistent_key_xyz2")
        self.assertIsNone(val)

    async def test_overwrite(self):
        k = self._track("overwrite1")
        await self.client.set(k, "v1")
        await self.client.set(k, "v2")
        val = await self.client.get(k)
        self.assertEqual(val, "v2")

    async def test_delete_existing(self):
        k = self._track("del1")
        await self.client.set(k, "deleteme")
        result = await self.client.delete(k)
        self.assertTrue(result)
        val = await self.client.get(k)
        self.assertIsNone(val)

    async def test_delete_nonexistent(self):
        result = await self.client.delete("never_existed_xyz")
        self.assertFalse(result)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Expire / TTL
# ═══════════════════════════════════════════════════════════════════════════
class TestEtcdExpire(_EtcdTestBase):
    _ns = "expire"

    async def test_set_with_expire(self):
        k = self._track("ttl1")
        await self.client.set(k, "temporary", expire=60)
        val = await self.client.get(k)
        self.assertEqual(val, "temporary")
        ttl = await self.client.get_expire(k)
        self.assertIsNotNone(ttl)
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, 60)

    async def test_set_expire_after_creation(self):
        k = self._track("ttl2")
        await self.client.set(k, "will_expire")
        # Initially no TTL
        ttl_before = await self.client.get_expire(k)
        self.assertIsNone(ttl_before)
        # Set expire
        result = await self.client.set_expire(k, 120)
        self.assertTrue(result)
        ttl_after = await self.client.get_expire(k)
        self.assertIsNotNone(ttl_after)
        self.assertGreater(ttl_after, 0)
        self.assertLessEqual(ttl_after, 120)

    async def test_set_expire_on_nonexistent(self):
        result = await self.client.set_expire("no_such_key_xyz", 60)
        self.assertFalse(result)

    async def test_get_expire_on_nonexistent(self):
        ttl = await self.client.get_expire("no_such_key_xyz2")
        self.assertIsNone(ttl)

    async def test_remove_expire(self):
        k = self._track("ttl3")
        await self.client.set(k, "was_temp", expire=60)
        ttl1 = await self.client.get_expire(k)
        self.assertIsNotNone(ttl1)
        # Remove TTL by re-setting without expire
        await self.client.set(k, "was_temp")
        ttl2 = await self.client.get_expire(k)
        self.assertIsNone(ttl2)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Keys listing
# ═══════════════════════════════════════════════════════════════════════════
class TestEtcdKeys(_EtcdTestBase):
    _ns = "keys"

    async def test_keys_empty(self):
        keys = await self.client.keys()
        # May or may not be empty (other tests), but should be a list
        self.assertIsInstance(keys, list)

    async def test_keys_after_set(self):
        k1 = self._track("a_key")
        k2 = self._track("b_key")
        await self.client.set(k1, "val1")
        await self.client.set(k2, "val2")
        keys = await self.client.keys()
        self.assertIn(k1, keys)
        self.assertIn(k2, keys)

    async def test_keys_with_prefix(self):
        k1 = self._track("prefix_alpha")
        k2 = self._track("prefix_beta")
        k3 = self._track("other_gamma")
        await self.client.set(k1, 1)
        await self.client.set(k2, 2)
        await self.client.set(k3, 3)
        keys = await self.client.keys(prefix="prefix_")
        self.assertIn(k1, keys)
        self.assertIn(k2, keys)
        self.assertNotIn(k3, keys)

    async def test_keys_after_delete(self):
        k = self._track("del_me")
        await self.client.set(k, "will_be_gone")
        keys1 = await self.client.keys()
        self.assertIn(k, keys1)
        await self.client.delete(k)
        keys2 = await self.client.keys()
        self.assertNotIn(k, keys2)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Namespace isolation
# ═══════════════════════════════════════════════════════════════════════════
class TestEtcdNamespaceIsolation(unittest.IsolatedAsyncioTestCase):

    async def test_different_namespaces_isolated(self):
        c1 = _make_client("ns_alpha")
        c2 = _make_client("ns_beta")
        try:
            await c1.set("shared_key", "from_alpha")
            await c2.set("shared_key", "from_beta")
            v1 = await c1.get("shared_key")
            v2 = await c2.get("shared_key")
            self.assertEqual(v1, "from_alpha")
            self.assertEqual(v2, "from_beta")
        finally:
            await c1.delete("shared_key")
            await c2.delete("shared_key")
            c1.close()
            c2.close()


# ═══════════════════════════════════════════════════════════════════════════
# 5. target_type deserialization
# ═══════════════════════════════════════════════════════════════════════════
class TestEtcdTargetType(_EtcdTestBase):
    _ns = "ttype"

    async def test_get_with_target_type_str(self):
        k = self._track("tt_str")
        await self.client.set(k, 123)
        val = await self.client.get(k, target_type=str)
        self.assertIsInstance(val, str)

    async def test_get_with_target_type_int(self):
        k = self._track("tt_int")
        await self.client.set(k, "456")
        val = await self.client.get(k, target_type=int)
        self.assertEqual(val, 456)

    async def test_get_with_target_type_dict(self):
        k = self._track("tt_dict")
        await self.client.set(k, {"x": 1, "y": 2})
        val = await self.client.get(k, target_type=dict)
        self.assertIsInstance(val, dict)
        self.assertEqual(val["x"], 1)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Cleanup
# ═══════════════════════════════════════════════════════════════════════════
class TestEtcdCleanup(_EtcdTestBase):
    _ns = "cleanup"

    async def test_cleanup_runs_without_error(self):
        k = self._track("clean1")
        await self.client.set(k, "some data")
        removed = await self.client.cleanup(force=True)
        self.assertIsInstance(removed, int)
        self.assertGreaterEqual(removed, 0)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Large values
# ═══════════════════════════════════════════════════════════════════════════
class TestEtcdLargeValues(_EtcdTestBase):
    _ns = "large"

    async def test_large_string(self):
        k = self._track("big_str")
        big = "x" * 100_000
        await self.client.set(k, big)
        val = await self.client.get(k)
        self.assertEqual(val, big)

    async def test_large_dict(self):
        k = self._track("big_dict")
        big = {f"key_{i}": f"value_{i}" for i in range(500)}
        await self.client.set(k, big)
        val = await self.client.get(k)
        self.assertEqual(val, big)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Start / Close lifecycle
# ═══════════════════════════════════════════════════════════════════════════
class TestEtcdLifecycle(unittest.IsolatedAsyncioTestCase):

    async def test_start_idempotent(self):
        c = _make_client("lifecycle")
        try:
            c.start()
            c.start()  # should not raise
            await c.set("lc_key", "ok")
            val = await c.get("lc_key")
            self.assertEqual(val, "ok")
        finally:
            await c.delete("lc_key")
            c.close()

    async def test_close_and_restart(self):
        c = _make_client("lifecycle2")
        try:
            await c.set("lc2_key", "before")
            c.close()
            c.start()
            val = await c.get("lc2_key")
            self.assertEqual(val, "before")
        finally:
            await c.delete("lc2_key")
            c.close()

    async def test_double_close(self):
        c = _make_client("lifecycle3")
        c.close()
        c.close()  # should not raise


if __name__ == "__main__":
    unittest.main()
