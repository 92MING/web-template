import os
import sys
import time
import asyncio
import unittest
import aiohttp
from typing import Awaitable, Callable
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.ai.base import (
    ProbeInterval,
    ServiceBase,
    ServiceClientBase,
    StrategyLevel,
    enter_service_context,
    exit_service_context,
    get_inference_context,
    set_service_runtime_reloading,
)


class _FakeAsyncProbeClient(ServiceClientBase[None]):

    @classmethod
    def _compute_cache_key(cls, args: tuple[object, ...], kwargs: dict[str, object]):
        return None

    def __init__(self, *, healthy: bool = True, probe_log: list[float] | None = None):
        unique_key = f'probe-{time.time_ns()}'
        super().__init__(key=unique_key)
        self.unique_key = unique_key
        self.healthy = healthy
        self.probe_log = probe_log if probe_log is not None else []

    @classmethod
    def TestingInput(cls) -> None:
        return None

    async def probe_min_health(self) -> bool:
        self.probe_log.append(time.time())
        await asyncio.sleep(0.01)
        return self.healthy


class _FakeAsyncProbeService(ServiceBase):

    def __init__(self, *clients: _FakeAsyncProbeClient, recovery_interval: float | None = None, **kwargs):
        super().__init__(*clients, fail_cooldown=1.0, recovery_interval=recovery_interval, **kwargs)

    @classmethod
    def Default(cls) -> '_FakeAsyncProbeService':
        return cls(_FakeAsyncProbeClient())


# ── Failover helper service ─────────────────────────────────────────────────

_call_log: list[str] = []

class _FailoverClient(ServiceClientBase[None]):

    @classmethod
    def _compute_cache_key(cls, args: tuple[object, ...], kwargs: dict[str, object]):
        return None

    def __init__(self, name: str, *, raise_exc: Exception | None = None, strategy_lvl: int = 0):
        super().__init__(strategy_lvl=strategy_lvl, key=f'{name}-{time.time_ns()}')
        self.name = name
        self.raise_exc = raise_exc

    @classmethod
    def TestingInput(cls) -> None:
        return None

    async def probe_min_health(self) -> bool:
        return True


class _FailoverService(ServiceBase):

    def __init__(self, *clients: _FailoverClient, fail_cooldown: float = 0.1):
        super().__init__(*clients, fail_cooldown=fail_cooldown)

    @classmethod
    def Default(cls) -> '_FailoverService':
        return cls(_FailoverClient('default'))

    async def call(self) -> str:
        async def _action(client: _FailoverClient) -> str:
            if client.raise_exc:
                raise client.raise_exc
            return client.name
        return await self._run_with_failover(self.clients, _action, error_prefix='all clients failed')


class _ReloadableFailoverService(ServiceBase):

    default_call_count = 0

    def __init__(self, *clients: _FailoverClient, fail_cooldown: float = 0.1, **kwargs):
        super().__init__(*clients, fail_cooldown=fail_cooldown, **kwargs)

    @classmethod
    def Default(cls) -> '_ReloadableFailoverService':
        cls.WaitUntilRuntimeReady()
        if existing := cls.GetInstance('default'):
            return existing
        cls.default_call_count += 1
        return cls(_FailoverClient(f'default-{cls.default_call_count}'), key='default')

    async def call(self) -> str:
        async def _action(client: _FailoverClient) -> str:
            if client.raise_exc:
                raise client.raise_exc
            return client.name
        return await self._run_with_failover(self.clients, _action, error_prefix='all clients failed')


class _SessionCachingClient(ServiceClientBase[None]):

    def __init__(self, *, key: str, **kwargs):
        super().__init__(key=key, **kwargs)

    @classmethod
    def TestingInput(cls) -> None:
        return None

    async def probe_min_health(self) -> bool:
        return True


