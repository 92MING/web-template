# -*- coding: utf-8 -*-
"""Gallery routes used by distributed forwarding smoke tests."""

import asyncio
import os
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from core.server import Route

__all__ = [
    "GalleryDistributedProbeRoute",
    "GalleryDistributedStreamRoute",
    "GalleryDistributedEchoStreamRoute",
]


class GalleryDistributedProbeRoute(Route):
    RoutePath = "/distributed-probe"

    async def get(self, value: str = "") -> dict[str, Any]:
        return {
            "node_id": self.shared_data.instance_uuid,
            "pid": os.getpid(),
            "value": value,
        }

    async def post(self, value: str = "") -> dict[str, Any]:
        return {
            "node_id": self.shared_data.instance_uuid,
            "pid": os.getpid(),
            "value": value,
        }


class GalleryDistributedStreamRoute(Route):
    RoutePath = "/distributed-probe/stream"

    async def get(self, chunks: int = 3) -> StreamingResponse:
        async def _events():
            for idx in range(max(1, min(int(chunks), 8))):
                yield f"data: {idx}\n\n"
                await asyncio.sleep(0.02)

        return StreamingResponse(_events(), media_type="text/event-stream")


class GalleryDistributedEchoStreamRoute(Route):
    RoutePath = "/distributed-probe/echo-stream"

    async def post(self, request: Request) -> dict[str, Any]:
        size = 0
        chunks = 0
        async for chunk in request.stream():
            if not chunk:
                continue
            chunks += 1
            size += len(chunk)
        return {
            "node_id": self.shared_data.instance_uuid,
            "pid": os.getpid(),
            "chunks": chunks,
            "size": size,
        }
