# -*- coding: utf-8 -*-
"""AI services admin panel routes — overview, settings, runtime reload."""


import os
import time
import json
import io
import asyncio
import inspect
import logging
from collections.abc import Mapping as MappingABC, MutableMapping as MutableMappingABC
from pathlib import Path
from typing import Literal, TypedDict, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ConfigDict, Field

from core.utils.type_utils import AdvancedBaseModel
from core.ai import (
    get_predefined_service_kinds,
    reconcile_runtime_services,
)
from core.ai.shared import AIServiceKind
from core.ai.base import (
    ServiceClient,
    ServiceClientBase,
    ProbeInterval,
    set_service_runtime_reloading,
)
from core.ai.config import AI_SERVICES_CONFIG_SOURCE_ENV, AIServicesConfig, _load_config_file
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

logger = logging.getLogger(__name__)
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}
_synced_runtime_config_version: int | None = None
type AIServiceConfigSource = Literal["shared-runtime", "process-env", "defaults"]


class AIServiceSyncInfo(TypedDict):
    config: AIServicesConfig | None
    version: int
    source: AIServiceConfigSource
    raw_config: dict[str, object] | None

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
    last_probe_at: float = 0.0
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
    recovery_interval: ProbeInterval | float | None = None
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
    raw_config: dict[str, object] | None = None
    client_types: list[str] = Field(default_factory=list)
    client_types_by_kind: dict[str, list[str]] = Field(default_factory=dict)
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
    config: dict[str, object]
    wait_for_reload: bool = True


class AIServiceRuntimeClientUpdateRequest(AdvancedBaseModel):
    model_config = ConfigDict(extra='allow')

    values: dict[str, object] = Field(default_factory=dict)

    def update_values(self) -> dict[str, object]:
        values = dict(self.values)
        extra = getattr(self, 'model_extra', None)
        if isinstance(extra, dict):
            values.update(cast(dict[str, object], extra))
        return values


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
        last_probe_at=info.last_probe_at,
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


async def apply_ai_service_client_value_update(
    *,
    service_type: str,
    service_key: str,
    client_key: str,
    values: MappingABC[str, object] | None = None,
) -> ClientStatusInfo:
    found = _find_runtime_service_client(service_type, service_key, client_key)
    if found is None:
        raise KeyError(f'AI service client {service_type}:{service_key}:{client_key} not found.')
    instance, binding = found
    runtime_values = dict(values or {})
    client_values = dict(runtime_values)
    if 'priority' in runtime_values:
        await instance.set_client_priority(client_key, runtime_values['priority'])  # type: ignore[attr-defined]
        client_values.pop('priority', None)
    if 'strategy_lvl' in runtime_values:
        await instance.set_client_strategy_lvl(client_key, runtime_values['strategy_lvl'])  # type: ignore[attr-defined]
        client_values.pop('strategy_lvl', None)
    if client_values and not binding.client.update(**client_values):
        raise ValueError(f'AI service client {service_type}:{service_key}:{client_key} cannot update values: {sorted(client_values)}')
    sync_info = sync_ai_services_config_from_shared()
    _get_shared().invalidate_cache('ai-services:')
    return _build_client_status(binding, sync_info['config'])


async def apply_ai_service_client_value_updates_from_shared(version: int = 0) -> int:
    applied_version = int(version or 0)
    for update in _get_shared().get_ai_service_client_value_updates_since(applied_version):
        update_version = int(update.get('version') or 0)
        try:
            await apply_ai_service_client_value_update(
                service_type=str(update.get('service_type') or ''),
                service_key=str(update.get('service_key') or ''),
                client_key=str(update.get('client_key') or ''),
                values=cast(dict[str, object], update.get('values') if isinstance(update.get('values'), dict) else {}),
            )
        except Exception:
            pass
        finally:
            applied_version = max(applied_version, update_version)
    return applied_version


def _get_shared() -> AppSharedData:
    return AppSharedData.Get()


def _serialize_ai_services_config(cfg: AIServicesConfig | None) -> str | None:
    if cfg is None:
        return None
    return cfg.to_serialized_env()


