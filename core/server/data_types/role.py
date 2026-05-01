from datetime import datetime
from typing import Any, Literal, TypedDict

from pydantic import Field, field_validator

from core.storage import ORMField, ORMModel, StorageConfig

from .permission_common import (
    RateLimitConfig,
    export_whitelist_routes,
    is_route_allowed,
    match_route_pattern,
    normalize_patterns,
    normalize_whitelist_routes_value,
)


def _get_permission_role_orm_client():
    return StorageConfig.Global().get_orm_client("apikey")


def _default_internal_blacklist_routes() -> list[str]:
    try:
        from .config import Config

        return [Config.GetConfig().server_config.get_internal_path("*")]
    except Exception:
        return ["/_internal/*"]


def _role_names(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return normalize_patterns([str(item) for item in value])
    text = str(value or "").strip()
    return [text] if text else []


class PermissionRoleCreateParams(TypedDict, total=False):
    name: str
    comment: str | None
    banned: bool
    whitelist_routes: Literal["all"] | list[str]
    blacklist_routes: list[str]
    ratelimit: dict[str, RateLimitConfig]


class PermissionRoleUpdateParams(TypedDict, total=False):
    name: str
    comment: str | None
    banned: bool
    whitelist_routes: Literal["all"] | list[str]
    blacklist_routes: list[str]
    ratelimit: dict[str, RateLimitConfig]


async def _ensure_unique_permission_role_name(name: str, *, exclude_id: str | None = None) -> str:
    existing = await PermissionRole.SearchOne({"name": name}, client=_get_permission_role_orm_client())
    if existing is None:
        return name
    existing_id = str(getattr(existing, "id", "") or "")
    if exclude_id and existing_id == exclude_id:
        return name
    raise ValueError(f"Permission role already exists: {name}")


class PermissionRole(ORMModel, collection_name="permission_roles"):
    name: str = ORMField(..., index=True)
    banned: bool = False
    created_at: datetime = ORMField(default_factory=datetime.now)
    last_edit: datetime = ORMField(default_factory=datetime.now)
    blacklist_routes: list[str] = Field(default_factory=_default_internal_blacklist_routes)
    whitelist_routes: list[str] = Field(default_factory=lambda: ["*"])
    ratelimit: dict[str, RateLimitConfig] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("role name is required")
        return text

    @field_validator("whitelist_routes", mode="before")
    @classmethod
    def _normalize_whitelist_routes_field(cls, value: object) -> list[str]:
        return normalize_whitelist_routes_value(value)

    @field_validator("blacklist_routes", mode="before")
    @classmethod
    def _normalize_blacklist_routes_field(cls, value: object) -> list[str]:
        if value is None:
            return _default_internal_blacklist_routes()
        if isinstance(value, list):
            return normalize_patterns([str(item) for item in value])
        text = str(value or "").strip()
        return normalize_patterns([text]) if text else _default_internal_blacklist_routes()

    @property
    def rate_limit(self) -> dict[str, RateLimitConfig]:
        return self.ratelimit

    @rate_limit.setter
    def rate_limit(self, value: dict[str, RateLimitConfig]) -> None:
        self.ratelimit = value

    def _match_route_pattern(self, route: str, pattern: str) -> bool:
        return match_route_pattern(route, pattern)

    def _is_route_allowed(self, route: str) -> bool:
        return is_route_allowed(
            banned=bool(self.banned),
            blacklist_routes=list(self.blacklist_routes),
            whitelist_routes=list(self.whitelist_routes),
            route=route,
        )

    async def save(
        self,
        *,
        client=None,
        expire: float | int | None = None,
        create_collection: bool = True,
        force: bool = False,
    ) -> str:
        object_id = str(getattr(self, "id", "") or "")
        await _ensure_unique_permission_role_name(self.name, exclude_id=object_id or None)
        self.last_edit = datetime.now()
        return await super().save(
            client=client or _get_permission_role_orm_client(),
            expire=expire,
            create_collection=create_collection,
            force=force,
        )


async def get_permission_role_by_name(name: str) -> PermissionRole | None:
    name_text = str(name or "").strip()
    if not name_text:
        return None
    return await PermissionRole.SearchOne({"name": name_text}, client=_get_permission_role_orm_client())


async def get_permission_role_by_id(object_id: str) -> PermissionRole | None:
    object_id_text = str(object_id or "").strip()
    if not object_id_text:
        return None
    return await PermissionRole.SearchOneById(object_id_text, client=_get_permission_role_orm_client())


async def list_permission_roles(*, limit: int = 100, offset: int = 0) -> tuple[list[PermissionRole], int | None]:
    client = _get_permission_role_orm_client()
    items = [item async for item in PermissionRole.Search(limit=limit, offset=offset, client=client)]
    query_count = getattr(client, "query_count", None)
    total = await query_count(PermissionRole) if callable(query_count) else None
    return items, total


async def _require_permission_role(object_id: str) -> PermissionRole:
    role = await get_permission_role_by_id(object_id)
    if role is None:
        raise LookupError(f"Permission role not found: {object_id}")
    return role


async def create_permission_role(**kwargs: PermissionRoleCreateParams) -> PermissionRole:
    role = PermissionRole(
        name=str(kwargs.get("name") or "").strip(),
        comment=kwargs.get("comment"),
        banned=bool(kwargs.get("banned", False)),
        whitelist_routes=kwargs.get("whitelist_routes", "all"),
        blacklist_routes=normalize_patterns(kwargs.get("blacklist_routes", _default_internal_blacklist_routes())),
        ratelimit=kwargs.get("ratelimit", {}),
    )
    await role.save(client=_get_permission_role_orm_client())
    return role


async def count_permission_role_references(name: str) -> int:
    role_name = str(name or "").strip()
    if not role_name:
        return 0
    from .apikey import APIKey

    count = 0
    async for api_key in APIKey.Search(client=_get_permission_role_orm_client()):
        if role_name in _role_names(getattr(api_key, "role", None)):
            count += 1
    return count


async def update_permission_role(object_id: str, **kwargs: PermissionRoleUpdateParams) -> PermissionRole:
    role = await get_permission_role_by_id(object_id)
    if role is None:
        raise LookupError(f"Permission role not found: {object_id}")
    if "name" in kwargs:
        next_name = str(kwargs.get("name") or "").strip()
        if next_name and next_name != role.name and await count_permission_role_references(role.name) > 0:
            raise ValueError(f"Cannot rename permission role while API keys still reference it: {role.name}")
        role.name = next_name
    if "comment" in kwargs:
        role.comment = kwargs.get("comment")
    if "banned" in kwargs:
        role.banned = bool(kwargs.get("banned"))
    if "whitelist_routes" in kwargs:
        role.whitelist_routes = normalize_whitelist_routes_value(kwargs["whitelist_routes"])
    if "blacklist_routes" in kwargs:
        role.blacklist_routes = normalize_patterns(kwargs["blacklist_routes"])
    if "ratelimit" in kwargs:
        role.ratelimit = kwargs["ratelimit"]
    await role.save(client=_get_permission_role_orm_client())
    return role


async def delete_permission_role(object_id: str) -> bool:
    role = await get_permission_role_by_id(object_id)
    if role is None:
        return False
    return await role.delete(client=_get_permission_role_orm_client())


def permission_role_to_dict(role: PermissionRole) -> dict[str, Any]:
    return {
        "id": str(getattr(role, "id", "") or ""),
        "name": role.name,
        "banned": bool(role.banned),
        "created_at": role.created_at,
        "last_edit": role.last_edit,
        "blacklist_routes": list(role.blacklist_routes),
        "whitelist_routes": export_whitelist_routes(role.whitelist_routes),
        "ratelimit": role.ratelimit,
        "comment": role.comment,
    }


async def serialize_permission_role_for_admin(role: PermissionRole) -> dict[str, Any]:
    return {
        **permission_role_to_dict(role),
        "reference_count": await count_permission_role_references(role.name),
    }


async def list_permission_role_admin_items(*, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int | None]:
    items, total = await list_permission_roles(limit=limit, offset=offset)
    return [await serialize_permission_role_for_admin(item) for item in items], total


async def create_permission_role_admin_item(**kwargs: PermissionRoleCreateParams) -> dict[str, Any]:
    return await serialize_permission_role_for_admin(await create_permission_role(**kwargs))


async def get_permission_role_admin_item(object_id: str) -> dict[str, Any]:
    return await serialize_permission_role_for_admin(await _require_permission_role(object_id))


async def update_permission_role_admin_item(object_id: str, **kwargs: PermissionRoleUpdateParams) -> dict[str, Any]:
    return await serialize_permission_role_for_admin(await update_permission_role(object_id, **kwargs))


async def delete_permission_role_admin_item(object_id: str) -> dict[str, object]:
    role = await _require_permission_role(object_id)
    reference_count = await count_permission_role_references(role.name)
    if reference_count > 0:
        raise ValueError(f"Permission role is still referenced by {reference_count} API key(s): {role.name}")
    deleted = await delete_permission_role(object_id)
    if not deleted:
        raise LookupError(f"Permission role not found: {object_id}")
    return {"ok": True, "deleted": True, "id": object_id}


__all__ = [
    "RateLimitConfig",
    "PermissionRole",
    "PermissionRoleCreateParams",
    "PermissionRoleUpdateParams",
    "permission_role_to_dict",
    "get_permission_role_by_name",
    "get_permission_role_by_id",
    "list_permission_roles",
    "serialize_permission_role_for_admin",
    "list_permission_role_admin_items",
    "create_permission_role_admin_item",
    "get_permission_role_admin_item",
    "update_permission_role_admin_item",
    "delete_permission_role_admin_item",
    "create_permission_role",
    "update_permission_role",
    "count_permission_role_references",
    "delete_permission_role",
]