# -*- coding: utf-8 -*-
"""REST API for querying / managing the ORM application log and AI service call logs."""

import time
import json
import asyncio
from collections import defaultdict
from pathlib import Path

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import ConfigDict, Field

from core.ai.shared import AIServiceKind
from core.utils.type_utils import AdvancedBaseModel
from core.server.data_types.config import Config

from ...html_injection import html_response_from_path
from ...app import get_resources, internal_admin_path, on_before_app_created
from ...shared import AppSharedData, RuntimeMeta

if TYPE_CHECKING:
    from core.storage.orm import DefaultORMLogStore


_log_store_singleton = None


def _get_log_store() -> "DefaultORMLogStore":
    """Get the ORM log store singleton (db mode only)."""
    global _log_store_singleton

    from core.storage.config import StorageConfig
    from core.storage.orm import get_default_log_store, get_log_record_model

    cfg = StorageConfig.Global()
    client = cfg.get_log_orm_client()
    collection_name = str(getattr(cfg.orm.log, "log_collection_name", "log") or "log")
    if _log_store_singleton is not None:
        try:
            cached_client = _log_store_singleton._get_client()
            cached_collection = _log_store_singleton._get_model_cls().CollectionName
            if cached_client is client and cached_collection == collection_name:
                return _log_store_singleton
        except Exception:
            pass
    _log_store_singleton = get_default_log_store(client, lambda: get_log_record_model(collection_name))
    return _log_store_singleton


def _get_service_log_mixin():
    """Lazily import ServiceCallLogMixin."""
    from core.ai.base import ServiceCallLogMixin
    return ServiceCallLogMixin


def _get_shared() -> AppSharedData:
    return AppSharedData.Get()


def _make_cache_key(namespace: str, **payload) -> str:
    return f"logs:{namespace}:{json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)}"


def _runtime_meta() -> RuntimeMeta:
    return _get_shared().get_runtime_meta()


class LogsResponseModel(AdvancedBaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, use_attribute_docstrings=True)


class LogsRuntimeMeta(LogsResponseModel):
    instance_uuid: str | None = None
    worker_pid: int | None = None
    cache_scope: str | None = None
    server_start_time: str | None = None
    worker_count: int | None = None
    request_count_total: int | None = None
    supervisor_pid: int | None = None
    control_mode: str | None = None
    control_supported: bool | None = None
    config_file_path: str | None = None
    workers: list['LogsWorkerInfo'] = Field(default_factory=list)


class LogsWorkerInfo(LogsResponseModel):
    pid: int | None = None
    msg_port: int | None = None
    started_at: str | None = None
    request_count: int | None = None
    last_request_at: str | None = None
    status: str | None = None


class LogsConfigResponse(LogsRuntimeMeta):
    db_enabled: bool
    sqlite_enabled: bool
    file_enabled: bool
    log_path: str | None = None


class BackendLogRow(LogsResponseModel):
    id: str | None = None
    timestamp: str | None = None
    level: str | None = None
    levelno: int | None = None
    name: str | None = None
    message: str | None = None


class LogsQueryResponse(AdvancedBaseModel):
    total: int
    offset: int
    limit: int
    returned: int
    has_more: bool
    rows: list[BackendLogRow] = Field(default_factory=list)
    meta: LogsRuntimeMeta | None = None


class LogsDeleteResponse(AdvancedBaseModel):
    deleted: str | None = None
    deleted_before: str | None = None


class ServiceCallLogEntry(LogsResponseModel):
    id: str | None = None
    created_at: str | None = None
    service_kind: AIServiceKind | str | None = None
    operation: str | None = None
    client_class: str | None = None
    success: bool | None = None
    duration_ms: float | None = None
    error_type: str | None = None
    error_message: str | None = None
    request_chars: int | None = None
    response_chars: int | None = None
    pid: int | None = None
    project_root: str | None = None


class ServiceCallStatEntry(AdvancedBaseModel):
    group: str
    call_count: int
    success_count: int
    failure_count: int
    avg_duration_ms: float
    last_called_at: str | None = None


class ServiceCallTimelineEntry(AdvancedBaseModel):
    time: str
    total: int
    success: int
    failure: int


