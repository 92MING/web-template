# -*- coding: utf-8 -*-
# pyright: reportUnusedFunction=false
import asyncio
import json
import inspect
import re
import sqlite3
import time
import types
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, cast

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ...app import on_before_app_created
from ...storage_utils import broadcast_runtime_storage_bootstrap, broadcast_runtime_storage_forget

from ._common import (
    _section_client_names,
    ensure_vector_collection_registered,
    ensure_vector_collection_registered_async,
    extract_schema_fields,
    get_backend_type,
    get_storage_config,
    jsonable_value,
    list_vector_collections,
    list_vector_collections_async,
    sample_document_fields,
    storage_html_response,
    ttl_payload,
)
from ._models import (
    StorageCleanupResponse,
    StorageClientsResponse,
    VectorBrowseResponse,
    VectorCollectionActionResponse,
    VectorCollectionCreateResponse,
    VectorCollectionDetailResponse,
    VectorCollectionsResponse,
    VectorConfigResponse,
    VectorDeleteManyResponse,
    VectorDeleteResponse,
    VectorDocumentResponse,
    VectorExpireResponse,
    VectorSchemaResponse,
    VectorSearchResponse,
    VectorUpsertResponse,
)

from core.storage.base import _ttl_from_expire_at
from core.storage.orm.client_base import _to_mongo_object_id
from core.storage.vector import AnnoySQLiteVectorClient, MongoVectorClient, RedisVectorClient, VectorIndex, VectorORMField, VectorORMModel, resolve_vector_embedder, _BaseMilvusVectorClient
from core.utils.data_structs.files.medias import Audio, Image, Video


class VectorBrowseBody(BaseModel):
    collection: str = Field(min_length=1)
    filter: dict[str, Any] | None = None
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    sort: list["VectorSortItem"] = Field(default_factory=list)


class VectorSortItem(BaseModel):
    field: str = Field(min_length=1)
    direction: str = Field(default="asc", pattern="^(asc|desc)$")


class VectorSearchBody(BaseModel):
    collection: str = Field(min_length=1)
    mode: Literal["text", "content", "vector"] = "text"
    content_type: Literal["text", "image", "audio", "video"] = "text"
    query_text: str | None = None
    query_vector: list[float] | str | None = None
    vector_field: str | None = None
    filter: dict[str, Any] | None = None
    top_k: int = Field(default=10, ge=1, le=100)
    use_cache: bool = True
    save_cache: bool = True
    embedder: str | None = None


class VectorExpireBody(BaseModel):
    collection: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    expire_seconds: float | None = None


class VectorFieldSpec(BaseModel):
    name: str = Field(min_length=1)
    dim: int = Field(ge=1, le=32768)
    metric_type: Literal["COSINE", "L2", "EUCLIDEAN", "IP", "DOT", "MANHATTAN", "HAMMING"] | None = None


class VectorCreateCollectionBody(BaseModel):
    collection: str = Field(min_length=1)
    vector_fields: list[VectorFieldSpec] = Field(default_factory=list)
    scalar_fields: list[str] = Field(default_factory=list)

class VectorCollectionRenameBody(BaseModel):
    collection: str = Field(min_length=1)
    new_collection: str = Field(min_length=1)


class VectorUpsertBody(BaseModel):
    collection: str = Field(min_length=1)
    document: dict[str, Any]
    expire_seconds: float | None = None
    auto_embed_strings: bool = True


class VectorDeleteManyBody(BaseModel):
    collection: str = Field(min_length=1)
    object_ids: list[str] = Field(default_factory=list)


def _vector_supports_score(client: Any) -> bool:
    return isinstance(client, (AnnoySQLiteVectorClient, _BaseMilvusVectorClient)) or callable(getattr(client, "search_vector", None))


def _vector_supports_load(client: Any) -> bool:
    return isinstance(client, _BaseMilvusVectorClient)


def _vector_supports_offload(client: Any) -> bool:
    return isinstance(client, _BaseMilvusVectorClient)


def _embedding_service_names() -> list[str]:
    from core.ai.base import ServiceBase
    from core.ai.config import AIServicesConfig
    from core.ai.embedding import EmbeddingService

    names: list[str] = []
    cfg = AIServicesConfig.Global()
    predefined = getattr(cfg, "embedding", None) if cfg is not None else None
    if getattr(predefined, "default", None) is not None:
        names.append("default")
    extras = getattr(predefined, "extras", {}) or {}
    for key in sorted(str(name) for name in extras.keys()):
        if key not in names:
            names.append(key)
    for service_cls, key in getattr(ServiceBase, "ServiceInstances", {}).keys():
        if service_cls is EmbeddingService and key not in names:
            names.append(str(key))
    return names


def _get_named_embedding_service(name: str):
    from core.ai.config import AIServicesConfig
    from core.ai.embedding import EmbeddingService

    normalized = str(name or "").strip()
    if not normalized:
        raise HTTPException(400, "Embedder name is required")
    existing = EmbeddingService.GetInstance(normalized, fallback="")
    if existing is not None:
        return existing
    cfg = AIServicesConfig.Global()
    predefined = getattr(cfg, "embedding", None) if cfg is not None else None
    if predefined is None:
        raise HTTPException(404, f"Embedding service not found: {normalized}")
    service = predefined.get_service(normalized)
    if service is None:
        raise HTTPException(404, f"Embedding service not found: {normalized}")
    return service


