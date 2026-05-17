# -*- coding: utf-8 -*-

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app"))

from core.server.app import create_app
from core.server.data_types.apikey import delete_apikey, get_apikey_by_key
from core.server.data_types.config import Config
from core.server.shared import AppSharedData
from core.server.shared_dict import SharedDict


class EclassClassroomWorkspaceTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        import core.server.app as core_app_module

        core_app_module._app = None
        cfg = Config()
        root = Path(__file__).resolve().parent.parent.parent
        cfg.server_config.extra_app_paths = [str(root / "example" / "e-class")]
        cfg.server_config.extra_public_paths = [str(root / "example" / "e-class" / "public")]
        cfg.plugin_configs["webrtc-chatroom"] = {"enabled": True}
        cls.app = create_app(config=cfg)

    async def asyncSetUp(self):
        import httpx

        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")
        self._created_tokens: list[str] = []
        self.shared_dict = SharedDict(AppSharedData.Get(), namespace="EClassRoute")
        for key in [
            "class:c1:chat",
            "class:c1:homework",
            "class:c1:meetings",
            "class:c1:submissions",
            "class:c1:rtc",
        ]:
            self.shared_dict.delete(key)

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

    async def test_teacher_workspace_updates_visible_to_student(self):
        teacher_token = await self._login("teacher1@example.com")
        student_token = await self._login("student1@example.com")

        members_response = await self.client.get(
            "/api/classroom/c1/members",
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(members_response.status_code, 200, members_response.text)

        homework_response = await self.client.post(
            "/api/classroom/c1/workspace",
            json={
                "action": "create_homework",
                "title": "Reading Reflection",
                "description": "Write down the three key arguments.",
                "due_at": "2026-05-18T20:00",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(homework_response.status_code, 200, homework_response.text)
        self.assertTrue(homework_response.json()["ok"])

        meeting_response = await self.client.post(
            "/api/classroom/c1/workspace",
            json={
                "action": "create_meeting",
                "title": "Chapter 4 Seminar",
                "description": "Discuss the reading live in class.",
                "scheduled_at": "2026-05-18T18:30",
                "meeting_mode": "scheduled",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(meeting_response.status_code, 200, meeting_response.text)
        meeting_payload = meeting_response.json()
        self.assertTrue(meeting_payload["ok"])
        meeting_id = meeting_payload["meeting"]["meeting_id"]
        self.assertTrue(meeting_payload["meeting"]["create_token"])

        teacher_workspace = await self.client.get(
            "/api/classroom/c1/workspace",
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(teacher_workspace.status_code, 200)
        teacher_data = teacher_workspace.json()
        self.assertTrue(teacher_data["can_manage"])
        self.assertEqual(len(teacher_data["homework"]), 1)
        self.assertEqual(len(teacher_data["meetings"]), 1)
        self.assertEqual(len(teacher_data["calendar"]), 2)

        self.shared_dict.set("class:c1:submissions", [{
            "submission_id": "student1-reading-reflection",
            "student_id": "student1",
            "class_id": "c1",
            "homework_id": teacher_data["homework"][0]["id"],
            "filename": "reflection.txt",
            "object_name": "homework/c1/hw-1/student1-1710000000-reflection.txt",
            "url": "/api/classroom/c1/files/student1-1710000000-reflection.txt",
            "content_type": "text/plain",
            "size": 128,
            "created_at": "2026-05-18T19:30:00",
            "grade": None,
            "feedback": None,
            "meta": {"size": 128, "content_type": "text/plain"},
        }])

        teacher_workspace = await self.client.get(
            "/api/classroom/c1/workspace",
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(teacher_workspace.status_code, 200)
        teacher_homework = teacher_workspace.json()["homework"][0]
        self.assertEqual(teacher_homework["submission_count"], 1)
        self.assertEqual(len(teacher_homework["submissions"]), 1)
        self.assertEqual(teacher_homework["submissions"][0]["student_name"], "Student One")
        self.assertTrue(teacher_homework["submissions"][0]["url"].endswith("student1-1710000000-reflection.txt"))

        review_response = await self.client.post(
            "/api/classroom/c1/workspace",
            json={
                "action": "review_submission",
                "submission_id": "student1-reading-reflection",
                "grade": "A-",
                "feedback": "Argument two needs more evidence.",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(review_response.status_code, 200, review_response.text)
        review_payload = review_response.json()
        self.assertTrue(review_payload["ok"])
        self.assertEqual(review_payload["submission"]["grade"], "A-")
        self.assertEqual(review_payload["submission"]["feedback"], "Argument two needs more evidence.")

        activate_response = await self.client.post(
            "/api/classroom/c1/workspace",
            json={
                "action": "activate_meeting",
                "meeting_id": meeting_id,
                "room_id": "room-live-001",
                "room_password": "pw-001",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(activate_response.status_code, 200)
        self.assertTrue(activate_response.json()["ok"])

        student_workspace = await self.client.get(
            "/api/classroom/c1/workspace",
            headers=self._bearer(student_token),
        )
        self.assertEqual(student_workspace.status_code, 200)
        student_data = student_workspace.json()
        self.assertFalse(student_data["can_manage"])
        self.assertEqual(student_data["homework"][0]["status"], "graded")
        self.assertEqual(student_data["meetings"][0]["status"], "live")
        self.assertTrue(student_data["meetings"][0]["join_token"])
        self.assertEqual(student_data["homework"][0]["submission"]["filename"], "reflection.txt")
        self.assertEqual(student_data["homework"][0]["submission"]["grade"], "A-")
        self.assertEqual(student_data["homework"][0]["submission"]["feedback"], "Argument two needs more evidence.")
        self.assertTrue(any(item["kind"] == "homework" for item in student_data["calendar"]))
        self.assertTrue(any(item["kind"] == "meeting" for item in student_data["calendar"]))


if __name__ == "__main__":
    unittest.main()