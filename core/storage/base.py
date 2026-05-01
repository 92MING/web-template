import os
import re
import fnmatch
import bson
import time
import types
import logging
import tempfile
import threading
import bson.errors
import orjson as _orjson

from abc import ABC
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from pydantic import BaseModel
from pydantic_core import core_schema
from typing_extensions import Unpack
from typing import Any, ClassVar, Mapping, Sequence, TypedDict, cast, get_args, get_origin, get_type_hints, Union, Callable, Literal, Self

_logger = logging.getLogger(__name__)

type StorageCategory = Literal["object", "vector", "kv", "orm"]


def _normalize_storage_registry_key(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "")

class ObjectId(bson.ObjectId):
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return str(self) == other
        return bool(super().__eq__(other))

    __hash__ = bson.ObjectId.__hash__

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: Callable[[Any], core_schema.CoreSchema],
    ) -> core_schema.CoreSchema:
        _ = (_source_type, _handler)
        def validate_from_string_or_bytes(value: Union[str, bytes]) -> bson.ObjectId:
            try:
                return bson.ObjectId(value)
            except bson.errors.InvalidId:
                raise ValueError("Invalid ObjectId")

        from_string_or_bytes_schema = core_schema.chain_schema(
            [
                core_schema.union_schema(
                    [
                        core_schema.str_schema(),
                        core_schema.bytes_schema(),
                    ]
                ),
                core_schema.no_info_plain_validator_function(
                    validate_from_string_or_bytes
                ),
            ]
        )

        return core_schema.json_or_python_schema(
            json_schema=from_string_or_bytes_schema,
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(bson.ObjectId),
                    from_string_or_bytes_schema,
                ],
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, when_used="json"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, _schema: core_schema.CoreSchema, handler):
        _ = _schema
        json_schema = handler(core_schema.str_schema())
        json_schema.update(
            examples=["5f85f36d6dfecacc68428a46", "ffffffffffffffffffffffff"],
            example="5f85f36d6dfecacc68428a46",
        )
        return json_schema

class StorageClientInitParams(TypedDict, total=False):
    name: str | None
    cleanup_interval: float
    max_size: int | None
    auto_start: bool

