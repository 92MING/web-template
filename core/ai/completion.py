import re
import json
import time
import hashlib
import asyncio
import logging
import aiohttp
import inspect
import unicodedata

from types import UnionType
from functools import partial, cache
from typing_extensions import Unpack
from pydantic.fields import PydanticUndefined  # type: ignore
from pydantic.v1 import BaseModel as BaseModelV1
from pydantic import BaseModel, ConfigDict, Field, create_model, model_serializer, model_validator
from thinkthinksyn import ThinkThinkSyn

from typing import (
    TYPE_CHECKING, Any, AsyncGenerator, Awaitable, ClassVar, Sequence, Literal, Callable, TypeVar, Union, cast, overload,
    TypedDict, NotRequired, Required, Protocol, runtime_checkable, Self
)

from core.storage.orm import ORMModel, ORMField
from core.utils.data_structs import File, Audio, Image, Video, LLMDocumentMixin 
from core.utils.concurrent_utils import run_any_func
from core.utils.text_utils import json_repair_loads, Language, detect_language as detect_lang, split_text_by_word_count, truncate_text_by_word_count, word_count
from core.utils.type_utils import get_pydantic_type_adapter, AdvancedBaseModel, create_type_default_instance
from core.utils.network_utils.proxy_requests import aiosseclient_with_proxy

from .base import (
    StrategyLevel,
    ServiceClient,
    ServiceClientBase,
    ServiceCallLogMixin,
    ServiceBase,
    ServiceInitParams,
    ServiceClientInitParams,
    ServiceParamsBase,
    ConcurrentPool,
    _AnnotateDefault,
    _apply_service_param_defaults,
    _env_first,
    _detect_local_tts_base_url,
    _patch_thinkthinksyn_proxy,
    _create_proxied_thinkthinksyn,
    _rewrite_url_for_ssh_tunnel,
    _apply_ssh_tunnel_to_tts_client,
    _resolve_ssh_tunnel_config,
    _sanitize_for_log,
    _truncate_text,
    get_inference_context,
    enter_service_context,
    exit_service_context,
)
from .shared import AIServiceKind, CompletionConcurrentPool
from ._multimodal_token_utils import (
    TokenCountable,
    compress_image_to_token_budget,
    estimate_multimodal_tokens,
    estimate_text_tokens,
    split_audio_on_silence,
    split_video_to_token_budget,
    trim_audio_to_token_budget,
    trim_video_to_token_budget,
)

if TYPE_CHECKING:
    from .s2t import S2TService
    from ...utils.network_utils.ssh_tunnel import SSHTunnelConfig

_logger = logging.getLogger(__name__)
_T = TypeVar('_T')
_NO_TRANSLATION_CACHE_LEN = 8192
_DEFAULT_COMPLETION_TIMEOUT = 180.0
'''默认 completion 请求超时（秒）。'''

# Translation-noise ranges mostly cover emoji/pictograph-heavy blocks and invisible
# formatting controls that should not be translated on their own.
_TRANSLATION_NOISE_RANGES: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD),      # Soft Hyphen
    (0x200B, 0x200F),      # Zero-width / bidi helpers
    (0x202A, 0x202E),      # Bidi embedding / override
    (0x2060, 0x206F),      # Word joiner / invisible format controls
    (0x2190, 0x21FF),      # Arrows
    (0x2300, 0x23FF),      # Miscellaneous Technical
    (0x2460, 0x24FF),      # Enclosed Alphanumerics
    (0x2500, 0x257F),      # Box Drawing
    (0x2580, 0x259F),      # Block Elements
    (0x25A0, 0x25FF),      # Geometric Shapes
    (0x2600, 0x26FF),      # Miscellaneous Symbols
    (0x2700, 0x27BF),      # Dingbats
    (0x27F0, 0x27FF),      # Supplemental Arrows-A
    (0x2900, 0x297F),      # Supplemental Arrows-B
    (0x2980, 0x29FF),      # Miscellaneous Mathematical Symbols-B
    (0x2A00, 0x2BFF),      # Supplemental Mathematical Operators + misc arrows/shapes
    (0xFE00, 0xFE0F),      # Variation Selectors
    (0x1F000, 0x1FAFF),    # Mahjong / domino / emoji / pictographs blocks
    (0x1FB00, 0x1FBFF),    # Symbols for Legacy Computing
    (0xE0000, 0xE007F),    # Tags
    (0xE0100, 0xE01EF),    # Variation Selectors Supplement
)

__all__: list[str] = []


