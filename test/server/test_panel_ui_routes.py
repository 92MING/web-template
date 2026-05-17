# -*- coding: utf-8 -*-
"""Tests for admin panel HTML page routes."""

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel

_server_dir = Path(__file__).resolve().parent.parent.parent / "app" / "core" / "server"
if str(_server_dir.parent.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent.parent))
if str(_server_dir.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent))

from _test_helpers import FullAppTestBase
from core.server.data_types.apikey import create_apikey, delete_apikey
from core.server.data_types.config import Config
from core.server.plugin import clear_plugins, configure_plugin, get_plugin_key, register_plugin
from core.server.routes.panel.main import _prune_internal_paths_from_openapi


def test_backend_role_panel_template_regression_markers():
    panel_path = Path(__file__).resolve().parents[2] / "resources" / "admin-panel" / "panel" / "backend_role.html"
    body = panel_path.read_text(encoding="utf-8")
    assert ".empty-box.hidden" in body
    assert "const subtitle = String(item.comment || '').trim();" in body
    assert "els.detailSubtitle.textContent = String(item.comment || '').trim();" in body


def test_panel_openapi_export_markers():
    panel_main_path = Path(__file__).resolve().parents[2] / "core" / "server" / "routes" / "panel" / "main.py"
    body = panel_main_path.read_text(encoding="utf-8")
    assert "导出完整API文档HTML" in body
    assert "导出非内部API文档HTML" in body
    assert "_prune_internal_paths_from_openapi" in body
    assert "section.models .model-box" in body


def test_plugin_panel_shell_markers():
    panel_path = Path(__file__).resolve().parents[2] / "resources" / "admin-panel" / "panel.html"
    body = panel_path.read_text(encoding="utf-8")
    assert "nav-pluginlab" in body
    assert "page-pluginlab" in body
    assert "pluginlab-iframe" in body
    assert "showTab('pluginlab')" in body

    plugin_page_path = Path(__file__).resolve().parents[2] / "resources" / "admin-panel" / "panel" / "plugins.html"
    plugin_body = plugin_page_path.read_text(encoding="utf-8")
    assert "plugin-sidebar" in plugin_body
    assert "plugin-nav" in plugin_body
    assert "plugin-frame" in plugin_body
    assert "plugin-import-open" in plugin_body
    assert "plugin-import-modal" in plugin_body
    assert "plugin-config-modal" in plugin_body
    assert "plugin-nav-gear" in plugin_body
    assert "plugin-import-tab-local" in plugin_body
    assert "plugin-import-tab-remote" in plugin_body
    assert "plugin-local-picker" in plugin_body
    assert "plugin-local-dropzone" in plugin_body
    assert "plugin-remote-browser" in plugin_body
    assert "plugin-config-restart" in plugin_body
    assert "plugin-config-delete" in plugin_body
    assert "plugin-config-submit" in plugin_body
    assert "plugin-config-list" in plugin_body
    assert "buildPluginRuntimeUrl" in plugin_body
    assert "buildSystemFilesListUrl" in plugin_body
    assert "buildPluginListUrl" in plugin_body
    assert "buildPluginViewUrl" in plugin_body
    assert "submitPluginRegistration" in plugin_body
    assert "openManageModal" in plugin_body
    assert "restartManagedPlugin" in plugin_body
    assert "deleteManagedPlugin" in plugin_body
    assert "openConfigModal" in plugin_body
    assert "proj-admin-auth-expired" in plugin_body


