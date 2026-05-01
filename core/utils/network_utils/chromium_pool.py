import asyncio
import logging
import secrets

from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Literal, Self, Sequence, cast, override

from attr import attrib, attrs
from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from ..concurrent_utils import SyncOrAsyncFunc, is_async_callable, run_any_func
from ..type_utils import get_func_name

# region constants
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
DEFAULT_EXTRA_HTTP_HEADERS = {
    'Accept-Language': 'en-US,zh;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Upgrade-Insecure-Requests': '1',
}
DEFAULT_VIEWPORT = (1920, 1080)
_STEALTH_INIT_SCRIPT = '''
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    Object.defineProperty(navigator, 'language', { get: () => 'en-US' });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin' },
            { name: 'Chrome PDF Viewer' },
            { name: 'Native Client' },
        ],
    });
    window.chrome = window.chrome || { runtime: {}, app: {} };
    const originalQuery = navigator.permissions && navigator.permissions.query;
    if (originalQuery) {
        navigator.permissions.query = (parameters) => (
            parameters && parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
    }
    const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return originalGetParameter.call(this, parameter);
    };
}
'''
# endregion


def _gen_alphanum_string(
    length: int,
    lower_only: bool = False,
    extra_choices: Sequence[str] | None = None,
) -> str:
    choices = 'abcdefghijklmnopqrstuvwxyz0123456789'
    if not lower_only:
        choices += 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    if extra_choices:
        for c in extra_choices:
            assert isinstance(c, str), f'Extra choices must be a sequence of single characters, got: {c}'
            assert len(c) == 1, f'Extra choices must be a sequence of single characters, got: {c}'
        choices += ''.join(extra_choices)
    return ''.join(secrets.choice(choices) for _ in range(length))


if TYPE_CHECKING:
    _FakePageCls = Page
    _fake_override = override
else:
    _FakePageCls = object
    _fake_override = lambda x: x


type FloodPageStrategy = Literal['wait', 'new_temp', 'error']

_DEFAULT_LAUNCH_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-accelerated-2d-canvas',
    '--no-first-run',
    '--no-zygote',
    '--disable-gpu',
    '--disable-web-security',
    '--disable-blink-features=AutomationControlled',
    '--disable-extensions',
    '--disable-plugins',
    '--disable-features=VizDisplayCompositor',
]

_logger = logging.getLogger(__name__)

@attrs(auto_attribs=False, eq=False, hash=False)
class _PageEntry:
    id: str = attrib()
    context: BrowserContext = attrib()
    page: Page = attrib()
    is_temp: bool = attrib(default=False)
    user_agent: str = attrib(default=DEFAULT_USER_AGENT)
    extra_headers: dict[str, str] = attrib(factory=dict)
    viewport: tuple[int, int] = attrib(default=DEFAULT_VIEWPORT)

@attrs(auto_attribs=False, eq=False, hash=False)
class PageWrapper(_FakePageCls):
    page: Page = attrib()
    pool: 'WebPagePool' = attrib()
    context: BrowserContext = attrib()

    _closed: bool = False
    _closing: bool = False

    if not TYPE_CHECKING:
        def __getattr__(self, name):
            if self.isClosed():
                raise RuntimeError('Attempt to use a closed page')
            return getattr(self.page, name)

    def __eq__(self, other):
        if not isinstance(other, PageWrapper):
            return False
        return self.id == other.id and self.pool == other.pool

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return f'<Page id={self.id} temporary={self.is_temp} closed={self.isClosed()}>'

    __repr__ = __str__

    def __del__(self):
        run_any_func(self._close)

    @property
    def id(self) -> str:
        if not (id := getattr(self.page, '__page_id__', None)):
            raise RuntimeError('Page does not have an id.')
        return id

    @property
    def is_temp(self) -> bool:
        return getattr(self.page, '__is_temp__', False)

    async def _close(self):
        if self.isClosed():
            return
        if self._closing:
            while self._closing:
                await asyncio.sleep(0.05)
            return
        self._closing = True
        self._closed = True
        try:
            await self.pool._release_page(self.id)
        finally:
            self._closing = False

    @_fake_override
    def isClosed(self) -> bool:  # type: ignore
        return self._closed or self.page.is_closed()

    @_fake_override
    async def close(self):  # type: ignore
        await self._close()


class NoAvailablePageError(RuntimeError):
    '''Raised when no pages are available and flood strategy is 'error'.'''


