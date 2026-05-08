# -*- coding: utf-8 -*-
"""
Advanced request wrappers for aiohttp / requests / aiossechat with built-in
proxy logic.

Proxy detection and health-checking is inherited from the former ``proxy.py``.
In addition, this module provides high-level helpers that handle proxy
transparently:

*  `aiohttp_client_session` – drop-in ``aiohttp.ClientSession`` subclass that
   auto-injects proxy for non-local targets and retries on proxy failure.
*  `requests_request` / `requests_get` / `requests_post` / … – thin wrappers
   around the *requests* library (all standard HTTP methods).
*  `aiosseclient_with_proxy` – wrapper for ``aiossechat.aiosseclient``.

Usage::

    from core.utils.network_utils.proxy_requests import (
        aiohttp_client_session,
        requests_get,
        aiosseclient_with_proxy,
    )

    # aiohttp — drop-in replacement
    async with aiohttp_client_session() as session:
        async with session.get("https://example.com") as resp: ...

    # requests
    resp = requests_get("https://example.com")

    # aiossechat SSE streaming
    async for event in aiosseclient_with_proxy("https://api.example.com/stream"):
        print(event)
"""


import asyncio
import os
import ipaddress
import socket
import time
import aiohttp
import logging
import threading

from urllib.parse import urlparse
from typing import Any, AsyncGenerator


_logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Internal proxy state
# ──────────────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_cached_proxy: str | None = None
_cache_ts: float = 0.0
_CACHE_TTL: float = 30.0          # seconds before background re-probe
_PROBE_TIMEOUT: float = 3.0       # TCP connect timeout for health checks
_BG_INTERVAL: float = 30.0        # background checker loop interval
_PRIVATE_SUBNET_TTL: float = 300.0  # seconds before subnet route cache expires
_bg_thread: threading.Thread | None = None
_bg_stop = threading.Event()
_private_subnet_proxy_modes: dict[str, tuple[bool, float]] = {}

# Common Clash / V2Ray / Shadowsocks local ports
_COMMON_LOCAL_PORTS = list(range(7890, 7900))
_PRIVATE_V4_NETWORKS = (
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
)

# ──────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ──────────────────────────────────────────────────────────────────────────────
def _tcp_reachable(host: str, port: int, timeout: float = _PROBE_TIMEOUT) -> bool:
    """Return *True* if a TCP connection to *host:port* succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _probe_proxy(url: str) -> bool:
    """Check whether *url* points to a responsive proxy (TCP-level)."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        return _tcp_reachable(host, port)
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Candidate collectors
# ──────────────────────────────────────────────────────────────────────────────
def _candidates_from_env() -> list[str]:
    """Collect proxy URLs from environment variables."""
    candidates: list[str] = []
    for key in ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy',
                'ALL_PROXY', 'all_proxy'):
        val = os.environ.get(key, '').strip()
        if val:
            candidates.append(val)
    return candidates


def _candidates_from_windows_registry() -> list[str]:
    """Read the Windows system (IE) proxy setting from the registry."""
    candidates: list[str] = []
    try:
        import winreg  # type: ignore[import-untyped]
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, 'ProxyEnable')
            if not enabled:
                return []
            server, _ = winreg.QueryValueEx(key, 'ProxyServer')
            if not server:
                return []
            server = str(server).strip()
            # Could be "host:port" or "http=host:port;https=host:port;..."
            if '=' in server:
                for part in server.split(';'):
                    part = part.strip()
                    if not part:
                        continue
                    _proto, _, _addr = part.partition('=')
                    _addr = _addr.strip()
                    if _addr:
                        if not _addr.startswith(('http://', 'https://', 'socks')):
                            _addr = f'http://{_addr}'
                        candidates.append(_addr)
            else:
                if not server.startswith(('http://', 'https://', 'socks')):
                    server = f'http://{server}'
                candidates.append(server)
    except Exception:
        pass
    return candidates


def _candidates_from_common_ports() -> list[str]:
    """Generate candidate URLs for common local proxy ports."""
    return [f'http://127.0.0.1:{p}' for p in _COMMON_LOCAL_PORTS]


