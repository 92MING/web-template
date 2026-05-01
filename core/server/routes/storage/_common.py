import json
import base64
import sqlite3
import mimetypes
import importlib
import inspect
import types

# pyright: reportUnusedFunction=false

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, cast
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from core.storage.config import StorageConfig
from core.storage.orm import MongoORMClient, ORMModel, RedisORMClient, SQL_ORM_Client, SQLiteORMClient
from core.storage.vector import MongoVectorClient, VectorIndex, VectorORMField, VectorORMModel
from ...app import get_resources
from ...html_injection import html_response_from_path


def storage_html_response(name: str) -> HTMLResponse:
    path = get_resources("admin-panel", "storage", f"storage_{name}.html") or Path(f"storage_{name}.html")
    return html_response_from_path(path, not_found_message=f"storage/storage_{name}.html not found")


def get_storage_config() -> StorageConfig:
    return StorageConfig.Global()


def _section_client_names(section: Any) -> list[dict[str, Any]]:
    """Return a list of ``{name, backend_type, is_default}`` for every
    resolvable client name in a :class:`StorageConfigSection`."""
    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    skip = {"extra"}
    fields = type(section).model_fields
    for field_name in fields:
        if field_name in skip:
            continue
        cfg = getattr(section, field_name, None)
        if cfg is None:
            continue
        if field_name not in seen_keys:
            seen_keys.add(field_name)
            results.append({
                "name": field_name,
                "backend_type": get_backend_type(cfg),
                "is_default": field_name == "default",
                "slot": "named",
            })
    for key, cfg in (section.extra or {}).items():
        if key not in seen_keys:
            seen_keys.add(key)
            results.append({
                "name": key,
                "backend_type": get_backend_type(cfg),
                "is_default": False,
                "slot": "extra",
            })
    return results

_ = _section_client_names


def get_kv_client(name: str = "default", fallback: str = "default"):
    return get_storage_config().get_kv_client(name, fallback)


def get_object_client(name: str = "default", fallback: str = "default"):
    return get_storage_config().get_object_client(name, fallback)


def get_orm_client(name: str = "default", fallback: str = "default"):
    return get_storage_config().get_orm_client(name, fallback)


def get_vector_client(name: str = "default", fallback: str = "default"):
    return get_storage_config().get_vector_client(name, fallback)


def get_backend_type(config_obj: Any) -> str:
    return str(getattr(config_obj, "Type", getattr(config_obj, "type", type(config_obj).__name__)))


def to_iso_ts(value: float | int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value)).isoformat()
    except Exception:
        return None


def ttl_payload(ttl: float | None) -> dict[str, Any]:
    if ttl is None:
        return {"ttl_seconds": None, "ttl_state": "persistent", "expire_at": None}
    if ttl <= 0:
        return {"ttl_seconds": 0.0, "ttl_state": "expired_or_missing", "expire_at": None}
    return {
        "ttl_seconds": float(ttl),
        "ttl_state": "expiring",
        "expire_at": to_iso_ts(datetime.now().timestamp() + float(ttl)),
    }


