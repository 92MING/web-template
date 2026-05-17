import atexit
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent
APP_DIR = PROJECT_DIR / "app"
MAIN_PY = APP_DIR / "__main__.py"

# Ensure project root and app dir on sys.path
for p in (str(PROJECT_DIR), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _write_chatroom_plugin_config() -> str:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as file:
        json.dump({"enabled": True}, file, ensure_ascii=False)
        file.write("\n")
        temp_path = file.name
    atexit.register(lambda: Path(temp_path).unlink(missing_ok=True))
    return temp_path

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-port", type=int, default=19001)
    parser.add_argument("--server-worker", type=int, default=2)
    args = parser.parse_args()

    extra_app = ",".join([str(HERE / "public"), str(HERE)])
    extra_public = str(HERE / "public")
    plugin_path = str(PROJECT_DIR / "plugin" / "webrtc-chatroom")
    plugin_config_path = _write_chatroom_plugin_config()

    cmd = [
        sys.executable,
        str(MAIN_PY),
        "--server-port", str(args.server_port),
        "--server-worker", str(args.server_worker),
        "--plugin", plugin_path,
        "--plugin-config", plugin_config_path,
        "--extra-app-paths", extra_app,
        "--extra-public-paths", extra_public,
    ]
    os.chdir(str(PROJECT_DIR))
    sys.argv = cmd[1:]
    runpy.run_path(str(MAIN_PY), run_name="__main__")


if __name__ == "__main__":
    main()
