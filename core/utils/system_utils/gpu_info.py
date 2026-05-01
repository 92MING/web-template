# -*- coding: utf-8 -*-
"""GPU information collection — models, multi-backend collectors, and merge logic."""

import os
import platform
import re
import shutil
import subprocess
import threading

from contextlib import contextmanager
from concurrent.futures import as_completed
from dataclasses import dataclass, field as dc_field
from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from .cpu_info import KeyValueItem, _safe_float, _safe_int, _append_detail


class _AutoDocModel(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)


# ══════════════════════════════════════════════════════════════════════════════
# Intermediate dataclass for raw GPU records (replaces dict[str, Any])
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _RawGpuRecord:
    """Structured intermediate representation returned by each collector."""
    index: int = 0
    name: str = ""
    vendor: str | None = None
    backend_sources: list[str] = dc_field(default_factory=list)
    driver_version: str | None = None
    bus_id: str | None = None
    utilization_percent: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    memory_free_bytes: int | None = None
    temperature_c: float | None = None
    fan_percent: float | None = None
    power_watts: float | None = None
    core_clock_mhz: float | None = None
    memory_clock_mhz: float | None = None
    details: list[KeyValueItem] = dc_field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Public models (API response schemas)
# ══════════════════════════════════════════════════════════════════════════════

class GpuDeviceInfo(_AutoDocModel):
    index: int
    """设备索引"""
    name: str
    """设备名称"""
    vendor: Optional[str] = None
    """厂商"""
    backend_sources: list[str] = Field(default_factory=list)
    """数据来源后端"""
    driver_version: Optional[str] = None
    """驱动版本"""
    bus_id: Optional[str] = None
    """总线 ID"""
    utilization_percent: Optional[float] = None
    """GPU 利用率 (%)"""
    memory_total_bytes: Optional[int] = None
    """显存总量 (bytes)"""
    memory_used_bytes: Optional[int] = None
    """已用显存 (bytes)"""
    memory_free_bytes: Optional[int] = None
    """空闲显存 (bytes)"""
    temperature_c: Optional[float] = None
    """温度 (℃)"""
    fan_percent: Optional[float] = None
    """风扇转速 (%)"""
    power_watts: Optional[float] = None
    """功耗 (W)"""
    core_clock_mhz: Optional[float] = None
    """核心频率 (MHz)"""
    memory_clock_mhz: Optional[float] = None
    """显存频率 (MHz)"""
    details: list[KeyValueItem] = Field(default_factory=list)
    """设备详情列表"""


class GpuSummary(_AutoDocModel):
    gpu_count: int = 0
    """GPU 数量"""
    vendors: list[str] = Field(default_factory=list)
    """厂商列表"""
    backend_sources: list[str] = Field(default_factory=list)
    """已命中的采集后端"""
    total_memory_bytes: int = 0
    """总显存 (bytes)"""
    used_memory_bytes: int = 0
    """已用显存 (bytes)"""
    avg_utilization_percent: Optional[float] = None
    """平均利用率 (%)"""


class GpuDetails(_AutoDocModel):
    timestamp: str
    """采集时间戳"""
    detected: bool
    """是否检测到 GPU"""
    message: str
    """提示消息"""
    summary: GpuSummary = Field(default_factory=GpuSummary)
    """GPU 汇总"""
    devices: list[GpuDeviceInfo] = Field(default_factory=list)
    """GPU 列表"""


# ══════════════════════════════════════════════════════════════════════════════
# Backend availability cache
# ══════════════════════════════════════════════════════════════════════════════

_unavailable_backends: set[str] = set()
_unavailable_lock = threading.Lock()
_native_stderr_lock = threading.RLock()


def _mark_unavailable(backend: str):
    with _unavailable_lock:
        _unavailable_backends.add(backend)


def _is_available(backend: str) -> bool:
    with _unavailable_lock:
        return backend not in _unavailable_backends


def reset_gpu_backend_cache():
    """Reset the backend availability cache (e.g. after hardware change)."""
    with _unavailable_lock:
        _unavailable_backends.clear()


@contextmanager
def _suppress_native_stderr():
    """Temporarily redirect process stderr to devnull for noisy native libraries."""
    devnull_fd: int | None = None
    saved_fd: int | None = None
    with _native_stderr_lock:
        try:
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
            saved_fd = os.dup(2)
            os.dup2(devnull_fd, 2)
        except OSError:
            pass
        try:
            yield
        finally:
            if saved_fd is not None:
                try:
                    os.dup2(saved_fd, 2)
                except OSError:
                    pass
                try:
                    os.close(saved_fd)
                except OSError:
                    pass
            if devnull_fd is not None:
                try:
                    os.close(devnull_fd)
                except OSError:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _norm_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _kv(key: str, value: str) -> KeyValueItem:
    return KeyValueItem(key=key, value=value)


