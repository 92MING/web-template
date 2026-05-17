import hashlib
import importlib.util
import inspect
import json
import sys
import types

from pathlib import Path
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname, urlopen

from typing_extensions import Unpack
from typing import Any, AsyncGenerator, Callable, Iterable, Protocol, Sequence, cast, runtime_checkable

from core.utils.concurrent_utils import run_any_func
from core.utils.data_structs import Audio, Image, Video
from core.storage.object import OBS_Object

from .completion import ChatCompleteParams, CompletionClient, CompletionStreamChunk
from .embedding import EmbeddingClient, EmbeddingRequestParams
from .s2t import S2TClient, S2TParams, _build_min_probe_audio
from .t2s import T2SClient, T2SParams, ThinkThinkSynT2SClient

__all__ = [
    'CustomAdapterProtocol',
    'CustomCompletionAdapterProtocol',
    'CustomEmbeddingAdapterProtocol',
    'CustomS2TAdapterProtocol',
    'CustomT2SAdapterProtocol',
    'CustomCompletionClient',
    'CustomEmbeddingClient',
    'CustomS2TClient',
    'CustomT2SClient',
    'create_custom_service_client',
    'instantiate_custom_adapter',
    'load_custom_adapter_module',
]


class CustomAdapterProtocol(Protocol):
    '''自定义 adapter 的公共标记协议。'''


@runtime_checkable
class CustomCompletionAdapterProtocol(CustomAdapterProtocol, Protocol):
    '''Completion custom adapter 协议。'''

    max_tokens: int | None
    max_images: int | None
    max_audios: int | None
    max_videos: int | None
    support_json: bool

    def stream_complete(self, **kwargs: Unpack[ChatCompleteParams]) -> Any: ...


@runtime_checkable
class CustomEmbeddingAdapterProtocol(CustomAdapterProtocol, Protocol):
    '''Embedding custom adapter 协议。'''

    max_tokens: int | None
    support_image: bool
    support_audio: bool
    support_video: bool

    def embedding(
        self,
        inputs: Sequence[str | Image | Audio | Video],
        **kwargs: Unpack[EmbeddingRequestParams],
    ) -> Any: ...


@runtime_checkable
class CustomS2TAdapterProtocol(CustomAdapterProtocol, Protocol):
    '''S2T custom adapter 协议。'''

    def s2t(self, audio: Audio | Video, **kwargs: Unpack[S2TParams]) -> Any: ...


@runtime_checkable
class CustomT2SAdapterProtocol(CustomAdapterProtocol, Protocol):
    '''T2S custom adapter 协议。'''

    def t2s(self, text: str, **kwargs: Unpack[T2SParams]) -> Any: ...


def _custom_adapter_cache_key(adapter_url: str | OBS_Object) -> str:
    if isinstance(adapter_url, OBS_Object):
        payload = adapter_url.model_dump(mode='python')
        return json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return str(adapter_url or '').strip()


def _normalize_custom_adapter_url(adapter_url: str | OBS_Object) -> tuple[str, str | Path | OBS_Object]:
    if isinstance(adapter_url, OBS_Object):
        return 'obs', adapter_url

    raw = str(adapter_url or '').strip()
    if not raw:
        raise ValueError('Custom adapter requires a non-empty adapter_url.')

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


def _custom_module_name(adapter_url: str | OBS_Object) -> str:
    digest = hashlib.md5(_custom_adapter_cache_key(adapter_url).encode('utf-8')).hexdigest()
    return f'core.ai.custom_adapter_{digest}'


