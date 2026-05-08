import os
import json
import time
import asyncio
import hashlib
import logging
import inspect

from functools import cache
from dataclasses import dataclass
from typing_extensions import Unpack
from typing import TYPE_CHECKING, Callable, ClassVar, Literal, Sequence, cast, TypedDict, overload
from thinkthinksyn import ThinkThinkSyn

from core.utils.data_structs import Audio, Image, Video, LLMDocumentMixin
from core.utils.text_utils import (
    split_text_by_word_count, 
    truncate_text_by_word_count, 
    translate_chinese, 
    ZHTranslationType
)
from core.storage import ORMField, ORMModel, StorageConfig

from .base import (
    ServiceClient,
    ServiceClientBase,
    ServiceInitParams,
    ServiceClientInitParams,
    ServiceParamsBase,
    ServiceBase,
    StrategyLevel,
    ConcurrentPool,
    _AnnotateDefault,
    _apply_service_param_defaults,
    _patch_thinkthinksyn_proxy,
    _apply_ssh_tunnel_to_tts_client,
    _resolve_ssh_tunnel_config,
    thinkthinksyn_client,
    get_inference_context,
    enter_service_context,
    exit_service_context,
)
from .shared import AIServiceKind
from ._multimodal_token_utils import (
    TokenCountable,
    compress_image_to_token_budget,
    estimate_multimodal_tokens,
    split_audio_on_silence,
    split_video_to_token_budget,
    trim_audio_to_token_budget,
    trim_video_to_token_budget,
)

if TYPE_CHECKING:
    from .completion import CompletionService
    from .s2t import S2TService

_logger = logging.getLogger(__name__)
_DEFAULT_EMBEDDING_TIMEOUT = 60.0
'''默认 embedding 请求超时（秒）。'''

EmbeddingCachePayload = dict[str, object]
EmbeddingModelLookup = dict[str, tuple[str, type[object]]]

__all__ = []

# ══════════════════════════════════════════════════════════════════════════════
# Data classes for advanced methods
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EmbeddedChunk:
    '''文本分块 + 对应向量。'''
    text: str
    '''分块文本内容。'''
    vector: list[float]
    '''对应的嵌入向量。'''
    index: int
    '''在原始分块序列中的索引。'''
    offset: int = 0
    '''在原始文本中的字符偏移量。'''

@dataclass
class EmbeddingRerankItem:
    '''基于嵌入的重排结果项。'''
    index: int
    '''候选项在原始序列中的索引。'''
    score: float
    '''余弦相似度分数。'''
    candidate: str
    '''原始候选文本。'''

@dataclass
class DiversityRerankItem:
    '''多样性重排结果项。'''
    index: int
    '''候选项在原始序列中的索引。'''
    candidate: str
    '''原始候选文本。'''
    min_distance: float = 0.0
    '''与已选集合中最近项的余弦距离。'''

# ══════════════════════════════════════════════════════════════════════════════
# ORM-backed embedding cache
# ══════════════════════════════════════════════════════════════════════════════
class EmbeddingCacheRecord(ORMModel, collection_name='embedding_cache'):
    '''ORM record for a cached embedding vector.'''
    text_hash: str = ORMField(index=True)
    '''SHA-256 hex digest of the source text.'''
    text_content: str
    '''Original text content (stored for debugging / deduplication).'''
    vector_json: list[float]
    '''Embedding vector stored as a native list of floats.'''
    dims: int
    '''Dimensionality of the stored vector.'''
    accessed_at: float = 0.0
    '''Unix timestamp of the most recent cache hit.'''

