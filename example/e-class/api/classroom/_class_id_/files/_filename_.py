from fastapi import Request
from fastapi.responses import StreamingResponse
from eclass_api_base import EClassRoute
from core.storage.config import StorageConfig


def _get_object_client():
    sc = StorageConfig.Global()
    if sc is None:
        raise RuntimeError("StorageConfig not initialized")
    return sc.get_object_client()


class ClassroomFilesRoute(EClassRoute):
    Tags = "Classroom"
    ResponseClass = StreamingResponse

    async def get(self, request: Request, class_id: str, filename: str):
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        classroom = self._get_classrooms().get(class_id)
        if not classroom:
            return {"ok": False, "error": "教室不存在"}

        user_id = str(user.get("user_id") or "")
        role = str(user.get("role") or "")
        teacher_id = str(classroom.get("teacher_id") or "")
        member_ids = {str(item) for item in classroom.get("members", [])}
        can_access = (role == "teacher" and teacher_id == user_id) or user_id in member_ids
        if not can_access:
            return {"ok": False, "error": "无权限"}

        chat_rows = list(self.shared_dict.get(f"class:{class_id}:chat", []))
        submission_rows = list(self.shared_dict.get(f"class:{class_id}:submissions", []))
        object_name = None
        content_type = "application/octet-stream"
        for row in chat_rows:
            for att in row.get("attachments", []):
                if att.get("name") == filename or att.get("url", "").endswith(f"/{filename}"):
                    object_name = att.get("object_name")
                    content_type = att.get("type", "application/octet-stream")
                    break
            if object_name:
                break

        if not object_name:
            for row in submission_rows:
                row_object_name = str(row.get("object_name") or "")
                row_basename = row_object_name.split("/")[-1] if row_object_name else ""
                row_url = str(row.get("url") or "")
                if row.get("filename") == filename or row_basename == filename or row_url.endswith(f"/{filename}"):
                    object_name = row_object_name
                    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
                    content_type = str(row.get("content_type") or meta.get("content_type") or "application/octet-stream")
                    break

        if not object_name:
            # Fallback: try direct path
            object_name = f"classroom/{class_id}/files/{filename}"

        client = _get_object_client()

        async def _stream():
            async for chunk in client.get(object_name, chunk_size=65536):
                yield chunk

        headers = {
            "Content-Disposition": f'inline; filename="{filename}"',
        }
        return StreamingResponse(_stream(), media_type=content_type, headers=headers)
