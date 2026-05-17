# -*- coding: utf-8 -*-

import sys
from unittest.mock import patch

from _test_helpers import FullAppTestBase
from core.server.data_types.apikey import create_apikey, delete_apikey
from core.server.plugin import get_plugin_instance, get_plugin_key, get_registered_plugins


class _ClashAdminBase(FullAppTestBase):
    _platform_patch = None

    @classmethod
    def setUpClass(cls):
        cls._platform_patch = patch("core.server.plugin.get_current_platform", return_value="linux")
        cls._platform_patch.start()
        try:
            super().setUpClass()
        except Exception:
            cls._platform_patch.stop()
            cls._platform_patch = None
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            if cls._platform_patch is not None:
                cls._platform_patch.stop()
                cls._platform_patch = None

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._admin_apikey = await create_apikey(
            name="clash plugin test",
            whitelist_routes="all",
            blacklist_routes=[],
        )

    async def asyncTearDown(self):
        try:
            if getattr(self, "_admin_apikey", None) is not None:
                await delete_apikey(str(getattr(self._admin_apikey, "id", "") or ""))
        finally:
            await super().asyncTearDown()

    def _admin_headers(self) -> dict[str, str]:
        return {"x-api-key": str(self._admin_apikey.key)}

    def _plugin_class(self):
        return next(plugin for plugin in get_registered_plugins() if get_plugin_key(plugin) == "clash")

    def _plugin_module(self):
        plugin_class = self._plugin_class()
        return sys.modules[plugin_class.__module__]

    def _plugin_instance(self):
        plugin_class = self._plugin_class()
        instance = get_plugin_instance(plugin_class, "worker")
        assert instance is not None
        return instance


