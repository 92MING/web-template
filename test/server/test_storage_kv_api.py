# -*- coding: utf-8 -*-
"""Tests for KV Storage API endpoints (/_internal/admin/api/storage/kv/*)."""


import base64
import json
import unittest

from _test_helpers import StorageKVTestBase
from _test_helpers import _make_storage_config
from core.storage.config import KV_StorageConfig, LocalKVDBConfig, StorageConfig


class TestKVConfig(StorageKVTestBase):
    """GET /_internal/admin/api/storage/kv/config"""

    async def test_config_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/config")
        self.assertEqual(resp.status_code, 200)

    async def test_config_has_required_fields(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/config")
        data = resp.json()
        for key in ("backend", "namespace", "supports_binary", "supports_bulk_delete", "supports_copy", "supports_rename"):
            self.assertIn(key, data, f"Missing '{key}' in config response")

    async def test_config_backend_type(self):
        data = (await self._client.get("/_internal/admin/api/storage/kv/config")).json()
        # Should be 'sqlite' since LocalKVDBConfig is the SQLite-backed KV backend
        self.assertIsInstance(data["backend"], str)
        self.assertEqual(data["backend"], "sqlite")


class TestKVKeys(StorageKVTestBase):
    """GET /_internal/admin/api/storage/kv/keys"""

    async def test_keys_empty_initially(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/keys")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("page", data)
        self.assertIn("page_size", data)

    async def test_keys_pagination_params(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"page": 1, "page_size": 10})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 10)

    async def test_keys_with_prefix_filter(self):
        # Put two keys with different prefixes
        await self._client.put("/_internal/admin/api/storage/kv/item", params={"key": "alpha:one"},
                               json={"mode": "json", "value": 1})
        await self._client.put("/_internal/admin/api/storage/kv/item", params={"key": "beta:two"},
                               json={"mode": "json", "value": 2})
        resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "alpha:"})
        data = resp.json()
        keys = [item["key"] for item in data["items"]]
        self.assertTrue(all(k.startswith("alpha:") for k in keys))
        # Cleanup
        await self._client.delete("/_internal/admin/api/storage/kv/item", params={"key": "alpha:one"})
        await self._client.delete("/_internal/admin/api/storage/kv/item", params={"key": "beta:two"})

    async def test_keys_support_wildcard_pattern_filter(self):
        await self._client.put("/_internal/admin/api/storage/kv/item", params={"key": "wild:user:1"}, json={"mode": "json", "value": 1})
        await self._client.put("/_internal/admin/api/storage/kv/item", params={"key": "wild:session:1"}, json={"mode": "json", "value": 2})

        resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "wild:", "pattern": "*user:*"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual([item["key"] for item in data["items"]], ["wild:user:1"])
        self.assertEqual(data["pattern"], "*user:*")

    async def test_keys_support_value_kind_filter(self):
        await self._client.put("/_internal/admin/api/storage/kv/item", params={"key": "typed:object"}, json={"mode": "json", "value": {"a": 1}})
        await self._client.put("/_internal/admin/api/storage/kv/item", params={"key": "typed:text"}, json={"mode": "text", "value": "hello"})

        resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "typed:", "value_kind": "object"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual([item["key"] for item in data["items"]], ["typed:object"])
        self.assertEqual(data["value_kind"], "object")


