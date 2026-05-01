# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import fnmatch
import time
from pathlib import Path
from urllib.parse import quote
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from ...app import get_resources, on_app_created, on_before_app_created
from ...html_injection import html_response_from_path
from ...security.admin_password import has_admin_password, verify_admin_password
from core.server.data_types.apikey import (
    APIKey,
    APIKeyValidationResult,
    create_apikey,
    delete_apikey,
    extract_apikey_from_request,
    extract_apikey_from_websocket,
    get_apikey_by_key,
    get_apikey_expire_seconds,
    validate_apikey_identity,
    validate_apikey_route,
)
from core.server.data_types.config import Config


ADMIN_APIKEY_COOKIE_NAME = "proj_admin_apikey"
ADMIN_APIKEY_LOCALSTORAGE_KEY = "proj.admin.apikey"
ADMIN_APIKEY_TTL_SECONDS = 60 * 60 * 24 * 3
_ADMIN_APIKEY_NAME_PREFIX = "__proj_admin_login__:"
_ADMIN_APIKEY_COMMENT = "generated admin login session apikey"


_AUTH_EXEMPT_PATHS = {
    "/admin/login",
    "/admin/session",
    "/admin/openapi.json",
}
_AUTH_EXEMPT_PREFIXES = (
    "/admin/login",
)


class AdminLoginRequest(BaseModel):
    password: str
    next_path: str | None = None


class AdminLoginResponse(BaseModel):
    authenticated: bool
    api_key: str
    cookie_name: str = ADMIN_APIKEY_COOKIE_NAME
    localstorage_key: str = ADMIN_APIKEY_LOCALSTORAGE_KEY
    expires_at: float
    ttl_seconds: int = ADMIN_APIKEY_TTL_SECONDS
    redirect_to: str


class AdminSessionResponse(BaseModel):
    authenticated: bool
    cookie_name: str = ADMIN_APIKEY_COOKIE_NAME
    localstorage_key: str = ADMIN_APIKEY_LOCALSTORAGE_KEY
    expires_at: float | None = None


def _extract_cookie_value(cookie_header: str, cookie_name: str) -> str | None:
    for item in str(cookie_header or "").split(";"):
        name, _, value = item.strip().partition("=")
        if name == cookie_name and value:
            return value.strip()
    return None


def _extract_admin_apikey_from_headers(headers: dict[str, str]) -> str | None:
    return _extract_cookie_value(headers.get("cookie") or "", ADMIN_APIKEY_COOKIE_NAME)


def _extract_admin_apikey_from_request(request: Request) -> str | None:
    token = extract_apikey_from_request(request)
    if token:
        return token
    return _extract_admin_apikey_from_headers(dict(request.headers.items()))


def _extract_admin_apikey_from_websocket(websocket: object) -> str | None:
    token = extract_apikey_from_websocket(websocket)  # type: ignore[arg-type]
    if token:
        return token
    return _extract_admin_apikey_from_headers(dict(getattr(websocket, "headers", {}).items()))


def _is_login_session_apikey(api_key: APIKey | None) -> bool:
    if api_key is None:
        return False
    return str(api_key.name or "").startswith(_ADMIN_APIKEY_NAME_PREFIX)


async def _issue_admin_login_apikey(*, ttl_seconds: int = ADMIN_APIKEY_TTL_SECONDS) -> tuple[APIKey, float]:
    now = time.time()
    api_key = await create_apikey(
        name=f"{_ADMIN_APIKEY_NAME_PREFIX}{int(now)}",
        comment=_ADMIN_APIKEY_COMMENT,
        credit=0.0,
        banned=False,
        whitelist_routes="all",
        blacklist_routes=[],
        expire_seconds=ttl_seconds,
    )
    return api_key, now + int(ttl_seconds)


async def _revoke_admin_login_apikey(key: str | None) -> None:
    normalized = str(key or "").strip()
    if not normalized:
        return
    api_key = await get_apikey_by_key(normalized)
    if not _is_login_session_apikey(api_key):
        return
    await delete_apikey(str(getattr(api_key, "id", "") or ""))