def jsonable_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return {
            "__type__": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
            "size": len(value),
        }
    if isinstance(value, bytearray):
        return jsonable_value(bytes(value))
    if isinstance(value, memoryview):
        return jsonable_value(value.tobytes())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable_value(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return jsonable_value(value.model_dump(mode="json", by_alias=True))
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return jsonable_value(value.dict())
        except Exception:
            pass
    return str(value)


def describe_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        encoded = base64.b64encode(value).decode("ascii")
        return {
            "value_kind": "bytes",
            "display_mode": "base64",
            "value": encoded,
            "pretty_json": None,
            "size_bytes_estimate": len(value),
        }
    payload = jsonable_value(value)
    kind = type(payload).__name__
    if isinstance(payload, dict):
        kind = "object"
    elif isinstance(payload, list):
        kind = "array"
    elif isinstance(payload, str):
        kind = "string"
    elif payload is None:
        kind = "null"
    display_mode = "text" if isinstance(payload, str) else "json"
    pretty_json: str | None = None
    if not isinstance(payload, str):
        try:
            pretty_json = json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception:
            pretty_json = None
    else:
        pretty_json = payload
    try:
        size_estimate = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except Exception:
        size_estimate = None
    return {
        "value_kind": kind,
        "display_mode": display_mode,
        "value": payload,
        "pretty_json": pretty_json,
        "size_bytes_estimate": size_estimate,
    }


def normalize_object_path(path: str) -> str:
    raw = str(path or "").replace("\\", "/").strip()
    raw = raw.lstrip("/")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise HTTPException(400, "Invalid object path.")
    normalized = "/".join(parts)
    if not normalized:
        raise HTTPException(400, "Object path is required.")
    return normalized


def parent_prefix(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) <= 1:
        return ""
    return "/".join(parts[:-1]) + "/"


def breadcrumbs(prefix: str) -> list[dict[str, str]]:
    normalized = str(prefix or "").replace("\\", "/").strip("/")
    if not normalized:
        return [{"name": "Home", "path": ""}]
    items = [{"name": "Home", "path": ""}]
    parts = normalized.split("/")
    curr: list[str] = []
    for part in parts:
        curr.append(part)
        items.append({"name": part, "path": "/".join(curr) + "/"})
    return items


def infer_content_type(path: str, content_type: str | None = None) -> str:
    if content_type:
        return content_type
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        try:
            return {str(key): value for key, value in mapping.items()}
        except Exception:
            pass
    try:
        return dict(row)
    except Exception:
        keys = getattr(row, "keys", lambda: [])()
        return {str(k): row[k] for k in keys}


def try_import_model(module_name: str | None, class_name: str | None) -> type[ORMModel] | None:
    if not module_name or not class_name:
        return None
    try:
        module = importlib.import_module(module_name)
        model_cls = getattr(module, class_name, None)
        if isinstance(model_cls, type) and issubclass(model_cls, ORMModel):
            return model_cls
    except Exception:
        return None
    return None


def _logical_orm_collection_name(table_name: object) -> str | None:
    name = str(table_name or "").strip().strip('"')
    if not name.startswith("orm_"):
        return None
    collection_name = name[4:]
    return collection_name or None


def _list_physical_vector_collection_names(client: Any) -> list[str]:
    if not isinstance(client, MongoVectorClient):
        return []
    try:
        if not client._started:
            client.start()
        database = getattr(client, "_sync_database", None)
        if database is None:
            return []
        prefix = f"vector_{client._namespace}_"
        names = database.list_collection_names()
        logical_names: list[str] = []
        for raw_name in names:
            name = str(raw_name or "").strip()
            if not name.startswith(prefix):
                continue
            logical_name = name[len(prefix):].strip()
            if logical_name:
                logical_names.append(logical_name)
        return sorted(set(logical_names))
    except Exception:
        return []


def _merge_collection_meta_rows(rows: list[dict[str, Any]], physical_collections: Iterable[str]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("collection_name") or "").strip()
        if name:
            merged[name] = row
    for collection_name in physical_collections:
        name = str(collection_name or "").strip()
        if name and name not in merged:
            merged[name] = {"collection_name": name}
    return [merged[name] for name in sorted(merged)]


def _list_physical_orm_collection_names(client: Any) -> list[str]:
    if isinstance(client, SQLiteORMClient):
        db_path = getattr(client, "_db_path", None)
        if db_path is None:
            return []
        try:
            with sqlite3.connect(str(db_path)) as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'orm_%' ORDER BY name"
                ).fetchall()
        except Exception:
            return []
        return [
            collection_name
            for row in rows
            for collection_name in [_logical_orm_collection_name(row[0])]
            if collection_name is not None
        ]
    if isinstance(client, SQL_ORM_Client):
        try:
            from sqlalchemy import inspect as sa_inspect

            if not client._started:
                client.start()
            engine = client._require_engine()
            table_names = sa_inspect(engine.sync_engine).get_table_names()
        except Exception:
            return []
        return [
            collection_name
            for table_name in table_names
            for collection_name in [_logical_orm_collection_name(table_name)]
            if collection_name is not None
        ]
    if isinstance(client, MongoORMClient):
        try:
            from pymongo import MongoClient as SyncMongoClient

            sync_client = SyncMongoClient(client._mongo_url, serverSelectionTimeoutMS=3000)
            try:
                collection_names = sync_client[client._database_name].list_collection_names()
            finally:
                sync_client.close()
        except Exception:
            return []
        return [
            collection_name
            for raw_name in collection_names
            for collection_name in [_logical_orm_collection_name(raw_name)]
            if collection_name is not None
        ]
    return []


