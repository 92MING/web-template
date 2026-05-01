import os
import json
import asyncio
import logging
import importlib
import inspect

from collections.abc import Iterable, Mapping
from typing import Awaitable, Callable, TypedDict, cast

from core.storage.base import StorageClientBase
from core.storage.config import (
    ORMStorageConfig,
    StorageConfig,
    StorageConfigBase,
    VectorStorageConfig,
    _ORM_PREFLIGHT_ENV,
    _VECTOR_PREFLIGHT_ENV,
)
from core.storage.orm import (
    MongoORMClient,
    ORMModel,
    ORM_ClientBase,
    RedisORMClient,
    SQL_ORM_Client,
    SQLiteORMClient,
)
from core.storage.orm.client_base import _safe_model_schema
from core.storage.vector import VectorClientBase, VectorORMModel

_logger = logging.getLogger(__name__)


type _CollectionPreflightMap = dict[str, list[str]]
type _StoragePreflightPayload = dict[str, _CollectionPreflightMap]
type _CollectionMetaRow = dict[str, object]
type _CollectionMetaRows = list[_CollectionMetaRow]
type _CollectionMetaClient = ORM_ClientBase | VectorClientBase
type _ClientGroup = tuple[str, list[str], StorageClientBase]


class _ClientNameGroup(TypedDict):
    primary: str
    names: list[str]


async def _maybe_await(value: object) -> object:
    if inspect.isawaitable(value):
        return await cast(Awaitable[object], value)
    return value


async def apply_runtime_storage_bootstrap(
    storage_kind: str,
    client_name: str,
    collection: str,
    model_module: str | None = None,
    model_name: str | None = None,
) -> dict[str, object]:
    resolved_name = str(client_name or "default")
    collection_name = str(collection or "").strip()
    if not collection_name:
        raise ValueError("collection is required")

    storage_config = StorageConfig.Global()
    if storage_kind == "orm":
        resolved_name, _ = storage_config.orm._resolve_config_for_name(resolved_name)
        client = storage_config.orm.get_client(resolved_name)
        model_cls: type[ORMModel] | None = None
        if model_module and model_name:
            model_cls = _load_model_from_meta({
                "model_module": model_module,
                "model_name": model_name,
            })
        if model_cls is None:
            resolve_model = getattr(client, "_resolve_collection_model", None)
            if callable(resolve_model):
                try:
                    model_cls = resolve_model(collection_name)
                except Exception:
                    model_cls = None
        register_model = getattr(client, "register_model", None)
        if model_cls is not None and callable(register_model):
            try:
                register_model(model_cls)
            except Exception:
                pass
        marker = getattr(client, "mark_collection_bootstrapped", None)
        if callable(marker):
            marker(collection_name)
        restore_state = getattr(client, "_restore_collection_state", None)
        if callable(restore_state):
            try:
                await _maybe_await(restore_state())
            except Exception:
                pass
        return {
            "ok": True,
            "pid": os.getpid(),
            "storage_kind": "orm",
            "client_name": resolved_name,
            "collection": collection_name,
        }

    if storage_kind == "vector":
        resolved_name, _ = storage_config.vector._resolve_config_for_name(resolved_name)
        client = storage_config.vector.get_client(resolved_name)
        payload: object | None = None
        load_meta = getattr(client, "_load_collection_meta", None)
        if callable(load_meta):
            try:
                payload = await _maybe_await(load_meta(collection_name))
            except Exception:
                payload = None
        apply_meta = getattr(client, "_apply_collection_meta", None)
        if isinstance(payload, Mapping) and callable(apply_meta):
            try:
                await _maybe_await(apply_meta(payload))
            except Exception:
                payload = None
        if payload is None:
            restore_state = getattr(client, "_async_restore_collection_state", None)
            if callable(restore_state):
                try:
                    await _maybe_await(restore_state())
                except Exception:
                    pass
            restore_state = getattr(client, "_restore_collection_state", None)
            if callable(restore_state):
                try:
                    await _maybe_await(restore_state())
                except Exception:
                    pass
        marker = getattr(client, "mark_collection_bootstrapped", None)
        if callable(marker):
            marker(collection_name)
        else:
            marker = getattr(client, "_mark_collection_bootstrapped", None)
            if callable(marker):
                marker(collection_name)
        return {
            "ok": True,
            "pid": os.getpid(),
            "storage_kind": "vector",
            "client_name": resolved_name,
            "collection": collection_name,
        }

    raise ValueError(f"Unsupported storage kind: {storage_kind}")


