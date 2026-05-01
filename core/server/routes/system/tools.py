# -*- coding: utf-8 -*-
import asyncio
import contextlib
import mimetypes
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import threading
import time
import uuid
import zipfile
import psutil

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import Field

from core.constants import PROJECT_DIR
from core.utils.type_utils import AdvancedBaseModel

from ...app import get_resources, on_app_shutdown, on_before_app_created
from ...shared import AppSharedData
from .._office_preview import (
    office_preview_cache_key,
    office_preview_cache_paths,
    office_preview_kind,
    office_preview_payload,
    presentation_preview_payload,
)
from ...html_injection import html_response_from_path
from core.server.constants import SERVER_DIR
from core.server.data_types.config import Config


_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".env", ".html", ".css", ".scss", ".less",
    ".xml", ".csv", ".sql", ".sh", ".bat", ".ps1", ".java", ".c", ".cpp", ".h",
    ".hpp", ".go", ".rs", ".kt", ".swift", ".rb", ".php", ".log",
}

_terminal_sessions_lock = threading.Lock()
_terminal_session_ids: set[str] = set()
_terminal_sessions_by_id: dict[str, "_TerminalBaseSession"] = {}
_system_tools_snapshot_lock = threading.Lock()
_system_tools_snapshot_thread: threading.Thread | None = None
_system_tools_snapshot_stop = threading.Event()
_cached_process_snapshot: "ProcessListResponse | None" = None
_cached_port_snapshot: "PortListResponse | None" = None
_cached_process_snapshot_payload: dict[str, Any] | None = None
_cached_port_snapshot_payload: dict[str, Any] | None = None
_shared_process_snapshot_payload_cache: dict[str, Any] | None = None
_shared_process_snapshot_payload_cache_at = 0.0
_shared_port_snapshot_payload_cache: dict[str, Any] | None = None
_shared_port_snapshot_payload_cache_at = 0.0
_SYSTEM_TOOLS_SNAPSHOT_INTERVAL_SECONDS = 5.0
_SYSTEM_TOOLS_SHARED_CACHE_TTL_SECONDS = 1.0


def _get_shared() -> AppSharedData:
    return AppSharedData.Get()

def _internal_admin_path(path: str = "") -> str:
    return Config.GetConfig().server_config.get_internal_admin_path(path)

def _cache_is_fresh(updated_at: float, ttl_seconds: float) -> bool:
    return updated_at > 0 and (time.monotonic() - updated_at) <= max(float(ttl_seconds), 0.0)

def _shared_supports_local_mirror(shared: Any) -> bool:
    return getattr(shared, "cache_scope", None) == "cross-process"

class RootInfo(AdvancedBaseModel):
    key: str
    label: str
    path: str
    is_default: bool = False

class SystemToolsConfig(AdvancedBaseModel):
    platform: str
    websocket_path: str
    default_root: str
    default_terminal_path: str
    available_shells: list[dict[str, str]] = Field(default_factory=list)
    roots: list[RootInfo] = Field(default_factory=list)
    windows_terminal_backend: str | None = None
    terminal_available: bool = True
    terminal_unavailable_reason: str | None = None
    terminal_max_sessions: int = 6

class FileEntry(AdvancedBaseModel):
    name: str
    relative_path: str
    is_dir: bool
    size: int
    modified_at: str | None = None
    mime_type: str | None = None
    extension: str | None = None
    mode: str | None = None

class FileListResponse(AdvancedBaseModel):
    root: RootInfo
    current_path: str
    parent_path: str | None = None
    entries: list[FileEntry] = Field(default_factory=list)

class TextPreviewResponse(AdvancedBaseModel):
    root: RootInfo
    relative_path: str
    size: int
    mime_type: str | None = None
    encoding: str
    truncated: bool
    content: str

class TextWriteRequest(AdvancedBaseModel):
    content: str = ''
    encoding: str = 'utf-8'

class FileRenameRequest(AdvancedBaseModel):
    root: str | None = None
    path: str
    new_name: str

class FileTransferRequest(AdvancedBaseModel):
    source_root: str | None = None
    source_path: str
    target_root: str | None = None
    target_dir: str = ''
    target_name: str | None = None
    overwrite: bool = False

class FileExtractRequest(AdvancedBaseModel):
    root: str | None = None
    path: str
    target_dir: str | None = None
    overwrite: bool = False
    extractor: str | None = None  # one of: auto / 7z / tar / unzip / unrar / python

class ProcessEntry(AdvancedBaseModel):
    pid: int
    name: str | None = None
    status: str | None = None
    username: str | None = None
    cpu_percent: float | None = None
    memory_rss: int | None = None
    memory_percent: float | None = None
    create_time: str | None = None
    cmdline: list[str] = Field(default_factory=list)
    exe: str | None = None

class ProcessListResponse(AdvancedBaseModel):
    generated_at: str
    total: int
    truncated: bool = False
    items: list[ProcessEntry] = Field(default_factory=list)

class ProcessActionResponse(AdvancedBaseModel):
    pid: int
    action: str
    status: str
    name: str | None = None
    exit_code: int | None = None
    message: str | None = None

class PortEntry(AdvancedBaseModel):
    protocol: str
    local_address: str
    remote_address: str | None = None
    status: str | None = None
    pid: int | None = None
    process_name: str | None = None
    username: str | None = None
    cmdline: list[str] = Field(default_factory=list)

class PortListResponse(AdvancedBaseModel):
    generated_at: str
    total: int
    truncated: bool = False
    items: list[PortEntry] = Field(default_factory=list)


class _TerminalBaseSession:
    def __init__(self, *, shell_key: str, shell_command: str, cwd: Path, cols: int, rows: int):
        self.session_id = str(uuid.uuid4())
        self.shell_key = shell_key
        self.shell_command = shell_command
        self.cwd = cwd
        self.cols = max(40, int(cols or 120))
        self.rows = max(12, int(rows or 30))
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start_reader(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[dict[str, Any]]):
        def _push(event: dict[str, Any]):
            if loop.is_closed():
                return
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def _run():
            try:
                self._reader_loop(_push)
            except Exception as exc:
                _push({"type": "error", "message": str(exc)})
            finally:
                _push({"type": "exit", "code": self.exit_code()})

        self._reader_thread = threading.Thread(
            target=_run,
            name=f"system-terminal-{self.session_id[:8]}",
            daemon=True,
        )
        self._reader_thread.start()

    def _reader_loop(self, push):
        raise NotImplementedError

    def write(self, data: str):
        raise NotImplementedError

    def resize(self, cols: int, rows: int):
        raise NotImplementedError

    def is_alive(self) -> bool:
        raise NotImplementedError

    def close(self):
        self._stop_event.set()

    def exit_code(self) -> int | None:
        return None

class _UnixTerminalSession(_TerminalBaseSession):
    def __init__(self, *, shell_key: str, shell_command: str, cwd: Path, cols: int, rows: int):
        super().__init__(shell_key=shell_key, shell_command=shell_command, cwd=cwd, cols=cols, rows=rows)
        import fcntl
        import pty
        import termios

        self._fcntl = fcntl
        self._termios = termios
        self._master_fd, slave_fd = pty.openpty()   # type: ignore
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        self._process = subprocess.Popen(
            [shell_command],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(cwd),
            env=env,
            start_new_session=True,
        )
        os.close(slave_fd)
        self.resize(cols, rows)

    def _reader_loop(self, push):
        while not self._stop_event.is_set():
            try:
                chunk = os.read(self._master_fd, 4096)
            except OSError:
                break
            if not chunk:
                if not self.is_alive():
                    break
                continue
            push({"type": "output", "data": chunk.decode("utf-8", errors="replace")})

    def write(self, data: str):
        if not data:
            return
        os.write(self._master_fd, data.encode("utf-8", errors="ignore"))

    def resize(self, cols: int, rows: int):
        import struct

        self.cols = max(40, int(cols or self.cols))
        self.rows = max(12, int(rows or self.rows))
        try:
            payload = struct.pack("HHHH", self.rows, self.cols, 0, 0)
            self._fcntl.ioctl(self._master_fd, self._termios.TIOCSWINSZ, payload)   # type: ignore
        except Exception:
            pass

    def is_alive(self) -> bool:
        return self._process.poll() is None

    def close(self):
        super().close()
        with contextlib.suppress(Exception):
            if self.is_alive():
                self._process.terminate()
        with contextlib.suppress(Exception):
            os.close(self._master_fd)

    def exit_code(self) -> int | None:
        return self._process.poll()

