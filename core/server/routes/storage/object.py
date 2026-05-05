# -*- coding: utf-8 -*-





import base64

import fnmatch

import json

import time



from datetime import datetime, timezone

from typing import Any

from urllib.parse import quote



from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile

from fastapi.responses import Response

from pydantic import BaseModel, Field



from ...app import internal_admin_path, on_before_app_created

from ...data_types.config import Config

from .._office_preview import (

    office_preview_cache_key,

    office_preview_cache_paths,

    office_preview_kind,

    office_preview_payload,

    presentation_preview_payload,

)



from ._common import (

    _section_client_names,

    breadcrumbs,

    get_backend_type,

    get_storage_config,

    infer_content_type,

    jsonable_value,

    normalize_object_path,

    parent_prefix,

    storage_html_response,

    to_iso_ts,

    ttl_payload,

)

from ._models import (

    ObjectBucketsResponse,

    ObjectBucketDeleteResponse,

    ObjectBucketDescriptor,

    ObjectBucketWriteResponse,

    ObjectConfigResponse,

    ObjectDeleteManyResponse,

    ObjectDeleteResponse,

    ObjectExpireResponse,

    ObjectFolderCreateResponse,

    ObjectItem,

    ObjectItemsResponse,

    ObjectMetadataUpdateResponse,

    ObjectOfficePreviewResponse,

    ObjectPathTransferResponse,

    ObjectUploadResponse,

    ObjectWriteResponse,

    StorageCleanupResponse,

    StorageClientsResponse,

)





FOLDER_MARKER_NAME = ".proj_folder"


def _internal_admin_path(path: str = "") -> str:

    return Config.GetConfig().server_config.get_internal_admin_path(path)

ARCHIVE_EXTENSIONS = {"zip", "tar", "gz", "bz2", "7z", "rar", "xz"}

WORD_EXTENSIONS = {"doc", "docx", "odt", "wps", "pages", "hwp", "hwpx"}

PRESENTATION_EXTENSIONS = {"ppt", "pptx", "odp", "key"}

SPREADSHEET_EXTENSIONS = {"xls", "xlsx", "xlsm", "xltx", "xltm", "ods", "numbers", "csv", "tsv"}

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico", "avif"}

VIDEO_EXTENSIONS = {"mp4", "webm", "ogg", "mov", "avi", "mkv"}

AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "flac", "aac", "wma", "m4a"}

EXECUTABLE_EXTENSIONS = {"exe", "msi", "bat", "cmd", "com", "ps1", "sh", "bash", "zsh"}

BINARY_EXTENSIONS = {"bin", "dll", "so", "dylib", "a", "lib", "o", "obj", "dat", "pak", "wasm", "class"}

CODE_EXTENSIONS = {

    "js", "ts", "jsx", "tsx", "rb", "go", "rs", "java", "c", "cpp", "h", "hpp", "css", "html", "htm", "xml",

    "vue", "svelte", "scss", "less", "sass", "lua", "php", "pl", "r", "swift", "kt", "kts", "dart", "erl", "hrl",

    "hs", "scala", "groovy", "sql", "graphql", "proto", "py", "pyi", "ipynb",

}

TEXT_EXTENSIONS = {

    "txt", "md", "markdown", "json", "jsonl", "geojson", "yaml", "yml", "toml", "ini", "cfg", "conf", "env", "log",

    "csv", "tsv",

}





class ObjectExpireBody(BaseModel):

    expire_seconds: float | None = None





class ObjectMetadataBody(BaseModel):

    metadata: dict[str, Any] = Field(default_factory=dict)

    merge: bool = True





class ObjectWriteBody(BaseModel):

    mode: str = Field(default="text", pattern="^(text|base64)$")

    value: str = ""

    content_type: str | None = None

    metadata: dict[str, Any] | None = None

    preserve_metadata: bool = True

    preserve_ttl: bool = True





class ObjectFolderCreateBody(BaseModel):

    path: str

    metadata: dict[str, Any] = Field(default_factory=dict)

    overwrite: bool = False





class ObjectCopyMoveBody(BaseModel):

    source_client: str | None = None

    source_path: str

    target_path: str

    overwrite: bool = False





class ObjectDeleteManyBody(BaseModel):

    paths: list[str] = Field(default_factory=list)





class ObjectBucketCreateBody(BaseModel):

    name: str = Field(min_length=1)

    bucket: str = Field(min_length=1)

    folder: str | None = None

    root_path: str | None = None





class ObjectBucketUpdateBody(BaseModel):

    new_name: str | None = None

    bucket: str | None = None

    folder: str | None = None

    root_path: str | None = None





def _get_exact_object_config(client_name: str | None) -> tuple[str, Any]:

    section = get_storage_config().object

    requested_name = str(client_name or "default").strip() or "default"

    if requested_name in type(section).model_fields:

        config = getattr(section, requested_name, None)

        if config is not None:

            return requested_name, config

    if requested_name in section.extra:

        config = section.extra.get(requested_name)

        if config is not None:

            return requested_name, config

    raise HTTPException(404, f"Object client '{requested_name}' not found")





def _get_exact_object_client(client_name: str | None) -> tuple[str, Any, Any]:

    section = get_storage_config().object

    resolved_name, config = _get_exact_object_config(client_name)

    client = section.get_client(resolved_name, fallback="", fuzzy=False)

    return resolved_name, config, client





def _normalize_optional_prefix(prefix: str | None) -> str:

    raw = str(prefix or "").replace("\\", "/").strip().lstrip("/")

    if not raw:

        return ""

    normalized = normalize_object_path(raw.rstrip("/"))

    return normalized + "/"





def _normalize_folder_path(path: str) -> str:

    raw = str(path or "").replace("\\", "/").strip().lstrip("/")

    if not raw:

        raise HTTPException(400, "Folder path is required.")

    normalized = normalize_object_path(raw.rstrip("/"))

    return normalized + "/"





def _normalize_any_path(path: str) -> str:

    raw = str(path or "").replace("\\", "/").strip().lstrip("/")

    if not raw:

        raise HTTPException(400, "Object path is required.")

    if raw.endswith("/"):

        return _normalize_folder_path(raw)

    return normalize_object_path(raw)





def _is_folder_path(path: str) -> bool:

    return str(path or "").endswith("/")





