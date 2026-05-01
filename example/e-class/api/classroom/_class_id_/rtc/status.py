# -*- coding: utf-8 -*-

from fastapi import Request

from eclass_api_base import EClassRoute


__all__ = ["ClassroomRTCStatusRoute"]


class ClassroomRTCStatusRoute(EClassRoute):
    Tags = "Classroom"

    async def get(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        room = self.shared_dict.get(f"class:{class_id}:rtc")
        if not room:
            return {"ok": True, "active": False, "room": None}

        participants = list(room.get("participants", []))
        users = self._get_users()
        participant_list = [
            {
                "user_id": uid,
                "name": (users.get(uid) or {}).get("nickname") or (users.get(uid) or {}).get("name") or uid,
            }
            for uid in participants
        ]

        return {
            "ok": True,
            "active": room.get("status") == "open",
            "room": {
                "room_id": room.get("room_id"),
                "status": room.get("status"),
                "started_by": room.get("started_by"),
                "started_at": room.get("started_at"),
                "participants": participant_list,
            },
        }
