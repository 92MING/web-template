from eshop_base import ShopRouteBase


class ShopProductDetailRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, product_id: str) -> dict[str, object]:
        product = self._get_product(product_id)
        if not product:
            return {"error": "Product not found"}
        reviews = self.shared_dict.get(f"shop:reviews:{product_id}", [
            {"user": "user1", "rating": 5, "comment": "Great product! Highly recommended.", "created_at": 1714000000},
            {"user": "user2", "rating": 4, "comment": "Good value for money, fast shipping.", "created_at": 1713800000},
        ])
        return {"product": product, "reviews": reviews}
