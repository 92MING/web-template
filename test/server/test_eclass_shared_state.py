# -*- coding: utf-8 -*-

import sys
from pathlib import Path
import unittest

from core.server.data_types.apikey import delete_apikey, get_apikey_by_key, get_apikey_expire_seconds

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app"))

from core.server.app import create_app
from core.server.data_types.config import Config


class EclassSharedStateTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        import core.server.app as core_app_module

        core_app_module._app = None
        cfg = Config()
        root = Path(__file__).resolve().parent.parent.parent
        cfg.server_config.extra_app_paths = [str(root / "example" / "e-class")]
        cfg.server_config.extra_public_paths = [str(root / "example" / "e-class" / "public")]
        cls.app = create_app(config=cfg)

    async def asyncSetUp(self):
        import httpx

        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")
        self._created_tokens: list[str] = []

    async def asyncTearDown(self):
        for token in self._created_tokens:
            api_key = await get_apikey_by_key(token)
            if api_key is not None:
                await delete_apikey(str(getattr(api_key, "id", "") or ""))
        await self.client.aclose()

    async def _login(self, email: str, password: str = "123456") -> str:
        response = await self.client.post(
            "/api/auth?action=login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        token = data["token"]
        self._created_tokens.append(token)
        return token

    def _bearer(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def test_teacher_material_upload_visible_to_student_materials_route(self):
        teacher_token = await self._login("teacher1@example.com")
        student_token = await self._login("student1@example.com")

        response = await self.client.post(
            "/api/teacher/materials/upload",
            data={"class_id": "c1", "title": "Shared material"},
            files={"file": ("shared-material.txt", b"material body", "text/plain")},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(response.status_code, 200)

        response = await self.client.get(
            "/api/student/materials",
            params={"class_id": "c1"},
            headers=self._bearer(student_token),
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Shared material")
        self.assertEqual(items[0]["filename"], "shared-material.txt")

    async def test_teacher_announcements_visible_in_student_list_route(self):
        teacher_token = await self._login("teacher1@example.com")
        student_token = await self._login("student1@example.com")

        response = await self.client.post(
            "/api/teacher/announcements",
            json={"class_id": "c1", "title": "Shared notice", "body": "Notice body"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(response.status_code, 200)

        response = await self.client.get(
            "/api/student/announcements/list",
            params={"class_id": "c1", "page": 1, "page_size": 10},
            headers=self._bearer(student_token),
        )
        self.assertEqual(response.status_code, 200)
        announcements = response.json()["announcements"]
        self.assertEqual(len(announcements), 1)
        self.assertEqual(announcements[0]["title"], "Shared notice")
        self.assertEqual(announcements[0]["content"], "Notice body")
        self.assertEqual(announcements[0]["date"], response.json()["announcements"][0]["date"])

    async def test_teacher_homework_visible_in_student_homework_list(self):
        teacher_token = await self._login("teacher1@example.com")
        student_token = await self._login("student1@example.com")

        response = await self.client.post(
            "/api/teacher/homework",
            json={
                "class_id": "c1",
                "title": "Shared homework",
                "description": "Homework body",
                "due_at": "2026-05-05T10:00",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(response.status_code, 200)

        response = await self.client.get(
            "/api/student/homework/list",
            params={"class_id": "c1", "student_id": "student1@example.com"},
            headers=self._bearer(student_token),
        )
        self.assertEqual(response.status_code, 200)
        homework = response.json()["homework"]
        self.assertEqual(len(homework), 1)
        self.assertEqual(homework[0]["title"], "Shared homework")
        self.assertEqual(homework[0]["due_date"], "2026-05-05T10:00")
        self.assertEqual(homework[0]["status"], "pending")

    async def test_classroom_chat_keeps_text_from_json_payload(self):
        token = await self._login("teacher1@example.com")

        response = await self.client.post(
            "/api/classroom/c1/chat",
            json={"text": "Shared chat body"},
            headers=self._bearer(token),
        )
        self.assertEqual(response.status_code, 200)
        message = response.json()["message"]
        self.assertEqual(message["text"], "Shared chat body")

        response = await self.client.get(
            "/api/classroom/c1/chat",
            headers=self._bearer(token),
        )
        self.assertEqual(response.status_code, 200)
        messages = response.json()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["text"], "Shared chat body")

    async def test_login_returns_real_apikey_with_user_id_and_ttl(self):
        token = await self._login("teacher1@example.com")

        stored = await get_apikey_by_key(token)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.user_id, "teacher1")
        self.assertEqual(stored.role, ["teacher"])

        ttl_seconds = await get_apikey_expire_seconds(stored)
        self.assertIsNotNone(ttl_seconds)
        assert ttl_seconds is not None
        self.assertGreater(ttl_seconds, 86000)

        me_response = await self.client.get(
            "/api/auth?action=me",
            headers=self._bearer(token),
        )
        self.assertEqual(me_response.status_code, 200)
        me_data = me_response.json()
        self.assertTrue(me_data["ok"])
        self.assertEqual(me_data["user"]["user_id"], "teacher1")

    async def test_teacher_and_student_prefix_permissions_are_enforced(self):
        teacher_token = await self._login("teacher1@example.com")
        student_token = await self._login("student1@example.com")

        teacher_allowed = await self.client.get(
            "/api/teacher/students",
            params={"class_id": "c1"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(teacher_allowed.status_code, 200)

        teacher_denied = await self.client.get(
            "/api/student/grades",
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(teacher_denied.status_code, 403)

        student_allowed = await self.client.get(
            "/api/student/grades",
            headers=self._bearer(student_token),
        )
        self.assertEqual(student_allowed.status_code, 200)

        student_denied = await self.client.post(
            "/api/teacher/materials/upload",
            data={"class_id": "c1", "title": "forbidden"},
            files={"file": ("forbidden.txt", b"body", "text/plain")},
            headers=self._bearer(student_token),
        )
        self.assertEqual(student_denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()