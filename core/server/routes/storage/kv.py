# -*- coding: utf-8 -*-


import base64
import math
import re
from typing import Any, Literal
import fnmatch

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from ...app import on_before_app_created

from ._common import (
    _section_client_names,
    describe_value,
    get_backend_type,
    get_storage_config,
    jsonable_value,
    storage_html_response,
    ttl_payload,
)
from ._models import (
    KVBulkTTLResponse,
    KVConfigResponse,
    KVDeleteByPrefixResponse,
    KVDeleteManyResponse,
    KVDeleteResponse,
    KVItemResponse,
    KVKeysResponse,
    KVSummaryResponse,
    KVTransferResponse,
    KVWriteResponse,
    StorageCleanupResponse,
    StorageClientsResponse,
)


class KVSetBody(BaseModel):
    mode: Literal["json", "text", "base64"] = "json"
    value: Any = None
    expire_seconds: float | None = Field(default=None)


class KVTTLBody(BaseModel):
    expire_seconds: float | None = Field(default=None)


class KVPrefixDeleteBody(BaseModel):
    prefix: str = ""
    dry_run: bool = False
    limit: int = Field(default=1000, ge=1, le=10000)


class KVDeleteManyBody(BaseModel):
    keys: list[str] = Field(default_factory=list)


class KVBulkTTLBody(BaseModel):
    keys: list[str] = Field(default_factory=list)
    expire_seconds: float | None = Field(default=None)


class KVTransferBody(BaseModel):
    source_key: str = Field(min_length=1)
    target_key: str = Field(min_length=1)
    overwrite: bool = False
    preserve_ttl: bool = True


def _kv_namespace_segments(key: str, prefix: str | None = None) -> list[str]:
    key_text = str(key or "")
    prefix_text = str(prefix or "")
    if prefix_text and key_text.startswith(prefix_text):
        key_text = key_text[len(prefix_text) :]
    key_text = key_text.strip(":/")
    if not key_text:
        return []
    return [part for part in re.split(r":+", key_text) if part]


def _kv_ttl_bucket(ttl_seconds: float | None) -> str:
    if ttl_seconds is None:
        return "no_expiry"
    if ttl_seconds <= 60:
        return "lt_1m"
    if ttl_seconds <= 3600:
        return "lt_1h"
    if ttl_seconds <= 86400:
        return "lt_1d"
    if ttl_seconds <= 7 * 86400:
        return "lt_7d"
    return "gte_7d"


def _kv_key_length_bucket(key_text: str) -> str:
    length = len(key_text)
    if length <= 15:
        return "1-15"
    if length <= 31:
        return "16-31"
    if length <= 63:
        return "32-63"
    return "64+"


def _get_exact_kv_config(client_name: str | None) -> tuple[str, Any]:
    section = get_storage_config().kv
    requested_name = str(client_name or "default").strip() or "default"
    if requested_name in type(section).model_fields:
        config = getattr(section, requested_name, None)
        if config is not None:
            return requested_name, config
    if requested_name in section.extra:
        config = section.extra.get(requested_name)
        if config is not None:
            return requested_name, config
    raise HTTPException(404, f"KV client '{requested_name}' not found")


def _get_exact_kv_client(client_name: str | None) -> tuple[str, Any, Any]:
    section = get_storage_config().kv
    resolved_name, config = _get_exact_kv_config(client_name)
    client = section.get_client(resolved_name, fallback="", fuzzy=False)
    return resolved_name, config, client


async def _kv_get_existing_value(client: Any, key: str) -> Any:
    missing = object()
    value = await client.get(key, default=missing)
    if value is missing:
        raise HTTPException(404, "Key not found")
    return value


async def _kv_has_key(client: Any, key: str) -> bool:
    missing = object()
    return await client.get(key, default=missing) is not missing


