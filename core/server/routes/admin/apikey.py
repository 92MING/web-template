# -*- coding: utf-8 -*-



import asyncio

from datetime import datetime

from typing import Any, Literal



from fastapi import FastAPI, HTTPException, Query, Request

from pydantic import BaseModel, Field



from core.server.data_types.apikey import (

    APIKeyStatsSnapshot,

    APIKeyValidationResult,

    RateLimitConfig,

    adjust_apikey_credit,

    apikey_to_dict,

    create_apikey,

    delete_apikey,

    get_apikey_expire_seconds,

    get_apikey_by_id,

    get_apikey_stats,

    list_apikeys,

    record_apikey_usage,

    set_apikey_credit,

    update_apikey,

    validate_apikey_route,

)



from ...app import internal_admin_path, on_before_app_created





_LOCAL_HOSTS = {"", "127.0.0.1", "::1", "localhost", "testclient"}
# -*- coding: utf-8 -*-

from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.server.data_types.apikey import (
    APIKeyStatsSnapshot,
    APIKeyValidationResult,
    RateLimitConfig,
    adjust_apikey_credit,
    apikey_to_dict,
    create_apikey,
    delete_apikey,
    get_apikey_expire_seconds,
    get_apikey_by_id,
    get_apikey_stats,
    list_apikeys,
    record_apikey_usage,
    set_apikey_credit,
    update_apikey,
    validate_apikey_route,
    _default_internal_blacklist_routes,
)

from ...app import on_before_app_created


_LOCAL_HOSTS = {"", "127.0.0.1", "::1", "localhost", "testclient"}


class AdminAPIKeyCreateBody(BaseModel):
    key: str | None = None
    name: str | None = None
    comment: str | None = None
    user_id: str | None = None
    credit: float = Field(default=0.0, ge=0.0)
    expire_seconds: float | None = Field(default=None, ge=0.0)
    banned: bool = False
    role: str | list[str] | None = None
    whitelist_routes: Literal["all"] | list[str] = "all"
    blacklist_routes: list[str] = Field(default_factory=_default_internal_blacklist_routes)
    rate_limit: dict[str, RateLimitConfig] = Field(default_factory=dict)


class AdminAPIKeyPatchBody(BaseModel):
    name: str | None = None
    comment: str | None = None
    user_id: str | None = None
    expire_seconds: float | None = Field(default=None, ge=0.0)
    banned: bool | None = None
    role: str | list[str] | None = None
    whitelist_routes: Literal["all"] | list[str] | None = None
    blacklist_routes: list[str] | None = None
    rate_limit: dict[str, RateLimitConfig] | None = None


class AdminAPIKeyCreditBody(BaseModel):
    credit: float | None = Field(default=None, ge=0.0)
    delta: float | None = None


class AdminAPIKeyChargeBody(BaseModel):
    route: str = Field(min_length=1)
    cost: float = Field(ge=0.0)


class AdminAPIKeyValidateBody(BaseModel):
    key: str = Field(min_length=1)
    route: str = Field(min_length=1)
    cost: float = Field(default=0.0, ge=0.0)
    record_access: bool = False


class AdminAPIKeyItemResponse(BaseModel):
    id: str
    key: str
    banned: bool
    created_at: Any
    edited_at: Any
    last_used_at: Any | None = None
    role: str | list[str] | None = None
    user_id: str | None = None
    blacklist_routes: list[str]
    whitelist_routes: Literal["all"] | list[str]
    rate_limit: dict[str, RateLimitConfig]
    credit: float
    name: str | None = None
    comment: str | None = None
    ttl_seconds: float | None = None
    ttl_state: Literal["persistent", "expiring", "expired_or_missing"] = "persistent"
    expire_at: datetime | None = None


class AdminAPIKeyListResponse(BaseModel):
    items: list[AdminAPIKeyItemResponse]
    total: int
    limit: int
    offset: int


class AdminAPIKeyStatsResponse(BaseModel):
    apikey: AdminAPIKeyItemResponse
    stats: APIKeyStatsSnapshot


def _is_local_request(request: Request) -> bool:
    host = (request.client.host if request.client else "") if request is not None else ""
    return (host or "").strip().lower() in _LOCAL_HOSTS


def _ensure_local_request(request: Request) -> None:
    if not _is_local_request(request):
        raise HTTPException(403, "APIKey 管理接口仅允许本机访问。")


async def _require_apikey(object_id: str):
    api_key = await get_apikey_by_id(object_id)
    if api_key is None:
        raise HTTPException(404, f"API key not found: {object_id}")
    return api_key


def _validation_http_status(result: APIKeyValidationResult) -> int:
    if result.reason == "not_found":
        return 404
    if result.reason in {"banned", "route_not_allowed"}:
        return 403
    if result.reason == "insufficient_credit":
        return 409
    if result.reason in {"minimum_interval", "rate_limited"}:
        return 429
    return 400


