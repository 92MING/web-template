"""Large-scale expire + max_size / LRU cleanup tests for all local storage backends.

Phase 20.2: Validates that expire actually removes data after TTL elapses,
and max_size / LRU eviction keeps the most-recently-accessed entries.

Backends under test (all local — no external services):
  - KV: LocalKVClient
  - ORM: SQLiteORMClient, SQL_ORM_Client (SQLAlchemy + SQLite)
  - Vector: AnnoySQLiteVectorClient
  - Object: LocalObjectClient
"""
import shutil
import sys
import tempfile
import time
import unittest
from asyncio import sleep
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.storage.kv import SQLiteKVClient
from core.storage.object import LocalObjectClient
from core.storage.orm import ORMField, ORMModel, SQL_ORM_Client, SQLiteORMClient
from core.storage.vector import AnnoySQLiteVectorClient, VectorIndex, VectorORMField, VectorORMModel

# ---------------------------------------------------------------------------
# Test ORM / Vector models
# ---------------------------------------------------------------------------

class ExpireNote(ORMModel, collection_name="expire_notes"):
    title: str = ORMField(default="")
    payload: str = ORMField(default="")


class ExpireVec(VectorORMModel, collection_name="expire_vecs", client=None):
    label: str = VectorORMField(default="")
    embedding: list[float] = VectorORMField(default_factory=list, index=VectorIndex(dim=8))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_vector(seed: int, dim: int = 8) -> list[float]:
    """Deterministic unit-ish vector for testing."""
    import math
    raw = [(seed * 7 + i) % 97 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def _close_safe(client: object) -> None:
    for method in ("aclose", "close"):
        fn = getattr(client, method, None)
        if callable(fn):
            try:
                import asyncio, inspect
                result = fn()
                if inspect.isawaitable(result):
                    try:
                        asyncio.get_running_loop().create_task(result)
                    except RuntimeError:
                        asyncio.run(result)
            except Exception:
                pass
            return


# ===================================================================
# 1. KV — expire + max_size/LRU  (100+ keys)
# ===================================================================

class TestLocalKVExpireAndMaxSize(unittest.IsolatedAsyncioTestCase):
    """LocalKVClient: large-scale expire + LRU eviction."""

    async def test_expire_removes_keys_after_ttl(self) -> None:
        """100 keys with short TTL expire correctly; 100 permanent keys survive."""
        with tempfile.TemporaryDirectory() as tmp:
            client = SQLiteKVClient(db_path=Path(tmp) / "kv.sqlite3", cleanup_interval=0)
            client.start()
            try:
                n = 100
                for i in range(n):
                    await client.set(f"perm:{i}", f"value-{i}")
                for i in range(n):
                    await client.set(f"temp:{i}", f"dying-{i}", expire=0.05)

                await sleep(0.1)

                for i in range(n):
                    self.assertIsNotNone(await client.get(f"perm:{i}"), f"perm:{i} should survive")
                for i in range(n):
                    self.assertIsNone(await client.get(f"temp:{i}"), f"temp:{i} should have expired")
            finally:
                _close_safe(client)

    async def test_set_expire_after_creation(self) -> None:
        """set_expire retroactively adds TTL; key expires afterward."""
        with tempfile.TemporaryDirectory() as tmp:
            client = SQLiteKVClient(db_path=Path(tmp) / "kv.sqlite3", cleanup_interval=0)
            client.start()
            try:
                await client.set("retro", "will die")
                self.assertIsNone(await client.get_expire("retro"))
                await client.set_expire("retro", 1)
                ttl = await client.get_expire("retro")
                self.assertIsNotNone(ttl)
                self.assertGreater(ttl, 0)

                await sleep(1.5)
                self.assertIsNone(await client.get("retro"))
            finally:
                _close_safe(client)

    async def test_max_size_lru_eviction_large(self) -> None:
        """Insert 150 keys into max_size=50 client, cleanup retains 45 most recent."""
        with tempfile.TemporaryDirectory() as tmp:
            client = SQLiteKVClient(db_path=Path(tmp) / "kv.sqlite3", max_size=50, cleanup_interval=0)
            client.start()
            try:
                total = 150
                for i in range(total):
                    await client.set(f"k:{i}", f"v-{i}")

                removed = await client.cleanup(force=True)
                self.assertGreater(removed, 0, "cleanup must evict some entries")

                surviving = []
                for i in range(total):
                    val = await client.get(f"k:{i}")
                    if val is not None:
                        surviving.append(i)

                self.assertLessEqual(len(surviving), 50, "should be <= max_size after cleanup")
                self.assertGreater(len(surviving), 0, "at least some keys should survive")
            finally:
                _close_safe(client)

    async def test_lru_keeps_recently_accessed(self) -> None:
        """Access older keys to promote them; LRU should evict untouched keys instead."""
        with tempfile.TemporaryDirectory() as tmp:
            client = SQLiteKVClient(db_path=Path(tmp) / "kv.sqlite3", max_size=30, cleanup_interval=0)
            client.start()
            try:
                for i in range(60):
                    await client.set(f"item:{i}", f"data-{i}")

                # Touch the first 10 items to promote them in LRU
                for i in range(10):
                    await client.get(f"item:{i}")

                await client.cleanup(force=True)

                # The first 10 (recently accessed) should all survive
                for i in range(10):
                    val = await client.get(f"item:{i}")
                    self.assertIsNotNone(val, f"item:{i} was accessed recently, should survive LRU")
            finally:
                _close_safe(client)


# ===================================================================
# 2. ORM SQLite — expire + max_size/LRU  (100+ docs)
# ===================================================================

class TestSQLiteORMExpireAndMaxSize(unittest.IsolatedAsyncioTestCase):

    async def test_expire_removes_docs_after_ttl(self) -> None:
        tmp = tempfile.mkdtemp()
        client = SQLiteORMClient(db_path=Path(tmp) / "orm.sqlite3", cleanup_interval=0)
        client.start()
        try:
            await client.create_collection(ExpireNote)
            ids_perm: list[str] = []
            ids_temp: list[str] = []

            for i in range(100):
                obj_id = await client.set(ExpireNote(title=f"perm-{i}", payload="x" * 50))
                ids_perm.append(str(obj_id))

            for i in range(100):
                obj_id = await client.set(ExpireNote(title=f"temp-{i}", payload="y" * 50))
                ids_temp.append(str(obj_id))
                await client.set_expire(ExpireNote, str(obj_id), 5)

            await sleep(6)
            removed = await client.cleanup(force=True)
            self.assertGreaterEqual(removed, 90, "most temp docs should be expired+cleaned")

            for oid in ids_perm:
                doc = await client.get(ExpireNote, oid)
                self.assertIsNotNone(doc, f"permanent doc {oid} should survive")

            expired_alive = 0
            for oid in ids_temp:
                doc = await client.get(ExpireNote, oid)
                if doc is not None:
                    expired_alive += 1
            self.assertEqual(expired_alive, 0, "all expired docs should be gone")
        finally:
            try:
                aclose = getattr(client, "aclose", None)
                if callable(aclose):
                    await aclose()
                else:
                    client.close()
            except Exception:
                pass
            shutil.rmtree(tmp, ignore_errors=True)

    async def test_max_size_lru_eviction(self) -> None:
        tmp = tempfile.mkdtemp()
        client = SQLiteORMClient(db_path=Path(tmp) / "orm.sqlite3", max_size=40, cleanup_interval=999)
        client.start()
        try:
            await client.create_collection(ExpireNote)
            all_ids: list[str] = []
            for i in range(120):
                obj_id = await client.set(ExpireNote(title=f"doc-{i}", payload="z" * 30))
                all_ids.append(str(obj_id))

            # Re-write the first 20 docs to promote them in LRU (ORM tracks write time, not read time)
            for oid in all_ids[:20]:
                doc = await client.get(ExpireNote, oid)
                if doc is not None:
                    await client.set(doc)

            removed = await client.cleanup(force=True)
            self.assertGreater(removed, 0)

            live_count = 0
            promoted_alive = 0
            for idx, oid in enumerate(all_ids):
                doc = await client.get(ExpireNote, oid)
                if doc is not None:
                    live_count += 1
                    if idx < 20:
                        promoted_alive += 1

            self.assertLessEqual(live_count, 40, "live count should be <= max_size")
            self.assertGreaterEqual(promoted_alive, 15, "most re-written docs should survive LRU")
        finally:
            try:
                aclose = getattr(client, "aclose", None)
                if callable(aclose):
                    await aclose()
                else:
                    client.close()
            except Exception:
                pass
            shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# 3. ORM SQLAlchemy — expire + max_size/LRU  (100+ docs)
# ===================================================================

class TestSQLAlchemyORMExpireAndMaxSize(unittest.IsolatedAsyncioTestCase):

    async def test_expire_removes_docs_after_ttl(self) -> None:
        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "orm_sa.sqlite3"
        client = SQL_ORM_Client(url=f"sqlite:///{db_path.as_posix()}", cleanup_interval=0)
        client.start()
        try:
            await client.create_collection(ExpireNote)
            ids_perm: list[str] = []
            ids_temp: list[str] = []

            for i in range(100):
                obj_id = await client.set(ExpireNote(title=f"perm-{i}", payload="x" * 50))
                ids_perm.append(str(obj_id))

            for i in range(100):
                obj_id = await client.set(ExpireNote(title=f"temp-{i}", payload="y" * 50))
                ids_temp.append(str(obj_id))
                await client.set_expire(ExpireNote, str(obj_id), 5)

            await sleep(6)
            removed = await client.cleanup(force=True)
            self.assertGreaterEqual(removed, 90, "most temp docs should be expired+cleaned")

            for oid in ids_perm:
                doc = await client.get(ExpireNote, oid)
                self.assertIsNotNone(doc, f"permanent doc {oid} should survive")

            expired_alive = 0
            for oid in ids_temp:
                doc = await client.get(ExpireNote, oid)
                if doc is not None:
                    expired_alive += 1
            self.assertEqual(expired_alive, 0, "all expired docs should be gone")
        finally:
            try:
                aclose = getattr(client, "aclose", None)
                if callable(aclose):
                    await aclose()
                else:
                    client.close()
            except Exception:
                pass
            shutil.rmtree(tmp, ignore_errors=True)

    async def test_max_size_lru_eviction(self) -> None:
        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "orm_sa.sqlite3"
        client = SQL_ORM_Client(url=f"sqlite:///{db_path.as_posix()}", max_size=40, cleanup_interval=999)
        client.start()
        try:
            await client.create_collection(ExpireNote)
            all_ids: list[str] = []
            for i in range(120):
                obj_id = await client.set(ExpireNote(title=f"doc-{i}", payload="z" * 30))
                all_ids.append(str(obj_id))

            # Re-write the first 20 docs to promote them (ORM tracks write time, not read time)
            for oid in all_ids[:20]:
                doc = await client.get(ExpireNote, oid)
                if doc is not None:
                    await client.set(doc)

            removed = await client.cleanup(force=True)
            self.assertGreater(removed, 0)

            live_count = 0
            promoted_alive = 0
            for idx, oid in enumerate(all_ids):
                doc = await client.get(ExpireNote, oid)
                if doc is not None:
                    live_count += 1
                    if idx < 20:
                        promoted_alive += 1

            self.assertLessEqual(live_count, 40)
            self.assertGreaterEqual(promoted_alive, 15, "most re-written docs should survive LRU")
        finally:
            try:
                aclose = getattr(client, "aclose", None)
                if callable(aclose):
                    await aclose()
                else:
                    client.close()
            except Exception:
                pass
            shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# 4. Vector Annoy — expire + max_size/LRU  (100+ vectors)
# ===================================================================

class TestAnnoyVectorExpireAndMaxSize(unittest.IsolatedAsyncioTestCase):

    async def test_expire_removes_vectors_after_ttl(self) -> None:
        tmp = tempfile.mkdtemp()
        client = AnnoySQLiteVectorClient(db_dir=str(Path(tmp) / "annoy"), cleanup_interval=0)
        client.start()
        try:
            await client.create_collection(ExpireVec)
            ids_perm: list[str] = []
            ids_temp: list[str] = []

            for i in range(100):
                vec = ExpireVec(label=f"perm-{i}", embedding=_dummy_vector(i))
                obj_id = await client.set(vec)
                ids_perm.append(str(obj_id))

            for i in range(100, 200):
                vec = ExpireVec(label=f"temp-{i}", embedding=_dummy_vector(i))
                obj_id = await client.set(vec)
                ids_temp.append(str(obj_id))
                await client.set_expire(ExpireVec, str(obj_id), 2)

            await sleep(3)
            removed = await client.cleanup(force=True)
            self.assertGreaterEqual(removed, 90, "most temp vectors should be expired+cleaned")

            for oid in ids_perm:
                doc = await client.get(ExpireVec, oid)
                self.assertIsNotNone(doc, f"permanent vector {oid} should survive")

            expired_alive = 0
            for oid in ids_temp:
                doc = await client.get(ExpireVec, oid)
                if doc is not None:
                    expired_alive += 1
            self.assertEqual(expired_alive, 0, "all expired vectors should be gone")
        finally:
            client.close()
            shutil.rmtree(tmp, ignore_errors=True)

    async def test_max_size_lru_eviction(self) -> None:
        tmp = tempfile.mkdtemp()
        client = AnnoySQLiteVectorClient(db_dir=str(Path(tmp) / "annoy"), max_size=40, cleanup_interval=999)
        client.start()
        try:
            await client.create_collection(ExpireVec)
            all_ids: list[str] = []
            for i in range(120):
                vec = ExpireVec(label=f"vec-{i}", embedding=_dummy_vector(i))
                obj_id = await client.set(vec)
                all_ids.append(str(obj_id))

            # Re-write the first 20 vectors to promote them (vector tracks write time, not read time)
            for oid in all_ids[:20]:
                doc = await client.get(ExpireVec, oid, as_model=False)
                if doc is not None:
                    vec = ExpireVec(**{k: v for k, v in doc.items() if k not in ("_id", "id")}, id=oid)
                    await client.set(vec)

            removed = await client.cleanup(force=True)
            self.assertGreater(removed, 0)

            live_count = 0
            promoted_alive = 0
            for idx, oid in enumerate(all_ids):
                doc = await client.get(ExpireVec, oid)
                if doc is not None:
                    live_count += 1
                    if idx < 20:
                        promoted_alive += 1

            self.assertLessEqual(live_count, 40, "live count should be <= max_size")
            self.assertGreaterEqual(promoted_alive, 15, "most re-written vectors should survive LRU")
        finally:
            client.close()
            shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# 5. Object Local — expire + max_size/LRU
# ===================================================================

class TestLocalObjectExpireAndMaxSize(unittest.IsolatedAsyncioTestCase):

    async def test_expire_removes_objects_after_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = LocalObjectClient(root_path=Path(tmp) / "objects", cleanup_interval=0)
            client.start()
            try:
                for i in range(50):
                    await client.put_bytes(f"perm-data-{i}".encode(), object_name=f"perm/{i}.bin")

                for i in range(50):
                    await client.put_bytes(f"temp-data-{i}".encode(), object_name=f"temp/{i}.bin", expire=2)

                await sleep(3)
                # cleanup triggers list_metadata which auto-deletes expired items inline,
                # so removed count may be 0 (already deleted during iteration).
                await client.cleanup(force=True)

                for i in range(50):
                    data = await client.get_bytes(f"perm/{i}.bin")
                    self.assertIsNotNone(data, f"perm/{i}.bin should survive")

                expired_alive = 0
                for i in range(50):
                    data = await client.get_bytes(f"temp/{i}.bin")
                    if data is not None:
                        expired_alive += 1
                self.assertEqual(expired_alive, 0, "all expired objects should be gone")
            finally:
                client.close()

    async def test_set_expire_after_put(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = LocalObjectClient(root_path=Path(tmp) / "objects", cleanup_interval=0)
            client.start()
            try:
                await client.put_bytes(b"hello", object_name="retro.bin")
                self.assertIsNone(await client.get_expire("retro.bin"))

                await client.set_expire("retro.bin", 1)
                ttl = await client.get_expire("retro.bin")
                self.assertIsNotNone(ttl)
                self.assertGreater(ttl, 0)

                await sleep(1.5)
                data = await client.get_bytes("retro.bin")
                self.assertIsNone(data, "object should have expired")
            finally:
                client.close()

    async def test_max_size_lru_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # max_size for Object is a byte budget, not a count.
            # 80 objects × 100 bytes = 8000 total; max_size=2000 forces heavy eviction.
            client = LocalObjectClient(root_path=Path(tmp) / "objects", max_size=2000, cleanup_interval=0)
            client.start()
            try:
                all_names: list[str] = []
                for i in range(80):
                    name = f"obj/{i}.bin"
                    await client.put_bytes(b"x" * 100, object_name=name)
                    all_names.append(name)

                removed = await client.cleanup(force=True)
                self.assertGreater(removed, 0)

                live_bytes = 0
                for name in all_names:
                    data = await client.get_bytes(name)
                    if data is not None:
                        live_bytes += len(data)

                self.assertLessEqual(live_bytes, 2000, "live byte total should be <= max_size after cleanup")
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
