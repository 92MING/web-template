# -*- coding: utf-8 -*-
"""Tests for ORM Storage API endpoints (/_internal/admin/api/storage/orm/*)."""


import json
import shutil
import tempfile
import unittest
from asyncio import sleep
from pathlib import Path
from unittest.mock import patch

from _test_helpers import StorageORMTestBase, _make_storage_config, register_test_orm_model
from core.storage.config import ORMStorageConfig, SQLiteORMDBConfig, StorageConfig
from core.storage.orm import ORMModel, SQLiteORMClient
from core.server.routes.storage._common import list_orm_collection_meta, orm_collection_count


_ORM_API_MODEL_SAMPLES: dict[str, dict[str, object]] = {
    "helper_coll": {"name": "Alice"},
    "test_collection": {"name": "Alice", "age": 30, "tags": ["admin"]},
    "test_get_coll": {"title": "My Doc", "body": "Content here"},
    "query_coll": {"index": 0, "label": "item_0"},
    "page_coll": {"idx": 0},
    "filter_coll": {"status": "active", "val": 1},
    "id_alias_coll": {"status": "ready"},
    "regex_coll": {"name": "Alice"},
    "wildcard_coll": {"name": "Alice"},
    "wildcard_multi_coll": {"name": "abc"},
    "unsupported_filter_coll": {"name": "Alice"},
    "del_coll": {"k": "v"},
    "exp_coll": {"data": "expires soon"},
    "ttl_coll": {"x": 1},
    "schema_coll": {"name": "test", "value": 42},
    "drop_me": {"foo": "bar"},
    "drop_recreate_diff_fields": {"val": 1, "v": 2},
    "typed_drop_recreate": {"name": "Alice", "age": 30},
}


class SchemaSourceRecord(ORMModel, collection_name="schema_source_coll"):
    title: str | None = None
    score: int | None = None


def _register_orm_api_models(testcase: StorageORMTestBase, *collections: str) -> None:
    for collection in collections:
        testcase._register_orm_model(collection, _ORM_API_MODEL_SAMPLES.get(collection))


class StrictClientSelectionORMTestBase(StorageORMTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        base = _make_storage_config(tmp)
        return StorageConfig(
            kv=base.kv,
            orm=ORMStorageConfig(
                default=SQLiteORMDBConfig(db_path=base.orm.default.db_path),
                cache=SQLiteORMDBConfig(db_path=base.orm.cache.db_path),
                log=SQLiteORMDBConfig(db_path=base.orm.log.db_path),
                extra={
                    "analytics": SQLiteORMDBConfig(db_path=str(Path(tmp) / "orm_analytics.sqlite3")),
                },
            ),
            object=base.object,
            vector=base.vector,
        )


class TestORMConfig(StorageORMTestBase):
    """GET /_internal/admin/api/storage/orm/config"""

    async def test_config_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/storage/orm/config")
        self.assertEqual(resp.status_code, 200)

    async def test_config_has_required_fields(self):
        data = (await self._client.get("/_internal/admin/api/storage/orm/config")).json()
        for key in ("backend", "namespace", "supports_ttl", "supports_drop_collection",
                     "supports_document_upsert", "supports_query_count", "supports_sort"):
            self.assertIn(key, data, f"Missing '{key}'")

    async def test_config_backend_type(self):
        data = (await self._client.get("/_internal/admin/api/storage/orm/config")).json()
        self.assertIsInstance(data["backend"], str)
        self.assertTrue(len(data["backend"]) > 0)

    async def test_config_reflects_query_count_and_sort_capabilities(self):
        storage_client = self._storage_config.get_orm_client()
        with patch.object(storage_client, "query_count", None), patch.object(storage_client, "search_sorted", None):
            data = (await self._client.get("/_internal/admin/api/storage/orm/config")).json()
        self.assertFalse(data["supports_query_count"])
        self.assertFalse(data["supports_sort"])


class TestORMCollections(StorageORMTestBase):
    """GET /_internal/admin/api/storage/orm/collections"""

    async def test_collections_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/storage/orm/collections")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertIsInstance(data["items"], list)

    async def test_collections_include_external_sqlite_table_without_registered_meta(self):
        storage_config = self._storage_config
        assert storage_config is not None
        client = storage_config.orm.get_default()
        self.assertIsInstance(client, SQLiteORMClient)

        object_id = await client.raw_set("external_shadow", {"name": "outside", "rank": 1})
        conn = await client._get_conn()
        await conn.execute("DELETE FROM _orm_collections WHERE collection_name = ?", ("external_shadow",))
        await conn.commit()
        client._forget_collection("external_shadow")

        list_resp = await self._client.get("/_internal/admin/api/storage/orm/collections")
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.json()["items"]
        shadow = next((item for item in items if item.get("name") == "external_shadow"), None)
        self.assertIsNotNone(shadow)
        assert shadow is not None
        self.assertFalse(shadow["typed_model"])

        get_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "external_shadow", "object_id": object_id},
        )
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["document"]["name"], "outside")