class _SessionProbingClient(_SessionCachingClient):
    async def probe_min_health(self) -> bool:
        session = await self._get_session()
        return session is not None and not session.closed


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _CachedDefaultService(ServiceBase):

    default_call_count = 0

    def __init__(self, *clients: _FakeAsyncProbeClient, **kwargs):
        super().__init__(*clients, **kwargs)

    @classmethod
    def Default(cls) -> '_CachedDefaultService':
        cls.WaitUntilRuntimeReady()
        if existing := cls.GetInstance('default'):
            return existing
        cls.default_call_count += 1
        return cls(_FakeAsyncProbeClient(), key='default')


# ── Tests ────────────────────────────────────────────────────────────────────

class TestServiceBaseAsyncProbe(unittest.IsolatedAsyncioTestCase):


    def test_default_probe_interval_caps_at_24_hours(self):
        policy = ServiceBase._normalize_probe_interval_value(ServiceBase.DefaultProbeInterval)

        self.assertIsInstance(policy, ProbeInterval)
        self.assertEqual(policy.max_interval, 86400.0)


    def test_effective_probe_interval_decays_for_idle_clients(self):
        client = _FakeAsyncProbeClient()
        service = _FakeAsyncProbeService(client, recovery_interval=1.0)
        self.addCleanup(service.close)

        service._recovery_interval = ProbeInterval(interval=10.0, decay=2.0, max_interval=60.0)
        client._state_created_at = time.time() - 25.0

        self.assertEqual(service._effective_probe_interval(client, now=time.time()), 40.0)

    async def test_probe_client_min_health_awaits_async_client_probe(self):
        probe_log: list[float] = []
        client = _FakeAsyncProbeClient(probe_log=probe_log)
        service = _FakeAsyncProbeService(client)
        self.addCleanup(service.close)

        result = await service._probe_client_min_health(client)

        self.assertTrue(result)
        self.assertEqual(len(probe_log), 1)

    async def test_closed_service_rejects_new_calls(self):
        service = _FailoverService(_FailoverClient('ok'))
        service.close()

        with self.assertRaisesRegex(RuntimeError, 'retired'):
            await service.call()

    async def test_recovery_loop_recovers_client_via_async_probe(self):
        probe_log: list[float] = []
        client = _FakeAsyncProbeClient(healthy=True, probe_log=probe_log)
        service = _FakeAsyncProbeService(client, recovery_interval=1.0)
        service._recovery_interval = 0.05
        self.addCleanup(service.close)

        client._state_fail_count = 2
        client._state_score = 0.2
        client._state_cooldown_until = time.time() - 1.0
        service._ensure_recovery_task()

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if probe_log and client._state_fail_count == 0 and client._state_cooldown_until == 0.0:
                break
            await asyncio.sleep(0.05)

        self.assertTrue(probe_log)
        self.assertEqual(client._state_fail_count, 0)
        self.assertEqual(client._state_cooldown_until, 0.0)
        self.assertGreater(client._state_score, 0.2)

    async def test_recovery_loop_skips_probe_when_shared_status_is_fresh(self):
        probe_log: list[float] = []
        shared_load_calls: list[float] = []
        client = _FakeAsyncProbeClient(healthy=True, probe_log=probe_log)
        service = _FakeAsyncProbeService(client, recovery_interval=1.0)
        service._recovery_interval = 0.05
        self.addCleanup(service.close)

        client._state_fail_count = 2
        client._state_score = 0.2
        client._state_cooldown_until = time.time() - 1.0

        async def _fake_load(_client: _FakeAsyncProbeClient, *, max_age: float | None = None) -> bool:
            effective_age = max_age if max_age is not None else service.ProbeStatusFreshnessSeconds
            shared_load_calls.append(effective_age)
            _client._state_fail_count = 0
            _client._state_score = 0.9
            _client._state_cooldown_until = 0.0
            return True

        service._load_client_status_from_shared = _fake_load  # type: ignore[method-assign]
        service._ensure_recovery_task()

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if shared_load_calls and client._state_fail_count == 0:
                break
            await asyncio.sleep(0.05)

        self.assertTrue(shared_load_calls)
        self.assertFalse(probe_log)
        self.assertEqual(shared_load_calls[0], service.ProbeStatusFreshnessSeconds)
        self.assertEqual(client._state_fail_count, 0)
        self.assertEqual(client._state_cooldown_until, 0.0)
        self.assertEqual(client._state_score, 0.9)

    async def test_recovery_loop_probes_when_shared_failure_cooldown_already_expired(self):
        probe_log: list[float] = []
        shared_load_calls: list[float] = []
        client = _FakeAsyncProbeClient(healthy=True, probe_log=probe_log)
        service = _FakeAsyncProbeService(client, recovery_interval=1.0)
        service._recovery_interval = 0.05
        self.addCleanup(service.close)

        client._state_fail_count = 2
        client._state_score = 0.2
        client._state_cooldown_until = time.time() - 1.0

        async def _fake_load(_client: _FakeAsyncProbeClient, *, max_age: float | None = None) -> bool:
            shared_load_calls.append(max_age or 0.0)
            _client._state_fail_count = 2
            _client._state_score = 0.55
            _client._state_cooldown_until = time.time() - 1.0
            return True

        service._load_client_status_from_shared = _fake_load  # type: ignore[method-assign]
        service._ensure_recovery_task()

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if probe_log and client._state_fail_count == 0 and client._state_cooldown_until == 0.0:
                break
            await asyncio.sleep(0.05)

        self.assertTrue(shared_load_calls)
        self.assertTrue(probe_log)
        self.assertEqual(client._state_fail_count, 0)
        self.assertEqual(client._state_cooldown_until, 0.0)
        self.assertGreater(client._state_score, 0.55)

    async def test_recovery_loop_degrades_unhealthy_client(self):
        '''unhealthy probe → score 降低、cooldown_until 提升。'''
        probe_log: list[float] = []
        client = _FakeAsyncProbeClient(healthy=False, probe_log=probe_log)
        service = _FakeAsyncProbeService(client, recovery_interval=1.0)
        service._recovery_interval = 0.05
        self.addCleanup(service.close)

        initial_score = float(client._state_score)
        client._state_cooldown_until = 0.0  # 使其进入 probe 分支
        service._ensure_recovery_task()

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if probe_log and client._state_cooldown_until > time.time():
                break
            await asyncio.sleep(0.05)

        self.assertTrue(probe_log)
        self.assertLess(client._state_score, initial_score)
        self.assertGreater(client._state_cooldown_until, time.time())

    async def test_wait_recovery_interval_returns_false_after_interval(self):
        '''_wait_recovery_interval 超时后返回 False（不被 stop_event 中断）。'''
        service = _FakeAsyncProbeService()
        service._recovery_interval = 0.05
        self.addCleanup(service.close)

        stopped = await service._wait_recovery_interval()
        self.assertFalse(stopped)

    async def test_wait_recovery_interval_returns_true_on_stop(self):
        '''stop_event 触发后 _wait_recovery_interval 返回 True。'''
        service = _FakeAsyncProbeService()
        service._recovery_interval = 10.0
        self.addCleanup(service.close)

        async def _stop_soon() -> None:
            await asyncio.sleep(0.05)
            service._recovery_stop_event.set()

        asyncio.create_task(_stop_soon())
        stopped = await service._wait_recovery_interval()
        self.assertTrue(stopped)

    async def test_registered_probe_skips_recent_success_and_probes_stale_client(self):
        probe_log: list[float] = []
        client = _FakeAsyncProbeClient(healthy=True, probe_log=probe_log)
        service = _FakeAsyncProbeService(client, recovery_interval=10.0, key='registered-probe-test')
        self.addCleanup(service.close)
        service._load_client_status_from_shared = lambda *_args, **_kwargs: False  # type: ignore[method-assign]

        client._state_last_success_at = time.time()
        skipped = await service._probe_client_if_due(client, interval=10.0)

        self.assertIsNone(skipped)
        self.assertFalse(probe_log)

        client._state_last_success_at = time.time() - 20.0
        probed = await service._probe_client_if_due(client, interval=10.0)

        self.assertTrue(probed)
        self.assertTrue(probe_log)

    async def test_registered_probe_skips_recent_failed_probe_attempt(self):
        probe_log: list[float] = []
        client = _FakeAsyncProbeClient(healthy=False, probe_log=probe_log)
        service = _FakeAsyncProbeService(client, recovery_interval=10.0, key='registered-probe-failure-interval-test')
        self.addCleanup(service.close)

        first = await ServiceBase.ProbeRegisteredClientsOnce()
        second = await ServiceBase.ProbeRegisteredClientsOnce()

        self.assertEqual(first['probed'], 1)
        self.assertEqual(first['unhealthy'], 1)
        self.assertEqual(second['probed'], 0)
        self.assertEqual(len(probe_log), 1)

    async def test_registered_probe_skips_services_with_disabled_probe_interval(self):
        probe_log: list[float] = []
        client = _FakeAsyncProbeClient(healthy=True, probe_log=probe_log)
        service = _FakeAsyncProbeService(client, recovery_interval=10.0, key='registered-probe-disabled-test')
        service._recovery_interval = None
        self.addCleanup(service.close)

        result = await ServiceBase.ProbeRegisteredClientsOnce()

        self.assertEqual(result['checked'], 0)
        self.assertEqual(result['probed'], 0)
        self.assertFalse(probe_log)


