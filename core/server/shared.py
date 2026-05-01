# -*- coding: utf-8 -*-

"""

Shared state visible to all workers — ported from v2's ``shared.py``.



For multi-worker deployments ``AppSharedData`` inherits from

``CrossProcessSharedObject`` so that all state (workers, room-worker mapping,

cache, etc.) is transparently shared across processes via a manager.



Worker-to-worker communication (``WorkerMessage``, ``WorkerRedirectMessage``)

is also carried over from v2 to enable request forwarding across workers.

"""





import os

import time

import uuid

import socket

import pickle

import struct

import asyncio

import inspect

from typing import get_type_hints



from fastapi import FastAPI

from datetime import datetime, timedelta, timezone

from abc import ABC, abstractmethod

from dataclasses import dataclass, field

from pydantic import BaseModel

from starlette.requests import Request

from starlette.routing import Match, Route



from core.ai.shared import AIServiceKind
from core.storage.config import close_global_storage_clients

from starlette.types import Scope

from typing import TYPE_CHECKING, Self, Literal, NotRequired, TypeGuard, TypeVar, TypedDict, cast, overload



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



type WorkerRuntimeStatus = Literal["starting", "running"]

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

    msg_port: int

    started_at: str | None

    request_count: int

    last_request_at: str | None

    status: WorkerRuntimeStatus

    lifespan_ready: bool





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

    worker_pid: int

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



_other_worker_sockets: dict[int, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}

_other_worker_socket_locks: dict[int, asyncio.Lock] = {}





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



