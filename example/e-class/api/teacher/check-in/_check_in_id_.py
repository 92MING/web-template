# -*- coding: utf-8 -*-

from fastapi import HTTPException, Request

from eclass_api_base import EClassRoute
from teacher_domain import AttendanceActivity, AttendanceRecord, TeacherDomainRepository


__all__ = ["TeacherCheckInStatsRoute"]


class TeacherCheckInStatsRoute(EClassRoute):
    Tags = "Teacher"

    async def get(self, request: Request, class_id: str, check_in_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        if user.get("role") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可查看考勤统计")
        repo = TeacherDomainRepository()
        classroom = self._get_classrooms().get(class_id) or {}
        if not repo.teacher_can_access_class(user=user, classroom=classroom):
            raise HTTPException(status_code=403, detail="无权查看指定班级考勤")

        # Find activity
        activities = list(self.shared_dict.get(f"class:{class_id}:checkin-activities", []))
        activity = None
        for a in activities:
            if a.get("check_in_id") == check_in_id:
                activity = a
                break
        if not activity:
            try:
                persisted = await AttendanceActivity.SearchOneById(check_in_id)
            except ValueError:
                persisted = None
            if isinstance(persisted, AttendanceActivity) and persisted.class_id == class_id:
                activity = {
                    **persisted.model_dump(mode="json"),
                    "check_in_id": str(persisted.id),
                }
        if not activity:
            return {"ok": False, "error": "签到活动不存在"}

        # Get all check-in records for this activity
        records = list(self.shared_dict.get(f"class:{class_id}:checkins", []))
        activity_records = [r for r in records if r.get("check_in_id") == check_in_id]
        orm_records = [
            item
            async for item in AttendanceRecord.Search({"activity_id": check_in_id})
            if isinstance(item, AttendanceRecord)
        ]

        # Get classroom members
        member_ids = list(classroom.get("members", []))
        users = self._get_users()

        status_by_student: dict[str, dict[str, object]] = {}
        for record in orm_records:
            status_by_student[record.student_id] = {
                "status": record.status,
                "checked_at": record.checked_at,
            }
        for row in activity_records:
            if not isinstance(row, dict):
                continue
            student_id = str(row.get("student_id") or "")
            if student_id and student_id not in status_by_student:
                status_by_student[student_id] = {
                    "status": str(row.get("status") or "present"),
                    "checked_at": row.get("checked_at"),
                }

        status_counts = {
            "present": 0,
            "late": 0,
            "absent": 0,
            "leave": 0,
            "makeup": 0,
        }
        present = []
        absent = []

        for uid in member_ids:
            u = users.get(uid) or {}
            info = {
                "user_id": uid,
                "name": u.get("nickname") or u.get("name") or uid,
            }
            record = status_by_student.get(uid)
            if record is not None:
                status = str(record.get("status") or "present")
                info["checked_at"] = record.get("checked_at")
                info["status"] = status
                if status in status_counts:
                    status_counts[status] += 1
                present.append(info)
            else:
                status_counts["absent"] += 1
                info["status"] = "absent"
                absent.append(info)

        return {
            "ok": True,
            "activity": activity,
            "stats": {
                "total": len(member_ids),
                "checked": len(present),
                "unchecked": len(absent),
                "status_counts": status_counts,
                "checked_list": present,
                "unchecked_list": absent,
                "present_list": present,
                "absent_list": absent,
            },
        }
