"""Integration tests: MongoDB vector client — CRUD, scalar queries, vector search, expire/max_size.

Target: MongoVectorClient against MongoDB (127.0.0.1:27017).
"""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from core.storage.vector import (
    MongoVectorClient,
    VectorIndex,
    VectorORMField,
    VectorORMModel,
)

# ── Shared test embedder ──────────────────────────────────────────────────────

async def _test_embedder(content):
    text = str(content).lower()
    if "alpha" in text:
        return [1.0, 0.0, 0.0, 0.0]
    if "beta" in text:
        return [0.0, 1.0, 0.0, 0.0]
    if "gamma" in text:
        return [0.0, 0.0, 1.0, 0.0]
    if "delta" in text:
        return [0.0, 0.0, 0.0, 1.0]
    return [0.25, 0.25, 0.25, 0.25]


MONGO_URL = os.getenv("TEST_MONGO_URL", "mongodb://127.0.0.1:27018/?directConnection=true")
_SUFFIX = str(int(time.time()))
_DB_NAME = f"proj_vec_integ_{_SUFFIX}"


# ── Models ────────────────────────────────────────────────────────────────────

class MongoCrudItem(VectorORMModel, collection_name=f"mv_crud_{_SUFFIX}"):
    title: str = ""
    category: str = ""
    rank: int = 0
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class MongoScalarItem(VectorORMModel, collection_name=f"mv_scalar_{_SUFFIX}"):
    title: str = ""
    category: str = ""
    rank: int = 0
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class MongoVecSearchItem(VectorORMModel, collection_name=f"mv_vecsrch_{_SUFFIX}"):
    title: str = ""
    category: str = ""
    rank: int = 0
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class MongoExpireItem(VectorORMModel, collection_name=f"mv_expire_{_SUFFIX}"):
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client(**extra) -> MongoVectorClient:
    client = MongoVectorClient(
        mongo_url=MONGO_URL,
        database=_DB_NAME,
        **extra,
    )
    client.start()
    return client


def setUpModule():
    """Skip entire module if MongoDB is not reachable or Atlas Search is disabled."""
    from pymongo import MongoClient
    try:
        c = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
        c.server_info()
    except Exception as exc:
        raise unittest.SkipTest(f"MongoDB not available at {MONGO_URL}: {exc}") from exc
    # Probe Atlas Search support
    try:
        db = c[_DB_NAME]
        db.create_collection("_probe_search_support")
        list(db["_probe_search_support"].list_search_indexes())
        db.drop_collection("_probe_search_support")
    except Exception as exc:
        c.drop_database(_DB_NAME)
        c.close()
        raise unittest.SkipTest(
            f"Atlas Search / Vector Search not enabled at {MONGO_URL}: {exc}"
        ) from exc
    c.close()


def tearDownModule():
    """Drop the entire test database after all tests."""
    try:
        from pymongo import MongoClient
        c = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
        c.drop_database(_DB_NAME)
        c.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# CRUD
# ══════════════════════════════════════════════════════════════════════════════

class TestMongoCRUD(unittest.IsolatedAsyncioTestCase):
    MODEL = MongoCrudItem

    async def asyncSetUp(self):
        self.client = _make_client()
        await self.client.create_collection(self.MODEL)

    async def asyncTearDown(self):
        try:
            await self.client.drop_collection(self.MODEL.CollectionName)
        except Exception:
            pass
        self.client.close()

    async def test_set_and_get(self):
        item = self.MODEL(title="alpha doc", category="science", rank=1,
                          embedding=[1.0, 0.0, 0.0, 0.0])
        oid = await self.client.set(item)
        self.assertTrue(oid)

        got = await self.client.get(self.MODEL, oid)
        self.assertIsNotNone(got)
        self.assertEqual(got.title, "alpha doc")
        self.assertEqual(got.category, "science")
        self.assertEqual(got.rank, 1)

    async def test_set_update_get(self):
        item = self.MODEL(title="alpha doc", category="science", rank=1,
                          embedding=[1.0, 0.0, 0.0, 0.0])
        oid = await self.client.set(item)

        item2 = self.MODEL(id=oid, title="alpha updated", category="science", rank=2,
                           embedding=[1.0, 0.0, 0.0, 0.0])
        oid2 = await self.client.set(item2)
        self.assertEqual(oid, oid2)

        got = await self.client.get(self.MODEL, oid)
        self.assertIsNotNone(got)
        self.assertEqual(got.title, "alpha updated")
        self.assertEqual(got.rank, 2)

    async def test_delete(self):
        item = self.MODEL(title="to_delete", category="temp", rank=0,
                          embedding=[0.25, 0.25, 0.25, 0.25])
        oid = await self.client.set(item)
        got = await self.client.get(self.MODEL, oid)
        self.assertIsNotNone(got)

        deleted = await self.client.delete(self.MODEL.CollectionName, oid)
        self.assertTrue(deleted)

        got = await self.client.get(self.MODEL, oid)
        self.assertIsNone(got)

    async def test_collection_count(self):
        for i in range(3):
            await self.client.set(
                self.MODEL(title=f"doc_{i}", category="count", rank=i,
                           embedding=[float(i)*0.1, 0.0, 0.0, 0.0])
            )
        count = await self.client.collection_count(self.MODEL.CollectionName)
        self.assertEqual(count, 3)


