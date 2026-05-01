import asyncio
import os
import sys
import unittest
import aiohttp
import requests

from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.ai.base import _create_proxied_thinkthinksyn, _patch_thinkthinksyn_proxy
from core.ai.completion import CompletionClient, CompletionService
from core.ai.embedding import ThinkThinkSynEmbeddingClient
from core.ai.t2s import ThinkThinkSynT2SClient
from core.utils.network_utils import proxy_requests as _proxy_mod
from thinkthinksyn import ThinkThinkSyn


class _FakeResponse:

    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self._payload


class _FakeSession:

    calls: list[tuple[str, dict[str, object]]] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def close(self):
        self.closed = True

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse({'data': [{'embedding': [1.0, 2.0]}]})


async def _fake_sse(url, **kwargs):
    _fake_sse.calls.append((url, kwargs))

    class _Event:
        event = 'message'
        data = '{"audio": "ZmFrZQ=="}'

    yield _Event()


_fake_sse.calls = []


class TestThinkThinkSynProxyClient(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        _FakeSession.calls.clear()
        _fake_sse.calls.clear()

    async def test_proxied_client_routes_http_and_sse_via_proxy_wrappers(self):
        with patch('core.utils.network_utils.proxy_requests.aiohttp_client_session', _FakeSession), \
             patch('core.utils.network_utils.proxy_requests.aiosseclient_with_proxy', _fake_sse):
            client = _create_proxied_thinkthinksyn(base_url='https://api.example.com/tts/ai', apikey='token')
            embedding_client = ThinkThinkSynEmbeddingClient(client)

            result = await embedding_client._embedding_impl(['hello'])
            self.assertEqual(result, [[1.0, 2.0]])
            self.assertEqual(len(_FakeSession.calls), 1)
            url, kwargs = _FakeSession.calls[0]
            self.assertIn('/embedding/', url)
            self.assertEqual(kwargs['headers'], {'Authorization': 'Bearer token'})
            self.assertFalse(bool(kwargs['json']['stream']))

            first = None
            async for event in client._stream_request_ai('/t2s/model', {'text': 'hello'}):
                first = event
                break

            self.assertIsNotNone(first)
            self.assertEqual(len(_fake_sse.calls), 1)
            sse_url, sse_kwargs = _fake_sse.calls[0]
            self.assertIn('/t2s/model', sse_url)
            self.assertEqual(sse_kwargs['headers'], {'Authorization': 'Bearer token'})
            self.assertTrue(bool(sse_kwargs['json']['stream']))

    async def test_patch_thinkthinksyn_proxy_keeps_same_instance(self):
        with patch('core.utils.network_utils.proxy_requests.aiohttp_client_session', _FakeSession):
            client = ThinkThinkSyn(base_url='https://api.example.com/tts/ai', apikey='token')
            original_type = type(client)

            patched = _patch_thinkthinksyn_proxy(client)

            self.assertIs(patched, client)
            self.assertIsNot(type(client), original_type)
            self.assertIs(patched, _patch_thinkthinksyn_proxy(client))

            embedding_client = ThinkThinkSynEmbeddingClient(client)
            self.assertIs(embedding_client._tts_client, client)
            result = await embedding_client._embedding_impl(['hello'])

            self.assertEqual(result, [[1.0, 2.0]])
            self.assertEqual(len(_FakeSession.calls), 1)

    async def test_embedding_client_uses_alias_for_slash_model_name(self):
        with patch('core.utils.network_utils.proxy_requests.aiohttp_client_session', _FakeSession):
            client = _create_proxied_thinkthinksyn(base_url='https://api.example.com/tts/ai', apikey='token')
            embedding_client = ThinkThinkSynEmbeddingClient(
                client,
                model='iampanda/zpoint_large_embedding_zh',
            )

            await embedding_client._embedding_impl(['hello'])

            self.assertEqual(len(_FakeSession.calls), 1)
            url, _kwargs = _FakeSession.calls[0]
            self.assertIn('/embedding/zpoint', url)
            self.assertNotIn('/embedding/iampanda/zpoint_large_embedding_zh', url)

    def test_t2s_constructor_patches_raw_thinkthinksyn_instance(self):
        client = ThinkThinkSyn(base_url='https://api.example.com/tts/ai', apikey='token')
        original_type = type(client)

        t2s_client = ThinkThinkSynT2SClient(client)

        self.assertIs(t2s_client._tts_client, client)
        self.assertIsNot(type(client), original_type)

    def test_completion_factory_uses_proxied_thinkthinksyn_instance(self):
        client = CompletionClient.CreateThinkThinkSynClient(apikey='token')

        self.assertIsInstance(client._tts_client, ThinkThinkSyn)
        self.assertIsNot(type(client._tts_client), ThinkThinkSyn)


class TestPrivateSubnetProxyRouting(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        _proxy_mod._private_subnet_proxy_modes.clear()
        _proxy_mod._cached_proxy = None
        _proxy_mod._cache_ts = 0.0

    async def test_aiohttp_private_subnet_learns_direct_on_direct_response(self):
        calls: list[dict[str, object]] = []

        async def _fake_request(self, method, str_or_url, **kwargs):
            calls.append(kwargs.copy())
            return object()

        with patch.object(aiohttp.ClientSession, '_request', new=_fake_request), \
             patch('core.utils.network_utils.proxy_requests.get_proxy_url', return_value='http://127.0.0.1:7890'):
            async with _proxy_mod.aiohttp_client_session() as session:
                await session._request('GET', 'http://192.168.50.10/ping')
                await session._request('GET', 'http://192.168.50.99/ping')

        self.assertEqual(len(calls), 2)
        self.assertNotIn('proxy', calls[0])
        self.assertNotIn('proxy', calls[1])
        self.assertFalse(_proxy_mod._private_subnet_proxy_modes['192.168.50.0/24'])

    async def test_aiohttp_private_subnet_learns_proxy_after_direct_failure(self):
        calls: list[dict[str, object]] = []

        async def _fake_request(self, method, str_or_url, **kwargs):
            calls.append(kwargs.copy())
            if 'proxy' not in kwargs:
                raise OSError('direct-unreachable')
            return object()

        with patch.object(aiohttp.ClientSession, '_request', new=_fake_request), \
             patch('core.utils.network_utils.proxy_requests.get_proxy_url', return_value='http://127.0.0.1:7890'), \
             patch('core.utils.network_utils.proxy_requests._can_reach_target_direct', return_value=False):
            async with _proxy_mod.aiohttp_client_session() as session:
                await session._request('GET', 'http://192.168.60.10/ping')
                calls.clear()
                await session._request('GET', 'http://192.168.60.20/ping')

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['proxy'], 'http://127.0.0.1:7890')
        self.assertTrue(_proxy_mod._private_subnet_proxy_modes['192.168.60.0/24'])

    async def test_aiohttp_private_subnet_same_failure_marks_direct(self):
        async def _fake_request(self, method, str_or_url, **kwargs):
            raise OSError('network-down')

        with patch.object(aiohttp.ClientSession, '_request', new=_fake_request), \
             patch('core.utils.network_utils.proxy_requests.get_proxy_url', return_value='http://127.0.0.1:7890'), \
             patch('core.utils.network_utils.proxy_requests._can_reach_target_direct', return_value=False):
            async with _proxy_mod.aiohttp_client_session() as session:
                with self.assertRaises(OSError):
                    await session._request('GET', 'http://10.20.30.40/ping')

        self.assertFalse(_proxy_mod._private_subnet_proxy_modes['10.20.30.0/24'])

    async def test_aiohttp_private_subnet_marks_direct_when_tcp_is_reachable(self):
        calls: list[dict[str, object]] = []

        async def _fake_request(self, method, str_or_url, **kwargs):
            calls.append(kwargs.copy())
            raise OSError('tls-handshake-failed')

        with patch.object(aiohttp.ClientSession, '_request', new=_fake_request), \
             patch('core.utils.network_utils.proxy_requests.get_proxy_url', return_value='http://127.0.0.1:7890'), \
             patch('core.utils.network_utils.proxy_requests._can_reach_target_direct', return_value=True):
            async with _proxy_mod.aiohttp_client_session() as session:
                with self.assertRaises(OSError):
                    await session._request('GET', 'https://192.168.80.10/ping')

        self.assertEqual(len(calls), 1)
        self.assertNotIn('proxy', calls[0])
        self.assertFalse(_proxy_mod._private_subnet_proxy_modes['192.168.80.0/24'])

    async def test_aiohttp_auto_injected_proxy_connectivity_failure_falls_back_to_direct(self):
        calls: list[dict[str, object]] = []

        async def _fake_request(self, method, str_or_url, **kwargs):
            calls.append(kwargs.copy())
            if kwargs.get('proxy'):
                raise OSError('proxy-route-connect-failed')
            return object()

        with patch.object(aiohttp.ClientSession, '_request', new=_fake_request), \
             patch('core.utils.network_utils.proxy_requests.get_proxy_url', return_value='http://127.0.0.1:7890'), \
             patch('core.utils.network_utils.proxy_requests.report_proxy_failure') as mock_report:
            async with _proxy_mod.aiohttp_client_session() as session:
                result = await session._request('GET', 'https://api.thinkthinksyn.com/tts/ai/embedding/zpoint')

        self.assertIsNotNone(result)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].get('proxy'), 'http://127.0.0.1:7890')
        self.assertNotIn('proxy', calls[1])
        mock_report.assert_called_once()


