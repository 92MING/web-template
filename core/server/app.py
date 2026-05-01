

import os
import logging
import asyncio
import inspect
import importlib
import traceback
import struct
import pickle
import fnmatch
import re
import mimetypes

from collections import defaultdict
from dataclasses import asdict, is_dataclass
from functools import lru_cache
from threading import Thread
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, TYPE_CHECKING
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse, StreamingResponse, FileResponse
from pydantic import BaseModel

from core.constants import APP_DIR, PROJECT_DIR, PUBLIC_DIR, RESOURCES_DIR
from core.utils.concurrent_utils import run_any_func
from .request import AdvanceRequest

if TYPE_CHECKING:
    from .shared import WorkerMessage

type AppCallbackResult = object | Awaitable[object]
type AppCallback = Callable[..., AppCallbackResult]
type AppFastAPICallback = Callable[[FastAPI], AppCallbackResult]
type AppNoArgCallback = Callable[[], AppCallbackResult]

# ---- Callback registries ----
_on_before_app_created_callbacks: list[AppCallback] = []
_on_app_created_callbacks: list[AppCallback] = []
_on_app_shutdown_callbacks: list[AppCallback] = []
_on_uvicorn_close_callbacks: list[AppCallback] = []
_app: FastAPI | None = None
_inner_comm_server_thread: Thread | None = None
_app_stop_event = asyncio.Event()

logger = logging.getLogger("proj-template")


def _is_app_shutting_down() -> bool:
    return _app_stop_event.is_set() or os.environ.get("__APP_SHUTTING_DOWN__") == "1"


def _is_separate_uvicorn_worker_process() -> bool:
    if os.environ.get("IN_FASTAPI_WORKER") != "1":
        return False
    try:
        supervisor_pid = int(os.environ.get("__SERVER_SUPERVISOR_PID__") or "0")
    except ValueError:
        return False
    return supervisor_pid > 0 and supervisor_pid != os.getpid()


def _schedule_worker_hard_exit_after_lifespan() -> None:
    if not _is_separate_uvicorn_worker_process():
        return

    def _exit_worker() -> None:
        import sys
        import time

        time.sleep(0.5)
        try:
            sys.stderr.write("[shutdown worker] lifespan complete; forcing worker process exit\n")
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    Thread(target=_exit_worker, name="uvicorn-worker-hard-exit", daemon=True).start()

_OPENAPI_SEGMENT_LABELS = {
    "admin": "Admin",
    "ai": "AI",
    "ai-services": "AI Services",
    "api": "API",
    "apikey": "API Key",
    "apikeys": "API Keys",
    "backend": "Backend",
    "files": "Files",
    "html": "HTML",
    "kv": "KV",
    "logs": "Logs",
    "monitoring": "Monitoring",
    "object": "Object",
    "openapi": "OpenAPI",
    "orm": "ORM",
    "panel": "Panel",
    "room": "Room",
    "rooms": "Rooms",
    "rtc": "RTC",
    "search": "Search",
    "server": "Server",
    "services": "Services",
    "settings": "Settings",
    "storage": "Storage",
    "system": "System",
    "translate": "Translate",
    "ui": "UI",
    "ui_translate": "UI Translate",
    "vector": "Vector",
    "vendor": "Vendor",
    "web": "Web",
}


# ---- Helpers ----
async def _invoke_callbacks(callbacks: list[AppCallback], *args: object, **kwargs: object) -> None:
    coros: list[Awaitable[object]] = []
    for cb in callbacks:
        param_count = len(inspect.signature(cb).parameters)
        try:
            result = cb(*args[:param_count], **kwargs) if param_count else cb()
            if inspect.isawaitable(result):
                coros.append(result)
        except Exception as e:
            logger.error(f"Error invoking callback {cb}: {e}\n{traceback.format_exc()}")
    if coros:
        await asyncio.gather(*(
            _safe_await(c) for c in coros
        ), return_exceptions=True)

def _sync_invoke_callbacks(callbacks: list[AppCallback], *args: object, **kwargs: object) -> None:
    coros: list[Awaitable[object]] = []
    for cb in callbacks:
        try:
            r = cb(*args, **kwargs)
            if inspect.isawaitable(r):
                coros.append(r)
        except Exception as e:
            logger.error(f"Error invoking callback {cb}: {e}\n{traceback.format_exc()}")
    if coros:
        async def _wait(coros: list[Awaitable[object]]) -> None:
            await asyncio.gather(*coros, return_exceptions=True)
        run_any_func(_wait, coros)


async def _safe_await(coro: Awaitable[object]) -> None:
    try:
        await coro
    except Exception as e:
        logger.error(f"Error awaiting callback: {e}\n{traceback.format_exc()}")


def _titleize_openapi_segment(segment: str) -> str:
    text = str(segment or "").strip().replace("_", "-")
    if not text:
        return ""
    if text in _OPENAPI_SEGMENT_LABELS:
        return _OPENAPI_SEGMENT_LABELS[text]
    parts: list[str] = []
    for item in text.split("-"):
        key = item.lower()
        if not key:
            continue
        if key in _OPENAPI_SEGMENT_LABELS:
            parts.append(_OPENAPI_SEGMENT_LABELS[key])
        elif len(key) <= 3:
            parts.append(key.upper())
        else:
            parts.append(key.capitalize())
    return " ".join(parts)


