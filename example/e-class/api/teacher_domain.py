# -*- coding: utf-8 -*-
"""Teacher domain models and helpers for the e-class example.

This module is intentionally route-free. Route files import it to use the same
formal ORM-backed data domain instead of adding more SharedDict-only state.
"""

import time
from typing import Any, Literal

from core.storage.orm import ORMField, ORMModel

TEACHER_DOMAIN_COLLECTIONS: tuple[str, ...] = (
    "teacher_profiles",
    "teacher_profile_change_requests",
    "teacher_homework",
    "teacher_homework_submissions",
    "teacher_attendance_activities",
    "teacher_attendance_records",
    "teacher_resources",
    "teacher_honors",
    "teacher_work_logs",
    "teacher_audit_trails",
)

TeacherAuditAction = Literal[
    "create",
    "update",
    "delete",
    "submit",
    "withdraw",
    "approve",
    "reject",
    "share",
    "export",
    "bootstrap",
]

PROFILE_FIELD_SCHEMA: tuple[dict[str, object], ...] = (
    {
        "tab": "基础信息",
        "modules": (
            {
                "name": "个人信息",
                "fields": (
                    {"name": "姓名", "type": "text", "required": True},
                    {"name": "证件号", "type": "id_card", "required": False, "sensitive": True, "key": True},
                    {"name": "联系电话", "type": "phone", "required": False, "sensitive": True},
                    {"name": "出生日期", "type": "date", "required": False},
                    {"name": "年龄", "type": "integer", "required": False},
                    {"name": "所在学校", "type": "text", "required": True},
                    {"name": "联系地址", "type": "text", "required": False, "sensitive": True},
                ),
            },
            {
                "name": "学历信息列表",
                "fields": (
                    {"name": "最高学历", "type": "text", "required": False},
                    {"name": "毕业证书编号", "type": "certificate_no", "required": False, "sensitive": True, "key": True},
                    {"name": "学位证书编号", "type": "certificate_no", "required": False, "sensitive": True, "key": True},
                    {"name": "证明材料", "type": "attachments", "required": False, "key": True},
                ),
            },
        ),
    },
    {
        "tab": "职务职称",
        "modules": (
            {
                "name": "教师资格",
                "fields": (
                    {"name": "资格证书编号", "type": "certificate_no", "required": False, "sensitive": True, "key": True},
                    {"name": "任教学段", "type": "text", "required": False},
                    {"name": "任教学科", "type": "text", "required": False},
                ),
            },
            {
                "name": "拟申报职称",
                "fields": (
                    {"name": "现职称", "type": "text", "required": False, "key": True},
                    {"name": "拟申报职称", "type": "text", "required": False, "key": True},
                ),
            },
        ),
    },
    {"tab": "教育教学", "modules": ({"name": "教学工作获奖", "fields": ()},)},
    {"tab": "科研工作", "modules": ({"name": "主持课题", "fields": ()},)},
    {"tab": "奖惩考核", "modules": ({"name": "综合荣誉单项获奖", "fields": ()},)},
    {"tab": "示范引领", "modules": ({"name": "名师工作室", "fields": ()},)},
    {"tab": "培训教育", "modules": ({"name": "培训学时", "fields": ()},)},
    {"tab": "学术团体", "modules": ({"name": "学术任职", "fields": ()},)},
    {"tab": "评价评议", "modules": ({"name": "教学质量综合考核表", "fields": ()},)},
    {"tab": "离退休", "modules": ({"name": "离退休信息", "fields": ()},)},
)

PROFILE_FIELD_INDEX: dict[str, dict[str, object]] = {
    f"{tab['tab']}.{module['name']}.{field['name']}": {
        **field,
        "tab": tab["tab"],
        "module": module["name"],
    }
    for tab in PROFILE_FIELD_SCHEMA
    for module in tab["modules"]  # type: ignore[index]
    for field in module["fields"]  # type: ignore[index]
}

SENSITIVE_PROFILE_FIELD_NAMES: frozenset[str] = frozenset(
    str(field["name"])
    for field in PROFILE_FIELD_INDEX.values()
    if bool(field.get("sensitive"))
)

KEY_PROFILE_FIELD_NAMES: frozenset[str] = frozenset(
    str(field["name"])
    for field in PROFILE_FIELD_INDEX.values()
    if bool(field.get("key"))
)


