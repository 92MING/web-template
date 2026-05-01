# -*- coding: utf-8 -*-
"""CPU information collection — models and data gathering functions."""

import os
import platform
import re
from functools import lru_cache

import psutil

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class _AutoDocModel(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)


# ══════════════════════════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════════════════════════

class KeyValueItem(_AutoDocModel):
    key: str
    """显示名称"""
    value: str
    """显示值"""


class CpuCoreSnapshot(_AutoDocModel):
    index: int
    """核心索引"""
    percent: float
    """核心利用率 (%)"""
    freq_mhz: Optional[float] = None
    """核心频率 (MHz)"""


class CpuSummary(_AutoDocModel):
    overall_percent: float
    """整体 CPU 利用率 (%)"""
    logical_count: int
    """逻辑核心数"""
    physical_count: Optional[int] = None
    """物理核心数"""
    current_freq_mhz: Optional[float] = None
    """当前频率 (MHz)"""
    min_freq_mhz: Optional[float] = None
    """最低频率 (MHz)"""
    max_freq_mhz: Optional[float] = None
    """最高频率 (MHz)"""
    load_avg_1m: Optional[float] = None
    """1 分钟负载"""
    load_avg_5m: Optional[float] = None
    """5 分钟负载"""
    load_avg_15m: Optional[float] = None
    """15 分钟负载"""
    ctx_switches: int = 0
    """上下文切换次数"""
    interrupts: int = 0
    """中断次数"""
    soft_interrupts: Optional[int] = None
    """软中断次数"""
    syscalls: Optional[int] = None
    """系统调用次数"""
    process_count: int = 0
    """当前进程数"""


class CpuDetails(_AutoDocModel):
    timestamp: str
    """采集时间戳"""
    summary: CpuSummary
    """CPU 汇总指标"""
    per_core: list[CpuCoreSnapshot] = Field(default_factory=list)
    """每核利用率 / 频率"""
    times_percent: dict[str, float] = Field(default_factory=dict)
    """cpu_times_percent 的可用字段"""
    details: list[KeyValueItem] = Field(default_factory=list)
    """类似 lscpu 的详情列表"""


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "N/A", "[N/A]", "Not Supported", "[Not Supported]"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    if value in (None, "", "N/A", "[N/A]", "Not Supported", "[Not Supported]"):
        return None
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _fmt_frequency(value: Any) -> str:
    num = _safe_float(value)
    if num is None:
        return "—"
    if num >= 1000:
        return f"{num / 1000:.2f} GHz"
    return f"{num:.1f} MHz"


def _append_detail(details: list[KeyValueItem], key: str, value: Any):
    text = str(value or "").strip()
    if not text:
        return
    details.append(KeyValueItem(key=key, value=text))


@lru_cache(maxsize=1)
def _collect_cpu_info_map() -> dict[str, Any]:
    try:
        import cpuinfo  # type: ignore
        data = cpuinfo.get_cpu_info() or {}
        return dict(data)
    except Exception:
        return {}


def warm_cpu_static_cache() -> None:
    """Warm the cached static CPU metadata so the first detail request is cheap."""
    _collect_cpu_info_map()


def _snapshot_value(snapshot: Any, key: str) -> Any:
    if snapshot is None:
        return None
    if isinstance(snapshot, dict):
        return snapshot.get(key)
    return getattr(snapshot, key, None)


def _snapshot_cpu_percents(snapshot: Any) -> list[float] | None:
    raw = _snapshot_value(snapshot, "cpu_cores")
    if not isinstance(raw, (list, tuple)):
        return None
    values: list[float] = []
    for item in raw:
        num = _safe_float(item)
        if num is None:
            return None
        values.append(round(float(num), 2))
    return values


# ══════════════════════════════════════════════════════════════════════════════
# Main collection function
# ══════════════════════════════════════════════════════════════════════════════

