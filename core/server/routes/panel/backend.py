# -*- coding: utf-8 -*-
import os
import types
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, TypeGuard, TypedDict, get_args, get_origin
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from core.server.translate import _register_internal_translation, TranslationLanguage
from core.utils.type_utils import AdvancedBaseModel
from core.server.constants import SERVER_DIR
from core.server.data_types.config import Config, RuntimeConfigPathInfo
from ... import runtime_control
from ...app import get_resources, internal_admin_path, on_app_created
from ...html_injection import html_response_from_path
from ...shared import AppSharedData, RuntimeMeta, WorkerSnapshot
HK_TZ = timezone(timedelta(hours=8), name="Asia/Hong_Kong")
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}
logger = logging.getLogger(__name__)
_shared_runtime_sync_failures: set[str] = set()

class BackendRuntimeState(TypedDict):
    worker_pid: int
    started_at: str
    request_count: int
    last_request_at: str | None

class BackendControlRequest(AdvancedBaseModel):
    action: Literal["restart", "stop"]
    reason: str | None = None

class BackendSettingsSaveRequest(AdvancedBaseModel):
    config: Config
    file_path: str | None = None
    write_to_source_file: bool = False

class BackendResponseModel(AdvancedBaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, use_attribute_docstrings=True)

class BackendWorkerInfo(BackendResponseModel):
    pid: int | None = None
    msg_port: int | None = None
    status: str | None = None
    started_at: str | None = None
    last_request_at: str | None = None
    request_count: int | None = None
    rooms_running: int | None = None

class BackendServerInfo(BackendResponseModel):
    host: str | None = None
    port: int | None = None
    worker: int | None = None
    reload: bool | None = None

class BackendConfigFileInfo(BackendResponseModel):
    source_path: str | None = None
    source_exists: bool | None = None
    write_path: str | None = None
    write_note: str | None = None

class BackendGitInfo(BackendResponseModel):
    available: bool | None = None
    branch: str | None = None
    head: str | None = None
    head_full: str | None = None
    git_dir: str | None = None

class BackendUIFieldInfo(BackendResponseModel):
    name: str
    path: str
    label: str
    label_key: str | None = None
    description: str | None = None
    description_key: str | None = None
    required: bool
    nullable: bool
    kind: str
    options: list[str] = Field(default_factory=list)
    children: list['BackendUIFieldInfo'] = Field(default_factory=list)
    item_kind: str | None = None
    value_kind: str | None = None

class BackendRuntimeResponse(AdvancedBaseModel):
    instance_id: str | None = None
    server_start_time: str | None = None
    server_start_time_hk: str | None = None
    uptime_seconds: float | None = None
    current_worker_pid: int | None = None
    app_request_count: int | None = None
    app_last_request_at: str | None = None
    worker_count: int | None = None
    request_count_total: int | None = None
    workers: list[BackendWorkerInfo] = Field(default_factory=list)
    cache_scope: str | None = None
    server: BackendServerInfo | None = None
    config_file: BackendConfigFileInfo | None = None
    git: BackendGitInfo | None = None
    control: BackendResponseModel | None = None
    start_args: str | None = None
    open_rooms: int | None = None
    runtime_warning: str | None = None

class BackendSettingsResponse(AdvancedBaseModel):
    config: Config
    ui_schema: list[BackendUIFieldInfo] = Field(default_factory=list)
    config_file: BackendConfigFileInfo
    load_note: str | None = None
    restart_required_message: str

class BackendSettingsSaveResponse(AdvancedBaseModel):
    saved: bool
    file_path: str | None = None
    restart_required: bool
    message: str
    write_note: str | None = None
    config: Config

class BackendControlResponse(AdvancedBaseModel):
    accepted: bool
    action: Literal["restart", "stop"]
    message: str
    control: BackendResponseModel | None = None
BackendUIFieldInfo.model_rebuild()

def _field_title_key(path: str) -> str:
    return f"backend.settings.field.{path}.label"

def _field_description_key(path: str) -> str:
    return f"backend.settings.field.{path}.description"

