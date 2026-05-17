import logging
import threading
import os
import json
from collections.abc import Sequence
from typing import cast

from core.utils.concurrent_utils import run_any_func

from .shared import *
from .config import *
from .base import ServiceBase, ServiceClientBase
from .completion import CodingAgentCompletionClient, CompletionClient, CompletionService, OpenAILikedCompletionClient, OpenRouterCompletionClient, ThinkThinkSynCompletionClient
from .embedding import EmbeddingClient, EmbeddingService, OpenAILikedEmbeddingClient, OpenRouterEmbeddingClient, ThinkThinkSynEmbeddingClient
from .s2t import CompletionAsS2TClient, OpenAILikedS2TClient, OpenRouterS2TClient, S2TClient, S2TService
from .t2s import OpenAILikedT2SClient, OpenRouterT2SClient, T2SClient, T2SService, ThinkThinkSynT2SClient
from .t2img import OpenAILikedT2ImgClient, OpenRouterT2ImgClient, T2ImgClient, T2ImgService

_logger = logging.getLogger(__name__)
_PREDEFINED_SERVICE_CLASSES: dict[str, type[ServiceBase]] = {
    'completion': CompletionService,
    'embedding': EmbeddingService,
    's2t': S2TService,
    't2s': T2SService,
    't2img': T2ImgService,
}
_main_process_probe_stop_event = threading.Event()
_main_process_probe_thread: threading.Thread | None = None
_main_process_probe_config_version: int | None = None
_main_process_client_value_version: int = 0


def _selected_service_classes(service_kinds: Sequence[str] | None = None) -> list[tuple[str, type[ServiceBase]]]:
    if service_kinds is None:
        return list(_PREDEFINED_SERVICE_CLASSES.items())
    result: list[tuple[str, type[ServiceBase]]] = []
    for service_kind in service_kinds:
        normalized = str(service_kind).strip().lower()
        if normalized.endswith('service'):
            normalized = normalized[:-7]
        service_cls = _PREDEFINED_SERVICE_CLASSES.get(normalized)
        if service_cls is None:
            _logger.warning('Unknown predefined AI service kind %r.', service_kind)
            continue
        result.append((normalized, service_cls))
    return result


def preload_default_services(
    background: bool = True,
    service_kinds: Sequence[str] | None = None,
) -> None:
    """Preload default AI service instances for the current process."""
    selected = _selected_service_classes(service_kinds)

    def _preload() -> None:
        for service_kind, service_cls in selected:
            try:
                service_cls.Default()
            except Exception as exc:
                _logger.debug('Default %s AI service preload skipped: %s', service_kind, exc)

    if background:
        threading.Thread(target=_preload, name='ai-default-service-preload', daemon=True).start()
        return
    _preload()


def configured_client_cache_keys(
    cfg: AIServicesConfig | None,
    service_kinds: Sequence[str] | None = None,
) -> set[str]:
    """Return explicit client cache keys defined by configured service buckets."""
    if cfg is None:
        return set()
    keys: set[str] = set()
    for service_kind, _ in _selected_service_classes(service_kinds):
        bucket = getattr(cfg, service_kind, None)
        if bucket is None:
            continue
        for client_key in getattr(bucket, 'clients', {}) or {}:
            keys.add(bucket.scoped_client_key(str(client_key)))
    return keys


def clear_runtime_services(
    service_kinds: Sequence[str] | None = None,
    *,
    client_cache_keys: set[str] | None = None,
) -> None:
    """Clear process-local AI service instances."""
    for _, service_cls in _selected_service_classes(service_kinds):
        service_cls.ClearInstances(close=True)
    if client_cache_keys:
        ServiceClientBase.ClearClientCache(keys=client_cache_keys, close=False)


def _effective_service_configs(bucket: AIPredefinedService | None) -> dict[str, AIServiceInitData]:
    if bucket is None:
        return {}
    configs = dict(getattr(bucket, 'service', {}) or {})
    if 'default' not in configs and getattr(bucket, 'clients', None):
        configs['default'] = AIServiceInitData(clients=list(bucket.clients))
    return configs


def _service_instance(service_cls: type[ServiceBase], key: str) -> ServiceBase | None:
    return ServiceBase.ServiceInstances.get((service_cls, key))


