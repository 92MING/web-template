from fastapi import Request
from eshop_base import ShopRouteBase, MERCHANT_ROLE_NAME, ADMIN_ROLE_NAME


class ShopMerchantProductsRoute(ShopRouteBase):
    Tags = "Shop"

    def _check_merchant(self, request):
        user = self._get_current_user(request)
        if not user:
            return None, {"ok": False, "error": "Not logged in"}
        role = user.get("role", "")
        if role not in (MERCHANT_ROLE_NAME, ADMIN_ROLE_NAME):
            return None, {"ok": False, "error": "Permission denied"}
        return user, None

    async def get(self, request: Request) -> dict[str, object]:
        user, error = self._check_merchant(request)
        if error:
            return error
        products = list(self._get_products().values())
        return {"ok": True, "products": products}

    async def post(self, request: Request) -> dict[str, object]:
        user, error = self._check_merchant(request)
        if error:
            return error
        body = await request.json()
        product_id = body.get("id", "").strip()
        if not product_id:
            return {"ok": False, "error": "Product ID required"}
        products = self._get_products()
        existing = products.get(product_id)
        product = {
            "id": product_id,
            "name": body.get("name", existing.get("name", "") if existing else ""),
            "price": int(body.get("price", existing.get("price", 0) if existing else 0)),
            "old_price": int(body.get("old_price", existing.get("old_price", 0) if existing else 0)),
            "image": body.get("image", existing.get("image", "") if existing else ""),
            "category": body.get("category", existing.get("category", "") if existing else ""),
            "stock": int(body.get("stock", existing.get("stock", 0) if existing else 0)),
            "sales": int(body.get("sales", existing.get("sales", 0) if existing else 0)),
            "rating": float(body.get("rating", existing.get("rating", 4.5) if existing else 4.5)),
            "description": body.get("description", existing.get("description", "") if existing else ""),
            "tags": body.get("tags", existing.get("tags", []) if existing else []),
        }
        products[product_id] = product
        self.shared_dict.set("shop:products", products)
        return {"ok": True, "product": product}

    async def delete(self, request: Request) -> dict[str, object]:
        user, error = self._check_merchant(request)
        if error:
            return error
        body = await request.json()
        product_id = body.get("id", "").strip()
        if not product_id:
            return {"ok": False, "error": "Product ID required"}
        products = self._get_products()
        if product_id in products:
            del products[product_id]
            self.shared_dict.set("shop:products", products)
        return {"ok": True}
