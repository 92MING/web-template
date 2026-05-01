from fastapi import Request
from eshop_base import ShopRouteBase


class ShopCartRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, user_id: str) -> dict[str, object]:
        key = f"shop:cart:{user_id}"
        items: list[dict] = list(self.shared_dict.get(key, []))
        # Enrich with product info
        products = self._get_products()
        enriched = []
        for item in items:
            pid = item.get("product_id")
            product = products.get(pid)
            if product:
                enriched.append({
                    **item,
                    "name": product.get("name"),
                    "price": product.get("price"),
                    "image": product.get("image"),
                    "stock": product.get("stock", 0),
                })
        return {"items": enriched}

    async def post(self, request: Request) -> dict[str, object]:
        body = await request.json()
        user_id = body.get("user_id", "")
        product_id = body.get("product_id", "")
        quantity = body.get("quantity", 1)
        product = self._get_product(product_id)
        if not product:
            return {"ok": False, "error": "Product not found"}
        if product.get("stock", 0) < quantity:
            return {"ok": False, "error": "Insufficient stock"}
        key = f"shop:cart:{user_id}"
        items: list[dict] = list(self.shared_dict.get(key, []))
        for item in items:
            if item.get("product_id") == product_id:
                new_qty = item.get("quantity", 0) + quantity
                if product.get("stock", 0) < new_qty:
                    return {"ok": False, "error": "Insufficient stock"}
                item["quantity"] = new_qty
                if item["quantity"] <= 0:
                    items.remove(item)
                break
        else:
            if quantity > 0:
                items.append({"product_id": product_id, "quantity": quantity})
        self.shared_dict.set(key, items)
        return {"ok": True, "items": items}

    async def put(self, request: Request) -> dict[str, object]:
        body = await request.json()
        user_id = body.get("user_id", "")
        product_id = body.get("product_id", "")
        quantity = body.get("quantity", 0)
        product = self._get_product(product_id)
        if not product:
            return {"ok": False, "error": "Product not found"}
        if quantity > 0 and product.get("stock", 0) < quantity:
            return {"ok": False, "error": "Insufficient stock"}
        key = f"shop:cart:{user_id}"
        items: list[dict] = list(self.shared_dict.get(key, []))
        for item in items:
            if item.get("product_id") == product_id:
                if quantity <= 0:
                    items.remove(item)
                else:
                    item["quantity"] = quantity
                break
        self.shared_dict.set(key, items)
        return {"ok": True, "items": items}

    async def delete(self, request: Request) -> dict[str, object]:
        body = await request.json()
        user_id = body.get("user_id", "")
        product_id = body.get("product_id", "")
        key = f"shop:cart:{user_id}"
        items: list[dict] = list(self.shared_dict.get(key, []))
        if product_id:
            items = [i for i in items if i.get("product_id") != product_id]
        else:
            items = []
        self.shared_dict.set(key, items)
        return {"ok": True, "items": items}
