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


class TeacherMaterialUploadRoute(EClassRoute):
    Tags = "Teacher"

    async def post(self, file: UploadFile, class_id: str = Form(...), title: str = Form(...)) -> dict[str, object]:
        safe_name = Path(file.filename or "material.bin").name
        object_name = f"materials/{class_id}/{int(time.time())}-{safe_name}"
        data = await file.read()
        client = _get_object_client()
        meta = await client.put(data, object_name=object_name, content_type=file.content_type)
        material = {"title": title, "filename": safe_name, "object_name": object_name, "meta": meta}
        key = f"class:{class_id}:materials"
        rows = list(self.shared_dict.get(key, []))
        rows.append(material)
        self.shared_dict.set(key, rows)
        return {"ok": True, "material": material}
