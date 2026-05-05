# -*- coding: utf-8 -*-
"""AI services admin panel routes — overview, settings, runtime reload."""


import os
import time
import json
import asyncio
import inspect
import logging
from pathlib import Path
from typing import Literal, TypedDict, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ConfigDict, Field

from core.utils.type_utils import AdvancedBaseModel
from core.ai import (
    clear_runtime_services,
    get_predefined_service_kinds,
    preload_default_services,
)
from core.ai.shared import AIServiceKind, ConcurrentPool
from core.ai.base import (
    ServiceClient,
    ServiceClientBase,
    set_service_runtime_reloading,
)
from core.ai.config import AIServicesConfig
from core.constants import PROJECT_DIR

from ._client_view import build_client_info as build_ai_service_client_info
from ...html_injection import html_response_from_path
from ...app import get_resources, internal_admin_path, on_before_app_created, send_message_to_worker
from ...shared import (
    AIServiceConfigSnapshot,
    AIServiceReloadStateRow,
    AIServiceRuntimeUpdateResult,
    AppSharedData,
    WorkerAIServiceClientValueMessage,
    WorkerAIServiceReloadMessage,
    WorkerSnapshot,
)

logger = logging.getLogger("proj-template.ai_services_panel")
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}
type AIServiceConfigSource = Literal["shared-runtime", "process-env", "defaults"]


class AIServiceSyncInfo(TypedDict):
    config: AIServicesConfig | None
    version: int
    source: AIServiceConfigSource

# ══════════════════════════════════════════════════════════════════════════════
# Response models
# ══════════════════════════════════════════════════════════════════════════════

class ClientStatusInfo(AdvancedBaseModel):
    type: str | None = None
    key: str = ""
    config_key: str | None = None
    score: float = 1.0
    fail_count: int = 0
    success_count: int = 0
    cooldown_until: float = 0.0
    last_error: str | None = None
    speed_ewma: float = 0.0
    last_success_at: float = 0.0
    priority: float = 0.0
    strategy_lvl: int = 0
    max_concurrent: int | None = None
    inflight: int = 0
    init_snapshot: dict[str, object] = Field(default_factory=dict)
    internal: bool = False


class ServiceInstanceInfo(AdvancedBaseModel):
    service_kind: AIServiceKind | None = None
    service_type: str
    key: str
    fail_cooldown: float = 10.0
    recovery_interval: float | None = None
    client_count: int = 0
    clients: list[ClientStatusInfo] = Field(default_factory=list)


class AIServicesOverviewResponse(AdvancedBaseModel):
    services: list[ServiceInstanceInfo] = Field(default_factory=list)
    config_loaded: bool = False
    config_source: str = "defaults"
    config_version: int = 0
    reload_state: list['AIServiceReloadStateInfo'] = Field(default_factory=list)
    timestamp: float = 0.0


class AIServicesPanelResponseModel(AdvancedBaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, use_attribute_docstrings=True)


class AIServiceWorkerInfo(AIServicesPanelResponseModel):
    pid: int | None = None
    status: str | None = None
    request_count: int | None = None
    started_at: str | None = None
    last_request_at: str | None = None
    lifespan_ready: bool | None = None


class AIServiceReloadStateInfo(AIServicesPanelResponseModel):
    pid: int | None = None
    version: int | None = None
    state: str | None = None
    service_kinds: list[AIServiceKind] = Field(default_factory=list)
    error: str | None = None
    ok: bool | None = None


class AIServicesSettingsResponse(AdvancedBaseModel):
    config_loaded: bool
    config_source: str
    config_version: int
    config: AIServicesConfig
    client_types: list[str] = Field(default_factory=list)
    service_kinds: list[AIServiceKind] = Field(default_factory=list)
    workers: list[AIServiceWorkerInfo] = Field(default_factory=list)
    reload_state: list[AIServiceReloadStateInfo] = Field(default_factory=list)
    services: list[ServiceInstanceInfo] = Field(default_factory=list)


