# -*- coding: utf-8 -*-
"""Teacher work log CRUD, statistics, and export data endpoint."""

from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from eclass_api_base import EClassRoute
from teacher_domain import TeacherDomainRepository, TeacherWorkLog


WORK_LOG_TYPES: frozenset[str] = frozenset({
    "teaching",
    "research",
    "class_management",
    "home_school",
    "training",
    "other",
})
WORK_LOG_STATUSES: frozenset[str] = frozenset({"draft", "published", "deleted"})


class WorkLogCreatePayload(BaseModel):
    log_date: str
    log_type: str = "other"
    title: str
    content: str = ""
    status: str = "draft"
    class_ids: list[str] = Field(default_factory=list)
    course_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    homework_ids: list[str] = Field(default_factory=list)
    related_object_ids: list[str] = Field(default_factory=list)
    attachments: list[dict[str, object]] = Field(default_factory=list)


class WorkLogUpdatePayload(BaseModel):
    work_log_id: str
    log_date: str | None = None
    log_type: str | None = None
    title: str | None = None
    content: str | None = None
    status: str | None = None
    class_ids: list[str] | None = None
    course_ids: list[str] | None = None
    resource_ids: list[str] | None = None
    homework_ids: list[str] | None = None
    related_object_ids: list[str] | None = None
    attachments: list[dict[str, object]] | None = None


class WorkLogIdPayload(BaseModel):
    work_log_id: str


