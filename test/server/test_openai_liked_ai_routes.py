# -*- coding: utf-8 -*-
"""Tests for compatible AI service routes."""

import base64
import io
import json
import sys
import wave
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_DIR = _PROJECT_ROOT / "app"
for _path in (str(_PROJECT_ROOT), str(_APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.server.data_types.config import Config, ServerConfig
from core.server.routes.ai_services import api as ai_api
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
    from PIL import Image as PILImage

    buffer = io.BytesIO()
    PILImage.new('RGB', (1, 1), color=(255, 0, 0)).save(buffer, format='PNG')
    return buffer.getvalue()


def _openai_liked_app() -> FastAPI:
    Config.SetConfig(Config(server_config=ServerConfig(
        expose_ai_service=False,
        expose_internal_prefix=False,
        expose_compatible_ai_services=True,
    )))
    app = FastAPI()
    ai_api.register_ai_service_routes(app)
    app.dependency_overrides[ai_api._require_exposed_ai_service_apikey] = lambda: None
    return app


def test_openai_liked_completion_route(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeCompletionService:
        async def complete(self, **kwargs: Any) -> str:
            calls.append(kwargs)
            return 'hello back'

        async def stream_complete(self, **kwargs: Any):
            yield {'data': 'hello'}

        def _peek_latest_token_usage(self) -> dict[str, Any]:
            return {'input_tokens': 2, 'output_tokens': 3, 'total_tokens': 5}

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 'completion'
        assert service_key == 'default'
        return FakeCompletionService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/completion/service/default/openai/v1/chat/completions', json={
            'model': 'gpt-test',
            'messages': [{'role': 'user', 'content': 'hi'}],
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'chat.completion'
    assert payload['model'] == 'gpt-test'
    assert payload['choices'][0]['message']['content'] == 'hello back'
    assert calls[0]['model'] == 'gpt-test'


def test_openai_liked_completion_stream_starts_with_role_and_skips_think(monkeypatch) -> None:
    class FakeCompletionService:
        async def complete(self, **kwargs: Any) -> str:
            return 'unused'

        async def stream_complete(self, **kwargs: Any):
            yield {'type': 'think', 'data': 'hidden thought'}
            yield {'type': 'text', 'data': 'hello'}

        def _peek_latest_token_usage(self) -> dict[str, Any]:
            return {}

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 'completion'
        assert service_key == 'default'
        return FakeCompletionService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/completion/service/default/openai/v1/chat/completions', json={
            'messages': [{'role': 'user', 'content': 'hi'}],
            'stream': True,
        })

    assert response.status_code == 200
    events = [line.removeprefix('data: ') for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1] == '[DONE]'
    payloads = [json.loads(event) for event in events[:-1]]
    assert payloads[0]['choices'][0]['delta'] == {'role': 'assistant'}
    content = ''.join(item['choices'][0]['delta'].get('content', '') for item in payloads)
    assert content == 'hello'
    assert 'hidden thought' not in response.text


def test_anthropic_liked_completion_route(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeCompletionService:
        async def complete(self, **kwargs: Any) -> str:
            calls.append(kwargs)
            return 'hello anthropic'

        async def stream_complete(self, **kwargs: Any):
            yield {'data': 'unused'}

        def _peek_latest_token_usage(self) -> dict[str, Any]:
            return {'input_tokens': 4, 'output_tokens': 5, 'total_tokens': 9}

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 'completion'
        assert service_key == 'default'
        return FakeCompletionService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/completion/service/default/anthropic/v1/messages', json={
            'model': 'claude-test',
            'system': 'You are helpful.',
            'max_tokens': 128,
            'messages': [{'role': 'user', 'content': 'hi'}],
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload['type'] == 'message'
    assert payload['model'] == 'claude-test'
    assert payload['content'][0]['text'] == 'hello anthropic'
    assert payload['usage'] == {'input_tokens': 4, 'output_tokens': 5}
    assert calls[0]['max_tokens'] == 128
    assert calls[0]['messages'] == [
        {'role': 'system', 'content': 'You are helpful.'},
        {'role': 'user', 'content': 'hi'},
    ]


def test_anthropic_liked_completion_stream_uses_anthropic_events(monkeypatch) -> None:
    class FakeCompletionService:
        async def complete(self, **kwargs: Any) -> str:
            return 'unused'

        async def stream_complete(self, **kwargs: Any):
            yield {'type': 'think', 'data': 'hidden thought'}
            yield {'type': 'text', 'data': 'hello'}

        def _peek_latest_token_usage(self) -> dict[str, Any]:
            return {'output_tokens': 3}

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 'completion'
        assert service_key == 'default'
        return FakeCompletionService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/completion/service/default/anthropic/messages', json={
            'messages': [{'role': 'user', 'content': 'hi'}],
            'stream': True,
        })

    assert response.status_code == 200
    assert 'event: message_start' in response.text
    assert 'event: content_block_start' in response.text
    assert 'event: content_block_delta' in response.text
    assert 'event: message_delta' in response.text
    assert 'event: message_stop' in response.text
    assert 'hidden thought' not in response.text


