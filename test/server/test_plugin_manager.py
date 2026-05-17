# -*- coding: utf-8 -*-

import asyncio
import os
import sys
import tarfile
import tempfile
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

import core.server.plugin as plugin_module
from core.server.plugin import PluginRuntimeProcessResult, apply_runtime_plugin_action
import core.server.app as core_app_module
from core.server.app import create_app
from core.server.data_types.config import Config
from core.server.plugin import (
    clear_plugins,
    configure_plugin,
    get_plugin_paths_from_env,
    get_plugin_instance,
    get_registered_plugins,
    register_plugin,
    render_plugin_panel,
    start_plugins,
    stop_plugins,
)


def _create_isolated_app() -> FastAPI:
    core_app_module._app = None
    return create_app(config=Config())

def _write_plugin_file(path: Path, *, class_name: str, plugin_name: str) -> None:
    path.write_text(
        (
            f'class {class_name}:\n'
            f'    Name = {plugin_name!r}\n'
            '    Type = "main-only"\n\n'
            '    @classmethod\n'
            '    def Create(cls, create_in, config=None, core_module=None):\n'
            '        assert core_module is not None\n'
            '        return cls()\n'
        ),
        encoding='utf-8',
    )


def _restore_plugin_runtime(saved_env: str | None, saved_config: Config | None) -> None:
    clear_plugins()
    if saved_env is None:
        os.environ.pop('__SERVER_PLUGIN_PATHS__', None)
    else:
        os.environ['__SERVER_PLUGIN_PATHS__'] = saved_env
    Config.__Instance__ = saved_config  # type: ignore[attr-defined]


def test_register_plugin_rejects_instance_registration() -> None:
    clear_plugins()

    class InvalidPlugin:
        Name = "invalid"
        Type = "main-only"

    try:
        register_plugin(InvalidPlugin())
    except TypeError as exc:
        assert "class" in str(exc).lower()
    else:
        raise AssertionError("register_plugin should reject plugin instances")


def test_register_plugin_rejects_unsupported_platform() -> None:
    clear_plugins()
    unsupported_platform_map = {
        'windows': 'linux',
        'linux': 'macos',
        'macos': 'windows',
    }
    unsupported_platform = unsupported_platform_map[plugin_module._get_current_platform()]

    class UnsupportedPlatformPlugin:
        Name = "unsupported-platform"
        Type = "main-only"
        SupportedPlatform = unsupported_platform

        @classmethod
        def Create(cls, create_in, config=None, core_module=None):
            return cls()

    try:
        register_plugin(UnsupportedPlatformPlugin)
    except RuntimeError as exc:
        assert "platform" in str(exc).lower()
    else:
        raise AssertionError("register_plugin should reject unsupported platforms")


