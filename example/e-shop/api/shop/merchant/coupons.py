from fastapi import Request
from eshop_base import ShopRouteBase, MERCHANT_ROLE_NAME, ADMIN_ROLE_NAME


class ShopMerchantCouponsRoute(ShopRouteBase):
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
        return {"ok": True, "coupons": self._get_coupons()}

    async def post(self, request: Request) -> dict[str, object]:
        user, error = self._check_merchant(request)
        if error:
            return error
        body = await request.json()
        coupon_id = body.get("id", "").strip()
        if not coupon_id:
            return {"ok": False, "error": "Coupon ID required"}
        coupons = self._get_coupons()
        existing = None
        for c in coupons:
            if c.get("id") == coupon_id:
                existing = c
                break
        coupon = {
            "id": coupon_id,
            "code": body.get("code", existing.get("code", "") if existing else "").upper(),
            "discount": int(body.get("discount", existing.get("discount", 0) if existing else 0)),
            "min_order": int(body.get("min_order", existing.get("min_order", 0) if existing else 0)),
            "description": body.get("description", existing.get("description", "") if existing else ""),
        }
        if existing:
            for i, c in enumerate(coupons):
                if c.get("id") == coupon_id:
                    coupons[i] = coupon
                    break
        else:
            coupons.append(coupon)
        self.shared_dict.set("shop:coupons", coupons)
        return {"ok": True, "coupon": coupon}

    async def delete(self, request: Request) -> dict[str, object]:
        user, error = self._check_merchant(request)
        if error:
            return error
        body = await request.json()
        coupon_id = body.get("id", "").strip()
        if not coupon_id:
            return {"ok": False, "error": "Coupon ID required"}
        coupons = self._get_coupons()
        coupons = [c for c in coupons if c.get("id") != coupon_id]
        self.shared_dict.set("shop:coupons", coupons)
        return {"ok": True}