class _ORMEmbeddingCache:
    '''Async ORM-backed embedding cache.

    All reads/writes go through the project-wide ORM client (cache DB).
    '''

    _ACCESSED_AT_UPDATE_THRESHOLD_SECONDS = 300  # 5 minutes

    def __init__(self) -> None:
        self._client: object | None = None

    def _get_client(self):
        if self._client is None:
            cfg = StorageConfig.Global()
            self._client = cfg.orm.get_client('embedding_cache', fallback='cache')
        return self._client

    async def _ensure_collection_ready(self) -> None:
        client = self._get_client()
        ensure_collection = getattr(client, 'ensure_collection', None)
        if callable(ensure_collection):
            await ensure_collection(EmbeddingCacheRecord)   # type: ignore

    async def _build_store_payloads(self, texts: Sequence[str], vectors: Sequence[list[float]]) -> list[EmbeddingCachePayload]:
        unique_payloads: dict[str, tuple[str, list[float]]] = {}
        for text, vector in zip(texts, vectors):
            try:
                vector_list = [float(value) for value in vector]
            except Exception:
                continue
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            unique_payloads[text_hash] = (text, vector_list)

        if not unique_payloads:
            return []

        client = self._get_client()
        await self._ensure_collection_ready()

        hashes = list(unique_payloads)
        existing_ids: dict[str, str] = {}
        selected_search = getattr(client, 'selected_search', None)
        if callable(selected_search):
            async for row in selected_search(
                EmbeddingCacheRecord,
                fields=('id', 'text_hash'),
                query={'text_hash': {'$in': hashes}},
                limit=len(hashes),
            ):  # type: ignore
                if not isinstance(row, dict):
                    continue
                text_hash = str(row.get('text_hash') or '').strip()
                record_id = str(row.get('id') or row.get('_id') or '').strip()
                if text_hash and record_id and text_hash not in existing_ids:
                    existing_ids[text_hash] = record_id

        now = time.time()
        payloads: list[EmbeddingCachePayload] = []
        for text_hash, (text, vector_list) in unique_payloads.items():
            payload: EmbeddingCachePayload = {
                'text_hash': text_hash,
                'text_content': text[:256],
                'vector_json': vector_list,
                'dims': len(vector_list),
                'accessed_at': now,
            }
            existing_id = existing_ids.get(text_hash)
            if existing_id:
                payload['id'] = existing_id
            payloads.append(payload)
        return payloads

    async def _flush_payload_batches(self, payload_batches: Sequence[Sequence[EmbeddingCachePayload]]) -> None:
        merged: dict[str, EmbeddingCachePayload] = {}
        for payload_batch in payload_batches:
            for payload in payload_batch:
                text_hash = str(payload.get('text_hash') or payload.get('id') or payload.get('_id') or '')
                if not text_hash:
                    continue
                merged[text_hash] = dict(payload)
        if not merged:
            return
        await EmbeddingCacheRecord.BatchSave(list(merged.values()), client=self._get_client())

    async def lookup(self, text: str) -> list[float] | None:
        '''Return cached vector for *text*, or ``None`` on miss.'''
        h = hashlib.sha256(text.encode()).hexdigest()
        try:
            client = self._get_client()
            rec = await client.search_one(EmbeddingCacheRecord, {'text_hash': h})
            if rec is None:
                return None
            now = time.time()
            last_accessed = float(rec.accessed_at or 0.0)
            if now - last_accessed > self._ACCESSED_AT_UPDATE_THRESHOLD_SECONDS:
                rec.accessed_at = now
                try:
                    await client.set(rec)
                except Exception:
                    pass
            vector = rec.vector_json
            if isinstance(vector, str):
                vector = json.loads(vector)
            return [float(v) for v in vector]
        except Exception as exc:
            _logger.debug('Embedding cache lookup failed: %s', exc)
            return None

    async def lookup_batch(self, texts: Sequence[str]) -> dict[str, list[float]]:
        '''Return cached vectors for *texts* using one backend query when possible.'''
        if not texts:
            return {}

        hash_to_texts: dict[str, list[str]] = {}
        for text in texts:
            h = hashlib.sha256(text.encode()).hexdigest()
            hash_to_texts.setdefault(h, []).append(text)

        try:
            client = self._get_client()
            rows: list[EmbeddingCachePayload] = []
            selected_search = getattr(client, 'selected_search', None)
            if callable(selected_search):
                async for row in selected_search(
                    EmbeddingCacheRecord,
                    fields=('text_hash', 'vector_json'),
                    query={'text_hash': {'$in': list(hash_to_texts)}},
                    limit=len(hash_to_texts),
                ):  # type: ignore
                    if isinstance(row, dict):
                        rows.append(row)
            else:
                async for row in client.search(
                    EmbeddingCacheRecord,
                    {'text_hash': {'$in': list(hash_to_texts)}},
                    limit=len(hash_to_texts),
                    as_model=False,
                ):
                    if isinstance(row, dict):
                        rows.append(row)

            found: dict[str, list[float]] = {}
            for row in rows:
                text_hash = str(row.get('text_hash') or '').strip()
                vector_json = row.get('vector_json')
                if not text_hash or not vector_json:
                    continue
                if isinstance(vector_json, str):
                    try:
                        parsed = json.loads(vector_json)
                    except Exception:
                        continue
                else:
                    parsed = vector_json
                if not isinstance(parsed, list):
                    continue
                vector = [float(value) for value in parsed]
                for text in hash_to_texts.get(text_hash, ()): 
                    found[text] = list(vector)
            return found
        except Exception as exc:
            _logger.debug('Embedding cache batch lookup failed: %s', exc)
            return {}

    async def store(self, text: str, vector: list[float]) -> None:
        '''Upsert a single text→vector entry.'''
        try:
            await self.store_batch([text], [vector])
        except Exception as exc:
            _logger.debug('Embedding cache store failed: %s', exc)

    async def enqueue_store_batch(self, owner: ServiceClientBase, texts: Sequence[str], vectors: Sequence[list[float]]) -> None:
        payloads = await self._build_store_payloads(texts, vectors)
        if not payloads:
            return
        owner.queue_cache_save(
            merge_key=f'embedding-cache:{id(self._get_client())}',
            payload=payloads,
            flush_many=self._flush_payload_batches,
        )

    async def store_batch(self, texts: Sequence[str], vectors: Sequence[list[float]]) -> None:
        '''Batch upsert.'''
        try:
            payloads = await self._build_store_payloads(texts, vectors)
            if not payloads:
                return
            await self._flush_payload_batches([payloads])
        except Exception as exc:
            _logger.debug('Embedding cache batch store failed: %s', exc)

    async def stats(self) -> 'EmbeddingCacheStats':
        '''Return cache statistics.'''
        try:
            client = self._get_client()
            records = [item async for item in client.dump_collection(EmbeddingCacheRecord)]
            return {'count': len(records), 'backend': 'orm'}
        except Exception as exc:
            return {'count': None, 'backend': 'orm', 'error': str(exc) or exc.__class__.__name__}

    async def clear(self) -> int:
        '''Drop all cached entries; return number cleared.'''
        try:
            client = self._get_client()
            records = [item async for item in client.dump_collection(EmbeddingCacheRecord)]
            count = len(records)
            await client.drop_collection(EmbeddingCacheRecord)
            return count
        except Exception:
            return 0

    def close(self) -> None:
        '''No-op — lifecycle managed by StorageConfig.'''
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Text tidying for embedding
# ══════════════════════════════════════════════════════════════════════════════

def _tidy_text(text: str, *, zh_tw_to_cn: bool = True) -> str:
    '''标准化文本：去除首尾空白；可选地将繁体中文转为简体。'''
    text = text.strip()
    if not text:
        return text
    if not zh_tw_to_cn or text.isascii():
        return text
    try:
        return translate_chinese(text, ZHTranslationType.Trad2Sim)
    except Exception:
        return text

# ══════════════════════════════════════════════════════════════════════════════
# Overflow handling types
# ══════════════════════════════════════════════════════════════════════════════

OverflowHandleMode = Literal['chunk', 'truncate', 'raise', 'ignore']
'''当文本超出 max_tokens 时的处理策略：

* ``chunk``    — 切成多段分别嵌入，然后加权平均并归一化。
* ``truncate`` — 粗略截断到估算限制长度后嵌入。
* ``raise``    — 抛出 ``ValueError``。
* ``ignore``   — 忽略溢出，直接传给客户端（默认）。
'''

