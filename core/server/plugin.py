import asyncio
from collections.abc import Sequence as ABCSequence
import contextlib
import gzip
import inspect
import importlib
import importlib.util
import json
import logging
import hashlib
import os
import shutil
import socket
import sys
import tarfile
import threading
import zipfile
from html import escape
from pathlib import Path
from types import ModuleType
from typing import (
    Protocol, runtime_checkable, ClassVar, TYPE_CHECKING, Literal, Any, Awaitable, Self, Mapping, Sequence, cast,
)

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from core.constants import PROJECT_DIR
from core.utils.concurrent_utils.file_lock import FileCrossProcessLock
from core.utils.concurrent_utils import run_any_func

from .app import get_resources, on_app_created, on_app_shutdown, on_before_app_created
from .events import on_main_process_starts_event, on_main_process_stops_event, register_main_process_context_manager
from .html_injection import html_response_from_content, html_response_from_path
if TYPE_CHECKING:
    from .translate import InternalTranslateLang

type HTML = str
type PluginType = Literal['main-only', 'worker-only', 'main-and-worker']
type Platform = Literal['windows', 'macos', 'linux', 'all']
type CreateIn = Literal['main', 'worker']
type PluginConfig = BaseModel | dict[str, Any] | None
type CoreModule = ModuleType
type PluginRuntimeAction = Literal['register', 'delete', 'restart']

logger = logging.getLogger(__name__)

_PLUGIN_TYPES: set[PluginType] = {'main-only', 'worker-only', 'main-and-worker'}
_PLATFORMS: set[Platform] = {'windows', 'macos', 'linux', 'all'}
_PLUGIN_PATHS_ENV = '__SERVER_PLUGIN_PATHS__'
_PLUGIN_CACHE_DIR = PROJECT_DIR / 'tmp' / 'plugins'
_PLUGIN_UPLOAD_DIR = _PLUGIN_CACHE_DIR / 'uploaded'
_PLUGIN_IMPORTABLE_DIR = _PLUGIN_CACHE_DIR / 'importable'
_PLUGIN_CONTROL_HOST_ENV = '__SERVER_PLUGIN_CONTROL_HOST__'
_PLUGIN_CONTROL_PORT_ENV = '__SERVER_PLUGIN_CONTROL_PORT__'
_PLUGIN_CONTROL_TOKEN_ENV = '__SERVER_PLUGIN_CONTROL_TOKEN__'
_LOCAL_HOSTS = {'127.0.0.1', '::1', 'localhost', 'testclient', 'testserver'}

@runtime_checkable
class PluginBase(Protocol):
    
    Key: ClassVar[str|None] = None
    Name: ClassVar[str|dict["InternalTranslateLang", str]]
    Type: ClassVar[PluginType]
    SupportedPlatform: ClassVar[Sequence[Platform] | Platform] = 'all'
    Description: ClassVar[str|dict["InternalTranslateLang", str]|None] = None
    ConfigType: ClassVar[type[BaseModel]|None] = None
    
    @classmethod
    def Create(
        cls, 
        create_in: CreateIn,
        config: PluginConfig=None,
        core_module: CoreModule | None=None,
    )->Self|Awaitable[Self]:
        '''if `ConfigType` is defined, `config` will be validated and parsed to the type,
        otherwise raw `config` dict will be passed. `core_module` is the imported `core`
        package so plugins can directly access shared runtime helpers.'''
        ...

@runtime_checkable
class MainOnlyPlugin(PluginBase, Protocol):
    Type: ClassVar[Literal['main-only']] = 'main-only'
    
@runtime_checkable
class WorkerOnlyPlugin(PluginBase, Protocol):
    Type: ClassVar[Literal['worker-only']] = 'worker-only'
    
@runtime_checkable
class MainAndWorkerPlugin(MainOnlyPlugin, WorkerOnlyPlugin, Protocol):
    Type: ClassVar[Literal['main-and-worker']] = 'main-and-worker'
    
type Plugin = MainOnlyPlugin | WorkerOnlyPlugin | MainAndWorkerPlugin
type PluginClass = type[PluginBase]


class PluginPanelItem(BaseModel):
    key: str
    name: str
    description: str | None = None
    type: PluginType
    has_panel: bool
    source_path: str | None = None
    supported_platforms: list[Platform] = Field(default_factory=list)
    has_config: bool = False
    current_config: dict[str, Any] | None = None
    config_fields: list['PluginConfigFieldDescriptor'] = Field(default_factory=list)


class PluginPanelListResponse(BaseModel):
    plugins: list[PluginPanelItem]


class PluginRuntimeRequest(BaseModel):
    path: str
    config: dict[str, Any] | None = None
    plugin_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PluginRegisteredRuntimeRequest(BaseModel):
    plugin_key: str
    config: dict[str, Any] | None = None


class PluginRegisteredRuntimeResponse(BaseModel):
    saved: bool
    file_path: str | None = None
    action: PluginRuntimeAction
    plugin_key: str
    path: str | None = None
    plugin_type: PluginType
    results: list['PluginRuntimeProcessResult'] = Field(default_factory=list)


class PluginConfigFieldDescriptor(BaseModel):
    name: str
    title: str | None = None
    description: str | None = None
    json_type: str | None = None
    format: str | None = None
    required: bool = False
    has_default: bool = False
    default: Any = None
    field_schema: dict[str, Any] = Field(default_factory=dict)


class PluginRuntimeInspectionItem(BaseModel):
    key: str
    name: str
    description: str | None = None
    type: PluginType
    supported_platforms: list[Platform] = Field(default_factory=list)
    has_panel: bool = False
    has_config: bool = False
    config_schema: dict[str, Any] | None = None
    config_fields: list[PluginConfigFieldDescriptor] = Field(default_factory=list)


class PluginRuntimeInspectResponse(BaseModel):
    path: str
    plugin_keys: list[str] = Field(default_factory=list)
    plugin_types: list[PluginType] = Field(default_factory=list)
    plugins: list[PluginRuntimeInspectionItem] = Field(default_factory=list)


class PluginRuntimeProcessResult(BaseModel):
    ok: bool = True
    pid: int
    stage: Literal['main', 'worker']
    action: PluginRuntimeAction
    path: str
    plugin_keys: list[str] = Field(default_factory=list)
    plugin_types: list[PluginType] = Field(default_factory=list)
    error: str | None = None


class PluginRuntimeResponse(BaseModel):
    saved: bool
    file_path: str | None = None
    action: PluginRuntimeAction
    path: str
    plugin_keys: list[str] = Field(default_factory=list)
    plugin_types: list[PluginType] = Field(default_factory=list)
    results: list[PluginRuntimeProcessResult] = Field(default_factory=list)


class PluginUploadRuntimeResponse(PluginRuntimeInspectResponse):
    uploaded_path: str

_registered_plugin_classes: list[PluginClass] = []
_plugin_configs: dict[str, PluginConfig] = {}
_plugin_source_keys_by_plugin_key: dict[str, str] = {}
_plugin_paths_by_source_key: dict[str, Path] = {}
_plugin_keys_by_source_key: dict[str, list[str]] = {}
_plugin_instances: dict[CreateIn, dict[str, Plugin]] = {
    'main': {},
    'worker': {},
}
_started_plugin_keys: dict[CreateIn, list[str]] = {
    'main': [],
    'worker': [],
}
_core_module: CoreModule | None = None
_loaded_plugin_source_keys: set[str] = set()
_plugin_control_server: '_PluginControlSocketServer | None' = None


