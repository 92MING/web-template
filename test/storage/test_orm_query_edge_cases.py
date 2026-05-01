"""Extreme edge-case tests for _orm_query.py.

Covers: Enum, datetime/date, int/float/str coercion, structured BaseModel eq/ne,
string-JSON → BaseModel parsing, contains with type mismatch, in-memory matching,
SQL param generation, and Mongo filter generation.
"""
import sys
from datetime import date, datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Literal

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import os

from pydantic import BaseModel

from core.storage.orm.query import (
    _FieldExpression,
    _normalize_query_value,
    _build_structured_query_expression,
    _coerce_structured_query_value,
    ORMFieldProxy,
    QueryExpression,
)


# ── Test models / enums ──────────────────────────────────────────────────────
class Status(str, Enum):
    READY = "ready"
    GENERATING = "generating"
    ERROR = "error"


class Priority(IntEnum):
    LOW = 1
    MEDIUM = 5
    HIGH = 10


class InnerModel(BaseModel):
    status: Status = Status.READY
    error_message: str | None = None


class OuterModel(BaseModel):
    name: str = ""
    inner: InnerModel = InnerModel()
    score: float = 0.0


# ── helpers ──────────────────────────────────────────────────────────────────
def _matches(field: str, op: str, value, doc: dict) -> bool:
    return _FieldExpression(field, op, value).matches(doc)


def _sql(field: str, op: str, value, dialect: str = "sqlite"):
    return _FieldExpression(field, op, value).to_sql_conditions(dialect)


def _mongo(field: str, op: str, value):
    return _FieldExpression(field, op, value).to_mongo_filter()


# ══════════════════════════════════════════════════════════════════════════════
# 1. Enum handling
# ══════════════════════════════════════════════════════════════════════════════
class TestEnumHandling:

    def test_normalize_str_enum(self):
        assert _normalize_query_value(Status.READY) == "ready"

    def test_normalize_int_enum(self):
        assert _normalize_query_value(Priority.HIGH) == 10

    def test_normalize_enum_in_list(self):
        result = _normalize_query_value([Status.READY, Status.ERROR])
        assert result == ["ready", "error"]

    def test_normalize_enum_in_dict(self):
        result = _normalize_query_value({"status": Status.READY, "priority": Priority.LOW})
        assert result == {"status": "ready", "priority": 1}

    def test_matches_eq_str_enum(self):
        assert _matches("s", "eq", Status.READY, {"s": "ready"})
        assert not _matches("s", "eq", Status.READY, {"s": "error"})

    def test_matches_eq_int_enum(self):
        assert _matches("p", "eq", Priority.HIGH, {"p": 10})
        assert _matches("p", "eq", Priority.HIGH, {"p": "10"})  # str actual → int coerce

    def test_matches_ne_enum(self):
        assert _matches("s", "ne", Status.READY, {"s": "error"})
        assert not _matches("s", "ne", Status.READY, {"s": "ready"})

    def test_matches_gt_int_enum(self):
        assert _matches("p", "gt", Priority.LOW, {"p": 5})
        assert not _matches("p", "gt", Priority.HIGH, {"p": 5})

    def test_matches_in_enum(self):
        assert _matches("s", "in", [Status.READY, Status.ERROR], {"s": "ready"})
        assert not _matches("s", "in", [Status.READY, Status.ERROR], {"s": "generating"})

    def test_matches_contains_enum_in_list(self):
        assert _matches("tags", "contains", Status.READY, {"tags": ["ready", "foo"]})
        assert not _matches("tags", "contains", Status.READY, {"tags": ["error"]})

    def test_sql_param_enum(self):
        _, params = _sql("s", "eq", Status.READY)
        for v in params.values():
            assert v == "ready"

    def test_sql_param_int_enum(self):
        _, params = _sql("p", "eq", Priority.HIGH)
        for v in params.values():
            assert v == 10

    def test_mongo_filter_enum(self):
        f = _mongo("s", "eq", Status.READY)
        assert f == {"s": {"$eq": "ready"}}

    def test_mongo_filter_in_enum(self):
        f = _mongo("s", "in", [Status.READY, Status.ERROR])
        assert f == {"s": {"$in": ["ready", "error"]}}


