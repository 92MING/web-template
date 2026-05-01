import sqlite3
import os
import json
import shutil
import sys
import tempfile
import unittest
from asyncio import sleep
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
                    "prefix": "test",

from core.storage.config import (
    EtcdKVDBConfig,
    KV_StorageConfig,
    LocalObjectDBConfig,
    LocalKVDBConfig,
    MySQL_ORM_DB_Config,
    ObjectStorageConfig,
    ORMStorageConfig,
    SQLiteORMDBConfig,
    StorageConfig,
)
from pydantic import BaseModel

from core.storage.kv import KVClientBase, SQLiteKVClient
from core.storage.object import LocalObjectClient
from core.storage.base import ObjectId
from core.storage.orm import DefaultORMLogStore, ORMField, ORM_ClientBase, ORMModel, ORMSystemMetricsStore, SQL_ORM_Client, SQLiteORMClient, SystemMetricRecord
from core.storage.vector import AnnoySQLiteVectorClient, VectorClientBase, VectorIndex, VectorORMField, VectorORMModel


class StorageNote(ORMModel, collection_name="storage_notes"):
    title: str
    category: str = "general"
    tags: list[str] = []


class SimpleItem(BaseModel):
    """Plain pydantic model (no ORMModel extras) used for target_type tests."""
    name: str
    count: int = 0
    tags: list[str] = []


class NestedAddress(BaseModel):
    city: str
    room: int = 0


class NestedProfile(BaseModel):
    label: str
    address: NestedAddress


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _close_local_kv(client: object) -> None:
    """Close a LocalKVClient via its public shutdown path."""
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


async def _close_orm_client(client: object) -> None:
    """Close ORM clients and await async handle disposal when available."""
    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        try:
            await aclose()
            return
        except Exception:
            pass
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    local = getattr(client, "_local", None)
    conn = getattr(local, "conn", None)
    if conn is not None:
        conn.close()
        local.conn = None


def _close_object_client(client: LocalObjectClient) -> None:
    """Close a LocalObjectClient and its metadata KV store."""
    client.close()


# ---------------------------------------------------------------------------
# KV – basic
# ---------------------------------------------------------------------------

class TestLocalKVClientBasic(unittest.IsolatedAsyncioTestCase):
    """Basic set/get/expire/LRU tests for LocalKVClient."""

    async def test_set_get_expire_and_lru_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "kv.sqlite3"
            client = SQLiteKVClient(db_path=db_path, max_size=2, cleanup_interval=1)
            client.start()
            try:
                await client.set("alpha", {"x": 1})
                self.assertEqual(await client.get("alpha"), {"x": 1})

                await client.set_expire("alpha", 0.01)
                await sleep(0.03)
                self.assertIsNone(await client.get("alpha"))

                await client.set("k1", "a" * 256)
                await client.set("k2", "b" * 256)
                await client.set("k3", "c" * 256)
                await client.cleanup(force=True)

                remaining = [await client.get("k1"), await client.get("k2"), await client.get("k3")]
                self.assertTrue(any(item is None for item in remaining), "at least one evicted")
                self.assertTrue(any(item is not None for item in remaining), "at least one survives")
            finally:
                _close_local_kv(client)

    async def test_get_default_on_missing_key(self) -> None:
        """get returns default when key is absent."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                self.assertIsNone(await client.get("no_such_key"))
                self.assertEqual(await client.get("no_such_key", "fallback"), "fallback")
            finally:
                _close_local_kv(client)

    async def test_overwrite_existing_key(self) -> None:
        """Setting a key twice overwrites the previous value."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                await client.set("key", "first")
                await client.set("key", "second")
                self.assertEqual(await client.get("key"), "second")
            finally:
                _close_local_kv(client)

    async def test_delete_returns_bool(self) -> None:
        """delete returns True on success, False when key does not exist."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                await client.set("to_delete", 42)
                self.assertTrue(await client.delete("to_delete"))
                self.assertIsNone(await client.get("to_delete"))
                self.assertFalse(await client.delete("to_delete"))
                self.assertFalse(await client.delete("never_existed"))
            finally:
                _close_local_kv(client)


# ---------------------------------------------------------------------------
# KV – type serialization / deserialization
# ---------------------------------------------------------------------------

class TestLocalKVClientTypes(unittest.IsolatedAsyncioTestCase):
    """Tests for recursive_dump_to_basic_types, bytes passthrough, and target_type."""

    async def test_bytes_passthrough(self) -> None:
        """bytes values bypass recursive_dump_to_basic_types and are stored as-is."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                raw = b"\x00\x01\x02\x03\xff"
                await client.set("raw_bytes", raw)
                result = await client.get("raw_bytes")
                self.assertEqual(result, raw)
                self.assertIsInstance(result, bytes)
            finally:
                _close_local_kv(client)

    async def test_pydantic_model_serializes_to_dict(self) -> None:
        """Pydantic models are converted to plain dicts via recursive_dump_to_basic_types."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                note = StorageNote(title="pydantic test", tags=["x", "y"])
                await client.set("note", note)
                result = await client.get("note")
                # Should come back as a plain dict, not a pydantic model instance
                self.assertIsInstance(result, dict)
                self.assertEqual(result.get("title"), "pydantic test")
                self.assertEqual(result.get("tags"), ["x", "y"])
            finally:
                _close_local_kv(client)

    async def test_get_with_target_type(self) -> None:
        """get(target_type=T) deserializes the stored value back to the given type."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                item = SimpleItem(name="typed get", count=7, tags=["a"])
                await client.set("typed_item", item)

                # Without target_type: comes back as plain dict
                raw = await client.get("typed_item")
                self.assertIsInstance(raw, dict)

                # With target_type: deserialized to SimpleItem
                typed = await client.get("typed_item", target_type=SimpleItem)
                self.assertIsInstance(typed, SimpleItem)
                self.assertEqual(typed.name, "typed get")
                self.assertEqual(typed.count, 7)
                self.assertEqual(typed.tags, ["a"])
            finally:
                _close_local_kv(client)

    async def test_get_with_target_type_falls_back_on_failure(self) -> None:
        """get with target_type falls back to raw value when deserialization fails."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                # Store a plain string that is not valid StorageNote JSON
                await client.set("bad_note", "not-a-valid-model")
                result = await client.get("bad_note", target_type=StorageNote)
                # Must not raise; returns raw value instead
                self.assertEqual(result, "not-a-valid-model")
            finally:
                _close_local_kv(client)


# ---------------------------------------------------------------------------
# KV – keys & expire
# ---------------------------------------------------------------------------

class TestLocalKVClientKeysAndExpire(unittest.IsolatedAsyncioTestCase):

    async def test_keys_prefix_filter(self) -> None:
        """keys(prefix=…) returns only matching non-expired keys in sorted order."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                await client.set("app:config:1", "v1")
                await client.set("app:config:2", "v2")
                await client.set("app:other", "vo")
                await client.set("misc:thing", "vm")

                app_config = await client.keys(prefix="app:config:")
                self.assertEqual(app_config, ["app:config:1", "app:config:2"])

                all_app = await client.keys(prefix="app:")
                self.assertEqual(all_app, ["app:config:1", "app:config:2", "app:other"])

                all_keys = await client.keys()
                self.assertIn("misc:thing", all_keys)
                self.assertEqual(len(all_keys), 4)
            finally:
                _close_local_kv(client)

    async def test_expired_keys_excluded_from_keys(self) -> None:
        """keys() omits keys whose TTL has elapsed."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                await client.set("live", "yes")
                await client.set("dying", "soon", expire=0.01)
                await sleep(0.03)

                all_keys = await client.keys()
                self.assertIn("live", all_keys)
                self.assertNotIn("dying", all_keys)
            finally:
                _close_local_kv(client)

    async def test_set_expire_and_get_expire(self) -> None:
        """get_expire returns approximate TTL; expired values are evicted."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            client.start()
            try:
                # Permanent key → get_expire returns None
                await client.set("permanent", "forever")
                self.assertIsNone(await client.get_expire("permanent"))

                # Key with TTL
                await client.set("temp", "soon gone", expire=10)
                ttl = await client.get_expire("temp")
                self.assertIsNotNone(ttl)
                self.assertGreater(ttl, 0)
                self.assertLessEqual(ttl, 10)

                # set_expire extends TTL
                self.assertTrue(await client.set_expire("temp", 200))
                new_ttl = await client.get_expire("temp")
                self.assertGreater(new_ttl, 10)

                # set_expire on missing key → False
                self.assertFalse(await client.set_expire("ghost", 5))
            finally:
                _close_local_kv(client)


