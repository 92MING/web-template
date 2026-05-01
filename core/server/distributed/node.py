# -*- coding: utf-8 -*-
"""Distributed node data model."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

type NodeRelation = Literal["parent", "child", "friend"]
type NodeHealthStatus = Literal["healthy", "degraded", "unreachable"]


@dataclass
class Node:
    """Represents a remote node in the distributed network."""

    node_id: str
    """Unique node identifier (usually the server instance UUID)."""

    host: str
    """Hostname or IP address."""

    port: int
    """HTTP port of the node's FastAPI server."""

    gsd_port: int = 0
    """GlobalSharedDict TCP port (0 = unknown / not started)."""

    relation: NodeRelation = "friend"
    """Relationship to this node: parent, child, or friend."""

    admin_password_hash: str = ""
    """PBKDF2 hash of the admin password (hex). Used for mutual auth."""

    rtt_ms: float | None = None
    """Round-trip time in milliseconds (None = not yet probed)."""

    last_seen: float = field(default_factory=time.time)
    """Unix timestamp of last successful contact."""

    health_status: NodeHealthStatus = "healthy"
    """Current health assessment."""

    health_score: float = 100.0
    """0-100 health score. Decreases on failures, recovers on success."""

    failed_probes: int = 0
    """Consecutive failed health probes."""

    metadata: dict[str, str] = field(default_factory=dict)
    """Optional key/value metadata (e.g. region, version)."""

    def update_health(self, success: bool, rtt_ms: float | None = None) -> None:
        if success:
            self.failed_probes = 0
            self.health_status = "healthy"
            self.health_score = min(100.0, self.health_score + 10.0)
            self.last_seen = time.time()
            if rtt_ms is not None:
                self.rtt_ms = rtt_ms
        else:
            self.failed_probes += 1
            self.health_score = max(0.0, self.health_score - 20.0)
            if self.failed_probes >= 3:
                self.health_status = "unreachable"
            elif self.failed_probes >= 1:
                self.health_status = "degraded"

    def is_healthy(self) -> bool:
        return self.health_status == "healthy"

    def is_parent(self) -> bool:
        return self.relation == "parent"

    def is_child(self) -> bool:
        return self.relation == "child"

    def is_friend(self) -> bool:
        return self.relation == "friend"

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "gsd_port": self.gsd_port,
            "relation": self.relation,
            "rtt_ms": self.rtt_ms,
            "last_seen": self.last_seen,
            "health_status": self.health_status,
            "health_score": self.health_score,
            "failed_probes": self.failed_probes,
            "metadata": dict(self.metadata),
        }
