import random
from eshop_base import ShopRouteBase


class ShopRecommendationsRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, user_id: str = "", category: str = "", limit: int = 4) -> dict[str, object]:
        products = list(self._get_products().values())
        if category and category != "all":
            products = [p for p in products if p.get("category") == category]
        # Simple recommendation: top sales + random mix
        products.sort(key=lambda p: p.get("sales", 0), reverse=True)
        top = products[:limit]
        if len(top) < limit:
            remaining = [p for p in products if p not in top]
            random.shuffle(remaining)
            top.extend(remaining[:limit - len(top)])
        return {"products": top}