class TestORMClientSelection(StrictClientSelectionORMTestBase):
    async def test_config_resolves_exact_named_client(self):
        resp = await self._client.get("/_internal/admin/api/storage/orm/config", params={"client": "analytics"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["client_name"], "analytics")
        self.assertEqual(data["backend"], "sqlite")

    async def test_named_client_isolated_from_default_client(self):
        upsert_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            params={"client": "analytics"},
            json={
                "collection": "analytics_docs",
                "document": {"title": "Quarterly report", "rank": 1},
            },
        )
        self.assertEqual(upsert_resp.status_code, 200)
        object_id = upsert_resp.json()["id"]

        analytics_get = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"client": "analytics", "collection": "analytics_docs", "object_id": object_id},
        )
        self.assertEqual(analytics_get.status_code, 200)

        default_get = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "analytics_docs", "object_id": object_id},
        )
        self.assertEqual(default_get.status_code, 404)

    async def test_unknown_client_does_not_fallback_or_fuzzy_match(self):
        resp = await self._client.get("/_internal/admin/api/storage/orm/config", params={"client": "analyticss"})
        self.assertEqual(resp.status_code, 404)
        self.assertIn("analyticss", resp.text)


class TestORMIntrospectionHelpers(unittest.IsolatedAsyncioTestCase):
    class _DuckTypedFakeClient:
        def _conn(self):
            raise AssertionError("duck-typed fake client must not be treated as SQLite ORM client")

    def test_helpers_do_not_duck_type_private_sql_attrs(self):
        fake = self._DuckTypedFakeClient()
        self.assertEqual(list_orm_collection_meta(fake), [])
        self.assertIsNone(orm_collection_count(fake, "demo_collection"))

    async def test_helpers_still_support_sqlite_orm_client(self):
        tmp_dir = tempfile.mkdtemp()
        client = SQLiteORMClient(db_path=Path(tmp_dir) / "orm.sqlite3")
        client.start()
        try:
            register_test_orm_model(client, "helper_coll", _ORM_API_MODEL_SAMPLES["helper_coll"])
            await client.set({"name": "Alice"}, collection="helper_coll")
            metas = list_orm_collection_meta(client)
            self.assertIn("helper_coll", {str(item.get("collection_name")) for item in metas})
            self.assertEqual(orm_collection_count(client, "helper_coll"), 1)
        finally:
            client.close()
            await sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestORMDocumentCRUD(StorageORMTestBase):
    """PUT / GET / POST query / DELETE on ORM documents."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        _register_orm_api_models(
            self,
            "test_collection",
            "test_get_coll",
            "query_coll",
            "page_coll",
            "filter_coll",
            "id_alias_coll",
            "regex_coll",
            "wildcard_coll",
            "wildcard_multi_coll",
            "unsupported_filter_coll",
            "del_coll",
            "exp_coll",
        )

    async def test_create_document(self):
        resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={
                "collection": "test_collection",
                "document": {"name": "Alice", "age": 30, "tags": ["admin"]},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("id", data)
        self.assertEqual(data["collection"], "test_collection")

    async def test_create_document_allows_unknown_collection_without_model(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={
                "collection": "unknown_collection",
                "document": {"name": "Alice", "age": 30},
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        object_id = create_resp.json()["id"]

        get_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "unknown_collection", "object_id": object_id},
        )
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["document"]["name"], "Alice")

        query_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={
                "collection": "unknown_collection",
                "query": {"name": "Alice"},
            },
        )
        self.assertEqual(query_resp.status_code, 200)
        self.assertEqual(query_resp.json()["total"], 1)

        delete_resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "unknown_collection", "object_id": object_id},
        )
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])

    async def test_create_raw_collection_with_schema_then_write_and_query(self):
        create_collection_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/collection",
            json={
                "collection": "raw_schema_collection",
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "score": {"type": "integer"},
                    },
                    "required": ["name"],
                },
            },
        )
        self.assertEqual(create_collection_resp.status_code, 200)

        upsert_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={
                "collection": "raw_schema_collection",
                "document": {"name": "Bob", "score": 7},
            },
        )
        self.assertEqual(upsert_resp.status_code, 200)

        query_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={
                "collection": "raw_schema_collection",
                "query": {"score": 7},
            },
        )
        self.assertEqual(query_resp.status_code, 200)
        data = query_resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["document"]["name"], "Bob")

    async def test_get_document(self):
        # Create first
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={
                "collection": "test_get_coll",
                "document": {"title": "My Doc", "body": "Content here"},
            },
        )
        object_id = create_resp.json()["id"]

        # Now get it
        resp = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "test_get_coll", "object_id": object_id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], object_id)
        self.assertEqual(data["collection"], "test_get_coll")
        self.assertIn("document", data)
        self.assertEqual(data["document"]["title"], "My Doc")

    async def test_get_document_nonexistent_returns_404(self):
        resp = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "no_coll", "object_id": "no_id"},
        )
        self.assertEqual(resp.status_code, 404)

    async def test_query_documents(self):
        # Insert several documents
        for i in range(5):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={
                    "collection": "query_coll",
                    "document": {"index": i, "label": f"item_{i}"},
                },
            )
        resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={"collection": "query_coll", "limit": 50, "offset": 0},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertGreaterEqual(data["total"], 5)
        self.assertGreaterEqual(len(data["items"]), 5)

    async def test_query_selection_projects_only_requested_fields_and_id(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={
                "collection": "query_coll",
                "document": {"label": "picked", "index": 7, "nested": {"score": 9}},
            },
        )

        resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={
                "collection": "query_coll",
                "query": {"label": "picked"},
                "selection": ["label", "nested.score"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        item = resp.json()["items"][0]
        self.assertEqual(set(item["document"].keys()), {"id", "label", "nested"})
        self.assertEqual(item["document"]["label"], "picked")
        self.assertEqual(item["document"]["nested"], {"score": 9})
        self.assertNotIn("index", item["document"])

    async def test_query_selection_respects_sort_order(self):
        for value in (3, 1, 2):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={
                    "collection": "page_coll",
                    "document": {"idx": value, "extra": f"row-{value}"},
                },
            )

        resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={
                "collection": "page_coll",
                "selection": ["idx"],
                "sort": [{"field": "idx", "direction": "desc"}],
            },
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertEqual([item["document"]["idx"] for item in items[:3]], [3, 2, 1])
        self.assertTrue(all(set(item["document"].keys()) == {"id", "idx"} for item in items[:3]))

    async def test_query_with_pagination(self):
        # Ensure at least 3 items
        for i in range(3):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={
                    "collection": "page_coll",
                    "document": {"idx": i},
                },
            )
        resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={"collection": "page_coll", "limit": 2, "offset": 0},
        )
        data = resp.json()
        self.assertLessEqual(len(data["items"]), 2)
        self.assertIn("has_more", data)

    async def test_query_with_json_filter(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "filter_coll", "document": {"status": "active", "val": 1}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "filter_coll", "document": {"status": "inactive", "val": 2}},
        )
        resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={
                "collection": "filter_coll",
                "query_json": json.dumps({"status": "active"}),
            },
        )
        self.assertEqual(resp.status_code, 200)

    async def test_query_accepts_id_alias_filter(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "id_alias_coll", "document": {"_id": "alias-doc", "status": "ready"}},
        )
        self.assertEqual(create_resp.status_code, 200)

        resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={
                "collection": "id_alias_coll",
                "query": {"_id": "alias-doc"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["id"], "alias-doc")

    async def test_query_regex_uses_sqlite_pushdown(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "regex_coll", "document": {"name": "Alice"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "regex_coll", "document": {"name": "Bob"}},
        )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("sqlite regex query should be pushed down to SQL, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={
                    "collection": "regex_coll",
                    "query": {"name": {"$regex": "^Al"}},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["document"]["name"], "Alice")

    async def test_query_wildcard_uses_sqlite_pushdown(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "wildcard_coll", "document": {"name": "Alice"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "wildcard_coll", "document": {"name": "Alfred"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "wildcard_coll", "document": {"name": "Bob"}},
        )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("sqlite wildcard query should be pushed down to SQL, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={
                    "collection": "wildcard_coll",
                    "query": {"name": {"$wildcard": "Al*"}},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual({item["document"]["name"] for item in data["items"]}, {"Alice", "Alfred"})

    async def test_query_multi_segment_wildcard_uses_sqlite_pushdown(self):
        for name in ("abc", "axbyc", "abbbc", "acb"):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": "wildcard_multi_coll", "document": {"name": name}},
            )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("sqlite multi-segment wildcard query should be pushed down to SQL, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={
                    "collection": "wildcard_multi_coll",
                    "query": {"name": {"$wildcard": "a*b*c"}},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual({item["document"]["name"] for item in data["items"]}, {"abc", "axbyc", "abbbc"})

    async def test_query_rejects_non_pushdown_filter_instead_of_scanning(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "unsupported_filter_coll", "document": {"name": "Alice"}},
        )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("ORM API query should not fall back to Python filtering"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={
                    "collection": "unsupported_filter_coll",
                    "query": {"name": {"$unsupported": "Alice"}},
                },
            )

        self.assertEqual(resp.status_code, 400)

    async def test_query_batches_ttl_reads_instead_of_per_item_get_expire(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "query_coll", "document": {"index": 1, "label": "item_1"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "query_coll", "document": {"index": 2, "label": "item_2"}},
        )
        storage_client = self._storage_config.get_orm_client()

        with patch.object(
            storage_client,
            "get_expire",
            side_effect=AssertionError("ORM API query should batch TTL reads instead of calling get_expire per row"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={
                    "collection": "query_coll",
                    "query": {"label": {"$wildcard": "item_*"}},
                    "sort": [{"field": "index", "direction": "asc"}],
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 2)

    async def test_query_sort_falls_back_when_search_sorted_is_unavailable(self):
        self._register_orm_model("query_sort_fallback_coll", {"index": 0, "label": "item_0"})
        for value in (3, 1, 2):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": "query_sort_fallback_coll", "document": {"index": value, "label": f"item_{value}"}},
            )
        storage_client = self._storage_config.get_orm_client()

        with patch.object(storage_client, "search_sorted", None):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={
                    "collection": "query_sort_fallback_coll",
                    "sort": [{"field": "index", "direction": "asc"}],
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual([item["document"]["index"] for item in resp.json()["items"]], [1, 2, 3])

    async def test_delete_document(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "del_coll", "document": {"k": "v"}},
        )
        oid = create_resp.json()["id"]

        resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "del_coll", "object_id": oid},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["deleted"])

        # Confirm gone
        get_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "del_coll", "object_id": oid},
        )
        self.assertEqual(get_resp.status_code, 404)

    async def test_create_with_expire(self):
        resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={
                "collection": "exp_coll",
                "document": {"data": "expires soon"},
                "expire_seconds": 600,
            },
        )
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["ttl_state"], "expiring")


class TestORMExpire(StorageORMTestBase):
    """PATCH /_internal/admin/api/storage/orm/expire"""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        _register_orm_api_models(self, "ttl_coll")

    async def test_set_expire_on_document(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "ttl_coll", "document": {"x": 1}},
        )
        oid = create_resp.json()["id"]

        resp = await self._client.patch(
            "/_internal/admin/api/storage/orm/expire",
            json={"collection": "ttl_coll", "object_id": oid, "expire_seconds": 1800},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["updated"])
        self.assertEqual(data["ttl_state"], "expiring")

    async def test_set_expire_nonexistent_returns_404(self):
        resp = await self._client.patch(
            "/_internal/admin/api/storage/orm/expire",
            json={"collection": "no_coll", "object_id": "no_id", "expire_seconds": 100},
        )
        self.assertEqual(resp.status_code, 404)


class TestORMSchema(StorageORMTestBase):
    """GET /_internal/admin/api/storage/orm/schema"""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        _register_orm_api_models(self, "schema_coll")

    async def test_get_schema(self):
        # Create a collection first
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "schema_coll", "document": {"name": "test", "value": 42}},
        )
        resp = await self._client.get("/_internal/admin/api/storage/orm/schema", params={"collection": "schema_coll"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["collection"], "schema_coll")
        self.assertIn("declared_fields", data)
        self.assertIn("sample_fields", data)
        # sample_fields should have at least something from the document
        self.assertIsInstance(data["sample_fields"], list)

    async def test_get_schema_includes_model_source_metadata(self):
        storage_config = self._storage_config
        assert storage_config is not None
        storage_config.orm.get_default().register_model(SchemaSourceRecord)

        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "schema_source_coll", "document": {"title": "alpha", "score": 7}},
        )
        self.assertEqual(create_resp.status_code, 200)

        resp = await self._client.get("/_internal/admin/api/storage/orm/schema", params={"collection": "schema_source_coll"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["typed_model"])
        self.assertEqual(data["model_name"], "SchemaSourceRecord")
        self.assertEqual(data["model_module"], SchemaSourceRecord.__module__)
        self.assertTrue(data["model_source_path"].replace('\\', '/').endswith("test/server/test_storage_orm_api.py"))
        self.assertIn("class SchemaSourceRecord", data["model_source"])

    async def test_get_schema_nonexistent_returns_404(self):
        resp = await self._client.get("/_internal/admin/api/storage/orm/schema", params={"collection": "nonexistent_coll"})
        self.assertEqual(resp.status_code, 404)


class TestORMDropCollection(StorageORMTestBase):
    """DELETE /_internal/admin/api/storage/orm/collection"""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        _register_orm_api_models(self, "drop_me", "drop_recreate_diff_fields", "typed_drop_recreate")

    async def test_drop_collection(self):
        # Create collection with document
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "drop_me", "document": {"foo": "bar"}},
        )
        resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/collection",
            params={"collection": "drop_me"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["deleted"])

    async def test_drop_collection_clears_schemaless_field_cache(self):
        coll = "drop_recreate_diff_fields"
        try:
            resp = await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": coll, "document": {"_id": "old", "val": 1}},
            )
            self.assertEqual(resp.status_code, 200, resp.text)

            resp = await self._client.delete(
                "/_internal/admin/api/storage/orm/collection",
                params={"collection": coll},
            )
            self.assertEqual(resp.status_code, 200, resp.text)

            resp = await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": coll, "document": {"_id": "new", "v": 2}},
            )
            self.assertEqual(resp.status_code, 200, resp.text)

            resp = await self._client.get(
                "/_internal/admin/api/storage/orm/document",
                params={"collection": coll, "object_id": "new"},
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            document = resp.json()["document"]
            self.assertIn("v", document)
            self.assertIsNone(document.get("val"))
        finally:
            await self._client.delete(
                "/_internal/admin/api/storage/orm/collection",
                params={"collection": coll},
            )

    async def test_drop_typed_collection_recreates_on_next_write(self):
        coll = "typed_drop_recreate"
        try:
            resp = await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": coll, "document": {"_id": "old", "name": "Alice", "age": 30}},
            )
            self.assertEqual(resp.status_code, 200, resp.text)

            resp = await self._client.delete(
                "/_internal/admin/api/storage/orm/collection",
                params={"collection": coll},
            )
            self.assertEqual(resp.status_code, 200, resp.text)

            resp = await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": coll, "document": {"_id": "new", "name": "Bob", "age": 31}},
            )
            self.assertEqual(resp.status_code, 200, resp.text)

            resp = await self._client.get(
                "/_internal/admin/api/storage/orm/document",
                params={"collection": coll, "object_id": "new"},
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            document = resp.json()["document"]
            self.assertEqual(document["name"], "Bob")
            self.assertEqual(document["age"], 31)
        finally:
            await self._client.delete(
                "/_internal/admin/api/storage/orm/collection",
                params={"collection": coll},
            )


class TestORMCleanup(StorageORMTestBase):
    """POST /_internal/admin/api/storage/orm/cleanup"""

    async def test_cleanup(self):
        resp = await self._client.post("/_internal/admin/api/storage/orm/cleanup")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("removed", data)
        self.assertIsInstance(data["removed"], int)


if __name__ == "__main__":
    unittest.main()
