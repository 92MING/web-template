# -*- coding: utf-8 -*-
"""Extended tests for AI service endpoints with mocked backends."""


import base64
import os
import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from _test_helpers import FullAppTestBase
from core.server.routes.ai_services._client_view import (
    AIServiceClientInfo,
    AIServiceInfo,
    AIServiceInstanceInfo,
)


def _fake_wav_bytes() -> bytes:
    return b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80>\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


class _FakeAudioPayload:
    def __init__(self, data: bytes):
        self._data = data

    def to_bytes(self) -> bytes:
        return self._data


class _FakeTranscriptResult:
    def model_dump(self):
        return {
            "transcript": [
                {"speaker": "A", "text": "hello transcript"},
            ]
        }


class _FakeHttpResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestAITempClientFactory(unittest.TestCase):
    def test_check_temp_client_env_key_accepts_tts_aliases(self):
        from core.server.routes.ai_services import api as ai_api

        with patch.dict(os.environ, {"TTS_APIKEY": "tk"}, clear=True):
            self.assertTrue(ai_api._check_temp_client_env_key("thinkthinksyn"))
        with patch.dict(os.environ, {"TTS_API_KEY": "tk"}, clear=True):
            self.assertTrue(ai_api._check_temp_client_env_key("thinkthinksyn"))

    def test_check_temp_client_env_key_accepts_openrouter_aliases(self):
        from core.server.routes.ai_services import api as ai_api

        with patch.dict(os.environ, {"OPENROUTER_APIKEY": "ork"}, clear=True):
            self.assertTrue(ai_api._check_temp_client_env_key("openrouter"))
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "ork"}, clear=True):
            self.assertTrue(ai_api._check_temp_client_env_key("openrouter"))

    def test_make_temp_openrouter_client_imports_public_completion_client(self):
        from core.server.routes.ai_services import api as ai_api

        temp_client = object()
        with patch("core.ai.CompletionClient.CreateOpenRouterClient", return_value=temp_client) as create_client:
            client = ai_api._make_temp_completion_client(
                "openrouter",
                base_url="https://example.com/v1",
                apikey="explicit-key",
                model="openrouter/mock-model",
            )

        self.assertIs(client, temp_client)
        create_client.assert_called_once()
        self.assertEqual(create_client.call_args.kwargs["base_url"], "https://example.com/v1")
        self.assertEqual(create_client.call_args.kwargs["apikey"], "explicit-key")
        self.assertEqual(create_client.call_args.kwargs["model"], "openrouter/mock-model")