class _EmbeddingRequestParams(ServiceParamsBase, total=False):
    '''Embedding 请求参数。'''
    timeout: _AnnotateDefault[float | None, _DEFAULT_EMBEDDING_TIMEOUT]
    '''请求超时（秒）。默认 60 秒。'''
    zh_tw_to_cn: _AnnotateDefault[bool, True]
    '''当 ``True`` (默认) 时，在 tidy-text 阶段自动将繁体中文转为简体。'''
    on_overflow: _AnnotateDefault[OverflowHandleMode, 'ignore']
    '''文本超出客户端 ``max_tokens`` 时的处理方式（默认 ``'ignore'``）。'''
    use_cache: _AnnotateDefault[bool, True]
    '''是否读取 embedding 缓存（默认 ``True``）。'''
    save_cache: _AnnotateDefault[bool, True]
    '''是否将新结果写入 embedding 缓存（默认 ``True``）。'''

if TYPE_CHECKING:
    class EmbeddingRequestParams(_EmbeddingRequestParams, extra_items=object):
        '''Embedding 请求参数。'''
else:
    EmbeddingRequestParams = _EmbeddingRequestParams


class EmbeddingCacheStats(TypedDict, total=False):
    count: int | None
    backend: str
    error: str

# ══════════════════════════════════════════════════════════════════════════════
# EmbeddingClient
# ══════════════════════════════════════════════════════════════════════════════
class EmbeddingHealthProbeInput(TypedDict):
    '''Embedding 健康探测最小输入。'''
    inputs: Sequence[str | Image | Audio | Video]
    '''用于最小探测的输入序列。'''
    kwargs: EmbeddingRequestParams
    '''探测时附带的额外参数。'''

class EmbeddingClientInitParams(ServiceClientInitParams, total=False):
    '''Embedding 客户端初始化参数。'''
    model: str | None
    '''模型名称或标识符，供客户端内部使用（如 API 请求参数）。'''
    max_tokens: int | None
    '''该客户端单次输入所能接受的最大 token 数；``None`` 表示无限制。'''
    token_counter: Callable[[TokenCountable], int] | None
    '''自定义 token 估算器；提供时优先于默认启发式估算。'''
    support_image: bool
    '''客户端是否原生支持图像输入。'''
    support_audio: bool
    '''客户端是否原生支持音频输入。'''
    support_video: bool
    '''客户端是否原生支持视频输入。'''

class EmbeddingClient(ServiceClientBase[EmbeddingHealthProbeInput]):

    ServiceKind: ClassVar['AIServiceKind'] = 'embedding'
    '''向量嵌入客户端抽象基类。'''

    support_image: bool = False
    '''客户端是否原生支持图像输入。'''
    support_audio: bool = False
    '''客户端是否原生支持音频输入。'''
    support_video: bool = False
    '''客户端是否原生支持视频输入。'''
    max_tokens: int | None = None
    '''该客户端单次输入所能接受的最大 token 数；``None`` 表示无限制。'''
    token_counter: Callable[[TokenCountable], int] | None = None
    '''可选的自定义 token 估算器。'''
    _IGNORED_SERVICE_KWARGS = ('use_cache', 'save_cache', 'zh_tw_to_cn', 'on_overflow')

    def __init__(self, **kwargs: Unpack[EmbeddingClientInitParams]):
        '''初始化 Embedding 客户端。

        Args:
            **kwargs: 客户端初始化参数，结构见 `EmbeddingClientInitParams`。
        '''
        self.max_tokens = kwargs.get('max_tokens')
        self.token_counter = kwargs.get('token_counter')
        self.support_image = bool(kwargs.get('support_image', False))
        self.support_audio = bool(kwargs.get('support_audio', False))
        self.support_video = bool(kwargs.get('support_video', False))
        super().__init__(
            key=kwargs.get('key'),
            max_concurrent=kwargs.get('max_concurrent'),
            priority=kwargs.get('priority', 0.0),
            strategy_lvl=kwargs.get('strategy_lvl', StrategyLevel.LOAD_BALANCE),
        )

    def count_tokens(self, value: str | Image | Audio | Video) -> int:
        '''估算文本/多模态输入的 token 数量。
        基类使用 :func:`~core.utils.text_utils.detect.word_count`
        启发式方法进行估算。若子类绑定了实际 tokenizer，应覆盖此方法以取得
        更精确的结果。
        
        Args:
            value: 待估算的文本或多模态输入。
        Returns:
            估算的 token 数量（整数）。
        '''
        if self.token_counter is not None:
            try:
                counted = int(self.token_counter(value))
                if counted >= 0:
                    return counted
            except Exception:
                pass
        return estimate_multimodal_tokens(value)

    def _log_request_payload(self, operation: str, args: tuple[object, ...], kwargs: dict[str, object]) -> object:
        inputs = args[0] if args else kwargs.get('inputs', [])
        return {
            'inputs': inputs,
            'kwargs': kwargs,
        }

    def _log_response_payload(self, operation: str, result: object) -> object:
        if not isinstance(result, list):
            return result
        vector_count = len(result)
        first_vector = result[0] if result else []
        first_dims = len(first_vector) if isinstance(first_vector, list) else 0
        preview = first_vector[:8] if isinstance(first_vector, list) else []
        return {
            'vector_count': vector_count,
            'first_vector_dims': first_dims,
            'first_vector_preview': preview,
        }

    @classmethod
    @cache
    def TestingInput(cls) -> EmbeddingHealthProbeInput:
        '''返回最小健康探测输入。

        Returns:
            适用于 embedding 最小可用性检测的输入参数。
        '''
        return {
            'inputs': ['ping'],
            'kwargs': {'use_cache': False, 'save_cache': False, 'timeout': 8.0},
        }

    async def probe_min_health(self) -> bool:
        '''执行最小健康探测。

        Returns:
            成功返回非空向量结果时为 `True`。
        '''
        try:
            probe = type(self).TestingInput()
            vectors = await self.embedding(probe['inputs'], __skip_log__=True, **probe.get('kwargs', {}))
            return bool(vectors)
        except Exception:
            return False

    async def embedding(self, inputs: Sequence[str | Image | Audio | Video], **kwargs: Unpack[EmbeddingRequestParams]) -> list[list[float]]:
        '''执行向量嵌入。

        Args:
            inputs: 待编码的输入序列。
            **kwargs: 传递给底层客户端的附加参数。

        Returns:
            二维向量列表，每个输入对应一个向量。
        '''
        exec_kwargs = cast(dict[str, object], kwargs.copy())
        skip_log = bool(exec_kwargs.pop('__skip_log__', False))
        _apply_service_param_defaults(exec_kwargs, _EmbeddingRequestParams)
        req_timeout = float(exec_kwargs.pop('timeout'))
        log_kwargs = exec_kwargs.copy()
        for key in self._IGNORED_SERVICE_KWARGS:
            log_kwargs.pop(key, None)
        request = self._log_request_payload('embedding', (inputs,), log_kwargs.copy())
        metadata = self._log_extra_metadata('embedding', (inputs,), log_kwargs.copy())
        for key in self._IGNORED_SERVICE_KWARGS:
            exec_kwargs.pop(key, None)
        return cast(
            list[list[float]],
            await self._trace_async_call(
                'embedding',
                lambda: asyncio.wait_for(self._embedding_impl(inputs, **exec_kwargs), timeout=req_timeout),
                request=request,
                metadata=metadata,
                skip_log=skip_log,
            ),
        )

    async def _embedding_impl(self, inputs: Sequence[str | Image | Audio | Video], **kwargs: object) -> list[list[float]]:
        raise NotImplementedError

