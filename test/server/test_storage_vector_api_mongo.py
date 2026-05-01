# -*- coding: utf-8 -*-


import asyncio
import unittest
from typing import Awaitable, Callable, TypeVar

from _test_helpers import StorageMongoVectorTestBase
from core.storage.vector import MongoVectorClient, VectorIndex, VectorORMField, VectorORMModel


_T = TypeVar("_T")


async def _mongo_vector_embedder(content):
    text = str(content).lower()
    if "alpha" in text:
        return [1.0, 0.0]
    if "beta" in text:
        return [0.0, 1.0]
    return [0.0, 0.0]


class _MongoVectorRecord(VectorORMModel, collection_name="mongo_vector_record_test"):
    title: str = ""
    category: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=2, embedder=_mongo_vector_embedder),
    )


def _assert_search_not_enabled(test_case: unittest.TestCase, message: str) -> None:
    text = str(message or "").lower()
    test_case.assertTrue(
        "vector search is not enabled" in text
        or "atlas cli local deployment" in text
        or "atlas search" in text,
        msg=f"unexpected mongo vector error: {message}",
    )


async def _eventually_fetch(
    fetch: Callable[[], Awaitable[_T]],
    *,
    predicate: Callable[[_T], bool],
    timeout: float = 15.0,
    interval: float = 0.25,
) -> _T:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_result = await fetch()
    while not predicate(last_result):
        if loop.time() >= deadline:
            return last_result
        await asyncio.sleep(interval)
        last_result = await fetch()
    return last_result


class TestMongoVectorConfig(StorageMongoVectorTestBase):
    async def test_config_reports_mongo_backend(self):
        data = (await self._client.get("/_internal/admin/api/storage/vector/config")).json()
        self.assertEqual(data["backend"], "mongo")


