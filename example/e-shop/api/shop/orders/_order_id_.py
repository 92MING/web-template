from eshop_base import ShopRouteBase


class ShopOrderDetailRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, order_id: str, user_id: str = "") -> dict[str, object]:
        if not user_id:
            user_id = "demo"
        key = f"shop:orders:{user_id}"
        orders: list[dict] = list(self.shared_dict.get(key, []))
        for order in orders:
            if order.get("order_id") == order_id:
                # Enrich items
                products = self._get_products()
                for item in order.get("items", []):
                    pid = item.get("product_id")
                    if pid and pid in products:
                        item["name"] = products[pid].get("name")
                        item["price"] = products[pid].get("price")
                        item["image"] = products[pid].get("image")
                return {"order": order}
        return {"error": "Order not found"}
