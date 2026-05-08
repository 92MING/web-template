# -*- coding: utf-8 -*-
"""Tests for distributed network API."""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from starlette.requests import Request

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


def test_distributed_node_receiver_paths_are_admin_auth_exempt():
    from core.server.routes.admin.auth import _is_auth_exempt_path

    assert _is_auth_exempt_path("/_internal/admin/api/distributed/health") is True
    assert _is_auth_exempt_path("/_internal/admin/api/distributed/connect") is True
    assert _is_auth_exempt_path("/_internal/admin/api/distributed/connect-to") is False


def test_connection_ban_expires_resets_and_escalates(monkeypatch):
    from core.server.routes.distributed import main as distributed_main
    from core.server.shared import AppSharedData

    ip = "203.0.113.9"
    now = 1000.0
    old_pass = os.environ.get("FRIEND_NODE_CONN_PASS")
    os.environ["FRIEND_NODE_CONN_PASS"] = "secret"
    distributed_main._CONNECTION_BANS.clear()
    AppSharedData.Get().clear_shared_dict(distributed_main._CONNECTION_BAN_NAMESPACE)
    monkeypatch.setattr(distributed_main.time, "time", lambda: now)
    try:
        for _ in range(3):
            try:
                distributed_main._check_connection_auth(ip, "ff", "wrong")
            except HTTPException as exc:
                assert exc.status_code == 401
            else:
                raise AssertionError("wrong password should fail")

        record = distributed_main._connection_ban_record(ip)
        assert record["failures"] == 3
        assert record["banned_until"] == now + 10 * 60

        try:
            distributed_main._check_connection_auth(ip, "ff", "secret")
        except HTTPException as exc:
            assert exc.status_code == 429
        else:
            raise AssertionError("active ban should reject even correct password")

        now += 10 * 60 + 1
        distributed_main._check_connection_auth(ip, "ff", "secret")
        record = distributed_main._connection_ban_record(ip)
        assert record == {"failures": 0, "banned_until": 0.0}

        ban_durations: list[float] = []
        for _ in range(4):
            attempt_time = now
            try:
                distributed_main._check_connection_auth(ip, "ff", "wrong")
            except HTTPException as exc:
                assert exc.status_code == 401
            else:
                raise AssertionError("wrong password should fail")
            banned_until = float(distributed_main._connection_ban_record(ip)["banned_until"])
            if banned_until:
                ban_durations.append(banned_until - attempt_time)
                now = banned_until + 1

        record = distributed_main._connection_ban_record(ip)
        assert record["failures"] == 4
        assert ban_durations == [10 * 60, 20 * 60]
    finally:
        distributed_main._CONNECTION_BANS.clear()
        AppSharedData.Get().clear_shared_dict(distributed_main._CONNECTION_BAN_NAMESPACE)
        if old_pass is None:
            os.environ.pop("FRIEND_NODE_CONN_PASS", None)
        else:
            os.environ["FRIEND_NODE_CONN_PASS"] = old_pass


