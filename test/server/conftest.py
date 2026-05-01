# -*- coding: utf-8 -*-
"""
pytest conftest — ensures test/server/ is on sys.path so that
``_test_helpers`` can be imported as a plain module.
"""
import sys
from pathlib import Path

_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))
