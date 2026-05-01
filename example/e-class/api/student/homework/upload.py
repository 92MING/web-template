import time
from pathlib import Path

from fastapi import Form, UploadFile

from eclass_api_base import EClassRoute
from core.storage.config import StorageConfig


def _get_object_client():
    sc = StorageConfig.Global()
    if sc is None:
        raise RuntimeError("StorageConfig not initialized")
    return sc.get_object_client()


class StudentHomeworkUploadRoute(EClassRoute):
    Tags = "Student"

    async def post(
        self,
        file: UploadFile,
        student_id: str = Form(...),
        class_id: str = Form(...),
        homework_id: str = Form(...),
    ) -> dict[str, object]:
        safe_name = Path(file.filename or "submission.bin").name
        object_name = f"homework/{class_id}/{homework_id}/{student_id}-{int(time.time())}-{safe_name}"
        data = await file.read()
        client = _get_object_client()
        meta = await client.put(data, object_name=object_name, content_type=file.content_type)
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        submission = {
            "submission_id": Path(object_name).stem,
            "student_id": student_id,
            "class_id": class_id,
            "homework_id": homework_id,
            "filename": safe_name,
            "object_name": object_name,
            "meta": meta,
            "content_type": file.content_type or "application/octet-stream",
            "size": len(data),
            "created_at": created_at,
            "url": f"/api/classroom/{class_id}/files/{object_name.split('/')[-1]}",
            "grade": None,
            "feedback": None,
        }
        submissions_key = f"class:{class_id}:submissions"
        submissions = list(self.shared_dict.get(submissions_key, []))
        submissions.append(submission)
        self.shared_dict.set(submissions_key, submissions)
        return {"ok": True, "submission": submission}
