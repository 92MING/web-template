#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Server launcher."""

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


def _print_help_and_exit() -> None:
    parser = Config.BuildArgParser()
    parser.print_help()
    sys.exit(0)


def main() -> None:
    if {"-h", "--help"} & set(sys.argv[1:]):
        _print_help_and_exit()

    parser = Config.BuildArgParser()
    args = parser.parse_args(sys.argv[1:])

    instance_id = str(uuid.uuid4())
    os.environ["__SERVER_INSTANCE_ID__"] = instance_id

    cmd = [sys.executable, "-m", "app", *sys.argv[1:]]
    popen_kwargs: dict[str, object] = {
        "cwd": str(_project_root),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)

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
    print(f"  Start time:         {start_time}")


if __name__ == "__main__":
    main()