def _build_redirect_request(path: str, method: str) -> Request:

    scope = cast(Scope, {

        "type": "http",

        "asgi": {"version": "3.0", "spec_version": "2.3"},

        "http_version": "1.1",

        "method": method.upper(),

        "scheme": "http",

        "path": path,

        "raw_path": path.encode("utf-8"),

        "query_string": b"",

        "headers": [],

        "client": ("127.0.0.1", 0),

        "server": ("127.0.0.1", 0),

    })



    async def _receive() -> RedirectRequestMessage:

        return {"type": "http.request", "body": b"", "more_body": False}



    return Request(scope, receive=_receive)



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

                try:

                    resolved_type_hints = get_type_hints(endpoint, globalns=getattr(endpoint, '__globals__', {}))

                except Exception:

                    resolved_type_hints = {}

                # Extract path parameters (e.g. user_id from /users/{user_id})

                if "path_params" in child_scope:

                    path_params = child_scope["path_params"]

                    if isinstance(path_params, dict):

                        raw_params.update({str(key): value for key, value in path_params.items()})

                try:

                    params: dict[str, object] = {}

                    signature = inspect.signature(endpoint)

                    for name, parameter in signature.parameters.items():

                        annotation = resolved_type_hints.get(name, parameter.annotation)

                        if name in raw_params:

                            value = raw_params[name]

                            if _is_pydantic_model(annotation) and isinstance(value, dict):

                                value = annotation.model_validate(value)

                            params[name] = value

                            continue

                        if _is_request_annotation(annotation):

                            params[name] = _build_redirect_request(self.path, self.method)

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



    def get_client_lock(self) -> asyncio.Lock:

        '''Get or create the asyncio lock for IPC socket access to this worker.'''

        lock = _other_worker_socket_locks.get(self.pid)

        if lock is None:

            lock = asyncio.Lock()

            _other_worker_socket_locks[self.pid] = lock

        return lock

    

    async def get_client(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:

        '''Get or establish a TCP connection to this worker for IPC.'''

        client = _other_worker_sockets.get(self.pid)

        if client is not None:

            _, writer = client

            if not writer.is_closing():

                return client

        reader, writer = await asyncio.open_connection('127.0.0.1', self.msg_port)

        _other_worker_sockets[self.pid] = (reader, writer)

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

    

    # ---- Worker management ----



    def register_worker(self, pid: int, msg_port: int | None = None) -> WorkerInfo:

        info = self.workers.get(pid)

        if info is None:

            reserved_ports = {worker.msg_port for worker in self.workers.values()}

            info = WorkerInfo(

                pid=pid,

                msg_port=_allocate_worker_msg_port(reserved_ports, preferred_port=msg_port),

            )

            self.workers[pid] = info

        elif msg_port is not None:

            info.msg_port = msg_port

        if info.started_at is None:

            info.started_at = datetime.now(timezone.utc).isoformat()

        info.status = "running"

        return info



    def reallocate_worker_msg_port(self, pid: int, preferred_port: int | None = None) -> WorkerInfo:

        info = self.register_worker(pid=pid)

        reserved_ports = {

            worker.msg_port

            for worker_pid, worker in self.workers.items()

            if worker_pid != pid

        }

        info.msg_port = _allocate_worker_msg_port(reserved_ports, preferred_port=preferred_port)

        return info



    def touch_worker(

        self,

        pid: int,

        *,

        started_at: str | None = None,

        last_request_at: str | None = None,

        status: WorkerRuntimeStatus | None = None,

    ) -> WorkerInfo:

        info = self.register_worker(pid=pid)

        if started_at is not None:

            info.started_at = started_at

        if last_request_at is not None:

            info.last_request_at = last_request_at

        if status is not None:

            info.status = status

        return info



    def increment_worker_request(self, pid: int, at: str | None = None) -> WorkerInfo:

        if at is None:

            at = datetime.now(timezone.utc).isoformat()

        info = self.touch_worker(pid, last_request_at=at, status="running")

        info.request_count += 1

        return info



    def mark_worker_ready(self, pid: int) -> WorkerInfo:

        """Called by a worker when its lifespan startup has completed."""

        info = self.register_worker(pid=pid)

        info.lifespan_ready = True

        return info



    def count_ready_workers(self) -> int:

        """Return how many registered workers reported lifespan startup complete."""

        return sum(1 for info in self.workers.values() if info.lifespan_ready)



    def get_workers_snapshot(self) -> list[WorkerSnapshot]:

        rows: list[WorkerSnapshot] = []

        for pid, info in sorted(self.workers.items(), key=lambda item: item[0]):

            rows.append({

                "pid": pid,

                "msg_port": info.msg_port,

                "started_at": info.started_at,

                "request_count": info.request_count,

                "last_request_at": info.last_request_at,

                "status": info.status,

                "lifespan_ready": info.lifespan_ready,

            })

        return rows

        

    def get_worker(self, pid: int) -> WorkerInfo:

        info = self.workers.get(pid)

        if info is None:

            raise ValueError(f"Worker with pid {pid} not found")

        return info



    # ---- WebRTC room-to-worker mapping ----



    def update_room_worker(self, room_id: str, worker_pid: int) -> None:

        '''Map a room to the worker handling it.'''

        self.room_worker_map[room_id] = worker_pid

        

    def delete_room_worker(self, room_id: str) -> int | None:

        '''Remove the room-to-worker mapping.'''

        return self.room_worker_map.pop(room_id, None)

    

    def get_room_worker(self, room_id: str) -> int | None:

        '''Get the worker PID assigned to a room.'''

        return self.room_worker_map.get(room_id)



    def get_all_room_info(self) -> list[RoomInfo]:

        '''Return a list of all room info entries.'''

        infos: list[RoomInfo] = []

        for room_id, worker_id in self.room_worker_map.items():

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

        if not self.workers:

            return prefer_pid

        min_count: int | None = None

        candidates: list[int] = []

        for pid in self.workers.keys():

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

        self.ai_services_reload_state[int(pid)] = row

        return row



    def get_ai_services_reload_state(self) -> list[AIServiceReloadStateRow]:

        return [

            dict(self.ai_services_reload_state[pid])

            for pid in sorted(self.ai_services_reload_state)

        ]



    # ---- Lightweight cache helpers ----



    @overload

    def get_cache(self, key: str) -> object | None:

        ...



    @overload

    def get_cache(self, key: str, default: TCacheDefault) -> object | TCacheDefault:

        ...



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

    def get_runtime_meta(self) -> RuntimeMeta:

        self.cleanup_expired_cache()

        workers = self.get_workers_snapshot()

        return {

            "instance_uuid": self.instance_uuid,

            "server_start_time": self.server_start_time,

            "worker_pid": os.getpid(),

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

]

