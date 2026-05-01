# -*- coding: utf-8 -*-

import time

from fastapi import Request

from eclass_api_base import EClassRoute


__all__ = ["ClassroomRTCJoinRoute"]


class ClassroomRTCJoinRoute(EClassRoute):
    Tags = "Classroom"

    async def post(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        room = self.shared_dict.get(f"class:{class_id}:rtc")
        if not room:
            return {"ok": False, "error": "会议尚未开始"}
        if room.get("status") != "open":
            return {"ok": False, "error": "会议已结束"}

        user_id = user.get("user_id")
        participants = list(room.get("participants", []))
        if user_id not in participants:
            participants.append(user_id)
            room["participants"] = participants
            self.shared_dict.set(f"class:{class_id}:rtc", room)

        return {
            "ok": True,
            "room": room,
            "join_url": f"/rtc-room.html?room_id=rtc-{class_id}&user_id={user_id}",
        }