class _PluginControlSocketServer:
    def __init__(self) -> None:
        self.host = '127.0.0.1'
        self.port = 0
        self.token = os.urandom(16).hex()
        self._stop_event = threading.Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, 0))
        self._socket.listen(8)
        self._socket.settimeout(0.5)
        self.port = int(self._socket.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, name='proj-plugin-control-socket', daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        with contextlib.suppress(Exception):
            self._socket.close()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1.0)

    def _read_payload(self, conn: socket.socket) -> dict[str, object]:
        chunks: list[bytes] = []
        total = 0
        while total < 64 * 1024:
            data = conn.recv(4096)
            if not data:
                break
            chunks.append(data)
            total += len(data)
            if b'\n' in data:
                break
        raw = b''.join(chunks).split(b'\n', 1)[0].strip()
        if not raw:
            return {}
        payload = json.loads(raw.decode('utf-8'))
        return dict(payload) if isinstance(payload, dict) else {}

    def _write_response(self, conn: socket.socket, payload: dict[str, object]) -> None:
        conn.sendall((json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8'))

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            payload = self._read_payload(conn)
            if payload.get('token') != self.token:
                self._write_response(conn, {'ok': False, 'error': 'Unauthorized plugin runtime request.'})
                return
            action = str(payload.get('action') or '').strip().lower()
            path = str(payload.get('path') or '').strip()
            plugin_key = str(payload.get('plugin_key') or '').strip()
            if action not in {'register', 'delete', 'restart'}:
                self._write_response(conn, {'ok': False, 'error': f'Unsupported plugin action: {action or "<empty>"}'})
                return
            shared_config = payload.get('config') if isinstance(payload.get('config'), dict) else None
            raw_plugin_configs = payload.get('plugin_configs')
            plugin_configs = raw_plugin_configs if isinstance(raw_plugin_configs, dict) else None
            if plugin_key:
                result = run_any_func(
                    _apply_local_main_registered_plugin_action,
                    cast(Literal['restart', 'delete'], action),
                    plugin_key,
                    shared_config=cast(dict[str, Any] | None, shared_config),
                )
            else:
                if not path:
                    self._write_response(conn, {'ok': False, 'error': 'Plugin path is required.'})
                    return
                result = run_any_func(
                    _apply_local_main_plugin_action,
                    cast(PluginRuntimeAction, action),
                    path,
                    shared_config=cast(dict[str, Any] | None, shared_config),
                    plugin_configs=cast(dict[str, dict[str, Any]] | None, plugin_configs),
                )
            self._write_response(conn, {'ok': True, 'result': result.model_dump(mode='python')})
        except Exception as exc:
            self._write_response(conn, {'ok': False, 'error': str(exc)})

    def _serve(self) -> None:
        while not self._stop_event.is_set():
            try:
                conn, _addr = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                continue
            with conn:
                self._handle_client(conn)


class _PluginControlSocketContextManager:
    def __enter__(self) -> None:
        global _plugin_control_server
        server = _PluginControlSocketServer()
        server.start()
        _plugin_control_server = server
        os.environ[_PLUGIN_CONTROL_HOST_ENV] = server.host
        os.environ[_PLUGIN_CONTROL_PORT_ENV] = str(server.port)
        os.environ[_PLUGIN_CONTROL_TOKEN_ENV] = server.token
        return None

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        global _plugin_control_server
        server = _plugin_control_server
        _plugin_control_server = None
        if server is not None:
            server.close()
        os.environ.pop(_PLUGIN_CONTROL_HOST_ENV, None)
        os.environ.pop(_PLUGIN_CONTROL_PORT_ENV, None)
        os.environ.pop(_PLUGIN_CONTROL_TOKEN_ENV, None)
        return None


register_main_process_context_manager(_PluginControlSocketContextManager())


def get_plugin_key(plugin_class: PluginClass) -> str:
    explicit_key = str(getattr(plugin_class, 'Key', '') or '').strip()
    if explicit_key:
        return explicit_key
    return f'{plugin_class.__module__}.{plugin_class.__qualname__}'


def normalize_plugin_paths(plugin_paths: Sequence[str | Path]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(_normalize_plugin_path(path) for path in plugin_paths))


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, Mapping):
        return {str(key): _jsonable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _current_plugin_config_payloads() -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for plugin_key, plugin_config in _plugin_configs.items():
        if plugin_config is None:
            continue
        if isinstance(plugin_config, BaseModel):
            payloads[plugin_key] = cast(dict[str, Any], plugin_config.model_dump(mode='json'))
            continue
        if isinstance(plugin_config, Mapping):
            payloads[plugin_key] = cast(dict[str, Any], _jsonable_value(dict(plugin_config)))
    return payloads


def _current_plugin_paths() -> tuple[Path, ...]:
    try:
        from .data_types.config import Config

        config = Config.GetConfig()
        if config.plugin_paths:
            return normalize_plugin_paths(config.plugin_paths)
    except Exception:
        pass
    return get_plugin_paths_from_env()


def _plugin_scope_flags(plugin_classes: Sequence[PluginClass]) -> tuple[list[str], list[PluginType]]:
    return (
        [get_plugin_key(plugin_class) for plugin_class in plugin_classes],
        [cast(PluginType, plugin_class.Type) for plugin_class in plugin_classes],
    )


def _plugin_types_include_scope(plugin_types: Sequence[PluginType], scope: CreateIn) -> bool:
    if scope == 'main':
        return any(plugin_type in {'main-only', 'main-and-worker'} for plugin_type in plugin_types)
    return any(plugin_type in {'worker-only', 'main-and-worker'} for plugin_type in plugin_types)


def _update_current_process_plugin_paths(plugin_paths: Sequence[str | Path]) -> tuple[Path, ...]:
    normalized_paths = normalize_plugin_paths(plugin_paths)
    set_plugin_paths_env(normalized_paths)
    with contextlib.suppress(Exception):
        from .data_types.config import Config

        Config.GetConfig().plugin_paths = [str(path) for path in normalized_paths]
    return normalized_paths


def _persist_runtime_plugin_paths(plugin_paths: Sequence[str | Path]) -> str:
    from .data_types.config import Config

    normalized_paths = _update_current_process_plugin_paths(plugin_paths)
    config = Config.GetConfig()
    current_configs = _current_plugin_config_payloads()
    config.plugins = []
    for plugin_path in normalized_paths:
        entry_config: dict[str, dict[str, Any]] = {}
        with contextlib.suppress(Exception):
            for plugin_class in _get_plugins_for_source(plugin_path):
                plugin_key = get_plugin_key(plugin_class)
                if plugin_key in current_configs:
                    entry_config[plugin_key] = dict(current_configs[plugin_key])
        config.set_plugin_entry(plugin_path, entry_config)
    config_info = Config.DescribeRuntimeConfigPath()
    saved_path = config.write_to_path(config_info['write_path'])
    os.environ['__CONFIG_FILE_PATH__'] = str(saved_path)
    os.environ['__WRITABLE_CONFIG_FILE_PATH__'] = str(saved_path)
    os.environ['__CONFIG__'] = config.model_dump_json(indent=None)
    return str(saved_path)


def _normalize_uploaded_relative_path(raw_path: str, fallback_name: str) -> Path:
    candidate = str(raw_path or '').replace('\\', '/').strip().lstrip('/')
    if not candidate:
        candidate = Path(fallback_name).name
    normalized = Path(candidate)
    if normalized.is_absolute() or any(part in {'', '.', '..'} for part in normalized.parts):
        raise HTTPException(400, f'Illegal uploaded plugin path: {raw_path or fallback_name}')
    return normalized


def _select_uploaded_plugin_target(upload_root: Path, relative_paths: Sequence[Path]) -> Path:
    if not relative_paths:
        raise HTTPException(400, 'No plugin files were uploaded.')
    if len(relative_paths) == 1 and len(relative_paths[0].parts) == 1:
        return upload_root / relative_paths[0]
    top_levels = {path.parts[0] for path in relative_paths}
    if len(top_levels) != 1:
        raise HTTPException(400, '请选择单个插件文件、压缩包，或一个插件目录。')
    return upload_root / next(iter(top_levels))


async def _store_uploaded_plugin_bundle(files: Sequence[UploadFile], relative_paths: Sequence[str]) -> tuple[Path, Path]:
    import aiofiles

    if not files:
        raise HTTPException(400, 'No plugin files were uploaded.')

    _PLUGIN_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_root = (_PLUGIN_UPLOAD_DIR / f'plugin-{os.getpid()}-{os.urandom(6).hex()}').resolve()
    upload_root.mkdir(parents=True, exist_ok=False)
    written_relative_paths: list[Path] = []
    try:
        for index, upload in enumerate(files):
            fallback_name = Path(upload.filename or '').name.strip()
            if not fallback_name:
                raise HTTPException(400, '上传文件名不能为空。')
            relative_path = _normalize_uploaded_relative_path(
                relative_paths[index] if index < len(relative_paths) else '',
                fallback_name,
            )
            destination = (upload_root / relative_path).resolve(strict=False)
            if upload_root not in destination.parents and destination != upload_root:
                raise HTTPException(403, '上传目标超出插件缓存目录。')
            destination.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(destination, 'wb') as file:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    await file.write(chunk)
            await upload.close()
            written_relative_paths.append(relative_path)
        return upload_root, _select_uploaded_plugin_target(upload_root, written_relative_paths)
    except Exception:
        shutil.rmtree(upload_root, ignore_errors=True)
        raise


def _register_plugin_source(plugin_class: PluginClass, source_path: Path | None) -> None:
    if source_path is None:
        return
    source_key = _plugin_source_key(source_path)
    plugin_key = get_plugin_key(plugin_class)
    _plugin_source_keys_by_plugin_key[plugin_key] = source_key
    _plugin_paths_by_source_key[source_key] = source_path
    _plugin_keys_by_source_key.setdefault(source_key, [])
    if plugin_key not in _plugin_keys_by_source_key[source_key]:
        _plugin_keys_by_source_key[source_key].append(plugin_key)


def _get_plugins_for_source(source_path: str | Path) -> tuple[PluginClass, ...]:
    path = _normalize_plugin_path(source_path)
    source_key = _plugin_source_key(path)
    classes: list[PluginClass] = []
    for plugin_key in _plugin_keys_by_source_key.get(source_key, []):
        plugin_class = _find_plugin_class(plugin_key)
        if plugin_class is not None:
            classes.append(plugin_class)
    return tuple(classes)


def get_plugins_for_path(source_path: str | Path) -> tuple[PluginClass, ...]:
    return _get_plugins_for_source(source_path)


def _get_plugin_source_path(plugin_class: PluginClass | str) -> Path | None:
    plugin_key = plugin_class if isinstance(plugin_class, str) else get_plugin_key(plugin_class)
    source_key = _plugin_source_keys_by_plugin_key.get(plugin_key)
    if source_key is None:
        return None
    return _plugin_paths_by_source_key.get(source_key)


def _get_plugin_config_payload(plugin_class: PluginClass) -> dict[str, Any] | None:
    raw_config = _get_plugin_config(plugin_class)
    if raw_config is None:
        return None
    normalized = _jsonable_value(raw_config)
    if isinstance(normalized, dict):
        return cast(dict[str, Any], normalized)
    return None


def _forget_plugin_source(source_path: str | Path) -> None:
    path = _normalize_plugin_path(source_path)
    source_key = _plugin_source_key(path)
    for plugin_key in _plugin_keys_by_source_key.pop(source_key, []):
        _plugin_source_keys_by_plugin_key.pop(plugin_key, None)
    _plugin_paths_by_source_key.pop(source_key, None)
    _loaded_plugin_source_keys.discard(source_key)


def _normalize_plugin_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f'Plugin path not found: {candidate}')
    return candidate.resolve()


def _plugin_source_key(path: Path) -> str:
    return str(path.resolve()).replace('\\', '/').lower()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _module_token(source: str) -> str:
    return hashlib.sha1(source.encode('utf-8')).hexdigest()[:16]


def _archive_stem(path: Path) -> str:
    name = path.name
    name_lower = name.lower()
    for suffix in ('.tar.gz', '.tgz', '.zip', '.gz'):
        if name_lower.endswith(suffix):
            return name[: -len(suffix)] or 'plugin'
    return path.stem or 'plugin'


def _safe_archive_target(root: Path, member_name: str) -> Path:
    if not member_name:
        return root.resolve()
    target = (root / member_name).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f'Archive contains illegal path: {member_name}')
    return target


