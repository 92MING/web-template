# -*- coding: utf-8 -*-
"""AI services configuration models.

Provides typed config classes that can be loaded from YAML / JSON / TOML / env
and used to instantiate AI service clients and services declaratively.
"""
import os
import json
import logging
from pathlib import Path

from typing import TYPE_CHECKING, Any, Callable, ClassVar, Generic, Mapping, TypeVar, Self, cast
from pydantic import Field, PrivateAttr, model_validator, ConfigDict

from core.utils.type_utils import AdvancedBaseModel
from core.constants import PROJECT_DIR
from core.storage.object import OBS_Object
from .base import ProbeInterval
from .shared import AIServiceKind

if TYPE_CHECKING:
    from .base import ServiceClient, ServiceClientBase, ServiceBase
    from .completion import CompletionService, CompletionClient
    from .embedding import EmbeddingService, EmbeddingClient
    from .s2t import S2TService, S2TClient
    from .t2s import T2SService, T2SClient
    from .t2img import T2ImgService, T2ImgClient

_logger = logging.getLogger(__name__)
_AI_SERVICES_FILE_SUFFIXES: tuple[str, ...] = ('.yaml', '.yml', '.json', '.toml')
_SERVER_RUNTIME_ENV_KEYS: tuple[str, ...] = (
    'IN_UVICORN_PROCESS',
    '__SERVER_PROCESS_PID__',
    '__SERVER_SUPERVISOR_PID__',
    '__SERVER_INSTANCE_ID__',
)
AI_SERVICES_CONFIG_SOURCE_ENV = '__AI_SERVICES_CONFIG_SOURCE_PATH__'

_CT = TypeVar('_CT', bound='ServiceClientBase')
_ST = TypeVar('_ST', bound='ServiceBase')

ConfigMapping = dict[str, object]
ConfigLoader = Callable[[Path], ConfigMapping]

_SERVICE_KIND_FIELDS: tuple[str, ...] = ('completion', 'embedding', 's2t', 't2s', 't2img')
_CLIENT_TYPE_ALIASES: dict[str, str] = {
    'openai-liked': 'openai',
    'openai_liked': 'openai',
}
_NUMERIC_SUFFIX_FIELDS: frozenset[str] = frozenset({
    'max_tokens',
    'max_images',
    'max_audios',
    'max_videos',
    'max_concurrent',
    'strategy_lvl',
})
_STRATEGY_LEVEL_ALIASES: dict[str, int] = {
    'loadbalance': 0,
    'onratelimit': 1,
    'ratelimit': 1,
    'onerror': 2,
    'error': 2,
}


def _ensure_config_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise ValueError(f'{path} must be a mapping.')


def _parse_numeric_suffix(value: str) -> int | str:
    text = value.strip()
    if len(text) < 2:
        return value
    suffix = text[-1].lower()
    if suffix not in {'k', 'm'}:
        return value
    number = text[:-1].strip()
    if not number.isdigit():
        return value
    multiplier = 1000 if suffix == 'k' else 1000000
    return int(number) * multiplier


def _parse_strategy_level(value: str) -> int | str:
    text = value.strip()
    if text.isdigit():
        return int(text)
    normalized = text.lower().replace('_', '').replace('-', '').replace(' ', '')
    return _STRATEGY_LEVEL_ALIASES.get(normalized, value)


def _normalize_config_value(key: str, value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k): _normalize_config_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_config_value(key, item) for item in value]
    if key == 'strategy_lvl' and isinstance(value, str):
        return _parse_strategy_level(value)
    if key in _NUMERIC_SUFFIX_FIELDS and isinstance(value, str):
        return _parse_numeric_suffix(value)
    if key == 'type' and isinstance(value, str):
        normalized = value.strip()
        return _CLIENT_TYPE_ALIASES.get(normalized.lower(), normalized)
    return value


def _normalize_config_mapping(data: Mapping[str, object]) -> dict[str, object]:
    return {str(k): _normalize_config_value(str(k), v) for k, v in data.items()}


def _resolve_kwargs_reference_value(
    value: object,
    *,
    presets: Mapping[str, Mapping[str, object]],
    path: str,
) -> dict[str, object]:
    if isinstance(value, str):
        if value not in presets:
            raise ValueError(f'Unknown kwargs reference {value!r} at {path}.')
        return dict(presets[value])
    if isinstance(value, list):
        merged: dict[str, object] = {}
        for idx, item in enumerate(value):
            item_kwargs = _resolve_kwargs_reference_value(
                item,
                presets=presets,
                path=f'{path}[{idx}]',
            )
            merged.update(item_kwargs)
        return merged
    if isinstance(value, Mapping):
        return _normalize_config_mapping(value)
    raise ValueError(f'{path} must be a kwargs reference string, a list of references, or a mapping.')


