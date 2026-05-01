# -*- coding: utf-8 -*-
"""
Protocol-backed system metrics store and background worker.

The data is now stored via an :class:`SystemMetricsStoreProtocol`-compatible
backend (defaulting to :class:`ORMSystemMetricsStore`) instead of being
written directly to a bare SQLite connection.

The public API is unchanged in terms of *shape* -- only the connection/store
parameter type has changed from ``sqlite3.Connection`` to
``SystemMetricsStoreProtocol``.
"""


import time
import logging
import threading
import typing as t

from datetime import datetime, timedelta
from typing import Any, Optional, Protocol, runtime_checkable

from .helper_funcs import get_memory_usage, get_disks_usage, get_network_io, get_disk_io

try:
    import psutil as _psutil
except ImportError:
    _psutil = None  # type: ignore[assignment]


# -- SystemMetricsStoreProtocol -----------------------------------------------

@runtime_checkable
class SystemMetricsStoreProtocol(Protocol):
    """抽象系统指标存储协议。

    写入方法为同步（fire-and-forget 可接受），查询方法为异步。
    """

    def write(self, record: Any) -> None:
        """写入一条系统指标快照（同步，实现中可 fire-and-forget）。"""
        ...

    async def query_latest(self) -> Optional[dict[str, Any]]:
        """返回最新一条快照，表为空时返回 ``None``。"""
        ...

    async def query_last_n(self, seconds: int = 60) -> list[dict[str, Any]]:
        """返回最近 *seconds* 秒内所有快照（按时间升序）。"""
        ...


# -- Worker -------------------------------------------------------------------

def start_system_metrics_worker(
    store: "SystemMetricsStoreProtocol | Any",
    root_logger: logging.Logger,
    interval: int = 5,
) -> None:
    """启动后台守护线程，周期性采集系统指标并写入 *store*。

    Args:
        store:        实现 :class:`SystemMetricsStoreProtocol` 的存储后端。
        root_logger:  用于输出告警 / 调试消息的 Logger 实例。
        interval:     采集间隔（秒），默认 5。
    """
    if _psutil is None:
        root_logger.warning("System metrics: psutil not installed, metrics worker will not start.")
        return

    try:
        from core.storage.orm import SystemMetricRecord
    except Exception as exc:
        root_logger.warning(f"System metrics: cannot import SystemMetricRecord: {exc}")
        return

    def _worker() -> None:
        # prime psutil so the very first measurement is non-zero
        _psutil.cpu_percent(percpu=True)

        while True:
            time.sleep(interval)
            try:
                cpu_cores = _psutil.cpu_percent(percpu=True)
                cpu_avg = round(sum(cpu_cores) / len(cpu_cores), 2) if cpu_cores else 0.0
                freq_info = _psutil.cpu_freq()
                cpu_freq = round(freq_info.current, 1) if freq_info else None

                mem = get_memory_usage(detail=True)
                disks_raw = get_disks_usage()
                network_data = get_network_io(pernic=True)
                disk_io_data = get_disk_io(perdisk=True)
                try:
                    process_count = len(_psutil.pids())
                except Exception:
                    process_count = 0

                cpu_temp: float | None = None
                try:
                    temps = getattr(_psutil, "sensors_temperatures", lambda: None)()
                    if temps:
                        for key in temps:
                            for entry in temps[key]:
                                if hasattr(entry, "current") and entry.current:
                                    cpu_temp = float(entry.current)
                                    break
                            if cpu_temp is not None:
                                break
                except Exception:
                    cpu_temp = None

                disk_data = {
                    mount: {
                        "used_gb": float(info.used),
                        "total_gb": float(info.total),
                        "percent": info.percent,
                    }
                    for mount, info in disks_raw.items()
                }

                record = SystemMetricRecord(
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    cpu_avg=cpu_avg,
                    cpu_cores=[round(c, 1) for c in cpu_cores],
                    cpu_freq=cpu_freq,
                    cpu_temp=cpu_temp,
                    mem_used=int(mem.used),
                    mem_total=int(mem.total),
                    mem_pct=round(mem.percent, 2),
                    disk_data=disk_data,
                    network_data={
                        nic_id: nic_metrics.model_dump(mode="python")
                        for nic_id, nic_metrics in network_data.items()
                    },
                    disk_io_data={
                        disk_id: disk_metrics.model_dump(mode="python")
                        for disk_id, disk_metrics in disk_io_data.items()
                    },
                    process_count=process_count,
                )
                store.write(record)
            except Exception as exc:
                root_logger.debug(f"System metrics poll error: {exc}")

    threading.Thread(target=_worker, daemon=True, name="sysmet-worker").start()
    root_logger.info("System metrics background thread started.")


__all__ = [
    "SystemMetricsStoreProtocol",
    "start_system_metrics_worker",
]
