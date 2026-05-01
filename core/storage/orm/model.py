import asyncio
import logging
import sqlite3
from pathlib import Path
from urllib.parse import unquote
from typing import (
    Any, AsyncGenerator, ClassVar, Literal, Mapping, Sequence, TypeVar, cast,
    overload, TYPE_CHECKING
)
from pydantic import (
    BaseModel, ConfigDict, Field, AliasChoices, 
    model_serializer, model_validator
)
from typing_extensions import Self, TypeAliasType

from ...utils.concurrent_utils import run_any_func
from ...utils.type_utils import is_empty_method
from ...utils.text_utils.formatting import to_snake_case
from .query import ORMFieldProxy, QueryExpression, _ORMMetaModel
from .query_dict import (
    QueryDict,
    QueryAndDict,
    QueryOrDict,
    QueryLeafDict,
    QueryOpDict,
    QueryFieldValue,
    QueryScalar,
    QueryValue,
)
from .field_metadata import (
    ORMFieldInfo,
    _is_storage_excluded,
    build_field_name_mapping,
    remap_payload_from_db,
)
from ..base import (
    ObjectId,
    _get_foreign_annotation_info,
    _now_ts,
)
if TYPE_CHECKING:
    from .client_base import ORM_ClientBase


ModelT = TypeVar("ModelT", bound="ORMModel")
CollectionLike = TypeAliasType("CollectionLike", str | type[ModelT], type_params=(ModelT,))

# Query parameter type alias — accepts a programmatic ``QueryExpression`` (built
# via ``MyModel.field == ...`` etc.), a wire-shaped :class:`QueryDict`, a
# normalized ``Mapping[str, object]`` used by internal storage helpers, or
# ``None`` for "match everything". The :class:`QueryDict` branch is what
# request bodies bind to, so OpenAPI gets a precise schema instead of a
# free-form ``additionalProperties: true`` map.
type QueryLike = QueryExpression | QueryDict | Mapping[str, object] | None
type DeleteQueryLike = QueryExpression | QueryDict | Mapping[str, object]

_orm_model_logger = logging.getLogger(__name__)

