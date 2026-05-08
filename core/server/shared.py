import os
import time
import uuid
import socket
import pickle
import struct
import asyncio
import inspect
import atexit
import threading
import re

from fastapi import FastAPI
from datetime import datetime, timedelta, timezone
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from pydantic import BaseModel
from starlette.requests import Request
from starlette.routing import Match, Route
from starlette.types import Scope
from typing import (
    TYPE_CHECKING, Self, Literal, NotRequired, TypeGuard, TypeVar, TypedDict, cast, overload,
    get_type_hints,
)

from core.ai.shared import AIServiceKind
from core.storage.config import close_global_storage_clients
from core.rtc_chat.room import close_all_rooms, RoomInfo
from core.utils.concurrent_utils.shared_obj import CrossProcessSharedObject, _close_all_managers

from .app import on_app_shutdown, on_uvicorn_close

# close rooms per-worker (safe to call from each worker)
on_app_shutdown(close_all_rooms)

# close storage clients per-worker so sqlite/aiosqlite background threads do not hang interpreter shutdown
on_app_shutdown(close_global_storage_clients)

# close managers only once when uvicorn fully exits (not per-worker)
on_uvicorn_close(_close_all_managers)

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════
type WorkerRuntimeStatus = Literal["starting", "running", "dead"]
type AIServiceReloadStatus = Literal["reloading", "ready", "error"]
type CacheScope = Literal["cross-process"]
type ProcessSnapshotPayload = dict[str, object]
type PortSnapshotPayload = dict[str, object]

TCacheValue = TypeVar("TCacheValue")
TCacheDefault = TypeVar("TCacheDefault")

class RedirectRequestMessage(TypedDict):
    type: Literal["http.request"]
    body: bytes
    more_body: bool

class WorkerSnapshot(TypedDict):
    pid: int
    generation: int
    shm_slot: int | None
    msg_port: int | None
    started_at: str | None
    request_count: int
    last_request_at: str | None
    status: WorkerRuntimeStatus
    lifespan_ready: bool
    dead: bool
    
class AIServiceConfigSnapshot(TypedDict):
    serialized_config: str | None
    version: int
    updated_at: str | None

class AIServiceReloadStateRow(TypedDict):
    pid: int
    version: int
    state: AIServiceReloadStatus
    service_kinds: list[AIServiceKind]
    error: str | None
    updated_at: str

class AIServiceRuntimeUpdateResult(TypedDict):
    ok: bool
    pid: int
    version: int
    service_kinds: list[AIServiceKind]
    error: NotRequired[str | None]

class DiskSnapshotPayload(TypedDict):
    used_gb: float
    total_gb: float
    percent: float

class NetworkInterfaceSnapshotPayload(TypedDict):
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int

class DiskIOSnapshotPayload(TypedDict):
    read_bytes: int
    write_bytes: int
    read_count: int
    write_count: int

class SystemSnapshotPayload(TypedDict):
    timestamp: str
    cpu_avg: float
    cpu_cores: list[float]
    cpu_freq: float | None
    cpu_temp: float | None
    mem_used: int
    mem_total: int
    mem_pct: float
    disk_data: dict[str, DiskSnapshotPayload]
    network_data: dict[str, NetworkInterfaceSnapshotPayload]
    disk_io_data: dict[str, DiskIOSnapshotPayload]
    process_count: int

class RuntimeMeta(TypedDict):
    instance_uuid: str
    server_start_time: str | None
    shared_manager_pid: int
    cache_scope: CacheScope
    worker_count: int
    request_count_total: int
    workers: list[WorkerSnapshot]
    supervisor_pid: int | None
    control_mode: str | None
    control_supported: bool
    config_file_path: str | None

def _find_available_port(
    start_port: int = 10000,
    end_port: int = 32768,
    *,
    exclude_ports: set[int] | None = None,
) -> int:
    """Find the first TCP port in *[start_port, end_port)* that is not in use."""
    excluded = exclude_ports or set()
    for port in range(start_port, end_port):
        if port in excluded:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port

    raise RuntimeError(f"No available port found in range {start_port}-{end_port}")

def _allocate_worker_msg_port(
    existing_ports: set[int],
    preferred_port: int | None = None,
) -> int:
    if preferred_port is not None and preferred_port not in existing_ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', preferred_port)) != 0:
                return preferred_port
    return _find_available_port(exclude_ports=existing_ports)

_WORKER_SHM_SLOT_SIZE = 48
_WORKER_SHM_HEARTBEAT_INTERVAL_SECONDS = 5.0
_WORKER_SHM_DEAD_AFTER_SECONDS = 16.0
_WORKER_SHM_STATUS_STARTING = 0
_WORKER_SHM_STATUS_RUNNING = 1
_WORKER_SHM_STATUS_DEAD = 2
_WORKER_STATUS_TO_BYTE: dict[WorkerRuntimeStatus, int] = {
    "starting": _WORKER_SHM_STATUS_STARTING,
    "running": _WORKER_SHM_STATUS_RUNNING,
    "dead": _WORKER_SHM_STATUS_DEAD,
}
_WORKER_STATUS_FROM_BYTE: dict[int, WorkerRuntimeStatus] = {
    _WORKER_SHM_STATUS_STARTING: "starting",
    _WORKER_SHM_STATUS_RUNNING: "running",
    _WORKER_SHM_STATUS_DEAD: "dead",
}
_WORKER_SHM_NAME_ENV = "WORKER_SHM_NAME"
_WORKER_SHM_SLOT_ENV = "WORKER_SHM_SLOT"
_WORKER_GENERATION_ENV = "WORKER_GENERATION"
_WORKER_MANAGER_PID_ENV = "WORKER_SHARED_MANAGER_PID"

_worker_shm: shared_memory.SharedMemory | None = None
_worker_shm_name: str | None = None
_worker_heartbeat_stop: threading.Event | None = None
_worker_heartbeat_thread: threading.Thread | None = None
_worker_info_cache: dict[int, tuple[int, int, int, str]] = {}
_worker_info_cache_lock = threading.RLock()
_worker_slot_write_lock = threading.RLock()

_other_worker_sockets: dict[tuple[int, int], tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}
_other_worker_socket_locks: dict[tuple[int, int], asyncio.Lock] = {}

def _status_byte_to_text(value: int) -> WorkerRuntimeStatus:
    return _WORKER_STATUS_FROM_BYTE.get(int(value), "starting")

def _status_text_to_byte(value: WorkerRuntimeStatus) -> int:
    return _WORKER_STATUS_TO_BYTE.get(value, _WORKER_SHM_STATUS_STARTING)

def _worker_shm_name_for_manager(manager_pid: int) -> str:
    instance_id = os.getenv("__SERVER_INSTANCE_ID__", "").strip() or "default"
    safe_instance_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", instance_id).strip("-._") or "default"
    return f"wt-wshm-{safe_instance_id}-{int(manager_pid)}"

def _expected_worker_slots() -> int:
    try:
        from core.server.data_types.config import Config

        expected_workers = int(Config.GetConfig().server_config.worker or 1)
    except Exception:
        expected_workers = 1
    return max(8, int(expected_workers * 1.5 + 0.999))