class DefaultHTMLModifier(Enum):
    '''default modifiers after getting soup from `fetch_html` method'''

    @staticmethod
    def _visible_only_modifier(soup: BeautifulSoup) -> BeautifulSoup:
        for elem in soup.select(
            '[style*="display: none"], [style*="visibility: hidden"], script, style, head, meta, link, noscript'
        ):
            elem.decompose()
        return soup

    NONE = ('NONE', lambda x: x)
    VISIBLE_ONLY = ('VISIBLE_ONLY', _visible_only_modifier)

    def __call__(self, soup: BeautifulSoup) -> BeautifulSoup:
        return self.value[1](soup)


class DefaultTextifier(Enum):
    '''default textifiers for extracting text from `page`, in `fetch_text` method'''

    @staticmethod
    async def _bs4_textifier(page: PageWrapper) -> str:
        soup = BeautifulSoup(await page.content(), 'html.parser')
        soup = DefaultHTMLModifier.VISIBLE_ONLY(soup)
        return soup.get_text(' ', strip=True)

    @staticmethod
    async def _img2text_textifier(page: PageWrapper) -> str:
        raise NotImplementedError('Img2Txt textifier is not implemented yet.')

    BS4 = ('BS4', _bs4_textifier)
    Img2Txt = ('Img2Txt', _img2text_textifier)

    def __call__(self, page: PageWrapper):
        return self.value[1](page)


def _check_closed[F: Callable](f: F) -> F:
    func_name = get_func_name(f, no_module=True)
    if is_async_callable(f):
        @wraps(f)
        async def wrapper(self: 'WebPagePool', *args, **kwargs):  # type: ignore
            if self._closing:
                raise RuntimeError(f'Cannot call `{func_name}` while closing the WebPagePool.')
            if self._closed:
                raise RuntimeError(f'Cannot call `{func_name}` on a closed WebPagePool.')
            return await f(self, *args, **kwargs)
    else:
        @wraps(f)
        def wrapper(self: 'WebPagePool', *args, **kwargs):  # type: ignore
            if self._closing:
                raise RuntimeError(f'Cannot call `{func_name}` while closing the WebPagePool.')
            if self._closed:
                raise RuntimeError(f'Cannot call `{func_name}` on a closed WebPagePool.')
            return f(self, *args, **kwargs)
    return wrapper  # type: ignore


