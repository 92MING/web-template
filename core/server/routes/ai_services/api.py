# -*- coding: utf-8 -*-
"""AI service API routes (production endpoints)."""
import json
import base64
import logging
import time as _time
import uuid
from pathlib import Path

from typing import Any, AsyncGenerator, Literal, Optional, Protocol, Union, cast
from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile, File, Header, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import ConfigDict, Field, field_validator

from core.utils.type_utils import AdvancedBaseModel
from core.ai.embedding import _cosine_similarity
from core.ai.shared import AIServiceKind
from core.ai.base import ServiceBase, ServiceClientBase, _normalize_service_kind_name
from core.utils.data_structs import Audio, Image
from core.utils.text_utils import Language

from ...app import on_before_app_created
from ...data_types.config import Config

logger = logging.getLogger(__name__)


def _public(func):
    setattr(func, "__public__", True)
    return func


async def _require_exposed_ai_service_apikey(request: Request) -> None:
    from ...route import RouteLoader

    await RouteLoader(Path("."), request.app)._require_apikey_dependency(request)


def _apikey_protected_route_kwargs(**kwargs: Any) -> dict[str, Any]:
    route_kwargs = dict(kwargs)
    dependencies = list(route_kwargs.pop("dependencies", []) or [])
    dependencies.append(Depends(_require_exposed_ai_service_apikey))
    route_kwargs["dependencies"] = dependencies
    return route_kwargs


def _ai_service_path(kind: AIServiceKind, suffix: str, service_key_param: str = "{service_key}") -> str:
    cleaned = suffix.strip("/")
    base = f"/ai/{kind}/service/{service_key_param}"
    return f"{base}/{cleaned}" if cleaned else base


def _ai_client_path(kind: AIServiceKind, suffix: str, client_key_param: str = "{client_key}") -> str:
    cleaned = suffix.strip("/")
    base = f"/ai/{kind}/client/{client_key_param}"
    return f"{base}/{cleaned}" if cleaned else base


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
                public_kwargs = _apikey_protected_route_kwargs(**kwargs)
                for prefix in self._public_prefixes:
                    self._app.get(self._alias_path(path, prefix), **public_kwargs)(func)
            return func

        return _decorator

    def post(self, path: str, **kwargs: Any):
        def _decorator(func):
            for prefix in self._internal_prefixes:
                self._app.post(self._alias_path(path, prefix), **kwargs)(func)
            if getattr(func, "__public__", False):
                public_kwargs = _apikey_protected_route_kwargs(**kwargs)
                for prefix in self._public_prefixes:
                    self._app.post(self._alias_path(path, prefix), **public_kwargs)(func)
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
    def stream_complete(self, **kwargs: Any) -> AsyncGenerator[Any, None]: ...
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
    client_key: str | None = None
    """Pinned completion client key inside the selected service instance; None/empty means service-managed routing."""


class CompletionRequest(_BaseCompletionRequest):
    """默认 CompletionService 请求体。"""


class OpenAIChatCompletionRequest(_BaseCompletionRequest):
    """OpenAI 兼容 Chat Completion 请求体。"""

    model: Optional[str] = None
    """指定使用的模型名称（仅用于标识，不影响路由）。"""
    stop: str | list[str] | None = None
    """停止序列。"""
    seed: Optional[int] = None
    """随机种子。"""
    response_format: dict[str, Any] | None = None
    """响应格式（如 json_schema）。"""
    n: Optional[int] = None
    """生成候选数（当前仅支持 1）。"""
    logprobs: Optional[bool] = None
    """是否返回 token 概率（当前未实现）。"""


class OpenAIChatCompletionChoice(AdvancedBaseModel):
    """OpenAI 兼容 Chat Completion 非流式 choice。"""

    index: int = 0
    message: dict[str, Any]
    finish_reason: str = "stop"


