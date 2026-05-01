from eshop_base import ShopRouteBase


class ShopProductsRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, category: str = "") -> dict[str, object]:
        products = list(self._get_products().values())
        if category and category != "all":
            products = [p for p in products if p.get("category") == category]
        return {"products": products}