class StorageClientBase(ABC):
    __DefaultInstances__: ClassVar[dict[tuple[type, bool], "StorageClientBase"]] = {}
    _ClientClses: ClassVar[dict[tuple[str, str], type["StorageClientBase"]]] = {}
    _MetadataTypedDictCache: ClassVar[dict[type["StorageClientBase"], type[dict[str, object]] | None]] = {}
    Category: ClassVar[StorageCategory]
    Type: ClassVar[str | None] = None
    StorageKind: ClassVar[str]

    def __init_subclass__(
        cls,
        *,
        storage_kind: str | None = None,
        category: StorageCategory | str | None = None,
        type: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        cls_category = category or storage_kind or getattr(cls, "Category", None) or getattr(cls, "StorageKind", None)
        if not cls_category:
            raise TypeError(f"{cls.__name__} must declare `StorageKind` either as a class variable or as a parameter to `__init_subclass__`.")
        normalized_category = _normalize_storage_registry_key(str(cls_category))
        cls.Category = cast(StorageCategory, normalized_category)
        cls.StorageKind = normalized_category

        registered_type = type if type is not None else getattr(cls, "Type", None)
        cls.Type = registered_type
        if not registered_type:
            return

        key = (normalized_category, _normalize_storage_registry_key(registered_type))
        current = cls._ClientClses.get(key)
        if current is not None and current.__qualname__ != cls.__qualname__:
            raise TypeError(
                f"Duplicate storage client registration for category={normalized_category!r}, type={registered_type!r}: "
                f"{current.__qualname__} vs {cls.__qualname__}"
            )
        cls._ClientClses[key] = cls

    @classmethod
    def GetClientCls(
        cls,
        type_name: str,
        *,
        category: StorageCategory | str | None = None,
    ) -> type["StorageClientBase"] | None:
        cls_category = category or getattr(cls, "Category", None) or getattr(cls, "StorageKind", None)
        if not cls_category:
            raise TypeError(f"{cls.__name__} must declare `Category`/`StorageKind` to resolve client classes.")
        return cls._ClientClses.get(
            (
                _normalize_storage_registry_key(str(cls_category)),
                _normalize_storage_registry_key(type_name),
            )
        )

    def __init__(self, **kwargs: Unpack[StorageClientInitParams]) -> None:
        self._name = kwargs.get("name") or self.__class__.__name__
        self._cleanup_interval = max(1.0, float(kwargs.get("cleanup_interval", 60.0)))
        raw_max_size = kwargs.get("max_size")
        self._max_size = int(raw_max_size) if raw_max_size is not None else None
        self._auto_start = bool(kwargs.get("auto_start", False))
        self._started = False
        self._cleanup_lock = threading.RLock()
        self._last_cleanup_at = time.time()

    @property
    def started(self) -> bool:
        return self._started

    def _mark_started(self) -> None:
        self._started = True

    def _mark_stopped(self) -> None:
        self._started = False

    def _cleanup_kv_key(self) -> str:
        """Return a KV key used to share the last-cleanup timestamp across workers."""
        ns = getattr(self, "_namespace", "default")
        kind = getattr(self, "StorageKind", "unknown")
        return f"_cleanup_ts:{kind}:{ns}:{self._name}"

    def _should_cleanup(self, *, force: bool = False) -> bool:
        if force:
            return True
        return (time.time() - self._last_cleanup_at) >= self._cleanup_interval

    async def _should_cleanup_async(self, *, force: bool = False) -> bool:
        """Like ``_should_cleanup`` but also checks shared KV for multi-worker coordination."""
        if force:
            return True
        now = time.time()
        if (now - self._last_cleanup_at) < self._cleanup_interval:
            return False
        if getattr(self, "StorageKind", None) == "kv":
            return True
        try:
            from .kv import KVClientBase
            kv = KVClientBase.Default()
            if not kv.started:
                kv.start()
            raw = await kv.get(self._cleanup_kv_key())
            if isinstance(raw, (str, int, float)):
                shared_ts = float(raw)
                if (now - shared_ts) < self._cleanup_interval:
                    self._last_cleanup_at = shared_ts
                    return False
        except Exception:
            pass  # KV not configured — fall back to local-only check
        return True

    def _mark_cleanup(self) -> None:
        self._last_cleanup_at = time.time()

    async def _mark_cleanup_async(self) -> None:
        """Like ``_mark_cleanup`` but also writes timestamp to shared KV."""
        now = time.time()
        self._last_cleanup_at = now
        if getattr(self, "StorageKind", None) == "kv":
            return
        try:
            from .kv import KVClientBase
            kv = KVClientBase.Default()
            if not kv.started:
                kv.start()
            await kv.set(self._cleanup_kv_key(), str(now))
        except Exception:
            pass  # KV not configured — local-only timestamp is fine

    def close(self) -> None:
        self._mark_stopped()

    @classmethod
    def _metadata_typed_dict_cls(cls) -> type[dict[str, object]] | None:
        cached = cls._MetadataTypedDictCache.get(cls, None)
        if cls in cls._MetadataTypedDictCache:
            return cached

        typed_dict_cls: type[dict[str, object]] | None = None
        for base in cls.__mro__:
            init = getattr(base, "__init__", None)
            if init is None:
                continue
            try:
                hints = get_type_hints(init, globalns=getattr(init, "__globals__", {}), include_extras=True)
            except Exception:
                hints = getattr(init, "__annotations__", {}) or {}
            kwargs_hint = hints.get("kwargs")
            if kwargs_hint is None:
                continue
            origin = get_origin(kwargs_hint)
            if origin is None or "Unpack" not in str(origin):
                continue
            args = get_args(kwargs_hint)
            if not args:
                continue
            candidate = args[0]
            if isinstance(candidate, type) and hasattr(candidate, "__annotations__"):
                typed_dict_cls = cast(type[dict[str, object]], candidate)
                break

        cls._MetadataTypedDictCache[cls] = typed_dict_cls
        return typed_dict_cls

    @staticmethod
    def _metadata_attr_candidates(field_name: str) -> tuple[str, ...]:
        candidates = [field_name, f"_{field_name}"]
        if field_name == "name":
            candidates.append("_name")
        if field_name == "folder":
            candidates.append("_folder_prefix")
        return tuple(dict.fromkeys(candidates))

    def _metadata_value_for_field(self, field_name: str) -> object:
        for attr_name in self._metadata_attr_candidates(field_name):
            if hasattr(self, attr_name):
                return getattr(self, attr_name)
        raise AttributeError(field_name)

    def metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        typed_dict_cls = self._metadata_typed_dict_cls()
        if typed_dict_cls is not None:
            for field_name in _typed_dict_annotation_names(typed_dict_cls):
                try:
                    raw_value = self._metadata_value_for_field(field_name)
                except AttributeError:
                    continue
                metadata[field_name] = _metadata_to_serializable(field_name, raw_value)
        metadata.setdefault("started", bool(self.started))
        return metadata

    def __del__(self):
        try:
            self.close()
        except Exception as e:
            _logger.warning(
                '%s.__del__() failed: %s',
                getattr(self, '_name', self.__class__.__name__),
                e,
            )

    @classmethod
    def Default(cls, *, use_cache: bool = False)->Self:
        cache_key = (cls, bool(use_cache))
        cached = cls.__DefaultInstances__.get(cache_key)
        if cached is not None:
            if bool(getattr(cached, "_closing", False)):
                cls.__DefaultInstances__.pop(cache_key, None)
            else:
                return cast("StorageClientBase", cached)    # type: ignore[return-value]

        storage_kind = getattr(cls, "StorageKind", None)
        if not storage_kind:
            raise TypeError(f"{cls.__name__} must declare `StorageKind` to use Default().")

        from .config import StorageConfig

        storage_cfg = StorageConfig.Global()
        getter = getattr(storage_cfg, f"get_{storage_kind}_client", None)
        if getter is None:
            raise AttributeError(f"StorageConfig does not provide get_{storage_kind}_client().")
        client = getter("cache" if use_cache else "default")
        if not isinstance(client, cls):
            raise TypeError(
                f"Global {storage_kind} client is `{type(client).__name__}`, not `{cls.__name__}`."
            )
        cls.__DefaultInstances__[cache_key] = client
        return client

    @classmethod
    def SetGlobal(cls, client: "StorageClientBase", *, use_cache: bool = False):
        if not isinstance(client, cls):
            raise TypeError(f"`client` must be an instance of `{cls.__name__}`.")
        cls.__DefaultInstances__[(cls, bool(use_cache))] = client
        return client

    @classmethod
    def ClearDefaultInstances(cls) -> None:
        keys_to_delete = [
            key
            for key in cls.__DefaultInstances__
            if issubclass(key[0], cls) or issubclass(cls, key[0])
        ]
        for key in keys_to_delete:
            cls.__DefaultInstances__.pop(key, None)

class ExpirableItem(TypedDict, total=False):
    expire_at: float | None
    accessed_at: float
    size: int

class SchemaInfo(TypedDict):
    collection_name: str
    bootstrapped: bool

def _ensure_parent_dir(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _ensure_dir(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def _now_ts() -> float:
    return time.time()

def _coerce_object_id(value: object) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))  # type: ignore[call-arg]
    except Exception:
        return cast(ObjectId, value)

def _normalize_expire_at(expire: float | int | None = None, *, expire_at: float | None = None) -> float | None:
    if expire_at is not None:
        return float(expire_at)
    if expire is None:
        return None
    ttl = float(expire)
    if ttl <= 0:
        return _now_ts() - 1.0
    return _now_ts() + ttl

def _ttl_from_expire_at(expire_at: float | None) -> float | None:
    if expire_at is None:
        return None
    remain = float(expire_at) - _now_ts()
    if remain <= 0:
        return 0.0
    return remain

# ── JSON helpers (use orjson when available for ~4x speedup) ─────────────────
def _json_default(value: object) -> object:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

def _typed_dict_annotation_names(typed_dict_cls: type[dict[str, object]]) -> list[str]:
    names: list[str] = []
    for base in reversed(typed_dict_cls.__mro__):
        annotations = getattr(base, "__annotations__", None)
        if not isinstance(annotations, dict):
            continue
        for key in annotations:
            if key not in names:
                names.append(key)
    return names

def _sanitize_metadata_value(key: str, value: object) -> object:
    lowered = key.lower()
    if any(token in lowered for token in ("password", "secret", "token", "access_key", "secret_key")):
        return "<redacted>"
    if lowered in {"url", "uri", "mongo_url"} and isinstance(value, str):
        try:
            parts = urlsplit(value)
        except Exception:
            return value
        if parts.username is None and parts.password is None:
            return value
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    return value

def _metadata_to_serializable(key: str, value: object) -> object:
    sanitized = _sanitize_metadata_value(key, value)
    try:
        _json_dumps_bytes(sanitized)
        return sanitized
    except Exception:
        pass

    if isinstance(sanitized, BaseModel):
        try:
            return sanitized.model_dump(mode="json", by_alias=True)
        except Exception:
            return str(sanitized)
    if isinstance(sanitized, Path):
        return str(sanitized)
    if isinstance(sanitized, Mapping):
        return {str(map_key): _metadata_to_serializable(str(map_key), map_value) for map_key, map_value in sanitized.items()}
    if isinstance(sanitized, Sequence) and not isinstance(sanitized, (str, bytes, bytearray, memoryview)):
        return [_metadata_to_serializable(key, item) for item in sanitized]
    if isinstance(sanitized, set):
        return [_metadata_to_serializable(key, item) for item in sorted(sanitized, key=lambda item: str(item))]
    return str(sanitized)

def _json_dumps_bytes(data: object) -> bytes:
    """Serialize *data* to UTF-8 JSON bytes (fast path via orjson)."""
    return _orjson.dumps(data, default=_json_default)  # type: ignore[return-value]

def _json_dumps(data: object) -> str:
    return _json_dumps_bytes(data).decode("utf-8")

def _json_loads(data: str | bytes | bytearray) -> object:
    return _orjson.loads(data)  # type: ignore[return-value]

def _estimate_json_size(data: object) -> int:
    return len(_json_dumps_bytes(data))  # no encode() roundtrip

def _deep_get(data: Mapping[str, object] | BaseModel | None, path: str, default: object = None) -> object:
    if data is None:
        return default
    current: object
    if isinstance(data, BaseModel):
        current = data.model_dump(mode="python", by_alias=True)
    else:
        current = data
    for chunk in path.split("."):
        if isinstance(current, BaseModel):
            current = current.model_dump(mode="python", by_alias=True)
        if isinstance(current, Mapping):
            if chunk not in current:
                return default
            current = current[chunk]
            continue
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            try:
                current = current[int(chunk)]
            except Exception:
                return default
            continue
        return default
    return current

def _match_query(document: Mapping[str, object], query: Mapping[str, object] | None) -> bool:
    if not query:
        return True
    for key, expected in query.items():
        actual = _deep_get(document, key)
        if isinstance(expected, Mapping):
            if not _match_operator(actual, expected):
                return False
            continue
        if actual != expected:
            return False
    return True

def _match_operator(actual: object, expected: Mapping[str, object]) -> bool:
    import re

    def _compare_order(left: object, right: object, op: str) -> bool:
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if op == "$gt":
                return float(left) > float(right)
            if op == "$gte":
                return float(left) >= float(right)
            if op == "$lt":
                return float(left) < float(right)
            if op == "$lte":
                return float(left) <= float(right)
            return False
        if isinstance(left, str) and isinstance(right, str):
            if op == "$gt":
                return left > right
            if op == "$gte":
                return left >= right
            if op == "$lt":
                return left < right
            if op == "$lte":
                return left <= right
            return False
        return False

    for op, value in expected.items():
        if op == "$eq" and not (actual == value):
            return False
        if op == "$ne" and not (actual != value):
            return False
        if op == "$gt" and not _compare_order(actual, value, "$gt"):
            return False
        if op == "$gte" and not _compare_order(actual, value, "$gte"):
            return False
        if op == "$lt" and not _compare_order(actual, value, "$lt"):
            return False
        if op == "$lte" and not _compare_order(actual, value, "$lte"):
            return False
        if op == "$in":
            if not isinstance(value, (list, tuple, set)) or actual not in value:
                return False
        if op == "$contains":
            if isinstance(actual, Mapping):
                if value not in actual.values() and value not in actual.keys():
                    return False
            elif isinstance(actual, Sequence) and not isinstance(actual, (str, bytes, bytearray)):
                if value not in actual:
                    return False
            elif isinstance(actual, str):
                if str(value) not in actual:
                    return False
            else:
                return False
        if op == "$wildcard":
            if not fnmatch.fnmatch(str(actual or "").lower(), str(value or "").lower()):
                return False
        if op == "$regex":
            try:
                if not re.search(str(value), str(actual or ""), re.IGNORECASE):
                    return False
            except Exception:
                return False
    return True

def _unwrap_optional(annotation: object) -> tuple[object, bool]:
    """If *annotation* is ``Optional[X]`` (i.e. ``Union[X, None]``), return ``(X, True)``.

    Otherwise return ``(annotation, False)``.
    """
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in {Union, types.UnionType}:
        non_none = [a for a in args if a is not type(None)]
        if type(None) in args and len(non_none) == 1:
            return non_none[0], True
    return annotation, False


def _is_vector_annotation(annotation: object) -> bool:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is None:
        try:
            import numpy as np  # type: ignore
            if annotation is np.ndarray:
                return True
        except ImportError:
            pass
        return False
    if origin in (list, tuple, Sequence):
        return bool(args) and args[0] in (float, int)
    return False


def _get_foreign_annotation_info(annotation: object) -> tuple[type | None, bool]:
    """Inspect *annotation* for a foreign :class:`ORMModel` reference.

    Returns ``(target_model_class, is_nullable)``.
    Returns ``(None, False)`` when the annotation is not a foreign model.
    """
    # Avoid circular import at module level
    from .orm import ORMModel as _ORM

    resolved, is_optional = _unwrap_optional(annotation)
    if isinstance(resolved, type) and issubclass(resolved, _ORM):
        return resolved, is_optional
    return None, False

_SAFE_COLLECTION_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')

def _validate_collection_name(name: str) -> str:
    """Validate and return *name* if it is safe for use as a SQL identifier.

    Raises :class:`ValueError` if the name contains characters that could
    enable SQL injection.
    """
    if not name or not _SAFE_COLLECTION_NAME_RE.match(name):
        raise ValueError(
            f"Invalid collection name {name!r}. "
            "Only alphanumerics, underscores, and hyphens are allowed."
        )
    return name

def _sanitize_milvus_expr_value(value: str) -> str:
    """Escape a string value for safe embedding in a Milvus filter expression."""
    return value.replace('\\', '\\\\').replace('"', '\\"')

def _default_local_storage_root(*parts: str) -> Path:
    return _ensure_dir(Path.home() / ".local" / "share" / "proj-template" / "storage" / Path(*parts))

def _in_uvicorn_process() -> bool:
    if os.getenv("IN_FASTAPI_WORKER"):
        return False
    if os.getenv("IN_UVICORN_PROCESS"):
        return True
    return True


__all__ = [
    "ExpirableItem",
    "SchemaInfo",
    "StorageCategory",
    "StorageClientBase",
    "StorageClientInitParams",
    "ObjectId",
]
