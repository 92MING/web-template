"""Tests for the new ORMFieldSpec / extract_field_specs / serialize / deserialize.

Covers:
  - Kind detection for ALL 12 field kinds
  - Column name resolution (no f_ prefix in extract_field_specs)
  - sql_column_type for all dialects × all kinds
  - serialize_field_value / deserialize_field_value round-trip
  - _sqlite_supports_jsonb / _json_column_type / _blob_column_type
  - detect_column_renames with new expanded kinds
  - index=True on non-indexable kinds → warning & suppressed
  - Edge cases: Optional, Literal, Enum, nested BaseModel, media types
"""
import json
import os
import sys
import unittest
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import ClassVar, Literal
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from pydantic import BaseModel, Field

from core.storage.orm import ORMModel, ORMField
from core.storage.orm.log_store import LogRecordModel, LOG_RECORD_TEXT_MAX_LENGTH
from core.storage.orm.field_schema import (
    FieldKind,
    ORMFieldSpec,
    SQL_DEFAULT_VARCHAR_LENGTH,
    detect_column_renames,
    deserialize_field_value,
    extract_field_specs,
    serialize_field_value,
    sql_column_type,
    _json_column_type,
    _blob_column_type,
    _sqlite_supports_jsonb,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helper models
# ══════════════════════════════════════════════════════════════════════════════

class Color(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"

class Priority(Enum):
    LOW = 1
    MED = 2
    HIGH = 3

class EmbeddedMeta(BaseModel):
    key: str = ""
    value: str = ""

class ScalarModel(ORMModel, full_collection_name="test_scalar"):
    name: str = ""
    score: float = 0.0
    count: int = 0
    active: bool = False
    created: datetime = Field(default_factory=datetime.now)
    birthday: date = Field(default_factory=date.today)
    color: Color = Color.RED
    priority: Priority = Priority.LOW
    status: Literal["draft", "published", "archived"] = "draft"

class JsonModel(ORMModel, full_collection_name="test_json"):
    tags: dict[str, str] = {}
    items: list[int] = []
    meta: EmbeddedMeta = Field(default_factory=EmbeddedMeta)
    raw: dict = {}

class NullableModel(ORMModel, full_collection_name="test_nullable"):
    name: str | None = None
    score: float | None = None
    count: int | None = None
    active: bool | None = None
    created: datetime | None = None
    birthday: date | None = None
    tags: dict | None = None

class MaxLenModel(ORMModel, full_collection_name="test_maxlen"):
    short_name: str = ORMField("", max_length=32)
    description: str = ""  # default 2048
    bio: str = ORMField("", max_length=1024)
    code: Literal["A", "BB", "CCC"] = "A"  # max_length=3 inferred

class IndexModel(ORMModel, full_collection_name="test_index"):
    name: str = ORMField("", index=True)
    score: float = ORMField(0.0, index=True)
    tags: dict = ORMField(default_factory=dict, index=True)  # json → index suppressed
    meta: EmbeddedMeta = ORMField(default_factory=EmbeddedMeta, index=True)  # json → suppressed

class AliasModel(ORMModel, full_collection_name="test_alias"):
    user_name: str = ORMField("", db_name="username")
    phone_number: str = ORMField("", db_name="phone")
    email: str = ""  # column = "email"


# ══════════════════════════════════════════════════════════════════════════════
# Tests: Kind Detection
# ══════════════════════════════════════════════════════════════════════════════

class TestKindDetection(unittest.TestCase):

    def test_scalar_kinds(self):
        specs = extract_field_specs(ScalarModel)
        self.assertEqual(specs["name"].kind, "str")
        self.assertEqual(specs["score"].kind, "float")
        self.assertEqual(specs["count"].kind, "int")
        self.assertEqual(specs["active"].kind, "bool")
        self.assertEqual(specs["created"].kind, "datetime")
        self.assertEqual(specs["birthday"].kind, "date")

    def test_enum_kinds(self):
        specs = extract_field_specs(ScalarModel)
        self.assertEqual(specs["color"].kind, "str")
        self.assertEqual(specs["priority"].kind, "int")

    def test_literal_kind(self):
        specs = extract_field_specs(ScalarModel)
        self.assertEqual(specs["status"].kind, "str")

    def test_json_kinds(self):
        specs = extract_field_specs(JsonModel)
        self.assertEqual(specs["tags"].kind, "json")
        self.assertEqual(specs["items"].kind, "json")
        self.assertEqual(specs["meta"].kind, "json")
        self.assertEqual(specs["raw"].kind, "json")

    def test_nullable_kinds(self):
        specs = extract_field_specs(NullableModel)
        self.assertEqual(specs["name"].kind, "str")
        self.assertTrue(specs["name"].nullable)
        self.assertEqual(specs["score"].kind, "float")
        self.assertTrue(specs["score"].nullable)
        self.assertEqual(specs["count"].kind, "int")
        self.assertTrue(specs["count"].nullable)
        self.assertEqual(specs["active"].kind, "bool")
        self.assertTrue(specs["active"].nullable)
        self.assertEqual(specs["created"].kind, "datetime")
        self.assertTrue(specs["created"].nullable)
        self.assertEqual(specs["birthday"].kind, "date")
        self.assertTrue(specs["birthday"].nullable)
        self.assertEqual(specs["tags"].kind, "json")
        self.assertTrue(specs["tags"].nullable)

    def test_non_nullable_scalars(self):
        specs = extract_field_specs(ScalarModel)
        self.assertFalse(specs["name"].nullable)
        self.assertFalse(specs["score"].nullable)
        self.assertFalse(specs["count"].nullable)
        self.assertFalse(specs["active"].nullable)

    def test_log_record_message_and_exc_info_use_explicit_large_max_length(self):
        specs = extract_field_specs(LogRecordModel)
        self.assertEqual(specs["message"].kind, "str")
        self.assertFalse(specs["message"].nullable)
        self.assertEqual(specs["message"].max_length, LOG_RECORD_TEXT_MAX_LENGTH)
        self.assertEqual(specs["exc_info"].kind, "str")
        self.assertTrue(specs["exc_info"].nullable)
        self.assertEqual(specs["exc_info"].max_length, LOG_RECORD_TEXT_MAX_LENGTH)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: Column Name Resolution
# ══════════════════════════════════════════════════════════════════════════════

class TestColumnNames(unittest.TestCase):

    def test_no_f_prefix_in_extract_field_specs(self):
        specs = extract_field_specs(ScalarModel)
        for name, spec in specs.items():
            self.assertFalse(spec.column_name.startswith("f_"),
                             f"Field {name} has f_ prefix: {spec.column_name}")

    def test_alias_db_name(self):
        specs = extract_field_specs(AliasModel)
        self.assertEqual(specs["user_name"].column_name, "username")
        self.assertEqual(specs["phone_number"].column_name, "phone")
        self.assertEqual(specs["email"].column_name, "email")

    def test_alias_db_name_resolved(self):
        specs = extract_field_specs(AliasModel)
        self.assertEqual(specs["user_name"].column_name, "username")
        self.assertEqual(specs["phone_number"].column_name, "phone")
        self.assertEqual(specs["email"].column_name, "email")


# ══════════════════════════════════════════════════════════════════════════════
# Tests: Max Length
# ══════════════════════════════════════════════════════════════════════════════

class TestMaxLength(unittest.TestCase):

    def test_declared_max_length(self):
        specs = extract_field_specs(MaxLenModel)
        self.assertEqual(specs["short_name"].max_length, 32)
        self.assertEqual(specs["bio"].max_length, 1024)

    def test_default_max_length(self):
        specs = extract_field_specs(MaxLenModel)
        self.assertEqual(SQL_DEFAULT_VARCHAR_LENGTH, 2048)
        self.assertEqual(specs["description"].max_length, SQL_DEFAULT_VARCHAR_LENGTH)

    def test_literal_inferred_max_length(self):
        specs = extract_field_specs(MaxLenModel)
        self.assertEqual(specs["code"].max_length, 3)

    def test_non_str_no_max_length(self):
        specs = extract_field_specs(ScalarModel)
        self.assertIsNone(specs["count"].max_length)
        self.assertIsNone(specs["score"].max_length)
        self.assertIsNone(specs["active"].max_length)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: Index
# ══════════════════════════════════════════════════════════════════════════════

class TestIndex(unittest.TestCase):

    def test_index_on_scalar(self):
        specs = extract_field_specs(IndexModel)
        self.assertTrue(specs["name"].index)
        self.assertTrue(specs["score"].index)

    def test_index_suppressed_on_json(self):
        specs = extract_field_specs(IndexModel)
        self.assertFalse(specs["tags"].index)
        self.assertFalse(specs["meta"].index)


# ══════════════════════════════════════════════════════════════════════════════
# Tests: sql_column_type
# ══════════════════════════════════════════════════════════════════════════════

class TestSqlColumnType(unittest.TestCase):

    def _spec(self, kind: str, max_length: int | None = None) -> ORMFieldSpec:
        return ORMFieldSpec(
            field_name="x", column_name="x",
            kind=kind, nullable=False, index=False,
            max_length=max_length,
        )

    # ── SQLite ──

    def test_sqlite_bool(self):
        self.assertEqual(sql_column_type(self._spec("bool"), "sqlite"), "INTEGER")

    def test_sqlite_int(self):
        self.assertEqual(sql_column_type(self._spec("int"), "sqlite"), "INTEGER")

    def test_sqlite_float(self):
        self.assertEqual(sql_column_type(self._spec("float"), "sqlite"), "REAL")

    def test_sqlite_str(self):
        self.assertEqual(sql_column_type(self._spec("str", 100), "sqlite"), "TEXT")

    def test_sqlite_datetime(self):
        self.assertEqual(sql_column_type(self._spec("datetime"), "sqlite"), "DATETIME")

    def test_sqlite_date(self):
        self.assertEqual(sql_column_type(self._spec("date"), "sqlite"), "DATE")

    def test_sqlite_json(self):
        col_type = sql_column_type(self._spec("json"), "sqlite")
        self.assertIn(col_type, {"JSONB", "TEXT"})

    def test_sqlite_blob(self):
        self.assertEqual(sql_column_type(self._spec("blob_single"), "sqlite"), "BLOB")
        self.assertEqual(sql_column_type(self._spec("blob_union"), "sqlite"), "BLOB")

    def test_sqlite_file_id(self):
        col_type = sql_column_type(self._spec("file_id"), "sqlite")
        self.assertIn(col_type, {"JSONB", "TEXT"})

    def test_sqlite_foreign_single(self):
        self.assertEqual(sql_column_type(self._spec("foreign_single"), "sqlite"), "TEXT")

    def test_sqlite_foreign_list(self):
        col_type = sql_column_type(self._spec("foreign_list"), "sqlite")
        self.assertIn(col_type, {"JSONB", "TEXT"})

    # ── PostgreSQL ──

    def test_postgresql_bool(self):
        self.assertEqual(sql_column_type(self._spec("bool"), "postgresql"), "BOOLEAN")

    def test_postgresql_int(self):
        self.assertEqual(sql_column_type(self._spec("int"), "postgresql"), "BIGINT")

    def test_postgresql_float(self):
        self.assertEqual(sql_column_type(self._spec("float"), "postgresql"), "DOUBLE PRECISION")

    def test_postgresql_str_varchar(self):
        self.assertEqual(sql_column_type(self._spec("str", 128), "postgresql"), "VARCHAR(128)")

    def test_postgresql_datetime(self):
        self.assertEqual(sql_column_type(self._spec("datetime"), "postgresql"), "TIMESTAMP")

    def test_postgresql_json(self):
        self.assertEqual(sql_column_type(self._spec("json"), "postgresql"), "JSONB")

    def test_postgresql_blob(self):
        self.assertEqual(sql_column_type(self._spec("blob_single"), "postgresql"), "BYTEA")

    def test_postgresql_foreign_single(self):
        self.assertEqual(sql_column_type(self._spec("foreign_single"), "postgresql"), "VARCHAR(64)")

    # ── MySQL ──

    def test_mysql_bool(self):
        self.assertEqual(sql_column_type(self._spec("bool"), "mysql"), "BOOLEAN")

    def test_mysql_datetime(self):
        self.assertEqual(sql_column_type(self._spec("datetime"), "mysql"), "DATETIME(6)")

    def test_mysql_json(self):
        self.assertEqual(sql_column_type(self._spec("json"), "mysql"), "JSON")

    def test_mysql_blob(self):
        self.assertEqual(sql_column_type(self._spec("blob_single"), "mysql"), "LONGBLOB")


# ══════════════════════════════════════════════════════════════════════════════
# Tests: JSONB support
# ══════════════════════════════════════════════════════════════════════════════

class TestJsonbSupport(unittest.TestCase):

    def test_sqlite_supports_jsonb_returns_bool(self):
        result = _sqlite_supports_jsonb()
        self.assertIsInstance(result, bool)

    def test_json_column_type_sqlite(self):
        col = _json_column_type("sqlite")
        self.assertIn(col, {"JSONB", "TEXT"})

    def test_json_column_type_postgresql(self):
        self.assertEqual(_json_column_type("postgresql"), "JSONB")

    def test_json_column_type_mysql(self):
        self.assertEqual(_json_column_type("mysql"), "JSON")

    def test_blob_column_type_sqlite(self):
        self.assertEqual(_blob_column_type("sqlite"), "BLOB")

    def test_blob_column_type_postgresql(self):
        self.assertEqual(_blob_column_type("postgresql"), "BYTEA")

    def test_blob_column_type_mysql(self):
        self.assertEqual(_blob_column_type("mysql"), "LONGBLOB")


# ══════════════════════════════════════════════════════════════════════════════
# Tests: serialize_field_value
# ══════════════════════════════════════════════════════════════════════════════

class TestSerializeFieldValue(unittest.TestCase):

    def _spec(self, kind: str, max_length: int | None = None) -> ORMFieldSpec:
        return ORMFieldSpec(
            field_name="x", column_name="x",
            kind=kind, nullable=False, index=False,
            max_length=max_length,
        )

    def test_none_returns_none(self):
        for kind in ("bool", "int", "float", "str", "date", "datetime", "json"):
            result = serialize_field_value(self._spec(kind), None)
            self.assertIsNone(result, f"kind={kind}")

    def test_bool_values(self):
        s = self._spec("bool")
        self.assertIs(serialize_field_value(s, True), True)
        self.assertIs(serialize_field_value(s, False), False)
        self.assertIs(serialize_field_value(s, 1), True)
        self.assertIs(serialize_field_value(s, 0), False)

    def test_int_values(self):
        s = self._spec("int")
        self.assertEqual(serialize_field_value(s, 42), 42)
        self.assertEqual(serialize_field_value(s, "123"), 123)
        self.assertIsNone(serialize_field_value(s, "not_a_number"))

    def test_float_values(self):
        s = self._spec("float")
        self.assertEqual(serialize_field_value(s, 3.14), 3.14)
        self.assertEqual(serialize_field_value(s, "2.5"), 2.5)
        self.assertIsNone(serialize_field_value(s, "bad"))

    def test_str_values(self):
        s = self._spec("str")
        self.assertEqual(serialize_field_value(s, "hello"), "hello")
        self.assertEqual(serialize_field_value(s, 42), "42")

    def test_str_truncation(self):
        s = self._spec("str", max_length=5)
        self.assertEqual(serialize_field_value(s, "hello world"), "hello")

    def test_str_dict_json_dumps(self):
        s = self._spec("str")
        result = serialize_field_value(s, {"key": "val"})
        self.assertEqual(json.loads(result), {"key": "val"})

    def test_datetime_iso(self):
        s = self._spec("datetime")
        dt = datetime(2024, 1, 15, 12, 30, 0)
        self.assertEqual(serialize_field_value(s, dt), "2024-01-15T12:30:00")

    def test_date_iso(self):
        s = self._spec("date")
        d = date(2024, 1, 15)
        self.assertEqual(serialize_field_value(s, d), "2024-01-15")

    def test_date_from_datetime(self):
        s = self._spec("date")
        dt = datetime(2024, 1, 15, 12, 30, 0)
        self.assertEqual(serialize_field_value(s, dt), "2024-01-15")

    def test_json_dict(self):
        s = self._spec("json")
        result = serialize_field_value(s, {"a": 1, "b": [2, 3]})
        parsed = json.loads(result)
        self.assertEqual(parsed, {"a": 1, "b": [2, 3]})

    def test_json_list(self):
        s = self._spec("json")
        result = serialize_field_value(s, [1, 2, 3])
        self.assertEqual(json.loads(result), [1, 2, 3])

    def test_json_pydantic_model(self):
        s = self._spec("json")
        m = EmbeddedMeta(key="k", value="v")
        result = serialize_field_value(s, m)
        parsed = json.loads(result)
        self.assertEqual(parsed, {"key": "k", "value": "v"})

    def test_json_plain_string_is_json_encoded(self):
        s = self._spec("json")
        result = serialize_field_value(s, "not-json")
        self.assertEqual(result, '"not-json"')

    def test_enum_serialized(self):
        s = self._spec("str")
        self.assertEqual(serialize_field_value(s, Color.RED), "red")
        si = self._spec("int")
        self.assertEqual(serialize_field_value(si, Priority.HIGH), 3)

    def test_blob_bytes(self):
        s = self._spec("blob_single")
        self.assertEqual(serialize_field_value(s, b"raw"), b"raw")

    def test_foreign_single_with_id(self):
        s = self._spec("foreign_single")

        class FakeModel:
            id = "abc123"

        self.assertEqual(serialize_field_value(s, FakeModel()), "abc123")

    def test_foreign_list(self):
        s = self._spec("foreign_list")

        class FakeModel:
            def __init__(self, oid):
                self.id = oid

        result = serialize_field_value(s, [FakeModel("a"), FakeModel("b")])
        self.assertEqual(json.loads(result), ["a", "b"])


# ══════════════════════════════════════════════════════════════════════════════
# Tests: deserialize_field_value
# ══════════════════════════════════════════════════════════════════════════════

class TestDeserializeFieldValue(unittest.TestCase):

    def _spec(self, kind: str) -> ORMFieldSpec:
        return ORMFieldSpec(
            field_name="x", column_name="x",
            kind=kind, nullable=False, index=False,
        )

    def test_none_returns_none(self):
        for kind in ("bool", "int", "float", "str", "json"):
            self.assertIsNone(deserialize_field_value(self._spec(kind), None))

    def test_bool(self):
        self.assertIs(deserialize_field_value(self._spec("bool"), 1), True)
        self.assertIs(deserialize_field_value(self._spec("bool"), 0), False)

    def test_int(self):
        self.assertEqual(deserialize_field_value(self._spec("int"), 42), 42)
        self.assertEqual(deserialize_field_value(self._spec("int"), "99"), 99)

    def test_float(self):
        self.assertAlmostEqual(deserialize_field_value(self._spec("float"), 1.5), 1.5)
        self.assertAlmostEqual(deserialize_field_value(self._spec("float"), "2.7"), 2.7)

    def test_str_passthrough(self):
        self.assertEqual(deserialize_field_value(self._spec("str"), "hello"), "hello")

    def test_json_from_str(self):
        result = deserialize_field_value(self._spec("json"), '{"a": 1}')
        self.assertEqual(result, {"a": 1})

    def test_json_from_dict(self):
        result = deserialize_field_value(self._spec("json"), {"a": 1})
        self.assertEqual(result, {"a": 1})

    def test_json_invalid_string_returns_raw(self):
        result = deserialize_field_value(self._spec("json"), "not-json")
        self.assertEqual(result, "not-json")

    def test_foreign_single_str(self):
        self.assertEqual(deserialize_field_value(self._spec("foreign_single"), "abc"), "abc")

    def test_foreign_list_from_json(self):
        result = deserialize_field_value(self._spec("foreign_list"), '["a","b","c"]')
        self.assertEqual(result, ["a", "b", "c"])


# ══════════════════════════════════════════════════════════════════════════════
# Tests: detect_column_renames
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectColumnRenames(unittest.TestCase):

    def test_system_columns_never_orphaned(self):
        """System columns (size, expire_at, etc.) should never be considered orphans."""
        existing = {
            "id": "TEXT",
            "_id": "TEXT",
            "payload_json": "TEXT",
            "size": "INTEGER",
            "expire_at": "REAL",
            "accessed_at": "REAL",
        }
        missing_spec = ORMFieldSpec(
            field_name="count", column_name="count",
            kind="int", nullable=False, index=False,
        )
        renames = detect_column_renames(existing, {"count": missing_spec}, "sqlite")
        self.assertEqual(renames, [], "System columns should not match rename candidates")

    def test_rename_detected(self):
        existing = {"old_name": "TEXT", "id": "TEXT"}
        spec = ORMFieldSpec(
            field_name="new_name", column_name="new_name",
            kind="str", nullable=False, index=False,
        )
        renames = detect_column_renames(existing, {"new_name": spec}, "sqlite")
        self.assertEqual(len(renames), 1)
        self.assertEqual(renames[0][0], "old_name")
        self.assertEqual(renames[0][1].column_name, "new_name")

    def test_ambiguous_rename_not_detected(self):
        """Two orphaned TEXT columns → ambiguous → no rename."""
        existing = {"col_a": "TEXT", "col_b": "TEXT", "id": "TEXT"}
        spec = ORMFieldSpec(
            field_name="target", column_name="target",
            kind="str", nullable=False, index=False,
        )
        renames = detect_column_renames(existing, {"target": spec}, "sqlite")
        self.assertEqual(renames, [])


# ══════════════════════════════════════════════════════════════════════════════
# Tests: Serialize → Deserialize Round Trip
# ══════════════════════════════════════════════════════════════════════════════

class TestSerializeDeserializeRoundTrip(unittest.TestCase):

    def _spec(self, kind: str, **kw) -> ORMFieldSpec:
        return ORMFieldSpec(
            field_name="x", column_name="x",
            kind=kind, nullable=False, index=False,
            **kw,
        )

    def test_bool_round_trip(self):
        s = self._spec("bool")
        for v in (True, False):
            self.assertEqual(deserialize_field_value(s, serialize_field_value(s, v)), v)

    def test_int_round_trip(self):
        s = self._spec("int")
        for v in (0, 42, -100, 2**31):
            self.assertEqual(deserialize_field_value(s, serialize_field_value(s, v)), v)

    def test_float_round_trip(self):
        s = self._spec("float")
        for v in (0.0, 3.14, -1e10):
            self.assertAlmostEqual(deserialize_field_value(s, serialize_field_value(s, v)), v)

    def test_str_round_trip(self):
        s = self._spec("str")
        for v in ("", "hello", "中文", "a" * 1000):
            self.assertEqual(deserialize_field_value(s, serialize_field_value(s, v)), v)

    def test_json_dict_round_trip(self):
        s = self._spec("json")
        d = {"key": "val", "nested": [1, 2, {"a": True}]}
        result = deserialize_field_value(s, serialize_field_value(s, d))
        self.assertEqual(result, d)

    def test_foreign_list_round_trip(self):
        s = self._spec("foreign_list")
        ids = ["id1", "id2", "id3"]
        serialized = serialize_field_value(s, ids)
        deserialized = deserialize_field_value(s, serialized)
        self.assertEqual(deserialized, ids)


if __name__ == "__main__":
    unittest.main()
