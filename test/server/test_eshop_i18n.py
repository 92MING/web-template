# -*- coding: utf-8 -*-
"""Verify e-shop i18n, auth, search APIs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app"))

import unittest

from core.server.translate import _registry
from core.server.app import create_app
from core.server.data_types.config import Config


class EshopI18nTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        _registry.clear()
        # Import and run e-shop translation registration from api/__init__.py
        init_py = Path(__file__).resolve().parent.parent.parent / "example" / "e-shop" / "api" / "__init__.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("eshop_api", init_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    async def asyncSetUp(self):
        # Bypass global app cache so e-shop routes are discovered
        import core.server.app as core_app_module
        core_app_module._app = None
        cfg = Config()
        eshop_root = Path(__file__).resolve().parent.parent.parent / "example" / "e-shop"
        cfg.server_config.extra_app_paths = [str(eshop_root), str(eshop_root / "public")]
        cfg.server_config.extra_public_paths = [str(eshop_root / "public")]
        self.app = create_app(config=cfg)
        import httpx
        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_i18n_zh_cn_catalog(self):
        r = await self.client.get("/i18n/zh-cn")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("eshop.title", data)
        self.assertEqual(data["eshop.title"], "e-Shop")
        self.assertEqual(data["eshop.loading"], "加载中...")
        self.assertEqual(data["eshop.theme_dark"], "深色")
        self.assertEqual(data["eshop.search"], "搜索")

    async def test_i18n_en_catalog(self):
        r = await self.client.get("/i18n/en")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["eshop.title"], "e-Shop")
        self.assertEqual(data["eshop.loading"], "Loading...")
        self.assertEqual(data["eshop.theme_dark"], "Dark")
        self.assertEqual(data["eshop.search"], "Search")

    async def test_auth_login_demo(self):
        r = await self.client.post("/api/shop/auth?action=login", json={"username": "demo", "password": "demo123"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertIn("token", data)
        self.assertEqual(data["user_id"], "demo")

    async def test_auth_login_wrong_password(self):
        r = await self.client.post("/api/shop/auth?action=login", json={"username": "demo", "password": "wrong"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["ok"])

    async def test_auth_register_and_me(self):
        r = await self.client.post("/api/shop/auth?action=register", json={"username": "testuser99", "password": "testpass"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        token = data["token"]

        r2 = await self.client.get("/api/shop/auth?action=me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r2.status_code, 200)
        data2 = r2.json()
        self.assertTrue(data2["ok"])
        self.assertEqual(data2["user"]["user_id"], "testuser99")

    async def test_product_search(self):
        r = await self.client.get("/api/shop/products/search?q=耳机")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["products"]), 1)
        self.assertEqual(data["products"][0]["id"], "p1")

    async def test_product_search_empty(self):
        r = await self.client.get("/api/shop/products/search?q=不存在的商品")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["products"]), 0)

    async def test_product_search_all(self):
        r = await self.client.get("/api/shop/products/search")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["products"]), 6)

    async def test_all_translations_count(self):
        r = await self.client.get("/i18n/en")
        data = r.json()
        # e-shop registered ~60 keys + framework keys
        self.assertGreaterEqual(len(data), 50)


if __name__ == "__main__":
    unittest.main()
