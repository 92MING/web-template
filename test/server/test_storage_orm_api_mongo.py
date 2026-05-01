# -*- coding: utf-8 -*-
"""Mongo-backed ORM Storage API regression tests."""


import unittest
from unittest.mock import patch

from pymongo import MongoClient

from _test_helpers import MONGO_TEST_URL, StorageMongoORMTestBase


_MONGO_MODEL_SAMPLES: dict[str, dict[str, object]] = {
    "mongo_docs": {"name": "Alice", "age": 30},
    "mongo_wildcard": {"name": "Alice"},
    "mongo_wildcard_multi": {"name": "abc"},
    "mongo_custom_index": {"title": "alpha", "score": 7},
}


class TestMongoORMConfig(StorageMongoORMTestBase):
    async def test_config_backend_type_is_mongo(self):
        resp = await self._client.get("/_internal/admin/api/storage/orm/config")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["backend"], "mongo")


class TestMongoORMCRUD(StorageMongoORMTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for collection, sample in _MONGO_MODEL_SAMPLES.items():
            self._register_orm_model(collection, sample)

    async def test_create_query_and_delete_document(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mongo_docs", "document": {"name": "Alice", "age": 30}},
        )
        self.assertEqual(create_resp.status_code, 200)
        object_id = create_resp.json()["id"]

        query_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={"collection": "mongo_docs", "query": {"name": "Alice"}},
        )
        self.assertEqual(query_resp.status_code, 200)
        self.assertEqual(query_resp.json()["total"], 1)

        delete_resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "mongo_docs", "object_id": object_id},
        )
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])

    async def test_query_wildcard_uses_mongo_pushdown(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mongo_wildcard", "document": {"name": "Alice"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mongo_wildcard", "document": {"name": "Alfred"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mongo_wildcard", "document": {"name": "Bob"}},
        )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("mongo wildcard query should be pushed down to Mongo, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={"collection": "mongo_wildcard", "query": {"name": {"$wildcard": "Al*"}}},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 2)

    async def test_query_multi_segment_wildcard_uses_mongo_pushdown(self):
        for name in ("abc", "axbyc", "abbbc", "acb"):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": "mongo_wildcard_multi", "document": {"name": name}},
            )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("mongo multi-segment wildcard query should be pushed down to Mongo, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={"collection": "mongo_wildcard_multi", "query": {"name": {"$wildcard": "a*b*c"}}},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 3)

    async def test_query_rejects_non_pushdown_filter_instead_of_ignoring_it(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mongo_docs", "document": {"name": "Alice", "age": 30}},
        )

        resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={
                "collection": "mongo_docs",
                "query": {"name": {"$unsupported": "Alice"}},
            },
        )

        self.assertEqual(resp.status_code, 400)

    async def test_collections_include_external_mongo_collection_without_registered_meta(self):
        storage_config = self._storage_config
        assert storage_config is not None
        cfg = storage_config.orm.default
        database = getattr(cfg, "database", None)
        self.assertIsInstance(database, str)
        assert isinstance(database, str)

        mongo = MongoClient(MONGO_TEST_URL, serverSelectionTimeoutMS=3000)
        try:
            db = mongo[database]
            db["orm_external_shadow"].delete_many({})
            inserted_id = db["orm_external_shadow"].insert_one({"name": "outside", "rank": 1}).inserted_id
            db["_orm_collections"].delete_many({"collection_name": "external_shadow"})
        finally:
            mongo.close()

        client = storage_config.orm.get_default()
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
            params={"collection": "external_shadow", "object_id": str(inserted_id)},
        )
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["document"]["name"], "outside")


class TestMongoORMIndexes(StorageMongoORMTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._register_orm_model("mongo_custom_index", _MONGO_MODEL_SAMPLES["mongo_custom_index"])

    async def test_create_and_drop_custom_index(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mongo_custom_index", "document": {"title": "alpha", "score": 7}},
        )

        create_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/index",
            json={
                "collection": "mongo_custom_index",
                "fields": [{"field": "title", "direction": "asc"}],
                "name": "idx_mongo_custom_title",
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        list_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/indexes",
            params={"collection": "mongo_custom_index"},
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertIn("idx_mongo_custom_title", {item["name"] for item in list_resp.json()["items"]})

        drop_resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/index",
            params={"collection": "mongo_custom_index", "name": "idx_mongo_custom_title"},
        )
        self.assertEqual(drop_resp.status_code, 200)
        self.assertTrue(drop_resp.json()["deleted"])


if __name__ == "__main__":
    unittest.main()