async def _resolve_authenticated_apikey(key: str | None) -> tuple[APIKey | None, APIKeyValidationResult | None]:
    normalized = str(key or "").strip()
    if not normalized:
        return None, None
    result = await validate_apikey_identity(normalized)
    if not result.ok:
        return None, result
    return await get_apikey_by_key(normalized), result


def _normalize_next_path(value: str | None) -> str:
    admin_panel_path = Config.GetConfig().server_config.get_internal_admin_path("panel")
    raw = str(value or "").strip()
    if not raw.startswith("/"):
        return admin_panel_path
    if raw.startswith("//"):
        return admin_panel_path
    if _is_auth_exempt_path(raw):
        return admin_panel_path
    return raw


def _is_auth_exempt_path(path: str) -> bool:
    server_cfg = Config.GetConfig().server_config
    auth_exempt_paths = {
        server_cfg.get_internal_admin_path("login"),
        server_cfg.get_internal_admin_path("session"),
        server_cfg.get_internal_admin_path("openapi.json"),
    }
    auth_exempt_prefixes = (server_cfg.get_internal_admin_path("login"),)
    if path in auth_exempt_paths:
        return True
    if any(path == prefix or path.startswith(prefix + "/") for prefix in auth_exempt_prefixes):
        return True
    if path in _AUTH_EXEMPT_PATHS:
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _AUTH_EXEMPT_PREFIXES)


def _wants_html(scope: Scope) -> bool:
    headers = dict(scope.get("headers") or [])
    accept = headers.get(b"accept", b"").decode("latin-1", "ignore")
    return "text/html" in accept or "*/*" in accept


def _wants_explicit_html(scope: Scope) -> bool:
    headers = dict(scope.get("headers") or [])
    accept = headers.get(b"accept", b"").decode("latin-1", "ignore")
    return "text/html" in accept or "application/xhtml+xml" in accept


def _is_http_login_flow_path(path: str) -> bool:
    return _is_auth_exempt_path(path)


def _is_websocket_login_flow_path(path: str) -> bool:
    return False


def _is_html_navigation(scope: Scope) -> bool:
    if not _is_html_document_request(scope):
        return False
    path = str(scope.get("path") or "")
    if path == "/openapi.json" or path.startswith("/api/") or path == "/api":
        return False
    return True


def _is_html_document_request(scope: Scope) -> bool:
    if str(scope.get("method") or "GET").upper() not in {"GET", "HEAD"}:
        return False
    path = str(scope.get("path") or "")
    admin_api_path = Config.GetConfig().server_config.get_internal_admin_path("api")
    if path == "/openapi.json":
        return False
    if (
        path.startswith("/api/") or path == "/api"
        or path.startswith(admin_api_path + "/") or path == admin_api_path
        or path.startswith("/admin/api/") or path == "/admin/api"
    ):
        return _wants_explicit_html(scope) or path.endswith("/html") or path.endswith("-html")
    return _wants_html(scope)


def _route_text_from_scope(scope: Scope) -> str:
    path = str(scope.get("path") or "").strip() or "/"
    return path


def _admin_ip_allowed(scope: Scope) -> bool:
    patterns = Config.GetConfig().server_config.get_internal_path_allowed_ip_patterns()
    if not patterns:
        return True
    client = scope.get("client")
    client_ip = str(client[0]) if isinstance(client, tuple) and client else ""
    return bool(client_ip and any(fnmatch.fnmatchcase(client_ip, pattern) for pattern in patterns))


async def _validate_admin_or_apikey_http(scope: Scope, receive: Receive) -> tuple[bool, APIKeyValidationResult | None]:
    request = Request(scope, receive=receive)
    api_key_text = _extract_admin_apikey_from_request(request)
    if not api_key_text:
        return False, None
    if _is_html_document_request(scope):
        result = await validate_apikey_identity(api_key_text)
    else:
        result = await validate_apikey_route(api_key_text, _route_text_from_scope(scope), record_access=True)
    return bool(result.ok), result