class TestDistributedNodes(_AdminAPIKeyTestBase):
    async def test_register_node(self):
        headers = self._admin_headers()
        r = await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-a",
            "host": "127.0.0.1",
            "port": 18000,
            "relation": "ff",
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["node_id"], "node-a")
        self.assertEqual(data["relation"], "ff")

    async def test_list_nodes(self):
        headers = self._admin_headers()
        await self._client.post("/_internal/admin/api/distributed/nodes", headers=headers, json={
            "node_id": "node-b",
            "host": "127.0.0.1",
            "port": 18001,
            "relation": "pc",
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
            "relation": "pc",
        })
        r = await self._client.get("/_internal/admin/api/distributed/nodes?relation=pc", headers=headers)
        self.assertEqual(r.status_code, 200)
        nodes = r.json()
        self.assertTrue(all(n["relation"] == "pc" for n in nodes))

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
                "relation": "ff",
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

    async def test_connect_password_bans_after_three_failures(self):
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        headers = self._admin_headers()
        old_pass = os.environ.get("FRIEND_NODE_CONN_PASS")
        os.environ["FRIEND_NODE_CONN_PASS"] = "secret"
        distributed_main._CONNECTION_BANS.clear()
        AppSharedData.Get().clear_shared_dict(distributed_main._CONNECTION_BAN_NAMESPACE)
        try:
            body = {
                "node_id": "node-connect",
                "host": "127.0.0.1",
                "port": 18007,
                "relation": "ff",
                "password": "wrong",
            }
            for _ in range(3):
                r = await self._client.post("/_internal/admin/api/distributed/connect", headers=headers, json=body)
                self.assertEqual(r.status_code, 401)
            r = await self._client.post("/_internal/admin/api/distributed/connect", headers=headers, json={**body, "password": "secret"})
            self.assertEqual(r.status_code, 429)
        finally:
            distributed_main._CONNECTION_BANS.clear()
            AppSharedData.Get().clear_shared_dict(distributed_main._CONNECTION_BAN_NAMESPACE)
            if old_pass is None:
                os.environ.pop("FRIEND_NODE_CONN_PASS", None)
            else:
                os.environ["FRIEND_NODE_CONN_PASS"] = old_pass

    async def test_initiate_connect_registers_remote_self_and_sends_password(self):
        from aiohttp import web
        from core.server.shared import AppSharedData

        captured: list[dict[str, object]] = []
        port_holder: dict[str, int] = {}

        async def handle_connect(request: web.Request) -> web.Response:
            payload = await request.json()
            captured.append(payload)
            return web.json_response({
                "ok": True,
                "node": payload,
                "self": {
                    "node_id": "remote-connect-target",
                    "name": "Remote Target",
                    "host": "127.0.0.1",
                    "port": port_holder["port"],
                    "gsd_port": port_holder["port"] + 1000,
                },
            })

        app = web.Application()
        app.router.add_post("/_internal/admin/api/distributed/connect", handle_connect)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port_holder["port"] = site._server.sockets[0].getsockname()[1]

        headers = self._admin_headers()
        try:
            r = await self._client.post("/_internal/admin/api/distributed/connect-to", headers=headers, json={
                "target_host": "127.0.0.1",
                "target_port": port_holder["port"],
                "target_node_id": "remote-connect-target",
                "password": "secret-pass",
                "relation": "pc",
                "metadata": {"purpose": "test"},
                "allow_child_api_forward": True,
            })
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["node"]["node_id"], "remote-connect-target")
            self.assertEqual(data["node"]["relation"], "pc")
            self.assertTrue(data["node"]["allow_child_api_forward"])

            self.assertEqual(len(captured), 1)
            sent = captured[0]
            self.assertEqual(sent["password"], "secret-pass")
            self.assertEqual(sent["relation"], "pc")
            self.assertEqual(sent["allow_child_api_forward"], True)
            self_id = AppSharedData.Get().instance_uuid
            self.assertEqual(sent["metadata"], {"purpose": "test", "parent_id": self_id})

            node = await NodeRegistry.get_instance().get("remote-connect-target")
            self.assertIsNotNone(node)
            assert node is not None
            self.assertEqual(node.name, "Remote Target")
            self.assertEqual(node.gsd_port, port_holder["port"] + 1000)
            self.assertEqual(node.metadata.get("parent_id"), self_id)
        finally:
            await runner.cleanup()


class TestDistributedBroadcast(_AdminAPIKeyTestBase):
    async def test_broadcast(self):
        headers = self._admin_headers()
        r = await self._client.post("/_internal/admin/api/distributed/broadcast", headers=headers, json={
            "message": {"hello": "world"},
            "target_relations": ["ff"],
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
            Node("leaf", "127.0.0.1", leaf_port, relation="ff"),
        ])
        relay_b_runner, relay_b_port = await make_site("relay-b", relay_b_registry)
        relay_a_registry = _FakeBroadcastRegistry([
            Node("relay-b", "127.0.0.1", relay_b_port, relation="ff"),
        ])
        relay_a_runner, relay_a_port = await make_site("relay-a", relay_a_registry)
        try:
            master_registry = _FakeBroadcastRegistry([
                Node("leaf", "127.0.0.1", 1, relation="ff"),
                Node("relay-a", "127.0.0.1", relay_a_port, relation="ff"),
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


class _FakeForwardRegistry:
    def __init__(self, nodes: list[Node]) -> None:
        self._nodes = {node.node_id: node for node in nodes}
        self.health_updates: list[tuple[str, bool, float | None]] = []

    async def get(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    async def all(self) -> list[Node]:
        return list(self._nodes.values())

    async def can_forward_to(self, self_id: str, target_id: str) -> bool:
        return target_id in self._nodes or target_id == self_id

    async def update_health(self, node_id: str, success: bool, rtt_ms: float | None = None) -> None:
        self.health_updates.append((node_id, success, rtt_ms))


def _forward_request(
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> Request:
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 0),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


def test_forward_candidates_only_rotate_inside_fast_latency_band(monkeypatch):
    async def scenario() -> None:
        from core.server.routes.distributed import main as distributed_main

        distributed_main._FORWARD_ROUND_ROBIN.clear()
        registry = _FakeForwardRegistry([
            Node("slow", "127.0.0.1", 18001, relation="ff", rtt_ms=400.0),
            Node("fast-b", "127.0.0.1", 18002, relation="ff", rtt_ms=12.0),
            Node("fast-a", "127.0.0.1", 18003, relation="ff", rtt_ms=10.0),
        ])
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid="root")),
        )

        first = await distributed_main._forward_candidates(_forward_request("/_internal/admin/api/distributed/forward/probe"))
        second = await distributed_main._forward_candidates(_forward_request("/_internal/admin/api/distributed/forward/probe"))
        third = await distributed_main._forward_candidates(_forward_request("/_internal/admin/api/distributed/forward/probe"))

        assert [node.node_id for node in first] == ["fast-a", "fast-b", "slow"]
        assert [node.node_id for node in second] == ["fast-b", "fast-a", "slow"]
        assert [node.node_id for node in third] == ["fast-a", "fast-b", "slow"]

    asyncio.run(scenario())