class TestServiceBaseOnSuccessOnFail(unittest.IsolatedAsyncioTestCase):

    async def test_on_success_increments_score_and_clears_cooldown(self):
        client = _FakeAsyncProbeClient()
        service = _FakeAsyncProbeService(client)
        self.addCleanup(service.close)

        client._state_score = 0.5
        client._state_fail_count = 3
        client._state_cooldown_until = time.time() + 100.0
        await service._on_success(client)

        self.assertGreater(client._state_score, 0.5)
        self.assertEqual(client._state_cooldown_until, 0.0)
        self.assertEqual(client._state_fail_count, 2)  # decremented by 1

    async def test_on_fail_ratelimit_applies_shorter_cooldown(self):
        client = _FakeAsyncProbeClient()
        service = _FakeAsyncProbeService(client)
        self.addCleanup(service.close)

        client._state_score = 1.0
        exc = RuntimeError('429 too many requests')
        await service._on_fail(client, exc)

        self.assertLess(client._state_score, 1.0)
        self.assertGreater(client._state_cooldown_until, time.time())
        # ratelimit cooldown cap is 120s, timeout/transient cap is much higher
        self.assertLess(client._state_cooldown_until, time.time() + 130.0)

    async def test_on_fail_permanent_applies_max_score_penalty(self):
        client = _FakeAsyncProbeClient()
        service = _FakeAsyncProbeService(client)
        self.addCleanup(service.close)

        client._state_score = 1.0
        exc = RuntimeError('unauthorized: invalid api key')
        await service._on_fail(client, exc)

        # permanent → score * 0.3
        self.assertLessEqual(client._state_score, 0.31)

    async def test_on_fail_timeout_applies_medium_penalty(self):
        client = _FakeAsyncProbeClient()
        service = _FakeAsyncProbeService(client)
        self.addCleanup(service.close)

        client._state_score = 1.0
        exc = asyncio.TimeoutError()
        await service._on_fail(client, exc)

        self.assertLessEqual(client._state_score, 0.71)


