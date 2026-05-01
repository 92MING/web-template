import re
import hashlib
import numpy as np

from enum import Enum
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence
from redis.commands.search.field import NumericField, TagField, TextField, VectorField

from .query import QueryExpression, _AndExpression, _FieldExpression, _OrExpression

type RedisScalarKind = Literal["string", "numeric", "bool", "tag"]
type RedisTagScalar = str | int | float | bool | None
type RedisTextScalar = str | int | float

type _RedisSearchField = NumericField | TagField | TextField

class RedisSearchQueryError(ValueError):
    pass

@dataclass(frozen=True)
class RedisScalarFieldSpec:
    field_path: str
    kind: RedisScalarKind

@dataclass(frozen=True)
class RedisVectorFieldSpec:
    field_path: str
    dim: int
    metric_type: str
    algorithm: str = "FLAT"

def redis_field_slug(field_path: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_]+", "_", str(field_path or "").strip()) or "field"
    digest = hashlib.md5(str(field_path).encode("utf-8")).hexdigest()[:8]
    return f"{clean.lower()}_{digest}"

def redis_json_path(field_path: str) -> str:
    """Build ``$.field`` JSON path for flat (no envelope) document layout."""
    if field_path in {"id", "_id"}:
        return "$.id"
    parts = [part for part in str(field_path or "").split(".") if part]
    path = "$"
    for part in parts:
        if part.isdigit():
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path

def redis_array_json_path(field_path: str) -> str:
    """Build ``$.field[*]`` JSON path for flat document layout."""
    return f"{redis_json_path(field_path)}[*]"


def redis_payload_json_path(field_path: str) -> str:
    if field_path in {"id", "_id"}:
        return "$.payload.id"
    parts = [part for part in str(field_path or "").split(".") if part]
    path = "$.payload"
    for part in parts:
        if part.isdigit():
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def redis_payload_array_json_path(field_path: str) -> str:
    base = redis_payload_json_path(field_path)
    return f"{base}[*]"


def redis_scalar_text_alias(field_path: str) -> str:
    return f"txt_{redis_field_slug(field_path)}"


def redis_scalar_tag_alias(field_path: str) -> str:
    return f"tag_{redis_field_slug(field_path)}"


def redis_scalar_numeric_alias(field_path: str) -> str:
    return f"num_{redis_field_slug(field_path)}"


def redis_vector_alias(field_path: str) -> str:
    return f"vec_{redis_field_slug(field_path)}"


def redis_scalar_sort_alias(spec: RedisScalarFieldSpec) -> str:
    if spec.kind == "numeric":
        return redis_scalar_numeric_alias(spec.field_path)
    if spec.kind == "string":
        return redis_scalar_text_alias(spec.field_path)
    return redis_scalar_tag_alias(spec.field_path)


def build_redis_scalar_fields(spec: RedisScalarFieldSpec) -> list[_RedisSearchField]:
    json_path = redis_payload_json_path(spec.field_path)
    if spec.kind == "numeric":
        return [
            NumericField(json_path, as_name=redis_scalar_numeric_alias(spec.field_path), sortable=True),
        ]
    if spec.kind == "string":
        return [
            TextField(
                json_path,
                as_name=redis_scalar_text_alias(spec.field_path),
                sortable=True,
                no_stem=True,
                withsuffixtrie=True,
            ),
            TagField(
                json_path,
                as_name=redis_scalar_tag_alias(spec.field_path),
                separator="|",
            ),
        ]
    if spec.kind in {"bool", "tag"}:
        json_path = redis_payload_array_json_path(spec.field_path) if spec.kind == "tag" else json_path
        return [
            TagField(
                json_path,
                as_name=redis_scalar_tag_alias(spec.field_path),
                separator="|",
            ),
        ]
    raise RedisSearchQueryError(f"Unsupported Redis scalar field kind: {spec.kind}")


