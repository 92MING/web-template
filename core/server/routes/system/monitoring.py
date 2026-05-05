# -*- coding: utf-8 -*-
"""System monitoring API routes and response models.

Provides endpoints:
    GET /admin/api/system            ?C latest system snapshot
    GET /admin/api/system/cpu        ?C detailed CPU metrics
    GET /admin/api/system/gpu        ?C cross-vendor GPU summary
    GET /admin/api/system_last_infos ?C metric history
    GET /admin/api/system/extended   ?C host info + uptime
    GET /admin/panel/system/*        ?C panel sub-pages (HTML)
"""

import asyncio
import logging
import os
import psutil
import time
import threading

from collections import deque
from typing import Optional, cast
from datetime import datetime, timedelta

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocket, WebSocketDisconnect
from pydantic import Field

from core.utils.type_utils import AdvancedBaseModel
from core.utils.system_utils.helper_funcs import (
    get_host_info,
    HostInfo,
    get_disks_usage,
    get_memory_usage,
    get_network_io,
    get_disk_io,
    get_network_interfaces,
    get_disk_partitions_info,
)
from core.utils.system_utils.cpu_info import collect_cpu_details, CpuDetails, warm_cpu_static_cache
from core.utils.system_utils.gpu_info import collect_gpu_details, GpuDetails
from core.storage import StorageConfig, make_orm_system_metrics_store

from core.server.data_types.config import Config
from ...html_injection import html_response_from_path
from ...app import get_resources, internal_admin_path, on_before_app_created
from ...shared import AppSharedData, SystemSnapshotPayload

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Models (API response schemas)
# ══════════════════════════════════════════════════════════════════════════════

class DiskSnapshot(AdvancedBaseModel):
    used_gb: float
    """磁盘已使用空间 (GB)"""
    total_gb: float
    """磁盘总容量 (GB)"""
    percent: float
    """磁盘使用百分比"""

class NetworkInterfaceSnapshot(AdvancedBaseModel):
    bytes_sent: int = 0
    """网络接口发送字节数"""
    bytes_recv: int = 0
    """网络接口发送字节数"""
    packets_sent: int = 0
    """网络接口接收包数"""
    packets_recv: int = 0
    """网络接口接收包数"""

class DiskIOSnapshot(AdvancedBaseModel):
    read_bytes: int = 0
    """网络接口接收包数"""
    write_bytes: int = 0
    """磁盘写入字节数"""
    read_count: int = 0
    """网络接口接收字节数"""
    write_count: int = 0
    """磁盘写入次数"""

class SystemSnapshot(AdvancedBaseModel):
    timestamp: str
    """快照时间戳, 格式 YYYY-MM-DD HH:MM:SS"""
    cpu_avg: float
    """CPU 平均使用率 (%)"""
    cpu_cores: list[float]
    """各 CPU 核心使用率 (%)"""
    cpu_freq: Optional[float] = None
    """CPU 当前频率 (MHz), 获取失败时为 None"""
    cpu_temp: Optional[float] = None
    """CPU 温度 (°C), 获取失败时为 None"""
    mem_used: int
    """内存已使用 (MB)"""
    mem_total: int
    """内存总量 (MB)"""
    mem_pct: float
    """内存使用百分比"""
    disk_data: dict[str, DiskSnapshot] = Field(default_factory=dict)
    """各磁盘分区使用快照"""
    network_data: dict[str, NetworkInterfaceSnapshot] = Field(default_factory=dict)
    """各磁盘分区 IO 快照"""
    disk_io_data: dict[str, DiskIOSnapshot] = Field(default_factory=dict)
    """各磁盘分区 IO 快照"""
    process_count: int = 0
    """网络接口名称"""


class ExtendedHostInfo(HostInfo):
    server_start_time: str | None = None
    """服务启动时间 ISO-8601 格式"""
    service_uptime_seconds: float | None = None
    """服务运行时长 (秒)"""
    process_count: int | None = None
    """网络接口发送包数"""
    network_interfaces: dict[str, object] = Field(default_factory=dict)
    """网络接口列表"""
    disk_partitions: dict[str, object] = Field(default_factory=dict)
    """网络接口发送字节数"""


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