def _serialize_raw_ai_services_config(data: dict[str, object] | None) -> str | None:
    if data is None:
        return None
    return json.dumps(data, ensure_ascii=False)


def _raw_config_from_serialized(serialized: object) -> dict[str, object] | None:
    if not serialized:
        return None
    try:
        data = json.loads(str(serialized))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _raw_config_from_source(cfg: AIServicesConfig | None) -> dict[str, object] | None:
    if cfg is None:
        return None
    env_raw = _raw_config_from_serialized(os.environ.get('__AI_SERVICES_CONFIG__'))
    if env_raw is not None:
        return env_raw
    source_path = cfg.source_path()
    if source_path is None or not source_path.is_file():
        return None
    try:
        data = _load_config_file(source_path)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _default_ai_services_config_path() -> Path:
    return PROJECT_DIR / 'config' / 'ai_services.yaml'


def _ai_services_config_source_path(*configs: AIServicesConfig | None) -> Path | None:
    for cfg in configs:
        if cfg is None:
            continue
        source_path = cfg.source_path()
        if source_path is not None:
            return source_path
    env_source = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
    return Path(env_source) if env_source else None


def _ai_services_config_write_path(*configs: AIServicesConfig | None) -> Path:
    source_path = _ai_services_config_source_path(*configs)
    if source_path is None:
        return _default_ai_services_config_path()
    if source_path.suffix.lower() not in {'.yaml', '.yml', '.json', '.toml'}:
        return _default_ai_services_config_path()
    return source_path


def _drop_toml_none(value: object) -> object:
    if isinstance(value, MappingABC):
        return {str(k): _drop_toml_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_toml_none(item) for item in value if item is not None]
    return value


