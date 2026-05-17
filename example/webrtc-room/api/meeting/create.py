from urllib.parse import urlencode
from pydantic import BaseModel
from fastapi import Request

from meeting_base import MeetingRouteBase


class CreateMeetingRequest(BaseModel):
    user_name: str
    room_name: str | None = None
    room_password: str | None = None
    close_room_on_creator_left: bool = True


class MeetingCreateRoute(MeetingRouteBase):
    Tags = "ExampleWebRTCRoom"

    async def post(self, request: Request) -> dict[str, object]:
        payload = CreateMeetingRequest.model_validate(await request.json())
        user_name = str(payload.user_name or "").strip()
        if not user_name:
            return {"ok": False, "error": "请输入显示名称"}

        room_name = str(payload.room_name or "").strip() or "Quick Room"
        room_password = str(payload.room_password or "").strip() or None
        module = self._chatroom_module()
        create_token = module.create_room_token(
            name=room_name,
            password=room_password,
            user_name=user_name,
            close_room_on_creator_left=bool(payload.close_room_on_creator_left),
            is_public=room_password is None,
        )
        query = urlencode({
            "mode": "create",
            "create_token": create_token,
            "name": room_name,
            "user_name": user_name,
            "close_room_on_creator_left": "true" if payload.close_room_on_creator_left else "false",
            **({"password": room_password} if room_password else {}),
        })
        return {
            "ok": True,
            "room_url": f"/room.html?{query}",
            "create_token": create_token,
            "room_name": room_name,
            "room_password": room_password,
        }