def _load_module_from_file(path: Path, module_name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f'Failed to load custom adapter module from {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_module_from_source(source: str, *, module_name: str, origin: str) -> types.ModuleType:
    module = types.ModuleType(module_name)
    module.__file__ = origin
    sys.modules[module_name] = module
    exec(compile(source, origin, 'exec'), module.__dict__)
    return module


def _load_module_from_url(adapter_url: str, module_name: str) -> types.ModuleType:
    with urlopen(adapter_url, timeout=15) as response:
        source = response.read().decode('utf-8')
    return _load_module_from_source(source, module_name=module_name, origin=adapter_url)


def _load_module_from_obs_object(adapter: OBS_Object, module_name: str) -> types.ModuleType:
    source = run_any_func(adapter._get_bytes)
    if source is None:
        raise FileNotFoundError(f'Custom adapter object not found: {adapter.storage_name}:{adapter.path}')
    if isinstance(source, str):
        source_text = source
    else:
        source_text = bytes(source).decode('utf-8')
    origin = f'obs://{adapter.storage_name}/{adapter.path.lstrip("/")}'
    return _load_module_from_source(source_text, module_name=module_name, origin=origin)


def load_custom_adapter_module(adapter_url: str | OBS_Object) -> types.ModuleType:
    module_name = _custom_module_name(adapter_url)
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    source_kind, source = _normalize_custom_adapter_url(adapter_url)
    if source_kind == 'file':
        path = cast(Path, source)
        if not path.is_file():
            raise FileNotFoundError(f'Custom adapter script not found: {path}')
        return _load_module_from_file(path, module_name)
    if source_kind == 'obs':
        return _load_module_from_obs_object(cast(OBS_Object, source), module_name)
    return _load_module_from_url(cast(str, source), module_name)


def instantiate_custom_adapter(
    *,
    adapter_url: str | OBS_Object,
    protocol: type[CustomCompletionAdapterProtocol | CustomEmbeddingAdapterProtocol | CustomS2TAdapterProtocol | CustomT2SAdapterProtocol],
    init_kwargs: dict[str, object],
) -> CustomAdapterProtocol:
    module = load_custom_adapter_module(adapter_url)
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
        if protocol is CustomCompletionAdapterProtocol and not hasattr(instance, 'support_json'):
            setattr(instance, 'support_json', True)
        if isinstance(instance, protocol):
            return cast(CustomAdapterProtocol, instance)
        errors.append(f'{name}: does not satisfy {protocol.__name__}')

    detail = '; '.join(errors) if errors else 'no top-level class found in module'
    raise TypeError(f'No class in {adapter_url!r} satisfies {protocol.__name__}: {detail}')


async def _resolve_maybe_awaitable(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _iterate_maybe_stream(value: Any) -> AsyncGenerator[Any, None]:
    resolved = await _resolve_maybe_awaitable(value)
    if hasattr(resolved, '__aiter__'):
        async for item in resolved:
            yield item
        return
    if isinstance(resolved, (str, bytes, bytearray, memoryview, dict, Audio, Image, Video)):
        yield resolved
        return
    if isinstance(resolved, Iterable):
        for item in resolved:
            yield item
        return
    raise TypeError(f'Unsupported custom adapter stream value: {type(resolved).__name__}')


async def _call_optional_override(adapter: object, method_name: str, *args: object, **kwargs: object) -> Any:
    method = getattr(adapter, method_name, None)
    if not callable(method):
        return None
    return await _resolve_maybe_awaitable(method(*args, **kwargs))


def _copy_attr_if_present(target: object, adapter: object, attr_name: str) -> None:
    if hasattr(adapter, attr_name):
        setattr(target, attr_name, getattr(adapter, attr_name))


def _normalize_completion_result(result: Any) -> tuple[str, dict[str, int | None] | None, str | None]:
    if hasattr(result, 'model_dump'):
        result = result.model_dump()
    elif hasattr(result, '__dict__') and not isinstance(result, dict):
        result = result.__dict__

    if isinstance(result, dict) and 'text' in result:
        usage = {
            'input_tokens': int(result['input_tokens']) if isinstance(result.get('input_tokens'), (int, float)) else None,
            'output_tokens': int(result['output_tokens']) if isinstance(result.get('output_tokens'), (int, float)) else None,
        }
        return str(result.get('text') or ''), usage, cast(str | None, result.get('thinking'))
    return str(result or ''), None, None


def _normalize_completion_chunk(chunk: Any) -> CompletionStreamChunk | None:
    if hasattr(chunk, 'model_dump'):
        chunk = chunk.model_dump()
    elif hasattr(chunk, '__dict__') and not isinstance(chunk, dict):
        chunk = chunk.__dict__

    if isinstance(chunk, dict):
        data = chunk.get('data')
        chunk_type = chunk.get('type', 'text')
        if isinstance(data, str) and chunk_type in ('text', 'think'):
            return CompletionStreamChunk(data=data, type=cast('str', chunk_type))  # type: ignore[arg-type]
        return None
    if chunk is None:
        return None
    return CompletionStreamChunk(data=str(chunk), type='text')


async def _collect_completion_from_stream(value: Any) -> tuple[str, str | None]:
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    async for chunk in _iterate_maybe_stream(value):
        normalized = _normalize_completion_chunk(chunk)
        if normalized is None:
            continue
        if normalized['type'] == 'think':
            thinking_parts.append(normalized['data'])
        else:
            text_parts.append(normalized['data'])
    thinking = ''.join(thinking_parts) or None
    return ''.join(text_parts), thinking


def _normalize_embedding_result(result: Any) -> list[list[float]]:
    if not isinstance(result, list):
        raise TypeError(f'Custom embedding adapter must return list, got {type(result).__name__}')
    if result and all(isinstance(value, (int, float)) for value in result):
        return [[float(value) for value in result]]

    vectors: list[list[float]] = []
    for row in result:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes, bytearray, memoryview)):
            raise TypeError('Custom embedding adapter must return list[list[float]]')
        vectors.append([float(value) for value in row])
    return vectors


