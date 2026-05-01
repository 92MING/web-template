# -*- coding: utf-8 -*-


import contextlib
import json
import os
import socket
import threading

from datetime import datetime, timezone
from typing import Callable, Literal, NotRequired, Protocol, TypedDict, cast

type ControlAction = Literal["restart", "stop"]
type ControlTrigger = Callable[[ControlAction, str | None], None]


class ControlStatus(TypedDict):
    supported: bool
    accepted: bool | None
    mode: str
    note: str | None
    supervisor_pid: int | None
    server_pid: int | None
    restart_supported: bool
    stop_supported: bool
    requested_action: ControlAction | None
    requested_at: str | None
    requested_reason: str | None
    last_completed_action: ControlAction | None
    actions: list[ControlAction]


class RemoteControlRequest(TypedDict):
    token: NotRequired[str]
    type: NotRequired[Literal["status"]]
    action: NotRequired[ControlAction]
    reason: NotRequired[str | None]


class RemoteControlEnvelope(TypedDict):
    ok: bool
    status: NotRequired[ControlStatus]
    error: NotRequired[str]


class ShutdownControllableServer(Protocol):
    should_exit: bool

_SUPPORTED_ACTIONS: tuple[ControlAction, ...] = ("restart", "stop")
_ENV_CONTROL_HOST = "__SERVER_CONTROL_HOST__"
_ENV_CONTROL_PORT = "__SERVER_CONTROL_PORT__"
_ENV_CONTROL_TOKEN = "__SERVER_CONTROL_TOKEN__"
_lock = threading.RLock()
_controller: "_BaseServerController | None" = None
_socket_server: "_ControlSocketServer | None" = None

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class _BaseServerController:
    def __init__(self, *, mode: str, note: str | None = None, supervisor_pid: int | None = None, server_pid: int | None = None):
        self.mode = mode
        self.note = note
        self.supervisor_pid = supervisor_pid or os.getpid()
        self.server_pid = server_pid or os.getpid()
        self._requested_action: ControlAction | None = None
        self._requested_at: str | None = None
        self._requested_reason: str | None = None
        self._last_completed_action: ControlAction | None = None

    def _trigger_shutdown(self, action: ControlAction, reason: str | None = None) -> None:
        raise NotImplementedError

    def request(self, action: ControlAction, reason: str | None = None) -> ControlStatus:
        with _lock:
            self._requested_action = action
            self._requested_at = _now_iso()
            self._requested_reason = (reason or "").strip() or None
        self._trigger_shutdown(action, self._requested_reason)
        return self.snapshot(accepted=True)

    def consume_requested_action(self) -> ControlAction | None:
        with _lock:
            action = self._requested_action
            if action is not None:
                self._last_completed_action = action
            self._requested_action = None
            self._requested_reason = None
            self._requested_at = None
            return action

    def snapshot(self, *, accepted: bool | None = None) -> ControlStatus:
        return {
            "supported": True,
            "accepted": accepted,
            "mode": self.mode,
            "note": self.note,
            "supervisor_pid": self.supervisor_pid,
            "server_pid": self.server_pid,
            "restart_supported": True,
            "stop_supported": True,
            "requested_action": self._requested_action,
            "requested_at": self._requested_at,
            "requested_reason": self._requested_reason,
            "last_completed_action": self._last_completed_action,
            "actions": list(_SUPPORTED_ACTIONS),
        }


class InProcessServerController(_BaseServerController):
    def __init__(self, server: ShutdownControllableServer, *, mode: str, note: str | None = None):
        super().__init__(mode=mode, note=note)
        self.server = server

    def _trigger_shutdown(self, action: ControlAction, reason: str | None = None) -> None:
        graceful_shutdown = getattr(self.server, "request_graceful_shutdown", None)
        if callable(graceful_shutdown):
            graceful_shutdown(reason=reason or action)
        else:
            self.server.should_exit = True

class CallbackServerController(_BaseServerController):
    def __init__(self, trigger: ControlTrigger, *, mode: str, note: str | None = None):
        super().__init__(mode=mode, note=note)
        self._trigger = trigger

    def _trigger_shutdown(self, action: ControlAction, reason: str | None = None) -> None:
        self._trigger(action, reason)

