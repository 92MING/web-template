import json
import os
import re
import sys
import logging
import hashlib
import inspect

from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Annotated, Any, Callable, ClassVar, Generic, Literal, Self, TYPE_CHECKING, TypeVar, cast, overload

from pydantic import BeforeValidator, ConfigDict, Field, PrivateAttr, SerializeAsAny, model_serializer, model_validator

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import yaml

from ..utils.network_utils.ssh_tunnel import SSHTunnelConfig
from ..utils.network_utils.helper_funcs import can_reach
from ..utils.type_utils.base_clses import AdvancedBaseModel
from ..constants import PROJECT_DIR
from .base import StorageCategory, StorageClientBase, _default_local_storage_root

if TYPE_CHECKING:
    from .kv import KVClientBase
    from .object import ObjectClientBase
    from .orm import ORM_ClientBase
    from .vector import VectorClientBase

_logger = logging.getLogger(__name__)

KV_Backend = Literal["sqlite", "redis", "etcd"]
ORM_Backend = Literal["sqlite", "sql", "mongo", "postgresql", "mysql", "redis"]
VectorBackend = Literal["milvus-lite", "milvus", "annoy", "redis", "mongo"]
ObjectBackend = Literal["local", "minio"]

type StorageBackendType = KV_Backend | ORM_Backend | VectorBackend | ObjectBackend

_STORAGE_CONFIG_ENV = "__STORAGE_CONFIG__"
_ORM_PREFLIGHT_ENV = "__ORM_PREFLIGHT__"
_VECTOR_PREFLIGHT_ENV = "__VECTOR_PREFLIGHT__"
_STORAGE_FILE_SUFFIXES: tuple[str, ...] = (".yaml", ".yml", ".json", ".toml")
_SERVER_RUNTIME_ENV_KEYS: tuple[str, ...] = (
    "IN_UVICORN_PROCESS",
    "__SERVER_PROCESS_PID__",
    "__SERVER_SUPERVISOR_PID__",
    "__SERVER_INSTANCE_ID__",
)

_CFGT = TypeVar("_CFGT", bound="StorageConfigBase[Any]")
_CT = TypeVar("_CT", bound=StorageClientBase)


def _default_vector_backend() -> VectorBackend:
    if sys.platform == "win32":
        return "annoy"
    return "milvus-lite"


def _normalize_storage_registry_key(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "")


def _normalize_for_fuzzy(value: str) -> str:
    return re.sub(r"[\s_\-/\\]+", "", str(value or "")).lower()


@overload
def _env(prefix: str, field: str, default: None = None) -> str | None: ...
@overload
def _env(prefix: str, field: str, default: str) -> str: ...
@overload
def _env[_DT](prefix: str, field: str, default: _DT) -> str | _DT: ...
def _env(prefix: str, field: str, default: object = None) -> object:
    return os.getenv(f"{prefix}{field}".upper(), cast("str | None", default))


