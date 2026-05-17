import asyncio
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from html import escape
from pathlib import Path
from typing import ClassVar, Literal

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.constants import PROJECT_DIR
from core.server.plugin import get_plugin_key
from core.utils.type_utils import AdvancedBaseModel

from .shared import NginxManagerSharedData


PLUGIN_SHARED_ID = "nginx-manager"
PLUGIN_DIR = Path(__file__).resolve().parent
PLUGIN_STATE_DIR = PROJECT_DIR / "tmp" / "plugins" / "nginx-manager"
_NGINX_UI_IMAGE = "uozi/nginx-ui:latest"
_NGINX_UI_CONTAINER = "proj-plugin-nginx-manager-ui"
_NGINX_UI_CONFIG_DIR = PLUGIN_STATE_DIR / "nginx-ui-config"
_NGINX_UI_WWW_DIR = PLUGIN_STATE_DIR / "www"
_FREE_PORT_START = 38181
_FREE_PORT_END = 38280
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
    r"permission denied|got permission denied while trying to connect|must be root|superuser|access denied",
    re.IGNORECASE,
)
_BAD_SUDO_RE = re.compile(
    r"incorrect password|try again|no password was provided|a password is required|authentication failure",
    re.IGNORECASE,
)
_NO_OBJECT_RE = re.compile(r"no such object|no such container", re.IGNORECASE)
_HTML_ATTR_RE = re.compile(r'(?P<attr>(?:src|href|action)=([\"\']))/(?P<path>[^\"\']*)', re.IGNORECASE)
_CSS_URL_RE = re.compile(r'url\((?P<quote>[\"\']?)/(?P<path>[^)\"\']*)(?P=quote)\)')
_NGINX_CONF_PATH_RE = re.compile(r"--conf-path=(?P<path>[^\s]+)")


def _normalize_internal_suffix(path: str, fallback: str) -> str:
    text = str(path or "").strip().strip("/")
    return text or fallback


def _is_linux() -> bool:
    return platform.system().lower() == "linux"


def _supports_sudo() -> bool:
    return _is_linux() and shutil.which("sudo") is not None


def _is_root_user() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return bool(callable(geteuid) and geteuid() == 0)


def _get_docker_binary() -> str | None:
    return shutil.which("docker")


def _get_nginx_binary() -> str | None:
    return shutil.which("nginx")


def _port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", int(port)))
        except OSError:
            return False
    return True


def _choose_available_port(preferred: int | None, shared_port: int | None, fallback_start: int) -> int:
    for candidate in (preferred, shared_port):
        if candidate is not None and _port_is_available(int(candidate)):
            return int(candidate)
    for candidate in range(fallback_start, _FREE_PORT_END + 1):
        if _port_is_available(candidate):
            return candidate
    raise RuntimeError("No free high port available for nginx-ui.")


def _looks_like_permission_error(text: str) -> bool:
    return bool(_PERMISSION_RE.search(text or ""))


def _looks_like_bad_sudo_password(text: str) -> bool:
    return bool(_BAD_SUDO_RE.search(text or ""))


class NginxManagerPluginConfig(BaseModel):
    enabled: bool = True
    nginx_ui_image: str = _NGINX_UI_IMAGE
    nginx_ui_container_name: str = _NGINX_UI_CONTAINER
    nginx_ui_http_port: int | None = None
    nginx_ui_https_port: int | None = None
    nginx_ui_config_dir: str = str(_NGINX_UI_CONFIG_DIR)
    nginx_ui_www_dir: str = str(_NGINX_UI_WWW_DIR)
    admin_status_path: str = "api/nginx-manager/status"
    admin_install_path: str = "api/nginx-manager/install"
    admin_sudo_password_path: str = "api/nginx-manager/sudo-password"
    admin_ui_start_path: str = "api/nginx-manager/ui/start"
    admin_ui_stop_path: str = "api/nginx-manager/ui/stop"
    admin_ui_proxy_path: str = "nginx-manager/ui"

    def model_post_init(self, __context) -> None:
        self.admin_status_path = _normalize_internal_suffix(self.admin_status_path, "api/nginx-manager/status")
        self.admin_install_path = _normalize_internal_suffix(self.admin_install_path, "api/nginx-manager/install")
        self.admin_sudo_password_path = _normalize_internal_suffix(self.admin_sudo_password_path, "api/nginx-manager/sudo-password")
        self.admin_ui_start_path = _normalize_internal_suffix(self.admin_ui_start_path, "api/nginx-manager/ui/start")
        self.admin_ui_stop_path = _normalize_internal_suffix(self.admin_ui_stop_path, "api/nginx-manager/ui/stop")
        self.admin_ui_proxy_path = _normalize_internal_suffix(self.admin_ui_proxy_path, "nginx-manager/ui")


class NginxManagerStatusResponse(AdvancedBaseModel):
    plugin_key: str
    enabled: bool
    host_platform: str
    nginx_installed: bool
    docker_installed: bool
    docker_accessible: bool
    install_supported: bool
    requires_sudo: bool = False
    sudo_cached: bool = False
    missing_dependencies: list[str] = []
    nginx_ui_container_exists: bool = False
    nginx_ui_running: bool = False
    nginx_ui_http_port: int | None = None
    nginx_ui_https_port: int | None = None
    nginx_ui_proxy_path: str | None = None
    message: str | None = None


