import asyncio
import json
import os
import platform
import re
import shutil
import socket
import subprocess
from html import escape
from pathlib import Path
from typing import ClassVar, Literal

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.server.plugin import get_plugin_key
from core.utils.type_utils import AdvancedBaseModel

from .shared import ClashSharedData


PLUGIN_SHARED_ID = "clash"
PLUGIN_DIR = Path(__file__).resolve().parent
_DEFAULT_PROJECT_DIR = PLUGIN_DIR / "clash-for-linux"
_DEFAULT_BOOTSTRAP_SUBSCRIPTION = "plugin-bootstrap.yaml"
_DEFAULT_CLASH_REPO = "https://ghfast.top/https://github.com/wnlen/clash-for-linux.git"
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "content-encoding",
}
_PERMISSION_RE = re.compile(
    r"permission denied|must be root|superuser|access denied|operation not permitted",
    re.IGNORECASE,
)
_BAD_SUDO_RE = re.compile(
    r"incorrect password|try again|no password was provided|a password is required|authentication failure",
    re.IGNORECASE,
)
_HTML_ATTR_RE = re.compile(r'(?P<attr>(?:src|href|action)=([\"\']))/(?P<path>[^\"\']*)', re.IGNORECASE)
_CSS_URL_RE = re.compile(r'url\((?P<quote>[\"\']?)/(?P<path>[^)\"\']*)(?P=quote)\)')


def _normalize_internal_suffix(path: str, fallback: str) -> str:
    text = str(path or "").strip().strip("/")
    return text or fallback


def _normalize_url_path(path: str, fallback: str) -> str:
    text = str(path or "").strip()
    if not text:
        return fallback
    return "/" + text.strip("/")


def _is_linux() -> bool:
    return platform.system().lower() == "linux"


def _supports_sudo() -> bool:
    return _is_linux() and shutil.which("sudo") is not None


def _is_root_user() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return bool(callable(geteuid) and geteuid() == 0)


def _looks_like_permission_error(text: str) -> bool:
    return bool(_PERMISSION_RE.search(text or ""))


def _looks_like_bad_sudo_password(text: str) -> bool:
    return bool(_BAD_SUDO_RE.search(text or ""))


def _shell_single_quote(text: str) -> str:
    return "'" + str(text).replace("'", "'\"'\"'") + "'"


def _project_dir(config: "ClashPluginConfig") -> Path:
    return Path(config.project_dir).expanduser().resolve()


def _bootstrap_subscription_path(config: "ClashPluginConfig") -> Path:
    return _project_dir(config) / "runtime" / "subscriptions" / _DEFAULT_BOOTSTRAP_SUBSCRIPTION


def _controller_base_url(config: "ClashPluginConfig") -> str:
    return f"{config.controller_scheme}://{config.controller_host}:{int(config.controller_port)}"


def _controller_headers(config: "ClashPluginConfig") -> dict[str, str]:
    headers: dict[str, str] = {}
    if str(config.controller_secret or "").strip():
        headers["Authorization"] = f"Bearer {config.controller_secret}"
    return headers


def _rewrite_html(html: str, proxy_prefix: str) -> str:
    prefix = proxy_prefix.rstrip("/")
    rewritten = _HTML_ATTR_RE.sub(lambda match: f'{match.group("attr")}{prefix}/{match.group("path")}', html)
    rewritten = _CSS_URL_RE.sub(lambda match: f'url({match.group("quote")}{prefix}/{match.group("path")}{match.group("quote")})', rewritten)
    runtime = (
        "<script>(function(){"
        f"const PREFIX={json.dumps(prefix)};"
        "function mapUrl(url){ if(typeof url!==\"string\") return url; if(!url) return url; if(url.startsWith(PREFIX)) return url; if(/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url)||url.startsWith('//')) return url; if(url.startsWith('/')) return PREFIX+url; return url; }"
        "document.querySelectorAll('[src],[href],[action]').forEach(function(node){ ['src','href','action'].forEach(function(attr){ var value=node.getAttribute(attr); if(value&&value.startsWith('/')) node.setAttribute(attr, mapUrl(value)); }); });"
        "if(window.fetch){ const rawFetch=window.fetch.bind(window); window.fetch=function(input, init){ if(typeof input==='string'){ return rawFetch(mapUrl(input), init); } return rawFetch(input, init); }; }"
        "if(window.XMLHttpRequest&&window.XMLHttpRequest.prototype){ const rawOpen=window.XMLHttpRequest.prototype.open; window.XMLHttpRequest.prototype.open=function(method, url){ arguments[1]=mapUrl(String(url)); return rawOpen.apply(this, arguments); }; }"
        "if(window.WebSocket){ const RawWebSocket=window.WebSocket; window.WebSocket=function(url, protocols){ var next=String(url||''); if(next.startsWith('/')){ var proto=window.location.protocol==='https:'?'wss://':'ws://'; next=proto+window.location.host+mapUrl(next); } return new RawWebSocket(next, protocols); }; window.WebSocket.prototype=RawWebSocket.prototype; }"
        "if(window.EventSource){ const RawEventSource=window.EventSource; window.EventSource=function(url, config){ return new RawEventSource(mapUrl(String(url||'')), config); }; window.EventSource.prototype=RawEventSource.prototype; }"
        "})();</script>"
    )
    if "</head>" in rewritten:
        return rewritten.replace("</head>", runtime + "</head>", 1)
    return runtime + rewritten


