# -*- coding: utf-8 -*-
"""Tests for cached public fallback after route miss."""

import sys
import tempfile
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app"))

import httpx

from core.server.app import create_app
from core.server.data_types.config import Config


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class PublicFallbackTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        import core.server.app as core_app_module

        core_app_module._app = None
        cls._tmp_dir_obj = tempfile.TemporaryDirectory(prefix="proj_public_fallback_")
        root = Path(cls._tmp_dir_obj.name)
        cls._extra_app_dir = root / "extra-app"
        cls._extra_public_dir = root / "extra-public"
        (cls._extra_app_dir / "posts" / "_slug_").mkdir(parents=True)
        (cls._extra_app_dir / "_private" / "_slug_").mkdir(parents=True)
        (cls._extra_public_dir / "docs").mkdir(parents=True)
        (cls._extra_public_dir / "posts" / "_slug_").mkdir(parents=True)
        (cls._extra_public_dir / "articles" / "_article_id_").mkdir(parents=True)
        (cls._extra_public_dir / "downloads").mkdir(parents=True)
        (cls._extra_public_dir / "mobile").mkdir(parents=True)
        (cls._extra_public_dir / "i18n" / "en").mkdir(parents=True)
        (cls._extra_public_dir / "vendor" / "plain").mkdir(parents=True)
        (cls._extra_public_dir / "vendor" / "minified").mkdir(parents=True)

        (cls._extra_app_dir / "posts" / "_slug_" / "index.html").write_text(
            "<html><body>APP DYNAMIC POST</body></html>",
            encoding="utf-8",
        )
        (cls._extra_app_dir / "_private" / "_slug_" / "index.html").write_text(
            "<html><body>PRIVATE APP DYNAMIC POST</body></html>",
            encoding="utf-8",
        )

        (cls._extra_public_dir / "index.html").write_text(
            "<html><body>EXTRA ROOT INDEX</body></html>",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "docs" / "index.html").write_text(
            "<html><body>EXTRA DOCS INDEX</body></html>",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "posts" / "_slug_" / "index.html").write_text(
            "<html><body>PUBLIC DYNAMIC POST</body></html>",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "articles" / "_article_id_" / "index.html").write_text(
            "<html><body>PUBLIC DYNAMIC ARTICLE</body></html>",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "downloads" / "_file_id_.txt").write_text(
            "PUBLIC DYNAMIC FILE",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "mobile" / "index.html").write_text(
            "<html><body>DESKTOP MOBILE PAGE</body></html>",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "mobile" / "index.m.html").write_text(
            "<html><body>MOBILE MOBILE PAGE</body></html>",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "i18n" / "en" / "index.html").write_text(
            "<html><body>SHOULD NOT WIN</body></html>",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "vendor" / "plain" / "only.js").write_text(
            "console.log('plain-only');",
            encoding="utf-8",
        )
        (cls._extra_public_dir / "vendor" / "minified" / "only.min.js").write_text(
            "console.log('minified-only');",
            encoding="utf-8",
        )

        cfg = Config()
        cfg.server_config.extra_app_paths = [str(cls._extra_app_dir)]
        cfg.server_config.extra_public_paths = [str(cls._extra_public_dir)]
        cls.app = create_app(config=cfg)

    @classmethod
    def tearDownClass(cls):
        import core.server.app as core_app_module

        core_app_module._app = None
        if getattr(cls, "_tmp_dir_obj", None) is not None:
            cls._tmp_dir_obj.cleanup()

    async def asyncSetUp(self):
        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_app_root_precedes_extra_public_root(self):
        response = await self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("HELLO WORLD", response.text)
        self.assertNotIn("EXTRA ROOT INDEX", response.text)

    async def test_directory_path_without_trailing_slash_serves_index_html(self):
        response = await self.client.get("/docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn("EXTRA DOCS INDEX", response.text)

    async def test_app_dynamic_html_precedes_public_dynamic_html(self):
        response = await self.client.get("/posts/hello-next-style")
        self.assertEqual(response.status_code, 200)
        self.assertIn("APP DYNAMIC POST", response.text)
        self.assertNotIn("PUBLIC DYNAMIC POST", response.text)

    async def test_public_dynamic_html_and_files_are_served(self):
        html_response = await self.client.get("/articles/intro-to-fallback")
        self.assertEqual(html_response.status_code, 200)
        self.assertIn("PUBLIC DYNAMIC ARTICLE", html_response.text)

        file_response = await self.client.get("/downloads/monthly-report.txt")
        self.assertEqual(file_response.status_code, 200)
        self.assertIn("PUBLIC DYNAMIC FILE", file_response.text)

    async def test_private_app_dynamic_html_is_not_served(self):
        response = await self.client.get("/_private/secret")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("PRIVATE APP DYNAMIC POST", response.text)

    async def test_mobile_index_merge_still_applies_for_directory_fallback(self):
        response = await self.client.get("/mobile")
        self.assertEqual(response.status_code, 200)
        self.assertIn("__mobile_branch__", response.text)
        self.assertIn("DESKTOP MOBILE PAGE", response.text)
        self.assertIn("MOBILE MOBILE PAGE", response.text)

    async def test_registered_route_still_beats_public_fallback(self):
        response = await self.client.get("/i18n/en")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.headers.get("content-type", ""))
        self.assertNotIn("SHOULD NOT WIN", response.text)

    async def test_vendor_minified_asset_fallbacks_are_served(self):
        js_response = await self.client.get("/vendor/chart/chart.min.js")
        self.assertEqual(js_response.status_code, 200)
        self.assertIn("javascript", js_response.headers.get("content-type", ""))

        css_response = await self.client.get("/vendor/tailwindcss/tailwind.min.css")
        self.assertEqual(css_response.status_code, 200)
        self.assertIn("text/css", css_response.headers.get("content-type", ""))

    async def test_minified_asset_fallbacks_are_bidirectional(self):
        min_to_plain = await self.client.get("/vendor/plain/only.min.js")
        self.assertEqual(min_to_plain.status_code, 200)
        self.assertIn("plain-only", min_to_plain.text)

        plain_to_min = await self.client.get("/vendor/minified/only.js")
        self.assertEqual(plain_to_min.status_code, 200)
        self.assertIn("minified-only", plain_to_min.text)

    async def test_test_media_is_not_global_public_route(self):
        response = await self.client.get("/test-media/sample-video.mp4")
        self.assertEqual(response.status_code, 404)

class GalleryTestMediaRouteTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        import core.server.app as core_app_module

        core_app_module._app = None
        cfg = Config()
        cfg.server_config.extra_app_paths = [str(PROJECT_ROOT / "example" / "gallery")]
        cfg.server_config.extra_public_paths = [str(PROJECT_ROOT / "example" / "gallery" / "public")]
        cls.app = create_app(config=cfg)

    @classmethod
    def tearDownClass(cls):
        import core.server.app as core_app_module

        core_app_module._app = None

    async def asyncSetUp(self):
        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_gallery_serves_test_media_from_resources(self):
        response = await self.client.get("/test-media/gallery-sample-video.mp4")
        self.assertEqual(response.status_code, 200)
        self.assertIn("video", response.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()