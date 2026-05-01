import annotated_types as _annotated_types
import json as _json
import logging as _logging
import sqlite3 as _sqlite3
import types as _types

from datetime import date, datetime
from enum import Enum
from dataclasses import dataclass
from functools import cache as _cache
from typing import Final, Literal, Mapping, Sequence, Union, get_args, get_origin

from pydantic import BaseModel as _BaseModel

from .field_metadata import ORMFieldInfo, _is_storage_excluded, resolve_db_field_name
from ..base import _unwrap_optional, _get_foreign_annotation_info
from ..base import ObjectId as _ObjectId

_schema_logger = _logging.getLogger(__name__)


SQL_DEFAULT_VARCHAR_LENGTH: Final[int] = 2048

type NativeScalarKind = Literal["bool", "int", "float", "str", "date", "datetime"]
type FieldKind = Literal[
    "bool", "int", "float", "str", "date", "datetime",
    "json", "blob_single", "blob_union", "file_id",
    "foreign_single", "foreign_list",
]

# ── ORMFieldSpec (replaces ORMNativeFieldSpec) ────────────────────────────────

@dataclass(frozen=True, slots=True)
class ORMFieldSpec:
    """Complete column specification for one model field."""
    field_name: str
    column_name: str          # = resolve_db_field_name() result, NO f_ prefix
    kind: FieldKind
    nullable: bool
    index: bool | None        # None = align with DB; True = ensure; False = ensure dropped
    max_length: int | None = None       # str kind only
    media_type: str | None = None       # blob_single: fixed type ("image","audio",...); blob_union: None
    foreign_model: type | None = None   # foreign_single/foreign_list: target ORMModel class





# ── JSONB support detection ──────────────────────────────────────────────────

@_cache
def _sqlite_supports_jsonb() -> bool:
    v = tuple(int(x) for x in _sqlite3.sqlite_version.split("."))
    return v >= (3, 45, 0)


def _json_column_type(dialect: str) -> str:
    d = str(dialect or "").lower()
    if d == "sqlite":
        return "JSONB" if _sqlite_supports_jsonb() else "TEXT"
    if d == "postgresql":
        return "JSONB"
    if d in {"mysql", "mariadb"}:
        return "JSON"
    return "TEXT"


def _blob_column_type(dialect: str) -> str:
    d = str(dialect or "").lower()
    if d == "sqlite":
        return "BLOB"
    if d == "postgresql":
        return "BYTEA"
    if d in {"mysql", "mariadb"}:
        return "LONGBLOB"
    return "BLOB"


# ── Media type helpers ───────────────────────────────────────────────────────

def _is_file_type(cls: object) -> bool:
    """Return True if *cls* is a concrete File protocol implementation (Image, Audio, etc.)."""
    if not isinstance(cls, type):
        return False
    # Check for the canonical attributes that all file types share.
    return (
        hasattr(cls, "Type")
        and hasattr(cls, "TypeNames")
        and hasattr(cls, "to_bytes")
        and hasattr(cls, "to_base64")
    )


def _is_single_media_type(annotation: object) -> bool:
    """True for a single concrete media class (Image, Audio, Video, PDF, etc.)."""
    return _is_file_type(annotation)


def _is_media_union(annotation: object) -> bool:
    """True for a union of multiple media types (Image|Audio) or bare File protocol."""
    try:
        from ...utils.data_structs.files.base import File
        if annotation is File:
            return True
    except ImportError:
        pass
    origin = get_origin(annotation)
    if origin in {Union, _types.UnionType}:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) >= 2 and all(_is_file_type(a) for a in args):
            return True
    return False


def _is_list_of_orm_model(annotation: object) -> bool:
    """True for list[SomeORMModel] or Sequence[SomeORMModel]."""
    from .model import ORMModel as _ORM
    origin = get_origin(annotation)
    if origin in {list, Sequence}:
        args = get_args(annotation)
        if args and len(args) == 1 and isinstance(args[0], type) and issubclass(args[0], _ORM):
            return True
    return False


def _single_media_type_name(annotation: object) -> str | None:
    """Get the canonical type name for a single media class."""
    if _is_file_type(annotation):
        return str(getattr(annotation, "Type", annotation.__name__)).lower()
    return None


# ── Kind inference helpers ───────────────────────────────────────────────────

