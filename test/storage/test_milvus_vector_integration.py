"""Integration tests: Milvus vector client — query pushdown, schema, CRUD, vector search.

Target: PyMilvusVectorClient against proj-milvus-standalone (127.0.0.1:19530).
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
    PyMilvusVectorClient,
    VectorIndex,
    VectorORMField,
    VectorORMModel,
)

# ── Shared test embedder ──────────────────────────────────────────────────────

async def _test_embedder(content):
    """Simple deterministic embedder for testing."""
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


MILVUS_URI = os.getenv("TEST_MILVUS_URI", "http://127.0.0.1:19530")

# Milvus "Bounded" consistency can cause data to be invisible immediately after
# flush.  We retry queries up to N times with a brief sleep to absorb the
# staleness window.
_CONSISTENCY_RETRIES = 8
_CONSISTENCY_SLEEP = 0.5  # seconds

# Use timestamp-based collection names to avoid stale data from prior runs
_SUFFIX = str(int(time.time()))

# Monotonic counter for unique client aliases to avoid pymilvus alias collision
_alias_counter = 0


# ── V1 model ─────────────────────────────────────────────────────────────────

class CrudItem(VectorORMModel, collection_name=f"mi_crud_{_SUFFIX}"):
    title: str = ""
    category: str = ""
    rank: int = 0
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class ScalarItem(VectorORMModel, collection_name=f"mi_scalar_{_SUFFIX}"):
    title: str = ""
    category: str = ""
    rank: int = 0
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class VecSearchItem(VectorORMModel, collection_name=f"mi_vecsrch_{_SUFFIX}"):
    title: str = ""
    category: str = ""
    rank: int = 0
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class SchemaItem(VectorORMModel, collection_name=f"mi_schema_{_SUFFIX}"):
    title: str = ""
    category: str = ""
    rank: int = 0
    tag: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class PerfItem(VectorORMModel, collection_name=f"mi_perf_{_SUFFIX}"):
    title: str = ""
    category: str = ""
    rank: int = 0
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client() -> PyMilvusVectorClient:
    global _alias_counter
    _alias_counter += 1
    client = PyMilvusVectorClient(uri=MILVUS_URI, name=f"proj_test_{os.getpid()}_{_alias_counter}")
    client.start()
    return client


async def _retry_get(client, model, oid, retries=_CONSISTENCY_RETRIES):
    """Retry `client.get()` to absorb Milvus eventual-consistency window."""
    for _ in range(retries):
        result = await client.get(model, oid)
        if result is not None:
            return result
        await asyncio.sleep(_CONSISTENCY_SLEEP)
    return None


async def _retry_search(client, model, query, *, limit=100, retries=_CONSISTENCY_RETRIES, expect_min=1):
    """Retry `client.search()` until at least *expect_min* results appear."""
    for _ in range(retries):
        results = [item async for item in client.search(model, query, limit=limit)]
        if len(results) >= expect_min:
            return results
        await asyncio.sleep(_CONSISTENCY_SLEEP)
    return results  # return last attempt regardless


async def _retry_count(client, collection, *, retries=_CONSISTENCY_RETRIES, expect_min=1):
    for _ in range(retries):
        count = await client.collection_count(collection)
        if count >= expect_min:
            return count
        await asyncio.sleep(_CONSISTENCY_SLEEP)
    return count


def setUpModule():
    """Skip entire module if Milvus is not reachable."""
    try:
        from pymilvus import connections, utility
        alias = f"integ-probe-{os.getpid()}"
        connections.connect(alias=alias, uri=MILVUS_URI)
        utility.list_collections(using=alias)
        connections.disconnect(alias)
    except Exception as exc:
        raise unittest.SkipTest(f"Milvus not available at {MILVUS_URI}: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════════════
# CRUD + Search
# ══════════════════════════════════════════════════════════════════════════════

class TestMilvusCRUD(unittest.IsolatedAsyncioTestCase):

    MODEL = CrudItem

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

        got = await _retry_get(self.client, self.MODEL, oid)
        self.assertIsNotNone(got, "get() returned None after set — consistency retry exhausted")
        self.assertEqual(got.title, "alpha doc")
        self.assertEqual(got.category, "science")
        self.assertEqual(got.rank, 1)

    async def test_set_update_get(self):
        item = self.MODEL(title="alpha doc", category="science", rank=1,
                      embedding=[1.0, 0.0, 0.0, 0.0])
        oid = await self.client.set(item)
        await _retry_get(self.client, self.MODEL, oid)  # wait for visibility

        # Update by setting same id
        item2 = self.MODEL(id=oid, title="alpha updated", category="science", rank=2,
                       embedding=[1.0, 0.0, 0.0, 0.0])
        oid2 = await self.client.set(item2)
        self.assertEqual(oid, oid2)

        # Wait for update to be visible
        for _ in range(_CONSISTENCY_RETRIES):
            got = await self.client.get(self.MODEL, oid)
            if got is not None and got.title == "alpha updated":
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertIsNotNone(got)
        self.assertEqual(got.title, "alpha updated")
        self.assertEqual(got.rank, 2)

    async def test_delete(self):
        item = self.MODEL(title="to_delete", category="temp", rank=0,
                      embedding=[0.25, 0.25, 0.25, 0.25])
        oid = await self.client.set(item)
        got = await _retry_get(self.client, self.MODEL, oid)
        self.assertIsNotNone(got, "item must be visible before delete test")

        deleted = await self.client.delete(self.MODEL.CollectionName, oid)
        self.assertTrue(deleted)

        # Retry to confirm deletion (also eventual)
        for _ in range(_CONSISTENCY_RETRIES):
            got = await self.client.get(self.MODEL, oid)
            if got is None:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertIsNone(got)

    async def test_collection_count(self):
        for i in range(3):
            await self.client.set(
                self.MODEL(title=f"doc_{i}", category="count", rank=i,
                       embedding=[float(i) * 0.1, 0.0, 0.0, 0.0])
            )
        count = await _retry_count(self.client, self.MODEL.CollectionName, expect_min=3)
        self.assertEqual(count, 3)


# ══════════════════════════════════════════════════════════════════════════════
# Scalar filter queries (pushdown to Milvus expr)
# ══════════════════════════════════════════════════════════════════════════════

class TestMilvusScalarQueries(unittest.IsolatedAsyncioTestCase):
    """Read-only query tests — seed data once, create fresh client per test."""

    MODEL = ScalarItem
    _seeded: bool = False
    _seed_ids: list[str] = []

    async def asyncSetUp(self):
        self.client = _make_client()
        await self.client.create_collection(self.MODEL)
        if not TestMilvusScalarQueries._seeded:
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
            await _retry_count(self.client, self.MODEL.CollectionName, expect_min=5)
            TestMilvusScalarQueries._seed_ids = ids
            TestMilvusScalarQueries._seeded = True
        self._ids = TestMilvusScalarQueries._seed_ids

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
        results = await _retry_search(self.client, self.MODEL, query, expect_min=max(expect_min, 1))
        return {r.title for r in results}

    # ── eq ──
    async def test_eq_str(self):
        titles = await self._search_titles({"category": "math"})
        self.assertEqual(titles, {"Alpha Paper", "Beta Paper", "Epsilon Guide"})

    async def test_eq_int(self):
        titles = await self._search_titles({"rank": 10})
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report"})

    async def test_eq_no_match(self):
        results = [item async for item in self.client.search(self.MODEL, {"category": "history"}, limit=100)]
        self.assertEqual(len(results), 0)

    # ── ne ──
    async def test_ne(self):
        titles = await self._search_titles({"category": {"$ne": "math"}}, expect_min=2)
        self.assertEqual(titles, {"Gamma Report", "Delta Notes"})

    # ── gt / gte / lt / lte ──
    async def test_gt(self):
        titles = await self._search_titles({"rank": {"$gt": 8}}, expect_min=2)
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report"})

    async def test_gte(self):
        titles = await self._search_titles({"rank": {"$gte": 8}}, expect_min=3)
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report", "Epsilon Guide"})

    async def test_lt(self):
        titles = await self._search_titles({"rank": {"$lt": 5}})
        self.assertEqual(titles, {"Delta Notes"})

    async def test_lte(self):
        titles = await self._search_titles({"rank": {"$lte": 5}}, expect_min=2)
        self.assertEqual(titles, {"Beta Paper", "Delta Notes"})

    # ── $in ──
    async def test_in(self):
        titles = await self._search_titles({"category": {"$in": ["math", "art"]}}, expect_min=4)
        self.assertEqual(titles, {"Alpha Paper", "Beta Paper", "Epsilon Guide", "Delta Notes"})

    async def test_in_int(self):
        titles = await self._search_titles({"rank": {"$in": [1, 10]}}, expect_min=3)
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report", "Delta Notes"})

    # ── compound: $and (implicit) ──
    async def test_compound_and_implicit(self):
        titles = await self._search_titles({"category": "math", "rank": {"$gte": 8}}, expect_min=2)
        self.assertEqual(titles, {"Alpha Paper", "Epsilon Guide"})

    # ── compound: $or ──
    async def test_compound_or(self):
        titles = await self._search_titles({
            "$or": [
                {"category": "art"},
                {"rank": 10},
            ]
        }, expect_min=3)
        self.assertEqual(titles, {"Alpha Paper", "Gamma Report", "Delta Notes"})

    # ── compound: $or + $and ──
    async def test_compound_or_and(self):
        titles = await self._search_titles({
            "$or": [
                {"category": "art"},
                {"rank": {"$gte": 8}},
            ],
            "category": {"$ne": "science"},
        }, expect_min=3)
        self.assertEqual(titles, {"Delta Notes", "Alpha Paper", "Epsilon Guide"})

    # ── get by id ──
    async def test_get_by_id(self):
        got = await _retry_get(self.client, self.MODEL, self._ids[0])
        self.assertIsNotNone(got)
        self.assertEqual(got.title, "Alpha Paper")

    # ── query None (all items) ──
    async def test_search_all(self):
        results = await _retry_search(self.client, self.MODEL, None, expect_min=5)
        self.assertEqual(len(results), 5)


# ══════════════════════════════════════════════════════════════════════════════
# Vector similarity search
# ══════════════════════════════════════════════════════════════════════════════

class TestMilvusVectorSearch(unittest.IsolatedAsyncioTestCase):
    """Read-only vector search tests — seed data once, create fresh client per test."""

    _seeded: bool = False

    async def asyncSetUp(self):
        self.client = _make_client()
        await self.client.create_collection(VecSearchItem)
        if not TestMilvusVectorSearch._seeded:
            seeds = [
                VecSearchItem(title="Alpha Paper", category="math", rank=10,
                       embedding=[1.0, 0.0, 0.0, 0.0]),
                VecSearchItem(title="Beta Paper", category="math", rank=5,
                       embedding=[0.0, 1.0, 0.0, 0.0]),
                VecSearchItem(title="Gamma Report", category="science", rank=10,
                       embedding=[0.0, 0.0, 1.0, 0.0]),
            ]
            for s in seeds:
                await self.client.set(s)
            await _retry_count(self.client, VecSearchItem.CollectionName, expect_min=3)
            TestMilvusVectorSearch._seeded = True

    async def asyncTearDown(self):
        self.client.close()

    @classmethod
    def tearDownClass(cls):
        if cls._seeded:
            async def _cleanup():
                client = _make_client()
                try:
                    await client.drop_collection(VecSearchItem.CollectionName)
                except Exception:
                    pass
                client.close()
            try:
                asyncio.run(_cleanup())
            except Exception:
                pass
            cls._seeded = False

    async def test_vector_search_top1(self):
        for _ in range(_CONSISTENCY_RETRIES):
            results = []
            async for item in self.client.search_vector(
                VecSearchItem, [1.0, 0.0, 0.0, 0.0],
                field="embedding", limit=1,
            ):
                results.append(item)
            if results:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Alpha Paper")

    async def test_vector_search_top3_order(self):
        for _ in range(_CONSISTENCY_RETRIES):
            results = []
            async for item in self.client.search_vector(
                VecSearchItem, [0.9, 0.1, 0.0, 0.0],
                field="embedding", limit=3,
            ):
                results.append(item)
            if len(results) >= 3:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertEqual(len(results), 3)
        # Closest to [0.9, 0.1, 0, 0] should be Alpha
        self.assertEqual(results[0].title, "Alpha Paper")

    async def test_vector_search_with_filter(self):
        for _ in range(_CONSISTENCY_RETRIES):
            results = []
            async for item in self.client.search_vector(
                VecSearchItem, [1.0, 0.0, 0.0, 0.0],
                field="embedding", limit=10,
                query={"category": "math"},
            ):
                results.append(item)
            if len(results) >= 2:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        titles = {r.title for r in results}
        self.assertIn("Alpha Paper", titles)
        self.assertIn("Beta Paper", titles)
        self.assertNotIn("Gamma Report", titles)

    async def test_vector_search_with_text_embedder(self):
        """Text search through the embedder function."""
        for _ in range(_CONSISTENCY_RETRIES):
            results = []
            async for item in self.client.search_vector(
                VecSearchItem, "alpha query",
                field="embedding", limit=1,
            ):
                results.append(item)
            if results:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Alpha Paper")


# ══════════════════════════════════════════════════════════════════════════════
# Schema evolution (Milvus: limited — cannot add fields to existing collection)
# ══════════════════════════════════════════════════════════════════════════════

class TestMilvusSchemaEvolution(unittest.IsolatedAsyncioTestCase):

    MODEL = SchemaItem

    async def asyncSetUp(self):
        self.client = _make_client()

    async def asyncTearDown(self):
        try:
            await self.client.drop_collection(self.MODEL.CollectionName)
        except Exception:
            pass
        self.client.close()

    async def test_create_collection_idempotent(self):
        """Calling create_collection twice should not crash."""
        try:
            await self.client.drop_collection(self.MODEL.CollectionName)
        except Exception:
            pass
        await self.client.create_collection(self.MODEL)
        # Second call — should be no-op
        self.client._bootstrapped_collections.discard(self.MODEL.CollectionName)
        await self.client.create_collection(self.MODEL)

        # Data should work
        oid = await self.client.set(
            self.MODEL(title="test", category="a", rank=1, tag="hello",
                   embedding=[1.0, 0.0, 0.0, 0.0])
        )
        got = await _retry_get(self.client, self.MODEL, oid)
        self.assertIsNotNone(got)
        self.assertEqual(got.title, "test")
        self.assertEqual(got.tag, "hello")

    async def test_drop_and_recreate_with_new_schema(self):
        """Drop + recreate is the Milvus way to evolve schemas."""
        try:
            await self.client.drop_collection(self.MODEL.CollectionName)
        except Exception:
            pass
        await self.client.create_collection(self.MODEL)

        oid = await self.client.set(
            self.MODEL(title="v2doc", category="math", rank=5, tag="physics",
                   embedding=[0.0, 1.0, 0.0, 0.0])
        )
        got = await _retry_get(self.client, self.MODEL, oid)
        self.assertIsNotNone(got)
        self.assertEqual(got.tag, "physics")

        # Query on new field
        results = await _retry_search(self.client, self.MODEL, {"tag": "physics"}, expect_min=1)
        titles = {r.title for r in results}
        self.assertIn("v2doc", titles)


# ══════════════════════════════════════════════════════════════════════════════
# Performance benchmark
# ══════════════════════════════════════════════════════════════════════════════

class TestMilvusPerformance(unittest.IsolatedAsyncioTestCase):
    """Performance benchmarks — seed data once, create fresh client per test."""

    MODEL = PerfItem
    _seeded: bool = False

    async def asyncSetUp(self):
        self.client = _make_client()
        await self.client.create_collection(self.MODEL)
        if not TestMilvusPerformance._seeded:
            for i in range(20):
                await self.client.set(
                    self.MODEL(title=f"doc_{i}", category="perf", rank=i,
                           embedding=[float(i % 4 == 0), float(i % 4 == 1),
                                      float(i % 4 == 2), float(i % 4 == 3)])
                )
            await _retry_count(self.client, self.MODEL.CollectionName, expect_min=20)
            TestMilvusPerformance._seeded = True

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

    async def test_scalar_query_performance(self):
        t0 = time.perf_counter()
        for _ in range(10):
            _ = [item async for item in self.client.search(self.MODEL, {"rank": {"$gte": 10}}, limit=20)]
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 10.0, f"10 scalar queries took {elapsed:.2f}s, expected <10s")

    async def test_vector_search_performance(self):
        t0 = time.perf_counter()
        for _ in range(10):
            _ = [item async for item in self.client.search_vector(
                self.MODEL, [1.0, 0.0, 0.0, 0.0], field="embedding", limit=5
            )]
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 10.0, f"10 vector searches took {elapsed:.2f}s, expected <10s")


# ══════════════════════════════════════════════════════════════════════════════
# Expire + max_size cleanup
# ══════════════════════════════════════════════════════════════════════════════

class ExpireItem(VectorORMModel, collection_name=f"mi_expire_{_SUFFIX}"):
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_test_embedder),
    )


class TestMilvusExpireAndMaxSize(unittest.IsolatedAsyncioTestCase):

    async def test_expire_removes_docs_after_ttl(self):
        """Documents with a short TTL should be removed by cleanup()."""
        client = _make_client()
        try:
            await client.create_collection(ExpireItem)

            # Insert 5 permanent docs
            for i in range(5):
                await client.set(
                    ExpireItem(title=f"perm_{i}", embedding=[float(i)*0.1, 0.0, 0.0, 0.0]),
                )
            # Insert 5 docs with 2-second TTL
            temp_ids: list[str] = []
            for i in range(5):
                oid = await client.set(
                    ExpireItem(title=f"temp_{i}", embedding=[0.0, float(i)*0.1, 0.0, 0.0]),
                    expire=2,
                )
                temp_ids.append(oid)

            await _retry_count(client, ExpireItem.CollectionName, expect_min=10)
            self.assertEqual(await client.collection_count(ExpireItem), 10)

            # Wait for TTL to elapse
            await asyncio.sleep(3)

            removed = await client.cleanup(force=True)
            self.assertGreaterEqual(removed, 5, f"Expected >=5 expired docs removed, got {removed}")

            # Wait for Milvus bounded consistency to reflect the deletes
            remaining = 10
            for _ in range(_CONSISTENCY_RETRIES * 2):
                remaining = await client.collection_count(ExpireItem)
                if remaining <= 5:
                    break
                await asyncio.sleep(_CONSISTENCY_SLEEP)
            self.assertEqual(remaining, 5, f"Expected 5 permanent docs to survive, got {remaining}")
        finally:
            try:
                await client.drop_collection(ExpireItem.CollectionName)
            except Exception:
                pass
            client.close()

    async def test_set_expire_and_get_expire(self):
        """set_expire() + get_expire() roundtrip."""
        client = _make_client()
        try:
            await client.create_collection(ExpireItem)
            oid = await client.set(
                ExpireItem(title="will expire", embedding=[1.0, 0.0, 0.0, 0.0]),
            )
            await _retry_get(client, ExpireItem, oid)

            # Initially no TTL
            ttl = await client.get_expire(ExpireItem, oid)
            self.assertIsNone(ttl)

            # Set expire
            ok = await client.set_expire(ExpireItem, oid, 120)
            self.assertTrue(ok)

            ttl = await client.get_expire(ExpireItem, oid)
            self.assertIsNotNone(ttl)
            self.assertGreater(ttl, 0)
            self.assertLessEqual(ttl, 120)
        finally:
            try:
                await client.drop_collection(ExpireItem.CollectionName)
            except Exception:
                pass
            client.close()

    async def test_max_size_lru_eviction(self):
        """When max_size is set, cleanup() should evict LRU docs."""
        global _alias_counter
        _alias_counter += 1
        client = PyMilvusVectorClient(
            uri=MILVUS_URI,
            name=f"proj_test_{os.getpid()}_{_alias_counter}",
            max_size=8,
        )
        client.start()
        try:
            await client.create_collection(ExpireItem)

            # Insert 15 docs
            for i in range(15):
                await client.set(
                    ExpireItem(title=f"lru_{i}", embedding=[float(i)*0.05, 0.0, 0.0, 0.0]),
                )

            await _retry_count(client, ExpireItem.CollectionName, expect_min=15)
            self.assertEqual(await client.collection_count(ExpireItem), 15)

            removed = await client.cleanup(force=True)
            self.assertGreater(removed, 0, "Expected some docs evicted by max_size LRU")

            # Wait for Milvus bounded consistency to reflect the deletes
            remaining = 15
            for _ in range(_CONSISTENCY_RETRIES * 2):
                remaining = await client.collection_count(ExpireItem)
                if remaining <= 8:
                    break
                await asyncio.sleep(_CONSISTENCY_SLEEP)
            self.assertLessEqual(remaining, 8, f"Expected <= 8 docs after LRU, got {remaining}")
        finally:
            try:
                await client.drop_collection(ExpireItem.CollectionName)
            except Exception:
                pass
            client.close()


if __name__ == "__main__":
    unittest.main()
