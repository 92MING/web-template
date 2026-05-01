# -*- coding: utf-8 -*-
"""AI services configuration models.

Provides typed config classes that can be loaded from YAML / JSON / TOML / env
and used to instantiate AI service clients and services declaratively.
"""
import os
import json
import logging
from pathlib import Path

from typing import TYPE_CHECKING, Callable, ClassVar, Generic, Mapping, TypeVar, Self, cast
from pydantic import Field, model_validator, ConfigDict

from core.utils.type_utils import AdvancedBaseModel
from core.constants import PROJECT_DIR
from .shared import AIServiceKind

if TYPE_CHECKING:
    from .base import ServiceClient, ServiceClientBase, ServiceBase
    from .completion import CompletionService, CompletionClient
    from .embedding import EmbeddingService, EmbeddingClient
    from .s2t import S2TService, S2TClient
    from .t2s import T2SService, T2SClient

_logger = logging.getLogger(__name__)
_AI_SERVICES_FILE_SUFFIXES: tuple[str, ...] = ('.yaml', '.yml', '.json', '.toml')
_SERVER_RUNTIME_ENV_KEYS: tuple[str, ...] = (
    'IN_UVICORN_PROCESS',
    '__SERVER_PROCESS_PID__',
    '__SERVER_SUPERVISOR_PID__',
    '__SERVER_INSTANCE_ID__',
)

_CT = TypeVar('_CT', bound='ServiceClientBase')
_ST = TypeVar('_ST', bound='ServiceBase')

ConfigMapping = dict[str, object]
ConfigLoader = Callable[[Path], ConfigMapping]

