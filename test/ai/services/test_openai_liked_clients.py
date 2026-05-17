# -*- coding: utf-8 -*-
"""Regression tests for OpenAI-compatible AI clients."""

import base64
import io
import struct
import unittest
import wave
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

import core.ai.base as ai_base
from core.ai.base import _CLIENT_TYPE_REGISTRY
from core.ai.completion import CompletionClient, CompletionService, OpenAILikedCompletionClient, OpenRouterCompletionClient
from core.ai.embedding import EmbeddingClient, EmbeddingService, OpenAILikedEmbeddingClient, OpenRouterEmbeddingClient, _decode_base64_embedding
from core.ai.s2t import OpenAILikedS2TClient, OpenRouterS2TClient, S2TClient, S2TService
from core.ai.t2s import OpenAILikedT2SClient, OpenRouterT2SClient, T2SClient
from core.ai.t2img import OpenAILikedT2ImgClient, OpenRouterT2ImgClient, T2ImgClient
from core.utils.data_structs import Audio, Image


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\x00\x00' * 160)
    return buffer.getvalue()


def _png_bytes() -> bytes:
    return base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII='
    )


def _json_context_session(response_data: object, *, content_type: str = 'application/json') -> MagicMock:
    response = MagicMock()
    response.headers = {'Content-Type': content_type}
    response.json = AsyncMock(return_value=response_data)
    response.text = AsyncMock(return_value=str(response_data))
    response.raise_for_status = MagicMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = MagicMock(return_value=cm)
    return session