class TeacherWorkLogsRoute(EClassRoute):
    Tags = "Teacher"

    async def _current_teacher_or_403(self, request: Request) -> dict[str, Any]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        if user.get("role") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可操作工作日志")
        return user

    def _client_context(self, request: Request) -> dict[str, object]:
        return {
            "host": request.client.host if request.client is not None else "",
            "user_agent": request.headers.get("user-agent", ""),
        }

    def _normalize_unique_ids(self, values: list[str] | None) -> list[str]:
        return list(dict.fromkeys([str(item).strip() for item in values or [] if str(item).strip()]))

    def _validate_log_type(self, value: str) -> str:
        log_type = str(value or "other").strip() or "other"
        if log_type not in WORK_LOG_TYPES:
            raise HTTPException(status_code=400, detail="无效的日志类型")
        return log_type

    def _validate_status(self, value: str) -> str:
        status = str(value or "draft").strip() or "draft"
        if status not in WORK_LOG_STATUSES:
            raise HTTPException(status_code=400, detail="无效的日志状态")
        return status

    def _validate_log_date(self, value: str) -> str:
        text = str(value or "").strip()
        parts = text.split("-")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise HTTPException(status_code=400, detail="日期格式必须为 YYYY-MM-DD")
        return text

    def _check_class_scope(self, user: dict[str, Any], class_ids: list[str]) -> None:
        repo = TeacherDomainRepository()
        classrooms = self._get_classrooms()
        denied = [
            class_id
            for class_id in class_ids
            if not repo.teacher_can_access_class(user=user, classroom=classrooms.get(class_id, {}))
        ]
        if denied:
            raise HTTPException(status_code=403, detail="无权关联指定班级")

    async def _get_owned_log(self, user: dict[str, Any], work_log_id: str) -> TeacherWorkLog:
        try:
            work_log = await TeacherWorkLog.SearchOneById(work_log_id)
        except ValueError:
            work_log = None
        if not isinstance(work_log, TeacherWorkLog):
            raise HTTPException(status_code=404, detail="工作日志不存在")
        if work_log.teacher_id != str(user.get("user_id") or ""):
            raise HTTPException(status_code=403, detail="无权操作该工作日志")
        return work_log

    def _matches_filters(
        self,
        work_log: TeacherWorkLog,
        *,
        month: str,
        log_type: str,
        status: str,
        include_deleted: bool,
    ) -> bool:
        if not include_deleted and work_log.status == "deleted":
            return False
        if month and not work_log.log_date.startswith(f"{month}-"):
            return False
        if log_type and work_log.log_type != log_type:
            return False
        if status and work_log.status != status:
            return False
        return True

    def _serialize_log(self, work_log: TeacherWorkLog) -> dict[str, object]:
        return work_log.model_dump(mode="json")

    def _build_stats(self, work_logs: list[TeacherWorkLog]) -> dict[str, object]:
        by_type: dict[str, int] = {}
        by_month: dict[str, int] = {}
        by_class: dict[str, int] = {}
        for work_log in work_logs:
            by_type[work_log.log_type] = by_type.get(work_log.log_type, 0) + 1
            month = work_log.log_date[:7]
            by_month[month] = by_month.get(month, 0) + 1
            for class_id in work_log.class_ids:
                by_class[class_id] = by_class.get(class_id, 0) + 1
        return {
            "total": len(work_logs),
            "by_type": by_type,
            "by_month": by_month,
            "by_class": by_class,
        }

    def _build_export_rows(self, work_logs: list[TeacherWorkLog]) -> list[dict[str, object]]:
        return [
            {
                "id": str(work_log.id),
                "log_date": work_log.log_date,
                "log_type": work_log.log_type,
                "title": work_log.title,
                "content": work_log.content,
                "status": work_log.status,
                "class_ids": ",".join(work_log.class_ids),
                "course_ids": ",".join(work_log.course_ids),
                "resource_ids": ",".join(work_log.resource_ids),
                "homework_ids": ",".join(work_log.homework_ids),
                "attachment_count": len(work_log.attachments),
            }
            for work_log in work_logs
        ]

    async def _filtered_logs(
        self,
        user: dict[str, Any],
        *,
        month: str,
        log_type: str,
        status: str,
        include_deleted: bool,
    ) -> list[TeacherWorkLog]:
        items = [
            work_log
            async for work_log in TeacherWorkLog.Search({"teacher_id": str(user.get("user_id") or "")})
            if isinstance(work_log, TeacherWorkLog)
            and self._matches_filters(
                work_log,
                month=month,
                log_type=log_type,
                status=status,
                include_deleted=include_deleted,
            )
        ]
        items.sort(key=lambda item: (item.log_date, item.updated_at), reverse=True)
        return items

    async def get(
        self,
        request: Request,
        action: str = "list",
        month: str = "",
        log_type: str = "",
        status: str = "",
        include_deleted: bool = False,
    ) -> dict[str, object]:
        user = await self._current_teacher_or_403(request)
        work_logs = await self._filtered_logs(
            user,
            month=month,
            log_type=log_type,
            status=status,
            include_deleted=include_deleted,
        )
        if action == "stats":
            return {"ok": True, "stats": self._build_stats(work_logs)}
        if action == "export":
            repo = TeacherDomainRepository()
            await repo.create_audit(
                object_type="TeacherWorkLog",
                object_id=str(user.get("user_id") or ""),
                actor_id=str(user.get("user_id") or ""),
                action="export",
                school_id=str(user.get("school_id") or ""),
                teacher_id=str(user.get("user_id") or ""),
                summary="Exported teacher work logs",
                after={"count": len(work_logs), "month": month, "log_type": log_type},
                client=self._client_context(request),
            )
            return {"ok": True, "rows": self._build_export_rows(work_logs)}
        if action != "list":
            return {"ok": False, "error": "无效的操作"}
        return {"ok": True, "items": [self._serialize_log(item) for item in work_logs]}

    async def post(self, request: Request, action: str = "create") -> dict[str, object]:
        user = await self._current_teacher_or_403(request)
        body = await request.json()
        raw_payload = body if isinstance(body, dict) else {}
        repo = TeacherDomainRepository()

        if action == "create":
            payload = WorkLogCreatePayload.model_validate(raw_payload)
            class_ids = self._normalize_unique_ids(payload.class_ids)
            self._check_class_scope(user, class_ids)
            work_log = TeacherWorkLog(
                teacher_id=str(user.get("user_id") or ""),
                school_id=str(user.get("school_id") or ""),
                created_by=str(user.get("user_id") or ""),
                log_date=self._validate_log_date(payload.log_date),
                log_type=self._validate_log_type(payload.log_type),
                title=payload.title,
                content=payload.content,
                status=self._validate_status(payload.status),
                class_ids=class_ids,
                course_ids=self._normalize_unique_ids(payload.course_ids),
                resource_ids=self._normalize_unique_ids(payload.resource_ids),
                homework_ids=self._normalize_unique_ids(payload.homework_ids),
                related_object_ids=self._normalize_unique_ids(payload.related_object_ids),
                attachments=payload.attachments,
            )
            await work_log.save()
            await repo.create_audit(
                object_type="TeacherWorkLog",
                object_id=str(work_log.id),
                actor_id=str(user.get("user_id") or ""),
                action="create",
                school_id=work_log.school_id,
                teacher_id=work_log.teacher_id,
                summary="Created teacher work log",
                after=work_log.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "work_log": self._serialize_log(work_log)}

        if action == "update":
            payload = WorkLogUpdatePayload.model_validate(raw_payload)
            work_log = await self._get_owned_log(user, payload.work_log_id)
            before = work_log.model_dump(mode="json")
            if payload.log_date is not None:
                work_log.log_date = self._validate_log_date(payload.log_date)
            if payload.log_type is not None:
                work_log.log_type = self._validate_log_type(payload.log_type)
            if payload.title is not None:
                work_log.title = payload.title
            if payload.content is not None:
                work_log.content = payload.content
            if payload.status is not None:
                work_log.status = self._validate_status(payload.status)
            if payload.class_ids is not None:
                class_ids = self._normalize_unique_ids(payload.class_ids)
                self._check_class_scope(user, class_ids)
                work_log.class_ids = class_ids
            if payload.course_ids is not None:
                work_log.course_ids = self._normalize_unique_ids(payload.course_ids)
            if payload.resource_ids is not None:
                work_log.resource_ids = self._normalize_unique_ids(payload.resource_ids)
            if payload.homework_ids is not None:
                work_log.homework_ids = self._normalize_unique_ids(payload.homework_ids)
            if payload.related_object_ids is not None:
                work_log.related_object_ids = self._normalize_unique_ids(payload.related_object_ids)
            if payload.attachments is not None:
                work_log.attachments = payload.attachments
            work_log.touch(str(user.get("user_id") or ""))
            await work_log.save()
            await repo.create_audit(
                object_type="TeacherWorkLog",
                object_id=str(work_log.id),
                actor_id=str(user.get("user_id") or ""),
                action="update",
                school_id=work_log.school_id,
                teacher_id=work_log.teacher_id,
                summary="Updated teacher work log",
                before=before,
                after=work_log.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "work_log": self._serialize_log(work_log)}

        if action == "delete":
            payload = WorkLogIdPayload.model_validate(raw_payload)
            work_log = await self._get_owned_log(user, payload.work_log_id)
            before = work_log.model_dump(mode="json")
            work_log.status = "deleted"
            work_log.touch(str(user.get("user_id") or ""))
            await work_log.save()
            await repo.create_audit(
                object_type="TeacherWorkLog",
                object_id=str(work_log.id),
                actor_id=str(user.get("user_id") or ""),
                action="delete",
                school_id=work_log.school_id,
                teacher_id=work_log.teacher_id,
                summary="Soft-deleted teacher work log",
                before=before,
                after=work_log.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "work_log": self._serialize_log(work_log)}

        return {"ok": False, "error": "无效的操作"}