# ══════════════════════════════════════════════════════════════════════════════
# Scalar filter queries
# ══════════════════════════════════════════════════════════════════════════════

class TestMongoScalarQueries(unittest.IsolatedAsyncioTestCase):
    MODEL = MongoScalarItem
    _seeded: bool = False
    _seed_ids: list[str] = []

    async def asyncSetUp(self):
        self.client = _make_client()
        await self.client.create_collection(self.MODEL)
        if not TestMongoScalarQueries._seeded:
            seeds = [
                self.MODEL(title="Alpha Paper", category="math", rank=10,
                           embedding=[1.0, 0.0, 0.0, 0.0]),
                self.MODEL(title="Beta Paper", category="math", rank=5,
                           embedding=[0.0, 1.0, 0.0, 0.0]),
                self.MODEL(title="Gamma Report", category="science", rank=10,
                           embedding=[0.0, 0.0, 1.0, 0.0]),
                self.MODEL(title="Delta Notes", category="art", rank=1,
                           embedding=[0.0, 0.0, 0.0, 1.0]),
                self.MODEL(title="Epsilon Guide", category="math", rank=8,
                           embedding=[0.5, 0.5, 0.0, 0.0]),
            ]
            ids = []
            for s in seeds:
                oid = await self.client.set(s)
                ids.append(oid)
            TestMongoScalarQueries._seed_ids = ids
            TestMongoScalarQueries._seeded = True
        self._ids = TestMongoScalarQueries._seed_ids

    async def asyncTearDown(self):
        self.client.close()

    @classmethod
    def tearDownClass(cls):
        if cls._seeded:
            async def _cleanup():
                client = _make_client()
                try:
                    await client.drop_collection(cls.MODEL.CollectionName)
                except Exception:
                    pass
                client.close()
            try:
                asyncio.run(_cleanup())
            except Exception:
                pass
            cls._seeded = False

    async def _search_titles(self, query, *, expect_min=0) -> set[str]:
        results = [item async for item in self.client.search(self.MODEL, query, limit=100)]
        return {r.title for r in results}

    async def test_eq_str(self):
        titles = await self._search_titles({"category": "math"})
        self.assertEqual(titles, {"Alpha Paper", "Beta Paper", "Epsilon Guide"})

    async def test_eq_int(self):
        titles = await self._search_titles({"rank": 10})
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report"})

    async def test_eq_no_match(self):
        results = [item async for item in self.client.search(self.MODEL, {"category": "history"}, limit=100)]
        self.assertEqual(len(results), 0)

    async def test_ne(self):
        titles = await self._search_titles({"category": {"$ne": "math"}})
        self.assertEqual(titles, {"Gamma Report", "Delta Notes"})

    async def test_gt(self):
        titles = await self._search_titles({"rank": {"$gt": 8}})
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report"})

    async def test_gte(self):
        titles = await self._search_titles({"rank": {"$gte": 8}})
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report", "Epsilon Guide"})

    async def test_lt(self):
        titles = await self._search_titles({"rank": {"$lt": 5}})
        self.assertEqual(titles, {"Delta Notes"})

    async def test_lte(self):
        titles = await self._search_titles({"rank": {"$lte": 5}})
        self.assertEqual(titles, {"Beta Paper", "Delta Notes"})

    async def test_in(self):
        titles = await self._search_titles({"category": {"$in": ["math", "art"]}})
        self.assertEqual(titles, {"Alpha Paper", "Beta Paper", "Epsilon Guide", "Delta Notes"})

    async def test_in_int(self):
        titles = await self._search_titles({"rank": {"$in": [1, 10]}})
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report", "Delta Notes"})

    async def test_compound_and_implicit(self):
        titles = await self._search_titles({"category": "math", "rank": {"$gte": 8}})
        self.assertEqual(titles, {"Alpha Paper", "Epsilon Guide"})

    async def test_compound_or(self):
        titles = await self._search_titles({
            "$or": [
                {"category": "art"},
                {"rank": 10},
            ]
        })
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report", "Delta Notes"})

    async def test_get_by_id(self):
        got = await self.client.get(self.MODEL, self._ids[0])
        self.assertIsNotNone(got)
        self.assertEqual(got.title, "Alpha Paper")

    async def test_search_all(self):
        results = [item async for item in self.client.search(self.MODEL, None, limit=100)]
        self.assertEqual(len(results), 5)


# ══════════════════════════════════════════════════════════════════════════════
# Vector similarity search
# ══════════════════════════════════════════════════════════════════════════════