def _response_context(response: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestOpenAILikedCompletionClient(unittest.TestCase):
    def test_openai_headers_do_not_include_openrouter_metadata(self) -> None:
        client = OpenAILikedCompletionClient(apikey='openai-key', base_url='https://api.openai.com/v1')

        with patch.dict('os.environ', {
            'OPENROUTER_HTTP_REFERER': 'https://example.test',
            'OPENROUTER_X_TITLE': 'Example',
        }, clear=False):
            headers = client._headers()

        self.assertEqual(headers['Authorization'], 'Bearer openai-key')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertNotIn('HTTP-Referer', headers)
        self.assertNotIn('X-Title', headers)

    def test_openrouter_completion_subclass_adds_openrouter_metadata(self) -> None:
        client = OpenRouterCompletionClient(apikey='router-key', base_url='https://openrouter.ai/api/v1')

        with patch.dict('os.environ', {
            'OPENROUTER_HTTP_REFERER': 'https://example.test',
            'OPENROUTER_X_TITLE': 'Example',
        }, clear=False):
            headers = client._headers()

        self.assertEqual(headers['Authorization'], 'Bearer router-key')
        self.assertEqual(headers['HTTP-Referer'], 'https://example.test')
        self.assertEqual(headers['X-Title'], 'Example')

    def test_openrouter_completion_factory_uses_specialized_client(self) -> None:
        client = CompletionClient.CreateOpenRouterClient(apikey='router-key')

        self.assertIsInstance(client, OpenRouterCompletionClient)

    def test_openrouter_direct_constructors_use_default_base_url(self) -> None:
        clients = [
            OpenRouterCompletionClient(apikey='router-key'),
            OpenRouterEmbeddingClient(apikey='router-key'),
            OpenRouterS2TClient(apikey='router-key'),
            OpenRouterT2SClient(apikey='router-key'),
            OpenRouterT2ImgClient(apikey='router-key'),
        ]

        for client in clients:
            self.assertEqual(client._base_url, 'https://openrouter.ai/api/v1')

    def test_openai_completion_client_applies_custom_headers(self) -> None:
        client = OpenAILikedCompletionClient(
            apikey='kimi-key',
            base_url='https://api.kimi.com/coding/v1',
            extra_headers={'User-Agent': 'claude-code/1.0.0'},
        )

        headers = client._headers()

        self.assertEqual(headers['Authorization'], 'Bearer kimi-key')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(headers['User-Agent'], 'claude-code/1.0.0')
        self.assertNotIn('HTTP-Referer', headers)
        self.assertNotIn('X-Title', headers)

    def test_all_openai_liked_factories_forward_ssh_tunnel(self) -> None:
        tunneled_url = 'http://127.0.0.1:19000/v1'
        with patch.object(ai_base, '_rewrite_url_for_ssh_tunnel', return_value=tunneled_url) as rewrite_url:
            clients = [
                CompletionClient.CreateOpenAILikedClient(apikey='openai-key', base_url='https://completion.test/v1', ssh_tunnel='box'),
                CompletionClient.CreateOpenRouterClient(apikey='router-key', base_url='https://router-completion.test/v1', ssh_tunnel='box'),
                EmbeddingClient.CreateOpenAILikedEmbeddingClient(apikey='openai-key', base_url='https://embedding.test/v1', ssh_tunnel='box'),
                EmbeddingClient.CreateOpenRouterEmbeddingClient(apikey='router-key', base_url='https://router-embedding.test/v1', ssh_tunnel='box'),
                S2TClient.CreateOpenAILikedS2TClient(apikey='openai-key', base_url='https://s2t.test/v1', ssh_tunnel='box'),
                S2TClient.CreateOpenRouterS2TClient(apikey='router-key', base_url='https://router-s2t.test/v1', ssh_tunnel='box'),
                T2SClient.CreateOpenAILikedT2SClient(apikey='openai-key', base_url='https://t2s.test/v1', ssh_tunnel='box'),
                T2SClient.CreateOpenRouterT2SClient(apikey='router-key', base_url='https://router-t2s.test/v1', ssh_tunnel='box'),
                T2ImgClient.CreateOpenAILikedT2ImgClient(apikey='openai-key', base_url='https://t2img.test/v1', ssh_tunnel='box'),
                T2ImgClient.CreateOpenRouterT2ImgClient(apikey='router-key', base_url='https://router-t2img.test/v1', ssh_tunnel='box'),
            ]

        self.assertEqual(rewrite_url.call_count, len(clients))
        for client in clients:
            self.assertEqual(client._base_url, tunneled_url)

    def test_ssh_tunnel_uses_base_url_host_as_remote_bind_host(self) -> None:
        opened: list[object] = []

        class DummyTunnel:
            remote_ip = '127.0.0.1'

            def open_tunnel(self, remote_port: int) -> int:
                opened.append((self.remote_ip, remote_port))
                return 19001

        rewritten = ai_base._rewrite_url_for_ssh_tunnel('http://localhost:9391/v1', DummyTunnel())

        self.assertEqual(opened, [('localhost', 9391)])
        self.assertEqual(rewritten, 'http://127.0.0.1:19001/v1')

    def test_openai_liked_factories_allow_self_hosted_without_apikey(self) -> None:
        clients = [
            CompletionClient.CreateOpenAILikedClient(base_url='http://localhost:9391'),
            EmbeddingClient.CreateOpenAILikedEmbeddingClient(base_url='http://localhost:9391'),
            S2TClient.CreateOpenAILikedS2TClient(base_url='http://localhost:9391'),
            T2SClient.CreateOpenAILikedT2SClient(base_url='http://localhost:9391'),
            T2ImgClient.CreateOpenAILikedT2ImgClient(base_url='http://localhost:9391'),
        ]

        for client in clients:
            self.assertEqual(client._apikey, '')
            self.assertEqual(client._base_url, 'http://localhost:9391')
            self.assertNotIn('Authorization', client._openai_liked_headers())

    def test_openai_liked_factory_still_requires_apikey_for_default_endpoint(self) -> None:
        with patch.dict('os.environ', {
            'OPENAI_APIKEY': '',
            'OPENAI_API_KEY': '',
            'OPENAI_API_URL': '',
            'OPENAI_BASE_URL': '',
        }, clear=False):
            with self.assertRaises(ValueError):
                CompletionClient.CreateOpenAILikedClient()

    def test_failed_openai_liked_init_does_not_leave_partial_cached_client(self) -> None:
        with patch.object(ai_base, '_rewrite_url_for_ssh_tunnel', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                OpenAILikedCompletionClient(apikey=None, base_url='http://self-hosted.test/v1', ssh_tunnel='box', key='partial-cache-test')

        client = OpenAILikedCompletionClient(apikey=None, base_url='http://self-hosted.test/v1', key='partial-cache-test')
        self.assertEqual(client._base_url, 'http://self-hosted.test/v1')
        self.assertIsNone(client._model)

    def test_root_base_url_has_v1_endpoint_fallback(self) -> None:
        client = OpenAILikedCompletionClient(apikey=None, base_url='http://self-hosted.test')

        self.assertEqual(
            client._completion_urls(),
            [
                'http://self-hosted.test/chat/completions',
                'http://self-hosted.test/v1/chat/completions',
            ],
        )


class TestOpenAILikedCompletionClientAsync(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        _CLIENT_TYPE_REGISTRY.pop(('completion', 'dummynoaudiocompletionclient'), None)
        _CLIENT_TYPE_REGISTRY.pop(('completion', 'dummynoaudiocompletionserviceclient'), None)

    async def test_no_audio_completion_client_uses_default_s2t_fallback(self) -> None:
        class DummyNoAudioCompletionClient(CompletionClient, type='dummy-no-audio-completion-client'):
            def __init__(self):
                super().__init__(max_audios=0)
                self.seen_messages = None

            async def _complete_impl(self, **kwargs):
                self.seen_messages = kwargs['messages']
                return 'ok'

        class FakeS2TService:
            def __init__(self):
                self.calls = []

            async def s2t(self, audio, **kwargs):
                self.calls.append((audio, kwargs))
                return 'This is a test.'

        client = DummyNoAudioCompletionClient()
        fake_s2t = FakeS2TService()

        with patch.object(S2TService, 'Default', return_value=fake_s2t):
            result = await client.complete(messages=[{'role': 'user', 'content': ['Audio says: ', Audio(_wav_bytes())]}])

        self.assertEqual(result, 'ok')
        self.assertEqual(len(fake_s2t.calls), 1)
        self.assertEqual(client.seen_messages, [{'role': 'user', 'content': ['Audio says: ', 'This is a test.']}])

    async def test_no_audio_completion_service_uses_configured_s2t_fallback(self) -> None:
        class DummyNoAudioCompletionClient(CompletionClient, type='dummy-no-audio-completion-service-client'):
            def __init__(self):
                super().__init__(max_audios=0)
                self.seen_messages = None

            async def _complete_impl(self, **kwargs):
                self.seen_messages = kwargs['messages']
                return 'service ok'

        class FakeS2TService:
            async def s2t(self, audio, **kwargs):
                return 'configured transcript'

        client = DummyNoAudioCompletionClient()
        service = CompletionService(client, s2t_service=FakeS2TService(), key='dummy-no-audio-completion-service')
        self.addCleanup(service.close)

        result = await service.complete(messages=[{'role': 'user', 'content': ['Audio says: ', Audio(_wav_bytes())]}])

        self.assertEqual(result, 'service ok')
        self.assertEqual(client.seen_messages, [{'role': 'user', 'content': ['Audio says: ', 'configured transcript']}])

    async def test_deepseek_disables_thinking_when_reasoning_false(self) -> None:
        client = OpenAILikedCompletionClient(apikey='deepseek-key', base_url='https://api.deepseek.com/v1', model='deepseek-v4-pro')

        payload = await client._build_payload(
            {
                'messages': [{'role': 'user', 'content': 'Reply OK'}],
                'max_tokens': 4,
                'reasoning': False,
            },
            stream=False,
        )

        self.assertEqual(payload['reasoning'], {'enabled': False})
        self.assertEqual(payload['thinking'], {'type': 'disabled'})

    async def test_regular_openai_liked_does_not_add_thinking_payload(self) -> None:
        client = OpenAILikedCompletionClient(apikey='test-key', base_url='https://example.test/v1', model='model')

        payload = await client._build_payload(
            {
                'messages': [{'role': 'user', 'content': 'Reply OK'}],
                'max_tokens': 4,
                'reasoning': False,
            },
            stream=False,
        )

        self.assertNotIn('thinking', payload)

    async def test_micu_gpt_uses_anthropic_image_part(self) -> None:
        client = OpenAILikedCompletionClient(apikey='micu-key', base_url='https://www.micuapi.ai/v1', model='gpt-5.4', max_images=1)

        payload = await client._build_payload(
            {
                'messages': [{
                    'role': 'user',
                    'content': ['What logo?', Image(_png_bytes())],
                }],
                'max_tokens': 4,
                'reasoning': False,
            },
            stream=False,
        )

        image_part = payload['messages'][0]['content'][1]
        self.assertEqual(image_part['type'], 'image')
        self.assertEqual(image_part['source']['type'], 'base64')
        self.assertEqual(image_part['source']['media_type'], 'image/png')
        self.assertIsInstance(image_part['source']['data'], str)

    def test_micu_qwen_does_not_advertise_image_support(self) -> None:
        client = OpenAILikedCompletionClient(apikey='micu-key', base_url='https://www.micuapi.ai/v1', model='qwen3.6-plus', max_images=16)

        self.assertEqual(client.max_images, 0)

    async def test_completion_retries_v1_endpoint_after_root_404(self) -> None:
        client = OpenAILikedCompletionClient(apikey=None, base_url='http://self-hosted.test')
        not_found = MagicMock()
        not_found.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=404,
            message='Not Found',
        ))
        success = MagicMock()
        success.raise_for_status = MagicMock()
        success.json = AsyncMock(return_value={
            'choices': [{'message': {'content': 'OK'}}],
        })
        session = MagicMock()
        session.post = MagicMock(side_effect=[_response_context(not_found), _response_context(success)])

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client._complete_impl(
                messages=[{'role': 'user', 'content': 'Reply OK'}],
                max_tokens=4,
                reasoning=False,
                stream=False,
            )

        self.assertEqual(result, 'OK')
        self.assertEqual(session.post.call_args_list[0].args[0], 'http://self-hosted.test/chat/completions')
        self.assertEqual(session.post.call_args_list[1].args[0], 'http://self-hosted.test/v1/chat/completions')


class TestOpenAILikedEmbeddingClient(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        _CLIENT_TYPE_REGISTRY.pop(('embedding', 'dummyopenailikedtest'), None)

    def test_decode_base64_embedding_round_trips_float32(self) -> None:
        original = [0.1, -0.2, 0.3]
        encoded = base64.b64encode(struct.pack('3f', *original)).decode('ascii')

        decoded = _decode_base64_embedding(encoded)

        for actual, expected in zip(decoded, original):
            self.assertAlmostEqual(actual, expected, places=5)

    def test_embedding_url_handles_trailing_slash_base_url(self) -> None:
        client = OpenAILikedEmbeddingClient(apikey='test-key', base_url='https://api.openai.com/v1/')

        self.assertEqual(client._embedding_url(), 'https://api.openai.com/v1/embeddings')

    async def test_embedding_raw_forwards_openai_payload_fields(self) -> None:
        client = OpenAILikedEmbeddingClient(apikey='test-key', base_url='https://api.openai.com/v1')
        session = _json_context_session({
            'object': 'list',
            'data': [{'object': 'embedding', 'embedding': [0.1, 0.2], 'index': 0}],
            'model': 'text-embedding-3-small',
            'usage': {'prompt_tokens': 2, 'total_tokens': 2},
        })

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.embedding_raw(
                ['hello'],
                model='text-embedding-3-small',
                encoding_format='float',
                dimensions=128,
                user='user-1',
            )

        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['input'], 'hello')
        self.assertEqual(payload['model'], 'text-embedding-3-small')
        self.assertEqual(payload['encoding_format'], 'float')
        self.assertEqual(payload['dimensions'], 128)
        self.assertEqual(payload['user'], 'user-1')
        self.assertEqual(result['data'][0]['embedding'], [0.1, 0.2])

    async def test_embedding_raw_preserves_token_array_shape(self) -> None:
        client = OpenAILikedEmbeddingClient(apikey='test-key', base_url='https://api.openai.com/v1')
        session = _json_context_session({
            'object': 'list',
            'data': [{'object': 'embedding', 'embedding': [0.5], 'index': 0}],
            'usage': {'prompt_tokens': 3, 'total_tokens': 3},
        })

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            await client.embedding_raw([[101, 202, 303]])

        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['input'], [101, 202, 303])

    async def test_embedding_raw_preserves_batch_token_array_shape(self) -> None:
        client = OpenAILikedEmbeddingClient(apikey='test-key', base_url='https://api.openai.com/v1')
        session = _json_context_session({
            'object': 'list',
            'data': [
                {'object': 'embedding', 'embedding': [0.1], 'index': 0},
                {'object': 'embedding', 'embedding': [0.2], 'index': 1},
            ],
            'usage': {'prompt_tokens': 4, 'total_tokens': 4},
        })

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            await client.embedding_raw([[1, 2], [3, 4]])

        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['input'], [[1, 2], [3, 4]])

    async def test_embedding_impl_decodes_base64_embedding(self) -> None:
        client = OpenAILikedEmbeddingClient(apikey='test-key', base_url='https://api.openai.com/v1')
        expected = [0.1, 0.2, 0.3]
        encoded = base64.b64encode(struct.pack('3f', *expected)).decode('ascii')
        session = _json_context_session({
            'object': 'list',
            'data': [{'object': 'embedding', 'embedding': encoded, 'index': 0}],
            'usage': {'prompt_tokens': 1, 'total_tokens': 1},
        })

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client._embedding_impl(['hello'], encoding_format='base64')

        for actual, expected_value in zip(result[0], expected):
            self.assertAlmostEqual(actual, expected_value, places=5)

    async def test_embedding_raw_retries_on_disconnect_before_response(self) -> None:
        client = OpenAILikedEmbeddingClient(apikey='test-key', base_url='https://api.openai.com/v1')
        ok_response = MagicMock()
        ok_response.json = AsyncMock(return_value={
            'object': 'list',
            'data': [{'object': 'embedding', 'embedding': [0.1], 'index': 0}],
            'usage': {'prompt_tokens': 1, 'total_tokens': 1},
        })
        ok_response.raise_for_status = MagicMock()
        ok_cm = MagicMock()
        ok_cm.__aenter__ = AsyncMock(return_value=ok_response)
        ok_cm.__aexit__ = AsyncMock(return_value=False)
        fail_cm = MagicMock()
        fail_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ServerDisconnectedError())
        fail_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post = MagicMock(side_effect=[fail_cm, ok_cm])

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.embedding_raw(['hello'])

        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(result['data'][0]['embedding'], [0.1])

    async def test_service_embedding_raw_wraps_clients_without_raw_override(self) -> None:
        class DummyEmbeddingClient(EmbeddingClient, type='dummy-openai-liked-test'):
            async def _embedding_impl(self, inputs, **kwargs):
                return [[0.1, 0.2]]

        service = EmbeddingService(DummyEmbeddingClient(), key='dummy-openai-liked-test')

        result = await service.embedding_raw(['hello'])

        self.assertEqual(result['object'], 'list')
        self.assertEqual(result['data'][0]['embedding'], [0.1, 0.2])
        self.assertEqual(result['usage']['prompt_tokens'], 0)

    def test_openrouter_embedding_factory_uses_specialized_client(self) -> None:
        client = EmbeddingClient.CreateOpenRouterEmbeddingClient(apikey='router-key')

        self.assertIsInstance(client, OpenRouterEmbeddingClient)