def _extract_plugin_archive(path: Path) -> Path:
    archive_hash = _hash_file(path)
    extract_root = _PLUGIN_CACHE_DIR / f'{_archive_stem(path)}_{archive_hash[:16]}'
    if extract_root.is_dir():
        return extract_root

    shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True, exist_ok=True)
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for member in archive.namelist():
                    _safe_archive_target(extract_root, member)
                archive.extractall(extract_root)
            return extract_root

        if tarfile.is_tarfile(path):
            with tarfile.open(path, 'r:*') as archive:
                for member in archive.getmembers():
                    if member.issym() or member.islnk():
                        raise ValueError(f'Archive contains unsupported link entry: {member.name}')
                    _safe_archive_target(extract_root, member.name)
                archive.extractall(extract_root, filter='data')
            return extract_root

        if path.suffix.lower() == '.gz':
            target_name = _archive_stem(path)
            target_file = _safe_archive_target(extract_root, target_name)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, 'rb') as source, target_file.open('wb') as target:
                shutil.copyfileobj(source, target)
            return extract_root
    except Exception:
        shutil.rmtree(extract_root, ignore_errors=True)
        raise

    shutil.rmtree(extract_root, ignore_errors=True)
    raise ValueError(f'Unsupported plugin archive format: {path}')


def _resolve_extracted_plugin_entry(extract_root: Path) -> Path:
    direct_main = extract_root / '__main__.py'
    if direct_main.is_file():
        return extract_root

    package_dirs = [
        child for child in sorted(extract_root.iterdir())
        if child.is_dir() and (child / '__main__.py').is_file()
    ]
    if len(package_dirs) == 1:
        return package_dirs[0]
    if len(package_dirs) > 1:
        raise ValueError(f'Ambiguous plugin archive layout: multiple package roots found in {extract_root}')

    py_files = [
        child for child in sorted(extract_root.iterdir())
        if child.is_file() and child.suffix.lower() == '.py'
    ]
    if len(py_files) == 1:
        return py_files[0]
    if len(py_files) > 1:
        raise ValueError(f'Ambiguous plugin archive layout: multiple Python files found in {extract_root}')
    raise ValueError(f'Plugin archive {extract_root} does not contain __main__.py or a single Python plugin file.')


def _load_module_from_python_file(py_file: Path, source_path: Path) -> ModuleType:
    module_name = f'_server_plugin_file_{_module_token(_plugin_source_key(source_path))}'
    import_root = _ensure_plugin_importable_root()
    staged_file = import_root / f'{module_name}.py'
    with FileCrossProcessLock(f"plugin_stage_{module_name}", default_timeout=10):
        staged_file.parent.mkdir(parents=True, exist_ok=True)
        if not (_is_archive_plugin_source(source_path) and staged_file.is_file()):
            shutil.copy2(py_file, staged_file)
        importlib.invalidate_caches()
        sys.modules.pop(module_name, None)
        return importlib.import_module(module_name)


def _load_module_from_package_dir(module_dir: Path, source_path: Path) -> ModuleType:
    main_file = module_dir / '__main__.py'
    if not main_file.is_file():
        raise FileNotFoundError(f'Plugin module directory must contain __main__.py: {module_dir}')
    module_name = f'_server_plugin_pkg_{_module_token(_plugin_source_key(source_path))}'
    import_root = _ensure_plugin_importable_root()
    staged_dir = import_root / module_name
    with FileCrossProcessLock(f"plugin_stage_{module_name}", default_timeout=10):
        if staged_dir.exists() and not _is_archive_plugin_source(source_path):
            shutil.rmtree(staged_dir, ignore_errors=True)
        if not staged_dir.exists():
            shutil.copytree(module_dir, staged_dir)
        init_file = staged_dir / '__init__.py'
        init_file.write_text('from .__main__ import *\n', encoding='utf-8')
        importlib.invalidate_caches()
        _clear_plugin_package_modules(module_name)
        return importlib.import_module(f'{module_name}.__main__')


def _ensure_plugin_importable_root() -> Path:
    import_root = _PLUGIN_IMPORTABLE_DIR.resolve()
    import_root.mkdir(parents=True, exist_ok=True)
    import_root_str = str(import_root)
    if import_root_str not in sys.path:
        sys.path.insert(0, import_root_str)
    return import_root


def _clear_plugin_package_modules(module_name: str) -> None:
    for loaded_name in tuple(sys.modules):
        if loaded_name == module_name or loaded_name.startswith(f'{module_name}.'):
            sys.modules.pop(loaded_name, None)


def _is_archive_plugin_source(path: Path) -> bool:
    name = path.name.lower()
    return path.is_file() and name.endswith(('.zip', '.tar.gz', '.tgz', '.gz'))


def _collect_plugin_classes_from_module(module: ModuleType, *, validate_platform: bool = True) -> tuple[PluginClass, ...]:
    loaded: list[PluginClass] = []
    for _, obj in sorted(module.__dict__.items(), key=lambda item: item[0]):
        if not isinstance(obj, type):
            continue
        if getattr(obj, '__module__', None) != module.__name__:
            continue
        try:
            plugin_class = _validate_plugin_class(obj, validate_platform=validate_platform)
        except TypeError:
            continue
        loaded.append(plugin_class)

    if not loaded:
        raise ValueError(f'No plugin class found in {module.__name__}.')
    return tuple(loaded)


def _register_plugins_from_module(module: ModuleType, source_path: Path) -> tuple[PluginClass, ...]:
    loaded = [
        _register_plugin_class(plugin_class, source_path=source_path)
        for plugin_class in _collect_plugin_classes_from_module(module)
    ]

    if not loaded:
        raise ValueError(f'No plugin class found in {source_path}.')
    return tuple(loaded)


def _load_plugin_module_from_path(path: Path) -> ModuleType:
    if path.is_file() and path.suffix.lower() == '.py':
        return _load_module_from_python_file(path, path)

    if path.is_dir():
        return _load_module_from_package_dir(path, path)

    if path.is_file() and path.name.lower().endswith(('.zip', '.tar.gz', '.tgz', '.gz')):
        extract_root = _extract_plugin_archive(path)
        entry = _resolve_extracted_plugin_entry(extract_root)
        if entry.is_dir():
            return _load_module_from_package_dir(entry, path)
        return _load_module_from_python_file(entry, path)

    raise ValueError(f'Unsupported plugin path: {path}')


def _load_plugins_from_path(path: Path) -> tuple[PluginClass, ...]:
    module = _load_plugin_module_from_path(path)
    return _register_plugins_from_module(module, path)


def set_plugin_paths_env(plugin_paths: Sequence[str | Path]) -> tuple[str, ...]:
    normalized_paths = tuple(str(path) for path in normalize_plugin_paths(plugin_paths))
    if normalized_paths:
        os.environ[_PLUGIN_PATHS_ENV] = json.dumps(normalized_paths, ensure_ascii=False)
    else:
        os.environ.pop(_PLUGIN_PATHS_ENV, None)
    return normalized_paths


def get_plugin_paths_from_env() -> tuple[Path, ...]:
    raw = str(os.environ.get(_PLUGIN_PATHS_ENV, '') or '').strip()
    if not raw:
        return ()
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError(f'{_PLUGIN_PATHS_ENV} must be a JSON array of plugin paths.')
    return normalize_plugin_paths(payload)


def load_plugins_from_paths(plugin_paths: Sequence[str | Path]) -> tuple[PluginClass, ...]:
    loaded: list[PluginClass] = []
    for path in normalize_plugin_paths(plugin_paths):
        source_key = _plugin_source_key(path)
        if source_key in _loaded_plugin_source_keys:
            loaded.extend(_get_plugins_for_source(path))
            continue
        loaded.extend(_load_plugins_from_path(path))
        _loaded_plugin_source_keys.add(source_key)
    return tuple(loaded)


def configure_runtime_plugin_paths(plugin_paths: Sequence[str | Path], *, load_now: bool = True) -> tuple[PluginClass, ...]:
    set_plugin_paths_env(plugin_paths)
    if not load_now:
        return ()
    return load_plugins_from_env()


def load_plugins_from_env() -> tuple[PluginClass, ...]:
    return load_plugins_from_paths(get_plugin_paths_from_env())


def _register_plugin_class[P: PluginClass](plugin_class: P, *, source_path: Path | None = None) -> P:
    plugin_class = cast(P, _validate_plugin_class(plugin_class))
    plugin_key = get_plugin_key(plugin_class)
    if any(get_plugin_key(item) == plugin_key for item in _registered_plugin_classes):
        raise ValueError(f'Plugin {plugin_key} is already registered.')
    _registered_plugin_classes.append(plugin_class)
    _register_plugin_source(plugin_class, source_path)
    return plugin_class


