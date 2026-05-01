# -*- coding: utf-8 -*-

import time

from fastapi import FastAPI

from _test_helpers import _StorageTestBase
from core.server.routes.admin.apikey import register_admin_apikey_routes
from core.server.routes.admin.permission_role import register_admin_permission_role_routes
from core.server.data_types.apikey import (
    FixedWindowRateLimit,
    RateLimitConfig,
    SlidingWindowRateLimit,
    create_apikey,
    delete_apikey,
    get_apikey_by_id,
    record_apikey_usage,
    validate_apikey_route,
)


class APIKeyAdminRouteTestBase(_StorageTestBase):
    @classmethod
    def _register_routes(cls, app: FastAPI):
        register_admin_apikey_routes(app)
        register_admin_permission_role_routes(app)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._created_ids: list[str] = []

    async def asyncTearDown(self):
        for object_id in self._created_ids:
            try:
                await delete_apikey(object_id)
            except Exception:
                pass
        await super().asyncTearDown()

    def _remember(self, object_id: str) -> str:
        self._created_ids.append(object_id)
        return object_id


class TestAdminAPIKeyCRUD(APIKeyAdminRouteTestBase):
    async def test_create_list_patch_and_delete(self):
        unique = str(time.time_ns())
        create_resp = await self._client.post(
            "/_internal/admin/apikeys",
            json={
                "key": f"proj_admin_{unique}",
                "name": "Admin Test",
                "comment": "created via admin api",
                "user_id": "teacher_001",
                "credit": 12.5,
                "expire_seconds": 3600,
                "whitelist_routes": ["/api/demo/*"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        created = create_resp.json()
        object_id = self._remember(created["id"])
        self.assertEqual(created["name"], "Admin Test")
        self.assertEqual(created["credit"], 12.5)
        self.assertEqual(created["user_id"], "teacher_001")
        self.assertIsNone(created["role"])
        self.assertEqual(created["whitelist_routes"], ["/api/demo/*"])
        self.assertEqual(created["blacklist_routes"], ["/_internal/*"])
        self.assertEqual(created["ttl_state"], "expiring")
        self.assertIsNotNone(created["expire_at"])
        self.assertGreater(created["ttl_seconds"], 3000)
        self.assertIsNotNone(created["edited_at"])
        self.assertIsNone(created["last_used_at"])

        list_resp = await self._client.get("/_internal/admin/apikeys")
        self.assertEqual(list_resp.status_code, 200)
        self.assertGreaterEqual(list_resp.json()["total"], 1)

        patch_resp = await self._client.patch(
            f"/_internal/admin/apikeys/{object_id}",
            json={
                "comment": "patched",
                "user_id": "teacher_002",
                "banned": True,
                "role": ["reader", "writer"],
                "blacklist_routes": ["/_internal/admin/*", "/api/secret/*"],
            },
        )
        self.assertEqual(patch_resp.status_code, 200)
        patched = patch_resp.json()
        self.assertTrue(patched["banned"])
        self.assertEqual(patched["comment"], "patched")
        self.assertEqual(patched["user_id"], "teacher_002")
        self.assertEqual(patched["role"], ["reader", "writer"])
        self.assertIn("/api/secret/*", patched["blacklist_routes"])

        clear_resp = await self._client.patch(
            f"/_internal/admin/apikeys/{object_id}",
            json={
                "name": None,
                "comment": None,
                "user_id": None,
                "expire_seconds": None,
            },
        )
        self.assertEqual(clear_resp.status_code, 200)
        cleared = clear_resp.json()
        self.assertIsNone(cleared["name"])
        self.assertIsNone(cleared["comment"])
        self.assertIsNone(cleared["user_id"])
        self.assertIsNone(cleared["ttl_seconds"])
        self.assertEqual(cleared["ttl_state"], "persistent")
        self.assertIsNone(cleared["expire_at"])

        get_resp = await self._client.get(f"/_internal/admin/apikeys/{object_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIsNone(get_resp.json()["comment"])

        delete_resp = await self._client.delete(f"/_internal/admin/apikeys/{object_id}")
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])
        self._created_ids.remove(object_id)

        missing_resp = await self._client.get(f"/_internal/admin/apikeys/{object_id}")
        self.assertEqual(missing_resp.status_code, 404)

    async def test_credit_adjust_validate_and_charge(self):
        unique = str(time.time_ns())
        create_resp = await self._client.post(
            "/_internal/admin/apikeys",
            json={
                "key": f"proj_credit_{unique}",
                "credit": 10.0,
                "whitelist_routes": "all",
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        created = create_resp.json()
        object_id = self._remember(created["id"])
        key = created["key"]
        self.assertEqual(created["blacklist_routes"], ["/_internal/*"])

        blocked = await self._client.post(
            "/_internal/admin/apikeys/validate",
            json={"key": key, "route": "/_internal/admin/apikeys", "record_access": False},
        )
        self.assertEqual(blocked.status_code, 403)

        validate_resp = await self._client.post(
            "/_internal/admin/apikeys/validate",
            json={"key": key, "route": "/api/demo/run", "cost": 3.0, "record_access": True},
        )
        self.assertEqual(validate_resp.status_code, 200)
        self.assertTrue(validate_resp.json()["ok"])
        self.assertEqual(validate_resp.json()["remaining_credit"], 7.0)

        credit_resp = await self._client.post(
            f"/_internal/admin/apikeys/{object_id}/credit",
            json={"delta": 2.5},
        )
        self.assertEqual(credit_resp.status_code, 200)
        self.assertEqual(credit_resp.json()["credit"], 12.5)

        charge_resp = await self._client.post(
            f"/_internal/admin/apikeys/{object_id}/charge",
            json={"route": "/api/demo/run", "cost": 4.0},
        )
        self.assertEqual(charge_resp.status_code, 200)
        payload = charge_resp.json()
        self.assertEqual(payload["apikey"]["credit"], 8.5)
        self.assertIsNotNone(payload["apikey"]["last_used_at"])
        self.assertEqual(payload["stats"]["usage_count"], 1)
        self.assertEqual(payload["stats"]["total_cost"], 4.0)

        stats_resp = await self._client.get(f"/_internal/admin/apikeys/{object_id}/stats")
        self.assertEqual(stats_resp.status_code, 200)
        stats_payload = stats_resp.json()
        self.assertEqual(stats_payload["stats"]["access_count"], 1)
        self.assertEqual(stats_payload["stats"]["usage_count"], 1)
        self.assertIn("/api/demo/run", stats_payload["stats"]["routes"])
        access_history = stats_payload["stats"].get("access_history", [])
        credit_history = stats_payload["stats"].get("credit_history", [])
        self.assertGreaterEqual(len(access_history), 1)
        self.assertEqual(access_history[0]["route"], "/api/demo/run")
        history_actions = {entry["action"] for entry in credit_history}
        self.assertIn("delta", history_actions)
        self.assertIn("charge", history_actions)

    async def test_role_control_applies_route_permissions(self):
        role_resp = await self._client.post(
            "/_internal/admin/permission-roles",
            json={
                "name": f"reader_{time.time_ns()}",
                "whitelist_routes": ["/api/role/*"],
                "blacklist_routes": ["/_internal/admin/*"],
            },
        )
        self.assertEqual(role_resp.status_code, 200)
        role_name = role_resp.json()["name"]

        create_resp = await self._client.post(
            "/_internal/admin/apikeys",
            json={
                "key": f"proj_role_{time.time_ns()}",
                "credit": 5.0,
                "role": role_name,
                "whitelist_routes": "all",
                "blacklist_routes": [],
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        created = create_resp.json()
        object_id = self._remember(created["id"])
        api_key = await get_apikey_by_id(object_id)
        assert api_key is not None

        allowed = await validate_apikey_route(api_key, "/api/role/demo", record_access=True)
        self.assertTrue(allowed.ok)

        blocked = await validate_apikey_route(api_key, "/api/other/demo", record_access=True)
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.reason, "route_not_allowed")


class TestAPIKeyLogicFunctions(APIKeyAdminRouteTestBase):
    async def test_route_wildcard_whitelist_and_blacklist_logic(self):
        api_key = await create_apikey(
            key=f"proj_wildcard_{time.time_ns()}",
            credit=5.0,
            whitelist_routes=["/api/demo/*"],
            blacklist_routes=["/_internal/admin/*", "/api/demo/private/*"],
        )
        self._remember(str(api_key.id))

        allowed = await validate_apikey_route(api_key, "/api/demo/run", record_access=True)
        self.assertTrue(allowed.ok)
        self.assertEqual(allowed.reason, "ok")

        blocked_by_blacklist = await validate_apikey_route(api_key, "/api/demo/private/report", record_access=True)
        self.assertFalse(blocked_by_blacklist.ok)
        self.assertEqual(blocked_by_blacklist.reason, "route_not_allowed")

        blocked_by_whitelist = await validate_apikey_route(api_key, "/api/other/run", record_access=True)
        self.assertFalse(blocked_by_whitelist.ok)
        self.assertEqual(blocked_by_whitelist.reason, "route_not_allowed")

    async def test_minimum_interval_limit_and_usage_logic(self):
        api_key = await create_apikey(
            key=f"proj_logic_{time.time_ns()}",
            credit=5.0,
            whitelist_routes="all",
            rate_limit={
                "/api/limited": RateLimitConfig(minimum_interval_seconds=60.0),
            },
        )
        object_id = self._remember(str(api_key.id))

        first = await validate_apikey_route(api_key, "/api/limited", record_access=True)
        self.assertTrue(first.ok)

        second = await validate_apikey_route(api_key, "/api/limited", record_access=True)
        self.assertFalse(second.ok)
        self.assertEqual(second.reason, "minimum_interval")
        self.assertIsNotNone(second.retry_after_seconds)

        snapshot = await record_apikey_usage(api_key, "/api/limited", 1.5)
        self.assertEqual(snapshot.usage_count, 1)
        self.assertEqual(snapshot.total_cost, 1.5)

        fresh = await get_apikey_by_id(object_id)
        self.assertIsNotNone(fresh)
        assert fresh is not None
        self.assertEqual(fresh.credit, 3.5)

    async def test_sliding_window_rate_limit_logic(self):
        api_key = await create_apikey(
            key=f"proj_sliding_{time.time_ns()}",
            credit=5.0,
            whitelist_routes="all",
            rate_limit={
                "/api/sliding/*": RateLimitConfig(
                    limits=[SlidingWindowRateLimit(reset_interval_seconds=60.0, capacity=1)],
                ),
            },
        )
        self._remember(str(api_key.id))

        first = await validate_apikey_route(api_key, "/api/sliding/demo", record_access=True)
        self.assertTrue(first.ok)

        second = await validate_apikey_route(api_key, "/api/sliding/demo", record_access=True)
        self.assertFalse(second.ok)
        self.assertEqual(second.reason, "rate_limited")
        self.assertIsNotNone(second.retry_after_seconds)
        self.assertGreater(second.retry_after_seconds or 0.0, 0.0)

    async def test_fixed_window_rate_limit_logic(self):
        api_key = await create_apikey(
            key=f"proj_fixed_{time.time_ns()}",
            credit=5.0,
            whitelist_routes="all",
            rate_limit={
                "/api/fixed/*": RateLimitConfig(
                    limits=[FixedWindowRateLimit(reset_time={"hour": 0, "minute": 0}, capacity=1)],
                ),
            },
        )
        self._remember(str(api_key.id))

        first = await validate_apikey_route(api_key, "/api/fixed/demo", record_access=True)
        self.assertTrue(first.ok)

        second = await validate_apikey_route(api_key, "/api/fixed/demo", record_access=True)
        self.assertFalse(second.ok)
        self.assertEqual(second.reason, "rate_limited")
        self.assertIsNotNone(second.retry_after_seconds)
        self.assertGreater(second.retry_after_seconds or 0.0, 0.0)