class TestKVSummary(StorageKVTestBase):
    """GET /_internal/admin/api/storage/kv/summary"""

    async def test_summary_includes_value_insight_fields(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "summary:json"},
            json={"mode": "json", "value": {"alpha": 1, "beta": [1, 2, 3]}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "summary:text"},
            json={"mode": "text", "value": "hello summary"},
        )

        resp = await self._client.get("/_internal/admin/api/storage/kv/summary", params={"prefix": "summary:"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("type_counts", data)
        self.assertIn("largest_items", data)
        self.assertIn("value_sampled_count", data)
        self.assertIn("sampled_value_bytes", data)
        self.assertGreaterEqual(data["value_sampled_count"], 2)

        labels = {item["label"] for item in data["type_counts"]}
        self.assertIn("object", labels)
        self.assertIn("string", labels)
        self.assertTrue(any(item["key"].startswith("summary:") for item in data["largest_items"]))

    async def test_summary_supports_value_kind_filter(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "summary-filter:json"},
            json={"mode": "json", "value": {"alpha": 1}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "summary-filter:text"},
            json={"mode": "text", "value": "hello"},
        )

        resp = await self._client.get("/_internal/admin/api/storage/kv/summary", params={"prefix": "summary-filter:", "value_kind": "string"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["matched_total"], 1)
        self.assertEqual(data["value_kind"], "string")
        labels = {item["label"] for item in data["type_counts"]}
        self.assertEqual(labels, {"string"})


class TestKVItem(StorageKVTestBase):
    """PUT / GET / PATCH / DELETE on /_internal/admin/api/storage/kv/item"""

    async def test_put_json_value(self):
        resp = await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "test_json_key"},
            json={"mode": "json", "value": {"hello": "world"}},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["key"], "test_json_key")

    async def test_get_json_value(self):
        # Set first
        await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "get_test"},
            json={"mode": "json", "value": {"num": 42}},
        )
        resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "get_test"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["key"], "get_test")
        self.assertTrue(data["exists"])
        self.assertIn("value_kind", data)
        # The stored value should be a dict (object)
        self.assertEqual(data["value_kind"], "object")
        self.assertEqual(data["value"]["num"], 42)

    async def test_get_nonexistent_key_returns_404(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "no_such_key_xyz"})
        self.assertEqual(resp.status_code, 404)

    async def test_put_text_mode(self):
        resp = await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "text_key"},
            json={"mode": "text", "value": "plain text content"},
        )
        self.assertEqual(resp.status_code, 200)
        get_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "text_key"})
        data = get_resp.json()
        self.assertEqual(data["value_kind"], "string")
        self.assertEqual(data["value"], "plain text content")

    async def test_put_base64_mode(self):
        raw = b"binary data \x00\x01\x02"
        encoded = base64.b64encode(raw).decode("ascii")
        resp = await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "b64_key"},
            json={"mode": "base64", "value": encoded},
        )
        self.assertEqual(resp.status_code, 200)
        get_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "b64_key"})
        data = get_resp.json()
        self.assertEqual(data["value_kind"], "bytes")
        self.assertEqual(data["display_mode"], "base64")

    async def test_put_invalid_base64_returns_400(self):
        resp = await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "bad_b64"},
            json={"mode": "base64", "value": "not-valid-base64!!!"},
        )
        self.assertEqual(resp.status_code, 400)

    async def test_patch_ttl(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "ttl_key"},
            json={"mode": "json", "value": "ttl_val"},
        )
        resp = await self._client.patch(
            "/_internal/admin/api/storage/kv/item/ttl", params={"key": "ttl_key"},
            json={"expire_seconds": 3600},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["ttl_state"], "expiring")
        self.assertGreater(data["ttl_seconds"], 0)

    async def test_patch_ttl_nonexistent_returns_404(self):
        resp = await self._client.patch(
            "/_internal/admin/api/storage/kv/item/ttl", params={"key": "no_key_here"},
            json={"expire_seconds": 100},
        )
        self.assertEqual(resp.status_code, 404)

    async def test_delete_key(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "del_key"},
            json={"mode": "json", "value": "byebye"},
        )
        resp = await self._client.delete("/_internal/admin/api/storage/kv/item", params={"key": "del_key"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["deleted"])
        # Confirm gone
        get_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "del_key"})
        self.assertEqual(get_resp.status_code, 404)

    async def test_put_with_expire(self):
        resp = await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "expire_key"},
            json={"mode": "json", "value": 123, "expire_seconds": 60},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["ttl_state"], "expiring")

    async def test_put_overwrite(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "ow_key"},
            json={"mode": "json", "value": "first"},
        )
        await self._client.put(
            "/_internal/admin/api/storage/kv/item", params={"key": "ow_key"},
            json={"mode": "json", "value": "second"},
        )
        resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "ow_key"})
        self.assertEqual(resp.json()["value"], "second")

    async def test_get_json_null_value(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "null_key"},
            json={"mode": "json", "value": None},
        )
        resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "null_key"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["exists"])
        self.assertEqual(data["value_kind"], "null")
        self.assertIsNone(data["value"])