def _coerce_supported_platforms(
    supported_platform: Platform | Sequence[Platform],
    *,
    error_prefix: str,
) -> tuple[Platform, ...]:
    if isinstance(supported_platform, str):
        supported_platforms = (cast(Platform, supported_platform),)
    elif isinstance(supported_platform, ABCSequence):
        supported_platforms = tuple(cast(Platform, item) for item in supported_platform)
    else:
        raise TypeError(f'{error_prefix} must define SupportedPlatform as a platform string or sequence.')

    if not supported_platforms:
        raise TypeError(f'{error_prefix} must define at least one supported platform.')

    invalid_platforms = [item for item in supported_platforms if item not in _PLATFORMS]
    if invalid_platforms:
        raise TypeError(f'{error_prefix} declares invalid SupportedPlatform values: {invalid_platforms!r}')

    return supported_platforms


def _supported_platforms_for_plugin(plugin_class: type[object]) -> tuple[Platform, ...]:
    return _coerce_supported_platforms(
        getattr(plugin_class, 'SupportedPlatform', 'all'),
        error_prefix=f'Plugin {plugin_class!r}',
    )


def _validate_plugin_class(plugin_class: object, *, validate_platform: bool = True) -> PluginClass:
    if not isinstance(plugin_class, type):
        raise TypeError('Plugin must be registered as a class, not an instance.')

    plugin_type = getattr(plugin_class, 'Type', None)
    if plugin_type not in _PLUGIN_TYPES:
        raise TypeError(f'Invalid plugin type: {plugin_type!r}')

    if getattr(plugin_class, 'Name', None) in (None, ''):
        raise TypeError(f'Plugin {plugin_class!r} must define a non-empty Name.')

    _supported_platforms_for_plugin(plugin_class)
    if validate_platform:
        _validate_plugin_platform(plugin_class)

    create = getattr(plugin_class, 'Create', None)
    if not callable(create):
        raise TypeError(f'Plugin {plugin_class!r} must define classmethod Create().')

    return cast(PluginClass, plugin_class)


def _get_current_platform() -> Platform:
    if sys.platform.startswith('win'):
        return 'windows'
    if sys.platform == 'darwin':
        return 'macos'
    if sys.platform.startswith('linux'):
        return 'linux'
    raise RuntimeError(f'Unsupported host platform: {sys.platform!r}')


def get_current_platform() -> Platform:
    return _get_current_platform()


def is_platform_supported(supported_platform: Platform | Sequence[Platform]) -> bool:
    supported_platforms = _coerce_supported_platforms(
        supported_platform,
        error_prefix='supported_platform',
    )

    return 'all' in supported_platforms or get_current_platform() in supported_platforms


def _validate_plugin_platform(plugin_class: type[object]) -> None:
    supported_platforms = _supported_platforms_for_plugin(plugin_class)

    if 'all' in supported_platforms:
        return

    current_platform = get_current_platform()
    if current_platform not in supported_platforms:
        raise RuntimeError(
            f'Plugin {plugin_class!r} does not support current platform {current_platform!r}. '
            f'SupportedPlatform={supported_platforms!r}'
        )


def _plugin_supports_scope(plugin_class: PluginClass, create_in: CreateIn) -> bool:
    plugin_type = cast(PluginType, plugin_class.Type)
    if create_in == 'main':
        return plugin_type in {'main-only', 'main-and-worker'}
    return plugin_type in {'worker-only', 'main-and-worker'}


def _find_plugin_class(plugin_key: str) -> PluginClass | None:
    for plugin_class in _registered_plugin_classes:
        if get_plugin_key(plugin_class) == plugin_key:
            return plugin_class
    return None


def _resolve_plugin_text(
    value: str | dict['InternalTranslateLang', str] | None,
    lang: str | None,
) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None

    from .translate import normalize_language

    normalized = {
        normalize_language(item_lang): str(item_text).strip()
        for item_lang, item_text in value.items()
        if str(item_text).strip()
    }
    if not normalized:
        return None

    resolved_lang = normalize_language(lang)
    base_lang = resolved_lang.split('-', 1)[0]
    return (
        normalized.get(resolved_lang)
        or normalized.get(base_lang)
        or normalized.get('en')
        or next(iter(normalized.values()), None)
    )


def _resolve_plugin_ui_text(
    lang: str | None,
    *,
    zh_cn: str,
    zh_tw: str,
    en: str,
) -> str:
    from .translate import normalize_language

    resolved_lang = normalize_language(lang)
    if resolved_lang == 'zh-tw':
        return zh_tw
    if resolved_lang == 'en':
        return en
    return zh_cn


def _plugin_has_admin_panel(plugin_class: PluginClass) -> bool:
    if not _plugin_supports_scope(plugin_class, 'worker'):
        return False
    return callable(getattr(plugin_class, 'admin_panel', None))


def _build_plugin_panel_item(plugin_class: PluginClass, lang: str | None) -> PluginPanelItem:
    config_type = getattr(plugin_class, 'ConfigType', None)
    return PluginPanelItem(
        key=get_plugin_key(plugin_class),
        name=_resolve_plugin_text(plugin_class.Name, lang) or get_plugin_key(plugin_class),
        description=_resolve_plugin_text(getattr(plugin_class, 'Description', None), lang),
        type=cast(PluginType, plugin_class.Type),
        has_panel=_plugin_has_admin_panel(plugin_class),
        source_path=str(_get_plugin_source_path(plugin_class)) if _get_plugin_source_path(plugin_class) is not None else None,
        supported_platforms=list(_supported_platforms_for_plugin(plugin_class)),
        has_config=config_type is not None,
        current_config=_get_plugin_config_payload(plugin_class),
        config_fields=list(_build_plugin_config_field_descriptors(config_type)) if config_type is not None else [],
    )


def _build_plugin_config_field_descriptors(config_type: type[BaseModel]) -> tuple[PluginConfigFieldDescriptor, ...]:
    schema = cast(dict[str, Any], _jsonable_value(config_type.model_json_schema()))
    properties = cast(dict[str, dict[str, Any]], schema.get('properties') or {})
    required = {str(item) for item in cast(list[str], schema.get('required') or [])}
    fields: list[PluginConfigFieldDescriptor] = []
    for field_name, model_field in config_type.model_fields.items():
        field_schema = cast(dict[str, Any], _jsonable_value(properties.get(field_name) or {}))
        json_type = field_schema.get('type')
        if isinstance(json_type, list):
            json_type = next((item for item in json_type if item != 'null'), json_type[0] if json_type else None)
        default: Any = None
        has_default = False
        if not model_field.is_required():
            has_default = True
            if model_field.default_factory is not None:
                try:
                    default = model_field.default_factory()
                except Exception:
                    has_default = False
            else:
                default = model_field.default
            if has_default:
                default = _jsonable_value(default)
        fields.append(
            PluginConfigFieldDescriptor(
                name=field_name,
                title=cast(str | None, field_schema.get('title')),
                description=cast(str | None, field_schema.get('description')),
                json_type=cast(str | None, json_type if isinstance(json_type, str) else None),
                format=cast(str | None, field_schema.get('format')),
                required=field_name in required,
                has_default=has_default,
                default=default,
                field_schema=field_schema,
            )
        )
    return tuple(fields)


def _build_plugin_runtime_inspection_item(plugin_class: PluginClass, lang: str | None) -> PluginRuntimeInspectionItem:
    config_type = getattr(plugin_class, 'ConfigType', None)
    config_schema: dict[str, Any] | None = None
    config_fields: tuple[PluginConfigFieldDescriptor, ...] = ()
    if config_type is not None:
        config_schema = cast(dict[str, Any], _jsonable_value(config_type.model_json_schema()))
        config_fields = _build_plugin_config_field_descriptors(config_type)
    return PluginRuntimeInspectionItem(
        key=get_plugin_key(plugin_class),
        name=_resolve_plugin_text(plugin_class.Name, lang) or get_plugin_key(plugin_class),
        description=_resolve_plugin_text(getattr(plugin_class, 'Description', None), lang),
        type=cast(PluginType, plugin_class.Type),
        supported_platforms=list(_supported_platforms_for_plugin(plugin_class)),
        has_panel=_plugin_has_admin_panel(plugin_class),
        has_config=config_type is not None,
        config_schema=config_schema,
        config_fields=list(config_fields),
    )


def list_plugin_panels(lang: str | None = None) -> tuple[PluginPanelItem, ...]:
    return tuple(_build_plugin_panel_item(plugin_class, lang) for plugin_class in _registered_plugin_classes)


def inspect_plugin_path(path: str | Path, lang: str | None = None) -> PluginRuntimeInspectResponse:
    plugin_path = _normalize_plugin_path(path)
    plugin_classes = _get_plugins_for_source(plugin_path)
    if not plugin_classes:
        module = _load_plugin_module_from_path(plugin_path)
        plugin_classes = _collect_plugin_classes_from_module(module, validate_platform=False)
    plugin_keys, plugin_types = _plugin_scope_flags(plugin_classes)
    return PluginRuntimeInspectResponse(
        path=str(plugin_path),
        plugin_keys=plugin_keys,
        plugin_types=plugin_types,
        plugins=[_build_plugin_runtime_inspection_item(plugin_class, lang) for plugin_class in plugin_classes],
    )


def _get_plugin_config(plugin_class: PluginClass) -> PluginConfig:
    raw_config = _plugin_configs.get(get_plugin_key(plugin_class))
    config_type = getattr(plugin_class, 'ConfigType', None)
    if config_type is None or raw_config is None:
        return raw_config
    if isinstance(raw_config, config_type):
        return raw_config
    payload: BaseModel | dict[str, Any]
    if isinstance(raw_config, BaseModel):
        payload = raw_config.model_dump(mode='python')
    else:
        payload = raw_config
    return config_type.model_validate(payload)