def _derive_openapi_tag(path: str) -> tuple[str, str | None]:
    parts = [part for part in str(path or "").split("/") if part]
    server_cfg = None
    try:
        from core.server.data_types.config import Config

        server_cfg = Config.GetConfig().server_config
        prefix_parts = [part for part in str(server_cfg.internal_path_prefix or "").split("/") if part]
        if prefix_parts and parts[:len(prefix_parts)] == prefix_parts:
            parts = parts[len(prefix_parts):]
    except Exception:
        pass

    def visible_prefix(prefix_parts: list[str]) -> str:
        raw_prefix = "/" + "/".join(prefix_parts)
        if server_cfg is not None and prefix_parts[:1] in (["admin"], ["html-assets"]):
            return server_cfg.get_internal_path(raw_prefix)
        return raw_prefix

    if not parts:
        return "General", None

    if parts[0] in {"vendor", "html-assets"}:
        label = "Static Assets" if parts[0] == "html-assets" else "Vendor Assets"
        return label, visible_prefix(parts[:1])

    is_admin = parts[0] == "admin"
    scope_prefix = "Admin" if is_admin else "API"
    start = 1 if is_admin else 0

    if is_admin and len(parts) >= 2 and parts[1] in {"login", "logout", "session"}:
        return "Admin Auth", visible_prefix(["admin"])

    if is_admin and len(parts) >= 2 and parts[1] == "apikeys":
        return "Admin API Keys", visible_prefix(["admin", "apikeys"])

    if is_admin and len(parts) >= 2 and parts[1] == "ai-services":
        return "Admin AI Services", visible_prefix(["admin", "ai-services"])

    if len(parts) > start and parts[start] == "panel":
        label_parts = [_titleize_openapi_segment(part) for part in parts[start:start + 3]]
        return f"{scope_prefix} {' '.join(part for part in label_parts if part)}", visible_prefix(parts[:start + 3])

    if len(parts) > start and parts[start] == "api":
        if len(parts) <= start + 1:
            return f"{scope_prefix} API", visible_prefix(parts[:start + 1])

        group_parts = parts[start + 1:start + 3]
        first_group = group_parts[0] if group_parts else ""
        if group_parts[:1] == ["storage"] and len(group_parts) >= 2:
            label = f"Storage {_titleize_openapi_segment(group_parts[1])}"
            return f"{scope_prefix} {label}", visible_prefix(parts[:start + 3])
        if group_parts[:1] == ["system"] and len(group_parts) >= 2:
            label = f"System {_titleize_openapi_segment(group_parts[1])}"
            return f"{scope_prefix} {label}", visible_prefix(parts[:start + 3])
        if group_parts[:2] == ["ai", "services"]:
            return f"{scope_prefix} AI Services", visible_prefix(parts[:start + 3])
        if first_group == "ai-services":
            return f"{scope_prefix} AI Services", visible_prefix(parts[:start + 2])
        label = _titleize_openapi_segment(first_group) or "General"
        return f"{scope_prefix} {label}", visible_prefix(parts[:start + 2])

    label = " ".join(
        _titleize_openapi_segment(part)
        for part in parts[start:start + 2]
        if _titleize_openapi_segment(part)
    ) or "General"
    prefix_len = min(len(parts), start + 2)
    if is_admin:
        return f"Admin {label}", visible_prefix(parts[:prefix_len])
    return label, "/" + "/".join(parts[:prefix_len])


def _decorate_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return schema

    used_tags: set[str] = set()
    tag_prefixes: dict[str, set[str]] = defaultdict(set)
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        default_tag, prefix = _derive_openapi_tag(path)
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            tags = [tag for tag in (operation.get("tags") or []) if isinstance(tag, str) and tag.strip()]
            if not tags:
                tags = [default_tag]
                operation["tags"] = tags
            for tag in tags:
                used_tags.add(tag)
                if prefix:
                    tag_prefixes[tag].add(prefix)

    existing_tags: dict[str, dict[str, Any]] = {}
    for item in schema.get("tags") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            existing_tags[name] = item

    schema["tags"] = [
        existing_tags.get(name, {
            "name": name,
            "description": f"Routes grouped under {sorted(tag_prefixes.get(name) or {'/'})[0]}",
        })
        for name in sorted(used_tags)
    ]
    return schema


def ensure_openapi_customization(app: FastAPI) -> FastAPI:
    if getattr(app.state, "_openapi_customized", False):
        return app

    def _custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            servers=app.servers,
            tags=app.openapi_tags,
        )
        app.openapi_schema = _decorate_openapi_schema(schema)
        return app.openapi_schema

    app.openapi = _custom_openapi
    app.state._openapi_customized = True
    return app


def register_i18n_routes(app: FastAPI) -> None:
    if getattr(app.state, "_i18n_routes_registered", False):
        return

    @app.get("/i18n/{lang}", tags=["I18N"])
    async def i18n_catalog(lang: str) -> dict[str, str]:
        from .translate import get_all_global_translations

        return get_all_global_translations(lang)

    app.state._i18n_routes_registered = True


def _is_admin_route_module(rel_path: Path) -> bool:
    parts = rel_path.with_suffix("").parts
    if len(parts) < 2 or parts[0] != "routes":
        return False
    if parts[1] in {"admin", "panel", "storage", "system", "distributed"}:
        return True
    if parts[1] == "ai_services" and len(parts) >= 3 and parts[2] == "panel":
        return True
    return False


def _is_admin_callback(callback: AppCallback) -> bool:
    module = getattr(callback, "__module__", "")
    admin_prefixes = (
        "core.server.routes.admin",
        "core.server.routes.panel",
        "core.server.routes.storage",
        "core.server.routes.system",
        "core.server.routes.distributed",
        "core.server.routes.ai_services.panel",
    )
    return module.startswith(admin_prefixes)


def _enabled_callbacks(callbacks: list[AppCallback], *, expose_internal: bool) -> list[AppCallback]:
    if expose_internal:
        return callbacks
    return [callback for callback in callbacks if not _is_admin_callback(callback)]


def _config_existing_dirs(value: str | list[str] | None) -> list[Path]:
    if not value:
        return []
    paths = [value] if isinstance(value, str) else list(value)
    return [Path(p) for p in paths if Path(p).is_dir()]


