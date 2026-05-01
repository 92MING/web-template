"""Tests for ORMModel.update() and Field(exclude=True) storage exclusion."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.storage.orm.field_metadata import (
    _is_storage_excluded,
    build_field_name_mapping,
    ORMField,
)
from core.storage.orm.field_schema import extract_field_specs
from core.storage.orm import (
    ORMModel,
    SQLiteORMClient,
)

_TMP_DIR = Path(tempfile.gettempdir()) / "proj_test_update_exclude"
_TMP_DIR.mkdir(parents=True, exist_ok=True)
_SUFFIX = uuid.uuid4().hex[:8]


# ═══════════════════════════════════════════════════════════════════════════════
# Test models
# ═══════════════════════════════════════════════════════════════════════════════

from pydantic import Field


class SimpleItem(ORMModel, collection_name=f"upd_simple_{_SUFFIX}"):
    title: str = ORMField("untitled")
    count: int = ORMField(0)
    description: str = ORMField("default")


class ExcludedFieldItem(ORMModel, collection_name=f"upd_excl_{_SUFFIX}"):
    """Model with some fields marked exclude=True."""
    title: str = ORMField("untitled", native=True, index=True)
    count: int = ORMField(0, native=True)
    cached_html: str = Field(default="", exclude=True)
    temp_data: dict = Field(default_factory=dict, exclude=True)


class ExcludedDbNameItem(ORMModel, collection_name=f"upd_exdbn_{_SUFFIX}"):
    """exclude=True field should not get db_name mapping."""
    title: str = ORMField("untitled", db_name="titulo")
    hidden: str = Field(default="secret", exclude=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _is_storage_excluded unit tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsStorageExcluded(unittest.TestCase):
    def test_normal_field_not_excluded(self):
        info = SimpleItem.model_fields["title"]
        self.assertFalse(_is_storage_excluded(info))

    def test_exclude_true_is_excluded(self):
        info = ExcludedFieldItem.model_fields["cached_html"]
        self.assertTrue(_is_storage_excluded(info))

    def test_exclude_true_dict_field(self):
        info = ExcludedFieldItem.model_fields["temp_data"]
        self.assertTrue(_is_storage_excluded(info))

    def test_non_excluded_orm_field(self):
        info = ExcludedFieldItem.model_fields["title"]
        self.assertFalse(_is_storage_excluded(info))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. extract_field_specs skips excluded fields
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractFieldSpecsExclude(unittest.TestCase):
    def test_excluded_field_not_in_specs(self):
        specs = extract_field_specs(ExcludedFieldItem)
        # title, count should be in specs; cached_html, temp_data should NOT
        self.assertIn("title", specs)
        self.assertIn("count", specs)
        self.assertNotIn("cached_html", specs)
        self.assertNotIn("temp_data", specs)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. build_field_name_mapping skips excluded fields
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildFieldNameMappingExclude(unittest.TestCase):
    def test_excluded_field_not_in_mapping(self):
        mapping = build_field_name_mapping(ExcludedDbNameItem)
        self.assertIn("title", mapping)
        self.assertEqual(mapping["title"], "titulo")
        self.assertNotIn("hidden", mapping)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. model_dump naturally excludes excluded fields
# ═══════════════════════════════════════════════════════════════════════════════


class TestModelDumpExclude(unittest.TestCase):
    def test_excluded_fields_not_in_dump(self):
        item = ExcludedFieldItem(title="hello", count=5, cached_html="<b>hi</b>", temp_data={"a": 1})
        data = item.model_dump(mode="json")
        self.assertIn("title", data)
        self.assertIn("count", data)
        self.assertNotIn("cached_html", data)
        self.assertNotIn("temp_data", data)

    def test_serialize_for_storage_excludes(self):
        item = ExcludedFieldItem(title="hello", count=5, cached_html="<b>hi</b>")
        data = item._serialize_for_storage()
        self.assertNotIn("cached_html", data)
        self.assertNotIn("temp_data", data)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ORMModel.update() — SQLite integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdate(unittest.IsolatedAsyncioTestCase):
    client: SQLiteORMClient

    @classmethod
    def setUpClass(cls):
        cls.client = SQLiteORMClient(
            db_path=str(_TMP_DIR / f"test_update_{_SUFFIX}.db"),
            auto_start=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    async def test_update_all_fields(self):
        """update() with no args refreshes all fields from DB."""
        await self.client.create_collection(SimpleItem)
        item = SimpleItem(title="original", count=1, description="desc")
        await item.save(client=self.client)

        # Modify in DB directly via another instance
        item2 = await self.client.get(SimpleItem, item.id)
        item2.title = "modified"
        item2.count = 99
        await item2.save(client=self.client)

        # item still has old values
        self.assertEqual(item.title, "original")
        self.assertEqual(item.count, 1)

        # update() refreshes from DB
        await item.update(client=self.client)
        self.assertEqual(item.title, "modified")
        self.assertEqual(item.count, 99)

    async def test_update_specific_fields_by_name(self):
        """update('title') only refreshes the named field."""
        await self.client.create_collection(SimpleItem)
        item = SimpleItem(title="original", count=1, description="desc")
        await item.save(client=self.client)

        item2 = await self.client.get(SimpleItem, item.id)
        item2.title = "changed"
        item2.count = 42
        item2.description = "new_desc"
        await item2.save(client=self.client)

        await item.update("title", client=self.client)
        self.assertEqual(item.title, "changed")
        self.assertEqual(item.count, 1)  # NOT refreshed
        self.assertEqual(item.description, "desc")  # NOT refreshed

    async def test_update_specific_fields_by_proxy(self):
        """update(Model.field) accepts ORMFieldProxy."""
        await self.client.create_collection(SimpleItem)
        item = SimpleItem(title="original", count=1, description="desc")
        await item.save(client=self.client)

        item2 = await self.client.get(SimpleItem, item.id)
        item2.count = 77
        item2.title = "changed"
        await item2.save(client=self.client)

        await item.update(SimpleItem.count, client=self.client)
        self.assertEqual(item.count, 77)
        self.assertEqual(item.title, "original")  # NOT refreshed

    async def test_update_multiple_specific_fields(self):
        """update('title', 'count') refreshes multiple named fields."""
        await self.client.create_collection(SimpleItem)
        item = SimpleItem(title="original", count=1, description="old")
        await item.save(client=self.client)

        item2 = await self.client.get(SimpleItem, item.id)
        item2.title = "new_title"
        item2.count = 50
        item2.description = "new_desc"
        await item2.save(client=self.client)

        await item.update("title", "count", client=self.client)
        self.assertEqual(item.title, "new_title")
        self.assertEqual(item.count, 50)
        self.assertEqual(item.description, "old")  # NOT refreshed

    async def test_update_not_found_raises(self):
        """update() raises LookupError if the object is not in DB."""
        await self.client.create_collection(SimpleItem)
        item = SimpleItem(title="ghost", count=0)
        # Never saved, so won't be found
        with self.assertRaises(LookupError):
            await item.update(client=self.client)

    async def test_update_unknown_field_raises(self):
        """update('nonexistent') raises ValueError."""
        await self.client.create_collection(SimpleItem)
        item = SimpleItem(title="hello", count=1)
        await item.save(client=self.client)
        with self.assertRaises(ValueError):
            await item.update("nonexistent_field", client=self.client)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. update() skips excluded fields when refreshing all
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdateWithExcludedFields(unittest.IsolatedAsyncioTestCase):
    client: SQLiteORMClient

    @classmethod
    def setUpClass(cls):
        cls.client = SQLiteORMClient(
            db_path=str(_TMP_DIR / f"test_update_excl_{_SUFFIX}.db"),
            auto_start=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    async def test_update_all_preserves_excluded_field(self):
        """When update() refreshes all fields, excluded fields keep their local values."""
        await self.client.create_collection(ExcludedFieldItem)
        item = ExcludedFieldItem(title="original", count=1, cached_html="<b>local</b>")
        await item.save(client=self.client)

        # Modify in DB
        item2 = await self.client.get(ExcludedFieldItem, item.id)
        item2.title = "modified"
        await item2.save(client=self.client)

        # update() should refresh title, count — but NOT cached_html
        await item.update(client=self.client)
        self.assertEqual(item.title, "modified")
        self.assertEqual(item.cached_html, "<b>local</b>")  # preserved


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SQLite integration — excluded fields don't get native columns
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLiteExcludedNativeColumns(unittest.IsolatedAsyncioTestCase):
    async def test_no_native_column_for_excluded_field(self):
        """Fields with exclude=True should not get SQL native columns."""
        import aiosqlite

        db_path = str(_TMP_DIR / f"test_excl_col_{_SUFFIX}.db")
        client = SQLiteORMClient(db_path=db_path, auto_start=True)
        await client.create_collection(ExcludedFieldItem)

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(f'PRAGMA table_info("orm_{ExcludedFieldItem.CollectionName}")')
            rows = await cursor.fetchall()
            col_names = [str(row["name"]) for row in rows]

        # title and count should have native columns; cached_html and temp_data should NOT
        self.assertIn("title", col_names)
        self.assertIn("count", col_names)
        self.assertNotIn("cached_html", col_names)
        self.assertNotIn("temp_data", col_names)
        client.close()

    async def test_excluded_field_still_accessible_on_model(self):
        """Even though excluded from storage, the in-memory attribute works fine."""
        db_path = str(_TMP_DIR / f"test_excl_attr_{_SUFFIX}.db")
        client = SQLiteORMClient(db_path=db_path, auto_start=True)
        await client.create_collection(ExcludedFieldItem)

        item = ExcludedFieldItem(title="test", count=5, cached_html="<b>hi</b>")
        self.assertEqual(item.cached_html, "<b>hi</b>")

        await client.set(item)
        loaded = await client.get(ExcludedFieldItem, item.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "test")
        self.assertEqual(loaded.count, 5)
        # cached_html is not in storage — loaded instance gets default
        self.assertEqual(loaded.cached_html, "")
        client.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
