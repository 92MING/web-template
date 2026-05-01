#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query backend logs via the admin API."""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

_script_path = Path(__file__).resolve()
_project_root = _script_path.parent.parent

_DEFAULT_PORT_START = 8000
_DEFAULT_PORT_SCAN_MAX = 16
_DEFAULT_PROD_PORT = 9191
_POLL_INTERVAL_SECONDS = 1.0
_LOGIN_ENDPOINT = "/_internal/admin/login"
_LOGS_ENDPOINT = "/_internal/admin/api/logs"
_BACKEND_PROBE_ENDPOINT = "/_internal/admin/api/logs/config"


def _error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def _info(message: str) -> None:
    print(message, file=sys.stderr)


def _http_request(method: str, url: str, *, headers: dict[str, str] | None = None, body: bytes | None = None, timeout: float = 5.0) -> tuple[int, bytes]:
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
        status, body = _http_request("GET", f"http://{host}:{port}{_BACKEND_PROBE_ENDPOINT}", timeout=2.0)
    except Exception:
        return False
    if status == 401:
        return True
    if status == 200:
        data = _json_response(body)
        return isinstance(data, dict) and ("db_enabled" in data or "file_enabled" in data)
    return False


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


def _query_logs(base_url: str, token: str, **params: str | int | None) -> list[dict]:
    clean_params = {key: value for key, value in params.items() if value not in (None, "")}
    status, body = _http_request(
        "GET",
        f"{base_url}{_LOGS_ENDPOINT}?{urlencode(clean_params)}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = _json_response(body)
    if status != 200 or not isinstance(data, dict):
        detail = data.get("detail") if isinstance(data, dict) else None
        _error(f"Log query failed ({status}): {detail or 'unknown error'}")
    rows = data.get("rows", [])
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _format_row(row: dict) -> str:
    return f"{row.get('timestamp') or ''}  {str(row.get('level') or 'UNKNOWN'):8s}  [{row.get('name') or ''}]  {row.get('message') or ''}"


def _tail_logs(base_url: str, token: str, *, query: str | None, logger_name: str | None, level: str | None, min_level: int | None, limit: int) -> None:
    seen_ids: set[str] = set()
    last_since: str | None = None
    try:
        while True:
            rows = _query_logs(
                base_url,
                token,
                search=query,
                name=logger_name,
                level=level,
                min_levelno=min_level,
                since=last_since,
                limit=limit,
                offset=0,
                order="DESC",
            )
            for row in reversed(rows):
                row_id = str(row.get("id") or "")
                if row_id and row_id in seen_ids:
                    continue
                if row_id:
                    seen_ids.add(row_id)
                print(_format_row(row), flush=True)
            if rows:
                newest_ts = str(rows[0].get("timestamp") or "")
                if newest_ts:
                    last_since = newest_ts
            time.sleep(_POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        _info("\nInterrupted.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query backend logs via the admin API.")
    parser.add_argument("-p", "--port", type=int, default=None, help="Backend port")
    parser.add_argument("-H", "--host", type=str, default="127.0.0.1", help="Backend host")
    parser.add_argument("-pw", "--password", type=str, default=None, help="Admin password")
    parser.add_argument("-q", "--query", type=str, default=None, help="Message text search filter")
    parser.add_argument("-lg", "--logger", type=str, default=None, help="Logger name substring filter")
    parser.add_argument("-o", "--output", type=str, default=None, help="Output JSON file path")
    parser.add_argument("--level", type=str, default=None, help="Exact log level filter")
    parser.add_argument("--since", type=str, default=None, help="ISO-8601 timestamp lower bound")
    parser.add_argument("--until", type=str, default=None, help="ISO-8601 timestamp upper bound")
    parser.add_argument("-l", "--limit", type=int, default=200, help="Max rows per query")

    def _parse_min_level(value: str) -> int:
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        upper = value.upper()
        if upper in levels:
            return levels[upper]
        try:
            return int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid log level: {value!r}") from exc

    parser.add_argument("-ml", "--min-level", type=_parse_min_level, default=None, help="Minimum log level")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    password = args.password or _find_password_in_env_files(_project_root)
    if not password:
        _error("Admin password not found. Provide -pw/--password or set ADMIN_PW in an env file.")
    host = args.host
    port = args.port or _find_backend_port(host, _DEFAULT_PORT_START, _DEFAULT_PORT_SCAN_MAX)
    base_url = f"http://{host}:{port}"
    _info(f"Logging in to {base_url} ...")
    token = _login(base_url, password)
    _info("Login succeeded.")

    if args.output:
        rows = _query_logs(
            base_url,
            token,
            search=args.query,
            name=args.logger,
            level=args.level,
            min_levelno=args.min_level,
            since=args.since,
            until=args.until,
            limit=args.limit,
            offset=0,
            order="DESC",
        )
        output_path = Path(args.output)
        output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        _info(f"Wrote {len(rows)} log row(s) to {output_path}")
    else:
        _tail_logs(base_url, token, query=args.query, logger_name=args.logger, level=args.level, min_level=args.min_level, limit=args.limit)


if __name__ == "__main__":
    main()