def _same_client_runtime_type(client: ServiceClientBase, cfg: AIServiceClientInitData, service_kind: str) -> bool:
    client_cls = ServiceClientBase.GetClientCls(cfg.type, service_kind=service_kind)
    return client_cls is not None and isinstance(client, client_cls)


def _reconcile_configured_clients(
    service_kind: str,
    previous_bucket: AIPredefinedService | None,
    next_bucket: AIPredefinedService,
) -> None:
    previous_clients = getattr(previous_bucket, 'clients', {}) if previous_bucket is not None else {}
    next_clients = getattr(next_bucket, 'clients', {}) or {}
    previous_keys = set(previous_clients)
    next_keys = set(next_clients)
    for client_key in sorted(previous_keys | next_keys):
        scoped_key = next_bucket.scoped_client_key(str(client_key))
        previous_client_cfg = previous_clients.get(client_key)
        next_client_cfg = next_clients.get(client_key)
        if next_client_cfg is None:
            ServiceClientBase.ClearClientCache(keys={scoped_key}, close=False)
            continue
        if previous_client_cfg is not None and previous_client_cfg.model_dump(mode='json') == next_client_cfg.model_dump(mode='json'):
            continue
        existing = ServiceClientBase.GetClient(scoped_key)
        if existing is None:
            continue
        if not _same_client_runtime_type(existing, next_client_cfg, service_kind):
            ServiceClientBase.ClearClientCache(keys={scoped_key}, close=False)
            continue
        if not existing.update(**next_client_cfg.build_client_init_kwargs(key=scoped_key)):
            ServiceClientBase.ClearClientCache(keys={scoped_key}, close=False)


def _reconcile_configured_services(
    service_cls: type[ServiceBase],
    previous_bucket: AIPredefinedService | None,
    next_bucket: AIPredefinedService,
) -> None:
    previous_services = _effective_service_configs(previous_bucket)
    next_services = _effective_service_configs(next_bucket)
    for service_key in sorted(set(previous_services) - set(next_services)):
        existing = _service_instance(service_cls, service_key)
        if existing is not None:
            existing.close()
    for service_key, service_cfg in sorted(next_services.items()):
        existing = _service_instance(service_cls, service_key)
        if existing is None:
            next_bucket._build_service_from_config(service_cfg, key=service_key)
            continue
        service_clients = next_bucket.build_service_clients(service_cfg, key=service_key)
        service_kwargs = next_bucket.build_service_init_kwargs(service_cfg, key=service_key)
        service_kwargs.pop('key', None)
        service_kwargs.pop('init_probe', None)
        if not existing.update(clients=service_clients, **service_kwargs):
            existing.close()
            next_bucket._build_service_from_config(service_cfg, key=service_key)


def reconcile_runtime_services(
    previous_cfg: AIServicesConfig | None,
    next_cfg: AIServicesConfig | None,
    service_kinds: Sequence[str] | None = None,
) -> None:
    """Apply AI service config changes with the smallest practical runtime mutation."""
    for service_kind, service_cls in _selected_service_classes(service_kinds):
        previous_bucket = getattr(previous_cfg, service_kind, None) if previous_cfg is not None else None
        next_bucket = getattr(next_cfg, service_kind, None) if next_cfg is not None else None
        if next_bucket is None:
            client_keys = configured_client_cache_keys(previous_cfg, [service_kind])
            service_cls.ClearInstances(close=True)
            if client_keys:
                ServiceClientBase.ClearClientCache(keys=client_keys, close=False)
            if next_cfg is None:
                preload_default_services(background=False, service_kinds=[service_kind])
            continue
        _reconcile_configured_clients(service_kind, previous_bucket, next_bucket)
        _reconcile_configured_services(service_cls, previous_bucket, next_bucket)


def preload_configured_services_for_probe(service_kinds: Sequence[str] | None = None) -> None:
    """Create configured service instances in the main process for health probes."""
    cfg = AIServicesConfig.Global()
    if cfg is None:
        preload_default_services(background=False, service_kinds=service_kinds)
        return
    selected = [kind for kind, _ in _selected_service_classes(service_kinds)]
    for service_kind in selected:
        bucket = getattr(cfg, service_kind, None)
        if bucket is None:
            continue
        try:
            bucket.get_default()
        except Exception as exc:
            _logger.debug('Default %s AI service probe preload skipped: %s', service_kind, exc)
        try:
            bucket.preload_service_instances()
        except Exception as exc:
            _logger.debug('%s AI service instance probe preload skipped: %s', service_kind, exc)


