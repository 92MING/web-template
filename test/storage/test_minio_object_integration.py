"""Integration tests: MinIO object client — CRUD, metadata, streaming, cleanup.

Target: MinIOObjectClient against proj-minio-test (127.0.0.1:9002).
"""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from core.storage.object import MinIOObjectClient

MINIO_ENDPOINT = os.getenv("TEST_MINIO_ENDPOINT", "127.0.0.1:9002")
MINIO_ACCESS_KEY = os.getenv("TEST_MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("TEST_MINIO_SECRET_KEY", "minioadmin")
TEST_BUCKET = "proj-integ-test"


def _make_client(*, bucket: str = TEST_BUCKET) -> MinIOObjectClient:
    client = MinIOObjectClient(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        bucket=bucket,
        secure=False,
    )
    client.start()
    return client


def setUpModule():
    """Skip module if MinIO not reachable."""
    async def _probe():
        from miniopy_async import Minio
        mc = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
        try:
            await mc.list_buckets()
        finally:
            await mc._session.close()
    try:
        asyncio.run(_probe())
    except Exception as exc:
        raise unittest.SkipTest(f"MinIO not available at {MINIO_ENDPOINT}: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════════════
# Basic CRUD
# ══════════════════════════════════════════════════════════════════════════════

class TestMinIOCRUD(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.client = _make_client()
        self._created: list[str] = []

    async def asyncTearDown(self):
        for name in self._created:
            try:
                await self.client.delete(name)
            except Exception:
                pass
        self.client.close()

    async def _put_and_track(self, data: bytes, name: str, **kwargs):
        self._created.append(name)
        return await self.client.put_bytes(data, object_name=name, **kwargs)

    # ── put_bytes / get_bytes ──
    async def test_put_and_get_bytes(self):
        meta = await self._put_and_track(b"hello minio", "test/hello.txt")
        self.assertIn("path", meta)

        got = await self.client.get_bytes("test/hello.txt")
        self.assertEqual(got, b"hello minio")

    async def test_put_bytes_content_type(self):
        meta = await self._put_and_track(
            b"<h1>hi</h1>", "test/page.html",
            content_type="text/html",
        )
        self.assertIn("path", meta)

    async def test_get_bytes_nonexistent(self):
        got = await self.client.get_bytes("nonexistent/file.txt")
        self.assertIsNone(got)

    # ── put_file / get roundtrip ──
    async def test_put_file_and_chunked_get(self):
        content = b"A" * 4096
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(content)
            tmp_path = f.name
        try:
            self._created.append("test/from_file.bin")
            await self.client.put_file(tmp_path, object_name="test/from_file.bin")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        chunks: list[bytes] = []
        async for chunk in self.client.get("test/from_file.bin"):
            chunks.append(chunk)
        self.assertEqual(b"".join(chunks), content)

    # ── put (stream) ──
    async def test_put_stream(self):
        async def _gen():
            yield b"chunk1"
            yield b"chunk2"
        self._created.append("test/streamed.txt")
        meta = await self.client.put(_gen(), object_name="test/streamed.txt")
        self.assertIn("path", meta)

        got = await self.client.get_bytes("test/streamed.txt")
        self.assertEqual(got, b"chunk1chunk2")

    # ── overwrite ──
    async def test_overwrite_existing(self):
        await self._put_and_track(b"version1", "test/overwrite.txt")
        # Overwrite without adding to _created again (already tracked)
        await self.client.put_bytes(b"version2", object_name="test/overwrite.txt")

        got = await self.client.get_bytes("test/overwrite.txt")
        self.assertEqual(got, b"version2")

    # ── delete ──
    async def test_delete_existing(self):
        await self.client.put_bytes(b"delete me", object_name="test/delete_me.txt")
        deleted = await self.client.delete("test/delete_me.txt")
        self.assertTrue(deleted)

        got = await self.client.get_bytes("test/delete_me.txt")
        self.assertIsNone(got)

    async def test_delete_nonexistent(self):
        # Should not raise
        deleted = await self.client.delete("test/never_existed_12345.txt")
        # Behaviour: either True or False is fine, just no crash
        self.assertIsInstance(deleted, bool)


# ══════════════════════════════════════════════════════════════════════════════
# Metadata
# ══════════════════════════════════════════════════════════════════════════════

class TestMinIOMetadata(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.client = _make_client()
        self._created: list[str] = []

    async def asyncTearDown(self):
        for name in self._created:
            try:
                await self.client.delete(name)
            except Exception:
                pass
        self.client.close()

    async def test_metadata_roundtrip(self):
        self._created.append("test/meta.txt")
        meta = await self.client.put_bytes(
            b"some data", object_name="test/meta.txt",
            metadata={"author": "bot", "version": "3"},
        )
        self.assertIn("path", meta)
        # Size
        self.assertEqual(meta.get("size"), len(b"some data"))

    async def test_metadata_custom_fields(self):
        self._created.append("test/meta_custom.txt")
        await self.client.put_bytes(
            b"data",
            object_name="test/meta_custom.txt",
            metadata={"foo": "bar", "count": "42"},
        )
        # get_bytes should still work (metadata doesn't interfere)
        got = await self.client.get_bytes("test/meta_custom.txt")
        self.assertEqual(got, b"data")


# ══════════════════════════════════════════════════════════════════════════════
# Large payload
# ══════════════════════════════════════════════════════════════════════════════

class TestMinIOLargePayload(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.client = _make_client()
        self._created: list[str] = []

    async def asyncTearDown(self):
        for name in self._created:
            try:
                await self.client.delete(name)
            except Exception:
                pass
        self.client.close()

    async def test_1mb_upload(self):
        data = os.urandom(1024 * 1024)  # 1 MB
        self._created.append("test/large_1mb.bin")
        await self.client.put_bytes(data, object_name="test/large_1mb.bin")

        got = await self.client.get_bytes("test/large_1mb.bin")
        self.assertEqual(got, data)

    async def test_chunked_get_1mb(self):
        data = os.urandom(1024 * 1024)
        self._created.append("test/large_chunked.bin")
        await self.client.put_bytes(data, object_name="test/large_chunked.bin")

        chunks: list[bytes] = []
        async for chunk in self.client.get("test/large_chunked.bin", chunk_size=4096):
            chunks.append(chunk)
        self.assertEqual(b"".join(chunks), data)


# ══════════════════════════════════════════════════════════════════════════════
# Expire-based cleanup
# ══════════════════════════════════════════════════════════════════════════════

class TestMinIOExpireCleanup(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.client = _make_client()
        self._created: list[str] = []

    async def asyncTearDown(self):
        for name in self._created:
            try:
                await self.client.delete(name)
            except Exception:
                pass
        self.client.close()

    async def test_put_with_expire(self):
        """Put with expire; object should be retrievable before expiry."""
        self._created.append("test/expiring.txt")
        await self.client.put_bytes(
            b"expires later", object_name="test/expiring.txt",
            expire=3600,  # 1 hour from now
        )
        got = await self.client.get_bytes("test/expiring.txt")
        self.assertEqual(got, b"expires later")


# ══════════════════════════════════════════════════════════════════════════════
# Bucket auto-creation
# ══════════════════════════════════════════════════════════════════════════════

class TestMinIOBucketCreation(unittest.IsolatedAsyncioTestCase):

    async def test_auto_create_bucket(self):
        """Client.start() should create the bucket if it doesn't exist."""
        unique_bucket = f"proj-integ-auto-{int(time.time())}"
        client = MinIOObjectClient(
            endpoint=MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            bucket=unique_bucket,
            secure=False,
        )
        try:
            client.start()
            # Should not raise
            await client.put_bytes(b"hi", object_name="probe.txt")
            got = await client.get_bytes("probe.txt")
            self.assertEqual(got, b"hi")
        finally:
            try:
                await client.delete("probe.txt")
            except Exception:
                pass
            # Clean up bucket
            try:
                from miniopy_async import Minio
                mc = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
                await mc.remove_bucket(unique_bucket)
                await mc._session.close()
            except Exception:
                pass
            client.close()


# ══════════════════════════════════════════════════════════════════════════════
# Multiple objects + isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestMinIOMultipleObjects(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.client = _make_client()
        self._created: list[str] = []

    async def asyncTearDown(self):
        for name in self._created:
            try:
                await self.client.delete(name)
            except Exception:
                pass
        self.client.close()

    async def test_multiple_objects_isolated(self):
        for i in range(5):
            name = f"test/multi_{i}.txt"
            self._created.append(name)
            await self.client.put_bytes(f"content_{i}".encode(), object_name=name)

        for i in range(5):
            got = await self.client.get_bytes(f"test/multi_{i}.txt")
            self.assertEqual(got, f"content_{i}".encode())

    async def test_delete_one_keeps_others(self):
        self._created.append("test/keep.txt")
        self._created.append("test/remove.txt")
        await self.client.put_bytes(b"keep", object_name="test/keep.txt")
        await self.client.put_bytes(b"remove", object_name="test/remove.txt")

        await self.client.delete("test/remove.txt")

        got_keep = await self.client.get_bytes("test/keep.txt")
        self.assertEqual(got_keep, b"keep")

        got_removed = await self.client.get_bytes("test/remove.txt")
        self.assertIsNone(got_removed)


# ══════════════════════════════════════════════════════════════════════════════
# Binary content preservation
# ══════════════════════════════════════════════════════════════════════════════

class TestMinIOBinaryContent(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.client = _make_client()
        self._created: list[str] = []

    async def asyncTearDown(self):
        for name in self._created:
            try:
                await self.client.delete(name)
            except Exception:
                pass
        self.client.close()

    async def test_binary_roundtrip(self):
        data = bytes(range(256))
        self._created.append("test/binary.bin")
        await self.client.put_bytes(data, object_name="test/binary.bin")
        got = await self.client.get_bytes("test/binary.bin")
        self.assertEqual(got, data)

    async def test_empty_bytes(self):
        self._created.append("test/empty.bin")
        await self.client.put_bytes(b"", object_name="test/empty.bin")
        got = await self.client.get_bytes("test/empty.bin")
        self.assertEqual(got, b"")

    async def test_utf8_content(self):
        text = "你好世界 Unicode 🎉".encode("utf-8")
        self._created.append("test/unicode.txt")
        await self.client.put_bytes(text, object_name="test/unicode.txt")
        got = await self.client.get_bytes("test/unicode.txt")
        self.assertEqual(got, text)


if __name__ == "__main__":
    unittest.main()
