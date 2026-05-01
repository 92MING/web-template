from pydantic import BaseModel

from eclass_api_base import EClassRoute


class GradeRequest(BaseModel):
    class_id: str
    grade: float
    feedback: str = ""


class TeacherGradeSubmissionRoute(EClassRoute):
    Tags = "Teacher"

    async def post(self, submission_id: str, payload: GradeRequest) -> dict[str, object]:
        key = f"class:{payload.class_id}:submissions"
        rows = list(self.shared_dict.get(key, []))
        for row in rows:
            if isinstance(row, dict) and row.get("submission_id") == submission_id:
                row["grade"] = payload.grade
                row["feedback"] = payload.feedback
                self.shared_dict.set(key, rows)
                return {"ok": True, "submission": row}
        return {"ok": False, "error": "submission not found"}