def _is_codepoint_in_ranges(codepoint: int, ranges: Sequence[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start <= codepoint <= end:
            return True
    return False


def _is_translation_noise_char(ch: str) -> bool:
    if not ch:
        return True
    if ch.isspace():
        return True
    codepoint = ord(ch)
    if 0xFDD0 <= codepoint <= 0xFDEF or (codepoint & 0xFFFF) in {0xFFFE, 0xFFFF}:
        return True
    if _is_codepoint_in_ranges(codepoint, _TRANSLATION_NOISE_RANGES):
        return True
    category = unicodedata.category(ch)
    if category in {'Cc', 'Cf', 'Cs', 'Co', 'Cn'}:
        return True
    if category.startswith('Z') or category.startswith('P') or category.startswith('S'):
        return True
    return False


def _normalize_translation_signal_text(text: str | None) -> str:
    if not text:
        return ''
    normalized = unicodedata.normalize('NFKC', text)
    kept = ''.join(ch for ch in normalized if not _is_translation_noise_char(ch))
    return kept.casefold().strip()


def _sanitize_translation_reference(text: str, reference: str | None) -> str | None:
    normalized_text = _normalize_translation_signal_text(text)
    if not normalized_text or not reference or not reference.strip():
        return None
    normalized_reference = _normalize_translation_signal_text(reference)
    if not normalized_reference or normalized_reference == normalized_text:
        return None
    return reference.strip()

class ChatCompletionOutput(TypedDict):
    '''Chat Completion 完整输出结构。'''
    text: str
    '''模型最终生成的文本内容。'''
    thinking: str | None
    '''推理 / chain-of-thought 内容；未启用或模型不支持时为 ``None``。'''
    input_tokens: int | None
    '''输入 token 数；无法获取时为 ``None``。'''
    output_tokens: int | None
    '''输出 token 数（含 thinking token）；无法获取时为 ``None``。'''

class CompletionStreamChunk(TypedDict):
    '''流式补全的单个输出块。'''
    data: str
    '''当前分片携带的文本内容。'''
    type: Literal['text', 'think']
    '''分片类型；`text` 表示正文，`think` 表示推理内容。'''

class _StreamLogCollector:
    '''收集流式返回的最终文本, 正确分离正文与推理内容。'''

    def __init__(self):
        self._text_parts: list[str] = []
        self._think_parts: list[str] = []

    def add(self, chunk: "CompletionStreamChunk") -> None:
        data = str(chunk.get('data', ''))
        if data:
            if chunk.get('type') == 'think':
                self._think_parts.append(data)
            else:
                self._text_parts.append(data)

    def final_text(self) -> str:
        return ''.join(self._text_parts)

    def final_think_text(self) -> str:
        return ''.join(self._think_parts)

    def as_response(self, *, mode: Literal['stream', 'non-stream']) -> dict[str, Any]:
        return {
            'text': self.final_text(),
            'mode': mode,
        }
            
type ChatRole = Literal['system', 'user', 'assistant'] | str

MEDIA_TAG = '<__MEDIA__>'
'''Prompt 中标注附件插入位置的占位符。'''

@runtime_checkable
class _LLMContentProtocol(Protocol):
    '''可转换为 LLM 输入的内容协议。实现者须提供 ``to_llm`` 方法。'''
    def to_llm(self, **kwargs: Any) -> 'str | File | Sequence[str | File] | Awaitable[str | File | Sequence[str | File]]':
        ...

_STRING_TYPE_ADAPTER = get_pydantic_type_adapter(str)
_FILE_TYPE_ADAPTER = get_pydantic_type_adapter(File)

def _serialize_file_content(value: File) -> dict[str, Any]:
    dumped = _FILE_TYPE_ADAPTER.dump_python(value, mode='json')
    if not isinstance(dumped, dict):
        raise TypeError(f'Unsupported serialized file content type: {type(dumped).__name__}')
    return cast(dict[str, Any], dumped)

def _coerce_native_llm_part(value: Any) -> str | File:
    if isinstance(value, str):
        return value
    if isinstance(value, (Image, Audio, Video, LLMDocumentMixin)):
        return cast(File, value)
    try:
        return _STRING_TYPE_ADAPTER.validate_python(value)
    except Exception:
        ...
    try:
        return cast(File, _FILE_TYPE_ADAPTER.validate_python(value))
    except Exception as exc:
        raise ValueError(f'Unsupported native LLM content item: {type(value).__name__}') from exc

def _serialize_native_llm_part(value: str | File) -> str | dict[str, Any]:
    if isinstance(value, str):
        return value
    return _serialize_file_content(value)


class _UnknownLLMContent(AdvancedBaseModel):
    '''无法原生 roundtrip 的 LLMContent 降级封装。'''

    if not TYPE_CHECKING:
        model_config = ConfigDict(arbitrary_types_allowed=True)

    content: list[str | File] = Field(default_factory=list)

    @model_validator(mode='before')
    @classmethod
    def _normalize_unknown_content(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return {'content': [_coerce_native_llm_part(item) for item in value]}
        if isinstance(value, dict) and isinstance(value.get('content'), (list, tuple)):
            payload = dict(value)
            payload['content'] = [_coerce_native_llm_part(item) for item in payload['content']]
            return payload
        return value

    def to_llm(self, **kwargs: Any) -> list[str | File]:
        return list(self.content)

    @model_serializer(mode='plain')
    def _serialize(self) -> list[str | dict[str, Any]]:
        return [_serialize_native_llm_part(item) for item in self.content]


type LLMContent = str | Image | Audio | Video | LLMDocumentMixin | _UnknownLLMContent | _LLMContentProtocol

def _is_runtime_llm_content(value: object) -> bool:
    return isinstance(value, (str, Image, Audio, Video, LLMDocumentMixin, _UnknownLLMContent, _LLMContentProtocol))

def _normalize_unknown_llm_content(value: Any) -> _UnknownLLMContent:
    if isinstance(value, _UnknownLLMContent):
        return value
    if isinstance(value, dict) and 'content' in value:
        return _UnknownLLMContent.model_validate(value)
    if isinstance(value, (list, tuple)):
        return _UnknownLLMContent(content=[_coerce_native_llm_part(item) for item in value])
    raise TypeError(f'Cannot convert {type(value).__name__} to _UnknownLLMContent')

def _restore_prompt_attach(value: Any) -> LLMContent:
    if _is_runtime_llm_content(value):
        return cast(LLMContent, value)

    if isinstance(value, dict):
        if 'content' in value:
            return _normalize_unknown_llm_content(value)
        return cast(LLMContent, _coerce_native_llm_part(value))

    if isinstance(value, (list, tuple)):
        return _normalize_unknown_llm_content(value)

    return cast(LLMContent, _coerce_native_llm_part(value))

def _dump_prompt_attach(attach: LLMContent) -> str | dict[str, Any] | list[str | dict[str, Any]]:
    if isinstance(attach, str):
        return attach
    if isinstance(attach, (Image, Audio, Video, LLMDocumentMixin)):
        return _serialize_file_content(cast(File, attach))
    if isinstance(attach, _UnknownLLMContent):
        return attach.model_dump(mode='json')
    if isinstance(attach, _LLMContentProtocol):
        expanded = run_any_func(attach.to_llm)
        if isinstance(expanded, (list, tuple)):
            wrapped = _UnknownLLMContent(content=[_coerce_native_llm_part(item) for item in expanded])
        else:
            wrapped = _UnknownLLMContent(content=[_coerce_native_llm_part(expanded)])
        return wrapped.model_dump(mode='json')
    return _serialize_native_llm_part(_coerce_native_llm_part(attach))

class Prompt(AdvancedBaseModel):
    '''结构化提示词，包含文本数据与可选附件。

    ``data`` 中可使用 ``MEDIA_TAG`` (``<__MEDIA__>``) 标注附件插入位置。
    - 标签数量 < 附件数量时，剩余附件自动追加到文本末尾。
    - 标签数量 > 附件数量时，多余标签自动移除。
    '''

    if not TYPE_CHECKING:
        model_config = ConfigDict(arbitrary_types_allowed=True)

    data: str
    '''文本内容，可包含 ``<__MEDIA__>`` 占位符。'''
    attaches: list[LLMContent] = Field(default_factory=list)
    '''附件列表；原生可 roundtrip 的 ``str/File`` 保持原样，其余内容在序列化时退化为 ``_UnknownLLMContent``。'''

    @model_validator(mode='before')
    @classmethod
    def _normalize_attaches_before_validate(cls, data: Any) -> Any:
        if not isinstance(data, dict) or 'attaches' not in data:
            return data

        raw_attaches = data.get('attaches')
        if raw_attaches is None:
            return data
        if not isinstance(raw_attaches, (list, tuple)):
            raise TypeError('Prompt.attaches must be a list or tuple.')

        payload = dict(data)
        payload['attaches'] = [_restore_prompt_attach(item) for item in raw_attaches]
        return payload

    def model_post_init(self, __context: Any) -> None:
        self.data = inspect.cleandoc(self.data)

    @model_validator(mode='after')
    def _normalize_media_tags(self) -> 'Prompt':
        tag_count = self.data.count(MEDIA_TAG)
        attach_count = len(self.attaches)
        if tag_count > attach_count:
            parts = self.data.split(MEDIA_TAG)
            rebuilt: list[str] = [parts[0]]
            for i in range(1, len(parts)):
                if i <= attach_count:
                    rebuilt.append(MEDIA_TAG)
                rebuilt.append(parts[i])
            self.data = ''.join(rebuilt)
        return self

    def __add__(self, other: 'str | Prompt') -> 'Prompt':
        if isinstance(other, str):
            return Prompt(data=self.data + other, attaches=list(self.attaches))
        if isinstance(other, Prompt):
            return Prompt(data=self.data + other.data, attaches=[*self.attaches, *other.attaches])
        return NotImplemented

    def __radd__(self, other: str) -> 'Prompt':
        if isinstance(other, str):
            return Prompt(data=other + self.data, attaches=list(self.attaches))
        return NotImplemented

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        return {
            'data': self.data,
            'attaches': [_dump_prompt_attach(attach) for attach in self.attaches],
        }

type ChatContentPart = Prompt | LLMContent
type ChatContent = ChatContentPart | Sequence[ChatContentPart]

class ChatMessage(TypedDict):
    '''标准聊天消息结构。'''
    role: ChatRole
    '''消息角色。'''
    content: 'ChatContent'
    '''消息内容，可为单项、Prompt 或多模态序列。'''

type ChatMessageInput = ChatMessage | ChatContentPart

class _ChatCompleteParams(ServiceParamsBase, total=False):
    '''Chat Completion请求参数集合。'''
    timeout: _AnnotateDefault[float | None, _DEFAULT_COMPLETION_TIMEOUT]
    '''请求超时（秒）。默认 180 秒。'''
    messages: Required[Sequence[ChatMessageInput]]
    '''消息序列。'''
    temperature: NotRequired[float | None]
    '''采样温度（通常 0–2）。值越低输出越确定：0.0–0.4 适合代码生成、信息提取、摘要等精准任务；
    0.5–0.8 适合一般对话；0.9–1.5 适合创意写作、头脑风暴等需要多样性的场景。
    通常只需调节 temperature 或 top_p 之一，避免同时大幅修改两者。'''
    top_p: NotRequired[float | None]
    '''Nucleus sampling 截断概率（0–1）。每步采样时只保留累积概率前 top_p 的候选 token。
    较低值（0.1–0.3）使输出更保守稳定；较高值（0.9–1.0）允许更多多样性。
    若已通过 temperature 控制随机性，top_p 可保留默认值（约 0.9–1.0），避免双重限制。'''
    top_k: NotRequired[int | None]
    '''Top-K 采样（每步仅从概率最高的 k 个 token 中选取）。k=1 等价于贪心搜索（确定性最强），
    k 越大多样性越强。通常与 temperature/top_p 组合；40–100 是大多数对话场景的合理范围。'''
    max_tokens: NotRequired[int | None]
    '''最大输出 token 数。控制单次响应最多生成多少 token。未设置时模型会尽量生成完整响应。
    长文档生成建议显式设置上限，避免超时或费用超出预期。'''
    presence_penalty: NotRequired[float | None]
    '''存在惩罚（通常 -2–2）。对已生成内容中出现过的 token 施加固定惩罚，降低其再次被选中的概率。
    正值（0.1–1.0）鼓励模型讨论新主题，减少话题重复；负值鼓励聚焦同一主题持续展开。
    适用场景：创意生成或长文多样性要求高时，可设为 0.5–1.0。'''
    frequency_penalty: NotRequired[float | None]
    '''频率惩罚（通常 -2–2）。按 token 在已生成内容中的出现**次数**比例降低其被选中概率。
    正值（0.1–1.0）有效抑制逐字重复；负值允许反复使用同一词语（罕见场景）。
    与 presence_penalty 的区别：frequency_penalty 随重复次数累积，presence_penalty 是固定惩罚。
    若输出出现大量重复短语，设为 0.3–0.7 通常有效。'''
    seed: NotRequired[int | None]
    '''随机种子。固定后在完全相同的输入与参数下可复现相同输出（并非所有模型/服务均支持）。
    适用于调试、A/B 测试或要求输出可复现的生产场景。'''
    stop: NotRequired[str | Sequence[str] | None]
    '''停止词或停止词序列（最多通常支持 4 个）。模型生成到这些字符串时立即终止。
    例如解析代码块时可设置 stop=["```"] 来防止模型溢出格式边界。'''
    json_schema: NotRequired[dict[str, Any] | None]
    '''期望输出遵循的 JSON Schema。提供后会在 prompt 末尾自动注入 schema 约束指令，
    强制模型返回合法的结构化 JSON。适用于 json_complete 等方法；若直接调用 complete，需自行从输出中解析 JSON。'''
    reasoning: _AnnotateDefault[bool | None, False]
    '''是否启用推理内容（chain-of-thought / thinking）。True 时，支持 thinking 的模型会先输出内部推理过程再给出最终答案。
    可显著提升复杂推理、数学证明、代码调试等任务的准确性，但会增加 token 消耗与延迟。
    默认 ``False``；若未显式提供，会由 ``_apply_service_param_defaults`` 自动填入 ``False``。'''
    full_output: NotRequired[bool]
    '''是否返回 ``ChatCompletionOutput`` 完整输出（含 token 用量与 thinking 内容）。
    默认 ``False``，仅返回文本字符串；设为 ``True`` 时返回 ``ChatCompletionOutput``。'''

if TYPE_CHECKING:
    class ChatCompleteParams(_ChatCompleteParams, extra_items=Any): ...
else:
    ChatCompleteParams = _ChatCompleteParams

class CompletionServiceInitParams(ServiceInitParams, total=False):
    '''CompletionService 初始化参数。'''
    ...

class CompletionClientInitParams(ServiceClientInitParams, total=False):
    '''Chat Completion客户端初始化参数。'''
    max_tokens: int | None
    '''客户端可接受的最大输入 token 估算值；``None`` 表示不限制。'''
    token_counter: Callable[[TokenCountable], int] | None
    '''自定义 token 估算器；提供时优先于默认启发式估算。'''
    max_images: int | None
    '''可直接处理的最大图片数；`None` 表示不限制。'''
    max_audios: int | None
    '''可直接处理的最大音频数；`None` 表示不限制。'''
    max_videos: int | None
    '''可直接处理的最大视频数；`None` 表示不限制。'''

class ChatCompleteOptionalParams(ServiceParamsBase, total=False):
    '''Chat Completion可选参数。含义与 ChatCompleteParams 中同名字段完全一致，此处省略详细说明，请参见 ChatCompleteParams。'''
    timeout: _AnnotateDefault[float | None, _DEFAULT_COMPLETION_TIMEOUT]
    '''请求超时（秒）。默认 180 秒。'''
    messages: Sequence[ChatMessageInput]
    '''消息序列。'''
    temperature: float | None
    '''采样温度（0–2）：低值确定性强，高值随机多样；精准任务建议 0–0.4，创意场景 0.9–1.5。'''
    top_p: float | None
    '''Nucleus sampling 概率截断（0–1）：只保留累积概率前 top_p 的候选 token，建议与 temperature 二选一使用。'''
    top_k: int | None
    '''每步从概率最高的 k 个 token 中采样；k=1 为贪心，较大值增加多样性。'''
    max_tokens: int | None
    '''最大输出 token 数；未设置时模型自行决定响应长度。'''
    presence_penalty: float | None
    '''存在惩罚（-2–2）：正值鼓励讨论新主题，减少话题重复。'''
    frequency_penalty: float | None
    '''频率惩罚（-2–2）：正值按重复次数抑制逐字重复，与 presence_penalty 有所区别。'''
    seed: int | None
    '''随机种子：固定后可复现输出（支持程度因模型而异）。'''
    stop: str | Sequence[str] | None
    '''停止词：生成到这些字符串时立即终止。'''
    json_schema: dict[str, Any] | None
    '''期望输出遵循的 JSON Schema；会自动注入到 prompt 约束指令中。'''
    reasoning: _AnnotateDefault[bool | None, False]
    '''是否启用链式推理（thinking）；默认 ``False``。'''

class JsonCompleteRequiredMessagesParams(ChatCompleteOptionalParams):
    '''json_complete 在未提供 prompt 时使用的参数集合。'''
    messages: Required[Sequence[ChatMessageInput]]
    '''消息序列；未提供 prompt 时必须显式传入。'''

class ThinkThinkSynCompletionClientCreateParams(CompletionClientInitParams, total=False):
    '''ThinkThinkSyn completion 客户端创建参数。'''
    apikey: str | None
    '''显式指定的 ThinkThinkSyn API Key。'''
    base_url: str | None
    '''显式指定的 ThinkThinkSyn 接口根地址；为 None 时回落到环境变量 / 本地探测。'''
    model_filter: str | None
    '''模型过滤表达式。'''

class OpenAILikedCompletionClientCreateParams(CompletionClientInitParams, total=False):
    '''OpenAI-liked completion 客户端创建参数。'''
    apikey: str | None
    '''显式指定的 OpenAI 兼容 API Key。'''
    base_url: str | None
    '''OpenAI 兼容接口根地址。'''
    model: str | None
    '''默认模型名。'''

class OpenRouterCompletionClientCreateParams(CompletionClientInitParams, total=False):
    '''OpenRouter completion 客户端创建参数。'''
    apikey: str | None
    '''显式指定的 OpenRouter API Key。'''
    base_url: str | None
    '''显式指定的 OpenRouter 兼容接口根地址；为 None 时使用默认 https://openrouter.ai/api/v1。'''
    model: str | None
    '''默认模型名。'''

__all__ += [
    'ChatRole',
    'LLMContent',
    'ChatContentPart',
    'ChatContent',
    'MEDIA_TAG',
    'Prompt',
    'ChatMessage',
    'ChatMessageInput',
    'ChatCompleteParams',
    'CompletionStreamChunk',
    'CompletionServiceInitParams',
    'CompletionClientInitParams',
    'ChatCompleteOptionalParams',
    'ChatCompletionOutput',
    'ThinkThinkSynCompletionClientCreateParams',
    'OpenAILikedCompletionClientCreateParams',
    'OpenRouterCompletionClientCreateParams',
]


def _extract_token_usage(value: object) -> dict[str, int | None] | None:
    '''从响应对象中提取 token 使用量。'''
    if value is None:
        return None

    model_dump_func = getattr(value, 'model_dump', None)
    if callable(model_dump_func):
        try:
            return _extract_token_usage(model_dump_func())
        except Exception:
            return None

    if hasattr(value, '__dict__'):
        return _extract_token_usage(vars(value))

    if not isinstance(value, dict):
        return None

    usage_raw = value.get('usage', value)
    if not isinstance(usage_raw, dict):
        return None

    prompt_tokens = usage_raw.get('prompt_tokens')
    completion_tokens = usage_raw.get('completion_tokens')
    total_tokens = usage_raw.get('total_tokens')
    completion_details = usage_raw.get('completion_tokens_details')
    reasoning_tokens = completion_details.get('reasoning_tokens') if isinstance(completion_details, dict) else None

    if not any(isinstance(v, (int, float)) for v in (prompt_tokens, completion_tokens, total_tokens, reasoning_tokens)):
        return None

    return {
        'input_tokens': int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else None,
        'output_tokens': int(completion_tokens) if isinstance(completion_tokens, (int, float)) else None,
        'total_tokens': int(total_tokens) if isinstance(total_tokens, (int, float)) else None,
        'reasoning_tokens': int(reasoning_tokens) if isinstance(reasoning_tokens, (int, float)) else None,
    }

def _extract_thinking_from_openai_liked_response(value: object) -> str | None:
    '''从 OpenAI 类响应中提取 reasoning/thinking 内容。'''
    if value is None:
        return None

    model_dump_func = getattr(value, 'model_dump', None)
    if callable(model_dump_func):
        try:
            return _extract_thinking_from_openai_liked_response(model_dump_func())
        except Exception:
            return None

    if hasattr(value, '__dict__') and not isinstance(value, dict):
        return _extract_thinking_from_openai_liked_response(vars(value))

    if not isinstance(value, dict):
        return None

    if 'choices' in value and isinstance(value['choices'], list) and value['choices']:
        return _extract_thinking_from_openai_liked_response(value['choices'][0])

    for key in ('message', 'delta'):
        if key in value and isinstance(value[key], dict):
            msg = value[key]
            for tkey in ('reasoning_content', 'reasoning', 'think', 'thinking'):
                thinking = msg.get(tkey)
                if isinstance(thinking, str) and thinking:
                    return thinking
            return None

    for tkey in ('reasoning_content', 'reasoning', 'think', 'thinking'):
        thinking = value.get(tkey)
        if isinstance(thinking, str) and thinking:
            return thinking

    return None

def _prompt_to_content_parts(prompt: Prompt) -> list[LLMContent]:
    parts: list[LLMContent] = []
    text_parts = prompt.data.split(MEDIA_TAG)
    attach_count = len(prompt.attaches)

    for index, text in enumerate(text_parts):
        if text != '':
            parts.append(text)
        if index < attach_count:
            parts.append(prompt.attaches[index])

    if attach_count > len(text_parts) - 1:
        parts.extend(prompt.attaches[len(text_parts) - 1:])
    return parts

def _format_prompt_template(template: str | Prompt, /, **kwargs: Any) -> str | Prompt:
    if isinstance(template, Prompt):
        return Prompt(data=template.data.format(**kwargs), attaches=list(template.attaches))
    return template.format(**kwargs)

def _as_list(value: ChatContent) -> list[LLMContent]:
    if isinstance(value, Prompt):
        return _prompt_to_content_parts(value)
    if _is_runtime_llm_content(value):
        return [cast(LLMContent, value)]

    sequence_value = cast(Sequence[ChatContentPart], value)
    parts: list[LLMContent] = []
    for item in sequence_value:
        if isinstance(item, Prompt):
            parts.extend(_prompt_to_content_parts(item))
        else:
            parts.append(cast(LLMContent, item))
    return parts

def _is_single_chat_content(value: object) -> bool:
    return isinstance(value, Prompt) or _is_runtime_llm_content(value)


async def _expand_llm_output_items(
    value: object,
    *,
    document_mode: Literal['mixed', 'image'] = 'mixed',
) -> list[str | Image | Audio | Video]:
    if isinstance(value, (str, Image, Audio, Video, LLMDocumentMixin)):
        items: list[object] = [value]
    elif isinstance(value, Sequence):
        items = list(value)
    else:
        raise TypeError(f'Unsupported LLM output type: {type(value).__name__}')

    expanded: list[str | Image | Audio | Video] = []
    for item in items:
        if isinstance(item, (str, Image, Audio, Video)):
            expanded.append(item)
        elif isinstance(item, LLMDocumentMixin):
            expanded.extend(await _expand_llm_part(cast(LLMContent, item), document_mode=document_mode))
        else:
            raise TypeError(f'Unsupported expanded LLM content type: {type(item).__name__}')
    return expanded

async def _expand_llm_part(
    part: ChatContentPart,
    *,
    document_mode: Literal['mixed', 'image'] = 'mixed',
) -> list[str | Image | Audio | Video]:
    if isinstance(part, Prompt):
        expanded_prompt: list[str | Image | Audio | Video] = []
        for nested in _prompt_to_content_parts(part):
            expanded_prompt.extend(await _expand_llm_part(nested, document_mode=document_mode))
        return expanded_prompt
    if isinstance(part, (str, Image, Audio, Video)):
        return [part]
    if isinstance(part, _UnknownLLMContent):
        return await _expand_llm_output_items(part.to_llm(), document_mode=document_mode)
    if isinstance(part, LLMDocumentMixin):
        try:
            expanded = part.to_llm(mode=document_mode)
        except TypeError:
            expanded = part.to_llm()
        if inspect.isawaitable(expanded):
            expanded = await expanded
        return await _expand_llm_output_items(expanded, document_mode=document_mode)
    if isinstance(part, _LLMContentProtocol):
        expanded = part.to_llm()
        if inspect.isawaitable(expanded):
            expanded = await expanded
        return await _expand_llm_output_items(expanded, document_mode=document_mode)
    raise TypeError(f'Unsupported message content type: {type(part).__name__}')

def _llm_expand_cache_keys(part: LLMDocumentMixin, document_mode: str) -> list[str]:
    '''Build multiple cache lookup keys for a document part.'''
    keys = [f'_llm_expand_{id(part)}_{document_mode}']
    try:
        if hasattr(part, 'to_md5_hash'):
            keys.append(f'_llm_expand_md5_{part.to_md5_hash()}_{document_mode}')  # type: ignore[attr-defined]
        elif hasattr(part, 'to_bytes'):
            _raw = part.to_bytes()  # type: ignore[attr-defined]
            if isinstance(_raw, bytes):
                keys.append(f'_llm_expand_md5_{hashlib.md5(_raw).hexdigest()}_{document_mode}')
    except Exception:
        pass
    return keys


async def _expand_llm_content(
    content: ChatContent,
    *,
    document_mode: Literal['mixed', 'image'] = 'mixed',
) -> list[str | Image | Audio | Video]:
    ctx = get_inference_context()
    expanded: list[str | Image | Audio | Video] = []
    for part in _as_list(content):
        if isinstance(part, LLMDocumentMixin) and ctx is not None:
            cache_keys = _llm_expand_cache_keys(part, document_mode)
            # Try all keys in order
            cached_result: list[str | Image | Audio | Video] | None = None
            hit_key: str | None = None
            for ck in cache_keys:
                if ctx.cache_has(ck):
                    cached_result = ctx.cache_get(ck)
                    hit_key = ck
                    break
            if cached_result is not None:
                # Back-fill any missing keys for faster future lookups
                for ck in cache_keys:
                    if not ctx.cache_has(ck):
                        ctx.cache_set(ck, cached_result)
                expanded.extend(cached_result)
                continue
            result = await _expand_llm_part(part, document_mode=document_mode)
            for ck in cache_keys:
                ctx.cache_set(ck, result)
            expanded.extend(result)
        else:
            expanded.extend(await _expand_llm_part(part, document_mode=document_mode))
    return expanded

async def _normalize_msg_content_for_thinkthinksyn(content: ChatContent) -> tuple[str, dict[int, dict[str, Any]] | None]:
    '''将消息内容转换为 ThinkThinkSyn 兼容格式。'''
    parts = await _expand_llm_content(content)
    text_parts: list[str] = []
    medias: dict[int, dict[str, Any]] = {}
    media_idx = 0

    for part in parts:
        if isinstance(part, str):
            text_parts.append(part)
            continue

        media_items: list[Image | Audio | Video] = []
        if isinstance(part, (Image, Audio, Video)):
            media_items.append(part)
        else:
            raise TypeError(f'Unsupported message content type: {type(part).__name__}')

        for media in media_items:
            text_parts.append(f'<__MEDIA_{media_idx}__>')
            media_content = media.to_base64(url_scheme=True)
            media_type = type(media).__name__.lower()
            if isinstance(media, Image):
                media_type = 'image'
            elif isinstance(media, Audio):
                media_type = 'audio'
            elif isinstance(media, Video):
                media_type = 'video'
            medias[media_idx] = {
                'type': media_type,
                'content': media_content,
            }
            media_idx += 1

    final_text = ''.join(text_parts)
    return final_text, medias if medias else None

async def _normalize_msgs_for_thinkthinksyn(messages: Sequence[ChatMessageInput]) -> list[dict[str, Any]]:
    '''规范化消息到 ThinkThinkSyn 请求结构，并合并连续同角色消息。'''
    normalized: list[dict[str, Any]] = []

    def _append_or_merge(role: ChatRole, text: str, medias: dict[int, dict[str, Any]] | None) -> None:
        role_s = str(role)
        if not normalized or str(normalized[-1].get('role', 'user')) != role_s:
            payload: dict[str, Any] = {'role': role_s, 'content': text}
            if medias:
                payload['medias'] = medias.copy()
            normalized.append(payload)
            return

        last = normalized[-1]
        last_text = str(last.get('content', ''))
        last_medias = cast(dict[int, dict[str, Any]], last.get('medias', {}))
        media_offset = len(last_medias)

        remapped_text = text
        remapped_medias: dict[int, dict[str, Any]] = {}
        if medias:
            for old_index in sorted(medias.keys()):
                new_index = media_offset + old_index
                remapped_text = remapped_text.replace(f'<__MEDIA_{old_index}__>', f'<__MEDIA_{new_index}__>')
                remapped_medias[new_index] = medias[old_index]

        last['content'] = last_text + remapped_text
        if remapped_medias:
            merged_medias = last_medias.copy()
            merged_medias.update(remapped_medias)
            last['medias'] = merged_medias

    for msg in messages:
        role: ChatRole = 'user'
        content: ChatContent
        if isinstance(msg, dict):
            role = cast(ChatRole, msg.get('role', 'user'))
            if 'content' not in msg:
                raise ValueError('Each message dict must include `content`.')
            content = cast(ChatContent, msg['content'])
        else:
            content = msg

        text, medias = await _normalize_msg_content_for_thinkthinksyn(content)
        _append_or_merge(role, text, medias)

    return normalized

def _to_openai_audio_part(audio: Audio) -> dict[str, Any]:
    '''将 Audio 转换为 OpenAI 输入片段。'''
    b64 = audio.to_base64()
    fmt = 'wav'
    if isinstance(b64, str) and b64.startswith('data:audio/') and ';base64,' in b64[:64]:
        meta, payload = b64.split(',', 1)
        b64 = payload
        try:
            fmt = meta.split('data:audio/', 1)[1].split(';', 1)[0]
        except Exception:
            fmt = 'wav'
    return {
        'type': 'input_audio',
        'input_audio': {
            'data': b64,
            'format': fmt,
        },
    }

def _to_openai_image_part(image: Image) -> dict[str, Any]:
    '''将 Image 转换为 OpenAI 图像片段。'''
    url = image.to_base64(url_scheme=True)
    return {
        'type': 'image_url',
        'image_url': {'url': url},
    }

async def _to_openai_content(content: ChatContent) -> str | list[dict[str, Any]]:
    '''将通用内容转换为 OpenAI content 结构。'''
    parts = await _expand_llm_content(content)
    if len(parts) == 1 and isinstance(parts[0], str):
        return parts[0]

    out: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, str):
            out.append({'type': 'text', 'text': part})
            continue
        if isinstance(part, Image):
            out.append(_to_openai_image_part(part))
            continue
        if isinstance(part, Audio):
            out.append(_to_openai_audio_part(part))
            continue
        if isinstance(part, Video):
            url = part.to_base64(url_scheme=True)
            out.append({'type': 'video_url', 'video_url': {'url': url}})
            continue
        raise TypeError(f'Unsupported content type for OpenAI-liked payload: {type(part).__name__}')

    return out

async def _to_openai_messages(messages: Sequence[ChatMessageInput]) -> list[dict[str, Any]]:
    '''将消息序列转换为 OpenAI 请求消息，并合并连续同角色消息。'''
    out: list[dict[str, Any]] = []

    async def _as_openai_part_array(content_value: ChatContent) -> list[dict[str, Any]]:
        converted = await _to_openai_content(content_value)
        if isinstance(converted, str):
            return [{'type': 'text', 'text': converted}]
        return list(converted)

    for msg in messages:
        role = 'user'
        content: ChatContent
        if isinstance(msg, dict):
            role = str(msg.get('role', 'user'))
            if 'content' not in msg:
                raise ValueError('Each message dict must include `content`.')
            content = cast(ChatContent, msg['content'])
        else:
            content = msg

        content_array = await _as_openai_part_array(content)
        if out and str(out[-1].get('role', 'user')) == role:
            last_content = out[-1].get('content')
            if isinstance(last_content, str):
                last_parts: list[dict[str, Any]] = [{'type': 'text', 'text': last_content}]
            elif isinstance(last_content, list):
                last_parts = cast(list[dict[str, Any]], last_content)
            else:
                last_parts = []
            out[-1]['content'] = [*last_parts, *content_array]
        else:
            out.append({'role': role, 'content': content_array})
    return out

def _serialize_chat_part_for_log(part: LLMContent) -> object:
    if isinstance(part, str):
        return _truncate_text(part, 1200)
    payload = _sanitize_for_log(part)
    if isinstance(payload, dict) and payload.keys() == {'__type__', '__repr__'}:
        return {'type': type(part).__name__}
    return payload

def _serialize_chat_content_for_log(content: ChatContent) -> object:
    parts = _as_list(content)
    if len(parts) == 1 and isinstance(parts[0], str):
        return _truncate_text(cast(str, parts[0]), 1200)
    return [_serialize_chat_part_for_log(part) for part in parts]

def _serialize_chat_message_for_log(message: ChatMessageInput) -> dict[str, object]:
    if isinstance(message, dict):
        payload: dict[str, object] = {'role': str(message.get('role', 'user'))}
        if 'content' in message:
            payload['content'] = _serialize_chat_content_for_log(cast(ChatContent, message['content']))
        return payload
    return {
        'role': 'user',
        'content': _serialize_chat_content_for_log(message),
    }

def _serialize_completion_request_payload(kwargs: dict[str, object]) -> dict[str, object]:
    payload = kwargs.copy()
    messages = payload.get('messages')
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes, bytearray)):
        payload['messages'] = [_serialize_chat_message_for_log(cast(ChatMessageInput, message)) for message in messages]
    return payload