# ══════════════════════════════════════════════════════════════════════════════
# 2. datetime / date edge cases
# ══════════════════════════════════════════════════════════════════════════════
class TestDatetimeEdgeCases:

    def test_datetime_eq_isoformat_string_actual(self):
        dt = datetime(2026, 1, 15, 10, 30, 0)
        assert _matches("t", "eq", dt, {"t": "2026-01-15T10:30:00"})

    def test_datetime_gt_isoformat_string_actual(self):
        dt = datetime(2026, 1, 1)
        assert _matches("t", "gt", dt, {"t": "2026-06-01T00:00:00"})
        assert not _matches("t", "gt", dt, {"t": "2025-06-01T00:00:00"})

    def test_datetime_lt_isoformat_string_actual(self):
        dt = datetime(2026, 6, 1)
        assert _matches("t", "lt", dt, {"t": "2026-01-01T00:00:00"})

    def test_date_eq_isoformat_string_actual(self):
        d = date(2026, 1, 15)
        # stored as datetime ISO → date should compare as midnight
        assert _matches("t", "eq", d, {"t": "2026-01-15T00:00:00"})

    def test_date_gt_isoformat_string_actual(self):
        d = date(2026, 1, 1)
        assert _matches("t", "gt", d, {"t": "2026-06-01T00:00:00"})

    def test_datetime_eq_unix_timestamp_actual(self):
        dt = datetime(2026, 1, 1)
        ts = dt.timestamp()
        assert _matches("t", "eq", dt, {"t": ts})

    def test_date_gt_date_same_type(self):
        """Both sides are date objects (rare for stored doc, but possible in-memory)."""
        assert _matches("t", "gt", date(2026, 1, 1), {"t": date(2026, 6, 1)})

    def test_datetime_in_with_iso_strings(self):
        dt1 = datetime(2026, 1, 1)
        dt2 = datetime(2026, 6, 1)
        assert _matches("t", "in", [dt1, dt2], {"t": "2026-06-01T00:00:00"})
        assert not _matches("t", "in", [dt1, dt2], {"t": "2026-03-01T00:00:00"})

    def test_date_in_with_iso_strings(self):
        d1 = date(2026, 1, 1)
        d2 = date(2026, 6, 1)
        assert _matches("t", "in", [d1, d2], {"t": "2026-06-01T00:00:00"})

    def test_datetime_ne_isoformat(self):
        dt = datetime(2026, 1, 1)
        assert _matches("t", "ne", dt, {"t": "2026-06-01T00:00:00"})
        assert not _matches("t", "ne", dt, {"t": "2026-01-01T00:00:00"})

    def test_datetime_contains_in_list_of_strings(self):
        """List contains check: actual is list of ISO strings, value is datetime."""
        dt = datetime(2026, 1, 1)
        assert _matches("ts", "contains", dt, {"ts": ["2026-01-01T00:00:00", "2026-06-01T00:00:00"]})
        assert not _matches("ts", "contains", dt, {"ts": ["2026-06-01T00:00:00"]})

    def test_datetime_contains_in_string(self):
        """String contains: actual is a long string, searching for datetime ISO substring."""
        dt = datetime(2026, 1, 15, 10, 30)
        assert _matches("text", "contains", dt, {"text": "Created at 2026-01-15T10:30:00 by admin"})

    def test_sql_param_datetime(self):
        dt = datetime(2026, 1, 15, 10, 30, 0)
        _, params = _sql("t", "eq", dt)
        for v in params.values():
            assert v == "2026-01-15T10:30:00"

    def test_sql_param_date(self):
        d = date(2026, 1, 15)
        _, params = _sql("t", "eq", d)
        for v in params.values():
            assert v == "2026-01-15"

    def test_mongo_datetime(self):
        dt = datetime(2026, 1, 15)
        f = _mongo("t", "gt", dt)
        assert f == {"t": {"$gt": "2026-01-15T00:00:00"}}

    def test_mongo_date(self):
        d = date(2026, 1, 15)
        f = _mongo("t", "eq", d)
        assert f == {"t": {"$eq": "2026-01-15"}}