def _literal_field_kind(annotation: object) -> tuple[NativeScalarKind | None, int | None]:
    args = list(get_args(annotation))
    if not args:
        return None, None
    if all(isinstance(item, bool) for item in args):
        return "bool", None
    if all(isinstance(item, int) and not isinstance(item, bool) for item in args):
        return "int", None
    if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in args):
        return "float", None
    if all(isinstance(item, str) for item in args):
        return "str", max(len(item) for item in args) if args else None
    return None, None

def _enum_field_kind(enum_cls: type[Enum]) -> tuple[NativeScalarKind, int | None]:
    values = [item.value for item in enum_cls]
    if all(isinstance(item, bool) for item in values):
        return "bool", None
    if all(isinstance(item, int) and not isinstance(item, bool) for item in values):
        return "int", None
    if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in values):
        return "float", None
    stringified = [str(item) for item in values]
    return "str", max((len(item) for item in stringified), default=None)

def _annotation_native_kind(annotation: object) -> tuple[NativeScalarKind | None, bool, int | None]:
    """Infer a native scalar kind from a type annotation.

    Returns (kind, nullable, inferred_max_length).  kind is None when the
    annotation is not a native scalar type.
    """
    inner, nullable = _unwrap_optional(annotation)
    origin = get_origin(inner)

    if inner is bool:
        return "bool", nullable, None
    if inner is int:
        return "int", nullable, None
    if inner is float:
        return "float", nullable, None
    if inner is _ObjectId:
        return "str", nullable, 24
    if inner is str:
        return "str", nullable, None
    if inner is datetime:
        return "datetime", nullable, None
    if inner is date:
        return "date", nullable, None
    if origin is Literal:
        kind, max_length = _literal_field_kind(inner)
        return kind, nullable, max_length
    if isinstance(inner, type) and issubclass(inner, Enum):
        kind, max_length = _enum_field_kind(inner)
        return kind, nullable, max_length
    if origin in {Union, _types.UnionType}:
        # A union of scalar members (e.g. ``ObjectId | str``) collapses to a
        # single native kind when every member maps to the same kind. ObjectId
        # is stored as its 24-char hex string in SQL, so ``ObjectId | str`` is
        # equivalent to ``str`` at the column level.
        member_kinds: list[tuple[NativeScalarKind, int | None]] = []
        for arg in get_args(inner):
            if arg is type(None):
                continue
            member_kind, _member_nullable, member_max = _annotation_native_kind(arg)
            if member_kind is None:
                return None, nullable, None
            member_kinds.append((member_kind, member_max))
        if member_kinds:
            kinds = {k for k, _ in member_kinds}
            if len(kinds) == 1:
                kind = next(iter(kinds))
                lengths = [m for _, m in member_kinds if m is not None]
                # When members disagree on max_length (e.g. ObjectId=24 vs
                # bare str=None), drop the cap so the longer member fits.
                max_length = max(lengths) if lengths and len(lengths) == len(member_kinds) else None
                return kind, nullable, max_length
    return None, nullable, None


def _detect_field_kind(
    field_name: str,
    field_info: object,
    annotation: object,
) -> tuple[FieldKind, bool, int | None, str | None, type | None]:
    """Detect the FieldKind for a model field.

    Returns (kind, nullable, max_length, media_type, foreign_model_cls).
    """
    inner, nullable = _unwrap_optional(annotation)
    is_orm_field = isinstance(field_info, ORMFieldInfo)
    is_foreign = is_orm_field and getattr(field_info, "foreign_model", False)

    # ── foreign_model=True special handling ──
    if is_foreign:
        # media type + foreign_model → file_id (stored as JSON, data in ObjectStore)
        if _is_single_media_type(inner) or _is_media_union(inner):
            return "file_id", nullable, None, None, None
        # list[ORMModel] → foreign_list
        if _is_list_of_orm_model(inner):
            from .model import ORMModel as _ORM
            args = get_args(inner)
            target = args[0] if args else None
            return "foreign_list", nullable, None, None, target
        # single ORMModel → foreign_single
        target_cls, _ = _get_foreign_annotation_info(annotation)
        if target_cls is not None:
            return "foreign_single", nullable, None, None, target_cls

    # ── scalar types ──
    scalar_kind, scalar_nullable, scalar_max_length = _annotation_native_kind(annotation)
    if scalar_kind is not None:
        return scalar_kind, scalar_nullable, scalar_max_length, None, None

    # ── media types (not foreign_model) ──
    if _is_single_media_type(inner):
        return "blob_single", nullable, None, _single_media_type_name(inner), None
    if _is_media_union(inner):
        return "blob_union", nullable, None, None, None

    # ── everything else → json ──
    return "json", nullable, None, None, None


