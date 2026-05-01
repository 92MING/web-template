# -*- coding: utf-8 -*-

import os
import re
import unittest

import httpx

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path

from _test_helpers import FullAppTestBase, _StorageTestBase
from core.server.routes.admin.apikey import register_admin_apikey_routes
from core.server.routes.admin.auth import install_admin_panel_auth, register_admin_auth_routes
from core.server.routes.admin.permission_role import register_admin_permission_role_routes
from core.server.routes.panel.main import register_panel_routes
from core.server.security.admin_password import clear_admin_password_state, initialize_admin_password
from core.server.data_types.apikey import create_apikey, delete_apikey, get_apikey_by_key
from core.server.data_types.config import Config, LogConfig, ServerConfig
from core.server.html_injection import html_response_from_path


class AdminPanelAuthTestBase(_StorageTestBase):
    _env_backup: dict[str, str] | None = None

    @classmethod
    def _register_routes(cls, app: FastAPI):
        register_admin_auth_routes(app)
        register_panel_routes(app)
        @app.get("/demo-page", response_class=HTMLResponse)
        async def demo_page() -> HTMLResponse:
            return HTMLResponse("<html><body>demo</body></html>")

        @app.get("/api/demo")
        async def demo_api() -> dict[str, bool]:
            return {"ok": True}

        @app.get("/api/demo-html", response_class=HTMLResponse)
        async def demo_html_api() -> HTMLResponse:
            return HTMLResponse("<html><body>demo html api</body></html>")

        install_admin_panel_auth(app)

    @classmethod
    def setUpClass(cls):
        cls._env_backup = os.environ.copy()
        os.environ["ADMIN_PW"] = "panel-admin-secret"
        super().setUpClass()
        Config.SetConfig(
            Config(
                server_config=ServerConfig(host="127.0.0.1", port=18999),
                log_config=LogConfig(log_method=["db"]),
            )
        )
        initialize_admin_password(logger=__import__("logging").getLogger(__name__), allow_generate=False)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._api_key = await create_apikey(name="panel auth test key")

    async def asyncTearDown(self):
        try:
            if getattr(self, "_api_key", None) is not None:
                await delete_apikey(str(getattr(self._api_key, "id", "") or ""))
        finally:
            await super().asyncTearDown()

    @classmethod
    def tearDownClass(cls):
        clear_admin_password_state()
        if cls._env_backup is not None:
            os.environ.clear()
            os.environ.update(cls._env_backup)
        super().tearDownClass()