def test_dynamic_plugin_register_and_delete_updates_config_and_calls_stop_hooks() -> None:
    saved_env = {
        '__SERVER_PLUGIN_PATHS__': os.environ.get('__SERVER_PLUGIN_PATHS__'),
        '__CONFIG_FILE_PATH__': os.environ.get('__CONFIG_FILE_PATH__'),
        '__WRITABLE_CONFIG_FILE_PATH__': os.environ.get('__WRITABLE_CONFIG_FILE_PATH__'),
        '__CONFIG__': os.environ.get('__CONFIG__'),
    }
    saved_config = Config.__Instance__  # type: ignore[attr-defined]
    clear_plugins()

    try:
        with tempfile.TemporaryDirectory(prefix='proj_plugin_dynamic_') as tmp_dir:
            tmp_root = Path(tmp_dir)
            config_path = tmp_root / 'server.yaml'
            log_path = tmp_root / 'events.log'
            plugin_path = tmp_root / 'dynamic_plugin.py'
            plugin_path.write_text(
                (
                    'from pathlib import Path\n\n'
                    f'LOG_PATH = Path(r"{str(log_path)}")\n\n'
                    'def _log(message: str) -> None:\n'
                    '    with LOG_PATH.open("a", encoding="utf-8") as file:\n'
                    '        file.write(message + "\\n")\n\n'
                    'class DynamicPlugin:\n'
                    '    Name = "dynamic-plugin"\n'
                    '    Type = "main-and-worker"\n\n'
                    '    @classmethod\n'
                    '    def Create(cls, create_in, config=None, core_module=None):\n'
                    '        _log(f"create:{create_in}")\n'
                    '        return cls()\n\n'
                    '    async def on_main_start(self):\n'
                    '        _log("main-start")\n\n'
                    '    async def on_main_stop(self):\n'
                    '        _log("main-stop")\n\n'
                    '    async def on_app_start(self, app):\n'
                    '        _log("worker-start")\n\n'
                    '    async def on_app_shutdown(self, app):\n'
                    '        _log("worker-stop")\n'
                ),
                encoding='utf-8',
            )

            os.environ['__CONFIG_FILE_PATH__'] = str(config_path)
            os.environ['__WRITABLE_CONFIG_FILE_PATH__'] = str(config_path)
            runtime_config = Config(plugin_paths=[])
            Config.__Instance__ = runtime_config  # type: ignore[attr-defined]
            runtime_config.write_to_path(config_path)

            app = FastAPI(title='Dynamic Plugin Test App')
            register_result = asyncio.run(apply_runtime_plugin_action('register', plugin_path, app=app, persist_to_config=True))
            assert register_result.saved is True
            assert register_result.plugin_types == ['main-and-worker']
            assert Config.Load(config_path, set_global=False).plugin_paths == [str(plugin_path.resolve())]

            delete_result = asyncio.run(apply_runtime_plugin_action('delete', plugin_path, app=app, persist_to_config=True))
            assert delete_result.saved is True
            assert Config.Load(config_path, set_global=False).plugin_paths == []

            log_lines = log_path.read_text(encoding='utf-8').splitlines()
            assert log_lines[:4] == ['create:main', 'main-start', 'create:worker', 'worker-start']
            assert 'main-stop' in log_lines
            assert 'worker-stop' in log_lines
    finally:
        clear_plugins()
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        Config.__Instance__ = saved_config  # type: ignore[attr-defined]


def test_plugin_manager_lifecycle_and_panel_rendering() -> None:
    clear_plugins()
    events: list[tuple[str, str, str, str]] = []

    class DemoPluginConfig(BaseModel):
        enabled: bool
        label: str

    @register_plugin
    class DemoPlugin:
        Name = "demo"
        Type = "main-and-worker"
        Description = "demo plugin"
        ConfigType = DemoPluginConfig

        def __init__(self, create_in: str, config: DemoPluginConfig | None):
            self.create_in = create_in
            self.config = config

        @classmethod
        async def Create(cls, create_in: str, config=None, core_module=None):
            assert isinstance(config, DemoPluginConfig)
            assert core_module is not None
            events.append(("create", create_in, config.label, getattr(core_module, "__name__", "")))
            return cls(create_in, config)

        async def on_main_start(self):
            events.append(("main-start", self.create_in, self.config.label, ""))

        async def on_main_stop(self):
            events.append(("main-stop", self.create_in, self.config.label, ""))

        async def on_app_start(self, app: FastAPI):
            events.append(("worker-start", app.title, self.config.label, ""))

        async def on_app_shutdown(self, app: FastAPI):
            events.append(("worker-stop", app.title, self.config.label, ""))

        async def admin_panel(self) -> str:
            return f'<div class="demo-plugin">{self.config.label}:{self.create_in}</div>'

    configure_plugin(DemoPlugin, {"enabled": True, "label": "demo-label"})

    asyncio.run(start_plugins("main"))
    main_instance = get_plugin_instance(DemoPlugin, "main")
    assert main_instance is not None

    worker_app = FastAPI(title="Plugin Test App")
    asyncio.run(start_plugins("worker", worker_app))
    worker_instance = get_plugin_instance(DemoPlugin, "worker")
    assert worker_instance is not None

    panel_html = asyncio.run(render_plugin_panel(plugin_module.get_plugin_key(DemoPlugin)))
    assert 'class="demo-plugin"' in panel_html
    assert "demo-label:worker" in panel_html

    asyncio.run(stop_plugins("worker", worker_app))
    asyncio.run(stop_plugins("main"))

    assert events == [
        ("create", "main", "demo-label", "core"),
        ("main-start", "main", "demo-label", ""),
        ("create", "worker", "demo-label", "core"),
        ("worker-start", "Plugin Test App", "demo-label", ""),
        ("worker-stop", "Plugin Test App", "demo-label", ""),
        ("main-stop", "main", "demo-label", ""),
    ]