class _WindowsTerminalSession(_TerminalBaseSession):
    def __init__(self, *, shell_key: str, shell_command: str, cwd: Path, cols: int, rows: int):
        super().__init__(shell_key=shell_key, shell_command=shell_command, cwd=cwd, cols=cols, rows=rows)
        from winpty import PTY  # type: ignore

        self._pty = PTY(self.cols, self.rows)
        self._pty.spawn(shell_command)  # type: ignore
        self.write(self._startup_command())

    def _startup_command(self) -> str:
        if self.shell_key == "cmd":
            return f'chcp 65001>nul & cd /d "{str(self.cwd)}"\r\n'
        if self.shell_key == "wsl":
            escaped = _windows_path_to_wsl(self.cwd).replace("'", r"'\''")
            return f"cd '{escaped}'\r\n"
        escaped = str(self.cwd).replace("'", "''")
        return (
            "$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
            "[Console]::InputEncoding=[System.Text.UTF8Encoding]::new(); "
            f"Set-Location -LiteralPath '{escaped}'\r\n"
        )

    def _reader_loop(self, push):
        while not self._stop_event.is_set():
            try:
                data = self._pty.read()
            except Exception:
                break
            if not data:
                if not self.is_alive():
                    break
                continue
            push({"type": "output", "data": data})

    def write(self, data: str):
        if not data:
            return
        self._pty.write(data)   # type: ignore

    def resize(self, cols: int, rows: int):
        self.cols = max(40, int(cols or self.cols))
        self.rows = max(12, int(rows or self.rows))
        with contextlib.suppress(Exception):
            self._pty.set_size(self.cols, self.rows)

    def is_alive(self) -> bool:
        with contextlib.suppress(Exception):
            return bool(self._pty.isalive())
        return False

    def close(self):
        super().close()
        with contextlib.suppress(Exception):
            self._pty.close()   # type: ignore

def _within_root(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_relative_path(value: str | None) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text in {"", ".", "/"}:
        return ""
    if text.startswith("/"):
        raise HTTPException(400, "路径必须为相对路径。")
    if len(text) >= 2 and text[1] == ":":
        raise HTTPException(400, "路径必须为相对路径。")
    parts = [part for part in text.split("/") if part not in {"", "."}]
    return "/".join(parts)


def _default_system_root_paths() -> list[str]:
    roots = [str(PROJECT_DIR), str(SERVER_DIR)]
    home = Path.home()
    for path in (home, home / "Desktop", home / "Downloads", home / "Documents"):
        roots.append(str(path))
    return roots


def _windows_path_to_wsl(path: Path) -> str:
    text = str(path)
    if len(text) >= 2 and text[1] == ":":
        drive = text[0].lower()
        suffix = text[2:].replace("\\", "/")
        return f"/mnt/{drive}{suffix}"
    return text.replace("\\", "/")


def _parse_root_paths() -> tuple[list[RootInfo], dict[str, Path], str, str, int]:
    cfg = Config.GetConfig().server_config
    raw_roots = list(getattr(cfg, "system_allowed_roots", None) or _default_system_root_paths())
    default_root_raw = str(getattr(cfg, "system_default_root", str(PROJECT_DIR)) or str(PROJECT_DIR))
    terminal_cwd_raw = str(getattr(cfg, "system_terminal_default_cwd", default_root_raw) or default_root_raw)
    max_sessions = max(1, int(getattr(cfg, "system_terminal_max_sessions", 6) or 6))

    for extra_root in _default_system_root_paths():
        if extra_root not in raw_roots:
            raw_roots.append(extra_root)

    normalized_paths: list[Path] = []
    for raw in raw_roots:
        try:
            path = Path(raw).expanduser().resolve()
        except Exception:
            continue
        if path.exists() and path.is_dir() and all(existing != path for existing in normalized_paths):
            normalized_paths.append(path)

    if not normalized_paths:
        normalized_paths = [PROJECT_DIR.resolve(), SERVER_DIR.resolve()]

    labels: dict[Path, tuple[str, str]] = {
        PROJECT_DIR.resolve(): ("workspace", "Workspace"),
        SERVER_DIR.resolve(): ("server", "Server"),
        Path.home().resolve(): ("home", "Home"),
        (Path.home() / "Desktop").resolve(): ("desktop", "Desktop"),
        (Path.home() / "Downloads").resolve(): ("downloads", "Downloads"),
        (Path.home() / "Documents").resolve(): ("documents", "Documents"),
    }
    roots: list[RootInfo] = []
    root_map: dict[str, Path] = {}
    counter = 1
    default_key = ""
    default_root_path = Path(default_root_raw).expanduser().resolve(strict=False)
    terminal_cwd_path = Path(terminal_cwd_raw).expanduser().resolve(strict=False)

    for path in normalized_paths:
        key, label = labels.get(path, (f"root{counter}", path.name or f"Root {counter}"))
        if key in root_map:
            key = f"root{counter}"
            label = path.name or f"Root {counter}"
        is_default = (not default_key and _within_root(path, default_root_path)) or path == default_root_path
        roots.append(RootInfo(key=key, label=label, path=str(path), is_default=is_default))
        root_map[key] = path
        if is_default and not default_key:
            default_key = key
        counter += 1

    if not default_key:
        default_key = roots[0].key
        roots[0].is_default = True

    terminal_default_relative = ""
    default_root_path_obj = root_map[default_key]
    if terminal_cwd_path.exists() and terminal_cwd_path.is_dir() and _within_root(default_root_path_obj, terminal_cwd_path):
        with contextlib.suppress(ValueError):
            terminal_default_relative = terminal_cwd_path.relative_to(default_root_path_obj).as_posix()

    return roots, root_map, default_key, terminal_default_relative, max_sessions


def _pick_root(root_key: str | None) -> tuple[RootInfo, Path]:
    roots, root_map, default_key, _default_terminal_path, _max_sessions = _parse_root_paths()
    key = root_key or default_key
    if key not in root_map:
        raise HTTPException(400, f"未知根目录: {key}")
    root_info = next(root for root in roots if root.key == key)
    return root_info, root_map[key]


def _resolve_target(root_key: str | None, relative_path: str | None, *, must_exist: bool = True, expect_dir: bool | None = None) -> tuple[RootInfo, Path, str]:
    root_info, root_path = _pick_root(root_key)
    normalized = _normalize_relative_path(relative_path)
    target = (root_path / normalized).resolve(strict=False)
    if not _within_root(root_path, target):
        raise HTTPException(403, "目标路径超出允许范围。")
    if must_exist and not target.exists():
        raise HTTPException(404, "目标路径不存在。")
    if expect_dir is True and target.exists() and not target.is_dir():
        raise HTTPException(400, "目标不是目录。")
    if expect_dir is False and target.exists() and not target.is_file():
        raise HTTPException(400, "目标不是文件。")
    return root_info, target, normalized


def _format_mode(path: Path) -> str | None:
    with contextlib.suppress(Exception):
        return stat.filemode(path.stat().st_mode)
    return None


def _file_entry(root_path: Path, item: Path) -> FileEntry:
    stat_result = item.stat()
    relative_path = item.relative_to(root_path).as_posix()
    mime_type, _ = mimetypes.guess_type(str(item))
    return FileEntry(
        name=item.name,
        relative_path=relative_path,
        is_dir=item.is_dir(),
        size=0 if item.is_dir() else int(stat_result.st_size),
        modified_at=datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
        mime_type=mime_type,
        extension=item.suffix.lower() or None,
        mode=_format_mode(item),
    )


def _is_text_file(path: Path, mime_type: str | None) -> bool:
    if mime_type and (mime_type.startswith("text/") or mime_type in {"application/json", "application/xml", "application/javascript"}):
        return True
    return path.suffix.lower() in _TEXT_EXTENSIONS


_SEVENZIP_DEFAULT_PATHS = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
    "/usr/bin/7z",
    "/usr/local/bin/7z",
    "/opt/homebrew/bin/7z",
)