class AIServiceClientInitData(AdvancedBaseModel, Generic[_CT]):
    """Declarative configuration for a single AI service client.

    ``type`` maps to the registered client type (via ``__init_subclass__``).
    Common fields mirror :class:`ServiceClientInitParams`.  Extra unknown
    keys are collected into ``kwargs`` automatically.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    """Registered client type string, e.g. ``'tts-completion'``, ``'openai-completion'``."""
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

    _RESERVED_FIELDS: ClassVar[frozenset[str]] = frozenset({'type', 'key', 'max_concurrent', 'priority', 'strategy_lvl', 'kwargs'})

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

    def get_client(self, key: str | None = None) -> _CT | None:
        """Instantiate and return the client described by this config.

        Args:
            key: Override the config's ``key`` field for the created instance.
        """
        from .base import ServiceClientBase
        client_cls = ServiceClientBase.GetClientCls(self.type)
        if client_cls is None:
            _logger.warning('Unknown client type %r, cannot create client.', self.type)
            return None
        init_kw: dict[str, object] = {}
        for field_name in type(self).model_fields:
            if field_name in ('type', 'kwargs'):
                continue
            val = getattr(self, field_name)
            if val is not None or field_name == 'key':
                init_kw[field_name] = val
        if self.kwargs:
            init_kw.update(self.kwargs)
        if key is not None:
            init_kw['key'] = key
        try:
            return client_cls(**init_kw)  # type: ignore[return-value]
        except Exception as exc:
            _logger.warning('Failed to create client %r: %s', self.type, exc)
            return None

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

class T2SClientConfig(AIServiceClientInitData['T2SClient']):
    """Configuration for a T2S client."""


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
                client = cast(_CT | None, local_clients[client_ref].get_client(key=scoped_key))
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

        client = cast(_CT | None, self.client.get_client())
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
    recovery_interval: float | None = None
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

class AIPredefinedService(AdvancedBaseModel, Generic[_ST]):
    """Pre-defined service configurations for a specific service type.

    ``clients`` stores named client configs local to this service kind, so
    client keys can be reused across ``completion`` / ``embedding`` / ``s2t`` /
    ``t2s`` without colliding.
    ``default`` is the config used by ``ServiceBase.Default()``.
    ``extras`` holds additional named service configs (e.g. ``'advanced'``).
    Unknown keys that look like service init data are auto-collected into ``extras``.
    """

    clients: dict[str, AIServiceClientInitData] = Field(default_factory=dict)
    """Named client configs local to the owning service kind."""
    default: AIServiceInitData | None = None
    """Default service config (used by ``Default()``)."""
    extras: dict[str, AIServiceInitData] = Field(default_factory=dict)
    """Named additional service configs.  Keys are instance names."""

    @model_validator(mode='before')
    @classmethod
    def _collect_extras(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        known = set(cls.model_fields) | {'default', 'extras'}
        extras_in: dict[str, object] = {}
        if 'extras' in data and isinstance(data['extras'], dict):
            extras_in = dict(data['extras'])
        to_remove: list[str] = []
        for k, v in data.items():
            if k not in known and _looks_like_service_init_data(v):
                extras_in[k] = v
                to_remove.append(k)
        for k in to_remove:
            del data[k]
        if extras_in:
            data['extras'] = extras_in
        return data

    def get_service(self, key: str) -> _ST | None:
        """Get or create a service instance for *key*.

        Looks up the key in ``ServiceBase.ServiceInstances`` first; if not found,
        creates it from the config (``default`` for ``'default'``, otherwise ``extras``).
        """
        from .base import ServiceBase
        # Try cached instance first
        service_cls = self._resolve_service_cls()
        existing = service_cls.GetInstance(key)  # type: ignore[arg-type]
        if existing is not None:
            return existing  # type: ignore[return-value]
        # Get config for key
        if key == 'default':
            cfg = self.default
        else:
            cfg = self.extras.get(key)
        if cfg is None:
            return None
        return self._build_service_from_config(cfg, key=key)

    def get_default(self) -> _ST | None:
        """Shortcut for ``get_service('default')``."""
        return self.get_service('default')

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

    def _build_service_from_config(
        self, cfg: AIServiceInitData, *, key: str,
    ) -> _ST | None:
        """Instantiate a service from an ``AIServiceInitData`` config."""
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
                    client = self.clients[client_ref].get_client(key=scoped_client_key)
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
                client = client_ref.get_client()
                if client is not None:
                    clients.append(client)
        clients.extend(self._resolve_additional_clients(cfg, key=key))
        if not clients:
            _logger.warning('No clients resolved for service %s key=%r', service_cls.__name__, key)
            return None
        try:
            init_kw: dict[str, object] = {
                'fail_cooldown': cfg.fail_cooldown,
                'key': key,
            }
            if cfg.recovery_interval is not None:
                init_kw['recovery_interval'] = cfg.recovery_interval
            if cfg.kwargs:
                init_kw.update(cfg.kwargs)
            related_kwargs = self._resolve_service_kwargs(cfg, key=key)
            if related_kwargs:
                init_kw.update(related_kwargs)
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
    if service_cls is None:
        return None

    existing = service_cls.GetInstance(normalized_key)
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


def _looks_like_service_init_data(v: object) -> bool:
    """Heuristic: does *v* look like an ``AIServiceInitData`` or shorthand?"""
    if isinstance(v, (str, list)):
        return True
    if isinstance(v, AIServiceInitData):
        return True
    if isinstance(v, dict):
        return 'clients' in v or any(isinstance(val, (str, list)) for val in v.values())
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Concrete PredefinedServices per service kind
# ══════════════════════════════════════════════════════════════════════════════

class PredefinedCompletionService(AIPredefinedService['CompletionService']):
    """Predefined configs for CompletionService instances."""
    clients: dict[str, CompletionClientConfig] = Field(default_factory=dict)
    default: CompletionServiceInitData | None = None
    extras: dict[str, CompletionServiceInitData] = Field(default_factory=dict)

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
    default: EmbeddingServiceInitData | None = None
    extras: dict[str, EmbeddingServiceInitData] = Field(default_factory=dict)

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
    default: S2TServiceInitData | None = None
    extras: dict[str, S2TServiceInitData] = Field(default_factory=dict)

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
    default: T2SServiceInitData | None = None
    extras: dict[str, T2SServiceInitData] = Field(default_factory=dict)

    def _resolve_service_cls(self) -> type['T2SService']:
        from .t2s import T2SService
        return T2SService

class AIServicesConfig(AdvancedBaseModel):
    """Top-level configuration for all AI services.

    Can be loaded from:
    1. ``__AI_SERVICES_CONFIG__`` environment variable (serialized JSON)
    2. ``PROJECT_DIR/config/ai_services.yaml|json|toml``
    """

    __Instance__: ClassVar[Self | None] = None

    completion: PredefinedCompletionService = Field(default_factory=PredefinedCompletionService)
    """Completion service configs plus completion-local client definitions."""
    embedding: PredefinedEmbeddingService = Field(default_factory=PredefinedEmbeddingService)
    """Embedding service configs plus embedding-local client definitions."""
    s2t: PredefinedS2TService = Field(default_factory=PredefinedS2TService)
    """S2T service configs plus S2T-local client definitions."""
    t2s: PredefinedT2SService = Field(default_factory=PredefinedT2SService)
    """T2S service configs plus T2S-local client definitions."""

    @model_validator(mode='before')
    @classmethod
    def _reject_global_clients(cls, data: object) -> object:
        if isinstance(data, dict) and 'clients' in data:
            raise ValueError(
                'AIServicesConfig top-level `clients` 已移除；请改为 `completion.clients` / '
                '`embedding.clients` / `s2t.clients` / `t2s.clients`。'
            )
        return data

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
        cls.__Instance__ = config

    @classmethod
    def _try_load_from_env(cls) -> Self | None:
        env_data = os.environ.get('__AI_SERVICES_CONFIG__')
        if env_data:
            try:
                data = json.loads(env_data)
                return cls.model_validate(data)
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
        return [f'ai_services.{mode}', 'ai_services', f'ai_services.{opposite_mode}', f'{mode}_ai_services', f'{opposite_mode}_ai_services']
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
]