async def _serialize_apikey(api_key: Any) -> AdminAPIKeyItemResponse:
    ttl_seconds = await get_apikey_expire_seconds(api_key)
    ttl_state: Literal["persistent", "expiring", "expired_or_missing"]
    if ttl_seconds is None:
        ttl_state = "persistent"
    elif ttl_seconds <= 0:
        ttl_state = "expired_or_missing"
    else:
        ttl_state = "expiring"
    expire_at = None if ttl_seconds is None else datetime.fromtimestamp(datetime.now().timestamp() + ttl_seconds)
    return AdminAPIKeyItemResponse.model_validate(
        {
            **apikey_to_dict(api_key),
            "ttl_seconds": ttl_seconds,
            "ttl_state": ttl_state,
            "expire_at": expire_at,
        }
    )


@on_before_app_created
def register_admin_apikey_routes(app: FastAPI) -> None:
    admin_path = internal_admin_path

    @app.get(admin_path("apikeys"), response_model=AdminAPIKeyListResponse)
    async def admin_apikey_list(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> AdminAPIKeyListResponse:
        _ensure_local_request(request)
        items, total = await list_apikeys(limit=limit, offset=offset)
        return AdminAPIKeyListResponse(
            items=[await _serialize_apikey(item) for item in items],
            total=int(total if total is not None else len(items)),
            limit=limit,
            offset=offset,
        )

    @app.post(admin_path("apikeys"), response_model=AdminAPIKeyItemResponse)
    async def admin_apikey_create(body: AdminAPIKeyCreateBody, request: Request) -> AdminAPIKeyItemResponse:
        _ensure_local_request(request)
        try:
            api_key = await create_apikey(**body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return await _serialize_apikey(api_key)

    @app.get(admin_path("apikeys/{object_id}"), response_model=AdminAPIKeyItemResponse)
    async def admin_apikey_get(object_id: str, request: Request) -> AdminAPIKeyItemResponse:
        _ensure_local_request(request)
        api_key = await _require_apikey(object_id)
        return await _serialize_apikey(api_key)

    @app.patch(admin_path("apikeys/{object_id}"), response_model=AdminAPIKeyItemResponse)
    async def admin_apikey_patch(
        object_id: str,
        body: AdminAPIKeyPatchBody,
        request: Request,
    ) -> AdminAPIKeyItemResponse:
        _ensure_local_request(request)
        payload = {key: getattr(body, key) for key in body.model_fields_set}
        try:
            api_key = await update_apikey(object_id, **payload)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return await _serialize_apikey(api_key)

    @app.delete(admin_path("apikeys/{object_id}"))
    async def admin_apikey_delete(object_id: str, request: Request) -> dict[str, object]:
        _ensure_local_request(request)
        deleted = await delete_apikey(object_id)
        if not deleted:
            raise HTTPException(404, f"API key not found: {object_id}")
        return {"ok": True, "deleted": True, "id": object_id}

    @app.post(admin_path("apikeys/{object_id}/credit"), response_model=AdminAPIKeyItemResponse)
    async def admin_apikey_credit(
        object_id: str,
        body: AdminAPIKeyCreditBody,
        request: Request,
    ) -> AdminAPIKeyItemResponse:
        _ensure_local_request(request)
        try:
            if body.credit is not None and body.delta is not None:
                raise HTTPException(400, "Pass either `credit` or `delta`, not both.")
            if body.credit is not None:
                api_key = await set_apikey_credit(object_id, body.credit)
            elif body.delta is not None:
                api_key = await adjust_apikey_credit(object_id, body.delta)
            else:
                raise HTTPException(400, "Missing `credit` or `delta`.")
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return await _serialize_apikey(api_key)

    @app.post(admin_path("apikeys/validate"), response_model=APIKeyValidationResult)
    async def admin_apikey_validate(body: AdminAPIKeyValidateBody, request: Request) -> APIKeyValidationResult:
        _ensure_local_request(request)
        result = await validate_apikey_route(
            body.key,
            body.route,
            cost=body.cost,
            record_access=body.record_access,
        )
        if not result.ok:
            raise HTTPException(_validation_http_status(result), result.detail or result.reason)
        return result

    @app.post(admin_path("apikeys/{object_id}/charge"), response_model=AdminAPIKeyStatsResponse)
    async def admin_apikey_charge(
        object_id: str,
        body: AdminAPIKeyChargeBody,
        request: Request,
    ) -> AdminAPIKeyStatsResponse:
        _ensure_local_request(request)
        api_key = await _require_apikey(object_id)
        try:
            stats = await record_apikey_usage(api_key, body.route, body.cost)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        fresh = await _require_apikey(object_id)
        return AdminAPIKeyStatsResponse(
            apikey=await _serialize_apikey(fresh),
            stats=stats,
        )

    @app.get(admin_path("apikeys/{object_id}/stats"), response_model=AdminAPIKeyStatsResponse)
    async def admin_apikey_stats(object_id: str, request: Request) -> AdminAPIKeyStatsResponse:
        _ensure_local_request(request)
        api_key = await _require_apikey(object_id)
        return AdminAPIKeyStatsResponse(
            apikey=await _serialize_apikey(api_key),
            stats=await get_apikey_stats(api_key),
        )


__all__ = ["register_admin_apikey_routes"]