def test_forward_api_retries_non_stream_500_on_next_candidate(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from core.server.routes.distributed import main as distributed_main

        distributed_main._FORWARD_ROUND_ROBIN.clear()

        async def make_site(node_id: str, status: int):
            async def handle(request: web.Request) -> web.Response:
                return web.json_response({"node_id": node_id}, status=status)

            app = web.Application()
            app.router.add_get("/probe", handle)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            return runner, site._server.sockets[0].getsockname()[1]

        bad_runner, bad_port = await make_site("bad", 500)
        good_runner, good_port = await make_site("good", 200)
        registry = _FakeForwardRegistry([
            Node("bad", "127.0.0.1", bad_port, relation="ff", rtt_ms=10.0),
            Node("good", "127.0.0.1", good_port, relation="ff", rtt_ms=10.0),
        ])
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid="root")),
        )
        try:
            response = await distributed_main.forward_api_request(
                "probe",
                _forward_request("/_internal/admin/api/distributed/forward/probe"),
            )
            assert response.status_code == 200
            assert response.headers["x-distributed-node-id"] == "good"
            assert json.loads(response.body.decode("utf-8")) == {"node_id": "good"}
            assert registry.health_updates == [("bad", False, None), ("good", True, None)]
        finally:
            await bad_runner.cleanup()
            await good_runner.cleanup()

    asyncio.run(scenario())


def test_forward_api_records_success_count_in_node_metadata(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        distributed_main._FORWARD_ROUND_ROBIN.clear()

        async def handle(request: web.Request) -> web.Response:
            return web.json_response({"ok": True})

        app = web.Application()
        app.router.add_get("/probe", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        registry = NodeRegistry(
            shared_data=AppSharedData("distributed-forward-metadata-test"),
            namespace="distributed-forward-metadata-test",
        )
        await registry.register("forward-node", "127.0.0.1", port, relation="ff")
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid="root")),
        )
        try:
            response = await distributed_main.forward_api_request(
                "probe",
                _forward_request("/_internal/admin/api/distributed/forward/probe"),
            )
            assert response.status_code == 200
            updated = await registry.get("forward-node")
            assert updated is not None
            assert updated.metadata["forwarded"] == "1"
            assert updated.metadata["forwarded_requests"] == "1"
            assert float(updated.metadata["last_forwarded_at"]) > 0
        finally:
            await runner.cleanup()

    asyncio.run(scenario())


def test_forward_api_records_failure_count_in_node_metadata(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        distributed_main._FORWARD_ROUND_ROBIN.clear()

        async def handle(request: web.Request) -> web.Response:
            return web.json_response({"ok": False}, status=500)

        app = web.Application()
        app.router.add_get("/probe", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        registry = NodeRegistry(
            shared_data=AppSharedData("distributed-forward-failure-metadata-test"),
            namespace="distributed-forward-failure-metadata-test",
        )
        await registry.register("forward-bad-node", "127.0.0.1", port, relation="ff")
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid="root")),
        )
        try:
            response = await distributed_main.forward_api_request(
                "probe",
                _forward_request("/_internal/admin/api/distributed/forward/probe"),
            )
            assert response.status_code == 500
            updated = await registry.get("forward-bad-node")
            assert updated is not None
            assert updated.metadata["forward_failed"] == "1"
            assert float(updated.metadata["last_forward_failed_at"]) > 0
        finally:
            await runner.cleanup()

    asyncio.run(scenario())


