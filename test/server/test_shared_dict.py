# -*- coding: utf-8 -*-
"""Tests for SharedDict and GlobalSharedDict."""

import pytest
import asyncio
import random
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
        p = g.register_peer("node-1", "127.0.0.1", 18000, relation="pc")
        assert p.node_id == "node-1"
        assert p.relation == "pc"
        peers = g.get_peers()
        assert len(peers) == 1

    def test_nearest_peers_sorting(self):
        g = GlobalSharedDict(AppSharedData("gsd-test5"), listen_port=0)
        g.register_peer("near", "127.0.0.1", 18001, relation="ff")
        g.register_peer("far", "127.0.0.1", 18002, relation="ff")
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

                master.register_peer("relay-a", "127.0.0.1", relay_a_port, relation="ff")
                relay_a.register_peer("master", "127.0.0.1", master_port, relation="ff")
                relay_a.register_peer("relay-b", "127.0.0.1", relay_b_port, relation="ff")
                relay_b.register_peer("relay-a", "127.0.0.1", relay_a_port, relation="ff")
                relay_b.register_peer("leaf", "127.0.0.1", leaf_port, relation="ff")
                leaf.register_peer("relay-b", "127.0.0.1", relay_b_port, relation="ff")

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

    def test_delete_tombstone_does_not_overwrite_newer_set(self):
        async def scenario() -> None:
            g = GlobalSharedDict(AppSharedData("gsd-tombstone-test"), listen_port=0)
            try:
                await g.set("x", 1)
                newer = g._local_data["default"]["x"]["ts"]
                await g._process_inbound(
                    {
                        "cmd": "delete",
                        "ns": "default",
                        "key": "x",
                        "entry": {"v": None, "ts": newer - 1.0, "exp": None, "deleted": True},
                    },
                    None,  # type: ignore[arg-type]
                )
                assert await g.get("x") == 1
            finally:
                await g.stop()

        asyncio.run(scenario())

    def test_delayed_delete_from_one_node_does_not_overwrite_newer_set_from_another(self):
        async def scenario() -> None:
            node_b = GlobalSharedDict(AppSharedData("gsd-delay-node-b"), listen_port=0, node_id="node-b")
            try:
                delete_from_a = {
                    "cmd": "delete",
                    "ns": "default",
                    "key": "x",
                    "entry": {"v": None, "ts": 1000.000, "exp": None, "deleted": True},
                    "seen": ["node-a"],
                }
                set_from_c = {
                    "cmd": "set",
                    "ns": "default",
                    "key": "x",
                    "entry": {"v": 1, "ts": 1000.001, "exp": None, "deleted": False},
                    "seen": ["node-c"],
                }

                await node_b._process_inbound(set_from_c, None)  # type: ignore[arg-type]
                await node_b._process_inbound(delete_from_a, None)  # type: ignore[arg-type]

                assert await node_b.get("x") == 1
                assert node_b._local_data["default"]["x"]["ts"] == 1000.001
            finally:
                await node_b.stop()

        asyncio.run(scenario())

    def test_three_node_delayed_delete_does_not_overwrite_newer_forwarded_set(self):
        async def scenario() -> None:
            node_a = GlobalSharedDict(AppSharedData("gsd-delay-node-a-live"), listen_port=0, node_id="node-a")
            node_b = GlobalSharedDict(AppSharedData("gsd-delay-node-b-live"), listen_port=0, node_id="node-b", broadcast_fanout=2)
            node_c = GlobalSharedDict(AppSharedData("gsd-delay-node-c-live"), listen_port=0, node_id="node-c")
            try:
                _, port_a = await node_a.start()
                _, port_b = await node_b.start()
                _, port_c = await node_c.start()
                node_a.register_peer("node-b", "127.0.0.1", port_b, relation="ff")
                node_b.register_peer("node-a", "127.0.0.1", port_a, relation="ff")
                node_b.register_peer("node-c", "127.0.0.1", port_c, relation="ff")
                node_c.register_peer("node-b", "127.0.0.1", port_b, relation="ff")

                set_from_c = {
                    "cmd": "set",
                    "ns": "default",
                    "key": "x",
                    "entry": {"v": 1, "ts": 1000.002, "exp": None, "deleted": False},
                    "seen": ["node-c"],
                }
                old_delete_from_a = {
                    "cmd": "delete",
                    "ns": "default",
                    "key": "x",
                    "entry": {"v": None, "ts": 1000.001, "exp": None, "deleted": True},
                    "seen": ["node-a"],
                }

                node_c._local_data.setdefault("default", {})["x"] = dict(set_from_c["entry"])
                await node_b._process_inbound(set_from_c, None)  # type: ignore[arg-type]
                await _wait_for_gsd_value(node_a, "x", 1)
                await node_b._process_inbound(old_delete_from_a, None)  # type: ignore[arg-type]

                await asyncio.sleep(0.2)
                assert await node_b.get("x") == 1
                assert await node_c.get("x") == 1
                assert node_b._local_data["default"]["x"]["ts"] == 1000.002
                assert node_c._local_data["default"]["x"]["ts"] == 1000.002
            finally:
                await node_c.stop()
                await node_b.stop()
                await node_a.stop()

        asyncio.run(scenario())

    def test_three_node_jitter_keeps_newest_entries_across_namespaces(self):
        async def wait_entry(
            gsd: GlobalSharedDict,
            namespace: str,
            key: str,
            predicate,
            timeout: float = 3.0,
        ) -> None:
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                entry = gsd._local_data.get(namespace, {}).get(key)
                if predicate(entry):
                    return
                await asyncio.sleep(0.05)
            raise AssertionError(f"Expected {namespace}.{key} to match predicate, got {gsd._local_data.get(namespace, {}).get(key)!r}")

        async def scenario() -> None:
            node_a = GlobalSharedDict(AppSharedData("gsd-jitter-node-a-live"), listen_port=0, node_id="node-a")
            node_b = GlobalSharedDict(AppSharedData("gsd-jitter-node-b-live"), listen_port=0, node_id="node-b", broadcast_fanout=2)
            node_c = GlobalSharedDict(AppSharedData("gsd-jitter-node-c-live"), listen_port=0, node_id="node-c")
            try:
                _, port_a = await node_a.start()
                _, port_b = await node_b.start()
                _, port_c = await node_c.start()
                node_a.register_peer("node-b", "127.0.0.1", port_b, relation="ff")
                node_b.register_peer("node-a", "127.0.0.1", port_a, relation="ff")
                node_b.register_peer("node-c", "127.0.0.1", port_c, relation="ff")
                node_c.register_peer("node-b", "127.0.0.1", port_b, relation="ff")

                alpha_new_set = {
                    "cmd": "set",
                    "ns": "alpha",
                    "key": "x",
                    "entry": {"v": 1, "ts": 1000.004, "exp": None, "deleted": False},
                    "seen": ["node-c"],
                }
                alpha_old_delete = {
                    "cmd": "delete",
                    "ns": "alpha",
                    "key": "x",
                    "entry": {"v": None, "ts": 1000.001, "exp": None, "deleted": True},
                    "seen": ["node-a"],
                }
                beta_new_delete = {
                    "cmd": "delete",
                    "ns": "beta",
                    "key": "y",
                    "entry": {"v": None, "ts": 1000.006, "exp": None, "deleted": True},
                    "seen": ["node-c"],
                }
                beta_old_set = {
                    "cmd": "set",
                    "ns": "beta",
                    "key": "y",
                    "entry": {"v": "stale", "ts": 1000.002, "exp": None, "deleted": False},
                    "seen": ["node-a"],
                }

                node_c._local_data.setdefault("alpha", {})["x"] = dict(alpha_new_set["entry"])
                node_c._local_data.setdefault("beta", {})["y"] = dict(beta_new_delete["entry"])

                await node_b._process_inbound(alpha_new_set, None)  # type: ignore[arg-type]
                await node_b._process_inbound(beta_new_delete, None)  # type: ignore[arg-type]
                await _wait_for_gsd_value(node_a, "x", 1, namespace="alpha")
                await wait_entry(node_a, "beta", "y", lambda entry: isinstance(entry, dict) and entry.get("deleted") is True)

                await node_b._process_inbound(alpha_old_delete, None)  # type: ignore[arg-type]
                await node_b._process_inbound(beta_old_set, None)  # type: ignore[arg-type]

                await asyncio.sleep(0.2)
                for node in (node_a, node_b, node_c):
                    assert await node.get("x", namespace="alpha") == 1
                    assert await node.get("y", namespace="beta") is None
                    assert node._local_data["alpha"]["x"]["ts"] == 1000.004
                    assert node._local_data["beta"]["y"]["ts"] == 1000.006
                    assert node._local_data["beta"]["y"].get("deleted") is True
            finally:
                await node_c.stop()
                await node_b.stop()
                await node_a.stop()

        asyncio.run(asyncio.wait_for(scenario(), timeout=6.0))

    def test_three_node_randomized_jitter_converges_by_lww_timestamp(self):
        async def scenario() -> None:
            random_source = random.Random(20260508)
            nodes = [
                GlobalSharedDict(AppSharedData("gsd-fuzz-node-a"), listen_port=0, node_id="node-a"),
                GlobalSharedDict(AppSharedData("gsd-fuzz-node-b"), listen_port=0, node_id="node-b"),
                GlobalSharedDict(AppSharedData("gsd-fuzz-node-c"), listen_port=0, node_id="node-c"),
            ]
            namespaces = ["alpha", "beta", "gamma"]
            keys = [f"key-{index}" for index in range(8)]
            expected_entries: dict[tuple[str, str], dict[str, object]] = {}
            deliveries: list[tuple[GlobalSharedDict, dict[str, object]]] = []
            timestamp = 1000.0

            try:
                for index in range(80):
                    timestamp += random_source.choice([0.001, 0.002, 0.005, 0.011])
                    namespace = random_source.choice(namespaces)
                    key = random_source.choice(keys)
                    deleted = random_source.random() < 0.34
                    entry = {
                        "v": None if deleted else {"round": index, "source": random_source.choice(["node-a", "node-b", "node-c"])},
                        "ts": timestamp,
                        "exp": None,
                        "deleted": deleted,
                    }
                    payload = {
                        "cmd": "delete" if deleted else "set",
                        "ns": namespace,
                        "key": key,
                        "entry": dict(entry),
                        "seen": [f"origin-{index % 3}"],
                    }
                    current_expected = expected_entries.get((namespace, key))
                    if current_expected is None or timestamp > float(current_expected["ts"]):
                        expected_entries[(namespace, key)] = dict(entry)
                    for node in nodes:
                        deliveries.append((node, dict(payload)))

                random_source.shuffle(deliveries)
                for node, payload in deliveries:
                    await node._process_inbound(payload, None)  # type: ignore[arg-type]

                for node in nodes:
                    for (namespace, key), expected_entry in expected_entries.items():
                        local_entry = node._local_data.get(namespace, {}).get(key)
                        assert local_entry is not None
                        assert local_entry["ts"] == expected_entry["ts"]
                        assert bool(local_entry.get("deleted")) is bool(expected_entry.get("deleted"))
                        if expected_entry.get("deleted"):
                            assert await node.get(key, namespace=namespace) is None
                        else:
                            assert await node.get(key, namespace=namespace) == expected_entry["v"]
            finally:
                for node in nodes:
                    await node.stop()

        asyncio.run(scenario())


