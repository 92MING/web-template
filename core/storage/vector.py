import os
import time
import hashlib
import logging
import sqlite3
import threading
import inspect
import importlib
import numpy as np
import functools
import asyncio
import types as _types_mod
from contextlib import nullcontext

from abc import ABC, abstractmethod
from pathlib import Path
from collections.abc import AsyncGenerator, Iterable, Sequence
from typing import Any, ClassVar, Literal, Mapping, Protocol, Self, TYPE_CHECKING, TypeVar, TypedDict, cast, overload, Callable, Awaitable
from pydantic_core import PydanticUndefined
from typing_extensions import Unpack

if TYPE_CHECKING:
    from ..ai.services.embedding import EmbeddingService as _EmbeddingService
    from motor.motor_asyncio import (
        AsyncIOMotorClient as _AsyncMotorClient,
        AsyncIOMotorCollection as _AsyncMotorCollection,
        AsyncIOMotorDatabase as _AsyncMotorDB,
    )
    from pymilvus import (
        AsyncMilvusClient as _AsyncMilvusClient,
        Collection as _MilvusCollection,
        CollectionSchema as _MilvusCollectionSchema,
        DataType as _MilvusDataType,
        FieldSchema as _MilvusFieldSchema,
        Hit as _MilvusHit,
    )
    from pymilvus.orm.mutation import MutationResult as _MilvusMutationResult
    from pydantic.fields import FieldInfo as _PydanticFieldInfo
    from pymongo import MongoClient as _SyncMongoClient, ReplaceOne as _PymongoReplaceOne
    from pymongo.synchronous.collection import Collection as _SyncMongoCollection
    from pymongo.synchronous.database import Database as _SyncMongoDB
    from bson import ObjectId as _BsonObjectId
    from redis.asyncio import Redis as _RedisAsyncClient
    from redis.commands.search.document import Document as _RedisSearchDocument
    from redis.commands.search.field import VectorField as _RedisVectorField
    from .orm.redis_search import _RedisSearchField
    from .orm.redis_support import RedisRuntimeCapabilities as _RedisCapabilities

from ..utils.concurrent_utils import run_async_in_sync as _run_async_in_sync
from ..utils.data_structs.files.medias import Audio, Image, Video
from .base import (
    SchemaInfo,
    StorageClientBase,
    StorageClientInitParams,
    _default_local_storage_root,
    _is_vector_annotation,
    _json_dumps,
    _json_loads,
    _normalize_expire_at,
    _now_ts,
    _sanitize_milvus_expr_value,
    _ttl_from_expire_at,
    _unwrap_optional,
    _validate_collection_name,
)
from .expire_sidecar import ExpireSidecar
from .orm.client_base import (
    _build_mongo_selected_projection,
    _build_mongo_selected_query,
    _match_query_or_expr,
    _normalize_selected_fields,
    _project_selected_pairs,
    _project_selected_payload,
    _query_to_expression,
    _restore_mongo_doc,
    _resolve_foreign_payload,
    _safe_model_schema,
    _to_mongo_object_id,
    _validate_selected_field_name,
)
from .orm import (
    ORMModel,
    ORMFieldInfo,
)
from .orm.field_metadata import ORMFieldInfoParams, _is_storage_excluded, build_field_name_mapping, check_schema_conflict, remap_payload_from_db, remap_payload_to_db, _translate_field_path
from .orm.query import QueryExpression, _AndExpression, _FieldExpression, _OrExpression
from ._vector_index import (
    MetricType,
    VectorIndex,
    VectorIndexAlgorithm,
    _VALID_METRIC_TYPES,
    _VALID_VECTOR_INDEX_ALGORITHMS,
    coerce_vector_index,
)
from .orm.redis_support import (
    async_load_redis_runtime_capabilities,
    ensure_redis_vector_supported,
)
from .orm.redis_search import (
    RedisScalarFieldSpec,
    RedisScalarKind,
    RedisSearchQueryError,
    RedisVectorFieldSpec,
    build_redis_scalar_fields,
    build_redis_vector_field,
    compile_redis_query,
    decode_redis_search_value,
    redis_payload_json_path,
    redis_scalar_sort_alias,
    redis_vector_alias,
    vector_query_param_bytes,
)

_logger = logging.getLogger(__name__)


def _async_owner_key() -> tuple[int, int]:
    return (threading.get_ident(), id(asyncio.get_running_loop()))


def _is_vector_annotation_string(annotation: str) -> bool:
    ann_lower = annotation.lower().replace(" ", "")
    valid_patterns = (
        "list[float]", "list[int]",
        "tuple[float,", "tuple[int,",
        "sequence[float]", "sequence[int]",
        "ndarray", "np.ndarray", "numpy.ndarray",
    )
    return any(pat in ann_lower for pat in valid_patterns)


def _selected_field_roots(fields: Sequence[str]) -> list[str]:
    roots: list[str] = []
    seen: set[str] = set()
    for field in _normalize_selected_fields(fields):
        if field in {"id", "_id"}:
            continue
        root = field.split(".", 1)[0]
        if root in seen:
            continue
        roots.append(root)
        seen.add(root)
    return roots


def _milvus_expr_literal(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    if isinstance(value, str):
        return f'"{_sanitize_milvus_expr_value(value)}"'
    return None


def _is_milvus_collection_not_loaded_error(exc: Exception) -> bool:
    return "collection not loaded" in str(exc).lower()


def _milvus_expression_field_name(field: str, available_scalar: set[str], field_name_map: dict[str, str] | None = None) -> str | None:
    validated = _validate_selected_field_name(str(field or ""))
    if validated not in {"id", "_id"} and "." in validated:
        return None
    resolved = "id" if validated in {"id", "_id"} else validated
    if resolved != "id" and resolved not in available_scalar:
        return None
    if resolved != "id" and field_name_map:
        resolved = field_name_map.get(resolved, resolved)
    return resolved


def _milvus_expression_to_filter(
    expression: QueryExpression,
    *,
    available_scalar: set[str],
    field_name_map: dict[str, str] | None = None,
) -> str | None:
    if isinstance(expression, _FieldExpression):
        field_name = _milvus_expression_field_name(expression.field, available_scalar, field_name_map)
        if field_name is None:
            return None

        if expression.op == "in":
            if not isinstance(expression.value, (list, tuple, set)):
                return None
            rendered_items = [_milvus_expr_literal(item) for item in expression.value]
            if any(item is None for item in rendered_items):
                return None
            return f"{field_name} in [{', '.join(cast(list[str], rendered_items))}]"

        if expression.op not in {"eq", "ne", "gt", "gte", "lt", "lte"}:
            return None
        literal = _milvus_expr_literal(expression.value)
        if literal is None:
            return None
        operator = {
            "eq": "==",
            "ne": "!=",
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
        }[expression.op]
        return f"{field_name} {operator} {literal}"

    if isinstance(expression, _AndExpression):
        left = _milvus_expression_to_filter(expression.left, available_scalar=available_scalar, field_name_map=field_name_map)
        right = _milvus_expression_to_filter(expression.right, available_scalar=available_scalar, field_name_map=field_name_map)
        if left is None or right is None:
            return None
        return f"({left}) and ({right})"

    if isinstance(expression, _OrExpression):
        left = _milvus_expression_to_filter(expression.left, available_scalar=available_scalar, field_name_map=field_name_map)
        right = _milvus_expression_to_filter(expression.right, available_scalar=available_scalar, field_name_map=field_name_map)
        if left is None or right is None:
            return None
        return f"({left}) or ({right})"

    return None


def _mongo_vector_similarity(metric: MetricType) -> Literal["cosine", "euclidean", "dotProduct"]:
    normalized = str(metric or "COSINE").upper()
    if normalized == "COSINE":
        return "cosine"
    if normalized in {"L2", "EUCLIDEAN"}:
        return "euclidean"
    if normalized in {"IP", "DOT"}:
        return "dotProduct"
    raise ValueError(
        f"Mongo vector search does not support metric_type `{metric}`; use COSINE, L2/EUCLIDEAN, or IP/DOT."
    )


_MONGO_SIMILARITY_TO_METRIC: dict[str, MetricType] = {
    "cosine": "COSINE",
    "euclidean": "L2",
    "dotproduct": "IP",
}


def _mongo_similarity_to_metric(similarity: str) -> MetricType | None:
    return _MONGO_SIMILARITY_TO_METRIC.get(str(similarity).lower())


def _mongo_vector_filter_supported(filter_doc: Mapping[str, object]) -> bool:
    for key, value in filter_doc.items():
        if key in {"$and", "$or"}:
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                return False
            if not all(isinstance(item, Mapping) and _mongo_vector_filter_supported(item) for item in value):
                return False
            continue
        if key.startswith("$"):
            return False
        if not isinstance(value, Mapping):
            continue
        for op, operand in value.items():
            if op not in {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte", "$in", "$exists"}:
                return False
            if op == "$in" and not isinstance(operand, (list, tuple, set)):
                return False
            if op == "$exists" and not isinstance(operand, bool):
                return False
    return True


type VectorEmbeddingContent = str | Image | Audio | Video
type VectorEmbeddingVector = Sequence[float] | np.ndarray
type VectorSearchInput = VectorEmbeddingContent | VectorEmbeddingVector
type VectorEmbedder = Callable[[VectorEmbeddingContent], VectorEmbeddingVector | Awaitable[VectorEmbeddingVector]]


def _is_vector_content(value: object) -> bool:
    return isinstance(value, (str, Image, Audio, Video))


def normalize_vector_embedding(vector: VectorEmbeddingVector) -> list[float]:
    if isinstance(vector, np.ndarray):
        vector = vector.tolist()
    if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes, bytearray)):
        raise TypeError(f'Unexpected embedding result type: {type(vector).__name__}')
    return [float(v) for v in vector]


def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _json_loads_if_needed(value: object) -> object:
    if isinstance(value, (str, bytes, bytearray)):
        return _json_loads(value)
    return value


def _json_loads_dict_or_none(value: object) -> dict[str, object] | None:
    loaded = _json_loads_if_needed(value)
    return loaded if isinstance(loaded, dict) else None


def _json_loads_str_list(value: object) -> list[str]:
    loaded = _json_loads_if_needed(value)
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item or "")]


def _coerce_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_metric_type(value: object, default: MetricType) -> MetricType:
    metric_name = str(value or default).upper()
    if metric_name in _VALID_METRIC_TYPES:
        return cast(MetricType, metric_name)
    return default


def _normalize_milvus_ids(ids: Sequence[str] | str | int | None) -> list[str] | str | int | None:
    if ids is None or isinstance(ids, (str, int)):
        return ids
    return [str(item) for item in ids]

def _extract_vector_embedder_model_name(candidate: object) -> str | None:
    if candidate is None:
        return None
    model_name = getattr(candidate, 'model', None) or getattr(candidate, '_model', None)
    if model_name:
        return str(model_name)
    for client in getattr(candidate, 'clients', []) or []:
        model_name = getattr(client, 'model', None) or getattr(client, '_model', None)
        if model_name:
            return str(model_name)
    return None

def _resolve_vector_embedder_model_name(embedder: Callable[..., object], default_model_name: str) -> str:
    model_name = _extract_vector_embedder_model_name(getattr(embedder, '__self__', None))
    if model_name:
        return model_name
    model_name = _extract_vector_embedder_model_name(embedder)
    if model_name:
        return model_name

    owner = getattr(embedder, '__self__', None)
    module = getattr(embedder, '__module__', None) or getattr(type(owner or embedder), '__module__', None)
    qualname = (
        getattr(embedder, '__qualname__', None)
        or getattr(embedder, '__name__', None)
        or getattr(type(owner or embedder), '__qualname__', None)
    )
    if module or qualname:
        return f'custom:{module or ""}.{qualname or ""}'.rstrip('.')
    return default_model_name

def _default_embedding_service_info() -> tuple["_EmbeddingService", str]:
    from ..ai.services.embedding import EmbeddingService

    service = EmbeddingService.Default()
    model_name = 'default'
    for client in getattr(service, 'clients', []):
        model_name = str(
            getattr(client, 'model', None)
            or getattr(client, '_model', None)
            or model_name
        )
        if model_name:
            break
    return service, model_name


def resolve_vector_embedder(
    embedder: VectorEmbedder | None = None,
    *,
    default_service: "_EmbeddingService | None" = None,
    default_model_name: str | None = None,
) -> tuple["_EmbeddingService | None", VectorEmbedder, str]:
    service = default_service
    model_name = default_model_name
    if embedder is None:
        if service is None or model_name is None:
            service, model_name = _default_embedding_service_info()
        assert model_name is not None
        return service, service.embedding, model_name
    resolved_model_name = _resolve_vector_embedder_model_name(embedder, model_name or 'default')
    return service, embedder, resolved_model_name


async def call_vector_embedder(embedder: VectorEmbedder, content: VectorEmbeddingContent) -> list[float]:
    vector = embedder(content)
    if inspect.isawaitable(vector):
        vector = await vector
    return normalize_vector_embedding(vector)


VectorModelT = TypeVar("VectorModelT", bound="VectorORMModel")
"""TypeVar bound to :class:`VectorORMModel` for generic overloads."""

_R = TypeVar("_R")


class _MilvusAsyncConnectKwargs(TypedDict, total=False):
    uri: str
    user: str
    password: str
    token: str
    db_name: str
    timeout: float | int


class _MilvusQueryKwargs(TypedDict, total=False):
    limit: int
    offset: int


class _MilvusDeleteKwargs(TypedDict, total=False):
    ids: list[str] | str | int
    filter: str


class _MilvusFieldSchemaKwargs(TypedDict, total=False):
    max_length: int


class _MilvusConnectionsProtocol(Protocol):
    def connect(
        self,
        *,
        alias: str,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        token: str | None = None,
        db_name: str | None = None,
        timeout: float | int | None = None,
    ) -> object: ...

    def disconnect(self, alias: str) -> object: ...


class _RedisSearchQueryBuilder(Protocol):
    def dialect(self, value: int) -> Self: ...

    def paging(self, offset: int, num: int) -> Self: ...

    def no_content(self) -> Self: ...

    def sort_by(self, field: str, asc: bool = True) -> Self: ...

    def return_field(self, field: str, as_field: str | None = None) -> Self: ...


class _RedisAsyncSearchProtocol(Protocol):
    async def search(self, query: object, query_params: Mapping[str, object] | None = None) -> object: ...

    async def info(self) -> object: ...

    async def create_index(self, fields: object, definition: object | None = None) -> object: ...

    async def alter_schema_add(self, fields: object) -> object: ...

    async def dropindex(self, delete_documents: bool = False) -> object: ...


def _redis_search_query(query_string: str) -> _RedisSearchQueryBuilder:
    from redis.commands.search.query import Query

    return cast(_RedisSearchQueryBuilder, Query(query_string))


class _MilvusIndexInfo(Protocol):
    field_name: str | None
    params: Mapping[str, object] | None


class _AnnoyIndexProtocol(Protocol):
    def load(self, path: str, prefault: bool = False) -> bool: ...

    def save(self, path: str) -> bool: ...

    def add_item(self, item_index: int, vector: Sequence[float]) -> None: ...

    def build(self, n_trees: int, n_jobs: int = -1) -> bool: ...

    def get_n_items(self) -> int: ...

    def get_nns_by_vector(
        self,
        vector: Sequence[float],
        n: int,
        search_k: int = -1,
        include_distances: bool = False,
    ) -> tuple[list[int], list[float]]: ...

type VectorPayloadLike = Mapping[str, object]
type VectorPayload = dict[str, object]
type VectorQuery = Mapping[str, object]
type HydratedVectorDocument = ORMModel | VectorPayload

class VectorORMFieldInfoParams(ORMFieldInfoParams, total=False):
    """Keyword arguments for :class:`VectorORMFieldInfo`.

    Extends :class:`ORMFieldInfoParams` with vector-embedding metadata.
    """
    index: VectorIndex | Literal[False] | None


class VectorORMFieldInfo(ORMFieldInfo):
    """Extended :class:`~core.storage.orm.ORMFieldInfo` with
    vector-specific metadata.

    Use the :func:`VectorORMField` factory instead of instantiating directly.

    Attributes:
        index: Declarative vector-index metadata for this field.
        is_vector: Whether this field is treated as a vector index field.
        drop_index: ``True`` when ``index=False`` signals existing index removal.
    """
    index: VectorIndex | None
    is_vector: bool
    drop_index: bool

    def __init__(
        self,
        *,
        index: VectorIndex | Literal[False] | None = None,
        **kwargs: Unpack[ORMFieldInfoParams],   # type: ignore
    ) -> None:
        resolved_index = coerce_vector_index(index)
        super().__init__(index=False, **kwargs) # type: ignore
        self.drop_index = resolved_index is False
        self.index = resolved_index if isinstance(resolved_index, VectorIndex) else None
        self.is_vector = isinstance(resolved_index, VectorIndex)

    @property
    def vector_index(self) -> VectorIndex | None:
        return self.index if isinstance(self.index, VectorIndex) else None

    @property
    def metric_type(self) -> MetricType | None:
        vector_index = self.vector_index
        return None if vector_index is None else vector_index.metric_type

    @property
    def dim(self) -> int | None:
        vector_index = self.vector_index
        return None if vector_index is None else int(vector_index.dim)

    @property
    def embedder(self) -> VectorEmbedder | None:
        vector_index = self.vector_index
        return None if vector_index is None else cast(VectorEmbedder | None, vector_index.embedder)

    @property
    def algorithm(self) -> VectorIndexAlgorithm | None:
        vector_index = self.vector_index
        return None if vector_index is None else vector_index.algorithm


def VectorORMField(
    default: Any = PydanticUndefined,
    *,
    index: VectorIndex | Literal[False] | None = None,
    foreign_model: bool = False,
    **kwargs: Any,
) -> Any:
    """Create a Pydantic field with vector-specific ORM metadata.

    Drop-in replacement for :func:`~core.storage.orm.ORMField`
    that adds vector-embedding parameters.

    Args:
        default: Default value (omit for required fields).
        index: Declarative vector-index metadata. Example:
            ``VectorIndex(dim=768, metric_type='COSINE', embedder=my_embedder)``.
        foreign_model: Store only the referenced model's ``id`` and resolve on
            read.  See :func:`~core.storage.orm.ORMField`.
        **kwargs: Standard :func:`~pydantic.Field` keyword arguments.
            See :class:`~core.storage.orm.PydanticFieldInfoParams`.

    Example::

        class DocumentChunk(VectorORMModel):
            text: str = ""
            embedding: list[float] = VectorORMField(
                default_factory=list,
                index=VectorIndex(dim=768, metric_type="COSINE"),
            )
    """
    if default is not PydanticUndefined:
        kwargs["default"] = default
    return VectorORMFieldInfo(
        index=index,
        foreign_model=foreign_model,
        **kwargs,
    )


class VectorClientInitParams(StorageClientInitParams, total=False):
    namespace: str
    default_expire: float | None
    metric_type: MetricType

class MilvusLiteVectorClientInitParams(VectorClientInitParams, total=False):
    db_path: str | Path

class PyMilvusVectorClientInitParams(VectorClientInitParams, total=False):
    uri: str
    token: str | None
    alias: str | None


class RedisVectorClientInitParams(VectorClientInitParams, total=False):
    url: str
    prefix: str
    db: int
    decode_responses: bool


class MongoVectorClientInitParams(VectorClientInitParams, total=False):
    mongo_url: str
    database: str

