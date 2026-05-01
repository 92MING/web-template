# -*- coding: utf-8 -*-


import unittest
from unittest.mock import patch

from _test_helpers import StorageMilvusLiteVectorTestBase
from core.storage.vector import MilvusLiteVectorClient, VectorIndex, VectorORMField, VectorORMModel


async def _milvus_lite_vector_embedder(content):
    text = str(content).lower()
    if "alpha" in text:
        return [1.0, 0.0]
    if "beta" in text:
        return [0.0, 1.0]
    return [0.0, 0.0]


class _MilvusLiteVectorRecord(VectorORMModel, collection_name="milvus_lite_vector_record_test"):
    title: str = ""
    category: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=2, embedder=_milvus_lite_vector_embedder),
    )


class TestMilvusLiteVectorConfig(StorageMilvusLiteVectorTestBase):
    async def test_config_reports_milvus_lite_backend(self):
        data = (await self._client.get("/_internal/admin/api/storage/vector/config")).json()
        self.assertEqual(data["backend"], "milvus-lite")


class TestMilvusLiteVectorRoutes(StorageMilvusLiteVectorTestBase):
    async def test_create_browse_and_vector_search(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": "milvus_lite_vector_docs",
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
                json={"collection": "milvus_lite_vector_docs", "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        browse_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={
                "collection": "milvus_lite_vector_docs",
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertEqual(browse_resp.status_code, 200)
        self.assertEqual(browse_resp.json()["total"], 3)

        search_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": "milvus_lite_vector_docs",
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
                "collection": "milvus_lite_sorted_docs",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["rank"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        upsert_resp = await self._client.put(
            "/_internal/admin/api/storage/vector/document",
            json={
                "collection": "milvus_lite_sorted_docs",
                "document": {"_id": "a", "rank": 1, "embedding": [1.0, 0.0]},
                "auto_embed_strings": False,
            },
        )
        self.assertEqual(upsert_resp.status_code, 200)

        browse_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={
                "collection": "milvus_lite_sorted_docs",
                "limit": 10,
                "offset": 0,
                "sort": [{"field": "rank", "direction": "desc"}],
            },
        )
        self.assertEqual(browse_resp.status_code, 400)
        self.assertIn("排序", browse_resp.text)

    async def test_text_search_uses_field_embedder(self):
        client = self._storage_config.get_vector_client()
        await client.create_collection(_MilvusLiteVectorRecord)
        await client.set(_MilvusLiteVectorRecord(title="alpha doc", category="notes", embedding=[1.0, 0.0]))
        await client.set(_MilvusLiteVectorRecord(title="beta doc", category="notes", embedding=[0.0, 1.0]))

        resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": _MilvusLiteVectorRecord.CollectionName,
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


class TestMilvusLiteVectorModelBinding(StorageMilvusLiteVectorTestBase):
    async def test_milvus_lite_vector_model_binds_to_milvus_lite_client(self):
        client = _MilvusLiteVectorRecord._get_vector_client()
        self.assertIsInstance(client, MilvusLiteVectorClient)

        await client.create_collection(_MilvusLiteVectorRecord)
        item = _MilvusLiteVectorRecord(title="alpha-bind", category="bind", embedding=[1.0, 0.0])
        await item.save()
        try:
            results = [row async for row in _MilvusLiteVectorRecord.SearchVector("alpha query", field="embedding", limit=1)]
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], _MilvusLiteVectorRecord)
            self.assertEqual(results[0].title, "alpha-bind")
        finally:
            await item.delete()

    async def test_selected_search_one_by_id_uses_backend_projection_path(self):
        client = _MilvusLiteVectorRecord._get_vector_client()
        self.assertIsInstance(client, MilvusLiteVectorClient)

        await client.create_collection(_MilvusLiteVectorRecord)
        item = _MilvusLiteVectorRecord(title="alpha-selected", category="notes", embedding=[1.0, 0.0])
        await item.save()
        try:
            with (
                patch.object(client, "get", side_effect=AssertionError("selected_search_by_id should not fall back to get()")),
                patch.object(client, "search", side_effect=AssertionError("selected_search_by_id should not fall back to search()")),
            ):
                payload = await _MilvusLiteVectorRecord.SelectedSearchOneById(str(item.id), fields=("title", "category"))
            self.assertEqual(payload, {"id": str(item.id), "title": "alpha-selected", "category": "notes"})
        finally:
            await item.delete()


if __name__ == "__main__":
    unittest.main()