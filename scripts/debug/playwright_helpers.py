"""Reusable Playwright + auth helpers for debugging the demo / app servers.

Provides:
- `find_admin_password()`: scan project *.env for ADMIN_PW (mirrors scripts/stop.py).
- `admin_login(host, port)`: POST /_internal/admin/login, return api_key or None.
- `discover_gallery_port()`: probe common dev ports (19003 default for example/gallery).
- `BrowserSession`: async context manager wrapping Playwright with a single page,
  auto-installing browsers if missing, recording console+page errors per nav.
- `take_screenshot(url, out_path, ...)`: one-shot navigate + full page screenshot.
- `click_then_screenshot(url, selector, out_path, ...)`: navigate, click, capture.
- `audit_pages(base_url, slugs)`: for each slug, navigate and collect JS errors,
  then write a JSON report to tmp/debug/<name>.json.

Auth model: most demo pages are public; admin endpoints under /_internal/admin
require Bearer api_key. `BrowserSession` accepts an optional `bearer` token and
sets it as default extra header.

Examples:

    # Capture a single page
    python -m scripts.debug.playwright_helpers screenshot \\
        --url http://127.0.0.1:19003/pages/cart-drawer.html \\
        --out tmp/debug/cart.png

    # Audit all live pages for JS errors (writes tmp/debug/audit.json)
    python -m scripts.debug.playwright_helpers audit \\
        --base http://127.0.0.1:19003 --pages-from example/gallery/public/pages

    # Click a selector then screenshot
    python -m scripts.debug.playwright_helpers click-shot \\
        --url http://127.0.0.1:19003/pages/cart-drawer.html \\
        --selector "button.builtin-primary" --out tmp/debug/cart-open.png

CLI is thin; for scripted multi-step flows import the functions directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEBUG_OUT_DIR = PROJECT_ROOT / "tmp" / "debug"
DEBUG_OUT_DIR.mkdir(parents=True, exist_ok=True)

LOGIN_ENDPOINT = "/_internal/admin/login"
BACKEND_PROBE_ENDPOINT = "/_internal/admin/api/logs/config"
DEMO_DEFAULT_PORT = 19003
APP_DEFAULT_PORT = 19211


def find_admin_password() -> str | None:
    env_files = list(PROJECT_ROOT.rglob("*.env"))
    env_files.sort(key=lambda p: (len(p.parts), str(p)))
    for env_path in env_files:
        try:
            text = env_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            m = re.match(r"^ADMIN_PW\s*=\s*(.+)$", line)
            if m:
                pw = m.group(1).strip().strip('"').strip("'")
                if pw:
                    return pw
    return None


def _http_post_json(url: str, payload: dict[str, Any], timeout: float = 5.0) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # type: ignore[arg-type]
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def admin_login(host: str = "127.0.0.1", port: int = APP_DEFAULT_PORT, password: str | None = None) -> str | None:
    pw = password or find_admin_password()
    if not pw:
        return None
    try:
        status, body = _http_post_json(f"http://{host}:{port}{LOGIN_ENDPOINT}", {"password": pw})
    except Exception:
        return None
    if status != 200:
        return None
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("authenticated"):
        return None
    token = data.get("api_key")
    return str(token) if token else None


def discover_port(host: str = "127.0.0.1", candidates: tuple[int, ...] = (DEMO_DEFAULT_PORT, APP_DEFAULT_PORT, 9191)) -> int | None:
    for port in candidates:
        try:
            req = urllib.request.Request(f"http://{host}:{port}/", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:  # type: ignore[arg-type]
                if resp.status in (200, 401, 404):
                    return port
        except Exception:
            continue
    return None


@dataclass
class PageReport:
    url: str
    ok: bool
    status: int | None = None
    js_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    screenshot: str | None = None


class BrowserSession:
    """Thin async context manager around Playwright with shared single-page setup."""

    def __init__(
        self,
        bearer: str | None = None,
        viewport: tuple[int, int] = (1280, 800),
        device: str | None = None,
        color_scheme: str = "light",
        verbose: bool = False,
        no_cache: bool = True,
    ):
        self.bearer = bearer
        self.viewport = viewport
        self.device = device
        self.color_scheme = color_scheme
        self.verbose = verbose
        self.no_cache = no_cache
        self._pw = None
        self._browser = None
        self._ctx = None
        self.page = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("Playwright not installed. Run: pip install playwright && playwright install chromium", file=sys.stderr)
            raise

        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(headless=True)
        except Exception as exc:
            # Auto-install on first use
            print(f"Browser launch failed ({exc}); attempting `playwright install chromium`...", file=sys.stderr)
            import subprocess
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
            self._browser = await self._pw.chromium.launch(headless=True)

        ctx_kwargs: dict[str, Any] = {"color_scheme": self.color_scheme}
        if self.device and self._pw.devices.get(self.device):
            ctx_kwargs.update(self._pw.devices[self.device])
        else:
            ctx_kwargs["viewport"] = {"width": self.viewport[0], "height": self.viewport[1]}
        headers: dict[str, str] = {}
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        if self.no_cache:
            headers["Cache-Control"] = "no-cache"
            headers["Pragma"] = "no-cache"
        if headers:
            ctx_kwargs["extra_http_headers"] = headers

        self._ctx = await self._browser.new_context(**ctx_kwargs)
        self.page = await self._ctx.new_page()
        if self.no_cache:
            try:
                # Force no HTTP cache so stale cached JS modules can't poison runs.
                cdp = await self._ctx.new_cdp_session(self.page)
                await cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
            except Exception:
                pass
        return self

    async def __aexit__(self, *exc):
        try:
            if self._ctx: await self._ctx.close()
            if self._browser: await self._browser.close()
            if self._pw: await self._pw.stop()
        except Exception:
            pass

    async def goto_with_report(self, url: str, *, wait: str = "load", timeout_ms: int = 15000) -> PageReport:
        report = PageReport(url=url, ok=True)
        page = self.page
        assert page is not None
        verbose = self.verbose

        def _on_pageerror(exc):
            text = str(exc)
            report.js_errors.append(text)
            report.ok = False
            if verbose:
                print(f"[PAGEERROR] {url} :: {text}", file=sys.stderr, flush=True)

        def _on_console(msg):
            if msg.type in ("error", "warning"):
                snippet = msg.text[:500]
                if msg.type == "error":
                    report.console_errors.append(snippet)
                if verbose:
                    loc = msg.location or {}
                    where = f"{loc.get('url','?')}:{loc.get('lineNumber','?')}"
                    print(f"[CONSOLE.{msg.type.upper()}] {where} :: {snippet}", file=sys.stderr, flush=True)

        def _on_request_failed(req):
            url_ = req.url
            # Ignore external CDN failures (no internet in sandbox)
            if any(host in url_ for host in ("picsum.photos", "pravatar.cc", "i.imgur", "unsplash")):
                return
            failure = req.failure if isinstance(req.failure, str) else (req.failure or "")
            report.failed_requests.append(f"{req.method} {url_}")
            if verbose:
                print(f"[REQFAIL] {req.method} {url_} :: {failure}", file=sys.stderr, flush=True)

        page.on("pageerror", _on_pageerror)
        page.on("console", _on_console)
        page.on("requestfailed", _on_request_failed)
        try:
            resp = await page.goto(url, wait_until=wait, timeout=timeout_ms)
            report.status = resp.status if resp else None
            await page.wait_for_timeout(400)
        except Exception as exc:
            report.ok = False
            report.js_errors.append(f"NAV: {exc}")
        finally:
            page.remove_listener("pageerror", _on_pageerror)
            page.remove_listener("console", _on_console)
            page.remove_listener("requestfailed", _on_request_failed)
        return report

    async def screenshot(self, out_path: Path, full_page: bool = True) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(out_path), full_page=full_page)
        return out_path

    async def set_dark_mode(self, enabled: bool = True) -> None:
        await self.page.evaluate(
            """(dark) => {
                if (window.setSharedTheme) window.setSharedTheme(dark);
                else document.documentElement.dataset.builtinTheme = dark ? 'dark' : 'light';
            }""",
            enabled,
        )

    async def set_lang(self, lang: str) -> None:
        await self.page.evaluate(
            """(l) => {
                if (window.ProjectGalleryShell?.setGalleryLang) window.ProjectGalleryShell.setGalleryLang(l);
                else document.documentElement.lang = l;
            }""",
            lang,
        )


# ---------------------------------------------------------------------------
# High-level helpers


async def take_screenshot(
    url: str,
    out_path: str | Path,
    *,
    dark: bool = False,
    lang: str | None = None,
    viewport: tuple[int, int] = (1280, 800),
    full_page: bool = True,
    wait_ms: int = 600,
) -> PageReport:
    async with BrowserSession(viewport=viewport) as sess:
        report = await sess.goto_with_report(url)
        if dark:
            await sess.set_dark_mode(True)
        if lang:
            await sess.set_lang(lang)
        await sess.page.wait_for_timeout(wait_ms)
        path = await sess.screenshot(Path(out_path), full_page=full_page)
        report.screenshot = str(path)
        return report


async def click_then_screenshot(
    url: str,
    selector: str,
    out_path: str | Path,
    *,
    dark: bool = False,
    viewport: tuple[int, int] = (1280, 800),
    wait_after_click_ms: int = 500,
) -> PageReport:
    async with BrowserSession(viewport=viewport) as sess:
        report = await sess.goto_with_report(url)
        if dark:
            await sess.set_dark_mode(True)
        try:
            await sess.page.click(selector, timeout=5000)
            await sess.page.wait_for_timeout(wait_after_click_ms)
        except Exception as exc:
            report.js_errors.append(f"CLICK: {exc}")
            report.ok = False
        path = await sess.screenshot(Path(out_path))
        report.screenshot = str(path)
        return report


async def audit_pages(base_url: str, slugs: list[str], *, out_json: Path | None = None, verbose: bool = False) -> list[PageReport]:
    out_json = out_json or DEBUG_OUT_DIR / "audit.json"
    reports: list[PageReport] = []
    async with BrowserSession(verbose=verbose) as sess:
        for slug in slugs:
            url = f"{base_url.rstrip('/')}/{slug.lstrip('/')}"
            if verbose:
                print(f"\n=== AUDIT {url} ===", file=sys.stderr, flush=True)
            r = await sess.goto_with_report(url)
            reports.append(r)
            tag = "OK" if (not r.js_errors and not r.console_errors) else "FAIL"
            print(
                f"[{tag}] {url} st={r.status} js={len(r.js_errors)} con={len(r.console_errors)} fr={len(r.failed_requests)}",
                flush=True,
            )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps([r.__dict__ for r in reports], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote audit report ({len(reports)} pages) to {out_json}")
    return reports


def _list_html_under(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.glob("*.html"))


# ---------------------------------------------------------------------------
# CLI


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Debug helpers for demo / app via Playwright.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("screenshot", help="Navigate and capture a full-page screenshot.")
    s.add_argument("--url", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--dark", action="store_true")
    s.add_argument("--lang", default=None)
    s.add_argument("--viewport", default="1280x800", help="WxH, e.g. 375x812 for iPhone")
    s.add_argument("--no-full-page", action="store_true")

    c = sub.add_parser("click-shot", help="Navigate, click selector, then screenshot.")
    c.add_argument("--url", required=True)
    c.add_argument("--selector", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--dark", action="store_true")

    a = sub.add_parser("audit", help="Visit each page under a folder and report JS errors.")
    a.add_argument("--base", required=True, help="e.g. http://127.0.0.1:19003")
    a.add_argument("--pages-from", required=True, help="Local folder of *.html (e.g. example/gallery/public/pages)")
    a.add_argument("--prefix", default="/pages/", help="URL prefix for each html (default /pages/)")
    a.add_argument("--out", default=str(DEBUG_OUT_DIR / "audit.json"))
    a.add_argument("--verbose", "-v", action="store_true", help="Stream console errors / page errors / failed requests live to stderr.")

    t = sub.add_parser("token", help="Discover ADMIN_PW and login to print api_key.")
    t.add_argument("--host", default="127.0.0.1")
    t.add_argument("--port", type=int, default=APP_DEFAULT_PORT)

    return p


def _parse_viewport(s: str) -> tuple[int, int]:
    m = re.match(r"^(\d+)x(\d+)$", s)
    if not m:
        raise SystemExit(f"Invalid viewport '{s}', expected WxH")
    return int(m.group(1)), int(m.group(2))


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "screenshot":
        vp = _parse_viewport(args.viewport)
        report = asyncio.run(take_screenshot(args.url, args.out, dark=args.dark, lang=args.lang, viewport=vp, full_page=not args.no_full_page))
        print(json.dumps(report.__dict__, indent=2, ensure_ascii=False))
    elif args.cmd == "click-shot":
        report = asyncio.run(click_then_screenshot(args.url, args.selector, args.out, dark=args.dark))
        print(json.dumps(report.__dict__, indent=2, ensure_ascii=False))
    elif args.cmd == "audit":
        folder = (PROJECT_ROOT / args.pages_from).resolve()
        if not folder.is_dir():
            raise SystemExit(f"Not a folder: {folder}")
        slugs = [args.prefix.lstrip('/') + name for name in _list_html_under(folder)]
        asyncio.run(audit_pages(args.base, slugs, out_json=Path(args.out), verbose=args.verbose))
    elif args.cmd == "token":
        token = admin_login(args.host, args.port)
        if not token:
            print("Login failed (no ADMIN_PW or backend down).", file=sys.stderr)
            return 1
        print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
