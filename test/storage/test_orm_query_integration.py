"""Integration tests: ORM field queries against REAL database backends.

Targets: SQLite, PostgreSQL (5433), MySQL (3307), MongoDB (native 27017), Redis (6379).
Tests extreme edge cases — Enum, datetime/date, type coercion, structured BaseModel,
garbage values, comparison operators, contains/wildcard/regex — across all backends.
"""
import asyncio
import os
import sys
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import ClassVar

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from pydantic import BaseModel, Field as PydanticField

from core.storage.orm import (
    ORMModel,
    ORMField,
    SQLiteORMClient,
    SQL_ORM_Client,
    PostgreSQLORMClient,
    MySQLORMClient,
    MongoORMClient,
    RedisORMClient,
)


# ─── Test enums ───────────────────────────────────────────────────────────────
class Color(str, Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class Priority(IntEnum):
    LOW = 1
    MEDIUM = 5
    HIGH = 10


# ─── Nested BaseModel ────────────────────────────────────────────────────────
class Address(BaseModel):
    city: str = ""
    zip_code: str = ""


# ─── Test ORMModel ────────────────────────────────────────────────────────────
class EdgeItem(ORMModel, collection_name="integ_edge_item"):
    name: str = ORMField("", index=True)
    score: float = ORMField(0.0, index=True)
    priority: int = ORMField(0, index=True)
    color: str = ORMField("", index=True)
    active: bool = False
    created: str = ""          # ISO datetime stored as str
    tags: list[str] = []
    address: Address = Address()
    note: str = ""


# ─── unique collection name per backend to avoid collisions ──────────────────
_BACKEND_COLLECTION_NAMES: dict[str, str] = {
    "sqlite": "integ_edge_sqlite",
    "postgresql": "integ_edge_pg",
    "mysql": "integ_edge_mysql",
    "mongo": "integ_edge_mongo",
    "redis": "integ_edge_redis",
}


def _make_model(backend: str):
    """Create a fresh ORMModel class with a unique collection name for each backend."""
    coll = _BACKEND_COLLECTION_NAMES[backend]

    class _Item(ORMModel, full_collection_name=coll):
        name: str = ORMField("", index=True)
        score: float = ORMField(0.0, index=True)
        priority: int = ORMField(0, index=True)
        color: str = ORMField("", index=True)
        active: bool = False
        created: str = ""
        tags: list[str] = []
        address: Address = Address()
        note: str = ""

    return _Item


# ─── DB connection helpers ────────────────────────────────────────────────────
_TMP_DIR = Path(__file__).resolve().parent.parent.parent / "tmp"


def _sqlite_client() -> SQLiteORMClient:
    db_path = _TMP_DIR / "test_integ_edge.sqlite3"
    client = SQLiteORMClient(db_path=str(db_path))
    client.start()
    return client


def _pg_client() -> PostgreSQLORMClient:
    client = PostgreSQLORMClient(
        host="127.0.0.1",
        port=5433,
        username="postgres",
        password="postgres",
        database="projtemplate_test",
    )
    client.start()
    return client


def _mysql_client() -> MySQLORMClient:
    client = MySQLORMClient(
        host="127.0.0.1",
        port=3307,
        username="root",
        password="rootpass",
        database="projtemplate_test",
    )
    client.start()
    return client


def _mongo_client() -> MongoORMClient:
    client = MongoORMClient(
        mongo_url=os.getenv("TEST_MONGO_URL", "mongodb://127.0.0.1:27017/?directConnection=true"),
        database="projtemplate_integ_test",
    )
    client.start()
    return client


def _redis_client() -> RedisORMClient:
    client = RedisORMClient(
        url="redis://127.0.0.1:6379/0",
        prefix="orm:integ_test",
    )
    client.start()
    return client


# ─── Seed data ────────────────────────────────────────────────────────────────
_SEEDS = [
    dict(name="Alice", score=95.5, priority=10, color="red", active=True,
         created="2025-06-01T10:00:00", tags=["math", "science"],
         address={"city": "Hong Kong", "zip_code": "999077"}, note="Top student"),
    dict(name="Bob", score=60.0, priority=5, color="green", active=False,
         created="2025-03-15T08:30:00", tags=["art"],
         address={"city": "Taipei", "zip_code": "100"}, note="Average"),
    dict(name="Charlie", score=88.8, priority=10, color="blue", active=True,
         created="2025-01-20T14:00:00", tags=["math", "art", "music"],
         address={"city": "Tokyo", "zip_code": "100-0001"}, note="Good at math"),
    dict(name="Diana", score=0.0, priority=1, color="red", active=False,
         created="2024-12-31T23:59:59", tags=[],
         address={"city": "Hong Kong", "zip_code": "999077"}, note=""),
    dict(name="Eve", score=100.0, priority=10, color="green", active=True,
         created="2025-06-01T10:00:00", tags=["science"],
         address={"city": "Seoul", "zip_code": "04524"}, note="Perfect score"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Base test class — parametrized per backend
# ═══════════════════════════════════════════════════════════════════════════════

# Track seeded collections so we don't re-seed across tests within one process,
# but still create a fresh client per test (required for IsolatedAsyncioTestCase
# because each test gets its own event loop).
_SEEDED_COLLECTIONS: set[str] = set()
_SEED_IDS_CACHE: dict[str, list[str]] = {}


class _BackendTestBase(unittest.IsolatedAsyncioTestCase):
    """Subclass this, override _backend_name and _make_client."""
    __test__ = False  # Prevent pytest from collecting this base class
    _backend_name: ClassVar[str]
    _client = None
    _model_cls = None

    @classmethod
    def _make_client(cls):
        raise NotImplementedError

    async def asyncSetUp(self):
        # Fresh client per test — required because IsolatedAsyncioTestCase uses
        # a new event loop for each method, and SQLAlchemy async engines are
        # bound to the loop they were created on.
        self._client = self._make_client()
        if self.__class__._model_cls is None:
            self.__class__._model_cls = _make_model(self._backend_name)
        coll_key = f"{self._backend_name}:{self._model_cls.CollectionName}"
        if coll_key not in _SEEDED_COLLECTIONS:
            model = self._model_cls
            client = self._client
            try:
                await client.drop_collection(model.CollectionName)
            except Exception:
                pass
            await client.create_collection(model)
            ids = []
            for seed in _SEEDS:
                obj = model(**seed)
                oid = await client.set(obj)
                ids.append(oid)
            _SEED_IDS_CACHE[coll_key] = ids
            _SEEDED_COLLECTIONS.add(coll_key)
        self._seed_ids = _SEED_IDS_CACHE.get(coll_key, [])

    async def asyncTearDown(self):
        if self._client:
            try:
                if hasattr(self._client, 'aclose'):
                    await self._client.aclose()
                else:
                    self._client.close()
            except Exception:
                pass

    # ── helpers ────────────────────────────────────────────────────────────────
    async def _search(self, query, limit=100):
        return [item async for item in self._client.search(
            self._model_cls, query, limit=limit
        )]

    async def _search_count(self, query):
        return len(await self._search(query))

    async def _search_names(self, query) -> set[str]:
        results = await self._search(query)
        return {r.name if hasattr(r, "name") else r.get("name", "") for r in results}

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — exact equality
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_eq_str(self):
        names = await self._search_names({"name": "Alice"})
        self.assertEqual(names, {"Alice"})

    async def test_eq_str_no_match(self):
        count = await self._search_count({"name": "Nobody"})
        self.assertEqual(count, 0)

    async def test_eq_float(self):
        names = await self._search_names({"score": 95.5})
        self.assertEqual(names, {"Alice"})

    async def test_eq_float_zero(self):
        names = await self._search_names({"score": 0.0})
        self.assertEqual(names, {"Diana"})

    async def test_eq_int(self):
        names = await self._search_names({"priority": 5})
        self.assertEqual(names, {"Bob"})

    async def test_eq_bool_true(self):
        names = await self._search_names({"active": True})
        self.assertIn("Alice", names)
        self.assertIn("Eve", names)

    async def test_eq_bool_false(self):
        names = await self._search_names({"active": False})
        self.assertIn("Bob", names)
        self.assertIn("Diana", names)

    # ── int / float cross-type equality ───────────────────────────────────────
    async def test_eq_int_as_float(self):
        """Query int field with float value: priority == 5.0"""
        names = await self._search_names({"priority": 5.0})
        self.assertIn("Bob", names)

    async def test_eq_float_as_int(self):
        """Query float field with int value: score == 0 (should match 0.0)"""
        names = await self._search_names({"score": 0})
        self.assertIn("Diana", names)

    # ── str Enum ──────────────────────────────────────────────────────────────
    async def test_eq_str_enum_value(self):
        names = await self._search_names({"color": Color.RED})
        self.assertEqual(names, {"Alice", "Diana"})

    async def test_eq_int_enum_value(self):
        names = await self._search_names({"priority": Priority.HIGH})
        self.assertEqual(names, {"Alice", "Charlie", "Eve"})

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — comparison operators ($gt, $gte, $lt, $lte)
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_gt_float(self):
        names = await self._search_names({"score": {"$gt": 90.0}})
        self.assertIn("Alice", names)
        self.assertIn("Eve", names)
        self.assertNotIn("Bob", names)

    async def test_gte_float(self):
        names = await self._search_names({"score": {"$gte": 88.8}})
        self.assertIn("Charlie", names)
        self.assertIn("Alice", names)
        self.assertIn("Eve", names)

    async def test_lt_int(self):
        names = await self._search_names({"priority": {"$lt": 5}})
        self.assertIn("Diana", names)
        self.assertNotIn("Bob", names)

    async def test_lte_int(self):
        names = await self._search_names({"priority": {"$lte": 5}})
        self.assertIn("Diana", names)
        self.assertIn("Bob", names)
        self.assertNotIn("Alice", names)

    async def test_gt_str_datetime(self):
        """Comparison on ISO datetime string field.
        Redis doesn't support range queries on string (TEXT/TAG) fields."""
        if self._backend_name == "redis":
            self.skipTest("Redis cannot do range queries on string fields")
        names = await self._search_names({"created": {"$gt": "2025-05-01T00:00:00"}})
        self.assertIn("Alice", names)
        self.assertIn("Eve", names)
        self.assertNotIn("Bob", names)

    async def test_lt_str_datetime(self):
        if self._backend_name == "redis":
            self.skipTest("Redis cannot do range queries on string fields")
        names = await self._search_names({"created": {"$lt": "2025-02-01T00:00:00"}})
        self.assertIn("Charlie", names)
        self.assertIn("Diana", names)

    # ── Enum in comparison ────────────────────────────────────────────────────
    async def test_gte_int_enum(self):
        names = await self._search_names({"priority": {"$gte": Priority.MEDIUM}})
        self.assertIn("Bob", names)
        self.assertIn("Alice", names)
        self.assertNotIn("Diana", names)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — $ne
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_ne_str(self):
        names = await self._search_names({"color": {"$ne": "red"}})
        self.assertNotIn("Alice", names)
        self.assertNotIn("Diana", names)
        self.assertIn("Bob", names)
        self.assertIn("Charlie", names)

    async def test_ne_enum(self):
        names = await self._search_names({"color": {"$ne": Color.RED}})
        self.assertNotIn("Alice", names)
        self.assertIn("Bob", names)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — $in
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_in_str(self):
        names = await self._search_names({"name": {"$in": ["Alice", "Eve"]}})
        self.assertEqual(names, {"Alice", "Eve"})

    async def test_in_int(self):
        names = await self._search_names({"priority": {"$in": [1, 5]}})
        self.assertEqual(names, {"Diana", "Bob"})

    async def test_in_enum(self):
        names = await self._search_names({"color": {"$in": [Color.RED, Color.BLUE]}})
        self.assertEqual(names, {"Alice", "Diana", "Charlie"})

    async def test_in_mixed_int_float(self):
        names = await self._search_names({"priority": {"$in": [1.0, 5.0]}})
        self.assertIn("Diana", names)
        self.assertIn("Bob", names)

    async def test_in_empty_list(self):
        if self._backend_name == "redis":
            self.skipTest("Redis empty $in uses nonexistent __never__ field (known limitation)")
        count = await self._search_count({"name": {"$in": []}})
        self.assertEqual(count, 0)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — $contains (substring search)
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_contains_str_substring(self):
        names = await self._search_names({"note": {"$contains": "math"}})
        self.assertIn("Charlie", names)

    async def test_contains_str_full_word(self):
        """Contains a lowercase full-word that appears in note.
        Redis indexes tokens as lowercase; SQLite instr is case-sensitive;
        so we use an all-lowercase word that exists verbatim in the data."""
        names = await self._search_names({"note": {"$contains": "student"}})
        self.assertIn("Alice", names)  # note = "Top student"

    async def test_contains_no_match(self):
        count = await self._search_count({"note": {"$contains": "zzzzzzzzz"}})
        self.assertEqual(count, 0)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — $wildcard (LIKE pattern)
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_wildcard_prefix(self):
        """Wildcard prefix on note field — 'top*' lowercase for cross-backend.
        SQL matches full string, Redis matches per-token."""
        names = await self._search_names({"note": {"$wildcard": "top*"}})
        self.assertIn("Alice", names)
        self.assertNotIn("Bob", names)

    async def test_wildcard_suffix(self):
        names = await self._search_names({"note": {"$wildcard": "*score"}})
        self.assertIn("Eve", names)  # note = "Perfect score"

    async def test_wildcard_question_mark(self):
        """Single-char wildcard on name field: Bo? matches Bob (3 chars).
        Redis tokens are lowercase, so use lowercase."""
        if self._backend_name == "redis":
            # Redis token "bob" matches "bo?" but name field uses tag for eq.
            # Wildcard goes through TEXT index which lowercases tokens.
            names = await self._search_names({"name": {"$wildcard": "bo?"}})
        else:
            names = await self._search_names({"name": {"$wildcard": "Bo?"}})
        self.assertIn("Bob", names)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — $regex
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_regex_prefix(self):
        """Regex prefix on note field — lowercase for Redis compatibility.
        PG ~* is case-insensitive, SQLite regexp uses re.IGNORECASE."""
        names = await self._search_names({"note": {"$regex": "^perfect.*"}})
        self.assertIn("Eve", names)

    async def test_regex_contains(self):
        names = await self._search_names({"note": {"$regex": "math"}})
        self.assertIn("Charlie", names)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — compound expressions ($and, $or)
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_and_implicit(self):
        """Multiple keys in one dict → implicit AND."""
        names = await self._search_names({"color": "red", "active": True})
        self.assertEqual(names, {"Alice"})

    async def test_and_explicit(self):
        names = await self._search_names({
            "$and": [
                {"priority": {"$gte": 10}},
                {"score": {"$gte": 90}},
            ]
        })
        self.assertTrue(names.issubset({"Alice", "Eve"}))
        self.assertTrue(len(names) >= 2)

    async def test_or_explicit(self):
        names = await self._search_names({
            "$or": [
                {"name": "Alice"},
                {"name": "Bob"},
            ]
        })
        self.assertEqual(names, {"Alice", "Bob"})

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — edge cases / garbage values
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_eq_empty_string(self):
        """Redis can't query empty tag value (syntax error); skip for Redis."""
        if self._backend_name == "redis":
            self.skipTest("Redis cannot query empty string via tag (known limitation)")
        names = await self._search_names({"note": ""})
        self.assertIn("Diana", names)

    async def test_eq_very_long_string(self):
        count = await self._search_count({"name": "x" * 1000})
        self.assertEqual(count, 0)

    async def test_eq_numeric_string_on_str_field(self):
        """Query a str field with number-like value — should return 0 matches."""
        count = await self._search_count({"name": "12345"})
        self.assertEqual(count, 0)

    async def test_gt_with_zero(self):
        names = await self._search_names({"score": {"$gt": 0}})
        self.assertNotIn("Diana", names)
        self.assertTrue(len(names) >= 3)

    async def test_eq_float_precision(self):
        """88.8 exactly."""
        names = await self._search_names({"score": 88.8})
        self.assertIn("Charlie", names)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — query by id
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_get_by_id(self):
        """Retrieve the first seeded object by ID."""
        obj = await self._client.get(self._model_cls, self._seed_ids[0])
        self.assertIsNotNone(obj)
        self.assertEqual(obj.name, "Alice")

    async def test_get_nonexistent_id(self):
        obj = await self._client.get(self._model_cls, "nonexistent_id_12345")
        self.assertIsNone(obj)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tests — performance: query should return quickly (< 2s for 5 docs)
    # ═══════════════════════════════════════════════════════════════════════════
    async def test_perf_eq(self):
        start = time.perf_counter()
        await self._search({"name": "Alice"})
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0, f"eq query took {elapsed:.3f}s")

    async def test_perf_gt(self):
        start = time.perf_counter()
        await self._search({"score": {"$gt": 50}})
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0, f"gt query took {elapsed:.3f}s")

    async def test_perf_contains(self):
        start = time.perf_counter()
        await self._search({"note": {"$contains": "math"}})
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0, f"contains query took {elapsed:.3f}s")

    async def test_perf_regex(self):
        start = time.perf_counter()
        await self._search({"note": {"$regex": "math"}})
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0, f"regex query took {elapsed:.3f}s")

    async def test_perf_in_large(self):
        start = time.perf_counter()
        await self._search({"name": {"$in": [f"name_{i}" for i in range(500)]}})
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 3.0, f"$in(500) query took {elapsed:.3f}s")


# ═══════════════════════════════════════════════════════════════════════════════
# Concrete backend test classes
# ═══════════════════════════════════════════════════════════════════════════════
class TestSQLite(_BackendTestBase):
    __test__ = True
    _backend_name = "sqlite"

    @classmethod
    def _make_client(cls):
        return _sqlite_client()


class TestPostgreSQL(_BackendTestBase):
    __test__ = True
    _backend_name = "postgresql"

    @classmethod
    def _make_client(cls):
        return _pg_client()


class TestMySQL(_BackendTestBase):
    __test__ = True
    _backend_name = "mysql"

    @classmethod
    def _make_client(cls):
        return _mysql_client()


class TestMongoDB(_BackendTestBase):
    __test__ = True
    _backend_name = "mongo"

    @classmethod
    def _make_client(cls):
        return _mongo_client()


class TestRedis(_BackendTestBase):
    __test__ = True
    _backend_name = "redis"

    @classmethod
    def _make_client(cls):
        return _redis_client()


if __name__ == "__main__":
    unittest.main()