# ══════════════════════════════════════════════════════════════════════════════
# 3. int / float / str coercion edge cases
# ══════════════════════════════════════════════════════════════════════════════
class TestNumericCoercion:

    def test_int_eq_str_actual(self):
        assert _matches("n", "eq", 42, {"n": "42"})

    def test_int_ne_str_actual(self):
        assert _matches("n", "ne", 42, {"n": "43"})
        assert not _matches("n", "ne", 42, {"n": "42"})

    def test_int_gt_str_actual(self):
        assert _matches("n", "gt", 10, {"n": "20"})
        assert not _matches("n", "gt", 10, {"n": "5"})

    def test_float_eq_str_actual(self):
        assert _matches("n", "eq", 3.14, {"n": "3.14"})

    def test_float_lt_str_actual(self):
        assert _matches("n", "lt", 10.0, {"n": "5.5"})

    def test_int_eq_float_actual(self):
        """int expected, float actual → both promoted to float."""
        assert _matches("n", "eq", 42, {"n": 42.0})

    def test_float_eq_int_actual(self):
        """float expected, int actual → int promoted to float."""
        assert _matches("n", "eq", 42.0, {"n": 42})

    def test_str_eq_int_actual(self):
        """str expected, int actual → int stringified."""
        assert _matches("n", "eq", "42", {"n": 42})

    def test_str_eq_float_actual(self):
        assert _matches("n", "eq", "3.14", {"n": 3.14})

    def test_bool_eq_int_actual(self):
        assert _matches("b", "eq", True, {"b": 1})
        assert _matches("b", "eq", False, {"b": 0})

    def test_bool_eq_str_actual(self):
        assert _matches("b", "eq", True, {"b": "true"})
        assert _matches("b", "eq", True, {"b": "1"})
        assert _matches("b", "eq", False, {"b": "false"})
        assert _matches("b", "eq", False, {"b": "0"})

    def test_int_gt_non_numeric_str(self):
        """str actual can't be parsed as int → should not crash, just return False."""
        assert not _matches("n", "gt", 10, {"n": "abc"})

    def test_float_gt_non_numeric_str(self):
        assert not _matches("n", "gt", 10.0, {"n": "abc"})

    def test_int_eq_none_actual(self):
        assert not _matches("n", "eq", 42, {"n": None})

    def test_none_eq_none(self):
        assert _matches("n", "eq", None, {"n": None})

    def test_none_ne_value(self):
        assert _matches("n", "ne", 42, {"n": None})

    def test_int_gt_none_actual(self):
        assert not _matches("n", "gt", 10, {"n": None})

    def test_int_in_with_str_actuals(self):
        """In list: actual is string, list elements are ints."""
        assert _matches("n", "in", [10, 20, 30], {"n": "20"})
        assert not _matches("n", "in", [10, 20, 30], {"n": "25"})

    def test_str_scientific_notation(self):
        """String '1e3' should match float 1000.0"""
        assert _matches("n", "eq", 1000, {"n": "1e3"})