def test_ai_test_ui_service_client_target_markers():
    root = Path(__file__).resolve().parents[2]
    shared = (root / "resources" / "admin-panel" / "shared" / "js" / "ai-test-shared.js").read_text(encoding="utf-8")
    assert "function fetchServiceInfo(kind)" in shared
    assert "function initServiceTargetControls(kind, targetSelectOrId, instanceSelectOrId" in shared
    assert "client_key" in shared
    assert "proj-language-change" in shared
    assert "cocopilot-language-change" not in shared

    pages = root / "resources" / "admin-panel" / "test" / "ai"
    for name, kind, target_marker in [
        ("chat.html", "completion", "completion-target-select"),
        ("translate.html", "completion", "service-target"),
        ("detect_language.html", "completion", "service-target"),
        ("summarize.html", "completion", "service-target"),
        ("ocr.html", "completion", "service-target"),
        ("asr.html", "completion", "service-target"),
        ("rerank.html", "embedding", "rerank-target"),
        ("embedding.html", "embedding", "serviceTargetSelect"),
        ("s2t.html", "s2t", "serviceTargetSelect"),
        ("t2s.html", "t2s", "serviceTarget"),
        ("t2img.html", "t2img", "service-target"),
    ]:
        body = (pages / name).read_text(encoding="utf-8")
        assert target_marker in body
        assert f"initServiceTargetControls('{kind}'" in body or f"initServiceTargetControls(\n    '{kind}'" in body

    chat_body = (pages / "chat.html").read_text(encoding="utf-8")
    assert 'data-tab="openai"' in chat_body
    assert '/test_openai_liked_complete' not in chat_body
    assert '/chat/completions' in chat_body
    assert 'headers.Authorization = `Bearer ${apiKey}`' in chat_body
    assert '/clients/openai/list-models' in chat_body
    assert 'https://openrouter.ai/api/v1' in chat_body
    assert 'https://api.openai.com/v1' in chat_body
    assert 'https://api.deepseek.com/v1' in chat_body
    assert 'https://api.moonshot.cn/v1' in chat_body
    assert 'has-env-key' not in chat_body
    assert 'btn-apikey-mode' not in chat_body
    assert 'test_thinkthinksyn_complete' not in chat_body
    assert 'test_openrouter_complete' not in chat_body
    assert '/clients/thinkthinksyn/list-models' not in chat_body
    assert '/clients/openrouter/list-models' not in chat_body

    t2img_body = (pages / "t2img.html").read_text(encoding="utf-8")
    assert '<option value="generate" selected>Generate</option>' in t2img_body
    assert '<option value="edit">Edit</option>' in t2img_body
    assert '<option value="variation">Variation</option>' in t2img_body
    assert 'openai/v1/images/edits' in t2img_body
    assert 'openai/v1/images/variations' in t2img_body
    assert 'openai/v1/images/generations' in t2img_body


def test_ai_services_settings_shared_kwargs_markers():
    root = Path(__file__).resolve().parents[2]
    body = (root / "resources" / "admin-panel" / "panel" / "ai_services_settings.html").read_text(encoding="utf-8")
    assert "data-instance-tab=\"kwargs\"" in body
    assert "kwargs-preset-library" in body
    assert "openKwargsPresetModal" in body
    assert "parseClientKwargsInput" in body
    assert "formatEpochSeconds(runtime.last_probe_at || runtime.last_success_at)" in body
    assert "parseRecoveryIntervalInput" in body


def test_distributed_panel_management_and_link_stats_markers():
    panel_path = Path(__file__).resolve().parents[2] / "resources" / "admin-panel" / "panel" / "distributed.html"
    body = panel_path.read_text(encoding="utf-8")
    assert "丢包率" in body
    assert "转发失败" in body
    assert "openSetWorkers" in body
    assert "submitSetWorkers" in body
    assert "sendCommand(node.node_id, 'stop')" in body
    assert "GRAPH_LAYOUT_KEY" in body
    assert "saveGraphLayout" in body
    assert "canvasTools" in body
    assert "graphSearchBtn" in body
    assert "openGraphSearch" in body
    assert "submitGraphSearch" in body
    assert "relationFilter" in body
    assert "filterChip" in body
    assert "nodeMatchesFilter" in body
    assert "focusGraphNodes" in body
    assert "setGraphZoom" in body
    assert "visibleNodes" in body
    assert "drawFlowDots" in body
    assert "renderLinkDetails" in body
    assert "relationDirection" in body
    assert "friend-friend" in body
    assert "parent-child" in body
    assert "parent-parent" in body
    assert "last_forward_failed_at" in body
    assert "Child 上行转发" in body
    assert "showToast" in body
    assert "runUiAction" in body
    assert "autoClusterLayout" in body
    assert "自动聚类" in body
    assert "selectRect" in body
    assert "openBatchMenu" in body
    assert "batchPingSelected" in body
    assert "batchCommandSelected" in body
    assert "selectedNodes" in body
    assert "selectionBar" in body
    assert "confirmAction" in body
    assert "LINK_HISTORY_KEY" in body
    assert "linkHistorySvg" in body
    assert "isNodeLinkLost" in body
    assert "断链 / 失去消息" in body
    assert "批量操作" in body
    assert "storage-kv-shell" not in body
    assert "qFilterInput" not in body
    assert "GSD 分析" not in body
    assert "setDataPage" not in body


