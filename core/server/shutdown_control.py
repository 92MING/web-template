# -*- coding: utf-8 -*-
"""Process-shutdown coordination primitives for the server supervisor.

Extracted from ``server/main.py`` so the signal/force-exit logic can be unit
tested without spawning a real uvicorn process.

Design constraints (do NOT regress):

* The watchdog and force-exit paths must NEVER call into the standard logging
  pipeline. During shutdown the queue handlers / DB log handler may already
  be torn down and a ``logger.error(...)`` call can block forever, which
  prevents the subsequent ``os._exit(...)`` from ever running. Emergency
  diagnostics go to stderr only via the injected ``stderr_write`` hook.
* On Windows the console can deliver multiple SIGINT events from a single
  physical Ctrl+C press; a fixed grace window absorbs those duplicates,
  after which ANY further signal is treated as an explicit "force exit now"
  request — guaranteeing the user can always strong-kill the server.
* Child processes (Playwright render workers, question-search preload) must
  be terminated proactively from the signal path so the supervisor isn't
  blocked waiting for them inside a ``finally`` block that uvicorn never
  unwinds to.
"""
from __future__ import annotations

import os
import sys
import threading
import time as _sd_time
from collections.abc import Callable
from typing import Protocol

_SHUTDOWN_TRACE_T0 = _sd_time.monotonic()


def _shutdown_trace(message: str) -> None:
    """Stderr-direct shutdown trace; used only at high-value checkpoints
    inside this module. Bypasses logging because the logging pipeline may
    already be torn down during shutdown."""
    try:
        elapsed = _sd_time.monotonic() - _SHUTDOWN_TRACE_T0
        sys.stderr.write(f"[shutdown +{elapsed:6.2f}s] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


class _ExitFunc(Protocol):
    def __call__(self, code: int) -> None: ...  # pragma: no cover - protocol


def _default_stderr_write(message: str) -> None:
    try:
        sys.stderr.write(message)
        if not message.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()
    except Exception:
        pass


class ShutdownController:
    """Coordinates graceful + force-exit shutdown for the supervisor process.

    All side-effecting dependencies (``time``, ``os._exit``, stderr, child
    termination) are injected so the controller can be exercised by unit
    tests without touching the real process.
    """

    def __init__(
        self,
        *,
        force_exit_timeout: float,
        grace_seconds: float = 2.0,
        time_source: Callable[[], float],
        exit_func: _ExitFunc,
        stderr_write: Callable[[str], None] = _default_stderr_write,
        terminate_children: Callable[[], None] = lambda: None,
        force_terminate_children: Callable[[], None] | None = None,
    ) -> None:
        self._force_exit_timeout = float(force_exit_timeout)
        self._grace_seconds = float(grace_seconds)
        self._time_source = time_source
        self._exit_func = exit_func
        self._stderr_write = stderr_write
        self._terminate_children = terminate_children
        self._force_terminate_children = force_terminate_children or terminate_children

        self._shutdown_started = threading.Event()
        self._shutdown_finished = threading.Event()
        self._lock = threading.Lock()
        self._watchdog_started = False
        self._first_request_at: float = 0.0

    # ── status accessors ────────────────────────────────────────────────
    @property
    def shutdown_started(self) -> bool:
        return self._shutdown_started.is_set()

    @property
    def shutdown_finished(self) -> bool:
        return self._shutdown_finished.is_set()

    @property
    def force_exit_timeout(self) -> float:
        return self._force_exit_timeout

    # ── shutdown flow ───────────────────────────────────────────────────
    def request_shutdown(self) -> bool:
        """Mark shutdown as started. Returns True if this was the first call."""
        if self._shutdown_started.is_set():
            return False
        self._shutdown_started.set()
        with self._lock:
            self._first_request_at = float(self._time_source())
        # Children are terminated proactively so the supervisor isn't blocked
        # waiting for them later. Best-effort: failures are swallowed.
        try:
            self._terminate_children()
        except Exception:
            pass
        return True

    def mark_finished(self) -> None:
        self._shutdown_finished.set()

    def handle_repeated_signal(self, sig_name: str) -> None:
        """Decide what to do with a signal received AFTER shutdown started.

        Within the grace window: assume Windows-console duplicate, swallow.
        Outside the grace window: force-exit immediately.
        """
        with self._lock:
            first = self._first_request_at
        if first <= 0:
            self.force_exit(sig_name)
            return
        elapsed = float(self._time_source()) - first
        if elapsed <= self._grace_seconds:
            return  # absorb duplicate
        self.force_exit(sig_name)

    def force_exit(self, sig_name: str | None, *, code: int = 130) -> None:
        """Terminate children, write to stderr (no logging), then ``_exit``."""
        _shutdown_trace(f"force-exit triggered ({sig_name or 'signal'}); aborting process now")
        try:
            self._force_terminate_children()
        except Exception:
            pass
        try:
            self._stderr_write(
                f"[force-exit] received {sig_name or 'signal'} during shutdown; aborting process now."
            )
        except Exception:
            pass
        self._exit_func(code)

    def start_force_exit_watchdog(self, reason: str) -> bool:
        """Spin up the background watchdog. Idempotent. Returns True on first call."""
        if self._force_exit_timeout <= 0:
            return False
        with self._lock:
            if self._watchdog_started:
                return False
            self._watchdog_started = True

        thread = threading.Thread(
            target=self._run_watchdog,
            args=(reason,),
            name="server-force-exit-watchdog",
            daemon=True,
        )
        thread.start()
        return True

    def run_watchdog_blocking(self, reason: str) -> None:
        """Synchronous watchdog loop — exposed so tests can drive it directly."""
        if self._force_exit_timeout <= 0:
            return
        self._run_watchdog(reason)

    def _run_watchdog(self, reason: str) -> None:
        if self._shutdown_finished.wait(self._force_exit_timeout):
            return
        _shutdown_trace(
            f"watchdog timed out after {self._force_exit_timeout}s ({reason}); aborting process"
        )
        try:
            self._force_terminate_children()
        except Exception:
            pass
        try:
            self._stderr_write(
                f"[force-exit] graceful shutdown timed out after {self._force_exit_timeout}s "
                f"({reason}); aborting process."
            )
        except Exception:
            pass
        self._exit_func(1)


__all__ = ["ShutdownController"]
