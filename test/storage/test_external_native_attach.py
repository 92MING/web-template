"""Integration tests for attaching local models to externally created storage.

These tests validate the user-facing scenario where a backend-native table or
collection already exists, then a local ORM/vector model with nearly the same
shape attaches to it and can continue normal CRUD/search operations.
"""

import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from core.storage.base import ObjectId
from core.storage.orm import ORMField, ORMModel, PostgreSQLORMClient, SQLiteORMClient
from core.storage.vector import PyMilvusVectorClient, VectorIndex, VectorORMField, VectorORMModel


POSTGRES_HOST = os.getenv("TEST_POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("TEST_POSTGRES_PORT", "5433"))
POSTGRES_USER = os.getenv("TEST_POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("TEST_POSTGRES_PASSWORD", "postgres")
MILVUS_URI = os.getenv("TEST_MILVUS_URI", "http://127.0.0.1:19530")
MILVUS_TOKEN = os.getenv("TEST_MILVUS_TOKEN", None) or None
_CONSISTENCY_RETRIES = 8
_CONSISTENCY_SLEEP = 0.5


def _new_id() -> str:
    return str(ObjectId())


async def _close_orm_client(client: object) -> None:
    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        try:
            await aclose()
            return
        except Exception:
            pass
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _make_sql_attach_model(collection: str):
    class _AttachItem(ORMModel, collection_name=collection):
        title: str = ORMField(default="", index=True)
        score: int = ORMField(default=0, index=True)
        status: str = ORMField(default="", index=True)

    return _AttachItem


def _make_milvus_attach_model(collection: str):
    class _AttachVectorItem(VectorORMModel, collection_name=collection):
        __NoExpireField__ = True

        title: str = ""
        embedding: list[float] = VectorORMField(
            default_factory=list,
            index=VectorIndex(dim=3, metric_type="COSINE"),
        )

    return _AttachVectorItem


def _retry_loop_ready(async_fn):
    async def _runner(*args, **kwargs):
        last = None
        for _ in range(_CONSISTENCY_RETRIES):
            last = await async_fn(*args, **kwargs)
            if last:
                return last
            await asyncio.sleep(_CONSISTENCY_SLEEP)
        return last

    return _runner


@_retry_loop_ready
async def _retry_get(client, model, object_id: str):
    return await client.get(model, object_id)


async def _retry_get_none(client, model, object_id: str):
    last = await client.get(model, object_id)
    for _ in range(_CONSISTENCY_RETRIES):
        if last is None:
            return None
        await asyncio.sleep(_CONSISTENCY_SLEEP)
        last = await client.get(model, object_id)
    return last


@_retry_loop_ready
async def _retry_vector_search_ids(client, model, vector: list[float], expect_id: str):
    rows = [item async for item in client.search_vector(model, vector, limit=3)]
    if rows and str(rows[0].id) == expect_id:
        return rows
    return None


def _ensure_postgres_available() -> None:
    try:
        import psycopg

        with psycopg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname="postgres",
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as exc:
        raise unittest.SkipTest(f"PostgreSQL not available at {POSTGRES_HOST}:{POSTGRES_PORT}: {exc}") from exc


def _create_postgres_database(database: str) -> None:
    import psycopg

    with psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname="postgres",
        autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if cur.fetchone() is None:
                cur.execute(f'DROP DATABASE IF EXISTS "{database}"')
                cur.execute(f'CREATE DATABASE "{database}"')


def _drop_postgres_database(database: str) -> None:
    import psycopg

    with psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname="postgres",
        autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{database}"')


def _create_external_postgres_table(database: str, collection: str) -> None:
    import psycopg

    with psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=database,
        autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "_orm_{collection}_sys"')
            cur.execute(f'DROP TABLE IF EXISTS "orm_{collection}"')
            cur.execute(f'CREATE TABLE "orm_{collection}" (id TEXT PRIMARY KEY, title TEXT, score INTEGER)')
            cur.execute(
                f'INSERT INTO "orm_{collection}" (id, title, score) VALUES (%s, %s, %s)',
                ("ext-a", "alpha", 7),
            )


def _ensure_milvus_available() -> None:
    try:
        from pymilvus import connections, utility

        alias = f"native-attach-probe-{os.getpid()}"
        connections.connect(alias=alias, uri=MILVUS_URI, token=MILVUS_TOKEN)
        utility.list_collections(using=alias)
        connections.disconnect(alias)
    except Exception as exc:
        raise unittest.SkipTest(f"Milvus not available at {MILVUS_URI}: {exc}") from exc


def _drop_milvus_collection(*, uri: str, token: str | None, collection_name: str, db_name: str | None = None) -> None:
    from pymilvus import connections, utility

    alias = f"native-attach-drop-{os.getpid()}-{time.time_ns()}"
    try:
        connect_kwargs = {"alias": alias, "uri": uri, "token": token}
        if db_name:
            connect_kwargs["db_name"] = db_name
        connections.connect(**connect_kwargs)
        if utility.has_collection(collection_name, using=alias):
            utility.drop_collection(collection_name, using=alias)
    except Exception:
        pass
    finally:
        try:
            connections.disconnect(alias)
        except Exception:
            pass


def _create_external_milvus_collection(*, collection_name: str, docs: list[dict[str, object]] | None = None) -> None:
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

    alias = f"native-attach-create-{os.getpid()}-{time.time_ns()}"
    connections.connect(alias=alias, uri=MILVUS_URI, token=MILVUS_TOKEN)
    try:
        if utility.has_collection(collection_name, using=alias):
            utility.drop_collection(collection_name, using=alias)
        schema = CollectionSchema(
            fields=[
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=3),
            ],
            enable_dynamic_field=True,
        )
        collection = Collection(name=collection_name, schema=schema, using=alias)
        collection.create_index(
            field_name="embedding",
            index_params={"index_type": "AUTOINDEX", "metric_type": "COSINE"},
        )
        payloads = list(docs or [])
        if payloads:
            collection.insert([
                [str(doc.get("id") or doc.get("_id") or "") for doc in payloads],
                [str(doc.get("title") or "") for doc in payloads],
                [list(doc.get("embedding") or []) for doc in payloads],
            ])
            collection.flush()
        collection.load()
    finally:
        connections.disconnect(alias)


class TestSQLiteNativeTableAttach(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_native_table_attach_then_crud(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        db_path = Path(tmp_dir) / "external_attach.sqlite3"
        collection = f"native_sqlite_attach_{time.time_ns()}"
        model_cls = _make_sql_attach_model(collection)
        ext_a = _new_id()
        ext_b = _new_id()

        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(f'CREATE TABLE "orm_{collection}" (id TEXT PRIMARY KEY, title TEXT, score INTEGER)')
            conn.execute(
                f'INSERT INTO "orm_{collection}" (id, title, score) VALUES (?, ?, ?)',
                (ext_a, "alpha", 7),
            )
            conn.commit()

        client = SQLiteORMClient(db_path=db_path, cleanup_interval=999999)
        client.start()
        try:
            await client.create_collection(model_cls)

            existing = await client.get(model_cls, ext_a)
            self.assertIsNotNone(existing)
            self.assertEqual(existing.title, "alpha")
            self.assertEqual(existing.score, 7)

            await client.set(model_cls(id=ext_a, title="alpha-updated", score=11, status="seed"))
            updated = await client.get(model_cls, ext_a)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.title, "alpha-updated")
            self.assertEqual(updated.status, "seed")

            await client.set(model_cls(id=ext_b, title="beta", score=3, status="fresh"))
            rows = [item async for item in client.search(model_cls, {"status": "fresh"}, as_model=False)]
            self.assertEqual([row["id"] for row in rows], [ext_b])

            self.assertTrue(await client.delete(model_cls.CollectionName, ext_a))
            self.assertIsNone(await client.get(model_cls, ext_a))

            with sqlite3.connect(str(db_path)) as conn:
                row = conn.execute(
                    "SELECT collection_name FROM _orm_collections WHERE collection_name = ?",
                    (collection,),
                ).fetchone()
            self.assertEqual(row[0], collection)
        finally:
            await _close_orm_client(client)
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestPostgreSQLNativeTableAttach(unittest.IsolatedAsyncioTestCase):
    async def test_postgresql_native_table_attach_then_crud(self) -> None:
        _ensure_postgres_available()
        database = f"proj_test_attach_{time.time_ns()}"
        collection = f"native_pg_attach_{time.time_ns()}"
        model_cls = _make_sql_attach_model(collection)
        ext_a = _new_id()
        ext_b = _new_id()

        _create_postgres_database(database)
        _create_external_postgres_table(database, collection)

        import psycopg

        with psycopg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=database,
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DELETE FROM "orm_{collection}"')
                cur.execute(
                    f'INSERT INTO "orm_{collection}" (id, title, score) VALUES (%s, %s, %s)',
                    (ext_a, "alpha", 7),
                )

        client = PostgreSQLORMClient(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            username=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=database,
            cleanup_interval=999999,
        )
        client.start()
        try:
            await client.create_collection(model_cls)

            existing = await client.get(model_cls, ext_a)
            self.assertIsNotNone(existing)
            self.assertEqual(existing.title, "alpha")
            self.assertEqual(existing.score, 7)

            await client.set(model_cls(id=ext_a, title="alpha-updated", score=11, status="seed"))
            updated = await client.get(model_cls, ext_a)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.title, "alpha-updated")
            self.assertEqual(updated.status, "seed")

            await client.set(model_cls(id=ext_b, title="beta", score=3, status="fresh"))
            rows = [item async for item in client.search(model_cls, {"status": "fresh"}, as_model=False)]
            self.assertEqual([row["id"] for row in rows], [ext_b])

            self.assertTrue(await client.delete(model_cls.CollectionName, ext_a))
            self.assertIsNone(await client.get(model_cls, ext_a))

            with psycopg.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=database,
                autocommit=True,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT collection_name FROM _orm_collections WHERE collection_name = %s",
                        (collection,),
                    )
                    row = cur.fetchone()
            self.assertEqual(row[0], collection)
        finally:
            await _close_orm_client(client)
            _drop_postgres_database(database)