class AIServicesSettingsApplyResponse(AdvancedBaseModel):
    saved: bool
    reloaded: bool
    config_version: int | None = None
    service_kinds: list[AIServiceKind] = Field(default_factory=list)
    reload_results: list[AIServiceReloadStateInfo] = Field(default_factory=list)
    workers: list[AIServiceWorkerInfo] = Field(default_factory=list)
    message: str


class AIServiceProbeResult(AdvancedBaseModel):
    key: str
    healthy: bool
    error: str | None = None


class AIServiceProbeResponse(AdvancedBaseModel):
    service: str
    results: list[AIServiceProbeResult] = Field(default_factory=list)


class AIServicesSettingsApplyRequest(AdvancedBaseModel):
    config: AIServicesConfig
    wait_for_reload: bool = True


class AIServiceRuntimeClientUpdateRequest(AdvancedBaseModel):
    max_concurrent: int | None = None
    priority: float | None = None
    strategy_lvl: int | None = None


def _probe_error_from_result(client: ServiceClientBase, result: object | None, exc: Exception | None = None) -> str | None:
    if exc is not None:
        return str(exc)
    if isinstance(result, dict):
        for key in ('error', 'message', 'detail'):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(result, (tuple, list)) and len(result) >= 2 and not bool(result[0]):
        detail = result[1]
        if detail:
            return str(detail)
    last_error = getattr(client, '_state_last_error', None) or getattr(client, 'last_error', None)
    if isinstance(last_error, str) and last_error.strip():
        return last_error.strip()
    if result is False:
        return 'Health probe returned unhealthy status.'
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _is_local_request(request: Request) -> bool:
    host = (request.client.host if request.client else '') if request is not None else ''
    host = (host or '').strip().lower()
    return not host or host in _LOCAL_HOSTS


def _ensure_local_request(request: Request) -> None:
    if not _is_local_request(request):
        raise HTTPException(403, 'AI 服务配置写入仅允许本机访问。')


def _real_client(client: ServiceClientBase | ServiceClient[ServiceClientBase]) -> ServiceClientBase:
    return client.client if isinstance(client, ServiceClient) else client


def _client_config_snapshot(
    client: ServiceClientBase | ServiceClient[ServiceClientBase],
    cfg: AIServicesConfig | None,
) -> tuple[str | None, dict[str, object]]:
    client = _real_client(client)
    if cfg is None:
        return None, {}
    scoped_key = getattr(client, '_key', None)
    if not isinstance(scoped_key, str) or ':' not in scoped_key:
        return None, {}
    service_kind, config_key = scoped_key.split(':', 1)
    if service_kind not in get_predefined_service_kinds():
        return None, {}
    bucket = getattr(cfg, service_kind, None)
    client_map = getattr(bucket, 'clients', None) if bucket is not None else None
    if not isinstance(client_map, dict):
        return config_key, {}
    client_cfg = client_map.get(config_key)
    if client_cfg is None:
        return config_key, {}
    model_dump = getattr(client_cfg, 'model_dump', None)
    if callable(model_dump):
        payload = model_dump(mode='json')
        if isinstance(payload, dict):
            return config_key, cast(dict[str, object], payload)
    return config_key, {}


def _build_client_status(client: ServiceClientBase | ServiceClient[ServiceClientBase], cfg: AIServicesConfig | None = None) -> ClientStatusInfo:
    info = build_ai_service_client_info(client)
    config_key, init_snapshot = _client_config_snapshot(client, cfg)
    return ClientStatusInfo(
        type=info.type,
        key=info.key,
        config_key=config_key,
        score=info.score,
        fail_count=info.fail_count,
        success_count=info.success_count,
        cooldown_until=info.cooldown_until,
        last_error=info.last_error,
        speed_ewma=info.speed_ewma,
        last_success_at=info.last_success_at,
        priority=info.priority,
        strategy_lvl=info.strategy_lvl,
        max_concurrent=info.max_concurrent,
        inflight=info.inflight,
        init_snapshot=init_snapshot,
        internal=config_key is None,
    )


