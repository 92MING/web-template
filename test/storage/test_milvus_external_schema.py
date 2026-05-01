"""Integration tests for §0.4 — `__NoExpireField__` + KV expire sidecar.

Verifies that PyMilvusVectorClient can attach to an externally-created Milvus
collection whose schema does NOT contain `_expire_at` / `_accessed_at`, and
that expire / max_size cleanup still functions via the KV sidecar.

Target: Milvus standalone at 127.0.0.1:19530 + the default KV backend.
"""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from core.storage.expire_sidecar import ExpireSidecar
from core.storage.vector import (
    PyMilvusVectorClient,
    VectorIndex,
    VectorORMField,
    VectorORMModel,
)


MILVUS_URI = os.getenv("TEST_MILVUS_URI", "http://127.0.0.1:19530")
_CONSISTENCY_RETRIES = 8
_CONSISTENCY_SLEEP = 0.5
_SUFFIX = str(int(time.time()))

_alias_counter = 0


async def _embedder(content):
    text = str(content).lower()
    if "alpha" in text:
        return [1.0, 0.0, 0.0, 0.0]
    if "beta" in text:
        return [0.0, 1.0, 0.0, 0.0]
    return [0.25, 0.25, 0.25, 0.25]


def _make_client() -> PyMilvusVectorClient:
    global _alias_counter
    _alias_counter += 1
    client = PyMilvusVectorClient(uri=MILVUS_URI, name=f"proj_extschema_{os.getpid()}_{_alias_counter}")
    client.start()
    return client


def setUpModule():
    try:
        from pymilvus import connections, utility
        alias = f"extschema-probe-{os.getpid()}"
        connections.connect(alias=alias, uri=MILVUS_URI)
        utility.list_collections(using=alias)
        connections.disconnect(alias)
    except Exception as exc:
        raise unittest.SkipTest(f"Milvus not available at {MILVUS_URI}: {exc}") from exc


def _create_external_collection(name: str) -> None:
    """Create a Milvus collection externally with NO expire/accessed metadata fields."""
    from pymilvus import CollectionSchema, DataType, FieldSchema, connections, utility
    alias = f"extschema-create-{os.getpid()}"
    connections.connect(alias=alias, uri=MILVUS_URI)
    try:
        if utility.has_collection(name, using=alias):
            utility.drop_collection(name, using=alias)
        schema = CollectionSchema(
            fields=[
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=4),
            ],
            enable_dynamic_field=True,
        )
        from pymilvus import Collection
        coll = Collection(name=name, schema=schema, using=alias)
        coll.create_index(
            field_name="embedding",
            index_params={"index_type": "AUTOINDEX", "metric_type": "COSINE"},
        )
        coll.load()
    finally:
        connections.disconnect(alias)


def _drop_external_collection(name: str) -> None:
    from pymilvus import connections, utility
    alias = f"extschema-drop-{os.getpid()}"
    try:
        connections.connect(alias=alias, uri=MILVUS_URI)
        if utility.has_collection(name, using=alias):
            utility.drop_collection(name, using=alias)
    except Exception:
        pass
    finally:
        try:
            connections.disconnect(alias)
        except Exception:
            pass


def _describe_field_names(name: str) -> set[str]:
    from pymilvus import Collection, connections
    alias = f"extschema-describe-{os.getpid()}"
    connections.connect(alias=alias, uri=MILVUS_URI)
    try:
        coll = Collection(name=name, using=alias)
        return {field.name for field in coll.schema.fields}
    finally:
        connections.disconnect(alias)


# Model with __NoExpireField__=True matching the external collection layout.
_EXT_LOGICAL = f"mi_external_{_SUFFIX}"


class ExternalItem(VectorORMModel, collection_name=_EXT_LOGICAL):
    __NoExpireField__ = True

    title: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=4, embedder=_embedder),
    )


# The actual Milvus collection name VectorORMModel uses.
_EXT_COLL = ExternalItem.CollectionName