def test_distributed_data_panel_kv_browser_markers():
    panel_path = Path(__file__).resolve().parents[2] / "resources" / "admin-panel" / "panel" / "distributed_data.html"
    body = panel_path.read_text(encoding="utf-8")
    assert "storage-kv-shell" in body
    assert "Key Explorer" in body
    assert "GSD 分析" in body
    assert "qFilterInput" in body
    assert "kv-filter-chip" in body
    assert "dataNamespaceCount" in body
    assert "setDataPage" in body
    assert "/distributed/gsd/items" in body
    assert "/distributed/gsd/summary" in body
    assert "/distributed/gsd/delete-by-prefix" in body


def test_prune_internal_paths_from_openapi_removes_all_internal_prefix_routes():
    source = {
        "paths": {
            "/api/health": {
                "get": {
                    "tags": ["Public"],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/PublicResponse"},
                                },
                            },
                        },
                    },
                },
            },
            "/_internal/admin/openapi.json": {
                "get": {
                    "tags": ["Admin"],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/InternalResponse"},
                                },
                            },
                        },
                    },
                },
            },
            "/rtc_room/create": {
                "post": {
                    "tags": ["RTC"],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/InternalRtcResponse"},
                                },
                            },
                        },
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "PublicResponse": {"type": "object"},
                "InternalResponse": {"type": "object"},
                "InternalRtcResponse": {"type": "object"},
            },
        },
        "tags": [
            {"name": "Public"},
            {"name": "Admin"},
            {"name": "RTC"},
        ],
    }

    pruned = _prune_internal_paths_from_openapi(source, internal_path_prefix="/_internal")

    assert set(pruned["paths"].keys()) == {"/api/health"}
    assert pruned["components"]["schemas"] == {"PublicResponse": {"type": "object"}}
    assert pruned["tags"] == [{"name": "Public"}]


