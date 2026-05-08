# -*- coding: utf-8 -*-
"""Server entry-point."""

import os
import sys
import asyncio
import logging
import uuid
import json

from pathlib import Path
from dotenv import load_dotenv  # type: ignore

# ensure project root is on sys.path
_server_dir = Path(__file__).resolve().parent
_project_root = _server_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

# mode detection
_curr_filename = "app.__main__"
_in_fastapi = __name__ == _curr_filename                  # imported by uvicorn worker
_in_main = __name__ == "__main__"                         # python -m app

# Publish the main process PID so helper subprocesses can self-terminate if the
# supervisor dies instead of becoming orphaned.
if _in_main:
    os.environ["__SERVER_MAIN_PID__"] = str(os.getpid())

def _load_optional_env_file(path: Path, *, override: bool = False) -> bool:
    if not path.exists() or not path.is_file():
        return False
    load_dotenv(dotenv_path=path, override=override, encoding="utf-8-sig")
    return True

def _load_base_env() -> None:
    env_path = _project_root / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False, encoding="utf-8-sig")
    else:
        load_dotenv(override=False, encoding="utf-8-sig")

def _load_mode_env(mode: str) -> bool:
    normalized = "prod" if str(mode).lower().strip() == "prod" else "dev"
    if normalized == "dev":
        candidates = (
            _project_root / ".dev.env",
            _project_root / ".env.dev",
            _project_root / ".env.development",
            _project_root / ".env.develop",
            _project_root / "env.dev",
            _project_root / "env.development",
            _project_root / "env.develop",
        )
    else:
        candidates = (
            _project_root / ".prod.env",
            _project_root / ".env.prod",
            _project_root / ".env.production",
            _project_root / ".env.product",
            _project_root / "env.prod",
            _project_root / "env.production",
            _project_root / "env.product",
        )

    for candidate in candidates:
        if _load_optional_env_file(candidate, override=False):
            return True
    return False

def _load_server_env(mode: str) -> str:
    normalized = _set_runtime_mode_env(mode)
    _load_mode_env(normalized)
    _load_base_env()
    _ensure_jwt_keys()
    return normalized

def _ensure_jwt_keys() -> None:
    from core.server.security.jwt import ensure_jwt_keys_or_warn
    ensure_jwt_keys_or_warn(_project_root)


def _load_admin_password_runtime_from_env() -> None:
    from core.server.security.admin_password import load_admin_password_state_from_env

    load_admin_password_state_from_env()

def _set_runtime_mode_env(mode: str) -> str:
    normalized = "prod" if str(mode).lower().strip() == "prod" else "dev"
    os.environ["__MODE__"] = normalized
    if normalized == "prod":
        os.environ["__PROD__"] = "1"
        os.environ.pop("__DEV__", None)
    else:
        os.environ["__DEV__"] = "1"
        os.environ.pop("__PROD__", None)
    return normalized

def _ensure_server_instance_env() -> str:
    instance_id = os.getenv("__SERVER_INSTANCE_ID__") or str(uuid.uuid4())
    os.environ["__SERVER_INSTANCE_ID__"] = instance_id
    return instance_id

def _refresh_server_instance_env() -> str:
    instance_id = str(uuid.uuid4())
    os.environ["__SERVER_INSTANCE_ID__"] = instance_id
    return instance_id

def _detect_cli_mode(argv: list[str]) -> str:
    return "prod" if "--production" in argv else "dev"

def _serialize_env_file_value(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)

def _write_temp_env_file(env_values: dict[str, object]) -> str:
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        suffix=".env",
    ) as tmp_env:
        for key, value in env_values.items():
            if value is None:
                continue
            tmp_env.write(f"{key}={_serialize_env_file_value(value)}\n")
        return tmp_env.name

