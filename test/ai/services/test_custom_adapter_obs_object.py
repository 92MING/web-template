import tempfile
import unittest

from pathlib import Path

from core.ai.config import AIServicesConfig
from core.ai.completion import CompletionClient
from core.storage.object import LocalObjectClient, OBS_Object


class TestCustomAdapterOBSObject(unittest.IsolatedAsyncioTestCase):
    async def test_custom_client_accepts_obs_object_adapter_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix='custom_adapter_obs_', ignore_cleanup_errors=True) as tmp_dir:
            object_client = LocalObjectClient(
                root_path=Path(tmp_dir) / 'objects',
                metadata_db_path=Path(tmp_dir) / 'objects_meta.sqlite3',
                cleanup_interval=1,
            )
            object_client.start()
            try:
                adapter_source = await object_client.put_bytes(
                    """
from typing import Any

class OBSCompletionAdapter:
    def __init__(self, max_tokens: int = 4096, max_images: int = 0, max_audios: int = 0, max_videos: int = 0):
        self.max_tokens = max_tokens
        self.max_images = max_images
        self.max_audios = max_audios
        self.max_videos = max_videos

    async def stream_complete(self, **kwargs: Any):
        yield {'data': 'obs adapter ok', 'type': 'text'}
""".strip().encode('utf-8'),
                    object_name='adapters/obs_completion_adapter.py',
                    content_type='text/x-python',
                )
                self.assertIsInstance(adapter_source, OBS_Object)

                cfg = AIServicesConfig.model_validate({
                    'completion': {
                        'clients': {
                            'obs-custom': {
                                'type': 'custom',
                                'adapter': adapter_source,
                                'max_tokens': 256,
                            },
                        },
                        'service': {'default': {'clients': ['obs-custom']}},
                    },
                })

                client = cfg.completion.clients['obs-custom'].get_client(service_kind='completion')
                self.assertIsInstance(client, CompletionClient)
                text = await client.complete(__skip_log__=True, messages=[{'role': 'user', 'content': 'ping'}])
                self.assertEqual(text, 'obs adapter ok')
                client.close()
            finally:
                object_client.close()