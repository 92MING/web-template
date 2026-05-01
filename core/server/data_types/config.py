
import os
import yaml
import json
import socket
import logging
import argparse

from pathlib import Path
from datetime import datetime
from typing import Any, ClassVar, Literal, Self, TypedDict
from pydantic import BaseModel, Field, field_validator

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler as _TimedRotatingFileHandler
except ImportError:  # pragma: no cover
    from logging.handlers import TimedRotatingFileHandler as _TimedRotatingFileHandler  # type: ignore

from core.rtc_chat.config import ChatRoomConfig, AudioConfig, WebRTCConfiguration, WebRTCIceServer
from core.constants import PROJECT_DIR
from core.server.constants import (
    SERVER_DIR,
    ADMIN_PANEL_DIR,
    ADMIN_PANEL_SHARED_DIR,
    PUBLIC_VENDOR_DIR,
    DEFAULT_LOG_DIR,
    DEFAULT_CONFIG_PATH,
)
from core.storage.config import StorageConfig
from core.utils.log_utils import ORMLogHandler

_logger = logging.getLogger(__name__)

class _CommonUvicornNoiseLogFilter(logging.Filter):
    _ignored_fragments = (
        "opening handshake failed",
        "connection closed while reading http request line",
        "no close frame received or sent",
    )
    
    def __init__(self, strategy: Literal['degrade', 'ignore']):
        super().__init__()
        self._strategy = strategy.lower()

    def filter(self, record: logging.LogRecord) -> bool:
        # Filter out noisy Uvicorn WebSocket handshake failure logs (degrade to DEBUG or drop)
        message = record.getMessage().lower()
        if any(f in message for f in self._ignored_fragments):
            if self._strategy == "degrade":
                record.levelno = logging.DEBUG
                record.levelname = "DEBUG"
            elif self._strategy == "ignore":
                return False
        return True

class _LogPrefixFilter(logging.Filter):
    def __init__(self, *filter_prefixes: str):
        super().__init__()
        self._filter_prefixes = set(filter_prefixes)
    
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        return not any(message.startswith(prefix) for prefix in self._filter_prefixes)


def _correct_uvicorn_loggers(log_level: int) -> None:
    """Reset the three uvicorn loggers so records propagate to root handlers.

    uvicorn's own ``dictConfig`` may attach empty handler lists and in some
    re-import scenarios also disable propagation. This helper forces a
    known-good state: no local handlers, propagate=True, level at
    ``log_level``, not disabled. Safe to call repeatedly.
    """
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.setLevel(log_level)
        lg.propagate = True
        lg.disabled = False

# Backward-compatible aliases (deprecated, prefer core.server.constants)
SERVER_HTML_DIR = ADMIN_PANEL_DIR
HTML_SHARED_DIR = ADMIN_PANEL_SHARED_DIR
VENDOR_DIR = PUBLIC_VENDOR_DIR

SUPPORTED_CONFIG_WRITE_SUFFIXES = {".json", ".yaml", ".yml"}
SUPPORTED_CONFIG_READ_SUFFIXES = {".json", ".yaml", ".yml", ".toml"}
_CONFIG_FILE_SUFFIXES: tuple[str, ...] = (".yaml", ".yml", ".json", ".toml")
_SERVER_RUNTIME_ENV_KEYS: tuple[str, ...] = (
    "IN_UVICORN_PROCESS",
    "__SERVER_PROCESS_PID__",
    "__SERVER_SUPERVISOR_PID__",
    "__SERVER_INSTANCE_ID__",
)

__all__ = [
    "SERVER_DIR",
    "SERVER_HTML_DIR",
    "HTML_SHARED_DIR",
    "VENDOR_DIR",
    "ADMIN_PANEL_DIR",
    "ADMIN_PANEL_SHARED_DIR",
    "PUBLIC_VENDOR_DIR",
    "DEFAULT_LOG_DIR",
    "DEFAULT_CONFIG_PATH",
    "RuntimeConfigPathInfo",
    "ServerConfig",
    "LogConfig",
    "WebRTCRoomConfig",
    "Config",
]

# ---- Helpers ----
def _get_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default

def _get_bool_env(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower().strip() in ("true", "1", "yes")

def _get_path_list_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, None)
    if raw is None:
        return list(default)
    text = str(raw).strip()
    if not text:
        return list(default)
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                items = [str(item).strip() for item in data if str(item).strip()]
                return items or list(default)
        except Exception:
            pass
    normalized = text.replace("\r", "\n").replace(";", "\n").replace(",", "\n")
    items = [part.strip() for part in normalized.split("\n") if part.strip()]
    return items or list(default)

def _default_log_path() -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return str(os.getenv("LOG_PATH") or (DEFAULT_LOG_DIR / ts))

def _prefer_mode_specific_default_paths() -> bool:
    return any(str(os.getenv(key, "") or "").strip() for key in _SERVER_RUNTIME_ENV_KEYS)


def _default_config_roots() -> list[Path]:
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


def _default_config_name_order(*, prefer_mode_specific: bool | None = None) -> list[str]:
    prefer_mode_specific = _prefer_mode_specific_default_paths() if prefer_mode_specific is None else prefer_mode_specific
    mode = str(os.getenv("__MODE__", "")).strip().lower()
    if prefer_mode_specific and mode in {"dev", "prod"}:
        opposite_mode = "prod" if mode == "dev" else "dev"
        return [f"server.{mode}", "server", f"server.{opposite_mode}", f"{mode}_server", f"{opposite_mode}_server"]
    return ["server", "server.dev", "server.prod", "dev_server", "prod_server"]