class TestMongoVectorRoutes(StorageMongoVectorTestBase):
    async def test_collections_include_external_collection_without_registered_meta(self):
        from pymongo import MongoClient

        storage_config = self._storage_config
        assert storage_config is not None
        database = str(getattr(storage_config.vector.default, "database"))
        namespace = str(getattr(storage_config.vector.default, "namespace", "default"))
        collection = "mongo_vector_external_no_meta"
        physical_name = f"vector_{namespace}_{collection}"

        mongo_client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)
        try:
            mongo_collection = mongo_client[database][physical_name]
            mongo_collection.drop()
            mongo_collection = mongo_client[database][physical_name]
            mongo_collection.insert_many([
                {"_id": "ext-a", "title": "alpha", "embedding": [1.0, 0.0]},
                {"_id": "ext-b", "title": "beta", "embedding": [0.0, 1.0]},
            ])

            resp = await self._client.get("/_internal/admin/api/storage/vector/collections")
            self.assertEqual(resp.status_code, 200)
            items = {item["name"]: item for item in resp.json()["items"]}
            self.assertIn(collection, items)
            self.assertFalse(items[collection]["registered"])
        finally:
            mongo_client[database][physical_name].drop()
            mongo_client.close()

    async def test_create_collection_succeeds_or_reports_missing_search_enablement(self):
        resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "mongo_vector_docs",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["title", "category"],
            },
        )
        self.assertIn(resp.status_code, (200, 400))
        if resp.status_code == 400:
            _assert_search_not_enabled(self, resp.text)

    async def test_create_upsert_and_vector_search_or_report_clear_error(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "mongo_vector_docs_search",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["title", "category"],
            },
        )
        self.assertIn(create_resp.status_code, (200, 400))
        if create_resp.status_code == 400:
            _assert_search_not_enabled(self, create_resp.text)
            return

        docs = [
            {"_id": "a", "title": "alpha", "category": "notes", "embedding": [1.0, 0.0]},
            {"_id": "b", "title": "beta", "category": "notes", "embedding": [0.0, 1.0]},
        ]
        for doc in docs:
            upsert_resp = await self._client.put(
                "/_internal/admin/api/storage/vector/document",
                json={"collection": "mongo_vector_docs_search", "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        async def _search_items():
            search_resp = await self._client.post(
                "/_internal/admin/api/storage/vector/search",
                json={
                    "collection": "mongo_vector_docs_search",
                    "mode": "vector",
                    "query_vector": [1.0, 0.0],
                    "vector_field": "embedding",
                    "filter": {"category": "notes"},
                    "top_k": 2,
                },
            )
            self.assertEqual(search_resp.status_code, 200)
            return search_resp.json()["items"]

        items = await _eventually_fetch(
            _search_items,
            predicate=lambda rows: len(rows) >= 1 and rows[0]["id"] == "a",
        )
        self.assertEqual(items[0]["id"], "a")

    async def test_browse_and_vector_search_support_compound_filters_or_report_clear_error(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "mongo_vector_docs_compound",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["title", "category", "rank"],
            },
        )
        self.assertIn(create_resp.status_code, (200, 400))
        if create_resp.status_code == 400:
            _assert_search_not_enabled(self, create_resp.text)
            return

        docs = [
            {"_id": "a", "title": "axbyc", "category": "wild", "rank": 2, "embedding": [1.0, 0.0]},
            {"_id": "b", "title": "notes doc", "category": "notes", "rank": 3, "embedding": [0.8, 0.2]},
            {"_id": "c", "title": "acb", "category": "other", "rank": 1, "embedding": [0.0, 1.0]},
        ]
        for doc in docs:
            upsert_resp = await self._client.put(
                "/_internal/admin/api/storage/vector/document",
                json={"collection": "mongo_vector_docs_compound", "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        browse_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={
                "collection": "mongo_vector_docs_compound",
                "filter": {
                    "$or": [
                        {"title": {"$wildcard": "a*b*c"}},
                        {"category": "notes"},
                    ],
                    "rank": {"$gte": 2},
                },
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertEqual(browse_resp.status_code, 200)
        self.assertEqual({item["id"] for item in browse_resp.json()["items"]}, {"a", "b"})

        async def _search_items():
            search_resp = await self._client.post(
                "/_internal/admin/api/storage/vector/search",
                json={
                    "collection": "mongo_vector_docs_compound",
                    "mode": "vector",
                    "query_vector": [1.0, 0.0],
                    "vector_field": "embedding",
                    "filter": {
                        "$or": [
                            {"category": "notes"},
                            {"rank": {"$gte": 2}},
                        ],
                    },
                    "top_k": 2,
                },
            )
            self.assertEqual(search_resp.status_code, 200)
            return search_resp.json()["items"]

        items = await _eventually_fetch(
            _search_items,
            predicate=lambda rows: len(rows) >= 1 and rows[0]["id"] == "a",
        )
        self.assertEqual(items[0]["id"], "a")


class TestMongoVectorModelBinding(StorageMongoVectorTestBase):
    async def test_mongo_vector_model_binds_or_reports_clear_error(self):
        client = _MongoVectorRecord._get_vector_client()
        self.assertIsInstance(client, MongoVectorClient)

        try:
            await client.create_collection(_MongoVectorRecord)
        except ValueError as exc:
            _assert_search_not_enabled(self, str(exc))
            return

        item = _MongoVectorRecord(title="alpha-bind", category="notes", embedding=[1.0, 0.0])
        await item.save()
        try:
            async def _search_results():
                return [
                    row async for row in _MongoVectorRecord.SearchVector(
                        "alpha prompt",
                        field="embedding",
                        limit=1,
                    )
                ]

            results = await _eventually_fetch(
                _search_results,
                predicate=lambda rows: len(rows) == 1,
            )
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], _MongoVectorRecord)
            self.assertEqual(results[0].title, "alpha-bind")
        finally:
            await item.delete()


if __name__ == "__main__":
    unittest.main()