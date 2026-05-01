import logging
import asyncio
import re as _re
from contextlib import nullcontext
from datetime import date, datetime

from abc import ABC, abstractmethod
from pathlib import Path
from typing import (
    AsyncGenerator, Literal, Mapping, Self, Sequence, TypeAlias, cast,
    TypeVar, overload, TYPE_CHECKING,
)
from typing_extensions import Unpack

if TYPE_CHECKING:
    from ...utils.data_structs.files.base import FileID
from .query import (
    QueryExpression,
    _FieldExpression,
    _ParamCounter,
    _q,
)
from .field_metadata import (
    build_field_name_mapping,
    check_schema_conflict,
    remap_payload_from_db,
    _translate_field_path,
)
from .field_schema import (
    FieldKind,
    ORMFieldSpec,
    deserialize_field_value,
    extract_field_specs,
    serialize_field_value,
)
from ..base import (
    SchemaInfo,
    StorageClientBase,
    StorageClientInitParams,
    _deep_get,
    _json_loads,
    ObjectId,
)
from .model import ORMModel, ModelT, CollectionLike, QueryLike


ORMPayloadLike: TypeAlias = Mapping[str, object]
ORMPayload: TypeAlias = dict[str, object]
RawORMSchema: TypeAlias = Mapping[str, object]
HydratedORMDocument: TypeAlias = ORMModel | ORMPayload
_RowT = TypeVar("_RowT")


class ORMClientInitParams(StorageClientInitParams, total=False):
    namespace: str
    default_expire: float | None

class SQLiteORMClientInitParams(ORMClientInitParams, total=False):
    db_path: str | Path
    write_buffer_size: int

class SQLORMClientInitParams(ORMClientInitParams, total=False):
    url: str


class PostgreSQLORMClientInitParams(SQLORMClientInitParams, total=False):
    host: str
    port: int
    username: str
    password: str | None
    database: str


class MongoORMClientInitParams(ORMClientInitParams, total=False):
    mongo_url: str
    database: str


class RedisORMClientInitParams(ORMClientInitParams, total=False):
    url: str
    prefix: str
    db: int
    decode_responses: bool