def _slot_offset(slot: int) -> int:
    return int(slot) * _WORKER_SHM_SLOT_SIZE

def _iso_from_time_ns(value: int) -> str | None:
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, timezone.utc).isoformat()

def _monotonic_seconds_int() -> int:
    return int(time.monotonic())

def _pack_worker_slot(
    buf: memoryview,
    slot: int,
    *,
    pid: int,
    generation: int,
    request_count: int,
    last_request_at_ns: int,
    alive_at_monotonic: int,
    msg_port: int,
    lifespan_ready: bool,
    status: WorkerRuntimeStatus,
) -> None:
    offset = _slot_offset(slot)
    struct.pack_into(
        ">QQQQQIBBH",
        buf,
        offset,
        max(0, int(pid)),
        max(0, int(generation)),
        max(0, int(request_count)),
        max(0, int(last_request_at_ns)),
        max(0, int(alive_at_monotonic)),
        max(0, int(msg_port)),
        1 if lifespan_ready else 0,
        _status_text_to_byte(status),
        0,
    )

def _read_worker_slot(buf: memoryview, slot: int) -> dict[str, int | bool | WorkerRuntimeStatus]:
    offset = _slot_offset(slot)
    pid, generation, request_count, last_request_at_ns, alive_at_monotonic, msg_port, ready, status, _ = struct.unpack_from(
        ">QQQQQIBBH",
        buf,
        offset,
    )
    return {
        "pid": int(pid),
        "generation": int(generation),
        "request_count": int(request_count),
        "last_request_at_ns": int(last_request_at_ns),
        "alive_at_monotonic": int(alive_at_monotonic),
        "msg_port": int(msg_port),
        "lifespan_ready": bool(ready),
        "status": _status_byte_to_text(int(status)),
    }

def _clear_worker_slot(buf: memoryview, slot: int) -> None:
    offset = _slot_offset(slot)
    buf[offset:offset + _WORKER_SHM_SLOT_SIZE] = b"\x00" * _WORKER_SHM_SLOT_SIZE

def _connect_worker_shm(name: str | None = None) -> shared_memory.SharedMemory | None:
    global _worker_shm, _worker_shm_name
    resolved_name = name or os.getenv(_WORKER_SHM_NAME_ENV)
    if not resolved_name:
        manager_pid = os.getenv(_WORKER_MANAGER_PID_ENV)
        if manager_pid:
            resolved_name = _worker_shm_name_for_manager(int(manager_pid))
    if not resolved_name:
        return None
    if _worker_shm is not None and _worker_shm_name == resolved_name:
        return _worker_shm
    if _worker_shm is not None:
        try:
            _worker_shm.close()
        except Exception:
            pass
    _worker_shm = shared_memory.SharedMemory(name=resolved_name)
    _worker_shm_name = resolved_name
    return _worker_shm

def _close_worker_shm() -> None:
    global _worker_shm, _worker_shm_name
    if _worker_shm is not None:
        try:
            _worker_shm.close()
        except Exception:
            pass
    _worker_shm = None
    _worker_shm_name = None

atexit.register(_close_worker_shm)

def _is_request_annotation(annotation: object) -> TypeGuard[type[Request]]:
    try:
        return inspect.isclass(annotation) and issubclass(annotation, Request)
    except Exception:
        return False

def _is_pydantic_model(annotation: object) -> TypeGuard[type[BaseModel]]:
    try:
        return inspect.isclass(annotation) and issubclass(annotation, BaseModel)
    except Exception:
        return False

def _build_redirect_request(path: str, method: str, headers: list[tuple[str, str]] | None = None) -> Request:
    scope = cast(Scope, {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in (headers or [])],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 0),
    })
    async def _receive() -> RedirectRequestMessage:
        return {"type": "http.request", "body": b"", "more_body": False}
    return Request(scope, receive=_receive) # type: ignore

def _parse_snapshot_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════════════
# Worker Messages — cross-worker request forwarding
# ══════════════════════════════════════════════════════════════════════════════
# region worker message
@dataclass(kw_only=True)
class WorkerMessage(ABC):
    event: str
    '''Event type. For redirects, the requesting worker sends the request to the target worker.'''
    sender: int
    '''Sender PID.'''
    time: datetime = field(default_factory=datetime.now)

    def dump(self) -> bytes:
        data = pickle.dumps(self)
        return struct.pack('!I', len(data)) + data

    @abstractmethod
    async def handle(self, app: FastAPI) -> object:
        raise NotImplementedError

@dataclass(kw_only=True)
class WorkerRedirectMessage(WorkerMessage):
    event: Literal['redirect'] = 'redirect'
    path: str
    '''Target path, e.g. "/api/v1/xxx".'''
    method: str
    '''HTTP method, e.g. "GET", "POST".'''
    request_params: dict[str, object]
    '''Parameters for the target endpoint handler.'''
    headers: list[tuple[str, str]] = field(default_factory=list)

    @dataclass
    class RedirectResult:
        result: object | None = None
        error: BaseException | None = None

    async def handle(self, app: FastAPI) -> "RedirectResult":
        scope = {
            "type": "http",
            "path": self.path,
            "method": self.method.upper(),
        }
        for route in app.routes:
            match, child_scope = route.matches(scope)
            if match == Match.FULL and isinstance(route, Route):
                endpoint = route.endpoint
                raw_params = dict(self.request_params)
                # Try cache first
                from core.server.route import _ENDPOINT_CACHE, _callable_cache_ids
                cached = None
                for endpoint_id in _callable_cache_ids(endpoint):
                    cached = _ENDPOINT_CACHE.get(endpoint_id)
                    if cached is not None:
                        break
                if cached is not None:
                    resolved_type_hints = cached.type_hints
                    signature = cached.signature
                else:
                    try:
                        resolved_type_hints = get_type_hints(endpoint, globalns=getattr(endpoint, '__globals__', {}))
                    except Exception:
                        resolved_type_hints = {}
                    signature = inspect.signature(endpoint)
                # Extract path parameters (e.g. user_id from /users/{user_id})
                if "path_params" in child_scope:
                    path_params = child_scope["path_params"]
                    if isinstance(path_params, dict):
                        raw_params.update({str(key): value for key, value in path_params.items()})
                try:
                    params: dict[str, object] = {}
                    for name, parameter in signature.parameters.items():
                        annotation = resolved_type_hints.get(name, parameter.annotation)
                        if name in raw_params:
                            value = raw_params[name]
                            if _is_pydantic_model(annotation) and isinstance(value, dict):
                                value = annotation.model_validate(value)
                            params[name] = value
                            continue
                        if _is_request_annotation(annotation):
                            params[name] = _build_redirect_request(self.path, self.method, self.headers)
                            continue
                        if _is_pydantic_model(annotation):
                            params[name] = annotation.model_validate(raw_params)
                            continue
                        if parameter.default is inspect._empty:
                            raise TypeError(f"Missing required redirect parameter: {name}")

                        # Resolve FastAPI parameter defaults (Query, Path, Body, etc.)
                        default = parameter.default
                        if hasattr(default, 'default'):
                            # FieldInfo objects (from Query(), Path(), etc.) have a .default attr
                            params[name] = default.default
                        else:
                            params[name] = default

                    result = endpoint(**params)
                    if inspect.isawaitable(result):
                        result = await result
                    return self.RedirectResult(result=result)

                except BaseException as e:
                    return self.RedirectResult(result=None, error=e)
        raise ValueError(f"No matching route found for {self.method} {self.path}")