def _collect_all_services(cfg: AIServicesConfig | None = None) -> list[ServiceInstanceInfo]:
    from core.ai.base import ServiceBase
    result: list[ServiceInstanceInfo] = []
    for (cls, key), instance in ServiceBase.ServiceInstances.items():
        clients_info: list[ClientStatusInfo] = []
        for client in getattr(instance, '_clients', []):
            clients_info.append(_build_client_status(client, cfg))
        result.append(ServiceInstanceInfo(
            service_kind=cast(AIServiceKind, cls.ServiceKind()),
            service_type=cls.__name__,
            key=key,
            fail_cooldown=float(getattr(instance, '_fail_cooldown', 10.0)),
            recovery_interval=getattr(instance, '_recovery_interval', None),
            client_count=len(clients_info),
            clients=clients_info,
        ))
    return result


def _find_runtime_client(client_key: str) -> ServiceClientBase | None:
    from core.ai.base import ServiceBase
    target = str(client_key or '').strip()
    if not target:
        return None
    for instance in ServiceBase.ServiceInstances.values():
        for client in getattr(instance, 'clients', []) or []:
            if build_ai_service_client_info(client).key == target:
                return client
    return None


def _find_runtime_service_client(
    service_type: str,
    service_key: str,
    client_key: str,
) -> tuple[object, ServiceClient[ServiceClientBase]] | None:
    from core.ai.base import ServiceBase
    service_type = str(service_type or '').strip()
    service_key = str(service_key or '').strip()
    target_client_key = str(client_key or '').strip()
    if not service_type or not service_key or not target_client_key:
        return None
    for (cls, key), instance in ServiceBase.ServiceInstances.items():
        if cls.__name__ != service_type or key != service_key:
            continue
        for binding in getattr(instance, '_clients', []) or []:
            info = build_ai_service_client_info(binding)
            if info.key == target_client_key:
                return instance, binding
    return None


def _set_runtime_client_max_concurrent(client: ServiceClientBase, value: int | None) -> None:
    if value is None:
        client.max_concurrent = None
        return
    next_value = max(1, int(value))
    pool = getattr(client, 'max_concurrent', None)
    if isinstance(pool, ConcurrentPool):
        pool.max_concurrent = next_value
        return
    client.max_concurrent = ConcurrentPool(getattr(client, 'key', None), next_value)


async def apply_ai_service_client_value_update(
    *,
    service_type: str,
    service_key: str,
    client_key: str,
    update_max_concurrent: bool = False,
    max_concurrent: int | None = None,
    update_priority: bool = False,
    priority: float | None = None,
    update_strategy_lvl: bool = False,
    strategy_lvl: int | None = None,
) -> ClientStatusInfo:
    found = _find_runtime_service_client(service_type, service_key, client_key)
    if found is None:
        raise KeyError(f'AI service client {service_type}:{service_key}:{client_key} not found.')
    instance, binding = found
    if update_max_concurrent:
        _set_runtime_client_max_concurrent(binding.client, max_concurrent)
    if update_priority:
        await instance.set_client_priority(client_key, priority)  # type: ignore[attr-defined]
    if update_strategy_lvl:
        await instance.set_client_strategy_lvl(client_key, strategy_lvl)  # type: ignore[attr-defined]
    sync_info = sync_ai_services_config_from_shared()
    _get_shared().invalidate_cache('ai-services:')
    return _build_client_status(binding, sync_info['config'])


def _get_shared() -> AppSharedData:
    return AppSharedData.Get()


def _serialize_ai_services_config(cfg: AIServicesConfig | None) -> str | None:
    if cfg is None:
        return None
    return cfg.to_serialized_env()


def _default_ai_services_config_path() -> Path:
    return PROJECT_DIR / 'config' / 'ai_services.yaml'


def _write_ai_services_config_file(cfg: AIServicesConfig) -> Path:
    import yaml  # type: ignore[import-untyped]
    path = _default_ai_services_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode='json')
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding='utf-8')
    return path


