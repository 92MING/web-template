"""Integration tests: vector index mismatch detection & model-to-DB alignment.

When a vector ORM model declares dim / metric_type / algorithm that differ from
the *actual* DB index, the storage layer must:

1. Emit a WARNING (not modify the DB index).
2. Force-align the in-memory model state to match the DB so that subsequent
   queries use the correct DB-side parameters.

Tests run against all available Docker vector backends (Milvus, Redis, Mongo,
Annoy/SQLite).
"""
import asyncio
import logging
import os
import sys
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from core.storage.vector import (
    AnnoySQLiteVectorClient,
    MetricType,
    PyMilvusVectorClient,
    VectorClientBase,
    VectorIndex,
    VectorIndexAlgorithm,
    VectorORMField,
    VectorORMModel,
)

_logger = logging.getLogger("core.storage.vector")

_SUFFIX = str(int(time.time()))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MILVUS_URI = os.getenv("TEST_MILVUS_URI", "http://127.0.0.1:19530")
REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/0")
MONGO_URL = os.getenv("TEST_MONGO_URL", "mongodb://127.0.0.1:27017/?directConnection=true")


def _run(coro):
    """Run a coroutine to completion, reusing or creating an event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _milvus_available() -> bool:
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI)
        c.list_collections()
        c.close()
        return True
    except Exception:
        return False


def _redis_available() -> bool:
    try:
        import redis
        r = redis.Redis.from_url(REDIS_URL)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


def _mongo_available() -> bool:
    try:
        from pymongo import MongoClient
        c = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)
        c.server_info()
        c.close()
        return True
    except Exception:
        return False


_MILVUS_OK = _milvus_available()
_REDIS_OK = _redis_available()
_MONGO_OK = _mongo_available()

# Milvus bounded-consistency helpers
_CONSISTENCY_RETRIES = 6
_CONSISTENCY_SLEEP = 0.3


# ══════════════════════════════════════════════════════════════════════════════
# Milvus
# ══════════════════════════════════════════════════════════════════════════════

_MILVUS_COLL = f"vir_milvus_{_SUFFIX}"


class _MilvusOriginal(VectorORMModel, collection_name=_MILVUS_COLL):
    """Model used to create the initial Milvus collection."""
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, metric_type="COSINE", algorithm="AUTOINDEX"),
    )


class _MilvusMismatch(VectorORMModel, collection_name=_MILVUS_COLL):
    """Same collection name, but different dim/metric/algorithm declarations."""
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=8, metric_type="L2", algorithm="FLAT"),
    )


@unittest.skipUnless(_MILVUS_OK, "Milvus not reachable")
class TestMilvusVectorIndexReconciliation(unittest.TestCase):

    client: PyMilvusVectorClient
    _coll: str  # resolved CollectionName

    @classmethod
    def setUpClass(cls):
        cls._coll = _MilvusOriginal.CollectionName
        cls.client = PyMilvusVectorClient(
            uri=MILVUS_URI,
            metric_type="COSINE",
            namespace=f"vitest_{_SUFFIX}",
        )
        cls.client.start()
        _run(cls.client.create_collection(_MilvusOriginal))
        _run(
            cls.client.set(_MilvusOriginal(title="seed", embedding=[0.1, 0.2, 0.3, 0.4]))
        )

    @classmethod
    def tearDownClass(cls):
        try:
            _run(cls.client.drop_collection(cls._coll))
        except Exception:
            pass
        cls.client.close()

    def test_dim_mismatch_warns_and_aligns(self):
        client = self.__class__.client  # type: ignore
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_MilvusMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("dim mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'dim mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(client._vector_fields.get(coll, {}).get("embedding"), 4)

    def test_metric_mismatch_warns_and_aligns(self):
        client = self.__class__.client  # type: ignore
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_MilvusMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("metric_type mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'metric_type mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(str(client._vector_field_metrics.get(coll, {}).get("embedding")).upper(), "COSINE")

    def test_algorithm_mismatch_warns_and_aligns(self):
        client = self.__class__.client  # type: ignore
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_MilvusMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("algorithm mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'algorithm mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(str(client._vector_field_algorithms.get(coll, {}).get("embedding")).upper(), "AUTOINDEX")

    def test_db_index_not_modified(self):
        client = self.__class__.client  # type: ignore
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        _run(client.create_collection(_MilvusMismatch))
        index_info = _run(
            client._milvus_describe_index(coll, "embedding")
        )
        self.assertEqual(str(index_info.get("metric_type", "")).upper(), "COSINE")
        self.assertEqual(str(index_info.get("index_type", "")).upper(), "AUTOINDEX")

    def test_matching_model_no_warning(self):
        client = self.__class__.client  # type: ignore
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_MilvusOriginal))
        mismatch_warns = [
            c for c in mock_warn.call_args_list
            if "mismatch" in str(c).lower()
        ]
        self.assertEqual(mismatch_warns, [], f"Unexpected mismatch warnings: {mismatch_warns}")


# ══════════════════════════════════════════════════════════════════════════════
# Redis
# ══════════════════════════════════════════════════════════════════════════════

_REDIS_COLL = f"vir_redis_{_SUFFIX}"


class _RedisOriginal(VectorORMModel, collection_name=_REDIS_COLL):
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, metric_type="COSINE", algorithm="FLAT"),
    )


class _RedisMismatch(VectorORMModel, collection_name=_REDIS_COLL):
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=8, metric_type="L2", algorithm="HNSW"),
    )


@unittest.skipUnless(_REDIS_OK, "Redis not reachable")
class TestRedisVectorIndexReconciliation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from core.storage.vector import RedisVectorClient
        cls.RedisVectorClient = RedisVectorClient
        cls._coll = _RedisOriginal.CollectionName
        cls.client = RedisVectorClient(
            redis_url=REDIS_URL,
            metric_type="COSINE",
            namespace=f"vitest-{_SUFFIX}",
        )
        cls.client.start()
        _run(cls.client.create_collection(_RedisOriginal))

    @classmethod
    def tearDownClass(cls):
        try:
            _run(cls.client.drop_collection(cls._coll))
        except Exception:
            pass
        cls.client.close()

    def test_dim_mismatch_warns_and_aligns(self):
        client = self.__class__.client
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_RedisMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("dim mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'dim mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(client._vector_fields.get(coll, {}).get("embedding"), 4)

    def test_metric_mismatch_warns_and_aligns(self):
        client = self.__class__.client
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_RedisMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("metric_type mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'metric_type mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(str(client._vector_field_metrics.get(coll, {}).get("embedding")).upper(), "COSINE")

    def test_algorithm_mismatch_warns_and_aligns(self):
        client = self.__class__.client
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_RedisMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("algorithm mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'algorithm mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(str(client._vector_field_algorithms.get(coll, {}).get("embedding")).upper(), "FLAT")

    def test_db_index_not_modified(self):
        client = self.__class__.client
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        _run(client.create_collection(_RedisMismatch))
        info = _run(client._search(coll).info())
        for attr in info.get("attributes", []):
            if not isinstance(attr, (list, tuple)):
                continue
            attr_dict = {}
            for i in range(0, len(attr) - 1, 2):
                attr_dict[str(attr[i]).lower()] = attr[i + 1]
            if str(attr_dict.get("type", "")).upper() != "VECTOR":
                continue
            self.assertEqual(int(attr_dict.get("dim", 0)), 4)
            self.assertEqual(str(attr_dict.get("distance_metric", "")).upper(), "COSINE")
            self.assertEqual(str(attr_dict.get("algorithm", "")).upper(), "FLAT")

    def test_matching_model_no_warning(self):
        client = self.__class__.client
        coll = self.__class__._coll
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_RedisOriginal))
        mismatch_warns = [
            c for c in mock_warn.call_args_list
            if "mismatch" in str(c).lower()
        ]
        self.assertEqual(mismatch_warns, [], f"Unexpected mismatch warnings: {mismatch_warns}")


# ══════════════════════════════════════════════════════════════════════════════
# Annoy / SQLite
# ══════════════════════════════════════════════════════════════════════════════

import tempfile

_ANNOY_COLL = f"vir_annoy_{_SUFFIX}"


class _AnnoyOriginal(VectorORMModel, collection_name=_ANNOY_COLL):
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, metric_type="COSINE"),
    )


class _AnnoyMismatch(VectorORMModel, collection_name=_ANNOY_COLL):
    """Same collection but model declares dim=8."""
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=8, metric_type="COSINE"),
    )


class TestAnnoySQLiteVectorIndexReconciliation(unittest.TestCase):
    """Annoy/SQLite can only reconcile dim (metric/algo are in-memory, not stored)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.client = AnnoySQLiteVectorClient(
            db_dir=self._tmpdir,
            metric_type="COSINE",
        )
        self.client.start()
        _run(self.client.create_collection(_AnnoyOriginal))
        # Insert a row with dim=4
        _run(
            self.client.set(_AnnoyOriginal(title="seed", embedding=[0.1, 0.2, 0.3, 0.4]))
        )

    def tearDown(self):
        try:
            self.client.close()
        except Exception:
            pass
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_dim_mismatch_warns_and_aligns(self):
        coll = _AnnoyOriginal.CollectionName
        self.client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(self.client.create_collection(_AnnoyMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("dim mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'dim mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(self.client._vector_fields.get(coll, {}).get("embedding"), 4)

    def test_matching_dim_no_warning(self):
        coll = _AnnoyOriginal.CollectionName
        self.client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(self.client.create_collection(_AnnoyOriginal))
        mismatch_warns = [
            c for c in mock_warn.call_args_list
            if "mismatch" in str(c).lower()
        ]
        self.assertEqual(mismatch_warns, [], f"Unexpected mismatch warnings: {mismatch_warns}")

    def test_empty_table_no_warning(self):
        coll = _AnnoyOriginal.CollectionName
        _run(self.client.drop_collection(coll))
        self.client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(self.client.create_collection(_AnnoyMismatch))
        mismatch_warns = [
            c for c in mock_warn.call_args_list
            if "mismatch" in str(c).lower()
        ]
        self.assertEqual(mismatch_warns, [], f"Unexpected mismatch warnings: {mismatch_warns}")


# ══════════════════════════════════════════════════════════════════════════════
# MongoDB (Atlas local)
# ══════════════════════════════════════════════════════════════════════════════

_MONGO_COLL = f"vir_mongo_{_SUFFIX}"


class _MongoOriginal(VectorORMModel, collection_name=_MONGO_COLL):
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, metric_type="COSINE"),
    )


class _MongoMismatch(VectorORMModel, collection_name=_MONGO_COLL):
    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=8, metric_type="IP"),
    )


