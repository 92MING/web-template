"""Concurrent large-file read/write tests for object storage backends.

Backends tested:
  - LocalObjectClient  (always runs)
  - MinIOObjectClient   (skipped when MinIO is unreachable)

Each test uploads several 5 MB files concurrently, reads them back
concurrently, and verifies data integrity via SHA-256 digests.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from core.storage.object import LocalObjectClient, MinIOObjectClient

# ── constants ────────────────────────────────────────────────────────────────

FILE_SIZE = 5 * 1024 * 1024   # 5 MB
FILE_COUNT = 6                 # concurrent files
_SUFFIX = str(int(time.time()))


def _random_blob(size: int = FILE_SIZE) -> bytes:
    return os.urandom(size)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# Local filesystem
# ══════════════════════════════════════════════════════════════════════════════

class TestLocalObjectConcurrentLargeFiles(unittest.IsolatedAsyncioTestCase):
    """Concurrent 5 MB × 6 files via LocalObjectClient."""

    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.client = LocalObjectClient(
            root_path=Path(self._tmpdir.name) / "objects",
            metadata_db_path=Path(self._tmpdir.name) / "objects_meta.sqlite3",
            cleanup_interval=0,
        )
        self.client.start()

    async def asyncTearDown(self):
        self.client.close()
        self._tmpdir.cleanup()

    async def test_concurrent_write_then_concurrent_read(self):
        """Write FILE_COUNT files concurrently, then read them back concurrently."""
        blobs = [_random_blob() for _ in range(FILE_COUNT)]
        expected_digests = [_sha256(b) for b in blobs]
        names = [f"large/file_{i}_{_SUFFIX}.bin" for i in range(FILE_COUNT)]

        # ── concurrent writes ──
        async def _write(i: int) -> None:
            await self.client.put_bytes(blobs[i], object_name=names[i])

        await asyncio.gather(*(_write(i) for i in range(FILE_COUNT)))

        # ── concurrent reads ──
        async def _read(i: int) -> bytes | None:
            return await self.client.get_bytes(names[i])

        results = await asyncio.gather(*(_read(i) for i in range(FILE_COUNT)))

        for i, data in enumerate(results):
            self.assertIsNotNone(data, f"{names[i]} should be readable")
            self.assertEqual(len(data), FILE_SIZE, f"{names[i]} size mismatch")  # type: ignore[arg-type]
            self.assertEqual(_sha256(data), expected_digests[i], f"{names[i]} digest mismatch")  # type: ignore[arg-type]

    async def test_concurrent_chunked_read(self):
        """Write a file, then read it back with multiple concurrent chunked streams."""
        blob = _random_blob()
        expected = _sha256(blob)
        name = f"large/chunked_{_SUFFIX}.bin"
        await self.client.put_bytes(blob, object_name=name)

        async def _chunked_read() -> str:
            chunks: list[bytes] = []
            async for chunk in self.client.get(name, chunk_size=65536):
                chunks.append(chunk)
            return _sha256(b"".join(chunks))

        # 4 concurrent chunked readers on the same file
        digests = await asyncio.gather(*(_chunked_read() for _ in range(4)))
        for d in digests:
            self.assertEqual(d, expected)

    async def test_concurrent_write_same_name_no_crash(self):
        """Multiple concurrent writes to the same object_name — no crash, file readable."""
        blobs = [_random_blob() for _ in range(4)]
        name = f"large/race_{_SUFFIX}.bin"

        async def _write(data: bytes) -> None:
            await self.client.put_bytes(data, object_name=name)

        await asyncio.gather(*(_write(b) for b in blobs))

        # With non-atomic local FS writes, the final content may be
        # interleaved; we only assert the file is readable and non-empty.
        got = await self.client.get_bytes(name)
        self.assertIsNotNone(got)
        self.assertGreater(len(got), 0)  # type: ignore[arg-type]

    async def test_concurrent_put_file(self):
        """Concurrent put_file from temp files."""
        blobs = [_random_blob() for _ in range(FILE_COUNT)]
        expected_digests = [_sha256(b) for b in blobs]
        names = [f"large/fromfile_{i}_{_SUFFIX}.bin" for i in range(FILE_COUNT)]

        tmp_paths: list[str] = []
        for blob in blobs:
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
            f.write(blob)
            f.close()
            tmp_paths.append(f.name)

        try:
            async def _upload(i: int) -> None:
                await self.client.put_file(tmp_paths[i], object_name=names[i])

            await asyncio.gather(*(_upload(i) for i in range(FILE_COUNT)))

            async def _read(i: int) -> bytes | None:
                return await self.client.get_bytes(names[i])

            results = await asyncio.gather(*(_read(i) for i in range(FILE_COUNT)))

            for i, data in enumerate(results):
                self.assertIsNotNone(data, f"{names[i]} should exist")
                self.assertEqual(_sha256(data), expected_digests[i], f"{names[i]} digest mismatch")  # type: ignore[arg-type]
        finally:
            for p in tmp_paths:
                Path(p).unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# MinIO
# ══════════════════════════════════════════════════════════════════════════════

MINIO_ENDPOINT = os.getenv("TEST_MINIO_ENDPOINT", "127.0.0.1:9002")
MINIO_ACCESS_KEY = os.getenv("TEST_MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("TEST_MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = f"proj-conc-test-{_SUFFIX}"


def _minio_available() -> bool:
    try:
        async def _probe():
            from miniopy_async import Minio
            mc = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
            try:
                await mc.list_buckets()
            finally:
                await mc._session.close()
        asyncio.run(_probe())
        return True
    except Exception:
        return False


_MINIO_UP = _minio_available()


def _make_minio_client() -> MinIOObjectClient:
    client = MinIOObjectClient(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        bucket=MINIO_BUCKET,
        secure=False,
    )
    client.start()
    return client


@unittest.skipUnless(_MINIO_UP, f"MinIO not available at {MINIO_ENDPOINT}")
class TestMinIOConcurrentLargeFiles(unittest.IsolatedAsyncioTestCase):
    """Concurrent 5 MB × 6 files via MinIOObjectClient."""

    async def asyncSetUp(self):
        self.client = _make_minio_client()
        self._created: list[str] = []

    async def asyncTearDown(self):
        for name in self._created:
            try:
                await self.client.delete(name)
            except Exception:
                pass
        self.client.close()

    async def test_concurrent_write_then_concurrent_read(self):
        blobs = [_random_blob() for _ in range(FILE_COUNT)]
        expected_digests = [_sha256(b) for b in blobs]
        names = [f"conc/file_{i}.bin" for i in range(FILE_COUNT)]
        self._created.extend(names)

        async def _write(i: int) -> None:
            await self.client.put_bytes(blobs[i], object_name=names[i])

        await asyncio.gather(*(_write(i) for i in range(FILE_COUNT)))

        async def _read(i: int) -> bytes | None:
            return await self.client.get_bytes(names[i])

        results = await asyncio.gather(*(_read(i) for i in range(FILE_COUNT)))

        for i, data in enumerate(results):
            self.assertIsNotNone(data, f"{names[i]} should be readable")
            self.assertEqual(len(data), FILE_SIZE, f"{names[i]} size mismatch")  # type: ignore[arg-type]
            self.assertEqual(_sha256(data), expected_digests[i], f"{names[i]} digest mismatch")  # type: ignore[arg-type]

    async def test_concurrent_chunked_read(self):
        blob = _random_blob()
        expected = _sha256(blob)
        name = "conc/chunked.bin"
        self._created.append(name)
        await self.client.put_bytes(blob, object_name=name)

        async def _chunked_read() -> str:
            chunks: list[bytes] = []
            async for chunk in self.client.get(name, chunk_size=65536):
                chunks.append(chunk)
            return _sha256(b"".join(chunks))

        digests = await asyncio.gather(*(_chunked_read() for _ in range(4)))
        for d in digests:
            self.assertEqual(d, expected)

    async def test_concurrent_write_same_name_no_crash(self):
        blobs = [_random_blob() for _ in range(4)]
        name = "conc/race.bin"
        self._created.append(name)

        async def _write(data: bytes) -> None:
            await self.client.put_bytes(data, object_name=name)

        await asyncio.gather(*(_write(b) for b in blobs))

        got = await self.client.get_bytes(name)
        self.assertIsNotNone(got)
        self.assertGreater(len(got), 0)  # type: ignore[arg-type]

    async def test_concurrent_stream_upload(self):
        """Concurrent async-generator uploads."""
        blobs = [_random_blob() for _ in range(FILE_COUNT)]
        expected_digests = [_sha256(b) for b in blobs]
        names = [f"conc/stream_{i}.bin" for i in range(FILE_COUNT)]
        self._created.extend(names)

        async def _stream_write(i: int) -> None:
            async def _gen():
                data = blobs[i]
                for offset in range(0, len(data), 65536):
                    yield data[offset:offset + 65536]
            await self.client.put(_gen(), object_name=names[i])

        await asyncio.gather(*(_stream_write(i) for i in range(FILE_COUNT)))

        async def _read(i: int) -> bytes | None:
            return await self.client.get_bytes(names[i])

        results = await asyncio.gather(*(_read(i) for i in range(FILE_COUNT)))

        for i, data in enumerate(results):
            self.assertIsNotNone(data, f"{names[i]} should be readable")
            self.assertEqual(_sha256(data), expected_digests[i], f"{names[i]} digest mismatch")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