class OpenAIChatCompletionUsage(AdvancedBaseModel):
    """OpenAI 兼容 token 使用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatCompletionResponse(AdvancedBaseModel):
    """OpenAI 兼容 Chat Completion 非流式响应。"""

    id: str
    object: str = "chat.completion"
    created: int
    model: str | None = None
    choices: list[OpenAIChatCompletionChoice]
    usage: OpenAIChatCompletionUsage


class OpenAIChatCompletionStreamChoice(AdvancedBaseModel):
    """OpenAI 兼容 Chat Completion 流式 choice。"""

    index: int = 0
    delta: dict[str, Any]
    finish_reason: str | None = None


class OpenAIChatCompletionStreamResponse(AdvancedBaseModel):
    """OpenAI 兼容 Chat Completion 流式 chunk。"""

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str | None = None
    choices: list[OpenAIChatCompletionStreamChoice]


class AnthropicMessagesRequest(AdvancedBaseModel):
    """Anthropic 兼容 Messages 请求体。"""

    model_config = ConfigDict(extra="allow")

    messages: list[dict[str, Any]]

    @field_validator('messages', mode='before')
    @classmethod
    def _validate_messages(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError("'messages' must be a list")
        return _validate_messages(value)

    model: str | None = None
    system: str | list[dict[str, Any]] | None = None
    max_tokens: int | None = None
    stop_sequences: list[str] | None = None
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    thinking: bool | dict[str, Any] | None = None
    client_key: str | None = None


class AnthropicTextContentBlock(AdvancedBaseModel):
    type: Literal['text'] = 'text'
    text: str


class AnthropicMessageUsage(AdvancedBaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class AnthropicMessageResponse(AdvancedBaseModel):
    id: str
    type: Literal['message'] = 'message'
    role: Literal['assistant'] = 'assistant'
    content: list[AnthropicTextContentBlock]
    model: str | None = None
    stop_reason: str | None = 'end_turn'
    stop_sequence: str | None = None
    usage: AnthropicMessageUsage


class OpenAIEmbeddingRequest(AdvancedBaseModel):
    """OpenAI 兼容 Embedding 请求体。"""

    model: str | None = None
    input: str | list[str] | list[int] | list[list[int]]
    encoding_format: str = "float"
    dimensions: int | None = None
    user: str | None = None
    service_key: str | None = None
    client_key: str | None = None


class OpenAIEmbeddingData(AdvancedBaseModel):
    """OpenAI 兼容 Embedding 响应项。"""

    object: str = "embedding"
    index: int
    embedding: list[float]


class OpenAIEmbeddingUsage(AdvancedBaseModel):
    """OpenAI 兼容 Embedding 用量统计。"""

    prompt_tokens: int = 0
    total_tokens: int = 0


class OpenAIEmbeddingResponse(AdvancedBaseModel):
    """OpenAI 兼容 Embedding 响应体。"""

    object: str = "list"
    data: list[OpenAIEmbeddingData]
    model: str | None = None
    usage: OpenAIEmbeddingUsage


class OpenAIS2TResponse(AdvancedBaseModel):
    """OpenAI 兼容 S2T 响应体。"""

    text: str
    usage: dict[str, Any] | None = None


class OpenAIT2SRequest(AdvancedBaseModel):
    """OpenAI 兼容 TTS 请求体。"""

    model: str = "tts-1"
    input: str
    voice: str | dict[str, str] = "alloy"
    response_format: str = "mp3"
    speed: float = 1.0
    instructions: str | None = None
    service_key: str | None = None
    client_key: str | None = None


class OpenAIImageGenerationRequest(AdvancedBaseModel):
    """OpenAI 兼容图片生成请求体。"""

    model_config = ConfigDict(extra="allow")

    prompt: str
    model: str | None = None
    n: int = 1
    background: str | None = None
    moderation: str | None = None
    output_compression: int | None = None
    output_format: str | None = None
    partial_images: int | None = None
    quality: str | None = None
    response_format: str | None = None
    size: str | None = None
    stream: bool = False
    style: str | None = None
    user: str | None = None
    service_key: str | None = None
    client_key: str | None = None


class OpenAIImageData(AdvancedBaseModel):
    b64_json: str | None = None
    url: str | None = None
    revised_prompt: str | None = None


class OpenAIImagesResponse(AdvancedBaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, use_attribute_docstrings=True)

    created: int
    data: list[OpenAIImageData] = Field(default_factory=list)
    background: str | None = None
    output_format: str | None = None
    quality: str | None = None
    size: str | None = None
    usage: dict[str, Any] | None = None


class TranslateRequest(AdvancedBaseModel):
    text: str
    """要翻译的文本"""
    target_language: str = "zh-tw"
    """目标语言代码"""
    service_key: str | None = None
    client_key: str | None = None


class TranslateResponse(AdvancedBaseModel):
    translated: str
    """翻译结果"""
    elapsed_ms: int | None = None
    request_echo: dict[str, Any] | None = None


class DetectLanguageRequest(AdvancedBaseModel):
    text: str
    """要检测语言的文本"""
    service_key: str | None = None
    client_key: str | None = None


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
    service_key: str | None = None
    client_key: str | None = None


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
    client_key: str | None = None
    """Pinned T2S client key inside the selected service instance; None/empty means service-managed routing."""


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
    client_key: str | None = None
    """Pinned embedding client key inside the selected service instance; None/empty means service-managed routing."""


class EmbeddingRerankRequest(AdvancedBaseModel):
    query: str
    """查询文本"""
    candidates: list[str]
    """候选文本列表"""
    service_key: str | None = None
    """Embedding service instance key; None/empty means default."""
    client_key: str | None = None
    """Pinned embedding client key inside the selected service instance; None/empty means service-managed routing."""


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
    client_key: str | None = None
    """Pinned embedding client key inside the selected service instance; None/empty means service-managed routing."""


class EmbeddingDiversityRequest(AdvancedBaseModel):
    candidates: list[str]
    """候选文本列表"""
    top_k: Optional[int] = None
    """选取最大数量, None 为全部"""
    service_key: str | None = None
    """Embedding service instance key; None/empty means default."""
    client_key: str | None = None
    """Pinned embedding client key inside the selected service instance; None/empty means service-managed routing."""


from ._client_view import (
    AIServiceClientInfo,
    AIServiceInstanceInfo,
    AIServiceInfo,
    build_service_info,
    build_all_services_info,
)


class AIResponseModel(AdvancedBaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, use_attribute_docstrings=True)


class TempClientCredentials(AdvancedBaseModel):
    """OpenAI-compatible temporary client credentials."""
    base_url: str | None = None
    """接口根地址；None 表示使用默认 OpenRouter URL。"""
    apikey: str | None = None
    """API Key；必须由请求显式提供。"""


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
_t2img_service = None
_embedding_service = None


def reset_ai_service_route_caches(service_kinds: list[AIServiceKind] | tuple[AIServiceKind, ...] | None = None) -> None:
    global _completion_service, _s2t_service, _t2s_service, _t2img_service, _embedding_service

    normalized = {str(kind or '').strip().lower() for kind in (service_kinds or ('completion', 'embedding', 's2t', 't2s', 't2img'))}
    if 'completion' in normalized:
        _completion_service = None
    if 's2t' in normalized:
        _s2t_service = None
    if 't2s' in normalized:
        _t2s_service = None
    if 't2img' in normalized:
        _t2img_service = None
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


async def _resolve_completion_target(service_key: str | None = None, client_key: str | None = None) -> tuple[Any, bool]:
    if client_key:
        return await _resolve_ai_client_instance('completion', client_key), True
    return await _resolve_ai_service_instance('completion', service_key), False


def _normalize_service_key(service_key: str | None) -> str:
    normalized = str(service_key or '').strip()
    return normalized or 'default'


def _client_key_candidates(kind: AIServiceKind, client_key: str) -> list[str]:
    target = str(client_key or '').strip()
    if not target:
        return []
    candidates: list[str] = [target]
    parts = target.split(':')
    if len(parts) >= 3 and parts[1] == kind:
        candidates.append(':'.join(parts[1:]))
    if ':' not in target:
        candidates.append(f'{kind}:{target}')
    return list(dict.fromkeys(candidates))


def _config_client_key_from_runtime_key(kind: AIServiceKind, client_key: str) -> str:
    target = str(client_key or '').strip()
    if not target:
        return ''
    parts = target.split(':')
    if len(parts) >= 3 and parts[1] == kind:
        return ':'.join(parts[2:])
    if len(parts) >= 2 and parts[0] == kind:
        return ':'.join(parts[1:])
    return target


def _sync_ai_services_runtime_from_shared() -> None:
    try:
        from .panel import sync_ai_services_config_from_shared

        sync_ai_services_config_from_shared()
    except Exception as exc:
        logger.debug('AI service runtime shared sync skipped: %s', exc, exc_info=True)


def _resolve_ai_service_class(kind: AIServiceKind) -> type[ServiceBase]:
    from core.ai import _PREDEFINED_SERVICE_CLASSES

    service_cls = _PREDEFINED_SERVICE_CLASSES.get(str(kind))
    if service_cls is None:
        raise HTTPException(400, f'Unknown AI service kind: {kind}')
    return service_cls


def _client_matches_kind(client: Any, kind: AIServiceKind) -> bool:
    return _normalize_service_kind_name(getattr(type(client), 'ServiceKind', None) or type(client)) == kind


async def _resolve_ai_service_instance(kind: AIServiceKind, service_key: str | None) -> Any:
    _sync_ai_services_runtime_from_shared()
    normalized_key = _normalize_service_key(service_key)
    from core.ai.config import AIServicesConfig

    service_cls = _resolve_ai_service_class(kind)
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

    if normalized_key == 'default':
        try:
            return service_cls.Default()
        except Exception as e:
            logger.warning(f"{kind} default service init failed: {e}")
            raise HTTPException(503, f"{kind} service 不可用: {e}")

    raise HTTPException(404, f'{kind} service instance not found: {normalized_key}')


async def _resolve_ai_client_instance(kind: AIServiceKind, client_key: str | None) -> Any:
    _sync_ai_services_runtime_from_shared()
    normalized_key = str(client_key or '').strip()
    if not normalized_key:
        raise HTTPException(400, f'{kind} client key is required')

    from core.ai.config import AIServicesConfig

    _resolve_ai_service_class(kind)
    for candidate in _client_key_candidates(kind, normalized_key):
        existing = ServiceClientBase.GetClient(candidate)
        if existing is not None and _client_matches_kind(existing, kind) and not bool(getattr(existing, '_closed', False)):
            return existing

    cfg = AIServicesConfig.Global()
    predefined = getattr(cfg, kind, None) if cfg is not None else None
    config_key = _config_client_key_from_runtime_key(kind, normalized_key)
    if predefined is not None and config_key in predefined.clients:
        client = predefined.clients[config_key].get_client(
            key=predefined.scoped_client_key(config_key),
            service_kind=kind,
        )
        if client is not None and _client_matches_kind(client, kind) and not bool(getattr(client, '_closed', False)):
            return client

    raise HTTPException(404, f'{kind} client instance not found: {normalized_key}')


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


def _get_audio_source_bytes(audio: Any) -> bytes | None:
    source = getattr(audio, '_source', None)
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    get_value = getattr(source, 'getvalue', None)
    if callable(get_value):
        value = get_value()
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
    return None


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
    if req.client_key:
        params["client_key"] = req.client_key
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


_OPENAI_LIKED_COMPLETION_SUBPATHS = {
    "", "completions", "chat/completions",
    "v1/chat/completions", "api/v1/chat/completions",
}

_ANTHROPIC_COMPLETION_SUBPATHS = {
    "", "messages", "v1/messages",
}

_OPENAI_LIKED_EMBEDDING_SUBPATHS = {
    "", "embeddings", "embedding",
    "v1/embeddings", "v1/embedding",
    "api/v1/embeddings", "api/v1/embedding",
}

_OPENAI_LIKED_S2T_SUBPATHS = {
    "", "transcriptions", "audio/transcriptions",
    "v1/audio/transcriptions", "api/v1/audio/transcriptions",
}

_OPENAI_LIKED_T2S_SUBPATHS = {
    "", "speech", "audio/speech",
    "v1/audio/speech", "api/v1/audio/speech",
}

_OPENAI_LIKED_T2IMG_GENERATION_SUBPATHS = {
    "", "generations", "images/generations",
    "v1/images/generations", "api/v1/images/generations",
}

_OPENAI_LIKED_T2IMG_EDIT_SUBPATHS = {
    "", "edits", "images/edits",
    "v1/images/edits", "api/v1/images/edits",
}

_OPENAI_LIKED_T2IMG_VARIATION_SUBPATHS = {
    "", "variations", "images/variations",
    "v1/images/variations", "api/v1/images/variations",
}

_T2S_RESPONSE_FORMAT_MIME: dict[str, str] = {
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}


def _validate_openai_liked_suffix(path: str, allowed_subpaths: set[str]) -> None:
    if path.strip("/") not in allowed_subpaths:
        raise HTTPException(404, "Not found")


async def _run_openai_liked_stream(
    svc: _CompletionCallable,
    params: dict[str, Any],
    model: str | None,
) -> StreamingResponse:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(_time.time())
    model_name = model or getattr(svc, 'model', None) or "unknown"

    async def _sse() -> AsyncGenerator[str, None]:
        role_data = OpenAIChatCompletionStreamResponse(
            id=completion_id,
            created=created,
            model=model_name,
            choices=[OpenAIChatCompletionStreamChoice(delta={"role": "assistant"})],
        ).model_dump()
        yield f"data: {json.dumps(role_data, ensure_ascii=False)}\n\n"
        async for chunk in svc.stream_complete(**params):
            if isinstance(chunk, dict) and chunk.get("type") == "think":
                continue
            text = str(chunk.get("data", "")) if isinstance(chunk, dict) else str(chunk)
            if not text:
                continue
            data = OpenAIChatCompletionStreamResponse(
                id=completion_id,
                created=created,
                model=model_name,
                choices=[OpenAIChatCompletionStreamChoice(delta={"content": text})],
            ).model_dump()
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        data = OpenAIChatCompletionStreamResponse(
            id=completion_id,
            created=created,
            model=model_name,
            choices=[OpenAIChatCompletionStreamChoice(delta={}, finish_reason="stop")],
        ).model_dump()
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


async def _run_openai_liked_complete(
    svc: _CompletionCallable,
    params: dict[str, Any],
    model: str | None,
) -> OpenAIChatCompletionResponse:
    result = await svc.complete(**params)
    usage = svc._peek_latest_token_usage()
    model_name = model or getattr(svc, 'model', None) or "unknown"
    return OpenAIChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(_time.time()),
        model=model_name,
        choices=[OpenAIChatCompletionChoice(
            message={"role": "assistant", "content": result},
            finish_reason="stop",
        )],
        usage=OpenAIChatCompletionUsage(
            prompt_tokens=usage.get('input_tokens', 0) if usage else 0,
            completion_tokens=usage.get('output_tokens', 0) if usage else 0,
            total_tokens=usage.get('total_tokens', 0) if usage else 0,
        ),
    )


def _anthropic_block_to_openai_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, list):
        return ''.join(_anthropic_block_to_openai_text(item) for item in block)
    if not isinstance(block, dict):
        return str(block)

    block_type = str(block.get('type', '')).strip().lower()
    if block_type == 'text':
        return str(block.get('text', ''))
    if block_type == 'tool_result':
        return _anthropic_block_to_openai_text(block.get('content', ''))
    if block_type == 'tool_use':
        payload = {
            'id': block.get('id'),
            'name': block.get('name'),
            'input': block.get('input'),
        }
        return json.dumps(payload, ensure_ascii=False)
    if 'text' in block:
        return str(block.get('text', ''))
    if 'content' in block:
        return _anthropic_block_to_openai_text(block.get('content', ''))
    return json.dumps(block, ensure_ascii=False)


def _anthropic_content_to_openai(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return _anthropic_block_to_openai_text(content)

    parts: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            if block:
                parts.append({'type': 'text', 'text': block})
            continue
        if not isinstance(block, dict):
            text = str(block)
            if text:
                parts.append({'type': 'text', 'text': text})
            continue
        block_type = str(block.get('type', '')).strip().lower()
        if block_type == 'text':
            text = str(block.get('text', ''))
            if text:
                parts.append({'type': 'text', 'text': text})
            continue
        if block_type == 'image':
            source = block.get('source')
            if isinstance(source, dict) and str(source.get('type', '')).strip().lower() == 'base64':
                data = str(source.get('data', '')).strip()
                media_type = str(source.get('media_type', 'image/png')).strip() or 'image/png'
                if data:
                    parts.append({'type': 'image_url', 'image_url': {'url': f'data:{media_type};base64,{data}'}})
                    continue
        text = _anthropic_block_to_openai_text(block)
        if text:
            parts.append({'type': 'text', 'text': text})

    if len(parts) == 1 and parts[0].get('type') == 'text':
        return str(parts[0].get('text', ''))
    return parts


def _anthropic_thinking_enabled(value: bool | dict[str, Any] | None) -> bool:
    if isinstance(value, dict):
        return str(value.get('type', '')).strip().lower() not in {'', 'disabled'}
    return bool(value)


def _build_anthropic_completion_params(req: AnthropicMessagesRequest) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    if req.system is not None:
        system_content = _anthropic_content_to_openai(req.system)
        if system_content != '' and system_content != []:
            messages.append({'role': 'system', 'content': system_content})
    for message in req.messages:
        role = 'assistant' if str(message.get('role', 'user')).strip().lower() == 'assistant' else 'user'
        messages.append({'role': role, 'content': _anthropic_content_to_openai(message.get('content', ''))})

    params: dict[str, Any] = {
        'messages': messages,
        'max_tokens': req.max_tokens,
        'reasoning': _anthropic_thinking_enabled(req.thinking),
    }
    if req.temperature is not None:
        params['temperature'] = req.temperature
    if req.top_p is not None:
        params['top_p'] = req.top_p
    if req.top_k is not None:
        params['top_k'] = req.top_k
    if req.client_key:
        params['client_key'] = req.client_key
    if req.model is not None:
        params['model'] = req.model
    if req.stop_sequences:
        params['stop'] = req.stop_sequences
    return params


def _anthropic_event_payload(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _run_anthropic_liked_stream(
    svc: _CompletionCallable,
    params: dict[str, Any],
    model: str | None,
) -> StreamingResponse:
    message_id = f"msg_{uuid.uuid4().hex}"
    model_name = model or getattr(svc, 'model', None) or 'unknown'

    async def _sse() -> AsyncGenerator[str, None]:
        yield _anthropic_event_payload('message_start', {
            'type': 'message_start',
            'message': {
                'id': message_id,
                'type': 'message',
                'role': 'assistant',
                'content': [],
                'model': model_name,
                'stop_reason': None,
                'stop_sequence': None,
                'usage': {'input_tokens': 0, 'output_tokens': 0},
            },
        })
        yield _anthropic_event_payload('content_block_start', {
            'type': 'content_block_start',
            'index': 0,
            'content_block': {'type': 'text', 'text': ''},
        })
        async for chunk in svc.stream_complete(**params):
            if isinstance(chunk, dict) and chunk.get('type') == 'think':
                continue
            text = str(chunk.get('data', '')) if isinstance(chunk, dict) else str(chunk)
            if not text:
                continue
            yield _anthropic_event_payload('content_block_delta', {
                'type': 'content_block_delta',
                'index': 0,
                'delta': {'type': 'text_delta', 'text': text},
            })
        usage = svc._peek_latest_token_usage() or {}
        yield _anthropic_event_payload('content_block_stop', {
            'type': 'content_block_stop',
            'index': 0,
        })
        yield _anthropic_event_payload('message_delta', {
            'type': 'message_delta',
            'delta': {'stop_reason': 'end_turn', 'stop_sequence': None},
            'usage': {'output_tokens': int(usage.get('output_tokens', 0))},
        })
        yield _anthropic_event_payload('message_stop', {'type': 'message_stop'})

    return StreamingResponse(_sse(), media_type='text/event-stream')


async def _run_anthropic_liked_complete(
    svc: _CompletionCallable,
    params: dict[str, Any],
    model: str | None,
) -> AnthropicMessageResponse:
    result = await svc.complete(**params)
    usage = svc._peek_latest_token_usage() or {}
    model_name = model or getattr(svc, 'model', None) or 'unknown'
    return AnthropicMessageResponse(
        id=f'msg_{uuid.uuid4().hex}',
        model=model_name,
        content=[AnthropicTextContentBlock(text=result)],
        usage=AnthropicMessageUsage(
            input_tokens=int(usage.get('input_tokens', 0)),
            output_tokens=int(usage.get('output_tokens', 0)),
        ),
    )


def _register_openai_liked_completion_routes(app: FastAPI) -> None:
    async def _openai_liked_completion_response(
        req: OpenAIChatCompletionRequest,
        target: _CompletionCallable,
        *,
        direct_client: bool = False,
    ) -> StreamingResponse | OpenAIChatCompletionResponse:
        params = _build_completion_params(req)
        if direct_client:
            params.pop('client_key', None)
        if req.model is not None:
            params["model"] = req.model
        if req.stop is not None:
            params["stop"] = req.stop
        if req.seed is not None:
            params["seed"] = req.seed
        if req.response_format is not None:
            params["response_format"] = req.response_format
        if req.stream:
            return await _run_openai_liked_stream(target, params, req.model)
        return await _run_openai_liked_complete(target, params, req.model)

    @app.post(_ai_service_path('completion', 'openai'), response_model=None)
    @app.post(_ai_service_path('completion', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_completion_service(
        service_key: str,
        path: str = "",
        req: OpenAIChatCompletionRequest = ...,  # type: ignore[assignment]
    ) -> StreamingResponse | OpenAIChatCompletionResponse:
        _validate_openai_liked_suffix(path, _OPENAI_LIKED_COMPLETION_SUBPATHS)
        svc = await _resolve_ai_service_instance('completion', service_key)
        return await _openai_liked_completion_response(req, svc)

    @app.post(_ai_client_path('completion', 'openai'), response_model=None)
    @app.post(_ai_client_path('completion', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_completion_client(
        client_key: str,
        path: str = "",
        req: OpenAIChatCompletionRequest = ...,  # type: ignore[assignment]
    ) -> StreamingResponse | OpenAIChatCompletionResponse:
        _validate_openai_liked_suffix(path, _OPENAI_LIKED_COMPLETION_SUBPATHS)
        client = await _resolve_ai_client_instance('completion', client_key)
        return await _openai_liked_completion_response(req, client, direct_client=True)


def _register_anthropic_liked_completion_routes(app: FastAPI) -> None:
    async def _anthropic_liked_completion_response(
        req: AnthropicMessagesRequest,
        target: _CompletionCallable,
        *,
        direct_client: bool = False,
    ) -> StreamingResponse | AnthropicMessageResponse:
        params = _build_anthropic_completion_params(req)
        if direct_client:
            params.pop('client_key', None)
        if req.stream:
            return await _run_anthropic_liked_stream(target, params, req.model)
        return await _run_anthropic_liked_complete(target, params, req.model)

    @app.post(_ai_service_path('completion', 'anthropic'), response_model=None)
    @app.post(_ai_service_path('completion', 'anthropic/{path:path}'), response_model=None)
    @_public
    async def anthropic_liked_completion_service(
        service_key: str,
        path: str = "",
        req: AnthropicMessagesRequest = ...,  # type: ignore[assignment]
    ) -> StreamingResponse | AnthropicMessageResponse:
        _validate_openai_liked_suffix(path, _ANTHROPIC_COMPLETION_SUBPATHS)
        svc = await _resolve_ai_service_instance('completion', service_key)
        return await _anthropic_liked_completion_response(req, svc)

    @app.post(_ai_client_path('completion', 'anthropic'), response_model=None)
    @app.post(_ai_client_path('completion', 'anthropic/{path:path}'), response_model=None)
    @_public
    async def anthropic_liked_completion_client(
        client_key: str,
        path: str = "",
        req: AnthropicMessagesRequest = ...,  # type: ignore[assignment]
    ) -> StreamingResponse | AnthropicMessageResponse:
        _validate_openai_liked_suffix(path, _ANTHROPIC_COMPLETION_SUBPATHS)
        client = await _resolve_ai_client_instance('completion', client_key)
        return await _anthropic_liked_completion_response(req, client, direct_client=True)


def _register_openai_liked_embedding_routes(app: FastAPI) -> None:
    async def _openai_liked_embedding_response(
        req: OpenAIEmbeddingRequest,
        target: Any,
        *,
        direct_client: bool = False,
    ) -> OpenAIEmbeddingResponse:
        raw_input = req.input
        if isinstance(raw_input, list) and raw_input and isinstance(raw_input[0], int):
            inputs: list[Any] = [raw_input]
        elif isinstance(raw_input, list):
            inputs = raw_input
        else:
            inputs = [raw_input]

        kwargs: dict[str, Any] = {"encoding_format": req.encoding_format}
        if req.dimensions is not None:
            kwargs["dimensions"] = req.dimensions
        if req.user is not None:
            kwargs["user"] = req.user
        if req.model is not None:
            kwargs["model"] = req.model
        if req.client_key and not direct_client:
            kwargs["client_key"] = req.client_key

        raw = await target.embedding_raw(inputs, **kwargs)
        data_rows = raw.get('data', []) if isinstance(raw, dict) else []
        usage = raw.get('usage', {}) if isinstance(raw, dict) else {}
        model_name = (raw.get('model') if isinstance(raw, dict) else None) or req.model or getattr(target, 'model', None) or "unknown"

        data: list[OpenAIEmbeddingData] = []
        for index, row in enumerate(data_rows):
            if not isinstance(row, dict):
                continue
            emb = row.get('embedding', [])
            if isinstance(emb, str) and req.encoding_format == 'base64':
                from core.ai.embedding import _decode_base64_embedding
                emb = _decode_base64_embedding(emb)
            if not isinstance(emb, list):
                emb = []
            data.append(OpenAIEmbeddingData(index=int(row.get('index', index)), embedding=[float(value) for value in emb]))

        return OpenAIEmbeddingResponse(
            model=model_name,
            data=data,
            usage=OpenAIEmbeddingUsage(
                prompt_tokens=int(usage.get('prompt_tokens', 0)) if isinstance(usage, dict) else 0,
                total_tokens=int(usage.get('total_tokens', 0)) if isinstance(usage, dict) else 0,
            ),
        )

    @app.post(_ai_service_path('embedding', 'openai'), response_model=None)
    @app.post(_ai_service_path('embedding', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_embedding_service(
        service_key: str,
        path: str = "",
        req: OpenAIEmbeddingRequest = ...,  # type: ignore[assignment]
    ) -> OpenAIEmbeddingResponse:
        _validate_openai_liked_suffix(path, _OPENAI_LIKED_EMBEDDING_SUBPATHS)
        svc = await _resolve_ai_service_instance('embedding', service_key)
        return await _openai_liked_embedding_response(req, svc)

    @app.post(_ai_client_path('embedding', 'openai'), response_model=None)
    @app.post(_ai_client_path('embedding', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_embedding_client(
        client_key: str,
        path: str = "",
        req: OpenAIEmbeddingRequest = ...,  # type: ignore[assignment]
    ) -> OpenAIEmbeddingResponse:
        _validate_openai_liked_suffix(path, _OPENAI_LIKED_EMBEDDING_SUBPATHS)
        client = await _resolve_ai_client_instance('embedding', client_key)
        return await _openai_liked_embedding_response(req, client, direct_client=True)


def _register_openai_liked_s2t_routes(app: FastAPI) -> None:
    async def _parse_openai_liked_s2t_request(request: Request) -> tuple[Audio, dict[str, Any], str]:
        content_type = request.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            try:
                body = await request.json()
            except Exception as exc:
                raise HTTPException(400, f"Invalid JSON body: {exc}")
            if not isinstance(body, dict):
                raise HTTPException(400, "JSON body must be an object")
            b64_data = body.get('file') or body.get('input_audio')
            if not isinstance(b64_data, str) or not b64_data:
                raise HTTPException(400, "JSON body requires 'file' or 'input_audio' as base64 string")
            try:
                data = base64.b64decode(b64_data)
            except Exception:
                raise HTTPException(400, "Invalid base64 audio data")
            language = body.get('language')
            prompt = body.get('prompt')
            model = body.get('model')
            client_key = body.get('client_key')
            response_format = str(body.get('response_format', 'json'))
            temperature = body.get('temperature')
        else:
            try:
                form = await request.form()
            except Exception as exc:
                raise HTTPException(400, f"Invalid form data: {exc}")
            file_field = form.get('file')
            if file_field is None:
                raise HTTPException(400, "Missing 'file' field")
            if hasattr(file_field, 'read'):
                data = await file_field.read()  # type: ignore[attr-defined]
            else:
                data = str(file_field).encode()
            language = form.get('language')
            prompt = form.get('prompt')
            model = form.get('model')
            client_key = form.get('client_key')
            response_format = str(form.get('response_format', 'json'))
            temperature_text = form.get('temperature')
            temperature = float(temperature_text) if temperature_text is not None else None

        kwargs: dict[str, Any] = {'response_format': response_format}
        if language:
            kwargs['language'] = str(language)
        if prompt:
            kwargs['prompt'] = str(prompt)
        if model:
            kwargs['model'] = str(model)
        if client_key:
            kwargs['client_key'] = str(client_key)
        if temperature is not None:
            kwargs['temperature'] = temperature
        return Audio(data), kwargs, response_format

    async def _openai_liked_s2t_response(target: Any, audio: Audio, kwargs: dict[str, Any], response_format: str) -> Response:
        try:
            raw = await target.s2t_raw(audio, **kwargs)
        except Exception as e:
            raise HTTPException(500, f"S2T failed: {e}")

        if response_format in ('text', 'srt', 'vtt'):
            text = raw.get('text', '') if isinstance(raw, dict) else str(raw)
            return Response(content=text, media_type='text/plain')

        payload = raw if isinstance(raw, dict) else OpenAIS2TResponse(text=str(raw)).model_dump()
        if 'text' not in payload:
            payload['text'] = ''
        return Response(content=json.dumps(payload, ensure_ascii=False), media_type='application/json')

    @app.post(_ai_service_path('s2t', 'openai'), response_model=None)
    @app.post(_ai_service_path('s2t', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_s2t_service(request: Request, service_key: str, path: str = "") -> Response:
        _validate_openai_liked_suffix(path, _OPENAI_LIKED_S2T_SUBPATHS)
        audio, kwargs, response_format = await _parse_openai_liked_s2t_request(request)
        svc = await _resolve_ai_service_instance('s2t', service_key)
        return await _openai_liked_s2t_response(svc, audio, kwargs, response_format)

    @app.post(_ai_client_path('s2t', 'openai'), response_model=None)
    @app.post(_ai_client_path('s2t', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_s2t_client(request: Request, client_key: str, path: str = "") -> Response:
        _validate_openai_liked_suffix(path, _OPENAI_LIKED_S2T_SUBPATHS)
        audio, kwargs, response_format = await _parse_openai_liked_s2t_request(request)
        kwargs.pop('client_key', None)
        client = await _resolve_ai_client_instance('s2t', client_key)
        return await _openai_liked_s2t_response(client, audio, kwargs, response_format)


def _register_openai_liked_t2s_routes(app: FastAPI) -> None:
    async def _openai_liked_t2s_response(target: Any, req: OpenAIT2SRequest, *, direct_client: bool = False) -> Response:
        kwargs: dict[str, Any] = {
            'model': req.model,
            'voice': req.voice,
            'response_format': req.response_format,
            'speed': req.speed,
        }
        if req.instructions is not None:
            kwargs['instructions'] = req.instructions
        if req.client_key and not direct_client:
            kwargs['client_key'] = req.client_key
        try:
            audio = await target.t2s(req.input, **kwargs)
            audio_bytes = _get_audio_source_bytes(audio) or audio.to_bytes(format=req.response_format)
        except Exception as e:
            raise HTTPException(500, f"T2S failed: {e}")
        mime_type = _T2S_RESPONSE_FORMAT_MIME.get(req.response_format)
        if mime_type is None:
            mime_type, _ = _detect_audio_mime(audio_bytes)
        return Response(content=audio_bytes, media_type=mime_type)

    @app.post(_ai_service_path('t2s', 'openai'), response_model=None)
    @app.post(_ai_service_path('t2s', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_t2s_service(
        service_key: str,
        path: str = "",
        req: OpenAIT2SRequest = ...,  # type: ignore[assignment]
    ) -> Response:
        _validate_openai_liked_suffix(path, _OPENAI_LIKED_T2S_SUBPATHS)
        svc = await _resolve_ai_service_instance('t2s', service_key)
        return await _openai_liked_t2s_response(svc, req)

    @app.post(_ai_client_path('t2s', 'openai'), response_model=None)
    @app.post(_ai_client_path('t2s', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_t2s_client(
        client_key: str,
        path: str = "",
        req: OpenAIT2SRequest = ...,  # type: ignore[assignment]
    ) -> Response:
        _validate_openai_liked_suffix(path, _OPENAI_LIKED_T2S_SUBPATHS)
        client = await _resolve_ai_client_instance('t2s', client_key)
        return await _openai_liked_t2s_response(client, req, direct_client=True)


def _normalize_openai_image_output_format(output_format: str | None, response_format: str | None) -> tuple[str, str]:
    fmt = (output_format or 'png').strip().lower() or 'png'
    if fmt == 'jpg':
        fmt = 'jpeg'
    if fmt not in {'png', 'jpeg', 'webp'}:
        fmt = 'png'
    resp = (response_format or 'b64_json').strip().lower() or 'b64_json'
    if resp not in {'b64_json', 'url'}:
        resp = 'b64_json'
    return fmt, resp


def _openai_image_response(images: Any, *, response_format: str | None, output_format: str | None, background: str | None = None, quality: str | None = None, size: str | None = None, usage: dict[str, Any] | None = None) -> OpenAIImagesResponse:
    image_list = images if isinstance(images, list) else [images]
    fmt, resp = _normalize_openai_image_output_format(output_format, response_format)
    use_url = resp == 'url'
    data: list[OpenAIImageData] = []
    for image in image_list:
        if use_url:
            data.append(OpenAIImageData(url=image.to_base64(format=fmt, url_scheme=True)))
        else:
            data.append(OpenAIImageData(b64_json=image.to_base64(format=fmt)))
    return OpenAIImagesResponse(
        created=int(_time.time()),
        data=data,
        background=background,
        output_format=fmt,
        quality=quality,
        size=size,
        usage=usage,
    )


def _openai_image_stream_response(images: Any, *, response_format: str | None, output_format: str | None, background: str | None = None, quality: str | None = None, size: str | None = None) -> dict[str, Any]:
    return _openai_image_response(images, response_format=response_format, output_format=output_format, background=background, quality=quality, size=size).model_dump(exclude_none=True)


def _openai_image_extra_fields(model: AdvancedBaseModel, excluded: set[str]) -> dict[str, Any]:
    extras = getattr(model, 'model_extra', None) or {}
    return {str(key): value for key, value in dict(extras).items() if key not in excluded and value is not None}


def _openai_image_kwargs_from_generation(req: OpenAIImageGenerationRequest, *, direct_client: bool = False) -> dict[str, Any]:
    excluded = {'prompt', 'n', 'response_format', 'output_format', 'service_key', 'client_key'}
    kwargs: dict[str, Any] = {'count': req.n}
    for key in ('model', 'background', 'moderation', 'output_compression', 'partial_images', 'quality', 'size', 'stream', 'style', 'user'):
        value = getattr(req, key)
        if value is not None:
            kwargs[key] = value
    kwargs.update(_openai_image_extra_fields(req, excluded | set(kwargs)))
    if req.client_key and not direct_client:
        kwargs['client_key'] = req.client_key
    return kwargs


async def _parse_openai_liked_image_form(request: Request) -> tuple[dict[str, Any], list[Image], Image | None]:
    try:
        form = await request.form()
    except Exception as exc:
        raise HTTPException(400, f"Invalid form data: {exc}")
    kwargs: dict[str, Any] = {}
    handled_keys = {'image', 'image[]', 'images', 'mask'}
    for key in ('model', 'prompt', 'background', 'input_fidelity', 'moderation', 'quality', 'response_format', 'output_format', 'size', 'style', 'user', 'service_key', 'client_key'):
        value = form.get(key)
        handled_keys.add(key)
        if value is not None:
            kwargs[key] = str(value)
    for key in ('n', 'output_compression', 'partial_images'):
        value = form.get(key)
        handled_keys.add(key)
        if value is not None:
            kwargs[key] = int(str(value))
    for key, value in form.multi_items():
        if key in handled_keys or hasattr(value, 'filename'):
            continue
        kwargs[key] = str(value)
    if 'n' in kwargs:
        kwargs['count'] = kwargs.pop('n')
    stream_value = form.get('stream')
    if stream_value is not None:
        kwargs['stream'] = str(stream_value).lower() in {'1', 'true', 'yes', 'on'}

    async def _read_upload(value: Any) -> bytes:
        if hasattr(value, 'read'):
            return await value.read()
        if isinstance(value, str):
            return base64.b64decode(value.split(',', 1)[1] if value.startswith('data:') and ',' in value else value)
        return bytes(value)

    images: list[Image] = []
    for key in ('image', 'image[]', 'images'):
        values = form.getlist(key)
        for value in values:
            if value is not None:
                images.append(Image(await _read_upload(value)))
    mask_value = form.get('mask')
    mask = Image(await _read_upload(mask_value)) if mask_value is not None else None
    return kwargs, images, mask


def _register_openai_liked_t2img_routes(app: FastAPI) -> None:
    async def _generation_response(target: Any, req: OpenAIImageGenerationRequest, *, direct_client: bool = False) -> OpenAIImagesResponse | StreamingResponse:
        kwargs = _openai_image_kwargs_from_generation(req, direct_client=direct_client)
        if req.stream:
            async def _sse() -> AsyncGenerator[str, None]:
                try:
                    stream_func = getattr(target, 'generate_stream', None)
                    if callable(stream_func):
                        async for image in stream_func(req.prompt, **kwargs):
                            payload = _openai_image_stream_response(image, response_format=req.response_format, output_format=req.output_format, background=req.background, quality=req.quality, size=req.size)
                            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    else:
                        images = await target.generate(req.prompt, **kwargs)
                        payload = _openai_image_stream_response(images, response_format=req.response_format, output_format=req.output_format, background=req.background, quality=req.quality, size=req.size)
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(_sse(), media_type='text/event-stream')
        try:
            images = await target.generate(req.prompt, **kwargs)
        except Exception as e:
            raise HTTPException(500, f"T2Img generation failed: {e}")
        return _openai_image_response(images, response_format=req.response_format, output_format=req.output_format, background=req.background, quality=req.quality, size=req.size)

    async def _edit_response(target: Any, kwargs: dict[str, Any], images: list[Image], mask: Image | None, *, direct_client: bool = False, response_format: str | None = None, output_format: str | None = None) -> OpenAIImagesResponse:
        if not images:
            raise HTTPException(400, "Image edit requires at least one image field")
        response_format = response_format or cast(str | None, kwargs.pop('response_format', None))
        output_format = output_format or cast(str | None, kwargs.pop('output_format', None))
        prompt = str(kwargs.pop('prompt', '')).strip()
        if not prompt:
            raise HTTPException(400, "Image edit requires prompt")
        kwargs.pop('service_key', None)
        client_key = kwargs.pop('client_key', None)
        if client_key and not direct_client:
            kwargs['client_key'] = str(client_key)
        if mask is not None:
            kwargs['mask'] = mask
        try:
            result = await target.edit(images if len(images) > 1 else images[0], prompt, **kwargs)
        except Exception as e:
            raise HTTPException(500, f"T2Img edit failed: {e}")
        return _openai_image_response(result, response_format=response_format, output_format=output_format, background=cast(str | None, kwargs.get('background')), quality=cast(str | None, kwargs.get('quality')), size=cast(str | None, kwargs.get('size')))

    async def _variation_response(target: Any, kwargs: dict[str, Any], images: list[Image], *, direct_client: bool = False, response_format: str | None = None, output_format: str | None = None) -> OpenAIImagesResponse:
        if not images:
            raise HTTPException(400, "Image variation requires image field")
        response_format = response_format or cast(str | None, kwargs.pop('response_format', None))
        output_format = output_format or cast(str | None, kwargs.pop('output_format', None))
        kwargs.pop('prompt', None)
        kwargs.pop('service_key', None)
        client_key = kwargs.pop('client_key', None)
        if client_key and not direct_client:
            kwargs['client_key'] = str(client_key)
        try:
            result = await target.variation(images[0], **kwargs)
        except Exception as e:
            raise HTTPException(500, f"T2Img variation failed: {e}")
        return _openai_image_response(result, response_format=response_format, output_format=output_format, quality=cast(str | None, kwargs.get('quality')), size=cast(str | None, kwargs.get('size')))

    async def _openai_liked_t2img_response(request: Request, target: Any, path: str, *, direct_client: bool = False) -> OpenAIImagesResponse | StreamingResponse:
        normalized = path.strip('/')
        if normalized in _OPENAI_LIKED_T2IMG_EDIT_SUBPATHS and normalized not in _OPENAI_LIKED_T2IMG_GENERATION_SUBPATHS:
            kwargs, images, mask = await _parse_openai_liked_image_form(request)
            return await _edit_response(
                target, kwargs, images, mask,
                direct_client=direct_client,
                response_format=request.query_params.get('response_format'),
                output_format=request.query_params.get('output_format'),
            )
        if normalized in _OPENAI_LIKED_T2IMG_VARIATION_SUBPATHS and normalized not in _OPENAI_LIKED_T2IMG_GENERATION_SUBPATHS:
            kwargs, images, _ = await _parse_openai_liked_image_form(request)
            return await _variation_response(
                target, kwargs, images,
                direct_client=direct_client,
                response_format=request.query_params.get('response_format'),
                output_format=request.query_params.get('output_format'),
            )
        _validate_openai_liked_suffix(normalized, _OPENAI_LIKED_T2IMG_GENERATION_SUBPATHS)
        req = OpenAIImageGenerationRequest.model_validate(await request.json())
        return await _generation_response(target, req, direct_client=direct_client)

    @app.post(_ai_service_path('t2img', 'openai'), response_model=None)
    @app.post(_ai_service_path('t2img', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_t2img_service(request: Request, service_key: str, path: str = "") -> OpenAIImagesResponse | StreamingResponse:
        svc = await _resolve_ai_service_instance('t2img', service_key)
        return await _openai_liked_t2img_response(request, svc, path)

    @app.post(_ai_client_path('t2img', 'openai'), response_model=None)
    @app.post(_ai_client_path('t2img', 'openai/{path:path}'), response_model=None)
    @_public
    async def openai_liked_t2img_client(request: Request, client_key: str, path: str = "") -> OpenAIImagesResponse | StreamingResponse:
        client = await _resolve_ai_client_instance('t2img', client_key)
        return await _openai_liked_t2img_response(request, client, path, direct_client=True)


def _register_compatible_ai_service_routes(app: FastAPI) -> None:
    _register_openai_liked_completion_routes(app)
    _register_anthropic_liked_completion_routes(app)
    _register_openai_liked_embedding_routes(app)
    _register_openai_liked_s2t_routes(app)
    _register_openai_liked_t2s_routes(app)
    _register_openai_liked_t2img_routes(app)

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
        if server_cfg.is_compatible_ai_services_exposed():
            app = _AIAliasRouteRegistrar(app, internal_prefixes=[], public_prefixes=["/ai"])  # type: ignore[assignment]
            _register_compatible_ai_service_routes(app)  # type: ignore[arg-type]
        return
    app = _AIAliasRouteRegistrar(app, internal_prefixes=internal_prefixes, public_prefixes=public_prefixes)  # type: ignore[assignment]
    if server_cfg.is_compatible_ai_services_exposed():
        _register_compatible_ai_service_routes(app)  # type: ignore[arg-type]

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

    @app.post("/ai/clients/openai/list-models", response_model=ProviderModelsResponse)
    async def list_openai_liked_models(req: TempClientCredentials | None = None) -> ProviderModelsResponse:
        """获取 OpenAI-compatible 模型列表。body 必须显式传 apikey，可传 base_url 覆盖默认 OpenRouter URL。"""
        creds = req or TempClientCredentials()
        base_url = (creds.base_url or '').strip() or 'https://openrouter.ai/api/v1'
        api_key = (creds.apikey or '').strip()
        if not api_key:
            raise HTTPException(400, 'OpenAI-compatible API key required (请手动填写 API Key)')
        url = f"{base_url.rstrip('/')}/models"
        return await _proxy_models_request(url, api_key)


    # ── Completion (non-stream + SSE stream) ──────────────────────────────
    @app.post(_ai_service_path('completion', 'complete'), response_model=CompletionResponse)
    @_public
    async def complete_service(service_key: str, req: CompletionRequest) -> StreamingResponse | CompletionResponse:
        """指定 CompletionService instance 的文本补全 / 聊天接口。"""
        service_req = req.model_copy(update={'service_key': service_key})
        return await _run_completion_request(service_req, await _resolve_ai_service_instance('completion', service_key))

    @app.post('/ai/completion/service/default', response_model=CompletionResponse)
    @app.post('/ai/completion/service', response_model=CompletionResponse)
    @_public
    async def complete_default_service(req: CompletionRequest) -> StreamingResponse | CompletionResponse:
        """默认 CompletionService instance 的文本补全 / 聊天接口。"""
        return await complete_service('default', req)

    @app.post(_ai_client_path('completion', 'complete'), response_model=CompletionResponse)
    @_public
    async def complete_client(client_key: str, req: CompletionRequest) -> StreamingResponse | CompletionResponse:
        """直接指定 Completion client instance 的文本补全 / 聊天接口。"""
        client = await _resolve_ai_client_instance('completion', client_key)
        direct_req = req.model_copy(update={'client_key': None})
        return await _run_completion_request(direct_req, client)

    # ── Translate ─────────────────────────────────────────────────────────

    @app.post(_ai_service_path('completion', 'translate'), response_model=TranslateResponse)
    @app.post(_ai_client_path('completion', 'translate'), response_model=TranslateResponse)
    @_public
    async def translate(req: TranslateRequest, service_key: str | None = None, client_key: str | None = None) -> TranslateResponse:
        """文本翻译。"""
        if client_key:
            target, direct_client = await _resolve_completion_target(client_key=client_key)
        else:
            target, direct_client = await _resolve_completion_target(service_key)
        try:
            t0 = _time.perf_counter()
            pinned_client_key = None if direct_client else req.client_key
            kwargs = {'client_key': pinned_client_key} if pinned_client_key else {}
            result = await target.translate(req.text, target_language=req.target_language, **kwargs)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return TranslateResponse(
                translated=result,
                elapsed_ms=elapsed,
                request_echo={'target_language': req.target_language, 'text_length': len(req.text)},
            )
        except Exception as e:
            raise HTTPException(500, f"Translation failed: {e}")

    # ── Detect Language ───────────────────────────────────────────────────

    @app.post(_ai_service_path('completion', 'detect-language'), response_model=DetectLanguageResponse)
    @app.post(_ai_client_path('completion', 'detect-language'), response_model=DetectLanguageResponse)
    @_public
    async def detect_language(req: DetectLanguageRequest, service_key: str | None = None, client_key: str | None = None) -> DetectLanguageResponse:
        """语言检测。"""
        if client_key:
            target, direct_client = await _resolve_completion_target(client_key=client_key)
        else:
            target, direct_client = await _resolve_completion_target(service_key)
        try:
            t0 = _time.perf_counter()
            pinned_client_key = None if direct_client else req.client_key
            kwargs = {'client_key': pinned_client_key} if pinned_client_key else {}
            result = await target.detect_language(req.text, **kwargs)
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

    async def _run_ocr_request(
        target: Any,
        direct_client: bool,
        file: UploadFile,
        pinned_client_key: str | None = None,
    ) -> TextOperationResponse:
        try:
            data = await file.read()
            img = Image(data)
            t0 = _time.perf_counter()
            kwargs = {} if direct_client else {'client_key': pinned_client_key} if pinned_client_key else {}
            result = await target.ocr(img, stream=False, **kwargs)
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

    @app.post(_ai_service_path('completion', 'ocr'), response_model=TextOperationResponse)
    @_public
    async def ocr_service(
        service_key: str,
        file: UploadFile = File(...),
        client_key: str = Form(''),
    ) -> TextOperationResponse:
        """图片 OCR 文字识别。"""
        target = await _resolve_ai_service_instance('completion', service_key)
        return await _run_ocr_request(target, False, file, client_key or None)

    @app.post(_ai_client_path('completion', 'ocr'), response_model=TextOperationResponse)
    @_public
    async def ocr_client(client_key: str, file: UploadFile = File(...)) -> TextOperationResponse:
        """直接指定 Completion client instance 的 OCR 接口。"""
        target = await _resolve_ai_client_instance('completion', client_key)
        return await _run_ocr_request(target, True, file)

    # ── ASR (upload audio) ────────────────────────────────────────────────

    async def _run_asr_request(
        target: Any,
        direct_client: bool,
        file: UploadFile,
        expected_languages: str = "",
        prompt: str = "",
        pinned_client_key: str | None = None,
    ) -> TextOperationResponse:
        try:
            data = await file.read()
            audio = Audio(data)
            lang_list = [l.strip() for l in expected_languages.split(",") if l.strip()] if expected_languages else None
            t0 = _time.perf_counter()
            kwargs = {} if direct_client else {'client_key': pinned_client_key} if pinned_client_key else {}
            result = await target.asr(
                audio,
                prompt=prompt or None,
                expected_languages=lang_list or None,
                stream=False,
                **kwargs,
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

    @app.post(_ai_service_path('completion', 'asr'), response_model=TextOperationResponse)
    @_public
    async def asr_service(
        service_key: str,
        file: UploadFile = File(...),
        expected_languages: str = Form(""),
        prompt: str = Form(""),
        client_key: str = Form(''),
    ) -> TextOperationResponse:
        """音频语音识别 (ASR)。支持 expected_languages (逗号分隔语言代码) 和自定义 prompt。"""
        target = await _resolve_ai_service_instance('completion', service_key)
        return await _run_asr_request(target, False, file, expected_languages, prompt, client_key or None)

    @app.post(_ai_client_path('completion', 'asr'), response_model=TextOperationResponse)
    @_public
    async def asr_client(
        client_key: str,
        file: UploadFile = File(...),
        expected_languages: str = Form(""),
        prompt: str = Form(""),
    ) -> TextOperationResponse:
        """直接指定 Completion client instance 的 ASR 接口。"""
        target = await _resolve_ai_client_instance('completion', client_key)
        return await _run_asr_request(target, True, file, expected_languages, prompt)

    # ── Summarize ─────────────────────────────────────────────────────────

    async def _run_summarize_request(
        target: Any,
        direct_client: bool,
        req: SummarizeRequest,
        pinned_client_key: str | None = None,
    ) -> StreamingResponse | SummarizeResponse:
        kwargs: dict[str, Any] = {}
        if req.chunk_size is not None:
            kwargs["chunk_size"] = req.chunk_size
        if req.sliding_window_size != 0.15:
            kwargs["sliding_window_size"] = req.sliding_window_size
        if pinned_client_key and not direct_client:
            kwargs['client_key'] = pinned_client_key

        if req.stream:
            async def _sse_summarize():
                t0 = _time.perf_counter()
                try:
                    result = await target.summarize(
                        req.text,
                        prompt=req.prompt or None,
                        stream=True,
                        **kwargs,
                    )
                    elapsed = round((_time.perf_counter() - t0) * 1000)
                    usage = target._peek_latest_token_usage()
                    payload = {"summary": result, "elapsed_ms": elapsed, "token_usage": usage}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return StreamingResponse(_sse_summarize(), media_type="text/event-stream")

        try:
            t0 = _time.perf_counter()
            result = await target.summarize(
                req.text,
                prompt=req.prompt or None,
                stream=False,
                **kwargs,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            usage = target._peek_latest_token_usage()
            return SummarizeResponse(
                summary=result,
                elapsed_ms=elapsed,
                token_usage=TokenUsageResponse.model_validate(usage or {}),
            )
        except Exception as e:
            raise HTTPException(500, f"Summarize failed: {e}")

    @app.post(_ai_service_path('completion', 'summarize'), response_model=SummarizeResponse)
    @_public
    async def summarize_service(service_key: str, req: SummarizeRequest) -> StreamingResponse | SummarizeResponse:
        """文本摘要。支持 chunk_size / sliding_window_size / prompt / stream 参数。"""
        target = await _resolve_ai_service_instance('completion', service_key)
        return await _run_summarize_request(target, False, req, req.client_key)

    @app.post(_ai_client_path('completion', 'summarize'), response_model=SummarizeResponse)
    @_public
    async def summarize_client(client_key: str, req: SummarizeRequest) -> StreamingResponse | SummarizeResponse:
        """直接指定 Completion client instance 的摘要接口。"""
        target = await _resolve_ai_client_instance('completion', client_key)
        return await _run_summarize_request(target, True, req)

    # ── S2T (upload audio) ────────────────────────────────────────────────

    async def _run_s2t_request(
        target: Any,
        direct_client: bool,
        file: UploadFile,
        service_key: str | None = None,
        pinned_client_key: str | None = None,
    ) -> TextOperationResponse:
        try:
            data = await file.read()
            audio = Audio(data)
            t0 = _time.perf_counter()
            if direct_client:
                result = await target.s2t(audio)
            else:
                result = await target.s2t(audio, client_key=pinned_client_key)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return TextOperationResponse(
                text=result,
                elapsed_ms=elapsed,
                request_echo=FileRequestEcho(
                    filename=file.filename,
                    content_type=file.content_type,
                    bytes=len(data),
                ).model_dump() | {
                    'service_key': _normalize_service_key(service_key) if service_key else None,
                    'client_key': str(pinned_client_key or '').strip() or None,
                },
            )
        except Exception as e:
            raise HTTPException(500, f"S2T failed: {e}")

    @app.post(_ai_service_path('s2t', 's2t'), response_model=TextOperationResponse)
    @_public
    async def s2t_service(
        service_key: str,
        file: UploadFile = File(...),
        client_key: str | None = Form(None),
    ) -> TextOperationResponse:
        """指定 S2TService instance 的语音转文字接口。"""
        target = await _resolve_ai_service_instance('s2t', service_key)
        return await _run_s2t_request(target, False, file, service_key, client_key)

    @app.post('/ai/s2t/service/default', response_model=TextOperationResponse)
    @app.post('/ai/s2t/service', response_model=TextOperationResponse)
    @_public
    async def s2t_default_service(
        file: UploadFile = File(...),
        client_key: str | None = Form(None),
    ) -> TextOperationResponse:
        """默认 S2TService instance 的语音转文字接口。"""
        return await s2t_service('default', file, client_key)

    @app.post(_ai_client_path('s2t', 's2t'), response_model=TextOperationResponse)
    @_public
    async def s2t_client(client_key: str, file: UploadFile = File(...)) -> TextOperationResponse:
        """直接指定 S2T client instance 的语音转文字接口。"""
        target = await _resolve_ai_client_instance('s2t', client_key)
        return await _run_s2t_request(target, True, file, pinned_client_key=client_key)

    # ── T2S ───────────────────────────────────────────────────────────────

    async def _run_t2s_request(
        target: Any,
        direct_client: bool,
        req: T2SRequest,
        service_key: str | None = None,
        pinned_client_key: str | None = None,
    ) -> T2SResponse:
        try:
            t0 = _time.perf_counter()
            if direct_client:
                audio = await target.t2s(req.text)
            else:
                audio = await target.t2s(req.text, client_key=pinned_client_key)
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
                request_echo={
                    'text_length': len(req.text),
                    'service_key': _normalize_service_key(service_key) if service_key else None,
                    'client_key': str(pinned_client_key or '').strip() or None,
                },
            )
        except Exception as e:
            raise HTTPException(500, f"T2S failed: {e}")

    @app.post(_ai_service_path('t2s', 't2s'), response_model=T2SResponse)
    @_public
    async def t2s_service(service_key: str, req: T2SRequest) -> T2SResponse:
        """指定 T2SService instance 的文字转语音接口。"""
        target = await _resolve_ai_service_instance('t2s', service_key)
        return await _run_t2s_request(target, False, req, service_key, req.client_key)

    @app.post('/ai/t2s/service/default', response_model=T2SResponse)
    @app.post('/ai/t2s/service', response_model=T2SResponse)
    @_public
    async def t2s_default_service(req: T2SRequest) -> T2SResponse:
        """默认 T2SService instance 的文字转语音接口。"""
        return await t2s_service('default', req)

    @app.post(_ai_client_path('t2s', 't2s'), response_model=T2SResponse)
    @_public
    async def t2s_client(client_key: str, req: T2SRequest) -> T2SResponse:
        """直接指定 T2S client instance 的文字转语音接口。"""
        target = await _resolve_ai_client_instance('t2s', client_key)
        return await _run_t2s_request(target, True, req, pinned_client_key=client_key)

    async def _run_t2s_stream_request(
        target: Any,
        direct_client: bool,
        req: T2SRequest,
        service_key: str | None = None,
        pinned_client_key: str | None = None,
    ) -> StreamingResponse:
        chunk_size = max(1024, int(req.chunk_size or 16384))

        async def _stream_audio():
            if direct_client:
                async for chunk in target.t2s_stream(req.text, chunk_size=chunk_size):
                    yield chunk
            else:
                async for chunk in target.t2s_stream(req.text, chunk_size=chunk_size, client_key=pinned_client_key):
                    yield chunk

        return StreamingResponse(
            _stream_audio(),
            media_type='audio/wav',
            headers={
                'X-AI-Mode': 't2s-stream',
                'X-AI-Chunk-Size': str(chunk_size),
                'X-AI-Service-Key': _normalize_service_key(service_key) if service_key else '',
                'X-AI-Client-Key': str(pinned_client_key or '').strip() or '',
            },
        )

    @app.post(_ai_service_path('t2s', 'stream'))
    @_public
    async def t2s_stream_service(service_key: str, req: T2SRequest) -> StreamingResponse:
        """指定 T2SService instance 的文字转语音流式接口。"""
        target = await _resolve_ai_service_instance('t2s', service_key)
        return await _run_t2s_stream_request(target, False, req, service_key, req.client_key)

    @app.post(_ai_client_path('t2s', 'stream'))
    @_public
    async def t2s_stream_client(client_key: str, req: T2SRequest) -> StreamingResponse:
        """直接指定 T2S client instance 的文字转语音流式接口。"""
        target = await _resolve_ai_client_instance('t2s', client_key)
        return await _run_t2s_stream_request(target, True, req, pinned_client_key=client_key)

    # ── Embedding ─────────────────────────────────────────────────────────

    def _embedding_payload(req: EmbeddingRequest) -> str | list[str]:
        payload: str | list[str] | None = None
        if req.text is not None and req.text.strip():
            payload = req.text
        elif req.texts:
            payload = [text for text in req.texts if text.strip()]
        if payload is None or (isinstance(payload, list) and not payload):
            raise HTTPException(400, "Embedding request requires `text` or non-empty `texts`.")
        return payload

    @app.post(_ai_service_path('embedding', 'embedding'), response_model=EmbeddingResponse)
    @_public
    async def embedding_service(service_key: str, req: EmbeddingRequest) -> EmbeddingResponse:
        """指定 EmbeddingService instance 的文本向量化接口。"""
        svc = await _resolve_ai_service_instance('embedding', service_key)
        try:
            t0 = _time.perf_counter()
            payload = _embedding_payload(req)
            result = await svc.embedding(
                payload,
                use_cache=req.use_cache,
                save_cache=req.save_cache,
                client_key=req.client_key,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            if isinstance(payload, str):
                return EmbeddingResponse(vector=result, elapsed_ms=elapsed)
            return EmbeddingResponse(vectors=result, elapsed_ms=elapsed)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Embedding failed: {e}")

    @app.post('/ai/embedding/service/default', response_model=EmbeddingResponse)
    @app.post('/ai/embedding/service', response_model=EmbeddingResponse)
    @_public
    async def embedding_default_service(req: EmbeddingRequest) -> EmbeddingResponse:
        """默认 EmbeddingService instance 的文本向量化接口。"""
        return await embedding_service('default', req)

    @app.post(_ai_client_path('embedding', 'embedding'), response_model=EmbeddingResponse)
    @_public
    async def embedding_client(client_key: str, req: EmbeddingRequest) -> EmbeddingResponse:
        """直接指定 Embedding client instance 的文本向量化接口。"""
        client = await _resolve_ai_client_instance('embedding', client_key)
        try:
            t0 = _time.perf_counter()
            payload = _embedding_payload(req)
            client_payload = [payload] if isinstance(payload, str) else payload
            result = await client.embedding(
                client_payload,
                use_cache=req.use_cache,
                save_cache=req.save_cache,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            if isinstance(payload, str):
                vector = result[0] if result else []
                return EmbeddingResponse(vector=vector, elapsed_ms=elapsed)
            return EmbeddingResponse(vectors=result, elapsed_ms=elapsed)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Embedding failed: {e}")

    @app.post(_ai_service_path('embedding', 'rerank'), response_model=RankedItemsResponse)
    @_public
    async def embedding_rerank_service(service_key: str, req: EmbeddingRerankRequest) -> RankedItemsResponse:
        """基于语义相似度的重排序。"""
        svc = await _resolve_ai_service_instance('embedding', service_key)
        try:
            t0 = _time.perf_counter()
            items = await svc.rerank(req.query, req.candidates, client_key=req.client_key)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return RankedItemsResponse(
                items=[RankedItemResponse(index=it.index, score=it.score, candidate=it.candidate) for it in items],
                elapsed_ms=elapsed,
            )
        except Exception as e:
            raise HTTPException(500, f"Embedding rerank failed: {e}")

    @app.post(_ai_client_path('embedding', 'rerank'), response_model=RankedItemsResponse)
    @_public
    async def embedding_rerank_client(client_key: str, req: EmbeddingRerankRequest) -> RankedItemsResponse:
        """直接指定 Embedding client instance 的语义重排序接口。"""
        client = await _resolve_ai_client_instance('embedding', client_key)
        try:
            t0 = _time.perf_counter()
            if not req.candidates:
                items: list[RankedItemResponse] = []
            else:
                query_stripped = req.query.strip()
                exact_match_indices = {i for i, candidate in enumerate(req.candidates) if candidate.strip() == query_stripped}
                rerank_candidates = [candidate for i, candidate in enumerate(req.candidates) if i not in exact_match_indices]
                rerank_indices = [i for i in range(len(req.candidates)) if i not in exact_match_indices]
                items = [
                    RankedItemResponse(index=i, score=1.0, candidate=req.candidates[i])
                    for i in exact_match_indices
                ]
                if rerank_candidates:
                    vectors = await client.embedding([req.query, *rerank_candidates])
                    query_vector = vectors[0]
                    items.extend(
                        RankedItemResponse(
                            index=original_index,
                            score=_cosine_similarity(query_vector, vectors[local_index + 1]),
                            candidate=req.candidates[original_index],
                        )
                        for local_index, original_index in enumerate(rerank_indices)
                    )
                items.sort(key=lambda item: item.score or 0.0, reverse=True)
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return RankedItemsResponse(items=items, elapsed_ms=elapsed)
        except Exception as e:
            raise HTTPException(500, f"Embedding rerank failed: {e}")

    @app.post(_ai_service_path('embedding', 'chunking'), response_model=EmbeddingChunkingResponse)
    @_public
    async def embedding_chunking_service(service_key: str, req: EmbeddingChunkingRequest) -> EmbeddingChunkingResponse:
        """长文本分块并向量化。"""
        svc = await _resolve_ai_service_instance('embedding', service_key)
        try:
            t0 = _time.perf_counter()
            chunks = await svc.chunking(
                req.content,
                max_word_count=req.max_word_count,
                use_cache=req.use_cache,
                save_cache=req.save_cache,
                client_key=req.client_key,
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

    @app.post(_ai_client_path('embedding', 'chunking'), response_model=EmbeddingChunkingResponse)
    @_public
    async def embedding_chunking_client(client_key: str, req: EmbeddingChunkingRequest) -> EmbeddingChunkingResponse:
        """直接指定 Embedding client instance 的分块向量化接口。"""
        from core.utils.text_utils import split_text_by_word_count

        client = await _resolve_ai_client_instance('embedding', client_key)
        try:
            t0 = _time.perf_counter()
            chunks = split_text_by_word_count(req.content, max_word_count=req.max_word_count) if req.content.strip() else []
            vectors = await client.embedding([chunk['text'] for chunk in chunks]) if chunks else []
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return EmbeddingChunkingResponse(
                chunks=[
                    EmbeddingChunkResponse(
                        text=chunk['text'],
                        vector=vector,
                        index=index,
                        offset=chunk['offset'],
                    )
                    for index, (chunk, vector) in enumerate(zip(chunks, vectors))
                ],
                elapsed_ms=elapsed,
            )
        except Exception as e:
            raise HTTPException(500, f"Embedding chunking failed: {e}")

    @app.post(_ai_service_path('embedding', 'diversity'), response_model=RankedItemsResponse)
    @_public
    async def embedding_diversity_service(service_key: str, req: EmbeddingDiversityRequest) -> RankedItemsResponse:
        """基于多样性的候选文本重排序。"""
        svc = await _resolve_ai_service_instance('embedding', service_key)
        try:
            t0 = _time.perf_counter()
            items = await svc.diversity_rerank(req.candidates, top_k=req.top_k, client_key=req.client_key)
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

    @app.post(_ai_client_path('embedding', 'diversity'), response_model=RankedItemsResponse)
    @_public
    async def embedding_diversity_client(client_key: str, req: EmbeddingDiversityRequest) -> RankedItemsResponse:
        """直接指定 Embedding client instance 的多样性重排序接口。"""
        client = await _resolve_ai_client_instance('embedding', client_key)
        try:
            t0 = _time.perf_counter()
            candidates = req.candidates
            if not candidates:
                ranked_items: list[RankedItemResponse] = []
            else:
                k = min(req.top_k or len(candidates), len(candidates))
                vectors = await client.embedding(list(candidates))
                selected: list[int] = []
                remaining = set(range(len(candidates)))
                norms = [sum(value * value for value in vector) ** 0.5 for vector in vectors]
                first = max(remaining, key=lambda i: norms[i])
                selected.append(first)
                remaining.discard(first)
                min_dists = {idx: 1.0 - _cosine_similarity(vectors[idx], vectors[first]) for idx in remaining}
                while len(selected) < k and remaining:
                    best = max(remaining, key=lambda i: min_dists.get(i, 0.0))
                    selected.append(best)
                    remaining.discard(best)
                    best_vector = vectors[best]
                    for idx in remaining:
                        dist = 1.0 - _cosine_similarity(vectors[idx], best_vector)
                        if dist < min_dists.get(idx, float('inf')):
                            min_dists[idx] = dist
                ranked_items = [
                    RankedItemResponse(
                        index=idx,
                        candidate=candidates[idx],
                        min_distance=min_dists.get(idx, 0.0) if order > 0 else 0.0,
                    )
                    for order, idx in enumerate(selected)
                ]
            elapsed = round((_time.perf_counter() - t0) * 1000)
            return RankedItemsResponse(items=ranked_items, elapsed_ms=elapsed)
        except Exception as e:
            raise HTTPException(500, f"Embedding diversity rerank failed: {e}")

    # ── Transcript (diarization) ──────────────────────────────────────────

    async def _run_transcript_request(
        target: Any,
        direct_client: bool,
        file: UploadFile,
        roles: str = "",
        expected_languages: str = "",
        prompt: str = "",
        pinned_client_key: str | None = None,
    ) -> TranscriptResponse:
        try:
            data = await file.read()
            audio = Audio(data)
            role_list = [r.strip() for r in roles.split(",") if r.strip()] if roles else None
            lang_list = [l.strip() for l in expected_languages.split(",") if l.strip()] if expected_languages else None
            t0 = _time.perf_counter()
            kwargs = {} if direct_client else {'client_key': pinned_client_key} if pinned_client_key else {}
            result = await target.transcript(
                audio,
                roles=role_list,
                expected_languages=lang_list or None,
                prompt=prompt or None,
                stream=False,
                **kwargs,
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

    @app.post(_ai_service_path('completion', 'transcript'), response_model=TranscriptResponse)
    @_public
    async def transcript_service(
        service_key: str,
        file: UploadFile = File(...),
        roles: str = Form(""),
        expected_languages: str = Form(""),
        prompt: str = Form(""),
        client_key: str = Form(''),
    ) -> TranscriptResponse:
        """音频说话人分离与转录。支持 roles / expected_languages / prompt 参数。"""
        target = await _resolve_ai_service_instance('completion', service_key)
        return await _run_transcript_request(target, False, file, roles, expected_languages, prompt, client_key or None)

    @app.post(_ai_client_path('completion', 'transcript'), response_model=TranscriptResponse)
    @_public
    async def transcript_client(
        client_key: str,
        file: UploadFile = File(...),
        roles: str = Form(""),
        expected_languages: str = Form(""),
        prompt: str = Form(""),
    ) -> TranscriptResponse:
        """直接指定 Completion client instance 的转录接口。"""
        target = await _resolve_ai_client_instance('completion', client_key)
        return await _run_transcript_request(target, True, file, roles, expected_languages, prompt)

    # ── LLM Rerank ────────────────────────────────────────────────────────

    async def _run_completion_rerank_request(target: Any, req: CompletionRerankRequest) -> RankedItemsResponse:
        try:
            t0 = _time.perf_counter()
            result = await target.rerank(
                req.query,
                req.candidates,
                prompt=req.prompt or None,
                stream=req.stream,
            )
            elapsed = round((_time.perf_counter() - t0) * 1000)
            usage = target._peek_latest_token_usage()
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

    @app.post(_ai_service_path('completion', 'rerank'), response_model=RankedItemsResponse)
    @_public
    async def completion_rerank_service(service_key: str, req: CompletionRerankRequest) -> RankedItemsResponse:
        """基于 LLM 的语义重排序 (0–10 评分)。"""
        target = await _resolve_ai_service_instance('completion', service_key)
        return await _run_completion_rerank_request(target, req)

    @app.post(_ai_client_path('completion', 'rerank'), response_model=RankedItemsResponse)
    @_public
    async def completion_rerank_client(client_key: str, req: CompletionRerankRequest) -> RankedItemsResponse:
        """直接指定 Completion client instance 的 LLM 重排序接口。"""
        from core.ai.completion import CompletionService

        client = await _resolve_ai_client_instance('completion', client_key)
        target = CompletionService([client])
        return await _run_completion_rerank_request(target, req)

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
