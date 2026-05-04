# -*- coding: utf-8 -*-
"""Leader aggregate attendance summary."""

from fastapi import HTTPException, Request

from eclass_api_base import EClassRoute
from teacher_domain import AttendanceActivity, AttendanceRecord


class LeaderAttendanceSummaryRoute(EClassRoute):
    Tags = "Leader"

    async def get(self, request: Request, class_id: str = "", school_id: str = "") -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        if str(user.get("role") or "") not in {"leader", "school_admin"}:
            raise HTTPException(status_code=403, detail="仅领导可查看考勤统计")

        target_school_id = school_id or str(user.get("school_id") or "")
        classrooms = self._get_classrooms()
        if class_id:
            target_classrooms = {
                cid: classroom
                for cid, classroom in classrooms.items()
                if cid == class_id and str(classroom.get("school_id") or "") == target_school_id
            }
        else:
            target_classrooms = {
                cid: classroom
                for cid, classroom in classrooms.items()
                if str(classroom.get("school_id") or "") == target_school_id
            }
        class_ids = set(target_classrooms.keys())

        query = {"class_id": class_id} if class_id else {"school_id": target_school_id}
        activities = [
            item
            async for item in AttendanceActivity.Search(query)
            if isinstance(item, AttendanceActivity) and item.class_id in class_ids
        ]

        status_counts = {
            "present": 0,
            "late": 0,
            "absent": 0,
            "leave": 0,
            "makeup": 0,
        }
        total_students = 0
        for activity in activities:
            member_ids = list(target_classrooms.get(activity.class_id, {}).get("members", []))
            total_students += len(member_ids)
            records = [
                record
                async for record in AttendanceRecord.Search({"activity_id": str(activity.id)})
                if isinstance(record, AttendanceRecord)
            ]
            recorded_student_ids: set[str] = set()
            for record in records:
                if record.student_id not in member_ids:
                    continue
                recorded_student_ids.add(record.student_id)
                if record.status in status_counts:
                    status_counts[record.status] += 1
            status_counts["absent"] += max(len(member_ids) - len(recorded_student_ids), 0)

        attended = status_counts["present"] + status_counts["late"] + status_counts["makeup"]
        attendance_rate = round(attended / total_students, 4) if total_students else 0.0
        return {
            "ok": True,
            "summary": {
                "school_id": target_school_id,
                "class_id": class_id,
                "class_count": len(class_ids),
                "total_activities": len(activities),
                "total_students": total_students,
                "attendance_rate": attendance_rate,
                **status_counts,
            },
        }
