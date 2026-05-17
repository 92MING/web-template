# -*- coding: utf-8 -*-
"""Tests for AI services configuration system.

Covers:
  - AIServiceClientInitData extra-key collection and client instantiation
  - AIServiceInitData normalization (bare str / list / dict)
    - AIPredefinedService service map & get_service
  - AIServicesConfig singleton, Global(), SetGlobal(), env loading
  - ServiceBase.ServiceInstances + GetInstance key-based lookup
  - Server Config.BuildArgParser --ai-services-config
  - Server Config.CreateConfigFromArgs writes __AI_SERVICES_CONFIG__ to env
"""


import os
import sys
import json
import time
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from pathlib import Path

from aiohttp import web
from pydantic import BaseModel

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SERVER_PACKAGE = 'data_types.config'
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.ai.base import (
    ProbeInterval,
    _CLIENT_TYPE_REGISTRY,
    ServiceBase,
    ServiceClient,
    ServiceClientBase,
)
from core.ai.config import (
    AIServiceClientInitData,
    AIServiceClientBinding,
    AIServiceInitData,
    AI_SERVICES_CONFIG_SOURCE_ENV,
    CompletionServiceInitData,
    EmbeddingServiceInitData,
    S2TServiceInitData,
    T2SServiceInitData,
    T2ImgServiceInitData,
    AIPredefinedService,
    PredefinedCompletionService,
    PredefinedEmbeddingService,
    PredefinedS2TService,
    PredefinedT2SService,
    AIServicesConfig,
)
from core.ai.completion import CompletionClient, ThinkThinkSynCompletionClient, OpenAILikedCompletionClient, OpenRouterCompletionClient, CustomCompletionClient
from core.ai.embedding import EmbeddingClient
from core.ai.completion import CompletionService
from core.ai.embedding import EmbeddingService, ThinkThinkSynEmbeddingClient, OpenAILikedEmbeddingClient, CustomEmbeddingClient
from core.ai.s2t import S2TClient, S2TService, CompletionAsS2TClient, OpenAILikedS2TClient, OpenRouterS2TClient, CustomS2TClient
from core.ai.t2s import T2SClient, T2SService, ThinkThinkSynT2SClient, OpenAILikedT2SClient, CustomT2SClient
from core.ai.t2img import T2ImgClient, T2ImgService, OpenAILikedT2ImgClient, OpenRouterT2ImgClient
from core.utils.data_structs import Audio


def _write_adapter_script(path: Path, content: str) -> str:
    path.write_text(textwrap.dedent(content), encoding='utf-8')
    return path.resolve().as_uri()


# ══════════════════════════════════════════════════════════════════════════════
# Fake service / client classes for isolated testing
# ══════════════════════════════════════════════════════════════════════════════

class _FakeConfigClient(ServiceClientBase, type='fake-config-test'):
    """A minimal client whose type is registered for config lookup."""

    ServiceKind = 'completion'

    def __init__(self, *, key: str | None = None, model: str = 'test-model', **kw):
        super().__init__(key=key, **kw)
        self.model = model

    def update(self, **new_params: object) -> bool:
        params = dict(new_params)
        model = params.pop('model', None) if 'model' in params else None
        if not super().update(**params):
            return False
        if 'model' in new_params:
            self.model = str(model)
        return True

    @classmethod
    def TestingInput(cls):
        return None

    async def probe_min_health(self) -> bool:
        return True


class _FakeConfigService(ServiceBase):
    """A minimal service for testing config-driven creation."""

    @classmethod
    def ServiceKind(cls) -> str:
        return 'completion'

    def __init__(self, *clients: _FakeConfigClient, **kwargs):
        kwargs.setdefault('fail_cooldown', 1.0)
        super().__init__(*clients, **kwargs)

    @classmethod
    def Default(cls) -> '_FakeConfigService':
        return cls(_FakeConfigClient())


class _FakeConfigPredefined(AIPredefinedService['_FakeConfigService']):
    def _resolve_service_cls(self):
        return _FakeConfigService


def tearDownModule() -> None:
    _CLIENT_TYPE_REGISTRY.pop(('completion', 'fake-config-test'), None)
    _CLIENT_TYPE_REGISTRY.pop(('completion', 'fakeconfigtest'), None)


# ══════════════════════════════════════════════════════════════════════════════
# Tests — AIServiceClientInitData
# ══════════════════════════════════════════════════════════════════════════════

class TestAIServiceClientInitData(unittest.TestCase):

    def test_basic_fields(self):
        cfg = AIServiceClientInitData(type='fake-config-test')
        self.assertEqual(cfg.type, 'fake-config-test')
        self.assertIsNone(cfg.key)
        self.assertEqual(cfg.priority, 0.0)
        self.assertEqual(cfg.kwargs, {})

    def test_extra_keys_collected_into_kwargs(self):
        data = {
            'type': 'fake-config-test',
            'model': 'gpt-4',
            'temperature': 0.5,
        }
        cfg = AIServiceClientInitData.model_validate(data)
        self.assertEqual(cfg.kwargs['model'], 'gpt-4')
        self.assertEqual(cfg.kwargs['temperature'], 0.5)

    def test_explicit_kwargs_merged_with_extras(self):
        data = {
            'type': 'fake-config-test',
            'kwargs': {'existing_key': 1},
            'extra_field': 'hello',
        }
        cfg = AIServiceClientInitData.model_validate(data)
        self.assertEqual(cfg.kwargs['existing_key'], 1)
        self.assertEqual(cfg.kwargs['extra_field'], 'hello')

    def test_get_client_creates_instance(self):
        cfg = AIServiceClientInitData(type='fake-config-test', kwargs={'model': 'test-v2'})
        client = cfg.get_client()
        self.assertIsNotNone(client)
        self.assertIsInstance(client, _FakeConfigClient)
        self.assertEqual(client.model, 'test-v2')

    def test_get_client_unknown_type_returns_none(self):
        cfg = AIServiceClientInitData(type='nonexistent-type-xyz')
        client = cfg.get_client()
        self.assertIsNone(client)

    def test_get_client_key_override(self):
        cfg = AIServiceClientInitData(type='fake-config-test', key='original')
        client = cfg.get_client(key='overridden')
        self.assertIsNotNone(client)
        # The cache key should be 'overridden'
        found = ServiceClientBase.GetClient('overridden')
        self.assertIs(found, client)

    def test_registered_client_types_are_scoped_by_service_kind(self):
        self.assertIs(ServiceClientBase.GetClientCls('thinkthinksyn', service_kind='completion'), ThinkThinkSynCompletionClient)
        self.assertIs(ServiceClientBase.GetClientCls('openai', service_kind='completion'), OpenAILikedCompletionClient)
        self.assertIs(ServiceClientBase.GetClientCls('openrouter', service_kind='completion'), OpenRouterCompletionClient)
        self.assertIs(ServiceClientBase.GetClientCls('custom', service_kind='completion'), CustomCompletionClient)
        self.assertIs(ServiceClientBase.GetClientCls('thinkthinksyn', service_kind='embedding'), ThinkThinkSynEmbeddingClient)
        self.assertIs(ServiceClientBase.GetClientCls('openai', service_kind='embedding'), OpenAILikedEmbeddingClient)
        self.assertIs(ServiceClientBase.GetClientCls('custom', service_kind='embedding'), CustomEmbeddingClient)
        self.assertIs(ServiceClientBase.GetClientCls('completion', service_kind='s2t'), CompletionAsS2TClient)
        self.assertIs(ServiceClientBase.GetClientCls('openai', service_kind='s2t'), OpenAILikedS2TClient)
        self.assertIs(ServiceClientBase.GetClientCls('openrouter', service_kind='s2t'), OpenRouterS2TClient)
        self.assertIs(ServiceClientBase.GetClientCls('custom', service_kind='s2t'), CustomS2TClient)
        self.assertIs(ServiceClientBase.GetClientCls('thinkthinksyn', service_kind='t2s'), ThinkThinkSynT2SClient)
        self.assertIs(ServiceClientBase.GetClientCls('openai', service_kind='t2s'), OpenAILikedT2SClient)
        self.assertIs(ServiceClientBase.GetClientCls('custom', service_kind='t2s'), CustomT2SClient)
        self.assertIs(ServiceClientBase.GetClientCls('openai', service_kind='t2img'), OpenAILikedT2ImgClient)
        self.assertIs(ServiceClientBase.GetClientCls('openrouter', service_kind='t2img'), OpenRouterT2ImgClient)
        self.assertIn('openai', ServiceClientBase.RegisteredClientTypes(service_kind='completion'))
        self.assertIn('openrouter', ServiceClientBase.RegisteredClientTypes(service_kind='completion'))
        self.assertIn('openai', ServiceClientBase.RegisteredClientTypes(service_kind='embedding'))
        self.assertIn('openai', ServiceClientBase.RegisteredClientTypes(service_kind='s2t'))
        self.assertIn('openrouter', ServiceClientBase.RegisteredClientTypes(service_kind='s2t'))
        self.assertIn('openai', ServiceClientBase.RegisteredClientTypes(service_kind='t2s'))
        self.assertIn('openai', ServiceClientBase.RegisteredClientTypes(service_kind='t2img'))
        self.assertIn('openrouter', ServiceClientBase.RegisteredClientTypes(service_kind='t2img'))
        self.assertIn('thinkthinksyn', ServiceClientBase.RegisteredClientTypes(service_kind='completion'))

    def test_get_client_uses_registered_completion_class_config_constructor(self):
        created_client = object()
        cfg = AIServiceClientInitData(type='thinkthinksyn', kwargs={'apikey': 'test-key', 'model_filter': 'Name == test'})

        with patch.object(ThinkThinkSynCompletionClient, 'CreateFromConfig', return_value=created_client) as factory:
            client = cfg.get_client(key='completion:tts', service_kind='completion')

        self.assertIs(client, created_client)
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['key'], 'completion:tts')
        self.assertEqual(factory.call_args.kwargs['apikey'], 'test-key')
        self.assertEqual(factory.call_args.kwargs['model_filter'], 'Name == test')

    def test_get_client_uses_registered_embedding_class_config_constructor(self):
        created_client = object()
        cfg = AIServiceClientInitData(type='thinkthinksyn', kwargs={'apikey': 'test-key', 'model': 'zpoint'})

        with patch.object(ThinkThinkSynEmbeddingClient, 'CreateFromConfig', return_value=created_client) as factory:
            client = cfg.get_client(key='embedding:zpoint', service_kind='embedding')

        self.assertIs(client, created_client)
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['key'], 'embedding:zpoint')
        self.assertEqual(factory.call_args.kwargs['apikey'], 'test-key')
        self.assertEqual(factory.call_args.kwargs['model'], 'zpoint')

    def test_get_client_uses_registered_openai_class_config_constructor(self):
        created_client = object()
        cfg = AIServiceClientInitData(type='openai', kwargs={'model': 'remote-model', 'ssh_tunnel': 'remote-host'})

        with patch.object(OpenAILikedCompletionClient, 'CreateFromConfig', return_value=created_client) as factory:
            client = cfg.get_client(key='completion:remote', service_kind='completion')

        self.assertIs(client, created_client)
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['key'], 'completion:remote')
        self.assertEqual(factory.call_args.kwargs['model'], 'remote-model')
        self.assertEqual(factory.call_args.kwargs['ssh_tunnel'], 'remote-host')
        self.assertIn('completion', ServiceClientBase.RegisteredClientTypes(service_kind='s2t'))


