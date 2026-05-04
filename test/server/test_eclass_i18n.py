# -*- coding: utf-8 -*-
"""Verify e-class i18n now ships from a static public catalog."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app"))

from core.server.app import create_app
from core.server.data_types.config import Config


class EclassI18nTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        import core.server.app as core_app_module

        core_app_module._app = None
        cfg = Config()
        cfg.server_config.extra_app_paths = [str(Path(__file__).resolve().parent.parent.parent / "example" / "e-class")]
        cfg.server_config.extra_public_paths = [str(Path(__file__).resolve().parent.parent.parent / "example" / "e-class" / "public")]
        cls.app = create_app(config=cfg)

    async def asyncSetUp(self):
        import httpx

        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_translate_catalog_file_served(self):
        response = await self.client.get("/translate.json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["eclass.title"]["zh_cn"], "在线课堂")
        self.assertEqual(data["eclass.title"]["en"], "Online Classroom")
        self.assertEqual(data["eclass.loading"]["zh_cn"], "加载中...")
        self.assertEqual(data["eclass.theme_dark"]["en"], "Dark")

    async def test_translate_catalog_contains_expected_keys(self):
        response = await self.client.get("/translate.json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("eclass.nonexistent", data)
        self.assertIn("eclass.page_info", data)
        self.assertIn("eclass.create_success", data)
        self.assertGreaterEqual(len(data), 100)

    async def test_public_pages_use_static_translate_catalog(self):
        for path in (
            "/announcements.html",
            "/homework-list.html",
            "/grades.html",
            "/courses.html",
            "/teacher-classrooms.html",
            "/course-detail.html",
            "/classroom.html",
        ):
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            if path == "/classroom.html":
                self.assertIn("classroom-app.js", response.text, path)
                continue
            self.assertIn("'/translate.json", response.text, path)

    async def test_default_i18n_endpoint_still_available(self):
        response = await self.client.get("/i18n/en")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), dict)


if __name__ == "__main__":
    unittest.main()
