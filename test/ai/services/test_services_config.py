# -*- coding: utf-8 -*-
"""Tests for AI services configuration system.

Covers:
  - AIServiceClientInitData extra-key collection and client instantiation
  - AIServiceInitData normalization (bare str / list / dict)
  - AIPredefinedService extras collection & get_service
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
import unittest
from unittest.mock import patch
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SERVER_PACKAGE = 'data_types.config'
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.ai.base import (
    ServiceBase,
    ServiceClient,
    ServiceClientBase,
)
from core.ai.config import (
    AIServiceClientInitData,
    AIServiceClientBinding,
    AIServiceInitData,
    CompletionServiceInitData,
    EmbeddingServiceInitData,
    S2TServiceInitData,
    T2SServiceInitData,
    AIPredefinedService,
    PredefinedCompletionService,
    PredefinedEmbeddingService,
    PredefinedS2TService,
    PredefinedT2SService,
    AIServicesConfig,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fake service / client classes for isolated testing
# ══════════════════════════════════════════════════════════════════════════════

class _FakeConfigClient(ServiceClientBase, type='fake-config-test'):
    """A minimal client whose type is registered for config lookup."""

    def __init__(self, *, key: str | None = None, model: str = 'test-model', **kw):
        super().__init__(key=key, **kw)
        self.model = model

    @classmethod
    def TestingInput(cls):
        return None

    async def probe_min_health(self) -> bool:
        return True


class _FakeConfigService(ServiceBase):
    """A minimal service for testing config-driven creation."""

    def __init__(self, *clients: _FakeConfigClient, **kwargs):
        super().__init__(*clients, fail_cooldown=1.0, **kwargs)

    @classmethod
    def Default(cls) -> '_FakeConfigService':
        return cls(_FakeConfigClient())


class _FakeConfigPredefined(AIPredefinedService['_FakeConfigService']):
    def _resolve_service_cls(self):
        return _FakeConfigService


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


class TestAIServiceClientBinding(unittest.TestCase):

    def setUp(self):
        self._saved_global = AIServicesConfig.Global()
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

    def test_extras_auto_collected_from_unknown_keys(self):
        data = {
            'default': {'clients': ['c1']},
            'advanced': {'clients': ['c2', 'c3']},
        }
        cfg = _FakeConfigPredefined.model_validate(data)
        self.assertIsNotNone(cfg.default)
        self.assertIn('advanced', cfg.extras)
        self.assertEqual(len(cfg.extras['advanced'].clients), 2)

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
        AIServicesConfig.SetGlobal(None)

    def tearDown(self):
        AIServicesConfig.__Instance__ = self._saved_instance  # type: ignore[attr-defined]
        if self._saved_env is not None:
            os.environ['__AI_SERVICES_CONFIG__'] = self._saved_env
        else:
            os.environ.pop('__AI_SERVICES_CONFIG__', None)

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
                'default': {'clients': ['my-client']},
            },
        }
        os.environ['__AI_SERVICES_CONFIG__'] = json.dumps(config_data)
        result = AIServicesConfig.Global()
        self.assertIsNotNone(result)
        self.assertIn('my-client', result.completion.clients)

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

    def test_top_level_clients_are_rejected(self):
        with self.assertRaises(ValueError):
            AIServicesConfig.model_validate({
                'clients': {
                    'legacy-client': {'type': 'fake-config-test'},
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
        os.environ.pop('__AI_SERVICES_CONFIG__', None)
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
                'default': {'clients': ['test-c']},
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
        self._saved_instance = AIServicesConfig.__Instance__  # type: ignore[attr-defined]
        self._saved_service_instances = dict(ServiceBase.ServiceInstances)
        AIServicesConfig.SetGlobal(None)
        os.environ.pop('__AI_SERVICES_CONFIG__', None)

    def tearDown(self):
        AIServicesConfig.__Instance__ = self._saved_instance  # type: ignore[attr-defined]
        ServiceBase.ServiceInstances.clear()
        ServiceBase.ServiceInstances.update(self._saved_service_instances)
        if self._saved_env is not None:
            os.environ['__AI_SERVICES_CONFIG__'] = self._saved_env
        else:
            os.environ.pop('__AI_SERVICES_CONFIG__', None)

    def test_env_written_before_global_read(self):
        """Simulate server startup: write env, then Global() should load."""
        config_data = {
            'completion': {
                'clients': {
                    'fc1': {'type': 'fake-config-test', 'model': 'e2e-model'},
                },
                'default': {'clients': ['fc1']},
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


if __name__ == '__main__':
    unittest.main()