def now_ts() -> float:
    return time.time()


def _is_valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split("-")
    if len(parts) != 3:
        return False
    year, month, day = parts
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return False
    return 1900 <= int(year) <= 2100 and 1 <= int(month) <= 12 and 1 <= int(day) <= 31


def _mask_text(value: object) -> object:
    text = str(value or "")
    if len(text) <= 2:
        return "*" * len(text)
    if len(text) <= 6:
        return f"{text[0]}{'*' * (len(text) - 2)}{text[-1]}"
    return f"{text[:3]}{'*' * (len(text) - 5)}{text[-2:]}"


def _deep_merge_dict(base: dict[str, object], patch: dict[str, object]) -> dict[str, object]:
    merged: dict[str, object] = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(
                merged[key],  # type: ignore[arg-type]
                value,
            )
        else:
            merged[key] = value
    return merged


def _iter_profile_fields(
    groups: dict[str, object],
) -> list[tuple[str, str, str, object]]:
    result: list[tuple[str, str, str, object]] = []
    for tab_name, tab_value in groups.items():
        if not isinstance(tab_value, dict):
            continue
        for module_name, module_value in tab_value.items():
            if not isinstance(module_value, dict):
                continue
            for field_name, field_value in module_value.items():
                result.append((str(tab_name), str(module_name), str(field_name), field_value))
    return result


class TeacherOwnedModel(ORMModel):
    """Base model for teacher-owned records."""

    teacher_id: str = ORMField(default="", index=True)
    school_id: str = ORMField(default="", index=True)
    created_by: str = ""
    created_at: float = ORMField(default_factory=now_ts, index=True)
    updated_at: float = ORMField(default_factory=now_ts, index=True)

    def touch(self, user_id: str) -> None:
        self.updated_at = now_ts()
        if not self.created_by:
            self.created_by = user_id


class TeacherProfile(TeacherOwnedModel, full_collection_name="teacher_profiles"):
    """Teacher one-person-one-file profile root."""

    display_name: str = ""
    email: str = ORMField(default="", index=True)
    role: str = "teacher"
    status: str = ORMField(default="active", index=True)
    field_groups: dict[str, object] = {}
    privacy_settings: dict[str, object] = {}


class TeacherProfileChangeRequest(
    TeacherOwnedModel,
    full_collection_name="teacher_profile_change_requests",
):
    """Auditable change request for key profile fields."""

    profile_id: str = ORMField(default="", index=True)
    status: str = ORMField(default="pending", index=True)
    changes: dict[str, object] = {}
    reason: str = ""
    reviewer_id: str = ""
    review_reason: str = ""
    reviewed_at: float | None = None


class Homework(TeacherOwnedModel, full_collection_name="teacher_homework"):
    """Formal homework assignment root."""

    title: str = ""
    description: str = ""
    status: str = ORMField(default="draft", index=True)
    class_ids: list[str] = []
    student_ids: list[str] = []
    due_at: str | None = None
    attachments: list[dict[str, object]] = []
    answer_files: list[dict[str, object]] = []


class HomeworkSubmission(TeacherOwnedModel, full_collection_name="teacher_homework_submissions"):
    """Student submission and grading record."""

    homework_id: str = ORMField(default="", index=True)
    class_id: str = ORMField(default="", index=True)
    student_id: str = ORMField(default="", index=True)
    status: str = ORMField(default="submitted", index=True)
    files: list[dict[str, object]] = []
    grade: float | None = None
    grade_level: str = ""
    feedback: str = ""
    graded_by: str = ""
    graded_at: float | None = None


class AttendanceActivity(
    TeacherOwnedModel,
    full_collection_name="teacher_attendance_activities",
):
    """Teacher-launched student attendance activity."""

    class_id: str = ORMField(default="", index=True)
    course_id: str = ORMField(default="", index=True)
    attendance_date: str = ORMField(default="", index=True)
    attendance_type: str = "check_in"
    status: str = ORMField(default="open", index=True)
    starts_at: float = ORMField(default_factory=now_ts, index=True)
    expires_at: float | None = None
    ended_at: float | None = None
    allow_makeup: bool = False


