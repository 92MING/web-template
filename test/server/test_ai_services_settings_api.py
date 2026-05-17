# -*- coding: utf-8 -*-

import json
import os
import unittest.mock as unittest_mock

from pathlib import Path

from _test_helpers import _StorageTestBase, _restore_config_global


class _AIServicesPanelTestBase(_StorageTestBase):
    _previous_config: object | None = None

    @classmethod
    def _register_routes(cls, app):
        from core.server.routes.ai_services.panel import register_ai_services_panel_routes

        register_ai_services_panel_routes(app)

    @classmethod
    def setUpClass(cls):
        from core.server.data_types.config import Config, LogConfig, ServerConfig

        cls._previous_config = Config.__Instance__
        Config.SetConfig(
            Config(
                server_config=ServerConfig(host='127.0.0.1', port=18999, expose_ai_service=True),
                log_config=LogConfig(log_method=['db']),
            )
        )
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        _restore_config_global(cls._previous_config)
        super().tearDownClass()


class TestAIServicesSettingsAPI(_AIServicesPanelTestBase):
    async def test_write_ai_services_config_file_preserves_source_json_path(self):
        from core.ai.config import AI_SERVICES_CONFIG_SOURCE_ENV, AIServicesConfig
        from core.server.routes.ai_services import panel as panel_routes

        saved_source_env = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
        config_path = Path(self.__class__._tmp_dir_obj.name) / 'ai_services.test.json'
        config_path.write_text(
            json.dumps({'completion': {'clients': {'old': {'type': 'fake-config-test'}}}}),
            encoding='utf-8',
        )
        source_cfg = AIServicesConfig.Load(config_path)
        next_cfg = AIServicesConfig.model_validate({
            'completion': {
                'clients': {
                    'json-client': {'type': 'fake-config-test', 'model': 'json-model'},
                },
            },
        })
        try:
            written_path = panel_routes._write_ai_services_config_file(next_cfg, source_cfg=source_cfg)
            self.assertEqual(written_path, config_path)
            persisted = json.loads(config_path.read_text(encoding='utf-8'))
            self.assertIn('json-client', persisted['completion']['clients'])
            self.assertEqual(persisted['completion']['clients']['json-client']['kwargs']['model'], 'json-model')
        finally:
            if saved_source_env is not None:
                os.environ[AI_SERVICES_CONFIG_SOURCE_ENV] = saved_source_env
            else:
                os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)

    async def test_write_ai_services_config_file_preserves_source_toml_path(self):
        from core.ai.config import AI_SERVICES_CONFIG_SOURCE_ENV, AIServicesConfig
        from core.server.routes.ai_services import panel as panel_routes

        saved_source_env = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
        config_path = Path(self.__class__._tmp_dir_obj.name) / 'ai_services.test.toml'
        config_path.write_text(
            '[completion.clients.old]\n'
            'type = "fake-config-test"\n',
            encoding='utf-8',
        )
        source_cfg = AIServicesConfig.Load(config_path)
        next_cfg = AIServicesConfig.model_validate({
            'completion': {
                'clients': {
                    'toml-client': {'type': 'fake-config-test', 'model': 'toml-model'},
                },
                'service': {
                    'default': {'clients': ['toml-client']},
                },
            },
        })
        try:
            written_path = panel_routes._write_ai_services_config_file(next_cfg, source_cfg=source_cfg)
            self.assertEqual(written_path, config_path)
            loaded = AIServicesConfig.Load(config_path)
            self.assertIn('toml-client', loaded.completion.clients)
            self.assertEqual(loaded.completion.clients['toml-client'].kwargs['model'], 'toml-model')
            self.assertEqual(loaded.completion.service['default'].clients, ['toml-client'])
        finally:
            if saved_source_env is not None:
                os.environ[AI_SERVICES_CONFIG_SOURCE_ENV] = saved_source_env
            else:
                os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)

    async def test_write_ai_services_config_file_preserves_yaml_comments(self):
        from core.ai.config import AI_SERVICES_CONFIG_SOURCE_ENV, AIServicesConfig
        from core.server.routes.ai_services import panel as panel_routes

        saved_source_env = os.environ.get(AI_SERVICES_CONFIG_SOURCE_ENV)
        config_path = Path(self.__class__._tmp_dir_obj.name) / 'ai_services.test.yaml'
        config_path.write_text(
            '# top comment\n'
            'completion:\n'
            '  # clients comment\n'
            '  clients:\n'
            '    old:\n'
            '      type: fake-config-test\n',
            encoding='utf-8',
        )
        source_cfg = AIServicesConfig.Load(config_path)
        next_cfg = AIServicesConfig.model_validate({
            'completion': {
                'clients': {
                    'yaml-client': {'type': 'fake-config-test', 'model': 'yaml-model'},
                },
            },
        })
        try:
            written_path = panel_routes._write_ai_services_config_file(next_cfg, source_cfg=source_cfg)
            self.assertEqual(written_path, config_path)
            text = config_path.read_text(encoding='utf-8')
            self.assertIn('# top comment', text)
            self.assertIn('# clients comment', text)
            self.assertIn('yaml-client:', text)
        finally:
            if saved_source_env is not None:
                os.environ[AI_SERVICES_CONFIG_SOURCE_ENV] = saved_source_env
            else:
                os.environ.pop(AI_SERVICES_CONFIG_SOURCE_ENV, None)

    async def test_settings_payload_exposes_client_types_by_kind(self):
        from core.server.routes.ai_services import panel as panel_routes

        with unittest_mock.patch.object(
            panel_routes,
            'get_predefined_service_kinds',
            return_value=['completion', 'embedding', 's2t', 't2s'],
        ):
            settings_resp = await self._client.get('/_internal/admin/ai-services/settings')

        self.assertEqual(settings_resp.status_code, 200)
        settings_data = settings_resp.json()
        completion_types = settings_data['client_types_by_kind']['completion']
        embedding_types = settings_data['client_types_by_kind']['embedding']
        s2t_types = settings_data['client_types_by_kind']['s2t']
        t2s_types = settings_data['client_types_by_kind']['t2s']

        self.assertTrue({'coding-agent', 'custom', 'openai', 'openrouter', 'thinkthinksyn'}.issubset(set(completion_types)))
        self.assertTrue({'custom', 'openai', 'openrouter', 'thinkthinksyn'}.issubset(set(embedding_types)))
        self.assertTrue({'completion', 'custom', 'openai', 'openrouter'}.issubset(set(s2t_types)))
        self.assertTrue({'custom', 'openai', 'openrouter', 'thinkthinksyn'}.issubset(set(t2s_types)))
        self.assertNotIn('coding-agent', embedding_types)
        self.assertNotIn('coding-agent', s2t_types)
        self.assertNotIn('coding-agent', t2s_types)

    async def test_settings_apply_accepts_obs_object_adapter_source(self):
        from core.ai.config import AIServicesConfig
        from core.server.routes.ai_services import panel as panel_routes

        shared = panel_routes._get_shared()
        previous_snapshot = shared.get_ai_services_config()
        previous_global_config = AIServicesConfig.__Instance__
        shared.clear_ai_services_reload_state()
        shared.set_ai_services_config(None, version=0)
        AIServicesConfig.SetGlobal(AIServicesConfig())

        mocked_path = Path(self.__class__._tmp_dir_obj.name) / 'ai_services.settings.test.yaml'
        payload = {
            'completion': {
                'clients': {
                    'obs-custom': {
                        'type': 'custom',
                        'adapter': {
                            'storage_name': 'default',
                            'object_id': 'ai/custom-adapters/completion/demo_adapter.py',
                            'path': 'ai/custom-adapters/completion/demo_adapter.py',
                            'name': 'demo_adapter.py',
                            'size': 123,
                            'content_type': 'text/x-python',
                            'metadata': {
                                'purpose': 'ai-custom-adapter',
                            },
                        },
                        'max_tokens': 256,
                    },
                },
                'service': {
                    'default': {
                        'clients': ['obs-custom'],
                    },
                },
            },
        }

        try:
            with unittest_mock.patch.object(panel_routes, 'get_predefined_service_kinds', return_value=['completion']), \
                 unittest_mock.patch.object(panel_routes, '_reload_workers', new=unittest_mock.AsyncMock(return_value=[])), \
                 unittest_mock.patch.object(panel_routes, '_write_ai_services_config_file', return_value=mocked_path):
                apply_resp = await self._client.post(
                    '/_internal/admin/ai-services/settings/apply',
                    json={
                        'config': payload,
                        'wait_for_reload': False,
                    },
                )

                self.assertEqual(apply_resp.status_code, 200)
                apply_data = apply_resp.json()
                self.assertTrue(apply_data['saved'])
                self.assertNotEqual(apply_data['message'], '配置未发生变更。')

                shared_snapshot = shared.get_ai_services_config()
                serialized_config = shared_snapshot.get('serialized_config')
                self.assertIsInstance(serialized_config, str)
                shared_config = json.loads(serialized_config)
                self.assertIn('obs-custom', shared_config['completion']['clients'])

                settings_resp = await self._client.get('/_internal/admin/ai-services/settings')
                self.assertEqual(settings_resp.status_code, 200)
                settings_data = settings_resp.json()
                self.assertIn('obs-custom', settings_data['config']['completion']['clients'])
                client_cfg = settings_data['config']['completion']['clients']['obs-custom']
                self.assertEqual(client_cfg['type'], 'custom')
                self.assertIsInstance(client_cfg['adapter'], dict)
                self.assertEqual(client_cfg['adapter']['path'], 'ai/custom-adapters/completion/demo_adapter.py')
                self.assertEqual(client_cfg['adapter']['storage_name'], 'default')
                self.assertEqual(client_cfg['adapter']['metadata']['purpose'], 'ai-custom-adapter')
        finally:
            AIServicesConfig.SetGlobal(previous_global_config)
            shared.clear_ai_services_reload_state()
            shared.set_ai_services_config(
                previous_snapshot.get('serialized_config'),
                version=int(previous_snapshot.get('version') or 0),
            )

    async def test_settings_apply_preserves_shared_kwargs_presets(self):
        from core.ai.config import AIServicesConfig
        from core.server.routes.ai_services import panel as panel_routes

        shared = panel_routes._get_shared()
        previous_snapshot = shared.get_ai_services_config()
        previous_global_config = AIServicesConfig.__Instance__
        shared.clear_ai_services_reload_state()
        shared.set_ai_services_config(None, version=0)
        AIServicesConfig.SetGlobal(AIServicesConfig())

        mocked_path = Path(self.__class__._tmp_dir_obj.name) / 'ai_services.kwargs.test.yaml'
        payload = {
            'kwargs': {
                'openai-base': {
                    'type': 'openai-liked',
                    'model': 'preset-model',
                    'max_tokens': '14K',
                },
                'completion-small': {
                    'kwargs': 'openai-base',
                    'temperature': 0.2,
                },
            },
            'services': {
                'completion': {
                    'clients': {
                        'preset-client': {
                            'kwargs': 'completion-small',
                            'model': 'local-model',
                        },
                    },
                    'services': {
                        'default': {
                            'clients': ['preset-client'],
                        },
                    },
                },
            },
        }

        try:
            with unittest_mock.patch.object(panel_routes, 'get_predefined_service_kinds', return_value=['completion']), \
                 unittest_mock.patch.object(panel_routes, '_reload_workers', new=unittest_mock.AsyncMock(return_value=[])), \
                 unittest_mock.patch.object(panel_routes, '_write_ai_services_config_file', return_value=mocked_path):
                apply_resp = await self._client.post(
                    '/_internal/admin/ai-services/settings/apply',
                    json={
                        'config': payload,
                        'wait_for_reload': False,
                    },
                )

                self.assertEqual(apply_resp.status_code, 200)
                apply_data = apply_resp.json()
                self.assertTrue(apply_data['saved'])
                self.assertEqual(apply_data['service_kinds'], ['completion'])

                settings_resp = await self._client.get('/_internal/admin/ai-services/settings')
                self.assertEqual(settings_resp.status_code, 200)
                settings_data = settings_resp.json()
                self.assertIn('openai-base', settings_data['config']['kwargs'])
                self.assertEqual(settings_data['config']['kwargs']['openai-base']['type'], 'openai')
                self.assertEqual(settings_data['config']['kwargs']['openai-base']['max_tokens'], 14000)
                preset_client = settings_data['config']['completion']['clients']['preset-client']
                self.assertEqual(preset_client['type'], 'openai')
                self.assertEqual(preset_client['max_tokens'], 14000)
                self.assertEqual(preset_client['kwargs']['model'], 'local-model')
                self.assertEqual(preset_client['kwargs']['temperature'], 0.2)
                raw_client = settings_data['raw_config']['services']['completion']['clients']['preset-client']
                self.assertEqual(raw_client['kwargs'], 'completion-small')
                self.assertEqual(raw_client['model'], 'local-model')
                self.assertEqual(settings_data['raw_config']['kwargs']['completion-small']['kwargs'], 'openai-base')
        finally:
            AIServicesConfig.SetGlobal(previous_global_config)
            shared.clear_ai_services_reload_state()
            shared.set_ai_services_config(
                previous_snapshot.get('serialized_config'),
                version=int(previous_snapshot.get('version') or 0),
            )

    async def test_settings_apply_saves_raw_kwargs_refs_without_runtime_reload_when_effective_config_unchanged(self):
        from core.ai.config import AIServicesConfig
        from core.server.routes.ai_services import panel as panel_routes

        shared = panel_routes._get_shared()
        previous_snapshot = shared.get_ai_services_config()
        previous_global_config = AIServicesConfig.__Instance__
        raw_payload = {
            'kwargs': {
                'openai-base': {
                    'type': 'openai-liked',
                    'base_url': 'http://127.0.0.1:18888/v1',
                    'model': 'preset-model',
                },
            },
            'services': {
                'completion': {
                    'clients': {
                        'preset-client': {
                            'kwargs': 'openai-base',
                            'model': 'local-model',
                        },
                    },
                    'services': {
                        'default': {'clients': ['preset-client']},
                    },
                },
            },
        }
        normalized_cfg = AIServicesConfig.model_validate(raw_payload)
        mocked_path = Path(self.__class__._tmp_dir_obj.name) / 'ai_services.raw-refs.test.yaml'

        try:
            shared.clear_ai_services_reload_state()
            shared.set_ai_services_config(normalized_cfg.to_serialized_env(), version=1)
            AIServicesConfig.SetGlobal(normalized_cfg)
            reload_mock = unittest_mock.AsyncMock(return_value=[])
            with unittest_mock.patch.object(panel_routes, 'get_predefined_service_kinds', return_value=['completion']), \
                 unittest_mock.patch.object(panel_routes, '_reload_workers', new=reload_mock), \
                 unittest_mock.patch.object(panel_routes, '_write_ai_services_config_file', return_value=mocked_path):
                apply_resp = await self._client.post(
                    '/_internal/admin/ai-services/settings/apply',
                    json={
                        'config': raw_payload,
                        'wait_for_reload': True,
                    },
                )

                self.assertEqual(apply_resp.status_code, 200)
                apply_data = apply_resp.json()
                self.assertTrue(apply_data['saved'])
                self.assertFalse(apply_data['reloaded'])
                self.assertEqual(apply_data['service_kinds'], [])
                reload_mock.assert_not_called()

                settings_resp = await self._client.get('/_internal/admin/ai-services/settings')
                self.assertEqual(settings_resp.status_code, 200)
                raw_client = settings_resp.json()['raw_config']['services']['completion']['clients']['preset-client']
                self.assertEqual(raw_client['kwargs'], 'openai-base')
                self.assertEqual(raw_client['model'], 'local-model')
        finally:
            AIServicesConfig.SetGlobal(previous_global_config)
            shared.clear_ai_services_reload_state()
            shared.set_ai_services_config(
                previous_snapshot.get('serialized_config'),
                version=int(previous_snapshot.get('version') or 0),
            )

    async def test_runtime_client_update_records_shared_value_update(self):
        from core.server.routes.ai_services import panel as panel_routes

        shared = panel_routes._get_shared()
        previous_updates = dict(getattr(shared, 'ai_service_client_value_updates', {}))
        previous_update_version = int(getattr(shared, 'ai_service_client_value_version', 0))
        try:
            with unittest_mock.patch.object(
                panel_routes,
                'apply_ai_service_client_value_update',
                new=unittest_mock.AsyncMock(return_value=panel_routes.ClientStatusInfo(key='client-key')),
            ):
                resp = await self._client.post(
                    '/_internal/admin/ai-services/runtime-service-client/FakeService/default/client-key',
                    json={
                        'max_concurrent': 3,
                        'priority': 1.25,
                        'model': 'runtime-model',
                    },
                )

            self.assertEqual(resp.status_code, 200)
            updates = shared.get_ai_service_client_value_updates_since(previous_update_version)
            self.assertTrue(updates)
            latest = updates[-1]
            self.assertEqual(latest['service_type'], 'FakeService')
            self.assertEqual(latest['service_key'], 'default')
            self.assertEqual(latest['client_key'], 'client-key')
            self.assertEqual(latest['values']['max_concurrent'], 3)
            self.assertEqual(latest['values']['priority'], 1.25)
            self.assertEqual(latest['values']['model'], 'runtime-model')
        finally:
            shared.ai_service_client_value_updates = previous_updates
            shared.ai_service_client_value_version = previous_update_version