def _normalize_t2s_audio(value: object) -> Audio:
    if isinstance(value, dict):
        for key in ('data', 'audio', 'source', 'voice', 'sound', 'url'):
            if key in value and value[key]:
                return ThinkThinkSynT2SClient._coerce_to_audio(value[key])
        raise ValueError(f'T2S adapter returned dict without recognizable audio key: {list(value.keys())}')
    return ThinkThinkSynT2SClient._coerce_to_audio(value)


class CustomCompletionClient(CompletionClient):
    '''Completion 自定义 adapter 包装器。'''

    Type = 'custom'

    def __init__(self, adapter: CustomCompletionAdapterProtocol, **kwargs: Any):
        super().__init__(**kwargs)
        self._adapter = adapter
        for attr_name in ('max_tokens', 'max_images', 'max_audios', 'max_videos', 'support_json'):
            _copy_attr_if_present(self, adapter, attr_name)
        token_counter = getattr(adapter, 'token_counter', None)
        if callable(token_counter):
            self.token_counter = cast(Callable[[object], int], token_counter)

    @classmethod
    def TestingInput(cls) -> ChatCompleteParams:
        return {
            'messages': [{'role': 'user', 'content': 'ping'}],
            'timeout': 8.0,
        }

    async def probe_min_health(self) -> bool:
        override = await _call_optional_override(self._adapter, 'probe_min_health')
        if override is not None:
            return bool(override)

        testing_input = getattr(type(self._adapter), 'TestingInput', None)
        if callable(testing_input):
            probe = cast(dict[str, Any], testing_input())
            output = await self.complete(__skip_log__=True, **probe)  # type: ignore[arg-type]
            return bool(str(output).strip())
        return await super().probe_min_health()

    def count_tokens(self, value: object) -> int:
        count_tokens = getattr(self._adapter, 'count_tokens', None)
        if callable(count_tokens):
            try:
                counted = int(count_tokens(value))
                if counted >= 0:
                    return counted
            except Exception:
                pass
        return super().count_tokens(cast(Any, value))

    async def _complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> str:
        complete_func = getattr(self._adapter, 'complete', None)
        if callable(complete_func):
            result = await _resolve_maybe_awaitable(complete_func(**kwargs))
            text, usage, thinking = _normalize_completion_result(result)
            self._set_latest_token_usage(usage)
            self._set_latest_thinking(thinking)
            return text

        text, thinking = await _collect_completion_from_stream(self._adapter.stream_complete(**kwargs))
        self._set_latest_token_usage(None)
        self._set_latest_thinking(thinking)
        return text

    async def _stream_complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> AsyncGenerator[CompletionStreamChunk, None]:
        async for chunk in _iterate_maybe_stream(self._adapter.stream_complete(**kwargs)):
            normalized = _normalize_completion_chunk(chunk)
            if normalized is not None:
                yield normalized

    def close(self, reason: str | None = None) -> None:
        close_func = getattr(self._adapter, 'close', None)
        if callable(close_func):
            try:
                run_any_func(close_func)
            except Exception:
                pass
        super().close(reason=reason)