async def _list_physical_orm_collection_names_async(client: Any) -> list[str]:
    if isinstance(client, SQLiteORMClient):
        try:
            conn = await client._get_conn()
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'orm_%' ORDER BY name"
            )
            rows = await cursor.fetchall()
            await cursor.close()
        except Exception:
            return []
        return [
            collection_name
            for row in rows
            for collection_name in [_logical_orm_collection_name(row[0])]
            if collection_name is not None
        ]
    if isinstance(client, SQL_ORM_Client):
        try:
            from sqlalchemy import inspect as sa_inspect

            engine = await client._ensure_schema_ready()
            async with engine.connect() as conn:
                table_names = await conn.run_sync(lambda sync_conn: sa_inspect(sync_conn).get_table_names())
        except Exception:
            return []
        return [
            collection_name
            for table_name in table_names
            for collection_name in [_logical_orm_collection_name(table_name)]
            if collection_name is not None
        ]
    if isinstance(client, MongoORMClient):
        try:
            if not client._started:
                client.start()
            client._ensure_async_client()
            database = client._database
            if database is None:
                return []
            collection_names = await database.list_collection_names()
        except Exception:
            return []
        return [
            collection_name
            for raw_name in collection_names
            for collection_name in [_logical_orm_collection_name(raw_name)]
            if collection_name is not None
        ]
    return []


def list_orm_collection_meta(client: Any) -> list[dict[str, Any]]:
    getter = getattr(client, "list_collection_meta", None)
    if callable(getter):
        try:
            rows = getter()
            return _merge_collection_meta_rows([_row_to_dict(row) for row in rows], _list_physical_orm_collection_names(client))  # type: ignore[arg-type]
        except Exception:
            pass
    if isinstance(client, SQLiteORMClient):
        db_path = getattr(client, "_db_path", None)
        if db_path is None:
            return []
        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT collection_name, model_module, model_name, schema_json FROM _orm_collections ORDER BY collection_name"
                ).fetchall()
                return _merge_collection_meta_rows([_row_to_dict(row) for row in rows], _list_physical_orm_collection_names(client))
        except sqlite3.OperationalError:
            return _merge_collection_meta_rows([], _list_physical_orm_collection_names(client))
    if isinstance(client, SQL_ORM_Client):
        if not client._started:
            client.start()
        engine = client._require_engine()
        with engine.sync_engine.begin() as conn:
            rows = conn.execute(
                client._sql_text(
                    "SELECT collection_name, model_module, model_name, schema_json FROM _orm_collections ORDER BY collection_name"
                )
            ).fetchall()
        return _merge_collection_meta_rows([_row_to_dict(row) for row in rows], _list_physical_orm_collection_names(client))
    if isinstance(client, MongoORMClient):
        try:
            from pymongo import MongoClient as SyncMongoClient

            sync_client = SyncMongoClient(client._mongo_url, serverSelectionTimeoutMS=3000)
            try:
                rows = list(
                    cast(
                        Iterable[object],
                        sync_client[client._database_name]["_orm_collections"].find({}, {"_id": 0}).sort("collection_name", 1),
                    )
                )
            finally:
                sync_client.close()
        except Exception:
            rows = []
        return _merge_collection_meta_rows([_row_to_dict(row) for row in rows], _list_physical_orm_collection_names(client))
    if isinstance(client, RedisORMClient):
        try:
            import redis as _sync_redis

            sync_client = _sync_redis.Redis.from_url(client._url, db=client._db, decode_responses=True)
            try:
                collection_names = sorted(sync_client.smembers(client._collections_key()) or [])
                result: list[dict[str, Any]] = []
                for coll in collection_names:
                    meta_raw = sync_client.json().get(client._collection_meta_key(coll))
                    if isinstance(meta_raw, dict):
                        result.append(_row_to_dict(meta_raw))
                    else:
                        result.append({"collection_name": coll})
                return result
            finally:
                sync_client.close()
        except Exception:
            return []
    return []