def build_redis_scalar_fields_flat(spec: RedisScalarFieldSpec) -> list[_RedisSearchField]:
    """Build RediSearch field definitions for flat (no envelope) document layout."""
    json_path = redis_json_path(spec.field_path)
    if spec.kind == "numeric":
        return [
            NumericField(json_path, as_name=redis_scalar_numeric_alias(spec.field_path), sortable=True),
        ]
    if spec.kind == "string":
        return [
            TextField(
                json_path,
                as_name=redis_scalar_text_alias(spec.field_path),
                sortable=True,
                no_stem=True,
                withsuffixtrie=True,
            ),
            TagField(
                json_path,
                as_name=redis_scalar_tag_alias(spec.field_path),
                separator="|",
            ),
        ]
    if spec.kind in {"bool", "tag"}:
        json_path = redis_array_json_path(spec.field_path) if spec.kind == "tag" else json_path
        return [
            TagField(
                json_path,
                as_name=redis_scalar_tag_alias(spec.field_path),
                separator="|",
            ),
        ]
    raise RedisSearchQueryError(f"Unsupported Redis scalar field kind: {spec.kind}")


def build_redis_vector_field(spec: RedisVectorFieldSpec) -> VectorField:
    return VectorField(
        redis_payload_json_path(spec.field_path),
        spec.algorithm,
        {
            "TYPE": "FLOAT32",
            "DIM": int(spec.dim),
            "DISTANCE_METRIC": str(spec.metric_type or "COSINE").upper(),
        },
        as_name=redis_vector_alias(spec.field_path),
    )


def escape_redis_tag_value(value: str | int | float | bool) -> str:
    text = str(value)
    escaped: list[str] = []
    for char in text:
        if char.isalnum() or char in {"_", "-"}:
            escaped.append(char)
        else:
            escaped.append("\\" + char)
    return "".join(escaped)


def escape_redis_text_literal(value: str | int | float) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace("'", "\\'")


def encode_redis_tag_value(value: str | int | float | bool | None) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _require_redis_tag_scalar(value: object, *, field_path: str, op: str) -> RedisTagScalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise RedisSearchQueryError(
        f"Redis predicate `{op}` for `{field_path}` requires a scalar value, got {type(value).__name__}."
    )


def _require_redis_text_scalar(value: object, *, field_path: str, op: str) -> RedisTextScalar:
    if isinstance(value, bool):
        raise RedisSearchQueryError(
            f"Redis predicate `{op}` for `{field_path}` requires a text-like scalar, got bool."
        )
    if isinstance(value, (str, int, float)):
        return value
    raise RedisSearchQueryError(
        f"Redis predicate `{op}` for `{field_path}` requires a text-like scalar, got {type(value).__name__}."
    )


def _compile_string_regex(pattern: str) -> tuple[str, str]:
    raw = str(pattern or "")
    exact = re.fullmatch(r"\^?([A-Za-z0-9_\- ]+)\$?", raw)
    if exact and raw.startswith("^") and raw.endswith("$"):
        return "eq", exact.group(1)
    prefix = re.fullmatch(r"\^([A-Za-z0-9_\- ]+)\.\*\$?", raw)
    if prefix:
        return "wildcard", prefix.group(1) + "*"
    suffix = re.fullmatch(r"\.\*([A-Za-z0-9_\- ]+)\$$", raw)
    if suffix:
        return "wildcard", "*" + suffix.group(1)
    contains = re.fullmatch(r"\.\*([A-Za-z0-9_\- ]+)\.\*", raw)
    if contains:
        return "wildcard", "*" + contains.group(1) + "*"
    plain = re.fullmatch(r"([A-Za-z0-9_\- ]+)", raw)
    if plain:
        return "wildcard", "*" + plain.group(1) + "*"
    raise RedisSearchQueryError(
        f"Redis full-text backend cannot push down regex pattern {pattern!r}; "
        "only exact / prefix / suffix / contains-style literal regex is supported."
    )


