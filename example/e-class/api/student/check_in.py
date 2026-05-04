# -*- coding: utf-8 -*-

import time

from fastapi import Request
from pydantic import BaseModel

from eclass_api_base import EClassRoute
from teacher_domain import AttendanceActivity, AttendanceRecord


class CheckInRequest(BaseModel):
    check_in_id: str
    class_id: str


__all__ = ["StudentCheckInRoute"]


class StudentCheckInRoute(EClassRoute):
    Tags = "Student"

    async def post(self, request: Request, payload: CheckInRequest) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        # Validate check-in activity
        activities = list(self.shared_dict.get(f"class:{payload.class_id}:checkin-activities", []))
        activity = None
        for a in activities:
            if a.get("check_in_id") == payload.check_in_id:
                activity = a
                break
        if not activity:
            return {"ok": False, "error": "签到活动不存在"}
        if activity.get("status") != "open":
            return {"ok": False, "error": "签到已结束"}
        if activity.get("expires_at") and time.time() > activity.get("expires_at"):
            return {"ok": False, "error": "签到已过期"}

        student_id = user.get("user_id")
        key = f"class:{payload.class_id}:checkins"
        rows = list(self.shared_dict.get(key, []))

        # Prevent duplicate check-in for same activity
        for row in rows:
            if row.get("check_in_id") == payload.check_in_id and row.get("student_id") == student_id:
                return {"ok": False, "error": "已签到，无需重复"}

        activity_model: AttendanceActivity | None = None
        try:
            candidate = await AttendanceActivity.SearchOneById(payload.check_in_id)
            if isinstance(candidate, AttendanceActivity):
                activity_model = candidate
        except ValueError:
            activity_model = None

        row = {
            "check_in_id": payload.check_in_id,
            "student_id": student_id,
            "student_name": user.get("nickname") or user.get("name") or student_id,
            "class_id": payload.class_id,
            "checked_at": time.time(),
            "status": "present",
        }
        rows.append(row)
        self.shared_dict.set(key, rows)

        if activity_model is not None:
            existing = await AttendanceRecord.SearchOne({
                "activity_id": payload.check_in_id,
                "student_id": str(student_id or ""),
            })
            if not isinstance(existing, AttendanceRecord):
                record = AttendanceRecord(
                    teacher_id=activity_model.teacher_id,
                    school_id=activity_model.school_id,
                    created_by=str(student_id or ""),
                    activity_id=payload.check_in_id,
                    class_id=payload.class_id,
                    student_id=str(student_id or ""),
                    status="present",
                    checked_at=row["checked_at"],
                )
                await record.save()

        students_key = f"class:{payload.class_id}:students"
        students = set(self.shared_dict.get(students_key, []))
        students.add(student_id)
        self.shared_dict.set(students_key, sorted(students))
        return {"ok": True, "check_in": row}

    async def get(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        student_id = user.get("user_id")
        key = f"class:{class_id}:checkins"
        rows = list(self.shared_dict.get(key, []))
        my_checkins = [r for r in rows if r.get("student_id") == student_id]
        return {"ok": True, "checkins": my_checkins}
