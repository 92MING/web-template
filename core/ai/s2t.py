import base64
import json
import asyncio
import hashlib
import inspect
import importlib.util
import logging
import sys
import types
import aiohttp

from pathlib import Path
from functools import cache
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname, urlopen

from typing_extensions import Unpack
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, Self, cast, TypedDict

from core.storage.object import OBS_Object
from core.utils.concurrent_utils import run_any_func
from core.utils.data_structs import Audio, Video
from .base import (
    ServiceClient,
    ServiceClientBase,
    ServiceInitParams,
    ServiceClientInitParams,
    ServiceParamsBase,
    ServiceBase,
    ConcurrentPool,
    _AnnotateDefault,
    _apply_service_param_defaults,
    enter_service_context,
    exit_service_context,
    OpenAILikedClientCreateParams,
    OpenRouterClientCreateParams,
    OpenAILikedClientMixin,
    _env_first,
    _resolve_openai_liked_client_params,
    _resolve_openrouter_client_params,
    _append_default_client,
    _append_env_default_client,
)
from .completion import CompletionService
from .shared import AIServiceKind

if TYPE_CHECKING:
    from core.utils.network_utils.ssh_tunnel import SSHTunnelConfig


__all__ = []
_logger = logging.getLogger(__name__)
_DEFAULT_S2T_TIMEOUT = 90.0
'''默认 S2T 请求超时（秒）。'''

class _S2TParams(ServiceParamsBase, total=False):
    '''S2T 请求参数。'''
    timeout: _AnnotateDefault[float | None, _DEFAULT_S2T_TIMEOUT]
    '''请求超时（秒）。默认 90 秒。'''
    client_key: str | None
    '''固定使用指定的 service-attached client key；``None`` 表示仍由 service 自动调度。'''

if TYPE_CHECKING:
    class S2TParams(_S2TParams, extra_items=object):
        '''S2T 请求参数。'''
else:
    S2TParams = _S2TParams

class S2THealthProbeInput(TypedDict):
    '''S2T 健康探测最小输入。'''
    audio: Audio | Video
    '''用于最小探测的音频或视频输入。'''
    kwargs: S2TParams
    '''探测时附带的额外参数。'''

class S2TClientInitParams(ServiceClientInitParams, total=False):
    '''S2T 客户端初始化参数。'''

class OpenAILikedS2TClientCreateParams(OpenAILikedClientCreateParams, S2TClientInitParams, total=False):
    '''OpenAI-Liked S2T 客户端创建参数。'''

class OpenRouterS2TClientCreateParams(OpenRouterClientCreateParams, S2TClientInitParams, total=False):
    '''OpenRouter S2T 客户端创建参数。'''


def _get_audio_source_bytes(audio: Audio) -> bytes | None:
    source = getattr(audio, '_source', None)
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    get_value = getattr(source, 'getvalue', None)
    if callable(get_value):
        value = get_value()
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
    return None

@cache
def _build_min_probe_audio() -> Audio:
    '''使用仓库内固定测试音频构建 S2T 健康探测输入。'''
    project_root = Path(__file__).resolve().parents[4]
    probe_audio_path = project_root / 'resources' / 'test' / 'test.mp3'
    if not probe_audio_path.exists():
        raise FileNotFoundError(f'S2T probe audio not found: {probe_audio_path}')
    return Audio(probe_audio_path)

