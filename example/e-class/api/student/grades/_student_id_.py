from eclass_api_base import EClassRoute


class StudentGradesRoute(EClassRoute):
    Tags = "Student"

    async def get(self, student_id: str) -> dict[str, object]:
        grades: list[dict[str, object]] = []
        for key, value in self.shared_dict.all().items():
            if not key.endswith(":submissions") or not isinstance(value, list):
                continue
            for row in value:
                if isinstance(row, dict) and row.get("student_id") == student_id and row.get("grade") is not None:
                    grades.append(row)
        return {"student_id": student_id, "grades": grades}
