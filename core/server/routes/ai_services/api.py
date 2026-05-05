# -*- coding: utf-8 -*-
"""AI service API routes (production endpoints)."""
import json
import base64
import logging
import time as _time

from typing import Any, AsyncGenerator, Literal, Optional, Protocol, Union
from fastapi import FastAPI, Form, HTTPException, UploadFile, File, Header, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import ConfigDict, Field, field_validator

from core.utils.type_utils import AdvancedBaseModel
from core.ai.shared import AIServiceKind
from core.utils.data_structs import Audio, Image
from core.utils.text_utils import Language

from ...app import on_before_app_created
from ...data_types.config import Config

logger = logging.getLogger(__name__)


def _env_first(*keys: str) -> str:
    import os
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return ''


def _public(func):
    setattr(func, "__public__", True)
    return func


class _AIAliasRouteRegistrar:
    def __init__(self, app: FastAPI, *, internal_prefixes: list[str], public_prefixes: list[str]):
        self._app = app
        self._internal_prefixes = internal_prefixes
        self._public_prefixes = public_prefixes

    def _alias_path(self, path: str, prefix: str) -> str:
        if path == "/ai":
            return prefix
        if path.startswith("/ai/"):
            return prefix + path[len("/ai"):]
        return path

    def get(self, path: str, **kwargs: Any):
        def _decorator(func):
            for prefix in self._internal_prefixes:
                self._app.get(self._alias_path(path, prefix), **kwargs)(func)
            if getattr(func, "__public__", False):
                for prefix in self._public_prefixes:
                    self._app.get(self._alias_path(path, prefix), **kwargs)(func)
            return func

        return _decorator

    def post(self, path: str, **kwargs: Any):
        def _decorator(func):
            for prefix in self._internal_prefixes:
                self._app.post(self._alias_path(path, prefix), **kwargs)(func)
            if getattr(func, "__public__", False):
                for prefix in self._public_prefixes:
                    self._app.post(self._alias_path(path, prefix), **kwargs)(func)
            return func

        return _decorator


# ══════════════════════════════════════════════════════════════════════════════
# Chat message type helpers
# ══════════════════════════════════════════════════════════════════════════════

# Standard OpenAI roles
_OPENAI_ROLES = frozenset({"system", "user", "assistant", "tool", "function", "developer"})

# OpenAI multi-modal content part types (extensible)
_OPENAI_CONTENT_TYPES = frozenset({"text", "image_url", "image", "input_audio", "audio", "file", "video", "document"})


class OpenAITextPart(AdvancedBaseModel):
    '''OpenAI message content part — plain text.'''
    type: Literal['text'] = 'text'
    text: str


class OpenAIImageURLPart(AdvancedBaseModel):
    '''OpenAI message content part — image URL / base64.'''
    type: Literal['image_url', 'image']
    image_url: dict[str, Any] | None = None
    image: dict[str, Any] | None = None


class OpenAIAudioPart(AdvancedBaseModel):
    '''OpenAI message content part — audio input.'''
    type: Literal['input_audio', 'audio']
    input_audio: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None


class OpenAIFilePart(AdvancedBaseModel):
    '''OpenAI message content part — file reference (supports FileID dicts).'''
    type: Literal['file', 'video', 'document']
    file: dict[str, Any] | None = None
    video: dict[str, Any] | None = None
    document: dict[str, Any] | None = None


# Union of all content parts; plain dict is the fallback for unknown types.
OpenAIContentPart = Union[OpenAITextPart, OpenAIImageURLPart, OpenAIAudioPart, OpenAIFilePart, dict[str, Any]]


class _CompletionCallable(Protocol):
    async def complete(self, **kwargs: Any) -> str: ...
    async def stream_complete(self, **kwargs: Any) -> AsyncGenerator[dict[str, Any], None]: ...
    def _peek_latest_token_usage(self) -> dict[str, Any] | None: ...


def _validate_messages(messages: list[Any]) -> list[dict[str, Any]]:
    '''Validate and normalise a list of chat messages.

    Accepts both the OpenAI wire format and the custom format.  Each message
    must contain at minimum a ``role`` key.  Unknown roles are allowed to support
    custom agents; a warning is logged when they appear.
    '''
    validated: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise ValueError(f"messages[{i}]: expected a dict, got {type(msg).__name__!r}")
        if 'role' not in msg:
            raise ValueError(f"messages[{i}]: missing required field 'role'")
        role = str(msg['role'])
        if role not in _OPENAI_ROLES:
            logger.warning("AI completion request: non-standard role %r in messages[%d]", role, i)
        content = msg.get('content')
        if content is None and 'parts' not in msg and 'text' not in msg:
            raise ValueError(
                f"messages[{i}]: 'content' is required (or use 'parts' / 'text' for the custom format)"
            )
        validated.append(dict(msg))
    return validated


# ══════════════════════════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════════════════════════

class _BaseCompletionRequest(AdvancedBaseModel):
    messages: list[dict[str, Any]]
    """聊天消息列表。

    支持两种格式（可混用）：

    **OpenAI 格式**::

        {"role": "user", "content": "Hello"}
        {"role": "user", "content": [{"type": "text", "text": "Describe this."}, {"type": "image_url", "image_url": {...}}]}

    **自定义格式**::

        {"role": "user", "content": <ChatMsgContent | list[ChatMsgContent]>}

    FileID dict 可直接作为 content part 传入；服务层会自动拉取对应文件字节。
    每条消息必须包含 ``role`` 字段；``content`` 字段必须存在（或使用 ``parts``/``text`` 替代）。
    """

    @field_validator('messages', mode='before')
    @classmethod
    def _validate_messages(cls, v: Any) -> list[dict[str, Any]]:
        if not isinstance(v, list):
            raise ValueError("'messages' must be a list")
        return _validate_messages(v)

    max_tokens: int|None = None
    """最大生成 token 数"""
    reasoning: bool = False
    """是否启用推理模式"""
    stream: bool = False
    """是否使用 SSE 流式输出"""
    temperature: Optional[float] = None
    """采样温度, None 使用默认值"""
    top_p: Optional[float] = None
    """Nucleus sampling 参数"""
    top_k: Optional[int] = None
    """Top-K 采样参数"""
    presence_penalty: Optional[float] = None
    """存在惩罚"""
    frequency_penalty: Optional[float] = None
    """频率惩罚"""
    service_key: str | None = None
    """Completion service instance key; None/empty means default."""


class CompletionRequest(_BaseCompletionRequest):
    """默认 CompletionService 请求体。"""