def _rewrite_location(location: str, proxy_prefix: str) -> str:
    if not location.startswith("/"):
        return location
    return proxy_prefix.rstrip("/") + location


class ClashPluginConfig(BaseModel):
    enabled: bool = True
    install_repo_url: str = _DEFAULT_CLASH_REPO
    project_dir: str = str(_DEFAULT_PROJECT_DIR)
    controller_scheme: Literal["http", "https"] = "http"
    controller_bind_host: str = "0.0.0.0"
    controller_host: str = "192.168.0.1"
    controller_port: int = 9090
    controller_ui_path: str = "/ui"
    controller_secret: str = "proj-clash-secret"
    mixed_port: int = 7890
    admin_status_path: str = "api/clash/status"
    admin_install_path: str = "api/clash/install"
    admin_sudo_password_path: str = "api/clash/sudo-password"
    admin_ui_proxy_path: str = "clash/ui"

    def model_post_init(self, __context) -> None:
        self.admin_status_path = _normalize_internal_suffix(self.admin_status_path, "api/clash/status")
        self.admin_install_path = _normalize_internal_suffix(self.admin_install_path, "api/clash/install")
        self.admin_sudo_password_path = _normalize_internal_suffix(self.admin_sudo_password_path, "api/clash/sudo-password")
        self.admin_ui_proxy_path = _normalize_internal_suffix(self.admin_ui_proxy_path, "clash/ui")
        self.controller_ui_path = _normalize_url_path(self.controller_ui_path, "/ui")
        self.project_dir = str(Path(self.project_dir).expanduser())


class ClashStatusResponse(AdvancedBaseModel):
    plugin_key: str
    enabled: bool
    host_platform: str
    clash_project_present: bool
    clashctl_available: bool
    controller_accessible: bool
    install_supported: bool
    requires_sudo: bool = False
    sudo_cached: bool = False
    controller_url: str | None = None
    controller_ui_url: str | None = None
    controller_secret_configured: bool = False
    proxy_path: str | None = None
    message: str | None = None


class ClashActionResponse(AdvancedBaseModel):
    ok: bool
    requires_sudo: bool = False
    invalid_password: bool = False
    sudo_cached: bool = False
    message: str | None = None
    status: ClashStatusResponse | None = None


class ClashPasswordRequest(AdvancedBaseModel):
    password: str


class _NeedSudoPasswordError(RuntimeError):
    def __init__(self, message: str, *, invalid_password: bool = False):
        super().__init__(message)
        self.invalid_password = bool(invalid_password)


class _CommandExecutionError(RuntimeError):
    def __init__(self, message: str, *, stderr: str = "", stdout: str = ""):
        super().__init__(message)
        self.stderr = stderr
        self.stdout = stdout