class S2TClient(ServiceClientBase[S2THealthProbeInput]):

    ServiceKind: ClassVar['AIServiceKind'] = 's2t'
    '''语音转文本客户端抽象基类。'''

    def __init__(self, **kwargs: Unpack[S2TClientInitParams]):
        '''初始化 S2T 客户端。

        Args:
            **kwargs: 客户端初始化参数，结构见 `S2TClientInitParams`。
        '''
        super().__init__(**kwargs)

    @classmethod
    @cache
    def TestingInput(cls) -> S2THealthProbeInput:
        '''返回最小健康探测输入。'''
        return {
            'audio': _build_min_probe_audio(),
            'kwargs': {
                'prompt': 'Transcribe exactly.',
                'stream': False,
                'timeout': 8.0,
            },
        }

    async def probe_min_health(self) -> bool:
        '''执行最小健康探测。'''
        try:
            probe = type(self).TestingInput()
            output = await self.s2t(probe['audio'], __skip_log__=True, **probe.get('kwargs', {}))
            return bool(str(output).strip())
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
    def CreateOpenAILikedS2TClient(
        cls,
        **kwargs: Unpack[OpenAILikedS2TClientCreateParams],
    ) -> 'S2TClient':
        client_kwargs = cls._extract_common_client_kwargs(cast(dict[str, Any], kwargs))
        client_kwargs.update(_resolve_openai_liked_client_params(kwargs, service_name='s2t'))
        return OpenAILikedS2TClient(**client_kwargs)

    @classmethod
    def CreateOpenRouterS2TClient(
        cls,
        **kwargs: Unpack[OpenRouterS2TClientCreateParams],
    ) -> 'S2TClient':
        client_kwargs = cls._extract_common_client_kwargs(cast(dict[str, Any], kwargs))
        client_kwargs.update(_resolve_openrouter_client_params(kwargs, service_name='s2t'))
        return OpenRouterS2TClient(**client_kwargs)

    async def s2t(self, audio: Audio | Video, **kwargs: Unpack[S2TParams]) -> str:
        '''执行语音转文本。

        Args:
            audio: 待转写的音频或视频。
            **kwargs: 传递给底层客户端的附加参数。

        Returns:
            转写后的文本。
        '''
        exec_kwargs = dict(kwargs)
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, _S2TParams)
        req_timeout = float(exec_kwargs.pop('timeout')) # type: ignore
        request = self._log_request_payload('s2t', (audio,), dict(exec_kwargs))
        metadata = self._log_extra_metadata('s2t', (audio,), dict(exec_kwargs))
        return cast(
            str,
            await self._trace_async_call(
                's2t',
                lambda: asyncio.wait_for(self._s2t_impl(audio, **exec_kwargs), timeout=req_timeout),
                request=request,
                metadata=metadata,
                skip_log=skip_log,
            ),
        )

    async def _s2t_impl(self, audio: Audio | Video, **kwargs: object) -> str:
        raise NotImplementedError

    async def s2t_raw(self, audio: Audio | Video, **kwargs: object) -> dict[str, Any]:
        return {'text': await self.s2t(audio, **cast(S2TParams, kwargs))}

class CompletionAsS2TClient(S2TClient, type='completion'):
    '''将 CompletionService 适配为 S2T 客户端。'''

    def __init__(
        self,
        completion_service: CompletionService,  # TODO: 要适配client或service
        **kwargs: Unpack[S2TClientInitParams],
    ):
        super().__init__(
            key=kwargs.get('key'),
            priority=float(kwargs.get('priority', 0.0)),
            strategy_lvl=int(kwargs.get('strategy_lvl', 0)),
            max_concurrent=kwargs.get('max_concurrent'),
        )
        self._completion_service = completion_service

    def update(self, **new_params: object) -> bool:
        params = dict(new_params)
        completion_service = params.pop('completion_service', None) if 'completion_service' in params else None
        if not super().update(**params):
            return False
        if 'completion_service' in new_params:
            self._completion_service = cast(CompletionService, completion_service)
        return True

    def close(self, reason: str | None = None) -> None:
        super().close(reason=reason)
        close = getattr(self._completion_service, 'close', None)
        if callable(close):
            close()

    async def probe_min_health(self) -> bool:
        '''适配型客户端不单独做主动探测，避免为 completion 服务引入额外音频 probe。'''
        return True

    async def _s2t_impl(self, audio: Audio | Video, **kwargs: object) -> str:
        params = dict(kwargs)

        mode = params.pop('mode', None) or params.pop('task', None)
        if isinstance(mode, str) and mode.strip().lower() in ('transcript', 'diarization'):
            transcript_prompt = (
                params.pop('transcript_prompt', None)
                or params.pop('prompt', None)
                or params.pop('instruction', None)
            )
            roles = params.pop('roles', None)
            stream = params.pop('stream', params.pop('use_stream', True))
            transcript = await self._completion_service.transcript(
                audio,
                prompt=cast(Any, transcript_prompt),
                roles=cast(Any, roles),
                stream=bool(stream),
                **cast(Any, params),
            )
            return json.dumps(transcript.model_dump(), ensure_ascii=False)

        asr_prompt = (
            params.pop('asr_prompt', None)
            or params.pop('prompt', None)
            or params.pop('instruction', None)
        )
        stream = params.pop('stream', params.pop('use_stream', True))
        return await self._completion_service.asr(
            audio,
            prompt=cast(Any, asr_prompt),
            stream=bool(stream),
            **cast(Any, params),
        )