class ORMModel(BaseModel, metaclass=_ORMMetaModel):  
    
    model_config = ConfigDict(
        populate_by_name=True, protected_namespaces=(), arbitrary_types_allowed=True, validate_assignment=True, use_attribute_docstrings=True
    )
    CollectionName: ClassVar[str]
    Client: ClassVar["ORM_ClientBase|None"] = None
    _ClientExplicit: ClassVar[bool] = False

    # When True, the backend MUST NOT modify the physical collection schema to
    # add `_expire_at` / `_accessed_at` / `_sys` fields for this model. Backends
    # that need those metadata for expire / max_size will route them through
    # the KV-backed sidecar (`core.storage.expire_sidecar`).
    # Use this for collections whose schema is owned externally (e.g. a Milvus
    # collection created via raw `pymilvus.MilvusClient.create_collection`).
    __NoExpireField__: ClassVar[bool] = False
    
    id: ObjectId = Field(default_factory=ObjectId, validation_alias=AliasChoices('id', '_id'))

    # ── dirty-save tracking (private, never serialized) ──────────────
    # `__dirty__`: names of model fields mutated since the last successful
    # save / hydrate; `id` is excluded.
    # `__persisted__`: True once this instance is known to have a corresponding
    # row in the backend (after a successful save, or after being hydrated by
    # the ORM client). Combined with an empty `__dirty__` set this lets
    # `save(force=False)` skip the network round-trip entirely.
    if TYPE_CHECKING:
        __dirty__: set[str]
        __persisted__: bool

    @overload
    def __init_subclass__(
        cls,
        *,
        collection_name: str,
        client: "ORM_ClientBase|None" = ...,
        **kwargs,
    ) -> None: ...

    @overload
    def __init_subclass__(
        cls,
        *,
        full_collection_name: str,
        client: "ORM_ClientBase|None" = ...,
        **kwargs,
    ) -> None: ...

    @overload
    def __init_subclass__(
        cls,
        *,
        client: "ORM_ClientBase|None" = ...,
        **kwargs,
    ) -> None: ...

    def __init_subclass__(  # type: ignore
        cls,
        collection_name: str | None = None,
        full_collection_name: str | None = None,
        client: "ORM_ClientBase|None" = None,
        **kwargs,
    ) -> None:
        # ── alias support ────────────────────────────────────────────
        if collection_name is None:
            collection_name = kwargs.pop("collection", None)    # type: ignore
        if full_collection_name is None:
            full_collection_name = kwargs.pop("full_collection", None)  # type: ignore

        super().__init_subclass__(**kwargs) # type: ignore

        # ── mutual exclusivity ───────────────────────────────────────
        if collection_name is not None and full_collection_name is not None:
            raise TypeError(
                f"{cls.__name__}: cannot specify both `collection_name` "
                "and `full_collection_name`."
            )

        # ── client ───────────────────────────────────────────────────
        if client is not None:
            from .client_base import ORM_ClientBase
            if not isinstance(client, ORM_ClientBase):
                raise TypeError(f"{cls.__name__} `client` must be an instance of ORMClientBase.")
        cls.Client = client
        cls._ClientExplicit = client is not None

        # ── collection name ──────────────────────────────────────────
        if full_collection_name is not None:
            cls.CollectionName = full_collection_name
        else:
            curr_collection_name = getattr(cls, "CollectionName", None)
            pass_in_collection_name = collection_name or to_snake_case(cls.__name__)
            if curr_collection_name:
                cn = f'{curr_collection_name}_{pass_in_collection_name}'
            else:
                cn = pass_in_collection_name
            cls.CollectionName = cn

    @classmethod
    def _iter_model_subclasses(cls, *, include_self: bool = False):
        seen: set[type[object]] = set()
        pending: list[type[object]] = [cls] if include_self else list(cls.__subclasses__())
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            yield cast(type["ORMModel"], current)
            pending.extend(current.__subclasses__())

    @classmethod
    def ResetClientBindings(cls, *, include_explicit: bool = False) -> None:
        for model_cls in cls._iter_model_subclasses(include_self=True):
            if include_explicit or not getattr(model_cls, "_ClientExplicit", False):
                model_cls.Client = None

    @classmethod
    def GetClient(cls) -> "ORM_ClientBase":
        from .client_base import ORM_ClientBase
        if cls.Client is not None:
            return cls.Client
        resolved = None
        try:
            from ..config import StorageConfig
            resolved = StorageConfig.Global().orm.get_client(
                getattr(cls, 'CollectionName', 'default'),
            )
        except Exception:
            resolved = None
        if not isinstance(resolved, ORM_ClientBase):
            resolved = cast(ORM_ClientBase, ORM_ClientBase.Default())
        cls.Client = resolved
        return resolved

    @classmethod
    def get_index_fields(cls) -> dict[str, ORMFieldInfo]:
        """Return fields decorated with ``index=True`` via :func:`ORMField`.

        Returns:
            Mapping of field name → :class:`ORMFieldInfo` for every field whose
            ``index`` flag is ``True``.
        """
        return {
            name: info
            for name, info in cls.model_fields.items()
            if isinstance(info, ORMFieldInfo) and info.index
            and not _is_storage_excluded(info)
        }

    @classmethod
    def _get_client(cls, client: "ORM_ClientBase|None" = None) -> "ORM_ClientBase":
        if client is not None:
            return client
        return cls.GetClient()

    # ── dirty tracking helpers ────────────────────────────────────────
    def model_post_init(self, __context: object) -> None:
        _ = __context
        # Fields explicitly provided to the constructor are considered dirty
        # until the instance is persisted. `id` is auto-generated by default
        # and is not user-meaningful for save de-duplication.
        explicit = set(self.__pydantic_fields_set__)
        explicit.discard('id')
        object.__setattr__(self, '__dirty__', explicit)
        object.__setattr__(self, '__persisted__', False)

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name in type(self).model_fields and name != 'id':
            dirty = getattr(self, '__dirty__', None)
            if isinstance(dirty, set):
                dirty.add(name)

    def _mark_persisted_clean(self) -> None:
        """Mark this instance as persisted with no pending dirty fields.

        Called after a successful ``save()`` / ``BatchSave()`` / refresh, and
        by the ORM client when hydrating an instance from the backend.
        """
        dirty = getattr(self, '__dirty__', None)
        if isinstance(dirty, set):
            dirty.clear()
        object.__setattr__(self, '__persisted__', True)

    def _has_post_delete_hook(self) -> bool:
        has = getattr(self, '__has_post_delete__', None)
        if has is not None:
            return has
        hook = getattr(type(self), 'post_delete', None)
        if (hook is None) or (hook is ORMModel.post_delete):
            has = False
        else:
            has = not is_empty_method(hook)
        object.__setattr__(self, '__has_post_delete__', has)
        return has

    async def _run_post_delete_guarded(self) -> None:
        try:
            await self.post_delete()
        except Exception:
            _orm_model_logger.exception(
                "ORMModel.post_delete failed for %s(id=%s).",
                type(self).__name__,
                getattr(self, 'id', None),
            )

    def _schedule_post_delete(self) -> None:
        if not self._has_post_delete_hook():
            return
        asyncio.create_task(self._run_post_delete_guarded())

    async def post_delete(self):
        '''你可以定义这个方法来在实例被删除后执行一些清理工作。注意, post_delete只会在通过ORMModel.Delete()/delete()方法触发'''

    @property
    def IsDirty(self) -> bool:
        """Whether this instance has unsaved field mutations."""
        dirty = getattr(self, '__dirty__', None)
        return bool(dirty)

    @property
    def DirtyFields(self) -> frozenset[str]:
        """Names of fields mutated since the last successful save / hydrate."""
        dirty = getattr(self, '__dirty__', None)
        if not isinstance(dirty, set):
            return frozenset()
        return frozenset(dirty)

    async def save(
        self,
        *,
        client: "ORM_ClientBase|None"= None,
        expire: float | int | None = None,
        create_collection: bool = True,
        force: bool = False,
    ) -> str:
        # Fast path: a previously persisted instance with no dirty fields can
        # skip the round-trip entirely. Pass `force=True` to override.
        if not force and self.__persisted__ and not self.__dirty__:
            return str(self.id)
        object_id = await self.__class__._get_client(client).set(
            self,
            expire=expire,
            create_collection=create_collection,
        )
        try:
            self.id = ObjectId(str(object_id))  # type: ignore[call-arg]
        except Exception:
            pass
        self._mark_persisted_clean()
        return object_id

    @classmethod
    async def BatchSave(
        cls,
        values: Sequence["ORMModel | dict[str, object]"],
        *,
        client: "ORM_ClientBase|None" = None,
        expire: float | int | None = None,
        create_collection: bool = True,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []
        ids = await cls._get_client(client).set_many(
            batch,
            collection=cls,
            expire=expire,
            create_collection=create_collection,
        )
        # Best-effort: mark every ORMModel input as persisted+clean. Plain
        # dicts in `batch` are not tracked.
        for item, new_id in zip(batch, ids):
            if isinstance(item, ORMModel):
                try:
                    item.id = ObjectId(str(new_id))  # type: ignore[call-arg]
                except Exception:
                    pass
                item._mark_persisted_clean()
        return ids

    async def update(
        self,
        *fields: str | ORMFieldProxy,
        client: "ORM_ClientBase|None" = None,
    ) -> None:
        """Refresh this instance from the database.

        Parameters
        ----------
        *fields:
            Field names (or :class:`ORMFieldProxy` references such as
            ``MyModel.score``) whose values should be fetched from the DB and
            applied to this instance.  When omitted **all** mutable model
            fields are refreshed.
        client:
            Optional explicit ORM client override.
        """
        orm_client = self.__class__._get_client(client)

        if fields:
            # Resolve field names from ORMFieldProxy or plain strings
            names = [
                f.field_name if isinstance(f, ORMFieldProxy) else str(f)
                for f in fields
            ]
            for name in names:
                if name not in self.__class__.model_fields:
                    raise ValueError(f"Unknown field: {name!r}")

            # Use projection to fetch only the requested fields
            projected = await orm_client.selected_search_by_id(
                self.__class__, self.id, fields=names,
            )
            if projected is None:
                raise LookupError(
                    f"{self.__class__.__name__} with id={self.id!s} not found in DB"
                )
            for name in names:
                if name in projected:
                    setattr(self, name, projected[name])
        else:
            loaded = await orm_client.get(self.__class__, self.id, as_model=True)
            if loaded is None:
                raise LookupError(
                    f"{self.__class__.__name__} with id={self.id!s} not found in DB"
                )
            for name, info in self.__class__.model_fields.items():
                if name == "id":
                    continue
                if _is_storage_excluded(info):
                    continue
                setattr(self, name, getattr(loaded, name))
        # Refresh leaves the in-memory copy in sync with the backend.
        self._mark_persisted_clean()

    @overload
    @classmethod
    def Search(
        cls: type[ModelT],
        query: "QueryLike | Any" = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[True] = True,
        client: "ORM_ClientBase|None" = None,
    ) -> AsyncGenerator[ModelT, None]: ...

    @overload
    @classmethod
    def Search(
        cls: type[ModelT],
        query: "QueryLike" = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[False],
        client: "ORM_ClientBase|None" = None,
    ) -> AsyncGenerator[dict[str, object], None]: ...

    @classmethod
    def Search(
        cls: type[ModelT],
        query: "QueryLike" = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
        client: "ORM_ClientBase|None" = None,
    ) -> AsyncGenerator[ModelT | dict[str, object], None]:
        async def _iterate() -> AsyncGenerator[ModelT | dict[str, object], None]:
            orm_client = cls._get_client(client)
            async for item in orm_client.search(cls, query, limit=limit, offset=offset, as_model=as_model):
                yield item

        return _iterate()

    @overload
    @classmethod
    async def SearchOne(
        cls: type[ModelT],
        query: "QueryLike" = None,
        *,
        as_model: Literal[True] = True,
        client: "ORM_ClientBase|None" = None,
    ) -> ModelT | None: ...

    @overload
    @classmethod
    async def SearchOne(
        cls: type[ModelT],
        query: "QueryLike" = None,
        *,
        as_model: Literal[False],
        client: "ORM_ClientBase|None" = None,
    ) -> dict[str, object] | None: ...

    @classmethod
    async def SearchOne(
        cls: type[ModelT],
        query: "QueryLike | Any" = None,
        *,
        as_model: bool = True,
        client: "ORM_ClientBase|None" = None,
    ) -> ModelT | dict[str, object] | None:
        return await cls._get_client(client).search_one(cls, query, as_model=as_model)

    @classmethod
    async def SelectedSearch(
        cls,
        query: "QueryLike | Any" = None,
        *,
        fields: Sequence[str],
        limit: int | None = None,
        offset: int = 0,
        client: "ORM_ClientBase|None" = None,
    ) -> AsyncGenerator[dict[str, object], None]:
        """Yield selected fields as a projected ``dict``.

        Notes:
            - ``id`` is always included in the returned payload even when it is
              omitted from ``fields``.
            - Dotted paths build nested structures instead of flat keys.
            - Numeric path chunks are treated as list indexes, so
              ``a.0.b`` becomes ``{"id": ..., "a": [{"b": value}]}``.
        """
        orm_client = cls._get_client(client)
        async for item in orm_client.selected_search(cls, fields=fields, query=query, limit=limit, offset=offset):
            yield item

    @classmethod
    async def SelectedSearchOne(
        cls,
        query: "QueryLike | Any" = None,
        *,
        fields: Sequence[str],
        client: "ORM_ClientBase|None" = None,
    ) -> dict[str, object] | None:
        """Return the first SelectedSearch projection, including auto-added ``id``."""
        return await cls._get_client(client).selected_search_one(cls, fields=fields, query=query)

    async def delete(self, *, client: "ORM_ClientBase|None" = None) -> bool:
        return await self.__class__.Delete(self, client=client)

    @overload
    @classmethod
    async def Delete(cls: type[Self], target: Self, *, client: "ORM_ClientBase|None" = None) -> bool: ...

    @overload
    @classmethod
    async def Delete(cls, target: str | ObjectId, *, client: "ORM_ClientBase|None" = None) -> bool: ...

    @overload
    @classmethod
    async def Delete(cls, target: "DeleteQueryLike", *, client: "ORM_ClientBase|None" = None) -> bool: ...

    @classmethod
    async def Delete(
        cls,
        target: Self | str | ObjectId | "DeleteQueryLike",
        *,
        client: "ORM_ClientBase|None" = None,
    ) -> bool:
        orm_client = cls._get_client(client)

        if isinstance(target, ORMModel):
            if not isinstance(target, cls):
                raise TypeError(
                    f"{cls.__name__}.Delete() expected an instance of {cls.__name__}, got {type(target).__name__}."
                )
            deleted = await orm_client.delete(cls, target.id)
            if deleted:
                target._schedule_post_delete()
            return deleted

        if isinstance(target, (QueryExpression, dict)):
            object_ids: list[str] = []
            async for item in cls.SelectedSearch(target, fields=("id",), client=orm_client):
                object_id = str(item.get('id') or item.get('_id') or '').strip()
                if object_id:
                    object_ids.append(object_id)
            if not object_ids:
                return False
            deleted_by_id = await orm_client.delete_many(cls, list(dict.fromkeys(object_ids)))
            return any(deleted_by_id.values())

        if target is None:
            raise TypeError(f"{cls.__name__}.Delete() does not accept None.")

        return await orm_client.delete(cls, cast(str | ObjectId, target))

    @classmethod
    async def SelectedSearchOneById(
        cls,
        object_id: str | ObjectId,
        *,
        fields: Sequence[str],
        client: "ORM_ClientBase|None" = None,
    ) -> dict[str, object] | None:
        """Return a SelectedSearch projection for one object by id.

        The result always contains ``id`` even if ``fields`` only requests
        nested paths such as ``a.0.b``.
        """
        return await cls._get_client(client).selected_search_by_id(cls, object_id, fields=fields)

    @overload
    @classmethod
    async def SearchOneById(
        cls: type[ModelT],
        object_id: str | ObjectId,
        *,
        as_model: Literal[True] = True,
        client: "ORM_ClientBase|None" = None,
    ) -> ModelT | None: ...

    @overload
    @classmethod
    async def SearchOneById(
        cls: type[ModelT],
        object_id: str | ObjectId,
        *,
        as_model: Literal[False],
        client: "ORM_ClientBase|None" = None,
    ) -> dict[str, object] | None: ...

    @classmethod
    async def SearchOneById(
        cls: type[ModelT],
        object_id: str | ObjectId,
        *,
        as_model: bool = True,
        client: "ORM_ClientBase|None" = None,
    ) -> ModelT | dict[str, object] | None:
        return await cls._get_client(client).search_by_id(cls, object_id, as_model=as_model)

    @classmethod
    async def SetExpire(
        cls,
        object_id: str | ObjectId,
        expire: float | int | None,
        *,
        client: "ORM_ClientBase|None" = None,
    ) -> bool:
        return await cls._get_client(client).set_expire(cls, object_id, expire)

    @classmethod
    async def GetExpire(
        cls,
        object_id: str | ObjectId,
        *,
        client: "ORM_ClientBase|None" = None,
    ) -> float | None:
        return await cls._get_client(client).get_expire(cls, object_id)

    # ── foreign model helpers ─────────────────────────────────────────────

    @classmethod
    def _get_foreign_fields(cls) -> dict[str, tuple[type["ORMModel"], bool]]:
        """Return ``{field_name: (target_model_class, is_nullable)}`` for every
        field declared with ``foreign_model=True`` via :func:`ORMField`.
        """
        result: dict[str, tuple[type["ORMModel"], bool]] = {}
        for name, info in cls.model_fields.items():
            if not isinstance(info, ORMFieldInfo) or not info.foreign_model:
                continue
            if _is_storage_excluded(info):
                continue
            target_cls, nullable = _get_foreign_annotation_info(info.annotation)
            if target_cls is not None:
                result[name] = (target_cls, nullable)
        return result

    def _serialize_for_storage(self) -> dict[str, object]:
        """Like :meth:`model_dump` but foreign-model fields are replaced with
        their ``id`` string so the backend stores only a reference.
        """
        data: dict[str, object] = self.model_dump(mode="json")
        for name in self.__class__._get_foreign_fields():
            value = getattr(self, name, None)
            if value is None:
                data[name] = None
            elif isinstance(value, ORMModel):
                data[name] = str(value.id)
            # else: already a string id — leave as-is
        return data

    @staticmethod
    def _foreign_model_storage_id(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, ORMModel):
            return str(value.id)
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            keys = {str(key) for key in value.keys()}
            if keys and keys.issubset({"id", "_id"}):
                raw_id = value.get("id", value.get("_id"))
                if raw_id is not None:
                    return str(raw_id)
        return None

    @staticmethod
    def _sqlite_db_path_from_client_url(url: str) -> Path | None:
        raw = str(url or "")
        prefixes = (
            "sqlite+aiosqlite:///",
            "sqlite:///",
            "sqlite+aiosqlite://",
            "sqlite://",
        )
        db_path: str | None = None
        for prefix in prefixes:
            if raw.startswith(prefix):
                db_path = raw[len(prefix):]
                break
        if not db_path:
            return None
        decoded = unquote(db_path)
        if decoded.startswith("/") and len(decoded) >= 3 and decoded[2] == ":":
            decoded = decoded[1:]
        return Path(decoded)

    @classmethod
    def _resolve_foreign_model_from_sqlite(
        cls,
        target_cls: type["ORMModel"],
        *,
        db_path: str | Path | None,
        table_name: str,
        object_id: str,
    ) -> "ORMModel | None":
        if db_path is None:
            return None
        from .client_base import _deserialize_row
        from .field_schema import extract_field_specs

        sys_table = f"_orm_{target_cls.CollectionName}_sys"
        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    f'SELECT d.*, s.expire_at FROM {table_name} d'
                    f' LEFT JOIN {sys_table} s ON d."id" = s."id"'
                    f' WHERE d."id" = ?',
                    (object_id,),
                ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        expire_at = row["expire_at"]
        if expire_at is not None and float(expire_at) <= _now_ts():
            return None
        specs = extract_field_specs(target_cls)
        payload = _deserialize_row(dict(row), specs)
        mapping = build_field_name_mapping(target_cls)
        if mapping:
            payload = remap_payload_from_db(payload, mapping)
        instance = target_cls.model_validate(payload)
        instance._mark_persisted_clean()
        return instance

    @classmethod
    def _resolve_foreign_model_instance(
        cls,
        target_cls: type["ORMModel"],
        object_id: str,
    ) -> "ORMModel | None":
        from .sqlite_client import SQLiteORMClient
        from .sql_client import SQL_ORM_Client

        client = target_cls._get_client()
        if isinstance(client, SQLiteORMClient):
            return cls._resolve_foreign_model_from_sqlite(
                target_cls,
                db_path=getattr(client, "_db_path", None),
                table_name=client._table_sql(target_cls.CollectionName),
                object_id=object_id,
            )
        if isinstance(client, SQL_ORM_Client):
            sqlite_path = cls._sqlite_db_path_from_client_url(getattr(client, "_url", ""))
            if sqlite_path is not None:
                return cls._resolve_foreign_model_from_sqlite(
                    target_cls,
                    db_path=sqlite_path,
                    table_name=client._table_sql(target_cls.CollectionName),
                    object_id=object_id,
                )
        return run_any_func(target_cls.SearchOneById, object_id)

    @model_serializer(mode="wrap")
    def _serialize_orm_model(self, handler, info):
        data = handler(self)
        if not isinstance(data, dict):
            return data
        for name in self.__class__._get_foreign_fields():
            field_info = self.__class__.model_fields.get(name)
            key = name
            if getattr(info, "by_alias", False) and field_info is not None:
                key = cast(str, getattr(field_info, "serialization_alias", None) or getattr(field_info, "alias", None) or name)
            data[key] = self._foreign_model_storage_id(getattr(self, name, None))
        return data

    @model_validator(mode="before")
    @classmethod
    def _resolve_foreign_id_strings(cls, data: object) -> object:
        """Safety-net validator: if a foreign-model field received a plain
        string / :class:`ObjectId` instead of a model instance, attempt to
        fetch the real model synchronously via :func:`run_any_func`.

        When multiple foreign fields need resolution, they are fetched in
        parallel via ``asyncio.gather`` to reduce total latency.
        """
        if not isinstance(data, dict):
            return data
        foreign_fields = cls._get_foreign_fields()
        if not foreign_fields:
            return data

        # Collect fields needing resolution
        to_resolve: list[tuple[str, type["ORMModel"], bool, str]] = []  # (name, target_cls, nullable, foreign_id)
        for name, (target_cls, nullable) in foreign_fields.items():
            value = data.get(name)
            if value is None or isinstance(value, ORMModel):
                continue
            foreign_id = cls._foreign_model_storage_id(value)
            if foreign_id is not None:
                to_resolve.append((name, target_cls, nullable, foreign_id))

        if not to_resolve:
            return data

        # Single field → direct sync resolution (avoid asyncio.gather overhead)
        if len(to_resolve) == 1:
            name, target_cls, nullable, foreign_id = to_resolve[0]
            try:
                result = cls._resolve_foreign_model_instance(target_cls, foreign_id)
                if result is not None:
                    data[name] = result
                elif nullable:
                    data[name] = None
                else:
                    raise ValueError(
                        f"Foreign model {target_cls.__name__} with "
                        f"id={foreign_id!r} not found for required field "
                        f"`{name}` in {cls.__name__}"
                    )
            except ValueError:
                raise
            except Exception as exc:
                if nullable:
                    data[name] = None
                else:
                    raise ValueError(
                        f"Failed to resolve foreign model for field "
                        f"`{name}` in {cls.__name__}: {exc}"
                    ) from exc
            return data

        # Multiple fields → use the same sqlite-aware helper path in worker
        # threads so SQLite-backed clients do not fall back to async re-entry.
        async def _gather_resolve():
            return await asyncio.gather(
                *(
                    asyncio.to_thread(cls._resolve_foreign_model_instance, tc, fid)
                    for _, tc, _, fid in to_resolve
                ),
                return_exceptions=True,
            )

        results = run_any_func(_gather_resolve)
        for (name, target_cls, nullable, foreign_id), result in zip(to_resolve, results):
            if isinstance(result, Exception):
                if nullable:
                    data[name] = None
                else:
                    raise ValueError(
                        f"Failed to resolve foreign model for field "
                        f"`{name}` in {cls.__name__}: {result}"
                    ) from result
            elif result is not None:
                data[name] = result
            elif nullable:
                data[name] = None
            else:
                raise ValueError(
                    f"Foreign model {target_cls.__name__} with "
                    f"id={foreign_id!r} not found for required field "
                    f"`{name}` in {cls.__name__}"
                )
        return data


class RedisModel(ORMModel):

    @classmethod
    def GetClient(cls) -> "ORM_ClientBase":
        from .client_base import ORM_ClientBase
        if cls.Client is not None:
            return cls.Client
        try:
            from ..config import StorageConfig
            resolved = StorageConfig.Global().orm.get_client("redis")
            if isinstance(resolved, ORM_ClientBase):
                cls.Client = resolved
                return resolved
        except Exception:
            pass
        return super().GetClient()


__all__ = [
    'ModelT', 'CollectionLike', 'QueryLike', 'ORMModel', 'RedisModel',
    'QueryDict', 'QueryAndDict', 'QueryOrDict', 'QueryLeafDict',
    'QueryOpDict', 'QueryFieldValue', 'QueryScalar', 'QueryValue',
]