@dataclass(kw_only=True)
class WorkerRedirectStreamStart:
    status_code: int = 200
    media_type: str | None = None
    headers: list[tuple[str, str]] = field(default_factory=list)

@dataclass(kw_only=True)
class WorkerRedirectStreamChunk:
    data: bytes

@dataclass(kw_only=True)
class WorkerRedirectStreamEnd:
    error: str | None = None

@dataclass(kw_only=True)
class WorkerAIServiceReloadMessage(WorkerMessage):
    event: Literal['ai-services-reload'] = 'ai-services-reload'
    serialized_config: str | None
    version: int
    service_kinds: list[AIServiceKind]
    reason: str | None = None

    async def handle(self, app: FastAPI) -> AIServiceRuntimeUpdateResult:
        from .routes.ai_services.panel import apply_ai_services_runtime_update
        result = apply_ai_services_runtime_update(
            serialized_config=self.serialized_config,
            service_kinds=self.service_kinds,
            version=self.version,
            reason=self.reason,
        )

        if inspect.isawaitable(result):
            result = await result
        return cast(AIServiceRuntimeUpdateResult, result)

@dataclass(kw_only=True)
class WorkerAIServiceClientValueMessage(WorkerMessage):
    event: Literal['ai-service-client-value'] = 'ai-service-client-value'
    service_type: str
    service_key: str
    client_key: str
    update_max_concurrent: bool = False
    max_concurrent: int | None = None
    update_priority: bool = False
    priority: float | None = None
    update_strategy_lvl: bool = False
    strategy_lvl: int | None = None

    async def handle(self, app: FastAPI) -> dict[str, object]:
        from .routes.ai_services.panel import apply_ai_service_client_value_update
        result = await apply_ai_service_client_value_update(
            service_type=self.service_type,
            service_key=self.service_key,
            client_key=self.client_key,
            update_max_concurrent=self.update_max_concurrent,
            max_concurrent=self.max_concurrent,
            update_priority=self.update_priority,
            priority=self.priority,
            update_strategy_lvl=self.update_strategy_lvl,
            strategy_lvl=self.strategy_lvl,
        )
        return result.model_dump(mode='python')


@dataclass(kw_only=True)
class WorkerStorageBootstrapMessage(WorkerMessage):
    event: Literal['storage-bootstrap'] = 'storage-bootstrap'
    storage_kind: Literal['orm', 'vector']
    client_name: str
    collection: str
    model_module: str | None = None
    model_name: str | None = None

    async def handle(self, app: FastAPI) -> dict[str, object]:
        from .storage_utils import apply_runtime_storage_bootstrap
        return await apply_runtime_storage_bootstrap(
            storage_kind=self.storage_kind,
            client_name=self.client_name,
            collection=self.collection,
            model_module=self.model_module,
            model_name=self.model_name,
        )

@dataclass(kw_only=True)
class WorkerStorageForgetMessage(WorkerMessage):
    event: Literal['storage-forget'] = 'storage-forget'
    storage_kind: Literal['orm', 'vector']
    client_name: str
    collection: str

    async def handle(self, app: FastAPI) -> dict[str, object]:
        from .storage_utils import apply_runtime_storage_forget
        return await apply_runtime_storage_forget(
            storage_kind=self.storage_kind,
            client_name=self.client_name,
            collection=self.collection,
        )

# endregion