class OpenAILikedS2TClient(S2TClient, OpenAILikedClientMixin, type='openai'):
    '''OpenAI 协议兼容的语音转文本客户端。'''

    @classmethod
    def CreateFromConfig(cls, **kwargs: object) -> 'Self':
        return cast(Self, S2TClient.CreateOpenAILikedS2TClient(**cast(Any, kwargs)))

    def __init__(
        self,
        apikey: str | None,
        base_url: str,
        model: str | None = None,
        ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None' = None,
        **kwargs: Unpack[S2TClientInitParams],
    ):
        super().__init__(**kwargs)
        resolved_model = model or _env_first('OPENAI_S2T_MODEL') or 'whisper-1'
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

    def _transcription_url(self) -> str:
        return self._openai_liked_endpoint('/audio/transcriptions')

    def _transcription_urls(self) -> list[str]:
        return self._openai_liked_endpoint_candidates('/audio/transcriptions')

    async def s2t_raw(self, audio: Audio | Video, **kwargs: object) -> dict[str, Any]:
        params = dict(kwargs)
        audio_model = audio.get_audio_model() if isinstance(audio, Video) else audio
        if audio_model is None:
            raise ValueError('Video contains no audio track for S2T.')

        input_format = str(params.pop('input_format', 'wav'))
        audio_bytes = audio_model.to_bytes(format=input_format)
        model = str(params.pop('model', None) or self._model or 'whisper-1')

        prompt = params.pop('prompt', None) or params.pop('asr_prompt', None) or params.pop('instruction', None)
        if prompt is not None:
            prompt = str(prompt)
        language = params.pop('language', None)
        if language is None:
            expected_langs = params.pop('expected_languages', None)
            if isinstance(expected_langs, str):
                language = expected_langs.split(',', 1)[0].strip().lower()
        if language:
            language = str(language)
        if (response_format := params.pop('response_format', None)) is not None:
            response_format = str(response_format)
        if (temperature := params.pop('temperature', None)) is not None:
            temperature = str(temperature)
        timestamp_granularities = params.pop('timestamp_granularities', None)

        def build_form() -> aiohttp.FormData:
            form = aiohttp.FormData()
            form.add_field('file', audio_bytes, filename=f'audio.{input_format}', content_type=f'audio/{input_format}')
            form.add_field('model', model)
            if prompt is not None:
                form.add_field('prompt', cast(str, prompt))
            if language:
                form.add_field('language', cast(str, language))
            if response_format is not None:
                form.add_field('response_format', cast(str, response_format))
            if temperature is not None:
                form.add_field('temperature', cast(str, temperature))
            if isinstance(timestamp_granularities, (list, tuple)):
                for item in timestamp_granularities:
                    form.add_field('timestamp_granularities[]', str(item))
            return form

        timeout_value = cast(Any, params.pop('timeout', _DEFAULT_S2T_TIMEOUT))
        timeout = aiohttp.ClientTimeout(total=float(timeout_value))
        headers = self._openai_liked_headers(content_type=None)
        last_not_found: aiohttp.ClientResponseError | None = None
        urls = self._transcription_urls()
        for url_index, url in enumerate(urls):
            for attempt in range(2):
                session = await self._get_session()
                try:
                    async with session.post(url, data=build_form(), headers=headers, timeout=timeout) as response:
                        try:
                            response.raise_for_status()
                        except aiohttp.ClientResponseError as exc:
                            if exc.status == 404 and url_index < len(urls) - 1:
                                last_not_found = exc
                                break
                            raise
                        content_type = response.headers.get('Content-Type', '')
                        if 'application/json' in content_type:
                            return cast(dict[str, Any], await response.json())
                        text = await response.text()
                        return {'text': text}
                except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError, aiohttp.ClientConnectionError):
                    await self._close_session()
                    if attempt == 0:
                        continue
                    raise
        if last_not_found is not None:
            raise last_not_found
        raise RuntimeError('OpenAI-liked S2T request failed without response.')

    async def _s2t_impl(self, audio: Audio | Video, **kwargs: object) -> str:
        raw = await self.s2t_raw(audio, **kwargs)
        text = raw.get('text')
        if isinstance(text, str):
            return text
        return json.dumps(raw, ensure_ascii=False)