def _extract_text_from_openai_liked_response(value: object) -> str:
    '''从任意嵌套响应对象中尽力提取文本。'''
    if value is None:
        return ''
    model_dump_func = getattr(value, 'model_dump', None)
    if callable(model_dump_func):
        try:
            return _extract_text_from_openai_liked_response(model_dump_func())
        except Exception:
            pass
    if hasattr(value, '__dict__'):
        return _extract_text_from_openai_liked_response(vars(value))
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ''.join(_extract_text_from_openai_liked_response(v) for v in value)
    if isinstance(value, dict):
        if 'choices' in value and isinstance(value['choices'], list):
            return ''.join(_extract_text_from_openai_liked_response(choice) for choice in value['choices'])
        for key in ('message', 'delta', 'content', 'text', 'data', 'output_text', 'response'):
            if key in value:
                return _extract_text_from_openai_liked_response(value[key])
    return str(value)

def _extract_openai_liked_stream_chunk(chunk: object)-> CompletionStreamChunk | None:
    '''解析流式分片为统一结构。'''
    data_obj = chunk
    model_dump_func = getattr(chunk, 'model_dump', None)
    if callable(model_dump_func):
        try:
            data_obj = model_dump_func()
        except Exception:
            data_obj = chunk
    elif hasattr(chunk, '__dict__'):
        data_obj = vars(chunk)

    if isinstance(data_obj, dict) and 'choices' in data_obj and isinstance(data_obj['choices'], list) and data_obj['choices']:
        data_obj = data_obj['choices'][0]
    
    if isinstance(data_obj, dict):
        for key in ('reasoning_content', 'reasoning', 'think', 'thinking'):
            text = _extract_text_from_openai_liked_response(data_obj.get(key))
            if text:
                return {'data': text, 'type': 'think'}

        for key in ('delta', 'message', 'content', 'text', 'data'):
            data = data_obj.get(key)
            if isinstance(data, dict):
                for key in ('reasoning', 'think', 'thinking', 'reasoning_content'):
                    if (maybe_think:=data.get(key)) is not None:
                        if isinstance(maybe_think, str):
                            return {'data': maybe_think, 'type': 'think'}
                        
            text = _extract_text_from_openai_liked_response(data)
            if text:
                return {'data': text, 'type': 'text'}

    text = _extract_text_from_openai_liked_response(data_obj)
    if text:
        return {'data': text, 'type': 'text'}
    return None

def _is_basemodel_v2(return_type: type[object], type_origin: object) -> bool:
    try:
        return issubclass(return_type, BaseModel) and (type_origin not in (Union, UnionType))
    except TypeError:
        return False

def _is_basemodel_v1(return_type: type[object], type_origin: object) -> bool:
    try:
        return issubclass(return_type, BaseModelV1) and (type_origin not in (Union, UnionType))
    except TypeError:
        return False

def _validate_to_type(value: object, target_type: type[object]) -> object:
    '''将值校验并转换为目标类型。'''
    try:
        if issubclass(target_type, BaseModel):
            return target_type.model_validate(value)
    except TypeError:
        ...
    type_adapter = get_pydantic_type_adapter(target_type)
    return type_adapter.validate_python(value)

def _enforce_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    '''递归为所有 object 节点添加 ``additionalProperties: false`` 并确保 ``required`` 包含所有属性，
    以满足 OpenAI / OpenRouter structured output strict 模式要求。'''
    if not isinstance(schema, dict):
        return schema

    schema = dict(schema)  # shallow copy

    # Handle $defs / definitions
    for defs_key in ('$defs', 'definitions'):
        if defs_key in schema and isinstance(schema[defs_key], dict):
            schema[defs_key] = {
                k: _enforce_strict_json_schema(v)
                for k, v in schema[defs_key].items()
            }

    if schema.get('type') == 'object' and 'properties' in schema:
        schema['additionalProperties'] = False
        props = schema['properties']
        if isinstance(props, dict):
            existing_required = set(schema.get('required') or [])
            schema['required'] = sorted(existing_required | set(props.keys()))
            schema['properties'] = {
                k: _enforce_strict_json_schema(v) for k, v in props.items()
            }

    if schema.get('type') == 'array' and 'items' in schema:
        schema['items'] = _enforce_strict_json_schema(schema['items'])

    for key in ('anyOf', 'oneOf', 'allOf'):
        if key in schema and isinstance(schema[key], list):
            schema[key] = [_enforce_strict_json_schema(item) for item in schema[key]]

    return schema

def _json_schema_of_type(target_type: type[object]) -> dict[str, Any]:
    '''获取目标类型对应 JSON Schema，并为 strict structured output 添加必要约束。'''
    try:
        if issubclass(target_type, BaseModel):
            raw = cast(dict[str, Any], target_type.model_json_schema())
            return _enforce_strict_json_schema(raw)
    except TypeError:
        ...
    type_adapter = get_pydantic_type_adapter(target_type)
    schema = type_adapter.json_schema()
    if not isinstance(schema, dict):
        return {'type': 'object', 'additionalProperties': False}
    return _enforce_strict_json_schema(cast(dict[str, Any], schema))

def _json_schema_response_name(schema: dict[str, Any], default: str = 'response') -> str:
    '''Derive a stable OpenAI json_schema.name from schema metadata.''' 
    candidates = [schema.get('title'), schema.get('$id'), schema.get('id')]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        name = candidate.strip()
        if not name:
            continue
        name = name.rsplit('/', 1)[-1]
        name = name.split('#', 1)[0]
        name = re.sub(r'\.json$', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[^0-9A-Za-z_-]+', '_', name).strip('_')
        if not name:
            continue
        if name[0].isdigit():
            name = f'{default}_{name}'
        return name
    return default

def _to_json_example_dumpable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, BaseModelV1):
        return value.dict()
    if isinstance(value, dict):
        return {k: _to_json_example_dumpable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_example_dumpable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_json_example_dumpable(v) for v in value]
    return value


def _try_dump_default_json_example(target_type: type[object]) -> str | None:
    try:
        default_value = create_type_default_instance(target_type)
    except Exception:
        return None

    try:
        dumpable = _to_json_example_dumpable(default_value)
        return json.dumps(dumpable, ensure_ascii=False)
    except Exception:
        return None


def _append_schema_instruction(
    messages: Sequence[ChatMessageInput],
    schema: dict[str, Any],
    *,
    reasoning: bool = False,
    default_json_example: str | None = None,
) -> list[ChatMessageInput]:
    '''在最后一条消息后附加 schema 约束提示。'''
    if not messages:
        return list(messages)

    schema_json = json.dumps(schema, ensure_ascii=False)
    if not reasoning:
        schema_note = (
            '\n\nNOTE: Your response should follows the json schema below:'
            f'\n```\n{schema_json}\n```'
            '\nReturn the valid json response only, without any other text.'
            ' The json response should have no indentation, meaning no newline characters and whitespace.'
        )
    else:
        schema_note = (
            '\n\nNOTE: First think carefully about the answer before responding.'
            '\nThen return your final answer using the JSON format described below,'
            ' wrapped inside a ```json fenced block.'
            f'\n```\n{schema_json}\n```'
        )
        if default_json_example:
            schema_note += (
                '\nA default example of the expected JSON shape is:'
                f'\n```json\n{default_json_example}\n```'
            )
        schema_note += (
            '\nYour final answer must be a single ```json fenced block containing the final JSON only.'
        )

    patched = list(messages)
    last = patched[-1]
    if isinstance(last, dict):
        content = last.get('content', '')
        if isinstance(content, str):
            new_last = cast(dict[str, Any], last.copy())
            new_last['content'] = content + schema_note
            patched[-1] = cast(ChatMessageInput, new_last)
        else:
            new_last = cast(dict[str, Any], last.copy())
            new_last['content'] = [*_as_list(cast(ChatContent, content)), schema_note]
            patched[-1] = cast(ChatMessageInput, new_last)
    else:
        if isinstance(last, str):
            patched[-1] = last + schema_note
        else:
            patched[-1] = cast(ChatMessageInput, {'role': 'user', 'content': [*_as_list(last), schema_note]})
    return patched


def _iter_json_response_candidates(text: str) -> list[str]:
    candidates: list[str] = []

    def add_candidate(value: str | None) -> None:
        if not isinstance(value, str):
            return
        cleaned = value.strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    add_candidate(text)
    for pattern in (
        r'```json\s*(.*?)\s*```',
        r'```(?:json)?\s*(.*?)\s*```',
    ):
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            add_candidate(match.group(1))

    for pattern in (
        r'(\{[\s\S]*\})',
        r'(\[[\s\S]*\])',
    ):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            add_candidate(match.group(1))

    return candidates


def _try_parse_json_response_text(text: str) -> Any:
    for candidate in _iter_json_response_candidates(text):
        try:
            return json_repair_loads(candidate)
        except Exception:
            continue
    return text

def _merge_messages_with_user_prompt(
    messages: Sequence[ChatMessageInput] | None,
    prompt: ChatContent | None,
) -> list[ChatMessageInput]:
    '''将 prompt 作为 user 消息并入消息列表；若 messages 已存在，则 prompt 追加为最后一条 user 消息。'''
    merged = list(messages or [])
    if prompt is None:
        return merged
    merged.append({'role': 'user', 'content': prompt})
    return merged

def _resolve_completion_timeout(kwargs: ChatCompleteParams) -> float:
    '''Read pre-filled timeout from kwargs, with fallback for safety.'''
    timeout = kwargs.get('timeout')
    if timeout is None:
        return _DEFAULT_COMPLETION_TIMEOUT
    timeout_value = float(timeout)
    if timeout_value <= 0:
        raise ValueError('timeout must be greater than 0')
    return timeout_value


