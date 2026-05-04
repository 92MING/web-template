# -*- coding: utf-8 -*-
"""Teacher-domain foundation endpoint."""

from fastapi import HTTPException, Request

from eclass_api_base import EClassRoute
from teacher_domain import TEACHER_DOMAIN_COLLECTIONS, TeacherDomainRepository


class TeacherFoundationRoute(EClassRoute):
    Tags = "Teacher"

    async def get(self, request: Request) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        if user.get("role") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可访问教师端底座")

        repo = TeacherDomainRepository()
        profile = await repo.ensure_teacher_profile(user)
        audits = await repo.list_audit_trails(teacher_id=str(user.get("user_id") or ""), limit=20)

        classrooms = self._get_classrooms()
        owned_class_ids = [
            classroom_id
            for classroom_id, classroom in classrooms.items()
            if repo.teacher_can_access_class(user=user, classroom=classroom)
        ]

        return {
            "ok": True,
            "data_domain": {
                "collections": list(TEACHER_DOMAIN_COLLECTIONS),
                "profile_collection": "teacher_profiles",
                "audit_collection": "teacher_audit_trails",
            },
            "permission_scope": {
                "teacher_id": user.get("user_id"),
                "school_id": user.get("school_id"),
                "owned_class_ids": owned_class_ids,
                "can_edit_self_profile": repo.teacher_can_access_teacher_record(
                    user=user,
                    teacher_id=str(profile.teacher_id),
                ),
            },
            "profile": profile.model_dump(mode="json"),
            "audit_trails": [audit.model_dump(mode="json") for audit in audits],
        }
