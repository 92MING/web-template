# -*- coding: utf-8 -*-

import time

from fastapi import HTTPException, Request
from pydantic import BaseModel

from eclass_api_base import EClassRoute
from teacher_domain import AttendanceActivity, TeacherDomainRepository, now_ts


class CheckInCreateRequest(BaseModel):
    class_id: str
    course_id: str = ""
    attendance_date: str = ""
    attendance_type: str = "check_in"
    expires_minutes: int = 15
    allow_makeup: bool = False


class CheckInCloseRequest(BaseModel):
    check_in_id: str
    class_id: str


__all__ = ["TeacherCheckInRoute"]


class TeacherCheckInRoute(EClassRoute):
    Tags = "Teacher"

    async def _current_teacher_or_403(self, request: Request) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        if user.get("role") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可操作考勤")
        return user

    def _client_context(self, request: Request) -> dict[str, object]:
        return {
            "host": request.client.host if request.client is not None else "",
            "user_agent": request.headers.get("user-agent", ""),
        }

    async def post(self, request: Request, action: str = "create") -> dict[str, object]:
        user = await self._current_teacher_or_403(request)
        body = await request.json()
        raw_payload = body if isinstance(body, dict) else {}
        repo = TeacherDomainRepository()

        if action == "close":
            payload = CheckInCloseRequest.model_validate(raw_payload)
            classrooms = self._get_classrooms()
            classroom = classrooms.get(payload.class_id, {})
            if not repo.teacher_can_access_class(user=user, classroom=classroom):
                raise HTTPException(status_code=403, detail="无权结束指定班级考勤")

            key = f"class:{payload.class_id}:checkin-activities"
            rows = list(self.shared_dict.get(key, []))
            item: dict[str, object] | None = None
            now = now_ts()
            for row in rows:
                if isinstance(row, dict) and row.get("check_in_id") == payload.check_in_id:
                    row["status"] = "closed"
                    row["ended_at"] = now
                    item = row
                    break

            activity = await AttendanceActivity.SearchOneById(payload.check_in_id)
            if isinstance(activity, AttendanceActivity):
                before = activity.model_dump(mode="json")
                activity.status = "closed"
                activity.ended_at = now
                activity.touch(str(user.get("user_id") or ""))
                await activity.save()
                await repo.create_audit(
                    object_type="AttendanceActivity",
                    object_id=str(activity.id),
                    actor_id=str(user.get("user_id") or ""),
                    action="update",
                    school_id=activity.school_id,
                    teacher_id=activity.teacher_id,
                    summary="Closed attendance activity",
                    before=before,
                    after=activity.model_dump(mode="json"),
                    client=self._client_context(request),
                )
                item = {
                    **activity.model_dump(mode="json"),
                    "check_in_id": str(activity.id),
                }
            if item is None:
                return {"ok": False, "error": "签到活动不存在"}
            self.shared_dict.set(key, rows)
            return {"ok": True, "activity": item}

        payload = CheckInCreateRequest.model_validate(raw_payload)
        classrooms = self._get_classrooms()
        classroom = classrooms.get(payload.class_id, {})
        if not repo.teacher_can_access_class(user=user, classroom=classroom):
            raise HTTPException(status_code=403, detail="无权向指定班级发起考勤")

        teacher_id = str(user.get("user_id") or "")
        now = now_ts()
        activity = AttendanceActivity(
            teacher_id=teacher_id,
            school_id=str(user.get("school_id") or ""),
            created_by=teacher_id,
            class_id=payload.class_id,
            course_id=payload.course_id,
            attendance_date=payload.attendance_date,
            attendance_type=payload.attendance_type,
            status="open",
            starts_at=now,
            expires_at=now + payload.expires_minutes * 60,
            allow_makeup=payload.allow_makeup,
        )
        await activity.save()
        check_in_id = str(activity.id)
        item = {
            "check_in_id": check_in_id,
            "class_id": payload.class_id,
            "course_id": payload.course_id,
            "attendance_date": payload.attendance_date,
            "attendance_type": payload.attendance_type,
            "created_by": user.get("user_id"),
            "created_at": now,
            "expires_at": activity.expires_at,
            "status": "open",
            "allow_makeup": payload.allow_makeup,
        }
        key = f"class:{payload.class_id}:checkin-activities"
        rows = list(self.shared_dict.get(key, []))
        rows.append(item)
        self.shared_dict.set(key, rows)
        await repo.create_audit(
            object_type="AttendanceActivity",
            object_id=str(activity.id),
            actor_id=teacher_id,
            action="create",
            school_id=activity.school_id,
            teacher_id=teacher_id,
            summary="Created attendance activity",
            after=activity.model_dump(mode="json"),
            client=self._client_context(request),
        )
        return {"ok": True, "activity": item}

    async def get(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self._current_teacher_or_403(request)
        repo = TeacherDomainRepository()
        classroom = self._get_classrooms().get(class_id) or {}
        if not repo.teacher_can_access_class(user=user, classroom=classroom):
            raise HTTPException(status_code=403, detail="无权查看指定班级考勤")

        key = f"class:{class_id}:checkin-activities"
        rows = list(self.shared_dict.get(key, []))
        # Auto-close expired
        now = time.time()
        for row in rows:
            if row.get("status") == "open" and row.get("expires_at") and now > row.get("expires_at"):
                row["status"] = "closed"
        seen_ids = {str(row.get("check_in_id") or "") for row in rows if isinstance(row, dict)}
        async for activity in AttendanceActivity.Search({"class_id": class_id}):
            if not isinstance(activity, AttendanceActivity):
                continue
            if activity.teacher_id != str(user.get("user_id") or ""):
                continue
            if str(activity.id) in seen_ids:
                continue
            rows.append({
                **activity.model_dump(mode="json"),
                "check_in_id": str(activity.id),
            })
        self.shared_dict.set(key, rows)
        return {"ok": True, "activities": sorted(rows, key=lambda x: x.get("created_at", 0), reverse=True)}