def _find_executable(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _find_seven_zip() -> str | None:
    found = _find_executable("7z", "7za", "7z.exe", "7za.exe")
    if found:
        return found
    for candidate in _SEVENZIP_DEFAULT_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def _find_winrar() -> str | None:
    found = _find_executable("unrar", "unrar.exe", "UnRAR.exe")
    if found:
        return found
    for candidate in (r"C:\Program Files\WinRAR\UnRAR.exe", r"C:\Program Files (x86)\WinRAR\UnRAR.exe"):
        if Path(candidate).exists():
            return candidate
    return None


def _archive_kind(target: Path) -> str | None:
    """Return one of: zip / tar / tar.gz / tar.bz2 / tar.xz / 7z / rar / None."""
    name_lower = target.name.lower()
    if name_lower.endswith('.tar.gz') or name_lower.endswith('.tgz'):
        return 'tar.gz'
    if name_lower.endswith('.tar.bz2') or name_lower.endswith('.tbz2'):
        return 'tar.bz2'
    if name_lower.endswith('.tar.xz') or name_lower.endswith('.txz'):
        return 'tar.xz'
    if name_lower.endswith('.tar'):
        return 'tar'
    if name_lower.endswith('.zip'):
        return 'zip'
    if name_lower.endswith('.7z'):
        return '7z'
    if name_lower.endswith('.rar'):
        return 'rar'
    # Fallback by signature
    with contextlib.suppress(Exception):
        if zipfile.is_zipfile(target):
            return 'zip'
    with contextlib.suppress(Exception):
        if tarfile.is_tarfile(target):
            return 'tar'
    return None


def _build_python_extract_script(target: Path, dest_dir: Path, kind: str) -> str:
    """Build a self-contained python -c script that extracts to dest_dir with traversal checks."""
    return (
        "import sys, os, zipfile, tarfile\n"
        f"target = {repr(str(target))}\n"
        f"dest = {repr(str(dest_dir))}\n"
        f"kind = {repr(kind)}\n"
        "os.makedirs(dest, exist_ok=True)\n"
        "dest_real = os.path.realpath(dest)\n"
        "def safe(member_name):\n"
        "    target_path = os.path.realpath(os.path.join(dest, member_name))\n"
        "    if not (target_path == dest_real or target_path.startswith(dest_real + os.sep)):\n"
        "        raise SystemExit('archive contains illegal path: ' + member_name)\n"
        "if kind == 'zip':\n"
        "    with zipfile.ZipFile(target) as ar:\n"
        "        for m in ar.namelist(): safe(m)\n"
        "        ar.extractall(dest)\n"
        "else:\n"
        "    with tarfile.open(target) as ar:\n"
        "        for m in ar.getmembers(): safe(m.name)\n"
        "        ar.extractall(dest)\n"
    )


def _extractor_candidates(kind: str, target: Path, dest_dir: Path) -> list[tuple[str, list[str]]]:
    """Return ordered list of (label, argv) candidates for extracting target into dest_dir."""
    candidates: list[tuple[str, list[str]]] = []
    seven_zip = _find_seven_zip()
    sys_tar = _find_executable("tar", "tar.exe")
    unzip = _find_executable("unzip", "unzip.exe")
    unrar = _find_winrar()

    if kind == 'zip':
        if seven_zip:
            candidates.append(('7z', [seven_zip, 'x', str(target), f'-o{dest_dir}', '-y']))
        if unzip:
            candidates.append(('unzip', [unzip, '-o', str(target), '-d', str(dest_dir)]))
    elif kind in ('tar', 'tar.gz', 'tar.bz2', 'tar.xz'):
        if sys_tar:
            candidates.append(('tar', [sys_tar, '-xf', str(target), '-C', str(dest_dir)]))
        if seven_zip:
            # 7z needs two passes for tar.gz/etc, but for plain .tar one pass is fine.
            if kind == 'tar':
                candidates.append(('7z', [seven_zip, 'x', str(target), f'-o{dest_dir}', '-y']))
    elif kind == '7z':
        if seven_zip:
            candidates.append(('7z', [seven_zip, 'x', str(target), f'-o{dest_dir}', '-y']))
    elif kind == 'rar':
        if unrar:
            candidates.append(('unrar', [unrar, 'x', '-o+', str(target), str(dest_dir) + os.sep]))
        if seven_zip:
            candidates.append(('7z', [seven_zip, 'x', str(target), f'-o{dest_dir}', '-y']))

    if kind in ('zip', 'tar'):
        candidates.append((
            'python',
            [sys.executable, '-c', _build_python_extract_script(target, dest_dir, kind)],
        ))
    return candidates


def _archive_default_target_name(target: Path) -> str:
    name = target.name
    for suffix in ('.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.tbz2', '.txz'):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)] or 'extracted'
    stem = target.stem
    return stem or 'extracted'


def _decode_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "gb18030", "big5"):
        try:
            return data.decode(encoding), encoding
        except Exception:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8(replace)"


def _system_file_target(root_key: str | None, relative_path: str | None) -> tuple[RootInfo, Path, str, bytes, str | None]:
    root_info, target, normalized = _resolve_target(root_key, relative_path, must_exist=True, expect_dir=False)
    if not target.is_file():
        raise HTTPException(400, '目标不是文件。')
    mime_type, _ = mimetypes.guess_type(str(target))
    return root_info, target, normalized, target.read_bytes(), mime_type


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_psutil_call(func, default=None):
    try:
        return func()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ProcessLookupError):
        return default


def _normalize_cmdline(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return [str(value)]
    return [str(item) for item in value if str(item or "").strip()]


def _timestamp_to_iso(value: float | int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value)).isoformat(timespec="seconds")
    except Exception:
        return None


def _snapshot_payload(snapshot: ProcessListResponse | PortListResponse) -> dict[str, Any]:
    return snapshot.model_dump(mode="python")


def _set_shared_process_snapshot(payload: dict[str, Any] | None) -> None:
    if os.getenv("__APP_SHUTTING_DOWN__", "").strip().lower() in {"1", "true", "yes"}:
        return
    try:
        setter = getattr(_get_shared(), "set_process_snapshot", None)
        if callable(setter):
            setter(payload)
    except (BrokenPipeError, ConnectionError, ConnectionResetError, EOFError, OSError):
        if not _system_tools_snapshot_stop.is_set():
            _system_tools_snapshot_stop.set()


def _set_shared_port_snapshot(payload: dict[str, Any] | None) -> None:
    if os.getenv("__APP_SHUTTING_DOWN__", "").strip().lower() in {"1", "true", "yes"}:
        return
    try:
        setter = getattr(_get_shared(), "set_port_snapshot", None)
        if callable(setter):
            setter(payload)
    except (BrokenPipeError, ConnectionError, ConnectionResetError, EOFError, OSError):
        if not _system_tools_snapshot_stop.is_set():
            _system_tools_snapshot_stop.set()


def _get_shared_process_snapshot_payload() -> dict[str, Any] | None:
    getter = getattr(_get_shared(), "get_process_snapshot", None)
    if not callable(getter):
        return None
    payload = getter()
    return payload if isinstance(payload, dict) else None


def _get_shared_port_snapshot_payload() -> dict[str, Any] | None:
    getter = getattr(_get_shared(), "get_port_snapshot", None)
    if not callable(getter):
        return None
    payload = getter()
    return payload if isinstance(payload, dict) else None


def _copy_process_snapshot_payload() -> dict[str, Any] | None:
    global _shared_process_snapshot_payload_cache, _shared_process_snapshot_payload_cache_at
    shared = _get_shared()
    use_local_mirror = _shared_supports_local_mirror(shared)
    with _system_tools_snapshot_lock:
        if _cached_process_snapshot_payload is not None:
            return _cached_process_snapshot_payload
        if use_local_mirror and _cache_is_fresh(_shared_process_snapshot_payload_cache_at, _SYSTEM_TOOLS_SHARED_CACHE_TTL_SECONDS):
            return _shared_process_snapshot_payload_cache
    getter = getattr(shared, "get_process_snapshot", None)
    shared_payload = getter() if callable(getter) else None
    if isinstance(shared_payload, dict):
        if use_local_mirror:
            with _system_tools_snapshot_lock:
                _shared_process_snapshot_payload_cache = shared_payload
                _shared_process_snapshot_payload_cache_at = time.monotonic()
        return shared_payload
    return None


def _copy_port_snapshot_payload() -> dict[str, Any] | None:
    global _shared_port_snapshot_payload_cache, _shared_port_snapshot_payload_cache_at
    shared = _get_shared()
    use_local_mirror = _shared_supports_local_mirror(shared)
    with _system_tools_snapshot_lock:
        if _cached_port_snapshot_payload is not None:
            return _cached_port_snapshot_payload
        if use_local_mirror and _cache_is_fresh(_shared_port_snapshot_payload_cache_at, _SYSTEM_TOOLS_SHARED_CACHE_TTL_SECONDS):
            return _shared_port_snapshot_payload_cache
    getter = getattr(shared, "get_port_snapshot", None)
    shared_payload = getter() if callable(getter) else None
    if isinstance(shared_payload, dict):
        if use_local_mirror:
            with _system_tools_snapshot_lock:
                _shared_port_snapshot_payload_cache = shared_payload
                _shared_port_snapshot_payload_cache_at = time.monotonic()
        return shared_payload
    return None


def _get_or_collect_process_snapshot_payload() -> dict[str, Any]:
    snapshot = _copy_process_snapshot_payload()
    if snapshot is not None:
        return snapshot
    snapshot = _collect_process_snapshot()
    payload = _snapshot_payload(snapshot)
    with _system_tools_snapshot_lock:
        global _cached_process_snapshot, _cached_process_snapshot_payload
        if _cached_process_snapshot is None:
            _cached_process_snapshot = snapshot
            _cached_process_snapshot_payload = payload
        cached = _cached_process_snapshot_payload or payload
    _set_shared_process_snapshot(cached)
    return cached