class TestAdminPanelAuth(AdminPanelAuthTestBase):
    async def test_unauthenticated_panel_redirects_to_login(self):
        resp = await self._client.get("/_internal/admin/panel", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)
        self.assertEqual(resp.headers.get("location"), "/_internal/admin/login?next=%2F_internal%2Fadmin%2Fpanel")

    async def test_unauthenticated_panel_api_returns_401(self):
        resp = await self._client.get("/_internal/admin/api/backend/runtime")
        self.assertEqual(resp.status_code, 401)

    async def test_unauthenticated_admin_api_with_default_fetch_accept_returns_401_json(self):
        resp = await self._client.get(
            "/_internal/admin/api/backend/runtime",
            headers={"accept": "*/*"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("application/json", resp.headers.get("content-type", ""))
        self.assertIn("detail", resp.json())

    async def test_login_sets_cookie_and_stores_token_in_kv(self):
        resp = await self._client.post("/_internal/admin/login", json={"password": "panel-admin-secret", "next_path": "/_internal/admin/panel"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        api_key = data.get("api_key")
        self.assertTrue(api_key)
        self.assertEqual(data.get("redirect_to"), "/_internal/admin/panel")
        self.assertIn("proj_admin_apikey=", resp.headers.get("set-cookie", ""))

        stored = await get_apikey_by_key(str(api_key))
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertTrue(str(stored.name or "").startswith("__proj_admin_login__:"))

        panel_resp = await self._client.get("/_internal/admin/panel")
        self.assertEqual(panel_resp.status_code, 200)
        self.assertIn("text/html", panel_resp.headers.get("content-type", ""))

    async def test_existing_admin_apikey_reports_authenticated(self):
        login = await self._client.post("/_internal/admin/login", json={"password": "panel-admin-secret", "next_path": "/_internal/admin/panel"})
        api_key = login.json()["api_key"]

        session_resp = await self._client.get("/_internal/admin/session")
        self.assertEqual(session_resp.status_code, 200)
        data = session_resp.json()
        self.assertTrue(data.get("authenticated"))
        self.assertGreater(float(data.get("expires_at") or 0), 0.0)

        stored = await get_apikey_by_key(str(api_key))
        self.assertIsNotNone(stored)

    async def test_authenticated_login_page_redirects_without_rendering_login_shell(self):
        await self._client.post("/_internal/admin/login", json={"password": "panel-admin-secret", "next_path": "/_internal/admin/panel"})

        response = await self._client.get(
            "/_internal/admin/login",
            params={"next": "/_internal/admin/panel/backend/apikey"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers.get("location"), "/_internal/admin/panel/backend/apikey")

    async def test_login_page_renders_with_recomputed_content_length(self):
        response = await self._client.get(
            "/_internal/admin/login",
            params={"next": "/_internal/admin/panel/backend/apikey"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertEqual(int(response.headers.get("content-length") or 0), len(response.content))
        self.assertIn("/_internal/admin/panel/backend/apikey", response.text)

    async def test_panel_accepts_admin_apikey_header_without_login_redirect(self):
        login = await self._client.post("/_internal/admin/login", json={"password": "panel-admin-secret", "next_path": "/_internal/admin/panel"})
        api_key = login.json()["api_key"]

        transport = httpx.ASGITransport(app=self._app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as fresh_client:
            resp = await fresh_client.get(
                "/_internal/admin/panel",
                headers={"x-api-key": api_key},
                follow_redirects=False,
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))

    async def test_apikey_can_access_globally_protected_api(self):
        resp = await self._client.get("/api/demo", headers={"x-api-key": self._api_key.key})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})

    async def test_apikey_can_access_globally_protected_page(self):
        resp = await self._client.get("/demo-page", headers={"x-api-key": self._api_key.key})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))

    async def test_plain_apikey_can_open_html_page_without_admin_route_permission(self):
        limited_key = await create_apikey(
            name="html-only panel access",
            whitelist_routes=["*"],
            blacklist_routes=["/api/demo"],
        )
        try:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as fresh_client:
                html_resp = await fresh_client.get(
                    "/_internal/admin/panel",
                    params={"api_key": limited_key.key},
                    follow_redirects=False,
                )
                self.assertEqual(html_resp.status_code, 200)
                self.assertIn("text/html", html_resp.headers.get("content-type", ""))

                html_api_resp = await fresh_client.get(
                    "/api/demo-html",
                    params={"api_key": limited_key.key},
                    headers={"accept": "text/html"},
                    follow_redirects=False,
                )
                self.assertEqual(html_api_resp.status_code, 200)
                self.assertIn("text/html", html_api_resp.headers.get("content-type", ""))

                # Non-admin routes are no longer globally protected by _AdminPanelAuthMiddleware
                api_resp = await fresh_client.get(
                    "/api/demo",
                    params={"api_key": limited_key.key},
                    follow_redirects=False,
                )
                self.assertEqual(api_resp.status_code, 200)
        finally:
            await delete_apikey(str(getattr(limited_key, "id", "") or ""))

    async def test_logout_revokes_session(self):
        login = await self._client.post("/_internal/admin/login", json={"password": "panel-admin-secret", "next_path": "/_internal/admin/panel"})
        api_key = login.json()["api_key"]

        logout = await self._client.post("/_internal/admin/logout")
        self.assertEqual(logout.status_code, 200)

        stored = await get_apikey_by_key(str(api_key))
        self.assertIsNone(stored)

        resp = await self._client.get("/_internal/admin/api/backend/runtime")
        self.assertEqual(resp.status_code, 401)


class TestAdminLoginPage(unittest.TestCase):
    def test_login_page_persists_token_to_localstorage_and_cookie(self):
        Config.SetConfig(
            Config(
                server_config=ServerConfig(host="127.0.0.1", port=18999),
                log_config=LogConfig(log_method=["db"]),
            )
        )
        path = Path(__file__).resolve().parents[2] / "resources" / "admin-panel" / "panel_login.html"
        html = html_response_from_path(path).body.decode("utf-8")
        self.assertIn("localStorage.setItem(ADMIN_APIKEY_LOCALSTORAGE_KEY", html)
        self.assertIn("document.cookie = `${ADMIN_APIKEY_COOKIE_NAME}=", html)
        self.assertIn("localStorage.setItem(PANEL_DARK_KEY", html)
        self.assertIn("localStorage.setItem(PANEL_LANG_KEY", html)
        self.assertIn("/_internal/admin/login", html)
        self.assertIn("管理面板登录", html)
        self.assertIn('id="admin-password"', html)
        self.assertIn('id="admin-password-toggle"', html)
        self.assertIn('id="admin-login-submit"', html)
        self.assertIn('id="lang-toggle"', html)
        self.assertIn('id="dark-toggle"', html)
        self.assertIn("function togglePasswordVisibility()", html)
        self.assertIn("renderPasswordToggle();", html)
        self.assertIn("applyDark();", html)
        self.assertIn("applyPanelLang();", html)
        self.assertNotIn("/_internal/admin/session", html)
        self.assertNotIn("bootstrapExistingSession", html)


class TestProtectedFullAppRouteAudit(FullAppTestBase):
    _env_backup: dict[str, str] | None = None

    @classmethod
    def setUpClass(cls):
        cls._env_backup = os.environ.copy()
        os.environ["ADMIN_PW"] = "panel-admin-secret"
        super().setUpClass()
        assert cls._app is not None
        register_admin_auth_routes(cls._app)
        register_admin_apikey_routes(cls._app)
        register_admin_permission_role_routes(cls._app)
        install_admin_panel_auth(cls._app)
        initialize_admin_password(logger=__import__("logging").getLogger(__name__), allow_generate=False)

    @classmethod
    def tearDownClass(cls):
        clear_admin_password_state()
        if cls._env_backup is not None:
            os.environ.clear()
            os.environ.update(cls._env_backup)
        super().tearDownClass()

    @staticmethod
    def _materialize_path(path: str) -> str:
        return re.sub(r"\{[^}:]+(?::[^}]+)?\}", "audit", path)

    async def test_unauthenticated_routes_are_blocked_or_redirected(self):
        assert self._app is not None
        exempt_paths = {"/_internal/admin/login", "/_internal/admin/session", "/_internal/admin/openapi.json"}
        allowed_statuses = {307, 401, 402, 403, 429}
        audited: list[tuple[str, str]] = []
        failures: list[str] = []

        for route in self._app.routes:
            path = getattr(route, "path", None)
            methods = set(getattr(route, "methods", set()) or set())
            if not path or path in exempt_paths:
                continue
            if path.startswith("/_internal/admin/login/"):
                continue
            # Only check internal admin routes — non-admin routes are no longer globally protected
            if not path.startswith("/_internal/admin"):
                continue
            methods -= {"HEAD", "OPTIONS"}
            if not methods:
                continue
            request_path = self._materialize_path(path)
            for method in sorted(methods):
                audited.append((method, path))
                response = await self._client.request(method, request_path, follow_redirects=False)
                if response.status_code not in allowed_statuses:
                    failures.append(f"{method} {path} -> {response.status_code}")

        self.assertGreater(len(audited), 10)
        self.assertFalse(failures, "Unauthenticated admin routes unexpectedly succeeded: " + ", ".join(failures[:20]))