def _install_internal_path_rewriter(app: FastAPI, server_cfg: Any) -> None:
    if getattr(app.state, "_internal_path_rewriter_installed", False):
        return

    expose_internal = server_cfg.is_internal_exposed()
    original_add_api_route = app.add_api_route
    original_add_api_websocket_route = app.add_api_websocket_route
    original_include_router = app.include_router
    original_router_add_api_route = app.router.add_api_route
    original_router_add_api_websocket_route = app.router.add_api_websocket_route

    def _is_internal_route_path(path: str) -> bool:
        normalized = "/" + str(path or "").lstrip("/")
        return normalized.startswith("/admin") or normalized.startswith("/html-assets")

    def _rewrite(path: str) -> str | None:
        normalized = "/" + str(path or "").lstrip("/")
        if not _is_internal_route_path(normalized):
            return path
        if not expose_internal:
            return None
        return server_cfg.get_internal_path(normalized)

    def add_api_route(path: str, endpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        rewritten = _rewrite(path)
        if rewritten is None:
            return None
        return original_add_api_route(rewritten, endpoint, *args, **kwargs)

    def router_add_api_route(path: str, endpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        rewritten = _rewrite(path)
        if rewritten is None:
            return None
        return original_router_add_api_route(rewritten, endpoint, *args, **kwargs)

    def add_api_websocket_route(path: str, endpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        rewritten = _rewrite(path)
        if rewritten is None:
            return None
        return original_add_api_websocket_route(rewritten, endpoint, *args, **kwargs)

    def router_add_api_websocket_route(path: str, endpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        rewritten = _rewrite(path)
        if rewritten is None:
            return None
        return original_router_add_api_websocket_route(rewritten, endpoint, *args, **kwargs)

    def include_router(router, *args: Any, **kwargs: Any) -> None:
        route_paths = [str(getattr(route, "path", "")) for route in getattr(router, "routes", [])]
        if any(_is_internal_route_path(path) for path in route_paths):
            if not expose_internal:
                return None
            prefix = str(kwargs.pop("prefix", "") or "")
            internal_prefix = server_cfg.internal_path_prefix or ""
            kwargs["prefix"] = prefix + internal_prefix
        return original_include_router(router, *args, **kwargs)

    app.add_api_route = add_api_route  # type: ignore[method-assign]
    app.add_api_websocket_route = add_api_websocket_route  # type: ignore[method-assign]
    app.router.add_api_route = router_add_api_route  # type: ignore[method-assign]
    app.router.add_api_websocket_route = router_add_api_websocket_route  # type: ignore[method-assign]
    app.include_router = include_router  # type: ignore[method-assign]
    app.state._internal_path_rewriter_installed = True


def get_resources(*path: str) -> Path | None:
    from core.server.data_types.config import Config

    rel = Path(*path)
    if rel.is_absolute() or any(part in {"..", ""} for part in rel.parts):
        return None
    cfg = Config.GetConfig()
    for resource_dir in [*_config_existing_dirs(cfg.server_config.extra_resources_paths), RESOURCES_DIR]:
        try:
            base = resource_dir.resolve()
            candidate = (resource_dir / rel).resolve()
            candidate.relative_to(base)
        except Exception:
            continue
        if candidate.is_file() or candidate.is_dir():
            return candidate
    return None


def _normalize_worker_result(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _normalize_worker_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_worker_result(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_worker_result(item) for item in value)
    if isinstance(value, set):
        return [_normalize_worker_result(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            key: _normalize_worker_result(item)
            for key, item in asdict(value).items()
        }
    return value


def _is_redirect_stream_result(value: object) -> bool:
    if isinstance(value, StreamingResponse):
        return True
    if inspect.isasyncgen(value) or inspect.isgenerator(value):
        return True
    return False


def _stream_chunk_to_bytes(chunk: object) -> bytes:
    if isinstance(chunk, bytes):
        return chunk
    if isinstance(chunk, bytearray):
        return bytes(chunk)
    if isinstance(chunk, memoryview):
        return chunk.tobytes()
    return str(chunk).encode("utf-8")


async def _iter_stream_chunks(iterator: object):
    if hasattr(iterator, "__aiter__"):
        async for chunk in iterator:  # type: ignore[attr-defined]
            yield chunk
    else:
        for chunk in iterator:  # type: ignore[operator]
            yield chunk
            await asyncio.sleep(0)


def _worker_response_frame(value: object) -> bytes:
    data = pickle.dumps(value)
    return struct.pack("!I", len(data)) + data


async def _write_worker_response_frame(writer: asyncio.StreamWriter, value: object) -> None:
    writer.write(_worker_response_frame(value))
    await writer.drain()


async def _read_worker_response_frame(
    reader: asyncio.StreamReader,
    *,
    timeout: float | None,
) -> bytes:
    if timeout is None:
        length_data = await reader.readexactly(4)
        length = struct.unpack("!I", length_data)[0]
        return await reader.readexactly(length)
    length_data = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
    length = struct.unpack("!I", length_data)[0]
    return await asyncio.wait_for(reader.readexactly(length), timeout=timeout)


def _redirect_stream_start(value: object):
    from .shared import WorkerRedirectStreamStart

    if isinstance(value, StreamingResponse):
        headers = [
            (key, item)
            for key, item in value.headers.items()
            if key.lower() != "content-length"
        ]
        return WorkerRedirectStreamStart(
            status_code=value.status_code,
            media_type=value.media_type,
            headers=headers,
        ), value.body_iterator
    return WorkerRedirectStreamStart(media_type="text/event-stream"), value


async def _write_worker_redirect_result(
    writer: asyncio.StreamWriter,
    result: object,
) -> None:
    from .shared import WorkerRedirectStreamChunk, WorkerRedirectStreamEnd

    if hasattr(result, "result") and hasattr(result, "error"):
        stream_value = getattr(result, "result")
        if getattr(result, "error") is None and _is_redirect_stream_result(stream_value):
            stream_response = stream_value if isinstance(stream_value, StreamingResponse) else None
            stream_start, iterator = _redirect_stream_start(stream_value)
            result.result = stream_start  # type: ignore[attr-defined]
            await _write_worker_response_frame(writer, result)
            try:
                async for chunk in _iter_stream_chunks(iterator):
                    await _write_worker_response_frame(
                        writer,
                        WorkerRedirectStreamChunk(data=_stream_chunk_to_bytes(chunk)),
                    )
            except Exception as exc:
                await _write_worker_response_frame(
                    writer,
                    WorkerRedirectStreamEnd(error=f"{type(exc).__name__}: {exc}"),
                )
            else:
                await _write_worker_response_frame(writer, WorkerRedirectStreamEnd())
            finally:
                if stream_response is not None and stream_response.background is not None:
                    await stream_response.background()
            return

        result.result = _normalize_worker_result(stream_value)  # type: ignore[attr-defined]

    await _write_worker_response_frame(writer, result)


# ---- Public decorators ----
def on_before_app_created(f: AppFastAPICallback) -> AppFastAPICallback:
    """Register a callback invoked *before* the app is ready (in lifespan startup)."""
    _on_before_app_created_callbacks.append(f)
    return f

def on_app_created(f: AppFastAPICallback | AppNoArgCallback) -> AppFastAPICallback | AppNoArgCallback:
    """Register a callback invoked *after* route discovery, before lifespan starts."""
    _on_app_created_callbacks.append(f)
    return f

def on_app_shutdown(f: AppFastAPICallback | AppNoArgCallback) -> AppFastAPICallback | AppNoArgCallback:
    """Register a callback invoked when the app is shutting down."""
    _on_app_shutdown_callbacks.append(f)
    return f

def on_uvicorn_close(f: AppNoArgCallback) -> AppNoArgCallback:
    """Register a callback invoked once when uvicorn fully exits (not per-worker)."""
    _on_uvicorn_close_callbacks.append(f)
    return f

def invoke_uvicorn_close():
    """Invoke all on_uvicorn_close callbacks. Should be called once from the main process."""
    _sync_invoke_callbacks(_on_uvicorn_close_callbacks)


class _PublicFallbackResolver:
    """Resolve app HTML and public files after FastAPI route matching has failed."""

    def __init__(self, app_dirs: list[Path], public_dirs: list[Path]):
        self._app_dirs = app_dirs
        self._public_dirs = public_dirs

    def _candidate_paths_for_request(self, path: str) -> list[Path]:
        requested = Path(path.lstrip("/"))
        candidates = [requested]
        if requested.name.endswith(".min.js"):
            candidates.append(requested.with_name(requested.name[:-7] + ".js"))
        elif requested.name.endswith(".js"):
            candidates.append(requested.with_name(requested.name[:-3] + ".min.js"))
        if requested.name.endswith(".min.css"):
            candidates.append(requested.with_name(requested.name[:-8] + ".css"))
        elif requested.name.endswith(".css"):
            candidates.append(requested.with_name(requested.name[:-4] + ".min.css"))
        return candidates

    @lru_cache(maxsize=2048)
    def _resolve_cached(self, path: str) -> tuple[str, str, str | None] | None:
        lang, static_path = self._resolve_localized_path(path)
        html_path = self._app_html_path_for_request(static_path)
        if html_path is not None:
            return ("html", str(html_path), lang)

        html_path = self._public_html_path_for_request(static_path)
        if html_path is not None:
            return ("html", str(html_path), lang)

        file_path = self._public_file_for_request(static_path)
        if file_path is not None:
            return ("file", str(file_path), lang)

        return None

    def response_for_path(self, path: str) -> HTMLResponse | FileResponse | None:
        resolved = self._resolve_cached(path)
        if resolved is None:
            return None

        resolved_type, file_path, lang = resolved
        resolved_path = Path(file_path)
        if resolved_type == "html":
            from .html_injection import html_response_from_path_with_mobile

            response = html_response_from_path_with_mobile(resolved_path)
            if lang:
                response = self._with_html_lang(response, lang)
            return response

        media_type, _ = mimetypes.guess_type(str(resolved_path))
        return FileResponse(resolved_path, media_type=media_type)

    def _resolve_localized_path(self, path: str) -> tuple[str | None, str]:
        from .translate import is_language_code, normalize_language

        parts = [part for part in path.split("/") if part]
        if not parts or not is_language_code(parts[0]):
            return None, path
        lang = normalize_language(parts[0])
        stripped = "/" + "/".join(parts[1:])
        if path.endswith("/") and not stripped.endswith("/"):
            stripped += "/"
        if stripped == "/":
            return lang, stripped
        if self._request_path_exists(stripped):
            return lang, stripped
        return None, path

    def _request_path_exists(self, path: str) -> bool:
        return (
            self._app_html_path_for_request(path) is not None
            or self._public_file_for_request(path) is not None
            or self._public_html_path_for_request(path) is not None
        )

    def _public_file_for_request(self, path: str) -> Path | None:
        for public_dir in self._public_dirs:
            try:
                base = public_dir.resolve()
            except Exception:
                continue
            for request_path in self._candidate_paths_for_request(path):
                candidate = self._resolve_existing_request_path(base, public_dir, request_path, require_html=False)
                if candidate is not None and candidate.is_file():
                    return candidate
        return None

    def _app_html_path_for_request(self, path: str) -> Path | None:
        if self._has_private_app_path_part(path):
            return None
        return self._html_path_for_request(path, self._app_dirs, include_index_for_file=True)

    def _public_html_path_for_request(self, path: str) -> Path | None:
        return self._html_path_for_request(path, self._public_dirs, include_index_for_file=True)

    def _html_path_for_request(self, path: str, roots: list[Path], *, include_index_for_file: bool) -> Path | None:
        request_path = path or "/"
        candidates: list[Path] = []
        if request_path.endswith("/"):
            candidates.append(Path(request_path.lstrip("/")) / "index.html")
        else:
            raw = Path(request_path.lstrip("/"))
            candidates.append(raw)
            if raw.suffix == "":
                if include_index_for_file:
                    candidates.append(raw / "index.html")
                candidates.append(raw.with_suffix(".html"))

        for public_dir in roots:
            try:
                base = public_dir.resolve()
            except Exception:
                continue
            for rel in candidates:
                candidate = self._resolve_existing_request_path(base, public_dir, rel, require_html=True)
                if candidate is not None and candidate.is_file() and candidate.suffix.lower() == ".html":
                    return candidate
        return None

    def _resolve_existing_request_path(self, base: Path, root: Path, rel: Path, *, require_html: bool) -> Path | None:
        if rel.is_absolute() or any(part in {"", ".."} for part in rel.parts):
            return None
        exact = self._safe_existing_path(base, root / rel, require_html=require_html)
        if exact is not None:
            return exact
        return self._resolve_dynamic_request_path(base, root, rel.parts, require_html=require_html)

    def _safe_existing_path(self, base: Path, path: Path, *, require_html: bool) -> Path | None:
        try:
            candidate = path.resolve()
            candidate.relative_to(base)
        except Exception:
            return None
        if not candidate.is_file():
            return None
        if require_html and candidate.suffix.lower() != ".html":
            return None
        return candidate

    def _resolve_dynamic_request_path(
        self,
        base: Path,
        current: Path,
        parts: tuple[str, ...],
        *,
        require_html: bool,
        index: int = 0,
    ) -> Path | None:
        if index >= len(parts):
            return self._safe_existing_path(base, current, require_html=require_html)
        if not current.is_dir():
            return None

        part = parts[index]
        exact = self._resolve_dynamic_request_path(
            base,
            current / part,
            parts,
            require_html=require_html,
            index=index + 1,
        )
        if exact is not None:
            return exact

        is_last = index == len(parts) - 1
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            if child.name == part:
                continue
            if child.is_dir() and self._is_dynamic_path_token(child.name):
                resolved = self._resolve_dynamic_request_path(
                    base,
                    child,
                    parts,
                    require_html=require_html,
                    index=index + 1,
                )
                if resolved is not None:
                    return resolved
            elif is_last and child.is_file() and self._dynamic_file_matches(child.name, part):
                return self._safe_existing_path(base, child, require_html=require_html)
        return None

    def _is_dynamic_path_token(self, value: str) -> bool:
        return len(value) > 2 and value.startswith("_") and value.endswith("_")

    def _dynamic_file_matches(self, candidate_name: str, requested_name: str) -> bool:
        candidate = Path(candidate_name)
        requested = Path(requested_name)
        return candidate.suffix == requested.suffix and self._is_dynamic_path_token(candidate.stem)

    def _has_private_app_path_part(self, path: str) -> bool:
        for part in Path(path.lstrip("/")).parts:
            if part in {"__init__.py", ""}:
                continue
            if part.startswith("_"):
                return True
        return False

    def _with_html_lang(self, response: HTMLResponse, lang: str) -> HTMLResponse:
        text = response.body.decode(response.charset or "utf-8", "replace")
        normalized = lang
        if re.search(r"<html\b", text, re.IGNORECASE):
            def _replace(match: re.Match[str]) -> str:
                tag = match.group(0)
                if re.search(r"\slang\s*=", tag, re.IGNORECASE):
                    return re.sub(
                        r"\slang\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
                        f' lang="{normalized}"',
                        tag,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                return tag[:-1] + f' lang="{normalized}">'

            text = re.sub(r"<html\b[^>]*>", _replace, text, count=1, flags=re.IGNORECASE)
        headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
        new_response = HTMLResponse(text, status_code=response.status_code, headers=headers)
        new_response.headers["content-language"] = normalized
        return new_response


def _has_registered_route_match(app: FastAPI, scope: dict[str, Any]) -> bool:
    from starlette.routing import Match

    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match != Match.NONE:
            return True
    return False


def register_public_fallback(app: FastAPI, config=None) -> None:
    """Register cached public-file fallback that runs only after route miss."""

    if getattr(app.state, "_public_fallback_registered", False):
        return

    from core.server.data_types.config import Config

    cfg = config or Config.GetConfig()
    app_dirs: list[Path] = []
    app_dirs.extend(_config_existing_dirs(cfg.server_config.extra_app_paths))
    if APP_DIR.is_dir():
        app_dirs.append(APP_DIR)

    extra_public = cfg.server_config.extra_public_paths
    public_dirs: list[Path] = []

    public_dirs.extend(_config_existing_dirs(extra_public))
    if PUBLIC_DIR.is_dir():
        public_dirs.append(PUBLIC_DIR)
    if not app_dirs and not public_dirs:
        return

    resolver = _PublicFallbackResolver(app_dirs, public_dirs)
    app.state._public_fallback_registered = True
    app.state.public_fallback_resolver = resolver

    @app.middleware("http")
    async def _public_fallback_middleware(request: Request, call_next):
        response = await call_next(request)
        if response.status_code != 404 or request.method not in {"GET", "HEAD"}:
            return response
        if _has_registered_route_match(app, request.scope):
            return response
        from .rtc_room import is_rtc_room_enabled, is_rtc_room_public_path

        if is_rtc_room_public_path(request.url.path) and not is_rtc_room_enabled(cfg):
            return response
        fallback_response = resolver.response_for_path(request.url.path)
        if fallback_response is None:
            return response
        return fallback_response

# ---- App factory ----
def create_app(config=None) -> FastAPI:
    """Create the FastAPI instance, auto-discover routes, wire lifespan.
    
    Args:
        config: Optional pre-built Config instance. When provided it overrides
        the global singleton so that e.g. extra_app_paths / extra_public_paths
        can be injected programmatically.
    """
    global _app, _inner_comm_server_thread, _app_stop_event
    if _app is not None:
        return _app
    from core.server.data_types.config import Config
    if config is not None:
        Config.SetConfig(config)
    cfg = Config.GetConfig()
    server_cfg = cfg.server_config
    expose_internal = server_cfg.is_internal_exposed()
    enable_rtc_chatroom = bool(server_cfg.enable_rtc_chatroom)

    # ---- Import all route modules ----
    curr_dir = Path(__file__).resolve().parent
    routes_root = curr_dir / "routes"

    if routes_root.is_dir():
        for py_file in sorted(routes_root.rglob("*.py")):
            if py_file.name.startswith("_"):
                continue
            rel = py_file.relative_to(curr_dir)
            if not expose_internal and _is_admin_route_module(rel):
                continue
            if not enable_rtc_chatroom and rel.with_suffix("").parts == ("routes", "rtc_room"):
                continue
            module_name = str(rel.with_suffix("")).replace(os.sep, ".")
            full_module = f"core.server.{module_name}"
            logger.debug(f"Importing route module {full_module} ...")
            try:
                importlib.import_module(full_module)
            except Exception as e:
                logger.warning(f"Import {full_module} failed: {e}\n{traceback.format_exc()}")

    logger.debug("All route modules loaded.")

    # ---- Lifespan ----
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(f"Worker PID {os.getpid()} starting...")
        from core.utils.type_utils import install_cached_docstring_extractor
        from .storage_utils import warmup_storage_clients

        install_cached_docstring_extractor()
        if expose_internal:
            try:
                from .routes.ai_services.panel import sync_ai_services_config_from_shared
                sync_ai_services_config_from_shared()
            except Exception as exc:
                logger.debug('AI services shared-config sync skipped: %s', exc)
        from core.ai import preload_default_services
        _skip_preload = os.getenv("__SKIP_AI_PRELOAD__", "").strip() in ("1", "true", "yes")
        if _skip_preload:
            logger.info("AI service preload skipped (__SKIP_AI_PRELOAD__=1).")
        else:
            preload_default_services(background=True, probe_predefined_clients=False)
        await warmup_storage_clients(logger=logger, phase="worker startup")
        # Start distributed services
        try:
            from core.server.distributed import NodeRegistry
            from core.server.shared_dict import GlobalSharedDict
            await NodeRegistry.get_instance().start()
            await GlobalSharedDict.get_instance().start()
        except Exception as exc:
            logger.debug("Distributed services startup skipped: %s", exc)
        await _invoke_callbacks(_enabled_callbacks(_on_before_app_created_callbacks, expose_internal=expose_internal), app)
        # Move Mount("/admin") and Mount("") to the end so lifespan-registered Routes are checked first.
        # Mount("") must remain the absolute last catch-all.
        from starlette.routing import Mount
        admin_mount: Mount | None = None
        root_mount: Mount | None = None
        for route in list(app.routes):
            if isinstance(route, Mount):
                if route.path == server_cfg.get_internal_admin_path():
                    admin_mount = route
                    app.routes.remove(route)
                elif route.path == "":
                    root_mount = route
                    app.routes.remove(route)
        if admin_mount is not None:
            app.routes.append(admin_mount)
        if root_mount is not None:
            app.routes.append(root_mount)
        # After uvicorn's dictConfig runs (before lifespan), root handlers
        # and uvicorn.* loggers can be left in inconsistent state. Re-apply
        # our root logger setup — it's idempotent when handlers already exist.
        try:
            import logging as _logging
            from core.server.data_types.config import _correct_uvicorn_loggers, Config as _SrvConfig
            _cfg = _SrvConfig.GetConfig()
            _cfg.log_config.init_root_logger(_logging.getLogger())
            _correct_uvicorn_loggers(_cfg.log_config.get_int_log_level())
        except Exception as exc:
            logger.debug("Post-lifespan logger correction skipped: %s", exc)
        # Publish "this worker is ready" to AppSharedData so the main process
        # rendezvous thread can emit the completion banner.
        try:
            from .shared import AppSharedData as _AppSharedData
            _AppSharedData.Get().mark_worker_ready(os.getpid())
        except Exception as exc:
            logger.debug("mark_worker_ready failed: %s", exc)
        yield
        logger.info(f"Worker PID {os.getpid()} shutting down...")
        os.environ["__APP_SHUTTING_DOWN__"] = "1"
        await _invoke_callbacks(_on_app_shutdown_callbacks, app)
        _app_stop_event.set()
        logger.info(f"Worker PID {os.getpid()} exited.")
        _schedule_worker_hard_exit_after_lifespan()

    app = FastAPI(
        title="Backend",
        description="API — extensible FastAPI backend with auto-discovered routes, admin panel, and pluggable storage/AI.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=server_cfg.get_internal_admin_path("openapi.json") if expose_internal else None,
    )
    _install_internal_path_rewriter(app, server_cfg)
    ensure_openapi_customization(app)
    register_i18n_routes(app)

    @app.exception_handler(Exception)
    async def _log_unhandled_exception(request: Request, exc: Exception):
        logger.exception(
            "Unhandled application exception for %s %s",
            getattr(request, "method", "?"),
            getattr(getattr(request, "url", None), "path", "?"),
            exc_info=exc,
        )
        return PlainTextResponse("Internal Server Error", status_code=500)

    @app.middleware("http")
    async def _advance_request_cast_middleware(request: Request, call_next):
        return await call_next(AdvanceRequest.Cast(request))

    # ---- Middleware: AI API exposure control ----
    @app.middleware("http")
    async def _ai_api_exposure_middleware(request: Request, call_next):
        return await call_next(request)

    # ---- Middleware: internal IP restriction ----
    _internal_ip_patterns = server_cfg.get_internal_path_allowed_ip_patterns()

    @app.middleware("http")
    async def _internal_ip_restriction_middleware(request: Request, call_next):
        path = request.url.path
        if server_cfg.is_internal_path(path) and path != (app.openapi_url or ""):
            if _internal_ip_patterns:
                client_ip = request.client.host if request.client else None
                if client_ip and not any(fnmatch.fnmatchcase(client_ip, pattern) for pattern in _internal_ip_patterns):
                    logger.warning("Internal access denied from %s", client_ip)
                    return JSONResponse(
                        {"detail": "Internal access denied from this IP."},
                        status_code=403,
                    )
        return await call_next(request)

    _request_trace_enabled = os.getenv("__PT_REQUEST_TRACE__", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    @app.middleware("http")
    async def _request_trace_middleware(request: Request, call_next):
        if not _request_trace_enabled:
            return await call_next(request)

        start_time = asyncio.get_running_loop().time()
        request_path = request.url.path
        logger.warning(
            "REQUEST TRACE start pid=%s method=%s path=%s",
            os.getpid(),
            request.method,
            request_path,
        )
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (asyncio.get_running_loop().time() - start_time) * 1000
            logger.exception(
                "REQUEST TRACE error pid=%s method=%s path=%s elapsed_ms=%.1f",
                os.getpid(),
                request.method,
                request_path,
                elapsed_ms,
            )
            raise

        elapsed_ms = (asyncio.get_running_loop().time() - start_time) * 1000
        logger.warning(
            "REQUEST TRACE end pid=%s method=%s path=%s status=%s elapsed_ms=%.1f",
            os.getpid(),
            request.method,
            request_path,
            response.status_code,
            elapsed_ms,
        )
        return response

    _app = app

    # ---- Register worker & start inner communication server ----
    from .shared import AppSharedData
    shared_data = AppSharedData.Get()
    if _inner_comm_server_thread is not None and _inner_comm_server_thread.is_alive():
        shared_data.register_worker(pid=os.getpid())
        comm_port: int | None = None
    else:
        if _app_stop_event.is_set():
            _app_stop_event = asyncio.Event()
        self_info = shared_data.register_worker(pid=os.getpid())
        comm_port = self_info.msg_port

    async def _handle_inner_comm(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming cross-worker messages on the TCP channel."""
        buf = b""
        target_size: int | None = None

        async def handle(msg: "WorkerMessage"):
            try:
                r = await msg.handle(get_app())
                await _write_worker_redirect_result(writer, r)
            except Exception as e:
                logger.error(f"Error handling worker message: {e}\n{traceback.format_exc()}")

        while not _app_stop_event.is_set():
            try:
                data = await reader.read(4096)
                if not data:
                    break
                buf += data
                while True:
                    if target_size is None:
                        if len(buf) >= 4:
                            target_size = struct.unpack('!I', buf[:4])[0]
                            buf = buf[4:]
                        else:
                            break
                    if target_size is not None and len(buf) >= target_size:
                        msg_data = buf[:target_size]
                        buf = buf[target_size:]
                        target_size = None
                        try:
                            msg = pickle.loads(msg_data)
                            asyncio.create_task(handle(msg))
                        except Exception as e:
                            logger.error(f"Error deserializing worker message: {e}\n{traceback.format_exc()}")
                    else:
                        break
            except Exception as e:
                logger.error(f"Error in inner communication: {e}\n{traceback.format_exc()}")
                await asyncio.sleep(0)
                break

    async def _start_inner_comm_server():
        nonlocal comm_port
        if comm_port is None:
            return
        bind_attempts = 0
        while not _is_app_shutting_down():
            try:
                server = await asyncio.start_server(_handle_inner_comm, '127.0.0.1', comm_port)
                async with server:
                    await server.serve_forever()
                return
            except OSError as exc:
                if _is_app_shutting_down():
                    return
                is_addr_in_use = exc.errno == 10048 or getattr(exc, "winerror", None) == 10048
                if not is_addr_in_use or bind_attempts >= 3:
                    raise
                bind_attempts += 1
                from .shared import AppSharedData

                logger.warning(
                    "Worker PID %s inner communication port %s is already in use; reallocating (attempt %s).",
                    os.getpid(),
                    comm_port,
                    bind_attempts,
                )
                try:
                    self_info = AppSharedData.Get().reallocate_worker_msg_port(os.getpid())
                except (BrokenPipeError, ConnectionResetError, EOFError, OSError) as reallocate_exc:
                    logger.debug(
                        "Worker PID %s stopped inner communication port reallocation: %s",
                        os.getpid(),
                        reallocate_exc,
                    )
                    return
                comm_port = self_info.msg_port

    def _run_inner_comm_server():
        try:
            asyncio.run(_start_inner_comm_server())
        except Exception as exc:
            if _is_app_shutting_down():
                logger.debug("Inner communication server stopped during shutdown: %s", exc)
                return
            logger.error(f"Inner communication server failed: {exc}\n{traceback.format_exc()}")

    if comm_port is not None:
        _inner_comm_server_thread = Thread(target=_run_inner_comm_server, daemon=True)
        _inner_comm_server_thread.start()

    from .route import RouteLoader

    # ---- Mount extra app paths before app/ so collisions prefer extras ----
    for p_path in _config_existing_dirs(cfg.server_config.extra_app_paths):
        RouteLoader(p_path, app).load_all()

    # ---- Mount auto-discovered Route classes from app/ ----
    if APP_DIR.is_dir():
        RouteLoader(APP_DIR, app).load_all()

    # ---- Mount static files (public + admin-panel + extras) ----
    class _AdaptiveHTMLStaticFiles:
        """ASGI wrapper around StaticFiles that merges .m.html mobile branches."""
        def __init__(self, static_app, public_dir: Path):
            self._static = static_app
            self._public_dir = public_dir

        def _candidate_paths_for_request(self, path: str) -> list[Path]:
            requested = Path(path.lstrip("/"))
            candidates = [requested]
            if requested.name.endswith(".min.js"):
                candidates.append(requested.with_name(requested.name[:-7] + ".js"))
            elif requested.name.endswith(".js"):
                candidates.append(requested.with_name(requested.name[:-3] + ".min.js"))
            if requested.name.endswith(".min.css"):
                candidates.append(requested.with_name(requested.name[:-8] + ".css"))
            elif requested.name.endswith(".css"):
                candidates.append(requested.with_name(requested.name[:-4] + ".min.css"))
            return candidates

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                from starlette.staticfiles import get_route_path
                path = get_route_path(scope)
                lang, static_path = self._resolve_localized_path(path)
                html_path = self._html_path_for_request(static_path)
                if html_path is not None:
                    from .html_injection import html_response_from_path_with_mobile
                    response = html_response_from_path_with_mobile(html_path)
                    if lang:
                        response = self._with_html_lang(response, lang)
                    await response(scope, receive, send)
                    return
                if static_path != path:
                    localized_scope = dict(scope)
                    localized_scope["path"] = static_path
                    await self._static(localized_scope, receive, send)
                    return
            await self._static(scope, receive, send)

        def _resolve_localized_path(self, path: str) -> tuple[str | None, str]:
            from .translate import is_language_code, normalize_language

            parts = [part for part in path.split("/") if part]
            if not parts or not is_language_code(parts[0]):
                return None, path
            lang = normalize_language(parts[0])
            stripped = "/" + "/".join(parts[1:])
            if path.endswith("/") and not stripped.endswith("/"):
                stripped += "/"
            if stripped == "/":
                return lang, stripped
            if self._request_path_exists(stripped):
                return lang, stripped
            return None, path

        def _request_path_exists(self, path: str) -> bool:
            return self._file_for_request(path) is not None or self._html_path_for_request(path) is not None

        def _file_for_request(self, path: str) -> Path | None:
            try:
                base = self._public_dir.resolve()
            except Exception:
                return None
            for request_path in self._candidate_paths_for_request(path):
                try:
                    candidate = (self._public_dir / request_path).resolve()
                    candidate.relative_to(base)
                except Exception:
                    continue
                if candidate.is_file():
                    return candidate
            return None

        def _html_path_for_request(self, path: str) -> Path | None:
            request_path = path or "/"
            candidates: list[Path] = []
            if request_path.endswith("/"):
                candidates.append(Path(request_path.lstrip("/")) / "index.html")
            else:
                raw = Path(request_path.lstrip("/"))
                candidates.append(raw)
                if raw.suffix == "":
                    candidates.append(raw.with_suffix(".html"))
            try:
                base = self._public_dir.resolve()
            except Exception:
                return None
            for rel in candidates:
                try:
                    candidate = (self._public_dir / rel).resolve()
                    candidate.relative_to(base)
                except Exception:
                    continue
                if candidate.is_file() and candidate.suffix.lower() == ".html":
                    return candidate
            return None

        def _with_html_lang(self, response: HTMLResponse, lang: str) -> HTMLResponse:
            text = response.body.decode(response.charset or "utf-8", "replace")
            normalized = lang
            if re.search(r"<html\b", text, re.IGNORECASE):
                def _replace(match: re.Match[str]) -> str:
                    tag = match.group(0)
                    if re.search(r"\slang\s*=", tag, re.IGNORECASE):
                        return re.sub(
                            r"\slang\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
                            f' lang="{normalized}"',
                            tag,
                            count=1,
                            flags=re.IGNORECASE,
                        )
                    return tag[:-1] + f' lang="{normalized}">'

                text = re.sub(r"<html\b[^>]*>", _replace, text, count=1, flags=re.IGNORECASE)
            headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
            new_response = HTMLResponse(text, status_code=response.status_code, headers=headers)
            new_response.headers["content-language"] = normalized
            return new_response

    extra_public = cfg.server_config.extra_public_paths
    register_public_fallback(app, cfg)

    admin_panel_dir = get_resources("admin-panel")
    internal_admin_path = server_cfg.get_internal_admin_path()
    if expose_internal and admin_panel_dir is not None and admin_panel_dir.is_dir():
        class _AdminPanelStaticFiles:
            """ASGI wrapper that returns 404 for /login and /session so FastAPI routes handle them."""
            _EXEMPT = {"/login", "/session", "/login/", "/session/"}
            def __init__(self, static_app):
                self._static = static_app
            async def __call__(self, scope, receive, send):
                if scope.get("type") == "http":
                    from starlette.staticfiles import get_route_path
                    request_path = get_route_path(scope)
                    path = scope.get("path", "")
                    if path in self._EXEMPT:
                        from starlette.responses import Response
                        response = Response(status_code=404)
                        await response(scope, receive, send)
                        return
                    html_path = self._html_path_for_request(request_path)
                    if html_path is not None:
                        from .html_injection import html_response_from_path
                        response = html_response_from_path(html_path)
                        await response(scope, receive, send)
                        return
                await self._static(scope, receive, send)

            def _html_path_for_request(self, path: str) -> Path | None:
                request_path = path or "/"
                if request_path.startswith(internal_admin_path + "/"):
                    request_path = request_path[len(internal_admin_path):]
                elif request_path == internal_admin_path:
                    request_path = "/"
                candidates: list[Path] = []
                stripped = request_path.strip("/")
                parts = [p for p in request_path.split("/") if p]
                if not parts:
                    candidates.extend([Path("index.html"), Path("panel.html")])
                elif request_path.endswith("/"):
                    base_dir = Path(*parts)
                    candidates.append(base_dir / "index.html")
                    candidates.append(base_dir.with_suffix(".html"))
                else:
                    base_file = Path(*parts)
                    if base_file.suffix == "":
                        candidates.append(base_file.with_suffix(".html"))
                    else:
                        candidates.append(base_file)
                    if len(parts) >= 2:
                        parent = Path(*parts[:-2]) if len(parts) > 2 else Path(".")
                        last_two = parts[-2:]
                        for sep in ("_", "-"):
                            candidates.append(parent / (sep.join(last_two) + ".html"))
                        candidates.append(parent / (last_two[0].replace("-", "_") + "_" + last_two[1] + ".html"))
                    if len(parts) == 2:
                        dir_name = parts[0]
                        page_name = parts[1]
                        for sep in ("_", "-"):
                            candidates.append(Path(dir_name) / (f"{dir_name}{sep}{page_name}.html"))
                        candidates.append(Path(dir_name) / (f"{dir_name.replace('-', '_')}_{page_name}.html"))
                        dir_tail = dir_name.replace("-", "_").split("_")[-1]
                        candidates.append(Path(dir_name) / (f"{dir_tail}_{page_name}.html"))
                seen: set[str] = set()
                deduped: list[Path] = []
                for rel in candidates:
                    key = str(rel).replace("\\", "/")
                    if key not in seen:
                        seen.add(key)
                        deduped.append(rel)
                try:
                    base = admin_panel_dir.resolve()
                except Exception:
                    return None
                for rel in deduped:
                    try:
                        candidate = (admin_panel_dir / rel).resolve()
                        candidate.relative_to(base)
                    except Exception:
                        continue
                    if candidate.is_file() and candidate.suffix.lower() == ".html":
                        return candidate
                return None
        app.mount(internal_admin_path, _AdminPanelStaticFiles(StaticFiles(directory=str(admin_panel_dir), html=True)), name="admin-panel")

    if extra_public:
        resolved_extra_public = [str(p) for p in _config_existing_dirs(extra_public)]
        app.state.extra_public_paths = resolved_extra_public
        for idx, public_path in enumerate(resolved_extra_public):
            p_path = Path(public_path)
            app.mount(f"/extra-public-{idx}", _AdaptiveHTMLStaticFiles(StaticFiles(directory=str(p_path)), p_path), name=f"extra-public-{idx}")
    else:
        app.state.extra_public_paths = []

    extra_resources = cfg.server_config.extra_resources_paths
    if extra_resources:
        app.state.extra_resources_paths = [str(p) for p in _config_existing_dirs(extra_resources)]
    else:
        app.state.extra_resources_paths = []

    # sync callbacks (run before lifespan, right after route import)
    _sync_invoke_callbacks(_enabled_callbacks(_on_app_created_callbacks, expose_internal=expose_internal), app)

    return app


def get_app() -> FastAPI:
    """Return the app singleton. Raises if ``create_app()`` hasn't been called."""
    if _app is None:
        raise RuntimeError("App not created yet — call create_app() first.")
    return _app


async def redirect_to_worker(worker_id: int, request: Request, request_params: dict[str, object]) -> object:
    """Redirect a request to another worker by PID.
    
    Args:
        worker_id: Target worker PID.
        request: FastAPI Request object (contains path and method).
        request_params: Parameters to pass to the target endpoint.
    
    Returns:
        The result from the target worker's endpoint handler.
    """
    from .shared import (
        WorkerRedirectMessage,
        AppSharedData,
        WorkerRedirectStreamStart,
        WorkerRedirectStreamChunk,
        WorkerRedirectStreamEnd,
    )

    msg = WorkerRedirectMessage(
        sender=os.getpid(),
        path=request.url.path,
        method=request.method,
        request_params=request_params,
    )
    if worker_id == os.getpid():
        # Same worker, handle locally
        r: WorkerRedirectMessage.RedirectResult = await msg.handle(get_app())
        if r.error is not None:
            raise r.error
        if _is_redirect_stream_result(r.result) and not isinstance(r.result, StreamingResponse):
            return StreamingResponse(_iter_stream_chunks(r.result), media_type="text/event-stream")
        return r.result

    shared_data = AppSharedData.Get()
    worker_info = shared_data.get_worker(worker_id)
    lock = worker_info.get_client_lock()
    await lock.acquire()
    release_lock = True

    try:
        reader, writer = await worker_info.get_client()
        writer.write(msg.dump())
        await writer.drain()

        try:
            response_data = await _read_worker_response_frame(reader, timeout=30.0)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Worker {worker_id} did not respond within 30s for redirect to {msg.path}")

        result: WorkerRedirectMessage.RedirectResult = pickle.loads(response_data)
        if result.error is not None:
            raise result.error

        if isinstance(result.result, WorkerRedirectStreamStart):
            stream_start = result.result

            async def _stream_from_worker():
                nonlocal release_lock
                try:
                    while True:
                        frame = pickle.loads(await _read_worker_response_frame(reader, timeout=None))
                        if isinstance(frame, WorkerRedirectStreamChunk):
                            yield frame.data
                        elif isinstance(frame, WorkerRedirectStreamEnd):
                            if frame.error:
                                raise RuntimeError(frame.error)
                            break
                        else:
                            raise RuntimeError(
                                f"Unexpected worker redirect stream frame: {type(frame).__name__}"
                            )
                finally:
                    if not release_lock:
                        release_lock = True
                        lock.release()

            headers = {
                key: value
                for key, value in stream_start.headers
                if key.lower() != "content-length"
            }
            release_lock = False
            return StreamingResponse(
                _stream_from_worker(),
                status_code=stream_start.status_code,
                media_type=stream_start.media_type,
                headers=headers,
            )

        return result.result
    finally:
        if release_lock:
            lock.release()


async def send_message_to_worker(worker_id: int, msg: 'WorkerMessage') -> object:
    """Send a generic worker message and return the remote handler result."""
    from .shared import AppSharedData

    if worker_id == os.getpid():
        return await msg.handle(get_app())

    shared_data = AppSharedData.Get()
    worker_info = shared_data.get_worker(worker_id)

    async with worker_info.get_client_lock():
        reader, writer = await worker_info.get_client()
        writer.write(msg.dump())
        await writer.drain()

        length_data = await asyncio.wait_for(reader.readexactly(4), timeout=30.0)
        length = struct.unpack('!I', length_data)[0]
        response_data = await asyncio.wait_for(reader.readexactly(length), timeout=30.0)
    return pickle.loads(response_data)


__all__ = [
    "on_before_app_created",
    "on_app_created",
    "on_app_shutdown",
    "on_uvicorn_close",
    "invoke_uvicorn_close",
    "redirect_to_worker",
    "send_message_to_worker",
    "create_app",
    "get_app",
]
