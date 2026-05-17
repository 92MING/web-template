import asyncio
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import tarfile
import tempfile
import time
import tomllib
import urllib.parse
import urllib.request
import zipfile
from html import escape
from pathlib import Path
from typing import ClassVar, Literal

import httpx
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from core.constants import PROJECT_DIR
from core.server.plugin import get_plugin_key
from core.utils.type_utils import AdvancedBaseModel

from .shared import FrpManagerSharedData


PLUGIN_SHARED_ID = "frp-manager"
PLUGIN_DIR = Path(__file__).resolve().parent
PLUGIN_STATE_DIR = PROJECT_DIR / "tmp" / "plugins" / "frp-manager"
PLUGIN_STORAGE_DIR = PLUGIN_STATE_DIR / "binaries"
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
_HTML_ATTR_RE = re.compile(r'(?P<attr>(?:src|href|action)=([\"\']))/(?P<path>[^\"\']*)', re.IGNORECASE)
_CSS_URL_RE = re.compile(r'url\((?P<quote>[\"\']?)/(?P<path>[^)\"\']*)(?P=quote)\)')
_FRP_RELEASE_API_URL = "https://api.github.com/repos/fatedier/frp/releases/latest"
_UI_DEFAULTS: dict[str, int] = {"frps": 7500, "frpc": 7400}
_BINARY_NAMES: dict[str, str] = {
    "frps": "frps.exe" if platform.system().lower() == "windows" else "frps",
    "frpc": "frpc.exe" if platform.system().lower() == "windows" else "frpc",
}


def _normalize_internal_suffix(path: str, fallback: str) -> str:
    text = str(path or "").strip().strip("/")
    return text or fallback


def _binary_name(target: Literal["frps", "frpc"]) -> str:
    return _BINARY_NAMES[target]


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _release_platform_token() -> str | None:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    if system == "darwin":
        return "darwin"
    return None


def _release_arch_candidates() -> list[str]:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return ["amd64"]
    if machine in {"arm64", "aarch64"}:
        return ["arm64"]
    if machine in {"386", "i386", "i686", "x86"}:
        return ["386"]
    if machine in {"arm", "armv6l"}:
        return ["arm", "arm_hf"]
    if machine in {"armv7", "armv7l"}:
        return ["arm_hf", "arm"]
    if machine in {"mips"}:
        return ["mips"]
    if machine in {"mips64"}:
        return ["mips64"]
    if machine in {"loong64"}:
        return ["loong64"]
    return [machine]


def _config_root(config: "FrpManagerPluginConfig") -> Path:
    return Path(config.state_dir).expanduser().resolve()


def _storage_root(config: "FrpManagerPluginConfig") -> Path:
    return Path(config.local_storage_dir).expanduser().resolve()