def _normalize_kwargs_presets(value: object) -> dict[str, dict[str, object]]:
    if value is None:
        return {}
    raw_presets = {str(k): v for k, v in _ensure_config_mapping(value, path='kwargs').items()}
    resolved: dict[str, dict[str, object]] = {}

    def resolve(name: str, stack: tuple[str, ...] = ()) -> dict[str, object]:
        if name in resolved:
            return dict(resolved[name])
        if name in stack:
            cycle = ' -> '.join((*stack, name))
            raise ValueError(f'Circular kwargs reference: {cycle}.')
        raw = _ensure_config_mapping(raw_presets[name], path=f'kwargs.{name}')
        local = dict(raw)
        refs = local.pop('kwargs', None)
        merged: dict[str, object] = {}
        if refs is not None:
            merged.update(_resolve_preset_reference_value(refs, stack=(*stack, name), path=f'kwargs.{name}.kwargs'))
        merged.update(_normalize_config_mapping(local))
        resolved[name] = merged
        return dict(merged)

    def _resolve_preset_reference_value(value: object, *, stack: tuple[str, ...], path: str) -> dict[str, object]:
        if isinstance(value, str):
            if value not in raw_presets:
                raise ValueError(f'Unknown kwargs reference {value!r} at {path}.')
            return resolve(value, stack)
        if isinstance(value, list):
            merged: dict[str, object] = {}
            for idx, item in enumerate(value):
                merged.update(_resolve_preset_reference_value(item, stack=stack, path=f'{path}[{idx}]'))
            return merged
        if isinstance(value, Mapping):
            mapping = dict(value)
            refs = mapping.pop('kwargs', None)
            merged: dict[str, object] = {}
            if refs is not None:
                merged.update(_resolve_preset_reference_value(refs, stack=stack, path=f'{path}.kwargs'))
            merged.update(_normalize_config_mapping(mapping))
            return merged
        raise ValueError(f'{path} must be a kwargs reference string, a list of references, or a mapping.')

    for preset_name in raw_presets:
        resolve(preset_name)
    return resolved


def _expand_client_config_kwargs_refs(
    value: object,
    *,
    presets: Mapping[str, Mapping[str, object]],
    path: str,
) -> object:
    if not isinstance(value, Mapping):
        return value
    data = dict(value)
    refs = data.get('kwargs')
    if isinstance(refs, (str, list)):
        merged = _resolve_kwargs_reference_value(refs, presets=presets, path=f'{path}.kwargs')
        for k, v in data.items():
            if k == 'kwargs':
                continue
            merged[str(k)] = _normalize_config_value(str(k), v)
        return merged
    if refs is not None and not isinstance(refs, Mapping):
        raise ValueError(f'{path}.kwargs must be a mapping, a kwargs reference string, or a list of references.')
    return _normalize_config_mapping(data)


def _normalize_service_clients(
    value: object,
    *,
    presets: Mapping[str, Mapping[str, object]],
    path: str,
) -> object:
    if isinstance(value, list):
        items: list[object] = []
        for idx, item in enumerate(value):
            if isinstance(item, Mapping):
                if 'client' in item and not ({'type', 'kwargs'} & set(item)):
                    normalized_binding = _normalize_config_mapping(item)
                    client_value = normalized_binding.get('client')
                    if isinstance(client_value, Mapping):
                        normalized_binding['client'] = _expand_client_config_kwargs_refs(
                            client_value,
                            presets=presets,
                            path=f'{path}[{idx}].client',
                        )
                    items.append(normalized_binding)
                else:
                    items.append(_expand_client_config_kwargs_refs(item, presets=presets, path=f'{path}[{idx}]'))
            else:
                items.append(item)
        return items
    return value


def _normalize_service_config_node(
    value: object,
    *,
    presets: Mapping[str, Mapping[str, object]],
    path: str,
) -> object:
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for k, v in value.items():
            key = str(k)
            if key == 'clients':
                normalized[key] = _normalize_service_clients(v, presets=presets, path=f'{path}.clients')
            else:
                normalized[key] = _normalize_service_config_node(v, presets=presets, path=f'{path}.{key}')
        return normalized
    if isinstance(value, list):
        return [
            _normalize_service_config_node(item, presets=presets, path=f'{path}[{idx}]')
            for idx, item in enumerate(value)
        ]
    return value


def _normalize_predefined_service_config(
    value: object,
    *,
    presets: Mapping[str, Mapping[str, object]],
    path: str,
) -> object:
    if not isinstance(value, Mapping):
        return value
    data = dict(value)
    if 'services' in data:
        if 'service' in data:
            raise ValueError(f'{path} cannot define both service and services.')
        data['service'] = data.pop('services')
    clients = data.get('clients')
    if isinstance(clients, Mapping):
        data['clients'] = {
            str(client_key): _expand_client_config_kwargs_refs(
                client_value,
                presets=presets,
                path=f'{path}.clients.{client_key}',
            )
            for client_key, client_value in clients.items()
        }
    service = data.get('service')
    if isinstance(service, Mapping):
        data['service'] = {
            str(service_key): _normalize_service_config_node(
                service_value,
                presets=presets,
                path=f'{path}.service.{service_key}',
            )
            for service_key, service_value in service.items()
        }
    return _normalize_config_mapping(data)


