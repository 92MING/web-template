# -*- coding: utf-8 -*-
"""Distributed network management routes."""

from __future__ import annotations

import os
import hmac
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
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
from core.utils.network_utils.helper_funcs import get_ip_geo_info
from ...app import get_resources, internal_admin_path, on_before_app_created

router = APIRouter(tags=["Distributed"])


@on_before_app_created
def register_distributed_routes(app):
    app.include_router(router, prefix=internal_admin_path("api/distributed"))
    register_distributed_html_routes(app)


class RegisterNodeRequest(BaseModel):
    node_id: str
    name: str = ""
    host: str
    port: int
    relation: NodeRelation = "ff"
    admin_password_hash: str = ""
    gsd_port: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)
    allow_child_api_forward: bool = False


class ConnectNodeRequest(BaseModel):
    node_id: str
    name: str = ""
    host: str
    port: int
    relation: NodeRelation = "ff"
    password: str
    gsd_port: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)
    allow_child_api_forward: bool = False


class InitiateConnectRequest(BaseModel):
    target_host: str
    target_port: int
    password: str
    relation: NodeRelation = "ff"
    target_node_id: str = ""
    target_name: str = ""
    target_gsd_port: int = 0
    self_host: str = ""
    self_port: int = 0
    self_gsd_port: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)
    allow_child_api_forward: bool = False


_CONNECTION_BANS: dict[str, dict[str, float | int]] = {}
_CONNECTION_BAN_NAMESPACE = "__distributed_connection_bans__"
_CONNECTION_AUTH_BAN_THRESHOLD = 3
_CONNECTION_AUTH_BAN_STEP_SECONDS = 10 * 60
_FORWARD_ROUND_ROBIN: dict[str, int] = {}

