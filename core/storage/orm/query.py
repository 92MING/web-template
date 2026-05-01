"""ORM Query Expression DSL for type-safe database queries.

Usage::

    class MyModel(ORMModel, collection_name="my_model"):
        name: str
        age: int

    # Build expressions via class-level field access
    results = [item async for item in MyModel.Search(
        (MyModel.age >= 18) & (MyModel.name == "Alice")
    )]
    result = await MyModel.SearchOne(MyModel.url_hash == some_hash)
"""
from __future__ import annotations

import fnmatch
import json as _json
import re as _re
import types

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Union, get_args, get_origin, Any, Iterable
from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
from pydantic.fields import FieldInfo as _PydanticFieldInfo

from .field_metadata import _translate_field_path

# ── Parameter name counter ────────────────────────────────────────────────────
class _ParamCounter:
    """Generates unique named SQL parameter names within a single query."""
    __slots__ = ("_n",)

    def __init__(self) -> None:
        self._n = 0

    def next(self, prefix: str = "_q_") -> str:
        name = f"{prefix}{self._n}"
        self._n += 1
        return name

# ── SQL column / JSON extraction helper ───────────────────────────────────────

def _q(col: str, dialect: str = "sqlite") -> str:
    """Quote a column/identifier for SQL."""
    d = str(dialect or "").lower()
    if d in {"mysql", "mariadb"}:
        return f"`{col}`"
    return f'"{col}"'


def _sql_json_extract(
    dialect: str,
    field: str,
    *,
    native_fields: set[str] | None = None,
    field_name_map: dict[str, str] | None = None,
) -> str:
    """Return a SQL expression that references *field*.

    In the current architecture every top-level field has its own column
    (no ``payload_json``).  For dotted paths the first segment is the
    column name and the remainder is a JSON path inside that column.
    """
    if field in ("id", "_id"):
        return f'd.{_q("id", dialect)}'
    db_field = _translate_field_path(field, field_name_map) if field_name_map else field

    # ── top-level field → direct column reference ──
    if "." not in field:
        return _q(db_field, dialect)

    # ── dotted path → json_extract on the first-segment column ──
    parts = db_field.split(".")
    col = _q(parts[0], dialect)
    rest = parts[1:]
    path = "$"
    for p in rest:
        path += f"[{p}]" if p.isdigit() else f".{p}"

    if dialect == "sqlite":
        return f"json_extract({col}, '{path}')"
    if dialect == "postgresql":
        expr = f"CAST({col} AS JSONB)"
        for p in rest[:-1]:
            expr = f"{expr}->{p}" if p.isdigit() else f"{expr}->'{p}'"
        last = rest[-1]
        return f"{expr}->>{last}" if last.isdigit() else f"{expr}->>'{last}'"
    if dialect in {"mysql", "mariadb"}:
        return f"JSON_UNQUOTE(JSON_EXTRACT({col}, '{path}'))"
    return f"json_extract({col}, '{path}')"


# ── FTS5 helpers ──────────────────────────────────────────────────────────────

def _fts5_escape_term(term: str) -> str:
    """Escape *term* for use inside an FTS5 MATCH double-quoted phrase.

    The only character that needs escaping inside ``"..."`` is the double-quote
    itself, which is doubled (``""``).
    """
    return term.replace('"', '""')


def _fts5_match_term(column: str, value: object) -> str:
    """Return a single column-scoped FTS5 MATCH fragment, e.g. ``name:"alice"``."""
    return f'{column}:"{_fts5_escape_term(str(value))}"'


