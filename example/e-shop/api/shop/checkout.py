import time
from pydantic import BaseModel
from eshop_base import ShopRouteBase


class CheckoutItem(BaseModel):
    product_id: str
    quantity: int


class CheckoutRequest(BaseModel):
    user_id: str
    items: list[CheckoutItem]
    shipping: dict | None = None
    coupon_code: str = ""


class ShopCheckoutRoute(ShopRouteBase):
    Tags = "Shop"

    async def post(self, payload: CheckoutRequest) -> dict[str, object]:
        products = self._get_products()
        # Validate stock
        for item in payload.items:
            product = products.get(item.product_id)
            if not product:
                return {"ok": False, "error": f"Product not found: {item.product_id}"}
            if product.get("stock", 0) < item.quantity:
                return {"ok": False, "error": f"Insufficient stock: {product['name']}"}

        # Calculate total
        total = sum(products[i.product_id]["price"] * i.quantity for i in payload.items)
        discount = 0
        if payload.coupon_code:
            coupons = self._get_coupons()
            for coupon in coupons:
                if coupon.get("code") == payload.coupon_code.upper():
                    if total >= coupon.get("min_order", 0):
                        discount = coupon.get("discount", 0)
                    break
        final_total = max(0, total - discount)

        # Deduct stock
        for item in payload.items:
            self._deduct_stock(item.product_id, item.quantity)

        order = {
            "order_id": f"o-{int(time.time())}-{payload.user_id}",
            "user_id": payload.user_id,
            "items": [i.model_dump() for i in payload.items],
            "status": "paid",
            "created_at": time.time(),
            "shipping": payload.shipping or {},
            "total": total,
            "discount": discount,
            "final_total": final_total,
        }
        key = f"shop:orders:{payload.user_id}"
        orders: list[dict] = list(self.shared_dict.get(key, []))
        orders.append(order)
        self.shared_dict.set(key, orders)
        # clear cart
        self.shared_dict.delete(f"shop:cart:{payload.user_id}")
        return {"ok": True, "order": order}