def _parse_query_vector_input(raw: list[float] | str | None) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return [float(item) for item in raw]
    text = str(raw).strip()
    if not text:
        return None
    if text[0] in "[(" and text[-1] in "])":
        text = text[1:-1].strip()
    if not text:
        return []
    try:
        return [float(part.strip()) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(400, "query_vector 必须是合法的数字列表") from exc


def _vector_field_payload(client: Any, collection: str, field_name: str, dim: int) -> dict[str, Any]:
    metric_getter = getattr(client, "_get_field_metric", None)
    algorithm_getter = getattr(client, "_get_field_algorithm", None)
    metric_type = None
    algorithm = None
    if callable(metric_getter):
        try:
            metric_type = str(metric_getter(collection, field_name)).upper()
        except Exception:
            metric_type = None
    if callable(algorithm_getter):
        try:
            algorithm = str(algorithm_getter(collection, field_name, default="AUTOINDEX")).upper()
        except TypeError:
            try:
                algorithm = str(algorithm_getter(collection, field_name)).upper()
            except Exception:
                algorithm = None
        except Exception:
            algorithm = None
    has_bound_embedder = False
    embedder_name = None
    field_info_getter = getattr(client, "_get_vector_field_info", None)
    if callable(field_info_getter):
        try:
            _, field_info = field_info_getter(collection, field_name)
            embedder = getattr(field_info, "embedder", None)
            if embedder is not None:
                has_bound_embedder = True
                _, _, embedder_name = resolve_vector_embedder(embedder, default_service=None, default_model_name="default")
        except Exception:
            has_bound_embedder = False
            embedder_name = None
    return {
        "name": field_name,
        "dim": int(dim),
        "metric_type": metric_type,
        "algorithm": algorithm,
        "embedder_name": embedder_name,
        "has_bound_embedder": has_bound_embedder,
    }


def _vector_field_payloads(client: Any, collection: str, fields: dict[str, int]) -> list[dict[str, Any]]:
    return [_vector_field_payload(client, collection, name, dim) for name, dim in sorted(fields.items())]


async def _uploaded_content_to_media(upload: UploadFile, content_type: str) -> str | Image | Audio | Video:
    raw = await upload.read()
    if not raw:
        raise HTTPException(400, "Uploaded content is empty")
    kind = str(content_type or "").strip().lower()
    if not kind:
        mime = str(upload.content_type or "").lower()
        if mime.startswith("image/"):
            kind = "image"
        elif mime.startswith("audio/"):
            kind = "audio"
        elif mime.startswith("video/"):
            kind = "video"
    filename = str(upload.filename or "")
    suffix = Path(filename).suffix.lower()
    if not kind:
        if suffix in Image.Suffixes:
            kind = "image"
        elif suffix in Audio.Suffixes:
            kind = "audio"
        elif suffix in Video.Suffixes:
            kind = "video"
    if kind == "image":
        return Image(raw)
    if kind == "audio":
        return Audio(raw, format=suffix.lstrip(".") or None)
    if kind == "video":
        return Video(raw)
    raise HTTPException(400, "Unsupported content_type for uploaded file")


async def _run_vector_search(
    *,
    client: Any,
    collection: str,
    requested_mode: str,
    content_type: str,
    query_text: str | None,
    query_vector_raw: list[float] | str | None,
    vector_field: str | None,
    query_filter: dict[str, Any] | None,
    top_k: int,
    use_cache: bool,
    save_cache: bool,
    embedder_name: str | None,
    uploaded_content: str | Image | Audio | Video | None = None,
) -> dict[str, Any]:
    fields = await ensure_vector_collection_registered_async(client, collection)
    resolved_vector_field = vector_field or (next(iter(fields.keys())) if fields else None)
    if not resolved_vector_field:
        raise HTTPException(400, "No vector field available for this collection")

    query_vector = _parse_query_vector_input(query_vector_raw)
    search_input: Any = query_vector
    normalized_mode = requested_mode
    query_vector_dim = 0

    if requested_mode == "vector":
        if not query_vector:
            raise HTTPException(400, "query_vector is required in vector mode")
        dim = int(fields.get(resolved_vector_field) or 0)
        if dim and len(query_vector) != dim:
            raise HTTPException(400, f"query_vector dimension mismatch: expected {dim}, got {len(query_vector)}")
        search_input = list(query_vector)
        query_vector_dim = len(query_vector)
    else:
        normalized_mode = "content"
        content_value = uploaded_content
        if content_value is None:
            text_value = str(query_text or "").strip()
            if not text_value:
                raise HTTPException(400, "query_text is required in content mode")
            content_value = text_value
            content_type = "text"
        if embedder_name and embedder_name != "(model)":
            service = _get_named_embedding_service(embedder_name)
            embedded = await service.embedding(content_value, use_cache=use_cache, save_cache=save_cache)
            search_input = [float(item) for item in embedded]
        else:
            search_input = content_value
        if isinstance(search_input, list):
            query_vector_dim = len(search_input)
        else:
            query_vector_dim = int(fields.get(resolved_vector_field) or 0)

    t1 = time.perf_counter()
    try:
        results = [item async for item in client.search_vector(
            collection,
            search_input,
            field=resolved_vector_field,
            limit=top_k,
            query=query_filter,
            as_model=False,
        )]
    except Exception as exc:
        if requested_mode != "vector":
            raise HTTPException(503, f"Embedding search unavailable: {exc}") from exc
        raise HTTPException(400, f"Vector search failed: {exc}") from exc
    elapsed_search_ms = round((time.perf_counter() - t1) * 1000)
    metric_type = str(getattr(client, "_get_field_metric", lambda _c, _f: getattr(client, "_metric_type", "COSINE"))(collection, resolved_vector_field)).upper()
    items = []
    for idx, payload in enumerate(results, start=1):
        doc = dict(payload)
        object_id = _vector_api_object_id(doc)
        normalized_doc = _normalize_vector_api_payload(doc, object_id=object_id)
        score = doc.get("_score", None)
        items.append({
            "rank": idx,
            "score": round(float(score), 6) if score is not None else None,
            "id": object_id,
            "payload": normalized_doc,
            "raw_json": json.dumps(normalized_doc, ensure_ascii=False, indent=2),
        })
    return {
        "collection": collection,
        "mode": normalized_mode,
        "vector_field": resolved_vector_field,
        "metric_type": metric_type,
        "score_kind": _vector_score_kind(metric_type),
        "query_vector_dim": query_vector_dim,
        "elapsed_ms": elapsed_search_ms,
        "items": items,
    }


def _vector_score_kind(metric_type: str | None) -> str:
    metric = str(metric_type or "COSINE").upper()
    if metric in {"L2", "EUCLIDEAN", "MANHATTAN", "HAMMING"}:
        return "distance"
    return "score"


def _vector_collection_scalar_fields(client: Any, collection: str) -> list[str]:
    payload = getattr(client, "_scalar_fields", {}) or {}
    values = payload.get(collection, []) if isinstance(payload, dict) else []
    return [str(item) for item in values if str(item or "").strip()]


def _vector_collection_schema(client: Any, collection: str) -> dict[str, Any] | None:
    model_cls = (getattr(client, "_collection_models", {}) or {}).get(collection)
    if model_cls is None:
        return None
    schema_fn = getattr(model_cls, "model_json_schema", None)
    if callable(schema_fn):
        try:
            return cast(dict[str, Any], schema_fn())
        except Exception:
            return None
    return None


def _vector_api_object_id(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("id") or payload.get("_id") or "")


def _normalize_vector_api_payload(payload: Any, *, object_id: str | None = None) -> Any:
    value = jsonable_value(payload)
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    resolved_id = str(object_id or normalized.get("id") or normalized.get("_id") or "")
    if resolved_id:
        normalized["id"] = resolved_id
    normalized.pop("_id", None)
    return normalized


async def _vector_search_score_map(client: Any, collection: str, vector: list[float], vector_field: str, limit: int) -> dict[str, float]:
    if isinstance(client, AnnoySQLiteVectorClient):
        state = client._ensure_index(collection)
        idx = state.annoy_indexes.get(vector_field)
        if idx is None or state.next_int == 0:
            return {}
        search_k = min(state.next_int, max(limit * 5, limit))
        int_ids, distances = idx.get_nns_by_vector(list(vector), search_k, include_distances=True)
        mapping: dict[str, float] = {}
        for int_id, distance in zip(int_ids, distances):
            object_id = state.int_to_id.get(int_id)
            if object_id is not None:
                mapping[str(object_id)] = float(distance)
        return mapping
    if isinstance(client, _BaseMilvusVectorClient):
        collection_obj = client._collection(collection)
        rows = cast(Sequence[Sequence[Any]], collection_obj.search(
            data=[list(vector)],
            anns_field=vector_field,
            param={"metric_type": client._get_field_metric(collection, vector_field), "params": {}},
            limit=limit,
            output_fields=["id"],
        ))
        if not rows:
            return {}
        mapping = {}
        for hit in rows[0]:
            object_id = hit.entity.get("id") or hit.entity.get("_id") or str(hit.id)
            raw_score = getattr(hit, "score", None)
            if raw_score is None:
                raw_score = getattr(hit, "distance", None)
            if raw_score is not None:
                mapping[str(object_id)] = float(raw_score)
        return mapping
    return {}

def _safe_vector_model_name(collection: str) -> str:
    return "StorageVector_" + re.sub(r"[^0-9A-Za-z_]+", "_", collection).strip("_")

def _build_vector_model(collection: str, vector_fields: list[VectorFieldSpec], scalar_fields: list[str]) -> type[VectorORMModel]:
    def exec_body(namespace: dict[str, Any]) -> None:
        annotations: dict[str, Any] = {}
        for field_name in scalar_fields:
            clean_name = str(field_name or "").strip()
            if not clean_name or clean_name in {"id", "_id"}:
                continue
            annotations[clean_name] = Any
            namespace[clean_name] = None
        for spec in vector_fields:
            annotations[spec.name] = list[float]
            namespace[spec.name] = VectorORMField(
                default_factory=list,
                index=VectorIndex(dim=spec.dim, metric_type=spec.metric_type),
            )
        namespace["__annotations__"] = annotations

    model_cls = types.new_class(
        _safe_vector_model_name(collection),
        (VectorORMModel,),
        {},
        exec_body,
    )
    model_cls.CollectionName = collection
    return model_cls

async def _convert_vector_strings_if_needed(client: Any, collection: str, payload: dict[str, Any], auto_embed_strings: bool) -> dict[str, Any]:
    fields = await ensure_vector_collection_registered_async(client, collection)
    if not fields:
        return payload
    next_payload = dict(payload)
    if auto_embed_strings:
        for field_name in fields:
            value = next_payload.get(field_name)
            if isinstance(value, str):
                embed_field_value = getattr(client, 'embed_field_value', None)
                if callable(embed_field_value):
                    next_payload[field_name] = await embed_field_value(
                        collection,
                        value.strip(),
                        field=field_name,
                        use_cache=True,
                        save_cache=True,
                    )   # type: ignore
                else:
                    svc = _get_embedding_service()
                    next_payload[field_name] = await svc.embedding(value.strip(), use_cache=True, save_cache=True)
    for field_name, dim in fields.items():
        value = next_payload.get(field_name)
        if not isinstance(value, list):
            raise HTTPException(400, f"Vector field `{field_name}` 必须是向量数组，或在自动转换开启时提供字符串。")
        if dim and len(value) != dim:
            raise HTTPException(400, f"Vector field `{field_name}` 维度不匹配：期望 {dim}，实际 {len(value)}")
    return next_payload


def _collection_runtime(client: Any, collection: str):
    getter = getattr(client, "_collection", None)
    if callable(getter):
        try:
            return getter(collection)
        except Exception:
            return None
    return None


async def _vector_collection_exists_async(client: Any, collection: str) -> bool:
    async_exists = getattr(client, "_async_collection_exists", None)
    if callable(async_exists):
        try:
            result = async_exists(collection)
            if inspect.isawaitable(result):
                result = await result
            if bool(result):
                return True
        except Exception:
            pass
    sync_exists = getattr(client, "_collection_exists", None)
    if callable(sync_exists):
        try:
            result = sync_exists(collection)
            if inspect.isawaitable(result):
                result = await result
            if bool(result):
                return True
        except Exception:
            pass
    milvus_has = getattr(client, "_milvus_has_collection", None)
    if callable(milvus_has):
        try:
            result = milvus_has(collection)
            if inspect.isawaitable(result):
                result = await result
            if bool(result):
                return True
        except Exception:
            pass
    try:
        items = await list_vector_collections_async(client)
    except Exception:
        return False
    return any(str(item.get("name") or "").strip() == str(collection or "").strip() for item in items)


async def _ensure_vector_collection_accessible_async(client: Any, collection: str) -> dict[str, int]:
    fields = await ensure_vector_collection_registered_async(client, collection)
    if fields or await _vector_collection_exists_async(client, collection):
        return fields
    raise HTTPException(404, "Collection not found")


def _nested_sort_value(document: dict[str, Any], dotted_field: str) -> tuple[int, Any]:
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


def _apply_sort(items: list[dict[str, Any]], sort_items: list[VectorSortItem]) -> list[dict[str, Any]]:
    ordered = list(items)
    for sort_item in reversed(sort_items or []):
        reverse = sort_item.direction == "desc"
        ordered.sort(key=lambda item: _nested_sort_value(item, sort_item.field), reverse=reverse)
    return ordered


async def _resolve_count_result(counter: Any, *args: Any) -> int | None:
    if not callable(counter):
        return None
    try:
        result = counter(*args)
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout=5.0)
        return int(result)  # type: ignore
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None


