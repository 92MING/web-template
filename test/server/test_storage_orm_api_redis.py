# -*- coding: utf-8 -*-


import unittest
from unittest.mock import patch

from _test_helpers import StorageRedisORMTestBase
from core.storage.orm import RedisModel, RedisORMClient


_REDIS_MODEL_SAMPLES: dict[str, dict[str, object]] = {
    "redis_docs": {"name": "Alice", "status": "active", "score": 9},
    "redis_native_query_docs": {"name": "Alice", "status": "active", "score": 9},
    "redis_wildcard_multi_docs": {"name": "abc", "status": "active", "score": 9},
    "redis_schema_docs": {"name": "Bob", "status": "draft", "score": 3},
}


class _RedisORMArticle(RedisModel, collection_name="redis_orm_article_test"):
    name: str = ""
    status: str = ""
    score: int = 0


class TestRedisORMConfig(StorageRedisORMTestBase):
    async def test_config_reports_redis_backend(self):
        data = (await self._client.get("/_internal/admin/api/storage/orm/config")).json()
        self.assertEqual(data["backend"], "redis")


class TestRedisORMDocument(StorageRedisORMTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for collection, sample in _REDIS_MODEL_SAMPLES.items():
            self._register_orm_model(collection, sample)

    async def test_put_get_query_and_expire(self):
        create_resp = await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={
                "collection": "redis_docs",
                "document": {"name": "Alice", "status": "active", "score": 9},
                "expire_seconds": 600,
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        payload = create_resp.json()
        self.assertEqual(payload["ttl_state"], "expiring")
        object_id = payload["id"]

        get_resp = await self._client.get(
            "/_internal/admin/api/storage/orm/document",
            params={"collection": "redis_docs", "object_id": object_id},
        )
        self.assertEqual(get_resp.status_code, 200)
        document = get_resp.json()["document"]
        self.assertEqual(document["name"], "Alice")
        self.assertEqual(document["status"], "active")

        query_resp = await self._client.post(
            "/_internal/admin/api/storage/orm/query",
            json={"collection": "redis_docs", "query": {"status": "active"}},
        )
        self.assertEqual(query_resp.status_code, 200)
        query_data = query_resp.json()
        self.assertEqual(query_data["total"], 1)
        self.assertEqual(query_data["items"][0]["document"]["name"], "Alice")

        expire_resp = await self._client.patch(
            "/_internal/admin/api/storage/orm/expire",
            json={"collection": "redis_docs", "object_id": object_id, "expire_seconds": 120},
        )
        self.assertEqual(expire_resp.status_code, 200)
        self.assertEqual(expire_resp.json()["ttl_state"], "expiring")

    async def test_query_uses_native_redis_search_without_collection_scan(self):
        client = self._storage_config.get_orm_client()
        await client.set({"_id": "redis-native-1", "name": "Alice", "status": "active", "score": 9}, collection="redis_native_query_docs")
        redis_client = client._client()

        with patch.object(redis_client, "smembers", side_effect=AssertionError("redis ORM query should not scan collection ids")):
            query_resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={"collection": "redis_native_query_docs", "query": {"status": "active"}},
            )

        self.assertEqual(query_resp.status_code, 200)
        self.assertEqual(query_resp.json()["items"][0]["document"]["name"], "Alice")

    async def test_multi_segment_wildcard_uses_native_redis_search(self):
        client = self._storage_config.get_orm_client()
        for object_id, name in (("redis-wildcard-1", "abc"), ("redis-wildcard-2", "axbyc"), ("redis-wildcard-3", "abbbc"), ("redis-wildcard-4", "acb")):
            await client.set(
                {"_id": object_id, "name": name, "status": "active", "score": 9},
                collection="redis_wildcard_multi_docs",
            )
        redis_client = client._client()

        with patch.object(redis_client, "smembers", side_effect=AssertionError("redis wildcard query should not scan collection ids")):
            query_resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={
                    "collection": "redis_wildcard_multi_docs",
                    "query": {"name": {"$wildcard": "a*b*c"}},
                },
            )

        self.assertEqual(query_resp.status_code, 200)
        query_data = query_resp.json()
        self.assertEqual(query_data["total"], 3)
        self.assertEqual({item["document"]["name"] for item in query_data["items"]}, {"abc", "axbyc", "abbbc"})

    async def test_query_rejects_non_pushdown_filter_instead_of_scanning(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={"collection": "redis_docs", "document": {"name": "Alice", "status": "active", "score": 9}},
        )

        with patch(
            "core.storage.orm.client_base._match_query_or_expr",
            side_effect=AssertionError("redis ORM API query should not fall back to Python filtering"),
        ):
            resp = await self._client.post(
                "/_internal/admin/api/storage/orm/query",
                json={
                    "collection": "redis_docs",
                    "query": {"name": {"$unsupported": "Alice"}},
                },
            )

        self.assertEqual(resp.status_code, 400)

    async def test_schema_route_uses_redis_collection_meta(self):
        await self._client.put(
            "/_internal/admin/api/storage/orm/document",
            json={
                "collection": "redis_schema_docs",
                "document": {"name": "Bob", "status": "draft", "score": 3},
            },
        )
        resp = await self._client.get(
            "/_internal/admin/api/storage/orm/schema",
            params={"collection": "redis_schema_docs"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        sample_names = {item["name"] for item in data["sample_fields"]}
        self.assertIn("name", sample_names)
        self.assertIn("status", sample_names)


class TestRedisModelBinding(StorageRedisORMTestBase):
    async def test_redis_model_binds_to_redis_client(self):
        client = _RedisORMArticle._get_client()
        self.assertIsInstance(client, RedisORMClient)

        article = _RedisORMArticle(name="bound", status="ready", score=7)
        await article.save()
        try:
            fetched = await _RedisORMArticle.SearchOneById(str(article.id))
            self.assertIsInstance(fetched, _RedisORMArticle)
            assert fetched is not None
            self.assertEqual(fetched.name, "bound")
            self.assertEqual(fetched.status, "ready")
        finally:
            await article.delete()

    async def test_selected_search_one_by_id_uses_backend_projection_path(self):
        client = _RedisORMArticle._get_client()
        self.assertIsInstance(client, RedisORMClient)

        article = _RedisORMArticle(name="selected", status="ready", score=5)
        await article.save()
        try:
            with (
                patch.object(client, "get", side_effect=AssertionError("selected_search_by_id should not fall back to get()")),
                patch.object(client, "search", side_effect=AssertionError("selected_search_by_id should not fall back to search()")),
            ):
                payload = await _RedisORMArticle.SelectedSearchOneById(str(article.id), fields=("name", "status"))
            self.assertEqual(payload, {"id": str(article.id), "name": "selected", "status": "ready"})
        finally:
            await article.delete()


if __name__ == "__main__":
    unittest.main()