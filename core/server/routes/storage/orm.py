# -*- coding: utf-8 -*-
# pyright: reportUnusedFunction=false

import asyncio

import json
import os
import re
import inspect
import time

from pathlib import Path
from typing import Any, Mapping, cast
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from core.storage.orm import MongoORMClient, RedisORMClient, SQL_ORM_Client, SQLiteORMClient
from core.storage.orm.client_base import _q, _query_to_mongo_filter, _to_mongo_object_id
from core.storage.orm.query_dict import QueryDict
from core.storage.orm.redis_search import RedisSearchQueryError
from core.utils.build_utils import build_cython as _build_cython

from ...app import internal_admin_path, on_before_app_created
from ...storage_utils import broadcast_runtime_storage_bootstrap, broadcast_runtime_storage_forget
from ._common import (
    _section_client_names,
    extract_schema_fields,
    get_backend_type,
    get_storage_config,
    jsonable_value,
    list_orm_collection_meta,
    list_orm_collection_meta_async,
    load_orm_model_if_present,
    orm_collection_count,
    sample_document_fields,
    storage_html_response,
    ttl_payload,
)
from ._models import (
    ORMCollectionActionResponse,
    ORMCollectionsResponse,
    ORMConfigResponse,
    ORMDeleteManyResponse,
    ORMDeleteResponse,
    ORMDocumentResponse,
    ORMExpireResponse,
    ORMIndexMutationResponse,
    ORMIndexesResponse,
    ORMQueryResponse,
    ORMSchemaResponse,
    StorageCleanupResponse,
    StorageClientsResponse,
    ORMUpsertResponse,
)

_orm_fast = _build_cython(Path(os.path.join(os.path.dirname(__file__), '_orm_fast.pyx')))
_c_nested_sort_value = _orm_fast.nested_sort_value
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ORMQueryBody(BaseModel):
    collection: str = Field(min_length=1)
    query: QueryDict | None = None
    query_json: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    selection: list[str] = Field(default_factory=list)
    sort: list["ORMSortItem"] = Field(default_factory=list)

class ORMSortItem(BaseModel):
    field: str = Field(min_length=1)
    direction: str = Field(default="asc", pattern="^(asc|desc)$")

class ORMUpsertBody(BaseModel):
    collection: str = Field(min_length=1)
    document: dict[str, Any]
    expire_seconds: float | None = None

class ORMExpireBody(BaseModel):
    collection: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    expire_seconds: float | None = None
class ORMCollectionRenameBody(BaseModel):
    collection: str = Field(min_length=1)
    new_collection: str = Field(min_length=1)
class ORMDeleteManyBody(BaseModel):
    collection: str = Field(min_length=1)
    object_ids: list[str] = Field(default_factory=list)

class ORMCreateCollectionBody(BaseModel):
    collection: str = Field(min_length=1)
    raw_schema: dict[str, object] | None = Field(default=None, alias="schema")

class ORMIndexFieldBody(BaseModel):
    field: str = Field(min_length=1)
    direction: str = Field(default="asc", pattern="^(asc|desc)$")

class ORMCreateIndexBody(BaseModel):
    collection: str = Field(min_length=1)
    fields: list[ORMIndexFieldBody] = Field(min_length=1)
    unique: bool = False
    name: str | None = None


def _orm_supports_index_manage(client: Any) -> bool:
    if isinstance(client, (SQLiteORMClient, MongoORMClient)):
        return True
    if isinstance(client, SQL_ORM_Client):
        try:
            engine = getattr(client, "_engine", None)
            dialect_name = getattr(getattr(engine, "dialect", None), "name", None)
            return str(dialect_name) in {"sqlite", "postgresql", "mysql", "mariadb"}
        except Exception:
            return False
    return False


def _orm_supports_query_count(client: Any) -> bool:
    return callable(getattr(client, "query_count", None))


def _orm_supports_sort(client: Any) -> bool:
    return callable(getattr(client, "search_sorted", None))


def _safe_index_slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "")).strip("_").lower() or "idx"


def _safe_sql_identifier(value: str, *, label: str = "identifier") -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        raise HTTPException(400, f"Invalid {label}: {value}")
    return text


async def _resolve_runtime_model_class(client: Any, collection: str) -> type[Any] | None:
    resolve_model = getattr(client, "_resolve_collection_model", None)
    if callable(resolve_model):
        try:
            model_cls = resolve_model(collection)
        except Exception:
            model_cls = None
        if model_cls is not None:
            return cast(type[Any], model_cls)
    for meta in await list_orm_collection_meta_async(client):
        if str(meta.get("collection_name") or "").strip() != str(collection or "").strip():
            continue
        return cast(type[Any] | None, load_orm_model_if_present(client, meta))
    return None


