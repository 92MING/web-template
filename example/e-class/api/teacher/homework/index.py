from pydantic import BaseModel
from fastapi import HTTPException, Request

from eclass_api_base import EClassRoute
from teacher_domain import Homework, TeacherDomainRepository, now_ts


class HomeworkCreateRequest(BaseModel):
    class_id: str = ""
    class_ids: list[str] = []
    student_ids: list[str] = []
    title: str
    description: str = ""
    due_at: str | None = None
    attachments: list[dict[str, object]] = []
    answer_files: list[dict[str, object]] = []
    answer_visible_to_students: bool = False


class GradeImportPreviewRequest(BaseModel):
    homework_id: str
    rows: list[dict[str, object]]


class TeacherHomeworkRoute(EClassRoute):
    Tags = "Teacher"

    async def _current_teacher_or_403(self, request: Request) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        if user.get("role") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可操作作业")
        return user

    def _normalize_class_ids(self, payload: HomeworkCreateRequest) -> list[str]:
        class_ids = [item for item in payload.class_ids if item]
        if payload.class_id:
            class_ids.insert(0, payload.class_id)
        return list(dict.fromkeys(class_ids))

    def _preview_grade_rows(self, rows: list[dict[str, object]]) -> dict[str, object]:
        errors: list[dict[str, object]] = []
        valid_rows: list[dict[str, object]] = []
        for index, row in enumerate(rows, start=1):
            student_id = str(row.get("student_id") or "").strip()
            raw_score = row.get("score")
            if not student_id:
                errors.append({"row": index, "field": "student_id", "message": "缺少学生 ID"})
                continue
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                errors.append({"row": index, "field": "score", "message": "成绩必须为数字"})
                continue
            if score < 0 or score > 100:
                errors.append({"row": index, "field": "score", "message": "成绩必须在 0 到 100 之间"})
                continue
            valid_rows.append({
                "row": index,
                "student_id": student_id,
                "score": score,
                "comment": str(row.get("comment") or ""),
            })
        return {
            "ok": len(errors) == 0,
            "valid_rows": valid_rows,
            "errors": errors,
            "will_write": False,
        }

    async def post(self, request: Request, action: str = "create") -> dict[str, object]:
        user = await self._current_teacher_or_403(request)
        body = await request.json()
        raw_payload = body if isinstance(body, dict) else {}

        if action == "preview_grades":
            payload = GradeImportPreviewRequest.model_validate(raw_payload)
            preview = self._preview_grade_rows(payload.rows)
            preview["homework_id"] = payload.homework_id
            return preview

        payload = HomeworkCreateRequest.model_validate(raw_payload)
        repo = TeacherDomainRepository()
        class_ids = self._normalize_class_ids(payload)
        classrooms = self._get_classrooms()
        denied_class_ids = [
            class_id
            for class_id in class_ids
            if not repo.teacher_can_access_class(user=user, classroom=classrooms.get(class_id, {}))
        ]
        if denied_class_ids:
            raise HTTPException(status_code=403, detail="无权向指定班级发布作业")

        teacher_id = str(user.get("user_id") or "")
        homework = Homework(
            teacher_id=teacher_id,
            school_id=str(user.get("school_id") or ""),
            created_by=teacher_id,
            title=payload.title,
            description=payload.description,
            status="published",
            class_ids=class_ids,
            student_ids=payload.student_ids,
            due_at=payload.due_at,
            attachments=payload.attachments,
            answer_files=[
                {**item, "visible_to_students": payload.answer_visible_to_students}
                for item in payload.answer_files
            ],
        )
        await homework.save()
        await repo.create_audit(
            object_type="Homework",
            object_id=str(homework.id),
            actor_id=teacher_id,
            action="create",
            school_id=homework.school_id,
            teacher_id=teacher_id,
            summary="Published homework",
            after=homework.model_dump(mode="json"),
        )

        item = {
            **payload.model_dump(),
            "homework_id": str(homework.id),
            "id": str(homework.id),
            "status": homework.status,
            "created_at": now_ts(),
        }
        for class_id in class_ids:
            key = f"class:{class_id}:homework"
            rows = list(self.shared_dict.get(key, []))
            rows.append(item)
            self.shared_dict.set(key, rows)
        return {"ok": True, "homework": item}

    async def get(self, request: Request, class_id: str = "", student_id: str = "") -> dict[str, object]:
        user = await self._current_teacher_or_403(request)
        repo = TeacherDomainRepository()
        classrooms = self._get_classrooms()
        if class_id and not repo.teacher_can_access_class(user=user, classroom=classrooms.get(class_id, {})):
            raise HTTPException(status_code=403, detail="无权查看指定班级作业")

        items: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        if class_id:
            for item in self.shared_dict.get(f"class:{class_id}:homework", []):
                if not isinstance(item, dict):
                    continue
                homework_id = str(item.get("homework_id") or item.get("id") or "")
                if homework_id:
                    seen_ids.add(homework_id)
                items.append(item)

        async for homework in Homework.Search({"status": "published"}):
            if not isinstance(homework, Homework):
                continue
            if homework.teacher_id != str(user.get("user_id") or ""):
                continue
            if class_id and class_id not in homework.class_ids:
                continue
            if student_id and homework.student_ids and student_id not in homework.student_ids:
                continue
            if str(homework.id) in seen_ids:
                continue
            seen_ids.add(str(homework.id))
            items.append(homework.model_dump(mode="json"))
        return {"items": items}
