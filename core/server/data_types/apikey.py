import secrets
import time

from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, Awaitable, Callable, Concatenate, Literal, ParamSpec, Protocol, TypedDict

from fastapi import HTTPException, Request
from starlette.websockets import WebSocket
from pydantic import BaseModel, Field, field_validator

from core.storage import ORMField, ORMModel, StorageConfig

from .permission_common import (
    FixedWindowRateLimit,
    RateLimitConfig,
    SlidingWindowRateLimit,
    export_whitelist_routes,
    fixed_window_bounds,
    is_route_allowed,
    match_route_pattern,
    normalize_patterns,
    normalize_whitelist_routes_value,
)
from .role import PermissionRole, get_permission_role_by_name


P = ParamSpec("P")
_APIKEY_HISTORY_LIMIT = 80


def _default_internal_blacklist_routes() -> list[str]:
    try:
        from .config import Config

        return [Config.GetConfig().server_config.get_internal_path("*")]
    except Exception:
        return ["/_internal/*"]

class _PermissionSubject(Protocol):
    banned: bool
    blacklist_routes: list[str]
    whitelist_routes: list[str]
    rate_limit: dict[str, RateLimitConfig]

    def _match_route_pattern(self, route: str, pattern: str) -> bool: ...

    def _is_route_allowed(self, route: str) -> bool: ...


class APIKey(ORMModel, collection_name="apikeys"):
    key: str = ORMField(..., index=True)
    banned: bool = False
    created_at: datetime = ORMField(default_factory=datetime.now)
    edited_at: datetime = ORMField(default_factory=datetime.now)
    last_used_at: datetime | None = None
    role: list[str] = Field(default_factory=list)
    user_id: str | None = ORMField(default=None, index=True)
    blacklist_routes: list[str] = Field(default_factory=_default_internal_blacklist_routes)
    whitelist_routes: list[str] = Field(default_factory=lambda: ["*"])
    rate_limit: dict[str, RateLimitConfig] = Field(default_factory=dict)
    credit: float = 0.0
    name: str | None = ORMField(default=None, index=True)
    comment: str | None = None

    @field_validator("whitelist_routes", mode="before")
    @classmethod
    def _normalize_whitelist_routes_field(cls, value: object) -> list[str]:
        return normalize_whitelist_routes_value(value)

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role_field(cls, value: object) -> list[str]:
        return _normalize_role_value(value)

    @field_validator("blacklist_routes", mode="before")
    @classmethod
    def _normalize_blacklist_routes_field(cls, value: object) -> list[str]:
        if value is None:
            return _default_internal_blacklist_routes()
        if isinstance(value, list):
            return normalize_patterns([str(item) for item in value])
        text = str(value or "").strip()
        return normalize_patterns([text]) if text else _default_internal_blacklist_routes()

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
        touch_edited_at: bool = True,
    ) -> str:
        if touch_edited_at:
            self.edited_at = datetime.now()
        return await super().save(
            client=client or _get_apikey_orm_client(),
            expire=expire,
            create_collection=create_collection,
            force=force,
        )


class APIKeyRouteStats(TypedDict, total=False):
    access_count: int
    usage_count: int
    total_cost: float
    last_access_at: float
    last_usage_at: float


class APIKeyIdentityCachePayload(TypedDict, total=False):
    object_id: str
    key: str
    user_id: str | None


class APIKeyAccessHistoryEntry(BaseModel):
    at: float
    route: str
    matched_patterns: list[str] = Field(default_factory=list)
    cost: float = 0.0


class APIKeyCreditHistoryEntry(BaseModel):
    at: float
    action: Literal["create", "set", "delta", "charge"]
    delta: float
    before_credit: float
    after_credit: float
    route: str | None = None


class APIKeyFixedWindowState(TypedDict, total=False):
    window_start_at: float
    count: int


class APIKeyUsageStats(TypedDict, total=False):
    object_id: str
    key: str
    access_count: int
    usage_count: int
    total_cost: float
    last_access_at: float
    last_usage_at: float
    routes: dict[str, APIKeyRouteStats]
    access_history: list[dict[str, object]]
    credit_history: list[dict[str, object]]
    minimum_interval_last_access_at: dict[str, float]
    sliding_windows: dict[str, list[float]]
    fixed_windows: dict[str, APIKeyFixedWindowState]


class APIKeyValidationResult(BaseModel):
    ok: bool
    reason: Literal[
        "ok",
        "not_found",
        "banned",
        "route_not_allowed",
        "insufficient_credit",
        "minimum_interval",
        "rate_limited",
    ]
    route: str
    object_id: str | None = None
    key: str | None = None
    matched_patterns: list[str] = Field(default_factory=list)
    credit: float | None = None
    remaining_credit: float | None = None
    retry_after_seconds: float | None = None
    detail: str | None = None


