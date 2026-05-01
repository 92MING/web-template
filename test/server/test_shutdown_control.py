import time

import pytest

from core.server.shutdown_control import ShutdownController


class _ExitRaised(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def test_watchdog_terminates_children_before_force_exit() -> None:
    calls: list[str] = []

    def terminate_children() -> None:
        calls.append("terminate_children")

    def exit_func(code: int) -> None:
        calls.append(f"exit:{code}")
        raise _ExitRaised(code)

    controller = ShutdownController(
        force_exit_timeout=0.01,
        time_source=time.monotonic,
        exit_func=exit_func,
        terminate_children=terminate_children,
    )

    with pytest.raises(_ExitRaised) as exc_info:
        controller.run_watchdog_blocking("test")

    assert exc_info.value.code == 1
    assert calls == ["terminate_children", "exit:1"]


def test_watchdog_uses_force_cleanup_when_provided() -> None:
    calls: list[str] = []

    def terminate_children() -> None:
        calls.append("terminate_children")

    def force_terminate_children() -> None:
        calls.append("force_terminate_children")

    def exit_func(code: int) -> None:
        calls.append(f"exit:{code}")
        raise _ExitRaised(code)

    controller = ShutdownController(
        force_exit_timeout=0.01,
        time_source=time.monotonic,
        exit_func=exit_func,
        terminate_children=terminate_children,
        force_terminate_children=force_terminate_children,
    )

    with pytest.raises(_ExitRaised):
        controller.run_watchdog_blocking("test")

    assert calls == ["force_terminate_children", "exit:1"]