class TestClassifyError(unittest.TestCase):

    def setUp(self):
        self._service = _FakeAsyncProbeService()

    def tearDown(self):
        self._service.close()

    def test_ratelimit_by_message(self):
        exc = RuntimeError('rate limit exceeded')
        self.assertEqual(self._service._classify_error(exc), 'ratelimit')

    def test_ratelimit_by_429(self):
        exc = RuntimeError('429 too many requests')
        self.assertEqual(self._service._classify_error(exc), 'ratelimit')

    def test_timeout_asyncio(self):
        exc = asyncio.TimeoutError()
        self.assertEqual(self._service._classify_error(exc), 'timeout')

    def test_permanent_unauthorized(self):
        exc = RuntimeError('unauthorized: invalid api key')
        self.assertEqual(self._service._classify_error(exc), 'permanent')

    def test_permanent_404(self):
        exc = RuntimeError('404 not found')
        self.assertEqual(self._service._classify_error(exc), 'permanent')

    def test_transient_generic(self):
        exc = RuntimeError('connection reset by peer')
        self.assertEqual(self._service._classify_error(exc), 'transient')


class TestRunWithFailover(unittest.IsolatedAsyncioTestCase):

    async def test_returns_first_healthy_client(self):
        service = _FailoverService(
            _FailoverClient('ok'),
        )
        self.addCleanup(service.close)
        result = await service.call()
        self.assertEqual(result, 'ok')

    async def test_falls_over_to_second_client(self):
        service = _FailoverService(
            _FailoverClient('bad', raise_exc=RuntimeError('server error')),
            _FailoverClient('good'),
        )
        self.addCleanup(service.close)
        result = await service.call()
        self.assertEqual(result, 'good')

    async def test_raises_when_all_clients_fail(self):
        service = _FailoverService(
            _FailoverClient('a', raise_exc=RuntimeError('err-a')),
            _FailoverClient('b', raise_exc=RuntimeError('err-b')),
        )
        self.addCleanup(service.close)
        with self.assertRaises(RuntimeError) as ctx:
            await service.call()
        self.assertIn('all clients failed', str(ctx.exception))

    async def test_skips_client_in_cooldown(self):
        bad = _FailoverClient('bad')
        bad._state_cooldown_until = time.time() + 100.0  # in cooldown
        good = _FailoverClient('good')
        service = _FailoverService(bad, good)
        self.addCleanup(service.close)
        result = await service.call()
        self.assertEqual(result, 'good')

    async def test_strategy_level_separates_tiers(self):
        '''ON_RATELIMIT 客户端不会在 LOAD_BALANCE tier 失败时被尝试。'''
        lb_client = _FailoverClient('lb', raise_exc=RuntimeError('err'), strategy_lvl=int(StrategyLevel.LOAD_BALANCE))
        on_rl_client = _FailoverClient('on_rl', strategy_lvl=int(StrategyLevel.ON_RATELIMIT))
        service = _FailoverService(lb_client, on_rl_client)
        self.addCleanup(service.close)
        # LOAD_BALANCE tier fails, should fall through to ON_RATELIMIT tier
        result = await service.call()
        self.assertEqual(result, 'on_rl')