_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _client_ip(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    return request.client.host if request.client else "unknown"


def _connection_ban_record(ip: str) -> dict[str, float | int]:
    try:
        raw = AppSharedData.Get().get_shared_dict_value(_CONNECTION_BAN_NAMESPACE, ip)
    except Exception:
        raw = _CONNECTION_BANS.get(ip)
    if not isinstance(raw, dict):
        return {"failures": 0, "banned_until": 0.0}
    return {
        "failures": int(raw.get("failures", 0)),
        "banned_until": float(raw.get("banned_until", 0.0)),
    }


def _save_connection_ban_record(ip: str, record: dict[str, float | int]) -> None:
    safe_record = {
        "failures": int(record.get("failures", 0)),
        "banned_until": float(record.get("banned_until", 0.0)),
    }
    try:
        AppSharedData.Get().set_shared_dict_value(_CONNECTION_BAN_NAMESPACE, ip, safe_record)
    except Exception:
        _CONNECTION_BANS[ip] = safe_record


def _connection_password_env_for_relation(relation: NodeRelation) -> str:
    if relation == "pc":
        return "PARENT_CHILD_NODE_CONN_PASS"
    return "FRIEND_NODE_CONN_PASS"


def _verify_connection_password(relation: NodeRelation, password: str) -> bool:
    env_name = _connection_password_env_for_relation(relation)
    configured = os.getenv(env_name)
    if configured is not None:
        return hmac.compare_digest(str(configured), str(password))
    from core.server.security.admin_password import verify_admin_password
    return verify_admin_password(password)


def _record_connection_auth_failure(ip: str) -> None:
    record = _connection_ban_record(ip)
    failures = int(record.get("failures", 0)) + 1
    record["failures"] = failures
    if failures >= _CONNECTION_AUTH_BAN_THRESHOLD:
        ban_seconds = max(
            _CONNECTION_AUTH_BAN_STEP_SECONDS,
            (failures - _CONNECTION_AUTH_BAN_THRESHOLD + 1) * _CONNECTION_AUTH_BAN_STEP_SECONDS,
        )
        record["banned_until"] = time.time() + ban_seconds
    _save_connection_ban_record(ip, record)


def _check_connection_auth(ip: str, relation: NodeRelation, password: str) -> None:
    record = _connection_ban_record(ip)
    banned_until = float(record.get("banned_until", 0.0))
    now = time.time()
    if banned_until > now:
        retry_after = int(max(1.0, banned_until - now))
        raise HTTPException(status_code=429, detail=f"IP temporarily banned. Retry after {retry_after}s.")
    if banned_until:
        record["banned_until"] = 0.0
        _save_connection_ban_record(ip, record)
    if _verify_connection_password(relation, password):
        record["failures"] = 0
        record["banned_until"] = 0.0
        _save_connection_ban_record(ip, record)
        return
    _record_connection_auth_failure(ip)
    raise HTTPException(status_code=401, detail="Invalid node connection password")


def _with_default_parent_metadata(relation: NodeRelation, metadata: dict[str, str]) -> dict[str, str]:
    if relation != "pc":
        return dict(metadata)
    out = dict(metadata)
    if not any(out.get(key) for key in ("parent_id", "parent_node_id")):
        out["parent_id"] = AppSharedData.Get().instance_uuid
    return out


def _pc_metadata(parent_id: str, metadata: dict[str, str]) -> dict[str, str]:
    out = dict(metadata)
    out["parent_id"] = parent_id
    return out


def _local_relation_metadata(relation: NodeRelation, parent_id: str, metadata: dict[str, str]) -> dict[str, str]:
    if relation == "pc":
        return _pc_metadata(parent_id, metadata)
    return dict(metadata)


def _host_geo_metadata(host: str) -> dict[str, str]:
    info = get_ip_geo_info(host)
    if not info:
        return {}
    metadata: dict[str, str] = {}
    if info["source"]:
        metadata["ip_location"] = info["source"]
    if info["country"]:
        metadata["ip_country"] = info["country"]
    if info["country_code"]:
        metadata["ip_country_code"] = info["country_code"]
    if info["subdivision"]:
        metadata["ip_subdivision"] = info["subdivision"]
    if info["city"]:
        metadata["ip_city"] = info["city"]
    if info["timezone"]:
        metadata["ip_timezone"] = info["timezone"]
    if info["latitude"] is not None:
        metadata["ip_latitude"] = str(info["latitude"])
    if info["longitude"] is not None:
        metadata["ip_longitude"] = str(info["longitude"])
    return metadata


async def _register_node_and_gsd_peer(
    *,
    node_id: str,
    name: str,
    host: str,
    port: int,
    relation: NodeRelation,
    gsd_port: int = 0,
    metadata: dict[str, str] | None = None,
    admin_password_hash: str = "",
    allow_child_api_forward: bool = False,
) -> Node:
    registry = NodeRegistry.get_instance()
    node = await registry.register(
        node_id=node_id,
        name=name,
        host=host,
        port=port,
        relation=relation,
        admin_password_hash=admin_password_hash,
        gsd_port=gsd_port,
        metadata=metadata or {},
        allow_child_api_forward=allow_child_api_forward,
    )
    try:
        from core.server.shared_dict import GlobalSharedDict
        GlobalSharedDict.get_instance().register_peer(
            node_id=node.node_id,
            host=node.host,
            port=node.gsd_port or node.port,
            relation=node.relation,
        )
    except Exception:
        pass
    return node


def _self_node_info() -> dict[str, Any]:
    sd = AppSharedData.Get()
    cfg = Config.GetConfig().server_config
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    return {
        "node_id": sd.instance_uuid,
        "name": cfg.name or sd.instance_uuid,
        "host": os.getenv("__HOST__", "127.0.0.1"),
        "port": int(os.getenv("__PORT__", "0")),
        "gsd_port": int(getattr(gsd, "_listen_port", 0) or 0),
    }


async def _initiate_connect(req: InitiateConnectRequest) -> dict[str, Any]:
    import aiohttp

    self_info = _self_node_info()
    self_id = str(self_info["node_id"])
    advertised_host = req.self_host.strip() or str(self_info["host"])
    advertised_port = req.self_port or int(self_info["port"])
    advertised_gsd_port = req.self_gsd_port or int(self_info.get("gsd_port") or 0)
    remote_metadata = _local_relation_metadata(req.relation, self_id, req.metadata)
    payload = {
        "node_id": self_id,
        "name": str(self_info["name"]),
        "host": advertised_host,
        "port": advertised_port,
        "gsd_port": advertised_gsd_port,
        "relation": req.relation,
        "password": req.password,
        "metadata": remote_metadata,
        "allow_child_api_forward": req.allow_child_api_forward,
    }
    path = Config.GetConfig().server_config.get_internal_admin_path("api/distributed/connect")
    url = f"http://{req.target_host}:{req.target_port}{path}"
    timeout = aiohttp.ClientTimeout(total=10.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            try:
                response_payload = await resp.json()
            except Exception:
                response_payload = {"text": await resp.text()}
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail=response_payload)

    remote_self = response_payload.get("self") if isinstance(response_payload, dict) else None
    if not isinstance(remote_self, dict):
        raise HTTPException(status_code=502, detail="Remote connect response missed self node info")
    target_node_id = str(remote_self.get("node_id") or req.target_node_id).strip()
    if not target_node_id:
        raise HTTPException(status_code=502, detail="Remote connect response missed node_id")
    target_host = str(remote_self.get("host") or req.target_host)
    target_port = int(remote_self.get("port") or req.target_port)
    target_name = str(remote_self.get("name") or req.target_name or target_node_id)
    target_gsd_port = int(remote_self.get("gsd_port") or req.target_gsd_port or 0)
    local_metadata = _local_relation_metadata(req.relation, self_id, req.metadata)
    node = await _register_node_and_gsd_peer(
        node_id=target_node_id,
        name=target_name,
        host=target_host,
        port=target_port,
        gsd_port=target_gsd_port,
        relation=req.relation,
        metadata=local_metadata,
        allow_child_api_forward=req.allow_child_api_forward,
    )
    return {
        "ok": True,
        "node": node.to_dict(),
        "remote": response_payload,
    }


class AuthChallengeResponse(BaseModel):
    nonce: str
    timestamp: float


class AuthVerifyRequest(BaseModel):
    nonce: str
    timestamp: float
    hash: str


class BroadcastRequest(BaseModel):
    message: dict[str, Any]
    target_relations: list[NodeRelation] = Field(default_factory=lambda: ["ff", "pc", "pp"])
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


class UpdateNodeRequest(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    relation: NodeRelation | None = None
    gsd_port: int | None = None
    metadata: dict[str, str] | None = None
    allow_child_api_forward: bool | None = None


class ChangeNodeRelationRequest(BaseModel):
    relation: NodeRelation
    parent_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    allow_child_api_forward: bool = False
    sync_remote: bool = True


class SyncRelationRequest(BaseModel):
    node_id: str
    name: str = ""
    host: str
    port: int
    relation: NodeRelation
    gsd_port: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)
    allow_child_api_forward: bool = False

class SetWorkersRequest(BaseModel):
    workers: int = Field(ge=1)
    persist: bool = False
    restart: bool = False


class GSDSetBody(BaseModel):
    value: Any = None
    expire_seconds: int | None = Field(default=None, ge=1)


class GSDDeleteByPrefixBody(BaseModel):
    prefix: str = ""
    dry_run: bool = False
    limit: int = Field(default=1000, ge=1, le=10000)


def _gsd_value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, bytes | bytearray):
        return "bytes"
    return "string"


def _gsd_size_bytes(value: Any) -> int:
    try:
        import json

        if isinstance(value, bytes | bytearray):
            return len(value)
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return len(str(value).encode("utf-8", errors="replace"))