# ══════════════════════════════════════════════════════════════════════════════
# Tests — AIServiceInitData
# ══════════════════════════════════════════════════════════════════════════════

class TestAIServiceInitData(unittest.TestCase):

    def test_bare_str_normalized_to_clients(self):
        cfg = AIServiceInitData.model_validate('client-a')
        self.assertEqual(cfg.clients, ['client-a'])

    def test_bare_list_normalized_to_clients(self):
        cfg = AIServiceInitData.model_validate(['a', 'b'])
        self.assertEqual(cfg.clients, ['a', 'b'])

    def test_dict_with_clients(self):
        cfg = AIServiceInitData.model_validate({'clients': ['x'], 'fail_cooldown': 5.0})
        self.assertEqual(cfg.clients, ['x'])
        self.assertEqual(cfg.fail_cooldown, 5.0)

    def test_dict_with_bare_clients_string(self):
        cfg = AIServiceInitData.model_validate({'clients': 'x'})
        self.assertEqual(cfg.clients, ['x'])

    def test_extra_keys_collected_into_kwargs(self):
        cfg = AIServiceInitData.model_validate({
            'clients': ['x'],
            'custom_param': 42,
        })
        self.assertEqual(cfg.kwargs.get('custom_param'), 42)


class TestTypedServiceInitData(unittest.TestCase):

    def test_completion_service_init_exposes_s2t_service(self):
        cfg = CompletionServiceInitData.model_validate({
            'clients': ['completion-local'],
            's2t_service': 'default',
            'custom_param': 42,
        })
        self.assertEqual(cfg.s2t_service, 'default')
        self.assertEqual(cfg.kwargs.get('custom_param'), 42)

    def test_embedding_service_init_exposes_related_service_fields(self):
        cfg = EmbeddingServiceInitData.model_validate({
            'clients': ['embedding-local'],
            'completion_service': 'advanced',
            's2t_service': 'default',
        })
        self.assertEqual(cfg.completion_service, 'advanced')
        self.assertEqual(cfg.s2t_service, 'default')

    def test_s2t_service_init_exposes_completion_service(self):
        cfg = S2TServiceInitData.model_validate({
            'completion_service': 'default',
        })
        self.assertEqual(cfg.completion_service, 'default')
        self.assertEqual(cfg.clients, [])

    def test_t2s_service_init_remains_a_typed_subclass(self):
        cfg = T2SServiceInitData.model_validate('tts-client')
        self.assertEqual(cfg.clients, ['tts-client'])

    def test_t2img_service_init_exposes_completion_service(self):
        cfg = T2ImgServiceInitData.model_validate({
            'clients': ['image-client'],
            'completion_service': 'prompt-helper',
        })
        self.assertEqual(cfg.clients, ['image-client'])
        self.assertEqual(cfg.completion_service, 'prompt-helper')


