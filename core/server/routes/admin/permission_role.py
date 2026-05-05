# -*- coding: utf-8 -*-

from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.server.data_types.role import (
    RateLimitConfig,
    _default_internal_blacklist_routes,
    create_permission_role_admin_item,
    delete_permission_role_admin_item,
    get_permission_role_admin_item,
    list_permission_role_admin_items,
    update_permission_role_admin_item,
)

from ...app import internal_admin_path, on_before_app_created


_LOCAL_HOSTS = {"", "127.0.0.1", "::1", "localhost", "testclient"}


class AdminPermissionRoleCreateBody(BaseModel):
    name: str = Field(min_length=1)
    comment: str | None = None
    banned: bool = False
    whitelist_routes: Literal["all"] | list[str] = "all"
    blacklist_routes: list[str] = Field(default_factory=_default_internal_blacklist_routes)
    ratelimit: dict[str, RateLimitConfig] = Field(default_factory=dict)


class AdminPermissionRolePatchBody(BaseModel):
    name: str | None = None
    comment: str | None = None
    banned: bool | None = None
    whitelist_routes: Literal["all"] | list[str] | None = None
    blacklist_routes: list[str] | None = None
    ratelimit: dict[str, RateLimitConfig] | None = None


class AdminPermissionRoleItemResponse(BaseModel):
    id: str
    name: str
    banned: bool
    created_at: Any
    last_edit: Any
    blacklist_routes: list[str]
    whitelist_routes: Literal["all"] | list[str]
    ratelimit: dict[str, RateLimitConfig]
    comment: str | None = None
    reference_count: int = 0


class AdminPermissionRoleListResponse(BaseModel):
    items: list[AdminPermissionRoleItemResponse]
    total: int
    limit: int
    offset: int


def _is_local_request(request: Request) -> bool:
    host = (request.client.host if request.client else "") if request is not None else ""
    return (host or "").strip().lower() in _LOCAL_HOSTS


def _ensure_local_request(request: Request) -> None:
    if not _is_local_request(request):
        raise HTTPException(403, "PermissionRole 管理接口仅允许本机访问。")


async def _serialize_permission_role(item: Any) -> AdminPermissionRoleItemResponse:
    return AdminPermissionRoleItemResponse.model_validate(item)


@on_before_app_created
def register_admin_permission_role_routes(app: FastAPI) -> None:
    admin_path = internal_admin_path

    @app.get(admin_path("permission-roles"), response_model=AdminPermissionRoleListResponse)
    async def admin_permission_role_list(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> AdminPermissionRoleListResponse:
        _ensure_local_request(request)
        items, total = await list_permission_role_admin_items(limit=limit, offset=offset)
        return AdminPermissionRoleListResponse(
            items=[await _serialize_permission_role(item) for item in items],
            total=int(total if total is not None else len(items)),
            limit=limit,
            offset=offset,
        )

    @app.post(admin_path("permission-roles"), response_model=AdminPermissionRoleItemResponse)
    async def admin_permission_role_create(
        body: AdminPermissionRoleCreateBody,
        request: Request,
    ) -> AdminPermissionRoleItemResponse:
        _ensure_local_request(request)
        try:
            item = await create_permission_role_admin_item(**body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return await _serialize_permission_role(item)

    @app.get(admin_path("permission-roles/{object_id}"), response_model=AdminPermissionRoleItemResponse)
    async def admin_permission_role_get(object_id: str, request: Request) -> AdminPermissionRoleItemResponse:
        _ensure_local_request(request)
        try:
            item = await get_permission_role_admin_item(object_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return await _serialize_permission_role(item)

    @app.patch(admin_path("permission-roles/{object_id}"), response_model=AdminPermissionRoleItemResponse)
    async def admin_permission_role_patch(
        object_id: str,
        body: AdminPermissionRolePatchBody,
        request: Request,
    ) -> AdminPermissionRoleItemResponse:
        _ensure_local_request(request)
        payload = {key: getattr(body, key) for key in body.model_fields_set}
        try:
            item = await update_permission_role_admin_item(object_id, **payload)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            status_code = 409 if "reference" in str(exc).lower() else 400
            raise HTTPException(status_code, str(exc)) from exc
        return await _serialize_permission_role(item)

    @app.delete(admin_path("permission-roles/{object_id}"))
    async def admin_permission_role_delete(object_id: str, request: Request) -> dict[str, object]:
        _ensure_local_request(request)
        try:
            return await delete_permission_role_admin_item(object_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


__all__ = ["register_admin_permission_role_routes"]