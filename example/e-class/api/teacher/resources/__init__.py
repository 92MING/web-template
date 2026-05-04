# -*- coding: utf-8 -*-
"""Formal teacher resource management endpoint."""

import re
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from eclass_api_base import EClassRoute
from teacher_domain import TeachingResource, TeacherDomainRepository


RESOURCE_TAG_DIMENSIONS: tuple[str, ...] = ("学段", "学科", "年级", "版本", "章节")
RESOURCE_VISIBILITIES: frozenset[str] = frozenset({"private", "class", "school", "group", "region"})
RESOURCE_STAT_METRICS: dict[str, str] = {
    "browse": "browse_count",
    "download": "download_count",
    "favorite": "favorite_count",
    "reference": "reference_count",
}


class ResourceCreatePayload(BaseModel):
    title: str
    description: str = ""
    resource_type: str = "file"
    class_ids: list[str] = Field(default_factory=list)
    visibility: str = "private"
    file_refs: list[dict[str, object]] = Field(default_factory=list)
    tags: dict[str, object] = Field(default_factory=dict)
    version: str = ""
    course_objectives_html: str = ""
    course_content_html: str = ""
    evaluation_method_html: str = ""


class ResourceUpdatePayload(BaseModel):
    resource_id: str
    title: str | None = None
    description: str | None = None
    resource_type: str | None = None
    class_ids: list[str] | None = None
    visibility: str | None = None
    file_refs: list[dict[str, object]] | None = None
    tags: dict[str, object] | None = None
    version: str | None = None
    course_objectives_html: str | None = None
    course_content_html: str | None = None
    evaluation_method_html: str | None = None


class ResourceIdPayload(BaseModel):
    resource_id: str


class ResourceStatPayload(BaseModel):
    resource_id: str
    metric: str


