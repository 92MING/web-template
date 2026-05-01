
import asyncio
import inspect
import threading

from typing import AsyncGenerator, Literal, Mapping, Protocol, Self, Sequence, TYPE_CHECKING, cast, overload
from typing_extensions import Unpack

if TYPE_CHECKING:
    from redis.asyncio import Redis as _AioRedis
    from .redis_support import RedisRuntimeCapabilities as _RedisCapabilities
    from .redis_search import RedisScalarKind

from .field_schema import (
    FieldKind,
    ORMFieldSpec,
    extract_field_specs,
)
from .field_metadata import (
    remap_payload_to_db,
    _translate_field_path,
)
from .redis_support import (
    async_load_redis_runtime_capabilities,
    ensure_redis_orm_supported,
)
from .redis_search import (
    RedisScalarFieldSpec,
    RedisSearchQueryError,
    build_redis_scalar_fields_flat,
    compile_redis_query,
    decode_redis_search_value,
    redis_json_path,
    redis_scalar_sort_alias,
)
from ..base import (
    _deep_get,
    _estimate_json_size,
    _json_loads,
    _normalize_expire_at,
    _now_ts,
    ObjectId,
    _validate_collection_name,
)
from .model import ORMModel, ModelT, CollectionLike, QueryLike
from .client_base import (
    HydratedORMDocument,
    ORMPayload,
    ORMPayloadLike,
    ORM_ClientBase,
    RedisORMClientInitParams,
    _get_schema_lock,
    _normalize_raw_orm_payload,
    _raw_schema_from_specs,
    _restore_payload_from_storage,
    _safe_model_schema,
    _normalize_selected_fields,
    _project_selected_pairs,
    _orm_logger,
)


class _RedisSearchDocument(Protocol):
    id: bytes | str
    json: object

    def __getattr__(self, name: str) -> object: ...


class _RedisSearchResult(Protocol):
    docs: Sequence[_RedisSearchDocument]
    total: int | None


class _RedisSearchIndex(Protocol):
    async def info(self) -> object: ...

    async def create_index(self, fields: Sequence[object], definition: object) -> object: ...

    async def alter_schema_add(self, fields: Sequence[object]) -> object: ...

    async def search(
        self,
        query: object,
        query_params: Mapping[str, object] | None = None,
    ) -> _RedisSearchResult: ...

    async def dropindex(self, delete_documents: bool = False) -> object: ...


def _async_owner_key() -> tuple[int, int]:
    return (threading.get_ident(), id(asyncio.get_running_loop()))


