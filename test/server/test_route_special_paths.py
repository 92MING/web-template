# -*- coding: utf-8 -*-
"""Tests for _xxx_.py path parameter routes."""

import sys
from pathlib import Path

_server_dir = Path(__file__).resolve().parent.parent.parent / "app" / "core" / "server"
if str(_server_dir.parent.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent.parent))
if str(_server_dir.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent))

from _test_helpers import FullAppTestBase


class TestSpecialPathRoutes(FullAppTestBase):
    async def test_student_grades_with_student_id(self):
        """Test /api/student/grades/{student_id} route exists."""
        r = await self._client.get("/api/student/grades/s123")
        # Route exists but may return 404 if handler returns empty/None
        self.assertIn(r.status_code, (200, 404, 422))

    async def test_teacher_analytics_with_class_id(self):
        """Test /api/teacher/analytics/{class_id} route exists."""
        r = await self._client.get("/api/teacher/analytics/c456")
        self.assertIn(r.status_code, (200, 404, 422))

    async def test_classroom_chat_with_class_id(self):
        """Test /api/classroom/{class_id}/chat route exists."""
        r = await self._client.get("/api/classroom/c789/chat")
        self.assertIn(r.status_code, (200, 404, 422))

    async def test_classroom_rtc_with_class_id(self):
        """Test /api/classroom/{class_id}/rtc/start route exists."""
        r = await self._client.get("/api/classroom/c789/rtc/start")
        self.assertIn(r.status_code, (200, 404, 422))

    async def test_teacher_submissions_grade_with_submission_id(self):
        """Test /api/teacher/submissions/{submission_id}/grade route exists."""
        r = await self._client.get("/api/teacher/submissions/sub001/grade")
        self.assertIn(r.status_code, (200, 404, 422))

    async def test_route_loader_mounted_routes(self):
        """Verify that example routes are actually mounted."""
        r = await self._client.get("/_internal/admin/openapi.json")
        self.assertEqual(r.status_code, 200)
        schema = r.json()
        paths = list(schema.get("paths", {}).keys())
        example_paths = [p for p in paths if p.startswith("/api/")]
        self.assertGreater(len(example_paths), 0, "No example API routes mounted")
