from fastapi import Request
from eshop_base import ShopRouteBase


class ShopCouponsRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self) -> dict[str, object]:
        return {"coupons": self._get_coupons()}

    async def post(self, request: Request) -> dict[str, object]:
        body = await request.json()
        code = body.get("code", "")
        order_total = body.get("order_total", 0)
        coupons = self._get_coupons()
        for coupon in coupons:
            if coupon.get("code") == code.upper():
                if order_total > 0 and order_total < coupon.get("min_order", 0):
                    return {"ok": False, "error": f"Order minimum is {coupon['min_order']}"}
                return {"ok": True, "coupon": coupon}
        return {"ok": False, "error": "Coupon not found"}