def _normalize_orm_api_query(query: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if query is None:
        return None
    normalized: dict[str, Any] = {}
    for raw_key, value in query.items():
        key = "id" if str(raw_key).strip() == "_id" else str(raw_key)
        if key in normalized and normalized[key] != value:
            raise HTTPException(400, "Conflicting id filters: use either `id` or `_id`, not both.")
        normalized[key] = value
    return normalized


def _orm_api_object_id(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("id") or payload.get("_id") or "")


def _orm_model_source_payload(meta: Mapping[str, Any] | None, model_cls: type[Any] | None) -> dict[str, str | None]:
    module_name = str((meta or {}).get("model_module") or getattr(model_cls, "__module__", "") or "").strip() or None
    model_name = str((meta or {}).get("model_name") or getattr(model_cls, "__name__", "") or "").strip() or None
    source_path: str | None = None
    source_text: str | None = None
    if model_cls is not None:
        try:
            source_file = inspect.getsourcefile(model_cls) or inspect.getfile(model_cls)
            if source_file:
                resolved_source = Path(source_file).resolve()
                try:
                    source_path = resolved_source.relative_to(_PROJECT_ROOT).as_posix()
                except ValueError:
                    source_path = str(resolved_source)
        except Exception:
            source_path = None
        try:
            source_text = inspect.getsource(model_cls)
        except Exception:
            source_text = None
    return {
        "model_module": module_name,
        "model_name": model_name,
        "model_source_path": source_path,
        "model_source": source_text,
    }


_MISSING = object()


def _normalize_orm_selection(selection: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_field in selection or []:
        field = str(raw_field or "").strip()
        if not field:
            continue
        field = "id" if field == "_id" else field
        if field in seen:
            continue
        seen.add(field)
        normalized.append(field)
    return normalized


def _lookup_selected_value(document: Any, dotted_field: str) -> Any:
    current = document
    for part in [segment for segment in str(dotted_field or "").split(".") if segment]:
        if isinstance(current, dict) and part in current:
            current = current.get(part)
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return _MISSING
    return current


def _build_selected_node(parts: list[str], value: Any) -> Any:
    if not parts:
        return value
    head, *tail = parts
    if head.isdigit():
        index = int(head)
        items: list[Any] = [None] * (index + 1)
        items[index] = _build_selected_node(tail, value)
        return items
    return {head: _build_selected_node(tail, value)}


def _merge_selected_nodes(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            merged[key] = _merge_selected_nodes(merged[key], value) if key in merged else value
        return merged
    if isinstance(existing, list) and isinstance(incoming, list):
        size = max(len(existing), len(incoming))
        merged: list[Any] = [None] * size
        for index in range(size):
            left = existing[index] if index < len(existing) else _MISSING
            right = incoming[index] if index < len(incoming) else _MISSING
            if right is _MISSING:
                merged[index] = None if left is _MISSING else left
            elif left is _MISSING or left is None:
                merged[index] = right
            else:
                merged[index] = _merge_selected_nodes(left, right)
        while merged and merged[-1] is None:
            merged.pop()
        return merged
    return incoming


def _normalize_orm_api_document(payload: Any, *, object_id: str | None = None) -> Any:
    value = jsonable_value(payload)
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    resolved_id = str(object_id or normalized.get("id") or normalized.get("_id") or "")
    if resolved_id:
        normalized["id"] = resolved_id
    normalized.pop("_id", None)
    return normalized


def _project_orm_api_document(payload: Any, *, object_id: str | None = None, selection: list[str] | None = None) -> Any:
    document = _normalize_orm_api_document(payload, object_id=object_id)
    selected_fields = _normalize_orm_selection(selection)
    if not selected_fields or not isinstance(document, dict):
        return document
    projected: dict[str, Any] = {}
    if document.get("id") is not None:
        projected["id"] = document.get("id")
    for field in selected_fields:
        if field == "id":
            continue
        value = _lookup_selected_value(document, field)
        if value is _MISSING:
            continue
        projected = _merge_selected_nodes(projected, _build_selected_node([part for part in field.split(".") if part], value))
    return projected


_MAX_FALLBACK_SORT_ROWS = 10000


def _orm_query_response_item(payload: Any, selection: list[str] | None = None) -> dict[str, Any]:
    object_id = _orm_api_object_id(payload if isinstance(payload, dict) else None)
    return {
        "id": object_id,
        "document": _project_orm_api_document(payload, object_id=object_id, selection=selection),
    }


async def _fallback_sorted_orm_query(
    client: Any,
    collection: str,
    query: dict[str, Any] | None,
    sort: list[ORMSortItem],
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    matched: list[dict[str, Any]] = []
    count = 0
    try:
        async for row in client.raw_query(collection, query, limit=None, offset=0):
            matched.append(_orm_query_response_item(row))
            count += 1
            if count > _MAX_FALLBACK_SORT_ROWS:
                import logging
                logging.getLogger(__name__).warning(
                    "ORM fallback sort exceeded %s rows for collection=%s query=%s. "
                    "Consider adding an index or narrowing the query.",
                    _MAX_FALLBACK_SORT_ROWS, collection, query,
                )
                raise HTTPException(
                    400,
                    f"排序查询结果超过 {_MAX_FALLBACK_SORT_ROWS} 行，无法执行内存排序。"
                    "请缩小查询范围或为该字段添加索引。",
                )
    except ValueError as exc:
        raise HTTPException(400, f"排序查询失败: {exc}") from exc

    ordered = _apply_sort(matched, sort)
    total = len(ordered)
    page = ordered[offset: offset + limit + 1]
    has_more = len(page) > limit
    return page[:limit], total, has_more


def _require_native_query_support(client: Any, collection: str, query: dict[str, Any] | None) -> None:
    if query is None:
        return
    if isinstance(query, dict) and not query:
        return
    if isinstance(client, MongoORMClient):
        mongo_filter = _query_to_mongo_filter(query, field_name_map=client._get_field_name_map(collection))
        if mongo_filter is None:
            raise HTTPException(400, "查询失败: Mongo query must be pushdown-compatible.")
        return
    if isinstance(client, RedisORMClient):
        try:
            client._build_query_string(collection, query)
        except RedisSearchQueryError as exc:
            raise HTTPException(400, f"查询失败: {exc}") from exc


def _ttl_from_expire_at_value(expire_at: object, *, now: float) -> float | None:
    if expire_at is None:
        return None
    if not isinstance(expire_at, (int, float, str)):
        return None
    try:
        ttl = float(expire_at) - now
    except Exception:
        return None
    return 0.0 if ttl <= 0 else ttl


async def _batch_query_ttls(client: Any, collection: str, object_ids: list[str]) -> dict[str, float | None]:
    ordered_ids = [object_id for object_id in dict.fromkeys(str(object_id or "").strip() for object_id in object_ids) if object_id]
    if not ordered_ids:
        return {}

    now = time.time()
    results: dict[str, float | None] = {}

    if isinstance(client, SQLiteORMClient):
        conn = await client._get_conn()
        sys_table = client._sys_table_sql(collection)
        for start in range(0, len(ordered_ids), 500):
            batch = ordered_ids[start:start + 500]
            placeholders = ", ".join("?" for _ in batch)
            cursor = await conn.execute(
                f'SELECT "id", expire_at FROM {sys_table} WHERE "id" IN ({placeholders})',
                tuple(batch),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            for row in rows:
                results[str(row[0])] = _ttl_from_expire_at_value(row[1], now=now)
        return results

    if isinstance(client, SQL_ORM_Client):
        engine = await client._ensure_schema_ready()
        dialect = str(engine.dialect.name).lower()
        sys_table = client._sys_table_sql(collection)
        async with engine.connect() as conn:
            for start in range(0, len(ordered_ids), 500):
                batch = ordered_ids[start:start + 500]
                params = {f"oid_{index}": object_id for index, object_id in enumerate(batch)}
                placeholders = ", ".join(f":oid_{index}" for index in range(len(batch)))
                result = await conn.execute(
                    client._sql_text(
                        f'SELECT {_q("id", dialect)} AS oid, expire_at FROM {sys_table} '
                        f'WHERE {_q("id", dialect)} IN ({placeholders})'
                    ),
                    params,
                )
                for row in result.fetchall():
                    results[str(row._mapping["oid"])] = _ttl_from_expire_at_value(row._mapping.get("expire_at"), now=now)
        return results

    if isinstance(client, MongoORMClient):
        cursor = client._collection(collection).find(
            {"_id": {"$in": [_to_mongo_object_id(object_id) for object_id in ordered_ids]}},
            {"_id": 1, "_sys.expire_at": 1},
        )
        try:
            async for doc in cursor:
                sys_meta = doc.get("_sys") or {}
                results[str(doc.get("_id"))] = _ttl_from_expire_at_value(sys_meta.get("expire_at"), now=now)
        finally:
            await cursor.close()
        return results

    if isinstance(client, RedisORMClient):
        await client._ensure_ready()
        pipe = client._client().pipeline(transaction=False)
        for object_id in ordered_ids:
            pipe.ttl(client._doc_key(collection, object_id))
        raw_ttls = await pipe.execute()
        for object_id, ttl in zip(ordered_ids, raw_ttls):
            ttl_value = int(ttl) if isinstance(ttl, (int, float)) else -2
            if ttl_value in {-2, -1}:
                results[object_id] = None
            elif ttl_value < 0:
                results[object_id] = 0.0
            else:
                results[object_id] = float(ttl_value)
        return results

    for object_id in ordered_ids:
        results[object_id] = await client.get_expire(collection, object_id)
    return results


def _get_exact_orm_config(client_name: str | None) -> tuple[str, Any]:
    section = get_storage_config().orm
    resolved_name = str(client_name or "default").strip() or "default"
    if resolved_name in type(section).model_fields:
        config = getattr(section, resolved_name, None)
        if config is not None:
            return resolved_name, config
    extra = section.extra or {}
    if resolved_name in extra:
        return resolved_name, extra[resolved_name]
    raise HTTPException(404, f"ORM client not found: {resolved_name}")


def _get_exact_orm_client(client_name: str | None) -> tuple[str, Any]:
    resolved_name, _ = _get_exact_orm_config(client_name)
    client = get_storage_config().orm.get_client(resolved_name, fallback="", fuzzy=False)
    return resolved_name, client


def _sqlite_index_expr(field_name: str) -> str:
    clean = str(field_name or "").strip()
    if not clean:
        raise HTTPException(400, "Index field is required")
    if clean in {"_id", "expire_at", "accessed_at", "created_at", "updated_at", "size"}:
        return clean
    return f'"' + clean.replace('"', '""') + '"'


def _postgres_index_expr(field_name: str) -> str:
    clean = str(field_name or "").strip()
    if not clean:
        raise HTTPException(400, "Index field is required")
    if clean in {"_id", "expire_at", "accessed_at", "created_at", "updated_at", "size"}:
        return clean
    return '"' + clean.replace('"', '""') + '"'


def _system_index_names_for_collection(collection: str, backend: str, *, sql_style: bool = False) -> set[str]:
    if backend == "mongo":
        return {"_id_", "created_at_1", "expire_at_1", "accessed_at_1"}
    if sql_style or backend in {"sqlite", "postgresql", "mysql", "mariadb"}:
        return {
            f"idx_{collection}_sys_expire",
            f"idx_{collection}_sys_access",
        }
    return {"_id_", f"idx_{collection}_expire", f"idx_{collection}_access", f"idx_{collection}_created"}


def _build_index_name(collection: str, fields: list[ORMIndexFieldBody], unique: bool, explicit_name: str | None) -> str:
    if explicit_name and explicit_name.strip():
        return _safe_index_slug(explicit_name)
    parts = [f"{_safe_index_slug(item.field)}_{'desc' if item.direction == 'desc' else 'asc'}" for item in fields]
    prefix = "uidx" if unique else "idx"
    return _safe_index_slug(f"{prefix}_{collection}_{'_'.join(parts)}")


def _parse_sqlite_index_sql(sql_text: str | None) -> tuple[list[dict[str, str]], bool]:
    text = str(sql_text or "")
    unique = bool(re.search(r"CREATE\s+UNIQUE\s+INDEX", text, flags=re.I))
    fields: list[dict[str, str]] = []
    json_matches = re.findall(r"json_extract\(payload_json,\s*'([^']+)'\)\s*(DESC|ASC)?", text, flags=re.I)
    for path, direction in json_matches:
        field = ".".join(re.findall(r'\."([^"]+)"', path)) or path.strip("$")
        fields.append({"field": field, "direction": (direction or "asc").lower()})
    column_matches = re.findall(r"\(([^\)]+)\)", text)
    if column_matches and not fields:
        for raw in column_matches[-1].split(","):
            value = raw.strip()
            if not value:
                continue
            direction = "desc" if value.upper().endswith(" DESC") else "asc"
            value = re.sub(r"\s+(ASC|DESC)$", "", value, flags=re.I).strip()
            fields.append({"field": value.strip('"'), "direction": direction})
    return fields, unique


def _list_sqlite_indexes(conn: Any, table: str, collection: str, *, sql_style: bool = False) -> list[dict[str, Any]]:
    table_name = table.strip('"')
    rows = conn.execute(f"PRAGMA index_list('{table_name}')").fetchall()
    system_names = _system_index_names_for_collection(collection, "sqlite", sql_style=sql_style)
    items: list[dict[str, Any]] = []
    for row in rows:
        row_map = dict(row) if not isinstance(row, tuple) else {
            "seq": row[0], "name": row[1], "unique": row[2], "origin": row[3] if len(row) > 3 else None, "partial": row[4] if len(row) > 4 else None,
        }
        name = str(row_map.get("name") or "")
        sql_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name = ?", (name,)).fetchone()
        sql_text = sql_row[0] if sql_row else None
        fields, parsed_unique = _parse_sqlite_index_sql(sql_text)
        items.append({
            "name": name,
            "unique": bool(row_map.get("unique") if sql_text is None else parsed_unique),
            "fields": fields,
            "backend": "sqlite",
            "managed_by_system": name in system_names,
            "definition": sql_text,
        })
    return items


async def _list_sqlite_indexes_async(conn: Any, table: str, collection: str, *, sql_style: bool = False) -> list[dict[str, Any]]:
    table_name = table.strip('"')
    cursor = await conn.execute(f"PRAGMA index_list('{table_name}')")
    rows = await cursor.fetchall()
    system_names = _system_index_names_for_collection(collection, "sqlite", sql_style=sql_style)
    items: list[dict[str, Any]] = []
    for row in rows:
        row_map = dict(row) if not isinstance(row, tuple) else {
            "seq": row[0], "name": row[1], "unique": row[2], "origin": row[3] if len(row) > 3 else None, "partial": row[4] if len(row) > 4 else None,
        }
        name = str(row_map.get("name") or "")
        sql_cursor = await conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name = ?", (name,))
        sql_row = await sql_cursor.fetchone()
        sql_text = sql_row[0] if sql_row else None
        fields, parsed_unique = _parse_sqlite_index_sql(sql_text)
        items.append({
            "name": name,
            "unique": bool(row_map.get("unique") if sql_text is None else parsed_unique),
            "fields": fields,
            "backend": "sqlite",
            "managed_by_system": name in system_names,
            "definition": sql_text,
        })
    return items


async def _list_postgres_indexes(client: SQL_ORM_Client, table: str, collection: str) -> list[dict[str, Any]]:
    system_names = _system_index_names_for_collection(collection, "postgresql", sql_style=True)
    engine = await client._ensure_schema_ready()
    async with engine.begin() as conn:
        result = await conn.execute(
            client._sql_text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = :table"
            ),
            {"table": table},
        )
        rows = result.fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        name = str(row[0])
        definition = str(row[1] or "")
        unique = "CREATE UNIQUE INDEX" in definition.upper()
        fields: list[dict[str, str]] = []
        json_matches = re.findall(r"#>> '\{([^}]+)\}'\)\s*(DESC|ASC)?", definition, flags=re.I)
        for path, direction in json_matches:
            fields.append({"field": path.replace(",", "."), "direction": (direction or "asc").lower()})
        if not fields:
            raw_match = re.search(r"\((.+)\)", definition)
            if raw_match:
                for raw in raw_match.group(1).split(","):
                    value = raw.strip()
                    if not value:
                        continue
                    direction = "desc" if value.upper().endswith(" DESC") else "asc"
                    value = re.sub(r"\s+(ASC|DESC)$", "", value, flags=re.I).strip()
                    fields.append({"field": value.strip('"() '), "direction": direction})
        items.append({
            "name": name,
            "unique": unique,
            "fields": fields,
            "backend": "postgresql",
            "managed_by_system": name in system_names,
            "definition": definition,
        })
    return items


def _mysql_json_path_to_field(path: str) -> str:
    dotted = str(path or "").strip().lstrip("$")
    dotted = dotted.replace('"', "")
    dotted = re.sub(r"\[(\d+)\]", r".\1", dotted)
    return dotted.lstrip(".")


def _mysql_index_expr(field_name: str) -> str:
    clean = str(field_name or "").strip()
    if not clean:
        raise HTTPException(400, "Index field is required")
    if clean in {"_id", "expire_at", "accessed_at", "created_at", "updated_at", "size"}:
        return clean
    return '`' + clean.replace('`', '``') + '`'


async def _list_mysql_indexes(client: SQL_ORM_Client, table: str, collection: str) -> list[dict[str, Any]]:
    system_names = _system_index_names_for_collection(collection, "mysql", sql_style=True)
    engine = await client._ensure_schema_ready()
    async with engine.begin() as conn:
        result = await conn.execute(
            client._sql_text(
                """
                SELECT INDEX_NAME, NON_UNIQUE, COLUMN_NAME, EXPRESSION, COLLATION, SEQ_IN_INDEX
                FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table
                ORDER BY INDEX_NAME, SEQ_IN_INDEX
                """
            ),
            {"table": table},
        )
        rows = result.fetchall()

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row[0])
        item = grouped.setdefault(
            name,
            {
                "name": name,
                "unique": not bool(row[1]),
                "fields": [],
                "backend": "mysql",
                "managed_by_system": name in system_names,
                "definition": [],
            },
        )
        column_name = row[2]
        expression = row[3]
        collation = str(row[4] or "A").upper()
        definition = str(column_name or expression or "")
        field_name = str(column_name or "")
        if not field_name and expression is not None:
            expression_text = str(expression)
            path_match = re.search(r"JSON_EXTRACT\([^,]+,\s*'([^']+)'\)", expression_text, flags=re.I)
            field_name = _mysql_json_path_to_field(path_match.group(1)) if path_match else expression_text
            definition = expression_text
        item["definition"].append(definition)
        item["fields"].append({
            "field": field_name,
            "direction": "desc" if collation == "D" else "asc",
        })

    return list(grouped.values())


async def _list_mongo_indexes(client: MongoORMClient, collection: str) -> list[dict[str, Any]]:
    system_names = _system_index_names_for_collection(collection, "mongo")
    payload = await client._collection(collection).index_information()
    items: list[dict[str, Any]] = []
    for name, meta in payload.items():
        keys = meta.get("key") or []
        fields = []
        for field_name, direction in keys:
            fields.append({"field": str(field_name), "direction": "desc" if int(direction) < 0 else "asc"})
        items.append({
            "name": name,
            "unique": bool(meta.get("unique")),
            "fields": fields,
            "backend": "mongo",
            "managed_by_system": name in system_names,
            "definition": meta,
        })
    return items


async def _list_orm_indexes(client: Any, collection: str, backend: str) -> list[dict[str, Any]]:
    if isinstance(client, SQLiteORMClient):
        conn = await client._get_conn()
        return [
            *await _list_sqlite_indexes_async(conn, client._table_sql(collection), collection),
            *await _list_sqlite_indexes_async(conn, client._sys_table_sql(collection), collection),
        ]
    if isinstance(client, MongoORMClient):
        return await _list_mongo_indexes(client, collection)
    if isinstance(client, SQL_ORM_Client):
        engine = await client._ensure_schema_ready()
        dialect = str(engine.dialect.name)
        if dialect == "sqlite":
            with engine.sync_engine.begin() as conn:
                return [
                    *_list_sqlite_indexes(conn.connection, client._table_sql(collection), collection, sql_style=True),
                    *_list_sqlite_indexes(conn.connection, client._sys_table_sql(collection), collection, sql_style=True),
                ]
        if dialect == "postgresql":
            return [
                *await _list_postgres_indexes(client, client._table_sql(collection), collection),
                *await _list_postgres_indexes(client, client._sys_table_sql(collection), collection),
            ]
        if dialect in {"mysql", "mariadb"}:
            return [
                *await _list_mysql_indexes(client, client._table_sql(collection), collection),
                *await _list_mysql_indexes(client, client._sys_table_sql(collection), collection),
            ]
    raise HTTPException(400, f"当前 backend 不支持索引管理：{backend}")


def _create_sqlite_index(conn: Any, table: str, collection: str, body: ORMCreateIndexBody) -> str:
    name = _safe_sql_identifier(_build_index_name(collection, body.fields, body.unique, body.name), label="index name")
    table = _safe_sql_identifier(table.strip('"'), label="table name")
    exprs = [f"{_sqlite_index_expr(item.field)} {'DESC' if item.direction == 'desc' else 'ASC'}" for item in body.fields]
    unique_sql = "UNIQUE " if body.unique else ""
    conn.execute(f"CREATE {unique_sql}INDEX IF NOT EXISTS {name} ON \"{table}\" ({', '.join(exprs)})")
    return name


async def _create_sqlite_index_async(conn: Any, table: str, collection: str, body: ORMCreateIndexBody) -> str:
    name = _safe_sql_identifier(_build_index_name(collection, body.fields, body.unique, body.name), label="index name")
    table = _safe_sql_identifier(table.strip('"'), label="table name")
    exprs = [f"{_sqlite_index_expr(item.field)} {'DESC' if item.direction == 'desc' else 'ASC'}" for item in body.fields]
    unique_sql = "UNIQUE " if body.unique else ""
    await conn.execute(f"CREATE {unique_sql}INDEX IF NOT EXISTS {name} ON \"{table}\" ({', '.join(exprs)})")
    return name


async def _create_postgres_index(client: SQL_ORM_Client, table: str, collection: str, body: ORMCreateIndexBody) -> str:
    name = _safe_sql_identifier(_build_index_name(collection, body.fields, body.unique, body.name), label="index name")
    table = _safe_sql_identifier(table.strip('"'), label="table name")
    exprs = [f"{_postgres_index_expr(item.field)} {'DESC' if item.direction == 'desc' else 'ASC'}" for item in body.fields]
    unique_sql = "UNIQUE " if body.unique else ""
    engine = await client._ensure_schema_ready()
    async with engine.begin() as conn:
        await conn.execute(client._sql_text(f"CREATE {unique_sql}INDEX IF NOT EXISTS {name} ON \"{table}\" ({', '.join(exprs)})"))
    return name


async def _create_mysql_index(client: SQL_ORM_Client, table: str, collection: str, body: ORMCreateIndexBody) -> str:
    name = _safe_sql_identifier(_build_index_name(collection, body.fields, body.unique, body.name), label="index name")
    table = _safe_sql_identifier(table.strip('`'), label="table name")
    exprs: list[str] = []
    for item in body.fields:
        expr = _mysql_index_expr(item.field)
        if re.fullmatch(r"(?:`[A-Za-z_][A-Za-z0-9_]*`|[A-Za-z_][A-Za-z0-9_]*)", expr):
            exprs.append(f"{expr} {'DESC' if item.direction == 'desc' else 'ASC'}")
        else:
            exprs.append(f"(({expr}))")
    unique_sql = "UNIQUE " if body.unique else ""
    try:
        engine = await client._ensure_schema_ready()
        async with engine.begin() as conn:
            await conn.execute(client._sql_text(f"CREATE {unique_sql}INDEX {name} ON `{table}` ({', '.join(exprs)})"))
    except Exception as exc:
        if "1061" not in str(exc):
            raise
    return name


async def _create_mongo_index(client: MongoORMClient, collection: str, body: ORMCreateIndexBody) -> str:
    keys = [(item.field, -1 if item.direction == 'desc' else 1) for item in body.fields]
    kwargs: dict[str, Any] = {"unique": body.unique}
    if body.name and body.name.strip():
        kwargs["name"] = body.name.strip()
    return str(await client._collection(collection).create_index(keys, **kwargs))


async def _drop_orm_index(client: Any, collection: str, index_name: str, backend: str) -> None:
    if not index_name.strip():
        raise HTTPException(400, "Index name is required")
    if isinstance(client, MongoORMClient):
        raw_index_name = str(index_name).strip()
        system_names = _system_index_names_for_collection(collection, "mongo")
        if raw_index_name in system_names:
            raise HTTPException(400, f"系统索引不允许删除：{raw_index_name}")
        await client._collection(collection).drop_index(raw_index_name)
        return
    if isinstance(client, SQLiteORMClient):
        safe_index_name = _safe_sql_identifier(index_name, label="index name")
        system_names = _system_index_names_for_collection(collection, "sqlite")
        if safe_index_name in system_names:
            raise HTTPException(400, f"系统索引不允许删除：{safe_index_name}")
        conn = await client._get_conn()
        await conn.execute(f"DROP INDEX IF EXISTS {safe_index_name}")
        await conn.commit()
        return
    if isinstance(client, SQL_ORM_Client):
        safe_index_name = _safe_sql_identifier(index_name, label="index name")
        engine = await client._ensure_schema_ready()
        dialect = str(engine.dialect.name)
        system_names = _system_index_names_for_collection(collection, backend, sql_style=True)
        if safe_index_name in system_names:
            raise HTTPException(400, f"系统索引不允许删除：{safe_index_name}")
        async with engine.begin() as conn:
            if dialect in {"mysql", "mariadb"}:
                table = _safe_sql_identifier(client._table_sql(collection).strip('`'), label="table name")
                await conn.execute(client._sql_text(f"DROP INDEX {safe_index_name} ON `{table}`"))
            else:
                await conn.execute(client._sql_text(f"DROP INDEX IF EXISTS {safe_index_name}"))
        return
    raise HTTPException(400, f"当前 backend 不支持索引删除：{backend}")


def _safe_collection_marker(collection: str) -> str:
    return "__storage_create__" + re.sub(r"[^0-9A-Za-z_]+", "_", collection).strip("_")


def _nested_sort_value(document: dict[str, Any], dotted_field: str) -> tuple[int, Any]:
    if _c_nested_sort_value is not None:
        return _c_nested_sort_value(document, dotted_field or "")

    current: Any = document
    for part in str(dotted_field or "").split("."):
        if not part:
            continue
        if isinstance(current, dict) and part in current:
            current = current.get(part)
        else:
            return (1, None)
    if current is None:
        return (1, None)
    if isinstance(current, bool):
        return (0, int(current))
    if isinstance(current, (int, float, str)):
        return (0, current)
    return (0, json.dumps(jsonable_value(current), ensure_ascii=False, sort_keys=True))


def _apply_sort(items: list[dict[str, Any]], sort_items: list[ORMSortItem]) -> list[dict[str, Any]]:
    ordered = list(items)
    for sort_item in reversed(sort_items or []):
        reverse = sort_item.direction == "desc"
        ordered.sort(key=lambda item: _nested_sort_value(item.get("document") or {}, sort_item.field), reverse=reverse)
    return ordered


async def _resolve_count_result(counter: Any, *args: Any) -> int | None:
    if not callable(counter):
        return None
    try:
        result = counter(*args)
        if inspect.isawaitable(result):
            result = await result
        return int(result)  # type: ignore
    except Exception:
        return None

@on_before_app_created
def register_storage_orm_routes(app: FastAPI):
    admin_path = internal_admin_path

    @app.get(admin_path("storage/orm"))
    async def storage_orm_page():
        return storage_html_response("orm")

    @app.get(admin_path("api/storage/orm/clients"), response_model=StorageClientsResponse)
    async def storage_orm_clients() -> StorageClientsResponse:
        section = get_storage_config().orm
        return StorageClientsResponse.model_validate({"clients": _section_client_names(section)})

    @app.get(admin_path("api/storage/orm/config"), response_model=ORMConfigResponse)
    async def storage_orm_config(client_name: str | None = Query(default=None, alias="client")) -> ORMConfigResponse:
        resolved_name, config = _get_exact_orm_config(client_name)
        _, client = _get_exact_orm_client(client_name)
        # 给前端一个明确的关联向量 client 名：优先同名，否则 default。
        vector_section = get_storage_config().vector
        vector_names = {item.get("name") for item in _section_client_names(vector_section)}
        if resolved_name in vector_names:
            associated_vector_client: str | None = resolved_name
        elif "default" in vector_names:
            associated_vector_client = "default"
        else:
            associated_vector_client = None
        return ORMConfigResponse.model_validate({
            "client_name": resolved_name,
            "backend": get_backend_type(config),
            "namespace": getattr(config, "namespace", "default"),
            "client_metadata": client.metadata(),
            "default_expire": getattr(config, "default_expire", None),
            "supports_ttl": True,
            "supports_drop_collection": True,
            "supports_create_collection": True,
            "supports_document_upsert": True,
            "supports_batch_delete": True,
            "supports_query_count": _orm_supports_query_count(client),
            "supports_sort": _orm_supports_sort(client),
            "supports_index_manage": _orm_supports_index_manage(client),
            "vector_client": associated_vector_client,
        })

    @app.get(admin_path("api/storage/orm/collections"), response_model=ORMCollectionsResponse)
    async def storage_orm_collections(client_name: str | None = Query(default=None, alias="client")) -> ORMCollectionsResponse:
        _, client = _get_exact_orm_client(client_name)
        metas = await list_orm_collection_meta_async(client)
        items: list[dict[str, Any]] = []
        for meta in metas:
            model_cls = load_orm_model_if_present(client, meta)
            schema_raw = meta.get("schema_json")
            if isinstance(schema_raw, str):
                try:
                    schema_raw = json.loads(schema_raw)
                except Exception:
                    schema_raw = None
            collection_name = str(meta.get("collection_name"))
            document_count = await _resolve_count_result(getattr(client, "collection_count", None), collection_name)
            if document_count is None:
                document_count = orm_collection_count(client, collection_name)
            items.append(
                {
                    "name": meta.get("collection_name"),
                    "typed_model": model_cls is not None,
                    "model_module": meta.get("model_module"),
                    "model_name": meta.get("model_name"),
                    "document_count": document_count,
                    "schema_fields": extract_schema_fields(schema_raw),
                }
            )
        return ORMCollectionsResponse.model_validate({"items": items})

    @app.get(admin_path("api/storage/orm/schema"), response_model=ORMSchemaResponse)
    async def storage_orm_schema(
        collection: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> ORMSchemaResponse:
        _, client = _get_exact_orm_client(client_name)
        metas = {str(item.get("collection_name")): item for item in await list_orm_collection_meta_async(client)}
        meta = metas.get(collection)
        if meta is None:
            raise HTTPException(404, "Collection not found")
        model_cls = load_orm_model_if_present(client, meta)
        schema_raw = meta.get("schema_json")
        if isinstance(schema_raw, str):
            try:
                schema_raw = json.loads(schema_raw)
            except Exception:
                schema_raw = None
        samples = [jsonable_value(item) async for item in client.search(collection, limit=30, as_model=False)]
        return ORMSchemaResponse.model_validate({
            "collection": collection,
            "typed_model": model_cls is not None,
            **_orm_model_source_payload(meta, model_cls),
            "schema_json": jsonable_value(schema_raw),
            "declared_fields": extract_schema_fields(schema_raw if isinstance(schema_raw, dict) else None),
            "sample_fields": sample_document_fields(samples),
        })

    @app.get(admin_path("api/storage/orm/indexes"), response_model=ORMIndexesResponse)
    async def storage_orm_indexes(
        collection: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> ORMIndexesResponse:
        _, config = _get_exact_orm_config(client_name)
        _, client = _get_exact_orm_client(client_name)
        backend = get_backend_type(config)
        if not _orm_supports_index_manage(client):
            raise HTTPException(400, f"当前 backend 不支持索引管理：{backend}")
        return ORMIndexesResponse.model_validate({"collection": collection, "items": await _list_orm_indexes(client, collection, backend)})

    @app.post(admin_path("api/storage/orm/index"), response_model=ORMIndexMutationResponse)
    async def storage_orm_create_index(body: ORMCreateIndexBody, client_name: str | None = Query(default=None, alias="client")) -> ORMIndexMutationResponse:
        _, config = _get_exact_orm_config(client_name)
        _, client = _get_exact_orm_client(client_name)
        backend = get_backend_type(config)
        if not _orm_supports_index_manage(client):
            raise HTTPException(400, f"当前 backend 不支持索引管理：{backend}")
        if isinstance(client, MongoORMClient):
            name = await _create_mongo_index(client, body.collection, body)
        elif isinstance(client, SQLiteORMClient):
            conn = await client._get_conn()
            name = await _create_sqlite_index_async(conn, client._table_sql(body.collection), body.collection, body)
            await conn.commit()
        elif isinstance(client, SQL_ORM_Client):
            engine = await client._ensure_schema_ready()
            dialect = str(engine.dialect.name)
            if dialect == "sqlite":
                async with engine.begin() as conn:
                    name = await conn.run_sync(
                        lambda sync_conn: _create_sqlite_index(
                            sync_conn.connection,
                            client._table_sql(body.collection),
                            body.collection,
                            body,
                        )
                    )
            elif dialect == "postgresql":
                name = await _create_postgres_index(client, client._table_sql(body.collection), body.collection, body)
            elif dialect in {"mysql", "mariadb"}:
                name = await _create_mysql_index(client, client._table_sql(body.collection), body.collection, body)
            else:
                raise HTTPException(400, f"当前 backend 不支持索引管理：{backend}")
        else:
            raise HTTPException(400, f"当前 backend 不支持索引管理：{backend}")
        return ORMIndexMutationResponse.model_validate({"created": True, "collection": body.collection, "name": name})

    @app.delete(admin_path("api/storage/orm/index"), response_model=ORMIndexMutationResponse)
    async def storage_orm_drop_index(
        collection: str = Query(..., min_length=1),
        name: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> ORMIndexMutationResponse:
        _, config = _get_exact_orm_config(client_name)
        _, client = _get_exact_orm_client(client_name)
        backend = get_backend_type(config)
        if not _orm_supports_index_manage(client):
            raise HTTPException(400, f"当前 backend 不支持索引管理：{backend}")
        await _drop_orm_index(client, collection, name, backend)
        return ORMIndexMutationResponse.model_validate({"deleted": True, "collection": collection, "name": name})

    @app.post(admin_path("api/storage/orm/query"), response_model=ORMQueryResponse)
    async def storage_orm_query(body: ORMQueryBody, client_name: str | None = Query(default=None, alias="client")) -> ORMQueryResponse:
        _, client = _get_exact_orm_client(client_name)
        selected_fields = _normalize_orm_selection(body.selection)
        query = body.query
        if body.query_json and not query:
            try:
                raw = json.loads(body.query_json)
                query = raw if isinstance(raw, dict) else None
            except Exception as exc:
                raise HTTPException(400, f"Invalid query_json: {exc}") from exc
        query = _normalize_orm_api_query(query)
        _require_native_query_support(client, body.collection, query)
        matched: list[dict[str, Any]] = []
        total: int | None = None
        has_more = False
        if body.sort:
            search_sorted = getattr(client, "search_sorted", None)
            sort_items = [(item.field, item.direction) for item in body.sort]
            fallback_to_memory_sort = not callable(search_sorted)
            if not fallback_to_memory_sort:
                try:
                    async for row in search_sorted(body.collection, query, sort=sort_items, limit=body.limit + 1, offset=body.offset, as_model=False):  # type: ignore
                        matched.append(_orm_query_response_item(row, selected_fields))
                except (ValueError, RedisSearchQueryError, NotImplementedError):
                    matched = []
                    fallback_to_memory_sort = True
            if fallback_to_memory_sort:
                matched, total, has_more = await _fallback_sorted_orm_query(
                    client,
                    body.collection,
                    query,
                    body.sort,
                    limit=body.limit,
                    offset=body.offset,
                )
            else:
                has_more = len(matched) > body.limit
                matched = matched[: body.limit]
        else:
            selected_search = getattr(client, "selected_search", None)

            async def _iter_items() -> Any:
                if selected_fields and callable(selected_search):
                    try:
                        async for row in selected_search(body.collection, selected_fields, query, limit=body.limit + 1, offset=body.offset):  # type: ignore[misc]
                            yield row
                        return
                    except (TypeError, ValueError, NotImplementedError):
                        pass
                try:
                    async for row in client.raw_query(body.collection, query, limit=body.limit + 1, offset=body.offset):
                        yield row
                except ValueError as exc:
                    raise HTTPException(400, f"查询失败: {exc}") from exc

            async for item in _iter_items():    # type: ignore
                matched.append(_orm_query_response_item(item, selected_fields))
            has_more = len(matched) > body.limit
            matched = matched[: body.limit]
        ttl_map = await _batch_query_ttls(
            client,
            body.collection,
            [str(item.get("id") or "") for item in matched],
        )
        for item in matched:
            item.update(ttl_payload(ttl_map.get(str(item.get("id") or ""))))
        items = matched
        if total is None:
            total = await _resolve_count_result(getattr(client, "query_count", None), body.collection, query)
        if total is None:
            total = body.offset + len(items) + (1 if has_more else 0)
        return ORMQueryResponse.model_validate({
            "collection": body.collection,
            "items": items,
            "total": total,
            "limit": body.limit,
            "offset": body.offset,
            "has_more": has_more,
        })

    @app.post(admin_path("api/storage/orm/collection"), response_model=ORMCollectionActionResponse)
    async def storage_orm_create_collection(body: ORMCreateCollectionBody, client_name: str | None = Query(default=None, alias="client")) -> ORMCollectionActionResponse:
        resolved_name, client = _get_exact_orm_client(client_name)
        await client.raw_create_collection(body.collection, body.raw_schema)
        model_cls = await _resolve_runtime_model_class(client, body.collection)
        await broadcast_runtime_storage_bootstrap(
            "orm",
            resolved_name,
            body.collection,
            model_module=getattr(model_cls, "__module__", None),
            model_name=getattr(model_cls, "__name__", None),
        )
        return ORMCollectionActionResponse.model_validate({"created": True, "collection": body.collection})
    @app.post(admin_path("api/storage/orm/collection/rename"), response_model=ORMCollectionActionResponse)
    async def storage_orm_rename_collection(body: ORMCollectionRenameBody, client_name: str | None = Query(default=None, alias="client")) -> ORMCollectionActionResponse:
        source = body.collection.strip()
        target = body.new_collection.strip()
        if not source or not target:
            raise HTTPException(400, "collection name cannot be empty")
        if source == target:
            return ORMCollectionActionResponse.model_validate({"collection": source, "renamed": False, "new_collection": target})
        resolved_name, client = _get_exact_orm_client(client_name)
        metas = {str(item.get("collection_name")): item for item in await list_orm_collection_meta_async(client)}
        if source not in metas:
            raise HTTPException(404, f"Collection `{source}` not found")
        if target in metas:
            raise HTTPException(409, f"Collection `{target}` already exists")
        schema_raw = metas[source].get("schema_json")
        if isinstance(schema_raw, str):
            try:
                schema_raw = json.loads(schema_raw)
            except Exception:
                schema_raw = None
        schema = schema_raw if isinstance(schema_raw, Mapping) else None
        await client.raw_create_collection(target, schema)
        moved = 0
        try:
            async for item in client.raw_query(source, None, limit=None):
                if isinstance(item, Mapping):
                    await client.raw_set(target, dict(item))
                    moved += 1
        except Exception:
            await client.raw_drop_collection(target)
            raise
        await client.raw_drop_collection(source)
        await broadcast_runtime_storage_forget("orm", resolved_name, source)
        model_cls = await _resolve_runtime_model_class(client, target)
        await broadcast_runtime_storage_bootstrap(
            "orm",
            resolved_name,
            target,
            model_module=getattr(model_cls, "__module__", None),
            model_name=getattr(model_cls, "__name__", None),
        )
        return ORMCollectionActionResponse.model_validate({"collection": source, "renamed": True, "new_collection": target, "moved": moved})
    @app.get(admin_path("api/storage/orm/document"), response_model=ORMDocumentResponse)
    async def storage_orm_document(
        collection: str = Query(..., min_length=1),
        object_id: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> ORMDocumentResponse:
        _, client = _get_exact_orm_client(client_name)
        document = await client.raw_get(collection, object_id)
        if document is None:
            raise HTTPException(404, "Document not found")
        ttl = await client.get_expire(collection, object_id)
        return ORMDocumentResponse.model_validate({
            "collection": collection,
            "id": object_id,
            "document": _normalize_orm_api_document(document, object_id=object_id),
            **ttl_payload(ttl),
        })

    @app.put(admin_path("api/storage/orm/document"), response_model=ORMUpsertResponse)
    async def storage_orm_upsert(body: ORMUpsertBody, client_name: str | None = Query(default=None, alias="client")) -> ORMUpsertResponse:
        resolved_name, client = _get_exact_orm_client(client_name)
        payload = dict(body.document)
        existed_before = False
        collection_exists = getattr(client, "_async_collection_exists", None)
        if callable(collection_exists):
            try:
                exists_result = collection_exists(body.collection)
                existed_before = bool(await exists_result) if inspect.isawaitable(exists_result) else bool(exists_result)
            except Exception:
                existed_before = False
        has_typed_model = False
        resolve_model = getattr(client, "_resolve_collection_model", None)
        if callable(resolve_model):
            try:
                has_typed_model = resolve_model(body.collection) is not None
            except Exception:
                has_typed_model = False
        try:
            object_id = await client.raw_set(body.collection, payload, expire=body.expire_seconds)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if (not existed_before) or (not has_typed_model):
            model_cls = await _resolve_runtime_model_class(client, body.collection)
            await broadcast_runtime_storage_bootstrap(
                "orm",
                resolved_name,
                body.collection,
                model_module=getattr(model_cls, "__module__", None),
                model_name=getattr(model_cls, "__name__", None),
            )
        ttl = await client.get_expire(body.collection, object_id)
        return ORMUpsertResponse.model_validate({"ok": True, "collection": body.collection, "id": object_id, **ttl_payload(ttl)})

    @app.delete(admin_path("api/storage/orm/document"), response_model=ORMDeleteResponse)
    async def storage_orm_delete_document(
        collection: str = Query(..., min_length=1),
        object_id: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> ORMDeleteResponse:
        _, client = _get_exact_orm_client(client_name)
        deleted = await client.raw_delete(collection, object_id)
        return ORMDeleteResponse.model_validate({"deleted": deleted, "collection": collection, "id": object_id})

    @app.post(admin_path("api/storage/orm/delete-many"), response_model=ORMDeleteManyResponse)
    async def storage_orm_delete_many(body: ORMDeleteManyBody, client_name: str | None = Query(default=None, alias="client")) -> ORMDeleteManyResponse:
        _, client = _get_exact_orm_client(client_name)
        object_ids = [str(object_id or "").strip() for object_id in body.object_ids]
        object_ids = [object_id for object_id in object_ids if object_id]
        try:
            results = await asyncio.wait_for(
                client.delete_many(body.collection, object_ids),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            results = {}
            for object_id_text in object_ids:
                results[object_id_text] = await client.raw_delete(body.collection, object_id_text)
        deleted = sum(1 for removed in results.values() if removed)
        items = [
            {"id": object_id_text, "deleted": bool(removed)}
            for object_id_text, removed in results.items()
        ]
        return ORMDeleteManyResponse.model_validate({"deleted": deleted > 0, "removed": deleted, "collection": body.collection, "items": items})

    @app.patch(admin_path("api/storage/orm/expire"), response_model=ORMExpireResponse)
    async def storage_orm_expire(body: ORMExpireBody, client_name: str | None = Query(default=None, alias="client")) -> ORMExpireResponse:
        _, client = _get_exact_orm_client(client_name)
        updated = await client.set_expire(body.collection, body.object_id, body.expire_seconds)
        if not updated:
            raise HTTPException(404, "Document not found")
        ttl = await client.get_expire(body.collection, body.object_id)
        return ORMExpireResponse.model_validate({"updated": updated, "collection": body.collection, "id": body.object_id, **ttl_payload(ttl)})

    @app.delete(admin_path("api/storage/orm/collection"), response_model=ORMCollectionActionResponse)
    async def storage_orm_drop_collection(
        collection: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> ORMCollectionActionResponse:
        resolved_name, client = _get_exact_orm_client(client_name)
        await client.raw_drop_collection(collection)
        await broadcast_runtime_storage_forget("orm", resolved_name, collection)
        return ORMCollectionActionResponse.model_validate({"deleted": True, "collection": collection})

    @app.post(admin_path("api/storage/orm/cleanup"), response_model=StorageCleanupResponse)
    async def storage_orm_cleanup(force: bool = True, client_name: str | None = Query(default=None, alias="client")) -> StorageCleanupResponse:
        _, client = _get_exact_orm_client(client_name)
        removed = await client.cleanup(force=force)
        return StorageCleanupResponse.model_validate({"removed": removed})
