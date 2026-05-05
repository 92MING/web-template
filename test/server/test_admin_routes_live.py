# -*- coding: utf-8 -*-
"""Live integration tests for admin panel routes and API endpoints.

Starts the full server via ``python scripts/run.py`` with 2 workers,
logs in, then probes every ``/_internal/admin/*`` route from the OpenAPI spec.
Also uses Playwright to verify key HTML pages render without console errors
or broken static asset references.
"""

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

# Ensure project root is importable
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_SERVER_PORT = 19031
_BASE_URL = f"http://127.0.0.1:{_SERVER_PORT}"
_RUN_PY = str(_project_root / "scripts" / "run.py")
_STOP_PY = str(_project_root / "scripts" / "stop.py")
_ADMIN_PW = "ThinkThinkSyn2023"


def _server_env() -> dict[str, str]:
    env = os.environ.copy()
    env["ADMIN_PW"] = _ADMIN_PW
    env["__SKIP_AI_PRELOAD__"] = "1"
    return env


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        return fp
    def http_error_307(self, req, fp, code, msg, headers):
        return fp
    def http_error_301(self, req, fp, code, msg, headers):
        return fp


def _wait_for_server_ready(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{_BASE_URL}/_internal/admin/session", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Server did not become ready within {timeout}s")


def _login() -> str:
    login_req = urllib.request.Request(
        f"{_BASE_URL}/_internal/admin/login",
        data=json.dumps({"password": _ADMIN_PW, "next_path": "/_internal/admin/panel"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(login_req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return str(data["api_key"])


def _request(
    path: str,
    method: str = "GET",
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    cookie: str | None = None,
    follow_redirects: bool = True,
) -> tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(f"{_BASE_URL}{path}", method=method)
    if body is not None:
        req.data = body
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = cookie
    for k, v in h.items():
        req.add_header(k, v)

    if follow_redirects:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                ct = resp.headers.get("content-type", "")
                return resp.status, ct, dict(resp.headers)
        except urllib.error.HTTPError as exc:
            ct = exc.headers.get("content-type", "")
            return exc.code, ct, dict(exc.headers)
    else:
        opener = urllib.request.build_opener(NoRedirectHandler())
        with opener.open(req, timeout=30) as resp:
            ct = resp.headers.get("content-type", "")
            return resp.status, ct, dict(resp.headers)


class TestAdminRoutesLive(unittest.TestCase):
    _api_key: str = ""

    @classmethod
    def setUpClass(cls):
        # Kill any leftover process on the port
        try:
            import urllib.request
            urllib.request.urlopen(f"{_BASE_URL}/_internal/admin/session", timeout=1)
        except Exception:
            pass

        result = subprocess.run(
            [sys.executable, _RUN_PY, "--server-port", str(_SERVER_PORT), "--server-worker", "2"],
            cwd=str(_project_root),
            env=_server_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or f"run.py exited with {result.returncode}")
        _wait_for_server_ready(timeout=60.0)
        cls._api_key = _login()

    @classmethod
    def tearDownClass(cls):
        subprocess.run(
            [sys.executable, _STOP_PY, "-p", str(_SERVER_PORT), "-y"],
            cwd=str(_project_root),
            env=_server_env(),
            capture_output=True,
            text=True,
            timeout=45,
        )

    @property
    def _cookie(self) -> str:
        return f"proj_admin_apikey={self._api_key}"

    def _fetch_openapi_paths(self) -> list[tuple[str, list[str]]]:
        req = urllib.request.Request(f"{_BASE_URL}/_internal/admin/openapi.json", method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            spec = json.loads(resp.read().decode("utf-8"))
        paths = []
        for path, path_item in spec.get("paths", {}).items():
            if not path.startswith("/_internal/admin"):
                continue
            methods = [m.upper() for m in path_item.keys() if m in {
                "get", "post", "put", "patch", "delete", "head", "options"
            }]
            paths.append((path, methods))
        return sorted(paths)

    def test_admin_login_page_unauthenticated(self):
        status, ct, _ = _request("/_internal/admin/login", follow_redirects=False)
        self.assertEqual(status, 200, "/_internal/admin/login should be reachable without auth")
        self.assertIn("text/html", ct)

    def test_admin_root_redirects_unauthenticated_to_login(self):
        status, _, _ = _request("/_internal/admin", follow_redirects=False, headers={"Accept": "text/html"})
        # When unauthenticated, internal admin should redirect to login (307) or return 401
        self.assertIn(status, {307, 401}, "/_internal/admin should not be directly accessible when unauthenticated")

    def test_admin_panel_authenticated(self):
        status, ct, _ = _request("/_internal/admin/panel", cookie=self._cookie)
        self.assertEqual(status, 200, "/_internal/admin/panel should be reachable when authenticated")
        self.assertIn("text/html", ct)

    def test_admin_root_authenticated(self):
        status, ct, _ = _request("/_internal/admin", cookie=self._cookie)
        # Should follow redirect and eventually return panel html
        self.assertIn(status, {200, 307}, "/_internal/admin should not 404 when authenticated")

    def test_admin_panel_pages_all_return_200(self):
        """Key admin panel HTML pages must all return 200."""
        pages = [
            "/_internal/admin/",
            "/_internal/admin/panel",
            "/_internal/admin/panel/backend/overview",
            "/_internal/admin/panel/backend/settings",
            "/_internal/admin/panel/backend/apikey",
            "/_internal/admin/panel/system/overview",
            "/_internal/admin/panel/system/cpu",
            "/_internal/admin/panel/system/gpu",
            "/_internal/admin/panel/system/files",
            "/_internal/admin/panel/system/ports",
            "/_internal/admin/panel/system/processes",
            "/_internal/admin/panel/system/terminal",
            "/_internal/admin/panel/ai-services/overview",
            "/_internal/admin/panel/ai-services/settings",
            "/_internal/admin/panel/distributed.html",
            "/_internal/admin/storage/kv",
            "/_internal/admin/storage/object",
            "/_internal/admin/storage/orm",
            "/_internal/admin/storage/vector",
            "/_internal/admin/log/overview",
            "/_internal/admin/log/backend",
            "/_internal/admin/log/service",
            "/_internal/admin/log/detail",
            "/_internal/admin/log/analysis",
            "/_internal/admin/test/ai",
            "/_internal/admin/test/ai/chat",
        ]
        failures = []
        for path in pages:
            status, ct, _ = _request(path, cookie=self._cookie)
            if status != 200:
                failures.append(f"{path} -> {status} ({ct})")
        self.assertFalse(failures, "Some admin panel pages failed: " + "; ".join(failures))

    def test_admin_api_endpoints_return_200_or_expected(self):
        """Core admin API endpoints must be reachable and not return 404."""
        endpoints = [
            ("/_internal/admin/api/backend/runtime", "GET"),
            ("/_internal/admin/api/backend/settings", "GET"),
            ("/_internal/admin/api/backend/start_args", "GET"),
            ("/_internal/admin/api/logs", "GET"),
            ("/_internal/admin/api/logs/overview", "GET"),
            ("/_internal/admin/api/system", "GET"),
            ("/_internal/admin/api/system/cpu", "GET"),
            ("/_internal/admin/api/system/gpu", "GET"),
            ("/_internal/admin/api/system/ports", "GET"),
            ("/_internal/admin/api/system/processes", "GET"),
            ("/_internal/admin/apikeys", "GET"),
            ("/_internal/admin/permission-roles", "GET"),
            ("/_internal/admin/session", "GET"),
        ]
        failures = []
        for path, method in endpoints:
            status, ct, _ = _request(path, method, cookie=self._cookie)
            if status == 404:
                failures.append(f"{method} {path} -> 404")
            elif status >= 500:
                failures.append(f"{method} {path} -> {status}")
        self.assertFalse(failures, "Some admin API endpoints failed: " + "; ".join(failures))

    def test_openapi_admin_paths_are_reachable(self):
        """Use the live OpenAPI spec to spot-check every internal admin path."""
        admin_paths = self._fetch_openapi_paths()
        self.assertGreater(len(admin_paths), 50, "Expected many admin paths in OpenAPI")

        failures = []
        # We can't safely POST/PUT/DELETE on most endpoints, but we can at least
        # GET every path that supports GET and verify it doesn't 404.
        for path, methods in admin_paths:
            if "GET" not in methods:
                continue
            # Skip paths with path parameters that we can't safely materialize
            if "{" in path:
                continue
            if "/_internal/admin/ai/" in path:
                continue  # AI endpoints may require request bodies
            try:
                status, ct, _ = _request(path, "GET", cookie=self._cookie)
                if status == 404:
                    failures.append(f"GET {path} -> 404")
                elif status >= 500:
                    failures.append(f"GET {path} -> {status}")
                # 400 / 422 are acceptable: route exists but needs query params / body
            except Exception as exc:
                failures.append(f"GET {path} -> {type(exc).__name__}: {exc}")

        # Limit failure reporting so the assertion message stays readable
        self.assertFalse(
            failures,
            f"{len(failures)} admin GET routes returned 404 or 5xx: "
            + "; ".join(failures[:20]),
        )

    def test_playwright_panel_pages_no_console_errors(self):
        """Use Playwright to open key panel pages and collect console errors."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")

        pages_to_check = [
            "/_internal/admin/panel",
            "/_internal/admin/panel/backend/overview",
            "/_internal/admin/panel/system/overview",
            "/_internal/admin/storage/kv",
            "/_internal/admin/log/overview",
        ]

        errors: list[str] = []
        network_failures: list[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context()
            # Set the auth cookie so we don't get redirected to login
            context.add_cookies([{
                "name": "proj_admin_apikey",
                "value": self._api_key,
                "domain": "127.0.0.1",
                "path": "/",
            }])

            for path in pages_to_check:
                page = context.new_page()
                page.on("console", lambda msg: errors.append(f"{path}: [{msg.type}] {msg.text}") if msg.type == "error" else None)
                page.on("response", lambda resp: network_failures.append(f"{path}: {resp.status} {resp.url}") if resp.status >= 400 and (resp.url.endswith(".css") or resp.url.endswith(".js")) else None)
                page.goto(f"{_BASE_URL}{path}", wait_until="load", timeout=15_000)
                page.wait_for_timeout(1_000)
                page.close()

            browser.close()

        # Filter out expected errors (e.g., favicon 404s are common and harmless)
        serious_errors = [e for e in errors if "favicon" not in e.lower()]
        serious_network = [n for n in network_failures if "favicon" not in n.lower()]

        self.assertFalse(
            serious_network,
            "Static asset 404s detected: " + "; ".join(serious_network[:10]),
        )
        self.assertFalse(
            serious_errors,
            "Console errors detected: " + "; ".join(serious_errors[:10]),
        )


if __name__ == "__main__":
    unittest.main()