def _folder_marker_path(folder_path: str) -> str:

    return _normalize_folder_path(folder_path) + FOLDER_MARKER_NAME





def _is_folder_marker(path: str) -> bool:

    return path == FOLDER_MARKER_NAME or path.endswith("/" + FOLDER_MARKER_NAME)





def _folder_path_from_marker(path: str) -> str:

    return path[: -len(FOLDER_MARKER_NAME)]





def _metadata_lookup_path(path: str) -> str:

    normalized = _normalize_any_path(path)

    return _folder_marker_path(normalized) if _is_folder_path(normalized) else normalized





def _ttl_seconds_from_meta(meta: dict[str, Any]) -> float | None:

    expire_at = meta.get("expire_at")

    if expire_at is None:

        return None

    try:

        return max(0.0, float(expire_at) - time.time())

    except Exception:

        return None





def _matches_search(path: str, name: str, q: str, pattern: str) -> bool:

    lowered_path = path.lower()

    lowered_name = name.lower()

    if q and q not in lowered_path and q not in lowered_name:

        return False

    if pattern:

        if not any(

            fnmatch.fnmatch(candidate, pattern)

            for candidate in {lowered_path, lowered_name, path.rsplit("/", 1)[-1].lower()}

        ):

            return False

    return True





def _parse_datetime_filter(value: str | None) -> float | None:

    text = str(value or "").strip()

    if not text:

        return None

    try:

        return float(text)

    except Exception:

        pass

    try:

        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))

    except Exception as exc:

        raise HTTPException(400, f"Invalid datetime filter: {value}") from exc

    if dt.tzinfo is None:

        dt = dt.replace(tzinfo=timezone.utc)

    return dt.timestamp()





def _file_ext(path: str) -> str:

    name = path.rsplit("/", 1)[-1]

    if "." not in name:

        return ""

    return name.rsplit(".", 1)[-1].lower()





def _object_type_group(path: str, content_type: str) -> str:

    ext = _file_ext(path)

    ct = str(content_type or "").lower()

    if ct.startswith("image/") or ext in IMAGE_EXTENSIONS:

        return "image"

    if ct.startswith("video/") or ext in VIDEO_EXTENSIONS:

        return "video"

    if ct.startswith("audio/") or ext in AUDIO_EXTENSIONS:

        return "audio"

    if "pdf" in ct or ext == "pdf":

        return "pdf"

    if ext in WORD_EXTENSIONS or any(token in ct for token in ("wordprocessingml", "msword", "opendocument.text")):

        return "word"

    if ext in PRESENTATION_EXTENSIONS or any(token in ct for token in ("presentationml", "powerpoint", "opendocument.presentation")):

        return "presentation"

    if ext in SPREADSHEET_EXTENSIONS or any(token in ct for token in ("spreadsheetml", "excel", "opendocument.spreadsheet")):

        return "spreadsheet"

    if ext in ARCHIVE_EXTENSIONS:

        return "archive"

    if ext in EXECUTABLE_EXTENSIONS or any(token in ct for token in ("x-msdownload", "x-dosexec", "x-executable")):

        return "executable"

    if ext in BINARY_EXTENSIONS or ct == "application/octet-stream":

        return "binary"

    if ext in CODE_EXTENSIONS or any(token in ct for token in ("javascript", "typescript", "x-python", "x-sh", "x-shellscript")):

        return "code"

    if ct.startswith("text/") or ext in TEXT_EXTENSIONS or any(token in ct for token in ("json", "xml", "yaml", "css")):

        return "text"

    return ""





def _metadata_tag_values(metadata: dict[str, Any]) -> list[str]:

    raw = metadata.get("tags")

    if isinstance(raw, str):

        return [raw]

    if isinstance(raw, (list, tuple, set)):

        return [str(item) for item in raw if str(item).strip()]

    return []





def _matches_advanced_filters(

    item: dict[str, Any],

    *,

    type_group: str,

    content_type: str,

    min_size: int | None,

    max_size: int | None,

    created_from_ts: float | None,

    created_to_ts: float | None,

    tag: str,

    metadata_key: str,

    metadata_value: str,

) -> bool:

    item_path = str(item.get("path") or item.get("object_id") or "")

    item_content_type = str(item.get("content_type") or infer_content_type(item_path)).lower()

    if type_group and _object_type_group(item_path, item_content_type) != type_group:

        return False

    if content_type and content_type not in item_content_type:

        return False



    try:

        size = int(item.get("size", 0))

    except Exception:

        size = 0

    if min_size is not None and size < min_size:

        return False

    if max_size is not None and size > max_size:

        return False



    created_at = item.get("created_at")

    try:

        created_ts = float(created_at) if created_at is not None else None

    except Exception:

        created_ts = None

    if created_from_ts is not None and (created_ts is None or created_ts < created_from_ts):

        return False

    if created_to_ts is not None and (created_ts is None or created_ts > created_to_ts):

        return False



    metadata = dict(item.get("metadata") or {})

    if tag:

        tags = [value.lower() for value in _metadata_tag_values(metadata)]

        if tag not in tags:

            return False

    if metadata_key:

        if metadata_key not in metadata:

            return False

        if metadata_value:

            raw_value = metadata.get(metadata_key)

            if isinstance(raw_value, (dict, list, tuple, set)):

                value_text = json.dumps(jsonable_value(raw_value), ensure_ascii=False).lower()

            else:

                value_text = str(raw_value).lower()

            if metadata_value not in value_text:

                return False

    return True





def _build_file_payload(path: str, item: dict[str, Any]) -> dict[str, Any]:

    ttl = _ttl_seconds_from_meta(item)

    return {

        "kind": "file",

        "name": item.get("name") or path.rsplit("/", 1)[-1],

        "path": path,

        "parent_prefix": parent_prefix(path),

        "size": int(item.get("size", 0)),

        "content_type": item.get("content_type") or infer_content_type(path),

        "created_at": to_iso_ts(item.get("created_at")),

        "updated_at": to_iso_ts(item.get("updated_at")),

        "expire_at": to_iso_ts(item.get("expire_at")),

        **ttl_payload(ttl),

        "metadata": jsonable_value(item.get("metadata") or {}),

        "download_url": f"{_internal_admin_path('api/storage/object/content')}?path={quote(path)}&download=true",

    }