def test_openai_liked_embedding_route(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeEmbeddingService:
        async def embedding_raw(self, inputs: list[Any], **kwargs: Any) -> dict[str, Any]:
            calls.append({'inputs': inputs, 'kwargs': kwargs})
            return {
                'object': 'list',
                'data': [{'object': 'embedding', 'embedding': [0.1, 0.2], 'index': 0}],
                'model': kwargs.get('model'),
                'usage': {'prompt_tokens': 1, 'total_tokens': 1},
            }

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 'embedding'
        assert service_key == 'special'
        return FakeEmbeddingService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/embedding/service/special/openai/v1/embeddings', json={
            'model': 'text-embedding-test',
            'input': 'hello',
            'encoding_format': 'float',
            'dimensions': 2,
            'client_key': 'embedding:client-a',
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload['object'] == 'list'
    assert payload['data'][0]['embedding'] == [0.1, 0.2]
    assert calls[0]['inputs'] == ['hello']
    assert calls[0]['kwargs']['model'] == 'text-embedding-test'
    assert calls[0]['kwargs']['dimensions'] == 2
    assert calls[0]['kwargs']['client_key'] == 'embedding:client-a'


def test_openai_liked_s2t_route_json_audio(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeS2TService:
        async def s2t_raw(self, audio: Audio, **kwargs: Any) -> dict[str, Any]:
            calls.append({'audio': audio, 'kwargs': kwargs})
            return {'text': 'transcribed'}

    async def fake_resolve_client(kind: str, client_key: str | None) -> Any:
        assert kind == 's2t'
        assert client_key == 's2t:client-a'
        return FakeS2TService()

    monkeypatch.setattr(ai_api, '_resolve_ai_client_instance', fake_resolve_client)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/s2t/client/s2t:client-a/openai/v1/audio/transcriptions', json={
            'file': base64.b64encode(_wav_bytes()).decode('ascii'),
            'model': 'whisper-test',
            'language': 'en',
            'response_format': 'json',
        })

    assert response.status_code == 200
    assert response.json()['text'] == 'transcribed'
    assert calls[0]['kwargs']['model'] == 'whisper-test'
    assert calls[0]['kwargs']['language'] == 'en'
    assert 'client_key' not in calls[0]['kwargs']


def test_openai_liked_t2s_route(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2SService:
        async def t2s(self, text: str, **kwargs: Any) -> Audio:
            calls.append({'text': text, 'kwargs': kwargs})
            return Audio(_wav_bytes())

    async def fake_resolve_client(kind: str, client_key: str | None) -> Any:
        assert kind == 't2s'
        assert client_key == 't2s:client-a'
        return FakeT2SService()

    monkeypatch.setattr(ai_api, '_resolve_ai_client_instance', fake_resolve_client)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/t2s/client/t2s:client-a/openai/v1/audio/speech', json={
            'model': 'tts-test',
            'input': 'hello',
            'voice': 'alloy',
            'response_format': 'wav',
            'speed': 1.1,
        })

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('audio/wav')
    assert calls[0]['text'] == 'hello'
    assert calls[0]['kwargs']['model'] == 'tts-test'
    assert calls[0]['kwargs']['voice'] == 'alloy'
    assert calls[0]['kwargs']['speed'] == 1.1
    assert 'client_key' not in calls[0]['kwargs']


