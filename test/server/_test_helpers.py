# -*- coding: utf-8 -*-
"""
Shared test helpers for server API tests.

Provides base test-case classes that spin up a lightweight FastAPI app
with only the routes needed for each test domain, backed by temporary
SQLite / local-filesystem storage.

Usage (in any test file)::

    from _test_helpers import StorageKVTestBase

    class TestKVAPI(StorageKVTestBase):
        async def test_something(self):
            resp = await self._client.get("/_internal/admin/api/storage/kv/config")
            self.assertEqual(resp.status_code, 200)
"""


import asyncio
import sys
import os
import httpx 
import logging
import tempfile
import time
import types
import unittest
import importlib
import unittest.mock as unittest_mock

from fastapi import FastAPI 
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Callable, Mapping
from pydantic import ConfigDict

# ── ensure project root + app dir are importable ──────────────────────────
_project_root = Path(__file__).resolve().parent.parent.parent
_app_dir = _project_root / "app"

for _p in (str(_project_root), str(_app_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Silence noisy loggers during tests
logging.getLogger("proj-template").setLevel(logging.WARNING)
logging.getLogger("core").setLevel(logging.WARNING)

# Avoid unrelated top-level core imports when storage tests only need storage modules.
# Eager imports disabled for tests (legacy env var removed)

# Atlas Local advertises an internal replica-set hostname on Windows hosts.
# Pin test clients to the published localhost endpoint.
MONGO_TEST_URL = os.getenv("PROJ_TEST_MONGO_URL", "mongodb://127.0.0.1:27017/?directConnection=true")
_MILVUS_TEST_DB_PREFIXES = ("milvus_vector_", "vitest_")
_STORAGE_CONFIG_ENV = "__STORAGE_CONFIG__"

# ── imports that need the path setup ─────────────────────────────────────────
from core.storage.config import ( 
    StorageConfig,
    KV_StorageConfig,
    ORMStorageConfig,
    ObjectStorageConfig,
    VectorStorageConfig,
    EtcdKVDBConfig,
    LocalKVDBConfig,
    RedisKVDBConfig,
    LocalObjectDBConfig,
    MySQL_ORM_DB_Config,
    MinIO_ObjectDB_Config,
    MongoORM_DB_Config,
    PostgreSQL_ORM_DB_Config,
    RedisORMDBConfig,
    RedisVectorDBConfig,
    SQLiteORMDBConfig,
    MilvusVectorDBConfig,
    MilvusLiteVectorDBConfig,
    AnnoyVectorDBConfig,
    MongoVectorDBConfig,
    _default_vector_backend,
)


def _restore_storage_global(config: StorageConfig | None, env_value: str | None) -> None:
    if config is not None:
        StorageConfig.SetGlobal(config)
        return
    StorageConfig.__Instance__ = None
    if hasattr(StorageConfig, "_StorageConfig__Instance__"):
        delattr(StorageConfig, "_StorageConfig__Instance__")
    if env_value is None:
        os.environ.pop(_STORAGE_CONFIG_ENV, None)
    else:
        os.environ[_STORAGE_CONFIG_ENV] = env_value
    try:
        from core.storage.base import StorageClientBase
        StorageClientBase.ClearDefaultInstances()
        from core.storage.orm import ORMModel
        ORMModel.ResetClientBindings()
    except Exception:
        pass


def _restore_config_global(config: object | None) -> None:
    try:
        from core.server.data_types.config import Config
        Config.__Instance__ = config
        if hasattr(Config, "_Config__Instance__"):
            delattr(Config, "_Config__Instance__")
    except Exception:
        pass
from core.storage.vector import (  
    VectorORMFieldInfo,
    call_vector_embedder,
    normalize_vector_embedding,
    resolve_vector_embedder,
)


async def _fake_tts_embedding_impl(self, inputs, **kwargs):
    return [[0.0, 0.0, 0.0] for _ in inputs]


def _patch_vector_embedding_service():
    module = importlib.import_module("core.server.routes.storage.vector")
    return unittest_mock.patch.object(
        module,
        "_get_embedding_service",
        side_effect=RuntimeError("EmbeddingService unavailable in tests"),
    )


_TEST_ORM_MODELS: dict[str, type] = {}


def _infer_test_orm_annotation(value: object) -> object:
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    if isinstance(value, str):
        return str
    if isinstance(value, list):
        return list[object]
    if isinstance(value, dict):
        return dict[str, object]
    if value is None:
        return object | None
    return object


def ensure_test_orm_model(collection: str, sample: Mapping[str, object] | None = None):
    from core.storage.orm import ORMModel

    collection_name = str(collection or "").strip()
    if not collection_name:
        raise ValueError("collection is required")

    cached = _TEST_ORM_MODELS.get(collection_name)
    if cached is not None:
        return cached

    annotations: dict[str, object] = {}
    attrs: dict[str, object] = {
        "__module__": __name__,
        "model_config": ConfigDict(
            populate_by_name=True,
            protected_namespaces=(),
            arbitrary_types_allowed=True,
            validate_assignment=True,
            extra="allow",
        ),
    }
    for field_name, value in (sample or {}).items():
        if field_name in {"id", "_id"} or field_name.startswith("_"):
            continue
        annotations[field_name] = _infer_test_orm_annotation(value) | None
        attrs[field_name] = None
    attrs["__annotations__"] = annotations

    model_name = "_TestORM_" + "".join(ch if ch.isalnum() else "_" for ch in collection_name)

    def _exec_body(ns: dict[str, object]) -> None:
        ns.update(attrs)

    model_cls = types.new_class(
        model_name,
        (ORMModel,),
        {"collection_name": collection_name},
        _exec_body,
    )
    _TEST_ORM_MODELS[collection_name] = model_cls
    return model_cls


def _milvus_db_name_from_namespace(namespace: str) -> str:
    sanitized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(namespace or "default"))
    if not sanitized or not (sanitized[0].isalpha() or sanitized[0] == "_"):
        sanitized = f"ns_{sanitized}"
    return sanitized[:255]


def milvus_vector_database_names(storage_config: StorageConfig | None) -> list[str]:
    if storage_config is None:
        return []
    names: list[str] = []
    for cfg in (storage_config.vector.default, storage_config.vector.cache):
        if not isinstance(cfg, MilvusVectorDBConfig):
            continue
        namespace = getattr(cfg, "namespace", None)
        if not isinstance(namespace, str) or not namespace.strip() or namespace == "default":
            continue
        db_name = _milvus_db_name_from_namespace(namespace)
        if db_name not in names:
            names.append(db_name)
    return names


def cleanup_milvus_test_databases(storage_config: StorageConfig | None = None, *, prune_stale: bool = False) -> None:
    from pymilvus import connections, db, utility

    alias = f"proj-test-milvus-cleanup-{os.getpid()}-{int(time.time() * 1000)}"
    uri = os.getenv("proj_test_MILVUS_URI", "http://127.0.0.1:19530")
    token = os.getenv("proj_test_MILVUS_TOKEN", None) or None
    target_names = set(milvus_vector_database_names(storage_config))

    def _drop_database(name: str) -> None:
        db_alias = f"{alias}-db-{name}"
        try:
            connections.connect(alias=db_alias, uri=uri, token=token, db_name=name)
            for collection_name in list(utility.list_collections(using=db_alias) or []):
                try:
                    utility.drop_collection(collection_name, using=db_alias)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                connections.disconnect(db_alias)
            except Exception:
                pass
        try:
            db.drop_database(name, using=alias)
        except Exception:
            pass

    connections.connect(alias=alias, uri=uri, token=token)
    try:
        existing = {str(name) for name in (db.list_database(using=alias) or [])}
        if prune_stale:
            for name in sorted(existing):
                if name == "default" or name in target_names:
                    continue
                if not any(name.startswith(prefix) for prefix in _MILVUS_TEST_DB_PREFIXES):
                    continue
                _drop_database(name)
        for name in sorted(target_names):
            if name not in existing:
                continue
            _drop_database(name)
    finally:
        try:
            connections.disconnect(alias)
        except Exception:
            pass


def register_test_orm_model(client: object, collection: str, sample: Mapping[str, object] | None = None):
    model_cls = ensure_test_orm_model(collection, sample)
    register = getattr(client, "register_model", None)
    if callable(register):
        register(model_cls)
    return model_cls


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_storage_config(tmp: str) -> StorageConfig:
    """Create a minimal StorageConfig backed by temp directories."""
    if _default_vector_backend() == "annoy":
        vector_default = AnnoyVectorDBConfig(db_dir=str(Path(tmp) / "vector_annoy"))
        vector_cache = AnnoyVectorDBConfig(db_dir=str(Path(tmp) / "vector_cache_annoy"))
    else:
        vector_default = MilvusLiteVectorDBConfig(db_path=str(Path(tmp) / "vector_milvus_lite.db"))  # type: ignore[assignment]
        vector_cache = MilvusLiteVectorDBConfig(db_path=str(Path(tmp) / "vector_cache_milvus_lite.db"))  # type: ignore[assignment]
    return StorageConfig(
        kv=KV_StorageConfig(
            default=LocalKVDBConfig(db_path=str(Path(tmp) / "kv.sqlite3")),
            cache=LocalKVDBConfig(db_path=str(Path(tmp) / "kv_cache.sqlite3")),
        ),
        orm=ORMStorageConfig(
            default=SQLiteORMDBConfig(db_path=str(Path(tmp) / "orm.sqlite3")),
            cache=SQLiteORMDBConfig(db_path=str(Path(tmp) / "orm_cache.sqlite3")),
            log=SQLiteORMDBConfig(db_path=str(Path(tmp) / "log.sqlite3")),
        ),
        object=ObjectStorageConfig(
            default=LocalObjectDBConfig(root_path=str(Path(tmp) / "objects")),
            cache=LocalObjectDBConfig(root_path=str(Path(tmp) / "objects_cache")),
        ),
        vector=VectorStorageConfig(
            default=vector_default,
            cache=vector_cache,
        ),
    )


def _make_redis_kv_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    tmp_name = Path(tmp).name.replace("_", "-")
    return StorageConfig(
        kv=KV_StorageConfig(
            default=RedisKVDBConfig(
                url="redis://127.0.0.1:6379/0",
                prefix=f"test:kv-api:{tmp_name}:default",
                namespace=f"redis-{tmp_name}-default",
            ),
            cache=RedisKVDBConfig(
                url="redis://127.0.0.1:6379/0",
                prefix=f"test:kv-api:{tmp_name}:cache",
                namespace=f"redis-{tmp_name}-cache",
            ),
        ),
        orm=base.orm,
        object=base.object,
        vector=base.vector,
    )

def _make_etcd_kv_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    tmp_name = Path(tmp).name.replace("_", "-")
    etcd_port = int(os.getenv("proj_test_ETCD_PORT", "23791"))
    return StorageConfig(
        kv=KV_StorageConfig(
            default=EtcdKVDBConfig(
                host="127.0.0.1",
                port=etcd_port,
                protocol="http",
                prefix=f"test:kv-api:{tmp_name}:default",
                namespace=f"etcd-{tmp_name}-default",
            ),
            cache=EtcdKVDBConfig(
                host="127.0.0.1",
                port=etcd_port,
                protocol="http",
                prefix=f"test:kv-api:{tmp_name}:cache",
                namespace=f"etcd-{tmp_name}-cache",
            ),
        ),
        orm=base.orm,
        object=base.object,
        vector=base.vector,
    )


def _make_redis_orm_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    tmp_name = Path(tmp).name.replace("_", "-")
    return StorageConfig(
        kv=base.kv,
        orm=ORMStorageConfig(
            default=RedisORMDBConfig(
                url="redis://127.0.0.1:6379/0",
                prefix=f"test:orm-api:{tmp_name}:default",
                namespace=f"redis-orm-{tmp_name}-default",
            ),
            cache=RedisORMDBConfig(
                url="redis://127.0.0.1:6379/0",
                prefix=f"test:orm-api:{tmp_name}:cache",
                namespace=f"redis-orm-{tmp_name}-cache",
            ),
            log=RedisORMDBConfig(
                url="redis://127.0.0.1:6379/0",
                prefix=f"test:orm-api:{tmp_name}:log",
                namespace=f"redis-orm-{tmp_name}-log",
            ),
        ),
        object=base.object,
        vector=base.vector,
    )


def _make_mongo_orm_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    tmp_name = Path(tmp).name.replace("_", "-")
    default_db = f"proj_test_mongo_orm_{tmp_name}"
    cache_db = f"proj_test_mongo_orm_{tmp_name}_cache"
    log_db = f"proj_test_mongo_orm_{tmp_name}_log"
    return StorageConfig(
        kv=base.kv,
        orm=ORMStorageConfig(
            default=MongoORM_DB_Config(
                url=MONGO_TEST_URL,
                database=default_db,
                namespace=f"mongo-orm-{tmp_name}-default",
            ),
            cache=MongoORM_DB_Config(
                url=MONGO_TEST_URL,
                database=cache_db,
                namespace=f"mongo-orm-{tmp_name}-cache",
            ),
            log=MongoORM_DB_Config(
                url=MONGO_TEST_URL,
                database=log_db,
                namespace=f"mongo-orm-{tmp_name}-log",
            ),
        ),
        object=base.object,
        vector=base.vector,
    )


def _make_mysql_orm_storage_config(tmp: str) -> StorageConfig:
    tmp_name = Path(tmp).name.replace("_", "-")
    default_db = f"proj_test_orm_{tmp_name}"
    cache_db = f"proj_test_orm_{tmp_name}_cache"
    log_db = f"proj_test_orm_{tmp_name}_log"
    mysql_port = int(os.getenv("proj_test_MYSQL_PORT", "3307"))
    mysql_user = os.getenv("proj_test_MYSQL_USER", "root")
    mysql_password = os.getenv("proj_test_MYSQL_PASSWORD", "rootpass")
    if _default_vector_backend() == "annoy":
        vector_default = AnnoyVectorDBConfig(db_dir=str(Path(tmp) / "vector_annoy"))
        vector_cache = AnnoyVectorDBConfig(db_dir=str(Path(tmp) / "vector_cache_annoy"))
    else:
        vector_default = MilvusLiteVectorDBConfig(db_path=str(Path(tmp) / "vector_milvus_lite.db"))  # type: ignore[assignment]
        vector_cache = MilvusLiteVectorDBConfig(db_path=str(Path(tmp) / "vector_cache_milvus_lite.db"))  # type: ignore[assignment]
    return StorageConfig(
        kv=KV_StorageConfig(
            default=LocalKVDBConfig(db_path=str(Path(tmp) / "kv.sqlite3")),
            cache=LocalKVDBConfig(db_path=str(Path(tmp) / "kv_cache.sqlite3")),
        ),
        orm=ORMStorageConfig(
            default=MySQL_ORM_DB_Config(
                host="127.0.0.1",
                port=mysql_port,
                username=mysql_user,
                password=mysql_password,
                database=default_db,
                namespace=f"mysql-orm-{tmp_name}-default",
            ),
            cache=MySQL_ORM_DB_Config(
                host="127.0.0.1",
                port=mysql_port,
                username=mysql_user,
                password=mysql_password,
                database=cache_db,
                namespace=f"mysql-orm-{tmp_name}-cache",
            ),
            log=MySQL_ORM_DB_Config(
                host="127.0.0.1",
                port=mysql_port,
                username=mysql_user,
                password=mysql_password,
                database=log_db,
                namespace=f"mysql-orm-{tmp_name}-log",
            ),
        ),
        object=ObjectStorageConfig(
            default=LocalObjectDBConfig(root_path=str(Path(tmp) / "objects")),
            cache=LocalObjectDBConfig(root_path=str(Path(tmp) / "objects_cache")),
        ),
        vector=VectorStorageConfig(
            default=vector_default,
            cache=vector_cache,
        ),
    )


def _make_postgresql_orm_storage_config(tmp: str) -> StorageConfig:
    tmp_name = Path(tmp).name.replace("-", "_").replace(".", "_")
    default_db = f"proj_test_orm_{tmp_name}"
    cache_db = f"proj_test_orm_{tmp_name}_cache"
    log_db = f"proj_test_orm_{tmp_name}_log"
    pg_port = int(os.getenv("proj_test_POSTGRES_PORT", "5433"))
    pg_user = os.getenv("proj_test_POSTGRES_USER", "postgres")
    pg_password = os.getenv("proj_test_POSTGRES_PASSWORD", "postgres")
    if _default_vector_backend() == "annoy":
        vector_default = AnnoyVectorDBConfig(db_dir=str(Path(tmp) / "vector_annoy"))
        vector_cache = AnnoyVectorDBConfig(db_dir=str(Path(tmp) / "vector_cache_annoy"))
    else:
        vector_default = MilvusLiteVectorDBConfig(db_path=str(Path(tmp) / "vector_milvus_lite.db"))  # type: ignore[assignment]
        vector_cache = MilvusLiteVectorDBConfig(db_path=str(Path(tmp) / "vector_cache_milvus_lite.db"))  # type: ignore[assignment]
    return StorageConfig(
        kv=KV_StorageConfig(
            default=LocalKVDBConfig(db_path=str(Path(tmp) / "kv.sqlite3")),
            cache=LocalKVDBConfig(db_path=str(Path(tmp) / "kv_cache.sqlite3")),
        ),
        orm=ORMStorageConfig(
            default=PostgreSQL_ORM_DB_Config(
                host="127.0.0.1",
                port=pg_port,
                username=pg_user,
                password=pg_password,
                database=default_db,
                namespace=f"postgres-orm-{tmp_name}-default",
            ),
            cache=PostgreSQL_ORM_DB_Config(
                host="127.0.0.1",
                port=pg_port,
                username=pg_user,
                password=pg_password,
                database=cache_db,
                namespace=f"postgres-orm-{tmp_name}-cache",
            ),
            log=PostgreSQL_ORM_DB_Config(
                host="127.0.0.1",
                port=pg_port,
                username=pg_user,
                password=pg_password,
                database=log_db,
                namespace=f"postgres-orm-{tmp_name}-log",
            ),
        ),
        object=ObjectStorageConfig(
            default=LocalObjectDBConfig(root_path=str(Path(tmp) / "objects")),
            cache=LocalObjectDBConfig(root_path=str(Path(tmp) / "objects_cache")),
        ),
        vector=VectorStorageConfig(
            default=vector_default,
            cache=vector_cache,
        ),
    )


def _make_minio_object_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    tmp_name = Path(tmp).name.replace("_", "-").lower()
    bucket = f"proj-test-{tmp_name}"[:50].strip("-") or "proj-test-bucket"
    return StorageConfig(
        kv=base.kv,
        orm=base.orm,
        object=ObjectStorageConfig(
            default=MinIO_ObjectDB_Config(
                endpoint=os.getenv("proj_test_MINIO_ENDPOINT", "127.0.0.1:9002"),
                access_key=os.getenv("proj_test_MINIO_ACCESS_KEY", "minioadmin"),
                secret_key=os.getenv("proj_test_MINIO_SECRET_KEY", "minioadmin"),
                bucket=bucket,
                secure=False,
                namespace=f"minio-object-{tmp_name}-default",
                metadata_db=LocalKVDBConfig(db_path=str(Path(tmp) / "minio_objects_meta.sqlite3"), namespace=f"minio-object-{tmp_name}:meta"),
            ),
            cache=MinIO_ObjectDB_Config(
                endpoint=os.getenv("proj_test_MINIO_ENDPOINT", "127.0.0.1:9002"),
                access_key=os.getenv("proj_test_MINIO_ACCESS_KEY", "minioadmin"),
                secret_key=os.getenv("proj_test_MINIO_SECRET_KEY", "minioadmin"),
                bucket=f"{bucket}-cache"[:50].strip("-") or "proj-test-cache",
                secure=False,
                namespace=f"minio-object-{tmp_name}-cache",
                metadata_db=LocalKVDBConfig(db_path=str(Path(tmp) / "minio_objects_cache_meta.sqlite3"), namespace=f"minio-object-{tmp_name}:cache-meta"),
            ),
        ),
        vector=base.vector,
    )


def _make_redis_vector_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    tmp_name = Path(tmp).name.replace("_", "-")
    return StorageConfig(
        kv=base.kv,
        orm=base.orm,
        object=base.object,
        vector=VectorStorageConfig(
            default=RedisVectorDBConfig(
                url="redis://127.0.0.1:6379/0",
                prefix=f"test:vector-api:{tmp_name}:default",
                namespace=f"redis-vector-{tmp_name}-default",
            ),
            cache=RedisVectorDBConfig(
                url="redis://127.0.0.1:6379/0",
                prefix=f"test:vector-api:{tmp_name}:cache",
                namespace=f"redis-vector-{tmp_name}-cache",
            ),
        ),
    )


def _make_mongo_vector_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    tmp_name = Path(tmp).name.replace("_", "-")
    default_db = f"proj_test_vector_{tmp_name}"
    cache_db = f"proj_test_vector_{tmp_name}_cache"
    return StorageConfig(
        kv=base.kv,
        orm=base.orm,
        object=base.object,
        vector=VectorStorageConfig(
            default=MongoVectorDBConfig(
                url=MONGO_TEST_URL,
                database=default_db,
                namespace=f"mongo-vector-{tmp_name}-default",
            ),
            cache=MongoVectorDBConfig(
                url=MONGO_TEST_URL,
                database=cache_db,
                namespace=f"mongo-vector-{tmp_name}-cache",
            ),
        ),
    )


def _make_milvus_vector_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    tmp_name = Path(tmp).name.replace("_", "-")
    uri = os.getenv("proj_test_MILVUS_URI", "http://127.0.0.1:19530")
    token = os.getenv("proj_test_MILVUS_TOKEN", None)
    return StorageConfig(
        kv=base.kv,
        orm=base.orm,
        object=base.object,
        vector=VectorStorageConfig(
            default=MilvusVectorDBConfig(
                uri=uri,
                token=token,
                namespace=f"milvus-vector-{tmp_name}-default",
            ),
            cache=MilvusVectorDBConfig(
                uri=uri,
                token=token,
                namespace=f"milvus-vector-{tmp_name}-cache",
            ),
        ),
    )


def _make_milvus_lite_vector_storage_config(tmp: str) -> StorageConfig:
    base = _make_storage_config(tmp)
    return StorageConfig(
        kv=base.kv,
        orm=base.orm,
        object=base.object,
        vector=VectorStorageConfig(
            default=MilvusLiteVectorDBConfig(
                db_path=str(Path(tmp) / "vector_milvus_lite_real.db"),
                namespace=f"milvus-lite-{Path(tmp).name}-default",
            ),
            cache=MilvusLiteVectorDBConfig(
                db_path=str(Path(tmp) / "vector_milvus_lite_cache_real.db"),
                namespace=f"milvus-lite-{Path(tmp).name}-cache",
            ),
        ),
    )


def _register_kv_routes(app: FastAPI):
    from core.server.routes.storage.kv import register_storage_kv_routes   # type: ignore
    register_storage_kv_routes(app)


def _register_object_routes(app: FastAPI):
    from core.server.routes.storage.object import register_storage_object_routes   # type: ignore
    register_storage_object_routes(app)


def _register_orm_routes(app: FastAPI):
    from core.server.routes.storage.orm import register_storage_orm_routes # type: ignore
    register_storage_orm_routes(app)


def _register_vector_routes(app: FastAPI):
    from core.server.routes.storage.vector import register_storage_vector_routes   # type: ignore
    register_storage_vector_routes(app)


class _FallbackVectorClient:
    """Minimal in-memory vector client used only when Milvus Lite is unavailable."""

    def __init__(self):
        self._namespace = "default"
        self._vector_fields: dict[str, dict[str, int]] = {}
        self._collection_models: dict[str, type] = {}
        self._documents: dict[str, dict[str, dict]] = {}
        self._ttl: dict[tuple[str, str], float | None] = {}

    def start(self):
        return self

    def stop(self):
        return None

    async def get(self, collection: str, object_id: str, *, as_model: bool = True):
        return self._documents.get(collection, {}).get(object_id)

    async def delete(self, collection: str, object_id: str):
        existed = object_id in self._documents.get(collection, {})
        self._documents.get(collection, {}).pop(object_id, None)
        self._ttl.pop((collection, object_id), None)
        return existed

    async def set_expire(self, collection: str, object_id: str, expire_seconds: float | None):
        if object_id not in self._documents.get(collection, {}):
            return False
        self._ttl[(collection, object_id)] = expire_seconds
        return True

    async def get_expire(self, collection: str, object_id: str):
        return self._ttl.get((collection, object_id))

    async def cleanup(self, force: bool = True):
        return 0

    async def create_collection(self, model_cls):
        collection = getattr(model_cls, "CollectionName", getattr(model_cls, "__name__", "default"))
        self._documents.setdefault(collection, {})
        self._collection_models[collection] = model_cls
        vector_fields = {}
        model_fields = getattr(model_cls, 'model_fields', {}) or {}
        for field_name, field_info in model_fields.items():
            dim = None
            extra = getattr(field_info, 'json_schema_extra', None)
            if isinstance(extra, dict):
                dim = extra.get('dim')
            if isinstance(field_info, VectorORMFieldInfo) and field_info.is_vector:
                vector_fields[field_name] = int(field_info.dim or dim or 0)
            elif dim is not None:
                vector_fields[field_name] = int(dim or 0)
        self._vector_fields.setdefault(collection, vector_fields or {"vector": 0})

    async def embed_field_value(self, collection, value, *, field: str | None = None, use_cache: bool = True, save_cache: bool = True):
        collection_name = getattr(collection, 'CollectionName', None) or str(collection)
        field_name = field or next(iter(self._vector_fields.get(collection_name, {})), 'vector')
        model_cls = self._collection_models.get(collection_name)
        field_info = None if model_cls is None else (getattr(model_cls, 'model_fields', {}) or {}).get(field_name)
        embedder = field_info.embedder if isinstance(field_info, VectorORMFieldInfo) else None
        service, resolved_embedder, _ = resolve_vector_embedder(embedder)
        if embedder is None:
            vector = await service.embedding(value, use_cache=use_cache, save_cache=save_cache)
            return normalize_vector_embedding(vector)
        return await call_vector_embedder(resolved_embedder, value)

    async def drop_collection(self, collection: str):
        self._documents.pop(collection, None)
        self._vector_fields.pop(collection, None)

    async def set(self, value, *, collection: str | None = None, expire: float | int | None = None):
        if collection is None:
            collection = getattr(value, "CollectionName", "default")
        collection_name: str = str(collection or "default")
        if isinstance(value, dict):
            payload = dict(value)
        else:
            payload = value.model_dump(mode="json")
        object_id = str(payload.get("_id") or payload.get("id") or len(self._documents.setdefault(collection_name, {})) + 1)
        payload["_id"] = object_id
        self._documents.setdefault(collection_name, {})[object_id] = payload
        self._ttl[(collection_name, object_id)] = float(expire) if expire is not None else None
        self._vector_fields.setdefault(collection_name, {"vector": len(payload.get("vector", [])) if isinstance(payload.get("vector"), list) else 0})
        return object_id

    async def _iter_docs(self, collection: str, *, limit: int | None = None, offset: int = 0) -> AsyncGenerator[dict, None]:
        docs = list(self._documents.get(collection, {}).values())
        if offset:
            docs = docs[offset:]
        if limit is not None:
            docs = docs[:limit]
        for item in docs:
            yield dict(item)

    def search(self, collection: str, query=None, *, limit: int | None = None, offset: int = 0, as_model: bool = True):
        async def _gen():
            async for item in self._iter_docs(collection, limit=limit, offset=offset):
                if query and any(item.get(k) != v for k, v in query.items()):
                    continue
                yield item
        return _gen()

    def search_vector(self, collection: str, vector, *, field: str | None = None, limit: int = 10, query=None, as_model: bool = True):
        async def _gen():
            query_vector = await self.embed_field_value(collection, vector, field=field, use_cache=True, save_cache=False) if isinstance(vector, str) else [float(v) for v in vector]
            field_name = field or next(iter(self._vector_fields.get(collection, {})), 'vector')
            scored: list[dict] = []
            async for item in self._iter_docs(collection, limit=None, offset=0):
                if query and any(item.get(k) != v for k, v in query.items()):
                    continue
                stored_vector = item.get(field_name)
                if not isinstance(stored_vector, list):
                    continue
                payload = dict(item)
                payload['_score'] = sum(float(a) * float(b) for a, b in zip(query_vector, stored_vector))
                scored.append(payload)
            scored.sort(key=lambda item: float(item.get('_score', 0.0)), reverse=True)
            count = 0
            for payload in scored:
                yield payload
                count += 1
                if count >= limit:
                    break
        return _gen()


# ══════════════════════════════════════════════════════════════════════════════
# Base test classes for Storage domains
# ══════════════════════════════════════════════════════════════════════════════

class _StorageTestBase(unittest.IsolatedAsyncioTestCase):
    """
    Abstract base: creates a temp dir, sets up ``StorageConfig``, builds
    a minimal FastAPI app, and provides ``self._client`` (httpx.AsyncClient).
    Subclasses override ``_register_routes`` to attach the routes they need.
    """
    _tmp_dir_obj: tempfile.TemporaryDirectory | None = None
    _app: FastAPI | None = None
    _storage_config: StorageConfig | None = None
    _previous_storage_config: StorageConfig | None = None
    _previous_storage_env: str | None = None

    @classmethod
    def _register_routes(cls, app: FastAPI):
        """Override in subclass to register the required route group."""
        raise NotImplementedError

    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._previous_storage_config = StorageConfig.__Instance__
        cls._previous_storage_env = os.environ.get(_STORAGE_CONFIG_ENV)
        cls._tmp_dir_obj = tempfile.TemporaryDirectory(prefix="proj_test_")
        tmp = cls._tmp_dir_obj.name

        cls._storage_config = cls._make_storage_config(tmp)
        StorageConfig.SetGlobal(cls._storage_config)

        from core.server.app import _install_internal_path_rewriter
        from core.server.data_types.config import ServerConfig

        cls._app = FastAPI(docs_url=None, redoc_url=None, openapi_url="/_internal/admin/openapi.json")
        _install_internal_path_rewriter(cls._app, ServerConfig())
        cls._register_routes(cls._app)

    @classmethod
    def tearDownClass(cls):
        # Cleanup storage clients
        if cls._storage_config is not None:
            for attr in ('kv', 'orm', 'vector', 'object'):
                section = getattr(cls._storage_config, attr, None)
                if section is None:
                    continue
                for client in section._client_singletons.values():
                    stop = getattr(client, "stop", None) or getattr(client, "close", None)
                    if callable(stop):
                        try:
                            stop()
                        except Exception:
                            pass
                section._client_singletons.clear()
        if cls._tmp_dir_obj is not None:
            try:
                cls._tmp_dir_obj.cleanup()
            except Exception:
                pass
        _restore_storage_global(cls._previous_storage_config, cls._previous_storage_env)
        super().tearDownClass()

    async def asyncSetUp(self):
        assert self._app is not None
        app = self._app
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async def asyncTearDown(self):
        if hasattr(self, "_client") and self._client is not None:
            await self._client.aclose()


class StorageKVTestBase(_StorageTestBase):
    @classmethod
    def _register_routes(cls, app: FastAPI):
        _register_kv_routes(app)

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        kv_section = storage_config.kv
        seen: set[int] = set()

        for client in list(kv_section._client_singletons.values()):
            client_id = id(client)
            if client_id in seen:
                continue
            seen.add(client_id)
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass

        for _, cfg in kv_section.iter_unique_configs():
            client = cfg.__dict__.get("__client__")
            if client is None:
                continue
            client_id = id(client)
            if client_id in seen:
                continue
            seen.add(client_id)
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass

        kv_section.clear_cached_clients()

        from core.storage.kv import KVClientBase

        KVClientBase.ClearDefaultInstances()
        await super().asyncSetUp()


class StorageRedisKVTestBase(StorageKVTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_redis_kv_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            import redis

            redis.Redis.from_url("redis://127.0.0.1:6379/0", socket_timeout=3).ping()
        except Exception as exc:
            raise unittest.SkipTest(f"Redis not available for tests: {exc}") from exc
        super().setUpClass()

class StorageEtcdKVTestBase(StorageKVTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_etcd_kv_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            import httpx

            port = int(os.getenv("proj_test_ETCD_PORT", "23791"))
            resp = httpx.post(
                f"http://127.0.0.1:{port}/v3/maintenance/status",
                json={},
                timeout=5,
                trust_env=False,
            )
            resp.raise_for_status()
        except Exception as exc:
            raise unittest.SkipTest(f"etcd not available for KV tests: {exc}") from exc
        super().setUpClass()


class StorageObjectTestBase(_StorageTestBase):
    @classmethod
    def _register_routes(cls, app: FastAPI):
        _register_object_routes(app)


class StorageMinIOObjectTestBase(StorageObjectTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_minio_object_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        async def _probe():
            from miniopy_async import Minio
            client = Minio(
                os.getenv("proj_test_MINIO_ENDPOINT", "127.0.0.1:9002"),
                access_key=os.getenv("proj_test_MINIO_ACCESS_KEY", "minioadmin"),
                secret_key=os.getenv("proj_test_MINIO_SECRET_KEY", "minioadmin"),
                secure=False,
            )
            try:
                await client.list_buckets()
            finally:
                await client._session.close()
        try:
            asyncio.run(_probe())
        except Exception as exc:
            raise unittest.SkipTest(f"MinIO not available for object tests: {exc}") from exc
        super().setUpClass()


class StorageORMTestBase(_StorageTestBase):
    @classmethod
    def _register_routes(cls, app: FastAPI):
        _register_orm_routes(app)

    def _register_orm_model(self, collection: str, sample: Mapping[str, object] | None = None):
        storage_config = self._storage_config
        assert storage_config is not None
        client = storage_config.orm.get_default()
        return register_test_orm_model(client, collection, sample)


class StorageRedisORMTestBase(StorageORMTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_redis_orm_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            import redis

            redis.Redis.from_url("redis://127.0.0.1:6379/0", socket_timeout=3).ping()
        except Exception as exc:
            raise unittest.SkipTest(f"Redis not available for ORM tests: {exc}") from exc
        super().setUpClass()

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        orm_section = storage_config.orm
        for client in list(orm_section._client_singletons.values()):
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        orm_section._client_singletons.clear()
        from core.storage.orm import ORMModel
        ORMModel.ResetClientBindings()
        await super().asyncSetUp()


class StorageMongoORMTestBase(StorageORMTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_mongo_orm_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            from pymongo import MongoClient

            MongoClient(MONGO_TEST_URL, serverSelectionTimeoutMS=3000).server_info()
        except Exception as exc:
            raise unittest.SkipTest(f"MongoDB not available for ORM tests: {exc}") from exc
        super().setUpClass()

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        orm_section = storage_config.orm
        for client in list(orm_section._client_singletons.values()):
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        orm_section._client_singletons.clear()
        await super().asyncSetUp()

    @classmethod
    def tearDownClass(cls):
        storage_config = cls._storage_config
        databases: list[str] = []
        if storage_config is not None:
            for cfg in (storage_config.orm.default, storage_config.orm.cache, storage_config.orm.log):
                database = getattr(cfg, "database", None)
                if isinstance(database, str) and database:
                    databases.append(database)

        super().tearDownClass()

        if databases:
            try:
                from pymongo import MongoClient

                client = MongoClient(MONGO_TEST_URL, serverSelectionTimeoutMS=3000)
                for database in databases:
                    client.drop_database(database)
                client.close()
            except Exception:
                pass


class StorageMySQLORMTestBase(StorageORMTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_mysql_orm_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            import asyncio
            import aiomysql

            async def _probe() -> None:
                conn = await aiomysql.connect(
                    host="127.0.0.1",
                    port=int(os.getenv("proj_test_MYSQL_PORT", "3307")),
                    user=os.getenv("proj_test_MYSQL_USER", "root"),
                    password=os.getenv("proj_test_MYSQL_PASSWORD", "rootpass"),
                    db="mysql",
                    autocommit=True,
                    connect_timeout=3,
                )
                conn.close()

            asyncio.run(_probe())
        except Exception as exc:
            raise unittest.SkipTest(f"MySQL not available for ORM tests: {exc}") from exc

        super().setUpClass()

        storage_config = cls._storage_config
        assert storage_config is not None
        databases = []
        for cfg in (storage_config.orm.default, storage_config.orm.cache, storage_config.orm.log):
            database = getattr(cfg, "database", None)
            if isinstance(database, str) and database:
                databases.append(database)

        try:
            import asyncio
            import aiomysql

            async def _prepare_databases() -> None:
                conn = await aiomysql.connect(
                    host="127.0.0.1",
                    port=int(os.getenv("proj_test_MYSQL_PORT", "3307")),
                    user=os.getenv("proj_test_MYSQL_USER", "root"),
                    password=os.getenv("proj_test_MYSQL_PASSWORD", "rootpass"),
                    db="mysql",
                    autocommit=True,
                )
                try:
                    cur = await conn.cursor()
                    try:
                        for database in databases:
                            await cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                    finally:
                        await cur.close()
                finally:
                    conn.close()

            asyncio.run(_prepare_databases())
        except Exception as exc:
            raise unittest.SkipTest(f"MySQL database bootstrap failed: {exc}") from exc

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        orm_section = storage_config.orm
        for client in list(orm_section._client_singletons.values()):
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        orm_section._client_singletons.clear()
        await super().asyncSetUp()

    async def asyncTearDown(self):
        storage_config = self._storage_config
        assert storage_config is not None
        orm_section = storage_config.orm
        from core.storage.orm import SQL_ORM_Client

        for client in list(orm_section._client_singletons.values()):
            if isinstance(client, SQL_ORM_Client) and getattr(client, "_engine", None) is not None:
                engine = client._engine
                client._engine = None
                client._schema_ready = False
                client._mark_stopped()
                try:
                    await engine.dispose()
                except Exception:
                    pass
                continue
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        orm_section._client_singletons.clear()
        await super().asyncTearDown()

    @classmethod
    def tearDownClass(cls):
        storage_config = cls._storage_config
        databases: list[str] = []
        if storage_config is not None:
            for cfg in (storage_config.orm.default, storage_config.orm.cache, storage_config.orm.log):
                database = getattr(cfg, "database", None)
                if isinstance(database, str) and database:
                    databases.append(database)

        super().tearDownClass()

        if databases:
            try:
                import asyncio
                import aiomysql

                async def _drop_databases() -> None:
                    conn = await aiomysql.connect(
                        host="127.0.0.1",
                        port=int(os.getenv("proj_test_MYSQL_PORT", "3307")),
                        user=os.getenv("proj_test_MYSQL_USER", "root"),
                        password=os.getenv("proj_test_MYSQL_PASSWORD", "rootpass"),
                        db="mysql",
                        autocommit=True,
                    )
                    try:
                        cur = await conn.cursor()
                        try:
                            for database in databases:
                                await cur.execute(f"DROP DATABASE IF EXISTS `{database}`")
                        finally:
                            await cur.close()
                    finally:
                        conn.close()

                asyncio.run(_drop_databases())
            except Exception:
                pass


class StoragePostgreSQLORMTestBase(StorageORMTestBase):
    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_postgresql_orm_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            import psycopg

            with psycopg.connect(
                host="127.0.0.1",
                port=int(os.getenv("proj_test_POSTGRES_PORT", "5433")),
                user=os.getenv("proj_test_POSTGRES_USER", "postgres"),
                password=os.getenv("proj_test_POSTGRES_PASSWORD", "postgres"),
                dbname="postgres",
                autocommit=True,
                connect_timeout=3,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL not available for ORM tests: {exc}") from exc

        super().setUpClass()

        storage_config = cls._storage_config
        assert storage_config is not None
        databases = []
        for cfg in (storage_config.orm.default, storage_config.orm.cache, storage_config.orm.log):
            database = getattr(cfg, "database", None)
            if isinstance(database, str) and database:
                databases.append(database)

        try:
            import psycopg

            with psycopg.connect(
                host="127.0.0.1",
                port=int(os.getenv("proj_test_POSTGRES_PORT", "5433")),
                user=os.getenv("proj_test_POSTGRES_USER", "postgres"),
                password=os.getenv("proj_test_POSTGRES_PASSWORD", "postgres"),
                dbname="postgres",
                autocommit=True,
            ) as conn:
                with conn.cursor() as cur:
                    for database in databases:
                        cur.execute(f'CREATE DATABASE "{database}"')
        except Exception as exc:
            if 'already exists' not in str(exc):
                raise unittest.SkipTest(f"PostgreSQL database bootstrap failed: {exc}") from exc

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        orm_section = storage_config.orm
        for client in list(orm_section._client_singletons.values()):
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        orm_section._client_singletons.clear()
        await super().asyncSetUp()

    async def asyncTearDown(self):
        storage_config = self._storage_config
        assert storage_config is not None
        orm_section = storage_config.orm
        from core.storage.orm import SQL_ORM_Client

        for client in list(orm_section._client_singletons.values()):
            if isinstance(client, SQL_ORM_Client) and getattr(client, "_engine", None) is not None:
                engine = client._engine
                client._engine = None
                client._schema_ready = False
                client._mark_stopped()
                try:
                    await engine.dispose()
                except Exception:
                    pass
                continue
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        orm_section._client_singletons.clear()
        await super().asyncTearDown()

    @classmethod
    def tearDownClass(cls):
        storage_config = cls._storage_config
        databases: list[str] = []
        if storage_config is not None:
            for cfg in (storage_config.orm.default, storage_config.orm.cache, storage_config.orm.log):
                database = getattr(cfg, "database", None)
                if isinstance(database, str) and database:
                    databases.append(database)

        super().tearDownClass()

        if databases:
            try:
                import psycopg

                with psycopg.connect(
                    host="127.0.0.1",
                    port=int(os.getenv("proj_test_POSTGRES_PORT", "5433")),
                    user=os.getenv("proj_test_POSTGRES_USER", "postgres"),
                    password=os.getenv("proj_test_POSTGRES_PASSWORD", "postgres"),
                    dbname="postgres",
                    autocommit=True,
                ) as conn:
                    with conn.cursor() as cur:
                        for database in databases:
                            cur.execute(f'DROP DATABASE IF EXISTS "{database}"')
            except Exception:
                pass


class StorageVectorTestBase(_StorageTestBase):
    """
    Vector storage base.

    Uses the platform-appropriate backend: Annoy+SQLite on Windows,
    Milvus-Lite on Linux/macOS.  If the chosen backend fails to start,
    falls back to a minimal in-memory vector client so the route tests
    still execute.

    The embedding service is automatically stubbed out (raises RuntimeError)
    to avoid blocking network calls to ThinkThinkSyn during tests.
    """
    _skip_all: bool = False
    _skip_reason: str = ""
    _embedding_patch: unittest.mock.MagicMock | None = None

    @classmethod
    def _register_routes(cls, app: FastAPI):
        _register_vector_routes(app)

    @classmethod
    def setUpClass(cls):
        cls._skip_all = False
        cls._skip_reason = ""

        # Stub out the embedding service to avoid blocking network calls
        # (ThinkThinkSyn probes localhost/LAN and can hang for tens of seconds)
        cls._embedding_patch = _patch_vector_embedding_service()
        cls._embedding_patch.start()

        try:
            super().setUpClass()
            # Force-create the vector client to see if it works
            storage_config = cls._storage_config
            assert storage_config is not None
            storage_config.get_vector_client()
        except Exception as exc:
            storage_config = cls._storage_config
            assert storage_config is not None
            logging.getLogger("proj-test").warning(
                "Falling back to in-memory vector client for tests: %s",
                exc,
            )
            storage_config.vector._client_singletons.clear()
            fallback = _FallbackVectorClient().start()
            storage_config.vector._client_singletons["default"] = fallback
            storage_config.vector._client_singletons["cache"] = fallback
            cls._skip_all = False
            cls._skip_reason = ""

    @classmethod
    def tearDownClass(cls):
        if cls._embedding_patch is not None:
            cls._embedding_patch.stop()
            cls._embedding_patch = None
        super().tearDownClass()

    def setUp(self):
        if self.__class__._skip_all:
            self.skipTest(self.__class__._skip_reason)


class StorageRedisVectorTestBase(_StorageTestBase):
    _embedding_patch: unittest.mock.MagicMock | None = None

    @classmethod
    def _register_routes(cls, app: FastAPI):
        _register_vector_routes(app)

    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_redis_vector_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            import redis

            redis.Redis.from_url("redis://127.0.0.1:6379/0", socket_timeout=3).ping()
        except Exception as exc:
            raise unittest.SkipTest(f"Redis not available for vector tests: {exc}") from exc

        cls._embedding_patch = _patch_vector_embedding_service()
        cls._embedding_patch.start()
        super().setUpClass()

        storage_config = cls._storage_config
        assert storage_config is not None
        storage_config.get_vector_client()

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        vector_section = storage_config.vector
        for client in list(vector_section._client_singletons.values()):
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        vector_section._client_singletons.clear()
        from core.storage.orm import ORMModel
        ORMModel.ResetClientBindings()
        await super().asyncSetUp()

    @classmethod
    def tearDownClass(cls):
        if cls._embedding_patch is not None:
            cls._embedding_patch.stop()
            cls._embedding_patch = None
        super().tearDownClass()


class StorageMongoVectorTestBase(_StorageTestBase):
    _embedding_patch: unittest.mock.MagicMock | None = None

    @classmethod
    def _register_routes(cls, app: FastAPI):
        _register_vector_routes(app)

    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_mongo_vector_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            from pymongo import MongoClient

            MongoClient(MONGO_TEST_URL, serverSelectionTimeoutMS=3000).server_info()
        except Exception as exc:
            raise unittest.SkipTest(f"MongoDB not available for vector tests: {exc}") from exc

        cls._embedding_patch = _patch_vector_embedding_service()
        cls._embedding_patch.start()
        super().setUpClass()

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        vector_section = storage_config.vector
        for client in list(vector_section._client_singletons.values()):
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        vector_section._client_singletons.clear()
        await super().asyncSetUp()

    @classmethod
    def tearDownClass(cls):
        storage_config = cls._storage_config
        databases: list[str] = []
        if storage_config is not None:
            for cfg in (storage_config.vector.default, storage_config.vector.cache):
                database = getattr(cfg, "database", None)
                if isinstance(database, str) and database:
                    databases.append(database)

        if cls._embedding_patch is not None:
            cls._embedding_patch.stop()
            cls._embedding_patch = None

        super().tearDownClass()

        if databases:
            try:
                from pymongo import MongoClient

                client = MongoClient(MONGO_TEST_URL, serverSelectionTimeoutMS=3000)
                for database in databases:
                    client.drop_database(database)
                client.close()
            except Exception:
                pass


class StorageMilvusVectorTestBase(_StorageTestBase):
    _embedding_patch: unittest.mock.MagicMock | None = None

    @classmethod
    def _register_routes(cls, app: FastAPI):
        _register_vector_routes(app)

    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_milvus_vector_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        try:
            from pymilvus import connections, utility

            cleanup_milvus_test_databases(prune_stale=True)
            uri = os.getenv("proj_test_MILVUS_URI", "http://127.0.0.1:19530")
            alias = f"proj-test-milvus-probe-{os.getpid()}-{cls.__name__}"
            connections.connect(alias=alias, uri=uri, token=os.getenv("proj_test_MILVUS_TOKEN", None) or None, timeout=5)
            utility.list_collections(using=alias)
            try:
                connections.disconnect(alias)
            except Exception:
                pass
        except Exception as exc:
            raise unittest.SkipTest(f"Milvus not available for vector tests: {exc}") from exc

        cls._embedding_patch = _patch_vector_embedding_service()
        cls._embedding_patch.start()
        super().setUpClass()

        storage_config = cls._storage_config
        assert storage_config is not None
        storage_config.get_vector_client()

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        vector_section = storage_config.vector
        for client in list(vector_section._client_singletons.values()):
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        vector_section._client_singletons.clear()
        await super().asyncSetUp()

    @classmethod
    def tearDownClass(cls):
        storage_config = cls._storage_config
        if cls._embedding_patch is not None:
            cls._embedding_patch.stop()
            cls._embedding_patch = None
        super().tearDownClass()
        cleanup_milvus_test_databases(storage_config)


class StorageMilvusLiteVectorTestBase(_StorageTestBase):
    _embedding_patch: unittest.mock.MagicMock | None = None

    @classmethod
    def _register_routes(cls, app: FastAPI):
        _register_vector_routes(app)

    @classmethod
    def _make_storage_config(cls, tmp: str) -> StorageConfig:
        return _make_milvus_lite_vector_storage_config(tmp)

    @classmethod
    def setUpClass(cls):
        cls._embedding_patch = _patch_vector_embedding_service()
        cls._embedding_patch.start()

        try:
            import importlib
            if importlib.util.find_spec("milvus_lite") is None:
                raise ModuleNotFoundError("milvus_lite is not installed")
            super().setUpClass()
            storage_config = cls._storage_config
            assert storage_config is not None
            client = storage_config.get_vector_client()
            from core.storage.vector import MilvusLiteVectorClient

            if not isinstance(client, MilvusLiteVectorClient):
                raise RuntimeError(f"expected MilvusLiteVectorClient, got {type(client).__name__}")
        except Exception as exc:
            if cls._embedding_patch is not None:
                cls._embedding_patch.stop()
                cls._embedding_patch = None
            raise unittest.SkipTest(f"milvus-lite not available for vector tests: {exc}") from exc

    async def asyncSetUp(self):
        storage_config = self._storage_config
        assert storage_config is not None
        vector_section = storage_config.vector
        for client in list(vector_section._client_singletons.values()):
            stop = getattr(client, "stop", None) or getattr(client, "close", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        vector_section._client_singletons.clear()
        await super().asyncSetUp()

    @classmethod
    def tearDownClass(cls):
        if cls._embedding_patch is not None:
            cls._embedding_patch.stop()
            cls._embedding_patch = None
        super().tearDownClass()


# ══════════════════════════════════════════════════════════════════════════════
# Full-App base (for panel, logs, ai, files tests)
# ══════════════════════════════════════════════════════════════════════════════

def _register_panel_routes(app: FastAPI):
    from core.server.routes.panel.main import register_panel_routes    # type: ignore
    register_panel_routes(app)


def _register_rtc_room_routes(app: FastAPI):
    from core.server.data_types.config import Config  # type: ignore
    from core.server.plugin import clear_plugins, configure_plugins, is_platform_supported, load_plugins_from_paths, start_plugins  # type: ignore
    from core.utils.concurrent_utils import run_any_func  # type: ignore

    plugin_root = Path(__file__).resolve().parents[2] / "plugin"
    plugin_paths = [
        plugin_root / plugin_name
        for plugin_name, supported_platforms in (
            ("webrtc-chatroom", ("all",)),
            ("frp-manager", ("all",)),
            ("docker-manager", ("all",)),
            ("clash", ("linux",)),
            ("nginx-manager", ("linux",)),
        )
        if is_platform_supported(supported_platforms) and (plugin_root / plugin_name).is_dir()
    ]
    clear_plugins()
    load_plugins_from_paths(plugin_paths)
    configure_plugins(Config.GetConfig().plugin_configs)
    run_any_func(start_plugins, "worker", app)


def _load_webrtc_chatroom_module():
    import sys

    from core.server.plugin import get_plugin_key, load_plugins_from_paths  # type: ignore

    plugin_path = Path(__file__).resolve().parents[2] / "plugin" / "webrtc-chatroom"
    plugin_classes = load_plugins_from_paths([plugin_path])
    plugin_class = next(
        (
            plugin
            for plugin in plugin_classes
            if get_plugin_key(plugin) == "webrtc-chatroom"
        ),
        None,
    )
    if plugin_class is None:
        raise RuntimeError("webrtc-chatroom plugin could not be loaded.")
    module = sys.modules.get(plugin_class.__module__)
    if module is None:
        raise RuntimeError("webrtc-chatroom plugin module is not loaded.")
    return module


def _register_system_monitoring_routes(app: FastAPI):
    from core.server.routes.system.monitoring import register_system_monitoring_routes # type: ignore
    register_system_monitoring_routes(app)


def _register_log_routes(app: FastAPI):
    from core.server.routes.system.logs import register_log_routes # type: ignore
    register_log_routes(app)


def _register_ai_service_routes(app: FastAPI):
    from core.server.routes.ai_services.api import register_ai_service_routes  # type: ignore
    register_ai_service_routes(app)


def _register_ai_services_panel_routes(app: FastAPI):
    from core.server.routes.ai_services.panel import register_ai_services_panel_routes # type: ignore
    register_ai_services_panel_routes(app)


def _register_system_tools_routes(app: FastAPI):
    from core.server.routes.system.tools import register_system_tools_routes   # type: ignore
    register_system_tools_routes(app)


def _register_distributed_routes(app: FastAPI):
    from core.server.routes.distributed.main import register_distributed_routes   # type: ignore
    register_distributed_routes(app)


def _register_admin_auth_routes(app: FastAPI):
    from core.server.routes.admin.auth import register_admin_auth_routes   # type: ignore
    register_admin_auth_routes(app)


def _register_plugin_panel_routes(app: FastAPI):
    from core.server.plugin import register_plugin_panel_routes  # type: ignore
    register_plugin_panel_routes(app)


_ALL_ROUTE_REGISTRARS: list[tuple[str, Callable]] = [
    ("kv",          _register_kv_routes),
    ("object",      _register_object_routes),
    ("orm",         _register_orm_routes),
    ("vector",      _register_vector_routes),
    ("rtc_room",    _register_rtc_room_routes),
    ("panel",       _register_panel_routes),
    ("system_monitoring", _register_system_monitoring_routes),
    ("logs",        _register_log_routes),
    ("system_tools", _register_system_tools_routes),
    ("ai_services", _register_ai_service_routes),
    ("ai_services_panel", _register_ai_services_panel_routes),
    ("distributed", _register_distributed_routes),
    ("admin_auth", _register_admin_auth_routes),
    ("plugin_panel", _register_plugin_panel_routes),
]


class FullAppTestBase(unittest.IsolatedAsyncioTestCase):
    """
    Brings up a near-complete app by directly registering each route group
    on a bare FastAPI instance (bypasses ``create_app`` and its lifespan
    callback mechanism which ``httpx.ASGITransport`` does not trigger).

    If Config init fails, tests are skipped rather than erroring.
    """

    _tmp_dir_obj: tempfile.TemporaryDirectory | None = None
    _app: FastAPI | None = None
    _skip_all: bool = False
    _skip_reason: str = ""
    _embedding_patch: unittest.mock.MagicMock | None = None
    _tts_embedding_patch: unittest.mock.MagicMock | None = None
    _storage_config: StorageConfig | None = None
    _previous_storage_config: StorageConfig | None = None
    _previous_storage_env: str | None = None
    _previous_config: object | None = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._previous_storage_config = StorageConfig.__Instance__
        cls._previous_storage_env = os.environ.get(_STORAGE_CONFIG_ENV)
        try:
            from core.server.data_types.config import Config
            cls._previous_config = Config.__Instance__
        except Exception:
            cls._previous_config = None

        # Stub the embedding service to prevent blocking network calls
        cls._embedding_patch = _patch_vector_embedding_service()
        cls._embedding_patch.start()
        cls._tts_embedding_patch = unittest_mock.patch(
            "core.ai.embedding.ThinkThinkSynEmbeddingClient._embedding_impl",
            new=_fake_tts_embedding_impl,
        )
        cls._tts_embedding_patch.start()

        cls._tmp_dir_obj = tempfile.TemporaryDirectory(prefix="proj_fullapp_test_")
        tmp = cls._tmp_dir_obj.name

        try:
            sc = _make_storage_config(tmp)
            cls._storage_config = sc

            from core.server.data_types.config import Config, LogConfig, ServerConfig   # type: ignore
            from core.server.app import register_public_fallback
            cfg = Config(
                server_config=ServerConfig(host="127.0.0.1", port=18999, expose_ai_service=True),
                log_config=LogConfig(log_method=["db"]),
                plugin_configs={"webrtc-chatroom": {"enabled": True}},
            )
            Config.SetConfig(cfg)
            StorageConfig.SetGlobal(sc)

            from core.server.app import _install_internal_path_rewriter

            cls._app = FastAPI(docs_url=None, redoc_url=None, openapi_url="/_internal/admin/openapi.json")
            _install_internal_path_rewriter(cls._app, cfg.server_config)
            # Ensure JWT keys are available for routes that issue tokens
            from core.server.security.jwt import ensure_jwt_keys_or_warn
            ensure_jwt_keys_or_warn(Path(__file__).resolve().parent.parent.parent)
            for name, registrar in _ALL_ROUTE_REGISTRARS:
                try:
                    registrar(cls._app)
                except Exception as exc:
                    logging.getLogger("proj-test").warning(
                        f"Route group '{name}' skipped: {exc}"
                    )
            register_public_fallback(cls._app, cfg)
        except Exception as exc:
            cls._skip_all = True
            cls._skip_reason = f"Full app init failed: {exc}"
            cls._app = FastAPI(docs_url=None, redoc_url=None, openapi_url="/_internal/admin/openapi.json")

    @classmethod
    def tearDownClass(cls):
        if cls._storage_config is not None:
            for attr in ('kv', 'orm', 'vector', 'object'):
                section = getattr(cls._storage_config, attr, None)
                if section is None:
                    continue
                for client in section._client_singletons.values():
                    stop = getattr(client, "stop", None) or getattr(client, "close", None)
                    if callable(stop):
                        try:
                            stop()
                        except Exception:
                            pass
                section._client_singletons.clear()
        if cls._tts_embedding_patch is not None:
            cls._tts_embedding_patch.stop()
            cls._tts_embedding_patch = None
        if cls._embedding_patch is not None:
            cls._embedding_patch.stop()
            cls._embedding_patch = None
        if cls._tmp_dir_obj is not None:
            try:
                cls._tmp_dir_obj.cleanup()
            except Exception:
                pass
        _restore_storage_global(cls._previous_storage_config, cls._previous_storage_env)
        _restore_config_global(cls._previous_config)
        super().tearDownClass()

    def setUp(self):
        if self.__class__._skip_all:
            self.skipTest(self.__class__._skip_reason)

    async def asyncSetUp(self):
        assert self._app is not None
        app = self._app
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async def asyncTearDown(self):
        if hasattr(self, "_client") and self._client is not None:
            await self._client.aclose()