class CustomEmbeddingClient(EmbeddingClient):
    '''Embedding 自定义 adapter 包装器。'''

    Type = 'custom'

    def __init__(self, adapter: CustomEmbeddingAdapterProtocol, **kwargs: Any):
        super().__init__(**kwargs)
        self._adapter = adapter
        for attr_name in ('max_tokens', 'support_image', 'support_audio', 'support_video'):
            _copy_attr_if_present(self, adapter, attr_name)
        token_counter = getattr(adapter, 'token_counter', None)
        if callable(token_counter):
            self.token_counter = cast(Callable[[object], int], token_counter)

    @classmethod
    def TestingInput(cls) -> dict[str, object]:
        return {
            'inputs': ['ping'],
            'kwargs': {'use_cache': False, 'save_cache': False, 'timeout': 8.0},
        }

    async def probe_min_health(self) -> bool:
        override = await _call_optional_override(self._adapter, 'probe_min_health')
        if override is not None:
            return bool(override)

        testing_input = getattr(type(self._adapter), 'TestingInput', None)
        if callable(testing_input):
            probe = cast(dict[str, Any], testing_input())
            vectors = await self.embedding(__skip_log__=True, **probe)  # type: ignore[arg-type]
            return bool(vectors)
        return await super().probe_min_health()

    def count_tokens(self, value: str | Image | Audio | Video) -> int:
        count_tokens = getattr(self._adapter, 'count_tokens', None)
        if callable(count_tokens):
            try:
                counted = int(count_tokens(value))
                if counted >= 0:
                    return counted
            except Exception:
                pass
        return super().count_tokens(value)

    async def _embedding_impl(self, inputs: Sequence[str | Image | Audio | Video], **kwargs: object) -> list[list[float]]:
        result = await _resolve_maybe_awaitable(self._adapter.embedding(inputs, **cast(dict[str, Any], kwargs)))
        return _normalize_embedding_result(result)

    def close(self, reason: str | None = None) -> None:
        close_func = getattr(self._adapter, 'close', None)
        if callable(close_func):
            try:
                run_any_func(close_func)
            except Exception:
                pass
        super().close(reason=reason)


class CustomS2TClient(S2TClient):
    '''S2T 自定义 adapter 包装器。'''

    Type = 'custom'

    def __init__(self, adapter: CustomS2TAdapterProtocol, **kwargs: Any):
        super().__init__(**kwargs)
        self._adapter = adapter

    @classmethod
    def TestingInput(cls) -> dict[str, object]:
        return {
            'audio': _build_min_probe_audio(),
            'kwargs': {'prompt': 'Transcribe exactly.', 'stream': False, 'timeout': 8.0},
        }

    async def probe_min_health(self) -> bool:
        override = await _call_optional_override(self._adapter, 'probe_min_health')
        if override is not None:
            return bool(override)

        testing_input = getattr(type(self._adapter), 'TestingInput', None)
        if callable(testing_input):
            probe = cast(dict[str, Any], testing_input())
            output = await self.s2t(__skip_log__=True, **probe)  # type: ignore[arg-type]
            return bool(str(output).strip())
        return await super().probe_min_health()

    async def _s2t_impl(self, audio: Audio | Video, **kwargs: object) -> str:
        result = await _resolve_maybe_awaitable(self._adapter.s2t(audio, **cast(dict[str, Any], kwargs)))
        return str(result or '')

    def close(self, reason: str | None = None) -> None:
        close_func = getattr(self._adapter, 'close', None)
        if callable(close_func):
            try:
                run_any_func(close_func)
            except Exception:
                pass
        super().close(reason=reason)


