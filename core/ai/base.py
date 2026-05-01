import os

import json

import time

import asyncio

import hashlib

import inspect

import functools

import threading

import logging



import aiohttp



from weakref import WeakValueDictionary

import contextvars

from contextvars import ContextVar

from dataclasses import dataclass, field as _dataclass_field

from datetime import datetime

from queue import Queue, Empty as QueueEmpty



from urllib.parse import urlparse, urlunparse

from urllib.request import Request, urlopen

from urllib.error import URLError, HTTPError



from pathlib import Path

from enum import IntEnum

from abc import ABC, abstractmethod

from typing_extensions import Unpack

from pydantic import BaseModel

from pydantic.v1 import BaseModel as BaseModelV1

from thinkthinksyn import ThinkThinkSyn

from typing import (

    Annotated, Any, Awaitable, ClassVar, TypedDict, Sequence, NotRequired, Required, Literal, Callable, TYPE_CHECKING,

    Protocol, Generic, TypeVar, Self, cast, get_origin, get_args

)



from core.utils.concurrent_utils import async_run_any_func as _async_run_any_func, run_any_func as _run_any_func

from core.utils.network_utils.ssh_tunnel import SSHTunnelConfig

from core.utils.data_structs import Audio, Image, Video, PDF, Doc, Excel, HTML, PPT, RTF

from core.utils.data_structs.files.base import File as _FileProtocol

from .shared import AIServiceKind, ConcurrentPool, compute_client_hash



_base_logger = logging.getLogger(__name__)

_service_call_logger = logging.getLogger("app.ai.service_call")



if TYPE_CHECKING:

    from core.storage.orm import SQL_ORM_Client, ORMModel



__all__: list[str] = []



# region thinkthinksyn

_thinkthinksyn = None

_UNPROBED = object()

_cached_local_tts_url: str | None | object = _UNPROBED

_cached_tts_lock = threading.Lock()



class _ProxiedThinkThinkSyn(ThinkThinkSyn):

    '''通过代理包装 ThinkThinkSyn 的底层 HTTP/SSE 请求。'''



    _is_proxied_thinkthinksyn = True



    async def _request_ai(self, endpoint: str, payload: dict, return_type: type, session: Any | None = None) -> Any:

        from core.utils.network_utils.proxy_requests import aiohttp_client_session



        endpoint = endpoint.lstrip('/')

        headers = {'Authorization': f'Bearer {self.apikey}'} if self.apikey else {}

        payload['stream'] = False

        # ThinkThinkSyn's **payload kwargs may include 'session'; extract it

        # so json.dumps(payload) does not choke on the non-serializable object.

        session = payload.pop('session', None) or session



        if session is not None:

            async with session.post(self._ai_url(endpoint), json=payload, headers=headers) as response:

                response.raise_for_status()

                return await response.json()



        async with aiohttp_client_session() as created_session:

            async with created_session.post(self._ai_url(endpoint), json=payload, headers=headers) as response:

                response.raise_for_status()

                return await response.json()



    async def _stream_request_ai(self, endpoint: str, payload: dict, session: Any | None = None):  # type: ignore[override]

        from core.utils.network_utils.proxy_requests import aiosseclient_with_proxy



        endpoint = endpoint.lstrip('/')

        headers = {'Authorization': f'Bearer {self.apikey}'} if self.apikey else {}

        payload['stream'] = True

        session = payload.pop('session', None) or session

        async for event in aiosseclient_with_proxy(

            self._ai_url(endpoint), method='post', json=payload, headers=headers, session=session,

        ):

            yield event



def _patch_thinkthinksyn_proxy(tts_client: "ThinkThinkSyn") -> "ThinkThinkSyn":

    '''原地 patch ThinkThinkSyn 实例的 class，使其请求走代理包装。'''

    if getattr(type(tts_client), '_is_proxied_thinkthinksyn', False):

        return tts_client

    tts_client.__class__ = _ProxiedThinkThinkSyn

    return tts_client



def set_thinkthinksyn_client(tts_client: "ThinkThinkSyn") -> None:

    '''手动设定全局 ThinkThinkSyn 客户端实例。



    Args:

        tts_client: 要缓存为全局默认实例的 ThinkThinkSyn 客户端。

    '''

    global _thinkthinksyn

    _thinkthinksyn = _patch_thinkthinksyn_proxy(tts_client)



def _probe_single_tts_url(url: str) -> str | None:

    '''同步探测单个 TTS URL，成功或收到 HTTPError 均视为可用。'''

    try:

        req = Request(url, method='POST', data=b'')

        urlopen(req, timeout=2)

        return url

    except HTTPError:

        return url          # 服务在线，只是请求格式不对

    except (URLError, OSError):

        return None



async def _async_probe_tts_url(url: str) -> str | None:

    '''在线程池中并发探测单个 TTS URL。'''

    loop = asyncio.get_running_loop()

    return await loop.run_in_executor(None, _probe_single_tts_url, url)



async def _detect_local_tts_base_url_async() -> str | None:

    '''异步并发探测本地 ThinkThinkSyn 服务（asyncio.gather）。'''

    global _cached_local_tts_url

    with _cached_tts_lock:

        if _cached_local_tts_url is not _UNPROBED:

            return _cached_local_tts_url  # type: ignore[return-value]



    candidates = [

        'http://localhost:9194/tts/ai',

        'http://192.168.50.251:9194/tts/ai',

    ]

    results = await asyncio.gather(*[_async_probe_tts_url(u) for u in candidates])

    result = next((r for r in results if r is not None), None)

    with _cached_tts_lock:

        _cached_local_tts_url = result

    return result



