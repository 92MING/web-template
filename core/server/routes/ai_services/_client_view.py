# -*- coding: utf-8 -*-
"""共享 AI 服务实例 / client 状态视图 (Sec 5.1)。

供 ``api.py`` 暴露给外部的 ``/api/ai/services`` 系列端点使用,语义为
"按 service kind 聚合实例与 client",不重叠 ``panel.py`` 内部 admin 视图。
"""

from __future__ import annotations

import time as _time
from typing import TYPE_CHECKING

from core.utils.type_utils import AdvancedBaseModel
from core.ai.shared import AIServiceKind

if TYPE_CHECKING:
    from core.ai.base import ServiceBase, ServiceClient, ServiceClientBase


_KIND_TO_SERVICE_NAME: dict[AIServiceKind, str] = {
    'completion': 'CompletionService',
    'embedding': 'EmbeddingService',
    's2t': 'S2TService',
    't2s': 'T2SService',
}


def _get_service_class(kind: AIServiceKind) -> 'type[ServiceBase] | None':
    from core.ai import (
        CompletionService, EmbeddingService, S2TService, T2SService,
    )
    return {
        'completion': CompletionService,
        'embedding': EmbeddingService,
        's2t': S2TService,
        't2s': T2SService,
    }.get(kind)


# ══════════════════════════════════════════════════════════════════════════════
# Response models
# ══════════════════════════════════════════════════════════════════════════════

class AIServiceClientInfo(AdvancedBaseModel):
    key: str
    """ServiceClientBase._service_key / cache key。"""
    type: str
    """ServiceClientBase.Type 厂商标识 (e.g. 'tts-completion', 'openrouter-completion')。"""
    available: bool
    """当前不处冷却且最近一次 probe 不为 fail。"""
    strategy_lvl: int
    """0/1/2 调度等级。"""
    priority: float = 0.0
    """当前 service binding 的有效调度优先级。"""
    max_concurrent: int | None
    """ConcurrentPool.max_concurrent;None 表示不限。"""
    inflight: int
    """当前在途请求数。"""
    cooldown_until: float
    """冷却截止时间戳。"""
    last_error: str | None
    """最近一次错误文本。"""
    last_success_at: float
    """最近一次成功时间戳。"""
    fail_count: int
    """累计失败次数。"""
    success_count: int
    """累计成功次数。"""
    score: float
    """调度评分。"""
    speed_ewma: float
    """speed EWMA (作为 latency 代理)。"""


class AIServiceInstanceInfo(AdvancedBaseModel):
    key: str
    """ServiceBase._service_key (e.g. 'default')。"""
    available: bool
    """instance 下任一 client available。"""
    clients: list[str]
    """实例下属 client 的 key 序列;详细数据从顶层 dict 查。"""
    max_concurrent: int | None
    """仅 strategy_lvl <= 1 的 client max_concurrent 求和;任一为 None 则本字段为 None。"""
    avg_speed_ewma: float
    """该实例下所有 client speed_ewma 均值。"""
    inflight_total: int
    """sum(c.inflight)。"""


class AIServiceInfo(AdvancedBaseModel):
    kind: AIServiceKind
    """Service 类型。"""
    instances: dict[str, AIServiceInstanceInfo]
    """实例 key → 实例信息。"""
    clients: dict[str, AIServiceClientInfo]
    """client key → client 信息 (跨实例去重)。"""


# ══════════════════════════════════════════════════════════════════════════════
# Builders
# ══════════════════════════════════════════════════════════════════════════════

