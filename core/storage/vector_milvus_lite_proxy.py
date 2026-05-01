# -*- coding: utf-8 -*-
"""Milvus-Lite proxy process for multi-process access to one DB file."""

from __future__ import annotations

import asyncio
import copyreg
import glob
import hashlib
import logging
import os
import pickle
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from pymilvus.orm.schema import CollectionSchema, FieldSchema
except Exception:
    CollectionSchema = None  # type: ignore[misc, assignment]
    FieldSchema = None  # type: ignore[misc, assignment]

if FieldSchema is not None:
    def _field_schema_reconstruct(data: dict) -> Any:
        return FieldSchema.construct_from_dict(data)

    def _collection_schema_reconstruct(data: dict) -> Any:
        fields = [_field_schema_reconstruct(field) for field in data.get("fields", [])]
        kwargs: dict[str, Any] = {}
        if "enable_dynamic_field" in data:
            kwargs["enable_dynamic_field"] = data["enable_dynamic_field"]
        if "enable_namespace" in data:
            kwargs["enable_namespace"] = data["enable_namespace"]
        return CollectionSchema(fields, data.get("description", ""), **kwargs)

    copyreg.pickle(FieldSchema, lambda field: (_field_schema_reconstruct, (field.to_dict(),)))
    copyreg.pickle(CollectionSchema, lambda schema: (_collection_schema_reconstruct, (schema.to_dict(),)))

_logger = logging.getLogger(__name__)


async def _read_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    try:
        header = await reader.readexactly(4)
    except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
        return None
    size = struct.unpack("!I", header)[0]
    if size == 0:
        return None
    payload = await reader.readexactly(size)
    return pickle.loads(payload)


