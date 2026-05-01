# -*- coding: utf-8 -*-
'''get system information, e.g. network, cpu, memory, ...'''
import sys
import platform
import socket
import psutil
import subprocess

from datetime import datetime, timezone
from pydantic import BaseModel
from psutil import disk_usage
from typing import Sequence, overload, Literal


def run_command(cmds: str | Sequence[str], sudo_pw: str | None = None) -> str:  # type: ignore
    '''
    run a command and get the output.

    Args:
        cmd: the command to run
        sudo_pw: the password of sudo. `sudo` mode will be enabled if sudo_pw is not None.

    WARNING: using sudo mode may cause security issues. Be careful when using it.
    '''
    if sudo_pw is not None:
        cmd_prefix = f'echo {sudo_pw} | sudo -SE '
    else:
        cmd_prefix = ''
    if isinstance(cmds, str):
        cmds = [cmds]
    cmd = ' && '.join(cmds)
    cmd = f'{cmd_prefix}{cmd}'

    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    p.wait()
    if p.returncode != 0:
        raise Exception(f'error occur when running command: {cmd}, return code: {p.returncode}, error: {err}')
    return out.decode().strip()


class MemoryInfo(BaseModel):
    used: int
    '''used memory, in MB'''
    total: int
    '''total memory, in MB'''
    percent: float
    '''usage percentage'''


@overload
def get_memory_usage() -> float: ...
@overload
def get_memory_usage(detail: Literal[False]) -> float: ...
@overload
def get_memory_usage(detail: Literal[True]) -> MemoryInfo: ...


def get_memory_usage(detail: bool = False):  # type: ignore
    '''
    Get memory usage.
    If `detail` is True, return MemoryInfo object, otherwise only return usage percentage.
    '''
    if not detail:
        return psutil.virtual_memory().percent
    else:
        mem = psutil.virtual_memory()
        used = mem.used // 1024 // 1024
        total = mem.total // 1024 // 1024
        percent = mem.percent
        return MemoryInfo(used=used, total=total, percent=percent)


class DiskUsage(BaseModel):
    percent: float
    '''usage percentage'''
    used: int
    '''used space in GB'''
    total: int
    '''total space in GB'''


class NetworkIOInfo(BaseModel):
    bytes_sent: int
    '''累计发送字节数'''
    bytes_recv: int
    '''累计接收字节数'''
    packets_sent: int
    '''累计发送包数'''
    packets_recv: int
    '''累计接收包数'''


class NetworkInterfaceIOInfo(BaseModel):
    bytes_sent: int
    '''该网卡累计发送字节数'''
    bytes_recv: int
    '''该网卡累计接收字节数'''
    packets_sent: int
    '''该网卡累计发送包数'''
    packets_recv: int
    '''该网卡累计接收包数'''


class DiskIOInfo(BaseModel):
    read_bytes: int
    '''累计磁盘读取字节数'''
    write_bytes: int
    '''累计磁盘写入字节数'''
    read_count: int
    '''累计磁盘读取次数'''
    write_count: int
    '''累计磁盘写入次数'''


class DiskDeviceIOInfo(BaseModel):
    read_bytes: int
    '''该磁盘累计读取字节数'''
    write_bytes: int
    '''该磁盘累计写入字节数'''
    read_count: int
    '''该磁盘累计读取次数'''
    write_count: int
    '''该磁盘累计写入次数'''


def get_disks_usage() -> dict[str, DiskUsage]:
    '''
    Get all disks' usage. Cross-platform (Windows & Linux/macOS).
    Return in {'C:\\\\': DiskUsage, 'D:\\\\': DiskUsage, ...} on Windows,
    or {'/': DiskUsage, '/mnt/disk1': DiskUsage, ...} on Linux.
    '''
    disk_usages = {}
    seen = set()
    for part in psutil.disk_partitions(all=False):
        mp = part.mountpoint
        if mp in seen:
            continue
        # skip optical drives and pseudo-filesystems on Windows
        if platform.system() == 'Windows' and part.fstype == '':
            continue
        try:
            usage = disk_usage(mp)
        except (PermissionError, OSError):
            continue
        seen.add(mp)
        percent = usage.percent
        used = usage.used // 1024 // 1024 // 1024
        total = usage.total // 1024 // 1024 // 1024
        disk_usages[mp] = DiskUsage(percent=percent, used=used, total=total)
    return disk_usages


@overload
def get_network_io() -> NetworkIOInfo: ...
@overload
def get_network_io(pernic: Literal[False]) -> NetworkIOInfo: ...
@overload
def get_network_io(pernic: Literal[True]) -> dict[str, NetworkInterfaceIOInfo]: ...


def get_network_io(pernic: bool = False):
    '''获取主机累计网络收发统计。'''
    counters = psutil.net_io_counters(pernic=pernic)
    if pernic:
        if not counters:
            return {}
        return {
            str(nic_id): NetworkInterfaceIOInfo(
                bytes_sent=int(getattr(nic_counters, 'bytes_sent', 0) or 0),
                bytes_recv=int(getattr(nic_counters, 'bytes_recv', 0) or 0),
                packets_sent=int(getattr(nic_counters, 'packets_sent', 0) or 0),
                packets_recv=int(getattr(nic_counters, 'packets_recv', 0) or 0),
            )
            for nic_id, nic_counters in dict(counters).items()
        }
    if counters is None:
        return NetworkIOInfo(bytes_sent=0, bytes_recv=0, packets_sent=0, packets_recv=0)
    return NetworkIOInfo(
        bytes_sent=int(getattr(counters, 'bytes_sent', 0) or 0),
        bytes_recv=int(getattr(counters, 'bytes_recv', 0) or 0),
        packets_sent=int(getattr(counters, 'packets_sent', 0) or 0),
        packets_recv=int(getattr(counters, 'packets_recv', 0) or 0),
    )