class _ControlSocketServer:
    def __init__(self, controller: _BaseServerController):
        self.controller = controller
        self.host = "127.0.0.1"
        self.port = 0
        self.token = os.urandom(16).hex()
        self._stop_event = threading.Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, 0))
        self._socket.listen(8)
        self._socket.settimeout(0.5)
        self.port = int(self._socket.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, name="proj-runtime-control-socket", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        with contextlib.suppress(Exception):
            self._socket.close()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1.0)

    def _read_payload(self, conn: socket.socket) -> RemoteControlRequest:
        chunks: list[bytes] = []
        total = 0
        while total < 64 * 1024:
            data = conn.recv(4096)
            if not data:
                break
            chunks.append(data)
            total += len(data)
            if b"\n" in data:
                break
        raw = b"".join(chunks).split(b"\n", 1)[0].strip()
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return {}
        return cast(RemoteControlRequest, payload)

    def _write_response(self, conn: socket.socket, payload: RemoteControlEnvelope) -> None:
        conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            payload = self._read_payload(conn)
            if payload.get("token") != self.token:
                self._write_response(conn, {"ok": False, "error": "Unauthorized runtime control request."})
                return
            if payload.get("type") == "status":
                self._write_response(conn, {"ok": True, "status": self.controller.snapshot(accepted=None)})
                return
            action = str(payload.get("action") or "").strip().lower()
            if action not in _SUPPORTED_ACTIONS:
                self._write_response(conn, {"ok": False, "error": f"Unsupported control action: {action or '<empty>'}"})
                return
            reason = payload.get("reason")
            status = self.controller.request(cast(ControlAction, action), reason=reason if isinstance(reason, str) else None)
            self._write_response(conn, {"ok": True, "status": status})
        except Exception as exc:
            self._write_response(conn, {"ok": False, "error": str(exc)})

    def _serve(self) -> None:
        while not self._stop_event.is_set():
            try:
                conn, _addr = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                continue
            with conn:
                self._handle_client(conn)


def _stop_socket_server() -> None:
    global _socket_server
    if _socket_server is None:
        return
    server = _socket_server
    _socket_server = None
    server.close()


def _start_socket_server(controller: _BaseServerController) -> _ControlSocketServer:
    global _socket_server
    _stop_socket_server()
    server = _ControlSocketServer(controller)
    server.start()
    _socket_server = server
    return server


def _remote_control_available() -> bool:
    host = (os.getenv(_ENV_CONTROL_HOST) or "").strip()
    port = (os.getenv(_ENV_CONTROL_PORT) or "").strip()
    token = (os.getenv(_ENV_CONTROL_TOKEN) or "").strip()
    return bool(host and port and token)


def _read_remote_status() -> ControlStatus | None:
    try:
        return _request_remote_control({"type": "status"})
    except Exception:
        return None