class ThinkThinkSynEmbeddingClient(EmbeddingClient, type='tts-embedding'):
    '''ThinkThinkSyn 向量嵌入客户端。'''

    _DEFAULT_MODEL = 'zpoint'
    _REQUEST_MODEL_ALIASES = {
        'iampanda/zpoint_large_embedding_zh': 'zpoint',
    }

    def __init__(
        self,
        tts_client: 'ThinkThinkSyn',
        ssh_tunnel: object | None = None,
        **kwargs: Unpack[EmbeddingClientInitParams],
    ):
        super().__init__(**kwargs)
        _ssh = _resolve_ssh_tunnel_config(ssh_tunnel)
        if _ssh:
            _apply_ssh_tunnel_to_tts_client(tts_client, _ssh)
        self._tts_client = _patch_thinkthinksyn_proxy(tts_client)
        self._model = self._normalize_request_model_name(kwargs.get('model') or self._DEFAULT_MODEL) or self._DEFAULT_MODEL
        self._resolved_embedding_model: object | None = None  # cached EmbeddingModel instance
        self._request_model_name: str | None = None

    @property
    def model(self) -> str | None:
        return self._model

    @classmethod
    @cache
    def _embedding_model_lookup(cls) -> EmbeddingModelLookup:
        mapping: EmbeddingModelLookup = {}
        try:
            from thinkthinksyn.data_types import EmbeddingModel
        except Exception:
            return mapping

        pending = list(EmbeddingModel.__subclasses__())
        seen: set[type[object]] = set()
        while pending:
            model_cls = pending.pop()
            if model_cls in seen:
                continue
            seen.add(model_cls)
            pending.extend(model_cls.__subclasses__())
            canonical = str(getattr(model_cls, 'Name', '') or '').strip()
            aliases = tuple(
                str(item).strip()
                for item in (getattr(model_cls, 'Alias', ()) or ())
                if str(item).strip()
            )
            request_name = aliases[0] if canonical and '/' in canonical and aliases else (canonical or (aliases[0] if aliases else ''))
            if not request_name:
                continue
            for key in {canonical, model_cls.__name__, *aliases}:
                normalized = str(key or '').strip()
                if normalized:
                    mapping[normalized.casefold()] = (request_name, model_cls)
        return mapping

    @classmethod
    def _normalize_request_model_name(cls, model_name: object) -> str | None:
        candidate = str(model_name or '').strip()
        if not candidate:
            return None
        direct_alias = cls._REQUEST_MODEL_ALIASES.get(candidate.casefold())
        if direct_alias:
            return direct_alias
        resolved = cls._embedding_model_lookup().get(candidate.casefold())
        if resolved is not None:
            return resolved[0]
        if candidate.casefold().endswith('/zpoint_large_embedding_zh'):
            return 'zpoint'
        return candidate

    def _get_request_model_name(self) -> str | None:
        if self._request_model_name is not None:
            return self._request_model_name
        candidate = str(self._model or '').strip()
        if not candidate:
            return None
        resolved = self._embedding_model_lookup().get(candidate.casefold())
        if resolved is None:
            self._request_model_name = self._normalize_request_model_name(candidate)
            return self._request_model_name
        request_name, model_cls = resolved
        self._resolved_embedding_model = model_cls
        self._request_model_name = request_name
        return self._request_model_name

    def _batch_request_concurrency_limit(self) -> int | None:
        max_concurrent = getattr(self, 'max_concurrent', None)
        if isinstance(max_concurrent, ConcurrentPool):
            return max(1, int(max_concurrent.max_concurrent))
        if isinstance(max_concurrent, int) and max_concurrent > 0:
            return max(1, int(max_concurrent))
        return None

    async def _embedding_impl(self, inputs: Sequence[str | Image | Audio | Video], **kwargs: object) -> list[list[float]]:
        params = cast(dict[str, object], kwargs.copy())
        text_inputs = [str(inp) if not isinstance(inp, str) else inp for inp in inputs]
        request_model = self._get_request_model_name() or self._DEFAULT_MODEL
        shared_session = params.pop('session', None)
        if shared_session is None:
            shared_session = await self._get_session()

        async def _embed_single(text: str, *, session: object | None = None) -> list[float]:
            output = await self._tts_client.embedding(request_model, text=text, session=session, **params)
            return self._parse_embedding_output(output)

        if len(text_inputs) == 1:
            return [await _embed_single(text_inputs[0], session=shared_session)]

        concurrency_limit = self._batch_request_concurrency_limit()

        async def _run_batch(session: object | None) -> list[list[float]]:
            if concurrency_limit is not None and concurrency_limit < len(text_inputs):
                semaphore = asyncio.Semaphore(concurrency_limit)

                async def _embed_single_limited(text: str) -> list[float]:
                    async with semaphore:
                        return await _embed_single(text, session=session)
            else:
                async def _embed_single_limited(text: str) -> list[float]:
                    return await _embed_single(text, session=session)

            tasks = [asyncio.create_task(_embed_single_limited(text)) for text in text_inputs]
            try:
                results = await asyncio.gather(*tasks)
                return list(results)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        return await _run_batch(shared_session)

    @staticmethod
    def _parse_embedding_output(output: object) -> list[float]:
        '''Parse a single embedding response into a float vector.'''
        data: object = output
        if hasattr(output, 'model_dump'):
            data = output.model_dump()
        elif hasattr(output, '__dict__'):
            data = output.__dict__

        if isinstance(data, dict):
            # Try standard response shapes: {data: [{embedding: [...]}]} or {embeddings: [[...]]}
            rows = data.get('data', data.get('embeddings', []))
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        emb = row.get('embedding')
                        if isinstance(emb, list):
                            return [float(v) for v in emb]
                    elif isinstance(row, list):
                        return [float(v) for v in row]
            # Direct vector in 'embedding' key
            emb = data.get('embedding')
            if isinstance(emb, list):
                return [float(v) for v in emb]
        elif isinstance(data, list):
            return [float(v) for v in data]
        return []

