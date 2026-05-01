from fastapi import Request
from eshop_base import ShopRouteBase


class ShopFavoritesRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, user_id: str) -> dict[str, object]:
        key = f"shop:favorites:{user_id}"
        favorites: list[str] = list(self.shared_dict.get(key, []))
        products = self._get_products()
        items = [products.get(pid) for pid in favorites if pid in products]
        return {"items": items, "product_ids": favorites}

    async def post(self, request: Request) -> dict[str, object]:
        body = await request.json()
        user_id = body.get("user_id", "")
        product_id = body.get("product_id", "")
        key = f"shop:favorites:{user_id}"
        favorites: list[str] = list(self.shared_dict.get(key, []))
        if product_id not in favorites:
            favorites.append(product_id)
            self.shared_dict.set(key, favorites)
        return {"ok": True, "product_ids": favorites}

    async def delete(self, request: Request) -> dict[str, object]:
        body = await request.json()
        user_id = body.get("user_id", "")
        product_id = body.get("product_id", "")
        key = f"shop:favorites:{user_id}"
        favorites: list[str] = list(self.shared_dict.get(key, []))
        if product_id:
            favorites = [pid for pid in favorites if pid != product_id]
        else:
            favorites = []
        self.shared_dict.set(key, favorites)
        return {"ok": True, "product_ids": favorites}
