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
from core.storage.orm.client_base import _build_mongo_selected_query, _query_to_expression
from core.storage.orm.redis_search import RedisScalarFieldSpec, compile_redis_query
from core.storage.vector import (
    AnnoySQLiteVectorClient,
    VectorIndex,
    VectorORMField,
    VectorORMModel,
    _milvus_expression_to_filter,
)


class VectorNormalizationRecord(VectorORMModel, collection_name="vector_query_normalization_records"):
    title: str = ""
    category: str = ""
    rank: int = 0
    embedding: list[float] = VectorORMField(default_factory=list, index=VectorIndex(dim=2))


class EmptyVectorRecord(VectorORMModel, collection_name="vector_empty_records"):
    title: str = ""
    embedding: list[float] = VectorORMField(default_factory=list, index=VectorIndex(dim=2))


def _close_vector_client(client: object) -> None:
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
                    for operand in value.values():
                        if isinstance(operand, list):
                            found.extend(operand)
                        else:
                            found.append(operand)
                else:
                    found.append(value)
            found.extend(_collect_id_operands(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_collect_id_operands(item))
    return found


def test_vector_query_helpers_normalize_compounds() -> None:
    object_id = ObjectId()

    mongo_query = {
        "$or": [
            {"id": str(object_id)},
            {"title": {"$wildcard": "a*b*c"}},
        ],
        "rank": {"$gte": 2},
    }
    mongo_filter = _build_mongo_selected_query(mongo_query)
    assert mongo_filter is not None
    assert "$or" in str(mongo_filter)
    id_operands = _collect_id_operands(mongo_filter)
    assert any(isinstance(value, ObjectId) for value in id_operands)

    redis_query = compile_redis_query(
        {
            "$or": [
                {"title": {"$wildcard": "a*b*c"}},
                {"category": "notes"},
            ],
            "rank": {"$gte": 2},
        },
        {
            "id": RedisScalarFieldSpec(field_path="id", kind="string"),
            "title": RedisScalarFieldSpec(field_path="title", kind="string"),
            "category": RedisScalarFieldSpec(field_path="category", kind="string"),
            "rank": RedisScalarFieldSpec(field_path="rank", kind="numeric"),
        },
    )
    assert "|" in redis_query
    assert "a*b*c" in redis_query

    milvus_expression = _query_to_expression(
        {
            "$or": [
                {"title": "alpha"},
                {"rank": {"$gte": 3}},
            ],
            "category": "notes",
        }
    )
    assert milvus_expression is not None
    milvus_filter = _milvus_expression_to_filter(
        milvus_expression,
        available_scalar={"title", "category", "rank"},
    )
    assert milvus_filter is not None
    assert " or " in milvus_filter.lower()
    assert " and " in milvus_filter.lower()


def test_annoy_search_supports_compound_mapping_query() -> None:
    async def _run() -> None:
        tmp_dir = tempfile.mkdtemp()
        client = AnnoySQLiteVectorClient(db_dir=tmp_dir, cleanup_interval=1)
        client.start()
        try:
            await client.create_collection(VectorNormalizationRecord)
            await client.set(VectorNormalizationRecord(id="64e0000000000000000000a1", title="axbyc", category="wild", rank=2, embedding=[1.0, 0.0]))
            await client.set(VectorNormalizationRecord(id="64e0000000000000000000b2", title="notes doc", category="notes", rank=3, embedding=[0.8, 0.2]))
            await client.set(VectorNormalizationRecord(id="64e0000000000000000000c3", title="acb", category="other", rank=3, embedding=[0.0, 1.0]))

            query = {
                "$or": [
                    {"title": {"$wildcard": "a*b*c"}},
                    {"category": "notes"},
                ],
                "rank": {"$gte": 2},
            }
            rows = [
                item async for item in client.search(
                    VectorNormalizationRecord,
                    query,
                    as_model=False,
                )
            ]
            assert {row["id"] for row in rows} == {"64e0000000000000000000a1", "64e0000000000000000000b2"}
        finally:
            _close_vector_client(client)
            await asyncio.sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    asyncio.run(_run())


def test_annoy_selected_search_compound_query_uses_sql_pushdown() -> None:
    async def _run() -> None:
        tmp_dir = tempfile.mkdtemp()
        client = AnnoySQLiteVectorClient(db_dir=tmp_dir, cleanup_interval=1)
        client.start()
        try:
            await client.create_collection(VectorNormalizationRecord)
            await client.set(VectorNormalizationRecord(id="64e0000000000000000000d4", title="alpha", category="notes", rank=1, embedding=[1.0, 0.0]))
            await client.set(VectorNormalizationRecord(id="64e0000000000000000000e5", title="beta", category="notes", rank=3, embedding=[0.8, 0.2]))
            await client.set(VectorNormalizationRecord(id="64e0000000000000000000f6", title="gamma", category="other", rank=3, embedding=[0.0, 1.0]))

            query = {
                "$or": [
                    {"title": "alpha"},
                    {"rank": {"$gte": 3}},
                ],
                "category": "notes",
            }
            with patch.object(client, "search", side_effect=AssertionError("compound selected_search should be pushed down to SQLite")):
                rows = [
                    item async for item in client.selected_search(
                        VectorNormalizationRecord,
                        fields=("title", "rank"),
                        query=query,
                    )
                ]
            assert rows == [
                {"id": "64e0000000000000000000d4", "title": "alpha", "rank": 1},
                {"id": "64e0000000000000000000e5", "title": "beta", "rank": 3},
            ]
        finally:
            _close_vector_client(client)
            await asyncio.sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    asyncio.run(_run())


def test_annoy_search_skips_build_when_no_valid_vectors_exist() -> None:
    async def _run() -> None:
        tmp_dir = tempfile.mkdtemp()
        client = AnnoySQLiteVectorClient(db_dir=tmp_dir, cleanup_interval=1)
        client.start()
        try:
            await client.create_collection(EmptyVectorRecord)
            await client.set(EmptyVectorRecord(id="64e0000000000000000000aa", title="empty", embedding=[]))

            rows = [
                item async for item in client.search_vector(
                    EmptyVectorRecord,
                    [1.0, 0.0],
                    as_model=False,
                )
            ]

            assert rows == []
            assert not client._annoy_path(EmptyVectorRecord.CollectionName, "embedding").exists()
        finally:
            _close_vector_client(client)
            await asyncio.sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    asyncio.run(_run())


def test_annoy_selected_search_without_sys_table_still_returns_rows() -> None:
    async def _run() -> None:
        tmp_dir = tempfile.mkdtemp()
        client = AnnoySQLiteVectorClient(db_dir=tmp_dir, cleanup_interval=1)
        client.start()
        try:
            await client.create_collection(VectorNormalizationRecord)
            await client.set(VectorNormalizationRecord(id="64e0000000000000000000d4", title="alpha", category="notes", rank=1, embedding=[1.0, 0.0]))
            await client.set(VectorNormalizationRecord(id="64e0000000000000000000e5", title="beta", category="notes", rank=3, embedding=[0.8, 0.2]))

            conn = client._ensure_started()
            sys_tbl = f"{VectorNormalizationRecord.CollectionName}_sys"
            conn.execute(f'DROP TABLE IF EXISTS "{sys_tbl}"')
            conn.commit()

            rows = [
                item async for item in client.selected_search(
                    VectorNormalizationRecord,
                    fields=("title", "rank"),
                    query={"category": "notes"},
                )
            ]
            assert rows == [
                {"id": "64e0000000000000000000d4", "title": "alpha", "rank": 1},
                {"id": "64e0000000000000000000e5", "title": "beta", "rank": 3},
            ]
        finally:
            _close_vector_client(client)
            await asyncio.sleep(0.05)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    asyncio.run(_run())