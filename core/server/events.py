import contextlib
import logging

from contextlib import AsyncExitStack
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from core.utils.concurrent_utils import async_run_any_func, run_any_func

from .app import on_app_created, on_app_shutdown, on_before_app_created, on_uvicorn_close

logger = logging.getLogger(__name__)


@runtime_checkable
class _MainProcessContextManager(Protocol):
    def __enter__(self) -> Any: ...
    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> Any: ...


@runtime_checkable
class _AsyncMainProcessContextManager(Protocol):
    async def __aenter__(self) -> Any: ...
    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> Any: ...


type MainProcessContextManager = _MainProcessContextManager | _AsyncMainProcessContextManager
type MainProcessEventHandler = Callable[[], Awaitable[Any]] | Callable[[], Any]

_main_process_context_managers: list[MainProcessContextManager] = []
_main_process_starts_event_handlers: list[MainProcessEventHandler] = []
_main_process_stops_event_handlers: list[MainProcessEventHandler] = []
_main_process_exit_stack: AsyncExitStack | None = None


def register_main_process_context_manager(manager: MainProcessContextManager) -> MainProcessContextManager:
    """Register a context manager used by the supervisor process."""
    _main_process_context_managers.append(manager)
    return manager


def on_main_process_starts_event[F: MainProcessEventHandler](func: F) -> F:
    """Register a sync or async callback invoked before uvicorn starts."""
    _main_process_starts_event_handlers.append(func)
    return func


def on_main_process_stops_event[F: MainProcessEventHandler](func: F | None = None):
    """Register a sync or async callback invoked after uvicorn stops."""

    def decorator(target: F) -> F:
        _main_process_stops_event_handlers.append(target)
        return target

    return decorator(func) if func is not None else decorator


async def _start_main_process_events_async() -> None:
    global _main_process_exit_stack
    if _main_process_exit_stack is not None:
        return

    stack = AsyncExitStack()
    try:
        for manager in _main_process_context_managers:
            if isinstance(manager, _AsyncMainProcessContextManager):
                await stack.enter_async_context(manager)
            else:
                stack.enter_context(manager)
        for handler in list(_main_process_starts_event_handlers):
            try:
                await async_run_any_func(handler)
            except Exception:
                logger.exception("Main process start event handler %s failed.", handler)
        _main_process_exit_stack = stack
    except Exception:
        with contextlib.suppress(Exception):
            await stack.aclose()
        raise


async def _stop_main_process_events_async() -> None:
    global _main_process_exit_stack
    for handler in reversed(_main_process_stops_event_handlers):
        try:
            await async_run_any_func(handler)
        except Exception:
            logger.exception("Main process stop event handler %s failed.", handler)
    if _main_process_exit_stack is not None:
        stack = _main_process_exit_stack
        _main_process_exit_stack = None
        await stack.aclose()


def start_main_process_events() -> None:
    """Enter registered main-process contexts and run start callbacks."""
    run_any_func(_start_main_process_events_async)


def stop_main_process_events() -> None:
    """Run stop callbacks and exit registered main-process contexts."""
    run_any_func(_stop_main_process_events_async)


__all__ = [
    "MainProcessContextManager",
    "on_app_created",
    "on_app_shutdown",
    "on_before_app_created",
    "on_main_process_starts_event",
    "on_main_process_stops_event",
    "on_uvicorn_close",
    "register_main_process_context_manager",
    "start_main_process_events",
    "stop_main_process_events",
]