class TestAIProviderAndModelEndpoints(FullAppTestBase):
    async def test_has_env_key_thinkthinksyn_true(self):
        with patch.dict(os.environ, {"TTS_APIKEY": "tk"}, clear=False):
            resp = await self._client.get("/ai/clients/thinkthinksyn/has-env-key")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"has_env_key": True})

    async def test_has_env_key_openrouter_missing(self):
        env = {k: v for k, v in os.environ.items() if k not in {"OPENROUTER_APIKEY", "OPENROUTER_API_KEY"}}
        with patch.dict(os.environ, env, clear=True):
            resp = await self._client.get("/ai/clients/openrouter/has-env-key")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"has_env_key": False})

    async def test_has_env_key_unknown_provider_422(self):
        resp = await self._client.get("/ai/clients/unknown/has-env-key")
        self.assertEqual(resp.status_code, 422)

    async def test_completion_status_returns_lightweight_service_state(self):
        client_a = SimpleNamespace(
            _state_cooldown_until=0.0,
            _state_last_error=None,
            _state_inflight=0,
            _state_last_success_at=1000.0,
        )
        client_b = SimpleNamespace(
            _state_cooldown_until=0.0,
            _state_last_error=None,
            _state_inflight=1,
            _state_last_success_at=2000.0,
        )
        service = SimpleNamespace(clients=[client_a, client_b])

        with patch("core.server.routes.ai_services.api._get_completion_service", return_value=service):
            resp = await self._client.get("/ai/completion-status")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {
                "client_count": 2,
                "healthy_count": 2,
                "cooling_count": 0,
                "inflight_total": 1,
                "last_success_at": 2000.0,
                "last_error": None,
            },
        )

    async def test_models_thinkthinksyn_missing_apikey_returns_400(self):
        env = {k: v for k, v in os.environ.items() if k not in {"TTS_APIKEY", "TTS_API_KEY"}}
        with patch.dict(os.environ, env, clear=True):
            resp = await self._client.post("/ai/clients/thinkthinksyn/list-models", json={})
        self.assertEqual(resp.status_code, 400)

    async def test_models_openrouter_proxy_success(self):
        seen: dict[str, object] = {}

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                seen["kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None):
                seen["url"] = url
                seen["headers"] = headers or {}
                return _FakeHttpResponse({"data": [{"id": "openrouter/mock-model"}]})

        with (
            patch("httpx.AsyncClient", _FakeAsyncClient),
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret-token"}, clear=False),
        ):
            resp = await self._client.post("/ai/clients/openrouter/list-models", json={})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"][0]["id"], "openrouter/mock-model")
        self.assertEqual(seen["url"], "https://openrouter.ai/api/v1/models")
        self.assertEqual(seen["headers"], {"Authorization": "Bearer secret-token"})

    async def test_models_openrouter_explicit_credentials_override_env(self):
        seen: dict[str, object] = {}

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None):
                seen["url"] = url
                seen["headers"] = headers or {}
                return _FakeHttpResponse({"data": []})

        with patch("httpx.AsyncClient", _FakeAsyncClient):
            resp = await self._client.post(
                "/ai/clients/openrouter/list-models",
                json={"base_url": "https://example.com/v1", "apikey": "explicit"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(seen["url"], "https://example.com/v1/models")
        self.assertEqual(seen["headers"], {"Authorization": "Bearer explicit"})


class TestAIServiceDiscoveryDetails(FullAppTestBase):
    async def test_get_service_instance_returns_instance_payload(self):
        fake_info = AIServiceInfo(
            kind='completion',
            instances={
                'default': AIServiceInstanceInfo(
                    key='default',
                    available=True,
                    clients=['client-a'],
                    max_concurrent=8,
                    avg_speed_ewma=0.25,
                    inflight_total=1,
                ),
            },
            clients={
                'client-a': AIServiceClientInfo(
                    key='client-a',
                    type='mock-completion',
                    available=True,
                    strategy_lvl=0,
                    max_concurrent=8,
                    inflight=1,
                    cooldown_until=0.0,
                    last_error=None,
                    last_success_at=123.0,
                    fail_count=0,
                    success_count=5,
                    score=1.0,
                    speed_ewma=0.25,
                ),
            },
        )

        with patch('core.server.routes.ai_services.api.build_service_info', return_value=fake_info):
            resp = await self._client.get('/ai/services/completion/instances/default')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {
                'key': 'default',
                'available': True,
                'clients': ['client-a'],
                'max_concurrent': 8,
                'avg_speed_ewma': 0.25,
                'inflight_total': 1,
            },
        )

    async def test_get_service_client_returns_client_payload(self):
        fake_info = AIServiceInfo(
            kind='completion',
            instances={},
            clients={
                'client-a': AIServiceClientInfo(
                    key='client-a',
                    type='mock-completion',
                    available=False,
                    strategy_lvl=1,
                    max_concurrent=None,
                    inflight=2,
                    cooldown_until=456.0,
                    last_error='cooling',
                    last_success_at=123.0,
                    fail_count=2,
                    success_count=7,
                    score=0.75,
                    speed_ewma=1.5,
                ),
            },
        )

        with patch('core.server.routes.ai_services.api.build_service_info', return_value=fake_info):
            resp = await self._client.get('/ai/services/completion/clients/client-a')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {
                'key': 'client-a',
                'type': 'mock-completion',
                'available': False,
                'strategy_lvl': 1,
                'priority': 0.0,
                'max_concurrent': None,
                'inflight': 2,
                'cooldown_until': 456.0,
                'last_error': 'cooling',
                'last_success_at': 123.0,
                'fail_count': 2,
                'success_count': 7,
                'score': 0.75,
                'speed_ewma': 1.5,
            },
        )


