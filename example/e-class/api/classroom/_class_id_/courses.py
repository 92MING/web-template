# -*- coding: utf-8 -*-

import time

from fastapi import Request
from pydantic import BaseModel

from eclass_api_base import EClassRoute


class CourseCreateRequest(BaseModel):
    title: str
    description: str = ""
    syllabus: list[str] = []


__all__ = ["ClassroomCoursesRoute"]


class ClassroomCoursesRoute(EClassRoute):
    Tags = "Classroom"

    def _get_courses(self, class_id: str) -> list[dict]:
        key = f"class:{class_id}:courses"
        courses = self.shared_dict.get(key)
        if courses is None:
            # Seed default courses for demo
            defaults = [
                {"id": "course-1", "title": "Python 基础", "description": "从零开始学习 Python 编程", "teacher": "", "syllabus": ["变量与数据类型", "控制流", "函数", "面向对象"], "materials": [{"name": "第1章讲义", "url": "#"}, {"name": "第2章讲义", "url": "#"}], "enrolled_count": 2, "created_at": "2024-01-15"},
                {"id": "course-2", "title": "Web 开发入门", "description": "HTML、CSS、JavaScript 基础", "teacher": "", "syllabus": ["HTML结构", "CSS样式", "JS交互", "DOM操作"], "materials": [{"name": "HTML参考", "url": "#"}], "enrolled_count": 2, "created_at": "2024-02-01"},
                {"id": "course-3", "title": "数据结构与算法", "description": "常用数据结构与算法解析", "teacher": "", "syllabus": ["数组与链表", "栈与队列", "树", "排序算法"], "materials": [{"name": "算法导论", "url": "#"}], "enrolled_count": 1, "created_at": "2024-03-01"},
            ]
            self.shared_dict.set(key, defaults)
            return list(defaults)
        return list(courses)

    def _save_courses(self, class_id: str, courses: list[dict]) -> None:
        self.shared_dict.set(f"class:{class_id}:courses", courses)

    async def get(self, class_id: str, page: int = 1, page_size: int = 10) -> dict[str, object]:
        courses = self._get_courses(class_id)
        classroom = self._get_classrooms().get(class_id) or {}
        teacher_id = classroom.get("teacher_id")
        teacher = (self._get_users().get(teacher_id or "") or {}).get("nickname") or teacher_id

        normalized_courses = [
            course if course.get("teacher") else {**course, "teacher": teacher}
            for course in courses
        ]
        total = len(normalized_courses)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "courses": normalized_courses[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def post(self, request: Request, class_id: str, payload: CourseCreateRequest) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        if user.get("role") != "teacher":
            return {"ok": False, "error": "仅老师可创建课程"}

        courses = self._get_courses(class_id)
        course_id = f"course-{int(time.time())}"
        item = {
            "id": course_id,
            "title": payload.title,
            "description": payload.description,
            "teacher": user.get("nickname") or user.get("name") or user.get("user_id"),
            "syllabus": payload.syllabus,
            "materials": [],
            "enrolled_count": 0,
            "created_at": time.strftime("%Y-%m-%d"),
        }
        courses.append(item)
        self._save_courses(class_id, courses)
        return {"ok": True, "course": item}