class ThinkThinkSynCompleteRequest(_BaseCompletionRequest):
    """ThinkThinkSyn 特殊测试接口请求体。"""

    model: Optional[str] = None
    """指定使用的模型名称。"""
    base_url: Optional[str] = None
    """临时客户端接口根地址；None 表示使用环境/默认。"""
    apikey: Optional[str] = None
    """临时客户端 API Key；None 表示使用环境变量。"""


class OpenRouterCompleteRequest(_BaseCompletionRequest):
    """OpenRouter 特殊测试接口请求体。"""

    model: Optional[str] = None
    """指定使用的模型名称。"""
    base_url: Optional[str] = None
    """临时客户端接口根地址；None 表示使用环境/默认。"""
    apikey: Optional[str] = None
    """临时客户端 API Key；None 表示使用环境变量。"""


class TranslateRequest(AdvancedBaseModel):
    text: str
    """要翻译的文本"""
    target_language: str = "zh-tw"
    """目标语言代码"""


class TranslateResponse(AdvancedBaseModel):
    translated: str
    """翻译结果"""
    elapsed_ms: int | None = None
    request_echo: dict[str, Any] | None = None


class DetectLanguageRequest(AdvancedBaseModel):
    text: str
    """要检测语言的文本"""


class DetectLanguageResponse(AdvancedBaseModel):
    language: str | None
    """检测到的语言代码"""
    elapsed_ms: int | None = None
    request_echo: dict[str, Any] | None = None


class SummarizeRequest(AdvancedBaseModel):
    text: str
    """要摘要的文本"""
    prompt: str | None = None
    """自定义摘要指令"""
    chunk_size: int | None = None
    """每个文本块的最大词数, None 使用默认值"""
    sliding_window_size: float = 0.15
    """相邻块的重叠比例 (0–1)"""
    stream: bool = False
    """是否使用流式请求"""


class SummarizeResponse(AdvancedBaseModel):
    summary: str
    """摘要结果"""
    elapsed_ms: int | None = None
    token_usage: 'TokenUsageResponse | None' = None


class CompletionRerankRequest(AdvancedBaseModel):
    query: str
    """查询文本"""
    candidates: list[str]
    """候选文本列表"""
    prompt: str | None = None
    """自定义排序指令"""
    stream: bool = True
    """是否使用流式请求"""


class T2SRequest(AdvancedBaseModel):
    text: str
    """要合成语音的文本"""
    chunk_size: int | None = None
    """流式输出时的切块大小（字节）"""
    service_key: str | None = None
    """T2S service instance key; None/empty means default."""


class T2SResponse(AdvancedBaseModel):
    audio_base64: str
    """音频 Base64 编码"""
    format: str = "wav"
    """音频格式"""
    mime_type: str = "audio/wav"
    audio_bytes: int | None = None
    elapsed_ms: int | None = None
    request_echo: dict[str, Any] | None = None


class EmbeddingRequest(AdvancedBaseModel):
    text: str | None = None
    """要向量化的单条文本"""
    texts: list[str] | None = None
    """要向量化的文本列表"""
    use_cache: bool = True
    """是否读取 embedding 缓存"""
    save_cache: bool = True
    """是否写入 embedding 缓存"""
    service_key: str | None = None
    """Embedding service instance key; None/empty means default."""


class EmbeddingRerankRequest(AdvancedBaseModel):
    query: str
    """查询文本"""
    candidates: list[str]
    """候选文本列表"""
    service_key: str | None = None
    """Embedding service instance key; None/empty means default."""


class EmbeddingChunkingRequest(AdvancedBaseModel):
    content: str
    """要分块的长文本"""
    max_word_count: int = Field(default=512)
    """每块最大估算词数"""
    use_cache: bool = True
    """是否读取 embedding 缓存"""
    save_cache: bool = True
    """是否写入 embedding 缓存"""
    service_key: str | None = None
    """Embedding service instance key; None/empty means default."""


class EmbeddingDiversityRequest(AdvancedBaseModel):
    candidates: list[str]
    """候选文本列表"""
    top_k: Optional[int] = None
    """选取最大数量, None 为全部"""
    service_key: str | None = None
    """Embedding service instance key; None/empty means default."""


from ._client_view import (
    AIServiceClientInfo,
    AIServiceInstanceInfo,
    AIServiceInfo,
    build_service_info,
    build_all_services_info,
)


class AIResponseModel(AdvancedBaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, use_attribute_docstrings=True)


AITempClientProvider = Literal['thinkthinksyn', 'openrouter']
"""临时裸 client 支持的三方 provider，不含 'default' (默认 service 走调度)。"""


class TempClientCredentials(AdvancedBaseModel):
    """临时裸 client 凭证 (仅用于 thinkthinksyn / openrouter 上下文)。"""
    base_url: str | None = None
    """接口根地址；None 表示使用环境/默认。"""
    apikey: str | None = None
    """API Key；None 表示使用环境变量。"""


class HasEnvKeyResponse(AdvancedBaseModel):
    has_env_key: bool


class CompletionStatusResponse(AdvancedBaseModel):
    client_count: int
    """默认 CompletionService 下已构造的 client 总数"""
    healthy_count: int
    """当前可用 client 数 (cooldown_until <= now 且 last_error 为空)"""
    cooling_count: int
    """当前处于冷却期的 client 数 (cooldown_until > now)"""
    inflight_total: int
    """所有 client 正在处理中的请求数之和"""
    last_success_at: float
    """所有 client 中最近一次成功调用的时间戳 (epoch 秒);无则为 0"""
    last_error: str | None
    """最近报错的 client 的 last_error 文本;没有错误时为 None"""


class LanguageOptionResponse(AdvancedBaseModel):
    code: str
    name: str
    iso_639_1: str | None = None
    iso_639_3: str | None = None
    aliases: list[str] = Field(default_factory=list)