class TestLocalKVNamespaces(unittest.IsolatedAsyncioTestCase):

    async def test_open_namespace_returns_child_client_backed_by_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            child = parent.open_namespace("child")
            sibling = parent.open_namespace("sibling")
            try:
                self.assertIsInstance(child, SQLiteKVClient)
                self.assertIs(child._parent, parent)
                self.assertEqual(child._namespace, "default:child")

                await child.set("alpha", {"value": 1})

                self.assertEqual(await child.get("alpha"), {"value": 1})
                self.assertEqual(await parent.get("child:alpha"), {"value": 1})
                self.assertIsNone(await sibling.get("alpha"))
                self.assertEqual(await child.keys(), ["alpha"])
                self.assertIn("child:alpha", await parent.keys())

                self.assertTrue(await child.delete("alpha"))
                self.assertIsNone(await parent.get("child:alpha"))
            finally:
                _close_local_kv(child)
                _close_local_kv(sibling)
                _close_local_kv(parent)

    async def test_nested_namespace_start_and_close_delegate_to_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            child = parent.open_namespace("child")
            grandchild = child.open_namespace("nested")
            try:
                self.assertFalse(parent.started)
                self.assertFalse(child.started)
                self.assertFalse(grandchild.started)

                grandchild.start()

                self.assertTrue(parent.started)
                self.assertTrue(child.started)
                self.assertTrue(grandchild.started)

                await grandchild.set("beta", "value", expire=10)

                self.assertEqual(await parent.get("child:nested:beta"), "value")
                self.assertEqual(await child.keys(prefix="nested:"), ["nested:beta"])
                ttl = await grandchild.get_expire("beta")
                self.assertIsNotNone(ttl)
                self.assertGreater(ttl, 0)

                grandchild.close()

                self.assertTrue(parent.started)
                self.assertFalse(grandchild.started)
                self.assertEqual(await parent.get("child:nested:beta"), "value")
            finally:
                _close_local_kv(grandchild)
                _close_local_kv(child)
                _close_local_kv(parent)

    async def test_namespace_cleanup_delegates_to_parent_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = SQLiteKVClient(db_path=Path(tmp_dir) / "kv.sqlite3")
            child = parent.open_namespace("child")
            try:
                await child.set("soon", "gone", expire=0.01)
                await child.set("stay", "alive")

                await sleep(0.03)
                removed = await child.cleanup(force=True)

                self.assertGreaterEqual(removed, 1)
                self.assertIsNone(await child.get("soon"))
                self.assertEqual(await child.get("stay"), "alive")
            finally:
                _close_local_kv(child)
                _close_local_kv(parent)


# ---------------------------------------------------------------------------
# ORM
# ---------------------------------------------------------------------------