_root_logger = logging.getLogger()
_aiortc_logger = logging.getLogger("aiortc")
_aioice_logger = logging.getLogger("aioice")
_grpc_logger = logging.getLogger("grpc")
_aiortc_logger.setLevel(logging.INFO)
_aioice_logger.setLevel(logging.INFO)
_grpc_logger.setLevel(logging.INFO)

# ══════════════════════════════════════════════════════════════════════════════
# _in_fastapi  — called once per uvicorn worker
# ══════════════════════════════════════════════════════════════════════════════
if _in_fastapi:
    os.environ["IN_FASTAPI_WORKER"] = "1"
    _load_server_env(os.getenv("__MODE__", "dev"))
    _load_admin_password_runtime_from_env()
    _ensure_server_instance_env()
    config_json = os.environ["__CONFIG__"]
    from core.server.data_types.config import Config

    config = Config.model_validate_json(config_json)
    Config.SetConfig(config)
    config.rtc_room_config.apply()
    config.log_config.init_root_logger(_root_logger)
    log_lvl = config.log_config.get_int_log_level()
    if log_lvl > logging.INFO:
        _aiortc_logger.setLevel(log_lvl)
        _aioice_logger.setLevel(log_lvl)
        _grpc_logger.setLevel(log_lvl)

    from core.server.app import create_app
    app = create_app()

