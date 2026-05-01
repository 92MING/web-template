# -*- coding: utf-8 -*-

from fastapi import Request
from pydantic import BaseModel

from eclass_api_base import EClassRoute


class CourseUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    syllabus: list[str] | None = None


__all__ = ["ClassroomCourseDetailRoute"]


class ClassroomCourseDetailRoute(EClassRoute):
    Tags = "Classroom"

    def _get_courses(self, class_id: str) -> list[dict]:
        key = f"class:{class_id}:courses"
        courses = self.shared_dict.get(key)
        if courses is None:
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

    async def get(self, class_id: str, course_id: str) -> dict[str, object]:
        courses = self._get_courses(class_id)
        classroom = self._get_classrooms().get(class_id) or {}
        teacher_id = classroom.get("teacher_id")
        teacher = (self._get_users().get(teacher_id or "") or {}).get("nickname") or teacher_id
        for course in courses:
            if course["id"] == course_id:
                return {"course": course if course.get("teacher") else {**course, "teacher": teacher}}
        return {"error": "Course not found"}

    async def put(self, request: Request, class_id: str, course_id: str, payload: CourseUpdateRequest) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        if user.get("role") != "teacher":
            return {"ok": False, "error": "仅老师可编辑课程"}

        courses = self._get_courses(class_id)
        for i, course in enumerate(courses):
            if course["id"] == course_id:
                if payload.title is not None:
                    course["title"] = payload.title
                if payload.description is not None:
                    course["description"] = payload.description
                if payload.syllabus is not None:
                    course["syllabus"] = payload.syllabus
                courses[i] = course
                self._save_courses(class_id, courses)
                return {"ok": True, "course": course}
        return {"ok": False, "error": "Course not found"}

    async def delete(self, request: Request, class_id: str, course_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        if user.get("role") != "teacher":
            return {"ok": False, "error": "仅老师可删除课程"}

        courses = self._get_courses(class_id)
        for i, course in enumerate(courses):
            if course["id"] == course_id:
                courses.pop(i)
                self._save_courses(class_id, courses)
                return {"ok": True, "deleted": course_id}
        return {"ok": False, "error": "Course not found"}