class ORM_ClientBase(StorageClientBase, ABC, storage_kind="orm"):

    def __init__(self, **kwargs: Unpack[ORMClientInitParams]) -> None:
        super().__init__(**kwargs)
        self._namespace = kwargs.get("namespace", "default")
        self._default_expire = kwargs.get("default_expire", None)
        self._collection_models: dict[str, type[ORMModel]] = {}
        self._native_field_specs: dict[str, dict[str, ORMFieldSpec]] = {}
        self._field_name_mappings: dict[str, dict[str, str]] = {}
        self._known_collections: set[str] = set()
        self._bootstrapped_collections: set[str] = set()
        self._forgotten_collections: set[str] = set()
        self._collection_init_locks: dict[str, asyncio.Lock] = {}
        if self._auto_start:
            self.start()

    @abstractmethod
    def start(self) -> Self:
        '''Start the client and connect to the backend.

        Called automatically on construction unless *auto_start* is ``False``.
        '''
        ...

    @abstractmethod
    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        '''Ensure the collection for *model_cls* exists in the backend.

        Creates the collection (table / MongoDB collection / etc.) if it does
        not already exist.  Safe to call multiple times.
        '''
        ...

    @abstractmethod
    async def drop_collection(self, collection: CollectionLike[ORMModel]) -> None:
        '''Permanently delete a collection and **all** its documents.

        Args:
            collection: An :class:`ORMModel` subclass or the collection name
                string.
        '''
        ...

    @abstractmethod
    async def raw_create_collection(self, collection: str, schema: RawORMSchema | None = None) -> None:
        '''Ensure a raw collection exists without requiring an ORMModel class.'''
        ...

    @abstractmethod
    async def raw_set(
        self,
        collection: str,
        payload: ORMPayloadLike,
        *,
        expire: float | int | None = None,
        create_collection: bool = True,
    ) -> str:
        '''Insert or replace a raw document without model validation.'''
        ...

    async def raw_get(self, collection: str, object_id: str | ObjectId) -> ORMPayload | None:
        row = await self.get(collection, object_id, as_model=False)
        if not isinstance(row, Mapping):
            return None
        return dict(row)

    async def raw_delete(self, collection: str, object_id: str | ObjectId) -> bool:
        return await self.delete(collection, object_id)

    async def raw_drop_collection(self, collection: str) -> None:
        await self.drop_collection(collection)

    async def raw_query(
        self,
        collection: str,
        query: QueryLike = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[ORMPayload, None]:
        async for row in self.search(collection, query, limit=limit, offset=offset, as_model=False):
            if isinstance(row, Mapping):
                yield dict(row)

    async def delete_many(self, collection: CollectionLike[ORMModel], object_ids: Sequence[str | ObjectId]) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for object_id in object_ids:
            object_id_text = str(object_id or "").strip()
            if not object_id_text:
                continue
            results[object_id_text] = bool(await self.delete(collection, object_id_text))
        return results

    @overload
    def dump_collection(self, collection: type[ModelT], *, as_model: Literal[True] = True) -> AsyncGenerator[ModelT, None]: ...

    @overload
    def dump_collection(self, collection: type[ModelT], *, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    @overload
    def dump_collection(self, collection: str, *, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def dump_collection(self, collection: str, *, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    @abstractmethod
    def dump_collection(self, collection: CollectionLike[ORMModel], *, as_model: bool = True) -> AsyncGenerator[HydratedORMDocument, None]:
        '''Yield every document in the collection.
        Args:
            collection: Target collection class or name.
            as_model: When ``True`` (default), deserialize documents into their
                :class:`ORMModel` subclass; ``False`` returns raw dicts.
        Yields:
            Each document in the collection.
        '''
        ...

    @overload
    def search(self, collection: type[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ModelT, None]: ...

    @overload
    def search(self, collection: type[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    @overload
    def search(self, collection: str, query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: str, query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    @abstractmethod
    def search(self, collection: CollectionLike[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: bool = True) -> AsyncGenerator[HydratedORMDocument, None]:
        '''Lazily iterate over documents matching *query*.

        Args:
            collection: Target collection class or name.
            query: Field-equality filter; ``None`` returns all documents.
            limit: Maximum number of documents to yield (``None`` = unlimited).
            offset: Number of matching documents to skip before yielding.
            as_model: Yield typed model instances when ``True``.

        Yields:
            Matching documents one at a time.
        '''
        ...

    async def _first_or_none(self, rows: AsyncGenerator[_RowT, None]) -> _RowT | None:
        try:
            return await anext(rows)
        except StopAsyncIteration:
            return None
        finally:
            await rows.aclose()

    @abstractmethod
    def selected_search(
        self,
        collection: CollectionLike[ModelT],
        *,
        fields: Sequence[str],
        query: "QueryLike" = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[ORMPayload, None]:
        '''Lazily iterate over selected fields for documents matching *query*.

        Notes:
            - Returned rows always include ``id`` even when omitted from
              ``fields``.
            - Dotted field paths are reconstructed as nested dict/list
              structures.
            - Numeric path chunks are treated as list indexes, so ``a.0.b``
              produces ``{"id": ..., "a": [{"b": value}]}``.
        '''
        ...

    async def selected_search_one(
        self,
        collection: CollectionLike[ModelT],
        *,
        fields: Sequence[str],
        query: "QueryLike" = None,
    ) -> dict[str, object] | None:
        return await self._first_or_none(
            self.selected_search(collection, fields=fields, query=query, limit=1)
        )

    async def selected_search_by_id(
        self,
        collection: CollectionLike[ModelT],
        id: str | ObjectId,
        *,
        fields: Sequence[str],
    ) -> dict[str, object] | None:
        return await self.selected_search_one(collection, fields=fields, query={"id": str(id)})

    @overload
    async def search_one(self, collection: type[ModelT], query: "QueryLike" = None, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def search_one(self, collection: type[ModelT], query: "QueryLike" = None, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def search_one(self, collection: str, query: "QueryLike" = None, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def search_one(self, collection: str, query: "QueryLike" = None, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @abstractmethod
    async def search_one(self, collection: CollectionLike[ModelT], query: "QueryLike" = None, *, as_model: bool = True) -> HydratedORMDocument | None:
        '''Return the first document matching *query*, or ``None``.

        Args:
            collection: Target collection class or name.
            query: Field-equality filter; ``None`` matches any document.
            as_model: Return a typed model instance when ``True``.

        Returns:
            First matching document or ``None`` if no match exists.
        '''
        ...

    @overload
    async def search_by_id(self, collection: type[ModelT], id: str | ObjectId, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def search_by_id(self, collection: type[ModelT], id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def search_by_id(self, collection: str, id: str | ObjectId, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def search_by_id(self, collection: str, id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @abstractmethod
    async def search_by_id(self, collection: CollectionLike[ModelT], id: str | ObjectId, *, as_model: bool = True) -> HydratedORMDocument | None:
        '''Fetch a single document by its unique *id*.

        Equivalent to :meth:`get` but participates in the ``search_*`` naming
        convention for consistency with query-based overloads.
        '''
        ...

    @overload
    async def set(self, value: ORMModel, *, expire: float | int | None = None, create_collection: bool = True) -> str: ...

    @overload
    async def set(self, value: ORMPayloadLike, *, collection: CollectionLike[ORMModel], expire: float | int | None = None) -> str: ...

    @abstractmethod
    async def set(self, value: ORMModel | ORMPayloadLike, *, collection: CollectionLike[ORMModel] | None = None, expire: float | int | None = None, create_collection: bool = True) -> str:
        '''Insert or replace a document.

        Args:
            value: An :class:`ORMModel` instance (collection inferred from the
                model) or a plain ``dict`` (``collection`` is required).
            collection: Explicit target collection; ignored when *value* is an
                :class:`ORMModel`.
            expire: Optional TTL in seconds from now, or absolute UNIX
                timestamp (values > 1e9 are treated as absolute).
            create_collection: Auto-create the collection when ``True``
                (default).

        Returns:
            The string object-ID of the upserted document.
        '''
        ...

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
        return list(await asyncio.gather(*[
            self.set(
                value,
                collection=collection,
                expire=expire,
                create_collection=create_collection,
            )   # type: ignore
            for value in batch
        ]))  # type: ignore

    @overload
    async def get(self, collection: type[ModelT], object_id: str | ObjectId, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def get(self, collection: type[ModelT], object_id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def get(self, collection: str, object_id: str | ObjectId, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: str, object_id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @abstractmethod
    async def get(self, collection: CollectionLike[ModelT], object_id: str | ObjectId, *, as_model: bool = True) -> HydratedORMDocument | None:
        '''Retrieve a document by primary key.

        Args:
            collection: Target collection class or name.
            object_id: The ``_id`` of the document to retrieve.
            as_model: Return a typed model instance when ``True``.

        Returns:
            Matching document, or ``None`` if not found.
        '''
        ...

    @abstractmethod
    async def delete(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> bool:
        '''Delete a document by primary key.

        Returns:
            ``True`` if the document existed and was deleted, ``False``
            otherwise.
        '''
        ...

    @abstractmethod
    async def set_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId, expire: float | int | None) -> bool:
        '''Update the expiry of an existing document without changing its data.

        Args:
            collection: Target collection class or name.
            object_id: Document identifier.
            expire: New TTL (seconds), absolute UNIX timestamp, or ``None`` to
                make the document permanent.

        Returns:
            ``True`` if the document was found and updated.
        '''
        ...

    @abstractmethod
    async def get_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> float | None:
        '''Return the absolute UNIX expiry timestamp of a document.

        Returns:
            Expiry timestamp, or ``None`` if the document does not exist or
            has no expiry set.
        '''
        ...

    @abstractmethod
    async def cleanup(self, *, force: bool = False) -> int:
        '''Remove all expired documents from every collection.

        Args:
            force: Skip throttle guard and clean up immediately.

        Returns:
            Total number of documents deleted.
        '''
        ...

    @abstractmethod
    def _collection_exists(self, collection: str) -> bool:
        '''Return ``True`` if the given collection name already exists.'''
        ...

    async def _load_stored_schema(self, collection: str) -> dict[str, object] | None:
        """Load the stored model schema_json for *collection* from the backend.

        Returns ``None`` when the collection does not yet exist or the backend
        does not persist schema information (default: skip conflict check).
        """
        return None

    async def check_schema(self, model_cls: type[ORMModel]) -> SchemaInfo:
        '''Unified schema check entry point.

        If the collection is already bootstrapped in this process, returns
        immediately.  Otherwise delegates to :meth:`main_check_schema` which
        performs DDL and index alignment.

        Workers that received preflight data call
        :meth:`mark_collection_bootstrapped` beforehand so this method becomes
        a fast no-op for them.
        '''
        collection = model_cls.CollectionName
        self.register_model(model_cls)
        if collection in self._bootstrapped_collections:
            if await self._load_stored_schema(collection) is not None:
                return SchemaInfo(collection_name=collection, bootstrapped=True)
            self._forget_collection(collection)
        lock = self._collection_init_locks.setdefault(collection, asyncio.Lock())
        async with lock:
            if collection in self._bootstrapped_collections:
                if await self._load_stored_schema(collection) is not None:
                    return SchemaInfo(collection_name=collection, bootstrapped=True)
                self._forget_collection(collection)
            return await self.main_check_schema(model_cls)

    async def main_check_schema(self, model_cls: type[ORMModel]) -> SchemaInfo:
        '''Heavy schema operations — DDL creation, index alignment, schema
        conflict detection.  Intended to run once per collection in the main
        process.  Workers should skip this via preflight bootstrapping.
        '''
        collection = model_cls.CollectionName
        stored_schema = await self._load_stored_schema(collection)
        check_schema_conflict(model_cls, stored_schema, collection)
        await self.create_collection(model_cls)
        self._known_collections.add(collection)
        self._bootstrapped_collections.add(collection)
        return SchemaInfo(collection_name=collection, bootstrapped=True)

    async def ensure_collection(self, model_cls: type[ORMModel]) -> None:
        '''Bootstrap a model collection at most once per process.

        Legacy wrapper around :meth:`check_schema`.
        '''
        await self.check_schema(model_cls)

    def mark_collection_bootstrapped(self, collection: CollectionLike[ORMModel]) -> None:
        '''Mark a collection as already schema-bootstrapped in this process.'''
        collection_name, _ = self._normalize_collection(collection)
        self._known_collections.add(collection_name)
        self._forgotten_collections.discard(collection_name)
        self._bootstrapped_collections.add(collection_name)

    def _mark_collection_known(self, collection: str) -> None:
        collection_name = str(collection)
        self._known_collections.add(collection_name)
        self._forgotten_collections.discard(collection_name)

    def _forget_collection(self, collection: str) -> None:
        name = str(collection)
        self._known_collections.discard(name)
        self._bootstrapped_collections.discard(name)
        self._forgotten_collections.add(name)
        self._native_field_specs.pop(name, None)
        self._field_name_mappings.pop(name, None)

    def register_model(self, model_cls: type[ORMModel]) -> None:
        name = model_cls.CollectionName
        if (
            self._collection_models.get(name) is model_cls
            and name in self._native_field_specs
            and name in self._field_name_mappings
        ):
            return
        self._collection_models[name] = model_cls
        self._native_field_specs[name] = extract_field_specs(model_cls)
        self._field_name_mappings[name] = build_field_name_mapping(model_cls)

    def _resolve_collection_model(self, collection_name: str) -> type[ORMModel] | None:
        resolved = self._collection_models.get(collection_name)
        if resolved is not None:
            return resolved

        matches: list[type[ORMModel]] = []
        seen: set[type[ORMModel]] = set()
        for model_cls in ORMModel._iter_model_subclasses():
            if getattr(model_cls, "CollectionName", None) != collection_name:
                continue
            if model_cls in seen:
                continue
            seen.add(model_cls)
            matches.append(model_cls)

        if len(matches) != 1:
            return None

        resolved = matches[0]
        self.register_model(resolved)
        return resolved

    def _get_native_field_specs(self, collection: str) -> dict[str, ORMFieldSpec]:
        return dict(self._native_field_specs.get(str(collection), {}))

    def _get_field_name_map(self, collection: str) -> dict[str, str]:
        return self._field_name_mappings.get(str(collection), {})

    async def _ensure_raw_specs(
        self,
        collection: str,
        *,
        schema: RawORMSchema | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, ORMFieldSpec]:
        collection_name = str(collection)
        existing = dict(self._native_field_specs.get(collection_name, {}))
        if not existing:
            stored_schema = schema if schema is not None else await self._load_stored_schema(collection_name)
            if isinstance(stored_schema, Mapping):
                existing = self._merge_raw_specs(collection_name, _infer_raw_field_specs(schema=stored_schema))
        if payload:
            existing = self._merge_raw_specs(collection_name, _infer_raw_field_specs(payload=payload))
        if collection_name not in self._field_name_mappings:
            self._field_name_mappings[collection_name] = {}
        return existing

    def _merge_raw_specs(self, collection: str, specs: Mapping[str, ORMFieldSpec]) -> dict[str, ORMFieldSpec]:
        collection_name = str(collection)
        merged = dict(self._native_field_specs.get(collection_name, {}))
        changed = False
        for field_name, spec in specs.items():
            if field_name in {"id", "_id"} or field_name.startswith("_"):
                continue
            if field_name not in merged:
                merged[field_name] = spec
                changed = True
        if changed or collection_name not in self._native_field_specs:
            self._native_field_specs[collection_name] = merged
        if changed or collection_name not in self._field_name_mappings:
            self._field_name_mappings[collection_name] = {}
        return merged

    async def _cleanup_foreign_on_delete(self, collection: str, payload: dict[str, object]) -> None:
        """Clean up foreign resources (file_id fields) before deleting a record.

        For ``file_id`` kind fields with ``foreign_model=True``, calls
        ``FileID.Delete()`` to remove the referenced file from object storage.
        """
        specs = self._get_native_field_specs(collection)
        if not specs:
            return
        from ...utils.data_structs.files.base import FileID
        for spec in specs.values():
            if spec.kind != "file_id":
                continue
            value = payload.get(spec.field_name)
            if value is None:
                continue
            file_id = None
            try:
                file_id = _coerce_file_id(value)
                if file_id is None:
                    raise TypeError(f"Unsupported FileID payload type: {type(value).__name__}")
                await FileID.Delete(file_id)
            except Exception as exc:
                _orm_logger.warning(
                    "Failed to cleanup file_id field `%s.%s` (id=%s): %s",
                    collection, spec.field_name, getattr(file_id if file_id is not None else value, "id", "?"), exc,
                )

    async def _handle_file_id_ref_on_overwrite(
        self, collection: str, old_payload: dict[str, object] | None, new_payload: dict[str, object],
    ) -> None:
        """Adjust FileID reference counts when a record is overwritten (set/upsert).

        For each ``file_id`` kind field:
        - If old_payload has a FileID and it differs from new → decrement old
        - If new_payload has a FileID and it differs from old → increment new
        """
        specs = self._get_native_field_specs(collection)
        if not specs:
            return
        file_id_specs = [s for s in specs.values() if s.kind == "file_id"]
        if not file_id_specs:
            return
        from ...utils.data_structs.files.base import FileID

        for spec in file_id_specs:
            old_fid = _coerce_file_id(old_payload.get(spec.field_name)) if old_payload else None
            new_fid = _coerce_file_id(new_payload.get(spec.field_name))

            old_hash = old_fid.id if old_fid else None
            new_hash = new_fid.id if new_fid else None

            if old_hash == new_hash:
                continue  # same content or both None — no change

            # Decrement old ref
            if old_fid and _is_file_id_content_hash(old_fid.id):
                try:
                    await FileID._decr_ref_and_cleanup(old_fid.category, old_fid.id)
                except Exception as exc:
                    _orm_logger.warning(
                        "file_id ref decrement failed for `%s.%s` (id=%s): %s",
                        collection, spec.field_name, old_fid.id, exc,
                    )

            # Increment new ref
            if new_fid and _is_file_id_content_hash(new_fid.id):
                try:
                    await FileID._incr_ref(new_fid.category, new_fid.id)
                except Exception as exc:
                    _orm_logger.warning(
                        "file_id ref increment failed for `%s.%s` (id=%s): %s",
                        collection, spec.field_name, new_fid.id, exc,
                    )

    def _normalize_collection(self, collection: CollectionLike[ModelT]) -> tuple[str, type[ORMModel] | None]:
        if isinstance(collection, type) and issubclass(collection, ORMModel):
            self.register_model(collection)
            return collection.CollectionName, collection
        collection_name = str(collection)
        return collection_name, self._resolve_collection_model(collection_name)

    def _normalize_value(self, value: ORMModel | ORMPayloadLike, *, collection: CollectionLike[ORMModel] | None = None) -> tuple[str, ORMPayload, type[ORMModel] | None]:
        if isinstance(value, ORMModel):
            collection_name = collection or value.CollectionName
            model_cls = type(value)
            _, payload = _prepare_payload_for_write(value._serialize_for_storage())
            self.register_model(model_cls)
            return self._normalize_collection(collection_name)[0], payload, model_cls
        if not isinstance(value, Mapping):
            raise TypeError("ORMClient.set() only accepts ORMModel or plain mapping values.")
        if not collection:
            raise ValueError("`collection` is required when setting a plain mapping.")
        collection_name, model_cls = self._normalize_collection(collection)
        if model_cls is None:
            raise ValueError(
                f"Collection `{collection_name}` does not map to a loaded ORMModel class; "
                "raw dict writes require a defined ORM model."
            )
        raw_payload: ORMPayload = dict(value)
        explicit_id = raw_payload.pop("id", None)
        explicit_alias_id = raw_payload.pop("_id", None)
        if explicit_id is not None and explicit_alias_id is not None and str(explicit_id) != str(explicit_alias_id):
            raise ValueError("Conflicting id values: use either `id` or `_id`, not both.")

        validated = model_cls.model_validate(raw_payload)
        _, payload = _prepare_payload_for_write(validated._serialize_for_storage())
        raw_object_id = explicit_id if explicit_id is not None else explicit_alias_id
        if raw_object_id is not None:
            payload["id"] = str(raw_object_id)
        return collection_name, payload, model_cls

    def _normalize_batch_values(
        self,
        values: Sequence[ORMModel | ORMPayloadLike],
        *,
        collection: CollectionLike[ORMModel] | None = None,
    ) -> tuple[str, list[dict[str, object]], type[ORMModel] | None]:
        batch = list(values)
        if not batch:
            raise ValueError('ORMClient.set_many() requires at least one value.')

        collection_name: str | None = None
        payloads: list[dict[str, object]] = []
        model_cls: type[ORMModel] | None = None
        for value in batch:
            current_collection, payload, current_model_cls = self._normalize_value(value, collection=collection)
            if collection_name is None:
                collection_name = current_collection
            elif collection_name != current_collection:
                raise ValueError('ORMClient.set_many() requires all values to target the same collection.')
            if model_cls is None and current_model_cls is not None:
                model_cls = current_model_cls
            payloads.append(payload)

        assert collection_name is not None
        return collection_name, payloads, model_cls

    @overload
    def _hydrate(self, collection: type[ModelT], payload: dict[str, object], *, as_model: Literal[True] = True, _remapped: bool = False) -> ModelT: ...
    @overload
    def _hydrate(self, collection: type[ModelT], payload: dict[str, object], *, as_model: Literal[False], _remapped: bool = False) -> dict[str, object]: ...
    @overload
    def _hydrate(self, collection: str, payload: dict[str, object], *, as_model: Literal[True] = True, _remapped: bool = False) -> ORMModel | dict[str, object]: ...
    @overload
    def _hydrate(self, collection: str, payload: dict[str, object], *, as_model: Literal[False], _remapped: bool = False) -> dict[str, object]: ...

    def _hydrate(self, collection: CollectionLike[ModelT], payload: dict[str, object], *, as_model: bool = True, _remapped: bool = False) -> ORMModel | dict[str, object]:
        collection_name, model_cls = self._normalize_collection(collection)
        if not _remapped:
            mapping = self._get_field_name_map(collection_name)
            if mapping:
                payload = remap_payload_from_db(payload, mapping)
        if not as_model:
            return payload
        if model_cls is None:
            return payload
        instance = model_cls.model_validate(_coerce_model_payload(payload, model_cls))
        # Newly hydrated instances are in sync with the backend — clear the
        # dirty set seeded by Pydantic from the constructor's fields_set so
        # that a subsequent `save(force=False)` becomes a no-op until the
        # caller actually mutates a field.
        instance._mark_persisted_clean()
        return instance

    @overload
    async def _hydrate_with_foreign(self, collection: type[ModelT], payload: dict[str, object], *, as_model: Literal[True] = True) -> ModelT: ...
    @overload
    async def _hydrate_with_foreign(self, collection: type[ModelT], payload: dict[str, object], *, as_model: Literal[False]) -> dict[str, object]: ...
    @overload
    async def _hydrate_with_foreign(self, collection: str, payload: dict[str, object], *, as_model: Literal[True] = True) -> ORMModel | dict[str, object]: ...
    @overload
    async def _hydrate_with_foreign(self, collection: str, payload: dict[str, object], *, as_model: Literal[False]) -> dict[str, object]: ...

    async def _hydrate_with_foreign(self, collection: CollectionLike[ModelT], payload: dict[str, object], *, as_model: bool = True) -> ORMModel | dict[str, object]:
        """Like :meth:`_hydrate` but resolves foreign-model fields first."""
        collection_name, model_cls = self._normalize_collection(collection)
        mapping = self._get_field_name_map(collection_name)
        if mapping:
            payload = remap_payload_from_db(payload, mapping)
        if as_model and model_cls is not None:
            payload = await _resolve_foreign_payload(payload, model_cls)
        return self._hydrate(collection, payload, as_model=as_model, _remapped=True)

    async def _selected_search_fallback(
        self,
        collection: CollectionLike[ModelT],
        *,
        fields: Sequence[str],
        query: "QueryLike" = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[dict[str, object], None]:
        normalized_fields = _normalize_selected_fields(fields)
        async for item in self.search(collection, query, limit=limit, offset=offset, as_model=False):
            row = dict(item) if isinstance(item, Mapping) else cast(dict[str, object], item)
            yield _project_selected_payload(row, normalized_fields)


# ── Schema helpers ────────────────────────────────────────────────────────────
_orm_logger = logging.getLogger(__name__)

JSONNode: TypeAlias = 'dict[str, JSONNode] | list[JSONNode] | str | int | float | bool | None'
_FILE_ID_CONTENT_HASH_RE = _re.compile(r"^[0-9a-f]{64}$")


def _is_file_id_content_hash(file_id: str) -> bool:
    return bool(_FILE_ID_CONTENT_HASH_RE.fullmatch(str(file_id or "")))


def _coerce_file_id(value: object) -> "FileID | None":
    from ...utils.data_structs.files.base import FileID

    if value is None:
        return None
    if isinstance(value, FileID):
        return value
    if isinstance(value, Mapping):
        raw_value: object = dict(value)
    elif isinstance(value, (str, bytes, bytearray)):
        raw_value = _json_loads(value)
    else:
        return None
    try:
        return FileID.model_validate(raw_value)
    except Exception:
        return None

def _get_schema_lock(name: str):
    """Return a no-op context for schema updates.

    Runtime schema coordination is handled by worker bootstrap broadcast.
    """
    return nullcontext()


def _prepare_payload_for_write(payload: dict[str, object]) -> tuple[str, dict[str, object]]:
    normalized = dict(payload)
    raw_id = normalized.pop("_id", normalized.get("id"))
    if raw_id is None:
        raw_id = ObjectId()
    object_id = str(raw_id)
    normalized["id"] = object_id
    return object_id, normalized


def _normalize_raw_orm_payload(payload: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    explicit_id = normalized.get("id")
    explicit_alias_id = normalized.get("_id")
    if (
        explicit_id is not None
        and explicit_alias_id is not None
        and str(explicit_id) != str(explicit_alias_id)
    ):
        raise ValueError("Conflicting id values: use either `id` or `_id`, not both.")
    return _prepare_payload_for_write(normalized)[1]


def _raw_schema_property_kind(
    property_schema: Mapping[str, object],
) -> tuple[FieldKind, bool, int | None]:
    nullable = False
    schema_obj: Mapping[str, object] = property_schema
    raw_type = schema_obj.get("type")

    if isinstance(raw_type, list):
        type_names = {str(item).strip().lower() for item in raw_type if str(item).strip()}
        nullable = "null" in type_names
        type_names.discard("null")
        raw_type = next(iter(type_names), None)

    if raw_type is None:
        for bucket_name in ("anyOf", "oneOf"):
            bucket = schema_obj.get(bucket_name)
            if not isinstance(bucket, Sequence) or isinstance(bucket, (str, bytes, bytearray)):
                continue
            normalized_options = [item for item in bucket if isinstance(item, Mapping)]
            if not normalized_options:
                continue
            for option in normalized_options:
                option_type = str(option.get("type") or "").strip().lower()
                if option_type == "null":
                    nullable = True
                    continue
                schema_obj = option
                raw_type = option_type or option.get("type")
                break
            if raw_type is not None:
                break

    type_name = str(raw_type or "object").strip().lower()
    if type_name == "boolean":
        return "bool", nullable, None
    if type_name == "integer":
        return "int", nullable, None
    if type_name == "number":
        return "float", nullable, None
    if type_name == "string":
        format_name = str(schema_obj.get("format") or "").strip().lower()
        max_length = schema_obj.get("maxLength")
        if format_name == "date":
            return "date", nullable, None
        if format_name in {"date-time", "datetime"}:
            return "datetime", nullable, None
        return "str", nullable, int(max_length) if isinstance(max_length, int) else None
    return "json", True if type_name in {"array", "object"} else nullable, None


def _raw_value_field_kind(value: object) -> tuple[FieldKind, bool, int | None]:
    if value is None:
        return "json", True, None
    if isinstance(value, bool):
        return "bool", False, None
    if isinstance(value, int) and not isinstance(value, bool):
        return "int", False, None
    if isinstance(value, float):
        return "float", False, None
    if isinstance(value, datetime):
        return "datetime", False, None
    if isinstance(value, date):
        return "date", False, None
    if isinstance(value, str):
        return "str", False, max(len(value), 1)
    return "json", False, None


def _infer_raw_field_specs(
    *,
    schema: RawORMSchema | None = None,
    payload: Mapping[str, object] | None = None,
) -> dict[str, ORMFieldSpec]:
    inferred: dict[str, ORMFieldSpec] = {}

    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    required_values = schema.get("required") if isinstance(schema, Mapping) else None
    required: set[str] = set()
    if isinstance(required_values, Sequence) and not isinstance(required_values, (str, bytes, bytearray)):
        required = {str(item) for item in required_values if str(item or "").strip()}
    if isinstance(properties, Mapping):
        for raw_name, raw_schema in properties.items():
            field_name = str(raw_name or "").strip()
            if not field_name or field_name in {"id", "_id"} or field_name.startswith("_"):
                continue
            kind, nullable, max_length = _raw_schema_property_kind(raw_schema) if isinstance(raw_schema, Mapping) else ("json", True, None)
            inferred[field_name] = ORMFieldSpec(
                field_name=field_name,
                column_name=field_name,
                kind=kind,
                nullable=field_name not in required if nullable else False,
                index=None,
                max_length=max_length,
            )

    if isinstance(payload, Mapping):
        for raw_name, value in payload.items():
            field_name = str(raw_name or "").strip()
            if not field_name or field_name in {"id", "_id"} or field_name.startswith("_"):
                continue
            if field_name in inferred:
                continue
            kind, nullable, max_length = _raw_value_field_kind(value)
            inferred[field_name] = ORMFieldSpec(
                field_name=field_name,
                column_name=field_name,
                kind=kind,
                nullable=nullable,
                index=None,
                max_length=max_length,
            )
    return inferred


def _raw_schema_from_specs(collection: str, specs: Mapping[str, ORMFieldSpec]) -> dict[str, object]:
    properties: dict[str, object] = {}
    required: list[str] = []
    for field_name, spec in specs.items():
        property_schema: dict[str, object]
        if spec.kind == "bool":
            property_schema = {"type": "boolean"}
        elif spec.kind == "int":
            property_schema = {"type": "integer"}
        elif spec.kind == "float":
            property_schema = {"type": "number"}
        elif spec.kind == "date":
            property_schema = {"type": "string", "format": "date"}
        elif spec.kind == "datetime":
            property_schema = {"type": "string", "format": "date-time"}
        elif spec.kind == "str":
            property_schema = {"type": "string"}
            if spec.max_length is not None:
                property_schema["maxLength"] = int(spec.max_length)
        else:
            property_schema = {"type": "object" if spec.kind in {"foreign_single", "json", "blob_single", "blob_union", "file_id"} else "array"}
        if spec.nullable:
            property_schema["type"] = [property_schema["type"], "null"]
            property_schema.pop("format", None)
        else:
            required.append(field_name)
        properties[field_name] = property_schema
    schema_json: dict[str, object] = {
        "title": f"RawORMCollection:{collection}",
        "type": "object",
        "properties": properties,
    }
    if required:
        schema_json["required"] = required
    return schema_json


def _restore_payload_from_storage(payload: dict[str, object], object_id: str | ObjectId | None = None) -> dict[str, object]:
    restored = dict(payload)
    raw_id = restored.pop("_id", restored.get("id", object_id))
    if raw_id is not None:
        restored["id"] = str(raw_id)
    return restored


def _q(col: str, dialect: str = "sqlite") -> str:
    """Quote a column/identifier for SQL. MySQL uses backticks, others double quotes."""
    d = str(dialect or "").lower()
    if d in {"mysql", "mariadb"}:
        return f"`{col}`"
    return f'"{col}"'


def _native_column_values(
    payload: Mapping[str, object],
    specs: Mapping[str, ORMFieldSpec] | None,
) -> dict[str, object]:
    values: dict[str, object] = {}
    for field_name, spec in (specs or {}).items():
        values[spec.column_name] = serialize_field_value(spec, payload.get(field_name))
    return values


def _deserialize_row(
    row: 'Mapping[str, object]',
    specs: Mapping[str, ORMFieldSpec],
    *,
    field_name_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Build a payload dict from a data-table + sys-table row.

    *row* must be an ``aiosqlite.Row`` (or dict-like) containing at least
    the data-table columns.  For ``blob_union`` fields the row must also
    contain ``{column}_type`` from the sys table.

    Non-nullable fields whose DB value is NULL are **omitted** so that
    Pydantic model_validate can fall back to field defaults.
    """
    payload: dict[str, object] = {"id": str(row["id"])}
    for field_name, spec in specs.items():
        col = spec.column_name
        try:
            db_value = row[col]
        except (KeyError, IndexError):
            db_value = None
        if db_value is None:
            # Only include explicit None for nullable fields;
            # non-nullable fields are omitted so Pydantic uses defaults.
            if spec.nullable:
                payload[field_name] = None
            continue
        if spec.kind == "blob_union":
            type_col = f"{col}_type"
            try:
                raw_media_type = row[type_col]
            except (KeyError, IndexError):
                raw_media_type = None
            media_type = raw_media_type if isinstance(raw_media_type, str) else None
            payload[field_name] = deserialize_field_value(spec, db_value, media_type=media_type)
        else:
            payload[field_name] = deserialize_field_value(spec, db_value)
    return payload


def _build_sql_sort_clauses(
    sort: Sequence[tuple[str, str]],
    *,
    dialect: str,
    native_fields: Mapping[str, ORMFieldSpec] | None = None,
    field_name_map: dict[str, str] | None = None,
) -> list[str]:
    clauses: list[str] = []
    for raw_field, raw_direction in sort:
        field = _validate_selected_field_name(str(raw_field or ""))
        expr = _sql_json_field_expr(dialect, field, native_fields=native_fields, field_name_map=field_name_map)
        if expr is None:
            raise ValueError(f"Unsupported sort field `{field}` for {dialect} backend.")
        direction = "DESC" if str(raw_direction or "asc").lower() == "desc" else "ASC"
        clauses.append(f"{expr} {direction}")
    return clauses


async def _resolve_foreign_payload(payload: dict[str, object], model_cls: type[ORMModel]) -> dict[str, object]:
    """Resolve foreign-model ID strings in *payload* to full model instances.

    Modifies *payload* **in-place** and returns it for chaining.
    """
    foreign_fields = model_cls._get_foreign_fields()
    if not foreign_fields:
        return payload

    async def _resolve_one(name: str, target_cls: type[ORMModel], nullable: bool):
        value = payload.get(name)
        if value is None or isinstance(value, ORMModel):
            return name, value
        if isinstance(value, (str, ObjectId)):
            result = await target_cls.SearchOneById(str(value))
            if result is None and not nullable:
                raise ValueError(
                    f"Foreign model {target_cls.__name__} with id={value!r} "
                    f"not found for required field `{name}` in {model_cls.__name__}"
                )
            return name, result
        return name, value  # already a dict/model — let Pydantic handle it

    tasks = [
        _resolve_one(name, target_cls, nullable)
        for name, (target_cls, nullable) in foreign_fields.items()
    ]
    results = await asyncio.gather(*tasks)
    for name, value in results:
        payload[name] = value
    return payload

# ── QueryLike → SQL / Mongo / in-memory bridge helpers ───────────────────────

def _combine_query_expressions(
    expressions: Sequence[QueryExpression],
    *,
    op: Literal["and", "or"],
) -> QueryExpression | None:
    iterator = iter(expressions)
    try:
        combined = next(iterator)
    except StopIteration:
        return None
    for expression in iterator:
        combined = combined & expression if op == "and" else combined | expression
    return combined


def _normalize_mapping_query_identity_value(field: str, value: object) -> object:
    if field not in {"id", "_id"}:
        return value
    return _normalize_sql_identity_value(value)


def _field_mapping_to_query_expression(field: str, expected: object) -> QueryExpression | None:
    validated_field = _validate_selected_field_name(field)
    if not isinstance(expected, Mapping):
        return _FieldExpression(
            validated_field,
            "eq",
            _normalize_mapping_query_identity_value(validated_field, expected),
        )

    expressions: list[QueryExpression] = []
    for raw_op, raw_value in expected.items():
        op = str(raw_op or "").strip()
        normalized_value = _normalize_mapping_query_identity_value(validated_field, raw_value)
        if op == "$eq":
            expressions.append(_FieldExpression(validated_field, "eq", normalized_value))
            continue
        if op == "$ne":
            expressions.append(_FieldExpression(validated_field, "ne", normalized_value))
            continue
        if op == "$gt":
            expressions.append(_FieldExpression(validated_field, "gt", normalized_value))
            continue
        if op == "$gte":
            expressions.append(_FieldExpression(validated_field, "gte", normalized_value))
            continue
        if op == "$lt":
            expressions.append(_FieldExpression(validated_field, "lt", normalized_value))
            continue
        if op == "$lte":
            expressions.append(_FieldExpression(validated_field, "lte", normalized_value))
            continue
        if op == "$contains":
            expressions.append(_FieldExpression(validated_field, "contains", normalized_value))
            continue
        if op == "$wildcard":
            expressions.append(_FieldExpression(validated_field, "wildcard", normalized_value))
            continue
        if op == "$regex":
            expressions.append(_FieldExpression(validated_field, "regex", normalized_value))
            continue
        if op == "$in":
            if not isinstance(normalized_value, (list, tuple, set)):
                return None
            expressions.append(_FieldExpression(validated_field, "in", list(normalized_value)))
            continue
        return None
    return _combine_query_expressions(expressions, op="and")


def _mapping_query_to_expression(query: Mapping[str, object] | None) -> QueryExpression | None:
    if not query:
        return None

    expressions: list[QueryExpression] = []
    for raw_key, expected in query.items():
        key = str(raw_key or "").strip()
        if key in {"$and", "$or"}:
            if not isinstance(expected, Sequence) or isinstance(expected, (str, bytes, bytearray)):
                return None
            nested_expressions: list[QueryExpression] = []
            for item in expected:
                if not isinstance(item, Mapping):
                    return None
                nested_expression = _mapping_query_to_expression(item)
                if nested_expression is None:
                    return None
                nested_expressions.append(nested_expression)
            compound = _combine_query_expressions(
                nested_expressions,
                op="and" if key == "$and" else "or",
            )
            if compound is None:
                return None
            expressions.append(compound)
            continue

        field_expression = _field_mapping_to_query_expression(key, expected)
        if field_expression is None:
            return None
        expressions.append(field_expression)

    return _combine_query_expressions(expressions, op="and")


def _query_to_expression(query: "QueryLike") -> QueryExpression | None:
    if query is None:
        return None
    if isinstance(query, QueryExpression):
        return query
    return _mapping_query_to_expression(query)


def _normalize_mongo_filter_ids(filter_doc: Mapping[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in filter_doc.items():
        if key in {"$and", "$or"} and isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            normalized[key] = [
                _normalize_mongo_filter_ids(item) if isinstance(item, Mapping) else item
                for item in value
            ]
            continue
        if key == "_id":
            if isinstance(value, Mapping):
                normalized_ops: dict[str, object] = {}
                for op, operand in value.items():
                    if op == "$in" and isinstance(operand, (list, tuple, set)):
                        normalized_ops[op] = [_to_mongo_object_id(item) for item in operand]
                    else:
                        normalized_ops[op] = _to_mongo_object_id(operand)
                normalized[key] = normalized_ops
            else:
                normalized[key] = _to_mongo_object_id(value)    # type: ignore
            continue
        if isinstance(value, Mapping):
            normalized[key] = _normalize_mongo_filter_ids(value)
            continue
        normalized[key] = value
    return normalized

def _query_to_sql_conditions(
    query: "QueryLike",
    dialect: str,
    *,
    counter: "_ParamCounter | None" = None,
    native_fields: set[str] | None = None,
    field_name_map: dict[str, str] | None = None,
    fts_table: str | None = None,
    fts_columns: set[str] | None = None,
) -> "tuple[list[str], dict[str, object]] | None":
    """Convert a :class:`QueryLike` to ``(conditions, params)`` for a SQL WHERE clause.

    Returns ``None`` when the query cannot be expressed in SQL (fall back to
    Python-side filtering).  Returns ``([], {})`` for *None* queries.
    """
    if query is None:
        return [], {}
    expression = _query_to_expression(query)
    if expression is None:
        return None
    if counter is None:
        counter = _ParamCounter()
    return expression.to_sql_conditions(
        dialect, counter=counter, native_fields=native_fields,
        field_name_map=field_name_map, fts_table=fts_table, fts_columns=fts_columns,
    )


def _require_sql_query_conditions(
    query: "QueryLike",
    dialect: str,
    *,
    counter: "_ParamCounter | None" = None,
    native_fields: set[str] | None = None,
    field_name_map: dict[str, str] | None = None,
    operation: str,
    fts_table: str | None = None,
    fts_columns: set[str] | None = None,
) -> tuple[list[str], dict[str, object]]:
    result = _query_to_sql_conditions(
        query,
        dialect,
        counter=counter,
        native_fields=native_fields,
        field_name_map=field_name_map,
        fts_table=fts_table,
        fts_columns=fts_columns,
    )
    if result is None:
        raise ValueError(f"{dialect} {operation} requires a query that can be pushed down to SQL.")
    return result


def _match_query_or_expr(doc: Mapping[str, object], query: "QueryLike") -> bool:
    """Evaluate a :class:`QueryLike` against an in-memory document dict."""
    expression = _query_to_expression(query)
    if expression is None:
        return query is None
    return expression.matches(doc)


def _query_to_mongo_filter(query: "QueryLike", *, field_name_map: dict[str, str] | None = None) -> "dict[str, object] | None":
    """Convert a :class:`QueryLike` to a MongoDB filter dict.

    Returns ``None`` when the query cannot be expressed as a MongoDB filter
    (fall back to Python-side filtering).  Returns ``{}`` for *None* queries.
    """
    if query is None:
        return {}
    expression = _query_to_expression(query)
    if expression is None:
        return None
    try:
        return _normalize_mongo_filter_ids(expression.to_mongo_filter(field_name_map=field_name_map))
    except ValueError:
        return None


def _sqlite_regexp(pattern: str, value: object) -> bool:
    """Fallback SQLite user-defined REGEXP (used when sqlite-regex extension is unavailable)."""
    try:
        return bool(_re.search(pattern, str(value or ""), _re.IGNORECASE))
    except Exception:
        return False


def _fts_rowid(doc_id: str) -> int:
    """Deterministic positive 63-bit integer from *doc_id* for FTS5 rowid."""
    import hashlib
    return int.from_bytes(hashlib.md5(doc_id.encode()).digest()[:8], 'big') & 0x7FFFFFFFFFFFFFFF


def _sql_contains_clause(expr: str, param: str, value: object, *, dialect: str) -> tuple[str, object]:
    if dialect == "sqlite":
        return f"instr(COALESCE({expr}, ''), :{param}) > 0", str(value)
    if dialect == "postgresql":
        return f"COALESCE({expr}, '') ILIKE :{param}", f"%{value}%"
    return f"COALESCE({expr}, '') LIKE :{param}", f"%{value}%"


def _sql_regex_clause(expr: str, param: str, value: object, *, dialect: str) -> tuple[str, object]:
    if dialect == "sqlite":
        return f"regexp(:{param}, COALESCE({expr}, ''))", str(value)
    if dialect == "postgresql":
        return f"COALESCE({expr}, '') ~* :{param}", str(value)
    return f"COALESCE({expr}, '') REGEXP :{param}", str(value)



def _to_mongo_object_id(value: str | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))  # type: ignore[call-arg]
    except Exception:
        return value  # type: ignore[return-value]


def _restore_mongo_doc(doc: dict[str, object]) -> dict[str, object]:
    """Convert a flat MongoDB document back to a plain ORM payload dict."""
    payload: dict[str, object] = {}
    for k, v in doc.items():
        if k == "_id":
            payload["id"] = str(v)
        elif k == "_sys":
            continue
        else:
            payload[k] = v
    return payload


def _coerce_model_payload(payload: dict[str, object], model_cls: type[ORMModel]) -> dict[str, object]:
    restored = _restore_payload_from_storage(payload)
    if "id" in restored:
        try:
            restored["id"] = ObjectId(str(restored["id"]))  # type: ignore[call-arg]
        except Exception:
            pass
    return restored


_SELECTED_FIELD_RE = _re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")


def _validate_selected_field_name(field: str) -> str:
    normalized = str(field or "").strip()
    if normalized in {"id", "_id"}:
        return normalized
    if not normalized or not _SELECTED_FIELD_RE.fullmatch(normalized):
        raise ValueError(f"Invalid selected field path: {field!r}")
    return normalized


def _normalize_selected_fields(fields: Sequence[str]) -> list[str]:
    """Normalize projection paths and auto-include ``id`` in the result shape.

    ``fields`` must still request at least one non-empty path explicitly; the
    automatic ``id`` insertion only affects the returned projection, not the
    caller contract.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_field in fields:
        field = _validate_selected_field_name(str(raw_field))
        if field in seen:
            continue
        normalized.append(field)
        seen.add(field)
    if not normalized:
        raise ValueError("`fields` must contain at least one selected field.")
    if "id" not in seen:
        normalized.insert(0, "id")
    return normalized


def _merge_selected_nodes(target: object, source: object) -> object:
    if isinstance(target, dict) and isinstance(source, dict):
        for key, source_value in source.items():
            if key not in target:
                target[key] = source_value
                continue
            target[key] = _merge_selected_nodes(target[key], source_value)
        return target

    if isinstance(target, list) and isinstance(source, list):
        if len(target) < len(source):
            target.extend([None] * (len(source) - len(target)))
        for index, source_value in enumerate(source):
            if source_value is None:
                continue
            if target[index] is None:
                target[index] = source_value
                continue
            target[index] = _merge_selected_nodes(target[index], source_value)
        return target

    return source


def _build_selected_structure(parts: Sequence[str], value: object) -> object:
    """Build nested dict/list containers for one selected dotted path.

    Examples:
        - ``("a", "b", "c")`` -> ``{"a": {"b": {"c": value}}}``
        - ``("a", "0", "b")`` -> ``{"a": [{"b": value}]}``
        - ``("a", "1", "b")`` -> ``{"a": [None, {"b": value}]}``
    """
    current: object = value
    for index in range(len(parts) - 1, -1, -1):
        part = parts[index]
        if part.isdigit() and index > 0:
            list_value: list[object | None] = [None] * (int(part) + 1)
            list_value[int(part)] = current
            current = list_value
            continue
        current = {part: current}
    return current


def _assign_selected_field(result: dict[str, object], field: str, value: object) -> None:
    """Assign one projected field into the nested SelectedSearch result shape."""
    validated = _validate_selected_field_name(field)
    if validated in {"id", "_id"}:
        result[validated] = str(value) if value is not None else None
        return

    nested_value = _build_selected_structure(validated.split("."), value)
    _merge_selected_nodes(result, nested_value)


def _project_selected_pairs(items: Sequence[tuple[str, object]]) -> dict[str, object]:
    """Convert ``[(field_path, value), ...]`` into the SelectedSearch output shape."""
    result: dict[str, object] = {}
    for field, value in items:
        _assign_selected_field(result, field, value)
    return result


def _project_selected_payload(payload: Mapping[str, object], fields: Sequence[str]) -> dict[str, object]:
    return _project_selected_pairs([
        (
            field,
            payload.get("id", payload.get("_id")) if field in {"id", "_id"} else _deep_get(payload, field),
        )
        for field in fields
    ])


def _sql_json_path(field: str) -> str:
    validated = _validate_selected_field_name(field)
    path = "$"
    for part in validated.split("."):
        if part.isdigit():
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def _sql_json_field_expr(
    dialect: str,
    field: str,
    *,
    native_fields: Mapping[str, ORMFieldSpec] | None = None,
    field_name_map: dict[str, str] | None = None,
) -> str | None:
    """Return a SQL expression for *field*.

    Every top-level field is a column; dotted paths use ``json_extract``
    on the first-segment column.
    """
    validated = _validate_selected_field_name(field)
    if validated in {"id", "_id"}:
        return _q("id", dialect)
    db_field = _translate_field_path(validated, field_name_map) if field_name_map else validated

    # ── top-level field → direct column reference ──
    if "." not in validated:
        if native_fields and validated in native_fields:
            return _q(native_fields[validated].column_name, dialect)
        return _q(db_field, dialect)

    # ── dotted path → json_extract on the first-segment column ──
    parts = db_field.split(".")
    col = _q(parts[0], dialect)
    rest = parts[1:]
    path = "$"
    for p in rest:
        path += f"[{p}]" if p.isdigit() else f".{p}"
    if dialect == "sqlite":
        return f"json_extract({col}, '{path}')"
    if dialect == "postgresql":
        expr = f"CAST({col} AS JSONB)"
        for p in rest[:-1]:
            expr = f"{expr}->{p}" if p.isdigit() else f"{expr}->'{p}'"
        last = rest[-1]
        return f"{expr}->>{last}" if last.isdigit() else f"{expr}->>'{last}'"
    if dialect in {"mysql", "mariadb"}:
        return f"JSON_UNQUOTE(JSON_EXTRACT({col}, '{path}'))"
    return None

def _normalize_sql_identity_value(value: object) -> str | list[str | None] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        return [str(item) if item is not None else None for item in value]
    return str(value)

def _build_sql_selected_query_parts(
    query: Mapping[str, object] | None,
    *,
    dialect: str,
    native_fields: Mapping[str, ORMFieldSpec] | None = None,
    field_name_map: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, object]] | None:
    if not query:
        return [], {}
    native_field_names = set(native_fields) if native_fields else None
    return _query_to_sql_conditions(query, dialect, native_fields=native_field_names, field_name_map=field_name_map)

def _build_sql_selected_columns(
    fields: Sequence[str],
    *,
    dialect: str,
    native_fields: Mapping[str, ORMFieldSpec] | None = None,
    field_name_map: dict[str, str] | None = None,
    table_alias: str | None = None,
) -> tuple[list[str], list[tuple[str, str]]] | None:
    prefix = f"{table_alias}." if table_alias else ""
    columns = [f'{prefix}{_q("id", dialect)} AS __row_id']
    aliases: list[tuple[str, str]] = []
    for index, field in enumerate(_normalize_selected_fields(fields)):
        expr = _sql_json_field_expr(dialect, field, native_fields=native_fields, field_name_map=field_name_map)
        if expr is None:
            return None
        # id references need table qualifier in JOIN contexts
        if table_alias and expr == _q("id", dialect):
            expr = f"{prefix}{expr}"
        alias = f"__sel_{index}"
        columns.append(f"{expr} AS {alias}")
        aliases.append((field, alias))
    return columns, aliases

def _build_mongo_selected_query(query: Mapping[str, object] | None, *, field_name_map: dict[str, str] | None = None) -> dict[str, object] | None:
    return _query_to_mongo_filter(query, field_name_map=field_name_map)

def _build_mongo_selected_projection(fields: Sequence[str], *, field_name_map: dict[str, str] | None = None) -> dict[str, int]:
    projection: dict[str, int] = {"_id": 1}
    for field in _normalize_selected_fields(fields):
        if field in {"id", "_id"}:
            projection["_id"] = 1
            continue
        db_field = _translate_field_path(field, field_name_map) if field_name_map else field
        projection[db_field] = 1
    return projection

def _safe_model_schema(model_cls: type[ORMModel]) -> dict[str, object]:
    try:
        return model_cls.model_json_schema()
    except Exception:
        return {
            "title": model_cls.__name__,
            "type": "object",
        }

__all__ = [
    'ORMClientInitParams', 
    'SQLiteORMClientInitParams', 
    'SQLORMClientInitParams', 
    'PostgreSQLORMClientInitParams', 
    'MongoORMClientInitParams', 
    'RedisORMClientInitParams', 
    'ORM_ClientBase'
]