class TestClashPanel(_ClashAdminBase):
    async def test_clash_panel_view_has_shell_markers(self):
        headers = self._admin_headers()
        response = await self._client.get("/_internal/admin/panel/plugins/view/clash", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("clash-plugin-shell", response.text)
        self.assertIn("clash-plugin-frame", response.text)
        self.assertIn("clash-plugin-install", response.text)
        self.assertIn("clash-plugin-password-dialog", response.text)
        self.assertIn("/_internal/admin/api/clash/status", response.text)
        self.assertIn("/_internal/admin/clash/ui", response.text)

    async def test_clash_status_reports_missing_project(self):
        module = self._plugin_module()
        headers = self._admin_headers()
        with (
            patch.object(module, "_probe_controller", return_value=(False, "controller unavailable")),
            patch.object(module.shutil, "which", side_effect=lambda name: None if name in {"clashctl", "git"} else "/usr/bin/bash"),
            patch.object(module.Path, "exists", return_value=True),
            patch.object(module.Path, "is_file", return_value=False),
        ):
            response = await self._client.get("/_internal/admin/api/clash/status", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["clash_project_present"])
        self.assertFalse(payload["clashctl_available"])
        self.assertFalse(payload["controller_accessible"])

    async def test_clash_sudo_password_api_caches_password_in_shared_data(self):
        module = self._plugin_module()
        plugin_class = self._plugin_class()
        instance = self._plugin_instance()
        instance.shared.clear_sudo_password()

        def _fake_collect_status(_self):
            return module.ClashStatusResponse(
                plugin_key="clash",
                enabled=True,
                host_platform="Linux",
                clash_project_present=True,
                clashctl_available=True,
                controller_accessible=False,
                install_supported=True,
                sudo_cached=_self.shared.has_sudo_password(),
                controller_url="http://127.0.0.1:9090",
                controller_ui_url="http://127.0.0.1:9090/ui",
                controller_secret_configured=True,
                proxy_path=None,
                message="ok",
            )

        def _fake_verify(shared, password: str) -> None:
            shared.set_sudo_password(password)

        headers = self._admin_headers()
        with (
            patch.object(module, "_verify_sudo_password", side_effect=_fake_verify),
            patch.object(plugin_class, "_collect_status", _fake_collect_status),
        ):
            response = await self._client.post(
                "/_internal/admin/api/clash/sudo-password",
                headers=headers,
                json={"password": "secret-pass"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["sudo_cached"])
        self.assertEqual(instance.shared.get_sudo_password(), "secret-pass")

    async def test_clash_install_api_runs_install_helper(self):
        module = self._plugin_module()
        plugin_class = self._plugin_class()
        headers = self._admin_headers()

        def _fake_install(_self):
            return module.ClashStatusResponse(
                plugin_key="clash",
                enabled=True,
                host_platform="Linux",
                clash_project_present=True,
                clashctl_available=True,
                controller_accessible=True,
                install_supported=True,
                sudo_cached=False,
                controller_url="http://127.0.0.1:9090",
                controller_ui_url="http://127.0.0.1:9090/ui",
                controller_secret_configured=True,
                proxy_path="/_internal/admin/clash/ui",
                message="installed",
            )

        with patch.object(plugin_class, "_install", _fake_install):
            response = await self._client.post("/_internal/admin/api/clash/install", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["status"]["controller_accessible"])

    async def test_clash_proxy_rewrites_root_relative_assets_and_auth_header(self):
        module = self._plugin_module()
        plugin_class = self._plugin_class()
        instance = self._plugin_instance()
        instance.config.controller_host = "127.0.0.1"
        instance.config.controller_port = 9090
        instance.config.controller_secret = "abc123"

        captured: dict[str, object] = {}

        def _fake_collect_status(_self):
            return module.ClashStatusResponse(
                plugin_key="clash",
                enabled=True,
                host_platform="Linux",
                clash_project_present=True,
                clashctl_available=True,
                controller_accessible=True,
                install_supported=True,
                sudo_cached=False,
                controller_url="http://127.0.0.1:9090",
                controller_ui_url="http://127.0.0.1:9090/ui",
                controller_secret_configured=True,
                proxy_path="/_internal/admin/clash/ui",
                message="running",
            )

        class _FakeProxyResponse:
            status_code = 200
            headers = {"content-type": "text/html; charset=utf-8"}
            text = "<html><head></head><body><script src=\"/assets/app.js\"></script><a href=\"/configs\">configs</a></body></html>"
            content = text.encode("utf-8")

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def request(self, method, url, headers=None, content=None, params=None):
                captured["url"] = url
                captured["headers"] = dict(headers or {})
                return _FakeProxyResponse()

        headers = self._admin_headers()
        with (
            patch.object(plugin_class, "_collect_status", _fake_collect_status),
            patch.object(module.httpx, "AsyncClient", _FakeAsyncClient),
        ):
            response = await self._client.get("/_internal/admin/clash/ui/", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["url"], "http://127.0.0.1:9090/ui/")
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer abc123")
        self.assertIn('/_internal/admin/clash/ui/assets/app.js', response.text)
        self.assertIn('/_internal/admin/clash/ui/configs', response.text)
        self.assertIn('const PREFIX=', response.text)

    async def test_clash_proxy_forwards_nested_ui_requests_with_auth_header(self):
        module = self._plugin_module()
        plugin_class = self._plugin_class()
        instance = self._plugin_instance()
        instance.config.controller_host = "127.0.0.1"
        instance.config.controller_port = 9090
        instance.config.controller_secret = "abc123"

        captured: dict[str, object] = {}

        def _fake_collect_status(_self):
            return module.ClashStatusResponse(
                plugin_key="clash",
                enabled=True,
                host_platform="Linux",
                clash_project_present=True,
                clashctl_available=True,
                controller_accessible=True,
                install_supported=True,
                sudo_cached=False,
                controller_url="http://127.0.0.1:9090",
                controller_ui_url="http://127.0.0.1:9090/ui",
                controller_secret_configured=True,
                proxy_path="/_internal/admin/clash/ui",
                message="running",
            )

        class _FakeProxyResponse:
            status_code = 200
            headers = {"content-type": "application/json; charset=utf-8"}
            content = b'{"ok":true}'
            text = '{"ok":true}'

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def request(self, method, url, headers=None, content=None, params=None):
                captured["method"] = method
                captured["url"] = url
                captured["headers"] = dict(headers or {})
                return _FakeProxyResponse()

        headers = self._admin_headers()
        with (
            patch.object(plugin_class, "_collect_status", _fake_collect_status),
            patch.object(module.httpx, "AsyncClient", _FakeAsyncClient),
        ):
            response = await self._client.get("/_internal/admin/clash/ui/configs", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["url"], "http://127.0.0.1:9090/configs")
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer abc123")