def _collect_all_candidates() -> list[str]:
    """Return de-duplicated candidate list in priority order."""
    seen: set[str] = set()
    result: list[str] = []
    for url in (
        *_candidates_from_env(),
        *_candidates_from_windows_registry(),
        *_candidates_from_common_ports(),
    ):
        norm = url.rstrip('/')
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Core probe & cache
# ──────────────────────────────────────────────────────────────────────────────
def _discover_proxy() -> str | None:
    """Walk through candidates and return the first healthy one (or *None*)."""
    for url in _collect_all_candidates():
        if _probe_proxy(url):
            return url
    return None


def _refresh_cache() -> None:
    global _cached_proxy, _cache_ts
    proxy = _discover_proxy()
    with _lock:
        changed = proxy != _cached_proxy
        _cached_proxy = proxy
        _cache_ts = time.monotonic()
    if changed:
        if proxy:
            _logger.debug('Proxy refreshed: %s', proxy)
        else:
            _logger.debug('No working proxy detected')


# ──────────────────────────────────────────────────────────────────────────────
# Background checker
# ──────────────────────────────────────────────────────────────────────────────
def _bg_loop() -> None:
    while not _bg_stop.wait(_BG_INTERVAL):
        try:
            _refresh_cache()
        except Exception:
            pass


def _ensure_bg_thread() -> None:
    global _bg_thread
    if _bg_thread is not None and _bg_thread.is_alive():
        return
    _bg_stop.clear()
    _bg_thread = threading.Thread(target=_bg_loop, name='proxy-checker', daemon=True)
    _bg_thread.start()


# ──────────────────────────────────────────────────────────────────────────────
# Localhost detection
# ──────────────────────────────────────────────────────────────────────────────
_LOCAL_HOSTS = frozenset(('localhost', '127.0.0.1', '::1'))


def _is_local_target(url: str) -> bool:
    """Return *True* if *url* targets localhost / 127.0.0.1 / ::1."""
    try:
        host = urlparse(url).hostname or ''
    except Exception:
        return False
    return host in _LOCAL_HOSTS or host.startswith('127.')


