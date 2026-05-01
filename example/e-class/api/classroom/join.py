from fastapi import Request
from eclass_api_base import EClassRoute


class ClassroomJoinRoute(EClassRoute):
    Tags = "Classroom"

    async def post(self, request: Request) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        body = await request.json()
        class_id = body.get("class_id")
        user_id = str(user.get("user_id") or "")
        if not user_id or not class_id:
            return {"ok": False, "error": "缺少参数"}
        key = f"user:{user_id}:classrooms"
        joined = set(self.shared_dict.get(key, []))
        joined.add(class_id)
        self.shared_dict.set(key, list(joined))
        return {"ok": True, "classrooms": list(joined)}

    async def get(self, request: Request, user_id: str = "") -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        current_user_id = str(user.get("user_id") or "")
        resolved_user_id = str(user_id or current_user_id).strip()
        if not resolved_user_id:
            return {"ok": False, "error": "缺少 user_id"}
        if user.get("role") != "teacher" and resolved_user_id != current_user_id:
            return {"ok": False, "error": "无权限"}
        key = f"user:{resolved_user_id}:classrooms"
        joined = self.shared_dict.get(key, [])
        return {"ok": True, "classrooms": joined}
