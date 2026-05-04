# -*- coding: utf-8 -*-
"""Teacher personal honor declaration and review endpoint."""

from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from eclass_api_base import EClassRoute
from teacher_domain import TeacherDomainRepository, TeacherHonor, now_ts


HONOR_CATEGORIES: tuple[str, ...] = (
    "综合荣誉",
    "教学获奖",
    "科研成果",
    "指导学生获奖",
    "名师称号",
    "培训专家",
    "其他",
)
HONOR_TAG_DIMENSIONS: tuple[str, ...] = ("级别", "学段", "学科", "年份", "授予单位", "证明材料类型")
HONOR_VISIBILITIES: frozenset[str] = frozenset({"private", "school", "group", "region"})
HONOR_STAT_METRICS: dict[str, str] = {
    "preview": "preview_count",
    "share": "share_count",
    "reference": "reference_count",
}


class HonorCreatePayload(BaseModel):
    title: str
    category: str = "其他"
    level: str = ""
    granted_by: str = ""
    granted_at: str = ""
    tags: dict[str, object] = Field(default_factory=dict)
    attachments: list[dict[str, object]] = Field(default_factory=list)
    ocr_fields: dict[str, object] = Field(default_factory=dict)
    ai_fields: dict[str, object] = Field(default_factory=dict)
    reminder_due_at: str = ""


class HonorUpdatePayload(BaseModel):
    honor_id: str
    title: str | None = None
    category: str | None = None
    level: str | None = None
    granted_by: str | None = None
    granted_at: str | None = None
    tags: dict[str, object] | None = None
    attachments: list[dict[str, object]] | None = None
    ocr_fields: dict[str, object] | None = None
    ai_fields: dict[str, object] | None = None
    reminder_due_at: str | None = None


class HonorIdPayload(BaseModel):
    honor_id: str


class HonorReviewPayload(BaseModel):
    honor_id: str
    review_reason: str = ""


class HonorSharePayload(BaseModel):
    honor_id: str
    visibility: str


class HonorStatPayload(BaseModel):
    honor_id: str
    metric: str


