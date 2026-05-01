"""Stress & concurrency tests for ORM storage backends.

Tests:
  1. Concurrent writes: 1000 records via asyncio.gather
  2. Concurrent reads: 1000 records via asyncio.gather
  3. Bulk insert: 10000 records, then query performance
  4. Mixed read/write concurrency
  5. Large payload JSON serialization
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


from core.storage.orm import (
    ORMModel,
    ORMField,
    SQLiteORMClient,
)

_TMP = Path(__file__).resolve().parents[2] / "tmp"
_TMP.mkdir(exist_ok=True)


class _NondebugAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    """IsolatedAsyncioTestCase with debug=False for realistic perf benchmarks."""
    def _setupAsyncioRunner(self):
        self._asyncioRunner = asyncio.Runner(debug=False)



# ── Models ────────────────────────────────────────────────────────────────────

class StressItem(ORMModel, full_collection_name="stress_item"):
    name: str = ORMField("", index=True, max_length=128)
    score: float = ORMField(0.0, index=True)
    category: str = ORMField("", index=True, max_length=32)
    active: bool = False
    tags: dict = {}
    description: str = ORMField("", max_length=65536)


class BulkItem(ORMModel, full_collection_name="bulk_item"):
    idx: int = ORMField(0, index=True)
    name: str = ORMField("", index=True, max_length=64)
    value: float = 0.0
    category: str = ORMField("", max_length=32)


# ══════════════════════════════════════════════════════════════════════════════
# SQLite Stress Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSQLiteConcurrentWrites(_NondebugAsyncTestCase):
    """Concurrent writes: 1000 records via asyncio.gather"""

    async def asyncSetUp(self):
        db = _TMP / "stress_concurrent_writes.sqlite3"
        self._client = SQLiteORMClient(db_path=str(db))
        self._client.start()
        try:
            await self._client.drop_collection("stress_item")
        except Exception:
            pass
        await self._client.create_collection(StressItem)

    async def asyncTearDown(self):
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass

    async def test_1000_concurrent_writes(self):
        N = 1000

        async def write_one(i: int) -> str:
            item = StressItem(
                name=f"item_{i:04d}",
                score=float(i % 100),
                category=f"cat_{i % 10}",
                active=i % 2 == 0,
                tags={"batch": "concurrent", "idx": str(i)},
                description=f"Item number {i} in the stress test batch",
            )
            return await self._client.set(item)

        t0 = time.perf_counter()
        ids = await asyncio.gather(*(write_one(i) for i in range(N)))
        elapsed = time.perf_counter() - t0

        self.assertEqual(len(ids), N)
        self.assertEqual(len(set(ids)), N, "All IDs should be unique")
        print(f"\n  [PERF] {N} concurrent writes: {elapsed:.3f}s ({N/elapsed:.0f} ops/s)")

    async def test_1000_concurrent_reads(self):
        N = 1000

        # Seed data first (sequential to avoid confusing the test)
        obj_ids: list[str] = []
        for i in range(N):
            item = StressItem(
                name=f"read_item_{i:04d}",
                score=float(i),
                category=f"cat_{i % 5}",
                active=True,
            )
            oid = await self._client.set(item)
            obj_ids.append(oid)

        async def read_one(oid: str):
            return await self._client.get(StressItem, oid)

        t0 = time.perf_counter()
        results = await asyncio.gather(*(read_one(oid) for oid in obj_ids))
        elapsed = time.perf_counter() - t0

        none_count = sum(1 for r in results if r is None)
        self.assertEqual(none_count, 0, f"{none_count} reads returned None")
        print(f"\n  [PERF] {N} concurrent reads: {elapsed:.3f}s ({N/elapsed:.0f} ops/s)")

    async def test_mixed_read_write(self):
        """50% writes + 50% reads concurrently."""
        N = 500

        # Pre-seed some data
        seed_ids: list[str] = []
        for i in range(N):
            item = StressItem(name=f"seed_{i}", score=float(i), category="seed")
            seed_ids.append(await self._client.set(item))

        async def write_op(i: int):
            item = StressItem(name=f"mixed_write_{i}", score=float(i), category="mixed")
            return await self._client.set(item)

        async def read_op(oid: str):
            return await self._client.get(StressItem, oid)

        tasks = []
        for i in range(N):
            tasks.append(write_op(i))
            tasks.append(read_op(seed_ids[i]))

        t0 = time.perf_counter()
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - t0

        total_ops = len(tasks)
        print(f"\n  [PERF] {total_ops} mixed ops ({N} writes + {N} reads): {elapsed:.3f}s ({total_ops/elapsed:.0f} ops/s)")


class TestSQLiteBulkInsert(_NondebugAsyncTestCase):
    """Bulk insert 10k records then query performance."""

    async def asyncSetUp(self):
        db = _TMP / "stress_bulk_insert.sqlite3"
        self._client = SQLiteORMClient(db_path=str(db), write_buffer_size=200)
        self._client.start()
        try:
            await self._client.drop_collection("bulk_item")
        except Exception:
            pass
        await self._client.create_collection(BulkItem)

    async def asyncTearDown(self):
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass

    async def test_10000_sequential_inserts(self):
        N = 10000
        t0 = time.perf_counter()
        for i in range(N):
            item = BulkItem(
                idx=i,
                name=f"bulk_{i:05d}",
                value=float(i) * 0.1,
                category=f"cat_{i % 20}",
            )
            await self._client.set(item)
        t_insert = time.perf_counter() - t0
        print(f"\n  [PERF] {N} sequential inserts: {t_insert:.3f}s ({N/t_insert:.0f} ops/s)")

        # Query by indexed field — exact match
        t0 = time.perf_counter()
        results = []
        async for item in self._client.search(BulkItem, {"idx": 5000}, limit=1):
            results.append(item)
        t_exact = time.perf_counter() - t0
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].idx, 5000)
        print(f"  [PERF] Exact index query: {t_exact*1000:.1f}ms")

        # Range query
        t0 = time.perf_counter()
        results = []
        async for item in self._client.search(BulkItem, {"idx": {"$gte": 9990}}, limit=100):
            results.append(item)
        t_range = time.perf_counter() - t0
        self.assertEqual(len(results), 10)
        print(f"  [PERF] Range query (10 results from 10k): {t_range*1000:.1f}ms")

        # Category query (indexed str)
        t0 = time.perf_counter()
        results = []
        async for item in self._client.search(BulkItem, {"category": "cat_0"}, limit=1000):
            results.append(item)
        t_cat = time.perf_counter() - t0
        self.assertEqual(len(results), 500)  # 10000 / 20 categories
        print(f"  [PERF] Category query (500 results): {t_cat*1000:.1f}ms")

    async def test_set_many_bulk(self):
        """Test set_many with 1000 records at once."""
        N = 1000
        items = [
            BulkItem(
                idx=i + 100000,
                name=f"setmany_{i:04d}",
                value=float(i),
                category=f"cat_{i % 5}",
            )
            for i in range(N)
        ]
        t0 = time.perf_counter()
        ids = await self._client.set_many(items)
        elapsed = time.perf_counter() - t0
        self.assertEqual(len(ids), N)
        print(f"\n  [PERF] set_many({N}): {elapsed:.3f}s ({N/elapsed:.0f} ops/s)")


class TestSQLiteConcurrentCollections(_NondebugAsyncTestCase):
    """Multiple concurrent operations on different collections."""

    async def asyncSetUp(self):
        db = _TMP / "stress_multi_coll.sqlite3"
        self._client = SQLiteORMClient(db_path=str(db))
        self._client.start()
        for coll in ("stress_item", "bulk_item"):
            try:
                await self._client.drop_collection(coll)
            except Exception:
                pass

    async def asyncTearDown(self):
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass

    async def test_concurrent_different_collections(self):
        """Write to two collections concurrently."""
        await self._client.create_collection(StressItem)
        await self._client.create_collection(BulkItem)

        N = 200

        async def write_stress(i: int):
            return await self._client.set(StressItem(name=f"s_{i}", score=float(i), category="x"))

        async def write_bulk(i: int):
            return await self._client.set(BulkItem(idx=i, name=f"b_{i}", value=float(i), category="y"))

        tasks = []
        for i in range(N):
            tasks.append(write_stress(i))
            tasks.append(write_bulk(i))

        t0 = time.perf_counter()
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - t0

        self.assertEqual(len(results), N * 2)
        print(f"\n  [PERF] {N*2} concurrent cross-collection writes: {elapsed:.3f}s ({N*2/elapsed:.0f} ops/s)")


class TestSQLiteLargePayload(_NondebugAsyncTestCase):
    """Write and read records with large JSON payloads."""

    async def asyncSetUp(self):
        db = _TMP / "stress_large_payload.sqlite3"
        self._client = SQLiteORMClient(db_path=str(db))
        self._client.start()
        try:
            await self._client.drop_collection("stress_item")
        except Exception:
            pass
        await self._client.create_collection(StressItem)

    async def asyncTearDown(self):
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass

    async def test_large_tags_dict(self):
        """Write a record with a large tags dict (10k+ chars)."""
        large_tags = {f"key_{i}": f"value_{i}_{'x' * 50}" for i in range(200)}
        item = StressItem(name="large_tags", score=99.9, category="large", tags=large_tags)
        oid = await self._client.set(item)
        retrieved = await self._client.get(StressItem, oid)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "large_tags")
        # Tags are stored in payload_json, so should survive round-trip
        self.assertEqual(len(retrieved.tags), 200)

    async def test_large_description(self):
        """Write a record with a very long description string."""
        long_desc = "A" * 50000
        item = StressItem(name="long_desc", score=0.0, category="long", description=long_desc)
        oid = await self._client.set(item)
        retrieved = await self._client.get(StressItem, oid)
        self.assertIsNotNone(retrieved)
        self.assertEqual(len(retrieved.description), 50000)


if __name__ == "__main__":
    unittest.main()