class StrictClientSelectionKVTestBase(StorageKVTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        base = _make_storage_config(tmp)
        return StorageConfig(
            kv=KV_StorageConfig(
                default=LocalKVDBConfig(db_path=base.kv.default.db_path, namespace="default-kv"),
                cache=LocalKVDBConfig(db_path=base.kv.cache.db_path, namespace="cache-kv"),
                extra={
                    "analytics": LocalKVDBConfig(db_path=f"{tmp}/kv_analytics.sqlite3", namespace="analytics-kv"),
                },
            ),
            orm=base.orm,
            object=base.object,
            vector=base.vector,
        )


class TestKVClientSelection(StrictClientSelectionKVTestBase):
    async def test_config_resolves_exact_named_client(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/config", params={"client": "analytics"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["client_name"], "analytics")
        self.assertEqual(data["namespace"], "analytics-kv")

    async def test_unknown_client_does_not_fallback_or_fuzzy_match(self):
        resp = await self._client.get("/_internal/admin/api/storage/kv/config", params={"client": "analyticsz"})
        self.assertEqual(resp.status_code, 404)
        self.assertIn("analyticsz", resp.text)


class TestKVBulkOperations(StorageKVTestBase):
    """POST /_internal/admin/api/storage/kv/delete-by-prefix, POST /_internal/admin/api/storage/kv/cleanup"""

    async def test_delete_by_prefix_dry_run(self):
        # Insert keys
        for i in range(3):
            await self._client.put(
                "/_internal/admin/api/storage/kv/item", params={"key": f"bulk:item:{i}"},
                json={"mode": "json", "value": i},
            )
        resp = await self._client.post(
            "/_internal/admin/api/storage/kv/delete-by-prefix",
            json={"prefix": "bulk:", "dry_run": True, "limit": 100},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["matched"], 3)
        self.assertEqual(data["deleted"], 0)  # dry run = no actual deletion
        # Confirm keys still exist
        keys_resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "bulk:"})
        self.assertGreaterEqual(keys_resp.json()["total"], 3)

    async def test_delete_by_prefix_actual(self):
        for i in range(3):
            await self._client.put(
                "/_internal/admin/api/storage/kv/item", params={"key": f"delpfx:{i}"},
                json={"mode": "json", "value": i},
            )
        resp = await self._client.post(
            "/_internal/admin/api/storage/kv/delete-by-prefix",
            json={"prefix": "delpfx:", "dry_run": False, "limit": 100},
        )
        data = resp.json()
        self.assertGreaterEqual(data["deleted"], 3)
        # Confirm gone
        keys_resp = await self._client.get("/_internal/admin/api/storage/kv/keys", params={"prefix": "delpfx:"})
        self.assertEqual(keys_resp.json()["total"], 0)

    async def test_cleanup(self):
        resp = await self._client.post("/_internal/admin/api/storage/kv/cleanup")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("removed", data)
        self.assertIsInstance(data["removed"], int)


class TestKVTransferOperations(StorageKVTestBase):
    """POST /_internal/admin/api/storage/kv/item/copy and /_internal/admin/api/storage/kv/item/rename"""

    async def test_copy_item_preserves_value_and_ttl(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "copy:source"},
            json={"mode": "json", "value": {"hello": "world"}, "expire_seconds": 120},
        )

        resp = await self._client.post(
            "/_internal/admin/api/storage/kv/item/copy",
            json={"source_key": "copy:source", "target_key": "copy:target", "preserve_ttl": True},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "copy")
        self.assertEqual(data["target_key"], "copy:target")
        self.assertEqual(data["ttl_state"], "expiring")

        source_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "copy:source"})
        target_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "copy:target"})
        self.assertEqual(source_resp.status_code, 200)
        self.assertEqual(target_resp.status_code, 200)
        self.assertEqual(target_resp.json()["value"], {"hello": "world"})

    async def test_rename_item_moves_key(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "rename:source"},
            json={"mode": "text", "value": "rename-me"},
        )

        resp = await self._client.post(
            "/_internal/admin/api/storage/kv/item/rename",
            json={"source_key": "rename:source", "target_key": "rename:target", "preserve_ttl": True},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "rename")
        self.assertTrue(data["source_deleted"])

        source_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "rename:source"})
        target_resp = await self._client.get("/_internal/admin/api/storage/kv/item", params={"key": "rename:target"})
        self.assertEqual(source_resp.status_code, 404)
        self.assertEqual(target_resp.status_code, 200)
        self.assertEqual(target_resp.json()["value"], "rename-me")

    async def test_copy_item_rejects_existing_target_without_overwrite(self):
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "copy:conflict:source"},
            json={"mode": "json", "value": 1},
        )
        await self._client.put(
            "/_internal/admin/api/storage/kv/item",
            params={"key": "copy:conflict:target"},
            json={"mode": "json", "value": 2},
        )

        resp = await self._client.post(
            "/_internal/admin/api/storage/kv/item/copy",
            json={"source_key": "copy:conflict:source", "target_key": "copy:conflict:target", "overwrite": False},
        )
        self.assertEqual(resp.status_code, 409)


if __name__ == "__main__":
    unittest.main()