async def list_orm_collection_meta_async(client: Any) -> list[dict[str, Any]]:
    getter = getattr(client, "list_collection_meta", None)
    if callable(getter):
        try:
            rows = getter()
            if inspect.isawaitable(rows):
                rows = await rows
            return _merge_collection_meta_rows([_row_to_dict(row) for row in rows], await _list_physical_orm_collection_names_async(client))  # type: ignore[arg-type]
        except Exception:
            pass
    if isinstance(client, SQLiteORMClient):
        try:
            conn = await client._get_conn()
            cursor = await conn.execute(
                "SELECT collection_name, model_module, model_name, schema_json FROM _orm_collections ORDER BY collection_name"
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return _merge_collection_meta_rows([_row_to_dict(row) for row in rows], await _list_physical_orm_collection_names_async(client))
        except Exception:
            return _merge_collection_meta_rows([], await _list_physical_orm_collection_names_async(client))
    if isinstance(client, SQL_ORM_Client):
        try:
            engine = await client._ensure_schema_ready()
            async with engine.begin() as conn:
                sql_result = await conn.execute(
                    client._sql_text(
                        "SELECT collection_name, model_module, model_name, schema_json FROM _orm_collections ORDER BY collection_name"
                    )
                )
                sql_rows = cast(list[object], sql_result.fetchall())
            return _merge_collection_meta_rows([_row_to_dict(row) for row in sql_rows], await _list_physical_orm_collection_names_async(client))
        except Exception:
            return _merge_collection_meta_rows([], await _list_physical_orm_collection_names_async(client))
    if isinstance(client, MongoORMClient):
        try:
            if not client._started:
                client.start()
            cursor = client._meta_collection().find({}, {"_id": 0}).sort("collection_name", 1)
            rows = [_row_to_dict(row) async for row in cursor]
            return _merge_collection_meta_rows(rows, await _list_physical_orm_collection_names_async(client))
        except Exception:
            return _merge_collection_meta_rows([], await _list_physical_orm_collection_names_async(client))
    if isinstance(client, RedisORMClient):
        try:
            await client._ensure_ready()
            collection_names = await client._async_collection_names()
            result: list[dict[str, Any]] = []
            for coll in collection_names:
                meta_raw = await client._load_collection_meta(coll)
                if isinstance(meta_raw, dict):
                    result.append(_row_to_dict(meta_raw))
                else:
                    result.append({"collection_name": coll})
            return result
        except Exception:
            return []
    return []


def orm_collection_count(client: Any, collection: str) -> int | None:
    try:
        if isinstance(client, SQLiteORMClient):
            db_path = getattr(client, "_db_path", None)
            if db_path is None:
                return None
            with sqlite3.connect(str(db_path)) as conn:
                row = conn.execute(
                    f"SELECT COUNT(1) FROM {client._table_sql(collection)} d"
                    f" LEFT JOIN {client._sys_table_sql(collection)} s ON d.\"id\" = s.\"id\""
                    f" WHERE s.expire_at IS NULL OR s.expire_at > ?",
                    (datetime.now().timestamp(),),
                ).fetchone()
                return int(row[0]) if row else 0
        counter = getattr(client, "collection_count", None)
        if callable(counter):
            result = counter(collection)
            if inspect.isawaitable(result):
                return None
            if isinstance(result, bool):
                return int(result)
            if isinstance(result, (int, float)):
                return int(result)
            return None
        if isinstance(client, SQL_ORM_Client):
            if not client._started:
                client.start()
            engine = client._require_engine()
            with engine.sync_engine.begin() as conn:
                row = conn.execute(client._sql_text(f"SELECT COUNT(1) FROM {client._table_sql(collection)}")).fetchone()
            return int(row[0]) if row else 0
        if isinstance(client, MongoORMClient):
            count_result = client._collection(collection).count_documents({})
            if inspect.isawaitable(count_result):
                return None
            if isinstance(count_result, bool):
                return int(count_result)
            if isinstance(count_result, (int, float)):
                return int(count_result)
            return None
    except Exception:
        return None
    return None


def load_orm_model_if_present(client: Any, meta: dict[str, Any]) -> type[ORMModel] | None:
    model_cls = try_import_model(meta.get("model_module"), meta.get("model_name"))
    if model_cls is None:
        collection_name = str(meta.get("collection_name") or "").strip()
        resolve_model = getattr(client, "_resolve_collection_model", None)
        if collection_name and callable(resolve_model):
            try:
                model_cls = resolve_model(collection_name)
            except Exception:
                model_cls = None
    if model_cls is not None:
        try:
            client.register_model(model_cls)
        except Exception:
            pass
    return cast(type[ORMModel] | None, model_cls)


def extract_schema_fields(schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    items: list[dict[str, Any]] = []
    for name, payload in props.items():
        if not isinstance(payload, dict):
            payload = {}
        declared_type = payload.get("type") or payload.get("title")
        if isinstance(declared_type, list):
            declared_type = " | ".join(str(item) for item in declared_type if str(item or "").strip()) or None
        items.append(
            {
                "name": name,
                "declared_type": declared_type,
                "required": name in required,
                "description": payload.get("description"),
            }
        )
    return items


def sample_document_fields(documents: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for doc in documents:
        for key, value in (doc or {}).items():
            info = stats.setdefault(key, {"types": set(), "examples": []})
            if isinstance(value, dict):
                typ = "object"
            elif isinstance(value, list):
                typ = "array"
            elif value is None:
                typ = "null"
            else:
                typ = type(value).__name__
            info["types"].add(typ)
            if len(info["examples"]) < 3:
                info["examples"].append(jsonable_value(value))
    return [
        {
            "name": key,
            "sample_types": sorted(info["types"]),
            "examples": info["examples"],
        }
        for key, info in sorted(stats.items(), key=lambda item: item[0])
    ]

def list_vector_collections(client: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    restore_state = getattr(client, "_restore_collection_state", None)
    if callable(restore_state) and not inspect.iscoroutinefunction(restore_state):
        try:
            restore_state()
        except Exception:
            pass
    alias = getattr(client, "_alias", None)
    utility = getattr(client, "_utility", None)
    namespace = getattr(client, "_namespace", "")
    if utility is not None and hasattr(utility, "list_collections"):
        try:
            for raw_name in utility.list_collections(using=alias):
                name = str(raw_name)
                logical = name
                prefix = f"{namespace}_"
                if namespace and name.startswith(prefix):
                    logical = name[len(prefix):]
                fields = ensure_vector_collection_registered(client, logical)
                items.append({
                    "name": logical,
                    "backend_name": name,
                    "vector_fields": [{"name": key, "dim": val} for key, val in sorted(fields.items())],
                    "registered": logical in getattr(client, "_vector_fields", {}),
                })
                seen.add(logical)
        except Exception:
            pass
    for logical, fields in getattr(client, "_vector_fields", {}).items():
        if logical in seen:
            continue
        items.append({
            "name": logical,
            "backend_name": logical,
            "vector_fields": [{"name": key, "dim": val} for key, val in sorted(fields.items())],
            "registered": True,
        })
        seen.add(logical)
    collection_name_func = getattr(client, "_collection_name", None)
    for logical in _list_physical_vector_collection_names(client):
        if logical in seen:
            continue
        fields = ensure_vector_collection_registered(client, logical)
        backend_name = logical
        if callable(collection_name_func):
            try:
                backend_name = str(collection_name_func(logical))
            except Exception:
                backend_name = logical
        items.append({
            "name": logical,
            "backend_name": backend_name,
            "vector_fields": [{"name": key, "dim": val} for key, val in sorted(fields.items())],
            "registered": logical in getattr(client, "_vector_fields", {}),
        })
        seen.add(logical)
    items.sort(key=lambda item: item["name"])
    return items


def _apply_vector_collection_meta_fallback(client: Any, meta: Mapping[str, Any]) -> None:
    collection = str(meta.get("collection") or meta.get("collection_name") or "").strip()
    if not collection:
        return
    vector_fields_bucket = getattr(client, "_vector_fields", None)
    raw_vector_fields = meta.get("vector_fields") or {}
    if isinstance(vector_fields_bucket, dict) and isinstance(raw_vector_fields, Mapping):
        vector_fields_bucket[collection] = {
            str(name): int(dim)
            for name, dim in raw_vector_fields.items()
        }
    scalar_fields_bucket = getattr(client, "_scalar_fields", None)
    raw_scalar_fields = meta.get("scalar_fields") or []
    if isinstance(scalar_fields_bucket, dict) and isinstance(raw_scalar_fields, list):
        scalar_fields_bucket[collection] = [str(item) for item in raw_scalar_fields]
    _ensure_runtime_vector_model(client, collection)


def _build_runtime_vector_model(client: Any, collection: str) -> type[VectorORMModel] | None:
    vector_fields = dict((getattr(client, "_vector_fields", {}) or {}).get(collection, {}))
    if not vector_fields:
        return None
    scalar_fields = [
        str(item)
        for item in ((getattr(client, "_scalar_fields", {}) or {}).get(collection, []) or [])
        if str(item or "").strip()
    ]
    vector_metrics = dict((getattr(client, "_vector_field_metrics", {}) or {}).get(collection, {}))

    def exec_body(namespace: dict[str, Any]) -> None:
        annotations: dict[str, Any] = {}
        for field_name in scalar_fields:
            annotations[field_name] = Any
            namespace[field_name] = None
        for field_name, dim in vector_fields.items():
            annotations[field_name] = list[float]
            namespace[field_name] = VectorORMField(
                default_factory=list,
                index=VectorIndex(dim=int(dim), metric_type=vector_metrics.get(field_name)),
            )
        namespace["__annotations__"] = annotations

    model_cls = types.new_class(
        "StorageRuntimeVector_" + "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in collection).strip("_") or "Collection",
        (VectorORMModel,),
        {},
        exec_body,
    )
    model_cls.CollectionName = collection
    return model_cls


def _ensure_runtime_vector_model(client: Any, collection: str) -> None:
    collection_models = getattr(client, "_collection_models", None)
    if not isinstance(collection_models, dict):
        return
    if collection_models.get(collection) is not None:
        return
    model_cls = _build_runtime_vector_model(client, collection)
    if model_cls is not None:
        collection_models[collection] = model_cls


async def restore_vector_collection_state_async(client: Any) -> None:
    ensure_ready = getattr(client, "_ensure_ready", None)
    if callable(ensure_ready):
        try:
            result = ensure_ready()
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass
    async_restore_state = getattr(client, "_async_restore_collection_state", None)
    has_async_restore = callable(async_restore_state)
    if has_async_restore:
        try:
            result = async_restore_state()
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass
    restore_state = getattr(client, "_restore_collection_state", None)
    if not has_async_restore and callable(restore_state):
        try:
            result = restore_state()
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass


async def list_vector_collections_async(client: Any) -> list[dict[str, Any]]:
    await restore_vector_collection_state_async(client)
    return list_vector_collections(client)


def ensure_vector_collection_registered(client: Any, collection: str) -> dict[str, int]:
    fields = dict((getattr(client, "_vector_fields", {}) or {}).get(collection, {}))
    if fields:
        _ensure_runtime_vector_model(client, collection)
        return fields
    load_meta = getattr(client, "_load_collection_meta", None)
    apply_meta = getattr(client, "_apply_collection_meta", None)
    if (
        callable(load_meta)
        and callable(apply_meta)
        and not inspect.iscoroutinefunction(load_meta)
        and not inspect.iscoroutinefunction(apply_meta)
    ):
        try:
            payload = load_meta(collection)
            if isinstance(payload, dict):
                apply_meta(payload)
                fields = dict((getattr(client, "_vector_fields", {}) or {}).get(collection, {}))
                if fields:
                    _ensure_runtime_vector_model(client, collection)
                    return fields
        except Exception:
            pass
    utility = getattr(client, "_utility", None)
    collection_cls = getattr(client, "_Collection", None)
    alias = getattr(client, "_alias", None)
    collection_name_func = getattr(client, "_collection_name", None)
    if utility is None or collection_cls is None or collection_name_func is None:
        return fields
    try:
        backend_name = collection_name_func(collection)
        if not utility.has_collection(backend_name, using=alias):
            return fields
        coll = collection_cls(backend_name, using=alias)
        schema_fields: dict[str, int] = {}
        scalar_fields: list[str] = []
        for field in getattr(coll.schema, "fields", []) or []:
            params = getattr(field, "params", {}) or {}
            dim = params.get("dim") if isinstance(params, dict) else None
            field_name = str(getattr(field, "name", "") or "")
            dtype = str(getattr(field, "dtype", ""))
            if dim is not None or "VECTOR" in dtype.upper():
                schema_fields[field_name] = int(dim or 0)
                continue
            if field_name in {"", "id", "_id", "_expire_at", "_accessed_at"}:
                continue
            scalar_fields.append(field_name)
        if schema_fields:
            getattr(client, "_vector_fields", {})[collection] = schema_fields
            scalar_bucket = getattr(client, "_scalar_fields", None)
            if isinstance(scalar_bucket, dict):
                scalar_bucket[collection] = scalar_fields
            marker = getattr(client, "_mark_collection_bootstrapped", None)
            if callable(marker):
                marker(collection)
            _ensure_runtime_vector_model(client, collection)
            return schema_fields
    except Exception:
        return fields
    return fields


async def ensure_vector_collection_registered_async(client: Any, collection: str) -> dict[str, int]:
    fields = ensure_vector_collection_registered(client, collection)
    if fields:
        return fields
    load_meta = getattr(client, "_load_collection_meta", None)
    if callable(load_meta):
        try:
            payload = load_meta(collection)
            if inspect.isawaitable(payload):
                payload = await payload
            if isinstance(payload, Mapping):
                apply_meta = getattr(client, "_apply_collection_meta", None)
                if callable(apply_meta):
                    result = apply_meta(payload)
                    if inspect.isawaitable(result):
                        await result
                else:
                    _apply_vector_collection_meta_fallback(client, payload)
                fields = dict((getattr(client, "_vector_fields", {}) or {}).get(collection, {}))
                if fields:
                    _ensure_runtime_vector_model(client, collection)
                    return fields
        except Exception:
            pass
    await restore_vector_collection_state_async(client)
    fields = dict((getattr(client, "_vector_fields", {}) or {}).get(collection, {}))
    if fields:
        _ensure_runtime_vector_model(client, collection)
        return fields
    return ensure_vector_collection_registered(client, collection)
