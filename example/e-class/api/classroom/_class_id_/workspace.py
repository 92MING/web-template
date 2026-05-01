# -*- coding: utf-8 -*-

import time
from typing import Any

from fastapi import Request
from pydantic import BaseModel

from eclass_api_base import EClassRoute


class WorkspaceActionRequest(BaseModel):
    action: str = ""


__all__ = ["ClassroomWorkspaceRoute"]


class ClassroomWorkspaceRoute(EClassRoute):
    Tags = "Classroom"

    @staticmethod
    def _submission_reviewed(row: dict[str, Any]) -> bool:
        return row.get("grade") is not None or bool(str(row.get("feedback") or "").strip())

    def _get_homework(self, class_id: str) -> list[dict[str, Any]]:
        return list(self.shared_dict.get(f"class:{class_id}:homework", []))

    def _get_meetings(self, class_id: str) -> list[dict[str, Any]]:
        return list(self.shared_dict.get(f"class:{class_id}:meetings", []))

    def _get_submissions(self, class_id: str) -> list[dict[str, Any]]:
        return list(self.shared_dict.get(f"class:{class_id}:submissions", []))

    def _can_access_classroom(self, user: dict[str, Any], classroom: dict[str, Any]) -> bool:
        user_id = str(user.get("user_id") or "")
        role = str(user.get("role") or "")
        teacher_id = str(classroom.get("teacher_id") or "")
        member_ids = {str(item) for item in classroom.get("members", [])}
        return (role == "teacher" and teacher_id == user_id) or user_id in member_ids

    def _serialize_submission(self, class_id: str, row: dict[str, Any]) -> dict[str, Any]:
        users = self._get_users()
        student_id = str(row.get("student_id") or "")
        student = users.get(student_id) or {}
        object_name = str(row.get("object_name") or "")
        filename = str(row.get("filename") or object_name.split("/")[-1] or "submission.bin")
        basename = object_name.split("/")[-1] if object_name else filename
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        return {
            "submission_id": str(row.get("submission_id") or basename),
            "student_id": student_id,
            "student_name": str(student.get("nickname") or student.get("name") or student_id or "Student"),
            "filename": filename,
            "url": str(row.get("url") or f"/api/classroom/{class_id}/files/{basename}"),
            "content_type": str(row.get("content_type") or meta.get("content_type") or "application/octet-stream"),
            "size": int(row.get("size") or meta.get("size") or 0),
            "created_at": row.get("created_at"),
            "grade": row.get("grade"),
            "feedback": row.get("feedback"),
            "reviewed_at": row.get("reviewed_at"),
        }

    def _serialize_homework(
        self,
        class_id: str,
        homework_rows: list[dict[str, Any]],
        submission_rows: list[dict[str, Any]],
        *,
        current_user_id: str,
        can_manage: bool,
    ) -> list[dict[str, Any]]:
        submissions_by_homework: dict[str, list[dict[str, Any]]] = {}
        current_submission_by_homework: dict[str, dict[str, Any]] = {}

        for row in submission_rows:
            homework_id = str(row.get("homework_id") or "")
            if not homework_id:
                continue
            submission = self._serialize_submission(class_id, row)
            submissions_by_homework.setdefault(homework_id, []).append(submission)
            if str(row.get("student_id") or "") == current_user_id:
                previous = current_submission_by_homework.get(homework_id)
                if previous is None or str(submission.get("created_at") or "") >= str(previous.get("created_at") or ""):
                    current_submission_by_homework[homework_id] = submission

        for items in submissions_by_homework.values():
            items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)

        payload: list[dict[str, Any]] = []
        for index, row in enumerate(homework_rows, start=1):
            homework_id = str(row.get("id") or row.get("homework_id") or f"hw-{index}")
            my_submission = current_submission_by_homework.get(homework_id)
            item = {
                "id": homework_id,
                "title": str(row.get("title") or homework_id),
                "description": str(row.get("description") or ""),
                "due_at": row.get("due_at") or row.get("due_date"),
                "created_at": row.get("created_at"),
                "submission_count": len(submissions_by_homework.get(homework_id, [])),
                "submission": my_submission,
                "status": "published" if can_manage else ("graded" if my_submission and self._submission_reviewed(my_submission) else "submitted" if my_submission else "pending"),
            }
            if can_manage:
                item["submissions"] = submissions_by_homework.get(homework_id, [])
            payload.append(item)

        payload.sort(key=lambda item: str(item.get("due_at") or "9999"))
        return payload

    def _serialize_meetings(self, class_id: str, meeting_rows: list[dict[str, Any]], *, can_manage: bool) -> list[dict[str, Any]]:
        meetings = [dict(item) for item in meeting_rows]
        rtc = self.shared_dict.get(f"class:{class_id}:rtc")
        rtc_room_id = str((rtc or {}).get("room_id") or "")
        rtc_open = bool(rtc and rtc.get("status") == "open" and rtc_room_id)

        if rtc_open:
            bound = False
            for meeting in meetings:
                meeting_room_id = str(meeting.get("room_id") or "")
                if meeting_room_id == rtc_room_id or (meeting.get("status") == "live" and not meeting_room_id):
                    meeting["room_id"] = rtc_room_id
                    meeting["status"] = "live"
                    meeting["started_at"] = meeting.get("started_at") or rtc.get("started_at")
                    bound = True
                    break
            if not bound:
                meetings.insert(0, {
                    "meeting_id": rtc_room_id,
                    "title": "线上课堂",
                    "description": "",
                    "status": "live",
                    "room_id": rtc_room_id,
                    "started_at": rtc.get("started_at"),
                    "scheduled_at": None,
                    "can_manage": can_manage,
                    "create_token": None,
                    "join_token": f"join-{rtc_room_id}",
                })

        payload: list[dict[str, Any]] = []
        for row in meetings:
            room_id = str(row.get("room_id") or "")
            status = str(row.get("status") or "scheduled")
            item = {
                "meeting_id": str(row.get("meeting_id") or row.get("room_id") or f"mtg-{len(payload) + 1}"),
                "title": str(row.get("title") or "线上课堂"),
                "description": str(row.get("description") or ""),
                "status": status,
                "room_id": room_id or None,
                "started_at": row.get("started_at"),
                "scheduled_at": row.get("scheduled_at"),
                "can_manage": bool(row.get("can_manage") or can_manage),
                "create_token": row.get("create_token") if can_manage and not room_id and status != "ended" else None,
                "join_token": row.get("join_token") or (f"join-{room_id}" if room_id and status == "live" else None),
                "whiteboard_snapshot": row.get("whiteboard_snapshot"),
                "whiteboard_updated_at": row.get("whiteboard_updated_at"),
            }
            payload.append(item)

        payload.sort(key=lambda item: str(item.get("scheduled_at") or item.get("started_at") or "9999"))
        return payload

    def _build_calendar_payload(self, homework: list[dict[str, Any]], meetings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in homework:
            items.append({
                "kind": "homework",
                "title": row.get("title"),
                "start": row.get("due_at"),
                "target_id": row.get("id"),
                "status": row.get("status"),
            })
        for row in meetings:
            items.append({
                "kind": "meeting",
                "title": row.get("title"),
                "start": row.get("started_at") or row.get("scheduled_at"),
                "target_id": row.get("meeting_id"),
                "status": row.get("status"),
            })
        items.sort(key=lambda item: str(item.get("start") or "9999"))
        return items

    async def get(self, request: Request, class_id: str) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        classroom = self._get_classrooms().get(class_id)
        if not classroom:
            return {"ok": False, "error": "教室不存在"}

        if not self._can_access_classroom(user, classroom):
            return {"ok": False, "error": "无权限"}

        user_id = str(user.get("user_id") or "")
        role = str(user.get("role") or "student")
        can_manage = role == "teacher" and str(classroom.get("teacher_id") or "") == user_id

        homework = self._serialize_homework(
            class_id,
            self._get_homework(class_id),
            self._get_submissions(class_id),
            current_user_id=user_id,
            can_manage=can_manage,
        )
        meetings = self._serialize_meetings(class_id, self._get_meetings(class_id), can_manage=can_manage)
        calendar = self._build_calendar_payload(homework, meetings)

        return {
            "ok": True,
            "classroom": classroom,
            "can_manage": can_manage,
            "homework": homework,
            "meetings": meetings,
            "calendar": calendar,
        }

    async def post(self, request: Request, class_id: str, payload: WorkspaceActionRequest) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        classroom = self._get_classrooms().get(class_id)
        if not classroom:
            return {"ok": False, "error": "教室不存在"}

        if not self._can_access_classroom(user, classroom):
            return {"ok": False, "error": "无权限"}

        can_manage = str(user.get("role") or "") == "teacher" and str(classroom.get("teacher_id") or "") == str(user.get("user_id") or "")
        if not can_manage:
            return {"ok": False, "error": "仅老师可操作课堂工作区"}

        action = payload.action
        body = await request.json()

        if action == "create_homework":
            key = f"class:{class_id}:homework"
            rows = list(self.shared_dict.get(key, []))
            item = {
                "id": f"hw-{len(rows) + 1}",
                "title": body.get("title", ""),
                "description": body.get("description", ""),
                "due_at": body.get("due_at"),
                "created_at": time.time(),
            }
            rows.append(item)
            self.shared_dict.set(key, rows)
            return {"ok": True, "homework": item}

        if action == "create_meeting":
            key = f"class:{class_id}:meetings"
            rows = list(self.shared_dict.get(key, []))
            meeting_id = f"mtg-{int(time.time())}"
            item = {
                "meeting_id": meeting_id,
                "title": body.get("title", ""),
                "description": body.get("description", ""),
                "status": "scheduled" if body.get("scheduled_at") else "live",
                "room_id": None,
                "started_at": time.time() if not body.get("scheduled_at") else None,
                "scheduled_at": body.get("scheduled_at"),
                "can_manage": user.get("role") == "teacher",
                "create_token": f"create-{meeting_id}",
                "join_token": None,
            }
            rows.append(item)
            self.shared_dict.set(key, rows)
            return {"ok": True, "meeting": item}

        if action == "activate_meeting":
            meeting_id = str(body.get("meeting_id") or "")
            room_id = str(body.get("room_id") or "")
            if not meeting_id or not room_id:
                return {"ok": False, "error": "缺少会议参数"}
            key = f"class:{class_id}:meetings"
            rows = list(self.shared_dict.get(key, []))
            meeting = None
            for row in rows:
                if str(row.get("meeting_id") or "") != meeting_id:
                    continue
                row["status"] = "live"
                row["room_id"] = room_id
                row["room_password"] = body.get("room_password")
                row["started_at"] = row.get("started_at") or time.time()
                row["join_token"] = f"join-{room_id}"
                meeting = row
                break
            if meeting is None:
                return {"ok": False, "error": "会议不存在"}
            self.shared_dict.set(key, rows)
            self.shared_dict.set(f"class:{class_id}:rtc", {
                "class_id": class_id,
                "room_id": room_id,
                "status": "open",
                "started_by": user.get("user_id"),
                "started_at": meeting.get("started_at") or time.time(),
                "participants": [],
            })
            return {"ok": True, "meeting": meeting}

        if action == "save_whiteboard":
            meeting_id = str(body.get("meeting_id") or "")
            snapshot = body.get("whiteboard_snapshot")
            key = f"class:{class_id}:meetings"
            rows = list(self.shared_dict.get(key, []))
            for row in rows:
                if str(row.get("meeting_id") or "") != meeting_id:
                    continue
                row["whiteboard_snapshot"] = snapshot
                row["whiteboard_updated_at"] = time.time()
                self.shared_dict.set(key, rows)
                return {"ok": True, "meeting": row}
            return {"ok": False, "error": "会议不存在"}

        if action == "review_submission":
            submission_id = str(body.get("submission_id") or "")
            if not submission_id:
                return {"ok": False, "error": "缺少提交参数"}
            key = f"class:{class_id}:submissions"
            rows = list(self.shared_dict.get(key, []))
            for row in rows:
                if str(row.get("submission_id") or "") != submission_id:
                    continue
                grade = body.get("grade")
                feedback = str(body.get("feedback") or "").strip()
                row["grade"] = None if grade in (None, "") else str(grade)
                row["feedback"] = feedback or None
                row["reviewed_at"] = time.time()
                row["reviewed_by"] = user.get("user_id")
                self.shared_dict.set(key, rows)
                return {"ok": True, "submission": self._serialize_submission(class_id, row)}
            return {"ok": False, "error": "提交不存在"}

        if action == "end_meeting":
            meeting_id = body.get("meeting_id")
            key = f"class:{class_id}:meetings"
            rows = list(self.shared_dict.get(key, []))
            for row in rows:
                if row.get("meeting_id") == meeting_id:
                    row["status"] = "ended"
                    row["join_token"] = None
                    row["create_token"] = None
            self.shared_dict.set(key, rows)
            # Also close RTC if matching
            rtc = self.shared_dict.get(f"class:{class_id}:rtc")
            if rtc and (rtc.get("room_id") == meeting_id or any(row.get("meeting_id") == meeting_id and row.get("room_id") == rtc.get("room_id") for row in rows)):
                rtc["status"] = "closed"
                rtc["participants"] = []
                self.shared_dict.set(f"class:{class_id}:rtc", rtc)
            return {"ok": True}

        return {"ok": False, "error": "未知的操作"}
