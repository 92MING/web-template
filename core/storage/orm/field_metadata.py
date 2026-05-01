import re as _re
import annotated_types as _annotated_types

from collections.abc import Mapping
from typing import Any, Callable, Literal, TypedDict

from pydantic import AliasChoices, AliasPath
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from typing_extensions import deprecated, Unpack


class PydanticFieldInfoParams(TypedDict, total=False):
    """Public TypedDict mirror of the keyword arguments accepted by Pydantic FieldInfo."""

    default: Any
    default_factory: Callable[[], Any] | Callable[[dict[str, Any]], Any] | None
    alias: str | None
    alias_priority: int | None
    validation_alias: str | AliasPath | AliasChoices | None
    serialization_alias: str | None
    title: str | None
    field_title_generator: Callable[[str, FieldInfo], str] | None
    description: str | None
    examples: list[Any] | None
    exclude: bool | None
    exclude_if: Callable[[Any], bool] | None
    gt: _annotated_types.SupportsGt | None
    ge: _annotated_types.SupportsGe | None
    lt: _annotated_types.SupportsLt | None
    le: _annotated_types.SupportsLe | None
    multiple_of: float | None
    strict: bool | None
    min_length: int | None
    max_length: int | None
    pattern: str | _re.Pattern[str] | None
    allow_inf_nan: bool | None
    max_digits: int | None
    decimal_places: int | None
    union_mode: Literal["smart", "left_to_right"] | None
    discriminator: str | None
    deprecated: deprecated | str | bool | None
    json_schema_extra: dict[str, Any] | Callable[[dict[str, Any]], None] | None
    frozen: bool | None
    validate_default: bool | None
    repr: bool
    init: bool | None
    init_var: bool | None
    kw_only: bool | None
    coerce_numbers_to_str: bool | None
    fail_fast: bool | None


class ORMFieldInfoParams(PydanticFieldInfoParams, total=False):
    index: bool | None
    foreign_model: bool
    db_name: str | None


class ORMFieldInfo(FieldInfo):  # type: ignore
    """Pydantic FieldInfo carrying storage-layer hints used by ORM backends."""

    index: bool | None
    foreign_model: bool
    db_name: str | None

    def __init__(
        self,
        *,
        index: bool | None = None,
        foreign_model: bool = False,
        db_name: str | None = None,
        **kwargs: Unpack[PydanticFieldInfoParams],
    ) -> None:
        super().__init__(**kwargs)
        self.index = index  # None = align with DB; True = ensure; False = ensure dropped
        self.foreign_model = bool(foreign_model)
        self.db_name = db_name


def ORMField(
    default: Any = PydanticUndefined,
    *,
    index: bool | None = None,
    foreign_model: bool = False,
    db_name: str | None = None,
    **kwargs: Unpack[PydanticFieldInfoParams],  # type: ignore[no-untyped-def]
) -> Any:
    """Create a Pydantic field with ORM-specific metadata."""

    if default is not PydanticUndefined:
        kwargs["default"] = default
    return ORMFieldInfo(index=index, foreign_model=foreign_model, db_name=db_name, **kwargs)


# ── DB Field Name Resolution ─────────────────────────────────────────────────
_SYSTEM_FIELDS = frozenset({"id", "_id", "expire_at", "accessed_at", "size"})


def _is_storage_excluded(field_info: FieldInfo) -> bool:
    """Return ``True`` if *field_info* is excluded from serialization.

    Fields marked with ``Field(exclude=True)`` should not be persisted to
    storage backends, should not get native SQL columns, and should not appear
    in search indexes.  Pydantic ``PrivateAttr`` fields never appear in
    ``model_fields`` so they are excluded implicitly.
    """
    return getattr(field_info, "exclude", False) is True

def resolve_db_field_name(
    python_name: str,
    field_info: FieldInfo,
    alias_generator: object | None = None,
) -> str:
    """Resolve the database field name for a Python model field.

    Priority: ``db_name`` > ``serialization_alias`` > ``alias`` >
    ``alias_generator.serialization_alias`` > *python_name*.
    """
    if isinstance(field_info, ORMFieldInfo) and field_info.db_name is not None:
        return field_info.db_name
    ser_alias = getattr(field_info, "serialization_alias", None)
    if ser_alias is not None:
        return str(ser_alias)
    alias = getattr(field_info, "alias", None)
    if isinstance(alias, str):
        return alias
    if alias_generator is not None:
        gen_fn = getattr(alias_generator, "serialization_alias", None)
        if callable(gen_fn):
            result = gen_fn(python_name)
            if isinstance(result, str):
                return result
        if not hasattr(alias_generator, "serialization_alias") and callable(alias_generator):
            result = alias_generator(python_name)
            if isinstance(result, str):
                return result
    return python_name


