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
        self.assertIn("/rtc_room/create", shared_room_page.text)

        room_page = await self._client.get("/rtc_room/room")
        self.assertEqual(room_page.status_code, 200)
        self.assertIn("/api/test-audio/test.mp3", room_page.text)

        test_audio = await self._client.get("/api/test-audio/__missing__.mp3")
        self.assertEqual(test_audio.status_code, 404)

        create = await self._client.post("/api/rooms/create", json={})
        self.assertEqual(create.status_code, 422)

        join = await self._client.post("/api/rooms/join", json={})
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
        self.assertIn("node-parent-id", body)
        self.assertIn("management.can_manage", body)
        self.assertIn("管理路径", body)
        self.assertIn("pingNode", body)
        self.assertIn("联通性测试", body)
        self.assertIn("proj-admin-auth-expired", body)

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
