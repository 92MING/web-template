import base64
import json
import asyncio
import logging
import aiohttp
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncGenerator, ClassVar, Literal, Sequence, TYPE_CHECKING, TypedDict, cast, overload
from typing_extensions import Required, Unpack
from PIL import Image as PILImage, ImageChops

from core.utils.data_structs import Audio, Video
from core.utils.data_structs.files import Image
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
    enter_service_context,
    exit_service_context,
    OpenAILikedClientCreateParams,
    OpenRouterClientCreateParams,
    OpenAILikedClientMixin,
    _env_first,
    _resolve_openai_liked_client_params,
    _resolve_openrouter_client_params,
    _append_env_default_client,
)
from .shared import AIServiceKind

if TYPE_CHECKING:
    from core.utils.network_utils.ssh_tunnel import SSHTunnelConfig
    from .completion import CompletionService, LLMContent
    from .s2t import S2TService
else:
    LLMContent = object

__all__: list[str] = []
_logger = logging.getLogger(__name__)
_DEFAULT_T2IMG_TIMEOUT = 180.0


type CommonSize = Literal['256x256', '512x512', '1024x1024', '1792x1024', '1024x1792', '1536x864', '2560x1440', '3820x2160', '1536x1024', '1024x1536']
type BackgroundOption = Literal['transparent', 'white', 'black', 'red', 'green', 'blue']
type TaskType = Literal['generate', 'edit', 'variation']


class T2ImgInput(TypedDict, total=False):  # type: ignore[name-defined]
    prompt: Required['LLMContent | Sequence[LLMContent]']
    size: CommonSize | str | tuple[int, int]
    count: int
    background: BackgroundOption | str | tuple[int, int, int]
    output_compression: int
    stream: bool


class _T2ImgParams(ServiceParamsBase, total=False):
    timeout: _AnnotateDefault[float | None, _DEFAULT_T2IMG_TIMEOUT]
    client_key: str | None
    size: CommonSize | str | tuple[int, int]
    count: int
    n: int
    background: BackgroundOption | str | tuple[int, int, int]
    output_compression: int
    stream: bool


if TYPE_CHECKING:
    class T2ImgParams(_T2ImgParams, extra_items=object): ...
else:
    T2ImgParams = _T2ImgParams


class T2ImgHealthProbeInput(TypedDict):  # type: ignore[name-defined]
    prompt: str
    kwargs: T2ImgParams


class _T2ImgClientInitParams(ServiceClientInitParams, total=False):
    supported_tasks: TaskType | Sequence[TaskType]
    support_image_prompt: bool
    support_audio_prompt: bool
    support_video_prompt: bool
    support_stream: bool
    completion_service: 'CompletionService | None'
    s2t_service: 'S2TService | None'


if TYPE_CHECKING:
    class T2ImgClientInitParams(_T2ImgClientInitParams, extra_items=object): ...
else:
    T2ImgClientInitParams = _T2ImgClientInitParams


class OpenAILikedT2ImgClientCreateParams(OpenAILikedClientCreateParams, _T2ImgClientInitParams, total=False): ...
class OpenRouterT2ImgClientCreateParams(OpenRouterClientCreateParams, _T2ImgClientInitParams, total=False): ...


def _normalize_task_set(tasks: TaskType | Sequence[TaskType] | None) -> frozenset[TaskType]:
    if tasks is None:
        return frozenset({'generate'})
    if isinstance(tasks, str):
        return frozenset({cast(TaskType, tasks)})
    return frozenset(cast(Sequence[TaskType], tasks))


def _serialize_task_set(tasks: Sequence[TaskType] | frozenset[TaskType]) -> str:
    return ','.join(sorted(str(task) for task in tasks))


def _deserialize_task_set(value: object) -> frozenset[TaskType]:
    if isinstance(value, str):
        return _normalize_task_set([part.strip() for part in value.split(',') if part.strip()])
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _normalize_task_set(cast(Sequence[TaskType], value))
    return frozenset()


def _normalize_size(size: object) -> str | None:
    if size is None:
        return None
    if isinstance(size, tuple) and len(size) == 2:
        return f'{int(size[0])}x{int(size[1])}'
    text = str(size).strip()
    return text or None


def _normalize_background(background: object) -> str | None:
    if background is None:
        return None
    if isinstance(background, tuple) and len(background) == 3:
        return '#%02x%02x%02x' % (int(background[0]), int(background[1]), int(background[2]))
    text = str(background).strip()
    return text or None


def _decode_data_url(value: str) -> bytes:
    return base64.b64decode(value.split(',', 1)[1] if ',' in value[:128] else value)


def _coerce_image(value: object) -> Image:
    if isinstance(value, Image):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return Image(bytes(value))
    if isinstance(value, str):
        if value.startswith('data:image/') or len(value) > 256 and not value.startswith(('http://', 'https://')) and not Path(value).exists():
            try:
                return Image(_decode_data_url(value))
            except Exception:
                pass
        return Image(value)
    if isinstance(value, dict):
        for key in ('b64_json', 'b64', 'base64', 'data', 'image'):
            data = value.get(key)
            if data:
                return _coerce_image(data)
        image_url = value.get('image_url') or value.get('url')
        if isinstance(image_url, dict):
            image_url = image_url.get('url')
        if image_url:
            return _coerce_image(image_url)
    raise ValueError(f'Cannot convert {type(value).__name__} to Image.')