def _request_remote_control(payload: RemoteControlRequest, *, timeout: float = 1.5) -> ControlStatus:
    host = (os.getenv(_ENV_CONTROL_HOST) or "").strip()
    port_text = (os.getenv(_ENV_CONTROL_PORT) or "").strip()
    token = (os.getenv(_ENV_CONTROL_TOKEN) or "").strip()
    if not host or not port_text or not token:
        raise RuntimeError("主进程控制通道尚未初始化。")
    request = dict(payload)
    request["token"] = token
    port = int(port_text)
    with socket.create_connection((host, port), timeout=timeout) as conn:
        conn.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        with contextlib.suppress(OSError):
            conn.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            data = conn.recv(4096)
            if not data:
                break
            chunks.append(data)
            if b"\n" in data:
                break
    raw = b"".join(chunks).split(b"\n", 1)[0].strip()
    if not raw:
        raise RuntimeError("主进程控制通道未返回响应。")
    response = json.loads(raw.decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("主进程控制响应格式无效。")
    envelope = cast(RemoteControlEnvelope, response)
    if not envelope.get("ok"):
        raise RuntimeError(envelope.get("error") or "主进程控制请求失败。")
    status = envelope.get("status")
    if not isinstance(status, dict):
        raise RuntimeError("主进程控制响应格式无效。")
    return cast(ControlStatus, status)

def _set_env_control_status(*, supported: bool, mode: str, note: str | None = None, supervisor_pid: int | None = None, server_pid: int | None = None, host: str | None = None, port: int | None = None, token: str | None = None) -> None:
    os.environ["__SERVER_CONTROL_SUPPORTED__"] = "1" if supported else "0"
    os.environ["__SERVER_CONTROL_MODE__"] = mode
    if note:
        os.environ["__SERVER_CONTROL_NOTE__"] = note
    else:
        os.environ.pop("__SERVER_CONTROL_NOTE__", None)
    if supervisor_pid is not None:
        os.environ["__SERVER_SUPERVISOR_PID__"] = str(supervisor_pid)
    if server_pid is not None:
        os.environ["__SERVER_PROCESS_PID__"] = str(server_pid)
    if host and port and token:
        os.environ[_ENV_CONTROL_HOST] = host
        os.environ[_ENV_CONTROL_PORT] = str(port)
        os.environ[_ENV_CONTROL_TOKEN] = token
    else:
        os.environ.pop(_ENV_CONTROL_HOST, None)
        os.environ.pop(_ENV_CONTROL_PORT, None)
        os.environ.pop(_ENV_CONTROL_TOKEN, None)

def install_inprocess_controller(server: ShutdownControllableServer, *, note: str | None = None) -> ControlStatus:
    global _controller
    with _lock:
        _controller = InProcessServerController(server, mode="inprocess-exec", note=note)
        _stop_socket_server()
        _set_env_control_status(
            supported=True,
            mode="inprocess-exec",
            note=note,
            supervisor_pid=_controller.supervisor_pid,
            server_pid=_controller.server_pid,
        )
        return _controller.snapshot(accepted=None)


def install_callback_controller(trigger: ControlTrigger, *, mode: str, note: str | None = None) -> ControlStatus:
    global _controller
    with _lock:
        _controller = CallbackServerController(trigger, mode=mode, note=note)
        server = _start_socket_server(_controller)
        _set_env_control_status(
            supported=True,
            mode=mode,
            note=note,
            supervisor_pid=_controller.supervisor_pid,
            server_pid=_controller.server_pid,
            host=server.host,
            port=server.port,
            token=server.token,
        )
        return _controller.snapshot(accepted=None)


def install_disabled_controller(*, mode: str = "unsupported", note: str | None = None, supervisor_pid: int | None = None, server_pid: int | None = None) -> ControlStatus:
    global _controller
    with _lock:
        _controller = None
        _stop_socket_server()
        _set_env_control_status(
            supported=False,
            mode=mode,
            note=note,
            supervisor_pid=supervisor_pid,
            server_pid=server_pid,
        )
        return get_control_status()


def get_control_status() -> ControlStatus:
    with _lock:
        if _controller is not None:
            return _controller.snapshot(accepted=None)

    if _remote_control_available():
        if remote_status := _read_remote_status():
            return remote_status

    supported = os.getenv("__SERVER_CONTROL_SUPPORTED__", "0").strip() in {"1", "true", "yes"}
    supervisor_pid = os.getenv("__SERVER_SUPERVISOR_PID__")
    server_pid = os.getenv("__SERVER_PROCESS_PID__")
    return {
        "supported": supported,
        "accepted": None,
        "mode": os.getenv("__SERVER_CONTROL_MODE__", "unavailable"),
        "note": os.getenv("__SERVER_CONTROL_NOTE__") or None,
        "supervisor_pid": int(supervisor_pid) if supervisor_pid and supervisor_pid.isdigit() else None,
        "server_pid": int(server_pid) if server_pid and server_pid.isdigit() else None,
        "restart_supported": supported,
        "stop_supported": supported,
        "requested_action": None,
        "requested_at": None,
        "requested_reason": None,
        "last_completed_action": None,
        "actions": list(_SUPPORTED_ACTIONS),
    }

def request_control_action(action: str, *, reason: str | None = None) -> ControlStatus:
    normalized = str(action or "").strip().lower()
    if normalized not in _SUPPORTED_ACTIONS:
        raise ValueError(f"Unsupported control action: {action}")
    with _lock:
        if _controller is None:
            status = get_control_status()
            if not status.get("supported"):
                raise RuntimeError(status.get("note") or "当前启动模式不支持进程级控制。")
            if _remote_control_available():
                return _request_remote_control({"action": cast(ControlAction, normalized), "reason": reason})
            raise RuntimeError("进程控制器未初始化。")
        return _controller.request(cast(ControlAction, normalized), reason=reason)

def consume_requested_action() -> ControlAction | None:
    with _lock:
        if _controller is None:
            return None
        return _controller.consume_requested_action()


def shutdown_control_server() -> None:
    _stop_socket_server()


__all__ = [
    "ControlAction",
    "ControlStatus",
    "consume_requested_action",
    "get_control_status",
    "install_callback_controller",
    "install_disabled_controller",
    "install_inprocess_controller",
    "request_control_action",
    "shutdown_control_server",
]