class TestAIServiceClientBinding(unittest.TestCase):

    def setUp(self):
        self._saved_global = AIServicesConfig.__Instance__  # type: ignore[attr-defined]
        self._saved_client_cache = dict(ServiceClientBase._instance_cache)

    def tearDown(self):
        AIServicesConfig.SetGlobal(self._saved_global)
        ServiceClientBase._instance_cache.clear()
        ServiceClientBase._instance_cache.update(self._saved_client_cache)

    def test_binding_without_overrides_wraps_named_client_without_local_values(self):
        cfg = AIServicesConfig.model_validate({
            'completion': {
                'clients': {
                    'named-client': {
                        'type': 'fake-config-test',
                        'model': 'baseline-model',
                    },
                },
            },
        })
        AIServicesConfig.SetGlobal(cfg)

        binding = AIServiceClientBinding.model_validate('named-client')
        service_client = binding.get_client(
            local_clients=cfg.completion.clients,
            client_scope='completion',
            service_kind='completion',
            service_key='default',
            binding_idx=0,
        )

        self.assertIsNotNone(service_client)
        self.assertIsInstance(service_client, ServiceClient)
        self.assertIs(service_client.client, ServiceClientBase.GetClient('completion:named-client'))
        self.assertIsNone(service_client.priority)
        self.assertIsNone(service_client.strategy_lvl)

    def test_binding_with_local_values_wraps_same_named_client(self):
        cfg = AIServicesConfig.model_validate({
            'completion': {
                'clients': {
                    'named-client': {
                        'type': 'fake-config-test',
                        'model': 'baseline-model',
                        'max_concurrent': 5,
                        'priority': 1.0,
                        'strategy_lvl': 0,
                    },
                },
            },
        })
        AIServicesConfig.SetGlobal(cfg)

        base_client = cfg.completion.clients['named-client'].get_client(key='completion:named-client')
        binding = AIServiceClientBinding.model_validate({
            'client': 'named-client',
            'priority': 7.5,
            'strategy_lvl': 2,
        })
        service_client = binding.get_client(
            local_clients=cfg.completion.clients,
            client_scope='completion',
            service_kind='completion',
            service_key='default',
            binding_idx=0,
        )

        self.assertIsNotNone(service_client)
        self.assertIs(service_client.client, base_client)
        self.assertEqual(service_client.priority, 7.5)
        self.assertEqual(service_client.strategy_lvl, 2)
        self.assertEqual(service_client.get_priority(), 7.5)
        self.assertEqual(base_client.priority, 1.0)
        self.assertEqual(base_client.strategy_lvl, 0)
        self.assertEqual(base_client.max_concurrent.max_concurrent, 5)

    def test_service_uses_local_priority_and_strategy_over_client_defaults(self):
        saved_instances = dict(ServiceBase.ServiceInstances)
        try:
            ServiceBase.ServiceInstances.clear()
            cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'thinkthinksyn-qwen3-omni': {
                            'type': 'fake-config-test',
                            'model': 'omni-local',
                            'priority': 9.0,
                            'strategy_lvl': 2,
                        },
                        'server9-qwen3-omni': {
                            'type': 'fake-config-test',
                            'model': 'omni-server9',
                            'priority': 8.0,
                            'strategy_lvl': 2,
                        },
                    },
                    'services': {
                        'omni': {
                            'clients': [
                                {
                                    'client': 'thinkthinksyn-qwen3-omni',
                                    'strategy_lvl': 'load_balance',
                                    'priority': 0,
                                },
                                {
                                    'client': 'server9-qwen3-omni',
                                    'strategy_lvl': 1,
                                    'priority': 1,
                                },
                            ],
                        },
                    },
                },
            })
            AIServicesConfig.SetGlobal(cfg)

            service = cfg.completion.get_service('omni')

            self.assertIsNotNone(service)
            assert service is not None
            self.assertEqual([binding.get_priority() for binding in service._clients], [0.0, 1.0])
            self.assertEqual([int(binding.get_strategy_lvl()) for binding in service._clients], [0, 1])
            self.assertEqual([client.priority for client in service.clients], [9.0, 8.0])
            self.assertEqual([client.strategy_lvl for client in service.clients], [2, 2])
        finally:
            ServiceClientBase.ClearClientCache(keys={'completion:thinkthinksyn-qwen3-omni', 'completion:server9-qwen3-omni'}, close=True)
            ServiceBase.ServiceInstances.clear()
            ServiceBase.ServiceInstances.update(saved_instances)

    def test_local_client_names_are_scoped_per_service_kind(self):
        cfg = AIServicesConfig.model_validate({
            'completion': {
                'clients': {
                    'shared': {
                        'type': 'fake-config-test',
                        'model': 'completion-model',
                    },
                },
            },
            'embedding': {
                'clients': {
                    'shared': {
                        'type': 'fake-config-test',
                        'model': 'embedding-model',
                    },
                },
            },
        })

        completion_client = cfg.completion.clients['shared'].get_client(key=cfg.completion.scoped_client_key('shared'))
        embedding_client = cfg.embedding.clients['shared'].get_client(key=cfg.embedding.scoped_client_key('shared'))

        self.assertIsNotNone(completion_client)
        self.assertIsNotNone(embedding_client)
        self.assertIsNot(completion_client, embedding_client)
        self.assertEqual(completion_client.model, 'completion-model')
        self.assertEqual(embedding_client.model, 'embedding-model')

    def test_s2t_completion_client_resolves_completion_service_reference(self):
        cfg = AIServicesConfig.model_validate({
            'completion': {
                'clients': {
                    'named-client': {
                        'type': 'fake-config-test',
                        'model': 'completion-model',
                    },
                },
                'service': {
                    'omni': {'clients': ['named-client']},
                },
            },
            's2t': {
                'clients': {
                    'omni-s2t': {
                        'type': 'completion',
                        'services': 'omni',
                    },
                },
            },
        })
        AIServicesConfig.SetGlobal(cfg)

        client = cfg.s2t.clients['omni-s2t'].get_client(key='s2t:omni-s2t', service_kind='s2t')

        self.assertIsNotNone(client)
        self.assertIsInstance(client, CompletionAsS2TClient)

    def test_s2t_completion_adapter_close_retires_nested_completion_service(self):
        cfg = AIServicesConfig.model_validate({
            'completion': {
                'clients': {
                    'named-client': {
                        'type': 'fake-config-test',
                        'model': 'completion-model',
                    },
                },
                'service': {
                    'omni': {'clients': ['named-client']},
                },
            },
            's2t': {
                'clients': {
                    'omni-s2t': {
                        'type': 'completion',
                        'services': 'omni',
                    },
                },
            },
        })
        AIServicesConfig.SetGlobal(cfg)

        client = cfg.s2t.clients['omni-s2t'].get_client(key='s2t:omni-s2t', service_kind='s2t')

        self.assertIsInstance(client, CompletionAsS2TClient)
        completion_service = client._completion_service
        client.close(reason='test close')
        self.assertTrue(getattr(client, '_closed', False))
        self.assertTrue(getattr(completion_service, '_closed', False))


# ══════════════════════════════════════════════════════════════════════════════
# Tests — AIPredefinedService
# ══════════════════════════════════════════════════════════════════════════════

class TestAIPredefinedService(unittest.TestCase):

    def setUp(self):
        # Clean service instances to avoid cross-test leakage
        self._saved_instances = dict(ServiceBase.ServiceInstances)

    def tearDown(self):
        ServiceBase.ServiceInstances.clear()
        ServiceBase.ServiceInstances.update(self._saved_instances)

    def test_service_map_holds_named_instances(self):
        data = {
            'service': {
                'default': {'clients': ['c1']},
                'advanced': {'clients': ['c2', 'c3']},
            },
        }
        cfg = _FakeConfigPredefined.model_validate(data)
        self.assertIn('default', cfg.service)
        self.assertIn('advanced', cfg.service)
        self.assertEqual(len(cfg.service['advanced'].clients), 2)

    def test_flat_service_instances_are_rejected(self):
        with self.assertRaises(ValueError):
            _FakeConfigPredefined.model_validate({
                'default': {'clients': ['c1']},
            })

    def test_get_service_returns_none_for_missing_key(self):
        cfg = _FakeConfigPredefined()
        result = cfg.get_service('nonexistent')
        self.assertIsNone(result)

    def test_get_service_returns_cached_instance(self):
        """Once a service is created, GetInstance should return the same one."""
        # Manually create and register an instance
        client = _FakeConfigClient(key='cached-client')
        svc = _FakeConfigService(client, key='mykey')

        cfg = _FakeConfigPredefined()
        # get_service should find the cached instance
        result = cfg.get_service('mykey')
        self.assertIs(result, svc)
        svc.close()

    def test_get_default_uses_all_clients_when_default_service_missing(self):
        cfg = _FakeConfigPredefined.model_validate({
            'clients': {
                'c1': {'type': 'fake-config-test', 'model': 'm1'},
                'c2': {'type': 'fake-config-test', 'model': 'm2'},
            },
        })

        svc = cfg.get_default()

        self.assertIsNotNone(svc)
        self.assertEqual([client.model for client in svc.clients], ['m1', 'm2'])
        self.assertIs(_FakeConfigService.GetInstance('default'), svc)

    def test_named_service_does_not_fall_back_to_cached_default(self):
        saved_instances = dict(ServiceBase.ServiceInstances)
        try:
            ServiceBase.ServiceInstances.clear()
            cfg = _FakeConfigPredefined.model_validate({
                'clients': {
                    'default-client': {'type': 'fake-config-test', 'model': 'default-model'},
                    'named-client': {'type': 'fake-config-test', 'model': 'named-model'},
                },
                'service': {
                    'named': {'clients': ['named-client']},
                },
            })

            default_service = cfg.get_default()
            named_service = cfg.get_service('named')

            self.assertIsNotNone(default_service)
            self.assertIsNotNone(named_service)
            self.assertIsNot(default_service, named_service)
            assert named_service is not None
            self.assertEqual([client.model for client in named_service.clients], ['named-model'])
        finally:
            ServiceBase.ServiceInstances.clear()
            ServiceBase.ServiceInstances.update(saved_instances)


# ══════════════════════════════════════════════════════════════════════════════
# Tests — ServiceBase.ServiceInstances + GetInstance
# ══════════════════════════════════════════════════════════════════════════════

class TestServiceInstances(unittest.TestCase):

    def setUp(self):
        self._saved = dict(ServiceBase.ServiceInstances)

    def tearDown(self):
        ServiceBase.ServiceInstances.clear()
        ServiceBase.ServiceInstances.update(self._saved)

    def test_key_registers_instance(self):
        client = _FakeConfigClient()
        svc = _FakeConfigService(client, key='test-reg')
        self.assertIn((_FakeConfigService, 'test-reg'), ServiceBase.ServiceInstances)
        self.assertIs(ServiceBase.ServiceInstances[(_FakeConfigService, 'test-reg')], svc)
        svc.close()

    def test_get_instance_found(self):
        client = _FakeConfigClient()
        svc = _FakeConfigService(client, key='lookup')
        result = _FakeConfigService.GetInstance('lookup')
        self.assertIs(result, svc)
        svc.close()

    def test_get_instance_not_found(self):
        result = _FakeConfigService.GetInstance('nope')
        self.assertIsNone(result)

    def test_get_instance_fallback(self):
        client = _FakeConfigClient()
        svc = _FakeConfigService(client, key='default')
        result = _FakeConfigService.GetInstance('missing', fallback='default')
        self.assertIs(result, svc)
        svc.close()

    def test_no_key_does_not_register(self):
        client = _FakeConfigClient()
        svc = _FakeConfigService(client)
        self.assertNotIn((_FakeConfigService, None), ServiceBase.ServiceInstances)
        svc.close()


# ══════════════════════════════════════════════════════════════════════════════
# Tests — AIServicesConfig singleton & env loading
# ══════════════════════════════════════════════════════════════════════════════