class APIKeyStatsSnapshot(BaseModel):
    object_id: str
    key: str
    access_count: int = 0
    usage_count: int = 0
    total_cost: float = 0.0
    last_access_at: float | None = None
    last_usage_at: float | None = None
    routes: dict[str, APIKeyRouteStats] = Field(default_factory=dict)
    access_history: list[APIKeyAccessHistoryEntry] = Field(default_factory=list)
    credit_history: list[APIKeyCreditHistoryEntry] = Field(default_factory=list)


class APIKeyCreateParams(TypedDict, total=False):
    key: str
    name: str | None
    comment: str | None
    user_id: str | None
    credit: float
    expire_seconds: float | None
    banned: bool
    role: str | list[str] | None
    whitelist_routes: Literal["all"] | list[str]
    blacklist_routes: list[str]
    rate_limit: dict[str, RateLimitConfig]


class APIKeyUpdateParams(TypedDict, total=False):
    name: str | None
    comment: str | None
    user_id: str | None
    expire_seconds: float | None
    banned: bool
    role: str | list[str] | None
    whitelist_routes: Literal["all"] | list[str]
    blacklist_routes: list[str]
    rate_limit: dict[str, RateLimitConfig]


@dataclass(slots=True)
class _ResolvedValidation:
    api_key: APIKey | None
    result: APIKeyValidationResult
    stats: APIKeyUsageStats | None = None


def _get_kv_apikey_record_client():
    return StorageConfig.Global().get_kv_client("apikey").open_namespace("apikey_records")


def _get_kv_apikey_identity_client():
    return StorageConfig.Global().get_kv_client("apikey").open_namespace("apikey_identity")


def _get_apikey_orm_client():
    return StorageConfig.Global().get_orm_client("apikey")


def _apikey_record_key(api_key: APIKey) -> str:
    object_id = str(getattr(api_key, "id", "") or "").strip()
    if object_id:
        return object_id
    return str(api_key.key).strip()


def _apikey_identity_key_by_key(key: str) -> str:
    return f"key:{str(key or '').strip()}"


def _apikey_identity_key_by_id(object_id: str) -> str:
    return f"id:{str(object_id or '').strip()}"


def _apikey_identity_payload(api_key: APIKey) -> APIKeyIdentityCachePayload:
    return {
        "object_id": str(getattr(api_key, "id", "") or "").strip(),
        "key": str(api_key.key or "").strip(),
        "user_id": _normalize_optional_text(getattr(api_key, "user_id", None)),
    }


async def _sync_apikey_identity_cache(api_key: APIKey) -> None:
    payload = _apikey_identity_payload(api_key)
    key_text = payload.get("key") or ""
    object_id = payload.get("object_id") or ""
    client = _get_kv_apikey_identity_client()
    if key_text:
        await client.set(_apikey_identity_key_by_key(key_text), payload)
    if object_id:
        await client.set(_apikey_identity_key_by_id(object_id), payload)


async def _delete_apikey_identity_cache(api_key: APIKey) -> None:
    key_text = str(getattr(api_key, "key", "") or "").strip()
    object_id = str(getattr(api_key, "id", "") or "").strip()
    client = _get_kv_apikey_identity_client()
    if key_text:
        await client.delete(_apikey_identity_key_by_key(key_text))
    if object_id:
        await client.delete(_apikey_identity_key_by_id(object_id))


async def get_apikey_identity_from_cache(key_or_object_id: str) -> APIKeyIdentityCachePayload | None:
    lookup = str(key_or_object_id or "").strip()
    if not lookup:
        return None
    client = _get_kv_apikey_identity_client()
    raw = await client.get(_apikey_identity_key_by_key(lookup), default=None)
    if not isinstance(raw, dict):
        raw = await client.get(_apikey_identity_key_by_id(lookup), default=None)
    if not isinstance(raw, dict):
        return None
    return {
        "object_id": str(raw.get("object_id") or "").strip(),
        "key": str(raw.get("key") or "").strip(),
        "user_id": _normalize_optional_text(raw.get("user_id")),
    }


def _generate_api_key_value() -> str:
    return f"proj_{secrets.token_urlsafe(24)}"