# ══════════════════════════════════════════════════════════════════════════════
# Collectors — each returns a list[_RawGpuRecord]
# ══════════════════════════════════════════════════════════════════════════════

def _collect_gpu_from_nvml() -> list[_RawGpuRecord]:
    if not _is_available("nvml"):
        return []
    records: list[_RawGpuRecord] = []
    try:
        with _suppress_native_stderr():
            from pynvml import (  # type: ignore
                NVML_CLOCK_GRAPHICS,
                NVML_CLOCK_MEM,
                NVML_TEMPERATURE_GPU,
                NVMLError,
                nvmlDeviceGetClockInfo,
                nvmlDeviceGetCount,
                nvmlDeviceGetFanSpeed,
                nvmlDeviceGetHandleByIndex,
                nvmlDeviceGetMemoryInfo,
                nvmlDeviceGetName,
                nvmlDeviceGetPciInfo,
                nvmlDeviceGetPowerUsage,
                nvmlDeviceGetTemperature,
                nvmlDeviceGetUtilizationRates,
                nvmlInit,
                nvmlShutdown,
                nvmlSystemGetDriverVersion,
            )

            nvmlInit()
            driver_version = nvmlSystemGetDriverVersion()
            if isinstance(driver_version, bytes):
                driver_version = driver_version.decode("utf-8", errors="replace")
            for index in range(int(nvmlDeviceGetCount())):
                handle = nvmlDeviceGetHandleByIndex(index)
                name = nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                mem = nvmlDeviceGetMemoryInfo(handle)
                pci = nvmlDeviceGetPciInfo(handle)
                bus_id = getattr(pci, "busId", None)
                if isinstance(bus_id, bytes):
                    bus_id = bus_id.decode("utf-8", errors="replace")
                utilization = None
                temperature = None
                fan = None
                power = None
                core_clock = None
                mem_clock = None
                try:
                    utilization = float(getattr(nvmlDeviceGetUtilizationRates(handle), "gpu", 0.0))
                except NVMLError:
                    pass
                try:
                    temperature = float(nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU))
                except NVMLError:
                    pass
                try:
                    fan = float(nvmlDeviceGetFanSpeed(handle))
                except NVMLError:
                    pass
                try:
                    power = round(float(nvmlDeviceGetPowerUsage(handle)) / 1000.0, 2)
                except NVMLError:
                    pass
                try:
                    core_clock = float(nvmlDeviceGetClockInfo(handle, NVML_CLOCK_GRAPHICS))
                except NVMLError:
                    pass
                try:
                    mem_clock = float(nvmlDeviceGetClockInfo(handle, NVML_CLOCK_MEM))
                except NVMLError:
                    pass
                records.append(_RawGpuRecord(
                    index=index,
                    name=str(name),
                    vendor="NVIDIA",
                    backend_sources=["nvml"],
                    driver_version=str(driver_version or "") or None,
                    bus_id=str(bus_id or "") or None,
                    utilization_percent=round(utilization, 2) if utilization is not None else None,
                    memory_total_bytes=int(getattr(mem, "total", 0) or 0) or None,
                    memory_used_bytes=int(getattr(mem, "used", 0) or 0) or None,
                    memory_free_bytes=int(getattr(mem, "free", 0) or 0) or None,
                    temperature_c=temperature,
                    fan_percent=fan,
                    power_watts=power,
                    core_clock_mhz=core_clock,
                    memory_clock_mhz=mem_clock,
                    details=[
                        _kv("Collector", "NVML"),
                        _kv("Driver version", str(driver_version or "—")),
                    ],
                ))
    except Exception:
        _mark_unavailable("nvml")
        return []
    finally:
        try:
            nvmlShutdown()
        except Exception:
            pass
    if not records:
        _mark_unavailable("nvml")
    return records