class CompletionCallableMixin(ServiceCallLogMixin):
    '''补全接口与日志包装的共享实现。'''

    def _clear_latest_token_usage(self) -> None:
        self._latest_token_usage: dict[str, int | None] | None = None

    def _set_latest_token_usage(self, usage: dict[str, int | None] | None) -> None:
        self._latest_token_usage = usage.copy() if isinstance(usage, dict) else None

    def _peek_latest_token_usage(self) -> dict[str, int | None] | None:
        usage = getattr(self, '_latest_token_usage', None)
        return usage.copy() if isinstance(usage, dict) else None

    def _clear_latest_thinking(self) -> None:
        self._latest_thinking: str | None = None

    def _set_latest_thinking(self, thinking: str | None) -> None:
        self._latest_thinking = thinking

    def _peek_latest_thinking(self) -> str | None:
        return getattr(self, '_latest_thinking', None)

    def _log_request_payload(self, operation: str, args: tuple[object, ...], kwargs: dict[str, object]) -> object:
        payload = kwargs.copy()
        payload.pop('__skip_log__', None)
        if operation in {'complete', 'stream_complete'}:
            return _serialize_completion_request_payload(payload)
        return payload

    def _log_response_payload(self, operation: str, result: object) -> object:
        return {
            'text': _extract_text_from_openai_liked_response(result),
            'mode': 'stream' if operation == 'stream_complete' else 'non-stream',
        }

    def _log_extra_metadata(
        self,
        operation: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        result: object = None,
    ) -> dict[str, object] | None:
        if operation not in {'complete', 'stream_complete'}:
            return None

        if result is None:
            return {
                'input_tokens': None,
                'output_tokens': None,
                'total_tokens': None,
                'reasoning_tokens': None,
            }

        usage = self._peek_latest_token_usage()
        if usage is None:
            return {
                'input_tokens': None,
                'output_tokens': None,
                'total_tokens': None,
                'reasoning_tokens': None,
            }

        return cast(dict[str, object], usage)

    @classmethod
    @cache
    def TestingInput(cls) -> ChatCompleteParams:
        return {
            'messages': [{'role': 'user', 'content': '1+1=?'}],
            'max_tokens': 8,
            'reasoning': False,
            'timeout': 8.0,
        }

    @overload
    async def complete(self, *, full_output: Literal[True], stream: bool=False, **kwargs: Unpack[ChatCompleteOptionalParams]) -> ChatCompletionOutput: ...
    @overload
    async def complete(self, stream: bool=False, **kwargs: Unpack[ChatCompleteParams]) -> str: ...

    async def complete(self, stream: bool=False, **kwargs: Any) -> str | ChatCompletionOutput:
        '''
        Complete the chat based on input messages and parameters.
        NOTE: 如果传入`stream=True`, 不代表流式返回, 而是会以流式方式执行并收集结果, 最终返回完整文本或包含思考过程的输出对象。
        这有助于避免因为等待过久而cloudflare超时.
        '''
        
        exec_kwargs = cast(dict[str, object], kwargs.copy())
        full_output = bool(exec_kwargs.pop('full_output', False))
        use_stream = bool(exec_kwargs.pop('stream', False))
        self._clear_latest_token_usage()
        self._clear_latest_thinking()
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, ChatCompleteParams)
        request = self._log_request_payload('complete', (), exec_kwargs.copy())
        metadata = self._log_extra_metadata('complete', (), exec_kwargs.copy())
        if use_stream:
            async def _stream_and_collect() -> str:
                collector = _StreamLogCollector()
                async for chunk in self._stream_complete_impl(**cast(ChatCompleteParams, exec_kwargs)):
                    collector.add(chunk)
                think_text = collector.final_think_text()
                if think_text and not self._peek_latest_thinking():
                    self._set_latest_thinking(think_text)
                return collector.final_text()
            text = cast(
                str,
                await self._trace_async_call(
                    'complete',
                    _stream_and_collect,
                    request=request,
                    metadata=metadata,
                    metadata_builder=lambda result: self._log_extra_metadata('complete', (), exec_kwargs.copy(), result=result),
                    skip_log=skip_log,
                ),
            )
        else:
            text = cast(
                str,
                await self._trace_async_call(
                    'complete',
                    lambda: self._complete_impl(**cast(ChatCompleteParams, exec_kwargs)),
                    request=request,
                    metadata=metadata,
                    metadata_builder=lambda result: self._log_extra_metadata('complete', (), exec_kwargs.copy(), result=result),
                    skip_log=skip_log,
                ),
            )
        if not full_output:
            return text
        usage = self._peek_latest_token_usage()
        return ChatCompletionOutput(
            text=text,
            thinking=self._peek_latest_thinking(),
            input_tokens=usage.get('input_tokens') if usage else None,
            output_tokens=usage.get('output_tokens') if usage else None,
        )

    async def stream_complete(self, **kwargs: Unpack[ChatCompleteParams]) -> AsyncGenerator[CompletionStreamChunk, None]:
        exec_kwargs = cast(dict[str, object], kwargs.copy())
        self._clear_latest_token_usage()
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, ChatCompleteParams)
        request = self._log_request_payload('stream_complete', (), exec_kwargs.copy())
        metadata = self._log_extra_metadata('stream_complete', (), exec_kwargs.copy())
        collector = _StreamLogCollector()
        started_at = time.perf_counter()
        try:
            async for chunk in self._stream_complete_impl(**cast(ChatCompleteParams, exec_kwargs)):
                collector.add(chunk)
                yield chunk
        except Exception as exc:
            if not skip_log:
                failure_metadata = self._log_extra_metadata('stream_complete', (), exec_kwargs.copy(), result=None)
                self._record_call_log(
                    operation='stream_complete',
                    started_at=started_at,
                    success=False,
                    request=request,
                    error=exc,
                    metadata=failure_metadata if failure_metadata is not None else metadata,
                )
            raise

        if not skip_log:
            success_response = collector.as_response(mode='stream')
            success_metadata = self._log_extra_metadata('stream_complete', (), exec_kwargs.copy(), result=success_response)
            self._record_call_log(
                operation='stream_complete',
                started_at=started_at,
                success=True,
                request=request,
                response=success_response,
                metadata=success_metadata if success_metadata is not None else metadata,
            )

    async def _complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> str:
        raise NotImplementedError

    def _stream_complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> AsyncGenerator[CompletionStreamChunk, None]:
        raise NotImplementedError

class CompletionClient(CompletionCallableMixin, ServiceClientBase[ChatCompleteParams]):
    '''补全类客户端抽象基类。'''

    ServiceKind: ClassVar['AIServiceKind'] = 'completion'

    def __init__(self, **kwargs: Unpack[CompletionClientInitParams]):
        super().__init__(
            key=kwargs.get('key'),
            max_concurrent=kwargs.get('max_concurrent'),
            priority=kwargs.get('priority', 0.0),
            strategy_lvl=kwargs.get('strategy_lvl', StrategyLevel.LOAD_BALANCE),
        )
        self.max_tokens = kwargs.get('max_tokens', 32768)
        self.token_counter = kwargs.get('token_counter')
        raw_max_images = kwargs.get('max_images', 0)
        raw_max_audios = kwargs.get('max_audios', 0)
        raw_max_videos = kwargs.get('max_videos', 0)
        self.max_images = None if raw_max_images is None else int(raw_max_images)
        self.max_audios = None if raw_max_audios is None else int(raw_max_audios)
        self.max_videos = None if raw_max_videos is None else int(raw_max_videos)

    def count_tokens(self, value: TokenCountable | ChatMessageInput | Sequence[ChatMessageInput]) -> int:
        if self.token_counter is not None:
            try:
                counted = int(self.token_counter(cast(TokenCountable, value)))
                if counted >= 0:
                    return counted
            except Exception:
                pass
        return estimate_multimodal_tokens(cast(TokenCountable, value))

    async def probe_min_health(self) -> bool:
        try:
            probe = cast(dict[str, object], type(self).TestingInput())
            output = await self.complete(__skip_log__=True, **probe)     # type: ignore[arg-type]
            return bool(str(output).strip())
        except Exception:
            return False

    @staticmethod
    def _extract_common_client_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        '''从工厂参数中提取公共客户端初始化参数（media limits、并发、优先级、策略等级、token 上限、计数器）。'''
        result: dict[str, Any] = {
            'max_images': kwargs.get('max_images', 0),
            'max_audios': kwargs.get('max_audios', 0),
            'max_videos': kwargs.get('max_videos', 0),
            'max_concurrent': kwargs.get('max_concurrent'),
            'priority': kwargs.get('priority', 0.0),
            'strategy_lvl': kwargs.get('strategy_lvl', StrategyLevel.LOAD_BALANCE),
        }
        for key in ('max_tokens', 'token_counter'):
            if key in kwargs:
                result[key] = kwargs[key]
        return result

    @classmethod
    def CreateThinkThinkSynClient(
        cls,
        **kwargs: Unpack[ThinkThinkSynCompletionClientCreateParams],
    ) -> 'CompletionClient':
        model_filter = kwargs.get('model_filter')
        apikey = kwargs.get('apikey')
        key = apikey or _env_first('TTS_APIKEY', 'TTS_API_KEY')
        api_url = kwargs.get('base_url') or _env_first('TTS_API_BASEURL')
        if not api_url:
            api_url = _detect_local_tts_base_url()
        init_params: dict[str, Any] = {}
        if key:
            init_params['apikey'] = key
        if api_url:
            init_params['base_url'] = api_url
        client_kwargs = cls._extract_common_client_kwargs(kwargs)   # type: ignore
        return ThinkThinkSynCompletionClient(
            _create_proxied_thinkthinksyn(**init_params),
            model_filter=model_filter,
            **client_kwargs,
        )

    @classmethod
    def CreateOpenAILikedClient(
        cls,
        **kwargs: Unpack[OpenAILikedCompletionClientCreateParams],
    ) -> 'CompletionClient':
        apikey = kwargs.get('apikey')
        base_url = kwargs.get('base_url')
        model = kwargs.get('model')
        key = apikey or _env_first('OPENAI_APIKEY', 'OPENAI_API_KEY')
        if not key:
            raise ValueError('OpenAI-liked apikey is required.')
        final_base_url = base_url or _env_first('OPENAI_API_URL', 'OPENAI_BASE_URL') or 'https://api.openai.com/v1'
        if not final_base_url:
            raise ValueError('OpenAI-liked base_url is required.')
        client_kwargs = cls._extract_common_client_kwargs(kwargs)   # type: ignore
        return OpenAILikedCompletionClient(
            apikey=key,
            base_url=final_base_url,
            model=model,
            **client_kwargs,
        )

    @classmethod
    def CreateOpenRouterClient(
        cls,
        **kwargs: Unpack[OpenRouterCompletionClientCreateParams],
    ) -> 'CompletionClient':
        apikey = kwargs.get('apikey')
        model = kwargs.get('model')
        key = apikey or _env_first('OPENROUTER_APIKEY', 'OPENROUTER_API_KEY')
        if not key:
            raise ValueError('OpenRouter apikey not provided. Please pass `apikey` or set OPENROUTER_APIKEY / OPENROUTER_API_KEY.')

        base_url = kwargs.get('base_url') or _env_first('OPENROUTER_API_URL') or 'https://openrouter.ai/api/v1'
        final_model = model or _env_first(
            'OPENROUTER_MODEL',
            'OPENROUTER_MODEL_FILTER',
        ) or 'qwen/qwen3.5-122b-a10b'
        final_max_images = kwargs.get('max_images', 0)
        if final_model in {'qwen/qwen3.5-122b-a10b', 'qwen/qwen3.5-27b'} and final_max_images == 8:
            final_max_images = None

        client_kwargs = cls._extract_common_client_kwargs(kwargs)   # type: ignore
        client_kwargs.update({
            'apikey': key,
            'base_url': base_url,
            'model': final_model,
            'max_images': final_max_images,
            'max_audios': kwargs.get('max_audios'),
            'max_videos': kwargs.get('max_videos'),
        })
        return cls.CreateOpenAILikedClient(**client_kwargs)

class ThinkThinkSynCompletionClient(CompletionClient, type='tts-completion'):
    '''ThinkThinkSyn 补全客户端实现。'''

    def __init__(
        self,
        tts_client: 'ThinkThinkSyn',
        model_filter: str | None = None,
        ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None' = None,
        **kwargs: Unpack[CompletionClientInitParams],
    ):
        # Apply preset defaults by model_filter when kwargs are not explicitly provided
        try:
            _defaults_cls = CompletionService.ThinkThinkSynDefaultClientParams
            for _attr in dir(_defaults_cls):
                if _attr.startswith('_'):
                    continue
                _preset = getattr(_defaults_cls, _attr, None)
                if isinstance(_preset, dict) and _preset.get('model_filter') == model_filter:
                    for _pk, _pv in _preset.items():
                        if _pk not in ('model_filter', 'apikey') and _pk not in kwargs:
                            kwargs[_pk] = _pv  # type: ignore
                    break
        except Exception:
            pass
        if 'max_tokens' not in kwargs:
            kwargs['max_tokens'] = 14336 # thinkthinksyn 模型默认14336上下文长度
        super().__init__(**kwargs)
        _ssh = _resolve_ssh_tunnel_config(ssh_tunnel)
        if _ssh:
            _apply_ssh_tunnel_to_tts_client(tts_client, _ssh)
        self._tts_client = _patch_thinkthinksyn_proxy(tts_client)
        self._model_filter = model_filter

    def _tts_url(self) -> str:
        return self._tts_client._ai_url('/completion')

    def _tts_headers(self) -> dict[str, str]:
        if self._tts_client.apikey:
            return {'Authorization': f'Bearer {self._tts_client.apikey}'}
        return {}

    async def _build_payload(self, kwargs: ChatCompleteParams) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        payload['messages'] = await _normalize_msgs_for_thinkthinksyn(kwargs['messages'])

        for key in (
            'temperature',
            'top_p',
            'top_k',
            'max_tokens',
            'presence_penalty',
            'frequency_penalty',
            'seed',
            'stop',
            'json_schema',
        ):
            value = kwargs.get(key)
            if value is not None:
                payload[key] = value

        payload['reasoning'] = bool(kwargs.get('reasoning', False))

        if self._model_filter:
            payload['model_filter'] = self._model_filter
        return payload

    async def _request_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload, 'stream': False}
        session = await self._get_session()
        async with session.post(self._tts_url(), json=payload, headers=self._tts_headers()) as response:
            response.raise_for_status()
            return await response.json()

    async def _request_stream(self, payload: dict[str, Any]) -> AsyncGenerator[dict[str, str], None]:
        payload = {**payload, 'stream': True}
        session = await self._get_session()
        async for event in aiosseclient_with_proxy(
            self._tts_url(), method='post', json=payload, headers=self._tts_headers(), session=session,
        ):
            if data := event.data:
                yield {'event': event.event or 'message', 'data': data}

    async def _complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> str:
        for _attempt in range(2):
            try:
                payload = await self._build_payload(kwargs)
                req_timeout = _resolve_completion_timeout(kwargs)
                output = await asyncio.wait_for(self._request_completion(payload), timeout=req_timeout) if req_timeout else await self._request_completion(payload)
                self._set_latest_token_usage(_extract_token_usage(output))
                self._set_latest_thinking(_extract_thinking_from_openai_liked_response(output))
                return _extract_text_from_openai_liked_response(output)
            except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError):
                if _attempt == 0:
                    continue
                raise
        raise RuntimeError('unreachable')

    async def _stream_complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> AsyncGenerator[CompletionStreamChunk, None]:
        for _attempt in range(2):
            first_token_received = False
            try:
                payload = await self._build_payload(kwargs)
                stream = self._request_stream(payload)
                req_timeout = _resolve_completion_timeout(kwargs)
                deadline = time.monotonic() + req_timeout if req_timeout else None
                allow_thinking = bool(kwargs.get('reasoning', False))

                ttft_deadline = time.monotonic() + self._STREAM_TTFT_TIMEOUT

                stream_iter = stream.__aiter__()
                while True:
                    remaining: float | None = None
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise asyncio.TimeoutError('ThinkThinkSyn stream completion timed out')

                    if not first_token_received:
                        ttft_remaining = ttft_deadline - time.monotonic()
                        if ttft_remaining <= 0:
                            raise asyncio.TimeoutError(f'ThinkThinkSyn stream first token timed out ({self._STREAM_TTFT_TIMEOUT}s)')
                        remaining = min(remaining, ttft_remaining) if remaining is not None else ttft_remaining

                    try:
                        chunk = await asyncio.wait_for(stream_iter.__anext__(), timeout=remaining) if remaining is not None else await stream_iter.__anext__()
                    except StopAsyncIteration:
                        break

                    evt_type = chunk.get('event', 'message') if isinstance(chunk, dict) else 'message'
                    evt_data = chunk.get('data', '') if isinstance(chunk, dict) else str(chunk)
                    if not evt_data:
                        continue
                    # Try extract token usage from JSON events (e.g. final usage event)
                    if evt_type not in ('message', 'think'):
                        try:
                            _parsed_json = json.loads(evt_data) if isinstance(evt_data, str) else evt_data
                            if isinstance(_parsed_json, dict):
                                _chunk_usage = _extract_token_usage(_parsed_json)
                                if _chunk_usage is not None:
                                    self._set_latest_token_usage(_chunk_usage)
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                        continue
                    text_data = evt_data if isinstance(evt_data, str) else str(evt_data)
                    chunk_type: Literal['text', 'think'] = 'think' if evt_type == 'think' else 'text'
                    first_token_received = True
                    if chunk_type == 'think' and not allow_thinking:
                        continue
                    yield CompletionStreamChunk(data=text_data, type=chunk_type)  # type: ignore
                return  # stream completed successfully, exit retry loop
            except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError):
                if _attempt == 0 and not first_token_received:
                    continue
                raise

