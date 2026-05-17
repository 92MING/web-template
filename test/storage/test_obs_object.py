import tempfile
import unittest

from pathlib import Path

from core.storage.object import LocalObjectClient, OBS_Object


class TestOBSObject(unittest.IsolatedAsyncioTestCase):
    async def test_search_returns_obs_object_and_supports_bytes_and_metadata_access(self) -> None:
        with tempfile.TemporaryDirectory(prefix='obs_object_') as tmp_dir:
            client = LocalObjectClient(
                root_path=Path(tmp_dir) / 'objects',
                metadata_db_path=Path(tmp_dir) / 'objects_meta.sqlite3',
                cleanup_interval=1,
            )
            client.start()
            try:
                created = await client.put_bytes(
                    b'hello obs',
                    object_name='docs/hello.txt',
                    metadata={'topic': 'demo'},
                    content_type='text/plain',
                )
                self.assertIsInstance(created, OBS_Object)
                self.assertEqual(created.get('path'), 'docs/hello.txt')

                results = [item async for item in client.search(name='hello', path_prefix='docs/')]
                self.assertEqual(len(results), 1)
                self.assertIsInstance(results[0], OBS_Object)
                self.assertEqual(results[0].get('metadata'), {'topic': 'demo'})
                self.assertEqual(await results[0].get(), b'hello obs')
                self.assertEqual(await results[0].get_text(), 'hello obs')
            finally:
                client.close()