class AttendanceRecord(TeacherOwnedModel, full_collection_name="teacher_attendance_records"):
    """Per-student attendance result."""

    activity_id: str = ORMField(default="", index=True)
    class_id: str = ORMField(default="", index=True)
    student_id: str = ORMField(default="", index=True)
    status: str = ORMField(default="present", index=True)
    checked_at: float | None = None
    makeup_reason: str = ""


class TeachingResource(TeacherOwnedModel, full_collection_name="teacher_resources"):
    """Teaching resource with formal tag dimensions."""

    title: str = ""
    description: str = ""
    resource_type: str = ORMField(default="file", index=True)
    status: str = ORMField(default="active", index=True)
    class_ids: list[str] = []
    visibility: str = ORMField(default="private", index=True)
    file_refs: list[dict[str, object]] = []
    tags: dict[str, object] = {}
    version: str = ""
    course_objectives_html: str = ""
    course_content_html: str = ""
    evaluation_method_html: str = ""
    stats: dict[str, int] = {}


class TeacherHonor(TeacherOwnedModel, full_collection_name="teacher_honors"):
    """Teacher honor declaration and review record."""

    title: str = ""
    category: str = ORMField(default="", index=True)
    level: str = ORMField(default="", index=True)
    granted_by: str = ""
    granted_at: str = ""
    status: str = ORMField(default="draft", index=True)
    tags: dict[str, object] = {}
    attachments: list[dict[str, object]] = []
    ocr_fields: dict[str, object] = {}
    ai_fields: dict[str, object] = {}
    visibility: str = ORMField(default="private", index=True)
    stats: dict[str, int] = {}
    reviewer_id: str = ""
    review_reason: str = ""
    submitted_at: float | None = None
    reviewed_at: float | None = None
    withdrawn_at: float | None = None
    reminder_due_at: str = ""


class TeacherWorkLog(TeacherOwnedModel, full_collection_name="teacher_work_logs"):
    """Teacher work log entry."""

    log_date: str = ORMField(default="", index=True)
    log_type: str = ORMField(default="other", index=True)
    title: str = ""
    content: str = ""
    status: str = ORMField(default="draft", index=True)
    class_ids: list[str] = []
    course_ids: list[str] = []
    resource_ids: list[str] = []
    homework_ids: list[str] = []
    related_object_ids: list[str] = []
    attachments: list[dict[str, object]] = []


class AuditTrail(ORMModel, full_collection_name="teacher_audit_trails"):
    """Whole-chain teacher-domain audit entry."""

    object_type: str = ORMField(default="", index=True)
    object_id: str = ORMField(default="", index=True)
    actor_id: str = ORMField(default="", index=True)
    action: str = ORMField(default="", index=True)
    school_id: str = ORMField(default="", index=True)
    teacher_id: str = ORMField(default="", index=True)
    summary: str = ""
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    client: dict[str, object] = {}
    created_at: float = ORMField(default_factory=now_ts, index=True)


