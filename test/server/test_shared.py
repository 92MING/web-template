

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from core.server import shared


class _FakeSocket:
    def __init__(self, busy_ports: set[int], calls: list[int], *args: Any, **kwargs: Any) -> None:
        self._busy_ports = busy_ports
        self._calls = calls

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def connect_ex(self, address: tuple[str, int]) -> int:
        port = int(address[1])
        self._calls.append(port)
        return 0 if port in self._busy_ports else 1


def test_allocate_worker_msg_port_skips_existing_reserved_ports() -> None:
    calls: list[int] = []

    with patch.object(shared.socket, "socket", lambda *args, **kwargs: _FakeSocket(set(), calls, *args, **kwargs)):
        port = shared._allocate_worker_msg_port({10000, 10001})

    assert port == 10002
    assert calls == [10002]


def test_allocate_worker_msg_port_prefers_explicit_free_port() -> None:
    calls: list[int] = []

    with patch.object(shared.socket, "socket", lambda *args, **kwargs: _FakeSocket(set(), calls, *args, **kwargs)):
        port = shared._allocate_worker_msg_port({10000, 10001}, preferred_port=10123)

    assert port == 10123
    assert calls == [10123]


def test_reallocate_worker_msg_port_skips_current_and_reserved_ports() -> None:
    calls: list[int] = []
    data = object.__new__(shared.AppSharedData)
    data.workers = {
        1: shared.WorkerInfo(pid=1, msg_port=10010),
        2: shared.WorkerInfo(pid=2, msg_port=10011),
    }

    with patch.object(shared.socket, "socket", lambda *args, **kwargs: _FakeSocket(set(), calls, *args, **kwargs)):
        info = data.reallocate_worker_msg_port(1)

    assert info.msg_port == 10000
    assert data.workers[2].msg_port == 10011
    assert calls == [10000]