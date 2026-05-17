import time
import asyncio
import json
import hashlib
import inspect
import importlib.util
import logging
import sys
import types
import aiohttp
from pydub import AudioSegment

from functools import cache
from pathlib import Path
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname, urlopen
from typing_extensions import Unpack
from typing import TYPE_CHECKING, Any, AsyncGenerator, ClassVar, Iterable, Protocol, cast, TypedDict, Self
from thinkthinksyn import ThinkThinkSyn

from core.storage.object import OBS_Object
from core.utils.concurrent_utils import run_any_func
from core.utils.data_structs import Audio
from .base import (
    ProbeInterval,
    ServiceClient,
    ServiceClientBase,
    ServiceInitParams,
    ServiceClientInitParams,
    ServiceParamsBase,
    ServiceBase,
    ConcurrentPool,
    _AnnotateDefault,
    _apply_service_param_defaults,
    _patch_thinkthinksyn_proxy,
    _create_proxied_thinkthinksyn,
    _apply_ssh_tunnel_to_tts_client,
    _resolve_ssh_tunnel_config,
    thinkthinksyn_client,
    OpenAILikedClientCreateParams,
    OpenRouterClientCreateParams,
    OpenAILikedClientMixin,
    _env_first,
    _resolve_openai_liked_client_params,
    _resolve_openrouter_client_params,
    _append_default_client,
    _append_env_default_client,
)
from .shared import AIServiceKind

__all__: list[str] = []
_logger = logging.getLogger(__name__)
_DEFAULT_T2S_TIMEOUT = 120.0
'''默认 T2S 请求超时（秒）。'''

def _speech_response_audio(data: bytes, content_type: str | None) -> Audio:
    normalized_content_type = str(content_type or '').lower()
    if normalized_content_type.startswith('audio/pcm'):
        params: dict[str, str] = {}
        for part in normalized_content_type.split(';')[1:]:
            if '=' in part:
                key, value = part.split('=', 1)
                params[key.strip()] = value.strip()
        frame_rate = int(params.get('rate') or 24000)
        channels = int(params.get('channels') or 1)
        segment = AudioSegment(
            data=data,
            sample_width=2,
            frame_rate=frame_rate,
            channels=channels,
        )
        return Audio(segment)
    return Audio(data)

class _T2SParams(ServiceParamsBase, total=False):
    '''T2S 请求参数。'''
    timeout: _AnnotateDefault[float | None, _DEFAULT_T2S_TIMEOUT]
    '''请求超时（秒）。默认 120 秒。'''
    client_key: str | None
    '''固定使用指定的 service-attached client key；``None`` 表示仍由 service 自动调度。'''

if TYPE_CHECKING:
    class T2SParams(_T2SParams, extra_items=object):
        '''T2S 请求参数。'''
else:
    T2SParams = _T2SParams

class T2SHealthProbeInput(TypedDict):
    '''T2S 健康探测最小输入。'''

    text: str
    '''用于最小探测的输入文本。'''

    kwargs: T2SParams
    '''探测时附带的额外参数。'''

class _T2SClientInitParams(ServiceClientInitParams, total=False):
    '''T2S 客户端初始化参数。'''

if TYPE_CHECKING:
    class T2SClientInitParams(_T2SClientInitParams, extra_items=object):
        '''T2S 客户端初始化参数。'''
else:
    T2SClientInitParams = _T2SClientInitParams

class OpenAILikedT2SClientCreateParams(OpenAILikedClientCreateParams, _T2SClientInitParams, total=False):
    '''OpenAI-Liked T2S 客户端创建参数。'''

class OpenRouterT2SClientCreateParams(OpenRouterClientCreateParams, _T2SClientInitParams, total=False):
    '''OpenRouter T2S 客户端创建参数。'''

class ThinkThinkSynT2SClientCreateParams(_T2SClientInitParams, total=False):
    '''ThinkThinkSyn T2S 客户端创建参数。'''
    apikey: str | None
    base_url: str | None
    model: str | None