class TestAIServicesConfig(unittest.TestCase):

    def setUp(self):
        self._saved_instance = AIServicesConfig.__Instance__  # type: ignore[attr-defined]
        self._saved_env = os.environ.get('__AI_SERVICES_CONFIG__')
        self._saved_source_env = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
        AIServicesConfig.SetGlobal(None)
        os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)

    def tearDown(self):
        AIServicesConfig.__Instance__ = self._saved_instance  # type: ignore[attr-defined]
        if self._saved_env is not None:
            os.environ['__AI_SERVICES_CONFIG__'] = self._saved_env
        else:
            os.environ.pop('__AI_SERVICES_CONFIG__', None)
        if self._saved_source_env is not None:
            os.environ[AI_SERVICES_CONFIG_SOURCE_ENV] = self._saved_source_env
        else:
            os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)

    def test_global_returns_none_without_env(self):
        os.environ.pop('__AI_SERVICES_CONFIG__', None)
        result = AIServicesConfig.Global()
        self.assertIsNone(result)

    def test_global_loads_from_env(self):
        config_data = {
            'completion': {
                'clients': {
                    'my-client': {'type': 'fake-config-test', 'model': 'env-model'},
                },
                'service': {'default': {'clients': ['my-client']}},
            },
        }
        os.environ['__AI_SERVICES_CONFIG__'] = json.dumps(config_data)
        os.environ[AI_SERVICES_CONFIG_SOURCE_ENV] = 'config/from-env-ai-services.yaml'
        result = AIServicesConfig.Global()
        self.assertIsNotNone(result)
        self.assertIn('my-client', result.completion.clients)
        self.assertEqual(result.source_path(), Path('config/from-env-ai-services.yaml'))

    def test_set_global_then_global(self):
        cfg = AIServicesConfig()
        AIServicesConfig.SetGlobal(cfg)
        self.assertIs(AIServicesConfig.Global(), cfg)

    def test_to_serialized_env_roundtrip(self):
        config_data = {
            'completion': {
                'clients': {
                    'c1': {'type': 'fake-config-test'},
                },
            },
        }
        cfg = AIServicesConfig.model_validate(config_data)
        serialized = cfg.to_serialized_env()
        os.environ['__AI_SERVICES_CONFIG__'] = serialized
        AIServicesConfig.SetGlobal(None)
        loaded = AIServicesConfig.Global()
        self.assertIsNotNone(loaded)
        self.assertIn('c1', loaded.completion.clients)

    def test_main_process_shared_config_sync_updates_same_key_client_in_place(self):
        import core.ai as ai_runtime
        from core.server.shared import AppSharedData

        shared = AppSharedData.Get()
        saved_instances = dict(ServiceBase.ServiceInstances)
        saved_probe_version = ai_runtime._main_process_probe_config_version
        saved_snapshot = shared.get_ai_services_config()
        old_client = None
        try:
            ServiceBase.ServiceInstances.clear()
            old_cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'main-sync-client': {'type': 'fake-config-test', 'model': 'old-model'},
                    },
                    'service': {'default': {'clients': ['main-sync-client']}},
                },
            })
            AIServicesConfig.SetGlobal(old_cfg)
            old_service = old_cfg.completion.get_default()
            self.assertIsNotNone(old_service)
            assert old_service is not None
            old_client = old_service.clients[0]
            self.assertEqual(old_client.model, 'old-model')

            next_cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'main-sync-client': {'type': 'fake-config-test', 'model': 'new-model'},
                    },
                    'service': {'default': {'clients': ['main-sync-client']}},
                },
            })
            version = int(time.time() * 1000)
            shared.set_ai_services_config(next_cfg.to_serialized_env(), version=version)
            ai_runtime._main_process_probe_config_version = version - 1

            ai_runtime.sync_main_process_probe_runtime_from_shared(['completion'])
            ai_runtime.preload_configured_services_for_probe(['completion'])

            new_service = CompletionService.GetInstance('default')
            self.assertIsNotNone(new_service)
            assert new_service is not None
            self.assertIs(old_service, new_service)
            self.assertIs(old_client, new_service.clients[0])
            self.assertEqual(old_client.model, 'new-model')
            self.assertFalse(old_service._closed)
            self.assertFalse(old_client._closed)
        finally:
            ai_runtime._main_process_probe_config_version = saved_probe_version
            shared.set_ai_services_config(
                saved_snapshot.get('serialized_config'),
                version=int(saved_snapshot.get('version') or 0),
            )
            if old_client is not None:
                old_client.close(reason='test cleanup')
            ServiceClientBase.ClearClientCache(keys={'completion:main-sync-client'}, close=True)
            ServiceBase.ServiceInstances.clear()
            ServiceBase.ServiceInstances.update(saved_instances)

    def test_reconcile_updates_clients_when_referenced_kwargs_preset_changes(self):
        import core.ai as ai_runtime

        saved_instances = dict(ServiceBase.ServiceInstances)
        old_client = None
        try:
            ServiceBase.ServiceInstances.clear()
            old_cfg = AIServicesConfig.model_validate({
                'kwargs': {
                    'fake-preset': {
                        'type': 'fake-config-test',
                        'model': 'old-preset-model',
                    },
                },
                'completion': {
                    'clients': {
                        'preset-client': {'kwargs': 'fake-preset'},
                    },
                    'service': {'default': {'clients': ['preset-client']}},
                },
            })
            AIServicesConfig.SetGlobal(old_cfg)
            service = old_cfg.completion.get_default()
            self.assertIsNotNone(service)
            assert service is not None
            old_client = service.clients[0]
            self.assertEqual(old_client.model, 'old-preset-model')

            next_cfg = AIServicesConfig.model_validate({
                'kwargs': {
                    'fake-preset': {
                        'type': 'fake-config-test',
                        'model': 'new-preset-model',
                    },
                },
                'completion': {
                    'clients': {
                        'preset-client': {'kwargs': 'fake-preset'},
                    },
                    'service': {'default': {'clients': ['preset-client']}},
                },
            })

            AIServicesConfig.SetGlobal(next_cfg)
            ai_runtime.reconcile_runtime_services(old_cfg, next_cfg, ['completion'])

            updated_service = CompletionService.GetInstance('default')
            self.assertIs(service, updated_service)
            self.assertIs(old_client, service.clients[0])
            self.assertEqual(old_client.model, 'new-preset-model')
            self.assertFalse(service._closed)
            self.assertFalse(old_client._closed)
        finally:
            if old_client is not None:
                old_client.close(reason='test cleanup')
            ServiceClientBase.ClearClientCache(keys={'completion:preset-client'}, close=True)
            ServiceBase.ServiceInstances.clear()
            ServiceBase.ServiceInstances.update(saved_instances)

    def test_reconcile_removes_deleted_client_binding_without_stopping_service(self):
        import core.ai as ai_runtime

        saved_instances = dict(ServiceBase.ServiceInstances)
        old_client_1 = None
        old_client_2 = None
        try:
            ServiceBase.ServiceInstances.clear()
            old_cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'keep-client': {'type': 'fake-config-test', 'model': 'keep-model'},
                        'drop-client': {'type': 'fake-config-test', 'model': 'drop-model'},
                    },
                    'service': {'default': {'clients': ['keep-client', 'drop-client']}},
                },
            })
            AIServicesConfig.SetGlobal(old_cfg)
            service = old_cfg.completion.get_default()
            self.assertIsNotNone(service)
            assert service is not None
            old_client_1, old_client_2 = service.clients

            next_cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'keep-client': {'type': 'fake-config-test', 'model': 'keep-model'},
                    },
                    'service': {'default': {'clients': ['keep-client']}},
                },
            })

            AIServicesConfig.SetGlobal(next_cfg)
            ai_runtime.reconcile_runtime_services(old_cfg, next_cfg, ['completion'])

            updated_service = CompletionService.GetInstance('default')
            self.assertIs(service, updated_service)
            self.assertFalse(service._closed)
            self.assertEqual(service.clients, [old_client_1])
            self.assertFalse(old_client_1._closed)
            self.assertFalse(old_client_2._closed)
        finally:
            if old_client_1 is not None:
                old_client_1.close(reason='test cleanup')
            if old_client_2 is not None:
                old_client_2.close(reason='test cleanup')
            ServiceClientBase.ClearClientCache(keys={'completion:keep-client', 'completion:drop-client'}, close=True)
            ServiceBase.ServiceInstances.clear()
            ServiceBase.ServiceInstances.update(saved_instances)

    def test_reconcile_can_leave_service_with_no_clients(self):
        import core.ai as ai_runtime

        saved_instances = dict(ServiceBase.ServiceInstances)
        old_client = None
        try:
            ServiceBase.ServiceInstances.clear()
            old_cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'only-client': {'type': 'fake-config-test', 'model': 'only-model'},
                    },
                    'service': {'default': {'clients': ['only-client']}},
                },
            })
            AIServicesConfig.SetGlobal(old_cfg)
            service = old_cfg.completion.get_default()
            self.assertIsNotNone(service)
            assert service is not None
            old_client = service.clients[0]

            next_cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {},
                    'service': {'default': {'clients': []}},
                },
            })
            AIServicesConfig.SetGlobal(next_cfg)

            ai_runtime.reconcile_runtime_services(old_cfg, next_cfg, ['completion'])

            updated_service = CompletionService.GetInstance('default')
            self.assertIs(service, updated_service)
            self.assertFalse(service._closed)
            self.assertEqual(service.clients, [])
            self.assertFalse(old_client._closed)
        finally:
            if old_client is not None:
                old_client.close(reason='test cleanup')
            ServiceClientBase.ClearClientCache(keys={'completion:only-client'}, close=True)
            ServiceBase.ServiceInstances.clear()
            ServiceBase.ServiceInstances.update(saved_instances)

    def test_top_level_clients_are_rejected(self):
        with self.assertRaises(ValueError):
            AIServicesConfig.model_validate({
                'clients': {
                    'legacy-client': {'type': 'fake-config-test'},
                },
            })

    def test_services_wrapper_expands_shared_kwargs_references(self):
        cfg = AIServicesConfig.model_validate({
            'kwargs': {
                'base': {
                    'type': 'fake-config-test',
                    'model': 'shared-model',
                    'max_concurrent': '3',
                },
                'limit': {
                    'kwargs': 'base',
                    'max_tokens': '14K',
                    'priority': 0.25,
                },
                'media-limit': {
                    'max_images': '4',
                    'max_videos': 2,
                },
                'openai-compatible': {
                    'type': 'openai-liked',
                    'max_tokens': '262K',
                },
            },
            'services': {
                'completion': {
                    'clients': {
                        'merged-client': {
                            'kwargs': ['limit', 'media-limit'],
                            'model': 'local-model',
                            'temperature': 0.2,
                        },
                        'openai-alias-client': {
                            'kwargs': 'openai-compatible',
                            'model': 'alias-model',
                        },
                    },
                    'services': {
                        'default': {'clients': ['merged-client']},
                    },
                },
            },
        })

        merged_client = cfg.completion.clients['merged-client']
        self.assertEqual(merged_client.type, 'fake-config-test')
        self.assertEqual(merged_client.max_concurrent, 3)
        self.assertEqual(merged_client.max_tokens, 14000)
        self.assertEqual(merged_client.max_images, 4)
        self.assertEqual(merged_client.max_videos, 2)
        self.assertEqual(merged_client.priority, 0.25)
        self.assertEqual(merged_client.kwargs['model'], 'local-model')
        self.assertEqual(merged_client.kwargs['temperature'], 0.2)
        self.assertIn('default', cfg.completion.service)
        self.assertEqual(cfg.kwargs['openai-compatible']['type'], 'openai')
        self.assertEqual(cfg.kwargs['openai-compatible']['max_tokens'], 262000)

        alias_client = cfg.completion.clients['openai-alias-client']
        self.assertEqual(alias_client.type, 'openai')
        self.assertEqual(alias_client.max_tokens, 262000)
        self.assertEqual(alias_client.kwargs['model'], 'alias-model')

    def test_t2img_config_creates_openai_and_openrouter_clients(self):
        cfg = AIServicesConfig.model_validate({
            't2img': {
                'clients': {
                    'openai-image': {
                        'type': 'openai',
                        'apikey': 'openai-key',
                        'base_url': 'https://openai.example/v1',
                        'model': 'gpt-image-1',
                        'supported_tasks': ['generate', 'edit'],
                    },
                    'router-image': {
                        'type': 'openrouter',
                        'apikey': 'router-key',
                        'model': 'black-forest-labs/flux.2-flex',
                    },
                },
                'service': {
                    'default': {'clients': ['openai-image', 'router-image']},
                },
            },
        })

        openai_client = cfg.t2img.clients['openai-image'].get_client(key='t2img:openai-image', service_kind='t2img')
        router_client = cfg.t2img.clients['router-image'].get_client(key='t2img:router-image', service_kind='t2img')

        self.assertIsInstance(openai_client, OpenAILikedT2ImgClient)
        self.assertIsInstance(router_client, OpenRouterT2ImgClient)
        self.assertTrue(openai_client.supports_task('edit'))
        self.assertFalse(router_client.supports_task('edit'))
        self.assertIsInstance(cfg.t2img.get_default(), T2ImgService)

    def test_service_recovery_interval_accepts_probe_interval_object_and_explicit_none(self):
        cfg = AIServicesConfig.model_validate({
            't2img': {
                'clients': {
                    'openai-image': {
                        'type': 'openai',
                        'apikey': 'openai-key',
                        'base_url': 'https://openai.example/v1',
                        'model': 'gpt-image-1',
                    },
                },
                'service': {
                    'default': {
                        'clients': ['openai-image'],
                        'recovery_interval': {
                            'interval': 120,
                            'decay': 2,
                            'max_interval': 3600,
                        },
                    },
                    'disabled': {
                        'clients': ['openai-image'],
                        'recovery_interval': None,
                    },
                },
            },
        })

        disabled_service = cfg.t2img.get_service('disabled')
        default_service = cfg.t2img.get_service('default')

        self.assertIsInstance(default_service._recovery_interval, ProbeInterval)
        self.assertEqual(default_service._recovery_interval.interval, 120.0)
        self.assertEqual(default_service._recovery_interval.decay, 2.0)
        self.assertEqual(default_service._recovery_interval.max_interval, 3600.0)
        self.assertIsNone(disabled_service._recovery_interval)

    def test_shared_kwargs_reference_cycle_is_rejected(self):
        with self.assertRaises(ValueError):
            AIServicesConfig.model_validate({
                'kwargs': {
                    'a': {'kwargs': 'b'},
                    'b': {'kwargs': 'a'},
                },
                'services': {
                    'completion': {
                        'clients': {
                            'cycle-client': {'kwargs': 'a'},
                        },
                    },
                },
            })

    def test_global_auto_discovers_generic_file_first_in_direct_mode(self):
        generic_payload = {
            'completion': {
                'clients': {
                    'generic-client': {'type': 'fake-config-test', 'model': 'generic-model'},
                },
            },
        }
        dev_payload = {
            'completion': {
                'clients': {
                    'dev-client': {'type': 'fake-config-test', 'model': 'dev-model'},
                },
            },
        }

        with tempfile.TemporaryDirectory(prefix='proj_ai_cfg_') as tmp_dir:
            config_dir = Path(tmp_dir) / 'config'
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / 'ai_services.json').write_text(json.dumps(generic_payload), encoding='utf-8')
            (config_dir / 'dev_ai_services.json').write_text(json.dumps(dev_payload), encoding='utf-8')
            with (
                patch('core.ai.config.PROJECT_DIR', Path(tmp_dir)),
                patch('core.ai.config.Path.cwd', return_value=Path(tmp_dir)),
                patch.dict(os.environ, {'__MODE__': 'dev'}, clear=False),
            ):
                result = AIServicesConfig.Global()

        self.assertIsNotNone(result)
        self.assertIn('generic-client', result.completion.clients)
        self.assertNotIn('dev-client', result.completion.clients)
        self.assertEqual(result.source_path(), config_dir / 'ai_services.json')

    def test_global_prefers_mode_specific_file_in_server_runtime(self):
        generic_payload = {
            'completion': {
                'clients': {
                    'generic-client': {'type': 'fake-config-test', 'model': 'generic-model'},
                },
            },
        }
        dev_payload = {
            'completion': {
                'clients': {
                    'dev-client': {'type': 'fake-config-test', 'model': 'dev-model'},
                },
            },
        }

        with tempfile.TemporaryDirectory(prefix='proj_ai_cfg_') as tmp_dir:
            config_dir = Path(tmp_dir) / 'config'
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / 'ai_services.json').write_text(json.dumps(generic_payload), encoding='utf-8')
            (config_dir / 'dev_ai_services.json').write_text(json.dumps(dev_payload), encoding='utf-8')
            with (
                patch('core.ai.config.PROJECT_DIR', Path(tmp_dir)),
                patch('core.ai.config.Path.cwd', return_value=Path(tmp_dir)),
                patch.dict(os.environ, {'__MODE__': 'dev', '__SERVER_PROCESS_PID__': '123'}, clear=False),
            ):
                result = AIServicesConfig.Global()

        self.assertIsNotNone(result)
        self.assertIn('dev-client', result.completion.clients)
        self.assertNotIn('generic-client', result.completion.clients)
        self.assertEqual(result.source_path(), config_dir / 'dev_ai_services.json')

    def test_invalid_env_returns_none(self):
        os.environ['__AI_SERVICES_CONFIG__'] = 'not valid json {'
        result = AIServicesConfig.Global()
        self.assertIsNone(result)