def _compile_scalar_clause(field_path: str, op: str, value: object, specs: Mapping[str, RedisScalarFieldSpec]) -> str:
    spec = specs.get(field_path)
    if spec is None:
        raise RedisSearchQueryError(f"Redis search field `{field_path}` is not indexed.")
    # Use the resolved DB-name path from the spec for alias resolution;
    # the incoming *field_path* is the Python name used only for dict lookup.
    field_path = spec.field_path
    # Extract Enum values before any processing
    while isinstance(value, Enum):
        value = value.value
    if isinstance(value, (list, tuple, set)):
        value = [item.value if isinstance(item, Enum) else item for item in value]
    if value is None:
        raise RedisSearchQueryError(f"Redis search does not support NULL predicate pushdown for `{field_path}`.")

    if spec.kind == "numeric":
        alias = redis_scalar_numeric_alias(field_path)
        if op in {"eq", "$eq"}:
            return f"@{alias}:[{value} {value}]"
        if op in {"ne", "$ne"}:
            return f"-@{alias}:[{value} {value}]"
        if op in {"gt", "$gt"}:
            return f"@{alias}:[({value} +inf]"
        if op in {"gte", "$gte"}:
            return f"@{alias}:[{value} +inf]"
        if op in {"lt", "$lt"}:
            return f"@{alias}:[-inf ({value}]"
        if op in {"lte", "$lte"}:
            return f"@{alias}:[-inf {value}]"
        if op in {"in", "$in"}:
            values = list(value or []) if isinstance(value, (list, tuple, set)) else None
            if values is None:
                raise RedisSearchQueryError(f"Redis $in for `{field_path}` requires a list-like value.")
            if not values:
                return "(@__never__:{__never__})"
            inner = "|".join(f"@{alias}:[{item} {item}]" for item in values)
            return f"({inner})"
        raise RedisSearchQueryError(f"Redis numeric predicate `{op}` is not supported for `{field_path}`.")

    if spec.kind == "string":
        tag_alias = redis_scalar_tag_alias(field_path)
        text_alias = redis_scalar_text_alias(field_path)
        if op in {"eq", "$eq"}:
            scalar = _require_redis_tag_scalar(value, field_path=field_path, op=op)
            return f"@{tag_alias}:{{{escape_redis_tag_value(encode_redis_tag_value(scalar))}}}"
        if op in {"ne", "$ne"}:
            scalar = _require_redis_tag_scalar(value, field_path=field_path, op=op)
            return f"-@{tag_alias}:{{{escape_redis_tag_value(encode_redis_tag_value(scalar))}}}"
        if op in {"in", "$in"}:
            values = list(value or []) if isinstance(value, (list, tuple, set)) else None
            if values is None:
                raise RedisSearchQueryError(f"Redis $in for `{field_path}` requires a list-like value.")
            if not values:
                return "(@__never__:{__never__})"
            encoded = "|".join(
                escape_redis_tag_value(
                    encode_redis_tag_value(_require_redis_tag_scalar(item, field_path=field_path, op=op))
                )
                for item in values
            )
            return f"@{tag_alias}:{{{encoded}}}"
        if op in {"contains", "$contains"}:
            literal = escape_redis_text_literal(_require_redis_text_scalar(value, field_path=field_path, op=op))
            return f"@{text_alias}:(w'*{literal}*')"
        if op in {"wildcard", "$wildcard"}:
            pattern = str(value or "").strip()
            if not pattern:
                raise RedisSearchQueryError(f"Redis wildcard pattern for `{field_path}` must not be empty.")
            if any(char in pattern for char in "[]{}"):
                raise RedisSearchQueryError(
                    f"Redis wildcard pushdown for `{field_path}` only supports simple '*' / '?' string patterns."
                )
            return f"@{text_alias}:(w'{escape_redis_text_literal(pattern)}')"
        if op in {"regex", "$regex"}:
            mode, literal = _compile_string_regex(str(value))
            if mode == "eq":
                return f"@{tag_alias}:{{{escape_redis_tag_value(literal)}}}"
            return f"@{text_alias}:(w'{escape_redis_text_literal(literal)}')"
        raise RedisSearchQueryError(f"Redis string predicate `{op}` is not supported for `{field_path}`.")

    alias = redis_scalar_tag_alias(field_path)
    if op in {"eq", "$eq", "contains", "$contains"}:
        scalar = _require_redis_tag_scalar(value, field_path=field_path, op=op)
        return f"@{alias}:{{{escape_redis_tag_value(encode_redis_tag_value(scalar))}}}"
    if op in {"ne", "$ne"}:
        scalar = _require_redis_tag_scalar(value, field_path=field_path, op=op)
        return f"-@{alias}:{{{escape_redis_tag_value(encode_redis_tag_value(scalar))}}}"
    if op in {"in", "$in"}:
        values = list(value or []) if isinstance(value, (list, tuple, set)) else None
        if values is None:
            raise RedisSearchQueryError(f"Redis $in for `{field_path}` requires a list-like value.")
        if not values:
            return "(@__never__:{__never__})"
        encoded = "|".join(
            escape_redis_tag_value(
                encode_redis_tag_value(_require_redis_tag_scalar(item, field_path=field_path, op=op))
            )
            for item in values
        )
        return f"@{alias}:{{{encoded}}}"
    raise RedisSearchQueryError(f"Redis tag predicate `{op}` is not supported for `{field_path}`.")