def test_create_app_registers_plugin_panel_route() -> None:
    clear_plugins()
    app = _create_isolated_app()
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/_internal/admin/panel/plugins" in route_paths
    assert "/_internal/admin/panel/plugins/view/{plugin_key:path}" in route_paths
    assert "/_internal/admin/api/plugins" in route_paths
    assert "/_internal/admin/api/plugins/runtime/register" in route_paths
    assert "/_internal/admin/api/plugins/runtime/delete" in route_paths
    assert "/_internal/admin/api/plugins/runtime/restart-item" in route_paths
    assert "/_internal/admin/api/plugins/runtime/delete-item" in route_paths
    assert "/_internal/admin/api/plugins/runtime/inspect" in route_paths
    assert "/_internal/admin/api/plugins/runtime/upload" in route_paths


def test_plugin_optional_hooks_are_not_required() -> None:
    clear_plugins()
    events: list[tuple[str, str, str]] = []

    @register_plugin
    class MinimalPlugin:
        Name = "minimal"
        Type = "main-and-worker"

        @classmethod
        def Create(cls, create_in: str, config=None, core_module=None):
            events.append(("create", create_in, getattr(core_module, "__name__", "")))
            return cls()

    worker_app = FastAPI(title="Minimal Plugin App")

    asyncio.run(start_plugins("main"))
    asyncio.run(start_plugins("worker", worker_app))
    panel_html = asyncio.run(render_plugin_panel(plugin_module.get_plugin_key(MinimalPlugin)))
    asyncio.run(stop_plugins("worker", worker_app))
    asyncio.run(stop_plugins("main"))

    assert "This plugin does not expose an admin panel." in panel_html
    assert events == [
        ("create", "main", "core"),
        ("create", "worker", "core"),
    ]


def test_arg_parser_can_load_multiple_plugin_paths() -> None:
    saved_env = os.environ.get('__SERVER_PLUGIN_PATHS__')
    saved_config = Config.__Instance__  # type: ignore[attr-defined]
    clear_plugins()

    try:
        with tempfile.TemporaryDirectory(prefix='proj_plugin_multi_') as tmp_dir:
            tmp_root = Path(tmp_dir)
            plugin_file = tmp_root / 'file_plugin.py'
            _write_plugin_file(plugin_file, class_name='FilePlugin', plugin_name='file-plugin')

            package_dir = tmp_root / 'package_plugin'
            package_dir.mkdir()
            _write_plugin_file(package_dir / '__main__.py', class_name='PackagePlugin', plugin_name='package-plugin')

            parser = Config.BuildArgParser()
            args = parser.parse_args(['--plugin', str(plugin_file), '--plugin', str(package_dir)])
            Config.CreateConfigFromArgs(args, set_global=False)

            registered_names = sorted(plugin.Name for plugin in get_registered_plugins())
            assert registered_names == ['file-plugin', 'package-plugin']
            assert get_plugin_paths_from_env() == (plugin_file.resolve(), package_dir.resolve())
    finally:
        _restore_plugin_runtime(saved_env, saved_config)


