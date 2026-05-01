from fastapi import Request
from core.utils.type_utils import AdvancedBaseModel
from eshop_base import ShopRouteBase


class UpdateProfileRequest(AdvancedBaseModel):
    name: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""


class ShopUserProfileRoute(ShopRouteBase):
    Tags = "Shop"

    async def get(self, user_id: str) -> dict[str, object]:
        users = self._get_users()
        user = users.get(user_id, {"user_id": user_id, "name": user_id, "phone": "", "email": "", "address": ""})
        return {"user": user}

    async def put(self, request: Request, user_id: str) -> dict[str, object]:
        body = await request.json()
        req = UpdateProfileRequest(**body)
        users = self._get_users()
        user = users.get(user_id)
        if not user:
            return {"ok": False, "error": "User not found"}
        if req.name:
            user["name"] = req.name
        if req.phone:
            user["phone"] = req.phone
        if req.email:
            user["email"] = req.email
        if req.address:
            user["address"] = req.address
        self.shared_dict.set("shop:users", users)
        return {"ok": True, "user": user}