# ── extract_field_specs (replaces extract_native_field_specs) ─────────────────

_SYSTEM_FIELDS = frozenset({"id", "_id"})

# Kinds that cannot have B-tree indexes
_NON_INDEXABLE_KINDS: frozenset[FieldKind] = frozenset({
    "json", "blob_single", "blob_union", "file_id", "foreign_list",
})


def extract_field_specs(model_cls: type[_BaseModel]) -> dict[str, ORMFieldSpec]:
    """Extract an ORMFieldSpec for every persistable field in *model_cls*.

    This replaces the old ``extract_native_field_specs()`` which only covered
    scalar types.  The new version covers ALL field kinds.
    """
    specs: dict[str, ORMFieldSpec] = {}
    alias_gen = None
    config = getattr(model_cls, "model_config", None)
    if config and isinstance(config, dict):
        alias_gen = config.get("alias_generator")

    for field_name, field_info in model_cls.model_fields.items():
        if field_name in _SYSTEM_FIELDS:
            continue
        if field_name.startswith("_"):
            continue
        if _is_storage_excluded(field_info):
            continue

        kind, nullable, inferred_max_length, media_type, foreign_cls = _detect_field_kind(
            field_name, field_info, field_info.annotation,
        )

        declared_index: bool | None = None  # default: align with DB
        if isinstance(field_info, ORMFieldInfo):
            declared_index = field_info.index  # None / True / False

        # Warn and suppress index for non-indexable kinds
        if declared_index is True and kind in _NON_INDEXABLE_KINDS:
            _schema_logger.warning(
                "Field `%s` (kind=%s) cannot have a B-tree index; "
                "index=True will be ignored.",
                field_name, kind,
            )
            declared_index = False

        max_length = None
        if kind == "str":
            raw_declared = None
            for m in getattr(field_info, "metadata", ()):
                if isinstance(m, _annotated_types.MaxLen):
                    raw_declared = m.max_length
                    break
            if raw_declared is not None:
                max_length = int(raw_declared)
            elif inferred_max_length is not None:
                max_length = int(inferred_max_length)
            else:
                max_length = SQL_DEFAULT_VARCHAR_LENGTH

        db_name = resolve_db_field_name(field_name, field_info, alias_gen)
        specs[field_name] = ORMFieldSpec(
            field_name=field_name,
            column_name=db_name,  # NO f_ prefix
            kind=kind,
            nullable=bool(nullable),
            index=declared_index,
            max_length=max_length,
            media_type=media_type,
            foreign_model=foreign_cls,
        )
    return specs


# ── sql_column_type ──────────────────────────────────────────────────────────

def sql_column_type(spec: ORMFieldSpec, dialect: str) -> str:
    d = str(dialect or "").lower()
    k = spec.kind

    if k == "bool":
        return "BOOLEAN" if d in {"postgresql", "mysql", "mariadb"} else "INTEGER"
    if k == "int":
        return "INTEGER" if d == "sqlite" else "BIGINT"
    if k == "float":
        if d == "postgresql":
            return "DOUBLE PRECISION"
        if d in {"mysql", "mariadb"}:
            return "DOUBLE"
        return "REAL"
    if k == "datetime":
        if d == "sqlite":
            return "DATETIME"
        if d == "postgresql":
            return "TIMESTAMP"
        if d in {"mysql", "mariadb"}:
            return "DATETIME(6)"
        return "DATETIME"
    if k == "date":
        return "DATE"
    if k == "str":
        max_length = int(spec.max_length or SQL_DEFAULT_VARCHAR_LENGTH)
        return "TEXT" if d == "sqlite" else f"VARCHAR({max_length})"
    if k in {"json", "file_id", "foreign_list"}:
        return _json_column_type(d)
    if k in {"blob_single", "blob_union"}:
        return _blob_column_type(d)
    if k == "foreign_single":
        return "TEXT" if d == "sqlite" else "VARCHAR(64)"
    return "TEXT"


