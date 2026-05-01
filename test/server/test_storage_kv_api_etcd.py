# -*- coding: utf-8 -*-
"""etcd-backed smoke tests for KV Storage API endpoints (/_internal/admin/api/storage/kv/*)."""


import unittest

from _test_helpers import StorageEtcdKVTestBase


class TestEtcdKVConfig(StorageEtcdKVTestBase):
    async def test_config_reports_etcd_backend(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/config")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["backend"], "etcd")


class TestEtcdKVItem(StorageEtcdKVTestBase):
    async def test_put_get_delete_json_value(self):
        put_resp = await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "etcd:item:json"},
            json={"mode": "json", "value": {"hello": "etcd", "count": 3}},
        )
        self.assertEqual(put_resp.status_code, 200)

        get_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "etcd:item:json"})
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["value"], {"hello": "etcd", "count": 3})

        delete_resp = await self._client.delete("/_internal/admin/api/storage/kv/item", params={"key": "etcd:item:json"})
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])

    async def test_patch_ttl_updates_existing_key(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "etcd:item:ttl"},
            json={"mode": "json", "value": "ttl-test"},
        )

        ttl_resp = await self._client.patch(
            "/_internal/admin/api/storage/kv/item/ttl",
            params={"key": "etcd:item:ttl"},
            json={"expire_seconds": 120},
        )
        self.assertEqual(ttl_resp.status_code, 200)
        self.assertTrue(ttl_resp.json()["ok"])
        self.assertEqual(ttl_resp.json()["ttl_state"], "expiring")
        self.assertGreater(ttl_resp.json()["ttl_seconds"], 0)


class TestEtcdKVBulkOperations(StorageEtcdKVTestBase):
    async def test_keys_and_delete_by_prefix(self):
        for index in range(3):
            await self._client.put(
                "/_internal/admin/api/storage/kv/item",
                params={"key": f"etcd:bulk:{index}"},
                json={"mode": "json", "value": index},
            )

        keys_resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "etcd:bulk:"})
        self.assertEqual(keys_resp.status_code, 200)
        self.assertEqual(keys_resp.json()["total"], 3)

        delete_resp = await self._client.post(
            "/_internal/admin/api/storage/kv/delete-by-prefix",
            json={"prefix": "etcd:bulk:", "dry_run": False, "limit": 100},
        )
        self.assertEqual(delete_resp.status_code, 200)
        self.assertEqual(delete_resp.json()["deleted"], 3)

        after_resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "etcd:bulk:"})
        self.assertEqual(after_resp.status_code, 200)
        self.assertEqual(after_resp.json()["total"], 0)


if __name__ == "__main__":
    unittest.main()