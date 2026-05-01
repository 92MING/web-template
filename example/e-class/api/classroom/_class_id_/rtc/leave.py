# -*- coding: utf-8 -*-

from fastapi import Request

from eclass_api_base import EClassRoute


__all__ = ["ClassroomRTCLeaveRoute"]


class ClassroomRTCLeaveRoute(EClassRoute):
    Tags = "Classroom"

    async def post(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        room = self.shared_dict.get(f"class:{class_id}:rtc")
        if not room:
            return {"ok": False, "error": "会议不存在"}

        user_id = user.get("user_id")
        participants = list(room.get("participants", []))
        if user_id in participants:
            participants.remove(user_id)
            room["participants"] = participants
            self.shared_dict.set(f"class:{class_id}:rtc", room)

        return {"ok": True, "room": room}