def _current_process_ai_config() -> AIServicesConfig | None:
    return AIServicesConfig.Global()


def _config_source(shared_snapshot: AIServiceConfigSnapshot, cfg: AIServicesConfig | None) -> AIServiceConfigSource:
    if shared_snapshot.get('serialized_config'):
        return 'shared-runtime'
    if cfg is not None and os.environ.get('__AI_SERVICES_CONFIG__'):
        return 'process-env'
    return 'defaults'


def sync_ai_services_config_from_shared() -> AIServiceSyncInfo:
    shared_snapshot = _get_shared().get_ai_services_config()
    serialized = shared_snapshot.get('serialized_config')
    if serialized:
        try:
            os.environ['__AI_SERVICES_CONFIG__'] = str(serialized)
            cfg = AIServicesConfig.model_validate(json.loads(str(serialized)))
            AIServicesConfig.SetGlobal(cfg)
            return {
                'config': cfg,
                'version': int(shared_snapshot.get('version') or 0),
                'source': 'shared-runtime',
            }
        except Exception as exc:
            logger.warning('Failed to sync AI services config from shared state: %s', exc)
    cfg = _current_process_ai_config()
    return {
        'config': cfg,
        'version': int(shared_snapshot.get('version') or 0),
        'source': _config_source(shared_snapshot, cfg),
    }


def _empty_ai_config_payload() -> AIServicesConfig:
    return AIServicesConfig()


def _build_settings_payload() -> AIServicesSettingsResponse:
    sync_info = sync_ai_services_config_from_shared()
    cfg = sync_info['config']
    shared = _get_shared()
    try:
        preload_default_services(background=True, probe_predefined_clients=False)
    except Exception as exc:
        logger.debug('AI service preload skipped while building settings payload: %s', exc)
    return AIServicesSettingsResponse(
        config_loaded=cfg is not None,
        config_source=sync_info['source'],
        config_version=int(sync_info['version']),
        config=cfg if cfg is not None else _empty_ai_config_payload(),
        client_types=ServiceClientBase.RegisteredClientTypes(),
        service_kinds=list(get_predefined_service_kinds()),
        workers=[AIServiceWorkerInfo.model_validate(row) for row in shared.get_workers_snapshot()],
        reload_state=[AIServiceReloadStateInfo.model_validate(row) for row in shared.get_ai_services_reload_state()],
        services=_collect_all_services(cfg),
    )


def _infer_affected_service_kinds(
    previous_cfg: AIServicesConfig | None,
    next_cfg: AIServicesConfig,
) -> list[AIServiceKind]:
    predefined_kinds = list(get_predefined_service_kinds())
    if previous_cfg is None:
        return predefined_kinds
    prev_dump = previous_cfg.model_dump(mode='json')
    next_dump = next_cfg.model_dump(mode='json')

    affected: list[AIServiceKind] = []
    for service_kind in predefined_kinds:
        if prev_dump.get(service_kind) != next_dump.get(service_kind):
            affected.append(service_kind)
    return affected


def apply_ai_services_runtime_update(
    *,
    serialized_config: str | None,
    service_kinds: list[AIServiceKind] | tuple[AIServiceKind, ...],
    version: int,
    reason: str | None = None,
) -> AIServiceRuntimeUpdateResult:
    affected_kinds = list(service_kinds or get_predefined_service_kinds())
    shared = _get_shared()
    pid = os.getpid()
    shared.update_ai_services_reload_state(
        pid=pid,
        version=version,
        state='reloading',
        service_kinds=affected_kinds,
        error=None,
    )
    set_service_runtime_reloading(
        affected_kinds,
        reloading=True,
        reason=reason,
        version=version,
        block_new_requests=False,
    )

    try:
        if serialized_config:
            os.environ['__AI_SERVICES_CONFIG__'] = serialized_config
            cfg = AIServicesConfig.model_validate(json.loads(serialized_config))
        else:
            os.environ.pop('__AI_SERVICES_CONFIG__', None)
            cfg = None

        AIServicesConfig.SetGlobal(cfg)

        from .api import reset_ai_service_route_caches

        reset_ai_service_route_caches(affected_kinds)
        clear_runtime_services(service_kinds=affected_kinds)
        preload_default_services(
            background=False,
            probe_predefined_clients=False,
            service_kinds=affected_kinds,
        )
        shared.invalidate_cache('ai-services:')
        shared.update_ai_services_reload_state(
            pid=pid,
            version=version,
            state='ready',
            service_kinds=affected_kinds,
            error=None,
        )
        return {
            'ok': True,
            'pid': pid,
            'version': version,
            'service_kinds': affected_kinds,
        }
    except Exception as exc:
        shared.update_ai_services_reload_state(
            pid=pid,
            version=version,
            state='error',
            service_kinds=affected_kinds,
            error=str(exc),
        )
        raise
    finally:
        set_service_runtime_reloading(
            affected_kinds,
            reloading=False,
            reason=reason,
            version=version,
            block_new_requests=False,
        )


