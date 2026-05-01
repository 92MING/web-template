# -*- coding: utf-8 -*-
"""MinIO-backed Object Storage API regression tests."""


import unittest

from _test_helpers import StorageMinIOObjectTestBase


class TestMinIOObjectConfig(StorageMinIOObjectTestBase):
    async def test_config_backend_type_is_minio(self):
        resp = await self._client.get("/_internal/admin/api/storage/object/config")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["backend"], "minio")


class TestMinIOObjectCRUD(StorageMinIOObjectTestBase):
    async def test_upload_meta_get_and_delete_roundtrip(self):
        files = {"files": ("hello.txt", b"hello minio", "text/plain")}
        upload_resp = await self._client.post("/_internal/admin/api/storage/object/upload", files=files)
        self.assertEqual(upload_resp.status_code, 200)
        path = upload_resp.json()["uploaded"][0]["path"]

        meta_resp = await self._client.get("/_internal/admin/api/storage/object/meta", params={"path": path})
        self.assertEqual(meta_resp.status_code, 200)
        self.assertEqual(meta_resp.json()["path"], path)

        content_resp = await self._client.get("/_internal/admin/api/storage/object/content", params={"path": path})
        self.assertEqual(content_resp.status_code, 200)
        self.assertEqual(content_resp.content, b"hello minio")

        delete_resp = await self._client.delete("/_internal/admin/api/storage/object/item", params={"path": path})
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])


if __name__ == "__main__":
    unittest.main()
