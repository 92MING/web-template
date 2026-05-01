from fastapi import Request

from eclass_api_base import EClassRoute


class ClassroomMembersRoute(EClassRoute):
    Tags = "Classroom"

    async def get(self, request: Request, class_id: str, action: str = "list") -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        classrooms = self._get_classrooms()
        classroom = classrooms.get(class_id)
        if not classroom:
            return {"ok": False, "error": "教室不存在"}

        if action == "list":
            users = self._get_users()
            members = []
            for uid in classroom.get("members", []):
                u = users.get(uid)
                if u:
                    members.append({
                        "user_id": u.get("user_id"),
                        "nickname": u.get("nickname"),
                        "email": u.get("email"),
                        "role": u.get("role"),
                        "grade": u.get("grade"),
                    })
            return {"ok": True, "members": members}

        if action == "candidates":
            q = request.query_params.get("q", "").lower()
            users = self._get_users()
            existing = set(classroom.get("members", []))
            school_id = classroom.get("school_id")
            candidates = []
            for uid, u in users.items():
                if uid in existing:
                    continue
                if u.get("role") != "student":
                    continue
                if school_id and u.get("school_id") != school_id:
                    continue
                if q and q not in u.get("nickname", "").lower() and q not in u.get("email", "").lower():
                    continue
                candidates.append({
                    "user_id": u.get("user_id"),
                    "nickname": u.get("nickname"),
                    "email": u.get("email"),
                    "grade": u.get("grade"),
                })
            return {"ok": True, "candidates": candidates}

        return {"ok": False, "error": "无效的操作"}

    async def post(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        classrooms = self._get_classrooms()
        classroom = classrooms.get(class_id)
        if not classroom:
            return {"ok": False, "error": "教室不存在"}

        body = await request.json()
        target_user_id = body.get("user_id")
        if not target_user_id:
            return {"ok": False, "error": "缺少用户ID"}

        members = list(classroom.get("members", []))
        if target_user_id not in members:
            members.append(target_user_id)
            classroom["members"] = members
            self.shared_data.set_shared_dict_value("eclass", "classrooms", classrooms)

        return {"ok": True, "members": members}
