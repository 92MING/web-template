from datetime import datetime

from fastapi import Request
from pydantic import BaseModel

from eclass_api_base import EClassRoute


class AnnouncementRequest(BaseModel):
    class_id: str
    title: str
    body: str


class TeacherAnnouncementRoute(EClassRoute):
    Tags = "Teacher"

    async def post(self, request: Request, payload: AnnouncementRequest) -> dict[str, object]:
        key = f"class:{payload.class_id}:announcements"
        rows = list(self.shared_dict.get(key, []))
        current_user = await self.get_current_user(request)
        author = current_user.get("nickname") or current_user.get("name") or current_user.get("user_id") if current_user else None
        item = payload.model_dump()
        item["created_at"] = datetime.now().strftime("%Y-%m-%d")
        item["author"] = author
        rows.append(item)
        self.shared_dict.set(key, rows)
        return {"ok": True, "announcement": item}