class TestOpenAILikedS2TClient(unittest.IsolatedAsyncioTestCase):
    def test_s2t_default_model_is_whisper_1(self) -> None:
        client = OpenAILikedS2TClient(apikey='test-key', base_url='https://api.openai.com/v1')

        self.assertEqual(client._model, 'whisper-1')

    async def test_s2t_raw_posts_openai_form_fields(self) -> None:
        client = OpenAILikedS2TClient(apikey='test-key', base_url='https://api.openai.com/v1')
        session = _json_context_session({'text': 'hello', 'usage': {'input_tokens': 5}})

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.s2t_raw(
                Audio(_wav_bytes()),
                model='whisper-1',
                language='en',
                prompt='say it clearly',
                temperature=0.5,
                response_format='json',
            )

        form = session.post.call_args.kwargs['data']
        field_names = {field[0]['name'] for field in form._fields}
        self.assertIn('file', field_names)
        self.assertIn('model', field_names)
        self.assertIn('language', field_names)
        self.assertIn('prompt', field_names)
        self.assertIn('temperature', field_names)
        self.assertEqual(result['text'], 'hello')

    async def test_s2t_raw_accepts_prompt_aliases_and_expected_languages(self) -> None:
        client = OpenAILikedS2TClient(apikey='test-key', base_url='https://api.openai.com/v1')
        session = _json_context_session({'text': 'hello'})

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            await client.s2t_raw(
                Audio(_wav_bytes()),
                asr_prompt='say it clearly',
                expected_languages='EN, zh',
                response_format='json',
            )

        form = session.post.call_args.kwargs['data']
        fields = {field[0]['name']: field[2] for field in form._fields}
        self.assertEqual(fields['prompt'], 'say it clearly')
        self.assertEqual(fields['language'], 'en')

    async def test_s2t_raw_wraps_plain_text_response(self) -> None:
        client = OpenAILikedS2TClient(apikey='test-key', base_url='https://api.openai.com/v1')
        session = _json_context_session('plain text', content_type='text/plain')

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.s2t_raw(Audio(_wav_bytes()), response_format='text')

        self.assertEqual(result['text'], 'plain text')

    async def test_s2t_raw_retries_on_disconnect_before_response(self) -> None:
        client = OpenAILikedS2TClient(apikey='test-key', base_url='https://api.openai.com/v1')
        ok_response = MagicMock()
        ok_response.headers = {'Content-Type': 'application/json'}
        ok_response.json = AsyncMock(return_value={'text': 'hello'})
        ok_response.raise_for_status = MagicMock()
        ok_cm = MagicMock()
        ok_cm.__aenter__ = AsyncMock(return_value=ok_response)
        ok_cm.__aexit__ = AsyncMock(return_value=False)
        fail_cm = MagicMock()
        fail_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ServerDisconnectedError())
        fail_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post = MagicMock(side_effect=[fail_cm, ok_cm])

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.s2t_raw(Audio(_wav_bytes()))

        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(result['text'], 'hello')

    async def test_service_s2t_raw_delegates_to_client(self) -> None:
        client = OpenAILikedS2TClient(apikey='test-key', base_url='https://api.openai.com/v1')
        service = S2TService(client, key='openai-s2t-test')
        session = _json_context_session({'text': 'hello'})

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await service.s2t_raw(Audio(_wav_bytes()))

        self.assertEqual(result['text'], 'hello')

    async def test_openrouter_s2t_raw_posts_json_audio_payload(self) -> None:
        client = OpenRouterS2TClient(apikey='test-key', base_url='https://openrouter.ai/api/v1')
        session = _json_context_session({'text': 'openrouter hello'})

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.s2t_raw(
                Audio(_wav_bytes()),
                model='openai/whisper-1',
                input_format='wav',
                language='en',
                asr_prompt='say it clearly',
                response_format='json',
            )

        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['model'], 'openai/whisper-1')
        self.assertEqual(payload['input_audio']['format'], 'wav')
        self.assertEqual(base64.b64decode(payload['input_audio']['data'])[:4], b'RIFF')
        self.assertEqual(payload['language'], 'en')
        self.assertEqual(payload['prompt'], 'say it clearly')
        self.assertEqual(result['text'], 'openrouter hello')

    async def test_openrouter_s2t_raw_preserves_original_audio_bytes(self) -> None:
        original = b'ID3original-mp3-bytes'
        client = OpenRouterS2TClient(apikey='test-key', base_url='https://openrouter.ai/api/v1')
        session = _json_context_session({'text': 'openrouter hello'})

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            await client.s2t_raw(Audio(original, format='mp3'), model='openai/whisper-1')

        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['input_audio']['format'], 'mp3')
        self.assertEqual(base64.b64decode(payload['input_audio']['data']), original)

    def test_openrouter_s2t_factory_uses_specialized_client(self) -> None:
        client = S2TClient.CreateOpenRouterS2TClient(apikey='test-key', model='openai/whisper-1')

        self.assertIsInstance(client, OpenRouterS2TClient)