def test_forward_api_proxies_streaming_output(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from starlette.responses import StreamingResponse
        from core.server.routes.distributed import main as distributed_main

        distributed_main._FORWARD_ROUND_ROBIN.clear()

        async def handle_stream(request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse(status=200, headers={"content-type": "text/event-stream"})
            await response.prepare(request)
            await response.write(b"data: one\n\n")
            await response.write(b"data: two\n\n")
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/stream", handle_stream)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        registry = _FakeForwardRegistry([
            Node("stream-node", "127.0.0.1", port, relation="ff", rtt_ms=5.0),
        ])
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid="root")),
        )
        try:
            response = await distributed_main.forward_api_request(
                "stream",
                _forward_request(
                    "/_internal/admin/api/distributed/forward/stream",
                    headers={"x-distributed-stream-output": "1"},
                ),
            )
            assert isinstance(response, StreamingResponse)
            assert response.status_code == 200
            assert response.headers["x-distributed-node-id"] == "stream-node"
            chunks: list[bytes] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            assert b"".join(chunks) == b"data: one\n\ndata: two\n\n"
            assert registry.health_updates == [("stream-node", True, None)]
        finally:
            await runner.cleanup()

    asyncio.run(scenario())


def test_stream_proxy_records_failure_when_remote_stream_breaks():
    async def scenario() -> None:
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        class BrokenContent:
            async def iter_chunked(self, size: int):
                yield b"data: before-break\n\n"
                raise RuntimeError("remote stream broke")

        class BrokenResponse:
            content = BrokenContent()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb) -> None:
                return None

        class Session:
            closed = False

            async def close(self) -> None:
                self.closed = True

        registry = NodeRegistry(
            shared_data=AppSharedData("distributed-stream-failure-metadata-test"),
            namespace="distributed-stream-failure-metadata-test",
        )
        node = await registry.register("stream-bad-node", "127.0.0.1", 18000, relation="ff")
        session = Session()
        chunks: list[bytes] = []
        try:
            async for chunk in distributed_main._stream_proxy_response(session, BrokenResponse(), registry, node):
                chunks.append(chunk)
        except RuntimeError as exc:
            assert str(exc) == "remote stream broke"
        else:
            raise AssertionError("broken stream should raise")

        updated = await registry.get("stream-bad-node")
        assert updated is not None
        assert chunks == [b"data: before-break\n\n"]
        assert session.closed is True
        assert updated.metadata["forward_failed"] == "1"
        assert "forwarded_requests" not in updated.metadata

    asyncio.run(scenario())


def test_forward_api_streams_large_input_and_output(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from starlette.responses import StreamingResponse
        from core.server.routes.distributed import main as distributed_main

        distributed_main._FORWARD_ROUND_ROBIN.clear()
        large_body = b"x" * (512 * 1024)

        async def handle_echo_size(request: web.Request) -> web.Response:
            size = 0
            async for chunk in request.content.iter_chunked(8192):
                size += len(chunk)
            return web.json_response({"size": size})

        async def handle_large_stream(request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse(status=200, headers={"content-type": "text/event-stream"})
            await response.prepare(request)
            for idx in range(16):
                await response.write((f"data: {idx}:" + "y" * 2048 + "\n\n").encode("utf-8"))
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_post("/echo-size", handle_echo_size)
        app.router.add_get("/large-stream", handle_large_stream)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        registry = _FakeForwardRegistry([
            Node("stream-large-node", "127.0.0.1", port, relation="ff", rtt_ms=5.0),
        ])
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid="root")),
        )
        try:
            input_response = await distributed_main.forward_api_request(
                "echo-size",
                _forward_request(
                    "/_internal/admin/api/distributed/forward/echo-size",
                    method="POST",
                    headers={"x-distributed-stream-input": "1"},
                    body=large_body,
                ),
            )
            assert input_response.status_code == 200
            assert json.loads(input_response.body.decode("utf-8")) == {"size": len(large_body)}

            output_response = await distributed_main.forward_api_request(
                "large-stream",
                _forward_request(
                    "/_internal/admin/api/distributed/forward/large-stream",
                    headers={"x-distributed-stream-output": "1"},
                ),
            )
            assert isinstance(output_response, StreamingResponse)
            chunks: list[bytes] = []
            async for chunk in output_response.body_iterator:
                chunks.append(chunk)
            body = b"".join(chunks)
            assert body.count(b"data:") == 16
            assert len(body) > 32 * 1024
            assert registry.health_updates == [
                ("stream-large-node", True, None),
                ("stream-large-node", True, None),
            ]
        finally:
            await runner.cleanup()

    asyncio.run(scenario())


