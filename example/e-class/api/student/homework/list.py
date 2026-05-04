import time
from fastapi import Request

from eclass_api_base import EClassRoute


class StudentHomeworkListRoute(EClassRoute):
    Tags = "Student"

    async def get(self, request: Request, student_id: str = "s1", class_id: str = "c1") -> dict[str, object]:
        user = await self.get_current_user(request)
        current_student_id = str((user or {}).get("user_id") or student_id)
        rows = list(self.shared_dict.get(f"class:{class_id}:homework", []))
        submission_rows = [
            item
            for item in self.shared_dict.get(f"class:{class_id}:submissions", [])
            if isinstance(item, dict) and item.get("student_id") in {student_id, current_student_id}
        ]
        submission_by_homework: dict[str, dict[str, object]] = {}
        for item in submission_rows:
            homework_id = item.get("homework_id")
            if isinstance(homework_id, str):
                previous = submission_by_homework.get(homework_id)
                if previous is None or (previous.get("grade") is None and item.get("grade") is not None):
                    submission_by_homework[homework_id] = item

        homework = []
        for index, item in enumerate(rows, start=1):
            if not isinstance(item, dict):
                continue
            assigned_student_ids = item.get("student_ids")
            if (
                isinstance(assigned_student_ids, list)
                and assigned_student_ids
                and current_student_id not in assigned_student_ids
                and student_id not in assigned_student_ids
            ):
                continue
            homework_id = item.get("homework_id") or item.get("id") or f"h{index}"
            submission = submission_by_homework.get(str(homework_id))
            status = "pending"
            if submission is not None:
                status = "graded" if submission.get("grade") is not None else "submitted"
            homework.append({
                "id": homework_id,
                "title": item.get("title", ""),
                "due_date": item.get("due_date") or item.get("due_at"),
                "status": status,
            })
        return {"homework": homework}
