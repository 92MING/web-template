# -*- coding: utf-8 -*-
import gzip
import json
import os    
import re
import socket
import aiohttp
import requests
import netifaces
import logging
import urllib.request

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Literal, TypedDict

from core.constants import RESOURCES_DIR

_logger = logging.getLogger(__name__)
_local_ip = None
_global_ip = None

GEOLITE2_CITY_URL = "https://cdn.jsdelivr.net/npm/geolite2-city/GeoLite2-City.mmdb.gz"
GEOLITE2_CITY_DB_PATH = RESOURCES_DIR / "common" / "GeoLite2-City.mmdb"
GEOLITE2_CITY_UPDATE_RECORD_PATH = RESOURCES_DIR / "common" / "GeoLite2-City.update.json"

_ipv4_pattern = re.compile(r"(?:(?:[0-9]{1,3}\.){3}[0-9]{1,3})")
_ipv6_pattern = re.compile(
    r"((([0-9a-fA-F]{1,4}:){7}([0-9a-fA-F]{1,4}|:))|(([0-9a-fA-F]{1,4}:){1,7}:)|(([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4})|(([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2})|(([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3})|(([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4})|(([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5})|([0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6}))|(:((:[0-9a-fA-F]{1,4}){1,7}|:)))(%.+)?"
)


class IpGeoInfo(TypedDict):
    ip: str
    country: str
    country_code: str
    subdivision: str
    city: str
    latitude: float | None
    longitude: float | None
    timezone: str
    source: str


def _latest_geolite2_release_time(now: datetime | None = None) -> datetime:
    current = now.astimezone(UTC) if now else datetime.now(UTC)
    release_time = time(hour=6, tzinfo=UTC)
    release_weekdays = {1, 4}
    for delta_days in range(8):
        day = current.date() - timedelta(days=delta_days)
        candidate = datetime.combine(day, release_time)
        if candidate.weekday() in release_weekdays and candidate <= current:
            return candidate
    return datetime.combine(current.date(), release_time)


def _read_geolite2_update_record() -> dict[str, str]:
    try:
        with GEOLITE2_CITY_UPDATE_RECORD_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def geolite2_city_update_due(now: datetime | None = None) -> bool:
    if not GEOLITE2_CITY_DB_PATH.is_file():
        return True
    record = _read_geolite2_update_record()
    downloaded_at = str(record.get("downloaded_at") or "")
    if not downloaded_at:
        return True
    try:
        downloaded_dt = datetime.fromisoformat(downloaded_at).astimezone(UTC)
    except ValueError:
        return True
    return downloaded_dt < _latest_geolite2_release_time(now)