class TokenUsageResponse(AIResponseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ProviderModelInfo(AIResponseModel):
    id: str | None = None
    object: str | None = None
    created: int | None = None
    owned_by: str | None = None


class ProviderModelsResponse(AIResponseModel):
    object: str | None = None
    data: list[ProviderModelInfo] = Field(default_factory=list)


class CompletionResponse(AdvancedBaseModel):
    text: str
    elapsed_ms: int | None = None
    token_usage: TokenUsageResponse | None = None


class FileRequestEcho(AIResponseModel):
    filename: str | None = None
    content_type: str | None = None
    bytes: int | None = None
    expected_languages: list[str] = Field(default_factory=list)
    prompt: str | None = None
    roles: list[str] = Field(default_factory=list)


class TextOperationResponse(AdvancedBaseModel):
    text: str
    elapsed_ms: int | None = None
    request_echo: FileRequestEcho | None = None


class RankedItemResponse(AdvancedBaseModel):
    index: int
    candidate: str
    score: float | None = None
    min_distance: float | None = None


class RankedItemsResponse(AdvancedBaseModel):
    items: list[RankedItemResponse] = Field(default_factory=list)
    elapsed_ms: int | None = None
    token_usage: TokenUsageResponse | None = None


class EmbeddingResponse(AdvancedBaseModel):
    vector: list[float] | None = None
    vectors: list[list[float]] | None = None
    elapsed_ms: int | None = None


class EmbeddingChunkResponse(AdvancedBaseModel):
    text: str
    vector: list[float]
    index: int
    offset: int


class EmbeddingChunkingResponse(AdvancedBaseModel):
    chunks: list[EmbeddingChunkResponse] = Field(default_factory=list)
    elapsed_ms: int | None = None


class EmbeddingCacheStatsResponse(AIResponseModel):
    count: int | None = None
    backend: str | None = None
    items: int | None = None
    bytes: int | None = None
    error: str | None = None


class DeleteCountResponse(AdvancedBaseModel):
    deleted: int


class TranscriptPayload(AIResponseModel):
    segments: list[AIResponseModel] = Field(default_factory=list)


class TranscriptResponse(AdvancedBaseModel):
    transcript: TranscriptPayload
    elapsed_ms: int | None = None
    request_echo: FileRequestEcho | None = None


def _build_transcript_payload(result: Any) -> TranscriptPayload:
    payload = result.model_dump() if hasattr(result, 'model_dump') else result
    if not isinstance(payload, dict):
        raise ValueError(f'Unsupported transcript payload: {type(payload).__name__}')

    transcript = payload.get('transcript')
    if not isinstance(transcript, list):
        raise ValueError(f'Unsupported transcript payload: {type(payload).__name__}')

    segments: list[dict[str, Any]] = []
    for item in transcript:
        if not isinstance(item, dict):
            raise ValueError(f'Unsupported transcript segment payload: {type(item).__name__}')

        speaker = item.get('speaker')
        text = item.get('text')
        if isinstance(speaker, str) and isinstance(text, str):
            segments.append({'speaker': speaker, 'text': text})
            continue

        if len(item) == 1:
            role, content = next(iter(item.items()))
            if isinstance(role, str) and isinstance(content, str):
                segments.append({'speaker': role, 'text': content})
                continue

        raise ValueError(f'Unsupported transcript segment payload: {item}')

    return TranscriptPayload.model_validate({'segments': segments})


class FileIDPayload(AIResponseModel):
    id: str | None = None
    category: str | None = None
    filename: str | None = None
    type: str | None = None
    expire: float | None = None


class FileUploadResponse(AdvancedBaseModel):
    file_id: FileIDPayload
    category: str
    size: int
    filename: str | None = None
    content_type: str | None = None
    file_expire: float | None = None


class FileDeleteResponse(AdvancedBaseModel):
    deleted: bool
    id: str
    category: str


class TempUploadTokenResponse(AdvancedBaseModel):
    token: str
    expires_at: float
    category: str
    max_size: int
    file_expire: float | None
    upload_url: str


SummarizeResponse.model_rebuild()


# ══════════════════════════════════════════════════════════════════════════════
# Lazy service cache
# ══════════════════════════════════════════════════════════════════════════════

_completion_service = None
_s2t_service = None
_t2s_service = None
_embedding_service = None


def reset_ai_service_route_caches(service_kinds: list[AIServiceKind] | tuple[AIServiceKind, ...] | None = None) -> None:
    global _completion_service, _s2t_service, _t2s_service, _embedding_service

    normalized = {str(kind or '').strip().lower() for kind in (service_kinds or ('completion', 'embedding', 's2t', 't2s'))}
    if 'completion' in normalized:
        _completion_service = None
    if 's2t' in normalized:
        _s2t_service = None
    if 't2s' in normalized:
        _t2s_service = None
    if 'embedding' in normalized:
        _embedding_service = None


def _service_has_retired_clients(service: Any) -> bool:
    clients = list(getattr(service, 'clients', []) or [])
    return any(bool(getattr(client, '_closed', False)) for client in clients)


async def _get_completion_service():
    global _completion_service
    if _completion_service is not None and (
        bool(getattr(_completion_service, '_closed', False))
        or _service_has_retired_clients(_completion_service)
    ):
        _completion_service = None
    if _completion_service is None:
        try:
            from core.ai import CompletionService
            await CompletionService.AwaitRuntimeReady()
            cached_default = CompletionService.GetInstance('default')
            if cached_default is not None and _service_has_retired_clients(cached_default):
                CompletionService.ClearInstances(keys={'default'})
            _completion_service = CompletionService.Default()
            logger.info("CompletionService initialized via Default()")
        except Exception as e:
            logger.warning(f"CompletionService init failed: {e}")
            raise HTTPException(503, f"CompletionService 不可用: {e}")
    return _completion_service


def _make_temp_completion_client(
    provider: AITempClientProvider,
    *,
    base_url: str | None,
    apikey: str | None,
    model: str | None,
):
    """为 chat UI 快看效果场景创建一次性裸 CompletionClient，不经 service 调度与探测。

    使用 ``key=`` 随机化避免命中 ``ServiceClientBase`` 参数哈希缓存，
    从而不与默认池内现有 client 合并。
    """
    from core.ai import CompletionClient
    one_shot_key = f"temp:{provider}:{base_url or ''}:{(apikey or '')[:8]}:{model or ''}:{_time.monotonic_ns()}"
    if provider == 'thinkthinksyn':
        return CompletionClient.CreateThinkThinkSynClient(
            apikey=apikey,
            base_url=base_url,
            model_filter=(f"Name == '{model}'" if model else None),
            key=one_shot_key,
        )
    if provider == 'openrouter':
        return CompletionClient.CreateOpenRouterClient(
            apikey=apikey,
            base_url=base_url,
            model=model,
            key=one_shot_key,
        )
    raise HTTPException(400, f"Unknown temp client provider: {provider!r}")


def _check_temp_client_env_key(provider: AITempClientProvider) -> bool:
    if provider == 'thinkthinksyn':
        return bool(_env_first('TTS_APIKEY', 'TTS_API_KEY'))
    if provider == 'openrouter':
        return bool(_env_first('OPENROUTER_APIKEY', 'OPENROUTER_API_KEY'))
    return False


async def _get_s2t_service():
    global _s2t_service
    if _s2t_service is not None and bool(getattr(_s2t_service, '_closed', False)):
        _s2t_service = None
    if _s2t_service is None:
        try:
            from core.ai import S2TService
            await S2TService.AwaitRuntimeReady()
            _s2t_service = S2TService.Default()
            logger.info("S2TService initialized via Default()")
        except Exception as e:
            logger.warning(f"S2TService init failed: {e}")
            raise HTTPException(503, f"S2TService 不可用: {e}")
    return _s2t_service


async def _get_t2s_service():
    global _t2s_service
    if _t2s_service is not None and bool(getattr(_t2s_service, '_closed', False)):
        _t2s_service = None
    if _t2s_service is None:
        try:
            from core.ai import T2SService
            await T2SService.AwaitRuntimeReady()
            _t2s_service = T2SService.Default()
            logger.info("T2SService initialized via Default()")
        except Exception as e:
            logger.warning(f"T2SService init failed: {e}")
            raise HTTPException(503, f"T2SService 不可用: {e}")
    return _t2s_service


async def _get_embedding_service():
    global _embedding_service
    if _embedding_service is not None and bool(getattr(_embedding_service, '_closed', False)):
        _embedding_service = None
    if _embedding_service is None:
        try:
            from core.ai import EmbeddingService
            await EmbeddingService.AwaitRuntimeReady()
            _embedding_service = EmbeddingService.Default()
            logger.info("EmbeddingService initialized via Default()")
        except Exception as e:
            logger.warning(f"EmbeddingService init failed: {e}")
            raise HTTPException(503, f"EmbeddingService 不可用: {e}")
    return _embedding_service


def _normalize_service_key(service_key: str | None) -> str:
    normalized = str(service_key or '').strip()
    return normalized or 'default'


async def _resolve_ai_service_instance(kind: AIServiceKind, service_key: str | None) -> Any:
    normalized_key = _normalize_service_key(service_key)

    if kind == 'completion' and normalized_key == 'default':
        return await _get_completion_service()
    if kind == 's2t' and normalized_key == 'default':
        return await _get_s2t_service()
    if kind == 't2s' and normalized_key == 'default':
        return await _get_t2s_service()
    if kind == 'embedding' and normalized_key == 'default':
        return await _get_embedding_service()

    from core.ai import CompletionService, EmbeddingService, S2TService, T2SService
    from core.ai.config import AIServicesConfig

    service_cls: type[Any] | None = {
        'completion': CompletionService,
        'embedding': EmbeddingService,
        's2t': S2TService,
        't2s': T2SService,
    }.get(kind)
    if service_cls is None:
        raise HTTPException(400, f'Unknown AI service kind: {kind}')

    await service_cls.AwaitRuntimeReady()
    existing = service_cls.GetInstance(normalized_key, fallback='')
    if existing is not None and (
        bool(getattr(existing, '_closed', False))
        or _service_has_retired_clients(existing)
    ):
        service_cls.ClearInstances(keys={normalized_key})
        existing = None
    if existing is not None:
        return existing

    cfg = AIServicesConfig.Global()
    predefined = getattr(cfg, kind, None) if cfg is not None else None
    if predefined is not None:
        service = predefined.get_service(normalized_key)
        if service is not None and not bool(getattr(service, '_closed', False)):
            return service

    raise HTTPException(404, f'{kind} service instance not found: {normalized_key}')


def _detect_audio_mime(data: bytes) -> tuple[str, str]:
    if data.startswith(b'RIFF') and data[8:12] == b'WAVE':
        return 'audio/wav', 'wav'
    if data.startswith(b'ID3') or data[:2] == b'\xff\xfb':
        return 'audio/mpeg', 'mp3'
    if data.startswith(b'OggS'):
        return 'audio/ogg', 'ogg'
    if data.startswith(b'fLaC'):
        return 'audio/flac', 'flac'
    return 'audio/wav', 'wav'


def _build_completion_params(req: _BaseCompletionRequest) -> dict[str, Any]:
    messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in req.messages]
    params: dict[str, Any] = {
        "messages": messages,
        "max_tokens": req.max_tokens,
        "reasoning": req.reasoning,
    }
    if req.temperature is not None:
        params["temperature"] = req.temperature
    if req.top_p is not None:
        params["top_p"] = req.top_p
    if req.top_k is not None:
        params["top_k"] = req.top_k
    if req.presence_penalty is not None:
        params["presence_penalty"] = req.presence_penalty
    if req.frequency_penalty is not None:
        params["frequency_penalty"] = req.frequency_penalty
    return params