def _detect_local_tts_base_url() -> str | None:

    '''尝试探测本地 ThinkThinkSyn 服务（sync wrapper，内部并发探测）。'''

    global _cached_local_tts_url

    with _cached_tts_lock:

        if _cached_local_tts_url is not _UNPROBED:

            return _cached_local_tts_url  # type: ignore[return-value]



    try:

        loop = asyncio.get_running_loop()

    except RuntimeError:

        loop = None



    if loop is not None and loop.is_running():

        # 已在事件循环中 — 不能 run_until_complete，改用线程池同步并发探测

        import concurrent.futures

        candidates = [

            'http://localhost:9194/tts/ai',

            'http://192.168.50.251:9194/tts/ai',

        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as pool:

            futures = {pool.submit(_probe_single_tts_url, u): u for u in candidates}

            for fut in concurrent.futures.as_completed(futures):

                result = fut.result()

                if result is not None:

                    with _cached_tts_lock:

                        _cached_local_tts_url = result

                    return result

        with _cached_tts_lock:

            _cached_local_tts_url = None

        return None



    # 没有正在运行的事件循环

    return _run_any_func(_detect_local_tts_base_url_async)



def _create_proxied_thinkthinksyn(**params: Any) -> "ThinkThinkSyn":

    '''创建带代理支持的 ThinkThinkSyn 实例。



    覆写底层 ``_request_ai`` 和 ``_stream_request_ai`` 方法，

    使所有 HTTP 请求（completion / embedding / t2s 等）自动通过

    ``aiohttp_client_session`` / ``aiosseclient_with_proxy`` 走代理。

    '''

    return _patch_thinkthinksyn_proxy(ThinkThinkSyn(**params))



def thinkthinksyn_client() -> "ThinkThinkSyn":

    '''获取全局 ThinkThinkSyn 客户端实例，如果尚未创建则根据环境变量初始化。



    Returns:

        可复用的全局 ThinkThinkSyn 客户端实例。



    Raises:

        ImportError: 当前环境未安装 `thinkthinksyn` 包时抛出。

    '''

    global _thinkthinksyn

    if _thinkthinksyn:

        _thinkthinksyn = _patch_thinkthinksyn_proxy(_thinkthinksyn)

        return _thinkthinksyn



    if 'TTS_APIKEY' in os.environ:

        apikey = os.environ['TTS_APIKEY']

    else:

        apikey = ''



    if 'TTS_API_BASEURL' in os.environ:

        api_url = os.environ['TTS_API_BASEURL']

    else:

        api_url = None



    if not api_url:

        api_url = _detect_local_tts_base_url()



    params: dict[str, Any] = {'apikey': apikey, 'base_url': api_url}

    if not apikey:

        params.pop('apikey')

    if not api_url:

        params.pop('base_url')



    _thinkthinksyn = _create_proxied_thinkthinksyn(**params)

    return _thinkthinksyn



__all__ += [

    'set_thinkthinksyn_client',

    'thinkthinksyn_client',

    '_patch_thinkthinksyn_proxy',

    '_create_proxied_thinkthinksyn',

]

# endregion





# region helpers

def _env_first(*keys: str) -> str | None:

    '''Return the value of the first environment variable found, or ``None``.'''

    for k in keys:

        v = os.environ.get(k)

        if v:

            return v

    return None



__all__ += ['_env_first']

# endregion





# region inference context

@dataclass

class InferenceContext:

    '''Tracks active service kinds and cached intermediate results during an inference call chain.



    Used to prevent circular service calls (e.g. completion → s2t → completion → …)

    and to share client-independent intermediate results across client failover attempts.

    '''

    _active_kinds: frozenset[str] = _dataclass_field(default_factory=frozenset)

    _cache: dict[str, Any] = _dataclass_field(default_factory=dict)



    def is_active(self, kind: str) -> bool:

        '''Check whether a service kind is currently in the call chain.'''

        return kind in self._active_kinds



    def _with_kind(self, kind: str) -> 'InferenceContext':

        '''Return a new context that adds *kind* while sharing the cache dict.'''

        return InferenceContext(

            _active_kinds=self._active_kinds | {kind},

            _cache=self._cache,

        )



    def cache_get(self, key: str, default: Any = None) -> Any:

        '''Retrieve a cached intermediate value.'''

        return self._cache.get(key, default)



    def cache_set(self, key: str, value: Any) -> None:

        '''Store a cached intermediate value.'''

        self._cache[key] = value



    def cache_has(self, key: str) -> bool:

        '''Check whether a key is present in the cache.'''

        return key in self._cache





_inference_context_var: ContextVar['InferenceContext | None'] = ContextVar(

    '_ai_service_inference_context', default=None

)



def get_inference_context() -> 'InferenceContext | None':

    '''Return the inference context for the current async task, or ``None`` if not set.'''

    return _inference_context_var.get()



def enter_service_context(kind: str) -> 'tuple[InferenceContext, contextvars.Token[InferenceContext | None]]':

    '''Register *kind* in the inference context and return ``(new_ctx, reset_token)``.



    Call :func:`_exit_service_context` with the returned token to restore the

    previous context when the call completes.

    '''

    current = _inference_context_var.get()

    if current is None:

        new_ctx = InferenceContext(_active_kinds=frozenset({kind}))

    else:

        new_ctx = current._with_kind(kind)

    token = _inference_context_var.set(new_ctx)

    return new_ctx, token



def exit_service_context(token: 'contextvars.Token[InferenceContext | None]') -> None:

    '''Restore the inference context to its state before :func:`_enter_service_context`.'''

    _inference_context_var.reset(token)



__all__ += [

    'get_inference_context',

    'enter_service_context',

    'exit_service_context',

]

# endregion



class StrategyLevel(IntEnum):

    '''客户端调度等级。'''

    LOAD_BALANCE = 0

    ON_RATELIMIT = 1

    ON_ERROR = 2



class ServiceClientInitParams(TypedDict, total=False):

    '''通用客户端初始化参数。'''

    key: str | None

    '''客户端实例名。给定时，同一 key 只缓存一个实例。'''

    max_concurrent: int | ConcurrentPool | None

    '''客户端允许的最大并发数；`None` 表示不限制。

    当传入 :class:`~._shared.ConcurrentPool` 时，并发限制由跨进程共享上下文统一管控。'''

    priority: float

    '''调度优先级；值越小越优先。'''

    strategy_lvl: int | StrategyLevel

    '''失败切换策略层级；默认值为 `StrategyLevel.LOAD_BALANCE`。'''



class ServiceInitParams(TypedDict, total=False):

    '''通用服务初始化参数。'''

    key: str | None

    '''服务实例名；给定时实例保存至 ``ServiceBase.ServiceInstances``。'''

    fail_cooldown: float

    '''客户端失败后的基础冷却秒数。'''

    recovery_interval: float | None

    '''后台健康恢复探测间隔；`None` 表示关闭恢复线程。'''



CT = TypeVar('CT')



@dataclass

class ServiceClient(Generic[CT]):

    '''服务实例内的 client 绑定配置。'''

    client: CT

    '''真实 client 实例。'''

    strategy_lvl: StrategyLevel | int | None = None

    '''定义时覆写真实 client 的 strategy_lvl。'''

    priority: float | None = None

    '''定义时覆写真实 client 的 priority。'''



    def get_priority(self) -> float:

        p = self.priority if self.priority is not None else getattr(self.client, 'priority', None)

        if p is None:

            return 1.0

        return float(p)



    def get_strategy_lvl(self) -> StrategyLevel:

        raw = self.strategy_lvl if self.strategy_lvl is not None else getattr(self.client, 'strategy_lvl', None)

        if raw is None:

            return StrategyLevel.LOAD_BALANCE

        try:

            return StrategyLevel(int(raw))

        except Exception:

            return StrategyLevel.LOAD_BALANCE



type ServiceClientEditableValues = dict[str, type | Any]



_empty = object()

'''Annotated 默认值哨兵：标注了 ``_empty`` 的字段不会被 :func:`_apply_service_param_defaults` 自动填入。'''



_AnnotateDefault = Annotated

'''用于在 TypedDict 字段上标注默认值的别名。

用法: ``field: _AnnotateDefault[Type, default_value]``

当调用 :func:`_apply_service_param_defaults` 时，缺失的字段会自动以 ``default_value`` 填入。

'''



class ServiceParamsBase(TypedDict, total=False):

    '''通用服务请求参数。'''

    timeout: float | None

    '''请求超时（秒）。未显式提供或传入 ``None`` 时，会回退到具体服务的默认值：

    ``completion=180``、``embedding=60``、``s2t=90``、``t2s=120``。

    各子 TypedDict 通过 ``_AnnotateDefault[float|None, <default>]`` 声明具体默认值。'''



def _apply_service_param_defaults(kwargs: dict[str, Any], td_cls: type) -> dict[str, Any]:

    '''根据 TypedDict 类的 ``Annotated`` 标注自动填入缺失参数的默认值。



    遍历 *td_cls* 及其父类（MRO 顺序，子类覆盖父类）的所有字段标注，

    对于缺失的键，若标注为 ``Annotated[T, default]`` 且 ``default is not _empty``，

    自动将 ``default`` 写入 *kwargs*。



    Args:

        kwargs: 待补全的参数字典（就地修改）。

        td_cls: 携带 ``Annotated`` 默认值标注的 TypedDict 类。



    Returns:

        补全后的 *kwargs*（与传入对象为同一引用）。

    '''

    # Collect annotations from MRO (child overrides parent)

    all_annotations: dict[str, Any] = {}

    for cls in reversed(td_cls.__mro__):

        cls_annotations = getattr(cls, '__annotations__', None)

        if cls_annotations:

            all_annotations.update(cls_annotations)

    # Fill defaults

    for key, anno in all_annotations.items():

        if key in kwargs:

            continue

        if get_origin(anno) is Annotated:

            anno_args = get_args(anno)

            if len(anno_args) >= 2 and anno_args[1] is not _empty:

                kwargs[key] = anno_args[1]

    return kwargs



_LOG_MAX_STRING_CHARS = 4096

_LOG_MAX_COLLECTION_ITEMS = 24

_LOG_MAX_DEPTH = 4



# ══════════════════════════════════════════════════════════════════════════════

# MediaLogInfo — 媒体文件的日志元数据

# ══════════════════════════════════════════════════════════════════════════════



class MediaLogInfo(TypedDict, total=False):

    '''媒体/文档对象在日志中的序列化表示。'''

    __type__: str

    source: str | None

    format: str | None

    byte_size: int

    md5: str

    page_count: int

    width: int

    height: int

    mode: str

    duration_seconds: float

    frame_rate: int

    channels: int

    fps: float

    frame_count: int



# ══════════════════════════════════════════════════════════════════════════════

# ServiceCallLogModel — ORM 日志模型

# ══════════════════════════════════════════════════════════════════════════════



def _lazy_orm_model_base():

    from core.storage.orm import ORMModel

    return ORMModel



def _lazy_orm_field():

    from core.storage.orm import ORMField

    return ORMField



# 延迟定义，仅在首次使用时创建 ORMModel 子类。

_ServiceCallLogModel: type | None = None

_ServiceCallLogModel_lock = threading.Lock()



def _get_service_call_log_model():

    global _ServiceCallLogModel

    if _ServiceCallLogModel is not None:

        return _ServiceCallLogModel

    with _ServiceCallLogModel_lock:

        if _ServiceCallLogModel is not None:

            return _ServiceCallLogModel

        ORMModel = _lazy_orm_model_base()

        ORMField = _lazy_orm_field()



        class ServiceCallLogModel(ORMModel, full_collection_name='service_call_logs'):

            '''ORM 模型：AI 服务调用日志。'''

            created_at: float = 0.0

            service_kind: str = ''

            operation: str = ''

            client_class: str = ''

            success: bool = True

            duration_ms: float = 0.0

            request_json: str | None = ORMField(default=None, max_length=65536)

            response_json: str | None = ORMField(default=None, max_length=65536)

            error_type: str | None = None

            error_message: str | None = None

            request_chars: int = 0

            response_chars: int = 0

            pid: int = 0

            project_root: str | None = None

            metadata_json: str | None = None



        _ServiceCallLogModel = ServiceCallLogModel

        return _ServiceCallLogModel



# ══════════════════════════════════════════════════════════════════════════════

# ORM 客户端获取 — 遵循 storage protocol

# ══════════════════════════════════════════════════════════════════════════════



_log_orm_client: object | None = None

_log_orm_client_lock = threading.Lock()



def _get_log_orm_client():

    '''通过 StorageConfig 获取 service_record ORM 客户端。



    解析顺序（由 ``StorageConfig.Global().orm.get_service_record()`` 控制）：

    1. orm.service_record 命名槽位

    2. fallback 到 orm.default

    '''

    global _log_orm_client

    if _log_orm_client is not None:

        return _log_orm_client

    with _log_orm_client_lock:

        if _log_orm_client is not None:

            return _log_orm_client

        from core.storage.config import StorageConfig

        _log_orm_client = StorageConfig.Global().orm.get_service_record()

        return _log_orm_client



# ══════════════════════════════════════════════════════════════════════════════

# TypedDicts — 日志记录 & 统计

# ══════════════════════════════════════════════════════════════════════════════



class ServiceCallTraceRecordInput(TypedDict, total=False):

    '''写入日志时使用的基础结构。'''

    service_kind: Required[str]

    operation: Required[str]

    client_class: Required[str]

    success: Required[bool]

    duration_ms: Required[float]

    request: NotRequired[object | None]

    response: NotRequired[object | None]

    error: NotRequired[Exception | None]

    metadata: NotRequired[dict[str, object] | None]



class ServiceCallLogRecord(TypedDict):

    '''单条调用日志（查询返回值）。'''

    id: str

    created_at: str | None

    service_kind: str

    operation: str

    client_class: str

    success: bool

    duration_ms: float

    request: object | None

    response: object | None

    error_type: str | None

    error_message: str | None

    request_chars: int

    response_chars: int

    pid: int

    project_root: str | None

    metadata: object | None



class ServiceCallStatRecord(TypedDict):

    '''调用统计记录。'''

    group: str

    call_count: int

    success_count: int

    failure_count: int

    avg_duration_ms: float

    last_called_at: str | None



# ══════════════════════════════════════════════════════════════════════════════

# ServiceCallLogMixin — 查询与写入入口

# ══════════════════════════════════════════════════════════════════════════════



class ServiceCallLogMixin:

    '''提供 ORM 调用日志查询能力。'''



    def _log_request_payload(self, operation: str, args: tuple[object, ...], kwargs: dict[str, object]) -> object:

        return {'args': args, 'kwargs': kwargs}



    def _log_response_payload(self, operation: str, result: object) -> object:

        return result



    def _log_extra_metadata(

        self,

        operation: str,

        args: tuple[object, ...],

        kwargs: dict[str, object],

        result: object = None,

    ) -> dict[str, object] | None:

        return None



    def _service_kind_for_log(self) -> str:

        return _normalize_service_kind_name(type(self))



    def _record_call_log(

        self,

        *,

        operation: str,

        started_at: float,

        success: bool,

        request: object,

        response: object = None,

        error: Exception | None = None,

        metadata: dict[str, object] | None = None,

    ) -> None:

        service_kind = self._service_kind_for_log()

        client_class = type(self).__name__

        duration_ms = (time.perf_counter() - started_at) * 1000.0

        if not success:

            _service_call_logger.error(

                'AI service call failed: kind=%s op=%s client=%s duration_ms=%.1f error=%r',

                service_kind, operation, client_class, duration_ms, error,

                exc_info=error if isinstance(error, BaseException) else False,

            )

        ServiceCallTraceStore.record(

            service_kind=service_kind,

            operation=operation,

            client_class=client_class,

            success=success,

            duration_ms=duration_ms,

            request=request,

            response=response,

            error=error,

            metadata=metadata,

        )



    async def _record_call_log_async(

        self,

        *,

        operation: str,

        started_at: float,

        success: bool,

        request: object,

        response: object = None,

        error: Exception | None = None,

        metadata: dict[str, object] | None = None,

    ) -> None:

        service_kind = self._service_kind_for_log()

        client_class = type(self).__name__

        duration_ms = (time.perf_counter() - started_at) * 1000.0

        if not success:

            _service_call_logger.error(

                'AI service call failed: kind=%s op=%s client=%s duration_ms=%.1f error=%r',

                service_kind, operation, client_class, duration_ms, error,

                exc_info=error if isinstance(error, BaseException) else False,

            )

        await ServiceCallTraceStore.arecord(

            service_kind=service_kind,

            operation=operation,

            client_class=client_class,

            success=success,

            duration_ms=duration_ms,

            request=request,

            response=response,

            error=error,

            metadata=metadata,

        )



    async def _trace_async_call(

        self,

        operation: str,

        func: Callable[[], Awaitable['TraceResultT']],

        *,

        request: object,

        metadata: dict[str, object] | None = None,

        metadata_builder: Callable[['TraceResultT | None'], dict[str, object] | None] | None = None,

        skip_log: bool = False,

        response_builder: Callable[['TraceResultT'], object] | None = None,

    ) -> 'TraceResultT':

        started_at = time.perf_counter()

        if bool(getattr(self, '_closed', False)):

            exc = RuntimeError(f'{type(self).__name__} instance was retired during AI service reload')

            if not skip_log:

                await self._record_call_log_async(

                    operation=operation,

                    started_at=started_at,

                    success=False,

                    request=request,

                    error=exc,

                    metadata=metadata,

                )

            raise exc

        try:

            result = await func()

        except Exception as exc:

            if not skip_log:

                failure_metadata = metadata_builder(None) if metadata_builder else None

                await self._record_call_log_async(

                    operation=operation,

                    started_at=started_at,

                    success=False,

                    request=request,

                    error=exc,

                    metadata=metadata if metadata is not None else failure_metadata,

                )

            raise



        if not skip_log:

            success_metadata = metadata_builder(result) if metadata_builder else None

            response = response_builder(result) if response_builder else self._log_response_payload(operation, result)

            await self._record_call_log_async(

                operation=operation,

                started_at=started_at,

                success=True,

                request=request,

                response=response,

                metadata=success_metadata if success_metadata is not None else metadata,

            )

        return result



    @classmethod

    def get_call_log(cls, call_id: str) -> ServiceCallLogRecord | None:

        '''按主键读取单条日志。



        Args:

            call_id: 日志记录 ID（ORM ObjectId 字符串）。



        Returns:

            命中的日志记录；不存在时返回 `None`。

        '''

        return _run_any_func(_async_get_call_log, str(call_id))



    @classmethod

    def recent_call_logs(cls, limit: int = 50) -> list[ServiceCallLogRecord]:

        '''读取最近日志。'''

        return cls.QueryCallLogs(limit=limit)



    @classmethod

    def QueryCallLogs(

        cls,

        *,

        limit: int = 100,

        success: bool | None = None,

        operation: str | None = None,

        client_class: str | None = None,

        service_kind: AIServiceKind | str | None = None,

        since: float | None = None,

        until: float | None = None,

    ) -> list[ServiceCallLogRecord]:

        '''按条件查询调用日志。



        Args:

            limit: 最多返回的日志条数；内部至少按 1 处理。

            success: 仅筛选成功或失败记录；``None`` 表示不过滤。

            operation: 按操作名筛选，例如 ``complete``、``embedding``。

            client_class: 按客户端类名筛选。

            service_kind: 按服务类别筛选，例如 ``completion``、``s2t``。

            since: 仅返回创建时间 >= 该 Unix 时间戳的记录。

            until: 仅返回创建时间 <= 该 Unix 时间戳的记录。



        Returns:

            满足条件的日志记录列表，按创建时间倒序返回。

        '''

        return _run_any_func(

            _async_query_call_logs,

            limit=max(1, int(limit)),

            success=success,

            operation=operation,

            client_class=client_class,

            service_kind=service_kind,

            since=since,

            until=until,

        )



    @classmethod

    def QueryCallStats(

        cls,

        *,

        group_by: Literal['service_kind', 'operation', 'client_class'] = 'operation',

        success: bool | None = None,

        operation: str | None = None,

        client_class: str | None = None,

        service_kind: AIServiceKind | str | None = None,

        since: float | None = None,

        until: float | None = None,

    ) -> list[ServiceCallStatRecord]:

        '''按条件聚合调用统计。



        Args:

            group_by: 统计分组维度，可按服务类别、操作名或客户端类名聚合。

            success: 仅统计成功或失败记录；``None`` 表示不过滤。

            operation: 按操作名筛选。

            client_class: 按客户端类名筛选。

            service_kind: 按服务类别筛选。

            since: 仅统计创建时间 >= 该 Unix 时间戳的记录。

            until: 仅统计创建时间 <= 该 Unix 时间戳的记录。



        Returns:

            聚合后的统计结果列表，按调用次数降序、最后调用时间降序返回。

        '''

        return _run_any_func(

            _async_query_call_stats,

            group_by=group_by,

            success=success,

            operation=operation,

            client_class=client_class,

            service_kind=service_kind,

            since=since,

            until=until,

        )





# ══════════════════════════════════════════════════════════════════════════════

# ORM 异步查询实现

# ══════════════════════════════════════════════════════════════════════════════



def _match_log_record(

    row: dict[str, Any],

    *,

    success: bool | None,

    operation: str | None,

    client_class: str | None,

    service_kind: AIServiceKind | str | None,

    since: float | None,

    until: float | None,

) -> bool:

    '''在 Python 侧对 ORM 返回的原始行进行条件过滤。'''

    if service_kind and row.get('service_kind') != service_kind:

        return False

    if success is not None and row.get('success') != success:

        return False

    if operation and row.get('operation') != operation:

        return False

    if client_class and row.get('client_class') != client_class:

        return False

    created_at = row.get('created_at', 0.0)

    if since is not None and created_at < since:

        return False

    if until is not None and created_at > until:

        return False

    return True





def _orm_row_to_log_record(row: dict[str, Any]) -> ServiceCallLogRecord:

    '''将 ORM 返回的 dict 行转换为 ``ServiceCallLogRecord``。'''

    return {

        'id': str(row.get('id') or row.get('_id', '')),

        'created_at': _format_timestamp(row.get('created_at')),

        'service_kind': row.get('service_kind', ''),

        'operation': row.get('operation', ''),

        'client_class': row.get('client_class', ''),

        'success': bool(row.get('success')),

        'duration_ms': float(row.get('duration_ms', 0.0)),

        'request': _parse_json_or_none(row.get('request_json')),

        'response': _parse_json_or_none(row.get('response_json')),

        'error_type': row.get('error_type'),

        'error_message': row.get('error_message'),

        'request_chars': int(row.get('request_chars', 0)),

        'response_chars': int(row.get('response_chars', 0)),

        'pid': int(row.get('pid', 0)),

        'project_root': row.get('project_root'),

        'metadata': _parse_json_or_none(row.get('metadata_json')),

    }





def _service_log_sql_json_field_expr(client: 'SQL_ORM_Client', field: str) -> str | None:

    dialect = str(client._engine.dialect.name).lower()

    if dialect == 'sqlite':

        return f"json_extract(payload_json, '$.{field}')"

    if dialect == 'postgresql':

        return f"CAST(payload_json AS JSONB)->>'{field}'"

    return None





def _build_service_log_sql_parts(

    *,

    success: bool | None,

    operation: str | None,

    client_class: str | None,

    service_kind: AIServiceKind | str | None,

    since: float | None,

    until: float | None,

) -> tuple[Any, str, str, list[str], dict[str, Any], dict[str, str]] | None:

    try:

        from core.storage.orm import SQL_ORM_Client

    except Exception:

        return None



    client = _get_log_orm_client()

    if not isinstance(client, SQL_ORM_Client):

        return None



    Model = _get_service_call_log_model()

    collection, _ = client._normalize_collection(Model)

    if not client._started:

        client.start()

    if not client._collection_exists(collection):

        return None



    exprs = {

        'service_kind': _service_log_sql_json_field_expr(client, 'service_kind'),

        'operation': _service_log_sql_json_field_expr(client, 'operation'),

        'client_class': _service_log_sql_json_field_expr(client, 'client_class'),

        'success': _service_log_sql_json_field_expr(client, 'success'),

        'duration_ms': _service_log_sql_json_field_expr(client, 'duration_ms'),

    }

    if not all(exprs.values()):

        return None



    dialect = str(client._engine.dialect.name).lower()

    conditions = ['(expire_at IS NULL OR expire_at > :now)']

    params: dict[str, Any] = {'now': time.time()}



    if service_kind:

        params['service_kind'] = service_kind

        conditions.append(f"COALESCE({exprs['service_kind']}, '') = :service_kind")

    if operation:

        params['operation'] = operation

        conditions.append(f"COALESCE({exprs['operation']}, '') = :operation")

    if client_class:

        params['client_class'] = client_class

        conditions.append(f"COALESCE({exprs['client_class']}, '') = :client_class")

    if success is not None:

        if dialect == 'sqlite':

            params['success'] = 1 if success else 0

            conditions.append(f"CAST(COALESCE({exprs['success']}, 0) AS INTEGER) = :success")

        else:

            params['success'] = 'true' if success else 'false'

            conditions.append(

                f"LOWER(COALESCE(CAST({exprs['success']} AS TEXT), 'false')) = :success"

            )

    if since is not None:

        params['since'] = float(since)

        conditions.append('created_at >= :since')

    if until is not None:

        params['until'] = float(until)

        conditions.append('created_at <= :until')



    return client, collection, dialect, conditions, params, cast(dict[str, str], exprs)





def _sql_service_log_row_to_record(row_id: 'int | str', payload_json: str) -> ServiceCallLogRecord:

    from core.storage.base import _json_loads

    from core.storage.orm.client_base import _restore_payload_from_storage

    restored = _restore_payload_from_storage(_json_loads(payload_json), row_id)

    row = dict(restored) if isinstance(restored, dict) else {'id': str(row_id)}

    return _orm_row_to_log_record(row)





def _success_truthy_sql(expr: str, dialect: str) -> str:

    if dialect == 'sqlite':

        return f"CAST(COALESCE({expr}, 0) AS INTEGER) <> 0"

    return f"LOWER(COALESCE(CAST({expr} AS TEXT), 'false')) IN ('1', 'true', 't', 'yes')"





async def _async_get_call_log(call_id: str) -> ServiceCallLogRecord | None:

    '''按 ORM ID 读取单条日志。'''

    try:

        client = _get_log_orm_client()

        Model = _get_service_call_log_model()

        row = await client.search_one(Model, query={'id': call_id}, as_model=False) # type: ignore

        if row is None:

            return None

        return _orm_row_to_log_record(dict(row) if not isinstance(row, dict) else row)

    except Exception:

        return None





async def _async_query_call_logs(

    *,

    limit: int,

    success: bool | None,

    operation: str | None,

    client_class: str | None,

    service_kind: AIServiceKind | str | None,

    since: float | None,

    until: float | None,

) -> list[ServiceCallLogRecord]:

    '''通过 ORM 客户端异步查询日志，Python 侧过滤 + 排序 + 截断。'''

    try:

        sql_parts = _build_service_log_sql_parts(

            success=success,

            operation=operation,

            client_class=client_class,

            service_kind=service_kind,

            since=since,

            until=until,

        )

        if sql_parts is not None:

            client, collection, _dialect, conditions, params, _exprs = sql_parts

            query_sql = (

                f"SELECT _id, payload_json FROM {client._table_sql(collection)} "

                f"WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT :limit"

            )

            query_params = dict(params)

            query_params['limit'] = max(1, int(limit))

            with client._engine.begin() as conn:

                rows = conn.execute(client._sql_text(query_sql), query_params).fetchall()

            return [_sql_service_log_row_to_record(row[0], row[1]) for row in rows]



        client = _get_log_orm_client()

        Model = _get_service_call_log_model()

        # 构建等值查询字典（ORM search 仅支持等值匹配）

        eq_query: dict[str, Any] = {}

        if service_kind:

            eq_query['service_kind'] = service_kind

        if operation:

            eq_query['operation'] = operation

        if client_class:

            eq_query['client_class'] = client_class

        if success is not None:

            eq_query['success'] = success



        results: list[dict[str, Any]] = []

        async for item in client.search(Model, query=eq_query or None, as_model=False): # type: ignore

            row = dict(item) if not isinstance(item, dict) else item

            if not _match_log_record(row, success=None, operation=None, client_class=None,

                                     service_kind=None, since=since, until=until):

                continue

            results.append(row)



        results.sort(key=lambda r: float(r.get('created_at', 0.0)), reverse=True)

        return [_orm_row_to_log_record(r) for r in results[:limit]]

    except Exception:

        return []





async def _async_query_call_stats(

    *,

    group_by: str,

    success: bool | None,

    operation: str | None,

    client_class: str | None,

    service_kind: AIServiceKind | str | None,

    since: float | None,

    until: float | None,

) -> list[ServiceCallStatRecord]:

    '''通过 ORM 客户端异步查询并在 Python 侧聚合统计。'''

    try:

        sql_parts = _build_service_log_sql_parts(

            success=success,

            operation=operation,

            client_class=client_class,

            service_kind=service_kind,

            since=since,

            until=until,

        )

        if sql_parts is not None:

            client, collection, dialect, conditions, params, exprs = sql_parts

            group_expr = exprs.get(group_by)

            duration_expr = exprs.get('duration_ms')

            success_expr = exprs.get('success')

            if group_expr and duration_expr and success_expr:

                success_true = _success_truthy_sql(success_expr, dialect)

                query_sql = (

                    f"SELECT COALESCE(CAST({group_expr} AS TEXT), '') AS group_key, "

                    f"COUNT(*) AS call_count, "

                    f"SUM(CASE WHEN {success_true} THEN 1 ELSE 0 END) AS success_count, "

                    f"SUM(CASE WHEN {success_true} THEN 0 ELSE 1 END) AS failure_count, "

                    f"AVG(CAST(COALESCE({duration_expr}, 0) AS REAL)) AS avg_duration_ms, "

                    f"MAX(created_at) AS last_called_at "

                    f"FROM {client._table_sql(collection)} WHERE {' AND '.join(conditions)} "

                    f"GROUP BY group_key ORDER BY call_count DESC, last_called_at DESC"

                )

                with client._engine.begin() as conn:

                    rows = conn.execute(client._sql_text(query_sql), params).fetchall()

                return [

                    {

                        'group': str(row[0] or ''),

                        'call_count': int(row[1] or 0),

                        'success_count': int(row[2] or 0),

                        'failure_count': int(row[3] or 0),

                        'avg_duration_ms': float(row[4] or 0.0),

                        'last_called_at': _format_timestamp(float(row[5])) if row[5] else None,

                    }

                    for row in rows

                ]



        client = _get_log_orm_client()

        Model = _get_service_call_log_model()

        eq_query: dict[str, Any] = {}

        if service_kind:

            eq_query['service_kind'] = service_kind

        if operation:

            eq_query['operation'] = operation

        if client_class:

            eq_query['client_class'] = client_class

        if success is not None:

            eq_query['success'] = success



        groups: dict[str, dict[str, Any]] = {}

        async for item in client.search(Model, query=eq_query or None, as_model=False): # type: ignore

            row = dict(item) if not isinstance(item, dict) else item

            if not _match_log_record(row, success=None, operation=None, client_class=None,

                                     service_kind=None, since=since, until=until):

                continue

            key = str(row.get(group_by, ''))

            if key not in groups:

                groups[key] = {'total': 0, 'success': 0, 'failure': 0, 'duration_sum': 0.0, 'last_at': 0.0}

            g = groups[key]

            g['total'] += 1

            if row.get('success'):

                g['success'] += 1

            else:

                g['failure'] += 1

            g['duration_sum'] += float(row.get('duration_ms', 0.0))

            created_at = float(row.get('created_at', 0.0))

            if created_at > g['last_at']:

                g['last_at'] = created_at



        stats: list[ServiceCallStatRecord] = []

        for key, g in groups.items():

            stats.append({

                'group': key,

                'call_count': g['total'],

                'success_count': g['success'],

                'failure_count': g['failure'],

                'avg_duration_ms': g['duration_sum'] / g['total'] if g['total'] else 0.0,

                'last_called_at': _format_timestamp(g['last_at']) if g['last_at'] else None,

            })

        stats.sort(key=lambda s: (s['call_count'], s['last_called_at'] or ''), reverse=True)

        return stats

    except Exception:

        return []





class ServiceCallTraceStore:

    '''负责将服务调用记录写入 ORM 存储。'''



    @staticmethod

    def _build_record_obj(**record_input: Unpack[ServiceCallTraceRecordInput]) -> 'ORMModel':

        request_json = _dump_log_payload(record_input.get('request'))

        response_json = _dump_log_payload(record_input.get('response'))

        metadata_json = _dump_log_payload(record_input.get('metadata'))

        error = record_input.get('error')



        Model = _get_service_call_log_model()

        return Model(

            created_at=time.time(),

            service_kind=record_input['service_kind'],

            operation=record_input['operation'],

            client_class=record_input['client_class'],

            success=record_input['success'],

            duration_ms=float(record_input['duration_ms']),

            request_json=request_json,

            response_json=response_json,

            error_type=type(error).__name__ if error else None,

            error_message=_truncate_text(str(error), _LOG_MAX_STRING_CHARS) if error else None,

            request_chars=len(request_json) if request_json else 0,

            response_chars=len(response_json) if response_json else 0,

            pid=os.getpid(),

            project_root=_truncate_text(str(Path.cwd()), 512),

            metadata_json=metadata_json,

        )



    @classmethod

    def record(cls, **record_input: Unpack[ServiceCallTraceRecordInput]) -> None:

        '''写入一条调用日志（同步 fallback）。'''

        try:

            record_obj = cls._build_record_obj(**record_input)

            _run_any_func(_async_store_record, record_obj)

        except Exception:

            pass



    @classmethod

    async def arecord(cls, **record_input: Unpack[ServiceCallTraceRecordInput]) -> None:

        '''在当前事件循环中写入一条调用日志。'''

        try:

            record_obj = cls._build_record_obj(**record_input)

            await _async_store_record(record_obj)

        except Exception:

            pass





async def _async_store_record(record: 'ORMModel') -> None:

    '''将单条日志模型实例写入 ORM 客户端。'''

    try:

        client = _get_log_orm_client()

        await client.set(record)    # type: ignore

    except Exception:

        pass



def _serialize_media_for_log(value: Image | Audio | Video | PDF | PPT | HTML | Doc | RTF | Excel) -> MediaLogInfo:

    info: MediaLogInfo = {'__type__': type(value).__name__}

    source = getattr(value, 'source', None)

    if source is not None:

        info['source'] = _truncate_text(str(source), 256)



    # 通过 File.Type 直接获取格式；对 Image 补充 format 属性

    if isinstance(value, _FileProtocol):    # type: ignore

        info['format'] = type(value).Type

    fmt = getattr(value, 'format', None)

    if isinstance(fmt, str) and fmt:

        info['format'] = fmt.lower()



    if isinstance(value, (PDF, PPT, Doc)):

        try:

            info['page_count'] = value.page_count

        except Exception:

            ...



    md5_func = getattr(value, 'to_md5_hash', None)

    if callable(md5_func):

        try:

            info['md5'] = md5_func()    # type: ignore

        except Exception:

            ...



    try:

        info['byte_size'] = len(value.to_bytes())

    except Exception:

        ...



    # 利用 Image/Audio/Video 的原生属性直接读取元数据，避免 bytes→reload

    if isinstance(value, Image):

        try:

            info['width'] = int(value.width)

            info['height'] = int(value.height)

        except Exception:

            ...

        mode = getattr(value, 'mode', None)

        if isinstance(mode, str):

            info['mode'] = mode

    elif isinstance(value, Audio):

        try:

            info['duration_seconds'] = round(len(value) / 1000.0, 3)

        except Exception:

            ...

        try:

            info['frame_rate'] = int(value.frame_rate)

        except Exception:

            ...

        try:

            info['channels'] = int(value.channels)

        except Exception:

            ...

    elif isinstance(value, Video):

        try:

            w = getattr(value, 'w', None) or getattr(value, 'width', None)

            h = getattr(value, 'h', None) or getattr(value, 'height', None)

            if w:

                info['width'] = int(w)

            if h:

                info['height'] = int(h)

        except Exception:

            ...

        try:

            fps = getattr(value, 'fps', None)

            if fps:

                info['fps'] = round(float(fps), 6)

        except Exception:

            ...

        n_frames = getattr(value, 'n_frames', None)

        if n_frames:

            try:

                info['frame_count'] = int(n_frames)

            except Exception:

                ...

        try:

            dur = getattr(value, 'duration', None)

            if dur:

                info['duration_seconds'] = round(float(dur), 3)

            elif fps and n_frames:

                info['duration_seconds'] = round(float(n_frames) / float(fps), 3)

        except Exception:

            ...



    return info



def _truncate_text(text: str, max_len: int = _LOG_MAX_STRING_CHARS) -> str:

    if len(text) <= max_len:

        return text

    extra = len(text) - max_len

    return f'{text[:max_len]}...(truncated {extra} chars)'



def _sanitize_for_log(value: object, *, depth: int = 0) -> object:

    if depth >= _LOG_MAX_DEPTH:

        return {'__type__': type(value).__name__, '__repr__': _truncate_text(repr(value), 256)}



    if value is None or isinstance(value, (bool, int, float)):

        return value

    if isinstance(value, str):

        return _truncate_text(value)

    if isinstance(value, bytes):

        return {'__type__': 'bytes', 'byte_size': len(value)}

    if isinstance(value, bytearray):

        return {'__type__': 'bytearray', 'byte_size': len(value)}

    if isinstance(value, Path):

        return str(value)

    if isinstance(value, (Image, Audio, Video, PDF, PPT, HTML, Doc, RTF, Excel)):

        return _serialize_media_for_log(value)

    if isinstance(value, BaseModel):

        try:

            return _sanitize_for_log(value.model_dump(), depth=depth + 1)

        except Exception:

            return {'__type__': type(value).__name__, '__repr__': _truncate_text(repr(value), 256)}

    if isinstance(value, BaseModelV1):

        try:

            return _sanitize_for_log(value.dict(), depth=depth + 1)

        except Exception:

            return {'__type__': type(value).__name__, '__repr__': _truncate_text(repr(value), 256)}

    if isinstance(value, dict):

        items = list(value.items())[:_LOG_MAX_COLLECTION_ITEMS]

        dict_payload: dict[str, Any] = {}

        for k, v in items:

            dict_payload[_truncate_text(str(k), 128)] = _sanitize_for_log(v, depth=depth + 1)

        if len(value) > _LOG_MAX_COLLECTION_ITEMS:

            dict_payload['__truncated_items__'] = len(value) - _LOG_MAX_COLLECTION_ITEMS

        return dict_payload

    if isinstance(value, (list, tuple, set, frozenset)):

        seq = list(value)

        list_payload: list[Any] = [_sanitize_for_log(item, depth=depth + 1) for item in seq[:_LOG_MAX_COLLECTION_ITEMS]]

        if len(seq) > _LOG_MAX_COLLECTION_ITEMS:

            list_payload.append({'__truncated_items__': len(seq) - _LOG_MAX_COLLECTION_ITEMS})

        return list_payload

    model_dump_func = getattr(value, 'model_dump', None)

    if callable(model_dump_func):

        try:

            return _sanitize_for_log(model_dump_func(), depth=depth + 1)

        except Exception:

            ...

    if hasattr(value, '__dict__'):

        try:

            return {

                '__type__': type(value).__name__,

                'fields': _sanitize_for_log(vars(value), depth=depth + 1),

            }

        except Exception:

            ...

    return {'__type__': type(value).__name__, '__repr__': _truncate_text(repr(value), 256)}



def _dump_log_payload(value: object) -> str | None:

    if value is None:

        return None

    sanitized = _sanitize_for_log(value)

    return json.dumps(sanitized, ensure_ascii=False)



def _parse_json_or_none(value: object) -> object | None:

    if value in (None, ''):

        return None

    if isinstance(value, str):

        try:

            return json.loads(value)

        except Exception:

            return value

    return value



def _format_timestamp(value: object) -> str | None:

    if value in (None, ''):

        return None

    try:

        timestamp_value = float(cast(int | float | str, value))

        return datetime.fromtimestamp(timestamp_value).astimezone().isoformat(timespec='seconds')

    except Exception:

        return None



ProbeInputT = TypeVar('ProbeInputT')

TraceResultT = TypeVar('TraceResultT')

ClientT = TypeVar('ClientT')

RunResultT = TypeVar('RunResultT')



class _RuntimeManagedClient(Protocol):

    max_concurrent: int | ConcurrentPool | None

    priority: float | None

    strategy_lvl: int | StrategyLevel | None

    _state_score: float

    _state_success_count: int

    _state_fail_count: int

    _state_cooldown_until: float

    _state_last_error: str | None

    _state_inflight: int

    _state_speed_ewma: float

    _state_last_success_at: float





@dataclass

class _CacheSaveTask:

    merge_key: str

    payload: Any

    flush_many: Callable[[list[Any]], Any]



_CLIENT_TYPE_REGISTRY: dict[str, type['ServiceClientBase']] = {}

'''全局客户端类型注册表，key 为 normalize 后的 type 字符串。'''



_SERVICE_RUNTIME_STATE_LOCK = threading.RLock()

_SERVICE_RUNTIME_EVENTS: dict[str, threading.Event] = {}





@dataclass(slots=True)

class ServiceRuntimeState:

    '''Process-local reload/block state for a service kind.'''

    reloading: bool = False

    reason: str | None = None

    block_new_requests: bool = False

    version: int | None = None

    updated_at: float = 0.0





_SERVICE_RUNTIME_STATE: dict[str, ServiceRuntimeState] = {}



def _normalize_client_type(t: str) -> str:

    '''将 type 字符串标准化：小写并去除 ``_`` / 空格 / ``-``。'''

    return t.lower().replace('_', '').replace(' ', '').replace('-', '')





def _normalize_service_kind_name(service_kind: AIServiceKind | str | type | None) -> str:

    if service_kind is None:

        return ''

    if isinstance(service_kind, type):

        name = service_kind.__name__

    else:

        name = str(service_kind)

    lowered = name.strip().lower()

    if lowered.endswith('service'):

        lowered = lowered[:-7]

    return lowered





def _get_service_runtime_event(service_kind: AIServiceKind | str | type | None) -> threading.Event:

    normalized = _normalize_service_kind_name(service_kind)

    with _SERVICE_RUNTIME_STATE_LOCK:

        event = _SERVICE_RUNTIME_EVENTS.get(normalized)

        if event is None:

            event = threading.Event()

            event.set()

            _SERVICE_RUNTIME_EVENTS[normalized] = event

        return event





def set_service_runtime_reloading(

    service_kinds: Sequence[AIServiceKind | str | type],

    *,

    reloading: bool,

    reason: str | None = None,

    version: int | None = None,

    block_new_requests: bool = True,

) -> None:

    with _SERVICE_RUNTIME_STATE_LOCK:

        for service_kind in service_kinds:

            normalized = _normalize_service_kind_name(service_kind)

            event = _get_service_runtime_event(normalized)

            state = _SERVICE_RUNTIME_STATE.setdefault(normalized, ServiceRuntimeState())

            state.reloading = bool(reloading)

            state.reason = reason

            state.block_new_requests = bool(reloading and block_new_requests)

            if version is not None:

                state.version = int(version)

            state.updated_at = time.time()

            if reloading and block_new_requests:

                event.clear()

            else:

                event.set()





def wait_service_runtime_ready(service_kind: AIServiceKind | str | type | None, timeout: float | None = None) -> None:

    event = _get_service_runtime_event(service_kind)

    if timeout is None:

        event.wait()

        return

    event.wait(timeout=max(0.0, float(timeout)))





async def await_service_runtime_ready(

    service_kind: AIServiceKind | str | type | None,

    timeout: float | None = None,

) -> None:

    await asyncio.to_thread(wait_service_runtime_ready, service_kind, timeout)





def get_service_runtime_state(service_kind: AIServiceKind | str | type | None) -> ServiceRuntimeState:

    normalized = _normalize_service_kind_name(service_kind)

    with _SERVICE_RUNTIME_STATE_LOCK:

        existing = _SERVICE_RUNTIME_STATE.get(normalized)

        if existing is None:

            return ServiceRuntimeState()

        return ServiceRuntimeState(

            reloading=existing.reloading,

            reason=existing.reason,

            block_new_requests=existing.block_new_requests,

            version=existing.version,

            updated_at=existing.updated_at,

        )



class ServiceClientBase(ServiceCallLogMixin, ABC, Generic[ProbeInputT]):

    '''所有客户端统一底层能力与运行态。'''



    ServiceKind: ClassVar['AIServiceKind | None'] = None

    '''所属服务种类。具体子类（CompletionClient/EmbeddingClient/...）通过 ClassVar 声明。'''



    def _service_kind_for_log(self) -> str:

        kind = type(self).ServiceKind

        if kind:

            return kind

        return _normalize_service_kind_name(type(self))



    Type: ClassVar[str | None] = None

    '''通过 ``__init_subclass__(type=...)`` 注册的客户端类型标识。'''



    _STREAM_TTFT_TIMEOUT: ClassVar[float] = 16.0

    '''流式请求首个有效数据块的默认超时 (秒)。'''



    _instance_cache: ClassVar[WeakValueDictionary[tuple[type, str], Self]] = WeakValueDictionary()

    '''跨子类共享的弱引用实例缓存，key=(cls, params_hash)。'''



    @classmethod

    def _compute_cache_key(cls, args: tuple[object, ...], kwargs: dict[str, object]) -> tuple[type, str] | None:

        '''从 __init__ 参数计算缓存 key，填充所有默认值后哈希。'''

        explicit_key = kwargs.get('key')

        if explicit_key is not None:

            return (cls, str(explicit_key))

        try:

            sig = inspect.signature(cls.__init__)

            bound = sig.bind_partial(None, *args, **kwargs)

            bound.apply_defaults()

            params: dict[str, object] = {'__class__': cls.__qualname__}

            for k, v in sorted(bound.arguments.items()):

                if k == 'self':

                    continue

                if isinstance(v, ConcurrentPool) or callable(v):

                    continue

                if isinstance(v, BaseModel):

                    params[k] = v.model_dump_json()

                elif hasattr(v, 'apikey') and hasattr(v, 'base_url'):

                    params[k] = f'{getattr(v, "apikey", "")}@{getattr(v, "base_url", "")}'

                elif hasattr(v, 'api_key'):

                    params[k] = f'{getattr(v, "api_key", "")}'

                else:

                    try:

                        json.dumps(v, default=str)

                        params[k] = v

                    except (TypeError, ValueError, OverflowError):

                        params[k] = repr(v)

            data = json.dumps(params, sort_keys=True, default=str, ensure_ascii=False)

            return (cls, hashlib.md5(data.encode()).hexdigest())

        except Exception:

            return None



    def __new__(cls, *args: Any, **kwargs: Any) -> Self:

        cache_key = cls._compute_cache_key(args, kwargs)

        if cache_key is not None:

            cached = cls._instance_cache.get(cache_key)

            if cached is not None:

                if bool(getattr(cached, '_closed', False)):

                    cls._instance_cache.pop(cache_key, None)

                else:

                    return cached

        instance = super().__new__(cls)

        if cache_key is not None:

            instance._cache_key = cache_key     # type: ignore

            cls._instance_cache[cache_key] = instance

        return instance



    def __init_subclass__(cls, *, type: str | None = None, **kwargs: Any) -> None:  # noqa: A002

        super().__init_subclass__(**kwargs)

        cls.Type = type

        if type is not None:

            normalized = _normalize_client_type(type)

            if normalized in _CLIENT_TYPE_REGISTRY:

                existing = _CLIENT_TYPE_REGISTRY[normalized]

                raise TypeError(

                    f"Client type {type!r} (normalized: {normalized!r}) "

                    f"is already registered by {existing.__qualname__}"

                )

            _CLIENT_TYPE_REGISTRY[normalized] = cls

        own_init = cls.__dict__.get('__init__')

        if own_init is not None:

            @functools.wraps(own_init)

            def _guarded_init(self: 'ServiceClientBase', *args: Any, **kw: Any) -> None:

                if getattr(self, '_inited', False):

                    return

                own_init(self, *args, **kw)

            cls.__init__ = _guarded_init  # type: ignore[method-assign]



    def __init__(self, **kwargs: Unpack[ServiceClientInitParams]):

        '''初始化客户端通用运行态。



        Args:

            **kwargs: 客户端初始化参数，结构见 `ServiceClientInitParams`。

        '''

        if getattr(self, '_inited', False):

            return

        self._key: str | None = kwargs.get('key')

        _max_concurrent: int | ConcurrentPool | None = kwargs.get('max_concurrent')

        if isinstance(_max_concurrent, int):

            _max_concurrent = ConcurrentPool(max_concurrent=_max_concurrent)

        if isinstance(_max_concurrent, ConcurrentPool) and _max_concurrent.category is None:

            _max_concurrent.category = self.key

        self.max_concurrent: ConcurrentPool | None = _max_concurrent

        self.priority = float(kwargs.get('priority', 0.0))

        self.strategy_lvl: int = int(kwargs.get('strategy_lvl', StrategyLevel.LOAD_BALANCE))



        self._state_score: float = 1.0

        self._state_success_count: int = 0

        self._state_fail_count: int = 0

        self._state_cooldown_until: float = 0.0

        self._state_last_error: str | None = None

        self._state_inflight: int = 0

        self._state_speed_ewma: float = 0.0

        self._state_last_success_at: float = 0.0

        self._cached_session: aiohttp.ClientSession | None = None

        self._cached_session_limit: int | None = None

        self._cached_session_loop: asyncio.AbstractEventLoop | None = None

        self._cache_save_tasks: Queue[_CacheSaveTask] = Queue()

        self._cache_save_stop = threading.Event()

        self._cache_save_thread: threading.Thread | None = None

        self._cache_save_thread_lock = threading.Lock()

        self._closed: bool = False

        self._close_reason: str | None = None

        self._start_cache_save_worker()

        self._inited = True



    @property

    def key(self) -> str:

        '''客户端实例的唯一标识。



        若 ``__init__`` 传入了 ``key``，格式为 ``{Type}:{key}``；

        否则使用缓存哈希 ``{Type}:{cache_hash}``。

        '''

        prefix = self.Type or type(self).__name__

        if getattr(self, '_key', None) is not None:

            return f'{prefix}:{self._key}'

        cache_key = getattr(self, '_cache_key', None)

        if cache_key is not None:

            return f'{prefix}:{cache_key[1]}'

        return prefix



    def _ensure_open(self) -> None:

        if bool(getattr(self, '_closed', False)):

            reason = str(getattr(self, '_close_reason', None) or 'AI service runtime reload')

            raise RuntimeError(f'{type(self).__name__} instance was retired: {reason}')



    def _start_cache_save_worker(self) -> None:

        with self._cache_save_thread_lock:

            worker = self._cache_save_thread

            if worker is not None and worker.is_alive():

                return

            self._cache_save_stop.clear()

            worker = threading.Thread(

                target=self._cache_save_worker,

                name=f'{type(self).__name__}-cache-save',

                daemon=True,

            )

            self._cache_save_thread = worker

            worker.start()



    def queue_cache_save(

        self,

        *,

        merge_key: str,

        payload: Any,

        flush_many: Callable[[list[Any]], Any],

    ) -> None:

        if bool(getattr(self, '_closed', False)):

            return

        self._cache_save_tasks.put(_CacheSaveTask(

            merge_key=str(merge_key),

            payload=payload,

            flush_many=flush_many,

        ))



    def _drain_cache_save_tasks(self) -> list[_CacheSaveTask]:

        drained: list[_CacheSaveTask] = []

        while True:

            try:

                drained.append(self._cache_save_tasks.get_nowait())

            except QueueEmpty:

                return drained



    def _flush_cache_save_tasks(self, tasks: list[_CacheSaveTask]) -> None:

        if not tasks:

            return

        grouped: dict[str, list[_CacheSaveTask]] = {}

        for task in tasks:

            grouped.setdefault(task.merge_key, []).append(task)

        for grouped_tasks in grouped.values():

            flush_many = grouped_tasks[0].flush_many

            payloads = [task.payload for task in grouped_tasks]

            try:

                _run_any_func(flush_many, payloads)

            except Exception as exc:

                _base_logger.debug('Cache save flush failed for %s: %s', type(self).__name__, exc)



    def _cache_save_worker(self) -> None:

        pending: list[_CacheSaveTask] = []

        while True:

            if self._cache_save_stop.is_set():

                pending.extend(self._drain_cache_save_tasks())

                self._flush_cache_save_tasks(pending)

                return

            try:

                task = self._cache_save_tasks.get(timeout=1.0)

                pending.append(task)

            except QueueEmpty:

                ...

            pending.extend(self._drain_cache_save_tasks())

            if pending:

                self._flush_cache_save_tasks(pending)

                pending = []



    def _stop_cache_save_worker(self) -> None:

        self._cache_save_stop.set()

        worker = self._cache_save_thread

        if worker is None:

            return

        if worker.is_alive() and threading.current_thread() is not worker:

            worker.join(timeout=1.5)

        self._cache_save_thread = None



    async def _get_session(self) -> 'aiohttp.ClientSession':

        '''获取或创建可复用的 aiohttp 代理会话。



        若缓存的会话已关闭、``max_concurrent`` 发生变化或 event loop 不匹配则自动重建。

        连接池上限根据 ``max_concurrent`` 调整。

        '''

        import aiohttp as _aiohttp

        from core.utils.network_utils.proxy_requests import aiohttp_client_session



        self._ensure_open()



        mc = getattr(self, 'max_concurrent', None)

        if isinstance(mc, ConcurrentPool):

            limit = max(1, int(mc.max_concurrent))

        elif isinstance(mc, int) and mc > 0:

            limit = max(1, int(mc))

        else:

            limit = 100



        current_loop = asyncio.get_running_loop()

        s = getattr(self, '_cached_session', None)

        prev_limit = getattr(self, '_cached_session_limit', None)

        prev_loop = getattr(self, '_cached_session_loop', None)

        if s is not None and not s.closed and prev_limit == limit and prev_loop is current_loop:

            return s



        # limit 变化、session 已关闭或 event loop 不匹配 → 关掉旧的再重建

        if s is not None and not s.closed:

            if prev_loop is current_loop:

                await s.close()

            else:

                # 不能在错误的 loop 里直接 await close；尽量回到原 loop 关闭，失败则仅丢弃缓存。

                # 不要手工把 _connector 置空，否则旧请求若仍引用该 session，aiohttp 内部会触发

                # AttributeError: 'NoneType' object has no attribute '_timeout_ceil_threshold'.

                try:

                    if prev_loop is not None and not prev_loop.is_closed() and prev_loop.is_running():

                        close_future = asyncio.run_coroutine_threadsafe(s.close(), prev_loop)

                        close_future.result(timeout=1.0)

                except Exception:

                    pass



        connector = _aiohttp.TCPConnector(limit=limit, limit_per_host=limit)

        s = aiohttp_client_session(connector=connector)

        self._cached_session = s

        self._cached_session_limit = limit

        self._cached_session_loop = current_loop

        return s



    async def _close_session(self) -> None:

        '''关闭并丢弃缓存的 aiohttp 会话。'''

        s = getattr(self, '_cached_session', None)

        self._cached_session = None

        self._cached_session_limit = None

        self._cached_session_loop = None

        if s is not None and not s.closed:

            await s.close()



    def close(self, reason: str | None = None) -> None:

        '''作废客户端实例，并尽量终止其底层网络会话。'''

        self._closed = True

        self._close_reason = reason or 'AI service runtime reload'

        self._stop_cache_save_worker()

        s = getattr(self, '_cached_session', None)

        self._cached_session = None

        self._cached_session_limit = None

        self._cached_session_loop = None

        if s is None or s.closed:

            return

        try:

            _run_any_func(s.close)

        except Exception:

            pass



    def __del__(self):

        try:

            self.close(reason='Service client garbage collected')

        except Exception:

            pass



    @staticmethod

    def GetClientCls(type: str) -> 'type[ServiceClientBase] | None':  # noqa: A002

        '''根据注册的 type 字符串获取客户端类。'''

        return _CLIENT_TYPE_REGISTRY.get(_normalize_client_type(type))



    @classmethod

    def GetClient(cls, key: str) -> 'Self | None':

        '''根据 init 时传入的 key 获取已缓存的客户端实例。'''

        for (klass, cache_k), instance in list(cls._instance_cache.items()):

            if cache_k == key and issubclass(klass, cls):

                if bool(getattr(instance, '_closed', False)):

                    continue

                return instance

        return None



    @classmethod

    def RegisteredClientTypes(cls) -> list[str]:

        '''返回已注册的客户端 type 列表。'''

        values = [registered.Type or registered.__name__ for registered in _CLIENT_TYPE_REGISTRY.values()]

        return sorted({str(value) for value in values})



    @classmethod

    def ClearClientCache(cls, keys: set[str] | None = None, close: bool = True) -> int:

        '''清除客户端实例缓存。'''

        removed = 0

        for cache_key in list(cls._instance_cache.keys()):

            klass, raw_key = cache_key

            if not issubclass(klass, cls):

                continue

            if keys is not None and str(raw_key) not in keys:

                continue

            instance = cls._instance_cache.pop(cache_key, None)

            if close and instance is not None:

                try:

                    instance.close(reason='AI service runtime reload')

                except Exception:

                    pass

            removed += 1

        return removed



    @classmethod

    @abstractmethod

    def TestingInput(cls) -> ProbeInputT:

        '''返回该客户端类型用于健康探测的最小输入。



        Returns:

            适配当前客户端调用签名的最小探测输入。

        '''

        ...



    @abstractmethod

    async def probe_min_health(self) -> bool:

        '''异步执行客户端最小健康探测。



        Returns:

            探测成功返回 `True`，否则返回 `False`。

        '''

        ...



class ServiceBase(ServiceCallLogMixin, ABC, Generic[CT]):

    '''聚合服务调度基类。'''



    TempFileExpire: ClassVar[float] = 360.0

    '''Default TTL (seconds) for temporary files created via FileID during service calls.'''



    ProbeStatusFreshnessSeconds: ClassVar[float] = 30.0

    '''Shared probe/status freshness window used to skip redundant health probes.'''



    ServiceInstances: ClassVar[dict[tuple[type, str], 'ServiceBase']] = {}

    '''Global registry of keyed service instances: ``{(cls, key): instance}``.'''



    _default_creation_lock: ClassVar[threading.Lock]

    '''Per-subclass lock that serializes concurrent calls to Default().

    Automatically set for every concrete (and abstract) subclass via __init_subclass__.

    '''



    def __init_subclass__(cls, **kwargs) -> None:

        super().__init_subclass__(**kwargs)

        cls._default_creation_lock = threading.Lock()



    @classmethod

    def ServiceKind(cls) -> AIServiceKind | str:

        return _normalize_service_kind_name(cls)



    @classmethod

    def WaitUntilRuntimeReady(cls, timeout: float | None = None) -> None:

        wait_service_runtime_ready(cls.ServiceKind(), timeout=timeout)



    @classmethod

    async def AwaitRuntimeReady(cls, timeout: float | None = None) -> None:

        await await_service_runtime_ready(cls.ServiceKind(), timeout=timeout)



    @classmethod

    def ClearInstances(cls, *, keys: set[str] | None = None, close: bool = True) -> int:

        removed = 0

        for (klass, cache_key), instance in list(ServiceBase.ServiceInstances.items()):

            if not issubclass(klass, cls):

                continue

            if keys is not None and cache_key not in keys:

                continue

            ServiceBase.ServiceInstances.pop((klass, cache_key), None)

            if close:

                try:

                    instance.close()

                except Exception:

                    pass

            removed += 1

        return removed



    @classmethod

    def GetInstance(cls, key: str, fallback: str = 'default') -> 'Self | None':

        '''Retrieve a cached service instance by *key*.



        Looks up ``(cls, key)`` first, then falls back to ``(cls, fallback)``.



        Args:

            key: Instance key to look up.

            fallback: Fallback key when *key* is not found.  Default ``'default'``.



        Returns:

            The cached instance or ``None`` if neither key nor fallback exists.

        '''

        inst = cls.ServiceInstances.get((cls, key))

        if inst is not None:

            return cast('Self', inst)

        if fallback and fallback != key:

            inst = cls.ServiceInstances.get((cls, fallback))

            if inst is not None:

                return cast('Self', inst)

        return None



    @classmethod

    @abstractmethod

    def Default(cls) -> 'Self':

        '''创建该服务类型的默认实例。



        Returns:

            已配置好默认客户端的服务实例。

        '''

        ...



    _clients: list[ServiceClient[CT]]



    def __init__(self, *clients: CT | ServiceClient[CT], **kwargs: Unpack[ServiceInitParams]):

        '''初始化服务级调度参数。



        Args:

            *clients: 一个或多个真实 client，或带 service-local 调度覆写的 ServiceClient。

            **kwargs: 服务初始化参数，结构见 `ServiceInitParams`。

        '''

        fail_cooldown = float(kwargs.get('fail_cooldown', 10.0))

        recovery_interval = kwargs.get('recovery_interval')

        self._fail_cooldown = max(1.0, fail_cooldown)

        self._recovery_interval = max(1.0, recovery_interval) if recovery_interval is not None else None

        self._clients = [self._normalize_service_client(client) for client in clients]

        self._recovery_thread: threading.Thread | None = None

        self._recovery_stop_event = threading.Event()

        self._ewma_alpha = 0.2

        self._closed = False

        self._close_reason: str | None = None

        # Register keyed instance

        self._service_key: str | None = kwargs.get('key')  # type: ignore[typeddict-item]

        if self._service_key is not None:

            ServiceBase.ServiceInstances[(type(self), self._service_key)] = self



    @staticmethod

    def _normalize_service_client(client: CT | ServiceClient[CT]) -> ServiceClient[CT]:

        if isinstance(client, ServiceClient):

            return client

        return ServiceClient(client=client)



    @property

    def clients(self) -> list[CT]:

        return [binding.client for binding in self._clients]



    @classmethod

    def GetServiceClientEditableValues(cls) -> ServiceClientEditableValues:

        return {

            'priority': float,

            'strategy_lvl': StrategyLevel,

        }



    def _service_client_for(self, client: CT | ServiceClient[CT]) -> ServiceClient[CT]:

        if isinstance(client, ServiceClient):

            return client

        for binding in self._clients:

            if binding.client is client:

                return binding

        return ServiceClient(client=client)



    def _service_client_sequence(self, clients: Sequence[CT | ServiceClient[CT]]) -> list[ServiceClient[CT]]:

        return [self._service_client_for(client) for client in clients]



    def _find_service_client(self, client_key: str) -> ServiceClient[CT] | None:

        target = str(client_key or '').strip()

        if not target:

            return None

        for binding in self._clients:

            client = binding.client

            key = str(getattr(client, 'key', '') or '')

            if key == target:

                return binding

        return None



    async def set_client_value(self, client: str, field: str, value: Any) -> None:

        editable = self.GetServiceClientEditableValues()

        if field not in editable:

            raise ValueError(f'Client field {field!r} is not editable for {type(self).__name__}.')

        binding = self._find_service_client(client)

        if binding is None:

            raise KeyError(f'Client {client!r} is not attached to {type(self).__name__}.')

        if field == 'priority':

            binding.priority = None if value is None else float(value)

            return

        if field == 'strategy_lvl':

            binding.strategy_lvl = None if value is None else StrategyLevel(int(value))

            return

        setattr(binding, field, value)



    async def set_client_priority(self, client: str, priority: float | None) -> None:

        await self.set_client_value(client, 'priority', priority)



    async def set_client_strategy_lvl(self, client: str, lvl: StrategyLevel | int | None) -> None:

        await self.set_client_value(client, 'strategy_lvl', lvl)



    def _ensure_open(self) -> None:

        if bool(getattr(self, '_closed', False)):

            reason = str(getattr(self, '_close_reason', None) or 'AI service runtime reload')

            raise RuntimeError(f'{type(self).__name__} instance was retired: {reason}')

    

    def _should_skip_probe_from_shared_status(

        self,

        client: ServiceClientBase,

        *,

        now: float | None = None,

    ) -> bool:

        """判断当前已加载的共享状态是否足以跳过真实 probe。



        仅当共享状态表明客户端已经恢复，或仍处于其他 worker 刚写入的冷却期内时，

        才跳过本地 probe。对于“状态很新鲜但冷却已过期”的失败记录，必须重新实测，

        否则恢复线程会被 freshness 窗口错误地抑制。

        """

        runtime = cast(_RuntimeManagedClient, client)

        current_time = time.time() if now is None else float(now)

        last_success = float(getattr(runtime, '_state_last_success_at', 0.0))

        recovery_interval = float(self._recovery_interval or 300.0)

        if last_success > 0 and (current_time - last_success) < recovery_interval:

            return True

        fail_count = int(getattr(runtime, '_state_fail_count', 0))

        cooldown_until = float(getattr(runtime, '_state_cooldown_until', 0.0))

        if fail_count <= 0:

            return True

        return cooldown_until > current_time



    def close(self) -> None:

        '''停止后台恢复线程并释放服务级运行资源。'''

        if bool(getattr(self, '_closed', False)):

            return

        self._closed = True

        self._close_reason = 'AI service runtime reload'

        self._recovery_stop_event.set()

        thread = self._recovery_thread

        if thread is not None and thread.is_alive() and thread is not threading.current_thread():

            thread.join(timeout=1.0)

        self._recovery_thread = None

        for binding in list(getattr(self, '_clients', ()) or ()):

            client = binding.client

            close = getattr(client, 'close', None)

            if callable(close):

                try:

                    close(reason=self._close_reason)

                except Exception:

                    pass



    def __del__(self):

        try:

            self.close()

        except Exception:

            pass



    def _ensure_recovery_task(self) -> None:

        if self._recovery_interval is None:

            return

        if self._recovery_thread and self._recovery_thread.is_alive():

            return

        self._recovery_stop_event.clear()

        self._recovery_thread = threading.Thread(

            target=self._run_recovery_loop,

            name=f'{type(self).__name__}-health-check',

            daemon=True,

        )

        self._recovery_thread.start()



    def _run_recovery_loop(self) -> None:

        try:

            _run_any_func(self._recovery_loop)

        except Exception:

            pass



    async def _wait_recovery_interval(self) -> bool:

        assert self._recovery_interval is not None

        deadline = time.monotonic() + self._recovery_interval

        while not self._recovery_stop_event.is_set():

            remaining = deadline - time.monotonic()

            if remaining <= 0:

                return False

            await asyncio.sleep(min(remaining, 0.25))

        return True



    async def _recovery_loop(self) -> None:

        assert self._recovery_interval is not None

        while not await self._wait_recovery_interval():

            try:

                now = time.time()

                for client in getattr(self, 'clients', []):

                    if float(client._state_cooldown_until) <= now:

                        if await self._load_client_status_from_shared(

                            client,

                        ) and self._should_skip_probe_from_shared_status(client, now=now):

                            continue

                        if await self._probe_client_min_health(client):

                            client._state_score = min(1.0, float(client._state_score) + 0.15)

                            client._state_last_success_at = time.time()

                            if int(client._state_fail_count) > 0:

                                client._state_fail_count = max(0, int(client._state_fail_count) - 2)

                            if int(client._state_fail_count) <= 0:

                                client._state_cooldown_until = 0.0

                            await _async_run_any_func(self._sync_client_status_to_shared, client)

                        else:

                            fail_count = int(getattr(client, '_state_fail_count', 0)) + 1

                            client._state_fail_count = fail_count

                            client._state_score = max(0.05, float(getattr(client, '_state_score', 1.0)) * 0.7)

                            client._state_cooldown_until = time.time() + min(self._fail_cooldown * (2 ** min(fail_count, 5)), 1800.0)

            except Exception:

                pass



    async def _probe_client_min_health(self, client: ServiceClientBase) -> bool:

        probe = getattr(client, 'probe_min_health', None)

        if not callable(probe):

            return False

        snapshot = dict(vars(client))

        _runtime_keys = frozenset({

            'max_concurrent', 'priority', 'strategy_lvl',

            '_state_score', '_state_success_count', '_state_fail_count',

            '_state_cooldown_until', '_state_last_error', '_state_inflight',

            '_state_speed_ewma', '_state_last_success_at',

            '_cached_session', '_cached_session_limit', '_cached_session_loop',

        })

        try:

            return bool(await _async_run_any_func(cast(Callable[[], object], probe)))

        except Exception:

            return False

        finally:

            current = vars(client)

            for key in list(current.keys()):

                if key not in snapshot:

                    current.pop(key, None)

            for key, val in snapshot.items():

                if key not in _runtime_keys and not callable(val):

                    current[key] = val



    def _should_probe_on_init(self, client: ServiceClientBase) -> bool:

        '''仅对真正的 ServiceClient 做初始化探测，避免把 Service 误当作 client。'''

        return isinstance(client, ServiceClientBase) and not isinstance(client, ServiceBase)



    async def _sync_client_status_to_shared(self, client: ServiceClientBase) -> None:

        """将客户端运行状态写入跨进程共享上下文。"""

        from .shared import AIServiceSharedContext

        try:

            ctx = AIServiceSharedContext.Get()

            runtime = cast(_RuntimeManagedClient, client)

            client_hash = compute_client_hash(client)

            await _async_run_any_func(ctx.update_client_status, client_hash, {

                'score': float(getattr(runtime, '_state_score', 1.0)),

                'fail_count': int(getattr(runtime, '_state_fail_count', 0)),

                'cooldown_until': float(getattr(runtime, '_state_cooldown_until', 0.0)),

                'last_error': getattr(runtime, '_state_last_error', None),

                'speed_ewma': float(getattr(runtime, '_state_speed_ewma', 0.0)),

                'last_success_at': float(getattr(runtime, '_state_last_success_at', 0.0)),

            })

        except Exception:

            pass



    async def _load_client_status_from_shared(

        self,

        client: ServiceClientBase,

        *,

        max_age: float | None = None,

    ) -> bool:

        """从跨进程共享上下文读取客户端状态（若足够新鲜）。



        Returns:

            True 如果成功加载了新鲜状态，False 否则。

        """

        from .shared import AIServiceSharedContext

        try:

            ctx = AIServiceSharedContext.Get()

            client_hash = compute_client_hash(client)

            freshness_window = float(

                self.ProbeStatusFreshnessSeconds if max_age is None else max_age,

            )

            if freshness_window <= 0:

                return False

            if not await _async_run_any_func(

                ctx.is_client_status_fresh,

                client_hash,

                max_age=freshness_window,

            ):

                return False

            status = await _async_run_any_func(ctx.get_client_status, client_hash)

            if status is None:

                return False

            runtime = cast(_RuntimeManagedClient, client)

            if 'score' in status:

                runtime._state_score = float(status['score'])

            if 'fail_count' in status:

                runtime._state_fail_count = int(status['fail_count'])

            if 'cooldown_until' in status:

                runtime._state_cooldown_until = float(status['cooldown_until'])

            if 'last_error' in status:

                runtime._state_last_error = status['last_error']

            if 'speed_ewma' in status:

                runtime._state_speed_ewma = float(status['speed_ewma'])

            if 'last_success_at' in status:

                runtime._state_last_success_at = float(status['last_success_at'])

            return True

        except Exception:

            return False



    async def _probe_all_clients_on_init(self) -> None:

        '''并发探测所有客户端的最小健康状态，用于 init 阶段快速掌握各客户端情况。



        优先从跨进程共享上下文加载近期状态，仅在状态不新鲜时才执行实际 probe。

        探测结果同步写回共享上下文供其他进程复用。

        '''

        clients = [

            client for client in getattr(self, 'clients', [])

            if self._should_probe_on_init(client)

        ]

        if not clients:

            return

        async def _probe_one(client: ServiceClientBase) -> None:

            try:

                # Try loading fresh status from shared context first

                if (

                    await _async_run_any_func(self._load_client_status_from_shared, client)

                    and self._should_skip_probe_from_shared_status(client)

                ):

                    return  # Status is fresh, skip probing



                pre_fail_count = int(getattr(client, '_state_fail_count', 0))

                healthy = await self._probe_client_min_health(client)

                runtime = cast(_RuntimeManagedClient, client)

                # Only update state if no concurrent _on_fail changed it during the probe

                if int(getattr(runtime, '_state_fail_count', 0)) != pre_fail_count:

                    return  # state was modified concurrently, skip updating

                if healthy:

                    runtime._state_score = min(1.0, float(getattr(runtime, '_state_score', 1.0)) + 0.2)

                    runtime._state_cooldown_until = 0.0

                else:

                    # Mark client as initially degraded

                    runtime._state_score = max(0.05, float(getattr(runtime, '_state_score', 1.0)) * 0.7)

                # Sync probe result to shared context

                await _async_run_any_func(self._sync_client_status_to_shared, client)

            except Exception:

                pass



        await asyncio.gather(*(_probe_one(c) for c in clients), return_exceptions=True)



    def _start_init_probe(self) -> None:

        '''在后台线程中启动初始化探测（不阻塞 __init__）。'''

        t = threading.Thread(

            target=self._run_init_probe,

            name=f'{type(self).__name__}-init-probe',

            daemon=True,

        )

        t.start()



    def _run_init_probe(self) -> None:

        try:

            _run_any_func(self._probe_all_clients_on_init)

        except Exception:

            pass



    async def _can_accept(self, client: ServiceClientBase) -> bool:

        if bool(getattr(client, '_closed', False)):

            return False

        max_concurrent = getattr(client, 'max_concurrent', None)

        if max_concurrent is None:

            return True

        if isinstance(max_concurrent, ConcurrentPool):

            return await max_concurrent.can_accept(compute_client_hash(client))

        inflight = int(getattr(client, '_state_inflight', 0))

        return inflight < int(max_concurrent)



    async def _state_rank_score(self, binding: ServiceClient[ClientT]) -> float:

        client = binding.client

        score = float(getattr(client, '_state_score', 1.0))

        speed = float(getattr(client, '_state_speed_ewma', 0.0))

        priority = binding.get_priority()

        multimodal_bonus = float(getattr(client, '_state_multimodal_bonus', 0.0))

        max_concurrent = getattr(client, 'max_concurrent', None)

        inflight = int(getattr(client, '_state_inflight', 0))

        success_count = int(getattr(client, '_state_success_count', 0))

        if isinstance(max_concurrent, ConcurrentPool):

            pool_count = await max_concurrent.get_count(compute_client_hash(client))

            load_penalty = pool_count / max(1, max_concurrent.max_concurrent)

        elif max_concurrent is None or int(max_concurrent) <= 0:

            load_penalty = inflight * 0.02

        else:

            load_penalty = inflight / max(1, int(max_concurrent))

        speed_component = speed * 0.4 if speed > 0 else score * 0.2

        reliability = min(1.0, success_count / 10.0) * 0.1 if success_count > 0 else 0.0

        return speed_component + (score * 0.3) + reliability - (priority * 0.2) - (load_penalty * 0.5) + multimodal_bonus



    async def _sorted_service_clients(self, clients: Sequence[ClientT | ServiceClient[ClientT]]) -> list[ServiceClient[ClientT]]:

        bindings = self._service_client_sequence(clients)

        now = time.time()

        decorated: list[tuple[tuple[bool, bool, float, float], ServiceClient[ClientT]]] = []

        for binding in bindings:

            client = binding.client

            decorated.append((

                (

                    float(getattr(client, '_state_cooldown_until', 0.0)) > now,

                    not await self._can_accept(client),

                    -await self._state_rank_score(binding),

                    binding.get_priority(),

                ),

                binding,

            ))

        decorated.sort(key=lambda item: item[0])

        return [binding for _, binding in decorated]



    async def _sorted_clients(self, clients: Sequence[ClientT | ServiceClient[ClientT]]) -> list[ClientT]:

        return [binding.client for binding in await self._sorted_service_clients(clients)]



    def _measure_speed(self, client: ServiceClientBase, elapsed: float, result: object) -> float:

        return 0.0 if elapsed <= 0 else (1.0 / elapsed)



    def _update_speed(self, client: ServiceClientBase, speed: float) -> None:

        if speed <= 0:

            return

        runtime_client = cast(_RuntimeManagedClient, client)

        prev = float(getattr(runtime_client, '_state_speed_ewma', 0.0))

        if prev <= 0:

            runtime_client._state_speed_ewma = speed

        else:

            runtime_client._state_speed_ewma = (1 - self._ewma_alpha) * prev + self._ewma_alpha * speed



    async def _on_success(self, client: ServiceClientBase) -> None:

        runtime_client = cast(_RuntimeManagedClient, client)

        runtime_client._state_success_count = int(getattr(runtime_client, '_state_success_count', 0)) + 1

        runtime_client._state_score = min(1.0, float(getattr(runtime_client, '_state_score', 1.0)) + 0.2)

        runtime_client._state_cooldown_until = 0.0

        runtime_client._state_last_error = None

        runtime_client._state_last_success_at = time.time()

        if int(runtime_client._state_fail_count) > 0:

            runtime_client._state_fail_count = max(0, int(runtime_client._state_fail_count) - 1)

        await _async_run_any_func(self._sync_client_status_to_shared, client)



    def _classify_error(self, exc: Exception) -> Literal['ratelimit', 'timeout', 'transient', 'permanent']:

        exc_type = type(exc).__name__.lower()

        exc_msg = str(exc).lower()

        if any(kw in exc_type for kw in ('ratelimit', 'rate_limit')):

            return 'ratelimit'

        if any(kw in exc_msg for kw in ('rate limit', 'rate_limit', 'ratelimit', '429', 'too many requests', 'quota exceeded')):

            return 'ratelimit'

        if isinstance(exc, asyncio.TimeoutError):

            return 'timeout'

        if 'timeout' in exc_type:

            return 'timeout'

        if any(kw in exc_msg for kw in ('unauthorized', 'forbidden', 'invalid api key', 'authentication failed', '404')):

            return 'permanent'

        return 'transient'



    async def _on_fail(self, client: ServiceClientBase, exc: Exception) -> None:

        runtime_client = cast(_RuntimeManagedClient, client)

        error_kind = self._classify_error(exc)

        fail_count = int(getattr(runtime_client, '_state_fail_count', 0)) + 1

        runtime_client._state_fail_count = fail_count

        runtime_client._state_last_error = f'{type(exc).__name__}: {exc}'

        if error_kind == 'ratelimit':

            runtime_client._state_score = max(0.3, float(getattr(runtime_client, '_state_score', 1.0)) * 0.85)

            runtime_client._state_cooldown_until = time.time() + min(self._fail_cooldown * 0.5 * (2 ** min(fail_count, 3)), 120.0)

        elif error_kind == 'timeout':

            runtime_client._state_score = max(0.1, float(getattr(runtime_client, '_state_score', 1.0)) * 0.7)

            runtime_client._state_cooldown_until = time.time() + min(self._fail_cooldown * (2 ** min(fail_count, 4)), 600.0)

        elif error_kind == 'permanent':

            runtime_client._state_score = max(0.01, float(getattr(runtime_client, '_state_score', 1.0)) * 0.3)

            runtime_client._state_cooldown_until = time.time() + min(self._fail_cooldown * (2 ** min(fail_count, 6)), 3600.0)

        else:

            runtime_client._state_score = max(0.05, float(getattr(runtime_client, '_state_score', 1.0)) * 0.5)

            runtime_client._state_cooldown_until = time.time() + min(self._fail_cooldown * (2 ** min(fail_count, 5)), 1800.0)

        await _async_run_any_func(self._sync_client_status_to_shared, client)



    def _client_display_name(self, client: ServiceClientBase) -> str:

        return type(client).__name__



    def _service_client_groups(self, clients: Sequence[ClientT | ServiceClient[ClientT]]) -> list[list[ServiceClient[ClientT]]]:

        max_lvl = max((int(v) for v in StrategyLevel), default=0)

        groups: list[list[ServiceClient[ClientT]]] = [[] for _ in range(max_lvl + 1)]

        for binding in self._service_client_sequence(clients):

            lvl = min(max_lvl, max(0, int(binding.get_strategy_lvl())))

            groups[lvl].append(binding)

        return groups



    def _strategy_groups(self, clients: Sequence[ClientT | ServiceClient[ClientT]]) -> list[list[ClientT]]:

        return [[binding.client for binding in group] for group in self._service_client_groups(clients)]



    async def _run_with_failover(

        self,

        clients: Sequence[ClientT | ServiceClient[ClientT]],

        action: Callable[[ClientT], Awaitable[RunResultT | tuple[RunResultT, float]]],

        *,

        error_prefix: str,

    ) -> RunResultT:

        self._ensure_open()

        self._ensure_recovery_task()

        errors: list[str] = []

        grouped_clients = self._service_client_groups(clients)

        cooldown_blocked: list[ServiceClient[ClientT]] = []



        for tier_clients in grouped_clients:

            if not tier_clients:

                continue



            tried_any = False

            for binding in await self._sorted_service_clients(tier_clients):

                client = binding.client

                self._ensure_open()

                if bool(getattr(client, '_closed', False)):

                    errors.append(f'[{self._client_display_name(client)}] RuntimeError: client retired during AI service reload')

                    continue

                cooldown_until = float(getattr(client, '_state_cooldown_until', 0.0))

                if cooldown_until > time.time():

                    if await self._can_accept(client):

                        cooldown_blocked.append(binding)

                    continue

                if not await self._can_accept(client):

                    continue



                tried_any = True

                runtime_client = cast(_RuntimeManagedClient, client)

                runtime_client._state_inflight = int(getattr(runtime_client, '_state_inflight', 0)) + 1



                _pool: ConcurrentPool | None = None

                _pool_key: str = ''

                mc = runtime_client.max_concurrent

                if isinstance(mc, ConcurrentPool):

                    _pool_key = compute_client_hash(client)

                    await mc.acquire(_pool_key)

                    _pool = mc



                started_at = time.perf_counter()

                try:

                    action_result = await action(client)

                    elapsed = max(1e-6, time.perf_counter() - started_at)

                    result: RunResultT = cast(RunResultT, action_result)

                    speed_override_workload: float | None = None

                    if isinstance(action_result, tuple) and len(action_result) == 2 and isinstance(action_result[1], (int, float)):

                        result = cast(RunResultT, action_result[0])

                        speed_override_workload = float(action_result[1])



                    speed = (speed_override_workload / elapsed) if (speed_override_workload is not None and speed_override_workload > 0) else self._measure_speed(client, elapsed, result)

                    self._update_speed(client, speed)

                    await self._on_success(client)

                    return result

                except Exception as exc:

                    await self._on_fail(client, exc)

                    errors.append(f'[{self._client_display_name(client)}] {type(exc).__name__}: {exc}')

                finally:

                    runtime_client._state_inflight = max(0, int(getattr(runtime_client, '_state_inflight', 1)) - 1)

                    if _pool is not None:

                        await _pool.release(_pool_key)



            if tried_any:

                continue



        # Fallback: 有客户端仅因 cooldown 被跳过（可能来自 shared context 污染），

        # 清除 cooldown 后强制重试最佳候选

        if not errors and cooldown_blocked:

            best_binding = cooldown_blocked[0]

            best = best_binding.client

            runtime_client = cast(_RuntimeManagedClient, best)

            runtime_client._state_cooldown_until = 0.0

            runtime_client._state_inflight = int(getattr(runtime_client, '_state_inflight', 0)) + 1



            _pool: ConcurrentPool | None = None

            _pool_key = ''

            mc = runtime_client.max_concurrent

            if isinstance(mc, ConcurrentPool):

                _pool_key = compute_client_hash(best)

                await mc.acquire(_pool_key)

                _pool = mc



            started_at = time.perf_counter()

            try:

                action_result = await action(best)

                elapsed = max(1e-6, time.perf_counter() - started_at)

                result = cast(RunResultT, action_result)

                speed_override_workload: float | None = None

                if isinstance(action_result, tuple) and len(action_result) == 2 and isinstance(action_result[1], (int, float)):

                    result = cast(RunResultT, action_result[0])

                    speed_override_workload = float(action_result[1])

                speed = (speed_override_workload / elapsed) if (speed_override_workload is not None and speed_override_workload > 0) else self._measure_speed(best, elapsed, result)

                self._update_speed(best, speed)

                await self._on_success(best)

                return result

            except Exception as exc:

                await self._on_fail(best, exc)

                errors.append(f'[{self._client_display_name(best)}] {type(exc).__name__}: {exc}')

            finally:

                runtime_client._state_inflight = max(0, int(getattr(runtime_client, '_state_inflight', 1)) - 1)

                if _pool is not None:

                    await _pool.release(_pool_key)



        raise RuntimeError(f'{error_prefix}. ' + ' | '.join(errors))





# ══════════════════════════════════════════════════════════════════════════════

# SSH tunnel URL rewriting

# ══════════════════════════════════════════════════════════════════════════════



def _rewrite_url_for_ssh_tunnel(url: str, ssh_tunnel: 'SSHTunnelConfig') -> str:

    '''Rewrite a remote URL to point at the local SSH-forwarded port.



    Extracts the port from *url*, opens the tunnel, and replaces host:port

    with ``127.0.0.1:<local_port>``.

    '''

    parsed = urlparse(url)

    remote_port = parsed.port

    if remote_port is None:

        remote_port = 443 if parsed.scheme == 'https' else 80

    local_port = ssh_tunnel.open_tunnel(remote_port)

    netloc = f'127.0.0.1:{local_port}'

    return urlunparse(parsed._replace(netloc=netloc, scheme='http'))



def _apply_ssh_tunnel_to_tts_client(

    tts_client: 'ThinkThinkSyn',

    ssh_tunnel: 'SSHTunnelConfig',

) -> 'ThinkThinkSyn':

    '''Rewrite the base_url of a ThinkThinkSyn client through an SSH tunnel.'''

    base_url = getattr(tts_client, 'base_url', None) or getattr(tts_client, '_base_url', None)

    if not base_url:

        raise ValueError('Cannot apply SSH tunnel: ThinkThinkSyn client has no base_url')

    new_url = _rewrite_url_for_ssh_tunnel(str(base_url), ssh_tunnel)

    if hasattr(tts_client, 'base_url'):

        tts_client.base_url = new_url

    elif hasattr(tts_client, '_base_url'):

        tts_client._base_url = new_url  # type: ignore

    return tts_client





SSHTunnelConfigType = None  # forward reference placeholder



def _resolve_ssh_tunnel_config(

    ssh_tunnel: 'SSHTunnelConfig | dict[str, Any] | str | None',

) -> 'SSHTunnelConfig | None':

    '''Accept SSHTunnelConfig | dict | str | None and return SSHTunnelConfig | None.'''

    if ssh_tunnel is None:

        return None

    from core.utils.network_utils.ssh_tunnel import SSHTunnelConfig

    if isinstance(ssh_tunnel, SSHTunnelConfig):

        return ssh_tunnel

    if isinstance(ssh_tunnel, str):

        return SSHTunnelConfig(ssh_host=ssh_tunnel)

    if isinstance(ssh_tunnel, dict):

        return SSHTunnelConfig(**ssh_tunnel)

    return ssh_tunnel





__all__ += [

    'InferenceContext',

    'ServiceCallTraceRecordInput',

    'ServiceCallLogRecord',

    'ServiceCallStatRecord',

    'ServiceRuntimeState',

    'await_service_runtime_ready',

    'get_service_runtime_state',

    'StrategyLevel',

    'ServiceClientInitParams',

    'ServiceInitParams',

    'ServiceClient',

    'ServiceClientEditableValues',

    'ServiceParamsBase',

    'ServiceCallLogMixin',

    'ServiceCallTraceStore',

    'set_service_runtime_reloading',

    'ServiceClientBase',

    'ServiceBase',

    'ConcurrentPool',

    'compute_client_hash',

    'wait_service_runtime_ready',

]