def build_client_info(client: 'ServiceClientBase | ServiceClient[ServiceClientBase]') -> AIServiceClientInfo:
    binding = client if hasattr(client, 'client') and hasattr(client, 'get_priority') else None
    real_client = binding.client if binding is not None else client
    mc_obj = getattr(client, 'max_concurrent', None)
    if binding is not None:
        mc_obj = getattr(real_client, 'max_concurrent', None)
    mc_val: int | None = None
    if isinstance(mc_obj, int):
        mc_val = mc_obj
    elif mc_obj is not None and hasattr(mc_obj, 'max_concurrent'):
        mc_val = getattr(mc_obj, 'max_concurrent', None)

    cooldown_until = float(getattr(real_client, '_state_cooldown_until', 0.0) or 0.0)
    err = getattr(real_client, '_state_last_error', None)
    err_text = str(err) if err else None
    available = (cooldown_until <= _time.time()) and not err_text
    strategy_lvl = int(binding.get_strategy_lvl()) if binding is not None else int(getattr(real_client, 'strategy_lvl', 0) or 0)
    priority = float(binding.get_priority()) if binding is not None else float(getattr(real_client, 'priority', 0.0) or 0.0)

    return AIServiceClientInfo(
        key=str(getattr(real_client, 'key', '') or ''),
        type=str(getattr(real_client, 'Type', '') or ''),
        available=available,
        strategy_lvl=strategy_lvl,
        priority=priority,
        max_concurrent=mc_val,
        inflight=int(getattr(real_client, '_state_inflight', 0) or 0),
        cooldown_until=cooldown_until,
        last_error=err_text,
        last_success_at=float(getattr(real_client, '_state_last_success_at', 0.0) or 0.0),
        fail_count=int(getattr(real_client, '_state_fail_count', 0) or 0),
        success_count=int(getattr(real_client, '_state_success_count', 0) or 0),
        score=float(getattr(real_client, '_state_score', 1.0) or 0.0),
        speed_ewma=float(getattr(real_client, '_state_speed_ewma', 0.0) or 0.0),
    )


def build_instance_info(
    instance_key: str,
    clients_info: list[AIServiceClientInfo],
) -> AIServiceInstanceInfo:
    if not clients_info:
        return AIServiceInstanceInfo(
            key=instance_key, available=False, clients=[],
            max_concurrent=0, avg_speed_ewma=0.0, inflight_total=0,
        )
    available = any(c.available for c in clients_info)
    inflight_total = sum(c.inflight for c in clients_info)
    relevant_mc = [c.max_concurrent for c in clients_info if c.strategy_lvl <= 1]
    if any(mc is None for mc in relevant_mc):
        max_concurrent: int | None = None
    else:
        max_concurrent = sum(int(mc or 0) for mc in relevant_mc)
    avg_speed_ewma = sum(c.speed_ewma for c in clients_info) / float(len(clients_info))
    return AIServiceInstanceInfo(
        key=instance_key,
        available=available,
        clients=[c.key for c in clients_info],
        max_concurrent=max_concurrent,
        avg_speed_ewma=avg_speed_ewma,
        inflight_total=inflight_total,
    )


def build_service_info(kind: AIServiceKind) -> AIServiceInfo:
    """收集指定 kind 下所有已注册实例 + client,聚合为 AIServiceInfo。

    若没有任何实例 (服务未初始化),则返回 instances/clients 均为空字典的对象。
    """
    from core.ai.base import ServiceBase

    svc_cls = _get_service_class(kind)
    instances: dict[str, AIServiceInstanceInfo] = {}
    clients: dict[str, AIServiceClientInfo] = {}
    if svc_cls is None:
        return AIServiceInfo(kind=kind, instances=instances, clients=clients)

    for (cls, instance_key), instance in list(ServiceBase.ServiceInstances.items()):
        if cls is not svc_cls:
            continue
        instance_clients_info: list[AIServiceClientInfo] = []
        for client in getattr(instance, '_clients', []) or []:
            info = build_client_info(client)
            instance_clients_info.append(info)
            clients.setdefault(info.key, info)
        instances[instance_key] = build_instance_info(instance_key, instance_clients_info)

    return AIServiceInfo(kind=kind, instances=instances, clients=clients)


def build_all_services_info() -> list[AIServiceInfo]:
    return [build_service_info(kind) for kind in ('completion', 'embedding', 's2t', 't2s')]
