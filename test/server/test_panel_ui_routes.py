# -*- coding: utf-8 -*-
"""Tests for admin panel HTML page routes."""

import sys
from pathlib import Path

_server_dir = Path(__file__).resolve().parent.parent.parent / "app" / "core" / "server"
if str(_server_dir.parent.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent.parent))
if str(_server_dir.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent))

from _test_helpers import FullAppTestBase
from core.server.data_types.apikey import create_apikey, delete_apikey
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
            "/_internal/rtc_room/create": {
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
        self.assertEqual(shared_room_page.status_code, 404)

        room_page = await self._client.get("/_internal/rtc_room/room")
        self.assertEqual(room_page.status_code, 200)
        self.assertIn("__RTC_ROOM_URLS__", room_page.text)

        test_audio = await self._client.get("/_internal/rtc_room/test-audio/__missing__.mp3")
        self.assertEqual(test_audio.status_code, 404)

        create = await self._client.post("/_internal/rtc_room/create", json={})
        self.assertEqual(create.status_code, 422)

        join = await self._client.post("/_internal/rtc_room/join", json={})
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

    async def test_panel_ai_services_overview_page(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/panel/ai-services/overview", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("proj-admin-auth-expired", r.text)

    async def test_ai_test_pages_use_current_api_prefix(self):
        headers = self._admin_headers()

        index_page = await self._client.get("/_internal/admin/test/ai", headers=headers)
        self.assertEqual(index_page.status_code, 200)
        self.assertIn("/ai/translate", index_page.text)
        self.assertNotIn("/api/ai/", index_page.text)

        chat = await self._client.get("/_internal/admin/test/ai/chat", headers=headers)
        self.assertEqual(chat.status_code, 200)
        self.assertIn("/ai/complete", chat.text)
        self.assertNotIn("/api/ai/", chat.text)

        t2s = await self._client.get("/_internal/admin/test/ai/t2s", headers=headers)
        self.assertEqual(t2s.status_code, 200)
        self.assertIn("/ai/t2s/stream", t2s.text)
        self.assertNotIn("/api/ai/", t2s.text)

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
