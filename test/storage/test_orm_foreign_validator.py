from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from core.storage.orm import ORMField, ORMModel, SQL_ORM_Client, SQLiteORMClient


def _make_child_model(suffix: str):
    class _Child(ORMModel, full_collection_name=f"foreign_validator_child_{suffix}"):
        label: str = ""

    return _Child


def _make_parent_model(suffix: str, child_cls: type[ORMModel]):
    class _Parent(ORMModel, full_collection_name=f"foreign_validator_parent_{suffix}"):
        title: str = ""
        child: child_cls = ORMField(foreign_model=True)  # type: ignore[valid-type]
        opt_child: child_cls | None = ORMField(default=None, foreign_model=True)  # type: ignore[valid-type]

    return _Parent


async def _close_client(client: object) -> None:
    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        try:
            await aclose()
            return
        except Exception:
            pass
    close = getattr(client, "close", None)
    if callable(close):
        close()


class TestForeignValidatorSQLite(unittest.IsolatedAsyncioTestCase):
    async def test_model_validate_resolves_foreign_id_via_sync_sqlite_lookup(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            client = SQLiteORMClient(db_path=Path(tmp_dir) / "foreign_validator.sqlite3")
            client.start()
            child_cls = None
            parent_cls = None
            try:
                child_cls = _make_child_model("sqlite")
                parent_cls = _make_parent_model("sqlite", child_cls)
                child_cls.Client = client
                parent_cls.Client = client

                await client.create_collection(child_cls)
                await client.create_collection(parent_cls)

                child = child_cls(label="sqlite-child")
                await client.set(child)

                with patch.object(child_cls, "SearchOneById", side_effect=AssertionError("SQLite validator should not use async SearchOneById fallback")):
                    parent = parent_cls.model_validate({
                        "title": "sqlite-parent",
                        "child": str(child.id),
                        "opt_child": str(child.id),
                    })

                self.assertIsInstance(parent.child, child_cls)
                self.assertEqual(parent.child.label, "sqlite-child")
                self.assertIsInstance(parent.opt_child, child_cls)
                self.assertEqual(parent.opt_child.label, "sqlite-child")
            finally:
                if child_cls is not None:
                    child_cls.Client = None
                if parent_cls is not None:
                    parent_cls.Client = None
                await _close_client(client)


class TestForeignValidatorSQLClientSQLite(unittest.IsolatedAsyncioTestCase):
    async def test_model_validate_resolves_foreign_id_via_sqlite_url_shortcut(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            db_path = Path(tmp_dir) / "foreign_validator_sql.sqlite3"
            client = SQL_ORM_Client(url=f"sqlite:///{db_path.as_posix()}")
            client.start()
            child_cls = None
            parent_cls = None
            try:
                child_cls = _make_child_model("sqlsqlite")
                parent_cls = _make_parent_model("sqlsqlite", child_cls)
                child_cls.Client = client
                parent_cls.Client = client

                await client.create_collection(child_cls)
                await client.create_collection(parent_cls)

                child = child_cls(label="sql-child")
                await client.set(child)

                with patch.object(child_cls, "SearchOneById", side_effect=AssertionError("SQL sqlite validator should not use async SearchOneById fallback")):
                    parent = parent_cls.model_validate({
                        "title": "sql-parent",
                        "child": str(child.id),
                        "opt_child": str(child.id),
                    })

                self.assertIsInstance(parent.child, child_cls)
                self.assertEqual(parent.child.label, "sql-child")
                self.assertIsInstance(parent.opt_child, child_cls)
                self.assertEqual(parent.opt_child.label, "sql-child")
            finally:
                if child_cls is not None:
                    child_cls.Client = None
                if parent_cls is not None:
                    parent_cls.Client = None
                await _close_client(client)