class T2SClient(ServiceClientBase[T2SHealthProbeInput]):

    ServiceKind: ClassVar['AIServiceKind'] = 't2s'
    '''文本转语音客户端抽象基类。'''

    def __init__(self, **kwargs: Unpack[T2SClientInitParams]):
        '''初始化 T2S 客户端。

        Args:
            **kwargs: 客户端初始化参数，结构见 `T2SClientInitParams`。
        '''
        super().__init__(**kwargs)

    @classmethod
    @cache
    def TestingInput(cls) -> T2SHealthProbeInput:
        '''返回最小健康探测输入。

        Returns:
            适用于 T2S 最小可用性检测的输入参数。
        '''
        return {
            'text': 'ok',
            'kwargs': {'timeout': 8.0},
        }

    async def probe_min_health(self) -> bool:
        '''执行最小健康探测。

        Returns:
            成功返回 `Audio` 对象时为 `True`。
        '''
        try:
            probe = type(self).TestingInput()
            output = await self.t2s(probe['text'], __skip_log__=True, **probe.get('kwargs', {}))
            return isinstance(output, Audio)
        except Exception:
            return False

    @staticmethod
    def _extract_common_client_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        return {
            'key': kwargs.get('key'),
            'max_concurrent': kwargs.get('max_concurrent'),
            'priority': kwargs.get('priority', 0.0),
            'strategy_lvl': kwargs.get('strategy_lvl', 0),
        }

    @classmethod
    def CreateOpenAILikedT2SClient(
        cls,
        **kwargs: Unpack[OpenAILikedT2SClientCreateParams],
    ) -> 'T2SClient':
        client_kwargs = cls._extract_common_client_kwargs(cast(dict[str, Any], kwargs))
        client_kwargs.update(_resolve_openai_liked_client_params(kwargs, service_name='t2s'))
        return OpenAILikedT2SClient(**client_kwargs)

    @classmethod
    def CreateThinkThinkSynT2SClient(
        cls,
        **kwargs: Unpack[ThinkThinkSynT2SClientCreateParams],
    ) -> 'T2SClient':
        init_params: dict[str, Any] = {}
        if kwargs.get('apikey'):
            init_params['apikey'] = kwargs['apikey']
        if kwargs.get('base_url'):
            init_params['base_url'] = kwargs['base_url']
        tts_client = _create_proxied_thinkthinksyn(**init_params) if init_params else thinkthinksyn_client()
        client_kwargs = cls._extract_common_client_kwargs(cast(dict[str, Any], kwargs))
        if 'model' in kwargs:
            client_kwargs['model'] = kwargs['model']
        return ThinkThinkSynT2SClient(tts_client=tts_client, **client_kwargs)

    @classmethod
    def CreateOpenRouterT2SClient(
        cls,
        **kwargs: Unpack[OpenRouterT2SClientCreateParams],
    ) -> 'T2SClient':
        client_kwargs = cls._extract_common_client_kwargs(cast(dict[str, Any], kwargs))
        client_kwargs.update(_resolve_openrouter_client_params(kwargs, service_name='t2s'))
        return OpenRouterT2SClient(**client_kwargs)

    async def t2s(self, text: str, **kwargs: Unpack[T2SParams]) -> Audio:
        '''执行文本转语音。

        Args:
            text: 待合成的文本。
            **kwargs: 传递给底层客户端的附加参数。

        Returns:
            合成后的音频对象。
        '''
        exec_kwargs = dict(kwargs)
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, _T2SParams)
        req_timeout = float(exec_kwargs.pop('timeout'))     # type: ignore
        request = self._log_request_payload('t2s', (text,), dict(exec_kwargs))
        metadata = self._log_extra_metadata('t2s', (text,), dict(exec_kwargs))
        return cast(
            Audio,
            await self._trace_async_call(
                't2s',
                lambda: asyncio.wait_for(self._t2s_impl(text, **exec_kwargs), timeout=req_timeout),
                request=request,
                metadata=metadata,
                skip_log=skip_log,
            ),
        )

    async def _t2s_impl(self, text: str, **kwargs: object) -> Audio:
        raise NotImplementedError

    async def t2s_stream(self, text: str, *, chunk_size: int = 16384, **kwargs: Unpack[T2SParams]) -> AsyncGenerator[bytes, None]:
        '''以字节流方式执行文本转语音。

        默认实现会优先调用客户端的流式能力，若底层不支持则退回到
        `t2s()` 结果并按块切分输出，确保前端始终可使用流式播放/下载链路。
        '''
        exec_kwargs = dict(kwargs)
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, _T2SParams)
        req_timeout = float(exec_kwargs.pop('timeout'))     # type: ignore
        exec_chunk_size = max(1024, int(exec_kwargs.pop('chunk_size', chunk_size or 16384)))    # type: ignore
        request = self._log_request_payload('t2s_stream', (text,), dict(exec_kwargs, chunk_size=exec_chunk_size))
        metadata = self._log_extra_metadata('t2s_stream', (text,), dict(exec_kwargs, chunk_size=exec_chunk_size))
        started_at = asyncio.get_running_loop().time()
        total_bytes = 0
        deadline = time.monotonic() + req_timeout
        ttft_deadline = time.monotonic() + self._STREAM_TTFT_TIMEOUT
        first_chunk_received = False
        try:
            stream_iter = self._t2s_stream_impl(text, chunk_size=exec_chunk_size, **exec_kwargs).__aiter__()
            while True:
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError('T2S stream timed out')
                    if not first_chunk_received:
                        ttft_remaining = ttft_deadline - time.monotonic()
                        if ttft_remaining <= 0:
                            raise asyncio.TimeoutError(f'T2S stream first chunk timed out ({self._STREAM_TTFT_TIMEOUT}s)')
                        chunk = await asyncio.wait_for(stream_iter.__anext__(), timeout=min(remaining, ttft_remaining))
                        first_chunk_received = True
                    else:
                        chunk = await asyncio.wait_for(stream_iter.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                total_bytes += len(chunk)
                yield chunk
        except Exception as exc:
            if not skip_log:
                self._record_call_log(
                    operation='t2s_stream',
                    started_at=started_at,
                    success=False,
                    request=request,
                    error=exc,
                    metadata=metadata,
                )
            raise

        if not skip_log:
            self._record_call_log(
                operation='t2s_stream',
                started_at=started_at,
                success=True,
                request=request,
                response={'streamed_bytes': total_bytes, 'chunk_size': exec_chunk_size},
                metadata=metadata,
            )

    async def _t2s_stream_impl(self, text: str, *, chunk_size: int = 16384, **kwargs: object) -> AsyncGenerator[bytes, None]:
        audio = await self.t2s(text, **kwargs)
        data = audio.to_bytes()
        for idx in range(0, len(data), max(1024, chunk_size)):
            yield data[idx: idx + max(1024, chunk_size)]


class ThinkThinkSynT2SClient(T2SClient, type='thinkthinksyn'):
    '''ThinkThinkSyn 文本转语音客户端。'''

    @classmethod
    def CreateFromConfig(cls, **kwargs: object) -> 'Self':
        return cast(Self, T2SClient.CreateThinkThinkSynT2SClient(**cast(Any, kwargs)))

    def __init__(
        self,
        tts_client: 'ThinkThinkSyn',
        model: str | None = None,
        ssh_tunnel: object | None = None,
        **kwargs: Unpack[T2SClientInitParams],
    ):
        super().__init__(**kwargs)
        _ssh = _resolve_ssh_tunnel_config(ssh_tunnel)
        if _ssh:
            _apply_ssh_tunnel_to_tts_client(tts_client, _ssh)
        self._tts_client = _patch_thinkthinksyn_proxy(tts_client)
        self._model = model

    def update(self, **new_params: object) -> bool:
        params = dict(new_params)
        model = params.pop('model', None) if 'model' in params else None
        old_model = self._model
        if not super().update(**params):
            return False
        if 'model' in new_params:
            self._model = None if model is None else str(model)
            if self._model != old_model:
                self.reset_health_state()
        return True
        
    @property
    def model(self) -> str|None:
        return self._model

    async def _t2s_impl(self, text: str, **kwargs: object) -> Audio:
        session = await self._get_session()
        t2s_func = getattr(self._tts_client, 't2s')
        output = await t2s_func(self.model, text=text, session=session, **kwargs)
        if isinstance(output, Audio):
            return output
        if isinstance(output, dict):
            for key in ('data', 'audio', 'source', 'voice', 'sound', 'url'):
                if key in output and output[key]:
                    return self._coerce_to_audio(output[key])
            raise ValueError(f"T2S returned dict without recognizable audio key: {list(output.keys())}")
        return self._coerce_to_audio(output)

    @staticmethod
    def _coerce_to_audio(value: object) -> Audio:
        """Convert a raw value (base64 string, bytes, etc.) to an Audio object.

        Handles unpad base64 strings that ThinkThinkSyn may return.
        """
        if isinstance(value, Audio):
            return value
        if isinstance(value, (bytes, bytearray, memoryview)):
            return Audio(bytes(value))
        if isinstance(value, str) and len(value) > 64:
            # Likely base64 — ensure proper padding before creating Audio
            import base64 as _b64
            pad = len(value) % 4
            padded = value + '=' * ((4 - pad) % 4)
            try:
                raw = _b64.b64decode(padded)
                return Audio(raw)
            except Exception:
                pass
        return Audio(value)

    @staticmethod
    def _resolve_audio_source(chunk: object) -> Audio:
        """Resolve a chunk to an Audio object, handling dict payloads from ThinkThinkSyn."""
        if isinstance(chunk, Audio):
            return chunk
        if isinstance(chunk, dict):
            for key in ('data', 'audio', 'source', 'voice', 'sound', 'url'):
                if key in chunk and chunk[key]:
                    return Audio(chunk[key])
            raise ValueError(f"T2S stream chunk dict without recognizable audio key: {list(chunk.keys())}")
        return Audio(chunk)

    async def _t2s_stream_impl(self, text: str, *, chunk_size: int = 16384, **kwargs: object) -> AsyncGenerator[bytes, None]:
        stream_func = getattr(self._tts_client, 'stream_t2s', None)
        if callable(stream_func):
            try:
                emit_chunk_size = max(1024, chunk_size)

                def _append_audio_chunks(buffer: list[bytes], value: object) -> None:
                    audio = self._coerce_to_audio(value)
                    data = audio.to_bytes()
                    for idx in range(0, len(data), emit_chunk_size):
                        buffer.append(data[idx: idx + emit_chunk_size])

                session = await self._get_session()
                output = stream_func(self.model, text=text, session=session, **kwargs)
                if hasattr(output, '__aiter__'):
                    buffered_chunks: list[bytes] = []
                    async for chunk in output:  # type: ignore
                        if not chunk:
                            continue
                        if isinstance(chunk, (bytes, bytearray, memoryview)):
                            buffered_chunks.append(bytes(chunk))
                        elif isinstance(chunk, dict):
                            for key in ('data', 'audio', 'source', 'voice', 'sound', 'url'):
                                if key in chunk and chunk[key]:
                                    _append_audio_chunks(buffered_chunks, chunk[key])
                                    break
                            else:
                                raise ValueError(f"T2S stream chunk dict without recognizable audio key: {list(chunk.keys())}")
                        else:
                            _append_audio_chunks(buffered_chunks, chunk)
                    for buffered_chunk in buffered_chunks:
                        yield buffered_chunk
                    return

                if isinstance(output, (bytes, bytearray)):
                    data = bytes(output)
                    for idx in range(0, len(data), emit_chunk_size):
                        yield data[idx: idx + emit_chunk_size]
                    return
                audio = self._coerce_to_audio(output)
                data = audio.to_bytes()
                for idx in range(0, len(data), emit_chunk_size):
                    yield data[idx: idx + emit_chunk_size]
                return
            except Exception:
                # stream_t2s may internally fail (dict-as-FileID, memoryview
                # attribute errors, etc.); fall back to non-streaming path.
                pass

        async for chunk in super()._t2s_stream_impl(text, chunk_size=chunk_size, **kwargs):
            yield chunk


class OpenAILikedT2SClient(T2SClient, OpenAILikedClientMixin, type='openai-liked', alias='openai'):
    '''OpenAI 协议兼容的文本转语音客户端。'''

    @classmethod
    def CreateFromConfig(cls, **kwargs: object) -> 'Self':
        return cast(Self, T2SClient.CreateOpenAILikedT2SClient(**cast(Any, kwargs)))

    def __init__(
        self,
        apikey: str | None,
        base_url: str,
        model: str | None = None,
        ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None' = None,
        **kwargs: Unpack[T2SClientInitParams],
    ):
        super().__init__(**kwargs)
        resolved_model = model or _env_first('OPENAI_T2S_MODEL') or 'tts-1'
        self._init_openai_liked_client(apikey=apikey, base_url=base_url, model=resolved_model, ssh_tunnel=ssh_tunnel)

    def update(self, **new_params: object) -> bool:
        params = dict(new_params)
        openai_params = {key: params.pop(key) for key in ('apikey', 'base_url', 'model') if key in params}
        old_identity = (self._apikey, self._base_url, self._model)
        if not super().update(**params):
            return False
        if 'apikey' in openai_params:
            self._apikey = '' if openai_params['apikey'] is None else str(openai_params['apikey'])
        if 'base_url' in openai_params and openai_params['base_url'] is not None:
            self._base_url = str(openai_params['base_url']).rstrip('/')
        if 'model' in openai_params:
            self._model = None if openai_params['model'] is None else str(openai_params['model'])
        if openai_params and (self._apikey, self._base_url, self._model) != old_identity:
            self.reset_health_state()
        return True

    @property
    def model(self) -> str | None:
        return self._model

    def _speech_url(self) -> str:
        return self._openai_liked_endpoint('/audio/speech')

    def _speech_urls(self) -> list[str]:
        return self._openai_liked_endpoint_candidates('/audio/speech')

    def _build_payload(self, text: str, params: dict[str, object]) -> dict[str, object]:
        payload: dict[str, object] = {
            'model': params.pop('model', None) or self._model or 'tts-1',
            'input': text,
            'voice': params.pop('voice', 'alloy'),
        }
        for key in ('response_format', 'speed', 'instructions'):
            value = params.pop(key, None)
            if value is not None:
                payload[key] = value
        return payload

    async def _request_speech(self, text: str, **kwargs: object) -> aiohttp.ClientResponse:
        params = dict(kwargs)
        timeout = aiohttp.ClientTimeout(total=float(params.pop('timeout', _DEFAULT_T2S_TIMEOUT)))
        payload = self._build_payload(text, params)
        last_not_found: aiohttp.ClientResponseError | None = None
        urls = self._speech_urls()
        for url_index, url in enumerate(urls):
            session = await self._get_session()
            response = await session.post(
                url,
                json=payload,
                headers=self._openai_liked_headers(),
                timeout=timeout,
            )
            try:
                response.raise_for_status()
            except aiohttp.ClientResponseError as exc:
                response.release()
                if exc.status == 404 and url_index < len(urls) - 1:
                    last_not_found = exc
                    continue
                raise
            return response
        if last_not_found is not None:
            raise last_not_found
        raise RuntimeError('OpenAI-liked T2S request failed without response.')

    async def _t2s_impl(self, text: str, **kwargs: object) -> Audio:
        response = await self._request_speech(text, **kwargs)
        try:
            return _speech_response_audio(await response.read(), response.headers.get('Content-Type'))
        finally:
            response.release()

    async def _t2s_stream_impl(self, text: str, *, chunk_size: int = 16384, **kwargs: object) -> AsyncGenerator[bytes, None]:
        response = await self._request_speech(text, **kwargs)
        try:
            async for chunk in response.content.iter_chunked(max(1024, chunk_size)):
                if chunk:
                    yield chunk
        finally:
            response.release()


class OpenRouterT2SClient(OpenAILikedT2SClient, type='openrouter'):
    '''OpenRouter 文本转语音客户端。'''

    @classmethod
    def CreateFromConfig(cls, **kwargs: object) -> 'Self':
        return cast(Self, T2SClient.CreateOpenRouterT2SClient(**cast(Any, kwargs)))

    def __init__(
        self,
        apikey: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None' = None,
        **kwargs: Unpack[T2SClientInitParams],
    ):
        resolved = _resolve_openrouter_client_params(
            {
                'apikey': apikey,
                'base_url': base_url,
                'model': model,
                'ssh_tunnel': ssh_tunnel,
            },
            service_name='t2s',
            model_env_keys=('OPENROUTER_T2S_MODEL',),
            default_model='tts-1',
        )
        super().__init__(
            apikey=cast(str, resolved['apikey']),
            base_url=cast(str, resolved['base_url']),
            model=cast(str | None, resolved['model']),
            ssh_tunnel=cast('SSHTunnelConfig | dict[str, Any] | str | None', resolved['ssh_tunnel']),
            **kwargs,
        )

    def _build_payload(self, text: str, params: dict[str, object]) -> dict[str, object]:
        payload = super()._build_payload(text, params)
        model = str(payload.get('model') or '').lower()
        voice = payload.get('voice')
        if model.startswith('google/gemini-') and 'tts' in model and str(voice).lower() == 'alloy':
            payload['voice'] = 'Kore'
        return payload

    async def _request_speech(self, text: str, **kwargs: object) -> aiohttp.ClientResponse:
        params = dict(kwargs)
        timeout = aiohttp.ClientTimeout(total=float(params.pop('timeout', _DEFAULT_T2S_TIMEOUT)))
        payload = self._build_payload(text, params)
        last_not_found: aiohttp.ClientResponseError | None = None
        urls = self._speech_urls()
        for url_index, url in enumerate(urls):
            session = await self._get_session()
            response = await session.post(
                url,
                json=payload,
                headers=self._openrouter_headers(),
                timeout=timeout,
            )
            try:
                response.raise_for_status()
            except aiohttp.ClientResponseError as exc:
                response.release()
                if exc.status == 404 and url_index < len(urls) - 1:
                    last_not_found = exc
                    continue
                raise
            return response
        if last_not_found is not None:
            raise last_not_found
        raise RuntimeError('OpenRouter T2S request failed without response.')


class T2SService(ServiceBase):
    '''文本转语音聚合服务。'''

    DefaultProbeInterval = ProbeInterval(interval=600.0, decay=2.0, max_interval=86400.0)

    class DefaultThinkThinkSynClientParams:
        '''T2S 默认客户端参数。'''
        XTTS: T2SClientInitParams = {
            'max_concurrent': ConcurrentPool('t2s', 50),
            'model': 'xtts',
        }

    def __init__(self, *clients: T2SClient | ServiceClient[T2SClient], **kwargs: Unpack[ServiceInitParams]):
        '''初始化 T2S 聚合服务。

        Args:
            *clients: 一个或多个 T2S 客户端。
            **kwargs: 服务初始化参数，结构见 `ServiceInitParams`。
        '''
        super().__init__(*clients, **kwargs)

    @classmethod
    def Default(cls) -> Self:
        '''创建默认 T2S 服务。

        Returns:
            使用默认 ThinkThinkSyn 客户端的 T2S 服务实例。
        '''
        cls.WaitUntilRuntimeReady()
        if existing := cls.GetInstance('default'):
            return existing

        # ── Config-driven creation ──────────────────────────────────
        from .config import AIServicesConfig
        cfg = AIServicesConfig.Global()
        if cfg is not None:
            svc = cfg.t2s.get_default()
            if svc is not None:
                cfg.t2s.preload_service_instances()
                return cast(Self, svc)

        # ── Hardcoded / env fallback ──────────────────────────────
        clients: list[T2SClient] = []
        _append_default_client(
            clients,
            lambda: ThinkThinkSynT2SClient(
                tts_client=thinkthinksyn_client(),
                **cls.DefaultThinkThinkSynClientParams.XTTS,
            ),
            logger=_logger,
            description='ThinkThinkSyn T2S',
        )
        _append_env_default_client(
            clients,
            T2SClient.CreateOpenAILikedT2SClient,
            logger=_logger,
            description='OpenAI-compatible T2S',
            env_keys=('OPENAI_APIKEY', 'OPENAI_API_KEY'),
        )
        _append_env_default_client(
            clients,
            T2SClient.CreateOpenRouterT2SClient,
            logger=_logger,
            description='OpenRouter T2S',
            env_keys=('OPENROUTER_APIKEY', 'OPENROUTER_API_KEY'),
        )

        if not clients:
            raise RuntimeError(
                'Cannot create default T2SService: no client could be initialized. '
                'Please ensure thinkthinksyn is installed or set OPENAI_APIKEY / OPENAI_API_KEY / OPENROUTER_APIKEY / OPENROUTER_API_KEY.'
            )
        return cls(*clients, key='default')

    async def t2s(self, text: str, **kwargs: Unpack[T2SParams]) -> Audio:
        '''通过故障转移机制执行文本转语音。

        Args:
            text: 待合成的文本。
            **kwargs: 传递给客户端的附加参数。

        Returns:
            合成后的音频对象。
        '''
        request_kwargs = dict(kwargs)
        selected_client_key = cast(str | None, request_kwargs.pop('client_key', None))

        async def _action(client: T2SClient) -> Audio:
            return await client.t2s(text, **request_kwargs)

        candidate_clients = self._resolve_service_client_candidates(self._clients, selected_client_key)
        return cast(Audio, await self._run_with_failover(candidate_clients, _action, error_prefix='All T2S clients failed'))

    async def t2s_stream(self, text: str, *, chunk_size: int = 16384, **kwargs: Unpack[T2SParams]) -> AsyncGenerator[bytes, None]:
        '''通过客户端故障转移输出流式音频字节（含策略分级、冷却检查和状态追踪）。'''
        self._ensure_recovery_task()
        errors: list[str] = []
        cooldown_blocked: list[T2SClient] = []
        request_kwargs = dict(kwargs)
        selected_client_key = cast(str | None, request_kwargs.pop('client_key', None))
        candidate_clients = self._resolve_service_client_candidates(self._clients, selected_client_key)

        for tier_clients in self._strategy_groups(candidate_clients):
            if not tier_clients:
                continue
            for client in await self._sorted_clients(tier_clients):
                cooldown_until = float(getattr(client, '_state_cooldown_until', 0.0))
                if cooldown_until > time.time():
                    if await self._can_accept(client):
                        cooldown_blocked.append(client)
                    continue
                if not await self._can_accept(client):
                    continue

                streamed = False
                client._state_inflight = int(getattr(client, '_state_inflight', 0)) + 1
                try:
                    async for chunk in client.t2s_stream(text, chunk_size=chunk_size, **request_kwargs):
                        streamed = True
                        yield chunk
                    await self._on_success(client)
                    return
                except Exception as exc:
                    if self._is_non_client_responsibility_error(exc):
                        raise
                    await self._on_fail(client, exc)
                    if streamed:
                        raise
                    errors.append(f'[{self._client_display_name(client)}] {type(exc).__name__}: {exc}')
                finally:
                    client._state_inflight = max(0, int(getattr(client, '_state_inflight', 1)) - 1)

        # Fallback: 有客户端仅因 cooldown 被跳过，清除 cooldown 后强制重试
        if not errors and cooldown_blocked:
            best = cooldown_blocked[0]
            best._state_cooldown_until = 0.0  # type: ignore[attr-defined]
            best._state_inflight = int(getattr(best, '_state_inflight', 0)) + 1  # type: ignore[attr-defined]
            try:
                async for chunk in best.t2s_stream(text, chunk_size=chunk_size, **request_kwargs):
                    yield chunk
                await self._on_success(best)
                return
            except Exception as exc:
                if self._is_non_client_responsibility_error(exc):
                    raise
                await self._on_fail(best, exc)
                errors.append(f'[{self._client_display_name(best)}] {type(exc).__name__}: {exc}')
            finally:
                best._state_inflight = max(0, int(getattr(best, '_state_inflight', 1)) - 1)  # type: ignore[attr-defined]

        raise RuntimeError('All T2S stream clients failed. ' + ' | '.join(errors))


class CustomT2SAdapterProtocol(Protocol):
    '''T2S custom adapter 协议。'''

    def t2s(self, text: str, **kwargs: Unpack[T2SParams]) -> Any: ...


def _is_custom_t2s_adapter(adapter: object) -> bool:
    return callable(getattr(adapter, 't2s', None))


def _custom_t2s_adapter_cache_key(adapter: str | OBS_Object) -> str:
    if isinstance(adapter, OBS_Object):
        payload = adapter.model_dump(mode='python')
        return json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return str(adapter or '').strip()


def _normalize_custom_t2s_adapter(adapter: str | OBS_Object) -> tuple[str, str | Path | OBS_Object]:
    if isinstance(adapter, OBS_Object):
        return 'obs', adapter

    raw = str(adapter or '').strip()
    if not raw:
        raise ValueError('Custom t2s adapter requires a non-empty adapter.')

    parsed = urlparse(raw)
    if parsed.scheme in ('', 'file'):
        if parsed.scheme == 'file':
            file_path = url2pathname(unquote(parsed.path))
            if parsed.netloc and parsed.netloc not in ('', 'localhost'):
                file_path = f'//{parsed.netloc}{file_path}'
            path = Path(file_path)
        else:
            path = Path(raw)
        return 'file', path.expanduser().resolve()
    return 'url', raw


def _custom_t2s_module_name(adapter: str | OBS_Object) -> str:
    digest = hashlib.md5(_custom_t2s_adapter_cache_key(adapter).encode('utf-8')).hexdigest()
    return f'core.ai.custom_t2s_adapter_{digest}'


def _load_t2s_module_from_file(path: Path, module_name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f'Failed to load custom t2s adapter module from {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_t2s_module_from_source(source: str, *, module_name: str, origin: str) -> types.ModuleType:
    module = types.ModuleType(module_name)
    module.__file__ = origin
    sys.modules[module_name] = module
    exec(compile(source, origin, 'exec'), module.__dict__)
    return module


def _load_t2s_module_from_url(adapter: str, module_name: str) -> types.ModuleType:
    with urlopen(adapter, timeout=15) as response:
        source = response.read().decode('utf-8')
    return _load_t2s_module_from_source(source, module_name=module_name, origin=adapter)


def _load_t2s_module_from_obs_object(adapter: OBS_Object, module_name: str) -> types.ModuleType:
    source = run_any_func(adapter._get_bytes)
    if source is None:
        raise FileNotFoundError(f'Custom t2s adapter object not found: {adapter.storage_name}:{adapter.path}')
    if isinstance(source, str):
        source_text = source
    else:
        source_text = bytes(source).decode('utf-8')
    origin = f'obs://{adapter.storage_name}/{adapter.path.lstrip("/")}'
    return _load_t2s_module_from_source(source_text, module_name=module_name, origin=origin)


def load_custom_t2s_adapter_module(adapter: str | OBS_Object) -> types.ModuleType:
    module_name = _custom_t2s_module_name(adapter)
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    source_kind, source = _normalize_custom_t2s_adapter(adapter)
    if source_kind == 'file':
        path = cast(Path, source)
        if not path.is_file():
            raise FileNotFoundError(f'Custom t2s adapter script not found: {path}')
        return _load_t2s_module_from_file(path, module_name)
    if source_kind == 'obs':
        return _load_t2s_module_from_obs_object(cast(OBS_Object, source), module_name)
    return _load_t2s_module_from_url(cast(str, source), module_name)


def instantiate_custom_t2s_adapter(
    *,
    adapter: str | OBS_Object,
    init_kwargs: dict[str, object],
) -> CustomT2SAdapterProtocol:
    module = load_custom_t2s_adapter_module(adapter)
    errors: list[str] = []

    for name, value in sorted(module.__dict__.items(), key=lambda item: item[0]):
        if name.startswith('_'):
            continue
        if not inspect.isclass(value):
            continue
        if getattr(value, '__module__', None) != module.__name__:
            continue
        try:
            instance = value(**init_kwargs)
        except Exception as exc:
            errors.append(f'{name}: init failed with {type(exc).__name__}: {exc}')
            continue
        if _is_custom_t2s_adapter(instance):
            return cast(CustomT2SAdapterProtocol, instance)
        errors.append(f'{name}: does not satisfy {CustomT2SAdapterProtocol.__name__}')

    detail = '; '.join(errors) if errors else 'no top-level class found in module'
    raise TypeError(f'No class in {adapter!r} satisfies {CustomT2SAdapterProtocol.__name__}: {detail}')


async def _resolve_custom_t2s_awaitable(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _iterate_custom_t2s_stream(value: Any) -> AsyncGenerator[Any, None]:
    resolved = await _resolve_custom_t2s_awaitable(value)
    if hasattr(resolved, '__aiter__'):
        async for item in resolved:
            yield item
        return
    if isinstance(resolved, (str, bytes, bytearray, memoryview, dict, Audio)):
        yield resolved
        return
    if isinstance(resolved, Iterable):
        for item in resolved:
            yield item
        return
    raise TypeError(f'Unsupported custom t2s adapter stream value: {type(resolved).__name__}')


async def _call_custom_t2s_override(adapter: object, method_name: str, *args: object, **kwargs: object) -> Any:
    method = getattr(adapter, method_name, None)
    if not callable(method):
        return None
    return await _resolve_custom_t2s_awaitable(method(*args, **kwargs))


def _normalize_custom_t2s_audio(value: object) -> Audio:
    if isinstance(value, dict):
        for key in ('data', 'audio', 'source', 'voice', 'sound', 'url'):
            if key in value and value[key]:
                return ThinkThinkSynT2SClient._coerce_to_audio(value[key])
        raise ValueError(f'T2S adapter returned dict without recognizable audio key: {list(value.keys())}')
    return ThinkThinkSynT2SClient._coerce_to_audio(value)


class CustomT2SClient(T2SClient, type='custom'):
    '''T2S 自定义 adapter 包装器。'''

    _WRAPPER_INIT_FIELDS: ClassVar[frozenset[str]] = frozenset({'key', 'max_concurrent', 'priority', 'strategy_lvl'})

    def __init__(
        self,
        adapter: CustomT2SAdapterProtocol | str | OBS_Object | None = None,
        **kwargs: Any,
    ):
        if isinstance(adapter, (str, OBS_Object)):
            adapter_kwargs = {k: v for k, v in kwargs.items() if k not in self._WRAPPER_INIT_FIELDS}
            wrapper_kwargs = {k: v for k, v in kwargs.items() if k in self._WRAPPER_INIT_FIELDS}
            adapter = instantiate_custom_t2s_adapter(adapter=adapter, init_kwargs=adapter_kwargs)
        else:
            if adapter is None:
                raise ValueError('Custom T2S client requires adapter when adapter instance is not provided.')
            wrapper_kwargs = kwargs
            if not _is_custom_t2s_adapter(adapter):
                raise TypeError(f'Custom T2S adapter instance must define t2s(), got {type(adapter).__name__}')
            adapter = cast(CustomT2SAdapterProtocol, adapter)

        super().__init__(**wrapper_kwargs)
        self._adapter = adapter

    @classmethod
    def TestingInput(cls) -> dict[str, object]:
        return {
            'text': 'ok',
            'kwargs': {'timeout': 8.0},
        }

    async def probe_min_health(self) -> bool:
        override = await _call_custom_t2s_override(self._adapter, 'probe_min_health')
        if override is not None:
            return bool(override)

        testing_input = getattr(type(self._adapter), 'TestingInput', None)
        if callable(testing_input):
            probe = cast(dict[str, Any], testing_input())
            output = await self.t2s(__skip_log__=True, **probe)  # type: ignore[arg-type]
            return isinstance(output, Audio)
        return await super().probe_min_health()

    async def _t2s_impl(self, text: str, **kwargs: object) -> Audio:
        result = await _resolve_custom_t2s_awaitable(self._adapter.t2s(text, **cast(dict[str, Any], kwargs)))
        return _normalize_custom_t2s_audio(result)

    async def _t2s_stream_impl(self, text: str, *, chunk_size: int = 16384, **kwargs: object) -> AsyncGenerator[bytes, None]:
        stream_func = getattr(self._adapter, 't2s_stream', None)
        if callable(stream_func):
            async for chunk in _iterate_custom_t2s_stream(stream_func(text, chunk_size=chunk_size, **kwargs)):
                if isinstance(chunk, (bytes, bytearray, memoryview)):
                    yield bytes(chunk)
                else:
                    yield _normalize_custom_t2s_audio(chunk).to_bytes()
            return
        async for chunk in super()._t2s_stream_impl(text, chunk_size=chunk_size, **kwargs):
            yield chunk

    def close(self, reason: str | None = None) -> None:
        close_func = getattr(self._adapter, 'close', None)
        if callable(close_func):
            try:
                run_any_func(close_func)
            except Exception:
                pass
        super().close(reason=reason)


__all__ += [
    'T2SParams',
    'T2SHealthProbeInput',
    'T2SClientInitParams',
    'OpenAILikedT2SClientCreateParams',
    'OpenRouterT2SClientCreateParams',
    'ThinkThinkSynT2SClientCreateParams',
    'T2SClient',
    'ThinkThinkSynT2SClient',
    'OpenAILikedT2SClient',
    'OpenRouterT2SClient',
    'T2SService',
    'CustomT2SAdapterProtocol',
    'CustomT2SClient',
    'instantiate_custom_t2s_adapter',
    'load_custom_t2s_adapter_module',
]