def _humanize_label(name: str) -> str:
    return name.replace("_", " ").strip()

def _zh_field_label(name: str) -> str:
    mapping = {
        "server_config": "server_config",
        "host": "host",
        "port": "port",
        "frontend_baseurl": "frontend_baseurl",
        "worker": "worker",
        "reload": "reload",
        "description": "description",
        "force_exit_timeout": "force_exit_timeout",
        "system_allowed_roots": "system_allowed_roots",
        "system_default_root": "system_default_root",
        "system_terminal_default_cwd": "system_terminal_default_cwd",
        "system_terminal_max_sessions": "system_terminal_max_sessions",
        "core_config": "core_config",
        "log_config": "log_config",
        "log_level": "log_level",
        "log_path": "log_path",
        "log_method": "log_method",
        "log_format": "log_format",
        "log_time_format": "log_time_format",
        "filtering_logger_prefixes": "filtering_logger_prefixes",
        "uvicorn_noise_handling_strategy": "uvicorn_noise_handling_strategy",
        "system_metrics_interval": "system_metrics_interval",
        "system_metrics_retention_hours": "system_metrics_retention_hours",
        "log_backup_count": "log_backup_count",
        "zip_old_logs": "zip_old_logs",
        "log_rotation_interval": "log_rotation_interval",
        "rotation_time": "rotation_time",
        "rtc_room_config": "rtc_room_config",
        "audio_sample_rate": "audio_sample_rate",
        "min_silence_ms": "min_silence_ms",
        "min_voice_ms": "min_voice_ms",
        "mid_silence_ms": "mid_silence_ms",
        "max_segment_ms": "max_segment_ms",
        "min_energy_rms": "min_energy_rms",
        "ice_servers": "ice_servers",
        "urls": "urls",
        "username": "username",
        "credential": "credential",
        "bundle_policy": "bundle_policy",
    }
    return mapping.get(name, _humanize_label(name))

def _zh_option_label(value: str) -> str:
    mapping = {
        "file": "file",
        "db": "db",
        "degrade": "degrade",
        "ignore": "ignore",
        "none": "none",
        "balanced": "balanced",
        "max-compat": "max-compat",
        "max-bundle": "max-bundle",
        "on": "on",
        "off": "off",
    }
    return mapping.get(value, value)

def _zh_field_description(path: str, description: str | None) -> str | None:
    mapping = {
        "server_config": "server_config",
        "core_config": "core_config",
        "log_config": "log_config",
        "rtc_room_config": "rtc_room_config",
        "server_config.reload": "server_config.reload",
        "log_config.zip_old_logs": "log_config.zip_old_logs",
    }
    return mapping.get(path, description)
def _register_backend_settings_translations() -> None:
    rows = [
        ("backend.settings.title", "Backend Settings", "", ""),
        ("backend.settings.schema", "Config Schema", "", ""),
        ("backend.settings.write_target", "Write Target", "", ""),
        ("backend.settings.mode", "Mode", "", ""),
        ("backend.settings.reload", "Reload", "", ""),
        ("backend.settings.edit", "Edit", "", ""),
        ("backend.settings.cancel", "Cancel", "", ""),
        ("backend.settings.save", "Save Config", "", ""),
        ("backend.settings.write_source", "Write source file", "", ""),
        ("backend.settings.required", "Required", "", ""),
        ("backend.settings.nullable", "Nullable", "", ""),
        ("backend.settings.helper.list", "Use the input bar to add items, then manage them in the list below.", "", ""),
        ("backend.settings.helper.json", "Complex values are edited as JSON.", "", ""),
        ("backend.settings.helper.boolean", "Use switches for booleans.", "", ""),
        ("backend.settings.helper.enum_array", "Enum arrays use chip toggles.", "", ""),
        ("backend.settings.boolean.true", "On", "", ""),
        ("backend.settings.boolean.false", "Off", "", ""),
        ("backend.settings.item.add", "+ Add", "", ""),
        ("backend.settings.item.remove", "Remove", "", ""),
        ("backend.settings.mode.readonly", "Read only", "", ""),
        ("backend.settings.mode.editing", "Editing", "", ""),
        ("backend.settings.status.loading", "Loading backend config...", "", ""),
        ("backend.settings.status.loaded", "Loaded", "", ""),
        ("backend.settings.status.cancelled", "Cancelled", "", ""),
        ("backend.settings.status.editing", "Editing", "", ""),
        ("backend.settings.status.load_failed", "Failed to load config", "", ""),
    ]
    for alias, en, zh_cn, zh_tw in rows:
        for language, text in (
            (TranslationLanguage.EN, en),
            (TranslationLanguage.ZH_CN, zh_cn),
            (TranslationLanguage.ZH_TW, zh_tw),
        ):
            if text is not None:
                _register_internal_translation(alias, language, text, aliases=[alias])