class TestInferenceContext(unittest.TestCase):

    def setUp(self) -> None:
        # 捕获测试开始前的初始 token，确保 tearDown 能完整还原
        self._ctx_tokens: list = []

    def tearDown(self) -> None:
        for tok in reversed(self._ctx_tokens):
            try:
                exit_service_context(tok)
            except Exception:
                pass
        self._ctx_tokens.clear()

    def test_enter_and_exit_restores_previous(self):
        self.assertIsNone(get_inference_context())
        ctx1, tok1 = enter_service_context('completion')
        self._ctx_tokens.append(tok1)
        self.assertIn('completion', ctx1._active_kinds)
        ctx2, tok2 = enter_service_context('embedding')
        self._ctx_tokens.append(tok2)
        self.assertIn('completion', ctx2._active_kinds)
        self.assertIn('embedding', ctx2._active_kinds)
        exit_service_context(tok2)
        self._ctx_tokens.pop()
        # tok2 reset → 恢复到 tok1 那次 set 后的 ctx1（只含 'completion'）
        restored = get_inference_context()
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertIn('completion', restored._active_kinds)
        self.assertNotIn('embedding', restored._active_kinds)
        exit_service_context(tok1)
        self._ctx_tokens.pop()
        self.assertIsNone(get_inference_context())

    def test_get_inference_context_returns_none_by_default(self):
        self.assertIsNone(get_inference_context())