def _collect_gpu_from_nvidia_smi() -> list[_RawGpuRecord]:
    if not _is_available("nvidia-smi"):
        return []
    if shutil.which("nvidia-smi") is None:
        _mark_unavailable("nvidia-smi")
        return []
    fields = [
        "index",
        "name",
        "memory.total",
        "memory.used",
        "temperature.gpu",
        "utilization.gpu",
        "clocks.current.graphics",
        "clocks.current.memory",
        "power.draw",
        "fan.speed",
        "driver_version",
        "pci.bus_id",
    ]
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={','.join(fields)}",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        _mark_unavailable("nvidia-smi")
        return []
    if result.returncode != 0 or not result.stdout.strip():
        _mark_unavailable("nvidia-smi")
        return []
    records: list[_RawGpuRecord] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != len(fields):
            continue
        idx = _safe_int(parts[0])
        total_mib = _safe_float(parts[2])
        used_mib = _safe_float(parts[3])
        total_bytes = int(total_mib * 1024 * 1024) if total_mib is not None else None
        used_bytes = int(used_mib * 1024 * 1024) if used_mib is not None else None
        free_bytes = (total_bytes - used_bytes) if total_bytes is not None and used_bytes is not None else None
        records.append(_RawGpuRecord(
            index=idx if idx is not None else len(records),
            name=parts[1] or "NVIDIA GPU",
            vendor="NVIDIA",
            backend_sources=["nvidia-smi"],
            driver_version=parts[10] or None,
            bus_id=parts[11] or None,
            utilization_percent=_safe_float(parts[5]),
            memory_total_bytes=total_bytes,
            memory_used_bytes=used_bytes,
            memory_free_bytes=free_bytes,
            temperature_c=_safe_float(parts[4]),
            fan_percent=_safe_float(parts[9]),
            power_watts=_safe_float(parts[8]),
            core_clock_mhz=_safe_float(parts[6]),
            memory_clock_mhz=_safe_float(parts[7]),
            details=[_kv("Collector", "nvidia-smi")],
        ))
    if not records:
        _mark_unavailable("nvidia-smi")
    return records


def _collect_gpu_from_opencl() -> list[_RawGpuRecord]:
    if not _is_available("opencl"):
        return []
    records: list[_RawGpuRecord] = []
    try:
        with _suppress_native_stderr():
            import pyopencl as cl  # type: ignore

            for platform_obj in cl.get_platforms():
                for device in platform_obj.get_devices():
                    device_type = getattr(device, "type", 0)
                    if not int(device_type) & int(cl.device_type.GPU):
                        continue
                    details = [
                        _kv("Collector", "OpenCL"),
                        _kv("Platform", str(getattr(platform_obj, "name", "") or "—")),
                        _kv("OpenCL version", str(getattr(device, "version", "") or "—")),
                        _kv("Driver version", str(getattr(device, "driver_version", "") or "—")),
                        _kv("Compute units", str(getattr(device, "max_compute_units", "") or "—")),
                    ]
                    records.append(_RawGpuRecord(
                        index=len(records),
                        name=str(getattr(device, "name", None) or "OpenCL GPU"),
                        vendor=str(getattr(device, "vendor", None) or getattr(platform_obj, "vendor", None) or "Unknown"),
                        backend_sources=["opencl"],
                        driver_version=str(getattr(device, "driver_version", None) or "") or None,
                        memory_total_bytes=_safe_int(getattr(device, "global_mem_size", None)),
                        core_clock_mhz=_safe_float(getattr(device, "max_clock_frequency", None)),
                        details=details,
                    ))
    except Exception:
        _mark_unavailable("opencl")
        return []
    if not records:
        _mark_unavailable("opencl")
    return records


def _collect_gpu_from_windows_wmi() -> list[_RawGpuRecord]:
    if not _is_available("win32-wmi"):
        return []
    if platform.system() != "Windows":
        _mark_unavailable("win32-wmi")
        return []
    try:
        import win32com.client  # type: ignore
    except Exception:
        _mark_unavailable("win32-wmi")
        return []

    records: list[_RawGpuRecord] = []
    try:
        service = win32com.client.GetObject("winmgmts:root\\CIMV2")
        for index, item in enumerate(service.ExecQuery("SELECT * FROM Win32_VideoController")):
            name = str(getattr(item, "Name", None) or getattr(item, "Caption", None) or "").strip()
            if not name:
                continue
            vendor = str(getattr(item, "AdapterCompatibility", None) or "").strip() or None
            adapter_ram = _safe_int(getattr(item, "AdapterRAM", None))
            resolution = None
            width = _safe_int(getattr(item, "CurrentHorizontalResolution", None))
            height = _safe_int(getattr(item, "CurrentVerticalResolution", None))
            if width and height:
                resolution = f"{width} × {height}"
            details: list[KeyValueItem] = [_kv("Collector", "Win32_VideoController")]
            if resolution:
                details.append(_kv("Current resolution", resolution))
            refresh_rate = _safe_int(getattr(item, "CurrentRefreshRate", None))
            if refresh_rate:
                details.append(_kv("Refresh rate", f"{refresh_rate} Hz"))
            video_processor = str(getattr(item, "VideoProcessor", None) or "").strip()
            if video_processor:
                details.append(_kv("Video processor", video_processor))
            status = str(getattr(item, "Status", None) or "").strip()
            if status:
                details.append(_kv("Status", status))
            records.append(_RawGpuRecord(
                index=index,
                name=name,
                vendor=vendor,
                backend_sources=["win32-video-controller"],
                driver_version=str(getattr(item, "DriverVersion", None) or "") or None,
                bus_id=str(getattr(item, "PNPDeviceID", None) or "") or None,
                memory_total_bytes=adapter_ram,
                details=details,
            ))
    except Exception:
        _mark_unavailable("win32-wmi")
        return []
    if not records:
        _mark_unavailable("win32-wmi")
    return records