def test_forward_api_stream_output_yields_before_remote_completion(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from starlette.responses import StreamingResponse
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        distributed_main._FORWARD_ROUND_ROBIN.clear()
        first_chunk_written = asyncio.Event()
        allow_finish = asyncio.Event()

        async def handle_stream(request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse(status=200, headers={"content-type": "text/event-stream"})
            await response.prepare(request)
            await response.write(b"data: first\n\n")
            first_chunk_written.set()
            await allow_finish.wait()
            await response.write(b"data: second\n\n")
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/slow-stream", handle_stream)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        registry = NodeRegistry(
            shared_data=AppSharedData("distributed-stream-backpressure-test"),
            namespace="distributed-stream-backpressure-test",
        )
        await registry.register("slow-stream-node", "127.0.0.1", port, relation="ff")
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(
            distributed_main.AppSharedData,
            "Get",
            classmethod(lambda cls: SimpleNamespace(instance_uuid="root")),
        )
        try:
            response = await distributed_main.forward_api_request(
                "slow-stream",
                _forward_request(
                    "/_internal/admin/api/distributed/forward/slow-stream",
                    headers={"x-distributed-stream-output": "1"},
                ),
            )
            assert isinstance(response, StreamingResponse)
            assert await asyncio.wait_for(first_chunk_written.wait(), timeout=2.0) is True
            iterator = response.body_iterator.__aiter__()
            first = await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
            assert first == b"data: first\n\n"
            updated_mid_stream = await registry.get("slow-stream-node")
            assert updated_mid_stream is not None
            assert "forwarded_requests" not in updated_mid_stream.metadata

            allow_finish.set()
            rest = [chunk async for chunk in iterator]
            assert b"".join(rest) == b"data: second\n\n"
            updated_after_stream = await registry.get("slow-stream-node")
            assert updated_after_stream is not None
            assert updated_after_stream.metadata["forwarded_requests"] == "1"
        finally:
            allow_finish.set()
            await runner.cleanup()

    asyncio.run(scenario())


def test_stream_proxy_does_not_prefetch_remote_chunks_before_downstream_pull():
    async def scenario() -> None:
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        class ControlledContent:
            def __init__(self) -> None:
                self.pulled: list[int] = []

            async def iter_chunked(self, size: int):
                for index in range(3):
                    self.pulled.append(index)
                    yield f"chunk-{index}".encode("utf-8")

        class ControlledResponse:
            def __init__(self, content: ControlledContent) -> None:
                self.content = content

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb) -> None:
                return None

        class Session:
            closed = False

            async def close(self) -> None:
                self.closed = True

        registry = NodeRegistry(
            shared_data=AppSharedData("distributed-stream-pull-backpressure-test"),
            namespace="distributed-stream-pull-backpressure-test",
        )
        node = await registry.register("stream-pull-node", "127.0.0.1", 18000, relation="ff")
        content = ControlledContent()
        session = Session()
        iterator = distributed_main._stream_proxy_response(
            session,
            ControlledResponse(content),
            registry,
            node,
        ).__aiter__()

        first = await asyncio.wait_for(iterator.__anext__(), timeout=1.0)
        assert first == b"chunk-0"
        await asyncio.sleep(0.05)
        assert content.pulled == [0]
        mid_stream = await registry.get("stream-pull-node")
        assert mid_stream is not None
        assert "forwarded_requests" not in mid_stream.metadata

        second = await asyncio.wait_for(iterator.__anext__(), timeout=1.0)
        assert second == b"chunk-1"
        await asyncio.sleep(0.05)
        assert content.pulled == [0, 1]

        third = await asyncio.wait_for(iterator.__anext__(), timeout=1.0)
        assert third == b"chunk-2"
        try:
            await asyncio.wait_for(iterator.__anext__(), timeout=1.0)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("stream iterator should be exhausted")

        finished = await registry.get("stream-pull-node")
        assert finished is not None
        assert finished.metadata["forwarded_requests"] == "1"
        assert session.closed is True

    asyncio.run(scenario())


