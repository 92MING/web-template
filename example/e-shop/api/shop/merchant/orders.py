from fastapi import Request
from eshop_base import ShopRouteBase, MERCHANT_ROLE_NAME, ADMIN_ROLE_NAME


class ShopMerchantOrdersRoute(ShopRouteBase):
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
        # Collect all orders from all users
        users = self._get_users()
        products = self._get_products()
        all_orders: list[dict] = []
        for uid in users:
            key = f"shop:orders:{uid}"
            orders: list[dict] = list(self.shared_dict.get(key, []))
            for order in orders:
                for item in order.get("items", []):
                    pid = item.get("product_id")
                    if pid and pid in products:
                        item["name"] = products[pid].get("name")
                        item["price"] = products[pid].get("price")
            all_orders.extend(orders)
        # Sort by created_at desc
        all_orders.sort(key=lambda o: o.get("created_at", 0), reverse=True)
        return {"ok": True, "orders": all_orders}