class TestMilvusExternalSchemaSidecar(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        _create_external_collection(_EXT_COLL)

    @classmethod
    def tearDownClass(cls):
        _drop_external_collection(_EXT_COLL)

    async def asyncSetUp(self):
        self.client = _make_client()
        await self.client.create_collection(ExternalItem)

    async def asyncTearDown(self):
        try:
            self.client.close()
        except Exception:
            pass

    async def test_external_collection_registers_sidecar(self):
        """Existing collection lacking _expire_at/_accessed_at → sidecar registered."""
        sidecar = self.client._get_sidecar(_EXT_COLL)
        self.assertIsNotNone(sidecar, "Expected sidecar to be registered for external schema collection")
        self.assertIsInstance(sidecar, ExpireSidecar)
        # External schema unchanged (no _expire_at / _accessed_at columns).
        field_names = _describe_field_names(_EXT_COLL)
        self.assertNotIn("_expire_at", field_names)
        self.assertNotIn("_accessed_at", field_names)
        self.assertIn("title", field_names)
        self.assertIn("embedding", field_names)

    async def test_set_writes_to_sidecar_only(self):
        """set(expire=…) must NOT write _expire_at to Milvus, but MUST write to sidecar."""
        oid = await self.client.set(
            ExternalItem(title="alpha", embedding=[1.0, 0.0, 0.0, 0.0]),
            expire=60,
        )
        sidecar = self.client._get_sidecar(_EXT_COLL)
        assert sidecar is not None
        # Sidecar holds the expire timestamp.
        meta = await sidecar.get_metadata(oid)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertIsNotNone(meta.get("e"))
        # Round-trip via public API.
        expire_at = await self.client.get_expire(ExternalItem, oid)
        self.assertIsNotNone(expire_at)

    async def test_cleanup_via_sidecar_removes_expired(self):
        """Documents with short TTL stored via sidecar are removed by cleanup()."""
        # Insert 3 with TTL=1s.
        for i in range(3):
            await self.client.set(
                ExternalItem(title=f"alpha_{i}", embedding=[1.0, float(i)*0.1, 0.0, 0.0]),
                expire=1,
            )
        # Insert 2 permanent.
        for i in range(2):
            await self.client.set(
                ExternalItem(title=f"beta_{i}", embedding=[0.0, 1.0, float(i)*0.1, 0.0]),
            )

        # Wait for visibility.
        for _ in range(_CONSISTENCY_RETRIES):
            count = await self.client.collection_count(ExternalItem)
            if count >= 5:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertEqual(await self.client.collection_count(ExternalItem), 5)

        # Wait for TTL to elapse, then force cleanup.
        await asyncio.sleep(2)
        removed = await self.client.cleanup(force=True)
        self.assertGreaterEqual(removed, 3, f"Expected ≥3 sidecar-tracked rows removed, got {removed}")

        remaining = 5
        for _ in range(_CONSISTENCY_RETRIES * 2):
            remaining = await self.client.collection_count(ExternalItem)
            if remaining <= 2:
                break
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        self.assertEqual(remaining, 2, f"Expected 2 permanent rows to survive, got {remaining}")

    async def test_set_expire_roundtrip_via_sidecar(self):
        """set_expire() / get_expire() roundtrip on a sidecar collection."""
        oid = await self.client.set(
            ExternalItem(title="alpha_x", embedding=[1.0, 0.0, 0.0, 0.0]),
        )
        # No expire by default.
        self.assertIsNone(await self.client.get_expire(ExternalItem, oid))

        # Apply 600s TTL via set_expire.
        ok = await self.client.set_expire(ExternalItem, oid, 600)
        self.assertTrue(ok)
        ttl = await self.client.get_expire(ExternalItem, oid)
        self.assertIsNotNone(ttl)
        assert ttl is not None
        # Remaining TTL should be close to 600s.
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, 600)


if __name__ == "__main__":
    unittest.main()