@on_before_app_created
def register_storage_kv_routes(app: FastAPI):

    @app.get("/admin/storage/kv")
    async def storage_kv_page():
        return storage_html_response("kv")

    @app.get("/admin/api/storage/kv/clients", response_model=StorageClientsResponse)
    async def storage_kv_clients() -> StorageClientsResponse:
        section = get_storage_config().kv
        return StorageClientsResponse.model_validate({"clients": _section_client_names(section)})

    @app.get("/admin/api/storage/kv/config", response_model=KVConfigResponse)
    async def storage_kv_config(client_name: str | None = Query(default=None, alias="client")) -> KVConfigResponse:
        resolved_name, config, client = _get_exact_kv_client(client_name)
        return KVConfigResponse.model_validate({
            "client_name": resolved_name,
            "backend": get_backend_type(config),
            "namespace": getattr(config, "namespace", getattr(client, "_namespace", "default")),
            "client_metadata": client.metadata(),
            "default_expire": getattr(config, "default_expire", None),
            "max_size": getattr(config, "max_size", None),
            "list_strategy": "full-scan-prefix-filter",
            "supports_binary": True,
            "supports_bulk_delete": True,
            "supports_pattern_search": True,
            "supports_bulk_ttl": True,
            "supports_copy": True,
            "supports_rename": True,
        })

    @app.get("/admin/api/storage/kv/keys", response_model=KVKeysResponse)
    async def storage_kv_keys(
        prefix: str | None = Query(default=None),
        q: str | None = Query(default=None),
        pattern: str | None = Query(default=None),
        value_kind: str | None = Query(default=None),
        ttl_state: str | None = Query(default=None),
        min_ttl: float | None = Query(default=None, ge=0),
        max_ttl: float | None = Query(default=None, ge=0),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVKeysResponse:
        _, _, client = _get_exact_kv_client(client_name)
        keys = await client.keys(prefix=prefix)
        q_text = str(q or "").strip().lower()
        pattern_text = str(pattern or "").strip().lower()
        value_kind_text = str(value_kind or "").strip().lower()
        ttl_state_text = str(ttl_state or "").strip().lower()
        items = []
        for key in keys:
            key_text = str(key)
            lowered = key_text.lower()
            if q_text and q_text not in lowered:
                continue
            if pattern_text and not fnmatch.fnmatch(lowered, pattern_text):
                continue
            ttl = await client.get_expire(key)
            if ttl_state_text == "persistent" and ttl is not None:
                continue
            if ttl_state_text == "expiring" and ttl is None:
                continue
            if min_ttl is not None and (ttl is None or ttl < min_ttl):
                continue
            if max_ttl is not None and (ttl is None or ttl > max_ttl):
                continue
            if value_kind_text:
                value = await client.get(key_text, default=None)
                detail = describe_value(value)
                item_value_kind = str(detail.get("value_kind") or "unknown").lower()
                if item_value_kind != value_kind_text:
                    continue
            items.append({"key": key, **ttl_payload(ttl)})
        total = len(items)
        page_count = max(1, math.ceil(total / page_size)) if total else 1
        safe_page = min(max(page, 1), page_count)
        start = (safe_page - 1) * page_size
        return KVKeysResponse.model_validate({
            "items": items[start : start + page_size],
            "total": total,
            "page": safe_page,
            "page_count": page_count,
            "page_size": page_size,
            "prefix": prefix or "",
            "query": q or "",
            "pattern": pattern or "",
            "value_kind": value_kind or "",
            "ttl_state_filter": ttl_state or "",
            "min_ttl": min_ttl,
            "max_ttl": max_ttl,
        })

    @app.get("/admin/api/storage/kv/summary", response_model=KVSummaryResponse)
    async def storage_kv_summary(
        prefix: str | None = Query(default=None),
        q: str | None = Query(default=None),
        pattern: str | None = Query(default=None),
        value_kind: str | None = Query(default=None),
        ttl_state: str | None = Query(default=None),
        min_ttl: float | None = Query(default=None, ge=0),
        max_ttl: float | None = Query(default=None, ge=0),
        sample_limit: int = Query(default=2000, ge=100, le=10000),
        value_sample_limit: int = Query(default=400, ge=20, le=2000),
        top_n: int = Query(default=12, ge=1, le=50),
        expiring_limit: int = Query(default=12, ge=1, le=50),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVSummaryResponse:
        _, _, client = _get_exact_kv_client(client_name)
        keys = await client.keys(prefix=prefix)
        q_text = str(q or "").strip().lower()
        pattern_text = str(pattern or "").strip().lower()
        value_kind_text = str(value_kind or "").strip().lower()
        ttl_state_text = str(ttl_state or "").strip().lower()

        ttl_bucket_order = ["no_expiry", "lt_1m", "lt_1h", "lt_1d", "lt_7d", "gte_7d"]
        ttl_bucket_labels = {
            "no_expiry": "No Expiry",
            "lt_1m": "< 1 min",
            "lt_1h": "1 min - 1 hr",
            "lt_1d": "1 hr - 1 day",
            "lt_7d": "1 - 7 days",
            "gte_7d": "> 7 days",
        }
        length_bucket_order = ["1-15", "16-31", "32-63", "64+"]

        ttl_buckets = {key: 0 for key in ttl_bucket_order}
        length_buckets = {key: 0 for key in length_bucket_order}
        namespace_counts: dict[str, int] = {}
        sample_items: list[dict[str, Any]] = []
        soonest_expiring: list[dict[str, Any]] = []
        total_matched = 0
        persistent_count = 0
        expiring_count = 0
        ttl_sum = 0.0
        ttl_count = 0
        min_ttl_value: float | None = None
        max_ttl_value: float | None = None
        type_counts: dict[str, int] = {}
        largest_items: list[dict[str, Any]] = []
        sampled_value_bytes = 0
        value_sampled_count = 0

        for key in keys:
            key_text = str(key)
            lowered = key_text.lower()
            if q_text and q_text not in lowered:
                continue
            if pattern_text and not fnmatch.fnmatch(lowered, pattern_text):
                continue

            ttl = await client.get_expire(key_text)
            if ttl_state_text == "persistent" and ttl is not None:
                continue
            if ttl_state_text == "expiring" and ttl is None:
                continue
            if min_ttl is not None and (ttl is None or ttl < min_ttl):
                continue
            if max_ttl is not None and (ttl is None or ttl > max_ttl):
                continue

            detail: dict[str, Any] | None = None
            value_kind_name = ""
            if value_kind_text:
                value = await client.get(key_text, default=None)
                detail = describe_value(value)
                value_kind_name = str(detail.get("value_kind") or "unknown").lower()
                if value_kind_name != value_kind_text:
                    continue

            total_matched += 1
            ttl_bucket_key = _kv_ttl_bucket(ttl)
            ttl_buckets[ttl_bucket_key] += 1
            length_buckets[_kv_key_length_bucket(key_text)] += 1

            if ttl is None:
                persistent_count += 1
            else:
                expiring_count += 1
                ttl_sum += float(ttl)
                ttl_count += 1
                min_ttl_value = ttl if min_ttl_value is None else min(min_ttl_value, ttl)
                max_ttl_value = ttl if max_ttl_value is None else max(max_ttl_value, ttl)
                soonest_expiring.append({"key": key_text, **ttl_payload(ttl)})

            namespace = _kv_namespace_segments(key_text, prefix)
            namespace_label = namespace[0] if namespace else "(root)"
            namespace_counts[namespace_label] = namespace_counts.get(namespace_label, 0) + 1

            if len(sample_items) < sample_limit:
                sample_items.append({"key": key_text, **ttl_payload(ttl)})

            if value_sampled_count < value_sample_limit:
                if detail is None:
                    value = await client.get(key_text, default=None)
                    detail = describe_value(value)
                size_estimate = int(detail.get("size_bytes_estimate") or 0)
                value_kind_name = str(detail.get("value_kind") or "unknown")
                type_counts[value_kind_name] = type_counts.get(value_kind_name, 0) + 1
                sampled_value_bytes += size_estimate
                value_sampled_count += 1
                largest_items.append({
                    "key": key_text,
                    "value_kind": value_kind_name,
                    "size_bytes_estimate": size_estimate,
                    **ttl_payload(ttl),
                })

        soonest_expiring.sort(key=lambda item: float(item.get("ttl_seconds") or math.inf))
        top_namespaces = sorted(namespace_counts.items(), key=lambda entry: (-entry[1], entry[0]))[:top_n]
        largest_items.sort(key=lambda item: (-int(item.get("size_bytes_estimate") or 0), item.get("key") or ""))

        return KVSummaryResponse.model_validate({
            "prefix": prefix or "",
            "query": q or "",
            "pattern": pattern or "",
            "value_kind": value_kind or "",
            "ttl_state_filter": ttl_state or "",
            "min_ttl": min_ttl,
            "max_ttl": max_ttl,
            "scanned_total": len(keys),
            "matched_total": total_matched,
            "persistent_count": persistent_count,
            "expiring_count": expiring_count,
            "ttl_stats": {
                "min_ttl": min_ttl_value,
                "max_ttl": max_ttl_value,
                "avg_ttl": (ttl_sum / ttl_count) if ttl_count else None,
            },
            "ttl_buckets": [
                {"key": bucket, "label": ttl_bucket_labels[bucket], "count": ttl_buckets[bucket]}
                for bucket in ttl_bucket_order
            ],
            "key_length_buckets": [
                {"label": bucket, "count": length_buckets[bucket]}
                for bucket in length_bucket_order
            ],
            "top_namespaces": [
                {"label": label, "count": count}
                for label, count in top_namespaces
            ],
            "soonest_expiring": soonest_expiring[:expiring_limit],
            "sample_limit": sample_limit,
            "sampled_count": len(sample_items),
            "truncated": total_matched > len(sample_items),
            "sample_items": sample_items,
            "value_sampled_count": value_sampled_count,
            "value_metrics_truncated": total_matched > value_sampled_count,
            "sampled_value_bytes": sampled_value_bytes,
            "sampled_avg_value_bytes": (sampled_value_bytes / value_sampled_count) if value_sampled_count else None,
            "type_counts": [
                {"label": label, "count": count}
                for label, count in sorted(type_counts.items(), key=lambda entry: (-entry[1], entry[0]))
            ],
            "largest_items": largest_items[:top_n],
        })

    @app.get("/admin/api/storage/kv/item", response_model=KVItemResponse)
    async def storage_kv_item(
        key: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVItemResponse:
        _, _, client = _get_exact_kv_client(client_name)
        missing = object()
        value = await client.get(key, default=missing)
        if value is missing:
            raise HTTPException(404, "Key not found")
        ttl = await client.get_expire(key)
        detail = describe_value(value)
        return KVItemResponse.model_validate({
            "key": key,
            "exists": True,
            **ttl_payload(ttl),
            **detail,
            "editable": True,
        })

    @app.put("/admin/api/storage/kv/item", response_model=KVWriteResponse)
    async def storage_kv_put(
        body: KVSetBody,
        key: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVWriteResponse:
        _, _, client = _get_exact_kv_client(client_name)
        value = body.value
        if body.mode == "text":
            value = "" if value is None else str(value)
        elif body.mode == "base64":
            try:
                value = base64.b64decode(str(value or ""), validate=True)
            except Exception as exc:
                raise HTTPException(400, f"Invalid base64 payload: {exc}") from exc
        else:
            value = jsonable_value(value)
        await client.set(key, value, expire=body.expire_seconds)
        ttl = await client.get_expire(key)
        return KVWriteResponse.model_validate({"ok": True, "key": key, **ttl_payload(ttl)})

    @app.patch("/admin/api/storage/kv/item/ttl", response_model=KVWriteResponse)
    async def storage_kv_patch_ttl(
        body: KVTTLBody,
        key: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVWriteResponse:
        _, _, client = _get_exact_kv_client(client_name)
        ok = await client.set_expire(key, body.expire_seconds)
        if not ok:
            raise HTTPException(404, "Key not found")
        ttl = await client.get_expire(key)
        return KVWriteResponse.model_validate({"ok": True, "key": key, **ttl_payload(ttl)})

    @app.post("/admin/api/storage/kv/item/copy", response_model=KVTransferResponse)
    async def storage_kv_copy_item(
        body: KVTransferBody,
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVTransferResponse:
        _, _, client = _get_exact_kv_client(client_name)
        source_key = str(body.source_key).strip()
        target_key = str(body.target_key).strip()
        if source_key == target_key:
            raise HTTPException(400, "Target key must differ from source key")
        value = await _kv_get_existing_value(client, source_key)
        target_exists = await _kv_has_key(client, target_key)
        if target_exists and not body.overwrite:
            raise HTTPException(409, "Target key already exists")
        expire_seconds = await client.get_expire(source_key) if body.preserve_ttl else None
        await client.set(target_key, value, expire=expire_seconds)
        ttl = await client.get_expire(target_key)
        return KVTransferResponse.model_validate({
            "ok": True,
            "action": "copy",
            "source_key": source_key,
            "target_key": target_key,
            "overwritten": target_exists,
            **ttl_payload(ttl),
        })

    @app.post("/admin/api/storage/kv/item/rename", response_model=KVTransferResponse)
    async def storage_kv_rename_item(
        body: KVTransferBody,
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVTransferResponse:
        _, _, client = _get_exact_kv_client(client_name)
        source_key = str(body.source_key).strip()
        target_key = str(body.target_key).strip()
        if source_key == target_key:
            raise HTTPException(400, "Target key must differ from source key")
        value = await _kv_get_existing_value(client, source_key)
        target_exists = await _kv_has_key(client, target_key)
        if target_exists and not body.overwrite:
            raise HTTPException(409, "Target key already exists")
        expire_seconds = await client.get_expire(source_key) if body.preserve_ttl else None
        await client.set(target_key, value, expire=expire_seconds)
        source_deleted = bool(await client.delete(source_key))
        if not source_deleted:
            raise HTTPException(500, "Rename failed to remove source key")
        ttl = await client.get_expire(target_key)
        return KVTransferResponse.model_validate({
            "ok": True,
            "action": "rename",
            "source_key": source_key,
            "target_key": target_key,
            "overwritten": target_exists,
            "source_deleted": source_deleted,
            **ttl_payload(ttl),
        })

    @app.delete("/admin/api/storage/kv/item", response_model=KVDeleteResponse)
    async def storage_kv_delete(
        key: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVDeleteResponse:
        _, _, client = _get_exact_kv_client(client_name)
        deleted = await client.delete(key)
        return KVDeleteResponse.model_validate({"ok": True, "deleted": deleted, "key": key})

    @app.post("/admin/api/storage/kv/delete-by-prefix", response_model=KVDeleteByPrefixResponse)
    async def storage_kv_delete_by_prefix(
        body: KVPrefixDeleteBody,
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVDeleteByPrefixResponse:
        _, _, client = _get_exact_kv_client(client_name)
        keys = await client.keys(prefix=body.prefix or None)
        matched_total = len(keys)
        keys = keys[: body.limit]
        truncated = matched_total > len(keys)
        if body.dry_run:
            return KVDeleteByPrefixResponse.model_validate({
                "matched": len(keys),
                "matched_total": matched_total,
                "processed": len(keys),
                "deleted": 0,
                "truncated": truncated,
                "keys": keys[:100],
            })
        deleted = 0
        for key in keys:
            if await client.delete(key):
                deleted += 1
        return KVDeleteByPrefixResponse.model_validate({
            "matched": len(keys),
            "matched_total": matched_total,
            "processed": len(keys),
            "deleted": deleted,
            "truncated": truncated,
            "keys": keys[:100],
        })

    @app.post("/admin/api/storage/kv/delete-many", response_model=KVDeleteManyResponse)
    async def storage_kv_delete_many(
        body: KVDeleteManyBody,
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVDeleteManyResponse:
        _, _, client = _get_exact_kv_client(client_name)
        removed = 0
        items = []
        for key in body.keys:
            key_text = str(key or "").strip()
            if not key_text:
                continue
            deleted = await client.delete(key_text)
            removed += int(bool(deleted))
            items.append({"key": key_text, "deleted": bool(deleted)})
        return KVDeleteManyResponse.model_validate({"deleted": removed > 0, "removed": removed, "items": items})

    @app.patch("/admin/api/storage/kv/items/ttl", response_model=KVBulkTTLResponse)
    async def storage_kv_patch_many_ttl(
        body: KVBulkTTLBody,
        client_name: str | None = Query(default=None, alias="client"),
    ) -> KVBulkTTLResponse:
        _, _, client = _get_exact_kv_client(client_name)
        updated = 0
        items = []
        for key in body.keys:
            key_text = str(key or "").strip()
            if not key_text:
                continue
            ok = await client.set_expire(key_text, body.expire_seconds)
            if ok:
                updated += 1
            ttl = await client.get_expire(key_text) if ok else None
            items.append({"key": key_text, "updated": bool(ok), **ttl_payload(ttl)})
        return KVBulkTTLResponse.model_validate({"updated": updated, "count": len(items), "items": items})

    @app.post("/admin/api/storage/kv/cleanup", response_model=StorageCleanupResponse)
    async def storage_kv_cleanup(
        force: bool = True,
        client_name: str | None = Query(default=None, alias="client"),
    ) -> StorageCleanupResponse:
        _, _, client = _get_exact_kv_client(client_name)
        removed = await client.cleanup(force=force)
        return StorageCleanupResponse.model_validate({"removed": removed})
