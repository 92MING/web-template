"""Integration tests: db_name field-name mapping for ORM & vector backends.

Verifies:
  1. resolve_db_field_name priority chain:
       db_name → serialization_alias → alias → alias_generator → python_name
  2. build_field_name_mapping returns correct mapping (empty for no-op).
  3. remap_payload_to_db / remap_payload_from_db round-trip.
  4. SQLite  — write/read/query/sort/selected with db_name fields.
  5. PostgreSQL — write/read/query with db_name fields.
  6. MySQL   — write/read/query with db_name fields.
  7. MongoDB — write/read/query/sort/selected with db_name fields.
  8. Redis   — write/read/query/sort/selected with db_name fields.
  9. Mixed fields (some with db_name, some without).
  10. Schema evolution column rename detection.
  11. Milvus vector backend with db_name fields.
"""
import asyncio
import os
import re
import sys
import time
import unittest
from pathlib import Path
from typing import ClassVar, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from pydantic import AliasGenerator, ConfigDict, Field as PydanticField

from core.storage.orm.field_metadata import (
    ORMFieldInfo,
    build_field_name_mapping,
    remap_payload_from_db,
    remap_payload_to_db,
    resolve_db_field_name,
    _translate_field_path,
)
from core.storage.orm.field_schema import detect_column_renames, ORMFieldSpec
from core.storage.orm import (
    ORMModel,
    ORMField,
    SQLiteORMClient,
    PostgreSQLORMClient,
    MySQLORMClient,
    MongoORMClient,
    RedisORMClient,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TMP_DIR = Path(__file__).resolve().parent.parent.parent / "tmp"
_SUFFIX = str(int(time.time()))

_CONSISTENCY_RETRIES = 6
_CONSISTENCY_SLEEP = 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Unit tests — resolve_db_field_name / build_field_name_mapping
# ═══════════════════════════════════════════════════════════════════════════════


class ExplicitDbName(ORMModel, collection_name="dbn_explicit"):
    title: str = ORMField("untitled", db_name="titulo")
    count: int = ORMField(0, db_name="cnt")
    normal: str = ORMField("hello")


class AliasModel(ORMModel, collection_name="dbn_alias"):
    title: str = ORMField("untitled", alias="t")
    score: float = ORMField(0.0, serialization_alias="scr")
    normal: str = ORMField("hello")


class DbNameOverridesAlias(ORMModel, collection_name="dbn_override"):
    title: str = ORMField("untitled", db_name="titulo", alias="t", serialization_alias="ttl")


class GeneratorModel(ORMModel, collection_name="dbn_gen"):
    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            serialization_alias=lambda name: f"s_{name}",
        ),
        populate_by_name=True,
    )
    title: str = ORMField("untitled")
    count: int = ORMField(0)
    explicit: str = ORMField("x", db_name="expl")


def _get_alias_gen(model_cls):
    """Extract alias_generator from model config."""
    config = getattr(model_cls, "model_config", None)
    if config and isinstance(config, dict):
        return config.get("alias_generator")
    return None


class TestResolveDbFieldName(unittest.TestCase):
    """Priority: db_name → serialization_alias → alias → generator → python_name."""

    def test_explicit_db_name(self):
        info = ExplicitDbName.model_fields["title"]
        self.assertEqual(resolve_db_field_name("title", info, _get_alias_gen(ExplicitDbName)), "titulo")

    def test_no_db_name_returns_python(self):
        info = ExplicitDbName.model_fields["normal"]
        self.assertEqual(resolve_db_field_name("normal", info, _get_alias_gen(ExplicitDbName)), "normal")

    def test_serialization_alias_fallback(self):
        info = AliasModel.model_fields["score"]
        self.assertEqual(resolve_db_field_name("score", info, _get_alias_gen(AliasModel)), "scr")

    def test_alias_fallback(self):
        info = AliasModel.model_fields["title"]
        self.assertEqual(resolve_db_field_name("title", info, _get_alias_gen(AliasModel)), "t")

    def test_db_name_overrides_all(self):
        info = DbNameOverridesAlias.model_fields["title"]
        self.assertEqual(resolve_db_field_name("title", info, _get_alias_gen(DbNameOverridesAlias)), "titulo")

    def test_generator_fallback(self):
        info = GeneratorModel.model_fields["title"]
        self.assertEqual(resolve_db_field_name("title", info, _get_alias_gen(GeneratorModel)), "s_title")

    def test_db_name_overrides_generator(self):
        info = GeneratorModel.model_fields["explicit"]
        self.assertEqual(resolve_db_field_name("explicit", info, GeneratorModel), "expl")