def _target_endpoint(url: str) -> tuple[str, int] | None:
    """Extract ``(host, port)`` from *url* for direct TCP reachability checks."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    return host, port


def _private_ipv4_subnet(url: str) -> str | None:
    """Return the RFC1918 ``/24`` subnet key when *url* uses a private IPv4 literal."""
    endpoint = _target_endpoint(url)
    if endpoint is None:
        return None
    host, _port = endpoint
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if not isinstance(ip, ipaddress.IPv4Address):
        return None
    if not any(ip in network for network in _PRIVATE_V4_NETWORKS):
        return None
    return str(ipaddress.ip_network(f'{ip}/24', strict=False))


def _get_private_subnet_proxy_mode(subnet: str) -> bool | None:
    with _lock:
        entry = _private_subnet_proxy_modes.get(subnet)
        if entry is None:
            return None
        mode, ts = entry
        if time.monotonic() - ts > _PRIVATE_SUBNET_TTL:
            try:
                del _private_subnet_proxy_modes[subnet]
            except KeyError:
                pass
            return None
        return mode


def _remember_private_subnet_proxy_mode(subnet: str, use_proxy: bool) -> None:
    with _lock:
        old_entry = _private_subnet_proxy_modes.get(subnet)
        old_value = old_entry[0] if old_entry is not None else None
        _private_subnet_proxy_modes[subnet] = (use_proxy, time.monotonic())
    if old_value != use_proxy:
        route = 'proxy' if use_proxy else 'direct'
        _logger.debug('Private subnet %s route learned as %s', subnet, route)


def _private_route_plan(url: str, proxy_url: str | None) -> tuple[str | None, list[bool]]:
    """Return ``(subnet, [use_proxy...])`` for RFC1918 targets."""
    subnet = _private_ipv4_subnet(url)
    if subnet is None:
        return None, []

    cached_mode = _get_private_subnet_proxy_mode(subnet)
    route_plan: list[bool] = []
    if cached_mode is True and proxy_url:
        route_plan.append(True)

    route_plan.append(False)
    if proxy_url and True not in route_plan:
        route_plan.append(True)

    return subnet, route_plan


def _can_reach_target_direct(url: str) -> bool:
    """Return *True* when the target host:port is directly reachable via TCP."""
    endpoint = _target_endpoint(url)
    if endpoint is None:
        return False
    host, port = endpoint
    return _tcp_reachable(host, port)


def _failure_signature(exc: BaseException | None) -> tuple[str, str] | None:
    if exc is None:
        return None
    return type(exc).__name__, str(exc).strip()


def _same_failure(left: BaseException | None, right: BaseException | None) -> bool:
    left_sig = _failure_signature(left)
    right_sig = _failure_signature(right)
    return left_sig is not None and left_sig == right_sig


def _is_aiohttp_connectivity_failure(exc: Exception) -> bool:
    ssl_errors = tuple(
        cls for cls in (
            getattr(aiohttp, 'ClientSSLError', None),
            getattr(aiohttp, 'ClientConnectorCertificateError', None),
        ) if cls is not None
    )
    if ssl_errors and isinstance(exc, ssl_errors):
        return False
    return isinstance(exc, (
        aiohttp.ClientProxyConnectionError,
        aiohttp.ClientHttpProxyError,
        aiohttp.ClientConnectorError,
        aiohttp.ClientOSError,
        asyncio.TimeoutError,
        TimeoutError,
        OSError,
    ))


def _is_requests_connectivity_failure(exc: Exception, req_exc: Any) -> bool:
    if isinstance(exc, req_exc.SSLError):
        return False
    return isinstance(exc, (
        req_exc.ProxyError,
        req_exc.ConnectTimeout,
        req_exc.ConnectionError,
        req_exc.Timeout,
    ))


# ──────────────────────────────────────────────────────────────────────────────
# Public API — proxy core
# ──────────────────────────────────────────────────────────────────────────────
def get_proxy_url(*, force_refresh: bool = False) -> str | None:
    """Return a working proxy URL, or ``None`` if no proxy is available.

    On first call the proxy list is probed synchronously (fast TCP checks).
    Subsequent calls return the cached value and a background thread keeps the
    cache fresh.
    """
    global _cached_proxy, _cache_ts
    _ensure_bg_thread()

    now = time.monotonic()
    with _lock:
        age = now - _cache_ts

    if force_refresh or age > _CACHE_TTL:
        _refresh_cache()

    with _lock:
        return _cached_proxy


def report_proxy_failure() -> None:
    """Report that a request through the current proxy has failed.

    Immediately invalidates the cached proxy so that subsequent calls to
    :func:`get_proxy_url` return ``None`` until a healthy proxy is found.
    """
    global _cached_proxy, _cache_ts
    with _lock:
        if _cached_proxy is None:
            return
        old = _cached_proxy
        _cached_proxy = None
        _cache_ts = 0.0
    _logger.warning('Proxy failure reported — cleared %s, falling back to direct', old)


def stop_proxy_checker() -> None:
    """Stop the background proxy-checking thread (e.g. during shutdown)."""
    _bg_stop.set()
    if _bg_thread is not None and _bg_thread.is_alive():
        _bg_thread.join(timeout=2.0)


# ──────────────────────────────────────────────────────────────────────────────
# Public API — legacy helpers (backwards compat)
# ──────────────────────────────────────────────────────────────────────────────
def aiohttp_proxy_kwargs() -> dict[str, Any]:
    """Return ``{'proxy': url}`` for aiohttp, or empty dict.

    .. note:: Prefer :class:`aiohttp_client_session` which handles proxy
       injection and failover automatically.
    """
    url = get_proxy_url()
    return {'proxy': url} if url else {}


def requests_proxy_dict() -> dict[str, str] | None:
    """Return a ``proxies`` dict for *requests*, or ``None``.

    .. note:: Prefer :func:`requests_request` / :func:`requests_get` /
       :func:`requests_post` which handle proxy and failover automatically.
    """
    url = get_proxy_url()
    if url is None:
        return None
    return {'http': url, 'https': url}


# ──────────────────────────────────────────────────────────────────────────────
# Public API — aiohttp
# ──────────────────────────────────────────────────────────────────────────────
class aiohttp_client_session(aiohttp.ClientSession):
    """Drop-in ``aiohttp.ClientSession`` replacement with transparent proxy.

    *  Auto-detects a working proxy via the background checker.
    *  Injects the proxy for non-local targets (skips ``localhost`` /
       ``127.0.0.1`` / ``::1``).
    *  On proxy connection failure, reports the failure, clears the cache,
       and retries the **same** request without a proxy.
    """

    async def _request(  # type: ignore[override]
        self, method: str, str_or_url: Any, **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        url = str(str_or_url)
        proxy = kwargs.get('proxy')
        auto_injected = False

        if proxy is None and _is_local_target(url):
            return await super()._request(method, str_or_url, **kwargs)

        if proxy is None:
            subnet, route_plan = _private_route_plan(url, get_proxy_url())
            if subnet is not None:
                route_errors: dict[str, Exception] = {}
                last_exc: Exception | None = None
                proxy_url = get_proxy_url()
                for use_proxy in route_plan:
                    attempt_kwargs = kwargs.copy()
                    route_name = 'proxy' if use_proxy else 'direct'
                    if use_proxy:
                        if not proxy_url:
                            continue
                        attempt_kwargs['proxy'] = proxy_url
                    else:
                        attempt_kwargs.pop('proxy', None)
                    try:
                        response = await super()._request(method, str_or_url, **attempt_kwargs)
                        _remember_private_subnet_proxy_mode(subnet, use_proxy)
                        return response
                    except Exception as exc:
                        last_exc = exc
                        route_errors[route_name] = exc
                        if not use_proxy and _can_reach_target_direct(url):
                            _remember_private_subnet_proxy_mode(subnet, False)
                            raise
                        if use_proxy:
                            if isinstance(exc, (aiohttp.ClientProxyConnectionError, aiohttp.ClientHttpProxyError)):
                                report_proxy_failure()
                            if not _is_aiohttp_connectivity_failure(exc):
                                _remember_private_subnet_proxy_mode(subnet, True)
                                raise
                        continue

                if _same_failure(route_errors.get('direct'), route_errors.get('proxy')):
                    _remember_private_subnet_proxy_mode(subnet, False)
                if last_exc is not None:
                    raise last_exc

        if proxy is None and not _is_local_target(url):
            proxy = get_proxy_url()
            if proxy:
                kwargs['proxy'] = proxy
                auto_injected = True

        try:
            return await super()._request(method, str_or_url, **kwargs)
        except Exception as exc:
            if auto_injected and _is_aiohttp_connectivity_failure(exc):
                direct_kwargs = kwargs.copy()
                direct_kwargs.pop('proxy', None)
                response = await super()._request(method, str_or_url, **direct_kwargs)
                report_proxy_failure()
                return response
            raise


# ──────────────────────────────────────────────────────────────────────────────
# Public API — requests
# ──────────────────────────────────────────────────────────────────────────────
def requests_request(method: str, url: str, **kwargs: Any) -> Any:
    """Like ``requests.request`` with automatic proxy injection & failover."""
    import requests as _req  # lazy — avoid hard dep at import time
    req_exc = _req.exceptions

    if 'proxies' not in kwargs and _is_local_target(url):
        return _req.request(method, url, **kwargs)

    if 'proxies' not in kwargs:
        proxy_url = get_proxy_url()
        subnet, route_plan = _private_route_plan(url, proxy_url)
        if subnet is not None:
            route_errors: dict[str, Exception] = {}
            last_exc: Exception | None = None
            for use_proxy in route_plan:
                attempt_kwargs = kwargs.copy()
                route_name = 'proxy' if use_proxy else 'direct'
                if use_proxy:
                    if not proxy_url:
                        continue
                    attempt_kwargs['proxies'] = {'http': proxy_url, 'https': proxy_url}
                else:
                    attempt_kwargs.pop('proxies', None)
                try:
                    response = _req.request(method, url, **attempt_kwargs)
                    _remember_private_subnet_proxy_mode(subnet, use_proxy)
                    return response
                except req_exc.RequestException as exc:
                    last_exc = exc
                    route_errors[route_name] = exc
                    if not use_proxy and _can_reach_target_direct(url):
                        _remember_private_subnet_proxy_mode(subnet, False)
                        raise
                    if use_proxy:
                        if isinstance(exc, req_exc.ProxyError):
                            report_proxy_failure()
                        if not _is_requests_connectivity_failure(exc, req_exc):
                            _remember_private_subnet_proxy_mode(subnet, True)
                            raise
                    continue

            if _same_failure(route_errors.get('direct'), route_errors.get('proxy')):
                _remember_private_subnet_proxy_mode(subnet, False)
            if last_exc is not None:
                raise last_exc

    if 'proxies' not in kwargs and not _is_local_target(url):
        proxy_url = get_proxy_url()
        if proxy_url:
            kwargs['proxies'] = {'http': proxy_url, 'https': proxy_url}
            try:
                return _req.request(method, url, **kwargs)
            except _req.exceptions.ProxyError:
                report_proxy_failure()
                kwargs.pop('proxies', None)
                return _req.request(method, url, **kwargs)

    return _req.request(method, url, **kwargs)


def requests_get(url: str, **kwargs: Any) -> Any:
    """``requests.get`` with automatic proxy injection & failover."""
    return requests_request('GET', url, **kwargs)


def requests_post(url: str, **kwargs: Any) -> Any:
    """``requests.post`` with automatic proxy injection & failover."""
    return requests_request('POST', url, **kwargs)


def requests_put(url: str, **kwargs: Any) -> Any:
    """``requests.put`` with automatic proxy injection & failover."""
    return requests_request('PUT', url, **kwargs)


def requests_patch(url: str, **kwargs: Any) -> Any:
    """``requests.patch`` with automatic proxy injection & failover."""
    return requests_request('PATCH', url, **kwargs)


def requests_delete(url: str, **kwargs: Any) -> Any:
    """``requests.delete`` with automatic proxy injection & failover."""
    return requests_request('DELETE', url, **kwargs)


def requests_head(url: str, **kwargs: Any) -> Any:
    """``requests.head`` with automatic proxy injection & failover."""
    return requests_request('HEAD', url, **kwargs)


def requests_options(url: str, **kwargs: Any) -> Any:
    """``requests.options`` with automatic proxy injection & failover."""
    return requests_request('OPTIONS', url, **kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# Public API — aiossechat
# ──────────────────────────────────────────────────────────────────────────────
async def aiosseclient_with_proxy(
    url: str, **kwargs: Any,
) -> AsyncGenerator[Any, None]:
    """Wrapper for ``aiossechat.aiosseclient`` with automatic proxy.

    Creates an :class:`aiohttp_client_session` as the underlying session so
    that proxy injection and failover happen transparently.  For local
    targets the plain ``aiohttp.ClientSession`` is used instead.
    """
    from aiossechat import aiosseclient  # type: ignore[import-untyped]

    if 'session' not in kwargs:
        if _is_local_target(url):
            kwargs['session'] = aiohttp.ClientSession()
        else:
            kwargs['session'] = aiohttp_client_session()

    async for event in aiosseclient(url, **kwargs):
        yield event

__all__ = [
    # Proxy core
    'get_proxy_url',
    'report_proxy_failure',
    'stop_proxy_checker',
    
    # aiohttp
    'aiohttp_client_session',
    'aiohttp_proxy_kwargs',
    
    # requests
    'requests_request',
    'requests_get',
    'requests_post',
    'requests_put',
    'requests_patch',
    'requests_delete',
    'requests_head',
    'requests_options',
    'requests_proxy_dict',
    
    # aiossechat
    'aiosseclient_with_proxy',
]