class TestMongoVectorSearch(unittest.IsolatedAsyncioTestCase):
    _seeded: bool = False

    async def asyncSetUp(self):
        self.client = _make_client()
        await self.client.create_collection(MongoVecSearchItem)
        if not TestMongoVectorSearch._seeded:
            seeds = [
                MongoVecSearchItem(title="Alpha Paper", category="math", rank=10,
                                   embedding=[1.0, 0.0, 0.0, 0.0]),
                MongoVecSearchItem(title="Beta Paper", category="math", rank=5,
                                   embedding=[0.0, 1.0, 0.0, 0.0]),
                MongoVecSearchItem(title="Gamma Report", category="science", rank=10,
                                   embedding=[0.0, 0.0, 1.0, 0.0]),
            ]
            for s in seeds:
                await self.client.set(s)
            # Wait for vector search index to incorporate new documents
            await asyncio.sleep(2)
            TestMongoVectorSearch._seeded = True

    async def asyncTearDown(self):
        self.client.close()

    @classmethod
    def tearDownClass(cls):
        if cls._seeded:
            async def _cleanup():
                client = _make_client()
                try:
                    await client.drop_collection(MongoVecSearchItem.CollectionName)
                except Exception:
                    pass
                client.close()
            try:
                asyncio.run(_cleanup())
            except Exception:
                pass
            cls._seeded = False

    async def test_vector_search_top1(self):
        results = [item async for item in self.client.search_vector(
            MongoVecSearchItem, [1.0, 0.0, 0.0, 0.0],
            field="embedding", limit=1,
        )]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Alpha Paper")

    async def test_vector_search_top3_order(self):
        results = [item async for item in self.client.search_vector(
            MongoVecSearchItem, [0.9, 0.1, 0.0, 0.0],
            field="embedding", limit=3,
        )]
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].title, "Alpha Paper")

    async def test_vector_search_with_filter(self):
        results = [item async for item in self.client.search_vector(
            MongoVecSearchItem, [1.0, 0.0, 0.0, 0.0],
            field="embedding", limit=10,
            query={"category": "math"},
        )]
        titles = {r.title for r in results}
        self.assertIn("Alpha Paper", titles)
        self.assertIn("Beta Paper", titles)
        self.assertNotIn("Gamma Report", titles)

    async def test_vector_search_with_text_embedder(self):
        results = [item async for item in self.client.search_vector(
            MongoVecSearchItem, "alpha query",
            field="embedding", limit=1,
        )]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Alpha Paper")


# ══════════════════════════════════════════════════════════════════════════════
# Expire + max_size cleanup
# ══════════════════════════════════════════════════════════════════════════════

class TestMongoExpireAndMaxSize(unittest.IsolatedAsyncioTestCase):

    async def test_expire_removes_docs_after_ttl(self):
        client = _make_client()
        try:
            await client.create_collection(MongoExpireItem)

            for i in range(5):
                await client.set(
                    MongoExpireItem(title=f"perm_{i}", embedding=[float(i)*0.1, 0.0, 0.0, 0.0]),
                )
            temp_ids: list[str] = []
            for i in range(5):
                oid = await client.set(
                    MongoExpireItem(title=f"temp_{i}", embedding=[0.0, float(i)*0.1, 0.0, 0.0]),
                    expire=2,
                )
                temp_ids.append(oid)

            self.assertEqual(await client.collection_count(MongoExpireItem), 10)

            await asyncio.sleep(3)

            removed = await client.cleanup(force=True)
            self.assertGreaterEqual(removed, 5)

            remaining = await client.collection_count(MongoExpireItem)
            self.assertEqual(remaining, 5)
        finally:
            try:
                await client.drop_collection(MongoExpireItem.CollectionName)
            except Exception:
                pass
            client.close()

    async def test_set_expire_and_get_expire(self):
        client = _make_client()
        try:
            await client.create_collection(MongoExpireItem)
            oid = await client.set(
                MongoExpireItem(title="will expire", embedding=[1.0, 0.0, 0.0, 0.0]),
            )

            ttl = await client.get_expire(MongoExpireItem, oid)
            self.assertIsNone(ttl)

            ok = await client.set_expire(MongoExpireItem, oid, 120)
            self.assertTrue(ok)

            ttl = await client.get_expire(MongoExpireItem, oid)
            self.assertIsNotNone(ttl)
            self.assertGreater(ttl, 0)
            self.assertLessEqual(ttl, 120)
        finally:
            try:
                await client.drop_collection(MongoExpireItem.CollectionName)
            except Exception:
                pass
            client.close()

    async def test_max_size_lru_eviction(self):
        client = _make_client(max_size=8)
        try:
            await client.create_collection(MongoExpireItem)

            for i in range(15):
                await client.set(
                    MongoExpireItem(title=f"lru_{i}", embedding=[float(i)*0.05, 0.0, 0.0, 0.0]),
                )

            self.assertEqual(await client.collection_count(MongoExpireItem), 15)

            removed = await client.cleanup(force=True)
            self.assertGreater(removed, 0)

            remaining = await client.collection_count(MongoExpireItem)
            self.assertLessEqual(remaining, 8)
        finally:
            try:
                await client.drop_collection(MongoExpireItem.CollectionName)
            except Exception:
                pass
            client.close()


if __name__ == "__main__":
    unittest.main()