class LogsOverviewBackend(AdvancedBaseModel):
    total: int
    recent_errors: list[BackendLogRow] = Field(default_factory=list)
    error_count_24h: int
    warning_count_24h: int


class LogsOverviewService(AdvancedBaseModel):
    stats_by_operation: list[ServiceCallStatEntry] = Field(default_factory=list)
    stats_by_kind: list[ServiceCallStatEntry] = Field(default_factory=list)
    recent_failures: list[ServiceCallLogEntry] = Field(default_factory=list)
    total_calls: int


class LogsOverviewResponse(AdvancedBaseModel):
    backend: LogsOverviewBackend
    service: LogsOverviewService
    meta: LogsRuntimeMeta | None = None


class LogsAggregateMetrics(AdvancedBaseModel):
    total: int
    warning: int
    error: int
    critical: int
    warning_24h: int
    error_24h: int
    top_level: str | None = None
    top_logger: str | None = None
    logger_count: int


class LogsAggregateLogger(AdvancedBaseModel):
    name: str
    count: int


class LogsAggregateTimelineEntry(AdvancedBaseModel):
    bucket: str
    total: int
    WARNING: int
    ERROR: int
    CRITICAL: int
    by_logger: dict[str, int] = Field(default_factory=dict)


class LogsAggregateWindow(AdvancedBaseModel):
    since: str
    until: str
    bucket_minutes: int
    fetched_buckets: int
    cached_buckets: int
    open_bucket: str


class LogsAggregateAnalysisRow(AdvancedBaseModel):
    group: str
    count: int
    WARNING: int
    ERROR: int
    CRITICAL: int
    last: str | None = None


class LogsAggregateResponse(AdvancedBaseModel):
    metrics: LogsAggregateMetrics
    level_dist: dict[str, int] = Field(default_factory=dict)
    top_loggers: list[LogsAggregateLogger] = Field(default_factory=list)
    top_logger_names: list[str] = Field(default_factory=list)
    timeline: list[LogsAggregateTimelineEntry] = Field(default_factory=list)
    analysis_by_level: list[LogsAggregateAnalysisRow] = Field(default_factory=list)
    analysis_by_logger: list[LogsAggregateAnalysisRow] = Field(default_factory=list)
    window: LogsAggregateWindow
    meta: LogsRuntimeMeta | None = None


