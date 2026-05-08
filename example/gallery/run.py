import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent
APP_DIR = PROJECT_DIR / "app"
MAIN_PY = APP_DIR / "__main__.py"

# Ensure project root and app dir on sys.path
for p in (str(PROJECT_DIR), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-port", type=int, default=19003)
    parser.add_argument("--server-worker", type=int, default=2)
    parser.add_argument("--server-name", type=str, default=None)
    args = parser.parse_args()

    extra_app = ",".join([str(HERE / "public"), str(HERE)])
    extra_public = str(HERE / "public")

    cmd = [
        sys.executable,
        str(MAIN_PY),
        "--server-port", str(args.server_port),
        "--server-worker", str(args.server_worker),
        "--extra-app-paths", extra_app,
        "--extra-public-paths", extra_public,
    ]
    if args.server_name:
        cmd.extend(["--server-name", args.server_name])
    os.chdir(str(PROJECT_DIR))
    sys.argv = cmd[1:]
    runpy.run_path(str(MAIN_PY), run_name="__main__")


if __name__ == "__main__":
    main()