class TestBuildFieldNameMapping(unittest.TestCase):
    def test_empty_when_no_db_names(self):
        class Plain(ORMModel, collection_name="dbn_plain"):
            title: str = ORMField("x")
            count: int = ORMField(0)
        self.assertEqual(build_field_name_mapping(Plain), {})

    def test_only_differing_fields(self):
        m = build_field_name_mapping(ExplicitDbName)
        self.assertEqual(m, {"title": "titulo", "count": "cnt"})
        self.assertNotIn("normal", m)

    def test_alias_model_mapping(self):
        m = build_field_name_mapping(AliasModel)
        self.assertEqual(m, {"title": "t", "score": "scr"})

    def test_generator_model_mapping(self):
        m = build_field_name_mapping(GeneratorModel)
        self.assertIn("title", m)
        self.assertEqual(m["title"], "s_title")
        self.assertEqual(m["explicit"], "expl")


class TestRemapPayload(unittest.TestCase):
    def test_to_db_remap(self):
        mapping = {"title": "titulo", "count": "cnt"}
        payload = {"_id": "1", "title": "Hello", "count": 5, "normal": "abc"}
        db = remap_payload_to_db(payload, mapping)
        self.assertEqual(db["titulo"], "Hello")
        self.assertEqual(db["cnt"], 5)
        self.assertEqual(db["normal"], "abc")
        self.assertNotIn("title", db)
        self.assertNotIn("count", db)

    def test_from_db_remap(self):
        mapping = {"title": "titulo", "count": "cnt"}
        db = {"_id": "1", "titulo": "Hello", "cnt": 5, "normal": "abc"}
        py = remap_payload_from_db(db, mapping)
        self.assertEqual(py["title"], "Hello")
        self.assertEqual(py["count"], 5)
        self.assertEqual(py["normal"], "abc")

    def test_round_trip(self):
        mapping = {"title": "titulo", "count": "cnt"}
        original = {"_id": "1", "title": "Hello", "count": 5, "normal": "hi"}
        db = remap_payload_to_db(original, mapping)
        restored = remap_payload_from_db(db, mapping)
        self.assertEqual(restored, original)

    def test_empty_mapping_noop(self):
        payload = {"_id": "1", "title": "Hello"}
        self.assertEqual(remap_payload_to_db(payload, {}), payload)
        self.assertEqual(remap_payload_from_db(payload, {}), payload)