class OpenRouterS2TClient(OpenAILikedS2TClient, type='openrouter'):
    '''OpenRouter 语音转文本客户端。'''

    @classmethod
    def CreateFromConfig(cls, **kwargs: object) -> 'Self':
        return cast(Self, S2TClient.CreateOpenRouterS2TClient(**cast(Any, kwargs)))

    def __init__(
        self,
        apikey: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None' = None,
        **kwargs: Unpack[S2TClientInitParams],
    ):
        resolved = _resolve_openrouter_client_params(
            {
                'apikey': apikey,
                'base_url': base_url,
                'model': model,
                'ssh_tunnel': ssh_tunnel,
            },
            service_name='s2t',
            model_env_keys=('OPENROUTER_S2T_MODEL',),
            default_model='whisper-1',
        )
        super().__init__(
            apikey=cast(str, resolved['apikey']),
            base_url=cast(str, resolved['base_url']),
            model=cast(str | None, resolved['model']),
            ssh_tunnel=cast('SSHTunnelConfig | dict[str, Any] | str | None', resolved['ssh_tunnel']),
            **kwargs,
        )

    async def s2t_raw(self, audio: Audio | Video, **kwargs: object) -> dict[str, Any]:
        params = dict(kwargs)
        audio_model = audio.get_audio_model() if isinstance(audio, Video) else audio
        if audio_model is None:
            raise ValueError('Video contains no audio track for S2T.')

        requested_format = params.pop('input_format', None)
        if requested_format is None:
            input_format = str(audio_model.format or 'mp3')
            audio_bytes = _get_audio_source_bytes(audio_model) or audio_model.to_bytes(format=input_format)
        else:
            input_format = str(requested_format)
            audio_bytes = audio_model.to_bytes(format=input_format)
        payload: dict[str, Any] = {
            'input_audio': {
                'data': base64.b64encode(audio_bytes).decode('ascii'),
                'format': input_format,
            },
            'model': str(params.pop('model', None) or self._model or 'whisper-1'),
        }

        prompt = params.pop('prompt', None) or params.pop('asr_prompt', None) or params.pop('instruction', None)
        if prompt is not None:
            payload['prompt'] = str(prompt)
        language = params.pop('language', None)
        if language is None:
            expected_langs = params.pop('expected_languages', None)
            if isinstance(expected_langs, str):
                language = expected_langs.split(',', 1)[0].strip().lower()
        if language:
            payload['language'] = str(language)
        if (temperature := params.pop('temperature', None)) is not None:
            payload['temperature'] = float(cast(Any, temperature))
        if (response_format := params.pop('response_format', None)) is not None:
            payload['response_format'] = str(response_format)

        timeout_value = cast(Any, params.pop('timeout', _DEFAULT_S2T_TIMEOUT))
        timeout = aiohttp.ClientTimeout(total=float(timeout_value))
        headers = self._openrouter_headers()
        last_not_found: aiohttp.ClientResponseError | None = None
        urls = self._transcription_urls()
        for url_index, url in enumerate(urls):
            for attempt in range(2):
                session = await self._get_session()
                try:
                    async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                        try:
                            response.raise_for_status()
                        except aiohttp.ClientResponseError as exc:
                            if exc.status == 404 and url_index < len(urls) - 1:
                                last_not_found = exc
                                break
                            raise
                        content_type = response.headers.get('Content-Type', '')
                        if 'application/json' in content_type:
                            return cast(dict[str, Any], await response.json())
                        text = await response.text()
                        return {'text': text}
                except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError, aiohttp.ClientConnectionError):
                    await self._close_session()
                    if attempt == 0:
                        continue
                    raise
        if last_not_found is not None:
            raise last_not_found
        raise RuntimeError('OpenRouter S2T request failed without response.')