async def _validate_admin_or_apikey_websocket(scope: Scope) -> tuple[bool, APIKeyValidationResult | None]:
    query_params = dict(parse_qsl((scope.get("query_string") or b"").decode("latin-1", "ignore"), keep_blank_values=True))
    websocket = type(
        "AuthWebSocket",
        (),
        {
            "headers": {k.decode("latin-1"): v.decode("latin-1") for k, v in (scope.get("headers") or [])},
            "query_params": query_params,
        },
    )()
    api_key_text = _extract_admin_apikey_from_websocket(websocket)
    if not api_key_text:
        return False, None
    result = await validate_apikey_route(api_key_text, _route_text_from_scope(scope), record_access=True)
    return bool(result.ok), result


def _auth_failure_detail(result: APIKeyValidationResult | None) -> str:
    if result is None:
        return "Admin API key required."
    return result.detail or result.reason


def _auth_failure_status(result: APIKeyValidationResult | None) -> int:
    if result is None:
        return 401
    if result.reason == "not_found":
        return 401
    if result.reason in {"banned", "route_not_allowed"}:
        return 403
    if result.reason == "insufficient_credit":
        return 402
    if result.reason in {"minimum_interval", "rate_limited"}:
        return 429
    return 401


class _AdminPanelAuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        path = str(scope.get("path") or "")
        server_cfg = Config.GetConfig().server_config
        admin_path = server_cfg.get_internal_admin_path()
        openapi_path = server_cfg.get_internal_admin_path("openapi.json")

        if scope_type == "lifespan":
            await self.app(scope, receive, send)
            return

        if path.startswith(admin_path) and not path.startswith(openapi_path) and not _admin_ip_allowed(scope):
            if scope_type == "websocket":
                await send({"type": "websocket.close", "code": 4403, "reason": "Admin access denied from this IP."})
                return
            response = JSONResponse({"detail": "Admin access denied from this IP."}, status_code=403)
            await response(scope, receive, send)
            return

        if scope_type == "http" and _is_http_login_flow_path(path):
            await self.app(scope, receive, send)
            return

        if scope_type == "websocket" and _is_websocket_login_flow_path(path):
            await self.app(scope, receive, send)
            return

        if scope_type == "http" and not path.startswith(admin_path):
            await self.app(scope, receive, send)
            return

        if scope_type == "websocket" and not path.startswith(admin_path):
            await self.app(scope, receive, send)
            return

        if scope_type == "http":
            ok, result = await _validate_admin_or_apikey_http(scope, receive)
            if ok:
                await self.app(scope, receive, send)
                return
            if _is_html_navigation(scope):
                redirect = RedirectResponse(url=f"{admin_path}/login?next={quote(_normalize_next_path(path), safe='')}", status_code=307)
                await redirect(scope, receive, send)
                return
            response = JSONResponse({"detail": _auth_failure_detail(result)}, status_code=_auth_failure_status(result))
            await response(scope, receive, send)
            return

        if scope_type == "websocket":
            ok, result = await _validate_admin_or_apikey_websocket(scope)
            if ok:
                await self.app(scope, receive, send)
                return
            await send({"type": "websocket.close", "code": 4401, "reason": _auth_failure_detail(result)})
            return

        await self.app(scope, receive, send)


def install_admin_panel_auth(app: FastAPI) -> None:
    if getattr(app.state, "_admin_panel_auth_installed", False):
        return
    app.add_middleware(_AdminPanelAuthMiddleware)
    app.state._admin_panel_auth_installed = True


@on_app_created
def _install_admin_panel_auth_on_app_created(app: FastAPI):
    if not Config.GetConfig().server_config.is_internal_exposed():
        return
    install_admin_panel_auth(app)