class EmbeddingService(ServiceBase):
    '''向量嵌入聚合服务，支持缓存、文本整理、多模态回退、以及高级方法（rerank / chunking / diversity_rerank）。'''

    class ThinkThinkSynDefaultClientParams:
        '''ThinkThinkSyn embedding 默认客户端参数。'''
        ZPoint: EmbeddingClientInitParams = {
            'max_tokens': 512,
            'max_concurrent': ConcurrentPool('embedding', 50),
            'model': 'zpoint',
        }

    def __init__(
        self,
        *clients: EmbeddingClient | ServiceClient[EmbeddingClient],
        completion_service: 'CompletionService | None' = None,
        s2t_service: 'S2TService | None' = None,
        **kwargs: Unpack[ServiceInitParams],
    ):
        '''初始化 Embedding 聚合服务。

        Args:
            *clients: 一个或多个 embedding 客户端。
            completion_service: 可选的 CompletionService，用于 OCR/ASR 等多模态回退。
            s2t_service: 可选的 S2TService，用于语音转文字回退。
            **kwargs: 服务初始化参数，结构见 `ServiceInitParams`。
        '''
        if not clients:
            raise ValueError('EmbeddingService requires at least one client.')
        super().__init__(*clients, **kwargs)
        self._completion_service = completion_service
        self._s2t_service = s2t_service
        self._cache = _ORMEmbeddingCache()
        self._start_init_probe()

    @classmethod
    def Default(cls) -> 'EmbeddingService':
        '''创建默认 Embedding 服务。

        Returns:
            使用默认 ThinkThinkSyn 客户端的 Embedding 服务实例。
        '''
        cls.WaitUntilRuntimeReady()
        if existing := cls.GetInstance('default'):
            return existing

        # ── Config-driven creation ───────────────────────────────────────
        from .config import AIServicesConfig
        cfg = AIServicesConfig.Global()
        if cfg is not None:
            svc = cfg.embedding.get_default()
            if svc is not None:
                for ek in cfg.embedding.extras:
                    cfg.embedding.get_service(ek)
                return cast('EmbeddingService', svc)

        # ── Hardcoded fallback ───────────────────────────────────────────
        client = ThinkThinkSynEmbeddingClient(
            tts_client=thinkthinksyn_client(),
            **cls.ThinkThinkSynDefaultClientParams.ZPoint,
        )
        return cls(client, key='default')

    # ── Input normalization ───────────────────────────────────────────────

    async def _normalize_inputs(self, inputs: Sequence[str | Image | Audio | Video | LLMDocumentMixin] | str | Image | Audio | Video | LLMDocumentMixin) -> list[str | Image | Audio | Video]:
        src = [inputs] if isinstance(inputs, (str, Image, Audio, Video, LLMDocumentMixin)) else list(inputs)
        normalized: list[str | Image | Audio | Video] = []
        for item in src:
            if isinstance(item, LLMDocumentMixin):
                expanded_result = item.to_llm(mode='image')
                if inspect.isawaitable(expanded_result):
                    expanded_result = await expanded_result
                for expanded in expanded_result:
                    if isinstance(expanded, (str, Image, Audio, Video)):
                        normalized.append(expanded)
            else:
                normalized.append(item)
        return normalized

    # ── Multimodal fallback ───────────────────────────────────────────────

    async def _convert_to_text(self, item: Image | Audio | Video) -> str:
        '''将非文本输入转换为文本。不支持时返回空字符串。'''
        _ctx = get_inference_context()

        def _can_use(service_kind: AIServiceKind) -> bool:
            return _ctx is None or not _ctx.is_active(service_kind)

        def _lazy_completion() -> 'CompletionService | None':
            if self._completion_service is not None:
                return self._completion_service
            if not _can_use('completion'):
                return None
            try:
                from .completion import CompletionService as _CompletionService
                self._completion_service = _CompletionService.Default()
                return self._completion_service
            except Exception:
                return None

        def _lazy_s2t() -> 'S2TService | None':
            if self._s2t_service is not None:
                return self._s2t_service
            if not _can_use('s2t'):
                return None
            try:
                from .s2t import S2TService as _S2TService
                self._s2t_service = _S2TService.Default()
                return self._s2t_service
            except Exception:
                return None

        if isinstance(item, Image):
            completion_svc = _lazy_completion()
            if completion_svc:
                try:
                    return await completion_svc.ocr(item, stream=False)
                except Exception as e:
                    _logger.warning('OCR fallback failed for image: %s', e)
            return ''

        if isinstance(item, (Audio, Video)):
            # Try S2T service first (specialized)
            s2t_svc = _lazy_s2t()
            if s2t_svc:
                try:
                    return await s2t_svc.s2t(item)
                except Exception:
                    pass
            # Fallback: use completion ASR
            completion_svc = _lazy_completion()
            if completion_svc:
                try:
                    return await completion_svc.asr(item, stream=False)
                except Exception as e:
                    _logger.warning('ASR fallback failed for %s: %s', type(item).__name__.lower(), e)
            return ''

        return ''

    async def _prepare_inputs(self, normalized: list[str | Image | Audio | Video], client: EmbeddingClient) -> list[str | Image | Audio | Video]:
        '''根据客户端能力对不支持的模态做文本回退。'''
        result: list[str | Image | Audio | Video] = []
        for item in normalized:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, Image) and not client.support_image:
                text = await self._convert_to_text(item)
                result.append(text if text else '[image]')
            elif isinstance(item, Audio) and not client.support_audio:
                text = await self._convert_to_text(item)
                result.append(text if text else '[audio]')
            elif isinstance(item, Video) and not client.support_video:
                text = await self._convert_to_text(item)
                result.append(text if text else '[video]')
            else:
                result.append(item)
        return result

    async def _fit_item_to_token_limit(
        self,
        item: str | Image | Audio | Video,
        client: EmbeddingClient,
        *,
        on_overflow: OverflowHandleMode,
    ) -> str | Image | Audio | Video | list[str] | list[Audio] | list[Video]:
        if client.max_tokens is None:
            return item

        token_count = client.count_tokens(item)
        if token_count <= client.max_tokens:
            return item

        if isinstance(item, str):
            if on_overflow == 'raise':
                raise ValueError(
                    f'Text has {token_count} tokens which exceeds max_tokens={client.max_tokens}.'
                )
            if on_overflow == 'truncate':
                return truncate_text_by_word_count(item, client.max_tokens)
            if on_overflow == 'chunk':
                return [chunk['text'] for chunk in split_text_by_word_count(item, max_word_count=client.max_tokens)]
            return item

        if isinstance(item, Image):
            return compress_image_to_token_budget(item, client.max_tokens)

        if isinstance(item, Audio):
            segments = split_audio_on_silence(item, target_max_tokens=client.max_tokens)
            useful_segments = [
                trim_audio_to_token_budget(seg, client.max_tokens)
                for seg in segments
                if client.count_tokens(seg) > 0
            ]
            if len(useful_segments) > 1:
                return useful_segments
            trimmed = trim_audio_to_token_budget(item, client.max_tokens)
            if client.count_tokens(trimmed) <= client.max_tokens:
                return trimmed
            fallback_text = await self._convert_to_text(item)
            if fallback_text:
                return await self._fit_item_to_token_limit(fallback_text, client, on_overflow=on_overflow)
            return item

        if isinstance(item, Video):
            segments = split_video_to_token_budget(item, client.max_tokens)
            useful_segments = [
                trim_video_to_token_budget(seg, client.max_tokens, preserve_tail=False)
                for seg in segments
                if client.count_tokens(seg) > 0
            ]
            if len(useful_segments) > 1:
                return useful_segments
            trimmed = trim_video_to_token_budget(item, client.max_tokens, preserve_tail=True)
            if client.count_tokens(trimmed) <= client.max_tokens:
                return trimmed
            fallback_text = await self._convert_to_text(item)
            if fallback_text:
                return await self._fit_item_to_token_limit(fallback_text, client, on_overflow=on_overflow)
            return item

        return item

    # ── Text tidying ──────────────────────────────────────────────────────

    def _tidy_inputs(self, inputs: list[str | Image | Audio | Video], *, zh_tw_to_cn: bool = True) -> list[str | Image | Audio | Video]:
        '''对纯文本输入执行整理（strip；可选繁→简）。'''
        return [_tidy_text(item, zh_tw_to_cn=zh_tw_to_cn) if isinstance(item, str) else item for item in inputs]

    # ── Cache-aware batch embedding ───────────────────────────────────────

    async def _embed_batch_cached(
        self,
        items: Sequence[str | Image | Audio | Video],
        client: EmbeddingClient,
        *,
        use_cache: bool,
        save_cache: bool,
        **client_kwargs: object,
    ) -> list[list[float]]:
        '''带缓存的批量 embedding（供内部各路径复用）。'''
        cache_store = self._cache if (use_cache or save_cache) else None
        if cache_store and all(isinstance(item, str) for item in items):
            text_items = [cast(str, item) for item in items]
            cached_results: dict[int, list[float]] = {}
            to_embed_indices: list[int] = []
            to_embed_texts: list[str] = []

            cached_by_text: dict[str, list[float]] = {}
            if use_cache:
                lookup_batch = getattr(cache_store, 'lookup_batch', None)
                if callable(lookup_batch):
                    batch_cached = await lookup_batch(text_items)   # type: ignore
                    if isinstance(batch_cached, dict):  
                        cached_by_text = {
                            str(text): [float(v) for v in vector]
                            for text, vector in batch_cached.items()
                            if isinstance(vector, list)
                        }

            for i, text in enumerate(text_items):
                if use_cache:
                    cached = cached_by_text.get(text)
                    if cached is None and not cached_by_text:
                        cached = await cache_store.lookup(text)
                    if cached is not None:
                        cached_results[i] = cached
                        continue
                to_embed_indices.append(i)
                to_embed_texts.append(text)

            if not to_embed_texts:
                return [cached_results[i] for i in range(len(text_items))]

            new_vectors = await client.embedding(to_embed_texts, **client_kwargs)
            if save_cache:
                enqueue_store_batch = getattr(cache_store, 'enqueue_store_batch', None)
                if isinstance(client, ServiceClientBase) and callable(enqueue_store_batch):
                    await enqueue_store_batch(client, to_embed_texts, new_vectors)  # type: ignore
                else:
                    await cache_store.store_batch(to_embed_texts, new_vectors)

            all_vectors: list[list[float]] = [[] for _ in range(len(text_items))]
            for i, vec in cached_results.items():
                all_vectors[i] = vec
            for idx, vec in zip(to_embed_indices, new_vectors):
                all_vectors[idx] = vec
            return all_vectors

        return await client.embedding(items, **client_kwargs)

    # ── Core embedding ────────────────────────────────────────────────────

    @overload
    async def embedding(
        self,
        inputs: str | Image | Audio | Video | LLMDocumentMixin,
        **kwargs: Unpack[EmbeddingRequestParams],
    ) -> list[float]:
        ...

    @overload
    async def embedding(
        self,
        inputs: Sequence[str | Image | Audio | Video | LLMDocumentMixin],
        **kwargs: Unpack[EmbeddingRequestParams],
    ) -> list[list[float]]:
        ...

    async def embedding(
        self,
        inputs: Sequence[str | Image | Audio | Video | LLMDocumentMixin] | str | Image | Audio | Video | LLMDocumentMixin,
        **kwargs: object,  # overload impl — callers see Unpack[EmbeddingRequestParams]
    ) -> list[float] | list[list[float]]:
        '''通过故障转移机制执行向量嵌入，自动使用缓存、文本整理和多模态回退。

        除了传递给底层客户端的参数，还支持以下 :class:`EmbeddingRequestParams` 参数：

        * **zh_tw_to_cn** (``bool``, 默认 ``True``) — tidy-text 时自动繁→简转换。
        * **on_overflow** (:data:`OverflowHandleMode`, 默认 ``'ignore'``) —
          当文本 token 数超出客户端 ``max_tokens`` 时的处理方式。

        Args:
            inputs: 单个输入或输入序列；文档对象会先展开成适合 embedding 的内容序列。
            **kwargs: :class:`EmbeddingRequestParams` 控制参数 + 传递给客户端的附加参数。

        Returns:
            二维向量列表，顺序与输入对应。
        '''
        # Apply defaults & extract embedding-specific params — these are NOT forwarded to the client
        _apply_service_param_defaults(kwargs, _EmbeddingRequestParams)
        zh_tw_to_cn: bool = bool(kwargs.pop('zh_tw_to_cn'))
        on_overflow: OverflowHandleMode = cast(OverflowHandleMode, kwargs.pop('on_overflow'))
        use_cache: bool = bool(kwargs.pop('use_cache'))
        save_cache: bool = bool(kwargs.pop('save_cache'))
        kwargs.pop('timeout', None)  # timeout is consumed at client level, not service level
        single_input = isinstance(inputs, (str, Image, Audio, Video, LLMDocumentMixin))

        normalized = await self._normalize_inputs(inputs)
        normalized = self._tidy_inputs(normalized, zh_tw_to_cn=zh_tw_to_cn)

        if not normalized:
            return []

        _ctx, _ctx_token = enter_service_context('embedding')

        async def _action(client: EmbeddingClient) -> list[float] | list[list[float]]:
            prepared = await self._prepare_inputs(normalized, client)
            prepared_plans: list[str | Image | Audio | Video | list[str] | list[Audio] | list[Video]] = []
            for item in prepared:
                prepared_plans.append(await self._fit_item_to_token_limit(item, client, on_overflow=on_overflow))

            if any(isinstance(plan, list) for plan in prepared_plans):
                result_vectors: list[list[float]] = [[] for _ in range(len(prepared_plans))]
                normal_indices = [i for i, plan in enumerate(prepared_plans) if not isinstance(plan, list)]

                if normal_indices:
                    normal_items = [cast(str | Image | Audio | Video, prepared_plans[i]) for i in normal_indices]
                    normal_vecs = await self._embed_batch_cached(
                        normal_items,
                        client,
                        use_cache=use_cache,
                        save_cache=save_cache,
                        **kwargs,
                    )
                    for idx, vec in zip(normal_indices, normal_vecs):
                        result_vectors[idx] = vec

                for i, plan in enumerate(prepared_plans):
                    if not isinstance(plan, list) or not plan:
                        continue
                    chunk_vecs = await self._embed_batch_cached(
                        plan,
                        client,
                        use_cache=use_cache,
                        save_cache=save_cache,
                        **kwargs,
                    )
                    weights = [max(1.0, float(client.count_tokens(item))) for item in plan]
                    result_vectors[i] = _weighted_average_normalize(chunk_vecs, weights)

                prepared_item_weights = [
                    max(1.0, sum(float(client.count_tokens(item)) for item in plan)) if isinstance(plan, list)
                    else max(1.0, float(client.count_tokens(plan)))
                    for plan in prepared_plans
                ]
                if single_input:
                    return _weighted_average_normalize(result_vectors, prepared_item_weights)
                return result_vectors

            prepared_final = [cast(str | Image | Audio | Video, plan) for plan in prepared_plans]
            prepared_item_weights = [max(1.0, float(client.count_tokens(item))) for item in prepared_final]

            # ── Normal path (no overflow expansion needed) ─────────────────
            vectors = await self._embed_batch_cached(
                prepared_final,
                client,
                use_cache=use_cache,
                save_cache=save_cache,
                **kwargs,
            )
            if single_input:
                return _weighted_average_normalize(vectors, prepared_item_weights)
            return vectors

        try:
            return await self._run_with_failover(self.clients, _action, error_prefix='All embedding clients failed')
        finally:
            exit_service_context(_ctx_token)

    # ── Cache management ──────────────────────────────────────────────────

    async def cache_stats(self) -> EmbeddingCacheStats:
        '''返回 embedding 缓存统计。'''
        return await self._cache.stats()

    async def cache_clear(self) -> int:
        '''清空 embedding 缓存，返回删除条目数。'''
        return await self._cache.clear()

    def cache_close(self) -> None:
        '''关闭 embedding 缓存连接。'''
        self._cache.close()

    # ── Advanced: embedding-based rerank ──────────────────────────────────

    async def rerank(
        self,
        query: str,
        candidates: Sequence[str],
        **kwargs: Unpack[EmbeddingRequestParams],
    ) -> list[EmbeddingRerankItem]:
        '''基于嵌入余弦相似度对候选项排序。

        Args:
            query: 查询文本。
            candidates: 候选文本列表。
            **kwargs: 传递给 embedding 的附加参数。

        Returns:
            按相似度降序排列的 `EmbeddingRerankItem` 列表。
        '''
        if not candidates:
            return []

        # Defensive: candidates identical to the query get cosine similarity 1.0 directly
        query_stripped = query.strip()
        exact_match_indices: set[int] = set()
        rerank_candidate_texts: list[str] = []
        rerank_original_indices: list[int] = []
        for i, cand in enumerate(candidates):
            if isinstance(cand, str) and cand.strip() == query_stripped:
                exact_match_indices.add(i)
            else:
                rerank_candidate_texts.append(cand)
                rerank_original_indices.append(i)

        items: list[EmbeddingRerankItem] = []

        # Exact matches get the maximum score
        for i in exact_match_indices:
            items.append(EmbeddingRerankItem(index=i, score=1.0, candidate=candidates[i]))

        # Embed and score the remaining candidates
        if rerank_candidate_texts:
            all_texts = [query] + rerank_candidate_texts
            vectors = await self.embedding(all_texts, **kwargs)
            query_vec = vectors[0]
            for local_idx, original_idx in enumerate(rerank_original_indices):
                score = _cosine_similarity(query_vec, vectors[local_idx + 1])
                items.append(EmbeddingRerankItem(index=original_idx, score=score, candidate=candidates[original_idx]))

        items.sort(key=lambda x: x.score, reverse=True)
        return items

    # ── Advanced: text chunking with embedding ────────────────────────────

    async def chunking(
        self,
        content: str,
        *,
        max_word_count: int = 512,
        **kwargs: Unpack[EmbeddingRequestParams],
    ) -> list[EmbeddedChunk]:
        '''将长文本分块并对每块生成嵌入向量。

        Args:
            content: 原始长文本。
            max_word_count: 每块最大估算词数。
            **kwargs: 传递给 embedding 的附加参数。

        Returns:
            分块列表，每个含文本和对应向量。
        '''
        if not content.strip():
            return []

        chunks = split_text_by_word_count(content, max_word_count=max_word_count)
        if not chunks:
            return []

        texts = [c['text'] for c in chunks]
        vectors = await self.embedding(texts, **kwargs)

        result: list[EmbeddedChunk] = []
        for i, (ch, vec) in enumerate(zip(chunks, vectors)):
            result.append(EmbeddedChunk(
                text=ch['text'],
                vector=vec,
                index=i,
                offset=ch['offset'],
            ))
        return result

    # ── Advanced: diversity rerank ────────────────────────────────────────
    async def diversity_rerank(
        self,
        candidates: Sequence[str],
        *,
        top_k: int | None = None,
        **kwargs: Unpack[EmbeddingRequestParams],
    ) -> list[DiversityRerankItem]:
        '''贪心最大多样性选择——每步选与已选集合余弦距离最大的候选。

        Args:
            candidates: 候选文本列表。
            top_k: 选取的最大数量，None 为全部重排。
            **kwargs: 传递给 embedding 的附加参数。

        Returns:
            按多样性顺序排列的 `DiversityRerankItem` 列表。
        '''
        if not candidates:
            return []

        n = len(candidates)
        k = min(top_k or n, n)
        vectors = await self.embedding(list(candidates), **kwargs)

        selected: list[int] = []
        remaining = set(range(n))

        # First item: pick the one with highest norm (most "information")
        norms = [sum(v * v for v in vec) ** 0.5 for vec in vectors]
        first = max(remaining, key=lambda i: norms[i])
        selected.append(first)
        remaining.discard(first)

        # Track min-distance from each remaining point to selected set
        min_dists: dict[int, float] = {}
        for idx in remaining:
            min_dists[idx] = 1.0 - _cosine_similarity(vectors[idx], vectors[first])

        while len(selected) < k and remaining:
            # Pick candidate with maximum min-distance to selected set
            best = max(remaining, key=lambda i: min_dists.get(i, 0.0))
            selected.append(best)
            remaining.discard(best)

            # Update min-dists with new selected item
            best_vec = vectors[best]
            for idx in remaining:
                dist = 1.0 - _cosine_similarity(vectors[idx], best_vec)
                if dist < min_dists.get(idx, float('inf')):
                    min_dists[idx] = dist

        result: list[DiversityRerankItem] = []
        for order, idx in enumerate(selected):
            result.append(DiversityRerankItem(
                index=idx,
                candidate=candidates[idx],
                min_distance=min_dists.get(idx, 0.0) if order > 0 else 0.0,
            ))
        return result