def _mongo_vector_available() -> bool:
    """Check if MongoDB Atlas (with vector search) is reachable."""
    if not _MONGO_OK:
        return False
    try:
        from core.storage.vector import MongoVectorClient
        c = MongoVectorClient(mongo_url=MONGO_URL, namespace=f"probe-{_SUFFIX}")
        c.start()
        _run(c._ensure_vector_search_version())
        # Also verify Atlas Search is actually enabled (not just version check)
        _run(c._list_search_indexes("__probe__"))
        c.close()
        return True
    except Exception:
        return False


_MONGO_VECTOR_OK = _mongo_vector_available()


@unittest.skipUnless(_MONGO_VECTOR_OK, "MongoDB Atlas with vector search not reachable")
class TestMongoVectorIndexReconciliation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from core.storage.vector import MongoVectorClient
        cls.MongoVectorClient = MongoVectorClient
        cls.client = MongoVectorClient(
            mongo_url=MONGO_URL,
            metric_type="COSINE",
            namespace=f"vitest-{_SUFFIX}",
        )
        cls.client.start()
        _run(cls.client.create_collection(_MongoOriginal))

    @classmethod
    def tearDownClass(cls):
        try:
            _run(cls.client.drop_collection(_MongoOriginal.CollectionName))
        except Exception:
            pass
        cls.client.close()

    def test_dim_mismatch_warns_and_aligns(self):
        client = self.__class__.client
        coll = _MongoOriginal.CollectionName
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_MongoMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("dim mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'dim mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(client._vector_fields.get(coll, {}).get("embedding"), 4)

    def test_metric_mismatch_warns_and_aligns(self):
        client = self.__class__.client
        coll = _MongoOriginal.CollectionName
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_MongoMismatch))
        calls = [str(c) for c in mock_warn.call_args_list]
        self.assertTrue(
            any("metric_type mismatch" in str(c).lower() for c in mock_warn.call_args_list),
            f"Expected 'metric_type mismatch' warning. Actual warnings: {calls}",
        )
        self.assertEqual(str(client._vector_field_metrics.get(coll, {}).get("embedding")).upper(), "COSINE")

    def test_db_index_not_modified(self):
        client = self.__class__.client
        coll = _MongoOriginal.CollectionName
        client._bootstrapped_collections.discard(coll)
        _run(client.create_collection(_MongoMismatch))
        indexes = _run(
            client._list_search_indexes(coll)
        )
        found_vector = False
        for idx_doc in indexes:
            raw_def = idx_doc.get("latestDefinition") or idx_doc.get("definition") or {}
            for field_def in raw_def.get("fields", []):
                if field_def.get("type") == "vector":
                    self.assertEqual(int(field_def["numDimensions"]), 4)
                    self.assertEqual(field_def["similarity"], "cosine")
                    found_vector = True
        self.assertTrue(found_vector, "No vector field found in Mongo search index")

    def test_matching_model_no_warning(self):
        client = self.__class__.client
        coll = _MongoOriginal.CollectionName
        client._bootstrapped_collections.discard(coll)
        with patch.object(_logger, "warning", wraps=_logger.warning) as mock_warn:
            _run(client.create_collection(_MongoOriginal))
        mismatch_warns = [
            c for c in mock_warn.call_args_list
            if "mismatch" in str(c).lower()
        ]
        self.assertEqual(mismatch_warns, [], f"Unexpected mismatch warnings: {mismatch_warns}")


