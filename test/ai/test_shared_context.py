import os
import sys
import time
import unittest

from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.ai.shared import AIServiceSharedContext, ConcurrentPool


class _FakeKVClient:

    def __init__(self):
        self.store: dict[str, object] = {}
        self.fail = False

    async def set(self, key: str, value: object, *, expire=None) -> None:
        if self.fail:
            raise RuntimeError('kv unavailable')
        self.store[key] = value

    async def get(self, key: str, default=None, *, target_type=None):
        if self.fail:
            raise RuntimeError('kv unavailable')
        return self.store.get(key, default)

    async def delete(self, key: str) -> bool:
        if self.fail:
            raise RuntimeError('kv unavailable')
        return self.store.pop(key, None) is not None

    async def keys(self, prefix: str | None = None) -> list[str]:
        if self.fail:
            raise RuntimeError('kv unavailable')
        keys = sorted(self.store.keys())
        if prefix is None:
            return keys
        return [key for key in keys if key.startswith(prefix)]


class _FakeKVSection:

    def __init__(self, *, named: dict[str, _FakeKVClient] | None = None, default: _FakeKVClient | None = None):
        self.named = named or {}
        self.default = default or _FakeKVClient()
        self.calls: list[tuple[str, str, bool]] = []

    def get_client(self, name: str = 'default', fallback: str = 'default', *, fuzzy: bool = True):
        self.calls.append((name, fallback, fuzzy))
        if name in self.named:
            return self.named[name]
        if fallback == 'default':
            return self.default
        raise ValueError('missing KV client')


class _FakeStorageConfig:

    def __init__(self, kv_section: _FakeKVSection):
        self.kv = kv_section

    def get_kv_client(self, name: str = 'default', fallback: str = 'default'):
        return self.kv.get_client(name, fallback)


