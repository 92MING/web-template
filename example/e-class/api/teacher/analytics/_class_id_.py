from eclass_api_base import EClassRoute


class TeacherAnalyticsRoute(EClassRoute):
    Tags = "Teacher"

    async def get(self, class_id: str) -> dict[str, object]:
        submissions = self.shared_dict.get(f"class:{class_id}:submissions", [])
        grades = [
            float(row["grade"])
            for row in submissions
            if isinstance(row, dict) and row.get("grade") is not None
        ]
        avg = sum(grades) / len(grades) if grades else None
        return {
            "class_id": class_id,
            "submission_count": len(submissions),
            "graded_count": len(grades),
            "average_grade": avg,
        }