async def apply_runtime_storage_forget(
    storage_kind: str,
    client_name: str,
    collection: str,
) -> dict[str, object]:
    resolved_name = str(client_name or "default")
    collection_name = str(collection or "").strip()
    if not collection_name:
        raise ValueError("collection is required")

    storage_config = StorageConfig.Global()
    if storage_kind == "orm":
        resolved_name, _ = storage_config.orm._resolve_config_for_name(resolved_name)
        client = storage_config.orm.get_client(resolved_name)
        forget = getattr(client, "_forget_collection", None)
        if callable(forget):
            forget(collection_name)
        resolve_model = getattr(client, "_resolve_collection_model", None)
        register_model = getattr(client, "register_model", None)
        if callable(resolve_model) and callable(register_model):
            try:
                model_cls = resolve_model(collection_name)
            except Exception:
                model_cls = None
            if model_cls is not None:
                try:
                    register_model(model_cls)
                except Exception:
                    pass
        return {
            "ok": True,
            "pid": os.getpid(),
            "storage_kind": "orm",
            "client_name": resolved_name,
            "collection": collection_name,
        }

    if storage_kind == "vector":
        resolved_name, _ = storage_config.vector._resolve_config_for_name(resolved_name)
        client = storage_config.vector.get_client(resolved_name)
        forget = getattr(client, "_forget_collection", None)
        if callable(forget):
            forget(collection_name)
        return {
            "ok": True,
            "pid": os.getpid(),
            "storage_kind": "vector",
            "client_name": resolved_name,
            "collection": collection_name,
        }

    raise ValueError(f"Unsupported storage kind: {storage_kind}")


async def broadcast_runtime_storage_bootstrap(
    storage_kind: str,
    client_name: str,
    collection: str,
    model_module: str | None = None,
    model_name: str | None = None,
) -> list[dict[str, object]]:
    from .app import send_message_to_worker
    from .shared import AppSharedData, WorkerStorageBootstrapMessage

    shared = AppSharedData.Get()
    worker_ids = [int(row["pid"]) for row in shared.get_workers_snapshot() if row.get("pid")]
    if not worker_ids:
        worker_ids = [os.getpid()]

    async def _broadcast_one(pid: int) -> dict[str, object]:
        if pid == os.getpid():
            try:
                return await apply_runtime_storage_bootstrap(
                    storage_kind,
                    client_name,
                    collection,
                    model_module=model_module,
                    model_name=model_name,
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "pid": pid,
                    "storage_kind": storage_kind,
                    "client_name": client_name,
                    "collection": collection,
                    "error": str(exc),
                }

        msg = WorkerStorageBootstrapMessage(
            sender=os.getpid(),
            storage_kind=storage_kind,
            client_name=client_name,
            collection=collection,
            model_module=model_module,
            model_name=model_name,
        )
        try:
            result = await send_message_to_worker(pid, msg)
            row = dict(result) if isinstance(result, Mapping) else {
                "ok": True,
                "pid": pid,
                "storage_kind": storage_kind,
                "client_name": client_name,
                "collection": collection,
            }
            row.setdefault("ok", True)
            row.setdefault("pid", pid)
            row.setdefault("storage_kind", storage_kind)
            row.setdefault("client_name", client_name)
            row.setdefault("collection", collection)
            return {str(key): value for key, value in row.items()}
        except Exception as exc:
            _logger.warning(
                "Storage runtime bootstrap broadcast failed for worker=%s %s.%s.%s: %s",
                pid,
                storage_kind,
                client_name,
                collection,
                exc,
            )
            return {
                "ok": False,
                "pid": pid,
                "storage_kind": storage_kind,
                "client_name": client_name,
                "collection": collection,
                "error": str(exc),
            }

    return await asyncio.gather(*(_broadcast_one(pid) for pid in worker_ids))