# ══════════════════════════════════════════════════════════════════════════════
# WorkerInfo
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkerInfo:
    pid: int = field(default_factory=os.getpid)
    '''Worker process PID.'''
    generation: int = 1
    '''Worker generation. Incremented when a PID identity is reused after death.'''
    shm_slot: int | None = None
    '''SharedMemory slot index for this worker.'''
    shm_name: str | None = None
    '''SharedMemory block name owned by the shared manager.'''
    shared_manager_pid: int | None = None
    '''PID of the manager process that owns the worker SharedMemory block.'''
    msg_port: int = field(default_factory=_find_available_port)
    '''Port for IPC message communication.'''
    started_at: str | None = None
    '''Worker startup timestamp.'''
    request_count: int = 0
    '''Total requests handled by this worker.'''
    last_request_at: str | None = None
    '''Timestamp of the last request handled.'''
    status: WorkerRuntimeStatus = "starting"
    '''Current worker status.'''
    lifespan_ready: bool = False
    '''True when lifespan startup is complete; triggers the ready banner.'''
    dead: bool = False
    '''True if the manager sweep marked this worker generation dead.'''

    @property
    def identity(self) -> tuple[int, int]:
        return (self.pid, self.generation)

    def get_client_lock(self) -> asyncio.Lock:
        '''Get or create the asyncio lock for IPC socket access to this worker.'''
        lock = _other_worker_socket_locks.get(self.identity)
        if lock is None:
            lock = asyncio.Lock()
            _other_worker_socket_locks[self.identity] = lock
        return lock
    
    async def get_client(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        '''Get or establish a TCP connection to this worker for IPC.'''
        client = _other_worker_sockets.get(self.identity)
        if client is not None:
            _, writer = client
            if not writer.is_closing():
                return client
        reader, writer = await asyncio.open_connection('127.0.0.1', self.msg_port)
        _other_worker_sockets[self.identity] = (reader, writer)
        return reader, writer

# ══════════════════════════════════════════════════════════════════════════════
# CacheEntry (process-local, used by AppSharedData)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CacheEntry:
    value: object
    expires_at: float
    created_at: float = field(default_factory=time.time)

    def is_expired(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self.expires_at <= now

# ══════════════════════════════════════════════════════════════════════════════
# AppSharedData — cross-process shared singleton
# ══════════════════════════════════════════════════════════════════════════════

class AppSharedData(CrossProcessSharedObject):
    '''
    Cross-process shared state holder. Lives in the main process;
    worker processes access it via a proxy over IPC.
    Inherits from ``CrossProcessSharedObject`` for concurrency safety.
    '''

    if TYPE_CHECKING:
        workers: dict[int, WorkerInfo]
        worker_generations: dict[int, int]
        room_worker_map: dict[str, int]  # {room_id: worker_pid}
        ai_services_config_json: str | None
        ai_services_config_version: int
        ai_services_config_updated_at: str | None
        ai_services_reload_state: dict[int, AIServiceReloadStateRow]
        instance_uuid: str
        server_start_time: str | None
        cache_scope: CacheScope

    def __init__(self, id: str, /):
        # ``id`` is required by CrossProcessSharedObject but unused here.
        self.workers: dict[int, WorkerInfo] = {}
        self.worker_generations: dict[int, int] = {}
        self.room_worker_map: dict[str, int] = {}
        self.ai_services_config_json: str | None = None
        self.ai_services_config_version: int = 0
        self.ai_services_config_updated_at: str | None = None
        self.ai_services_reload_state: dict[int, AIServiceReloadStateRow] = {}
        self.instance_uuid = os.getenv("__SERVER_INSTANCE_ID__") or str(uuid.uuid4())
        os.environ.setdefault("__SERVER_INSTANCE_ID__", self.instance_uuid)
        self.server_start_time = os.getenv("__SERVER_START_TIME__")
        self.cache_scope: CacheScope = "cross-process"
        self._cache: dict[str, CacheEntry] = {}
        self._latest_system_snapshot: SystemSnapshotPayload | None = None
        self._system_snapshot_history: list[SystemSnapshotPayload] = []
        self._process_snapshot: ProcessSnapshotPayload | None = None
        self._port_snapshot: PortSnapshotPayload | None = None
        self._shared_dicts: dict[str, dict[str, object]] = {}
        self._worker_runtime_lock = threading.RLock()
        self._worker_shm_slots = _expected_worker_slots()
        self._worker_shm_name = _worker_shm_name_for_manager(os.getpid())
        self._worker_shm = self._create_worker_shm()

    def _create_worker_shm(self) -> shared_memory.SharedMemory:
        size = self._worker_shm_slots * _WORKER_SHM_SLOT_SIZE
        try:
            shm = shared_memory.SharedMemory(name=self._worker_shm_name, create=True, size=size)
        except FileExistsError:
            shm = shared_memory.SharedMemory(name=self._worker_shm_name)
            if shm.size < size:
                shm.close()
                raise RuntimeError(
                    f"Existing worker SharedMemory {self._worker_shm_name!r} is too small: {shm.size} < {size}"
                )
        shm.buf[:size] = b"\x00" * size
        atexit.register(self._cleanup_worker_shm)
        return shm

    def _cleanup_worker_shm(self) -> None:
        try:
            self._worker_shm.close()
        except Exception:
            pass
        try:
            self._worker_shm.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def _ensure_worker_runtime_storage(self) -> None:
        if not hasattr(self, "worker_generations"):
            self.worker_generations = {
                int(pid): max(1, int(getattr(info, "generation", 1)))
                for pid, info in getattr(self, "workers", {}).items()
            }
        if not hasattr(self, "_worker_shm_slots"):
            self._worker_shm_slots = _expected_worker_slots()
        if not hasattr(self, "_worker_shm_name"):
            self._worker_shm_name = _worker_shm_name_for_manager(os.getpid())
        if not hasattr(self, "_worker_shm"):
            self._worker_shm = self._create_worker_shm()
        if not hasattr(self, "_worker_runtime_lock"):
            self._worker_runtime_lock = threading.RLock()

    # ---- Worker management ----
    def _slot_is_dead(self, slot: int, now_monotonic: int | None = None) -> bool:
        row = _read_worker_slot(self._worker_shm.buf, slot)
        status = row["status"]
        alive_at = int(row["alive_at_monotonic"])
        if int(row["pid"]) <= 0:
            return True
        if status == "dead":
            return True
        if alive_at <= 0:
            return False
        now = _monotonic_seconds_int() if now_monotonic is None else now_monotonic
        return now - alive_at > _WORKER_SHM_DEAD_AFTER_SECONDS

    def _worker_info_from_slot(self, info: WorkerInfo) -> WorkerInfo:
        if info.shm_slot is None:
            return info
        row = _read_worker_slot(self._worker_shm.buf, info.shm_slot)
        if int(row["pid"]) != info.pid or int(row["generation"]) != info.generation:
            info.dead = True
            info.status = "dead"
            return info
        info.msg_port = int(row["msg_port"])
        info.request_count = int(row["request_count"])
        info.last_request_at = _iso_from_time_ns(int(row["last_request_at_ns"]))
        info.lifespan_ready = bool(row["lifespan_ready"])
        info.status = cast(WorkerRuntimeStatus, row["status"])
        if self._slot_is_dead(info.shm_slot):
            info.dead = True
            info.status = "dead"
            _pack_worker_slot(
                self._worker_shm.buf,
                info.shm_slot,
                pid=info.pid,
                generation=info.generation,
                request_count=info.request_count,
                last_request_at_ns=int(row["last_request_at_ns"]),
                alive_at_monotonic=int(row["alive_at_monotonic"]),
                msg_port=info.msg_port,
                lifespan_ready=info.lifespan_ready,
                status="dead",
            )
        else:
            info.dead = False
        return info

    def _invalidate_worker_client_cache(self, pid: int, generation: int | None = None) -> None:
        with _worker_info_cache_lock:
            if generation is None:
                _worker_info_cache.pop(pid, None)
            else:
                cached = _worker_info_cache.get(pid)
                if cached is not None and cached[0] == generation:
                    _worker_info_cache.pop(pid, None)
        keys = [
            key for key in _other_worker_sockets
            if key[0] == pid and (generation is None or key[1] == generation)
        ]
        for key in keys:
            _, writer = _other_worker_sockets.pop(key)
            try:
                writer.close()
            except Exception:
                pass
        for key in list(_other_worker_socket_locks):
            if key[0] == pid and (generation is None or key[1] == generation):
                _other_worker_socket_locks.pop(key, None)

    def _cleanup_dead_worker(self, pid: int, info: WorkerInfo) -> None:
        self.cleanup_worker_rooms(pid)
        self._invalidate_worker_client_cache(pid, info.generation)

    def sweep_dead_workers(self) -> int:
        self._ensure_worker_runtime_storage()
        with self._worker_runtime_lock:
            now = _monotonic_seconds_int()
            swept = 0
            for pid, info in list(self.workers.items()):
                if info.shm_slot is None:
                    continue
                row = _read_worker_slot(self._worker_shm.buf, info.shm_slot)
                startup_timed_out = False
                if int(row["alive_at_monotonic"]) <= 0 and info.started_at:
                    try:
                        started_at = datetime.fromisoformat(info.started_at)
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone.utc)
                        startup_timed_out = (datetime.now(timezone.utc) - started_at.astimezone(timezone.utc)).total_seconds() > _WORKER_SHM_DEAD_AFTER_SECONDS
                    except Exception:
                        startup_timed_out = False
                if not startup_timed_out and not self._slot_is_dead(info.shm_slot, now):
                    continue
                info.dead = True
                info.status = "dead"
                info.lifespan_ready = False
                _pack_worker_slot(
                    self._worker_shm.buf,
                    info.shm_slot,
                    pid=info.pid,
                    generation=info.generation,
                    request_count=int(row["request_count"]),
                    last_request_at_ns=int(row["last_request_at_ns"]),
                    alive_at_monotonic=int(row["alive_at_monotonic"]),
                    msg_port=int(row["msg_port"]),
                    lifespan_ready=False,
                    status="dead",
                )
                self._cleanup_dead_worker(pid, info)
                swept += 1
            return swept

    def _find_free_worker_slot(self, existing_slot: int | None = None) -> int:
        if existing_slot is not None and 0 <= existing_slot < self._worker_shm_slots:
            return existing_slot
        occupied = {
            info.shm_slot
            for info in self.workers.values()
            if info.shm_slot is not None and not info.dead
        }
        for slot in range(self._worker_shm_slots):
            if slot in occupied:
                continue
            row = _read_worker_slot(self._worker_shm.buf, slot)
            if int(row["pid"]) <= 0 or int(row["alive_at_monotonic"]) <= 0:
                return slot
        now = _monotonic_seconds_int()
        for slot in range(self._worker_shm_slots):
            if slot in occupied:
                continue
            if self._slot_is_dead(slot, now):
                return slot
        raise RuntimeError(f"No worker SharedMemory slot available ({self._worker_shm_slots} slots)")

    def register_worker(self, pid: int, msg_port: int | None = None) -> WorkerInfo:
        self._ensure_worker_runtime_storage()
        with self._worker_runtime_lock:
            self.sweep_dead_workers()
            info = self.workers.get(pid)
            if info is None:
                generation = int(self.worker_generations.get(pid, 0)) + 1
                self.worker_generations[pid] = generation
                reserved_ports = {worker.msg_port for worker in self.workers.values() if not worker.dead}
                slot = self._find_free_worker_slot()
                info = WorkerInfo(
                    pid=pid,
                    generation=generation,
                    shm_slot=slot,
                    shm_name=self._worker_shm_name,
                    shared_manager_pid=os.getpid(),
                    msg_port=_allocate_worker_msg_port(reserved_ports, preferred_port=msg_port),
                    started_at=datetime.now(timezone.utc).isoformat(),
                    status="starting",
                )
                self.workers[pid] = info
            elif info.dead:
                self._cleanup_dead_worker(pid, info)
                old_generation = info.generation
                generation = max(int(self.worker_generations.get(pid, old_generation)), old_generation) + 1
                self.worker_generations[pid] = generation
                reserved_ports = {
                    worker.msg_port
                    for worker_pid, worker in self.workers.items()
                    if worker_pid != pid and not worker.dead
                }
                info.generation = generation
                info.shm_slot = self._find_free_worker_slot(info.shm_slot)
                info.shm_name = self._worker_shm_name
                info.shared_manager_pid = os.getpid()
                info.msg_port = _allocate_worker_msg_port(reserved_ports, preferred_port=msg_port)
                info.started_at = datetime.now(timezone.utc).isoformat()
                info.request_count = 0
                info.last_request_at = None
                info.lifespan_ready = False
                info.dead = False
                info.status = "starting"
                self._invalidate_worker_client_cache(pid, old_generation)
            elif msg_port is not None:
                info.msg_port = msg_port
            if info.started_at is None:
                info.started_at = datetime.now(timezone.utc).isoformat()
            if info.shm_slot is None:
                info.shm_slot = self._find_free_worker_slot()
            info.shm_name = self._worker_shm_name
            info.shared_manager_pid = os.getpid()
            info.dead = False
            existing_row = _read_worker_slot(self._worker_shm.buf, info.shm_slot)
            preserve_existing = (
                int(existing_row["pid"]) == info.pid
                and int(existing_row["generation"]) == info.generation
            )
            _pack_worker_slot(
                self._worker_shm.buf,
                info.shm_slot,
                pid=info.pid,
                generation=info.generation,
                request_count=int(existing_row["request_count"]) if preserve_existing else info.request_count,
                last_request_at_ns=int(existing_row["last_request_at_ns"]) if preserve_existing else 0,
                alive_at_monotonic=int(existing_row["alive_at_monotonic"]) if preserve_existing else 0,
                msg_port=info.msg_port,
                lifespan_ready=bool(existing_row["lifespan_ready"]) if preserve_existing else info.lifespan_ready,
                status=info.status,
            )
            return info
    
    def reallocate_worker_msg_port(self, pid: int, preferred_port: int | None = None) -> WorkerInfo:
        self._ensure_worker_runtime_storage()
        with self._worker_runtime_lock:
            info = self.register_worker(pid=pid)
            reserved_ports = {
                worker.msg_port
                for worker_pid, worker in self.workers.items()
                if worker_pid != pid and not worker.dead
            }
            info.msg_port = _allocate_worker_msg_port(reserved_ports, preferred_port=preferred_port)
            if info.shm_slot is not None:
                row = _read_worker_slot(self._worker_shm.buf, info.shm_slot)
                _pack_worker_slot(
                    self._worker_shm.buf,
                    info.shm_slot,
                    pid=info.pid,
                    generation=info.generation,
                    request_count=int(row["request_count"]),
                    last_request_at_ns=int(row["last_request_at_ns"]),
                    alive_at_monotonic=int(row["alive_at_monotonic"]),
                    msg_port=info.msg_port,
                    lifespan_ready=bool(row["lifespan_ready"]),
                    status=cast(WorkerRuntimeStatus, row["status"]),
                )
            self._invalidate_worker_client_cache(pid, info.generation)
            return info

    def count_ready_workers(self) -> int:
        """Return how many registered workers reported lifespan startup complete."""
        self._ensure_worker_runtime_storage()
        with self._worker_runtime_lock:
            self.sweep_dead_workers()
            count = 0
            for info in self.workers.values():
                if info.shm_slot is None:
                    continue
                row = _read_worker_slot(self._worker_shm.buf, info.shm_slot)
                if (
                    int(row["pid"]) == info.pid
                    and int(row["generation"]) == info.generation
                    and bool(row["lifespan_ready"])
                    and row["status"] != "dead"
                ):
                    count += 1
            return count

    def get_workers_snapshot(self, include_dead: bool = False) -> list[WorkerSnapshot]:
        self._ensure_worker_runtime_storage()
        with self._worker_runtime_lock:
            self.sweep_dead_workers()
            rows: list[WorkerSnapshot] = []
            for pid, info in sorted(self.workers.items(), key=lambda item: item[0]):
                info = self._worker_info_from_slot(info)
                if info.dead and not include_dead:
                    continue
                rows.append({
                    "pid": pid,
                    "generation": info.generation,
                    "shm_slot": info.shm_slot,
                    "msg_port": info.msg_port,
                    "started_at": info.started_at,
                    "request_count": info.request_count,
                    "last_request_at": info.last_request_at,
                    "status": info.status,
                    "lifespan_ready": info.lifespan_ready,
                    "dead": info.dead,
                })
            return rows

    def get_worker(self, pid: int) -> WorkerInfo:
        self._ensure_worker_runtime_storage()
        with self._worker_runtime_lock:
            self.sweep_dead_workers()
            info = self.workers.get(pid)
            if info is None or info.dead:
                raise ValueError(f"Worker with pid {pid} not found")
            info = self._worker_info_from_slot(info)
            if info.dead:
                raise ValueError(f"Worker with pid {pid} not found")
            return info

    def get_worker_shm_meta(self) -> dict[str, int | str]:
        return {
            "name": self._worker_shm_name,
            "manager_pid": os.getpid(),
            "slot_size": _WORKER_SHM_SLOT_SIZE,
            "slots": self._worker_shm_slots,
        }

    # ---- WebRTC room-to-worker mapping ----
    def update_room_worker(self, room_id: str, worker_pid: int) -> None:
        '''Map a room to the worker handling it.'''
        try:
            self.get_worker(worker_pid)
        except Exception as exc:
            raise ValueError(f"Cannot map room {room_id} to dead worker {worker_pid}") from exc
        self.room_worker_map[room_id] = worker_pid

    def delete_room_worker(self, room_id: str) -> int | None:
        '''Remove the room-to-worker mapping.'''
        return self.room_worker_map.pop(room_id, None)

    def get_room_worker(self, room_id: str) -> int | None:
        '''Get the worker PID assigned to a room.'''
        worker_pid = self.room_worker_map.get(room_id)
        if worker_pid is None:
            return None
        try:
            self.get_worker(worker_pid)
        except Exception:
            self.room_worker_map.pop(room_id, None)
            return None
        return worker_pid

    def cleanup_worker_rooms(self, worker_pid: int) -> int:
        '''Remove all room mappings owned by a worker.'''
        room_ids = [room_id for room_id, pid in self.room_worker_map.items() if pid == worker_pid]
        for room_id in room_ids:
            self.room_worker_map.pop(room_id, None)
        return len(room_ids)

    def get_all_room_info(self) -> list[RoomInfo]:
        '''Return a list of all room info entries.'''
        self.sweep_dead_workers()
        infos: list[RoomInfo] = []
        for room_id, worker_id in list(self.room_worker_map.items()):
            try:
                self.get_worker(worker_id)
            except Exception:
                self.room_worker_map.pop(room_id, None)
                continue
            infos.append(RoomInfo(id=room_id, worker=worker_id))
        return infos

    def worker_running_room_count(self, worker_pid: int) -> int:
        '''Count how many rooms are running on a given worker.'''
        count = 0
        for wid in self.room_worker_map.values():
            if wid == worker_pid:
                count += 1
        return count

    def pick_least_room_running_worker(self, prefer_pid: int | None = None) -> int | None:
        '''Pick the worker with the fewest rooms; fallback to prefer_pid if all equal.'''
        workers = self.get_workers_snapshot()
        if not workers:
            return prefer_pid
        min_count: int | None = None
        candidates: list[int] = []
        for worker in workers:
            pid = worker["pid"]
            room_count = self.worker_running_room_count(pid)
            if min_count is None or room_count < min_count:
                min_count = room_count
                candidates = [pid]
            elif room_count == min_count:
                candidates.append(pid)
        if prefer_pid is not None and prefer_pid in candidates:
            return prefer_pid
        return candidates[0] if candidates else prefer_pid

    # ---- Exam task/session worker mapping ----
    def set_ai_services_config(self, serialized_config: str | None, *, version: int | None = None) -> AIServiceConfigSnapshot:
        next_version = int(version) if version is not None else (int(self.ai_services_config_version) + 1)
        self.ai_services_config_json = serialized_config
        self.ai_services_config_version = next_version
        self.ai_services_config_updated_at = datetime.now(timezone.utc).isoformat()
        return self.get_ai_services_config()

    def get_ai_services_config(self) -> AIServiceConfigSnapshot:
        return {
            'serialized_config': self.ai_services_config_json,
            'version': int(self.ai_services_config_version),
            'updated_at': self.ai_services_config_updated_at,
        }

    def clear_ai_services_reload_state(self) -> None:
        self.ai_services_reload_state = {}

    def update_ai_services_reload_state(
        self,
        *,
        pid: int,
        version: int,
        state: AIServiceReloadStatus,
        service_kinds: list[AIServiceKind],
        error: str | None = None,
    ) -> AIServiceReloadStateRow:
        row = {
            'pid': int(pid),
            'version': int(version),
            'state': str(state),
            'service_kinds': list(service_kinds),
            'error': error,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        self.ai_services_reload_state[int(pid)] = row   # type: ignore[list-item]
        return row  # type: ignore

    def get_ai_services_reload_state(self) -> list[AIServiceReloadStateRow]:
        return [
            dict(self.ai_services_reload_state[pid])
            for pid in sorted(self.ai_services_reload_state)
        ]   # type: ignore

    # ---- Lightweight cache helpers ----
    @overload
    def get_cache(self, key: str) -> object | None: ...
    @overload
    def get_cache(self, key: str, default: TCacheDefault) -> object | TCacheDefault: ...

    def get_cache(self, key: str, default: TCacheDefault | None = None) -> object | TCacheDefault | None:
        now = time.time()
        entry = self._cache.get(key)
        if entry is None:
            return default
        if entry.is_expired(now):
            self._cache.pop(key, None)
            return default
        return entry.value

    def set_cache(self, key: str, value: TCacheValue, ttl_seconds: float) -> TCacheValue:
        expires_at = time.time() + max(float(ttl_seconds), 0.0)
        self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
        return value

    def invalidate_cache(self, prefix: str | None = None) -> int:
        if prefix is None:
            count = len(self._cache)
            self._cache.clear()
            return count
        keys = [key for key in self._cache if key.startswith(prefix)]
        for key in keys:
            self._cache.pop(key, None)
        return len(keys)

    def cleanup_expired_cache(self) -> int:
        now = time.time()
        keys = [key for key, entry in self._cache.items() if entry.is_expired(now)]
        for key in keys:
            self._cache.pop(key, None)
        return len(keys)

    # ---- Shared system snapshot helpers ----
    def push_system_snapshot(self, snapshot: SystemSnapshotPayload, *, max_items: int = 1800) -> None:
        row = cast(SystemSnapshotPayload, dict(snapshot))
        timestamp = row.get("timestamp")
        self._latest_system_snapshot = row
        if self._system_snapshot_history and self._system_snapshot_history[-1].get("timestamp") == timestamp:
            self._system_snapshot_history[-1] = row
        else:
            self._system_snapshot_history.append(row)
        keep = max(1, int(max_items or 1))
        overflow = len(self._system_snapshot_history) - keep
        if overflow > 0:
            del self._system_snapshot_history[:overflow]

    def get_latest_system_snapshot(self) -> SystemSnapshotPayload | None:
        return self._latest_system_snapshot

    def get_system_snapshot_history(self, seconds: int | None = None) -> list[SystemSnapshotPayload]:
        rows = list(self._system_snapshot_history)
        if not rows or seconds is None:
            return rows
        window_seconds = max(0, int(seconds))
        if window_seconds <= 0:
            return rows
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        out: list[SystemSnapshotPayload] = []
        for row in reversed(rows):
            row_time = _parse_snapshot_time(row.get("timestamp"))
            if row_time is None:
                continue
            if row_time < cutoff:
                break
            out.append(row)
        out.reverse()
        return out

    # ---- Shared process / port snapshots ----
    def set_process_snapshot(self, snapshot: ProcessSnapshotPayload | None) -> None:
        self._process_snapshot = dict(snapshot or {}) if snapshot is not None else None

    def get_process_snapshot(self) -> ProcessSnapshotPayload | None:
        return self._process_snapshot

    def set_port_snapshot(self, snapshot: PortSnapshotPayload | None) -> None:
        self._port_snapshot = dict(snapshot or {}) if snapshot is not None else None

    def get_port_snapshot(self) -> PortSnapshotPayload | None:
        return self._port_snapshot

    # shared dict helpers
    def get_shared_dict(self, name: str) -> dict[str, object]:
        d = self._shared_dicts.get(name)
        if d is None:
            d = {}
            self._shared_dicts[name] = d
        return d

    def get_shared_dict_value(self, name: str, key: str) -> object | None:
        return self.get_shared_dict(name).get(key)

    def set_shared_dict_value(self, name: str, key: str, value: object) -> object:
        self.get_shared_dict(name)[key] = value
        return value

    def delete_shared_dict_value(self, name: str, key: str) -> object | None:
        return self.get_shared_dict(name).pop(key, None)

    def has_shared_dict_key(self, name: str, key: str) -> bool:
        return key in self.get_shared_dict(name)

    def clear_shared_dict(self, name: str) -> None:
        self.get_shared_dict(name).clear()

    # global shared dict helpers
    def get_global_shared_dict_entry(self, namespace: str, key: str) -> dict[str, object] | None:
        value = self.get_shared_dict_value(f"__global_shared_dict__:{namespace}", key)
        return dict(value) if isinstance(value, dict) else None

    def set_global_shared_dict_entry(self, namespace: str, key: str, entry: dict[str, object]) -> None:
        self.set_shared_dict_value(f"__global_shared_dict__:{namespace}", key, dict(entry))

    def delete_global_shared_dict_entry(self, namespace: str, key: str, entry: dict[str, object]) -> dict[str, object] | None:
        old = self.get_global_shared_dict_entry(namespace, key)
        self.set_global_shared_dict_entry(namespace, key, entry)
        return old

    def merge_global_shared_dict_entry(self, namespace: str, key: str, entry: dict[str, object]) -> bool:
        current = self.get_global_shared_dict_entry(namespace, key)
        if current is None or float(entry.get("ts", 0.0) or 0.0) > float(current.get("ts", 0.0) or 0.0):
            self.set_global_shared_dict_entry(namespace, key, entry)
            return True
        return False

    def get_global_shared_dict_namespace(self, namespace: str) -> dict[str, dict[str, object]]:
        rows: dict[str, dict[str, object]] = {}
        for key, value in self.get_shared_dict(f"__global_shared_dict__:{namespace}").items():
            if isinstance(value, dict):
                rows[str(key)] = dict(value)
        return rows

    def get_global_shared_dict_all_namespaces(self) -> dict[str, dict[str, dict[str, object]]]:
        prefix = "__global_shared_dict__:"
        rows: dict[str, dict[str, dict[str, object]]] = {}
        for name in list(self._shared_dicts):
            if not name.startswith(prefix):
                continue
            rows[name[len(prefix):]] = self.get_global_shared_dict_namespace(name[len(prefix):])
        return rows

    def merge_global_shared_dict_state(self, data: dict[str, dict[str, dict[str, object]]]) -> int:
        merged = 0
        for namespace, values in data.items():
            if not isinstance(values, dict):
                continue
            for key, entry in values.items():
                if isinstance(entry, dict) and self.merge_global_shared_dict_entry(str(namespace), str(key), entry):
                    merged += 1
        return merged

    def get_global_shared_dict_port(self) -> int:
        namespace = "__distributed_services__"
        existing = self.get_shared_dict_value(namespace, "gsd_port")
        if isinstance(existing, int) and existing > 0:
            return existing
        port = _find_available_port()
        self.set_shared_dict_value(namespace, "gsd_port", port)
        return port

    def get_runtime_meta(self) -> RuntimeMeta:
        self.cleanup_expired_cache()
        workers = self.get_workers_snapshot()
        return {
            "instance_uuid": self.instance_uuid,
            "server_start_time": self.server_start_time,
            "shared_manager_pid": os.getpid(),
            "cache_scope": self.cache_scope,
            "worker_count": len(workers),
            "request_count_total": sum(worker["request_count"] for worker in workers),
            "workers": workers,
            "supervisor_pid": int(os.getenv("__SERVER_SUPERVISOR_PID__", "0") or 0) or None,
            "control_mode": os.getenv("__SERVER_CONTROL_MODE__") or None,
            "control_supported": os.getenv("__SERVER_CONTROL_SUPPORTED__", "0").strip() in ("1", "true", "yes"),
            "config_file_path": os.getenv("__CONFIG_FILE_PATH__") or None,
        }

    # ---- Singleton accessor ----
    @classmethod
    def Get(cls) -> Self:
        if '__singleton__' not in cls.__dict__:
            from core.server.data_types.config import Config
            config = Config.GetConfig()
            id = f'{config.server_config.get_host()}:{config.server_config.port}'
            cls.__singleton__ = cls(id)
        return cls.__singleton__

def configure_current_worker_runtime(info: WorkerInfo) -> None:
    """Persist worker SharedMemory metadata into process-local environment."""
    if info.shm_slot is None or info.shared_manager_pid is None:
        return
    shm_name = info.shm_name or _worker_shm_name_for_manager(info.shared_manager_pid)
    os.environ[_WORKER_SHM_NAME_ENV] = shm_name
    os.environ[_WORKER_SHM_SLOT_ENV] = str(info.shm_slot)
    os.environ[_WORKER_GENERATION_ENV] = str(info.generation)
    os.environ[_WORKER_MANAGER_PID_ENV] = str(info.shared_manager_pid)
    _connect_worker_shm(shm_name)

def _current_worker_slot() -> int | None:
    value = os.getenv(_WORKER_SHM_SLOT_ENV)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None

def _current_worker_generation() -> int:
    try:
        return int(os.getenv(_WORKER_GENERATION_ENV) or "0")
    except ValueError:
        return 0

def _write_current_worker_slot(
    *,
    request_delta: int = 0,
    last_request_at_ns: int | None = None,
    alive_at_monotonic: int | None = None,
    lifespan_ready: bool | None = None,
    status: WorkerRuntimeStatus | None = None,
    msg_port: int | None = None,
) -> bool:
    slot = _current_worker_slot()
    generation = _current_worker_generation()
    if slot is None or generation <= 0:
        return False
    shm = _connect_worker_shm()
    if shm is None:
        return False
    with _worker_slot_write_lock:
        row = _read_worker_slot(shm.buf, slot)
        if int(row["pid"]) != os.getpid() or int(row["generation"]) != generation:
            return False
        _pack_worker_slot(
            shm.buf,
            slot,
            pid=os.getpid(),
            generation=generation,
            request_count=int(row["request_count"]) + max(0, int(request_delta)),
            last_request_at_ns=int(row["last_request_at_ns"]) if last_request_at_ns is None else max(0, int(last_request_at_ns)),
            alive_at_monotonic=int(row["alive_at_monotonic"]) if alive_at_monotonic is None else max(0, int(alive_at_monotonic)),
            msg_port=int(row["msg_port"]) if msg_port is None else max(0, int(msg_port)),
            lifespan_ready=bool(row["lifespan_ready"]) if lifespan_ready is None else lifespan_ready,
            status=cast(WorkerRuntimeStatus, row["status"]) if status is None else status,
        )
    return True

def write_current_worker_request() -> bool:
    """Update request count and last request timestamp for this worker without RPC."""
    return _write_current_worker_slot(
        request_delta=1,
        last_request_at_ns=time.time_ns(),
        status="running",
    )

def touch_current_worker_runtime(status: WorkerRuntimeStatus = "running") -> bool:
    """Update current worker runtime status without RPC."""
    return _write_current_worker_slot(status=status)

def mark_current_worker_lifespan_ready() -> bool:
    """Mark current worker lifespan ready without RPC."""
    return _write_current_worker_slot(lifespan_ready=True, status="running")

def update_current_worker_msg_port(msg_port: int) -> bool:
    """Update current worker message port in SharedMemory without RPC."""
    return _write_current_worker_slot(msg_port=msg_port)

def _heartbeat_worker(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            _write_current_worker_slot(
                alive_at_monotonic=_monotonic_seconds_int(),
                status="running",
            )
        except Exception:
            pass
        stop_event.wait(_WORKER_SHM_HEARTBEAT_INTERVAL_SECONDS)

def start_worker_heartbeat() -> None:
    """Start the daemon heartbeat thread for the current worker."""
    global _worker_heartbeat_stop, _worker_heartbeat_thread
    if _worker_heartbeat_thread is not None and _worker_heartbeat_thread.is_alive():
        return
    stop_event = threading.Event()
    thread = threading.Thread(target=_heartbeat_worker, args=(stop_event,), name="worker-shm-heartbeat", daemon=True)
    _worker_heartbeat_stop = stop_event
    _worker_heartbeat_thread = thread
    thread.start()

def stop_worker_heartbeat() -> None:
    """Stop the daemon heartbeat thread for the current worker."""
    global _worker_heartbeat_stop, _worker_heartbeat_thread
    if _worker_heartbeat_stop is not None:
        _worker_heartbeat_stop.set()
    if _worker_heartbeat_thread is not None and _worker_heartbeat_thread.is_alive():
        _worker_heartbeat_thread.join(timeout=1.0)
    _worker_heartbeat_stop = None
    _worker_heartbeat_thread = None
    try:
        _write_current_worker_slot(status="dead")
    except Exception:
        pass

def _worker_info_from_shared_row(
    *,
    pid: int,
    generation: int,
    shm_slot: int,
    manager_pid: int,
    shm_name: str,
    row: dict[str, int | bool | WorkerRuntimeStatus],
) -> WorkerInfo | None:
    if int(row["pid"]) != pid or int(row["generation"]) != generation:
        return None
    if row["status"] == "dead":
        return None
    alive_at = int(row["alive_at_monotonic"])
    dead = alive_at > 0 and _monotonic_seconds_int() - alive_at > _WORKER_SHM_DEAD_AFTER_SECONDS
    if dead:
        return None
    return WorkerInfo(
        pid=pid,
        generation=generation,
        shm_slot=shm_slot,
        shm_name=shm_name,
        shared_manager_pid=manager_pid,
        msg_port=int(row["msg_port"]),
        request_count=int(row["request_count"]),
        last_request_at=_iso_from_time_ns(int(row["last_request_at_ns"])),
        status=cast(WorkerRuntimeStatus, row["status"]),
        lifespan_ready=bool(row["lifespan_ready"]),
        dead=False,
    )

def get_worker_info(pid: int) -> WorkerInfo | None:
    """Return live worker info using one-time manager lookup plus SharedMemory reads."""
    with _worker_info_cache_lock:
        cached = _worker_info_cache.get(pid)
    if cached is None:
        try:
            info = AppSharedData.Get().get_worker(pid)
        except Exception:
            return None
        if info.shm_slot is None or info.shared_manager_pid is None:
            return info if not info.dead else None
        shm_name = info.shm_name or _worker_shm_name_for_manager(info.shared_manager_pid)
        cached = (info.generation, info.shm_slot, info.shared_manager_pid, shm_name)
        with _worker_info_cache_lock:
            _worker_info_cache[pid] = cached
    generation, shm_slot, manager_pid, shm_name = cached
    try:
        shm = _connect_worker_shm(shm_name)
        if shm is None:
            return None
        row = _read_worker_slot(shm.buf, shm_slot)
    except Exception:
        with _worker_info_cache_lock:
            _worker_info_cache.pop(pid, None)
        return None
    info = _worker_info_from_shared_row(
        pid=pid,
        generation=generation,
        shm_slot=shm_slot,
        manager_pid=manager_pid,
        shm_name=shm_name,
        row=row,
    )
    if info is not None:
        return info
    with _worker_info_cache_lock:
        _worker_info_cache.pop(pid, None)
    try:
        fresh = AppSharedData.Get().get_worker(pid)
    except Exception:
        return None
    if fresh.shm_slot is None or fresh.shared_manager_pid is None:
        return fresh if not fresh.dead else None
    fresh_name = fresh.shm_name or _worker_shm_name_for_manager(fresh.shared_manager_pid)
    with _worker_info_cache_lock:
        _worker_info_cache[pid] = (fresh.generation, fresh.shm_slot, fresh.shared_manager_pid, fresh_name)
    try:
        shm = _connect_worker_shm(fresh_name)
        if shm is None:
            return None
        row = _read_worker_slot(shm.buf, fresh.shm_slot)
    except Exception:
        return None
    return _worker_info_from_shared_row(
        pid=pid,
        generation=fresh.generation,
        shm_slot=fresh.shm_slot,
        manager_pid=fresh.shared_manager_pid,
        shm_name=fresh_name,
        row=row,
    )

def drop_worker_client_cache(pid: int, generation: int | None = None) -> None:
    """Drop process-local worker info/socket/lock caches."""
    with _worker_info_cache_lock:
        if generation is None:
            _worker_info_cache.pop(pid, None)
        else:
            cached = _worker_info_cache.get(pid)
            if cached is not None and cached[0] == generation:
                _worker_info_cache.pop(pid, None)
    for key in list(_other_worker_sockets):
        if key[0] != pid or (generation is not None and key[1] != generation):
            continue
        _, writer = _other_worker_sockets.pop(key)
        try:
            writer.close()
        except Exception:
            pass
    for key in list(_other_worker_socket_locks):
        if key[0] == pid and (generation is None or key[1] == generation):
            _other_worker_socket_locks.pop(key, None)

__all__ = [
    "AIServiceConfigSnapshot",
    "AIServiceReloadStateRow",
    "AIServiceRuntimeUpdateResult",
    "CacheEntry",
    "PortSnapshotPayload",
    "ProcessSnapshotPayload",
    "RuntimeMeta",
    "SystemSnapshotPayload",
    "WorkerInfo",
    "WorkerMessage",
    "WorkerRedirectMessage",
    "WorkerRedirectStreamStart",
    "WorkerRedirectStreamChunk",
    "WorkerRedirectStreamEnd",
    "WorkerAIServiceClientValueMessage",
    "WorkerStorageBootstrapMessage",
    "WorkerStorageForgetMessage",
    "WorkerSnapshot",
    "AppSharedData",
    "configure_current_worker_runtime",
    "drop_worker_client_cache",
    "get_worker_info",
    "mark_current_worker_lifespan_ready",
    "start_worker_heartbeat",
    "stop_worker_heartbeat",
    "touch_current_worker_runtime",
    "update_current_worker_msg_port",
    "write_current_worker_request",
]