@attrs
class WebPagePool:
    '''Pool for managing multiple browser pages on a shared Playwright Chromium instance.'''

    _get_page_lock: asyncio.Lock = attrib(init=False)
    _busy_pages: dict[str, _PageEntry] = attrib(init=False)
    _busy_temp_pages: dict[str, _PageEntry] = attrib(init=False)
    _available_pages: dict[str, _PageEntry] = attrib(init=False)

    _playwright: Playwright | None = attrib(init=False, default=None)
    _browser: Browser | None = attrib(init=False, default=None)
    _initializing: bool = attrib(init=False, default=False)
    _closing: bool = attrib(init=False, default=False)
    _closed: bool = attrib(init=False, default=False)

    initial_pages: int = attrib(default=4)
    max_pages: int = attrib(default=12)

    default_flood_page_strategy: FloodPageStrategy = attrib(default='new_temp')
    default_request_timeout: int = attrib(default=30)
    default_user_agent: str = attrib(default=DEFAULT_USER_AGENT)
    default_extra_headers: dict[str, str] = attrib(default=DEFAULT_EXTRA_HTTP_HEADERS)
    default_viewport: tuple[int, int] = attrib(default=DEFAULT_VIEWPORT)

    def __attrs_post_init__(self):
        self._get_page_lock = asyncio.Lock()
        self._busy_pages = {}
        self._busy_temp_pages = {}
        self._available_pages = {}
        if self.max_pages < 0:
            raise ValueError('`max_pages` must be non-negative.')
        self.initial_pages = min(self.initial_pages, self.max_pages)
        if self.initial_pages < 0:
            raise ValueError('`initial_pages` must be non-negative.')

    def __setattr__(self, name, value):
        if name in {'initial_pages', 'max_pages'} and getattr(self, '_browser', None):
            _logger.warning(f'You should not change `{name}` after browser is initialized.')
        return super().__setattr__(name, value)

    @property
    def page_count(self) -> int:
        return len(self._busy_pages) + len(self._available_pages)

    @property
    def temp_page_count(self) -> int:
        return len(self._busy_temp_pages)

    def _normalize_headers(self, extra_headers: dict[str, str] | None) -> dict[str, str]:
        return dict(extra_headers or self.default_extra_headers)

    def _normalize_viewport(self, viewport: tuple[int, int] | None) -> tuple[int, int]:
        normalized = viewport or self.default_viewport
        return int(normalized[0]), int(normalized[1])

    def _make_viewport_kwargs(self, viewport: tuple[int, int]) -> dict[str, int]:
        return {'width': int(viewport[0]), 'height': int(viewport[1])}

    def _entry_matches(
        self,
        entry: _PageEntry,
        user_agent: str,
        extra_headers: dict[str, str],
        viewport: tuple[int, int],
    ) -> bool:
        return (
            entry.user_agent == user_agent
            and entry.extra_headers == extra_headers
            and entry.viewport == viewport
        )

    def _entry_is_default(self, entry: _PageEntry) -> bool:
        return self._entry_matches(
            entry,
            self.default_user_agent,
            dict(self.default_extra_headers),
            self.default_viewport,
        )

    def _handle_browser_disconnected(self):
        self._browser = None
        self._playwright = None
        self._busy_pages.clear()
        self._busy_temp_pages.clear()
        self._available_pages.clear()
        self._initializing = False
        _logger.debug('Browser disconnected, page pool reset.')

    @_check_closed
    async def browser(self) -> Browser:
        if self._browser:
            return self._browser
        if self._initializing:
            while self._initializing and not self._browser:
                await asyncio.sleep(0.05)
            if self._browser:
                return self._browser
        self._initializing = True
        succ = False
        playwright: Playwright | None = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=True, args=list(_DEFAULT_LAUNCH_ARGS))
            browser.on('disconnected', lambda *_: self._handle_browser_disconnected())
            self._playwright = playwright
            self._browser = browser
            if self.initial_pages:
                pages = await asyncio.gather(*[self._create_entry(temp=False) for _ in range(self.initial_pages)])
                for entry in pages:
                    self._available_pages[entry.id] = entry
            succ = True
            return browser
        finally:
            self._initializing = False
            if not succ:
                self._handle_browser_disconnected()
                if playwright is not None:
                    try:
                        await playwright.stop()
                    except Exception:
                        pass
                raise RuntimeError('Failed to initialize browser.')

    async def _create_entry(
        self,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
        temp: bool = False,
    ) -> _PageEntry:
        browser = await self.browser()
        normalized_user_agent = user_agent or self.default_user_agent
        normalized_headers = self._normalize_headers(extra_headers)
        normalized_viewport = self._normalize_viewport(viewport)
        context = await browser.new_context(
            user_agent=normalized_user_agent,
            extra_http_headers=normalized_headers,
            viewport=cast(Any, self._make_viewport_kwargs(normalized_viewport)),
            locale='en-US',
            timezone_id='Asia/Hong_Kong',
            ignore_https_errors=True,
        )
        await context.add_init_script(_STEALTH_INIT_SCRIPT)
        page = await context.new_page()
        page.set_default_navigation_timeout(self.default_request_timeout * 1000)
        page.set_default_timeout(self.default_request_timeout * 1000)
        page_id = _gen_alphanum_string(16)
        setattr(page, '__page_id__', page_id)
        setattr(page, '__is_temp__', temp)
        return _PageEntry(
            id=page_id,
            context=context,
            page=page,
            is_temp=temp,
            user_agent=normalized_user_agent,
            extra_headers=normalized_headers,
            viewport=normalized_viewport,
        )

    async def _close_entry(self, entry: _PageEntry):
        try:
            if not entry.page.is_closed():
                await entry.page.close()
        except Exception:
            pass
        try:
            await entry.context.close()
        except Exception:
            pass

    async def _reset_page(self, entry: _PageEntry) -> _PageEntry | None:
        if self._closing or self._closed:
            await self._close_entry(entry)
            return None
        if not self._entry_is_default(entry):
            await self._close_entry(entry)
            return await self._create_entry(temp=False)
        try:
            await entry.page.goto('about:blank', wait_until='domcontentloaded')
        except Exception:
            pass
        try:
            await entry.page.evaluate(
                '''() => {
                    try { window.stop(); } catch (e) {}
                    try { localStorage.clear(); } catch (e) {}
                    try { sessionStorage.clear(); } catch (e) {}
                    try { document.body.innerHTML = ''; } catch (e) {}
                    try { history.pushState({}, '', 'about:blank'); } catch (e) {}
                }'''
            )
        except Exception:
            pass
        try:
            await entry.context.clear_cookies()
        except Exception:
            pass
        try:
            await entry.page.set_viewport_size(cast(Any, self._make_viewport_kwargs(self.default_viewport)))
        except Exception:
            pass
        return entry

    async def _entry_to_wrapper(self, entry: _PageEntry) -> PageWrapper:
        return PageWrapper(page=entry.page, pool=self, context=entry.context)

    async def _release_page(self, page_id: str):
        entry = self._busy_pages.pop(page_id, None)
        if entry is not None:
            entry = await self._reset_page(entry)
            if entry is not None and not self._closing and not self._closed:
                self._available_pages[entry.id] = entry
                _logger.debug(f'Returned page `{entry.id}` to pool.')
            return
        entry = self._busy_temp_pages.pop(page_id, None)
        if entry is not None:
            await self._close_entry(entry)
            _logger.debug(f'Destroyed temporary page `{entry.id}`.')

    async def _try_acquire_page(
        self,
        user_agent: str,
        extra_headers: dict[str, str],
        viewport: tuple[int, int],
    ) -> PageWrapper | None:
        async with self._get_page_lock:
            if self._available_pages:
                _, entry = self._available_pages.popitem()
                if not self._entry_matches(entry, user_agent, extra_headers, viewport):
                    await self._close_entry(entry)
                    entry = await self._create_entry(
                        user_agent=user_agent,
                        extra_headers=extra_headers,
                        viewport=viewport,
                        temp=False,
                    )
                self._busy_pages[entry.id] = entry
                return await self._entry_to_wrapper(entry)
            if self.page_count < self.max_pages:
                entry = await self._create_entry(
                    user_agent=user_agent,
                    extra_headers=extra_headers,
                    viewport=viewport,
                    temp=False,
                )
                self._busy_pages[entry.id] = entry
                return await self._entry_to_wrapper(entry)
        return None

    @_check_closed
    async def create_temp_page(
        self,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
    ) -> PageWrapper:
        entry = await self._create_entry(
            user_agent=user_agent,
            extra_headers=extra_headers,
            viewport=viewport,
            temp=True,
        )
        self._busy_temp_pages[entry.id] = entry
        return await self._entry_to_wrapper(entry)

    @_check_closed
    async def get_page(
        self,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
        flood_strategy: FloodPageStrategy | None = None,
        wait_timeout: int | None = None,
    ) -> PageWrapper:
        flood_strategy = flood_strategy or self.default_flood_page_strategy
        normalized_user_agent = user_agent or self.default_user_agent
        normalized_headers = self._normalize_headers(extra_headers)
        normalized_viewport = self._normalize_viewport(viewport)

        wrapper = await self._try_acquire_page(normalized_user_agent, normalized_headers, normalized_viewport)
        if wrapper is not None:
            return wrapper

        if flood_strategy == 'new_temp':
            return await self.create_temp_page(normalized_user_agent, normalized_headers, normalized_viewport)
        if flood_strategy == 'error':
            raise NoAvailablePageError
        if flood_strategy != 'wait':
            raise ValueError(f'Invalid flood_strategy: {flood_strategy}')
        if self.max_pages == 0:
            raise RuntimeError('Cannot wait for page when `max_pages` is 0.')

        timeout = wait_timeout
        interval = 0.05
        while True:
            await asyncio.sleep(interval)
            wrapper = await self._try_acquire_page(normalized_user_agent, normalized_headers, normalized_viewport)
            if wrapper is not None:
                return wrapper
            if timeout is not None:
                timeout -= interval
                if timeout <= 0:
                    raise TimeoutError('Timeout waiting for available page.')

    @_check_closed
    async def fetch(
        self,
        url: str,
        wait_selector: str | None = None,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
        flood_strategy: FloodPageStrategy | None = None,
        request_timeout: int | None = None,
    ) -> PageWrapper:
        request_timeout = request_timeout or self.default_request_timeout

        async def goto(page: PageWrapper, target_url: str, selector: str | None):
            await page.goto(target_url, wait_until='networkidle')
            if selector:
                await page.wait_for_selector(selector)
            return page

        page = await self.get_page(
            user_agent=user_agent,
            extra_headers=extra_headers,
            viewport=viewport,
            flood_strategy=flood_strategy,
        )
        return await asyncio.wait_for(goto(page, url, wait_selector), timeout=request_timeout)

    @_check_closed
    async def fetch_html(
        self,
        url: str,
        wait_selector: str | None = None,
        html_modifier: Callable[[BeautifulSoup], BeautifulSoup] | DefaultHTMLModifier = DefaultHTMLModifier.NONE,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
        flood_strategy: FloodPageStrategy | None = None,
        request_timeout: int | None = None,
    ) -> BeautifulSoup:
        page = await self.fetch(
            url=url,
            wait_selector=wait_selector,
            user_agent=user_agent,
            extra_headers=extra_headers,
            viewport=viewport,
            flood_strategy=flood_strategy,
            request_timeout=request_timeout,
        )
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        if not html_modifier:
            raise ValueError('`html_modifier` must be a callable or DefaultHTMLModifier.')
        soup = html_modifier(soup)
        await page.close()
        return soup

    @_check_closed
    async def fetch_text(
        self,
        url: str,
        wait_selector: str | None = None,
        textifier: SyncOrAsyncFunc[[PageWrapper], str] | DefaultTextifier = DefaultTextifier.BS4,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
        flood_strategy: FloodPageStrategy | None = None,
        request_timeout: int | None = None,
    ) -> str:
        page = await self.fetch(
            url=url,
            wait_selector=wait_selector,
            user_agent=user_agent,
            extra_headers=extra_headers,
            viewport=viewport,
            flood_strategy=flood_strategy,
            request_timeout=request_timeout,
        )
        if isinstance(textifier, DefaultTextifier):
            textifier = textifier.value[1]
        if not callable(textifier):
            raise ValueError('`textifier` must be a callable or DefaultTextifier.')
        text = textifier(page)
        if isinstance(text, Coroutine):
            text = await text
        await page.close()
        return text  # type: ignore

    @classmethod
    def Global(cls) -> Self:
        if '__Global__' not in cls.__dict__:
            setattr(cls, '__Global__', cls())  # type: ignore
        return getattr(cls, '__Global__')  # type: ignore

    @classmethod
    async def Fetch(
        cls,
        url: str,
        wait_selector: str | None = None,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
        flood_strategy: FloodPageStrategy | None = None,
        request_timeout: int | None = None,
    ) -> PageWrapper:
        return await cls.Global().fetch(
            url=url,
            wait_selector=wait_selector,
            user_agent=user_agent,
            extra_headers=extra_headers,
            viewport=viewport,
            flood_strategy=flood_strategy,
            request_timeout=request_timeout,
        )

    @classmethod
    async def FetchHTML(
        cls,
        url: str,
        wait_selector: str | None = None,
        html_modifier: Callable[[BeautifulSoup], BeautifulSoup] | DefaultHTMLModifier = DefaultHTMLModifier.NONE,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
        flood_strategy: FloodPageStrategy | None = None,
        request_timeout: int | None = None,
    ) -> BeautifulSoup:
        return await cls.Global().fetch_html(
            url=url,
            wait_selector=wait_selector,
            html_modifier=html_modifier,
            user_agent=user_agent,
            extra_headers=extra_headers,
            viewport=viewport,
            flood_strategy=flood_strategy,
            request_timeout=request_timeout,
        )

    @classmethod
    async def FetchText(
        cls,
        url: str,
        wait_selector: str | None = None,
        textifier: SyncOrAsyncFunc[[PageWrapper], str] | DefaultTextifier = DefaultTextifier.BS4,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        viewport: tuple[int, int] | None = None,
        flood_strategy: FloodPageStrategy | None = None,
        request_timeout: int | None = None,
    ) -> str:
        return await cls.Global().fetch_text(
            url=url,
            wait_selector=wait_selector,
            textifier=textifier,
            user_agent=user_agent,
            extra_headers=extra_headers,
            viewport=viewport,
            flood_strategy=flood_strategy,
            request_timeout=request_timeout,
        )

    async def close(self):
        self._closing = True
        browser = self._browser
        playwright = self._playwright
        try:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            self._handle_browser_disconnected()
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception:
                    pass
        finally:
            self._closing = False
            self._closed = True

    def __del__(self):
        run_any_func(self.close)  # type: ignore


__all__ = ['WebPagePool', 'PageWrapper', 'NoAvailablePageError']