class TestPanelPageRoutes(FullAppTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._admin_apikey = await create_apikey(
            name="panel ui route test",
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

    async def test_rtc_room_runtime_routes_exist(self):
        shared_room_page = await self._client.get("/shared/components/rtc_room.html")
        self.assertEqual(shared_room_page.status_code, 200)
        self.assertIn("__RTC_ROOM_URLS__", shared_room_page.text)

        room_page = await self._client.get("/rtc_room/room")
        self.assertEqual(room_page.status_code, 200)
        self.assertIn("__RTC_ROOM_URLS__", room_page.text)

        test_audio = await self._client.get("/rtc_room/test-audio/__missing__.mp3")
        self.assertEqual(test_audio.status_code, 404)

        create = await self._client.post("/rtc_room/create", json={})
        self.assertEqual(create.status_code, 422)

        join = await self._client.post("/rtc_room/join", json={})
        self.assertEqual(join.status_code, 422)

    async def test_nested_vendor_assets_are_served(self):
        for path in (
            "/vendor/tailwindcss/tailwind.css",
            "/vendor/tailwindcss/tailwind.min.css",
            "/vendor/chart/chart.js",
            "/vendor/chart/chart.min.js",
            "/vendor/xterm/xterm.min.js",
        ):
            r = await self._client.get(path)
            self.assertEqual(r.status_code, 200, path)

    async def test_panel_login_page(self):
        r = await self._client.get("/_internal/admin/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))

    async def test_panel_main_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/panel", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("/vendor/tailwindcss/tailwindcss-cdn.js", r.text)
        self.assertIn("/vendor/chart/chart.js", r.text)
        self.assertIn("proj-admin-auth-expired", r.text)
        self.assertIn("clearPanelState()", r.text)
        self.assertIn("nav-backend-distributed", r.text)
        self.assertIn("backend-distributed-sub-group", r.text)
        self.assertIn("nav-backend-distributed-nodes", r.text)
        self.assertIn("nav-backend-distributed-data", r.text)
        self.assertIn("nav-pluginlab", r.text)
        self.assertNotIn("nav-rooms", r.text)
        self.assertIn("nav-backend-permission", r.text)
        self.assertIn("backend-permission-sub-group", r.text)
        self.assertNotIn("/_internal/admin/test/tools", r.text)
        self.assertNotIn("/_internal/admin/test/question", r.text)
        self.assertNotIn("/_internal/admin/test/render", r.text)
        self.assertNotIn("/_internal/admin/test/agent", r.text)
        self.assertNotIn("/_internal/admin/test/papers", r.text)
        self.assertNotIn("/api/papers/types", r.text)
        self.assertNotIn("/api/papers/generate-and-render", r.text)

    async def test_missing_room_detail_and_delete_routes_exist(self):
        headers = self._admin_headers()

        detail = await self._client.get("/_internal/admin/api/rooms/__missing__", headers=headers)
        self.assertEqual(detail.status_code, 404)

        deleted = await self._client.delete("/_internal/admin/api/rooms/__missing__", headers=headers)
        self.assertEqual(deleted.status_code, 404)

    async def test_panel_distributed_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/panel/distributed.html", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        body = r.text
        self.assertTrue("分布式网络" in body or "distributed" in body.lower())
        self.assertIn("mParentId", body)
        self.assertIn("management.can_manage", body)
        self.assertIn("管理路径", body)
        self.assertIn("pingNode", body)
        self.assertIn("openGraphSearch", body)
        self.assertIn("friend-friend", body)

    async def test_panel_distributed_data_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/panel/distributed/data", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        body = r.text
        self.assertIn("storage-kv-shell", body)
        self.assertIn("Key Explorer", body)
        self.assertIn("GSD 分析", body)
        self.assertIn("qFilterInput", body)
        self.assertIn("/distributed/gsd/items", body)

    async def test_panel_backend_overview_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/panel/backend/overview", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("proj-admin-auth-expired", r.text)

    async def test_panel_system_overview_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/panel/system/overview", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("proj-admin-auth-expired", r.text)
        self.assertIn("内网 IP", r.text)
        self.assertIn("公网 IP", r.text)

    async def test_panel_ai_services_overview_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/panel/ai-services/overview", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("proj-admin-auth-expired", r.text)

    async def test_plugin_panel_list_api_localizes_metadata(self):
        clear_plugins()
        headers = self._admin_headers()

        class DemoPluginConfig(BaseModel):
            enabled: bool
            label: str

        @register_plugin
        class DemoPlugin:
            Name = {"zh-cn": "示例插件", "zh-tw": "示例外掛", "en": "Demo Plugin"}
            Description = {"zh-cn": "用于测试插件列表", "zh-tw": "用於測試插件列表", "en": "Used to test plugin listing"}
            Type = "main-and-worker"
            ConfigType = DemoPluginConfig

            @classmethod
            def Create(cls, create_in: str, config=None, core_module=None):
                return cls()

            def admin_panel(self):
                return "<div>demo panel</div>"

        @register_plugin
        class MainOnlyPlugin:
            Name = "main-only"
            Type = "main-only"

            @classmethod
            def Create(cls, create_in: str, config=None, core_module=None):
                return cls()

        try:
            configure_plugin(DemoPlugin, {"enabled": True, "label": "live"})
            response = await self._client.get("/_internal/admin/api/plugins?lang=zh-tw", headers=headers)
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("plugins", payload)
            self.assertEqual(payload["plugins"][0]["name"], "示例外掛")
            self.assertEqual(payload["plugins"][0]["description"], "用於測試插件列表")
            self.assertTrue(payload["plugins"][0]["has_panel"])
            self.assertTrue(payload["plugins"][0]["has_config"])
            self.assertEqual(payload["plugins"][0]["current_config"], {"enabled": True, "label": "live"})
            self.assertEqual(payload["plugins"][0]["config_fields"][0]["name"], "enabled")
            self.assertEqual(payload["plugins"][1]["name"], "main-only")
            self.assertFalse(payload["plugins"][1]["has_panel"])
        finally:
            clear_plugins()

    async def test_plugin_panel_view_route_renders_selected_plugin(self):
        clear_plugins()
        headers = self._admin_headers()

        @register_plugin
        class PanelPlugin:
            Name = {"zh-cn": "面板插件", "zh-tw": "面板外掛", "en": "Panel Plugin"}
            Description = {"zh-cn": "带有独立 panel", "zh-tw": "帶有獨立 panel", "en": "Has a dedicated panel"}
            Type = "main-and-worker"

            @classmethod
            def Create(cls, create_in: str, config=None, core_module=None):
                return cls()

            def admin_panel(self):
                return '<div id="plugin-panel-content">plugin-body</div>'

        @register_plugin
        class MainOnlyPlugin:
            Name = {"zh-cn": "主进程插件", "zh-tw": "主行程外掛", "en": "Main Plugin"}
            Type = "main-only"

            @classmethod
            def Create(cls, create_in: str, config=None, core_module=None):
                return cls()

        try:
            panel_key = quote(get_plugin_key(PanelPlugin), safe="")
            panel_response = await self._client.get(
                f"/_internal/admin/panel/plugins/view/{panel_key}?lang=zh-tw",
                headers=headers,
            )
            self.assertEqual(panel_response.status_code, 200)
            self.assertIn("plugin-panel-content", panel_response.text)
            self.assertIn("plugin-body", panel_response.text)

            main_only_key = quote(get_plugin_key(MainOnlyPlugin), safe="")
            placeholder_response = await self._client.get(
                f"/_internal/admin/panel/plugins/view/{main_only_key}?lang=zh-tw",
                headers=headers,
            )
            self.assertEqual(placeholder_response.status_code, 200)
            self.assertIn("主行程外掛", placeholder_response.text)
            self.assertIn("不提供 worker 側管理面板", placeholder_response.text)
        finally:
            clear_plugins()

    async def test_plugin_runtime_upload_route_inspects_then_registers_plugin_file(self):
        clear_plugins()
        headers = self._admin_headers()
        saved_env = {
            '__CONFIG_FILE_PATH__': str(os.environ.get('__CONFIG_FILE_PATH__') or ''),
            '__WRITABLE_CONFIG_FILE_PATH__': str(os.environ.get('__WRITABLE_CONFIG_FILE_PATH__') or ''),
            '__CONFIG__': str(os.environ.get('__CONFIG__') or ''),
        }
        saved_config = Config.__Instance__  # type: ignore[attr-defined]

        try:
            with tempfile.TemporaryDirectory(prefix='plugin_upload_route_') as tmp_dir:
                config_path = Path(tmp_dir) / 'server.yaml'
                runtime_config = Config(plugin_paths=[])
                Config.__Instance__ = runtime_config  # type: ignore[attr-defined]
                runtime_config.write_to_path(config_path)
                os.environ['__CONFIG_FILE_PATH__'] = str(config_path)
                os.environ['__WRITABLE_CONFIG_FILE_PATH__'] = str(config_path)
                os.environ['__CONFIG__'] = runtime_config.model_dump_json(indent=None)

                plugin_source = (
                    'class UploadedPlugin:\n'
                    '    Name = "uploaded-plugin"\n'
                    '    Type = "main-only"\n\n'
                    '    @classmethod\n'
                    '    def Create(cls, create_in, config=None, core_module=None):\n'
                    '        return cls()\n'
                ).encode('utf-8')

                response = await self._client.post(
                    '/_internal/admin/api/plugins/runtime/upload',
                    headers=headers,
                    data={'relative_paths_json': '["uploaded_plugin.py"]'},
                    files=[('files', ('uploaded_plugin.py', plugin_source, 'text/x-python'))],
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload['uploaded_path'].endswith('uploaded_plugin.py'))
                self.assertEqual(len(payload['plugin_keys']), 1)
                self.assertTrue(str(payload['plugin_keys'][0]).endswith('.UploadedPlugin'))
                self.assertIn('plugins', payload)
                self.assertEqual(payload['plugins'][0]['key'], payload['plugin_keys'][0])
                self.assertEqual(payload['plugins'][0]['name'], 'uploaded-plugin')

                register_response = await self._client.post(
                    '/_internal/admin/api/plugins/runtime/register',
                    headers=headers,
                    json={'path': payload['uploaded_path'], 'plugin_configs': {}},
                )
                self.assertEqual(register_response.status_code, 200)
                register_payload = register_response.json()
                self.assertEqual(register_payload['action'], 'register')
                self.assertTrue(register_payload['saved'])

                list_response = await self._client.get('/_internal/admin/api/plugins', headers=headers)
                self.assertEqual(list_response.status_code, 200)
                names = [item['name'] for item in list_response.json()['plugins']]
                self.assertIn('uploaded-plugin', names)

                loaded_config = Config.Load(config_path, set_global=False)
                self.assertEqual(loaded_config.plugin_paths, [payload['uploaded_path']])
        finally:
            clear_plugins()
            for key, value in saved_env.items():
                if value:
                    os.environ[key] = value
                else:
                    os.environ.pop(key, None)
            Config.__Instance__ = saved_config  # type: ignore[attr-defined]

    async def test_plugin_runtime_item_restart_and_delete_manage_registered_plugin(self):
        clear_plugins()
        headers = self._admin_headers()
        saved_env = {
            '__CONFIG_FILE_PATH__': str(os.environ.get('__CONFIG_FILE_PATH__') or ''),
            '__WRITABLE_CONFIG_FILE_PATH__': str(os.environ.get('__WRITABLE_CONFIG_FILE_PATH__') or ''),
            '__CONFIG__': str(os.environ.get('__CONFIG__') or ''),
        }
        saved_config = Config.__Instance__  # type: ignore[attr-defined]

        try:
            with tempfile.TemporaryDirectory(prefix='plugin_manage_route_') as tmp_dir:
                config_path = Path(tmp_dir) / 'server.yaml'
                runtime_config = Config(plugin_paths=[])
                Config.__Instance__ = runtime_config  # type: ignore[attr-defined]
                runtime_config.write_to_path(config_path)
                os.environ['__CONFIG_FILE_PATH__'] = str(config_path)
                os.environ['__WRITABLE_CONFIG_FILE_PATH__'] = str(config_path)
                os.environ['__CONFIG__'] = runtime_config.model_dump_json(indent=None)

                plugin_path = Path(tmp_dir) / 'managed_plugin.py'
                plugin_path.write_text(
                    (
                        'from pydantic import BaseModel\n\n'
                        'class ManagedConfig(BaseModel):\n'
                        '    enabled: bool\n'
                        '    label: str\n\n'
                        'class ManagedPlugin:\n'
                        '    Key = "managed-plugin"\n'
                        '    Name = "managed-plugin"\n'
                        '    Type = "main-only"\n'
                        '    ConfigType = ManagedConfig\n\n'
                        '    @classmethod\n'
                        '    def Create(cls, create_in, config=None, core_module=None):\n'
                        '        return cls()\n'
                    ),
                    encoding='utf-8',
                )

                register_response = await self._client.post(
                    '/_internal/admin/api/plugins/runtime/register',
                    headers=headers,
                    json={'path': str(plugin_path), 'plugin_configs': {'managed-plugin': {'enabled': True, 'label': 'alpha'}}},
                )
                self.assertEqual(register_response.status_code, 200)

                list_response = await self._client.get('/_internal/admin/api/plugins', headers=headers)
                self.assertEqual(list_response.status_code, 200)
                plugin_item = next(item for item in list_response.json()['plugins'] if item['key'] == 'managed-plugin')
                self.assertEqual(plugin_item['current_config'], {'enabled': True, 'label': 'alpha'})
                self.assertEqual(plugin_item['source_path'], str(plugin_path.resolve()))

                restart_response = await self._client.post(
                    '/_internal/admin/api/plugins/runtime/restart-item',
                    headers=headers,
                    json={'plugin_key': 'managed-plugin', 'config': {'enabled': False, 'label': 'beta'}},
                )
                self.assertEqual(restart_response.status_code, 200)
                self.assertEqual(restart_response.json()['action'], 'restart')

                refreshed = await self._client.get('/_internal/admin/api/plugins', headers=headers)
                refreshed_item = next(item for item in refreshed.json()['plugins'] if item['key'] == 'managed-plugin')
                self.assertEqual(refreshed_item['current_config'], {'enabled': False, 'label': 'beta'})

                delete_response = await self._client.post(
                    '/_internal/admin/api/plugins/runtime/delete-item',
                    headers=headers,
                    json={'plugin_key': 'managed-plugin'},
                )
                self.assertEqual(delete_response.status_code, 200)
                self.assertEqual(delete_response.json()['action'], 'delete')

                final_list = await self._client.get('/_internal/admin/api/plugins', headers=headers)
                self.assertEqual(final_list.status_code, 200)
                self.assertNotIn('managed-plugin', [item['key'] for item in final_list.json()['plugins']])
        finally:
            clear_plugins()
            for key, value in saved_env.items():
                if value:
                    os.environ[key] = value
                else:
                    os.environ.pop(key, None)
            Config.__Instance__ = saved_config  # type: ignore[attr-defined]

    async def test_ai_test_pages_use_current_api_prefix(self):
        headers = self._admin_headers()

        index_page = await self._client.get("/_internal/admin/test/ai", headers=headers)
        self.assertEqual(index_page.status_code, 200)
        self.assertIn("/ai/completion/{service|client}/{key}/translate", index_page.text)
        self.assertNotIn("/api/ai/", index_page.text)

        chat = await self._client.get("/_internal/admin/test/ai/chat", headers=headers)
        self.assertEqual(chat.status_code, 200)
        self.assertIn("/ai/completion/service", chat.text)
        self.assertNotIn("/api/ai/", chat.text)

        t2s = await self._client.get("/_internal/admin/test/ai/t2s", headers=headers)
        self.assertEqual(t2s.status_code, 200)
        self.assertIn("/ai/t2s/{service|client}/{key}/stream", t2s.text)
        self.assertNotIn("/api/ai/", t2s.text)

        t2img = await self._client.get("/_internal/admin/test/ai/t2img", headers=headers)
        self.assertEqual(t2img.status_code, 200)
        self.assertIn("t2img/service/default/${suffix}", t2img.text)
        self.assertIn("initServiceTargetControls('t2img'", t2img.text)
        self.assertNotIn("/api/ai/", t2img.text)

    async def test_removed_legacy_tools_pages_return_not_found(self):
        headers = self._admin_headers()

        for path in (
            "/_internal/admin/test/tools",
            "/_internal/admin/test/tools/web_searcher",
            "/_internal/admin/test/question",
            "/_internal/admin/test/render",
            "/_internal/admin/test/agent",
            "/_internal/admin/test/papers",
        ):
            response = await self._client.get(path, headers=headers)
            self.assertEqual(response.status_code, 404, path)

    async def test_panel_storage_kv_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/storage/kv", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))

    async def test_panel_log_overview_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/log/overview", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
