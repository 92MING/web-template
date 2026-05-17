import asyncio
import contextlib
import io
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Annotated, get_args, get_origin
from unittest.mock import patch

from pydantic import BaseModel

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from thinkthinksyn import ThinkThinkSyn

from core.ai.completion import CompletionClient, CompletionService, OpenAILikedCompletionClient
from core.ai.completion import ThinkThinkSynCompletionClient
from core.ai.embedding import EmbeddingClient, EmbeddingService
from core.ai.s2t import S2TClient
from core.ai.t2s import T2SClient
from core.ai._multimodal_token_utils import (
    estimate_audio_tokens,
    trim_audio_to_token_budget,
    trim_video_to_token_budget,
)
from core.utils.data_structs import Audio, Image, Video


@contextlib.contextmanager
def _patch_annotated_timeout(td_cls: type, key: str, new_default):
    """Temporarily replace the Annotated default for *key* in *td_cls*."""
    original = td_cls.__annotations__[key]
    args = get_args(original)
    # Annotated[type, default] -> Annotated[type, new_default]
    td_cls.__annotations__[key] = Annotated[args[0], new_default]
    try:
        yield
    finally:
        td_cls.__annotations__[key] = original


def _make_test_image(size: tuple[int, int] = (512, 512)) -> Image:
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new('RGB', size, color=(240, 240, 240)).save(buf, format='PNG')
    return Image(buf.getvalue())


def _make_test_audio(duration_seconds: float = 1.0, sample_rate: int = 16000) -> Audio:
    frame_count = max(1, int(duration_seconds * sample_rate))
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        silence_frame = struct.pack('<h', 0)
        wav_file.writeframes(silence_frame * frame_count)
    return Audio(buf.getvalue())


def _make_test_video(duration_seconds: float = 3.0, fps: float = 6.0, size: tuple[int, int] = (64, 64)) -> Video:
    import cv2  # type: ignore
    import numpy as np

    frame_count = max(1, int(round(duration_seconds * fps)))
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
        tmp_path = Path(tmp_file.name)

    try:
        writer = cv2.VideoWriter(
            str(tmp_path),
            cv2.VideoWriter_fourcc(*'mp4v'),
            fps,
            size,
        )
        if not writer.isOpened():
            raise RuntimeError('VideoWriter open failed')
        try:
            for idx in range(frame_count):
                value = int((idx * 255) / max(1, frame_count - 1))
                frame = np.full((size[1], size[0], 3), value, dtype=np.uint8)
                writer.write(frame)
        finally:
            writer.release()
        return Video(tmp_path.read_bytes())
    finally:
        tmp_path.unlink(missing_ok=True)


class DummyEmbeddingClient(EmbeddingClient):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_inputs = None

    async def _embedding_impl(self, inputs, **kwargs):
        self.last_inputs = list(inputs)
        return [[float(i + 1), float(i + 2)] for i, _ in enumerate(inputs)]


class SlowEmbeddingClient(EmbeddingClient):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_kwargs = None

    async def _embedding_impl(self, inputs, **kwargs):
        self.last_kwargs = dict(kwargs)
        await asyncio.sleep(0.05)
        return [[0.0] for _ in inputs]


class DummyCompletionClient(CompletionClient):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_messages = None
        self.last_kwargs = None

    async def _complete_impl(self, **kwargs):
        self.last_kwargs = dict(kwargs)
        self.last_messages = kwargs.get('messages')
        return 'ok'

    async def _stream_complete_impl(self, **kwargs):
        self.last_kwargs = dict(kwargs)
        self.last_messages = kwargs.get('messages')
        yield {'data': 'ok', 'type': 'text'}


class JsonResponseCompletionClient(DummyCompletionClient):

    def __init__(self, response_text: str, **kwargs):
        super().__init__(**kwargs)
        self.response_text = response_text

    async def _complete_impl(self, **kwargs):
        self.last_kwargs = dict(kwargs)
        self.last_messages = kwargs.get('messages')
        return self.response_text


def _message_text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(part for part in content if isinstance(part, str))
    return str(content)


class SlowS2TClient(S2TClient):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_kwargs = None

    async def _s2t_impl(self, audio, **kwargs):
        self.last_kwargs = dict(kwargs)
        await asyncio.sleep(0.05)
        return 'ok'


