# -*- coding: utf-8 -*-

import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from _test_helpers import FullAppTestBase
from core.server.data_types.apikey import create_apikey, delete_apikey
from core.server.plugin import get_plugin_instance, get_plugin_key, get_registered_plugins


class _FrpManagerAdminBase(FullAppTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._admin_apikey = await create_apikey(
            name="frp manager plugin test",
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
        return next(plugin for plugin in get_registered_plugins() if get_plugin_key(plugin) == "frp-manager")

    def _plugin_module(self):
        plugin_class = self._plugin_class()
        return sys.modules[plugin_class.__module__]

    def _plugin_instance(self):
        plugin_class = self._plugin_class()
        instance = get_plugin_instance(plugin_class, "worker")
        assert instance is not None
        return instance


class TestFrpManagerPanel(_FrpManagerAdminBase):
    async def test_frp_manager_panel_view_has_shell_markers(self):
        headers = self._admin_headers()
        response = await self._client.get("/_internal/admin/panel/plugins/view/frp-manager", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("frp-manager-shell", response.text)
        self.assertIn("frp-manager-frps-frame", response.text)
        self.assertIn("frp-manager-frpc-frame", response.text)
        self.assertIn("frp-manager-install", response.text)
        self.assertIn("/_internal/admin/api/frp-manager/status", response.text)
        self.assertIn("/_internal/admin/frp-manager/frps/ui", response.text)
        self.assertIn("/_internal/admin/frp-manager/frpc/ui", response.text)

    async def test_frp_manager_status_reports_missing_binaries(self):
        module = self._plugin_module()
        headers = self._admin_headers()
        with patch.object(module, "_system_binary_path", return_value=None):
            response = await self._client.get("/_internal/admin/api/frp-manager/status", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["frps_installed"])
        self.assertFalse(payload["frpc_installed"])
        self.assertEqual(payload["frps_binary_source"], "none")
        self.assertEqual(payload["frpc_binary_source"], "none")

    async def test_frp_manager_install_downloads_matching_release_into_local_dirs(self):
        module = self._plugin_module()
        instance = self._plugin_instance()
        headers = self._admin_headers()

        with tempfile.TemporaryDirectory(prefix="frp-manager-test-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            instance.config.local_storage_dir = str(tmp_path / "frp")
            instance.config.state_dir = str(tmp_path / "state")

            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, "w") as archive:
                archive.writestr("frp_0.68.1_windows_amd64/frps.exe", b"fake-frps")
                archive.writestr("frp_0.68.1_windows_amd64/frpc.exe", b"fake-frpc")
            release_payload = {
                "tag_name": "v0.68.1",
                "assets": [
                    {
                        "name": "frp_0.68.1_windows_amd64.zip",
                        "browser_download_url": "https://example.test/frp.zip",
                    }
                ],
            }

            def _fake_download(url: str, target_path: Path) -> None:
                target_path.write_bytes(archive_bytes.getvalue())

            with (
                patch.object(module, "_release_platform_token", return_value="windows"),
                patch.object(module, "_release_arch_candidates", return_value=["amd64"]),
                patch.object(module, "_fetch_latest_release_payload", return_value=release_payload),
                patch.object(module, "_download_asset", side_effect=_fake_download),
                patch.object(module, "_system_binary_path", return_value=None),
            ):
                response = await self._client.post("/_internal/admin/api/frp-manager/install", headers=headers)

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertTrue((tmp_path / "frp" / "frps" / "frps.exe").is_file())
            self.assertTrue((tmp_path / "frp" / "frpc" / "frpc.exe").is_file())
            release_meta = json.loads((tmp_path / "frp" / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(release_meta["tag_name"], "v0.68.1")

    async def test_frp_manager_proxy_rewrites_root_relative_assets(self):
        module = self._plugin_module()
        plugin_class = self._plugin_class()
        instance = self._plugin_instance()
        instance.shared.set_frps_pid(1234)
        instance.shared.set_frps_ui_port(7500)

        def _fake_collect_status(_self):
            return module.FrpManagerStatusResponse(
                plugin_key="frp-manager",
                enabled=True,
                host_platform="Windows",
                architecture="AMD64",
                install_supported=True,
                frps_installed=True,
                frpc_installed=True,
                frps_binary_source="local",
                frpc_binary_source="local",
                frps_binary_path="C:/tmp/frps.exe",
                frpc_binary_path="C:/tmp/frpc.exe",
                installed_release_tag="v0.68.1",
                frps_running=True,
                frpc_running=False,
                frps_pid=1234,
                frpc_pid=None,
                frps_ui_port=7500,
                frpc_ui_port=7400,
                frps_ui_proxy_path="/_internal/admin/frp-manager/frps/ui",
                frpc_ui_proxy_path=None,
                frps_config_path="C:/tmp/frps.toml",
                frpc_config_path="C:/tmp/frpc.toml",
                message="running",
            )

        class _FakeProxyResponse:
            status_code = 200
            headers = {"content-type": "text/html; charset=utf-8"}
            text = '<html><head></head><body><script src="/assets/app.js"></script><a href="/login">login</a></body></html>'
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
            response = await self._client.get("/_internal/admin/frp-manager/frps/ui/", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertIn('/_internal/admin/frp-manager/frps/ui/assets/app.js', response.text)
        self.assertIn('/_internal/admin/frp-manager/frps/ui/login', response.text)
        self.assertIn('const PREFIX=', response.text)