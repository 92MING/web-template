import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent.parent
APP_DIR = PROJECT_DIR / "app"
RUN_PY = PROJECT_DIR / "scripts" / "run.py"

# Ensure project root and app dir on sys.path
for p in (str(PROJECT_DIR), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.run import main as run_server_main  # noqa: E402

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-port", type=int, default=19002)
    parser.add_argument("--server-worker", type=int, default=2)
    args = parser.parse_args()

    extra_app = ",".join([str(HERE), str(HERE / "public")])
    extra_public = str(HERE / "public")

    forwarded_args = [
        "--server-port", str(args.server_port),
        "--server-worker", str(args.server_worker),
        "--extra-app-paths", extra_app,
        "--extra-public-paths", extra_public,
    ]
    os.chdir(str(PROJECT_DIR))
    sys.argv = [str(RUN_PY), *forwarded_args]
    run_server_main()


if __name__ == "__main__":
    main()