def get_core_module() -> CoreModule:
    global _core_module
    if _core_module is None:
        _core_module = importlib.import_module('core')
    return _core_module


async def _await_if_needed(value: object) -> object:
    if inspect.isawaitable(value):
        return await cast(Awaitable[object], value)
    return value


def _validate_plugin_instance(plugin_class: PluginClass, instance: object, create_in: CreateIn) -> Plugin:
    return cast(Plugin, instance)


def _get_optional_hook(instance: object, hook_name: str) -> Any | None:
    hook = getattr(instance, hook_name, None)
    return hook if callable(hook) else None


def _build_plugin_placeholder_html(
    title: str,
    message: str,
    description: str | None = None,
    *,
    lang: str | None = None,
) -> HTML:
    header = f'<div class="plugin-empty-title">{escape(title)}</div>'
    subtitle = f'<div class="plugin-empty-subtitle">{escape(description)}</div>' if description else ''
    body = f'<div class="plugin-empty-message">{escape(message)}</div>'
    html_lang = 'zh-CN'
    if lang == 'zh-tw':
        html_lang = 'zh-TW'
    elif lang == 'en':
        html_lang = 'en'
    return (
        f'<!DOCTYPE html><html lang="{html_lang}"><head><meta charset="UTF-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        '<title>Plugin Panel</title>'
        '<style>'
        ':root { color-scheme: light dark; }'
        'html, body { margin: 0; min-height: 100%; font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }'
        'body { background: #f4f7fb; color: #172033; }'
        '.plugin-empty-shell { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; }'
        '.plugin-empty-card { width: min(720px, 100%); border-radius: 18px; padding: 28px; background: rgba(255,255,255,0.92); border: 1px solid rgba(148,163,184,0.28); box-shadow: 0 18px 48px rgba(15,23,42,0.08); }'
        '.plugin-empty-kicker { font-size: 11px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; color: #64748b; }'
        '.plugin-empty-title { margin-top: 10px; font-size: 24px; font-weight: 700; color: #0f172a; }'
        '.plugin-empty-subtitle { margin-top: 8px; font-size: 14px; line-height: 1.65; color: #475569; }'
        '.plugin-empty-message { margin-top: 18px; padding: 14px 16px; border-radius: 14px; background: rgba(226,232,240,0.6); color: #334155; line-height: 1.7; }'
        'html.dark body { background: #0f172a; color: #e2e8f0; }'
        'html.dark .plugin-empty-card { background: rgba(15,23,42,0.92); border-color: rgba(148,163,184,0.18); box-shadow: 0 18px 48px rgba(2,6,23,0.38); }'
        'html.dark .plugin-empty-kicker { color: #94a3b8; }'
        'html.dark .plugin-empty-title { color: #f8fafc; }'
        'html.dark .plugin-empty-subtitle { color: #cbd5e1; }'
        'html.dark .plugin-empty-message { background: rgba(30,41,59,0.9); color: #e2e8f0; }'
        '</style></head><body>'
        '<div class="plugin-empty-shell"><section class="plugin-empty-card">'
        '<div class="plugin-empty-kicker">Plugin</div>'
        f'{header}{subtitle}{body}'
        '</section></div>'
        '<script>'
        '(function(){'
        'function applySync(data){ if(!data || typeof data !== "object") return; if(Object.prototype.hasOwnProperty.call(data, "dark")) document.documentElement.classList.toggle("dark", !!data.dark); if(data.lang){ document.documentElement.lang = String(data.lang).toLowerCase() === "zh-tw" ? "zh-TW" : String(data.lang).toLowerCase() === "en" ? "en" : "zh-CN"; }}'
        'window.addEventListener("message", function(event){ var data = event && event.data; if (!data || typeof data !== "object") return; if (data.type === "proj-sync" || data.type === "proj-set-dark" || data.type === "proj-set-lang") applySync(data); });'
        '})();'
        '</script></body></html>'
    )


async def render_plugin_panel(plugin_key: str, lang: str | None = None) -> HTML:
    plugin_class = _find_plugin_class(plugin_key)
    if plugin_class is None:
        raise HTTPException(404, 'Plugin not found')

    plugin_info = _build_plugin_panel_item(plugin_class, lang)
    if not _plugin_supports_scope(plugin_class, 'worker'):
        message = _resolve_plugin_ui_text(
            lang,
            zh_cn='这个插件只在主进程中运行，不提供 worker 侧管理面板。',
            zh_tw='這個插件只在主行程中運行，不提供 worker 側管理面板。',
            en='This plugin runs only in the main process and does not expose a worker-side admin panel.',
        )
        return _build_plugin_placeholder_html(
            plugin_info.name,
            message,
            plugin_info.description,
            lang=lang,
        )

    try:
        instance = await _ensure_plugin_instance(plugin_class, 'worker')
        hook = _get_optional_hook(instance, 'admin_panel')
        if hook is None:
            message = _resolve_plugin_ui_text(
                lang,
                zh_cn='这个插件没有声明可展示的管理面板。',
                zh_tw='這個插件沒有宣告可展示的管理面板。',
                en='This plugin does not expose an admin panel.',
            )
            return _build_plugin_placeholder_html(
                plugin_info.name,
                message,
                plugin_info.description,
                lang=lang,
            )
        html = str(await _await_if_needed(hook()) or '').strip()
    except Exception:
        logger.exception('Failed to render admin panel for plugin %s.', plugin_key)
        message = _resolve_plugin_ui_text(
            lang,
            zh_cn='这个插件面板渲染失败了，请检查后端日志。',
            zh_tw='這個插件面板渲染失敗了，請檢查後端日誌。',
            en='Failed to render this plugin panel. Check the server log for details.',
        )
        return _build_plugin_placeholder_html(
            plugin_info.name,
            message,
            plugin_info.description,
            lang=lang,
        )

    if not html:
        message = _resolve_plugin_ui_text(
            lang,
            zh_cn='这个插件返回了空的面板内容。',
            zh_tw='這個插件回傳了空的面板內容。',
            en='This plugin returned no panel content.',
        )
        return _build_plugin_placeholder_html(
            plugin_info.name,
            message,
            plugin_info.description,
            lang=lang,
        )
    return html


async def _create_plugin_instance(plugin_class: PluginClass, create_in: CreateIn) -> Plugin:
    instance = await _await_if_needed(
        plugin_class.Create(
            create_in,
            _get_plugin_config(plugin_class),
            core_module=get_core_module(),
        )
    )
    return _validate_plugin_instance(plugin_class, instance, create_in)


async def _ensure_plugin_instance(plugin_class: PluginClass, create_in: CreateIn) -> Plugin:
    plugin_key = get_plugin_key(plugin_class)
    instance = _plugin_instances[create_in].get(plugin_key)
    if instance is not None:
        return instance
    instance = await _create_plugin_instance(plugin_class, create_in)
    _plugin_instances[create_in][plugin_key] = instance
    return instance


def register_plugin[P: PluginClass](plugin_class: P) -> P:
    return _register_plugin_class(plugin_class)


def configure_plugin(plugin_class: PluginClass | str, config: PluginConfig) -> None:
    plugin_key = plugin_class if isinstance(plugin_class, str) else get_plugin_key(_validate_plugin_class(plugin_class))
    _plugin_configs[plugin_key] = config


def configure_plugins(configs: Mapping[PluginClass | str, PluginConfig]) -> None:
    for plugin_class, config in configs.items():
        configure_plugin(plugin_class, config)


def get_registered_plugins() -> tuple[PluginClass, ...]:
    return tuple(_registered_plugin_classes)


def get_plugin_instance(plugin_class: PluginClass, create_in: CreateIn) -> Plugin | None:
    return _plugin_instances[create_in].get(get_plugin_key(_validate_plugin_class(plugin_class)))


async def _start_plugin(plugin_class: PluginClass, create_in: CreateIn, app: FastAPI | None = None) -> None:
    if not _plugin_supports_scope(plugin_class, create_in):
        return
    plugin_key = get_plugin_key(plugin_class)
    if plugin_key in _started_plugin_keys[create_in]:
        return
    instance = await _ensure_plugin_instance(plugin_class, create_in)
    if create_in == 'main':
        hook = _get_optional_hook(instance, 'on_main_start')
        if hook is not None:
            await _await_if_needed(hook())
    else:
        if app is None:
            raise RuntimeError('Worker plugins require a FastAPI app instance during startup.')
        hook = _get_optional_hook(instance, 'on_app_start')
        if hook is not None:
            await _await_if_needed(hook(app))
    _started_plugin_keys[create_in].append(plugin_key)


async def _stop_plugin(plugin_class: PluginClass, create_in: CreateIn, app: FastAPI | None = None) -> None:
    plugin_key = get_plugin_key(plugin_class)
    instance = _plugin_instances[create_in].get(plugin_key)
    started = plugin_key in _started_plugin_keys[create_in]
    if started:
        _started_plugin_keys[create_in] = [key for key in _started_plugin_keys[create_in] if key != plugin_key]
    if instance is None:
        return
    try:
        if started:
            if create_in == 'main':
                hook = _get_optional_hook(instance, 'on_main_stop')
                if hook is not None:
                    await _await_if_needed(hook())
            else:
                if app is None:
                    raise RuntimeError('Worker plugins require a FastAPI app instance during shutdown.')
                hook = _get_optional_hook(instance, 'on_app_shutdown')
                if hook is not None:
                    await _await_if_needed(hook(app))
    finally:
        _plugin_instances[create_in].pop(plugin_key, None)