# ── Base QueryExpression ──────────────────────────────────────────────────────
class QueryExpression:
    """Base class for all ORM query expressions.

    Supports ``&`` (AND) and ``|`` (OR) to combine expressions::

        expr = (MyModel.age >= 18) & (MyModel.name == "Alice")
        async for obj in MyModel.Search(expr):
            ...
    """

    def __and__(self, other: "QueryExpression") -> "_AndExpression":
        return _AndExpression(self, other)

    def __or__(self, other: "QueryExpression") -> "_OrExpression":
        return _OrExpression(self, other)

    def matches(self, doc: Mapping[str, object]) -> bool:
        """Evaluate this expression against an in-memory document dict."""
        raise NotImplementedError(type(self).__name__)

    def to_sql_conditions(
        self,
        dialect: str,
        *,
        counter: "_ParamCounter | None" = None,
        native_fields: set[str] | None = None,
        field_name_map: dict[str, str] | None = None,
        fts_table: str | None = None,
        fts_columns: set[str] | None = None,
    ) -> "tuple[list[str], dict[str, object]]":
        """Return ``(conditions, params)`` for a SQL WHERE clause."""
        raise NotImplementedError(type(self).__name__)

    def _fts_match_expr(
        self,
        *,
        fts_columns: set[str] | None = None,
        field_name_map: dict[str, str] | None = None,
    ) -> str | None:
        """Return an FTS5 MATCH expression if this entire sub-tree can be expressed
        as a single MATCH clause (all children are ``contains`` on FTS columns).
        Returns ``None`` when not fully FTS-eligible.
        """
        return None

    def to_mongo_filter(self, *, field_name_map: dict[str, str] | None = None) -> dict[str, object]:
        """Return a MongoDB-style filter dict."""
        raise NotImplementedError(type(self).__name__)

# ── Leaf expression ───────────────────────────────────────────────────────────
_OP_TO_MONGO: dict[str, str] = {
    "eq": "$eq", "ne": "$ne",
    "gt": "$gt", "gte": "$gte",
    "lt": "$lt", "lte": "$lte",
    "in": "$in",
}


def _unwrap_proxy_annotation(annotation: object) -> object:
    origin = get_origin(annotation)
    if origin not in {types.UnionType, Union}:
        return annotation
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if len(args) == 1:
        return args[0]
    return annotation


def _annotation_model_cls(annotation: object) -> type[BaseModel] | None:
    inner = _unwrap_proxy_annotation(annotation)
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        return inner
    return None


def _normalize_query_value(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, Enum):
        return _normalize_query_value(value.value)
    if isinstance(value, BaseModel):
        return {
            str(key): _normalize_query_value(item)
            for key, item in value.model_dump(mode="python").items()
        }
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_query_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_query_value(item) for item in value]
    return value


def _combine_expression_list(expressions: Sequence[QueryExpression], *, op: str) -> QueryExpression:
    if not expressions:
        raise ValueError("Structured ORM query expressions must contain at least one comparable field.")
    iterator = iter(expressions)
    combined = next(iterator)
    for expression in iterator:
        combined = combined & expression if op == "and" else combined | expression
    return combined


def _build_structured_query_expression(field_name: str, value: object, *, op: str) -> QueryExpression:
    normalized = _normalize_query_value(value)
    if isinstance(normalized, Mapping):
        expressions = [
            _build_structured_query_expression(f"{field_name}.{key}", item, op=op)
            for key, item in normalized.items()
        ]
        return _combine_expression_list(expressions, op="and" if op == "eq" else "or")
    if isinstance(normalized, list):
        expressions = [
            _build_structured_query_expression(f"{field_name}.{index}", item, op=op)
            for index, item in enumerate(normalized)
        ]
        return _combine_expression_list(expressions, op="and" if op == "eq" else "or")
    return _FieldExpression(field_name, op, normalized)


def _coerce_structured_query_value(model_cls: type[BaseModel], value: object) -> object:
    if isinstance(value, model_cls):
        model = value
    elif isinstance(value, BaseModel):
        model = model_cls.model_validate(value.model_dump(mode="python"))
    else:
        model = model_cls.model_validate(value)
    return model.model_dump(mode="python")


def _iter_query_values(value: object) -> list[object] | None:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
        return list(value)
    return None