# ══════════════════════════════════════════════════════════════════════════════
# 4. Structured BaseModel eq/ne via ORMFieldProxy
# ══════════════════════════════════════════════════════════════════════════════
class TestStructuredModelQuery:

    def _proxy(self, name: str, annotation):
        """Create proxy for a field with given annotation."""
        class _FakeFieldInfo:
            pass
        info = _FakeFieldInfo()
        info.annotation = annotation  # type: ignore
        return ORMFieldProxy(name, info)

    def test_eq_with_model_instance(self):
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == InnerModel(status=Status.READY, error_message=None)
        assert isinstance(expr, QueryExpression)
        # Should decompose into per-field expressions
        doc = {"inner": {"status": "ready", "error_message": None}}
        assert expr.matches(doc)

    def test_eq_with_dict(self):
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == {"status": "ready", "error_message": None}
        doc = {"inner": {"status": "ready", "error_message": None}}
        assert expr.matches(doc)

    def test_eq_with_empty_dict(self):
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == {}
        # {} → model_validate({}) → InnerModel() → defaults
        doc_default = {"inner": {"status": "ready", "error_message": None}}
        assert expr.matches(doc_default)

    def test_eq_with_json_string(self):
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == '{"status": "ready", "error_message": null}'
        doc = {"inner": {"status": "ready", "error_message": None}}
        assert expr.matches(doc)

    def test_eq_with_empty_json_string(self):
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == '{}'
        doc_default = {"inner": {"status": "ready", "error_message": None}}
        assert expr.matches(doc_default)

    def test_ne_with_model_instance(self):
        proxy = self._proxy("inner", InnerModel)
        expr = proxy != InnerModel(status=Status.ERROR)
        doc_ready = {"inner": {"status": "ready", "error_message": None}}
        assert expr.matches(doc_ready)

    def test_ne_with_json_string(self):
        proxy = self._proxy("inner", InnerModel)
        expr = proxy != '{"status": "error"}'
        doc_ready = {"inner": {"status": "ready", "error_message": None}}
        assert expr.matches(doc_ready)

    def test_eq_model_with_enum_field(self):
        """Enum within model should be properly extracted."""
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == InnerModel(status=Status.ERROR, error_message="fail")
        doc = {"inner": {"status": "error", "error_message": "fail"}}
        assert expr.matches(doc)
        doc2 = {"inner": {"status": "ready", "error_message": None}}
        assert not expr.matches(doc2)

    def test_nested_model_eq(self):
        proxy = self._proxy("data", OuterModel)
        expr = proxy == OuterModel(name="test", inner=InnerModel(status=Status.READY), score=9.5)
        doc = {"data": {"name": "test", "inner": {"status": "ready", "error_message": None}, "score": 9.5}}
        assert expr.matches(doc)

    def test_eq_invalid_json_string_falls_back(self):
        """Non-JSON string that can't be validated as model → raw string comparison."""
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == "not-json"
        # Should not crash; just won't match dict-based docs
        doc = {"inner": {"status": "ready", "error_message": None}}
        assert not expr.matches(doc)
        # But matches if actual is the same string
        assert expr.matches({"inner": "not-json"})

    def test_structured_sql_generation(self):
        """Structured eq should produce multiple SQL conditions."""
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == InnerModel(status=Status.READY)
        conds, params = expr.to_sql_conditions("sqlite")
        # Should have conditions for status and error_message
        assert len(conds) >= 2
        assert any("ready" in str(v) for v in params.values())

    def test_structured_mongo_filter(self):
        proxy = self._proxy("inner", InnerModel)
        expr = proxy == InnerModel(status=Status.READY)
        mongo = expr.to_mongo_filter()
        assert "$and" in mongo


# ══════════════════════════════════════════════════════════════════════════════
# 5. _sql_param_value edge cases
# ══════════════════════════════════════════════════════════════════════════════
class TestSQLParamValue:

    def test_dict_value_becomes_json_string(self):
        val = _FieldExpression._sql_param_value({"a": 1, "b": "c"})
        assert isinstance(val, str)
        import json
        parsed = json.loads(val)
        assert parsed == {"a": 1, "b": "c"}

    def test_list_value_becomes_json_string(self):
        val = _FieldExpression._sql_param_value([1, 2, 3])
        assert isinstance(val, str)
        import json
        assert json.loads(val) == [1, 2, 3]

    def test_basemodel_value_becomes_json_string(self):
        model = InnerModel(status=Status.READY)
        val = _FieldExpression._sql_param_value(model)
        assert isinstance(val, str)
        import json
        parsed = json.loads(val)
        assert parsed["status"] == "ready"

    def test_enum_value_extracted(self):
        assert _FieldExpression._sql_param_value(Status.READY) == "ready"
        assert _FieldExpression._sql_param_value(Priority.HIGH) == 10

    def test_none_passthrough(self):
        assert _FieldExpression._sql_param_value(None) is None

    def test_str_passthrough(self):
        assert _FieldExpression._sql_param_value("hello") == "hello"

    def test_int_passthrough(self):
        assert _FieldExpression._sql_param_value(42) == 42


