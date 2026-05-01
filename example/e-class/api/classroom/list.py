from fastapi import Request

from eclass_api_base import EClassRoute


class ClassroomListRoute(EClassRoute):
    Tags = "Classroom"

    async def get(self, request: Request) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}
        classrooms = self._get_classrooms()
        return {"ok": True, "classrooms": list(classrooms.values())}
