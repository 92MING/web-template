
import threading

from typing import AsyncGenerator, Literal, Mapping, Self, Sequence, TYPE_CHECKING, overload
from typing_extensions import Unpack

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorClient as _MotorClient
    from motor.motor_asyncio import AsyncIOMotorCollection as _MotorCollection
    from motor.motor_asyncio import AsyncIOMotorDatabase as _MotorDB

from .field_metadata import (
    remap_payload_to_db,
    remap_payload_from_db,
    _translate_field_path,
)
import asyncio
from ..base import (
    _estimate_json_size,
    _json_loads,
    _normalize_expire_at,
    _now_ts,
    _ttl_from_expire_at,
    ObjectId,
    _validate_collection_name,
)
from .model import ORMModel, ModelT, CollectionLike, QueryLike
from .client_base import (
    HydratedORMDocument,
    ORMPayload,
    ORMPayloadLike,
    ORM_ClientBase,
    MongoORMClientInitParams,
    _get_schema_lock,
    _normalize_raw_orm_payload,
    _raw_schema_from_specs,
    _restore_mongo_doc,
    _query_to_mongo_filter,
    _safe_model_schema,
    _normalize_selected_fields,
    _project_selected_payload,
    _build_mongo_selected_projection,
    _to_mongo_object_id,
    _validate_selected_field_name,
    _orm_logger,
)