class TestDefaultCacheAndRuntimeGate(unittest.TestCase):

    def setUp(self) -> None:
        self._saved_instances = dict(ServiceBase.ServiceInstances)
        _CachedDefaultService.default_call_count = 0
        _ReloadableFailoverService.default_call_count = 0

    def tearDown(self) -> None:
        set_service_runtime_reloading([_CachedDefaultService.ServiceKind()], reloading=False)
        set_service_runtime_reloading([_ReloadableFailoverService.ServiceKind()], reloading=False)
        _CachedDefaultService.ClearInstances()
        _ReloadableFailoverService.ClearInstances()
        ServiceBase.ServiceInstances.clear()
        ServiceBase.ServiceInstances.update(self._saved_instances)

    def test_default_caches_single_instance(self):
        first = _CachedDefaultService.Default()
        second = _CachedDefaultService.Default()

        self.assertIs(first, second)
        self.assertEqual(_CachedDefaultService.default_call_count, 1)

    def test_wait_runtime_ready_blocks_until_reload_finishes(self):
        import threading
        import time

        results: list[_CachedDefaultService] = []

        def _worker() -> None:
            results.append(_CachedDefaultService.Default())

        set_service_runtime_reloading([_CachedDefaultService.ServiceKind()], reloading=True)
        thread = threading.Thread(target=_worker)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(results)

        set_service_runtime_reloading([_CachedDefaultService.ServiceKind()], reloading=False)
        thread.join(timeout=2.0)

        self.assertEqual(len(results), 1)

    def test_wait_runtime_ready_does_not_block_when_reload_is_non_blocking(self):
        import threading
        import time

        results: list[_CachedDefaultService] = []

        def _worker() -> None:
            results.append(_CachedDefaultService.Default())

        set_service_runtime_reloading(
            [_CachedDefaultService.ServiceKind()],
            reloading=True,
            block_new_requests=False,
        )
        thread = threading.Thread(target=_worker)
        thread.start()
        time.sleep(0.05)
        thread.join(timeout=2.0)

        self.assertEqual(len(results), 1)

        set_service_runtime_reloading([_CachedDefaultService.ServiceKind()], reloading=False)


class TestAsyncRuntimeGate(unittest.IsolatedAsyncioTestCase):

    def tearDown(self) -> None:
        set_service_runtime_reloading([_CachedDefaultService.ServiceKind()], reloading=False)
        _CachedDefaultService.ClearInstances()

    async def test_await_runtime_ready_does_not_block_event_loop(self):
        ticks: list[str] = []

        async def _heartbeat() -> None:
            await asyncio.sleep(0.05)
            ticks.append('tick')

        set_service_runtime_reloading([_CachedDefaultService.ServiceKind()], reloading=True)
        wait_task = asyncio.create_task(_CachedDefaultService.AwaitRuntimeReady())

        await _heartbeat()
        self.assertEqual(ticks, ['tick'])
        self.assertFalse(wait_task.done())

        set_service_runtime_reloading([_CachedDefaultService.ServiceKind()], reloading=False)
        await asyncio.wait_for(wait_task, timeout=2.0)