_register_backend_settings_translations()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _log_shared_runtime_sync_failure(stage: str, exc: Exception) -> None:
    key = f"{stage}:{type(exc).__name__}:{exc}"
    if key in _shared_runtime_sync_failures:
        return
    _shared_runtime_sync_failures.add(key)
    logger.warning("Backend runtime shared-state sync failed during %s: %s", stage, exc, exc_info=True)

def _ensure_backend_runtime_state(app: FastAPI) -> BackendRuntimeState:
    runtime = getattr(app.state, "backend_runtime", None)
    if not isinstance(runtime, dict):
        runtime = {
            "worker_pid": os.getpid(),
            "started_at": _now_iso(),
            "request_count": 0,
            "last_request_at": None,
        }
        app.state.backend_runtime = runtime
    try:
        shared = AppSharedData.Get()
        shared.touch_worker(
            runtime["worker_pid"],
            started_at=runtime.get("started_at"),
            status="running",
        )
    except Exception as exc:
        _log_shared_runtime_sync_failure("worker-touch", exc)
    return runtime

class _BackendRuntimeTrackingMiddleware:

    def __init__(self, app: ASGIApp, *, fastapi_app: FastAPI):
        self.app = app
        self.fastapi_app = fastapi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        runtime = _ensure_backend_runtime_state(self.fastapi_app)
        runtime["request_count"] = int(runtime.get("request_count") or 0) + 1
        runtime["last_request_at"] = _now_iso()
        try:
            AppSharedData.Get().increment_worker_request(runtime["worker_pid"], at=runtime["last_request_at"])
        except Exception as exc:
            _log_shared_runtime_sync_failure("request-increment", exc)

        async def _send_with_runtime_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Worker-PID", str(runtime["worker_pid"]))
                headers.setdefault("X-Request-Count", str(runtime["request_count"]))
            await send(message)
        try:
            await self.app(scope, receive, _send_with_runtime_headers)
        except Exception:
            logger.exception(
                "Unhandled request failure after backend runtime tracking for %s %s",
                scope.get("method"),
                scope.get("path"),
            )
            raise

def _install_runtime_tracking(app: FastAPI) -> None:
    if getattr(app.state, "_backend_runtime_tracking_installed", False):
        return
    _ensure_backend_runtime_state(app)
    app.add_middleware(_BackendRuntimeTrackingMiddleware, fastapi_app=app)
    app.state._backend_runtime_tracking_installed = True

@on_app_created
def _install_runtime_tracking_on_app_created(app: FastAPI):
    _install_runtime_tracking(app)

def _is_local_request(request: Request) -> bool:
    host = (request.client.host if request.client else "") if request is not None else ""
    host = (host or "").strip().lower()
    return not host or host in _LOCAL_HOSTS

def _ensure_local_request(request: Request) -> None:
    if not _is_local_request(request):
        raise HTTPException(403, "")

def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

def _to_hk_iso(value: str | None) -> str | None:
    dt = _parse_datetime(value)
    if dt is None:
        return None
    return dt.astimezone(HK_TZ).isoformat()

def _compute_uptime_seconds(value: str | None) -> float | None:
    dt = _parse_datetime(value)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())

