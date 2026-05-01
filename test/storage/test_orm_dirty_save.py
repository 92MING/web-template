"""Tests for ORMModel dirty-save behaviour (TODO §0.1).

These tests use the local SQLite ORM backend so they run cheaply in CI without
needing external DBs. The dirty tracking lives on the model layer, so the
behaviour is backend-agnostic; only the no-op-skip optimisation is tested
here. Per-backend wire-level partial UPDATE is a follow-up (see TODO §0.1).
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from core.storage.config import (
    KV_StorageConfig,
    LocalKVDBConfig,
    LocalObjectDBConfig,
    ObjectStorageConfig,
    ORMStorageConfig,
    SQLiteORMDBConfig,
    StorageConfig,
)
from core.storage.orm import ORMModel
from core.storage.orm.client_base import ORM_ClientBase


class _DirtyDoc(ORMModel, collection_name='dirty_docs'):
    title: str = ''
    score: int = 0


class _DeleteHookDoc(ORMModel, collection_name='delete_hook_docs'):
    _event: ClassVar[asyncio.Event | None] = None
    _deleted_ids: ClassVar[list[str]] = []

    title: str = ''

    async def post_delete(self) -> None:
        type(self)._deleted_ids.append(str(self.id))
        event = type(self)._event
        if event is not None:
            event.set()


class _EmptyDeleteHookDoc(ORMModel, collection_name='empty_delete_hook_docs'):
    title: str = ''

    async def post_delete(self) -> None:
        pass


class TestORMModelDirtySave(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        root = Path(self._tmp)
        ORM_ClientBase.ClearDefaultInstances()
        config = StorageConfig(
            orm=ORMStorageConfig(
                default=SQLiteORMDBConfig(db_path=str(root / 'orm.sqlite3'), namespace='dirty'),
            ),
            kv=KV_StorageConfig(
                default=LocalKVDBConfig(db_path=str(root / 'kv.sqlite3'), namespace='dirty'),
            ),
            object=ObjectStorageConfig(
                default=LocalObjectDBConfig(
                    root_path=str(root / 'objects'),
                    metadata_db=LocalKVDBConfig(db_path=str(root / 'objects_meta.sqlite3'), namespace='dirty:objects'),
                    namespace='dirty',
                ),
            ),
        )
        StorageConfig.SetGlobal(config)

    async def test_new_instance_starts_dirty(self) -> None:
        doc = _DirtyDoc(title='hello', score=1)
        self.assertTrue(doc.IsDirty)
        self.assertEqual(doc.DirtyFields, frozenset({'title', 'score'}))
        self.assertTrue(hasattr(doc, '__dirty__'))
        self.assertTrue(hasattr(doc, '__persisted__'))
        self.assertEqual(getattr(doc, '__dirty__'), {'title', 'score'})
        self.assertFalse(getattr(doc, '__persisted__'))
        self.assertFalse(hasattr(doc, '_dirty'))
        self.assertFalse(hasattr(doc, '_persisted'))

    async def test_save_clears_dirty_and_skips_when_clean(self) -> None:
        doc = _DirtyDoc(title='hello', score=1)
        first_id = await doc.save()
        self.assertFalse(doc.IsDirty)

        # Second save with no mutation must be a no-op (return same id).
        second_id = await doc.save()
        self.assertEqual(second_id, first_id)
        self.assertFalse(doc.IsDirty)

    async def test_force_save_runs_even_when_clean(self) -> None:
        doc = _DirtyDoc(title='hello', score=1)
        await doc.save()
        # Force=True must still call the backend (we just check that no exception
        # is raised and the result remains coherent).
        forced_id = await doc.save(force=True)
        self.assertEqual(forced_id, str(doc.id))

    async def test_mutation_re_dirties(self) -> None:
        doc = _DirtyDoc(title='hello', score=1)
        await doc.save()
        self.assertFalse(doc.IsDirty)
        doc.score = 42
        self.assertTrue(doc.IsDirty)
        self.assertEqual(doc.DirtyFields, frozenset({'score'}))
        await doc.save()
        self.assertFalse(doc.IsDirty)

    async def test_hydrated_instance_starts_clean(self) -> None:
        doc = _DirtyDoc(title='hello', score=1)
        new_id = await doc.save()
        loaded = await _DirtyDoc.SearchOneById(new_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertFalse(loaded.IsDirty)

    async def test_instance_delete_schedules_post_delete(self) -> None:
        event = asyncio.Event()
        _DeleteHookDoc._event = event
        _DeleteHookDoc._deleted_ids.clear()

        doc = _DeleteHookDoc(title='hello')
        await doc.save()

        self.assertTrue(await doc.delete())
        await asyncio.wait_for(event.wait(), timeout=1.0)
        self.assertEqual(_DeleteHookDoc._deleted_ids, [str(doc.id)])

    async def test_class_delete_with_instance_schedules_post_delete(self) -> None:
        event = asyncio.Event()
        _DeleteHookDoc._event = event
        _DeleteHookDoc._deleted_ids.clear()

        doc = _DeleteHookDoc(title='hello again')
        await doc.save()

        self.assertTrue(await _DeleteHookDoc.Delete(doc))
        await asyncio.wait_for(event.wait(), timeout=1.0)
        self.assertEqual(_DeleteHookDoc._deleted_ids, [str(doc.id)])

    async def test_empty_post_delete_does_not_schedule_task(self) -> None:
        doc = _EmptyDeleteHookDoc(title='noop')
        await doc.save()

        with patch('core.storage.orm.model.asyncio.create_task') as create_task:
            self.assertTrue(await doc.delete())

        create_task.assert_not_called()

    async def test_delete_accepts_query_dict(self) -> None:
        first = _DirtyDoc(title='keep', score=1)
        second = _DirtyDoc(title='remove-a', score=7)
        third = _DirtyDoc(title='remove-b', score=7)
        await first.save()
        await second.save()
        await third.save()

        self.assertTrue(await _DirtyDoc.Delete({'score': 7}))
        remaining = [item async for item in _DirtyDoc.Search()]
        self.assertEqual({item.title for item in remaining}, {'keep'})

    async def test_delete_accepts_query_expression(self) -> None:
        first = _DirtyDoc(title='keep', score=2)
        second = _DirtyDoc(title='remove', score=9)
        await first.save()
        await second.save()

        self.assertTrue(await _DirtyDoc.Delete(_DirtyDoc.score == 9))
        remaining = [item async for item in _DirtyDoc.Search()]
        self.assertEqual({item.title for item in remaining}, {'keep'})

    async def test_delete_rejects_none(self) -> None:
        with self.assertRaises(TypeError):
            await _DirtyDoc.Delete(None)  # type: ignore[arg-type]


if __name__ == '__main__':
    unittest.main()