# ══════════════════════════════════════════════════════════════════════════════
# Tests — Server Config.BuildArgParser / CreateConfigFromArgs
# ══════════════════════════════════════════════════════════════════════════════

class TestServerConfigAIServicesArg(unittest.TestCase):

    def setUp(self):
        self._saved_env = os.environ.get('__AI_SERVICES_CONFIG__')
        self._saved_source_env = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
        os.environ.pop('__AI_SERVICES_CONFIG__', None)
        os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)
        # Prevent auto-discovery of default config files
        self._saved_config_instance = None
        try:
            from core.server.data_types.config import Config
            self._saved_config_instance = Config.__Instance__  # type: ignore[attr-defined]
        except Exception:
            pass

    def tearDown(self):
        if self._saved_env is not None:
            os.environ['__AI_SERVICES_CONFIG__'] = self._saved_env
        else:
            os.environ.pop('__AI_SERVICES_CONFIG__', None)
        if self._saved_source_env is not None:
            os.environ[AI_SERVICES_CONFIG_SOURCE_ENV] = self._saved_source_env
        else:
            os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)
        try:
            from core.server.data_types.config import Config
            if self._saved_config_instance is not None:
                Config.__Instance__ = self._saved_config_instance  # type: ignore[attr-defined]
        except Exception:
            pass

    def test_arg_parser_has_ai_services_config(self):
        from core.server.data_types.config import Config
        parser = Config.BuildArgParser()
        # Check that --ai-services-config is a recognized argument
        actions = {a.option_strings[0]: a for a in parser._actions if a.option_strings}
        self.assertIn('--ai-services-config', actions)

    def test_create_config_from_args_writes_env(self):
        from core.server.data_types.config import Config

        config_data = {
            'completion': {
                'clients': {'test-c': {'type': 'fake-config-test'}},
                'service': {'default': {'clients': ['test-c']}},
            },
        }
        json_str = json.dumps(config_data)

        parser = Config.BuildArgParser()
        args = parser.parse_args(['--ai-services-config', json_str])
        Config.CreateConfigFromArgs(args, set_global=False)

        # __AI_SERVICES_CONFIG__ should now be set in env
        env_val = os.environ.get('__AI_SERVICES_CONFIG__')
        self.assertIsNotNone(env_val)
        loaded = json.loads(env_val)
        self.assertIn('completion', loaded)
        self.assertIn('clients', loaded['completion'])
        self.assertIn('test-c', loaded['completion']['clients'])

    def test_create_config_from_args_file_path(self):
        """--ai-services-config with a file path should load and write env."""
        import tempfile
        from core.server.data_types.config import Config

        config_data = {
            'completion': {
                'clients': {'file-client': {'type': 'fake-config-test'}},
            },
        }
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump(config_data, f)
            tmp_path = f.name

        try:
            parser = Config.BuildArgParser()
            args = parser.parse_args(['--ai-services-config', tmp_path])
            Config.CreateConfigFromArgs(args, set_global=False)

            env_val = os.environ.get('__AI_SERVICES_CONFIG__')
            self.assertIsNotNone(env_val)
            loaded = json.loads(env_val)
            self.assertIn('file-client', loaded['completion']['clients'])
            self.assertEqual(os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV), tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_create_config_invalid_ai_config_warns(self):
        """Invalid --ai-services-config should warn but not crash."""
        from core.server.data_types.config import Config

        parser = Config.BuildArgParser()
        args = parser.parse_args(['--ai-services-config', 'not-valid-json{{{'])
        # Should not raise
        Config.CreateConfigFromArgs(args, set_global=False)
        # Env should NOT be set
        env_val = os.environ.get('__AI_SERVICES_CONFIG__')
        self.assertFalse(env_val)  # None or empty string