def _resolve_git_dir(project_root: Path) -> Path | None:
    dot_git = project_root / ".git"
    if dot_git.is_dir():
        return dot_git
    if not dot_git.is_file():
        return None
    try:
        text = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.lower().startswith("gitdir:"):
        return None
    git_dir_text = text.split(":", 1)[1].strip()
    git_dir = Path(git_dir_text)
    if not git_dir.is_absolute():
        git_dir = (project_root / git_dir).resolve()
    return git_dir if git_dir.is_dir() else None

def _lookup_packed_ref(git_dir: Path, ref: str) -> str | None:
    packed_refs = git_dir / "packed-refs"
    if not packed_refs.is_file():
        return None
    try:
        for line in packed_refs.read_text(encoding="utf-8").splitlines():
            row = line.strip()
            if not row or row.startswith("#") or row.startswith("^"):
                continue
            sha, ref_name = row.split(" ", 1)
            if ref_name.strip() == ref:
                return sha.strip()
    except OSError:
        return None
    return None

def _read_git_info(project_root: Path) -> BackendGitInfo | None:
    git_dir = _resolve_git_dir(project_root)
    if git_dir is None:
        return None
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return BackendGitInfo(available=False)
    try:
        head_text = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return BackendGitInfo(available=False)
    branch: str | None = None
    commit: str | None = None
    if head_text.startswith("ref:"):
        ref_name = head_text.split(":", 1)[1].strip()
        branch = ref_name.split("/")[-1] if ref_name else None
        ref_path = git_dir / ref_name
        if ref_path.is_file():
            try:
                commit = ref_path.read_text(encoding="utf-8").strip() or None
            except OSError:
                commit = None
        if commit is None:
            commit = _lookup_packed_ref(git_dir, ref_name)
    else:
        commit = head_text or None
    return BackendGitInfo(
        available=True,
        branch=branch,
        head=(commit or "")[:12] or None,
        head_full=commit,
        git_dir=str(git_dir),
    )

def _unwrap_annotation(annotation: object) -> tuple[object, bool]:
    origin = get_origin(annotation)
    if origin in (types.UnionType, getattr(types, "UnionType", None)):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        nullable = len(args) != len(get_args(annotation))
        if len(args) == 1:
            return args[0], nullable
    if origin is None and hasattr(annotation, "__args__") and hasattr(annotation, "__origin__"):
        origin = get_origin(annotation)
    if origin is not None and str(origin) == "typing.Union":
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        nullable = len(args) != len(get_args(annotation))
        if len(args) == 1:
            return args[0], nullable
    return annotation, False

def _literal_options(annotation: object) -> list[object] | None:
    if get_origin(annotation) is Literal:
        return list(get_args(annotation))
    return None

def _list_item_annotation(annotation: object) -> object | None:
    origin = get_origin(annotation)
    if origin in (list, tuple, set):
        return get_args(annotation)[0] if get_args(annotation) else object
    if origin in (types.UnionType, getattr(types, "UnionType", None)) or str(origin) == "typing.Union":
        for arg in get_args(annotation):
            if arg is type(None):
                continue
            item_annotation = _list_item_annotation(arg)
            if item_annotation is not None:
                return item_annotation
    return None

def _is_model_type(annotation: object) -> TypeGuard[type[BaseModel]]:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)

def _label_for_field(name: str, field_info: FieldInfo) -> str:
    title = getattr(field_info, "title", None)
    if title:
        return str(title)
    return name.replace("_", " ")