class S2TService(ServiceBase):
    '''语音转文本聚合服务。'''

    class DefaultClientParams:
        '''S2T 默认客户端参数。'''
        BASIC: S2TClientInitParams = {
            'max_concurrent': ConcurrentPool('s2t', 80),
        }

    def __init__(self, *clients: S2TClient | CompletionService | ServiceClient[S2TClient | CompletionService], **kwargs: Unpack[ServiceInitParams]):
        '''初始化 S2T 聚合服务。

        Args:
            *clients: 一个或多个 S2T 客户端，或可适配为 S2T 的 `CompletionService`。
            **kwargs: 服务初始化参数，结构见 `ServiceInitParams`。
        '''
        normalized_clients: list[S2TClient | ServiceClient[S2TClient]] = []
        for item in clients:
            binding = item if isinstance(item, ServiceClient) else None
            client = binding.client if binding is not None else item
            if isinstance(client, CompletionService):
                max_audios = client.max_audios
                max_videos = client.max_videos
                audio_disabled = isinstance(max_audios, int) and max_audios <= 0
                video_disabled = isinstance(max_videos, int) and max_videos <= 0
                if audio_disabled and video_disabled:
                    continue
                adapted = CompletionAsS2TClient(client)
                if binding is not None:
                    normalized_clients.append(ServiceClient(
                        client=adapted,
                        priority=binding.priority,
                        strategy_lvl=binding.strategy_lvl,
                    ))
                else:
                    normalized_clients.append(adapted)
            else:
                client = cast(S2TClient, client)
                normalized_clients.append(ServiceClient(
                    client=client,
                    priority=binding.priority,
                    strategy_lvl=binding.strategy_lvl,
                ) if binding is not None else client)

        super().__init__(*normalized_clients, **kwargs)

    @classmethod
    def Default(cls) -> 'S2TService':
        '''创建默认 S2T 服务。

        Returns:
            使用默认 CompletionService 适配得到的 S2T 服务实例。
        '''
        cls.WaitUntilRuntimeReady()
        if existing := cls.GetInstance('default'):
            return existing

        # ── Config-driven creation ──────────────────────────────────
        from .config import AIServicesConfig
        cfg = AIServicesConfig.Global()
        if cfg is not None:
            svc = cfg.s2t.get_default()
            if svc is not None:
                cfg.s2t.preload_service_instances()
                return cast('S2TService', svc)

        # ── Hardcoded / env fallback ──────────────────────────────
        clients: list[S2TClient] = []
        _append_env_default_client(
            clients,
            S2TClient.CreateOpenAILikedS2TClient,
            logger=_logger,
            description='OpenAI-compatible S2T',
            env_keys=('OPENAI_APIKEY', 'OPENAI_API_KEY'),
            factory_kwargs=cls.DefaultClientParams.BASIC,
        )
        _append_env_default_client(
            clients,
            S2TClient.CreateOpenRouterS2TClient,
            logger=_logger,
            description='OpenRouter S2T',
            env_keys=('OPENROUTER_APIKEY', 'OPENROUTER_API_KEY'),
            factory_kwargs=cls.DefaultClientParams.BASIC,
        )
        _append_default_client(
            clients,
            lambda: CompletionAsS2TClient(
                CompletionService.Default(),
                **cls.DefaultClientParams.BASIC,
            ),
            logger=_logger,
            description='Completion-backed S2T',
        )

        if not clients:
            raise RuntimeError(
                'Cannot create default S2TService: no client could be initialized. '
                'Please set OPENAI_APIKEY / OPENAI_API_KEY / OPENROUTER_APIKEY / OPENROUTER_API_KEY or configure a completion service.'
            )
        return cls(*clients, key='default')

    async def s2t(self, audio: Audio | Video, **kwargs: Unpack[S2TParams]) -> str:
        '''通过故障转移机制执行语音转文本。

        Args:
            audio: 待转写的音频或视频。
            **kwargs: 传递给客户端的附加参数。

        Returns:
            转写后的文本。
        '''
        _ctx, _ctx_token = enter_service_context('s2t')
        request_kwargs = dict(kwargs)
        selected_client_key = cast(str | None, request_kwargs.pop('client_key', None))

        async def _action(client: S2TClient) -> str:
            return await client.s2t(audio, **cast(S2TParams, request_kwargs))

        try:
            candidate_clients = self._resolve_service_client_candidates(self._clients, selected_client_key)
            return cast(str, await self._run_with_failover(candidate_clients, _action, error_prefix='All S2T clients failed'))
        finally:
            exit_service_context(_ctx_token)

    async def s2t_raw(self, audio: Audio | Video, **kwargs: object) -> dict[str, Any]:
        '''通过故障转移机制执行 raw S2T 请求。'''
        _ctx, _ctx_token = enter_service_context('s2t')
        request_kwargs = dict(kwargs)
        selected_client_key = cast(str | None, request_kwargs.pop('client_key', None))

        async def _action(client: S2TClient) -> dict[str, Any]:
            return await client.s2t_raw(audio, **request_kwargs)

        try:
            candidate_clients = self._resolve_service_client_candidates(self._clients, selected_client_key)
            return cast(dict[str, Any], await self._run_with_failover(candidate_clients, _action, error_prefix='All S2T raw clients failed'))
        finally:
            exit_service_context(_ctx_token)