_system_metrics_store = None
_system_snapshot_thread: threading.Thread | None = None
_system_snapshot_stop = threading.Event()
_system_snapshot_lock = threading.Lock()
_recent_system_snapshots: deque[SystemSnapshot] = deque(maxlen=1800)
_SYSTEM_SNAPSHOT_INTERVAL_SECONDS = 2.0
_system_detail_warmup_thread: threading.Thread | None = None
_system_gpu_cache_thread: threading.Thread | None = None
_system_gpu_cache_stop = threading.Event()
_SYSTEM_CPU_CACHE_TTL_SECONDS = 2.0
_SYSTEM_GPU_CACHE_REFRESH_SECONDS = 20.0
_SYSTEM_GPU_CACHE_TTL_SECONDS = 60
_SYSTEM_EXTENDED_CACHE_TTL_SECONDS = 5.0
_shared_latest_snapshot_cache: SystemSnapshot | None = None
_shared_latest_snapshot_cache_at = 0.0
_local_cpu_details_cache: CpuDetails | None = None
_local_cpu_details_cache_at = 0.0
_local_gpu_details_cache: GpuDetails | None = None
_local_gpu_details_cache_at = 0.0
_local_extended_host_info_cache: ExtendedHostInfo | None = None
_local_extended_host_info_cache_at = 0.0


def _get_system_metrics_store():
    """Get the ORM-backed system metrics store (lazy singleton)."""
    global _system_metrics_store
    if _system_metrics_store is not None:
        return _system_metrics_store
    try:
        _system_metrics_store = make_orm_system_metrics_store(
            StorageConfig.Global().orm.get_system_metrics()
        )
        return _system_metrics_store
    except Exception:
        return None


def _get_shared() -> AppSharedData:
    return AppSharedData.Get()


def _make_cache_key(namespace: str, **payload: object) -> str:
    parts = [f"{key}={payload[key]}" for key in sorted(payload)]
    suffix = ":".join(parts)
    return f"system:{namespace}" if not suffix else f"system:{namespace}:{suffix}"


def _cache_is_fresh(updated_at: float, ttl_seconds: float) -> bool:
    return updated_at > 0 and (time.monotonic() - updated_at) <= max(float(ttl_seconds), 0.0)


def _shared_supports_local_mirror(shared: object) -> bool:
    return getattr(shared, "cache_scope", None) == "cross-process"


def _shared_latest_system_snapshot() -> SystemSnapshot | None:
    global _shared_latest_snapshot_cache, _shared_latest_snapshot_cache_at
    shared = _get_shared()
    use_local_mirror = _shared_supports_local_mirror(shared)
    if use_local_mirror and _cache_is_fresh(_shared_latest_snapshot_cache_at, _SYSTEM_SNAPSHOT_INTERVAL_SECONDS):
        return _shared_latest_snapshot_cache
    getter = getattr(shared, "get_latest_system_snapshot", None)
    if not callable(getter):
        return None
    payload = getter()
    if payload is None:
        return None
    try:
        snapshot = SystemSnapshot.model_validate(payload)
    except Exception:
        return None
    if use_local_mirror:
        _shared_latest_snapshot_cache = snapshot
        _shared_latest_snapshot_cache_at = time.monotonic()
    return snapshot


def _get_local_cpu_details() -> CpuDetails | None:
    if _cache_is_fresh(_local_cpu_details_cache_at, _SYSTEM_CPU_CACHE_TTL_SECONDS):
        return _local_cpu_details_cache
    return None


def _remember_local_cpu_details(details: CpuDetails) -> CpuDetails:
    global _local_cpu_details_cache, _local_cpu_details_cache_at
    _local_cpu_details_cache = details
    _local_cpu_details_cache_at = time.monotonic()
    return details


def _get_local_gpu_details() -> GpuDetails | None:
    if _cache_is_fresh(_local_gpu_details_cache_at, _SYSTEM_GPU_CACHE_TTL_SECONDS):
        return _local_gpu_details_cache
    return None


def _remember_local_gpu_details(details: GpuDetails) -> GpuDetails:
    global _local_gpu_details_cache, _local_gpu_details_cache_at
    _local_gpu_details_cache = details
    _local_gpu_details_cache_at = time.monotonic()
    return details


def _gpu_details_error_fallback(message: str) -> GpuDetails:
    return GpuDetails(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        detected=False,
        message=message,
        devices=[],
    )


