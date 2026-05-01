# -*- coding: utf-8 -*-
"""Tests for the Admin IP restriction middleware."""

import sys
import unittest
import httpx
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
_app_dir = _project_root / "app"
for _p in (str(_project_root), str(_app_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.server.data_types.config import Config, LogConfig, ServerConfig


class TestAdminIPMiddleware(unittest.IsolatedAsyncioTestCase):
    """Verify that internal admin paths are gated by internal_path_allowed_ip."""

    async def asyncSetUp(self):
        from core.server.app import create_app
        self.cfg = Config(
            server_config=ServerConfig(
                host="127.0.0.1",
                port=18999,
                internal_path_allowed_ip="127.0.0.1,::1",
            ),
            log_config=LogConfig(log_method=["db"]),
        )
        Config.SetConfig(self.cfg)
        self.app = create_app(config=self.cfg)
        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def _get(self, path: str, headers: dict | None = None):
        return await self.client.get(path, headers=headers)

    async def test_admin_page_allowed_from_localhost(self):
        """Requests from 127.0.0.1 should be allowed."""
        r = await self._get("/_internal/admin/login.html")
        # StaticFiles may 404 if the file doesn't exist in tests, but we care about not 403
        self.assertNotEqual(r.status_code, 403)

    async def test_admin_openapi_json_allowed_from_any_ip(self):
        """/_internal/admin/openapi.json is explicitly exempt from IP restriction."""
        r = await self._get("/_internal/admin/openapi.json")
        self.assertNotEqual(r.status_code, 403)

    async def test_non_admin_paths_not_restricted(self):
        """Non-admin paths should not be IP-gated."""
        r = await self._get("/api/shop/products")
        self.assertNotEqual(r.status_code, 403)


class TestAdminIPMiddlewareBlocked(unittest.IsolatedAsyncioTestCase):
    """Verify blocking when client IP is not in the whitelist."""

    async def asyncSetUp(self):
        from core.server.app import create_app
        self.cfg = Config(
            server_config=ServerConfig(
                host="127.0.0.1",
                port=18999,
                internal_path_allowed_ip="10.0.0.1",  # only allow a non-local IP
            ),
            log_config=LogConfig(log_method=["db"]),
        )
        Config.SetConfig(self.cfg)
        self.app = create_app(config=self.cfg)
        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_admin_page_blocked_when_ip_not_allowed(self):
        """Requests from 127.0.0.1 should be blocked when whitelist is 10.0.0.1."""
        r = await self.client.get("/_internal/admin/login.html")
        self.assertEqual(r.status_code, 403)
        self.assertIn("denied", str(r.json().get("detail", "")).lower())

    async def test_admin_openapi_json_still_allowed(self):
        """Even with a strict whitelist, /_internal/admin/openapi.json stays open."""
        r = await self.client.get("/_internal/admin/openapi.json")
        self.assertNotEqual(r.status_code, 403)

    async def test_non_admin_paths_unaffected(self):
        """Non-admin paths should still work."""
        r = await self.client.get("/api/shop/products")
        self.assertNotEqual(r.status_code, 403)


class TestAdminIPMiddlewareNoWhitelist(unittest.IsolatedAsyncioTestCase):
    """When internal_path_allowed_ip is all, no restriction should apply."""

    async def asyncSetUp(self):
        from core.server.app import create_app
        self.cfg = Config(
            server_config=ServerConfig(
                host="127.0.0.1",
                port=18999,
                internal_path_allowed_ip="all",
            ),
            log_config=LogConfig(log_method=["db"]),
        )
        Config.SetConfig(self.cfg)
        self.app = create_app(config=self.cfg)
        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_admin_page_allowed_when_no_whitelist(self):
        """No whitelist means no IP restriction."""
        r = await self.client.get("/_internal/admin/login.html")
        self.assertNotEqual(r.status_code, 403)