class TestOpenAILikedT2SClient(unittest.IsolatedAsyncioTestCase):
    def test_t2s_default_model_is_tts_1(self) -> None:
        client = OpenAILikedT2SClient(apikey='test-key', base_url='https://api.openai.com/v1')

        self.assertEqual(client.model, 'tts-1')

    async def test_t2s_payload_contains_openai_speech_fields(self) -> None:
        client = OpenAILikedT2SClient(apikey='test-key', base_url='https://api.openai.com/v1')
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.read = AsyncMock(return_value=_wav_bytes())
        response.release = MagicMock()
        session = MagicMock()
        session.post = AsyncMock(return_value=response)

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.t2s(
                'hello world',
                model='tts-1',
                voice={'id': 'voice-1'},
                response_format='wav',
                speed=1.2,
                instructions='warm',
                __skip_log__=True,
            )

        payload = session.post.call_args.kwargs['json']
        self.assertIsInstance(result, Audio)
        self.assertEqual(payload['model'], 'tts-1')
        self.assertEqual(payload['input'], 'hello world')
        self.assertEqual(payload['voice'], {'id': 'voice-1'})
        self.assertEqual(payload['response_format'], 'wav')
        self.assertEqual(payload['speed'], 1.2)
        self.assertEqual(payload['instructions'], 'warm')

    async def test_t2s_audio_is_created_from_response_bytes(self) -> None:
        client = OpenAILikedT2SClient(apikey='test-key', base_url='https://api.openai.com/v1')
        audio_bytes = _wav_bytes()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.read = AsyncMock(return_value=audio_bytes)
        response.release = MagicMock()
        session = MagicMock()
        session.post = AsyncMock(return_value=response)

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.t2s('hello', __skip_log__=True)

        self.assertIsInstance(result, Audio)
        self.assertGreater(len(result.to_bytes()), 0)

    def test_openrouter_t2s_factory_uses_specialized_client(self) -> None:
        client = T2SClient.CreateOpenRouterT2SClient(apikey='router-key')

        self.assertIsInstance(client, OpenRouterT2SClient)

    def test_openrouter_gemini_tts_uses_supported_default_voice(self) -> None:
        client = OpenRouterT2SClient(
            apikey='router-key',
            base_url='https://openrouter.ai/api/v1',
            model='google/gemini-3.1-flash-tts-preview',
        )

        payload = client._build_payload('hello', {})

        self.assertEqual(payload['voice'], 'Kore')

    async def test_openrouter_t2s_pcm_response_becomes_audio(self) -> None:
        client = OpenRouterT2SClient(
            apikey='router-key',
            base_url='https://openrouter.ai/api/v1',
            model='google/gemini-3.1-flash-tts-preview',
        )
        response = MagicMock()
        response.headers = {'Content-Type': 'audio/pcm;rate=24000;channels=1'}
        response.raise_for_status = MagicMock()
        response.read = AsyncMock(return_value=b'\x00\x00' * 2400)
        response.release = MagicMock()
        session = MagicMock()
        session.post = AsyncMock(return_value=response)

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.t2s('hello', __skip_log__=True)

        self.assertIsInstance(result, Audio)
        self.assertGreater(len(result.to_bytes()), 0)