def _unregister_plugin_class(plugin_class: PluginClass) -> None:
    plugin_key = get_plugin_key(plugin_class)
    _registered_plugin_classes[:] = [item for item in _registered_plugin_classes if get_plugin_key(item) != plugin_key]
    _plugin_configs.pop(plugin_key, None)
    source_key = _plugin_source_keys_by_plugin_key.pop(plugin_key, None)
    if source_key is not None:
        plugin_keys = [key for key in _plugin_keys_by_source_key.get(source_key, []) if key != plugin_key]
        if plugin_keys:
            _plugin_keys_by_source_key[source_key] = plugin_keys
        else:
            _plugin_keys_by_source_key.pop(source_key, None)
            _plugin_paths_by_source_key.pop(source_key, None)
            _loaded_plugin_source_keys.discard(source_key)


def clear_plugins() -> None:
    _registered_plugin_classes.clear()
    _plugin_configs.clear()
    _plugin_source_keys_by_plugin_key.clear()
    _plugin_paths_by_source_key.clear()
    _plugin_keys_by_source_key.clear()
    _loaded_plugin_source_keys.clear()
    for scope in ('main', 'worker'):
        _plugin_instances[scope].clear()
        _started_plugin_keys[scope].clear()


async def ensure_plugins(create_in: CreateIn) -> tuple[Plugin, ...]:
    instances: list[Plugin] = []
    for plugin_class in _registered_plugin_classes:
        if not _plugin_supports_scope(plugin_class, create_in):
            continue
        instances.append(await _ensure_plugin_instance(plugin_class, create_in))
    return tuple(instances)


async def start_plugins(create_in: CreateIn, app: FastAPI | None = None) -> None:
    for plugin_class in _registered_plugin_classes:
        try:
            await _start_plugin(plugin_class, create_in, app)
        except Exception:
            logger.exception('Failed to start plugin %s in %s.', get_plugin_key(plugin_class), create_in)


async def stop_plugins(create_in: CreateIn, app: FastAPI | None = None) -> None:
    started_keys = list(reversed(_started_plugin_keys[create_in]))
    for plugin_key in started_keys:
        plugin_class = _find_plugin_class(plugin_key)
        if plugin_class is None:
            continue
        try:
            await _stop_plugin(plugin_class, create_in, app)
        except Exception:
            logger.exception('Failed to stop plugin %s in %s.', plugin_key, create_in)