def _get_local_extended_host_info() -> ExtendedHostInfo | None:
    if _cache_is_fresh(_local_extended_host_info_cache_at, _SYSTEM_EXTENDED_CACHE_TTL_SECONDS):
        return _local_extended_host_info_cache
    return None


def _remember_local_extended_host_info(details: ExtendedHostInfo) -> ExtendedHostInfo:
    global _local_extended_host_info_cache, _local_extended_host_info_cache_at
    _local_extended_host_info_cache = details
    _local_extended_host_info_cache_at = time.monotonic()
    return details


def _shared_system_history(seconds: int) -> list[SystemSnapshot]:
    shared = _get_shared()
    getter = getattr(shared, "get_system_snapshot_history", None)
    if not callable(getter):
        return []
    try:
        rows = getter(seconds)
    except Exception:
        return []
    out: list[SystemSnapshot] = []
    for row in rows or []:
        try:
            out.append(SystemSnapshot.model_validate(row))
        except Exception:
            continue
    return out


def _build_extended_host_info() -> ExtendedHostInfo:
    data = get_host_info().model_dump(mode="python")
    shared = _get_shared()
    server_start_time = os.getenv("__SERVER_START_TIME__") or getattr(shared, "server_start_time", None)
    service_uptime_seconds = None
    if server_start_time:
        try:
            start_dt = datetime.fromisoformat(server_start_time)
            if start_dt.tzinfo is None:
                now_dt = datetime.now()
            else:
                now_dt = datetime.now(tz=start_dt.tzinfo)
            service_uptime_seconds = max(0.0, (now_dt - start_dt).total_seconds())
        except Exception:
            pass
    latest_snapshot = _latest_cached_system_snapshot()
    process_count = latest_snapshot.process_count if latest_snapshot is not None else None
    if process_count is None:
        try:
            process_count = len(psutil.pids())
        except Exception:
            process_count = 0
    return ExtendedHostInfo(
        **data,
        server_start_time=server_start_time,
        service_uptime_seconds=service_uptime_seconds,
        process_count=process_count,
        network_interfaces=get_network_interfaces(),
        disk_partitions=get_disk_partitions_info(),
    )


def _refresh_extended_host_info_cache() -> ExtendedHostInfo:
    shared = _get_shared()
    details = _build_extended_host_info()
    shared.set_cache(
        _make_cache_key("extended_info"),
        details.model_dump(mode="python"),
        ttl_seconds=_SYSTEM_EXTENDED_CACHE_TTL_SECONDS,
    )
    return _remember_local_extended_host_info(details) if _shared_supports_local_mirror(shared) else details

def _get_live_system_snapshot() -> SystemSnapshot:
    """Fallback: build a snapshot directly from psutil."""
    cpu_cores = psutil.cpu_percent(percpu=True)
    freq = psutil.cpu_freq()
    mem = get_memory_usage(detail=True)
    disks_raw = get_disks_usage()
    network_data = get_network_io(pernic=True)
    disk_io_data = get_disk_io(perdisk=True)
    try:
        process_count = len(psutil.pids())
    except Exception:
        process_count = 0
    cpu_temp = None
    try:
        temps = getattr(psutil, "sensors_temperatures", lambda: None)()
        if temps:
            for key in temps:
                for entry in temps[key]:
                    if hasattr(entry, "current") and entry.current:
                        cpu_temp = float(entry.current)
                        break
                if cpu_temp is not None:
                    break
    except Exception:
        pass
    return SystemSnapshot(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        cpu_avg=round(sum(cpu_cores) / len(cpu_cores), 2) if cpu_cores else 0.0,
        cpu_cores=[round(c, 1) for c in cpu_cores],
        cpu_freq=round(freq.current, 1) if freq else None,
        cpu_temp=cpu_temp,
        mem_used=int(mem.used),
        mem_total=int(mem.total),
        mem_pct=round(mem.percent, 2),
        disk_data={
            mount: DiskSnapshot(used_gb=float(info.used), total_gb=float(info.total), percent=info.percent)
            for mount, info in disks_raw.items()
        },
        network_data={
            nic_id: NetworkInterfaceSnapshot.model_validate(
                metrics.model_dump(mode="python") if hasattr(metrics, "model_dump") else metrics
            )
            for nic_id, metrics in network_data.items()
        },
        disk_io_data={
            disk_id: DiskIOSnapshot.model_validate(
                metrics.model_dump(mode="python") if hasattr(metrics, "model_dump") else metrics
            )
            for disk_id, metrics in disk_io_data.items()
        },
        process_count=process_count,
    )