class TestStorageORM(unittest.IsolatedAsyncioTestCase):
    async def test_object_id_equals_string(self) -> None:
        oid = ObjectId()
        self.assertEqual(oid, str(oid))
        self.assertNotEqual(oid, str(ObjectId()))

    async def test_sqlite_orm_create_set_search_and_expire(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "orm.sqlite3"
            client = SQLiteORMClient(db_path=db_path, cleanup_interval=1)
            client.start()
            try:
                await client.create_collection(StorageNote)

                note = StorageNote(title="hello storage", category="demo", tags=["a", "b"])
                object_id = await client.set(note)
                self.assertEqual(object_id, note.id)
                self.assertEqual(note.model_dump(mode="json")["id"], str(note.id))

                got = await client.get(StorageNote, object_id)
                self.assertIsInstance(got, StorageNote)
                self.assertEqual(got.title, "hello storage")    # type: ignore

                found = [item async for item in client.search(StorageNote, {"category": "demo"})]
                self.assertEqual(len(found), 1)
                self.assertIsInstance(found[0], StorageNote)

                found_one = await client.search_one(StorageNote, {"title": "hello storage"})
                self.assertIsNotNone(found_one)
                self.assertEqual(found_one.id, object_id)

                raw_id = await client.set({"title": "dict item", "category": "dict"}, collection=StorageNote.CollectionName)
                self.assertIsInstance(raw_id, str)
                raw = await client.search_by_id(StorageNote.CollectionName, raw_id, as_model=False)
                self.assertEqual(raw["title"], "dict item")

                await client.set_expire(StorageNote.CollectionName, raw_id, 0.01)
                await sleep(0.03)
                self.assertIsNone(await client.get(StorageNote.CollectionName, raw_id))

                self.assertTrue(await client.delete(StorageNote.CollectionName, object_id))
                self.assertIsNone(await client.get(StorageNote.CollectionName, object_id))
            finally:
                await _close_orm_client(client)
                await sleep(0.05)

    async def test_sqlite_orm_raw_dict_requires_resolvable_model_for_string_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "orm.sqlite3"
            client = SQLiteORMClient(db_path=db_path, cleanup_interval=1)
            client.start()
            try:
                with self.assertRaisesRegex(ValueError, "does not map to a loaded ORMModel class"):
                    await client.set({"title": "orphan dict"}, collection="unknown_collection")
            finally:
                await _close_orm_client(client)
                await sleep(0.05)

    async def test_sqlite_orm_native_columns_wildcard_sort_and_schema_evolution(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        db_path = Path(tmp_dir) / "orm.sqlite3"
        client = SQLiteORMClient(db_path=db_path, cleanup_interval=999999)
        client.start()
        try:
            class IndexedNoteV1(ORMModel, collection_name="indexed_notes"):
                title: str = ORMField(default="", index=True, max_length=32)
                order: int = ORMField(default=0, index=True)
                active: bool = ORMField(default=False)

            await client.create_collection(IndexedNoteV1)
            await client.set(IndexedNoteV1(title="Alice", order=2, active=True))
            await client.set(IndexedNoteV1(title="Alfred", order=1, active=False))
            await client.set(IndexedNoteV1(title="Bob", order=3, active=True))

            with patch(
                "core.storage.orm.client_base._match_query_or_expr",
                side_effect=AssertionError("sqlite wildcard query should be pushed down to SQL"),
            ):
                wildcard_rows = [
                    item async for item in client.search(
                        IndexedNoteV1,
                        {"title": {"$wildcard": "Al*"}},
                        as_model=False,
                    )
                ]
            self.assertEqual({row["title"] for row in wildcard_rows}, {"Alice", "Alfred"})

            sorted_rows = [
                item async for item in client.search_sorted(
                    IndexedNoteV1,
                    sort=[("order", "asc")],
                    as_model=False,
                )
            ]
            self.assertEqual([row["order"] for row in sorted_rows], [1, 2, 3])

            class IndexedNoteV2(ORMModel, collection_name="indexed_notes"):
                title: str = ORMField(default="", index=True, max_length=128)
                order: int = ORMField(default=0, index=True)
                category: str = ORMField(default="", index=True)

            await client.create_collection(IndexedNoteV2)

            table = client._table_sql("indexed_notes")
            conn = sqlite3.connect(str(db_path))
            try:
                columns = {
                    str(row[1]): str(row[2] or "")
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                index_names = {
                    str(row[1])
                    for row in conn.execute(f"PRAGMA index_list({table})").fetchall()
                }
            finally:
                conn.close()

            self.assertIn("title", columns)
            self.assertIn("order", columns)
            self.assertIn("active", columns)
            self.assertIn("category", columns)
            # str fields with index use FTS5, not B-tree → no B-tree idx
            # Only int/numeric indexed fields get B-tree
            self.assertIn("idx_indexed_notes_order", index_names)
            # Verify FTS5 table exists for str fields
            fts_name = "_orm_indexed_notes_fts"
            conn2 = sqlite3.connect(str(db_path))
            try:
                fts_exists = conn2.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (fts_name,),
                ).fetchone()
            finally:
                conn2.close()
            self.assertIsNotNone(fts_exists, "FTS5 table should exist for indexed str fields")
        finally:
            aio_conn = getattr(client, "_aio_conn", None)
            client._aio_conn = None
            client._schema_ready = False
            client._mark_stopped()
            if aio_conn is not None:
                try:
                    await aio_conn.close()
                except Exception:
                    pass
            await _close_orm_client(client)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def test_sqlite_orm_rejects_non_pushdown_query_without_python_filter_fallback(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        db_path = Path(tmp_dir) / "orm.sqlite3"
        client = SQLiteORMClient(db_path=db_path, cleanup_interval=1)
        client.start()
        try:
            await client.create_collection(StorageNote)
            await client.set(StorageNote(title="hello storage", category="demo"))

            with patch(
                "core.storage.orm.client_base._match_query_or_expr",
                side_effect=AssertionError("sqlite search should not fall back to Python filtering"),
            ):
                with self.assertRaisesRegex(ValueError, "sqlite search requires a query that can be pushed down to SQL"):
                    _ = [
                        item async for item in client.search(
                            StorageNote,
                            {"title": {"$unsupported": "hello"}},
                            as_model=False,
                        )
                    ]

            with self.assertRaisesRegex(ValueError, "sqlite selected_search requires a query that can be pushed down to SQL"):
                _ = [
                    item async for item in client.selected_search(
                        StorageNote,
                        fields=("title",),
                        query={"title": {"$unsupported": "hello"}},
                    )
                ]
        finally:
            await _close_orm_client(client)
            await sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def test_sqlalchemy_orm_rejects_non_pushdown_query_without_python_filter_fallback(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        db_path = Path(tmp_dir) / "orm_sqlalchemy.sqlite3"
        client = SQL_ORM_Client(url=f"sqlite:///{db_path.as_posix()}", cleanup_interval=1)
        client.start()
        try:
            await client.create_collection(StorageNote)
            await client.set(StorageNote(title="hello storage", category="demo"))

            with patch(
                "core.storage.orm.client_base._match_query_or_expr",
                side_effect=AssertionError("sqlalchemy search should not fall back to Python filtering"),
            ):
                with self.assertRaisesRegex(ValueError, "sqlite search requires a query that can be pushed down to SQL"):
                    _ = [
                        item async for item in client.search(
                            StorageNote,
                            {"title": {"$unsupported": "hello"}},
                            as_model=False,
                        )
                    ]

            with self.assertRaisesRegex(ValueError, "sqlite selected_search requires a query that can be pushed down to SQL"):
                _ = [
                    item async for item in client.selected_search(
                        StorageNote,
                        fields=("title",),
                        query={"title": {"$unsupported": "hello"}},
                    )
                ]
        finally:
            await _close_orm_client(client)
            await sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def test_nested_model_field_proxy_and_object_comparison_on_sqlite_and_sqlalchemy(self) -> None:
        class NestedQueryNote(ORMModel, collection_name="nested_query_notes"):
            title: str
            profile: NestedProfile

        async def _exercise(client: ORM_ClientBase) -> None:
            await client.create_collection(NestedQueryNote)
            await client.set(
                NestedQueryNote(
                    title="alpha",
                    profile=NestedProfile(label="teacher", address=NestedAddress(city="Hong Kong", room=1203)),
                )
            )
            await client.set(
                NestedQueryNote(
                    title="beta",
                    profile=NestedProfile(label="student", address=NestedAddress(city="Kowloon", room=402)),
                )
            )

            by_nested_field = [
                item async for item in NestedQueryNote.Search(
                    NestedQueryNote.profile.address.city == "Hong Kong",
                    client=client,
                )
            ]
            self.assertEqual([item.title for item in by_nested_field], ["alpha"])

            by_model_object = await NestedQueryNote.SearchOne(
                NestedQueryNote.profile == NestedProfile(
                    label="teacher",
                    address=NestedAddress(city="Hong Kong", room=1203),
                ),
                client=client,
            )
            self.assertIsNotNone(by_model_object)
            self.assertEqual(by_model_object.title, "alpha")

            by_dict_object = await NestedQueryNote.SearchOne(
                NestedQueryNote.profile.address == {"city": "Kowloon", "room": 402},
                client=client,
            )
            self.assertIsNotNone(by_dict_object)
            self.assertEqual(by_dict_object.title, "beta")

            with patch(
                "core.storage.orm.client_base._match_query_or_expr",
                side_effect=AssertionError("nested query expressions should be pushed down, not filtered in Python"),
            ):
                pushed_down = [
                    item async for item in client.search(
                        NestedQueryNote,
                        NestedQueryNote.profile.label == "teacher",
                        as_model=False,
                    )
                ]
            self.assertEqual([item["title"] for item in pushed_down], ["alpha"])

        tmp_dir = tempfile.mkdtemp()
        sqlite_path = Path(tmp_dir) / "nested_sqlite.sqlite3"
        sqlalchemy_path = Path(tmp_dir) / "nested_sqlalchemy.sqlite3"
        sqlite_client = SQLiteORMClient(db_path=sqlite_path, cleanup_interval=1)
        sqlalchemy_client = SQL_ORM_Client(url=f"sqlite:///{sqlalchemy_path.as_posix()}", cleanup_interval=1)
        sqlite_client.start()
        sqlalchemy_client.start()
        try:
            await _exercise(sqlite_client)
            await _exercise(sqlalchemy_client)
        finally:
            await _close_orm_client(sqlite_client)
            await _close_orm_client(sqlalchemy_client)
            await sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def test_foreign_model_field_serializes_as_id_and_resolves_across_clients(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        default_db_path = Path(tmp_dir) / "foreign_parent.sqlite3"
        child_db_path = Path(tmp_dir) / "foreign_child.sqlite3"
        ORM_ClientBase.ClearDefaultInstances()
        config = StorageConfig(
            orm=ORMStorageConfig(
                default=SQLiteORMDBConfig(db_path=str(default_db_path), namespace="foreign-parent"),
                cache=SQLiteORMDBConfig(db_path=str(Path(tmp_dir) / "foreign_cache.sqlite3"), namespace="foreign-cache"),
            ),
            kv=KV_StorageConfig(
                default=LocalKVDBConfig(db_path=str(Path(tmp_dir) / "foreign_kv.sqlite3"), namespace="foreign-parent"),
            ),
            object=ObjectStorageConfig(
                default=LocalObjectDBConfig(
                    root_path=str(Path(tmp_dir) / "foreign_objects"),
                    metadata_db=LocalKVDBConfig(db_path=str(Path(tmp_dir) / "foreign_objects_meta.sqlite3"), namespace="foreign-parent:objects"),
                    namespace="foreign-parent",
                ),
            ),
        )
        StorageConfig.SetGlobal(config)
        default_client = ORM_ClientBase.Default()
        child_client = SQLiteORMClient(db_path=child_db_path, cleanup_interval=1)
        child_client.start()

        class ForeignChild(ORMModel, collection_name="foreign_child", client=child_client):
            title: str

        class ForeignParent(ORMModel, collection_name="foreign_parent"):
            title: str
            child: ForeignChild = ORMField(foreign_model=True)
            optional_child: ForeignChild | None = ORMField(default=None, foreign_model=True)

        try:
            child = ForeignChild(title="child from custom db")
            await child.save()

            parent = ForeignParent(
                title="parent",
                child=str(child.id),
                optional_child={"id": str(child.id)},
            )
            self.assertIsInstance(parent.child, ForeignChild)
            self.assertIsInstance(parent.optional_child, ForeignChild)
            self.assertEqual(parent.child.title, "child from custom db")
            self.assertEqual(parent.optional_child.title, "child from custom db")

            dumped = parent.model_dump(mode="json")
            self.assertEqual(dumped["child"], str(child.id))
            self.assertEqual(dumped["optional_child"], str(child.id))

            parent_id = await parent.save()
            raw_parent = await default_client.get(ForeignParent.CollectionName, parent_id, as_model=False)
            self.assertEqual(raw_parent["child"], str(child.id))
            self.assertEqual(raw_parent["optional_child"], str(child.id))

            fetched = await ForeignParent.SearchOneById(parent_id)
            self.assertIsNotNone(fetched)
            self.assertIsInstance(fetched.child, ForeignChild)
            self.assertIsInstance(fetched.optional_child, ForeignChild)
            self.assertEqual(fetched.child.id, child.id)
            self.assertEqual(fetched.optional_child.id, child.id)
        finally:
            await _close_orm_client(default_client)
            await _close_orm_client(child_client)
            ORM_ClientBase.ClearDefaultInstances()
            await sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def test_orm_model_async_helpers_and_bound_client(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        default_db_path = Path(tmp_dir) / "default.sqlite3"
        custom_db_path = Path(tmp_dir) / "custom.sqlite3"
        config = StorageConfig(
            orm=ORMStorageConfig(
                default=SQLiteORMDBConfig(db_path=str(default_db_path), namespace="default-model"),
                cache=SQLiteORMDBConfig(db_path=str(Path(tmp_dir) / "cache.sqlite3"), namespace="cache-model"),
            ),
            kv=KV_StorageConfig(
                default=LocalKVDBConfig(db_path=str(Path(tmp_dir) / "kv.sqlite3"), namespace="default-model"),
            ),
            object=ObjectStorageConfig(
                default=LocalObjectDBConfig(
                    root_path=str(Path(tmp_dir) / "objects"),
                    metadata_db=LocalKVDBConfig(db_path=str(Path(tmp_dir) / "objects_meta.sqlite3"), namespace="default-model:objects"),
                    namespace="default-model",
                ),
            ),
        )
        StorageConfig.SetGlobal(config)
        default_client = ORM_ClientBase.Default()
        custom_client = SQLiteORMClient(db_path=custom_db_path, cleanup_interval=1)
        custom_client.start()

        class DefaultBoundNote(ORMModel, collection_name="default_bound_notes"):
            title: str

        class CustomBoundNote(ORMModel, collection_name="custom_bound_notes", client=custom_client):
            title: str

        try:
            note = DefaultBoundNote(title="hello default")
            object_id = await note.save()
            self.assertEqual(object_id, str(note.id))

            found = [item async for item in DefaultBoundNote.Search({"title": "hello default"})]
            self.assertEqual(len(found), 1)
            self.assertIsInstance(found[0], DefaultBoundNote)

            found_one = await DefaultBoundNote.SearchOne({"title": "hello default"})
            self.assertIsInstance(found_one, DefaultBoundNote)
            self.assertEqual(found_one.id, note.id)

            found_by_id = await DefaultBoundNote.SearchOneById(object_id)
            self.assertIsInstance(found_by_id, DefaultBoundNote)
            self.assertEqual(found_by_id.id, note.id)

            self.assertTrue(await note.delete())
            self.assertFalse(await DefaultBoundNote.Delete(object_id))

            custom_note = CustomBoundNote(title="hello custom")
            custom_id = await custom_note.save()
            self.assertIsNotNone(await custom_client.get(CustomBoundNote, custom_id))
            self.assertIsNone(await default_client.get(CustomBoundNote.CollectionName, custom_id))
        finally:
            await _close_orm_client(default_client)
            await _close_orm_client(custom_client)
            await sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def test_system_metrics_store_retention_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "metrics.sqlite3"
            client = SQLiteORMClient(db_path=db_path, cleanup_interval=1)
            client.start()
            try:
                store = ORMSystemMetricsStore(client, retention_seconds=0.05)
                record = SystemMetricRecord(
                    timestamp="2026-01-01 00:00:00",
                    cpu_avg=10.0,
                    cpu_cores=[10.0, 10.0],
                    mem_used=1,
                    mem_total=2,
                    mem_pct=50.0,
                    process_count=3,
                )

                await store._async_write(record)
                self.assertIsNotNone(await client.get(SystemMetricRecord, record.id))

                await sleep(0.08)
                await client.cleanup(force=True)
                self.assertIsNone(await client.get(SystemMetricRecord, record.id))
            finally:
                await _close_orm_client(client)


class TestDefaultORMLogStore(unittest.IsolatedAsyncioTestCase):
    class _FakeNonSQLLogClient:
        def __init__(self, rows: list[dict[str, object]]) -> None:
            self.rows = [dict(item) for item in rows]
            self.ensure_calls = 0
            self.search_calls = 0

        async def ensure_collection(self, model_cls: type[ORMModel]) -> None:
            self.ensure_calls += 1

        async def search(
            self,
            collection: type[ORMModel],
            query: dict[str, object] | None = None,
            *,
            limit: int | None = None,
            offset: int = 0,
            as_model: bool = True,
        ):
            self.search_calls += 1
            for row in self.rows:
                yield dict(row)

    async def test_non_sql_client_uses_search_fallback(self) -> None:
        client = self._FakeNonSQLLogClient([
            {
                "id": "1",
                "timestamp": "2026-01-01 00:00:00",
                "level": "INFO",
                "levelno": 20,
                "name": "mongo.test",
                "process": 1,
                "message": "alpha message",
            },
            {
                "id": "2",
                "timestamp": "2026-01-01 00:00:01",
                "level": "ERROR",
                "levelno": 40,
                "name": "mongo.test",
                "process": 1,
                "message": "beta message",
            },
        ])
        store = DefaultORMLogStore(client=client, model_cls_factory=lambda: StorageNote)

        def _fail_fetchall(*args: object, **kwargs: object) -> object:
            raise AssertionError("non-SQL log store query should not call SQL fetchall helper")

        def _fail_fetchone(*args: object, **kwargs: object) -> object:
            raise AssertionError("non-SQL log store count should not call SQL fetchone helper")

        store._execute_sql_fetchall = _fail_fetchall  # type: ignore[method-assign]
        store._execute_sql_fetchone = _fail_fetchone  # type: ignore[method-assign]

        rows = await store.query(search="alpha")
        total = await store.count_filtered(min_levelno=30)

        self.assertEqual([row["id"] for row in rows], ["1"])
        self.assertEqual(total, 1)
        self.assertEqual(client.ensure_calls, 2)
        self.assertEqual(client.search_calls, 2)

    async def test_non_sql_client_query_can_return_total(self) -> None:
        client = self._FakeNonSQLLogClient([
            {
                "id": "1",
                "timestamp": "2026-01-01 00:00:00",
                "level": "INFO",
                "levelno": 20,
                "name": "mongo.test",
                "process": 1,
                "message": "alpha message",
            },
            {
                "id": "2",
                "timestamp": "2026-01-01 00:00:01",
                "level": "ERROR",
                "levelno": 40,
                "name": "mongo.test",
                "process": 1,
                "message": "beta message",
            },
        ])
        store = DefaultORMLogStore(client=client, model_cls_factory=lambda: StorageNote)

        rows, total = await store.query(search="message", limit=1, include_total=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(total, 2)
        self.assertEqual(client.ensure_calls, 1)
        self.assertEqual(client.search_calls, 1)

    async def test_sql_helpers_reject_non_sql_clients(self) -> None:
        store = DefaultORMLogStore(client=object(), model_cls_factory=lambda: StorageNote)
        with self.assertRaises(TypeError):
            await store._execute_sql_fetchall(object(), "SELECT 1", {})
        with self.assertRaises(TypeError):
            await store._execute_sql_fetchone(object(), "SELECT 1", {})

    async def test_write_dispatches_async_persistence_in_background(self) -> None:
        store = DefaultORMLogStore(
            client=SQLiteORMClient(db_path=Path(tempfile.gettempdir()) / "proj_log_store_background.sqlite3"),
            model_cls_factory=lambda: StorageNote,
        )
        record = {
            "timestamp": "2026-01-01 00:00:00",
            "level": "INFO",
            "levelno": 20,
            "name": "app.worker",
            "process": 1,
            "message": "background write",
            "exc_info": None,
        }

        with patch("core.storage.orm.log_store.run_in_background") as run_in_background_mock:
            store.write(record)

        run_in_background_mock.assert_called_once_with(store._async_write, args=(record,), timeout=None)


class TestStorageConfigAliases(unittest.TestCase):
    def test_etcd_kv_config_resolves_from_dict(self) -> None:
        config = StorageConfig.model_validate({
            "kv": {
                "default": {
                    "type": "etcd",
                    "host": "127.0.0.1",
                    "port": 23791,
                    "prefix": "test",
                },
            },
        })
        self.assertIsInstance(config.kv.default, EtcdKVDBConfig)
        self.assertEqual(config.kv.default.Type, "etcd")

    def test_pica_kv_config_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown KV config type `pica`"):
            StorageConfig.model_validate({
                "kv": {
                    "default": {
                        "type": "pica",
                        "namespace": "pica-test",
                    },
                },
            })

    def test_local_kv_config_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown KV config type `local`"):
            StorageConfig.model_validate({
                "kv": {
                    "default": {
                        "type": "local",
                        "namespace": "legacy-local-test",
                    },
                },
            })

    def test_mysql_orm_config_resolves_from_dict(self) -> None:
        config = StorageConfig.model_validate({
            "orm": {
                "default": {
                    "type": "mysql",
                    "host": "127.0.0.1",
                    "port": 3307,
                    "username": "root",
                    "password": "rootpass",
                    "database": "projtemplate_test",
                },
            },
        })
        self.assertIsInstance(config.orm.default, MySQL_ORM_DB_Config)
        self.assertEqual(config.orm.default.Type, "mysql")


# ---------------------------------------------------------------------------
# Object storage
# ---------------------------------------------------------------------------

class TestStorageObject(unittest.IsolatedAsyncioTestCase):
    async def test_local_object_put_search_get_and_expire(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_path = Path(tmp_dir) / "objects"
            meta_path = Path(tmp_dir) / "objects_meta.sqlite3"
            client = LocalObjectClient(root_path=root_path, metadata_db_path=meta_path, cleanup_interval=1)
            client.start()
            try:
                meta = await client.put(
                    b"hello object storage",
                    object_name="docs/hello.txt",
                    metadata={"topic": "demo", "lang": "en"},
                    content_type="text/plain",
                )
                self.assertEqual(meta["name"], "hello.txt")
                self.assertEqual(await client.get_bytes("docs/hello.txt"), b"hello object storage")

                results = [item async for item in client.search(name="hello", path_prefix="docs/", metadata={"topic": "demo"})]
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["path"], "docs/hello.txt")

                self.assertTrue(await client.set_expire("docs/hello.txt", 0.01))
                await sleep(0.03)
                await client.cleanup(force=True)
                self.assertIsNone(await client.get_bytes("docs/hello.txt"))
                self.assertEqual([item async for item in client.search(name="hello")], [])
            finally:
                _close_object_client(client)

    async def test_object_metadata_db_name_uses_global_kv_and_explicit_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = StorageConfig(
                kv=KV_StorageConfig(
                    default=LocalKVDBConfig(db_path=str(root / "kv-default.sqlite3"), namespace="kv-default"),
                    extra={
                        "meta": LocalKVDBConfig(db_path=str(root / "kv-meta.sqlite3"), namespace="kv-meta"),
                    },
                ),
                object=ObjectStorageConfig(
                    default=LocalObjectDBConfig(root_path=str(root / "objects"), metadata_db="meta"),
                    temp_file_upload=LocalObjectDBConfig(root_path=str(root / "objects-fallback"), metadata_db="default"),
                ),
            )
            StorageConfig.SetGlobal(config)

            default_object = config.object.get_default()
            fallback_object = config.object.get_temp_file_upload()
            named_kv = config.kv.get_client("meta", fallback="default")
            default_kv = config.kv.get_default()
            try:
                default_object.start()
                fallback_object.start()

                self.assertIs(default_object._metadata_kv, named_kv)
                self.assertIs(fallback_object._metadata_kv, default_kv)
                self.assertFalse(default_object._owns_metadata_kv)
                self.assertFalse(fallback_object._owns_metadata_kv)
                self.assertTrue(named_kv.started)
                self.assertTrue(default_kv.started)
            finally:
                _close_object_client(default_object)
                _close_object_client(fallback_object)
                _close_local_kv(named_kv)
                if default_kv is not named_kv:
                    _close_local_kv(default_kv)


# ---------------------------------------------------------------------------
# Config & singleton
# ---------------------------------------------------------------------------

class TestStorageConfigSingleton(unittest.IsolatedAsyncioTestCase):
    async def test_set_global_resets_default_client_singletons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_1, tempfile.TemporaryDirectory() as tmp_dir_2:
            config_1 = StorageConfig(
                kv=KV_StorageConfig(
                    default=LocalKVDBConfig(db_path=str(Path(tmp_dir_1) / "kv.sqlite3"), namespace="cfg1"),
                ),
                orm=ORMStorageConfig(
                    default=SQLiteORMDBConfig(db_path=str(Path(tmp_dir_1) / "orm.sqlite3"), namespace="cfg1"),
                ),
                object=ObjectStorageConfig(
                    default=LocalObjectDBConfig(
                        root_path=str(Path(tmp_dir_1) / "objects"),
                        metadata_db=LocalKVDBConfig(db_path=str(Path(tmp_dir_1) / "objects_meta.sqlite3"), namespace="cfg1:objects"),
                        namespace="cfg1",
                    ),
                ),
            )
            StorageConfig.SetGlobal(config_1)
            kv_1 = KVClientBase.Default()
            orm_1 = ORM_ClientBase.Default()
            try:
                self.assertIs(StorageConfig.Global(), config_1)
                self.assertIsInstance(kv_1, SQLiteKVClient)
                self.assertIsInstance(orm_1, SQLiteORMClient)

                config_2 = StorageConfig(
                    kv=KV_StorageConfig(
                        default=LocalKVDBConfig(db_path=str(Path(tmp_dir_2) / "kv.sqlite3"), namespace="cfg2"),
                    ),
                    orm=ORMStorageConfig(
                        default=SQLiteORMDBConfig(db_path=str(Path(tmp_dir_2) / "orm.sqlite3"), namespace="cfg2"),
                    ),
                    object=ObjectStorageConfig(
                        default=LocalObjectDBConfig(
                            root_path=str(Path(tmp_dir_2) / "objects"),
                            metadata_db=LocalKVDBConfig(db_path=str(Path(tmp_dir_2) / "objects_meta.sqlite3"), namespace="cfg2:objects"),
                            namespace="cfg2",
                        ),
                    ),
                )
                StorageConfig.SetGlobal(config_2)
                kv_2 = KVClientBase.Default()
                orm_2 = ORM_ClientBase.Default()

                self.assertIs(StorageConfig.Global(), config_2)
                self.assertIsNot(kv_1, kv_2)
                self.assertIsNot(orm_1, orm_2)
                self.assertEqual(Path(kv_2._db_path).name, "kv.sqlite3")
                self.assertEqual(Path(orm_2._db_path).name, "orm.sqlite3")
            finally:
                _close_local_kv(kv_1)
                await _close_orm_client(orm_1)
                _close_local_kv(KVClientBase.Default())
                await _close_orm_client(ORM_ClientBase.Default())

    async def test_polymorphic_storage_config_dump_and_load(self) -> None:
        payload = {
            "kv": {
                "default": {"type": "sqlite", "namespace": "cfg", "db_path": "tmp/kv.sqlite3"},
            },
            "orm": {
                "default": {"type": "sqlite", "namespace": "cfg", "db_path": "tmp/orm.sqlite3"},
            },
            "object": {
                "default": {
                    "type": "local",
                    "namespace": "cfg",
                    "root_path": "tmp/objects",
                    "metadata_db": {"type": "sqlite", "namespace": "cfg:objects", "db_path": "tmp/meta.sqlite3"},
                },
            },
        }

        config = StorageConfig.model_validate(payload)
        dumped = config.model_dump(mode="json")

        # Section-based access
        self.assertIsInstance(config.kv.default, LocalKVDBConfig)
        self.assertIsInstance(config.orm.default, SQLiteORMDBConfig)
        self.assertIsInstance(config.object.default, LocalObjectDBConfig)
        # Dump format
        self.assertEqual(dumped["kv"]["default"]["type"], "sqlite")
        self.assertEqual(dumped["orm"]["default"]["type"], "sqlite")
        self.assertEqual(dumped["object"]["default"]["type"], "local")
        self.assertNotIn("url", dumped["kv"]["default"])
        self.assertEqual(dumped["object"]["default"]["metadata_db"]["type"], "sqlite")

    async def test_client_set_global_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SQLiteKVClient(db_path=Path(tmp_dir) / "manual.sqlite3")
            client.start()
            try:
                KVClientBase.SetGlobal(client)
                self.assertIs(KVClientBase.Default(), client)
            finally:
                _close_local_kv(client)
                KVClientBase.ClearDefaultInstances()

    async def test_storage_config_discards_closed_cached_default_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = StorageConfig(
                kv=KV_StorageConfig(
                    default=LocalKVDBConfig(db_path=str(Path(tmp_dir) / "kv.sqlite3"), namespace="cfg"),
                ),
            )
            kv_1 = config.kv.get_default()
            try:
                self.assertIsInstance(kv_1, SQLiteKVClient)
                _close_local_kv(kv_1)

                kv_2 = config.kv.get_default()
                self.assertIsInstance(kv_2, SQLiteKVClient)
                self.assertIsNot(kv_1, kv_2)
                await kv_2.set("probe", "ok")
                self.assertEqual(await kv_2.get("probe"), "ok")
            finally:
                _close_local_kv(config.kv.get_default())
                config.kv.clear_cached_clients()

    async def test_default_discards_closed_cached_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = StorageConfig(
                kv=KV_StorageConfig(
                    default=LocalKVDBConfig(db_path=str(Path(tmp_dir) / "kv.sqlite3"), namespace="cfg"),
                ),
            )
            StorageConfig.SetGlobal(config)
            kv_1 = KVClientBase.Default()
            try:
                self.assertIsInstance(kv_1, SQLiteKVClient)
                _close_local_kv(kv_1)

                kv_2 = KVClientBase.Default()
                self.assertIsInstance(kv_2, SQLiteKVClient)
                self.assertIsNot(kv_1, kv_2)
                await kv_2.set("probe", "ok")
                self.assertEqual(await kv_2.get("probe"), "ok")
            finally:
                _close_local_kv(KVClientBase.Default())
                KVClientBase.ClearDefaultInstances()

    async def test_set_global_resets_lazy_model_client_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_1, tempfile.TemporaryDirectory() as tmp_dir_2:
            class ReboundNote(ORMModel, collection_name="rebound_notes", client=None):
                title: str

            config_1 = StorageConfig(
                orm=ORMStorageConfig(
                    default=SQLiteORMDBConfig(db_path=str(Path(tmp_dir_1) / "orm.sqlite3"), namespace="cfg1"),
                ),
                kv=KV_StorageConfig(
                    default=LocalKVDBConfig(db_path=str(Path(tmp_dir_1) / "kv.sqlite3"), namespace="cfg1"),
                ),
                object=ObjectStorageConfig(
                    default=LocalObjectDBConfig(
                        root_path=str(Path(tmp_dir_1) / "objects"),
                        metadata_db=LocalKVDBConfig(db_path=str(Path(tmp_dir_1) / "objects_meta.sqlite3"), namespace="cfg1:objects"),
                        namespace="cfg1",
                    ),
                ),
            )
            config_2 = StorageConfig(
                orm=ORMStorageConfig(
                    default=SQLiteORMDBConfig(db_path=str(Path(tmp_dir_2) / "orm.sqlite3"), namespace="cfg2"),
                ),
                kv=KV_StorageConfig(
                    default=LocalKVDBConfig(db_path=str(Path(tmp_dir_2) / "kv.sqlite3"), namespace="cfg2"),
                ),
                object=ObjectStorageConfig(
                    default=LocalObjectDBConfig(
                        root_path=str(Path(tmp_dir_2) / "objects"),
                        metadata_db=LocalKVDBConfig(db_path=str(Path(tmp_dir_2) / "objects_meta.sqlite3"), namespace="cfg2:objects"),
                        namespace="cfg2",
                    ),
                ),
            )

            StorageConfig.SetGlobal(config_1)
            client_1 = ReboundNote.GetClient()

            self.assertIs(client_1, ReboundNote.Client)

            StorageConfig.SetGlobal(config_2)
            self.assertIsNone(ReboundNote.Client)

            client_2 = ReboundNote.GetClient()
            self.assertIs(client_2, ReboundNote.Client)
            self.assertIsNot(client_1, client_2)

            await _close_orm_client(client_1)
            await _close_orm_client(client_2)


class TestModelLazyClientBinding(unittest.TestCase):
    def tearDown(self) -> None:
        StorageConfig.__Instance__ = None
        ORMModel.ResetClientBindings(include_explicit=True)
        ORM_ClientBase.ClearDefaultInstances()
        VectorClientBase.ClearDefaultInstances()

    def test_orm_model_get_client_is_lazy_and_cached(self) -> None:
        with patch(
            "core.storage.config.StorageConfig.Global",
            side_effect=AssertionError("StorageConfig.Global() should stay lazy during class definition"),
        ):
            class LazyORMNote(ORMModel, collection_name="lazy_orm_notes", client=None):
                title: str

        self.assertIsNone(LazyORMNote.Client)

        with tempfile.TemporaryDirectory() as tmp_dir:
            expected_client = SQLiteORMClient(db_path=Path(tmp_dir) / "lazy.sqlite3", cleanup_interval=1)
            get_client = MagicMock(return_value=expected_client)
            with patch(
                "core.storage.config.StorageConfig.Global",
                return_value=SimpleNamespace(orm=SimpleNamespace(get_client=get_client)),
            ) as global_mock:
                self.assertIs(LazyORMNote.GetClient(), expected_client)
                self.assertIs(LazyORMNote.GetClient(), expected_client)

        self.assertIs(LazyORMNote.Client, expected_client)
        self.assertEqual(global_mock.call_count, 1)
        get_client.assert_called_once_with(LazyORMNote.CollectionName)

    def test_vector_model_get_client_is_lazy_and_cached(self) -> None:
        with patch(
            "core.storage.config.StorageConfig.Global",
            side_effect=AssertionError("StorageConfig.Global() should stay lazy during class definition"),
        ):
            class LazyVectorRecord(VectorORMModel, collection_name="lazy_vector_records", client=None):
                title: str = ""
                embedding: list[float] = VectorORMField(default_factory=list, index=VectorIndex(dim=2))

        self.assertIsNone(LazyVectorRecord.Client)

        with tempfile.TemporaryDirectory() as tmp_dir:
            expected_client = AnnoySQLiteVectorClient(db_dir=str(Path(tmp_dir) / "annoy"), cleanup_interval=1)
            get_client = MagicMock(return_value=expected_client)
            with patch(
                "core.storage.config.StorageConfig.Global",
                return_value=SimpleNamespace(vector=SimpleNamespace(get_client=get_client)),
            ) as global_mock:
                self.assertIs(LazyVectorRecord.GetClient(), expected_client)
                self.assertIs(LazyVectorRecord._get_vector_client(), expected_client)

        self.assertIs(LazyVectorRecord.Client, expected_client)
        self.assertEqual(global_mock.call_count, 1)
        get_client.assert_called_once_with(LazyVectorRecord.CollectionName)


class TestStorageConfigGlobalLoading(unittest.TestCase):
    def setUp(self) -> None:
        StorageConfig.__Instance__ = None

    def tearDown(self) -> None:
        StorageConfig.__Instance__ = None

    def test_global_prefers_env_over_discovered_files(self) -> None:
        env_payload = {
            "kv": {
                "default": {
                    "type": "sqlite",
                    "namespace": "env-kv",
                    "db_path": "tmp/env-kv.sqlite3",
                },
            },
        }
        file_payload = {
            "kv": {
                "default": {
                    "type": "sqlite",
                    "namespace": "file-kv",
                    "db_path": "tmp/file-kv.sqlite3",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "dev_storage.json").write_text(json.dumps(file_payload), encoding="utf-8")
            with (
                patch("core.storage.config.PROJECT_DIR", Path(tmp_dir)),
                patch("core.storage.config.Path.cwd", return_value=Path(tmp_dir)),
            ):
                with patch.dict(os.environ, {
                    "__MODE__": "dev",
                    "__STORAGE_CONFIG__": json.dumps(env_payload),
                }, clear=False):
                    config = StorageConfig.Global()

        self.assertIsInstance(config.kv.default, LocalKVDBConfig)
        self.assertEqual(config.kv.default.namespace, "env-kv")

    def test_global_prefers_generic_file_first_in_direct_mode(self) -> None:
        generic_payload = {
            "kv": {
                "default": {
                    "type": "sqlite",
                    "namespace": "generic-kv",
                    "db_path": "tmp/generic-kv.sqlite3",
                },
            },
        }
        dev_payload = {
            "kv": {
                "default": {
                    "type": "sqlite",
                    "namespace": "dev-kv",
                    "db_path": "tmp/dev-kv.sqlite3",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "storage.json").write_text(json.dumps(generic_payload), encoding="utf-8")
            (config_dir / "dev_storage.json").write_text(json.dumps(dev_payload), encoding="utf-8")
            with (
                patch("core.storage.config.PROJECT_DIR", Path(tmp_dir)),
                patch("core.storage.config.Path.cwd", return_value=Path(tmp_dir)),
            ):
                with patch.dict(os.environ, {"__MODE__": "dev"}, clear=True):
                    config = StorageConfig.Global()

        self.assertIsInstance(config.kv.default, LocalKVDBConfig)
        self.assertEqual(config.kv.default.namespace, "generic-kv")

    def test_global_prefers_mode_specific_file_in_server_runtime(self) -> None:
        generic_payload = {
            "kv": {
                "default": {
                    "type": "sqlite",
                    "namespace": "generic-kv",
                    "db_path": "tmp/generic-kv.sqlite3",
                },
            },
        }
        dev_payload = {
            "kv": {
                "default": {
                    "type": "sqlite",
                    "namespace": "dev-kv",
                    "db_path": "tmp/dev-kv.sqlite3",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "storage.json").write_text(json.dumps(generic_payload), encoding="utf-8")
            (config_dir / "dev_storage.json").write_text(json.dumps(dev_payload), encoding="utf-8")
            with (
                patch("core.storage.config.PROJECT_DIR", Path(tmp_dir)),
                patch("core.storage.config.Path.cwd", return_value=Path(tmp_dir)),
            ):
                with patch.dict(os.environ, {"__MODE__": "dev", "__SERVER_PROCESS_PID__": "123"}, clear=True):
                    config = StorageConfig.Global()

        self.assertIsInstance(config.kv.default, LocalKVDBConfig)
        self.assertEqual(config.kv.default.namespace, "dev-kv")


if __name__ == "__main__":
    unittest.main()