# ── serialize / deserialize ──────────────────────────────────────────────────

def serialize_field_value(spec: ORMFieldSpec, value: object) -> object:
    """Serialize a Python field value to a DB-storable value."""
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value

    k = spec.kind

    if k == "bool":
        if isinstance(value, bool):
            return value
        try:
            return bool(value)
        except Exception:
            return None

    if k == "int":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        try:
            return int(value)
        except Exception:
            return None

    if k == "float":
        if isinstance(value, float):
            return value
        try:
            return float(value)
        except Exception:
            return None

    if k == "datetime":
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    if k == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    if k == "str":
        if isinstance(value, str):
            s = value
        elif isinstance(value, (dict, list, tuple)):
            try:
                s = _json.dumps(value, ensure_ascii=False)
            except Exception:
                s = str(value)
        else:
            s = str(value)
        if spec.max_length is not None and len(s) > spec.max_length:
            _schema_logger.warning(
                "Column `%s` (field `%s`) value exceeds max_length=%d (%d chars); truncating.",
                spec.column_name, spec.field_name, spec.max_length, len(s),
            )
            s = s[: spec.max_length]
        return s

    if k == "json":
        if isinstance(value, _BaseModel):
            return _json.dumps(value.model_dump(mode="json"), ensure_ascii=False)
        if isinstance(value, (dict, list, tuple)):
            return _json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            try:
                _json.loads(value)
            except Exception:
                return _json.dumps(value, ensure_ascii=False)
            return value
        return _json.dumps(value, ensure_ascii=False, default=str)

    if k in {"blob_single", "blob_union"}:
        if isinstance(value, bytes):
            return value
        if hasattr(value, "to_bytes"):
            return bytes(value.to_bytes())
        return bytes(value)

    if k == "file_id":
        if isinstance(value, _BaseModel):
            return _json.dumps(value.model_dump(mode="json"), ensure_ascii=False)
        if isinstance(value, dict):
            return _json.dumps(value, ensure_ascii=False)
        return str(value)

    if k == "foreign_single":
        if hasattr(value, "id"):
            return str(value.id)
        return str(value)

    if k == "foreign_list":
        if isinstance(value, (list, tuple)):
            ids = []
            for item in value:
                if hasattr(item, "id"):
                    ids.append(str(item.id))
                else:
                    ids.append(str(item))
            return _json.dumps(ids, ensure_ascii=False)
        if isinstance(value, str):
            return value  # assume already JSON
        return _json.dumps(value, ensure_ascii=False, default=str)

    return str(value)


def deserialize_field_value(spec: ORMFieldSpec, db_value: object, *, media_type: str | None = None) -> object:
    """Deserialize a DB-stored value back to a Python value."""
    if db_value is None:
        return None

    k = spec.kind

    if k == "bool":
        return bool(db_value)

    if k == "int":
        return int(db_value) if not isinstance(db_value, int) else db_value

    if k == "float":
        return float(db_value) if not isinstance(db_value, float) else db_value

    if k in {"str", "date", "datetime"}:
        # Return as-is; Pydantic model_validate will handle date/datetime parsing.
        return db_value

    if k == "json":
        if isinstance(db_value, (str, bytes, bytearray)):
            try:
                return _json.loads(db_value)
            except Exception:
                return db_value
        return db_value  # already parsed (e.g., JSONB in PostgreSQL)

    if k == "blob_single":
        if not isinstance(db_value, (bytes, bytearray)):
            return db_value
        type_name = spec.media_type
        if type_name:
            try:
                from ...utils.data_structs.files.base import _match_file_class_by_type_name
                file_cls = _match_file_class_by_type_name(type_name)
                if file_cls is not None:
                    return file_cls(bytes(db_value))
            except ImportError:
                pass
        return bytes(db_value)

    if k == "blob_union":
        if not isinstance(db_value, (bytes, bytearray)):
            return db_value
        resolved_type = media_type or spec.media_type
        if resolved_type:
            try:
                from ...utils.data_structs.files.base import _match_file_class_by_type_name
                file_cls = _match_file_class_by_type_name(resolved_type)
                if file_cls is not None:
                    return file_cls(bytes(db_value))
            except ImportError:
                pass
        return bytes(db_value)

    if k == "file_id":
        raw = db_value
        if isinstance(raw, (str, bytes, bytearray)):
            raw = _json.loads(raw)
        if isinstance(raw, dict):
            try:
                from ...utils.data_structs.files.base import FileID
                return FileID.model_validate(raw)
            except ImportError:
                return raw
        return raw

    if k == "foreign_single":
        return str(db_value) if db_value is not None else None

    if k == "foreign_list":
        if isinstance(db_value, (str, bytes, bytearray)):
            return _json.loads(db_value)
        return db_value

    return db_value


