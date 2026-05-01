# -*- coding: utf-8 -*-
"""MySQL-backed ORM Storage API regression tests."""


import unittest
from unittest.mock import patch

from _test_helpers import StorageMySQLORMTestBase


_MYSQL_MODEL_SAMPLES: dict[str, dict[str, object]] = {
    "mysql_docs": {"name": "Alice", "age": 30},
    "mysql_wildcard": {"name": "Alice"},
    "mysql_wildcard_multi": {"name": "abc"},
    "mysql_sorted": {"rank": 1},
    "mysql_indexed": {"title": "hello", "level": 1},
    "mysql_custom_index": {"title": "alpha", "score": 7},
}


class TestMySQLORMConfig(StorageMySQLORMTestBase):
    async def test_config_backend_type_is_mysql(self):
        resp = await self._client.get("/_internal/admin/api/storage/orm/config")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["backend"], "mysql")


class TestMySQLORMDocumentCRUD(StorageMySQLORMTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for collection, sample in _MYSQL_MODEL_SAMPLES.items():
            self._register_orm_model(collection, sample)

    async def test_create_query_and_delete_document(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mysql_docs", "document": {"name": "Alice", "age": 30}},
        )
        self.assertEqual(create_resp.status_code, 200)
        object_id = create_resp.json()["id"]

        get_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "mysql_docs", "object_id": object_id},
        )
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["document"]["name"], "Alice")

        query_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={"collection": "mysql_docs", "query": {"name": "Alice"}},
        )
        self.assertEqual(query_resp.status_code, 200)
        self.assertEqual(query_resp.json()["total"], 1)

        delete_resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "mysql_docs", "object_id": object_id},
        )
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])

    async def test_query_wildcard_uses_mysql_pushdown(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mysql_wildcard", "document": {"name": "Alice"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mysql_wildcard", "document": {"name": "Alfred"}},
        )
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mysql_wildcard", "document": {"name": "Bob"}},
        )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("mysql wildcard query should be pushed down to SQL, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={"collection": "mysql_wildcard", "query": {"name": {"$wildcard": "Al*"}}},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 2)

    async def test_query_multi_segment_wildcard_uses_mysql_pushdown(self):
        for name in ("abc", "axbyc", "abbbc", "acb"):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": "mysql_wildcard_multi", "document": {"name": name}},
            )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("mysql multi-segment wildcard query should be pushed down to SQL, not filtered in Python"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={"collection": "mysql_wildcard_multi", "query": {"name": {"$wildcard": "a*b*c"}}},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 3)

    async def test_query_sort_uses_mysql_backend(self):
        for value in (3, 1, 2):
            await self._client.put(
                "/_internal/admin/api/storage/orm/document",
                json={"collection": "mysql_sorted", "document": {"rank": value}},
            )

        resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={
                "collection": "mysql_sorted",
                "sort": [{"field": "rank", "direction": "asc"}],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([item["document"]["rank"] for item in resp.json()["items"]], [1, 2, 3])


class TestMySQLORMIndexes(StorageMySQLORMTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._register_orm_model("mysql_indexed", _MYSQL_MODEL_SAMPLES["mysql_indexed"])
        self._register_orm_model("mysql_custom_index", _MYSQL_MODEL_SAMPLES["mysql_custom_index"])

    async def test_system_indexes_are_reported_and_protected(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mysql_indexed", "document": {"title": "hello", "level": 1}},
        )
        self.assertEqual(create_resp.status_code, 200)

        list_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/indexes",
            params={"collection": "mysql_indexed"},
        )
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.json()["items"]
        system_names = {item["name"] for item in items if item.get("managed_by_system")}
        self.assertIn("idx_mysql_indexed_sys_expire", system_names)
        self.assertIn("idx_mysql_indexed_sys_access", system_names)

        drop_resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/index",
            params={"collection": "mysql_indexed", "name": "idx_mysql_indexed_sys_expire"},
        )
        self.assertEqual(drop_resp.status_code, 400)

    async def test_create_and_drop_custom_index(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "mysql_custom_index", "document": {"title": "alpha", "score": 7}},
        )

        create_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/index",
            json={
                "collection": "mysql_custom_index",
                "fields": [{"field": "title", "direction": "asc"}],
                "name": "idx_mysql_custom_title",
            },
        )
        self.assertEqual(create_resp.status_code, 200)

        list_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/indexes",
            params={"collection": "mysql_custom_index"},
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertIn("idx_mysql_custom_title", {item["name"] for item in list_resp.json()["items"]})

        drop_resp = await self._client.delete(
            "/_internal/admin/api/storage/orm/index",
            params={"collection": "mysql_custom_index", "name": "idx_mysql_custom_title"},
        )
        self.assertEqual(drop_resp.status_code, 200)
        self.assertTrue(drop_resp.json()["deleted"])


if __name__ == "__main__":
    unittest.main()