def _build_ui_field(name: str, field_info: FieldInfo, *, path_prefix: str = "") -> BackendUIFieldInfo:
    path = f"{path_prefix}.{name}" if path_prefix else name
    annotation, nullable = _unwrap_annotation(field_info.annotation)
    options = _literal_options(annotation)
    descriptor = BackendUIFieldInfo(
        name=name,
        path=path,
        label=_label_for_field(name, field_info),
        label_key=_field_title_key(path),
        description=getattr(field_info, "description", None),
        description_key=_field_description_key(path) if getattr(field_info, "description", None) else None,
        required=field_info.is_required(),
        nullable=nullable,
        kind="json",
    )
    for language, text in (
        (TranslationLanguage.EN, descriptor.label),
        (TranslationLanguage.ZH_CN, _zh_field_label(name)),
        (TranslationLanguage.ZH_TW, _zh_field_label(name)),
    ):
        if text is not None:
            _register_internal_translation(descriptor.label_key, language, text, aliases=[descriptor.label_key, descriptor.path])
    if descriptor.description:
        for language, text in (
            (TranslationLanguage.EN, descriptor.description),
            (TranslationLanguage.ZH_CN, _zh_field_description(path, descriptor.description)),
            (TranslationLanguage.ZH_TW, _zh_field_description(path, descriptor.description)),
        ):
            if text is not None:
                _register_internal_translation(
                    descriptor.description_key or descriptor.description,
                    language,
                    text,
                    aliases=[descriptor.description_key or descriptor.description],
                )
    if _is_model_type(annotation):
        descriptor.kind = "object"
        descriptor.children = _build_ui_schema(annotation, path_prefix=path)
        return descriptor
    if options is not None:
        descriptor.kind = "enum"
        descriptor.options = [str(item) for item in options]
        return descriptor
    item_annotation = _list_item_annotation(annotation)
    if item_annotation is not None:
        item_annotation, _ = _unwrap_annotation(item_annotation)
        item_options = _literal_options(item_annotation)
        if item_options is not None:
            descriptor.kind = "enum-array"
            descriptor.options = [str(item) for item in item_options]
            return descriptor
        if item_annotation in (str, int, float, bool):
            descriptor.kind = "list"
            descriptor.item_kind = {
                str: "string",
                int: "integer",
                float: "number",
                bool: "boolean",
            }[item_annotation]
            return descriptor
        if _is_model_type(item_annotation):
            descriptor.kind = "list-object"
            descriptor.children = _build_ui_schema(item_annotation, path_prefix=path + "[]")
            return descriptor
        return descriptor
    origin = get_origin(annotation)
    if origin in (dict,):
        args = get_args(annotation)
        val_annotation = args[1] if len(args) > 1 else object
        val_annotation, _ = _unwrap_annotation(val_annotation)
        if val_annotation in (str, int, float, bool):
            descriptor.kind = "dict"
            descriptor.value_kind = {
                str: "string", int: "integer", float: "number", bool: "boolean",
            }[val_annotation]
            return descriptor
        return descriptor
    if annotation is bool:
        descriptor.kind = "boolean"
        return descriptor
    if annotation is int:
        descriptor.kind = "integer"
        return descriptor
    if annotation is float:
        descriptor.kind = "number"
        return descriptor
    if annotation in (str, Path):
        descriptor.kind = "string"
        return descriptor
    return descriptor

def _build_ui_schema(model_cls: type[BaseModel], *, path_prefix: str = "") -> list[BackendUIFieldInfo]:
    rows: list[BackendUIFieldInfo] = []
    for name, field_info in model_cls.model_fields.items():
        rows.append(_build_ui_field(name, field_info, path_prefix=path_prefix))
    return rows

def _prime_backend_settings_schema_translations() -> None:
    _build_ui_schema(Config)
_prime_backend_settings_schema_translations()

def _load_settings_config(config_path: str | None) -> tuple[Config, str | None]:
    if not config_path:
        return Config.GetConfig(), ""
    candidate = Path(config_path)
    if candidate.is_file():
        try:
            return Config.Load(candidate, set_global=False), None
        except Exception as exc:
            return Config.GetConfig(), f"Config validation failed: {exc}"
    return Config.GetConfig(), None

