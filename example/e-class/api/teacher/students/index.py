from pydantic import BaseModel

from eclass_api_base import EClassRoute


class StudentCreateRequest(BaseModel):
    class_id: str
    student_id: str
    name: str


class TeacherStudentsRoute(EClassRoute):
    Tags = "Teacher"

    async def post(self, payload: StudentCreateRequest) -> dict[str, object]:
        key = f"class:{payload.class_id}:student-profiles"
        profiles = dict(self.shared_dict.get(key, {}))
        profiles[payload.student_id] = payload.model_dump()
        self.shared_dict.set(key, profiles)
        students_key = f"class:{payload.class_id}:students"
        students = set(self.shared_dict.get(students_key, []))
        students.add(payload.student_id)
        self.shared_dict.set(students_key, sorted(students))
        return {"ok": True, "student": profiles[payload.student_id]}

    async def get(self, class_id: str) -> dict[str, object]:
        return {"items": self.shared_dict.get(f"class:{class_id}:student-profiles", {})}
