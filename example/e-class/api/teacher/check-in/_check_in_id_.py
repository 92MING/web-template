# -*- coding: utf-8 -*-

import time

from eclass_api_base import EClassRoute


__all__ = ["TeacherCheckInStatsRoute"]


class TeacherCheckInStatsRoute(EClassRoute):
    Tags = "Teacher"

    async def get(self, class_id: str, check_in_id: str) -> dict[str, object]:
        # Find activity
        activities = list(self.shared_dict.get(f"class:{class_id}:checkin-activities", []))
        activity = None
        for a in activities:
            if a.get("check_in_id") == check_in_id:
                activity = a
                break
        if not activity:
            return {"ok": False, "error": "签到活动不存在"}

        # Get all check-in records for this activity
        records = list(self.shared_dict.get(f"class:{class_id}:checkins", []))
        activity_records = [r for r in records if r.get("check_in_id") == check_in_id]

        # Get classroom members
        classroom = self._get_classrooms().get(class_id) or {}
        member_ids = list(classroom.get("members", []))
        users = self._get_users()

        checked_ids = {r.get("student_id") for r in activity_records}
        checked = []
        unchecked = []

        for uid in member_ids:
            u = users.get(uid) or {}
            info = {
                "user_id": uid,
                "name": u.get("nickname") or u.get("name") or uid,
            }
            if uid in checked_ids:
                record = next((r for r in activity_records if r.get("student_id") == uid), {})
                info["checked_at"] = record.get("checked_at")
                checked.append(info)
            else:
                unchecked.append(info)

        return {
            "ok": True,
            "activity": activity,
            "stats": {
                "total": len(member_ids),
                "checked": len(checked),
                "unchecked": len(unchecked),
                "checked_list": checked,
                "unchecked_list": unchecked,
            },
        }
