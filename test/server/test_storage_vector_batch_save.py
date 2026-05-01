import unittest

from _test_helpers import (
    StorageMilvusVectorTestBase,
    StorageMongoVectorTestBase,
    StorageRedisVectorTestBase,
    StorageVectorTestBase,
)
from core.storage.vector import VectorIndex, VectorORMField, VectorORMModel


class _BatchVectorNote(VectorORMModel, collection_name="batch_vector_notes"):
    title: str = ""
    embedding: list[float] = VectorORMField(default_factory=list, index=VectorIndex(dim=3, metric_type="COSINE"))


class _VectorBatchSaveBehaviorMixin:
    async def test_batch_save_writes_and_upserts(self):
        storage_config = self._storage_config
        assert storage_config is not None
        client = storage_config.vector.get_client("cache")

        try:
            first_ids = await _BatchVectorNote.BatchSave(
                [
                    {"id": "vec-a", "title": "Alpha", "embedding": [1.0, 0.0, 0.0]},
                    {"id": "vec-b", "title": "Beta", "embedding": [0.0, 1.0, 0.0]},
                ],
                client=client,
            )
        except ValueError as exc:
            if "Mongo vector search is not enabled" in str(exc):
                raise unittest.SkipTest(str(exc)) from exc
            raise
        self.assertEqual(first_ids, ["vec-a", "vec-b"])

        rows = [item async for item in _BatchVectorNote.Search(client=client, as_model=False)]
        self.assertEqual(len(rows), 2)

        await _BatchVectorNote.BatchSave(
            [
                {"id": "vec-a", "title": "Alpha-Updated", "embedding": [0.0, 0.0, 1.0]},
                _BatchVectorNote(title="Gamma", embedding=[0.5, 0.5, 0.5]),
            ],
            client=client,
        )

        final_rows = [item async for item in _BatchVectorNote.Search(client=client, as_model=False)]
        final_by_id = {str(row["id"]): row for row in final_rows}
        self.assertIn("vec-a", final_by_id)
        self.assertIn("vec-b", final_by_id)
        self.assertEqual(len(final_by_id), 3)
        self.assertEqual(final_by_id["vec-a"]["title"], "Alpha-Updated")
        self.assertEqual(final_by_id["vec-a"]["embedding"], [0.0, 0.0, 1.0])
        self.assertTrue(any(row["title"] == "Gamma" and row["embedding"] == [0.5, 0.5, 0.5] for row in final_rows))


class TestLocalVectorBatchSave(_VectorBatchSaveBehaviorMixin, StorageVectorTestBase):
    pass


class TestRedisVectorBatchSave(_VectorBatchSaveBehaviorMixin, StorageRedisVectorTestBase):
    pass


class TestMongoVectorBatchSave(_VectorBatchSaveBehaviorMixin, StorageMongoVectorTestBase):
    pass


class TestMilvusVectorBatchSave(_VectorBatchSaveBehaviorMixin, StorageMilvusVectorTestBase):
    pass