def _run_subprocess(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    sudo_password: str | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    resolved_args = list(args)
    input_text: str | None = None
    if sudo_password is not None:
        resolved_args = ["sudo", "-S", "-p", ""] + resolved_args
        input_text = str(sudo_password) + "\n"
    return subprocess.run(
        resolved_args,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        input=input_text,
        check=False,
    )


def _run_command_with_sudo_retry(
    shared: ClashSharedData,
    args: list[str],
    *,
    cwd: str | Path | None = None,
    require_root: bool = False,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    cached_password = shared.get_sudo_password()
    if require_root and not _is_root_user():
        if not _supports_sudo():
            raise _CommandExecutionError("This host does not support sudo for privileged actions.")
        if not cached_password:
            raise _NeedSudoPasswordError("This action requires sudo privileges.")
        result = _run_subprocess(args, cwd=cwd, sudo_password=cached_password, timeout=timeout)
        merged = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode == 0:
            return result
        if _looks_like_bad_sudo_password(merged):
            shared.clear_sudo_password()
            raise _NeedSudoPasswordError("Cached sudo password is invalid.", invalid_password=True)
        raise _CommandExecutionError("Privileged command failed.", stderr=result.stderr or "", stdout=result.stdout or "")

    result = _run_subprocess(args, cwd=cwd, timeout=timeout)
    merged = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode == 0:
        return result
    if _looks_like_permission_error(merged):
        if not _supports_sudo():
            raise _CommandExecutionError("Command access was denied and sudo is unavailable.", stderr=result.stderr or "", stdout=result.stdout or "")
        if not cached_password:
            raise _NeedSudoPasswordError("This action requires sudo privileges.")
        retry = _run_subprocess(args, cwd=cwd, sudo_password=cached_password, timeout=timeout)
        retry_merged = (retry.stdout or "") + "\n" + (retry.stderr or "")
        if retry.returncode == 0:
            return retry
        if _looks_like_bad_sudo_password(retry_merged):
            shared.clear_sudo_password()
            raise _NeedSudoPasswordError("Cached sudo password is invalid.", invalid_password=True)
        raise _CommandExecutionError("Command failed after sudo retry.", stderr=retry.stderr or "", stdout=retry.stdout or "")
    raise _CommandExecutionError("Command failed.", stderr=result.stderr or "", stdout=result.stdout or "")


def _verify_sudo_password(shared: ClashSharedData, password: str) -> None:
    if _is_root_user() or not _supports_sudo():
        shared.clear_sudo_password()
        return
    result = _run_subprocess(["-v"], sudo_password=password, timeout=20.0)
    merged = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0:
        shared.clear_sudo_password()
        raise _NeedSudoPasswordError("sudo password verification failed.", invalid_password=_looks_like_bad_sudo_password(merged))
    shared.set_sudo_password(password)


def _build_bootstrap_subscription_yaml(config: ClashPluginConfig) -> str:
    direct_group = "DIRECT"
    return (
        f"mixed-port: {int(config.mixed_port)}\n"
        "mode: rule\n"
        "allow-lan: true\n"
        "log-level: info\n"
        "proxies: []\n"
        "proxy-groups:\n"
        f"  - name: {direct_group}\n"
        "    type: select\n"
        f"    proxies: [{direct_group}]\n"
        "rules:\n"
        f"  - MATCH,{direct_group}\n"
    )


def _write_install_env(config: ClashPluginConfig) -> None:
    project_dir = _project_dir(config)
    subscription_path = _bootstrap_subscription_path(config)
    subscription_path.parent.mkdir(parents=True, exist_ok=True)
    subscription_path.write_text(_build_bootstrap_subscription_yaml(config), encoding="utf-8")
    env_lines = [
        f"EXTERNAL_CONTROLLER={_shell_single_quote(f'{config.controller_bind_host}:{int(config.controller_port)}')}",
        f"CLASH_CONTROLLER_SECRET={_shell_single_quote(str(config.controller_secret))}",
        f"MIXED_PORT={int(config.mixed_port)}",
        "ALLOW_LAN=true",
        f"CLASH_SUBSCRIPTION_URL={_shell_single_quote(subscription_path.as_uri())}",
    ]
    (project_dir / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")


def _probe_controller(config: ClashPluginConfig) -> tuple[bool, str | None]:
    try:
        with httpx.Client(trust_env=False, follow_redirects=True, timeout=5.0) as client:
            response = client.get(_controller_base_url(config) + "/version", headers=_controller_headers(config))
    except Exception as exc:
        return False, str(exc)
    if response.status_code == 200:
        return True, None
    if response.status_code in {401, 403}:
        return False, "Clash controller rejected the configured secret."
    return False, f"Unexpected controller response: {response.status_code}"


def _clone_project_if_missing(shared: ClashSharedData, config: ClashPluginConfig) -> None:
    project_dir = _project_dir(config)
    if (project_dir / "install.sh").is_file():
        return
    if project_dir.exists():
        raise _CommandExecutionError(f"Existing project directory is incomplete: {project_dir}")
    git_binary = shutil.which("git")
    if git_binary is None:
        raise _CommandExecutionError("git is required to install clash-for-linux.")
    project_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_command_with_sudo_retry(
        shared,
        [git_binary, "clone", "--branch", "master", "--depth", "1", config.install_repo_url, project_dir.name],
        cwd=project_dir.parent,
        timeout=600.0,
    )


def _install_clash_project(shared: ClashSharedData, config: ClashPluginConfig) -> None:
    if not _is_linux():
        raise _CommandExecutionError("Clash plugin installation is only supported on Linux hosts.")
    _clone_project_if_missing(shared, config)
    project_dir = _project_dir(config)
    _write_install_env(config)
    bash_binary = shutil.which("bash") or "bash"
    _run_command_with_sudo_retry(
        shared,
        [bash_binary, "install.sh"],
        cwd=project_dir,
        require_root=not _is_root_user(),
        timeout=1800.0,
    )


class ClashPlugin:
    Key: ClassVar[str] = PLUGIN_SHARED_ID
    Name: ClassVar[dict[str, str]] = {
        "zh-cn": "Clash",
        "zh-tw": "Clash",
        "en": "Clash",
    }
    Type: ClassVar[Literal["worker-only"]] = "worker-only"
    SupportedPlatform: ClassVar[Literal["linux"]] = "linux"
    Description: ClassVar[dict[str, str]] = {
        "zh-cn": "通过 clash-for-linux 安装并代理 Clash Web 控制台。",
        "zh-tw": "透過 clash-for-linux 安裝並代理 Clash Web 控制台。",
        "en": "Install clash-for-linux and proxy the Clash web console.",
    }
    ConfigType: ClassVar[type[BaseModel]] = ClashPluginConfig

    def __init__(self, config: ClashPluginConfig):
        self.config = config
        self.shared = ClashSharedData(PLUGIN_SHARED_ID)

    @classmethod
    def Create(cls, create_in: str, config=None, core_module=None):
        resolved_config = config if isinstance(config, ClashPluginConfig) else ClashPluginConfig.model_validate(config or {})
        return cls(resolved_config)

    def _admin_path(self, suffix: str) -> str:
        from core.server.data_types.config import Config

        return Config.GetConfig().server_config.get_internal_admin_path(suffix)

    def _proxy_root_path(self) -> str:
        return self._admin_path(self.config.admin_ui_proxy_path)

    def _status_response(
        self,
        *,
        clash_project_present: bool,
        clashctl_available: bool,
        controller_accessible: bool,
        install_supported: bool,
        requires_sudo: bool = False,
        message: str | None = None,
    ) -> ClashStatusResponse:
        controller_url = _controller_base_url(self.config)
        controller_ui_url = controller_url + self.config.controller_ui_path
        return ClashStatusResponse(
            plugin_key=get_plugin_key(self.__class__),
            enabled=self.config.enabled,
            host_platform=platform.system(),
            clash_project_present=clash_project_present,
            clashctl_available=clashctl_available,
            controller_accessible=controller_accessible,
            install_supported=install_supported,
            requires_sudo=requires_sudo,
            sudo_cached=self.shared.has_sudo_password(),
            controller_url=controller_url,
            controller_ui_url=controller_ui_url,
            controller_secret_configured=bool(str(self.config.controller_secret or "").strip()),
            proxy_path=self._proxy_root_path() if controller_accessible else None,
            message=message,
        )

    def _collect_status(self) -> ClashStatusResponse:
        if not self.config.enabled:
            return self._status_response(
                clash_project_present=False,
                clashctl_available=False,
                controller_accessible=False,
                install_supported=False,
                message="Clash plugin is disabled.",
            )

        project_dir = _project_dir(self.config)
        clash_project_present = (project_dir / "install.sh").is_file()
        clashctl_available = shutil.which("clashctl") is not None
        controller_accessible, controller_message = _probe_controller(self.config)
        install_supported = _is_linux() and shutil.which("git") is not None and (shutil.which("bash") is not None or Path("/bin/bash").exists())

        if controller_accessible:
            return self._status_response(
                clash_project_present=clash_project_present,
                clashctl_available=clashctl_available,
                controller_accessible=True,
                install_supported=install_supported,
                message="Clash controller is reachable.",
            )

        if not clash_project_present and not clashctl_available:
            return self._status_response(
                clash_project_present=False,
                clashctl_available=False,
                controller_accessible=False,
                install_supported=install_supported,
                message="clash-for-linux is not installed yet.",
            )

        return self._status_response(
            clash_project_present=clash_project_present,
            clashctl_available=clashctl_available,
            controller_accessible=False,
            install_supported=install_supported,
            message=controller_message or "Clash controller is not reachable yet.",
        )

    def _install(self) -> ClashStatusResponse:
        _install_clash_project(self.shared, self.config)
        return self._collect_status()

    def _proxy_target_url(self, path: str) -> str:
        clean_path = str(path or "").lstrip("/")
        if not clean_path:
            return _controller_base_url(self.config) + self.config.controller_ui_path.rstrip("/") + "/"
        return _controller_base_url(self.config) + "/" + clean_path

    async def _proxy_ui(self, request: Request, path: str) -> Response:
        status = await asyncio.to_thread(self._collect_status)
        if not status.controller_accessible:
            return Response(status_code=503, content=(status.message or "Clash controller is not reachable.").encode("utf-8"), media_type="text/plain")

        proxy_prefix = self._proxy_root_path()
        target_url = self._proxy_target_url(path)
        request_headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _HOP_BY_HOP_HEADERS
        }
        request_headers["host"] = f"{self.config.controller_host}:{int(self.config.controller_port)}"
        request_headers.update(_controller_headers(self.config))
        body = await request.body()

        async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=60.0) as client:
            response = await client.request(
                request.method,
                target_url,
                headers=request_headers,
                content=body,
                params=request.query_params,
            )

        response_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in _HOP_BY_HOP_HEADERS
        }
        if (location := response_headers.get("location")) is not None:
            response_headers["location"] = _rewrite_location(location, proxy_prefix)

        content_type = str(response.headers.get("content-type", ""))
        response_body = bytes(response.content)
        if "text/html" in content_type:
            response_body = _rewrite_html(response.text, proxy_prefix).encode("utf-8")
            response_headers["content-type"] = "text/html; charset=utf-8"
        elif "text/css" in content_type:
            css_text = _CSS_URL_RE.sub(
                lambda match: f'url({match.group("quote")}{proxy_prefix.rstrip("/")}/{match.group("path")}{match.group("quote")})',
                response.text,
            )
            response_body = css_text.encode("utf-8")
            response_headers["content-type"] = "text/css; charset=utf-8"

        return Response(content=response_body, status_code=response.status_code, headers=response_headers)

    def _register_routes(self, app: FastAPI) -> None:
        if getattr(app.state, "_clash_plugin_routes_registered", False):
            return
        app.state._clash_plugin_routes_registered = True

        status_path = self._admin_path(self.config.admin_status_path)
        install_path = self._admin_path(self.config.admin_install_path)
        sudo_password_path = self._admin_path(self.config.admin_sudo_password_path)
        ui_proxy_root = self._proxy_root_path().rstrip("/")

        @app.get(status_path, response_model=ClashStatusResponse)
        async def clash_status() -> ClashStatusResponse:
            return await asyncio.to_thread(self._collect_status)

        @app.post(sudo_password_path, response_model=ClashActionResponse)
        async def clash_save_sudo_password(payload: ClashPasswordRequest) -> ClashActionResponse:
            try:
                await asyncio.to_thread(_verify_sudo_password, self.shared, payload.password)
            except _NeedSudoPasswordError as exc:
                return ClashActionResponse(
                    ok=False,
                    invalid_password=exc.invalid_password,
                    sudo_cached=self.shared.has_sudo_password(),
                    message=str(exc),
                    status=await asyncio.to_thread(self._collect_status),
                )
            return ClashActionResponse(
                ok=True,
                sudo_cached=self.shared.has_sudo_password(),
                message="sudo password cached in memory.",
                status=await asyncio.to_thread(self._collect_status),
            )

        @app.delete(sudo_password_path, response_model=ClashActionResponse)
        async def clash_clear_sudo_password() -> ClashActionResponse:
            self.shared.clear_sudo_password()
            return ClashActionResponse(
                ok=True,
                sudo_cached=False,
                message="Cached sudo password cleared.",
                status=await asyncio.to_thread(self._collect_status),
            )

        @app.post(install_path, response_model=ClashActionResponse)
        async def clash_install() -> ClashActionResponse:
            try:
                status = await asyncio.to_thread(self._install)
                return ClashActionResponse(ok=True, sudo_cached=self.shared.has_sudo_password(), message="clash-for-linux installation finished.", status=status)
            except _NeedSudoPasswordError as exc:
                return ClashActionResponse(ok=False, requires_sudo=True, invalid_password=exc.invalid_password, sudo_cached=self.shared.has_sudo_password(), message=str(exc), status=await asyncio.to_thread(self._collect_status))
            except Exception as exc:
                return ClashActionResponse(ok=False, sudo_cached=self.shared.has_sudo_password(), message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.api_route(ui_proxy_root, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
        async def clash_proxy_root(request: Request) -> Response:
            return await self._proxy_ui(request, "")

        @app.api_route(ui_proxy_root + "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
        async def clash_proxy_path(path: str, request: Request) -> Response:
            return await self._proxy_ui(request, path)

    async def on_app_start(self, app: FastAPI) -> None:
        self._register_routes(app)

    async def admin_panel(self) -> str:
        status_path = escape(self._admin_path(self.config.admin_status_path), quote=True)
        install_path = escape(self._admin_path(self.config.admin_install_path), quote=True)
        sudo_password_path = escape(self._admin_path(self.config.admin_sudo_password_path), quote=True)
        proxy_root = escape(self._proxy_root_path(), quote=True)
        controller_ui_url = escape(_controller_base_url(self.config) + self.config.controller_ui_path, quote=True)
        plugin_key = escape(get_plugin_key(self.__class__), quote=True)
        return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Clash</title>
  <style>
    :root {{ color-scheme: light dark; }}
    html, body {{ margin: 0; min-height: 100%; font-family: \"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", sans-serif; }}
    body {{ background: #eef3f8; color: #102033; }}
    .clash-shell {{ min-height: 100vh; display: grid; grid-template-columns: minmax(0, 360px) minmax(0, 1fr); }}
    .clash-sidebar {{ padding: 22px 18px; background: linear-gradient(180deg, rgba(15,23,42,0.98), rgba(30,41,59,0.96)); color: #e2e8f0; box-sizing: border-box; }}
    .clash-kicker {{ font-size: 11px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; color: #94a3b8; }}
    .clash-title {{ margin-top: 10px; font-size: 28px; font-weight: 800; }}
    .clash-copy {{ margin-top: 12px; font-size: 13px; line-height: 1.7; color: #cbd5e1; }}
    .clash-meta {{ margin-top: 18px; display: grid; gap: 10px; }}
    .clash-meta-item {{ border-radius: 14px; padding: 12px 14px; background: rgba(148,163,184,0.12); }}
    .clash-meta-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; color: #94a3b8; }}
    .clash-meta-value {{ margin-top: 6px; font-size: 13px; word-break: break-all; }}
    .clash-actions {{ margin-top: 18px; display: flex; gap: 10px; flex-wrap: wrap; }}
    .clash-actions button {{ border: 0; border-radius: 14px; padding: 12px 14px; font-size: 13px; font-weight: 700; cursor: pointer; }}
    .clash-install {{ background: linear-gradient(135deg, #22c55e, #14b8a6); color: #04130d; }}
    .clash-refresh {{ background: rgba(226,232,240,0.18); color: #e2e8f0; }}
    .clash-main {{ min-width: 0; display: flex; flex-direction: column; background: radial-gradient(circle at top right, rgba(16,185,129,0.15), transparent 28%), #f8fafc; }}
    .clash-toolbar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 18px 22px; border-bottom: 1px solid rgba(148,163,184,0.22); background: rgba(255,255,255,0.74); backdrop-filter: blur(16px); }}
    .clash-toolbar h1 {{ margin: 0; font-size: 18px; font-weight: 700; color: #0f172a; }}
    .clash-toolbar span {{ font-size: 12px; color: #64748b; }}
    .clash-state {{ padding: 18px 22px; font-size: 13px; line-height: 1.7; color: #334155; }}
    .clash-state strong {{ color: #0f172a; }}
    .clash-frame-wrap {{ flex: 1; min-height: 0; padding: 0 18px 18px; box-sizing: border-box; }}
    .clash-frame {{ width: 100%; height: 100%; min-height: 65vh; border: 0; border-radius: 18px; background: #fff; box-shadow: 0 18px 48px rgba(15,23,42,0.08); }}
    .clash-password-dialog {{ position: fixed; inset: 0; display: none; align-items: center; justify-content: center; background: rgba(2,6,23,0.46); padding: 20px; box-sizing: border-box; }}
    .clash-password-card {{ width: min(420px, 100%); border-radius: 18px; padding: 22px; background: #fff; color: #0f172a; box-shadow: 0 24px 64px rgba(15,23,42,0.24); }}
    .clash-password-card h2 {{ margin: 0; font-size: 18px; }}
    .clash-password-card p {{ margin: 10px 0 0; color: #475569; font-size: 13px; line-height: 1.7; }}
    .clash-password-card input {{ width: 100%; margin-top: 16px; border-radius: 12px; border: 1px solid rgba(148,163,184,0.42); padding: 12px 14px; box-sizing: border-box; font: inherit; }}
    .clash-password-card .row {{ margin-top: 14px; display: flex; gap: 10px; justify-content: flex-end; }}
    .clash-password-card button {{ border: 0; border-radius: 12px; padding: 10px 14px; font: inherit; cursor: pointer; }}
    .clash-password-card .cancel {{ background: #e2e8f0; color: #0f172a; }}
    .clash-password-card .save {{ background: #0f172a; color: #f8fafc; }}
    .hidden {{ display: none !important; }}
  </style>
</head>
<body>
  <div class=\"clash-shell\" data-plugin-key=\"{plugin_key}\" id=\"clash-plugin-shell\">
    <aside class=\"clash-sidebar\">
      <div class=\"clash-kicker\">Plugin</div>
      <div class=\"clash-title\">Clash</div>
      <div class=\"clash-copy\">基于 clash-for-linux 安装项目，并把 Clash Web 控制台通过插件面板反向代理到当前管理页。</div>
      <div class=\"clash-meta\">
        <div class=\"clash-meta-item\"><div class=\"clash-meta-label\">Controller</div><div class=\"clash-meta-value\" id=\"clash-controller-url\">{controller_ui_url}</div></div>
        <div class=\"clash-meta-item\"><div class=\"clash-meta-label\">Proxy Path</div><div class=\"clash-meta-value\">{proxy_root}</div></div>
      </div>
      <div class=\"clash-actions\">
        <button type=\"button\" class=\"clash-install\" id=\"clash-plugin-install\">安装 clash-for-linux</button>
        <button type=\"button\" class=\"clash-refresh\" id=\"clash-plugin-refresh\">刷新状态</button>
      </div>
    </aside>
    <section class=\"clash-main\">
      <div class=\"clash-toolbar\">
        <div>
          <h1>Clash 控制台</h1>
          <span id=\"clash-status-headline\">正在检测控制器状态…</span>
        </div>
      </div>
      <div class=\"clash-state\" id=\"clash-status-copy\">正在加载…</div>
      <div class=\"clash-frame-wrap\">
        <iframe id=\"clash-plugin-frame\" class=\"clash-frame\" src=\"about:blank\"></iframe>
      </div>
    </section>
  </div>
  <div class=\"clash-password-dialog\" id=\"clash-plugin-password-dialog\">
    <div class=\"clash-password-card\">
      <h2>需要 sudo 密码</h2>
      <p>当前安装动作需要提权。密码只会临时缓存在当前进程内存里。</p>
      <input id=\"clash-plugin-password-input\" type=\"password\" placeholder=\"输入 sudo 密码\" />
      <div class=\"row\">
        <button type=\"button\" class=\"cancel\" id=\"clash-plugin-password-cancel\">取消</button>
        <button type=\"button\" class=\"save\" id=\"clash-plugin-password-save\">保存并继续</button>
      </div>
    </div>
  </div>
  <script>
    (function() {{
      const statusUrl = {json.dumps(status_path)};
      const installUrl = {json.dumps(install_path)};
      const sudoPasswordUrl = {json.dumps(sudo_password_path)};
      const proxyRoot = {json.dumps(proxy_root)};
      const installButton = document.getElementById('clash-plugin-install');
      const refreshButton = document.getElementById('clash-plugin-refresh');
      const frame = document.getElementById('clash-plugin-frame');
      const statusHeadline = document.getElementById('clash-status-headline');
      const statusCopy = document.getElementById('clash-status-copy');
      const controllerUrl = document.getElementById('clash-controller-url');
      const dialog = document.getElementById('clash-plugin-password-dialog');
      const passwordInput = document.getElementById('clash-plugin-password-input');
      const cancelButton = document.getElementById('clash-plugin-password-cancel');
      const saveButton = document.getElementById('clash-plugin-password-save');
      let pendingInstall = false;

      async function requestJson(url, init) {{
        const response = await fetch(url, Object.assign({{ credentials: 'same-origin' }}, init || {{}}));
        const payload = await response.json().catch(function() {{ return null; }});
        if (!response.ok) {{
          throw new Error((payload && payload.message) || ('HTTP ' + response.status));
        }}
        return payload;
      }}

      function renderStatus(status) {{
        if (!status) return;
        controllerUrl.textContent = status.controller_ui_url || controllerUrl.textContent;
        const summary = [];
        summary.push(status.clash_project_present ? '项目目录已存在。' : '项目目录还不存在，点击安装会 clone clash-for-linux。');
        summary.push(status.controller_accessible ? '控制器已连通，下面 iframe 会直接打开 Web UI。' : (status.message || '控制器暂时不可达。'));
        if (status.controller_secret_configured) summary.push('已配置控制器密钥，代理请求会自动附带 Authorization 头。');
        statusHeadline.textContent = status.controller_accessible ? '控制器已就绪' : '控制器未就绪';
        statusCopy.innerHTML = '<strong>' + (status.message || '') + '</strong><br />' + summary.join('<br />');
        installButton.disabled = !status.install_supported;
        installButton.textContent = status.clash_project_present ? '重新安装 / 补装' : '安装 clash-for-linux';
        frame.src = status.controller_accessible ? (proxyRoot + '/') : 'about:blank';
      }}

      async function loadStatus() {{
        statusHeadline.textContent = '正在刷新状态…';
        const status = await requestJson(statusUrl);
        renderStatus(status);
        return status;
      }}

      function openPasswordDialog() {{
        dialog.style.display = 'flex';
        passwordInput.value = '';
        passwordInput.focus();
      }}

      function closePasswordDialog() {{
        dialog.style.display = 'none';
      }}

      async function savePasswordAndInstall() {{
        const password = String(passwordInput.value || '');
        await requestJson(sudoPasswordUrl, {{
          method: 'POST',
          headers: {{ 'content-type': 'application/json' }},
          body: JSON.stringify({{ password }}),
        }});
        closePasswordDialog();
        await runInstall(true);
      }}

      async function runInstall(skipSudoRetry) {{
        if (pendingInstall) return;
        pendingInstall = true;
        installButton.disabled = true;
        statusHeadline.textContent = '正在执行安装…';
        try {{
          const payload = await requestJson(installUrl, {{ method: 'POST' }});
          renderStatus(payload.status || null);
        }} catch (error) {{
          const message = String(error && error.message || error || '安装失败');
          if (!skipSudoRetry && /sudo/i.test(message)) {{
            openPasswordDialog();
          }} else {{
            statusHeadline.textContent = '安装失败';
            statusCopy.textContent = message;
          }}
        }} finally {{
          pendingInstall = false;
          installButton.disabled = false;
        }}
      }}

      installButton.addEventListener('click', function() {{ void runInstall(false); }});
      refreshButton.addEventListener('click', function() {{ void loadStatus(); }});
      cancelButton.addEventListener('click', closePasswordDialog);
      saveButton.addEventListener('click', function() {{ void savePasswordAndInstall(); }});
      passwordInput.addEventListener('keydown', function(event) {{ if (event.key === 'Enter') void savePasswordAndInstall(); }});
      void loadStatus();
    }})();
  </script>
</body>
</html>"""


__all__ = [
    "ClashActionResponse",
    "ClashPasswordRequest",
    "ClashPlugin",
    "ClashPluginConfig",
    "ClashStatusResponse",
]