def _floor_to_bucket(dt: datetime, bucket_minutes: int) -> datetime:
    """Snap ``dt`` down to the start of its ``bucket_minutes`` bucket."""
    if bucket_minutes >= 60 and bucket_minutes % 60 == 0:
        hours = bucket_minutes // 60
        snapped = dt.replace(minute=0, second=0, microsecond=0)
        return snapped.replace(hour=(snapped.hour // hours) * hours)
    snapped = dt.replace(second=0, microsecond=0)
    return snapped.replace(minute=(snapped.minute // bucket_minutes) * bucket_minutes)


async def _get_cached_backend_log_total(store) -> int:
    shared = _get_shared()
    cache_key = _make_cache_key("backend_total")
    cached = shared.get_cache(cache_key)
    if cached is not None:
        return int(cached)
    total = await store.count()
    return shared.set_cache(cache_key, total, ttl_seconds=5)


@on_before_app_created
def register_log_routes(app: FastAPI):
    admin_path = internal_admin_path

    # ── Log sub-page serving ──────────────────────────────────────────────

    def _serve_log_html(name: str) -> HTMLResponse:
        path = get_resources("admin-panel", "log", f"log_{name}.html") or Path(f"log_{name}.html")
        return html_response_from_path(path, not_found_message=f"log/log_{name}.html not found")

    @app.get(admin_path("log/overview"), response_class=HTMLResponse)
    async def log_overview_page():
        return _serve_log_html("overview")

    @app.get(admin_path("log/service"), response_class=HTMLResponse)
    async def log_service_page():
        return _serve_log_html("service")

    @app.get(admin_path("log/backend"), response_class=HTMLResponse)
    async def log_backend_page():
        return _serve_log_html("backend")

    @app.get(admin_path("log/analysis"), response_class=HTMLResponse)
    async def log_analysis_page():
        return _serve_log_html("backend")

    @app.get(admin_path("log/detail"), response_class=HTMLResponse)
    async def log_detail_page():
        return _serve_log_html("backend")

    # ── GET /admin/api/logs/config ────────────────────────────────────────

    @app.get(admin_path("api/logs/config"), response_model=LogsConfigResponse)
    async def logs_config() -> LogsConfigResponse:
        cfg = Config.GetConfig().log_config
        db_enabled = "db" in cfg.log_method
        file_enabled = "file" in cfg.log_method
        return LogsConfigResponse.model_validate({
            "db_enabled": db_enabled,
            "sqlite_enabled": db_enabled,
            "file_enabled": file_enabled,
            "log_path": cfg.log_path if file_enabled else None,
            **_runtime_meta(),
        })

    @app.get(admin_path("api/logs/meta"), response_model=LogsRuntimeMeta)
    async def logs_meta() -> LogsRuntimeMeta:
        return LogsRuntimeMeta.model_validate(_runtime_meta())

    # ── GET /admin/api/logs ───────────────────────────────────────────────

    @app.get(admin_path("api/logs"), response_model=LogsQueryResponse)
    async def query_logs(
        level: Optional[str] = Query(None, description="Exact level string, e.g. INFO"),
        min_levelno: Optional[int] = Query(None, description="Minimum levelno, e.g. 20 for INFO"),
        name: Optional[str] = Query(None, description="Logger name substring filter"),
        search: Optional[str] = Query(None, description="Message substring filter"),
        since: Optional[str] = Query(None, description="ISO-8601 lower bound for timestamp"),
        until: Optional[str] = Query(None, description="ISO-8601 upper bound for timestamp"),
        order: str = Query("DESC", description="Row order: ASC or DESC"),
        limit: int = Query(200, ge=1, le=5000),
        offset: int = Query(0, ge=0),
    ) -> LogsQueryResponse:
        cfg = Config.GetConfig().log_config
        if "db" not in cfg.log_method:
            raise HTTPException(
                status_code=404,
                detail="DB logging not enabled. Add 'db' to --log-method to enable log UI.",
            )
        shared = _get_shared()
        cache_key = _make_cache_key(
            "backend_query",
            level=level,
            min_levelno=min_levelno,
            name=name,
            search=search,
            since=since,
            until=until,
            order=order,
            limit=limit,
            offset=offset,
        )
        cached = shared.get_cache(cache_key)
        if cached is not None:
            return LogsQueryResponse.model_validate(cached)
        store = _get_log_store()
        rows, total = await store.query(
            limit=limit,
            offset=offset,
            level=level,
            min_levelno=min_levelno,
            name_filter=name,
            search=search,
            since=since,
            until=until,
            order=order,
            include_total=True,
        )
        payload = {
            "total": total,
            "offset": offset,
            "limit": limit,
            "returned": len(rows),
            "has_more": len(rows) >= limit,
            "rows": rows,
            "meta": _runtime_meta(),
        }
        return LogsQueryResponse.model_validate(shared.set_cache(cache_key, payload, ttl_seconds=5))

    # ── GET /admin/api/logs/aggregate ─────────────────────────────────────

    @app.get(admin_path("api/logs/aggregate"), response_model=LogsAggregateResponse)
    async def aggregate_logs(
        hours: int = Query(24, ge=1, le=168),
        bucket_minutes: int = Query(60, ge=1, le=180),
        level: Optional[str] = Query(None),
        min_levelno: Optional[int] = Query(None),
        name: Optional[str] = Query(None),
        search: Optional[str] = Query(None),
        top_loggers: int = Query(10, ge=1, le=50),
    ) -> LogsAggregateResponse:
        cfg = Config.GetConfig().log_config
        if "db" not in cfg.log_method:
            raise HTTPException(status_code=404, detail="DB logging not enabled.")
        shared = _get_shared()
        store = _get_log_store()
        bm = int(bucket_minutes)
        # Always fetch at least 24h so the 24h counters stay correct even when
        # the user picks a shorter request window.
        fetch_hours = max(int(hours), 24)
        # Filter hash (excludes the time window so cache entries can be reused
        # across different `hours` selections of the same filter set).
        filter_hash = json.dumps(
            {"level": level, "min_levelno": min_levelno, "name": name, "search": search},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        now = datetime.now()
        open_start = _floor_to_bucket(now, bm)
        window_start = _floor_to_bucket(now - timedelta(hours=fetch_hours), bm)
        # Build the list of sealed bucket starts in chrono order.
        sealed_starts: list[datetime] = []
        cur = window_start
        while cur < open_start:
            sealed_starts.append(cur)
            cur = cur + timedelta(minutes=bm)
        # Look up sealed buckets in cache.
        cached_buckets: dict[str, dict[str, object]] = {}
        missing_starts: list[datetime] = []
        for bs in sealed_starts:
            bs_iso = bs.strftime("%Y-%m-%d %H:%M")
            ck = f"logs:agg:bucket:{filter_hash}:{bm}:{bs_iso}"
            c = shared.get_cache(ck)
            if c is not None:
                cached_buckets[bs_iso] = c  # type: ignore[assignment]
            else:
                missing_starts.append(bs)
        # Fetch all missing sealed buckets in a single SQL aggregation.
        if missing_starts:
            first = missing_starts[0]
            last_end = missing_starts[-1] + timedelta(minutes=bm)
            try:
                fresh = await store.aggregate_buckets(
                    since=first.strftime("%Y-%m-%d %H:%M:%S"),
                    until=last_end.strftime("%Y-%m-%d %H:%M:%S"),
                    bucket_minutes=bm,
                    level=level,
                    min_levelno=min_levelno,
                    name_filter=name,
                    search=search,
                )
            except TypeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            fresh_by_bucket = {str(f["bucket"]): f for f in fresh}
            for bs in missing_starts:
                bs_iso = bs.strftime("%Y-%m-%d %H:%M")
                agg = fresh_by_bucket.get(bs_iso) or {
                    "bucket": bs_iso, "total": 0, "level_dist": {}, "name_counts": {},
                }
                ck = f"logs:agg:bucket:{filter_hash}:{bm}:{bs_iso}"
                shared.set_cache(ck, agg, ttl_seconds=3600)
                cached_buckets[bs_iso] = agg
        # Always recompute the open (current) bucket; cache briefly.
        open_iso = open_start.strftime("%Y-%m-%d %H:%M")
        open_ck = f"logs:agg:open:{filter_hash}:{bm}:{open_iso}"
        open_agg = shared.get_cache(open_ck)
        if open_agg is None:
            try:
                open_aggs = await store.aggregate_buckets(
                    since=open_start.strftime("%Y-%m-%d %H:%M:%S"),
                    until=(now + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"),
                    bucket_minutes=bm,
                    level=level,
                    min_levelno=min_levelno,
                    name_filter=name,
                    search=search,
                )
            except TypeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            open_agg = next(
                (a for a in open_aggs if str(a.get("bucket")) == open_iso),
                {"bucket": open_iso, "total": 0, "level_dist": {}, "name_counts": {}},
            )
            shared.set_cache(open_ck, open_agg, ttl_seconds=5)
        # All buckets in chrono order: sealed (cached) + open.
        ordered_buckets: list[dict[str, object]] = [
            cached_buckets[bs.strftime("%Y-%m-%d %H:%M")] for bs in sealed_starts
        ]
        ordered_buckets.append(open_agg)  # type: ignore[arg-type]
        # Restrict the *response* timeline / metrics to the requested `hours` window;
        # the wider 24h slice is only used for warning_24h / error_24h.
        request_start = _floor_to_bucket(now - timedelta(hours=int(hours)), bm)
        request_start_iso = request_start.strftime("%Y-%m-%d %H:%M")
        in_window = [b for b in ordered_buckets if str(b["bucket"]) >= request_start_iso]
        level_totals: dict[str, int] = defaultdict(int)
        name_totals: dict[str, int] = defaultdict(int)
        # Per-group level breakdown for the analysis table (mode=level / mode=logger).
        level_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        name_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        level_last_seen: dict[str, str] = {}
        name_last_seen: dict[str, str] = {}
        total_count = 0
        for b in in_window:
            ld_raw = b.get("level_dist") or {}
            nc_raw = b.get("name_counts") or {}
            nl_raw = b.get("name_level") or {}
            last_seen = str(b.get("last_seen") or b.get("bucket") or "")
            for l, c in ld_raw.items():  # type: ignore[union-attr]
                cnt = int(c or 0)
                if cnt <= 0:
                    continue
                key = str(l)
                level_totals[key] += cnt
                level_breakdown[key][key] += cnt
                if last_seen > level_last_seen.get(key, ""):
                    level_last_seen[key] = last_seen
            for n, c in nc_raw.items():  # type: ignore[union-attr]
                cnt = int(c or 0)
                if cnt <= 0:
                    continue
                key = str(n)
                name_totals[key] += cnt
                if last_seen > name_last_seen.get(key, ""):
                    name_last_seen[key] = last_seen
            for n, lv_map in nl_raw.items():  # type: ignore[union-attr]
                for l, c in (lv_map or {}).items():
                    name_breakdown[str(n)][str(l)] += int(c or 0)
            total_count += int(b.get("total") or 0)  # type: ignore[arg-type]
        sorted_names = sorted(name_totals.items(), key=lambda x: x[1], reverse=True)
        top_logger_names_list = [n for n, _ in sorted_names[:top_loggers]]
        top_loggers_list = [{"name": n, "count": c} for n, c in sorted_names[:50]]
        cutoff_24h_iso = _floor_to_bucket(now - timedelta(hours=24), bm).strftime("%Y-%m-%d %H:%M")
        warning_24h = 0
        error_24h = 0
        for b in ordered_buckets:
            if str(b["bucket"]) >= cutoff_24h_iso:
                ld = b.get("level_dist") or {}
                warning_24h += int(ld.get("WARNING", 0) or 0)  # type: ignore[union-attr]
                error_24h += int(ld.get("ERROR", 0) or 0)  # type: ignore[union-attr]
        timeline_list = []
        for b in in_window:
            ld = b.get("level_dist") or {}
            nc = b.get("name_counts") or {}
            timeline_list.append({
                "bucket": str(b["bucket"]),
                "total": int(b.get("total") or 0),  # type: ignore[arg-type]
                "WARNING": int(ld.get("WARNING", 0) or 0),  # type: ignore[union-attr]
                "ERROR": int(ld.get("ERROR", 0) or 0),  # type: ignore[union-attr]
                "CRITICAL": int(ld.get("CRITICAL", 0) or 0),  # type: ignore[union-attr]
                "by_logger": {n: int((nc.get(n, 0) or 0)) for n in top_logger_names_list},  # type: ignore[union-attr]
            })
        top_level = max(level_totals.items(), key=lambda x: x[1])[0] if level_totals else None
        analysis_by_level = [
            {
                "group": k,
                "count": v,
                "WARNING": int(level_breakdown.get(k, {}).get("WARNING", 0)),
                "ERROR": int(level_breakdown.get(k, {}).get("ERROR", 0)),
                "CRITICAL": int(level_breakdown.get(k, {}).get("CRITICAL", 0)),
                "last": level_last_seen.get(k) or None,
            }
            for k, v in sorted(level_totals.items(), key=lambda x: x[1], reverse=True)
        ]
        analysis_by_logger = [
            {
                "group": n,
                "count": c,
                "WARNING": int(name_breakdown.get(n, {}).get("WARNING", 0)),
                "ERROR": int(name_breakdown.get(n, {}).get("ERROR", 0)),
                "CRITICAL": int(name_breakdown.get(n, {}).get("CRITICAL", 0)),
                "last": name_last_seen.get(n) or None,
            }
            for n, c in sorted_names[:50]
        ]
        return LogsAggregateResponse.model_validate({
            "metrics": {
                "total": total_count,
                "warning": int(level_totals.get("WARNING", 0)),
                "error": int(level_totals.get("ERROR", 0)),
                "critical": int(level_totals.get("CRITICAL", 0)),
                "warning_24h": warning_24h,
                "error_24h": error_24h,
                "top_level": top_level,
                "top_logger": (top_loggers_list[0]["name"] if top_loggers_list else None),
                "logger_count": len(name_totals),
            },
            "level_dist": dict(level_totals),
            "top_loggers": top_loggers_list,
            "top_logger_names": top_logger_names_list,
            "timeline": timeline_list,
            "analysis_by_level": analysis_by_level,
            "analysis_by_logger": analysis_by_logger,
            "window": {
                "since": request_start.strftime("%Y-%m-%d %H:%M:%S"),
                "until": now.strftime("%Y-%m-%d %H:%M:%S"),
                "bucket_minutes": bm,
                "fetched_buckets": len(missing_starts) + 1,
                "cached_buckets": len(sealed_starts) - len(missing_starts),
                "open_bucket": open_iso,
            },
            "meta": _runtime_meta(),
        })

    @app.delete(admin_path("api/logs"), response_model=LogsDeleteResponse)
    async def delete_all_logs() -> LogsDeleteResponse:
        cfg = Config.GetConfig().log_config
        if "db" not in cfg.log_method:
            raise HTTPException(status_code=404, detail="DB logging not enabled.")
        store = _get_log_store()
        await store.delete_all()
        _get_shared().invalidate_cache(prefix="logs:")
        return LogsDeleteResponse(deleted="all")

    # ── DELETE /admin/api/logs/before/{timestamp} ─────────────────────────

    @app.delete(admin_path("api/logs/before/{timestamp:path}"), response_model=LogsDeleteResponse)
    async def delete_logs_before(timestamp: str) -> LogsDeleteResponse:
        cfg = Config.GetConfig().log_config
        if "db" not in cfg.log_method:
            raise HTTPException(status_code=404, detail="DB logging not enabled.")
        store = _get_log_store()
        await store.delete_before(timestamp)
        _get_shared().invalidate_cache(prefix="logs:")
        return LogsDeleteResponse(deleted_before=timestamp)

    # ══════════════════════════════════════════════════════════════════════
    # Service call logs (AI services QueryCallLogs / QueryCallStats)
    # ══════════════════════════════════════════════════════════════════════

    @app.get(admin_path("api/logs/service/logs"), response_model=list[ServiceCallLogEntry])
    async def query_service_call_logs(
        limit: int = Query(100, ge=1, le=5000),
        success: Optional[bool] = Query(None),
        operation: Optional[str] = Query(None),
        client_class: Optional[str] = Query(None),
        service_kind: Optional[str] = Query(None),
        since: Optional[float] = Query(None, description="Unix timestamp lower bound"),
        until: Optional[float] = Query(None, description="Unix timestamp upper bound"),
    ) -> list[ServiceCallLogEntry]:
        """Query AI service call logs via ServiceCallLogMixin.QueryCallLogs."""
        try:
            mixin = _get_service_log_mixin()
            return [ServiceCallLogEntry.model_validate(item) for item in mixin.QueryCallLogs(
                limit=limit,
                success=success,
                operation=operation,
                client_class=client_class,
                service_kind=service_kind,
                since=since,
                until=until,
            )]
        except Exception as e:
            raise HTTPException(500, f"Query service logs failed: {e}")

    @app.get(admin_path("api/logs/service/stats"), response_model=list[ServiceCallStatEntry])
    async def query_service_call_stats(
        group_by: Literal["service_kind", "operation", "client_class"] = Query("operation"),
        success: Optional[bool] = Query(None),
        operation: Optional[str] = Query(None),
        client_class: Optional[str] = Query(None),
        service_kind: Optional[str] = Query(None),
        since: Optional[float] = Query(None),
        until: Optional[float] = Query(None),
    ) -> list[ServiceCallStatEntry]:
        """Aggregate AI service call statistics via ServiceCallLogMixin.QueryCallStats."""
        try:
            cache_key = _make_cache_key(
                "service_stats",
                group_by=group_by,
                success=success,
                operation=operation,
                client_class=client_class,
                service_kind=service_kind,
                since=since,
                until=until,
            )
            shared = _get_shared()
            cached = shared.get_cache(cache_key)
            if cached is not None:
                return [ServiceCallStatEntry.model_validate(item) for item in cached]
            mixin = _get_service_log_mixin()
            result = mixin.QueryCallStats(
                group_by=group_by,
                success=success,
                operation=operation,
                client_class=client_class,
                service_kind=service_kind,
                since=since,
                until=until,
            )
            cached_result = shared.set_cache(cache_key, result, ttl_seconds=10)
            return [ServiceCallStatEntry.model_validate(item) for item in cached_result]
        except Exception as e:
            raise HTTPException(500, f"Query service stats failed: {e}")

    @app.get(admin_path("api/logs/service/timeline"), response_model=list[ServiceCallTimelineEntry])
    async def service_call_timeline(
        hours: int = Query(24, ge=1, le=168),
        bucket_minutes: int = Query(60, ge=1, le=1440),
    ) -> list[ServiceCallTimelineEntry]:
        """Get aggregated call counts over time for charting."""
        try:
            cache_key = _make_cache_key("service_timeline", hours=hours, bucket_minutes=bucket_minutes)
            shared = _get_shared()
            cached = shared.get_cache(cache_key)
            if cached is not None:
                return [ServiceCallTimelineEntry.model_validate(item) for item in cached]
            mixin = _get_service_log_mixin()
            now = time.time()
            since = now - hours * 3600
            logs = mixin.QueryCallLogs(limit=50000, since=since)
            # Bucket by time
            buckets: dict[str, dict] = {}
            for log_entry in logs:
                ts = log_entry.get("created_at", "")
                if not ts:
                    continue
                # Parse ISO timestamp to bucket
                try:
                    from datetime import datetime as _dt
                    dt = _dt.fromisoformat(ts)
                    # Round down to bucket
                    minute = (dt.minute // bucket_minutes) * bucket_minutes
                    bucket_key = dt.strftime(f"%Y-%m-%d %H:") + f"{minute:02d}"
                except Exception:
                    continue
                if bucket_key not in buckets:
                    buckets[bucket_key] = {"time": bucket_key, "total": 0, "success": 0, "failure": 0}
                buckets[bucket_key]["total"] += 1
                if log_entry.get("success"):
                    buckets[bucket_key]["success"] += 1
                else:
                    buckets[bucket_key]["failure"] += 1
            # Sort by time
            timeline = sorted(buckets.values(), key=lambda x: x["time"])
            cached_timeline = shared.set_cache(cache_key, timeline, ttl_seconds=10)
            return [ServiceCallTimelineEntry.model_validate(item) for item in cached_timeline]
        except Exception as e:
            raise HTTPException(500, f"Timeline query failed: {e}")

    @app.get(admin_path("api/logs/overview"), response_model=LogsOverviewResponse)
    async def logs_overview() -> LogsOverviewResponse:
        """Aggregated overview for the dashboard: recent errors, service health, and backend log summary."""
        shared = _get_shared()
        cache_key = _make_cache_key("overview")
        cached = shared.get_cache(cache_key)
        if cached is not None:
            return LogsOverviewResponse.model_validate(cached)
        result = {
            "backend": {"total": 0, "recent_errors": [], "error_count_24h": 0, "warning_count_24h": 0},
            "service": {"stats_by_operation": [], "stats_by_kind": [], "recent_failures": [], "total_calls": 0},
            "meta": _runtime_meta(),
        }
        # Backend log summary
        cfg = Config.GetConfig().log_config
        if "db" in cfg.log_method:
            try:
                store = _get_log_store()
                since_24h = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                backend_total_task = asyncio.create_task(_get_cached_backend_log_total(store))
                recent_errors_task = asyncio.create_task(store.query(limit=10, min_levelno=40, order="DESC"))
                error_count_task = asyncio.create_task(store.count_filtered(min_levelno=40, since=since_24h))
                warning_count_task = asyncio.create_task(store.count_filtered(level="WARNING", since=since_24h))
                (
                    result["backend"]["total"],
                    result["backend"]["recent_errors"],
                    result["backend"]["error_count_24h"],
                    result["backend"]["warning_count_24h"],
                ) = await asyncio.gather(
                    backend_total_task,
                    recent_errors_task,
                    error_count_task,
                    warning_count_task,
                )
            except Exception:
                pass
        # Service log summary
        try:
            mixin = _get_service_log_mixin()
            (
                result["service"]["stats_by_operation"],
                result["service"]["stats_by_kind"],
                result["service"]["recent_failures"],
            ) = await asyncio.gather(
                asyncio.to_thread(mixin.QueryCallStats, group_by="operation"),
                asyncio.to_thread(mixin.QueryCallStats, group_by="service_kind"),
                asyncio.to_thread(mixin.QueryCallLogs, limit=10, success=False),
            )
            total = sum(s["call_count"] for s in result["service"]["stats_by_operation"])
            result["service"]["total_calls"] = total
        except Exception:
            pass
        return LogsOverviewResponse.model_validate(shared.set_cache(cache_key, result, ttl_seconds=15))