def _iter_default_config_candidates(*, prefer_mode_specific: bool | None = None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in _default_config_roots():
        config_dir = root / "config"
        for stem in _default_config_name_order(prefer_mode_specific=prefer_mode_specific):
            for suffix in _CONFIG_FILE_SUFFIXES:
                candidate = config_dir / f"{stem}{suffix}"
                if candidate in seen:
                    continue
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def _discover_existing_default_config_path(*, prefer_mode_specific: bool | None = None) -> Path | None:
    """Return the first existing default server config candidate, if any."""
    for candidate in _iter_default_config_candidates(prefer_mode_specific=prefer_mode_specific):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _default_config_write_path() -> Path:
    return (_default_config_roots()[0] / "config" / "server.yaml").resolve()


def _clean_optional_path(path: str | Path | None) -> str | None:
    if path is None:
        return None
    text = str(path).strip()
    return text or None

def _normalize_config_path(path: str | Path | None) -> Path:
    text = _clean_optional_path(path)
    if text is None:
        return _default_config_write_path()
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = candidate.resolve()
    return candidate

def _load_serialized_config(config_text: str, *, source_name: str = "<string>", format_hint: str | None = None) -> dict[str, Any]:
    """Parse serialized config text from JSON/TOML/YAML into a dict."""
    normalized_hint = (format_hint or "").lower().lstrip(".")
    errors: list[str] = []

    def _ensure_mapping(value: Any, parser_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{parser_name} config root must be an object/mapping, got {type(value).__name__}.")
        return value

    parsers: list[tuple[str, Any]]
    if normalized_hint in {"json", "toml", "yaml", "yml"}:
        parsers = [
            ("json", lambda text: json.loads(text)),
            ("toml", lambda text: tomllib.loads(text)),
            ("yaml", lambda text: yaml.safe_load(text)),
        ]
        parser_order = {
            "json": [parsers[0]],
            "toml": [parsers[1]],
            "yaml": [parsers[2]],
            "yml": [parsers[2]],
        }[normalized_hint]
    else:
        parser_order = [
            ("json", lambda text: json.loads(text)),
            ("toml", lambda text: tomllib.loads(text)),
            ("yaml", lambda text: yaml.safe_load(text)),
        ]

    for parser_name, parser in parser_order:
        try:
            return _ensure_mapping(parser(config_text), parser_name.upper())
        except Exception as exc:
            errors.append(f"{parser_name.upper()}: {exc}")

    supported = "JSON, TOML, YAML"
    hint_msg = f" (detected from extension '.{normalized_hint}')" if normalized_hint else ""
    joined = "; ".join(errors)
    raise ValueError(f"Failed to parse config from {source_name}{hint_msg}. Supported formats: {supported}. Details: {joined}")

def _load_config_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix not in {".json", ".toml", ".yaml", ".yml"}:
        raise ValueError(
            f"Unsupported config file format: '{path.suffix}'. Expected one of .json, .toml, .yaml, .yml"
        )
    return _load_serialized_config(
        path.read_text(encoding="utf-8"),
        source_name=str(path),
        format_hint=suffix,
    )


def _warn_and_use_default_subconfig(field_name: str, exc: Exception | str, default_factory):
    _logger.warning(
        "Config.%s validation failed: %s. Falling back to default config.",
        field_name,
        exc,
    )
    return default_factory()

_DEFAULT_DEV_PORT = _get_int_env("DEV_PORT", 8000)
_DEFAULT_PROD_PORT = _get_int_env("PROD_PORT", 9191)

class _AutoDocstringModel(BaseModel, use_attribute_docstrings=True): ...

class RuntimeConfigPathInfo(TypedDict):
    """Resolved runtime source/save paths for the server config UI."""
    source_path: str | None
    source_exists: bool
    write_path: str
    write_note: str | None

class ServerConfig(_AutoDocstringModel):
    host: str | None = Field(default_factory=lambda: os.getenv("HOST", os.getenv("__HOST__", None)))
    """Host address. ``None`` — auto-select based on mode."""
    port: int = Field(default_factory=lambda: _get_int_env("PORT", _get_int_env("__PORT__", -1)))
    """Port number (``-1`` — find a free port)."""
    frontend_baseurl: str | None = Field(default_factory=lambda: os.getenv("FRONTEND_BASEURL", None))
    """Optional request base URL injected into frontend HTML pages."""
    worker: int = Field(default_factory=lambda: (
        int(os.getenv("WORKER")) if os.getenv("WORKER") is not None else (
            min(30, max(1, (os.cpu_count() or 2) // 2))
            if os.getenv("__MODE__", "dev").lower() == "prod"
            else 1
        )
    ))
    """Number of uvicorn worker processes."""
    reload: bool = Field(default_factory=lambda: _get_bool_env("RELOAD", False))
    """Enable auto-reload (dev mode)."""
    description: str = "Server"
    """Server description shown in ``--help`` and API docs."""
    force_exit_timeout: int = Field(default_factory=lambda: _get_int_env("FORCE_EXIT_TIMEOUT", 8))
    """Seconds to wait before force-exit on shutdown."""
    system_allowed_roots: list[str] = Field(
        default_factory=lambda: _get_path_list_env(
            "SYSTEM_ALLOWED_ROOTS",
            [str(PROJECT_DIR), str(SERVER_DIR)],
        )
    )
    """Allowed filesystem roots for the system terminal/file pages."""
    system_default_root: str | None = Field(default_factory=lambda: os.getenv("SYSTEM_DEFAULT_ROOT", str(PROJECT_DIR)))
    """Preferred default root shown in the system tools UI."""
    system_terminal_default_cwd: str | None = Field(default_factory=lambda: os.getenv("SYSTEM_TERMINAL_DEFAULT_CWD", str(PROJECT_DIR)))
    """Default cwd for newly created terminal sessions."""
    system_terminal_max_sessions: int = Field(default_factory=lambda: _get_int_env("SYSTEM_TERMINAL_MAX_SESSIONS", 6))
    """Per-worker cap for concurrent interactive terminal sessions."""
    internal_path_prefix: str | None = Field(default_factory=lambda: os.getenv("INTERNAL_PATH_PREFIX", "/_internal"))
    """Prefix for internal routes. ``None`` exposes them without an additional prefix."""
    expose_internal_prefix: bool = Field(default_factory=lambda: _get_bool_env("EXPOSE_INTERNAL_PREFIX", True))
    """Whether internal routes and admin panel routes are exposed."""
    internal_path_allowed_ip: str | list[str] | Literal["all"] = Field(
        default_factory=lambda: os.getenv("INTERNAL_PATH_ALLOWED_IP", None) or ["localhost", "127.0.0.1"]
    )
    """IP patterns allowed to access internal routes. Use ``'all'`` to disable IP checks."""
    expose_ai_service: bool = Field(default_factory=lambda: _get_bool_env("EXPOSE_AI_SERVICE", False))
    """Whether to expose public AI service aliases (``/ai/*``). Internal AI APIs live under ``internal_path_prefix/ai/*``."""
    enable_rtc_chatroom: bool = Field(default_factory=lambda: _get_bool_env("ENABLE_RTC_CHATROOM", False))
    """Whether RTC chat-room routes and shared UI are exposed."""
    extra_app_paths: str | list[str] | None = Field(default=None)
    """Additional app directories scanned before the project app directory."""
    extra_public_paths: str | list[str] | None = Field(default=None)
    """Additional public/static file directories to serve (str or list of str)."""
    extra_resources_paths: str | list[str] | None = Field(default=None)
    """Additional resource directories (not directly exposed via HTTP) (str or list of str)."""

    def model_post_init(self, __context: Any) -> None:
        if self.internal_path_prefix is not None:
            text = str(self.internal_path_prefix).strip()
            self.internal_path_prefix = None if not text else "/" + text.strip("/")

    def is_ai_service_exposed(self) -> bool:
        return bool(self.expose_ai_service)

    def is_internal_exposed(self) -> bool:
        return bool(self.expose_internal_prefix)

    def get_internal_path(self, path: str = "") -> str:
        normalized = "/" + str(path or "").strip("/")
        if normalized == "/":
            normalized = ""
        prefix = self.internal_path_prefix
        if prefix is None:
            return normalized or "/"
        return (prefix.rstrip("/") + normalized) or "/"

    def get_internal_admin_path(self, path: str = "") -> str:
        suffix = "/admin" + ("/" + str(path).strip("/") if str(path).strip("/") else "")
        return self.get_internal_path(suffix)

    def is_internal_path(self, path: str) -> bool:
        normalized = "/" + str(path or "").lstrip("/")
        if self.internal_path_prefix is None:
            return normalized.startswith("/admin") or normalized.startswith("/ai")
        prefix = self.internal_path_prefix.rstrip("/")
        return normalized == prefix or normalized.startswith(prefix + "/")

    def get_internal_path_allowed_ip_patterns(self) -> list[str] | None:
        raw = self.internal_path_allowed_ip
        if raw is None:
            return None
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            if text.lower() == "all":
                return None
            if text.lower() == "localhost":
                return ["127.0.0.1", "::1", "localhost"]
            if any(ch in text for ch in ",;\n\r"):
                normalized = text.replace("\r", "\n").replace(";", "\n").replace(",", "\n")
                return [part.strip() for part in normalized.split("\n") if part.strip()] or None
            return [text]
        patterns: list[str] = []
        for item in raw:
            text = str(item).strip()
            if not text:
                continue
            if text.lower() == "all":
                return None
            if text.lower() == "localhost":
                patterns.extend(["127.0.0.1", "::1", "localhost"])
            else:
                patterns.append(text)
        return list(dict.fromkeys(patterns)) or None

    def get_host(self, default_mode: Literal["prod", "dev"] | None = None) -> str:
        if default_mode is None:
            default_mode = "dev" if os.getenv("__MODE__", "dev").lower() == "dev" else "prod"
        if not self.host or self.host.lower().strip() == "localhost":
            return "127.0.0.1" if default_mode == "dev" else "0.0.0.0"
        return self.host

    @staticmethod
    def _check_port_available(host: str, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
            return True
        except OSError:
            return False

    def get_port(self, default_mode: Literal["prod", "dev"] | None = None) -> int:
        if self.port > 0:
            return self.port
        if default_mode is None:
            default_mode = "dev" if os.getenv("__MODE__", "dev").lower() == "dev" else "prod"
        host = self.get_host(default_mode)
        from_port = _DEFAULT_PROD_PORT if default_mode == "prod" else _DEFAULT_DEV_PORT
        for port in range(from_port, 32768):
            if self._check_port_available(host, port):
                return port
            if port == from_port and default_mode == "prod":
                raise RuntimeError(f"Default production port {from_port} is not available.")
        raise RuntimeError(f"No free port found in range {from_port}-32768.")

    def get_frontend_baseurl(self) -> str | None:
        raw = (self.frontend_baseurl or "").strip()
        if not raw:
            return None
        return raw.rstrip("/")

type LogLevel = Literal["debug", "info", "warning", "error", "critical"]

class LogConfig(_AutoDocstringModel):
    log_level: LogLevel | None = Field(default_factory=lambda: os.getenv("LOG_LEVEL", None))  # type: ignore
    """Logging level (``None`` — mode-dependent default)."""
    log_path: str = Field(default_factory=_default_log_path)
    """Base directory for log files. In db mode, logs go to storage_config.orm.log instead."""
    log_method: list[Literal["file", "db"]] = Field(
        default_factory=lambda: [
            m.strip()
            for m in os.getenv("LOG_METHOD", "db").split(",")
            if m.strip() in ("file", "db")
        ]
        or ["db"]
    )  # type: ignore
    """Log output methods: ``file`` writes to disk; ``db`` persists via storage log_db."""
    log_format: str = Field(
        default_factory=lambda: os.getenv(
            "LOG_FORMAT",
            "(%(process)d)[%(levelname)s](%(name)s) %(asctime)s | %(message)s",
        )
    )
    """Log message format."""
    log_time_format: str = Field(default_factory=lambda: os.getenv("LOG_TIME_FORMAT", "%Y-%m-%d %H:%M:%S"))
    """Timestamp format for log messages."""
    filtering_logger_prefixes: str|list[str] = Field(default_factory=lambda: os.getenv("LOG_FILTERING_PREFIXES", []))
    '''Comma-separated log message prefixes to filter out (case-insensitive). Applies to ORM persistence logs and Uvicorn access logs by default.'''
    uvicorn_noise_handling_strategy: Literal['degrade', 'ignore', 'none'] = Field(default_factory=lambda: os.getenv("LOG_COMMON_NOISE_STRATEGY", "degrade").lower()) # type: ignore
    '''Strategy for handling common uvicorn noisy log messages (e.g. Uvicorn WebSocket handshake failures): "degrade" (lower to DEBUG), "ignore" (filter out), "none" (leave as is).'''
    
    system_metrics_interval: int = Field(default_factory=lambda: _get_int_env("SYSTEM_METRICS_INTERVAL", 2))
    """Seconds between system-metric snapshots."""
    system_metrics_retention_hours: int = Field(default_factory=lambda: _get_int_env("SYSTEM_METRICS_RETENTION_HOURS", 72))
    """Hours to retain persisted system-metric snapshots in db mode. Set to ``0`` to disable TTL cleanup."""
    
    # file mode settings
    log_backup_count: int = Field(default_factory=lambda: _get_int_env("LOG_BACKUP_COUNT", 14))
    """(file mode only) Number of rotated backup files to keep."""
    zip_old_logs: bool = Field(default_factory=lambda: _get_bool_env("LOG_ZIP_OLD_LOGS", False))
    """(file mode only) Whether to compress old log files on rotation."""
    log_rotation_interval: int = Field(default_factory=lambda: _get_int_env("LOG_ROTATION_INTERVAL", 24))
    """(file mode only) Log rotation interval in hours."""
    rotation_time: str = Field(default_factory=lambda: os.getenv("LOG_ROTATION_TIME", "00:00"))
    """(file mode only) Time-of-day to rotate logs (HH:MM, 24-hour)."""

    def get_orm_log_store(self):
        """Get the ORM log store. Returns None if db mode is disabled."""
        if "db" not in self.log_method:
            return None
        try:
            from core.storage.config import StorageConfig
            from core.storage.orm import get_default_log_store, get_log_record_model
            cfg = StorageConfig.Global()
            client = cfg.get_log_orm_client()
            collection_name = str(getattr(cfg.orm.log, "log_collection_name", "log") or "log")
            return get_default_log_store(client, lambda: get_log_record_model(collection_name))
        except Exception:
            return None

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value):
        if isinstance(value, int):
            value = logging.getLevelName(value).lower()
        if isinstance(value, str):
            value = value.lower().strip()
        return value
    
    @field_validator('filtering_logger_prefixes')
    @classmethod
    def _validate_filtering_prefixes(cls, value):
        if isinstance(value, str):
            if not value.strip():
                return []
            elif '[' in value and ']' in value:
                try:
                    data = json.loads(value)
                    if isinstance(data, list):
                        return [str(item).strip() for item in data if str(item).strip()]
                except Exception:
                    pass
            elif ',' in value or ';' in value or '\n' in value:
                normalized = value.replace("\r", "\n").replace(";", "\n").replace(",", "\n")
                return [part.strip() for part in normalized.split("\n") if part.strip()]
        return value or []

    def get_int_log_level(self, default_mode: Literal["prod", "dev"] | None = None) -> int:
        if self.log_level is None:
            if default_mode is None:
                default_mode = "dev" if os.getenv("__MODE__", "dev").lower() == "dev" else "prod"
            return logging.INFO if default_mode == "prod" else logging.DEBUG
        return getattr(logging, self.log_level.upper(), logging.INFO)

    def get_file_log_path(self) -> str:
        """Return the resolved log file path (``log.log``), creating parent dirs."""
        log_path = Path(self.log_path) / "log.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return str(log_path)

    def get_rotation_at_time(self):
        """Parse ``rotation_time`` ("HH:MM") to a ``datetime.time``. Falls back to midnight."""
        try:
            hr, mint = self.rotation_time.split(":")
            return datetime.strptime(f"{hr}:{mint}", "%H:%M").time()
        except (ValueError, AttributeError):
            return datetime.strptime("00:00", "%H:%M").time()

    def init_root_logger(
        self,
        root_logger: logging.Logger,
        default_mode: Literal["prod", "dev"] | None = None,
    ) -> logging.Logger:
        """Attach handlers (console + optional file/ORM-db) to *root_logger*."""
        if default_mode is None:
            default_mode = "dev" if os.getenv("__MODE__", "dev").lower() == "dev" else "prod"
        formatter = logging.Formatter(fmt=self.log_format, datefmt=self.log_time_format)
        log_level = self.get_int_log_level(default_mode=default_mode)

        if not any(
            isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
            for h in root_logger.handlers
        ):
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            root_logger.addHandler(console)

        if "file" in self.log_method:
            file_log_path = self.get_file_log_path()
            has_file = any(
                isinstance(h, _TimedRotatingFileHandler)
                and str(getattr(h, "baseFilename", "")) == file_log_path
                for h in root_logger.handlers
            )
            if not has_file:
                file_handler = _TimedRotatingFileHandler(
                    file_log_path,
                    when="h",
                    interval=self.log_rotation_interval,
                    backupCount=self.log_backup_count,
                    encoding="utf-8",
                )
                if self.zip_old_logs:
                    file_handler.namer = lambda name: name + ".gz"  # type: ignore
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)

        if "db" in self.log_method:
            # Avoid registering a second ORMLogHandler
            has = any(isinstance(h, ORMLogHandler) for h in root_logger.handlers)
            if not has:
                try:
                    from core.storage.config import StorageConfig
                    from core.storage.orm import get_default_log_store, get_log_record_model
                    cfg = StorageConfig.Global()
                    client = cfg.get_log_orm_client()
                    collection_name = str(getattr(cfg.orm.log, "log_collection_name", "log") or "log")
                    store = get_default_log_store(client, lambda: get_log_record_model(collection_name))
                    orm_handler = ORMLogHandler(store, level=log_level)
                    orm_handler.setLevel(log_level)
                    if self.filtering_logger_prefixes:
                        if isinstance(self.filtering_logger_prefixes, str):
                            prefixes = [self.filtering_logger_prefixes.strip().lower()]
                        else:
                            prefixes = [p.strip().lower() for p in self.filtering_logger_prefixes if p.strip()]
                        if not any(isinstance(f, _LogPrefixFilter) for f in orm_handler.filters):
                            orm_handler.addFilter(_LogPrefixFilter(*prefixes))
                    orm_handler.setFormatter(formatter)
                    root_logger.addHandler(orm_handler)
                except Exception as _e:
                    root_logger.warning(f"LogConfig: failed to attach ORM log handler: {_e}")

        if self.uvicorn_noise_handling_strategy != "none":
            uvicorn_error_logger = logging.getLogger("uvicorn.error")
            if not any(isinstance(f, _CommonUvicornNoiseLogFilter) for f in uvicorn_error_logger.filters):
                uvicorn_error_logger.addFilter(_CommonUvicornNoiseLogFilter(self.uvicorn_noise_handling_strategy))

        root_logger.setLevel(log_level)
        # Explicit correction for uvicorn loggers: ensure they propagate to
        # root so the handlers we just attached pick up their records. uvicorn's
        # own dictConfig may fight this ordering; a second correction is also
        # applied from the lifespan startup hook after dictConfig runs.
        _correct_uvicorn_loggers(log_level)
        return root_logger

    def get_uvicorn_log_config(self, default_mode: Literal["prod", "dev"] | None = None) -> dict:
        """Return a uvicorn-compatible log config dict that reuses root handlers.

        Uses ``incremental: True`` so ``dictConfig`` only updates the uvicorn
        loggers' levels without touching the root logger or recreating
        handlers/formatters — this prevents uvicorn from inadvertently
        clearing the handlers we already attached to root.
        """
        lvl = self.get_int_log_level(default_mode=default_mode)
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "incremental": True,
            "loggers": {
                "uvicorn": {"level": lvl},
                "uvicorn.error": {"level": lvl},
                "uvicorn.access": {"level": lvl},
            },
        }

class WebRTCRoomConfig(_AutoDocstringModel):
    """Settings specific to the WebRTC chat-room subsystem.

    On ``apply()`` these values are pushed to
    ``core.rtc_chat.config.ChatRoomConfig`` so the chat-room
    module picks them up transparently.
    """

    rtc_room_enable: bool = Field(default_factory=lambda: _get_bool_env("RTC_ROOM_ENABLE", False))
    """Whether RTC room UI and APIs are exposed."""

    audio_sample_rate: int = Field(default_factory=lambda: _get_int_env("AUDIO_SAMPLE_RATE", 16000))
    """Default sample rate (Hz)."""
    min_silence_ms: int = Field(default_factory=lambda: _get_int_env("MIN_SILENCE_MS", 1000))
    """Minimum silence duration to end a voice segment (ms)."""
    min_voice_ms: int = Field(default_factory=lambda: _get_int_env("MIN_VOICE_MS", 200))
    """Minimum voice duration for a valid segment (ms)."""
    mid_silence_ms: int = Field(default_factory=lambda: _get_int_env("MID_SILENCE_MS", 500))
    """Silence inserted between TTS segments (ms)."""
    max_segment_ms: int = Field(default_factory=lambda: _get_int_env("MAX_SEGMENT_MS", 10000))
    """Maximum single voice segment duration (ms)."""
    min_energy_rms: int = Field(default_factory=lambda: _get_int_env("MIN_ENERGY_RMS", 200))
    """Minimum RMS energy for energy-based VAD."""

    ice_servers: list[WebRTCIceServer] | None = Field(default=None)
    """Optional list of ICE servers for WebRTC. Validated via :class:`WebRTCIceServer`."""
    bundle_policy: str = Field(default_factory=lambda: os.getenv("BUNDLE_POLICY", "balanced"))
    """WebRTC bundle policy: ``balanced``, ``max-compat``, or ``max-bundle``."""

    def apply(self):
        """Push these values into ``ChatRoomConfig`` singleton."""
        audio = AudioConfig(
            audio_sample_rate=self.audio_sample_rate,
            min_silence_ms=self.min_silence_ms,
            min_voice_ms=self.min_voice_ms,
            mid_silence_ms=self.mid_silence_ms,
            max_segment_ms=self.max_segment_ms,
            min_energy_rms=self.min_energy_rms,
        )
        rtc: WebRTCConfiguration | None = None
        if self.ice_servers:
            rtc = WebRTCConfiguration(
                iceServers=self.ice_servers,
                bundlePolicy=self.bundle_policy,
            )

        cfg = ChatRoomConfig(audio_config=audio, rtc_config=rtc)
        ChatRoomConfig.SetConfig(cfg)


# ---- AI services config helpers ----

def _resolve_ai_services_config(raw: str):
    """Load an ``AIServicesConfig`` from a file path or inline JSON/YAML string."""
    from core.ai.config import AIServicesConfig

    candidate = Path(raw)
    try:
        path_exists = candidate.exists()
    except OSError:
        path_exists = False
    if path_exists:
        data = _load_config_file(candidate)
        return AIServicesConfig.model_validate(data)
    # Treat as serialized text
    data = _load_serialized_config(raw, source_name="--ai-services-config")
    return AIServicesConfig.model_validate(data)


def _auto_discover_ai_services_config():
    """Auto-discover AI services config using runtime-specific default-path priority."""
    from core.ai.config import AIServicesConfig
    return AIServicesConfig.AutoLoad(prefer_mode_specific=True)


class Config(_AutoDocstringModel):
    """
    Runtime configuration holder — aggregates all sub-configs.
    Server/core config see docs/config/server_example.yaml.
    Storage / AI services configs are managed by their respective modules.
    """

    __Instance__: ClassVar[Self | None] = None

    server_config: ServerConfig = Field(default_factory=ServerConfig)
    """Server (host, port, workers, …)."""
    log_config: LogConfig = Field(default_factory=LogConfig)
    """Logging configuration."""
    rtc_room_config: WebRTCRoomConfig = Field(default_factory=WebRTCRoomConfig)
    """WebRTC chat-room subsystem settings."""

    @field_validator("server_config", mode="before")
    @classmethod
    def _validate_server_config_field(cls, value):
        if value is None:
            return _warn_and_use_default_subconfig("server_config", "received null value", ServerConfig)
        if isinstance(value, ServerConfig):
            return value
        try:
            return ServerConfig.model_validate(value)
        except Exception as exc:
            return _warn_and_use_default_subconfig("server_config", exc, ServerConfig)

    @field_validator("log_config", mode="before")
    @classmethod
    def _validate_log_config_field(cls, value):
        if value is None:
            return _warn_and_use_default_subconfig("log_config", "received null value", LogConfig)
        if isinstance(value, LogConfig):
            return value
        try:
            return LogConfig.model_validate(value)
        except Exception as exc:
            return _warn_and_use_default_subconfig("log_config", exc, LogConfig)

    @field_validator("rtc_room_config", mode="before")
    @classmethod
    def _validate_rtc_room_config_field(cls, value):
        if value is None:
            return _warn_and_use_default_subconfig("rtc_room_config", "received null value", WebRTCRoomConfig)
        if isinstance(value, WebRTCRoomConfig):
            return value
        try:
            return WebRTCRoomConfig.model_validate(value)
        except Exception as exc:
            return _warn_and_use_default_subconfig("rtc_room_config", exc, WebRTCRoomConfig)

    @classmethod
    def SetConfig(cls, config: Self):
        cls.__Instance__ = config

    @classmethod
    def GetConfig(cls) -> Self:
        if cls.__Instance__ is None:
            cls.__Instance__ = cls.AutoLoad(prefer_mode_specific=_prefer_mode_specific_default_paths()) or cls()
        return cls.__Instance__  # type: ignore

    @classmethod
    def AutoLoad(cls, *, prefer_mode_specific: bool | None = None) -> Self | None:
        discovered = _discover_existing_default_config_path(prefer_mode_specific=prefer_mode_specific)
        if discovered is None:
            return None
        try:
            return cls.Load(discovered, set_global=False)
        except Exception as exc:
            _logger.warning("Failed to load discovered config %s: %s", discovered, exc)
            return None

    @classmethod
    def Load(cls, data: str | dict | Path, set_global: bool = True) -> Self:
        if isinstance(data, dict):
            config = cls.model_validate(data)
        elif isinstance(data, Path):
            config = cls.model_validate(_load_config_file(data))
        elif isinstance(data, str):
            candidate = Path(data)
            try:
                path_exists = candidate.exists()
            except OSError:
                path_exists = False
            if path_exists:
                config = cls.model_validate(_load_config_file(candidate))
            else:
                if candidate.suffix.lower() in {".json", ".toml", ".yaml", ".yml"}:
                    raise FileNotFoundError(f"Config file not found: {candidate}")
                config = cls.model_validate(_load_serialized_config(data, source_name="<string>"))
        else:
            raise ValueError("Unsupported data type for loading config.")
        if set_global:
            cls.SetConfig(config)
        return config

    @classmethod
    def GetDefaultConfigPath(cls) -> Path:
        return _default_config_write_path()

    @classmethod
    def DescribeRuntimeConfigPath(cls, preferred_path: str | Path | None = None, *, prefer_mode_specific: bool | None = None) -> RuntimeConfigPathInfo:
        preferred_text = _clean_optional_path(preferred_path)
        env_source_text = _clean_optional_path(os.getenv("__CONFIG_FILE_PATH__"))
        env_write_text = _clean_optional_path(os.getenv("__WRITABLE_CONFIG_FILE_PATH__"))

        source_path: Path | None
        if preferred_text is not None:
            source_path = _normalize_config_path(preferred_text)
        elif env_source_text is not None:
            source_path = _normalize_config_path(env_source_text)
        else:
            source_path = _discover_existing_default_config_path(prefer_mode_specific=prefer_mode_specific)

        write_path = _normalize_config_path(
            env_write_text
            or preferred_text
            or (str(source_path) if source_path is not None else None)
            or _default_config_write_path()
        )
        write_note: str | None = None
        if not write_path.suffix:
            write_path = write_path.with_suffix(".yaml")
        if write_path.suffix.lower() not in SUPPORTED_CONFIG_WRITE_SUFFIXES:
            write_path = _default_config_write_path()
            write_note = (
                f"Unsupported config extension '{source_path.suffix if source_path is not None else '<none>'}'. "
                f"Falling back to YAML format: {write_path}"
            )
        elif source_path is None:
            write_note = (
                f"No server config file found. A default config will be created. "
                f"You can override values via CLI or env vars. Write path: {write_path}"
            )
        return {
            "source_path": str(source_path) if source_path is not None else None,
            "source_exists": source_path.is_file() if source_path is not None else False,
            "write_path": str(write_path),
            "write_note": write_note,
        }

    def dump_serialized(self, path: str | Path | None = None, *, format_hint: str | None = None) -> str:
        target_path = _normalize_config_path(path) if path is not None else None
        normalized_hint = (format_hint or (target_path.suffix if target_path is not None else ".yaml") or ".yaml").lower().lstrip(".")
        data = self.model_dump(mode="json", exclude_none=False)
        if normalized_hint == "json":
            return json.dumps(data, ensure_ascii=False, indent=2)
        if normalized_hint not in {"yaml", "yml"}:
            raise ValueError(f"Unsupported config write format: {normalized_hint}")
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    def write_to_path(self, path: str | Path | None = None) -> Path:
        target = _normalize_config_path(path or _default_config_write_path())
        if not target.suffix:
            target = target.with_suffix(".yaml")
        suffix = target.suffix.lower()
        if suffix not in SUPPORTED_CONFIG_WRITE_SUFFIXES:
            raise ValueError(
                f"Unsupported config write format: '{target.suffix}'. Expected one of .json, .yaml, .yml"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.dump_serialized(target), encoding="utf-8")
        return target

    @classmethod
    def BuildArgParser(cls) -> argparse.ArgumentParser:
        default = cls.__Instance__ or cls.AutoLoad(prefer_mode_specific=True) or cls()
        p = argparse.ArgumentParser(description="Server")
        p.add_argument("--config", type=str, help="Optional path to server config file (.json/.toml/.yaml/.yml). When omitted, the server auto-discovers config/server.* if present, otherwise runs with defaults.")
        # server_config
        p.add_argument("--server-host", type=str, default=default.server_config.host, help="[server] Bind host")
        p.add_argument("--server-port", type=int, default=default.server_config.port, help="[server] Bind port (-1 = auto)")
        p.add_argument("--frontend-baseurl", type=str, default=default.server_config.frontend_baseurl, help="[server] Optional frontend request base URL injected into HTML pages")
        p.add_argument("--server-worker", type=int, default=default.server_config.worker, help="[server] Number of workers")
        p.add_argument("--server-reload", action="store_true", help="[server] Enable auto-reload (dev)")
        p.add_argument("--system-allowed-roots", type=str, default=",".join(default.server_config.system_allowed_roots), help="[server] Comma-separated allowed filesystem roots for terminal/file manager")
        p.add_argument("--system-default-root", type=str, default=default.server_config.system_default_root, help="[server] Preferred default root for terminal/file manager")
        p.add_argument("--system-terminal-default-cwd", type=str, default=default.server_config.system_terminal_default_cwd, help="[server] Default cwd for terminal sessions")
        p.add_argument("--system-terminal-max-sessions", type=int, default=default.server_config.system_terminal_max_sessions, help="[server] Max concurrent terminal sessions per worker")
        p.add_argument("--internal-path-prefix", type=str, default=default.server_config.internal_path_prefix, help="[server] Internal route prefix; use empty string for no prefix")
        p.add_argument("--expose-internal-prefix", action="store_true", default=None, help="[server] Expose internal routes and admin panel")
        p.add_argument("--hide-internal-prefix", action="store_true", help="[server] Hide internal routes and admin panel")
        p.add_argument("--internal-path-allowed-ip", type=str, default=None, help="[server] Internal IP allow list: localhost, all, wildcard, or comma-separated patterns")
        p.add_argument("--expose-ai-service", action="store_true", default=None, help="[server] Expose public /ai/* aliases for AI service APIs")
        p.add_argument("--enable-rtc-chatroom", action="store_true", default=None, help="[server] Enable RTC chat-room routes and UI")
        p.add_argument("--disable-rtc-chatroom", action="store_true", help="[server] Disable RTC chat-room routes and UI")

        # log_config
        p.add_argument("--log-level", type=str, default=default.log_config.log_level, help="[log] Log level [debug|info|warning|error|critical]")
        p.add_argument("--log-path", type=str, default=default.log_config.log_path, help="[log] Base directory for log files (file mode only)")
        p.add_argument("--log-method", type=str, default=",".join(default.log_config.log_method), help="[log] Comma-separated: file, db")
        p.add_argument("--log-system-metrics-interval", type=int, default=default.log_config.system_metrics_interval, help="[log] System metrics snapshot interval (s, db mode)")
        p.add_argument("--log-system-metrics-retention-hours", type=int, default=default.log_config.system_metrics_retention_hours, help="[log] Persisted system metrics retention window in hours (0 = disable TTL cleanup)")
        p.add_argument("--log-filtering-prefixes", type=str, default=default.log_config.filtering_logger_prefixes if isinstance(default.log_config.filtering_logger_prefixes, str) else ",".join(default.log_config.filtering_logger_prefixes), help="[log] Comma-separated log message prefixes to filter out (case-insensitive; e.g. ORM debug logs, Uvicorn access logs)")
        p.add_argument("--log-uvicorn-noise-strategy", type=str, default=default.log_config.uvicorn_noise_handling_strategy, help="[log] Strategy for handling uvicorn noisy log messages (e.g. Uvicorn WebSocket handshake failures): degrade (lower to DEBUG), ignore (filter out), none (leave as is)")
        p.add_argument("--log-backup-count", type=int, default=default.log_config.log_backup_count, help="[log, file mode] Rotated backup files to keep")
        p.add_argument("--log-rotation-interval", type=int, default=default.log_config.log_rotation_interval, help="[log, file mode] Rotation interval in hours")
        p.add_argument("--log-rotation-time", type=str, default=default.log_config.rotation_time, help="[log, file mode] Daily rotation time HH:MM")
        p.add_argument("--log-zip-old-logs", action="store_true", help="[log, file mode] Compress rotated log files")
        # rtc_room_config
        p.add_argument("--rtc-room-enable", action="store_true", default=None, help="[rtc_room] Alias of --enable-rtc-chatroom")
        p.add_argument("--rtc-room-audio-sample-rate", type=int, default=default.rtc_room_config.audio_sample_rate, help="[rtc_room] Audio sample rate (Hz)")
        p.add_argument("--rtc-room-min-silence-ms", type=int, default=default.rtc_room_config.min_silence_ms, help="[rtc_room] Min silence duration (ms)")
        p.add_argument("--rtc-room-min-voice-ms", type=int, default=default.rtc_room_config.min_voice_ms, help="[rtc_room] Min voice segment duration (ms)")
        p.add_argument("--rtc-room-mid-silence-ms", type=int, default=default.rtc_room_config.mid_silence_ms, help="[rtc_room] Silence inserted between TTS segments (ms)")
        p.add_argument("--rtc-room-max-segment-ms", type=int, default=default.rtc_room_config.max_segment_ms, help="[rtc_room] Max voice segment duration (ms)")
        p.add_argument("--rtc-room-min-energy-rms", type=int, default=default.rtc_room_config.min_energy_rms, help="[rtc_room] Min RMS energy for VAD")
        p.add_argument("--rtc-room-ice-servers-json", type=str, default=None, help="[rtc_room] JSON array of ICE server objects")
        p.add_argument("--rtc-room-bundle-policy", type=str, default=default.rtc_room_config.bundle_policy, help="[rtc_room] WebRTC bundle policy")
        # storage_config
        p.add_argument("--storage-config-json", type=str, default=None, help="[storage] JSON string for full StorageConfig override")
        # ai_services_config
        p.add_argument("--ai-services-config", type=str, default=None, help="[ai] Path to AI services config file (.json/.yaml/.yml/.toml), or inline JSON string")
        # extra
        p.add_argument("--extra-app-paths", type=str, default=None, help="Comma-separated extra app directory paths")
        p.add_argument("--extra-public-paths", type=str, default=None, help="Comma-separated extra public directory paths")
        p.add_argument("--extra-resources-paths", type=str, default=None, help="Comma-separated extra resources directory paths")
        p.add_argument("--open-browser", action="store_true", help="Open panel in browser after start")
        p.add_argument("--production", action="store_true", help="Run in production mode")
        return p

    @classmethod
    def CreateConfigFromArgs(cls, args: argparse.Namespace, set_global: bool = True) -> Self:
        if config_path := getattr(args, "config", None):
            config = cls.Load(config_path, set_global=False)
        else:
            config = cls.AutoLoad(prefer_mode_specific=True) or cls()
        # server_config
        config.server_config.host = getattr(args, "server_host", config.server_config.host)
        config.server_config.port = getattr(args, "server_port", config.server_config.port)
        config.server_config.frontend_baseurl = getattr(args, "frontend_baseurl", config.server_config.frontend_baseurl)
        config.server_config.worker = getattr(args, "server_worker", config.server_config.worker)
        raw_system_allowed_roots = getattr(args, "system_allowed_roots", None)
        if raw_system_allowed_roots is not None:
            config.server_config.system_allowed_roots = [
                part.strip()
                for part in str(raw_system_allowed_roots).replace(";", ",").split(",")
                if part.strip()
            ]
        config.server_config.system_default_root = getattr(args, "system_default_root", config.server_config.system_default_root)
        config.server_config.system_terminal_default_cwd = getattr(args, "system_terminal_default_cwd", config.server_config.system_terminal_default_cwd)
        config.server_config.system_terminal_max_sessions = getattr(args, "system_terminal_max_sessions", config.server_config.system_terminal_max_sessions)
        raw_internal_prefix = getattr(args, "internal_path_prefix", config.server_config.internal_path_prefix)
        if raw_internal_prefix == "":
            config.server_config.internal_path_prefix = None
        else:
            config.server_config.internal_path_prefix = raw_internal_prefix
            config.server_config.model_post_init(None)
        if getattr(args, "hide_internal_prefix", False):
            config.server_config.expose_internal_prefix = False
        elif getattr(args, "expose_internal_prefix", None) is not None:
            config.server_config.expose_internal_prefix = True
        raw_internal_allowed_ip = getattr(args, "internal_path_allowed_ip", None)
        if raw_internal_allowed_ip is not None:
            config.server_config.internal_path_allowed_ip = raw_internal_allowed_ip
        if getattr(args, "expose_ai_service", None) is not None:
            config.server_config.expose_ai_service = bool(getattr(args, "expose_ai_service", False))
        if getattr(args, "disable_rtc_chatroom", False):
            config.server_config.enable_rtc_chatroom = False
        elif getattr(args, "enable_rtc_chatroom", None) is not None or getattr(args, "rtc_room_enable", None) is not None:
            config.server_config.enable_rtc_chatroom = bool(getattr(args, "enable_rtc_chatroom", False) or getattr(args, "rtc_room_enable", False))
        if getattr(args, "server_reload", False):
            config.server_config.reload = True
        # core_config

        # log_config
        config.log_config.log_level = getattr(args, "log_level", config.log_config.log_level)
        config.log_config.log_path = getattr(args, "log_path", config.log_config.log_path)
        raw_methods = getattr(args, "log_method", None)
        if raw_methods is not None:
            config.log_config.log_method = [
                m.strip() for m in raw_methods.split(",") if m.strip() in ("file", "db")
            ]
        config.log_config.system_metrics_interval = getattr(args, "log_metrics_interval", config.log_config.system_metrics_interval)
        config.log_config.system_metrics_retention_hours = getattr(args, "log_metrics_retention_hours", config.log_config.system_metrics_retention_hours)
        config.log_config.log_backup_count = getattr(args, "log_backup_count", config.log_config.log_backup_count)
        config.log_config.log_rotation_interval = getattr(args, "log_rotation_interval", config.log_config.log_rotation_interval)
        config.log_config.rotation_time = getattr(args, "log_rotation_time", config.log_config.rotation_time)
        if getattr(args, "log_zip_old_logs", False):
            config.log_config.zip_old_logs = True
        # rtc_room_config
        config.rtc_room_config.rtc_room_enable = config.server_config.enable_rtc_chatroom
        config.rtc_room_config.audio_sample_rate = getattr(args, "rtc_room_audio_sample_rate", config.rtc_room_config.audio_sample_rate)
        config.rtc_room_config.min_silence_ms = getattr(args, "rtc_room_min_silence_ms", config.rtc_room_config.min_silence_ms)
        config.rtc_room_config.min_voice_ms = getattr(args, "rtc_room_min_voice_ms", config.rtc_room_config.min_voice_ms)
        config.rtc_room_config.mid_silence_ms = getattr(args, "rtc_room_mid_silence_ms", config.rtc_room_config.mid_silence_ms)
        config.rtc_room_config.max_segment_ms = getattr(args, "rtc_room_max_segment_ms", config.rtc_room_config.max_segment_ms)
        config.rtc_room_config.min_energy_rms = getattr(args, "rtc_room_min_energy_rms", config.rtc_room_config.min_energy_rms)
        config.rtc_room_config.bundle_policy = getattr(args, "rtc_room_bundle_policy", config.rtc_room_config.bundle_policy)
        raw_ice = getattr(args, "rtc_room_ice_servers_json", None)
        if raw_ice:
            try:
                servers = [WebRTCIceServer(**s) for s in json.loads(raw_ice)]
                config.rtc_room_config.ice_servers = servers
            except Exception as _e:
                _logger.warning(
                    "Config.rtc_room_config.ice_servers validation failed: %s. Keeping existing/default config.",
                    _e,
                )
        # storage_config
        raw_storage = getattr(args, "storage_config_json", None)
        if raw_storage:
            try:
                StorageConfig.SetGlobal(StorageConfig.model_validate_json(raw_storage))
                _logger.info("Loaded storage config from --storage-config-json.")
            except Exception as _e:
                _logger.warning(
                    "--storage-config-json validation failed: %s. Storage config will use Global() discovery/defaults.",
                    _e,
                )
                StorageConfig.SetGlobal(StorageConfig.AutoLoad(prefer_mode_specific=True) or StorageConfig())
        else:
            StorageConfig.SetGlobal(StorageConfig.AutoLoad(prefer_mode_specific=True) or StorageConfig())
        # ai_services_config → write to __AI_SERVICES_CONFIG__ env so workers
        # and AIServicesConfig.Global() pick it up before any Default() call.
        raw_ai = getattr(args, "ai_services_config", None)
        if raw_ai:
            try:
                ai_cfg = _resolve_ai_services_config(raw_ai)
                os.environ["__AI_SERVICES_CONFIG__"] = ai_cfg.to_serialized_env()
                _logger.info("Loaded AI services config from --ai-services-config.")
            except Exception as _e:
                _logger.warning(
                    "--ai-services-config validation failed: %s. AI services will use defaults.",
                    _e,
                )
        elif not os.environ.get("__AI_SERVICES_CONFIG__"):
            ai_cfg = _auto_discover_ai_services_config()
            if ai_cfg is not None:
                os.environ["__AI_SERVICES_CONFIG__"] = ai_cfg.to_serialized_env()
        # extra_paths
        raw_extra_app = getattr(args, "extra_app_paths", None)
        if raw_extra_app is not None:
            paths = [p.strip() for p in raw_extra_app.split(",") if p.strip()]
            if config.server_config.extra_app_paths is None:
                config.server_config.extra_app_paths = paths
            elif isinstance(config.server_config.extra_app_paths, str):
                config.server_config.extra_app_paths = [config.server_config.extra_app_paths] + paths
            else:
                config.server_config.extra_app_paths = list(config.server_config.extra_app_paths) + paths
        raw_extra_public = getattr(args, "extra_public_paths", None)
        if raw_extra_public is not None:
            paths = [p.strip() for p in raw_extra_public.split(",") if p.strip()]
            if config.server_config.extra_public_paths is None:
                config.server_config.extra_public_paths = paths
            elif isinstance(config.server_config.extra_public_paths, str):
                config.server_config.extra_public_paths = [config.server_config.extra_public_paths] + paths
            else:
                config.server_config.extra_public_paths = list(config.server_config.extra_public_paths) + paths
        raw_extra_resources = getattr(args, "extra_resources_paths", None)
        if raw_extra_resources is not None:
            paths = [p.strip() for p in raw_extra_resources.split(",") if p.strip()]
            if config.server_config.extra_resources_paths is None:
                config.server_config.extra_resources_paths = paths
            elif isinstance(config.server_config.extra_resources_paths, str):
                config.server_config.extra_resources_paths = [config.server_config.extra_resources_paths] + paths
            else:
                config.server_config.extra_resources_paths = list(config.server_config.extra_resources_paths) + paths
        if set_global:
            cls.SetConfig(config)
        return config


__all__ = [
    "SERVER_DIR",
    "SERVER_HTML_DIR",
    "VENDOR_DIR",
    "DEFAULT_LOG_DIR",
    "DEFAULT_CONFIG_PATH",
    "RuntimeConfigPathInfo",
    "ServerConfig",
    "LogConfig",
    "WebRTCRoomConfig",
    "JwtIssuanceConfig",
    "Config",
]


class _AiTempUploadJwtConfig:
    category: str = 'ai-temp'
    max_size: int = 50 * 1024 * 1024  # 50 MB
    file_expire: float | None = 3600.0
    ttl: int = 300  # token lifetime, seconds
    allowed_mime_prefixes: tuple[str, ...] = (
        'image/', 'audio/', 'video/', 'text/', 'application/pdf',
    )


class JwtIssuanceConfig:
    '''Server-side issuance constants for JWT capability tokens.

    Centralized to avoid scattering hard-coded values across route handlers.
    Each scope corresponds to one issuance route.
    '''
    AiTempUpload = _AiTempUploadJwtConfig
