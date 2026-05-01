# -*- coding: utf-8 -*-

import time

from fastapi import FastAPI

from _test_helpers import _StorageTestBase
from core.server.data_types.apikey import create_apikey, delete_apikey
from core.server.routes.admin.permission_role import register_admin_permission_role_routes


class PermissionRoleAdminRouteTestBase(_StorageTestBase):
    @classmethod
    def _register_routes(cls, app: FastAPI):
        register_admin_permission_role_routes(app)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._created_apikey_ids: list[str] = []

    async def asyncTearDown(self):
        for object_id in self._created_apikey_ids:
            try:
                await delete_apikey(object_id)
            except Exception:
                pass
        await super().asyncTearDown()

    def _remember_apikey(self, object_id: str) -> str:
        self._created_apikey_ids.append(object_id)
        return object_id


class TestAdminPermissionRoleCRUD(PermissionRoleAdminRouteTestBase):
    async def test_create_defaults_internal_path_blacklist(self):
        create_resp = await self._client.post(
            "/_internal/admin/permission-roles",
            json={
                "name": f"default_blacklist_{time.time_ns()}",
                "whitelist_routes": "all",
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        created = create_resp.json()
        object_id = created["id"]
        self.assertEqual(created["blacklist_routes"], ["/_internal/*"])

        delete_resp = await self._client.delete(f"/_internal/admin/permission-roles/{object_id}")
        self.assertEqual(delete_resp.status_code, 200)

    async def test_create_list_patch_and_delete(self):
        create_resp = await self._client.post(
            "/_internal/admin/permission-roles",
            json={
                "name": f"reader_{time.time_ns()}",
                "comment": "created via admin api",
                "whitelist_routes": ["/api/read/*"],
                "blacklist_routes": ["/_internal/admin/*"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        created = create_resp.json()
        object_id = created["id"]
        self.assertEqual(created["comment"], "created via admin api")
        self.assertEqual(created["reference_count"], 0)
        self.assertEqual(created["whitelist_routes"], ["/api/read/*"])

        list_resp = await self._client.get("/_internal/admin/permission-roles")
        self.assertEqual(list_resp.status_code, 200)
        self.assertGreaterEqual(list_resp.json()["total"], 1)

        patch_resp = await self._client.patch(
            f"/_internal/admin/permission-roles/{object_id}",
            json={
                "comment": "patched",
                "banned": True,
                "blacklist_routes": ["/_internal/admin/*", "/api/private/*"],
            },
        )
        self.assertEqual(patch_resp.status_code, 200)
        patched = patch_resp.json()
        self.assertEqual(patched["comment"], "patched")
        self.assertTrue(patched["banned"])
        self.assertIn("/api/private/*", patched["blacklist_routes"])

        delete_resp = await self._client.delete(f"/_internal/admin/permission-roles/{object_id}")
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])

    async def test_referenced_role_cannot_delete(self):
        create_resp = await self._client.post(
            "/_internal/admin/permission-roles",
            json={
                "name": f"role_ref_{time.time_ns()}",
                "whitelist_routes": ["/api/role/*"],
                "blacklist_routes": ["/_internal/admin/*"],
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        created = create_resp.json()
        object_id = created["id"]

        api_key = await create_apikey(
            key=f"proj_perm_role_{time.time_ns()}",
            role=created["name"],
            whitelist_routes="all",
            blacklist_routes=[],
        )
        self._remember_apikey(str(api_key.id))

        delete_resp = await self._client.delete(f"/_internal/admin/permission-roles/{object_id}")
        self.assertEqual(delete_resp.status_code, 409)
        self.assertIn("referenced", delete_resp.json()["detail"].lower())