def test_remote_admin_headers_prefer_node_metadata_api_key(monkeypatch):
    async def scenario() -> None:
        from core.server.routes.distributed import main as distributed_main

        monkeypatch.setattr(distributed_main, "_find_plain_admin_password", lambda: "should-not-be-used")
        node = Node(
            "node-with-key",
            "127.0.0.1",
            18000,
            relation="pc",
            metadata={"admin_api_key": "remote-key"},
        )
        headers = await distributed_main._remote_admin_headers(object(), node)

        assert headers == {"Authorization": "Bearer remote-key"}

    asyncio.run(scenario())


def test_receive_restart_command_reaches_main_process_control_socket(monkeypatch):
    async def scenario() -> None:
        from core.server import runtime_control
        from core.server.routes.distributed import main as distributed_main

        calls: list[tuple[str, str | None]] = []

        def trigger(action: str, reason: str | None) -> None:
            calls.append((action, reason))

        def request_via_control_socket(action: str, *, reason: str | None = None):
            return runtime_control._request_remote_control({"action": action, "reason": reason})

        try:
            runtime_control.install_callback_controller(
                trigger,
                mode="distributed-test-mainprocess-socket",
                note="distributed restart smoke",
            )
            main_controller = runtime_control._controller
            assert main_controller is not None
            monkeypatch.setattr(runtime_control, "request_control_action", request_via_control_socket)

            result = await distributed_main.receive_command(distributed_main.CommandRequest(
                command="restart",
                args={},
            ))

            assert result == {"ok": True, "message": "Restart requested"}
            assert calls == [("restart", "Distributed node command")]
            assert main_controller.consume_requested_action() == "restart"
        finally:
            runtime_control.shutdown_control_server()

    asyncio.run(scenario())


def test_node_runtime_metadata_uses_cached_gpu_details(monkeypatch):
    from core.server.routes.distributed import main as distributed_main

    class Shared:
        instance_uuid = "root"
        workers: dict[int, object] = {}

        def get_runtime_meta(self) -> dict[str, object]:
            return {"request_count_total": 7, "worker_count": 2}

        def get_latest_system_snapshot(self) -> None:
            return None

        def get_cache(self, key: str) -> object | None:
            assert key == "system:gpu_details"
            return {
                "summary": {
                    "gpu_count": 2,
                    "avg_utilization_percent": 12.345,
                    "total_memory_bytes": 16 * 1024 * 1024 * 1024,
                    "used_memory_bytes": 4 * 1024 * 1024 * 1024,
                }
            }

    monkeypatch.setattr(
        distributed_main.AppSharedData,
        "Get",
        classmethod(lambda cls: Shared()),
    )
    monkeypatch.setattr(
        "core.server.routes.system.monitoring._get_local_gpu_details",
        lambda: None,
    )

    metadata = distributed_main._node_runtime_metadata()

    assert metadata["handled_requests"] == "7"
    assert metadata["load"] == "2 worker(s)"
    assert metadata["gpu"] == "2 GPU 12.3% 4.0 GiB/16.0 GiB"