class TestNodeRegistry:
    def test_registry_state_is_shared_between_instances(self):
        async def scenario() -> None:
            shared_data = AppSharedData("node-registry-shared-test")
            namespace = "node-registry-shared-test"
            worker_a = NodeRegistry(shared_data=shared_data, namespace=namespace)
            worker_b = NodeRegistry(shared_data=shared_data, namespace=namespace)

            await worker_a.register("node-a", "127.0.0.1", 18000, relation="pc", gsd_port=28000)
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
                await registry.register("node-b", "127.0.0.1", 1, relation="ff")
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

    def test_registry_probe_merges_distributed_health_metadata(self):
        async def scenario() -> None:
            from aiohttp import web

            async def handle_health(request: web.Request) -> web.Response:
                return web.json_response({
                    "node_id": "node-metrics",
                    "status": "ok",
                    "metadata": {"cpu": "9.5%", "memory": "20.0%"},
                })

            app = web.Application()
            app.router.add_get("/_internal/admin/api/distributed/health", handle_health)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-probe-metadata-test"),
                namespace="node-registry-probe-metadata-test",
            )
            try:
                node = await registry.register("node-metrics", "127.0.0.1", port, relation="ff")
                await registry._probe_node(node)
                updated = await registry.get("node-metrics")
                assert updated is not None
                assert updated.metadata["cpu"] == "9.5%"
                assert updated.metadata["memory"] == "20.0%"
            finally:
                await runner.cleanup()

        asyncio.run(scenario())

    def test_registry_probe_records_packet_loss_metadata(self):
        async def scenario() -> None:
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-probe-loss-test"),
                namespace="node-registry-probe-loss-test",
            )
            await registry.register("node-loss", "127.0.0.1", 18000, relation="ff")

            await registry.record_probe_result("node-loss", success=True, rtt_ms=12.0)
            await registry.record_probe_result("node-loss", success=False)
            await registry.record_probe_result("node-loss", success=False)

            updated = await registry.get("node-loss")
            assert updated is not None
            assert updated.metadata["probe_total"] == "3"
            assert updated.metadata["probe_failed"] == "2"
            assert updated.metadata["packet_loss"] == "66.7%"
            assert float(updated.metadata["last_probe_at"]) > 0

        asyncio.run(scenario())

    def test_registry_forward_scope_follows_pc_chain_and_child_opt_in(self):
        async def scenario() -> None:
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-forward-scope-test"),
                namespace="node-registry-forward-scope-test",
            )
            await registry.register(
                "node-b",
                "127.0.0.1",
                18000,
                relation="pc",
                metadata={"parent_id": "node-a"},
            )
            await registry.register(
                "node-c",
                "127.0.0.1",
                18001,
                relation="pc",
                metadata={"parent_id": "node-b"},
            )
            assert await registry.can_forward_to("node-a", "node-c") is True
            assert await registry.can_forward_to("node-c", "node-a") is False

            await registry.register(
                "node-b",
                "127.0.0.1",
                18000,
                relation="pc",
                metadata={"parent_id": "node-a"},
                allow_child_api_forward=True,
            )
            await registry.register(
                "node-c",
                "127.0.0.1",
                18001,
                relation="pc",
                metadata={"parent_id": "node-b"},
                allow_child_api_forward=True,
            )
            assert await registry.can_forward_to("node-c", "node-a") is True

        asyncio.run(scenario())

    def test_registry_forward_scope_understands_local_parent_record(self):
        async def scenario() -> None:
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-local-parent-forward-test"),
                namespace="node-registry-local-parent-forward-test",
            )
            await registry.register(
                "node-a",
                "127.0.0.1",
                18000,
                relation="pc",
                metadata={"parent_id": "node-a"},
            )
            assert await registry.can_forward_to("node-b", "node-a") is False

            await registry.register(
                "node-a",
                "127.0.0.1",
                18000,
                relation="pc",
                metadata={"parent_id": "node-a"},
                allow_child_api_forward=True,
            )
            assert await registry.can_forward_to("node-b", "node-a") is True

        asyncio.run(scenario())

    def test_registry_management_scope_updates_when_pc_chain_changes_to_ff(self):
        async def scenario() -> None:
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-management-relation-change-test"),
                namespace="node-registry-management-relation-change-test",
            )
            await registry.register(
                "node-b",
                "127.0.0.1",
                18000,
                relation="pc",
                metadata={"parent_id": "node-a"},
            )
            await registry.register(
                "node-c",
                "127.0.0.1",
                18001,
                relation="pc",
                metadata={"parent_id": "node-b"},
            )
            route = await registry.management_route("node-a", "node-c")
            assert route is not None
            assert [node.node_id for node in route] == ["node-b", "node-c"]

            await registry.register(
                "node-b",
                "127.0.0.1",
                18000,
                relation="ff",
                metadata={"parent_id": ""},
            )
            assert await registry.management_route("node-a", "node-c") is None
            assert await registry.management_route("node-a", "node-b") is None

        asyncio.run(scenario())

    def test_registry_management_scope_does_not_cross_friend_branch(self):
        async def scenario() -> None:
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-friend-branch-management-test"),
                namespace="node-registry-friend-branch-management-test",
            )
            await registry.register(
                "node-b",
                "127.0.0.1",
                18000,
                relation="pc",
                metadata={"parent_id": "node-c"},
            )
            await registry.register(
                "node-a",
                "127.0.0.1",
                18001,
                relation="ff",
                metadata={"parent_id": "node-b"},
            )
            route_to_b = await registry.management_route("node-c", "node-b")
            assert route_to_b is not None
            assert [node.node_id for node in route_to_b] == ["node-b"]
            assert await registry.management_route("node-c", "node-a") is None

        asyncio.run(scenario())

    def test_registry_management_scope_crosses_anchored_pp_edge(self):
        async def scenario() -> None:
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-anchored-pp-management-test"),
                namespace="node-registry-anchored-pp-management-test",
            )
            await registry.register(
                "node-b",
                "127.0.0.1",
                18000,
                relation="pc",
                metadata={"parent_id": "node-c"},
            )
            await registry.register(
                "node-a",
                "127.0.0.1",
                18001,
                relation="pp",
                metadata={"parent_id": "node-b"},
            )

            route_to_b = await registry.management_route("node-c", "node-b")
            assert route_to_b is not None
            assert [node.node_id for node in route_to_b] == ["node-b"]
            route_to_a = await registry.management_route("node-c", "node-a")
            assert route_to_a is not None
            assert [node.node_id for node in route_to_a] == ["node-b", "node-a"]

            assert await registry.can_forward_to("node-c", "node-a") is True
            assert await registry.can_forward_to("node-a", "node-c") is False

        asyncio.run(scenario())

    def test_registry_management_scope_loses_pp_descendant_when_pc_parent_becomes_ff(self):
        async def scenario() -> None:
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-anchored-pp-relation-change-test"),
                namespace="node-registry-anchored-pp-relation-change-test",
            )
            await registry.register(
                "node-b",
                "127.0.0.1",
                18000,
                relation="pc",
                metadata={"parent_id": "node-c"},
            )
            await registry.register(
                "node-a",
                "127.0.0.1",
                18001,
                relation="pp",
                metadata={"parent_id": "node-b"},
            )
            assert await registry.management_route("node-c", "node-a") is not None

            await registry.register(
                "node-b",
                "127.0.0.1",
                18000,
                relation="ff",
                metadata={"parent_id": ""},
            )

            assert await registry.management_route("node-c", "node-b") is None
            assert await registry.management_route("node-c", "node-a") is None

        asyncio.run(scenario())

    def test_registry_original_three_node_topology_transitions_are_closed(self):
        async def scenario() -> None:
            registry = NodeRegistry(
                shared_data=AppSharedData("node-registry-original-topology-test"),
                namespace="node-registry-original-topology-test",
            )

            async def route_ids(root_id: str, target_id: str) -> list[str] | None:
                route = await registry.management_route(root_id, target_id)
                if route is None:
                    return None
                return [node.node_id for node in route]

            async def child_can_forward_to_parent(allowed: bool) -> bool:
                child_view_registry = NodeRegistry(
                    shared_data=AppSharedData(f"node-registry-child-forward-{allowed}"),
                    namespace=f"node-registry-child-forward-{allowed}",
                )
                await child_view_registry.register(
                    "node-a",
                    "127.0.0.1",
                    18000,
                    relation="pc",
                    metadata={"parent_id": "node-a"},
                    allow_child_api_forward=allowed,
                )
                return await child_view_registry.can_forward_to("node-b", "node-a")

            await registry.register(
                "node-b",
                "127.0.0.1",
                18001,
                relation="pc",
                metadata={"parent_id": "node-a"},
            )
            await registry.register(
                "node-c",
                "127.0.0.1",
                18002,
                relation="pc",
                metadata={"parent_id": "node-b"},
            )

            assert await route_ids("node-a", "node-c") == ["node-b", "node-c"]
            assert await registry.can_forward_to("node-a", "node-c") is True
            assert await registry.can_forward_to("node-c", "node-a") is False
            assert await child_can_forward_to_parent(False) is False
            assert await child_can_forward_to_parent(True) is True

            await registry.register(
                "node-b",
                "127.0.0.1",
                18001,
                relation="pc",
                metadata={"parent_id": "node-c"},
            )
            await registry.unregister("node-c")
            await registry.register(
                "node-a",
                "127.0.0.1",
                18000,
                relation="pp",
                metadata={"parent_id": "node-b"},
            )

            assert await route_ids("node-a", "node-c") is None
            assert await route_ids("node-b", "node-a") == ["node-a"]
            assert await route_ids("node-c", "node-b") == ["node-b"]
            assert await route_ids("node-c", "node-a") == ["node-b", "node-a"]
            assert await registry.can_forward_to("node-c", "node-a") is True
            assert await registry.can_forward_to("node-a", "node-c") is False

            await registry.register(
                "node-a",
                "127.0.0.1",
                18000,
                relation="ff",
                metadata={"parent_id": "", "parent_node_id": ""},
            )

            assert await route_ids("node-a", "node-b") is None
            assert await route_ids("node-b", "node-a") is None
            assert await route_ids("node-c", "node-a") is None
            assert await route_ids("node-c", "node-b") == ["node-b"]

        asyncio.run(scenario())
