# -*- coding: utf-8 -*-
"""Exercise every e-shop example page and API route."""

import importlib.util
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app"))

from core.server.app import create_app
from core.server.data_types.config import Config
from core.server.translate import _registry


ROOT = Path(__file__).resolve().parent.parent.parent
ESHOP_ROOT = ROOT / "example" / "e-shop"
ESHOP_PUBLIC = ESHOP_ROOT / "public"


class EshopFullRoutesTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        _registry.clear()
        init_py = ESHOP_ROOT / "api" / "__init__.py"
        spec = importlib.util.spec_from_file_location("eshop_api_full_routes", init_py)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

    async def asyncSetUp(self):
        import core.server.app as core_app_module
        import httpx

        core_app_module._app = None
        cfg = Config()
        cfg.server_config.extra_app_paths = [str(ESHOP_ROOT), str(ESHOP_PUBLIC)]
        cfg.server_config.extra_public_paths = [str(ESHOP_PUBLIC)]
        self.app = create_app(config=cfg)
        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def _login(self, username: str, password: str = "123456") -> tuple[str, dict[str, str]]:
        response = await self.client.post(
            "/api/shop/auth?action=login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["ok"], data)
        token = data["token"]
        return token, {"Authorization": f"Bearer {token}"}

    async def test_all_public_pages_and_assets_are_served(self):
        for html_path in sorted(ESHOP_PUBLIC.glob("*.html")):
            response = await self.client.get(f"/{html_path.name}")
            self.assertEqual(response.status_code, 200, html_path.name)
            self.assertIn("<", response.text, html_path.name)
            self.assertNotIn("Traceback", response.text, html_path.name)
            for icon_tag in re.findall(r"<pt-icon\b[^>]*>", response.text):
                icon_name_match = re.search(r'name="([^"]+)"', icon_tag)
                if not icon_name_match:
                    continue
                variant_match = re.search(r'variant="([^"]+)"', icon_tag)
                icon_variant = variant_match.group(1) if variant_match else "filled"
                icon_path = ROOT / "public" / "icons" / icon_variant / f"{icon_name_match.group(1)}.svg"
                self.assertTrue(icon_path.exists(), f"{html_path.name}: {icon_path}")
            if html_path.name == "index.html":
                self.assertIn("e-Shop", response.text)

        response = await self.client.get("/eshop-utils.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("function", response.text)

        products_response = await self.client.get("/api/shop/products")
        self.assertEqual(products_response.status_code, 200)
        for product in products_response.json()["products"]:
            image = product.get("image")
            if image and image.startswith("/icons/"):
                image_response = await self.client.get(image)
                self.assertEqual(image_response.status_code, 200, image)

    async def test_customer_shopping_flow_uses_every_customer_api(self):
        register_response = await self.client.post(
            "/api/shop/auth?action=register",
            json={"username": "routeuser", "password": "routepass", "role": "customer"},
        )
        self.assertEqual(register_response.status_code, 200, register_response.text)
        register_data = register_response.json()
        self.assertTrue(register_data["ok"], register_data)
        customer_headers = {"Authorization": f"Bearer {register_data['token']}"}

        accounts_response = await self.client.get("/api/shop/auth?action=test_accounts")
        self.assertEqual(accounts_response.status_code, 200)
        self.assertTrue(accounts_response.json()["ok"])

        me_response = await self.client.get("/api/shop/auth?action=me", headers=customer_headers)
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["user"]["user_id"], "routeuser")

        for path in (
            "/api/shop/categories",
            "/api/shop/products",
            "/api/shop/products?category=electronics",
            "/api/shop/products/search?q=耳机",
            "/api/shop/products/p1",
            "/api/shop/products/p1/reviews",
            "/api/shop/recommendations?user_id=routeuser&category=electronics&limit=3",
            "/api/shop/coupons",
            "/api/shop/user/profile?user_id=routeuser",
            "/api/shop/user/orders?user_id=routeuser",
        ):
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIsInstance(response.json(), dict, path)

        profile_response = await self.client.put(
            "/api/shop/user/profile?user_id=routeuser",
            json={"name": "Route User", "phone": "123", "email": "route@example.com", "address": "Test Street"},
        )
        self.assertEqual(profile_response.status_code, 200, profile_response.text)
        self.assertTrue(profile_response.json()["ok"])

        favorite_response = await self.client.post("/api/shop/favorites", json={"user_id": "routeuser", "product_id": "p1"})
        self.assertEqual(favorite_response.status_code, 200, favorite_response.text)
        self.assertTrue(favorite_response.json()["ok"])
        favorite_list_response = await self.client.get("/api/shop/favorites?user_id=routeuser")
        self.assertEqual(favorite_list_response.status_code, 200)
        self.assertIn("p1", favorite_list_response.json()["product_ids"])
        favorite_delete_response = await self.client.request("DELETE", "/api/shop/favorites", json={"user_id": "routeuser", "product_id": "p1"})
        self.assertEqual(favorite_delete_response.status_code, 200, favorite_delete_response.text)
        self.assertTrue(favorite_delete_response.json()["ok"])

        cart_add_response = await self.client.post("/api/shop/cart", json={"user_id": "routeuser", "product_id": "p1", "quantity": 2})
        self.assertEqual(cart_add_response.status_code, 200, cart_add_response.text)
        self.assertTrue(cart_add_response.json()["ok"])
        cart_get_response = await self.client.get("/api/shop/cart?user_id=routeuser")
        self.assertEqual(cart_get_response.status_code, 200)
        self.assertEqual(cart_get_response.json()["items"][0]["quantity"], 2)
        cart_put_response = await self.client.put("/api/shop/cart", json={"user_id": "routeuser", "product_id": "p1", "quantity": 1})
        self.assertEqual(cart_put_response.status_code, 200, cart_put_response.text)
        self.assertTrue(cart_put_response.json()["ok"])

        coupon_response = await self.client.post("/api/shop/coupons", json={"code": "WELCOME", "order_total": 399})
        self.assertEqual(coupon_response.status_code, 200, coupon_response.text)
        self.assertTrue(coupon_response.json()["ok"])

        checkout_response = await self.client.post(
            "/api/shop/checkout",
            json={
                "user_id": "routeuser",
                "items": [{"product_id": "p1", "quantity": 1}],
                "shipping": {"address": "Test Street"},
                "coupon_code": "WELCOME",
            },
        )
        self.assertEqual(checkout_response.status_code, 200, checkout_response.text)
        checkout_data = checkout_response.json()
        self.assertTrue(checkout_data["ok"], checkout_data)
        order_id = checkout_data["order"]["order_id"]

        orders_response = await self.client.get("/api/shop/orders?user_id=routeuser")
        self.assertEqual(orders_response.status_code, 200)
        self.assertEqual(orders_response.json()["orders"][0]["order_id"], order_id)
        order_detail_response = await self.client.get(f"/api/shop/orders/{order_id}?user_id=routeuser")
        self.assertEqual(order_detail_response.status_code, 200)
        self.assertEqual(order_detail_response.json()["order"]["order_id"], order_id)

        review_response = await self.client.post(
            "/api/shop/products/p1/reviews",
            json={"user_id": "routeuser", "rating": 5, "comment": "Works well"},
        )
        self.assertEqual(review_response.status_code, 200, review_response.text)
        self.assertTrue(review_response.json()["ok"])
        invalid_review_response = await self.client.post(
            "/api/shop/products/p1/reviews",
            json={"user_id": "routeuser", "rating": 6, "comment": "Nope"},
        )
        self.assertEqual(invalid_review_response.status_code, 200)
        self.assertFalse(invalid_review_response.json()["ok"])

        cart_delete_response = await self.client.request("DELETE", "/api/shop/cart", json={"user_id": "routeuser"})
        self.assertEqual(cart_delete_response.status_code, 200, cart_delete_response.text)
        self.assertTrue(cart_delete_response.json()["ok"])

    async def test_merchant_routes_enforce_role_and_mutate_catalog(self):
        _, customer_headers = await self._login("customer1")
        _, merchant_headers = await self._login("merchant1")

        denied_response = await self.client.get("/api/shop/merchant/products", headers=customer_headers)
        self.assertEqual(denied_response.status_code, 200)
        self.assertFalse(denied_response.json()["ok"])

        for path in ("/api/shop/merchant/products", "/api/shop/merchant/coupons", "/api/shop/merchant/orders"):
            response = await self.client.get(path, headers=merchant_headers)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.json()["ok"], response.json())

        product_payload = {
            "id": "route-product",
            "name": "Route Product",
            "price": 123,
            "old_price": 156,
            "image": "/icons/filled/shop.svg",
            "category": "electronics",
            "stock": 9,
            "sales": 1,
            "rating": 4.7,
            "description": "Created by full route test",
            "tags": ["route"],
        }
        create_product_response = await self.client.post("/api/shop/merchant/products", json=product_payload, headers=merchant_headers)
        self.assertEqual(create_product_response.status_code, 200, create_product_response.text)
        self.assertTrue(create_product_response.json()["ok"])
        product_response = await self.client.get("/api/shop/products/route-product")
        self.assertEqual(product_response.status_code, 200)
        self.assertEqual(product_response.json()["product"]["name"], "Route Product")
        delete_product_response = await self.client.request("DELETE", "/api/shop/merchant/products", json={"id": "route-product"}, headers=merchant_headers)
        self.assertEqual(delete_product_response.status_code, 200, delete_product_response.text)
        self.assertTrue(delete_product_response.json()["ok"])

        coupon_payload = {"id": "route-coupon", "code": "ROUTE10", "discount": 10, "min_order": 50, "description": "Route coupon"}
        create_coupon_response = await self.client.post("/api/shop/merchant/coupons", json=coupon_payload, headers=merchant_headers)
        self.assertEqual(create_coupon_response.status_code, 200, create_coupon_response.text)
        self.assertTrue(create_coupon_response.json()["ok"])
        coupon_check_response = await self.client.post("/api/shop/coupons", json={"code": "ROUTE10", "order_total": 100})
        self.assertEqual(coupon_check_response.status_code, 200)
        self.assertTrue(coupon_check_response.json()["ok"])
        delete_coupon_response = await self.client.request("DELETE", "/api/shop/merchant/coupons", json={"id": "route-coupon"}, headers=merchant_headers)
        self.assertEqual(delete_coupon_response.status_code, 200, delete_coupon_response.text)
        self.assertTrue(delete_coupon_response.json()["ok"])

    async def test_ai_chat_routes_return_fallback_responses_without_service_config(self):
        response = await self.client.post("/api/shop/ai-chat", json={"message": "shipping"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("reply", response.json())

        stream_response = await self.client.post("/api/shop/ai-chat/stream", json={"message": "shipping"})
        self.assertEqual(stream_response.status_code, 200, stream_response.text)
        self.assertIn("data:", stream_response.text)


if __name__ == "__main__":
    unittest.main()