# ══════════════════════════════════════════════════════════════════════════════
# Base class helpers (unit tests, no backend required)
# ══════════════════════════════════════════════════════════════════════════════

class TestAlignVectorFieldToDb(unittest.TestCase):
    """Unit-test _align_vector_field_to_db in isolation."""

    def _make_client(self) -> AnnoySQLiteVectorClient:
        """Return a minimal client with some in-memory state."""
        tmpdir = tempfile.mkdtemp()
        client = AnnoySQLiteVectorClient(db_dir=tmpdir, metric_type="COSINE")
        client._vector_fields["coll"] = {"emb": 4}
        client._vector_field_metrics["coll"] = {"emb": cast(MetricType, "COSINE")}
        client._vector_field_algorithms["coll"] = {"emb": cast(VectorIndexAlgorithm, "FLAT")}
        return client

    def test_align_dim(self):
        c = self._make_client()
        c._align_vector_field_to_db("coll", "emb", db_dim=16)
        self.assertEqual(c._vector_fields["coll"]["emb"], 16)

    def test_align_metric(self):
        c = self._make_client()
        c._align_vector_field_to_db("coll", "emb", db_metric="L2")
        self.assertEqual(c._vector_field_metrics["coll"]["emb"], "L2")

    def test_align_algorithm(self):
        c = self._make_client()
        c._align_vector_field_to_db("coll", "emb", db_algorithm="HNSW")
        self.assertEqual(c._vector_field_algorithms["coll"]["emb"], "HNSW")

    def test_align_all_at_once(self):
        c = self._make_client()
        c._align_vector_field_to_db("coll", "emb", db_dim=32, db_metric="IP", db_algorithm="AUTOINDEX")
        self.assertEqual(c._vector_fields["coll"]["emb"], 32)
        self.assertEqual(c._vector_field_metrics["coll"]["emb"], "IP")
        self.assertEqual(c._vector_field_algorithms["coll"]["emb"], "AUTOINDEX")

    def test_align_creates_missing_dict_entries(self):
        """If the collection had no per-field metrics/algo, align should create them."""
        tmpdir = tempfile.mkdtemp()
        c = AnnoySQLiteVectorClient(db_dir=tmpdir, metric_type="COSINE")
        c._vector_fields["coll"] = {"emb": 4}
        c._align_vector_field_to_db("coll", "emb", db_metric="L2", db_algorithm="HNSW")
        self.assertEqual(c._vector_field_metrics["coll"]["emb"], "L2")
        self.assertEqual(c._vector_field_algorithms["coll"]["emb"], "HNSW")

    def test_align_noop_when_none(self):
        """Passing None for an attribute should leave it unchanged."""
        c = self._make_client()
        c._align_vector_field_to_db("coll", "emb", db_dim=None, db_metric=None, db_algorithm=None)
        self.assertEqual(c._vector_fields["coll"]["emb"], 4)
        self.assertEqual(c._vector_field_metrics["coll"]["emb"], "COSINE")
        self.assertEqual(c._vector_field_algorithms["coll"]["emb"], "FLAT")


# ══════════════════════════════════════════════════════════════════════════════
# Mongo similarity �?metric helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestMongoSimilarityMapping(unittest.TestCase):
    def test_roundtrip(self):
        from core.storage.vector import (
            _mongo_similarity_to_metric,
            _mongo_vector_similarity,
        )
        for metric, similarity in [("COSINE", "cosine"), ("L2", "euclidean"), ("IP", "dotProduct")]:
            self.assertEqual(_mongo_vector_similarity(metric), similarity)
            self.assertEqual(_mongo_similarity_to_metric(similarity), metric.replace("L2", "L2"))

    def test_unknown_similarity_returns_none(self):
        from core.storage.vector import _mongo_similarity_to_metric
        self.assertIsNone(_mongo_similarity_to_metric("unknown"))


if __name__ == "__main__":
    unittest.main()
