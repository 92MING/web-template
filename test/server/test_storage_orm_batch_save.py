from _test_helpers import (
    StorageMongoORMTestBase,
    StorageMySQLORMTestBase,
    StorageORMTestBase,
    StoragePostgreSQLORMTestBase,
    StorageRedisORMTestBase,
)
from core.storage.orm import ORMField, ORMModel


class _BatchSaveNote(ORMModel, collection_name="batch_save_notes"):
    title: str = ""
    category: str = ORMField(default="", index=True)
    score: int = 0


class _BatchSaveBehaviorMixin:
    async def test_batch_save_writes_and_upserts(self):
        storage_config = self._storage_config
        assert storage_config is not None
        client = storage_config.orm.get_client("cache")

        first_ids = await _BatchSaveNote.BatchSave(
            [
                {"id": "batch-a", "title": "Alpha", "category": "demo", "score": 1},
                {"id": "batch-b", "title": "Beta", "category": "demo", "score": 2},
            ],
            client=client,
        )
        self.assertEqual(first_ids, ["batch-a", "batch-b"])

        rows = [item async for item in _BatchSaveNote.Search({"category": "demo"}, client=client, as_model=False)]
        self.assertEqual(len(rows), 2)

        await _BatchSaveNote.BatchSave(
            [
                {"id": "batch-a", "title": "Alpha-Updated", "category": "demo", "score": 9},
                _BatchSaveNote(title="Gamma", category="demo", score=3),
            ],
            client=client,
        )

        final_rows = [item async for item in _BatchSaveNote.Search({"category": "demo"}, client=client, as_model=False)]
        final_by_id = {str(row["id"]): row for row in final_rows}
        self.assertIn("batch-a", final_by_id)
        self.assertIn("batch-b", final_by_id)
        self.assertEqual(len(final_by_id), 3)
        self.assertEqual(final_by_id["batch-a"]["title"], "Alpha-Updated")
        self.assertEqual(final_by_id["batch-a"]["score"], 9)
        self.assertTrue(any(row["title"] == "Gamma" and row["score"] == 3 for row in final_rows))


class TestSQLiteORMBatchSave(_BatchSaveBehaviorMixin, StorageORMTestBase):
    pass


class TestRedisORMBatchSave(_BatchSaveBehaviorMixin, StorageRedisORMTestBase):
    pass


class TestMySQLORMBatchSave(_BatchSaveBehaviorMixin, StorageMySQLORMTestBase):
    pass


class TestPostgreSQLORMBatchSave(_BatchSaveBehaviorMixin, StoragePostgreSQLORMTestBase):
    pass


class TestMongoORMBatchSave(_BatchSaveBehaviorMixin, StorageMongoORMTestBase):
    pass