def _compile_query_expression(expr: QueryExpression, specs: Mapping[str, RedisScalarFieldSpec]) -> str:
    if isinstance(expr, _FieldExpression):
        return _compile_scalar_clause(expr.field, expr.op, expr.value, specs)
    if isinstance(expr, _AndExpression):
        left = _compile_query_expression(expr.left, specs)
        right = _compile_query_expression(expr.right, specs)
        return f"({left} {right})"
    if isinstance(expr, _OrExpression):
        left = _compile_query_expression(expr.left, specs)
        right = _compile_query_expression(expr.right, specs)
        return f"(({left})|({right}))"
    raise RedisSearchQueryError(f"Unsupported Redis query expression type: {type(expr).__name__}")


def compile_redis_query(query: QueryExpression | Mapping[str, object] | None, specs: Mapping[str, RedisScalarFieldSpec]) -> str:
    if query is None:
        return "*"
    if isinstance(query, Mapping) and not query:
        return "*"
    if isinstance(query, QueryExpression):
        expression = query
    elif isinstance(query, Mapping):
        from .client_base import _query_to_expression

        expression = _query_to_expression(query)
        if expression is None:
            raise RedisSearchQueryError("Redis query could not be normalized into a supported expression.")
    else:
        raise RedisSearchQueryError(f"Unsupported Redis query type: {type(query).__name__}")
    return _compile_query_expression(expression, specs)


def decode_redis_search_value(value: object) -> object:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if text[:1] in {'{', '[', '"'} or text in {"true", "false", "null"} or re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            try:
                import orjson
                return orjson.loads(text)
            except Exception:
                pass
        return value
    return value


def parse_ft_search_result(payload: object) -> tuple[int, list[dict[str, object]]]:
    if not isinstance(payload, (list, tuple)) or not payload:
        return 0, []
    total = int(payload[0] or 0)
    docs: list[dict[str, object]] = []
    index = 1
    while index < len(payload):
        raw_key = payload[index]
        raw_fields = payload[index + 1] if index + 1 < len(payload) else []
        key = raw_key.decode("utf-8", errors="replace") if isinstance(raw_key, bytes) else str(raw_key or "")
        field_map: dict[str, object] = {"__key": key}
        if isinstance(raw_fields, (list, tuple)):
            values = list(raw_fields)
            for offset in range(0, len(values), 2):
                if offset + 1 >= len(values):
                    break
                raw_name = values[offset]
                raw_value = values[offset + 1]
                name = raw_name.decode("utf-8", errors="replace") if isinstance(raw_name, bytes) else str(raw_name or "")
                field_map[name] = decode_redis_search_value(raw_value)
        docs.append(field_map)
        index += 2
    return total, docs


def vector_query_param_bytes(vector: Sequence[float]) -> bytes:
    return np.asarray(list(vector), dtype=np.float32).tobytes()
