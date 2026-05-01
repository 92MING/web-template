# -*- coding: utf-8 -*-
"""PostgreSQL-backed ORM Storage API regression tests."""


import unittest
from unittest.mock import patch

from _test_helpers import StoragePostgreSQLORMTestBase


_POSTGRES_MODEL_SAMPLES: dict[str, dict[str, object]] = {
    "pg_docs": {"name": "Alice", "age": 30},
    "pg_wildcard": {"name": "Alice"},
    "pg_wildcard_multi": {"name": "abc"},
    "pg_custom_index": {"title": "alpha", "score": 7},
}


class TestPostgreSQLORMConfig(StoragePostgreSQLORMTestBase):
    async def test_config_backend_type_is_postgresql(self):
        resp = await self._client.get("/_internal/admin/api/storage/orm/config")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["backend"], "postgresql")


class TestPostgreSQLORMCRUD(StoragePostgreSQLORMTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for collection, sample in _POSTGRES_MODEL_SAMPLES.items():
            self._register_orm_model(collection, sample)

    async def test_create_query_and_delete_document(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "pg_docs", "document": {"name": "Alice", "age": 30}},
        )
        self.assertEqual(create_resp.status_code, 200)
        object_id = create_resp.json()["id"]

        query_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={"collection": "pg_docs", "query": {"name": "Alice"}},
        )
        self.assertEqual(query_resp.status_code, 200)
        self.assertEqual(query_resp.json()["total"], 1)

        delete_resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "pg_docs", "object_id": object_id},
        )
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])

    async def test_query_wildcard_uses_postgresql_pushdown(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "pg_wildcard", "document": {"name": "Alice"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "pg_wildcard", "document": {"name": "Alfred"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "pg_wildcard", "document": {"name": "Bob"}},
        )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("postgresql wildcard query should be pushed down to SQL, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={"collection": "pg_wildcard", "query": {"name": {"$wildcard": "Al*"}}},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 2)

    async def test_query_multi_segment_wildcard_uses_postgresql_pushdown(self):
        for name in ("abc", "axbyc", "abbbc", "acb"):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": "pg_wildcard_multi", "document": {"name": name}},
            )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("postgresql multi-segment wildcard query should be pushed down to SQL, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={"collection": "pg_wildcard_multi", "query": {"name": {"$wildcard": "a*b*c"}}},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 3)


class TestPostgreSQLORMIndexes(StoragePostgreSQLORMTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._register_orm_model("pg_custom_index", _POSTGRES_MODEL_SAMPLES["pg_custom_index"])

    async def test_create_and_drop_custom_index(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "pg_custom_index", "document": {"title": "alpha", "score": 7}},
        )

        create_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/index",
            json={
                "collection": "pg_custom_index",
                "fields": [{"field": "title", "direction": "asc"}],
                "name": "idx_pg_custom_title",
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        list_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/indexes",
            params={"collection": "pg_custom_index"},
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertIn("idx_pg_custom_title", {item["name"] for item in list_resp.json()["items"]})

        drop_resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/index",
            params={"collection": "pg_custom_index", "name": "idx_pg_custom_title"},
        )
        self.assertEqual(drop_resp.status_code, 200)
        self.assertTrue(drop_resp.json()["deleted"])


if __name__ == "__main__":
    unittest.main()