async def broadcast_runtime_storage_forget(
    storage_kind: str,
    client_name: str,
    collection: str,
) -> list[dict[str, object]]:
    from .app import send_message_to_worker
    from .shared import AppSharedData, WorkerStorageForgetMessage

    shared = AppSharedData.Get()
    worker_ids = [int(row["pid"]) for row in shared.get_workers_snapshot() if row.get("pid")]
    if not worker_ids:
        worker_ids = [os.getpid()]

    async def _broadcast_one(pid: int) -> dict[str, object]:
        if pid == os.getpid():
            try:
                return await apply_runtime_storage_forget(storage_kind, client_name, collection)
            except Exception as exc:
                return {
                    "ok": False,
                    "pid": pid,
                    "storage_kind": storage_kind,
                    "client_name": client_name,
                    "collection": collection,
                    "error": str(exc),
                }

        msg = WorkerStorageForgetMessage(
            sender=os.getpid(),
            storage_kind=storage_kind,
            client_name=client_name,
            collection=collection,
        )
        try:
            result = await send_message_to_worker(pid, msg)
            row = dict(result) if isinstance(result, Mapping) else {
                "ok": True,
                "pid": pid,
                "storage_kind": storage_kind,
                "client_name": client_name,
                "collection": collection,
            }
            row.setdefault("ok", True)
            row.setdefault("pid", pid)
            row.setdefault("storage_kind", storage_kind)
            row.setdefault("client_name", client_name)
            row.setdefault("collection", collection)
            return {str(key): value for key, value in row.items()}
        except Exception as exc:
            _logger.warning(
                "Storage runtime forget broadcast failed for worker=%s %s.%s.%s: %s",
                pid,
                storage_kind,
                client_name,
                collection,
                exc,
            )
            return {
                "ok": False,
                "pid": pid,
                "storage_kind": storage_kind,
                "client_name": client_name,
                "collection": collection,
                "error": str(exc),
            }

    return await asyncio.gather(*(_broadcast_one(pid) for pid in worker_ids))


def _iter_startup_configs(storage_config: StorageConfig):
    seen: set[int] = set()
    for category, section in storage_config.iter_sections():
        for name, cfg in section.iter_unique_configs():
            cfg_id = id(cfg)
            if cfg_id not in seen:
                seen.add(cfg_id)
                yield category, name, cfg


def _warmup_single_config(
    *,
    category: str,
    name: str,
    cfg: StorageConfigBase[StorageClientBase],
) -> str:
    label = f"{category}.{name}"
    client = cfg.client()
    start = getattr(client, "start", None)
    if callable(start):
        start()
    return label


async def warmup_storage_clients(
    storage_config: StorageConfig | None = None,
    *,
    logger: logging.Logger | None = None,
    phase: str = "startup",
) -> list[str]:
    """Warm storage clients for process-local use.

    This helper only initializes client instances for the current process.
    Schema / index creation and migration belong to the main-process preflight.
    """
    active_logger = logger or _logger
    resolved_storage_config = storage_config or StorageConfig.Global()
    entries = list(_iter_startup_configs(resolved_storage_config))
    if not entries:
        return []
    labels = await asyncio.gather(
        *(
            asyncio.to_thread(
                _warmup_single_config,
                category=category,
                name=name,
                cfg=cfg,
            )
            for category, name, cfg in entries
        )
    )
    active_logger.info(
        "Storage %s warmup finished for %s client(s).",
        phase,
        len(labels),
    )
    return labels


def _merge_preflight_maps(*maps: _CollectionPreflightMap) -> _CollectionPreflightMap:
    merged: _CollectionPreflightMap = {}
    for payload in maps:
        for key, collections in payload.items():
            bucket = merged.setdefault(key, [])
            for collection_name in collections:
                if collection_name not in bucket:
                    bucket.append(collection_name)
    return merged


