#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop a running backend."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_DEFAULT_PORT_START = 8000
_DEFAULT_PORT_SCAN_MAX = 16
_DEFAULT_PROD_PORT = 9191
_BACKEND_PROBE_ENDPOINT = "/_internal/admin/api/logs/config"
_LOGIN_ENDPOINT = "/_internal/admin/login"
_CONTROL_ENDPOINT = "/_internal/admin/api/backend/control"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_IS_WINDOWS = sys.platform == "win32"

# Windows kernel/system PIDs that must never be touched. PID 0 (Idle) and
# PID 4 (System) frequently appear as `OwningProcess` for sockets in
# TIME_WAIT or for kernel-mode listeners. Trying to kill them — or worse,
# enumerate and kill their descendants — would target every process on the
# machine.
_WINDOWS_SYSTEM_PIDS: set[int] = {0, 4}


def _error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def _info(message: str) -> None:
    print(message, file=sys.stderr)


def _http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 5.0,
) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method=method, data=body, headers=headers or {}, unverifiable=True)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # type: ignore[arg-type]
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:
        raise ConnectionError(f"Request to {url} failed: {exc}") from exc


def _find_admin_password() -> str | None:
    """Scan project *.env files for ADMIN_PW (mirrors restart.py)."""
    env_files = list(_PROJECT_ROOT.rglob("*.env"))
    env_files.sort(key=lambda path: (len(path.parts), str(path)))
    for env_path in env_files:
        try:
            text = env_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            match = re.match(r"^ADMIN_PW\s*=\s*(.+)$", line)
            if match:
                password = match.group(1).strip().strip('"').strip("'")
                if password:
                    return password
    return None


def _admin_login(host: str, port: int, password: str) -> str | None:
    try:
        status, body = _http_request(
            "POST",
            f"http://{host}:{port}{_LOGIN_ENDPOINT}",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"password": password}).encode("utf-8"),
            timeout=5.0,
        )
    except Exception:
        return None
    if status != 200:
        return None
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("authenticated"):
        return None
    token = data.get("api_key")
    return str(token) if token else None


def _is_backend(host: str, port: int) -> bool:
    try:
        status, _body = _http_request("GET", f"http://{host}:{port}{_BACKEND_PROBE_ENDPOINT}", timeout=2.0)
    except Exception:
        return False
    return status in {200, 401}


def _find_backend_port(host: str, start: int, scan_max: int) -> int:
    if _is_backend(host, _DEFAULT_PROD_PORT):
        _info(f"Discovered backend at {host}:{_DEFAULT_PROD_PORT}")
        return _DEFAULT_PROD_PORT
    for offset in range(scan_max):
        port = start + offset
        if _is_backend(host, port):
            _info(f"Discovered backend at {host}:{port}")
            return port
    _error(f"No backend found on {host} in port range {start}-{start + scan_max - 1} or prod port {_DEFAULT_PROD_PORT}.")


def _pids_for_port(host: str, port: int) -> set[int]:
    return _pids_for_port_windows(port) if _IS_WINDOWS else _pids_for_port_linux(port)


def _pids_for_port_windows(port: int) -> set[int]:
    pids: set[int] = set()

    # Method 1: PowerShell Get-NetTCPConnection. Do NOT filter by `-State Listen`,
    # some sockets (e.g. dual-stack IPv6, Bound) can be missed otherwise.
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pid_value = int(line)
                    if pid_value not in _WINDOWS_SYSTEM_PIDS:
                        pids.add(pid_value)
    except Exception:
        pass

    # Method 2: netstat fallback. Match any state (LISTENING / ESTABLISHED / etc.)
    # because the caller only cares "who owns the port".
    try:
        result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            suffix = f":{port}"
            for line in result.stdout.splitlines():
                parts = line.split()
                # Typical lines:
                #   TCP    0.0.0.0:19210    0.0.0.0:0    LISTENING    12345
                #   TCP    [::]:19210       [::]:0       LISTENING    12345
                if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(suffix):
                    try:
                        pid_value = int(parts[-1])
                    except ValueError:
                        continue
                    if pid_value not in _WINDOWS_SYSTEM_PIDS:
                        pids.add(pid_value)
    except Exception:
        pass

    return pids


