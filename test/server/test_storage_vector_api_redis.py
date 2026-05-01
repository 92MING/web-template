# -*- coding: utf-8 -*-


import unittest
from unittest.mock import patch

from _test_helpers import StorageRedisVectorTestBase
from core.storage.vector import RedisVectorClient, VectorIndex, VectorORMField, VectorORMModel


async def _redis_vector_embedder(content):
    text = str(content).lower()
    if "alpha" in text:
        return [1.0, 0.0]
    if "beta" in text:
        return [0.0, 1.0]
    return [0.0, 0.0]


class _RedisVectorRecord(VectorORMModel, collection_name="redis_vector_record_test"):
    title: str = ""
    category: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=2, embedder=_redis_vector_embedder),
    )


class TestRedisVectorConfig(StorageRedisVectorTestBase):
    async def test_config_reports_redis_backend(self):
        data = (await self._client.get("/_internal/admin/api/storage/vector/config")).json()
        self.assertEqual(data["backend"], "redis")


class TestRedisVectorRoutes(StorageRedisVectorTestBase):
    async def test_create_browse_and_vector_search(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "redis_vector_docs",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["title", "rank"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        docs = [
            {"_id": "b", "title": "beta", "rank": 2, "embedding": [0.0, 1.0]},
            {"_id": "a", "title": "alpha", "rank": 1, "embedding": [1.0, 0.0]},
            {"_id": "c", "title": "alpha", "rank": 3, "embedding": [0.8, 0.2]},
        ]
        for doc in docs:
            upsert_resp = await self._client.put(
                "/_internal/admin/api/storage/vector/document",
                json={"collection": "redis_vector_docs", "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        browse_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={
                "collection": "redis_vector_docs",
                "limit": 10,
                "offset": 0,
                "sort": [
                    {"field": "rank", "direction": "desc"},
                ],
            },
        )
        self.assertEqual(browse_resp.status_code, 200)
        self.assertEqual([item["id"] for item in browse_resp.json()["items"]], ["c", "b", "a"])

        search_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": "redis_vector_docs",
                "mode": "vector",
                "query_vector": [1.0, 0.0],
                "vector_field": "embedding",
                "top_k": 2,
            },
        )
        self.assertEqual(search_resp.status_code, 200)
        items = search_resp.json()["items"]
        self.assertEqual(items[0]["id"], "a")
        self.assertGreaterEqual(float(items[0]["score"]), float(items[1]["score"]))

    async def test_browse_and_vector_search_do_not_scan_collection_ids(self):
        client = self._storage_config.get_vector_client()
        await client.create_collection(_RedisVectorRecord)
        await client.set(_RedisVectorRecord(id="64e00000000000000000000a", title="alpha doc", category="notes", embedding=[1.0, 0.0]))
        await client.set(_RedisVectorRecord(id="64e00000000000000000000b", title="beta doc", category="notes", embedding=[0.0, 1.0]))
        redis_client = client._client()

        with patch.object(redis_client, "smembers", side_effect=AssertionError("redis vector browse/search should not scan collection ids")):
            browse_resp = await self._client.post(
                "/_internal/admin/api/storage/vector/browse",
                json={
                    "collection": _RedisVectorRecord.CollectionName,
                    "filter": {"category": "notes"},
                    "limit": 10,
                    "offset": 0,
                },
            )
            search_resp = await self._client.post(
                "/_internal/admin/api/storage/vector/search",
                json={
                    "collection": _RedisVectorRecord.CollectionName,
                    "mode": "vector",
                    "query_vector": [1.0, 0.0],
                    "vector_field": "embedding",
                    "filter": {"category": "notes"},
                    "top_k": 2,
                },
            )

        self.assertEqual(browse_resp.status_code, 200)
        self.assertEqual(search_resp.status_code, 200)

    async def test_text_search_uses_field_embedder(self):
        client = self._storage_config.get_vector_client()
        await client.create_collection(_RedisVectorRecord)
        await client.set(_RedisVectorRecord(title="alpha doc", category="notes", embedding=[1.0, 0.0]))
        await client.set(_RedisVectorRecord(title="beta doc", category="notes", embedding=[0.0, 1.0]))

        resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": _RedisVectorRecord.CollectionName,
                "mode": "text",
                "query_text": "alpha prompt",
                "vector_field": "embedding",
                "top_k": 1,
            },
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["payload"]["title"], "alpha doc")

    async def test_browse_and_vector_search_support_compound_filters(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "redis_vector_compound_docs",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["title", "category", "rank"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        docs = [
            {"_id": "a", "title": "axbyc", "category": "wild", "rank": 2, "embedding": [1.0, 0.0]},
            {"_id": "b", "title": "notes doc", "category": "notes", "rank": 3, "embedding": [0.8, 0.2]},
            {"_id": "c", "title": "acb", "category": "other", "rank": 3, "embedding": [0.0, 1.0]},
        ]
        for doc in docs:
            upsert_resp = await self._client.put(
                "/_internal/admin/api/storage/vector/document",
                json={"collection": "redis_vector_compound_docs", "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        compound_filter = {
            "$or": [
                {"title": {"$wildcard": "a*b*c"}},
                {"category": "notes"},
            ],
            "rank": {"$gte": 2},
        }
        redis_client = self._storage_config.get_vector_client()._client()
        with patch.object(redis_client, "smembers", side_effect=AssertionError("redis vector compound filter should stay on RediSearch")):
            browse_resp = await self._client.post(
                "/_internal/admin/api/storage/vector/browse",
                json={
                    "collection": "redis_vector_compound_docs",
                    "filter": compound_filter,
                    "limit": 10,
                    "offset": 0,
                },
            )
            search_resp = await self._client.post(
                "/_internal/admin/api/storage/vector/search",
                json={
                    "collection": "redis_vector_compound_docs",
                    "mode": "vector",
                    "query_vector": [1.0, 0.0],
                    "vector_field": "embedding",
                    "filter": compound_filter,
                    "top_k": 3,
                },
            )

        self.assertEqual(browse_resp.status_code, 200)
        self.assertEqual({item["id"] for item in browse_resp.json()["items"]}, {"a", "b"})
        self.assertEqual(search_resp.status_code, 200)
        items = search_resp.json()["items"]
        self.assertEqual([item["id"] for item in items], ["a", "b"])


class TestRedisVectorClientBinding(StorageRedisVectorTestBase):
    async def test_vector_model_uses_explicit_bound_redis_client(self):
        _RedisVectorRecord.Client = self._storage_config.get_vector_client()
        client = _RedisVectorRecord._get_vector_client()
        self.assertIsInstance(client, RedisVectorClient)

        await client.create_collection(_RedisVectorRecord)
        item = _RedisVectorRecord(title="alpha-bind", category="bind", embedding=[1.0, 0.0])
        await item.save()
        try:
            results = [row async for row in _RedisVectorRecord.SearchVector("alpha query", field="embedding", limit=1)]
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], _RedisVectorRecord)
            self.assertEqual(results[0].title, "alpha-bind")
        finally:
            await item.delete()

    async def test_selected_search_one_by_id_uses_backend_projection_path(self):
        _RedisVectorRecord.Client = self._storage_config.get_vector_client()
        client = _RedisVectorRecord._get_vector_client()
        self.assertIsInstance(client, RedisVectorClient)

        await client.create_collection(_RedisVectorRecord)
        item = _RedisVectorRecord(id="64e00000000000000000000c", title="alpha-selected", category="notes", embedding=[1.0, 0.0])
        await item.save()
        try:
            with (
                patch.object(client, "get", side_effect=AssertionError("selected_search_by_id should not fall back to get()")),
                patch.object(client, "search", side_effect=AssertionError("selected_search_by_id should not fall back to search()")),
            ):
                payload = await _RedisVectorRecord.SelectedSearchOneById(str(item.id), fields=("title", "category"))
            self.assertEqual(payload, {"id": str(item.id), "title": "alpha-selected", "category": "notes"})
        finally:
            await item.delete()


if __name__ == "__main__":
    unittest.main()