def _row_to_dict(row: object) -> _CollectionMetaRow:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    mapping = getattr(row, "_mapping", None)
    if isinstance(mapping, Mapping):
        return {str(key): value for key, value in mapping.items()}
    try:
        converted = dict(row)
        return {str(key): value for key, value in converted.items()}
    except Exception:
        keys = getattr(row, "keys", lambda: [])()
        return {str(key): row[key] for key in keys}


def _schema_signature(value: object) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            pass
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load_model_from_meta(meta: _CollectionMetaRow) -> type[ORMModel] | None:
    module_name = str(meta.get("model_module") or "").strip()
    class_name = str(meta.get("model_name") or "").strip()
    if not module_name or not class_name:
        return None
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None
    model_cls = getattr(module, class_name, None)
    if isinstance(model_cls, type) and issubclass(model_cls, ORMModel):
        return model_cls
    return None


def _iter_client_names(section: ORMStorageConfig | VectorStorageConfig) -> list[str]:
    names: list[str] = []
    for field_name in type(section).model_fields:
        if field_name == "extra":
            continue
        if getattr(section, field_name, None) is not None:
            names.append(field_name)
    for name in (section.extra or {}):
        names.append(name)
    return list(dict.fromkeys(names))


def _group_client_names(section: ORMStorageConfig | VectorStorageConfig) -> list[tuple[str, list[str]]]:
    grouped: dict[str, _ClientNameGroup] = {}
    for name in _iter_client_names(section):
        resolved_name, cfg = section._resolve_config_for_name(name)
        if cfg is None:
            continue
        try:
            signature = json.dumps(cfg.model_dump(mode="json", exclude_none=False), ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            signature = f"{type(cfg).__name__}:{id(cfg)}"
        group = grouped.setdefault(signature, {"primary": resolved_name, "names": []})
        for alias in dict.fromkeys((name, resolved_name)):
            if alias not in group["names"]:
                group["names"].append(alias)
    return [
        (str(item["primary"]), list(item["names"]))
        for item in grouped.values()
    ]


def _iter_loaded_orm_models() -> list[type[ORMModel]]:
    models: list[type[ORMModel]] = []
    seen: set[type[ORMModel]] = set()
    for model_cls in ORMModel._iter_model_subclasses():
        if model_cls in seen or model_cls is ORMModel:
            continue
        if issubclass(model_cls, VectorORMModel):
            continue
        seen.add(model_cls)
        models.append(model_cls)
    return models


def _iter_loaded_vector_models() -> list[type[ORMModel]]:
    models: list[type[ORMModel]] = []
    seen: set[type[ORMModel]] = set()
    for model_cls in VectorORMModel._iter_model_subclasses():
        if model_cls in seen or model_cls is VectorORMModel:
            continue
        if not any(bool(getattr(field_info, "is_vector", False)) for field_info in model_cls.model_fields.values()):
            continue
        seen.add(cast(type[ORMModel], model_cls))
        models.append(cast(type[ORMModel], model_cls))
    return models


async def _run_loaded_model_preflight(
    section: ORMStorageConfig | VectorStorageConfig,
    *,
    logger: logging.Logger,
    model_classes: list[type[ORMModel]],
) -> _CollectionPreflightMap:
    if not model_classes:
        return {}

    client_groups: list[_ClientGroup] = []
    alias_to_group: dict[str, _ClientGroup] = {}
    for primary_name, mapped_names in _group_client_names(cast(ORMStorageConfig | VectorStorageConfig, section)):
        client = section.get_client(primary_name)
        group = (primary_name, mapped_names, client)
        client_groups.append(group)
        for alias in mapped_names:
            alias_to_group[alias] = group

    result: _CollectionPreflightMap = {}
    ensured: set[tuple[int, str]] = set()
    for model_cls in model_classes:
        collection_name = str(getattr(model_cls, "CollectionName", "") or "").strip()
        if not collection_name:
            continue

        matched_group: _ClientGroup | None = None
        explicit_client = getattr(model_cls, "Client", None)
        if explicit_client is not None:
            for group in client_groups:
                if group[2] is explicit_client:
                    matched_group = group
                    break
        if matched_group is None:
            resolved_name, cfg = section._resolve_config_for_name(collection_name)
            if cfg is None:
                continue
            matched_group = alias_to_group.get(resolved_name)
            if matched_group is None:
                client = section.get_client(resolved_name)
                matched_group = (resolved_name, [resolved_name], client)
                alias_to_group[resolved_name] = matched_group

        primary_name, mapped_names, client = matched_group
        ensure_key = (id(client), collection_name)
        if ensure_key not in ensured:
            try:
                await client.check_schema(model_cls)
            except Exception as exc:
                logger.warning(
                    "Main-process model bootstrap failed for client `%s` collection `%s`: %s",
                    primary_name,
                    collection_name,
                    exc,
                )
                continue
            ensured.add(ensure_key)

        for alias in mapped_names:
            bucket = result.setdefault(alias, [])
            if collection_name not in bucket:
                bucket.append(collection_name)
    return result


async def _list_orm_collection_meta(client: ORM_ClientBase) -> _CollectionMetaRows:
    getter = getattr(client, "list_collection_meta", None)
    if callable(getter):
        try:
            rows = await _maybe_await(getter())
            return [_row_to_dict(row) for row in rows]
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
            return [_row_to_dict(row) for row in rows]
        except Exception:
            return []

    if isinstance(client, SQL_ORM_Client):
        try:
            await client._ensure_schema_ready()
            async with client._engine.begin() as conn:
                result = await conn.execute(
                    client._sql_text(
                        "SELECT collection_name, model_module, model_name, schema_json FROM _orm_collections ORDER BY collection_name"
                    )
                )
                rows = result.fetchall()
            return [_row_to_dict(row) for row in rows]
        except Exception:
            return []

    if isinstance(client, MongoORMClient):
        try:
            if not client._started:
                client.start()
            cursor = client._database["_orm_collections"].find({}, {"_id": 0}).sort("collection_name", 1)
            return [dict(row) async for row in cursor]
        except Exception:
            return []

    if isinstance(client, RedisORMClient):
        try:
            import redis as _sync_redis

            sync_client = _sync_redis.Redis.from_url(client._url, db=client._db, decode_responses=True)
            try:
                collection_names = sorted(sync_client.smembers(client._collections_key()) or [])
                result_rows: _CollectionMetaRows = []
                for coll in collection_names:
                    meta_raw = sync_client.json().get(client._collection_meta_key(coll))
                    if isinstance(meta_raw, dict):
                        result_rows.append(_row_to_dict(meta_raw))
                    else:
                        result_rows.append({"collection_name": coll})
                return result_rows
            finally:
                sync_client.close()
        except Exception:
            return []

    return []


async def _list_vector_collection_meta(client: VectorClientBase) -> _CollectionMetaRows:
    getter = getattr(client, "list_collection_meta", None)
    if callable(getter):
        try:
            rows = await _maybe_await(getter())
            return [_row_to_dict(row) for row in rows]
        except Exception:
            pass

    sync_meta_collection = getattr(client, "_sync_meta_collection", None)
    namespace = str(getattr(client, "_namespace", "") or "").strip()
    if callable(sync_meta_collection) and namespace:
        try:
            if not getattr(client, "_started", False):
                client.start()
            meta_collection = sync_meta_collection()
            rows = meta_collection.find({"namespace": namespace}, {"_id": 0})
            return [_row_to_dict(row) for row in rows]
        except Exception:
            return []

    collection_names_getter = getattr(client, "_collection_names", None)
    load_collection_meta = getattr(client, "_load_collection_meta", None)
    if callable(collection_names_getter) and callable(load_collection_meta):
        try:
            if not getattr(client, "_started", False):
                client.start()
            rows: _CollectionMetaRows = []
            collection_names = await _maybe_await(collection_names_getter())
            for collection_name in collection_names or []:
                meta = await _maybe_await(load_collection_meta(str(collection_name)))
                if isinstance(meta, Mapping):
                    rows.append({str(key): value for key, value in meta.items()})
            return rows
        except Exception:
            return []

    return []


async def _preflight_one_client(
    section: ORMStorageConfig | VectorStorageConfig,
    *,
    primary_name: str,
    mapped_names: list[str],
    logger: logging.Logger,
    list_collection_meta: Callable[[_CollectionMetaClient], Awaitable[_CollectionMetaRows]],
) -> dict[str, list[str]]:
    client = section.get_client(primary_name)
    meta_rows = await list_collection_meta(client)
    ready_collections: list[str] = []

    for meta in meta_rows:
        collection_name = str(meta.get("collection_name") or "").strip()
        if not collection_name:
            continue
        model_cls = _load_model_from_meta(meta)
        if model_cls is None:
            continue

        stored_signature = _schema_signature(meta.get("schema_json"))
        live_signature = _schema_signature(_safe_model_schema(model_cls))
        try:
            await client.check_schema(model_cls)
        except Exception as exc:
            logger.warning(
                "ORM preflight failed for client `%s` collection `%s`: %s",
                primary_name,
                collection_name,
                exc,
            )
            continue

        if stored_signature != live_signature:
            logger.info(
                "ORM schema preflight refreshed client `%s` collection `%s`.",
                primary_name,
                collection_name,
            )
        if collection_name not in ready_collections:
            ready_collections.append(collection_name)

    return {
        name: list(ready_collections)
        for name in mapped_names
        if ready_collections
    }


async def _run_section_preflight(
    section: ORMStorageConfig | VectorStorageConfig,
    *,
    logger: logging.Logger,
    list_collection_meta: Callable[[_CollectionMetaClient], Awaitable[_CollectionMetaRows]],
) -> _CollectionPreflightMap:
    groups = _group_client_names(section)
    if not groups:
        return {}

    results = await asyncio.gather(
        *[
            _preflight_one_client(
                section,
                primary_name=primary_name,
                mapped_names=mapped_names,
                logger=logger,
                list_collection_meta=list_collection_meta,
            )
            for primary_name, mapped_names in groups
        ]
    )

    preflight_map: _CollectionPreflightMap = {}
    for payload in results:
        for name, collections in payload.items():
            bucket = preflight_map.setdefault(name, [])
            for collection_name in collections:
                if collection_name not in bucket:
                    bucket.append(collection_name)
    return preflight_map


def _publish_preflight_env(env_name: str, payload: _CollectionPreflightMap) -> None:
    if payload:
        os.environ[env_name] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        os.environ.pop(env_name, None)


async def run_main_process_orm_preflight(
    storage_config: StorageConfig,
    logger: logging.Logger | None = None,
) -> _StoragePreflightPayload:
    preflight_logger = logger or logging.getLogger("proj-template.orm-preflight")
    orm_discovered_map = await _run_loaded_model_preflight(
        storage_config.orm,
        logger=preflight_logger,
        model_classes=_iter_loaded_orm_models(),
    )
    orm_meta_map = await _run_section_preflight(
        storage_config.orm,
        logger=preflight_logger,
        list_collection_meta=_list_orm_collection_meta,
    )
    vector_discovered_map = await _run_loaded_model_preflight(
        storage_config.vector,
        logger=preflight_logger,
        model_classes=_iter_loaded_vector_models(),
    )
    vector_meta_map = await _run_section_preflight(
        storage_config.vector,
        logger=preflight_logger,
        list_collection_meta=_list_vector_collection_meta,
    )

    orm_preflight_map = _merge_preflight_maps(orm_discovered_map, orm_meta_map)
    vector_preflight_map = _merge_preflight_maps(vector_discovered_map, vector_meta_map)

    _publish_preflight_env(_ORM_PREFLIGHT_ENV, orm_preflight_map)
    _publish_preflight_env(_VECTOR_PREFLIGHT_ENV, vector_preflight_map)

    payload: _StoragePreflightPayload = {}
    if orm_preflight_map:
        payload["orm"] = orm_preflight_map
    if vector_preflight_map:
        payload["vector"] = vector_preflight_map
    return payload


__all__ = [
    "apply_runtime_storage_bootstrap",
    "broadcast_runtime_storage_bootstrap",
    "run_main_process_orm_preflight",
    "warmup_storage_clients",
]