def _get_exact_vector_config(client_name: str | None) -> tuple[str, Any]:
    section = get_storage_config().vector
    resolved_name = str(client_name or "default").strip() or "default"
    if resolved_name in type(section).model_fields:
        config = getattr(section, resolved_name, None)
        if config is not None:
            return resolved_name, config
    extra = section.extra or {}
    if resolved_name in extra:
        return resolved_name, extra[resolved_name]
    raise HTTPException(404, f"Vector client not found: {resolved_name}")


def _get_exact_vector_client(client_name: str | None) -> tuple[str, Any]:
    resolved_name, _ = _get_exact_vector_config(client_name)
    client = get_storage_config().vector.get_client(resolved_name, fallback="", fuzzy=False)
    return resolved_name, client


async def _batch_vector_ttls(client: Any, collection: str, object_ids: list[str]) -> dict[str, float | None]:
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for object_id in object_ids:
        object_id_text = str(object_id or "").strip()
        if not object_id_text or object_id_text in seen_ids:
            continue
        seen_ids.add(object_id_text)
        ordered_ids.append(object_id_text)

    results: dict[str, float | None] = {object_id: None for object_id in ordered_ids}
    if not ordered_ids:
        return results

    if isinstance(client, AnnoySQLiteVectorClient):
        collection_name = client._resolve_collection(collection)
        conn = client._ensure_started()
        sys_tbl = client._sys_table_name(collection_name)
        try:
            placeholders = ",".join("?" for _ in ordered_ids)
            rows = conn.execute(
                f'SELECT id, expire_at FROM "{sys_tbl}" WHERE id IN ({placeholders})',
                ordered_ids,
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for object_id, expire_at in rows:
            results[str(object_id)] = _ttl_from_expire_at(expire_at)
        return results

    if isinstance(client, MongoVectorClient):
        collection_name = client._resolve_collection(collection)
        mongo_ids = [_to_mongo_object_id(object_id) for object_id in ordered_ids]
        id_map = {
            str(mongo_object_id): object_id
            for object_id, mongo_object_id in zip(ordered_ids, mongo_ids)
        }
        cursor = client._collection(collection_name).find(
            {"_id": {"$in": mongo_ids}},
            {"_sys.expire_at": 1},
        )
        try:
            async for doc in cursor:
                object_id = id_map.get(str(doc.get("_id")))
                if object_id is not None:
                    results[object_id] = _ttl_from_expire_at((doc.get("_sys") or {}).get("expire_at"))
        finally:
            await cursor.close()
        return results

    if isinstance(client, RedisVectorClient):
        collection_name = client._resolve_collection(collection)
        await client._ensure_ready()
        pipe = client._client().pipeline(transaction=False)
        for object_id in ordered_ids:
            pipe.ttl(client._doc_key(collection_name, object_id))
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

    if isinstance(client, _BaseMilvusVectorClient):
        collection_name = client._resolve_collection(collection)
        await client._ensure_collection_loaded(collection_name)
        sidecar = client._get_sidecar(collection_name)
        if sidecar is not None:
            for object_id in ordered_ids:
                results[object_id] = _ttl_from_expire_at(await sidecar.get_expire(object_id))
            return results
        expr_items = ", ".join(json.dumps(object_id) for object_id in ordered_ids)
        rows = await client._milvus_query_rows(
            collection_name,
            expr=f"id in [{expr_items}]",
            output_fields=["id", "_expire_at"],
            limit=len(ordered_ids),
        )
        for row in rows:
            object_id = str(row.get("id") or "")
            if object_id:
                expire_at = row.get("_expire_at")
                results[object_id] = _ttl_from_expire_at(float(expire_at)) if isinstance(expire_at, (int, float)) else None
        return results

    ttl_cache = getattr(client, "_ttl", None)
    collection_name = getattr(client, "_resolve_collection", lambda value: value)(collection)
    if isinstance(ttl_cache, dict):
        for object_id in ordered_ids:
            results[object_id] = ttl_cache.get((collection_name, object_id))
        return results

    for object_id in ordered_ids:
        results[object_id] = await client.get_expire(collection, object_id)
    return results


def _get_embedding_service():
    from core.ai.embedding import EmbeddingService
    return EmbeddingService.Default()


def _embedding_service_declared_available() -> bool:
    from core.ai.config import AIServicesConfig
    from core.ai.embedding import EmbeddingService

    if EmbeddingService.GetInstance("default") is not None:
        return True
    cfg = AIServicesConfig.Global()
    if cfg is None:
        return False
    return getattr(cfg.embedding, "default", None) is not None

@on_before_app_created
def register_storage_vector_routes(app: FastAPI):

    @app.get("/admin/storage/vector")
    async def storage_vector_page():
        return storage_html_response("orm")

    @app.get("/admin/api/storage/vector/clients", response_model=StorageClientsResponse)
    async def storage_vector_clients() -> StorageClientsResponse:
        section = get_storage_config().vector
        return StorageClientsResponse.model_validate({"clients": _section_client_names(section)})

    @app.get("/admin/api/storage/vector/config", response_model=VectorConfigResponse)
    async def storage_vector_config(client_name: str | None = Query(default=None, alias="client")) -> VectorConfigResponse:
        resolved_name, config = _get_exact_vector_config(client_name)
        _, client = _get_exact_vector_client(client_name)
        embedding_available = _embedding_service_declared_available()
        return VectorConfigResponse.model_validate({
            "client_name": resolved_name,
            "backend": get_backend_type(config),
            "namespace": getattr(config, "namespace", "default"),
            "client_metadata": client.metadata(),
            "metric_type": getattr(config, "metric_type", "COSINE"),
            "supports_ttl": True,
            "supports_document_upsert": True,
            "supports_batch_delete": True,
            "supports_score": _vector_supports_score(client),
            "supports_create_collection": True,
            "supports_drop_collection": True,
            "supports_load": _vector_supports_load(client),
            "supports_offload": _vector_supports_offload(client),
            "supports_multimodal_query": embedding_available,
            "embedder_services": _embedding_service_names(),
        })

    @app.get("/admin/api/storage/vector/collections", response_model=VectorCollectionsResponse)
    async def storage_vector_collections(client_name: str | None = Query(default=None, alias="client")) -> VectorCollectionsResponse:
        _, client = _get_exact_vector_client(client_name)
        items = await list_vector_collections_async(client)
        count_query = getattr(client, "collection_count", None)
        for item in items:
            collection = item["name"]
            count = await _resolve_count_result(count_query, collection)
            item["item_count"] = count
            item["vector_fields"] = _vector_field_payloads(client, collection, {field["name"]: field["dim"] for field in item.get("vector_fields", [])})
        return VectorCollectionsResponse.model_validate({"items": items})

    @app.get("/admin/api/storage/vector/collection", response_model=VectorCollectionDetailResponse)
    async def storage_vector_collection(collection: str = Query(..., min_length=1), client_name: str | None = Query(default=None, alias="client")) -> VectorCollectionDetailResponse:
        _, client = _get_exact_vector_client(client_name)
        fields = await _ensure_vector_collection_accessible_async(client, collection)
        count = None
        count_query = getattr(client, "collection_count", None)
        count = await _resolve_count_result(count_query, collection)
        schema_json = _vector_collection_schema(client, collection)
        return VectorCollectionDetailResponse.model_validate({
            "collection": collection,
            "vector_fields": _vector_field_payloads(client, collection, fields),
            "metric_type": getattr(client, "_metric_type", "COSINE"),
            "scalar_fields": _vector_collection_scalar_fields(client, collection),
            "item_count": count,
            "schema_json": jsonable_value(schema_json),
            "declared_fields": extract_schema_fields(schema_json if isinstance(schema_json, dict) else None),
            "score_kind": _vector_score_kind(getattr(client, "_metric_type", "COSINE")),
        })

    @app.get("/admin/api/storage/vector/schema", response_model=VectorSchemaResponse)
    async def storage_vector_schema(collection: str = Query(..., min_length=1), client_name: str | None = Query(default=None, alias="client")) -> VectorSchemaResponse:
        _, client = _get_exact_vector_client(client_name)
        fields = await _ensure_vector_collection_accessible_async(client, collection)
        schema_json = _vector_collection_schema(client, collection)
        samples = [jsonable_value(item) async for item in client.raw_query(collection, limit=30, offset=0)]
        return VectorSchemaResponse.model_validate({
            "collection": collection,
            "metric_type": getattr(client, "_metric_type", "COSINE"),
            "vector_fields": _vector_field_payloads(client, collection, fields),
            "scalar_fields": _vector_collection_scalar_fields(client, collection),
            "schema_json": jsonable_value(schema_json),
            "declared_fields": extract_schema_fields(schema_json if isinstance(schema_json, dict) else None),
            "sample_fields": sample_document_fields(samples),
        })

    @app.post("/admin/api/storage/vector/collection", response_model=VectorCollectionCreateResponse)
    async def storage_vector_create_collection(body: VectorCreateCollectionBody, client_name: str | None = Query(default=None, alias="client")) -> VectorCollectionCreateResponse:
        if not body.vector_fields:
            raise HTTPException(400, "至少需要一个 vector field")
        resolved_name, client = _get_exact_vector_client(client_name)
        model_cls = _build_vector_model(body.collection, body.vector_fields, body.scalar_fields)
        try:
            await client.create_collection(model_cls)
        except ValueError as exc:
            raise HTTPException(400, f"创建 collection 失败: {exc}") from exc
        vector_field_map = {item.name: int(item.dim) for item in body.vector_fields}
        ensure_table = getattr(client, "_ensure_table", None)
        if callable(ensure_table):
            try:
                ensure_table(body.collection)
            except Exception:
                pass
        if hasattr(client, "_vector_fields"):
            getattr(client, "_vector_fields")[body.collection] = vector_field_map
        if hasattr(client, "_scalar_fields"):
            getattr(client, "_scalar_fields")[body.collection] = [str(item) for item in body.scalar_fields if str(item or "").strip()]
        if hasattr(client, "_collection_models"):
            getattr(client, "_collection_models")[body.collection] = model_cls
        ensure_vector_collection_registered(client, body.collection)
        await broadcast_runtime_storage_bootstrap("vector", resolved_name, body.collection)
        return VectorCollectionCreateResponse.model_validate({"created": True, "collection": body.collection, "vector_fields": [item.model_dump() for item in body.vector_fields]})

    @app.post("/admin/api/storage/vector/browse", response_model=VectorBrowseResponse)
    async def storage_vector_browse(body: VectorBrowseBody, client_name: str | None = Query(default=None, alias="client")) -> VectorBrowseResponse:
        _, client = _get_exact_vector_client(client_name)
        await _ensure_vector_collection_accessible_async(client, body.collection)
        if body.sort:
            search_sorted = getattr(client, "search_sorted", None)
            if not callable(search_sorted):
                raise HTTPException(400, "当前 backend 不支持原生排序浏览；已禁用全量扫描排序。")
            try:
                docs = [
                    item async for item in search_sorted(
                        body.collection,
                        query=body.filter,
                        sort=[(item.field, item.direction) for item in body.sort],
                        limit=body.limit + 1,
                        offset=body.offset,
                        as_model=False,
                    )   # type: ignore
                ]
            except ValueError as exc:
                raise HTTPException(400, f"排序浏览失败: {exc}") from exc
            has_more = len(docs) > body.limit
            docs = docs[: body.limit]
            count_query = getattr(client, "query_count", None)
            total = await _resolve_count_result(count_query, body.collection, body.filter)
            if total is None:
                total = body.offset + len(docs) + (1 if has_more else 0)
        else:
            try:
                docs = [item async for item in client.raw_query(body.collection, query=body.filter, limit=body.limit + 1, offset=body.offset)]
            except ValueError as exc:
                raise HTTPException(400, f"浏览失败: {exc}") from exc
            has_more = len(docs) > body.limit
            docs = docs[: body.limit]
            count_query = getattr(client, "query_count", None)
            total = await _resolve_count_result(count_query, body.collection, body.filter)
            if total is None:
                total = body.offset + len(docs) + (1 if has_more else 0)
        items = []
        ttl_map = await _batch_vector_ttls(
            client,
            body.collection,
            [_vector_api_object_id(doc if isinstance(doc, dict) else None) for doc in docs],
        )
        for doc in docs:
            object_id = _vector_api_object_id(doc if isinstance(doc, dict) else None)
            payload = _normalize_vector_api_payload(doc, object_id=object_id)
            ttl = ttl_map.get(object_id)
            items.append({
                "id": object_id,
                "payload": payload,
                "raw_json": json.dumps(payload, ensure_ascii=False, indent=2),
                **ttl_payload(ttl),
            })
        return VectorBrowseResponse.model_validate({"collection": body.collection, "items": items, "limit": body.limit, "offset": body.offset, "has_more": has_more, "total": total})

    @app.get("/admin/api/storage/vector/document", response_model=VectorDocumentResponse)
    async def storage_vector_document(
        collection: str = Query(..., min_length=1),
        object_id: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> VectorDocumentResponse:
        _, client = _get_exact_vector_client(client_name)
        await _ensure_vector_collection_accessible_async(client, collection)
        payload = await client.raw_get(collection, object_id)
        if payload is None:
            raise HTTPException(404, "Document not found")
        ttl = await client.get_expire(collection, object_id)
        return VectorDocumentResponse.model_validate({
            "collection": collection,
            "id": object_id,
            "payload": _normalize_vector_api_payload(payload, object_id=object_id),
            "raw_json": json.dumps(_normalize_vector_api_payload(payload, object_id=object_id), ensure_ascii=False, indent=2),
            **ttl_payload(ttl),
        })

    @app.put("/admin/api/storage/vector/document", response_model=VectorUpsertResponse)
    async def storage_vector_upsert(body: VectorUpsertBody, client_name: str | None = Query(default=None, alias="client")) -> VectorUpsertResponse:
        _, client = _get_exact_vector_client(client_name)
        await ensure_vector_collection_registered_async(client, body.collection)
        payload = await _convert_vector_strings_if_needed(client, body.collection, dict(body.document), body.auto_embed_strings)
        try:
            object_id = await client.raw_set(body.collection, payload, expire=body.expire_seconds)
        except ValueError as exc:
            raise HTTPException(400, f"写入失败: {exc}") from exc
        ttl = await client.get_expire(body.collection, object_id)
        return VectorUpsertResponse.model_validate({"ok": True, "collection": body.collection, "id": object_id, **ttl_payload(ttl)})

    @app.post("/admin/api/storage/vector/search", response_model=VectorSearchResponse)
    async def storage_vector_search(body: VectorSearchBody, client_name: str | None = Query(default=None, alias="client")) -> VectorSearchResponse:
        _, client = _get_exact_vector_client(client_name)
        payload = await _run_vector_search(
            client=client,
            collection=body.collection,
            requested_mode="vector" if body.mode == "vector" else "content",
            content_type=body.content_type,
            query_text=body.query_text,
            query_vector_raw=body.query_vector,
            vector_field=body.vector_field,
            query_filter=body.filter,
            top_k=body.top_k,
            use_cache=body.use_cache,
            save_cache=body.save_cache,
            embedder_name=body.embedder,
        )
        return VectorSearchResponse.model_validate(payload)

    @app.post("/admin/api/storage/vector/search/upload", response_model=VectorSearchResponse)
    async def storage_vector_search_upload(
        collection: str = Form(...),
        content_type: Literal["image", "audio", "video"] = Form(...),
        vector_field: str | None = Form(default=None),
        filter_json: str | None = Form(default=None),
        top_k: int = Form(default=10),
        use_cache: bool = Form(default=True),
        save_cache: bool = Form(default=True),
        embedder: str | None = Form(default=None),
        file: UploadFile = File(...),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> VectorSearchResponse:
        _, client = _get_exact_vector_client(client_name)
        query_filter = None
        if filter_json and filter_json.strip():
            try:
                query_filter = json.loads(filter_json)
            except json.JSONDecodeError as exc:
                raise HTTPException(400, "filter_json must be valid JSON") from exc
            if not isinstance(query_filter, dict):
                raise HTTPException(400, "filter_json must be a JSON object")
        payload = await _run_vector_search(
            client=client,
            collection=collection,
            requested_mode="content",
            content_type=content_type,
            query_text=None,
            query_vector_raw=None,
            vector_field=vector_field,
            query_filter=query_filter,
            top_k=max(1, min(100, int(top_k))),
            use_cache=bool(use_cache),
            save_cache=bool(save_cache),
            embedder_name=embedder,
            uploaded_content=await _uploaded_content_to_media(file, content_type),
        )
        return VectorSearchResponse.model_validate(payload)

    @app.post("/admin/api/storage/vector/delete-many", response_model=VectorDeleteManyResponse)
    async def storage_vector_delete_many(body: VectorDeleteManyBody, client_name: str | None = Query(default=None, alias="client")) -> VectorDeleteManyResponse:
        _, client = _get_exact_vector_client(client_name)
        await _ensure_vector_collection_accessible_async(client, body.collection)
        delete_many = getattr(client, "delete_many", None)
        if callable(delete_many):
            result = delete_many(body.collection, body.object_ids)
            try:
                deleted_map = await asyncio.wait_for(result, timeout=10.0) if inspect.isawaitable(result) else result
            except asyncio.TimeoutError:
                deleted_map = None
            if isinstance(deleted_map, dict):
                normalized = deleted_map
                items = [
                    {"id": object_id_text, "deleted": bool(normalized.get(object_id_text, False))}
                    for object_id_text in [str(object_id or "").strip() for object_id in body.object_ids]
                    if object_id_text
                ]
                removed = sum(1 for item in items if item["deleted"])
                return VectorDeleteManyResponse.model_validate({"deleted": removed > 0, "removed": removed, "collection": body.collection, "items": items})
        removed = 0
        items = []
        for object_id in body.object_ids:
            object_id_text = str(object_id or "").strip()
            if not object_id_text:
                continue
            deleted = await client.raw_delete(body.collection, object_id_text)
            removed += int(bool(deleted))
            items.append({"id": object_id_text, "deleted": bool(deleted)})
        return VectorDeleteManyResponse.model_validate({"deleted": removed > 0, "removed": removed, "collection": body.collection, "items": items})

    @app.delete("/admin/api/storage/vector/document", response_model=VectorDeleteResponse)
    async def storage_vector_delete_document(
        collection: str = Query(..., min_length=1),
        object_id: str = Query(..., min_length=1),
        client_name: str | None = Query(default=None, alias="client"),
    ) -> VectorDeleteResponse:
        _, client = _get_exact_vector_client(client_name)
        await _ensure_vector_collection_accessible_async(client, collection)
        deleted = await client.raw_delete(collection, object_id)
        return VectorDeleteResponse.model_validate({"deleted": deleted, "collection": collection, "id": object_id})

    @app.delete("/admin/api/storage/vector/collection", response_model=VectorCollectionActionResponse)
    async def storage_vector_drop_collection(collection: str = Query(..., min_length=1), client_name: str | None = Query(default=None, alias="client")) -> VectorCollectionActionResponse:
        resolved_name, client = _get_exact_vector_client(client_name)
        await _ensure_vector_collection_accessible_async(client, collection)
        await client.drop_collection(collection)
        await broadcast_runtime_storage_forget("vector", resolved_name, collection)
        return VectorCollectionActionResponse.model_validate({"deleted": True, "collection": collection})

    @app.post("/admin/api/storage/vector/collection/rename", response_model=VectorCollectionActionResponse)
    async def storage_vector_rename_collection(body: VectorCollectionRenameBody, client_name: str | None = Query(default=None, alias="client")) -> VectorCollectionActionResponse:
        source = body.collection.strip()
        target = body.new_collection.strip()
        if not source or not target:
            raise HTTPException(400, "collection name cannot be empty")
        if source == target:
            return VectorCollectionActionResponse.model_validate({"collection": source, "renamed": False, "new_collection": target})
        resolved_name, client = _get_exact_vector_client(client_name)
        fields = await _ensure_vector_collection_accessible_async(client, source)
        existing = {str(item.get("name")) for item in await list_vector_collections_async(client)}
        if target in existing:
            raise HTTPException(409, f"Collection `{target}` already exists")
        vector_fields = _vector_field_payloads(client, source, fields)
        scalar_fields = _vector_collection_scalar_fields(client, source)
        model_cls = _build_vector_model(
            target,
            [
                VectorFieldSpec(
                    name=item["name"],
                    dim=int(item["dim"]),
                    metric_type=cast(Any, item.get("metric_type")),
                )
                for item in vector_fields
            ],
            scalar_fields,
        )
        moved = 0
        try:
            await client.create_collection(model_cls)
            async for item in client.raw_query(source, None, limit=None):
                if isinstance(item, Mapping):
                    await client.raw_set(target, dict(item))
                    moved += 1
        except Exception:
            try:
                await client.drop_collection(target)
            except Exception:
                pass
            raise
        await client.drop_collection(source)
        await broadcast_runtime_storage_forget("vector", resolved_name, source)
        await broadcast_runtime_storage_bootstrap("vector", resolved_name, target)
        return VectorCollectionActionResponse.model_validate({"collection": source, "renamed": True, "new_collection": target, "moved": moved})

    @app.post("/admin/api/storage/vector/collection/load", response_model=VectorCollectionActionResponse)
    async def storage_vector_load_collection(collection: str = Query(..., min_length=1), client_name: str | None = Query(default=None, alias="client")) -> VectorCollectionActionResponse:
        _, client = _get_exact_vector_client(client_name)
        await _ensure_vector_collection_accessible_async(client, collection)
        loader = getattr(client, "load_collection", None)
        if callable(loader):
            result = loader(collection)
            if inspect.isawaitable(result):
                await result
            return VectorCollectionActionResponse.model_validate({"loaded": True, "collection": collection})
        collection_obj = _collection_runtime(client, collection)
        if collection_obj is None or not hasattr(collection_obj, "load"):
            raise HTTPException(400, "Current vector backend does not support load")
        collection_obj.load()   # type: ignore
        return VectorCollectionActionResponse.model_validate({"loaded": True, "collection": collection})

    @app.post("/admin/api/storage/vector/collection/offload", response_model=VectorCollectionActionResponse)
    async def storage_vector_offload_collection(collection: str = Query(..., min_length=1), client_name: str | None = Query(default=None, alias="client")) -> VectorCollectionActionResponse:
        _, client = _get_exact_vector_client(client_name)
        await _ensure_vector_collection_accessible_async(client, collection)
        offloader = getattr(client, "offload_collection", None)
        if callable(offloader):
            result = offloader(collection)
            if inspect.isawaitable(result):
                await result
            return VectorCollectionActionResponse.model_validate({"offloaded": True, "collection": collection})
        collection_obj = _collection_runtime(client, collection)
        releaser = getattr(collection_obj, "release", None) if collection_obj is not None else None
        if releaser is None:
            raise HTTPException(400, "Current vector backend does not support offload")
        releaser()
        loaded_collections = getattr(client, "_loaded_collections", None)
        if isinstance(loaded_collections, set):
            loaded_collections.discard(collection)
        return VectorCollectionActionResponse.model_validate({"offloaded": True, "collection": collection})

    @app.patch("/admin/api/storage/vector/expire", response_model=VectorExpireResponse)
    async def storage_vector_expire(body: VectorExpireBody, client_name: str | None = Query(default=None, alias="client")) -> VectorExpireResponse:
        _, client = _get_exact_vector_client(client_name)
        await _ensure_vector_collection_accessible_async(client, body.collection)
        updated = await client.set_expire(body.collection, body.object_id, body.expire_seconds)
        if not updated:
            raise HTTPException(404, "Document not found")
        return VectorExpireResponse.model_validate({"updated": updated, "collection": body.collection, "id": body.object_id, **ttl_payload(body.expire_seconds)})

    @app.post("/admin/api/storage/vector/cleanup", response_model=StorageCleanupResponse)
    async def storage_vector_cleanup(force: bool = True, client_name: str | None = Query(default=None, alias="client")) -> StorageCleanupResponse:
        _, client = _get_exact_vector_client(client_name)
        removed = await client.cleanup(force=force)
        return StorageCleanupResponse.model_validate({"removed": removed})