def _empty_folder_payload(path: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:

    metadata = metadata or {}

    return {

        "kind": "folder",

        "name": path.rstrip("/").rsplit("/", 1)[-1] if path.rstrip("/") else "根目录",

        "path": path,

        "parent_prefix": parent_prefix(path.rstrip("/")),

        "item_count": 0,

        "size": 0,

        "content_type": "inode/directory",

        "created_at": None,

        "updated_at": None,

        "expire_at": None,

        **ttl_payload(None),

        "metadata": jsonable_value(metadata),

        "download_url": None,

    }





async def _all_object_meta(client) -> list[dict[str, Any]]:

    return [dict(item) async for item in client.list_metadata()]





async def _folder_summary(client, folder_path: str) -> dict[str, Any] | None:

    folder_path = _normalize_folder_path(folder_path)

    marker_meta = await client._get_metadata(_folder_marker_path(folder_path))  # type: ignore[attr-defined]

    entries = []

    async for item in client.list_metadata():

        entry = dict(item)

        path = str(entry.get("path") or entry.get("object_id") or "")

        if path == _folder_marker_path(folder_path) or path.startswith(folder_path):

            entries.append(entry)

    if not entries and marker_meta is None:

        return None



    payload = _empty_folder_payload(folder_path, (marker_meta or {}).get("metadata") or {})

    created_values: list[float] = []

    updated_values: list[float] = []

    total_size = 0

    item_count = 0

    ttl_values: list[float] = []

    for entry in entries:

        path = str(entry.get("path") or entry.get("object_id") or "")

        if _is_folder_marker(path):

            continue

        total_size += int(entry.get("size", 0))

        item_count += 1

        created = entry.get("created_at")

        updated = entry.get("updated_at")

        if created is not None:

            try:

                created_values.append(float(created))

            except Exception:

                pass

        if updated is not None:

            try:

                updated_values.append(float(updated))

            except Exception:

                pass

        ttl = _ttl_seconds_from_meta(entry)

        if ttl is not None:

            ttl_values.append(ttl)

    if marker_meta is not None:

        marker_created = marker_meta.get("created_at")

        marker_updated = marker_meta.get("updated_at")

        if marker_created is not None:

            created_values.append(float(marker_created))

        if marker_updated is not None:

            updated_values.append(float(marker_updated))

        marker_ttl = _ttl_seconds_from_meta(marker_meta)

        if marker_ttl is not None:

            ttl_values.append(marker_ttl)

    payload.update(

        {

            "item_count": item_count,

            "size": total_size,

            "created_at": to_iso_ts(min(created_values)) if created_values else None,

            "updated_at": to_iso_ts(max(updated_values)) if updated_values else None,

            "expire_at": to_iso_ts(time.time() + min(ttl_values)) if ttl_values else None,

            **ttl_payload(min(ttl_values) if ttl_values else None),

        }

    )

    return payload





async def _ensure_path_absent_or_overwritable(client, target_path: str, overwrite: bool) -> None:

    lookup = _metadata_lookup_path(target_path)

    meta = await client._get_metadata(lookup)  # type: ignore[attr-defined]

    if meta is not None and not overwrite:

        raise HTTPException(409, f"Target already exists: {target_path}")

    if _is_folder_path(target_path):

        summary = await _folder_summary(client, target_path)

        if summary is not None and summary.get("item_count", 0) > 0 and not overwrite:

            raise HTTPException(409, f"Target folder already exists: {target_path}")





async def _copy_single_object(source_client, target_client, source_object_path: str, target_object_path: str, overwrite: bool) -> dict[str, Any]:

    await _ensure_path_absent_or_overwritable(target_client, target_object_path, overwrite)

    source_meta = await source_client._get_metadata(source_object_path)  # type: ignore[attr-defined]

    if source_meta is None:

        raise HTTPException(404, f"Source not found: {source_object_path}")

    source_data = await source_client.get_bytes(source_object_path)

    if source_data is None:

        raise HTTPException(404, f"Source not found: {source_object_path}")

    new_meta = await target_client.put_bytes(

        source_data,

        object_name=target_object_path,

        metadata=dict(source_meta.get("metadata") or {}),

        expire=_ttl_seconds_from_meta(source_meta),

        content_type=source_meta.get("content_type") or infer_content_type(target_object_path),

    )

    if source_meta.get("created_at") is not None:

        new_meta["created_at"] = source_meta.get("created_at")

    new_meta["updated_at"] = time.time()

    new_meta["expire_at"] = source_meta.get("expire_at")

    await target_client._set_metadata(target_object_path, new_meta)  # type: ignore[attr-defined]

    return new_meta





async def _copy_path(source_client, target_client, source_path: str, target_path: str, overwrite: bool) -> dict[str, Any]:

    source_path = _normalize_any_path(source_path)

    target_path = _normalize_any_path(target_path)



    if _is_folder_path(source_path) != _is_folder_path(target_path):

        raise HTTPException(400, "Source and target kinds must match.")



    copied_paths: list[str] = []

    if _is_folder_path(source_path):

        metas = await _all_object_meta(source_client)

        entries = []

        marker_path = _folder_marker_path(source_path)

        for meta in metas:

            path = str(meta.get("path") or meta.get("object_id") or "")

            if path == marker_path or path.startswith(source_path):

                entries.append(path)

        if not entries:

            raise HTTPException(404, "Source folder not found")

        for path in sorted(entries, key=lambda value: (0 if _is_folder_marker(value) else 1, value)):

            relative = path[len(source_path) :] if path.startswith(source_path) else ""

            target_object_path = _folder_marker_path(target_path) if path == marker_path else target_path + relative

            await _copy_single_object(source_client, target_client, path, target_object_path, overwrite)

            copied_paths.append(target_object_path)

        return {

            "kind": "folder",

            "source_path": source_path,

            "target_path": target_path,

            "copied": copied_paths,

        }



    await _copy_single_object(source_client, target_client, source_path, target_path, overwrite)

    copied_paths.append(target_path)

    return {

        "kind": "file",

        "source_path": source_path,

        "target_path": target_path,

        "copied": copied_paths,

    }





async def _move_path(source_client, target_client, source_path: str, target_path: str, overwrite: bool) -> dict[str, Any]:

    result = await _copy_path(source_client, target_client, source_path, target_path, overwrite)

    source_path = _normalize_any_path(source_path)

    removed = 0

    if _is_folder_path(source_path):

        metas = await _all_object_meta(source_client)

        marker_path = _folder_marker_path(source_path)

        for meta in metas:

            path = str(meta.get("path") or meta.get("object_id") or "")

            if path == marker_path or path.startswith(source_path):

                if await source_client.delete(path):

                    removed += 1

    else:

        if await source_client.delete(source_path):

            removed += 1

    result["moved"] = result.pop("copied")

    result["removed"] = removed

    return result





async def _delete_path(client, path: str) -> dict[str, Any]:

    normalized = _normalize_any_path(path)

    removed = 0

    if _is_folder_path(normalized):

        metas = await _all_object_meta(client)

        marker_path = _folder_marker_path(normalized)

        matched = [

            str(meta.get("path") or meta.get("object_id") or "")

            for meta in metas

            if str(meta.get("path") or meta.get("object_id") or "") == marker_path

            or str(meta.get("path") or meta.get("object_id") or "").startswith(normalized)

        ]

        for object_path in sorted(set(matched), reverse=True):

            if await client.delete(object_path):

                removed += 1

        return {"deleted": removed > 0, "path": normalized, "removed": removed, "kind": "folder"}



    deleted = await client.delete(normalized)

    return {"deleted": deleted, "path": normalized, "removed": int(bool(deleted)), "kind": "file"}





def _editable_bucket_name(section: Any, name: str) -> bool:

    return name in (section.extra or {})





def _clear_object_client_singleton(section: Any, name: str) -> None:

    try:

        section._client_singletons.pop(name, None)

    except Exception:

        pass





async def _object_bucket_descriptor(section: Any, name: str, config: Any, *, slot: str, is_default: bool) -> dict[str, Any]:

    client = section.get_client(name, fallback="", fuzzy=False)

    object_count = 0

    folder_count = 0

    total_size = 0

    latest_updated_at: float | None = None

    seen_folders: set[str] = set()

    async for raw in client.list_metadata():

        item = dict(raw)

        path = str(item.get("path") or item.get("object_id") or "")

        if not path:

            continue

        if _is_folder_marker(path):

            seen_folders.add(_folder_path_from_marker(path))

            continue

        object_count += 1

        total_size += int(item.get("size", 0) or 0)

        updated_at = item.get("updated_at") or item.get("created_at")

        try:

            updated_ts = float(updated_at) if updated_at is not None else None

        except Exception:

            updated_ts = None

        if updated_ts is not None and (latest_updated_at is None or updated_ts > latest_updated_at):

            latest_updated_at = updated_ts

    folder_count = len(seen_folders)

    root_path = getattr(config, "root_path", None)

    if root_path is not None:

        root_path = str(root_path)

    return ObjectBucketDescriptor.model_validate({

        "name": name,

        "backend": get_backend_type(config),

        "namespace": getattr(config, "namespace", getattr(client, "_namespace", "default")),

        "bucket": getattr(config, "bucket", None),

        "folder": getattr(config, "folder", None),

        "root_path": root_path,

        "slot": slot,

        "is_default": is_default,

        "editable": _editable_bucket_name(section, name),

        "deletable": _editable_bucket_name(section, name),

        "object_count": object_count,

        "folder_count": folder_count,

        "total_size": total_size,

        "latest_updated_at": to_iso_ts(latest_updated_at),

    }).model_dump(mode="python")





def _object_bucket_template_config(section: Any, existing_name: str | None = None) -> tuple[str, Any]:

    if existing_name:

        cfg = (section.extra or {}).get(existing_name)

        if cfg is None:

            raise HTTPException(404, f"Bucket '{existing_name}' not found")

        return existing_name, cfg

    for field_name in type(section).model_fields:

        if field_name == "extra":

            continue

        cfg = getattr(section, field_name, None)

        if cfg is not None:

            return field_name, cfg

    for extra_name, cfg in (section.extra or {}).items():

        return extra_name, cfg

    raise HTTPException(400, "No object storage config available to clone")





def _object_bucket_payload_from_config(config: Any, *, bucket: str | None, folder: str | None, root_path: str | None) -> dict[str, Any]:

    payload = config.model_dump(mode="python") if hasattr(config, "model_dump") else dict(config)

    if bucket is not None:

        payload["bucket"] = bucket

    if folder is not None:

        payload["folder"] = folder or None

    if root_path is not None and "root_path" in payload:

        payload["root_path"] = root_path or None

    return payload





@on_before_app_created

def register_storage_object_routes(app: FastAPI):

    admin_path = internal_admin_path



    @app.get(admin_path("storage/object"))

    async def storage_object_page():

        return storage_html_response("object")



    @app.get(admin_path("api/storage/object/clients"), response_model=StorageClientsResponse)

    async def storage_object_clients() -> StorageClientsResponse:

        section = get_storage_config().object

        return StorageClientsResponse.model_validate({"clients": _section_client_names(section)})



    @app.get(admin_path("api/storage/object/config"), response_model=ObjectConfigResponse)

    async def storage_object_config(client_name: str | None = Query(default=None, alias="client")) -> ObjectConfigResponse:

        resolved_name, config, client = _get_exact_object_client(client_name)

        return ObjectConfigResponse.model_validate({

            "client_name": resolved_name,

            "backend": get_backend_type(config),

            "namespace": getattr(config, "namespace", "default"),

            "client_metadata": client.metadata(),

            "default_expire": getattr(config, "default_expire", None),

            "max_size": getattr(config, "max_size", None),

            "supports_preview": True,

            "supports_cleanup": True,

            "supports_folders": True,

            "supports_copy": True,

            "supports_move": True,

            "supports_rename": True,

            "supports_metadata_edit": True,

            "supports_text_edit": True,

            "supports_tags": True,

            "supports_advanced_search": True,

            "supports_thumbnail_view": True,

            "supports_drag_move": True,

            "supports_bucket_admin": True,

            "folder_marker_name": FOLDER_MARKER_NAME,

        })



    @app.get(admin_path("api/storage/object/buckets"), response_model=ObjectBucketsResponse)

    async def storage_object_buckets() -> ObjectBucketsResponse:

        section = get_storage_config().object

        items: list[dict[str, Any]] = []

        for field_name in type(section).model_fields:

            if field_name == "extra":

                continue

            cfg = getattr(section, field_name, None)

            if cfg is None:

                continue

            items.append(await _object_bucket_descriptor(section, field_name, cfg, slot="named", is_default=field_name == "default"))

        for extra_name, cfg in (section.extra or {}).items():

            items.append(await _object_bucket_descriptor(section, extra_name, cfg, slot="extra", is_default=False))

        items.sort(key=lambda item: (0 if item.get("is_default") else 1, str(item.get("name") or "").lower()))

        return ObjectBucketsResponse.model_validate({"items": items})



    @app.post(admin_path("api/storage/object/buckets"), response_model=ObjectBucketWriteResponse)

    async def storage_object_create_bucket(body: ObjectBucketCreateBody) -> ObjectBucketWriteResponse:

        section = get_storage_config().object

        name = str(body.name).strip()

        if not name:

            raise HTTPException(400, "Bucket name is required")

        if name in type(section).model_fields or name in (section.extra or {}):

            raise HTTPException(409, f"Bucket '{name}' already exists")

        _, template = _object_bucket_template_config(section)

        payload = _object_bucket_payload_from_config(template, bucket=body.bucket, folder=body.folder, root_path=body.root_path)

        new_config = type(template).model_validate(payload)

        section.extra[name] = new_config

        _clear_object_client_singleton(section, name)

        descriptor = await _object_bucket_descriptor(section, name, new_config, slot="extra", is_default=False)

        return ObjectBucketWriteResponse.model_validate({"saved": True, "bucket": descriptor})



    @app.patch(admin_path("api/storage/object/buckets"), response_model=ObjectBucketWriteResponse)

    async def storage_object_update_bucket(

        body: ObjectBucketUpdateBody,

        name: str = Query(..., min_length=1),

    ) -> ObjectBucketWriteResponse:

        section = get_storage_config().object

        current_name = str(name).strip()

        if not _editable_bucket_name(section, current_name):

            raise HTTPException(403, f"Bucket '{current_name}' is not editable")

        _, current_config = _object_bucket_template_config(section, current_name)

        next_name = str(body.new_name or current_name).strip()

        if not next_name:

            raise HTTPException(400, "Bucket name is required")

        if next_name != current_name and (next_name in type(section).model_fields or next_name in (section.extra or {})):

            raise HTTPException(409, f"Bucket '{next_name}' already exists")

        payload = _object_bucket_payload_from_config(current_config, bucket=body.bucket, folder=body.folder, root_path=body.root_path)

        new_config = type(current_config).model_validate(payload)

        section.extra.pop(current_name, None)

        _clear_object_client_singleton(section, current_name)

        section.extra[next_name] = new_config

        _clear_object_client_singleton(section, next_name)

        descriptor = await _object_bucket_descriptor(section, next_name, new_config, slot="extra", is_default=False)

        return ObjectBucketWriteResponse.model_validate({"saved": True, "bucket": descriptor})



    @app.delete(admin_path("api/storage/object/buckets"), response_model=ObjectBucketDeleteResponse)

    async def storage_object_delete_bucket(

        name: str = Query(..., min_length=1),

        purge_objects: bool = Query(default=False),

    ) -> ObjectBucketDeleteResponse:

        section = get_storage_config().object

        bucket_name = str(name).strip()

        if not _editable_bucket_name(section, bucket_name):

            raise HTTPException(403, f"Bucket '{bucket_name}' is not deletable")

        _object_bucket_template_config(section, bucket_name)

        removed_objects = 0

        if purge_objects:

            client = section.get_client(bucket_name, fallback="", fuzzy=False)

            paths = [str(item.get("path") or item.get("object_id") or "") async for item in client.list_metadata()]

            for path in sorted({path for path in paths if path}, reverse=True):

                if await client.delete(path):

                    removed_objects += 1

        section.extra.pop(bucket_name, None)

        _clear_object_client_singleton(section, bucket_name)

        return ObjectBucketDeleteResponse.model_validate({"deleted": True, "name": bucket_name, "removed_objects": removed_objects})



    @app.get(admin_path("api/storage/object/items"), response_model=ObjectItemsResponse)

    async def storage_object_items(

        prefix: str = Query(default=""),

        q: str | None = Query(default=None),

        pattern: str | None = Query(default=None),

        recursive: bool = Query(default=False),

        type_group: str | None = Query(default=None),

        content_type: str | None = Query(default=None),

        min_size: int | None = Query(default=None, ge=0),

        max_size: int | None = Query(default=None, ge=0),

        created_from: str | None = Query(default=None),

        created_to: str | None = Query(default=None),

        tag: str | None = Query(default=None),

        metadata_key: str | None = Query(default=None),

        metadata_value: str | None = Query(default=None),

        limit: int = Query(default=100, ge=1, le=1000),

        offset: int = Query(default=0, ge=0),

        client_name: str | None = Query(default=None, alias="client"),

    ) -> ObjectItemsResponse:

        _, _, client = _get_exact_object_client(client_name)

        clean_prefix = _normalize_optional_prefix(prefix)

        all_items = await _all_object_meta(client)

        folders: dict[str, dict[str, Any]] = {}

        files: list[dict[str, Any]] = []

        q_lower = (q or "").strip().lower()

        pattern_text = (pattern or "").strip().lower()

        type_group_text = (type_group or "").strip().lower()

        content_type_text = (content_type or "").strip().lower()

        tag_text = (tag or "").strip().lower()

        metadata_key_text = (metadata_key or "").strip()

        metadata_value_text = (metadata_value or "").strip().lower()

        created_from_ts = _parse_datetime_filter(created_from)

        created_to_ts = _parse_datetime_filter(created_to)



        for raw in all_items:

            item = dict(raw)

            path = str(item.get("path") or item.get("object_id") or "")

            if not path:

                continue



            is_marker = _is_folder_marker(path)

            logical_path = _folder_path_from_marker(path) if is_marker else path

            name = logical_path.rstrip("/").rsplit("/", 1)[-1] if logical_path else ""



            if clean_prefix and not logical_path.startswith(clean_prefix):

                continue

            if is_marker and logical_path == clean_prefix:

                continue

            if not _matches_search(logical_path, name, q_lower, pattern_text):

                continue

            if not _matches_advanced_filters(

                item,

                type_group=type_group_text,

                content_type=content_type_text,

                min_size=min_size,

                max_size=max_size,

                created_from_ts=created_from_ts,

                created_to_ts=created_to_ts,

                tag=tag_text,

                metadata_key=metadata_key_text,

                metadata_value=metadata_value_text,

            ):

                continue



            remainder = logical_path[len(clean_prefix) :] if clean_prefix else logical_path

            if not remainder:

                continue



            if not recursive:

                trimmed = remainder.rstrip("/")

                if "/" in trimmed:

                    folder_name = trimmed.split("/", 1)[0]

                    folder_path = f"{clean_prefix}{folder_name}/"

                    folder = folders.setdefault(folder_path, _empty_folder_payload(folder_path))

                    folder["item_count"] = int(folder.get("item_count", 0)) + 1

                    continue



            if is_marker:

                folder_path = logical_path if logical_path.endswith("/") else logical_path + "/"

                folder = folders.setdefault(folder_path, _empty_folder_payload(folder_path, item.get("metadata") or {}))

                folder.update(

                    {

                        "metadata": jsonable_value(item.get("metadata") or {}),

                        "created_at": to_iso_ts(item.get("created_at")),

                        "updated_at": to_iso_ts(item.get("updated_at")),

                        "expire_at": to_iso_ts(item.get("expire_at")),

                        **ttl_payload(_ttl_seconds_from_meta(item)),

                    }

                )

                continue



            files.append(_build_file_payload(logical_path, item))



        folder_items = sorted(folders.values(), key=lambda item: str(item.get("name") or "").lower())

        file_items = sorted(files, key=lambda item: str(item.get("name") or "").lower())

        merged = folder_items + file_items

        return ObjectItemsResponse.model_validate({

            "prefix": clean_prefix,

            "breadcrumbs": breadcrumbs(clean_prefix),

            "folders": folder_items,

            "items": merged[offset : offset + limit],

            "total": len(merged),

            "offset": offset,

            "limit": limit,

            "recursive": recursive,

            "query": q or "",

            "pattern": pattern or "",

            "filters": {

                "type_group": type_group or "",

                "content_type": content_type or "",

                "min_size": min_size,

                "max_size": max_size,

                "created_from": created_from or "",

                "created_to": created_to or "",

                "tag": tag or "",

                "metadata_key": metadata_key or "",

                "metadata_value": metadata_value or "",

            },

        })



    @app.post(admin_path("api/storage/object/folder"), response_model=ObjectFolderCreateResponse)

    async def storage_object_create_folder(body: ObjectFolderCreateBody, client_name: str | None = Query(default=None, alias="client")) -> ObjectFolderCreateResponse:

        _, _, client = _get_exact_object_client(client_name)

        folder_path = _normalize_folder_path(body.path)

        marker_path = _folder_marker_path(folder_path)

        existing = await client._get_metadata(marker_path)  # type: ignore[attr-defined]

        if existing is not None and not body.overwrite:

            raise HTTPException(409, "Folder already exists")

        meta = await client.put_bytes(

            b"",

            object_name=marker_path,

            metadata={**body.metadata, "is_folder": True},

            content_type="application/x-template-folder-marker",

        )

        return ObjectFolderCreateResponse.model_validate({

            "created": True,

            "kind": "folder",

            "path": folder_path,

            "metadata": jsonable_value(meta.get("metadata") or {}),

        })



    @app.post(admin_path("api/storage/object/upload"), response_model=ObjectUploadResponse)

    async def storage_object_upload(

        files: list[UploadFile] = File(...),

        prefix: str = Form(default=""),

        expire_seconds: float | None = Form(default=None),

        metadata_json: str | None = Form(default=None),

        overwrite: bool = Form(default=True),

        client_name: str | None = Query(default=None, alias="client"),

    ) -> ObjectUploadResponse:

        _, _, client = _get_exact_object_client(client_name)

        clean_prefix = _normalize_optional_prefix(prefix)

        metadata_payload: dict[str, Any] = {}

        if metadata_json:

            try:

                parsed = json.loads(metadata_json)

                if isinstance(parsed, dict):

                    metadata_payload = parsed

            except Exception as exc:

                raise HTTPException(400, f"Invalid metadata_json: {exc}") from exc

        uploaded: list[dict[str, Any]] = []

        skipped: list[dict[str, Any]] = []

        for upload in files:

            object_name = normalize_object_path(f"{clean_prefix}{upload.filename or 'upload.bin'}")

            if not overwrite and await client._get_metadata(object_name) is not None:  # type: ignore[attr-defined]

                skipped.append({"path": object_name, "reason": "exists"})

                continue

            data = await upload.read()

            meta = await client.put_bytes(

                data,

                object_name=object_name,

                metadata={**metadata_payload, "original_filename": upload.filename},

                expire=expire_seconds,

                content_type=upload.content_type or infer_content_type(object_name),

            )

            uploaded.append(

                {

                    "path": object_name,

                    "name": meta.get("name"),

                    "size": meta.get("size"),

                    "content_type": meta.get("content_type"),

                    "created_at": to_iso_ts(meta.get("created_at")),

                    "updated_at": to_iso_ts(meta.get("updated_at")),

                    "expire_at": to_iso_ts(meta.get("expire_at")),

                    "metadata": jsonable_value(meta.get("metadata") or {}),

                }

            )

        return ObjectUploadResponse.model_validate({"uploaded": uploaded, "skipped": skipped})



    @app.get(admin_path("api/storage/object/meta"), response_model=ObjectItem)

    async def storage_object_meta(path: str = Query(..., min_length=1), client_name: str | None = Query(default=None, alias="client")) -> ObjectItem:

        _, _, client = _get_exact_object_client(client_name)

        normalized = _normalize_any_path(path)

        if _is_folder_path(normalized):

            summary = await _folder_summary(client, normalized)

            if summary is None:

                raise HTTPException(404, "Folder not found")

            return ObjectItem.model_validate(summary)

        meta = await client._get_metadata(normalized)  # type: ignore[attr-defined]

        if meta is None:

            raise HTTPException(404, "Object not found")

        ttl = await client.get_expire(normalized)

        return ObjectItem.model_validate({

            "path": normalized,

            "kind": "file",

            "name": meta.get("name") or normalized.rsplit("/", 1)[-1],

            "size": int(meta.get("size", 0)),

            "content_type": meta.get("content_type") or infer_content_type(normalized),

            "created_at": to_iso_ts(meta.get("created_at")),

            "updated_at": to_iso_ts(meta.get("updated_at")),

            "expire_at": to_iso_ts(meta.get("expire_at")),

            **ttl_payload(ttl),

            "metadata": jsonable_value(meta.get("metadata") or {}),

            "previewable": True,

            "download_url": f"{_internal_admin_path('api/storage/object/content')}?path={quote(normalized)}&download=true",

        })



    @app.get(admin_path("api/storage/object/content"))

    async def storage_object_content(

        path: str = Query(..., min_length=1),

        download: bool = Query(default=False),

        client_name: str | None = Query(default=None, alias="client"),

    ) -> Response:

        _, _, client = _get_exact_object_client(client_name)

        object_name = _normalize_any_path(path)

        if _is_folder_path(object_name):

            raise HTTPException(400, "Folder content cannot be downloaded from this endpoint.")

        data = await client.get_bytes(object_name)

        if data is None:

            raise HTTPException(404, "Object not found")

        meta = await client._get_metadata(object_name)  # type: ignore[attr-defined]

        content_type = infer_content_type(object_name, (meta or {}).get("content_type") if isinstance(meta, dict) else None)

        headers: dict[str, str] = {}

        if download:

            filename = object_name.rsplit("/", 1)[-1]

            headers["Content-Disposition"] = f'attachment; filename="{filename}"'

        return Response(content=data, media_type=content_type, headers=headers)



    @app.get(admin_path("api/storage/object/office-preview"), response_model=ObjectOfficePreviewResponse)

    async def storage_object_office_preview(

        path: str = Query(..., min_length=1),

        client_name: str | None = Query(default=None, alias="client"),

    ) -> ObjectOfficePreviewResponse:

        _, _, client = _get_exact_object_client(client_name)

        object_name = _normalize_any_path(path)

        if _is_folder_path(object_name):

            raise HTTPException(400, "Folder content cannot be previewed as Office document.")

        data = await client.get_bytes(object_name)

        if data is None:

            raise HTTPException(404, "Object not found")

        meta = await client._get_metadata(object_name)  # type: ignore[attr-defined]

        content_type = infer_content_type(object_name, (meta or {}).get("content_type") if isinstance(meta, dict) else None)

        return ObjectOfficePreviewResponse.model_validate(office_preview_payload(

            object_name,

            data,

            content_type,

            pdf_url_builder=lambda preview_path: f"{_internal_admin_path('api/storage/object/office-preview/pdf')}?path={quote(preview_path)}",

            thumb_url_builder=lambda preview_path, page: f"{_internal_admin_path('api/storage/object/office-preview/thumb')}?path={quote(preview_path)}&page={page}",

        ))



    @app.get(admin_path("api/storage/object/office-preview/pdf"))

    async def storage_object_office_preview_pdf(

        path: str = Query(..., min_length=1),

        client_name: str | None = Query(default=None, alias="client"),

    ) -> Response:

        _, _, client = _get_exact_object_client(client_name)

        object_name = _normalize_any_path(path)

        if _is_folder_path(object_name):

            raise HTTPException(400, "Folder content cannot be previewed as Office document.")

        data = await client.get_bytes(object_name)

        if data is None:

            raise HTTPException(404, "Object not found")

        meta = await client._get_metadata(object_name)  # type: ignore[attr-defined]

        content_type = infer_content_type(object_name, (meta or {}).get("content_type") if isinstance(meta, dict) else None)

        if office_preview_kind(object_name, content_type) != "presentation":

            raise HTTPException(400, "PDF office preview is only available for presentation documents.")

        cache_key = office_preview_cache_key(object_name, data, content_type)

        pdf_path, _ = office_preview_cache_paths(cache_key)

        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:

            presentation_preview_payload(

                object_name,

                data,

                content_type,

                pdf_url_builder=lambda preview_path: f"{_internal_admin_path('api/storage/object/office-preview/pdf')}?path={quote(preview_path)}",

                thumb_url_builder=lambda preview_path, page: f"{_internal_admin_path('api/storage/object/office-preview/thumb')}?path={quote(preview_path)}&page={page}",

            )

        return Response(content=pdf_path.read_bytes(), media_type="application/pdf")



    @app.get(admin_path("api/storage/object/office-preview/thumb"))

    async def storage_object_office_preview_thumb(

        path: str = Query(..., min_length=1),

        page: int = Query(..., ge=1),

        client_name: str | None = Query(default=None, alias="client"),

    ) -> Response:

        _, _, client = _get_exact_object_client(client_name)

        object_name = _normalize_any_path(path)

        if _is_folder_path(object_name):

            raise HTTPException(400, "Folder content cannot be previewed as Office document.")

        data = await client.get_bytes(object_name)

        if data is None:

            raise HTTPException(404, "Object not found")

        meta = await client._get_metadata(object_name)  # type: ignore[attr-defined]

        content_type = infer_content_type(object_name, (meta or {}).get("content_type") if isinstance(meta, dict) else None)

        if office_preview_kind(object_name, content_type) != "presentation":

            raise HTTPException(400, "Thumbnail preview is only available for presentation documents.")

        cache_key = office_preview_cache_key(object_name, data, content_type)

        _, thumb_dir = office_preview_cache_paths(cache_key)

        thumb_path = thumb_dir / f"{page}.png"

        if not thumb_path.exists() or thumb_path.stat().st_size <= 0:

            payload = presentation_preview_payload(

                object_name,

                data,

                content_type,

                pdf_url_builder=lambda preview_path: f"{_internal_admin_path('api/storage/object/office-preview/pdf')}?path={quote(preview_path)}",

                thumb_url_builder=lambda preview_path, page_no: f"{_internal_admin_path('api/storage/object/office-preview/thumb')}?path={quote(preview_path)}&page={page_no}",

            )

            if page > int(payload.get("page_count") or 0):

                raise HTTPException(404, "Preview page not found")

        if not thumb_path.exists() or thumb_path.stat().st_size <= 0:

            raise HTTPException(404, "Preview thumbnail not found")

        return Response(content=thumb_path.read_bytes(), media_type="image/png")



    @app.put(admin_path("api/storage/object/content"), response_model=ObjectWriteResponse)

    async def storage_object_write_content(

        body: ObjectWriteBody,

        path: str = Query(..., min_length=1),

        client_name: str | None = Query(default=None, alias="client"),

    ) -> ObjectWriteResponse:

        _, _, client = _get_exact_object_client(client_name)

        object_name = _normalize_any_path(path)

        if _is_folder_path(object_name):

            raise HTTPException(400, "Folder content cannot be edited.")

        existing = await client._get_metadata(object_name)  # type: ignore[attr-defined]

        old_ttl = await client.get_expire(object_name) if existing and body.preserve_ttl else None

        if body.mode == "base64":

            try:

                data = base64.b64decode(body.value.encode("utf-8"), validate=True)

            except Exception as exc:

                raise HTTPException(400, f"Invalid base64 payload: {exc}") from exc

        else:

            data = body.value.encode("utf-8")

        new_metadata = dict(existing.get("metadata") or {}) if existing and body.preserve_metadata else {}

        if body.metadata:

            new_metadata.update(body.metadata)

        content_type = body.content_type or (existing or {}).get("content_type") or infer_content_type(object_name)

        meta = await client.put_bytes(

            data,

            object_name=object_name,

            metadata=new_metadata,

            expire=old_ttl,

            content_type=content_type,

        )

        if existing and existing.get("created_at") is not None:

            meta["created_at"] = existing.get("created_at")

            meta["updated_at"] = time.time()

            await client._set_metadata(object_name, meta)  # type: ignore[attr-defined]

        return ObjectWriteResponse.model_validate({

            "saved": True,

            "path": object_name,

            "size": len(data),

            "content_type": content_type,

            "metadata": jsonable_value(meta.get("metadata") or {}),

        })



    @app.patch(admin_path("api/storage/object/metadata"), response_model=ObjectMetadataUpdateResponse)

    async def storage_object_update_metadata(

        body: ObjectMetadataBody,

        path: str = Query(..., min_length=1),

        client_name: str | None = Query(default=None, alias="client"),

    ) -> ObjectMetadataUpdateResponse:

        _, _, client = _get_exact_object_client(client_name)

        lookup_path = _metadata_lookup_path(path)

        meta = await client._get_metadata(lookup_path)  # type: ignore[attr-defined]

        if meta is None:

            raise HTTPException(404, "Object not found")

        current_metadata = dict(meta.get("metadata") or {}) if body.merge else {}

        current_metadata.update(body.metadata)

        meta["metadata"] = current_metadata

        meta["updated_at"] = time.time()

        await client._set_metadata(lookup_path, meta)  # type: ignore[attr-defined]

        return ObjectMetadataUpdateResponse.model_validate({

            "updated": True,

            "path": _normalize_any_path(path),

            "metadata": jsonable_value(current_metadata),

        })



    @app.post(admin_path("api/storage/object/copy"), response_model=ObjectPathTransferResponse)

    async def storage_object_copy(body: ObjectCopyMoveBody, client_name: str | None = Query(default=None, alias="client")) -> ObjectPathTransferResponse:

        _, _, target_client = _get_exact_object_client(client_name)

        _, _, source_client = _get_exact_object_client(body.source_client or client_name)

        return ObjectPathTransferResponse.model_validate(await _copy_path(source_client, target_client, body.source_path, body.target_path, body.overwrite))



    @app.post(admin_path("api/storage/object/move"), response_model=ObjectPathTransferResponse)

    async def storage_object_move(body: ObjectCopyMoveBody, client_name: str | None = Query(default=None, alias="client")) -> ObjectPathTransferResponse:

        _, _, target_client = _get_exact_object_client(client_name)

        _, _, source_client = _get_exact_object_client(body.source_client or client_name)

        return ObjectPathTransferResponse.model_validate(await _move_path(source_client, target_client, body.source_path, body.target_path, body.overwrite))



    @app.delete(admin_path("api/storage/object/item"), response_model=ObjectDeleteResponse)

    async def storage_object_delete(path: str = Query(..., min_length=1), client_name: str | None = Query(default=None, alias="client")) -> ObjectDeleteResponse:

        _, _, client = _get_exact_object_client(client_name)

        return ObjectDeleteResponse.model_validate(await _delete_path(client, path))



    @app.post(admin_path("api/storage/object/delete-many"), response_model=ObjectDeleteManyResponse)

    async def storage_object_delete_many(body: ObjectDeleteManyBody, client_name: str | None = Query(default=None, alias="client")) -> ObjectDeleteManyResponse:

        _, _, client = _get_exact_object_client(client_name)

        results = []

        total_removed = 0

        for path in body.paths:

            result = await _delete_path(client, path)

            total_removed += int(result.get("removed", 0))

            results.append(result)

        return ObjectDeleteManyResponse.model_validate({"deleted": total_removed > 0, "removed": total_removed, "items": results})



    @app.patch(admin_path("api/storage/object/expire"), response_model=ObjectExpireResponse)

    async def storage_object_expire(body: ObjectExpireBody, path: str = Query(..., min_length=1), client_name: str | None = Query(default=None, alias="client")) -> ObjectExpireResponse:

        _, _, client = _get_exact_object_client(client_name)

        object_name = _normalize_any_path(path)

        if _is_folder_path(object_name):

            object_name = _folder_marker_path(object_name)

        updated = await client.set_expire(object_name, body.expire_seconds)

        if not updated:

            raise HTTPException(404, "Object not found")

        ttl = await client.get_expire(object_name)

        return ObjectExpireResponse.model_validate({"updated": updated, "path": _normalize_any_path(path), **ttl_payload(ttl)})



    @app.post(admin_path("api/storage/object/cleanup"), response_model=StorageCleanupResponse)

    async def storage_object_cleanup(force: bool = True, client_name: str | None = Query(default=None, alias="client")) -> StorageCleanupResponse:

        _, _, client = _get_exact_object_client(client_name)

        removed = await client.cleanup(force=force)

        return StorageCleanupResponse.model_validate({"removed": removed})

