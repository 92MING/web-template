import secrets
from fastapi import Request
from core.utils.type_utils import AdvancedBaseModel

from eshop_base import ShopRouteBase, CUSTOMER_ROLE_NAME, MERCHANT_ROLE_NAME, ADMIN_ROLE_NAME


class RegisterRequest(AdvancedBaseModel):
    username: str
    password: str
    role: str = CUSTOMER_ROLE_NAME


class LoginRequest(AdvancedBaseModel):
    username: str
    password: str


class ShopAuthRoute(ShopRouteBase):
    Tags = "Shop"

    async def post(self, request: Request, action: str = "login") -> dict[str, object]:
        if action == "register":
            body = await request.json()
            req = RegisterRequest(**body)
            users = self._get_users()
            if req.username in users:
                return {"ok": False, "error": "Username already exists", "error_code": "username_exists"}
            role = self._normalize_role(req.role)
            users[req.username] = {
                "user_id": req.username,
                "name": req.username,
                "phone": "",
                "email": "",
                "address": "",
                "password_hash": self._hash(req.password),
                "role": role,
            }
            self.shared_dict.set("shop:users", users)
            token = secrets.token_urlsafe(16)
            self.shared_dict.set(f"shop:token:{token}", req.username)
            return {"ok": True, "token": token, "user_id": req.username, "role": role}

        if action == "login":
            body = await request.json()
            req = LoginRequest(**body)
            users = self._get_users()
            user = users.get(req.username)
            if not user or user.get("password_hash") != self._hash(req.password):
                return {"ok": False, "error": "Invalid username or password", "error_code": "invalid_credentials"}
            token = secrets.token_urlsafe(16)
            self.shared_dict.set(f"shop:token:{token}", req.username)
            role = user.get("role", CUSTOMER_ROLE_NAME)
            return {"ok": True, "token": token, "user_id": req.username, "role": role}

        return {"ok": False, "error": "Invalid action", "error_code": "invalid_action"}

    async def get(self, request: Request, action: str = "me") -> dict[str, object]:
        if action == "me":
            user = self._get_current_user(request)
            if not user:
                return {"ok": False, "error": "Not logged in", "error_code": "not_logged_in"}
            return {"ok": True, "user": user}

        if action == "test_accounts":
            return {
                "ok": True,
                "accounts": [
                    {"role": "customer", "username": "customer1", "password": "123456"},
                    {"role": "customer", "username": "customer2", "password": "123456"},
                    {"role": "merchant", "username": "merchant1", "password": "123456"},
                    {"role": "admin", "username": "admin", "password": "123456"},
                ]
            }

        return {"ok": False, "error": "Invalid action", "error_code": "invalid_action"}
