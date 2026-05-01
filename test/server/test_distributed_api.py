# -*- coding: utf-8 -*-
"""Tests for distributed network API."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

_server_dir = Path(__file__).resolve().parent.parent.parent / "app" / "core" / "server"
if str(_server_dir.parent.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent.parent))
if str(_server_dir.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent))

from _test_helpers import FullAppTestBase
from core.server.data_types.apikey import create_apikey, delete_apikey
from core.server.distributed import NodeRegistry
from core.server.distributed.node import Node
from core.server.distributed.auth import respond_to_challenge


class _AdminAPIKeyTestBase(FullAppTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._admin_apikey = await create_apikey(
            name="distributed admin test key",
            whitelist_routes="all",
            blacklist_routes=[],
        )

    async def asyncTearDown(self):
        try:
            if getattr(self, "_admin_apikey", None) is not None:
                await delete_apikey(str(getattr(self._admin_apikey, "id", "") or ""))
        finally:
            await super().asyncTearDown()

    def _admin_headers(self) -> dict[str, str]:
        return {"x-api-key": str(self._admin_apikey.key)}


class TestDistributedSelf(_AdminAPIKeyTestBase):
    async def test_get_self(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/api/distributed/self", headers=headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("node_id", data)
        self.assertIn("worker_count", data)


class TestDistributedHealth(FullAppTestBase):
    async def test_health_endpoint(self):
        r = await self._client.get("/_internal/admin/api/distributed/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("node_id", data)


class TestDistributedNodes(_AdminAPIKeyTestBase):
    async def test_register_node(self):
        headers = self._admin_headers()
        r = await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-a",
            "host": "127.0.0.1",
            "port": 18000,
            "relation": "friend",
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["node_id"], "node-a")
        self.assertEqual(data["relation"], "friend")

    async def test_list_nodes(self):
        headers = self._admin_headers()
        await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-b",
            "host": "127.0.0.1",
            "port": 18001,
            "relation": "child",
        })
        r = await self._client.get("/_internal/admin/api/distributed/nodes", headers=headers)
        self.assertEqual(r.status_code, 200)
        nodes = r.json()
        self.assertTrue(any(n["node_id"] == "node-b" for n in nodes))

    async def test_list_nodes_by_relation(self):
        headers = self._admin_headers()
        await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-c",
            "host": "127.0.0.1",
            "port": 18002,
            "relation": "parent",
        })
        r = await self._client.get("/_internal/admin/api/distributed/nodes?relation=parent", headers=headers)
        self.assertEqual(r.status_code, 200)
        nodes = r.json()
        self.assertTrue(all(n["relation"] == "parent" for n in nodes))

    async def test_get_node(self):
        headers = self._admin_headers()
        await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-d",
            "host": "127.0.0.1",
            "port": 18003,
        })
        r = await self._client.get("/_internal/admin/api/distributed/nodes/node-d", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["node_id"], "node-d")

    async def test_get_node_404(self):
        headers = self._admin_headers()
        r = await self._client.get("/_internal/admin/api/distributed/nodes/nonexistent", headers=headers)
        self.assertEqual(r.status_code, 404)

    async def test_delete_node(self):
        headers = self._admin_headers()
        await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-e",
            "host": "127.0.0.1",
            "port": 18004,
        })
        r = await self._client.delete("/_internal/admin/api/distributed/nodes/node-e", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        r2 = await self._client.get("/_internal/admin/api/distributed/nodes/node-e", headers=headers)
        self.assertEqual(r2.status_code, 404)

    async def test_ping_node_success(self):
        from aiohttp import web

        async def handle_health(request: web.Request) -> web.Response:
            return web.json_response({"node_id": "node-ping", "status": "ok", "worker_count": 1})

        app = web.Application()
        app.router.add_get("/_internal/admin/api/distributed/health", handle_health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        headers = self._admin_headers()
        try:
            await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
                "node_id": "node-ping",
                "host": "127.0.0.1",
                "port": port,
                "relation": "friend",
            })
            r = await self._client.post("/_internal/admin/api/distributed/nodes/node-ping/ping", headers=headers, json={})
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertTrue(data["ok"])
            self.assertFalse(data["relayed"])
            self.assertGreaterEqual(data["rtt_ms"], 0)
            self.assertEqual(data["response"]["status"], "ok")
        finally:
            await runner.cleanup()


class TestDistributedAuth(_AdminAPIKeyTestBase):
    async def test_auth_challenge(self):
        headers = self._admin_headers()
        await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-auth",
            "host": "127.0.0.1",
            "port": 18005,
            "admin_password_hash": "abcd1234" * 4,
        })
        r = await self._client.post("/_internal/admin/api/distributed/nodes/node-auth/auth/challenge", headers=headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("nonce", data)
        self.assertIn("timestamp", data)

    async def test_auth_verify(self):
        password_hash = "abcd1234" * 4
        headers = self._admin_headers()
        await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-verify",
            "host": "127.0.0.1",
            "port": 18006,
            "admin_password_hash": password_hash,
        })
        challenge_r = await self._client.post("/_internal/admin/api/distributed/nodes/node-verify/auth/challenge", headers=headers)
        challenge = challenge_r.json()
        response = respond_to_challenge(challenge, password_hash)
        r = await self._client.post("/_internal/admin/api/distributed/nodes/node-verify/auth/verify", headers=headers, json=response)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])


class TestDistributedBroadcast(_AdminAPIKeyTestBase):
    async def test_broadcast(self):
        headers = self._admin_headers()
        r = await self._client.post("/_internal/admin/api/distributed/broadcast", headers=headers, json={
            "message": {"hello": "world"},
            "target_relations": ["friend"],
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("sent", data)


class _FakeBroadcastRegistry:
    def __init__(self, nodes: list[Node]) -> None:
        self._nodes = {node.node_id: node for node in nodes}

    async def get(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    async def all(self) -> list[Node]:
        return list(self._nodes.values())

    async def by_relation(self, relation: str) -> list[Node]:
        return [node for node in self._nodes.values() if node.relation == relation]


def test_broadcast_reaches_target_through_two_relays(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from core.server.routes.distributed import main as distributed_main

        context: dict[str, object] = {}
        received_by_leaf: list[dict[str, object]] = []

        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: context["registry"]),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid=context["self_id"])),
        )

        async def make_site(self_id: str, registry: _FakeBroadcastRegistry):
            async def handle(request: web.Request) -> web.Response:
                context["self_id"] = self_id
                context["registry"] = registry
                payload = await request.json()
                if self_id == "leaf":
                    received_by_leaf.append(payload)
                result = await distributed_main.broadcast_message(
                    distributed_main.BroadcastRequest.model_validate(payload)
                )
                return web.json_response(result)

            app = web.Application()
            app.router.add_post("/_internal/admin/api/distributed/broadcast", handle)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            socket = site._server.sockets[0]
            port = socket.getsockname()[1]
            return runner, port

        leaf_registry = _FakeBroadcastRegistry([])
        leaf_runner, leaf_port = await make_site("leaf", leaf_registry)
        relay_b_registry = _FakeBroadcastRegistry([
            Node("leaf", "127.0.0.1", leaf_port, relation="friend"),
        ])
        relay_b_runner, relay_b_port = await make_site("relay-b", relay_b_registry)
        relay_a_registry = _FakeBroadcastRegistry([
            Node("relay-b", "127.0.0.1", relay_b_port, relation="friend"),
        ])
        relay_a_runner, relay_a_port = await make_site("relay-a", relay_a_registry)
        try:
            master_registry = _FakeBroadcastRegistry([
                Node("leaf", "127.0.0.1", 1, relation="friend"),
                Node("relay-a", "127.0.0.1", relay_a_port, relation="friend"),
            ])
            context["self_id"] = "master"
            context["registry"] = master_registry

            result = await distributed_main.broadcast_message(
                distributed_main.BroadcastRequest(
                    message={"kind": "probe"},
                    target_nodes=["leaf"],
                    ttl=8,
                )
            )

            assert result["sent"] == 1
            assert result["failed"] == 1
            assert len(received_by_leaf) == 1
            payload = received_by_leaf[0]
            assert payload["origin_node"] == "master"
            assert payload["target_nodes"] == ["leaf"]
            assert payload["from_node"] == "relay-b"
            assert payload["seen_nodes"] == ["master", "relay-a", "relay-b"]
        finally:
            await relay_a_runner.cleanup()
            await relay_b_runner.cleanup()
            await leaf_runner.cleanup()

    asyncio.run(scenario())


class _FakeCommandRegistry:
    def __init__(self, nodes: list[Node]) -> None:
        self._nodes = {node.node_id: node for node in nodes}

    async def get(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    async def all(self) -> list[Node]:
        return list(self._nodes.values())

    async def management_route(self, root_id: str, target_id: str) -> list[Node] | None:
        registry = NodeRegistry(shared_data=None, namespace="fake-command-registry")
        registry.all = self.all  # type: ignore[method-assign]
        return await registry.management_route(root_id, target_id)


class _FakePingRegistry:
    def __init__(self, nodes: list[Node]) -> None:
        self._nodes = {node.node_id: node for node in nodes}
        self.health_updates: list[tuple[str, bool, float | None]] = []

    async def get(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    async def all(self) -> list[Node]:
        return list(self._nodes.values())

    async def management_route(self, root_id: str, target_id: str) -> list[Node] | None:
        return None

    async def update_health(self, node_id: str, success: bool, rtt_ms: float | None = None) -> None:
        self.health_updates.append((node_id, success, rtt_ms))


def test_ping_node_reaches_target_through_relay(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from core.server.routes.distributed import main as distributed_main

        context: dict[str, object] = {}

        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: context["registry"]),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid=context["self_id"])),
        )

        async def make_health_site():
            async def handle_health(request: web.Request) -> web.Response:
                return web.json_response({"node_id": "leaf", "status": "ok"})

            app = web.Application()
            app.router.add_get("/_internal/admin/api/distributed/health", handle_health)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            return runner, site._server.sockets[0].getsockname()[1]

        async def make_relay_site(registry: _FakePingRegistry):
            async def handle_ping(request: web.Request) -> web.Response:
                context["self_id"] = "relay"
                context["registry"] = registry
                payload = await request.json()
                result = await distributed_main.ping_node(
                    request.match_info["node_id"],
                    distributed_main.PingNodeRequest.model_validate(payload),
                )
                return web.json_response(result)

            app = web.Application()
            app.router.add_post("/_internal/admin/api/distributed/nodes/{node_id}/ping", handle_ping)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            return runner, site._server.sockets[0].getsockname()[1]

        leaf_runner, leaf_port = await make_health_site()
        relay_registry = _FakePingRegistry([
            Node("leaf", "127.0.0.1", leaf_port, relation="friend"),
        ])
        relay_runner, relay_port = await make_relay_site(relay_registry)
        master_registry = _FakePingRegistry([
            Node("leaf", "127.0.0.1", 1, relation="friend"),
            Node("relay", "127.0.0.1", relay_port, relation="friend"),
        ])
        context["self_id"] = "master"
        context["registry"] = master_registry
        try:
            result = await distributed_main.ping_node(
                "leaf",
                distributed_main.PingNodeRequest(),
            )
            assert result["ok"] is True
            assert result["relayed"] is True
            assert result["via_node"] == "relay"
            assert result["route"] == ["master", "relay", "leaf"]
            assert result["rtt_ms"] >= 0
            assert any(update[0] == "leaf" and update[1] is True for update in master_registry.health_updates)
        finally:
            await relay_runner.cleanup()
            await leaf_runner.cleanup()

    asyncio.run(scenario())


def test_management_command_reaches_child_descendant_through_relay(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from core.server.routes.distributed import main as distributed_main

        context: dict[str, object] = {}
        received_by_leaf: list[dict[str, object]] = []

        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: context["registry"]),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid=context["self_id"])),
        )

        async def make_leaf_site():
            async def handle(request: web.Request) -> web.Response:
                payload = await request.json()
                received_by_leaf.append(payload)
                result = await distributed_main.receive_command(
                    distributed_main.CommandRequest.model_validate(payload)
                )
                return web.json_response(result)

            app = web.Application()
            app.router.add_post("/_internal/admin/api/distributed/command", handle)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            return runner, site._server.sockets[0].getsockname()[1]

        async def make_relay_site(self_id: str, registry: _FakeCommandRegistry):
            async def handle(request: web.Request) -> web.Response:
                context["self_id"] = self_id
                context["registry"] = registry
                payload = await request.json()
                result = await distributed_main.send_command_to_node(
                    request.match_info["node_id"],
                    distributed_main.CommandRequest.model_validate(payload),
                )
                return web.json_response(result)

            app = web.Application()
            app.router.add_post("/_internal/admin/api/distributed/nodes/{node_id}/command", handle)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            return runner, site._server.sockets[0].getsockname()[1]

        leaf_runner, leaf_port = await make_leaf_site()
        relay_registry = _FakeCommandRegistry([
            Node("node-c", "127.0.0.1", leaf_port, relation="child"),
        ])
        relay_runner, relay_port = await make_relay_site("node-b", relay_registry)
        try:
            root_registry = _FakeCommandRegistry([
                Node("node-b", "127.0.0.1", relay_port, relation="child"),
                Node("node-c", "127.0.0.1", 1, relation="child", metadata={"parent_id": "node-b"}),
            ])
            context["self_id"] = "node-a"
            context["registry"] = root_registry

            result = await distributed_main.send_command_to_node(
                "node-c",
                distributed_main.CommandRequest(command="set_workers", args={"workers": 2}),
            )

            assert result["ok"] is True
            assert len(received_by_leaf) == 1
            payload = received_by_leaf[0]
            assert payload["origin_node"] == "node-a"
            assert payload["from_node"] == "node-b"
            assert payload["seen_nodes"] == ["node-a", "node-b"]
        finally:
            await relay_runner.cleanup()
            await leaf_runner.cleanup()

    asyncio.run(scenario())


def test_management_command_rejects_friend_branch(monkeypatch):
    async def scenario() -> None:
        from core.server.routes.distributed import main as distributed_main

        registry = _FakeCommandRegistry([
            Node("node-b", "127.0.0.1", 18000, relation="child"),
            Node("node-c", "127.0.0.1", 18001, relation="friend", metadata={"parent_id": "node-b"}),
        ])
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid="node-a")),
        )

        try:
            await distributed_main.send_command_to_node(
                "node-c",
                distributed_main.CommandRequest(command="set_workers", args={}),
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("friend branch command should be rejected")

    asyncio.run(scenario())


class TestDistributedCommand(_AdminAPIKeyTestBase):
    async def test_receive_set_workers_command(self):
        headers = self._admin_headers()
        r = await self._client.post("/_internal/admin/api/distributed/command", headers=headers, json={
            "command": "set_workers",
            "args": {"workers": 4},
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    async def test_receive_unknown_command(self):
        headers = self._admin_headers()
        r = await self._client.post("/_internal/admin/api/distributed/command", headers=headers, json={
            "command": "fly_to_moon",
            "args": {},
        })
        self.assertEqual(r.status_code, 400)