def _descendant_pids_windows(pid: int) -> set[int]:
    """Return all descendant PIDs (recursively) of `pid` via WMI ParentProcessId.

    Important on Windows: when a supervisor dies but its multiprocessing
    workers are still running, the listening socket they inherited keeps the
    OS reporting the dead supervisor's PID as `OwningProcess`. Killing the
    supervisor PID is a no-op (it doesn't exist), but its orphaned children
    are the real owners that must be terminated to release the port.
    """
    descendants: set[int] = set()
    if pid in _WINDOWS_SYSTEM_PIDS:
        # Never walk the System process tree.
        return descendants
    queue: list[int] = [pid]
    seen: set[int] = set()
    while queue:
        parent = queue.pop()
        if parent in seen or parent in _WINDOWS_SYSTEM_PIDS:
            continue
        seen.add(parent)
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-CimInstance Win32_Process -Filter \"ParentProcessId={parent}\" | Select-Object -ExpandProperty ProcessId",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            continue
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                child = int(line)
                if child in _WINDOWS_SYSTEM_PIDS or child == pid:
                    continue
                if child not in descendants:
                    descendants.add(child)
                    queue.append(child)
    return descendants


def _force_kill_port_windows(port: int) -> set[int]:
    """Last-resort hammer: ask PowerShell to kill whoever owns the port,
    plus all descendants of that owner (in case the OwningProcess reported by
    the OS is a long-dead supervisor whose multiprocessing workers inherited
    the listening socket).

    Returns the set of PIDs we attempted to kill (best-effort).
    """
    killed: set[int] = set()
    # First find owners (may include dead PIDs).
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        owners: set[int] = set()
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pid_value = int(line)
                    if pid_value > 0 and pid_value not in _WINDOWS_SYSTEM_PIDS:
                        owners.add(pid_value)
    except Exception:
        owners = set()

    # Build full kill set: owners + their descendants.
    targets: set[int] = set(owners)
    for owner in owners:
        targets.update(_descendant_pids_windows(owner))

    for pid in sorted(targets):
        if _kill_pid(pid, force=True):
            killed.add(pid)
    return killed


def _pids_for_port_linux(port: int) -> set[int]:
    pids: set[int] = set()
    for cmd in (["ss", "-tlnp", f"sport = :{port}"], ["netstat", "-tlnp"]):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                continue
            for line in result.stdout.splitlines():
                if f":{port}" not in line:
                    continue
                for match in re.finditer(r"pid=(\d+)|(\d+)/", line):
                    value = match.group(1) or match.group(2)
                    if value:
                        pids.add(int(value))
        except Exception:
            continue
    if not pids:
        try:
            result = subprocess.run(["lsof", "-i", f"TCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                pids.update(int(item) for item in result.stdout.split() if item.isdigit())
        except Exception:
            pass
    return pids


def _get_process_info_windows(pid: int) -> dict[str, str]:
    """Return process name and command line for diagnostic output."""
    info: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "get", "Name,CommandLine", "/format:csv"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip() and not line.strip().startswith("Node,")]
            if lines:
                parts = lines[0].split(",")
                if len(parts) >= 3:
                    info["name"] = parts[1]
                    info["cmdline"] = parts[2]
    except Exception:
        pass
    return info


def _kill_pid(pid: int, *, force: bool = False) -> bool:
    if pid in _WINDOWS_SYSTEM_PIDS and _IS_WINDOWS:
        return False
    if _IS_WINDOWS:
        methods: list[list[str]] = []
        if force:
            methods.append(["taskkill", "/PID", str(pid), "/T", "/F"])
        else:
            methods.append(["taskkill", "/PID", str(pid), "/T"])
            methods.append(["taskkill", "/PID", str(pid), "/T", "/F"])
        methods.append(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"])

        for cmd in methods:
            try:
                # Silently swallow per-command stderr; we only care about the final outcome.
                result = subprocess.run(cmd, capture_output=True, timeout=15)
                if result.returncode == 0:
                    return True
            except Exception:
                pass
        return False
    import signal

    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _try_http_stop(host: str, port: int) -> bool:
    """Ask the backend to shut itself down via the internal control API.

    Requires admin auth (the route is gated behind the admin API-key
    middleware). We mirror restart.py: locate ADMIN_PW from project *.env
    files, log in to obtain a token, then POST the control action with a
    Bearer header.
    """
    password = _find_admin_password()
    if not password:
        return False
    token = _admin_login(host, port, password)
    if not token:
        return False
    body = json.dumps({"action": "stop", "reason": "stop-script"}).encode("utf-8")
    try:
        status, _resp = _http_request(
            "POST",
            f"http://{host}:{port}{_CONTROL_ENDPOINT}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            body=body,
            timeout=5.0,
        )
    except Exception:
        return False
    return status in (200, 201, 202, 204)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stop a backend process.")
    parser.add_argument("-p", "--port", type=int, default=None, help="Backend port")
    parser.add_argument("-H", "--host", type=str, default="127.0.0.1", help="Backend host")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    host = args.host
    port = args.port or _find_backend_port(host, _DEFAULT_PORT_START, _DEFAULT_PORT_SCAN_MAX)

    if not args.yes:
        try:
            answer = input(f"Stop backend on {host}:{port}? [y/N]: ")
        except EOFError:
            answer = "n"
        if answer.strip().lower() not in {"y", "yes"}:
            _info("Aborted.")
            return

    # First try graceful HTTP stop (most reliable on Windows with multi-worker).
    if _try_http_stop(host, port):
        _info(f"Asked backend on {host}:{port} to shut down gracefully.")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if not _is_backend(host, port):
                _info(f"Backend on {host}:{port} stopped.")
                return
        _info("Graceful shutdown timed out; falling back to PID kill.")

    # Fallback: find PID(s) and kill them.
    pids = _pids_for_port(host, port)
    if not pids:
        # Port may still be occupied by PID(s) we can't enumerate (e.g. socket
        # owned by a dead supervisor whose workers inherited it). Hammer it.
        if _IS_WINDOWS and _is_backend(host, port):
            hammered = _force_kill_port_windows(port)
            time.sleep(1.0)
            if not _is_backend(host, port) and not _pids_for_port(host, port):
                _info(f"Backend on {host}:{port} stopped (force-kill, {len(hammered)} pid(s)).")
                return
        _error(f"No process found listening on {host}:{port}")

    # On Windows, expand to descendants. The OS reports the original socket
    # creator (often a now-dead supervisor) as `OwningProcess`, but the actual
    # workers serving traffic are its multiprocessing children that inherited
    # the socket. We must kill the children to release the port.
    if _IS_WINDOWS:
        expanded: set[int] = set(pids)
        for pid in list(pids):
            expanded.update(_descendant_pids_windows(pid))
        pids = expanded

    _info(f"Killing PID(s) on {host}:{port}: {sorted(pids)}")
    killed: set[int] = set()
    for pid in sorted(pids):
        if _kill_pid(pid):
            killed.add(pid)

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        time.sleep(0.3)
        current = _pids_for_port(host, port)
        if _IS_WINDOWS:
            current = set(current) | {d for p in current for d in _descendant_pids_windows(p)}
        if not current:
            break
        for pid in sorted(current):
            if _kill_pid(pid):
                killed.add(pid)
    else:
        leftover = _pids_for_port(host, port)
        if _IS_WINDOWS:
            leftover = set(leftover) | {d for p in leftover for d in _descendant_pids_windows(p)}
        for pid in sorted(leftover):
            if _kill_pid(pid, force=True):
                killed.add(pid)

    final = _pids_for_port(host, port)
    if final and _IS_WINDOWS:
        # Last-resort hammer before giving up.
        hammered = _force_kill_port_windows(port)
        killed.update(hammered)
        time.sleep(1.0)
        final = _pids_for_port(host, port)
    if final:
        if _IS_WINDOWS:
            details = []
            for pid in sorted(final):
                info = _get_process_info_windows(pid)
                details.append(f"{pid} ({info.get('name', 'unknown')})")
            _error(
                f"Port {host}:{port} is still occupied by {', '.join(details)}. "
                "Try elevated: powershell -Command \"Stop-Process -Id "
                f"{', '.join(str(p) for p in sorted(final))} -Force\""
            )
        _error(f"Port {host}:{port} is still occupied by PID(s) {sorted(final)}.")
    _info(f"Backend on {host}:{port} stopped (killed {len(killed)} pid(s)).")


if __name__ == "__main__":
    main()