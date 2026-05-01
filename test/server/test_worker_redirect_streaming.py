# -*- coding: utf-8 -*-
"""Tests for streaming responses over worker redirect IPC."""

import asyncio
import pickle
import struct
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.requests import Request

_server_dir = Path(__file__).resolve().parent.parent.parent / "app" / "core" / "server"
if str(_server_dir.parent.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent.parent))
if str(_server_dir.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent))

from core.server import app as app_module
from core.server import shared as shared_module
from core.server.shared import WorkerInfo


class _FakeSharedData:
    def __init__(self, worker: WorkerInfo) -> None:
        self._worker = worker

    def get_worker(self, worker_id: int) -> WorkerInfo:
        assert worker_id == self._worker.pid
        return self._worker


async def _start_worker_redirect_server(target_app: FastAPI):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            length_data = await reader.readexactly(4)
            length = struct.unpack("!I", length_data)[0]
            message = pickle.loads(await reader.readexactly(length))
            result = await message.handle(target_app)
            await app_module._write_worker_redirect_result(writer, result)
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _cleanup_worker_client(worker_id: int) -> None:
    client = shared_module._other_worker_sockets.pop(worker_id, None)
    shared_module._other_worker_socket_locks.pop(worker_id, None)
    if client is not None:
        _, writer = client
        writer.close()
        await writer.wait_closed()


def _redirect_request(path: str) -> Request:
    return Request({"type": "http", "path": path, "method": "GET", "headers": []})


async def _collect_stream(response: StreamingResponse) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
    return b"".join(chunks)


def test_redirect_to_worker_preserves_streaming_response(monkeypatch):
    async def scenario() -> None:
        target_app = FastAPI()

        @target_app.get("/events")
        async def events() -> StreamingResponse:
            async def gen():
                yield "data: one\n\n"
                await asyncio.sleep(0)
                yield b"data: two\n\n"

            return StreamingResponse(
                gen(),
                media_type="text/event-stream",
                headers={"x-stream": "ok"},
            )

        server, port = await _start_worker_redirect_server(target_app)
        worker_id = 902001
        monkeypatch.setattr(
            shared_module.AppSharedData,
            "Get",
            classmethod(lambda cls: _FakeSharedData(WorkerInfo(pid=worker_id, msg_port=port))),
        )

        try:
            response = await app_module.redirect_to_worker(worker_id, _redirect_request("/events"), {})
            assert isinstance(response, StreamingResponse)
            assert response.media_type == "text/event-stream"
            assert response.headers["x-stream"] == "ok"
            assert await _collect_stream(response) == b"data: one\n\ndata: two\n\n"
        finally:
            server.close()
            await server.wait_closed()
            await _cleanup_worker_client(worker_id)

    asyncio.run(scenario())


def test_redirect_to_worker_wraps_direct_async_generator_as_sse(monkeypatch):
    async def scenario() -> None:
        target_app = FastAPI()

        @target_app.get("/raw-events")
        async def raw_events():
            async def gen():
                yield "data: raw-one\n\n"
                await asyncio.sleep(0)
                yield "data: raw-two\n\n"

            return gen()

        server, port = await _start_worker_redirect_server(target_app)
        worker_id = 902002
        monkeypatch.setattr(
            shared_module.AppSharedData,
            "Get",
            classmethod(lambda cls: _FakeSharedData(WorkerInfo(pid=worker_id, msg_port=port))),
        )

        try:
            response = await app_module.redirect_to_worker(worker_id, _redirect_request("/raw-events"), {})
            assert isinstance(response, StreamingResponse)
            assert response.media_type == "text/event-stream"
            assert await _collect_stream(response) == b"data: raw-one\n\ndata: raw-two\n\n"
        finally:
            server.close()
            await server.wait_closed()
            await _cleanup_worker_client(worker_id)

    asyncio.run(scenario())


def test_redirect_to_worker_keeps_non_stream_result(monkeypatch):
    async def scenario() -> None:
        target_app = FastAPI()

        @target_app.get("/value")
        async def value() -> dict[str, object]:
            return {"ok": True, "items": [1, 2, 3]}

        server, port = await _start_worker_redirect_server(target_app)
        worker_id = 902003
        monkeypatch.setattr(
            shared_module.AppSharedData,
            "Get",
            classmethod(lambda cls: _FakeSharedData(WorkerInfo(pid=worker_id, msg_port=port))),
        )

        try:
            response = await app_module.redirect_to_worker(worker_id, _redirect_request("/value"), {})
            assert response == {"ok": True, "items": [1, 2, 3]}
        finally:
            server.close()
            await server.wait_closed()
            await _cleanup_worker_client(worker_id)

    asyncio.run(scenario())