class VectorClientBase(StorageClientBase, ABC, storage_kind="vector"):

    def __init__(self, **kwargs: Unpack[VectorClientInitParams]) -> None:
        super().__init__(**kwargs)
        self._namespace = kwargs.get("namespace", "default")
        self._default_expire = kwargs.get("default_expire", None)
        self._metric_type: MetricType = cast(MetricType, kwargs.get("metric_type", "COSINE"))
        self._known_collections: set[str] = set()
        self._bootstrapped_collections: set[str] = set()
        self._forgotten_collections: set[str] = set()
        self._collection_init_locks: dict[str, asyncio.Lock] = {}
        self._collection_models: dict[str, type[ORMModel]] = {}
        self._vector_fields: dict[str, dict[str, int]] = {}
        self._vector_field_metrics: dict[str, dict[str, MetricType]] = {}
        self._vector_field_algorithms: dict[str, dict[str, VectorIndexAlgorithm]] = {}
        self._scalar_fields: dict[str, list[str]] = {}
        self._field_name_mappings: dict[str, dict[str, str]] = {}
        self._dropped_vector_fields: dict[str, list[str]] = {}  # collection → [field_names to drop]
        # Per-collection KV-backed expire / accessed_at sidecar. Populated when
        # the model declares ``__NoExpireField__=True`` or the backend probes
        # the existing physical schema and finds the metadata fields missing.
        # See ``core.storage.expire_sidecar``.
        self._sidecars: dict[str, ExpireSidecar] = {}
        if self._auto_start:
            self.start()

    @abstractmethod
    def start(self) -> Self:
        '''Start the client and initialise any backend connections.'''
        ...

    @abstractmethod
    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        '''Create the vector collection for *model_cls* if it does not exist.

        The model must have at least one field annotated as a vector (e.g.,
        ``list[float]`` with ``json_schema_extra={"dim": N}``).
        '''
        ...

    async def _load_stored_schema(self, _collection: str) -> dict[str, object] | None:
        """Load the stored model schema_json for *collection* from the backend.

        Returns ``None`` when the collection does not yet exist or the backend
        does not persist schema information (default: skip conflict check).
        """
        _ = _collection
        return None

    async def check_schema(self, model_cls: type[ORMModel]) -> SchemaInfo:
        '''Unified schema check entry point.

        If the collection is already bootstrapped in this process, returns
        immediately.  Otherwise delegates to :meth:`main_check_schema` which
        performs DDL and index alignment.
        '''
        collection = model_cls.CollectionName
        self._register_model(model_cls)
        if collection in self._bootstrapped_collections:
            return SchemaInfo(collection_name=collection, bootstrapped=True)
        lock = self._collection_init_locks.setdefault(collection, asyncio.Lock())
        async with lock:
            if collection in self._bootstrapped_collections:
                return SchemaInfo(collection_name=collection, bootstrapped=True)
            return await self.main_check_schema(model_cls)

    async def main_check_schema(self, model_cls: type[ORMModel]) -> SchemaInfo:
        '''Heavy schema operations — DDL creation, index alignment.

        Intended to run once per collection in the main process.
        '''
        collection = model_cls.CollectionName
        stored_schema = await self._load_stored_schema(collection)
        check_schema_conflict(model_cls, stored_schema, collection)
        await self.create_collection(model_cls)
        # Drop vector indexes for fields with index=False
        dropped = self._dropped_vector_fields.get(collection, [])
        if dropped:
            await self._drop_vector_indexes(collection, dropped)
        self._mark_collection_bootstrapped(collection)
        return SchemaInfo(collection_name=collection, bootstrapped=True)

    async def ensure_collection(self, model_cls: type[ORMModel]) -> None:
        '''Bootstrap a vector collection at most once per process.'''
        await self.check_schema(model_cls)

    async def load_collection(self, _collection: str | type[ORMModel]) -> None:
        '''Load a collection into memory for search/query.

        Backends that require explicit loading (e.g. Milvus) override this
        method.  The default implementation is a no-op.
        '''
        _ = _collection

    def mark_collection_bootstrapped(self, collection: str | type[ORMModel]) -> None:
        '''Mark a collection as already bootstrapped in this process.'''
        self._mark_collection_bootstrapped(self._resolve_collection(collection))

    @abstractmethod
    async def drop_collection(self, collection: str | type[ORMModel]) -> None:
        '''Permanently delete the named collection and all its data.

        Args:
            collection: Collection name string or :class:`ORMModel` subclass.
        '''
        ...

    async def _drop_vector_indexes(self, collection: str, fields: list[str]) -> None:
        """Drop vector indexes for the given *fields* (``index=False``).

        Backends that support index deletion override this method.
        The default implementation logs a warning.
        """
        for field in fields:
            _logger.warning(
                "%s: dropping vector index for field '%s.%s' is not supported; ignoring.",
                type(self).__name__, collection, field,
            )

    async def set(self, value: ORMModel | VectorPayloadLike, *, collection: str | type[ORMModel] | None = None, expire: float | int | None = None) -> str:
        '''Insert or replace a document in a vector collection.

        Args:
            value: An :class:`~core.storage.orm.ORMModel` instance
                or a plain ``dict`` (``collection`` required when using dict).
            collection: Target collection; inferred from model when ``None``.
            expire: Optional TTL in seconds or absolute UNIX timestamp.

        Returns:
            The string object-ID of the stored document.
        '''
        collection_resolved = self._resolve_collection(collection) if collection is not None else None
        collection_name, payload, model_cls = self._normalize_value(value, collection=collection_resolved)
        if model_cls is not None:
            await self.ensure_collection(model_cls)
        return await self.raw_set(collection_name, payload, expire=expire)

    async def set_many(
        self,
        values: Sequence[ORMModel | VectorPayloadLike],
        *,
        collection: str | type[ORMModel] | None = None,
        expire: float | int | None = None,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []
        object_ids: list[str] = []
        for value in batch:
            object_ids.append(await self.set(value, collection=collection, expire=expire))
        return object_ids

    @abstractmethod
    async def raw_set(
        self,
        collection: str | type[ORMModel],
        payload: VectorPayloadLike,
        *,
        expire: float | int | None = None,
    ) -> str:
        '''Insert or replace a raw logical payload without model hydration.'''
        ...

    async def raw_set_with_vector(
        self,
        collection: str | type[ORMModel],
        payload: VectorPayloadLike,
        vector: VectorEmbeddingVector,
        *,
        field: str | None = None,
        expire: float | int | None = None,
    ) -> str:
        if not isinstance(payload, Mapping):
            raise TypeError("VectorClient.raw_set_with_vector() only accepts mapping payloads.")
        collection_name = self._resolve_collection(collection)
        field_name = field or self._default_vector_field(collection_name)
        raw_payload: VectorPayload = dict(payload)
        raw_payload[field_name] = normalize_vector_embedding(vector)
        return await self.set(raw_payload, collection=collection_name, expire=expire)

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[True] = True) -> T | None: ...

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[False]) -> VectorPayload | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[False]) -> VectorPayload | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[False]) -> VectorPayload | None: ...

    async def get(self, collection: str | type[ORMModel], object_id: str, *, as_model: bool = True) -> HydratedVectorDocument | None:
        '''Retrieve a single document by *object_id*.

        Args:
            collection: Collection name.
            object_id: Document identifier.
            as_model: When ``True`` (default), return a typed model instance;
                ``False`` returns a raw ``dict``.

        Returns:
            Model instance, raw dict, or ``None`` if not found.
        '''
        collection_name = self._resolve_collection(collection)
        payload = await self.raw_get(collection_name, object_id)
        if payload is None:
            return None
        return await self._hydrate_logical_payload(collection_name, payload, as_model=as_model)

    @abstractmethod
    async def raw_get(self, collection: str | type[ORMModel], object_id: str) -> VectorPayload | None:
        '''Retrieve a raw logical payload by id without model hydration.'''
        ...

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @overload
    def search(self, collection: str, query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: str, query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    def search(self, collection: str | type[ORMModel], query: VectorQuery | Any | None = None, *, limit: int | None = None, offset: int = 0, as_model: bool = True) -> AsyncGenerator[HydratedVectorDocument, None]:
        '''Query documents by field values (non-vector filter search).

        Args:
            collection: Collection name.
            query: Field-equality filter dict; ``None`` returns all documents.
            limit: Maximum results to return (``None`` = unlimited).
            offset: Number of results to skip.
            as_model: Return typed model instances when ``True``.

        Yields:
            Matching documents.
        '''
        return self._typed_search(collection, query=query, limit=limit, offset=offset, as_model=as_model)

    async def _typed_search(
        self,
        collection: str | type[ORMModel],
        query: VectorQuery | Any | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:
        collection_name = self._resolve_collection(collection)
        async for item in self.raw_query(collection_name, query=query, limit=limit, offset=offset):  # type: ignore[misc]
            yield await self._hydrate_logical_payload(collection_name, item, as_model=as_model)

    @abstractmethod
    async def raw_query(
        self,
        collection: str | type[ORMModel],
        query: VectorQuery | Any | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[VectorPayload, None]:
        '''Iterate raw logical payloads without model hydration.'''
        ...

    async def _first_or_none(self, rows: AsyncGenerator[_R, None]) -> _R | None:
        try:
            return await anext(rows)
        except StopAsyncIteration:
            return None
        finally:
            await rows.aclose()

    async def selected_search(
        self,
        collection: str | type[ORMModel],
        *,
        fields: Sequence[str],
        query: VectorQuery | Any | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[VectorPayload, None]:
        """Project selected scalar/vector metadata fields as a nested ``dict``.

        Notes:
            - ``id`` is always included even when omitted from ``fields``.
            - Dotted paths are reconstructed as nested dict/list structures.
            - Numeric chunks are list indexes, so ``a.0.b`` becomes
              ``{"id": ..., "a": [{"b": value}]}``.
        """
        normalized_fields = _normalize_selected_fields(fields)
        async for item in self.search(collection, query, limit=limit, offset=offset, as_model=False):
            row = dict(item) if isinstance(item, Mapping) else cast(VectorPayload, item)
            yield _project_selected_payload(row, normalized_fields)

    async def selected_search_one(
        self,
        collection: str | type[ORMModel],
        *,
        fields: Sequence[str],
        query: VectorQuery | Any | None = None,
    ) -> VectorPayload | None:
        return await self._first_or_none(
            self.selected_search(collection, fields=fields, query=query, limit=1)
        )

    async def selected_search_by_id(
        self,
        collection: str | type[ORMModel],
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> VectorPayload | None:
        """Return one SelectedSearch projection by id without requiring ``id`` in fields."""
        return await self.selected_search_one(collection, fields=fields, query={"id": str(object_id)})

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @abstractmethod
    def search_vector(self, collection: str | type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: bool = True) -> AsyncGenerator[HydratedVectorDocument, None]:
        '''Nearest-neighbour search by vector similarity.

        Args:
            collection: Collection name.
            vector: Query vector, or ``str/Image/Audio/Video`` which will be
                embedded using the field-bound embedder.
            field: Vector field to search; inferred when only one exists.
            limit: Maximum results (default 10).
            query: Optional scalar filter applied before ANN search.
            as_model: Return typed model instances when ``True``.

        Yields:
            Nearest documents in order.
        '''
        ...

    async def delete(self, collection: str | type[ORMModel], object_id: str) -> bool:
        '''Delete a document by *object_id*.

        Returns:
            ``True`` if the document existed and was deleted.
        '''
        return await self.raw_delete(collection, object_id)

    @abstractmethod
    async def raw_delete(self, collection: str | type[ORMModel], object_id: str) -> bool:
        '''Delete a raw document by id without model hydration helpers.'''
        ...

    async def delete_many(self, collection: str | type[ORMModel], object_ids: Iterable[str]) -> dict[str, bool]:
        '''Delete multiple documents and return per-id deletion results.'''
        results: dict[str, bool] = {}
        for object_id in object_ids:
            object_id_text = str(object_id or "").strip()
            if not object_id_text:
                continue
            results[object_id_text] = bool(await self.delete(collection, object_id_text))
        return results

    @abstractmethod
    async def set_expire(self, collection: str | type[ORMModel], object_id: str, expire: float | int | None) -> bool:
        '''Update the expiry of an existing document.

        Returns:
            ``True`` if the document existed and was updated.
        '''
        ...

    @abstractmethod
    async def get_expire(self, collection: str | type[ORMModel], object_id: str) -> float | None:
        '''Return the absolute UNIX expiry timestamp of a document, or ``None``
        if the document does not exist or has no expiry.
        '''
        ...

    @abstractmethod
    async def cleanup(self, *, force: bool = False) -> int:
        '''Remove all expired documents across all collections.

        Returns:
            Total number of documents removed.
        '''
        ...

    def is_db_loaded(self) -> bool:
        '''Return ``True`` if the database is fully loaded and ready for queries.

        The default implementation always returns ``True``.  Backends that
        require lazy collection loading (e.g. Milvus) override this.
        '''
        return True

    def _register_model(self, model_cls: type[ORMModel]) -> None:
        vector_fields = self._extract_vector_fields(model_cls)
        if not vector_fields:
            raise ValueError(f"{model_cls.__name__} has no vector field definition.")
        self._known_collections.add(model_cls.CollectionName)
        self._collection_models[model_cls.CollectionName] = model_cls
        self._vector_fields[model_cls.CollectionName] = vector_fields
        self._field_name_mappings[model_cls.CollectionName] = build_field_name_mapping(model_cls)
        # Detect fields with index=False (drop_index)
        dropped: list[str] = []
        for field_name, field_info in model_cls.model_fields.items():
            if isinstance(field_info, VectorORMFieldInfo) and field_info.drop_index:
                dropped.append(field_name)
        if dropped:
            self._dropped_vector_fields[model_cls.CollectionName] = dropped
        else:
            self._dropped_vector_fields.pop(model_cls.CollectionName, None)
        # Extract per-field metric types from VectorORMFieldInfo
        metrics: dict[str, MetricType] = {}
        algorithms: dict[str, VectorIndexAlgorithm] = {}
        for field_name, field_info in model_cls.model_fields.items():
            if field_name not in vector_fields or not isinstance(field_info, VectorORMFieldInfo):
                continue
            if _is_storage_excluded(field_info):
                continue
            if field_info.metric_type is not None:
                metrics[field_name] = field_info.metric_type
            if field_info.algorithm is not None:
                algorithms[field_name] = field_info.algorithm
        if metrics:
            self._vector_field_metrics[model_cls.CollectionName] = metrics
        else:
            self._vector_field_metrics.pop(model_cls.CollectionName, None)
        if algorithms:
            self._vector_field_algorithms[model_cls.CollectionName] = algorithms
        else:
            self._vector_field_algorithms.pop(model_cls.CollectionName, None)
        # Compute scalar (non-vector, non-meta) field names for native storage
        _meta = {"id", "_id"}
        self._scalar_fields[model_cls.CollectionName] = [
            name for name, info in model_cls.model_fields.items()
            if name not in _meta and name not in vector_fields
            and not _is_storage_excluded(info)
        ]
        # Opt-in to KV sidecar when the model explicitly forbids schema fields
        # for expire/accessed_at metadata. Backends that auto-detect missing
        # native columns will register their own sidecars later.
        if getattr(model_cls, '__NoExpireField__', False):
            self._register_sidecar(model_cls.CollectionName)

    def _mark_collection_known(self, collection: str) -> None:
        collection_name = str(collection)
        self._known_collections.add(collection_name)
        self._forgotten_collections.discard(collection_name)

    def _mark_collection_bootstrapped(self, collection: str) -> None:
        collection_name = str(collection)
        self._known_collections.add(collection_name)
        self._forgotten_collections.discard(collection_name)
        self._bootstrapped_collections.add(collection_name)

    def _forget_collection(self, collection: str) -> None:
        collection_name = str(collection)
        self._known_collections.discard(collection_name)
        self._bootstrapped_collections.discard(collection_name)
        self._forgotten_collections.add(collection_name)
        self._sidecars.pop(collection_name, None)

    def _backend_tag(self) -> str:
        """Stable tag distinguishing this backend in sidecar KV keys."""
        return f'{getattr(self.__class__, "Type", self.__class__.__name__)}:{self._namespace}'

    def _register_sidecar(self, collection: str) -> ExpireSidecar:
        """Idempotently create and register a sidecar for *collection*."""
        existing = self._sidecars.get(collection)
        if existing is not None:
            return existing
        sidecar = ExpireSidecar(backend=self._backend_tag(), collection=collection)
        self._sidecars[collection] = sidecar
        return sidecar

    def _get_sidecar(self, collection: str) -> ExpireSidecar | None:
        return self._sidecars.get(collection)

    def _model_opts_out_of_expire_field(self, collection: str) -> bool:
        """Return True if the registered model declares ``__NoExpireField__=True``."""
        model_cls = self._collection_models.get(collection)
        if model_cls is None:
            return False
        return bool(getattr(model_cls, '__NoExpireField__', False))

    def _has_vector_annotation(self, model_cls: type[ORMModel], field_name: str, field_info: '_PydanticFieldInfo') -> bool:
        annotation = getattr(field_info, "annotation", None)
        if isinstance(annotation, str):
            return _is_vector_annotation_string(annotation)
        if annotation is not None:
            annotation, _ = _unwrap_optional(annotation)
            if _is_vector_annotation(annotation):
                return True

        raw_annotation = getattr(model_cls, "__annotations__", {}).get(field_name)
        if isinstance(raw_annotation, str):
            return _is_vector_annotation_string(raw_annotation)
        if raw_annotation is not None:
            raw_annotation, _ = _unwrap_optional(raw_annotation)
            return _is_vector_annotation(raw_annotation)
        return False

    def _resolve_vector_dim(self, model_cls: type[ORMModel], field_name: str, field_info: '_PydanticFieldInfo') -> int:
        if isinstance(field_info, VectorORMFieldInfo) and field_info.dim is not None:
            return int(field_info.dim)

        json_schema_extra = getattr(field_info, "json_schema_extra", None)
        if isinstance(json_schema_extra, Mapping):
            raw_dim = json_schema_extra.get("dim")
            if raw_dim is not None:
                return int(raw_dim)

        default = getattr(field_info, "default", PydanticUndefined)
        if default is not PydanticUndefined:
            if isinstance(default, (list, tuple)):
                return len(default)
            try:
                import numpy as np  # type: ignore
                if isinstance(default, np.ndarray):
                    if default.ndim <= 0:
                        return int(default.size)
                    return int(default.shape[-1])
            except ImportError:
                pass

        raise ValueError(
            f"Vector field `{field_name}` in {model_cls.__name__} must specify `dim` via "
            "VectorORMField(index=VectorIndex(dim=...)) or Field(json_schema_extra={'dim': N})."
        )

    def _extract_vector_fields(self, model_cls: type[ORMModel]) -> dict[str, int]:
        explicit_vector_fields: dict[str, int] = {}
        for field_name, field_info in model_cls.model_fields.items():
            if not (isinstance(field_info, VectorORMFieldInfo) and field_info.is_vector):
                continue
            if _is_storage_excluded(field_info):
                continue
            explicit_vector_fields[field_name] = self._resolve_vector_dim(model_cls, field_name, field_info)
        if explicit_vector_fields:
            return explicit_vector_fields

        inferred_vector_fields: dict[str, int] = {}
        for field_name, field_info in model_cls.model_fields.items():
            if not self._has_vector_annotation(model_cls, field_name, field_info):
                continue
            if _is_storage_excluded(field_info):
                continue
            inferred_vector_fields[field_name] = self._resolve_vector_dim(model_cls, field_name, field_info)
        if len(inferred_vector_fields) == 1:
            return inferred_vector_fields
        if len(inferred_vector_fields) > 1:
            raise ValueError(
                f"{model_cls.__name__} defines multiple vector-like fields without explicit VectorIndex metadata: "
                f"{', '.join(sorted(inferred_vector_fields))}. Mark one or more fields with VectorORMField(index=VectorIndex(...))."
            )
        return inferred_vector_fields

    def _resolve_collection(self, collection: str | type[ORMModel]) -> str:
        """Resolve a model class or string to a collection name string."""
        if isinstance(collection, type) and issubclass(collection, ORMModel):
            if collection.CollectionName not in self._collection_models:
                self._register_model(collection)
            return collection.CollectionName
        return str(collection)

    def _get_field_metric(self, collection: str, field: str) -> MetricType:
        """Return the distance metric for a specific vector field.

        Checks per-field :class:`VectorORMFieldInfo` metadata first, then falls
        back to the client-level ``metric_type``.
        """
        return self._vector_field_metrics.get(collection, {}).get(field, self._metric_type) # type: ignore

    def _get_field_algorithm(
        self,
        collection: str,
        field: str,
        *,
        default: VectorIndexAlgorithm,
    ) -> VectorIndexAlgorithm:
        return self._vector_field_algorithms.get(collection, {}).get(field, default)

    def _get_redis_field_algorithm(self, collection: str, field: str) -> Literal["FLAT", "HNSW"]:
        algorithm = self._get_field_algorithm(collection, field, default="FLAT")
        if algorithm not in {"FLAT", "HNSW"}:
            raise ValueError(
                f"Redis vector field `{collection}.{field}` only supports algorithm FLAT or HNSW, got {algorithm}."
            )
        return cast(Literal["FLAT", "HNSW"], algorithm)

    def _align_vector_field_to_db(
        self,
        collection: str,
        field: str,
        *,
        db_dim: int | None = None,
        db_metric: MetricType | None = None,
        db_algorithm: VectorIndexAlgorithm | None = None,
    ) -> None:
        """Force in-memory model state to match the actual DB schema for one vector field.

        Called when the model declaration disagrees with the existing DB index.
        The DB is NOT modified; only the in-memory dicts are patched so that all
        subsequent queries use the DB-side values.
        """
        if db_dim is not None:
            vf = self._vector_fields.get(collection)
            if vf is not None and field in vf:
                vf[field] = int(db_dim)
        if db_metric is not None:
            self._vector_field_metrics.setdefault(collection, {})[field] = db_metric
        if db_algorithm is not None:
            self._vector_field_algorithms.setdefault(collection, {})[field] = db_algorithm

    def _get_model_cls(self, collection: str | type[ORMModel]) -> type[ORMModel] | None:
        if isinstance(collection, type) and issubclass(collection, ORMModel):
            if collection.CollectionName not in self._collection_models:
                self._register_model(collection)
            return collection
        return self._collection_models.get(str(collection))

    async def _cleanup_foreign_on_delete(self, collection: str, payload: VectorPayload) -> None:
        """Clean up foreign resources (file_id fields) when deleting a vector record."""
        model_cls = self._collection_models.get(collection)
        if model_cls is None:
            return
        from .orm.field_schema import extract_field_specs
        specs = extract_field_specs(model_cls)
        if not specs:
            return
        from ..utils.data_structs.files.base import FileID
        for spec in specs.values():
            if spec.kind != "file_id":
                continue
            value = payload.get(spec.field_name)
            if value is None:
                continue
            try:
                if not isinstance(value, FileID):
                    value = FileID.model_validate(value if isinstance(value, dict) else _json_loads_if_needed(value))
                await FileID.Delete(value)
            except Exception as exc:
                _logger.warning(
                    "Failed to cleanup file_id field `%s.%s` (id=%s): %s",
                    collection, spec.field_name, getattr(value, "id", "?"), exc,
                )

    async def _handle_file_id_ref_on_overwrite(
        self, collection: str, old_payload: VectorPayload | None, new_payload: VectorPayload,
    ) -> None:
        """Adjust FileID ref counts when a vector record is overwritten."""
        if old_payload is None:
            return
        model_cls = self._collection_models.get(collection)
        if model_cls is None:
            return
        from .orm.field_schema import extract_field_specs
        specs = extract_field_specs(model_cls)
        if not specs:
            return
        from ..utils.data_structs.files.base import FileID
        for spec in specs.values():
            if spec.kind != "file_id":
                continue
            old_val = old_payload.get(spec.field_name)
            new_val = new_payload.get(spec.field_name)
            old_id = self._extract_file_id_hash(old_val)
            new_id = self._extract_file_id_hash(new_val)
            if old_id == new_id:
                continue
            # Decrement old ref
            if old_id is not None and old_val is not None:
                try:
                    fid = old_val if isinstance(old_val, FileID) else FileID.model_validate(
                        old_val if isinstance(old_val, dict) else _json_loads_if_needed(old_val)
                    )
                    await FileID.Delete(fid)
                except Exception as exc:
                    _logger.warning("file_id decref failed for %s.%s: %s", collection, spec.field_name, exc)
            # Increment new ref
            if new_id is not None and new_val is not None:
                try:
                    fid = new_val if isinstance(new_val, FileID) else FileID.model_validate(
                        new_val if isinstance(new_val, dict) else _json_loads_if_needed(new_val)
                    )
                    await FileID._incr_ref(fid.category, fid.id)
                except Exception as exc:
                    _logger.warning("file_id incref failed for %s.%s: %s", collection, spec.field_name, exc)

    @staticmethod
    def _extract_file_id_hash(value: object) -> str | None:
        if value is None:
            return None
        raw_id = getattr(value, "id", None)
        if raw_id is not None:
            return str(raw_id)
        if isinstance(value, dict):
            return str(value.get("id", ""))
        return None

    def _db_field_name(self, collection: str, python_name: str) -> str:
        """Translate a Python field name to its DB-side name for *collection*."""
        mapping = self._field_name_mappings.get(collection, {})
        return mapping.get(python_name, python_name)

    def _get_vector_field_info(
        self,
        collection: str | type[ORMModel],
        field: str | None = None,
    ) -> tuple[str, '_PydanticFieldInfo | None']:
        collection_name = self._resolve_collection(collection)
        field_name = field or self._default_vector_field(collection_name)
        model_cls = self._get_model_cls(collection)
        if model_cls is None:
            model_cls = self._collection_models.get(collection_name)
        if model_cls is None:
            return field_name, None
        return field_name, model_cls.model_fields.get(field_name)

    async def embed_field_value(
        self,
        collection: str | type[ORMModel],
        value: VectorEmbeddingContent,
        *,
        field: str | None = None,
        use_cache: bool = True,
        save_cache: bool = True,
    ) -> list[float]:
        collection_name = self._resolve_collection(collection)
        field_name, field_info = self._get_vector_field_info(collection, field)
        embedder = field_info.embedder if isinstance(field_info, VectorORMFieldInfo) else None
        service, resolved_embedder, _ = resolve_vector_embedder(embedder)
        if embedder is None:
            if service is None:
                raise RuntimeError("Default embedding service is unavailable.")
            vector = await service.embedding(value, use_cache=use_cache, save_cache=save_cache)
            vector_list = normalize_vector_embedding(vector)
        else:
            vector_list = await call_vector_embedder(resolved_embedder, value)
        expected_dim = int((self._vector_fields.get(collection_name) or {}).get(field_name) or 0)
        if expected_dim and len(vector_list) != expected_dim:
            raise ValueError(
                f"Vector field `{field_name}` dimension mismatch: expected {expected_dim}, got {len(vector_list)}."
            )
        return vector_list

    async def _resolve_search_vector(
        self,
        collection: str | type[ORMModel],
        vector: VectorSearchInput,
        *,
        field: str | None = None,
        use_cache: bool = True,
        save_cache: bool = False,
    ) -> tuple[str, str, list[float]]:
        collection_name = self._resolve_collection(collection)
        field_name = field or self._default_vector_field(collection_name)
        if _is_vector_content(vector):
            content = cast(VectorEmbeddingContent, vector)
            return collection_name, field_name, await self.embed_field_value(
                collection,
                content,
                field=field_name,
                use_cache=use_cache,
                save_cache=save_cache,
            )
        return collection_name, field_name, normalize_vector_embedding(cast(VectorEmbeddingVector, vector))

    def _normalize_value(self, value: ORMModel | VectorPayloadLike, *, collection: str | None = None) -> tuple[str, VectorPayload, type[ORMModel] | None]:
        if isinstance(value, ORMModel):
            model_cls = type(value)
            self._register_model(model_cls)
            payload = value._serialize_for_storage()
            raw_id = payload.pop("_id", None) or payload.pop("id", None) or str(value.id)
            payload["id"] = str(raw_id)
            return collection or model_cls.CollectionName, payload, model_cls
        if not isinstance(value, Mapping):
            raise TypeError("VectorClient.set() only accepts ORMModel or mapping.")
        if not collection:
            raise ValueError("`collection` is required when setting plain mapping into vector db.")
        payload: VectorPayload = dict(value)
        raw_id = payload.get("id", payload.get("_id"))
        if raw_id is None:
            raw_id = hashlib.md5(_json_dumps(payload).encode("utf-8")).hexdigest()
        payload["id"] = str(raw_id)
        payload.pop("_id", None)
        return collection, payload, self._collection_models.get(collection)

    def _default_vector_field(self, collection: str) -> str:
        fields = self._vector_fields.get(collection) or {}
        if not fields:
            raise ValueError(f"Collection `{collection}` has no registered vector field.")
        return next(iter(fields.keys()))

    def _hydrate(self, collection: str, payload: VectorPayload, *, as_model: bool = True, _remapped: bool = False) -> HydratedVectorDocument:
        if not _remapped:
            mapping = self._field_name_mappings.get(collection, {})
            if mapping:
                payload = remap_payload_from_db(payload, mapping)
        if not as_model:
            return payload
        model_cls = self._collection_models.get(collection)
        if model_cls is None:
            return payload
        return model_cls.model_validate(payload)

    async def _hydrate_with_foreign(self, collection: str, payload: VectorPayload, *, as_model: bool = True) -> HydratedVectorDocument:
        """Like :meth:`_hydrate` but resolves foreign-model fields first."""
        mapping = self._field_name_mappings.get(collection, {})
        if mapping:
            payload = remap_payload_from_db(payload, mapping)
        if as_model:
            model_cls = self._collection_models.get(collection)
            if model_cls is not None:
                payload = await _resolve_foreign_payload(payload, model_cls)
        return self._hydrate(collection, payload, as_model=as_model, _remapped=True)

    async def _hydrate_logical_payload(self, collection: str, payload: VectorPayload, *, as_model: bool = True) -> HydratedVectorDocument:
        logical_payload = dict(payload)
        if as_model:
            model_cls = self._collection_models.get(collection)
            if model_cls is not None:
                logical_payload = await _resolve_foreign_payload(logical_payload, model_cls)
        return self._hydrate(collection, logical_payload, as_model=as_model, _remapped=True)

class VectorORMModel(ORMModel):
    """Base model for vector-backed collections.

    Subclass this instead of :class:`ORMModel` when the collection contains
    vector embedding fields.  Use :func:`VectorORMField` to annotate vector
    fields with dimension, metric type, etc.

    Example::

        class DocumentChunk(VectorORMModel):
            text: str = ""
            embedding: list[float] = VectorORMField(
                default_factory=list,
                index=VectorIndex(dim=768, metric_type="COSINE"),
            )

        # persist
        chunk = DocumentChunk(text="hello", embedding=[0.1]*768)
        await chunk.save()

        # nearest-neighbour search
        async for hit in DocumentChunk.SearchVector([0.2]*768, limit=5):
            print(hit.text)
    """

    Client: ClassVar[VectorClientBase | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Validate vector field annotations at class definition time.
        # At this point Pydantic hasn't populated model_fields yet, so we
        # inspect cls.__annotations__ + cls.__dict__ directly.
        for attr_name, raw_ann in getattr(cls, "__annotations__", {}).items():
            default = cls.__dict__.get(attr_name)
            if not isinstance(default, VectorORMFieldInfo) or not default.is_vector:
                continue
            # raw_ann is a string when ````
            # is active; otherwise it's the resolved type.
            if isinstance(raw_ann, str):
                if not _is_vector_annotation_string(raw_ann):
                    raise TypeError(
                        f"Field `{attr_name}` in {cls.__name__} is marked "
                        f"with a VectorIndex but has annotation `{raw_ann}` which "
                        f"is not a vector type. Expected list[float], tuple[float, ...], "
                        f"Sequence[float], or numpy.ndarray."
                    )
            else:
                if not _is_vector_annotation(raw_ann):
                    raise TypeError(
                        f"Field `{attr_name}` in {cls.__name__} is marked "
                        f"with a VectorIndex but has annotation `{raw_ann}` which "
                        f"is not a vector type. Expected list[float], tuple[float, ...], "
                        f"Sequence[float], or numpy.ndarray."
                    )

    @classmethod
    def GetClient(cls) -> VectorClientBase:
        if isinstance(cls.Client, VectorClientBase):
            return cls.Client
        resolved: VectorClientBase | None = None
        try:
            from .config import StorageConfig
            resolved = StorageConfig.Global().vector.get_client(
                getattr(cls, 'CollectionName', 'default'),
            )
        except Exception:
            resolved = None
        if not isinstance(resolved, VectorClientBase):
            resolved = cast(VectorClientBase, VectorClientBase.Default())
        cls.Client = resolved
        return resolved

    @classmethod
    def _get_vector_client(cls, client: VectorClientBase | None = None) -> VectorClientBase:
        """Resolve the vector client to use (explicit → class-level → config section → global)."""
        if client is not None:
            return client
        return cls.GetClient()

    @classmethod
    async def Load(cls, *, client: VectorClientBase | None = None) -> None:
        """Load this model's collection into memory for search/query.

        Delegates to :meth:`VectorClientBase.load_collection`.  Backends
        that don't require explicit loading (non-Milvus) treat this as a
        no-op.
        """
        vc = cls._get_vector_client(client)
        await vc.load_collection(cls)

    @classmethod
    def Loaded(cls, *, client: VectorClientBase | None = None) -> bool:
        """Return ``True`` if the underlying vector database is fully loaded."""
        vc = cls._get_vector_client(client)
        return vc.is_db_loaded()

    @classmethod
    def get_vector_fields(cls) -> dict[str, VectorORMFieldInfo]:
        """Return all fields carrying explicit vector-index metadata."""
        return {
            name: info
            for name, info in cls.model_fields.items()
            if isinstance(info, VectorORMFieldInfo) and info.is_vector
            and not _is_storage_excluded(info)
        }

    # -- persistence overrides (use VectorClientBase instead of ORMClientBase) --

    async def save(
        self,
        *,
        client: VectorClientBase | None = None,  # type: ignore[override]
        expire: float | int | None = None,
        **_: Any,
    ) -> str:
        """Persist this model to the vector backend."""
        from .base import ObjectId as _OID
        vc = self.__class__._get_vector_client(client)
        object_id = await vc.set(self, expire=expire)
        try:
            self.id = _OID(str(object_id))  # type: ignore[call-arg]
        except Exception:
            pass
        return object_id

    @classmethod
    async def BatchSave(
        cls,
        values: Sequence["VectorORMModel | VectorPayloadLike"],
        *,
        client: VectorClientBase | None = None,
        expire: float | int | None = None,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []
        return await cls._get_vector_client(client).set_many(batch, collection=cls, expire=expire)

    @classmethod
    async def Search(
        cls: type[VectorModelT],
        query: VectorQuery | Any | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
        client: VectorClientBase | None = None,  # type: ignore[override]
    ) -> AsyncGenerator[VectorModelT | VectorPayload, None]:
        """Scalar-filter search on this vector collection."""
        vc = cls._get_vector_client(client)
        async for item in vc.search(cls, query, limit=limit, offset=offset, as_model=as_model):
            yield item

    @classmethod
    async def SelectedSearch(
        cls,
        query: VectorQuery | Any | None = None,
        *,
        fields: Sequence[str],
        limit: int | None = None,
        offset: int = 0,
        client: VectorClientBase | None = None,
    ) -> AsyncGenerator[VectorPayload, None]:
        """Yield vector-record projections with auto-added ``id``.

        Dotted paths are rebuilt into nested dict/list shapes. For example,
        ``a.0.b`` returns ``{"id": ..., "a": [{"b": value}]}``.
        """
        vc = cls._get_vector_client(client)
        async for item in vc.selected_search(cls, fields=fields, query=query, limit=limit, offset=offset):
            yield item

    @classmethod
    async def SearchVector(
        cls: type[VectorModelT],
        vector: VectorSearchInput,
        *,
        field: str | None = None,
        limit: int = 10,
        query: VectorQuery | Any | None = None,
        as_model: bool = True,
        client: VectorClientBase | None = None,
    ) -> AsyncGenerator[VectorModelT | VectorPayload, None]:
        """Nearest-neighbour search on this model's vector collection.

        Args:
            vector: Query vector, or ``str/Image/Audio/Video`` to be embedded
                with the field's configured embedder.
            field: Vector field to search; auto-detected when only one exists.
            limit: Maximum results.
            query: Optional scalar filter.
            as_model: Return model instances (``True``) or raw dicts.
            client: Explicit client; falls back to ``cls.Client`` then global.

        Yields:
            Matching documents ordered by similarity.
        """
        vc = cls._get_vector_client(client)
        async for item in vc.search_vector(
            cls, vector, field=field, limit=limit, query=query, as_model=as_model,
        ):
            yield item

    @overload
    @classmethod
    async def SearchOne(
        cls: type[VectorModelT],
        query: Mapping[str, Any] | None = None,
        *,
        as_model: Literal[True] = True,
        client: VectorClientBase | None = None,  # type: ignore[override]
    ) -> VectorModelT | None: ...

    @overload
    @classmethod
    async def SearchOne(
        cls: type[VectorModelT],
        query: VectorQuery | None = None,
        *,
        as_model: Literal[False],
        client: VectorClientBase | None = None,  # type: ignore[override]
    ) -> VectorPayload | None: ...

    @classmethod
    async def SearchOne(
        cls: type[VectorModelT],
        query: VectorQuery | Any | None = None,
        *,
        as_model: bool = True,
        client: VectorClientBase | None = None,  # type: ignore[override]
    ) -> VectorModelT | VectorPayload | None:
        vc = cls._get_vector_client(client)
        return await vc._first_or_none(vc.search(cls, query, limit=1, as_model=as_model))

    @classmethod
    async def SelectedSearchOne(
        cls,
        query: VectorQuery | Any | None = None,
        *,
        fields: Sequence[str],
        client: VectorClientBase | None = None,
    ) -> VectorPayload | None:
        """Return the first vector SelectedSearch projection, including ``id``."""
        vc = cls._get_vector_client(client)
        return await vc.selected_search_one(cls, fields=fields, query=query)

    async def delete(self, *, client: VectorClientBase | None = None) -> bool:  # type: ignore[override]
        return await self.__class__.Delete(str(self.id), client=client)

    @classmethod
    async def Delete(cls, object_id: str, *, client: VectorClientBase | None = None) -> bool:  # type: ignore[override]
        vc = cls._get_vector_client(client)
        return await vc.delete(cls, str(object_id))

    @overload
    @classmethod
    async def SearchOneById(
        cls: type[VectorModelT],
        object_id: str,
        *,
        as_model: Literal[True] = True,
        client: VectorClientBase | None = None,  # type: ignore[override]
    ) -> VectorModelT | None: ...

    @overload
    @classmethod
    async def SearchOneById(
        cls: type[VectorModelT],
        object_id: str,
        *,
        as_model: Literal[False],
        client: VectorClientBase | None = None,  # type: ignore[override]
    ) -> VectorPayload | None: ...

    @classmethod
    async def SearchOneById(
        cls: type[VectorModelT],
        object_id: str,
        *,
        as_model: bool = True,
        client: VectorClientBase | None = None,  # type: ignore[override]
    ) -> VectorModelT | VectorPayload | None:
        vc = cls._get_vector_client(client)
        return await vc.get(cls, str(object_id), as_model=as_model)

    @classmethod
    async def SelectedSearchOneById(
        cls,
        object_id: str,
        *,
        fields: Sequence[str],
        client: VectorClientBase | None = None,
    ) -> VectorPayload | None:
        """Return one vector SelectedSearch projection by id.

        ``id`` is always present in the returned dict even when only nested
        paths such as ``a.0.b`` are requested.
        """
        vc = cls._get_vector_client(client)
        return await vc.selected_search_by_id(cls, str(object_id), fields=fields)

    @classmethod
    async def SetExpire(
        cls,
        object_id: str,
        expire: float | int | None,
        *,
        client: VectorClientBase | None = None,
    ) -> bool:
        vc = cls._get_vector_client(client)
        return await vc.set_expire(cls, str(object_id), expire)

    @classmethod
    async def GetExpire(
        cls,
        object_id: str,
        *,
        client: VectorClientBase | None = None,
    ) -> float | None:
        vc = cls._get_vector_client(client)
        return await vc.get_expire(cls, str(object_id))
class _BaseMilvusVectorClient(VectorClientBase):
    def __init__(self, **kwargs: Unpack[VectorClientInitParams]) -> None:
        from pymilvus import AsyncMilvusClient, Collection, CollectionSchema, DataType, FieldSchema, connections, utility  # type: ignore
        self._alias = kwargs.get("name") or f"proj_{kwargs.get('namespace', 'default')}"
        self._AsyncMilvusClient: type[_AsyncMilvusClient] = AsyncMilvusClient
        self._connections: _MilvusConnectionsProtocol = cast(_MilvusConnectionsProtocol, connections)
        self._utility: _types_mod.ModuleType = utility
        self._Collection: type[_MilvusCollection] = Collection
        self._FieldSchema: type[_MilvusFieldSchema] = FieldSchema
        self._CollectionSchema: type[_MilvusCollectionSchema] = CollectionSchema
        self._DataType: type[_MilvusDataType] = DataType
        self._async_client: _AsyncMilvusClient | None = None
        self._async_connect_kwargs: _MilvusAsyncConnectKwargs = {}
        self._loaded_collections: set[str] = set()
        self._pending_flush_collections: set[str] = set()
        self._flush_locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[int] | None = None
        self._cleanup_alock = asyncio.Lock()
        super().__init__(**kwargs)
        self._last_cleanup_at = time.time()

    def _connect(self, **connect_kwargs: Unpack[_MilvusAsyncConnectKwargs]) -> None:
        self._connections.connect(alias=self._alias, **connect_kwargs)
        async_connect_kwargs: _MilvusAsyncConnectKwargs = {}
        for key, value in connect_kwargs.items():
            if value is None:
                continue
            if key in {"uri", "user", "password", "token", "db_name"}:
                async_connect_kwargs[key] = str(value)
                continue
            if key == "timeout" and isinstance(value, (int, float)):
                async_connect_kwargs[key] = value
        self._async_connect_kwargs = async_connect_kwargs
        try:
            self._async_client = self._AsyncMilvusClient(**self._async_connect_kwargs)
            self._async_client_loop_id: int | None = None
        except Exception as exc:
            self._async_client = None
            self._async_client_loop_id = None
            _logger.warning(
                "%s could not initialise AsyncMilvusClient for %s; falling back to sync pymilvus calls: %s",
                self.__class__.__name__,
                self._async_connect_kwargs.get("uri", self._alias),
                exc,
            )

    async def _ensure_async_client(self) -> None:
        """Re-create async client if the running event loop has changed."""
        if self._async_client is None:
            return
        if type(self._async_client).__name__ == '_AsyncMilvusClientProxy':
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        current_loop_id = id(loop)
        if getattr(self, '_async_client_loop_id', None) == current_loop_id:
            return
        try:
            close = getattr(self._async_client, "close", None)
            if callable(close):
                close_result = close()
                if inspect.isawaitable(close_result):
                    await close_result
        except Exception:
            pass
        try:
            self._async_client = self._AsyncMilvusClient(**self._async_connect_kwargs)
            self._async_client_loop_id = current_loop_id
        except Exception as exc:
            self._async_client = None
            self._async_client_loop_id = None
            _logger.warning(
                "%s could not re-initialise AsyncMilvusClient for %s after event loop change: %s",
                self.__class__.__name__,
                self._async_connect_kwargs.get("uri", self._alias),
                exc,
            )

    def _schedule_cleanup(self) -> None:
        """Fire-and-forget cleanup in background so set()/set_many() never blocks on it."""
        if not self._should_cleanup():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        self._cleanup_task = loop.create_task(self._guarded_cleanup())

    async def _guarded_cleanup(self) -> int:
        async with self._cleanup_alock:
            if not self._should_cleanup():
                return 0
            try:
                return await self.cleanup(force=True)
            except Exception:
                _logger.debug("%s background cleanup error", self.__class__.__name__, exc_info=True)
                return 0

    def close(self) -> None:
        task = self._cleanup_task
        self._cleanup_task = None
        if task is not None and not task.done():
            task.cancel()
        try:
            async_client = self._async_client
            self._async_client = None
            self._async_client_loop_id = None
            if async_client is not None:
                close = getattr(async_client, "close", None)
                if callable(close):
                    close_result = close()
                    if inspect.isawaitable(close_result):
                        _run_async_in_sync(lambda cr=close_result: cr)
        except Exception as e:
            _logger.warning('%s.close() async client close failed for alias %s: %s', self.__class__.__name__, self._alias, e)

        try:
            disconnect = getattr(self._connections, 'disconnect', None)
            if callable(disconnect):
                disconnect(self._alias)
        except Exception as e:
            _logger.warning('%s.close() failed for alias %s: %s', self.__class__.__name__, self._alias, e)
        finally:
            self._mark_stopped()

    def _normalize_milvus_collection_name(self, value: str) -> str:
        raw = str(value or "")
        normalized = "".join(
            ch if (("0" <= ch <= "9") or ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ch == "_") else "_"
            for ch in raw
        )
        if not normalized:
            normalized = "collection"
        needs_hash = normalized != raw
        if not (("A" <= normalized[0] <= "Z") or ("a" <= normalized[0] <= "z") or normalized[0] == "_"):
            normalized = f"c_{normalized}"
            needs_hash = True

        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        suffix = f"_{digest}" if needs_hash else ""
        max_base_len = 255 - len(suffix)
        if len(normalized) > max_base_len:
            normalized = normalized[:max_base_len]
            suffix = f"_{digest}"
        return f"{normalized[:255 - len(suffix)]}{suffix}"

    def _collection_name(self, collection: str) -> str:
        _validate_collection_name(collection)
        return self._normalize_milvus_collection_name(collection)

    def _collection(self, collection: str) -> '_MilvusCollection':
        return self._Collection(self._collection_name(collection), using=self._alias)

    def _milvus_scalar_value_for_write(self, collection_name: str, field_name: str, value: object) -> object:
        model_cls = self._collection_models.get(collection_name)
        if model_cls is None:
            return value
        field_info = (getattr(model_cls, "model_fields", {}) or {}).get(field_name)
        if field_info is None:
            return value
        dtype, _ = self._milvus_dtype_for_annotation(field_info.annotation, field_info)
        if dtype == self._DataType.JSON:
            return _json_dumps(value)
        return value

    def _has_async_client(self) -> bool:
        return self._async_client is not None

    def _mark_flush_pending(self, collection_name: str) -> None:
        self._pending_flush_collections.add(collection_name)

    def _flush_lock(self, collection_name: str) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
        except RuntimeError:
            loop_id = 0
        key = (loop_id, collection_name)
        lock = self._flush_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._flush_locks[key] = lock
        return lock

    async def _ensure_flushed(self, collection_name: str) -> None:
        if collection_name not in self._pending_flush_collections:
            return
        lock = self._flush_lock(collection_name)
        async with lock:
            if collection_name not in self._pending_flush_collections:
                return
            await self._milvus_flush(collection_name)
            self._pending_flush_collections.discard(collection_name)

    async def _milvus_flush(self, collection_name: str) -> None:
        await self._ensure_async_client()
        if self._async_client is not None:
            flush = getattr(self._async_client, "flush", None)
            if callable(flush):
                flush_result = flush(self._collection_name(collection_name))
                if inspect.isawaitable(flush_result):
                    await flush_result
                return
        await self._t(self._collection(collection_name).flush)

    async def _milvus_has_collection(self, collection_name: str) -> bool:
        await self._ensure_async_client()
        physical_name = self._collection_name(collection_name)
        if self._async_client is not None:
            return bool(await self._async_client.has_collection(physical_name))
        return bool(await self._t(self._utility.has_collection, physical_name, using=self._alias))

    async def _milvus_drop_collection(self, collection_name: str) -> None:
        await self._ensure_async_client()
        physical_name = self._collection_name(collection_name)
        if self._async_client is not None:
            await self._async_client.drop_collection(physical_name)
            return
        await self._t(self._utility.drop_collection, physical_name, using=self._alias)

    async def _milvus_load_collection(self, collection_name: str) -> None:
        if collection_name in self._loaded_collections:
            return
        if not await self._milvus_has_collection(collection_name):
            return
        physical_name = self._collection_name(collection_name)
        await self._ensure_async_client()
        if self._async_client is not None:
            await self._async_client.load_collection(physical_name)
        else:
            await self._t(self._collection(collection_name).load)
        self._loaded_collections.add(collection_name)

    async def _milvus_release_collection(self, collection_name: str) -> None:
        await self._ensure_async_client()
        physical_name = self._collection_name(collection_name)
        if self._async_client is not None:
            await self._async_client.release_collection(physical_name)
        else:
            await self._t(self._collection(collection_name).release)
        self._loaded_collections.discard(collection_name)

    def is_db_loaded(self) -> bool:
        return bool(self._loaded_collections) and self._loaded_collections >= set(self._collection_models)

    async def load_collection(self, collection: str | type[ORMModel]) -> None:
        '''Load a Milvus collection into memory for search/query.'''
        name = self._resolve_collection(collection)
        await self._milvus_load_collection(name)

    async def offload_collection(self, collection: str | type[ORMModel]) -> None:
        '''Release a Milvus collection from memory.'''
        name = self._resolve_collection(collection)
        await self._milvus_release_collection(name)

    async def _ensure_collection_loaded(self, collection_name: str) -> None:
        await self._milvus_load_collection(collection_name)

    async def _milvus_query_rows(
        self,
        collection_name: str,
        *,
        expr: str,
        output_fields: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        ids: Sequence[str] | str | int | None = None,
    ) -> list[VectorPayload]:
        if not await self._milvus_has_collection(collection_name):
            return []
        await self._ensure_flushed(collection_name)
        query_kwargs: _MilvusQueryKwargs = {}
        if limit is not None:
            query_kwargs["limit"] = int(limit)
            if offset:
                query_kwargs["offset"] = int(offset)
        normalized_ids = _normalize_milvus_ids(ids)
        await self._ensure_async_client()
        if self._async_client is not None:
            try:
                rows = cast(list[Mapping[str, object]], await self._async_client.query(
                    self._collection_name(collection_name),
                    filter=expr,
                    output_fields=list(output_fields) if output_fields is not None else None,
                    ids=normalized_ids,
                    **query_kwargs,
                ))
            except Exception as exc:
                if not _is_milvus_collection_not_loaded_error(exc):
                    raise
                self._loaded_collections.discard(collection_name)
                await self._milvus_load_collection(collection_name)
                await self._ensure_async_client()
                rows = cast(list[Mapping[str, object]], await self._async_client.query(
                    self._collection_name(collection_name),
                    filter=expr,
                    output_fields=list(output_fields) if output_fields is not None else None,
                    ids=normalized_ids,
                    **query_kwargs,
                ))
            if limit is None and offset:
                rows = rows[offset:]
            return [dict(row) for row in rows]
        try:
            rows = await self._t(
                self._collection(collection_name).query,
                expr=expr,
                output_fields=list(output_fields) if output_fields is not None else None,
                **query_kwargs,
            )
        except Exception as exc:
            if not _is_milvus_collection_not_loaded_error(exc):
                raise
            self._loaded_collections.discard(collection_name)
            await self._milvus_load_collection(collection_name)
            rows = await self._t(
                self._collection(collection_name).query,
                expr=expr,
                output_fields=list(output_fields) if output_fields is not None else None,
                **query_kwargs,
            )
        rows = cast(list[Mapping[str, object]], rows)
        if limit is None and offset:
            rows = rows[offset:]
        return [dict(row) for row in rows]

    async def _milvus_search_rows(
        self,
        collection_name: str,
        *,
        data: list[list[float]] | list[float],
        anns_field: str,
        limit: int,
        output_fields: Sequence[str] | None = None,
    ) -> list[Sequence['_MilvusHit | Mapping[str, object]']]:
        await self._ensure_flushed(collection_name)
        search_params = {"metric_type": self._get_field_metric(collection_name, anns_field), "params": {}}
        await self._ensure_async_client()
        if self._async_client is not None:
            try:
                rows = cast(list[Sequence['_MilvusHit | Mapping[str, object]']], await self._async_client.search(
                    self._collection_name(collection_name),
                    data=data,
                    anns_field=anns_field,
                    limit=int(limit),
                    output_fields=list(output_fields) if output_fields is not None else None,
                    search_params=search_params,
                ))
            except Exception as exc:
                if not _is_milvus_collection_not_loaded_error(exc):
                    raise
                self._loaded_collections.discard(collection_name)
                await self._milvus_load_collection(collection_name)
                await self._ensure_async_client()
                rows = cast(list[Sequence['_MilvusHit | Mapping[str, object]']], await self._async_client.search(
                    self._collection_name(collection_name),
                    data=data,
                    anns_field=anns_field,
                    limit=int(limit),
                    output_fields=list(output_fields) if output_fields is not None else None,
                    search_params=search_params,
                ))
            return [cast(Sequence['_MilvusHit | Mapping[str, object]'], row) for row in rows]
        try:
            rows = await self._t(
                self._collection(collection_name).search,
                data=data,
                anns_field=anns_field,
                param=search_params,
                limit=int(limit),
                output_fields=list(output_fields) if output_fields is not None else None,
            )
        except Exception as exc:
            if not _is_milvus_collection_not_loaded_error(exc):
                raise
            self._loaded_collections.discard(collection_name)
            await self._milvus_load_collection(collection_name)
            rows = await self._t(
                self._collection(collection_name).search,
                data=data,
                anns_field=anns_field,
                param=search_params,
                limit=int(limit),
                output_fields=list(output_fields) if output_fields is not None else None,
            )
        rows = cast(list[Sequence['_MilvusHit | Mapping[str, object]']], rows)
        return [cast(Sequence['_MilvusHit | Mapping[str, object]'], row) for row in rows]

    async def _milvus_upsert(self, collection_name: str, row: VectorPayload) -> '_MilvusMutationResult | Mapping[str, object]':
        await self._ensure_async_client()
        if self._async_client is not None:
            return await self._async_client.upsert(self._collection_name(collection_name), row)
        return await self._t(self._collection(collection_name).upsert, [row])

    async def _milvus_upsert_many(self, collection_name: str, rows: Sequence[VectorPayload]) -> '_MilvusMutationResult | Mapping[str, object] | None':
        if not rows:
            return None
        await self._ensure_async_client()
        if self._async_client is not None:
            return await self._async_client.upsert(self._collection_name(collection_name), list(rows))
        return await self._t(self._collection(collection_name).upsert, list(rows))

    async def _milvus_delete(self, collection_name: str, *, ids: Sequence[str] | str | int | None = None, expr: str | None = None) -> '_MilvusMutationResult | Mapping[str, object]':
        await self._ensure_flushed(collection_name)
        await self._ensure_async_client()
        if self._async_client is not None:
            delete_kwargs: _MilvusDeleteKwargs = {}
            normalized_ids = _normalize_milvus_ids(ids)
            if normalized_ids is not None:
                delete_kwargs["ids"] = normalized_ids
            if expr is not None:
                delete_kwargs["filter"] = expr
            return cast('_MilvusMutationResult | Mapping[str, object]', await self._async_client.delete(self._collection_name(collection_name), **delete_kwargs))
        delete_expr = expr
        if delete_expr is None and ids is not None:
            if isinstance(ids, (str, int)):
                id_values = [ids]
            else:
                id_values = list(ids)
            delete_expr = f'id in [{", ".join(_milvus_expr_literal(item) or "\"\"" for item in id_values)}]'
        return cast('_MilvusMutationResult | Mapping[str, object]', await self._t(self._collection(collection_name).delete, expr=delete_expr or 'id == ""'))

    async def _milvus_collection_count(self, collection_name: str) -> int:
        rows = await self._milvus_query_rows(
            collection_name,
            expr='id != ""',
            output_fields=["count(*)"],
        )
        if rows:
            return _coerce_int(rows[0].get("count(*)", 0)) or 0
        return 0

    async def _milvus_describe_collection(self, collection_name: str) -> dict[str, object]:
        await self._ensure_async_client()
        physical_name = self._collection_name(collection_name)
        if self._async_client is not None:
            return dict(await self._async_client.describe_collection(physical_name))
        collection = self._Collection(physical_name, using=self._alias)
        return {
            "fields": [
                {
                    "name": getattr(field, "name", None),
                    "params": dict(getattr(field, "params", {}) or {}),
                }
                for field in getattr(collection.schema, "fields", [])
            ]
        }

    @staticmethod
    def _milvus_field_dim(field: '_MilvusFieldSchema | Mapping[str, object]') -> tuple[str | None, int | None]:
        if isinstance(field, Mapping):
            params = field.get("params") or field.get("type_params") or {}
            if not isinstance(params, Mapping):
                params = {}
            raw_dim = params.get("dim") or params.get("dimension")
            try:
                dim = None if raw_dim is None else int(raw_dim)
            except Exception:
                dim = None
            return cast(str | None, field.get("name") or field.get("field_name")), dim
        name = getattr(field, "name", None)
        params = getattr(field, "params", {}) or {}
        raw_dim = params.get("dim") or params.get("dimension")
        try:
            dim = None if raw_dim is None else int(raw_dim)
        except Exception:
            dim = None
        return cast(str | None, name), dim

    async def _milvus_describe_index(self, collection_name: str, field_name: str) -> dict[str, object]:
        """Return index metadata (metric_type, index_type, …) for one Milvus vector field."""
        await self._ensure_async_client()
        physical_name = self._collection_name(collection_name)
        if self._async_client is not None:
            return dict(await self._async_client.describe_index(physical_name, field_name))
        # Sync fallback: iterate Collection.indexes
        coll = self._Collection(physical_name, using=self._alias)
        indexes = cast(list[_MilvusIndexInfo], await self._t(lambda: list(coll.indexes)))
        for idx in indexes:
            if getattr(idx, "field_name", None) == field_name:
                return dict(getattr(idx, "params", {}) or {})
        return {}

    @staticmethod
    def _milvus_hit_value(hit: '_MilvusHit | Mapping[str, object]', field_name: str) -> object:
        if isinstance(hit, Mapping):
            entity = hit.get("entity")
            if isinstance(entity, Mapping) and field_name in entity:
                return entity.get(field_name)
            return hit.get(field_name)
        entity = getattr(hit, "entity", None)
        getter = getattr(entity, "get", None)
        if callable(getter):
            value = getter(field_name)
            if value is not None:
                return value
        return getattr(hit, field_name, None)

    @classmethod
    def _milvus_hit_id(cls, hit: '_MilvusHit | Mapping[str, object]') -> str | None:
        raw_id = cls._milvus_hit_value(hit, "id")
        if raw_id in (None, ""):
            raw_id = cls._milvus_hit_value(hit, "pk")
        return None if raw_id is None else str(raw_id)

    @classmethod
    def _milvus_hit_score(cls, hit: '_MilvusHit | Mapping[str, object]') -> float | None:
        raw_score = cls._milvus_hit_value(hit, "score")
        if raw_score is None:
            raw_score = cls._milvus_hit_value(hit, "distance")
        return _coerce_float(raw_score)

    async def _payloads_for_query_expr(
        self,
        collection_name: str,
        *,
        expr: str,
        output_fields: Sequence[str],
        limit: int | None = None,
        offset: int = 0,
    ) -> list[VectorPayload]:
        rows = await self._milvus_query_rows(
            collection_name,
            expr=expr,
            output_fields=output_fields,
            limit=limit,
            offset=offset,
        )
        payloads: list[VectorPayload] = []
        for row in rows:
            expire_at = _coerce_float(row.get("_expire_at"))
            payload = self._reconstruct_payload(collection_name, row)
            if expire_at is not None and expire_at > 0 and expire_at <= _now_ts():
                await self.delete(collection_name, str(payload.get("id")))
                continue
            payloads.append(payload)
        return payloads

    async def _bounded_filtered_payloads(
        self,
        collection_name: str,
        *,
        output_fields: Sequence[str],
        query: VectorQuery,
        limit: int | None,
        offset: int,
    ) -> list[VectorPayload]:
        if limit is None:
            raise ValueError(
                "Milvus fallback filtering requires an explicit limit when native filter pushdown is unavailable."
            )
        target = int(limit) + int(offset)
        scan_cap = max(256, target * 4)
        page_size = min(256, scan_cap)
        scanned = 0
        query_offset = 0
        matched: list[VectorPayload] = []
        while scanned < scan_cap and len(matched) < target:
            batch_size = min(page_size, scan_cap - scanned)
            rows = await self._milvus_query_rows(
                collection_name,
                expr='id != ""',
                output_fields=output_fields,
                limit=batch_size,
                offset=query_offset,
            )
            if not rows:
                break
            query_offset += len(rows)
            scanned += len(rows)
            for row in rows:
                expire_at = _coerce_float(row.get("_expire_at"))
                payload = self._reconstruct_payload(collection_name, row)
                if expire_at is not None and expire_at > 0 and expire_at <= _now_ts():
                    await self.delete(collection_name, str(payload.get("id")))
                    continue
                if _match_query_or_expr(payload, query):
                    matched.append(payload)
                    if len(matched) >= target:
                        break
            if len(rows) < batch_size:
                break
        if len(matched) < target and scanned >= scan_cap:
            raise ValueError(
                "Milvus query exceeded the bounded fallback scan window; refine the query or use a backend with native filter support."
            )
        return matched[offset:offset + int(limit)]

    # ── native-type helpers ───────────────────────────────────────────────

    def _milvus_dtype_for_annotation(self, annotation: object, field_info: '_PydanticFieldInfo | None' = None) -> 'tuple[_MilvusDataType, _MilvusFieldSchemaKwargs]':
        """Map a Python type annotation to ``(DataType, extra_kwargs)`` for a
        :class:`FieldSchema`.

        Simple non-optional primitives get native Milvus columns; optional
        primitives and complex types use ``JSON`` (which natively stores
        ``null``).
        """
        DT = self._DataType
        inner, is_optional = _unwrap_optional(annotation)
        if is_optional:
            return DT.JSON, {}
        if inner is bool:
            return DT.BOOL, {}
        if inner is int:
            return DT.INT64, {}
        if inner is float:
            return DT.DOUBLE, {}
        if inner is str:
            max_len = 65535
            if field_info is not None:
                import annotated_types as _at
                for m in getattr(field_info, "metadata", ()):
                    if isinstance(m, _at.MaxLen):
                        max_len = m.max_length
                        break
            return DT.VARCHAR, {"max_length": max_len}
        return DT.JSON, {}

    def _output_fields_for_read(self, collection: str) -> list[str]:
        """Return output field names for queries."""
        scalar = self._scalar_fields.get(collection, [])
        vector = list((self._vector_fields.get(collection) or {}).keys())
        out = ["id"] + [self._db_field_name(collection, f) for f in scalar + vector]
        # Only request the native ``_expire_at`` column when it actually exists
        # in the physical schema. For sidecar-tracked collections the Milvus
        # row has no such field — requesting it would raise.
        if self._get_sidecar(collection) is None:
            out.append("_expire_at")
        return out

    def _selected_output_fields_for_read(
        self,
        collection: str,
        *,
        fields: Sequence[str],
        query: VectorQuery | None = None,
        include_query_roots: bool = False,
    ) -> list[str]:
        output_fields: list[str] = []
        seen: set[str] = set()

        def _append_field(name: str) -> None:
            db_name = self._db_field_name(collection, name)
            if db_name in seen:
                return
            output_fields.append(db_name)
            seen.add(db_name)

        _append_field("id")

        available = set(self._scalar_fields.get(collection, [])) | set(self._vector_fields.get(collection, {}).keys())
        for root in _selected_field_roots(fields):
            if root in {"id", "_id"}:
                continue
            if available and root not in available:
                continue
            _append_field(root)

        if include_query_roots and query:
            for raw_key in query.keys():
                validated = _validate_selected_field_name(str(raw_key or ""))
                if validated in {"id", "_id"}:
                    continue
                root = validated.split(".", 1)[0]
                if available and root not in available:
                    continue
                _append_field(root)

        # Sidecar collections have no native ``_expire_at`` column; the
        # inline expire check in callers degrades to a no-op when the field
        # is absent, and cleanup catches expired rows on its next pass.
        if self._get_sidecar(collection) is None:
            _append_field("_expire_at")
        return output_fields

    def _reconstruct_payload(
        self,
        collection: str,
        row: VectorPayload,
        *,
        object_id: str | None = None,
    ) -> VectorPayload:
        """Build a model-compatible payload dict from a Milvus row."""
        resolved_id = row.get("id") or object_id
        payload: VectorPayload = {"id": resolved_id}
        for f in self._scalar_fields.get(collection, []):
            db_f = self._db_field_name(collection, f)
            if db_f in row:
                payload[f] = row[db_f]
        for f in self._vector_fields.get(collection, {}):
            db_f = self._db_field_name(collection, f)
            if db_f in row:
                payload[f] = row[db_f]
        meta_fields = {"_expire_at", "_accessed_at"}
        mapping = self._field_name_mappings.get(collection, {})
        reverse_mapping = {db_name: py_name for py_name, db_name in mapping.items()}
        for db_f, value in row.items():
            if db_f in meta_fields or db_f in payload:
                continue
            logical_name = reverse_mapping.get(db_f, db_f)
            payload[logical_name] = value
        return payload

    def _build_milvus_query_expr(
        self,
        collection: str,
        query: VectorQuery | None,
    ) -> str | None:
        if not query:
            return ""

        available_scalar = set(self._scalar_fields.get(collection, []))
        expression = _query_to_expression(query)
        if expression is None:
            return None
        mapping = self._field_name_mappings.get(collection, {}) or None
        return _milvus_expression_to_filter(expression, available_scalar=available_scalar, field_name_map=mapping)

    @staticmethod
    async def _t(fn: 'Callable[..., _R]', *args: object, **kwargs: object) -> '_R':
        """Run a synchronous PyMilvus call in a thread pool to avoid blocking the event loop."""
        if kwargs:
            return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))
        return await asyncio.to_thread(fn, *args)

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        if not self._started:
            self.start()
        self._register_model(model_cls)
        logical_name = model_cls.CollectionName
        collection_name = self._collection_name(logical_name)
        new_vector_fields: dict[str, int] = self._vector_fields.get(logical_name, {})

        with nullcontext():
            if await self._milvus_has_collection(logical_name):
                try:
                    existing = await self._milvus_describe_collection(logical_name)
                    raw_existing_fields = existing.get("fields", []) if isinstance(existing, Mapping) else []
                    existing_fields_seq = raw_existing_fields if isinstance(raw_existing_fields, Sequence) and not isinstance(raw_existing_fields, (str, bytes, bytearray)) else []
                    # All field names declared in the physical schema. Used both
                    # for vector dim reconciliation below and for detecting
                    # whether ``_expire_at`` / ``_accessed_at`` are present —
                    # if not, this collection was created externally and we
                    # must route expire / accessed_at metadata through the
                    # KV-backed sidecar.
                    existing_field_names: set[str] = set()
                    for _f in existing_fields_seq:
                        if isinstance(_f, Mapping):
                            _name = _f.get("name") or _f.get("field_name")
                        else:
                            _name = getattr(_f, "name", None)
                        if _name is not None:
                            existing_field_names.add(str(_name))
                    if (
                        "_expire_at" not in existing_field_names
                        or "_accessed_at" not in existing_field_names
                    ):
                        self._register_sidecar(logical_name)
                    existing_fields = {
                        field_name: dim
                        for field_name, dim in (self._milvus_field_dim(field) for field in existing_fields_seq)
                        if field_name is not None and dim is not None
                    }
                    for field_name, new_dim in new_vector_fields.items():
                        db_fname = self._db_field_name(logical_name, field_name)
                        old_dim = existing_fields.get(db_fname)
                        if old_dim is None:
                            _logger.warning(
                                "New vector field '%s' detected for collection '%s'. "
                                "Milvus requires drop_collection() + re-create to add new fields.",
                                db_fname, logical_name,
                            )
                            continue
                        # ── dim ──
                        if int(old_dim) != int(new_dim):
                            _logger.warning(
                                "Vector field '%s' dim mismatch in collection '%s': "
                                "model=%d, db=%d. Aligning model to DB. "
                                "Drop and re-create to apply model changes.",
                                field_name, logical_name, new_dim, old_dim,
                            )
                            self._align_vector_field_to_db(logical_name, field_name, db_dim=int(old_dim))
                        # ── metric_type & algorithm (from Milvus index info) ──
                        try:
                            index_info = await self._milvus_describe_index(logical_name, db_fname)
                            db_metric_raw = str(index_info.get("metric_type") or "").upper()
                            db_algo_raw = str(index_info.get("index_type") or "").upper()
                            model_metric = str(self._get_field_metric(logical_name, field_name)).upper()
                            model_algo = str(self._get_field_algorithm(logical_name, field_name, default="AUTOINDEX")).upper()
                            if db_metric_raw and db_metric_raw != model_metric:
                                _logger.warning(
                                    "Vector field '%s' metric_type mismatch in collection '%s': "
                                    "model=%s, db=%s. Aligning model to DB.",
                                    field_name, logical_name, model_metric, db_metric_raw,
                                )
                                if db_metric_raw in _VALID_METRIC_TYPES:
                                    self._align_vector_field_to_db(
                                        logical_name, field_name,
                                        db_metric=cast(MetricType, db_metric_raw),
                                    )
                            if db_algo_raw and db_algo_raw != model_algo:
                                _logger.warning(
                                    "Vector field '%s' algorithm mismatch in collection '%s': "
                                    "model=%s, db=%s. Aligning model to DB.",
                                    field_name, logical_name, model_algo, db_algo_raw,
                                )
                                if db_algo_raw in _VALID_VECTOR_INDEX_ALGORITHMS:
                                    self._align_vector_field_to_db(
                                        logical_name, field_name,
                                        db_algorithm=cast(VectorIndexAlgorithm, db_algo_raw),
                                    )
                        except Exception as exc:
                            _logger.debug(
                                "Could not read index info for '%s.%s': %s",
                                logical_name, field_name, exc,
                            )
                except Exception as exc:
                    _logger.debug(
                        "Could not reconcile existing Milvus collection '%s': %s",
                        logical_name, exc,
                    )
                self._mark_collection_bootstrapped(logical_name)
                return

            DT = self._DataType
            _meta = {"id", "_id"}
            no_expire_field = bool(getattr(model_cls, '__NoExpireField__', False))
            if no_expire_field:
                # Model owner has explicitly forbidden us from declaring
                # ``_expire_at`` / ``_accessed_at`` schema fields. Route those
                # metadata through the KV sidecar instead.
                self._register_sidecar(logical_name)
            if self._has_async_client():
                schema = self._AsyncMilvusClient.create_schema(
                    auto_id=False,
                    enable_dynamic_field=True,
                    description=f"Framework vector collection {logical_name}",
                )
                schema.add_field("id", DT.VARCHAR, is_primary=True, max_length=64)
                if not no_expire_field:
                    schema.add_field("_expire_at", DT.DOUBLE)
                    schema.add_field("_accessed_at", DT.DOUBLE)
                for field_name, field_info in model_cls.model_fields.items():
                    if field_name in _meta or field_name in new_vector_fields:
                        continue
                    if _is_storage_excluded(field_info):
                        continue
                    dtype, extra_kw = self._milvus_dtype_for_annotation(field_info.annotation, field_info)
                    schema.add_field(self._db_field_name(logical_name, field_name), dtype, **extra_kw)
                for field_name, dim in new_vector_fields.items():
                    schema.add_field(self._db_field_name(logical_name, field_name), DT.FLOAT_VECTOR, dim=dim)

                index_params = self._AsyncMilvusClient.prepare_index_params()
                for field_name in new_vector_fields:
                    index_params.add_index(
                        self._db_field_name(logical_name, field_name),
                        index_type=self._get_field_algorithm(logical_name, field_name, default="AUTOINDEX"),
                        metric_type=self._get_field_metric(logical_name, field_name),
                        params={},
                    )
                await self._ensure_async_client()
                await self._async_client.create_collection( # type: ignore
                    collection_name,
                    schema=schema,
                    index_params=index_params,
                    consistency_level="Session",
                )
                await self._milvus_load_collection(logical_name)
                self._mark_collection_bootstrapped(logical_name)
                return

            fields = [
                self._FieldSchema(name="id", dtype=DT.VARCHAR, is_primary=True, max_length=64),
            ]
            if not no_expire_field:
                fields.append(self._FieldSchema(name="_expire_at", dtype=DT.DOUBLE))
                fields.append(self._FieldSchema(name="_accessed_at", dtype=DT.DOUBLE))
            for field_name, field_info in model_cls.model_fields.items():
                if field_name in _meta or field_name in new_vector_fields:
                    continue
                if _is_storage_excluded(field_info):
                    continue
                dtype, extra_kw = self._milvus_dtype_for_annotation(field_info.annotation, field_info)
                fields.append(self._FieldSchema(name=self._db_field_name(logical_name, field_name), dtype=dtype, **extra_kw))
            for field_name, dim in new_vector_fields.items():
                fields.append(self._FieldSchema(name=self._db_field_name(logical_name, field_name), dtype=DT.FLOAT_VECTOR, dim=dim))
            schema = self._CollectionSchema(
                fields=fields,
                enable_dynamic_field=True,
                description=f"Framework vector collection {logical_name}",
            )
            collection = self._Collection(name=collection_name, schema=schema, using=self._alias, consistency_level="Session")
            for field_name in new_vector_fields:
                await self._t(
                    collection.create_index,
                    field_name=self._db_field_name(logical_name, field_name),
                    index_params={
                        "index_type": self._get_field_algorithm(logical_name, field_name, default="AUTOINDEX"),
                        "metric_type": self._get_field_metric(logical_name, field_name),
                        "params": {},
                    },
                )
            await self._milvus_load_collection(logical_name)
            self._mark_collection_bootstrapped(logical_name)

    async def drop_collection(self, collection: str | type[ORMModel]) -> None:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        if await self._milvus_has_collection(collection):
            await self._milvus_drop_collection(collection)
        self._collection_models.pop(collection, None)
        self._vector_fields.pop(collection, None)
        self._vector_field_metrics.pop(collection, None)
        self._vector_field_algorithms.pop(collection, None)
        self._scalar_fields.pop(collection, None)
        self._loaded_collections.discard(collection)

    async def set(self, value: ORMModel | VectorPayloadLike, *, collection: str | type[ORMModel] | None = None, expire: float | int | None = None) -> str:  # type: ignore[override]
        return await super().set(value, collection=collection, expire=expire)

    async def raw_set(
        self,
        collection: str | type[ORMModel],
        payload: VectorPayloadLike,
        *,
        expire: float | int | None = None,
    ) -> str:  # type: ignore[override]
        if not self._started:
            self.start()
        collection_name = self._resolve_collection(collection)
        if isinstance(collection, type) and issubclass(collection, ORMModel):
            await self.ensure_collection(collection)
        elif collection_name not in self._vector_fields:
            raise ValueError(f"Collection `{collection_name}` is not registered. Call create_collection() with ORMModel first.")
        await self._ensure_collection_loaded(collection_name)
        collection_name, payload, _ = self._normalize_value(payload, collection=collection_name)
        object_id = str(payload["id"])

        sidecar = self._get_sidecar(collection_name)
        normalized_expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        accessed_at = _now_ts()

        data: VectorPayload = {"id": object_id}
        if sidecar is None:
            data["_expire_at"] = normalized_expire_at or 0.0
            data["_accessed_at"] = accessed_at
        for field_name in self._scalar_fields.get(collection_name, []):
            db_name = self._db_field_name(collection_name, field_name)
            data[db_name] = self._milvus_scalar_value_for_write(collection_name, field_name, payload.get(field_name))
        for field_name in self._vector_fields[collection_name]:
            vector = payload.get(field_name)
            if not isinstance(vector, list):
                raise ValueError(f"Vector field `{field_name}` must be a list[float].")
            db_name = self._db_field_name(collection_name, field_name)
            data[db_name] = vector
        await self._milvus_upsert(collection_name, data)
        self._mark_flush_pending(collection_name)
        if sidecar is not None:
            await sidecar.upsert(
                object_id,
                expire_at=normalized_expire_at,
                accessed_at=accessed_at,
            )
        return object_id

    async def set_many(
        self,
        values: Sequence[ORMModel | VectorPayloadLike],
        *,
        collection: str | type[ORMModel] | None = None,
        expire: float | int | None = None,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []
        if not self._started:
            self.start()

        collection_resolved = self._resolve_collection(collection) if collection is not None else None
        payloads: list[VectorPayload] = []
        collection_name: str | None = None
        model_cls: type[ORMModel] | None = None
        for value in batch:
            current_collection, payload, current_model_cls = self._normalize_value(value, collection=collection_resolved)
            if collection_name is None:
                collection_name = current_collection
            elif collection_name != current_collection:
                raise ValueError('VectorClient.set_many() requires all values to target the same collection.')
            if model_cls is None and current_model_cls is not None:
                model_cls = current_model_cls
            payloads.append(payload)

        assert collection_name is not None
        if model_cls is not None:
            await self.ensure_collection(model_cls)
        elif collection_name not in self._vector_fields:
            raise ValueError(f"Collection `{collection_name}` is not registered. Call create_collection() with ORMModel first.")
        await self._ensure_collection_loaded(collection_name)

        sidecar = self._get_sidecar(collection_name)
        normalized_expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        expire_at = normalized_expire_at or 0.0
        accessed_at = _now_ts()
        rows: list[VectorPayload] = []
        object_ids: list[str] = []
        for payload in payloads:
            object_id = str(payload["id"])
            object_ids.append(object_id)

            data: VectorPayload = {"id": object_id}
            if sidecar is None:
                data["_expire_at"] = expire_at
                data["_accessed_at"] = accessed_at
            for field_name in self._scalar_fields.get(collection_name, []):
                db_name = self._db_field_name(collection_name, field_name)
                data[db_name] = self._milvus_scalar_value_for_write(collection_name, field_name, payload.get(field_name))
            for field_name in self._vector_fields[collection_name]:
                vector = payload.get(field_name)
                if not isinstance(vector, list):
                    raise ValueError(f"Vector field `{field_name}` must be a list[float].")
                db_name = self._db_field_name(collection_name, field_name)
                data[db_name] = vector
            rows.append(data)

        await self._milvus_upsert_many(collection_name, rows)
        self._mark_flush_pending(collection_name)
        if sidecar is not None:
            for oid in object_ids:
                await sidecar.upsert(
                    oid,
                    expire_at=normalized_expire_at,
                    accessed_at=accessed_at,
                )
        return object_ids

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[True] = True) -> T | None: ...

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[False]) -> VectorPayload | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[False]) -> VectorPayload | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[False]) -> VectorPayload | None: ...

    async def get(self, collection: str | type[ORMModel], object_id: str, *, as_model: bool = True) -> HydratedVectorDocument | None:  # type: ignore[override]
        return await super().get(collection, object_id, as_model=as_model)

    async def raw_get(self, collection: str | type[ORMModel], object_id: str) -> VectorPayload | None:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        if not self._started:
            self.start()
        await self._ensure_collection_loaded(collection)
        safe_id = _sanitize_milvus_expr_value(object_id)
        output_fields = self._output_fields_for_read(collection)
        rows = await self._milvus_query_rows(collection, expr=f'id == "{safe_id}"', output_fields=output_fields, limit=1)
        if not rows:
            return None
        row = rows[0]
        expire_at = _coerce_float(row.get("_expire_at"))
        if expire_at is not None and expire_at > 0 and expire_at <= _now_ts():
            await self.delete(collection, object_id)
            return None
        return self._reconstruct_payload(collection, row, object_id=object_id)

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @overload
    def search(self, collection: str, query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: str, query: VectorQuery | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    async def search(self, collection: str | type[ORMModel], query: VectorQuery | Any | None = None, *, limit: int | None = None, offset: int = 0, as_model: bool = True) -> AsyncGenerator[HydratedVectorDocument, None]:  # type: ignore[override]
        async for item in super().search(collection, query=query, limit=limit, offset=offset, as_model=as_model):
            yield item

    async def raw_query(
        self,
        collection: str | type[ORMModel],
        query: VectorQuery | Any | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[VectorPayload, None]:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        if not self._started:
            self.start()
        await self._ensure_collection_loaded(collection)
        output_fields = self._output_fields_for_read(collection)
        pushed_expr = self._build_milvus_query_expr(collection, query)
        if query and pushed_expr is None:
            payloads = await self._bounded_filtered_payloads(
                collection,
                output_fields=output_fields,
                query=query,
                limit=limit,
                offset=offset,
            )
        else:
            payloads = await self._payloads_for_query_expr(
                collection,
                expr=pushed_expr or 'id != ""',
                output_fields=output_fields,
                limit=limit,
                offset=offset,
            )
        for payload in payloads:
            yield payload

    async def selected_search(
        self,
        collection: str | type[ORMModel],
        *,
        fields: Sequence[str],
        query: VectorQuery | Any | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[VectorPayload, None]:
        collection = self._resolve_collection(collection)
        if not self._started:
            self.start()
        await self._ensure_collection_loaded(collection)

        normalized_fields = _normalize_selected_fields(fields)
        pushed_expr = self._build_milvus_query_expr(collection, query)
        include_query_roots = pushed_expr is None and bool(query)
        output_fields = self._selected_output_fields_for_read(
            collection,
            fields=normalized_fields,
            query=query,
            include_query_roots=include_query_roots,
        )

        if query and pushed_expr is None:
            payloads = await self._bounded_filtered_payloads(
                collection,
                output_fields=output_fields,
                query=query,
                limit=limit,
                offset=offset,
            )
        else:
            payloads = await self._payloads_for_query_expr(
                collection,
                expr=pushed_expr or 'id != ""',
                output_fields=output_fields,
                limit=limit,
                offset=offset,
            )
        for payload in payloads:
            yield _project_selected_payload(payload, normalized_fields)

    async def selected_search_by_id(
        self,
        collection: str | type[ORMModel],
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> VectorPayload | None:
        collection = self._resolve_collection(collection)
        if not self._started:
            self.start()
        await self._ensure_collection_loaded(collection)

        normalized_fields = _normalize_selected_fields(fields)
        output_fields = self._selected_output_fields_for_read(collection, fields=normalized_fields)
        safe_id = _sanitize_milvus_expr_value(object_id)
        rows = await self._milvus_query_rows(collection, expr=f'id == "{safe_id}"', output_fields=output_fields, limit=1)
        if not rows:
            return None
        row = rows[0]
        expire_at = _coerce_float(row.get("_expire_at"))
        if expire_at is not None and expire_at > 0 and expire_at <= _now_ts():
            await self.delete(collection, object_id)
            return None
        payload = self._reconstruct_payload(collection, row, object_id=object_id)
        return _project_selected_payload(payload, normalized_fields)

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: Literal[False]) -> AsyncGenerator[VectorPayload, None]: ...

    async def search_vector(self, collection: str | type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: VectorQuery | None = None, as_model: bool = True) -> AsyncGenerator[HydratedVectorDocument, None]:  # type: ignore[override]
        if not self._started:
            self.start()
        collection, field_name, query_vector = await self._resolve_search_vector(collection, vector, field=field)
        await self._ensure_collection_loaded(collection)
        output_fields = self._output_fields_for_read(collection)
        db_anns_field = self._db_field_name(collection, field_name)
        rows = await self._milvus_search_rows(
            collection,
            data=[query_vector],
            anns_field=db_anns_field,
            limit=limit,
            output_fields=output_fields,
        )
        if not rows:
            return
        sidecar = self._get_sidecar(collection)
        for hit in rows[0]:
            row_data = {k: self._milvus_hit_value(hit, k) for k in output_fields}
            row_data["id"] = self._milvus_hit_id(hit)
            payload = self._reconstruct_payload(collection, row_data)
            score = self._milvus_hit_score(hit)
            if score is not None:
                payload["_score"] = score
            if sidecar is None:
                expire_at = _coerce_float(row_data.get("_expire_at"))
            else:
                expire_at = await sidecar.get_expire(str(payload.get("id")))
            if expire_at is not None and expire_at > 0 and expire_at <= _now_ts():
                await self.delete(collection, str(payload.get("id")))
                continue
            if not _match_query_or_expr(payload, query):
                continue
            yield await self._hydrate_with_foreign(collection, payload, as_model=as_model)

    async def delete(self, collection: str | type[ORMModel], object_id: str) -> bool:  # type: ignore[override]
        return await super().delete(collection, object_id)

    async def raw_delete(self, collection: str | type[ORMModel], object_id: str) -> bool:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        if not self._started:
            self.start()
        await self._ensure_collection_loaded(collection)
        result = await self._milvus_delete(collection, ids=[str(object_id)])
        deleted_count = getattr(result, "delete_count", None)
        if deleted_count is None and isinstance(result, dict):
            deleted_count = result.get("delete_count", 0)
        sidecar = self._get_sidecar(collection)
        if sidecar is not None:
            await sidecar.delete(str(object_id))
        return bool(deleted_count)

    async def set_expire(self, collection: str | type[ORMModel], object_id: str, expire: float | int | None) -> bool:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        sidecar = self._get_sidecar(collection)
        if sidecar is not None:
            await self._ensure_collection_loaded(collection)
            safe_id = _sanitize_milvus_expr_value(str(object_id))
            row = await self._milvus_query_rows(
                collection, expr=f'id == "{safe_id}"', output_fields=["id"], limit=1,
            )
            if not row:
                return False
            await sidecar.upsert(
                str(object_id),
                expire_at=_normalize_expire_at(expire),
                accessed_at=_now_ts(),
            )
            return True
        current = await self.get(collection, object_id, as_model=False)
        if current is None:
            return False
        await self.set(current, collection=collection, expire=expire)
        return True

    async def get_expire(self, collection: str | type[ORMModel], object_id: str) -> float | None:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        await self._ensure_collection_loaded(collection)
        sidecar = self._get_sidecar(collection)
        if sidecar is not None:
            raw_expire = await sidecar.get_expire(str(object_id))
        else:
            safe_id = _sanitize_milvus_expr_value(object_id)
            row = await self._milvus_query_rows(collection, expr=f'id == "{safe_id}"', output_fields=["_expire_at"], limit=1)
            if not row:
                return None
            raw_expire = row[0].get("_expire_at")
        expire_at = _coerce_float(raw_expire)
        if expire_at is None or expire_at == 0.0:
            return None  # no expiry set
        ttl = _ttl_from_expire_at(expire_at)
        if ttl == 0.0:
            await self.delete(collection, object_id)
        return ttl

    async def collection_count(self, collection: str | type[ORMModel]) -> int:
        collection_name = self._resolve_collection(collection)
        if not self._started:
            self.start()
        await self._ensure_collection_loaded(collection_name)
        return await self._milvus_collection_count(collection_name)

    async def query_count(self, collection: str | type[ORMModel], query: VectorQuery | Any | None = None) -> int:
        collection_name = self._resolve_collection(collection)
        if not self._started:
            self.start()
        await self._ensure_collection_loaded(collection_name)
        pushed_expr = self._build_milvus_query_expr(collection_name, query)
        if query and pushed_expr is None:
            raise ValueError("Milvus query_count requires native filter pushdown support.")
        expr = pushed_expr or 'id != ""'
        rows = await self._milvus_query_rows(
            collection_name,
            expr=expr,
            output_fields=["count(*)"],
        )
        if rows:
            return _coerce_int(rows[0].get("count(*)", 0)) or 0
        return 0

    async def cleanup(self, *, force: bool = False) -> int:
        if not await self._should_cleanup_async(force=force):
            return 0
        removed = 0
        total_size = 0
        live_rows: list[tuple[str, str, int, float]] = []
        for collection in list(self._collection_models.keys()):
            await self._ensure_collection_loaded(collection)
            now = _now_ts()
            sidecar = self._get_sidecar(collection)
            if sidecar is None:
                # Push expire filter to Milvus instead of loading all rows and filtering in Python.
                expire_expr = f'_expire_at > 0 && _expire_at <= {now}'
                expired_rows = await self._milvus_query_rows(collection, expr=expire_expr, output_fields=["id"], limit=16384)
                expired_ids = [str(row.get("id", "")) for row in expired_rows]
            else:
                # Sidecar mode: the physical schema lacks `_expire_at`, so we
                # must enumerate the KV-backed metadata to find expired ids.
                expired_ids = await sidecar.list_expired(now)
            if expired_ids:
                await self._milvus_delete(collection, ids=expired_ids)
                if sidecar is not None:
                    await sidecar.delete_many(expired_ids)
                removed += len(expired_ids)
            if self._max_size is not None:
                if sidecar is None:
                    scalar = self._scalar_fields.get(collection, [])
                    out_fields = scalar + ["_expire_at", "_accessed_at"]
                    rows = await self._milvus_query_rows(collection, expr='id != ""', output_fields=out_fields, limit=16384)
                    for row in rows:
                        object_id = str(row.get("id", ""))
                        size = sum(len(str(row.get(f, "")).encode("utf-8")) for f in self._scalar_fields.get(collection, []))
                        total_size += size
                        live_rows.append((collection, object_id, size, _coerce_float(row.get("_accessed_at", 0.0)) or 0.0))
                else:
                    for object_id, entry in await sidecar.list_entries():
                        size = int(entry.get("s", 0) or 0)
                        total_size += size
                        live_rows.append((collection, object_id, size, _coerce_float(entry.get("a", 0.0)) or 0.0))
        total_count = len(live_rows)
        if self._max_size is not None and len(live_rows) > self._max_size:
            target = max(0, int(self._max_size * 0.9))
            evict_by_collection: dict[str, list[str]] = {}
            for collection, object_id, size, _ in sorted(live_rows, key=lambda item: item[3]):
                if total_count <= target:
                    break
                evict_by_collection.setdefault(collection, []).append(object_id)
                total_count -= 1
                removed += 1
            for collection, ids in evict_by_collection.items():
                await self._milvus_delete(collection, ids=ids)
                sidecar = self._get_sidecar(collection)
                if sidecar is not None:
                    await sidecar.delete_many(ids)
        await self._mark_cleanup_async()
        return removed

class _AsyncMilvusClientProxy:
    """Forward AsyncMilvusClient method calls to the MilvusLite proxy process."""

    def __init__(self, socket_path: str, db_path: Path) -> None:
        self._socket_path = socket_path
        self._db_path = db_path
        self._proxy_conn: Any = None
        self._loop_id: int | None = None

    def _get_loop_id(self) -> int | None:
        try:
            return id(asyncio.get_running_loop())
        except RuntimeError:
            return None

    async def _ensure_connected(self) -> None:
        current_loop_id = self._get_loop_id()
        if self._proxy_conn is not None and self._proxy_conn.is_connected() and self._loop_id == current_loop_id:
            return
        from .vector_milvus_lite_proxy import MilvusLiteProxyConnection
        if self._proxy_conn is not None:
            try:
                self._proxy_conn.close()
            except Exception:
                pass
        self._proxy_conn = MilvusLiteProxyConnection(self._socket_path)
        await self._proxy_conn.connect()
        self._loop_id = current_loop_id

    async def _call(self, op: str, *args: Any, **kwargs: Any) -> Any:
        await self._ensure_connected()
        try:
            return await self._proxy_conn.call(op, *args, **kwargs)
        except (ConnectionResetError, BrokenPipeError, OSError):
            from .vector_milvus_lite_proxy import ensure_milvus_lite_proxy_async
            self._proxy_conn = await ensure_milvus_lite_proxy_async(self._db_path)
            self._loop_id = self._get_loop_id()
            return await self._proxy_conn.call(op, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        async def _forwarded(*args: Any, **kwargs: Any) -> Any:
            return await self._call(f"async_client.{name}", *args, **kwargs)
        return _forwarded

    def close(self) -> None:
        if self._proxy_conn is not None:
            try:
                self._proxy_conn.close()
            except Exception:
                pass
            self._proxy_conn = None
        self._loop_id = None

class MilvusLiteVectorClient(_BaseMilvusVectorClient, type="milvus-lite"):
    def __init__(self, **kwargs: Unpack[MilvusLiteVectorClientInitParams]) -> None:
        self._db_path = Path(kwargs.get("db_path") or (_default_local_storage_root("vector") / "milvus_lite.db")).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._proxy_socket_path: str | None = None
        self._proxy_mode: bool = bool(kwargs.pop("_proxy_mode", False))
        super().__init__(**kwargs)

    def _collection_name(self, collection: str) -> str:
        """MilvusLite has no database concept; prepend namespace to avoid collisions."""
        _validate_collection_name(collection)
        return self._normalize_milvus_collection_name(f"{self._namespace}_{collection}")

    def start(self) -> Self:
        if self._started:
            return self
        if getattr(self, '_proxy_mode', False) or os.name == "nt":
            self._connect(uri=str(self._db_path))
        else:
            from .vector_milvus_lite_proxy import ensure_milvus_lite_proxy
            self._proxy_socket_path = ensure_milvus_lite_proxy(self._db_path)
            self._async_client = _AsyncMilvusClientProxy(self._proxy_socket_path, self._db_path)  # type: ignore[assignment]
        self._mark_started()
        return self

    async def _async_restore_collection_state(self) -> None:
        if getattr(self, '_proxy_mode', False):
            return
        async_client = self._async_client
        if async_client is None:
            return
        try:
            raw_collections = await async_client.list_collections()
        except Exception:
            return
        prefix = f"{self._namespace}_"
        for physical_name in raw_collections:
            if not physical_name.startswith(prefix):
                continue
            logical = physical_name[len(prefix):]
            if logical in self._vector_fields:
                continue
            try:
                info = await async_client.describe_collection(physical_name)
            except Exception:
                continue
            if not isinstance(info, dict):
                continue
            fields = info.get("fields", []) or []
            vector_fields: dict[str, int] = {}
            scalar_fields: list[str] = []
            for field in fields:
                if not isinstance(field, dict):
                    continue
                name = field.get("name") or field.get("field_name")
                dtype = str(field.get("dtype") or field.get("type") or "")
                params = field.get("params") or field.get("type_params") or {}
                if not isinstance(params, dict):
                    params = {}
                dim = params.get("dim") or params.get("dimension")
                if dim is not None or "VECTOR" in dtype.upper():
                    try:
                        vector_fields[str(name)] = int(dim or 0)
                    except Exception:
                        pass
                    continue
                if name in {"", "id", "_id", "_expire_at", "_accessed_at"}:
                    continue
                scalar_fields.append(str(name))
            if vector_fields:
                self._vector_fields[logical] = vector_fields
                self._scalar_fields[logical] = scalar_fields
                self._mark_collection_bootstrapped(logical)

    def _restore_collection_state(self) -> None:
        _run_async_in_sync(self._async_restore_collection_state)

    def close(self) -> None:
        if self._async_client is not None:
            try:
                self._async_client.close()
            except Exception:
                pass
            self._async_client = None
        self._proxy_socket_path = None
        super().close()

class PyMilvusVectorClient(_BaseMilvusVectorClient, type="milvus"):
    def __init__(self, **kwargs: Unpack[PyMilvusVectorClientInitParams]) -> None:
        self._uri = kwargs.get("uri", "http://127.0.0.1:19530")
        self._token = kwargs.get("token", None)
        self._explicit_alias = kwargs.get("alias", None)
        super().__init__(**kwargs)
        if self._explicit_alias:
            self._alias = self._explicit_alias

    def _milvus_db_name(self) -> str:
        """Sanitize namespace to a valid Milvus database name (letters, digits, underscores)."""
        raw = str(self._namespace or "default")
        sanitized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw)
        if not sanitized or not (sanitized[0].isalpha() or sanitized[0] == "_"):
            sanitized = f"ns_{sanitized}"
        return sanitized[:255]

    def start(self) -> Self:
        if self._started:
            return self
        connect_kwargs: _MilvusAsyncConnectKwargs = {"uri": self._uri}
        if self._token:
            connect_kwargs["token"] = self._token
        if self._namespace and self._namespace != "default":
            db_name = self._milvus_db_name()
            # Ensure the database exists before connecting with db_name.
            admin_connect_kwargs: _MilvusAsyncConnectKwargs = {"uri": self._uri}
            if self._token:
                admin_connect_kwargs["token"] = self._token
            self._connections.connect(alias=self._alias, **admin_connect_kwargs)
            try:
                from pymilvus import db as _milvus_db
                existing = {str(n) for n in (_milvus_db.list_database(using=self._alias) or [])}
                if db_name not in existing:
                    _milvus_db.create_database(db_name, using=self._alias)
            except Exception as exc:
                _logger.warning("Could not auto-create Milvus database %r: %s", db_name, exc)
            finally:
                try:
                    self._connections.disconnect(self._alias)
                except Exception:
                    pass
            connect_kwargs["db_name"] = db_name
        self._connect(**connect_kwargs)
        self._mark_started()
        return self


# ── metric mapping ────────────────────────────────────────────────────────────
_METRIC_TO_ANNOY: dict[str, str] = {
    "COSINE": "angular",
    "L2": "euclidean",
    "EUCLIDEAN": "euclidean",
    "IP": "dot",
    "DOT": "dot",
    "MANHATTAN": "manhattan",
    "HAMMING": "hamming",
}


def _new_annoy_index(dim: int, metric: str) -> _AnnoyIndexProtocol:
    annoy_module = importlib.import_module("annoy")
    return cast(_AnnoyIndexProtocol, annoy_module.AnnoyIndex(dim, metric))

class AnnoySQLiteVectorClientInitParams(VectorClientInitParams, total=False):
    db_dir: str | Path
    n_trees: int

class _AnnoySQLiteVectorCollectionState:
    """Runtime state for one logical collection."""
    __slots__ = (
        "annoy_indexes",
        "dims",
        "item_counts",
        "id_to_int",
        "int_to_id",
        "next_int",
        "dirty",
        "version_times",
    )

    def __init__(self) -> None:
        self.annoy_indexes: dict[str, _AnnoyIndexProtocol] = {}
        self.dims: dict[str, int] = {}            # field -> dimension
        self.item_counts: dict[str, int] = {}     # field -> indexed vector count
        self.id_to_int: dict[str, int] = {}       # object_id -> int idx
        self.int_to_id: dict[int, str] = {}       # int idx -> object_id
        self.next_int: int = 0
        self.dirty: bool = False
        self.version_times: dict[str, int] = {}   # field -> last-loaded version μs

class AnnoySQLiteVectorClient(VectorClientBase, type="annoy"):
    """Vector client backed by Annoy (ANN) + SQLite (metadata).

    Each logical *collection* maps to:
    * a SQLite table ``<namespace>_<collection>`` with columns
      ``(id TEXT PK, payload_json TEXT, expire_at REAL, accessed_at REAL)``.
    * one Annoy index file per vector field, stored as
      ``<db_dir>/<namespace>_<collection>_<field>.ann``.
    """

    def __init__(self, **kwargs: Unpack[AnnoySQLiteVectorClientInitParams]) -> None:
        self._db_dir = Path(
            kwargs.get("db_dir")
            or _default_local_storage_root("vector")
        ).expanduser().resolve()
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._n_trees: int = int(kwargs.get("n_trees", 10))
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._states: dict[str, _AnnoySQLiteVectorCollectionState] = {}
        super().__init__(**kwargs)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> Self:
        if self._started:
            return self
        db_path = self._db_dir / f"{self._namespace}_meta.sqlite3"
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS _annoy_meta "
            "(key TEXT PRIMARY KEY, value TEXT)"
        )
        self._conn.commit()
        self._mark_started()
        self._restore_collection_state()
        return self

    def stop(self) -> None:
        self.close()

    def close(self) -> None:
        cleanup_task = self._cleanup_task
        self._cleanup_task = None
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
        conn = self._conn
        self._conn = None
        with self._lock:
            self._cleanup_async_locks.clear()
        self._states.clear()
        self._mark_stopped()
        if conn is None:
            return
        try:
            conn.close()
        except Exception as e:
            _logger.warning('AnnoySQLiteVectorClient.close() failed for %s: %s', self._db_dir, e)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ensure_started(self) -> sqlite3.Connection:
        if not self._started or self._conn is None:
            self.start()
        assert self._conn is not None
        return self._conn

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = (threading.get_ident(), id(asyncio.get_running_loop()))
        with self._lock:
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

    @staticmethod
    def _try_import_model(module_name: str | None, class_name: str | None) -> type[ORMModel] | None:
        if not module_name or not class_name:
            return None
        try:
            module = importlib.import_module(module_name)
            model_cls = getattr(module, class_name, None)
        except Exception:
            return None
        if isinstance(model_cls, type) and issubclass(model_cls, ORMModel):
            return model_cls
        return None

    def _collection_meta_key(self, collection: str) -> str:
        return f"collection_meta:{self._namespace}:{collection}"

    def _serialize_collection_meta(self, collection: str) -> dict[str, object]:
        model_cls = self._collection_models.get(collection)
        return {
            "namespace": self._namespace,
            "collection_name": collection,
            "vector_fields": dict(self._vector_fields.get(collection, {})),
            "vector_field_metrics": dict(self._vector_field_metrics.get(collection, {})),
            "vector_field_algorithms": dict(self._vector_field_algorithms.get(collection, {})),
            "scalar_fields": list(self._scalar_fields.get(collection, [])),
            "model_module": getattr(model_cls, "__module__", None),
            "model_name": getattr(model_cls, "__name__", None),
            "schema_json": _safe_model_schema(model_cls) if model_cls is not None else None,
        }

    def _persist_collection_meta(self, collection: str) -> None:
        conn = self._ensure_started()
        conn.execute(
            "INSERT OR REPLACE INTO _annoy_meta (key, value) VALUES (?, ?)",
            (self._collection_meta_key(collection), _json_dumps(self._serialize_collection_meta(collection))),
        )
        conn.commit()

    def _load_collection_meta(self, collection: str) -> dict[str, object] | None:
        conn = self._ensure_started()
        row = conn.execute(
            "SELECT value FROM _annoy_meta WHERE key = ?",
            (self._collection_meta_key(collection),),
        ).fetchone()
        if not row:
            return None
        try:
            payload = _json_loads(row[0])
        except Exception:
            return None
        return dict(payload) if isinstance(payload, Mapping) else None

    def _apply_collection_meta(self, meta: Mapping[str, object]) -> None:
        namespace = str(meta.get("namespace") or "")
        if namespace and namespace != self._namespace:
            return
        collection = str(meta.get("collection_name") or "").strip()
        if not collection:
            return
        raw_vector_fields = meta.get("vector_fields") or {}
        if isinstance(raw_vector_fields, Mapping):
            self._vector_fields[collection] = {
                str(name): int(dim)
                for name, dim in raw_vector_fields.items()
            }
        raw_metrics = meta.get("vector_field_metrics") or {}
        if isinstance(raw_metrics, Mapping):
            self._vector_field_metrics[collection] = {
                str(name): _coerce_metric_type(metric, self._metric_type)
                for name, metric in raw_metrics.items()
            }
        raw_algorithms = meta.get("vector_field_algorithms") or {}
        if isinstance(raw_algorithms, Mapping):
            self._vector_field_algorithms[collection] = {
                str(name): cast(VectorIndexAlgorithm, str(algorithm).upper())
                for name, algorithm in raw_algorithms.items()
                if str(algorithm).upper() in _VALID_VECTOR_INDEX_ALGORITHMS
            }
        raw_scalar_fields = meta.get("scalar_fields") or []
        if isinstance(raw_scalar_fields, Sequence) and not isinstance(raw_scalar_fields, (str, bytes, bytearray)):
            self._scalar_fields[collection] = [str(item) for item in raw_scalar_fields if str(item or "").strip()]
        model_cls = self._try_import_model(
            cast(str | None, meta.get("model_module")),
            cast(str | None, meta.get("model_name")),
        )
        if model_cls is not None:
            self._collection_models[collection] = model_cls
        self._mark_collection_bootstrapped(collection)

    def _restore_collection_state(self) -> None:
        conn = self._ensure_started()
        rows = conn.execute(
            "SELECT value FROM _annoy_meta WHERE key LIKE ?",
            (self._collection_meta_key("").rstrip("%") + "%",),
        ).fetchall()
        for row in rows:
            try:
                payload = _json_loads(row[0])
            except Exception:
                continue
            if isinstance(payload, Mapping):
                self._apply_collection_meta(payload)

    async def _load_stored_schema(self, collection: str) -> dict[str, object] | None:
        meta = self._load_collection_meta(collection)
        if meta is None:
            return None
        raw = meta.get("schema_json")
        if not raw:
            return None
        return _json_loads_dict_or_none(raw)

    def _table_name(self, collection: str) -> str:
        _validate_collection_name(collection)
        return f"{self._namespace}_{collection}".replace("-", "_")

    def _sys_table_name(self, collection: str) -> str:
        return f"_{self._table_name(collection)}_sys"

    def _annoy_path(self, collection: str, field: str) -> Path:
        return self._db_dir / f"{self._namespace}_{collection}_{field}.ann"

    def _annoy_metric_for_field(self, collection: str, field: str) -> str:
        """Annoy metric string for a specific field, respecting per-field overrides."""
        return _METRIC_TO_ANNOY.get(self._get_field_metric(collection, field).upper(), "angular")

    def _annoy_metric(self) -> str:
        """Fallback: global client-level Annoy metric."""
        return _METRIC_TO_ANNOY.get(self._metric_type.upper(), "angular")

    def _annoy_query_to_sql(
        self, query: VectorQuery, field_name_map: dict[str, str] | None = None,
    ) -> tuple[list[str], dict[str, object]]:
        """Convert a query dict to SQL conditions using json_extract on payload_json."""
        conditions: list[str] = []
        params: dict[str, object] = {}
        counter = [0]

        def _param_name() -> str:
            counter[0] += 1
            return f"_aq_{counter[0]}"

        def _field_expr(field: str) -> str:
            if field in {"id", "_id"}:
                return "d.id"
            db_field = (field_name_map or {}).get(field, field)
            return f"json_extract(d.payload_json, '$.{db_field}')"

        def _process(q: VectorQuery) -> list[str]:
            parts: list[str] = []
            for key, value in q.items():
                if key == "$or":
                    or_parts = []
                    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                        raise ValueError("$or requires a sequence of conditions")
                    for sub in value:
                        sub_parts = _process(sub)
                        if sub_parts:
                            or_parts.append(f"({' AND '.join(sub_parts)})")
                    if or_parts:
                        parts.append(f"({' OR '.join(or_parts)})")
                elif key == "$and":
                    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                        raise ValueError("$and requires a sequence of conditions")
                    for sub in value:
                        parts.extend(_process(sub))
                elif key.startswith("$"):
                    raise ValueError(f"Unsupported operator: {key}")
                elif isinstance(value, Mapping):
                    expr = _field_expr(key)
                    for op, operand in value.items():
                        pname = _param_name()
                        if op == "$eq":
                            parts.append(f"{expr} = :{pname}")
                            params[pname] = operand
                        elif op == "$ne":
                            parts.append(f"{expr} != :{pname}")
                            params[pname] = operand
                        elif op == "$gt":
                            parts.append(f"{expr} > :{pname}")
                            params[pname] = operand
                        elif op == "$gte":
                            parts.append(f"{expr} >= :{pname}")
                            params[pname] = operand
                        elif op == "$lt":
                            parts.append(f"{expr} < :{pname}")
                            params[pname] = operand
                        elif op == "$lte":
                            parts.append(f"{expr} <= :{pname}")
                            params[pname] = operand
                        elif op == "$in":
                            placeholders = []
                            for item in operand:
                                p = _param_name()
                                placeholders.append(f":{p}")
                                params[p] = item
                            parts.append(f"{expr} IN ({', '.join(placeholders)})")
                        elif op == "$nin":
                            placeholders = []
                            for item in operand:
                                p = _param_name()
                                placeholders.append(f":{p}")
                                params[p] = item
                            parts.append(f"{expr} NOT IN ({', '.join(placeholders)})")
                        else:
                            raise ValueError(f"Unsupported operator: {op}")
                else:
                    expr = _field_expr(key)
                    pname = _param_name()
                    parts.append(f"{expr} = :{pname}")
                    params[pname] = value
            return parts

        conditions = _process(query)
        return conditions, params

    def _ensure_table(self, collection: str) -> None:
        tbl = self._table_name(collection)
        sys_tbl = self._sys_table_name(collection)
        conn = self._ensure_started()
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{tbl}" (
                id         TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{sys_tbl}" (
                id         TEXT PRIMARY KEY,
                expire_at  REAL,
                size       INTEGER NOT NULL,
                accessed_at REAL NOT NULL
            )
        """)
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{tbl}_sys_expire" ON "{sys_tbl}" (expire_at)'
        )
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{tbl}_sys_access" ON "{sys_tbl}" (accessed_at)'
        )
        conn.commit()

    def _get_state(self, collection: str) -> _AnnoySQLiteVectorCollectionState:
        if collection not in self._states:
            self._states[collection] = _AnnoySQLiteVectorCollectionState()
        return self._states[collection]

    # ── version management (cross-process) ────────────────────────────────────

    def _get_version_time(self, collection: str, field: str) -> int:
        """Return the latest index version timestamp (μs) for *collection*/*field*."""
        conn = self._ensure_started()
        key = f"vt:{collection}:{field}"
        try:
            row = conn.execute(
                "SELECT value FROM _annoy_meta WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row:
            return int(row[0])
        # Fallback: file mtime
        annoy_path = self._annoy_path(collection, field)
        if annoy_path.exists():
            return int(annoy_path.stat().st_mtime_ns // 1000)
        return 0

    def _set_version_time(self, collection: str, field: str, ts: int) -> None:
        conn = self._ensure_started()
        key = f"vt:{collection}:{field}"
        conn.execute(
            "INSERT OR REPLACE INTO _annoy_meta (key, value) VALUES (?, ?)",
            (key, str(ts)),
        )

    def _save_id_mapping(self, collection: str, int_to_id: dict[int, str]) -> None:
        """Persist int→object_id mapping so other processes can reload without rebuilding."""
        conn = self._ensure_started()
        key = f"idmap:{collection}"
        max_id = max(int_to_id.keys()) if int_to_id else -1
        id_list = [int_to_id.get(i, "") for i in range(max_id + 1)]
        conn.execute(
            "INSERT OR REPLACE INTO _annoy_meta (key, value) VALUES (?, ?)",
            (key, _json_dumps(id_list)),
        )

    def _load_id_mapping(self, collection: str) -> tuple[dict[str, int], dict[int, str], int]:
        """Load persisted int?object_id mapping. Returns (id_to_int, int_to_id, next_int)."""
        conn = self._ensure_started()
        key = f"idmap:{collection}"
        try:
            row = conn.execute(
                "SELECT value FROM _annoy_meta WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.OperationalError:
            return {}, {}, 0
        if not row:
            return {}, {}, 0
        id_list = _json_loads_str_list(row[0])
        id_to_int: dict[str, int] = {}
        int_to_id: dict[int, str] = {}
        for i, doc_id in enumerate(id_list):
            if doc_id:
                id_to_int[doc_id] = i
                int_to_id[i] = doc_id
        return id_to_int, int_to_id, len(id_list)

    # ── Annoy index I/O ──────────────────────────────────────────────────────

    def _load_annoy_index(self, collection: str, field: str, dim: int) -> _AnnoyIndexProtocol:
        """Load an Annoy index from disk if it exists; else return a fresh one."""
        idx = _new_annoy_index(dim, self._annoy_metric_for_field(collection, field))
        annoy_path = self._annoy_path(collection, field)
        if annoy_path.exists():
            idx.load(str(annoy_path))
        return idx

    def _rebuild_annoy_indexes(self, collection: str) -> None:
        """Rebuild all Annoy indexes for *collection* from SQLite data.

        Expired rows are skipped (expire optimisation). The resulting int?id
        mapping is persisted so that other processes can reload from disk
        without a full rebuild.
        """
        state = self._get_state(collection)
        vec_fields = self._vector_fields.get(collection, {})
        if not vec_fields:
            return

        with nullcontext():
            conn = self._ensure_started()
            tbl = self._table_name(collection)
            sys_tbl = self._sys_table_name(collection)
            ts = _now_ts()

            # Read data, skip expired rows, deterministic order for stable IDs
            rows = conn.execute(
                f'SELECT d.id, d.payload_json FROM "{tbl}" d '
                f'LEFT JOIN "{sys_tbl}" s ON d.id = s.id '
                f'WHERE s.expire_at IS NULL OR s.expire_at > ? '
                f'ORDER BY d.id',
                (ts,),
            ).fetchall()

            # Reset id mapping
            state.id_to_int.clear()
            state.int_to_id.clear()
            state.next_int = 0
            state.item_counts.clear()

            new_indexes: dict[str, _AnnoyIndexProtocol] = {}
            for fname, dim in vec_fields.items():
                new_indexes[fname] = _new_annoy_index(dim, self._annoy_metric_for_field(collection, fname))
                state.item_counts[fname] = 0

            for doc_id, payload_json in rows:
                payload = _json_loads_dict_or_none(payload_json)
                if payload is None:
                    continue
                int_id = state.next_int
                state.id_to_int[doc_id] = int_id
                state.int_to_id[int_id] = doc_id
                state.next_int += 1
                for fname, dim in vec_fields.items():
                    vec = payload.get(fname)
                    if isinstance(vec, list) and len(vec) == dim:
                        new_indexes[fname].add_item(int_id, vec)
                        state.item_counts[fname] += 1

            version_ts = int(time.time() * 1_000_000)  # μs timestamp

            for fname, idx in new_indexes.items():
                annoy_path = self._annoy_path(collection, fname)
                if state.item_counts.get(fname, 0) <= 0:
                    if annoy_path.exists():
                        try:
                            os.remove(annoy_path)
                        except OSError:
                            pass
                    state.annoy_indexes[fname] = idx
                    state.dims[fname] = vec_fields[fname]
                    self._set_version_time(collection, fname, version_ts)
                    state.version_times[fname] = version_ts
                    continue
                idx.build(self._n_trees)
                # Atomic save: temp → rename (safe on POSIX; best-effort on Windows)
                tmp_path = annoy_path.with_suffix(".ann.tmp")
                try:
                    idx.save(str(tmp_path))
                    os.replace(str(tmp_path), str(annoy_path))
                except Exception:
                    try:
                        idx.save(str(annoy_path))
                    except Exception:
                        pass  # in-memory only fallback
                    finally:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                state.annoy_indexes[fname] = idx
                state.dims[fname] = vec_fields[fname]
                self._set_version_time(collection, fname, version_ts)
                state.version_times[fname] = version_ts

            # Persist ID mapping + commit all meta updates
            self._save_id_mapping(collection, state.int_to_id)
            conn.commit()

        state.dirty = False

    def _reload_annoy_indexes(self, collection: str) -> bool:
        """Reload Annoy indexes from disk (built by another process).

        Reconstructs the int?id mapping from the persisted metadata table.
        Returns *True* on success, *False* if a full rebuild is needed.
        """
        state = self._get_state(collection)
        vec_fields = self._vector_fields.get(collection, {})
        if not vec_fields:
            return False

        id_to_int, int_to_id, next_int = self._load_id_mapping(collection)
        if not int_to_id:
            return False  # no persisted mapping → must rebuild

        new_indexes: dict[str, _AnnoyIndexProtocol] = {}
        new_dims: dict[str, int] = {}
        new_counts: dict[str, int] = {}
        for fname, dim in vec_fields.items():
            annoy_path = self._annoy_path(collection, fname)
            if not annoy_path.exists():
                continue
            idx = _new_annoy_index(dim, self._annoy_metric_for_field(collection, fname))
            try:
                idx.load(str(annoy_path), prefault=True)
            except Exception:
                continue
            new_indexes[fname] = idx
            new_dims[fname] = dim
            new_counts[fname] = idx.get_n_items()

        if not new_indexes:
            return False  # no .ann files → must rebuild

        state.id_to_int = id_to_int
        state.int_to_id = int_to_id
        state.next_int = next_int
        state.annoy_indexes.update(new_indexes)
        state.dims.update(new_dims)
        state.item_counts.update(new_counts)

        for fname in vec_fields:
            state.version_times[fname] = self._get_version_time(collection, fname)
        state.dirty = False
        return True

    def _ensure_index(self, collection: str) -> _AnnoySQLiteVectorCollectionState:
        """Make sure in-memory Annoy indexes are loaded / rebuilt.

        * If *dirty* (this process wrote data) → full rebuild.
        * If indexes not yet loaded → try reload from disk, else rebuild.
        * If another process bumped the version → reload from disk.
        """
        state = self._get_state(collection)
        vec_fields = self._vector_fields.get(collection, {})
        if not vec_fields:
            return state

        if state.dirty:
            self._rebuild_annoy_indexes(collection)
            return state

        if not state.annoy_indexes:
            if not self._reload_annoy_indexes(collection):
                self._rebuild_annoy_indexes(collection)
            return state

        # Check for cross-process version bump
        for fname in vec_fields:
            remote_vt = self._get_version_time(collection, fname)
            local_vt = state.version_times.get(fname, 0)
            if remote_vt > local_vt:
                self._reload_annoy_indexes(collection)
                return state

        return state

    # ── abstract implementations ──────────────────────────────────────────────

    async def _drop_vector_indexes(self, collection: str, fields: list[str]) -> None:
        for field in fields:
            p = self._annoy_path(collection, field)
            for path in (p, p.with_suffix(".ann.tmp")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            # Clean up meta entries
            conn = self._ensure_started()
            try:
                conn.execute(
                    "DELETE FROM _annoy_meta WHERE key = ?",
                    (f"vt:{collection}:{field}",),
                )
                conn.commit()
            except sqlite3.OperationalError:
                pass
            state = self._get_state(collection)
            state.annoy_indexes.pop(field, None)
            state.dims.pop(field, None)
            state.item_counts.pop(field, None)
            state.version_times.pop(field, None)
            _logger.info("Dropped Annoy vector index for '%s.%s'.", collection, field)

    def _reconcile_annoy_vector_dim(self, collection: str) -> None:
        """Check existing stored vectors for dim mismatch, warn & align model."""
        conn = self._ensure_started()
        tbl = self._table_name(collection)
        try:
            row = conn.execute(f'SELECT payload_json FROM "{tbl}" LIMIT 1').fetchone()
        except Exception:
            return
        if not row:
            return
        payload = _json_loads(row[0])
        if not isinstance(payload, Mapping):
            return
        for field, model_dim in (self._vector_fields.get(collection) or {}).items():
            vec = payload.get(field)
            if isinstance(vec, (list, tuple)) and len(vec) > 0:
                db_dim = len(vec)
                if db_dim != model_dim:
                    _logger.warning(
                        "Vector field '%s' dim mismatch in Annoy/SQLite collection '%s': "
                        "model=%d, existing_data=%d. Aligning model to existing data dim.",
                        field, collection, model_dim, db_dim,
                    )
                    self._align_vector_field_to_db(collection, field, db_dim=db_dim)

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        self._ensure_started()
        self._register_model(model_cls)
        logical = model_cls.CollectionName
        self._ensure_table(logical)
        self._reconcile_annoy_vector_dim(logical)
        # Pre-build index so dims are known
        self._rebuild_annoy_indexes(logical)
        self._mark_collection_bootstrapped(logical)
        self._persist_collection_meta(logical)

    async def drop_collection(self, collection: str | type[ORMModel]) -> None:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        conn = self._ensure_started()
        tbl = self._table_name(collection)
        sys_tbl = self._sys_table_name(collection)
        conn.execute(f'DROP TABLE IF EXISTS "{sys_tbl}"')
        conn.execute(f'DROP TABLE IF EXISTS "{tbl}"')
        # Clean up annoy files + meta entries
        for fname in list(self._vector_fields.get(collection, {}).keys()):
            p = self._annoy_path(collection, fname)
            for path in (p, p.with_suffix(".ann.tmp")):
                if path.exists():
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            try:
                conn.execute(
                    "DELETE FROM _annoy_meta WHERE key = ?",
                    (f"vt:{collection}:{fname}",),
                )
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(
                "DELETE FROM _annoy_meta WHERE key = ?",
                (f"idmap:{collection}",),
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                "DELETE FROM _annoy_meta WHERE key = ?",
                (self._collection_meta_key(collection),),
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
        self._collection_models.pop(collection, None)
        self._vector_fields.pop(collection, None)
        self._vector_field_metrics.pop(collection, None)
        self._vector_field_algorithms.pop(collection, None)
        self._states.pop(collection, None)
        self._scalar_fields.pop(collection, None)
        self._forget_collection(collection)

    async def set(
        self,
        value: ORMModel | dict[str, Any],
        *,
        collection: str | type[ORMModel] | None = None,
        expire: float | int | None = None,
        _create_table: bool = True,
    ) -> str:  # type: ignore[override]
        _ = _create_table
        return await super().set(value, collection=collection, expire=expire)

    async def raw_set(
        self,
        collection: str | type[ORMModel],
        payload: VectorPayloadLike,
        *,
        expire: float | int | None = None,
    ) -> str:  # type: ignore[override]
        conn = self._ensure_started()
        coll_name = self._resolve_collection(collection)
        if isinstance(collection, type) and issubclass(collection, ORMModel):
            await self.ensure_collection(collection)
        elif coll_name not in self._vector_fields:
            raise ValueError(
                f"Collection `{coll_name}` is not registered. "
                "Call create_collection() with ORMModel first."
            )
        else:
            self._ensure_table(coll_name)
        coll_name, payload, _ = self._normalize_value(payload, collection=coll_name)

        object_id = str(payload["id"])

        # Validate vector fields
        for fname in self._vector_fields.get(coll_name, {}):
            vec = payload.get(fname)
            if not isinstance(vec, list):
                raise ValueError(f"Vector field `{fname}` must be a list[float].")

        tbl = self._table_name(coll_name)
        sys_tbl = self._sys_table_name(coll_name)
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        accessed_at = _now_ts()

        mapping = self._field_name_mappings.get(coll_name, {})
        db_payload = remap_payload_to_db(payload, mapping) if mapping else payload
        payload_json = _json_dumps(db_payload)
        with self._lock:
            conn.execute(
                f'INSERT OR REPLACE INTO "{tbl}" (id, payload_json) VALUES (?, ?)',
                (object_id, payload_json),
            )
            conn.execute(
                f'INSERT OR REPLACE INTO "{sys_tbl}" (id, expire_at, size, accessed_at) VALUES (?, ?, ?, ?)',
                (object_id, expire_at, len(payload_json.encode("utf-8")), accessed_at),
            )
            conn.commit()
            self._get_state(coll_name).dirty = True

        self._schedule_cleanup()
        return object_id

    async def set_many(
        self,
        values: Sequence[ORMModel | dict[str, Any]],
        *,
        collection: str | type[ORMModel] | None = None,
        expire: float | int | None = None,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []
        conn = self._ensure_started()
        collection_resolved = self._resolve_collection(collection) if collection is not None else None

        coll_name: str | None = None
        payloads: list[dict[str, Any]] = []
        model_cls: type[ORMModel] | None = None
        for value in batch:
            current_collection, payload, current_model_cls = self._normalize_value(value, collection=collection_resolved)
            if coll_name is None:
                coll_name = current_collection
            elif coll_name != current_collection:
                raise ValueError('VectorClient.set_many() requires all values to target the same collection.')
            if model_cls is None and current_model_cls is not None:
                model_cls = current_model_cls
            payloads.append(payload)

        assert coll_name is not None
        if model_cls is not None:
            await self.ensure_collection(model_cls)
        elif coll_name not in self._vector_fields:
            raise ValueError(
                f"Collection `{coll_name}` is not registered. "
                "Call create_collection() with ORMModel first."
            )
        else:
            self._ensure_table(coll_name)

        for payload in payloads:
            for fname in self._vector_fields.get(coll_name, {}):
                vec = payload.get(fname)
                if not isinstance(vec, list):
                    raise ValueError(f"Vector field `{fname}` must be a list[float].")

        tbl = self._table_name(coll_name)
        sys_tbl = self._sys_table_name(coll_name)
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        accessed_at = _now_ts()
        mapping = self._field_name_mappings.get(coll_name, {})
        data_rows: list[tuple[str, str]] = []
        sys_rows: list[tuple[str, float | None, int, float]] = []
        object_ids: list[str] = []
        for payload in payloads:
            object_id = str(payload["id"])
            object_ids.append(object_id)
            db_payload = remap_payload_to_db(payload, mapping) if mapping else payload
            payload_json = _json_dumps(db_payload)
            data_rows.append((object_id, payload_json))
            sys_rows.append((object_id, expire_at, len(payload_json.encode("utf-8")), accessed_at))

        with self._lock:
            conn.executemany(
                f'INSERT OR REPLACE INTO "{tbl}" (id, payload_json) VALUES (?, ?)',
                data_rows,
            )
            conn.executemany(
                f'INSERT OR REPLACE INTO "{sys_tbl}" (id, expire_at, size, accessed_at) VALUES (?, ?, ?, ?)',
                sys_rows,
            )
            conn.commit()
            self._get_state(coll_name).dirty = True

        self._schedule_cleanup()
        return object_ids

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[True] = True) -> T | None: ...

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    async def get(self, collection: str | type[ORMModel], object_id: str, *, as_model: bool = True) -> HydratedVectorDocument | None:  # type: ignore[override]
        return await super().get(collection, object_id, as_model=as_model)

    async def raw_get(self, collection: str | type[ORMModel], object_id: str) -> dict[str, Any] | None:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        conn = self._ensure_started()
        tbl = self._table_name(collection)
        sys_tbl = self._sys_table_name(collection)
        try:
            row = conn.execute(
                f'SELECT d.payload_json, s.expire_at FROM "{tbl}" d LEFT JOIN "{sys_tbl}" s ON d.id = s.id WHERE d.id = ?',
                (object_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # table does not exist yet
        if not row:
            return None
        payload_json, expire_at = row
        if expire_at is not None and expire_at <= _now_ts():
            await self.delete(collection, object_id)
            return None
        payload = _json_loads_dict_or_none(payload_json)
        if payload is None:
            return None
        mapping = self._field_name_mappings.get(collection, {})
        return remap_payload_from_db(payload, mapping) if mapping else payload

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search(self, collection: str, query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: str, query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    async def search(
        self,
        collection: str | type[ORMModel],
        query: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:  # type: ignore[override]
        async for item in super().search(collection, query=query, limit=limit, offset=offset, as_model=as_model):
            yield item

    async def raw_query(
        self,
        collection: str | type[ORMModel],
        query: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        conn = self._ensure_started()
        tbl = self._table_name(collection)
        sys_tbl = self._sys_table_name(collection)
        try:
            rows = conn.execute(
                f'SELECT d.id, d.payload_json, s.expire_at FROM "{tbl}" d LEFT JOIN "{sys_tbl}" s ON d.id = s.id'
            ).fetchall()
        except sqlite3.OperationalError:
            return  # table does not exist yet

        skipped = 0
        emitted = 0
        for doc_id, payload_json, expire_at in rows:
            if expire_at is not None and expire_at <= _now_ts():
                await self.delete(collection, doc_id)
                continue
            payload = _json_loads_dict_or_none(payload_json)
            if payload is None:
                continue
            if not _match_query_or_expr(payload, query):
                continue
            if skipped < offset:
                skipped += 1
                continue
            if limit is not None and emitted >= limit:
                break
            mapping = self._field_name_mappings.get(collection, {})
            yield remap_payload_from_db(payload, mapping) if mapping else payload
            emitted += 1

    async def selected_search(
        self,
        collection: str | type[ORMModel],
        *,
        fields: Sequence[str],
        query: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        collection = self._resolve_collection(collection)
        conn = self._ensure_started()
        tbl = self._table_name(collection)
        sys_tbl = self._sys_table_name(collection)

        normalized_fields = _normalize_selected_fields(fields)
        mapping = self._field_name_mappings.get(collection, {})
        # Build column expressions using json_extract on payload_json
        columns = ["d.id AS __row_id"]
        aliases: list[tuple[str, str]] = []
        for index, field in enumerate(normalized_fields):
            if field in {"id", "_id"}:
                columns.append(f"d.id AS __sel_{index}")
            else:
                db_field = mapping.get(field, field)
                columns.append(f"json_extract(d.payload_json, '$.{db_field}') AS __sel_{index}")
            aliases.append((field, f"__sel_{index}"))

        # Build WHERE conditions using json_extract on payload_json
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if query:
            try:
                conds, cond_params = self._annoy_query_to_sql(query, mapping)
                conditions = conds
                params = cond_params
            except (ValueError, KeyError):
                async for item in super().selected_search(
                    collection,
                    fields=normalized_fields,
                    query=query,
                    limit=limit,
                    offset=offset,
                ):
                    yield item
                return

        now = _now_ts()
        sys_table_exists = False
        try:
            sys_table_exists = bool(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                    (sys_tbl,),
                ).fetchone()
            )
            if sys_table_exists:
                expired_ids = conn.execute(
                    f'SELECT id FROM "{sys_tbl}" WHERE expire_at IS NOT NULL AND expire_at <= ?',
                    (now,),
                ).fetchall()
                if expired_ids:
                    id_list = [r[0] for r in expired_ids]
                    placeholders = ",".join("?" * len(id_list))
                    conn.execute(f'DELETE FROM "{tbl}" WHERE id IN ({placeholders})', id_list)
                    conn.execute(f'DELETE FROM "{sys_tbl}" WHERE id IN ({placeholders})', id_list)
                    conn.commit()
                query_sql = (
                    f'SELECT {", ".join(columns)} FROM "{tbl}" d'
                    f' LEFT JOIN "{sys_tbl}" s ON d.id = s.id'
                    f' WHERE (s.expire_at IS NULL OR s.expire_at > :selected_now)'
                )
                params = {**params, "selected_now": now}
            else:
                query_sql = f'SELECT {", ".join(columns)} FROM "{tbl}" d WHERE 1 = 1'

            if conditions:
                query_sql += f" AND {' AND '.join(conditions)}"
            if limit is not None:
                query_sql += " LIMIT :selected_limit"
                params["selected_limit"] = int(limit)
            if offset > 0:
                query_sql += " OFFSET :selected_offset"
                params["selected_offset"] = int(offset)

            rows = conn.execute(query_sql, params).fetchall()
        except sqlite3.OperationalError:
            async for item in super().selected_search(
                collection,
                fields=normalized_fields,
                query=query,
                limit=limit,
                offset=offset,
            ):
                yield item
            return

        if rows and sys_table_exists:
            conn.executemany(
                f'UPDATE "{sys_tbl}" SET accessed_at = ? WHERE id = ?',
                [(_now_ts(), row[0]) for row in rows],
            )
            conn.commit()

        for row in rows:
            yield _project_selected_pairs([
                (field, row[index + 1])
                for index, (field, _) in enumerate(aliases)
            ])

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    async def search_vector(
        self,
        collection: str | type[ORMModel],
        vector: VectorSearchInput,
        *,
        field: str | None = None,
        limit: int = 10,
        query: Mapping[str, Any] | None = None,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:  # type: ignore[override]
        collection, field_name, query_vector = await self._resolve_search_vector(collection, vector, field=field)
        conn = self._ensure_started()
        state = self._ensure_index(collection)
        idx = state.annoy_indexes.get(field_name)
        item_count = state.item_counts.get(field_name)
        if item_count is None:
            get_n_items = getattr(idx, 'get_n_items', None)
            if callable(get_n_items):
                item_count = _coerce_int(get_n_items())
                if item_count is None:
                    item_count = state.next_int
            else:
                item_count = state.next_int
        if idx is None or item_count <= 0:
            return

        # Annoy returns at most n_items results; request more to allow filtering
        search_k = min(item_count, limit * 3)
        int_ids, distances = idx.get_nns_by_vector(
            query_vector, search_k, include_distances=True,
        )
        tbl = self._table_name(collection)
        sys_tbl = self._sys_table_name(collection)
        emitted = 0
        for int_id, dist in zip(int_ids, distances):
            if emitted >= limit:
                break
            obj_id = state.int_to_id.get(int_id)
            if obj_id is None:
                continue
            row = conn.execute(
                f'SELECT d.payload_json, s.expire_at FROM "{tbl}" d LEFT JOIN "{sys_tbl}" s ON d.id = s.id WHERE d.id = ?',
                (obj_id,),
            ).fetchone()
            if not row:
                continue
            payload_json, expire_at = row
            if expire_at is not None and expire_at <= _now_ts():
                await self.delete(collection, obj_id)
                continue
            payload = _json_loads_dict_or_none(payload_json)
            if payload is None:
                continue
            if not _match_query_or_expr(payload, query):
                continue
            # Annoy angular distance → cosine similarity: cos_sim = 1 - dist^2 / 2
            payload["_score"] = 1.0 - dist * dist / 2.0
            yield await self._hydrate_with_foreign(collection, payload, as_model=as_model)
            emitted += 1

    async def delete(self, collection: str | type[ORMModel], object_id: str) -> bool:  # type: ignore[override]
        return await super().delete(collection, object_id)

    async def raw_delete(self, collection: str | type[ORMModel], object_id: str) -> bool:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        conn = self._ensure_started()
        tbl = self._table_name(collection)
        sys_tbl = self._sys_table_name(collection)
        try:
            with self._lock:
                cur = conn.execute(f'DELETE FROM "{tbl}" WHERE id = ?', (object_id,))
                conn.execute(f'DELETE FROM "{sys_tbl}" WHERE id = ?', (object_id,))
                conn.commit()
                deleted = (cur.rowcount or 0) > 0
                if deleted:
                    self._get_state(collection).dirty = True
            return deleted
        except sqlite3.OperationalError:
            return False  # table does not exist yet

    async def delete_many(self, collection: str | type[ORMModel], object_ids: Iterable[str]) -> dict[str, bool]:
        collection_name = self._resolve_collection(collection)
        ids = [str(object_id or "").strip() for object_id in object_ids]
        ids = [object_id for object_id in ids if object_id]
        if not ids:
            return {}
        conn = self._ensure_started()
        tbl = self._table_name(collection_name)
        sys_tbl = self._sys_table_name(collection_name)
        try:
            placeholders = ",".join("?" for _ in ids)
            with self._lock:
                existing_rows = conn.execute(
                    f'SELECT id FROM "{tbl}" WHERE id IN ({placeholders})',
                    ids,
                ).fetchall()
                existing_ids = {str(row[0]) for row in existing_rows}
                if not existing_ids:
                    return {object_id: False for object_id in ids}
                existing_list = sorted(existing_ids)
                existing_placeholders = ",".join("?" for _ in existing_list)
                conn.execute(f'DELETE FROM "{tbl}" WHERE id IN ({existing_placeholders})', existing_list)
                conn.execute(f'DELETE FROM "{sys_tbl}" WHERE id IN ({existing_placeholders})', existing_list)
                conn.commit()
                self._get_state(collection_name).dirty = True
            return {object_id: object_id in existing_ids for object_id in ids}
        except sqlite3.OperationalError:
            return {object_id: False for object_id in ids}

    async def set_expire(self, collection: str | type[ORMModel], object_id: str, expire: float | int | None) -> bool:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        conn = self._ensure_started()
        sys_tbl = self._sys_table_name(collection)
        expire_at = _normalize_expire_at(expire)
        try:
            with self._lock:
                cur = conn.execute(
                    f'UPDATE "{sys_tbl}" SET expire_at = ? WHERE id = ?',
                    (expire_at, object_id),
                )
                conn.commit()
            return (cur.rowcount or 0) > 0
        except sqlite3.OperationalError:
            return False  # table does not exist yet

    async def get_expire(self, collection: str | type[ORMModel], object_id: str) -> float | None:  # type: ignore[override]
        collection = self._resolve_collection(collection)
        conn = self._ensure_started()
        sys_tbl = self._sys_table_name(collection)
        try:
            row = conn.execute(
                f'SELECT expire_at FROM "{sys_tbl}" WHERE id = ?', (object_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # table does not exist yet
        if not row:
            return None
        ttl = _ttl_from_expire_at(row[0])
        if ttl == 0.0:
            await self.delete(collection, object_id)
        return ttl

    async def cleanup(self, *, force: bool = False) -> int:
        if not await self._should_cleanup_async(force=force):
            return 0
        async with self._cleanup_async_lock():
            if not await self._should_cleanup_async(force=force):
                return 0
            conn = self._ensure_started()
            removed = 0
            total_size = 0
            live_rows: list[tuple[str, str, int, float]] = []
            ts = _now_ts()

            for collection in list(self._collection_models.keys()):
                tbl = self._table_name(collection)
                sys_tbl = self._sys_table_name(collection)
                try:
                    rows = conn.execute(
                        f'SELECT d.id, d.payload_json, s.expire_at, s.accessed_at, s.size '
                        f'FROM "{tbl}" d LEFT JOIN "{sys_tbl}" s ON d.id = s.id'
                    ).fetchall()
                except sqlite3.OperationalError:
                    continue
                expired_ids: list[str] = []
                for doc_id, payload_json, expire_at, accessed_at, size in rows:
                    if expire_at is not None and expire_at <= ts:
                        expired_ids.append(doc_id)
                        continue
                    row_size = size if size is not None else len(payload_json.encode("utf-8"))
                    total_size += row_size
                    live_rows.append((collection, doc_id, row_size, float(accessed_at or 0.0)))
                if expired_ids:
                    with self._lock:
                        placeholders = ",".join("?" for _ in expired_ids)
                        conn.execute(f'DELETE FROM "{tbl}" WHERE id IN ({placeholders})', expired_ids)
                        conn.execute(f'DELETE FROM "{sys_tbl}" WHERE id IN ({placeholders})', expired_ids)
                        conn.commit()
                        self._get_state(collection).dirty = True
                    removed += len(expired_ids)

            total_count = len(live_rows)
            if self._max_size is not None and len(live_rows) > self._max_size:
                target = max(0, int(self._max_size * 0.9))
                evict_by_collection: dict[str, list[str]] = {}
                for collection, doc_id, size, _ in sorted(live_rows, key=lambda r: r[3]):
                    if total_count <= target:
                        break
                    evict_by_collection.setdefault(collection, []).append(doc_id)
                    total_count -= 1
                    removed += 1
                for collection, ids in evict_by_collection.items():
                    with self._lock:
                        tbl = self._table_name(collection)
                        sys_tbl = self._sys_table_name(collection)
                        placeholders = ",".join("?" for _ in ids)
                        conn.execute(f'DELETE FROM "{tbl}" WHERE id IN ({placeholders})', ids)
                        conn.execute(f'DELETE FROM "{sys_tbl}" WHERE id IN ({placeholders})', ids)
                        conn.commit()
                        self._get_state(collection).dirty = True

            await self._mark_cleanup_async()
            return removed


class MongoVectorClient(VectorClientBase, type="mongo"):
    _META_COLLECTION = "_vector_collections"

    def __init__(self, **kwargs: Unpack[MongoVectorClientInitParams]) -> None:
        self._mongo_url = kwargs.get("mongo_url", "mongodb://127.0.0.1:27017")
        self._database_name = kwargs.get("database", "app_backend")
        self._mongo_client: _AsyncMotorClient | None = None
        self._mongo_client_loop: asyncio.AbstractEventLoop | None = None
        self._sync_mongo_client: _SyncMongoClient | None = None
        self._database: _AsyncMotorDB | None = None
        self._sync_database: _SyncMongoDB | None = None
        self._server_version: tuple[int, int, int] | None = None
        super().__init__(**kwargs)

    def start(self) -> Self:
        if self._started:
            self._ensure_async_client()
            return self
        from pymongo import MongoClient  # lazy import

        self._sync_mongo_client = MongoClient(self._mongo_url)
        self._sync_database = self._sync_mongo_client[self._database_name]
        self._server_version = self._detect_server_version()
        self._restore_collection_state()
        self._mark_started()
        self._ensure_async_client()
        return self

    def close(self) -> None:
        mongo_client = self._mongo_client
        sync_mongo_client = self._sync_mongo_client
        self._mongo_client = None
        self._mongo_client_loop = None
        self._sync_mongo_client = None
        self._database = None
        self._sync_database = None
        self._mark_stopped()
        for client in (mongo_client, sync_mongo_client):
            if client is None:
                continue
            try:
                close_func = getattr(client, "close", None)
                if callable(close_func):
                    close_func()
            except Exception as exc:
                _logger.warning("MongoVectorClient.close() failed for %s: %s", self._mongo_url, exc)

    @staticmethod
    def _parse_server_version(text: str | None) -> tuple[int, int, int] | None:
        if not text:
            return None
        chunks = str(text).split(".")
        if len(chunks) < 2:
            return None
        numbers: list[int] = []
        for chunk in chunks[:3]:
            digits = "".join(ch for ch in str(chunk) if ch.isdigit())
            if not digits:
                return None
            numbers.append(int(digits))
        while len(numbers) < 3:
            numbers.append(0)
        return cast(tuple[int, int, int], tuple(numbers[:3]))

    def _detect_server_version(self) -> tuple[int, int, int] | None:
        sync_client = self._sync_mongo_client
        if sync_client is None:
            return None
        try:
            info = sync_client.server_info()
        except Exception:
            return None
        return self._parse_server_version(cast(str | None, info.get("version")))

    def _collection_name(self, collection: str) -> str:
        _validate_collection_name(collection)
        return f"vector_{self._namespace}_{collection}"

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
                _logger.warning("MongoVectorClient.close() failed for %s: %s", self._mongo_url, exc)
        from motor.motor_asyncio import AsyncIOMotorClient  # lazy import

        self._mongo_client = AsyncIOMotorClient(self._mongo_url)
        self._database = self._mongo_client[self._database_name]
        self._mongo_client_loop = current_loop

    def _collection(self, collection: str) -> '_AsyncMotorCollection':
        if not self._started:
            self.start()
        self._ensure_async_client()
        database = self._database
        assert database is not None
        return database[self._collection_name(collection)]

    def _sync_collection(self, collection: str) -> '_SyncMongoCollection':
        if not self._started:
            self.start()
        database = self._sync_database
        assert database is not None
        return database[self._collection_name(collection)]

    def _meta_collection(self) -> '_AsyncMotorCollection':
        if not self._started:
            self.start()
        self._ensure_async_client()
        database = self._database
        assert database is not None
        return database[self._META_COLLECTION]

    def _sync_meta_collection(self) -> '_SyncMongoCollection':
        if not self._started:
            self.start()
        database = self._sync_database
        assert database is not None
        return database[self._META_COLLECTION]

    @staticmethod
    def _try_import_model(module_name: str | None, class_name: str | None) -> type[ORMModel] | None:
        if not module_name or not class_name:
            return None
        try:
            module = importlib.import_module(module_name)
            model_cls = getattr(module, class_name, None)
        except Exception:
            return None
        if isinstance(model_cls, type) and issubclass(model_cls, ORMModel):
            return model_cls
        return None

    def _apply_collection_meta(self, meta: Mapping[str, Any]) -> None:
        namespace = str(meta.get("namespace") or "")
        if namespace and namespace != self._namespace:
            return
        collection = str(meta.get("collection_name") or "").strip()
        if not collection:
            return
        raw_vector_fields = meta.get("vector_fields") or {}
        if isinstance(raw_vector_fields, Mapping):
            self._vector_fields[collection] = {
                str(name): int(dim)
                for name, dim in raw_vector_fields.items()
            }
        raw_metrics = meta.get("vector_field_metrics") or {}
        if isinstance(raw_metrics, Mapping):
            self._vector_field_metrics[collection] = {
                str(name): _coerce_metric_type(metric, self._metric_type)
                for name, metric in raw_metrics.items()
            }
        raw_algorithms = meta.get("vector_field_algorithms") or {}
        if isinstance(raw_algorithms, Mapping):
            self._vector_field_algorithms[collection] = {
                str(name): cast(VectorIndexAlgorithm, str(algorithm).upper())
                for name, algorithm in raw_algorithms.items()
                if str(algorithm).upper() in {"AUTOINDEX", "FLAT", "HNSW"}
            }
        raw_scalar_fields = meta.get("scalar_fields") or []
        if isinstance(raw_scalar_fields, Sequence) and not isinstance(raw_scalar_fields, (str, bytes, bytearray)):
            self._scalar_fields[collection] = [str(item) for item in raw_scalar_fields if str(item or "").strip()]
        model_cls = self._try_import_model(
            cast(str | None, meta.get("model_module")),
            cast(str | None, meta.get("model_name")),
        )
        if model_cls is not None:
            self._collection_models[collection] = model_cls
        self._mark_collection_known(collection)

    def _restore_collection_state(self) -> None:
        try:
            rows = self._sync_meta_collection().find({"namespace": self._namespace})
        except Exception:
            return
        for row in rows:
            if isinstance(row, Mapping):
                self._apply_collection_meta(dict(row))

    async def _async_restore_collection_state(self) -> None:
        try:
            async for row in self._meta_collection().find({"namespace": self._namespace}):
                if isinstance(row, Mapping):
                    self._apply_collection_meta(dict(row))
        except Exception:
            return

    async def _load_collection_meta(self, collection: str) -> dict[str, Any] | None:
        try:
            row = await self._meta_collection().find_one(
                {"namespace": self._namespace, "collection_name": collection},
            )
        except Exception:
            return None
        return dict(row) if isinstance(row, Mapping) else None

    async def _async_collection_exists(self, collection: str) -> bool:
        if collection in self._known_collections:
            return True
        row = await self._load_collection_meta(collection)
        if isinstance(row, Mapping):
            self._apply_collection_meta(dict(row))
            return True
        try:
            physical_name = self._collection_name(collection)
            names = await self._database.list_collection_names()  # type: ignore[union-attr]
        except Exception:
            return False
        if physical_name in {str(name) for name in names}:
            self._mark_collection_known(collection)
            return True
        return False

    async def _load_stored_schema(self, collection: str) -> dict[str, Any] | None:
        try:
            row = await self._meta_collection().find_one(
                {"namespace": self._namespace, "collection_name": collection},
                {"schema_json": 1, "_id": 0},
            )
        except Exception:
            return None
        if not isinstance(row, Mapping):
            return None
        raw = row.get("schema_json")
        if not raw:
            return None
        return _json_loads_dict_or_none(raw)

    def _vector_index_name(self, collection: str, field: str) -> str:
        return f"proj_vector_{self._namespace}_{collection}_{field}"

    def _vector_index_definition(self, collection: str, field: str) -> dict[str, Any]:
        dim = int((self._vector_fields.get(collection) or {}).get(field) or 0)
        if dim <= 0:
            raise ValueError(f"Mongo vector field `{collection}.{field}` is missing a positive dimension.")
        db_field = self._db_field_name(collection, field)
        filter_fields = [
            {"type": "filter", "path": "_id"},
        ]
        seen_paths = {"_id"}
        for scalar_field in self._scalar_fields.get(collection, []):
            db_sf = self._db_field_name(collection, scalar_field)
            if db_sf in seen_paths:
                continue
            seen_paths.add(db_sf)
            filter_fields.append({"type": "filter", "path": db_sf})
        return {
            "fields": [
                {
                    "type": "vector",
                    "path": db_field,
                    "numDimensions": dim,
                    "similarity": _mongo_vector_similarity(self._get_field_metric(collection, field)),
                },
                *filter_fields,
            ]
        }

    async def _ensure_vector_search_version(self) -> None:
        version = self._server_version
        if version is None:
            self._ensure_async_client()
            mongo_client = self._mongo_client
            if mongo_client is None:
                self.start()
                self._ensure_async_client()
                mongo_client = self._mongo_client
            assert mongo_client is not None
            try:
                info = await mongo_client.server_info()
                version = self._parse_server_version(cast(str | None, info.get("version")))
                self._server_version = version
            except Exception as exc:
                raise ValueError(f"Failed to determine MongoDB server version: {exc}") from exc
        if version is None or version < (8, 2, 0):
            human = "unknown" if version is None else ".".join(str(part) for part in version)
            raise ValueError(f"Mongo vector search requires MongoDB >= 8.2, got {human}.")

    @staticmethod
    def _raise_vector_search_configuration_error(exc: Exception) -> None:
        message = str(exc)
        code = getattr(exc, "code", None)
        if code == 31082 or "SearchNotEnabled" in message or "requires additional configuration" in message:
            raise ValueError(
                "Mongo vector search is not enabled on this deployment. Plain mongod 8.2 is still not enough here; use MongoDB Atlas or an Atlas CLI local deployment with Atlas Search/Vector Search enabled."
            ) from exc
        raise exc

    async def _list_search_indexes(self, collection: str) -> list[dict[str, Any]]:
        coll = self._collection(collection)
        try:
            return [dict(item) async for item in coll.list_search_indexes()]
        except Exception as exc:
            self._raise_vector_search_configuration_error(exc)
            raise AssertionError("unreachable")

    @staticmethod
    def _search_index_queryable(index_doc: Mapping[str, Any]) -> bool:
        queryable = index_doc.get("queryable")
        if isinstance(queryable, bool):
            return queryable
        status = str(index_doc.get("status") or index_doc.get("state") or "").upper()
        return status in {"READY", "ACTIVE", "STEADY"}

    async def _wait_for_search_index(self, collection: str, index_name: str, *, timeout: float = 30.0) -> None:
        deadline = _now_ts() + timeout
        while _now_ts() < deadline:
            indexes = await self._list_search_indexes(collection)
            for index_doc in indexes:
                if str(index_doc.get("name") or "") != index_name:
                    continue
                if self._search_index_queryable(index_doc):
                    return
            await asyncio.sleep(0.25)
        raise TimeoutError(f"Mongo vector index `{index_name}` was not ready within {timeout:.1f}s.")

    async def _drop_vector_indexes(self, collection: str, fields: list[str]) -> None:
        try:
            existing = {
                str(index_doc.get("name") or ""): index_doc
                for index_doc in await self._list_search_indexes(collection)
            }
        except Exception:
            existing = {}
        coll = self._collection(collection)
        for field in fields:
            index_name = self._vector_index_name(collection, field)
            if index_name in existing:
                try:
                    await coll.drop_search_index(index_name)
                    _logger.info("Dropped Mongo vector search index '%s'.", index_name)
                except Exception as exc:
                    _logger.warning("Failed to drop Mongo vector index '%s': %s", index_name, exc)
            else:
                _logger.debug("Mongo vector index '%s' not found; nothing to drop.", index_name)

    async def _ensure_vector_indexes(self, collection: str) -> None:
        from pymongo.operations import SearchIndexModel

        coll = self._collection(collection)
        existing = {
            str(index_doc.get("name") or ""): index_doc
            for index_doc in await self._list_search_indexes(collection)
        }
        for field in self._vector_fields.get(collection, {}):
            index_name = self._vector_index_name(collection, field)
            if index_name in existing:
                # Reconcile: compare DB index with model, warn & align on mismatch.
                # Do NOT modify the DB index.
                self._reconcile_mongo_vector_index(collection, field, existing[index_name])
            else:
                definition = self._vector_index_definition(collection, field)
                try:
                    await coll.create_search_index(
                        SearchIndexModel(
                            definition=definition,
                            name=index_name,
                            type="vectorSearch",
                        )
                    )
                except Exception as exc:
                    self._raise_vector_search_configuration_error(exc)
                await self._wait_for_search_index(collection, index_name)

    def _reconcile_mongo_vector_index(
        self, collection: str, field: str, index_doc: Mapping[str, Any],
    ) -> None:
        """Compare an existing Mongo vector search index with the model and align on mismatch."""
        db_field = self._db_field_name(collection, field)
        raw_def = index_doc.get("latestDefinition") or index_doc.get("definition") or {}
        for field_def in (raw_def.get("fields") or []):
            if not isinstance(field_def, Mapping) or field_def.get("type") != "vector":
                continue
            if str(field_def.get("path") or "") != db_field:
                continue
            # Found the matching vector field definition
            db_dim_raw = field_def.get("numDimensions")
            db_similarity = str(field_def.get("similarity") or "").lower()
            model_dim = (self._vector_fields.get(collection) or {}).get(field)
            model_metric = self._get_field_metric(collection, field)
            try:
                model_similarity = _mongo_vector_similarity(model_metric)
            except ValueError:
                model_similarity = ""

            if db_dim_raw is not None and model_dim is not None and int(db_dim_raw) != int(model_dim):
                _logger.warning(
                    "Vector field '%s' dim mismatch in Mongo collection '%s': "
                    "model=%d, db=%d. Aligning model to DB.",
                    field, collection, model_dim, int(db_dim_raw),
                )
                self._align_vector_field_to_db(collection, field, db_dim=int(db_dim_raw))

            if db_similarity and db_similarity != model_similarity:
                db_metric = _mongo_similarity_to_metric(db_similarity)
                if db_metric is not None:
                    _logger.warning(
                        "Vector field '%s' metric_type mismatch in Mongo collection '%s': "
                        "model=%s (similarity=%s), db=%s (similarity=%s). Aligning model to DB.",
                        field, collection, model_metric, model_similarity, db_metric, db_similarity,
                    )
                    self._align_vector_field_to_db(collection, field, db_metric=db_metric)
            break

    async def _upsert_collection_meta(self, collection: str, model_cls: type[ORMModel] | None = None) -> None:
        if model_cls is not None:
            self._register_model(model_cls)
        existing = await self._meta_collection().find_one({"namespace": self._namespace, "collection_name": collection}) or {}
        schema_json = existing.get("schema_json")
        if model_cls is not None:
            schema_json = _safe_model_schema(model_cls)
        meta = {
            "namespace": self._namespace,
            "collection_name": collection,
            "backend_name": self._collection_name(collection),
            "model_module": existing.get("model_module", model_cls.__module__ if model_cls is not None else None),
            "model_name": existing.get("model_name", model_cls.__name__ if model_cls is not None else None),
            "schema_json": schema_json,
            "vector_fields": dict(self._vector_fields.get(collection, {})),
            "vector_field_metrics": dict(self._vector_field_metrics.get(collection, {})),
            "vector_field_algorithms": dict(self._vector_field_algorithms.get(collection, {})),
            "scalar_fields": list(self._scalar_fields.get(collection, [])),
        }
        await self._meta_collection().update_one(
            {"namespace": self._namespace, "collection_name": collection},
            {"$set": meta},
            upsert=True,
        )
        self._apply_collection_meta(meta)

    def _combined_query_filter(self, collection: str, query: Mapping[str, Any] | None) -> dict[str, Any]:
        mapping = self._field_name_mappings.get(collection) or None
        mongo_filter = _build_mongo_selected_query(query, field_name_map=mapping)
        if mongo_filter is None:
            raise ValueError("Mongo vector queries require filters that can be pushed down to Mongo.")
        validity: dict[str, Any] = {
            "$or": [
                {"_sys.expire_at": {"$exists": False}},
                {"_sys.expire_at": {"$gt": _now_ts()}},
            ]
        }
        return {"$and": [validity, mongo_filter]} if mongo_filter else validity

    def _vector_search_filter(self, collection: str, query: Mapping[str, Any] | None) -> dict[str, Any]:
        mapping = self._field_name_mappings.get(collection) or None
        mongo_filter = _build_mongo_selected_query(query, field_name_map=mapping)
        if mongo_filter is None:
            raise ValueError("Mongo vector queries require filters that can be pushed down to Mongo.")
        if not mongo_filter:
            return {}
        if not _mongo_vector_filter_supported(mongo_filter):
            raise ValueError("Mongo vector search only supports exact, range, and $in filters.")
        return mongo_filter

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        if not self._started:
            self.start()
        await self._ensure_vector_search_version()
        self._register_model(model_cls)
        collection = model_cls.CollectionName
        coll = self._collection(collection)
        with nullcontext():
            await coll.create_index("_sys.expire_at")
            await coll.create_index("_sys.accessed_at")
            for field_name in self._scalar_fields.get(collection, []):
                db_name = self._db_field_name(collection, field_name)
                await coll.create_index(db_name)
            # Upsert meta first, then reconcile indexes. _upsert_collection_meta
            # calls _register_model which would revert alignment done by
            # _ensure_vector_indexes, so reconciliation must run last.
            await self._upsert_collection_meta(collection, model_cls)
            await self._ensure_vector_indexes(collection)

    async def drop_collection(self, collection: str | type[ORMModel]) -> None:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        await self._collection(collection_name).drop()
        await self._meta_collection().delete_one({"namespace": self._namespace, "collection_name": collection_name})
        self._collection_models.pop(collection_name, None)
        self._vector_fields.pop(collection_name, None)
        self._vector_field_metrics.pop(collection_name, None)
        self._vector_field_algorithms.pop(collection_name, None)
        self._scalar_fields.pop(collection_name, None)
        self._forget_collection(collection_name)

    async def set(
        self,
        value: ORMModel | dict[str, Any],
        *,
        collection: str | type[ORMModel] | None = None,
        expire: float | int | None = None,
    ) -> str:  # type: ignore[override]
        return await super().set(value, collection=collection, expire=expire)

    async def raw_set(
        self,
        collection: str | type[ORMModel],
        payload: VectorPayloadLike,
        *,
        expire: float | int | None = None,
    ) -> str:  # type: ignore[override]
        if not self._started:
            self.start()
        collection_name = self._resolve_collection(collection)
        if isinstance(collection, type) and issubclass(collection, ORMModel):
            await self.ensure_collection(collection)
        elif not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` is not registered. Call create_collection() with ORMModel first.")
        collection_name, payload, _ = self._normalize_value(payload, collection=collection_name)

        for field_name, dim in self._vector_fields.get(collection_name, {}).items():
            vector = payload.get(field_name)
            if isinstance(vector, np.ndarray):
                vector = normalize_vector_embedding(vector)
                payload[field_name] = vector
            if not isinstance(vector, list):
                raise ValueError(f"Vector field `{field_name}` must be a list[float].")
            if dim and len(vector) != dim:
                raise ValueError(
                    f"Vector field `{field_name}` dimension mismatch: expected {dim}, got {len(vector)}."
                )
            payload[field_name] = [float(item) for item in vector]

        object_id = str(payload.get("id") or payload.get("_id"))
        mongo_object_id = _to_mongo_object_id(object_id)
        now = _now_ts()
        existing = await self._collection(collection_name).find_one({"_id": mongo_object_id})
        if existing is not None:
            await self._handle_file_id_ref_on_overwrite(collection_name, _restore_mongo_doc(existing), payload)
        mapping = self._field_name_mappings.get(collection_name, {})
        db_payload = remap_payload_to_db(payload, mapping) if mapping else payload
        db_payload_clean = {k: v for k, v in db_payload.items() if k not in ("id", "_id")}
        doc: dict[str, Any] = {"_id": mongo_object_id}
        doc.update(db_payload_clean)
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        sys_meta: dict[str, Any] = {
            "size": len(_json_dumps(db_payload).encode("utf-8")),
            "accessed_at": now,
        }
        if expire_at is not None:
            sys_meta["expire_at"] = expire_at
        doc["_sys"] = sys_meta
        await self._collection(collection_name).replace_one({"_id": mongo_object_id}, doc, upsert=True)
        await self.cleanup()
        return object_id

    async def set_many(
        self,
        values: Sequence[ORMModel | dict[str, Any]],
        *,
        collection: str | type[ORMModel] | None = None,
        expire: float | int | None = None,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []
        if not self._started:
            self.start()

        collection_resolved = self._resolve_collection(collection) if collection is not None else None
        collection_name: str | None = None
        payloads: list[dict[str, Any]] = []
        model_cls: type[ORMModel] | None = None
        for value in batch:
            current_collection, payload, current_model_cls = self._normalize_value(value, collection=collection_resolved)
            if collection_name is None:
                collection_name = current_collection
            elif collection_name != current_collection:
                raise ValueError('VectorClient.set_many() requires all values to target the same collection.')
            if model_cls is None and current_model_cls is not None:
                model_cls = current_model_cls
            payloads.append(payload)

        assert collection_name is not None
        if model_cls is not None:
            await self.create_collection(model_cls)
        elif not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` is not registered. Call create_collection() with ORMModel first.")

        from pymongo import ReplaceOne

        now = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        mapping = self._field_name_mappings.get(collection_name, {})
        operations: list['_PymongoReplaceOne'] = []
        object_ids: list[str] = []
        for payload in payloads:
            for field_name, dim in self._vector_fields.get(collection_name, {}).items():
                vector = payload.get(field_name)
                if isinstance(vector, np.ndarray):
                    vector = normalize_vector_embedding(vector)
                    payload[field_name] = vector
                if not isinstance(vector, list):
                    raise ValueError(f"Vector field `{field_name}` must be a list[float].")
                if dim and len(vector) != dim:
                    raise ValueError(
                        f"Vector field `{field_name}` dimension mismatch: expected {dim}, got {len(vector)}."
                    )
                payload[field_name] = [float(item) for item in vector]

            object_id = str(payload.get("id") or payload.get("_id"))
            object_ids.append(object_id)
            mongo_object_id = _to_mongo_object_id(object_id)
            db_payload = remap_payload_to_db(payload, mapping) if mapping else payload
            db_payload_clean = {k: v for k, v in db_payload.items() if k not in ("id", "_id")}
            replace_doc: dict[str, Any] = {"_id": mongo_object_id}
            replace_doc.update(db_payload_clean)
            sys_meta: dict[str, Any] = {
                "size": len(_json_dumps(db_payload).encode("utf-8")),
                "accessed_at": now,
            }
            if expire_at is not None:
                sys_meta["expire_at"] = expire_at
            replace_doc["_sys"] = sys_meta
            operations.append(ReplaceOne(
                {"_id": mongo_object_id},
                replace_doc,
                upsert=True,
            ))

        if operations:
            await self._collection(collection_name).bulk_write(operations, ordered=False)
        await self.cleanup()
        return object_ids

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[True] = True) -> T | None: ...

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    async def get(self, collection: str | type[ORMModel], object_id: str, *, as_model: bool = True) -> HydratedVectorDocument | None:  # type: ignore[override]
        return await super().get(collection, object_id, as_model=as_model)

    async def raw_get(self, collection: str | type[ORMModel], object_id: str) -> dict[str, Any] | None:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return None
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
        mapping = self._field_name_mappings.get(collection_name, {})
        return remap_payload_from_db(payload, mapping) if mapping else payload

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search(self, collection: str, query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: str, query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    async def search(
        self,
        collection: str | type[ORMModel],
        query: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:  # type: ignore[override]
        async for item in super().search(collection, query=query, limit=limit, offset=offset, as_model=as_model):
            yield item

    async def raw_query(
        self,
        collection: str | type[ORMModel],
        query: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return
        mapping = self._field_name_mappings.get(collection_name, {})
        cursor = self._collection(collection_name).find(self._combined_query_filter(collection_name, query)).sort("_id", -1)
        if offset > 0:
            cursor = cursor.skip(int(offset))
        if limit is not None:
            cursor = cursor.limit(int(limit))
        try:
            async for doc in cursor:
                payload = _restore_mongo_doc(doc)
                yield remap_payload_from_db(payload, mapping) if mapping else payload
        finally:
            await cursor.close()

    @overload
    def search_sorted[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search_sorted[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_sorted(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_sorted(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_sorted(self, collection: str, query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_sorted(self, collection: str, query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    async def search_sorted(
        self,
        collection: str | type[ORMModel],
        query: Mapping[str, Any] | None = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:
        collection_name = self._resolve_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return
        sort_spec: list[tuple[str, int]] = []
        mapping = self._field_name_mappings.get(collection_name) or None
        for raw_field, raw_direction in sort:
            field_name = _validate_selected_field_name(str(raw_field or ""))
            db_name = _translate_field_path(field_name, mapping) if mapping else field_name
            mongo_field = "_id" if field_name in {"id", "_id"} else db_name
            direction = -1 if str(raw_direction or "asc").lower() == "desc" else 1
            sort_spec.append((mongo_field, direction))
        cursor = self._collection(collection_name).find(self._combined_query_filter(collection_name, query)).sort(sort_spec or [("_id", -1)])
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

    async def selected_search(
        self,
        collection: str | type[ORMModel],
        *,
        fields: Sequence[str],
        query: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        collection_name = self._resolve_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return
        normalized_fields = _normalize_selected_fields(fields)
        mapping = self._field_name_mappings.get(collection_name) or None
        cursor = self._collection(collection_name).find(
            self._combined_query_filter(collection_name, query),
            _build_mongo_selected_projection(normalized_fields, field_name_map=mapping),
        ).sort("_id", -1)
        if offset > 0:
            cursor = cursor.skip(int(offset))
        if limit is not None:
            cursor = cursor.limit(int(limit))
        try:
            async for doc in cursor:
                payload = _restore_mongo_doc(doc)
                if mapping:
                    payload = remap_payload_from_db(payload, mapping)
                yield _project_selected_payload(payload, normalized_fields)
        finally:
            await cursor.close()

    async def selected_search_by_id(
        self,
        collection: str | type[ORMModel],
        object_id: str,
        *,
        fields: Sequence[str],
    ) -> dict[str, Any] | None:
        collection_name = self._resolve_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return None
        normalized_fields = _normalize_selected_fields(fields)
        mapping = self._field_name_mappings.get(collection_name) or None
        projection = _build_mongo_selected_projection(normalized_fields, field_name_map=mapping)
        projection["_sys.expire_at"] = 1
        doc = await self._collection(collection_name).find_one(
            {"_id": _to_mongo_object_id(object_id)},
            projection,
        )
        if doc is None:
            return None
        sys_meta = doc.get("_sys") or {}
        expire_at = sys_meta.get("expire_at")
        if expire_at is not None and expire_at <= _now_ts():
            await self.delete(collection_name, object_id)
            return None
        payload = _restore_mongo_doc(doc)
        if mapping:
            payload = remap_payload_from_db(payload, mapping)
        return _project_selected_payload(payload, normalized_fields)

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    async def search_vector(
        self,
        collection: str | type[ORMModel],
        vector: VectorSearchInput,
        *,
        field: str | None = None,
        limit: int = 10,
        query: Mapping[str, Any] | None = None,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:  # type: ignore[override]
        await self._ensure_vector_search_version()
        collection_name, field_name, query_vector = await self._resolve_search_vector(collection, vector, field=field)
        if not await self._async_collection_exists(collection_name):
            return
        requested_limit = max(int(limit), 1)
        stage_limit = max(requested_limit * 5, requested_limit)
        db_field = self._db_field_name(collection_name, field_name)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self._vector_index_name(collection_name, field_name),
                    "path": db_field,
                    "queryVector": query_vector,
                    "numCandidates": max(stage_limit * 20, stage_limit),
                    "limit": stage_limit,
                    "filter": self._vector_search_filter(collection_name, query),
                }
            },
            {
                "$addFields": {
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        try:
            cursor = self._collection(collection_name).aggregate(pipeline)
        except Exception as exc:
            self._raise_vector_search_configuration_error(exc)
            raise AssertionError("unreachable")
        try:
            yielded = 0
            async for doc in cursor:
                payload = _restore_mongo_doc(doc)
                if not isinstance(payload, dict):
                    continue
                sys_meta = payload.get("_sys")
                expire_at = _coerce_float(sys_meta.get("expire_at")) if isinstance(sys_meta, dict) else None
                if expire_at is not None and expire_at <= _now_ts():
                    object_id = str(payload.get("id") or payload.get("_id") or "")
                    if object_id:
                        await self.delete(collection_name, object_id)
                    continue
                payload["_score"] = _coerce_float(payload.pop("score", 0.0)) or 0.0
                yield await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)
                yielded += 1
                if yielded >= requested_limit:
                    break
        except Exception as exc:
            self._raise_vector_search_configuration_error(exc)
            raise AssertionError("unreachable")
        finally:
            await cursor.close()

    async def delete(self, collection: str | type[ORMModel], object_id: str) -> bool:  # type: ignore[override]
        return await super().delete(collection, object_id)

    async def raw_delete(self, collection: str | type[ORMModel], object_id: str) -> bool:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        mongo_id = _to_mongo_object_id(object_id)
        doc = await self._collection(collection_name).find_one({"_id": mongo_id})
        if doc is None:
            return False
        await self._cleanup_foreign_on_delete(collection_name, _restore_mongo_doc(doc))
        result = await self._collection(collection_name).delete_one({"_id": mongo_id})
        return result.deleted_count > 0

    async def set_expire(self, collection: str | type[ORMModel], object_id: str, expire: float | int | None) -> bool:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        normalized_expire_at = _normalize_expire_at(expire)
        update_doc: dict[str, Any]
        if normalized_expire_at is None:
            update_doc = {"$unset": {"_sys.expire_at": ""}}
        else:
            update_doc = {"$set": {"_sys.expire_at": normalized_expire_at}}
        result = await self._collection(collection_name).update_one(
            {"_id": _to_mongo_object_id(object_id)},
            update_doc,
        )
        return result.modified_count > 0

    async def get_expire(self, collection: str | type[ORMModel], object_id: str) -> float | None:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        doc = await self._collection(collection_name).find_one(
            {"_id": _to_mongo_object_id(object_id)},
            {"_sys.expire_at": 1},
        )
        if doc is None:
            return None
        ttl = _ttl_from_expire_at(doc.get("_sys", {}).get("expire_at"))
        if ttl == 0.0:
            await self.delete(collection_name, object_id)
        return ttl

    async def collection_count(self, collection: str | type[ORMModel]) -> int:
        collection_name = self._resolve_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return 0
        return int(await self._collection(collection_name).count_documents(self._combined_query_filter(collection_name, None)))

    async def query_count(self, collection: str | type[ORMModel], query: Mapping[str, Any] | None = None) -> int:
        collection_name = self._resolve_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return 0
        return int(await self._collection(collection_name).count_documents(self._combined_query_filter(collection_name, query)))

    async def cleanup(self, *, force: bool = False) -> int:
        if not await self._should_cleanup_async(force=force):
            return 0
        removed = 0
        total_size = 0
        live_rows: list[tuple[str, str, int, float]] = []
        now = _now_ts()
        async for meta in self._meta_collection().find({"namespace": self._namespace}, {"collection_name": 1}):
            collection_name = str(meta.get("collection_name") or "").strip()
            if not collection_name:
                continue
            coll = self._collection(collection_name)
            expired = await coll.delete_many({"_sys.expire_at": {"$exists": True, "$lte": now}})
            removed += int(expired.deleted_count or 0)
            if self._max_size is not None:
                async for doc in coll.find({}, {"_id": 1, "_sys.size": 1, "_sys.accessed_at": 1}):
                    sys_meta = doc.get("_sys", {})
                    size = int(sys_meta.get("size", 0) or 0)
                    total_size += size
                    live_rows.append((collection_name, str(doc.get("_id")), size, float(sys_meta.get("accessed_at", 0.0) or 0.0)))
        total_count = len(live_rows)
        if self._max_size is not None and len(live_rows) > self._max_size:
            target = max(0, int(self._max_size * 0.9))
            evict_by_collection: dict[str, list['_BsonObjectId']] = {}
            for collection_name, object_id, size, _ in sorted(live_rows, key=lambda item: item[3]):
                if total_count <= target:
                    break
                evict_by_collection.setdefault(collection_name, []).append(_to_mongo_object_id(object_id))
                total_count -= 1
                removed += 1
            for collection_name, mongo_ids in evict_by_collection.items():
                await self._collection(collection_name).delete_many({"_id": {"$in": mongo_ids}})
        await self._mark_cleanup_async()
        return removed


class RedisVectorClient(VectorClientBase, type="redis"):
    def __init__(self, **kwargs: Unpack[RedisVectorClientInitParams]) -> None:
        self._url = kwargs.get("url", "redis://127.0.0.1:6379/0")
        self._prefix = kwargs.get("prefix", "vector")
        self._db = int(kwargs.get("db", 0))
        self._decode_responses = bool(kwargs.get("decode_responses", True))
        self._redis: "_RedisAsyncClient | None" = None
        self._capabilities: "_RedisCapabilities | None" = None
        self._search_fields: dict[str, dict[str, RedisScalarFieldSpec]] = {}
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._state_lock = threading.RLock()
        super().__init__(**kwargs)

    def start(self) -> Self:
        if self._started:
            return self
        import redis.asyncio as aioredis  # type: ignore

        self._redis = aioredis.Redis.from_url(
            self._url,
            db=self._db,
            decode_responses=self._decode_responses,
        )
        self._mark_started()
        return self

    async def _ensure_ready(self) -> None:
        """Lazily ping + load capabilities on first async call."""
        if self._capabilities is not None:
            return
        client = self._client()
        await client.ping()
        self._capabilities = await async_load_redis_runtime_capabilities(client)
        ensure_redis_vector_supported(self._capabilities)
        await self._async_restore_collection_state()

    def close(self) -> None:
        redis_client = self._redis
        self._redis = None
        self._mark_stopped()
        self._capabilities = None
        with self._state_lock:
            self._cleanup_async_locks.clear()
        if redis_client is None:
            return
        try:
            aclose = getattr(redis_client, "aclose", None)
            if callable(aclose):
                _run_async_in_sync(cast(Callable[[], Awaitable[object]], aclose))
        except Exception as exc:
            _logger.warning("RedisVectorClient.close() failed for %s: %s", self._url, exc)

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = _async_owner_key()
        with self._state_lock:
            lock = self._cleanup_async_locks.get(owner)
            if lock is None:
                lock = asyncio.Lock()
                self._cleanup_async_locks[owner] = lock
            return lock

    def _client(self) -> "_RedisAsyncClient":
        if not self._started:
            self.start()
        assert self._redis is not None
        return self._redis

    def _root_prefix(self) -> str:
        return f"{self._prefix}:{self._namespace}"

    def _collections_key(self) -> str:
        return f"{self._root_prefix()}:collections"

    def _collection_meta_key(self, collection: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:meta"

    def _collection_ids_key(self, collection: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:ids"

    def _doc_key(self, collection: str, object_id: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:doc:{object_id}"

    def _search_index_name(self, collection: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:idx"

    def _search_doc_prefix(self, collection: str) -> str:
        return f"{self._root_prefix()}:collection:{collection}:doc:"

    def _search(self, collection: str) -> _RedisAsyncSearchProtocol:
        return cast(_RedisAsyncSearchProtocol, self._client().ft(self._search_index_name(collection)))

    @staticmethod
    def _decode_text(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    async def _collection_names(self) -> list[str]:
        values = await self._client().smembers(self._collections_key()) or []
        return sorted(self._decode_text(item) for item in values)

    @staticmethod
    def _serialize_search_fields(specs: Mapping[str, RedisScalarFieldSpec]) -> dict[str, dict[str, Any]]:
        return {
            field_path: {"kind": spec.kind}
            for field_path, spec in specs.items()
        }

    @staticmethod
    def _deserialize_search_fields(payload: object) -> dict[str, RedisScalarFieldSpec]:
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

    def _value_search_field_spec(self, field_path: str, value: object) -> RedisScalarFieldSpec | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return RedisScalarFieldSpec(field_path=field_path, kind="bool")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return RedisScalarFieldSpec(field_path=field_path, kind="numeric")
        if isinstance(value, str):
            return RedisScalarFieldSpec(field_path=field_path, kind="string")
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            items = [item for item in value if item is not None]
            if items and all(isinstance(item, (str, int, float, bool)) for item in items):
                return RedisScalarFieldSpec(field_path=field_path, kind="tag")
        return None

    def _payload_search_fields(self, collection: str, payload: Mapping[str, Any], prefix: str = "") -> dict[str, RedisScalarFieldSpec]:
        specs: dict[str, RedisScalarFieldSpec] = {"id": RedisScalarFieldSpec(field_path="id", kind="string")}
        vector_fields = set(self._vector_fields.get(collection, {}).keys())
        for raw_key, value in payload.items():
            key = str(raw_key or "").strip()
            if not key or key in {"id", "_id"} or key.startswith("_") or key in vector_fields:
                continue
            field_path = f"{prefix}.{key}" if prefix else key
            spec = self._value_search_field_spec(field_path, value)
            if spec is not None:
                specs[field_path] = spec
                continue
            if isinstance(value, Mapping):
                specs.update(self._payload_search_fields(collection, value, field_path))
        return specs

    async def _search_index_exists(self, collection: str) -> bool:
        try:
            await self._search(collection).info()
            return True
        except Exception:
            return False

    async def _load_search_fields(self, collection: str, *, refresh: bool = False) -> dict[str, RedisScalarFieldSpec]:
        if not refresh and collection in self._search_fields:
            return self._search_fields[collection]
        meta = await self._load_collection_meta(collection) or {}
        specs = self._deserialize_search_fields(meta.get("search_fields"))
        if "id" not in specs:
            specs["id"] = RedisScalarFieldSpec(field_path="id", kind="string")
        self._search_fields[collection] = specs
        return specs

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

    async def _load_collection_meta(self, collection: str) -> dict[str, Any] | None:
        payload = await self._load_json_value(self._collection_meta_key(collection))
        if isinstance(payload, Mapping):
            return dict(payload)
        return None

    async def _load_stored_schema(self, collection: str) -> dict[str, Any] | None:
        try:
            meta = await self._load_collection_meta(collection)
        except Exception:
            return None
        if meta is None:
            return None
        raw = meta.get("schema_json")
        if not raw:
            return None
        return _json_loads_dict_or_none(raw)

    async def _async_restore_collection_state(self) -> None:
        collections = await self._collection_names()
        self._known_collections.update(collections)
        for collection in collections:
            meta = await self._load_collection_meta(collection) or {}
            raw_vector_fields = meta.get("vector_fields") or {}
            raw_vector_metrics = meta.get("vector_field_metrics") or {}
            raw_vector_algorithms = meta.get("vector_field_algorithms") or {}
            raw_scalar_fields = meta.get("scalar_fields") or []
            if isinstance(raw_vector_fields, Mapping):
                self._vector_fields[collection] = {
                    str(name): int(dim)
                    for name, dim in raw_vector_fields.items()
                }
            if isinstance(raw_vector_metrics, Mapping):
                self._vector_field_metrics[collection] = {
                    str(name): _coerce_metric_type(metric, self._metric_type)
                    for name, metric in raw_vector_metrics.items()
                }
            if isinstance(raw_vector_algorithms, Mapping):
                self._vector_field_algorithms[collection] = {
                    str(name): cast(VectorIndexAlgorithm, str(algorithm).upper())
                    for name, algorithm in raw_vector_algorithms.items()
                    if str(algorithm).upper() in {"AUTOINDEX", "FLAT", "HNSW"}
                }
            if isinstance(raw_scalar_fields, list):
                self._scalar_fields[collection] = [str(item) for item in raw_scalar_fields]
            await self._load_search_fields(collection)

    async def _upsert_collection_meta(
        self,
        collection: str,
        model_cls: type[ORMModel] | None = None,
        *,
        search_fields: Mapping[str, RedisScalarFieldSpec] | None = None,
    ) -> dict[str, Any]:
        if model_cls is not None:
            self._register_model(model_cls)
        existing = await self._load_collection_meta(collection) or {}
        current_search_fields = self._deserialize_search_fields(existing.get("search_fields"))
        if search_fields is not None:
            current_search_fields.update(dict(search_fields))
        if "id" not in current_search_fields:
            current_search_fields["id"] = RedisScalarFieldSpec(field_path="id", kind="string")
        meta = {
            "collection_name": collection,
            "model_module": existing.get("model_module", model_cls.__module__ if model_cls is not None else None),
            "model_name": existing.get("model_name", model_cls.__name__ if model_cls is not None else None),
            "schema_json": existing.get("schema_json") or (model_cls.model_json_schema() if model_cls is not None else None),
            "vector_fields": dict(self._vector_fields.get(collection, {})),
            "vector_field_metrics": dict(self._vector_field_metrics.get(collection, {})),
            "vector_field_algorithms": dict(self._vector_field_algorithms.get(collection, {})),
            "scalar_fields": list(self._scalar_fields.get(collection, [])),
            "search_fields": self._serialize_search_fields(current_search_fields),
        }
        await self._store_json_value(self._collection_meta_key(collection), meta)
        await self._client().sadd(self._collections_key(), collection)
        self._mark_collection_known(collection)
        self._search_fields[collection] = current_search_fields
        return meta

    async def _reconcile_redis_vector_index(self, collection: str) -> None:
        """Compare existing Redis vector index schema with model, warn & align on mismatch."""
        try:
            info = await self._search(collection).info()
        except Exception:
            return
        info_map = info if isinstance(info, dict) else {}
        attributes = info_map.get("attributes", [])
        for attr in attributes:
            if not isinstance(attr, (list, tuple)):
                continue
            # Parse flat key-value pairs from FT.INFO attribute list
            attr_dict: dict[str, Any] = {}
            for i in range(0, len(attr) - 1, 2):
                attr_dict[str(attr[i]).lower()] = attr[i + 1]
            if str(attr_dict.get("type", "")).upper() != "VECTOR":
                continue
            identifier = str(attr_dict.get("identifier", ""))
            if not identifier.startswith("$.payload."):
                continue
            field = identifier[len("$.payload."):]
            if field not in (self._vector_fields.get(collection) or {}):
                continue

            db_dim_raw = attr_dict.get("dim")
            db_metric = str(attr_dict.get("distance_metric") or "").upper()
            db_algo = str(attr_dict.get("algorithm") or "").upper()
            model_dim = (self._vector_fields.get(collection) or {}).get(field)
            model_metric = str(self._get_field_metric(collection, field)).upper()
            try:
                model_algo = str(self._get_redis_field_algorithm(collection, field)).upper()
            except ValueError:
                model_algo = ""

            if db_dim_raw is not None and model_dim is not None and int(db_dim_raw) != int(model_dim):
                _logger.warning(
                    "Vector field '%s' dim mismatch in Redis collection '%s': "
                    "model=%d, db=%d. Aligning model to DB.",
                    field, collection, model_dim, int(db_dim_raw),
                )
                self._align_vector_field_to_db(collection, field, db_dim=int(db_dim_raw))
            if db_metric and db_metric != model_metric:
                _logger.warning(
                    "Vector field '%s' metric_type mismatch in Redis collection '%s': "
                    "model=%s, db=%s. Aligning model to DB.",
                    field, collection, model_metric, db_metric,
                )
                if db_metric in _VALID_METRIC_TYPES:
                    self._align_vector_field_to_db(collection, field, db_metric=cast(MetricType, db_metric))
            if db_algo and db_algo != model_algo:
                _logger.warning(
                    "Vector field '%s' algorithm mismatch in Redis collection '%s': "
                    "model=%s, db=%s. Aligning model to DB.",
                    field, collection, model_algo, db_algo,
                )
                if db_algo in {"FLAT", "HNSW"}:
                    self._align_vector_field_to_db(collection, field, db_algorithm=cast(VectorIndexAlgorithm, db_algo))

    async def _ensure_search_index(
        self,
        collection: str,
        *,
        model_cls: type[ORMModel] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        with nullcontext():
            current_search_fields = await self._load_search_fields(collection, refresh=True)
            desired_search_fields = dict(current_search_fields)
            if payload is not None:
                for field_path, spec in self._payload_search_fields(collection, payload).items():
                    desired_search_fields.setdefault(field_path, spec)
            vector_specs = [
                RedisVectorFieldSpec(
                    field_path=self._db_field_name(collection, field_name),
                    dim=int(dim),
                    metric_type=str(self._get_field_metric(collection, field_name)).upper(),
                    algorithm=self._get_redis_field_algorithm(collection, field_name),
                )
                for field_name, dim in self._vector_fields.get(collection, {}).items()
            ]
            if not vector_specs:
                raise ValueError(f"Collection `{collection}` has no registered vector fields.")
            missing_scalar_specs = [
                spec for field_path, spec in desired_search_fields.items()
                if field_path not in current_search_fields
            ]
            if not await self._search_index_exists(collection):
                from redis.commands.search.index_definition import IndexDefinition, IndexType

                fields: list['_RedisSearchField | _RedisVectorField'] = []
                for spec in desired_search_fields.values():
                    fields.extend(build_redis_scalar_fields(spec))
                for spec in vector_specs:
                    fields.append(build_redis_vector_field(spec))
                await self._search(collection).create_index(
                    fields,
                    definition=IndexDefinition(prefix=[self._search_doc_prefix(collection)], index_type=IndexType.JSON),
                )
                await self._upsert_collection_meta(collection, model_cls, search_fields=desired_search_fields)
                return
            # Index exists — reconcile vector schema (warn & align, do NOT modify DB).
            # Reconciliation must happen AFTER _upsert_collection_meta because that
            # calls _register_model which would overwrite aligned values.
            if missing_scalar_specs:
                fields = []
                for spec in missing_scalar_specs:
                    fields.extend(build_redis_scalar_fields(spec))
                await self._search(collection).alter_schema_add(fields)
            if model_cls is not None or missing_scalar_specs:
                await self._upsert_collection_meta(collection, model_cls, search_fields=desired_search_fields)
            await self._reconcile_redis_vector_index(collection)

    async def _load_doc_envelope(self, collection: str, object_id: str) -> dict[str, Any] | None:
        payload = await self._load_json_value(self._doc_key(collection, object_id))
        if isinstance(payload, Mapping):
            return dict(payload)
        return None

    def _payload_from_envelope(self, envelope: Mapping[str, Any], object_id: str) -> dict[str, Any]:
        raw_payload = envelope.get("payload", envelope)
        if isinstance(raw_payload, Mapping):
            payload = dict(raw_payload)
        else:
            payload = {}
        payload.setdefault("id", str(object_id))
        return payload

    async def _touch_doc(self, collection: str, object_id: str) -> None:
        try:
            await self._client().json().set(self._doc_key(collection, object_id), "$.accessed_at", _now_ts())
        except Exception:
            pass

    async def _prune_missing_document(self, collection: str, object_id: str) -> int:
        client = self._client()
        await client.srem(self._collection_ids_key(collection), object_id)
        return 1

    def _object_id_from_doc_key(self, collection: str, key: str) -> str:
        prefix = self._search_doc_prefix(collection)
        return key[len(prefix):] if key.startswith(prefix) else key

    def _payload_from_search_doc(self, collection: str, document: Any) -> dict[str, Any]:
        raw_payload = decode_redis_search_value(getattr(document, "__payload", None))
        payload: dict[str, Any]
        if isinstance(raw_payload, Mapping):
            payload = dict(raw_payload)
        else:
            payload = {}
        payload.setdefault("id", self._object_id_from_doc_key(collection, str(getattr(document, "id", ""))))
        return payload

    async def _build_query_string(self, collection: str, query: Mapping[str, Any] | None) -> str:
        mapping = self._field_name_mappings.get(collection)
        if mapping and query:
            translated: dict[str, Any] = {}
            for k, v in query.items():
                translated[_translate_field_path(str(k), mapping)] = v
            query = translated
        return compile_redis_query(query, await self._load_search_fields(collection))

    async def _iter_search_docs(
        self,
        collection: str,
        *,
        query_string: str,
        return_fields: Sequence[tuple[str, str]],
        limit: int | None,
        offset: int,
        query_params: Mapping[str, Any] | None = None,
        sort_by: str | None = None,
        sort_asc: bool = True,
    ) -> list['_RedisSearchDocument']:
        remaining = limit
        current_offset = int(offset)
        page_size = max(1, min(200, remaining if remaining is not None else 200))
        docs: list['_RedisSearchDocument'] = []
        while True:
            query = _redis_search_query(query_string).dialect(2).paging(current_offset, page_size)
            if sort_by:
                query.sort_by(sort_by, asc=sort_asc)
            for path, alias in return_fields:
                query.return_field(path, as_field=alias)
            result = await self._search(collection).search(query, query_params=dict(query_params or {}))
            page_docs = list(getattr(result, "docs", []))
            if not page_docs:
                break
            docs.extend(page_docs)
            current_offset += len(page_docs)
            if remaining is not None:
                remaining -= len(page_docs)
                if remaining <= 0:
                    break
                page_size = max(1, min(200, remaining))
            if len(page_docs) < page_size:
                break
        return docs

    @staticmethod
    def _distance_to_score(metric: str, raw_distance: float) -> float:
        metric_name = str(metric or "COSINE").upper()
        if metric_name in {"IP", "DOT"}:
            return float(raw_distance)
        return float(1.0 / (1.0 + raw_distance))

    async def collection_count(self, collection: str) -> int:
        if not await self._search_index_exists(collection):
            return 0
        result = await self._search(collection).search(_redis_search_query("*").dialect(2).paging(0, 0).no_content())
        return int(getattr(result, "total", 0) or 0)

    async def query_count(self, collection: str | type[ORMModel], query: Mapping[str, Any] | None = None) -> int:
        collection_name = self._resolve_collection(collection)
        query_string = await self._build_query_string(collection_name, query)
        result = await self._search(collection_name).search(_redis_search_query(query_string).dialect(2).paging(0, 0).no_content())
        return int(getattr(result, "total", 0) or 0)

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        if not self._started:
            self.start()
        await self._ensure_ready()
        self._register_model(model_cls)
        await self._ensure_search_index(model_cls.CollectionName, model_cls=model_cls)
        self._mark_collection_bootstrapped(model_cls.CollectionName)

    async def drop_collection(self, collection: str | type[ORMModel]) -> None:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        client = self._client()
        try:
            await self._search(collection_name).dropindex(delete_documents=True)
        except Exception:
            pass
        await client.delete(self._collection_ids_key(collection_name), self._collection_meta_key(collection_name))
        await client.srem(self._collections_key(), collection_name)
        self._collection_models.pop(collection_name, None)
        self._vector_fields.pop(collection_name, None)
        self._vector_field_metrics.pop(collection_name, None)
        self._vector_field_algorithms.pop(collection_name, None)
        self._scalar_fields.pop(collection_name, None)
        self._search_fields.pop(collection_name, None)

    async def set(
        self,
        value: ORMModel | dict[str, Any],
        *,
        collection: str | type[ORMModel] | None = None,
        expire: float | int | None = None,
    ) -> str:  # type: ignore[override]
        return await super().set(value, collection=collection, expire=expire)

    async def raw_set(
        self,
        collection: str | type[ORMModel],
        payload: VectorPayloadLike,
        *,
        expire: float | int | None = None,
    ) -> str:  # type: ignore[override]
        if not self._started:
            self.start()
        await self._ensure_ready()
        collection_name = self._resolve_collection(collection)
        model_cls: type[ORMModel] | None = collection if isinstance(collection, type) and issubclass(collection, ORMModel) else None
        if model_cls is not None:
            self._register_model(model_cls)
        elif collection_name not in self._vector_fields:
            raise ValueError(
                f"Collection `{collection_name}` is not registered. "
                "Call create_collection() with ORMModel first."
            )
        collection_name, payload, _ = self._normalize_value(payload, collection=collection_name)

        for field_name, dim in self._vector_fields.get(collection_name, {}).items():
            vector = payload.get(field_name)
            if isinstance(vector, np.ndarray):
                vector = normalize_vector_embedding(vector)
                payload[field_name] = vector
            if not isinstance(vector, list):
                raise ValueError(f"Vector field `{field_name}` must be a list[float].")
            if dim and len(vector) != dim:
                raise ValueError(
                    f"Vector field `{field_name}` dimension mismatch: expected {dim}, got {len(vector)}."
                )
            payload[field_name] = [float(item) for item in vector]

        mapping = self._field_name_mappings.get(collection_name, {})
        db_payload = remap_payload_to_db(payload, mapping) if mapping else payload
        await self._ensure_search_index(collection_name, model_cls=model_cls, payload=db_payload)

        object_id = str(payload.get("id") or payload.get("_id"))
        now = _now_ts()
        envelope = {
            "payload": db_payload,
            "size": len(_json_dumps(db_payload).encode("utf-8")),
            "accessed_at": now,
        }
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        ttl = None if expire_at is None else max(1, int(expire_at - now))
        await self._store_json_value(self._doc_key(collection_name, object_id), envelope, ttl=ttl)
        client = self._client()
        await client.sadd(self._collection_ids_key(collection_name), object_id)
        await client.sadd(self._collections_key(), collection_name)

        await self.cleanup()
        return object_id

    async def set_many(
        self,
        values: Sequence[ORMModel | dict[str, Any]],
        *,
        collection: str | type[ORMModel] | None = None,
        expire: float | int | None = None,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []
        if not self._started:
            self.start()
        await self._ensure_ready()

        collection_resolved = self._resolve_collection(collection) if collection is not None else None
        collection_name: str | None = None
        payloads: list[dict[str, Any]] = []
        model_cls: type[ORMModel] | None = None
        for value in batch:
            current_collection, payload, current_model_cls = self._normalize_value(value, collection=collection_resolved)
            if collection_name is None:
                collection_name = current_collection
            elif collection_name != current_collection:
                raise ValueError('VectorClient.set_many() requires all values to target the same collection.')
            if model_cls is None and current_model_cls is not None:
                model_cls = current_model_cls
            payloads.append(payload)

        assert collection_name is not None
        if model_cls is not None:
            self._register_model(model_cls)
        elif collection_name not in self._vector_fields:
            raise ValueError(
                f"Collection `{collection_name}` is not registered. "
                "Call create_collection() with ORMModel first."
            )

        for payload in payloads:
            for field_name, dim in self._vector_fields.get(collection_name, {}).items():
                vector = payload.get(field_name)
                if isinstance(vector, np.ndarray):
                    vector = normalize_vector_embedding(vector)
                    payload[field_name] = vector
                if not isinstance(vector, list):
                    raise ValueError(f"Vector field `{field_name}` must be a list[float].")
                if dim and len(vector) != dim:
                    raise ValueError(
                        f"Vector field `{field_name}` dimension mismatch: expected {dim}, got {len(vector)}."
                    )
                payload[field_name] = [float(item) for item in vector]

        mapping = self._field_name_mappings.get(collection_name, {})
        if model_cls is not None:
            await self._ensure_search_index(collection_name, model_cls=model_cls)
        for payload in payloads:
            db_payload = remap_payload_to_db(payload, mapping) if mapping else payload
            await self._ensure_search_index(collection_name, payload=db_payload)

        client = self._client()
        pipe = client.pipeline()
        now = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        ids_key = self._collection_ids_key(collection_name)
        collections_key = self._collections_key()
        object_ids: list[str] = []
        for payload in payloads:
            object_id = str(payload.get("id") or payload.get("_id"))
            object_ids.append(object_id)
            db_payload = remap_payload_to_db(payload, mapping) if mapping else payload
            envelope = {
                "payload": db_payload,
                "size": len(_json_dumps(db_payload).encode("utf-8")),
                "accessed_at": now,
            }
            ttl = None if expire_at is None else max(1, int(expire_at - now))
            doc_key = self._doc_key(collection_name, object_id)
            pipe.json().set(doc_key, "$", envelope)
            if ttl is None:
                pipe.persist(doc_key)
            else:
                pipe.expire(doc_key, ttl)
            pipe.sadd(ids_key, object_id)
        pipe.sadd(collections_key, collection_name)
        await pipe.execute()

        await self.cleanup()
        return object_ids

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[True] = True) -> T | None: ...

    @overload
    async def get[T: "VectorORMModel"](self, collection: type[T], object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: type[ORMModel], object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: str, object_id: str, *, as_model: Literal[False]) -> dict[str, Any] | None: ...

    async def get(self, collection: str | type[ORMModel], object_id: str, *, as_model: bool = True) -> HydratedVectorDocument | None:  # type: ignore[override]
        return await super().get(collection, object_id, as_model=as_model)

    async def raw_get(self, collection: str | type[ORMModel], object_id: str) -> dict[str, Any] | None:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        object_id_text = str(object_id)
        envelope = await self._load_doc_envelope(collection_name, object_id_text)
        if envelope is None:
            await self._prune_missing_document(collection_name, object_id_text)
            return None
        payload = self._payload_from_envelope(envelope, object_id_text)
        await self._touch_doc(collection_name, object_id_text)
        mapping = self._field_name_mappings.get(collection_name, {})
        return remap_payload_from_db(payload, mapping) if mapping else payload

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search(self, collection: str, query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: str, query: Mapping[str, Any] | None = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    async def search(
        self,
        collection: str | type[ORMModel],
        query: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:  # type: ignore[override]
        async for item in super().search(collection, query=query, limit=limit, offset=offset, as_model=as_model):
            yield item

    async def raw_query(
        self,
        collection: str | type[ORMModel],
        query: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        query_string = await self._build_query_string(collection_name, query)
        mapping = self._field_name_mappings.get(collection_name, {})
        docs = await self._iter_search_docs(
            collection_name,
            query_string=query_string,
            return_fields=[("$.payload", "__payload")],
            limit=limit,
            offset=offset,
        )
        for document in docs:
            payload = self._payload_from_search_doc(collection_name, document)
            object_id = str(payload.get("_id") or self._object_id_from_doc_key(collection_name, str(getattr(document, "id", ""))))
            await self._touch_doc(collection_name, object_id)
            yield remap_payload_from_db(payload, mapping) if mapping else payload

    @overload
    def search_sorted[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search_sorted[T: "VectorORMModel"](self, collection: type[T], query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_sorted(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_sorted(self, collection: type[ORMModel], query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_sorted(self, collection: str, query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_sorted(self, collection: str, query: Mapping[str, Any] | None = None, *, sort: Sequence[tuple[str, str]], limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    async def search_sorted(
        self,
        collection: str | type[ORMModel],
        query: Mapping[str, Any] | None = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:
        collection_name = self._resolve_collection(collection)
        sort_items = [(str(field or "").strip(), str(direction or "asc").lower()) for field, direction in sort if str(field or "").strip()]
        if not sort_items:
            async for item in self.search(collection, query=query, limit=limit, offset=offset, as_model=as_model):
                yield item
            return
        if len(sort_items) != 1:
            raise RedisSearchQueryError("Redis vector native sort currently supports exactly one sort field.")
        sort_field, sort_direction = sort_items[0]
        db_sort_field = _translate_field_path(sort_field, self._field_name_mappings.get(collection_name, {}))
        spec = (await self._load_search_fields(collection_name)).get(db_sort_field)
        if spec is None:
            raise RedisSearchQueryError(f"Redis sort field `{sort_field}` is not indexed.")
        docs = await self._iter_search_docs(
            collection_name,
            query_string=await self._build_query_string(collection_name, query),
            return_fields=[("$.payload", "__payload")],
            limit=limit,
            offset=offset,
            sort_by=redis_scalar_sort_alias(spec),
            sort_asc=sort_direction != "desc",
        )
        for document in docs:
            payload = self._payload_from_search_doc(collection_name, document)
            object_id = str(payload.get("_id") or self._object_id_from_doc_key(collection_name, str(getattr(document, "id", ""))))
            await self._touch_doc(collection_name, object_id)
            yield await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

    async def selected_search(
        self,
        collection: str | type[ORMModel],
        *,
        fields: Sequence[str],
        query: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        collection_name = self._resolve_collection(collection)
        normalized_fields = _normalize_selected_fields(fields)
        query_string = await self._build_query_string(collection_name, query)
        mapping = self._field_name_mappings.get(collection_name, {})
        return_fields: list[tuple[str, str]] = []
        alias_pairs: list[tuple[str, str]] = []
        for index, field in enumerate(normalized_fields):
            alias = "__id" if field in {"id", "_id"} else f"__sel_{index}"
            db_field = _translate_field_path(field, mapping) if mapping else field
            return_fields.append((redis_payload_json_path(db_field), alias))
            alias_pairs.append((field, alias))
        docs = await self._iter_search_docs(
            collection_name,
            query_string=query_string,
            return_fields=return_fields,
            limit=limit,
            offset=offset,
        )
        for document in docs:
            pairs: list[tuple[str, object]] = []
            for field, alias in alias_pairs:
                raw_value = getattr(document, alias, None)
                if field in {"id", "_id"} and raw_value is None:
                    raw_value = self._object_id_from_doc_key(collection_name, str(getattr(document, "id", "")))
                pairs.append((field, decode_redis_search_value(raw_value)))
            yield _project_selected_pairs(pairs)

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[T, None]: ...

    @overload
    def search_vector[T: "VectorORMModel"](self, collection: type[T], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: type[ORMModel], vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_vector(self, collection: str, vector: VectorSearchInput, *, field: str | None = None, limit: int = 10, query: Mapping[str, Any] | None = None, as_model: Literal[False]) -> AsyncGenerator[dict[str, Any], None]: ...

    async def search_vector(
        self,
        collection: str | type[ORMModel],
        vector: VectorSearchInput,
        *,
        field: str | None = None,
        limit: int = 10,
        query: Mapping[str, Any] | None = None,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedVectorDocument, None]:  # type: ignore[override]
        collection_name, field_name, query_vector = await self._resolve_search_vector(collection, vector, field=field)
        base_query = await self._build_query_string(collection_name, query)
        db_field = self._db_field_name(collection_name, field_name)
        vector_alias = redis_vector_alias(db_field)
        query_string = (
            f"{base_query}=>[KNN {int(limit)} @{vector_alias} $vector AS score]"
            if base_query != "*"
            else f"*=>[KNN {int(limit)} @{vector_alias} $vector AS score]"
        )
        docs = await self._iter_search_docs(
            collection_name,
            query_string=query_string,
            return_fields=[("$.payload", "__payload"), ("score", "score")],
            limit=limit,
            offset=0,
            query_params={"vector": vector_query_param_bytes(query_vector)},
            sort_by="score",
            sort_asc=True,
        )
        metric = str(self._get_field_metric(collection_name, field_name)).upper()
        for document in docs:
            payload = self._payload_from_search_doc(collection_name, document)
            raw_distance = _coerce_float(decode_redis_search_value(getattr(document, "score", 0.0))) or 0.0
            payload["_score"] = self._distance_to_score(metric, raw_distance)
            object_id = str(payload.get("_id") or self._object_id_from_doc_key(collection_name, str(getattr(document, "id", ""))))
            await self._touch_doc(collection_name, object_id)
            yield await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

    async def delete(self, collection: str | type[ORMModel], object_id: str) -> bool:  # type: ignore[override]
        return await super().delete(collection, object_id)

    async def raw_delete(self, collection: str | type[ORMModel], object_id: str) -> bool:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
        object_id_text = str(object_id)
        client = self._client()
        removed = await client.delete(self._doc_key(collection_name, object_id_text))
        await client.srem(self._collection_ids_key(collection_name), object_id_text)
        return bool(removed)

    async def delete_many(self, collection: str | type[ORMModel], object_ids: Iterable[str]) -> dict[str, bool]:
        collection_name = self._resolve_collection(collection)
        ids = [str(object_id or "").strip() for object_id in object_ids]
        ids = [object_id for object_id in ids if object_id]
        if not ids:
            return {}
        await self._ensure_ready()
        client = self._client()
        exists_pipe = client.pipeline(transaction=False)
        for object_id in ids:
            exists_pipe.exists(self._doc_key(collection_name, object_id))
        exists_results = await exists_pipe.execute()
        ids_key = self._collection_ids_key(collection_name)
        delete_pipe = client.pipeline(transaction=False)
        for object_id in ids:
            delete_pipe.delete(self._doc_key(collection_name, object_id))
            delete_pipe.srem(ids_key, object_id)
        await delete_pipe.execute()
        return {
            object_id: bool(exists_results[index])
            for index, object_id in enumerate(ids)
        }

    async def set_expire(self, collection: str | type[ORMModel], object_id: str, expire: float | int | None) -> bool:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
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
            await client.json().set(doc_key, "$.expire_at", _normalize_expire_at(expire))
        except Exception:
            pass
        return updated

    async def get_expire(self, collection: str | type[ORMModel], object_id: str) -> float | None:  # type: ignore[override]
        collection_name = self._resolve_collection(collection)
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
            total_size = 0
            live_rows: list[tuple[str, str, int, float]] = []
            for collection_name in await self._collection_names():
                object_ids = [self._decode_text(item) for item in await self._client().smembers(self._collection_ids_key(collection_name)) or []]
                if not object_ids:
                    continue
                # Batch-load all doc envelopes via pipeline instead of N+1 round trips.
                client = self._client()
                doc_keys = [self._doc_key(collection_name, oid) for oid in object_ids]
                pipe = client.pipeline(transaction=False)
                for dk in doc_keys:
                    pipe.json().get(dk)
                results = await pipe.execute()
                orphaned: list[str] = []
                for object_id, payload in zip(object_ids, results):
                    if payload is None or not isinstance(payload, Mapping):
                        orphaned.append(object_id)
                        continue
                    envelope = dict(payload)
                    size = int(envelope.get("size") or 0)
                    accessed_at = float(envelope.get("accessed_at") or 0.0)
                    total_size += size
                    live_rows.append((collection_name, object_id, size, accessed_at))
                for oid in orphaned:
                    removed += await self._prune_missing_document(collection_name, oid)
            total_count = len(live_rows)
            if self._max_size is not None and len(live_rows) > self._max_size:
                target = max(0, int(self._max_size * 0.9))
                client = self._client()
                evict_by_collection: dict[str, list[str]] = {}
                for collection_name, object_id, size, _ in sorted(live_rows, key=lambda item: item[3]):
                    if total_count <= target:
                        break
                    evict_by_collection.setdefault(collection_name, []).append(object_id)
                    total_count -= 1
                    removed += 1
                pipe = client.pipeline(transaction=False)
                for collection_name, ids in evict_by_collection.items():
                    ids_key = self._collection_ids_key(collection_name)
                    for object_id in ids:
                        pipe.delete(self._doc_key(collection_name, object_id))
                        pipe.srem(ids_key, object_id)
                await pipe.execute()
            await self._mark_cleanup_async()
            return removed


__all__ = [
    "VectorEmbeddingContent",
    "VectorEmbeddingVector",
    "VectorSearchInput",
    "VectorEmbedder",
    "call_vector_embedder",
    "normalize_vector_embedding",
    "resolve_vector_embedder",
    "MetricType",
    "VectorIndexAlgorithm",
    "VectorIndex",
    "MilvusLiteVectorClient",
    "MilvusLiteVectorClientInitParams",
    "PyMilvusVectorClient",
    "PyMilvusVectorClientInitParams",
    "MongoVectorClient",
    "MongoVectorClientInitParams",
    "RedisVectorClient",
    "RedisVectorClientInitParams",
    "VectorClientBase",
    "VectorClientInitParams",
    "VectorORMFieldInfo",
    "VectorORMField",
    "VectorORMModel",
    "VectorModelT",
    "AnnoySQLiteVectorClient",
    "AnnoySQLiteVectorClientInitParams",
]
