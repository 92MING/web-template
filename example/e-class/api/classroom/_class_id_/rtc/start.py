# -*- coding: utf-8 -*-

import time

from fastapi import Request

from eclass_api_base import EClassRoute


__all__ = ["ClassroomRTCStartRoute"]


class ClassroomRTCStartRoute(EClassRoute):
    Tags = "Classroom"

    async def post(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        if user.get("role") != "teacher":
            return {"ok": False, "error": "仅老师可开始会议"}

        room = {
            "class_id": class_id,
            "room_id": f"rtc-{class_id}",
            "status": "open",
            "started_by": user.get("user_id"),
            "started_at": time.time(),
            "participants": [],
        }
        self.shared_dict.set(f"class:{class_id}:rtc", room)
        return {"ok": True, "room": room}