class CustomS2TAdapterProtocol(Protocol):
    '''S2T custom adapter 协议。'''

    def s2t(self, audio: Audio | Video, **kwargs: Unpack[S2TParams]) -> Any: ...


def _is_custom_s2t_adapter(adapter: object) -> bool:
    return callable(getattr(adapter, 's2t', None))


def _custom_s2t_adapter_cache_key(adapter: str | OBS_Object) -> str:
    if isinstance(adapter, OBS_Object):
        payload = adapter.model_dump(mode='python')
        return json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return str(adapter or '').strip()


def _normalize_custom_s2t_adapter(adapter: str | OBS_Object) -> tuple[str, str | Path | OBS_Object]:
    if isinstance(adapter, OBS_Object):
        return 'obs', adapter

    raw = str(adapter or '').strip()
    if not raw:
        raise ValueError('Custom s2t adapter requires a non-empty adapter.')

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


def _custom_s2t_module_name(adapter: str | OBS_Object) -> str:
    digest = hashlib.md5(_custom_s2t_adapter_cache_key(adapter).encode('utf-8')).hexdigest()
    return f'core.ai.custom_s2t_adapter_{digest}'


def _load_s2t_module_from_file(path: Path, module_name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f'Failed to load custom s2t adapter module from {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_s2t_module_from_source(source: str, *, module_name: str, origin: str) -> types.ModuleType:
    module = types.ModuleType(module_name)
    module.__file__ = origin
    sys.modules[module_name] = module
    exec(compile(source, origin, 'exec'), module.__dict__)
    return module


def _load_s2t_module_from_url(adapter: str, module_name: str) -> types.ModuleType:
    with urlopen(adapter, timeout=15) as response:
        source = response.read().decode('utf-8')
    return _load_s2t_module_from_source(source, module_name=module_name, origin=adapter)


def _load_s2t_module_from_obs_object(adapter: OBS_Object, module_name: str) -> types.ModuleType:
    source = run_any_func(adapter._get_bytes)
    if source is None:
        raise FileNotFoundError(f'Custom s2t adapter object not found: {adapter.storage_name}:{adapter.path}')
    if isinstance(source, str):
        source_text = source
    else:
        source_text = bytes(source).decode('utf-8')
    origin = f'obs://{adapter.storage_name}/{adapter.path.lstrip("/")}'
    return _load_s2t_module_from_source(source_text, module_name=module_name, origin=origin)


def load_custom_s2t_adapter_module(adapter: str | OBS_Object) -> types.ModuleType:
    module_name = _custom_s2t_module_name(adapter)
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    source_kind, source = _normalize_custom_s2t_adapter(adapter)
    if source_kind == 'file':
        path = cast(Path, source)
        if not path.is_file():
            raise FileNotFoundError(f'Custom s2t adapter script not found: {path}')
        return _load_s2t_module_from_file(path, module_name)
    if source_kind == 'obs':
        return _load_s2t_module_from_obs_object(cast(OBS_Object, source), module_name)
    return _load_s2t_module_from_url(cast(str, source), module_name)


def instantiate_custom_s2t_adapter(
    *,
    adapter: str | OBS_Object,
    init_kwargs: dict[str, object],
) -> CustomS2TAdapterProtocol:
    module = load_custom_s2t_adapter_module(adapter)
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
        if _is_custom_s2t_adapter(instance):
            return cast(CustomS2TAdapterProtocol, instance)
        errors.append(f'{name}: does not satisfy {CustomS2TAdapterProtocol.__name__}')

    detail = '; '.join(errors) if errors else 'no top-level class found in module'
    raise TypeError(f'No class in {adapter!r} satisfies {CustomS2TAdapterProtocol.__name__}: {detail}')


async def _resolve_custom_s2t_awaitable(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _call_custom_s2t_override(adapter: object, method_name: str, *args: object, **kwargs: object) -> Any:
    method = getattr(adapter, method_name, None)
    if not callable(method):
        return None
    return await _resolve_custom_s2t_awaitable(method(*args, **kwargs))


class CustomS2TClient(S2TClient, type='custom'):
    '''S2T 自定义 adapter 包装器。'''

    _WRAPPER_INIT_FIELDS: ClassVar[frozenset[str]] = frozenset({'key', 'max_concurrent', 'priority', 'strategy_lvl'})

    def __init__(
        self,
        adapter: CustomS2TAdapterProtocol | str | OBS_Object | None = None,
        **kwargs: Any,
    ):
        if isinstance(adapter, (str, OBS_Object)):
            adapter_kwargs = {k: v for k, v in kwargs.items() if k not in self._WRAPPER_INIT_FIELDS}
            wrapper_kwargs = {k: v for k, v in kwargs.items() if k in self._WRAPPER_INIT_FIELDS}
            adapter = instantiate_custom_s2t_adapter(adapter=adapter, init_kwargs=adapter_kwargs)
        else:
            if adapter is None:
                raise ValueError('Custom S2T client requires adapter when adapter instance is not provided.')
            wrapper_kwargs = kwargs
            if not _is_custom_s2t_adapter(adapter):
                raise TypeError(f'Custom S2T adapter instance must define s2t(), got {type(adapter).__name__}')
            adapter = cast(CustomS2TAdapterProtocol, adapter)

        super().__init__(**wrapper_kwargs)
        self._adapter = adapter

    @classmethod
    def TestingInput(cls) -> dict[str, object]:
        return {
            'audio': _build_min_probe_audio(),
            'kwargs': {'prompt': 'Transcribe exactly.', 'stream': False, 'timeout': 8.0},
        }

    async def probe_min_health(self) -> bool:
        override = await _call_custom_s2t_override(self._adapter, 'probe_min_health')
        if override is not None:
            return bool(override)

        testing_input = getattr(type(self._adapter), 'TestingInput', None)
        if callable(testing_input):
            probe = cast(dict[str, Any], testing_input())
            output = await self.s2t(__skip_log__=True, **probe)  # type: ignore[arg-type]
            return bool(str(output).strip())
        return await super().probe_min_health()

    async def _s2t_impl(self, audio: Audio | Video, **kwargs: object) -> str:
        result = await _resolve_custom_s2t_awaitable(self._adapter.s2t(audio, **cast(dict[str, Any], kwargs)))
        return str(result or '')

    def close(self, reason: str | None = None) -> None:
        close_func = getattr(self._adapter, 'close', None)
        if callable(close_func):
            try:
                run_any_func(close_func)
            except Exception:
                pass
        super().close(reason=reason)


__all__ += [
    'S2TParams',
    'S2THealthProbeInput',
    'S2TClientInitParams',
    'OpenAILikedS2TClientCreateParams',
    'OpenRouterS2TClientCreateParams',
    'S2TClient',
    'CompletionAsS2TClient',
    'OpenAILikedS2TClient',
    'OpenRouterS2TClient',
    'S2TService',
    'CustomS2TAdapterProtocol',
    'CustomS2TClient',
    'instantiate_custom_s2t_adapter',
    'load_custom_s2t_adapter_module',
]