def _collect_gpu_from_lspci() -> list[_RawGpuRecord]:
    if not _is_available("lspci"):
        return []
    if shutil.which("lspci") is None:
        _mark_unavailable("lspci")
        return []
    try:
        result = subprocess.run(["lspci"], check=False, capture_output=True, text=True, timeout=2)
    except Exception:
        _mark_unavailable("lspci")
        return []
    if result.returncode != 0 or not result.stdout.strip():
        _mark_unavailable("lspci")
        return []
    records: list[_RawGpuRecord] = []
    for line in result.stdout.splitlines():
        lower = line.lower()
        if "vga compatible controller" not in lower and "3d controller" not in lower and "display controller" not in lower:
            continue
        bus_id, _, desc = line.partition(" ")
        desc = desc.split(":", 1)[-1].strip() if ":" in desc else desc.strip()
        vendor = None
        for candidate in ("nvidia", "amd", "advanced micro devices", "intel"):
            if candidate in lower:
                vendor = candidate.replace("advanced micro devices", "AMD").upper() if candidate != "intel" else "Intel"
                break
        records.append(_RawGpuRecord(
            index=len(records),
            name=desc or "GPU",
            vendor=vendor,
            backend_sources=["lspci"],
            bus_id=bus_id,
            details=[_kv("Collector", "lspci")],
        ))
    if not records:
        _mark_unavailable("lspci")
    return records


# ══════════════════════════════════════════════════════════════════════════════
# Merge logic
# ══════════════════════════════════════════════════════════════════════════════

def _vendors_compatible(a: str, b: str) -> bool:
    """Check if two normalised vendor strings refer to the same vendor."""
    if not a or not b:
        return True
    if a == b or a in b or b in a:
        return True
    # Keyword-level match: "nvidia" in "nvidiacorporation" etc.
    _VENDOR_KEYS = ("nvidia", "intel", "amd", "advancedmicrodevices")
    for key in _VENDOR_KEYS:
        if key in a and key in b:
            return True
    return False


def _find_matching_record(targets: list[_RawGpuRecord], record: _RawGpuRecord) -> _RawGpuRecord | None:
    record_bus = _norm_text(record.bus_id)
    record_name = _norm_text(record.name)
    record_vendor = _norm_text(record.vendor)
    for item in targets:
        if record_bus and record_bus == _norm_text(item.bus_id):
            return item
    for item in targets:
        item_name = _norm_text(item.name)
        item_vendor = _norm_text(item.vendor)
        if record_name and item_name and (record_name == item_name or record_name in item_name or item_name in record_name):
            if _vendors_compatible(record_vendor, item_vendor):
                return item
    return None


def _merge_into(target: _RawGpuRecord, source: _RawGpuRecord):
    for src in source.backend_sources:
        if src not in target.backend_sources:
            target.backend_sources.append(src)
    existing = {(d.key, d.value) for d in target.details}
    for d in source.details:
        if (d.key, d.value) not in existing:
            target.details.append(d)
            existing.add((d.key, d.value))
    # Fill in None fields from source
    for attr in (
        "name", "vendor", "driver_version", "bus_id",
        "utilization_percent", "memory_total_bytes", "memory_used_bytes",
        "memory_free_bytes", "temperature_c", "fan_percent", "power_watts",
        "core_clock_mhz", "memory_clock_mhz",
    ):
        if getattr(target, attr) in (None, "", 0) and getattr(source, attr) not in (None, "", 0):
            setattr(target, attr, getattr(source, attr))


_LOW_CONFIDENCE_GPU_BACKENDS = {"win32-video-controller", "lspci"}
_KNOWN_GPU_VENDOR_KEYS = ("nvidia", "intel", "amd", "advancedmicrodevices")
_GENERIC_GPU_NAME_KEYS = (
    "microsoft",
    "basicrender",
    "remote",
    "virtual",
    "displaylink",
    "indirect",
    "luminon",
)


