# -*- coding: utf-8 -*-

from fastapi import Request

from eclass_api_base import EClassRoute


__all__ = ["ClassroomRTCEndRoute"]


class ClassroomRTCEndRoute(EClassRoute):
    Tags = "Classroom"

    async def post(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        if user.get("role") != "teacher":
            return {"ok": False, "error": "仅老师可结束会议"}

        room = self.shared_dict.get(f"class:{class_id}:rtc")
        if not room:
            return {"ok": False, "error": "会议不存在"}

        room["status"] = "closed"
        room["participants"] = []
        self.shared_dict.set(f"class:{class_id}:rtc", room)
        return {"ok": True, "room": room}