class TestT2ImgClients(unittest.IsolatedAsyncioTestCase):
    async def test_openai_t2img_generation_posts_images_payload(self) -> None:
        client = OpenAILikedT2ImgClient(apikey='test-key', base_url='https://api.openai.com/v1', model='gpt-image-1')
        session = _json_context_session({'data': [{'b64_json': base64.b64encode(_png_bytes()).decode('ascii')}]})

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.generate('draw a cat', size='1024x1024', count=1, output_format='png', __skip_log__=True)

        payload = session.post.call_args.kwargs['json']
        self.assertIsInstance(result, Image)
        self.assertEqual(session.post.call_args.args[0], 'https://api.openai.com/v1/images/generations')
        self.assertEqual(payload['model'], 'gpt-image-1')
        self.assertEqual(payload['prompt'], 'draw a cat')
        self.assertEqual(payload['n'], 1)
        self.assertEqual(payload['size'], '1024x1024')
        self.assertNotIn('output_format', payload)

    async def test_openrouter_t2img_posts_chat_modalities_payload(self) -> None:
        client = OpenRouterT2ImgClient(apikey='router-key', base_url='https://openrouter.ai/api/v1', model='black-forest-labs/flux.2-flex')
        session = _json_context_session({
            'choices': [{'message': {'images': [{'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(_png_bytes()).decode('ascii')}}]}}]
        })

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            result = await client.generate('draw mountains', __skip_log__=True)

        payload = session.post.call_args.kwargs['json']
        self.assertIsInstance(result, Image)
        self.assertEqual(session.post.call_args.args[0], 'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(payload['messages'][0]['content'], 'draw mountains')
        self.assertEqual(payload['modalities'], ['image'])
        self.assertNotIn('prompt', payload)

    async def test_openai_t2img_strips_internal_output_format_and_stream_when_unsupported(self) -> None:
        client = OpenAILikedT2ImgClient(apikey='test-key', base_url='https://api.openai.com/v1', model='gpt-image-1')
        session = _json_context_session({'data': [{'b64_json': base64.b64encode(_png_bytes()).decode('ascii')}]})

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            await client.generate('draw a cat', output_format='webp', response_format='url', stream=True, __skip_log__=True)

        payload = session.post.call_args.kwargs['json']
        self.assertNotIn('output_format', payload)
        self.assertNotIn('response_format', payload)
        self.assertNotIn('stream', payload)

    async def test_t2img_background_postprocessing_can_make_transparent_image(self) -> None:
        class DummyClient(T2ImgClient):
            async def _generate_impl(self, prompt, *, count=1, **kwargs):
                from PIL import Image as PILImage
                img = PILImage.new('RGB', (5, 5), 'white')
                for x in range(1, 4):
                    for y in range(1, 4):
                        img.putpixel((x, y), (255, 0, 0))
                return Image(img)

        result = await DummyClient().generate('red square', background='transparent', __skip_log__=True)

        pil = result._ensure_loaded().convert('RGBA')
        self.assertEqual(pil.getpixel((0, 0))[3], 0)
        self.assertGreater(pil.getpixel((2, 2))[3], 0)

    async def test_t2img_media_prompt_uses_completion_conversion_when_client_does_not_support_images(self) -> None:
        class FakeCompletionService:
            async def complete(self, **kwargs):
                self.kwargs = kwargs
                return 'converted image prompt'

        class DummyClient(T2ImgClient):
            async def _generate_impl(self, prompt, *, count=1, **kwargs):
                self.prompt_text = await self._prompt_to_text(prompt)
                return Image(_png_bytes())

        completion = FakeCompletionService()
        client = DummyClient(completion_service=completion)

        await client.generate(['Draw this: ', Image(_png_bytes())], __skip_log__=True)

        self.assertEqual(client.prompt_text, 'converted image prompt')
        self.assertIn('messages', completion.kwargs)

    async def test_t2img_audio_prompt_uses_s2t_conversion(self) -> None:
        class FakeS2TService:
            async def s2t(self, audio, **kwargs):
                self.audio = audio
                return 'spoken prompt'

        class DummyClient(T2ImgClient):
            async def _generate_impl(self, prompt, *, count=1, **kwargs):
                self.prompt_text = await self._prompt_to_text(prompt)
                return Image(_png_bytes())

        s2t = FakeS2TService()
        client = DummyClient(s2t_service=s2t)

        await client.generate(['Draw: ', Audio(_wav_bytes())], __skip_log__=True)

        self.assertEqual(client.prompt_text, 'Draw: spoken prompt')
        self.assertIsInstance(s2t.audio, Audio)

    async def test_openrouter_t2img_edit_and_variation_are_not_directly_supported(self) -> None:
        client = OpenRouterT2ImgClient(apikey='router-key')

        with self.assertRaises(NotImplementedError):
            await client._edit_impl(Image(_png_bytes()), 'edit this')
        with self.assertRaises(NotImplementedError):
            await client._variation_impl(Image(_png_bytes()))

    async def test_openai_t2img_edit_404_becomes_not_implemented_and_drops_task(self) -> None:
        client = OpenAILikedT2ImgClient(apikey='test-key', base_url='https://api.openai.com/v1', model='gpt-image-1')
        not_found = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=404,
            message='Not Found',
        )

        with patch.object(client, '_request_json', new=AsyncMock(side_effect=not_found)):
            with self.assertRaises(NotImplementedError):
                await client.edit(Image(_png_bytes()), 'edit this', __skip_log__=True)

        self.assertNotIn('edit', client.supported_tasks)
        self.assertIn('generate', client.supported_tasks)

    async def test_openai_t2img_variation_404_becomes_not_implemented_and_drops_task(self) -> None:
        client = OpenAILikedT2ImgClient(apikey='test-key', base_url='https://api.openai.com/v1', model='gpt-image-1')
        not_found = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=404,
            message='Not Found',
        )

        with patch.object(client, '_request_json', new=AsyncMock(side_effect=not_found)):
            with self.assertRaises(NotImplementedError):
                await client.variation(Image(_png_bytes()), __skip_log__=True)

        self.assertNotIn('variation', client.supported_tasks)
        self.assertIn('generate', client.supported_tasks)

    async def test_openai_t2img_init_capability_probe_marks_tasks_known(self) -> None:
        client = OpenAILikedT2ImgClient(apikey='test-key', base_url='https://api.openai.com/v1', model='gpt-image-1')

        with (
            patch.object(client, 'edit', new=AsyncMock(side_effect=NotImplementedError('edit unsupported'))),
            patch.object(client, 'variation', new=AsyncMock(return_value=Image(_png_bytes()))),
        ):
            await client.probe_runtime_capabilities_on_init()

        self.assertTrue(client._supported_tasks_runtime_known)
        self.assertNotIn('edit', client.supported_tasks)
        self.assertIn('variation', client.supported_tasks)

    def test_openai_t2img_loads_supported_tasks_from_shared_status(self) -> None:
        client = OpenAILikedT2ImgClient(apikey='test-key', base_url='https://api.openai.com/v1', model='gpt-image-1')

        client.load_runtime_capabilities_from_shared_status({'supported_tasks': 'generate,variation'})

        self.assertEqual(client.supported_tasks, frozenset({'generate', 'variation'}))
        self.assertTrue(client._supported_tasks_runtime_known)

    async def test_t2img_stream_fallback_emits_one_chunk_from_generate(self) -> None:
        class GenerateOnlyClient(T2ImgClient):
            async def _generate_impl(self, prompt, *, count=1, **kwargs):
                self.kwargs = kwargs
                return Image(_png_bytes())

        client = GenerateOnlyClient()
        chunks = [image async for image in client.generate_stream('draw a cat', stream=True, __skip_log__=True)]

        self.assertEqual(len(chunks), 1)
        self.assertIsInstance(chunks[0], Image)
        self.assertNotIn('stream', client.kwargs)

    async def test_t2img_service_falls_back_to_generate_for_openrouter_edit(self) -> None:
        class FakeCompletionService:
            async def complete(self, **kwargs):
                return 'fallback generation prompt'

        class GenerateOnlyClient(T2ImgClient):
            def __init__(self):
                super().__init__(supported_tasks=('generate',))
                self.prompt = None

            async def _generate_impl(self, prompt, *, count=1, **kwargs):
                self.prompt = prompt
                return Image(_png_bytes())

        client = GenerateOnlyClient()
        service = __import__('core.ai.t2img', fromlist=['T2ImgService']).T2ImgService(client, completion_service=FakeCompletionService())
        self.addCleanup(service.close)

        await service.edit(Image(_png_bytes()), 'make it blue')

        self.assertEqual(client.prompt, 'fallback generation prompt')

    async def test_t2img_service_falls_back_to_generate_for_openrouter_variation(self) -> None:
        class FakeCompletionService:
            async def complete(self, **kwargs):
                self.kwargs = kwargs
                return 'variation generation prompt'

        class GenerateOnlyClient(T2ImgClient):
            def __init__(self):
                super().__init__(supported_tasks=('generate',))
                self.prompt = None

            async def _generate_impl(self, prompt, *, count=1, **kwargs):
                self.prompt = prompt
                return Image(_png_bytes())

        completion = FakeCompletionService()
        client = GenerateOnlyClient()
        service = __import__('core.ai.t2img', fromlist=['T2ImgService']).T2ImgService(client, completion_service=completion)
        self.addCleanup(service.close)

        await service.variation(Image(_png_bytes()))

        self.assertEqual(client.prompt, 'variation generation prompt')
        self.assertIn('messages', completion.kwargs)

    async def test_t2img_service_falls_back_to_generate_when_edit_endpoint_missing(self) -> None:
        class FakeCompletionService:
            async def complete(self, **kwargs):
                return 'fallback generation prompt'

        class MissingEditClient(T2ImgClient):
            def __init__(self):
                super().__init__(supported_tasks=('generate', 'edit'))
                self.prompt = None

            async def _generate_impl(self, prompt, *, count=1, **kwargs):
                self.prompt = prompt
                return Image(_png_bytes())

            async def _edit_impl(self, image, prompt, *, count=1, **kwargs):
                self.supported_tasks = frozenset({'generate'})
                raise NotImplementedError('edit unsupported')

        client = MissingEditClient()
        service = __import__('core.ai.t2img', fromlist=['T2ImgService']).T2ImgService(client, completion_service=FakeCompletionService())
        self.addCleanup(service.close)

        await service.edit(Image(_png_bytes()), 'make it blue')

        self.assertEqual(client.prompt, 'fallback generation prompt')

    async def test_t2img_service_falls_back_to_generate_when_variation_endpoint_missing(self) -> None:
        class FakeCompletionService:
            async def complete(self, **kwargs):
                return 'variation generation prompt'

        class MissingVariationClient(T2ImgClient):
            def __init__(self):
                super().__init__(supported_tasks=('generate', 'variation'))
                self.prompt = None

            async def _generate_impl(self, prompt, *, count=1, **kwargs):
                self.prompt = prompt
                return Image(_png_bytes())

            async def _variation_impl(self, image, *, count=1, **kwargs):
                self.supported_tasks = frozenset({'generate'})
                raise NotImplementedError('variation unsupported')

        completion = FakeCompletionService()
        client = MissingVariationClient()
        service = __import__('core.ai.t2img', fromlist=['T2ImgService']).T2ImgService(client, completion_service=completion)
        self.addCleanup(service.close)

        await service.variation(Image(_png_bytes()))

        self.assertEqual(client.prompt, 'variation generation prompt')

    async def test_openai_t2img_forwards_supported_image_params_and_extra_fields(self) -> None:
        client = OpenAILikedT2ImgClient(apikey='test-key', base_url='https://api.openai.com/v1', model='gpt-image-1')
        session = _json_context_session({'data': [{'b64_json': base64.b64encode(_png_bytes()).decode('ascii')}]})

        with patch.object(client, '_get_session', new=AsyncMock(return_value=session)):
            await client.generate('draw', partial_images=2, moderation='low', seed=42, __skip_log__=True)

        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['partial_images'], 2)
        self.assertEqual(payload['moderation'], 'low')
        self.assertEqual(payload['seed'], 42)

    def test_t2img_openrouter_factory_uses_specialized_client(self) -> None:
        client = T2ImgClient.CreateOpenRouterT2ImgClient(apikey='router-key')

        self.assertIsInstance(client, OpenRouterT2ImgClient)


if __name__ == '__main__':
    unittest.main()
