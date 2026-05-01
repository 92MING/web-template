from fastapi import Request

from eclass_api_base import EClassRoute


class ClassroomCreateRoute(EClassRoute):
    Tags = "Classroom"

    async def post(self, request: Request) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        if user.get("role") != "teacher":
            return {"ok": False, "error": "只有老师可以创建教室"}

        body = await request.json()
        name = body.get("name", "")
        school_id = body.get("school_id", user.get("school_id", ""))
        if not name:
            return {"ok": False, "error": "教室名称不能为空"}

        import time
        class_id = f"c{int(time.time())}"
        classrooms = self.shared_data.get_shared_dict_value("eclass", "classrooms") or {}
        classrooms[class_id] = {
            "id": class_id,
            "name": name,
            "school_id": school_id,
            "teacher_id": user.get("user_id"),
            "members": [],
        }
        self.shared_data.set_shared_dict_value("eclass", "classrooms", classrooms)
        return {"ok": True, "classroom": classrooms[class_id]}