class TestRuntimeReloadRetirement(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        self._saved_instances = dict(ServiceBase.ServiceInstances)
        _ReloadableFailoverService.default_call_count = 0

    def tearDown(self) -> None:
        set_service_runtime_reloading([_ReloadableFailoverService.ServiceKind()], reloading=False)
        _ReloadableFailoverService.ClearInstances()
        ServiceBase.ServiceInstances.clear()
        ServiceBase.ServiceInstances.update(self._saved_instances)

    async def test_clear_instances_retires_cached_default_service_without_closing_client(self):
        first = _ReloadableFailoverService.Default()
        first_client = first.clients[0]

        removed = _ReloadableFailoverService.ClearInstances(keys={'default'})

        self.assertEqual(removed, 1)
        self.assertTrue(first._closed)
        self.assertFalse(first_client._closed)
        with self.assertRaisesRegex(RuntimeError, 'retired'):
            await first.call()

        second = _ReloadableFailoverService.Default()
        self.assertIsNot(first, second)
        self.assertEqual(_ReloadableFailoverService.default_call_count, 2)

    async def test_clear_client_cache_can_drop_key_without_closing_shared_client(self):
        first = _SessionCachingClient(key='shared-reload-client')

        removed = ServiceClientBase.ClearClientCache(keys={'shared-reload-client'}, close=False)
        second = _SessionCachingClient(key='shared-reload-client')

        self.assertEqual(removed, 1)
        self.assertIsNot(first, second)
        self.assertFalse(first._closed)
        self.assertFalse(second._closed)

    async def test_main_process_shared_client_value_sync_updates_probe_service(self):
        import core.ai as ai_runtime
        from core.server.shared import AppSharedData

        shared = AppSharedData.Get()
        saved_instances = dict(ServiceBase.ServiceInstances)
        saved_update_version = ai_runtime._main_process_client_value_version
        saved_updates = dict(getattr(shared, 'ai_service_client_value_updates', {}))
        saved_shared_update_version = int(getattr(shared, 'ai_service_client_value_version', 0))
        service = None
        client = None
        try:
            ServiceBase.ServiceInstances.clear()
            client = _SessionCachingClient(key='main-sync-client')
            service = _FakeAsyncProbeService(client, key='main-sync-service')
            update = shared.record_ai_service_client_value_update(
                service_type=type(service).__name__,
                service_key='main-sync-service',
                client_key=client.key,
                values={
                    'max_concurrent': 7,
                    'priority': 2.5,
                    'strategy_lvl': int(StrategyLevel.ON_ERROR),
                },
            )
            ai_runtime._main_process_client_value_version = int(update['version']) - 1

            ai_runtime.sync_main_process_probe_runtime_from_shared([])

            self.assertIsNotNone(client.max_concurrent)
            assert client.max_concurrent is not None
            self.assertEqual(client.max_concurrent.max_concurrent, 7)
            self.assertEqual(service._clients[0].priority, 2.5)
            self.assertEqual(service._clients[0].strategy_lvl, StrategyLevel.ON_ERROR)
        finally:
            ai_runtime._main_process_client_value_version = saved_update_version
            shared.ai_service_client_value_updates = saved_updates
            shared.ai_service_client_value_version = saved_shared_update_version
            if service is not None:
                service.close()
            if client is not None:
                client.close(reason='test cleanup')
            ServiceBase.ServiceInstances.clear()
            ServiceBase.ServiceInstances.update(saved_instances)

    async def test_clear_client_cache_retires_cached_client_session(self):
        client = _SessionCachingClient(key='session-client')
        session = await client._get_session()

        removed = ServiceClientBase.ClearClientCache(keys={'session-client'})

        self.assertEqual(removed, 1)
        self.assertTrue(client._closed)
        self.assertIsNotNone(session)
        with self.assertRaisesRegex(RuntimeError, 'retired'):
            await client._get_session()

    async def test_closed_cached_client_is_not_reused(self):
        first = _SessionCachingClient(key='session-client-recreate')
        first.close(reason='test retirement')

        second = _SessionCachingClient(key='session-client-recreate')

        self.assertIsNot(first, second)
        self.assertTrue(first._closed)
        self.assertFalse(second._closed)

    async def test_client_destructor_closes_cached_session(self):
        client = _SessionCachingClient(key='session-client-del')
        fake_session = _FakeSession()
        client._cached_session = fake_session  # type: ignore[assignment]

        client.__del__()

        self.assertTrue(client._closed)
        self.assertTrue(fake_session.closed)
        self.assertEqual(fake_session.close_calls, 1)

    async def test_probe_min_health_preserves_cached_session(self):
        service = _FakeAsyncProbeService()
        self.addCleanup(service.close)
        client = _SessionProbingClient(key='session-probe-preserve')

        healthy = await service._probe_client_min_health(client)

        self.assertTrue(healthy)
        self.assertIsNotNone(client._cached_session)
        assert client._cached_session is not None
        self.assertFalse(client._cached_session.closed)
        client.close(reason='test cleanup')

    async def test_injected_session_is_reused_and_not_closed_by_client(self):
        session = aiohttp.ClientSession()
        try:
            client = _SessionCachingClient(key='session-injected', aiohttp_session=session)

            reused = await client._get_session()

            self.assertIs(reused, session)
            client.close(reason='test cleanup')
            self.assertFalse(session.closed)
        finally:
            await session.close()

    async def test_closed_injected_session_raises_on_get_session(self):
        session = aiohttp.ClientSession()
        await session.close()

        with self.assertRaisesRegex(RuntimeError, 'closed aiohttp_session'):
            _SessionCachingClient(key='session-injected-closed', aiohttp_session=session)