def test_arg_parser_can_apply_plugin_config_file() -> None:
    saved_env = os.environ.get('__SERVER_PLUGIN_PATHS__')
    saved_config = Config.__Instance__  # type: ignore[attr-defined]
    clear_plugins()

    try:
        with tempfile.TemporaryDirectory(prefix='proj_plugin_config_') as tmp_dir:
            tmp_root = Path(tmp_dir)
            plugin_file = tmp_root / 'configurable_plugin.py'
            plugin_file.write_text(
                (
                    'from pydantic import BaseModel\n\n'
                    'class DemoPluginConfig(BaseModel):\n'
                    '    enabled: bool\n'
                    '    label: str\n\n'
                    'class ConfigurablePlugin:\n'
                    '    Key = "configurable-plugin"\n'
                    '    Name = "configurable-plugin"\n'
                    '    Type = "main-only"\n'
                    '    ConfigType = DemoPluginConfig\n\n'
                    '    @classmethod\n'
                    '    def Create(cls, create_in, config=None, core_module=None):\n'
                    '        return cls()\n'
                ),
                encoding='utf-8',
            )
            plugin_config_file = tmp_root / 'plugin-config.yaml'
            plugin_config_file.write_text('enabled: true\nlabel: from-file\n', encoding='utf-8')

            parser = Config.BuildArgParser()
            args = parser.parse_args(['--plugin', str(plugin_file), '--plugin-config', str(plugin_config_file)])
            Config.CreateConfigFromArgs(args, set_global=False)

            assert plugin_module._plugin_configs['configurable-plugin'] == {'enabled': True, 'label': 'from-file'}
    finally:
        _restore_plugin_runtime(saved_env, saved_config)


def test_runtime_register_notifies_main_before_worker_broadcast(monkeypatch) -> None:
    saved_config = Config.__Instance__  # type: ignore[attr-defined]
    clear_plugins()

    try:
        with tempfile.TemporaryDirectory(prefix='proj_plugin_order_') as tmp_dir:
            plugin_path = Path(tmp_dir) / 'ordered_plugin.py'
            _write_plugin_file(plugin_path, class_name='OrderedPlugin', plugin_name='ordered-plugin')
            Config.__Instance__ = Config(plugin_paths=[])  # type: ignore[attr-defined]
            order: list[str] = []

            def _fake_main(action, path, **kwargs):
                order.append('main')
                return PluginRuntimeProcessResult(
                    ok=True,
                    pid=1,
                    stage='main',
                    action='register',
                    path=str(plugin_path.resolve()),
                    plugin_keys=['ordered'],
                    plugin_types=['main-and-worker'],
                )

            async def _fake_broadcast(action, path, app, **kwargs):
                assert order == ['main']
                order.append('worker')
                return [
                    PluginRuntimeProcessResult(
                        ok=True,
                        pid=os.getpid(),
                        stage='worker',
                        action='register',
                        path=str(plugin_path.resolve()),
                        plugin_keys=['ordered'],
                        plugin_types=['main-and-worker'],
                    )
                ]

            monkeypatch.setattr(plugin_module, '_request_main_plugin_action', _fake_main)
            monkeypatch.setattr(plugin_module, '_broadcast_worker_plugin_action', _fake_broadcast)
            monkeypatch.setattr(plugin_module, '_persist_runtime_plugin_paths', lambda plugin_paths: str(plugin_path.resolve()))

            result = asyncio.run(apply_runtime_plugin_action('register', plugin_path, app=FastAPI(title='Order App'), persist_to_config=True))
            assert result.saved is True
            assert order == ['main', 'worker']
    finally:
        clear_plugins()
        Config.__Instance__ = saved_config  # type: ignore[attr-defined]