def collect_cpu_details(*, snapshot: Any = None, percent_interval: float = 0.0) -> CpuDetails:
    """Collect detailed CPU information from psutil and cpuinfo.

    When a fresh system snapshot is available, reuse its CPU percentages and
    process count to avoid extra blocking psutil sampling on the request path.
    """
    cpu_percents = _snapshot_cpu_percents(snapshot)
    if cpu_percents is None:
        cpu_percents = [round(float(v), 2) for v in psutil.cpu_percent(interval=percent_interval, percpu=True)]

    snapshot_cpu_avg = _safe_float(_snapshot_value(snapshot, "cpu_avg"))
    overall = round(float(snapshot_cpu_avg), 2) if snapshot_cpu_avg is not None else (
        round(sum(cpu_percents) / len(cpu_percents), 2) if cpu_percents else 0.0
    )

    try:
        cpu_freq = psutil.cpu_freq()
    except Exception:
        cpu_freq = None
    try:
        cpu_freqs = psutil.cpu_freq(percpu=True)
    except Exception:
        cpu_freqs = []
    try:
        cpu_stats = psutil.cpu_stats()
    except Exception:
        cpu_stats = None
    try:
        cpu_times_percent = psutil.cpu_times_percent(interval=0.0)
        times_percent = {
            key: round(float(value), 2)
            for key, value in cpu_times_percent._asdict().items()
            if isinstance(value, (int, float))
        }
    except Exception:
        times_percent = {}
    load_avg_1m = load_avg_5m = load_avg_15m = None
    try:
        if hasattr(os, "getloadavg"):
            load_avg_1m, load_avg_5m, load_avg_15m = [round(float(v), 2) for v in os.getloadavg()]
    except Exception:
        pass

    snapshot_process_count = _safe_int(_snapshot_value(snapshot, "process_count"))
    if snapshot_process_count is not None:
        process_count = snapshot_process_count
    else:
        try:
            process_count = len(psutil.pids())
        except Exception:
            process_count = 0

    info = _collect_cpu_info_map()
    details: list[KeyValueItem] = []
    model_name = info.get("brand_raw") or info.get("brand") or platform.processor() or platform.uname().processor or "Unknown CPU"
    _append_detail(details, "Model name", model_name)
    _append_detail(details, "Vendor ID", info.get("vendor_id_raw") or info.get("vendor_id") or info.get("vendor") or platform.processor())
    _append_detail(details, "Architecture", info.get("arch_string_raw") or info.get("arch") or platform.machine())
    _append_detail(details, "Bits", info.get("bits"))
    _append_detail(details, "Logical CPU(s)", psutil.cpu_count(logical=True) or 0)
    _append_detail(details, "Core(s) per socket", psutil.cpu_count(logical=False))
    _append_detail(details, "Current frequency", _fmt_frequency(getattr(cpu_freq, "current", None)))
    _append_detail(details, "Min frequency", _fmt_frequency(getattr(cpu_freq, "min", None)))
    _append_detail(details, "Max frequency", _fmt_frequency(getattr(cpu_freq, "max", None)))
    _append_detail(details, "Advertised frequency", info.get("hz_advertised_friendly") or info.get("hz_actual_friendly"))
    _append_detail(details, "L2 cache", info.get("l2_cache_size"))
    _append_detail(details, "L3 cache", info.get("l3_cache_size"))
    flags = info.get("flags") or []
    if isinstance(flags, (list, tuple)) and flags:
        _append_detail(details, "Flags", ", ".join(str(flag) for flag in list(flags)[:24]))
    _append_detail(details, "Platform", f"{platform.system()} {platform.release()}")

    per_core: list[CpuCoreSnapshot] = []
    for idx, percent in enumerate(cpu_percents):
        freq_value = None
        if isinstance(cpu_freqs, list) and idx < len(cpu_freqs):
            freq_value = getattr(cpu_freqs[idx], "current", None)
        elif cpu_freq is not None:
            freq_value = getattr(cpu_freq, "current", None)
        per_core.append(
            CpuCoreSnapshot(
                index=idx,
                percent=percent,
                freq_mhz=round(float(freq_value), 1) if _safe_float(freq_value) is not None else None,  # type: ignore
            )
        )

    timestamp = str(_snapshot_value(snapshot, "timestamp") or "").strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return CpuDetails(
        timestamp=timestamp,
        summary=CpuSummary(
            overall_percent=overall,
            logical_count=psutil.cpu_count(logical=True) or 0,
            physical_count=psutil.cpu_count(logical=False),
            current_freq_mhz=round(float(getattr(cpu_freq, "current", 0.0)), 1) if cpu_freq and getattr(cpu_freq, "current", None) is not None else None,
            min_freq_mhz=round(float(getattr(cpu_freq, "min", 0.0)), 1) if cpu_freq and getattr(cpu_freq, "min", None) is not None else None,
            max_freq_mhz=round(float(getattr(cpu_freq, "max", 0.0)), 1) if cpu_freq and getattr(cpu_freq, "max", None) is not None else None,
            load_avg_1m=load_avg_1m,
            load_avg_5m=load_avg_5m,
            load_avg_15m=load_avg_15m,
            ctx_switches=int(getattr(cpu_stats, "ctx_switches", 0) or 0),
            interrupts=int(getattr(cpu_stats, "interrupts", 0) or 0),
            soft_interrupts=_safe_int(getattr(cpu_stats, "soft_interrupts", None)),
            syscalls=_safe_int(getattr(cpu_stats, "syscalls", None)),
            process_count=process_count,
        ),
        per_core=per_core,
        times_percent=times_percent,
        details=details,
    )


__all__ = [
    'KeyValueItem',
    'CpuCoreSnapshot',
    'CpuSummary',
    'CpuDetails',
    'collect_cpu_details',
    'warm_cpu_static_cache',
]
