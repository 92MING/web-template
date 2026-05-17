#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Server launcher."""

import argparse
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_script_path = Path(__file__).resolve()
_project_root = _script_path.parent.parent
_app_dir = _project_root / "app"

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

from core.server.data_types.config import Config  # type: ignore


_DASHBOARD_MODE_ENV = "__DASHBOARD_MODE__"
_RUN_LOG_DIR = _project_root / "tmp" / "run-logs"


def _resolve_detached_python_executable() -> str:
    return sys.executable


def _build_run_arg_parser() -> argparse.ArgumentParser:
    parser = Config.BuildArgParser()
    parser.add_argument(
        "--dashboard-mode",
        action="store_true",
        help="Open the admin panel from / and ignore app/ HTML fallback.",
    )
    return parser


def _strip_run_only_args(argv: list[str]) -> list[str]:
    return [arg for arg in argv if arg != "--dashboard-mode"]


def _print_help_and_exit() -> None:
    parser = _build_run_arg_parser()
    parser.print_help()
    sys.exit(0)


def main() -> None:
    if {"-h", "--help"} & set(sys.argv[1:]):
        _print_help_and_exit()

    parser = _build_run_arg_parser()
    argv = sys.argv[1:]
    forwarded_argv = _strip_run_only_args(argv)
    args = parser.parse_args(argv)

    instance_id = str(uuid.uuid4())
    env = os.environ.copy()
    env["__SERVER_INSTANCE_ID__"] = instance_id
    if getattr(args, "dashboard_mode", False):
        env[_DASHBOARD_MODE_ENV] = "1"
    else:
        env.pop(_DASHBOARD_MODE_ENV, None)

    _RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stderr_log_path = _RUN_LOG_DIR / f"server-{instance_id}.log"
    stderr_log = stderr_log_path.open("ab")
    cmd = [_resolve_detached_python_executable(), "-m", "app", *forwarded_argv]
    popen_kwargs: dict[str, object] = {
        "cwd": str(_project_root),
        "env": env,
        "stdout": stderr_log,
        "stderr": stderr_log,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    finally:
        stderr_log.close()

    hk_tz = timezone(timedelta(hours=8), name="Asia/Hong_Kong")
    start_time = datetime.now(tz=hk_tz).isoformat()
    config = Config.CreateConfigFromArgs(args)
    mode = "prod" if getattr(args, "production", False) else "dev"
    host = config.server_config.get_host(mode)
    port = config.server_config.get_port(mode)

    print("Server started")
    print(f"  PID:                {proc.pid}")
    print(f"  SERVER_INSTANCE_ID: {instance_id}")
    print(f"  Host:               {host}")
    print(f"  Port:               {port}")
    print(f"  Startup log:        {stderr_log_path}")
    print(f"  Start time:         {start_time}")


if __name__ == "__main__":
    main()
