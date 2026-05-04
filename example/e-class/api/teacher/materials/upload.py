import time
from pathlib import Path

from fastapi import Form, HTTPException, Request, UploadFile

from eclass_api_base import EClassRoute
from core.storage.config import StorageConfig
from teacher_domain import TeacherDomainRepository, TeachingResource


def _get_object_client():
    sc = StorageConfig.Global()
    if sc is None:
        raise RuntimeError("StorageConfig not initialized")
    return sc.get_object_client()


class TeacherMaterialUploadRoute(EClassRoute):
    Tags = "Teacher"

    def _client_context(self, request: Request) -> dict[str, object]:
        return {
            "host": request.client.host if request.client is not None else "",
            "user_agent": request.headers.get("user-agent", ""),
        }

    async def post(
        self,
        request: Request,
        file: UploadFile,
        class_id: str = Form(...),
        title: str = Form(...),
    ) -> dict[str, object]:
        user = await self.get_current_user(request)
        if not user:
            raise HTTPException(status_code=403, detail="未登录")
        if user.get("role") != "teacher":
            raise HTTPException(status_code=403, detail="仅老师可上传资源")
        repo = TeacherDomainRepository()
        classroom = self._get_classrooms().get(class_id, {})
        if not repo.teacher_can_access_class(user=user, classroom=classroom):
            raise HTTPException(status_code=403, detail="无权向指定班级上传资源")

        safe_name = Path(file.filename or "material.bin").name
        object_name = f"materials/{class_id}/{int(time.time())}-{safe_name}"
        data = await file.read()
        client = _get_object_client()
        meta = await client.put(data, object_name=object_name, content_type=file.content_type)
        resource = TeachingResource(
            teacher_id=str(user.get("user_id") or ""),
            school_id=str(user.get("school_id") or ""),
            created_by=str(user.get("user_id") or ""),
            title=title,
            resource_type="file",
            status="active",
            class_ids=[class_id],
            visibility="class",
            file_refs=[{
                "name": safe_name,
                "object_name": object_name,
                "content_type": file.content_type or "",
                "size": len(data),
            }],
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
            summary="Uploaded teaching material",
            after=resource.model_dump(mode="json"),
            client=self._client_context(request),
        )
        material = {
            "title": title,
            "filename": safe_name,
            "object_name": object_name,
            "meta": meta,
            "resource_id": str(resource.id),
        }
        key = f"class:{class_id}:materials"
        rows = list(self.shared_dict.get(key, []))
        rows.append(material)
        self.shared_dict.set(key, rows)
        return {"ok": True, "material": material}
