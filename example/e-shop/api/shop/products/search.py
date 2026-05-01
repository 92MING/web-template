from eshop_base import ShopRouteBase


class ShopProductsSearchRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, q: str = "") -> dict[str, object]:
        products = list(self._get_products().values())
        query = q.strip().lower()
        if query:
            products = [
                p for p in products
                if query in p["name"].lower()
                or query in p.get("category", "").lower()
                or query in p.get("description", "").lower()
                or any(query in t.lower() for t in p.get("tags", []))
            ]
        return {"products": products}
