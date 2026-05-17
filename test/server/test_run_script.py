# -*- coding: utf-8 -*-
"""Tests for the scripts.run launcher."""

import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.run import _build_run_arg_parser, _strip_run_only_args


def test_run_parser_accepts_dashboard_mode():
    parser = _build_run_arg_parser()

    args = parser.parse_args(["--dashboard-mode"])

    assert args.dashboard_mode is True


def test_strip_run_only_args_removes_dashboard_mode_flag():
    forwarded = _strip_run_only_args(["--dashboard-mode", "-p", "19021", "--production"])

    assert forwarded == ["-p", "19021", "--production"]