class TeacherResourcesRoute(EClassRoute):
    Tags = "Teacher"

    async def _current_teacher_or_403(self, request: Request) -> dict[str, Any]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        if user.get("role") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可操作资源")
        return user

    def _client_context(self, request: Request) -> dict[str, object]:
        return {
            "host": request.client.host if request.client is not None else "",
            "user_agent": request.headers.get("user-agent", ""),
        }

    def _sanitize_html(self, value: str) -> str:
        return re.sub(r"<script\b[^>]*>.*?</script>", "", value or "", flags=re.IGNORECASE | re.DOTALL)

    def _normalize_tags(self, tags: dict[str, object]) -> dict[str, object]:
        return {
            name: str(tags.get(name) or "").strip()
            for name in RESOURCE_TAG_DIMENSIONS
            if str(tags.get(name) or "").strip()
        }

    def _validate_visibility(self, visibility: str) -> str:
        value = str(visibility or "private").strip() or "private"
        if value not in RESOURCE_VISIBILITIES:
            raise HTTPException(status_code=400, detail="无效的共享范围")
        return value

    def _check_class_scope(self, user: dict[str, Any], class_ids: list[str]) -> None:
        repo = TeacherDomainRepository()
        classrooms = self._get_classrooms()
        denied = [
            class_id
            for class_id in class_ids
            if not repo.teacher_can_access_class(user=user, classroom=classrooms.get(class_id, {}))
        ]
        if denied:
            raise HTTPException(status_code=403, detail="无权操作指定班级资源")

    async def _get_owned_resource(self, user: dict[str, Any], resource_id: str) -> TeachingResource:
        try:
            resource = await TeachingResource.SearchOneById(resource_id)
        except ValueError:
            resource = None
        if not isinstance(resource, TeachingResource):
            raise HTTPException(status_code=404, detail="资源不存在")
        if resource.teacher_id != str(user.get("user_id") or ""):
            raise HTTPException(status_code=403, detail="无权操作该资源")
        return resource

    def _resource_payload(self, resource: TeachingResource) -> dict[str, object]:
        return resource.model_dump(mode="json")

    async def get(
        self,
        request: Request,
        stage: str = "",
        subject: str = "",
        grade: str = "",
        version: str = "",
        chapter: str = "",
        visibility: str = "",
        include_deleted: bool = False,
    ) -> dict[str, object]:
        user = await self._current_teacher_or_403(request)
        filters = {
            "学段": stage,
            "学科": subject,
            "年级": grade,
            "版本": version,
            "章节": chapter,
        }
        items: list[dict[str, object]] = []
        query = {"teacher_id": str(user.get("user_id") or "")}
        async for resource in TeachingResource.Search(query):
            if not isinstance(resource, TeachingResource):
                continue
            if not include_deleted and resource.status == "deleted":
                continue
            if visibility and resource.visibility != visibility:
                continue
            if any(value and resource.tags.get(name) != value for name, value in filters.items()):
                continue
            items.append(self._resource_payload(resource))
        items.sort(key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0), reverse=True)
        return {"ok": True, "items": items}

    async def post(self, request: Request, action: str = "create") -> dict[str, object]:
        user = await self._current_teacher_or_403(request)
        body = await request.json()
        raw_payload = body if isinstance(body, dict) else {}
        repo = TeacherDomainRepository()

        if action == "create":
            payload = ResourceCreatePayload.model_validate(raw_payload)
            class_ids = list(dict.fromkeys([item for item in payload.class_ids if item]))
            self._check_class_scope(user, class_ids)
            resource = TeachingResource(
                teacher_id=str(user.get("user_id") or ""),
                school_id=str(user.get("school_id") or ""),
                created_by=str(user.get("user_id") or ""),
                title=payload.title,
                description=payload.description,
                resource_type=payload.resource_type,
                status="active",
                class_ids=class_ids,
                visibility=self._validate_visibility(payload.visibility),
                file_refs=payload.file_refs,
                tags=self._normalize_tags(payload.tags),
                version=payload.version,
                course_objectives_html=self._sanitize_html(payload.course_objectives_html),
                course_content_html=self._sanitize_html(payload.course_content_html),
                evaluation_method_html=self._sanitize_html(payload.evaluation_method_html),
                stats={
                    "browse_count": 0,
                    "download_count": 0,
                    "favorite_count": 0,
                    "reference_count": 0,
                },
            )
            await resource.save()
            await repo.create_audit(
                object_type="TeachingResource",
                object_id=str(resource.id),
                actor_id=str(user.get("user_id") or ""),
                action="create",
                school_id=resource.school_id,
                teacher_id=resource.teacher_id,
                summary="Created teaching resource",
                after=resource.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "resource": self._resource_payload(resource)}

        if action == "update":
            payload = ResourceUpdatePayload.model_validate(raw_payload)
            resource = await self._get_owned_resource(user, payload.resource_id)
            before = resource.model_dump(mode="json")
            if payload.class_ids is not None:
                class_ids = list(dict.fromkeys([item for item in payload.class_ids if item]))
                self._check_class_scope(user, class_ids)
                resource.class_ids = class_ids
            if payload.title is not None:
                resource.title = payload.title
            if payload.description is not None:
                resource.description = payload.description
            if payload.resource_type is not None:
                resource.resource_type = payload.resource_type
            if payload.visibility is not None:
                resource.visibility = self._validate_visibility(payload.visibility)
            if payload.file_refs is not None:
                resource.file_refs = payload.file_refs
            if payload.tags is not None:
                resource.tags = self._normalize_tags(payload.tags)
            if payload.version is not None:
                resource.version = payload.version
            if payload.course_objectives_html is not None:
                resource.course_objectives_html = self._sanitize_html(payload.course_objectives_html)
            if payload.course_content_html is not None:
                resource.course_content_html = self._sanitize_html(payload.course_content_html)
            if payload.evaluation_method_html is not None:
                resource.evaluation_method_html = self._sanitize_html(payload.evaluation_method_html)
            resource.touch(str(user.get("user_id") or ""))
            await resource.save()
            await repo.create_audit(
                object_type="TeachingResource",
                object_id=str(resource.id),
                actor_id=str(user.get("user_id") or ""),
                action="update",
                school_id=resource.school_id,
                teacher_id=resource.teacher_id,
                summary="Updated teaching resource",
                before=before,
                after=resource.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "resource": self._resource_payload(resource)}

        if action == "delete":
            payload = ResourceIdPayload.model_validate(raw_payload)
            resource = await self._get_owned_resource(user, payload.resource_id)
            before = resource.model_dump(mode="json")
            resource.status = "deleted"
            resource.touch(str(user.get("user_id") or ""))
            await resource.save()
            await repo.create_audit(
                object_type="TeachingResource",
                object_id=str(resource.id),
                actor_id=str(user.get("user_id") or ""),
                action="delete",
                school_id=resource.school_id,
                teacher_id=resource.teacher_id,
                summary="Soft-deleted teaching resource",
                before=before,
                after=resource.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "resource": self._resource_payload(resource)}

        if action == "record_stat":
            payload = ResourceStatPayload.model_validate(raw_payload)
            resource = await self._get_owned_resource(user, payload.resource_id)
            stat_key = RESOURCE_STAT_METRICS.get(payload.metric)
            if stat_key is None:
                raise HTTPException(status_code=400, detail="无效的统计指标")
            stats = dict(resource.stats)
            stats[stat_key] = int(stats.get(stat_key, 0)) + 1
            resource.stats = stats
            resource.touch(str(user.get("user_id") or ""))
            await resource.save()
            return {"ok": True, "resource": self._resource_payload(resource)}

        return {"ok": False, "error": "无效的操作"}
