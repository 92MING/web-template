# -*- coding: utf-8 -*-
"""Shared helpers for the e-shop example APIs."""

import hashlib
from typing import Any

from fastapi import Request

from core.server import AdvanceRequest, Route
from core.server.shared_dict import SharedDict

CUSTOMER_ROLE_NAME = "customer"
MERCHANT_ROLE_NAME = "merchant"
ADMIN_ROLE_NAME = "admin"

__all__ = ["ShopRouteBase", "CUSTOMER_ROLE_NAME", "MERCHANT_ROLE_NAME", "ADMIN_ROLE_NAME"]


class ShopRouteBase(Route):
    Abstract = True

    @property
    def shared_dict(self) -> SharedDict:
        return SharedDict(self.shared_data, namespace="ShopRouteBase")

    def _hash(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()[:16]

    def _normalize_role(self, role: str) -> str:
        role_text = str(role or "").strip().lower()
        return role_text if role_text in {CUSTOMER_ROLE_NAME, MERCHANT_ROLE_NAME, ADMIN_ROLE_NAME} else CUSTOMER_ROLE_NAME

    def _get_users(self) -> dict[str, dict[str, Any]]:
        users = self.shared_dict.get("shop:users")
        if isinstance(users, dict):
            return users
        users = {
            "demo": {
                "user_id": "demo",
                "name": "Demo User",
                "phone": "",
                "email": "demo@example.com",
                "address": "",
                "password_hash": self._hash("demo123"),
                "role": CUSTOMER_ROLE_NAME,
            },
            "customer1": {
                "user_id": "customer1",
                "name": "Customer One",
                "phone": "",
                "email": "customer1@example.com",
                "address": "",
                "password_hash": self._hash("123456"),
                "role": CUSTOMER_ROLE_NAME,
            },
            "customer2": {
                "user_id": "customer2",
                "name": "Customer Two",
                "phone": "",
                "email": "customer2@example.com",
                "address": "",
                "password_hash": self._hash("123456"),
                "role": CUSTOMER_ROLE_NAME,
            },
            "merchant1": {
                "user_id": "merchant1",
                "name": "Merchant One",
                "phone": "",
                "email": "merchant1@example.com",
                "address": "",
                "password_hash": self._hash("123456"),
                "role": MERCHANT_ROLE_NAME,
            },
            "admin": {
                "user_id": "admin",
                "name": "Admin",
                "phone": "",
                "email": "admin@example.com",
                "address": "",
                "password_hash": self._hash("123456"),
                "role": ADMIN_ROLE_NAME,
            },
        }
        self.shared_dict.set("shop:users", users)
        return users

    def _get_products(self) -> dict[str, dict[str, Any]]:
        products = self.shared_dict.get("shop:products")
        if isinstance(products, dict):
            self._ensure_product_defaults(products)
            return products
        products = {
            "p1": {"id": "p1", "name": "无线降噪耳机", "price": 399, "category": "electronics", "description": "蓝牙耳机，主动降噪，长续航", "tags": ["耳机", "audio", "bluetooth"], "image": "/icons/filled/customer-service.svg"},
            "p2": {"id": "p2", "name": "轻薄笔记本电脑", "price": 4999, "category": "electronics", "description": "高性能办公与学习电脑", "tags": ["电脑", "laptop"], "image": "/icons/outlined/laptop.svg"},
            "p3": {"id": "p3", "name": "机械键盘", "price": 299, "category": "electronics", "description": "热插拔轴体与背光", "tags": ["keyboard"], "image": "/icons/outlined/desktop.svg"},
            "p4": {"id": "p4", "name": "城市通勤背包", "price": 169, "category": "bags", "description": "防泼水，多隔层", "tags": ["bag"], "image": "/icons/filled/shopping.svg"},
            "p5": {"id": "p5", "name": "保温水杯", "price": 89, "category": "home", "description": "不锈钢便携水杯", "tags": ["cup"], "image": "/icons/outlined/coffee.svg"},
            "p6": {"id": "p6", "name": "人体工学办公椅", "price": 899, "category": "home", "description": "腰托与可调扶手", "tags": ["chair"], "image": "/icons/filled/home.svg"},
        }
        self._ensure_product_defaults(products)
        self.shared_dict.set("shop:products", products)
        return products

    def _ensure_product_defaults(self, products: dict[str, dict[str, Any]]) -> None:
        for index, product in enumerate(products.values(), start=1):
            price = int(product.get("price", 0) or 0)
            product.setdefault("old_price", price + max(20, price // 5))
            product.setdefault("stock", 30 + index * 5)
            product.setdefault("sales", 120 - index * 7)
            product.setdefault("rating", round(4.8 - index * 0.05, 1))

    def _get_product(self, product_id: str) -> dict[str, Any] | None:
        product = self._get_products().get(str(product_id or ""))
        return product if isinstance(product, dict) else None

    def _get_categories(self) -> list[dict[str, Any]]:
        products = self._get_products().values()
        category_names = {
            "electronics": "数码电子",
            "bags": "箱包配饰",
            "home": "家居生活",
        }
        counts: dict[str, int] = {}
        for product in products:
            category = str(product.get("category", "") or "uncategorized")
            counts[category] = counts.get(category, 0) + 1
        return [
            {"id": category, "name": category_names.get(category, category), "count": count}
            for category, count in sorted(counts.items())
        ]

    def _deduct_stock(self, product_id: str, quantity: int) -> None:
        products = self._get_products()
        product = products.get(str(product_id or ""))
        if not isinstance(product, dict):
            return
        product["stock"] = max(0, int(product.get("stock", 0) or 0) - int(quantity or 0))
        product["sales"] = int(product.get("sales", 0) or 0) + max(0, int(quantity or 0))
        self.shared_dict.set("shop:products", products)

    def _get_coupons(self) -> list[dict[str, Any]]:
        coupons = self.shared_dict.get("shop:coupons")
        if isinstance(coupons, list):
            return coupons
        coupons = [
            {"id": "welcome", "code": "WELCOME", "discount": 20, "min_order": 100, "description": "新人优惠"},
            {"id": "save50", "code": "SAVE50", "discount": 50, "min_order": 500, "description": "满 500 减 50"},
            {"id": "tech100", "code": "TECH100", "discount": 100, "min_order": 1000, "description": "数码专区优惠"},
        ]
        self.shared_dict.set("shop:coupons", coupons)
        return coupons

    def _get_current_user(self, request: Request | AdvanceRequest) -> dict[str, Any] | None:
        advance_request = AdvanceRequest.Cast(request) if isinstance(request, Request) else request
        token = advance_request.apikey
        if not token:
            return None
        user_id = self.shared_dict.get(f"shop:token:{token}")
        users = self._get_users()
        user = users.get(str(user_id or ""))
        return dict(user) if isinstance(user, dict) else None