def _fallback_runtime_meta(runtime: BackendRuntimeState) -> RuntimeMeta:
    start_time = os.getenv("__SERVER_START_TIME__") or runtime.get("started_at")
    worker_pid = runtime["worker_pid"]
    worker: WorkerSnapshot = {
        "pid": worker_pid,
        "msg_port": None,
        "started_at": runtime.get("started_at"),
        "request_count": runtime.get("request_count") or 0,
        "last_request_at": runtime.get("last_request_at"),
        "status": "running",
        "lifespan_ready": False,
    }
    return {
        "instance_uuid": os.getenv("__SERVER_INSTANCE_ID__") or "",
        "server_start_time": start_time,
        "worker_pid": worker_pid,
        "cache_scope": "cross-process",
        "worker_count": 1,
        "request_count_total": worker["request_count"],
        "workers": [worker],
        "supervisor_pid": int(os.getenv("__SERVER_SUPERVISOR_PID__", "0") or 0) or None,
        "control_mode": os.getenv("__SERVER_CONTROL_MODE__") or None,
        "control_supported": os.getenv("__SERVER_CONTROL_SUPPORTED__", "0").strip() in ("1", "true", "yes"),
        "config_file_path": os.getenv("__CONFIG_FILE_PATH__") or None,
    }

def _safe_worker_room_count(shared: AppSharedData | None, pid: int, warnings: list[str]) -> int:
    if shared is None or pid <= 0:
        return 0
    try:
        return shared.worker_running_room_count(pid)
    except Exception as exc:
        _log_shared_runtime_sync_failure("worker-room-count", exc)
        warnings.append(f"worker {pid} error: {exc}")
        return 0

def _safe_open_room_count(shared: AppSharedData | None, warnings: list[str]) -> int:
    if shared is None:
        return 0
    try:
        return len(shared.get_all_room_info())
    except Exception as exc:
        _log_shared_runtime_sync_failure("open-room-count", exc)
        warnings.append(f"")
        return 0

def _build_runtime_payload(app: FastAPI) -> BackendRuntimeResponse:
    runtime = _ensure_backend_runtime_state(app)
    warnings: list[str] = []
    shared: AppSharedData | None = None
    try:
        shared = AppSharedData.Get()
        shared_meta = shared.get_runtime_meta()
    except Exception as exc:
        _log_shared_runtime_sync_failure("runtime-meta", exc)
        warnings.append(f"Failed to broadcast to worker: {exc}")
        shared_meta = _fallback_runtime_meta(runtime)
    config_info = Config.DescribeRuntimeConfigPath()
    server_cfg = Config.GetConfig().server_config
    start_time = shared_meta["server_start_time"] or runtime["started_at"]
    uptime_seconds = _compute_uptime_seconds(start_time)
    workers: list[BackendWorkerInfo] = []
    for worker in shared_meta["workers"]:
        pid = worker["pid"]
        workers.append(BackendWorkerInfo(
            pid=pid,
            msg_port=worker.get("msg_port"),
            status=worker["status"],
            started_at=worker["started_at"],
            last_request_at=worker["last_request_at"],
            request_count=worker["request_count"],
            rooms_running=_safe_worker_room_count(shared, pid, warnings),
        ))
    return BackendRuntimeResponse(
        instance_id=shared_meta["instance_uuid"] or os.getenv("__SERVER_INSTANCE_ID__"),
        server_start_time=start_time,
        server_start_time_hk=_to_hk_iso(start_time),
        uptime_seconds=uptime_seconds,
        current_worker_pid=runtime["worker_pid"],
        app_request_count=runtime["request_count"],
        app_last_request_at=runtime["last_request_at"],
        worker_count=shared_meta["worker_count"],
        request_count_total=shared_meta["request_count_total"],
        workers=workers,
        cache_scope=shared_meta["cache_scope"],
        server=BackendServerInfo(
            host=server_cfg.get_host(),
            port=server_cfg.get_port(),
            worker=server_cfg.worker,
            reload=server_cfg.reload,
        ),
        config_file=BackendConfigFileInfo.model_validate(config_info),
        git=_read_git_info(SERVER_DIR.parent),
        control=BackendResponseModel.model_validate(runtime_control.get_control_status()),
        start_args=os.getenv("__START_ARGS__", "[]"),
        open_rooms=_safe_open_room_count(shared, warnings),
        runtime_warning="; ".join(warnings) or None,
    )