def native_field_names(specs: Mapping[str, ORMFieldSpec] | None) -> set[str]:
    return set(specs or {})


# ── column rename detection ─────────────────────────────────────────────

_SYSTEM_COLUMNS = frozenset({
    "id", "_id", "payload_json", "expire_at", "size",
    "accessed_at",
})


def _sql_type_category(db_type: str) -> str:
    """Normalise a raw SQL column type to a broad category for comparison."""
    t = str(db_type or "").upper().split("(")[0].strip()
    if t in {"INTEGER", "BIGINT", "INT", "SMALLINT", "TINYINT", "INT8", "INT4", "INT2"}:
        return "int"
    if t in {"REAL", "DOUBLE", "DOUBLE PRECISION", "FLOAT", "NUMERIC", "DECIMAL"}:
        return "float"
    if t in {"BOOLEAN", "BOOL"}:
        return "bool"
    if t in {"TEXT", "VARCHAR", "CHAR", "CHARACTER VARYING", "BPCHAR", "NVARCHAR"}:
        return "str"
    if t in {"DATETIME", "TIMESTAMP", "TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP WITH TIME ZONE"}:
        return "datetime"
    if t in {"DATE"}:
        return "date"
    if t in {"BLOB", "BYTEA", "LONGBLOB"}:
        return "blob"
    if t in {"JSON", "JSONB"}:
        return "json"
    return t  # unknown


def detect_column_renames(
    existing_columns: Mapping[str, str],
    specs: Mapping[str, ORMFieldSpec],
    dialect: str,
) -> list[tuple[str, ORMFieldSpec]]:
    """Detect possible column renames by matching orphaned DB columns to missing specs.

    Returns a list of (old_column_name, matching_spec) pairs that are
    confident rename candidates.  The heuristic is conservative:

    * System columns (id, _id, payload_json) are skipped.
    * The orphaned column's DB type category must match the spec's ``kind``
      (blob_single/blob_union map to "blob", json/file_id/foreign_list to "json").
    * At most one orphaned column may match one missing spec (1-to-1 only).
    """
    spec_columns = {spec.column_name for spec in specs.values()}
    orphaned: dict[str, str] = {}  # column_name → sql_type_upper
    for col_name, col_type in existing_columns.items():
        if col_name in _SYSTEM_COLUMNS or col_name in spec_columns:
            continue
        orphaned[col_name] = str(col_type or "")

    missing: list[ORMFieldSpec] = [
        spec for spec in specs.values()
        if spec.column_name not in existing_columns
    ]
    if not orphaned or not missing:
        return []

    def _kind_to_category(kind: FieldKind) -> str:
        if kind in {"blob_single", "blob_union"}:
            return "blob"
        if kind in {"json", "file_id", "foreign_list"}:
            return "json"
        if kind == "foreign_single":
            return "str"
        return kind  # scalar kinds: bool, int, float, str, date, datetime

    renames: list[tuple[str, ORMFieldSpec]] = []
    used_orphans: set[str] = set()

    for spec in missing:
        spec_cat = _kind_to_category(spec.kind)
        candidates: list[str] = []
        for orphan_col, orphan_type in orphaned.items():
            if orphan_col in used_orphans:
                continue
            if _sql_type_category(orphan_type) == spec_cat:
                candidates.append(orphan_col)
        if len(candidates) == 1:
            renames.append((candidates[0], spec))
            used_orphans.add(candidates[0])

    return renames


__all__ = [
    "FieldKind",
    "ORMFieldSpec",
    "SQL_DEFAULT_VARCHAR_LENGTH",
    "detect_column_renames",
    "deserialize_field_value",
    "extract_field_specs",
    "native_field_names",
    "serialize_field_value",
    "sql_column_type",
    "_json_column_type",
    "_blob_column_type",
    "_sqlite_supports_jsonb",
]
