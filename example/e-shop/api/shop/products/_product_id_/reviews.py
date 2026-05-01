import time
from fastapi import Request
from core.utils.type_utils import AdvancedBaseModel
from eshop_base import ShopRouteBase


class ReviewRequest(AdvancedBaseModel):
    user_id: str
    rating: int
    comment: str


class ShopProductReviewsRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, product_id: str) -> dict[str, object]:
        reviews = self.shared_dict.get(f"shop:reviews:{product_id}", [
            {"user": "user1", "rating": 5, "comment": "Great product! Highly recommended.", "created_at": 1714000000},
            {"user": "user2", "rating": 4, "comment": "Good value for money, fast shipping.", "created_at": 1713800000},
        ])
        return {"reviews": reviews}

    async def post(self, request: Request, product_id: str) -> dict[str, object]:
        body = await request.json()
        req = ReviewRequest(**body)
        if req.rating < 1 or req.rating > 5:
            return {"ok": False, "error": "Rating must be between 1 and 5"}
        key = f"shop:reviews:{product_id}"
        reviews: list[dict] = list(self.shared_dict.get(key, []))
        reviews.append({
            "user": req.user_id,
            "rating": req.rating,
            "comment": req.comment,
            "created_at": int(time.time()),
        })
        self.shared_dict.set(key, reviews)
        return {"ok": True, "reviews": reviews}
