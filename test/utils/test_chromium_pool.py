import asyncio
import unittest
from unittest.mock import patch

from core.utils.network_utils.chromium_pool import (
    DEFAULT_USER_AGENT,
    DEFAULT_VIEWPORT,
    NoAvailablePageError,
    WebPagePool,
)


class FakePage:
    def __init__(self, context):
        self.context = context
        self.closed = False
        self.current_url = 'about:blank'
        self.waited_selectors: list[str] = []
        self.goto_calls: list[tuple[str, str | None]] = []
        self.evaluate_calls: list[str] = []
        self.viewport_history: list[dict[str, int]] = []

    async def goto(self, url, wait_until=None):
        self.current_url = url
        self.goto_calls.append((url, wait_until))

    async def wait_for_selector(self, selector):
        self.waited_selectors.append(selector)

    async def content(self):
        return self.context.browser.html_by_url.get(self.current_url, self.context.browser.default_html)

    async def evaluate(self, script):
        self.evaluate_calls.append(script)

    async def set_viewport_size(self, viewport):
        self.viewport_history.append(dict(viewport))

    def set_default_navigation_timeout(self, timeout):
        pass

    def set_default_timeout(self, timeout):
        pass

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed


class FakeContext:
    def __init__(self, browser, kwargs):
        self.browser = browser
        self.kwargs = kwargs
        self.closed = False
        self.clear_cookies_calls = 0
        self.init_scripts: list[str] = []
        self.page = FakePage(self)

    async def new_page(self):
        return self.page

    async def clear_cookies(self):
        self.clear_cookies_calls += 1

    async def close(self):
        self.closed = True

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


class FakeBrowser:
    def __init__(self):
        self.contexts: list[FakeContext] = []
        self.closed = False
        self.event_handlers = {}
        self.default_html = '<html><body><h1>default</h1></body></html>'
        self.html_by_url = {
            'https://example.com/page': '<html><head><style>.x{}</style></head><body><div>Hello <span>World</span></div><script>1</script></body></html>',
        }

    async def new_context(self, **kwargs):
        context = FakeContext(self, kwargs)
        self.contexts.append(context)
        return context

    def on(self, event, callback):
        self.event_handlers[event] = callback

    async def close(self):
        self.closed = True
        callback = self.event_handlers.get('disconnected')
        if callback is not None:
            callback()


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.launch_calls: list[dict] = []

    async def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return self.browser


class FakePlaywright:
    def __init__(self, browser):
        self.chromium = FakeChromium(browser)
        self.stopped = False

    async def stop(self):
        self.stopped = True


class FakeAsyncPlaywrightManager:
    def __init__(self, playwright):
        self.playwright = playwright
        self.start_calls = 0

    async def start(self):
        self.start_calls += 1
        return self.playwright


class TestWebPagePool(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.browser = FakeBrowser()
        self.playwright = FakePlaywright(self.browser)
        self.manager = FakeAsyncPlaywrightManager(self.playwright)
        self.patch_async_playwright = patch(
            'core.utils.network_utils.chromium_pool.async_playwright',
            return_value=self.manager,
        )
        self.patch_async_playwright.start()

    async def asyncTearDown(self):
        self.patch_async_playwright.stop()

    async def test_reuses_default_page_after_close(self):
        pool = WebPagePool(initial_pages=1, max_pages=1)
        try:
            page1 = await pool.get_page()
            page1_id = page1.id
            await page1.close()

            page2 = await pool.get_page()
            self.assertEqual(page2.id, page1_id)
            await page2.close()
        finally:
            await pool.close()

    async def test_temp_page_is_destroyed_on_close(self):
        pool = WebPagePool(initial_pages=0, max_pages=1)
        try:
            page = await pool.create_temp_page()
            entry = pool._busy_temp_pages[page.id]
            await page.close()

            self.assertEqual(pool.temp_page_count, 0)
            self.assertTrue(getattr(entry.page, 'closed'))
            self.assertTrue(getattr(entry.context, 'closed'))
        finally:
            await pool.close()

    async def test_custom_page_recreates_default_page_on_release(self):
        pool = WebPagePool(initial_pages=0, max_pages=1)
        try:
            page = await pool.get_page(user_agent='custom-agent')
            custom_id = page.id
            await page.close()

            self.assertEqual(len(pool._available_pages), 1)
            available_entry = next(iter(pool._available_pages.values()))
            self.assertEqual(available_entry.user_agent, DEFAULT_USER_AGENT)
            self.assertEqual(available_entry.viewport, DEFAULT_VIEWPORT)
            self.assertNotEqual(available_entry.id, custom_id)
        finally:
            await pool.close()

    async def test_wait_strategy_gets_page_after_release(self):
        pool = WebPagePool(initial_pages=0, max_pages=1)
        try:
            first_page = await pool.get_page()

            async def acquire_waiting_page():
                return await pool.get_page(flood_strategy='wait', wait_timeout=1)

            waiter = asyncio.create_task(acquire_waiting_page())
            await asyncio.sleep(0.1)
            await first_page.close()
            second_page = await waiter

            self.assertEqual(second_page.id, first_page.id)
            await second_page.close()
        finally:
            await pool.close()

    async def test_error_strategy_raises_when_pool_is_full(self):
        pool = WebPagePool(initial_pages=0, max_pages=1)
        try:
            page = await pool.get_page()
            with self.assertRaises(NoAvailablePageError):
                await pool.get_page(flood_strategy='error')
            await page.close()
        finally:
            await pool.close()

    async def test_fetch_html_and_text(self):
        pool = WebPagePool(initial_pages=1, max_pages=1)
        try:
            soup = await pool.fetch_html(
                'https://example.com/page',
                wait_selector='body',
            )
            self.assertIn('Hello', soup.get_text(' ', strip=True))

            text = await pool.fetch_text(
                'https://example.com/page',
                wait_selector='body',
            )
            self.assertEqual(text, 'Hello World')

            pages = [context.page for context in self.browser.contexts]
            self.assertTrue(
                any(('https://example.com/page', 'networkidle') in getattr(page, 'goto_calls') for page in pages)
            )
            self.assertTrue(any('body' in getattr(page, 'waited_selectors') for page in pages))
            self.assertTrue(any(getattr(context, 'clear_cookies_calls') >= 1 for context in self.browser.contexts))
        finally:
            await pool.close()
