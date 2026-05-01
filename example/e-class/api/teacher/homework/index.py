from pydantic import BaseModel

from eclass_api_base import EClassRoute


class HomeworkCreateRequest(BaseModel):
    class_id: str
    title: str
    description: str = ""
    due_at: str | None = None


class TeacherHomeworkRoute(EClassRoute):
    Tags = "Teacher"

    async def post(self, payload: HomeworkCreateRequest) -> dict[str, object]:
        key = f"class:{payload.class_id}:homework"
        rows = list(self.shared_dict.get(key, []))
        item = payload.model_dump()
        item["homework_id"] = f"hw-{len(rows) + 1}"
        rows.append(item)
        self.shared_dict.set(key, rows)
        return {"ok": True, "homework": item}

    async def get(self, class_id: str) -> dict[str, object]:
        return {"items": self.shared_dict.get(f"class:{class_id}:homework", [])}
