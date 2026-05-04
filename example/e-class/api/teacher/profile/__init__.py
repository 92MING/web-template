# -*- coding: utf-8 -*-
"""Teacher one-person-one-file profile endpoint."""

from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from eclass_api_base import EClassRoute
from teacher_domain import TeacherDomainRepository, TeacherProfileChangeRequest


class ProfileChangePayload(BaseModel):
    changes: dict[str, object] = Field(default_factory=dict)
    reason: str = ""


class ProfilePrivacyPayload(BaseModel):
    privacy_settings: dict[str, object] = Field(default_factory=dict)


class ProfileReviewPayload(BaseModel):
    change_id: str
    review_reason: str = ""


class TeacherProfileRoute(EClassRoute):
    Tags = "Teacher"

    def _client_context(self, request: Request) -> dict[str, object]:
        return {
            "host": request.client.host if request.client is not None else "",
            "user_agent": request.headers.get("user-agent", ""),
        }

    async def _current_user_or_403(self, request: Request) -> dict[str, Any]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        return user

    async def get(self, request: Request, action: str = "me", view: str = "self") -> dict[str, object]:
        user = await self._current_user_or_403(request)
        repo = TeacherDomainRepository()

        if action == "schema":
            return {"ok": True, "schema": list(repo.get_profile_schema())}

        if str(user.get("role") or "") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可访问本人档案")

        profile = await repo.ensure_teacher_profile(user)
        reveal_sensitive = view != "masked"
        data = profile.model_dump(mode="json")
        data["field_groups"] = repo.mask_profile_fields(
            profile.field_groups,
            reveal_sensitive=reveal_sensitive,
        )

        if action == "me":
            return {"ok": True, "profile": data}

        if action == "changes":
            changes = [
                item.model_dump(mode="json")
                async for item in TeacherProfileChangeRequest.Search(
                    {"teacher_id": str(user.get("user_id") or "")},
                    limit=50,
                )
                if isinstance(item, TeacherProfileChangeRequest)
            ]
            return {"ok": True, "changes": changes}

        return {"ok": False, "error": "无效的操作"}

    async def post(
        self,
        request: Request,
        action: str = "submit_change",
    ) -> dict[str, object]:
        user = await self._current_user_or_403(request)
        repo = TeacherDomainRepository()
        raw_payload = await request.json()
        body = raw_payload if isinstance(raw_payload, dict) else {}

        if action == "submit_change":
            if str(user.get("role") or "") != "teacher":
                raise HTTPException(status_code=403, detail="仅老师可提交本人档案变更")
            req = ProfileChangePayload.model_validate(body)
            change, errors = await repo.submit_profile_change(
                user=user,
                changes=req.changes,
                reason=req.reason,
                client=self._client_context(request),
            )
            if errors:
                return {"ok": False, "validation_errors": errors}
            assert change is not None
            return {"ok": True, "change": change.model_dump(mode="json")}

        if action == "set_privacy":
            if str(user.get("role") or "") != "teacher":
                raise HTTPException(status_code=403, detail="仅老师可设置本人隐私")
            req = ProfilePrivacyPayload.model_validate(body)
            profile = await repo.ensure_teacher_profile(user)
            before = profile.model_dump(mode="json")
            profile.privacy_settings = req.privacy_settings
            profile.touch(str(user.get("user_id") or ""))
            await profile.save()
            await repo.create_audit(
                object_type="TeacherProfile",
                object_id=str(profile.id),
                actor_id=str(user.get("user_id") or ""),
                action="update",
                school_id=profile.school_id,
                teacher_id=profile.teacher_id,
                summary="Updated teacher profile privacy settings",
                before=before,
                after=profile.model_dump(mode="json"),
                client=self._client_context(request),
            )
            return {"ok": True, "profile": profile.model_dump(mode="json")}

        if action == "approve_change":
            req = ProfileReviewPayload.model_validate(body)
            change = await repo.approve_profile_change(
                reviewer=user,
                change_id=req.change_id,
                review_reason=req.review_reason,
                client=self._client_context(request),
            )
            if change is None:
                raise HTTPException(status_code=403, detail="无权审批或变更不存在")
            return {"ok": True, "change": change.model_dump(mode="json")}

        if action == "reject_change":
            req = ProfileReviewPayload.model_validate(body)
            if not req.review_reason.strip():
                return {"ok": False, "error": "驳回必须填写理由"}
            change = await repo.reject_profile_change(
                reviewer=user,
                change_id=req.change_id,
                review_reason=req.review_reason,
                client=self._client_context(request),
            )
            if change is None:
                raise HTTPException(status_code=403, detail="无权审批或变更不存在")
            return {"ok": True, "change": change.model_dump(mode="json")}

        return {"ok": False, "error": "无效的操作"}
