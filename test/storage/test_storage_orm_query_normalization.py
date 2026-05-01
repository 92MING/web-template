import asyncio
import os
import shutil
import sys
import tempfile

from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from core.storage.base import ObjectId
from core.storage.orm.query import _ParamCounter
from core.storage.orm.client_base import (
    _match_query_or_expr,
    _query_to_mongo_filter, 
    _query_to_sql_conditions,
    
)
from core.storage.orm import (
    ORMModel,
    SQLiteORMClient,
)


class QueryNormalizationNote(ORMModel, collection_name="query_normalization_notes"):
    title: str
    category: str = "general"
    order: int = 0


def _close_orm_client(client: object) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _collect_id_operands(payload: object) -> list[object]:
    found: list[object] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "_id":
                if isinstance(value, dict):
                    found.extend(_collect_id_operands(value))
                    for operand in value.values():
                        if isinstance(operand, list):
                            found.extend(operand)
                        else:
                            found.append(operand)
                    continue
                found.append(value)
            found.extend(_collect_id_operands(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_collect_id_operands(item))
    return found


def test_mapping_query_compounds_normalize_to_sql_and_mongo() -> None:
    object_id = ObjectId()
    query = {
        "$or": [
            {"id": str(object_id)},
            {"title": {"$regex": "^Al"}},
        ],
        "category": {"$in": ["demo", "keep"]},
        "order": {"$gte": 2},
    }

    sql_result = _query_to_sql_conditions(query, "sqlite", counter=_ParamCounter())
    assert sql_result is not None
    conditions, params = sql_result
    assert any(" OR " in condition for condition in conditions)
    assert any(value == str(object_id) for value in params.values())

    mongo_filter = _query_to_mongo_filter(query)
    assert mongo_filter is not None
    id_operands = _collect_id_operands(mongo_filter)
    assert id_operands
    assert any(isinstance(value, ObjectId) for value in id_operands)


def test_mapping_query_compounds_match_in_memory() -> None:
    query = {
        "$or": [
            {"title": {"$wildcard": "Al*"}},
            {"category": "demo"},
        ],
        "order": {"$gte": 2},
    }
    assert _match_query_or_expr({"id": "1", "title": "Alice", "category": "keep", "order": 2}, query)
    assert _match_query_or_expr({"id": "2", "title": "Bob", "category": "demo", "order": 3}, query)
    assert not _match_query_or_expr({"id": "3", "title": "Bob", "category": "keep", "order": 3}, query)


def test_sqlite_compound_mapping_query_uses_pushdown() -> None:
    async def _run() -> None:
        tmp_dir = tempfile.mkdtemp()
        db_path = Path(tmp_dir) / "query_normalization.sqlite3"
        client = SQLiteORMClient(db_path=db_path, cleanup_interval=1)
        client.start()
        try:
            await client.create_collection(QueryNormalizationNote)
            await client.set(QueryNormalizationNote(title="Alice", category="keep", order=2))
            await client.set(QueryNormalizationNote(title="Bob", category="demo", order=3))
            await client.set(QueryNormalizationNote(title="Charlie", category="demo", order=1))

            query = {
                "$or": [
                    {"title": {"$wildcard": "Al*"}},
                    {"category": "demo"},
                ],
                "order": {"$gte": 2},
            }

            with patch(
                "core.storage.orm.client_base._match_query_or_expr",
                side_effect=AssertionError("compound mapping query should be pushed down to SQL"),
            ):
                rows = [
                    item async for item in client.search(
                        QueryNormalizationNote,
                        query,
                        as_model=False,
                    )
                ]
            assert {row["title"] for row in rows} == {"Alice", "Bob"}
        finally:
            _close_orm_client(client)
            await asyncio.sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    asyncio.run(_run())
