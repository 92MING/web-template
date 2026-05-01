# -*- coding: utf-8 -*-
"""Redis-backed smoke tests for KV Storage API endpoints (/_internal/admin/api/storage/kv/*)."""


import unittest

from _test_helpers import StorageRedisKVTestBase


class TestRedisKVConfig(StorageRedisKVTestBase):
    async def test_config_reports_redis_backend(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["backend"], "redis")


class TestRedisKVItem(StorageRedisKVTestBase):
    async def test_put_get_delete_json_value(self):
        resp = await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "redis:item:json"},
            json={"mode": "json", "value": {"hello": "redis", "count": 3}},
        )
        self.assertEqual(resp.status_code, 200)

        get_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "redis:item:json"})
        self.assertEqual(get_resp.status_code, 200)
        data = get_resp.json()
        self.assertEqual(data["value_kind"], "object")
        self.assertEqual(data["value"], {"hello": "redis", "count": 3})

        delete_resp = await self._client.delete("/_internal/admin/api/storage/kv/item", params={"key": "redis:item:json"})
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])

        missing_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "redis:item:json"})
        self.assertEqual(missing_resp.status_code, 404)

    async def test_patch_ttl_updates_existing_key(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "redis:item:ttl"},
            json={"mode": "json", "value": "ttl-test"},
        )

        resp = await self._client.patch(
            "/_internal/admin/api/storage/kv/item/ttl",
            params={"key": "redis:item:ttl"},
            json={"expire_seconds": 120},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["ttl_state"], "expiring")
        self.assertGreater(data["ttl_seconds"], 0)

        await self._client.delete("/_internal/admin/api/storage/kv/item", params={"key": "redis:item:ttl"})


class TestRedisKVBulkOperations(StorageRedisKVTestBase):
    async def test_keys_and_delete_by_prefix(self):
        for index in range(3):
            await self._client.put(
                "/_internal/admin/api/storage/kv/item",
                params={"key": f"redis:bulk:{index}"},
                json={"mode": "json", "value": index},
            )

        keys_resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "redis:bulk:"})
        self.assertEqual(keys_resp.status_code, 200)
        keys_data = keys_resp.json()
        self.assertEqual(keys_data["total"], 3)

        delete_resp = await self._client.post(
            "/_internal/admin/api/storage/kv/delete-by-prefix",
            json={"prefix": "redis:bulk:", "dry_run": False, "limit": 100},
        )
        self.assertEqual(delete_resp.status_code, 200)
        delete_data = delete_resp.json()
        self.assertEqual(delete_data["deleted"], 3)

        keys_resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "redis:bulk:"})
        self.assertEqual(keys_resp.json()["total"], 0)


if __name__ == "__main__":
    unittest.main()