def _env_bool(prefix: str, field: str, default: bool) -> bool:
    value = _env(prefix, field, str(default))
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(prefix: str, field: str, default: int | None = None) -> int | None:
    value = _env(prefix, field, default)
    if value in (None, "", "None"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_float(prefix: str, field: str, default: float | None = None) -> float | None:
    value = _env(prefix, field, default)
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_config_type(prefix: str, default_type: str) -> str:
    return str(_env(prefix, "type", _env(prefix, "backend", default_type)))


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _load_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Storage config root in {path} must be a mapping.")
    return cast(dict[str, object], data)


def _load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Storage config root in {path} must be a mapping.")
    return cast(dict[str, object], data)


_STORAGE_LOADERS: dict[str, Callable[[Path], dict[str, object]]] = {
    ".json": _load_json,
    ".yaml": _load_yaml,
    ".yml": _load_yaml,
    ".toml": _load_toml,
}


def _prefer_mode_specific_default_paths() -> bool:
    return any(str(os.getenv(key, "") or "").strip() for key in _SERVER_RUNTIME_ENV_KEYS)


def _storage_config_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for base in (Path.cwd(), PROJECT_DIR):
        try:
            resolved = Path(base).resolve()
        except Exception:
            resolved = Path(base)
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _storage_config_name_order(*, prefer_mode_specific: bool | None = None) -> list[str]:
    prefer_mode_specific = _prefer_mode_specific_default_paths() if prefer_mode_specific is None else prefer_mode_specific
    mode = str(os.getenv("__MODE__", "")).strip().lower()
    if prefer_mode_specific and mode in {"dev", "prod"}:
        opposite_mode = "prod" if mode == "dev" else "dev"
        return [f"storage.{mode}", "storage", f"storage.{opposite_mode}", f"{mode}_storage", f"{opposite_mode}_storage"]
    return ["storage", "storage.dev", "storage.prod", "dev_storage", "prod_storage"]


def _discover_storage_config_paths(*, prefer_mode_specific: bool | None = None) -> list[Path]:
    seen: set[Path] = set()
    resolved: list[Path] = []
    for root in _storage_config_roots():
        config_dir = root / "config"
        for stem in _storage_config_name_order(prefer_mode_specific=prefer_mode_specific):
            for suffix in _STORAGE_FILE_SUFFIXES:
                path = config_dir / f"{stem}{suffix}"
                if path in seen:
                    continue
                seen.add(path)
                resolved.append(path)
    return resolved


def _is_cached_client_stale(client: object) -> bool:
    return bool(getattr(client, "_closing", False) or getattr(client, "_closed", False))


def _load_storage_config_from_file(path: Path) -> dict[str, object]:
    loader = _STORAGE_LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ValueError(f"Unsupported storage config file format: {path.suffix}")
    return loader(path)


def _load_preflight_map(env_name: str) -> dict[str, list[str]]:
    raw = str(os.getenv(env_name, "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for key, value in payload.items():
        values = value if isinstance(value, (list, tuple, set)) else [value]
        items: list[str] = []
        for item in values:
            text = str(item or "").strip()
            if text and text not in items:
                items.append(text)
        if items:
            normalized[str(key)] = items
    return normalized


def _load_orm_preflight_map() -> dict[str, list[str]]:
    return _load_preflight_map(_ORM_PREFLIGHT_ENV)


def _load_vector_preflight_map() -> dict[str, list[str]]:
    return _load_preflight_map(_VECTOR_PREFLIGHT_ENV)


def _rewrite_url_with_tunnel(url: str, tunnel: SSHTunnelConfig) -> str:
    parsed = urlparse(url)
    remote_port = parsed.port or 80
    host = parsed.hostname or tunnel.ssh_host
    try:
        local_port = tunnel.open_tunnel(remote_port)
    except Exception as exc:
        if can_reach(host, remote_port):
            _logger.warning(
                "SSH tunnel to %s failed (%s), but %s:%d is directly reachable; using direct connection.",
                tunnel.ssh_host,
                exc,
                host,
                remote_port,
            )
            return url
        raise
    if local_port == remote_port and host in ("127.0.0.1", "localhost", "::1"):
        return url
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    return urlunparse(parsed._replace(netloc=f"{userinfo}127.0.0.1:{local_port}"))


def _rewrite_endpoint_with_tunnel(endpoint: str, tunnel: SSHTunnelConfig) -> str:
    parts = endpoint.rsplit(":", 1)
    host = parts[0] if parts else tunnel.ssh_host
    try:
        remote_port = int(parts[1]) if len(parts) == 2 else 9000
    except ValueError:
        remote_port = 9000
    try:
        local_port = tunnel.open_tunnel(remote_port)
    except Exception as exc:
        if can_reach(host, remote_port):
            _logger.warning(
                "SSH tunnel to %s failed (%s), but %s:%d is directly reachable; using direct connection.",
                tunnel.ssh_host,
                exc,
                host,
                remote_port,
            )
            return endpoint
        raise
    if local_port == remote_port and host in ("127.0.0.1", "localhost", "::1"):
        return endpoint
    return f"127.0.0.1:{local_port}"


def _normalize_object_path_segment(value: str | None) -> str | None:
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return None
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise ValueError(f"Invalid object path segment: {value!r}")
    return "/".join(parts) or None


def _derive_object_namespace(*parts: str | Path | None) -> str:
    normalized_parts: list[str] = []
    labels: list[str] = []
    for part in parts:
        text = str(part or "").replace("\\", "/").strip().strip("/")
        if not text:
            continue
        normalized_parts.append(text)
        label = _normalize_storage_registry_key(Path(text).name if "/" in text else text)
        if label and label not in labels:
            labels.append(label)
    if not normalized_parts:
        return "default"
    if len(normalized_parts) == 1 and normalized_parts[0] == labels[0] if labels else False:
        return labels[0]
    base = "_".join(labels[:2]).strip("_") or "object"
    digest = hashlib.sha1("|".join(normalized_parts).lower().encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}"


def _env_kv_config(prefix: str) -> "KV_DB_Config | None":
    raw_type = _env_config_type(prefix, "")
    if not raw_type:
        return None
    return KV_DB_ConfigBase.FromEnv(prefix, default_type=cast(KV_Backend, raw_type))


class StorageConfigBase(AdvancedBaseModel, Generic[_CT]):
    Type: ClassVar[str | None] = None
    Category: ClassVar[StorageCategory]
    Label: ClassVar[str] = "storage"
    DefaultType: ClassVar[str | None] = None
    _ConfigClses: ClassVar[dict[tuple[str, str], type["StorageConfigBase[Any]"]]] = {}
    _PreValidators: ClassVar[dict[str, Callable[[Any], Any]]] = {}

    def __init_subclass__(
        cls,
        *,
        type: str | None = None,
        category: StorageCategory | str | None = None,
        abstract: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "StorageConfigBase" or cls.__name__.startswith("StorageConfigBase["):
            return
        cls_category = category or getattr(cls, "Category", None)
        if not cls_category:
            raise TypeError(f"{cls.__name__} must declare `category=...` or `Category`.")
        normalized_category = _normalize_storage_registry_key(str(cls_category))
        if normalized_category not in {"object", "vector", "kv", "orm"}:
            raise TypeError(f"Unsupported storage category `{cls_category}` for {cls.__name__}.")
        cls.Category = cast(StorageCategory, normalized_category)
        if type is not None:
            cls.Type = type
        if abstract or not getattr(cls, "Type", None):
            return
        key = (normalized_category, _normalize_storage_registry_key(str(cls.Type)))
        current = cls._ConfigClses.get(key)
        if current is not None and current.__qualname__ != cls.__qualname__:
            raise TypeError(
                f"Duplicate storage config registration for category={normalized_category!r}, type={cls.Type!r}: "
                f"{current.__qualname__} vs {cls.__qualname__}"
            )
        cls._ConfigClses[key] = cls

    @model_serializer(mode="wrap")
    def _base_storage_config_serializer(self, handler):
        data = handler(self)
        if isinstance(data, dict) and self.Type:
            data["type"] = self.Type
        return data

    @classmethod
    def GetConfigCls(
        cls,
        type_name: str,
        *,
        category: StorageCategory | str | None = None,
    ) -> type["StorageConfigBase[Any]"] | None:
        cls_category = category or getattr(cls, "Category", None)
        if not cls_category:
            raise TypeError(f"{cls.__name__} must declare `Category` to resolve config classes.")
        return cls._ConfigClses.get(
            (
                _normalize_storage_registry_key(str(cls_category)),
                _normalize_storage_registry_key(type_name),
            )
        )

    @classmethod
    def PreValidator(cls) -> Callable[[Any], Any]:
        cls_category = getattr(cls, "Category", None)
        if not cls_category:
            raise TypeError(f"{cls.__name__} must declare `Category` to build validators.")
        validator = cls._PreValidators.get(cls_category)
        if validator is None:
            label = getattr(cls, "Label", cls_category)

            def _validator(data: Any) -> Any:
                if data is None or isinstance(data, StorageConfigBase):
                    return data
                if isinstance(data, dict):
                    raw_type = data.get("type", data.get("backend", None))
                    if not raw_type:
                        _logger.warning("Got %s config data without type: %r", label, data)
                        return None
                    config_cls = cls.GetConfigCls(str(raw_type), category=cls_category)
                    if config_cls is None:
                        raise ValueError(f"Unknown {label} config type `{raw_type}`.")
                    return config_cls.model_validate(data)
                return data

            validator = _validator
            cls._PreValidators[cls_category] = validator
        return validator

    @classmethod
    def FromEnv(cls, prefix: str, *, default_type: str | None = None) -> Self:
        resolved_default = default_type or getattr(cls, "DefaultType", None)
        if cls.Category == "vector" and not resolved_default:
            resolved_default = _default_vector_backend()
        config_type = _env_config_type(prefix, resolved_default or "")
        if not config_type:
            raise ValueError(f"Missing {cls.Label} config type for prefix `{prefix}`.")
        config_cls = cls.GetConfigCls(config_type, category=cls.Category)
        if config_cls is None:
            raise ValueError(f"Unknown {cls.Label} config type `{config_type}`.")
        return cast(Self, config_cls._from_env(prefix))

    @classmethod
    def _from_env(cls, prefix: str) -> "StorageConfigBase[Any]":
        return cls(**cls._common_env_kwargs(prefix))

    @classmethod
    def _common_env_kwargs(cls, prefix: str) -> dict[str, Any]:
        return {}

    @classmethod
    def _ClientBaseCls(cls) -> type[_CT]:
        raise NotImplementedError

    @property
    def client_cls(self) -> type[_CT]:
        if not self.Type:
            raise TypeError(f"{self.__class__.__name__} is missing registered Type.")
        client_cls = self._ClientBaseCls().GetClientCls(self.Type, category=self.Category)
        if client_cls is None:
            raise ValueError(
                f"No storage client class registered for category={self.Category!r}, type={self.Type!r}."
            )
        return cast(type[_CT], client_cls)

    def to_client_init_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for field_name, field_info in type(self).model_fields.items():
            if getattr(field_info, "exclude", False):
                continue
            params[field_name] = getattr(self, field_name)
        return params

    def create_client(self) -> _CT:
        params = self.to_client_init_params()
        return self.client_cls(**params)

    def client(self) -> _CT:
        cached = self.__dict__.get("__client__")
        if cached is not None and _is_cached_client_stale(cached):
            self.clear_cached_client()
            cached = None
        if cached is None:
            self.__client__ = self.create_client()
        return cast(_CT, self.__client__)

    def clear_cached_client(self) -> None:
        cast(dict[str, Any], self.__dict__).pop("__client__", None)


class KV_DB_ConfigBase(StorageConfigBase["KVClientBase"], category="kv", abstract=True):
    Type: ClassVar[KV_Backend | None] = None
    Label: ClassVar[str] = "KV"
    DefaultType: ClassVar[KV_Backend] = "sqlite"

    namespace: str = "default"
    cleanup_interval: float = 60.0
    max_size: int | None = None
    default_expire: float | None = None

    @classmethod
    def _ClientBaseCls(cls) -> type["KVClientBase"]:
        from .kv import KVClientBase
        return KVClientBase

    @classmethod
    def _common_env_kwargs(cls, prefix: str) -> dict[str, Any]:
        return {
            "namespace": _env(prefix, "namespace", "default"),
            "cleanup_interval": float(_env(prefix, "cleanup_interval", 60.0)),
            "max_size": _env_int(prefix, "max_size", None),
            "default_expire": _env_float(prefix, "default_expire", None),
        }


class LocalKVDBConfig(KV_DB_ConfigBase, type="sqlite"):
    db_path: str | None = None
    start_cleanup_thread: bool = False

    @classmethod
    def _from_env(cls, prefix: str) -> "LocalKVDBConfig":
        return cls(
            **cls._common_env_kwargs(prefix),
            db_path=_env(prefix, "db_path", None),
            start_cleanup_thread=_env_bool(prefix, "start_cleanup_thread", False),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["db_path"] = self.db_path or (_default_local_storage_root("kv") / f"{self.namespace}_kv.sqlite3")
        params["start_cleanup_thread"] = self.start_cleanup_thread
        return params


class RedisKVDBConfig(KV_DB_ConfigBase, type="redis"):
    url: str = "redis://127.0.0.1:6379/0"
    prefix: str = "kv"
    db: int = 0
    decode_responses: bool = False
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "RedisKVDBConfig":
        return cls(
            **cls._common_env_kwargs(prefix),
            url=_env(prefix, "url", _env(prefix, "redis_url", "redis://127.0.0.1:6379/0")),
            prefix=_env(prefix, "prefix", _env(prefix, "redis_prefix", "kv")),
            db=int(_env(prefix, "db", 0)),
            decode_responses=_env_bool(prefix, "decode_responses", False),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["url"] = _rewrite_url_with_tunnel(self.url, self.ssh_tunnel) if self.ssh_tunnel else self.url
        return params


class EtcdKVDBConfig(KV_DB_ConfigBase, type="etcd"):
    host: str = "127.0.0.1"
    port: int = 2379
    protocol: str = "http"
    prefix: str = "kv"
    timeout: float | None = 5.0
    api_path: str | None = None
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "EtcdKVDBConfig":
        return cls(
            **cls._common_env_kwargs(prefix),
            host=_env(prefix, "host", _env(prefix, "etcd_host", "127.0.0.1")),
            port=int(_env(prefix, "port", _env(prefix, "etcd_port", 2379))),
            protocol=_env(prefix, "protocol", _env(prefix, "etcd_protocol", "http")),
            prefix=_env(prefix, "prefix", _env(prefix, "etcd_prefix", "kv")),
            timeout=_env_float(prefix, "timeout", 5.0),
            api_path=_env(prefix, "api_path", _env(prefix, "etcd_api_path", None)),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        host = self.host
        port = self.port
        if self.ssh_tunnel:
            parsed = urlparse(f"{self.protocol}://{host}:{int(port)}")
            tunneled = _rewrite_url_with_tunnel(parsed.geturl(), self.ssh_tunnel)
            parsed_tunneled = urlparse(tunneled)
            host = parsed_tunneled.hostname or host
            port = int(parsed_tunneled.port or port)
        params["host"] = host
        params["port"] = port
        return params


type KV_DB_Config = SerializeAsAny[Annotated[KV_DB_ConfigBase, BeforeValidator(KV_DB_ConfigBase.PreValidator())]]


class ORM_DB_ConfigBase(StorageConfigBase["ORM_ClientBase"], category="orm", abstract=True):
    Type: ClassVar[ORM_Backend | None] = None
    Label: ClassVar[str] = "ORM"
    DefaultType: ClassVar[ORM_Backend] = "sqlite"

    namespace: str = "default"
    cleanup_interval: float = 120.0
    max_size: int | None = None
    default_expire: float | None = None
    log_collection_name: str = "log"

    @classmethod
    def _ClientBaseCls(cls) -> type["ORM_ClientBase"]:
        from .orm import ORM_ClientBase
        return ORM_ClientBase

    @classmethod
    def _common_env_kwargs(cls, prefix: str) -> dict[str, Any]:
        return {
            "namespace": _env(prefix, "namespace", "default"),
            "cleanup_interval": float(_env(prefix, "cleanup_interval", 120.0)),
            "max_size": _env_int(prefix, "max_size", None),
            "default_expire": _env_float(prefix, "default_expire", None),
            "log_collection_name": _env(prefix, "log_collection_name", "log"),
        }


class SQLiteORMDBConfig(ORM_DB_ConfigBase, type="sqlite"):
    db_path: str | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "SQLiteORMDBConfig":
        return cls(**cls._common_env_kwargs(prefix), db_path=_env(prefix, "db_path", None))

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["db_path"] = self.db_path or (_default_local_storage_root("orm") / f"{self.namespace}_orm.sqlite3")
        return params


class SQL_ORM_DB_Config(ORM_DB_ConfigBase, type="sql"):
    url: str | None = None
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "SQL_ORM_DB_Config":
        return cls(**cls._common_env_kwargs(prefix), url=_env(prefix, "url", _env(prefix, "sql_url", None)))

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        raw_url = self.url or f"sqlite:///{(_default_local_storage_root('orm') / f'{self.namespace}_orm_sql.sqlite3').as_posix()}"
        parsed = urlparse(raw_url)
        params["url"] = _rewrite_url_with_tunnel(raw_url, self.ssh_tunnel) if (self.ssh_tunnel and parsed.hostname) else raw_url
        return params


class MongoORM_DB_Config(ORM_DB_ConfigBase, type="mongo"):
    url: str = "mongodb://127.0.0.1:27017"
    database: str = "app_backend"
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "MongoORM_DB_Config":
        return cls(
            **cls._common_env_kwargs(prefix),
            url=_env(prefix, "url", _env(prefix, "mongo_url", "mongodb://127.0.0.1:27017")),
            database=_env(prefix, "database", _env(prefix, "mongo_database", "app_backend")),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["mongo_url"] = _rewrite_url_with_tunnel(self.url, self.ssh_tunnel) if self.ssh_tunnel else self.url
        params.pop("url", None)
        return params


class PostgreSQL_ORM_DB_Config(ORM_DB_ConfigBase, type="postgresql"):
    url: str | None = None
    host: str = "127.0.0.1"
    port: int = 5432
    username: str = "postgres"
    password: str | None = None
    database: str = "postgres"
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "PostgreSQL_ORM_DB_Config":
        return cls(
            **cls._common_env_kwargs(prefix),
            url=_env(prefix, "url", _env(prefix, "postgresql_url", _env(prefix, "postgres_url", None))),
            host=_env(prefix, "host", _env(prefix, "postgresql_host", "127.0.0.1")),
            port=int(_env(prefix, "port", _env(prefix, "postgresql_port", 5432))),
            username=_env(prefix, "username", _env(prefix, "postgresql_username", _env(prefix, "user", "postgres"))),
            password=_env(prefix, "password", _env(prefix, "postgresql_password", None)),
            database=_env(prefix, "database", _env(prefix, "postgresql_database", "postgres")),
        )

    def _raw_url(self) -> str:
        if self.url:
            return self.url
        from .orm import PostgreSQLORMClient
        return PostgreSQLORMClient.build_url(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database=self.database,
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        raw_url = self._raw_url()
        parsed = urlparse(raw_url)
        params["url"] = _rewrite_url_with_tunnel(raw_url, self.ssh_tunnel) if (self.ssh_tunnel and parsed.hostname) else raw_url
        return params


class MySQL_ORM_DB_Config(ORM_DB_ConfigBase, type="mysql"):
    url: str | None = None
    host: str = "127.0.0.1"
    port: int = 3306
    username: str = "root"
    password: str | None = None
    database: str = "app_backend"
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "MySQL_ORM_DB_Config":
        return cls(
            **cls._common_env_kwargs(prefix),
            url=_env(prefix, "url", _env(prefix, "mysql_url", None)),
            host=_env(prefix, "host", _env(prefix, "mysql_host", "127.0.0.1")),
            port=int(_env(prefix, "port", _env(prefix, "mysql_port", 3306))),
            username=_env(prefix, "username", _env(prefix, "mysql_username", _env(prefix, "user", "root"))),
            password=_env(prefix, "password", _env(prefix, "mysql_password", None)),
            database=_env(prefix, "database", _env(prefix, "mysql_database", "app_backend")),
        )

    def _raw_url(self) -> str:
        if self.url:
            return self.url
        from .orm import MySQLORMClient
        return MySQLORMClient.build_url(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database=self.database,
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        raw_url = self._raw_url()
        parsed = urlparse(raw_url)
        params["url"] = _rewrite_url_with_tunnel(raw_url, self.ssh_tunnel) if (self.ssh_tunnel and parsed.hostname) else raw_url
        return params


class RedisORMDBConfig(ORM_DB_ConfigBase, type="redis"):
    url: str = "redis://127.0.0.1:6379/0"
    prefix: str = "orm"
    db: int = 0
    decode_responses: bool = True
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "RedisORMDBConfig":
        return cls(
            **cls._common_env_kwargs(prefix),
            url=_env(prefix, "url", _env(prefix, "redis_url", "redis://127.0.0.1:6379/0")),
            prefix=_env(prefix, "prefix", _env(prefix, "redis_prefix", "orm")),
            db=int(_env(prefix, "db", 0)),
            decode_responses=_env_bool(prefix, "decode_responses", True),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["url"] = _rewrite_url_with_tunnel(self.url, self.ssh_tunnel) if self.ssh_tunnel else self.url
        return params


type ORMDBConfig = SerializeAsAny[Annotated[ORM_DB_ConfigBase, BeforeValidator(ORM_DB_ConfigBase.PreValidator())]]


class VectorDB_ConfigBase(StorageConfigBase["VectorClientBase"], category="vector", abstract=True):
    Type: ClassVar[VectorBackend | None] = None
    Label: ClassVar[str] = "vector"
    DefaultType: ClassVar[str | None] = None

    namespace: str = "default"
    cleanup_interval: float = 120.0
    max_size: int | None = None
    default_expire: float | None = None
    metric_type: Literal["COSINE", "L2", "EUCLIDEAN", "IP", "DOT", "MANHATTAN", "HAMMING"] = "COSINE"

    @classmethod
    def _ClientBaseCls(cls) -> type["VectorClientBase"]:
        from .vector import VectorClientBase
        return VectorClientBase

    @classmethod
    def _common_env_kwargs(cls, prefix: str) -> dict[str, Any]:
        return {
            "namespace": _env(prefix, "namespace", "default"),
            "cleanup_interval": float(_env(prefix, "cleanup_interval", 120.0)),
            "max_size": _env_int(prefix, "max_size", None),
            "default_expire": _env_float(prefix, "default_expire", None),
            "metric_type": _env(prefix, "metric_type", "COSINE"),
        }


class MilvusLiteVectorDBConfig(VectorDB_ConfigBase, type="milvus-lite"):
    db_path: str | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "MilvusLiteVectorDBConfig":
        return cls(**cls._common_env_kwargs(prefix), db_path=_env(prefix, "db_path", None))

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["db_path"] = self.db_path or (_default_local_storage_root("vector") / f"{self.namespace}_milvus_lite.db")
        return params


class MilvusVectorDBConfig(VectorDB_ConfigBase, type="milvus"):
    uri: str = "http://127.0.0.1:19530"
    token: str | None = None
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "MilvusVectorDBConfig":
        return cls(
            **cls._common_env_kwargs(prefix),
            uri=_env(prefix, "uri", "http://127.0.0.1:19530"),
            token=_env(prefix, "token", None),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["uri"] = _rewrite_url_with_tunnel(self.uri, self.ssh_tunnel) if self.ssh_tunnel else self.uri
        return params


class AnnoyVectorDBConfig(VectorDB_ConfigBase, type="annoy"):
    db_dir: str | None = None
    n_trees: int = 10

    @classmethod
    def _from_env(cls, prefix: str) -> "AnnoyVectorDBConfig":
        return cls(
            **cls._common_env_kwargs(prefix),
            db_dir=_env(prefix, "db_dir", None),
            n_trees=_env_int(prefix, "n_trees", 10) or 10,
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["db_dir"] = self.db_dir or (_default_local_storage_root("vector") / self.namespace)
        return params


class RedisVectorDBConfig(VectorDB_ConfigBase, type="redis"):
    url: str = "redis://127.0.0.1:6379/0"
    prefix: str = "vector"
    db: int = 0
    decode_responses: bool = True
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "RedisVectorDBConfig":
        return cls(
            **cls._common_env_kwargs(prefix),
            url=_env(prefix, "url", _env(prefix, "redis_url", "redis://127.0.0.1:6379/0")),
            prefix=_env(prefix, "prefix", _env(prefix, "redis_prefix", "vector")),
            db=int(_env(prefix, "db", 0)),
            decode_responses=_env_bool(prefix, "decode_responses", True),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["url"] = _rewrite_url_with_tunnel(self.url, self.ssh_tunnel) if self.ssh_tunnel else self.url
        return params


class MongoVectorDBConfig(VectorDB_ConfigBase, type="mongo"):
    url: str = "mongodb://127.0.0.1:27017"
    database: str = "app_backend"
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "MongoVectorDBConfig":
        return cls(
            **cls._common_env_kwargs(prefix),
            url=_env(prefix, "url", _env(prefix, "mongo_url", "mongodb://127.0.0.1:27017")),
            database=_env(prefix, "database", _env(prefix, "mongo_database", "app_backend")),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["mongo_url"] = _rewrite_url_with_tunnel(self.url, self.ssh_tunnel) if self.ssh_tunnel else self.url
        params.pop("url", None)
        return params


type VectorDBConfig = SerializeAsAny[Annotated[VectorDB_ConfigBase, BeforeValidator(VectorDB_ConfigBase.PreValidator())]]


class ObjectDB_ConfigBase(StorageConfigBase["ObjectClientBase"], category="object", abstract=True):
    Type: ClassVar[ObjectBackend | None] = None
    Label: ClassVar[str] = "object"
    DefaultType: ClassVar[ObjectBackend] = "local"

    bucket: str = "default"
    folder: str | None = None
    cleanup_interval: float = 120.0
    max_size: int | None = None
    default_expire: float | None = None
    metadata_db: KV_DB_Config | str | None = None

    @classmethod
    def _ClientBaseCls(cls) -> type["ObjectClientBase"]:
        from .object import ObjectClientBase
        return ObjectClientBase

    @classmethod
    def _common_env_kwargs(cls, prefix: str) -> dict[str, Any]:
        metadata_db = _env_kv_config(f"{prefix}metadata_db_")
        if metadata_db is None:
            metadata_db_name = str(_env(prefix, "metadata_db", "") or "").strip()
            metadata_db = metadata_db_name or None
        return {
            "bucket": _env(prefix, "bucket", "default"),
            "folder": _env(prefix, "folder", None),
            "cleanup_interval": float(_env(prefix, "cleanup_interval", 120.0)),
            "max_size": _env_int(prefix, "max_size", None),
            "default_expire": _env_float(prefix, "default_expire", None),
            "metadata_db": metadata_db,
        }

    @property
    def namespace(self) -> str:
        return self._effective_namespace()

    def _effective_namespace(self) -> str:
        bucket = _normalize_storage_registry_key(self.bucket)
        folder = _normalize_object_path_segment(self.folder)
        if bucket and bucket != "default":
            if folder:
                return _derive_object_namespace(bucket, folder)
            return bucket
        if folder:
            return _derive_object_namespace(folder)
        return "default"

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["namespace"] = self._effective_namespace()
        return params


class LocalObjectDBConfig(ObjectDB_ConfigBase, type="local"):
    root_path: str | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "LocalObjectDBConfig":
        return cls(**cls._common_env_kwargs(prefix), root_path=_env(prefix, "root_path", None))

    def _resolved_root_path(self) -> Path:
        root_path = Path(self.root_path) if self.root_path else _default_local_storage_root("object", "files")
        for segment in (self.bucket, self.folder):
            normalized = _normalize_object_path_segment(segment)
            if normalized:
                root_path = root_path.joinpath(*normalized.split("/"))
        return root_path

    def _effective_namespace(self) -> str:
        return _derive_object_namespace(self._resolved_root_path())

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        root_path = self._resolved_root_path()
        params["root_path"] = root_path
        params.pop("bucket", None)
        params.pop("folder", None)
        return params


class MinIO_ObjectDB_Config(ObjectDB_ConfigBase, type="minio"):
    endpoint: str = "127.0.0.1:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket: str = "app_backend"
    secure: bool = False
    region: str | None = None
    ssh_tunnel: SSHTunnelConfig | None = None

    @classmethod
    def _from_env(cls, prefix: str) -> "MinIO_ObjectDB_Config":
        return cls(
            **cls._common_env_kwargs(prefix),
            endpoint=_env(prefix, "endpoint", "127.0.0.1:9000"),
            access_key=_env(prefix, "access_key", "minioadmin"),
            secret_key=_env(prefix, "secret_key", "minioadmin"),
            bucket=_env(prefix, "bucket", "app_backend"),
            secure=_env_bool(prefix, "secure", False),
            region=_env(prefix, "region", None),
        )

    def to_client_init_params(self) -> dict[str, Any]:
        params = super().to_client_init_params()
        params["endpoint"] = _rewrite_endpoint_with_tunnel(self.endpoint, self.ssh_tunnel) if self.ssh_tunnel else self.endpoint
        params["bucket"] = str(self.bucket or "app_backend").strip().lower()
        return params


type ObjectDBConfig = SerializeAsAny[Annotated[ObjectDB_ConfigBase, BeforeValidator(ObjectDB_ConfigBase.PreValidator())]]


class StorageConfigSection(AdvancedBaseModel, Generic[_CFGT, _CT]):
    model_config = ConfigDict(extra="ignore")

    default: Any = None
    cache: Any = None
    extra: dict[str, Any] = Field(default_factory=dict)

    _client_singletons: dict[str, Any] = PrivateAttr(default_factory=dict)

    _NO_AUTO_FILL: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def _ConfigBaseCls(cls) -> type[StorageConfigBase[Any]]:
        raise NotImplementedError

    @model_validator(mode="before")
    @classmethod
    def _PreValidateSection(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        tidied: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in data.items():
            if key == "extra":
                if isinstance(value, dict):
                    extra.update(value)
                elif value is not None:
                    _logger.warning("Storage section `%s.extra` should be a dict, got %s.", cls.__name__, type(value).__name__)
                continue
            if key in cls.model_fields:
                tidied[key] = value
                continue
            if isinstance(value, (dict, StorageConfigBase)):
                extra[key] = value
            else:
                _logger.warning("Ignoring unsupported storage section item `%s` in %s: %r", key, cls.__name__, value)
        validator = cls._ConfigBaseCls().PreValidator()
        for key in tuple(tidied.keys()):
            tidied[key] = validator(tidied[key])
        validated_extra: dict[str, Any] = {}
        for key, value in extra.items():
            validated = validator(value)
            if validated is not None:
                validated_extra[key] = validated
        tidied["extra"] = validated_extra
        return tidied

    def model_post_init(self, __context: Any) -> None:
        for name in list(self.extra):
            if name in self.__class__.model_fields and getattr(self, name, None) is None:
                setattr(self, name, self.extra.pop(name))
        if self.default is None and self.cache is not None:
            self.default = self.cache
        elif self.cache is None and self.default is not None:
            self.cache = self.default
        if self.default is not None:
            for name in type(self).model_fields:
                if name in {"default", "cache", "extra"} or name in type(self)._NO_AUTO_FILL:
                    continue
                if getattr(self, name, None) is None:
                    setattr(self, name, self.default)

    def iter_config_items(self) -> list[tuple[str, _CFGT]]:
        items: list[tuple[str, _CFGT]] = []
        for field_name in type(self).model_fields:
            if field_name == "extra":
                continue
            cfg = getattr(self, field_name, None)
            if cfg is not None:
                items.append((field_name, cast(_CFGT, cfg)))
        for key, cfg in (self.extra or {}).items():
            if cfg is not None:
                items.append((key, cast(_CFGT, cfg)))
        return items

    def iter_unique_configs(self) -> list[tuple[str, _CFGT]]:
        seen: set[int] = set()
        items: list[tuple[str, _CFGT]] = []
        for key, cfg in self.iter_config_items():
            cfg_id = id(cfg)
            if cfg_id in seen:
                continue
            seen.add(cfg_id)
            items.append((key, cfg))
        return items

    def clear_cached_clients(self) -> None:
        for _, cfg in self.iter_unique_configs():
            cfg.clear_cached_client()
        self._client_singletons.clear()

    def _fuzzy_match(self, name: str) -> tuple[str, _CFGT] | None:
        normalized = _normalize_for_fuzzy(name)
        if not normalized:
            return None
        for field_name in type(self).model_fields:
            if field_name in {"default", "cache", "extra"}:
                continue
            if _normalize_for_fuzzy(field_name) == normalized:
                cfg = getattr(self, field_name, None)
                if cfg is not None:
                    return field_name, cast(_CFGT, cfg)
        for key, cfg in (self.extra or {}).items():
            if _normalize_for_fuzzy(key) == normalized:
                return key, cast(_CFGT, cfg)
        if not self.extra:
            return None
        best_prefix_key: str | None = None
        best_prefix_len = 0
        for key in self.extra:
            key_norm = _normalize_for_fuzzy(key)
            if normalized.startswith(key_norm) and len(key_norm) > best_prefix_len:
                best_prefix_key = key
                best_prefix_len = len(key_norm)
        if best_prefix_key and best_prefix_len >= 3:
            return best_prefix_key, cast(_CFGT, self.extra[best_prefix_key])
        for key in self.extra:
            key_norm = _normalize_for_fuzzy(key)
            if key_norm.startswith(normalized) and len(normalized) >= 3:
                return key, cast(_CFGT, self.extra[key])
        from difflib import SequenceMatcher
        best_key: str | None = None
        best_score = 0.0
        for key in self.extra:
            score = SequenceMatcher(None, normalized, _normalize_for_fuzzy(key)).ratio()
            if score > best_score:
                best_score = score
                best_key = key
        if best_key and best_score >= 0.8:
            return best_key, cast(_CFGT, self.extra[best_key])
        return None

    def _resolve_config_for_name(self, name: str, fallback: str = "default", *, fuzzy: bool = True) -> tuple[str, _CFGT | None]:
        if name in type(self).model_fields:
            cfg = getattr(self, name, None)
            if cfg is not None:
                return name, cast(_CFGT, cfg)
        if name in self.extra:
            return name, cast(_CFGT, self.extra[name])
        if fuzzy and name not in {"default", "cache"}:
            if matched := self._fuzzy_match(name):
                return matched
        if fallback and fallback != name:
            if fallback in type(self).model_fields:
                cfg = getattr(self, fallback, None)
                if cfg is not None:
                    return fallback, cast(_CFGT, cfg)
            if fallback in self.extra:
                return fallback, cast(_CFGT, self.extra[fallback])
        if name != "default" and self.default is not None:
            return "default", cast(_CFGT, self.default)
        return name, None

    def _evict_stale_singleton(self, client: object) -> None:
        stale_keys = [key for key, value in self._client_singletons.items() if value is client]
        for key in stale_keys:
            self._client_singletons.pop(key, None)

    def get_client(self, name: str = "default", fallback: str = "default", *, fuzzy: bool = True) -> _CT:
        if name in self._client_singletons:
            cached = self._client_singletons[name]
            if _is_cached_client_stale(cached):
                self._evict_stale_singleton(cached)
            else:
                return cast(_CT, cached)
        resolved_key, cfg = self._resolve_config_for_name(name, fallback, fuzzy=fuzzy)
        if cfg is None:
            raise ValueError(
                f"No storage config found for '{name}' (fallback='{fallback}') in {self.__class__.__name__}."
            )
        if resolved_key != name and resolved_key in self._client_singletons:
            client = self._client_singletons[resolved_key]
            if _is_cached_client_stale(client):
                self._evict_stale_singleton(client)
            else:
                self._client_singletons[name] = client
                return cast(_CT, client)
        client = cfg.client()
        self._client_singletons[resolved_key] = client
        if resolved_key != name:
            self._client_singletons[name] = client
        return cast(_CT, client)

    def get_default(self) -> _CT:
        return self.get_client("default")

    def get_cache(self) -> _CT:
        return self.get_client("cache")

    def default_client(self) -> _CT:
        return self.get_default()

    def cache_client(self) -> _CT:
        return self.get_cache()


class KV_StorageConfig(StorageConfigSection[KV_DB_ConfigBase, "KVClientBase"]):
    _NO_AUTO_FILL: ClassVar[frozenset[str]] = frozenset({
        "file_metadata", "ai_services_context",
    })

    default: KV_DB_Config | None = Field(default_factory=lambda: KV_DB_ConfigBase.FromEnv("STORAGE_KV_DB_", default_type="sqlite"))
    cache: KV_DB_Config | None = None
    extra: dict[str, KV_DB_Config] = Field(default_factory=dict)
    file_metadata: KV_DB_Config | None = None  # FileID ref counting & metadata
    ai_services_context: KV_DB_Config | None = None  # AI service shared context

    @classmethod
    def _ConfigBaseCls(cls) -> type[StorageConfigBase[Any]]:
        return KV_DB_ConfigBase


class ORMStorageConfig(StorageConfigSection[ORM_DB_ConfigBase, "ORM_ClientBase"]):
    _NO_AUTO_FILL: ClassVar[frozenset[str]] = frozenset({
        "system_metrics", "embedding_cache", "content_analyzer", "project_records",
    })

    default: ORMDBConfig | None = Field(default_factory=lambda: ORM_DB_ConfigBase.FromEnv("STORAGE_ORM_DB_", default_type="sqlite"))
    cache: ORMDBConfig | None = None
    extra: dict[str, ORMDBConfig] = Field(default_factory=dict)
    log: ORMDBConfig | None = None
    system_metrics: ORMDBConfig | None = None
    service_record: ORMDBConfig | None = None
    embedding_cache: ORMDBConfig | None = None  # AI embedding cache records
    content_analyzer: ORMDBConfig | None = None  # Content extraction/analysis cache
    project_records: ORMDBConfig | None = None  # generic business project records

    @classmethod
    def _ConfigBaseCls(cls) -> type[StorageConfigBase[Any]]:
        return ORM_DB_ConfigBase

    def get_log(self) -> "ORM_ClientBase":
        return self.get_client("log")

    def get_system_metrics(self) -> "ORM_ClientBase":
        return self.get_client("system_metrics", fallback="log")

    def get_service_record(self) -> "ORM_ClientBase":
        return self.get_client("service_record")

    def get_client(self, name: str = "default", fallback: str = "default", *, fuzzy: bool = True) -> "ORM_ClientBase":
        client = cast("ORM_ClientBase", super().get_client(name, fallback, fuzzy=fuzzy))
        preflight_map = _load_orm_preflight_map()
        if not preflight_map:
            return client
        resolved_key, _ = self._resolve_config_for_name(name, fallback, fuzzy=fuzzy)
        forgotten = cast(set[str], getattr(client, "_forgotten_collections", set()))
        for key in dict.fromkeys((name, resolved_key)):
            for collection_name in preflight_map.get(key, []):
                if collection_name in forgotten:
                    continue
                try:
                    client.mark_collection_bootstrapped(collection_name)
                except Exception:
                    continue
        return client


class VectorStorageConfig(StorageConfigSection[VectorDB_ConfigBase, "VectorClientBase"]):
    default: VectorDBConfig | None = Field(default_factory=lambda: VectorDB_ConfigBase.FromEnv("STORAGE_VECTOR_DB_", default_type=_default_vector_backend()))
    cache: VectorDBConfig | None = None
    extra: dict[str, VectorDBConfig] = Field(default_factory=dict)

    @classmethod
    def _ConfigBaseCls(cls) -> type[StorageConfigBase[Any]]:
        return VectorDB_ConfigBase

    def get_client(self, name: str = "default", fallback: str = "default", *, fuzzy: bool = True) -> "VectorClientBase":
        client = cast("VectorClientBase", super().get_client(name, fallback, fuzzy=fuzzy))
        preflight_map = _load_vector_preflight_map()
        if not preflight_map:
            return client
        resolved_key, _ = self._resolve_config_for_name(name, fallback, fuzzy=fuzzy)
        marker = getattr(client, "mark_collection_bootstrapped", None)
        if not callable(marker):
            marker = getattr(client, "_mark_collection_bootstrapped", None)
        if not callable(marker):
            return client
        forgotten = cast(set[str], getattr(client, "_forgotten_collections", set()))
        for key in dict.fromkeys((name, resolved_key)):
            for collection_name in preflight_map.get(key, []):
                if collection_name in forgotten:
                    continue
                try:
                    marker(collection_name)
                except Exception:
                    continue
        return client


class ObjectStorageConfig(StorageConfigSection[ObjectDB_ConfigBase, "ObjectClientBase"]):
    _NO_AUTO_FILL: ClassVar[frozenset[str]] = frozenset({"project_assets"})

    default: ObjectDBConfig | None = Field(default_factory=lambda: ObjectDB_ConfigBase.FromEnv("STORAGE_OBJECT_DB_", default_type="local"))
    cache: ObjectDBConfig | None = None
    extra: dict[str, ObjectDBConfig] = Field(default_factory=dict)
    temp_file_upload: ObjectDBConfig | None = None
    project_assets: ObjectDBConfig | None = None  # generic business assets

    @classmethod
    def _ConfigBaseCls(cls) -> type[StorageConfigBase[Any]]:
        return ObjectDB_ConfigBase

    def get_temp_file_upload(self) -> "ObjectClientBase":
        return self.get_client("temp_file_upload")


class StorageConfig(AdvancedBaseModel):
    __Instance__: ClassVar[Self | None] = None

    kv: KV_StorageConfig = Field(default_factory=KV_StorageConfig)
    orm: ORMStorageConfig = Field(default_factory=ORMStorageConfig)
    vector: VectorStorageConfig = Field(default_factory=VectorStorageConfig)
    object: ObjectStorageConfig = Field(default_factory=ObjectStorageConfig)

    @model_validator(mode="before")
    @classmethod
    def _drop_none_sections(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for section_key in ("kv", "orm", "vector", "object"):
            if data.get(section_key) is None:
                data.pop(section_key, None)
        return data

    def iter_sections(self) -> list[tuple[StorageCategory, StorageConfigSection[Any, Any]]]:
        return [
            ("kv", self.kv),
            ("orm", self.orm),
            ("vector", self.vector),
            ("object", self.object),
        ]

    def to_serialized_env(self) -> str:
        return self.model_dump_json()

    @classmethod
    def _try_load_from_env(cls) -> Self | None:
        env_data = os.getenv(_STORAGE_CONFIG_ENV)
        if not env_data:
            return None
        try:
            payload = json.loads(env_data)
            return cls.model_validate(payload)
        except Exception as exc:
            _logger.warning("Failed to load storage config from %s: %s", _STORAGE_CONFIG_ENV, exc)
            return None

    @classmethod
    def _try_load_from_files(cls, *, prefer_mode_specific: bool | None = None) -> Self | None:
        for path in _discover_storage_config_paths(prefer_mode_specific=prefer_mode_specific):
            if not path.is_file():
                continue
            try:
                payload = _load_storage_config_from_file(path)
                config = cls.model_validate(payload)
                _logger.info("Auto-discovered storage config from %s", path)
                return config
            except Exception as exc:
                _logger.warning("Failed to load storage config from %s: %s", path, exc)
        return None

    @classmethod
    def AutoLoad(cls, *, prefer_mode_specific: bool | None = None) -> Self | None:
        return cls._try_load_from_env() or cls._try_load_from_files(prefer_mode_specific=prefer_mode_specific)

    @classmethod
    def Global(cls) -> Self:
        if cls.__Instance__ is not None:
            return cls.__Instance__
        config = cls.AutoLoad(prefer_mode_specific=_prefer_mode_specific_default_paths()) or cls()
        return cls.SetGlobal(config)

    @classmethod
    def SetGlobal(cls, config: Self) -> Self:
        cls.__Instance__ = config
        os.environ[_STORAGE_CONFIG_ENV] = config.to_serialized_env()
        for _, section in config.iter_sections():
            section.clear_cached_clients()
        StorageClientBase.ClearDefaultInstances()
        try:
            from .orm import ORMModel
            ORMModel.ResetClientBindings()
        except Exception:
            pass
        return config

    def get_kv_client(self, name: str = "default", fallback: str = "default", *, fuzzy: bool = True) -> "KVClientBase":
        return self.kv.get_client(name, fallback, fuzzy=fuzzy)

    def get_orm_client(self, name: str = "default", fallback: str = "default", *, fuzzy: bool = True) -> "ORM_ClientBase":
        return self.orm.get_client(name, fallback, fuzzy=fuzzy)

    def get_log_orm_client(self, name: str = "log", fallback: str = "default", *, fuzzy: bool = True) -> "ORM_ClientBase":
        return self.orm.get_client(name, fallback, fuzzy=fuzzy)

    def get_vector_client(self, name: str = "default", fallback: str = "default", *, fuzzy: bool = True) -> "VectorClientBase":
        return self.vector.get_client(name, fallback, fuzzy=fuzzy)

    def get_object_client(self, name: str = "default", fallback: str = "default", *, fuzzy: bool = True) -> "ObjectClientBase":
        return self.object.get_client(name, fallback, fuzzy=fuzzy)


async def _close_storage_client_instance(client: object) -> None:
    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        try:
            close_result = aclose()
            if inspect.isawaitable(close_result):
                await close_result
            return
        except Exception as exc:
            _logger.warning("Storage client async close failed for %s: %s", type(client).__name__, exc)

    close = getattr(client, "close", None)
    if callable(close):
        try:
            close_result = close()
            if inspect.isawaitable(close_result):
                await close_result
        except Exception as exc:
            _logger.warning("Storage client close failed for %s: %s", type(client).__name__, exc)


async def close_global_storage_clients() -> None:
    config = StorageConfig.__Instance__
    if config is None:
        return

    for _, section in config.iter_sections():
        clients: list[object] = []
        seen_client_ids: set[int] = set()
        for client in section._client_singletons.values():
            client_id = id(client)
            if client_id in seen_client_ids:
                continue
            seen_client_ids.add(client_id)
            clients.append(client)
        for _, cfg in section.iter_unique_configs():
            cached = cast(dict[str, Any], cfg.__dict__).get("__client__", None)
            if cached is None:
                continue
            client_id = id(cached)
            if client_id in seen_client_ids:
                continue
            seen_client_ids.add(client_id)
            clients.append(cached)

        for client in clients:
            await _close_storage_client_instance(client)

        section.clear_cached_clients()

    StorageClientBase.ClearDefaultInstances()
    try:
        from .orm import ORMModel

        ORMModel.ResetClientBindings()
    except Exception:
        pass


__all__ = [
    "SSHTunnelConfig",
    "KV_Backend",
    "KV_DB_ConfigBase",
    "KV_DB_Config",
    "LocalKVDBConfig",
    "RedisKVDBConfig",
    "EtcdKVDBConfig",
    "MilvusLiteVectorDBConfig",
    "MilvusVectorDBConfig",
    "AnnoyVectorDBConfig",
    "RedisVectorDBConfig",
    "MongoVectorDBConfig",
    "ORM_Backend",
    "ORM_DB_ConfigBase",
    "ORMDBConfig",
    "MongoORM_DB_Config",
    "MySQL_ORM_DB_Config",
    "PostgreSQL_ORM_DB_Config",
    "RedisORMDBConfig",
    "SQLiteORMDBConfig",
    "SQL_ORM_DB_Config",
    "ObjectBackend",
    "ObjectDBConfig",
    "ObjectDB_ConfigBase",
    "LocalObjectDBConfig",
    "MinIO_ObjectDB_Config",
    "VectorBackend",
    "VectorDBConfig",
    "VectorDB_ConfigBase",
    "StorageConfigBase",
    "StorageConfigSection",
    "KV_StorageConfig",
    "ORMStorageConfig",
    "VectorStorageConfig",
    "ObjectStorageConfig",
    "StorageConfig",
    "close_global_storage_clients",
]