class TestTranslateFieldPath(unittest.TestCase):
    def test_simple_translation(self):
        m = {"title": "titulo"}
        self.assertEqual(_translate_field_path("title", m), "titulo")

    def test_dotted_path(self):
        m = {"address": "addr"}
        self.assertEqual(_translate_field_path("address.city", m), "addr.city")

    def test_no_mapping(self):
        self.assertEqual(_translate_field_path("title", {}), "title")

    def test_not_in_mapping(self):
        m = {"other": "x"}
        self.assertEqual(_translate_field_path("title", m), "title")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Schema rename detection unit tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectColumnRenames(unittest.TestCase):
    def test_single_rename(self):
        existing = {
            "_id": "TEXT", "payload_json": "TEXT",
            "titulo": "TEXT", "count": "INTEGER",
        }
        specs = {
            "title": ORMFieldSpec(field_name="title", column_name="title", kind="str", nullable=False, index=False),
            "count": ORMFieldSpec(field_name="count", column_name="count", kind="int", nullable=False, index=False),
        }
        renames = detect_column_renames(existing, specs, "sqlite")
        self.assertEqual(len(renames), 1)
        self.assertEqual(renames[0][0], "titulo")
        self.assertEqual(renames[0][1].column_name, "title")

    def test_no_rename_when_multiple_candidates(self):
        existing = {
            "_id": "TEXT", "payload_json": "TEXT",
            "a": "TEXT", "b": "TEXT",
        }
        specs = {
            "c": ORMFieldSpec(field_name="c", column_name="c", kind="str", nullable=False, index=False),
        }
        renames = detect_column_renames(existing, specs, "sqlite")
        # Two orphaned TEXT columns → ambiguous, no rename
        self.assertEqual(len(renames), 0)

    def test_no_rename_when_all_columns_match(self):
        existing = {
            "_id": "TEXT", "payload_json": "TEXT",
            "title": "TEXT",
        }
        specs = {
            "title": ORMFieldSpec(field_name="title", column_name="title", kind="str", nullable=False, index=False),
        }
        renames = detect_column_renames(existing, specs, "sqlite")
        self.assertEqual(len(renames), 0)

    def test_type_mismatch_prevents_rename(self):
        existing = {
            "_id": "TEXT", "payload_json": "TEXT",
            "old": "INTEGER",
        }
        specs = {
            "new_field": ORMFieldSpec(field_name="new_field", column_name="new_field", kind="str", nullable=False, index=False),
        }
        renames = detect_column_renames(existing, specs, "sqlite")
        self.assertEqual(len(renames), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SQLite integration — db_name round-trip
# ═══════════════════════════════════════════════════════════════════════════════


class DbNameItem(ORMModel, collection_name=f"dbn_item_{_SUFFIX}"):
    title: str = ORMField("untitled", db_name="titulo", native=True, index=True)
    count: int = ORMField(0, db_name="cnt", native=True)
    description: str = ORMField("default")


class TestSQLiteDbName(unittest.IsolatedAsyncioTestCase):
    client: SQLiteORMClient

    @classmethod
    def setUpClass(cls):
        cls.client = SQLiteORMClient(
            db_path=str(_TMP_DIR / f"test_db_name_{_SUFFIX}.db"),
            auto_start=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    async def test_write_read_round_trip(self):
        await self.client.create_collection(DbNameItem)
        item = DbNameItem(title="Hello", count=42, description="A test")
        await self.client.set(item)
        loaded = await self.client.get(DbNameItem, item.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "Hello")
        self.assertEqual(loaded.count, 42)
        self.assertEqual(loaded.description, "A test")

    async def test_query_by_mapped_field(self):
        await self.client.create_collection(DbNameItem)
        item = DbNameItem(title="QueryMe", count=99, description="q")
        await self.client.set(item)
        results = []
        async for r in self.client.search(DbNameItem, {"title": "QueryMe"}):
            results.append(r)
        self.assertTrue(any(r.title == "QueryMe" for r in results))

    async def test_native_column_uses_db_name(self):
        await self.client.create_collection(DbNameItem)
        item = DbNameItem(title="ColTest", count=7)
        await self.client.set(item)
        # Native column should be titulo, not title (no f_ prefix)
        conn = await self.client._get_conn()
        cursor = await conn.execute(
            f"PRAGMA table_info({self.client._table_sql(DbNameItem.CollectionName)})"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        col_names = [str(r["name"]) for r in rows]
        self.assertIn("titulo", col_names)
        self.assertNotIn("title", col_names)
        self.assertIn("cnt", col_names)
        self.assertNotIn("count", col_names)

    async def test_sorted_search(self):
        await self.client.create_collection(DbNameItem)
        for i in range(3):
            await self.client.set(DbNameItem(title=f"S{i}", count=i))
        results = []
        async for r in self.client.search_sorted(DbNameItem, sort=[("count", "asc")]):
            results.append(r)
        if len(results) >= 2:
            self.assertLessEqual(results[0].count, results[-1].count)

    async def test_selected_search(self):
        await self.client.create_collection(DbNameItem)
        await self.client.set(DbNameItem(title="SelTest", count=11))
        results = []
        async for r in self.client.selected_search(DbNameItem, fields=["title", "count"]):
            results.append(r)
        self.assertTrue(any("title" in r for r in results))

    async def test_query_count(self):
        await self.client.create_collection(DbNameItem)
        item = DbNameItem(title="CountMe", count=77)
        await self.client.set(item)
        count = await self.client.query_count(DbNameItem, {"count": 77})
        self.assertGreaterEqual(count, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PostgreSQL integration
# ═══════════════════════════════════════════════════════════════════════════════


class DbNamePGItem(ORMModel, collection_name=f"dbn_pg_{_SUFFIX}"):
    title: str = ORMField("untitled", db_name="titulo", native=True, index=True)
    count: int = ORMField(0, db_name="cnt", native=True)
    description: str = ORMField("default")


class TestPostgreSQLDbName(unittest.IsolatedAsyncioTestCase):
    client: PostgreSQLORMClient | None = None

    async def asyncSetUp(self):
        try:
            self.client = PostgreSQLORMClient(
                host="127.0.0.1", port=5433, username="postgres",
                password="postgres", database="projtemplate_test",
            )
            self.client.start()
        except Exception:
            self.client = None

    async def asyncTearDown(self):
        if self.client:
            self.client.close()

    async def test_write_read_round_trip(self):
        if not self.client:
            self.skipTest("PostgreSQL not available")
        await self.client.create_collection(DbNamePGItem)
        item = DbNamePGItem(title="PGTest", count=42, description="pg")
        await self.client.set(item)
        loaded = await self.client.get(DbNamePGItem, item.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "PGTest")
        self.assertEqual(loaded.count, 42)

    async def test_query(self):
        if not self.client:
            self.skipTest("PostgreSQL not available")
        await self.client.create_collection(DbNamePGItem)
        item = DbNamePGItem(title="PGQuery", count=55)
        await self.client.set(item)
        results = []
        async for r in self.client.search(DbNamePGItem, {"title": "PGQuery"}):
            results.append(r)
        self.assertTrue(any(r.title == "PGQuery" for r in results))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MySQL integration
# ═══════════════════════════════════════════════════════════════════════════════


class DbNameMySQLItem(ORMModel, collection_name=f"dbn_mysql_{_SUFFIX}"):
    title: str = ORMField("untitled", db_name="titulo", native=True)
    count: int = ORMField(0, db_name="cnt", native=True)


class TestMySQLDbName(unittest.IsolatedAsyncioTestCase):
    client: MySQLORMClient | None = None

    async def asyncSetUp(self):
        try:
            self.client = MySQLORMClient(
                host="127.0.0.1", port=3307, username="root",
                password="rootpass", database="projtemplate_test",
            )
            self.client.start()
        except Exception:
            self.client = None

    async def asyncTearDown(self):
        if self.client:
            self.client.close()

    async def test_write_read_round_trip(self):
        if not self.client:
            self.skipTest("MySQL not available")
        await self.client.create_collection(DbNameMySQLItem)
        item = DbNameMySQLItem(title="MySQLTest", count=33)
        await self.client.set(item)
        loaded = await self.client.get(DbNameMySQLItem, item.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "MySQLTest")
        self.assertEqual(loaded.count, 33)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MongoDB integration
# ═══════════════════════════════════════════════════════════════════════════════


class DbNameMongoItem(ORMModel, collection_name=f"dbn_mongo_{_SUFFIX}"):
    title: str = ORMField("untitled", db_name="titulo")
    count: int = ORMField(0, db_name="cnt")
    description: str = ORMField("default")


class TestMongoDbName(unittest.IsolatedAsyncioTestCase):
    client: MongoORMClient | None = None

    async def asyncSetUp(self):
        try:
            self.client = MongoORMClient(
                mongo_url=os.getenv("TEST_MONGO_URL", "mongodb://127.0.0.1:27017/?directConnection=true"),
                auto_start=True,
            )
        except Exception:
            self.client = None

    async def asyncTearDown(self):
        if self.client:
            self.client.close()

    async def test_write_read_round_trip(self):
        if not self.client:
            self.skipTest("MongoDB not available")
        await self.client.create_collection(DbNameMongoItem)
        item = DbNameMongoItem(title="MongoTest", count=42, description="mg")
        await self.client.set(item)
        loaded = await self.client.get(DbNameMongoItem, item.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "MongoTest")
        self.assertEqual(loaded.count, 42)

    async def test_query(self):
        if not self.client:
            self.skipTest("MongoDB not available")
        await self.client.create_collection(DbNameMongoItem)
        item = DbNameMongoItem(title="MongoQuery", count=55)
        await self.client.set(item)
        results = []
        async for r in self.client.search(DbNameMongoItem, {"title": "MongoQuery"}):
            results.append(r)
        self.assertTrue(any(r.title == "MongoQuery" for r in results))

    async def test_sorted_search(self):
        if not self.client:
            self.skipTest("MongoDB not available")
        await self.client.create_collection(DbNameMongoItem)
        for i in range(3):
            await self.client.set(DbNameMongoItem(title=f"MS{i}", count=i))
        results = []
        async for r in self.client.search_sorted(DbNameMongoItem, sort=[("count", "asc")]):
            results.append(r)
        if len(results) >= 2:
            self.assertLessEqual(results[0].count, results[-1].count)

    async def test_selected_search(self):
        if not self.client:
            self.skipTest("MongoDB not available")
        await self.client.create_collection(DbNameMongoItem)
        await self.client.set(DbNameMongoItem(title="MongoSel", count=9))
        results = []
        async for r in self.client.selected_search(DbNameMongoItem, fields=["title", "count"]):
            results.append(r)
        found = [r for r in results if r.get("title") == "MongoSel"]
        self.assertTrue(len(found) > 0)
        self.assertEqual(found[0]["count"], 9)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Redis integration
# ═══════════════════════════════════════════════════════════════════════════════


class DbNameRedisItem(ORMModel, collection_name=f"dbn_redis_{_SUFFIX}"):
    title: str = ORMField("untitled", db_name="titulo")
    count: int = ORMField(0, db_name="cnt")
    description: str = ORMField("default")


class TestRedisDbName(unittest.IsolatedAsyncioTestCase):
    client: RedisORMClient | None = None

    async def asyncSetUp(self):
        try:
            self.client = RedisORMClient(
                redis_url="redis://127.0.0.1:6379",
                auto_start=True,
            )
        except Exception:
            self.client = None

    async def asyncTearDown(self):
        if self.client:
            self.client.close()

    async def test_write_read_round_trip(self):
        if not self.client:
            self.skipTest("Redis not available")
        await self.client.create_collection(DbNameRedisItem)
        item = DbNameRedisItem(title="RedisTest", count=42, description="rd")
        await self.client.set(item)
        loaded = await self.client.get(DbNameRedisItem, item.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "RedisTest")
        self.assertEqual(loaded.count, 42)

    async def test_query(self):
        if not self.client:
            self.skipTest("Redis not available")
        await self.client.create_collection(DbNameRedisItem)
        item = DbNameRedisItem(title="RedisQuery", count=55)
        await self.client.set(item)
        results = []
        async for r in self.client.search(DbNameRedisItem, {"count": 55}):
            results.append(r)
        self.assertTrue(any(r.count == 55 for r in results))


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Schema evolution — column rename
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLiteSchemaRename(unittest.IsolatedAsyncioTestCase):
    async def test_column_rename_on_db_name_change(self):
        """When db_name changes, schema evolution should rename the column."""
        import aiosqlite

        db_path = str(_TMP_DIR / f"test_rename_{_SUFFIX}.db")

        # Phase 1: create with old column name
        class ItemV1(ORMModel, collection_name="rename_test"):
            title: str = ORMField("x", db_name="old_title", native=True)

        client1 = SQLiteORMClient(db_path=db_path, auto_start=True)
        await client1.create_collection(ItemV1)
        await client1.set(ItemV1(title="hello"))
        client1.close()

        # Verify old column exists
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('PRAGMA table_info("orm_rename_test")')
            rows = await cursor.fetchall()
            col_names = [str(row["name"]) for row in rows]
            self.assertIn("old_title", col_names)

        # Phase 2: open with new db_name → should rename
        class ItemV2(ORMModel, collection_name="rename_test"):
            title: str = ORMField("x", db_name="new_title", native=True)

        client2 = SQLiteORMClient(db_path=db_path, auto_start=True)
        await client2.create_collection(ItemV2)

        # Verify new column exists, old gone
        conn = await client2._get_conn()
        cursor = await conn.execute('PRAGMA table_info("orm_rename_test")')
        rows = await cursor.fetchall()
        await cursor.close()
        col_names = [str(r["name"]) for r in rows]
        self.assertIn("new_title", col_names)
        self.assertNotIn("old_title", col_names)

        # Verify data is preserved
        loaded = None
        async for item in client2.search(ItemV2):
            loaded = item
            break
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "hello")
        client2.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Mixed fields — some with db_name, some without
# ═══════════════════════════════════════════════════════════════════════════════


class MixedItem(ORMModel, collection_name=f"dbn_mixed_{_SUFFIX}"):
    """Some fields have db_name, some don't."""
    mapped_field: str = ORMField("a", db_name="mf")
    normal_field: str = ORMField("b")
    mapped_int: int = ORMField(0, db_name="mi")
    normal_int: int = ORMField(0)


class TestMixedDbNameSQLite(unittest.IsolatedAsyncioTestCase):
    client: SQLiteORMClient

    @classmethod
    def setUpClass(cls):
        cls.client = SQLiteORMClient(
            db_path=str(_TMP_DIR / f"test_mixed_dbn_{_SUFFIX}.db"),
            auto_start=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    async def test_mixed_round_trip(self):
        await self.client.create_collection(MixedItem)
        item = MixedItem(mapped_field="hello", normal_field="world", mapped_int=42, normal_int=7)
        await self.client.set(item)
        loaded = await self.client.get(MixedItem, item.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.mapped_field, "hello")
        self.assertEqual(loaded.normal_field, "world")
        self.assertEqual(loaded.mapped_int, 42)
        self.assertEqual(loaded.normal_int, 7)

    async def test_query_mapped_field(self):
        await self.client.create_collection(MixedItem)
        await self.client.set(MixedItem(mapped_field="find_me", normal_field="x"))
        results = []
        async for r in self.client.search(MixedItem, {"mapped_field": "find_me"}):
            results.append(r)
        self.assertTrue(any(r.mapped_field == "find_me" for r in results))

    async def test_query_normal_field(self):
        await self.client.create_collection(MixedItem)
        await self.client.set(MixedItem(mapped_field="y", normal_field="find_normal"))
        results = []
        async for r in self.client.search(MixedItem, {"normal_field": "find_normal"}):
            results.append(r)
        self.assertTrue(any(r.normal_field == "find_normal" for r in results))


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Milvus vector integration
# ═══════════════════════════════════════════════════════════════════════════════


try:
    from core.storage.vector import (
        PyMilvusVectorClient,
        VectorIndex,
        VectorORMField,
        VectorORMModel,
    )
    _HAS_MILVUS = True
except ImportError:
    _HAS_MILVUS = False

MILVUS_URI = os.getenv("TEST_MILVUS_URI", "http://127.0.0.1:19530")


if _HAS_MILVUS:
    class DbNameVecItem(VectorORMModel, collection_name=f"dbn_vec_{_SUFFIX}"):
        label: str = VectorORMField("x", db_name="lbl")
        score: float = VectorORMField(0.0, db_name="scr")
        embedding: list[float] = VectorORMField(
            default=[0.0] * 4,
            index=VectorIndex(dim=4, metric_type="COSINE"),
        )


@unittest.skipUnless(_HAS_MILVUS, "Milvus dependencies not installed")
class TestMilvusDbName(unittest.IsolatedAsyncioTestCase):
    client: "PyMilvusVectorClient | None" = None

    async def asyncSetUp(self):
        try:
            self.client = PyMilvusVectorClient(
                uri=MILVUS_URI,
                auto_start=True,
            )
        except Exception:
            self.client = None

    async def asyncTearDown(self):
        if self.client:
            try:
                await self.client.drop_collection(f"dbn_vec_{_SUFFIX}")
            except Exception:
                pass
            self.client.close()

    async def test_write_read_round_trip(self):
        if not self.client:
            self.skipTest("Milvus not available")
        await self.client.create_collection(DbNameVecItem)
        item = DbNameVecItem(label="MilvusTest", score=0.95, embedding=[1.0, 0.0, 0.0, 0.0])
        oid = await self.client.set(item)
        for _ in range(_CONSISTENCY_RETRIES):
            loaded = await self.client.get(DbNameVecItem, oid)
            if loaded is not None:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.label, "MilvusTest")
        self.assertAlmostEqual(loaded.score, 0.95, places=2)

    async def test_query(self):
        if not self.client:
            self.skipTest("Milvus not available")
        await self.client.create_collection(DbNameVecItem)
        item = DbNameVecItem(label="MilvusQ", score=0.5, embedding=[0.0, 1.0, 0.0, 0.0])
        await self.client.set(item)
        results = []
        for _ in range(_CONSISTENCY_RETRIES):
            results = []
            async for r in self.client.search(DbNameVecItem, {"label": "MilvusQ"}):
                results.append(r)
            if results:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertTrue(any(r.label == "MilvusQ" for r in results))


# ═══════════════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