def _resolve_runtime_plugin_configs(
    plugin_classes: Sequence[PluginClass],
    *,
    shared_config: Mapping[str, Any] | None,
    plugin_configs: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    raw_plugin_configs = plugin_configs or {}
    for plugin_class in plugin_classes:
        plugin_key = get_plugin_key(plugin_class)
        payload = raw_plugin_configs.get(plugin_key)
        if payload is None and shared_config is not None:
            payload = shared_config
        if payload is None:
            continue
        resolved[plugin_key] = cast(dict[str, Any], _jsonable_value(dict(payload)))
    return resolved


def _apply_runtime_plugin_configs(
    plugin_classes: Sequence[PluginClass],
    runtime_plugin_configs: Mapping[str, Mapping[str, Any]],
) -> None:
    for plugin_class in plugin_classes:
        plugin_key = get_plugin_key(plugin_class)
        payload = runtime_plugin_configs.get(plugin_key)
        if payload is None:
            continue
        configure_plugin(plugin_class, dict(payload))


async def _apply_local_main_plugin_action(
    action: PluginRuntimeAction,
    path: str | Path,
    *,
    shared_config: Mapping[str, Any] | None = None,
    plugin_configs: Mapping[str, Mapping[str, Any]] | None = None,
) -> PluginRuntimeProcessResult:
    plugin_path = _normalize_plugin_path(path)
    plugin_classes = _get_plugins_for_source(plugin_path)
    if action == 'register':
        plugin_classes = load_plugins_from_paths([plugin_path])
        _apply_runtime_plugin_configs(
            plugin_classes,
            _resolve_runtime_plugin_configs(plugin_classes, shared_config=shared_config, plugin_configs=plugin_configs),
        )
        for plugin_class in plugin_classes:
            if _plugin_supports_scope(plugin_class, 'main'):
                await _start_plugin(plugin_class, 'main')
        current_paths = set(_current_plugin_paths())
        current_paths.add(plugin_path)
        _update_current_process_plugin_paths(sorted(current_paths, key=str))
    else:
        for plugin_class in reversed(plugin_classes):
            if _plugin_supports_scope(plugin_class, 'main'):
                await _stop_plugin(plugin_class, 'main')
        for plugin_class in reversed(plugin_classes):
            _unregister_plugin_class(plugin_class)
        _update_current_process_plugin_paths([item for item in _current_plugin_paths() if item != plugin_path])
        _forget_plugin_source(plugin_path)

    plugin_keys, plugin_types = _plugin_scope_flags(plugin_classes)
    return PluginRuntimeProcessResult(
        ok=True,
        pid=os.getpid(),
        stage='main',
        action=action,
        path=str(plugin_path),
        plugin_keys=plugin_keys,
        plugin_types=plugin_types,
    )


async def _apply_local_worker_plugin_action(
    action: PluginRuntimeAction,
    path: str | Path,
    app: FastAPI,
    *,
    shared_config: Mapping[str, Any] | None = None,
    plugin_configs: Mapping[str, Mapping[str, Any]] | None = None,
) -> PluginRuntimeProcessResult:
    plugin_path = _normalize_plugin_path(path)
    plugin_classes = _get_plugins_for_source(plugin_path)
    if action == 'register':
        plugin_classes = load_plugins_from_paths([plugin_path])
        _apply_runtime_plugin_configs(
            plugin_classes,
            _resolve_runtime_plugin_configs(plugin_classes, shared_config=shared_config, plugin_configs=plugin_configs),
        )
        for plugin_class in plugin_classes:
            if _plugin_supports_scope(plugin_class, 'worker'):
                await _start_plugin(plugin_class, 'worker', app)
        current_paths = set(_current_plugin_paths())
        current_paths.add(plugin_path)
        _update_current_process_plugin_paths(sorted(current_paths, key=str))
    else:
        for plugin_class in reversed(plugin_classes):
            if _plugin_supports_scope(plugin_class, 'worker'):
                await _stop_plugin(plugin_class, 'worker', app)
        for plugin_class in reversed(plugin_classes):
            _unregister_plugin_class(plugin_class)
        _update_current_process_plugin_paths([item for item in _current_plugin_paths() if item != plugin_path])
        _forget_plugin_source(plugin_path)

    plugin_keys, plugin_types = _plugin_scope_flags(plugin_classes)
    return PluginRuntimeProcessResult(
        ok=True,
        pid=os.getpid(),
        stage='worker',
        action=action,
        path=str(plugin_path),
        plugin_keys=plugin_keys,
        plugin_types=plugin_types,
    )


async def _apply_local_main_registered_plugin_action(
    action: Literal['restart', 'delete'],
    plugin_key: str,
    *,
    shared_config: Mapping[str, Any] | None = None,
) -> PluginRuntimeProcessResult:
    plugin_class = _find_plugin_class(plugin_key)
    if plugin_class is None:
        raise ValueError(f'Plugin not found: {plugin_key}')
    plugin_path = _get_plugin_source_path(plugin_class)
    if shared_config is not None:
        configure_plugin(plugin_class, dict(shared_config))
    if action == 'restart':
        if _plugin_supports_scope(plugin_class, 'main'):
            await _stop_plugin(plugin_class, 'main')
            await _start_plugin(plugin_class, 'main')
    else:
        if _plugin_supports_scope(plugin_class, 'main'):
            await _stop_plugin(plugin_class, 'main')
        _unregister_plugin_class(plugin_class)
        if plugin_path is not None and not _get_plugins_for_source(plugin_path):
            _update_current_process_plugin_paths([item for item in _current_plugin_paths() if item != plugin_path])
            _forget_plugin_source(plugin_path)
    return PluginRuntimeProcessResult(
        ok=True,
        pid=os.getpid(),
        stage='main',
        action=action,
        path=str(plugin_path or ''),
        plugin_keys=[plugin_key],
        plugin_types=[cast(PluginType, plugin_class.Type)],
    )


async def _apply_local_worker_registered_plugin_action(
    action: Literal['restart', 'delete'],
    plugin_key: str,
    app: FastAPI,
    *,
    shared_config: Mapping[str, Any] | None = None,
    unregister: bool = True,
) -> PluginRuntimeProcessResult:
    plugin_class = _find_plugin_class(plugin_key)
    if plugin_class is None:
        raise ValueError(f'Plugin not found: {plugin_key}')
    plugin_path = _get_plugin_source_path(plugin_class)
    if shared_config is not None:
        configure_plugin(plugin_class, dict(shared_config))
    if action == 'restart':
        if _plugin_supports_scope(plugin_class, 'worker'):
            await _stop_plugin(plugin_class, 'worker', app)
            await _start_plugin(plugin_class, 'worker', app)
    else:
        if _plugin_supports_scope(plugin_class, 'worker'):
            await _stop_plugin(plugin_class, 'worker', app)
        if unregister:
            _unregister_plugin_class(plugin_class)
            if plugin_path is not None and not _get_plugins_for_source(plugin_path):
                _update_current_process_plugin_paths([item for item in _current_plugin_paths() if item != plugin_path])
                _forget_plugin_source(plugin_path)
    return PluginRuntimeProcessResult(
        ok=True,
        pid=os.getpid(),
        stage='worker',
        action=action,
        path=str(plugin_path or ''),
        plugin_keys=[plugin_key],
        plugin_types=[cast(PluginType, plugin_class.Type)],
    )


def _request_main_plugin_action(
    action: PluginRuntimeAction,
    path: str | Path,
    *,
    shared_config: Mapping[str, Any] | None = None,
    plugin_configs: Mapping[str, Mapping[str, Any]] | None = None,
) -> PluginRuntimeProcessResult:
    host = str(os.getenv(_PLUGIN_CONTROL_HOST_ENV, '') or '').strip()
    port_text = str(os.getenv(_PLUGIN_CONTROL_PORT_ENV, '') or '').strip()
    token = str(os.getenv(_PLUGIN_CONTROL_TOKEN_ENV, '') or '').strip()
    if not host or not port_text or not token:
        return run_any_func(_apply_local_main_plugin_action, action, path, shared_config=shared_config, plugin_configs=plugin_configs)

    with socket.create_connection((host, int(port_text)), timeout=1.5) as conn:
        conn.sendall((json.dumps({
            'token': token,
            'action': action,
            'path': str(_normalize_plugin_path(path)),
            'config': _jsonable_value(shared_config),
            'plugin_configs': _jsonable_value(plugin_configs),
        }, ensure_ascii=False) + '\n').encode('utf-8'))
        with contextlib.suppress(OSError):
            conn.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            data = conn.recv(4096)
            if not data:
                break
            chunks.append(data)
    payload = json.loads(b''.join(chunks).decode('utf-8').strip() or '{}')
    if not isinstance(payload, dict) or not payload.get('ok'):
        raise RuntimeError(str((payload or {}).get('error') or 'Main plugin runtime request failed.'))
    return PluginRuntimeProcessResult.model_validate(payload.get('result') or {})


def _request_main_registered_plugin_action(
    action: Literal['restart', 'delete'],
    plugin_key: str,
    *,
    shared_config: Mapping[str, Any] | None = None,
) -> PluginRuntimeProcessResult:
    host = str(os.getenv(_PLUGIN_CONTROL_HOST_ENV, '') or '').strip()
    port_text = str(os.getenv(_PLUGIN_CONTROL_PORT_ENV, '') or '').strip()
    token = str(os.getenv(_PLUGIN_CONTROL_TOKEN_ENV, '') or '').strip()
    if not host or not port_text or not token:
        return run_any_func(_apply_local_main_registered_plugin_action, action, plugin_key, shared_config=shared_config)

    with socket.create_connection((host, int(port_text)), timeout=1.5) as conn:
        conn.sendall((json.dumps({
            'token': token,
            'action': action,
            'plugin_key': plugin_key,
            'config': _jsonable_value(shared_config),
        }, ensure_ascii=False) + '\n').encode('utf-8'))
        with contextlib.suppress(OSError):
            conn.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            data = conn.recv(4096)
            if not data:
                break
            chunks.append(data)
    payload = json.loads(b''.join(chunks).decode('utf-8').strip() or '{}')
    if not isinstance(payload, dict) or not payload.get('ok'):
        raise RuntimeError(str((payload or {}).get('error') or 'Main plugin runtime request failed.'))
    return PluginRuntimeProcessResult.model_validate(payload.get('result') or {})


def _main_plugin_control_available() -> bool:
    host = str(os.getenv(_PLUGIN_CONTROL_HOST_ENV, '') or '').strip()
    port_text = str(os.getenv(_PLUGIN_CONTROL_PORT_ENV, '') or '').strip()
    token = str(os.getenv(_PLUGIN_CONTROL_TOKEN_ENV, '') or '').strip()
    return bool(host and port_text and token)


async def _broadcast_worker_plugin_action(
    action: PluginRuntimeAction,
    path: str | Path,
    app: FastAPI,
    *,
    shared_config: Mapping[str, Any] | None = None,
    plugin_configs: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[PluginRuntimeProcessResult]:
    from .app import send_message_to_worker
    from .shared import AppSharedData, WorkerPluginRuntimeMessage

    shared = AppSharedData.Get()
    worker_ids = [int(row['pid']) for row in shared.get_workers_snapshot() if row.get('pid')]
    if not worker_ids:
        worker_ids = [os.getpid()]

    async def _broadcast_one(pid: int) -> PluginRuntimeProcessResult:
        if pid == os.getpid():
            return await _apply_local_worker_plugin_action(
                action,
                path,
                app,
                shared_config=shared_config,
                plugin_configs=plugin_configs,
            )
        try:
            result = await send_message_to_worker(
                pid,
                WorkerPluginRuntimeMessage(
                    sender=os.getpid(),
                    action=action,
                    path=str(_normalize_plugin_path(path)),
                    config=cast(dict[str, object] | None, _jsonable_value(shared_config)),
                    plugin_configs=cast(dict[str, dict[str, object]], _jsonable_value(plugin_configs or {})),
                ),
            )
            return PluginRuntimeProcessResult.model_validate(result)
        except Exception as exc:
            return PluginRuntimeProcessResult(
                ok=False,
                pid=pid,
                stage='worker',
                action=action,
                path=str(_normalize_plugin_path(path)),
                error=str(exc),
            )

    return await asyncio.gather(*(_broadcast_one(pid) for pid in worker_ids))


async def _broadcast_worker_registered_plugin_action(
    action: Literal['restart', 'delete'],
    plugin_key: str,
    app: FastAPI,
    *,
    shared_config: Mapping[str, Any] | None = None,
) -> list[PluginRuntimeProcessResult]:
    from .app import send_message_to_worker
    from .shared import AppSharedData, WorkerPluginRuntimeMessage

    shared = AppSharedData.Get()
    worker_ids = [int(row['pid']) for row in shared.get_workers_snapshot() if row.get('pid')]
    if not worker_ids:
        worker_ids = [os.getpid()]

    async def _broadcast_one(pid: int) -> PluginRuntimeProcessResult:
        if pid == os.getpid():
            return await _apply_local_worker_registered_plugin_action(action, plugin_key, app, shared_config=shared_config)
        try:
            result = await send_message_to_worker(
                pid,
                WorkerPluginRuntimeMessage(
                    sender=os.getpid(),
                    action=action,
                    path='',
                    plugin_key=plugin_key,
                    config=cast(dict[str, object] | None, _jsonable_value(shared_config)),
                ),
            )
            return PluginRuntimeProcessResult.model_validate(result)
        except Exception as exc:
            plugin_class = _find_plugin_class(plugin_key)
            return PluginRuntimeProcessResult(
                ok=False,
                pid=pid,
                stage='worker',
                action=action,
                path=str(_get_plugin_source_path(plugin_key) or ''),
                plugin_keys=[plugin_key],
                plugin_types=[cast(PluginType, plugin_class.Type)] if plugin_class is not None else [],
                error=str(exc),
            )

    return await asyncio.gather(*(_broadcast_one(pid) for pid in worker_ids))


async def apply_registered_plugin_action(
    action: Literal['restart', 'delete'],
    plugin_key: str,
    *,
    app: FastAPI | None = None,
    persist_to_config: bool = True,
    shared_config: Mapping[str, Any] | None = None,
) -> PluginRegisteredRuntimeResponse:
    plugin_class = _find_plugin_class(plugin_key)
    if plugin_class is None:
        raise ValueError(f'Plugin not found: {plugin_key}')
    plugin_type = cast(PluginType, plugin_class.Type)
    plugin_path = _get_plugin_source_path(plugin_class)

    if action == 'delete' and not _main_plugin_control_available() and app is not None:
        results: list[PluginRuntimeProcessResult] = []
        if _plugin_supports_scope(plugin_class, 'worker'):
            results.append(await _apply_local_worker_registered_plugin_action('delete', plugin_key, app, shared_config=shared_config, unregister=False))
        results.insert(0, await _apply_local_main_registered_plugin_action('delete', plugin_key, shared_config=shared_config))
        saved_path: str | None = None
        if persist_to_config:
            saved_path = _persist_runtime_plugin_paths(_current_plugin_paths())
        return PluginRegisteredRuntimeResponse(
            saved=persist_to_config,
            file_path=saved_path,
            action=action,
            plugin_key=plugin_key,
            path=str(plugin_path) if plugin_path is not None else None,
            plugin_type=plugin_type,
            results=results,
        )

    main_result = _request_main_registered_plugin_action(action, plugin_key, shared_config=shared_config)
    results = [main_result]
    if _plugin_supports_scope(plugin_class, 'worker'):
        if app is None:
            raise RuntimeError('Registered worker plugin action requires a FastAPI app instance.')
        worker_results = await _broadcast_worker_registered_plugin_action(action, plugin_key, app, shared_config=shared_config)
        results.extend(worker_results)
        failures = [row for row in worker_results if not row.ok]
        if failures:
            raise RuntimeError('; '.join(row.error or f'worker {row.pid} failed' for row in failures))

    saved_path: str | None = None
    if persist_to_config:
        saved_path = _persist_runtime_plugin_paths(_current_plugin_paths())
    return PluginRegisteredRuntimeResponse(
        saved=persist_to_config,
        file_path=saved_path,
        action=action,
        plugin_key=plugin_key,
        path=str(plugin_path) if plugin_path is not None else None,
        plugin_type=plugin_type,
        results=results,
    )


async def apply_runtime_plugin_action(
    action: PluginRuntimeAction,
    path: str | Path,
    *,
    app: FastAPI | None = None,
    persist_to_config: bool = True,
    shared_config: Mapping[str, Any] | None = None,
    plugin_configs: Mapping[str, Mapping[str, Any]] | None = None,
) -> PluginRuntimeResponse:
    plugin_path = _normalize_plugin_path(path)

    if action == 'delete' and not _main_plugin_control_available() and app is not None:
        plugin_classes = _get_plugins_for_source(plugin_path)
        plugin_keys, plugin_types = _plugin_scope_flags(plugin_classes)
        results: list[PluginRuntimeProcessResult] = []
        if _plugin_types_include_scope(plugin_types, 'worker'):
            for plugin_class in reversed(plugin_classes):
                if _plugin_supports_scope(plugin_class, 'worker'):
                    await _stop_plugin(plugin_class, 'worker', app)
            results.append(
                PluginRuntimeProcessResult(
                    ok=True,
                    pid=os.getpid(),
                    stage='worker',
                    action=action,
                    path=str(plugin_path),
                    plugin_keys=plugin_keys,
                    plugin_types=plugin_types,
                )
            )
        if _plugin_types_include_scope(plugin_types, 'main'):
            for plugin_class in reversed(plugin_classes):
                if _plugin_supports_scope(plugin_class, 'main'):
                    await _stop_plugin(plugin_class, 'main')
        for plugin_class in reversed(plugin_classes):
            _unregister_plugin_class(plugin_class)
        _update_current_process_plugin_paths([item for item in _current_plugin_paths() if item != plugin_path])
        _forget_plugin_source(plugin_path)
        main_result = PluginRuntimeProcessResult(
            ok=True,
            pid=os.getpid(),
            stage='main',
            action=action,
            path=str(plugin_path),
            plugin_keys=plugin_keys,
            plugin_types=plugin_types,
        )
        results.insert(0, main_result)
        saved_path: str | None = None
        if persist_to_config:
            saved_path = _persist_runtime_plugin_paths([item for item in _current_plugin_paths() if item != plugin_path])
        return PluginRuntimeResponse(
            saved=persist_to_config,
            file_path=saved_path,
            action=action,
            path=str(plugin_path),
            plugin_keys=plugin_keys,
            plugin_types=plugin_types,
            results=results,
        )

    main_result = _request_main_plugin_action(
        action,
        plugin_path,
        shared_config=shared_config,
        plugin_configs=plugin_configs,
    )
    results = [main_result]
    plugin_keys = list(main_result.plugin_keys)
    plugin_types = list(main_result.plugin_types)

    if _plugin_types_include_scope(plugin_types, 'worker'):
        if app is None:
            raise RuntimeError('Dynamic worker plugin action requires a FastAPI app instance.')
        worker_results = await _broadcast_worker_plugin_action(
            action,
            plugin_path,
            app,
            shared_config=shared_config,
            plugin_configs=plugin_configs,
        )
        results.extend(worker_results)
        failures = [row for row in worker_results if not row.ok]
        if failures:
            raise RuntimeError('; '.join(row.error or f'worker {row.pid} failed' for row in failures))

    saved_path: str | None = None
    if persist_to_config:
        if action == 'register':
            current_paths = set(_current_plugin_paths())
            current_paths.add(plugin_path)
            saved_path = _persist_runtime_plugin_paths(sorted(current_paths, key=str))
        else:
            saved_path = _persist_runtime_plugin_paths([item for item in _current_plugin_paths() if item != plugin_path])

    return PluginRuntimeResponse(
        saved=persist_to_config,
        file_path=saved_path,
        action=action,
        path=str(plugin_path),
        plugin_keys=plugin_keys,
        plugin_types=plugin_types,
        results=results,
    )


def _is_local_request(request: Request) -> bool:
    host = (request.client.host if request.client else '') if request is not None else ''
    host = (host or '').strip().lower()
    return not host or host in _LOCAL_HOSTS


def _ensure_local_request(request: Request) -> None:
    if not _is_local_request(request):
        raise HTTPException(403, '')


@on_main_process_starts_event
async def _start_registered_main_plugins() -> None:
    await start_plugins('main')


@on_main_process_stops_event
async def _stop_registered_main_plugins() -> None:
    await stop_plugins('main')


@on_before_app_created
async def _start_registered_worker_plugins(app: FastAPI) -> None:
    await start_plugins('worker', app)


@on_app_shutdown
async def _stop_registered_worker_plugins(app: FastAPI) -> None:
    await stop_plugins('worker', app)

def register_plugin_panel_routes(app: FastAPI) -> None:
    if getattr(app.state, '_plugin_panel_routes_registered', False):
        return
    app.state._plugin_panel_routes_registered = True

    from .data_types.config import Config

    admin_path = Config.GetConfig().server_config.get_internal_admin_path
    plugin_panel_path = get_resources('admin-panel', 'panel', 'plugins.html') or Path('plugins.html')

    @app.get(admin_path('api/plugins'), response_model=PluginPanelListResponse)
    async def panel_plugins_list(lang: str | None = None) -> PluginPanelListResponse:
        return PluginPanelListResponse(plugins=list(list_plugin_panels(lang)))

    @app.post(admin_path('api/plugins/runtime/register'), response_model=PluginRuntimeResponse)
    async def panel_plugins_runtime_register(payload: PluginRuntimeRequest) -> PluginRuntimeResponse:
        return await apply_runtime_plugin_action(
            'register',
            payload.path,
            app=app,
            persist_to_config=True,
            shared_config=payload.config,
            plugin_configs=payload.plugin_configs,
        )

    @app.post(admin_path('api/plugins/runtime/delete'), response_model=PluginRuntimeResponse)
    async def panel_plugins_runtime_delete(payload: PluginRuntimeRequest) -> PluginRuntimeResponse:
        return await apply_runtime_plugin_action('delete', payload.path, app=app, persist_to_config=True)

    @app.post(admin_path('api/plugins/runtime/restart-item'), response_model=PluginRegisteredRuntimeResponse)
    async def panel_plugins_runtime_restart_item(payload: PluginRegisteredRuntimeRequest) -> PluginRegisteredRuntimeResponse:
        return await apply_registered_plugin_action(
            'restart',
            payload.plugin_key,
            app=app,
            persist_to_config=True,
            shared_config=payload.config,
        )

    @app.post(admin_path('api/plugins/runtime/delete-item'), response_model=PluginRegisteredRuntimeResponse)
    async def panel_plugins_runtime_delete_item(payload: PluginRegisteredRuntimeRequest) -> PluginRegisteredRuntimeResponse:
        return await apply_registered_plugin_action(
            'delete',
            payload.plugin_key,
            app=app,
            persist_to_config=True,
            shared_config=payload.config,
        )

    @app.post(admin_path('api/plugins/runtime/inspect'), response_model=PluginRuntimeInspectResponse)
    async def panel_plugins_runtime_inspect(payload: PluginRuntimeRequest, lang: str | None = None) -> PluginRuntimeInspectResponse:
        return inspect_plugin_path(payload.path, lang)

    @app.post(admin_path('api/plugins/runtime/upload'), response_model=PluginUploadRuntimeResponse)
    async def panel_plugins_runtime_upload(
        files: list[UploadFile] = File(...),
        relative_paths_json: str = Form(default='[]'),
        lang: str | None = Form(default=None),
    ) -> PluginUploadRuntimeResponse:
        try:
            raw_relative_paths = json.loads(relative_paths_json or '[]')
        except json.JSONDecodeError as exc:
            raise HTTPException(400, 'relative_paths_json must be valid JSON.') from exc
        if not isinstance(raw_relative_paths, list) or not all(isinstance(item, str) for item in raw_relative_paths):
            raise HTTPException(400, 'relative_paths_json must be a JSON string array.')

        _upload_root, plugin_path = await _store_uploaded_plugin_bundle(files, cast(list[str], raw_relative_paths))
        result = inspect_plugin_path(plugin_path, lang)
        return PluginUploadRuntimeResponse(
            uploaded_path=str(plugin_path),
            **result.model_dump(mode='python'),
        )

    @app.get(admin_path('panel/plugins'), response_class=HTMLResponse)
    async def panel_plugins_html() -> HTMLResponse:
        return html_response_from_path(
            plugin_panel_path,
            not_found_message='panel/plugins.html not found',
        )

    @app.get(admin_path('panel/plugins/view/{plugin_key:path}'), response_class=HTMLResponse, include_in_schema=False)
    async def panel_plugin_view_html(plugin_key: str, lang: str | None = None) -> HTMLResponse:
        html = await render_plugin_panel(plugin_key, lang)
        return html_response_from_content(html, cache_key=f'plugin-panel:{plugin_key}:{lang or ""}')


@on_app_created
def _register_plugin_routes(app: FastAPI) -> None:
    register_plugin_panel_routes(app)
    
__all__ = [
    'PluginBase',
    'MainOnlyPlugin', 
    'WorkerOnlyPlugin',
    'MainAndWorkerPlugin',
    'PluginRuntimeAction',
    'PluginRuntimeProcessResult',
    'PluginRuntimeRequest',
    'PluginConfigFieldDescriptor',
    'PluginRuntimeInspectionItem',
    'PluginRuntimeInspectResponse',
    'PluginRuntimeResponse',
    'PluginRegisteredRuntimeRequest',
    'PluginRegisteredRuntimeResponse',
    'PluginUploadRuntimeResponse',
    'Plugin', 
    'PluginClass',
    'PluginConfig',
    'apply_runtime_plugin_action',
    'apply_registered_plugin_action',
    'clear_plugins',
    'configure_plugin',
    'configure_plugins',
    'configure_runtime_plugin_paths',
    'ensure_plugins',
    'get_core_module',
    'get_current_platform',
    'get_plugin_instance',
    'get_plugin_key',
    'get_plugins_for_path',
    'get_plugin_paths_from_env',
    'get_registered_plugins',
    'inspect_plugin_path',
    'is_platform_supported',
    'list_plugin_panels',
    'load_plugins_from_env',
    'load_plugins_from_paths',
    'normalize_plugin_paths',
    'register_plugin',
    'register_plugin_panel_routes',
    'render_plugin_panel',
    'set_plugin_paths_env',
    'start_plugins',
    'stop_plugins',
]
