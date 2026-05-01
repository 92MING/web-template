# -*- coding: utf-8 -*-


import unittest
from unittest.mock import patch

from _test_helpers import StorageMilvusVectorTestBase
from core.storage.vector import PyMilvusVectorClient, VectorIndex, VectorORMField, VectorORMModel


async def _milvus_vector_embedder(content):
    text = str(content).lower()
    if "alpha" in text:
        return [1.0, 0.0]
    if "beta" in text:
        return [0.0, 1.0]
    return [0.0, 0.0]


class _MilvusVectorRecord(VectorORMModel, collection_name="milvus_vector_record_test"):
    title: str = ""
    category: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=2, embedder=_milvus_vector_embedder),
    )


class TestMilvusVectorConfig(StorageMilvusVectorTestBase):
    async def test_config_reports_milvus_backend(self):
        data = (await self._client.get("/_internal/admin/api/storage/vector/config")).json()
        self.assertEqual(data["backend"], "milvus")


class TestMilvusVectorRoutes(StorageMilvusVectorTestBase):
    async def test_create_browse_and_vector_search(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "milvus_vector_docs",
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
                json={"collection": "milvus_vector_docs", "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        browse_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={
                "collection": "milvus_vector_docs",
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertEqual(browse_resp.status_code, 200)
        self.assertEqual(browse_resp.json()["total"], 3)

        search_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": "milvus_vector_docs",
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

    async def test_sorted_browse_rejects_full_scan_fallback(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "milvus_sorted_docs",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["rank"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        upsert_resp = await self._client.put(
            "/_internal/admin/api/storage/vector/document",
            json={
                "collection": "milvus_sorted_docs",
                "document": {"_id": "a", "rank": 1, "embedding": [1.0, 0.0]},
                "auto_embed_strings": False,
            },
        )
        self.assertEqual(upsert_resp.status_code, 200)

        browse_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={
                "collection": "milvus_sorted_docs",
                "limit": 10,
                "offset": 0,
                "sort": [{"field": "rank", "direction": "desc"}],
            },
        )
        self.assertEqual(browse_resp.status_code, 400)
        self.assertIn("排序", browse_resp.text)

    async def test_browse_supports_compound_filter_with_native_pushdown(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "milvus_compound_docs",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["title", "category", "rank"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        docs = [
            {"_id": "a", "title": "alpha", "category": "notes", "rank": 1, "embedding": [1.0, 0.0]},
            {"_id": "b", "title": "beta", "category": "notes", "rank": 3, "embedding": [0.8, 0.2]},
            {"_id": "c", "title": "gamma", "category": "other", "rank": 3, "embedding": [0.0, 1.0]},
        ]
        for doc in docs:
            upsert_resp = await self._client.put(
                "/_internal/admin/api/storage/vector/document",
                json={"collection": "milvus_compound_docs", "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        client = self._storage_config.get_vector_client()
        with patch.object(client, "_bounded_filtered_payloads", side_effect=AssertionError("milvus compound browse should use native filter pushdown")):
            browse_resp = await self._client.post(
                "/_internal/admin/api/storage/vector/browse",
                json={
                    "collection": "milvus_compound_docs",
                    "filter": {
                        "$or": [
                            {"title": "alpha"},
                            {"rank": {"$gte": 3}},
                        ],
                        "category": "notes",
                    },
                    "limit": 10,
                    "offset": 0,
                },
            )

        self.assertEqual(browse_resp.status_code, 200)
        self.assertEqual({item["id"] for item in browse_resp.json()["items"]}, {"a", "b"})

    async def test_text_search_uses_field_embedder(self):
        client = self._storage_config.get_vector_client()
        await client.create_collection(_MilvusVectorRecord)
        await client.set(_MilvusVectorRecord(title="alpha doc", category="notes", embedding=[1.0, 0.0]))
        await client.set(_MilvusVectorRecord(title="beta doc", category="notes", embedding=[0.0, 1.0]))

        resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": _MilvusVectorRecord.CollectionName,
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

    async def test_expire_route_does_not_read_ttl_back(self):
        client = self._storage_config.get_vector_client()
        await client.create_collection(_MilvusVectorRecord)
        object_id = await client.set(
            _MilvusVectorRecord(title="alpha doc", category="notes", embedding=[1.0, 0.0]),
        )

        with patch.object(client, "get_expire", side_effect=AssertionError("expire route should not call get_expire")):
            resp = await self._client.patch(
                "/_internal/admin/api/storage/vector/expire",
                json={
                    "collection": _MilvusVectorRecord.CollectionName,
                    "object_id": object_id,
                    "expire_seconds": 120,
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["updated"])
        self.assertEqual(data["id"], object_id)
        self.assertEqual(data["ttl_state"], "expiring")
        self.assertEqual(float(data["ttl_seconds"]), 120.0)


class TestMilvusVectorModelBinding(StorageMilvusVectorTestBase):
    async def test_milvus_vector_model_binds_to_milvus_client(self):
        client = _MilvusVectorRecord._get_vector_client()
        self.assertIsInstance(client, PyMilvusVectorClient)

        await client.create_collection(_MilvusVectorRecord)
        item = _MilvusVectorRecord(title="alpha-bind", category="bind", embedding=[1.0, 0.0])
        await item.save()
        try:
            results = [row async for row in _MilvusVectorRecord.SearchVector("alpha query", field="embedding", limit=1)]
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], _MilvusVectorRecord)
            self.assertEqual(results[0].title, "alpha-bind")
        finally:
            await item.delete()

    async def test_selected_search_one_by_id_uses_backend_projection_path(self):
        client = _MilvusVectorRecord._get_vector_client()
        self.assertIsInstance(client, PyMilvusVectorClient)

        await client.create_collection(_MilvusVectorRecord)
        item = _MilvusVectorRecord(title="alpha-selected", category="notes", embedding=[1.0, 0.0])
        await item.save()
        try:
            with (
                patch.object(client, "get", side_effect=AssertionError("selected_search_by_id should not fall back to get()")),
                patch.object(client, "search", side_effect=AssertionError("selected_search_by_id should not fall back to search()")),
            ):
                payload = await _MilvusVectorRecord.SelectedSearchOneById(str(item.id), fields=("title", "category"))
            self.assertEqual(payload, {"id": str(item.id), "title": "alpha-selected", "category": "notes"})
        finally:
            await item.delete()


if __name__ == "__main__":
    unittest.main()