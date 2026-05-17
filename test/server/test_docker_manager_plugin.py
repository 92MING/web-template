# -*- coding: utf-8 -*-

import sys
from unittest.mock import patch

from _test_helpers import FullAppTestBase
from core.server.data_types.apikey import create_apikey, delete_apikey
from core.server.plugin import get_plugin_instance, get_plugin_key, get_registered_plugins


class _DockerManagerAdminBase(FullAppTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._admin_apikey = await create_apikey(
            name="docker manager plugin test",
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

    def _docker_plugin_class(self):
        return next(plugin for plugin in get_registered_plugins() if get_plugin_key(plugin) == "docker-manager")

    def _docker_plugin_module(self):
        plugin_class = self._docker_plugin_class()
        return sys.modules[plugin_class.__module__]

    def _docker_plugin_instance(self):
        plugin_class = self._docker_plugin_class()
        instance = get_plugin_instance(plugin_class, "worker")
        assert instance is not None
        return instance


class TestDockerManagerPanel(_DockerManagerAdminBase):
    async def test_docker_manager_panel_view_has_shell_markers(self):
        headers = self._admin_headers()
        response = await self._client.get("/_internal/admin/panel/plugins/view/docker-manager", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("docker-manager-shell", response.text)
        self.assertIn("docker-manager-frame", response.text)
        self.assertIn("docker-manager-install", response.text)
        self.assertIn("docker-manager-password-dialog", response.text)
        self.assertIn("/_internal/admin/api/docker-manager/status", response.text)
        self.assertIn("/_internal/admin/docker-manager/yacht", response.text)

    async def test_docker_manager_status_reports_missing_docker(self):
        module = self._docker_plugin_module()
        headers = self._admin_headers()
        with patch.object(module, "_get_docker_binary", return_value=None):
            response = await self._client.get("/_internal/admin/api/docker-manager/status", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["plugin_key"], "docker-manager")
        self.assertFalse(payload["docker_installed"])
        self.assertFalse(payload["docker_accessible"])
        self.assertFalse(payload["yacht_running"])

    async def test_docker_manager_status_requests_sudo_on_permission_error(self):
        module = self._docker_plugin_module()
        headers = self._admin_headers()
        with (
            patch.object(module, "_get_docker_binary", return_value="/usr/bin/docker"),
            patch.object(module, "_docker_command", side_effect=module._NeedSudoPasswordError("Docker access requires sudo privileges.")),
        ):
            response = await self._client.get("/_internal/admin/api/docker-manager/status", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["docker_installed"])
        self.assertFalse(payload["docker_accessible"])
        self.assertTrue(payload["requires_sudo"])

    async def test_docker_manager_sudo_password_api_caches_password_in_shared_data(self):
        module = self._docker_plugin_module()
        plugin_class = self._docker_plugin_class()
        instance = self._docker_plugin_instance()
        instance.shared.clear_sudo_password()

        def _fake_collect_status(_self):
            return module.DockerManagerStatusResponse(
                plugin_key="docker-manager",
                enabled=True,
                host_platform="Linux",
                docker_installed=True,
                docker_accessible=True,
                install_supported=True,
                sudo_cached=_self.shared.has_sudo_password(),
                yacht_container_exists=False,
                yacht_running=False,
                yacht_port=None,
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
                "/_internal/admin/api/docker-manager/sudo-password",
                headers=headers,
                json={"password": "secret-pass"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["sudo_cached"])
        self.assertEqual(instance.shared.get_sudo_password(), "secret-pass")

    async def test_docker_manager_proxy_rewrites_root_relative_assets(self):
        module = self._docker_plugin_module()
        plugin_class = self._docker_plugin_class()
        instance = self._docker_plugin_instance()
        instance.shared.set_yacht_port(38080)

        def _fake_collect_status(_self):
            return module.DockerManagerStatusResponse(
                plugin_key="docker-manager",
                enabled=True,
                host_platform="Linux",
                docker_installed=True,
                docker_accessible=True,
                install_supported=True,
                sudo_cached=False,
                yacht_container_exists=True,
                yacht_running=True,
                yacht_port=38080,
                yacht_proxy_path="/_internal/admin/docker-manager/yacht",
                message="running",
            )

        class _FakeProxyResponse:
            status_code = 200
            headers = {"content-type": "text/html; charset=utf-8"}
            text = "<html><head></head><body><script src=\"/app.js\"></script><a href=\"/settings\">settings</a></body></html>"
            content = text.encode("utf-8")

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def request(self, method, url, headers=None, content=None, params=None):
                return _FakeProxyResponse()

        headers = self._admin_headers()
        with (
            patch.object(plugin_class, "_collect_status", _fake_collect_status),
            patch.object(module.httpx, "AsyncClient", _FakeAsyncClient),
        ):
            response = await self._client.get("/_internal/admin/docker-manager/yacht/", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertIn('/_internal/admin/docker-manager/yacht/app.js', response.text)
        self.assertIn('/_internal/admin/docker-manager/yacht/settings', response.text)
        self.assertIn('const PREFIX=', response.text)