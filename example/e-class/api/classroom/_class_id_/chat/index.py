import time
import uuid
from fastapi import Request, UploadFile, File
from pydantic import BaseModel
from eclass_api_base import EClassRoute
from core.storage.config import StorageConfig


def _get_object_client():
    sc = StorageConfig.Global()
    if sc is None:
        raise RuntimeError("StorageConfig not initialized")
    return sc.get_object_client()


class ChatMessageRequest(BaseModel):
    sender_id: str = ""
    text: str = ""


class ClassroomChatRoute(EClassRoute):
    Tags = "Classroom"

    async def _read_message_payload(self, request: Request) -> ChatMessageRequest:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = await request.json()
            if isinstance(payload, dict):
                return ChatMessageRequest.model_validate(payload)
            return ChatMessageRequest()

        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            return ChatMessageRequest(
                sender_id=str(form.get("sender_id") or ""),
                text=str(form.get("text") or ""),
            )

        return ChatMessageRequest()

    async def post(self, request: Request, class_id: str, text: str = "", sender_id: str = "", file: UploadFile | None = File(None)) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录"}

        payload = await self._read_message_payload(request)
        resolved_text = payload.text or text
        resolved_sender_id = payload.sender_id or sender_id

        key = f"class:{class_id}:chat"
        rows = list(self.shared_dict.get(key, []))

        msg_id = str(uuid.uuid4())[:8]
        item = {
            "id": msg_id,
            "timestamp": int(time.time()),
            "sender_id": user.get("user_id", resolved_sender_id or "unknown"),
            "sender_name": user.get("name", user.get("user_id", "unknown")),
            "text": resolved_text,
            "attachments": [],
        }

        if file and file.filename:
            import re
            safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', file.filename)
            object_name = f"classroom/{class_id}/files/{int(time.time())}-{safe_name}"
            data = await file.read()
            client = _get_object_client()
            meta = await client.put(data, object_name=object_name, content_type=file.content_type or "application/octet-stream")
            item["attachments"].append({
                "name": safe_name,
                "url": f"/api/classroom/{class_id}/files/{object_name.split('/')[-1]}",
                "object_name": object_name,
                "type": file.content_type or "application/octet-stream",
                "size": len(data),
            })

        rows.append(item)
        self.shared_dict.set(key, rows)
        return {"ok": True, "message": item}

    async def get(self, request: Request, class_id: str, q: str = "") -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            return {"ok": False, "error": "未登录", "messages": []}

        rows = list(self.shared_dict.get(f"class:{class_id}:chat", []))
        if q:
            q_lower = q.lower()
            rows = [r for r in rows if q_lower in r.get("text", "").lower() or q_lower in r.get("sender_name", "").lower()]

        return {"ok": True, "messages": rows}