def register_backend_panel_routes(app: FastAPI):
    admin_path = internal_admin_path
    if not getattr(app.state, "_backend_runtime_tracking_installed", False):
        try:
            _install_runtime_tracking(app)
        except Exception:
            pass
    overview_path = get_resources("admin-panel", "panel", "backend_overview.html") or Path("backend_overview.html")
    settings_path = get_resources("admin-panel", "panel", "backend_settings.html") or Path("backend_settings.html")
    apikey_path = get_resources("admin-panel", "panel", "backend_apikey.html") or Path("backend_apikey.html")
    role_path = get_resources("admin-panel", "panel", "backend_role.html") or Path("backend_role.html")
    @app.get(admin_path("panel/backend/overview"), response_class=HTMLResponse)

    async def panel_backend_overview_html():
        return html_response_from_path(
            overview_path,
            not_found_message="panel/backend_overview.html not found",
        )
    @app.get(admin_path("panel/backend/settings"), response_class=HTMLResponse)

    async def panel_backend_settings_html():
        return html_response_from_path(
            settings_path,
            not_found_message="panel/backend_settings.html not found",
        )
    @app.get(admin_path("panel/backend/apikey"), response_class=HTMLResponse)

    async def panel_backend_apikey_html():
        return html_response_from_path(
            apikey_path,
            not_found_message="panel/backend_apikey.html not found",
        )
    @app.get(admin_path("panel/backend/role"), response_class=HTMLResponse)

    async def panel_backend_role_html():
        return html_response_from_path(
            role_path,
            not_found_message="panel/backend_role.html not found",
        )
    @app.get(admin_path("api/backend/runtime"), response_model=BackendRuntimeResponse)

    async def backend_runtime_info() -> BackendRuntimeResponse:
        return _build_runtime_payload(app)
    @app.get(admin_path("api/backend/start_args"))

    async def backend_start_args() -> dict[str, str]:
        return {"start_args": os.getenv("__START_ARGS__", "[]")}
    @app.get(admin_path("api/backend/settings"), response_model=BackendSettingsResponse)

    async def backend_settings_payload() -> BackendSettingsResponse:
        config_info = Config.DescribeRuntimeConfigPath()
        config_model, load_note = _load_settings_config(config_info["source_path"])
        return BackendSettingsResponse(
            config=config_model,
            ui_schema=_build_ui_schema(Config),
            config_file=BackendConfigFileInfo.model_validate(config_info),
            load_note=load_note,
            restart_required_message="",
        )
    @app.post(admin_path("api/backend/settings"), response_model=BackendSettingsSaveResponse)

    async def backend_save_settings(payload: BackendSettingsSaveRequest, request: Request) -> BackendSettingsSaveResponse:
        _ensure_local_request(request)
        config_model = payload.config
        config_info = Config.DescribeRuntimeConfigPath(payload.file_path)
        # Always update the in-memory runtime config
        Config.SetConfig(config_model)
        if not payload.write_to_source_file:
            # Only apply at runtime — do NOT write to disk
            return BackendSettingsSaveResponse(
                saved=True,
                file_path=None,
                restart_required=False,
                message="",
                write_note=None,
                config=config_model,
            )
        save_path = config_info["write_path"]
        try:
            saved_path = config_model.write_to_path(save_path)
        except Exception as exc:
            raise HTTPException(500, f"") from exc
        os.environ["__CONFIG_FILE_PATH__"] = str(saved_path)
        os.environ["__WRITABLE_CONFIG_FILE_PATH__"] = str(saved_path)
        return BackendSettingsSaveResponse(
            saved=True,
            file_path=str(saved_path),
            restart_required=True,
            message="",
            write_note=config_info.get("write_note"),
            config=config_model,
        )
    @app.post(admin_path("api/backend/control"), response_model=BackendControlResponse)

    async def backend_control(payload: BackendControlRequest, request: Request) -> BackendControlResponse:
        _ensure_local_request(request)
        try:
            status = runtime_control.request_control_action(payload.action, reason=payload.reason or "panel")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return BackendControlResponse(
            accepted=True,
            action=payload.action,
            message="Config updated successfully.",
            control=BackendResponseModel.model_validate(status),
        )
__all__ = ["register_backend_panel_routes"]