def _normalize_ai_services_config_data(data: object) -> object:
    if not isinstance(data, dict):
        return data
    if 'clients' in data:
        raise ValueError(
            'AIServicesConfig top-level `clients` 已移除；请改为 `completion.clients` / '
            '`embedding.clients` / `s2t.clients` / `t2s.clients`。'
        )
    normalized = dict(data)
    presets = _normalize_kwargs_presets(normalized.pop('kwargs', None))
    if presets:
        normalized['kwargs'] = presets
    wrapped_services = normalized.pop('services', None)
    if wrapped_services is not None:
        wrapped_mapping = _ensure_config_mapping(wrapped_services, path='services')
        for service_kind, service_config in wrapped_mapping.items():
            service_kind_key = str(service_kind)
            if service_kind_key in normalized and service_kind_key in _SERVICE_KIND_FIELDS:
                raise ValueError(f'AIServicesConfig cannot define both {service_kind_key} and services.{service_kind_key}.')
            normalized[service_kind_key] = service_config
    for service_kind in _SERVICE_KIND_FIELDS:
        if service_kind in normalized:
            normalized[service_kind] = _normalize_predefined_service_config(
                normalized[service_kind],
                presets=presets,
                path=service_kind,
            )
    return normalized

class AIServiceClientInitData(AdvancedBaseModel, Generic[_CT]):
    """Declarative configuration for a single AI service client.

    ``type`` maps to the registered client type (via ``__init_subclass__``).
    Common fields mirror :class:`ServiceClientInitParams`.  Extra unknown
    keys are collected into ``kwargs`` automatically.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    """Registered client type string within the current service kind, e.g. ``'thinkthinksyn'``, ``'openai'``."""
    adapter: str | OBS_Object | None = None
    """Custom adapter Python 脚本来源；可为字符串路径/URL，或 object storage 中的 OBS_Object。"""
    key: str | None = None
    """Client instance key.  Passed to the client ``__init__``."""
    max_concurrent: int | None = None
    """Max concurrent requests; ``None`` = unlimited."""
    priority: float = 0.0
    """Scheduling priority (lower = higher priority)."""
    strategy_lvl: int = 0
    """Failover strategy level (0=LOAD_BALANCE, 1=ON_RATELIMIT, 2=ON_ERROR)."""
    kwargs: dict[str, object] = Field(default_factory=dict)
    """Extra keyword arguments forwarded to the client ``__init__``."""

    _RESERVED_FIELDS: ClassVar[frozenset[str]] = frozenset({'type', 'adapter', 'key', 'max_concurrent', 'priority', 'strategy_lvl', 'kwargs'})

    @model_validator(mode='before')
    @classmethod
    def _collect_extra_into_kwargs(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        known = set(cls.model_fields) | cls._RESERVED_FIELDS
        extra: dict[str, object] = {}
        explicit_kwargs: dict[str, object] = {}
        if 'kwargs' in data and isinstance(data['kwargs'], dict):
            explicit_kwargs = dict(data['kwargs'])
        to_remove: list[str] = []
        for k, v in data.items():
            if k not in known:
                extra[k] = v
                to_remove.append(k)
        for k in to_remove:
            del data[k]
        merged = {**explicit_kwargs, **extra}
        if merged:
            data['kwargs'] = merged
        return data

    def get_client(self, key: str | None = None, *, service_kind: AIServiceKind | str | None = None) -> _CT | None:
        """Instantiate and return the client described by this config.

        Args:
            key: Override the config's ``key`` field for the created instance.
        """
        from .base import ServiceClientBase
        client_cls = ServiceClientBase.GetClientCls(self.type, service_kind=service_kind)
        if client_cls is None:
            _logger.warning('Unknown client type %r, cannot create client.', self.type)
            return None
        init_kw = self.build_client_init_kwargs(key=key)

        try:
            return cast(_CT, client_cls.CreateFromConfig(**init_kw))
        except Exception as exc:
            _logger.warning('Failed to create client %r: %s', self.type, exc)
            return None

    def build_client_init_kwargs(self, key: str | None = None) -> dict[str, object]:
        init_kw: dict[str, object] = {}
        for field_name in type(self).model_fields:
            if field_name in ('type', 'kwargs'):
                continue
            val = getattr(self, field_name)
            if field_name == 'key' or (field_name in self.model_fields_set and val is not None):
                init_kw[field_name] = val
        if self.kwargs:
            init_kw.update(self.kwargs)
        if key is not None:
            init_kw['key'] = key
        return init_kw

class CompletionClientConfig(AIServiceClientInitData['CompletionClient']):
    """Configuration for a completion client."""
    max_tokens: int | None = None
    max_images: int | None = None
    max_audios: int | None = None
    max_videos: int | None = None

class EmbeddingClientConfig(AIServiceClientInitData['EmbeddingClient']):
    """Configuration for an embedding client."""
    model: str | None = None
    max_tokens: int | None = None
    support_image: bool = False
    support_audio: bool = False
    support_video: bool = False

class S2TClientConfig(AIServiceClientInitData['S2TClient']):
    """Configuration for an S2T client."""

    def get_client(self, key: str | None = None, *, service_kind: AIServiceKind | str | None = None) -> 'S2TClient | None':
        if self.type != 'completion':
            return super().get_client(key=key, service_kind=service_kind)

        from .base import ServiceClientBase
        from .completion import CompletionService
        from .s2t import CompletionAsS2TClient

        params = dict(self.kwargs)
        completion_refs = params.pop('services', params.pop('service', params.pop('completion_service', None)))
        completion_client_refs = params.pop('clients', None)

        completion_services: list[CompletionService] = []
        if completion_refs is not None:
            refs = completion_refs if isinstance(completion_refs, list) else [completion_refs]
            for ref in refs:
                resolved = _resolve_named_service('completion', str(ref))
                if isinstance(resolved, CompletionService):
                    completion_services.append(resolved)
                else:
                    _logger.warning('Configured completion service %r was not found for S2T completion adapter.', ref)

        completion_clients: list['ServiceClientBase'] = []
        if completion_client_refs is not None:
            refs = completion_client_refs if isinstance(completion_client_refs, list) else [completion_client_refs]
            global_cfg = _get_global_config()
            completion_cfg = global_cfg.completion if global_cfg is not None else None
            for ref in refs:
                client_ref = str(ref)
                client = None
                if completion_cfg is not None and client_ref in completion_cfg.clients:
                    client = completion_cfg.clients[client_ref].get_client(
                        key=completion_cfg.scoped_client_key(client_ref),
                        service_kind='completion',
                    )
                if client is None:
                    client = ServiceClientBase.GetClient(f'completion:{client_ref}')
                if client is not None:
                    completion_clients.append(client)
                else:
                    _logger.warning('Configured completion client %r was not found for S2T completion adapter.', client_ref)

        if completion_clients:
            completion_services.append(CompletionService(*completion_clients, init_probe=False))

        if not completion_services:
            _logger.warning('No completion service/client resolved for S2T completion adapter %r.', key or self.key)
            return None

        completion_service = completion_services[0] if len(completion_services) == 1 else CompletionService(
            *[client for service in completion_services for client in service.clients],
            init_probe=False,
        )

        init_kw: dict[str, object] = {}
        for field_name in type(self).model_fields:
            if field_name in ('type', 'kwargs'):
                continue
            val = getattr(self, field_name)
            if field_name == 'key' or (field_name in self.model_fields_set and val is not None):
                init_kw[field_name] = val
        init_kw.update(params)
        if key is not None:
            init_kw['key'] = key
        try:
            return CompletionAsS2TClient(completion_service=completion_service, **init_kw)
        except Exception as exc:
            _logger.warning('Failed to create S2T completion adapter %r: %s', key or self.key, exc)
            return None

class T2SClientConfig(AIServiceClientInitData['T2SClient']):
    """Configuration for a T2S client."""


class T2ImgClientConfig(AIServiceClientInitData['T2ImgClient']):
    """Configuration for a T2Img client."""
    supported_tasks: str | list[str] | None = None
    support_image_prompt: bool = False
    support_audio_prompt: bool = False
    support_video_prompt: bool = False
    support_stream: bool = False


class AIServiceClientBinding(AdvancedBaseModel):
    """Bind a service slot to a client reference with optional service-local scheduling values.

    ``priority`` and ``strategy_lvl`` only apply inside the owning service
    instance. When omitted, scheduling falls back to the real client's defaults.
    """

    client: str | AIServiceClientInitData
    priority: float | None = None
    strategy_lvl: int | None = None

    @model_validator(mode='before')
    @classmethod
    def _normalize_input(cls, data: object) -> object:
        if isinstance(data, (str, AIServiceClientInitData)):
            return {'client': data}
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if 'strategy_lvl' in normalized and isinstance(normalized['strategy_lvl'], str):
            normalized['strategy_lvl'] = _parse_strategy_level(normalized['strategy_lvl'])
        if 'client' not in normalized:
            if 'ref' in normalized:
                normalized['client'] = normalized.pop('ref')
            elif 'client_key' in normalized:
                normalized['client'] = normalized.pop('client_key')
        return normalized

    def resolved_client_key(self) -> str | None:
        if isinstance(self.client, str):
            return self.client
        return self.client.key

    def resolved_strategy_lvl(self) -> int | None:
        if self.strategy_lvl is None:
            return None
        return int(self.strategy_lvl)

    def get_client(
        self,
        *,
        local_clients: Mapping[str, AIServiceClientInitData],
        client_scope: str,
        service_kind: AIServiceKind,
        service_key: str,
        binding_idx: int,
    ) -> 'ServiceClient[_CT] | None':    # type: ignore[return-type]
        """Resolve a service-local client binding."""
        from .base import ServiceClient, ServiceClientBase

        if isinstance(self.client, str):
            client_ref = self.client
            scoped_key = f'{client_scope}:{client_ref}'
            if client_ref in local_clients:
                client = cast(_CT | None, local_clients[client_ref].get_client(key=scoped_key, service_kind=service_kind))
            else:
                client = cast(_CT | None, ServiceClientBase.GetClient(scoped_key))
                if client is None:
                    _logger.warning(
                        'Client %r not found in %s.clients or cache key %r.',
                        client_ref,
                        service_kind,
                        scoped_key,
                    )
            if client is None:
                return None
            return ServiceClient(
                client=client,
                priority=self.priority,
                strategy_lvl=self.resolved_strategy_lvl(),
            )

        client = cast(_CT | None, self.client.get_client(service_kind=service_kind))
        if client is None:
            return None
        return ServiceClient(
            client=client,
            priority=self.priority,
            strategy_lvl=self.resolved_strategy_lvl(),
        )

class AIServiceInitData(AdvancedBaseModel):
    """Declarative configuration for a single service instance.

    ``clients`` is a list of local client config keys (resolved from the owning
    predefined service's ``clients`` dict) or inline ``AIServiceClientInitData``
    dicts. The model validator accepts shorthand: a bare ``str`` or
    ``list[str]`` is normalized to ``{'clients': ...}``.
    """

    clients: list[str | AIServiceClientBinding | AIServiceClientInitData] = Field(default_factory=list)
    """Client references (by key) or inline client configs."""
    fail_cooldown: float = 10.0
    recovery_interval: ProbeInterval | float | None = None
    kwargs: dict[str, object] = Field(default_factory=dict)
    """Extra keyword arguments forwarded to the service ``__init__``."""

    @model_validator(mode='before')
    @classmethod
    def _normalize_input(cls, data: object) -> object:
        # Accept bare str / list[str] as shorthand for {'clients': data}
        if isinstance(data, str):
            return {'clients': [data]}
        if isinstance(data, list):
            return {'clients': data}
        if not isinstance(data, dict):
            return data
        if isinstance(data.get('clients'), str):
            data['clients'] = [data['clients']]
        # Collect unknown keys into kwargs
        known = set(cls.model_fields) | {'clients', 'kwargs'}
        extra: dict[str, object] = {}
        explicit_kwargs: dict[str, object] = {}
        if 'kwargs' in data and isinstance(data['kwargs'], dict):
            explicit_kwargs = dict(data['kwargs'])
        to_remove: list[str] = []
        for k, v in data.items():
            if k not in known:
                extra[k] = v
                to_remove.append(k)
        for k in to_remove:
            del data[k]
        merged = {**explicit_kwargs, **extra}
        if merged:
            data['kwargs'] = merged
        return data


class CompletionServiceInitData(AIServiceInitData):
    """Completion service config with explicit cross-service dependencies."""

    s2t_service: str | None = None
    """Optional S2T service key used for audio/video fallback adaptation."""


class EmbeddingServiceInitData(AIServiceInitData):
    """Embedding service config with explicit multimodal fallback dependencies."""

    completion_service: str | None = None
    """Optional completion service key used for OCR/ASR-style text fallback."""
    s2t_service: str | None = None
    """Optional S2T service key used for speech-to-text fallback."""


class S2TServiceInitData(AIServiceInitData):
    """S2T service config with explicit completion-service adaptation support."""

    completion_service: str | None = None
    """Optional completion service key to adapt as an S2T client."""


class T2SServiceInitData(AIServiceInitData):
    """T2S service config. No extra typed fields beyond ``AIServiceInitData``."""


class T2ImgServiceInitData(AIServiceInitData):
    """T2Img service config with optional completion fallback dependency."""

    completion_service: str | None = None
    """Optional completion service key used to rewrite edit/variation fallback prompts."""


class AIPredefinedService(AdvancedBaseModel, Generic[_ST]):
    """Pre-defined service configurations for a specific service type.

    ``clients`` stores named client configs local to this service kind, so
    client keys can be reused across ``completion`` / ``embedding`` / ``s2t`` /
    ``t2s`` without colliding.
    ``service`` stores named service instance configs, including ``'default'``.
    """

    model_config = ConfigDict(extra='forbid')

    clients: dict[str, AIServiceClientInitData] = Field(default_factory=dict)
    """Named client configs local to the owning service kind."""
    service: dict[str, AIServiceInitData] = Field(default_factory=dict)
    """Named service configs. Keys are instance names such as ``default`` or ``summary``."""

    def get_service(self, key: str) -> _ST | None:
        """Get or create a service instance for *key*.

        Looks up the key in ``ServiceBase.ServiceInstances`` first; if not found,
        creates it from ``service.<key>``.
        """
        from .base import ServiceBase
        # Try cached instance first
        service_cls = self._resolve_service_cls()
        existing = service_cls.GetInstance(key, fallback='')  # type: ignore[arg-type]
        if existing is not None:
            return existing  # type: ignore[return-value]
        cfg = self.service.get(key)
        if cfg is None:
            return None
        return self._build_service_from_config(cfg, key=key)

    def get_default(self) -> _ST | None:
        """Shortcut for ``get_service('default')``."""
        service = self.get_service('default')
        if service is not None:
            return service
        if self.clients:
            return self._build_service_from_config(
                AIServiceInitData(clients=list(self.clients)),
                key='default',
            )
        return None

    def preload_service_instances(self) -> None:
        """Create every configured non-default service instance."""
        for key in self.service:
            if key != 'default':
                self.get_service(key)

    def scoped_client_key(self, client_key: str) -> str:
        return f'{self._resolve_service_cls().ServiceKind()}:{client_key}'

    def _resolve_service_cls(self) -> type["ServiceBase"]:
        """Resolve the concrete service class from the generic type parameter."""
        raise NotImplementedError(
            'Subclasses must override _resolve_service_cls to return the concrete ServiceBase subclass.'
        )

    def _resolve_service_kwargs(self, cfg: AIServiceInitData, *, key: str) -> dict[str, object]:
        return {}

    def _resolve_additional_clients(self, cfg: AIServiceInitData, *, key: str) -> list['ServiceClientBase']:
        return []

    def build_service_clients(self, cfg: AIServiceInitData, *, key: str) -> list[object]:
        from .base import ServiceClientBase
        service_cls = self._resolve_service_cls()
        clients: list[object] = []
        service_kind = cast(AIServiceKind, service_cls.ServiceKind())

        for binding_idx, client_ref in enumerate(cfg.clients):
            if isinstance(client_ref, AIServiceClientBinding):
                client = client_ref.get_client(
                    local_clients=self.clients,
                    client_scope=service_kind,
                    service_kind=service_kind,
                    service_key=key,
                    binding_idx=binding_idx,
                )
                if client is not None:
                    clients.append(client)
                continue
            if isinstance(client_ref, str):
                scoped_client_key = self.scoped_client_key(client_ref)
                if client_ref in self.clients:
                    client = self.clients[client_ref].get_client(key=scoped_client_key, service_kind=service_kind)
                    if client is not None:
                        clients.append(client)
                else:
                    existing = ServiceClientBase.GetClient(scoped_client_key)
                    if existing is not None:
                        clients.append(existing)
                    else:
                        _logger.warning(
                            'Client %r not found in %s.clients or cache key %r.',
                            client_ref,
                            service_kind,
                            scoped_client_key,
                        )
            elif isinstance(client_ref, AIServiceClientInitData):
                client = client_ref.get_client(service_kind=service_kind)
                if client is not None:
                    clients.append(client)
        clients.extend(self._resolve_additional_clients(cfg, key=key))
        return clients

    def build_service_init_kwargs(self, cfg: AIServiceInitData, *, key: str) -> dict[str, object]:
        init_kw: dict[str, object] = {
            'fail_cooldown': cfg.fail_cooldown,
            'init_probe': False,
            'key': key,
        }
        if 'recovery_interval' in cfg.model_fields_set:
            init_kw['recovery_interval'] = cfg.recovery_interval
        if cfg.kwargs:
            init_kw.update(cfg.kwargs)
        related_kwargs = self._resolve_service_kwargs(cfg, key=key)
        if related_kwargs:
            init_kw.update(related_kwargs)
        return init_kw

    def _build_service_from_config(
        self, cfg: AIServiceInitData, *, key: str,
    ) -> _ST | None:
        """Instantiate a service from an ``AIServiceInitData`` config."""
        service_cls = self._resolve_service_cls()
        clients = self.build_service_clients(cfg, key=key)
        try:
            init_kw = self.build_service_init_kwargs(cfg, key=key)
            return service_cls(*clients, **init_kw)  # type: ignore[return-value]
        except Exception as exc:
            _logger.warning('Failed to create service %s (key=%r): %s', service_cls.__name__, key, exc)
            return None


def _resolve_named_service(service_kind: AIServiceKind | str, service_key: str | None) -> 'ServiceBase | None':
    normalized_kind = str(service_kind or '').strip().lower()
    normalized_key = str(service_key or '').strip()
    if not normalized_kind or not normalized_key:
        return None

    service_cls: type['ServiceBase'] | None = None
    if normalized_kind == 'completion':
        from .completion import CompletionService
        service_cls = CompletionService
    elif normalized_kind == 'embedding':
        from .embedding import EmbeddingService
        service_cls = EmbeddingService
    elif normalized_kind == 's2t':
        from .s2t import S2TService
        service_cls = S2TService
    elif normalized_kind == 't2s':
        from .t2s import T2SService
        service_cls = T2SService
    elif normalized_kind == 't2img':
        from .t2img import T2ImgService
        service_cls = T2ImgService
    if service_cls is None:
        return None

    existing = service_cls.GetInstance(normalized_key, fallback='')
    if existing is not None:
        return existing

    global_cfg = _get_global_config()
    if global_cfg is not None:
        predefined = getattr(global_cfg, normalized_kind, None)
        if predefined is not None:
            service = predefined.get_service(normalized_key)
            if service is not None:
                return service

    if normalized_key == 'default':
        try:
            return service_cls.Default()
        except Exception as exc:
            _logger.warning(
                'Failed to resolve %s service %r while building dependent AI service config: %s',
                normalized_kind,
                normalized_key,
                exc,
            )
    return None

# ══════════════════════════════════════════════════════════════════════════════
# Concrete PredefinedServices per service kind
# ══════════════════════════════════════════════════════════════════════════════

class PredefinedCompletionService(AIPredefinedService['CompletionService']):
    """Predefined configs for CompletionService instances."""
    clients: dict[str, CompletionClientConfig] = Field(default_factory=dict)
    service: dict[str, CompletionServiceInitData] = Field(default_factory=dict)

    def _resolve_service_cls(self) -> type['CompletionService']:
        from .completion import CompletionService
        return CompletionService

    def _resolve_service_kwargs(self, cfg: AIServiceInitData, *, key: str) -> dict[str, object]:
        if not isinstance(cfg, CompletionServiceInitData) or not cfg.s2t_service:
            return {}
        s2t_service = _resolve_named_service('s2t', cfg.s2t_service)
        if s2t_service is None:
            _logger.warning('Configured S2T service %r was not found for completion service %r.', cfg.s2t_service, key)
            return {}
        return {'s2t_service': s2t_service}

class PredefinedEmbeddingService(AIPredefinedService['EmbeddingService']):
    """Predefined configs for EmbeddingService instances."""
    clients: dict[str, EmbeddingClientConfig] = Field(default_factory=dict)
    service: dict[str, EmbeddingServiceInitData] = Field(default_factory=dict)

    def _resolve_service_cls(self) -> type['EmbeddingService']:
        from .embedding import EmbeddingService
        return EmbeddingService

    def _resolve_service_kwargs(self, cfg: AIServiceInitData, *, key: str) -> dict[str, object]:
        if not isinstance(cfg, EmbeddingServiceInitData):
            return {}
        resolved: dict[str, object] = {}
        if cfg.completion_service:
            completion_service = _resolve_named_service('completion', cfg.completion_service)
            if completion_service is None:
                _logger.warning(
                    'Configured completion service %r was not found for embedding service %r.',
                    cfg.completion_service,
                    key,
                )
            else:
                resolved['completion_service'] = completion_service
        if cfg.s2t_service:
            s2t_service = _resolve_named_service('s2t', cfg.s2t_service)
            if s2t_service is None:
                _logger.warning('Configured S2T service %r was not found for embedding service %r.', cfg.s2t_service, key)
            else:
                resolved['s2t_service'] = s2t_service
        return resolved

class PredefinedS2TService(AIPredefinedService['S2TService']):
    """Predefined configs for S2TService instances."""
    clients: dict[str, S2TClientConfig] = Field(default_factory=dict)
    service: dict[str, S2TServiceInitData] = Field(default_factory=dict)

    def _resolve_service_cls(self) -> type['S2TService']:
        from .s2t import S2TService
        return S2TService

    def _resolve_additional_clients(self, cfg: AIServiceInitData, *, key: str) -> list['ServiceClientBase']:
        if not isinstance(cfg, S2TServiceInitData) or not cfg.completion_service:
            return []
        completion_service = _resolve_named_service('completion', cfg.completion_service)
        if completion_service is None:
            _logger.warning('Configured completion service %r was not found for S2T service %r.', cfg.completion_service, key)
            return []
        return [completion_service]

class PredefinedT2SService(AIPredefinedService['T2SService']):
    """Predefined configs for T2SService instances."""
    clients: dict[str, T2SClientConfig] = Field(default_factory=dict)
    service: dict[str, T2SServiceInitData] = Field(default_factory=dict)

    def _resolve_service_cls(self) -> type['T2SService']:
        from .t2s import T2SService
        return T2SService


class PredefinedT2ImgService(AIPredefinedService['T2ImgService']):
    """Predefined configs for T2ImgService instances."""
    clients: dict[str, T2ImgClientConfig] = Field(default_factory=dict)
    service: dict[str, T2ImgServiceInitData] = Field(default_factory=dict)

    def _resolve_service_cls(self) -> type['T2ImgService']:
        from .t2img import T2ImgService
        return T2ImgService

    def _resolve_service_kwargs(self, cfg: AIServiceInitData, *, key: str) -> dict[str, object]:
        if not isinstance(cfg, T2ImgServiceInitData) or not cfg.completion_service:
            return {}
        completion_service = _resolve_named_service('completion', cfg.completion_service)
        if completion_service is None:
            _logger.warning('Configured completion service %r was not found for T2Img service %r.', cfg.completion_service, key)
            return {}
        return {'completion_service': completion_service}

class AIServicesConfig(AdvancedBaseModel):
    """Top-level configuration for all AI services.

    Can be loaded from:
    1. ``__AI_SERVICES_CONFIG__`` environment variable (serialized JSON)
    2. ``PROJECT_DIR/config/ai_services.yaml|json|toml``
    """

    __Instance__: ClassVar[Self | None] = None
    _source_path: Path | None = PrivateAttr(default=None)

    kwargs: dict[str, dict[str, object]] = Field(default_factory=dict)
    """Shared kwargs presets available to all service-kind client configs."""
    completion: PredefinedCompletionService = Field(default_factory=PredefinedCompletionService)
    """Completion service configs plus completion-local client definitions."""
    embedding: PredefinedEmbeddingService = Field(default_factory=PredefinedEmbeddingService)
    """Embedding service configs plus embedding-local client definitions."""
    s2t: PredefinedS2TService = Field(default_factory=PredefinedS2TService)
    """S2T service configs plus S2T-local client definitions."""
    t2s: PredefinedT2SService = Field(default_factory=PredefinedT2SService)
    """T2S service configs plus T2S-local client definitions."""
    t2img: PredefinedT2ImgService = Field(default_factory=PredefinedT2ImgService)
    """T2Img service configs plus T2Img-local client definitions."""

    @model_validator(mode='before')
    @classmethod
    def _normalize_input(cls, data: object) -> object:
        return _normalize_ai_services_config_data(data)

    @classmethod
    def Global(cls) -> Self | None:
        """Return the global config singleton, loading it if necessary."""
        if cls.__Instance__ is not None:
            return cls.__Instance__
        cls.__Instance__ = cls.AutoLoad(prefer_mode_specific=_prefer_mode_specific_default_paths())
        return cls.__Instance__

    @classmethod
    def SetGlobal(cls, config: Self | None) -> None:
        """Set or clear the global config singleton."""
        if config is not None and config.source_path() is None:
            source_path = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
            if source_path:
                config.set_source_path(source_path)
        cls.__Instance__ = config

    def source_path(self) -> Path | None:
        return self._source_path

    def set_source_path(self, path: str | Path | None) -> Self:
        self._source_path = Path(path) if path is not None else None
        return self

    @classmethod
    def Load(cls, path: str | Path, *, set_global: bool = False) -> Self:
        source_path = Path(path)
        config = cls.model_validate(_load_config_file(source_path))
        config.set_source_path(source_path)
        if set_global:
            cls.SetGlobal(config)
        return config

    @classmethod
    def _try_load_from_env(cls) -> Self | None:
        env_data = os.environ.get('__AI_SERVICES_CONFIG__')
        if env_data:
            try:
                data = json.loads(env_data)
                config = cls.model_validate(data)
                source_path = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
                if source_path:
                    config.set_source_path(source_path)
                return config
            except Exception as exc:
                _logger.warning('Failed to load AI services config from env: %s', exc)
        return None

    @classmethod
    def _try_load_from_files(cls, *, prefer_mode_specific: bool | None = None) -> Self | None:
        for path in _discover_ai_services_config_paths(prefer_mode_specific=prefer_mode_specific):
            if not path.is_file():
                continue
            try:
                data = _load_config_file(path)
                config = cls.model_validate(data)
                config.set_source_path(path)
                _logger.info('Auto-discovered AI services config from %s', path)
                return config
            except Exception as exc:
                _logger.warning('Failed to load AI services config from %s: %s', path, exc)
        return None

    @classmethod
    def AutoLoad(cls, *, prefer_mode_specific: bool | None = None) -> Self | None:
        return cls._try_load_from_env() or cls._try_load_from_files(prefer_mode_specific=prefer_mode_specific)

    def to_serialized_env(self) -> str:
        """Serialize to JSON for ``__AI_SERVICES_CONFIG__`` env var."""
        return self.model_dump_json()


# ══════════════════════════════════════════════════════════════════════════════
# Config file loaders
# ══════════════════════════════════════════════════════════════════════════════

def _load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'AI services config root in {path} must be a mapping.')
    return data

def _load_yaml(path):
    import yaml  # type: ignore[import-untyped]
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f'AI services config root in {path} must be a mapping.')
    return data

def _load_toml(path):
    try:
        import tomllib  # type: ignore
    except ImportError:
        import tomli as tomllib  # type: ignore
    with open(path, 'rb') as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'AI services config root in {path} must be a mapping.')
    return data

_CONFIG_LOADERS: list[tuple[str, ConfigLoader]] = [
    ('.yaml', _load_yaml),
    ('.yml', _load_yaml),
    ('.json', _load_json),
    ('.toml', _load_toml),
]

def _prefer_mode_specific_default_paths() -> bool:
    return any(str(os.getenv(key, '') or '').strip() for key in _SERVER_RUNTIME_ENV_KEYS)


def _ai_services_config_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for base in (Path.cwd(), PROJECT_DIR):
        try:
            resolved = Path(base).resolve()
        except Exception:
            resolved = Path(base)
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _ai_services_name_order(*, prefer_mode_specific: bool | None = None) -> list[str]:
    prefer_mode_specific = _prefer_mode_specific_default_paths() if prefer_mode_specific is None else prefer_mode_specific
    mode = str(os.getenv('__MODE__', '')).strip().lower()
    if prefer_mode_specific and mode in {'dev', 'prod'}:
        opposite_mode = 'prod' if mode == 'dev' else 'dev'
        return [f'ai_services.{mode}', f'{mode}_ai_services', 'ai_services', f'ai_services.{opposite_mode}', f'{opposite_mode}_ai_services']
    return ['ai_services', 'ai_services.dev', 'ai_services.prod', 'dev_ai_services', 'prod_ai_services']


def _discover_ai_services_config_paths(*, prefer_mode_specific: bool | None = None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in _ai_services_config_roots():
        config_dir = root / 'config'
        for stem in _ai_services_name_order(prefer_mode_specific=prefer_mode_specific):
            for suffix in _AI_SERVICES_FILE_SUFFIXES:
                path = config_dir / f'{stem}{suffix}'
                if path in seen:
                    continue
                seen.add(path)
                candidates.append(path)
    return candidates


def _load_config_file(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    for ext, loader in _CONFIG_LOADERS:
        if ext == suffix:
            return loader(path)
    raise ValueError(f'Unsupported AI services config file format: {path.suffix}')

def _get_global_config() -> AIServicesConfig | None:
    return AIServicesConfig.Global()


__all__ = [
    'AIServiceClientInitData',
    'CompletionClientConfig',
    'EmbeddingClientConfig',
    'S2TClientConfig',
    'T2SClientConfig',
    'AIServiceInitData',
    'CompletionServiceInitData',
    'EmbeddingServiceInitData',
    'S2TServiceInitData',
    'T2SServiceInitData',
    'AIPredefinedService',
    'PredefinedCompletionService',
    'PredefinedEmbeddingService',
    'PredefinedS2TService',
    'PredefinedT2SService',
    'AIServicesConfig',
    'AI_SERVICES_CONFIG_SOURCE_ENV',
]