def build_field_name_mapping(model_cls: type) -> dict[str, str]:
    """Build ``{python_name: db_name}`` for fields where the DB name differs.

    Returns an empty dict when all fields use their Python name as DB name
    (the common case), so callers can short-circuit on ``if not mapping:``.
    """
    alias_gen = None
    config = getattr(model_cls, "model_config", None)
    if config and isinstance(config, Mapping):
        alias_gen = config.get("alias_generator")

    mapping: dict[str, str] = {}
    for name, info in getattr(model_cls, "model_fields", {}).items():
        if name in _SYSTEM_FIELDS or name.startswith("_"):
            continue
        if _is_storage_excluded(info):
            continue
        db_name = resolve_db_field_name(name, info, alias_gen)
        if db_name != name:
            mapping[name] = db_name
    return mapping


def _translate_field_path(field: str, mapping: dict[str, str]) -> str:
    """Translate a (possibly dot-delimited) Python field path to DB field path.

    Only the first segment is translated; nested segments remain unchanged.
    """
    if not mapping:
        return field
    if "." not in field:
        return mapping.get(field, field)
    first, rest = field.split(".", 1)
    return f"{mapping.get(first, first)}.{rest}"


def remap_payload_to_db(payload: dict[str, object], mapping: dict[str, str]) -> dict[str, object]:
    """Remap payload keys from Python field names to DB field names."""
    if not mapping:
        return payload
    return {mapping.get(k, k): v for k, v in payload.items()}


def remap_payload_from_db(payload: dict[str, object], mapping: dict[str, str]) -> dict[str, object]:
    """Remap payload keys from DB field names back to Python field names."""
    if not mapping:
        return payload
    reverse = {v: k for k, v in mapping.items()}
    return {reverse.get(k, k): v for k, v in payload.items()}


# ── Schema conflict detection ─────────────────────────────────────────────────

def _levenshtein_ratio(a: str, b: str) -> float:
    """Normalized Levenshtein similarity in [0.0, 1.0]."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    prev = list(range(lb + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return 1.0 - prev[lb] / max(la, lb)


def _model_field_name_candidates(model_cls: type) -> frozenset[str]:
    """Return all python field names and DB aliases for user fields in *model_cls*.

    Excludes system fields (id, expire_at, …) and storage-excluded fields.
    """
    alias_gen = None
    config = getattr(model_cls, "model_config", None)
    if config and isinstance(config, Mapping):
        alias_gen = config.get("alias_generator")
    candidates: set[str] = set()
    for name, info in getattr(model_cls, "model_fields", {}).items():
        if name in _SYSTEM_FIELDS or name.startswith("_"):
            continue
        if _is_storage_excluded(info):
            continue
        candidates.add(name)
        db_name = resolve_db_field_name(name, info, alias_gen)
        if db_name != name:
            candidates.add(db_name)
    return frozenset(candidates)


def _schema_field_names(stored_schema: Mapping[str, object] | None) -> frozenset[str]:
    """Extract user field names from a stored Pydantic JSON schema dict.

    Returns the top-level ``properties`` keys, excluding system fields.
    """
    if not stored_schema or not isinstance(stored_schema, Mapping):
        return frozenset()
    props = stored_schema.get("properties")
    if not isinstance(props, Mapping):
        return frozenset()
    return frozenset(
        name for name in props
        if name not in _SYSTEM_FIELDS and not str(name).startswith("_")
    )


def check_schema_conflict(
    model_cls: type,
    stored_schema: Mapping[str, object] | None,
    collection: str,
) -> None:
    """Raise ``ValueError`` when *model_cls* is incompatible with a stored DB schema.

    Compatibility is measured by Levenshtein field-name similarity.  A DB field
    is "matched" when its best Levenshtein ratio against any model candidate
    (python name *or* DB alias) is >= 0.5.  Confidence = matched / total DB
    fields.  An error is raised when confidence < 0.50.

    The check is skipped when *stored_schema* is None or contains fewer than 2
    user fields (new collection or schema-less collection).
    """
    db_names = _schema_field_names(stored_schema)
    if len(db_names) < 2:
        return
    model_candidates = _model_field_name_candidates(model_cls)
    if not model_candidates:
        return
    matched = sum(
        1 for db_field in db_names
        if max((_levenshtein_ratio(db_field, c) for c in model_candidates), default=0.0) >= 0.5
    )
    confidence = matched / len(db_names)
    if confidence < 0.5:
        db_list = ", ".join(sorted(db_names))
        model_list = ", ".join(sorted(model_candidates))
        raise ValueError(
            f"Collection `{collection}`: schema conflict detected "
            f"(confidence {confidence:.2f} < 0.50). "
            f"DB fields: [{db_list}]; "
            f"model `{getattr(model_cls, '__name__', str(model_cls))}` candidates: [{model_list}]. "
            "Use a distinct CollectionName or migrate the existing collection."
        )


__all__ = [
    "PydanticFieldInfoParams",
    "ORMFieldInfoParams",
    "ORMFieldInfo",
    "ORMField",
    "_is_storage_excluded",
    "resolve_db_field_name",
    "build_field_name_mapping",
    "remap_payload_to_db",
    "remap_payload_from_db",
    "check_schema_conflict",
]