@on_before_app_created
def register_admin_auth_routes(app: FastAPI):
    if not Config.GetConfig().server_config.is_internal_exposed():
        return
    login_path = get_resources("admin-panel", "panel_login.html") or Path("panel_login.html")

    @app.get("/admin/login", response_class=HTMLResponse)
    async def panel_login_page(request: Request, next: str | None = None):
        redirect_to = _normalize_next_path(next)
        api_key, result = await _resolve_authenticated_apikey(_extract_admin_apikey_from_request(request))
        if api_key is not None and result is not None and result.ok:
            return RedirectResponse(url=redirect_to, status_code=307)
        response = html_response_from_path(login_path, not_found_message="panel_login.html not found")
        return HTMLResponse(
            response.body.decode("utf-8").replace("__ADMIN_NEXT_PATH__", json.dumps(redirect_to)),
            status_code=response.status_code,
            media_type=response.media_type,
        )

    @app.get("/admin/session", response_model=AdminSessionResponse)
    async def admin_session_status(request: Request) -> AdminSessionResponse:
        api_key, result = await _resolve_authenticated_apikey(_extract_admin_apikey_from_request(request))
        if api_key is None or result is None or not result.ok:
            return AdminSessionResponse(authenticated=False)
        ttl_seconds = await get_apikey_expire_seconds(api_key)
        expires_at = None if ttl_seconds is None else (time.time() + float(ttl_seconds))
        return AdminSessionResponse(authenticated=True, expires_at=expires_at)

    @app.post("/admin/login", response_model=AdminLoginResponse)
    async def admin_login(body: AdminLoginRequest, response: Response) -> AdminLoginResponse:
        if not has_admin_password():
            raise HTTPException(503, "Admin password is not initialized.")
        if not verify_admin_password(body.password):
            raise HTTPException(401, "Invalid admin password.")
        api_key, expires_at = await _issue_admin_login_apikey()
        redirect_to = _normalize_next_path(body.next_path)
        response.set_cookie(
            key=ADMIN_APIKEY_COOKIE_NAME,
            value=api_key.key,
            max_age=ADMIN_APIKEY_TTL_SECONDS,
            expires=ADMIN_APIKEY_TTL_SECONDS,
            path="/",
            secure=False,
            httponly=False,
            samesite="lax",
        )
        return AdminLoginResponse(
            authenticated=True,
            api_key=api_key.key,
            expires_at=expires_at,
            redirect_to=redirect_to,
        )

    @app.post("/admin/logout")
    async def admin_logout(request: Request, response: Response) -> dict[str, bool]:
        await _revoke_admin_login_apikey(_extract_admin_apikey_from_request(request))
        response.delete_cookie(ADMIN_APIKEY_COOKIE_NAME, path="/")
        return {"ok": True}

    # Re-order routes so that /admin/login, /admin/session, /admin/logout
    # are matched before any Mount (including the catch-all Mount("") for
    # public static files and Mount("/admin") for admin-panel static files).
    from starlette.routing import Mount, Route
    server_cfg = Config.GetConfig().server_config
    admin_auth_paths = {
        server_cfg.get_internal_admin_path("login"),
        server_cfg.get_internal_admin_path("session"),
        server_cfg.get_internal_admin_path("logout"),
    }
    admin_auth_routes: list[Route] = []
    for i in range(len(app.routes) - 1, -1, -1):
        route = app.routes[i]
        if isinstance(route, Route) and route.path in admin_auth_paths:
            admin_auth_routes.append(app.routes.pop(i))
    # Insert before the first Mount so Routes are checked first.
    inserted = False
    for idx, route in enumerate(app.routes):
        if isinstance(route, Mount):
            for r in reversed(admin_auth_routes):
                app.routes.insert(idx, r)
            inserted = True
            break
    if not inserted:
        # No Mounts present (e.g. in unit tests) — append back to the end.
        for r in reversed(admin_auth_routes):
            app.routes.append(r)