def test_openai_liked_t2s_route_returns_original_audio_bytes(monkeypatch) -> None:
    original = b'ID3original-mp3-bytes'

    class FakeT2SService:
        async def t2s(self, text: str, **kwargs: Any) -> Audio:
            return Audio(original, format='mp3')

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 't2s'
        assert service_key == 'default'
        return FakeT2SService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/t2s/service/default/openai/v1/audio/speech', json={
            'input': 'hello',
            'voice': 'alloy',
            'response_format': 'mp3',
        })

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('audio/mpeg')
    assert response.content == original


def test_openai_liked_t2img_generation_service_route(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2ImgService:
        async def generate(self, prompt: str, **kwargs: Any) -> Image:
            calls.append({'prompt': prompt, 'kwargs': kwargs})
            return Image(_png_bytes())

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 't2img'
        assert service_key == 'default'
        return FakeT2ImgService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/t2img/service/default/openai/v1/images/generations', json={
            'model': 'gpt-image-test',
            'prompt': 'draw a cat',
            'n': 1,
            'size': '1024x1024',
            'background': 'transparent',
            'output_format': 'png',
            'response_format': 'b64_json',
            'quality': 'high',
            'client_key': 't2img:client-a',
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload['data'][0]['b64_json']
    assert payload['data'][0]['url'] is None
    assert payload['output_format'] == 'png'
    assert payload['background'] == 'transparent'
    assert payload['quality'] == 'high'
    assert payload['size'] == '1024x1024'
    assert calls[0]['prompt'] == 'draw a cat'
    assert calls[0]['kwargs']['model'] == 'gpt-image-test'
    assert calls[0]['kwargs']['count'] == 1
    assert calls[0]['kwargs']['size'] == '1024x1024'
    assert calls[0]['kwargs']['client_key'] == 't2img:client-a'


def test_openai_liked_t2img_edit_client_route_uses_path_client(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2ImgClient:
        async def edit(self, image: Image, prompt: str, **kwargs: Any) -> Image:
            calls.append({'image': image, 'prompt': prompt, 'kwargs': kwargs})
            return Image(_png_bytes())

    async def fake_resolve_client(kind: str, client_key: str | None) -> Any:
        assert kind == 't2img'
        assert client_key == 't2img:client-a'
        return FakeT2ImgClient()

    monkeypatch.setattr(ai_api, '_resolve_ai_client_instance', fake_resolve_client)

    with TestClient(_openai_liked_app()) as client:
        response = client.post(
            '/ai/t2img/client/t2img:client-a/openai/v1/images/edits',
            data={'prompt': 'make it blue', 'client_key': 'ignored-client-key'},
            files={'image': ('image.png', _png_bytes(), 'image/png')},
        )

    assert response.status_code == 200
    assert calls[0]['prompt'] == 'make it blue'
    assert isinstance(calls[0]['image'], Image)
    assert 'client_key' not in calls[0]['kwargs']


def test_openai_liked_t2img_variation_service_route(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2ImgService:
        async def variation(self, image: Image, **kwargs: Any) -> Image:
            calls.append({'image': image, 'kwargs': kwargs})
            return Image(_png_bytes())

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 't2img'
        assert service_key == 'default'
        return FakeT2ImgService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post(
            '/ai/t2img/service/default/openai/v1/images/variations',
            data={'n': '2', 'size': '1024x1024'},
            files={'image': ('image.png', _png_bytes(), 'image/png')},
        )

    assert response.status_code == 200
    assert isinstance(calls[0]['image'], Image)
    assert calls[0]['kwargs']['count'] == 2
    assert calls[0]['kwargs']['size'] == '1024x1024'


def test_openai_liked_t2img_variation_client_route_uses_path_client(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2ImgClient:
        async def variation(self, image: Image, **kwargs: Any) -> Image:
            calls.append({'image': image, 'kwargs': kwargs})
            return Image(_png_bytes())

    async def fake_resolve_client(kind: str, client_key: str | None) -> Any:
        assert kind == 't2img'
        assert client_key == 't2img:client-a'
        return FakeT2ImgClient()

    monkeypatch.setattr(ai_api, '_resolve_ai_client_instance', fake_resolve_client)

    with TestClient(_openai_liked_app()) as client:
        response = client.post(
            '/ai/t2img/client/t2img:client-a/openai/v1/images/variations',
            data={'client_key': 'ignored-client-key'},
            files={'image': ('image.png', _png_bytes(), 'image/png')},
        )

    assert response.status_code == 200
    assert isinstance(calls[0]['image'], Image)
    assert 'client_key' not in calls[0]['kwargs']


def test_openai_liked_t2img_generation_client_route_uses_url_format(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2ImgClient:
        async def generate(self, prompt: str, **kwargs: Any) -> Image:
            calls.append({'prompt': prompt, 'kwargs': kwargs})
            return Image(_png_bytes())

    async def fake_resolve_client(kind: str, client_key: str | None) -> Any:
        assert kind == 't2img'
        assert client_key == 't2img:client-a'
        return FakeT2ImgClient()

    monkeypatch.setattr(ai_api, '_resolve_ai_client_instance', fake_resolve_client)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/t2img/client/t2img:client-a/openai/v1/images/generations', json={
            'prompt': 'draw mountains',
            'response_format': 'url',
            'output_format': 'png',
            'client_key': 'ignored-client-key',
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload['data'][0]['url'].startswith('data:image/')
    assert payload['data'][0]['b64_json'] is None
    assert calls[0]['prompt'] == 'draw mountains'
    assert 'client_key' not in calls[0]['kwargs']


def test_openai_liked_t2img_generation_stream_falls_back_to_one_image_chunk(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2ImgService:
        async def generate_stream(self, prompt: str, **kwargs: Any):
            calls.append({'prompt': prompt, 'kwargs': kwargs})
            yield Image(_png_bytes())

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 't2img'
        assert service_key == 'default'
        return FakeT2ImgService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/t2img/service/default/openai/v1/images/generations', json={
            'prompt': 'draw mountains',
            'stream': True,
            'response_format': 'b64_json',
            'output_format': 'png',
        })

    assert response.status_code == 200
    events = [line.removeprefix('data: ') for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1] == '[DONE]'
    payload = json.loads(events[0])
    assert payload['data'][0]['b64_json']
    assert calls[0]['prompt'] == 'draw mountains'
    assert calls[0]['kwargs']['stream'] is True


def test_openai_liked_t2img_generation_route_forwards_extra_params(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2ImgService:
        async def generate(self, prompt: str, **kwargs: Any) -> Image:
            calls.append({'prompt': prompt, 'kwargs': kwargs})
            return Image(_png_bytes())

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 't2img'
        return FakeT2ImgService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post('/ai/t2img/service/default/openai/v1/images/generations', json={
            'prompt': 'draw a cat',
            'partial_images': 2,
            'moderation': 'low',
            'seed': 123,
            'response_format': 'url',
            'output_format': 'webp',
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload['data'][0]['url'].startswith('data:image/')
    assert payload['output_format'] == 'webp'
    assert calls[0]['kwargs']['partial_images'] == 2
    assert calls[0]['kwargs']['moderation'] == 'low'
    assert calls[0]['kwargs']['seed'] == 123
    assert 'response_format' not in calls[0]['kwargs']
    assert 'output_format' not in calls[0]['kwargs']


def test_openai_liked_t2img_edit_service_route_parses_multipart(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeT2ImgService:
        async def edit(self, image: Image, prompt: str, **kwargs: Any) -> Image:
            calls.append({'image': image, 'prompt': prompt, 'kwargs': kwargs})
            return Image(_png_bytes())

    async def fake_resolve(kind: str, service_key: str | None) -> Any:
        assert kind == 't2img'
        assert service_key == 'default'
        return FakeT2ImgService()

    monkeypatch.setattr(ai_api, '_resolve_ai_service_instance', fake_resolve)

    with TestClient(_openai_liked_app()) as client:
        response = client.post(
            '/ai/t2img/service/default/openai/v1/images/edits',
            data={
                'prompt': 'make it blue',
                'n': '1',
                'size': '1024x1024',
                'client_key': 't2img:client-a',
            },
            files={'image': ('image.png', _png_bytes(), 'image/png')},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload['data'][0]['b64_json']
    assert calls[0]['prompt'] == 'make it blue'
    assert isinstance(calls[0]['image'], Image)
    assert calls[0]['kwargs']['count'] == 1
    assert calls[0]['kwargs']['size'] == '1024x1024'
    assert calls[0]['kwargs']['client_key'] == 't2img:client-a'