class TestAIServiceSharedContext(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        self._had_singleton = '__singleton__' in AIServiceSharedContext.__dict__
        self._orig_singleton = AIServiceSharedContext.__dict__.get('__singleton__')
        if self._had_singleton:
            delattr(AIServiceSharedContext, '__singleton__')

    def tearDown(self) -> None:
        if '__singleton__' in AIServiceSharedContext.__dict__:
            delattr(AIServiceSharedContext, '__singleton__')
        if self._had_singleton:
            AIServiceSharedContext.__singleton__ = self._orig_singleton  # type: ignore[attr-defined]

    async def test_named_ai_services_context_client_is_preferred(self):
        named_client = _FakeKVClient()
        default_client = _FakeKVClient()
        storage_cfg = _FakeStorageConfig(_FakeKVSection(named={'ai_services_context': named_client}, default=default_client))

        with patch('core.storage.config.StorageConfig.Global', return_value=storage_cfg):
            ctx = AIServiceSharedContext('ai_services')
            await ctx.update_client_status('client-a', {'score': 0.75})

        self.assertTrue(any(key.startswith('ai_services_context:client_status:client-a:') for key in named_client.store))
        self.assertFalse(default_client.store)
        self.assertEqual(storage_cfg.kv.calls[0], ('ai_services_context', 'default', True))

    async def test_default_kv_client_is_used_when_named_client_missing(self):
        default_client = _FakeKVClient()
        storage_cfg = _FakeStorageConfig(_FakeKVSection(default=default_client))

        with patch('core.storage.config.StorageConfig.Global', return_value=storage_cfg):
            ctx = AIServiceSharedContext('ai_services')
            await ctx.update_client_status('client-a', {'score': 0.5})

        self.assertTrue(any(key.startswith('ai_services_context:client_status:client-a:') for key in default_client.store))
        self.assertEqual(storage_cfg.kv.calls[0], ('ai_services_context', 'default', True))

    async def test_in_memory_fallback_flushes_back_to_kv_after_recovery(self):
        kv_client = _FakeKVClient()
        storage_cfg = _FakeStorageConfig(_FakeKVSection(named={'ai_services_context': kv_client}, default=kv_client))

        with patch('core.storage.config.StorageConfig.Global', return_value=storage_cfg):
            ctx = AIServiceSharedContext('ai_services')
            kv_client.fail = True
            self.assertEqual(await ctx.acquire('completion', 'client-a'), 1)
            self.assertEqual(await ctx.get_count('completion', 'client-a'), 1)
            self.assertFalse(kv_client.store)

            kv_client.fail = False
            self.assertEqual(await ctx.get_count('completion', 'client-a'), 1)

            stored_keys = [key for key in kv_client.store if ':concurrent_pool:completion:' in key]
            self.assertEqual(len(stored_keys), 1)
            self.assertEqual(kv_client.store[stored_keys[0]]['counts']['client-a'], 1)  # type: ignore[index]

            self.assertEqual(await ctx.release('completion', 'client-a'), 0)
            self.assertFalse(any(':concurrent_pool:completion:' in key for key in kv_client.store))

    async def test_stale_remote_records_are_ignored(self):
        kv_client = _FakeKVClient()
        storage_cfg = _FakeStorageConfig(_FakeKVSection(named={'ai_services_context': kv_client}, default=kv_client))

        with patch('core.storage.config.StorageConfig.Global', return_value=storage_cfg):
            ctx = AIServiceSharedContext('ai_services')
            now = time.time()
            stale_pool_key = f'{ctx._KV_PREFIX}:concurrent_pool:completion:remote-stale'
            fresh_pool_key = f'{ctx._KV_PREFIX}:concurrent_pool:completion:remote-fresh'
            kv_client.store[stale_pool_key] = {
                'instance_id': 'remote-stale',
                'updated_at': now - ctx._CONCURRENT_RECORD_STALE_AFTER - 1,
                'counts': {'client-a': 9},
            }
            kv_client.store[fresh_pool_key] = {
                'instance_id': 'remote-fresh',
                'updated_at': now,
                'counts': {'client-a': 2},
            }

            stale_status_key = f'{ctx._KV_PREFIX}:client_status:hash-a:remote-stale'
            fresh_status_key = f'{ctx._KV_PREFIX}:client_status:hash-a:remote-fresh'
            kv_client.store[stale_status_key] = {
                'instance_id': 'remote-stale',
                '_updated_at': now - ctx._STATUS_RECORD_STALE_AFTER - 1,
                'score': 0.1,
            }
            kv_client.store[fresh_status_key] = {
                'instance_id': 'remote-fresh',
                '_updated_at': now,
                'score': 0.9,
            }

            self.assertEqual(await ctx.get_count('completion', 'client-a'), 2)
            self.assertTrue(await ctx.is_client_status_fresh('hash-a', max_age=30.0))
            self.assertEqual((await ctx.get_client_status('hash-a'))['score'], 0.9)  # type: ignore[index]
            self.assertNotIn(stale_pool_key, kv_client.store)
            self.assertNotIn(stale_status_key, kv_client.store)

    async def test_concurrent_pool_degrades_to_local_memory_when_kv_is_down(self):
        kv_client = _FakeKVClient()
        storage_cfg = _FakeStorageConfig(_FakeKVSection(named={'ai_services_context': kv_client}, default=kv_client))

        with patch('core.storage.config.StorageConfig.Global', return_value=storage_cfg):
            ctx = AIServiceSharedContext('ai_services')
            AIServiceSharedContext.__singleton__ = ctx  # type: ignore[attr-defined]
            kv_client.fail = True

            pool = ConcurrentPool('completion', 1)
            self.assertTrue(await pool.can_accept('client-a'))
            await pool.acquire('client-a')
            self.assertFalse(await pool.can_accept('client-a'))
            await pool.release('client-a')
            self.assertTrue(await pool.can_accept('client-a'))


if __name__ == '__main__':
    unittest.main()