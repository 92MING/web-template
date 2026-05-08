import asyncio
import contextlib
import functools
import heapq
import logging
import multiprocessing
import os
import threading
import time as time_module

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Awaitable, Callable, Literal, overload

from core.utils.concurrent_utils import async_run_any_func, is_async_callable, run_any_func

type _ScheduledTaskRunOn = Literal["main_process", "fastapi_process"] | Callable[[], bool]
type _ScheduledProcessKind = Literal["main_process", "fastapi_process"]
type _ScheduledTaskRunningMode = Literal["process", "thread"]
type _AsyncScheduledTaskRunningMode = Literal["process", "thread", "async"]
type _MaxInstancesReachedPolicy = Literal["skip", "kill_oldest"]
type _ScheduleCallable = Callable[..., Any] | Callable[..., Awaitable[Any]]
type _ScheduleAt = time | date | datetime

logger = logging.getLogger(__name__)


def _process_entry(func: _ScheduleCallable, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    run_any_func(func, *args, **kwargs)


class _ScheduleTrigger:
    repeating: bool

    def next_run_timestamp(self, now: float) -> float | None:
        raise NotImplementedError


@dataclass(slots=True)
class _IntervalTrigger(_ScheduleTrigger):
    interval_seconds: float
    run_immediately: bool = False
    repeating: bool = True
    _first_run: bool = True

    def next_run_timestamp(self, now: float) -> float | None:
        if self._first_run:
            self._first_run = False
            if self.run_immediately:
                return now
        return now + self.interval_seconds


@dataclass(slots=True)
class _TimedTrigger(_ScheduleTrigger):
    when: _ScheduleAt
    repeating: bool = field(init=False)

    def __post_init__(self) -> None:
        self.repeating = isinstance(self.when, time)

    def next_run_timestamp(self, now: float) -> float | None:
        if isinstance(self.when, datetime):
            target_ts = self.when.timestamp()
            return target_ts if target_ts > now else None

        if isinstance(self.when, time):
            tz = self.when.tzinfo
            current = datetime.fromtimestamp(now, tz=tz)
            candidate = datetime.combine(current.date(), self.when, tzinfo=tz)
            if candidate.timestamp() <= now:
                candidate = candidate + timedelta(days=1)
            return candidate.timestamp()

        target = datetime.combine(self.when, time.min)
        target_ts = target.timestamp()
        return target_ts if target_ts > now else None


@dataclass(slots=True)
class _ScheduledTaskDefinition:
    task_id: int
    func: _ScheduleCallable
    trigger: _ScheduleTrigger
    run_on: _ScheduledTaskRunOn
    running_mode: _AsyncScheduledTaskRunningMode | None
    max_instances: int | None
    timeout: float | None
    max_instances_reached_policy: _MaxInstancesReachedPolicy
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    name: str
    cancelled: bool = False

    def enabled_for(self, process_kind: _ScheduledProcessKind) -> bool:
        if self.cancelled:
            return False
        if callable(self.run_on):
            try:
                return bool(self.run_on())
            except Exception:
                logger.exception("Scheduled task %s run_on predicate failed.", self.name)
                return False
        return self.run_on == process_kind

    def selected_running_mode(self) -> _AsyncScheduledTaskRunningMode:
        if self.running_mode is not None:
            return self.running_mode
        return "async" if is_async_callable(self.func) else "thread"


@dataclass(slots=True)
class _RunningInstance:
    started_at: float
    mode: _AsyncScheduledTaskRunningMode
    async_task: asyncio.Task[Any] | None = None
    future: Future[Any] | None = None
    process: multiprocessing.Process | None = None
    timeout_task: asyncio.Task[Any] | None = None

    def is_done(self) -> bool:
        if self.async_task is not None:
            return self.async_task.done()
        if self.future is not None:
            return self.future.done()
        if self.process is not None:
            return self.process.exitcode is not None
        return True

    def cancel(self) -> bool:
        if self.async_task is not None:
            self.async_task.cancel()
            return True
        if self.future is not None:
            return self.future.cancel()
        if self.process is not None:
            if self.process.exitcode is not None:
                return True
            with contextlib.suppress(Exception):
                self.process.terminate()
            return True
        return True


@dataclass(slots=True)
class _ScheduledTaskState:
    definition: _ScheduledTaskDefinition
    trigger: _ScheduleTrigger
    next_run_at: float | None = None
    running_instances: list[_RunningInstance] = field(default_factory=list)

    def prepare(self) -> None:
        self.next_run_at = self.trigger.next_run_timestamp(time_module.time())

    def prune_finished(self) -> None:
        self.running_instances = [item for item in self.running_instances if not item.is_done()]


@dataclass(frozen=True, slots=True)
class ScheduledTaskHandle:
    task_id: int

    def cancel(self) -> None:
        cancel_scheduled_task(self)


class SchedulerRuntime:
    def __init__(self, process_kind: _ScheduledProcessKind, per_process_max_instances: int | None = None):
        self.process_kind = process_kind
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready_event = threading.Event()
        self._states: list[_ScheduledTaskState] = []
        self._state_heap: list[tuple[float, int, _ScheduledTaskState]] = []
        self._state_map: dict[int, _ScheduledTaskState] = {}
        self._per_process_max_instances = per_process_max_instances
        self._per_process_running_count = 0
        self._per_process_running_lock = threading.Lock()
        max_workers = per_process_max_instances if per_process_max_instances is not None else 64
        self._executor = ThreadPoolExecutor(
            thread_name_prefix=f"{process_kind}-scheduler",
            max_workers=max_workers,
        )
        self._closed = False

    def start(self, definitions: list[_ScheduledTaskDefinition]) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._states = [
            _ScheduledTaskState(
                definition=definition,
                trigger=_clone_trigger(definition.trigger),
            )
            for definition in definitions
            if definition.enabled_for(self.process_kind)
        ]
        for state in self._states:
            state.prepare()
        self._state_map = {state.definition.task_id: state for state in self._states}
        self._state_heap = [
            (state.next_run_at, state.definition.task_id, state)
            for state in self._states
            if state.next_run_at is not None
        ]
        heapq.heapify(self._state_heap)
        self._thread = threading.Thread(
            target=self._thread_main,
            name=f"{self.process_kind}-scheduler",
            daemon=True,
        )
        self._thread.start()
        self._ready_event.wait(timeout=3.0)

    def add_task(self, definition: _ScheduledTaskDefinition) -> None:
        if self._closed or not definition.enabled_for(self.process_kind):
            return
        state = _ScheduledTaskState(definition=definition, trigger=_clone_trigger(definition.trigger))
        if self._loop is None:
            self._states.append(state)
            self._state_map[state.definition.task_id] = state
            return
        self._loop.call_soon_threadsafe(self._add_state, state)

    def stop(self, timeout: float = 5.0) -> None:
        self._closed = True
        loop = self._loop
        if loop is not None and self._stop_event is not None:
            loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=timeout)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def cancel_task(self, task_id: int) -> None:
        if self._loop is None:
            self._states = [state for state in self._states if state.definition.task_id != task_id]
            return
        self._loop.call_soon_threadsafe(self._cancel_task_in_loop, task_id)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run_loop())
        except Exception:
            logger.exception("%s scheduler runtime crashed.", self.process_kind)

    async def _run_loop(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._ready_event.set()

        try:
            while not self._stop_event.is_set():
                self._run_due_tasks()
                sleep_seconds = self._next_sleep_seconds()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._cancel_all_instances()

    def _add_state(self, state: _ScheduledTaskState) -> None:
        state.prepare()
        self._states.append(state)
        self._state_map[state.definition.task_id] = state
        if state.next_run_at is not None:
            heapq.heappush(self._state_heap, (state.next_run_at, state.definition.task_id, state))

    def _cancel_task_in_loop(self, task_id: int) -> None:
        self._state_map.pop(task_id, None)
        remaining: list[_ScheduledTaskState] = []
        for state in self._states:
            if state.definition.task_id == task_id:
                for instance in state.running_instances:
                    instance.cancel()
                continue
            remaining.append(state)
        self._states = remaining

    def _run_due_tasks(self) -> None:
        now = time_module.time()
        while self._state_heap:
            next_run_at, task_id, state = self._state_heap[0]
            # Skip stale entries (cancelled or map mismatch)
            if task_id not in self._state_map or self._state_map[task_id] is not state:
                heapq.heappop(self._state_heap)
                continue
            if state.definition.cancelled:
                heapq.heappop(self._state_heap)
                continue
            if state.next_run_at is None or state.next_run_at > now:
                break
            heapq.heappop(self._state_heap)
            state.prune_finished()
            self._dispatch_state(state)
            state.next_run_at = state.trigger.next_run_timestamp(time_module.time()) if state.trigger.repeating else None
            if state.next_run_at is not None:
                heapq.heappush(self._state_heap, (state.next_run_at, task_id, state))

    def _next_sleep_seconds(self) -> float:
        while self._state_heap:
            next_run_at, task_id, state = self._state_heap[0]
            if task_id not in self._state_map or self._state_map[task_id] is not state:
                heapq.heappop(self._state_heap)
                continue
            if state.definition.cancelled:
                heapq.heappop(self._state_heap)
                continue
            return max(0.01, min(1.0, next_run_at - time_module.time()))
        return 0.5

    def _dispatch_state(self, state: _ScheduledTaskState) -> None:
        definition = state.definition
        if self._per_process_max_instances is not None:
            with self._per_process_running_lock:
                if self._per_process_running_count >= self._per_process_max_instances:
                    logger.warning(
                        "Scheduled task %s skipped because per-process instance limit (%s) was reached.",
                        definition.name, self._per_process_max_instances,
                    )
                    return
                self._per_process_running_count += 1
            acquired_global = True
        else:
            acquired_global = False

        if not self._reserve_instance_slot(state):
            if acquired_global:
                with self._per_process_running_lock:
                    self._per_process_running_count = max(0, self._per_process_running_count - 1)
            return

        mode = definition.selected_running_mode()
        instance = _RunningInstance(started_at=time_module.time(), mode=mode)
        state.running_instances.append(instance)
        try:
            if mode == "async":
                task = asyncio.create_task(self._run_async_instance(state, instance))
                instance.async_task = task
                task.add_done_callback(lambda _: self._finish_instance(state, instance))
                return
            if mode == "thread":
                self._start_thread_instance(state, instance)
                return
            self._start_process_instance(state, instance)
        except Exception:
            self._force_cleanup_instance(state, instance)
            raise

    def _reserve_instance_slot(self, state: _ScheduledTaskState) -> bool:
        definition = state.definition
        if definition.max_instances is None:
            return True
        state.prune_finished()
        if len(state.running_instances) < definition.max_instances:
            return True
        if definition.max_instances_reached_policy == "skip":
            logger.warning("Scheduled task %s skipped because max_instances was reached.", definition.name)
            return False

        oldest = min(state.running_instances, key=lambda item: item.started_at)
        cancelled = oldest.cancel()
        if cancelled:
            with contextlib.suppress(ValueError):
                state.running_instances.remove(oldest)
            logger.warning("Scheduled task %s killed oldest instance because max_instances was reached.", definition.name)
            return True
        state.prune_finished()
        if len(state.running_instances) < definition.max_instances:
            return True
        logger.warning("Scheduled task %s could not cancel oldest thread instance; skipped current run.", definition.name)
        return False

    async def _run_async_instance(self, state: _ScheduledTaskState, instance: _RunningInstance) -> None:
        definition = state.definition
        try:
            if definition.timeout is None:
                await self._call_in_async_mode(definition)
            else:
                await asyncio.wait_for(self._call_in_async_mode(definition), timeout=definition.timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled task %s failed.", definition.name)

    async def _call_in_async_mode(self, definition: _ScheduledTaskDefinition) -> Any:
        if is_async_callable(definition.func):
            return await async_run_any_func(definition.func, *definition.args, **definition.kwargs)
        bound = functools.partial(run_any_func, definition.func, *definition.args, **definition.kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, bound)

    def _start_thread_instance(self, state: _ScheduledTaskState, instance: _RunningInstance) -> None:
        definition = state.definition
        try:
            future = self._executor.submit(run_any_func, definition.func, *definition.args, **definition.kwargs)
        except Exception:
            self._force_cleanup_instance(state, instance)
            logger.exception("Scheduled task %s thread submit failed.", definition.name)
            return
        instance.future = future

        def _done(done_future: Future[Any]) -> None:
            try:
                done_future.result()
            except Exception:
                logger.exception("Scheduled task %s failed.", definition.name)
            if self._loop is not None:
                with contextlib.suppress(RuntimeError):
                    self._loop.call_soon_threadsafe(self._finish_instance, state, instance)

        future.add_done_callback(_done)
        if definition.timeout is not None:
            instance.timeout_task = asyncio.create_task(self._watch_thread_timeout(state, instance))

    async def _watch_thread_timeout(self, state: _ScheduledTaskState, instance: _RunningInstance) -> None:
        timeout = state.definition.timeout
        if timeout is None:
            return
        await asyncio.sleep(timeout)
        if instance.is_done():
            return
        if not instance.cancel():
            logger.warning("Scheduled task %s thread timeout reached; running threads cannot be force-killed.", state.definition.name)

    def _start_process_instance(self, state: _ScheduledTaskState, instance: _RunningInstance) -> None:
        definition = state.definition
        ctx = multiprocessing.get_context("spawn") if os.name == "nt" else multiprocessing.get_context()
        process = ctx.Process(
            target=_process_entry,
            args=(definition.func, definition.args, definition.kwargs),
            daemon=True,
            name=f"scheduled-task-{definition.name}",
        )
        try:
            process.start()
        except Exception:
            self._force_cleanup_instance(state, instance)
            logger.exception("Scheduled task %s process start failed.", definition.name)
            return
        instance.process = process
        instance.timeout_task = asyncio.create_task(self._watch_process_instance(state, instance))

    async def _watch_process_instance(self, state: _ScheduledTaskState, instance: _RunningInstance) -> None:
        definition = state.definition
        timeout_at = None if definition.timeout is None else instance.started_at + definition.timeout
        while instance.process is not None and instance.process.exitcode is None:
            if timeout_at is not None and time_module.time() >= timeout_at:
                logger.warning("Scheduled task %s process timeout reached; terminating process.", definition.name)
                instance.cancel()
                break
            await asyncio.sleep(0.1)
        if instance.process is not None:
            with contextlib.suppress(Exception):
                instance.process.join(timeout=0.2)
            if instance.process.exitcode not in (None, 0):
                logger.warning("Scheduled task %s process exited with code %s.", definition.name, instance.process.exitcode)
        self._finish_instance(state, instance)

    def _force_cleanup_instance(self, state: _ScheduledTaskState, instance: _RunningInstance) -> None:
        with contextlib.suppress(ValueError):
            state.running_instances.remove(instance)
        if instance.timeout_task is not None and not instance.timeout_task.done():
            instance.timeout_task.cancel()
        if self._per_process_max_instances is not None:
            with self._per_process_running_lock:
                self._per_process_running_count = max(0, self._per_process_running_count - 1)

    def _finish_instance(self, state: _ScheduledTaskState, instance: _RunningInstance) -> None:
        with contextlib.suppress(ValueError):
            state.running_instances.remove(instance)
        if instance.timeout_task is not None and not instance.timeout_task.done():
            instance.timeout_task.cancel()
        if self._per_process_max_instances is not None:
            with self._per_process_running_lock:
                self._per_process_running_count = max(0, self._per_process_running_count - 1)

    def _cancel_all_instances(self) -> None:
        for state in self._states:
            for instance in list(state.running_instances):
                instance.cancel()
            state.running_instances.clear()


_scheduled_task_lock = threading.RLock()
_scheduled_task_counter = 0
_scheduled_tasks: list[_ScheduledTaskDefinition] = []
_scheduler_runtimes: dict[_ScheduledProcessKind, SchedulerRuntime] = {}


def _clone_trigger(trigger: _ScheduleTrigger) -> _ScheduleTrigger:
    if isinstance(trigger, _IntervalTrigger):
        return _IntervalTrigger(trigger.interval_seconds, run_immediately=trigger.run_immediately)
    if isinstance(trigger, _TimedTrigger):
        return _TimedTrigger(trigger.when)
    raise TypeError(f"Unsupported schedule trigger: {type(trigger)!r}")


def _validate_max_instances(max_instances: int | None) -> int | None:
    if max_instances is None:
        return None
    if not isinstance(max_instances, int) or max_instances < 1:
        raise ValueError("max_instances must be a positive int or None.")
    return max_instances


def _normalize_timeout(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    value = float(timeout)
    return value if value > 0 else None


def _normalize_interval(interval: float | timedelta) -> float:
    value = interval.total_seconds() if isinstance(interval, timedelta) else float(interval)
    if value <= 0:
        raise ValueError("interval must be greater than 0 seconds.")
    return value


def _register_scheduled_task(
    func: _ScheduleCallable,
    trigger: _ScheduleTrigger,
    *,
    run_on: _ScheduledTaskRunOn,
    running_mode: _AsyncScheduledTaskRunningMode | None,
    max_instances: int | None,
    timeout: float | None,
    max_instances_reached_policy: _MaxInstancesReachedPolicy,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    name: str | None,
) -> ScheduledTaskHandle:
    global _scheduled_task_counter
    if max_instances_reached_policy not in ("skip", "kill_oldest"):
        raise ValueError("max_instances_reached_policy must be 'skip' or 'kill_oldest'.")
    with _scheduled_task_lock:
        _scheduled_task_counter += 1
        definition = _ScheduledTaskDefinition(
            task_id=_scheduled_task_counter,
            func=func,
            trigger=trigger,
            run_on=run_on,
            running_mode=running_mode,
            max_instances=_validate_max_instances(max_instances),
            timeout=_normalize_timeout(timeout),
            max_instances_reached_policy=max_instances_reached_policy,
            args=args,
            kwargs=kwargs,
            name=name or getattr(func, "__qualname__", getattr(func, "__name__", repr(func))),
        )
        _scheduled_tasks.append(definition)
        for runtime in _scheduler_runtimes.values():
            runtime.add_task(definition)
        return ScheduledTaskHandle(definition.task_id)


@overload
def schedule_interval(
    interval: float | timedelta,
    func: None = None,
    *,
    run_on: _ScheduledTaskRunOn = "main_process",
    running_mode: _AsyncScheduledTaskRunningMode | None = None,
    max_instances: int | None = 4,
    timeout: float | None = 180,
    max_instances_reached_policy: _MaxInstancesReachedPolicy = "kill_oldest",
    run_immediately: bool = False,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    name: str | None = None,
) -> Callable[[_ScheduleCallable], _ScheduleCallable]: ...


@overload
def schedule_interval(
    interval: float | timedelta,
    func: _ScheduleCallable,
    *,
    run_on: _ScheduledTaskRunOn = "main_process",
    running_mode: _AsyncScheduledTaskRunningMode | None = None,
    max_instances: int | None = 4,
    timeout: float | None = 180,
    max_instances_reached_policy: _MaxInstancesReachedPolicy = "kill_oldest",
    run_immediately: bool = False,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    name: str | None = None,
) -> _ScheduleCallable: ...


def schedule_interval(
    interval: float | timedelta,
    func: _ScheduleCallable | None = None,
    *,
    run_on: _ScheduledTaskRunOn = "main_process",
    running_mode: _AsyncScheduledTaskRunningMode | None = None,
    max_instances: int | None = 4,
    timeout: float | None = 180,
    max_instances_reached_policy: _MaxInstancesReachedPolicy = "kill_oldest",
    run_immediately: bool = False,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    name: str | None = None,
) -> _ScheduleCallable | Callable[[_ScheduleCallable], _ScheduleCallable]:
    def decorator(target: _ScheduleCallable) -> _ScheduleCallable:
        _register_scheduled_task(
            target,
            _IntervalTrigger(_normalize_interval(interval), run_immediately=run_immediately),
            run_on=run_on,
            running_mode=running_mode,
            max_instances=max_instances,
            timeout=timeout,
            max_instances_reached_policy=max_instances_reached_policy,
            args=args,
            kwargs=kwargs or {},
            name=name,
        )
        return target

    return decorator(func) if func is not None else decorator


def schedule_every(
    interval: float | timedelta,
    func: _ScheduleCallable | None = None,
    **kwargs: Any,
) -> _ScheduleCallable | Callable[[_ScheduleCallable], _ScheduleCallable]:
    return schedule_interval(interval, func, **kwargs)


@overload
def schedule_at(
    when: _ScheduleAt,
    func: None = None,
    *,
    run_on: _ScheduledTaskRunOn = "main_process",
    running_mode: _AsyncScheduledTaskRunningMode | None = None,
    max_instances: int | None = 4,
    timeout: float | None = 180,
    max_instances_reached_policy: _MaxInstancesReachedPolicy = "kill_oldest",
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    name: str | None = None,
) -> Callable[[_ScheduleCallable], _ScheduleCallable]: ...


@overload
def schedule_at(
    when: _ScheduleAt,
    func: _ScheduleCallable,
    *,
    run_on: _ScheduledTaskRunOn = "main_process",
    running_mode: _AsyncScheduledTaskRunningMode | None = None,
    max_instances: int | None = 4,
    timeout: float | None = 180,
    max_instances_reached_policy: _MaxInstancesReachedPolicy = "kill_oldest",
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    name: str | None = None,
) -> _ScheduleCallable: ...


def schedule_at(
    when: _ScheduleAt,
    func: _ScheduleCallable | None = None,
    *,
    run_on: _ScheduledTaskRunOn = "main_process",
    running_mode: _AsyncScheduledTaskRunningMode | None = None,
    max_instances: int | None = 4,
    timeout: float | None = 180,
    max_instances_reached_policy: _MaxInstancesReachedPolicy = "kill_oldest",
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    name: str | None = None,
) -> _ScheduleCallable | Callable[[_ScheduleCallable], _ScheduleCallable]:
    def decorator(target: _ScheduleCallable) -> _ScheduleCallable:
        _register_scheduled_task(
            target,
            _TimedTrigger(when),
            run_on=run_on,
            running_mode=running_mode,
            max_instances=max_instances,
            timeout=timeout,
            max_instances_reached_policy=max_instances_reached_policy,
            args=args,
            kwargs=kwargs or {},
            name=name,
        )
        return target

    return decorator(func) if func is not None else decorator


def schedule_daily(
    at: time,
    func: _ScheduleCallable | None = None,
    **kwargs: Any,
) -> _ScheduleCallable | Callable[[_ScheduleCallable], _ScheduleCallable]:
    return schedule_at(at, func, **kwargs)


def schedule_once(
    at: date | datetime,
    func: _ScheduleCallable | None = None,
    **kwargs: Any,
) -> _ScheduleCallable | Callable[[_ScheduleCallable], _ScheduleCallable]:
    return schedule_at(at, func, **kwargs)


def start_scheduler(process_kind: _ScheduledProcessKind = "main_process") -> None:
    from core.server.data_types.config import Config
    cfg = Config.GetConfig()
    raw_max = cfg.server_config.scheduler_per_process_max_instances
    if raw_max is not None and raw_max <= 0:
        per_process_max = None
    else:
        per_process_max = raw_max
    with _scheduled_task_lock:
        enabled_definitions = [
            definition
            for definition in _scheduled_tasks
            if definition.enabled_for(process_kind)
        ]
        runtime = _scheduler_runtimes.get(process_kind)
        if runtime is None and not enabled_definitions:
            return
        if runtime is None:
            runtime = SchedulerRuntime(process_kind, per_process_max_instances=per_process_max)
            _scheduler_runtimes[process_kind] = runtime
        runtime.start(enabled_definitions)


def stop_scheduler(process_kind: _ScheduledProcessKind | None = None) -> None:
    with _scheduled_task_lock:
        if process_kind is None:
            items = list(_scheduler_runtimes.items())
            _scheduler_runtimes.clear()
        else:
            runtime = _scheduler_runtimes.pop(process_kind, None)
            items = [] if runtime is None else [(process_kind, runtime)]
    for _, runtime in items:
        runtime.stop()


def cancel_scheduled_task(handle: ScheduledTaskHandle | int) -> None:
    task_id = handle.task_id if isinstance(handle, ScheduledTaskHandle) else int(handle)
    with _scheduled_task_lock:
        for definition in _scheduled_tasks:
            if definition.task_id == task_id:
                definition.cancelled = True
                break
        for runtime in _scheduler_runtimes.values():
            runtime.cancel_task(task_id)


def get_scheduled_tasks() -> list[ScheduledTaskHandle]:
    with _scheduled_task_lock:
        return [
            ScheduledTaskHandle(definition.task_id)
            for definition in _scheduled_tasks
            if not definition.cancelled
        ]


try:
    from .app import on_app_shutdown, on_before_app_created

    @on_before_app_created
    def _start_fastapi_process_scheduler(*_args: Any) -> None:
        start_scheduler("fastapi_process")

    @on_app_shutdown
    def _stop_fastapi_process_scheduler(*_args: Any) -> None:
        stop_scheduler("fastapi_process")
except Exception:
    pass


__all__ = [
    "ScheduledTaskHandle",
    "cancel_scheduled_task",
    "get_scheduled_tasks",
    "schedule_at",
    "schedule_daily",
    "schedule_every",
    "schedule_interval",
    "schedule_once",
    "start_scheduler",
    "stop_scheduler",
]