class MongoORMClient(ORM_ClientBase, type="mongo"):
    def __init__(self, **kwargs: Unpack[MongoORMClientInitParams]) -> None:
        self._mongo_url = kwargs.get("mongo_url", "mongodb://127.0.0.1:27017")
        self._database_name = kwargs.get("database", "app_backend")
        self._database: "_MotorDB | None" = None
        self._mongo_client: "_MotorClient | None" = None
        self._mongo_client_loop: asyncio.AbstractEventLoop | None = None
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        super().__init__(**kwargs)

    def start(self) -> Self:
        if self._started:
            self._ensure_async_client()
            return self
        self._mark_started()
        self._ensure_async_client()
        return self

    def close(self) -> None:
        cleanup_task = self._cleanup_task
        self._cleanup_task = None
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
        mongo_client = self._mongo_client
        self._mongo_client = None
        self._mongo_client_loop = None
        self._database = None
        self._cleanup_async_locks.clear()
        self._mark_stopped()
        if mongo_client is None:
            return
        try:
            close_func = getattr(mongo_client, "close", None)
            if callable(close_func):
                close_func()
        except Exception as e:
            _orm_logger.warning("MongoORMClient.close() failed for %s: %s", self._mongo_url, e)

    def _ensure_async_client(self) -> None:
        if not self._started:
            return
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is None:
            return
        if (
            self._mongo_client is not None
            and self._database is not None
            and self._mongo_client_loop is current_loop
        ):
            return
        stale_client = self._mongo_client
        self._mongo_client = None
        self._database = None
        self._mongo_client_loop = None
        if stale_client is not None:
            try:
                close_func = getattr(stale_client, "close", None)
                if callable(close_func):
                    close_func()
            except Exception as exc:
                _orm_logger.warning("MongoORMClient.close() failed for %s: %s", self._mongo_url, exc)
        from motor.motor_asyncio import AsyncIOMotorClient  # lazy import

        self._mongo_client = AsyncIOMotorClient(self._mongo_url)
        self._database = self._mongo_client[self._database_name]
        self._mongo_client_loop = current_loop

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = (threading.get_ident(), id(asyncio.get_running_loop()))
        lock = self._cleanup_async_locks.get(owner)
        if lock is None:
            lock = asyncio.Lock()
            self._cleanup_async_locks[owner] = lock
        return lock

    def _schedule_cleanup(self) -> None:
        if not self._should_cleanup():
            return
        task = self._cleanup_task
        if task is not None and not task.done():
            return
        self._cleanup_task = asyncio.create_task(self._background_cleanup())

    async def _background_cleanup(self) -> None:
        try:
            await self.cleanup()
        except Exception:
            pass

    def _collection(self, name: str) -> '_MotorCollection':
        if not self._started:
            self.start()
        self._ensure_async_client()
        database = self._database
        assert database is not None
        return database[f"orm_{name}"]

    def _meta_collection(self) -> '_MotorCollection':
        if not self._started:
            self.start()
        self._ensure_async_client()
        database = self._database
        assert database is not None
        return database["_orm_collections"]

    def _collection_exists(self, collection: str) -> bool:
        if collection in self._known_collections:
            return True
        try:
            from pymongo import MongoClient as SyncMongoClient

            sync_client = SyncMongoClient(self._mongo_url, serverSelectionTimeoutMS=3000)
            try:
                exists = f"orm_{collection}" in set(
                    sync_client[self._database_name].list_collection_names()
                )
            finally:
                sync_client.close()
        except Exception:
            return False
        if exists:
            self._mark_collection_known(collection)
        return exists

    async def _async_collection_exists(self, collection: str) -> bool:
        if collection in self._known_collections:
            return True
        if not self._started:
            self.start()
        row = await self._meta_collection().find_one({"collection_name": collection}, {"_id": 1})
        if row is not None:
            self._mark_collection_known(collection)
            return True
        try:
            self._ensure_async_client()
            database = self._database
            if database is None:
                return False
            exists = f"orm_{collection}" in set(await database.list_collection_names())
        except Exception:
            return False
        if exists:
            self._mark_collection_known(collection)
        return exists

    async def _load_stored_schema(self, collection: str) -> dict[str, object] | None:
        try:
            if not self._started:
                self.start()
            row = await self._meta_collection().find_one(
                {"collection_name": collection}, {"schema_json": 1, "_id": 0}
            )
        except Exception:
            return None
        if row is None:
            return None
        raw = row.get("schema_json")
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        try:
            return _json_loads(raw)
        except Exception:
            return None

    async def list_collection_meta(self) -> list[dict[str, object]]:
        if not self._started:
            self.start()
        cursor = self._meta_collection().find({}, {"_id": 0}).sort("collection_name", 1)
        return [dict(row) async for row in cursor if isinstance(row, Mapping)]

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        if not self._started:
            self.start()
        self.register_model(model_cls)
        collection = model_cls.CollectionName
        new_schema = _safe_model_schema(model_cls)
        with _get_schema_lock(collection):
            meta: dict[str, object] = {
                "collection_name": collection,
                "model_module": model_cls.__module__,
                "model_name": model_cls.__name__,
                "schema_json": new_schema,
            }
            await self._meta_collection().update_one(
                {"collection_name": collection}, {"$set": meta}, upsert=True
            )
            # System metadata indexes on _sys subdocument
            await self._collection(collection).create_index("_sys.expire_at")
            await self._collection(collection).create_index("_sys.accessed_at")

            # Field-level indexes — three-state logic
            specs = self._get_native_field_specs(collection)
            existing_indexes = set()
            try:
                async for idx_info in self._collection(collection).list_indexes():
                    # Extract field names from single-field indexes
                    idx_keys = list(idx_info.get("key", {}).keys())
                    if len(idx_keys) == 1:
                        existing_indexes.add(idx_keys[0])
            except Exception:
                pass

            for spec in (specs or {}).values():
                if spec.kind in ("json", "blob_single", "blob_union", "file_id", "foreign_list"):
                    if spec.index is True:
                        _orm_logger.warning(
                            "Mongo: index=True on non-indexable kind %r for field %r — ignored",
                            spec.kind, spec.field_name,
                        )
                    continue
                db_name = spec.column_name
                if spec.index is True:
                    await self._collection(collection).create_index(db_name)
                elif spec.index is False and db_name in existing_indexes:
                    try:
                        await self._collection(collection).drop_index(f"{db_name}_1")
                    except Exception:
                        pass  # index name may differ
                # index is None → do nothing (align with DB)

        self._mark_collection_known(collection)
        self._bootstrapped_collections.add(collection)

    async def raw_create_collection(self, collection: str, schema: Mapping[str, object] | None = None) -> None:
        if not self._started:
            self.start()
        collection_name = _validate_collection_name(collection)
        specs = await self._ensure_raw_specs(collection_name, schema=schema)
        schema_json = _raw_schema_from_specs(collection_name, specs) if specs else (dict(schema) if schema is not None else None)
        model_cls = self._resolve_collection_model(collection_name)
        with _get_schema_lock(collection_name):
            existing = await self._meta_collection().find_one({"collection_name": collection_name}, {"_id": 0}) or {}
            meta: dict[str, object] = {
                "collection_name": collection_name,
                "model_module": existing.get("model_module"),
                "model_name": existing.get("model_name"),
                "schema_json": schema_json,
            }
            if model_cls is not None:
                meta.update(
                    {
                        "model_module": model_cls.__module__,
                        "model_name": model_cls.__name__,
                    }
                )
            await self._meta_collection().update_one(
                {"collection_name": collection_name}, {"$set": meta}, upsert=True
            )
            await self._collection(collection_name).create_index("_sys.expire_at")
            await self._collection(collection_name).create_index("_sys.accessed_at")
        self._mark_collection_known(collection_name)
        self._bootstrapped_collections.add(collection_name)

    async def raw_set(
        self,
        collection: str,
        payload: ORMPayloadLike,
        *,
        expire: float | int | None = None,
        create_collection: bool = True,
    ) -> str:
        if not self._started:
            self.start()
        collection_name = _validate_collection_name(collection)
        normalized_payload = _normalize_raw_orm_payload(payload)
        specs = await self._ensure_raw_specs(collection_name, payload=normalized_payload)
        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        if create_collection:
            await self.raw_create_collection(collection_name, _raw_schema_from_specs(collection_name, specs) if specs else None)

        object_id = str(normalized_payload.get("id") or normalized_payload.get("_id"))
        mongo_object_id = _to_mongo_object_id(object_id)
        ts = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        db_payload = remap_payload_to_db(normalized_payload, self._get_field_name_map(collection_name))
        db_payload.pop("id", None)
        db_payload.pop("_id", None)
        doc: dict[str, object] = {"_id": mongo_object_id}
        doc.update(db_payload)
        doc["_sys"] = {
            "expire_at": expire_at,
            "size": _estimate_json_size(db_payload),
            "accessed_at": ts,
        }
        await self._collection(collection_name).replace_one({"_id": mongo_object_id}, doc, upsert=True)
        self._schedule_cleanup()
        return object_id

    async def drop_collection(self, collection: CollectionLike[ORMModel]) -> None:
        collection, model_cls = self._normalize_collection(collection)
        await self._collection(collection).drop()
        await self._meta_collection().delete_one({"collection_name": collection})
        self._collection_models.pop(collection, None)
        self._forget_collection(collection)
        if model_cls is not None:
            self.register_model(model_cls)

    @overload
    def dump_collection(self, collection: type[ModelT], *, as_model: Literal[True] = True) -> AsyncGenerator[ModelT, None]: ...

    @overload
    def dump_collection(self, collection: type[ModelT], *, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    @overload
    def dump_collection(self, collection: str, *, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def dump_collection(self, collection: str, *, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    async def dump_collection(self, collection: CollectionLike[ORMModel], *, as_model: bool = True) -> AsyncGenerator[HydratedORMDocument, None]:
        async for item in self.search(collection, None, as_model=as_model):
            yield item

    @overload
    def search(self, collection: type[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ModelT, None]: ...

    @overload
    def search(self, collection: type[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    @overload
    def search(self, collection: str, query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: str, query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    async def search(self, collection: CollectionLike[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: bool = True) -> AsyncGenerator[HydratedORMDocument, None]:
        collection, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection):
            return
        now = _now_ts()
        mongo_filter = _query_to_mongo_filter(query, field_name_map=self._get_field_name_map(collection))
        if query is not None and mongo_filter is None:
            raise ValueError("Mongo search requires a query that can be pushed down to Mongo.")
        validity: dict[str, object] = {"$or": [{"_sys.expire_at": None}, {"_sys.expire_at": {"$gt": now}}]}
        if mongo_filter:
            combined: dict[str, object] = {"$and": [validity, mongo_filter]}
        else:
            combined = validity
        cursor = self._collection(collection).find(combined).sort("_id", -1)
        if offset > 0:
            cursor = cursor.skip(int(offset))
        if limit is not None:
            cursor = cursor.limit(int(limit))
        try:
            async for doc in cursor:
                payload = _restore_mongo_doc(doc)
                yield await self._hydrate_with_foreign(collection, payload, as_model=as_model)
        finally:
            await cursor.close()

    async def selected_search(
        self,
        collection: CollectionLike[ModelT],
        *,
        fields: Sequence[str],
        query: "QueryLike" = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[ORMPayload, None]:
        collection, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection):
            return
        normalized_fields = _normalize_selected_fields(fields)
        now = _now_ts()
        fnmap = self._get_field_name_map(collection)
        mongo_filter = _query_to_mongo_filter(query, field_name_map=fnmap)
        if query is not None and mongo_filter is None:
            raise ValueError("Mongo selected_search requires a query that can be pushed down to Mongo.")
        validity: dict[str, object] = {"$or": [{"_sys.expire_at": None}, {"_sys.expire_at": {"$gt": now}}]}
        combined: dict[str, object] = {"$and": [validity, mongo_filter]} if mongo_filter else validity
        cursor = self._collection(collection).find(combined, _build_mongo_selected_projection(normalized_fields, field_name_map=fnmap)).sort("_id", -1)
        if offset > 0:
            cursor = cursor.skip(int(offset))
        if limit is not None:
            cursor = cursor.limit(int(limit))
        async for doc in cursor:
            payload = _restore_mongo_doc(doc)
            if fnmap:
                payload = remap_payload_from_db(payload, fnmap)
            yield _project_selected_payload(payload, normalized_fields)

    @overload
    async def search_one(self, collection: type[ModelT], query: "QueryLike" = None, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def search_one(self, collection: type[ModelT], query: "QueryLike" = None, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def search_one(self, collection: str, query: "QueryLike" = None, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def search_one(self, collection: str, query: "QueryLike" = None, *, as_model: Literal[False]) -> ORMPayload | None: ...

    async def search_one(self, collection: CollectionLike[ModelT], query: "QueryLike" = None, *, as_model: bool = True) -> HydratedORMDocument | None:
        return await self._first_or_none(
            self.search(collection, query, limit=1, as_model=as_model)
        )

    @overload
    async def search_by_id(self, collection: type[ModelT], id: str | ObjectId, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def search_by_id(self, collection: type[ModelT], id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def search_by_id(self, collection: str, id: str | ObjectId, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def search_by_id(self, collection: str, id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    async def search_by_id(self, collection: CollectionLike[ModelT], id: str | ObjectId, *, as_model: bool = True) -> HydratedORMDocument | None:
        return await self.get(collection, id, as_model=as_model)

    async def set(self, value: ORMModel | ORMPayloadLike, *, collection: CollectionLike[ORMModel] | None = None, expire: float | int | None = None, create_collection: bool = True) -> str:
        if not self._started:
            self.start()
        collection_name, payload, model_cls = self._normalize_value(value, collection=collection)
        if model_cls is None:
            raise ValueError(
                f"Collection `{collection_name}` does not map to a loaded ORMModel class; "
                "raw dict writes require a defined ORM model."
            )
        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        if create_collection:
            await self.ensure_collection(model_cls)
        object_id = str(payload.get("id") or payload.get("_id"))
        mongo_object_id = _to_mongo_object_id(object_id)

        # ── file_id ref counting on overwrite ──
        specs = self._get_native_field_specs(collection_name)
        file_id_specs = [s for s in (specs or {}).values() if s.kind == "file_id"]
        if file_id_specs:
            try:
                old = await self.get(collection_name, object_id)
                old_payload = old if isinstance(old, dict) else (old._serialize_for_storage() if old else None)
            except Exception:
                old_payload = None
            await self._handle_file_id_ref_on_overwrite(collection_name, old_payload, payload)

        ts = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        db_payload = remap_payload_to_db(payload, self._get_field_name_map(collection_name))
        db_payload.pop("id", None)
        db_payload.pop("_id", None)
        doc: dict[str, object] = {"_id": mongo_object_id}
        doc.update(db_payload)
        doc["_sys"] = {
            "expire_at": expire_at,
            "size": _estimate_json_size(db_payload),
            "accessed_at": ts,
        }
        await self._collection(collection_name).replace_one({"_id": mongo_object_id}, doc, upsert=True)
        self._schedule_cleanup()
        return object_id

    async def set_many(
        self,
        values: Sequence[ORMModel | ORMPayloadLike],
        *,
        collection: CollectionLike[ORMModel] | None = None,
        expire: float | int | None = None,
        create_collection: bool = True,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []
        if not self._started:
            self.start()

        collection_name, payloads, model_cls = self._normalize_batch_values(batch, collection=collection)
        if model_cls is None:
            return await ORM_ClientBase.set_many(
                self,
                batch,
                collection=collection,
                expire=expire,
                create_collection=create_collection,
            )

        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        if create_collection:
            await self.ensure_collection(model_cls)

        from pymongo import ReplaceOne

        ts = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        field_name_map = self._get_field_name_map(collection_name)
        operations: list[object] = []
        object_ids: list[str] = []
        for payload in payloads:
            object_id = str(payload.get("id") or payload.get("_id"))
            object_ids.append(object_id)
            mongo_object_id = _to_mongo_object_id(object_id)
            db_payload = remap_payload_to_db(payload, field_name_map)
            db_payload.pop("id", None)
            db_payload.pop("_id", None)
            replace_doc: dict[str, object] = {"_id": mongo_object_id}
            replace_doc.update(db_payload)
            replace_doc["_sys"] = {
                "expire_at": expire_at,
                "size": _estimate_json_size(db_payload),
                "accessed_at": ts,
            }
            operations.append(ReplaceOne(
                {"_id": mongo_object_id},
                replace_doc,
                upsert=True,
            ))

        if operations:
            await self._collection(collection_name).bulk_write(operations, ordered=False)
        self._schedule_cleanup()
        return object_ids

    @overload
    async def get(self, collection: type[ModelT], object_id: str | ObjectId, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def get(self, collection: type[ModelT], object_id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def get(self, collection: str, object_id: str | ObjectId, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: str, object_id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    async def get(self, collection: CollectionLike[ModelT], object_id: str | ObjectId, *, as_model: bool = True) -> HydratedORMDocument | None:
        collection_name, _ = self._normalize_collection(collection)
        mongo_object_id = _to_mongo_object_id(object_id)
        doc = await self._collection(collection_name).find_one({"_id": mongo_object_id})
        if doc is None:
            return None
        sys_meta = doc.get("_sys") or {}
        expire_at = sys_meta.get("expire_at")
        if expire_at is not None and expire_at <= _now_ts():
            await self._collection(collection_name).delete_one({"_id": mongo_object_id})
            return None
        payload = _restore_mongo_doc(doc)
        return await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

    async def delete(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> bool:
        collection_name, _ = self._normalize_collection(collection)
        mongo_id = _to_mongo_object_id(object_id)

        # cascade cleanup: fetch file_id fields before deleting
        specs = self._get_native_field_specs(collection_name)
        has_file_id = specs and any(s.kind == "file_id" for s in specs.values())
        if has_file_id:
            doc = await self._collection(collection_name).find_one({"_id": mongo_id})
            if doc is not None:
                await self._cleanup_foreign_on_delete(collection_name, _restore_mongo_doc(doc))

        result = await self._collection(collection_name).delete_one({"_id": mongo_id})
        return result.deleted_count > 0

    async def delete_many(self, collection: CollectionLike[ORMModel], object_ids: Sequence[str | ObjectId]) -> dict[str, bool]:
        collection_name, _ = self._normalize_collection(collection)
        normalized_ids: list[tuple[str, str]] = []
        for object_id in object_ids:
            object_id_text = str(object_id or "").strip()
            if object_id_text:
                normalized_ids.append((object_id_text, _to_mongo_object_id(object_id_text)))
        if not normalized_ids:
            return {}

        coll = self._collection(collection_name)
        mongo_ids = [mongo_id for _, mongo_id in normalized_ids]
        specs = self._get_native_field_specs(collection_name)
        has_file_id = specs and any(s.kind == "file_id" for s in specs.values())

        if not has_file_id:
            delete_result = await coll.delete_many({"_id": {"$in": mongo_ids}})
            if int(delete_result.deleted_count or 0) == len(normalized_ids):
                return {object_id_text: True for object_id_text, _ in normalized_ids}
            remaining_ids = {
                str(doc.get("_id"))
                async for doc in coll.find({"_id": {"$in": mongo_ids}}, {"_id": 1})
                if doc.get("_id") is not None
            }
            return {
                object_id_text: mongo_id not in remaining_ids
                for object_id_text, mongo_id in normalized_ids
            }

        existing_docs = [
            doc async for doc in coll.find(
                {"_id": {"$in": mongo_ids}},
                None if has_file_id else {"_id": 1},
            )
        ]
        existing_ids = {str(doc.get("_id")) for doc in existing_docs if doc.get("_id") is not None}

        if has_file_id:
            for doc in existing_docs:
                await self._cleanup_foreign_on_delete(collection_name, _restore_mongo_doc(doc))

        if existing_ids:
            await coll.delete_many({"_id": {"$in": list(existing_ids)}})

        return {
            object_id_text: mongo_id in existing_ids
            for object_id_text, mongo_id in normalized_ids
        }

    async def set_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId, expire: float | int | None) -> bool:
        collection_name, _ = self._normalize_collection(collection)
        result = await self._collection(collection_name).update_one(
            {"_id": _to_mongo_object_id(object_id)},
            {"$set": {"_sys.expire_at": _normalize_expire_at(expire)}},
        )
        return result.modified_count > 0

    async def get_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> float | None:
        collection_name, _ = self._normalize_collection(collection)
        doc = await self._collection(collection_name).find_one({"_id": _to_mongo_object_id(object_id)}, {"_sys.expire_at": 1})
        if doc is None:
            return None
        sys_meta = doc.get("_sys") or {}
        ttl = _ttl_from_expire_at(sys_meta.get("expire_at"))
        if ttl == 0.0:
            await self.delete(collection_name, object_id)
        return ttl

    async def cleanup(self, *, force: bool = False) -> int:
        if not await self._should_cleanup_async(force=force):
            return 0
        if not self._started:
            self.start()
        async with self._cleanup_async_lock():
            if not await self._should_cleanup_async(force=force):
                return 0
            removed = 0
            total_size = 0
            rows_all: list[tuple[str, str, int, float]] = []
            now = _now_ts()
            async for meta in self._meta_collection().find({}, {"collection_name": 1}):
                coll_name = meta["collection_name"]
                coll = self._collection(coll_name)
                expired = await coll.delete_many({"_sys.expire_at": {"$ne": None, "$lte": now}})
                removed += expired.deleted_count
                if self._max_size is not None:
                    async for doc in coll.find({}, {"_id": 1, "_sys.size": 1, "_sys.accessed_at": 1}):
                        sys_meta = doc.get("_sys") or {}
                        sz = int(sys_meta.get("size", 0))
                        total_size += sz
                        rows_all.append((coll_name, str(doc["_id"]), sz, float(sys_meta.get("accessed_at", 0.0))))
            total_count = len(rows_all)
            if self._max_size is not None and total_count > self._max_size:
                target = max(0, int(self._max_size * 0.9))
                for coll_name, oid, sz, _ in sorted(rows_all, key=lambda item: item[3]):
                    if total_count <= target:
                        break
                    if await self.delete(coll_name, oid):
                        total_count -= 1
                        removed += 1
            await self._mark_cleanup_async()
            return removed

    @overload
    def search_sorted(
        self,
        collection: type[ModelT],
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[True] = True,
    ) -> AsyncGenerator[ModelT, None]: ...

    @overload
    def search_sorted(
        self,
        collection: type[ModelT],
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[False],
    ) -> AsyncGenerator[ORMPayload, None]: ...

    @overload
    def search_sorted(
        self,
        collection: str,
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[True] = True,
    ) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_sorted(
        self,
        collection: str,
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[False],
    ) -> AsyncGenerator[ORMPayload, None]: ...

    async def search_sorted(
        self,
        collection: CollectionLike[ModelT],
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedORMDocument, None]:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return
        now = _now_ts()
        fnmap = self._get_field_name_map(collection_name)
        mongo_filter = _query_to_mongo_filter(query, field_name_map=fnmap)
        if mongo_filter is None:
            raise ValueError("Mongo sorted search requires a query that can be pushed down to Mongo.")
        validity: dict[str, object] = {"$or": [{"_sys.expire_at": None}, {"_sys.expire_at": {"$gt": now}}]}
        combined: dict[str, object] = {"$and": [validity, mongo_filter]} if mongo_filter else validity
        sort_spec = []
        for raw_field, raw_direction in sort:
            field = _validate_selected_field_name(str(raw_field or ""))
            db_field = _translate_field_path(field, fnmap) if fnmap else field
            mongo_field = "_id" if field in {"id", "_id"} else db_field
            sort_spec.append((mongo_field, -1 if str(raw_direction or "asc").lower() == "desc" else 1))
        cursor = self._collection(collection_name).find(combined).sort(sort_spec or [("_id", -1)])
        if offset > 0:
            cursor = cursor.skip(int(offset))
        if limit is not None:
            cursor = cursor.limit(int(limit))
        try:
            async for doc in cursor:
                payload = _restore_mongo_doc(doc)
                yield await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)
        finally:
            await cursor.close()

    async def collection_count(self, collection: str) -> int:
        now = _now_ts()
        return int(await self._collection(collection).count_documents({"$or": [{"_sys.expire_at": None}, {"_sys.expire_at": {"$gt": now}}]}))

    async def query_count(self, collection: CollectionLike[ORMModel], query: "QueryLike" = None) -> int:
        collection_name, _ = self._normalize_collection(collection)
        mongo_filter = _query_to_mongo_filter(query, field_name_map=self._get_field_name_map(collection_name))
        if mongo_filter is None:
            raise ValueError("Mongo query_count only supports pushdown-compatible filters.")
        now = _now_ts()
        validity: dict[str, object] = {"$or": [{"_sys.expire_at": None}, {"_sys.expire_at": {"$gt": now}}]}
        combined: dict[str, object] = {"$and": [validity, mongo_filter]} if mongo_filter else validity
        return int(await self._collection(collection_name).count_documents(combined))



__all__ = ['MongoORMClient']
