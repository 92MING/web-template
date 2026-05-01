# -*- coding: utf-8 -*-

import time
import uuid

from fastapi import Request
from pydantic import BaseModel

from eclass_api_base import EClassRoute


class CheckInCreateRequest(BaseModel):
    class_id: str
    expires_minutes: int = 15


__all__ = ["TeacherCheckInRoute"]


class TeacherCheckInRoute(EClassRoute):
    Tags = "Teacher"

    async def post(self, request: Request, payload: CheckInCreateRequest) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        if user.get("role") != "teacher":
            return {"ok": False, "error": "仅老师可发起签到"}

        check_in_id = str(uuid.uuid4())[:8]
        item = {
            "check_in_id": check_in_id,
            "class_id": payload.class_id,
            "created_by": user.get("user_id"),
            "created_at": time.time(),
            "expires_at": time.time() + payload.expires_minutes * 60,
            "status": "open",
        }
        key = f"class:{payload.class_id}:checkin-activities"
        rows = list(self.shared_dict.get(key, []))
        rows.append(item)
        self.shared_dict.set(key, rows)
        return {"ok": True, "activity": item}

    async def get(self, class_id: str) -> dict[str, object]:
        key = f"class:{class_id}:checkin-activities"
        rows = list(self.shared_dict.get(key, []))
        # Auto-close expired
        now = time.time()
        for row in rows:
            if row.get("status") == "open" and row.get("expires_at") and now > row.get("expires_at"):
                row["status"] = "closed"
        self.shared_dict.set(key, rows)
        return {"ok": True, "activities": sorted(rows, key=lambda x: x.get("created_at", 0), reverse=True)}