def _has_high_confidence_gpu_data(record: _RawGpuRecord) -> bool:
    return any(source not in _LOW_CONFIDENCE_GPU_BACKENDS for source in record.backend_sources)


def _looks_like_physical_fallback_gpu(record: _RawGpuRecord) -> bool:
    vendor = _norm_text(record.vendor)
    name = _norm_text(record.name)
    if any(key in vendor or key in name for key in _KNOWN_GPU_VENDOR_KEYS):
        return True
    if any(key in name for key in _GENERIC_GPU_NAME_KEYS):
        return False
    return bool(record.memory_total_bytes)


# ══════════════════════════════════════════════════════════════════════════════
# Main collection function
# ══════════════════════════════════════════════════════════════════════════════

_COLLECTOR_NAMES: list[str] = [
    '_collect_gpu_from_nvml',
    '_collect_gpu_from_nvidia_smi',
    '_collect_gpu_from_opencl',
    '_collect_gpu_from_windows_wmi',
    '_collect_gpu_from_lspci',
]


def collect_gpu_details() -> GpuDetails:
    """Collect GPU information from all available backends in parallel, merge duplicates."""
    from core.utils.concurrent_utils import get_threadpool
    import core.utils.system_utils.gpu_info as _self_module

    collectors = [getattr(_self_module, name) for name in _COLLECTOR_NAMES]
    pool = get_threadpool()
    futures = {pool.submit(collector): collector for collector in collectors}

    merged: list[_RawGpuRecord] = []
    for future in as_completed(futures):
        try:
            records = future.result(timeout=10)
        except Exception:
            continue
        for record in records or []:
            target = _find_matching_record(merged, record)
            if target is None:
                merged.append(record)
            else:
                _merge_into(target, record)

    if any(_has_high_confidence_gpu_data(item) for item in merged):
        merged = [
            item for item in merged
            if _has_high_confidence_gpu_data(item) or _looks_like_physical_fallback_gpu(item)
        ]

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    devices: list[GpuDeviceInfo] = []
    for index, item in enumerate(merged):
        details = list(item.details)
        _append_detail(details, "Vendor", item.vendor)
        _append_detail(details, "Bus ID", item.bus_id)
        _append_detail(details, "Driver version", item.driver_version)
        device = GpuDeviceInfo(
            index=item.index if item.index is not None else index,
            name=item.name or f"GPU {index}",
            vendor=item.vendor or None,
            backend_sources=list(dict.fromkeys(item.backend_sources)),
            driver_version=item.driver_version or None,
            bus_id=item.bus_id or None,
            utilization_percent=_safe_float(item.utilization_percent),
            memory_total_bytes=_safe_int(item.memory_total_bytes),
            memory_used_bytes=_safe_int(item.memory_used_bytes),
            memory_free_bytes=_safe_int(item.memory_free_bytes),
            temperature_c=_safe_float(item.temperature_c),
            fan_percent=_safe_float(item.fan_percent),
            power_watts=_safe_float(item.power_watts),
            core_clock_mhz=_safe_float(item.core_clock_mhz),
            memory_clock_mhz=_safe_float(item.memory_clock_mhz),
            details=details,
        )
        devices.append(device)

    devices.sort(key=lambda d: d.index)
    if not devices:
        return GpuDetails(
            timestamp=timestamp,
            detected=False,
            message="无检测到GPU",
            summary=GpuSummary(gpu_count=0, vendors=[], backend_sources=[]),
            devices=[],
        )

    vendors = sorted({device.vendor for device in devices if device.vendor})
    backend_sources = sorted({source for device in devices for source in device.backend_sources})
    total_memory_bytes = sum(int(device.memory_total_bytes or 0) for device in devices)
    used_memory_bytes = sum(int(device.memory_used_bytes or 0) for device in devices)
    available_utils = [float(device.utilization_percent) for device in devices if device.utilization_percent is not None]
    return GpuDetails(
        timestamp=timestamp,
        detected=True,
        message=f"已检测到 {len(devices)} 个 GPU",
        summary=GpuSummary(
            gpu_count=len(devices),
            vendors=vendors,
            backend_sources=backend_sources,
            total_memory_bytes=total_memory_bytes,
            used_memory_bytes=used_memory_bytes,
            avg_utilization_percent=round(sum(available_utils) / len(available_utils), 2) if available_utils else None,
        ),
        devices=devices,
    )


__all__ = [
    'GpuDeviceInfo',
    'GpuSummary',
    'GpuDetails',
    'collect_gpu_details',
    'reset_gpu_backend_cache',
]