def _bounded_history(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    return entries[:_APIKEY_HISTORY_LIMIT]


def _append_history(entries: list[dict[str, object]], entry: dict[str, object]) -> list[dict[str, object]]:
    return _bounded_history([entry, *entries])


def _normalize_role_value(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return normalize_patterns([str(item) for item in value])
    text = str(value or "").strip()
    return [text] if text else []


def _role_names(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return normalize_patterns([str(item) for item in value])
    text = str(value or "").strip()
    return [text] if text else []


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def _ensure_unique_api_key_value(key: str, *, exclude_id: str | None = None) -> str:
    existing = await APIKey.SearchOne({"key": key}, client=_get_apikey_orm_client())
    if existing is None:
        return key
    existing_id = str(getattr(existing, "id", "") or "")
    if exclude_id and existing_id == exclude_id:
        return key
    raise ValueError(f"API key already exists: {key}")


def _window_name(scope: str, pattern: str, index: int, mode: str) -> str:
    return f"{scope}|{pattern}|{index}|{mode}"


def _minimum_interval_key(scope: str, pattern: str) -> str:
    return f"{scope}|{pattern}"


def _matched_rate_limits(subject: _PermissionSubject, route: str) -> list[tuple[str, RateLimitConfig]]:
    matches: list[tuple[str, RateLimitConfig]] = []
    for pattern, config in subject.rate_limit.items():
        if not str(pattern or "").strip():
            continue
        if subject._match_route_pattern(route, pattern):
            matches.append((pattern, config))
    matches.sort(key=lambda item: (sum(ch in "*?[" for ch in item[0]), -len(item[0]), item[0]))
    return matches


def _permission_scope(subject: _PermissionSubject) -> str:
    if isinstance(subject, PermissionRole):
        return f"role:{subject.name}"
    return "apikey"


def _permission_label(subject: _PermissionSubject) -> str:
    if isinstance(subject, PermissionRole):
        return f"permission role {subject.name}"
    return "API key"


def _failure_priority(result: APIKeyValidationResult) -> int:
    priority = {
        "insufficient_credit": 50,
        "rate_limited": 40,
        "minimum_interval": 40,
        "route_not_allowed": 30,
        "banned": 20,
        "not_found": 10,
        "ok": 0,
    }
    return priority.get(result.reason, 0)


def _prefer_failure(current: APIKeyValidationResult | None, candidate: APIKeyValidationResult) -> APIKeyValidationResult:
    if current is None:
        return candidate
    return candidate if _failure_priority(candidate) >= _failure_priority(current) else current


async def _resolve_permission_subjects(api_key: APIKey) -> tuple[list[_PermissionSubject], list[str]]:
    role_names = _role_names(api_key.role)
    if not role_names:
        return [api_key], []
    subjects: list[_PermissionSubject] = []
    missing_roles: list[str] = []
    for role_name in role_names:
        role = await get_permission_role_by_name(role_name)
        if role is None:
            missing_roles.append(role_name)
            continue
        subjects.append(role)
    return subjects, missing_roles


def _check_permission_subject(
    subject: _PermissionSubject,
    *,
    api_key: APIKey,
    route_text: str,
    cost: float,
    record_access: bool,
    stats: APIKeyUsageStats,
    now_ts: float,
) -> tuple[APIKeyValidationResult | None, list[str]]:
    subject_label = _permission_label(subject)
    if subject.banned:
        return (
            _failure_result(
                api_key=api_key,
                route=route_text,
                reason="banned",
                detail=f"{subject_label} is banned",
                cost=cost,
            ),
            [],
        )
    if not subject._is_route_allowed(route_text):
        return (
            _failure_result(
                api_key=api_key,
                route=route_text,
                reason="route_not_allowed",
                detail=f"Route not allowed by {subject_label}: {route_text}",
                cost=cost,
            ),
            [],
        )

    matched_limits = _matched_rate_limits(subject, route_text)
    matched_patterns = [pattern for pattern, _ in matched_limits]
    minimum_interval_last_access_at = stats.setdefault("minimum_interval_last_access_at", {})
    sliding_windows = stats.setdefault("sliding_windows", {})
    fixed_windows = stats.setdefault("fixed_windows", {})
    scope = _permission_scope(subject)

    for pattern, config in matched_limits:
        minimum_interval = float(config.minimum_interval_seconds or 0.0)
        if minimum_interval > 0:
            last_access_key = _minimum_interval_key(scope, pattern)
            last_access_at = float(minimum_interval_last_access_at.get(last_access_key, 0.0) or 0.0)
            delta = now_ts - last_access_at
            if last_access_at > 0 and delta < minimum_interval:
                return (
                    _failure_result(
                        api_key=api_key,
                        route=route_text,
                        reason="minimum_interval",
                        detail=f"Minimum interval not reached for {subject_label} pattern {pattern}",
                        matched_patterns=matched_patterns,
                        retry_after_seconds=max(minimum_interval - delta, 0.0),
                        cost=cost,
                    ),
                    matched_patterns,
                )

        for index, limit in enumerate(config.limits):
            if isinstance(limit, SlidingWindowRateLimit):
                state_key = _window_name(scope, pattern, index, "sliding")
                timestamps = [
                    float(ts)
                    for ts in sliding_windows.get(state_key, [])
                    if now_ts - float(ts) < float(limit.reset_interval_seconds)
                ]
                if len(timestamps) >= int(limit.capacity):
                    retry_after = max(float(limit.reset_interval_seconds) - (now_ts - timestamps[0]), 0.0)
                    sliding_windows[state_key] = timestamps
                    return (
                        _failure_result(
                            api_key=api_key,
                            route=route_text,
                            reason="rate_limited",
                            detail=f"Sliding window limit exceeded for {subject_label} pattern {pattern}",
                            matched_patterns=matched_patterns,
                            retry_after_seconds=retry_after,
                            cost=cost,
                        ),
                        matched_patterns,
                    )
                if record_access:
                    timestamps.append(now_ts)
                sliding_windows[state_key] = timestamps
                continue

            state_key = _window_name(scope, pattern, index, "fixed")
            window_start_at, window_end_at = fixed_window_bounds(limit.reset_time, now_ts)
            state = fixed_windows.get(state_key, {})
            if not isinstance(state, dict) or float(state.get("window_start_at", -1.0) or -1.0) != window_start_at:
                state = {"window_start_at": window_start_at, "count": 0}
            count = int(state.get("count", 0) or 0)
            if count >= int(limit.capacity):
                fixed_windows[state_key] = state
                return (
                    _failure_result(
                        api_key=api_key,
                        route=route_text,
                        reason="rate_limited",
                        detail=f"Fixed window limit exceeded for {subject_label} pattern {pattern}",
                        matched_patterns=matched_patterns,
                        retry_after_seconds=max(window_end_at - now_ts, 0.0),
                        cost=cost,
                    ),
                    matched_patterns,
                )
            if record_access:
                state["count"] = count + 1
            fixed_windows[state_key] = state

    if record_access:
        route_stats = stats.setdefault("routes", {}).get(route_text)
        if not isinstance(route_stats, dict):
            route_stats = {}
            stats.setdefault("routes", {})[route_text] = route_stats
        route_stats["access_count"] = int(route_stats.get("access_count", 0) or 0) + 1
        route_stats["last_access_at"] = now_ts
        stats["access_count"] = int(stats.get("access_count", 0) or 0) + 1
        stats["last_access_at"] = now_ts
        stats["access_history"] = _append_history(
            stats.setdefault("access_history", []),
            {
                "at": now_ts,
                "route": route_text,
                "matched_patterns": list(matched_patterns),
                "cost": float(cost),
            },
        )
        for pattern, config in matched_limits:
            if float(config.minimum_interval_seconds or 0.0) > 0:
                minimum_interval_last_access_at[_minimum_interval_key(scope, pattern)] = now_ts

    return None, matched_patterns


def _datetime_from_timestamp(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value))


async def get_apikey_by_id(object_id: str) -> APIKey | None:
    object_id_text = str(object_id or "").strip()
    if not object_id_text:
        return None
    api_key = await APIKey.SearchOneById(object_id_text, client=_get_apikey_orm_client())
    if api_key is not None:
        await _sync_apikey_identity_cache(api_key)
    return api_key


async def get_apikey_by_key(key: str) -> APIKey | None:
    key_text = str(key or "").strip()
    if not key_text:
        return None
    cached_identity = await get_apikey_identity_from_cache(key_text)
    cached_object_id = str((cached_identity or {}).get("object_id") or "").strip()
    if cached_object_id:
        api_key = await APIKey.SearchOneById(cached_object_id, client=_get_apikey_orm_client())
        if api_key is not None:
            await _sync_apikey_identity_cache(api_key)
            return api_key
    api_key = await APIKey.SearchOne({"key": key_text}, client=_get_apikey_orm_client())
    if api_key is not None:
        await _sync_apikey_identity_cache(api_key)
    return api_key


async def list_apikeys(*, limit: int = 100, offset: int = 0) -> tuple[list[APIKey], int | None]:
    client = _get_apikey_orm_client()
    items = [item async for item in APIKey.Search(limit=limit, offset=offset, client=client)]
    query_count = getattr(client, "query_count", None)
    total = await query_count(APIKey) if callable(query_count) else None
    return items, total


async def get_apikey_expire_seconds(api_key: APIKey) -> float | None:
    object_id = str(getattr(api_key, "id", "") or "").strip()
    if not object_id:
        return None
    return await _get_apikey_orm_client().get_expire(APIKey, object_id)


async def create_apikey(**kwargs: APIKeyCreateParams) -> APIKey:
    key_text = str(kwargs.get("key") or "").strip() or _generate_api_key_value()
    await _ensure_unique_api_key_value(key_text)
    now = datetime.now()
    api_key = APIKey(
        key=key_text,
        created_at=now,
        edited_at=now,
        name=kwargs.get("name"),
        comment=kwargs.get("comment"),
        user_id=_normalize_optional_text(kwargs.get("user_id")),
        credit=float(kwargs.get("credit", 0.0) or 0.0),
        banned=bool(kwargs.get("banned", False)),
        role=_normalize_role_value(kwargs.get("role")),
        whitelist_routes=kwargs.get("whitelist_routes", "all"),
        blacklist_routes=normalize_patterns(kwargs.get("blacklist_routes", _default_internal_blacklist_routes())),
        rate_limit=kwargs.get("rate_limit", {}),
    )
    await api_key.save(
        client=_get_apikey_orm_client(),
        expire=kwargs.get("expire_seconds"),
    )
    await _record_credit_history(
        api_key,
        action="create",
        delta=float(api_key.credit),
        before_credit=0.0,
        after_credit=float(api_key.credit),
    )
    await _sync_apikey_identity_cache(api_key)
    return api_key


async def update_apikey(object_id: str, **kwargs: APIKeyUpdateParams) -> APIKey:
    api_key = await get_apikey_by_id(object_id)
    if api_key is None:
        raise LookupError(f"API key not found: {object_id}")
    if "name" in kwargs:
        api_key.name = kwargs.get("name")
    if "comment" in kwargs:
        api_key.comment = kwargs.get("comment")
    if "user_id" in kwargs:
        api_key.user_id = _normalize_optional_text(kwargs.get("user_id"))
    if "banned" in kwargs:
        api_key.banned = bool(kwargs.get("banned"))
    if "role" in kwargs:
        api_key.role = _normalize_role_value(kwargs.get("role"))
    if "whitelist_routes" in kwargs:
        api_key.whitelist_routes = normalize_whitelist_routes_value(kwargs["whitelist_routes"])
    if "blacklist_routes" in kwargs:
        api_key.blacklist_routes = normalize_patterns(kwargs["blacklist_routes"])
    if "rate_limit" in kwargs:
        api_key.rate_limit = kwargs["rate_limit"]
    await api_key.save(client=_get_apikey_orm_client())
    if "expire_seconds" in kwargs:
        await _get_apikey_orm_client().set_expire(APIKey, str(api_key.id), kwargs.get("expire_seconds"))
    await _sync_apikey_identity_cache(api_key)
    return api_key


async def set_apikey_credit(object_id: str, credit: float) -> APIKey:
    if credit < 0:
        raise ValueError("credit must be >= 0")
    api_key = await get_apikey_by_id(object_id)
    if api_key is None:
        raise LookupError(f"API key not found: {object_id}")
    before_credit = float(api_key.credit)
    api_key.credit = float(credit)
    await api_key.save(client=_get_apikey_orm_client())
    await _record_credit_history(
        api_key,
        action="set",
        delta=float(api_key.credit) - before_credit,
        before_credit=before_credit,
        after_credit=float(api_key.credit),
    )
    return api_key


async def adjust_apikey_credit(object_id: str, delta: float) -> APIKey:
    api_key = await get_apikey_by_id(object_id)
    if api_key is None:
        raise LookupError(f"API key not found: {object_id}")
    before_credit = float(api_key.credit)
    next_credit = before_credit + float(delta)
    if next_credit < 0:
        raise ValueError("credit cannot become negative")
    api_key.credit = next_credit
    await api_key.save(client=_get_apikey_orm_client())
    await _record_credit_history(
        api_key,
        action="delta",
        delta=float(delta),
        before_credit=before_credit,
        after_credit=float(api_key.credit),
    )
    return api_key


async def delete_apikey(object_id: str) -> bool:
    api_key = await get_apikey_by_id(object_id)
    if api_key is None:
        return False
    deleted = await api_key.delete(client=_get_apikey_orm_client())
    if deleted:
        await _get_kv_apikey_record_client().delete(_apikey_record_key(api_key))
        await _delete_apikey_identity_cache(api_key)
    return deleted


async def get_apikey_stats(api_key: APIKey) -> APIKeyStatsSnapshot:
    raw = await _get_kv_apikey_record_client().get(_apikey_record_key(api_key), default={})
    payload = raw if isinstance(raw, dict) else {}
    return APIKeyStatsSnapshot.model_validate(
        {
            "object_id": str(getattr(api_key, "id", "") or ""),
            "key": api_key.key,
            "access_count": int(payload.get("access_count", 0) or 0),
            "usage_count": int(payload.get("usage_count", 0) or 0),
            "total_cost": float(payload.get("total_cost", 0.0) or 0.0),
            "last_access_at": payload.get("last_access_at"),
            "last_usage_at": payload.get("last_usage_at"),
            "routes": payload.get("routes", {}),
            "access_history": payload.get("access_history", []),
            "credit_history": payload.get("credit_history", []),
        }
    )


async def _load_usage_stats(api_key: APIKey) -> APIKeyUsageStats:
    raw = await _get_kv_apikey_record_client().get(_apikey_record_key(api_key), default={})
    payload = raw if isinstance(raw, dict) else {}
    routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
    minimum_interval_last_access_at = payload.get("minimum_interval_last_access_at")
    sliding_windows = payload.get("sliding_windows")
    fixed_windows = payload.get("fixed_windows")
    return {
        "object_id": str(getattr(api_key, "id", "") or ""),
        "key": api_key.key,
        "access_count": int(payload.get("access_count", 0) or 0),
        "usage_count": int(payload.get("usage_count", 0) or 0),
        "total_cost": float(payload.get("total_cost", 0.0) or 0.0),
        "last_access_at": float(payload.get("last_access_at", 0.0) or 0.0) if payload.get("last_access_at") is not None else 0.0,
        "last_usage_at": float(payload.get("last_usage_at", 0.0) or 0.0) if payload.get("last_usage_at") is not None else 0.0,
        "routes": routes,
        "access_history": payload.get("access_history") if isinstance(payload.get("access_history"), list) else [],
        "credit_history": payload.get("credit_history") if isinstance(payload.get("credit_history"), list) else [],
        "minimum_interval_last_access_at": minimum_interval_last_access_at if isinstance(minimum_interval_last_access_at, dict) else {},
        "sliding_windows": sliding_windows if isinstance(sliding_windows, dict) else {},
        "fixed_windows": fixed_windows if isinstance(fixed_windows, dict) else {},
    }


async def _save_usage_stats(api_key: APIKey, stats: APIKeyUsageStats) -> None:
    await _get_kv_apikey_record_client().set(_apikey_record_key(api_key), stats)


async def _record_credit_history(
    api_key: APIKey,
    *,
    action: Literal["create", "set", "delta", "charge"],
    delta: float,
    before_credit: float,
    after_credit: float,
    route: str | None = None,
) -> None:
    stats = await _load_usage_stats(api_key)
    history = stats.setdefault("credit_history", [])
    history = _append_history(
        history,
        {
            "at": time.time(),
            "action": action,
            "delta": float(delta),
            "before_credit": float(before_credit),
            "after_credit": float(after_credit),
            "route": route,
        },
    )
    stats["credit_history"] = history
    await _save_usage_stats(api_key, stats)


def _failure_result(
    *,
    api_key: APIKey | None,
    route: str,
    reason: APIKeyValidationResult.model_fields["reason"].annotation,
    detail: str,
    matched_patterns: list[str] | None = None,
    retry_after_seconds: float | None = None,
    cost: float = 0.0,
) -> APIKeyValidationResult:
    current_credit = None if api_key is None else float(api_key.credit)
    remaining_credit = None if current_credit is None else max(current_credit - float(cost), current_credit)
    return APIKeyValidationResult(
        ok=False,
        reason=reason,
        route=route,
        object_id=None if api_key is None else str(getattr(api_key, "id", "") or ""),
        key=None if api_key is None else api_key.key,
        matched_patterns=matched_patterns or [],
        credit=current_credit,
        remaining_credit=remaining_credit if reason == "insufficient_credit" else current_credit,
        retry_after_seconds=retry_after_seconds,
        detail=detail,
    )


async def _resolve_validation(
    key_or_api_key: str | APIKey,
    route: str,
    *,
    cost: float = 0.0,
    record_access: bool = False,
) -> _ResolvedValidation:
    if cost < 0:
        raise ValueError("cost must be >= 0")
    api_key = key_or_api_key if isinstance(key_or_api_key, APIKey) else await get_apikey_by_key(str(key_or_api_key))
    route_text = str(route or "").strip()
    if api_key is None:
        return _ResolvedValidation(
            None,
            APIKeyValidationResult(ok=False, reason="not_found", route=route_text, detail="API key not found"),
        )
    if api_key.banned:
        return _ResolvedValidation(
            api_key,
            _failure_result(api_key=api_key, route=route_text, reason="banned", detail="API key is banned", cost=cost),
        )
    if float(api_key.credit) < float(cost):
        return _ResolvedValidation(
            api_key,
            _failure_result(
                api_key=api_key,
                route=route_text,
                reason="insufficient_credit",
                detail="Insufficient credit",
                cost=cost,
            ),
        )

    subjects, missing_roles = await _resolve_permission_subjects(api_key)
    if not subjects:
        missing_text = ", ".join(missing_roles) or "<empty>"
        return _ResolvedValidation(
            api_key,
            _failure_result(
                api_key=api_key,
                route=route_text,
                reason="route_not_allowed",
                detail=f"Permission role not found: {missing_text}",
                cost=cost,
            ),
        )

    stats = await _load_usage_stats(api_key)
    now_ts = time.time()
    best_failure: APIKeyValidationResult | None = None
    for subject in subjects:
        failure, matched_patterns = _check_permission_subject(
            subject,
            api_key=api_key,
            route_text=route_text,
            cost=cost,
            record_access=record_access,
            stats=stats,
            now_ts=now_ts,
        )
        if failure is not None:
            best_failure = _prefer_failure(best_failure, failure)
            continue
        if record_access:
            api_key.last_used_at = _datetime_from_timestamp(now_ts)
            await api_key.save(client=_get_apikey_orm_client(), touch_edited_at=False)
            await _save_usage_stats(api_key, stats)
        return _ResolvedValidation(
            api_key,
            APIKeyValidationResult(
                ok=True,
                reason="ok",
                route=route_text,
                object_id=str(getattr(api_key, "id", "") or ""),
                key=api_key.key,
                matched_patterns=matched_patterns,
                credit=float(api_key.credit),
                remaining_credit=max(float(api_key.credit) - float(cost), 0.0),
                detail="ok",
            ),
            stats,
        )

    return _ResolvedValidation(
        api_key,
        best_failure
        or _failure_result(
            api_key=api_key,
            route=route_text,
            reason="route_not_allowed",
            detail=f"Route not allowed: {route_text}",
            cost=cost,
        ),
        stats,
    )


async def validate_apikey_route(
    key_or_api_key: str | APIKey,
    route: str,
    *,
    cost: float = 0.0,
    record_access: bool = False,
) -> APIKeyValidationResult:
    return (await _resolve_validation(key_or_api_key, route, cost=cost, record_access=record_access)).result


async def record_apikey_access(api_key: APIKey, route: str) -> APIKeyValidationResult:
    resolved = await _resolve_validation(api_key, route, cost=0.0, record_access=True)
    if not resolved.result.ok:
        raise ValueError(resolved.result.detail or resolved.result.reason)
    return resolved.result


async def validate_apikey_identity(key_or_api_key: str | APIKey) -> APIKeyValidationResult:
    api_key = key_or_api_key if isinstance(key_or_api_key, APIKey) else await get_apikey_by_key(str(key_or_api_key))
    route = "*"
    if api_key is None:
        return APIKeyValidationResult(ok=False, reason="not_found", route=route, detail="API key not found.")
    if api_key.banned:
        return APIKeyValidationResult(
            ok=False,
            reason="banned",
            route=route,
            object_id=str(getattr(api_key, "id", "") or "") or None,
            key=str(api_key.key),
            credit=float(api_key.credit),
            remaining_credit=float(api_key.credit),
            detail="API key is banned.",
        )
    return APIKeyValidationResult(
        ok=True,
        reason="ok",
        route=route,
        object_id=str(getattr(api_key, "id", "") or "") or None,
        key=str(api_key.key),
        credit=float(api_key.credit),
        remaining_credit=float(api_key.credit),
        detail="API key is valid.",
    )


async def record_apikey_usage(api_key: APIKey, route: str, cost: float) -> APIKeyStatsSnapshot:
    if cost < 0:
        raise ValueError("cost must be >= 0")
    before_credit = float(api_key.credit)
    if before_credit < float(cost):
        raise ValueError("Insufficient credit")
    stats = await _load_usage_stats(api_key)
    now_ts = time.time()
    route_stats = stats.setdefault("routes", {}).get(route)
    if not isinstance(route_stats, dict):
        route_stats = {}
        stats.setdefault("routes", {})[route] = route_stats
    route_stats["usage_count"] = int(route_stats.get("usage_count", 0) or 0) + 1
    route_stats["total_cost"] = float(route_stats.get("total_cost", 0.0) or 0.0) + float(cost)
    route_stats["last_usage_at"] = now_ts
    stats["usage_count"] = int(stats.get("usage_count", 0) or 0) + 1
    stats["total_cost"] = float(stats.get("total_cost", 0.0) or 0.0) + float(cost)
    stats["last_usage_at"] = now_ts
    api_key.credit = before_credit - float(cost)
    stats["credit_history"] = _append_history(
        stats.setdefault("credit_history", []),
        {
            "at": now_ts,
            "action": "charge",
            "delta": -float(cost),
            "before_credit": before_credit,
            "after_credit": float(api_key.credit),
            "route": route,
        },
    )
    api_key.last_used_at = _datetime_from_timestamp(now_ts)
    await api_key.save(client=_get_apikey_orm_client(), touch_edited_at=False)
    await _save_usage_stats(api_key, stats)
    return await get_apikey_stats(api_key)


def extract_apikey_from_request(request: Request) -> str | None:
    current_apikey = str(getattr(request, "apikey", "") or "").strip()
    if current_apikey:
        return current_apikey
    header_key = (request.headers.get("x-api-key") or "").strip()
    if header_key:
        return header_key
    authorization = (request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    cookie_key = (request.cookies.get("x-api-key") or "").strip()
    if cookie_key:
        return cookie_key
    query_key = (request.query_params.get("api_key") or request.query_params.get("x_api_key") or "").strip()
    if query_key:
        return query_key
    return None


def require_apikey_from_request(request: Request) -> str:
    token = extract_apikey_from_request(request)
    if token:
        return token
    raise HTTPException(401, "Missing API key")


def extract_apikey_from_websocket(websocket: WebSocket) -> str | None:
    header_key = (websocket.headers.get("x-api-key") or "").strip()
    if header_key:
        return header_key
    authorization = (websocket.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    query_key = (websocket.query_params.get("api_key") or websocket.query_params.get("x_api_key") or "").strip()
    if query_key:
        return query_key
    return None


def _validation_http_status(result: APIKeyValidationResult) -> int:
    if result.reason == "not_found":
        return 401
    if result.reason in {"banned", "route_not_allowed"}:
        return 403
    if result.reason == "insufficient_credit":
        return 402
    if result.reason in {"minimum_interval", "rate_limited"}:
        return 429
    return 400


def credit_route_wrapper(
    func: Callable[Concatenate[Request, P], Awaitable[Any]],
    route: str,
    cost: float,
) -> Callable[Concatenate[Request, P], Awaitable[Any]]:
    @wraps(func)
    async def _wrapped(request: Request, *args: P.args, **kwargs: P.kwargs) -> Any:
        api_key_text = require_apikey_from_request(request)
        resolved = await _resolve_validation(api_key_text, route, cost=cost, record_access=True)
        if resolved.api_key is None or not resolved.result.ok:
            raise HTTPException(_validation_http_status(resolved.result), resolved.result.detail or resolved.result.reason)
        response = await func(request, *args, **kwargs)
        if cost > 0:
            await record_apikey_usage(resolved.api_key, route, cost)
        return response

    return _wrapped


def apikey_to_dict(api_key: APIKey) -> dict[str, Any]:
    return {
        "id": str(getattr(api_key, "id", "") or ""),
        "key": api_key.key,
        "banned": bool(api_key.banned),
        "created_at": api_key.created_at,
        "edited_at": api_key.edited_at,
        "last_used_at": api_key.last_used_at,
        "role": list(api_key.role) if api_key.role else None,
        "user_id": api_key.user_id,
        "blacklist_routes": list(api_key.blacklist_routes),
        "whitelist_routes": export_whitelist_routes(api_key.whitelist_routes),
        "rate_limit": api_key.rate_limit,
        "credit": float(api_key.credit),
        "name": api_key.name,
        "comment": api_key.comment,
    }


__all__ = [
    "SlidingWindowRateLimit",
    "FixedWindowRateLimit",
    "RateLimitConfig",
    "APIKey",
    "APIKeyAccessHistoryEntry",
    "APIKeyCreditHistoryEntry",
    "APIKeyValidationResult",
    "APIKeyStatsSnapshot",
    "apikey_to_dict",
    "get_apikey_by_id",
    "get_apikey_by_key",
    "get_apikey_identity_from_cache",
    "list_apikeys",
    "get_apikey_expire_seconds",
    "create_apikey",
    "update_apikey",
    "set_apikey_credit",
    "adjust_apikey_credit",
    "delete_apikey",
    "get_apikey_stats",
    "extract_apikey_from_request",
    "require_apikey_from_request",
    "extract_apikey_from_websocket",
    "validate_apikey_identity",
    "validate_apikey_route",
    "record_apikey_access",
    "record_apikey_usage",
    "credit_route_wrapper",
]