# ══════════════════════════════════════════════════════════════════════════════
# 6. contains edge cases
# ══════════════════════════════════════════════════════════════════════════════
class TestContainsEdgeCases:

    def test_contains_str_in_str(self):
        assert _matches("t", "contains", "world", {"t": "hello world"})

    def test_contains_int_in_str(self):
        assert _matches("t", "contains", 42, {"t": "answer is 42"})

    def test_contains_in_list_same_type(self):
        assert _matches("tags", "contains", "foo", {"tags": ["foo", "bar"]})

    def test_contains_int_in_list_of_strings(self):
        """Coerce: looking for int 42 in list of strings ['42', '43']."""
        assert _matches("ns", "contains", 42, {"ns": ["42", "43"]})

    def test_contains_str_in_list_of_ints(self):
        """Coerce: looking for str '42' in list of ints."""
        assert _matches("ns", "contains", "42", {"ns": [42, 43]})

    def test_contains_datetime_in_list_of_strings(self):
        dt = datetime(2026, 1, 1)
        assert _matches("ts", "contains", dt, {"ts": ["2026-01-01T00:00:00"]})
        assert not _matches("ts", "contains", dt, {"ts": ["2026-06-01T00:00:00"]})

    def test_contains_enum_in_list(self):
        assert _matches("tags", "contains", Status.READY, {"tags": ["ready", "bar"]})

    def test_contains_enum_in_str(self):
        assert _matches("text", "contains", Status.READY, {"text": "status is ready"})

    def test_contains_on_none_actual(self):
        assert not _matches("t", "contains", "x", {"t": None})

    def test_contains_on_missing_field(self):
        assert not _matches("t", "contains", "x", {"other": "y"})


# ══════════════════════════════════════════════════════════════════════════════
# 7. wildcard / regex with unusual values
# ══════════════════════════════════════════════════════════════════════════════
class TestWildcardRegex:

    def test_wildcard_none_actual(self):
        assert not _matches("t", "wildcard", "hello*", {"t": None})
        # should match empty with *
        assert _matches("t", "wildcard", "*", {"t": None})

    def test_regex_none_actual(self):
        assert not _matches("t", "regex", "hello", {"t": None})

    def test_wildcard_int_actual(self):
        """wildcard coerces actual to str."""
        assert _matches("n", "wildcard", "4*", {"n": 42})

    def test_regex_int_actual(self):
        assert _matches("n", "regex", r"^\d+$", {"n": 42})


# ══════════════════════════════════════════════════════════════════════════════
# 8. Comparison type mismatch safety
# ══════════════════════════════════════════════════════════════════════════════
class TestTypeMismatchSafety:

    def test_gt_incompatible_types_no_crash(self):
        """If coercion fails, gt/lt/etc should return False, not raise."""
        assert not _matches("x", "gt", 10, {"x": {"nested": True}})
        assert not _matches("x", "lt", "abc", {"x": [1, 2, 3]})

    def test_eq_dict_vs_string(self):
        """Dict actual vs string expected → not equal."""
        assert not _matches("x", "eq", "hello", {"x": {"a": 1}})

    def test_eq_list_vs_int(self):
        assert not _matches("x", "eq", 42, {"x": [1, 2, 3]})

    def test_ne_incompatible_types(self):
        """Different types that can't be coerced → not equal → ne returns True."""
        assert _matches("x", "ne", 42, {"x": {"a": 1}})

    def test_gt_str_vs_str(self):
        """String comparison should work lexicographically."""
        assert _matches("s", "gt", "apple", {"s": "banana"})
        assert not _matches("s", "gt", "banana", {"s": "apple"})

    def test_missing_field_eq_none(self):
        assert _matches("missing", "eq", None, {"other": 1})

    def test_missing_field_ne_value(self):
        assert _matches("missing", "ne", 42, {"other": 1})

    def test_missing_field_gt(self):
        assert not _matches("missing", "gt", 10, {"other": 1})