def _gsd_item_payload(namespace: str, item: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    expire_at = item.get("expire_at")
    ttl_seconds: float | None = None
    if expire_at:
        try:
            ttl_seconds = max(0.0, float(expire_at) - current_time)
        except (TypeError, ValueError):
            ttl_seconds = None
    value = item.get("value")
    key = str(item.get("key") or "")
    return {
        **item,
        "namespace": namespace,
        "ttl_seconds": ttl_seconds,
        "ttl_state": "expiring" if ttl_seconds is not None else "persistent",
        "value_kind": _gsd_value_kind(value),
        "key_size_bytes": len(key.encode("utf-8", errors="replace")),
        "size_bytes_estimate": _gsd_size_bytes(value),
    }


def _gsd_prefix_label(key: str) -> str:
    for delimiter in (":", "/", "."):
        if delimiter in key:
            return key.split(delimiter, 1)[0] + delimiter
    return "(root)"


_NODE_PARENT_METADATA_KEYS = ("parent_id", "parent_node_id")


def _relation_metadata(
    relation: NodeRelation,
    *,
    parent_id: str | None,
    metadata: dict[str, str] | None = None,
) -> dict[str, str]:
    out = dict(metadata or {})
    if relation == "pc":
        normalized_parent_id = str(parent_id or AppSharedData.Get().instance_uuid).strip()
        out["parent_id"] = normalized_parent_id
        out["parent_node_id"] = ""
        return out
    for key in _NODE_PARENT_METADATA_KEYS:
        out[key] = ""
    return out


async def _apply_relation_record(req: SyncRelationRequest) -> Node:
    return await _register_node_and_gsd_peer(
        node_id=req.node_id,
        name=req.name,
        host=req.host,
        port=req.port,
        relation=req.relation,
        gsd_port=req.gsd_port,
        metadata=req.metadata,
        allow_child_api_forward=req.allow_child_api_forward,
    )

def _set_workers(req: SetWorkersRequest) -> dict[str, Any]:
    config = Config.GetConfig().model_copy(deep=True)
    config.server_config.worker = req.workers
    Config.SetConfig(config)

    persisted_path: str | None = None
    persist = req.persist or req.restart
    if persist:
        config_info = Config.DescribeRuntimeConfigPath(prefer_mode_specific=True)
        saved_path = config.write_to_path(config_info["write_path"])
        persisted_path = str(saved_path)
        os.environ["__CONFIG_FILE_PATH__"] = persisted_path
        os.environ["__WRITABLE_CONFIG_FILE_PATH__"] = persisted_path

    control_status: dict[str, Any] | None = None
    if req.restart:
        from core.server.runtime_control import request_control_action

        control_status = request_control_action(
            "restart",
            reason=f"Distributed set_workers={req.workers}",
        )
    return {
        "ok": True,
        "workers": req.workers,
        "persisted": persisted_path is not None,
        "config_path": persisted_path,
        "restart_requested": req.restart,
        "control": control_status,
    }


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
        headers = await _remote_admin_headers(session, node)
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            detail_text = await resp.text()
            raise HTTPException(status_code=resp.status, detail=f"Node {node.node_id} returned {resp.status}: {detail_text}")


def _find_plain_admin_password() -> str | None:
    env_password = os.getenv("ADMIN_PW", "").strip()
    if env_password:
        return env_password
    root = Path.cwd()
    try:
        env_files = list(root.rglob("*.env"))
    except Exception:
        env_files = []
    env_files.sort(key=lambda p: (len(p.parts), str(p)))
    for env_path in env_files:
        try:
            text = env_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^ADMIN_PW\s*=\s*(.+)$", line)
            if not match:
                continue
            password = match.group(1).strip().strip('"').strip("'")
            if password:
                return password
    return None


async def _remote_admin_headers(session: Any, node: Node) -> dict[str, str]:
    explicit_api_key = str(
        node.metadata.get("admin_api_key")
        or node.metadata.get("admin_apikey")
        or node.metadata.get("admin_bearer_token")
        or ""
    ).strip()
    if explicit_api_key:
        return {"Authorization": f"Bearer {explicit_api_key}"}

    password = _find_plain_admin_password()
    if not password:
        return {}
    login_path = Config.GetConfig().server_config.get_internal_admin_path("login")
    url = f"http://{node.host}:{node.port}{login_path}"
    try:
        async with session.post(url, json={"password": password}) as resp:
            if resp.status != 200:
                return {}
            payload = await resp.json()
    except Exception:
        return {}
    api_key = payload.get("api_key") if isinstance(payload, dict) else None
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _csv_header(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _truthy_header(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _format_bytes(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "—"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"


def _cached_gpu_metadata(shared: Any) -> str | None:
    payload: Any = None
    try:
        from core.server.routes.system.monitoring import _get_local_gpu_details

        local_details = _get_local_gpu_details()
        if local_details is not None:
            payload = local_details.model_dump(mode="python")
    except Exception:
        payload = None
    if payload is None:
        try:
            payload = shared.get_cache("system:gpu_details")
        except Exception:
            payload = None
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    try:
        gpu_count = int(summary.get("gpu_count") or 0)
    except (TypeError, ValueError):
        gpu_count = 0
    if gpu_count <= 0:
        return None
    util = summary.get("avg_utilization_percent")
    total_memory = int(summary.get("total_memory_bytes") or 0)
    used_memory = int(summary.get("used_memory_bytes") or 0)
    parts = [f"{gpu_count} GPU"]
    if util is not None:
        try:
            parts.append(f"{float(util):.1f}%")
        except (TypeError, ValueError):
            pass
    if total_memory > 0:
        parts.append(f"{_format_bytes(used_memory)}/{_format_bytes(total_memory)}")
    return " ".join(parts)


def _node_runtime_metadata() -> dict[str, str]:
    shared = AppSharedData.Get()
    out: dict[str, str] = {}
    try:
        runtime = shared.get_runtime_meta()
        out["handled_requests"] = str(runtime.get("request_count_total", 0))
        out["load"] = f"{runtime.get('worker_count', 0)} worker(s)"
        start_time = runtime.get("server_start_time")
        if start_time:
            out["started_at"] = str(start_time)
    except Exception:
        pass

    gpu = _cached_gpu_metadata(shared)
    if gpu:
        out["gpu"] = gpu

    try:
        snapshot = shared.get_latest_system_snapshot()
    except Exception:
        snapshot = None
    if not isinstance(snapshot, dict):
        return out

    if "cpu_avg" in snapshot:
        out["cpu"] = f"{float(snapshot.get('cpu_avg') or 0):.1f}%"
    if "mem_pct" in snapshot:
        out["memory"] = f"{float(snapshot.get('mem_pct') or 0):.1f}% ({_format_bytes(snapshot.get('mem_used'))}/{_format_bytes(snapshot.get('mem_total'))})"
    disk_data = snapshot.get("disk_data")
    if isinstance(disk_data, dict) and disk_data:
        try:
            busiest_disk = max(
                (item for item in disk_data.values() if isinstance(item, dict)),
                key=lambda item: float(item.get("percent") or 0),
            )
            out["disk"] = f"{float(busiest_disk.get('percent') or 0):.1f}%"
        except ValueError:
            pass
    network_data = snapshot.get("network_data")
    if isinstance(network_data, dict) and network_data:
        sent = sum(int(item.get("bytes_sent") or 0) for item in network_data.values() if isinstance(item, dict))
        recv = sum(int(item.get("bytes_recv") or 0) for item in network_data.values() if isinstance(item, dict))
        out["network"] = f"↑{_format_bytes(sent)} ↓{_format_bytes(recv)}"
    if "process_count" in snapshot:
        out["processes"] = str(int(snapshot.get("process_count") or 0))
    return out


async def _merge_node_metadata(registry: NodeRegistry, node: Node, metadata: dict[str, str]) -> None:
    if not metadata:
        return
    await registry.register(
        node_id=node.node_id,
        name=node.name,
        host=node.host,
        port=node.port,
        relation=node.relation,
        admin_password_hash=node.admin_password_hash,
        gsd_port=node.gsd_port,
        metadata=metadata,
        allow_child_api_forward=node.allow_child_api_forward,
    )


async def _record_probe_result(registry: NodeRegistry, node: Node, *, success: bool, rtt_ms: float | None = None) -> None:
    if hasattr(registry, "record_probe_result"):
        await registry.record_probe_result(node.node_id, success=success, rtt_ms=rtt_ms)
    else:
        await registry.update_health(node.node_id, success=success, rtt_ms=rtt_ms)


async def _record_forward_success(registry: NodeRegistry, node: Node) -> None:
    await registry.update_health(node.node_id, success=True)
    latest = await registry.get(node.node_id)
    if latest is None or not hasattr(registry, "register"):
        return
    metadata = dict(latest.metadata)
    try:
        forwarded_count = int(metadata.get("forwarded_requests") or metadata.get("forwarded") or "0")
    except ValueError:
        forwarded_count = 0
    forwarded_count += 1
    metadata["forwarded"] = str(forwarded_count)
    metadata["forwarded_requests"] = str(forwarded_count)
    metadata["last_forwarded_at"] = str(time.time())
    await registry.register(
        node_id=latest.node_id,
        name=latest.name,
        host=latest.host,
        port=latest.port,
        relation=latest.relation,
        admin_password_hash=latest.admin_password_hash,
        gsd_port=latest.gsd_port,
        metadata=metadata,
        allow_child_api_forward=latest.allow_child_api_forward,
    )


async def _record_forward_failure(registry: NodeRegistry, node: Node) -> None:
    await registry.update_health(node.node_id, success=False)
    latest = await registry.get(node.node_id)
    if latest is None or not hasattr(registry, "register"):
        return
    metadata = dict(latest.metadata)
    try:
        failed_count = int(metadata.get("forward_failed") or "0")
    except ValueError:
        failed_count = 0
    failed_count += 1
    metadata["forward_failed"] = str(failed_count)
    metadata["last_forward_failed_at"] = str(time.time())
    await registry.register(
        node_id=latest.node_id,
        name=latest.name,
        host=latest.host,
        port=latest.port,
        relation=latest.relation,
        admin_password_hash=latest.admin_password_hash,
        gsd_port=latest.gsd_port,
        metadata=metadata,
        allow_child_api_forward=latest.allow_child_api_forward,
    )


def _forward_balance_head_size(candidates: list[Node]) -> int:
    if not candidates:
        return 0
    first = candidates[0]
    first_health_rank = 0 if first.health_status == "healthy" else 1
    fastest_rtt = first.rtt_ms if first.rtt_ms is not None else float("inf")
    if fastest_rtt == float("inf"):
        max_rtt = float("inf")
    else:
        max_rtt = max(fastest_rtt + 5.0, fastest_rtt * 1.25)

    size = 0
    for node in candidates:
        health_rank = 0 if node.health_status == "healthy" else 1
        if health_rank != first_health_rank:
            break
        node_rtt = node.rtt_ms if node.rtt_ms is not None else float("inf")
        if node_rtt > max_rtt:
            break
        size += 1
    return max(1, size)


def _forward_headers(request: Request, self_id: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        key_l = key.lower()
        if key_l in _HOP_BY_HOP_HEADERS:
            continue
        if key_l.startswith("x-distributed-"):
            continue
        headers[key] = value
    headers["x-distributed-from-node"] = self_id
    return headers


async def _forward_candidates(request: Request) -> list[Node]:
    registry = NodeRegistry.get_instance()
    self_id = AppSharedData.Get().instance_uuid
    target_ids = set(_csv_header(request.headers.get("x-distributed-target-nodes")))
    include_self = _truthy_header(request.headers.get("x-distributed-include-self"))
    nodes = await registry.all()
    candidates: list[Node] = []
    for node in nodes:
        if target_ids and node.node_id not in target_ids:
            continue
        if node.health_status == "unreachable":
            continue
        if not await registry.can_forward_to(self_id, node.node_id):
            continue
        candidates.append(node)

    if include_self and (not target_ids or self_id in target_ids):
        try:
            self_port = int(os.getenv("__PORT__", "0"))
        except ValueError:
            self_port = 0
        if self_port > 0:
            cfg = Config.GetConfig().server_config
            candidates.append(Node(
                node_id=self_id,
                name=cfg.name or self_id,
                host="127.0.0.1",
                port=self_port,
                relation="pp",
                health_status="healthy",
                rtt_ms=0.0,
            ))

    candidates.sort(key=lambda node: (
        0 if node.health_status == "healthy" else 1,
        node.rtt_ms if node.rtt_ms is not None else float("inf"),
        node.node_id,
    ))
    if len(candidates) <= 1:
        return candidates

    balance_count = _forward_balance_head_size(candidates)
    rr_key = "|".join([
        request.method.upper(),
        str(request.url.path),
        request.headers.get("x-distributed-target-nodes", ""),
        "self" if include_self else "remote",
    ])
    idx = _FORWARD_ROUND_ROBIN.get(rr_key, 0)
    _FORWARD_ROUND_ROBIN[rr_key] = idx + 1
    head = candidates[:balance_count]
    offset = idx % len(head)
    return [*head[offset:], *head[:offset], *candidates[balance_count:]]


def _response_headers(headers: Any, node: Node) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        key_l = str(key).lower()
        if key_l in _HOP_BY_HOP_HEADERS:
            continue
        out[str(key)] = str(value)
    out["x-distributed-node-id"] = node.node_id
    if node.name:
        out["x-distributed-node-name"] = node.name
    return out


async def _stream_proxy_response(
    session: Any,
    response: Any,
    registry: NodeRegistry | None = None,
    node: Node | None = None,
):
    try:
        async with response:
            async for chunk in response.content.iter_chunked(65536):
                if chunk:
                    yield chunk
        if registry is not None and node is not None:
            await _record_forward_success(registry, node)
    except Exception:
        if registry is not None and node is not None:
            await _record_forward_failure(registry, node)
        raise
    finally:
        await session.close()


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
                    await _record_probe_result(registry, node, success=True, rtt_ms=rtt_ms)
                    remote_metadata = payload.get("metadata") if isinstance(payload, dict) else None
                    if isinstance(remote_metadata, dict):
                        await _merge_node_metadata(
                            registry,
                            node,
                            {str(key): str(value) for key, value in remote_metadata.items()},
                        )
                    return {
                        "ok": True,
                        "node_id": node.node_id,
                        "status_code": resp.status,
                        "rtt_ms": rtt_ms,
                        "response": payload,
                    }
                await _record_probe_result(registry, node, success=False)
                return {
                    "ok": False,
                    "node_id": node.node_id,
                    "status_code": resp.status,
                    "rtt_ms": rtt_ms,
                    "response": payload,
                    "error": f"Health endpoint returned {resp.status}",
                }
    except Exception as exc:
        await _record_probe_result(registry, node, success=False)
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
    cfg = Config.GetConfig().server_config
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    return {
        "node_id": sd.instance_uuid,
        "name": cfg.name or sd.instance_uuid,
        "host": os.getenv("__HOST__", "127.0.0.1"),
        "port": int(os.getenv("__PORT__", "0")),
        "gsd_port": int(getattr(gsd, "_listen_port", 0) or 0),
        "worker_count": len(sd.workers),
        "control_supported": os.getenv("__SERVER_CONTROL_SUPPORTED__", "0").strip() in ("1", "true", "yes"),
        "metadata": _node_runtime_metadata(),
    }


# ── health endpoint (called by other nodes) ──────────────────────────────

@router.get("/health")
async def distributed_health() -> dict[str, Any]:
    sd = AppSharedData.Get()
    cfg = Config.GetConfig().server_config
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    return {
        "node_id": sd.instance_uuid,
        "name": cfg.name or sd.instance_uuid,
        "gsd_port": int(getattr(gsd, "_listen_port", 0) or 0),
        "status": "ok",
        "worker_count": len(sd.workers),
        "ready_workers": sd.count_ready_workers(),
        "metadata": _node_runtime_metadata(),
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
        geo_metadata = _host_geo_metadata(node.host)
        if geo_metadata:
            row_metadata = row.get("metadata")
            row["metadata"] = {**(row_metadata if isinstance(row_metadata, dict) else {}), **geo_metadata}
        route = await registry.management_route(self_id, node.node_id)
        row["management"] = {
            "can_manage": bool(route),
            "route": [hop.node_id for hop in route or []],
        }
        result.append(row)
    return result


@router.post("/nodes")
async def register_node(req: RegisterNodeRequest) -> dict[str, Any]:
    node = await _register_node_and_gsd_peer(
        node_id=req.node_id,
        name=req.name,
        host=req.host,
        port=req.port,
        relation=req.relation,
        admin_password_hash=req.admin_password_hash,
        gsd_port=req.gsd_port,
        metadata=_with_default_parent_metadata(req.relation, req.metadata),
        allow_child_api_forward=req.allow_child_api_forward,
    )
    return node.to_dict()


@router.post("/connect")
async def connect_node(req: ConnectNodeRequest, request: Request) -> dict[str, Any]:
    """Accept a password-protected connection request from another node."""
    client_ip = _client_ip(request)
    _check_connection_auth(client_ip, req.relation, req.password)
    node = await _register_node_and_gsd_peer(
        node_id=req.node_id,
        name=req.name,
        host=req.host,
        port=req.port,
        relation=req.relation,
        gsd_port=req.gsd_port,
        metadata=req.metadata,
        allow_child_api_forward=req.allow_child_api_forward,
    )
    return {
        "ok": True,
        "node": node.to_dict(),
        "self": _self_node_info(),
    }


@router.post("/connect-to")
async def initiate_connect_node(req: InitiateConnectRequest) -> dict[str, Any]:
    """Initiate a password-protected connection handshake with a remote node."""
    return await _initiate_connect(req)


@router.get("/nodes/{node_id}")
async def get_node(node_id: str) -> dict[str, Any]:
    registry = NodeRegistry.get_instance()
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node.to_dict()


@router.patch("/nodes/{node_id}")
async def update_node(node_id: str, req: UpdateNodeRequest) -> dict[str, Any]:
    registry = NodeRegistry.get_instance()
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    metadata = dict(node.metadata)
    if req.metadata is not None:
        metadata.update(req.metadata)
    relation = req.relation if req.relation is not None else node.relation
    metadata = _with_default_parent_metadata(relation, metadata)
    updated = await registry.register(
        node_id=node.node_id,
        name=req.name if req.name is not None else node.name,
        host=req.host if req.host is not None else node.host,
        port=req.port if req.port is not None else node.port,
        relation=relation,
        admin_password_hash=node.admin_password_hash,
        gsd_port=req.gsd_port if req.gsd_port is not None else node.gsd_port,
        metadata=metadata,
        allow_child_api_forward=(
            req.allow_child_api_forward
            if req.allow_child_api_forward is not None
            else node.allow_child_api_forward
        ),
    )
    return updated.to_dict()


@router.post("/nodes/{node_id}/relation")
async def change_node_relation(node_id: str, req: ChangeNodeRelationRequest) -> dict[str, Any]:
    registry = NodeRegistry.get_instance()
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    self_info = _self_node_info()
    self_id = str(self_info["node_id"])
    parent_id = str(req.parent_id or (self_id if req.relation == "pc" else "")).strip() or None
    metadata = _relation_metadata(req.relation, parent_id=parent_id, metadata={**node.metadata, **req.metadata})
    remote_result: dict[str, Any] | None = None

    if req.sync_remote:
        route = await registry.management_route(self_id, node_id)
        if route is None or not route:
            raise HTTPException(status_code=403, detail="Node is outside this node's management scope")
        remote_record = {
            "node_id": self_id,
            "name": str(self_info["name"]),
            "host": str(self_info["host"]),
            "port": int(self_info["port"]),
            "gsd_port": int(self_info.get("gsd_port") or 0),
            "relation": req.relation,
            "metadata": metadata,
            "allow_child_api_forward": req.allow_child_api_forward,
        }
        remote_result = await send_command_to_node(
            node_id,
            CommandRequest(command="sync_relation", args=remote_record),
        )

    updated = await _register_node_and_gsd_peer(
        node_id=node.node_id,
        name=node.name,
        host=node.host,
        port=node.port,
        relation=req.relation,
        admin_password_hash=node.admin_password_hash,
        gsd_port=node.gsd_port,
        metadata=metadata,
        allow_child_api_forward=req.allow_child_api_forward,
    )
    return {"ok": True, "node": updated.to_dict(), "remote": remote_result}


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


# ── management commands ──────────────────────────────────────────────────

@router.post("/nodes/{node_id}/command")
async def send_command_to_node(node_id: str, req: CommandRequest) -> dict[str, Any]:
    """Send a management command through pc/pp management scope."""
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


# ── receive command ──────────────────────────────────────────────────────

@router.post("/command")
async def receive_command(req: CommandRequest) -> dict[str, Any]:
    """Receive a management command from a node with management authority."""
    from core.server.runtime_control import request_control_action

    if req.command == "restart":
        try:
            request_control_action("restart", reason="Distributed node command")
            return {"ok": True, "message": "Restart requested"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    elif req.command == "stop":
        try:
            request_control_action("stop", reason="Distributed node command")
            return {"ok": True, "message": "Stop requested"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    elif req.command == "set_workers":
        payload = SetWorkersRequest.model_validate(req.args)
        result = _set_workers(payload)
        return {"message": "workers updated", **result}
    elif req.command == "rename":
        name = str(req.args.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Missing name")
        Config.GetConfig().server_config.name = name
        return {"ok": True, "message": "name updated", "name": name}
    elif req.command == "register_node":
        payload = RegisterNodeRequest.model_validate(req.args)
        node = await register_node(payload)
        return {"ok": True, "node": node}
    elif req.command == "connect_to_node":
        payload = InitiateConnectRequest.model_validate(req.args)
        result = await _initiate_connect(payload)
        return {"ok": True, **result}
    elif req.command == "sync_relation":
        payload = SyncRelationRequest.model_validate(req.args)
        node = await _apply_relation_record(payload)
        return {"ok": True, "node": node.to_dict()}
    elif req.command == "update_node":
        target_id = str(req.args.get("node_id") or "").strip()
        if not target_id:
            raise HTTPException(status_code=400, detail="Missing node_id")
        payload = UpdateNodeRequest.model_validate(req.args.get("patch") or {})
        node = await update_node(target_id, payload)
        return {"ok": True, "node": node}
    elif req.command == "delete_node":
        target_id = str(req.args.get("node_id") or "").strip()
        if not target_id:
            raise HTTPException(status_code=400, detail="Missing node_id")
        result = await unregister_node(target_id)
        return {"ok": True, **result}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown command: {req.command}")


# ── API forwarding ────────────────────────────────────────────────────────

@router.api_route("/forward/{forward_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def forward_api_request(forward_path: str, request: Request) -> Response:
    """Forward an HTTP request to the best available node for the target path.

    Control headers:
    * ``x-distributed-target-nodes``: optional comma-separated node ids.
    * ``x-distributed-include-self``: include this node as a candidate.
    * ``x-distributed-stream-input``: do not buffer request body.
    * ``x-distributed-stream-output``: return the remote body as a stream.
    """
    import aiohttp

    candidates = await _forward_candidates(request)
    if not candidates:
        raise HTTPException(status_code=503, detail="No eligible distributed node is available for API forwarding")

    registry = NodeRegistry.get_instance()
    self_id = AppSharedData.Get().instance_uuid
    target_path = "/" + forward_path.lstrip("/")
    query = request.url.query
    headers = _forward_headers(request, self_id)
    method = request.method.upper()
    stream_input = _truthy_header(request.headers.get("x-distributed-stream-input"))
    stream_output = _truthy_header(request.headers.get("x-distributed-stream-output"))
    body = None if stream_input else await request.body()
    errors: list[dict[str, str]] = []

    for index, node in enumerate(candidates):
        url = f"http://{node.host}:{node.port}{target_path}"
        if query:
            url += f"?{query}"
        timeout = aiohttp.ClientTimeout(total=None if stream_output else 30.0, sock_connect=5.0, sock_read=None if stream_output else 30.0)
        session = aiohttp.ClientSession(timeout=timeout)
        try:
            data = request.stream() if stream_input else body
            response = await session.request(method, url, headers=headers, data=data)
            content_type = str(response.headers.get("content-type") or "")
            should_stream = stream_output or "text/event-stream" in content_type.lower()
            if should_stream and response.status < 500:
                return StreamingResponse(
                    _stream_proxy_response(session, response, registry, node),
                    status_code=response.status,
                    headers=_response_headers(response.headers, node),
                    media_type=content_type or None,
                )

            async with response:
                content = await response.read()
                response_headers = _response_headers(response.headers, node)
                if response.status < 500 and response.status != 404:
                    await session.close()
                    await _record_forward_success(registry, node)
                    return Response(
                        content=content,
                        status_code=response.status,
                        headers=response_headers,
                        media_type=content_type or None,
                    )
                errors.append({"node_id": node.node_id, "error": f"HTTP {response.status}"})
                await _record_forward_failure(registry, node)
                if stream_input or index == len(candidates) - 1:
                    await session.close()
                    return Response(
                        content=content,
                        status_code=response.status,
                        headers=response_headers,
                        media_type=content_type or None,
                    )
                await session.close()
        except Exception as exc:
            await session.close()
            await _record_forward_failure(registry, node)
            errors.append({"node_id": node.node_id, "error": f"{type(exc).__name__}: {exc}"})
            if stream_input:
                break

    raise HTTPException(status_code=502, detail={"message": "All distributed forward candidates failed", "errors": errors})


# ── global shared dict sync ──────────────────────────────────────────────

def _gsd_visible_items(namespace: str) -> list[dict[str, Any]]:
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    raw_ns = gsd._local_data.get(namespace, {})
    now = time.time()
    items: list[dict[str, Any]] = []
    for key, entry in raw_ns.items():
        exp = entry.get("exp")
        deleted = bool(entry.get("deleted"))
        if exp and exp <= now:
            continue
        if deleted:
            continue
        items.append({
            "key": key,
            "value": entry.get("v"),
            "updated_at": entry.get("ts"),
            "expire_at": exp,
        })
    items.sort(key=lambda item: str(item["key"]))
    return items


@router.get("/gsd/namespaces")
async def gsd_namespaces() -> dict[str, Any]:
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    return {
        "namespaces": [
            {"namespace": namespace, "count": len(_gsd_visible_items(namespace))}
            for namespace in sorted(gsd._local_data)
        ]
    }


@router.get("/gsd/items")
async def gsd_items(
    namespace: str = "default",
    prefix: str = "",
    q: str = "",
    value_kind: str = "",
    ttl_state: str = "",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    safe_page = max(1, int(page))
    safe_page_size = min(500, max(1, int(page_size)))
    prefix_text = str(prefix or "")
    q_text = str(q or "").lower()
    kind_text = str(value_kind or "")
    ttl_state_text = str(ttl_state or "")
    visible_items = [_gsd_item_payload(namespace, item) for item in _gsd_visible_items(namespace)]
    items = [
        item for item in visible_items
        if (not prefix_text or str(item["key"]).startswith(prefix_text))
        and (not q_text or q_text in str(item["key"]).lower())
        and (not kind_text or item.get("value_kind") == kind_text)
        and (not ttl_state_text or item.get("ttl_state") == ttl_state_text)
    ]
    total = len(items)
    start = (safe_page - 1) * safe_page_size
    page_items = items[start:start + safe_page_size]
    return {
        "namespace": namespace,
        "items": page_items,
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
        "page_count": max(1, (total + safe_page_size - 1) // safe_page_size),
    }


@router.get("/gsd/summary")
async def gsd_summary(
    namespace: str = "default",
    prefix: str = "",
    q: str = "",
    value_kind: str = "",
    ttl_state: str = "",
) -> dict[str, Any]:
    prefix_text = str(prefix or "")
    q_text = str(q or "").lower()
    kind_text = str(value_kind or "")
    ttl_state_text = str(ttl_state or "")
    now = time.time()
    items = [
        _gsd_item_payload(namespace, item, now)
        for item in _gsd_visible_items(namespace)
        if (not prefix_text or str(item["key"]).startswith(prefix_text))
        and (not q_text or q_text in str(item["key"]).lower())
        and (not kind_text or _gsd_value_kind(item.get("value")) == kind_text)
    ]
    if ttl_state_text:
        items = [item for item in items if item.get("ttl_state") == ttl_state_text]
    ttl_values = [float(item["ttl_seconds"]) for item in items if item.get("ttl_seconds") is not None]
    ttl_buckets = {
        "lt_1m": {"key": "lt_1m", "label": "< 1m", "count": 0},
        "lt_1h": {"key": "lt_1h", "label": "< 1h", "count": 0},
        "lt_1d": {"key": "lt_1d", "label": "< 1d", "count": 0},
        "gte_1d": {"key": "gte_1d", "label": ">= 1d", "count": 0},
    }
    for ttl in ttl_values:
        if ttl < 60:
            ttl_buckets["lt_1m"]["count"] += 1
        elif ttl < 3600:
            ttl_buckets["lt_1h"]["count"] += 1
        elif ttl < 86400:
            ttl_buckets["lt_1d"]["count"] += 1
        else:
            ttl_buckets["gte_1d"]["count"] += 1

    prefix_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    length_counts = {
        "short": {"key": "short", "label": "< 32", "count": 0},
        "medium": {"key": "medium", "label": "32-96", "count": 0},
        "long": {"key": "long", "label": "> 96", "count": 0},
    }
    for item in items:
        key_text = str(item["key"])
        prefix_counts[_gsd_prefix_label(key_text)] = prefix_counts.get(_gsd_prefix_label(key_text), 0) + 1
        kind = str(item.get("value_kind") or "unknown")
        type_counts[kind] = type_counts.get(kind, 0) + 1
        key_len = len(key_text)
        if key_len < 32:
            length_counts["short"]["count"] += 1
        elif key_len <= 96:
            length_counts["medium"]["count"] += 1
        else:
            length_counts["long"]["count"] += 1

    largest_items = sorted(items, key=lambda item: int(item.get("size_bytes_estimate") or 0), reverse=True)[:8]
    soonest_expiring = sorted(
        [item for item in items if item.get("ttl_seconds") is not None],
        key=lambda item: float(item.get("ttl_seconds") or 0),
    )[:8]
    sampled_value_bytes = sum(int(item.get("size_bytes_estimate") or 0) for item in items)
    return {
        "namespace": namespace,
        "matched_total": len(items),
        "scanned_total": len(items),
        "persistent_count": len(items) - len(ttl_values),
        "expiring_count": len(ttl_values),
        "ttl_stats": {
            "min_ttl": min(ttl_values) if ttl_values else None,
            "max_ttl": max(ttl_values) if ttl_values else None,
            "avg_ttl": (sum(ttl_values) / len(ttl_values)) if ttl_values else None,
        },
        "ttl_buckets": list(ttl_buckets.values()),
        "key_length_buckets": list(length_counts.values()),
        "top_namespaces": [
            {"key": key, "label": key, "count": count}
            for key, count in sorted(prefix_counts.items(), key=lambda row: (-row[1], row[0]))[:12]
        ],
        "soonest_expiring": soonest_expiring,
        "sample_items": items[:100],
        "sampled_count": len(items),
        "sampled_value_bytes": sampled_value_bytes,
        "sampled_avg_value_bytes": (sampled_value_bytes / len(items)) if items else None,
        "type_counts": [
            {"key": key, "label": key, "count": count}
            for key, count in sorted(type_counts.items(), key=lambda row: (-row[1], row[0]))
        ],
        "largest_items": largest_items,
        "truncated": False,
        "value_metrics_truncated": False,
    }


@router.get("/gsd/item")
async def gsd_item(key: str, namespace: str = "default") -> dict[str, Any]:
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    raw = gsd._local_data.get(namespace, {}).get(key)
    if raw is None or raw.get("deleted"):
        raise HTTPException(status_code=404, detail="Key not found")
    exp = raw.get("exp")
    if exp and exp <= time.time():
        raise HTTPException(status_code=404, detail="Key not found")
    return {
        "namespace": namespace,
        "key": key,
        "value": raw.get("v"),
        "updated_at": raw.get("ts"),
        "expire_at": exp,
    } | _gsd_item_payload(namespace, {"key": key, "value": raw.get("v"), "updated_at": raw.get("ts"), "expire_at": exp})


@router.put("/gsd/item")
async def gsd_put_item(body: GSDSetBody, key: str, namespace: str = "default") -> dict[str, Any]:
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    await gsd.set(key, body.value, expire=body.expire_seconds, namespace=namespace)
    return {"ok": True, "namespace": namespace, "key": key}


@router.delete("/gsd/item")
async def gsd_delete_item(key: str, namespace: str = "default") -> dict[str, Any]:
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    await gsd.delete(key, namespace=namespace)
    return {"ok": True, "namespace": namespace, "key": key}


@router.post("/gsd/delete-by-prefix")
async def gsd_delete_by_prefix(body: GSDDeleteByPrefixBody, namespace: str = "default") -> dict[str, Any]:
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    keys = [str(item["key"]) for item in _gsd_visible_items(namespace) if str(item["key"]).startswith(body.prefix)]
    matched_total = len(keys)
    keys = keys[:body.limit]
    if body.dry_run:
        return {"ok": True, "matched_total": matched_total, "processed": len(keys), "deleted": 0, "keys": keys}
    for key in keys:
        await gsd.delete(key, namespace=namespace)
    return {"ok": True, "matched_total": matched_total, "processed": len(keys), "deleted": len(keys), "keys": keys[:100]}


@router.post("/gsd/sync")
async def gsd_sync_request() -> dict[str, Any]:
    """Return the full GlobalSharedDict state for sync."""
    from core.server.shared_dict import GlobalSharedDict
    gsd = GlobalSharedDict.get_instance()
    return {"node_id": gsd._node_id, "data": dict(gsd._local_data)}


# ── HTML page routes ─────────────────────────────────────────────────────

def register_distributed_html_routes(app):
    @app.get(internal_admin_path("panel/distributed"), response_class=HTMLResponse)
    @app.get(internal_admin_path("panel/distributed.html"), response_class=HTMLResponse)
    async def distributed_panel_html():
        path = get_resources("admin-panel", "panel", "distributed.html") or Path("distributed.html")
        return html_response_from_path(path, not_found_message="panel/distributed.html not found")

    @app.get(internal_admin_path("panel/distributed/data"), response_class=HTMLResponse)
    @app.get(internal_admin_path("panel/distributed_data.html"), response_class=HTMLResponse)
    async def distributed_data_panel_html():
        path = get_resources("admin-panel", "panel", "distributed_data.html") or Path("distributed_data.html")
        return html_response_from_path(path, not_found_message="panel/distributed_data.html not found")