@overload
def get_disk_io() -> DiskIOInfo: ...
@overload
def get_disk_io(perdisk: Literal[False]) -> DiskIOInfo: ...
@overload
def get_disk_io(perdisk: Literal[True]) -> dict[str, DiskDeviceIOInfo]: ...


def get_disk_io(perdisk: bool = False):
    '''获取主机累计磁盘读写统计。'''
    counters = psutil.disk_io_counters(perdisk=perdisk)
    if perdisk:
        if not counters:
            return {}
        return {
            str(disk_id): DiskDeviceIOInfo(
                read_bytes=int(getattr(disk_counters, 'read_bytes', 0) or 0),
                write_bytes=int(getattr(disk_counters, 'write_bytes', 0) or 0),
                read_count=int(getattr(disk_counters, 'read_count', 0) or 0),
                write_count=int(getattr(disk_counters, 'write_count', 0) or 0),
            )
            for disk_id, disk_counters in dict(counters).items()
        }
    if counters is None:
        return DiskIOInfo(read_bytes=0, write_bytes=0, read_count=0, write_count=0)
    return DiskIOInfo(
        read_bytes=int(getattr(counters, 'read_bytes', 0) or 0),
        write_bytes=int(getattr(counters, 'write_bytes', 0) or 0),
        read_count=int(getattr(counters, 'read_count', 0) or 0),
        write_count=int(getattr(counters, 'write_count', 0) or 0),
    )


class HostInfo(BaseModel):
    hostname: str
    os: str
    os_version: str
    architecture: str
    python_version: str
    cpu_count_logical: int
    cpu_count_physical: int | None
    boot_time: str       # ISO-8601 UTC
    uptime_seconds: float


class NetworkInterfaceAddress(BaseModel):
    family: str
    address: str
    netmask: str | None = None
    broadcast: str | None = None
    ptp: str | None = None


class NetworkInterfaceInfo(BaseModel):
    id: str
    is_up: bool | None = None
    mtu: int | None = None
    speed_mbps: int | None = None
    duplex: str | None = None
    addresses: list[NetworkInterfaceAddress]


class DiskPartitionInfo(BaseModel):
    device: str
    mountpoint: str
    fstype: str | None = None
    opts: str | None = None


def get_host_info() -> HostInfo:
    '''Return static/slow-changing host information.'''
    boot_ts = psutil.boot_time()
    boot_dt = datetime.fromtimestamp(boot_ts, tz=timezone.utc)
    uptime = (datetime.now(tz=timezone.utc) - boot_dt).total_seconds()
    return HostInfo(
        hostname=socket.gethostname(),
        os=platform.system(),
        os_version=platform.version(),
        architecture=platform.machine(),
        python_version=sys.version.split()[0],
        cpu_count_logical=psutil.cpu_count(logical=True) or 0,
        cpu_count_physical=psutil.cpu_count(logical=False),
        boot_time=boot_dt.isoformat(),
        uptime_seconds=uptime,
    )


def get_network_interfaces() -> dict[str, NetworkInterfaceInfo]:
    result: dict[str, NetworkInterfaceInfo] = {}
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    duplex_map = {
        getattr(psutil, 'NIC_DUPLEX_FULL', object()): 'full',
        getattr(psutil, 'NIC_DUPLEX_HALF', object()): 'half',
        getattr(psutil, 'NIC_DUPLEX_UNKNOWN', object()): 'unknown',
    }
    for nic_id, nic_addrs in addrs.items():
        stat_info = stats.get(nic_id)
        addresses = []
        for item in nic_addrs:
            family = getattr(item.family, 'name', None) or str(item.family)
            addresses.append(NetworkInterfaceAddress(
                family=family,
                address=str(getattr(item, 'address', '') or ''),
                netmask=str(getattr(item, 'netmask', '') or '') or None,
                broadcast=str(getattr(item, 'broadcast', '') or '') or None,
                ptp=str(getattr(item, 'ptp', '') or '') or None,
            ))
        result[str(nic_id)] = NetworkInterfaceInfo(
            id=str(nic_id),
            is_up=getattr(stat_info, 'isup', None),
            mtu=getattr(stat_info, 'mtu', None),
            speed_mbps=getattr(stat_info, 'speed', None),
            duplex=duplex_map.get(getattr(stat_info, 'duplex', None), str(getattr(stat_info, 'duplex', '')) or None),
            addresses=addresses,
        )
    return result


def get_disk_partitions_info() -> dict[str, DiskPartitionInfo]:
    result: dict[str, DiskPartitionInfo] = {}
    for part in psutil.disk_partitions(all=False):
        mountpoint = str(getattr(part, 'mountpoint', '') or '')
        if not mountpoint:
            continue
        result[mountpoint] = DiskPartitionInfo(
            device=str(getattr(part, 'device', '') or ''),
            mountpoint=mountpoint,
            fstype=str(getattr(part, 'fstype', '') or '') or None,
            opts=str(getattr(part, 'opts', '') or '') or None,
        )
    return result


__all__ = [
    'run_command',
    'get_memory_usage', 'MemoryInfo',
    'get_disks_usage', 'DiskUsage',
    'get_network_io', 'NetworkIOInfo',
    'NetworkInterfaceIOInfo',
    'get_disk_io', 'DiskIOInfo',
    'DiskDeviceIOInfo',
    'HostInfo', 'get_host_info',
    'NetworkInterfaceAddress', 'NetworkInterfaceInfo', 'get_network_interfaces',
    'DiskPartitionInfo', 'get_disk_partitions_info',
]