def test_arg_parser_can_load_plugin_from_tar_gz_cache() -> None:
    saved_env = os.environ.get('__SERVER_PLUGIN_PATHS__')
    saved_config = Config.__Instance__  # type: ignore[attr-defined]
    clear_plugins()

    try:
        with tempfile.TemporaryDirectory(prefix='proj_plugin_archive_') as tmp_dir:
            tmp_root = Path(tmp_dir)
            package_dir = tmp_root / 'archive_plugin'
            package_dir.mkdir()
            plugin_main = package_dir / '__main__.py'
            _write_plugin_file(plugin_main, class_name='ArchivePlugin', plugin_name='archive-plugin')

            archive_path = tmp_root / 'archive_plugin.tar.gz'
            with tarfile.open(archive_path, 'w:gz') as archive:
                archive.add(package_dir, arcname='archive_plugin')

            parser = Config.BuildArgParser()
            args = parser.parse_args(['--plugin', str(archive_path)])
            Config.CreateConfigFromArgs(args, set_global=False)

            first_plugin = get_registered_plugins()[0]
            assert first_plugin.Name == 'archive-plugin'
            first_module = sys.modules[first_plugin.__module__]
            extracted_main = Path(str(getattr(first_module, '__file__', ''))).resolve()
            extracted_main.write_text(
                extracted_main.read_text(encoding='utf-8').replace('archive-plugin', 'archive-plugin-cached'),
                encoding='utf-8',
            )

            clear_plugins()
            Config.CreateConfigFromArgs(args, set_global=False)

            reloaded_plugins = get_registered_plugins()
            assert len(reloaded_plugins) == 1
            assert reloaded_plugins[0].Name == 'archive-plugin-cached'
    finally:
        _restore_plugin_runtime(saved_env, saved_config)


def test_inspect_plugin_path_exposes_config_schema_without_registering_unsupported_plugin() -> None:
    clear_plugins()

    unsupported_platform_map = {
        'windows': 'linux',
        'linux': 'macos',
        'macos': 'windows',
    }
    unsupported_platform = unsupported_platform_map[plugin_module.get_current_platform()]

    with tempfile.TemporaryDirectory(prefix='proj_plugin_inspect_') as tmp_dir:
        plugin_path = Path(tmp_dir) / 'inspectable_plugin.py'
        plugin_path.write_text(
            (
                'from pydantic import BaseModel, Field\n\n'
                'class InspectConfig(BaseModel):\n'
                '    enabled: bool = True\n'
                '    label: str = Field(default="demo", description="label text")\n\n'
                'class InspectablePlugin:\n'
                '    Key = "inspectable-plugin"\n'
                '    Name = {"zh-cn": "可检查插件", "en": "Inspectable Plugin"}\n'
                f'    SupportedPlatform = "{unsupported_platform}"\n'
                '    Type = "worker-only"\n'
                '    ConfigType = InspectConfig\n\n'
                '    @classmethod\n'
                '    def Create(cls, create_in, config=None, core_module=None):\n'
                '        return cls()\n'
            ),
            encoding='utf-8',
        )

        inspect_result = plugin_module.inspect_plugin_path(plugin_path, lang='zh-cn')
        assert inspect_result.plugin_keys == ['inspectable-plugin']
        assert inspect_result.plugin_types == ['worker-only']
        assert inspect_result.plugins[0].name == '可检查插件'
        assert inspect_result.plugins[0].supported_platforms == [unsupported_platform]
        assert inspect_result.plugins[0].has_config is True
        assert [item.name for item in inspect_result.plugins[0].config_fields] == ['enabled', 'label']
        assert get_registered_plugins() == ()