def _snapshot_time(snapshot: SystemSnapshot) -> datetime:
    try:
        return datetime.strptime(str(snapshot.timestamp), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.min


def _remember_system_snapshot(snapshot: SystemSnapshot) -> None:
    with _system_snapshot_lock:
        if _recent_system_snapshots and _recent_system_snapshots[-1].timestamp == snapshot.timestamp:
            _recent_system_snapshots[-1] = snapshot
        else:
            _recent_system_snapshots.append(snapshot)
    try:
        _get_shared().push_system_snapshot(
            cast(SystemSnapshotPayload, snapshot.model_dump(mode="python")),
            max_items=_recent_system_snapshots.maxlen,
        )
    except Exception:
        pass


def _latest_cached_system_snapshot() -> SystemSnapshot | None:
    shared_snapshot = _shared_latest_system_snapshot()
    if shared_snapshot is not None:
        return shared_snapshot
    with _system_snapshot_lock:
        if not _recent_system_snapshots:
            return None
        return _recent_system_snapshots[-1].model_copy(deep=True)


def _cached_system_history(seconds: int) -> list[SystemSnapshot]:
    shared_rows = _shared_system_history(seconds)
    if shared_rows:
        return shared_rows
    cutoff = datetime.now() - timedelta(seconds=seconds)
    with _system_snapshot_lock:
        return [
            item.model_copy(deep=True)
            for item in _recent_system_snapshots
            if _snapshot_time(item) >= cutoff
        ]


def _system_snapshot_cache_loop() -> None:
    while not _system_snapshot_stop.is_set():
        try:
            snapshot = _get_live_system_snapshot()
            _remember_system_snapshot(snapshot)
            _refresh_cpu_detail_cache(snapshot)
        except Exception:
            pass
        if _system_snapshot_stop.wait(_SYSTEM_SNAPSHOT_INTERVAL_SECONDS):
            break


def _warm_system_detail_caches() -> None:
    try:
        warm_cpu_static_cache()
    except Exception:
        pass

    snapshot = _latest_cached_system_snapshot()
    try:
        _refresh_cpu_detail_cache(snapshot)
    except Exception:
        pass

    try:
        _refresh_gpu_detail_cache()
    except Exception:
        pass

    try:
        _refresh_extended_host_info_cache()
    except Exception:
        pass


def _refresh_cpu_detail_cache(snapshot: SystemSnapshot | None = None) -> None:
    if snapshot is None:
        snapshot = _latest_cached_system_snapshot()
    cpu_details = collect_cpu_details(
        snapshot=snapshot,
        percent_interval=0.0 if snapshot is not None else 0.15,
    )
    _get_shared().set_cache(
        _make_cache_key("cpu_details"),
        cpu_details.model_dump(mode="python"),
        ttl_seconds=_SYSTEM_CPU_CACHE_TTL_SECONDS,
    )


def _refresh_gpu_detail_cache() -> None:
    try:
        gpu_details = collect_gpu_details()
    except Exception as exc:
        logger.warning("GPU detail cache refresh failed: %s", exc)
        return
    _get_shared().set_cache(
        _make_cache_key("gpu_details"),
        gpu_details.model_dump(mode="python"),
        ttl_seconds=_SYSTEM_GPU_CACHE_TTL_SECONDS,
    )


def _system_gpu_cache_loop() -> None:
    while not _system_gpu_cache_stop.is_set():
        _refresh_gpu_detail_cache()
        if _system_gpu_cache_stop.wait(_SYSTEM_GPU_CACHE_REFRESH_SECONDS):
            break


def start_system_snapshot_cache(app: FastAPI | None = None) -> None:
    global _system_snapshot_thread
    if _system_snapshot_thread is not None and _system_snapshot_thread.is_alive():
        return
    _system_snapshot_stop.clear()
    _system_snapshot_thread = threading.Thread(
        target=_system_snapshot_cache_loop,
        name="proj-system-metrics-cache",
        daemon=True,
    )
    _system_snapshot_thread.start()


def start_system_detail_warmup(app: FastAPI | None = None) -> None:
    global _system_detail_warmup_thread
    if _system_detail_warmup_thread is not None and _system_detail_warmup_thread.is_alive():
        return
    _system_detail_warmup_thread = threading.Thread(
        target=_warm_system_detail_caches,
        name="proj-system-detail-warmup",
        daemon=True,
    )
    _system_detail_warmup_thread.start()


def start_system_gpu_cache(app: FastAPI | None = None) -> None:
    global _system_gpu_cache_thread
    if _system_gpu_cache_thread is not None and _system_gpu_cache_thread.is_alive():
        return
    _system_gpu_cache_stop.clear()
    _system_gpu_cache_thread = threading.Thread(
        target=_system_gpu_cache_loop,
        name="proj-system-gpu-cache",
        daemon=True,
    )
    _system_gpu_cache_thread.start()


def stop_system_snapshot_cache(app: FastAPI | None = None) -> None:
    _system_snapshot_stop.set()


def stop_system_gpu_cache(app: FastAPI | None = None) -> None:
    _system_gpu_cache_stop.set()


def _should_start_background_gpu_cache() -> bool:
    """Avoid startup-time GPU polling on Windows; route-level collection stays available."""
    return os.name != "nt"


def start_main_process_system_refresh() -> None:
    start_system_snapshot_cache()
    start_system_detail_warmup()
    if _should_start_background_gpu_cache():
        start_system_gpu_cache()
    else:
        logger.info("Background GPU cache refresh disabled on Windows; /admin/api/system/gpu will refresh on demand.")


def stop_main_process_system_refresh() -> None:
    stop_system_snapshot_cache()
    stop_system_gpu_cache()


# ══════════════════════════════════════════════════════════════════════════════
# Route registration
# ══════════════════════════════════════════════════════════════════════════════

@on_before_app_created
def register_system_monitoring_routes(app: FastAPI):
    admin_path = internal_admin_path


    @app.get(admin_path("api/system"), response_model=SystemSnapshot)
    async def system_snapshot() -> SystemSnapshot:
        """Latest system metrics snapshot."""
        cached = _latest_cached_system_snapshot()
        if cached is not None:
            return cached
        snapshot = await asyncio.to_thread(_get_live_system_snapshot)
        _remember_system_snapshot(snapshot)
        return snapshot

    @app.get(admin_path("api/system/cpu"), response_model=CpuDetails)
    async def system_cpu_details() -> CpuDetails:
        """Detailed CPU metrics for the CPU panel."""
        shared = _get_shared()
        use_local_mirror = _shared_supports_local_mirror(shared)
        if use_local_mirror:
            local_cached = _get_local_cpu_details()
            if local_cached is not None:
                return local_cached
        cache_key = _make_cache_key("cpu_details")
        cached = shared.get_cache(cache_key)
        if cached is not None:
            details = CpuDetails.model_validate(cached)
            return _remember_local_cpu_details(details) if use_local_mirror else details
        snapshot = _latest_cached_system_snapshot()
        details = await asyncio.to_thread(
            collect_cpu_details,
            snapshot=snapshot,
            percent_interval=0.0 if snapshot is not None else 0.15,
        )
        payload = details.model_dump(mode="python")
        shared.set_cache(cache_key, payload, ttl_seconds=_SYSTEM_CPU_CACHE_TTL_SECONDS)
        return _remember_local_cpu_details(details) if use_local_mirror else details

    @app.get(admin_path("api/system/gpu"), response_model=GpuDetails)
    async def system_gpu_details() -> GpuDetails:
        """Cross-vendor GPU summary with graceful fallback when no GPU exists."""
        shared = _get_shared()
        use_local_mirror = _shared_supports_local_mirror(shared)
        local_cached = _get_local_gpu_details() if use_local_mirror else None
        if use_local_mirror:
            if local_cached is not None:
                return local_cached
        cache_key = _make_cache_key("gpu_details")
        cached = shared.get_cache(cache_key)
        if cached is not None:
            try:
                details = GpuDetails.model_validate(cached)
            except Exception as exc:
                logger.warning("Invalid cached GPU details payload ignored: %s", exc)
            else:
                return _remember_local_gpu_details(details) if use_local_mirror else details
        try:
            details = await asyncio.to_thread(collect_gpu_details)
        except Exception as exc:
            logger.error("GPU detail collection failed: %s", exc, exc_info=True)
            if local_cached is not None:
                return local_cached
            return _gpu_details_error_fallback(f"GPU 详情采集失败: {exc}")
        payload = details.model_dump(mode="python")
        shared.set_cache(cache_key, payload, ttl_seconds=_SYSTEM_GPU_CACHE_TTL_SECONDS)
        return _remember_local_gpu_details(details) if use_local_mirror else details

    @app.get(admin_path("api/system_last_infos"), response_model=list[SystemSnapshot])
    async def system_history(seconds: int = Query(default=60, ge=1, le=3600)) -> list[SystemSnapshot]:
        """Return system metric snapshots from the last N seconds."""
        cached_rows = _cached_system_history(seconds)
        if cached_rows or _latest_cached_system_snapshot() is not None:
            return cached_rows
        cfg = Config.GetConfig().log_config
        if "db" in cfg.log_method:
            try:
                store = _get_system_metrics_store()
                if store is not None:
                    rows = await store.query_last_n(seconds=seconds)
                    return [SystemSnapshot.model_validate(r) for r in rows]
            except Exception:
                pass
        return []

    @app.get(admin_path("api/system/extended"), response_model=ExtendedHostInfo)
    async def system_info_extended() -> ExtendedHostInfo:
        """Host info + service uptime."""
        shared = _get_shared()
        use_local_mirror = _shared_supports_local_mirror(shared)
        if use_local_mirror:
            local_cached = _get_local_extended_host_info()
            if local_cached is not None:
                return local_cached
        cache_key = _make_cache_key("extended_info")
        cached = shared.get_cache(cache_key)
        if cached is not None:
            details = ExtendedHostInfo.model_validate(cached)
            return _remember_local_extended_host_info(details) if use_local_mirror else details
        details = await asyncio.to_thread(_build_extended_host_info)
        shared.set_cache(cache_key, details.model_dump(mode="python"), ttl_seconds=_SYSTEM_EXTENDED_CACHE_TTL_SECONDS)
        return _remember_local_extended_host_info(details) if use_local_mirror else details

    # 注册 WebSocket 推送式系统指标端点

    @app.websocket(admin_path("ws/system/metrics"))
    async def system_metrics_ws(websocket: WebSocket):
        """Push system snapshots to the client every 2 seconds."""
        await websocket.accept()
        try:
            while True:
                try:
                    snapshot = _latest_cached_system_snapshot()
                    if snapshot is None:
                        snapshot = await asyncio.to_thread(_get_live_system_snapshot)
                        _remember_system_snapshot(snapshot)
                    await websocket.send_json(snapshot.model_dump(mode="json"))
                except WebSocketDisconnect:
                    break
                except Exception:
                    pass
                await asyncio.sleep(_SYSTEM_SNAPSHOT_INTERVAL_SECONDS)
        except WebSocketDisconnect:
            pass

    # 注册 panel system 子页面 (HTML) 路由

    panel_system_path = get_resources("admin-panel", "panel", "system_overview.html") or Path("system_overview.html")
    panel_system_cpu_path = get_resources("admin-panel", "panel", "system_cpu.html") or Path("system_cpu.html")
    panel_system_gpu_path = get_resources("admin-panel", "panel", "system_gpu.html") or Path("system_gpu.html")

    @app.get(admin_path("panel/system"), response_class=HTMLResponse)
    @app.get(admin_path("panel/system/overview"), response_class=HTMLResponse)
    async def panel_system_html():
        """Standalone system overview page used by the panel iframe shell."""
        return html_response_from_path(panel_system_path, not_found_message="system_overview.html not found")

    @app.get(admin_path("panel/system/cpu"), response_class=HTMLResponse)
    async def panel_system_cpu_html():
        """Standalone detailed CPU page used by the panel iframe shell."""
        return html_response_from_path(panel_system_cpu_path, not_found_message="system_cpu.html not found")

    @app.get(admin_path("panel/system/gpu"), response_class=HTMLResponse)
    async def panel_system_gpu_html():
        """Standalone GPU page used by the panel iframe shell."""
        return html_response_from_path(panel_system_gpu_path, not_found_message="system_gpu.html not found")
