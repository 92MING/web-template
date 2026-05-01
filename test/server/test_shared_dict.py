# -*- coding: utf-8 -*-
"""Tests for SharedDict and GlobalSharedDict."""

import pytest
import asyncio
import time

import sys
from pathlib import Path

_server_dir = Path(__file__).resolve().parent.parent.parent / "app" / "core" / "server"
if str(_server_dir.parent.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent.parent))
if str(_server_dir.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent))

from core.server.shared import AppSharedData
from core.server.shared_dict import SharedDict, GlobalSharedDict
from core.server.distributed import NodeRegistry


async def _wait_for_gsd_value(
    gsd: GlobalSharedDict,
    key: str,
    expected: object,
    namespace: str = "default",
    timeout: float = 3.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await gsd.get(key, namespace=namespace) == expected:
            return
        await asyncio.sleep(0.05)
    actual = await gsd.get(key, namespace=namespace)
    raise AssertionError(f"Expected {key!r} to become {expected!r}, got {actual!r}")


@pytest.fixture
def shared_data():
    sd = AppSharedData("test-instance")
    return sd


class TestSharedDict:
    def test_get_set(self, shared_data):
        d = SharedDict(shared_data, namespace="test-ns")
        d.set("key1", "value1")
        assert d.get("key1") == "value1"

    def test_delete(self, shared_data):
        d = SharedDict(shared_data, namespace="test-ns2")
        d.set("key2", "value2")
        assert d.get("key2") == "value2"
        d.delete("key2")
        assert d.get("key2") is None

    def test_has(self, shared_data):
        d = SharedDict(shared_data, namespace="test-ns3")
        d.set("key3", "value3")
        assert d.has("key3") is True
        assert d.has("nonexistent") is False

    def test_expire(self, shared_data):
        d = SharedDict(shared_data, namespace="test-ns4")
        d.set("key4", "value4", expire=1)
        assert d.get("key4") == "value4"
        import time
        time.sleep(1.1)
        d.cleanup_expired()
        assert d.get("key4") is None

    def test_keys_and_all(self, shared_data):
        d = SharedDict(shared_data, namespace="test-ns5")
        d.set("a", 1)
        d.set("b", 2)
        assert sorted(d.keys()) == ["a", "b"]
        assert d.all() == {"a": 1, "b": 2}

    def test_clear(self, shared_data):
        d = SharedDict(shared_data, namespace="test-ns6")
        d.set("x", 1)
        d.clear()
        assert d.get("x") is None


class TestGlobalSharedDict:
    def test_singleton(self):
        g1 = GlobalSharedDict.get_instance()
        g2 = GlobalSharedDict.get_instance()
        assert g1 is g2

    def test_set_get(self):
        import asyncio
        g = GlobalSharedDict(AppSharedData("gsd-test"), listen_port=0)
        asyncio.run(g.set("k1", "v1"))
        assert asyncio.run(g.get("k1")) == "v1"
        asyncio.run(g.stop())

    def test_delete(self):
        import asyncio
        g = GlobalSharedDict(AppSharedData("gsd-test2"), listen_port=0)
        asyncio.run(g.set("k2", "v2"))
        old = asyncio.run(g.delete("k2"))
        assert old == "v2"
        assert asyncio.run(g.get("k2")) is None
        asyncio.run(g.stop())

    def test_all(self):
        import asyncio
        g = GlobalSharedDict(AppSharedData("gsd-test3"), listen_port=0)
        asyncio.run(g.set("a", 1))
        asyncio.run(g.set("b", 2))
        assert g.all() == {"a": 1, "b": 2}
        asyncio.run(g.stop())

    def test_peer_registration(self):
        g = GlobalSharedDict(AppSharedData("gsd-test4"), listen_port=0)
        p = g.register_peer("node-1", "127.0.0.1", 18000, relation="child")
        assert p.node_id == "node-1"
        assert p.relation == "child"
        peers = g.get_peers()
        assert len(peers) == 1

    def test_nearest_peers_sorting(self):
        g = GlobalSharedDict(AppSharedData("gsd-test5"), listen_port=0)
        g.register_peer("near", "127.0.0.1", 18001, relation="friend")
        g.register_peer("far", "127.0.0.1", 18002, relation="friend")
        g._peers["near"].rtt_ms = 10.0
        g._peers["far"].rtt_ms = 100.0
        nearest = g.get_nearest_peers(n=2)
        assert nearest[0].node_id == "near"
        assert nearest[1].node_id == "far"

    def test_global_shared_dict_gossips_through_two_relay_nodes(self):
        async def scenario() -> None:
            master = GlobalSharedDict(
                AppSharedData("gsd-master-node"),
                listen_host="127.0.0.1",
                listen_port=0,
                broadcast_fanout=1,
                node_id="master",
            )
            relay_a = GlobalSharedDict(
                AppSharedData("gsd-relay-a-node"),
                listen_host="127.0.0.1",
                listen_port=0,
                broadcast_fanout=1,
                node_id="relay-a",
            )
            relay_b = GlobalSharedDict(
                AppSharedData("gsd-relay-b-node"),
                listen_host="127.0.0.1",
                listen_port=0,
                broadcast_fanout=1,
                node_id="relay-b",
            )
            leaf = GlobalSharedDict(
                AppSharedData("gsd-leaf-node"),
                listen_host="127.0.0.1",
                listen_port=0,
                broadcast_fanout=1,
                node_id="leaf",
            )
            try:
                _, master_port = await master.start()
                _, relay_a_port = await relay_a.start()
                _, relay_b_port = await relay_b.start()
                _, leaf_port = await leaf.start()

                master.register_peer("relay-a", "127.0.0.1", relay_a_port, relation="friend")
                relay_a.register_peer("master", "127.0.0.1", master_port, relation="friend")
                relay_a.register_peer("relay-b", "127.0.0.1", relay_b_port, relation="friend")
                relay_b.register_peer("relay-a", "127.0.0.1", relay_a_port, relation="friend")
                relay_b.register_peer("leaf", "127.0.0.1", leaf_port, relation="friend")
                leaf.register_peer("relay-b", "127.0.0.1", relay_b_port, relation="friend")

                await master.set("from-master", "reached-leaf")
                await _wait_for_gsd_value(leaf, "from-master", "reached-leaf")

                await leaf.set("from-leaf", "reached-master")
                await _wait_for_gsd_value(master, "from-leaf", "reached-master")
            finally:
                await leaf.stop()
                await relay_b.stop()
                await relay_a.stop()
                await master.stop()

        asyncio.run(scenario())


class TestNodeRegistry:
    def test_registry_state_is_shared_between_instances(self):
        async def scenario() -> None:
            shared_data = AppSharedData("node-registry-shared-test")
            namespace = "node-registry-shared-test"
            worker_a = NodeRegistry(shared_data=shared_data, namespace=namespace)
            worker_b = NodeRegistry(shared_data=shared_data, namespace=namespace)

            await worker_a.register("node-a", "127.0.0.1", 18000, relation="child", gsd_port=28000)
            node_from_b = await worker_b.get("node-a")
            assert node_from_b is not None
            assert node_from_b.host == "127.0.0.1"
            assert node_from_b.port == 18000
            assert node_from_b.gsd_port == 28000

            await worker_b.update_health("node-a", success=False)
            node_from_a = await worker_a.get("node-a")
            assert node_from_a is not None
            assert node_from_a.failed_probes == 1
            assert node_from_a.health_status == "degraded"

            removed = await worker_b.unregister("node-a")
            assert removed is not None
            assert await worker_a.get("node-a") is None

        asyncio.run(scenario())

    def test_registry_health_uses_global_shared_dict_heartbeat(self):
        async def scenario() -> None:
            shared_data = AppSharedData("node-registry-heartbeat-test")
            namespace = "node-registry-heartbeat-test"
            registry = NodeRegistry(shared_data=shared_data, namespace=namespace)
            gsd = GlobalSharedDict(shared_data, listen_host="127.0.0.1", listen_port=0, node_id="master")
            original_instance = GlobalSharedDict._instance
            GlobalSharedDict._instance = gsd
            try:
                await registry.register("node-b", "127.0.0.1", 1, relation="friend")
                await registry.update_health("node-b", success=False)
                await gsd.set(
                    "node-b",
                    {"node_id": "node-b", "ts": time.time()},
                    namespace="__node_heartbeat__",
                )

                node = await registry.get("node-b")
                assert node is not None
                assert node.health_status == "degraded"
                healthy_nodes = await registry.healthy()
                assert [node.node_id for node in healthy_nodes] == ["node-b"]

                await gsd.set(
                    "node-b",
                    {"node_id": "node-b", "ts": time.time() - 120.0},
                    namespace="__node_heartbeat__",
                )
                nodes = await registry.all()
                assert nodes[0].health_status == "unreachable"
            finally:
                GlobalSharedDict._instance = original_instance
                await gsd.stop()

        asyncio.run(scenario())