def test_probe_node_health_merges_remote_runtime_metadata(monkeypatch):
    async def scenario() -> None:
        from aiohttp import web
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        async def handle_health(request: web.Request) -> web.Response:
            return web.json_response({
                "node_id": "metrics-node",
                "status": "ok",
                "metadata": {
                    "cpu": "12.5%",
                    "memory": "45.0%",
                    "handled_requests": "42",
                },
            })

        app = web.Application()
        app.router.add_get("/_internal/admin/api/distributed/health", handle_health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        registry = NodeRegistry(
            shared_data=AppSharedData("probe-runtime-metadata-test"),
            namespace="probe-runtime-metadata-test",
        )
        node = await registry.register(
            "metrics-node",
            "127.0.0.1",
            port,
            relation="ff",
            metadata={"probe_total": "9", "probe_failed": "9", "packet_loss": "99.0%"},
        )
        try:
            result = await distributed_main._probe_node_health(registry, node)

            assert result["ok"] is True
            updated = await registry.get("metrics-node")
            assert updated is not None
            assert updated.metadata["cpu"] == "12.5%"
            assert updated.metadata["memory"] == "45.0%"
            assert updated.metadata["handled_requests"] == "42"
            assert updated.metadata["probe_total"] == "10"
            assert updated.metadata["probe_failed"] == "9"
            assert updated.metadata["packet_loss"] == "90.0%"
        finally:
            await runner.cleanup()

    asyncio.run(scenario())


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
            Node("leaf", "127.0.0.1", leaf_port, relation="ff"),
        ])
        relay_runner, relay_port = await make_relay_site(relay_registry)
        master_registry = _FakePingRegistry([
            Node("leaf", "127.0.0.1", 1, relation="ff"),
            Node("relay", "127.0.0.1", relay_port, relation="ff"),
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
            Node("node-c", "127.0.0.1", leaf_port, relation="pc"),
        ])
        relay_runner, relay_port = await make_relay_site("node-b", relay_registry)
        try:
            root_registry = _FakeCommandRegistry([
                Node("node-b", "127.0.0.1", relay_port, relation="pc"),
                Node("node-c", "127.0.0.1", 1, relation="pc", metadata={"parent_id": "node-b"}),
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
            Node("node-b", "127.0.0.1", 18000, relation="pc"),
            Node("node-c", "127.0.0.1", 18001, relation="ff", metadata={"parent_id": "node-b"}),
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


def test_change_relation_syncs_remote_before_local_update(monkeypatch):
    async def scenario() -> None:
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        self_id = AppSharedData.Get().instance_uuid
        registry = NodeRegistry(
            shared_data=AppSharedData.Get(),
            namespace="relation-transaction-test",
        )
        await registry.register(
            "node-b",
            "127.0.0.1",
            18000,
            relation="pc",
            metadata={"parent_id": self_id},
        )
        calls: list[dict[str, object]] = []

        async def fake_send_command(node_id: str, req: object) -> dict[str, object]:
            local_node = await registry.get(node_id)
            calls.append({
                "node_id": node_id,
                "command": getattr(req, "command"),
                "local_relation_before_remote_sync": local_node.relation if local_node else None,
                "args": getattr(req, "args"),
            })
            return {"ok": True, "node": {"node_id": self_id}}

        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )
        monkeypatch.setattr(distributed_main, "send_command_to_node", fake_send_command)

        result = await distributed_main.change_node_relation(
            "node-b",
            distributed_main.ChangeNodeRelationRequest(relation="ff"),
        )

        assert result["ok"] is True
        assert len(calls) == 1
        assert calls[0]["command"] == "sync_relation"
        assert calls[0]["local_relation_before_remote_sync"] == "pc"
        synced_args = calls[0]["args"]
        assert isinstance(synced_args, dict)
        assert synced_args["node_id"] == self_id
        assert synced_args["relation"] == "ff"
        assert synced_args["metadata"]["parent_id"] == ""

        updated = await registry.get("node-b")
        assert updated is not None
        assert updated.relation == "ff"
        assert updated.metadata.get("parent_id") == ""

    asyncio.run(scenario())


def test_receive_sync_relation_updates_remote_view(monkeypatch):
    async def scenario() -> None:
        from core.server.routes.distributed import main as distributed_main
        from core.server.shared import AppSharedData

        registry = NodeRegistry(
            shared_data=AppSharedData.Get(),
            namespace="relation-sync-command-test",
        )
        monkeypatch.setattr(
            distributed_main.NodeRegistry,
            "get_instance",
            classmethod(lambda cls: registry),
        )

        result = await distributed_main.receive_command(distributed_main.CommandRequest(
            command="sync_relation",
            args={
                "node_id": "node-a",
                "name": "Node A",
                "host": "127.0.0.1",
                "port": 18001,
                "relation": "pp",
                "gsd_port": 28001,
                "metadata": {"region": "test"},
                "allow_child_api_forward": True,
            },
        ))

        assert result["ok"] is True
        node = await registry.get("node-a")
        assert node is not None
        assert node.name == "Node A"
        assert node.relation == "pp"
        assert node.gsd_port == 28001
        assert node.metadata["region"] == "test"
        assert node.allow_child_api_forward is True

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
        self.assertEqual(r.json()["workers"], 4)
        self.assertFalse(r.json()["restart_requested"])

    async def test_receive_unknown_command(self):
        headers = self._admin_headers()
        r = await self._client.post("/_internal/admin/api/distributed/command", headers=headers, json={
            "command": "fly_to_moon",
            "args": {},
        })
        self.assertEqual(r.status_code, 400)