def _binary_dir(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> Path:
    return _storage_root(config) / target


def _local_binary_path(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> Path:
    return _binary_dir(config, target) / _binary_name(target)


def _runtime_config_path(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> Path:
    return _config_root(config) / "config" / f"{target}.toml"


def _runtime_log_path(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> Path:
    return _config_root(config) / "logs" / f"{target}.log"


def _release_meta_path(config: "FrpManagerPluginConfig") -> Path:
    return _storage_root(config) / "release.json"


def _ensure_runtime_dirs(config: "FrpManagerPluginConfig") -> None:
    (_config_root(config) / "config").mkdir(parents=True, exist_ok=True)
    (_config_root(config) / "logs").mkdir(parents=True, exist_ok=True)
    _binary_dir(config, "frps").mkdir(parents=True, exist_ok=True)
    _binary_dir(config, "frpc").mkdir(parents=True, exist_ok=True)


def _default_frps_config(config: "FrpManagerPluginConfig") -> str:
    return (
        f'bindAddr = "0.0.0.0"\n'
        f'bindPort = {int(config.default_frps_bind_port)}\n\n'
        'webServer.addr = "127.0.0.1"\n'
        f'webServer.port = {int(config.default_frps_ui_port)}\n'
        f'webServer.user = "{config.default_ui_user}"\n'
        f'webServer.password = "{config.default_ui_password}"\n\n'
        'auth.method = "token"\n'
        'auth.token = "change-me"\n\n'
        'log.to = "console"\n'
        'log.level = "info"\n'
    )


def _default_frpc_config(config: "FrpManagerPluginConfig") -> str:
    return (
        'serverAddr = "127.0.0.1"\n'
        f'serverPort = {int(config.default_frps_bind_port)}\n\n'
        'webServer.addr = "127.0.0.1"\n'
        f'webServer.port = {int(config.default_frpc_ui_port)}\n'
        f'webServer.user = "{config.default_ui_user}"\n'
        f'webServer.password = "{config.default_ui_password}"\n\n'
        'auth.method = "token"\n'
        'auth.token = "change-me"\n\n'
        'log.to = "console"\n'
        'log.level = "info"\n\n'
        '# Add proxies below.\n'
    )


def _ensure_default_configs(config: "FrpManagerPluginConfig") -> None:
    _ensure_runtime_dirs(config)
    frps_path = _runtime_config_path(config, "frps")
    frpc_path = _runtime_config_path(config, "frpc")
    if not frps_path.is_file():
        frps_path.write_text(_default_frps_config(config), encoding="utf-8")
    if not frpc_path.is_file():
        frpc_path.write_text(_default_frpc_config(config), encoding="utf-8")


def _read_config_text(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> str:
    _ensure_default_configs(config)
    return _runtime_config_path(config, target).read_text(encoding="utf-8")


def _save_config_text(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"], content: str) -> None:
    _ensure_default_configs(config)
    tomllib.loads(str(content))
    _runtime_config_path(config, target).write_text(str(content).rstrip() + "\n", encoding="utf-8")


def _load_config_dict(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> dict[str, object]:
    _ensure_default_configs(config)
    return tomllib.loads(_runtime_config_path(config, target).read_text(encoding="utf-8"))


def _ui_port_from_config(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> int | None:
    try:
        payload = _load_config_dict(config, target)
    except Exception:
        return _UI_DEFAULTS[target]
    web_server = payload.get("webServer")
    if isinstance(web_server, dict):
        port = web_server.get("port")
        if isinstance(port, int):
            return int(port)
    return _UI_DEFAULTS[target]


def _ui_basic_auth_credentials(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> tuple[str, str] | None:
    try:
        payload = _load_config_dict(config, target)
    except Exception:
        return None
    web_server = payload.get("webServer")
    if not isinstance(web_server, dict):
        return None
    username = web_server.get("user")
    password = web_server.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return None
    return username, password


def _system_binary_path(target: Literal["frps", "frpc"]) -> str | None:
    return shutil.which(target)


def _binary_source(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> Literal["system", "local", "none"]:
    if _system_binary_path(target):
        return "system"
    if _local_binary_path(config, target).is_file():
        return "local"
    return "none"


def _effective_binary_path(config: "FrpManagerPluginConfig", target: Literal["frps", "frpc"]) -> Path | None:
    system_path = _system_binary_path(target)
    if system_path:
        return Path(system_path)
    local_path = _local_binary_path(config, target)
    if local_path.is_file():
        return local_path
    return None


def _read_release_meta(config: "FrpManagerPluginConfig") -> dict[str, object] | None:
    path = _release_meta_path(config)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_release_meta(config: "FrpManagerPluginConfig", *, tag_name: str, asset_name: str) -> None:
    _ensure_runtime_dirs(config)
    _release_meta_path(config).write_text(
        json.dumps({"tag_name": tag_name, "asset_name": asset_name}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fetch_latest_release_payload(config: "FrpManagerPluginConfig") -> dict[str, object]:
    request = urllib.request.Request(
        config.release_api_url,
        headers={
            "accept": "application/vnd.github+json",
            "user-agent": "proj-template-frp-manager",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Invalid GitHub release response.")
    return payload


def _select_release_asset(payload: dict[str, object]) -> tuple[str, str, str]:
    platform_token = _release_platform_token()
    if platform_token is None:
        raise RuntimeError(f"Unsupported host platform for frp: {platform.system()}")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("GitHub release response does not contain assets.")
    tag_name = str(payload.get("tag_name") or "").strip()
    if not tag_name:
        raise RuntimeError("GitHub release response does not contain tag_name.")

    candidate_items = [item for item in assets if isinstance(item, dict)]
    for arch in _release_arch_candidates():
        suffixes = [f"_{platform_token}_{arch}.zip", f"_{platform_token}_{arch}.tar.gz"]
        for suffix in suffixes:
            for item in candidate_items:
                name = str(item.get("name") or "")
                if not name.endswith(suffix):
                    continue
                url = str(item.get("browser_download_url") or "")
                if url:
                    return tag_name, name, url
    raise RuntimeError(
        f"No frp release asset matched platform={platform_token!r} arch candidates={_release_arch_candidates()!r}."
    )


def _download_asset(url: str, target_path: Path) -> None:
    request = urllib.request.Request(url, headers={"user-agent": "proj-template-frp-manager"})
    with urllib.request.urlopen(request, timeout=120) as response:
        target_path.write_bytes(response.read())


def _extract_archive(archive_path: Path, extract_root: Path) -> None:
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_root)
        return
    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, "r:*") as archive:
            archive.extractall(extract_root, filter="data")
        return
    raise RuntimeError(f"Unsupported frp archive format: {archive_path.name}")


def _find_executable(root: Path, target: Literal["frps", "frpc"]) -> Path:
    expected = _binary_name(target)
    matches = [path for path in root.rglob(expected) if path.is_file()]
    if not matches:
        raise RuntimeError(f"Could not find {expected} in extracted frp archive.")
    return sorted(matches)[0]


def _install_missing_binaries(config: "FrpManagerPluginConfig") -> tuple[str | None, list[str]]:
    _ensure_runtime_dirs(config)
    missing_targets = [
        target
        for target in ("frps", "frpc")
        if _system_binary_path(target) is None and not _local_binary_path(config, target).is_file()
    ]
    if not missing_targets:
        metadata = _read_release_meta(config)
        tag_name = str(metadata.get("tag_name") or "") if isinstance(metadata, dict) else ""
        return (tag_name or None), []

    payload = _fetch_latest_release_payload(config)
    tag_name, asset_name, download_url = _select_release_asset(payload)
    temp_root = Path(tempfile.mkdtemp(prefix="proj_frp_manager_"))
    archive_path = temp_root / asset_name
    extract_root = temp_root / "extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    try:
        _download_asset(download_url, archive_path)
        _extract_archive(archive_path, extract_root)
        installed: list[str] = []
        for target in missing_targets:
            source_path = _find_executable(extract_root, target)
            destination = _local_binary_path(config, target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            if not _is_windows():
                destination.chmod(0o755)
            installed.append(target)
        _write_release_meta(config, tag_name=tag_name, asset_name=asset_name)
        return tag_name, installed
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _is_pid_running(pid: int | None) -> bool:
    if pid is None or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _wait_for_tcp_port(port: int | None, timeout: float = 10.0) -> bool:
    if port is None:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            if sock.connect_ex(("127.0.0.1", int(port))) == 0:
                return True
        time.sleep(0.1)
    return False


def _terminate_pid(pid: int) -> None:
    if _is_windows():
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20.0,
        )
        if result.returncode not in {0, 128, 255} and _is_pid_running(pid):
            raise RuntimeError((result.stdout or "") + "\n" + (result.stderr or ""))
        return

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not _is_pid_running(pid):
            return
        time.sleep(0.1)
    os.kill(pid, signal.SIGKILL)


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


class FrpManagerPluginConfig(BaseModel):
    enabled: bool = True
    release_api_url: str = _FRP_RELEASE_API_URL
    local_storage_dir: str = str(PLUGIN_STORAGE_DIR)
    state_dir: str = str(PLUGIN_STATE_DIR)
    default_frps_bind_port: int = 7000
    default_frps_ui_port: int = 7500
    default_frpc_ui_port: int = 7400
    default_ui_user: str = "admin"
    default_ui_password: str = "admin"
    admin_status_path: str = "api/frp-manager/status"
    admin_install_path: str = "api/frp-manager/install"
    admin_config_path: str = "api/frp-manager/config"
    admin_frps_start_path: str = "api/frp-manager/frps/start"
    admin_frps_stop_path: str = "api/frp-manager/frps/stop"
    admin_frpc_start_path: str = "api/frp-manager/frpc/start"
    admin_frpc_stop_path: str = "api/frp-manager/frpc/stop"
    admin_frps_proxy_path: str = "frp-manager/frps/ui"
    admin_frpc_proxy_path: str = "frp-manager/frpc/ui"

    def model_post_init(self, __context) -> None:
        self.admin_status_path = _normalize_internal_suffix(self.admin_status_path, "api/frp-manager/status")
        self.admin_install_path = _normalize_internal_suffix(self.admin_install_path, "api/frp-manager/install")
        self.admin_config_path = _normalize_internal_suffix(self.admin_config_path, "api/frp-manager/config")
        self.admin_frps_start_path = _normalize_internal_suffix(self.admin_frps_start_path, "api/frp-manager/frps/start")
        self.admin_frps_stop_path = _normalize_internal_suffix(self.admin_frps_stop_path, "api/frp-manager/frps/stop")
        self.admin_frpc_start_path = _normalize_internal_suffix(self.admin_frpc_start_path, "api/frp-manager/frpc/start")
        self.admin_frpc_stop_path = _normalize_internal_suffix(self.admin_frpc_stop_path, "api/frp-manager/frpc/stop")
        self.admin_frps_proxy_path = _normalize_internal_suffix(self.admin_frps_proxy_path, "frp-manager/frps/ui")
        self.admin_frpc_proxy_path = _normalize_internal_suffix(self.admin_frpc_proxy_path, "frp-manager/frpc/ui")
        self.local_storage_dir = str(Path(self.local_storage_dir).expanduser())
        self.state_dir = str(Path(self.state_dir).expanduser())


class FrpManagerStatusResponse(AdvancedBaseModel):
    plugin_key: str
    enabled: bool
    host_platform: str
    architecture: str
    install_supported: bool
    frps_installed: bool
    frpc_installed: bool
    frps_binary_source: Literal["system", "local", "none"]
    frpc_binary_source: Literal["system", "local", "none"]
    frps_binary_path: str | None = None
    frpc_binary_path: str | None = None
    installed_release_tag: str | None = None
    frps_running: bool = False
    frpc_running: bool = False
    frps_pid: int | None = None
    frpc_pid: int | None = None
    frps_ui_port: int | None = None
    frpc_ui_port: int | None = None
    frps_ui_proxy_path: str | None = None
    frpc_ui_proxy_path: str | None = None
    frps_config_path: str | None = None
    frpc_config_path: str | None = None
    message: str | None = None


class FrpManagerActionResponse(AdvancedBaseModel):
    ok: bool
    message: str | None = None
    status: FrpManagerStatusResponse | None = None


class FrpManagerConfigResponse(AdvancedBaseModel):
    ok: bool
    target: Literal["frps", "frpc"]
    path: str
    content: str
    running: bool


class FrpManagerConfigRequest(AdvancedBaseModel):
    content: str


class _CommandExecutionError(RuntimeError):
    pass


class FrpManagerPlugin:
    Key: ClassVar[str] = PLUGIN_SHARED_ID
    Name: ClassVar[dict[str, str]] = {
        "zh-cn": "FRP Manager",
        "zh-tw": "FRP Manager",
        "en": "FRP Manager",
    }
    Type: ClassVar[Literal["worker-only"]] = "worker-only"
    SupportedPlatform: ClassVar[tuple[Literal["all"], ...]] = ("all",)
    Description: ClassVar[dict[str, str]] = {
        "zh-cn": "检测 frps / frpc，可从 GitHub 最新 release 下载适配二进制，并代理两侧内置 Web UI。",
        "zh-tw": "檢測 frps / frpc，可從 GitHub 最新 release 下載適配二進位，並代理兩側內建 Web UI。",
        "en": "Detect frps / frpc, download matching binaries from the latest GitHub release, and proxy both built-in web UIs.",
    }
    ConfigType: ClassVar[type[BaseModel]] = FrpManagerPluginConfig

    def __init__(self, config: FrpManagerPluginConfig):
        self.config = config
        self.shared = FrpManagerSharedData(PLUGIN_SHARED_ID)
        self._processes: dict[str, subprocess.Popen[bytes] | None] = {"frps": None, "frpc": None}
        self._log_handles: dict[str, object | None] = {"frps": None, "frpc": None}

    @classmethod
    def Create(cls, create_in: str, config=None, core_module=None):
        resolved_config = config if isinstance(config, FrpManagerPluginConfig) else FrpManagerPluginConfig.model_validate(config or {})
        return cls(resolved_config)

    def _admin_path(self, suffix: str) -> str:
        from core.server.data_types.config import Config

        return Config.GetConfig().server_config.get_internal_admin_path(suffix)

    def _proxy_root_path(self, target: Literal["frps", "frpc"]) -> str:
        proxy_suffix = self.config.admin_frps_proxy_path if target == "frps" else self.config.admin_frpc_proxy_path
        return self._admin_path(proxy_suffix)

    def _cleanup_local_process_ref(self, target: Literal["frps", "frpc"]) -> None:
        process = self._processes[target]
        if process is not None and process.poll() is not None:
            self._processes[target] = None
            handle = self._log_handles[target]
            self._log_handles[target] = None
            try:
                if handle is not None:
                    handle.close()
            except Exception:
                pass

    def _running_state(self, target: Literal["frps", "frpc"]) -> tuple[bool, int | None]:
        self._cleanup_local_process_ref(target)
        process = self._processes[target]
        if process is not None and process.poll() is None:
            return True, int(process.pid)
        pid = self.shared.get_frps_pid() if target == "frps" else self.shared.get_frpc_pid()
        if _is_pid_running(pid):
            return True, pid
        if target == "frps":
            self.shared.set_frps_pid(None)
        else:
            self.shared.set_frpc_pid(None)
        return False, None

    def _status_response(self, *, message: str | None = None) -> FrpManagerStatusResponse:
        _ensure_default_configs(self.config)
        release_meta = _read_release_meta(self.config)
        installed_release_tag = str(release_meta.get("tag_name") or "") if isinstance(release_meta, dict) else ""
        self.shared.set_installed_release_tag(installed_release_tag or None)
        frps_binary = _effective_binary_path(self.config, "frps")
        frpc_binary = _effective_binary_path(self.config, "frpc")
        frps_running, frps_pid = self._running_state("frps")
        frpc_running, frpc_pid = self._running_state("frpc")
        frps_ui_port = self.shared.get_frps_ui_port() or _ui_port_from_config(self.config, "frps")
        frpc_ui_port = self.shared.get_frpc_ui_port() or _ui_port_from_config(self.config, "frpc")
        return FrpManagerStatusResponse(
            plugin_key=get_plugin_key(self.__class__),
            enabled=self.config.enabled,
            host_platform=platform.system(),
            architecture=platform.machine(),
            install_supported=_release_platform_token() is not None,
            frps_installed=frps_binary is not None,
            frpc_installed=frpc_binary is not None,
            frps_binary_source=_binary_source(self.config, "frps"),
            frpc_binary_source=_binary_source(self.config, "frpc"),
            frps_binary_path=str(frps_binary) if frps_binary is not None else None,
            frpc_binary_path=str(frpc_binary) if frpc_binary is not None else None,
            installed_release_tag=installed_release_tag or self.shared.get_installed_release_tag(),
            frps_running=frps_running,
            frpc_running=frpc_running,
            frps_pid=frps_pid,
            frpc_pid=frpc_pid,
            frps_ui_port=frps_ui_port,
            frpc_ui_port=frpc_ui_port,
            frps_ui_proxy_path=self._proxy_root_path("frps") if frps_running and frps_ui_port is not None else None,
            frpc_ui_proxy_path=self._proxy_root_path("frpc") if frpc_running and frpc_ui_port is not None else None,
            frps_config_path=str(_runtime_config_path(self.config, "frps")),
            frpc_config_path=str(_runtime_config_path(self.config, "frpc")),
            message=message,
        )

    def _collect_status(self) -> FrpManagerStatusResponse:
        if not self.config.enabled:
            return self._status_response(message="FRP Manager plugin is disabled.")
        status = self._status_response()
        if not status.frps_installed or not status.frpc_installed:
            missing = []
            if not status.frps_installed:
                missing.append("frps")
            if not status.frpc_installed:
                missing.append("frpc")
            status.message = "Missing binaries: " + ", ".join(missing)
        elif not status.frps_running and not status.frpc_running:
            status.message = "frps and frpc are both stopped."
        else:
            status.message = "frp services are available."
        return status

    def _install_binaries(self) -> FrpManagerStatusResponse:
        tag_name, installed = _install_missing_binaries(self.config)
        if tag_name:
            self.shared.set_installed_release_tag(tag_name)
        if installed:
            return self._status_response(message=f"Installed {', '.join(installed)} from {tag_name}.")
        return self._status_response(message="frps and frpc are already available.")

    def _start_target(self, target: Literal["frps", "frpc"]) -> FrpManagerStatusResponse:
        status = self._collect_status()
        already_running = status.frps_running if target == "frps" else status.frpc_running
        if already_running:
            return self._status_response(message=f"{target} is already running.")
        binary_path = _effective_binary_path(self.config, target)
        if binary_path is None:
            raise _CommandExecutionError(f"{target} is not installed.")

        config_path = _runtime_config_path(self.config, target)
        ui_port = _ui_port_from_config(self.config, target)
        if ui_port is None:
            raise _CommandExecutionError(f"{target}.toml must define webServer.port for the plugin to proxy the UI.")

        log_path = _runtime_log_path(self.config, target)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("ab")
        popen_kwargs: dict[str, object] = {
            "cwd": str(_config_root(self.config)),
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
        }
        if _is_windows():
            popen_kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen([str(binary_path), "-c", str(config_path)], **popen_kwargs)
        self._processes[target] = process
        self._log_handles[target] = log_handle
        if target == "frps":
            self.shared.set_frps_pid(int(process.pid))
            self.shared.set_frps_ui_port(ui_port)
        else:
            self.shared.set_frpc_pid(int(process.pid))
            self.shared.set_frpc_ui_port(ui_port)

        if not _wait_for_tcp_port(ui_port, timeout=10.0):
            if process.poll() is not None:
                self._cleanup_local_process_ref(target)
                if target == "frps":
                    self.shared.set_frps_pid(None)
                else:
                    self.shared.set_frpc_pid(None)
                raise _CommandExecutionError(f"{target} exited before its Web UI became ready. Check log: {log_path}")
        return self._status_response(message=f"{target} is ready.")

    def _stop_target(self, target: Literal["frps", "frpc"]) -> FrpManagerStatusResponse:
        running, pid = self._running_state(target)
        if not running or pid is None:
            return self._status_response(message=f"{target} is already stopped.")
        _terminate_pid(pid)
        self._cleanup_local_process_ref(target)
        if target == "frps":
            self.shared.set_frps_pid(None)
        else:
            self.shared.set_frpc_pid(None)
        return self._status_response(message=f"{target} stopped.")

    async def _proxy_ui(self, request: Request, target: Literal["frps", "frpc"], path: str) -> Response:
        status = await asyncio.to_thread(self._collect_status)
        running = status.frps_running if target == "frps" else status.frpc_running
        ui_port = status.frps_ui_port if target == "frps" else status.frpc_ui_port
        if not running or ui_port is None:
            return Response(status_code=503, content=f"{target} is not running.".encode("utf-8"), media_type="text/plain")

        proxy_prefix = self._proxy_root_path(target)
        clean_path = str(path or "").lstrip("/")
        auth_credentials = _ui_basic_auth_credentials(self.config, target)
        if auth_credentials is None:
            target_origin = f"http://127.0.0.1:{ui_port}"
        else:
            username, password = auth_credentials
            target_origin = (
                f"http://{urllib.parse.quote(username, safe='')}:{urllib.parse.quote(password, safe='')}"
                f"@127.0.0.1:{ui_port}"
            )
        target_url = f"{target_origin}/{clean_path}" if clean_path else f"{target_origin}/"
        request_headers = {key: value for key, value in request.headers.items() if key.lower() not in _HOP_BY_HOP_HEADERS}
        request_headers["host"] = f"127.0.0.1:{ui_port}"
        body = await request.body()

        async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=60.0) as client:
            response = await client.request(
                request.method,
                target_url,
                headers=request_headers,
                content=body,
                params=request.query_params,
            )

        response_headers = {key: value for key, value in response.headers.items() if key.lower() not in _HOP_BY_HOP_HEADERS}
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
        if getattr(app.state, "_frp_manager_routes_registered", False):
            return
        app.state._frp_manager_routes_registered = True

        status_path = self._admin_path(self.config.admin_status_path)
        install_path = self._admin_path(self.config.admin_install_path)
        config_root_path = self._admin_path(self.config.admin_config_path)
        frps_start_path = self._admin_path(self.config.admin_frps_start_path)
        frps_stop_path = self._admin_path(self.config.admin_frps_stop_path)
        frpc_start_path = self._admin_path(self.config.admin_frpc_start_path)
        frpc_stop_path = self._admin_path(self.config.admin_frpc_stop_path)
        frps_proxy_root = self._proxy_root_path("frps").rstrip("/")
        frpc_proxy_root = self._proxy_root_path("frpc").rstrip("/")

        @app.get(status_path, response_model=FrpManagerStatusResponse)
        async def frp_manager_status() -> FrpManagerStatusResponse:
            return await asyncio.to_thread(self._collect_status)

        @app.post(install_path, response_model=FrpManagerActionResponse)
        async def frp_manager_install() -> FrpManagerActionResponse:
            try:
                status = await asyncio.to_thread(self._install_binaries)
                return FrpManagerActionResponse(ok=True, message=status.message, status=status)
            except Exception as exc:
                return FrpManagerActionResponse(ok=False, message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.get(config_root_path + "/{target}", response_model=FrpManagerConfigResponse)
        async def frp_manager_get_config(target: str) -> FrpManagerConfigResponse:
            normalized = str(target or "").strip().lower()
            if normalized not in {"frps", "frpc"}:
                return FrpManagerConfigResponse(ok=False, target="frps", path="", content="", running=False)
            running, _pid = await asyncio.to_thread(self._running_state, normalized)
            return FrpManagerConfigResponse(
                ok=True,
                target=normalized,
                path=str(_runtime_config_path(self.config, normalized)),
                content=await asyncio.to_thread(_read_config_text, self.config, normalized),
                running=running,
            )

        @app.post(config_root_path + "/{target}", response_model=FrpManagerActionResponse)
        async def frp_manager_save_config(target: str, payload: FrpManagerConfigRequest) -> FrpManagerActionResponse:
            normalized = str(target or "").strip().lower()
            if normalized not in {"frps", "frpc"}:
                return FrpManagerActionResponse(ok=False, message=f"Unsupported target: {target!r}", status=await asyncio.to_thread(self._collect_status))
            try:
                await asyncio.to_thread(_save_config_text, self.config, normalized, payload.content)
                return FrpManagerActionResponse(ok=True, message=f"{normalized}.toml saved. Restart {normalized} to apply changes.", status=await asyncio.to_thread(self._collect_status))
            except Exception as exc:
                return FrpManagerActionResponse(ok=False, message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.post(frps_start_path, response_model=FrpManagerActionResponse)
        async def frp_manager_start_frps() -> FrpManagerActionResponse:
            try:
                status = await asyncio.to_thread(self._start_target, "frps")
                return FrpManagerActionResponse(ok=True, message=status.message, status=status)
            except Exception as exc:
                return FrpManagerActionResponse(ok=False, message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.post(frps_stop_path, response_model=FrpManagerActionResponse)
        async def frp_manager_stop_frps() -> FrpManagerActionResponse:
            try:
                status = await asyncio.to_thread(self._stop_target, "frps")
                return FrpManagerActionResponse(ok=True, message=status.message, status=status)
            except Exception as exc:
                return FrpManagerActionResponse(ok=False, message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.post(frpc_start_path, response_model=FrpManagerActionResponse)
        async def frp_manager_start_frpc() -> FrpManagerActionResponse:
            try:
                status = await asyncio.to_thread(self._start_target, "frpc")
                return FrpManagerActionResponse(ok=True, message=status.message, status=status)
            except Exception as exc:
                return FrpManagerActionResponse(ok=False, message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.post(frpc_stop_path, response_model=FrpManagerActionResponse)
        async def frp_manager_stop_frpc() -> FrpManagerActionResponse:
            try:
                status = await asyncio.to_thread(self._stop_target, "frpc")
                return FrpManagerActionResponse(ok=True, message=status.message, status=status)
            except Exception as exc:
                return FrpManagerActionResponse(ok=False, message=str(exc), status=await asyncio.to_thread(self._collect_status))

        @app.api_route(frps_proxy_root, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
        async def frp_manager_proxy_frps_root(request: Request) -> Response:
            return await self._proxy_ui(request, "frps", "")

        @app.api_route(frps_proxy_root + "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
        async def frp_manager_proxy_frps_path(path: str, request: Request) -> Response:
            return await self._proxy_ui(request, "frps", path)

        @app.api_route(frpc_proxy_root, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
        async def frp_manager_proxy_frpc_root(request: Request) -> Response:
            return await self._proxy_ui(request, "frpc", "")

        @app.api_route(frpc_proxy_root + "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False)
        async def frp_manager_proxy_frpc_path(path: str, request: Request) -> Response:
            return await self._proxy_ui(request, "frpc", path)

    async def on_app_start(self, app: FastAPI) -> None:
        _ensure_default_configs(self.config)
        self._register_routes(app)

    async def on_app_shutdown(self, app: FastAPI) -> None:
        for target in ("frps", "frpc"):
            process = self._processes[target]
            if process is not None and process.poll() is None:
                try:
                    await asyncio.to_thread(_terminate_pid, int(process.pid))
                except Exception:
                    pass
            self._cleanup_local_process_ref(target)

    async def admin_panel(self) -> str:
        plugin_key = escape(get_plugin_key(self.__class__), quote=True)
        status_path = escape(self._admin_path(self.config.admin_status_path), quote=True)
        install_path = escape(self._admin_path(self.config.admin_install_path), quote=True)
        config_root_path = escape(self._admin_path(self.config.admin_config_path), quote=True)
        frps_start_path = escape(self._admin_path(self.config.admin_frps_start_path), quote=True)
        frps_stop_path = escape(self._admin_path(self.config.admin_frps_stop_path), quote=True)
        frpc_start_path = escape(self._admin_path(self.config.admin_frpc_start_path), quote=True)
        frpc_stop_path = escape(self._admin_path(self.config.admin_frpc_stop_path), quote=True)
        frps_proxy_root = escape(self._proxy_root_path("frps"), quote=True)
        frpc_proxy_root = escape(self._proxy_root_path("frpc"), quote=True)
        return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>FRP Manager</title>
  <style>
    :root {{ color-scheme: light dark; }}
    html, body {{ margin: 0; min-height: 100%; font-family: \"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", sans-serif; }}
    body {{ background: #eef4fb; color: #102033; }}
    .frp-manager-shell {{ min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }}
    .frp-manager-topbar {{ padding: 20px 24px 18px; border-bottom: 1px solid rgba(148,163,184,0.2); background: linear-gradient(135deg, rgba(13,56,122,0.96), rgba(17,24,39,0.92)); color: #e2e8f0; }}
    .frp-manager-kicker {{ font-size: 11px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; color: #93c5fd; }}
    .frp-manager-title {{ margin-top: 8px; font-size: 26px; font-weight: 700; }}
    .frp-manager-desc {{ margin-top: 10px; max-width: 980px; font-size: 13px; line-height: 1.7; color: #dbeafe; }}
    .frp-manager-toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    .frp-manager-toolbar button {{ border: 0; border-radius: 12px; padding: 10px 14px; font-size: 13px; font-weight: 700; cursor: pointer; }}
    .frp-manager-install {{ background: #f59e0b; color: #111827; }}
    .frp-manager-primary {{ background: #22c55e; color: #052e16; }}
    .frp-manager-danger {{ background: #ef4444; color: #fff; }}
    .frp-manager-ghost {{ background: rgba(148,163,184,0.16); color: #e2e8f0; }}
    .frp-manager-main {{ min-height: 0; display: grid; grid-template-columns: 320px minmax(0, 1fr); }}
    .frp-manager-side {{ padding: 20px; border-right: 1px solid rgba(148,163,184,0.2); background: rgba(255,255,255,0.88); box-sizing: border-box; }}
    .frp-manager-status-card {{ border-radius: 16px; padding: 16px; background: #fff; border: 1px solid rgba(148,163,184,0.18); box-shadow: 0 16px 36px rgba(15,23,42,0.06); }}
    .frp-manager-status-card h2 {{ margin: 0; font-size: 16px; }}
    .frp-manager-status-line {{ margin-top: 10px; font-size: 13px; color: #334155; line-height: 1.7; white-space: pre-wrap; }}
    .frp-manager-status-message {{ margin-top: 12px; padding: 12px 14px; border-radius: 12px; background: rgba(226,232,240,0.72); color: #334155; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }}
    .frp-manager-content {{ min-width: 0; min-height: 0; padding: 18px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; background: linear-gradient(180deg, rgba(255,255,255,0.82), rgba(241,245,249,0.9)); box-sizing: border-box; }}
    .frp-manager-pane {{ min-width: 0; display: grid; grid-template-rows: auto auto minmax(280px, 1fr); gap: 12px; }}
    .frp-manager-card {{ border-radius: 16px; background: #fff; border: 1px solid rgba(148,163,184,0.18); box-shadow: 0 16px 36px rgba(15,23,42,0.06); overflow: hidden; }}
    .frp-manager-card-head {{ padding: 14px 16px; border-bottom: 1px solid rgba(148,163,184,0.16); display: flex; align-items: center; justify-content: space-between; gap: 10px; }}
    .frp-manager-card-head h3 {{ margin: 0; font-size: 15px; }}
    .frp-manager-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .frp-manager-actions button {{ border: 0; border-radius: 10px; padding: 8px 12px; font-size: 12px; font-weight: 700; cursor: pointer; }}
    .frp-manager-editor {{ width: 100%; min-height: 280px; border: 0; resize: vertical; box-sizing: border-box; padding: 14px 16px; font: 12px/1.7 \"Consolas\", \"SFMono-Regular\", monospace; color: #0f172a; background: #fff; }}
    .frp-manager-frame {{ width: 100%; height: 100%; min-height: 340px; border: 0; display: none; background: #fff; }}
    .frp-manager-placeholder {{ min-height: 340px; display: flex; align-items: center; justify-content: center; padding: 24px; color: #475569; font-size: 13px; line-height: 1.8; box-sizing: border-box; }}
    @media (max-width: 1080px) {{ .frp-manager-main {{ grid-template-columns: 1fr; }} .frp-manager-side {{ border-right: 0; border-bottom: 1px solid rgba(148,163,184,0.2); }} .frp-manager-content {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class=\"frp-manager-shell\" data-plugin-key=\"{plugin_key}\">
    <section class=\"frp-manager-topbar\">
      <div class=\"frp-manager-kicker\">Plugin</div>
      <div class=\"frp-manager-title\">FRP Manager</div>
      <div class=\"frp-manager-desc\">检测系统上的 frps / frpc；如果缺失，就从 GitHub 的最新 release 下载适配当前系统的发行包，解压后放到插件目录下的 frp/frps 与 frp/frpc 中。面板同时提供两个配置编辑器、启动停止按钮，以及各自的内置 Web UI 代理入口。</div>
      <div class=\"frp-manager-toolbar\">
        <button type=\"button\" id=\"frp-manager-install\" class=\"frp-manager-install\">安装缺失二进制</button>
        <button type=\"button\" id=\"frp-manager-refresh\" class=\"frp-manager-ghost\">刷新状态</button>
      </div>
    </section>
    <div class=\"frp-manager-main\">
      <aside class=\"frp-manager-side\">
        <section class=\"frp-manager-status-card\">
          <h2>运行状态</h2>
          <div id=\"frp-manager-status\" class=\"frp-manager-status-line\">正在检查 frps / frpc 状态...</div>
          <div id=\"frp-manager-message\" class=\"frp-manager-status-message\">等待状态返回...</div>
        </section>
      </aside>
      <section class=\"frp-manager-content\">
        <section class=\"frp-manager-pane\">
          <div class=\"frp-manager-card\">
            <div class=\"frp-manager-card-head\">
              <h3>frps.toml</h3>
              <div class=\"frp-manager-actions\">
                <button type=\"button\" id=\"frp-manager-save-frps\" class=\"frp-manager-ghost\">保存配置</button>
                <button type=\"button\" id=\"frp-manager-start-frps\" class=\"frp-manager-primary\">启动 frps</button>
                <button type=\"button\" id=\"frp-manager-stop-frps\" class=\"frp-manager-danger\">停止 frps</button>
              </div>
            </div>
            <textarea id=\"frp-manager-editor-frps\" class=\"frp-manager-editor\"></textarea>
          </div>
          <div class=\"frp-manager-card\">
            <div class=\"frp-manager-card-head\"><h3>frps Dashboard</h3></div>
            <iframe id=\"frp-manager-frps-frame\" class=\"frp-manager-frame\"></iframe>
            <div id=\"frp-manager-frps-placeholder\" class=\"frp-manager-placeholder\">frps 启动后，这里会显示它的内置 Dashboard。</div>
          </div>
        </section>
        <section class=\"frp-manager-pane\">
          <div class=\"frp-manager-card\">
            <div class=\"frp-manager-card-head\">
              <h3>frpc.toml</h3>
              <div class=\"frp-manager-actions\">
                <button type=\"button\" id=\"frp-manager-save-frpc\" class=\"frp-manager-ghost\">保存配置</button>
                <button type=\"button\" id=\"frp-manager-start-frpc\" class=\"frp-manager-primary\">启动 frpc</button>
                <button type=\"button\" id=\"frp-manager-stop-frpc\" class=\"frp-manager-danger\">停止 frpc</button>
              </div>
            </div>
            <textarea id=\"frp-manager-editor-frpc\" class=\"frp-manager-editor\"></textarea>
          </div>
          <div class=\"frp-manager-card\">
            <div class=\"frp-manager-card-head\"><h3>frpc Admin UI</h3></div>
            <iframe id=\"frp-manager-frpc-frame\" class=\"frp-manager-frame\"></iframe>
            <div id=\"frp-manager-frpc-placeholder\" class=\"frp-manager-placeholder\">frpc 启动后，这里会显示它的内置 Admin UI。</div>
          </div>
        </section>
      </section>
    </div>
  </div>

  <script>
    const endpoints = {{
      status: {json.dumps(status_path)},
      install: {json.dumps(install_path)},
      configRoot: {json.dumps(config_root_path)},
      frpsStart: {json.dumps(frps_start_path)},
      frpsStop: {json.dumps(frps_stop_path)},
      frpcStart: {json.dumps(frpc_start_path)},
      frpcStop: {json.dumps(frpc_stop_path)},
      frpsProxy: {json.dumps(frps_proxy_root)},
      frpcProxy: {json.dumps(frpc_proxy_root)},
    }};

    const statusEl = document.getElementById('frp-manager-status');
    const messageEl = document.getElementById('frp-manager-message');
    const frpsEditor = document.getElementById('frp-manager-editor-frps');
    const frpcEditor = document.getElementById('frp-manager-editor-frpc');
    const frpsFrame = document.getElementById('frp-manager-frps-frame');
    const frpcFrame = document.getElementById('frp-manager-frpc-frame');
    const frpsPlaceholder = document.getElementById('frp-manager-frps-placeholder');
    const frpcPlaceholder = document.getElementById('frp-manager-frpc-placeholder');

    async function requestJson(url, options) {{
      const response = await fetch(url, options);
      const payload = await response.json().catch(() => null);
      if (!response.ok) {{
        throw new Error(payload?.message || `HTTP ${{response.status}}`);
      }}
      return payload;
    }}

    function renderStatus(status) {{
      if (!status) return;
      statusEl.textContent = [
        `Platform: ${{status.host_platform}} (${{status.architecture}})`,
        `frps: ${{status.frps_installed ? status.frps_binary_source : 'missing'}} / ${{status.frps_running ? 'running' : 'stopped'}}`,
        `frpc: ${{status.frpc_installed ? status.frpc_binary_source : 'missing'}} / ${{status.frpc_running ? 'running' : 'stopped'}}`,
        `release: ${{status.installed_release_tag || 'n/a'}}`,
      ].join('\n');
      messageEl.textContent = status.message || 'ok';

      if (status.frps_running && status.frps_ui_proxy_path) {{
        frpsFrame.src = endpoints.frpsProxy + '/';
        frpsFrame.style.display = 'block';
        frpsPlaceholder.style.display = 'none';
      }} else {{
        frpsFrame.removeAttribute('src');
        frpsFrame.style.display = 'none';
        frpsPlaceholder.style.display = 'flex';
      }}

      if (status.frpc_running && status.frpc_ui_proxy_path) {{
        frpcFrame.src = endpoints.frpcProxy + '/';
        frpcFrame.style.display = 'block';
        frpcPlaceholder.style.display = 'none';
      }} else {{
        frpcFrame.removeAttribute('src');
        frpcFrame.style.display = 'none';
        frpcPlaceholder.style.display = 'flex';
      }}
    }}

    async function loadStatus() {{
      const status = await requestJson(endpoints.status);
      renderStatus(status);
      return status;
    }}

    async function loadConfig(target) {{
      const payload = await requestJson(`${{endpoints.configRoot}}/${{target}}`);
      if (target === 'frps') frpsEditor.value = payload.content || '';
      if (target === 'frpc') frpcEditor.value = payload.content || '';
    }}

    async function saveConfig(target) {{
      const editor = target === 'frps' ? frpsEditor : frpcEditor;
      const payload = await requestJson(`${{endpoints.configRoot}}/${{target}}`, {{
        method: 'POST',
        headers: {{ 'content-type': 'application/json' }},
        body: JSON.stringify({{ content: editor.value }}),
      }});
      if (payload?.message) messageEl.textContent = payload.message;
      if (payload?.status) renderStatus(payload.status);
    }}

    async function runAction(url) {{
      const payload = await requestJson(url, {{ method: 'POST' }});
      if (payload?.message) messageEl.textContent = payload.message;
      if (payload?.status) renderStatus(payload.status);
    }}

    document.getElementById('frp-manager-install').addEventListener('click', () => {{ void runAction(endpoints.install); }});
    document.getElementById('frp-manager-refresh').addEventListener('click', () => {{ void loadStatus(); }});
    document.getElementById('frp-manager-save-frps').addEventListener('click', () => {{ void saveConfig('frps'); }});
    document.getElementById('frp-manager-save-frpc').addEventListener('click', () => {{ void saveConfig('frpc'); }});
    document.getElementById('frp-manager-start-frps').addEventListener('click', () => {{ void runAction(endpoints.frpsStart); }});
    document.getElementById('frp-manager-stop-frps').addEventListener('click', () => {{ void runAction(endpoints.frpsStop); }});
    document.getElementById('frp-manager-start-frpc').addEventListener('click', () => {{ void runAction(endpoints.frpcStart); }});
    document.getElementById('frp-manager-stop-frpc').addEventListener('click', () => {{ void runAction(endpoints.frpcStop); }});

    (async function init() {{
      try {{
        await Promise.all([loadStatus(), loadConfig('frps'), loadConfig('frpc')]);
      }} catch (error) {{
        messageEl.textContent = String(error?.message || error || '加载失败');
      }}
    }})();
  </script>
</body>
</html>
"""


__all__ = [
    "FrpManagerPlugin",
    "FrpManagerPluginConfig",
    "FrpManagerStatusResponse",
    "FrpManagerActionResponse",
    "FrpManagerConfigResponse",
    "FrpManagerConfigRequest",
]