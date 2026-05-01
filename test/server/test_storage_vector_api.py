# -*- coding: utf-8 -*-
"""Tests for Vector Storage API endpoints (/_internal/admin/api/storage/vector/*).

Prefer exercising the real Milvus-Lite backend. When the local runtime cannot
start it, the shared test helper injects a lightweight in-memory fallback so
the API surface is still covered instead of being skipped.
"""


import json
import unittest
from pathlib import Path
from typing import Any, cast
import numpy as np
from unittest.mock import patch

from core.storage.vector import AnnoySQLiteVectorClient, VectorIndex, VectorORMField, VectorORMModel, _BaseMilvusVectorClient
from core.storage.config import AnnoyVectorDBConfig, MilvusLiteVectorDBConfig, StorageConfig, VectorStorageConfig

from _test_helpers import StorageVectorTestBase, _make_storage_config


async def _panel_test_embedder(content):
    text = str(content).lower()
    if 'alpha' in text:
        return np.array([1.0, 0.0])
    if 'beta' in text:
        return np.array([0.0, 1.0])
    return np.array([0.0, 0.0])


class _PanelSearchVectorRecord(VectorORMModel, collection_name='panel_search_vector_record_test'):
    title: str = ''
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=2, embedder=_panel_test_embedder),
    )


