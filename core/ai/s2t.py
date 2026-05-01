import json
import asyncio

from pathlib import Path
from functools import cache

from typing_extensions import Unpack
from typing import TYPE_CHECKING, ClassVar, cast, TypedDict

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
)
from .completion import CompletionService
from .shared import AIServiceKind


__all__ = []
_DEFAULT_S2T_TIMEOUT = 90.0
'''默认 S2T 请求超时（秒）。'''

class _S2TParams(ServiceParamsBase, total=False):
    '''S2T 请求参数。'''
    timeout: _AnnotateDefault[float | None, _DEFAULT_S2T_TIMEOUT]
    '''请求超时（秒）。默认 90 秒。'''

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

class CompletionAsS2TClient(S2TClient, type='completion-as-s2t'):
    '''将 CompletionService 适配为 S2T 客户端。'''

    def __init__(
        self,
        completion_service: CompletionService,
        **kwargs: Unpack[S2TClientInitParams],
    ):
        super().__init__(
            key=kwargs.get('key'),
            priority=float(kwargs.get('priority', 0.0)),
            strategy_lvl=int(kwargs.get('strategy_lvl', 0)),
            max_concurrent=kwargs.get('max_concurrent'),
        )
        self._completion_service = completion_service

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
                prompt=transcript_prompt,
                roles=roles,
                stream=bool(stream),
                **params,
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
            prompt=asr_prompt,
            stream=bool(stream),
            **params,
        )

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
        if not clients:
            raise ValueError('S2TService requires at least one client.')

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
                normalized_clients.append(ServiceClient(
                    client=client,
                    priority=binding.priority,
                    strategy_lvl=binding.strategy_lvl,
                ) if binding is not None else client)

        if not normalized_clients:
            raise ValueError('S2TService requires at least one audio-capable client.')

        super().__init__(*normalized_clients, **kwargs)
        self._start_init_probe()

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
                for ek in cfg.s2t.extras:
                    cfg.s2t.get_service(ek)
                return cast('S2TService', svc)

        # ── Hardcoded fallback ────────────────────────────────────
        client = CompletionAsS2TClient(
            CompletionService.Default(),
            **cls.DefaultClientParams.BASIC,
        )
        return cls(client, key='default')

    async def s2t(self, audio: Audio | Video, **kwargs: Unpack[S2TParams]) -> str:
        '''通过故障转移机制执行语音转文本。

        Args:
            audio: 待转写的音频或视频。
            **kwargs: 传递给客户端的附加参数。

        Returns:
            转写后的文本。
        '''
        _ctx, _ctx_token = enter_service_context('s2t')

        async def _action(client: S2TClient) -> str:
            return await client.s2t(audio, **kwargs)

        try:
            return cast(str, await self._run_with_failover(self.clients, _action, error_prefix='All S2T clients failed'))
        finally:
            exit_service_context(_ctx_token)


__all__ += [
    'S2TParams',
    'S2THealthProbeInput',
    'S2TClientInitParams',
    'S2TClient',
    'CompletionAsS2TClient',
    'S2TService',
]