class SlowT2SClient(T2SClient):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_kwargs = None
        self.last_stream_kwargs = None

    async def _t2s_impl(self, text, **kwargs):
        self.last_kwargs = dict(kwargs)
        await asyncio.sleep(0.05)
        return _make_test_audio(0.1)

    async def _t2s_stream_impl(self, text, *, chunk_size=16384, **kwargs):
        self.last_stream_kwargs = dict(kwargs, chunk_size=chunk_size)
        await asyncio.sleep(0.05)
        yield b'ok'


class FakeS2TService:

    async def s2t(self, audio, **kwargs):
        return 'brief'


class TestMultimodalTokenCounting(unittest.TestCase):

    def test_completion_service_client_key_pins_specific_client(self):
        async def _run() -> None:
            client_a = DummyCompletionClient(key='client-a')
            client_b = DummyCompletionClient(key='client-b')
            service = CompletionService(client_a, client_b)

            try:
                result = await service.complete(
                    messages=[{'role': 'user', 'content': 'Say hello'}],
                    client_key=client_b.key,
                )

                self.assertEqual(result, 'ok')
                self.assertIsNone(client_a.last_kwargs)
                self.assertIsNotNone(client_b.last_kwargs)
                self.assertNotIn('client_key', client_b.last_kwargs)
            finally:
                service.close()

        asyncio.run(_run())

    def test_embedding_service_client_key_pins_specific_client(self):
        async def _run() -> None:
            client_a = DummyEmbeddingClient(key='client-a')
            client_b = DummyEmbeddingClient(key='client-b')
            with patch.object(EmbeddingService, '_start_init_probe', lambda self: None):
                service = EmbeddingService(client_a, client_b)

            try:
                result = await service.embedding(
                    'hello world',
                    client_key=client_b.key,
                    use_cache=False,
                    save_cache=False,
                )

                self.assertEqual(len(result), 2)
                self.assertGreater(result[0], 0.0)
                self.assertGreater(result[1], 0.0)
                self.assertIsNone(client_a.last_inputs)
                self.assertEqual(client_b.last_inputs, ['hello world'])
            finally:
                service.close()

        asyncio.run(_run())

    def test_json_complete_reasoning_true_uses_prompt_schema_without_hard_json_schema(self):
        class _Resp(BaseModel):
            text: str

        async def _run() -> None:
            client = JsonResponseCompletionClient('Thought carefully.\n```json\n{"text":"ok"}\n```')
            service = CompletionService(client)

            try:
                result = await service.json_complete(
                    'Return text ok.',
                    return_type=_Resp,
                    stream=False,
                    reasoning=True,
                )

                self.assertEqual(result.text, 'ok')
                self.assertIsNotNone(client.last_kwargs)
                self.assertTrue(client.last_kwargs['reasoning'])
                self.assertNotIn('json_schema', client.last_kwargs)

                self.assertIsNotNone(client.last_messages)
                last_message = client.last_messages[-1]
                content = _message_text_content(last_message['content'])
                self.assertIn('First think carefully', content)
                self.assertIn('```json', content)
                self.assertIn('"text": "text"', content)
                self.assertIn('"type": "object"', content)
            finally:
                service.close()

        asyncio.run(_run())

    def test_json_complete_reasoning_none_keeps_hard_json_schema(self):
        class _Resp(BaseModel):
            text: str

        async def _run() -> None:
            client = JsonResponseCompletionClient('{"text":"ok"}')
            service = CompletionService(client)

            try:
                result = await service.json_complete(
                    'Return text ok.',
                    return_type=_Resp,
                    stream=False,
                    reasoning=None,
                )

                self.assertEqual(result.text, 'ok')
                self.assertIsNotNone(client.last_kwargs)
                self.assertIn('json_schema', client.last_kwargs)
                self.assertFalse(client.last_kwargs['reasoning'])

                self.assertIsNotNone(client.last_messages)
                last_message = client.last_messages[-1]
                content = _message_text_content(last_message['content'])
                self.assertIn('Return the valid json response only', content)
                self.assertNotIn('First think carefully', content)
            finally:
                service.close()

        asyncio.run(_run())

    def test_json_complete_support_json_false_uses_prompt_schema_without_hard_json_schema(self):
        class _Resp(BaseModel):
            text: str

        async def _run() -> None:
            client = JsonResponseCompletionClient('```json\n{"text":"ok"}\n```', support_json=False)
            service = CompletionService(client)

            try:
                result = await service.json_complete(
                    'Return text ok.',
                    return_type=_Resp,
                    stream=False,
                    reasoning=False,
                )

                self.assertEqual(result.text, 'ok')
                self.assertIsNotNone(client.last_kwargs)
                self.assertNotIn('json_schema', client.last_kwargs)
                self.assertFalse(client.last_kwargs['reasoning'])

                self.assertIsNotNone(client.last_messages)
                last_message = client.last_messages[-1]
                content = _message_text_content(last_message['content'])
                self.assertIn('wrapped inside a ```json fenced block', content)
                self.assertIn('A default example of the expected JSON shape is', content)
                self.assertIn('```json', content)
                self.assertIn('"text": "text"', content)
                self.assertNotIn('First think carefully', content)
            finally:
                service.close()

        asyncio.run(_run())

    def test_embedding_count_tokens_accepts_multimodal_and_custom_counter(self):
        image = _make_test_image((1024, 1024))
        audio = _make_test_audio(1.5)

        default_client = DummyEmbeddingClient()
        self.assertGreaterEqual(default_client.count_tokens(image), 256)
        self.assertEqual(default_client.count_tokens(audio), math.ceil(1.5 * 12.0))

        custom_client = DummyEmbeddingClient(token_counter=lambda value: 777 if not isinstance(value, str) else 3)
        self.assertEqual(custom_client.count_tokens(image), 777)
        self.assertEqual(custom_client.count_tokens(audio), 777)

    def test_default_token_estimates_follow_requested_boundaries(self):
        min_image = _make_test_image((224, 224))
        max_image = _make_test_image((1024, 1024))
        short_audio = _make_test_audio(0.2)

        client = DummyEmbeddingClient()
        self.assertEqual(client.count_tokens(min_image), 256)
        self.assertEqual(client.count_tokens(max_image), 4096)
        self.assertEqual(estimate_audio_tokens(short_audio), 12)

    def test_completion_client_default_max_tokens(self):
        default_client = OpenAILikedCompletionClient(apikey='x', base_url='https://example.com/v1', model='gpt-4.1-mini')
        omni_client = OpenAILikedCompletionClient(apikey='x', base_url='https://example.com/v1', model='gpt-4o-mini')
        qwen_client = OpenAILikedCompletionClient(apikey='x', base_url='https://example.com/v1', model='qwen/qwen3.5-122b-a10b')

        self.assertEqual(default_client.max_tokens, 100 * 1024)
        self.assertEqual(omni_client.max_tokens, 100 * 1024)
        self.assertEqual(qwen_client.max_tokens, 260000)

    def test_completion_service_token_fit_preserves_tail_audio(self):
        async def _run() -> None:
            client = DummyCompletionClient(max_tokens=20, max_audios=None, max_images=0, max_videos=0)
            service = CompletionService(client, s2t_service=FakeS2TService())

            audio1 = _make_test_audio(1.0)
            audio2 = _make_test_audio(1.0)
            await service.complete(messages=[{'role': 'user', 'content': ['hello', audio1, audio2]}])

            self.assertIsNotNone(client.last_messages)
            msg = client.last_messages[0]
            content = msg['content']
            self.assertIsInstance(content, list)
            self.assertEqual(content[0], 'hello')
            self.assertEqual(content[1], 'brief')
            self.assertIsInstance(content[2], Audio)
            service.close()

        asyncio.run(_run())

    def test_completion_service_complete_defaults_reasoning_false(self):
        async def _run() -> None:
            client = DummyCompletionClient()
            service = CompletionService(client)

            try:
                await service.complete(messages=[{'role': 'user', 'content': 'hello'}])

                self.assertIsNotNone(client.last_kwargs)
                self.assertIn('reasoning', client.last_kwargs)
                self.assertFalse(client.last_kwargs['reasoning'])
                self.assertEqual(client.last_kwargs['timeout'], 180.0)
            finally:
                service.close()

        asyncio.run(_run())

    def test_completion_service_stream_defaults_reasoning_false(self):
        async def _run() -> None:
            client = DummyCompletionClient()
            service = CompletionService(client)

            try:
                chunks = [chunk async for chunk in service.stream_complete(messages=[{'role': 'user', 'content': 'hello'}])]

                self.assertEqual('ok', ''.join(chunk['data'] for chunk in chunks))
                self.assertIsNotNone(client.last_kwargs)
                self.assertIn('reasoning', client.last_kwargs)
                self.assertFalse(client.last_kwargs['reasoning'])
                self.assertEqual(client.last_kwargs['timeout'], 180.0)
            finally:
                service.close()

        asyncio.run(_run())

    def test_openai_liked_payload_defaults_reasoning_false(self):
        async def _run() -> None:
            client = OpenAILikedCompletionClient(apikey='x', base_url='https://example.com/v1', model='gpt-4.1-mini')
            payload = await client._build_payload({'messages': [{'role': 'user', 'content': 'hello'}]}, stream=False)

            self.assertIn('reasoning', payload)
            self.assertEqual(payload['reasoning'], {'enabled': False})

        asyncio.run(_run())

    def test_thinkthinksyn_payload_defaults_reasoning_false(self):
        async def _run() -> None:
            client = ThinkThinkSynCompletionClient(ThinkThinkSyn(base_url='https://example.com/tts/ai', apikey='x'))
            payload = await client._build_payload({'messages': [{'role': 'user', 'content': 'hello'}]})

            self.assertIn('reasoning', payload)
            self.assertFalse(payload['reasoning'])

        asyncio.run(_run())

    def test_embedding_client_applies_default_timeout_without_forwarding_timeout_kwarg(self):
        from core.ai.embedding import _EmbeddingRequestParams

        async def _run() -> None:
            client = SlowEmbeddingClient()

            with _patch_annotated_timeout(_EmbeddingRequestParams, 'timeout', 0.01):
                with self.assertRaises(asyncio.TimeoutError):
                    await client.embedding(['hello'])

            self.assertIsNotNone(client.last_kwargs)
            self.assertNotIn('timeout', client.last_kwargs)

        asyncio.run(_run())

    def test_s2t_client_applies_default_timeout_without_forwarding_timeout_kwarg(self):
        from core.ai.s2t import _S2TParams

        async def _run() -> None:
            client = SlowS2TClient()

            with _patch_annotated_timeout(_S2TParams, 'timeout', 0.01):
                with self.assertRaises(asyncio.TimeoutError):
                    await client.s2t(_make_test_audio())

            self.assertIsNotNone(client.last_kwargs)
            self.assertNotIn('timeout', client.last_kwargs)

        asyncio.run(_run())

    def test_t2s_client_applies_default_timeout_without_forwarding_timeout_kwarg(self):
        from core.ai.t2s import _T2SParams

        async def _run() -> None:
            client = SlowT2SClient()

            with _patch_annotated_timeout(_T2SParams, 'timeout', 0.01):
                with self.assertRaises(asyncio.TimeoutError):
                    await client.t2s('hello')

            self.assertIsNotNone(client.last_kwargs)
            self.assertNotIn('timeout', client.last_kwargs)

        asyncio.run(_run())

    def test_t2s_stream_applies_default_timeout_without_forwarding_timeout_kwarg(self):
        from core.ai.t2s import _T2SParams

        async def _run() -> None:
            client = SlowT2SClient()

            with _patch_annotated_timeout(_T2SParams, 'timeout', 0.01):
                with self.assertRaises(asyncio.TimeoutError):
                    async for _chunk in client.t2s_stream('hello'):
                        pass

            self.assertIsNotNone(client.last_stream_kwargs)
            self.assertNotIn('timeout', client.last_stream_kwargs)

        asyncio.run(_run())

    def test_trim_audio_to_token_budget_preserves_tail(self):
        audio = _make_test_audio(5.0)
        trimmed = trim_audio_to_token_budget(audio, 12)

        self.assertIsInstance(trimmed, Audio)
        self.assertLessEqual(DummyCompletionClient().count_tokens(trimmed), 12)
        self.assertLess(DummyCompletionClient().count_tokens(trimmed), DummyCompletionClient().count_tokens(audio))

    def test_completion_service_trims_last_audio_before_request(self):
        async def _run() -> None:
            client = DummyCompletionClient(max_tokens=20, max_audios=None, max_images=0, max_videos=0)
            service = CompletionService(client, s2t_service=FakeS2TService())

            long_audio = _make_test_audio(5.0)
            await service.complete(messages=[{'role': 'user', 'content': ['hello', long_audio]}])

            self.assertIsNotNone(client.last_messages)
            content = client.last_messages[0]['content']
            self.assertIsInstance(content, list)
            self.assertEqual(content[0], 'hello')
            self.assertTrue(any(isinstance(part, Audio) for part in content[1:]))
            self.assertTrue(any(isinstance(part, str) and part == 'brief' for part in content[1:-1]))
            tail_audio = next(part for part in reversed(content) if isinstance(part, Audio))
            self.assertLessEqual(client.count_tokens(tail_audio), client.max_tokens)
            service.close()

        asyncio.run(_run())

    def test_trim_video_to_token_budget_reduces_estimate(self):
        video = _make_test_video(4.0)
        trimmed = trim_video_to_token_budget(video, 12)

        self.assertIsInstance(trimmed, Video)
        self.assertLessEqual(DummyCompletionClient().count_tokens(trimmed), 12)
        self.assertLess(DummyCompletionClient().count_tokens(trimmed), DummyCompletionClient().count_tokens(video))

    def test_trim_video_to_token_budget_can_reduce_high_resolution_video(self):
        video = _make_test_video(4.0, fps=6.0, size=(1920, 1080))
        trimmed = trim_video_to_token_budget(video, 40)

        self.assertIsInstance(trimmed, Video)
        self.assertLessEqual(DummyCompletionClient().count_tokens(trimmed), 40)
        self.assertLess(DummyCompletionClient().count_tokens(trimmed), DummyCompletionClient().count_tokens(video))

    def test_completion_service_trims_last_video_before_request(self):
        async def _run() -> None:
            client = DummyCompletionClient(max_tokens=20, max_videos=None, max_images=0, max_audios=0)
            service = CompletionService(client, s2t_service=FakeS2TService())

            long_video = _make_test_video(5.0)
            await service.complete(messages=[{'role': 'user', 'content': ['hello', long_video]}])

            self.assertIsNotNone(client.last_messages)
            content = client.last_messages[0]['content']
            self.assertIsInstance(content, list)
            self.assertEqual(content[0], 'hello')
            self.assertTrue(any(isinstance(part, Video) for part in content[1:]))
            tail_video = next(part for part in reversed(content) if isinstance(part, Video))
            self.assertLessEqual(client.count_tokens(tail_video), client.max_tokens)
            service.close()

        asyncio.run(_run())

    def test_completion_service_preserves_tail_video_and_transcribes_prefix_video(self):
        async def _run() -> None:
            client = DummyCompletionClient(max_tokens=20, max_videos=None, max_images=0, max_audios=0)
            service = CompletionService(client, s2t_service=FakeS2TService())

            video1 = _make_test_video(5.0)
            video2 = _make_test_video(5.0)
            await service.complete(messages=[{'role': 'user', 'content': ['hello', video1, video2]}])

            self.assertIsNotNone(client.last_messages)
            content = client.last_messages[0]['content']
            self.assertIsInstance(content, list)
            self.assertEqual(content[0], 'hello')
            self.assertTrue(any(isinstance(part, str) and part == 'brief' for part in content[1:-1]))
            self.assertIsInstance(content[-1], Video)
            self.assertLessEqual(client.count_tokens(client.last_messages), client.max_tokens)
            service.close()

        asyncio.run(_run())

    def test_embedding_service_trims_supported_video_before_embedding(self):
        async def _run() -> None:
            client = DummyEmbeddingClient(max_tokens=20, support_video=True)
            service = EmbeddingService(client)

            long_video = _make_test_video(5.0)
            await service.embedding(long_video)

            self.assertIsNotNone(client.last_inputs)
            self.assertTrue(client.last_inputs)
            self.assertTrue(all(isinstance(item, Video) for item in client.last_inputs))
            self.assertTrue(all(client.count_tokens(item) <= client.max_tokens for item in client.last_inputs))

        asyncio.run(_run())


if __name__ == '__main__':
    unittest.main()