def _toml_key(key: str) -> str:
    if key and all(ch.isalnum() or ch in {'_', '-'} for ch in key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return '[' + ', '.join(_toml_value(item) for item in value) + ']'
    if isinstance(value, MappingABC):
        items = [f'{_toml_key(str(k))} = {_toml_value(v)}' for k, v in value.items()]
        return '{ ' + ', '.join(items) + ' }'
    raise ValueError(f'Unsupported TOML value type: {type(value).__name__}')


def _dump_toml_table(lines: list[str], path: tuple[str, ...], data: MappingABC[str, object]) -> None:
    scalar_items: list[tuple[str, object]] = []
    table_items: list[tuple[str, MappingABC[str, object]]] = []
    for key, value in data.items():
        if isinstance(value, MappingABC):
            table_items.append((str(key), value))
        else:
            scalar_items.append((str(key), value))

    if path:
        if lines and lines[-1] != '':
            lines.append('')
        lines.append(f'[{".".join(_toml_key(part) for part in path)}]')
    for key, value in scalar_items:
        lines.append(f'{_toml_key(key)} = {_toml_value(value)}')
    for key, value in table_items:
        _dump_toml_table(lines, (*path, key), value)


def _dump_toml(data: MappingABC[str, object]) -> str:
    lines: list[str] = []
    _dump_toml_table(lines, (), data)
    return '\n'.join(lines).rstrip() + '\n'


def _update_comment_preserving_mapping(target: MutableMappingABC[object, object], source: MappingABC[str, object]) -> None:
    for key in list(target.keys()):
        if str(key) not in source:
            del target[key]
    for key, value in source.items():
        existing = target.get(key)
        if isinstance(existing, MutableMappingABC) and isinstance(value, MappingABC):
            _update_comment_preserving_mapping(existing, value)
        else:
            target[key] = value


def _dump_toml_preserving_comments(path: Path, data: MappingABC[str, object]) -> str:
    toml_data = cast(MappingABC[str, object], _drop_toml_none(data))
    try:
        import tomlkit  # type: ignore[import-untyped]
    except Exception:
        return _dump_toml(toml_data)

    existing: object = None
    if path.is_file():
        existing = tomlkit.parse(path.read_text(encoding='utf-8'))
    if isinstance(existing, MutableMappingABC):
        _update_comment_preserving_mapping(existing, toml_data)
        return tomlkit.dumps(existing)
    return tomlkit.dumps(dict(toml_data))


def _extract_yaml_comments(path: Path) -> str:
    if not path.is_file():
        return ''
    comments: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('#') and line not in seen:
            comments.append(line)
            seen.add(line)
    return '\n'.join(comments).rstrip() + '\n' if comments else ''


def _dump_yaml_preserving_comments(path: Path, data: MappingABC[str, object]) -> str:
    try:
        from ruamel.yaml import YAML  # type: ignore[import-untyped]
    except Exception:
        import yaml  # type: ignore[import-untyped]
        dumped = yaml.safe_dump(dict(data), allow_unicode=True, sort_keys=False)
        return _extract_yaml_comments(path) + dumped

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    existing: object = None
    if path.is_file():
        existing = yaml.load(path.read_text(encoding='utf-8'))
    if isinstance(existing, MutableMappingABC):
        _update_comment_preserving_mapping(existing, data)
        dump_data: object = existing
    else:
        dump_data = dict(data)
    stream = io.StringIO()
    yaml.dump(dump_data, stream)
    return stream.getvalue()


def _serialize_ai_services_config_for_file(
    cfg: AIServicesConfig,
    path: Path,
    raw_data: dict[str, object] | None = None,
) -> str:
    suffix = path.suffix.lower()
    data = raw_data if raw_data is not None else cfg.model_dump(mode='json')
    if suffix == '.json':
        return json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if suffix == '.toml':
        return _dump_toml_preserving_comments(path, data)
    if suffix in {'.yaml', '.yml'}:
        return _dump_yaml_preserving_comments(path, data)
    raise ValueError(f'Unsupported AI services config write format: {path.suffix}')


def _write_ai_services_config_file(
    cfg: AIServicesConfig,
    source_cfg: AIServicesConfig | None = None,
    raw_data: dict[str, object] | None = None,
) -> Path:
    path = _ai_services_config_write_path(source_cfg, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _serialize_ai_services_config_for_file(cfg, path, raw_data=raw_data)
    path.write_text(text, encoding='utf-8')
    cfg.set_source_path(path)
    os.environ[AI_SERVICES_CONFIG_SOURCE_ENV] = str(path)
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
    global _synced_runtime_config_version
    shared_snapshot = _get_shared().get_ai_services_config()
    serialized = shared_snapshot.get('serialized_config')
    version = int(shared_snapshot.get('version') or 0)
    if serialized:
        try:
            raw_config = _raw_config_from_serialized(serialized)
            previous_cfg = AIServicesConfig.Global()
            os.environ['__AI_SERVICES_CONFIG__'] = str(serialized)
            cfg = AIServicesConfig.model_validate(raw_config or json.loads(str(serialized)))
            source_path = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
            if source_path:
                cfg.set_source_path(source_path)
            AIServicesConfig.SetGlobal(cfg)
            if _synced_runtime_config_version != version:
                from .api import reset_ai_service_route_caches

                reset_ai_service_route_caches(get_predefined_service_kinds())
                reconcile_runtime_services(previous_cfg, cfg)
                _synced_runtime_config_version = version
            return {
                'config': cfg,
                'version': version,
                'source': 'shared-runtime',
                'raw_config': raw_config,
            }
        except Exception as exc:
            logger.warning('Failed to sync AI services config from shared state: %s', exc)
    cfg = _current_process_ai_config()
    return {
        'config': cfg,
        'version': version,
        'source': _config_source(shared_snapshot, cfg),
        'raw_config': _raw_config_from_source(cfg),
    }


def _empty_ai_config_payload() -> AIServicesConfig:
    return AIServicesConfig()


def _build_settings_payload() -> AIServicesSettingsResponse:
    sync_info = sync_ai_services_config_from_shared()
    cfg = sync_info['config']
    shared = _get_shared()
    service_kinds = list(get_predefined_service_kinds())
    client_types_by_kind = {
        str(service_kind): ServiceClientBase.RegisteredClientTypes(service_kind=service_kind)
        for service_kind in service_kinds
    }
    client_types = sorted({
        client_type
        for type_list in client_types_by_kind.values()
        for client_type in type_list
    })
    return AIServicesSettingsResponse(
        config_loaded=cfg is not None,
        config_source=sync_info['source'],
        config_version=int(sync_info['version']),
        config=cfg if cfg is not None else _empty_ai_config_payload(),
        raw_config=sync_info.get('raw_config'),
        client_types=client_types,
        client_types_by_kind=client_types_by_kind,
        service_kinds=service_kinds,
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

    if prev_dump.get('kwargs') != next_dump.get('kwargs'):
        return predefined_kinds

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
    global _synced_runtime_config_version
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
        previous_cfg = AIServicesConfig.Global()
        if serialized_config:
            os.environ['__AI_SERVICES_CONFIG__'] = serialized_config
            cfg = AIServicesConfig.model_validate(json.loads(serialized_config))
            source_path = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
            if source_path:
                cfg.set_source_path(source_path)
        else:
            os.environ.pop('__AI_SERVICES_CONFIG__', None)
            cfg = None

        AIServicesConfig.SetGlobal(cfg)

        from .api import reset_ai_service_route_caches

        reset_ai_service_route_caches(affected_kinds)
        reconcile_runtime_services(previous_cfg, cfg, affected_kinds)
        _synced_runtime_config_version = version
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
        sync_info = sync_ai_services_config_from_shared()
        cfg = sync_info['config']
        return AIServicesOverviewResponse(
            services=_collect_all_services(cfg),
            config_loaded=cfg is not None,
            config_source=str(sync_info['source']),
            config_version=int(sync_info['version']),
            reload_state=[AIServiceReloadStateInfo.model_validate(row) for row in shared.get_ai_services_reload_state()],
            timestamp=time.time(),
        )

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

        current_sync_info = sync_ai_services_config_from_shared()
        current_cfg = current_sync_info['config']
        raw_next_config = payload.config
        next_cfg = AIServicesConfig.model_validate(raw_next_config)
        new_serialized = _serialize_raw_ai_services_config(raw_next_config)
        previous_serialized = _serialize_raw_ai_services_config(current_sync_info.get('raw_config')) or _serialize_ai_services_config(current_cfg)
        affected_kinds = _infer_affected_service_kinds(current_cfg, next_cfg)
        if not affected_kinds:
            shared = _get_shared()
            if new_serialized != previous_serialized:
                version = int(time.time() * 1000)
                written_path = _write_ai_services_config_file(next_cfg, source_cfg=current_cfg, raw_data=raw_next_config)
                shared.set_ai_services_config(new_serialized, version=version)
                shared.invalidate_cache('ai-services:')
                return AIServicesSettingsApplyResponse(
                    saved=True,
                    reloaded=False,
                    config_version=version,
                    service_kinds=[],
                    message=f'AI 服务配置已写入 {written_path}。运行时参数未变化，无需重载 worker。',
                    workers=[AIServiceWorkerInfo.model_validate(row) for row in shared.get_workers_snapshot()],
                    reload_results=[],
                )
            shared.invalidate_cache('ai-services:')
            return AIServicesSettingsApplyResponse(
                saved=True,
                reloaded=False,
                service_kinds=[],
                message='配置未发生变更。',
                workers=[AIServiceWorkerInfo.model_validate(row) for row in shared.get_workers_snapshot()],
                reload_results=[],
            )

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
            written_path = _write_ai_services_config_file(next_cfg, source_cfg=current_cfg, raw_data=raw_next_config)
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
                    'message': f'AI 服务配置已下发但写入 {_ai_services_config_write_path(current_cfg, next_cfg)} 失败，已尝试回滚。',
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
        values = payload.update_values()
        try:
            local_status = await apply_ai_service_client_value_update(
                service_type=service_type,
                service_key=service_key,
                client_key=client_key,
                values=values,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

        shared = _get_shared()
        shared.record_ai_service_client_value_update(
            service_type=service_type,
            service_key=service_key,
            client_key=client_key,
            values=values,
        )
        worker_ids = [row['pid'] for row in shared.get_workers_snapshot() if row['pid'] and row['pid'] != os.getpid()]
        if worker_ids:
            msg_kwargs = dict(
                sender=os.getpid(),
                service_type=service_type,
                service_key=service_key,
                client_key=client_key,
                values=values,
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