def test_runtime_register_applies_plugin_config_and_persists() -> None:
    saved_env = {
        '__SERVER_PLUGIN_PATHS__': os.environ.get('__SERVER_PLUGIN_PATHS__'),
        '__CONFIG_FILE_PATH__': os.environ.get('__CONFIG_FILE_PATH__'),
        '__WRITABLE_CONFIG_FILE_PATH__': os.environ.get('__WRITABLE_CONFIG_FILE_PATH__'),
        '__CONFIG__': os.environ.get('__CONFIG__'),
    }
    saved_config = Config.__Instance__  # type: ignore[attr-defined]
    clear_plugins()

    try:
        with tempfile.TemporaryDirectory(prefix='proj_plugin_runtime_cfg_') as tmp_dir:
            tmp_root = Path(tmp_dir)
            config_path = tmp_root / 'server.yaml'
            plugin_path = tmp_root / 'runtime_config_plugin.py'
            plugin_path.write_text(
                (
                    'from pydantic import BaseModel\n\n'
                    'class RuntimeConfig(BaseModel):\n'
                    '    enabled: bool\n'
                    '    label: str\n\n'
                    'class RuntimeConfigPlugin:\n'
                    '    Key = "runtime-config-plugin"\n'
                    '    Name = "runtime-config-plugin"\n'
                    '    Type = "main-and-worker"\n'
                    '    ConfigType = RuntimeConfig\n\n'
                    '    def __init__(self, config):\n'
                    '        self.config = config\n\n'
                    '    @classmethod\n'
                    '    def Create(cls, create_in, config=None, core_module=None):\n'
                    '        return cls(config)\n'
                ),
                encoding='utf-8',
            )

            os.environ['__CONFIG_FILE_PATH__'] = str(config_path)
            os.environ['__WRITABLE_CONFIG_FILE_PATH__'] = str(config_path)
            runtime_config = Config(plugin_paths=[])
            Config.__Instance__ = runtime_config  # type: ignore[attr-defined]
            runtime_config.write_to_path(config_path)

            app = FastAPI(title='Runtime Config Plugin Test App')
            result = asyncio.run(
                apply_runtime_plugin_action(
                    'register',
                    plugin_path,
                    app=app,
                    persist_to_config=True,
                    shared_config={'enabled': True, 'label': 'runtime-label'},
                )
            )

            assert result.saved is True
            assert result.plugin_keys == ['runtime-config-plugin']
            persisted = Config.Load(config_path, set_global=False)
            assert persisted.plugin_configs['runtime-config-plugin'] == {'enabled': True, 'label': 'runtime-label'}
            worker_instance = get_plugin_instance(get_registered_plugins()[0], 'worker')
            assert worker_instance is not None
            assert worker_instance.config.label == 'runtime-label'
    finally:
        clear_plugins()
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        Config.__Instance__ = saved_config  # type: ignore[attr-defined]


def test_set_config_applies_plugin_configs_by_plugin_key() -> None:
    saved_config = Config.__Instance__  # type: ignore[attr-defined]
    clear_plugins()

    @register_plugin
    class ConfiguredPlugin:
        Key = "configured-plugin"
        Name = "configured-plugin"
        Type = "main-only"

        @classmethod
        def Create(cls, create_in, config=None, core_module=None):
            return cls()

    try:
        plugin_key = "configured-plugin"
        Config.SetConfig(Config(plugin_configs={plugin_key: {"enabled": True, "label": "rtc"}}))

        stored = plugin_module._plugin_configs.get(plugin_key)
        assert stored == {"enabled": True, "label": "rtc"}
    finally:
        clear_plugins()
        Config.__Instance__ = saved_config  # type: ignore[attr-defined]


def test_plugin_explicit_key_overrides_dynamic_module_key() -> None:
    clear_plugins()

    @register_plugin
    class KeyedPlugin:
        Key = "webrtc-chatroom"
        Name = "keyed-plugin"
        Type = "main-only"

        @classmethod
        def Create(cls, create_in, config=None, core_module=None):
            return cls()

    try:
        assert plugin_module.get_plugin_key(KeyedPlugin) == "webrtc-chatroom"
    finally:
        clear_plugins()