class TestMilvusNativeCollectionAttach(unittest.IsolatedAsyncioTestCase):
    async def test_milvus_native_collection_attach_then_search_and_crud(self) -> None:
        _ensure_milvus_available()
        collection = f"native_milvus_attach_{time.time_ns()}"
        model_cls = _make_milvus_attach_model(collection)
        ext_a = _new_id()
        ext_b = _new_id()
        ext_c = _new_id()

        _drop_milvus_collection(uri=MILVUS_URI, token=MILVUS_TOKEN, collection_name=collection)
        _create_external_milvus_collection(collection_name=collection)

        client = PyMilvusVectorClient(
            uri=MILVUS_URI,
            token=MILVUS_TOKEN,
            name=f"native_attach_{os.getpid()}_{time.time_ns()}",
        )
        client.start()
        try:
            await client.create_collection(model_cls)

            await client.set(model_cls(id=ext_a, title="alpha", embedding=[1.0, 0.0, 0.0]))
            await client.set(model_cls(id=ext_b, title="beta", embedding=[0.0, 1.0, 0.0]))

            existing = await _retry_get(client, model_cls, ext_a)
            self.assertIsNotNone(existing)
            self.assertEqual(existing.title, "alpha")

            search_rows = await _retry_vector_search_ids(client, model_cls, [1.0, 0.0, 0.0], ext_a)
            self.assertIsNotNone(search_rows)
            self.assertEqual(str(search_rows[0].id), ext_a)

            await client.set(model_cls(id=ext_a, title="alpha-updated", embedding=[1.0, 0.0, 0.0]))
            updated = await _retry_get(client, model_cls, ext_a)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.title, "alpha-updated")

            await client.set(model_cls(id=ext_c, title="gamma", embedding=[0.0, 0.0, 1.0]))
            created = await _retry_get(client, model_cls, ext_c)
            self.assertIsNotNone(created)
            self.assertEqual(created.title, "gamma")

            self.assertTrue(await client.delete(model_cls.CollectionName, ext_b))
            removed = await _retry_get_none(client, model_cls, ext_b)
            self.assertIsNone(removed)
        finally:
            try:
                await client.drop_collection(model_cls.CollectionName)
            except Exception:
                pass
            client.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)