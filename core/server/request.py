import re

from collections.abc import Iterable
from typing import Any, Self

from fastapi import Request

from .data_types.apikey import extract_apikey_from_request, get_apikey_by_key, get_apikey_identity_from_cache


class FuzzyDict:
    def __init__(self, items: Iterable[tuple[str, object]]) -> None:
        self._data = {
            self._normalize_key(key): value
            for key, value in items
        }

    @staticmethod
    def _normalize_key(key: object) -> str:
        return re.sub(r"[^a-z0-9]", "", str(key or "").lower())

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(self._normalize_key(key), default)


class AdvanceRequest(Request):
    @property
    def apikey(self) -> str | None:
        return getattr(self, "_apikey", None)

    async def apikey_obj(self):
        if not getattr(self, "_apikey_obj_loaded", False):
            api_key = await get_apikey_by_key(self.apikey) if self.apikey else None
            object.__setattr__(self, "_apikey_obj", api_key)
            object.__setattr__(self, "_apikey_obj_loaded", True)
        return getattr(self, "_apikey_obj", None)

    async def get_user_id(self) -> str | None:
        if getattr(self, "_user_id_loaded", False):
            return getattr(self, "_user_id", None)

        user_id: str | None = None
        if self.apikey:
            cached_identity = await get_apikey_identity_from_cache(self.apikey)
            if isinstance(cached_identity, dict):
                user_id = str(cached_identity.get("user_id") or "").strip() or None

        if user_id is None:
            api_key = await self.apikey_obj()
            user_id = str(getattr(api_key, "user_id", "") or "").strip() or None

        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_user_id_loaded", True)
        return user_id

    @property
    def ip(self) -> str | None:
        return self.client.host if self.client else None

    def get_header(self, key: str, default: str | None = None) -> str | None:
        fuzzy_headers = getattr(self, "_fuzzy_headers", None)
        if fuzzy_headers is None:
            fuzzy_headers = FuzzyDict(self.headers.items())
            object.__setattr__(self, "_fuzzy_headers", fuzzy_headers)
        value = fuzzy_headers.get(key, default)
        return str(value) if value is not None else None

    @classmethod
    def Cast(cls, request: Request) -> Self:
        if isinstance(request, cls):
            if not hasattr(request, "_apikey"):
                object.__setattr__(request, "_apikey", extract_apikey_from_request(request))
            return request

        request.__class__ = cls
        object.__setattr__(request, "_apikey", extract_apikey_from_request(request))
        return request

    @classmethod
    def New(cls, scope: dict[str, Any], receive: Any) -> Self:
        request = cls(scope=scope, receive=receive)
        object.__setattr__(request, "_apikey", extract_apikey_from_request(request))
        return request


__all__ = ["AdvanceRequest"]