class CustomT2SClient(T2SClient):
    '''T2S 自定义 adapter 包装器。'''

    Type = 'custom'

    def __init__(self, adapter: CustomT2SAdapterProtocol, **kwargs: Any):
        super().__init__(**kwargs)
        self._adapter = adapter

    @classmethod
    def TestingInput(cls) -> dict[str, object]:
        return {
            'text': 'ok',
            'kwargs': {'timeout': 8.0},
        }

    async def probe_min_health(self) -> bool:
        override = await _call_optional_override(self._adapter, 'probe_min_health')
        if override is not None:
            return bool(override)

        testing_input = getattr(type(self._adapter), 'TestingInput', None)
        if callable(testing_input):
            probe = cast(dict[str, Any], testing_input())
            output = await self.t2s(__skip_log__=True, **probe)  # type: ignore[arg-type]
            return isinstance(output, Audio)
        return await super().probe_min_health()

    async def _t2s_impl(self, text: str, **kwargs: object) -> Audio:
        result = await _resolve_maybe_awaitable(self._adapter.t2s(text, **cast(dict[str, Any], kwargs)))
        return _normalize_t2s_audio(result)

    async def _t2s_stream_impl(self, text: str, *, chunk_size: int = 16384, **kwargs: object) -> AsyncGenerator[bytes, None]:
        stream_func = getattr(self._adapter, 't2s_stream', None)
        if callable(stream_func):
            async for chunk in _iterate_maybe_stream(stream_func(text, chunk_size=chunk_size, **kwargs)):
                if isinstance(chunk, (bytes, bytearray, memoryview)):
                    yield bytes(chunk)
                else:
                    yield _normalize_t2s_audio(chunk).to_bytes()
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


def create_custom_service_client(
    *,
    service_kind: str,
    adapter_url: str | OBS_Object,
    client_kwargs: dict[str, object],
    adapter_kwargs: dict[str, object],
) -> CompletionClient | EmbeddingClient | S2TClient | T2SClient:
    normalized_kind = str(service_kind or '').strip().lower()
    if normalized_kind == 'completion':
        adapter = instantiate_custom_adapter(
            adapter_url=adapter_url,
            protocol=CustomCompletionAdapterProtocol,
            init_kwargs=adapter_kwargs,
        )
        return CustomCompletionClient(cast(CustomCompletionAdapterProtocol, adapter), **client_kwargs)
    if normalized_kind == 'embedding':
        adapter = instantiate_custom_adapter(
            adapter_url=adapter_url,
            protocol=CustomEmbeddingAdapterProtocol,
            init_kwargs=adapter_kwargs,
        )
        return CustomEmbeddingClient(cast(CustomEmbeddingAdapterProtocol, adapter), **client_kwargs)
    if normalized_kind == 's2t':
        adapter = instantiate_custom_adapter(
            adapter_url=adapter_url,
            protocol=CustomS2TAdapterProtocol,
            init_kwargs=adapter_kwargs,
        )
        return CustomS2TClient(cast(CustomS2TAdapterProtocol, adapter), **client_kwargs)
    if normalized_kind == 't2s':
        adapter = instantiate_custom_adapter(
            adapter_url=adapter_url,
            protocol=CustomT2SAdapterProtocol,
            init_kwargs=adapter_kwargs,
        )
        return CustomT2SClient(cast(CustomT2SAdapterProtocol, adapter), **client_kwargs)
    raise ValueError(f'Unsupported custom service kind: {service_kind}')