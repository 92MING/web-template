# -*- coding: utf-8 -*-
"""Distributed network management routes."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from core.server.distributed import (
    Node,
    NodeRegistry,
    NodeRelation,
    create_auth_challenge,
    respond_to_challenge,
    verify_challenge_response,
)
from core.server.shared import AppSharedData
from core.server.data_types.config import Config
from core.server.html_injection import html_response_from_path
from ...app import get_resources, internal_admin_path, on_before_app_created

router = APIRouter(tags=["Distributed"])


@on_before_app_created
def register_distributed_routes(app):
    app.include_router(router, prefix=internal_admin_path("api/distributed"))
    register_distributed_html_routes(app)


class RegisterNodeRequest(BaseModel):
    node_id: str
    host: str
    port: int
    relation: NodeRelation = "friend"
    admin_password_hash: str = ""
    gsd_port: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)


class AuthChallengeResponse(BaseModel):
    nonce: str
    timestamp: float


class AuthVerifyRequest(BaseModel):
    nonce: str
    timestamp: float
    hash: str


class BroadcastRequest(BaseModel):
    message: dict[str, Any]
    target_relations: list[NodeRelation] = Field(default_factory=lambda: ["parent", "child", "friend"])
    target_nodes: list[str] | None = Field(default=None, description="Optional node ids for directed delivery.")
    origin_node: str | None = Field(default=None, description="Original sender node id.")
    from_node: str | None = Field(default=None, description="Previous relay node id.")
    seen_nodes: list[str] = Field(default_factory=list, description="Relay path used for loop prevention.")
    ttl: int = Field(default=16, ge=0, le=128)


class CommandRequest(BaseModel):
    command: str  # e.g. "restart", "stop", "set_workers"
    args: dict[str, Any] = Field(default_factory=dict)
    origin_node: str | None = Field(default=None, description="Original management sender node id.")
    from_node: str | None = Field(default=None, description="Previous relay node id.")
    seen_nodes: list[str] = Field(default_factory=list, description="Relay path used for loop prevention.")
    ttl: int = Field(default=16, ge=0, le=128)


class PingNodeRequest(BaseModel):
    origin_node: str | None = Field(default=None, description="Original ping sender node id.")
    from_node: str | None = Field(default=None, description="Previous relay node id.")
    seen_nodes: list[str] = Field(default_factory=list, description="Relay path used for loop prevention.")
    ttl: int = Field(default=8, ge=0, le=64)
    direct_only: bool = False


def _command_payload(req: CommandRequest, self_id: str) -> dict[str, Any]:
    payload = req.model_dump()
    seen = set(req.seen_nodes)
    if req.from_node:
        seen.add(req.from_node)
    seen.add(self_id)
    payload["origin_node"] = req.origin_node or req.from_node or self_id
    payload["from_node"] = self_id
    payload["seen_nodes"] = sorted(seen)
    payload["ttl"] = req.ttl - 1
    return payload


async def _post_command(node: Node, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    import aiohttp

    url = f"http://{node.host}:{node.port}{path}"
    timeout = aiohttp.ClientTimeout(total=10.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            raise HTTPException(status_code=502, detail=f"Node {node.node_id} returned {resp.status}")


async def _probe_node_health(registry: NodeRegistry, node: Node) -> dict[str, Any]:
    import aiohttp

    path = Config.GetConfig().server_config.get_internal_admin_path("api/distributed/health")
    url = f"http://{node.host}:{node.port}{path}"
    timeout = aiohttp.ClientTimeout(total=5.0)
    started = time.perf_counter()
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                rtt_ms = (time.perf_counter() - started) * 1000
                try:
                    payload = await resp.json()
                except Exception:
                    payload = {"text": await resp.text()}
                if resp.status == 200:
                    await registry.update_health(node.node_id, success=True, rtt_ms=rtt_ms)
                    return {
                        "ok": True,
                        "node_id": node.node_id,
                        "status_code": resp.status,
                        "rtt_ms": rtt_ms,
                        "response": payload,
                    }
                await registry.update_health(node.node_id, success=False)
                return {
                    "ok": False,
                    "node_id": node.node_id,
                    "status_code": resp.status,
                    "rtt_ms": rtt_ms,
                    "response": payload,
                    "error": f"Health endpoint returned {resp.status}",
                }
    except Exception as exc:
        await registry.update_health(node.node_id, success=False)
        return {
            "ok": False,
            "node_id": node.node_id,
            "status_code": None,
            "rtt_ms": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _post_ping(node: Node, target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    import aiohttp

    path = Config.GetConfig().server_config.get_internal_admin_path(f"api/distributed/nodes/{target_id}/ping")
    url = f"http://{node.host}:{node.port}{path}"
    timeout = aiohttp.ClientTimeout(total=10.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            if resp.status == 200:
                return data
            raise HTTPException(status_code=502, detail=f"Node {node.node_id} returned {resp.status}: {data}")


def _ping_payload(req: PingNodeRequest, self_id: str) -> dict[str, Any]:
    seen = set(req.seen_nodes)
    if req.from_node:
        seen.add(req.from_node)
    seen.add(self_id)
    return {
        "origin_node": req.origin_node or req.from_node or self_id,
        "from_node": self_id,
        "seen_nodes": sorted(seen),
        "ttl": req.ttl - 1,
        "direct_only": req.direct_only,
    }


# ── self info ────────────────────────────────────────────────────────────

@router.get("/self")
async def get_self_info() -> dict[str, Any]:
    sd = AppSharedData.Get()
    return {
        "node_id": sd.instance_uuid,
        "host": os.getenv("__HOST__", "127.0.0.1"),
        "port": int(os.getenv("__PORT__", "0")),
        "worker_count": len(sd.workers),
        "control_supported": os.getenv("__SERVER_CONTROL_SUPPORTED__", "0").strip() in ("1", "true", "yes"),
    }


# ── health endpoint (called by other nodes) ──────────────────────────────

@router.get("/health")
async def distributed_health() -> dict[str, Any]:
    sd = AppSharedData.Get()
    return {
        "node_id": sd.instance_uuid,
        "status": "ok",
        "worker_count": len(sd.workers),
        "ready_workers": sd.count_ready_workers(),
    }


# ── node CRUD ────────────────────────────────────────────────────────────

@router.get("/nodes")
async def list_nodes(
    relation: NodeRelation | None = None,
    healthy_only: bool = False,
) -> list[dict[str, Any]]:
    registry = NodeRegistry.get_instance()
    self_id = AppSharedData.Get().instance_uuid
    if healthy_only:
        nodes = await registry.healthy()
    elif relation:
        nodes = await registry.by_relation(relation)
    else:
        nodes = await registry.all()
    result: list[dict[str, Any]] = []
    for node in nodes:
        row = node.to_dict()
        route = await registry.management_route(self_id, node.node_id)
        row["management"] = {
            "can_manage": bool(route),
            "route": [hop.node_id for hop in route or []],
        }
        result.append(row)
    return result


@router.post("/nodes")
async def register_node(req: RegisterNodeRequest) -> dict[str, Any]:
    registry = NodeRegistry.get_instance()
    node = await registry.register(
        node_id=req.node_id,
        host=req.host,
        port=req.port,
        relation=req.relation,
        admin_password_hash=req.admin_password_hash,
        gsd_port=req.gsd_port,
        metadata=req.metadata,
    )
    # Also register as a GlobalSharedDict peer so gossip works out-of-the-box
    try:
        from core.server.shared_dict import GlobalSharedDict
        gsd = GlobalSharedDict.get_instance()
        gsd.register_peer(
            node_id=node.node_id,
            host=node.host,
            port=node.gsd_port or node.port,
            relation=node.relation,
        )
    except Exception:
        pass
    return node.to_dict()


@router.get("/nodes/{node_id}")
async def get_node(node_id: str) -> dict[str, Any]:
    registry = NodeRegistry.get_instance()
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node.to_dict()


@router.post("/nodes/{node_id}/ping")
async def ping_node(node_id: str, req: PingNodeRequest) -> dict[str, Any]:
    registry = NodeRegistry.get_instance()
    self_id = AppSharedData.Get().instance_uuid
    if node_id == self_id:
        return {
            "ok": True,
            "node_id": node_id,
            "status_code": 200,
            "rtt_ms": 0.0,
            "direct": True,
            "relayed": False,
            "route": [self_id],
            "response": {"node_id": self_id, "status": "ok"},
        }

    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    direct_result = await _probe_node_health(registry, node)
    direct_result["direct"] = True
    direct_result["relayed"] = False
    direct_result["route"] = [self_id, node_id]
    if direct_result["ok"] or req.direct_only:
        return direct_result

    if req.ttl <= 0:
        direct_result["ttl_expired"] = True
        return direct_result

    seen = set(req.seen_nodes)
    if req.from_node:
        seen.add(req.from_node)
    seen.add(self_id)

    candidates: dict[str, Node] = {}
    route = await registry.management_route(self_id, node_id)
    if route and len(route) > 1:
        candidates[route[0].node_id] = route[0]
    for candidate in await registry.all():
        if candidate.node_id in seen or candidate.node_id == node_id:
            continue
        candidates.setdefault(candidate.node_id, candidate)

    relay_errors: list[dict[str, str]] = []
    payload = _ping_payload(req, self_id)
    for candidate in candidates.values():
        started = time.perf_counter()
        try:
            relay_result = await _post_ping(candidate, node_id, payload)
        except Exception as exc:
            relay_errors.append({"node_id": candidate.node_id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if relay_result.get("ok") is True:
            end_to_end_rtt_ms = (time.perf_counter() - started) * 1000
            await registry.update_health(node_id, success=True, rtt_ms=end_to_end_rtt_ms)
            remote_route = relay_result.get("route")
            if not isinstance(remote_route, list):
                remote_route = [candidate.node_id, node_id]
            route_from_self = [self_id, *[str(item) for item in remote_route if str(item) != self_id]]
            relay_result.update({
                "direct": False,
                "relayed": True,
                "via_node": candidate.node_id,
                "route": route_from_self,
                "relay_rtt_ms": relay_result.get("rtt_ms"),
                "rtt_ms": end_to_end_rtt_ms,
            })
            return relay_result
        relay_errors.append({
            "node_id": candidate.node_id,
            "error": str(relay_result.get("error") or relay_result.get("status_code") or "ping failed"),
        })

    direct_result["relay_errors"] = relay_errors
    return direct_result


@router.delete("/nodes/{node_id}")
async def unregister_node(node_id: str) -> dict[str, Any]:
    registry = NodeRegistry.get_instance()
    node = await registry.unregister(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    # Also unregister from GlobalSharedDict peers
    try:
        from core.server.shared_dict import GlobalSharedDict
        GlobalSharedDict.get_instance().unregister_peer(node_id)
    except Exception:
        pass
    return {"ok": True, "node_id": node_id}


# ── auth challenge-response ──────────────────────────────────────────────

@router.post("/nodes/{node_id}/auth/challenge")
async def create_node_auth_challenge(node_id: str) -> AuthChallengeResponse:
    registry = NodeRegistry.get_instance()
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    challenge = create_auth_challenge()
    return AuthChallengeResponse(nonce=challenge["nonce"], timestamp=challenge["timestamp"])


@router.post("/nodes/{node_id}/auth/verify")
async def verify_node_auth(node_id: str, req: AuthVerifyRequest) -> dict[str, bool]:
    registry = NodeRegistry.get_instance()
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node.admin_password_hash:
        raise HTTPException(status_code=400, detail="Node has no registered password hash")
    ok = verify_challenge_response(
        req.nonce, req.timestamp, req.hash, node.admin_password_hash
    )
    return {"ok": ok}


# ── broadcast ────────────────────────────────────────────────────────────

@router.post("/broadcast")
async def broadcast_message(req: BroadcastRequest) -> dict[str, Any]:
    """Broadcast a message to all nodes matching target_relations.

    Relayed requests continue through known peers until TTL is exhausted. This
    allows a host node to reach a container-only node through an exposed peer.
    """
    registry = NodeRegistry.get_instance()
    self_id = AppSharedData.Get().instance_uuid
    target_nodes = set(req.target_nodes or [])
    delivered = req.from_node is not None and (not target_nodes or self_id in target_nodes)
    if delivered:
        import logging
        logging.getLogger("distributed").info(
            "Received broadcast from %s via %s: %s",
            req.origin_node or req.from_node,
            req.from_node,
            req.message,
        )

    if req.ttl <= 0:
        return {"sent": 0, "failed": 0, "received": delivered, "ttl_expired": True}

    sent = 0
    failed = 0
    seen = set(req.seen_nodes)
    if req.from_node:
        seen.add(req.from_node)
    seen.add(self_id)

    candidates: dict[str, Node] = {}
    if target_nodes:
        for node_id in target_nodes:
            node = await registry.get(node_id)
            if node is not None:
                candidates[node.node_id] = node
        for node in await registry.all():
            candidates.setdefault(node.node_id, node)
    else:
        for relation in req.target_relations:
            for node in await registry.by_relation(relation):
                candidates[node.node_id] = node

    import aiohttp
    timeout = aiohttp.ClientTimeout(total=5.0)
    payload = req.model_dump()
    payload["origin_node"] = req.origin_node or req.from_node or self_id
    payload["from_node"] = self_id
    payload["seen_nodes"] = sorted(seen)
    payload["ttl"] = req.ttl - 1
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for node in candidates.values():
            if node.node_id in seen:
                continue
            try:
                path = Config.GetConfig().server_config.get_internal_admin_path("api/distributed/broadcast")
                url = f"http://{node.host}:{node.port}{path}"
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        sent += 1
                    else:
                        failed += 1
            except Exception:
                failed += 1
    return {"sent": sent, "failed": failed, "received": delivered}


# ── parent management commands (parent -> child only) ────────────────────

@router.post("/nodes/{node_id}/command")
async def send_command_to_node(node_id: str, req: CommandRequest) -> dict[str, Any]:
    """Send a management command to a child or child-edge descendant node."""
    registry = NodeRegistry.get_instance()
    self_id = AppSharedData.Get().instance_uuid
    route = await registry.management_route(self_id, node_id)
    if route is None:
        if await registry.get(node_id) is None:
            raise HTTPException(status_code=404, detail="Node not found")
        raise HTTPException(status_code=403, detail="Node is outside this node's management scope")
    if not route:
        raise HTTPException(status_code=403, detail="Cannot send management commands to self through distributed node API")
    if req.ttl <= 0:
        raise HTTPException(status_code=508, detail="Management command relay TTL exhausted")

    seen = set(req.seen_nodes)
    if req.from_node:
        seen.add(req.from_node)
    if self_id in seen:
        raise HTTPException(status_code=508, detail="Management command relay loop detected")

    next_hop = route[0]
    if len(route) == 1:
        path = Config.GetConfig().server_config.get_internal_admin_path("api/distributed/command")
    else:
        path = Config.GetConfig().server_config.get_internal_admin_path(f"api/distributed/nodes/{node_id}/command")
    return await _post_command(next_hop, path, _command_payload(req, self_id))


@router.get("/nodes/{node_id}/management")
async def get_node_management_scope(node_id: str) -> dict[str, Any]:
    registry = NodeRegistry.get_instance()
    self_id = AppSharedData.Get().instance_uuid
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    route = await registry.management_route(self_id, node_id)
    return {
        "node_id": node_id,
        "can_manage": bool(route),
        "route": [hop.node_id for hop in route or []],
    }


# ── receive command (called by parent on this node) ──────────────────────

@router.post("/command")
async def receive_command(req: CommandRequest) -> dict[str, Any]:
    """Receive a management command from a parent node."""
    from core.server.runtime_control import request_control_action

    if req.command == "restart":
        try:
            request_control_action("restart", reason="Parent node command")
            return {"ok": True, "message": "Restart requested"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    elif req.command == "stop":
        try:
            request_control_action("stop", reason="Parent node command")
            return {"ok": True, "message": "Stop requested"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    elif req.command == "set_workers":
        # This would require runtime config update; stub for now
        return {"ok": True, "message": "set_workers not yet implemented", "args": req.args}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown command: {req.command}")


# ── global shared dict sync ──────────────────────────────────────────────

@router.post("/gsd/sync")
async def gsd_sync_request() -> dict[str, Any]:
    """Return the full GlobalSharedDict state for sync."""
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    return {"node_id": gsd._node_id, "data": dict(gsd._local_data)}


# ── HTML page routes ─────────────────────────────────────────────────────

def register_distributed_html_routes(app):
    @app.get(internal_admin_path("panel/distributed.html"), response_class=HTMLResponse)
    async def distributed_panel_html():
        path = get_resources("admin-panel", "panel", "distributed.html") or Path("distributed.html")
        return html_response_from_path(path, not_found_message="panel/distributed.html not found")