async def _run_completion_request(req: _BaseCompletionRequest, svc: _CompletionCallable) -> StreamingResponse | CompletionResponse:
    params = _build_completion_params(req)

    if req.stream:
        async def _sse() -> AsyncGenerator[str, None]:
            t0 = _time.perf_counter()
            try:
                async for chunk in svc.stream_complete(**params):
                    payload = {"data": chunk.get("data", ""), "type": chunk.get("type", "text")}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            elapsed = round((_time.perf_counter() - t0) * 1000)
            usage = svc._peek_latest_token_usage()
            meta = {"done": True, "elapsed_ms": elapsed, "token_usage": usage}
            yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

        return StreamingResponse(_sse(), media_type="text/event-stream")

    try:
        t0 = _time.perf_counter()
        result = await svc.complete(**params)
        elapsed = round((_time.perf_counter() - t0) * 1000)
        usage = svc._peek_latest_token_usage()
        return CompletionResponse(
            text=result,
            elapsed_ms=elapsed,
            token_usage=TokenUsageResponse.model_validate(usage or {}),
        )
    except Exception as e:
        raise HTTPException(500, f"Completion failed: {e}")

@on_before_app_created
def register_ai_service_routes(app: FastAPI):
    server_cfg = Config.GetConfig().server_config
    internal_prefixes: list[str] = []
    public_prefixes: list[str] = []
    if server_cfg.is_internal_exposed():
        internal_prefixes.append(server_cfg.get_internal_path("/ai"))
    if server_cfg.is_ai_service_exposed():
        public_prefixes.append("/ai")
    if not internal_prefixes and not public_prefixes:
        return
    app = _AIAliasRouteRegistrar(app, internal_prefixes=internal_prefixes, public_prefixes=public_prefixes)  # type: ignore[assignment]

    # ── Service discovery (Sec 5.1) ───────────────────────────────────────

    @app.get("/ai/services", response_model=list[AIServiceInfo])
    async def list_ai_services() -> list[AIServiceInfo]:
        """返回四个 AI 服务的实例/client 聚合状态 (不发起探测)。"""
        return build_all_services_info()

    @app.get("/ai/services/{kind}", response_model=AIServiceInfo)
    async def get_ai_service(kind: AIServiceKind) -> AIServiceInfo:
        """返回指定 kind 服务的全量实例/client 聚合状态。"""
        return build_service_info(kind)

    @app.get("/ai/services/{kind}/instances/{instance_key}", response_model=AIServiceInstanceInfo)
    async def get_ai_service_instance(kind: AIServiceKind, instance_key: str) -> AIServiceInstanceInfo:
        info = build_service_info(kind).instances.get(instance_key)
        if info is None:
            raise HTTPException(404, f"instance not found: kind={kind!r} key={instance_key!r}")
        return info

    @app.get("/ai/services/{kind}/clients/{client_key}", response_model=AIServiceClientInfo)
    async def get_ai_service_client(kind: AIServiceKind, client_key: str) -> AIServiceClientInfo:
        info = build_service_info(kind).clients.get(client_key)
        if info is None:
            raise HTTPException(404, f"client not found: kind={kind!r} key={client_key!r}")
        return info

    # ── Provider key status ───────────────────────────────────────────────

    @app.get("/ai/clients/{provider}/has-env-key", response_model=HasEnvKeyResponse)
    async def has_env_key(provider: AITempClientProvider) -> HasEnvKeyResponse:
        """检查指定临时 client provider 是否存在环境变量 API Key (不发起任何请求)。"""
        return HasEnvKeyResponse(has_env_key=_check_temp_client_env_key(provider))

    @app.get("/ai/completion-status", response_model=CompletionStatusResponse)
    async def completion_status() -> CompletionStatusResponse:
        """返回默认 CompletionService 的运行时健康聚合,不触发真实补全请求。"""
        svc = await _get_completion_service()
        clients = list(getattr(svc, 'clients', []) or [])
        now = _time.time()
        healthy_count = 0
        cooling_count = 0
        inflight_total = 0
        last_success_at = 0.0
        last_error_pair: tuple[float, str] | None = None  # (last_success_at, error_text) 取最新
        for client in clients:
            cooldown_until = float(getattr(client, '_state_cooldown_until', 0.0))
            err = getattr(client, '_state_last_error', None)
            err_text = str(err) if err else None
            inflight = int(getattr(client, '_state_inflight', 0) or 0)
            cls_last_success = float(getattr(client, '_state_last_success_at', 0.0) or 0.0)
            if cls_last_success > last_success_at:
                last_success_at = cls_last_success
            inflight_total += inflight
            if cooldown_until > now:
                cooling_count += 1
            elif not err_text:
                healthy_count += 1
            if err_text:
                ts = cls_last_success  # 以该 client 的最近活动时间戳代表"最新报错"
                if last_error_pair is None or ts > last_error_pair[0]:
                    last_error_pair = (ts, err_text)
        return CompletionStatusResponse(
            client_count=len(clients),
            healthy_count=healthy_count,
            cooling_count=cooling_count,
            inflight_total=inflight_total,
            last_success_at=last_success_at,
            last_error=last_error_pair[1] if last_error_pair else None,
        )

    @app.get("/ai/languages", response_model=list[LanguageOptionResponse])
    async def list_languages() -> list[LanguageOptionResponse]:
        """返回 Language 枚举中的语言选项，供前端下拉/输入建议使用。"""
        rows: list[LanguageOptionResponse] = []
        for item in Language:
            rows.append(LanguageOptionResponse(
                code=item.code,
                name=item.origin_name,
                iso_639_1=item.iso_639_1,
                iso_639_3=item.iso_639_3,
                aliases=list(item.aliases),
            ))
        rows.sort(key=lambda x: str(x.code or ''))
        return rows

    # ── Model list (proxy) ────────────────────────────────────────────────

    async def _proxy_models_request(url: str, api_key: str) -> ProviderModelsResponse:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                resp = await http_client.get(url, headers={'Authorization': f'Bearer {api_key}'})
                resp.raise_for_status()
                return ProviderModelsResponse.model_validate(resp.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, f"Model list request failed: {e}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"Model list request failed: {e}")

    @app.post("/ai/clients/thinkthinksyn/list-models", response_model=ProviderModelsResponse)
    async def list_thinkthinksyn_models(req: TempClientCredentials | None = None) -> ProviderModelsResponse:
        """获取 ThinkThinkSyn 模型列表。body 可传 base_url / apikey 覆盖环境变量。"""
        import os
        creds = req or TempClientCredentials()
        api_url = (creds.base_url
                   or os.environ.get('TTS_API_BASEURL')
                   or 'https://api.thinkthinksyn.com')
        api_key = creds.apikey or _env_first('TTS_APIKEY', 'TTS_API_KEY')
        if not api_key:
            raise HTTPException(400, 'ThinkThinkSyn API key required (请传 apikey 或设置 TTS_APIKEY / TTS_API_KEY)')
        url = f"{api_url.rstrip('/')}/tts/ai/completion/openai/v1/models"
        return await _proxy_models_request(url, api_key)

    @app.post("/ai/clients/openrouter/list-models", response_model=ProviderModelsResponse)
    async def list_openrouter_models(req: TempClientCredentials | None = None) -> ProviderModelsResponse:
        """获取 OpenRouter 模型列表。body 可传 base_url / apikey 覆盖环境变量。"""
        import os
        creds = req or TempClientCredentials()
        base_url = creds.base_url or os.environ.get('OPENROUTER_API_URL') or 'https://openrouter.ai/api/v1'
        api_key = creds.apikey or _env_first('OPENROUTER_APIKEY', 'OPENROUTER_API_KEY')
        if not api_key:
            raise HTTPException(400, 'OpenRouter API key required (请传 apikey 或设置 OPENROUTER_APIKEY / OPENROUTER_API_KEY)')
        url = f"{base_url.rstrip('/')}/models"
        return await _proxy_models_request(url, api_key)


    # ── Completion (non-stream + SSE stream) ──────────────────────────────
    @app.post("/ai/complete", response_model=CompletionResponse)
    @_public
    async def complete(req: CompletionRequest) -> StreamingResponse | CompletionResponse:
        """默认 CompletionService 文本补全 / 聊天接口。"""
        return await _run_completion_request(req, await _resolve_ai_service_instance('completion', req.service_key))

    @app.post("/ai/test_thinkthinksyn_complete", response_model=CompletionResponse)
    async def test_thinkthinksyn_complete(req: ThinkThinkSynCompleteRequest) -> StreamingResponse | CompletionResponse:
        """ThinkThinkSyn 特殊测试接口：直接创建临时 client，不走 service 调度。"""
        try:
            client = _make_temp_completion_client(
                'thinkthinksyn',
                base_url=(req.base_url or '').strip() or None,
                apikey=(req.apikey or '').strip() or None,
                model=req.model,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Temp client init failed: {e}")
        return await _run_completion_request(req, client)

    @app.post("/ai/test_openrouter_complete", response_model=CompletionResponse)
    async def test_openrouter_complete(req: OpenRouterCompleteRequest) -> StreamingResponse | CompletionResponse:
        """OpenRouter 特殊测试接口：直接创建临时 client，不走 service 调度。"""
        try:
            client = _make_temp_completion_client(
                'openrouter',
                base_url=(req.base_url or '').strip() or None,
                apikey=(req.apikey or '').strip() or None,
                model=req.model,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Temp client init failed: {e}")
        return await _run_completion_request(req, client)

    # ── Translate ─────────────────────────────────────────────────────────

    @app.post("/ai/translate", response_model=TranslateResponse)
    @_public
    async def translate(req: TranslateRequest) -> TranslateResponse:
        """文本翻译。"""
        svc = await _get_completion_service()
        try:
            t0 = _time.perf_counter()
            result = await svc.translate(req.text, target_language=req.target_language)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return TranslateResponse(
                translated=result,
                elapsed_ms=elapsed,
                request_echo={'target_language': req.target_language, 'text_length': len(req.text)},
            )
        except Exception as e:
            raise HTTPException(500, f"Translation failed: {e}")

    # ── Detect Language ───────────────────────────────────────────────────

    @app.post("/ai/detect-language", response_model=DetectLanguageResponse)
    @_public
    async def detect_language(req: DetectLanguageRequest) -> DetectLanguageResponse:
        """语言检测。"""
        svc = await _get_completion_service()
        try:
            t0 = _time.perf_counter()
            result = await svc.detect_language(req.text)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            lang_str = result.value.code if hasattr(result, "value") else str(result) if result else None
            return DetectLanguageResponse(
                language=lang_str,
                elapsed_ms=elapsed,
                request_echo={'text_length': len(req.text)},
            )
        except Exception as e:
            raise HTTPException(500, f"Detection failed: {e}")

    # ── OCR (upload image) ────────────────────────────────────────────────

    @app.post("/ai/ocr", response_model=TextOperationResponse)
    @_public
    async def ocr(file: UploadFile = File(...)) -> TextOperationResponse:
        """图片 OCR 文字识别。"""
        svc = await _get_completion_service()
        try:
            data = await file.read()
            img = Image(data)
            t0 = _time.perf_counter()
            result = await svc.ocr(img, stream=False)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return TextOperationResponse(
                text=result,
                elapsed_ms=elapsed,
                request_echo=FileRequestEcho(
                    filename=file.filename,
                    content_type=file.content_type,
                    bytes=len(data),
                ),
            )
        except Exception as e:
            raise HTTPException(500, f"OCR failed: {e}")

    # ── ASR (upload audio) ────────────────────────────────────────────────

    @app.post("/ai/asr", response_model=TextOperationResponse)
    @_public
    async def asr(
        file: UploadFile = File(...),
        expected_languages: str = Form(""),
        prompt: str = Form(""),
    ) -> TextOperationResponse:
        """音频语音识别 (ASR)。支持 expected_languages (逗号分隔语言代码) 和自定义 prompt。"""
        svc = await _get_completion_service()
        try:
            data = await file.read()
            audio = Audio(data)
            lang_list = [l.strip() for l in expected_languages.split(",") if l.strip()] if expected_languages else None
            t0 = _time.perf_counter()
            result = await svc.asr(
                audio,
                prompt=prompt or None,
                expected_languages=lang_list or None,
                stream=False,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return TextOperationResponse(
                text=result,
                elapsed_ms=elapsed,
                request_echo=FileRequestEcho(
                    filename=file.filename,
                    content_type=file.content_type,
                    bytes=len(data),
                    expected_languages=lang_list or [],
                    prompt=prompt or None,
                ),
            )
        except Exception as e:
            raise HTTPException(500, f"ASR failed: {e}")

    # ── Summarize ─────────────────────────────────────────────────────────

    @app.post("/ai/summarize", response_model=SummarizeResponse)
    @_public
    async def summarize(req: SummarizeRequest) -> StreamingResponse | SummarizeResponse:
        """文本摘要。支持 chunk_size / sliding_window_size / prompt / stream 参数。"""
        svc = await _get_completion_service()
        kwargs: dict[str, Any] = {}
        if req.chunk_size is not None:
            kwargs["chunk_size"] = req.chunk_size
        if req.sliding_window_size != 0.15:
            kwargs["sliding_window_size"] = req.sliding_window_size

        if req.stream:
            async def _sse_summarize():
                t0 = _time.perf_counter()
                try:
                    result = await svc.summarize(
                        req.text,
                        prompt=req.prompt or None,
                        stream=True,
                        **kwargs,
                    )
                    elapsed = round((_time.perf_counter() - t0) * 1000)
                    usage = svc._peek_latest_token_usage()
                    payload = {"summary": result, "elapsed_ms": elapsed, "token_usage": usage}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return StreamingResponse(_sse_summarize(), media_type="text/event-stream")

        try:
            t0 = _time.perf_counter()
            result = await svc.summarize(
                req.text,
                prompt=req.prompt or None,
                stream=False,
                **kwargs,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            usage = svc._peek_latest_token_usage()
            return SummarizeResponse(
                summary=result,
                elapsed_ms=elapsed,
                token_usage=TokenUsageResponse.model_validate(usage or {}),
            )
        except Exception as e:
            raise HTTPException(500, f"Summarize failed: {e}")

    # ── S2T (upload audio) ────────────────────────────────────────────────

    @app.post("/ai/s2t", response_model=TextOperationResponse)
    @_public
    async def s2t(file: UploadFile = File(...), service_key: str = Form('default')) -> TextOperationResponse:
        """语音转文字 (S2T)。"""
        svc = await _resolve_ai_service_instance('s2t', service_key)
        try:
            data = await file.read()
            audio = Audio(data)
            t0 = _time.perf_counter()
            result = await svc.s2t(audio)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return TextOperationResponse(
                text=result,
                elapsed_ms=elapsed,
                request_echo=FileRequestEcho(
                    filename=file.filename,
                    content_type=file.content_type,
                    bytes=len(data),
                ).model_dump() | {'service_key': _normalize_service_key(service_key)},
            )
        except Exception as e:
            raise HTTPException(500, f"S2T failed: {e}")

    # ── T2S ───────────────────────────────────────────────────────────────

    @app.post("/ai/t2s", response_model=T2SResponse)
    @_public
    async def t2s(req: T2SRequest) -> T2SResponse:
        """文字转语音 (T2S)。返回 Base64 编码的音频数据。"""
        svc = await _resolve_ai_service_instance('t2s', req.service_key)
        try:
            t0 = _time.perf_counter()
            audio = await svc.t2s(req.text)
            audio_bytes = audio.to_bytes()
            elapsed = round((_time.perf_counter() - t0) * 1000)
            mime_type, detected_format = _detect_audio_mime(audio_bytes)
            b64 = base64.b64encode(audio_bytes).decode("ascii")
            return T2SResponse(
                audio_base64=b64,
                format=detected_format,
                mime_type=mime_type,
                audio_bytes=len(audio_bytes),
                elapsed_ms=elapsed,
                request_echo={'text_length': len(req.text), 'service_key': _normalize_service_key(req.service_key)},
            )
        except Exception as e:
            raise HTTPException(500, f"T2S failed: {e}")

    @app.post('/ai/t2s/stream')
    @_public
    async def t2s_stream(req: T2SRequest) -> StreamingResponse:
        """文字转语音流式输出。按音频字节块返回响应流。"""
        svc = await _resolve_ai_service_instance('t2s', req.service_key)
        chunk_size = max(1024, int(req.chunk_size or 16384))

        async def _stream_audio():
            async for chunk in svc.t2s_stream(req.text, chunk_size=chunk_size):
                yield chunk

        return StreamingResponse(
            _stream_audio(),
            media_type='audio/wav',
            headers={
                'X-AI-Mode': 't2s-stream',
                'X-AI-Chunk-Size': str(chunk_size),
                'X-AI-Service-Key': _normalize_service_key(req.service_key),
            },
        )

    # ── Embedding ─────────────────────────────────────────────────────────

    @app.post("/ai/embedding", response_model=EmbeddingResponse)
    @_public
    async def embedding(req: EmbeddingRequest) -> EmbeddingResponse:
        """文本向量化。"""
        svc = await _resolve_ai_service_instance('embedding', req.service_key)
        try:
            t0 = _time.perf_counter()
            payload: str | list[str] | None = None
            if req.text is not None and req.text.strip():
                payload = req.text
            elif req.texts:
                payload = [text for text in req.texts if text.strip()]

            if payload is None or (isinstance(payload, list) and not payload):
                raise HTTPException(400, "Embedding request requires `text` or non-empty `texts`.")

            result = await svc.embedding(payload, use_cache=req.use_cache, save_cache=req.save_cache)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            if isinstance(payload, str):
                return EmbeddingResponse(vector=result, elapsed_ms=elapsed)
            return EmbeddingResponse(vectors=result, elapsed_ms=elapsed)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Embedding failed: {e}")

    @app.post("/ai/embedding/rerank", response_model=RankedItemsResponse)
    @_public
    async def embedding_rerank(req: EmbeddingRerankRequest) -> RankedItemsResponse:
        """基于语义相似度的重排序。"""
        svc = await _resolve_ai_service_instance('embedding', req.service_key)
        try:
            t0 = _time.perf_counter()
            items = await svc.rerank(req.query, req.candidates)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return RankedItemsResponse(
                items=[RankedItemResponse(index=it.index, score=it.score, candidate=it.candidate) for it in items],
                elapsed_ms=elapsed,
            )
        except Exception as e:
            raise HTTPException(500, f"Embedding rerank failed: {e}")

    @app.post("/ai/embedding/chunking", response_model=EmbeddingChunkingResponse)
    @_public
    async def embedding_chunking(req: EmbeddingChunkingRequest) -> EmbeddingChunkingResponse:
        """长文本分块并向量化。"""
        svc = await _resolve_ai_service_instance('embedding', req.service_key)
        try:
            t0 = _time.perf_counter()
            chunks = await svc.chunking(
                req.content,
                max_word_count=req.max_word_count,
                use_cache=req.use_cache,
                save_cache=req.save_cache,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return EmbeddingChunkingResponse(
                chunks=[
                    EmbeddingChunkResponse(text=c.text, vector=c.vector, index=c.index, offset=c.offset)
                    for c in chunks
                ],
                elapsed_ms=elapsed,
            )
        except Exception as e:
            raise HTTPException(500, f"Embedding chunking failed: {e}")

    @app.post("/ai/embedding/diversity", response_model=RankedItemsResponse)
    @_public
    async def embedding_diversity(req: EmbeddingDiversityRequest) -> RankedItemsResponse:
        """基于多样性的候选文本重排序。"""
        svc = await _resolve_ai_service_instance('embedding', req.service_key)
        try:
            t0 = _time.perf_counter()
            items = await svc.diversity_rerank(req.candidates, top_k=req.top_k)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return RankedItemsResponse(
                items=[
                    RankedItemResponse(index=it.index, candidate=it.candidate, min_distance=it.min_distance)
                    for it in items
                ],
                elapsed_ms=elapsed,
            )
        except Exception as e:
            raise HTTPException(500, f"Embedding diversity rerank failed: {e}")

    @app.get("/ai/embedding/cache-stats", response_model=EmbeddingCacheStatsResponse)
    async def embedding_cache_stats() -> EmbeddingCacheStatsResponse:
        """查询 Embedding 缓存统计。"""
        svc = await _get_embedding_service()
        return EmbeddingCacheStatsResponse.model_validate(await svc.cache_stats())

    @app.post("/ai/embedding/cache-clear", response_model=DeleteCountResponse)
    async def embedding_cache_clear() -> DeleteCountResponse:
        """清空 Embedding 缓存。"""
        svc = await _get_embedding_service()
        deleted = await svc.cache_clear()
        return DeleteCountResponse(deleted=deleted)

    # ── Transcript (diarization) ──────────────────────────────────────────

    @app.post("/ai/transcript", response_model=TranscriptResponse)
    @_public
    async def transcript(
        file: UploadFile = File(...),
        roles: str = Form(""),
        expected_languages: str = Form(""),
        prompt: str = Form(""),
    ) -> TranscriptResponse:
        """音频说话人分离与转录。支持 roles / expected_languages / prompt 参数。"""
        svc = await _get_completion_service()
        try:
            data = await file.read()
            audio = Audio(data)
            role_list = [r.strip() for r in roles.split(",") if r.strip()] if roles else None
            lang_list = [l.strip() for l in expected_languages.split(",") if l.strip()] if expected_languages else None
            t0 = _time.perf_counter()
            result = await svc.transcript(
                audio,
                roles=role_list,
                expected_languages=lang_list or None,
                prompt=prompt or None,
                stream=False,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return TranscriptResponse(
                transcript=_build_transcript_payload(result),
                elapsed_ms=elapsed,
                request_echo=FileRequestEcho(
                    filename=file.filename,
                    content_type=file.content_type,
                    bytes=len(data),
                    roles=role_list or [],
                    expected_languages=lang_list or [],
                    prompt=prompt or None,
                ),
            )
        except Exception as e:
            raise HTTPException(500, f"Transcript failed: {e}")

    # ── LLM Rerank ────────────────────────────────────────────────────────

    @app.post("/ai/rerank", response_model=RankedItemsResponse)
    @_public
    async def completion_rerank(req: CompletionRerankRequest) -> RankedItemsResponse:
        """基于 LLM 的语义重排序 (0–10 评分)。"""
        svc = await _get_completion_service()
        try:
            t0 = _time.perf_counter()
            result = await svc.rerank(
                req.query,
                req.candidates,
                prompt=req.prompt or None,
                stream=req.stream,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            usage = svc._peek_latest_token_usage()
            return RankedItemsResponse(
                items=[
                    RankedItemResponse(index=it.index, score=it.score, candidate=it.candidate)
                    for it in result.items
                ],
                elapsed_ms=elapsed,
                token_usage=TokenUsageResponse.model_validate(usage or {}),
            )
        except Exception as e:
            raise HTTPException(500, f"LLM rerank failed: {e}")

    # ── File storage (FileID) ─────────────────────────────────────────────

    def _parse_bearer(authorization: str) -> str:
        if not authorization or not authorization.lower().startswith('bearer '):
            raise HTTPException(401, 'Missing or malformed Authorization header')
        token = authorization[7:].strip()
        if not token:
            raise HTTPException(401, 'Empty bearer token')
        return token

    @app.post('/ai/upload_temp_file', response_model=TempUploadTokenResponse)
    @_public
    async def issue_temp_upload_token(request: Request) -> TempUploadTokenResponse:
        '''颁发一个上传临时 JWT，category/max_size/file_expire 由服务端单边决定。'''
        from core.server.security.jwt import issue_upload_token
        from core.server.data_types.config import JwtIssuanceConfig

        cfg = JwtIssuanceConfig.AiTempUpload
        token = issue_upload_token(
            category=cfg.category,
            max_size=cfg.max_size,
            file_expire=cfg.file_expire,
            ttl=cfg.ttl,
            issuer_route='ai.upload_temp_file',
            allowed_mime_prefixes=list(cfg.allowed_mime_prefixes),
        )
        server_cfg = Config.GetConfig().server_config
        internal_ai_path = server_cfg.get_internal_path("/ai")
        return TempUploadTokenResponse(
            token=token,
            expires_at=_time.time() + float(cfg.ttl),
            category=cfg.category,
            max_size=cfg.max_size,
            file_expire=cfg.file_expire,
            upload_url=(f'{internal_ai_path}/files/upload' if str(request.url.path).startswith(internal_ai_path + '/') else '/ai/files/upload'),
        )

    @app.post('/ai/files/upload', response_model=FileUploadResponse)
    @_public
    async def upload_file(
        file: UploadFile = File(...),
        authorization: str = Header(..., alias='Authorization'),
    ) -> FileUploadResponse:
        '''将文件上传至 object storage，需要 Bearer JWT (sub=file-upload)。'''
        from core.utils.data_structs.files.base import FileID, _infer_file_type_by_source
        from core.server.security.jwt import verify_token, JwtError

        token = _parse_bearer(authorization)
        try:
            claims = verify_token(token, expected_sub='file-upload')
        except JwtError as exc:
            raise HTTPException(401, str(exc))

        category = str(claims['category'])
        max_size = int(claims['max_size'])
        file_expire = claims.get('file_expire')
        allowed_mime_prefixes = claims.get('allowed_mime_prefixes')

        content_type = file.content_type or ''
        if allowed_mime_prefixes and not any(content_type.startswith(p) for p in allowed_mime_prefixes):
            raise HTTPException(415, f"MIME type '{content_type}' not allowed by token")

        # Stream-read with size guard
        chunks: list[bytes] = []
        total = 0
        chunk_size = 64 * 1024
        try:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size:
                    await file.close()
                    raise HTTPException(413, f'Payload exceeds max_size={max_size}')
                chunks.append(chunk)
        finally:
            try:
                await file.close()
            except Exception:
                pass

        data = b''.join(chunks)
        inferred_type = _infer_file_type_by_source(data)

        try:
            file_id = await FileID.Create(
                data,
                category=category,
                expire=file_expire,
                type=inferred_type,
                filename=file.filename,
            )
            return FileUploadResponse(
                file_id=FileIDPayload.model_validate(file_id.model_dump()),
                category=category,
                size=len(data),
                filename=file.filename,
                content_type=content_type or None,
                file_expire=file_expire,
            )
        except Exception as e:
            raise HTTPException(500, f'File upload failed: {e}')

    @app.post('/ai/files/get')
    @_public
    async def get_file(
        authorization: str = Header(..., alias='Authorization'),
    ) -> Response:
        '''按 JWT (sub=file-access, action=read) 取回原始文件字节。'''
        from core.utils.data_structs.files.base import FileID
        from core.server.security.jwt import verify_token, JwtError

        token = _parse_bearer(authorization)
        try:
            claims = verify_token(token, expected_sub='file-access')
        except JwtError as exc:
            raise HTTPException(401, str(exc))
        if claims.get('action') != 'read':
            raise HTTPException(403, 'token action mismatch')

        category = str(claims['category'])
        object_id = str(claims['object_id'])
        try:
            if not await FileID._peek_target(category, object_id, size=1):
                raise HTTPException(404, 'File not found')
            return StreamingResponse(
                FileID._iter_stored_chunks(category, object_id),
                media_type='application/octet-stream',
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f'File retrieval failed: {e}')

    @app.post('/ai/files/delete', response_model=FileDeleteResponse)
    @_public
    async def delete_file(
        authorization: str = Header(..., alias='Authorization'),
    ) -> FileDeleteResponse:
        '''按 JWT (sub=file-access, action=delete) 删除文件。'''
        from core.utils.data_structs.files.base import FileID
        from core.server.security.jwt import verify_token, JwtError

        token = _parse_bearer(authorization)
        try:
            claims = verify_token(token, expected_sub='file-access')
        except JwtError as exc:
            raise HTTPException(401, str(exc))
        if claims.get('action') != 'delete':
            raise HTTPException(403, 'token action mismatch')

        category = str(claims['category'])
        object_id = str(claims['object_id'])
        try:
            deleted = await FileID._delete_target(category, object_id)
            return FileDeleteResponse(deleted=deleted, id=object_id, category=category)
        except Exception as e:
            raise HTTPException(500, f'File deletion failed: {e}')