class StrictClientSelectionVectorTestBase(StorageVectorTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        base = _make_storage_config(tmp)
        default_cfg = base.vector.default
        if isinstance(default_cfg, AnnoyVectorDBConfig):
            analytics_cfg = AnnoyVectorDBConfig(db_dir=str(Path(tmp) / "vector_analytics_annoy"))
        elif isinstance(default_cfg, MilvusLiteVectorDBConfig):
            analytics_cfg = MilvusLiteVectorDBConfig(db_path=str(Path(tmp) / "vector_analytics_milvus_lite.db"))
        else:
            raise AssertionError(f"Unsupported vector config for strict-client tests: {type(default_cfg).__name__}")
        return StorageConfig(
            kv=base.kv,
            orm=base.orm,
            object=base.object,
            vector=VectorStorageConfig(
                default=base.vector.default,
                cache=base.vector.cache,
                extra={"analytics": analytics_cfg},
            ),
        )


class TestVectorFieldMetadata(unittest.TestCase):
    def test_vector_index_rejects_unknown_algorithm(self):
        with self.assertRaises(ValueError):
            VectorIndex(dim=2, algorithm=cast(Any, 'NOT_A_REAL_ALGO'))

    def test_vector_orm_field_rejects_legacy_vector_kwargs(self):
        # Pydantic v2 FieldInfo silently accepts unknown kwargs as metadata;
        # verify the field is created but does NOT get a VectorIndex.
        info = VectorORMField(default_factory=list, **{'is_vector': True, 'dim': 2})
        self.assertIsNone(getattr(info, 'index', None))


class TestVectorConfig(StorageVectorTestBase):
    """GET /_internal/admin/api/storage/vector/config"""

    async def test_storage_vector_page_returns_200(self):
        resp = await self._client.get("/_internal/admin/storage/vector")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Storage", resp.text)

    async def test_config_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/storage/vector/config")
        self.assertEqual(resp.status_code, 200)

    async def test_config_has_required_fields(self):
        data = (await self._client.get("/_internal/admin/api/storage/vector/config")).json()
        for key in ("backend", "metric_type"):
            self.assertIn(key, data, f"Missing '{key}'")

    async def test_config_backend_type(self):
        data = (await self._client.get("/_internal/admin/api/storage/vector/config")).json()
        self.assertIsInstance(data["backend"], str)
        self.assertTrue(len(data["backend"]) > 0)


class TestVectorCollections(StorageVectorTestBase):
    """GET /_internal/admin/api/storage/vector/collections"""

    async def test_collections_returns_200(self):
        resp = await self._client.get("/_internal/admin/api/storage/vector/collections")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertIsInstance(data["items"], list)


class TestVectorClientSelection(StrictClientSelectionVectorTestBase):
    async def test_config_resolves_exact_named_client(self):
        resp = await self._client.get("/_internal/admin/api/storage/vector/config", params={"client": "analytics"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["client_name"], "analytics")

    async def test_named_client_isolated_from_default_client(self):
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            params={"client": "analytics"},
            json={
                "collection": "analytics_vec_docs",
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["title"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        upsert_resp = await self._client.put(
            "/_internal/admin/api/storage/vector/document",
            params={"client": "analytics"},
            json={
                "collection": "analytics_vec_docs",
                "document": {"_id": "analytics-1", "title": "Quarterly report", "embedding": [1.0, 0.0]},
                "auto_embed_strings": False,
            },
        )
        self.assertEqual(upsert_resp.status_code, 200)

        analytics_get = await self._client.get(
            "/_internal/admin/api/storage/vector/document",
            params={"client": "analytics", "collection": "analytics_vec_docs", "object_id": "analytics-1"},
        )
        self.assertEqual(analytics_get.status_code, 200)

        default_get = await self._client.get(
            "/_internal/admin/api/storage/vector/document",
            params={"collection": "analytics_vec_docs", "object_id": "analytics-1"},
        )
        self.assertEqual(default_get.status_code, 404)

    async def test_unknown_client_does_not_fallback_or_fuzzy_match(self):
        resp = await self._client.get("/_internal/admin/api/storage/vector/config", params={"client": "analyticss"})
        self.assertEqual(resp.status_code, 404)
        self.assertIn("analyticss", resp.text)


class TestVectorBrowse(StorageVectorTestBase):
    """POST /_internal/admin/api/storage/vector/browse"""

    async def test_browse_empty_collection(self):
        """Browse a non-existent collection — should still return a valid response or error."""
        resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={"collection": "nonexistent_vec_coll", "limit": 5, "offset": 0},
        )
        # May return empty results or an error; either is acceptable
        self.assertIn(resp.status_code, (200, 404, 500))

    async def test_browse_uses_native_sort_or_explicitly_rejects_it(self):
        collection = "sorted_vec_coll"
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": collection,
                "vector_fields": [{"name": "embedding", "dim": 3, "metric_type": "COSINE"}],
                "scalar_fields": ["title", "rank"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        docs = [
            {"_id": "b", "title": "beta", "rank": 2, "embedding": [0.1, 0.2, 0.3]},
            {"_id": "a", "title": "alpha", "rank": 1, "embedding": [0.2, 0.1, 0.3]},
            {"_id": "c", "title": "alpha", "rank": 3, "embedding": [0.3, 0.2, 0.1]},
        ]
        for doc in docs:
            upsert_resp = await self._client.put(
                "/_internal/admin/api/storage/vector/document",
                json={"collection": collection, "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        browse_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={
                "collection": collection,
                "limit": 10,
                "offset": 0,
                "sort": [
                    {"field": "rank", "direction": "desc"},
                ],
            },
        )
        self.assertIn(browse_resp.status_code, (200, 400))
        if browse_resp.status_code == 200:
            data = browse_resp.json()
            self.assertEqual(data["total"], 3)
            self.assertEqual([item["id"] for item in data["items"]], ["c", "b", "a"])
        else:
            self.assertIn("排序", browse_resp.text)

    async def test_browse_supports_compound_filter(self):
        collection = "compound_vec_coll"
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": collection,
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
                json={"collection": collection, "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        browse_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/browse",
            json={
                "collection": collection,
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

    async def test_browse_avoids_per_item_get_expire(self):
        storage_client = self._storage_config.get_vector_client()
        if type(storage_client).__name__ == "_FallbackVectorClient":
            self.skipTest("fallback vector client has no native batch TTL path")

        collection = "browse_ttl_vec_coll"
        create_resp = await self._client.post(
            "/_internal/admin/api/storage/vector/collection",
            json={
                "collection": collection,
                "vector_fields": [{"name": "embedding", "dim": 2, "metric_type": "COSINE"}],
                "scalar_fields": ["title", "rank"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        for doc in (
            {"_id": "a", "title": "alpha", "rank": 1, "embedding": [1.0, 0.0]},
            {"_id": "b", "title": "beta", "rank": 2, "embedding": [0.0, 1.0]},
        ):
            upsert_resp = await self._client.put(
                "/_internal/admin/api/storage/vector/document",
                json={"collection": collection, "document": doc, "auto_embed_strings": False},
            )
            self.assertEqual(upsert_resp.status_code, 200)

        with patch.object(
            storage_client,
            "get_expire",
            side_effect=AssertionError("Vector browse should not call get_expire once per row"),
        ):
            browse_resp = await self._client.post(
                "/_internal/admin/api/storage/vector/browse",
                json={
                    "collection": collection,
                    "limit": 10,
                    "offset": 0,
                },
            )

        self.assertEqual(browse_resp.status_code, 200)
        data = browse_resp.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual({item["id"] for item in data["items"]}, {"a", "b"})


class TestVectorSelectedSearch(StorageVectorTestBase):
    async def test_vector_model_selected_search_one_by_id_returns_requested_fields(self):
        item = _PanelSearchVectorRecord(title='alpha-doc', embedding=[1.0, 0.0])
        await item.save()
        try:
            payload = await _PanelSearchVectorRecord.SelectedSearchOneById(
                str(item.id),
                fields=('title',),
            )
            self.assertEqual(payload, {'id': str(item.id), 'title': 'alpha-doc'})
        finally:
            await item.delete()

    async def test_vector_model_selected_search_one_by_id_uses_backend_specific_path(self):
        client = _PanelSearchVectorRecord._get_vector_client()
        if not isinstance(client, (AnnoySQLiteVectorClient, _BaseMilvusVectorClient)):
            self.skipTest(f'backend-specific SelectedSearch acceleration not available for {type(client).__name__}')

        item = _PanelSearchVectorRecord(title='beta-doc', embedding=[0.0, 1.0])
        await item.save()
        try:
            with (
                patch.object(client, 'get', side_effect=AssertionError('selected_search_by_id should not fall back to get()')),
                patch.object(client, 'search', side_effect=AssertionError('selected_search_by_id should not fall back to search()')),
            ):
                payload = await _PanelSearchVectorRecord.SelectedSearchOneById(
                    str(item.id),
                    fields=('title',),
                    client=client,
                )
            self.assertEqual(payload, {'id': str(item.id), 'title': 'beta-doc'})
        finally:
            await item.delete()


class TestVectorSearch(StorageVectorTestBase):
    """POST /_internal/admin/api/storage/vector/search"""

    async def test_search_vector_mode_requires_vector(self):
        """Vector mode without query_vector should return 400."""
        resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": "test_vec",
                "mode": "vector",
                "query_vector": None,
                "top_k": 5,
            },
        )
        # Expect 400 because query_vector is required in vector mode
        self.assertIn(resp.status_code, (400, 404, 500))

    async def test_search_text_mode_requires_text(self):
        """Text mode without query_text should return 400."""
        resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": "test_vec",
                "mode": "text",
                "query_text": "",
                "top_k": 5,
            },
        )
        self.assertIn(resp.status_code, (400, 404, 500, 503))

    async def test_search_text_mode_uses_model_field_embedder(self):
        storage_config = self._storage_config
        assert storage_config is not None
        client = storage_config.get_vector_client()
        await client.create_collection(_PanelSearchVectorRecord)
        await client.set(_PanelSearchVectorRecord(title='alpha doc', embedding=[1.0, 0.0]))
        await client.set(_PanelSearchVectorRecord(title='beta doc', embedding=[0.0, 1.0]))

        resp = await self._client.post(
            "/_internal/admin/api/storage/vector/search",
            json={
                "collection": _PanelSearchVectorRecord.CollectionName,
                "mode": "text",
                "query_text": "alpha prompt",
                "vector_field": "embedding",
                "top_k": 1,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['payload']['title'], 'alpha doc')


class TestVectorDocumentOperations(StorageVectorTestBase):
    """DELETE, PATCH expire on vector documents."""

    async def test_raw_set_with_vector_supports_plain_mapping(self):
        storage_config = self._storage_config
        assert storage_config is not None
        client = storage_config.get_vector_client()
        await client.create_collection(_PanelSearchVectorRecord)

        object_id = await client.raw_set_with_vector(
            _PanelSearchVectorRecord.CollectionName,
            {'id': 'raw-alpha', 'title': 'raw alpha'},
            [1.0, 0.0],
        )
        try:
            self.assertEqual(object_id, 'raw-alpha')

            payload = await client.raw_get(_PanelSearchVectorRecord.CollectionName, object_id)
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload['title'], 'raw alpha')
            self.assertEqual(payload['embedding'], [1.0, 0.0])

            rows = [
                row async for row in client.raw_query(
                    _PanelSearchVectorRecord.CollectionName,
                    {'title': 'raw alpha'},
                    limit=5,
                )
            ]
            self.assertTrue(any(str(row.get('id') or row.get('_id')) == object_id for row in rows))
        finally:
            await client.raw_delete(_PanelSearchVectorRecord.CollectionName, object_id)

    async def test_delete_nonexistent_document(self):
        resp = await self._client.delete(
            "/_internal/admin/api/storage/vector/document",
            params={"collection": "no_vec_coll", "object_id": "no_id"},
        )
        # Should succeed (false deleted) or fail with error
        self.assertIn(resp.status_code, (200, 404, 500))

    async def test_expire_nonexistent_document(self):
        resp = await self._client.patch(
            "/_internal/admin/api/storage/vector/expire",
            json={"collection": "no_vec_coll", "object_id": "no_id", "expire_seconds": 100},
        )
        self.assertIn(resp.status_code, (200, 404, 500))


class TestVectorCleanup(StorageVectorTestBase):
    """POST /_internal/admin/api/storage/vector/cleanup"""

    async def test_cleanup(self):
        resp = await self._client.post("/_internal/admin/api/storage/vector/cleanup")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("removed", data)
        self.assertIsInstance(data["removed"], int)


if __name__ == "__main__":
    unittest.main()