async def _reload_workers(
    *,
    serialized_config: str | None,
    service_kinds: list[AIServiceKind],
    version: int,
    reason: str,
) -> list[AIServiceRuntimeUpdateResult]:
    shared = _get_shared()
    worker_ids = [row['pid'] for row in shared.get_workers_snapshot() if row['pid']]
    if not worker_ids:
        worker_ids = [os.getpid()]

    async def _reload_one(pid: int) -> AIServiceRuntimeUpdateResult:
        if pid == os.getpid():
            try:
                return apply_ai_services_runtime_update(
                    serialized_config=serialized_config,
                    service_kinds=service_kinds,
                    version=version,
                    reason=reason,
                )
            except Exception as exc:
                return {
                    'ok': False,
                    'pid': pid,
                    'version': version,
                    'service_kinds': list(service_kinds),
                    'error': str(exc),
                }
        msg = WorkerAIServiceReloadMessage(
            sender=os.getpid(),
            serialized_config=serialized_config,
            version=version,
            service_kinds=service_kinds,
            reason=reason,
        )
        try:
            result = await send_message_to_worker(pid, msg)
            row = dict(result) if isinstance(result, dict) else {'ok': True, 'pid': pid, 'version': version, 'service_kinds': list(service_kinds)}
            row.setdefault('pid', pid)
            row.setdefault('ok', True)
            return cast(AIServiceRuntimeUpdateResult, row)
        except Exception as exc:
            return {
                'ok': False,
                'pid': pid,
                'version': version,
                'service_kinds': list(service_kinds),
                'error': str(exc),
            }

    return await asyncio.gather(*(_reload_one(pid) for pid in worker_ids))


# ══════════════════════════════════════════════════════════════════════════════
# Route registration
# ══════════════════════════════════════════════════════════════════════════════

