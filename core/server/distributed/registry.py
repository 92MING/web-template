# -*- coding: utf-8 -*-
"""Node registry — manages parent/child/friend relationships."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, TypedDict, cast

from .node import Node, NodeRelation, NodeHealthStatus

if TYPE_CHECKING:
    from core.server.shared import AppSharedData

_logger = logging.getLogger(__name__)

_NODE_REGISTRY_NAMESPACE = "__distributed_nodes__"
_NODE_HEARTBEAT_NAMESPACE = "__node_heartbeat__"
_NODE_HEARTBEAT_TIMEOUT = 30.0
_NODE_PARENT_METADATA_KEYS = ("parent_id", "parent_node_id")


class _NodeRecord(TypedDict):
    node_id: str
    host: str
    port: int
    gsd_port: int
    relation: NodeRelation
    admin_password_hash: str
    rtt_ms: float | None
    last_seen: float
    health_status: NodeHealthStatus
    health_score: float
    failed_probes: int
    metadata: dict[str, str]


class NodeRegistry:
    """Central registry for all known nodes in the distributed network.

    Thread-safe via internal asyncio lock.
    """

    _instance: NodeRegistry | None = None

    def __init__(
        self,
        shared_data: AppSharedData | None = None,
        namespace: str = _NODE_REGISTRY_NAMESPACE,
    ) -> None:
        self._shared_data = shared_data
        self._namespace = namespace
        self._lock = asyncio.Lock()
        self._health_task: asyncio.Task[None] | None = None
        self._running = False
        self._probe_interval = 15.0

    @classmethod
    def get_instance(cls) -> NodeRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _shared(self) -> AppSharedData:
        if self._shared_data is None:
            from core.server.shared import AppSharedData
            self._shared_data = AppSharedData.Get()
        return self._shared_data

    def _to_record(self, node: Node) -> _NodeRecord:
        return {
            "node_id": node.node_id,
            "host": node.host,
            "port": node.port,
            "gsd_port": node.gsd_port,
            "relation": node.relation,
            "admin_password_hash": node.admin_password_hash,
            "rtt_ms": node.rtt_ms,
            "last_seen": node.last_seen,
            "health_status": node.health_status,
            "health_score": node.health_score,
            "failed_probes": node.failed_probes,
            "metadata": dict(node.metadata),
        }

    def _from_record(self, record: object) -> Node | None:
        if not isinstance(record, Mapping):
            return None
        data = cast(Mapping[str, object], record)
        relation = data.get("relation", "friend")
        if relation not in ("parent", "child", "friend"):
            relation = "friend"
        health_status = data.get("health_status", "healthy")
        if health_status not in ("healthy", "degraded", "unreachable"):
            health_status = "healthy"
        metadata_raw = data.get("metadata", {})
        metadata = {
            str(key): str(value)
            for key, value in (metadata_raw.items() if isinstance(metadata_raw, Mapping) else [])
        }
        return Node(
            node_id=str(data["node_id"]),
            host=str(data["host"]),
            port=int(data["port"]),
            gsd_port=int(data.get("gsd_port", 0)),
            relation=cast(NodeRelation, relation),
            admin_password_hash=str(data.get("admin_password_hash", "")),
            rtt_ms=cast(float | None, data.get("rtt_ms")),
            last_seen=float(data.get("last_seen", time.time())),
            health_status=cast(NodeHealthStatus, health_status),
            health_score=float(data.get("health_score", 100.0)),
            failed_probes=int(data.get("failed_probes", 0)),
            metadata=metadata,
        )

    def _save(self, node: Node) -> None:
        self._shared().set_shared_dict_value(self._namespace, node.node_id, self._to_record(node))

    async def _apply_heartbeat_health(self, node: Node) -> Node:
        try:
            from core.server.shared_dict import GlobalSharedDict
            heartbeat = await GlobalSharedDict.get_instance().get(
                node.node_id,
                namespace=_NODE_HEARTBEAT_NAMESPACE,
            )
        except Exception:
            return node

        if not isinstance(heartbeat, Mapping):
            return node
        ts = heartbeat.get("ts")
        if not isinstance(ts, (int, float)):
            return node

        if time.time() - float(ts) <= _NODE_HEARTBEAT_TIMEOUT:
            node.update_health(True)
            node.last_seen = float(ts)
        else:
            node.failed_probes = max(node.failed_probes, 3)
            node.health_status = "unreachable"
            node.health_score = 0.0
        self._save(node)
        return node

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._health_task = asyncio.create_task(self._health_loop(), name="node-health")
        _logger.info("NodeRegistry started.")

    async def stop(self) -> None:
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None
        _logger.info("NodeRegistry stopped.")

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def register(
        self,
        node_id: str,
        host: str,
        port: int,
        relation: NodeRelation = "friend",
        admin_password_hash: str = "",
        gsd_port: int = 0,
        metadata: dict[str, str] | None = None,
    ) -> Node:
        async with self._lock:
            node = self._from_record(self._shared().get_shared_dict_value(self._namespace, node_id))
            if node is None:
                node = Node(
                    node_id=node_id,
                    host=host,
                    port=port,
                    relation=relation,
                    admin_password_hash=admin_password_hash,
                    gsd_port=gsd_port,
                    metadata=metadata or {},
                )
                _logger.info("Registered node %s (%s) at %s:%s", node_id, relation, host, port)
            else:
                node.host = host
                node.port = port
                node.gsd_port = gsd_port
                node.relation = relation
                if admin_password_hash:
                    node.admin_password_hash = admin_password_hash
                if metadata:
                    node.metadata.update(metadata)
                node.last_seen = time.time()
            self._save(node)
            return node

    async def unregister(self, node_id: str) -> Node | None:
        async with self._lock:
            node = self._from_record(self._shared().delete_shared_dict_value(self._namespace, node_id))
            return node

    async def get(self, node_id: str) -> Node | None:
        async with self._lock:
            return self._from_record(self._shared().get_shared_dict_value(self._namespace, node_id))

    async def all(self) -> list[Node]:
        async with self._lock:
            nodes: list[Node] = []
            for record in self._shared().get_shared_dict(self._namespace).values():
                node = self._from_record(record)
                if node is not None:
                    nodes.append(await self._apply_heartbeat_health(node))
            return nodes

    async def by_relation(self, relation: NodeRelation) -> list[Node]:
        return [node for node in await self.all() if node.relation == relation]

    async def parents(self) -> list[Node]:
        return await self.by_relation("parent")

    async def children(self) -> list[Node]:
        return await self.by_relation("child")

    async def friends(self) -> list[Node]:
        return await self.by_relation("friend")

    async def healthy(self) -> list[Node]:
        return [node for node in await self.all() if node.is_healthy()]

    async def update_health(self, node_id: str, success: bool, rtt_ms: float | None = None) -> None:
        async with self._lock:
            node = self._from_record(self._shared().get_shared_dict_value(self._namespace, node_id))
            if node:
                node.update_health(success, rtt_ms)
                self._save(node)

    # ── management scope lookup ────────────────────────────────────────────

    def _parent_id_for_management(self, node: Node, root_id: str) -> str | None:
        if node.relation != "child":
            return None
        for key in _NODE_PARENT_METADATA_KEYS:
            parent_id = node.metadata.get(key, "").strip()
            if parent_id:
                return parent_id
        return root_id

    async def management_route(self, root_id: str, target_id: str) -> list[Node] | None:
        """Return child-edge route from *root_id* to *target_id*.

        The returned list excludes *root_id* and includes *target_id*.
        Only nodes with relation="child" participate in the management graph;
        friend and parent edges deliberately do not grant management authority.
        """
        if root_id == target_id:
            return []

        nodes = await self.all()
        by_parent: dict[str, list[Node]] = {}
        for node in nodes:
            parent_id = self._parent_id_for_management(node, root_id)
            if parent_id is None:
                continue
            by_parent.setdefault(parent_id, []).append(node)

        queue: list[tuple[str, list[Node]]] = [(root_id, [])]
        visited: set[str] = set()
        while queue:
            current_id, route = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            for child in by_parent.get(current_id, []):
                next_route = [*route, child]
                if child.node_id == target_id:
                    return next_route
                queue.append((child.node_id, next_route))
        return None

    async def can_manage(self, root_id: str, target_id: str) -> bool:
        route = await self.management_route(root_id, target_id)
        return route is not None and len(route) > 0

    async def next_management_hop(self, root_id: str, target_id: str) -> Node | None:
        route = await self.management_route(root_id, target_id)
        if not route:
            return None
        return route[0]

    async def manageable_nodes(self, root_id: str) -> list[Node]:
        descendants = await self.get_all_descendants(root_id)
        return descendants

    # ── transitive parent lookup ───────────────────────────────────────────

    async def is_parent_of(self, ancestor_id: str, descendant_id: str) -> bool:
        """Check if *ancestor_id* is a transitive parent of *descendant_id*."""
        return await self.can_manage(ancestor_id, descendant_id)

    async def get_all_descendants(self, parent_id: str) -> list[Node]:
        """Return all transitive children of *parent_id*."""
        result: list[Node] = []
        nodes = await self.all()
        by_parent: dict[str, list[Node]] = {}
        for node in nodes:
            node_parent_id = self._parent_id_for_management(node, parent_id)
            if node_parent_id is None:
                continue
            by_parent.setdefault(node_parent_id, []).append(node)

        visited: set[str] = set()
        queue: list[str] = [parent_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for child in by_parent.get(current, []):
                if child.node_id not in visited:
                    result.append(child)
                    queue.append(child.node_id)
        return result

    # ── health loop ────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._probe_interval)
                nodes = await self.all()
                for node in nodes:
                    try:
                        await self._probe_node(node)
                    except Exception as exc:
                        _logger.debug("Health probe to %s failed: %s", node.node_id, exc)
                        await self.update_health(node.node_id, success=False)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _logger.debug("NodeRegistry health loop error: %s", exc)

    async def _probe_node(self, node: Node) -> None:
        """HTTP GET /admin/api/distributed/health against the remote node."""
        import aiohttp
        from core.server.data_types.config import Config

        path = Config.GetConfig().server_config.get_internal_admin_path("api/distributed/health")
        url = f"http://{node.host}:{node.port}{path}"
        timeout = aiohttp.ClientTimeout(total=5.0)
        t0 = time.time()
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                rtt = (time.time() - t0) * 1000
                if response.status == 200:
                    await self.update_health(node.node_id, success=True, rtt_ms=rtt)
                else:
                    await self.update_health(node.node_id, success=False)