# ══════════════════════════════════════════════════════════════════════════════
# Tests — End-to-end: config → env → Global() → Default()
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigToDefaultE2E(unittest.TestCase):
    """Verify the full flow: config writes to env, Global() reads it, Default() uses it."""

    def setUp(self):
        self._saved_env = os.environ.get('__AI_SERVICES_CONFIG__')
        self._saved_source_env = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
        self._saved_instance = AIServicesConfig.__Instance__  # type: ignore[attr-defined]
        self._saved_service_instances = dict(ServiceBase.ServiceInstances)
        AIServicesConfig.SetGlobal(None)
        os.environ.pop('__AI_SERVICES_CONFIG__', None)
        os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)

    def tearDown(self):
        AIServicesConfig.__Instance__ = self._saved_instance  # type: ignore[attr-defined]
        ServiceBase.ServiceInstances.clear()
        ServiceBase.ServiceInstances.update(self._saved_service_instances)
        if self._saved_env is not None:
            os.environ['__AI_SERVICES_CONFIG__'] = self._saved_env
        else:
            os.environ.pop('__AI_SERVICES_CONFIG__', None)
        if self._saved_source_env is not None:
            os.environ[AI_SERVICES_CONFIG_SOURCE_ENV] = self._saved_source_env
        else:
            os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)

    def test_env_written_before_global_read(self):
        """Simulate server startup: write env, then Global() should load."""
        config_data = {
            'completion': {
                'clients': {
                    'fc1': {'type': 'fake-config-test', 'model': 'e2e-model'},
                },
                'service': {'default': {'clients': ['fc1']}},
            },
        }
        # Simulate what CreateConfigFromArgs does
        cfg = AIServicesConfig.model_validate(config_data)
        os.environ['__AI_SERVICES_CONFIG__'] = cfg.to_serialized_env()

        # Now Global() should find it
        loaded = AIServicesConfig.Global()
        self.assertIsNotNone(loaded)
        self.assertIn('fc1', loaded.completion.clients)
        self.assertEqual(loaded.completion.clients['fc1'].kwargs.get('model'), 'e2e-model')


class TestDefaultEnvFallbacks(unittest.TestCase):
    _ENV_KEYS = (
        'OPENAI_APIKEY',
        'OPENAI_API_KEY',
        'OPENROUTER_APIKEY',
        'OPENROUTER_API_KEY',
        'TTS_APIKEY',
        'TTS_API_KEY',
    )

    def setUp(self):
        self._saved_env = {key: os.environ.get(key) for key in self._ENV_KEYS}
        self._saved_global = AIServicesConfig.__Instance__  # type: ignore[attr-defined]
        self._saved_service_instances = dict(ServiceBase.ServiceInstances)
        AIServicesConfig.SetGlobal(None)
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        AIServicesConfig.__Instance__ = self._saved_global  # type: ignore[attr-defined]
        ServiceBase.ServiceInstances.clear()
        ServiceBase.ServiceInstances.update(self._saved_service_instances)
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_embedding_default_uses_openai_env_client(self):
        os.environ['OPENAI_APIKEY'] = 'openai-key'

        with patch.object(AIServicesConfig, 'Global', return_value=None), \
             patch('core.ai.embedding.thinkthinksyn_client', side_effect=RuntimeError('no tts')), \
             patch.object(ServiceBase, '_start_init_probe', lambda self: None):
            service = EmbeddingService.Default()

        self.assertTrue(any(isinstance(client, OpenAILikedEmbeddingClient) for client in service.clients))
        service.close()

    def test_s2t_default_uses_openai_env_client(self):
        os.environ['OPENAI_APIKEY'] = 'openai-key'

        with patch.object(AIServicesConfig, 'Global', return_value=None), \
             patch('core.ai.s2t.CompletionService.Default', side_effect=RuntimeError('no completion')), \
             patch.object(ServiceBase, '_start_init_probe', lambda self: None):
            service = S2TService.Default()

        self.assertTrue(any(isinstance(client, OpenAILikedS2TClient) for client in service.clients))
        service.close()

    def test_t2s_default_uses_openai_env_client(self):
        os.environ['OPENAI_APIKEY'] = 'openai-key'

        with patch.object(AIServicesConfig, 'Global', return_value=None), \
             patch('core.ai.t2s.thinkthinksyn_client', side_effect=RuntimeError('no tts')), \
             patch.object(ServiceBase, '_start_init_probe', lambda self: None):
            service = T2SService.Default()

        self.assertTrue(any(isinstance(client, OpenAILikedT2SClient) for client in service.clients))
        service.close()


