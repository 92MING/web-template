# -*- coding: utf-8 -*-
"""Shared helpers for the e-class example APIs."""

import hashlib
from typing import Any

from fastapi import Request

from core.server import AdvanceRequest, Route
from core.server.data_types.apikey import get_apikey_by_key
from core.server.data_types.role import create_permission_role, get_permission_role_by_name, update_permission_role
from core.server.shared_dict import SharedDict

STUDENT_ROLE_NAME = "student"
TEACHER_ROLE_NAME = "teacher"
SCHOOL_ADMIN_ROLE_NAME = "school_admin"
LEADER_ROLE_NAME = "leader"
AUDITOR_ROLE_NAME = "auditor"

__all__ = [
    "EClassRoute",
    "STUDENT_ROLE_NAME",
    "TEACHER_ROLE_NAME",
    "SCHOOL_ADMIN_ROLE_NAME",
    "LEADER_ROLE_NAME",
    "AUDITOR_ROLE_NAME",
]


class EClassRoute(Route):
    Abstract = True
    ApikeyProtected = True

    @property
    def shared_dict(self) -> SharedDict:
        return SharedDict(self.shared_data, namespace="EClassRoute")

    def _init_data(self) -> None:
        schools = self.shared_data.get_shared_dict_value("eclass", "schools")
        if not schools:
            self.shared_data.set_shared_dict_value("eclass", "schools", {
                "school1": {"id": "school1", "name": "示例学校"},
            })

        users = self.shared_data.get_shared_dict_value("eclass", "users")
        if not users:
            self.shared_data.set_shared_dict_value("eclass", "users", {
                "student1": {
                    "user_id": "student1",
                    "email": "student1@example.com",
                    "nickname": "Student One",
                    "name": "Student One",
                    "role": STUDENT_ROLE_NAME,
                    "school_id": "school1",
                    "grade": "高一",
                    "password_hash": self._hash("123456"),
                },
                "student2": {
                    "user_id": "student2",
                    "email": "student2@example.com",
                    "nickname": "Student Two",
                    "name": "Student Two",
                    "role": STUDENT_ROLE_NAME,
                    "school_id": "school1",
                    "grade": "高二",
                    "password_hash": self._hash("123456"),
                },
                "teacher1": {
                    "user_id": "teacher1",
                    "email": "teacher1@example.com",
                    "nickname": "Teacher One",
                    "name": "Teacher One",
                    "role": TEACHER_ROLE_NAME,
                    "school_id": "school1",
                    "grade": "",
                    "password_hash": self._hash("123456"),
                },
                "auditor1": {
                    "user_id": "auditor1",
                    "email": "auditor1@example.com",
                    "nickname": "Auditor One",
                    "name": "Auditor One",
                    "role": AUDITOR_ROLE_NAME,
                    "school_id": "school1",
                    "grade": "",
                    "password_hash": self._hash("123456"),
                },
                "leader1": {
                    "user_id": "leader1",
                    "email": "leader1@example.com",
                    "nickname": "Leader One",
                    "name": "Leader One",
                    "role": LEADER_ROLE_NAME,
                    "school_id": "school1",
                    "grade": "",
                    "password_hash": self._hash("123456"),
                },
            })

        classrooms = self.shared_data.get_shared_dict_value("eclass", "classrooms")
        if classrooms is None:
            self.shared_data.set_shared_dict_value("eclass", "classrooms", {
                "c1": {
                    "id": "c1",
                    "name": "数学课 Class 1",
                    "school_id": "school1",
                    "teacher_id": "teacher1",
                    "members": ["student1", "student2"],
                },
                "c2": {
                    "id": "c2",
                    "name": "英语课 Class 2",
                    "school_id": "school1",
                    "teacher_id": "teacher1",
                    "members": ["student1"],
                },
                "c3": {
                    "id": "c3",
                    "name": "物理课 Class 3",
                    "school_id": "school1",
                    "teacher_id": "teacher1",
                    "members": [],
                },
            })

        courses_c1 = self.shared_data.get_shared_dict_value("eclass", "class:c1:courses")
        if courses_c1 is None:
            self.shared_data.set_shared_dict_value("eclass", "class:c1:courses", [
                {"id": "course-1", "title": "Python 基础", "description": "从零开始学习 Python 编程", "teacher": "Teacher One", "syllabus": ["变量与数据类型", "控制流", "函数", "面向对象"], "materials": [{"name": "第1章讲义", "url": "#"}, {"name": "第2章讲义", "url": "#"}], "enrolled_count": 2, "created_at": "2024-01-15"},
                {"id": "course-2", "title": "Web 开发入门", "description": "HTML、CSS、JavaScript 基础", "teacher": "Teacher One", "syllabus": ["HTML结构", "CSS样式", "JS交互", "DOM操作"], "materials": [{"name": "HTML参考", "url": "#"}], "enrolled_count": 2, "created_at": "2024-02-01"},
                {"id": "course-3", "title": "数据结构与算法", "description": "常用数据结构与算法解析", "teacher": "Teacher One", "syllabus": ["数组与链表", "栈与队列", "树", "排序算法"], "materials": [{"name": "算法导论", "url": "#"}], "enrolled_count": 1, "created_at": "2024-03-01"},
            ])

    def _get_users(self) -> dict[str, dict[str, Any]]:
        self._init_data()
        users = self.shared_data.get_shared_dict_value("eclass", "users") or {}
        return users if isinstance(users, dict) else {}

    def _get_schools(self) -> dict[str, dict[str, Any]]:
        self._init_data()
        schools = self.shared_data.get_shared_dict_value("eclass", "schools") or {}
        return schools if isinstance(schools, dict) else {}

    def _get_classrooms(self) -> dict[str, dict[str, Any]]:
        self._init_data()
        classrooms = self.shared_data.get_shared_dict_value("eclass", "classrooms") or {}
        return classrooms if isinstance(classrooms, dict) else {}

    def _hash(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()[:16]

    async def get_current_user(self, request: Request | AdvanceRequest) -> dict[str, Any] | None:
        advance_request = AdvanceRequest.Cast(request) if isinstance(request, Request) else request
        api_key_text = advance_request.apikey
        if not api_key_text:
            return None
        api_key = await get_apikey_by_key(api_key_text)
        user_id = str(getattr(api_key, "user_id", "") or "") if api_key is not None else ""
        if not user_id:
            return None
        users = self.shared_data.get_shared_dict_value("eclass", "users") or {}
        user = users.get(user_id)
        return dict(user) if isinstance(user, dict) else None

    async def ensure_permission_roles(self) -> None:
        await self._ensure_permission_role(
            STUDENT_ROLE_NAME,
            whitelist_routes=["/api/student*", "/api/classroom*"],
            blacklist_routes=["/api/teacher*"],
        )
        await self._ensure_permission_role(
            TEACHER_ROLE_NAME,
            whitelist_routes=["/api/teacher*", "/api/classroom*"],
            blacklist_routes=["/api/student*"],
        )
        await self._ensure_permission_role(
            SCHOOL_ADMIN_ROLE_NAME,
            whitelist_routes=["/api/teacher*", "/api/audit*", "/api/leader*"],
            blacklist_routes=[],
        )
        await self._ensure_permission_role(
            LEADER_ROLE_NAME,
            whitelist_routes=["/api/leader*", "/api/teacher/profile*"],
            blacklist_routes=[],
        )
        await self._ensure_permission_role(
            AUDITOR_ROLE_NAME,
            whitelist_routes=["/api/teacher/profile*", "/api/teacher/honors*", "/api/audit*"],
            blacklist_routes=[],
        )

    async def _ensure_permission_role(
        self,
        name: str,
        *,
        whitelist_routes: list[str],
        blacklist_routes: list[str],
    ) -> None:
        existing = await get_permission_role_by_name(name)
        if existing is not None:
            await update_permission_role(
                str(existing.id),
                whitelist_routes=whitelist_routes,
                blacklist_routes=blacklist_routes,
                banned=False,
            )
            return
        await create_permission_role(
            name=name,
            whitelist_routes=whitelist_routes,
            blacklist_routes=blacklist_routes,
            banned=False,
        )