class OpenAILikedCompletionClient(CompletionClient, type='openai-completion'):
    '''OpenAI 协议兼容的补全客户端实现。'''

    def __init__(
        self,
        apikey: str,
        base_url: str,
        model: str | None = None,
        ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None' = None,
        **kwargs: Unpack[CompletionClientInitParams],
    ):
        resolved_model = model or _env_first('OPENAI_MODEL') or None
        # Apply preset defaults by model name when kwargs are not explicitly provided
        if resolved_model:
            try:
                _defaults_cls = CompletionService.OpenAILikedDefaultClientParams
                for _attr in dir(_defaults_cls):
                    if _attr.startswith('_'):
                        continue
                    _preset = getattr(_defaults_cls, _attr, None)
                    if isinstance(_preset, dict) and _preset.get('model') == resolved_model:
                        for _pk, _pv in _preset.items():
                            if _pk not in ('model', 'apikey', 'base_url') and _pk not in kwargs:
                                kwargs[_pk] = _pv  # type: ignore
                        break
            except Exception:
                pass
        init_kwargs: CompletionClientInitParams = {
            'max_images': 0,
            'max_audios': 0,
            'max_videos': 0,
            **kwargs,
        }
        if 'max_tokens' not in init_kwargs:
            init_kwargs['max_tokens'] = 100 * 1024
        super().__init__(**init_kwargs)
        self._apikey = apikey
        _ssh = _resolve_ssh_tunnel_config(ssh_tunnel)
        self._base_url = (_rewrite_url_for_ssh_tunnel(base_url.rstrip('/'), _ssh) if _ssh else base_url.rstrip('/'))
        self._model = resolved_model

    def _completion_url(self) -> str:
        if self._base_url.endswith('/chat/completions'):
            return self._base_url
        return f'{self._base_url}/chat/completions'

    async def _build_payload(self, kwargs: ChatCompleteParams, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'messages': await _to_openai_messages(kwargs['messages']),
            'stream': stream,
        }
        if self._model:
            payload['model'] = self._model

        for key in (
            'temperature',
            'top_p',
            'max_tokens',
            'presence_penalty',
            'frequency_penalty',
            'seed',
            'stop',
        ):
            value = kwargs.get(key)
            if value is not None:
                payload[key] = value

        json_schema = kwargs.get('json_schema')
        if isinstance(json_schema, dict):
            payload['response_format'] = {
                'type': 'json_schema',
                'json_schema': {
                    'name': _json_schema_response_name(json_schema),
                    'strict': True,
                    'schema': json_schema,
                },
            }
        payload['reasoning'] = {'enabled': bool(kwargs.get('reasoning', False))}

        if stream:
            payload['stream_options'] = {'include_usage': True}

        return payload

    def _headers(self) -> dict[str, str]:
        headers = {
            'Authorization': f'Bearer {self._apikey}',
            'Content-Type': 'application/json',
        }
        referer = _env_first('OPENROUTER_HTTP_REFERER')
        if referer:
            headers['HTTP-Referer'] = referer
        x_title = _env_first('OPENROUTER_X_TITLE')
        if x_title:
            headers['X-Title'] = x_title
        return headers

    async def _complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> str:
        payload = await self._build_payload(kwargs, stream=False)
        req_timeout = _resolve_completion_timeout(kwargs)
        timeout = aiohttp.ClientTimeout(total=req_timeout)

        session = await self._get_session()
        for _attempt in range(2):
            try:
                async with session.post(self._completion_url(), json=payload, headers=self._headers(), timeout=timeout) as response:
                    response.raise_for_status()
                    data = await response.json()
                break
            except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError):
                if _attempt == 0:
                    continue
                raise
        self._set_latest_token_usage(_extract_token_usage(data))
        self._set_latest_thinking(_extract_thinking_from_openai_liked_response(data))
        return _extract_text_from_openai_liked_response(data)

    async def _stream_complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> AsyncGenerator[CompletionStreamChunk, None]:
        payload = await self._build_payload(kwargs, stream=True)
        req_timeout = _resolve_completion_timeout(kwargs)
        timeout = aiohttp.ClientTimeout(total=req_timeout)
        allow_thinking = bool(kwargs.get('reasoning', False))

        session = await self._get_session()
        for _attempt in range(2):
            first_token_received = False
            ttft_deadline = time.monotonic() + self._STREAM_TTFT_TIMEOUT

            try:
                async with session.post(self._completion_url(), json=payload, headers=self._headers(), timeout=timeout) as response:
                    response.raise_for_status()

                    content_iter = response.content.__aiter__()
                    while True:
                        try:
                            if not first_token_received:
                                ttft_remaining = ttft_deadline - time.monotonic()
                                if ttft_remaining <= 0:
                                    raise asyncio.TimeoutError(f'OpenAI-liked stream first token timed out ({self._STREAM_TTFT_TIMEOUT}s)')
                                raw_line = await asyncio.wait_for(content_iter.__anext__(), timeout=ttft_remaining)
                            else:
                                raw_line = await content_iter.__anext__()
                        except StopAsyncIteration:
                            break

                        line = raw_line.decode('utf-8', errors='ignore').strip()
                        if not line or not line.startswith('data:'):
                            continue
                        data = line[5:].strip()
                        if not data or data == '[DONE]':
                            continue
                        try:
                            chunk_obj = json.loads(data)
                        except Exception:
                            continue
                        usage = _extract_token_usage(chunk_obj)
                        if usage is not None:
                            self._set_latest_token_usage(usage)
                        parsed = _extract_openai_liked_stream_chunk(chunk_obj)
                        if parsed and parsed['data']:
                            first_token_received = True
                            if parsed['type'] == 'think' and not allow_thinking:
                                continue
                            yield parsed    # type: ignore
                break  # success — exit retry loop
            except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError):
                if _attempt == 0 and not first_token_received:
                    continue
                raise