class TestPrivateSubnetProxyRoutingRequests(unittest.TestCase):

    def setUp(self) -> None:
        _proxy_mod._private_subnet_proxy_modes.clear()
        _proxy_mod._cached_proxy = None
        _proxy_mod._cache_ts = 0.0

    def test_requests_private_subnet_learns_proxy_and_reuses_same_subnet(self):
        calls: list[dict[str, object]] = []
        response = object()

        def _fake_request(method, url, **kwargs):
            calls.append(kwargs.copy())
            if 'proxies' not in kwargs:
                raise requests.exceptions.ConnectionError('direct-unreachable')
            return response

        with patch('requests.request', side_effect=_fake_request), \
             patch('core.utils.network_utils.proxy_requests.get_proxy_url', return_value='http://127.0.0.1:7890'), \
             patch('core.utils.network_utils.proxy_requests._can_reach_target_direct', return_value=False):
            first = _proxy_mod.requests_get('http://192.168.70.10/ping')
            calls.clear()
            second = _proxy_mod.requests_get('http://192.168.70.88/ping')

        self.assertIs(first, response)
        self.assertIs(second, response)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['proxies'], {'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'})
        self.assertTrue(_proxy_mod._private_subnet_proxy_modes['192.168.70.0/24'])

    def test_requests_private_subnet_same_failure_marks_direct(self):
        def _fake_request(method, url, **kwargs):
            raise requests.exceptions.ConnectionError('network-down')

        with patch('requests.request', side_effect=_fake_request), \
             patch('core.utils.network_utils.proxy_requests.get_proxy_url', return_value='http://127.0.0.1:7890'), \
             patch('core.utils.network_utils.proxy_requests._can_reach_target_direct', return_value=False):
            with self.assertRaises(requests.exceptions.ConnectionError):
                _proxy_mod.requests_get('http://172.16.8.9/ping')

        self.assertFalse(_proxy_mod._private_subnet_proxy_modes['172.16.8.0/24'])


if __name__ == '__main__':
    unittest.main()