class TestCustomAIServiceClients(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self._saved_global = AIServicesConfig.__Instance__  # type: ignore[attr-defined]
        self._saved_client_cache = dict(ServiceClientBase._instance_cache)
        self._saved_service_instances = dict(ServiceBase.ServiceInstances)
        AIServicesConfig.SetGlobal(None)

    def tearDown(self):
        AIServicesConfig.__Instance__ = self._saved_global  # type: ignore[attr-defined]
        ServiceClientBase._instance_cache.clear()
        ServiceClientBase._instance_cache.update(self._saved_client_cache)
        ServiceBase.ServiceInstances.clear()
        ServiceBase.ServiceInstances.update(self._saved_service_instances)

    async def test_custom_clients_load_and_run_from_config(self):
        with tempfile.TemporaryDirectory(prefix='custom_ai_adapter_') as tmp_dir:
            tmp_path = Path(tmp_dir)
            completion_url = _write_adapter_script(
                tmp_path / 'completion_adapter.py',
                '''
                from typing import Any

                class APlainDict(dict):
                    pass

                class SimpleCompletionAdapter:
                    def __init__(self, prefix: str, max_tokens: int, max_images: int, max_audios: int, max_videos: int):
                        self.prefix = prefix
                        self.max_tokens = max_tokens
                        self.max_images = max_images
                        self.max_audios = max_audios
                        self.max_videos = max_videos

                    async def stream_complete(self, **kwargs: Any):
                        yield {'data': f'{self.prefix}:{len(kwargs.get("messages", []))}', 'type': 'text'}
                ''',
            )
            embedding_url = _write_adapter_script(
                tmp_path / 'embedding_adapter.py',
                '''
                from typing import Any, Sequence

                class SimpleEmbeddingAdapter:
                    def __init__(self, dims: int, support_image: bool, support_audio: bool, support_video: bool, max_tokens: int):
                        self.dims = dims
                        self.support_image = support_image
                        self.support_audio = support_audio
                        self.support_video = support_video
                        self.max_tokens = max_tokens

                    async def embedding(self, inputs: Sequence[object], **kwargs: Any) -> list[list[float]]:
                        return [[float(index + offset) for offset in range(self.dims)] for index, _ in enumerate(inputs)]
                ''',
            )
            s2t_url = _write_adapter_script(
                tmp_path / 's2t_adapter.py',
                '''
                from typing import Any

                class SimpleS2TAdapter:
                    def __init__(self, response_text: str):
                        self.response_text = response_text

                    async def s2t(self, audio: object, **kwargs: Any) -> str:
                        return self.response_text
                ''',
            )
            t2s_url = _write_adapter_script(
                tmp_path / 't2s_adapter.py',
                '''
                import io
                import wave
                from typing import Any
                from core.utils.data_structs import Audio

                class SimpleT2SAdapter:
                    def __init__(self, payload: str):
                        self.payload = payload

                    async def t2s(self, text: str, **kwargs: Any) -> Audio:
                        buffer = io.BytesIO()
                        with wave.open(buffer, 'wb') as wav_file:
                            wav_file.setnchannels(1)
                            wav_file.setsampwidth(2)
                            wav_file.setframerate(16000)
                            wav_file.writeframes((self.payload.encode('utf-8')[:8] or b'\\x00') * 320)
                        return Audio(buffer.getvalue())
                ''',
            )

            cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'custom-completion': {
                            'type': 'custom',
                            'adapter': completion_url,
                            'prefix': 'custom-ok',
                            'max_tokens': 2048,
                            'max_images': 2,
                            'max_audios': 3,
                            'max_videos': 4,
                        },
                    },
                    'service': {'default': {'clients': ['custom-completion']}},
                },
                'embedding': {
                    'clients': {
                        'custom-embedding': {
                            'type': 'custom',
                            'adapter': embedding_url,
                            'dims': 3,
                            'support_image': True,
                            'support_audio': False,
                            'support_video': False,
                            'max_tokens': 512,
                        },
                    },
                    'service': {'default': {'clients': ['custom-embedding']}},
                },
                's2t': {
                    'clients': {
                        'custom-s2t': {
                            'type': 'custom',
                            'adapter': s2t_url,
                            'response_text': 'adapter transcript',
                        },
                    },
                    'service': {'default': {'clients': ['custom-s2t']}},
                },
                't2s': {
                    'clients': {
                        'custom-t2s': {
                            'type': 'custom',
                            'adapter': t2s_url,
                            'payload': 'voice-bytes',
                        },
                    },
                    'service': {'default': {'clients': ['custom-t2s']}},
                },
            })

            completion_client = cfg.completion.clients['custom-completion'].get_client(
                key='completion:custom-completion',
                service_kind='completion',
            )
            embedding_client = cfg.embedding.clients['custom-embedding'].get_client(
                key='embedding:custom-embedding',
                service_kind='embedding',
            )
            s2t_client = cfg.s2t.clients['custom-s2t'].get_client(
                key='s2t:custom-s2t',
                service_kind='s2t',
            )
            t2s_client = cfg.t2s.clients['custom-t2s'].get_client(
                key='t2s:custom-t2s',
                service_kind='t2s',
            )

            self.assertIsInstance(completion_client, CompletionClient)
            self.assertIsInstance(embedding_client, EmbeddingClient)
            self.assertIsInstance(s2t_client, S2TClient)
            self.assertIsInstance(t2s_client, T2SClient)
            self.assertEqual(completion_client.max_images, 2)
            self.assertTrue(embedding_client.support_image)

            completion_output = await completion_client.complete(__skip_log__=True, messages=[{'role': 'user', 'content': 'hello'}])
            embedding_output = await embedding_client.embedding(['a', 'b'], __skip_log__=True)
            s2t_output = await s2t_client.s2t(Audio(b'ignored-audio'), __skip_log__=True)
            t2s_output = await t2s_client.t2s('hello', __skip_log__=True)

            self.assertEqual(completion_output, 'custom-ok:1')
            self.assertEqual(embedding_output, [[0.0, 1.0, 2.0], [1.0, 2.0, 3.0]])
            self.assertEqual(s2t_output, 'adapter transcript')
            self.assertIsInstance(t2s_output, Audio)
            self.assertGreater(len(t2s_output.to_bytes()), 0)

    async def test_custom_completion_adapter_raises_when_protocol_missing(self):
        with tempfile.TemporaryDirectory(prefix='custom_ai_adapter_bad_') as tmp_dir:
            bad_url = _write_adapter_script(
                Path(tmp_dir) / 'bad_adapter.py',
                '''
                class NotACompletionAdapter:
                    def __init__(self, value: str):
                        self.value = value
                ''',
            )

            cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'bad-client': {
                            'type': 'custom',
                            'adapter': bad_url,
                            'value': 'nope',
                        },
                    },
                },
            })

            self.assertIsNone(cfg.completion.clients['bad-client'].get_client(service_kind='completion'))

    async def test_custom_client_init_does_not_forward_implicit_config_defaults(self):
        with tempfile.TemporaryDirectory(prefix='custom_ai_adapter_defaults_') as tmp_dir:
            adapter = _write_adapter_script(
                Path(tmp_dir) / 'embedding_adapter.py',
                '''
                from typing import Sequence

                class MinimalEmbeddingAdapter:
                    def __init__(self, dims: int):
                        self.dims = dims
                        self.max_tokens = None
                        self.support_image = False
                        self.support_audio = False
                        self.support_video = False

                    async def embedding(self, inputs: Sequence[object], **kwargs: object) -> list[list[float]]:
                        return [[float(index)] * self.dims for index, _ in enumerate(inputs)]
                ''',
            )

            cfg = AIServicesConfig.model_validate({
                'embedding': {
                    'clients': {
                        'minimal-custom': {
                            'type': 'custom',
                            'adapter': adapter,
                            'dims': 2,
                        },
                    },
                },
            })

            client = cfg.embedding.clients['minimal-custom'].get_client(service_kind='embedding')
            self.assertIsInstance(client, EmbeddingClient)
            self.assertEqual(await client.embedding(['a', 'b'], __skip_log__=True), [[0.0, 0.0], [1.0, 1.0]])

    async def test_custom_adapter_instances_only_need_required_methods(self):
        class MinimalCompletionAdapter:
            async def stream_complete(self, **kwargs: object):
                yield {'data': 'minimal completion', 'type': 'text'}

        class MinimalEmbeddingAdapter:
            async def embedding(self, inputs: list[object], **kwargs: object) -> list[list[float]]:
                return [[float(index)] for index, _ in enumerate(inputs)]

        class MinimalS2TAdapter:
            async def s2t(self, audio: object, **kwargs: object) -> str:
                return 'minimal transcript'

        class MinimalT2SAdapter:
            async def t2s(self, text: str, **kwargs: object) -> Audio:
                return Audio(b'minimal audio')

        completion_client = CustomCompletionClient(adapter=MinimalCompletionAdapter())
        embedding_client = CustomEmbeddingClient(adapter=MinimalEmbeddingAdapter())
        s2t_client = CustomS2TClient(adapter=MinimalS2TAdapter())
        t2s_client = CustomT2SClient(adapter=MinimalT2SAdapter())

        self.assertEqual(
            await completion_client.complete(__skip_log__=True, messages=[{'role': 'user', 'content': 'hello'}]),
            'minimal completion',
        )
        self.assertEqual(await embedding_client.embedding(['a', 'b'], __skip_log__=True), [[0.0], [1.0]])
        self.assertEqual(await s2t_client.s2t(Audio(b'ignored-audio'), __skip_log__=True), 'minimal transcript')
        self.assertIsInstance(await t2s_client.t2s('hello', __skip_log__=True), Audio)

    async def test_custom_openai_liked_adapter_runs_against_local_openai_stub(self):
        app = web.Application()

        async def _completion_handler(request: web.Request) -> web.StreamResponse:
            payload = await request.json()
            if payload.get('stream'):
                response = web.StreamResponse(
                    status=200,
                    headers={'Content-Type': 'text/event-stream'},
                )
                await response.prepare(request)
                await response.write(b'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n')
                await response.write(b'data: {"choices":[{"delta":{"content":"stream"}}]}\n\n')
                await response.write(b'data: [DONE]\n\n')
                await response.write_eof()
                return response
            return web.json_response({
                'choices': [{'message': {'content': 'hello world'}}],
                'usage': {'prompt_tokens': 4, 'completion_tokens': 2, 'total_tokens': 6},
            })

        app.router.add_post('/chat/completions', _completion_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        sockets = getattr(site._server, 'sockets', [])
        port = sockets[0].getsockname()[1]
        base_url = f'http://127.0.0.1:{port}'

        try:
            with tempfile.TemporaryDirectory(prefix='custom_openai_adapter_') as tmp_dir:
                adapter = _write_adapter_script(
                    Path(tmp_dir) / 'openai_adapter.py',
                    '''
                    from typing import Any
                    from core.ai.completion import OpenAILikedCompletionClient

                    class LocalOpenAICompletionAdapter:
                        def __init__(self, apikey: str, base_url: str, model: str, max_tokens: int = 4096, max_images: int = 0, max_audios: int = 0, max_videos: int = 0):
                            self._client = OpenAILikedCompletionClient(
                                apikey=apikey,
                                base_url=base_url,
                                model=model,
                                max_tokens=max_tokens,
                                max_images=max_images,
                                max_audios=max_audios,
                                max_videos=max_videos,
                            )
                            self.max_tokens = self._client.max_tokens
                            self.max_images = self._client.max_images
                            self.max_audios = self._client.max_audios
                            self.max_videos = self._client.max_videos

                        async def complete(self, **kwargs: Any) -> str:
                            return await self._client.complete(**kwargs)

                        async def stream_complete(self, **kwargs: Any):
                            async for chunk in self._client.stream_complete(**kwargs):
                                yield chunk

                        def close(self) -> None:
                            self._client.close()
                    ''',
                )

                cfg = AIServicesConfig.model_validate({
                    'completion': {
                        'clients': {
                            'openai-like-custom': {
                                'type': 'custom',
                                'adapter': adapter,
                                'apikey': 'local-test-key',
                                'base_url': base_url,
                                'model': 'fake-openai-model',
                                'max_tokens': 1024,
                                'max_images': 1,
                            },
                        },
                        'service': {'default': {'clients': ['openai-like-custom']}},
                    },
                })

                client = cfg.completion.clients['openai-like-custom'].get_client(service_kind='completion')
                self.assertIsInstance(client, CompletionClient)

                text = await client.complete(__skip_log__=True, messages=[{'role': 'user', 'content': 'hello'}])
                chunks = [chunk async for chunk in client.stream_complete(__skip_log__=True, messages=[{'role': 'user', 'content': 'hello'}])]

                self.assertEqual(text, 'hello world')
                self.assertEqual(''.join(chunk['data'] for chunk in chunks), 'hello stream')
        finally:
            await runner.cleanup()

    async def test_custom_completion_service_json_complete_works(self):
        class _Resp(BaseModel):
            text: str

        with tempfile.TemporaryDirectory(prefix='custom_completion_service_') as tmp_dir:
            adapter = _write_adapter_script(
                Path(tmp_dir) / 'json_completion_adapter.py',
                '''
                from typing import Any

                class JsonChunkCompletionAdapter:
                    def __init__(self, max_tokens: int = 4096, max_images: int = 0, max_audios: int = 0, max_videos: int = 0):
                        self.max_tokens = max_tokens
                        self.max_images = max_images
                        self.max_audios = max_audios
                        self.max_videos = max_videos

                    async def stream_complete(self, **kwargs: Any):
                        yield {'data': '{"text":', 'type': 'text'}
                        yield {'data': '"ok"}', 'type': 'text'}
                ''',
            )

            cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'custom-json': {
                            'type': 'custom',
                            'adapter': adapter,
                            'max_tokens': 4096,
                        },
                    },
                    'service': {'default': {'clients': ['custom-json']}},
                },
            })

            service = cfg.completion.get_default()
            self.assertIsInstance(service, CompletionService)
            try:
                result = await service.json_complete(
                    'Return text ok.',
                    return_type=_Resp,
                    stream=True,
                    __skip_log__=True,
                )
                self.assertEqual(result.text, 'ok')
            finally:
                service.close()

    async def test_custom_completion_service_json_complete_falls_back_when_adapter_disables_support_json(self):
        class _Resp(BaseModel):
            text: str

        with tempfile.TemporaryDirectory(prefix='custom_completion_service_') as tmp_dir:
            adapter = _write_adapter_script(
                Path(tmp_dir) / 'soft_json_completion_adapter.py',
                '''from typing import Any

class SoftJsonCompletionAdapter:
    def __init__(self, max_tokens: int = 4096, max_images: int = 0, max_audios: int = 0, max_videos: int = 0):
        self.max_tokens = max_tokens
        self.max_images = max_images
        self.max_audios = max_audios
        self.max_videos = max_videos
        self.support_json = False

    async def stream_complete(self, **kwargs: Any):
        if 'json_schema' in kwargs:
            raise AssertionError('json_schema should not be forwarded when support_json=False')
        messages = kwargs.get('messages') or []
        last_message = messages[-1] if messages else {}
        content = last_message.get('content', '') if isinstance(last_message, dict) else str(last_message)
        if isinstance(content, list):
            content = ''.join(part for part in content if isinstance(part, str))
        if '```json' not in str(content):
            raise AssertionError('json fenced output instruction is required for support_json=False')
        yield {'data': '```json\\n{"text":"ok"}\\n```', 'type': 'text'}
''',
            )

            cfg = AIServicesConfig.model_validate({
                'completion': {
                    'clients': {
                        'custom-soft-json': {
                            'type': 'custom',
                            'adapter': adapter,
                            'max_tokens': 4096,
                        },
                    },
                    'service': {'default': {'clients': ['custom-soft-json']}},
                },
            })

            service = cfg.completion.get_default()
            self.assertIsInstance(service, CompletionService)
            try:
                result = await service.json_complete(
                    'Return text ok.',
                    return_type=_Resp,
                    stream=True,
                    __skip_log__=True,
                )
                self.assertEqual(result.text, 'ok')
            finally:
                service.close()

    async def test_custom_embedding_service_rerank_works(self):
        with tempfile.TemporaryDirectory(prefix='custom_embedding_service_') as tmp_dir:
            adapter = _write_adapter_script(
                Path(tmp_dir) / 'semantic_embedding_adapter.py',
                '''
                from typing import Any, Sequence

                class SemanticEmbeddingAdapter:
                    def __init__(self, max_tokens: int = 2048, support_image: bool = False, support_audio: bool = False, support_video: bool = False):
                        self.max_tokens = max_tokens
                        self.support_image = support_image
                        self.support_audio = support_audio
                        self.support_video = support_video

                    async def embedding(self, inputs: Sequence[object], **kwargs: Any) -> list[list[float]]:
                        vectors: list[list[float]] = []
                        for item in inputs:
                            text = str(item).casefold()
                            if 'apple' in text:
                                vectors.append([1.0, 0.0])
                            elif 'banana' in text:
                                vectors.append([0.0, 1.0])
                            else:
                                vectors.append([0.5, 0.5])
                        return vectors
                ''',
            )

            cfg = AIServicesConfig.model_validate({
                'embedding': {
                    'clients': {
                        'custom-rerank': {
                            'type': 'custom',
                            'adapter': adapter,
                            'max_tokens': 2048,
                            'support_image': False,
                            'support_audio': False,
                            'support_video': False,
                        },
                    },
                    'service': {'default': {'clients': ['custom-rerank']}},
                },
            })

            service = cfg.embedding.get_default()
            self.assertIsInstance(service, EmbeddingService)
            try:
                result = await service.rerank(
                    'apple',
                    ['banana split', 'apple tart', 'grape'],
                    __skip_log__=True,
                )
                self.assertEqual([item.candidate for item in result], ['apple tart', 'grape', 'banana split'])
                self.assertGreater(result[0].score, result[-1].score)
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