class NginxManagerActionResponse(AdvancedBaseModel):
    ok: bool
    requires_sudo: bool = False
    invalid_password: bool = False
    sudo_cached: bool = False
    message: str | None = None
    status: NginxManagerStatusResponse | None = None


class NginxManagerPasswordRequest(AdvancedBaseModel):
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
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        input=input_text,
        check=False,
    )


def _verify_sudo_password(shared: NginxManagerSharedData, password: str) -> None:
    if _is_root_user() or not _supports_sudo():
        shared.clear_sudo_password()
        return
    result = _run_subprocess(["-v"], sudo_password=password, timeout=20.0)
    merged = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0:
        shared.clear_sudo_password()
        raise _NeedSudoPasswordError("sudo password verification failed.", invalid_password=_looks_like_bad_sudo_password(merged))
    shared.set_sudo_password(password)


def _run_command_with_sudo_retry(
    shared: NginxManagerSharedData,
    args: list[str],
    *,
    require_root: bool = False,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    cached_password = shared.get_sudo_password()
    if require_root and not _is_root_user():
        if not _supports_sudo():
            raise _CommandExecutionError("This host does not support sudo for privileged actions.")
        if not cached_password:
            raise _NeedSudoPasswordError("This action requires sudo privileges.")
        result = _run_subprocess(args, sudo_password=cached_password, timeout=timeout)
        merged = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode == 0:
            return result
        if _looks_like_bad_sudo_password(merged):
            shared.clear_sudo_password()
            raise _NeedSudoPasswordError("Cached sudo password is invalid.", invalid_password=True)
        raise _CommandExecutionError("Privileged command failed.", stderr=result.stderr or "", stdout=result.stdout or "")

    result = _run_subprocess(args, timeout=timeout)
    merged = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode == 0:
        return result
    if _looks_like_permission_error(merged):
        if not _supports_sudo():
            raise _CommandExecutionError("Command access was denied and sudo is unavailable.", stderr=result.stderr or "", stdout=result.stdout or "")
        if not cached_password:
            raise _NeedSudoPasswordError("This action requires sudo privileges.")
        retry = _run_subprocess(args, sudo_password=cached_password, timeout=timeout)
        retry_merged = (retry.stdout or "") + "\n" + (retry.stderr or "")
        if retry.returncode == 0:
            return retry
        if _looks_like_bad_sudo_password(retry_merged):
            shared.clear_sudo_password()
            raise _NeedSudoPasswordError("Cached sudo password is invalid.", invalid_password=True)
        raise _CommandExecutionError("Command failed after sudo retry.", stderr=retry.stderr or "", stdout=retry.stdout or "")
    raise _CommandExecutionError("Command failed.", stderr=result.stderr or "", stdout=result.stdout or "")


def _docker_command(
    shared: NginxManagerSharedData,
    docker_binary: str,
    args: list[str],
    *,
    require_root: bool = False,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    return _run_command_with_sudo_retry(shared, [docker_binary] + args, require_root=require_root, timeout=timeout)


def _extract_mapped_port(inspect_payload: dict[str, object], key: str) -> int | None:
    network_settings = inspect_payload.get("NetworkSettings")
    if not isinstance(network_settings, dict):
        return None
    ports = network_settings.get("Ports")
    if not isinstance(ports, dict):
        return None
    bindings = ports.get(key)
    if not isinstance(bindings, list) or not bindings:
        return None
    first = bindings[0]
    if not isinstance(first, dict):
        return None
    host_port = first.get("HostPort")
    if host_port in (None, ""):
        return None
    try:
        return int(host_port)
    except Exception:
        return None


def _inspect_container(
    shared: NginxManagerSharedData,
    docker_binary: str,
    container_name: str,
) -> dict[str, object] | None:
    result = _docker_command(shared, docker_binary, ["inspect", container_name], timeout=30.0)
    text = (result.stdout or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _CommandExecutionError("Failed to parse docker inspect output.", stdout=text) from exc
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return None


def _safe_inspect_container(
    shared: NginxManagerSharedData,
    docker_binary: str,
    container_name: str,
) -> dict[str, object] | None:
    try:
        return _inspect_container(shared, docker_binary, container_name)
    except _CommandExecutionError as exc:
        merged = (exc.stdout or "") + "\n" + (exc.stderr or "")
        if _NO_OBJECT_RE.search(merged):
            return None
        raise


def _download_docker_install_script() -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="proj_docker_install_"))
    script_path = tmp_dir / "get-docker.sh"
    with urllib.request.urlopen("https://get.docker.com", timeout=30) as response:
        script_path.write_bytes(response.read())
    return script_path


def _find_package_manager() -> tuple[str, list[str]] | None:
    for binary, command in (
        ("apt-get", ["apt-get", "update", "&&", "apt-get", "install", "-y", "nginx"]),
        ("dnf", ["dnf", "install", "-y", "nginx"]),
        ("yum", ["yum", "install", "-y", "nginx"]),
        ("zypper", ["zypper", "--non-interactive", "install", "nginx"]),
        ("pacman", ["pacman", "-Sy", "--noconfirm", "nginx"]),
    ):
        if shutil.which(binary):
            return binary, command
    return None


def _run_shell_command_with_sudo_retry(
    shared: NginxManagerSharedData,
    command: str,
    *,
    require_root: bool = False,
    timeout: float = 1800.0,
) -> subprocess.CompletedProcess[str]:
    shell = shutil.which("bash") or shutil.which("sh") or "sh"
    return _run_command_with_sudo_retry(shared, [shell, "-lc", command], require_root=require_root, timeout=timeout)


def _detect_nginx_conf_dir(nginx_binary: str) -> Path:
    result = _run_subprocess([nginx_binary, "-V"], timeout=20.0)
    merged = (result.stdout or "") + "\n" + (result.stderr or "")
    match = _NGINX_CONF_PATH_RE.search(merged)
    if match is not None:
        conf_path = Path(match.group("path")).expanduser()
        if conf_path.is_absolute():
            return conf_path.parent
    return Path("/etc/nginx")


def _ensure_state_dirs(config: NginxManagerPluginConfig) -> tuple[Path, Path]:
    config_dir = Path(config.nginx_ui_config_dir).expanduser().resolve()
    www_dir = Path(config.nginx_ui_www_dir).expanduser().resolve()
    config_dir.mkdir(parents=True, exist_ok=True)
    www_dir.mkdir(parents=True, exist_ok=True)
    return config_dir, www_dir


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


class NginxManagerPlugin:
    Key: ClassVar[str] = PLUGIN_SHARED_ID
    Name: ClassVar[dict[str, str]] = {
        "zh-cn": "Nginx Manager",
        "zh-tw": "Nginx Manager",
        "en": "Nginx Manager",
    }
    Type: ClassVar[Literal["worker-only"]] = "worker-only"
    SupportedPlatform: ClassVar[Literal["linux"]] = "linux"
    Description: ClassVar[dict[str, str]] = {
        "zh-cn": "检测并安装 nginx 与 docker，然后把 nginx-ui 面板代理到插件页面。",
        "zh-tw": "檢測並安裝 nginx 與 docker，然後把 nginx-ui 面板代理到外掛頁面。",
        "en": "Detect and install nginx and docker, then proxy the nginx-ui panel into the plugin page.",
    }
    ConfigType: ClassVar[type[BaseModel]] = NginxManagerPluginConfig

    def __init__(self, config: NginxManagerPluginConfig):
        self.config = config
        self.shared = NginxManagerSharedData(PLUGIN_SHARED_ID)

    @classmethod
    def Create(cls, create_in: str, config=None, core_module=None):
        resolved_config = config if isinstance(config, NginxManagerPluginConfig) else NginxManagerPluginConfig.model_validate(config or {})
        return cls(resolved_config)

    def _admin_path(self, suffix: str) -> str:
        from core.server.data_types.config import Config

        return Config.GetConfig().server_config.get_internal_admin_path(suffix)

    def _proxy_root_path(self) -> str:
        return self._admin_path(self.config.admin_ui_proxy_path)

    def _status_response(
        self,
        *,
        nginx_installed: bool,
        docker_installed: bool,
        docker_accessible: bool,
        install_supported: bool,
        requires_sudo: bool = False,
        missing_dependencies: list[str] | None = None,
        nginx_ui_container_exists: bool = False,
        nginx_ui_running: bool = False,
        nginx_ui_http_port: int | None = None,
        nginx_ui_https_port: int | None = None,
        message: str | None = None,
    ) -> NginxManagerStatusResponse:
        return NginxManagerStatusResponse(
            plugin_key=get_plugin_key(self.__class__),
            enabled=self.config.enabled,
            host_platform=platform.system(),
            nginx_installed=nginx_installed,
            docker_installed=docker_installed,
            docker_accessible=docker_accessible,
            install_supported=install_supported,
            requires_sudo=requires_sudo,
            sudo_cached=self.shared.has_sudo_password(),
            missing_dependencies=list(missing_dependencies or []),
            nginx_ui_container_exists=nginx_ui_container_exists,
            nginx_ui_running=nginx_ui_running,
            nginx_ui_http_port=nginx_ui_http_port,
            nginx_ui_https_port=nginx_ui_https_port,
            nginx_ui_proxy_path=self._proxy_root_path() if nginx_ui_running and nginx_ui_http_port is not None else None,
            message=message,
        )

    def _collect_status(self) -> NginxManagerStatusResponse:
        if not self.config.enabled:
            return self._status_response(
                nginx_installed=False,
                docker_installed=False,
                docker_accessible=False,
                install_supported=False,
                message="Nginx Manager plugin is disabled.",
            )

        nginx_binary = _get_nginx_binary()
        docker_binary = _get_docker_binary()
        missing_dependencies: list[str] = []
        if nginx_binary is None:
            missing_dependencies.append("nginx")
        if docker_binary is None:
            missing_dependencies.append("docker")
        if missing_dependencies:
            return self._status_response(
                nginx_installed=nginx_binary is not None,
                docker_installed=docker_binary is not None,
                docker_accessible=False,
                install_supported=_is_linux(),
                missing_dependencies=missing_dependencies,
                message="Missing dependencies: " + ", ".join(missing_dependencies),
            )

        try:
            _docker_command(self.shared, docker_binary, ["info"], timeout=25.0)
        except _NeedSudoPasswordError as exc:
            return self._status_response(
                nginx_installed=True,
                docker_installed=True,
                docker_accessible=False,
                install_supported=_is_linux(),
                requires_sudo=True,
                message=str(exc),
            )
        except _CommandExecutionError as exc:
            merged = (exc.stdout or "") + "\n" + (exc.stderr or "")
            return self._status_response(
                nginx_installed=True,
                docker_installed=True,
                docker_accessible=False,
                install_supported=_is_linux(),
                message=merged.strip() or str(exc),
            )

        inspect_payload = _safe_inspect_container(self.shared, docker_binary, self.config.nginx_ui_container_name)
        if not inspect_payload:
            return self._status_response(
                nginx_installed=True,
                docker_installed=True,
                docker_accessible=True,
                install_supported=_is_linux(),
                nginx_ui_container_exists=False,
                nginx_ui_running=False,
                nginx_ui_http_port=self.shared.get_ui_http_port(),
                nginx_ui_https_port=self.shared.get_ui_https_port(),
                message="nginx-ui is not running yet.",
            )

        state_payload = inspect_payload.get("State")
        running = bool(isinstance(state_payload, dict) and state_payload.get("Running"))
        http_port = _extract_mapped_port(inspect_payload, "80/tcp")
        https_port = _extract_mapped_port(inspect_payload, "443/tcp")
        if http_port is not None:
            self.shared.set_ui_http_port(http_port)
        if https_port is not None:
            self.shared.set_ui_https_port(https_port)
        return self._status_response(
            nginx_installed=True,
            docker_installed=True,
            docker_accessible=True,
            install_supported=_is_linux(),
            nginx_ui_container_exists=True,
            nginx_ui_running=running,
            nginx_ui_http_port=http_port,
            nginx_ui_https_port=https_port,
            message="nginx-ui is running." if running else "nginx-ui container exists but is stopped.",
        )

    def _install_docker(self) -> None:
        if not _is_linux():
            raise _CommandExecutionError("Automatic Docker installation is currently supported only on Linux hosts.")
        script_path = _download_docker_install_script()
        try:
            _run_command_with_sudo_retry(self.shared, ["sh", str(script_path)], require_root=not _is_root_user(), timeout=1800.0)
            systemctl_binary = shutil.which("systemctl")
            if systemctl_binary is not None:
                try:
                    _run_command_with_sudo_retry(self.shared, [systemctl_binary, "enable", "--now", "docker"], require_root=not _is_root_user(), timeout=120.0)
                except Exception:
                    pass
        finally:
            shutil.rmtree(script_path.parent, ignore_errors=True)

    def _install_nginx(self) -> None:
        if not _is_linux():
            raise _CommandExecutionError("Automatic nginx installation is currently supported only on Linux hosts.")
        package_manager = _find_package_manager()
        if package_manager is None:
            raise _CommandExecutionError("Could not find a supported package manager to install nginx.")
        binary, command = package_manager
        if binary == "apt-get":
            _run_shell_command_with_sudo_retry(self.shared, "apt-get update && apt-get install -y nginx", require_root=not _is_root_user())
        else:
            _run_command_with_sudo_retry(self.shared, command, require_root=not _is_root_user(), timeout=1800.0)
        systemctl_binary = shutil.which("systemctl")
        if systemctl_binary is not None:
            try:
                _run_command_with_sudo_retry(self.shared, [systemctl_binary, "enable", "--now", "nginx"], require_root=not _is_root_user(), timeout=120.0)
            except Exception:
                pass

    def _install_missing_dependencies(self) -> NginxManagerStatusResponse:
        status = self._collect_status()
        if not status.docker_installed:
            self._install_docker()
        if not status.nginx_installed:
            self._install_nginx()
        return self._collect_status()

    def _start_nginx_ui(self) -> NginxManagerStatusResponse:
        status = self._collect_status()
        if status.missing_dependencies:
            raise _CommandExecutionError("Missing dependencies: " + ", ".join(status.missing_dependencies))
        if not status.docker_accessible:
            raise _CommandExecutionError(status.message or "Docker is not accessible.")

        docker_binary = _get_docker_binary()
        nginx_binary = _get_nginx_binary()
        if docker_binary is None or nginx_binary is None:
            raise _CommandExecutionError("nginx and docker must both be installed before starting nginx-ui.")

        inspect_payload = _safe_inspect_container(self.shared, docker_binary, self.config.nginx_ui_container_name)
        if inspect_payload is not None:
            state_payload = inspect_payload.get("State")
            running = bool(isinstance(state_payload, dict) and state_payload.get("Running"))
            if not running:
                _docker_command(self.shared, docker_binary, ["start", self.config.nginx_ui_container_name], timeout=120.0)
            updated = self._collect_status()
            if updated.nginx_ui_running:
                return updated

        http_port = _choose_available_port(self.config.nginx_ui_http_port, self.shared.get_ui_http_port(), _FREE_PORT_START)
        https_port = _choose_available_port(self.config.nginx_ui_https_port, self.shared.get_ui_https_port(), http_port + 1)
        self.shared.set_ui_http_port(http_port)
        self.shared.set_ui_https_port(https_port)
        config_dir, www_dir = _ensure_state_dirs(self.config)
        nginx_conf_dir = _detect_nginx_conf_dir(nginx_binary)
        _docker_command(
            self.shared,
            docker_binary,
            [
                "run",
                "-dit",
                "--name",
                self.config.nginx_ui_container_name,
                "--restart",
                "always",
                "-v",
                f"{str(nginx_conf_dir)}:/etc/nginx",
                "-v",
                f"{str(config_dir)}:/etc/nginx-ui",
                "-v",
                f"{str(www_dir)}:/var/www",
                "-p",
                f"{http_port}:80",
                "-p",
                f"{https_port}:443",
                self.config.nginx_ui_image,
            ],
            timeout=300.0,
        )
        return self._collect_status()

    def _stop_nginx_ui(self) -> NginxManagerStatusResponse:
        docker_binary = _get_docker_binary()
        if docker_binary is None:
            return self._collect_status()
        inspect_payload = _safe_inspect_container(self.shared, docker_binary, self.config.nginx_ui_container_name)
        if inspect_payload is None:
            return self._collect_status()
        _docker_command(self.shared, docker_binary, ["rm", "-f", self.config.nginx_ui_container_name], timeout=120.0)
        return self._collect_status()

    def _proxy_target_url(self, path: str) -> str:
        http_port = self.shared.get_ui_http_port()
        if http_port is None:
            raise _CommandExecutionError("nginx-ui HTTP port is unknown.")
        clean_path = str(path or "").lstrip("/")
        if clean_path:
            return f"http://127.0.0.1:{http_port}/{clean_path}"
        return f"http://127.0.0.1:{http_port}/"

    async def _proxy_ui(self, request: Request, path: str) -> Response:
        status = await asyncio.to_thread(self._collect_status)
        if not status.nginx_ui_running or status.nginx_ui_http_port is None:
            return Response(status_code=503, content=b"nginx-ui is not running.", media_type="text/plain")

        proxy_prefix = self._proxy_root_path()
        target_url = self._proxy_target_url(path)
        request_headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _HOP_BY_HOP_HEADERS
        }
        request_headers["host"] = f"127.0.0.1:{status.nginx_ui_http_port}"
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
        if getattr(app.state, "_nginx_manager_routes_registered", False):
            return
        app.state._nginx_manager_routes_registered = True

        status_path = self._admin_path(self.config.admin_status_path)
        install_path = self._admin_path(self.config.admin_install_path)
        sudo_password_path = self._admin_path(self.config.admin_sudo_password_path)
        ui_start_path = self._admin_path(self.config.admin_ui_start_path)
        ui_stop_path = self._admin_path(self.config.admin_ui_stop_path)
        ui_proxy_root = self._proxy_root_path().rstrip("/")

        @app.get(status_path, response_model=NginxManagerStatusResponse)
        async def nginx_manager_status() -> NginxManagerStatusResponse:
            return await asyncio.to_thread(self._collect_status)

        @app.post(sudo_password_path, response_model=NginxManagerActionResponse)
        async def nginx_manager_save_sudo_password(payload: NginxManagerPasswordRequest) -> NginxManagerActionResponse:
            try:
                await asyncio.to_thread(_verify_sudo_password, self.shared, payload.password)
            except _NeedSudoPasswordError as exc:
                return NginxManagerActionResponse(
                    ok=False,
                    invalid_password=exc.invalid_password,
                    sudo_cached=self.shared.has_sudo_password(),
                    message=str(exc),
                    status=await asyncio.to_thread(self._collect_status),
                )
            return NginxManagerActionResponse(
                ok=True,
                sudo_cached=self.shared.has_sudo_password(),
                message="sudo password cached in memory.",
                status=await asyncio.to_thread(self._collect_status),
            )

        @app.delete(sudo_password_path, response_model=NginxManagerActionResponse)
        async def nginx_manager_clear_sudo_password() -> NginxManagerActionResponse:
            self.shared.clear_sudo_password()
            return NginxManagerActionResponse(
                ok=True,
                sudo_cached=False,
                message="Cached sudo password cleared.",
                status=await asyncio.to_thread(self._collect_status),
            )

        @app.post(install_path, response_model=NginxManagerActionResponse)
        async def nginx_manager_install() -> NginxManagerActionResponse:
            try:
                status = await asyncio.to_thread(self._install_missing_dependencies)
                return NginxManagerActionResponse(ok=True, sudo_cached=self.shared.has_sudo_password(), message="Missing dependencies installation finished.", status=status)
            except _NeedSudoPasswordError as exc:
                return NginxManagerActionResponse(ok=False, requires_sudo=True, invalid_password=exc.invalid_password, sudo_cached=self.shared.has_sudo_password(), message=str(exc), status=await asyncio.to_thread(self._collect_status))
            except Exception as exc:
                return NginxManagerActionResponse(ok=False, sudo_cached=self.shared.has_sudo_password(), message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.post(ui_start_path, response_model=NginxManagerActionResponse)
        async def nginx_manager_start_ui() -> NginxManagerActionResponse:
            try:
                status = await asyncio.to_thread(self._start_nginx_ui)
                return NginxManagerActionResponse(ok=True, sudo_cached=self.shared.has_sudo_password(), message="nginx-ui is ready.", status=status)
            except _NeedSudoPasswordError as exc:
                return NginxManagerActionResponse(ok=False, requires_sudo=True, invalid_password=exc.invalid_password, sudo_cached=self.shared.has_sudo_password(), message=str(exc), status=await asyncio.to_thread(self._collect_status))
            except Exception as exc:
                return NginxManagerActionResponse(ok=False, sudo_cached=self.shared.has_sudo_password(), message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.post(ui_stop_path, response_model=NginxManagerActionResponse)
        async def nginx_manager_stop_ui() -> NginxManagerActionResponse:
            try:
                status = await asyncio.to_thread(self._stop_nginx_ui)
                return NginxManagerActionResponse(ok=True, sudo_cached=self.shared.has_sudo_password(), message="nginx-ui stopped.", status=status)
            except _NeedSudoPasswordError as exc:
                return NginxManagerActionResponse(ok=False, requires_sudo=True, invalid_password=exc.invalid_password, sudo_cached=self.shared.has_sudo_password(), message=str(exc), status=await asyncio.to_thread(self._collect_status))
            except Exception as exc:
                return NginxManagerActionResponse(ok=False, sudo_cached=self.shared.has_sudo_password(), message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.api_route(ui_proxy_root, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
        async def nginx_manager_proxy_root(request: Request) -> Response:
            return await self._proxy_ui(request, "")

        @app.api_route(ui_proxy_root + "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
        async def nginx_manager_proxy_path(path: str, request: Request) -> Response:
            return await self._proxy_ui(request, path)

    async def on_app_start(self, app: FastAPI) -> None:
        self._register_routes(app)

    async def admin_panel(self) -> str:
        status_path = escape(self._admin_path(self.config.admin_status_path), quote=True)
        install_path = escape(self._admin_path(self.config.admin_install_path), quote=True)
        sudo_password_path = escape(self._admin_path(self.config.admin_sudo_password_path), quote=True)
        ui_start_path = escape(self._admin_path(self.config.admin_ui_start_path), quote=True)
        ui_stop_path = escape(self._admin_path(self.config.admin_ui_stop_path), quote=True)
        ui_proxy_root = escape(self._proxy_root_path(), quote=True)
        plugin_key = escape(get_plugin_key(self.__class__), quote=True)
        return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Nginx Manager</title>
  <style>
    :root {{ color-scheme: light dark; }}
    html, body {{ margin: 0; min-height: 100%; font-family: \"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", sans-serif; }}
    body {{ background: #f2f6fb; color: #102033; }}
    .nginx-manager-shell {{ min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }}
    .nginx-manager-topbar {{ padding: 20px 24px 18px; border-bottom: 1px solid rgba(148,163,184,0.2); background: linear-gradient(135deg, rgba(3,105,161,0.96), rgba(15,23,42,0.92)); color: #e2e8f0; }}
    .nginx-manager-kicker {{ font-size: 11px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; color: #bae6fd; }}
    .nginx-manager-title {{ margin-top: 8px; font-size: 26px; font-weight: 700; }}
    .nginx-manager-desc {{ margin-top: 10px; max-width: 920px; font-size: 13px; line-height: 1.7; color: #dbeafe; }}
    .nginx-manager-toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    .nginx-manager-toolbar button {{ border: 0; border-radius: 12px; padding: 10px 14px; font-size: 13px; font-weight: 700; cursor: pointer; }}
    .nginx-manager-install {{ background: #f59e0b; color: #111827; }}
    .nginx-manager-start {{ background: #22c55e; color: #052e16; }}
    .nginx-manager-stop {{ background: #ef4444; color: #fff; }}
    .nginx-manager-refresh {{ background: rgba(148,163,184,0.16); color: #e2e8f0; }}
    .nginx-manager-main {{ min-height: 0; display: grid; grid-template-columns: 340px minmax(0, 1fr); }}
    .nginx-manager-side {{ padding: 20px; border-right: 1px solid rgba(148,163,184,0.2); background: rgba(255,255,255,0.86); box-sizing: border-box; }}
    .nginx-manager-status-card {{ border-radius: 16px; padding: 16px; background: #fff; border: 1px solid rgba(148,163,184,0.18); box-shadow: 0 16px 36px rgba(15,23,42,0.06); }}
    .nginx-manager-status-card h2 {{ margin: 0; font-size: 16px; }}
    .nginx-manager-status-line {{ margin-top: 10px; font-size: 13px; color: #334155; line-height: 1.7; white-space: pre-wrap; }}
    .nginx-manager-status-message {{ margin-top: 12px; padding: 12px 14px; border-radius: 12px; background: rgba(226,232,240,0.7); color: #334155; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }}
    .nginx-manager-content {{ min-width: 0; min-height: 0; background: linear-gradient(180deg, rgba(255,255,255,0.82), rgba(241,245,249,0.9)); }}
    .nginx-manager-frame {{ width: 100%; height: 100%; min-height: 70vh; border: 0; display: none; background: #fff; }}
    .nginx-manager-placeholder {{ height: 100%; min-height: 70vh; display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; color: #475569; font-size: 14px; line-height: 1.8; }}
    .nginx-manager-password-dialog::backdrop {{ background: rgba(15,23,42,0.42); }}
    .nginx-manager-password-dialog {{ width: min(420px, calc(100vw - 24px)); border: 0; border-radius: 18px; padding: 0; overflow: hidden; box-shadow: 0 24px 64px rgba(15,23,42,0.24); }}
    .nginx-manager-password-body {{ padding: 20px; background: #fff; color: #0f172a; }}
    .nginx-manager-password-body h3 {{ margin: 0; font-size: 18px; }}
    .nginx-manager-password-body p {{ margin: 10px 0 0; font-size: 13px; color: #475569; line-height: 1.7; }}
    .nginx-manager-password-body input {{ width: 100%; margin-top: 14px; box-sizing: border-box; border-radius: 12px; border: 1px solid rgba(148,163,184,0.35); padding: 12px 14px; font-size: 14px; }}
    .nginx-manager-password-actions {{ margin-top: 16px; display: flex; justify-content: flex-end; gap: 10px; }}
    .nginx-manager-password-actions button {{ border: 0; border-radius: 12px; padding: 10px 14px; cursor: pointer; font-weight: 700; }}
    .nginx-manager-password-cancel {{ background: #e2e8f0; color: #0f172a; }}
    .nginx-manager-password-submit {{ background: #0f172a; color: #fff; }}
    html.dark body {{ background: #020617; color: #e2e8f0; }}
    html.dark .nginx-manager-side {{ background: rgba(15,23,42,0.92); border-right-color: rgba(148,163,184,0.14); }}
    html.dark .nginx-manager-status-card {{ background: rgba(15,23,42,0.88); border-color: rgba(148,163,184,0.16); box-shadow: 0 16px 36px rgba(2,6,23,0.3); }}
    html.dark .nginx-manager-status-line {{ color: #cbd5e1; }}
    html.dark .nginx-manager-status-message {{ background: rgba(30,41,59,0.92); color: #e2e8f0; }}
    html.dark .nginx-manager-content {{ background: linear-gradient(180deg, rgba(15,23,42,0.9), rgba(15,23,42,0.96)); }}
    @media (max-width: 960px) {{ .nginx-manager-main {{ grid-template-columns: 1fr; }} .nginx-manager-side {{ border-right: 0; border-bottom: 1px solid rgba(148,163,184,0.2); }} }}
  </style>
</head>
<body>
  <div class=\"nginx-manager-shell\" data-plugin-key=\"{plugin_key}\">
    <section class=\"nginx-manager-topbar\">
      <div class=\"nginx-manager-kicker\">Plugin</div>
      <div class=\"nginx-manager-title\">Nginx Manager</div>
      <div class=\"nginx-manager-desc\">这个插件依赖宿主机上的 nginx 与 docker。缺少任一依赖时，会提示并协助安装；准备就绪后会在本机高位端口启动 <code>uozi/nginx-ui:latest</code>，再把它的界面代理回当前插件面板。</div>
      <div class=\"nginx-manager-toolbar\">
        <button type=\"button\" id=\"nginx-manager-install\" class=\"nginx-manager-install\">安装缺失依赖</button>
        <button type=\"button\" id=\"nginx-manager-start\" class=\"nginx-manager-start\">启动 nginx-ui</button>
        <button type=\"button\" id=\"nginx-manager-stop\" class=\"nginx-manager-stop\">停止 nginx-ui</button>
        <button type=\"button\" id=\"nginx-manager-refresh\" class=\"nginx-manager-refresh\">刷新状态</button>
      </div>
    </section>
    <div class=\"nginx-manager-main\">
      <aside class=\"nginx-manager-side\">
        <section class=\"nginx-manager-status-card\">
          <h2>运行状态</h2>
          <div id=\"nginx-manager-status\" class=\"nginx-manager-status-line\">正在检查 nginx / docker / nginx-ui 状态...</div>
          <div id=\"nginx-manager-status-message\" class=\"nginx-manager-status-message\"></div>
        </section>
      </aside>
      <section class=\"nginx-manager-content\">
        <div id=\"nginx-manager-placeholder\" class=\"nginx-manager-placeholder\">依赖尚未就绪。安装缺失依赖并启动 nginx-ui 后，这里会直接显示转发过来的 Nginx UI 界面。</div>
        <iframe id=\"nginx-manager-frame\" class=\"nginx-manager-frame\" src=\"about:blank\"></iframe>
      </section>
    </div>
  </div>

  <dialog id=\"nginx-manager-password-dialog\" class=\"nginx-manager-password-dialog\">
    <form method=\"dialog\" class=\"nginx-manager-password-body\">
      <h3>需要 sudo 密码</h3>
      <p id=\"nginx-manager-password-hint\">检测到当前操作需要提权。密码只会保存在当前服务进程的内存里，不会写入配置文件或磁盘。</p>
      <input id=\"nginx-manager-password-input\" type=\"password\" placeholder=\"请输入 sudo 密码\" autocomplete=\"current-password\" />
      <div class=\"nginx-manager-password-actions\">
        <button type=\"button\" id=\"nginx-manager-password-cancel\" class=\"nginx-manager-password-cancel\">取消</button>
        <button type=\"submit\" id=\"nginx-manager-password-submit\" class=\"nginx-manager-password-submit\">确认</button>
      </div>
    </form>
  </dialog>

  <script>
    (function() {{
      var statusUrl = {json.dumps(status_path)};
      var installUrl = {json.dumps(install_path)};
      var sudoPasswordUrl = {json.dumps(sudo_password_path)};
      var uiStartUrl = {json.dumps(ui_start_path)};
      var uiStopUrl = {json.dumps(ui_stop_path)};
      var uiProxyRoot = {json.dumps(ui_proxy_root)};
      var frame = document.getElementById('nginx-manager-frame');
      var placeholder = document.getElementById('nginx-manager-placeholder');
      var statusNode = document.getElementById('nginx-manager-status');
      var statusMessage = document.getElementById('nginx-manager-status-message');
      var passwordDialog = document.getElementById('nginx-manager-password-dialog');
      var passwordInput = document.getElementById('nginx-manager-password-input');
      var passwordHint = document.getElementById('nginx-manager-password-hint');
      var pendingAction = null;

      function syncTheme(data) {{
        if (!data || typeof data !== 'object') return;
        if (Object.prototype.hasOwnProperty.call(data, 'dark')) {{
          document.documentElement.classList.toggle('dark', !!data.dark);
        }}
      }}

      function setMessage(text) {{
        statusMessage.textContent = String(text || '').trim();
      }}

      function setStatus(data) {{
        if (!data || typeof data !== 'object') return;
        var lines = [];
        lines.push('nginx 已安装: ' + (data.nginx_installed ? '是' : '否'));
        lines.push('Docker 已安装: ' + (data.docker_installed ? '是' : '否'));
        lines.push('Docker 可访问: ' + (data.docker_accessible ? '是' : '否'));
        lines.push('sudo 已缓存: ' + (data.sudo_cached ? '是' : '否'));
        lines.push('nginx-ui 容器存在: ' + (data.nginx_ui_container_exists ? '是' : '否'));
        lines.push('nginx-ui 运行中: ' + (data.nginx_ui_running ? '是' : '否'));
        if (data.missing_dependencies && data.missing_dependencies.length) lines.push('缺失依赖: ' + data.missing_dependencies.join(', '));
        if (data.nginx_ui_http_port) lines.push('nginx-ui HTTP 端口: ' + data.nginx_ui_http_port);
        statusNode.textContent = lines.join('\n');
        setMessage(data.message || '');
        document.getElementById('nginx-manager-install').style.display = (data.missing_dependencies && data.missing_dependencies.length) ? '' : 'none';
        document.getElementById('nginx-manager-start').style.display = (data.nginx_installed && data.docker_installed) ? '' : 'none';
        document.getElementById('nginx-manager-stop').style.display = data.nginx_ui_running ? '' : 'none';
        if (data.nginx_ui_running) {{
          frame.style.display = 'block';
          placeholder.style.display = 'none';
          if (frame.getAttribute('src') !== uiProxyRoot) frame.setAttribute('src', uiProxyRoot);
        }} else {{
          frame.style.display = 'none';
          frame.setAttribute('src', 'about:blank');
          placeholder.style.display = 'flex';
        }}
        if (data.requires_sudo) {{
          openPasswordDialog(data.message || '当前操作需要 sudo 密码。');
        }}
      }}

      async function fetchJson(url, options) {{
        var response = await fetch(url, Object.assign({{ credentials: 'same-origin' }}, options || {{}}));
        var payload = null;
        try {{
          payload = await response.json();
        }} catch (error) {{
          payload = null;
        }}
        if (!response.ok && !payload) {{
          throw new Error('Request failed: ' + response.status);
        }}
        return payload;
      }}

      async function refreshStatus() {{
        var payload = await fetchJson(statusUrl);
        setStatus(payload);
        return payload;
      }}

      function openPasswordDialog(message) {{
        pendingAction = pendingAction || null;
        passwordHint.textContent = String(message || '当前操作需要 sudo 密码。');
        passwordInput.value = '';
        if (passwordDialog && typeof passwordDialog.showModal === 'function' && !passwordDialog.open) {{
          passwordDialog.showModal();
        }}
        window.setTimeout(function() {{ passwordInput.focus(); }}, 0);
      }}

      async function runAction(url) {{
        pendingAction = url;
        var payload = await fetchJson(url, {{ method: 'POST' }});
        if (payload && payload.requires_sudo) {{
          openPasswordDialog(payload.message || '当前操作需要 sudo 密码。');
          return payload;
        }}
        pendingAction = null;
        if (payload && payload.status) setStatus(payload.status);
        else await refreshStatus();
        if (payload && payload.message) setMessage(payload.message);
        return payload;
      }}

      document.getElementById('nginx-manager-install').addEventListener('click', function() {{ runAction(installUrl).catch(function(error) {{ setMessage(String(error)); }}); }});
      document.getElementById('nginx-manager-start').addEventListener('click', function() {{ runAction(uiStartUrl).catch(function(error) {{ setMessage(String(error)); }}); }});
      document.getElementById('nginx-manager-stop').addEventListener('click', function() {{ runAction(uiStopUrl).catch(function(error) {{ setMessage(String(error)); }}); }});
      document.getElementById('nginx-manager-refresh').addEventListener('click', function() {{ refreshStatus().catch(function(error) {{ setMessage(String(error)); }}); }});
      document.getElementById('nginx-manager-password-cancel').addEventListener('click', function() {{ pendingAction = null; passwordDialog.close(); }});
      passwordDialog.addEventListener('submit', function(event) {{
        event.preventDefault();
        fetchJson(sudoPasswordUrl, {{
          method: 'POST',
          headers: {{ 'content-type': 'application/json' }},
          body: JSON.stringify({{ password: passwordInput.value }}),
        }}).then(function(payload) {{
          if (payload && !payload.ok) {{
            passwordHint.textContent = payload.message || 'sudo 密码验证失败。';
            return;
          }}
          passwordDialog.close();
          var action = pendingAction;
          pendingAction = null;
          if (action) return runAction(action);
          return refreshStatus();
        }}).catch(function(error) {{
          passwordHint.textContent = String(error);
        }});
      }});

      window.addEventListener('message', function(event) {{
        var data = event && event.data;
        if (!data || typeof data !== 'object') return;
        if (data.type === 'proj-sync' || data.type === 'proj-set-dark') syncTheme(data);
      }});

      refreshStatus().catch(function(error) {{ setMessage(String(error)); }});
    }})();
  </script>
</body>
</html>"""


__all__ = [
    "NginxManagerActionResponse",
    "NginxManagerPasswordRequest",
    "NginxManagerPlugin",
    "NginxManagerPluginConfig",
    "NginxManagerStatusResponse",
    "PLUGIN_SHARED_ID",
]