async def _write_message(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    data = pickle.dumps(message)
    writer.write(struct.pack("!I", len(data)) + data)
    await writer.drain()


def _db_path_hash(db_path: Path) -> str:
    return hashlib.sha256(str(db_path.resolve()).encode()).hexdigest()[:16]


def _runtime_dir() -> Path:
    base = Path(os.getenv("TMPDIR", "/tmp")) / "proj-template-milvus-lite"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _get_socket_path(db_path: Path) -> str:
    return str(_runtime_dir() / f"proxy_{_db_path_hash(db_path)}.sock")


def _get_pid_file_path(db_path: Path) -> str:
    return str(_runtime_dir() / f"proxy_{_db_path_hash(db_path)}.pid")


def _safe_remove(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class MilvusLiteProxyConnection:
    """Unix-domain socket client for the Milvus-Lite proxy process."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self, timeout: float = 30.0) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_unix_connection(self._socket_path),
            timeout=timeout,
        )

    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def call(self, op: str, *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            if not self.is_connected() or self._writer is None or self._reader is None:
                raise ConnectionResetError("MilvusLite proxy connection lost")
            await _write_message(self._writer, {"op": op, "args": args, "kwargs": kwargs})
            response = await _read_message(self._reader)
            if response is None:
                raise ConnectionResetError("MilvusLite proxy closed connection")
            if not response.get("ok"):
                error = response.get("error", "Unknown proxy error")
                error_type = response.get("error_type", "Exception")
                raise RuntimeError(f"[{error_type}] {error}")
            return response.get("result")

    def close(self) -> None:
        writer = self._writer
        self._writer = None
        self._reader = None
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass


def _spawn_proxy_process(db_path: str, socket_path: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["__MILVUS_LITE_PROXY_PROCESS__"] = "1"
    app_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = app_root + os.pathsep + env.get("PYTHONPATH", "")
    watch_pid = env.get("__SERVER_MAIN_PID__") or env.get("__MAIN_PROCESS_PID__") or str(os.getpid())

    proc = subprocess.Popen(
        [sys.executable, "-m", "core.storage.vector_milvus_lite_proxy", db_path, socket_path, watch_pid],
        env=env,
        start_new_session=True,
    )
    _logger.info("Spawned MilvusLite proxy process pid=%s for %s", proc.pid, db_path)
    return proc


def ensure_milvus_lite_proxy(db_path: Path) -> str:
    """Ensure the proxy process is running and return its socket path."""
    if os.name == "nt":
        raise RuntimeError("MilvusLite proxy uses Unix-domain sockets and is only supported on POSIX systems.")

    from ..utils.concurrent_utils.file_lock import FileCrossProcessLock

    socket_path = _get_socket_path(db_path)
    if os.path.exists(socket_path):
        return socket_path

    lock = FileCrossProcessLock(f"milvus_lite_proxy_{_db_path_hash(db_path)}")
    if not lock.acquire(blocking=True, timeout=30.0):
        raise RuntimeError("Timeout acquiring MilvusLite proxy startup lock")

    try:
        if os.path.exists(socket_path):
            return socket_path

        _safe_remove(socket_path)
        pid_file = _get_pid_file_path(db_path)
        if os.path.exists(pid_file):
            try:
                old_pid = int(Path(pid_file).read_text().strip())
                os.kill(old_pid, 0)
                for _ in range(300):
                    if os.path.exists(socket_path):
                        return socket_path
                    time.sleep(0.1)
            except (OSError, ValueError):
                _safe_remove(pid_file)

        proc = _spawn_proxy_process(str(db_path), socket_path)
        Path(pid_file).write_text(str(proc.pid))
        for _ in range(300):
            if os.path.exists(socket_path):
                return socket_path
            time.sleep(0.1)
        raise RuntimeError(f"MilvusLite proxy did not create socket at {socket_path}")
    finally:
        lock.release()


async def ensure_milvus_lite_proxy_async(db_path: Path) -> MilvusLiteProxyConnection:
    """Ensure the proxy is running and return a new connected client."""
    if os.name == "nt":
        raise RuntimeError("MilvusLite proxy uses Unix-domain sockets and is only supported on POSIX systems.")

    from ..utils.concurrent_utils.file_lock import FileCrossProcessLock

    socket_path = _get_socket_path(db_path)
    if os.path.exists(socket_path):
        conn = MilvusLiteProxyConnection(socket_path)
        try:
            await asyncio.wait_for(conn.connect(), timeout=2.0)
            return conn
        except Exception:
            pass

    lock = FileCrossProcessLock(f"milvus_lite_proxy_{_db_path_hash(db_path)}")
    acquired = await asyncio.to_thread(lock.acquire, blocking=True, timeout=30.0)
    if not acquired:
        raise RuntimeError("Timeout acquiring MilvusLite proxy startup lock")

    try:
        if os.path.exists(socket_path):
            conn = MilvusLiteProxyConnection(socket_path)
            try:
                await asyncio.wait_for(conn.connect(), timeout=2.0)
                return conn
            except Exception:
                pass

        _safe_remove(socket_path)
        pid_file = _get_pid_file_path(db_path)
        if os.path.exists(pid_file):
            try:
                old_pid = int(Path(pid_file).read_text().strip())
                await asyncio.to_thread(os.kill, old_pid, 0)
                for _ in range(300):
                    if os.path.exists(socket_path):
                        break
                    await asyncio.sleep(0.1)
                conn = MilvusLiteProxyConnection(socket_path)
                await asyncio.wait_for(conn.connect(), timeout=5.0)
                return conn
            except (OSError, ValueError):
                _safe_remove(pid_file)

        proc = await asyncio.to_thread(_spawn_proxy_process, str(db_path), socket_path)
        await asyncio.to_thread(lambda: Path(pid_file).write_text(str(proc.pid)))
        for _ in range(300):
            if os.path.exists(socket_path):
                break
            await asyncio.sleep(0.1)

        conn = MilvusLiteProxyConnection(socket_path)
        await asyncio.wait_for(conn.connect(), timeout=5.0)
        return conn
    finally:
        lock.release()


def cleanup_all_milvus_lite_proxies() -> None:
    if os.name == "nt":
        return
    import signal

    runtime_dir = str(_runtime_dir())
    for pid_file in glob.glob(os.path.join(runtime_dir, "proxy_*.pid")):
        try:
            pid = int(Path(pid_file).read_text().strip())
            os.kill(pid, signal.SIGTERM)
            _logger.info("Sent SIGTERM to MilvusLite proxy pid=%s from %s", pid, pid_file)
        except ProcessLookupError:
            pass
        except Exception as exc:
            _logger.debug("Failed to kill proxy from %s: %s", pid_file, exc)
        try:
            os.unlink(pid_file)
        except Exception:
            pass
    for socket_file in glob.glob(os.path.join(runtime_dir, "proxy_*.sock")):
        _safe_remove(socket_file)


def _to_plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _to_plain_value(item) for key, item in value.items()}
    if isinstance(value, (str, bytes)):
        return value
    if hasattr(value, "tolist"):
        return _to_plain_value(value.tolist())
    if hasattr(value, "DESCRIPTOR"):
        return _protobuf_to_dict(value)
    try:
        return [_to_plain_value(item) for item in value]
    except TypeError:
        return value


def _protobuf_to_dict(message: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in message.DESCRIPTOR.fields:
        value = getattr(message, field.name, None)
        if value is None:
            continue
        if field.label == field.LABEL_REPEATED:
            result[field.name] = [_to_plain_value(item) for item in value]
        else:
            result[field.name] = _to_plain_value(value)
    return result


def _mutation_result_to_dict(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, dict):
        return {key: _to_plain_value(value) for key, value in result.items()}
    return {
        "primary_keys": list(getattr(result, "primary_keys", [])),
        "insert_count": getattr(result, "insert_count", 0),
        "delete_count": getattr(result, "delete_count", 0),
        "upsert_count": getattr(result, "upsert_count", 0),
        "succ_count": getattr(result, "succ_count", 0),
        "err_count": getattr(result, "err_count", 0),
        "err_index": list(getattr(result, "err_index", [])),
        "succ_index": list(getattr(result, "succ_index", [])),
        "timestamp": getattr(result, "timestamp", 0),
        "cost": getattr(result, "cost", 0),
    }


class _MilvusLiteProxyHandler:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                message = await _read_message(reader)
                if message is None:
                    break
                op = message.get("op", "")
                args = message.get("args", [])
                kwargs = message.get("kwargs", {})
                try:
                    result = await self._dispatch(op, *args, **kwargs)
                    await _write_message(writer, {"ok": True, "result": result})
                except Exception as exc:
                    _logger.debug("MilvusLite proxy op=%s error: %s", op, exc, exc_info=True)
                    await _write_message(writer, {
                        "ok": False,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    })
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _dispatch(self, op: str, *args: Any, **kwargs: Any) -> Any:
        if op.startswith("async_client."):
            method_name = op[len("async_client."):]
            method = getattr(self._client._async_client, method_name, None)
            if method is None:
                raise AttributeError(f"AsyncMilvusClient has no method {method_name!r}")
            result = await method(*args, **kwargs)
            if method_name in {"upsert", "delete"}:
                return _mutation_result_to_dict(result)
            return _to_plain_value(result)

        method = getattr(self._client, op, None)
        if method is None:
            raise AttributeError(f"MilvusLiteVectorClient has no method {op!r}")
        if asyncio.iscoroutinefunction(method):
            return await method(*args, **kwargs)
        return method(*args, **kwargs)


async def _watch_parent_process(parent_pid: int, server: asyncio.Server) -> None:
    while True:
        await asyncio.sleep(5)
        try:
            os.kill(parent_pid, 0)
        except (ProcessLookupError, OSError):
            _logger.warning("Parent process %s is gone; shutting down MilvusLite proxy.", parent_pid)
            server.close()
            return


async def _run_proxy_server(db_path: str, socket_path: str, parent_pid: int | None = None) -> None:
    from .vector import MilvusLiteVectorClient

    _safe_remove(socket_path)
    client = MilvusLiteVectorClient(db_path=db_path, _proxy_mode=True)
    client.start()

    try:
        await client._async_client.has_collection("__warmup__")
    except Exception as exc:
        _logger.debug("Proxy warm-up call failed: %s", exc)

    handler = _MilvusLiteProxyHandler(client)
    server = await asyncio.start_unix_server(handler.handle, path=socket_path)
    try:
        os.chmod(socket_path, 0o600)
    except Exception:
        pass

    _logger.info("MilvusLite proxy server listening on %s", socket_path)
    if parent_pid is not None:
        asyncio.create_task(_watch_parent_process(parent_pid, server))

    try:
        async with server:
            await server.serve_forever()
    finally:
        _logger.info("MilvusLite proxy server shutting down")
        try:
            client.close()
        except Exception:
            pass
        _safe_remove(socket_path)
        _safe_remove(_get_pid_file_path(Path(db_path)))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m core.storage.vector_milvus_lite_proxy <db_path> <socket_path> [parent_pid]", file=sys.stderr)
        sys.exit(1)

    db_path_arg = sys.argv[1]
    socket_path_arg = sys.argv[2]
    parent_pid_arg: int | None = None
    if len(sys.argv) > 3:
        try:
            parent_pid_arg = int(sys.argv[3])
        except ValueError:
            pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        asyncio.run(_run_proxy_server(db_path_arg, socket_path_arg, parent_pid_arg))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass