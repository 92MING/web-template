#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restart a running backend."""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

_script_path = Path(__file__).resolve()
_project_root = _script_path.parent.parent
_scripts_dir = _project_root / "scripts"

_DEFAULT_PORT_START = 8000
_DEFAULT_PORT_SCAN_MAX = 16
_DEFAULT_PROD_PORT = 9191
_BACKEND_PROBE_ENDPOINT = "/_internal/admin/api/logs/config"
_LOGIN_ENDPOINT = "/_internal/admin/login"
_CONTROL_ENDPOINT = "/_internal/admin/api/backend/control"
_START_ARGS_ENDPOINT = "/_internal/admin/api/backend/start_args"


def _error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def _info(message: str) -> None:
    print(message, file=sys.stderr)


def _http_request(method: str, url: str, *, headers: dict[str, str] | None = None, body: bytes | None = None, timeout: float = 10.0) -> tuple[int, bytes]:
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


def _json_response(body: bytes) -> dict | list | None:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None


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


def _find_password_in_env_files(project_root: Path) -> str | None:
    env_files = list(project_root.rglob("*.env"))
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
            for key in ("ADMIN_PW",):
                match = re.match(rf"^{re.escape(key)}\s*=\s*(.+)$", line)
                if match:
                    password = match.group(1).strip().strip('"').strip("'")
                    if password:
                        _info(f"Using admin password from {env_path}")
                        return password
    return None


def _login(base_url: str, password: str) -> str:
    status, body = _http_request(
        "POST",
        f"{base_url}{_LOGIN_ENDPOINT}",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"password": password}).encode("utf-8"),
    )
    data = _json_response(body)
    if status != 200 or not isinstance(data, dict) or not data.get("authenticated"):
        detail = data.get("detail") if isinstance(data, dict) else None
        _error(f"Admin login failed ({status}): {detail or 'invalid password'}")
    token = data.get("api_key")
    if not token:
        _error("Admin login succeeded but no token was returned.")
    return str(token)


def _api_restart(base_url: str, token: str) -> None:
    status, body = _http_request(
        "POST",
        f"{base_url}{_CONTROL_ENDPOINT}",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        body=json.dumps({"action": "restart", "reason": "cli-restart"}).encode("utf-8"),
    )
    data = _json_response(body)
    if status != 200:
        detail = data.get("detail") if isinstance(data, dict) else None
        _error(f"Restart API call failed ({status}): {detail or 'unknown error'}")


def _api_get_start_args(base_url: str, token: str) -> list[str]:
    status, body = _http_request("GET", f"{base_url}{_START_ARGS_ENDPOINT}", headers={"Authorization": f"Bearer {token}"})
    data = _json_response(body)
    if status != 200 or not isinstance(data, dict):
        detail = data.get("detail") if isinstance(data, dict) else None
        _error(f"Failed to fetch start_args ({status}): {detail or 'unknown error'}")
    try:
        loaded = json.loads(str(data.get("start_args", "[]")))
    except Exception:
        _error(f"Backend returned invalid start_args JSON: {data.get('start_args')!r}")
    if not isinstance(loaded, list):
        _error("Backend returned start_args that is not a JSON list.")
    return [str(item) for item in loaded]


def _run_stop(port: int) -> None:
    result = subprocess.run([sys.executable, str(_scripts_dir / "stop.py"), "-p", str(port), "--yes"], capture_output=True, text=True)
    if result.returncode != 0:
        _error(f"stop.py failed:\n{result.stderr or result.stdout}")
    if result.stdout.strip():
        _info(result.stdout.strip())


def _run_run_py(start_args: list[str]) -> None:
    result = subprocess.run([sys.executable, str(_scripts_dir / "run.py"), *start_args], text=True)
    if result.returncode != 0:
        _error(f"run.py exited with code {result.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restart a backend.")
    parser.add_argument("-p", "--port", type=int, default=None, help="Backend port")
    parser.add_argument("-H", "--host", type=str, default="127.0.0.1", help="Backend host")
    parser.add_argument("-pw", "--password", type=str, default=None, help="Admin password")
    parser.add_argument("-e", "--entire", action="store_true", help="Stop and relaunch through scripts/run.py")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    password = args.password or _find_password_in_env_files(_project_root)
    if not password:
        _error("Admin password not found. Provide -pw/--password or set ADMIN_PW in an env file.")
    host = args.host
    port = args.port or _find_backend_port(host, _DEFAULT_PORT_START, _DEFAULT_PORT_SCAN_MAX)
    if not args.yes:
        action = "full restart" if args.entire else "restart via API"
        try:
            answer = input(f"Restart backend on {host}:{port} ({action})? [y/N]: ")
        except EOFError:
            answer = "n"
        if answer.strip().lower() not in {"y", "yes"}:
            _info("Aborted.")
            return

    base_url = f"http://{host}:{port}"
    _info(f"Logging in to {base_url} ...")
    token = _login(base_url, password)
    _info("Login succeeded.")
    if not args.entire:
        _api_restart(base_url, token)
        _info("Backend restart requested via control API.")
        return

    start_args = _api_get_start_args(base_url, token)
    _info(f"Original start args: {start_args}")
    _run_stop(port)
    time.sleep(0.5)
    _run_run_py(start_args)
    _info("Backend re-launched via run.py.")


if __name__ == "__main__":
    main()