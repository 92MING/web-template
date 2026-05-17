# -*- coding: utf-8 -*-
"""SharedDict and GlobalSharedDict implementations.

* ``SharedDict`` — process-local shared dictionary backed by ``AppSharedData``.
* ``GlobalSharedDict`` — distributed replicated dictionary with gossip broadcast.
"""

from __future__ import annotations

import asyncio
import json
import time
import logging
import socket
from typing import Any, Callable

from .shared import AppSharedData

_logger = logging.getLogger(__name__)


class SharedDict:
    """A namespaced dictionary stored inside ``AppSharedData``.

    All operations are transparently forwarded to the cross-process shared
    object so that every worker sees the same data.
    """

    def __init__(self, shared_data: AppSharedData, namespace: str = "default") -> None:
        self._shared = shared_data
        self._namespace = namespace

    def get(self, key: str, default: Any = None) -> Any:
        meta_key = f"__exp__:{key}"
        d = self._shared.get_shared_dict(self._namespace)
        exp = d.get(meta_key)
        if exp is not None and exp <= time.time():
            d.pop(key, None)
            d.pop(meta_key, None)
            return default
        return d.get(key, default)

    def set(self, key: str, value: Any, expire: int | None = None) -> Any:
        result = self._shared.set_shared_dict_value(self._namespace, key, value)
        if expire is not None and expire > 0:
            # Store expiration metadata alongside the value
            meta_key = f"__exp__:{key}"
            self._shared.set_shared_dict_value(
                self._namespace, meta_key, time.time() + expire
            )
        return result

    def delete(self, key: str) -> Any | None:
        self._shared.delete_shared_dict_value(self._namespace, f"__exp__:{key}")
        return self._shared.delete_shared_dict_value(self._namespace, key)

    def has(self, key: str) -> bool:
        return self._shared.has_shared_dict_key(self._namespace, key)

    def clear(self) -> None:
        self._shared.clear_shared_dict(self._namespace)

    def keys(self) -> list[str]:
        d = self._shared.get_shared_dict(self._namespace)
        return [k for k in d if not k.startswith("__exp__:")]

    def all(self) -> dict[str, Any]:
        d = dict(self._shared.get_shared_dict(self._namespace))
        return {k: v for k, v in d.items() if not k.startswith("__exp__:")}

    def cleanup_expired(self) -> int:
        d = self._shared.get_shared_dict(self._namespace)
        now = time.time()
        expired: list[str] = []
        for key in list(d):
            if key.startswith("__exp__:"):
                target = key[8:]
                if d[key] <= now:
                    expired.append(target)
                    expired.append(key)
        for key in expired:
            d.pop(key, None)
        return len(expired) // 2


# ═══════════════════════════════════════════════════════════════════════════════
# GlobalSharedDict — distributed replicated dict with gossip propagation
# ═══════════════════════════════════════════════════════════════════════════════

_GSD_DEFAULT_PORT = 0  # auto-allocate
_GSD_DEFAULT_BROADCAST_FANOUT = 3
_GSD_NODE_HEARTBEAT_NAMESPACE = "__node_heartbeat__"
_GSD_PEER_NAMESPACE = "__gsd_peers__"
_GSD_HEARTBEAT_INTERVAL = 10.0
_GSD_HEARTBEAT_EXPIRE_SECONDS = 60


