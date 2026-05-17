import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent
APP_DIR = PROJECT_DIR / "app"
RUN_PY = PROJECT_DIR / "scripts" / "run.py"

for p in (str(PROJECT_DIR), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.run import main as run_server_main  # noqa: E402


def _write_chatroom_plugin_config() -> str:
    config_dir = PROJECT_DIR / "tmp" / "example-webrtc-room"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "webrtc-chatroom-plugin.json"
    config_path.write_text(json.dumps({"enabled": True}, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(config_path)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--server-port", type=int, default=19004)
    parser.add_argument("--server-worker", type=int, default=2)
    parser.add_argument("--server-name", type=str, default=None)
    args = parser.parse_args()

    extra_app = ",".join([str(HERE / "public"), str(HERE)])
    extra_public = str(HERE / "public")
    plugin_path = str(PROJECT_DIR / "plugin" / "webrtc-chatroom")
    plugin_config_path = _write_chatroom_plugin_config()

    forwarded_args = [
        "--server-port", str(args.server_port),
        "--server-worker", str(args.server_worker),
        "--plugin", plugin_path,
        "--plugin-config", plugin_config_path,
        "--extra-app-paths", extra_app,
        "--extra-public-paths", extra_public,
    ]
    if args.server_name:
        forwarded_args.extend(["--server-name", args.server_name])

    os.chdir(str(PROJECT_DIR))
    sys.argv = [str(RUN_PY), *forwarded_args]
    run_server_main()


if __name__ == "__main__":
    main()
