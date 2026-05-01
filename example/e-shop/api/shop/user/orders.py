from eshop_base import ShopRouteBase


class ShopUserOrdersRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, user_id: str) -> dict[str, object]:
        key = f"shop:orders:{user_id}"
        orders: list[dict] = list(self.shared_dict.get(key, []))
        # Enrich items with product names
        products = self._get_products()
        for order in orders:
            for item in order.get("items", []):
                pid = item.get("product_id")
                if pid and pid in products:
                    item["name"] = products[pid].get("name")
                    item["price"] = products[pid].get("price")
        return {"orders": orders}