@on_before_app_created
def register_ai_services_panel_routes(app: FastAPI):
    admin_path = internal_admin_path

    # ── HTML pages ────────────────────────────────────────────────────────

    @app.get(admin_path("panel/ai-services/overview"), response_class=HTMLResponse)
    async def panel_ai_services_overview_html():
        path = get_resources("admin-panel", "panel", "ai_services_overview.html") or Path("ai_services_overview.html")
        return html_response_from_path(path, not_found_message="ai_services_overview.html not found")

    @app.get(admin_path("panel/ai-services/settings"), response_class=HTMLResponse)
    async def panel_ai_services_settings_html():
        path = get_resources("admin-panel", "panel", "ai_services_settings.html") or Path("ai_services_settings.html")
        return html_response_from_path(path, not_found_message="ai_services_settings.html not found")

    # ── API endpoints ─────────────────────────────────────────────────────

    @app.get(admin_path("api/ai-services/overview"), response_model=AIServicesOverviewResponse, include_in_schema=False)
    @app.get(admin_path("ai-services/overview"), response_model=AIServicesOverviewResponse)
    async def api_ai_services_overview() -> AIServicesOverviewResponse:
        """Return registered AI service instances and their client health status."""
        shared = _get_shared()
        cache_key = "ai-services:overview"
        cached = shared.get_cache(cache_key)
        if cached is not None:
            return AIServicesOverviewResponse.model_validate(cached)
        sync_info = sync_ai_services_config_from_shared()
        cfg = sync_info['config']
        payload = AIServicesOverviewResponse(
            services=_collect_all_services(cfg),
            config_loaded=cfg is not None,
            config_source=str(sync_info['source']),
            config_version=int(sync_info['version']),
            reload_state=[AIServiceReloadStateInfo.model_validate(row) for row in shared.get_ai_services_reload_state()],
            timestamp=time.time(),
        )
        shared.set_cache(cache_key, payload.model_dump(mode="python"), ttl_seconds=5)
        return payload

    @app.get(admin_path('api/ai-services/settings'), response_model=AIServicesSettingsResponse, include_in_schema=False)
    @app.get(admin_path('ai-services/settings'), response_model=AIServicesSettingsResponse)
    async def api_ai_services_settings() -> AIServicesSettingsResponse:
        return _build_settings_payload()

    @app.post(admin_path('api/ai-services/settings/apply'), response_model=AIServicesSettingsApplyResponse, include_in_schema=False)
    @app.post(admin_path('ai-services/settings/apply'), response_model=AIServicesSettingsApplyResponse)
    async def api_ai_services_settings_apply(
        payload: AIServicesSettingsApplyRequest,
        request: Request,
    ) -> AIServicesSettingsApplyResponse:
        _ensure_local_request(request)

        current_cfg = sync_ai_services_config_from_shared()['config']
        next_cfg = payload.config
        affected_kinds = _infer_affected_service_kinds(current_cfg, next_cfg)
        if not affected_kinds:
            _get_shared().invalidate_cache('ai-services:')
            return AIServicesSettingsApplyResponse(
                saved=True,
                reloaded=False,
                service_kinds=[],
                message='配置未发生变更。',
                workers=[AIServiceWorkerInfo.model_validate(row) for row in _get_shared().get_workers_snapshot()],
                reload_results=[],
            )

        new_serialized = next_cfg.to_serialized_env()
        previous_serialized = _serialize_ai_services_config(current_cfg)
        shared = _get_shared()
        shared.clear_ai_services_reload_state()
        version = int(time.time() * 1000)
        reload_results = await _reload_workers(
            serialized_config=new_serialized,
            service_kinds=affected_kinds,
            version=version,
            reason='panel-apply',
        )

        failures = [row for row in reload_results if not row.get('ok')]
        if failures:
            rollback_version = version + 1
            shared.clear_ai_services_reload_state()
            rollback_results = await _reload_workers(
                serialized_config=previous_serialized,
                service_kinds=affected_kinds,
                version=rollback_version,
                reason='panel-rollback',
            )
            shared.set_ai_services_config(previous_serialized, version=rollback_version)
            raise HTTPException(
                500,
                {
                    'message': 'AI 服务配置下发失败，已尝试回滚。',
                    'service_kinds': affected_kinds,
                    'reload_results': reload_results,
                    'rollback_results': rollback_results,
                },
            )

        try:
            written_path = _write_ai_services_config_file(next_cfg)
        except Exception as exc:
            rollback_version = version + 1
            shared.clear_ai_services_reload_state()
            rollback_results = await _reload_workers(
                serialized_config=previous_serialized,
                service_kinds=affected_kinds,
                version=rollback_version,
                reason='panel-save-rollback',
            )
            shared.set_ai_services_config(previous_serialized, version=rollback_version)
            raise HTTPException(
                500,
                {
                    'message': f'AI 服务配置已下发但写入 {_default_ai_services_config_path()} 失败，已尝试回滚。',
                    'error': str(exc),
                    'service_kinds': affected_kinds,
                    'reload_results': reload_results,
                    'rollback_results': rollback_results,
                },
            ) from exc

        shared.set_ai_services_config(new_serialized, version=version)
        shared.invalidate_cache('ai-services:')
        return AIServicesSettingsApplyResponse(
            saved=True,
            reloaded=bool(payload.wait_for_reload),
            config_version=version,
            service_kinds=affected_kinds,
            reload_results=[AIServiceReloadStateInfo.model_validate(row) for row in reload_results],
            workers=[AIServiceWorkerInfo.model_validate(row) for row in shared.get_workers_snapshot()],
            message=f'AI 服务配置已写入 {written_path}，并同步到全部 worker。',
        )

    @app.post(admin_path('api/ai-services/runtime-service-client/{service_type}/{service_key}/{client_key:path}'), response_model=ClientStatusInfo, include_in_schema=False)
    @app.post(admin_path('ai-services/runtime-service-client/{service_type}/{service_key}/{client_key:path}'), response_model=ClientStatusInfo)
    async def api_ai_services_runtime_service_client_update(
        service_type: str,
        service_key: str,
        client_key: str,
        payload: AIServiceRuntimeClientUpdateRequest,
        request: Request,
    ) -> ClientStatusInfo:
        _ensure_local_request(request)
        fields_set = getattr(payload, 'model_fields_set', set())
        try:
            local_status = await apply_ai_service_client_value_update(
                service_type=service_type,
                service_key=service_key,
                client_key=client_key,
                update_max_concurrent='max_concurrent' in fields_set,
                max_concurrent=payload.max_concurrent,
                update_priority='priority' in fields_set,
                priority=payload.priority,
                update_strategy_lvl='strategy_lvl' in fields_set,
                strategy_lvl=payload.strategy_lvl,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

        shared = _get_shared()
        worker_ids = [row['pid'] for row in shared.get_workers_snapshot() if row['pid'] and row['pid'] != os.getpid()]
        if worker_ids:
            msg_kwargs = dict(
                sender=os.getpid(),
                service_type=service_type,
                service_key=service_key,
                client_key=client_key,
                update_max_concurrent='max_concurrent' in fields_set,
                max_concurrent=payload.max_concurrent,
                update_priority='priority' in fields_set,
                priority=payload.priority,
                update_strategy_lvl='strategy_lvl' in fields_set,
                strategy_lvl=payload.strategy_lvl,
            )
            await asyncio.gather(*(
                send_message_to_worker(pid, WorkerAIServiceClientValueMessage(**msg_kwargs))
                for pid in worker_ids
            ), return_exceptions=True)
        shared.invalidate_cache('ai-services:')
        return local_status

    @app.post(admin_path("api/ai-services/probe/{service_type}/{service_key}"), response_model=AIServiceProbeResponse, include_in_schema=False)
    @app.post(admin_path("ai-services/probe/{service_type}/{service_key}"), response_model=AIServiceProbeResponse)
    async def api_ai_services_probe(service_type: str, service_key: str) -> AIServiceProbeResponse:
        """Trigger a health probe on all clients of the specified service instance."""
        from core.ai.base import ServiceBase
        instance = None
        for (cls, key), svc in ServiceBase.ServiceInstances.items():
            if cls.__name__ == service_type and key == service_key:
                instance = svc
                break
        if instance is None:
            raise HTTPException(404, f"Service {service_type}:{service_key} not found")

        results: list[AIServiceProbeResult] = []
        for client in getattr(instance, 'clients', []):
            probe = getattr(client, 'probe_min_health', None)
            ok = False
            error: str | None = None
            raw_result: object | None = None
            if callable(probe):
                try:
                    raw_result = probe()
                    if inspect.isawaitable(raw_result):
                        raw_result = await raw_result
                    ok = bool(raw_result)
                except Exception as exc:
                    error = _probe_error_from_result(client, raw_result, exc)
                else:
                    if not ok:
                        error = _probe_error_from_result(client, raw_result)
            else:
                error = 'Client does not implement probe_min_health.'
            results.append(AIServiceProbeResult(
                key=getattr(client, 'key', ''),
                healthy=ok,
                error=error,
            ))
        return AIServiceProbeResponse(
            service=f"{service_type}:{service_key}",
            results=results,
        )