class CompletionService(CompletionCallableMixin, ServiceBase):
    '''统一补全服务。'''

    @property
    def max_images(self) -> int | None:
        return self._aggregate_client_limit('max_images')

    @property
    def max_audios(self) -> int | None:
        return self._aggregate_client_limit('max_audios')

    @property
    def max_videos(self) -> int | None:
        return self._aggregate_client_limit('max_videos')

    def _aggregate_client_limit(self, attr_name: Literal['max_images', 'max_audios', 'max_videos']) -> int | None:
        limits = [getattr(client, attr_name) for client in self.clients]
        if any(limit is None for limit in limits):
            return None
        normalized_limits = [int(limit) for limit in limits if isinstance(limit, int)]
        return max(normalized_limits, default=0)

    def _is_multi_ocr_input(self, image: Image | LLMDocumentMixin | Sequence[Image | LLMDocumentMixin]) -> bool:
        return isinstance(image, Sequence) and not isinstance(image, (str, bytes, bytearray, Image, LLMDocumentMixin))

    def _is_multi_asr_input(self, audio: Audio | Video | Sequence[Audio | Video]) -> bool:
        return isinstance(audio, Sequence) and not isinstance(audio, (str, bytes, bytearray, Audio, Video))

    def _build_expected_language_hint(
        self,
        expected_languages: str | Language | Sequence[str | Language] | None,
    ) -> tuple[str, str | None]:
        langs = self._tidy_languages(expected_languages)
        if not langs:
            return '', None

        unique_langs = list(dict.fromkeys(langs))
        labels = [f'{lang.value.origin_name} ({lang.value.code})' for lang in unique_langs]
        if len(unique_langs) == 1:
            hint = (
                f'The audio is probably spoken in {labels[0]}. '
                'Prefer transcribing in that language unless strong evidence indicates otherwise.'
            )
            return hint, unique_langs[0].value.code

        hint = (
            f'The audio is likely spoken in one of: {", ".join(labels)}. '
            'Choose the best-matching one from this list and transcribe accordingly.'
        )
        return hint, None

    def _pop_internal_complete_params(self, payload: dict[str, Any]) -> dict[str, Any]:
        internal: dict[str, Any] = {}
        for key in list(payload.keys()):
            if key.startswith('__') and key.endswith('__'):
                internal[key] = payload.pop(key)
        return internal

    def _internal_media_lang(
        self,
        internal_params: dict[str, Any],
        media_kind: Literal['audio', 'video'],
        media_idx: int,
    ) -> str | None:
        raw_lang = internal_params.get(f'__{media_kind}_{media_idx}_lang__')
        if isinstance(raw_lang, Language):
            return raw_lang.value.code
        if isinstance(raw_lang, str):
            lang = raw_lang.strip()
            if not lang:
                return None
            if lang_enum := Language.Find(lang):
                return lang_enum.value.code
            return lang.lower().replace('_', '-')
        return None

    TRANSLATE_PROMPT_TEMPLATE = 'Translate the following text to {target_language}.'
    TRANSCRIPT_PROMPT = 'Generate structured transcript for the given audio/video.'
    RERANK_PROMPT = (
        'You are a reranker. Score each candidate relevance to the query from 0 to 10. '
        'Only return index and score.'
    )

    class ThinkThinkSynDefaultClientParams:
        '''使用ThinkThinkSyn模型时推荐的默认模型参数配置。'''
        _DEFAULT_IMAGE_POOL: ConcurrentPool = ConcurrentPool('completion:images', 80)
        _DEFAULT_AUDIO_POOL: ConcurrentPool = ConcurrentPool('completion:audios', 80)
        _DEFAULT_VIDEO_POOL: ConcurrentPool = ConcurrentPool(
            'completion:videos', 20,
            _parents=[_DEFAULT_IMAGE_POOL, _DEFAULT_AUDIO_POOL],
        )
        _DEFAULT_POOL: CompletionConcurrentPool = CompletionConcurrentPool(
            'completion', 50,
            max_images=_DEFAULT_IMAGE_POOL,
            max_audios=_DEFAULT_AUDIO_POOL,
            max_videos=_DEFAULT_VIDEO_POOL,
        )
        _OMNI_POOL: CompletionConcurrentPool = _DEFAULT_POOL.create_sub_pool(40)

        BASIC: ThinkThinkSynCompletionClientCreateParams = {
            'model_filter': None,
            'max_tokens': 14336,
            'max_images': 0,
            'max_audios': 0,
            'max_videos': 0,
            'max_concurrent': _DEFAULT_POOL,
        }
        OMNI: ThinkThinkSynCompletionClientCreateParams = {
            'model_filter': "Name == 'Qwen/Qwen3-Omni-30B-A3B-Instruct'",
            'max_tokens': 14336,
            'max_images': 5,
            'max_audios': 4,
            'max_videos': 2,
            'max_concurrent': _OMNI_POOL,
        }

    class OpenAILikedDefaultClientParams:
        '''使用类似Openrouter这样的OpenAI格式接口时推荐的默认模型参数配置。'''
        QWEN_3_5_122B_A10B: OpenAILikedCompletionClientCreateParams = {
            'model': 'qwen/qwen3.5-122b-a10b',
            'max_tokens': 260000,
            'max_images': None,
            'max_videos': None,
        }
        QWEN_3_5_27B: OpenAILikedCompletionClientCreateParams = {
            'model': 'qwen/qwen3.5-27b',
            'max_tokens': 260000,
            'max_images': None,
            'max_videos': None,
        }
        QWEN_3_5_35B_A3B: OpenAILikedCompletionClientCreateParams = {
            'model': 'qwen/qwen3.5-35b-a3b',
            'max_tokens': 260000,
            'max_images': None,
            'max_videos': None,
        }
        GEMMA_4_26B_A4B: OpenAILikedCompletionClientCreateParams = {
            'model': 'google/gemma-4-26b-a4b-it',
            'max_tokens': 260000,
            'max_images': None,
            'max_audios': None,
            'max_videos': None,
        }

    class RerankItem(AdvancedBaseModel):
        index: int
        '''候选项在原始序列中的索引。'''
        score: Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        '''相关性分数（0 最低，10 最高）。'''

    class FullRerankItem(AdvancedBaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        index: int
        '''候选项在原始序列中的索引。'''
        score: float
        '''相关性分数。'''
        candidate: str | LLMContent | list[str | LLMContent]
        '''原始候选内容。'''

    class RerankResult(AdvancedBaseModel):
        items: list['CompletionService.FullRerankItem']
        '''重排后的候选结果列表。'''

    class Transcription(AdvancedBaseModel):
        transcript: list[dict[str, str]]
        '''结构化转写片段列表。'''

    class _ASRResult(AdvancedBaseModel):
        text: str
        '''转写结果文本。'''

    class _OCRResult(AdvancedBaseModel):
        text: str
        '''OCR 识别文本。'''

    class _SummaryResult(AdvancedBaseModel):
        summary: str
        '''摘要文本。'''

    class _DetectedLanguage(AdvancedBaseModel):
        detected: str | None
        '''检测到的语言代码，无法确定时为 None。'''

    class _RerankScoreResult(AdvancedBaseModel):
        items: list['CompletionService.RerankItem']
        '''每个候选项的评分列表。'''

    def __init__(
        self,
        *clients: CompletionClient | ServiceClient[CompletionClient],
        s2t_service: 'S2TService | None' = None,
        **kwargs: Unpack[CompletionServiceInitParams],
    ):
        fail_cooldown = float(kwargs.get('fail_cooldown', 15.0))
        recovery_interval = kwargs.get('recovery_interval')
        if not clients:
            raise ValueError('CompletionService requires at least one CompletionClient.')
        super().__init__(
            *clients,
            fail_cooldown=fail_cooldown,
            recovery_interval=recovery_interval,
            key=kwargs.get('key'),
        )
        self._s2t_service = s2t_service
        self._translate_cache_lock = asyncio.Lock()
        self._translate_cache_client = None  # lazy-init ORM client
        self._ensure_recovery_task()
        self._start_init_probe()

    @classmethod
    def Default(cls) -> Self:
        cls.WaitUntilRuntimeReady()
        if existing := cls.GetInstance('default'):
            return existing

        # ── Config-driven creation ───────────────────────────────────────
        from .config import AIServicesConfig
        cfg = AIServicesConfig.Global()
        if cfg is not None:
            svc = cfg.completion.get_default()
            if svc is not None:
                # Bootstrap extras (e.g. 'advanced') so GetInstance can find them
                for ek in cfg.completion.extras:
                    cfg.completion.get_service(ek)
                return cast(Self, svc)

        # ── Hardcoded fallback ───────────────────────────────────────────
        clients: list[CompletionClient] = []
        try:
            basic_client = CompletionClient.CreateThinkThinkSynClient(
                **cls.ThinkThinkSynDefaultClientParams.BASIC,
            )
            clients.append(basic_client)
        except Exception as exc:
            _logger.warning(f'Failed to create ThinkThinkSyn BASIC client: {exc}')

        try:
            omni_client = CompletionClient.CreateThinkThinkSynClient(
                **cls.ThinkThinkSynDefaultClientParams.OMNI,
            )
            clients.append(omni_client)
        except Exception as exc:
            _logger.warning(f'Failed to create ThinkThinkSyn OMNI client: {exc}')

        or_key = _env_first('OPENROUTER_APIKEY', 'OPENROUTER_API_KEY')
        if or_key:
            try:
                or_client = CompletionClient.CreateOpenRouterClient(
                    apikey=or_key,
                    **cls.OpenAILikedDefaultClientParams.GEMMA_4_26B_A4B,  # type: ignore
                    strategy_lvl=StrategyLevel.ON_RATELIMIT,    # type: ignore
                )   # type: ignore
                clients.append(or_client)
            except Exception as exc:
                _logger.warning(f'Failed to create OpenRouter default client: {exc}')

        if not clients:
            raise RuntimeError(
                'Cannot create default CompletionService: no client could be initialized. '
                'Please ensure thinkthinksyn is installed or set OPENROUTER_APIKEY / OPENROUTER_API_KEY.'
            )
        return cls(*clients, key='default')

    def close(self) -> None:
        try:
            super().close()
        except Exception:
            pass
        # ORM clients are managed by StorageConfig; no explicit close needed.

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _get_translate_cache_client(self):
        '''Lazily initialise the ORM client for translation cache.

        Resolution: named/extra ORM client matching ``'translation_cache'``
        (fuzzy) → global ORM cache client.
        '''
        if self._translate_cache_client is None:
            from core.storage.config import StorageConfig
            cfg = StorageConfig.Global()
            self._translate_cache_client = cfg.orm.get_client('translation_cache', fallback='cache')
        return self._translate_cache_client

    class _TranslationCacheRecord(ORMModel, collection_name='translation_cache'):
        cache_key: str = ORMField(index=True)
        source_text: str
        source_language: str | None = None
        target_language: str
        translated_text: str
        updated_at: float = 0.0
        hit_count: int = 0

    def _extract_msg_content(self, msg: ChatMessageInput) -> ChatContent:
        if isinstance(msg, dict):
            if 'content' not in msg:
                raise ValueError('Each message dict must include `content`.')
            return cast(ChatContent, msg['content'])
        return msg

    async def _iter_media_items(self, content: ChatContent) -> list[LLMContent]:
        media_items: list[LLMContent] = []
        for part in await _expand_llm_content(content):
            if isinstance(part, (Image, Audio, Video)):
                media_items.append(part)
        return media_items

    async def _count_multimodal(self, messages: Sequence[ChatMessageInput]) -> tuple[int, int, int]:
        image_count = 0
        audio_count = 0
        video_count = 0
        for msg in messages:
            content = self._extract_msg_content(msg)
            for media in await self._iter_media_items(content):
                if isinstance(media, Image):
                    image_count += 1
                elif isinstance(media, Audio):
                    audio_count += 1
                elif isinstance(media, Video):
                    video_count += 1
        return image_count, audio_count, video_count

    def _client_multimodal_score(
        self,
        client: CompletionClient,
        image_count: int,
        audio_count: int,
        video_count: int,
    ) -> float:
        score = 0.0
        max_images = client.max_images
        max_audios = client.max_audios
        max_videos = client.max_videos

        if image_count > 0 and (max_images is None or max_images >= image_count):
            score += 2.0
        elif image_count > 0 and isinstance(max_images, int) and max_images > 0:
            score += 0.5

        if audio_count > 0 and (max_audios is None or max_audios >= audio_count):
            score += 2.0
        elif audio_count > 0 and isinstance(max_audios, int) and max_audios > 0:
            score += 0.5

        if video_count > 0 and (max_videos is None or max_videos >= video_count):
            score += 2.0
        elif video_count > 0 and isinstance(max_videos, int) and max_videos > 0:
            score += 0.5
        return score

    async def _media_to_text_with_hint(self, media: Audio | Video, language: str | None = None) -> str:
        ctx = get_inference_context()
        _lang_sfx = f'_{language}' if language else ''
        _cache_keys: list[str] = [f'_s2t_{id(media)}{_lang_sfx}']
        if isinstance(media, Audio):
            try:
                _cache_keys.append(f'_s2t_md5_{media.to_md5_hash("wav")}{_lang_sfx}')
            except Exception:
                pass
            try:
                _cache_keys.append(f'_s2t_dur_{media.start_time:.3f}_{media.end_time:.3f}_{len(media)}{_lang_sfx}')
            except Exception:
                pass
        # Try all cache keys
        if ctx is not None:
            for _ck in _cache_keys:
                if ctx.cache_has(_ck):
                    _cached = ctx.cache_get(_ck)
                    # Back-fill missing keys
                    for _ck2 in _cache_keys:
                        if not ctx.cache_has(_ck2):
                            ctx.cache_set(_ck2, _cached)
                    return _cached

        s2t_svc = self._s2t_service
        if s2t_svc is None:
            from .s2t import S2TService as _S2TService
            # Only use S2TService.Default() when 'completion' is NOT already active in the call
            # chain, to prevent: completion -> s2t(uses completion) -> completion -> ...
            _ctx = get_inference_context()
            if _ctx is None or not _ctx.is_active('completion'):
                try:
                    s2t_svc = _S2TService.Default()
                except Exception:
                    s2t_svc = None
        if s2t_svc is None:
            raise RuntimeError(
                'No s2t_service configured for audio/video fallback adaptation '
                'and cannot create a default S2TService in the current call context.'
            )
        s2t_kwargs: dict[str, Any] = {}
        if language:
            s2t_kwargs['language'] = language
        result = (await s2t_svc.s2t(media, **s2t_kwargs)).strip()

        if ctx is not None:
            for _ck in _cache_keys:
                ctx.cache_set(_ck, result)
        return result

    async def _image_to_text(self, image: Image) -> str:
        try:
            return (await self.ocr(image, stream=False)).strip()
        except Exception:
            return ''

    async def _fit_messages_to_token_limit(
        self,
        messages: Sequence[ChatMessageInput],
        client: CompletionClient,
    ) -> list[ChatMessageInput]:
        if client.max_tokens is None:
            return list(messages)

        normalized: list[dict[str, Any]] = []
        for msg in messages:
            role: ChatRole = 'user'
            content = self._extract_msg_content(msg)
            if isinstance(msg, dict):
                role = cast(ChatRole, msg.get('role', 'user'))
            normalized.append({
                'role': role,
                'content': list(await _expand_llm_content(content)),
            })

        def _current_total() -> int:
            return client.count_tokens(normalized)

        total_tokens = _current_total()
        if total_tokens <= client.max_tokens:
            return [cast(ChatMessageInput, msg) for msg in normalized]

        original_audio_parts = [
            part
            for msg in normalized
            for part in cast(list[str | LLMContent], msg['content'])
            if isinstance(part, Audio)
        ]
        original_video_parts = [
            part
            for msg in normalized
            for part in cast(list[str | LLMContent], msg['content'])
            if isinstance(part, Video)
        ]
        last_audio_part = original_audio_parts[-1] if original_audio_parts else None
        last_video_part = original_video_parts[-1] if original_video_parts else None

        for msg in normalized:
            expanded_parts: list[str | LLMContent] = []
            for part in cast(list[str | LLMContent], msg['content']):
                if isinstance(part, Audio) and part is last_audio_part and client.count_tokens(part) > client.max_tokens:
                    try:
                        segments = split_audio_on_silence(part, target_max_tokens=client.max_tokens)
                    except Exception:
                        segments = [part]
                    segmented_parts = [
                        trim_audio_to_token_budget(seg, client.max_tokens, preserve_tail=False)
                        for seg in segments
                        if client.count_tokens(seg) > 0
                    ]
                    expanded_parts.extend(segmented_parts or [part])
                    continue
                if isinstance(part, Video) and part is last_video_part and client.count_tokens(part) > client.max_tokens:
                    try:
                        segments = split_video_to_token_budget(part, client.max_tokens)
                    except Exception:
                        segments = [part]
                    segmented_parts = [
                        trim_video_to_token_budget(seg, client.max_tokens, preserve_tail=False)
                        for seg in segments
                        if client.count_tokens(seg) > 0
                    ]
                    expanded_parts.extend(segmented_parts or [part])
                    continue
                expanded_parts.append(part)
            msg['content'] = expanded_parts

        total_tokens = _current_total()
        if total_tokens <= client.max_tokens:
            return [cast(ChatMessageInput, msg) for msg in normalized]

        image_refs: list[tuple[int, int]] = []
        audio_refs: list[tuple[int, int]] = []
        video_refs: list[tuple[int, int]] = []
        for msg_idx, msg in enumerate(normalized):
            for part_idx, part in enumerate(cast(list[str | LLMContent], msg['content'])):
                if isinstance(part, Image):
                    image_refs.append((msg_idx, part_idx))
                elif isinstance(part, Audio):
                    audio_refs.append((msg_idx, part_idx))
                elif isinstance(part, Video):
                    video_refs.append((msg_idx, part_idx))

        for msg_idx, part_idx in image_refs:
            if total_tokens <= client.max_tokens:
                break
            part = cast(list[str | LLMContent], normalized[msg_idx]['content'])[part_idx]
            if not isinstance(part, Image):
                continue
            current_tokens = client.count_tokens(part)
            if current_tokens <= 256:
                continue
            overflow = total_tokens - client.max_tokens
            target_tokens = max(256, current_tokens - overflow)
            cast(list[str | LLMContent], normalized[msg_idx]['content'])[part_idx] = compress_image_to_token_budget(part, target_tokens)
            total_tokens = _current_total()

        for refs, kind in ((audio_refs, 'audio'), (video_refs, 'video')):
            for order, (msg_idx, part_idx) in enumerate(refs):
                if total_tokens <= client.max_tokens:
                    break
                if order >= len(refs) - 1:
                    break
                part = cast(list[str | LLMContent], normalized[msg_idx]['content'])[part_idx]
                if kind == 'audio' and isinstance(part, Audio):
                    transcript = await self._media_to_text_with_hint(part)
                elif kind == 'video' and isinstance(part, Video):
                    transcript = await self._media_to_text_with_hint(part)
                else:
                    transcript = ''
                if transcript:
                    cast(list[str | LLMContent], normalized[msg_idx]['content'])[part_idx] = transcript
                    total_tokens = _current_total()

        if total_tokens > client.max_tokens and audio_refs:
            tail_msg_idx, tail_part_idx = audio_refs[-1]
            tail_parts = cast(list[str | LLMContent], normalized[tail_msg_idx]['content'])
            tail_part = tail_parts[tail_part_idx]
            if len(audio_refs) == 1 and isinstance(tail_part, Audio):
                transcript = await self._media_to_text_with_hint(tail_part)
                if transcript:
                    tail_parts.insert(tail_part_idx, transcript)
                    tail_part_idx += 1
                    audio_refs[-1] = (tail_msg_idx, tail_part_idx)
                    tail_part = tail_parts[tail_part_idx]
                    total_tokens = _current_total()
            if isinstance(tail_part, Audio):
                current_tokens = client.count_tokens(tail_part)
                while total_tokens > client.max_tokens and current_tokens > 0:
                    overflow = total_tokens - client.max_tokens
                    target_tokens = max(1, current_tokens - overflow)
                    trimmed_audio = trim_audio_to_token_budget(tail_part, target_tokens, preserve_tail=True)
                    trimmed_tokens = client.count_tokens(trimmed_audio)
                    if trimmed_tokens >= current_tokens:
                        break
                    tail_parts[tail_part_idx] = trimmed_audio
                    tail_part = trimmed_audio
                    current_tokens = trimmed_tokens
                    total_tokens = _current_total()

        if total_tokens > client.max_tokens and video_refs:
            tail_msg_idx, tail_part_idx = video_refs[-1]
            tail_part = cast(list[str | LLMContent], normalized[tail_msg_idx]['content'])[tail_part_idx]
            if isinstance(tail_part, Video):
                current_tokens = client.count_tokens(tail_part)
                while total_tokens > client.max_tokens and current_tokens > 0:
                    overflow = total_tokens - client.max_tokens
                    target_tokens = max(1, current_tokens - overflow)
                    trimmed_video = trim_video_to_token_budget(tail_part, target_tokens, preserve_tail=True)
                    trimmed_tokens = client.count_tokens(trimmed_video)
                    if trimmed_tokens >= current_tokens:
                        break
                    cast(list[str | LLMContent], normalized[tail_msg_idx]['content'])[tail_part_idx] = trimmed_video
                    tail_part = trimmed_video
                    current_tokens = trimmed_tokens
                    total_tokens = _current_total()

        for order, (msg_idx, part_idx) in enumerate(image_refs):
            if total_tokens <= client.max_tokens:
                break
            if order >= len(image_refs) - 1:
                break
            part = cast(list[str | LLMContent], normalized[msg_idx]['content'])[part_idx]
            if not isinstance(part, Image):
                continue
            ocr_text = await self._image_to_text(part)
            if ocr_text:
                cast(list[str | LLMContent], normalized[msg_idx]['content'])[part_idx] = ocr_text
                total_tokens = _current_total()

        out_messages: list[ChatMessageInput] = []
        for msg in normalized:
            parts = [part for part in cast(list[str | LLMContent], msg['content']) if not (isinstance(part, str) and not part.strip())]
            content: ChatContent
            if len(parts) == 1:
                content = parts[0]
            else:
                content = parts
            out_messages.append({'role': cast(ChatRole, msg['role']), 'content': content})
        return out_messages

    async def _adapt_messages_for_client(
        self,
        messages: Sequence[ChatMessageInput],
        client: CompletionClient,
        internal_params: dict[str, Any] | None = None,
    ) -> list[ChatMessageInput]:
        internal = internal_params or {}
        max_images = None if client.max_images is None else max(0, int(client.max_images))
        max_audios = None if client.max_audios is None else max(0, int(client.max_audios))
        max_videos = None if client.max_videos is None else max(0, int(client.max_videos))

        used_images = 0
        used_audios = 0
        used_videos = 0
        seen_audios = 0
        seen_videos = 0

        out_messages: list[ChatMessageInput] = []
        for msg in messages:
            role: ChatRole = 'user'
            content = self._extract_msg_content(msg)
            if isinstance(msg, dict):
                role = cast(ChatRole, msg.get('role', 'user'))

            new_parts: list[str | LLMContent] = []
            for part in await _expand_llm_content(content):
                if isinstance(part, Image):
                    if max_images is None or used_images < max_images:
                        new_parts.append(part)
                        used_images += 1
                    else:
                        ocr_text = cast(str, (await cast(Any, self.ocr)(part, stream=False)))
                        if ocr_text.strip():
                            new_parts.append(ocr_text)
                    continue

                if isinstance(part, Audio):
                    audio_idx = seen_audios
                    seen_audios += 1
                    if max_audios is None or used_audios < max_audios:
                        new_parts.append(part)
                        used_audios += 1
                    else:
                        s2t_lang = self._internal_media_lang(internal, 'audio', audio_idx)
                        s2t_text = await self._media_to_text_with_hint(part, language=s2t_lang)
                        if s2t_text:
                            new_parts.append(s2t_text)
                    continue

                if isinstance(part, Video):
                    video_idx = seen_videos
                    seen_videos += 1
                    if max_videos is None or used_videos < max_videos:
                        new_parts.append(part)
                        used_videos += 1
                    else:
                        s2t_lang = self._internal_media_lang(internal, 'video', video_idx)
                        s2t_text = await self._media_to_text_with_hint(part, language=s2t_lang)
                        if s2t_text:
                            new_parts.append(s2t_text)
                    continue

                new_parts.append(part)

            merged_content: ChatContent
            if len(new_parts) == 1:
                merged_content = new_parts[0]
            else:
                merged_content = new_parts
            out_messages.append({'role': role, 'content': merged_content})

        return out_messages

    async def _sort_clients_for_messages(self, messages: Sequence[ChatMessageInput]) -> list[CompletionClient]:
        image_count, audio_count, video_count = await self._count_multimodal(messages)
        for client in self.clients:
            bonus = self._client_multimodal_score(client, image_count, audio_count, video_count) * 0.7
            if image_count > 0 and isinstance(client.max_images, int) and client.max_images <= 0:
                bonus -= 100.0
            if audio_count > 0 and isinstance(client.max_audios, int) and client.max_audios <= 0:
                bonus -= 100.0
            if video_count > 0 and isinstance(client.max_videos, int) and client.max_videos <= 0:
                bonus -= 100.0
            setattr(client, '_state_multimodal_bonus', bonus)

        return cast(list[CompletionClient], await self._sorted_clients(self.clients))

    async def _complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> str:
        _ctx, _ctx_token = enter_service_context('completion')
        try:
            messages = list(kwargs.get('messages') or [])
            ordered_clients = await self._sort_clients_for_messages(messages)

            async def _action(client: CompletionClient) -> tuple[str, float]:
                payload_raw: dict[str, Any] = cast(dict[str, Any], kwargs.copy())
                internal_params = self._pop_internal_complete_params(payload_raw)
                payload = cast(ChatCompleteParams, payload_raw)
                if messages:
                    payload['messages'] = await self._adapt_messages_for_client(messages, client, internal_params)
                    payload['messages'] = await self._fit_messages_to_token_limit(payload['messages'], client)
                result = await client.complete(**payload)
                _usage = client._peek_latest_token_usage()
                self._set_latest_token_usage(_usage)
                self._set_latest_thinking(client._peek_latest_thinking())
                # Fallback: estimate tokens when the client does not report usage
                if _usage is None or all(v is None for v in _usage.values()):
                    try:
                        _in_est = client.count_tokens(cast(Any, payload.get('messages') or []))
                        _out_est = estimate_text_tokens(result)
                        _thinking_text = client._peek_latest_thinking()
                        _reasoning_est: int | None = None
                        if _thinking_text:
                            _reasoning_est = estimate_text_tokens(_thinking_text)
                            _out_est += _reasoning_est
                        self._set_latest_token_usage({
                            'input_tokens': _in_est,
                            'output_tokens': _out_est,
                            'total_tokens': _in_est + _out_est,
                            'reasoning_tokens': _reasoning_est,
                        })
                    except Exception:
                        pass
                throughput_workload = float(max(len(result), 1))
                return result, max(throughput_workload, 1.0)

            return cast(str, await self._run_with_failover(ordered_clients, _action, error_prefix='All completion clients failed'))
        finally:
            exit_service_context(_ctx_token)

    async def _stream_complete_impl(self, **kwargs: Unpack[ChatCompleteParams]) -> AsyncGenerator[CompletionStreamChunk, None]:
        _ctx, _ctx_token = enter_service_context('completion')
        try:
            self._ensure_recovery_task()
            errors: list[str] = []
            cooldown_blocked: list[CompletionClient] = []

            messages = list(kwargs.get('messages') or [])
            ordered_clients = await self._sort_clients_for_messages(messages)

            for tier_clients in self._strategy_groups(ordered_clients):
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
                        payload_raw: dict[str, Any] = cast(dict[str, Any], kwargs.copy())
                        internal_params = self._pop_internal_complete_params(payload_raw)
                        payload = cast(ChatCompleteParams, payload_raw)
                        if messages:
                            payload['messages'] = await self._adapt_messages_for_client(messages, client, internal_params)
                            payload['messages'] = await self._fit_messages_to_token_limit(payload['messages'], client)
                        _stream_collector = _StreamLogCollector()
                        async for chunk in client.stream_complete(**payload):
                            streamed = True
                            _stream_collector.add(chunk)
                            yield chunk
                        _stream_usage = client._peek_latest_token_usage()
                        self._set_latest_token_usage(_stream_usage)
                        self._set_latest_thinking(client._peek_latest_thinking())
                        # Fallback: estimate tokens when the client does not report usage
                        if _stream_usage is None or all(v is None for v in _stream_usage.values()):
                            try:
                                _in_est = client.count_tokens(cast(Any, payload.get('messages') or []))
                                _out_est = estimate_text_tokens(_stream_collector.final_text())
                                _think_text = _stream_collector.final_think_text()
                                _reasoning_est: int | None = estimate_text_tokens(_think_text) if _think_text else None
                                self._set_latest_token_usage({
                                    'input_tokens': _in_est,
                                    'output_tokens': _out_est,
                                    'total_tokens': _in_est + _out_est,
                                    'reasoning_tokens': _reasoning_est,
                                })
                            except Exception:
                                pass
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
                    payload_raw = cast(dict[str, Any], kwargs.copy())
                    internal_params = self._pop_internal_complete_params(payload_raw)
                    payload = cast(ChatCompleteParams, payload_raw)
                    if messages:
                        payload['messages'] = await self._adapt_messages_for_client(messages, best, internal_params)
                        payload['messages'] = await self._fit_messages_to_token_limit(payload['messages'], best)
                    _stream_collector = _StreamLogCollector()
                    async for chunk in best.stream_complete(**payload):
                        _stream_collector.add(chunk)
                        yield chunk
                    _stream_usage = best._peek_latest_token_usage()
                    self._set_latest_token_usage(_stream_usage)
                    self._set_latest_thinking(best._peek_latest_thinking())
                    if _stream_usage is None or all(v is None for v in _stream_usage.values()):
                        try:
                            _in_est = best.count_tokens(cast(Any, payload.get('messages') or []))
                            _out_est = estimate_text_tokens(_stream_collector.final_text())
                            _think_text = _stream_collector.final_think_text()
                            _reasoning_est: int | None = estimate_text_tokens(_think_text) if _think_text else None
                            self._set_latest_token_usage({
                                'input_tokens': _in_est,
                                'output_tokens': _out_est,
                                'total_tokens': _in_est + _out_est,
                                'reasoning_tokens': _reasoning_est,
                            })
                        except Exception:
                            pass
                    await self._on_success(best)
                    return
                except Exception as exc:
                    await self._on_fail(best, exc)
                    errors.append(f'[{self._client_display_name(best)}] {type(exc).__name__}: {exc}')
                finally:
                    best._state_inflight = max(0, int(getattr(best, '_state_inflight', 1)) - 1)  # type: ignore[attr-defined]

            if errors:
                raise RuntimeError('All stream completion clients failed. ' + ' | '.join(errors))
            total = len(ordered_clients)
            if total == 0:
                raise RuntimeError(
                    'No completion client is configured. '
                    'Check AI provider env keys (TTS_APIKEY / TTS_API_KEY / OPENROUTER_APIKEY / OPENROUTER_API_KEY / OPENAI_APIKEY / OPENAI_API_KEY) '
                    'and CompletionService configuration.'
                )
            now = time.time()
            details: list[str] = []
            for client in ordered_clients:
                name = self._client_display_name(client)
                reasons: list[str] = []
                if bool(getattr(client, '_closed', False)):
                    reasons.append('closed')
                cooldown_until = float(getattr(client, '_state_cooldown_until', 0.0))
                if cooldown_until > now:
                    reasons.append(f'cooldown {cooldown_until - now:.1f}s')
                inflight = int(getattr(client, '_state_inflight', 0))
                max_concurrent = getattr(client, 'max_concurrent', None)
                if isinstance(max_concurrent, int) and max_concurrent > 0 and inflight >= max_concurrent:
                    reasons.append(f'full {inflight}/{max_concurrent}')
                last_err = getattr(client, '_state_last_error', None)
                if last_err:
                    reasons.append(f'last_error={last_err}')
                details.append(f'[{name}] ' + (', '.join(reasons) if reasons else 'unavailable'))
            raise RuntimeError(
                f'No completion client could accept the request ({total} configured). ' + ' | '.join(details)
            )
        finally:
            try:
                exit_service_context(_ctx_token)
            except ValueError:
                pass  # Token was created in a different Context (generator GC'd across tasks)

    def _resolve_target_language(self, target_language: str | Language) -> tuple[str, str]:
        lang: Language | None = None
        if isinstance(target_language, Language):
            lang = target_language
        elif isinstance(target_language, str):
            lang = Language.Find(target_language)

        if lang is not None:
            return lang.code, f'{lang.name}({lang.origin_name})'

        target_text = str(target_language).strip()
        return target_text, target_text

    def _translation_cache_key(self, source_text: str, target_language: str) -> str:
        key_raw = f'{target_language}||{source_text}'
        return hashlib.md5(key_raw.encode('utf-8')).hexdigest()

    async def _translation_cache_get(self, source_text: str, target_language: str) -> str | None:
        key = self._translation_cache_key(source_text, target_language)
        try:
            client = self._get_translate_cache_client()
            rec = await client.search_one(self._TranslationCacheRecord, {'cache_key': key})
            if rec is None:
                return None
            rec.hit_count += 1
            rec.updated_at = time.time()
            await client.set(rec)
            return rec.translated_text
        except Exception:
            return None

    async def _translation_cache_put(self, source_text: str, target_language: str, translated_text: str) -> None:
        if len(source_text) > _NO_TRANSLATION_CACHE_LEN:
            return
        key = self._translation_cache_key(source_text, target_language)
        try:
            client = self._get_translate_cache_client()
            existing = await client.search_one(self._TranslationCacheRecord, {'cache_key': key})
            if existing is not None:
                existing.translated_text = translated_text
                existing.updated_at = time.time()
                await client.set(existing)
            else:
                rec = self._TranslationCacheRecord(
                    cache_key=key,
                    source_text=source_text,
                    source_language=None,
                    target_language=target_language,
                    translated_text=translated_text,
                    updated_at=time.time(),
                )
                await client.set(rec)
        except Exception:
            pass

    async def translate(
        self,
        text: str,
        target_language: str | Language,
        prompt: str | Prompt | None = None,
        reference: str | None = None,
        use_cache: bool = True,
        save_cache: bool = True,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> str:
        if not text or not text.strip():
            return text

        normalized_text = _normalize_translation_signal_text(text)
        if not normalized_text:
            return text

        sanitized_reference = _sanitize_translation_reference(text, reference)
        target_lang_key, prompt_target_language = self._resolve_target_language(target_language)

        if use_cache:
            cached = await self._translation_cache_get(text, target_lang_key)
            if cached is not None:
                return cached

        instruction_template = cast(str | Prompt, prompt or self.TRANSLATE_PROMPT_TEMPLATE)
        instruction = _format_prompt_template(
            instruction_template,
            target_language=prompt_target_language,
        )
        instruction = instruction + ' Return translated text only, keep original structure and line breaks.'
        if sanitized_reference:
            instruction = instruction + ' Use the reference context only to disambiguate wording; do not translate, echo, or expand the reference itself.'
        messages: list[ChatMessageInput] = [
            {'role': 'system', 'content': 'You are a professional translator.'},
            {
                'role': 'user',
                'content': (
                    [
                        instruction,
                        '\n\nReference context:\n',
                        sanitized_reference,
                        '\n\nText:\n',
                        text,
                    ]
                    if sanitized_reference else
                    [instruction, '\n\n', text]
                ),
            },
        ]
        payload = cast(ChatCompleteParams, kwargs.copy())
        payload['messages'] = messages
        translated = cast(str, await self.complete(stream=stream, **payload)).strip()
        if save_cache and translated:
            await self._translation_cache_put(text, target_lang_key, translated)
        return translated

    def _tidy_languages(self, languages: str | Language | Sequence[str | Language] | None) -> list[Language]:
        if isinstance(languages, (str, Language)):
            languages = [languages]

        tidied_langs: list[Language] = []
        if languages:
            for language_item in languages:
                if isinstance(language_item, str):
                    if language_item == 'zh':
                        tidied_langs.append(Language.SimplifiedChinese)
                        tidied_langs.append(Language.TraditionalChinese)
                    else:
                        lang = Language.Find(language_item)
                        if not lang:
                            raise ValueError(f'Invalid language code: {language_item}')
                        tidied_langs.append(lang)
                else:
                    tidied_langs.append(language_item)
        return tidied_langs

    async def detect_language(
        self,
        text: str,
        languages: str | Language | Sequence[str | Language] | None = None,
        fallback_to_algo: bool = True,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> Language | None:
        tidied_langs = self._tidy_languages(languages)
        if not tidied_langs:
            lang_infos = [lang.name for lang in Language]
        else:
            lang_infos = [lang.name for lang in tidied_langs]

        prompt = 'Analyze the following text and determine the human language which it is written in.\n'
        prompt += 'Choice of language should be one of the following:\n{language_list}.\n'
        prompt += 'Here are some hints:\n'
        prompt += '1. If the text is source code, infer the writer\'s language from comments or identifier naming style where possible.\n'
        prompt += '2. If the text mixes multiple languages, choose the dominant language or the one used by the most important speaker.\n'
        prompt += 'Choose the most probable one. If none of the languages match, return None.\n'
        prompt += 'Input text:\n```\n{text}\n```\n'
        prompt = prompt.format(language_list=', '.join(lang_infos), text=text)

        payload = cast(ChatCompleteParams, kwargs.copy())

        result = await self.json_complete(
            prompt,
            return_type=self._DetectedLanguage,
            default=self._DetectedLanguage(detected=None),
            stream=stream,
            **payload,
        )

        if result and result.detected:
            detected = result.detected.strip()
            if detected.lower() in {'none', 'null', ''}:
                detected = ''
            if detected and (lang_enum := Language.Find(detected)):
                return lang_enum

        if fallback_to_algo:
            return detect_lang(text, languages=languages)
        return None

    @overload
    async def ocr(
        self,
        image: Image | LLMDocumentMixin,
        prompt: str | Prompt | None = None,
        pdf_to_extract_mode: Literal['mixed', 'image'] = 'mixed',
        document_to_extract_mode: Literal['mixed', 'image'] | None = None,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> str:
        ...

    @overload
    async def ocr(
        self,
        image: Sequence[Image | LLMDocumentMixin],
        prompt: str | Prompt | None = None,
        pdf_to_extract_mode: Literal['mixed', 'image'] = 'mixed',
        document_to_extract_mode: Literal['mixed', 'image'] | None = None,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> list[str]:
        ...

    async def ocr(
        self,
        image: Image | LLMDocumentMixin | Sequence[Image | LLMDocumentMixin],
        prompt: str | Prompt | None = None,
        pdf_to_extract_mode: Literal['mixed', 'image'] = 'mixed',
        document_to_extract_mode: Literal['mixed', 'image'] | None = None,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> str | list[str]:
        extract_mode = document_to_extract_mode or pdf_to_extract_mode
        if self._is_multi_ocr_input(image):
            tasks = [
                self.ocr(
                    item,
                    prompt=prompt,
                    pdf_to_extract_mode=pdf_to_extract_mode,
                    document_to_extract_mode=document_to_extract_mode,
                    stream=stream,
                    **kwargs,
                )
                for item in cast(Sequence[Image | LLMDocumentMixin], image)
            ]
            results = await asyncio.gather(*tasks)
            return [cast(str, r) for r in results]

        ocr_prompt = prompt or 'Extract all readable text from the given image(s). Preserve order and line breaks.'

        if isinstance(image, LLMDocumentMixin):
            if extract_mode == 'image':
                images = [part for part in await _expand_llm_part(cast(str | LLMContent, image), document_mode='image') if isinstance(part, Image)]
                if not images:
                    return ''
                image_texts = await self.ocr(
                    images,
                    prompt=ocr_prompt,
                    pdf_to_extract_mode='image',
                    document_to_extract_mode='image',
                    stream=stream,
                    **kwargs,
                )
                return '\n'.join(text.strip() for text in image_texts if text.strip()).strip()

            if extract_mode == 'mixed':
                parts: list[str] = []
                images: list[Image] = []
                image_positions: list[int] = []

                for part in await _expand_llm_part(cast(str | LLMContent, image), document_mode='mixed'):
                    if isinstance(part, str):
                        text = part.strip()
                        if text:
                            parts.append(text)
                    elif isinstance(part, Image):
                        image_positions.append(len(parts))
                        parts.append('')
                        images.append(part)

                if images:
                    image_texts = await self.ocr(
                        images,
                        prompt=ocr_prompt,
                        document_to_extract_mode='image',
                        stream=stream,
                        **kwargs,
                    )
                    for index, image_text in enumerate(image_texts):
                        if index < len(image_positions):
                            pos = image_positions[index]
                            parts[pos] = image_text.strip()

                return '\n'.join(part for part in parts if part.strip()).strip()

            raise ValueError(f'Unsupported document extract mode: {extract_mode}')

        content: list[ChatContentPart] = [ocr_prompt, cast(Image, image)]  # type: ignore

        payload = cast(ChatCompleteParams, kwargs.copy())
        payload['messages'] = [{'role': 'user', 'content': content}]
        try:
            result = await self.json_complete(return_type=self._OCRResult, stream=stream, **payload)
            return result.text.strip()
        except Exception:
            raw = cast(str, await self.complete(stream=stream, **payload))
            return raw.strip()

    @overload
    async def asr(
        self,
        audio: Audio | Video,
        prompt: str | Prompt | None = None,
        expected_languages: str | Language | Sequence[str | Language] | None = None,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> str:
        ...

    @overload
    async def asr(
        self,
        audio: Sequence[Audio | Video],
        prompt: str | Prompt | None = None,
        expected_languages: str | Language | Sequence[str | Language] | None = None,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> list[str]:
        ...

    async def asr(
        self,
        audio: Audio | Video | Sequence[Audio | Video],
        prompt: str | Prompt | None = None,
        expected_languages: str | Language | Sequence[str | Language] | None = None,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> str | list[str]:
        if self._is_multi_asr_input(audio):
            tasks = [
                self.asr(item, prompt=prompt, expected_languages=expected_languages, stream=stream, **kwargs)
                for item in cast(Sequence[Audio | Video], audio)
            ]
            results = await asyncio.gather(*tasks)
            return [cast(str, r) for r in results]

        asr_prompt = cast(str | Prompt, prompt or 'Transcribe the given audio/video to text. Keep punctuation and formatting where possible.')
        expected_lang_hint, s2t_language = self._build_expected_language_hint(expected_languages)
        if expected_lang_hint:
            asr_prompt = asr_prompt + f' {expected_lang_hint}'
        payload_raw: dict[str, Any] = cast(dict[str, Any], kwargs.copy())
        payload = cast(ChatCompleteParams, payload_raw)
        payload['messages'] = [{'role': 'user', 'content': [asr_prompt, cast(Audio | Video, audio)]}]   # type: ignore
        if s2t_language:
            if isinstance(audio, Audio):
                payload_raw['__audio_0_lang__'] = s2t_language
            elif isinstance(audio, Video):
                payload_raw['__video_0_lang__'] = s2t_language
        result = await self.json_complete(return_type=self._ASRResult, stream=stream, **payload)
        return result.text.strip()

    @overload
    async def json_complete(
        self,
        prompt: ChatContent,
        *,
        return_type: type[_T],
        return_raw: Literal[True],
        default: _T | None = None,
        json_retry: bool | int = 1,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> tuple[_T, ChatCompletionOutput]: ...
    @overload
    async def json_complete(
        self,
        *,
        return_type: type[_T],
        return_raw: Literal[True],
        default: _T | None = None,
        json_retry: bool | int = 1,
        stream: bool = True,
        **kwargs: Unpack[JsonCompleteRequiredMessagesParams],
    ) -> tuple[_T, ChatCompletionOutput]: ...
    @overload
    async def json_complete(
        self,
        prompt: ChatContent,
        *,
        return_type: type[_T],
        default: _T | None = None,
        json_retry: bool | int = 1,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> _T: ...
    @overload
    async def json_complete(
        self,
        *,
        return_type: type[_T],
        default: _T | None = None,
        json_retry: bool | int = 1,
        stream: bool = True,
        **kwargs: Unpack[JsonCompleteRequiredMessagesParams],
    ) -> _T: ...

    async def json_complete(
        self,
        prompt: ChatContent | None = None,
        *,
        return_type: type[_T],
        default: _T | None = None,
        json_retry: bool | int = 1,
        stream: bool = True,
        return_raw: bool = False,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> _T | tuple[_T, ChatCompletionOutput]:
        payload = cast(ChatCompleteParams, kwargs.copy())
        messages = _merge_messages_with_user_prompt(payload.get('messages'), prompt)
        if not messages:
            raise ValueError('`messages` is required when `prompt` is not provided for json_complete.')
        payload['messages'] = messages

        origin_payload = cast(dict[str, Any], payload.copy())
        retry_count = int(json_retry)
        need_convert_to_tuple = False

        try:
            type_args = list(getattr(return_type, '__args__', []) or [])
        except Exception:
            type_args = []
        try:
            type_origin = getattr(return_type, '__origin__', None)
        except Exception:
            type_origin = None

        if return_type == tuple or type_origin == tuple:
            if not type_args:
                return_type = cast(type[_T], list)
                type_origin = list
                need_convert_to_tuple = True
            elif len(type_args) == 2 and type_args[0] != Ellipsis and type_args[1] == Ellipsis:
                return_type = cast(type[_T], list[type_args[0]])
                type_origin = list
                type_args = [type_args[0]]
                need_convert_to_tuple = True

        schema = _json_schema_of_type(cast(type[Any], return_type))
        reasoning = payload.get('reasoning', False)
        if reasoning:
            payload['messages'] = _append_schema_instruction(
                messages,
                schema,
                reasoning=True,
                default_json_example=_try_dump_default_json_example(cast(type[Any], return_type)),
            )
            payload.pop('json_schema', None)
            payload['reasoning'] = True
        else:
            payload['messages'] = _append_schema_instruction(messages, schema)
            payload['json_schema'] = schema
            payload['reasoning'] = False  # forward explicit disable to suppress thinking

        try_validate_types: list[tuple[type[Any], Callable[[Any], Any] | None]] = [(cast(type[Any], return_type), None)]
        if (return_type == list or type_origin == list) and len(type_args) == 1:
            try_validate_types.append((cast(type[Any], type_args[0]), list))

        is_model_v2 = _is_basemodel_v2(cast(type[Any], return_type), type_origin)
        is_model_v1 = (not is_model_v2 and _is_basemodel_v1(cast(type[Any], return_type), type_origin))

        def try_extract(s: str, val_types: list[tuple[type[Any], Callable[[Any], Any] | None]]) -> Any:
            candidate: Any = s
            if isinstance(candidate, str):
                candidate = _try_parse_json_response_text(candidate)

            for i, (try_type, callback) in enumerate(val_types):
                try:
                    if is_model_v2 or is_model_v1:
                        model_fields = try_type.model_fields if is_model_v2 else try_type.__fields__
                        required_fields: set[str] = set()
                        for name, field in model_fields.items():
                            if field.default == PydanticUndefined and field.default_factory in (None, PydanticUndefined):
                                required_fields.add(name)

                        def _check_dict(d: dict[str, Any]) -> bool:
                            required = required_fields.copy()
                            for key in d:
                                if key in required:
                                    required.remove(key)
                            return len(required) == 0

                        if isinstance(candidate, dict):
                            if 'properties' in candidate and 'title' in candidate and 'type' in candidate:
                                if any((k not in model_fields) for k in ['properties', 'title', 'type']):
                                    properties = candidate['properties']
                                    title = candidate['title']
                                    type_ = candidate['type']
                                    cls_name = try_type.__name__.split('.')[-1]
                                    if title == cls_name and type_ == 'object' and isinstance(properties, dict):
                                        candidate = properties
                                elif len(candidate) == 1:
                                    first_key = next(iter(candidate.keys()))
                                    inner = candidate[first_key]
                                    if first_key not in model_fields and isinstance(inner, dict) and _check_dict(inner):
                                        candidate = inner

                    validated = _validate_to_type(candidate, try_type)
                    if callback:
                        validated = callback(validated)
                    return validated
                except Exception:
                    if i != len(val_types) - 1:
                        continue
                    return None
            return None

        extract = partial(try_extract, val_types=try_validate_types)

        async def retry_or_default(exc: Exception, curr_retry: int) -> _T | tuple[_T, ChatCompletionOutput]:
            if curr_retry > 0:
                return await self.json_complete(  # type: ignore[call-overload]
                    return_type=return_type,
                    default=default,
                    json_retry=curr_retry - 1,
                    stream=stream,
                    return_raw=return_raw,  # type: ignore[arg-type]
                    **cast(ChatCompleteParams, origin_payload),
                )
            if default is not None:
                if return_raw:
                    return default, ChatCompletionOutput(text='', thinking=None, input_tokens=None, output_tokens=None)
                return default
            raise ValueError(f'Failed to get json response from LLM. Error: {type(exc).__name__}: {exc}') from exc

        raw_output: ChatCompletionOutput | None = None
        try:
            if return_raw:
                raw_output = await self.complete(full_output=True, stream=stream, **payload)  # type: ignore[call-overload]
                text = raw_output['text'].strip()   # type: ignore
            else:
                text = cast(str, await self.complete(stream=stream, **payload)).strip()
        except Exception as exc:
            return await retry_or_default(exc, retry_count)

        json_r: object = None
        if return_type == list or return_type == tuple or type_origin in (list, tuple):
            try_patterns = [r'(\[.*\])', r'(\{.*\})']
        else:
            try_patterns = [r'(\{.*\})']

        while (json_r is None) and try_patterns:
            p = try_patterns.pop(0)
            matched = re.search(p, text, re.DOTALL | re.MULTILINE)
            if matched:
                json_text = matched.group(1)
                json_r = extract(json_text)

        if json_r is None:
            if retry_count > 0:
                return await self.json_complete(  # type: ignore[call-overload]
                    return_type=return_type,
                    default=default,
                    json_retry=retry_count - 1,
                    stream=stream,
                    return_raw=return_raw,  # type: ignore[arg-type]
                    **cast(ChatCompleteParams, origin_payload),
                )
            if default is not None:
                if return_raw:
                    return default, raw_output or ChatCompletionOutput(text=text, thinking=None, input_tokens=None, output_tokens=None)
                return default
            raise ValueError(f'Failed to extract json response from model output: {text}')

        if need_convert_to_tuple and isinstance(json_r, Sequence) and not isinstance(json_r, str):
            json_r = tuple(json_r)
        if return_raw:
            return cast(_T, json_r), raw_output or ChatCompletionOutput(text=text, thinking=None, input_tokens=None, output_tokens=None)
        return cast(_T, json_r)

    async def summarize(
        self,
        content: ChatContent,
        *,
        prompt: str | Prompt | None = None,
        chunk_size: int | None = None,
        sliding_window_size: float = 0.15,
        acceptable_word_count: int | None = None,
        acceptable_word_count_error: float = 1.05,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> str:
        '''Summarize content.

        For purely text content, applies map-reduce chunking:
        - Splits text into chunks of at most `chunk_size` words at semantic boundaries.
        - Adds sliding window overlap from neighboring chunks (approximately
          `sliding_window_size * chunk_size` words from the previous/next chunk).
        - Summarizes all chunks in parallel via asyncio.gather.
        - Recursively reduces partial summaries until a final summary is produced.

        Multimodal content (containing Image / Audio / Video) is summarized directly
        without chunking.

        Args:
            chunk_size: Maximum word count per text chunk.  Defaults to
                ``min(1024, min_client_max_tokens)`` across live clients.
            sliding_window_size: Overlap fraction (0–1). E.g. 0.15 with 100-word
                chunks pulls ~15 words from the tail/head of neighboring chunks.
                Cuts are made at sentence/clause boundaries where possible.
        '''
        instruction = cast(str | Prompt, prompt or 'Summarize the following content briefly and accurately.')

        # Expand all parts to primitive types first so we can accurately detect real media.
        # LLMDocumentMixin subclasses (PlainText, Markdown, …) expand to strings;
        # PDF/Doc/Excel/etc. expand to Images – we need to know which is which.
        raw_parts = _as_list(content)
        expanded_parts: list[str | Image | Audio | Video] = []
        for _p in raw_parts:
            if isinstance(_p, (str, Image, Audio, Video)):
                expanded_parts.append(_p)
            else:
                try:
                    expanded_parts.extend(await _expand_llm_part(_p))
                except Exception:
                    expanded_parts.append(str(_p))

        # Check whether content contains any real media elements (after expansion)
        has_media = any(isinstance(p, (Image, Audio, Video)) for p in expanded_parts)

        if has_media:
            # Multimodal: skip chunking, summarize directly
            payload = cast(ChatCompleteParams, kwargs.copy())
            payload['messages'] = [{'role': 'user', 'content': cast(list[ChatContentPart], [instruction, '\n\n', *expanded_parts])}]
            result = await self.json_complete(return_type=self._SummaryResult, stream=stream, **payload)
            return result.summary.strip()

        # Text-only path: collect all string content from expanded parts
        full_text = '\n'.join(p for p in expanded_parts if isinstance(p, str)).strip()
        if not full_text:
            return ''

        # Determine chunk_size
        if chunk_size is None:
            _min_tokens = 1024
            for _c in self.clients:
                if isinstance(getattr(_c, 'max_tokens', None), int):
                    _min_tokens = min(_min_tokens, _c.max_tokens)   # type: ignore
            chunk_size = min(1024, _min_tokens)
        chunk_size = max(64, chunk_size)

        text_chunks = split_text_by_word_count(full_text, max_word_count=chunk_size)
        if not text_chunks:
            return ''

        async def _summarize_once(content_value: ChatContent) -> str:
            payload = cast(ChatCompleteParams, kwargs.copy())
            payload['messages'] = [{'role': 'user', 'content': content_value}]
            try:
                result = await self.json_complete(return_type=self._SummaryResult, stream=stream, **payload)
                return result.summary.strip()
            except Exception:
                raw = cast(str, await self.complete(stream=stream, **payload))
                return raw.strip()

        # Single chunk: summarize directly
        if len(text_chunks) == 1:
            return await _summarize_once(instruction + '\n\n' + text_chunks[0]['text'])

        # Multiple chunks: apply sliding window and summarize in parallel
        overlap_wc = max(1, int(chunk_size * max(0.0, min(1.0, sliding_window_size))))

        def _tail_overlap(text: str) -> str:
            '''Extract ~overlap_wc words from the tail of text at a semantic boundary.'''
            sub_chunks = split_text_by_word_count(text, max_word_count=max(1, overlap_wc))
            return sub_chunks[-1]['text'].strip() if sub_chunks else ''

        def _head_overlap(text: str) -> str:
            '''Extract ~overlap_wc words from the head of text at a semantic boundary.'''
            return truncate_text_by_word_count(text, overlap_wc).strip()

        async def _summarize_chunk(chunk_text: str) -> str:
            return await _summarize_once(instruction + '\n\n' + chunk_text)

        # Build windowed chunks
        windowed_chunks: list[str] = []
        for i, chunk in enumerate(text_chunks):
            window_parts: list[str] = []
            if i > 0:
                prev_tail = _tail_overlap(text_chunks[i - 1]['text'])
                if prev_tail:
                    window_parts.append('...\n' + prev_tail)
            window_parts.append(chunk['text'])
            if i < len(text_chunks) - 1:
                next_head = _head_overlap(text_chunks[i + 1]['text'])
                if next_head:
                    window_parts.append(next_head + '\n...')
            windowed_chunks.append('\n'.join(window_parts))

        # Gather all chunk summaries in parallel
        raw_summaries = await asyncio.gather(*(_summarize_chunk(wc) for wc in windowed_chunks))
        summaries = [s for s in raw_summaries if s]
        if not summaries:
            return ''
        if len(summaries) == 1:
            return summaries[0]

        # Early termination: combined summaries already within acceptable word count
        if acceptable_word_count is not None:
            joined = '\n\n'.join(summaries)
            if word_count(joined) <= acceptable_word_count * acceptable_word_count_error:
                return joined

        # Reduce phase: join summaries and recurse if still too long
        reduce_instruction = (
            'The following are partial summaries of a longer document. '
            'Merge them into a single coherent summary.\n\n' + instruction
        )
        combined = '\n\n'.join(f'[Part {i + 1}]\n{s}' for i, s in enumerate(summaries))
        if word_count(combined) <= chunk_size:
            return await _summarize_once(reduce_instruction + '\n\n' + combined)
        else:
            # Still too long: recurse
            return await self.summarize(
                combined,
                prompt=reduce_instruction,
                chunk_size=chunk_size,
                sliding_window_size=sliding_window_size,
                acceptable_word_count=acceptable_word_count,
                acceptable_word_count_error=acceptable_word_count_error,
                stream=stream,
                **kwargs,
            )

    async def rerank(
        self,
        query: str,
        candidates: Sequence[str | LLMContent | Sequence[str | LLMContent]],
        *,
        prompt: str | Prompt | None = None,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> 'CompletionService.RerankResult':
        if not candidates:
            return self.RerankResult(items=[])

        # Defensive: detect candidates that are exactly equal to the query text and
        # assign them the maximum score directly, to avoid wasting tokens on obvious matches.
        query_str = str(query).strip()
        exact_match_indices: set[int] = set()
        rerank_indices: list[int] = []
        for i, cand in enumerate(candidates):
            if _is_single_chat_content(cand) and isinstance(cand, str) and cand.strip() == query_str:
                exact_match_indices.add(i)
            else:
                rerank_indices.append(i)

        full_items: list['CompletionService.FullRerankItem'] = []

        # Exact matches get score 10 (max) directly
        for i in exact_match_indices:
            candidate = candidates[i]
            normalized_candidate: str | LLMContent | list[str | LLMContent]
            if _is_single_chat_content(candidate):
                normalized_candidate = cast(str | LLMContent, candidate)
            else:
                normalized_candidate = list(cast(Sequence[str | LLMContent], candidate))
            full_items.append(self.FullRerankItem(index=i, score=10.0, candidate=normalized_candidate))

        # Only send the non-exact candidates to the LLM for scoring
        if rerank_indices:
            instruction = cast(str | Prompt, prompt or self.RERANK_PROMPT)
            content: list[ChatContentPart] = [instruction, '\n\nQuery:\n', query, '\n\nCandidates:\n']
            for local_index, original_index in enumerate(rerank_indices):
                candidate = candidates[original_index]
                content.append(f'Candidate[{local_index}]:\n')
                if _is_single_chat_content(candidate):
                    content.append(cast(str | LLMContent, candidate))
                else:
                    content.extend(list(cast(Sequence[str | LLMContent], candidate)))
                content.append('\n')

            payload = cast(ChatCompleteParams, kwargs.copy())
            payload['messages'] = [{'role': 'user', 'content': content}]
            score_result = await self.json_complete(return_type=self._RerankScoreResult, stream=stream, **payload)

            for raw_item in score_result.items:
                if isinstance(raw_item, self.RerankItem):
                    item = raw_item
                elif isinstance(raw_item, dict):
                    try:
                        item = self.RerankItem.model_validate(raw_item)
                    except Exception:
                        continue
                else:
                    continue

                if item.index < 0 or item.index >= len(rerank_indices):
                    continue
                original_index = rerank_indices[item.index]
                candidate = candidates[original_index]
                normalized_candidate2: str | LLMContent | list[str | LLMContent]
                if _is_single_chat_content(candidate):
                    normalized_candidate2 = cast(str | LLMContent, candidate)
                else:
                    normalized_candidate2 = list(cast(Sequence[str | LLMContent], candidate))
                full_items.append(self.FullRerankItem(
                    index=original_index,
                    score=float(item.score),
                    candidate=normalized_candidate2,
                ))

        full_items.sort(key=lambda x: x.score, reverse=True)
        return self.RerankResult(items=full_items)

    async def transcript(
        self,
        audio: Audio | Video,
        *,
        prompt: str | Prompt | None = None,
        expected_languages: str | Language | Sequence[str | Language] | None = None,
        roles: Sequence[str] | None = None,
        stream: bool = True,
        **kwargs: Unpack[ChatCompleteOptionalParams],
    ) -> 'CompletionService.Transcription':
        instruction = cast(str | Prompt, prompt or self.TRANSCRIPT_PROMPT)
        expected_lang_hint, s2t_language = self._build_expected_language_hint(expected_languages)
        if expected_lang_hint:
            instruction = instruction + f' {expected_lang_hint}'
        if roles:
            role_hint = ', '.join(roles)
            instruction = instruction + f' Possible roles: {role_hint}.'
        payload_raw: dict[str, Any] = cast(dict[str, Any], kwargs.copy())
        payload = cast(ChatCompleteParams, payload_raw)
        payload['messages'] = [{'role': 'user', 'content': [instruction, audio]}]   # type: ignore
        if s2t_language:
            if isinstance(audio, Audio):
                payload_raw['__audio_0_lang__'] = s2t_language
            elif isinstance(audio, Video):
                payload_raw['__video_0_lang__'] = s2t_language

        transcription_type: type[Any] = self.Transcription
        if roles:
            normalized_roles = [role.strip() for role in roles if isinstance(role, str) and role.strip()]
            unique_roles = list(dict.fromkeys(normalized_roles))
            if unique_roles:
                role_literal = Literal.__getitem__(tuple(unique_roles) if len(unique_roles) > 1 else unique_roles[0])  # type: ignore[attr-defined]
                transcription_type = create_model(
                    'TranscriptionWithRoles',
                    transcript=(list[dict[role_literal, str]], ...),
                )

        result = await self.json_complete(return_type=cast(type[Any], transcription_type), stream=stream, **payload)
        if isinstance(result, BaseModel):
            return self.Transcription.model_validate(result.model_dump())
        return self.Transcription.model_validate(result)


__all__ += [
    'CompletionCallableMixin',
    'CompletionClient',
    'ThinkThinkSynCompletionClient',
    'OpenAILikedCompletionClient',
    'CompletionService',
]