class TeacherHonorsRoute(EClassRoute):
    Tags = "Teacher"

    async def _current_user_or_403(self, request: Request) -> dict[str, Any]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        return user

    def _client_context(self, request: Request) -> dict[str, object]:
        return {
            "host": request.client.host if request.client is not None else "",
            "user_agent": request.headers.get("user-agent", ""),
        }

    def _normalize_tags(self, tags: dict[str, object]) -> dict[str, object]:
        return {
            name: str(tags.get(name) or "").strip()
            for name in HONOR_TAG_DIMENSIONS
            if str(tags.get(name) or "").strip()
        }

    def _validate_category(self, value: str) -> str:
        category = str(value or "其他").strip() or "其他"
        if category not in HONOR_CATEGORIES:
            raise HTTPException(status_code=400, detail="无效的荣誉分类")
        return category

    def _validate_visibility(self, value: str) -> str:
        visibility = str(value or "private").strip() or "private"
        if visibility not in HONOR_VISIBILITIES:
            raise HTTPException(status_code=400, detail="无效的共享范围")
        return visibility

    def _require_teacher(self, user: dict[str, Any]) -> None:
        if str(user.get("role") or "") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可操作本人荣誉")

    def _require_reviewer(self, user: dict[str, Any]) -> None:
        if str(user.get("role") or "") not in {"auditor", "school_admin", "leader"}:
            raise HTTPException(status_code=403, detail="无权审核荣誉")

    async def _get_owned_honor(self, user: dict[str, Any], honor_id: str) -> TeacherHonor:
        try:
            honor = await TeacherHonor.SearchOneById(honor_id)
        except ValueError:
            honor = None
        if not isinstance(honor, TeacherHonor):
            raise HTTPException(status_code=404, detail="荣誉不存在")
        if honor.teacher_id != str(user.get("user_id") or ""):
            raise HTTPException(status_code=403, detail="无权操作该荣誉")
        return honor

    async def _get_review_honor(self, honor_id: str) -> TeacherHonor:
        try:
            honor = await TeacherHonor.SearchOneById(honor_id)
        except ValueError:
            honor = None
        if not isinstance(honor, TeacherHonor):
            raise HTTPException(status_code=404, detail="荣誉不存在")
        return honor

    def _serialize_honor(self, honor: TeacherHonor) -> dict[str, object]:
        return honor.model_dump(mode="json")

    def _build_stats(self, honors: list[TeacherHonor]) -> dict[str, object]:
        by_category: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_level: dict[str, int] = {}
        for honor in honors:
            by_category[honor.category] = by_category.get(honor.category, 0) + 1
            by_status[honor.status] = by_status.get(honor.status, 0) + 1
            if honor.level:
                by_level[honor.level] = by_level.get(honor.level, 0) + 1
        return {
            "total": len(honors),
            "by_category": by_category,
            "by_status": by_status,
            "by_level": by_level,
        }

    def _build_reminders(self, honors: list[TeacherHonor]) -> list[dict[str, object]]:
        reminders: list[dict[str, object]] = []
        for honor in honors:
            if honor.reminder_due_at:
                reminders.append({
                    "honor_id": str(honor.id),
                    "title": honor.title,
                    "type": "honor_due",
                    "due_at": honor.reminder_due_at,
                    "status": honor.status,
                })
            if honor.status in {"draft", "rejected"} and not honor.attachments:
                reminders.append({
                    "honor_id": str(honor.id),
                    "title": honor.title,
                    "type": "missing_attachment",
                    "due_at": honor.reminder_due_at,
                    "status": honor.status,
                })
        return reminders

    async def _list_teacher_honors(
        self,
        user: dict[str, Any],
        *,
        status: str = "",
        category: str = "",
        level: str = "",
        year: str = "",
    ) -> list[TeacherHonor]:
        honors = [
            honor
            async for honor in TeacherHonor.Search({"teacher_id": str(user.get("user_id") or "")})
            if isinstance(honor, TeacherHonor)
        ]
        result: list[TeacherHonor] = []
        for honor in honors:
            if status and honor.status != status:
                continue
            if category and honor.category != category:
                continue
            if level and honor.level != level:
                continue
            if year and str(honor.tags.get("年份") or "") != year and not honor.granted_at.startswith(year):
                continue
            result.append(honor)
        result.sort(key=lambda item: (item.granted_at, item.updated_at), reverse=True)
        return result

    async def get(
        self,
        request: Request,
        action: str = "list",
        honor_id: str = "",
        status: str = "",
        category: str = "",
        level: str = "",
        year: str = "",
    ) -> dict[str, object]:
        user = await self._current_user_or_403(request)
        if action == "schema":
            return {
                "ok": True,
                "categories": list(HONOR_CATEGORIES),
                "tag_dimensions": list(HONOR_TAG_DIMENSIONS),
                "visibility": sorted(HONOR_VISIBILITIES),
            }
        if action == "audit_queue":
            self._require_reviewer(user)
            items = [
                self._serialize_honor(honor)
                async for honor in TeacherHonor.Search({"status": "pending"})
                if isinstance(honor, TeacherHonor)
            ]
            return {"ok": True, "items": items}

        self._require_teacher(user)
        honors = await self._list_teacher_honors(
            user,
            status=status,
            category=category,
            level=level,
            year=year,
        )
        if action == "preview":
            honor = await self._get_owned_honor(user, honor_id)
            return {
                "ok": True,
                "preview": {
                    "honor_id": str(honor.id),
                    "title": honor.title,
                    "attachments": honor.attachments,
                    "ocr_fields": honor.ocr_fields,
                    "ai_fields": honor.ai_fields,
                },
            }
        if action == "stats":
            return {"ok": True, "stats": self._build_stats(honors)}
        if action == "reminders":
            return {"ok": True, "reminders": self._build_reminders(honors)}
        if action != "list":
            return {"ok": False, "error": "无效的操作"}
        return {"ok": True, "items": [self._serialize_honor(item) for item in honors]}

    async def post(self, request: Request, action: str = "create") -> dict[str, object]:
        user = await self._current_user_or_403(request)
        body = await request.json()
        raw_payload = body if isinstance(body, dict) else {}
        repo = TeacherDomainRepository()

        if action == "create":
            self._require_teacher(user)
            payload = HonorCreatePayload.model_validate(raw_payload)
            honor = TeacherHonor(
                teacher_id=str(user.get("user_id") or ""),
                school_id=str(user.get("school_id") or ""),
                created_by=str(user.get("user_id") or ""),
                title=payload.title,
                category=self._validate_category(payload.category),
                level=payload.level,
                granted_by=payload.granted_by,
                granted_at=payload.granted_at,
                status="draft",
                tags=self._normalize_tags(payload.tags),
                attachments=payload.attachments,
                ocr_fields=payload.ocr_fields,
                ai_fields=payload.ai_fields,
                stats={"preview_count": 0, "share_count": 0, "reference_count": 0},
                reminder_due_at=payload.reminder_due_at,
            )
            await honor.save()
            await repo.create_audit(
                object_type="TeacherHonor",
                object_id=str(honor.id),
                actor_id=str(user.get("user_id") or ""),
                action="create",
                school_id=honor.school_id,
                teacher_id=honor.teacher_id,
                summary="Created teacher honor draft",
                after=honor.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "honor": self._serialize_honor(honor)}

        if action == "update":
            self._require_teacher(user)
            payload = HonorUpdatePayload.model_validate(raw_payload)
            honor = await self._get_owned_honor(user, payload.honor_id)
            if honor.status == "pending":
                raise HTTPException(status_code=400, detail="审核中不可直接修改")
            before = honor.model_dump(mode="json")
            if payload.title is not None:
                honor.title = payload.title
            if payload.category is not None:
                honor.category = self._validate_category(payload.category)
            if payload.level is not None:
                honor.level = payload.level
            if payload.granted_by is not None:
                honor.granted_by = payload.granted_by
            if payload.granted_at is not None:
                honor.granted_at = payload.granted_at
            if payload.tags is not None:
                honor.tags = self._normalize_tags(payload.tags)
            if payload.attachments is not None:
                honor.attachments = payload.attachments
            if payload.ocr_fields is not None:
                honor.ocr_fields = payload.ocr_fields
            if payload.ai_fields is not None:
                honor.ai_fields = payload.ai_fields
            if payload.reminder_due_at is not None:
                honor.reminder_due_at = payload.reminder_due_at
            honor.touch(str(user.get("user_id") or ""))
            await honor.save()
            await repo.create_audit(
                object_type="TeacherHonor",
                object_id=str(honor.id),
                actor_id=str(user.get("user_id") or ""),
                action="update",
                school_id=honor.school_id,
                teacher_id=honor.teacher_id,
                summary="Updated teacher honor",
                before=before,
                after=honor.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "honor": self._serialize_honor(honor)}

        if action == "submit":
            self._require_teacher(user)
            payload = HonorIdPayload.model_validate(raw_payload)
            honor = await self._get_owned_honor(user, payload.honor_id)
            if honor.status not in {"draft", "rejected", "withdrawn"}:
                raise HTTPException(status_code=400, detail="当前状态不可提交")
            before = honor.model_dump(mode="json")
            honor.status = "pending"
            honor.submitted_at = now_ts()
            honor.review_reason = ""
            honor.touch(str(user.get("user_id") or ""))
            await honor.save()
            await repo.create_audit(
                object_type="TeacherHonor",
                object_id=str(honor.id),
                actor_id=str(user.get("user_id") or ""),
                action="submit",
                school_id=honor.school_id,
                teacher_id=honor.teacher_id,
                summary="Submitted teacher honor for review",
                before=before,
                after=honor.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "honor": self._serialize_honor(honor)}

        if action == "withdraw":
            self._require_teacher(user)
            payload = HonorIdPayload.model_validate(raw_payload)
            honor = await self._get_owned_honor(user, payload.honor_id)
            if honor.status != "pending":
                raise HTTPException(status_code=400, detail="仅待审核荣誉可撤回")
            before = honor.model_dump(mode="json")
            honor.status = "withdrawn"
            honor.withdrawn_at = now_ts()
            honor.touch(str(user.get("user_id") or ""))
            await honor.save()
            await repo.create_audit(
                object_type="TeacherHonor",
                object_id=str(honor.id),
                actor_id=str(user.get("user_id") or ""),
                action="withdraw",
                school_id=honor.school_id,
                teacher_id=honor.teacher_id,
                summary="Withdrew teacher honor review request",
                before=before,
                after=honor.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "honor": self._serialize_honor(honor)}

        if action in {"approve", "reject"}:
            self._require_reviewer(user)
            payload = HonorReviewPayload.model_validate(raw_payload)
            if action == "reject" and not payload.review_reason.strip():
                return {"ok": False, "error": "驳回必须填写理由"}
            honor = await self._get_review_honor(payload.honor_id)
            if honor.status != "pending":
                raise HTTPException(status_code=400, detail="仅待审核荣誉可处理")
            before = honor.model_dump(mode="json")
            honor.status = "approved" if action == "approve" else "rejected"
            honor.reviewer_id = str(user.get("user_id") or "")
            honor.review_reason = payload.review_reason
            honor.reviewed_at = now_ts()
            honor.touch(str(user.get("user_id") or ""))
            await honor.save()
            await repo.create_audit(
                object_type="TeacherHonor",
                object_id=str(honor.id),
                actor_id=str(user.get("user_id") or ""),
                action=action,
                school_id=honor.school_id,
                teacher_id=honor.teacher_id,
                summary=f"{action.title()}ed teacher honor",
                before=before,
                after=honor.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "honor": self._serialize_honor(honor)}

        if action == "share":
            self._require_teacher(user)
            payload = HonorSharePayload.model_validate(raw_payload)
            honor = await self._get_owned_honor(user, payload.honor_id)
            before = honor.model_dump(mode="json")
            honor.visibility = self._validate_visibility(payload.visibility)
            stats = dict(honor.stats)
            stats["share_count"] = int(stats.get("share_count", 0)) + 1
            honor.stats = stats
            honor.touch(str(user.get("user_id") or ""))
            await honor.save()
            await repo.create_audit(
                object_type="TeacherHonor",
                object_id=str(honor.id),
                actor_id=str(user.get("user_id") or ""),
                action="share",
                school_id=honor.school_id,
                teacher_id=honor.teacher_id,
                summary="Shared teacher honor",
                before=before,
                after=honor.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "honor": self._serialize_honor(honor)}

        if action == "record_stat":
            self._require_teacher(user)
            payload = HonorStatPayload.model_validate(raw_payload)
            honor = await self._get_owned_honor(user, payload.honor_id)
            stat_key = HONOR_STAT_METRICS.get(payload.metric)
            if stat_key is None:
                raise HTTPException(status_code=400, detail="无效的统计指标")
            stats = dict(honor.stats)
            stats[stat_key] = int(stats.get(stat_key, 0)) + 1
            honor.stats = stats
            honor.touch(str(user.get("user_id") or ""))
            await honor.save()
            return {"ok": True, "honor": self._serialize_honor(honor)}

        return {"ok": False, "error": "无效的操作"}