# ══════════════════════════════════════════════════════════════════════════════
# Utility functions
# ══════════════════════════════════════════════════════════════════════════════
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    '''计算两个向量的余弦相似度。'''
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)

def _weighted_average_normalize(
    vectors: list[list[float]],
    weights: Sequence[float],
) -> list[float]:
    '''对向量列表做加权平均，然后 L2 归一化。

    用于将 overflow-chunk 模式下分块嵌入的多个向量合并回一个向量。

    Args:
        vectors: 向量列表，每个向量维度相同。
        weights: 与 ``vectors`` 等长的权重列表（例如各块的 token 数）。

    Returns:
        加权平均后 L2 归一化的单一向量。
    '''
    if not vectors:
        return []
    dims = len(vectors[0])
    result = [0.0] * dims
    total_w = sum(weights) or 1.0
    for vec, w in zip(vectors, weights):
        for i in range(dims):
            result[i] += vec[i] * (w / total_w)
    # L2 normalise
    norm = sum(x * x for x in result) ** 0.5
    if norm > 0:
        result = [x / norm for x in result]
    return result


__all__ += [
    'OverflowHandleMode',
    'EmbeddingRequestParams',
    'EmbeddingHealthProbeInput',
    'EmbeddingClientInitParams',
    'EmbeddingClient',
    'ThinkThinkSynEmbeddingClient',
    'EmbeddingService',
    'EmbeddedChunk',
    'EmbeddingRerankItem',
    'DiversityRerankItem',
]