def ensure_geolite2_city_db(*, force: bool = False, timeout: float = 60.0) -> bool:
    if not force and not geolite2_city_update_due():
        return True
    GEOLITE2_CITY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_gz = GEOLITE2_CITY_DB_PATH.with_suffix(".mmdb.gz.tmp")
    tmp_mmdb = GEOLITE2_CITY_DB_PATH.with_suffix(".mmdb.tmp")
    try:
        with urllib.request.urlopen(GEOLITE2_CITY_URL, timeout=timeout) as response:
            with tmp_gz.open("wb") as file:
                file.write(response.read())
        with gzip.open(tmp_gz, "rb") as source, tmp_mmdb.open("wb") as target:
            target.write(source.read())
        os.replace(tmp_mmdb, GEOLITE2_CITY_DB_PATH)
        now = datetime.now(UTC)
        record = {
            "downloaded_at": now.isoformat(),
            "latest_release_at": _latest_geolite2_release_time(now).isoformat(),
            "source_url": GEOLITE2_CITY_URL,
        }
        with GEOLITE2_CITY_UPDATE_RECORD_PATH.open("w", encoding="utf-8") as file:
            json.dump(record, file, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        _logger.warning("GeoLite2 city database update failed: %s", exc)
        return GEOLITE2_CITY_DB_PATH.is_file()
    finally:
        for path in (tmp_gz, tmp_mmdb):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def get_ip_geo_info(ip: str, db_path: str | Path | None = None) -> IpGeoInfo | None:
    parsed = extract_ip(ip)
    if parsed is None:
        return None
    normalized_ip, _ = parsed
    database_path = Path(db_path) if db_path is not None else GEOLITE2_CITY_DB_PATH
    if not database_path.is_file():
        return None
    try:
        import geoip2.database
        import geoip2.errors
    except ImportError:
        return None
    try:
        with geoip2.database.Reader(str(database_path)) as reader:
            response = reader.city(normalized_ip)
    except geoip2.errors.AddressNotFoundError:
        return None
    except Exception as exc:
        _logger.debug("GeoLite2 lookup failed for %s: %s", normalized_ip, exc)
        return None
    country = response.country.name or ""
    city = response.city.name or ""
    subdivision = response.subdivisions.most_specific.name or ""
    return {
        "ip": normalized_ip,
        "country": country,
        "country_code": response.country.iso_code or "",
        "subdivision": subdivision,
        "city": city,
        "latitude": response.location.latitude,
        "longitude": response.location.longitude,
        "timezone": response.location.time_zone or "",
        "source": ", ".join(part for part in (country, subdivision, city) if part),
    }

def _get_env(key):
    return os.environ.get(key, None)

def get_available_port()->int:
    """Return a port that is available now"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    s.listen(1)
    port = s.getsockname()[1]
    s.close()
    return port

def check_port_is_using(port: int) -> bool:
    """Check if the port is using"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0

def get_local_ip(refresh: bool = False)->str:
    """Get local ip address, e.g. 192.168..."""
    global _local_ip
    if refresh or _local_ip is None:
        if (env_ip:=_get_env('SERVER_LOCAL_IP')):
            _local_ip = env_ip
        else:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                _local_ip = s.getsockname()[0]
            finally:
                s.close()
    return _local_ip

def get_global_IP(refresh: bool = False)->str:
    """sync version of aget_global_IP"""
    global _global_ip
    if refresh or _global_ip is None:
        if (ip:=_get_env('SERVER_GLOBAL_IP')) is not None:
            if m:=re.search(_ipv4_pattern, ip):
                _global_ip = m.group(0)
            elif m:=re.search(_ipv6_pattern, ip):
                _global_ip = m.group(0)
            else:
                _logger.warning(f'Environment variable SERVER_GLOBAL_IP="{ip}" is not a valid IP address. Try getting global IP automatically.')
        if _global_ip is not None:
            return _global_ip
        
        try:
            r = requests.get("https://api.ipify.org")
            _global_ip = r.text.strip()
            if m:=re.search(_ipv4_pattern, _global_ip):
                _global_ip = m.group(0)
            elif m:=re.search(_ipv6_pattern, _global_ip):
                _global_ip = m.group(0)
            
        except requests.exceptions.ConnectionError: 
            # e.g. for server in mainland China, api.ipify.org may be blocked
            r = requests.get("http://myip.ipip.net")
            if m:=re.search(_ipv4_pattern, r.text):
                _global_ip = m.group(0)
            elif m:=re.search(_ipv6_pattern, r.text):
                _global_ip = m.group(0)
        
        if not _global_ip:
            raise ValueError("Cannot get global IP address")
        
    return _global_ip

async def aget_global_ip(refresh: bool = False)->str:
    """Get global ip address(not local)"""
    global _global_ip
    if refresh or _global_ip is None:
        if (ip:=_get_env('SERVER_GLOBAL_IP')) is not None:
            if m:=re.search(_ipv4_pattern, ip):
                _global_ip = m.group(0)
            elif m:=re.search(_ipv6_pattern, ip):
                _global_ip = m.group(0)
            else:
                _logger.warning(f'Environment variable SERVER_GLOBAL_IP="{ip}" is not a valid IP address. Try getting global IP automatically.')
        if _global_ip is not None:
            return _global_ip
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.ipify.org") as response:
                    _global_ip = await response.text()
                    _global_ip = _global_ip.strip()
                    if m:=re.search(_ipv4_pattern, _global_ip):
                        _global_ip = m.group(0)
                    elif m:=re.search(_ipv6_pattern, _global_ip):
                        _global_ip = m.group(0)
        except aiohttp.ClientConnectionError:
            # e.g. for server in mainland China, api.ipify.org may be blocked
            async with aiohttp.ClientSession() as session:
                async with session.get("http://myip.ipip.net") as response:
                    text =  await response.text()
                    if m:=re.search(_ipv4_pattern, text):
                        _global_ip = m.group(0)
                    elif m:=re.search(_ipv6_pattern, text):
                        _global_ip = m.group(0)
        if not _global_ip:
            raise ValueError("Cannot get global IP address")

    return _global_ip

def get_sub_mask(ip: str | None = None)->str|None:
    """Get subnet mask of local ip address.
    (Default to get mask of local ip)"""
    ip_address = get_local_ip() if ip is None else ip
    for interface in netifaces.interfaces():  
        # loop all network interfaces to get subnet mask
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addrs:
            for addr in addrs[netifaces.AF_INET]:
                if addr["addr"] == ip_address:
                    return addr["netmask"]
    return None

def extract_ip(url: str)->tuple[str, Literal['ipv4', 'ipv6']]|None:
    '''extract ip from url(ipv4 or ipv6). Return (ip, type) if valid, else return None'''
    if m:=re.search(_ipv4_pattern, url):
        ip = m.group(0)
        # check if ip is valid
        if all(0 <= int(i) < 256 for i in ip.split(".")):
            return ip, 'ipv4'
    elif m:=re.search(_ipv6_pattern, url):
        ip = m.group(0)
        return ip, 'ipv6'
    return None

def check_ip_in_same_subnet(ip1: str, ip2: str, submask: str)->bool:
    """Check if two ip addresses are in the same subnet"""
    ip1, ip2 = extract_ip(ip1), extract_ip(ip2)   # type: ignore
    if not ip1 or not ip2:
        return False
    ip1 = [int(i) for i in ip1.split(".")]  # type: ignore
    ip2 = [int(i) for i in ip2.split(".")]  # type: ignore
    submask = submask.split(".")  # type: ignore
    for i in range(4):
        if (ip1[i] & int(submask[i])) != (ip2[i] & int(submask[i])):  # type: ignore
            return False
    return True

def ping(ip: str, count: int = 1, timeout: int|float|None=None)->int|None:
    '''
    Ping a ip address and return the time it takes to ping.
    If the ip address is not reachable, return None,
    else return the latency(in ms).
    '''
    ip = extract_ip(ip)    # type: ignore
    if not ip:
        return None
    if timeout and timeout > 0:
        cmd = f"ping -c {count} -W {int(timeout)} {ip}"
    else:
        cmd = f"ping -c {count} {ip}"
    result = os.popen(cmd).read()
    if "0 received" in result:
        return None
    else:
        times = re.findall(r"time=(\d+)\s?ms", result)
        if times:
            times = [float(i) for i in times]
            return int(sum(times) / len(times))  # type: ignore
        return None

_LOCALHOST_NAMES = frozenset(('localhost', '127.0.0.1', '::1'))

def is_own_ip(ip: str) -> bool:
    """Return *True* if *ip* resolves to this machine (localhost, LAN IP, or public IP)."""
    normalized_ip = ip.strip().lower()
    if normalized_ip in _LOCALHOST_NAMES or normalized_ip.startswith('127.'):
        return True
    extracted = extract_ip(ip)
    if extracted is None:
        return False
    resolved_ip, _ = extracted
    try:
        if resolved_ip == get_local_ip():
            return True
    except Exception:
        pass
    try:
        if resolved_ip == get_global_IP():
            return True
    except Exception:
        pass
    return False

def can_reach(host: str, port: int, timeout: float = 3.0) -> bool:
    """Return *True* if a TCP connection to *host*:*port* succeeds within *timeout* seconds."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

__all__ = [
    "get_available_port",
    "get_local_ip",
    "get_global_IP",
    "aget_global_ip",
    'extract_ip',
    "get_sub_mask",
    "check_ip_in_same_subnet",
    "check_port_is_using",
    'ping',
    'is_own_ip',
    'can_reach',
    'GEOLITE2_CITY_URL',
    'GEOLITE2_CITY_DB_PATH',
    'GEOLITE2_CITY_UPDATE_RECORD_PATH',
    'IpGeoInfo',
    'geolite2_city_update_due',
    'ensure_geolite2_city_db',
    'get_ip_geo_info',
]

if __name__ == "__main__":
    print(get_global_IP())