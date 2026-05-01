

import sys

from pathlib import Path


_TEST_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_ROOT.parent
_SERVER_DIR = _PROJECT_ROOT / "server"
_APP_DIR = _PROJECT_ROOT / "app"

for _path in (str(_PROJECT_ROOT), str(_SERVER_DIR), str(_APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