class TeacherDomainRepository:
    """Small repository for teacher-domain bootstrap and permission helpers."""

    async def ensure_teacher_profile(self, user: dict[str, Any]) -> TeacherProfile:
        teacher_id = str(user.get("user_id") or "")
        existing = await TeacherProfile.SearchOne({"teacher_id": teacher_id})
        if isinstance(existing, TeacherProfile):
            return existing

        profile = TeacherProfile(
            teacher_id=teacher_id,
            school_id=str(user.get("school_id") or ""),
            created_by=teacher_id,
            display_name=str(user.get("nickname") or user.get("name") or teacher_id),
            email=str(user.get("email") or ""),
            role=str(user.get("role") or "teacher"),
            field_groups={
                "基础信息": {
                    "个人信息": {
                        "姓名": user.get("name") or user.get("nickname") or teacher_id,
                        "所在学校": user.get("school_id") or "",
                    },
                },
            },
        )
        await profile.save()
        await self.create_audit(
            object_type="TeacherProfile",
            object_id=str(profile.id),
            actor_id=teacher_id,
            action="bootstrap",
            school_id=profile.school_id,
            teacher_id=teacher_id,
            summary="Created teacher profile root record",
            after=profile.model_dump(mode="json"),
        )
        return profile

    def get_profile_schema(self) -> tuple[dict[str, object], ...]:
        return PROFILE_FIELD_SCHEMA

    def validate_profile_changes(self, changes: dict[str, object]) -> list[dict[str, object]]:
        errors: list[dict[str, object]] = []
        for tab_name, module_name, field_name, value in _iter_profile_fields(changes):
            schema = PROFILE_FIELD_INDEX.get(f"{tab_name}.{module_name}.{field_name}")
            if schema is None:
                errors.append({
                    "tab": tab_name,
                    "module": module_name,
                    "field": field_name,
                    "message": "字段不在教师档案字段分组中",
                })
                continue

            if bool(schema.get("required")) and (value is None or str(value).strip() == ""):
                errors.append({
                    "tab": tab_name,
                    "module": module_name,
                    "field": field_name,
                    "message": "必填项不能为空",
                })
                continue

            field_type = str(schema.get("type") or "")
            if value in (None, ""):
                continue
            if field_type == "phone" and not (isinstance(value, str) and value.isdigit() and len(value) == 11):
                errors.append({
                    "tab": tab_name,
                    "module": module_name,
                    "field": field_name,
                    "message": "联系电话必须为 11 位数字",
                })
            elif field_type == "id_card" and not (
                isinstance(value, str)
                and len(value) == 18
                and value[:-1].isdigit()
                and (value[-1].isdigit() or value[-1].lower() == "x")
            ):
                errors.append({
                    "tab": tab_name,
                    "module": module_name,
                    "field": field_name,
                    "message": "证件号必须为 18 位",
                })
            elif field_type == "date" and not _is_valid_date(value):
                errors.append({
                    "tab": tab_name,
                    "module": module_name,
                    "field": field_name,
                    "message": "日期格式必须为 YYYY-MM-DD",
                })
            elif field_type == "integer" and not isinstance(value, int):
                errors.append({
                    "tab": tab_name,
                    "module": module_name,
                    "field": field_name,
                    "message": "必须为整数",
                })
        return errors

    def mask_profile_fields(
        self,
        field_groups: dict[str, object],
        *,
        reveal_sensitive: bool = False,
    ) -> dict[str, object]:
        if reveal_sensitive:
            return field_groups
        masked: dict[str, object] = {}
        for tab_name, tab_value in field_groups.items():
            if not isinstance(tab_value, dict):
                masked[tab_name] = tab_value
                continue
            masked_modules: dict[str, object] = {}
            for module_name, module_value in tab_value.items():
                if not isinstance(module_value, dict):
                    masked_modules[str(module_name)] = module_value
                    continue
                masked_fields: dict[str, object] = {}
                for field_name, field_value in module_value.items():
                    if str(field_name) in SENSITIVE_PROFILE_FIELD_NAMES:
                        masked_fields[str(field_name)] = _mask_text(field_value)
                    else:
                        masked_fields[str(field_name)] = field_value
                masked_modules[str(module_name)] = masked_fields
            masked[str(tab_name)] = masked_modules
        return masked

    async def submit_profile_change(
        self,
        *,
        user: dict[str, Any],
        changes: dict[str, object],
        reason: str = "",
        client: dict[str, object] | None = None,
    ) -> tuple[TeacherProfileChangeRequest | None, list[dict[str, object]]]:
        profile = await self.ensure_teacher_profile(user)
        errors = self.validate_profile_changes(changes)
        if errors:
            return None, errors

        teacher_id = str(user.get("user_id") or "")
        change = TeacherProfileChangeRequest(
            teacher_id=teacher_id,
            school_id=str(user.get("school_id") or ""),
            created_by=teacher_id,
            profile_id=str(profile.id),
            changes=changes,
            reason=reason,
        )
        await change.save()
        await self.create_audit(
            object_type="TeacherProfileChangeRequest",
            object_id=str(change.id),
            actor_id=teacher_id,
            action="submit",
            school_id=change.school_id,
            teacher_id=teacher_id,
            summary="Submitted teacher profile change request",
            after=change.model_dump(mode="json"),
            client=client,
        )
        return change, []

    async def approve_profile_change(
        self,
        *,
        reviewer: dict[str, Any],
        change_id: str,
        review_reason: str = "",
        client: dict[str, object] | None = None,
    ) -> TeacherProfileChangeRequest | None:
        if str(reviewer.get("role") or "") not in {"school_admin", "leader", "auditor"}:
            return None
        change = await TeacherProfileChangeRequest.SearchOneById(change_id)
        if not isinstance(change, TeacherProfileChangeRequest) or change.status != "pending":
            return None
        profile = await TeacherProfile.SearchOneById(change.profile_id)
        if not isinstance(profile, TeacherProfile):
            return None

        before = profile.model_dump(mode="json")
        profile.field_groups = _deep_merge_dict(profile.field_groups, change.changes)
        profile.touch(str(reviewer.get("user_id") or ""))
        await profile.save()

        change.status = "approved"
        change.reviewer_id = str(reviewer.get("user_id") or "")
        change.review_reason = review_reason
        change.reviewed_at = now_ts()
        change.touch(str(reviewer.get("user_id") or ""))
        await change.save()

        await self.create_audit(
            object_type="TeacherProfileChangeRequest",
            object_id=str(change.id),
            actor_id=change.reviewer_id,
            action="approve",
            school_id=change.school_id,
            teacher_id=change.teacher_id,
            summary="Approved teacher profile change request",
            before=before,
            after=profile.model_dump(mode="json"),
            client=client,
        )
        return change

    async def reject_profile_change(
        self,
        *,
        reviewer: dict[str, Any],
        change_id: str,
        review_reason: str,
        client: dict[str, object] | None = None,
    ) -> TeacherProfileChangeRequest | None:
        if not review_reason.strip():
            return None
        if str(reviewer.get("role") or "") not in {"school_admin", "leader", "auditor"}:
            return None
        change = await TeacherProfileChangeRequest.SearchOneById(change_id)
        if not isinstance(change, TeacherProfileChangeRequest) or change.status != "pending":
            return None
        before = change.model_dump(mode="json")
        change.status = "rejected"
        change.reviewer_id = str(reviewer.get("user_id") or "")
        change.review_reason = review_reason
        change.reviewed_at = now_ts()
        change.touch(str(reviewer.get("user_id") or ""))
        await change.save()
        await self.create_audit(
            object_type="TeacherProfileChangeRequest",
            object_id=str(change.id),
            actor_id=change.reviewer_id,
            action="reject",
            school_id=change.school_id,
            teacher_id=change.teacher_id,
            summary="Rejected teacher profile change request",
            before=before,
            after=change.model_dump(mode="json"),
            client=client,
        )
        return change

    async def create_audit(
        self,
        *,
        object_type: str,
        object_id: str,
        actor_id: str,
        action: TeacherAuditAction,
        school_id: str,
        teacher_id: str,
        summary: str,
        before: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
        client: dict[str, object] | None = None,
    ) -> AuditTrail:
        audit = AuditTrail(
            object_type=object_type,
            object_id=object_id,
            actor_id=actor_id,
            action=action,
            school_id=school_id,
            teacher_id=teacher_id,
            summary=summary,
            before=before or {},
            after=after or {},
            client=client or {},
        )
        await audit.save()
        return audit

    async def list_audit_trails(
        self,
        *,
        teacher_id: str,
        limit: int = 20,
    ) -> list[AuditTrail]:
        return [
            item
            async for item in AuditTrail.Search(
                {"teacher_id": teacher_id},
                limit=limit,
            )
            if isinstance(item, AuditTrail)
        ]

    def teacher_can_access_class(
        self,
        *,
        user: dict[str, Any],
        classroom: dict[str, Any],
    ) -> bool:
        return (
            str(user.get("role") or "") == "teacher"
            and str(classroom.get("teacher_id") or "") == str(user.get("user_id") or "")
        )

    def teacher_can_access_teacher_record(
        self,
        *,
        user: dict[str, Any],
        teacher_id: str,
    ) -> bool:
        return (
            str(user.get("role") or "") == "teacher"
            and str(user.get("user_id") or "") == str(teacher_id or "")
        )


__all__ = [
    "TEACHER_DOMAIN_COLLECTIONS",
    "TeacherAuditAction",
    "PROFILE_FIELD_SCHEMA",
    "SENSITIVE_PROFILE_FIELD_NAMES",
    "KEY_PROFILE_FIELD_NAMES",
    "TeacherOwnedModel",
    "TeacherProfile",
    "TeacherProfileChangeRequest",
    "Homework",
    "HomeworkSubmission",
    "AttendanceActivity",
    "AttendanceRecord",
    "TeachingResource",
    "TeacherHonor",
    "TeacherWorkLog",
    "AuditTrail",
    "TeacherDomainRepository",
]