# ══════════════════════════════════════════════════════════════════════════════
# _in_main  — CLI entry
# ══════════════════════════════════════════════════════════════════════════════
if _in_main:
    import time
    import signal
    import _thread
    import uvicorn
    import webbrowser
    import threading
    from datetime import datetime, timedelta, timezone

    hk_tz = timezone(timedelta(hours=8), name="Asia/Hong_Kong")
    os.environ["__SERVER_START_TIME__"] = datetime.now(tz=hk_tz).isoformat()
    mode = _load_server_env(_detect_cli_mode(sys.argv[1:]))
    instance_uuid = _ensure_server_instance_env()

    from core.utils.system_utils.system_metrics import start_system_metrics_worker
    from core.storage.config import StorageConfig
    from core.server.constants import SERVER_DIR
    from core.server.data_types.config import Config
    from core.server import runtime_control
    from core.server.storage_utils import run_main_process_orm_preflight, warmup_storage_clients

    parser = Config.BuildArgParser()
    _args = parser.parse_args()
    os.environ["__START_ARGS__"] = json.dumps(sys.argv[1:])

    runtime_config_info = Config.DescribeRuntimeConfigPath(getattr(_args, "config", None), prefer_mode_specific=True)
    runtime_source_text = runtime_config_info.get("source_path")
    runtime_source_path = Path(runtime_source_text) if runtime_source_text else None
    if not getattr(_args, "config", None) and runtime_source_path is not None and runtime_source_path.is_file():
        _args.config = str(runtime_source_path)
        runtime_config_info = Config.DescribeRuntimeConfigPath(_args.config, prefer_mode_specific=True)

    prod = getattr(_args, "production", False)
    mode = _load_server_env("prod" if prod else "dev")
    config = Config.CreateConfigFromArgs(_args)
    storage_config = StorageConfig.Global()
    runtime_config_info = Config.DescribeRuntimeConfigPath(getattr(_args, "config", None), prefer_mode_specific=True)
    if runtime_config_info.get("source_path"):
        os.environ["__CONFIG_FILE_PATH__"] = str(runtime_config_info["source_path"])
    else:
        os.environ.pop("__CONFIG_FILE_PATH__", None)
    os.environ["__WRITABLE_CONFIG_FILE_PATH__"] = str(runtime_config_info["write_path"])
    os.environ["__SERVER_SUPERVISOR_PID__"] = str(os.getpid())
    os.environ["__SERVER_PROCESS_PID__"] = str(os.getpid())
    storage_preflight_map: dict[str, dict[str, list[str]]] = {}
    try:
        storage_preflight_map = asyncio.run(run_main_process_orm_preflight(storage_config, logger=_root_logger))
    except Exception as exc:
        os.environ.pop("__PT_ORM_PREFLIGHT__", None)
        os.environ.pop("__PT_VECTOR_PREFLIGHT__", None)
        _root_logger.warning("Main process storage preflight failed: %s", exc, exc_info=True)
    config.rtc_room_config.apply()
    config.log_config.init_root_logger(_root_logger, default_mode=mode) # type: ignore
    log_lvl = config.log_config.get_int_log_level(default_mode=mode)    # type: ignore
    if log_lvl > logging.INFO:
        _aiortc_logger.setLevel(log_lvl)
        _aioice_logger.setLevel(log_lvl)
        _grpc_logger.setLevel(log_lvl)

    try:
        from core.utils.network_utils.helper_funcs import ensure_geolite2_city_db

        ensure_geolite2_city_db(timeout=30.0)
    except Exception as exc:
        _root_logger.warning("GeoLite2 city database startup update skipped: %s", exc)

    from core.server.security.admin_password import initialize_admin_password

    initialize_admin_password(logger=_root_logger, allow_generate=True)
    if storage_preflight_map:
        _root_logger.info(
            "Main process storage preflight prepared %s section(s), %s client mapping(s), and %s collection(s).",
            len(storage_preflight_map),
            sum(len(section_map) for section_map in storage_preflight_map.values()),
            sum(len(items) for section_map in storage_preflight_map.values() for items in section_map.values()),
        )
    asyncio.run(warmup_storage_clients(storage_config, logger=_root_logger, phase="main-process startup"))

    host = config.server_config.get_host(mode)  # type: ignore
    port = config.server_config.get_port(mode)  # type: ignore
    config.server_config.host = host
    config.server_config.port = port
    reload_enabled = bool(config.server_config.reload)
    uvicorn_workers = config.server_config.worker
    _root_logger.info(f"(mode={mode}) Starting server at {host}:{port} ...")
    _root_logger.info(f"Server instance UUID: {instance_uuid}")

    try:
        from core.server.shared import AppSharedData

        if os.getenv('__AI_SERVICES_CONFIG__'):
            AppSharedData.Get().set_ai_services_config(os.getenv('__AI_SERVICES_CONFIG__'), version=1)
    except Exception as exc:
        _root_logger.debug('Failed to publish initial AI services config to shared state: %s', exc)

    # watch / ignore dirs for reload
    cur_dir = Path(os.path.abspath(os.getcwd()))

    def _to_relative(paths: list[Path]) -> list[str]:
        out: list[str] = []
        for path in paths:
            if not path.exists():
                continue
            try:
                out.append(str(path.resolve().relative_to(cur_dir)))
            except ValueError:
                pass
        return list(dict.fromkeys(out))

    watch_dirs = _to_relative([SERVER_DIR])
    reload_includes = ["*.py"] if reload_enabled else None
    reload_excludes = None

    if reload_enabled:
        if uvicorn_workers != 1:
            _root_logger.warning(
                "reload=True 时不支持多 worker，已将 workers 从 %s 强制调整为 1。",
                uvicorn_workers,
            )
        uvicorn_workers = 1
        _root_logger.warning("注意: reload 模式下仅监听 server/ 目录中的 .py 文件变更。")

    control_supported = not reload_enabled
    if control_supported and uvicorn_workers == 1:
        control_mode = "mainprocess-socket-single"
        control_note = "当前启动模式支持通过主进程本地 control socket 执行 stop/restart；控制请求会先转发到 main process，再执行优雅停止与重启。"
    elif control_supported:
        control_mode = "mainprocess-socket-multiworker"
        control_note = "当前启动模式支持通过主进程本地 control socket 执行 stop/restart；worker 会把控制请求转发给 main process，由 main process 统一停止或重启全部 workers。"
    else:
        control_mode = "unsupported-reload"
        control_note = "reload=true 时主进程由 uvicorn reloader 托管，当前不支持从面板执行 stop/restart。"
    os.environ["__SERVER_CONTROL_SUPPORTED__"] = "1" if control_supported else "0"
    os.environ["__SERVER_CONTROL_MODE__"] = control_mode
    os.environ["__SERVER_CONTROL_NOTE__"] = control_note

    # open browser
    open_browser = getattr(_args, "open_browser", False) and os.getenv("__NO_BROWSER__", "0") != "1"
    if open_browser:
        url = f"http://{host}:{port}"
        def _open():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    # system metrics background thread
    if "db" in config.log_config.log_method:
        from core.storage.orm import make_orm_system_metrics_store
        _metrics_client = storage_config.orm.get_system_metrics()
        retention_hours = max(0, int(config.log_config.system_metrics_retention_hours))
        _metrics_store = make_orm_system_metrics_store(
            _metrics_client,
            retention_seconds=(retention_hours * 3600) if retention_hours > 0 else None,
        )
        start_system_metrics_worker(
            _metrics_store,
            _root_logger,
            interval=config.log_config.system_metrics_interval,
        )

    _main_process_refresh_started = False

    # force-exit safety net
    from core.server.shutdown_control import ShutdownController

    # shutdown trace (stderr-direct, bypasses logging)
    import time as _shutdown_trace_time
    _shutdown_trace_t0 = _shutdown_trace_time.monotonic()
    def _shutdown_trace(message: str) -> None:
        try:
            elapsed = _shutdown_trace_time.monotonic() - _shutdown_trace_t0
            sys.stderr.write(f"[shutdown +{elapsed:6.2f}s] {message}\n")
            sys.stderr.flush()
        except Exception:
            pass

    force_exit_timeout = config.server_config.force_exit_timeout

    def _force_kill_process_tree_best_effort(pid: int | None) -> None:
        if pid is None or pid <= 0 or pid == os.getpid():
            return
        try:
            if os.name == "nt":
                from scripts.stop import _descendant_pids_windows, _kill_pid

                for child_pid in sorted(_descendant_pids_windows(pid), reverse=True):
                    _kill_pid(child_pid, force=True)
                _kill_pid(pid, force=True)
            else:
                os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    def _terminate_server_children_best_effort() -> None:
        try:
            if os.name == "nt":
                from scripts.stop import _descendant_pids_windows, _kill_pid, _pids_for_port

                current_pid = os.getpid()
                targets: set[int] = set(_descendant_pids_windows(current_pid))
                port_pids = _pids_for_port(host, port)
                targets.update(pid for pid in port_pids if pid != current_pid)
                for port_pid in port_pids:
                    targets.update(_descendant_pids_windows(port_pid))
                for target_pid in sorted(targets, reverse=True):
                    if target_pid != current_pid:
                        _kill_pid(target_pid, force=True)
            else:
                from scripts.stop import _kill_pid, _pids_for_port

                current_pid = os.getpid()
                for target_pid in sorted(_pids_for_port(host, port), reverse=True):
                    if target_pid != current_pid:
                        _kill_pid(target_pid, force=True)
        except Exception:
            pass

    _shutdown_controller = ShutdownController(
        force_exit_timeout=force_exit_timeout,
        time_source=time.monotonic,
        exit_func=os._exit,
        force_terminate_children=_terminate_server_children_best_effort,
    )

    def _signal_name(sig: int | None) -> str:
        if sig is None:
            return "signal"
        try:
            return signal.Signals(sig).name
        except Exception:
            return str(sig)

    def _iter_shutdown_signals() -> tuple[int, ...]:
        values: list[int] = []
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                values.append(int(sig))
            except Exception:
                continue
        return tuple(dict.fromkeys(values))

    def _install_process_signal_handlers(handler) -> None:
        for sig in _iter_shutdown_signals():
            try:
                signal.signal(sig, handler)
            except Exception:
                continue

    def _start_force_exit_watchdog(reason: str) -> None:
        _shutdown_controller.start_force_exit_watchdog(reason)

    def _handle_repeated_shutdown_signal(sig: int | None) -> None:
        _shutdown_controller.handle_repeated_signal(_signal_name(sig))

    def _request_graceful_shutdown(*, reason: str, interrupt_main: bool = False) -> None:
        first_request = _shutdown_controller.request_shutdown()
        if first_request:
            _root_logger.info(
                "Shutdown requested (%s). Force-exit in %ss if needed ...",
                reason,
                force_exit_timeout,
            )
            _start_force_exit_watchdog(reason)
        else:
            _root_logger.warning("Repeated shutdown request received (%s); escalating.", reason)

        if interrupt_main:
            _thread.interrupt_main()

    def _request_from_main_control(action: runtime_control.ControlAction, reason: str | None = None) -> None:
        target_reason = reason or action
        _request_graceful_shutdown(reason=target_reason, interrupt_main=True)

    def _install_main_process_signal_handlers() -> None:
        def _signal_handler(sig, frame) -> None:
            sig_label = _signal_name(sig)
            if _shutdown_controller.shutdown_started:
                _shutdown_trace(f"received {sig_label} again (already shutting down)")
                _handle_repeated_shutdown_signal(sig)
                return
            _shutdown_trace(f"received {sig_label}, beginning graceful shutdown")
            _request_from_main_control("stop", reason=f"signal:{sig_label}")

        _install_process_signal_handlers(_signal_handler)

    def _begin_shutdown_finalization(reason: str) -> None:
        if _shutdown_controller.shutdown_started:
            _start_force_exit_watchdog(reason)
            return
        _shutdown_controller.request_shutdown()
        _root_logger.info(
            "Server loop exited; finalizing shutdown (%s). Force-exit in %ss if needed ...",
            reason,
            force_exit_timeout,
        )
        _start_force_exit_watchdog(reason)

    def _request_shutdown_from_uvicorn_signal(sig: int | None) -> None:
        sig_label = _signal_name(sig)
        if _shutdown_controller.shutdown_started:
            _shutdown_trace(f"received {sig_label} again (already shutting down)")
            _handle_repeated_shutdown_signal(sig)
            return
        _shutdown_trace(f"received {sig_label}, beginning graceful shutdown")
        _request_graceful_shutdown(reason=f"signal:{sig_label}", interrupt_main=False)

    def _patch_uvicorn_shutdown() -> None:
        import uvicorn.server as uvicorn_server
        import uvicorn.supervisors.multiprocess as uvicorn_multiprocess

        server_patch_flag = "_web_template_force_exit_patched"
        if not getattr(uvicorn_server.Server, server_patch_flag, False):
            original_server_handle_exit = uvicorn_server.Server.handle_exit

            def handle_exit_with_watchdog(self, sig, frame) -> None:
                _request_shutdown_from_uvicorn_signal(sig)
                original_server_handle_exit(self, sig, frame)
                try:
                    self._captured_signals.clear()
                except Exception:
                    pass

            uvicorn_server.Server.handle_exit = handle_exit_with_watchdog
            setattr(uvicorn_server.Server, server_patch_flag, True)

        multiprocess_patch_flag = "_web_template_force_exit_patched"
        if getattr(uvicorn_multiprocess.Multiprocess, multiprocess_patch_flag, False):
            return

        original_handle_int = uvicorn_multiprocess.Multiprocess.handle_int
        original_handle_term = uvicorn_multiprocess.Multiprocess.handle_term
        original_handle_break = getattr(uvicorn_multiprocess.Multiprocess, "handle_break", None)

        def handle_int_with_watchdog(self) -> None:
            _request_shutdown_from_uvicorn_signal(getattr(signal, "SIGINT", None))
            original_handle_int(self)

        def handle_term_with_watchdog(self) -> None:
            _request_shutdown_from_uvicorn_signal(getattr(signal, "SIGTERM", None))
            original_handle_term(self)

        uvicorn_multiprocess.Multiprocess.handle_int = handle_int_with_watchdog
        uvicorn_multiprocess.Multiprocess.handle_term = handle_term_with_watchdog

        if callable(original_handle_break):
            def handle_break_with_watchdog(self) -> None:
                _request_shutdown_from_uvicorn_signal(getattr(signal, "SIGBREAK", None))
                original_handle_break(self)

            uvicorn_multiprocess.Multiprocess.handle_break = handle_break_with_watchdog

        def join_with_timeout(self) -> None:
            logger = logging.getLogger("uvicorn.error")
            process = self.process
            pid = process.pid
            timeout = max(0.1, float(force_exit_timeout))
            logger.info(f"Waiting for child process [{pid}]")
            process.join(timeout)
            if not process.is_alive():
                return
            logger.warning(
                "Child process [%s] did not exit within %ss; force killing.",
                pid,
                timeout,
            )
            _force_kill_process_tree_best_effort(pid)
            try:
                self.kill()
            except Exception:
                pass
            process.join(2.0)
            if process.is_alive():
                logger.error("Child process [%s] is still alive after force kill.", pid)

        uvicorn_multiprocess.Process.join = join_with_timeout
        setattr(uvicorn_multiprocess.Multiprocess, multiprocess_patch_flag, True)

    def _run_uvicorn_server() -> None:
        _patch_uvicorn_shutdown()
        uvicorn.run(
            f"{_curr_filename}:app",
            host=host,
            port=port,
            reload=reload_enabled,
            workers=uvicorn_workers,
            timeout_keep_alive=5,
            log_config=config.log_config.get_uvicorn_log_config(default_mode=mode),  # type: ignore[arg-type]
            reload_dirs=(watch_dirs or None) if reload_enabled else None,
            reload_includes=reload_includes,
            reload_excludes=reload_excludes,
            env_file=Path(tmp_env_path),
            log_level=config.log_config.get_int_log_level(default_mode=mode),  # type: ignore[arg-type]
            access_log=True,
        )

    # write temp env file & launch uvicorn
    def _write_uvicorn_env_file() -> str:
        env_values: dict[str, object] = {
            "__CONFIG__": config.model_dump_json(indent=None),
            "__MODE__": mode,
            "__PORT__": port,
            "__HOST__": host,
            "IN_UVICORN_PROCESS": "1",
            "__SERVER_START_TIME__": os.environ["__SERVER_START_TIME__"],
            "__SERVER_INSTANCE_ID__": instance_uuid,
            "__CONFIG_FILE_PATH__": runtime_config_info["source_path"] or "",
            "__WRITABLE_CONFIG_FILE_PATH__": runtime_config_info["write_path"],
            "__SERVER_CONTROL_SUPPORTED__": "1" if control_supported else "0",
            "__SERVER_CONTROL_MODE__": control_mode,
            "__SERVER_CONTROL_NOTE__": control_note,
            "__SERVER_SUPERVISOR_PID__": os.getpid(),
            "__SERVER_PROCESS_PID__": os.getpid(),
            "__START_ARGS__": os.environ.get("__START_ARGS__", "[]"),
        }
        if os.getenv("__SERVER_CONTROL_HOST__"):
            env_values["__SERVER_CONTROL_HOST__"] = os.getenv("__SERVER_CONTROL_HOST__") or ""
        if os.getenv("__SERVER_CONTROL_PORT__"):
            env_values["__SERVER_CONTROL_PORT__"] = os.getenv("__SERVER_CONTROL_PORT__") or ""
        if os.getenv("__SERVER_CONTROL_TOKEN__"):
            env_values["__SERVER_CONTROL_TOKEN__"] = os.getenv("__SERVER_CONTROL_TOKEN__") or ""
        if os.getenv("__AI_SERVICES_CONFIG__"):
            env_values["__AI_SERVICES_CONFIG__"] = os.getenv("__AI_SERVICES_CONFIG__") or ""
        if os.getenv("__PT_ORM_PREFLIGHT__"):
            env_values["__PT_ORM_PREFLIGHT__"] = os.getenv("__PT_ORM_PREFLIGHT__") or ""
        if os.getenv("__PT_VECTOR_PREFLIGHT__"):
            env_values["__PT_VECTOR_PREFLIGHT__"] = os.getenv("__PT_VECTOR_PREFLIGHT__") or ""
        if os.getenv("__PT_ADMIN_PW_HASH__"):
            env_values["__PT_ADMIN_PW_HASH__"] = os.getenv("__PT_ADMIN_PW_HASH__") or ""
        if os.getenv("__PT_ADMIN_PW_SALT__"):
            env_values["__PT_ADMIN_PW_SALT__"] = os.getenv("__PT_ADMIN_PW_SALT__") or ""
        if os.getenv("__PT_ADMIN_PW_ITER__"):
            env_values["__PT_ADMIN_PW_ITER__"] = os.getenv("__PT_ADMIN_PW_ITER__") or ""
        if os.getenv("__PT_ADMIN_PW_SOURCE__"):
            env_values["__PT_ADMIN_PW_SOURCE__"] = os.getenv("__PT_ADMIN_PW_SOURCE__") or ""
        return _write_temp_env_file(env_values)

    def _iter_main_process_runtime_roots() -> list[Path]:
        from core.constants import APP_DIR

        roots: list[Path] = []

        def _append(path: Path) -> None:
            if not path.is_dir():
                return
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path
            if resolved not in roots:
                roots.append(resolved)

        extra_app_paths = config.server_config.extra_app_paths
        if isinstance(extra_app_paths, str):
            extra_items = [extra_app_paths]
        else:
            extra_items = list(extra_app_paths or [])
        for item in extra_items:
            _append(Path(item))
        _append(APP_DIR)
        return roots

    def _should_import_runtime_rel_path(rel_path: Path) -> bool:
        return rel_path.name != "__main__.py"

    def _runtime_module_name(root: Path, rel_path: Path) -> str:
        module_path = rel_path.with_suffix("")
        parts = list(module_path.parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        suffix = ".".join(parts).replace("-", "_")
        root_key = str(root).replace("\\", "/")
        prefix = "_main_process_runtime_" + str(abs(hash(root_key)))
        return f"{prefix}.{suffix}" if suffix else prefix

    def _import_main_process_runtime_modules() -> None:
        import importlib.util
        import traceback

        imported_paths: set[Path] = set()
        for root in _iter_main_process_runtime_roots():
            for import_root in (root, root / "api"):
                root_text = str(import_root)
                if import_root.is_dir() and root_text not in sys.path:
                    sys.path.insert(0, root_text)
            for py_file in sorted(root.rglob("*.py")):
                rel_path = py_file.relative_to(root)
                if not _should_import_runtime_rel_path(rel_path):
                    continue
                try:
                    resolved_file = py_file.resolve()
                except Exception:
                    resolved_file = py_file
                if resolved_file in imported_paths:
                    continue
                imported_paths.add(resolved_file)
                module_name = _runtime_module_name(root, rel_path)
                try:
                    spec = importlib.util.spec_from_file_location(module_name, str(py_file))
                    if spec is None or spec.loader is None:
                        _root_logger.warning("Main process runtime import spec failed: %s", py_file)
                        continue
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                except Exception as exc:
                    _root_logger.warning(
                        "Main process runtime import failed: %s: %s\n%s",
                        py_file,
                        exc,
                        traceback.format_exc(),
                    )

    if control_supported:
        runtime_control.install_callback_controller(
            _request_from_main_control,
            mode=control_mode,
            note=control_note,
        )
    else:
        runtime_control.install_disabled_controller(
            mode=control_mode,
            note=control_note,
            supervisor_pid=os.getpid(),
            server_pid=os.getpid(),
        )

    _install_main_process_signal_handlers()

    _import_main_process_runtime_modules()
    from core.server.events import start_main_process_events, stop_main_process_events
    from core.server.scheduler import start_scheduler, stop_scheduler

    _main_process_runtime_started = False
    try:
        start_main_process_events()
        start_scheduler("main_process")
        _main_process_runtime_started = True
    except Exception:
        try:
            stop_scheduler("main_process")
        except Exception:
            pass
        try:
            stop_main_process_events()
        except Exception:
            pass
        raise

    if not reload_enabled:
        from core.server.routes.system.monitoring import (
            start_main_process_system_refresh,
            stop_main_process_system_refresh,
        )
        from core.server.routes.system.tools import (
            start_main_process_system_tools_refresh,
            stop_main_process_system_tools_refresh,
        )

        start_main_process_system_refresh()
        start_main_process_system_tools_refresh()
        _main_process_refresh_started = True

    tmp_env_path = _write_uvicorn_env_file()
    requested_action = None

    # Start a rendezvous thread that watches AppSharedData.workers for
    # lifespan_ready and prints the completion banner once every
    # worker has finished its lifespan startup.
    def _banner_watcher() -> None:
        import time as _t
        from core.server.shared import AppSharedData as _ASD
        deadline = _t.monotonic() + 60.0 + 10.0 * uvicorn_workers
        divider = "-" * 56
        while _t.monotonic() < deadline:
            try:
                ready = _ASD.Get().count_ready_workers()
            except Exception:
                ready = 0
            if ready >= uvicorn_workers:
                _root_logger.info(divider)
                _root_logger.info("Server Initialization Completed at http://%s:%s !", host, port)
                _root_logger.info(divider)
                return
            _t.sleep(0.5)
        try:
            ready_final = _ASD.Get().count_ready_workers()
        except Exception:
            ready_final = 0
        _root_logger.warning(
            "Banner watcher timed out; only %s/%s worker(s) reported ready.",
            ready_final, uvicorn_workers,
        )
    from threading import Thread as _Thread
    _Thread(target=_banner_watcher, name="builtin-banner-watcher", daemon=True).start()

    try:
        try:
            _run_uvicorn_server()
        except KeyboardInterrupt:
            _root_logger.warning("Keyboard interrupt received; leaving server loop.")
        requested_action = runtime_control.consume_requested_action()
    finally:
        _shutdown_trace("supervisor cleanup: stopping background refresh threads")
        if _main_process_runtime_started:
            try:
                stop_scheduler("main_process")
            except Exception:
                _root_logger.exception("Failed to stop main process scheduler.")
            try:
                stop_main_process_events()
            except Exception:
                _root_logger.exception("Failed to stop main process events.")
        if _main_process_refresh_started:
            try:
                stop_main_process_system_refresh()
            except Exception:
                pass
            try:
                stop_main_process_system_tools_refresh()
            except Exception:
                pass
        runtime_control.shutdown_control_server()
        try:
            from core.storage.vector_milvus_lite_proxy import cleanup_all_milvus_lite_proxies
            cleanup_all_milvus_lite_proxies()
        except Exception:
            pass
        try:
            os.unlink(tmp_env_path)
        except OSError:
            pass
        _shutdown_trace("supervisor cleanup: done")

    _begin_shutdown_finalization("uvicorn-close")
    try:
        from core.server.app import invoke_uvicorn_close
        invoke_uvicorn_close()
    except Exception:
        pass
    finally:
        _shutdown_controller.mark_finished()

    if requested_action == "restart":
        os.environ["__NO_BROWSER__"] = "1"
        _refresh_server_instance_env()
        _root_logger.info("Restart requested by backend control API. Re-executing current process...")
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])

    _shutdown_trace("supervisor exiting via os._exit(0) (bypass stdlib atexit join chain)")
    try:
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(0)