class _GSDPeer:
    """Represents a remote node in the distributed network."""

    def __init__(
        self,
        node_id: str,
        host: str,
        port: int,
        relation: str = "ff",
        password_hash: str | None = None,
    ) -> None:
        self.node_id = node_id
        self.host = host
        self.port = port
        self.relation = relation  # "ff", "pc", "pp"
        self.password_hash = password_hash
        self.last_seen = time.time()
        self.rtt_ms: float | None = None
        self.healthy = True

    def __repr__(self) -> str:
        return f"<_GSDPeer {self.node_id} {self.host}:{self.port} ({self.relation})>"

    def to_record(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "relation": self.relation,
            "password_hash": self.password_hash,
            "last_seen": self.last_seen,
            "rtt_ms": self.rtt_ms,
            "healthy": self.healthy,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> _GSDPeer:
        peer = cls(
            node_id=str(record["node_id"]),
            host=str(record["host"]),
            port=int(record["port"]),
            relation=str(record.get("relation") or "ff"),
            password_hash=record.get("password_hash"),
        )
        peer.last_seen = float(record.get("last_seen", time.time()))
        peer.rtt_ms = record.get("rtt_ms")
        peer.healthy = bool(record.get("healthy", True))
        return peer


class GlobalSharedDict:
    """Distributed replicated dictionary.

    Design:
    * Each node keeps a local copy.
    * ``set`` / ``delete`` broadcasts to the N nearest peers.
    * Receiving peers propagate to N peers that have not yet received the
      update (gossip / epidemic broadcast).
    * Timestamps resolve conflicts — last write wins.
    * A dedicated asyncio TCP server handles inbound sync traffic.
    * On first connection, a node syncs its full state from the nearest peer.
    """

    _instance: GlobalSharedDict | None = None

    def __init__(
        self,
        shared_data: AppSharedData,
        listen_host: str = "0.0.0.0",
        listen_port: int = 0,
        broadcast_fanout: int = _GSD_DEFAULT_BROADCAST_FANOUT,
        node_id: str | None = None,
    ) -> None:
        self._shared = shared_data
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._fanout = max(1, broadcast_fanout)
        self._node_id = node_id or shared_data.instance_uuid
        self._peers: dict[str, _GSDPeer] = {}
        self._local_data: dict[str, dict[str, Any]] = {}  # {namespace: {key: {v, ts, exp}}}
        self._server: asyncio.Server | None = None
        self._server_task: asyncio.Task[Any] | None = None
        self._health_task: asyncio.Task[Any] | None = None
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()
        self._running = False

    @classmethod
    def get_instance(cls) -> GlobalSharedDict:
        if cls._instance is None:
            cls._instance = cls(AppSharedData.Get())
        return cls._instance

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> tuple[str, int]:
        """Start the internal asyncio TCP server. Returns (host, port)."""
        if self._running:
            return self._listen_host, self._listen_port
        self._server = await asyncio.start_server(
            self._handle_client, self._listen_host, self._listen_port
        )
        self._running = True
        addr = self._server.sockets[0].getsockname()
        self._listen_host = addr[0]
        self._listen_port = addr[1]
        _logger.info("GlobalSharedDict server started on %s:%s", self._listen_host, self._listen_port)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="gsd-heartbeat")
        self._health_task = asyncio.create_task(self._health_loop(), name="gsd-health")
        return self._listen_host, self._listen_port

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    # ── peer management ────────────────────────────────────────────────────

    def register_peer(
        self,
        node_id: str,
        host: str,
        port: int,
        relation: str = "ff",
        password_hash: str | None = None,
    ) -> _GSDPeer:
        peer = _GSDPeer(node_id, host, port, relation, password_hash)
        self._peers[node_id] = peer
        self._shared.set_shared_dict_value(_GSD_PEER_NAMESPACE, node_id, peer.to_record())
        _logger.info("Registered GSD peer %s (%s) at %s:%s", node_id, relation, host, port)
        return peer

    def unregister_peer(self, node_id: str) -> None:
        self._peers.pop(node_id, None)
        self._shared.delete_shared_dict_value(_GSD_PEER_NAMESPACE, node_id)

    def _refresh_peers_from_shared(self) -> None:
        records = self._shared.get_shared_dict(_GSD_PEER_NAMESPACE)
        record_ids = {str(node_id) for node_id in records}
        for node_id in list(self._peers):
            if node_id not in record_ids:
                self._peers.pop(node_id, None)
        for node_id, record in records.items():
            if node_id == self._node_id or not isinstance(record, dict):
                continue
            try:
                peer = _GSDPeer.from_record(record)
            except Exception:
                continue
            existing = self._peers.get(peer.node_id)
            if existing is None:
                self._peers[peer.node_id] = peer
                continue
            existing.host = peer.host
            existing.port = peer.port
            existing.relation = peer.relation
            existing.password_hash = peer.password_hash

    def get_peers(self, relation: str | None = None) -> list[_GSDPeer]:
        self._refresh_peers_from_shared()
        if relation is None:
            return list(self._peers.values())
        return [p for p in self._peers.values() if p.relation == relation]

    def get_nearest_peers(self, n: int | None = None) -> list[_GSDPeer]:
        """Return peers sorted by RTT (lowest first). Unknown RTT is treated as inf."""
        self._refresh_peers_from_shared()
        n = n or self._fanout
        sorted_peers = sorted(
            self._peers.values(),
            key=lambda p: p.rtt_ms if p.rtt_ms is not None else float("inf"),
        )
        return sorted_peers[:n]

    # ── data operations (local + broadcast) ────────────────────────────────

    async def get(self, key: str, namespace: str = "default") -> Any | None:
        ns = self._local_data.get(namespace, {})
        entry = ns.get(key)
        if entry is None:
            return None
        if entry.get("deleted"):
            return None
        if entry.get("exp") and entry["exp"] <= time.time():
            ns.pop(key, None)
            return None
        return entry.get("v")

    async def set(
        self,
        key: str,
        value: Any,
        expire: int | None = None,
        namespace: str = "default",
    ) -> Any:
        ts = time.time()
        entry = {"v": value, "ts": ts, "exp": ts + expire if expire else None}
        async with self._lock:
            self._local_data.setdefault(namespace, {})[key] = entry
        await self._broadcast("set", {"ns": namespace, "key": key, "entry": entry})
        return value

    async def delete(self, key: str, namespace: str = "default") -> Any | None:
        ts = time.time()
        async with self._lock:
            local_ns = self._local_data.setdefault(namespace, {})
            old = local_ns.get(key)
            local_ns[key] = {"v": None, "ts": ts, "exp": None, "deleted": True}
        await self._broadcast("delete", {
            "ns": namespace,
            "key": key,
            "entry": {"v": None, "ts": ts, "exp": None, "deleted": True},
        })
        return old.get("v") if old and not old.get("deleted") else None

    def all(self, namespace: str = "default") -> dict[str, Any]:
        ns = self._local_data.get(namespace, {})
        out: dict[str, Any] = {}
        now = time.time()
        for k, entry in ns.items():
            if entry.get("deleted"):
                continue
            if entry.get("exp") and entry["exp"] <= now:
                continue
            out[k] = entry["v"]
        return out

    # ── network protocol ───────────────────────────────────────────────────

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle inbound GSD connections from other nodes."""
        addr = writer.get_extra_info("peername")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                payload = json.loads(line.decode("utf-8"))
                await self._process_inbound(payload, writer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.debug("GSD client handler error from %s: %s", addr, exc)
        finally:
            writer.close()
            await writer.wait_closed()

    async def _process_inbound(
        self, payload: dict[str, Any], writer: asyncio.StreamWriter
    ) -> None:
        cmd = payload.get("cmd")
        if cmd == "ping":
            writer.write(json.dumps({"cmd": "pong", "node_id": self._node_id}).encode("utf-8") + b"\n")
            await writer.drain()
        elif cmd == "sync_request":
            # Another node wants our full state
            data = dict(self._local_data)
            writer.write(
                json.dumps({"cmd": "sync_response", "node_id": self._node_id, "data": data}).encode("utf-8")
                + b"\n"
            )
            await writer.drain()
        elif cmd == "sync_response":
            # Merge remote state (last-write-wins by timestamp)
            remote_data: dict[str, dict[str, Any]] = payload.get("data", {})
            async with self._lock:
                for ns, keys in remote_data.items():
                    local_ns = self._local_data.setdefault(ns, {})
                    for k, entry in keys.items():
                        local_entry = local_ns.get(k)
                        if local_entry is None or entry.get("ts", 0) > local_entry.get("ts", 0):
                            local_ns[k] = entry
        elif cmd == "set":
            ns = payload.get("ns", "default")
            key = payload["key"]
            entry = payload["entry"]
            seen = payload.get("seen", [])
            accepted = False
            async with self._lock:
                local_ns = self._local_data.setdefault(ns, {})
                local_entry = local_ns.get(key)
                if local_entry is None or entry.get("ts", 0) > local_entry.get("ts", 0):
                    local_ns[key] = entry
                    accepted = True
            # Gossip forward
            if accepted:
                await self._broadcast("set", {"ns": ns, "key": key, "entry": entry}, exclude=seen)
        elif cmd == "delete":
            ns = payload.get("ns", "default")
            key = payload["key"]
            entry = payload.get("entry")
            if not isinstance(entry, dict):
                entry = {"v": None, "ts": time.time(), "exp": None, "deleted": True}
            entry["deleted"] = True
            seen = payload.get("seen", [])
            accepted = False
            async with self._lock:
                local_ns = self._local_data.setdefault(ns, {})
                local_entry = local_ns.get(key)
                if local_entry is None or entry.get("ts", 0) > local_entry.get("ts", 0):
                    local_ns[key] = entry
                    accepted = True
            if accepted:
                await self._broadcast("delete", {"ns": ns, "key": key, "entry": entry}, exclude=seen)

    async def _broadcast(
        self,
        cmd: str,
        payload: dict[str, Any],
        exclude: list[str] | None = None,
    ) -> None:
        """Send to N nearest peers that are not in ``exclude``."""
        if not self._running:
            return
        exclude_set = set(exclude or [])
        exclude_set.add(self._node_id)
        targets = [p for p in self.get_nearest_peers() if p.node_id not in exclude_set]
        if not targets:
            targets = [p for p in self._peers.values() if p.node_id not in exclude_set]
        targets = targets[: self._fanout]
        seen = list(exclude_set)
        for peer in targets:
            asyncio.create_task(self._send_to_peer(peer, cmd, payload, seen))

    async def _send_to_peer(
        self,
        peer: _GSDPeer,
        cmd: str,
        payload: dict[str, Any],
        seen: list[str],
    ) -> None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(peer.host, peer.port), timeout=3.0
            )
            msg = {"cmd": cmd, **payload, "seen": list(dict.fromkeys([*seen, self._node_id]))}
            writer.write(json.dumps(msg).encode("utf-8") + b"\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            peer.last_seen = time.time()
            peer.healthy = True
        except Exception as exc:
            peer.healthy = False
            _logger.debug("GSD send to %s failed: %s", peer.node_id, exc)

    async def _probe_rtt(self, peer: _GSDPeer) -> float | None:
        """Probe RTT to a peer via TCP ping. Returns RTT in ms or None."""
        try:
            t0 = time.time()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(peer.host, peer.port), timeout=3.0
            )
            writer.write(json.dumps({"cmd": "ping"}).encode("utf-8") + b"\n")
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=3.0)
            rtt = (time.time() - t0) * 1000
            writer.close()
            await writer.wait_closed()
            if line:
                peer.last_seen = time.time()
                peer.healthy = True
                return rtt
        except Exception:
            peer.healthy = False
        return None

    async def _health_loop(self) -> None:
        """Periodically probe peers and update RTT / health status."""
        while self._running:
            try:
                await asyncio.sleep(10)
                for peer in list(self._peers.values()):
                    rtt = await self._probe_rtt(peer)
                    if rtt is not None:
                        peer.rtt_ms = rtt
                        _logger.debug("GSD peer %s RTT %.1f ms", peer.node_id, rtt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _logger.debug("GSD health loop error: %s", exc)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await self._publish_heartbeat()
                await asyncio.sleep(_GSD_HEARTBEAT_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _logger.debug("GSD heartbeat loop error: %s", exc)

    async def _publish_heartbeat(self) -> None:
        await self.set(
            self._node_id,
            {
                "node_id": self._node_id,
                "ts": time.time(),
                "host": self._listen_host,
                "gsd_port": self._listen_port,
            },
            expire=_GSD_HEARTBEAT_EXPIRE_SECONDS,
            namespace=_GSD_NODE_HEARTBEAT_NAMESPACE,
        )

    async def sync_from_nearest(self) -> bool:
        """Request full-state sync from the nearest healthy peer."""
        for peer in self.get_nearest_peers():
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(peer.host, peer.port), timeout=5.0
                )
                writer.write(
                    json.dumps({"cmd": "sync_request", "node_id": self._node_id}).encode("utf-8")
                    + b"\n"
                )
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                writer.close()
                await writer.wait_closed()
                if line:
                    payload = json.loads(line.decode("utf-8"))
                    await self._process_inbound(payload, writer)
                    _logger.info("GSD synced from %s", peer.node_id)
                    return True
            except Exception as exc:
                _logger.debug("GSD sync from %s failed: %s", peer.node_id, exc)
        return False