def _get_or_collect_port_snapshot_payload() -> dict[str, Any]:
    snapshot = _copy_port_snapshot_payload()
    if snapshot is not None:
        return snapshot
    snapshot = _collect_port_snapshot()
    payload = _snapshot_payload(snapshot)
    with _system_tools_snapshot_lock:
        global _cached_port_snapshot, _cached_port_snapshot_payload
        if _cached_port_snapshot is None:
            _cached_port_snapshot = snapshot
            _cached_port_snapshot_payload = payload
        cached = _cached_port_snapshot_payload or payload
    _set_shared_port_snapshot(cached)
    return cached


def _refresh_port_snapshot_payload() -> dict[str, Any]:
    snapshot = _collect_port_snapshot()
    payload = _snapshot_payload(snapshot)
    with _system_tools_snapshot_lock:
        global _cached_port_snapshot, _cached_port_snapshot_payload
        _cached_port_snapshot = snapshot
        _cached_port_snapshot_payload = payload
        _set_shared_port_snapshot(payload)
        return _cached_port_snapshot_payload


def _build_process_entry(
    proc: psutil.Process,
    *,
    include_cmdline: bool = True,
    include_exe: bool = True,
) -> ProcessEntry | None:
    try:
        pid = int(proc.pid)
    except (psutil.NoSuchProcess, ProcessLookupError):
        return None

    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        with proc.oneshot():
            memory_info = _safe_psutil_call(proc.memory_info)
            return ProcessEntry(
                pid=pid,
                name=_safe_psutil_call(proc.name),
                status=_safe_psutil_call(proc.status),
                username=_safe_psutil_call(proc.username),
                cpu_percent=_safe_psutil_call(proc.cpu_percent, 0.0),
                memory_rss=int(getattr(memory_info, "rss", 0) or 0),
                memory_percent=_safe_psutil_call(proc.memory_percent, 0.0),
                create_time=_timestamp_to_iso(_safe_psutil_call(proc.create_time)),
                cmdline=_normalize_cmdline(_safe_psutil_call(proc.cmdline) if include_cmdline else []),
                exe=_safe_psutil_call(proc.exe) if include_exe else None,
            )

    memory_info = _safe_psutil_call(proc.memory_info)
    return ProcessEntry(
        pid=pid,
        name=_safe_psutil_call(proc.name),
        status=_safe_psutil_call(proc.status),
        username=_safe_psutil_call(proc.username),
        cpu_percent=_safe_psutil_call(proc.cpu_percent, 0.0),
        memory_rss=int(getattr(memory_info, "rss", 0) or 0),
        memory_percent=_safe_psutil_call(proc.memory_percent, 0.0),
        create_time=_timestamp_to_iso(_safe_psutil_call(proc.create_time)),
        cmdline=_normalize_cmdline(_safe_psutil_call(proc.cmdline) if include_cmdline else []),
        exe=_safe_psutil_call(proc.exe) if include_exe else None,
    )


def _collect_process_snapshot() -> ProcessListResponse:
    items: list[ProcessEntry] = []
    for proc in psutil.process_iter():
        try:
            pid = int(proc.pid)
        except (psutil.NoSuchProcess, ProcessLookupError):
            continue

        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            with proc.oneshot():
                memory_info = _safe_psutil_call(proc.memory_info)
                items.append(ProcessEntry(
                    pid=pid,
                    name=_safe_psutil_call(proc.name),
                    status=None,
                    username=_safe_psutil_call(proc.username),
                    cpu_percent=_safe_psutil_call(proc.cpu_percent, 0.0),
                    memory_rss=int(getattr(memory_info, "rss", 0) or 0),
                    memory_percent=None,
                    create_time=_timestamp_to_iso(_safe_psutil_call(proc.create_time)),
                    cmdline=[],
                    exe=None,
                ))
    items.sort(key=lambda item: (item.pid, (item.name or "").lower()))
    return ProcessListResponse(
        generated_at=_now_iso(),
        total=len(items),
        truncated=False,
        items=items,
    )


def _read_process_detail(pid: int) -> ProcessEntry | None:
    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
        return None
    return _build_process_entry(proc, include_cmdline=True, include_exe=True)


