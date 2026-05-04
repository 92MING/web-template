# -*- coding: utf-8 -*-

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from core.server.data_types.apikey import delete_apikey, get_apikey_by_key
from core.storage.base import StorageClientBase
from core.storage.config import (
    KV_StorageConfig,
    LocalKVDBConfig,
    LocalObjectDBConfig,
    ObjectStorageConfig,
    ORMStorageConfig,
    SQLiteORMDBConfig,
    StorageConfig,
)
from core.storage.orm import ORMModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "example" / "e-class" / "api"))

from core.server.app import create_app
from core.server.data_types.config import Config
from teacher_domain import (
    AttendanceActivity,
    AttendanceRecord,
    AuditTrail,
    Homework,
    TeacherDomainRepository,
    TeacherHonor,
    TeacherProfile,
    TeacherProfileChangeRequest,
    TeacherWorkLog,
    TeachingResource,
)


class EclassTeacherFoundationTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import core.server.app as core_app_module

        cls._previous_storage_config = StorageConfig.__Instance__
        cls._previous_storage_env = os.environ.get("__STORAGE_CONFIG__")
        cls._tmp = tempfile.mkdtemp(prefix="eclass_teacher_foundation_")
        root = Path(cls._tmp)
        storage_config = StorageConfig(
            orm=ORMStorageConfig(
                default=SQLiteORMDBConfig(db_path=str(root / "orm.sqlite3"), namespace="eclass-teacher"),
            ),
            kv=KV_StorageConfig(
                default=LocalKVDBConfig(db_path=str(root / "kv.sqlite3"), namespace="eclass-teacher"),
            ),
            object=ObjectStorageConfig(
                default=LocalObjectDBConfig(
                    root_path=str(root / "objects"),
                    metadata_db=LocalKVDBConfig(
                        db_path=str(root / "objects_meta.sqlite3"),
                        namespace="eclass-teacher-objects",
                    ),
                    namespace="eclass-teacher",
                ),
            ),
        )
        StorageConfig.SetGlobal(storage_config)
        StorageClientBase.ClearDefaultInstances()
        ORMModel.ResetClientBindings()

        core_app_module._app = None
        cfg = Config()
        project_root = Path(__file__).resolve().parent.parent.parent
        cfg.server_config.extra_app_paths = [str(project_root / "example" / "e-class")]
        cfg.server_config.extra_public_paths = [str(project_root / "example" / "e-class" / "public")]
        cls.app = create_app(config=cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        StorageClientBase.ClearDefaultInstances()
        ORMModel.ResetClientBindings(include_explicit=True)
        if cls._previous_storage_config is not None:
            StorageConfig.SetGlobal(cls._previous_storage_config)
        else:
            StorageConfig.__Instance__ = None
            if hasattr(StorageConfig, "_StorageConfig__Instance__"):
                delattr(StorageConfig, "_StorageConfig__Instance__")
        if cls._previous_storage_env is None:
            os.environ.pop("__STORAGE_CONFIG__", None)
        else:
            os.environ["__STORAGE_CONFIG__"] = cls._previous_storage_env
        shutil.rmtree(cls._tmp, ignore_errors=True)

    async def asyncSetUp(self) -> None:
        import httpx

        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")
        self._created_tokens: list[str] = []

    async def asyncTearDown(self) -> None:
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

    async def test_teacher_foundation_bootstraps_profile_and_audit(self) -> None:
        token = await self._login("teacher1@example.com")

        response = await self.client.get(
            "/api/teacher/foundation",
            headers=self._bearer(token),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("teacher_profiles", data["data_domain"]["collections"])
        self.assertIn("teacher_audit_trails", data["data_domain"]["collections"])
        self.assertEqual(data["permission_scope"]["teacher_id"], "teacher1")
        self.assertEqual(data["permission_scope"]["owned_class_ids"], ["c1", "c2", "c3"])
        self.assertTrue(data["permission_scope"]["can_edit_self_profile"])
        self.assertEqual(data["profile"]["teacher_id"], "teacher1")
        self.assertGreaterEqual(len(data["audit_trails"]), 1)

        profile = await TeacherProfile.SearchOne({"teacher_id": "teacher1"})
        self.assertIsInstance(profile, TeacherProfile)
        audit = await AuditTrail.SearchOne({"teacher_id": "teacher1", "action": "bootstrap"})
        self.assertIsInstance(audit, AuditTrail)

    async def test_teacher_profile_bootstrap_is_idempotent(self) -> None:
        token = await self._login("teacher1@example.com")

        first = await self.client.get("/api/teacher/foundation", headers=self._bearer(token))
        second = await self.client.get("/api/teacher/foundation", headers=self._bearer(token))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["profile"]["id"], second.json()["profile"]["id"])

        rows = [
            row
            async for row in TeacherProfile.Search({"teacher_id": "teacher1"}, as_model=False)
        ]
        self.assertEqual(len(rows), 1)

    async def test_student_cannot_access_teacher_foundation(self) -> None:
        token = await self._login("student1@example.com")

        response = await self.client.get(
            "/api/teacher/foundation",
            headers=self._bearer(token),
        )

        self.assertEqual(response.status_code, 403)

    async def test_teacher_record_permission_helper(self) -> None:
        repo = TeacherDomainRepository()
        user = {"user_id": "teacher1", "role": "teacher"}

        self.assertTrue(repo.teacher_can_access_teacher_record(user=user, teacher_id="teacher1"))
        self.assertFalse(repo.teacher_can_access_teacher_record(user=user, teacher_id="teacher2"))

    async def test_teacher_profile_schema_and_masked_view(self) -> None:
        token = await self._login("teacher1@example.com")
        change_payload = {
            "changes": {
                "基础信息": {
                    "个人信息": {
                        "姓名": "Teacher One",
                        "证件号": "110101199001011234",
                        "联系电话": "13800138000",
                        "所在学校": "school1",
                    },
                },
            },
            "reason": "补充基础信息",
        }

        schema_response = await self.client.get(
            "/api/teacher/profile",
            params={"action": "schema"},
            headers=self._bearer(token),
        )
        self.assertEqual(schema_response.status_code, 200)
        schema_tabs = [item["tab"] for item in schema_response.json()["schema"]]
        self.assertIn("基础信息", schema_tabs)
        self.assertIn("职务职称", schema_tabs)

        submit_response = await self.client.post(
            "/api/teacher/profile",
            params={"action": "submit_change"},
            json=change_payload,
            headers=self._bearer(token),
        )
        self.assertEqual(submit_response.status_code, 200)
        self.assertTrue(submit_response.json()["ok"])

        auditor_token = await self._login("auditor1@example.com")
        change_id = submit_response.json()["change"]["id"]
        approve_response = await self.client.post(
            "/api/teacher/profile",
            params={"action": "approve_change"},
            json={"change_id": change_id, "review_reason": "材料齐全"},
            headers=self._bearer(auditor_token),
        )
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["change"]["status"], "approved")

        masked_response = await self.client.get(
            "/api/teacher/profile",
            params={"action": "me", "view": "masked"},
            headers=self._bearer(token),
        )
        self.assertEqual(masked_response.status_code, 200)
        fields = masked_response.json()["profile"]["field_groups"]["基础信息"]["个人信息"]
        self.assertEqual(fields["姓名"], "Teacher One")
        self.assertNotEqual(fields["证件号"], "110101199001011234")
        self.assertIn("*", fields["联系电话"])

        change = await TeacherProfileChangeRequest.SearchOneById(change_id)
        self.assertIsInstance(change, TeacherProfileChangeRequest)
        assert isinstance(change, TeacherProfileChangeRequest)
        self.assertEqual(change.status, "approved")

    async def test_teacher_profile_change_validation_and_reject_reason(self) -> None:
        token = await self._login("teacher1@example.com")

        invalid_response = await self.client.post(
            "/api/teacher/profile",
            params={"action": "submit_change"},
            json={
                "changes": {
                    "基础信息": {
                        "个人信息": {
                            "姓名": "Teacher One",
                            "联系电话": "not-a-phone",
                            "所在学校": "school1",
                        },
                    },
                },
                "reason": "联系电话格式错误",
            },
            headers=self._bearer(token),
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertFalse(invalid_response.json()["ok"])
        self.assertEqual(invalid_response.json()["validation_errors"][0]["field"], "联系电话")

        valid_response = await self.client.post(
            "/api/teacher/profile",
            params={"action": "submit_change"},
            json={
                "changes": {
                    "基础信息": {
                        "个人信息": {
                            "姓名": "Teacher One",
                            "联系电话": "13900139000",
                            "所在学校": "school1",
                        },
                    },
                },
                "reason": "更新联系电话",
            },
            headers=self._bearer(token),
        )
        self.assertEqual(valid_response.status_code, 200)
        change_id = valid_response.json()["change"]["id"]

        auditor_token = await self._login("auditor1@example.com")
        reject_without_reason = await self.client.post(
            "/api/teacher/profile",
            params={"action": "reject_change"},
            json={"change_id": change_id, "review_reason": ""},
            headers=self._bearer(auditor_token),
        )
        self.assertEqual(reject_without_reason.status_code, 200)
        self.assertFalse(reject_without_reason.json()["ok"])

        reject_response = await self.client.post(
            "/api/teacher/profile",
            params={"action": "reject_change"},
            json={"change_id": change_id, "review_reason": "证明材料不完整"},
            headers=self._bearer(auditor_token),
        )
        self.assertEqual(reject_response.status_code, 200)
        self.assertEqual(reject_response.json()["change"]["status"], "rejected")

    async def test_teacher_homework_publishes_to_class_or_students(self) -> None:
        teacher_token = await self._login("teacher1@example.com")
        student_token = await self._login("student1@example.com")
        student2_token = await self._login("student2@example.com")

        response = await self.client.post(
            "/api/teacher/homework",
            json={
                "class_ids": ["c2"],
                "student_ids": ["student1"],
                "title": "Formal targeted homework",
                "description": "Only student1 can see this",
                "due_at": "2026-05-06T10:00",
                "attachments": [{"name": "homework.pdf", "url": "/files/homework.pdf"}],
                "answer_files": [{"name": "answer.pdf", "url": "/files/answer.pdf"}],
                "answer_visible_to_students": False,
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        homework_id = response.json()["homework"]["id"]

        stored = await Homework.SearchOneById(homework_id)
        self.assertIsInstance(stored, Homework)
        assert isinstance(stored, Homework)
        self.assertEqual(stored.class_ids, ["c2"])
        self.assertEqual(stored.student_ids, ["student1"])
        self.assertFalse(bool(stored.answer_files[0]["visible_to_students"]))

        visible_response = await self.client.get(
            "/api/student/homework/list",
            params={"class_id": "c2", "student_id": "student1"},
            headers=self._bearer(student_token),
        )
        self.assertEqual(visible_response.status_code, 200)
        visible_titles = [item["title"] for item in visible_response.json()["homework"]]
        self.assertIn("Formal targeted homework", visible_titles)

        hidden_response = await self.client.get(
            "/api/student/homework/list",
            params={"class_id": "c2", "student_id": "student2"},
            headers=self._bearer(student2_token),
        )
        self.assertEqual(hidden_response.status_code, 200)
        hidden_titles = [item["title"] for item in hidden_response.json()["homework"]]
        self.assertNotIn("Formal targeted homework", hidden_titles)

    async def test_teacher_homework_grade_preview_reports_row_errors(self) -> None:
        teacher_token = await self._login("teacher1@example.com")

        response = await self.client.post(
            "/api/teacher/homework",
            params={"action": "preview_grades"},
            json={
                "homework_id": "hw-preview",
                "rows": [
                    {"student_id": "student1", "score": 96, "comment": "Good"},
                    {"student_id": "", "score": 82},
                    {"student_id": "student2", "score": "bad"},
                    {"student_id": "student3", "score": 130},
                ],
            },
            headers=self._bearer(teacher_token),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertFalse(data["will_write"])
        self.assertEqual(len(data["valid_rows"]), 1)
        self.assertEqual([item["row"] for item in data["errors"]], [2, 3, 4])

    async def test_teacher_attendance_lifecycle_records_student_and_stats(self) -> None:
        teacher_token = await self._login("teacher1@example.com")
        student_token = await self._login("student1@example.com")

        create_response = await self.client.post(
            "/api/teacher/check-in",
            json={
                "class_id": "c1",
                "course_id": "course-1",
                "attendance_date": "2026-05-03",
                "attendance_type": "lesson",
                "expires_minutes": 30,
                "allow_makeup": True,
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(create_response.status_code, 200)
        activity = create_response.json()["activity"]
        check_in_id = activity["check_in_id"]
        self.assertEqual(activity["course_id"], "course-1")
        self.assertEqual(activity["attendance_date"], "2026-05-03")
        self.assertTrue(activity["allow_makeup"])

        stored_activity = await AttendanceActivity.SearchOneById(check_in_id)
        self.assertIsInstance(stored_activity, AttendanceActivity)
        assert isinstance(stored_activity, AttendanceActivity)
        self.assertEqual(stored_activity.class_id, "c1")
        self.assertEqual(stored_activity.course_id, "course-1")
        self.assertTrue(stored_activity.allow_makeup)

        check_in_response = await self.client.post(
            "/api/student/check_in",
            json={"check_in_id": check_in_id, "class_id": "c1"},
            headers=self._bearer(student_token),
        )
        self.assertEqual(check_in_response.status_code, 200)
        self.assertTrue(check_in_response.json()["ok"])

        stored_record = await AttendanceRecord.SearchOne({
            "activity_id": check_in_id,
            "student_id": "student1",
        })
        self.assertIsInstance(stored_record, AttendanceRecord)
        assert isinstance(stored_record, AttendanceRecord)
        self.assertEqual(stored_record.status, "present")

        stats_response = await self.client.get(
            f"/api/teacher/check-in/{check_in_id}",
            params={"class_id": "c1"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(stats_response.status_code, 200)
        stats = stats_response.json()["stats"]
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["status_counts"]["present"], 1)
        self.assertEqual(stats["status_counts"]["absent"], 1)
        self.assertEqual(stats["present_list"][0]["user_id"], "student1")
        self.assertEqual(stats["absent_list"][0]["user_id"], "student2")

        close_response = await self.client.post(
            "/api/teacher/check-in",
            params={"action": "close"},
            json={"check_in_id": check_in_id, "class_id": "c1"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(close_response.status_code, 200)
        self.assertEqual(close_response.json()["activity"]["status"], "closed")

    async def test_leader_attendance_summary_is_aggregate_only(self) -> None:
        teacher_token = await self._login("teacher1@example.com")
        student_token = await self._login("student1@example.com")
        leader_token = await self._login("leader1@example.com")

        create_response = await self.client.post(
            "/api/teacher/check-in",
            json={
                "class_id": "c1",
                "course_id": "course-1",
                "attendance_date": "2026-05-03",
                "attendance_type": "lesson",
                "expires_minutes": 30,
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(create_response.status_code, 200)
        check_in_id = create_response.json()["activity"]["check_in_id"]

        check_in_response = await self.client.post(
            "/api/student/check_in",
            json={"check_in_id": check_in_id, "class_id": "c1"},
            headers=self._bearer(student_token),
        )
        self.assertEqual(check_in_response.status_code, 200)

        summary_response = await self.client.get(
            "/api/leader/attendance/summary",
            params={"class_id": "c1"},
            headers=self._bearer(leader_token),
        )
        self.assertEqual(summary_response.status_code, 200)
        summary = summary_response.json()["summary"]
        self.assertEqual(summary["class_id"], "c1")
        self.assertEqual(summary["total_activities"], 1)
        self.assertEqual(summary["total_students"], 2)
        self.assertEqual(summary["present"], 1)
        self.assertEqual(summary["absent"], 1)
        self.assertEqual(summary["attendance_rate"], 0.5)
        self.assertNotIn("present_list", summary)

    async def test_teacher_resource_lifecycle_tags_rich_text_and_stats(self) -> None:
        teacher_token = await self._login("teacher1@example.com")

        create_response = await self.client.post(
            "/api/teacher/resources",
            json={
                "title": "函数单调性课件",
                "description": "高一数学课件",
                "resource_type": "courseware",
                "class_ids": ["c1"],
                "visibility": "school",
                "file_refs": [{"name": "lesson.pdf", "object_name": "resources/lesson.pdf"}],
                "tags": {
                    "学段": "高中",
                    "学科": "数学",
                    "年级": "高一",
                    "版本": "人教A版",
                    "章节": "函数",
                },
                "version": "v1",
                "course_objectives_html": "<p>理解函数单调性</p>",
                "course_content_html": "<p>例题与练习</p>",
                "evaluation_method_html": "<p>课堂练习评价</p>",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(create_response.status_code, 200)
        resource = create_response.json()["resource"]
        resource_id = resource["id"]
        self.assertEqual(resource["tags"]["学科"], "数学")

        stored = await TeachingResource.SearchOneById(resource_id)
        self.assertIsInstance(stored, TeachingResource)
        assert isinstance(stored, TeachingResource)
        self.assertEqual(stored.visibility, "school")
        self.assertEqual(stored.course_objectives_html, "<p>理解函数单调性</p>")

        list_response = await self.client.get(
            "/api/teacher/resources",
            params={"subject": "数学", "grade": "高一", "chapter": "函数"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([item["id"] for item in list_response.json()["items"]], [resource_id])

        update_response = await self.client.post(
            "/api/teacher/resources",
            params={"action": "update"},
            json={
                "resource_id": resource_id,
                "title": "函数单调性课件-修订",
                "tags": {"学段": "高中", "学科": "数学", "年级": "高一", "版本": "人教A版", "章节": "函数与导数"},
                "course_objectives_html": "<p>理解并应用函数单调性</p>",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["resource"]["title"], "函数单调性课件-修订")
        self.assertEqual(update_response.json()["resource"]["tags"]["章节"], "函数与导数")

        stat_response = await self.client.post(
            "/api/teacher/resources",
            params={"action": "record_stat"},
            json={"resource_id": resource_id, "metric": "download"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(stat_response.status_code, 200)
        self.assertEqual(stat_response.json()["resource"]["stats"]["download_count"], 1)

        delete_response = await self.client.post(
            "/api/teacher/resources",
            params={"action": "delete"},
            json={"resource_id": resource_id},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["resource"]["status"], "deleted")

        deleted = await TeachingResource.SearchOneById(resource_id)
        self.assertIsInstance(deleted, TeachingResource)
        assert isinstance(deleted, TeachingResource)
        self.assertEqual(deleted.status, "deleted")

        hidden_response = await self.client.get(
            "/api/teacher/resources",
            params={"subject": "数学"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(hidden_response.status_code, 200)
        self.assertEqual(hidden_response.json()["items"], [])

    async def test_teacher_material_upload_creates_formal_resource(self) -> None:
        teacher_token = await self._login("teacher1@example.com")

        response = await self.client.post(
            "/api/teacher/materials/upload",
            data={"class_id": "c2", "title": "Shared material formalized"},
            files={"file": ("shared-material.txt", b"material body", "text/plain")},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(response.status_code, 200)
        material = response.json()["material"]
        self.assertIn("resource_id", material)

        resource = await TeachingResource.SearchOneById(material["resource_id"])
        self.assertIsInstance(resource, TeachingResource)
        assert isinstance(resource, TeachingResource)
        self.assertEqual(resource.title, "Shared material formalized")
        self.assertEqual(resource.class_ids, ["c2"])
        self.assertEqual(resource.visibility, "class")

    async def test_teacher_work_log_crud_month_stats_and_export(self) -> None:
        teacher_token = await self._login("teacher1@example.com")

        create_response = await self.client.post(
            "/api/teacher/work-logs",
            json={
                "log_date": "2026-05-03",
                "log_type": "teaching",
                "title": "高一数学课堂记录",
                "content": "完成函数单调性教学并布置练习。",
                "class_ids": ["c1"],
                "course_ids": ["course-1"],
                "resource_ids": ["resource-1"],
                "homework_ids": ["homework-1"],
                "attachments": [{"name": "课堂照片.jpg", "object_name": "logs/photo.jpg"}],
                "status": "draft",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(create_response.status_code, 200)
        log = create_response.json()["work_log"]
        log_id = log["id"]
        self.assertEqual(log["resource_ids"], ["resource-1"])
        self.assertEqual(log["homework_ids"], ["homework-1"])

        second_response = await self.client.post(
            "/api/teacher/work-logs",
            json={
                "log_date": "2026-04-20",
                "log_type": "training",
                "title": "校本培训",
                "content": "参加培训。",
                "class_ids": [],
                "course_ids": [],
                "status": "published",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(second_response.status_code, 200)

        stored = await TeacherWorkLog.SearchOneById(log_id)
        self.assertIsInstance(stored, TeacherWorkLog)
        assert isinstance(stored, TeacherWorkLog)
        self.assertEqual(stored.log_type, "teaching")
        self.assertEqual(stored.class_ids, ["c1"])

        may_response = await self.client.get(
            "/api/teacher/work-logs",
            params={"month": "2026-05"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(may_response.status_code, 200)
        self.assertEqual([item["id"] for item in may_response.json()["items"]], [log_id])

        update_response = await self.client.post(
            "/api/teacher/work-logs",
            params={"action": "update"},
            json={
                "work_log_id": log_id,
                "title": "高一数学课堂记录-已复盘",
                "status": "published",
                "content": "补充课后反思。",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["work_log"]["status"], "published")
        self.assertEqual(update_response.json()["work_log"]["title"], "高一数学课堂记录-已复盘")

        stats_response = await self.client.get(
            "/api/teacher/work-logs",
            params={"action": "stats", "month": "2026-05"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(stats_response.status_code, 200)
        stats = stats_response.json()["stats"]
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["by_type"]["teaching"], 1)
        self.assertEqual(stats["by_month"]["2026-05"], 1)
        self.assertEqual(stats["by_class"]["c1"], 1)

        export_response = await self.client.get(
            "/api/teacher/work-logs",
            params={"action": "export", "month": "2026-05"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(export_response.status_code, 200)
        rows = export_response.json()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["log_date"], "2026-05-03")
        self.assertEqual(rows[0]["title"], "高一数学课堂记录-已复盘")
        self.assertEqual(rows[0]["class_ids"], "c1")

        delete_response = await self.client.post(
            "/api/teacher/work-logs",
            params={"action": "delete"},
            json={"work_log_id": log_id},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["work_log"]["status"], "deleted")

        hidden_response = await self.client.get(
            "/api/teacher/work-logs",
            params={"month": "2026-05"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(hidden_response.status_code, 200)
        self.assertEqual(hidden_response.json()["items"], [])

    async def test_teacher_honor_lifecycle_review_share_stats_and_reminders(self) -> None:
        teacher_token = await self._login("teacher1@example.com")
        auditor_token = await self._login("auditor1@example.com")

        schema_response = await self.client.get(
            "/api/teacher/honors",
            params={"action": "schema"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(schema_response.status_code, 200)
        self.assertIn("教学获奖", schema_response.json()["categories"])
        self.assertIn("授予单位", schema_response.json()["tag_dimensions"])

        create_response = await self.client.post(
            "/api/teacher/honors",
            json={
                "title": "市级优质课一等奖",
                "category": "教学获奖",
                "level": "市级",
                "granted_by": "咸宁市教育局",
                "granted_at": "2026-04-20",
                "tags": {
                    "级别": "市级",
                    "学段": "高中",
                    "学科": "数学",
                    "年份": "2026",
                    "授予单位": "咸宁市教育局",
                    "证明材料类型": "获奖证书",
                },
                "attachments": [{"name": "certificate.pdf", "object_name": "honors/certificate.pdf"}],
                "ocr_fields": {"text": "市级优质课一等奖 咸宁市教育局"},
                "ai_fields": {"title": "市级优质课一等奖", "level": "市级", "source": "ai_suggestion"},
                "reminder_due_at": "2026-05-20",
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(create_response.status_code, 200)
        honor = create_response.json()["honor"]
        honor_id = honor["id"]
        self.assertEqual(honor["status"], "draft")
        self.assertEqual(honor["tags"]["学科"], "数学")
        self.assertEqual(honor["ai_fields"]["source"], "ai_suggestion")

        stored = await TeacherHonor.SearchOneById(honor_id)
        self.assertIsInstance(stored, TeacherHonor)
        assert isinstance(stored, TeacherHonor)
        self.assertEqual(stored.category, "教学获奖")
        self.assertEqual(stored.attachments[0]["name"], "certificate.pdf")

        preview_response = await self.client.get(
            "/api/teacher/honors",
            params={"action": "preview", "honor_id": honor_id},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.json()["preview"]["attachments"][0]["name"], "certificate.pdf")
        self.assertEqual(preview_response.json()["preview"]["ai_fields"]["source"], "ai_suggestion")

        submit_response = await self.client.post(
            "/api/teacher/honors",
            params={"action": "submit"},
            json={"honor_id": honor_id},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(submit_response.json()["honor"]["status"], "pending")

        pending_update = await self.client.post(
            "/api/teacher/honors",
            params={"action": "update"},
            json={"honor_id": honor_id, "title": "待审中不应修改"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(pending_update.status_code, 400)

        reject_without_reason = await self.client.post(
            "/api/teacher/honors",
            params={"action": "reject"},
            json={"honor_id": honor_id, "review_reason": ""},
            headers=self._bearer(auditor_token),
        )
        self.assertEqual(reject_without_reason.status_code, 200)
        self.assertFalse(reject_without_reason.json()["ok"])

        reject_response = await self.client.post(
            "/api/teacher/honors",
            params={"action": "reject"},
            json={"honor_id": honor_id, "review_reason": "证书编号不清晰"},
            headers=self._bearer(auditor_token),
        )
        self.assertEqual(reject_response.status_code, 200)
        self.assertEqual(reject_response.json()["honor"]["status"], "rejected")

        resubmit_response = await self.client.post(
            "/api/teacher/honors",
            params={"action": "submit"},
            json={"honor_id": honor_id},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(resubmit_response.status_code, 200)
        self.assertEqual(resubmit_response.json()["honor"]["status"], "pending")

        approve_response = await self.client.post(
            "/api/teacher/honors",
            params={"action": "approve"},
            json={"honor_id": honor_id, "review_reason": "材料完整"},
            headers=self._bearer(auditor_token),
        )
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["honor"]["status"], "approved")
        self.assertEqual(approve_response.json()["honor"]["review_reason"], "材料完整")

        share_response = await self.client.post(
            "/api/teacher/honors",
            params={"action": "share"},
            json={"honor_id": honor_id, "visibility": "school"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(share_response.status_code, 200)
        self.assertEqual(share_response.json()["honor"]["visibility"], "school")

        stat_response = await self.client.post(
            "/api/teacher/honors",
            params={"action": "record_stat"},
            json={"honor_id": honor_id, "metric": "preview"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(stat_response.status_code, 200)
        self.assertEqual(stat_response.json()["honor"]["stats"]["preview_count"], 1)

        stats_response = await self.client.get(
            "/api/teacher/honors",
            params={"action": "stats"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(stats_response.status_code, 200)
        stats = stats_response.json()["stats"]
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["by_category"]["教学获奖"], 1)
        self.assertEqual(stats["by_status"]["approved"], 1)

        reminders_response = await self.client.get(
            "/api/teacher/honors",
            params={"action": "reminders"},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(reminders_response.status_code, 200)
        self.assertEqual(reminders_response.json()["reminders"][0]["honor_id"], honor_id)

    async def test_teacher_honor_submit_and_withdraw(self) -> None:
        teacher_token = await self._login("teacher1@example.com")

        create_response = await self.client.post(
            "/api/teacher/honors",
            json={
                "title": "优秀班主任",
                "category": "综合荣誉",
                "level": "校级",
                "granted_by": "学校",
                "granted_at": "2026-03-01",
                "tags": {"级别": "校级", "年份": "2026", "授予单位": "学校"},
            },
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(create_response.status_code, 200)
        honor_id = create_response.json()["honor"]["id"]

        submit_response = await self.client.post(
            "/api/teacher/honors",
            params={"action": "submit"},
            json={"honor_id": honor_id},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(submit_response.json()["honor"]["status"], "pending")

        withdraw_response = await self.client.post(
            "/api/teacher/honors",
            params={"action": "withdraw"},
            json={"honor_id": honor_id},
            headers=self._bearer(teacher_token),
        )
        self.assertEqual(withdraw_response.status_code, 200)
        self.assertEqual(withdraw_response.json()["honor"]["status"], "withdrawn")


if __name__ == "__main__":
    unittest.main()
