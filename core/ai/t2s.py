import time
import asyncio

from functools import cache
from typing_extensions import Unpack
from typing import TYPE_CHECKING, AsyncGenerator, ClassVar, cast, TypedDict, Self
from thinkthinksyn import ThinkThinkSyn

from core.utils.data_structs import Audio
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
    _patch_thinkthinksyn_proxy,
    _apply_ssh_tunnel_to_tts_client,
    _resolve_ssh_tunnel_config,
    thinkthinksyn_client,
)
from .shared import AIServiceKind

__all__: list[str] = []
_DEFAULT_T2S_TIMEOUT = 120.0
'''默认 T2S 请求超时（秒）。'''

class _T2SParams(ServiceParamsBase, total=False):
    '''T2S 请求参数。'''
    timeout: _AnnotateDefault[float | None, _DEFAULT_T2S_TIMEOUT]
    '''请求超时（秒）。默认 120 秒。'''

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


class ThinkThinkSynT2SClient(T2SClient, type='tts-t2s'):
    '''ThinkThinkSyn 文本转语音客户端。'''

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


class T2SService(ServiceBase):
    '''文本转语音聚合服务。'''

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
        if not clients:
            raise ValueError('T2SService requires at least one client.')
        super().__init__(*clients, **kwargs)
        self._start_init_probe()

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
                for ek in cfg.t2s.extras:
                    cfg.t2s.get_service(ek)
                return cast(Self, svc)

        # ── Hardcoded fallback ────────────────────────────────────
        client = ThinkThinkSynT2SClient(
            tts_client=thinkthinksyn_client(),
            **cls.DefaultThinkThinkSynClientParams.XTTS,
        )
        return cls(client, key='default')

    async def t2s(self, text: str, **kwargs: Unpack[T2SParams]) -> Audio:
        '''通过故障转移机制执行文本转语音。

        Args:
            text: 待合成的文本。
            **kwargs: 传递给客户端的附加参数。

        Returns:
            合成后的音频对象。
        '''
        async def _action(client: T2SClient) -> Audio:
            return await client.t2s(text, **kwargs)

        return cast(Audio, await self._run_with_failover(self.clients, _action, error_prefix='All T2S clients failed'))

    async def t2s_stream(self, text: str, *, chunk_size: int = 16384, **kwargs: Unpack[T2SParams]) -> AsyncGenerator[bytes, None]:
        '''通过客户端故障转移输出流式音频字节（含策略分级、冷却检查和状态追踪）。'''
        self._ensure_recovery_task()
        errors: list[str] = []
        cooldown_blocked: list[T2SClient] = []

        for tier_clients in self._strategy_groups(self.clients):
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
                    async for chunk in client.t2s_stream(text, chunk_size=chunk_size, **kwargs):
                        streamed = True
                        yield chunk
                    await self._on_success(client)
                    return
                except Exception as exc:
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
                async for chunk in best.t2s_stream(text, chunk_size=chunk_size, **kwargs):
                    yield chunk
                await self._on_success(best)
                return
            except Exception as exc:
                await self._on_fail(best, exc)
                errors.append(f'[{self._client_display_name(best)}] {type(exc).__name__}: {exc}')
            finally:
                best._state_inflight = max(0, int(getattr(best, '_state_inflight', 1)) - 1)  # type: ignore[attr-defined]

        raise RuntimeError('All T2S stream clients failed. ' + ' | '.join(errors))


__all__ += [
    'T2SParams',
    'T2SHealthProbeInput',
    'T2SClientInitParams',
    'T2SClient',
    'ThinkThinkSynT2SClient',
    'T2SService',
]