class _FieldExpression(QueryExpression):
    """A single field comparison, e.g. ``MyModel.age > 18``."""

    __slots__ = ("field", "op", "value")

    def __init__(self, field: str, op: str, value: object) -> None:
        self.field = field
        self.op = op
        self.value = value

    @staticmethod
    def _coerce_comparable(actual: object, expected: object) -> tuple[object, object]:
        """Coerce *actual* (from stored doc) and *expected* (from query) to
        comparable types so that ``==``, ``<``, ``>`` etc. work correctly
        across JSON-serialized payloads and Python query values.

        The *expected* type is authoritative — *actual* is coerced to match
        whenever a lossless conversion exists.
        """
        if actual is None or expected is None:
            return actual, expected

        # ── extract Enum values before any type check ──
        if isinstance(expected, Enum):
            return _FieldExpression._coerce_comparable(actual, expected.value)
        if isinstance(actual, Enum):
            return _FieldExpression._coerce_comparable(actual.value, expected)

        if type(actual) is type(expected):
            return actual, expected

        # ── expected is datetime ──
        if isinstance(expected, datetime):
            if isinstance(actual, str):
                try:
                    return datetime.fromisoformat(actual), expected
                except (ValueError, TypeError):
                    return actual, expected.isoformat()
            if isinstance(actual, date):          # date → datetime(midnight)
                return datetime(actual.year, actual.month, actual.day), expected
            if isinstance(actual, (int, float)) and not isinstance(actual, bool):
                try:                              # interpret as unix-timestamp
                    return datetime.fromtimestamp(actual), expected
                except (ValueError, OSError, OverflowError):
                    pass
            return actual, expected

        # ── expected is date (not datetime) ──
        if isinstance(expected, date):
            if isinstance(actual, str):
                try:
                    parsed = datetime.fromisoformat(actual)
                    return parsed, datetime(expected.year, expected.month, expected.day)
                except (ValueError, TypeError):
                    return actual, expected.isoformat()
            if isinstance(actual, datetime):
                return actual, datetime(expected.year, expected.month, expected.day)
            return actual, expected

        # ── expected is bool (before int – bool is an int subclass) ──
        if isinstance(expected, bool):
            if isinstance(actual, (int, float)):
                return bool(actual), expected
            if isinstance(actual, str):
                low = actual.lower()
                if low in {"true", "1"}:
                    return True, expected
                if low in {"false", "0", ""}:
                    return False, expected
            return actual, expected

        # ── expected is int ──
        if isinstance(expected, int):
            if isinstance(actual, float):
                return actual, float(expected)
            if isinstance(actual, bool):
                return int(actual), expected
            if isinstance(actual, str):
                try:
                    if "." in actual or "e" in actual.lower():
                        return float(actual), float(expected)
                    return int(actual), expected
                except (ValueError, TypeError):
                    pass
            return actual, expected

        # ── expected is float ──
        if isinstance(expected, float):
            if isinstance(actual, (int, bool)):
                return float(actual), expected
            if isinstance(actual, str):
                try:
                    return float(actual), expected
                except (ValueError, TypeError):
                    pass
            return actual, expected

        # ── expected is str ──
        if isinstance(expected, str):
            if isinstance(actual, datetime):
                return actual.isoformat(), expected
            if isinstance(actual, date):
                return actual.isoformat(), expected
            if isinstance(actual, (int, float)) and not isinstance(actual, bool):
                return str(actual), expected
            if isinstance(actual, bool):
                return str(actual).lower(), expected
            return actual, expected

        return actual, expected

    @staticmethod
    def _sql_param_value(value: object) -> object:
        """Normalize a value before binding it as a SQL parameter."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Enum):
            return _FieldExpression._sql_param_value(value.value)
        if isinstance(value, BaseModel):
            return _json.dumps(value.model_dump(mode="json"), ensure_ascii=False)
        if isinstance(value, Mapping):
            return _json.dumps(dict(value), ensure_ascii=False, default=str)
        if isinstance(value, (list, tuple)):
            return _json.dumps(list(value), ensure_ascii=False, default=str)
        return value

    def matches(self, doc: Mapping[str, object]) -> bool:
        from ..base import _deep_get
        actual = _deep_get(doc, self.field)
        op = self.op

        # ``in`` needs per-element coercion
        if op == "in":
            for v in (self.value or []):    # type: ignore[union-attr]
                a, e = self._coerce_comparable(actual, v)
                if a == e:
                    return True
            return False

        actual, expected = self._coerce_comparable(actual, self.value)
        if op == "eq":      return actual == expected
        if op == "ne":      return actual != expected
        try:
            if op == "gt":      return actual is not None and actual > expected # type: ignore[operator]
            if op == "gte":     return actual is not None and actual >= expected    # type: ignore[operator]
            if op == "lt":      return actual is not None and actual < expected # type: ignore[operator]
            if op == "lte":     return actual is not None and actual <= expected    # type: ignore[operator]
        except TypeError:
            return False
        if op == "contains":
            search_val = self.value
            if isinstance(search_val, Enum):
                search_val = search_val.value
            if isinstance(actual, str):
                if isinstance(search_val, (datetime, date)):
                    return search_val.isoformat() in actual
                return str(search_val) in actual
            if isinstance(actual, (list, tuple)):
                for item in actual:
                    a, e = self._coerce_comparable(item, search_val)
                    if a == e:
                        return True
                return False
            return False
        if op == "wildcard":
            return fnmatch.fnmatch(str(actual or "").lower(), str(self.value or "").lower())
        if op == "regex":
            return bool(_re.search(str(self.value), str(actual or ""), _re.IGNORECASE))
        return False

    def to_sql_conditions(
        self,
        dialect: str,
        *,
        counter: "_ParamCounter | None" = None,
        native_fields: set[str] | None = None,
        field_name_map: dict[str, str] | None = None,
        fts_table: str | None = None,
        fts_columns: set[str] | None = None,
    ) -> "tuple[list[str], dict[str, object]]":
        if counter is None:
            counter = _ParamCounter()
        expr = _sql_json_extract(dialect, self.field, native_fields=native_fields, field_name_map=field_name_map)
        op = self.op

        # Resolve the DB column name for FTS column check
        _db_col = (_translate_field_path(self.field, field_name_map) if field_name_map else self.field) if "." not in self.field else None
        _is_fts = bool(fts_table and fts_columns and _db_col and _db_col in fts_columns)

        if op == "eq":
            if self.value is None:
                return [f"{expr} IS NULL"], {}
            p = counter.next()
            return [f"{expr} = :{p}"], {p: self._sql_param_value(self.value)}

        if op == "ne":
            if self.value is None:
                return [f"{expr} IS NOT NULL"], {}
            p = counter.next()
            return [f"{expr} != :{p}"], {p: self._sql_param_value(self.value)}

        if op in ("gt", "gte", "lt", "lte"):
            p = counter.next()
            sql_op = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            return [f"{expr} {sql_op} :{p}"], {p: self._sql_param_value(self.value)}

        if op == "in":
            vals = _iter_query_values(self.value)
            if vals is None:
                raise ValueError(f"_FieldExpression: `in` expects an iterable value, got {type(self.value).__name__}.")
            if not vals:
                return ["1 = 0"], {}
            params: dict[str, object] = {}
            phs: list[str] = []
            for v in vals:
                p = counter.next()
                params[p] = self._sql_param_value(v)
                phs.append(f":{p}")
            return [f"{expr} IN ({', '.join(phs)})"], params

        if op == "contains":
            p = counter.next()
            if dialect == "sqlite" and _is_fts and _db_col is not None:
                # FTS5 trigram MATCH (substring search)
                match_term = _fts5_match_term(_db_col, self.value)
                return [f'd."id" IN (SELECT _doc_id FROM {fts_table} WHERE {fts_table} MATCH :{p})'], {p: match_term}
            if dialect == "sqlite":
                return [f"instr(COALESCE({expr}, ''), :{p}) > 0"], {p: str(self.value)}
            if dialect == "postgresql":
                return [f"COALESCE({expr}, '') ILIKE :{p}"], {p: f"%{self.value}%"}
            return [f"COALESCE({expr}, '') LIKE :{p}"], {p: f"%{self.value}%"}

        if op == "wildcard":
            pattern = str(self.value or "")
            if dialect == "sqlite" and _is_fts and _db_col is not None and "[" not in pattern and "]" not in pattern:
                # Use LIKE on FTS5 trigram virtual table (supports full LIKE optimization)
                like = []
                for char in pattern:
                    if char == "*":
                        like.append("%")
                    elif char == "?":
                        like.append("_")
                    elif char in {"%", "_", "!"}:
                        like.append("!" + char)
                    else:
                        like.append(char)
                p = counter.next()
                return [
                    f'd."id" IN (SELECT _doc_id FROM {fts_table} WHERE {_q(_db_col)} LIKE :{p} ESCAPE \'!\')'
                ], {p: "".join(like)}
            if "[" not in pattern and "]" not in pattern:
                like = []
                for char in pattern:
                    if char == "*":
                        like.append("%")
                    elif char == "?":
                        like.append("_")
                    elif char in {"%", "_", "!"}:
                        like.append("!" + char)
                    else:
                        like.append(char)
                p = counter.next()
                if dialect == "postgresql":
                    return [f"COALESCE({expr}, '') ILIKE :{p} ESCAPE '!'"], {p: "".join(like)}
                return [f"COALESCE({expr}, '') LIKE :{p} ESCAPE '!'"], {p: "".join(like)}
            # Pattern has [...] character classes → convert to regex
            translated = fnmatch.translate(pattern)
            p = counter.next()
            if dialect == "sqlite":
                return [f"regexp(:{p}, COALESCE({expr}, ''))"], {p: translated}
            if dialect == "postgresql":
                return [f"COALESCE({expr}, '') ~* :{p}"], {p: translated}
            return [f"COALESCE({expr}, '') REGEXP :{p}"], {p: translated}

        if op == "regex":
            p = counter.next()
            if dialect == "sqlite":
                # regexp() provided by sqlite-regex extension (or Python fallback)
                return [f"regexp(:{p}, COALESCE({expr}, ''))"], {p: str(self.value)}
            if dialect == "postgresql":
                return [f"COALESCE({expr}, '') ~* :{p}"], {p: str(self.value)}
            return [f"COALESCE({expr}, '') REGEXP :{p}"], {p: str(self.value)}

        raise ValueError(f"_FieldExpression: unknown SQL op {self.op!r}")

    def _fts_match_expr(
        self,
        *,
        fts_columns: set[str] | None = None,
        field_name_map: dict[str, str] | None = None,
    ) -> str | None:
        if self.op != "contains":
            return None
        if "." in self.field:
            return None
        db_col = _translate_field_path(self.field, field_name_map) if field_name_map else self.field
        if not fts_columns or db_col not in fts_columns:
            return None
        return _fts5_match_term(db_col, self.value)

    @staticmethod
    def _mongo_scalar(value: object) -> object:
        """Normalize a value for MongoDB filter."""
        if isinstance(value, Enum):
            return _FieldExpression._mongo_scalar(value.value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    def to_mongo_filter(self, *, field_name_map: dict[str, str] | None = None) -> dict[str, object]:
        db_field = _translate_field_path(self.field, field_name_map) if field_name_map else self.field
        mongo_key = "_id" if self.field in ("id", "_id") else db_field
        if self.op in _OP_TO_MONGO:
            if self.op == "in":
                values = _iter_query_values(self.value)
                if values is None:
                    raise ValueError(f"_FieldExpression: `in` expects an iterable value, got {type(self.value).__name__}.")
                mongo_value = [self._mongo_scalar(v) for v in values]
            else:
                mongo_value = self._mongo_scalar(self.value)
            return {mongo_key: {_OP_TO_MONGO[self.op]: mongo_value}}
        if self.op == "contains":
            return {mongo_key: {"$regex": _re.escape(str(self.value)), "$options": "i"}}
        if self.op == "wildcard":
            return {mongo_key: {"$regex": fnmatch.translate(str(self.value)), "$options": "i"}}
        if self.op == "regex":
            return {mongo_key: {"$regex": str(self.value), "$options": "i"}}
        raise ValueError(f"_FieldExpression: unknown mongo op {self.op!r}")

# ── Compound expressions ──────────────────────────────────────────────────────
class _AndExpression(QueryExpression):
    """Conjunction (AND) of two expressions."""

    __slots__ = ("left", "right")

    def __init__(self, left: QueryExpression, right: QueryExpression) -> None:
        self.left = left
        self.right = right

    def matches(self, doc: Mapping[str, object]) -> bool:
        return self.left.matches(doc) and self.right.matches(doc)

    def to_sql_conditions(
        self,
        dialect: str,
        *,
        counter: "_ParamCounter | None" = None,
        native_fields: set[str] | None = None,
        field_name_map: dict[str, str] | None = None,
        fts_table: str | None = None,
        fts_columns: set[str] | None = None,
    ) -> "tuple[list[str], dict[str, object]]":
        if counter is None:
            counter = _ParamCounter()

        # ── attempt to merge all children into a single FTS MATCH ──
        if dialect == "sqlite" and fts_table and fts_columns:
            merged = self._fts_match_expr(fts_columns=fts_columns, field_name_map=field_name_map)
            if merged is not None:
                p = counter.next()
                return [f'd."id" IN (SELECT _doc_id FROM {fts_table} WHERE {fts_table} MATCH :{p})'], {p: merged}

        lc, lp = self.left.to_sql_conditions(
            dialect,
            counter=counter,
            native_fields=native_fields,
            field_name_map=field_name_map,
            fts_table=fts_table,
            fts_columns=fts_columns,
        )
        rc, rp = self.right.to_sql_conditions(
            dialect,
            counter=counter,
            native_fields=native_fields,
            field_name_map=field_name_map,
            fts_table=fts_table,
            fts_columns=fts_columns,
        )
        return lc + rc, {**lp, **rp}

    def _fts_match_expr(
        self,
        *,
        fts_columns: set[str] | None = None,
        field_name_map: dict[str, str] | None = None,
    ) -> str | None:
        left_m = self.left._fts_match_expr(fts_columns=fts_columns, field_name_map=field_name_map)
        right_m = self.right._fts_match_expr(fts_columns=fts_columns, field_name_map=field_name_map)
        if left_m is not None and right_m is not None:
            return f"({left_m} AND {right_m})"
        return None

    def to_mongo_filter(self, *, field_name_map: dict[str, str] | None = None) -> dict[str, object]:
        return {"$and": [self.left.to_mongo_filter(field_name_map=field_name_map), self.right.to_mongo_filter(field_name_map=field_name_map)]}

class _OrExpression(QueryExpression):
    """Disjunction (OR) of two expressions."""

    __slots__ = ("left", "right")

    def __init__(self, left: QueryExpression, right: QueryExpression) -> None:
        self.left = left
        self.right = right

    def matches(self, doc: Mapping[str, object]) -> bool:
        return self.left.matches(doc) or self.right.matches(doc)

    def to_sql_conditions(
        self,
        dialect: str,
        *,
        counter: "_ParamCounter | None" = None,
        native_fields: set[str] | None = None,
        field_name_map: dict[str, str] | None = None,
        fts_table: str | None = None,
        fts_columns: set[str] | None = None,
    ) -> "tuple[list[str], dict[str, object]]":
        if counter is None:
            counter = _ParamCounter()

        # ── attempt to merge all children into a single FTS MATCH ──
        if dialect == "sqlite" and fts_table and fts_columns:
            merged = self._fts_match_expr(fts_columns=fts_columns, field_name_map=field_name_map)
            if merged is not None:
                p = counter.next()
                return [f'd."id" IN (SELECT _doc_id FROM {fts_table} WHERE {fts_table} MATCH :{p})'], {p: merged}

        lc, lp = self.left.to_sql_conditions(
            dialect,
            counter=counter,
            native_fields=native_fields,
            field_name_map=field_name_map,
            fts_table=fts_table,
            fts_columns=fts_columns,
        )
        rc, rp = self.right.to_sql_conditions(
            dialect,
            counter=counter,
            native_fields=native_fields,
            field_name_map=field_name_map,
            fts_table=fts_table,
            fts_columns=fts_columns,
        )
        left_sql  = " AND ".join(lc) if lc else "1=1"
        right_sql = " AND ".join(rc) if rc else "1=1"
        return [f"({left_sql} OR {right_sql})"], {**lp, **rp}

    def _fts_match_expr(
        self,
        *,
        fts_columns: set[str] | None = None,
        field_name_map: dict[str, str] | None = None,
    ) -> str | None:
        left_m = self.left._fts_match_expr(fts_columns=fts_columns, field_name_map=field_name_map)
        right_m = self.right._fts_match_expr(fts_columns=fts_columns, field_name_map=field_name_map)
        if left_m is not None and right_m is not None:
            return f"({left_m} OR {right_m})"
        return None

    def to_mongo_filter(self, *, field_name_map: dict[str, str] | None = None) -> dict[str, object]:
        return {"$or": [self.left.to_mongo_filter(field_name_map=field_name_map), self.right.to_mongo_filter(field_name_map=field_name_map)]}

# ── ORMFieldProxy ─────────────────────────────────────────────────────────────
class ORMFieldProxy:
    """Returned when accessing model fields at the class level.

    Supports all comparison operators to produce :class:`QueryExpression`
    objects suitable for passing to ``Search()``, ``SearchOne()``, etc.::

        expr = (MyModel.score >= 90) | (MyModel.level == "expert")
        async for obj in MyModel.Search(expr):
            ...

    Methods
    -------
    regex(pattern)
        Match field against a regex *pattern* (case-insensitive).
    wildcard(pattern)
        Glob-style wildcard match supporting ``*`` and ``?``.
    contains(value)
        Check if field contains *value* as a substring or list element.
    in_(values)
        Check if field value is one of *values*.
    """

    __slots__ = ("_field_name", "_field_info")

    def __init__(self, field_name: str, field_info: '_PydanticFieldInfo') -> None:
        object.__setattr__(self, "_field_name", field_name)
        object.__setattr__(self, "_field_info", field_info)

    @property
    def field_name(self) -> str:
        return object.__getattribute__(self, "_field_name")

    @property
    def field_info(self) -> '_PydanticFieldInfo':
        return object.__getattribute__(self, "_field_info")

    @property
    def model_cls(self) -> type[BaseModel] | None:
        return _annotation_model_cls(getattr(self.field_info, "annotation", None))

    def _make(self, op: str, value: object) -> QueryExpression:
        field_name = object.__getattribute__(self, "_field_name")
        if op in {"eq", "ne"} and value is not None:
            model_cls = self.model_cls
            if model_cls is not None:
                if isinstance(value, (BaseModel, Mapping)):
                    normalized = _coerce_structured_query_value(model_cls, value)
                    return _build_structured_query_expression(field_name, normalized, op=op)
                if isinstance(value, str):
                    try:
                        parsed = _json.loads(value)
                        if isinstance(parsed, Mapping):
                            normalized = _coerce_structured_query_value(model_cls, parsed)
                            return _build_structured_query_expression(field_name, normalized, op=op)
                    except (ValueError, TypeError, _json.JSONDecodeError):
                        pass
                    try:
                        normalized = _coerce_structured_query_value(model_cls, value)
                        return _build_structured_query_expression(field_name, normalized, op=op)
                    except Exception:
                        pass
        return _FieldExpression(field_name, op, _normalize_query_value(value))

    def __getattr__(self, name: str) -> ORMFieldProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        model_cls = self.model_cls
        if model_cls is None:
            raise AttributeError(
                f"Field proxy {self.field_name!r} does not expose nested attribute {name!r}."
            )
        fields = getattr(model_cls, "model_fields", {}) or {}
        if name not in fields:
            raise AttributeError(
                f"Nested model {model_cls.__name__!r} has no field {name!r}."
            )
        return ORMFieldProxy(f"{self.field_name}.{name}", fields[name])

    # ── Comparison operators ──────────────────────────────────────────────────
    def __eq__(self, value: object) -> QueryExpression:       return self._make("eq",  value)   # type: ignore[override]
    def __ne__(self, value: object) -> QueryExpression:       return self._make("ne",  value)   # type: ignore[override]
    def __gt__(self, value: object) -> QueryExpression:       return self._make("gt",  value)
    def __ge__(self, value: object) -> QueryExpression:       return self._make("gte", value)
    def __lt__(self, value: object) -> QueryExpression:       return self._make("lt",  value)
    def __le__(self, value: object) -> QueryExpression:       return self._make("lte", value)
    def __contains__(self, value: object) -> QueryExpression: return self._make("contains", value)  # type: ignore[override]

    def __getitem__(self, value: object) -> QueryExpression:
        """``model.field[val]`` → IN query."""
        vals = list(value) if isinstance(value, (list, tuple)) else [value]
        return self._make("in", vals)

    # ── Convenience methods ────────────────────────────────────────────────────
    def regex(self, pattern: str) -> QueryExpression:
        """Match field against *pattern* (regular expression, case-insensitive)."""
        return self._make("regex", pattern)

    def wildcard(self, pattern: str) -> QueryExpression:
        """Match field against a glob-like wildcard pattern."""
        return self._make("wildcard", pattern)

    def contains(self, value: object) -> QueryExpression:
        """Check if field contains *value* as a substring or list element."""
        return self._make("contains", value)

    def in_(self, values: Iterable|str|bytes) -> QueryExpression:
        """Check if field value is one of *values*."""
        vs = (
            list(values)
            if hasattr(values, "__iter__") and not isinstance(values, (str, bytes))
            else [values]
        )
        return self._make("in", vs)

    def __hash__(self) -> int:
        return hash(object.__getattribute__(self, "_field_name"))

    def __repr__(self) -> str:
        fname = object.__getattribute__(self, "_field_name")
        return f"ORMFieldProxy({fname!r})"

# ── _ORMMetaModel ─────────────────────────────────────────────────────────────
class _ORMMetaModel(ModelMetaclass):
    """Metaclass for :class:`ORMModel` enabling class-level field access.

    When a field name is accessed at the class level (e.g. ``MyModel.name``),
    returns an :class:`ORMFieldProxy` instead of raising
    :class:`AttributeError`, enabling query-expression syntax::

        result = await MyModel.SearchOne(MyModel.url_hash == url_hash)
    """

    def __getattr__(cls, name: str) -> ORMFieldProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        # Only return ORMFieldProxy *after* Pydantic has fully initialised the
        # class.  During class creation, Pydantic internally calls
        # ``getattr(base_cls, field_name)`` when resolving inherited field
        # defaults.  Returning an ORMFieldProxy at that point would corrupt
        # Pydantic's schema: the proxy would be stored as the field's default
        # value (overriding ``default_factory``), so every instance would have
        # ``item.id == ORMFieldProxy('id')`` instead of a real ObjectId.
        if not cls.__dict__.get("__pydantic_complete__", False):
            raise AttributeError(name)
        try:
            fields: dict[str, _PydanticFieldInfo] = cls.model_fields  # type: ignore[attr-defined]
        except AttributeError:
            raise AttributeError(
                f"type object {cls.__name__!r} has no attribute {name!r}"
            )
        if name in fields:
            return ORMFieldProxy(name, fields[name])
        raise AttributeError(
            f"type object {cls.__name__!r} has no attribute {name!r}"
        )

__all__ = [
    "ORMFieldProxy",
    "QueryExpression",
]