class TestAIStreamingAndMediaEndpoints(FullAppTestBase):
    async def test_complete_stream_returns_sse_chunks_and_meta(self):
        async def _stream_complete(**kwargs):
            yield {"data": "hello", "type": "text"}
            yield {"data": " world", "type": "text"}

        service = SimpleNamespace(
            stream_complete=_stream_complete,
            _peek_latest_token_usage=lambda: {"total_tokens": 2},
        )

        with patch("core.server.routes.ai_services.api._get_completion_service", return_value=service):
            resp = await self._client.post(
                "/ai/complete",
                json={
                    "messages": [{"role": "user", "content": "Say hello"}],
                    "stream": True,
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.headers.get("content-type", ""))
        self.assertIn("hello", resp.text)
        self.assertIn('"done": true', resp.text)

    async def test_test_openrouter_complete_maps_factory_value_error_to_400(self):
        with patch(
            "core.server.routes.ai_services.api._make_temp_completion_client",
            side_effect=ValueError("OpenRouter apikey not provided."),
        ) as make_temp_client:
            resp = await self._client.post(
                "/ai/test_openrouter_complete",
                json={"messages": [{"role": "user", "content": "Say hello"}]},
            )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("apikey", resp.text.lower())
        make_temp_client.assert_called_once_with(
            "openrouter",
            base_url=None,
            apikey=None,
            model=None,
        )

    async def test_test_thinkthinksyn_complete_non_stream_uses_special_request_body(self):
        async def _complete(**kwargs):
            return "temp ok"

        client = SimpleNamespace(
            complete=_complete,
            _peek_latest_token_usage=lambda: {"total_tokens": 1},
        )

        with patch("core.server.routes.ai_services.api._make_temp_completion_client", return_value=client) as make_temp_client:
            resp = await self._client.post(
                "/ai/test_thinkthinksyn_complete",
                json={
                    "model": "qwen-omni",
                    "base_url": " https://example.com/v1 ",
                    "apikey": " explicit-key ",
                    "messages": [{"role": "user", "content": "Say hello"}],
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["text"], "temp ok")
        make_temp_client.assert_called_once_with(
            "thinkthinksyn",
            base_url="https://example.com/v1",
            apikey="explicit-key",
            model="qwen-omni",
        )

    async def test_test_openrouter_complete_stream_returns_sse_chunks_and_meta(self):
        async def _stream_complete(**kwargs):
            yield {"data": "temp", "type": "text"}

        client = SimpleNamespace(
            stream_complete=_stream_complete,
            _peek_latest_token_usage=lambda: {"total_tokens": 1},
        )

        with patch("core.server.routes.ai_services.api._make_temp_completion_client", return_value=client) as make_temp_client:
            resp = await self._client.post(
                "/ai/test_openrouter_complete",
                json={
                    "apikey": "explicit-key",
                    "stream": True,
                    "messages": [{"role": "user", "content": "Say hello"}],
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("temp", resp.text)
        self.assertIn('"done": true', resp.text)
        make_temp_client.assert_called_once_with(
            "openrouter",
            base_url=None,
            apikey="explicit-key",
            model=None,
        )

    async def test_ocr_success_returns_text_and_request_echo(self):
        service = SimpleNamespace(ocr=AsyncMock(return_value="recognized text"))

        with (
            patch("core.server.routes.ai_services.api._get_completion_service", return_value=service),
            patch("core.server.routes.ai_services.api.Image", return_value=object()),
        ):
            resp = await self._client.post(
                "/ai/ocr",
                files={"file": ("sample.png", b"fake-image", "image/png")},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["text"], "recognized text")
        self.assertEqual(data["request_echo"]["filename"], "sample.png")

    async def test_asr_success_returns_text_and_params(self):
        service = SimpleNamespace(asr=AsyncMock(return_value="speech text"))

        with (
            patch("core.server.routes.ai_services.api._get_completion_service", return_value=service),
            patch("core.server.routes.ai_services.api.Audio", return_value=object()),
        ):
            resp = await self._client.post(
                "/ai/asr",
                files={"file": ("sample.wav", b"fake-audio", "audio/wav")},
                data={"expected_languages": "en,zh", "prompt": "listen carefully"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["text"], "speech text")
        self.assertEqual(data["request_echo"]["expected_languages"], ["en", "zh"])
        self.assertEqual(data["request_echo"]["prompt"], "listen carefully")

    async def test_s2t_success_returns_text(self):
        service = SimpleNamespace(s2t=AsyncMock(return_value="transcribed"))

        with (
            patch("core.server.routes.ai_services.api._get_s2t_service", return_value=service),
            patch("core.server.routes.ai_services.api.Audio", return_value=object()),
        ):
            resp = await self._client.post(
                "/ai/s2t",
                files={"file": ("sample.wav", b"fake-audio", "audio/wav")},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["text"], "transcribed")

    async def test_t2s_success_returns_base64_audio(self):
        wav = _fake_wav_bytes()
        service = SimpleNamespace(t2s=AsyncMock(return_value=_FakeAudioPayload(wav)))

        with patch("core.server.routes.ai_services.api._get_t2s_service", return_value=service):
            resp = await self._client.post("/ai/t2s", json={"text": "hello voice"})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(base64.b64decode(data["audio_base64"]), wav)
        self.assertEqual(data["mime_type"], "audio/wav")
        self.assertEqual(data["format"], "wav")

    async def test_t2s_stream_returns_audio_bytes(self):
        async def _stream_audio(text: str, chunk_size: int = 16384):
            yield b"chunk-1-"
            yield b"chunk-2"

        service = SimpleNamespace(t2s_stream=_stream_audio)

        with patch("core.server.routes.ai_services.api._get_t2s_service", return_value=service):
            resp = await self._client.post("/ai/t2s/stream", json={"text": "hello voice", "chunk_size": 8})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"chunk-1-chunk-2")
        # Headers x-ai-mode / x-ai-chunk-size are not set by the current backend implementation

    async def test_transcript_success_returns_model_dump_payload(self):
        service = SimpleNamespace(transcript=AsyncMock(return_value=_FakeTranscriptResult()))

        with (
            patch("core.server.routes.ai_services.api._get_completion_service", return_value=service),
            patch("core.server.routes.ai_services.api.Audio", return_value=object()),
        ):
            resp = await self._client.post(
                "/ai/transcript",
                files={"file": ("sample.wav", b"fake-audio", "audio/wav")},
                data={"roles": "teacher,student", "expected_languages": "en", "prompt": "separate speakers"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["transcript"]["segments"][0]["text"], "hello transcript")
        self.assertEqual(data["request_echo"]["roles"], ["teacher", "student"])

    async def test_transcript_success_normalizes_role_key_payload(self):
        service = SimpleNamespace(
            transcript=AsyncMock(return_value=SimpleNamespace(model_dump=lambda: {
                "transcript": [
                    {"Teacher": "normalized transcript"},
                ]
            }))
        )

        with (
            patch("core.server.routes.ai_services.api._get_completion_service", return_value=service),
            patch("core.server.routes.ai_services.api.Audio", return_value=object()),
        ):
            resp = await self._client.post(
                "/ai/transcript",
                files={"file": ("sample.wav", b"fake-audio", "audio/wav")},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["transcript"]["segments"][0]["speaker"], "Teacher")
        self.assertEqual(data["transcript"]["segments"][0]["text"], "normalized transcript")

    async def test_rerank_success_returns_items_and_token_usage(self):
        result = SimpleNamespace(items=[SimpleNamespace(index=0, score=9.5, candidate="first")])
        service = SimpleNamespace(
            rerank=AsyncMock(return_value=result),
            _peek_latest_token_usage=lambda: {"total_tokens": 8},
        )

        with patch("core.server.routes.ai_services.api._get_completion_service", return_value=service):
            resp = await self._client.post(
                "/ai/rerank",
                json={"query": "rank this", "candidates": ["first", "second"], "stream": False},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["items"][0]["candidate"], "first")
        self.assertEqual(data["token_usage"]["total_tokens"], 8)


class TestAIEmbeddingExtendedEndpoints(FullAppTestBase):
    async def test_embedding_rerank_returns_items(self):
        service = SimpleNamespace(
            rerank=AsyncMock(return_value=[SimpleNamespace(index=1, score=0.91, candidate="beta")])
        )

        with patch("core.server.routes.ai_services.api._get_embedding_service", return_value=service):
            resp = await self._client.post(
                "/ai/embedding/rerank",
                json={"query": "topic", "candidates": ["alpha", "beta"]},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["items"][0]["candidate"], "beta")

    async def test_embedding_chunking_returns_chunks(self):
        service = SimpleNamespace(
            chunking=AsyncMock(return_value=[SimpleNamespace(text="chunk-1", vector=[0.1, 0.2], index=0, offset=0)])
        )

        with patch("core.server.routes.ai_services.api._get_embedding_service", return_value=service):
            resp = await self._client.post(
                "/ai/embedding/chunking",
                json={"content": "Long text for chunking", "max_word_count": 128},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["chunks"][0]["text"], "chunk-1")

    async def test_embedding_diversity_returns_items(self):
        service = SimpleNamespace(
            diversity_rerank=AsyncMock(return_value=[SimpleNamespace(index=0, candidate="alpha", min_distance=0.42)])
        )

        with patch("core.server.routes.ai_services.api._get_embedding_service", return_value=service):
            resp = await self._client.post(
                "/ai/embedding/diversity",
                json={"candidates": ["alpha", "beta"], "top_k": 1},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["items"][0]["min_distance"], 0.42)

    async def test_embedding_cache_endpoints_return_mocked_payloads(self):
        service = SimpleNamespace(
            cache_stats=AsyncMock(return_value={"items": 3, "bytes": 1024}),
            cache_clear=AsyncMock(return_value=2),
        )

        with patch("core.server.routes.ai_services.api._get_embedding_service", return_value=service):
            stats_resp = await self._client.get("/ai/embedding/cache-stats")
            clear_resp = await self._client.post("/ai/embedding/cache-clear")

        self.assertEqual(stats_resp.status_code, 200)
        self.assertEqual(stats_resp.json()["items"], 3)
        self.assertEqual(clear_resp.status_code, 200)
        self.assertEqual(clear_resp.json()["deleted"], 2)


class TestAIOpenAPISchemas(FullAppTestBase):
    async def test_openapi_exposes_named_models_for_ai_routes(self):
        resp = await self._client.get("/_internal/admin/openapi.json")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        paths = payload["paths"]
        schemas = payload["components"]["schemas"]

        provider_schema = paths["/ai/clients/{provider}/has-env-key"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        completion_request_schema = paths["/ai/complete"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        thinkthinksyn_request_schema = paths["/ai/test_thinkthinksyn_complete"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        openrouter_request_schema = paths["/ai/test_openrouter_complete"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        rerank_schema = paths["/ai/rerank"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]

        self.assertEqual(provider_schema["$ref"], "#/components/schemas/HasEnvKeyResponse")
        self.assertEqual(completion_request_schema["$ref"], "#/components/schemas/CompletionRequest")
        self.assertEqual(thinkthinksyn_request_schema["$ref"], "#/components/schemas/ThinkThinkSynCompleteRequest")
        self.assertEqual(openrouter_request_schema["$ref"], "#/components/schemas/OpenRouterCompleteRequest")
        self.assertEqual(rerank_schema["$ref"], "#/components/schemas/RankedItemsResponse")

        completion_props = schemas["CompletionRequest"]["properties"]
        self.assertNotIn("provider", completion_props)
        self.assertNotIn("model", completion_props)
        self.assertNotIn("base_url", completion_props)
        self.assertNotIn("apikey", completion_props)

        thinkthinksyn_props = schemas["ThinkThinkSynCompleteRequest"]["properties"]
        self.assertIn("model", thinkthinksyn_props)
        self.assertIn("base_url", thinkthinksyn_props)
        self.assertIn("apikey", thinkthinksyn_props)

        openrouter_props = schemas["OpenRouterCompleteRequest"]["properties"]
        self.assertIn("model", openrouter_props)
        self.assertIn("base_url", openrouter_props)
        self.assertIn("apikey", openrouter_props)

if __name__ == "__main__":
    unittest.main()