def start_main_process_probe_loop(
    *,
    service_kinds: Sequence[str] | None = None,
    poll_interval: float = 5.0,
) -> None:
    """Start the supervisor-process AI client health probe loop."""
    global _main_process_probe_thread
    if _main_process_probe_thread is not None and _main_process_probe_thread.is_alive():
        return
    _main_process_probe_stop_event.clear()
    selected_kinds = tuple(str(kind).strip().lower() for kind in service_kinds) if service_kinds is not None else None
    sleep_seconds = max(1.0, float(poll_interval))

    def _run() -> None:
        while not _main_process_probe_stop_event.is_set():
            try:
                sync_main_process_probe_runtime_from_shared(selected_kinds)
                preload_configured_services_for_probe(selected_kinds)
                stats = run_any_func(ServiceBase.ProbeRegisteredClientsOnce, service_kinds=selected_kinds)
                if isinstance(stats, dict) and int(stats.get('probed', 0)) > 0:
                    _logger.debug('AI main-process probe stats: %s', stats)
            except Exception:
                _logger.exception('AI main-process probe loop failed.')
            _main_process_probe_stop_event.wait(sleep_seconds)

    _main_process_probe_thread = threading.Thread(
        target=_run,
        name='ai-main-process-probe',
        daemon=True,
    )
    _main_process_probe_thread.start()


def stop_main_process_probe_loop() -> None:
    """Stop the supervisor-process AI client health probe loop."""
    global _main_process_probe_thread
    _main_process_probe_stop_event.set()
    thread = _main_process_probe_thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2.0)
    _main_process_probe_thread = None


def _set_global_ai_services_config_from_serialized(serialized_config: str | None) -> AIServicesConfig | None:
    if serialized_config:
        os.environ['__AI_SERVICES_CONFIG__'] = serialized_config
        return AIServicesConfig.model_validate(json.loads(serialized_config))
    os.environ.pop('__AI_SERVICES_CONFIG__', None)
    return None


def sync_main_process_probe_runtime_from_shared(service_kinds: Sequence[str] | None = None) -> None:
    """Synchronize supervisor-process probe services from AppSharedData."""
    global _main_process_probe_config_version, _main_process_client_value_version
    try:
        from core.server.shared import AppSharedData
    except Exception:
        return

    selected_kinds = [kind for kind, _ in _selected_service_classes(service_kinds)]
    try:
        shared = AppSharedData.Get()
        snapshot = shared.get_ai_services_config()
        version = int(snapshot.get('version') or 0)
        serialized = snapshot.get('serialized_config')
        shared_config_initialized = version > 0 or bool(serialized)
        if shared_config_initialized and _main_process_probe_config_version != version:
            previous_cfg = AIServicesConfig.Global()
            next_cfg = _set_global_ai_services_config_from_serialized(str(serialized) if serialized else None)
            AIServicesConfig.SetGlobal(next_cfg)
            reconcile_runtime_services(previous_cfg, next_cfg, selected_kinds)
            _main_process_probe_config_version = version
        elif _main_process_probe_config_version is None:
            _main_process_probe_config_version = version

        updates = shared.get_ai_service_client_value_updates_since(_main_process_client_value_version)
        if not updates:
            return
        from core.server.routes.ai_services.panel import apply_ai_service_client_value_update
        for update in updates:
            update_version = int(update.get('version') or 0)
            try:
                run_any_func(
                    apply_ai_service_client_value_update,
                    service_type=str(update.get('service_type') or ''),
                    service_key=str(update.get('service_key') or ''),
                    client_key=str(update.get('client_key') or ''),
                    values=cast(dict[str, object], update.get('values') if isinstance(update.get('values'), dict) else {}),
                )
            except Exception:
                _logger.debug('AI main-process client value sync skipped: %s', update, exc_info=True)
            finally:
                _main_process_client_value_version = max(_main_process_client_value_version, update_version)
    except Exception:
        _logger.debug('AI main-process shared runtime sync skipped.', exc_info=True)


def get_predefined_service_kinds() -> list[str]:
    """Return service kinds managed by the built-in AI runtime."""
    return list(_PREDEFINED_SERVICE_CLASSES)