class RedisORMClient(ORM_ClientBase, type="redis"):
    def __init__(self, **kwargs: Unpack[RedisORMClientInitParams]) -> None:
        self._url = kwargs.get("url", "redis://127.0.0.1:6379/0")
        self._prefix = kwargs.get("prefix", "orm")
        self._db = int(kwargs.get("db", 0))
        self._decode_responses = bool(kwargs.get("decode_responses", True))
        self._redis: "_AioRedis | None" = None
        self._redis_by_owner: dict[tuple[int, int], _AioRedis] = {}
        self._ready_owners: set[tuple[int, int]] = set()
        self._redis_lock = threading.RLock()
        self._capabilities: "_RedisCapabilities | None" = None
        self._search_fields: dict[str, dict[str, RedisScalarFieldSpec]] = {}
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        super().__init__(**kwargs)

    def start(self) -> Self:
        if self._started:
            return self
        self._mark_started()
        return self

    async def _ensure_ready(self) -> None:
        if not self._started:
            self.start()
        owner = _async_owner_key()
        with self._redis_lock:
            client = self._redis_by_owner.get(owner)
            if client is None:
                import redis.asyncio as aioredis  # type: ignore

                client = aioredis.Redis.from_url(
                    self._url,
                    db=self._db,
                    decode_responses=self._decode_responses,
                )
                self._redis_by_owner[owner] = client
            self._redis = client
            ready = owner in self._ready_owners
        if ready:
            return
        await client.ping()
        capabilities = await async_load_redis_runtime_capabilities(client)
        ensure_redis_orm_supported(capabilities)
        self._capabilities = capabilities
        await self._restore_collection_state()
        with self._redis_lock:
            self._ready_owners.add(owner)

    def close(self) -> None:
        cleanup_task = self._cleanup_task
        self._cleanup_task = None
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
        with self._redis_lock:
            redis_clients = list(self._redis_by_owner.values())
            self._redis_by_owner.clear()
            self._ready_owners.clear()
            self._cleanup_async_locks.clear()
        self._redis = None
        self._capabilities = None
        self._mark_stopped()
        if not redis_clients:
            return
        for redis_client in redis_clients:
            try:
                close_func = getattr(redis_client, "aclose", None) or getattr(redis_client, "close", None)
                if callable(close_func):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        from ...utils.concurrent_utils import run_async_in_sync

                        run_async_in_sync(close_func)
                    else:
                        close_result = close_func()
                        if inspect.isawaitable(close_result):
                            loop.create_task(close_result)
            except Exception as exc:
                _orm_logger.warning("RedisORMClient.close() failed for %s: %s", self._url, exc)

    def _client(self) -> "_AioRedis":
        if not self._started:
            self.start()
        owner = _async_owner_key()
        with self._redis_lock:
            client = self._redis_by_owner.get(owner)
            if client is None:
                import redis.asyncio as aioredis  # type: ignore

                client = aioredis.Redis.from_url(
                    self._url,
                    db=self._db,
                    decode_responses=self._decode_responses,
                )
                self._redis_by_owner[owner] = client
            self._redis = client
            return client

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = _async_owner_key()
        with self._redis_lock:
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

    def _root_prefix(self) -> str:
        return f"{self._prefix}:{self._namespace}"

    def _collections_key(self) -> str:
        return f"{self._root_prefix()}:collections"

    def _collection_meta_key(self, collection: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:meta"

    def _collection_ids_key(self, collection: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:ids"

    def _search_index_name(self, collection: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:idx"

    def _search_doc_prefix(self, collection: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:doc:"

    def _doc_key(self, collection: str, object_id: str | ObjectId) -> str:
        return f"{self._search_doc_prefix(collection)}{object_id}"

    def _search(self, collection: str) -> _RedisSearchIndex:
        return cast(_RedisSearchIndex, self._client().ft(self._search_index_name(collection)))

    @staticmethod
    def _decode_text(value: bytes | str) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    def _collection_names(self) -> list[str]:
        raise RuntimeError("Use async _async_collection_names() instead")

    async def _async_collection_names(self) -> list[str]:
        values = await self._client().smembers(self._collections_key()) or []
        return sorted(self._decode_text(item) for item in values)

    @staticmethod
    def _serialize_search_fields(specs: Mapping[str, RedisScalarFieldSpec]) -> dict[str, dict[str, object]]:
        return {
            field_path: {"kind": spec.kind}
            for field_path, spec in specs.items()
        }

    @staticmethod
    def _deserialize_search_fields(payload: Mapping[str, object] | None) -> dict[str, RedisScalarFieldSpec]:
        result: dict[str, RedisScalarFieldSpec] = {}
        if not isinstance(payload, Mapping):
            return result
        for raw_field, raw_spec in payload.items():
            if not isinstance(raw_spec, Mapping):
                continue
            kind = str(raw_spec.get("kind") or "").strip().lower()
            if kind not in {"string", "numeric", "bool", "tag"}:
                continue
            field_path = str(raw_field or "").strip()
            if not field_path:
                continue
            result[field_path] = RedisScalarFieldSpec(field_path=field_path, kind=cast("RedisScalarKind", kind))
        return result

    @staticmethod
    def _field_kind_to_redis_scalar(field_path: str, kind: "FieldKind") -> RedisScalarFieldSpec | None:
        """Map ORMFieldSpec.kind to RedisScalarFieldSpec."""
        if kind == "bool":
            return RedisScalarFieldSpec(field_path=field_path, kind="bool")
        if kind in {"int", "float"}:
            return RedisScalarFieldSpec(field_path=field_path, kind="numeric")
        if kind in {"str", "date", "datetime", "file_id", "foreign_single"}:
            return RedisScalarFieldSpec(field_path=field_path, kind="string")
        if kind == "foreign_list":
            return RedisScalarFieldSpec(field_path=field_path, kind="tag")
        # json, blob_single, blob_union → not indexed
        return None

    def _model_search_fields(self, model_cls: type[ORMModel]) -> dict[str, RedisScalarFieldSpec]:
        specs: dict[str, RedisScalarFieldSpec] = {"id": RedisScalarFieldSpec(field_path="id", kind="string")}
        native_specs = extract_field_specs(model_cls)
        for orm_spec in native_specs.values():
            redis_spec = self._field_kind_to_redis_scalar(orm_spec.column_name, orm_spec.kind)
            if redis_spec is not None:
                specs[orm_spec.field_name] = redis_spec
        return specs

    async def _search_index_exists(self, collection: str) -> bool:
        try:
            await self._search(collection).info()
            return True
        except Exception:
            return False

    async def _load_search_fields(self, collection: str) -> dict[str, RedisScalarFieldSpec]:
        if collection in self._search_fields:
            return self._search_fields[collection]
        meta = await self._load_collection_meta(collection) or {}
        specs = self._deserialize_search_fields(meta.get("search_fields"))
        if "id" not in specs:
            specs["id"] = RedisScalarFieldSpec(field_path="id", kind="string")
        self._search_fields[collection] = specs
        return specs

    async def _restore_collection_state(self) -> None:
        collections = await self._async_collection_names()
        self._known_collections.update(collections)
        for collection in collections:
            await self._load_search_fields(collection)

    async def _upsert_collection_meta(
        self,
        collection: str,
        *,
        model_cls: type[ORMModel] | None = None,
        search_fields: Mapping[str, RedisScalarFieldSpec] | None = None,
    ) -> dict[str, object]:
        existing = await self._load_collection_meta(collection) or {}
        current_search_fields = self._deserialize_search_fields(existing.get("search_fields"))
        if search_fields is not None:
            current_search_fields.update(dict(search_fields))
        if "id" not in current_search_fields:
            current_search_fields["id"] = RedisScalarFieldSpec(field_path="id", kind="string")
        meta: dict[str, object] = {
            "collection_name": collection,
            "model_module": existing.get("model_module"),
            "model_name": existing.get("model_name"),
            "schema_json": existing.get("schema_json"),
            "search_fields": self._serialize_search_fields(current_search_fields),
        }
        if model_cls is not None:
            meta.update(
                {
                    "model_module": model_cls.__module__,
                    "model_name": model_cls.__name__,
                    "schema_json": _safe_model_schema(model_cls),
                }
            )
            self.register_model(model_cls)
        await self._store_json_value(self._collection_meta_key(collection), meta)
        client = self._client()
        await client.sadd(self._collections_key(), collection)
        self._mark_collection_known(collection)
        self._search_fields[collection] = current_search_fields
        return meta

    async def _ensure_search_index(
        self,
        collection: str,
        *,
        model_cls: type[ORMModel] | None = None,
        _extra_specs: dict[str, "RedisScalarFieldSpec"] | None = None,
    ) -> None:
        desired_specs = await self._load_search_fields(collection)
        if model_cls is not None:
            desired_specs = {**desired_specs, **self._model_search_fields(model_cls)}
        if _extra_specs:
            desired_specs = {**desired_specs, **_extra_specs}
        if not await self._search_index_exists(collection):
            from redis.commands.search.index_definition import IndexDefinition, IndexType

            fields: list[object] = []
            for spec in desired_specs.values():
                fields.extend(build_redis_scalar_fields_flat(spec))
            await self._search(collection).create_index(
                fields,
                definition=IndexDefinition(prefix=[self._search_doc_prefix(collection)], index_type=IndexType.JSON),
            )
            await self._upsert_collection_meta(collection, model_cls=model_cls, search_fields=desired_specs)
            return
        current_specs = await self._load_search_fields(collection)
        missing_specs = [
            spec for field_path, spec in desired_specs.items()
            if field_path not in current_specs
        ]
        if missing_specs:
            fields = []
            for spec in missing_specs:
                fields.extend(build_redis_scalar_fields_flat(spec))
            await self._search(collection).alter_schema_add(fields)
        if model_cls is not None or missing_specs or _extra_specs:
            await self._upsert_collection_meta(collection, model_cls=model_cls, search_fields=desired_specs)

    def _object_id_from_doc_key(self, collection: str, key: str) -> str:
        prefix = self._search_doc_prefix(collection)
        return key[len(prefix):] if key.startswith(prefix) else key

    async def _load_json_value(self, key: str) -> object | None:
        return await self._client().json().get(key)

    async def _store_json_value(self, key: str, payload: object, *, ttl: int | None = None, keep_ttl: bool = False) -> None:
        client = self._client()
        preserved_ttl_ms: int | None = None
        if keep_ttl:
            raw_ttl = int(await client.pttl(key))
            if raw_ttl > 0:
                preserved_ttl_ms = raw_ttl
        await client.json().set(key, "$", payload)
        if ttl is not None:
            await client.expire(key, ttl)
        elif preserved_ttl_ms is not None:
            await client.pexpire(key, preserved_ttl_ms)
        elif not keep_ttl:
            await client.persist(key)

    async def _load_collection_meta(self, collection: str) -> dict[str, object] | None:
        payload = await self._load_json_value(self._collection_meta_key(collection))
        if isinstance(payload, Mapping):
            return dict(payload)
        return None

    async def _load_doc(self, collection: str, object_id: str) -> dict[str, object] | None:
        payload = await self._load_json_value(self._doc_key(collection, object_id))
        if isinstance(payload, Mapping):
            return dict(payload)
        return None

    @staticmethod
    def _payload_from_doc(doc: Mapping[str, object], object_id: str) -> dict[str, object]:
        """Extract user payload from flat doc, stripping ``_sys``."""
        result = {k: v for k, v in doc.items() if k != "_sys"}
        return _restore_payload_from_storage(result, object_id)

    async def _touch_doc(self, collection: str, object_id: str) -> None:
        try:
            await self._client().json().set(self._doc_key(collection, object_id), "$._sys.accessed_at", _now_ts())
        except Exception:
            pass

    async def _prune_missing_document(self, collection: str, object_id: str) -> int:
        await self._client().srem(self._collection_ids_key(collection), self._decode_text(object_id))
        return 1

    def _payload_from_search_doc(self, collection: str, document: _RedisSearchDocument) -> dict[str, object]:
        raw_doc = decode_redis_search_value(getattr(document, "json", None))
        doc: dict[str, object]
        if isinstance(raw_doc, Mapping):
            doc = {k: v for k, v in raw_doc.items() if k != "_sys"}
        else:
            doc = {}
        object_id = str(doc.get("id") or self._object_id_from_doc_key(collection, str(getattr(document, "id", ""))))
        return _restore_payload_from_storage(doc, object_id)

    def _build_query_string(self, collection: str, query: "QueryLike") -> str:
        specs = self._search_fields.get(collection, {})
        return compile_redis_query(query, specs)

    async def _iter_search_docs(
        self,
        collection: str,
        *,
        query_string: str,
        return_fields: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        sort_by: str | None = None,
        sort_asc: bool = True,
        query_params: Mapping[str, object] | None = None,
    ) -> AsyncGenerator[_RedisSearchDocument, None]:
        from redis.commands.search.query import Query

        remaining = limit
        current_offset = int(offset)
        page_size = max(1, min(200, remaining if remaining is not None else 200))
        while True:
            query = Query(query_string).dialect(2).paging(current_offset, page_size)
            if sort_by:
                query.sort_by(sort_by, asc=sort_asc)
            for path, alias in return_fields:
                query.return_field(path, as_field=alias)
            result = await self._search(collection).search(query, query_params=dict(query_params or {}))
            page_docs = list(cast(Sequence[_RedisSearchDocument], getattr(result, "docs", ())))
            if not page_docs:
                break
            for doc in page_docs:
                yield doc
            current_offset += len(page_docs)
            if remaining is not None:
                remaining -= len(page_docs)
                if remaining <= 0:
                    break
                page_size = max(1, min(200, remaining))
            if len(page_docs) < page_size:
                break

    def list_collection_meta(self) -> list[dict[str, object]]:
        raise RuntimeError("Use async list_collection_meta via search/dump_collection")

    async def collection_count(self, collection: str) -> int:
        from redis.commands.search.query import Query

        await self._ensure_ready()
        if not await self._search_index_exists(collection):
            return 0
        result = await self._search(collection).search(Query("*").dialect(2).paging(0, 0).no_content())
        return int(getattr(result, "total", 0) or 0)

    async def query_count(self, collection: CollectionLike[ORMModel], query: "QueryLike" = None) -> int:
        from redis.commands.search.query import Query

        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return 0
        try:
            query_string = self._build_query_string(collection_name, query)
        except RedisSearchQueryError:
            query_string = "*"
        if query_string != "*" or query is None:
            result = await self._search(collection_name).search(Query(query_string).dialect(2).paging(0, 0).no_content())
            return int(getattr(result, "total", 0) or 0)
        # fallback: count in memory
        count = 0
        from .client_base import _match_query_or_expr
        async for document in self._iter_search_docs(collection_name, query_string="*", return_fields=[("$", "json")]):
            payload = self._payload_from_search_doc(collection_name, document)
            if _match_query_or_expr(payload, query):
                count += 1
        return count

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        await self._ensure_ready()
        collection = model_cls.CollectionName
        with _get_schema_lock(collection):
            await self._ensure_search_index(collection, model_cls=model_cls)
        self._bootstrapped_collections.add(collection)

    def _raw_search_fields_from_specs(self, specs: Mapping[str, ORMFieldSpec]) -> dict[str, RedisScalarFieldSpec]:
        fields: dict[str, RedisScalarFieldSpec] = {}
        for spec in specs.values():
            redis_spec = self._field_kind_to_redis_scalar(spec.column_name, spec.kind)
            if redis_spec is not None:
                fields[spec.field_name] = redis_spec
        return fields

    async def raw_create_collection(self, collection: str, schema: Mapping[str, object] | None = None) -> None:
        await self._ensure_ready()
        collection_name = _validate_collection_name(collection)
        specs = await self._ensure_raw_specs(collection_name, schema=schema)
        search_fields = self._raw_search_fields_from_specs(specs)
        schema_json = _raw_schema_from_specs(collection_name, specs) if specs else (dict(schema) if schema is not None else None)
        with _get_schema_lock(collection_name):
            await self._ensure_search_index(collection_name, _extra_specs=search_fields)
            meta = await self._load_collection_meta(collection_name) or {}
            meta["collection_name"] = collection_name
            meta["schema_json"] = schema_json
            await self._store_json_value(self._collection_meta_key(collection_name), meta)
            await self._client().sadd(self._collections_key(), collection_name)
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
        await self._ensure_ready()
        collection_name = _validate_collection_name(collection)
        normalized_payload = _normalize_raw_orm_payload(payload)
        specs = await self._ensure_raw_specs(collection_name, payload=normalized_payload)
        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        await self.raw_create_collection(collection_name, _raw_schema_from_specs(collection_name, specs) if specs else None)

        object_id = str(normalized_payload.get("id") or normalized_payload.get("_id"))
        now = _now_ts()
        db_payload = remap_payload_to_db(normalized_payload, self._get_field_name_map(collection_name))
        doc: dict[str, object] = {"id": object_id}
        doc.update(db_payload)
        doc["_sys"] = {
            "expire_at": _normalize_expire_at(expire if expire is not None else self._default_expire),
            "size": _estimate_json_size(db_payload),
            "accessed_at": now,
        }
        expire_at = doc["_sys"]["expire_at"]
        ttl = None if expire_at is None else max(1, int(expire_at - now))
        await self._store_json_value(self._doc_key(collection_name, object_id), doc, ttl=ttl)
        client = self._client()
        await client.sadd(self._collection_ids_key(collection_name), object_id)
        await client.sadd(self._collections_key(), collection_name)
        self._schedule_cleanup()
        return object_id

    async def drop_collection(self, collection: CollectionLike[ORMModel]) -> None:
        await self._ensure_ready()
        collection_name, model_cls = self._normalize_collection(collection)
        client = self._client()

        # cascade cleanup: delete file_id refs for all docs
        specs = self._get_native_field_specs(collection_name)
        has_file_id = specs and any(s.kind == "file_id" for s in specs.values())
        if has_file_id:
            members = await client.smembers(self._collection_ids_key(collection_name)) or []
            for raw_oid in members:
                oid = self._decode_text(raw_oid)
                doc = await self._load_doc(collection_name, oid)
                if doc is not None:
                    payload = self._payload_from_doc(doc, oid)
                    await self._cleanup_foreign_on_delete(collection_name, payload)

        try:
            await self._search(collection_name).dropindex(delete_documents=True)
        except Exception:
            pass
        await client.delete(self._collection_ids_key(collection_name), self._collection_meta_key(collection_name))
        await client.srem(self._collections_key(), collection_name)
        self._collection_models.pop(collection_name, None)
        self._search_fields.pop(collection_name, None)
        self._forget_collection(collection_name)
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
        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return
        try:
            query_string = self._build_query_string(collection_name, query)
        except RedisSearchQueryError:
            query_string = "*"
        needs_mem_filter = query_string == "*" and query is not None
        emitted = 0
        skipped = 0
        async for document in self._iter_search_docs(
            collection_name,
            query_string=query_string,
            return_fields=[("$", "json")],
            limit=None if needs_mem_filter else limit,
            offset=0 if needs_mem_filter else offset,
        ):
            payload = self._payload_from_search_doc(collection_name, document)
            object_id = str(payload.get("id") or self._object_id_from_doc_key(collection_name, str(getattr(document, "id", ""))))
            if needs_mem_filter:
                from .client_base import _match_query_or_expr
                if not _match_query_or_expr(payload, query):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                if limit is not None and emitted >= limit:
                    break
                emitted += 1
            await self._touch_doc(collection_name, object_id)
            yield await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

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
        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return
        sort_items = [(str(field or "").strip(), str(direction or "asc").lower()) for field, direction in sort if str(field or "").strip()]
        if not sort_items:
            async for item in self.search(collection, query, limit=limit, offset=offset, as_model=as_model):
                yield item
            return
        if len(sort_items) != 1:
            raise RedisSearchQueryError("Redis ORM native sort currently supports exactly one sort field.")
        sort_field, sort_direction = sort_items[0]
        specs = self._search_fields.get(collection_name, {})
        spec = specs.get(sort_field)
        if spec is None:
            raise RedisSearchQueryError(f"Redis sort field `{sort_field}` is not indexed.")
        try:
            qs = self._build_query_string(collection_name, query)
        except RedisSearchQueryError:
            qs = "*"
        needs_mem_filter = qs == "*" and query is not None
        emitted = 0
        skipped = 0
        async for document in self._iter_search_docs(
            collection_name,
            query_string=qs,
            return_fields=[("$", "json")],
            limit=None if needs_mem_filter else limit,
            offset=0 if needs_mem_filter else offset,
            sort_by=redis_scalar_sort_alias(spec),
            sort_asc=sort_direction != "desc",
        ):
            payload = self._payload_from_search_doc(collection_name, document)
            object_id = str(payload.get("id") or self._object_id_from_doc_key(collection_name, str(getattr(document, "id", ""))))
            if needs_mem_filter:
                from .client_base import _match_query_or_expr
                if not _match_query_or_expr(payload, query):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                if limit is not None and emitted >= limit:
                    break
                emitted += 1
            await self._touch_doc(collection_name, object_id)
            yield await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

    async def selected_search(
        self,
        collection: CollectionLike[ModelT],
        *,
        fields: Sequence[str],
        query: "QueryLike" = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[ORMPayload, None]:
        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return
        normalized_fields = _normalize_selected_fields(fields)
        try:
            query_string = self._build_query_string(collection_name, query)
        except RedisSearchQueryError:
            query_string = "*"
        needs_mem_filter = query_string == "*" and query is not None
        fnmap = self._get_field_name_map(collection_name)
        return_fields: list[tuple[str, str]] = []
        alias_pairs: list[tuple[str, str]] = []
        for index, field in enumerate(normalized_fields):
            alias = "__id" if field in {"id", "_id"} else f"__sel_{index}"
            db_field = _translate_field_path(field, fnmap) if fnmap else field
            path = redis_json_path(db_field)
            return_fields.append((path, alias))
            alias_pairs.append((field, alias))
        if needs_mem_filter:
            return_fields = [("$", "json")]
        emitted = 0
        skipped = 0
        async for document in self._iter_search_docs(
            collection_name,
            query_string=query_string,
            return_fields=return_fields,
            limit=None if needs_mem_filter else limit,
            offset=0 if needs_mem_filter else offset,
        ):
            if needs_mem_filter:
                payload = self._payload_from_search_doc(collection_name, document)
                from .client_base import _match_query_or_expr
                if not _match_query_or_expr(payload, query):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                if limit is not None and emitted >= limit:
                    break
                emitted += 1
                # project selected fields from full payload
                values: list[tuple[str, object]] = []
                for field, _ in alias_pairs:
                    if field in {"id", "_id"}:
                        values.append((field, payload.get("id")))
                    else:
                        values.append((field, _deep_get(payload, field)))
                yield _project_selected_pairs(values)
            else:
                values2: list[tuple[str, object]] = []
                for field, alias in alias_pairs:
                    raw_value = getattr(document, alias, None)
                    if field in {"id", "_id"} and raw_value is None:
                        raw_value = self._object_id_from_doc_key(collection_name, str(getattr(document, "id", "")))
                    values2.append((field, decode_redis_search_value(raw_value)))
                yield _project_selected_pairs(values2)

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
        await self._ensure_ready()
        collection_name, payload, model_cls = self._normalize_value(value, collection=collection)
        if model_cls is None:
            raise ValueError(
                f"Collection `{collection_name}` does not map to a loaded ORMModel class; "
                "raw dict writes require a defined ORM model."
            )
        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        if collection_name not in self._bootstrapped_collections:
            await self._ensure_search_index(collection_name, model_cls=model_cls)
            self._bootstrapped_collections.add(collection_name)

        object_id = str(payload.get("id") or payload.get("_id"))
        now = _now_ts()
        existing = await self._load_doc(collection_name, object_id)

        # ── file_id ref counting on overwrite ──
        specs = self._get_native_field_specs(collection_name)
        file_id_specs = [s for s in (specs or {}).values() if s.kind == "file_id"]
        if file_id_specs and existing:
            old_payload = self._payload_from_doc(existing, object_id)
            await self._handle_file_id_ref_on_overwrite(collection_name, old_payload, payload)

        db_payload = remap_payload_to_db(payload, self._get_field_name_map(collection_name))
        existing_sys = (existing or {}).get("_sys") or {}
        doc: dict[str, object] = {"id": object_id}
        doc.update(db_payload)
        doc["_sys"] = {
            "expire_at": _normalize_expire_at(expire if expire is not None else self._default_expire),
            "size": _estimate_json_size(db_payload),
            "accessed_at": now,
        }
        expire_at = doc["_sys"]["expire_at"]
        ttl = None if expire_at is None else max(1, int(expire_at - now))
        await self._store_json_value(self._doc_key(collection_name, object_id), doc, ttl=ttl)
        client = self._client()
        await client.sadd(self._collection_ids_key(collection_name), object_id)
        await client.sadd(self._collections_key(), collection_name)
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
        await self._ensure_ready()

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

        if collection_name not in self._bootstrapped_collections:
            await self._ensure_search_index(collection_name, model_cls=model_cls)
            self._bootstrapped_collections.add(collection_name)

        client = self._client()
        pipe = client.pipeline()
        now = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        field_name_map = self._get_field_name_map(collection_name)
        ids_key = self._collection_ids_key(collection_name)
        collections_key = self._collections_key()
        object_ids: list[str] = []

        for payload in payloads:
            object_id = str(payload.get("id") or payload.get("_id"))
            object_ids.append(object_id)
            doc_key = self._doc_key(collection_name, object_id)
            existing = await self._load_doc(collection_name, object_id)
            existing_sys = (existing or {}).get("_sys") or {}
            db_payload = remap_payload_to_db(payload, field_name_map)
            doc: dict[str, object] = {"id": object_id}
            doc.update(db_payload)
            doc["_sys"] = {
                "expire_at": expire_at,
                "size": _estimate_json_size(db_payload),
                "accessed_at": now,
            }
            ttl = None if expire_at is None else max(1, int(expire_at - now))
            pipe.json().set(doc_key, "$", doc)
            if ttl is None:
                pipe.persist(doc_key)
            else:
                pipe.expire(doc_key, ttl)
            pipe.sadd(ids_key, object_id)
        pipe.sadd(collections_key, collection_name)
        await pipe.execute()
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
        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        object_id_text = str(object_id)
        doc = await self._load_doc(collection_name, object_id_text)
        if doc is None:
            await self._prune_missing_document(collection_name, object_id_text)
            return None
        payload = self._payload_from_doc(doc, object_id_text)
        await self._touch_doc(collection_name, object_id_text)
        return await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

    async def delete(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> bool:
        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        object_id_text = str(object_id)
        client = self._client()

        # cascade cleanup: fetch file_id fields before deleting
        specs = self._get_native_field_specs(collection_name)
        has_file_id = specs and any(s.kind == "file_id" for s in specs.values())
        if has_file_id:
            doc = await self._load_doc(collection_name, object_id_text)
            if doc is not None:
                payload = self._payload_from_doc(doc, object_id_text)
                await self._cleanup_foreign_on_delete(collection_name, payload)

        removed = await client.delete(self._doc_key(collection_name, object_id_text))
        await client.srem(self._collection_ids_key(collection_name), object_id_text)
        return bool(removed)

    async def delete_many(self, collection: CollectionLike[ORMModel], object_ids: Sequence[str | ObjectId]) -> dict[str, bool]:
        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        object_id_texts = [str(object_id or "").strip() for object_id in object_ids]
        object_id_texts = [object_id for object_id in object_id_texts if object_id]
        if not object_id_texts:
            return {}

        client = self._client()
        doc_keys = [self._doc_key(collection_name, object_id) for object_id in object_id_texts]
        load_pipe = client.pipeline(transaction=False)
        for doc_key in doc_keys:
            load_pipe.json().get(doc_key)
        raw_docs = await load_pipe.execute()

        results = {object_id: isinstance(raw_doc, Mapping) for object_id, raw_doc in zip(object_id_texts, raw_docs)}

        specs = self._get_native_field_specs(collection_name)
        has_file_id = specs and any(spec.kind == "file_id" for spec in specs.values())
        if has_file_id:
            for object_id, raw_doc in zip(object_id_texts, raw_docs):
                if not isinstance(raw_doc, Mapping):
                    continue
                payload = self._payload_from_doc(dict(raw_doc), object_id)
                await self._cleanup_foreign_on_delete(collection_name, payload)

        delete_pipe = client.pipeline(transaction=False)
        ids_key = self._collection_ids_key(collection_name)
        for object_id, doc_key in zip(object_id_texts, doc_keys):
            if results[object_id]:
                delete_pipe.delete(doc_key)
            delete_pipe.srem(ids_key, object_id)
        await delete_pipe.execute()
        return results

    async def set_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId, expire: float | int | None) -> bool:
        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        object_id_text = str(object_id)
        client = self._client()
        doc_key = self._doc_key(collection_name, object_id_text)
        if not await client.exists(doc_key):
            await self._prune_missing_document(collection_name, object_id_text)
            return False
        expire_at = _normalize_expire_at(expire)
        if expire_at is None:
            updated = bool(await client.persist(doc_key))
        else:
            updated = bool(await client.expire(doc_key, max(1, int(expire_at - _now_ts()))))
        try:
            now = _now_ts()
            await client.json().set(doc_key, "$._sys.expire_at", expire_at)
        except Exception:
            pass
        return updated

    async def get_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> float | None:
        await self._ensure_ready()
        collection_name, _ = self._normalize_collection(collection)
        object_id_text = str(object_id)
        ttl = await self._client().ttl(self._doc_key(collection_name, object_id_text))
        if ttl == -2:
            await self._prune_missing_document(collection_name, object_id_text)
            return None
        if ttl == -1:
            return None
        if ttl < 0:
            return 0.0
        return float(ttl)

    async def cleanup(self, *, force: bool = False) -> int:
        if not await self._should_cleanup_async(force=force):
            return 0
        async with self._cleanup_async_lock():
            if not await self._should_cleanup_async(force=force):
                return 0
            removed = 0
            with self._cleanup_lock:
                total_size = 0
                rows: list[tuple[str, str, int, float]] = []
                client = self._client()
                for collection_name in await self._async_collection_names():
                    raw_ids = list(await client.smembers(self._collection_ids_key(collection_name)) or [])
                    object_ids = [self._decode_text(raw) for raw in raw_ids]
                    if not object_ids:
                        continue
                    doc_keys = [self._doc_key(collection_name, oid) for oid in object_ids]
                    pipe = client.pipeline(transaction=False)
                    for doc_key in doc_keys:
                        pipe.json().get(doc_key)
                    results = await pipe.execute()
                    orphaned: list[str] = []
                    for object_id, payload in zip(object_ids, results):
                        if payload is None or not isinstance(payload, Mapping):
                            orphaned.append(object_id)
                            continue
                        doc = dict(payload)
                        sys_meta = doc.get("_sys") or {}
                        size = int(sys_meta.get("size") or 0)
                        accessed_at = float(sys_meta.get("accessed_at") or 0.0)
                        total_size += size
                        rows.append((collection_name, object_id, size, accessed_at))
                    if orphaned:
                        prune_pipe = client.pipeline(transaction=False)
                        ids_key = self._collection_ids_key(collection_name)
                        for object_id in orphaned:
                            prune_pipe.srem(ids_key, object_id)
                        await prune_pipe.execute()
                        removed += len(orphaned)
                total_count = len(rows)
                if self._max_size is not None and total_count > self._max_size:
                    target = max(0, int(self._max_size * 0.9))
                    for collection_name, object_id, size, _ in sorted(rows, key=lambda item: item[3]):
                        if total_count <= target:
                            break
                        if await self.delete(collection_name, object_id):
                            total_count -= 1
                            removed += 1
                await self._mark_cleanup_async()
            return removed

    async def _async_collection_exists(self, collection: str) -> bool:
        if collection in self._known_collections:
            return True
        meta = await self._load_collection_meta(collection)
        if meta is not None:
            self._mark_collection_known(collection)
            await self._load_search_fields(collection)
            return True
        return False

    def _collection_exists(self, collection: str) -> bool:
        return collection in self._known_collections

    async def _load_stored_schema(self, collection: str) -> dict[str, object] | None:
        try:
            meta = await self._load_collection_meta(collection)
        except Exception:
            return None
        if meta is None:
            return None
        raw = meta.get("schema_json")
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        try:
            return _json_loads(raw)
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────────────────────
# Log/Metrics ORM models & protocol stores

__all__ = ['RedisORMClient']