def _snapshot_entry_value(entry: ProcessEntry | PortEntry | dict[str, Any], key: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(key)
    return getattr(entry, key, None)


def _process_entry_from_payload(entry: ProcessEntry | dict[str, Any]) -> ProcessEntry:
    if isinstance(entry, ProcessEntry):
        return entry
    return ProcessEntry.model_validate(entry)


def _port_entry_from_payload(entry: PortEntry | dict[str, Any]) -> PortEntry:
    if isinstance(entry, PortEntry):
        return entry
    return PortEntry.model_validate(entry)


def _hydrate_process_entries(items: list[ProcessEntry | dict[str, Any]]) -> list[ProcessEntry]:
    hydrated: list[ProcessEntry] = []
    for item in items:
        current = _process_entry_from_payload(item)
        detail = _read_process_detail(current.pid)
        hydrated.append(detail or current)
    return hydrated


def _match_process(entry: ProcessEntry | dict[str, Any], search: str | None) -> bool:
    keyword = str(search or "").strip().lower()
    if not keyword:
        return True
    cmdline = _snapshot_entry_value(entry, "cmdline") or []
    haystacks = [
        str(_snapshot_entry_value(entry, "pid") or ""),
        str(_snapshot_entry_value(entry, "name") or ""),
        str(_snapshot_entry_value(entry, "status") or ""),
        str(_snapshot_entry_value(entry, "username") or ""),
        str(_snapshot_entry_value(entry, "exe") or ""),
        " ".join(str(item) for item in cmdline),
    ]
    return any(keyword in item.lower() for item in haystacks)


def _protect_process_action(pid: int):
    if pid <= 0:
        raise HTTPException(400, "pid 必须为正整数。")
    if pid == os.getpid():
        raise HTTPException(403, "不允许操作当前服务进程。")


def _wait_process_exit(proc: psutil.Process, timeout: float) -> int | None:
    return proc.wait(timeout=timeout)


def _execute_process_action(pid: int, action: str, *, wait_timeout: float) -> ProcessActionResponse:
    _protect_process_action(pid)
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess as exc:
        raise HTTPException(404, f"进程不存在: {pid}") from exc
    except psutil.AccessDenied as exc:
        raise HTTPException(403, f"无权访问进程: {pid}") from exc

    proc_name = _safe_psutil_call(proc.name)
    try:
        if action == "terminate":
            proc.terminate()
        elif action == "kill":
            proc.kill()
        else:
            raise HTTPException(400, f"不支持的操作: {action}")
    except psutil.NoSuchProcess:
        return ProcessActionResponse(
            pid=pid,
            name=proc_name,
            action=action,
            status="already_exited",
            message="进程在操作前已经退出。",
        )
    except psutil.AccessDenied as exc:
        raise HTTPException(403, f"无权执行 {action} 操作: {pid}") from exc

    try:
        exit_code = _wait_process_exit(proc, wait_timeout)
    except psutil.TimeoutExpired as exc:
        raise HTTPException(409, f"已发送 {action} 请求，但进程在 {wait_timeout:.1f}s 内未退出。") from exc
    except psutil.NoSuchProcess:
        exit_code = None

    return ProcessActionResponse(
        pid=pid,
        name=proc_name,
        action=action,
        status="completed",
        exit_code=exit_code,
        message=f"进程已执行 {action}。",
    )


def _format_address(value: Any) -> str:
    if not value:
        return ""
    host = getattr(value, "ip", None)
    port = getattr(value, "port", None)
    if host is None and isinstance(value, tuple):
        host = value[0] if len(value) > 0 else ""
        port = value[1] if len(value) > 1 else None
    host_text = str(host or "")
    if port in {None, ""}:
        return host_text
    if ":" in host_text and not host_text.startswith("["):
        host_text = f"[{host_text}]"
    return f"{host_text}:{port}"


def _connection_protocol(conn: Any) -> str:
    family = getattr(conn, "family", None)
    sock_type = getattr(conn, "type", None)
    base = "tcp" if sock_type == socket.SOCK_STREAM else "udp"
    suffix = "6" if family == socket.AF_INET6 else "4"
    return f"{base}{suffix}"


def _port_is_listening(conn: Any) -> bool:
    status = str(getattr(conn, "status", "") or "").upper()
    if status == "LISTEN":
        return True
    if getattr(conn, "type", None) == socket.SOCK_DGRAM and getattr(conn, "laddr", None) and not getattr(conn, "raddr", None):
        return True
    return False


def _get_process_brief(pid: int | None, *, include_cmdline: bool = False, cache: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    if pid is None:
        return {"process_name": None, "username": None, "cmdline": []}
    if cache is not None and pid in cache:
        return cache[pid]
    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
        info = {"process_name": None, "username": None, "cmdline": []}
        if cache is not None:
            cache[pid] = info
        return info

    info = {
        "process_name": _safe_psutil_call(proc.name),
        "username": _safe_psutil_call(proc.username),
        "cmdline": _normalize_cmdline(_safe_psutil_call(proc.cmdline) if include_cmdline else []),
    }
    if cache is not None:
        cache[pid] = info
    return info


def _collect_port_snapshot() -> PortListResponse:
    try:
        raw_connections = psutil.net_connections(kind="inet")
    except psutil.AccessDenied as exc:
        raise HTTPException(503, "当前环境无权限枚举网络连接。") from exc
    except Exception as exc:
        raise HTTPException(500, f"读取网络连接失败: {exc}") from exc

    process_cache: dict[int, dict[str, Any]] = {}
    items: list[PortEntry] = []
    for conn in raw_connections:
        pid = getattr(conn, "pid", None)
        proc_info = _get_process_brief(pid, include_cmdline=False, cache=process_cache)
        status = str(getattr(conn, "status", "") or "").upper() or None
        if status is None and _port_is_listening(conn):
            status = "LISTEN"
        items.append(PortEntry(
            protocol=_connection_protocol(conn),
            local_address=_format_address(getattr(conn, "laddr", None)),
            remote_address=_format_address(getattr(conn, "raddr", None)) or None,
            status=status,
            pid=pid,
            process_name=proc_info.get("process_name"),
            username=proc_info.get("username"),
            cmdline=[],
        ))

    items.sort(key=lambda item: ((item.status or "") != "LISTEN", item.local_address, item.pid or -1, item.protocol))
    return PortListResponse(
        generated_at=_now_iso(),
        total=len(items),
        truncated=False,
        items=items,
    )


def _hydrate_port_entries(items: list[PortEntry | dict[str, Any]]) -> list[PortEntry]:
    process_cache: dict[int, dict[str, Any]] = {}
    hydrated: list[PortEntry] = []
    for item in items:
        current = _port_entry_from_payload(item)
        proc_info = _get_process_brief(current.pid, include_cmdline=True, cache=process_cache)
        hydrated.append(current.model_copy(update={
            "username": current.username or proc_info.get("username"),
            "cmdline": proc_info.get("cmdline") or [],
        }))
    return hydrated


def _refresh_system_tools_snapshots() -> None:
    process_snapshot: ProcessListResponse | None = None
    port_snapshot: PortListResponse | None = None
    try:
        process_snapshot = _collect_process_snapshot()
    except Exception:
        process_snapshot = None
    try:
        port_snapshot = _collect_port_snapshot()
    except Exception:
        port_snapshot = None
    with _system_tools_snapshot_lock:
        global _cached_process_snapshot, _cached_port_snapshot
        global _cached_process_snapshot_payload, _cached_port_snapshot_payload
        if process_snapshot is not None:
            _cached_process_snapshot = process_snapshot
            _cached_process_snapshot_payload = _snapshot_payload(process_snapshot)
        if port_snapshot is not None:
            _cached_port_snapshot = port_snapshot
            _cached_port_snapshot_payload = _snapshot_payload(port_snapshot)
    if process_snapshot is not None:
        _set_shared_process_snapshot(_cached_process_snapshot_payload)
    if port_snapshot is not None:
        _set_shared_port_snapshot(_cached_port_snapshot_payload)


def _system_tools_snapshot_loop() -> None:
    while not _system_tools_snapshot_stop.is_set():
        _refresh_system_tools_snapshots()
        if _system_tools_snapshot_stop.wait(_SYSTEM_TOOLS_SNAPSHOT_INTERVAL_SECONDS):
            break


def start_system_tools_snapshot_cache(app: FastAPI | None = None) -> None:
    global _system_tools_snapshot_thread
    if _system_tools_snapshot_thread is not None and _system_tools_snapshot_thread.is_alive():
        return
    _system_tools_snapshot_stop.clear()
    _system_tools_snapshot_thread = threading.Thread(
        target=_system_tools_snapshot_loop,
        name="kp-system-tools-snapshot",
        daemon=True,
    )
    _system_tools_snapshot_thread.start()


def stop_system_tools_snapshot_cache(app: FastAPI | None = None) -> None:
    _system_tools_snapshot_stop.set()


def start_main_process_system_tools_refresh() -> None:
    start_system_tools_snapshot_cache()


def stop_main_process_system_tools_refresh() -> None:
    stop_system_tools_snapshot_cache()


@on_app_shutdown
def close_system_tools_worker_resources(app: FastAPI) -> None:
    _close_all_terminal_sessions()


def _match_port(entry: PortEntry | dict[str, Any], search: str | None) -> bool:
    keyword = str(search or "").strip().lower()
    if not keyword:
        return True
    pid = _snapshot_entry_value(entry, "pid")
    cmdline = _snapshot_entry_value(entry, "cmdline") or []
    if keyword.isdigit():
        if str(pid or "") == keyword:
            return True
        for address in (
            str(_snapshot_entry_value(entry, "local_address") or ""),
            str(_snapshot_entry_value(entry, "remote_address") or ""),
        ):
            if _address_port_equals(address, keyword):
                return True
        haystacks = [
            str(_snapshot_entry_value(entry, "process_name") or ""),
            str(_snapshot_entry_value(entry, "username") or ""),
            " ".join(str(item) for item in cmdline),
        ]
        return any(keyword in item.lower() for item in haystacks)
    haystacks = [
        str(_snapshot_entry_value(entry, "protocol") or ""),
        str(_snapshot_entry_value(entry, "local_address") or ""),
        str(_snapshot_entry_value(entry, "remote_address") or ""),
        str(_snapshot_entry_value(entry, "status") or ""),
        str(pid or ""),
        str(_snapshot_entry_value(entry, "process_name") or ""),
        str(_snapshot_entry_value(entry, "username") or ""),
        " ".join(str(item) for item in cmdline),
    ]
    return any(keyword in item.lower() for item in haystacks)


def _address_port_equals(address: str | None, keyword: str) -> bool:
    text = str(address or "").strip()
    if not text or not keyword:
        return False
    if text.startswith("[") and "]:" in text:
        port_text = text.rsplit("]:", 1)[-1]
    elif ":" in text:
        port_text = text.rsplit(":", 1)[-1]
    else:
        return False
    return port_text == keyword


def _list_shells() -> list[dict[str, str]]:
    if os.name == "nt":
        shells = []
        for key, candidates, label in (
            ("powershell", ["powershell.exe", "powershell"], "PowerShell"),
            ("cmd", ["cmd.exe", "cmd"], "Command Prompt"),
            ("wsl", ["wsl.exe", "wsl"], "WSL"),
        ):
            for candidate in candidates:
                resolved = shutil.which(candidate)
                if resolved:
                    shells.append({"key": key, "label": label, "command": resolved})
                    break
        return shells

    shells = []
    for key, candidates, label in (
        ("bash", ["bash"], "Bash"),
        ("sh", ["sh"], "POSIX Shell"),
    ):
        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                shells.append({"key": key, "label": label, "command": resolved})
                break
    return shells


def _terminal_backend_status() -> tuple[bool, str | None, str | None]:
    if os.name != "nt":
        return True, None, None
    with contextlib.suppress(Exception):
        import winpty  # noqa: F401

        return True, "pywinpty", None
    return False, None, "Windows 交互式终端依赖 pywinpty，当前环境尚未安装。"


def _build_system_tools_config() -> SystemToolsConfig:
    roots, _root_map, default_key, default_terminal_path, max_sessions = _parse_root_paths()
    available_shells = _list_shells()
    terminal_available, backend_name, reason = _terminal_backend_status()
    if not available_shells:
        terminal_available = False
        reason = reason or "当前系统未找到可用 shell。"
    return SystemToolsConfig(
        platform=platform.system().lower(),
        websocket_path=_internal_admin_path("ws/panel/system/terminal"),
        default_root=default_key,
        default_terminal_path=default_terminal_path,
        available_shells=available_shells,
        roots=roots,
        windows_terminal_backend=backend_name,
        terminal_available=terminal_available,
        terminal_unavailable_reason=reason,
        terminal_max_sessions=max_sessions,
    )


def _create_terminal_session(shell_key: str, shell_command: str, cwd: Path, cols: int, rows: int) -> _TerminalBaseSession:
    if os.name == "nt":
        return _WindowsTerminalSession(shell_key=shell_key, shell_command=shell_command, cwd=cwd, cols=cols, rows=rows)
    return _UnixTerminalSession(shell_key=shell_key, shell_command=shell_command, cwd=cwd, cols=cols, rows=rows)


def _register_terminal_session(session_id: str, max_sessions: int):
    with _terminal_sessions_lock:
        if len(_terminal_session_ids) >= max_sessions:
            raise RuntimeError(f"终端会话数已达到上限 ({max_sessions})。")
        _terminal_session_ids.add(session_id)


def _track_terminal_session(session: _TerminalBaseSession):
    with _terminal_sessions_lock:
        _terminal_sessions_by_id[session.session_id] = session


def _unregister_terminal_session(session_id: str):
    with _terminal_sessions_lock:
        _terminal_session_ids.discard(session_id)
        _terminal_sessions_by_id.pop(session_id, None)


def _close_all_terminal_sessions():
    with _terminal_sessions_lock:
        sessions = list(_terminal_sessions_by_id.values())
        _terminal_sessions_by_id.clear()
        _terminal_session_ids.clear()
    for session in sessions:
        with contextlib.suppress(Exception):
            session.close()


@on_before_app_created
def register_system_tools_routes(app: FastAPI):
    terminal_html_path = get_resources("admin-panel", "panel", "system_terminal.html") or Path("system_terminal.html")
    files_html_path = get_resources("admin-panel", "panel", "system_files.html") or Path("system_files.html")
    processes_html_path = get_resources("admin-panel", "panel", "system_processes.html") or Path("system_processes.html")
    ports_html_path = get_resources("admin-panel", "panel", "system_ports.html") or Path("system_ports.html")

    @app.get("/admin/panel/system/terminal", response_class=HTMLResponse)
    async def panel_system_terminal_html():
        return html_response_from_path(
            terminal_html_path,
            not_found_message="panel/system_terminal.html not found",
        )

    @app.get("/admin/panel/system/files", response_class=HTMLResponse)
    async def panel_system_files_html():
        return html_response_from_path(
            files_html_path,
            not_found_message="panel/system_files.html not found",
        )

    @app.get("/admin/panel/system/processes", response_class=HTMLResponse)
    async def panel_system_processes_html():
        return html_response_from_path(
            processes_html_path,
            not_found_message="panel/system_processes.html not found",
        )

    @app.get("/admin/panel/system/ports", response_class=HTMLResponse)
    async def panel_system_ports_html():
        return html_response_from_path(
            ports_html_path,
            not_found_message="panel/system_ports.html not found",
        )

    @app.get("/admin/api/system/tools/config", response_model=SystemToolsConfig)
    async def system_tools_config() -> SystemToolsConfig:
        return _build_system_tools_config()

    @app.get("/admin/api/system/processes", response_model=ProcessListResponse)
    async def system_processes_list(
        search: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
        include_cmdline: bool = Query(default=False),
    ) -> ProcessListResponse:
        def _collect() -> ProcessListResponse:
            snapshot = _get_or_collect_process_snapshot_payload()
            source_items = list(snapshot.get("items") or [])
            items = [item for item in source_items if _match_process(item, search)]
            total = len(items)
            truncated = total > limit
            limited = items[:limit]
            if include_cmdline:
                limited = _hydrate_process_entries(limited)
            else:
                limited = [_process_entry_from_payload(item) for item in limited]
            return ProcessListResponse(
                generated_at=str(snapshot.get("generated_at") or _now_iso()),
                total=total,
                truncated=truncated,
                items=limited,
            )
        return await asyncio.to_thread(_collect)

    @app.get("/admin/api/system/processes/{pid}", response_model=ProcessEntry)
    async def system_process_detail(pid: int) -> ProcessEntry:
        def _collect_detail() -> ProcessEntry:
            if pid <= 0:
                raise HTTPException(400, "系统保留进程不提供详情。")
            try:
                proc = psutil.Process(pid)
            except psutil.NoSuchProcess as exc:
                raise HTTPException(404, f"进程不存在: {pid}") from exc
            except (psutil.AccessDenied, ProcessLookupError) as exc:
                raise HTTPException(403, f"无法读取进程 {pid} 的详情，可能是系统保留进程或权限不足。") from exc
            detail = _build_process_entry(proc, include_cmdline=True, include_exe=True)
            if detail is None:
                raise HTTPException(403, f"无法读取进程 {pid} 的详情，可能是系统保留进程或权限不足。")
            return detail
        return await asyncio.to_thread(_collect_detail)

    @app.post("/admin/api/system/processes/{pid}/terminate", response_model=ProcessActionResponse)
    async def system_process_terminate(
        pid: int,
        wait_timeout: float = Query(default=3.0, ge=0.1, le=30.0),
    ) -> ProcessActionResponse:
        return _execute_process_action(pid, "terminate", wait_timeout=wait_timeout)

    @app.post("/admin/api/system/processes/{pid}/kill", response_model=ProcessActionResponse)
    async def system_process_kill(
        pid: int,
        wait_timeout: float = Query(default=3.0, ge=0.1, le=30.0),
    ) -> ProcessActionResponse:
        return _execute_process_action(pid, "kill", wait_timeout=wait_timeout)

    @app.get("/admin/api/system/ports", response_model=PortListResponse)
    async def system_ports_list(
        search: str | None = Query(default=None),
        listen_only: bool = Query(default=False),
        include_cmdline: bool = Query(default=False),
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> PortListResponse:
        def _collect() -> PortListResponse:
            snapshot = _get_or_collect_port_snapshot_payload()
            def _filter_items(source: dict[str, Any]) -> list[PortEntry | dict[str, Any]]:
                source_items = list(source.get("items") or [])
                return [
                    item for item in source_items
                    if (not listen_only or str(_snapshot_entry_value(item, "status") or "").upper() == "LISTEN") and _match_port(item, search)
                ]

            items = _filter_items(snapshot)
            if search and not items:
                snapshot = _refresh_port_snapshot_payload()
                items = _filter_items(snapshot)
            total = len(items)
            truncated = total > limit
            limited = items[:limit]
            if include_cmdline:
                limited = _hydrate_port_entries(limited)
            else:
                limited = [_port_entry_from_payload(item) for item in limited]
            return PortListResponse(
                generated_at=str(snapshot.get("generated_at") or _now_iso()),
                total=total,
                truncated=truncated,
                items=limited,
            )
        return await asyncio.to_thread(_collect)

    @app.get("/admin/api/system/files/list", response_model=FileListResponse)
    async def system_files_list(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
    ) -> FileListResponse:
        root_info, target, normalized = _resolve_target(root, path, must_exist=True, expect_dir=True)
        root_path = Path(root_info.path)
        entries = [_file_entry(root_path, item) for item in target.iterdir()]
        entries.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        parent_path = None
        if normalized:
            parent_parts = normalized.split("/")[:-1]
            parent_path = "/".join(parent_parts)
        return FileListResponse(root=root_info, current_path=normalized, parent_path=parent_path, entries=entries)

    @app.get("/admin/api/system/files/text", response_model=TextPreviewResponse)
    async def system_files_text_preview(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
        limit_bytes: int = Query(default=200_000, ge=1, le=1_000_000),
    ) -> TextPreviewResponse:
        root_info, target, normalized = _resolve_target(root, path, must_exist=True, expect_dir=False)
        if not target.is_file():
            raise HTTPException(400, "目标不是文件。")
        mime_type, _ = mimetypes.guess_type(str(target))
        if not _is_text_file(target, mime_type):
            raise HTTPException(415, "该文件不支持文本预览。")
        data = target.read_bytes()
        truncated = len(data) > limit_bytes
        payload = data[:limit_bytes]
        text, encoding = _decode_text(payload)
        return TextPreviewResponse(
            root=root_info,
            relative_path=normalized,
            size=len(data),
            mime_type=mime_type,
            encoding=encoding,
            truncated=truncated,
            content=text,
        )

    @app.put("/admin/api/system/files/text")
    async def system_files_text_write(
        body: TextWriteRequest,
        root: str | None = Query(default=None),
        path: str = Query(default=""),
    ) -> dict[str, Any]:
        root_info, target, normalized = _resolve_target(root, path, must_exist=True, expect_dir=False)
        if not target.is_file():
            raise HTTPException(400, '目标不是文件。')
        mime_type, _ = mimetypes.guess_type(str(target))
        if not _is_text_file(target, mime_type):
            raise HTTPException(415, '该文件不支持在线编辑。')
        try:
            data = body.content.encode(body.encoding)
        except LookupError as exc:
            raise HTTPException(400, f'未知编码: {body.encoding}') from exc
        except UnicodeEncodeError as exc:
            raise HTTPException(400, f'按 {body.encoding} 编码失败: {exc}') from exc
        target.write_bytes(data)
        return {
            'saved': True,
            'root': root_info.model_dump(),
            'relative_path': normalized,
            'size': len(data),
            'mime_type': mime_type,
            'encoding': body.encoding,
            'modified_at': datetime.fromtimestamp(target.stat().st_mtime).isoformat(),
        }

    @app.get("/admin/api/system/files/office-preview")
    async def system_files_office_preview(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
    ) -> dict[str, Any]:
        root_info, _target, normalized, data, mime_type = _system_file_target(root, path)
        return office_preview_payload(
            normalized,
            data,
            mime_type,
            pdf_url_builder=lambda preview_path: f"{_internal_admin_path('api/system/files/office-preview/pdf')}?root={quote(root_info.key, safe='')}&path={quote(preview_path, safe='')}",
            thumb_url_builder=lambda preview_path, page: f"{_internal_admin_path('api/system/files/office-preview/thumb')}?root={quote(root_info.key, safe='')}&path={quote(preview_path, safe='')}&page={page}",
        )

    @app.get("/admin/api/system/files/office-preview/pdf")
    async def system_files_office_preview_pdf(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
    ) -> FileResponse:
        root_info, _target, normalized, data, mime_type = _system_file_target(root, path)
        if office_preview_kind(normalized, mime_type) != 'presentation':
            raise HTTPException(400, 'PDF office preview is only available for presentation documents.')
        cache_key = office_preview_cache_key(normalized, data, mime_type)
        pdf_path, _ = office_preview_cache_paths(cache_key)
        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
            presentation_preview_payload(
                normalized,
                data,
                mime_type,
                pdf_url_builder=lambda preview_path: f"{_internal_admin_path('api/system/files/office-preview/pdf')}?root={quote(root_info.key, safe='')}&path={quote(preview_path, safe='')}",
                thumb_url_builder=lambda preview_path, page: f"{_internal_admin_path('api/system/files/office-preview/thumb')}?root={quote(root_info.key, safe='')}&path={quote(preview_path, safe='')}&page={page}",
            )
        return FileResponse(pdf_path, media_type='application/pdf', filename=f'{Path(normalized).stem or "preview"}.pdf')

    @app.get("/admin/api/system/files/office-preview/thumb")
    async def system_files_office_preview_thumb(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
        page: int = Query(..., ge=1),
    ) -> FileResponse:
        root_info, _target, normalized, data, mime_type = _system_file_target(root, path)
        if office_preview_kind(normalized, mime_type) != 'presentation':
            raise HTTPException(400, 'Thumbnail preview is only available for presentation documents.')
        cache_key = office_preview_cache_key(normalized, data, mime_type)
        _, thumb_dir = office_preview_cache_paths(cache_key)
        thumb_path = thumb_dir / f'{page}.png'
        if not thumb_path.exists() or thumb_path.stat().st_size <= 0:
            payload = presentation_preview_payload(
                normalized,
                data,
                mime_type,
                pdf_url_builder=lambda preview_path: f"{_internal_admin_path('api/system/files/office-preview/pdf')}?root={quote(root_info.key, safe='')}&path={quote(preview_path, safe='')}",
                thumb_url_builder=lambda preview_path, page_no: f"{_internal_admin_path('api/system/files/office-preview/thumb')}?root={quote(root_info.key, safe='')}&path={quote(preview_path, safe='')}&page={page_no}",
            )
            if page > int(payload.get('page_count') or 0):
                raise HTTPException(404, 'Preview page not found')
        return FileResponse(thumb_path, media_type='image/png')

    @app.get("/admin/api/system/files/raw")
    async def system_files_raw(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
    ) -> FileResponse:
        _root_info, target, _normalized = _resolve_target(root, path, must_exist=True, expect_dir=False)
        if not target.is_file():
            raise HTTPException(400, "目标不是文件。")
        media_type, _ = mimetypes.guess_type(str(target))
        return FileResponse(target, media_type=media_type)

    @app.get("/admin/api/system/files/download")
    async def system_files_download(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
    ) -> FileResponse:
        _root_info, target, _normalized = _resolve_target(root, path, must_exist=True, expect_dir=False)
        if not target.is_file():
            raise HTTPException(400, "目标不是文件。")
        media_type, _ = mimetypes.guess_type(str(target))
        return FileResponse(target, media_type=media_type, filename=target.name)

    @app.post("/admin/api/system/files/upload")
    async def system_files_upload(
        root: str = Form(...),
        path: str = Form(default=""),
        overwrite: bool = Form(default=False),
        files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        import aiofiles

        root_info, target_dir, normalized = _resolve_target(root, path, must_exist=True, expect_dir=True)
        if not target_dir.is_dir():
            raise HTTPException(400, "上传目标必须是目录。")

        written: list[dict[str, Any]] = []
        root_path = Path(root_info.path)
        for upload in files:
            filename = Path(upload.filename or "").name.strip()
            if not filename:
                raise HTTPException(400, "上传文件名不能为空。")
            if filename in {".", ".."}:
                raise HTTPException(400, "非法文件名。")
            destination = (target_dir / filename).resolve(strict=False)
            if not _within_root(root_path, destination):
                raise HTTPException(403, "上传目标超出允许范围。")
            if destination.exists() and destination.is_dir():
                raise HTTPException(409, f"目标已存在同名目录: {filename}")
            if destination.exists() and not overwrite:
                raise HTTPException(409, f"文件已存在: {filename}")
            async with aiofiles.open(destination, "wb") as f:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    await f.write(chunk)
            await upload.close()
            written.append(_file_entry(root_path, destination).model_dump())

        return {
            "root": root_info.model_dump(),
            "current_path": normalized,
            "files": written,
        }

    @app.post("/admin/api/system/files/mkdir")
    async def system_files_mkdir(
        root: str = Form(...),
        path: str = Form(default=""),
        name: str = Form(...),
    ) -> dict[str, Any]:
        root_info, target_dir, normalized = _resolve_target(root, path, must_exist=True, expect_dir=True)
        folder_name = Path(name or "").name.strip()
        if not folder_name or folder_name in {".", ".."}:
            raise HTTPException(400, "目录名非法。")
        root_path = Path(root_info.path)
        destination = (target_dir / folder_name).resolve(strict=False)
        if not _within_root(root_path, destination):
            raise HTTPException(403, "目标路径超出允许范围。")
        if destination.exists():
            raise HTTPException(409, f"目录已存在: {folder_name}")
        destination.mkdir(parents=True, exist_ok=False)
        return {
            "root": root_info.model_dump(),
            "current_path": normalized,
            "entry": _file_entry(root_path, destination).model_dump(),
        }

    @app.delete("/admin/api/system/files/item")
    async def system_files_delete(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
        recursive: bool = Query(default=False),
    ) -> dict[str, Any]:
        root_info, target, normalized = _resolve_target(root, path, must_exist=True)
        if not normalized:
            raise HTTPException(400, "不能删除根目录。")
        was_dir = target.is_dir()
        if was_dir:
            if recursive:
                shutil.rmtree(target)
            else:
                try:
                    target.rmdir()
                except OSError as exc:
                    raise HTTPException(409, f"目录非空，无法删除：{exc}") from exc
        else:
            target.unlink()
        return {
            "root": root_info.model_dump(),
            "deleted": True,
            "path": normalized,
            "was_dir": was_dir,
            "recursive": recursive,
        }

    @app.post("/admin/api/system/files/rename")
    async def system_files_rename(body: FileRenameRequest) -> dict[str, Any]:
        root_info, target, normalized = _resolve_target(body.root, body.path, must_exist=True)
        if not normalized:
            raise HTTPException(400, "不能重命名根目录。")
        new_name = Path(body.new_name or "").name.strip()
        if not new_name or new_name in {".", ".."}:
            raise HTTPException(400, "非法的新文件名。")
        root_path = Path(root_info.path)
        destination = (target.parent / new_name).resolve(strict=False)
        if not _within_root(root_path, destination):
            raise HTTPException(403, "目标路径超出允许范围。")
        if destination.exists():
            raise HTTPException(409, f"已存在同名项目: {new_name}")
        target.rename(destination)
        return {
            "root": root_info.model_dump(),
            "old_path": normalized,
            "entry": _file_entry(root_path, destination).model_dump(),
        }

    def _resolve_transfer(body: FileTransferRequest) -> tuple[RootInfo, Path, str, RootInfo, Path, str, Path]:
        src_root, src_target, src_normalized = _resolve_target(body.source_root, body.source_path, must_exist=True)
        dst_root_info, dst_dir, dst_normalized = _resolve_target(body.target_root or body.source_root, body.target_dir, must_exist=True, expect_dir=True)
        dst_root_path = Path(dst_root_info.path)
        name = (body.target_name or src_target.name).strip()
        name = Path(name).name.strip()
        if not name or name in {".", ".."}:
            raise HTTPException(400, "非法的目标文件名。")
        destination = (dst_dir / name).resolve(strict=False)
        if not _within_root(dst_root_path, destination):
            raise HTTPException(403, "目标路径超出允许范围。")
        return src_root, src_target, src_normalized, dst_root_info, dst_dir, dst_normalized, destination

    @app.post("/admin/api/system/files/copy")
    async def system_files_copy(body: FileTransferRequest) -> dict[str, Any]:
        _src_root, src_target, _src_normalized, dst_root_info, _dst_dir, _dst_normalized, destination = _resolve_transfer(body)
        if destination.exists():
            if not body.overwrite:
                raise HTTPException(409, f"目标已存在: {destination.name}")
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if src_target.is_dir():
            if destination.resolve() == src_target.resolve() or _within_root(src_target, destination):
                raise HTTPException(400, "不能将目录复制到其自身或子目录。")
            shutil.copytree(src_target, destination)
        else:
            shutil.copy2(src_target, destination)
        return {
            "root": dst_root_info.model_dump(),
            "entry": _file_entry(Path(dst_root_info.path), destination).model_dump(),
        }

    @app.post("/admin/api/system/files/move")
    async def system_files_move(body: FileTransferRequest) -> dict[str, Any]:
        _src_root, src_target, src_normalized, dst_root_info, _dst_dir, _dst_normalized, destination = _resolve_transfer(body)
        if not src_normalized:
            raise HTTPException(400, "不能移动根目录。")
        if destination.exists():
            if not body.overwrite:
                raise HTTPException(409, f"目标已存在: {destination.name}")
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if src_target.is_dir() and _within_root(src_target, destination):
            raise HTTPException(400, "不能将目录移动到其自身或子目录。")
        shutil.move(str(src_target), str(destination))
        return {
            "root": dst_root_info.model_dump(),
            "entry": _file_entry(Path(dst_root_info.path), destination).model_dump(),
        }

    @app.get("/admin/api/system/files/extract-preview")
    async def system_files_extract_preview(
        root: str | None = Query(default=None),
        path: str = Query(default=""),
    ) -> dict[str, Any]:
        root_info, target, normalized = _resolve_target(root, path, must_exist=True, expect_dir=False)
        kind = _archive_kind(target)
        if not kind:
            return {
                "root": root_info.model_dump(),
                "path": normalized,
                "kind": None,
                "supported": False,
                "default_target_dir": "",
                "extractors": [],
                "default_extractor": None,
            }
        default_name = _archive_default_target_name(target)
        parent_rel = Path(normalized).parent.as_posix()
        if parent_rel in ('.', ''):
            default_target_dir = default_name
        else:
            default_target_dir = f"{parent_rel}/{default_name}"
        # Probe candidates by passing a placeholder dest; we only want the labels here.
        placeholder = Path(target.parent / '__extract_probe__')
        candidates = _extractor_candidates(kind, target, placeholder)
        extractor_labels = [label for label, _ in candidates]
        return {
            "root": root_info.model_dump(),
            "path": normalized,
            "kind": kind,
            "supported": bool(candidates),
            "default_target_dir": default_target_dir,
            "extractors": extractor_labels,
            "default_extractor": extractor_labels[0] if extractor_labels else None,
        }

    @app.post("/admin/api/system/files/extract")
    async def system_files_extract(body: FileExtractRequest) -> dict[str, Any]:
        root_info, target, normalized = _resolve_target(body.root, body.path, must_exist=True, expect_dir=False)
        root_path = Path(root_info.path)
        kind = _archive_kind(target)
        if not kind:
            raise HTTPException(415, "该文件不是支持的压缩包 (zip/tar/tar.gz/tar.bz2/tar.xz/7z/rar)。")
        if body.target_dir is None or body.target_dir == "":
            stem = _archive_default_target_name(target)
            dest_dir = (target.parent / stem).resolve(strict=False)
        else:
            _dst_root, dest_dir, _ = _resolve_target(body.root, body.target_dir, must_exist=False, expect_dir=None)
        if not _within_root(root_path, dest_dir):
            raise HTTPException(403, "解压目标超出允许范围。")
        if dest_dir.exists():
            if not body.overwrite:
                raise HTTPException(409, f"解压目标已存在: {dest_dir.name}")
            if dest_dir.is_dir():
                shutil.rmtree(dest_dir)
            else:
                dest_dir.unlink()
        dest_dir.mkdir(parents=True, exist_ok=False)
        candidates = _extractor_candidates(kind, target, dest_dir)
        if not candidates:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(415, f"未找到可用的 {kind} 解压器 (7z/tar/unzip/unrar 均不可用)。")
        wanted = (body.extractor or 'auto').lower()
        if wanted not in ('auto', ''):
            chosen = next(((label, argv) for label, argv in candidates if label == wanted), None)
            if chosen is None:
                shutil.rmtree(dest_dir, ignore_errors=True)
                available = ', '.join(label for label, _ in candidates)
                raise HTTPException(400, f"指定的解压器 '{wanted}' 不可用。可用: {available}")
        else:
            chosen = candidates[0]
        used_label, argv = chosen
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(target.parent),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=600)
            except asyncio.TimeoutError:
                proc.kill()
                with contextlib.suppress(Exception):
                    await proc.wait()
                shutil.rmtree(dest_dir, ignore_errors=True)
                raise HTTPException(504, "解压超时（>10 分钟）。")
            if proc.returncode != 0:
                shutil.rmtree(dest_dir, ignore_errors=True)
                err = (stderr_bytes or b'').decode('utf-8', 'replace').strip() or (stdout_bytes or b'').decode('utf-8', 'replace').strip()
                raise HTTPException(400, f"解压失败 (extractor={used_label}, exit={proc.returncode}): {err[:500]}")
            # For tar.gz/.bz2/.xz handled by 7z, the first pass yields a .tar inside dest_dir; do a second pass.
            if used_label == '7z' and kind in ('tar.gz', 'tar.bz2', 'tar.xz'):
                inner_tar = next((p for p in dest_dir.iterdir() if p.suffix.lower() == '.tar'), None)
                if inner_tar is not None:
                    proc2 = await asyncio.create_subprocess_exec(
                        argv[0], 'x', str(inner_tar), f'-o{dest_dir}', '-y',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    out2, err2 = await proc2.communicate()
                    if proc2.returncode == 0:
                        with contextlib.suppress(Exception):
                            inner_tar.unlink()
                    else:
                        shutil.rmtree(dest_dir, ignore_errors=True)
                        raise HTTPException(400, f"二次解压失败: {(err2 or b'').decode('utf-8', 'replace')[:500]}")
        except HTTPException:
            raise
        except FileNotFoundError as exc:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(500, f"解压器不可用: {exc}") from exc
        except Exception as exc:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(400, f"解压失败: {exc}") from exc
        rel = dest_dir.relative_to(root_path).as_posix()
        return {
            "root": root_info.model_dump(),
            "source_path": normalized,
            "target_path": rel,
            "extractor": used_label,
            "kind": kind,
            "entry": _file_entry(root_path, dest_dir).model_dump(),
        }

    @app.websocket("/admin/ws/panel/system/terminal")
    async def system_terminal_ws(websocket: WebSocket):
        config = _build_system_tools_config()
        await websocket.accept()
        if not config.terminal_available:
            await websocket.send_json({
                "type": "error",
                "message": config.terminal_unavailable_reason or "终端功能当前不可用。",
            })
            await websocket.close(code=1011)
            return

        shell_key = (websocket.query_params.get("shell") or "").strip() or config.available_shells[0]["key"]
        root_key = websocket.query_params.get("root") or config.default_root
        relative_path = websocket.query_params.get("path") or config.default_terminal_path
        cols = int(websocket.query_params.get("cols") or 120)
        rows = int(websocket.query_params.get("rows") or 30)

        shell_info = next((item for item in config.available_shells if item["key"] == shell_key), None)
        if shell_info is None:
            await websocket.send_json({"type": "error", "message": f"不支持的终端类型: {shell_key}"})
            await websocket.close(code=1008)
            return

        try:
            root_info, cwd, normalized = _resolve_target(root_key, relative_path, must_exist=True, expect_dir=True)
        except HTTPException as exc:
            await websocket.send_json({"type": "error", "message": exc.detail})
            await websocket.close(code=1008)
            return

        session = None
        registered = False
        try:
            session = _create_terminal_session(shell_key, shell_info["command"], cwd, cols, rows)
            _register_terminal_session(session.session_id, config.terminal_max_sessions)
            _track_terminal_session(session)
            registered = True
        except Exception as exc:
            if session is not None:
                with contextlib.suppress(Exception):
                    session.close()
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=1011)
            return

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        session.start_reader(loop, queue)

        async def _sender():
            while True:
                event = await queue.get()
                try:
                    await websocket.send_json(event)
                except (WebSocketDisconnect, RuntimeError, OSError):
                    break
                if event.get("type") == "exit":
                    break

        sender_task = asyncio.create_task(_sender())
        await websocket.send_json({
            "type": "ready",
            "session_id": session.session_id,
            "shell": shell_key,
            "root": root_info.model_dump(),
            "cwd": normalized,
        })

        try:
            while True:
                message = await websocket.receive_json()
                msg_type = str(message.get("type") or "").strip().lower()
                if msg_type == "input":
                    session.write(str(message.get("data") or ""))
                elif msg_type == "resize":
                    session.resize(int(message.get("cols") or session.cols), int(message.get("rows") or session.rows))
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            session.close()
            if registered:
                _unregister_terminal_session(session.session_id)
            sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError, OSError):
                await sender_task