def _as_image_list(value: Image | list[Image]) -> list[Image]:
    return value if isinstance(value, list) else [value]


def _single_or_list(images: list[Image], count: int) -> Image | list[Image]:
    return images if count > 1 else images[0]


def _compress_image(image: Image, compression: int | None) -> Image:
    if compression is None:
        return image
    level = min(100, max(0, int(compression)))
    src = image._ensure_loaded()
    fmt = (src.format or 'PNG').lower()
    if fmt == 'jpg':
        fmt = 'jpeg'
    out = BytesIO()
    save_kwargs: dict[str, Any] = {'format': fmt.upper()}
    if fmt in {'jpeg', 'webp'}:
        save_kwargs['quality'] = max(1, 100 - level)
        save_kwargs['optimize'] = True
    elif fmt == 'png':
        save_kwargs['compress_level'] = min(9, max(0, round(level / 100 * 9)))
        save_kwargs['optimize'] = True
    pil = src.convert('RGB') if fmt == 'jpeg' and src.mode in {'RGBA', 'LA', 'P'} else src
    pil.save(out, **save_kwargs)
    return Image(out.getvalue())


def _apply_background(image: Image, background: object) -> Image:
    return image.replace_background(background)


async def _prompt_to_text(
    prompt: 'LLMContent | Sequence[LLMContent]',
    *,
    support_image_prompt: bool = False,
    support_audio_prompt: bool = False,
    support_video_prompt: bool = False,
    completion_service: 'CompletionService | None' = None,
    s2t_service: 'S2TService | None' = None,
) -> str:
    from .completion import _expand_llm_part
    parts = prompt if isinstance(prompt, Sequence) and not isinstance(prompt, (str, bytes, bytearray, Image, Audio, Video)) else [prompt]
    text_parts: list[str] = []
    media_parts: list[Image | Audio | Video] = []
    unsupported_media: list[Image | Audio | Video] = []
    for part in parts:  # type: ignore[assignment]
        for expanded in await _expand_llm_part(cast(Any, part), document_mode='mixed'):
            if isinstance(expanded, str):
                text_parts.append(expanded)
            elif isinstance(expanded, Image):
                (media_parts if support_image_prompt else unsupported_media).append(expanded)
            elif isinstance(expanded, Audio):
                if support_audio_prompt:
                    media_parts.append(expanded)
                elif s2t_service is not None:
                    text_parts.append(await s2t_service.s2t(expanded))
                else:
                    unsupported_media.append(expanded)
            elif isinstance(expanded, Video):
                if support_video_prompt:
                    media_parts.append(expanded)
                elif s2t_service is not None:
                    text_parts.append(await s2t_service.s2t(expanded))
                else:
                    unsupported_media.append(expanded)
    text = ''.join(text_parts).strip()
    if unsupported_media:
        if completion_service is None:
            raise ValueError('This T2Img client does not support non-text prompts directly and no conversion service is configured.')
        content: list[Any] = [
            'Convert this text-to-image prompt into a pure text prompt. Preserve all user intent and describe any attached media succinctly. Return only the prompt. Text prompt: ',
            text,
            *unsupported_media,
        ]
        text = str(await completion_service.complete(messages=[{'role': 'user', 'content': content}], stream=True)).strip()
    if media_parts:
        text = ' '.join([text, *[f'[{type(media).__name__} prompt attached]' for media in media_parts]]).strip()
    if not text:
        raise ValueError('T2Img prompt is empty after normalization.')
    return text


class T2ImgClient(ServiceClientBase[T2ImgHealthProbeInput]):
    ServiceKind: ClassVar['AIServiceKind'] = 't2img'

    def __init__(self, **kwargs: Unpack[T2ImgClientInitParams]):
        completion_service = kwargs.pop('completion_service', None)
        s2t_service = kwargs.pop('s2t_service', None)
        supported_tasks_explicit = 'supported_tasks' in kwargs and kwargs.get('supported_tasks') is not None
        super().__init__(**kwargs)
        self.supported_tasks = _normalize_task_set(cast(Any, kwargs.get('supported_tasks')))
        self._supported_tasks_explicit = bool(supported_tasks_explicit)
        self._supported_tasks_runtime_known = bool(supported_tasks_explicit)
        self.support_image_prompt = bool(kwargs.get('support_image_prompt', False))
        self.support_audio_prompt = bool(kwargs.get('support_audio_prompt', False))
        self.support_video_prompt = bool(kwargs.get('support_video_prompt', False))
        self.support_stream = bool(kwargs.get('support_stream', False))
        self._completion_service = cast('CompletionService | None', completion_service)
        self._s2t_service = cast('S2TService | None', s2t_service)

    @classmethod
    @cache
    def TestingInput(cls) -> T2ImgHealthProbeInput:
        return {'prompt': 'A single red dot on a white background.', 'kwargs': {'size': '256x256', 'count': 1, 'timeout': 12.0}}

    async def probe_min_health(self) -> bool:
        try:
            probe = type(self).TestingInput()
            output = await self.generate(probe['prompt'], __skip_log__=True, **probe.get('kwargs', {}))
            return isinstance(output, Image) or bool(output)
        except Exception:
            return False

    @staticmethod
    def _extract_common_client_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        out = {
            'key': kwargs.get('key'),
            'max_concurrent': kwargs.get('max_concurrent'),
            'priority': kwargs.get('priority', 0.0),
            'strategy_lvl': kwargs.get('strategy_lvl', 0),
        }
        for key in ('supported_tasks', 'support_image_prompt', 'support_audio_prompt', 'support_video_prompt', 'support_stream', 'completion_service', 's2t_service'):
            if key in kwargs:
                out[key] = kwargs[key]
        return out

    @classmethod
    def CreateOpenAILikedT2ImgClient(cls, **kwargs: Unpack[OpenAILikedT2ImgClientCreateParams]) -> 'T2ImgClient':
        client_kwargs = cls._extract_common_client_kwargs(cast(dict[str, Any], kwargs))
        client_kwargs.update(_resolve_openai_liked_client_params(kwargs, service_name='t2img'))
        return OpenAILikedT2ImgClient(**client_kwargs)

    @classmethod
    def CreateOpenRouterT2ImgClient(cls, **kwargs: Unpack[OpenRouterT2ImgClientCreateParams]) -> 'T2ImgClient':
        client_kwargs = cls._extract_common_client_kwargs(cast(dict[str, Any], kwargs))
        client_kwargs.update(_resolve_openrouter_client_params(kwargs, service_name='t2img', model_env_keys=('OPENROUTER_T2IMG_MODEL',), default_model='black-forest-labs/flux.2-flex'))
        return OpenRouterT2ImgClient(**client_kwargs)

    def supports_task(self, task: TaskType) -> bool:
        return task in self.supported_tasks

    def dump_runtime_capabilities_for_shared_status(self) -> dict[str, str | int | float | bool | None]:
        if not self._supported_tasks_runtime_known:
            return {}
        return {'supported_tasks': _serialize_task_set(self.supported_tasks)}

    def load_runtime_capabilities_from_shared_status(self, status: dict[str, object] | object) -> None:
        if self._supported_tasks_explicit or not isinstance(status, dict):
            return
        raw_tasks = status.get('supported_tasks')
        if raw_tasks is None:
            return
        parsed_tasks = _deserialize_task_set(raw_tasks)
        if parsed_tasks:
            self.supported_tasks = parsed_tasks
            self._supported_tasks_runtime_known = True

    def update(self, **new_params: object) -> bool:
        params = dict(new_params)
        supported_tasks = params.pop('supported_tasks', None) if 'supported_tasks' in params else None
        feature_keys = ('support_image_prompt', 'support_audio_prompt', 'support_video_prompt', 'support_stream')
        feature_values = {key: params.pop(key) for key in feature_keys if key in params}
        completion_service = params.pop('completion_service', None) if 'completion_service' in params else None
        s2t_service = params.pop('s2t_service', None) if 's2t_service' in params else None
        if not super().update(**params):
            return False
        if 'supported_tasks' in new_params:
            self.supported_tasks = _normalize_task_set(cast(Any, supported_tasks))
            self._supported_tasks_explicit = True
            self._supported_tasks_runtime_known = True
        for key, value in feature_values.items():
            setattr(self, key, bool(value))
        if 'completion_service' in new_params:
            self._completion_service = cast('CompletionService | None', completion_service)
        if 's2t_service' in new_params:
            self._s2t_service = cast('S2TService | None', s2t_service)
        return True

    @overload
    async def generate(self, prompt: 'LLMContent | Sequence[LLMContent]', *, count: Literal[1] = 1, **kwargs: Unpack[T2ImgParams]) -> Image: ...

    @overload
    async def generate(self, prompt: 'LLMContent | Sequence[LLMContent]', *, n: Literal[1], **kwargs: Unpack[T2ImgParams]) -> Image: ...

    @overload
    async def generate(self, prompt: 'LLMContent | Sequence[LLMContent]', **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]: ...

    async def generate(self, prompt: 'LLMContent | Sequence[LLMContent]', **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]:
        exec_kwargs = dict(kwargs)
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, _T2ImgParams)
        req_timeout = float(exec_kwargs.pop('timeout'))  # type: ignore[arg-type]
        count = int(exec_kwargs.pop('count', exec_kwargs.pop('n', 1)) or 1)
        compression = exec_kwargs.pop('output_compression', None)
        background = exec_kwargs.get('background')
        if exec_kwargs.pop('stream', False) and not self.support_stream:
            exec_kwargs['stream'] = False
        exec_kwargs.pop('output_format', None)
        request = self._log_request_payload('t2img_generate', (prompt,), dict(exec_kwargs, count=count))
        metadata = self._log_extra_metadata('t2img_generate', (prompt,), dict(exec_kwargs, count=count))
        result = cast(
            Image | list[Image],
            await self._trace_async_call(
                't2img_generate',
                lambda: asyncio.wait_for(self._generate_impl(prompt, count=count, **exec_kwargs), timeout=req_timeout),
                request=request,
                metadata=metadata,
                skip_log=skip_log,
            ),
        )
        images = [_apply_background(img, background) for img in _as_image_list(result)]
        images = [_compress_image(img, cast(int | None, compression)) for img in images]
        return _single_or_list(images, count)

    async def _prompt_to_text(self, prompt: 'LLMContent | Sequence[LLMContent]') -> str:
        return await _prompt_to_text(
            prompt,
            support_image_prompt=self.support_image_prompt,
            support_audio_prompt=self.support_audio_prompt,
            support_video_prompt=self.support_video_prompt,
            completion_service=self._completion_service,
            s2t_service=self._s2t_service,
        )

    async def generate_stream(self, prompt: 'LLMContent | Sequence[LLMContent]', **kwargs: Unpack[T2ImgParams]) -> AsyncGenerator[Image, None]:
        exec_kwargs = dict(kwargs)
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, _T2ImgParams)
        req_timeout = float(exec_kwargs.pop('timeout'))  # type: ignore[arg-type]
        count = int(exec_kwargs.pop('count', exec_kwargs.pop('n', 1)) or 1)
        exec_kwargs['stream'] = True
        request = self._log_request_payload('t2img_generate_stream', (prompt,), dict(exec_kwargs, count=count))
        metadata = self._log_extra_metadata('t2img_generate_stream', (prompt,), dict(exec_kwargs, count=count))
        started_at = asyncio.get_running_loop().time()
        emitted = 0
        try:
            stream_iter = self._generate_stream_impl(prompt, count=count, **exec_kwargs).__aiter__()
            while True:
                try:
                    image = await asyncio.wait_for(stream_iter.__anext__(), timeout=req_timeout)
                except StopAsyncIteration:
                    break
                emitted += 1
                yield image
        except Exception as exc:
            if not skip_log:
                self._record_call_log(
                    operation='t2img_generate_stream',
                    started_at=started_at,
                    success=False,
                    request=request,
                    error=exc,
                    metadata=metadata,
                )
            raise
        if not skip_log:
            self._record_call_log(
                operation='t2img_generate_stream',
                started_at=started_at,
                success=True,
                request=request,
                response={'streamed_images': emitted},
                metadata=metadata,
            )

    async def _generate_stream_impl(self, prompt: 'LLMContent | Sequence[LLMContent]', *, count: int = 1, **kwargs: object) -> AsyncGenerator[Image, None]:
        if self.support_stream:
            images = await self.generate(prompt, count=count, **cast(Any, kwargs))
        else:
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop('stream', None)
            images = await self.generate(prompt, count=count, **cast(Any, fallback_kwargs))
        for image in _as_image_list(cast(Image | list[Image], images)):
            yield image

    async def _generate_impl(self, prompt: 'LLMContent | Sequence[LLMContent]', *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        raise NotImplementedError

    @overload
    async def edit(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]', *, count: Literal[1] = 1, **kwargs: Unpack[T2ImgParams]) -> Image: ...

    @overload
    async def edit(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]', *, n: Literal[1], **kwargs: Unpack[T2ImgParams]) -> Image: ...

    @overload
    async def edit(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]', **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]: ...

    async def edit(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]', **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]:
        exec_kwargs = dict(kwargs)
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, _T2ImgParams)
        req_timeout = float(exec_kwargs.pop('timeout'))  # type: ignore[arg-type]
        count = int(exec_kwargs.pop('count', exec_kwargs.pop('n', 1)) or 1)
        compression = exec_kwargs.pop('output_compression', None)
        background = exec_kwargs.get('background')
        if exec_kwargs.pop('stream', False) and not self.support_stream:
            exec_kwargs['stream'] = False
        exec_kwargs.pop('output_format', None)
        request = self._log_request_payload('t2img_edit', (image, prompt), dict(exec_kwargs, count=count))
        metadata = self._log_extra_metadata('t2img_edit', (image, prompt), dict(exec_kwargs, count=count))
        result = cast(Image | list[Image], await self._trace_async_call(
            't2img_edit',
            lambda: asyncio.wait_for(self._edit_impl(image, prompt, count=count, **exec_kwargs), timeout=req_timeout),
            request=request,
            metadata=metadata,
            skip_log=skip_log,
        ))
        images = [_apply_background(img, background) for img in _as_image_list(result)]
        images = [_compress_image(img, cast(int | None, compression)) for img in images]
        return _single_or_list(images, count)

    async def _edit_impl(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]', *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        raise NotImplementedError

    @overload
    async def variation(self, image: Image, *, count: Literal[1] = 1, **kwargs: Unpack[T2ImgParams]) -> Image: ...

    @overload
    async def variation(self, image: Image, *, n: Literal[1], **kwargs: Unpack[T2ImgParams]) -> Image: ...

    @overload
    async def variation(self, image: Image, **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]: ...

    async def variation(self, image: Image, **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]:
        exec_kwargs = dict(kwargs)
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, _T2ImgParams)
        req_timeout = float(exec_kwargs.pop('timeout'))  # type: ignore[arg-type]
        count = int(exec_kwargs.pop('count', exec_kwargs.pop('n', 1)) or 1)
        compression = exec_kwargs.pop('output_compression', None)
        background = exec_kwargs.get('background')
        if exec_kwargs.pop('stream', False) and not self.support_stream:
            exec_kwargs['stream'] = False
        exec_kwargs.pop('output_format', None)
        request = self._log_request_payload('t2img_variation', (image,), dict(exec_kwargs, count=count))
        metadata = self._log_extra_metadata('t2img_variation', (image,), dict(exec_kwargs, count=count))
        result = cast(Image | list[Image], await self._trace_async_call(
            't2img_variation',
            lambda: asyncio.wait_for(self._variation_impl(image, count=count, **exec_kwargs), timeout=req_timeout),
            request=request,
            metadata=metadata,
            skip_log=skip_log,
        ))
        images = [_apply_background(img, background) for img in _as_image_list(result)]
        images = [_compress_image(img, cast(int | None, compression)) for img in images]
        return _single_or_list(images, count)

    async def _variation_impl(self, image: Image, *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        raise NotImplementedError


class OpenAILikedT2ImgClient(T2ImgClient, OpenAILikedClientMixin, type='openai'):
    @classmethod
    def CreateFromConfig(cls, **kwargs: object) -> 'OpenAILikedT2ImgClient':
        return cast(Any, T2ImgClient.CreateOpenAILikedT2ImgClient(**cast(Any, kwargs)))

    def __init__(self, apikey: str | None, base_url: str, model: str | None = None, ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None' = None, **kwargs: Unpack[T2ImgClientInitParams]):
        explicit_supported_tasks = 'supported_tasks' in kwargs and kwargs.get('supported_tasks') is not None
        if 'supported_tasks' not in kwargs:
            kwargs['supported_tasks'] = ('generate', 'edit', 'variation')
        super().__init__(**kwargs)
        self._supported_tasks_explicit = bool(explicit_supported_tasks)
        self._supported_tasks_runtime_known = bool(explicit_supported_tasks)
        resolved_model = model or _env_first('OPENAI_T2IMG_MODEL') or 'gpt-image-1'
        self._init_openai_liked_client(apikey=apikey, base_url=base_url, model=resolved_model, ssh_tunnel=ssh_tunnel)

    @property
    def model(self) -> str | None:
        return self._model

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

    def _image_urls(self, suffix: str) -> list[str]:
        return self._openai_liked_endpoint_candidates(suffix)

    def _mark_task_unsupported(self, task: TaskType) -> None:
        if task in self.supported_tasks:
            self.supported_tasks = frozenset(item for item in self.supported_tasks if item != task)
        self._supported_tasks_runtime_known = True

    def _raise_missing_task_endpoint(self, task: TaskType, exc: aiohttp.ClientResponseError) -> None:
        self._mark_task_unsupported(task)
        raise NotImplementedError(f'OpenAI-liked T2Img {task} is not supported by this backend.') from exc

    async def probe_runtime_capabilities_on_init(self) -> None:
        if self._supported_tasks_explicit or self._supported_tasks_runtime_known:
            return
        probe_image = Image(PILImage.new('RGBA', (16, 16), (255, 0, 0, 255)))
        if 'edit' in self.supported_tasks:
            try:
                await self.edit(probe_image, 'Keep the image unchanged.', size='256x256', __skip_log__=True)
            except NotImplementedError:
                self._mark_task_unsupported('edit')
            except Exception:
                pass
        if 'variation' in self.supported_tasks:
            try:
                await self.variation(probe_image, size='256x256', __skip_log__=True)
            except NotImplementedError:
                self._mark_task_unsupported('variation')
            except Exception:
                pass
        self._supported_tasks_runtime_known = True

    async def _request_json(self, suffix: str, *, payload: dict[str, object] | None = None, form: aiohttp.FormData | None = None, timeout: float | None = None) -> dict[str, Any]:
        last_not_found: aiohttp.ClientResponseError | None = None
        for url_index, url in enumerate(self._image_urls(suffix)):
            for attempt in range(2):
                session = await self._get_session()
                try:
                    async with session.post(
                        url,
                        json=payload if form is None else None,
                        data=form,
                        headers=self._openai_liked_headers(content_type=None if form is not None else 'application/json'),
                        timeout=aiohttp.ClientTimeout(total=float(timeout or _DEFAULT_T2IMG_TIMEOUT)),
                    ) as response:
                        try:
                            response.raise_for_status()
                        except aiohttp.ClientResponseError as exc:
                            if exc.status == 404 and url_index < len(self._image_urls(suffix)) - 1:
                                last_not_found = exc
                                break
                            raise
                        return cast(dict[str, Any], await response.json())
                except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError, aiohttp.ClientConnectionError):
                    await self._close_session()
                    if attempt == 0:
                        continue
                    raise
        if last_not_found is not None:
            raise last_not_found
        raise RuntimeError('OpenAI-liked T2Img request failed without response.')

    def _extract_images(self, raw: dict[str, Any]) -> list[Image]:
        rows = raw.get('data', [])
        if not isinstance(rows, list):
            raise ValueError('OpenAI-liked T2Img response missing data list.')
        return [_coerce_image(row) for row in rows]

    def _build_common_payload(self, params: dict[str, object], *, count: int) -> dict[str, object]:
        payload: dict[str, object] = {'model': params.pop('model', None) or self._model or 'gpt-image-1', 'n': count}
        for source_key, target_key in (('size', 'size'), ('quality', 'quality'), ('style', 'style'), ('moderation', 'moderation'), ('user', 'user'), ('partial_images', 'partial_images')):
            value = params.pop(source_key, None)
            if value is not None:
                payload[target_key] = _normalize_size(value) if target_key == 'size' else value
        params.pop('response_format', None)
        params.pop('output_format', None)
        params.pop('output_compression', None)
        params.pop('stream', None)
        for key, value in list(params.items()):
            if value is not None and not str(key).startswith('__'):
                payload[str(key)] = params.pop(key)
        background = _normalize_background(params.pop('background', None))
        if background is not None:
            payload['background'] = background
        return payload

    async def _generate_impl(self, prompt: 'LLMContent | Sequence[LLMContent]', *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        params = dict(kwargs)
        payload = self._build_common_payload(params, count=count)
        payload['prompt'] = await self._prompt_to_text(prompt)
        raw = await self._request_json('/images/generations', payload=payload, timeout=cast(float | None, params.pop('timeout', None)))
        return _single_or_list(self._extract_images(raw), count)

    async def _edit_impl(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]', *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        params = dict(kwargs)
        form = aiohttp.FormData()
        form.add_field('model', str(params.pop('model', None) or self._model or 'gpt-image-1'))
        form.add_field('prompt', await self._prompt_to_text(prompt))
        form.add_field('n', str(count))
        size = _normalize_size(params.pop('size', None))
        if size:
            form.add_field('size', size)
        background = _normalize_background(params.pop('background', None))
        if background:
            form.add_field('background', background)
        mask = params.pop('mask', None)
        for key in ('quality', 'input_fidelity', 'moderation', 'partial_images', 'user'):
            value = params.pop(key, None)
            if value is not None:
                form.add_field(key, str(value))
        params.pop('response_format', None)
        params.pop('output_format', None)
        params.pop('output_compression', None)
        params.pop('stream', None)
        for key, value in list(params.items()):
            if value is not None and not str(key).startswith('__'):
                form.add_field(str(key), str(params.pop(key)))
        images = list(image) if isinstance(image, Sequence) and not isinstance(image, Image) else [cast(Image, image)]
        field_name = 'image[]' if len(images) > 1 else 'image'
        for idx, img in enumerate(images):
            form.add_field(field_name, img.to_bytes(format='png'), filename=f'image_{idx}.png', content_type='image/png')
        if mask is not None:
            mask_img = _coerce_image(mask)
            form.add_field('mask', mask_img.to_bytes(format='png'), filename='mask.png', content_type='image/png')
        try:
            raw = await self._request_json('/images/edits', form=form, timeout=cast(float | None, params.pop('timeout', None)))
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                self._raise_missing_task_endpoint('edit', exc)
            raise
        return _single_or_list(self._extract_images(raw), count)

    async def _variation_impl(self, image: Image, *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        params = dict(kwargs)
        form = aiohttp.FormData()
        form.add_field('image', image.to_bytes(format='png'), filename='image.png', content_type='image/png')
        form.add_field('n', str(count))
        model = params.pop('model', None) or self._model
        if model:
            form.add_field('model', str(model))
        size = _normalize_size(params.pop('size', None))
        if size:
            form.add_field('size', size)
        for key in ('quality', 'style', 'moderation', 'partial_images', 'user'):
            value = params.pop(key, None)
            if value is not None:
                form.add_field(key, str(value))
        params.pop('response_format', None)
        params.pop('output_format', None)
        params.pop('output_compression', None)
        params.pop('stream', None)
        for key, value in list(params.items()):
            if value is not None and not str(key).startswith('__'):
                form.add_field(str(key), str(params.pop(key)))
        try:
            raw = await self._request_json('/images/variations', form=form, timeout=cast(float | None, params.pop('timeout', None)))
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                self._raise_missing_task_endpoint('variation', exc)
            raise
        return _single_or_list(self._extract_images(raw), count)


class OpenRouterT2ImgClient(T2ImgClient, OpenAILikedClientMixin, type='openrouter'):
    @classmethod
    def CreateFromConfig(cls, **kwargs: object) -> 'OpenRouterT2ImgClient':
        return cast(Any, T2ImgClient.CreateOpenRouterT2ImgClient(**cast(Any, kwargs)))

    def __init__(self, apikey: str | None = None, base_url: str | None = None, model: str | None = None, ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None' = None, **kwargs: Unpack[T2ImgClientInitParams]):
        if 'supported_tasks' not in kwargs:
            kwargs['supported_tasks'] = ('generate',)
        super().__init__(**kwargs)
        self._supported_tasks_runtime_known = True
        resolved = _resolve_openrouter_client_params({'apikey': apikey, 'base_url': base_url, 'model': model, 'ssh_tunnel': ssh_tunnel}, service_name='t2img', model_env_keys=('OPENROUTER_T2IMG_MODEL',), default_model='black-forest-labs/flux.2-flex')
        self._init_openai_liked_client(apikey=cast(str, resolved['apikey']), base_url=cast(str, resolved['base_url']), model=cast(str | None, resolved['model']), ssh_tunnel=cast('SSHTunnelConfig | dict[str, Any] | str | None', resolved['ssh_tunnel']))

    @property
    def model(self) -> str | None:
        return self._model

    def _chat_completions_url(self) -> str:
        return self._openai_liked_endpoint('/chat/completions')

    async def _generate_impl(self, prompt: 'LLMContent | Sequence[LLMContent]', *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        params = dict(kwargs)
        payload: dict[str, Any] = {
            'model': params.pop('model', None) or self._model or 'black-forest-labs/flux.2-flex',
            'messages': [{'role': 'user', 'content': await self._prompt_to_text(prompt)}],
            'modalities': ['image'],
        }
        if count > 1:
            payload['n'] = count
        for key in ('temperature', 'top_p', 'seed', 'user'):
            value = params.pop(key, None)
            if value is not None:
                payload[key] = value
        params.pop('response_format', None)
        params.pop('output_format', None)
        params.pop('output_compression', None)
        params.pop('background', None)
        params.pop('stream', None)
        timeout = aiohttp.ClientTimeout(total=float(params.pop('timeout', _DEFAULT_T2IMG_TIMEOUT)))
        session = await self._get_session()
        async with session.post(self._chat_completions_url(), json=payload, headers=self._openrouter_headers(), timeout=timeout) as response:
            response.raise_for_status()
            raw = cast(dict[str, Any], await response.json())
        images: list[Image] = []
        for choice in raw.get('choices', []) if isinstance(raw.get('choices'), list) else []:
            message = choice.get('message', {}) if isinstance(choice, dict) else {}
            for item in message.get('images', []) if isinstance(message.get('images'), list) else []:
                images.append(_coerce_image(item))
        if not images:
            raise ValueError('OpenRouter T2Img response did not include assistant message images.')
        return _single_or_list(images, count)

    async def _edit_impl(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]', *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        raise NotImplementedError('OpenRouter T2Img edit is not supported by this client.')

    async def _variation_impl(self, image: Image, *, count: int = 1, **kwargs: object) -> Image | list[Image]:
        raise NotImplementedError('OpenRouter T2Img variation is not supported by this client.')


class T2ImgService(ServiceBase):
    DefaultProbeInterval = ProbeInterval(interval=600.0, decay=2.0, max_interval=86400.0)

    class DefaultClientParams:
        BASIC: T2ImgClientInitParams = {'max_concurrent': ConcurrentPool('t2img', 20)}

    def __init__(self, *clients: T2ImgClient | ServiceClient[T2ImgClient], completion_service: 'CompletionService | None' = None, s2t_service: 'S2TService | None' = None, **kwargs: Unpack[ServiceInitParams]):
        super().__init__(*clients, **kwargs)
        self._completion_service = completion_service
        self._s2t_service = s2t_service
        for client in self.clients:
            if completion_service is not None and getattr(client, '_completion_service', None) is None:
                client.update(completion_service=completion_service)
            if s2t_service is not None and getattr(client, '_s2t_service', None) is None:
                client.update(s2t_service=s2t_service)

    @classmethod
    def Default(cls) -> 'T2ImgService':
        cls.WaitUntilRuntimeReady()
        if existing := cls.GetInstance('default'):
            return existing
        from .config import AIServicesConfig
        cfg = AIServicesConfig.Global()
        if cfg is not None:
            svc = cfg.t2img.get_default()
            if svc is not None:
                cfg.t2img.preload_service_instances()
                return cast('T2ImgService', svc)
        clients: list[T2ImgClient] = []
        _append_env_default_client(clients, T2ImgClient.CreateOpenAILikedT2ImgClient, logger=_logger, description='OpenAI-compatible T2Img', env_keys=('OPENAI_APIKEY', 'OPENAI_API_KEY'), factory_kwargs=cls.DefaultClientParams.BASIC)
        _append_env_default_client(clients, T2ImgClient.CreateOpenRouterT2ImgClient, logger=_logger, description='OpenRouter T2Img', env_keys=('OPENROUTER_APIKEY', 'OPENROUTER_API_KEY'), factory_kwargs=cls.DefaultClientParams.BASIC)
        if not clients:
            raise RuntimeError('Cannot create default T2ImgService: no client could be initialized. Please set OPENAI_APIKEY / OPENAI_API_KEY / OPENROUTER_APIKEY / OPENROUTER_API_KEY.')
        return cls(*clients, key='default')

    def update(self, **new_params: object) -> bool:
        params = dict(new_params)
        completion_service = params.pop('completion_service', None) if 'completion_service' in params else None
        s2t_service = params.pop('s2t_service', None) if 's2t_service' in params else None
        if not super().update(**params):
            return False
        if 'completion_service' in new_params:
            self._completion_service = cast('CompletionService | None', completion_service)
            for client in self.clients:
                client.update(completion_service=self._completion_service)
        if 's2t_service' in new_params:
            self._s2t_service = cast('S2TService | None', s2t_service)
            for client in self.clients:
                client.update(s2t_service=self._s2t_service)
        return True

    async def _prompt_to_text(self, prompt: 'LLMContent | Sequence[LLMContent]') -> str:
        return await _prompt_to_text(prompt, completion_service=self._completion_service, s2t_service=self._s2t_service)

    async def _fallback_prompt_for_edit(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]') -> str:
        text = await self._prompt_to_text(prompt)
        if self._completion_service is None:
            return text
        images = list(image) if isinstance(image, Sequence) and not isinstance(image, Image) else [cast(Image, image)]
        content: list[Any] = [
            'Create a detailed text-to-image generation prompt that applies this edit instruction to the provided image(s). Return only the prompt. Instruction: ',
            text,
            *images,
        ]
        return str(await self._completion_service.complete(messages=[{'role': 'user', 'content': content}], stream=True)).strip() or text

    async def _fallback_prompt_for_variation(self, image: Image) -> str:
        if self._completion_service is None:
            return 'Create a high-quality variation of the provided image.'
        return str(await self._completion_service.complete(messages=[{'role': 'user', 'content': ['Create a detailed text-to-image generation prompt for a visually similar variation of this image. Return only the prompt.', image]}], stream=True)).strip()

    async def generate(self, prompt: 'LLMContent | Sequence[LLMContent]', **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]:
        _ctx, token = enter_service_context('t2img')
        request_kwargs = dict(kwargs)
        selected_client_key = cast(str | None, request_kwargs.pop('client_key', None))
        try:
            candidates = self._resolve_service_client_candidates(self._clients, selected_client_key)
            async def _action(client: T2ImgClient) -> Image | list[Image]:
                if not client.supports_task('generate'):
                    raise RuntimeError(f'T2Img client {client.key} does not support generate.')
                return await client.generate(prompt, **cast(T2ImgParams, request_kwargs))
            return cast(Image | list[Image], await self._run_with_failover(candidates, _action, error_prefix='All T2Img generate clients failed'))
        finally:
            exit_service_context(token)

    async def generate_stream(self, prompt: 'LLMContent | Sequence[LLMContent]', **kwargs: Unpack[T2ImgParams]) -> AsyncGenerator[Image, None]:
        _ctx, token = enter_service_context('t2img')
        request_kwargs = dict(kwargs)
        selected_client_key = cast(str | None, request_kwargs.pop('client_key', None))
        try:
            candidates = self._resolve_service_client_candidates(self._clients, selected_client_key)
            async def _action(client: T2ImgClient) -> list[Image]:
                if not client.supports_task('generate'):
                    raise RuntimeError(f'T2Img client {client.key} does not support generate.')
                images: list[Image] = []
                async for image in client.generate_stream(prompt, **cast(T2ImgParams, request_kwargs)):
                    images.append(image)
                return images
            result = await self._run_with_failover(candidates, _action, error_prefix='All T2Img stream clients failed')
            for image in cast(list[Image], result):
                yield image
        finally:
            exit_service_context(token)

    async def edit(self, image: Image | Sequence[Image], prompt: 'LLMContent | Sequence[LLMContent]', **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]:
        _ctx, token = enter_service_context('t2img')
        request_kwargs = dict(kwargs)
        selected_client_key = cast(str | None, request_kwargs.pop('client_key', None))
        fallback_prompt: str | None = None
        try:
            candidates = self._resolve_service_client_candidates(self._clients, selected_client_key)
            async def _action(client: T2ImgClient) -> Image | list[Image]:
                nonlocal fallback_prompt
                if client.supports_task('edit'):
                    try:
                        return await client.edit(image, prompt, **cast(T2ImgParams, request_kwargs))
                    except NotImplementedError:
                        if not client.supports_task('generate'):
                            raise
                if client.supports_task('generate'):
                    if fallback_prompt is None:
                        fallback_prompt = await self._fallback_prompt_for_edit(image, prompt)
                    return await client.generate(fallback_prompt, **cast(T2ImgParams, request_kwargs))
                raise RuntimeError(f'T2Img client {client.key} does not support edit or generate fallback.')
            return cast(Image | list[Image], await self._run_with_failover(candidates, _action, error_prefix='All T2Img edit clients failed'))
        finally:
            exit_service_context(token)

    async def variation(self, image: Image, **kwargs: Unpack[T2ImgParams]) -> Image | list[Image]:
        _ctx, token = enter_service_context('t2img')
        request_kwargs = dict(kwargs)
        selected_client_key = cast(str | None, request_kwargs.pop('client_key', None))
        fallback_prompt: str | None = None
        try:
            candidates = self._resolve_service_client_candidates(self._clients, selected_client_key)
            async def _action(client: T2ImgClient) -> Image | list[Image]:
                nonlocal fallback_prompt
                if client.supports_task('variation'):
                    try:
                        return await client.variation(image, **cast(T2ImgParams, request_kwargs))
                    except NotImplementedError:
                        if not client.supports_task('generate'):
                            raise
                if client.supports_task('generate'):
                    if fallback_prompt is None:
                        fallback_prompt = await self._fallback_prompt_for_variation(image)
                    return await client.generate(fallback_prompt, **cast(T2ImgParams, request_kwargs))
                raise RuntimeError(f'T2Img client {client.key} does not support variation or generate fallback.')
            return cast(Image | list[Image], await self._run_with_failover(candidates, _action, error_prefix='All T2Img variation clients failed'))
        finally:
            exit_service_context(token)


__all__ += ['CommonSize', 'BackgroundOption', 'TaskType', 'T2ImgInput', 'T2ImgParams', 'T2ImgClient', 'OpenAILikedT2ImgClient', 'OpenRouterT2ImgClient', 'T2ImgService']
