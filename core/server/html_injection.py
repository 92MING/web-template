# -*- coding: utf-8 -*-
"""Helpers for injecting shared frontend config into served HTML pages."""


import hashlib
import html as _html
import json
import logging
import re

from collections import OrderedDict

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from core.server.constants import ADMIN_PANEL_SHARED_DIR, ADMIN_PANEL_DIR, PUBLIC_VENDOR_DIR
from core.server.data_types.config import Config

logger = logging.getLogger(__name__)

_DependencySnapshot = tuple[tuple[str, float], ...]

_LINK_TAG_RE = re.compile(r"<link\b(?P<attrs>[^>]*)>", re.IGNORECASE)
_STYLE_TAG_RE = re.compile(r"<style(?P<attrs>[^>]*)>(?P<content>.*?)</style>", re.IGNORECASE | re.DOTALL)
_SCRIPT_TAG_RE = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<content>.*?)</script>", re.IGNORECASE | re.DOTALL)
_CSS_IMPORT_RE = re.compile(
  r"@import\s+(?:url\(\s*(?P<url_quote>['\"]?)(?P<url>[^'\")]+)(?P=url_quote)\s*\)|(?P<str_quote>['\"])(?P<str>[^'\"]+)(?P=str_quote))\s*(?P<media>[^;]*);",
  re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
# Bootstrap script only depends on frontend_baseurl; cache it.
_bootstrap_cache: tuple[str | None, str] | None = None  # (baseurl, script)

# Fully-injected HTML per file path.
# key: resolved path string  ->  value: (mtime, baseurl, dependencies, injected_html)
_page_cache: dict[str, tuple[float, str | None, _DependencySnapshot, str]] = {}

# Inlined CSS per file path.
# key: resolved css path string -> value: (mtime, dependencies, inlined_css)
_css_cache: dict[str, tuple[float, _DependencySnapshot, str]] = {}

# Inlined local script files per path.
# key: resolved script path string -> value: (mtime, dependencies, script_text)
_script_cache: dict[str, tuple[float, _DependencySnapshot, str]] = {}

# Inlined HTML content cache for string-based responses.
_CONTENT_CACHE_MAX = 128
_content_cache: OrderedDict[str, tuple[str, str | None, _DependencySnapshot, str]] = OrderedDict()


def _resolve_static_file(base_dir: Path, file_path: str) -> Path | None:
  try:
    base = base_dir.resolve()
    full = (base_dir / file_path).resolve()
    full.relative_to(base)
  except Exception:
    return None
  return full if full.is_file() else None


def _resolve_html_shared_file(file_path: str) -> Path | None:
  direct = _resolve_static_file(ADMIN_PANEL_SHARED_DIR, file_path)
  if direct is not None:
    return direct
  if "/" in file_path or "\\" in file_path:
    return None
  for subdir in ("css", "js"):
    candidate = _resolve_static_file(ADMIN_PANEL_SHARED_DIR / subdir, file_path)
    if candidate is not None:
      return candidate
  return None


def _extract_html_attr(tag_text: str, attr_name: str) -> str | None:
  pattern = re.compile(
    rf"\b{re.escape(attr_name)}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
    re.IGNORECASE,
  )
  match = pattern.search(tag_text)
  if not match:
    return None
  for value in match.groups():
    if value is not None:
      return value
  return None


def _remove_html_attr(tag_text: str, attr_name: str) -> str:
  pattern = re.compile(
    rf"(\s+)\b{re.escape(attr_name)}\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
  )
  return pattern.sub("", tag_text)


def _is_stylesheet_link(tag_text: str) -> bool:
  rel = _extract_html_attr(tag_text, "rel")
  if rel is None:
    return False
  tokens = {token.strip().lower() for token in rel.split() if token.strip()}
  return "stylesheet" in tokens


def _is_module_script(attrs: str) -> bool:
  script_type = _extract_html_attr(attrs, "type")
  return str(script_type or "").strip().lower() == "module"


def _is_external_asset_ref(value: str) -> bool:
  text = str(value or "").strip()
  if not text:
    return True
  return bool(re.match(r"^[a-z][a-z0-9+.-]*:", text, re.IGNORECASE)) or text.startswith(("//", "data:", "blob:", "#"))


def _resolve_local_asset_path(ref: str, *, source_path: Path | None = None) -> Path | None:
  text = str(ref or "").strip()
  if not text or _is_external_asset_ref(text):
    return None
  asset_ref = re.split(r"[?#]", text, maxsplit=1)[0].replace("\\", "/")
  if asset_ref.startswith("/vendor/"):
    return _resolve_static_file(PUBLIC_VENDOR_DIR, asset_ref[len("/vendor/"):])
  if asset_ref.startswith("/html-assets/"):
    return _resolve_html_shared_file(asset_ref[len("/html-assets/"):])
  if asset_ref.startswith("/"):
    return None
  if source_path is None:
    return None
  return _resolve_static_file(source_path.parent, asset_ref)


def _merge_dependency_snapshots(*snapshots: _DependencySnapshot) -> _DependencySnapshot:
  merged: dict[str, float] = {}
  for snapshot in snapshots:
    for path_str, mtime in snapshot:
      merged[path_str] = mtime
  return tuple(sorted(merged.items(), key=lambda item: item[0]))


def _dependencies_unchanged(snapshot: _DependencySnapshot) -> bool:
  for path_str, cached_mtime in snapshot:
    try:
      current_mtime = Path(path_str).stat().st_mtime
    except OSError:
      return False
    if current_mtime != cached_mtime:
      return False
  return True


def _escape_style_content(css_text: str) -> str:
  return css_text.replace("</style", "<\\/style")


def _strip_css_charset(css_text: str) -> str:
  # @charset is only valid as the first token of a standalone stylesheet.
  # Once CSS is embedded in a <style> tag or nested via @import inlining, keep
  # the encoding declaration out to avoid parser warnings.
  return re.sub(
    r"^\s*@charset\s+(?:\"[^\"]*\"|'[^']*')\s*;",
    "",
    css_text,
    count=1,
    flags=re.IGNORECASE,
  ).lstrip()


def _escape_script_content(script_text: str) -> str:
  return script_text.replace("</script", "<\\/script")


def _inline_css_imports(
  css_text: str,
  *,
  source_path: Path | None,
  chain: set[str] | None = None,
) -> tuple[str, _DependencySnapshot]:
  dependency_rows: list[tuple[str, float]] = []
  active_chain = set(chain or set())

  def _replace_import(match: re.Match[str]) -> str:
    import_ref = str(match.group("url") or match.group("str") or "").strip()
    media_query = str(match.group("media") or "").strip()
    asset_path = _resolve_local_asset_path(import_ref, source_path=source_path)
    if asset_path is None:
      return match.group(0)

    resolved_asset = asset_path.resolve()
    asset_key = str(resolved_asset)
    if asset_key in active_chain:
      logger.warning("Circular CSS import ignored: %s -> %s", source_path, asset_path)
      return ""
    try:
      imported_css, imported_dependencies = _load_inlined_css(asset_path, chain=active_chain | {asset_key})
    except OSError:
      logger.warning("Failed to inline CSS import `%s` from `%s`", import_ref, source_path)
      return match.group(0)

    dependency_rows.extend(imported_dependencies)
    if media_query:
      return f"@media {media_query} {{\n{imported_css}\n}}"
    return imported_css

  return _strip_css_charset(_CSS_IMPORT_RE.sub(_replace_import, css_text)), _merge_dependency_snapshots(tuple(dependency_rows))


def _load_inlined_css(path: Path, *, chain: set[str] | None = None) -> tuple[str, _DependencySnapshot]:
  resolved_path = path.resolve()
  path_key = str(resolved_path)
  mtime = resolved_path.stat().st_mtime
  cached = _css_cache.get(path_key)
  if cached is not None:
    cached_mtime, cached_dependencies, cached_css = cached
    if cached_mtime == mtime and _dependencies_unchanged(cached_dependencies):
      return cached_css, cached_dependencies

  css_text = resolved_path.read_text(encoding="utf-8")
  inlined_css, imported_dependencies = _inline_css_imports(css_text, source_path=resolved_path, chain=chain)
  dependencies = _merge_dependency_snapshots(((path_key, mtime),), imported_dependencies)
  _css_cache[path_key] = (mtime, dependencies, inlined_css)
  return inlined_css, dependencies


def _load_inlined_script(path: Path) -> tuple[str, _DependencySnapshot]:
  resolved_path = path.resolve()
  path_key = str(resolved_path)
  mtime = resolved_path.stat().st_mtime
  cached = _script_cache.get(path_key)
  if cached is not None:
    cached_mtime, cached_dependencies, cached_script = cached
    if cached_mtime == mtime and _dependencies_unchanged(cached_dependencies):
      return cached_script, cached_dependencies

  script_text = resolved_path.read_text(encoding="utf-8")
  dependencies = ((path_key, mtime),)
  _script_cache[path_key] = (mtime, dependencies, script_text)
  return script_text, dependencies


def _inline_stylesheet_links(html_text: str, *, source_path: Path | None = None) -> tuple[str, _DependencySnapshot]:
  dependency_rows: list[tuple[str, float]] = []

  def _replace_link(match: re.Match[str]) -> str:
    tag_text = match.group(0)
    if not _is_stylesheet_link(tag_text):
      return tag_text
    if str(_extract_html_attr(tag_text, "id") or "").strip() == "theme-css":
      return tag_text
    href = _extract_html_attr(tag_text, "href")
    if href is None:
      return tag_text
    asset_path = _resolve_local_asset_path(href, source_path=source_path)
    if asset_path is None:
      return tag_text
    try:
      css_text, css_dependencies = _load_inlined_css(asset_path)
    except OSError:
      logger.warning("Failed to inline stylesheet `%s` for `%s`", href, source_path or "<inline>")
      return tag_text
    dependency_rows.extend(css_dependencies)
    media = _extract_html_attr(tag_text, "media")
    media_attr = f' media="{_html.escape(media, quote=True)}"' if media else ""
    return (
      f'<style data-proj-inline-href="{_html.escape(href, quote=True)}"{media_attr}>\n'
      f'{_escape_style_content(css_text)}\n'
      f'</style>'
    )

  return _LINK_TAG_RE.sub(_replace_link, html_text), _merge_dependency_snapshots(tuple(dependency_rows))


def _inline_style_tag_imports(html_text: str, *, source_path: Path | None = None) -> tuple[str, _DependencySnapshot]:
  dependency_rows: list[tuple[str, float]] = []

  def _replace_style(match: re.Match[str]) -> str:
    content = match.group("content")
    if "@import" not in content.lower():
      return match.group(0)
    inlined_css, css_dependencies = _inline_css_imports(content, source_path=source_path)
    dependency_rows.extend(css_dependencies)
    attrs = match.group("attrs") or ""
    return f"<style{attrs}>{_escape_style_content(inlined_css)}</style>"

  return _STYLE_TAG_RE.sub(_replace_style, html_text), _merge_dependency_snapshots(tuple(dependency_rows))


def _inline_local_script_tags(html_text: str, *, source_path: Path | None = None) -> tuple[str, _DependencySnapshot]:
  dependency_rows: list[tuple[str, float]] = []

  def _replace_script(match: re.Match[str]) -> str:
    attrs = match.group("attrs") or ""
    src = _extract_html_attr(attrs, "src")
    if src is None:
      return match.group(0)
    if _is_module_script(attrs):
      return match.group(0)
    asset_path = _resolve_local_asset_path(src, source_path=source_path)
    if asset_path is None:
      return match.group(0)
    try:
      script_text, script_dependencies = _load_inlined_script(asset_path)
    except OSError:
      logger.warning("Failed to inline script `%s` for `%s`", src, source_path or "<inline>")
      return match.group(0)
    dependency_rows.extend(script_dependencies)
    inline_attrs = _remove_html_attr(attrs, "src")
    return (
      f'<script{inline_attrs} data-proj-inline-src="{_html.escape(src, quote=True)}">\n'
      f'{_escape_script_content(script_text)}\n'
      f'</script>'
    )

  return _SCRIPT_TAG_RE.sub(_replace_script, html_text), _merge_dependency_snapshots(tuple(dependency_rows))


def _prepare_html_content(html_text: str, *, source_path: Path | None = None) -> tuple[str, _DependencySnapshot]:
  # Inject the frontend bootstrap BEFORE inlining external scripts.  Inlined
  # third-party scripts (e.g. xlsx.full.min.js) often contain literal
  # ``</head>`` / ``</body>`` substrings inside JavaScript string literals;
  # if the bootstrap injection runs after script inlining, ``find("</head>")``
  # latches onto one of those literals and splits the inlined ``<script>``
  # block, leaking the remainder of the JS source into the document body.
  html_with_bootstrap = inject_frontend_config(html_text)
  html_with_inlined_links, link_dependencies = _inline_stylesheet_links(html_with_bootstrap, source_path=source_path)
  html_with_inlined_styles, style_dependencies = _inline_style_tag_imports(html_with_inlined_links, source_path=source_path)
  html_with_inlined_scripts, script_dependencies = _inline_local_script_tags(html_with_inlined_styles, source_path=source_path)
  html_with_internal_paths = _rewrite_internal_path_literals(html_with_inlined_scripts)
  return html_with_internal_paths, _merge_dependency_snapshots(link_dependencies, style_dependencies, script_dependencies)


def _rewrite_internal_path_literals(html_text: str) -> str:
  try:
    server_cfg = Config.GetConfig().server_config
  except Exception:
    return html_text
  internal_admin_path = str(server_cfg.get_internal_admin_path()).rstrip("/") or "/admin"
  internal_assets_path = str(server_cfg.get_internal_path("/html-assets")).rstrip("/") or "/html-assets"
  replacements = {
    '"/admin': f'"{internal_admin_path}',
    "'/admin": f"'{internal_admin_path}",
    "`/admin": f"`{internal_admin_path}",
    '"/html-assets': f'"{internal_assets_path}',
    "'/html-assets": f"'{internal_assets_path}",
    "`/html-assets": f"`{internal_assets_path}",
  }
  rewritten = html_text
  for old_text, new_text in replacements.items():
    rewritten = rewritten.replace(old_text, new_text)
  return rewritten


def _content_cache_key(html_text: str, *, source_path: Path | None = None) -> str:
  digest = hashlib.sha256(html_text.encode("utf-8")).hexdigest()
  source_key = str(source_path.resolve()) if source_path is not None else "<inline>"
  return f"{source_key}:{digest}"


def _get_cached_content_html(cache_key: str, *, content_signature: str, baseurl: str | None) -> str | None:
  cached = _content_cache.get(cache_key)
  if cached is None:
    return None
  cached_signature, cached_baseurl, cached_dependencies, cached_html = cached
  if cached_signature != content_signature or cached_baseurl != baseurl or not _dependencies_unchanged(cached_dependencies):
    _content_cache.pop(cache_key, None)
    return None
  _content_cache.move_to_end(cache_key)
  return cached_html


def _store_cached_content_html(
  cache_key: str,
  *,
  content_signature: str,
  baseurl: str | None,
  dependencies: _DependencySnapshot,
  html_text: str,
) -> None:
  _content_cache[cache_key] = (content_signature, baseurl, dependencies, html_text)
  _content_cache.move_to_end(cache_key)
  while len(_content_cache) > _CONTENT_CACHE_MAX:
    _content_cache.popitem(last=False)

def _sanitize_frontend_baseurl(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.rstrip("/")

def get_frontend_baseurl() -> str | None:
    try:
        cfg = Config.GetConfig().server_config
    except Exception:
        return None
    return _sanitize_frontend_baseurl(getattr(cfg, "frontend_baseurl", None))

def build_frontend_bootstrap_script() -> str:
    global _bootstrap_cache
    baseurl = get_frontend_baseurl()
    if _bootstrap_cache is not None and _bootstrap_cache[0] == baseurl:
        return _bootstrap_cache[1]

    payload = {
        "frontend_baseurl": baseurl,
    }
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    script = f"""
<script>
(function() {{
  'use strict';

  if (window.__FRONTEND_BOOTSTRAPPED__) return;
  window.__FRONTEND_BOOTSTRAPPED__ = true;

  var payload = {payload_json};
  var baseUrl = typeof payload.frontend_baseurl === 'string' ? payload.frontend_baseurl.replace(/\\/$/, '') : '';

  function isAbsoluteUrl(url) {{
    return /^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith('//');
  }}

  function shouldBypass(url) {{
    return !url || isAbsoluteUrl(url) || url.startsWith('data:') || url.startsWith('blob:') || url.startsWith('#');
  }}

  function resolveUrl(url) {{
    if (typeof url !== 'string' || !baseUrl || shouldBypass(url)) return url;
    try {{
      if (url.startsWith('/')) return baseUrl + url;
      return new URL(url, baseUrl + '/').toString();
    }} catch (_err) {{
      return url;
    }}
  }}

  window.__FRONTEND_CONFIG__ = Object.assign({{}}, window.__FRONTEND_CONFIG__ || {{}}, payload, {{
    resolveUrl: resolveUrl,
  }});
  window.projResolveUrl = resolveUrl;

  if (!window.__FETCH_PATCHED__ && typeof window.fetch === 'function') {{
    var originalFetch = window.fetch.bind(window);
    window.fetch = function(input, init) {{
      if (typeof input === 'string') {{
        return originalFetch(resolveUrl(input), init);
      }}
      if (input instanceof URL) {{
        return originalFetch(new URL(resolveUrl(String(input))), init);
      }}
      if (typeof Request !== 'undefined' && input instanceof Request) {{
        return originalFetch(new Request(resolveUrl(input.url), input), init);
      }}
      return originalFetch(input, init);
    }};
    window.__FETCH_PATCHED__ = true;
  }}

  if (!window.__XHR_PATCHED__ && window.XMLHttpRequest && window.XMLHttpRequest.prototype && window.XMLHttpRequest.prototype.open) {{
    var originalOpen = window.XMLHttpRequest.prototype.open;
    window.XMLHttpRequest.prototype.open = function(method, url) {{
      if (typeof url === 'string') {{
        arguments[1] = resolveUrl(url);
      }}
      return originalOpen.apply(this, arguments);
    }};
    window.__XHR_PATCHED__ = true;
  }}
}})();
</script>
""".strip()
    _bootstrap_cache = (baseurl, script)
    return script

def inject_frontend_config(html: str) -> str:
    script = build_frontend_bootstrap_script()
    lower_html = html.lower()
    head_close_idx = lower_html.find("</head>")
    if head_close_idx >= 0:
        return html[:head_close_idx] + script + "\n" + html[head_close_idx:]
    body_open_idx = lower_html.find("<body")
    if body_open_idx >= 0:
        body_tag_end = html.find(">", body_open_idx)
        if body_tag_end >= 0:
            insert_idx = body_tag_end + 1
            return html[:insert_idx] + "\n" + script + html[insert_idx:]
    return script + "\n" + html


def html_response_from_content(
    html: str,
    *,
    source_path: Path | None = None,
    cache_key: str | None = None,
) -> HTMLResponse:
    baseurl = get_frontend_baseurl()
    content_signature = hashlib.sha256(html.encode("utf-8")).hexdigest()
    resolved_cache_key = cache_key or _content_cache_key(html, source_path=source_path)
    cached_html = _get_cached_content_html(
        resolved_cache_key,
        content_signature=content_signature,
        baseurl=baseurl,
    )
    if cached_html is not None:
        return HTMLResponse(cached_html)

    prepared_html, dependencies = _prepare_html_content(html, source_path=source_path)
    _store_cached_content_html(
        resolved_cache_key,
        content_signature=content_signature,
        baseurl=baseurl,
        dependencies=dependencies,
        html_text=prepared_html,
    )
    return HTMLResponse(prepared_html)


def _extract_tag_content(html: str, tag: str) -> str:
  """Extract inner content of the first occurrence of <tag>...</tag>."""
  start_tag = html.lower().find(f"<{tag}")
  if start_tag < 0:
    return ""
  close_bracket = html.find(">", start_tag)
  if close_bracket < 0:
    return ""
  end_tag = html.lower().rfind(f"</{tag}>")
  if end_tag < 0:
    return ""
  return html[close_bracket + 1:end_tag]


_ADAPTIVE_HTML_CSS = """\
<style data-proj-adaptive>
#__desktop_branch__ { display: block; }
#__mobile_branch__  { display: none; }
@media (max-width: 767px) {
  #__desktop_branch__ { display: none !important; }
  #__mobile_branch__  { display: block !important; }
}
</style>
"""

_ADAPTIVE_HTML_SCRIPT = """\
<script data-proj-adaptive>
(function() {
  function _kpUpdateAdaptive() {
    var isMobile = window.innerWidth < 768;
    var d = document.getElementById('__desktop_branch__');
    var m = document.getElementById('__mobile_branch__');
    if (d) d.style.display = isMobile ? 'none' : '';
    if (m) m.style.display = isMobile ? '' : 'none';
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _kpUpdateAdaptive);
  } else {
    _kpUpdateAdaptive();
  }
  window.addEventListener('resize', _kpUpdateAdaptive);
})();
</script>
"""


def merge_desktop_mobile_html(desktop_html: str, mobile_html: str) -> str:
  """Wrap desktop and mobile body contents in toggleable divs with CSS/JS."""
  desktop_body = _extract_tag_content(desktop_html, "body")
  mobile_body = _extract_tag_content(mobile_html, "body")

  # Find where to inject: before </body> in desktop html
  body_close = desktop_html.lower().rfind("</body>")
  if body_close < 0:
    return desktop_html

  body_open = desktop_html.lower().find("<body")
  if body_open < 0:
    return desktop_html
  body_tag_end = desktop_html.find(">", body_open)
  if body_tag_end < 0:
    return desktop_html

  # Inject CSS before </head>
  head_close = desktop_html.lower().rfind("</head>")
  if head_close >= 0:
    desktop_html = (
      desktop_html[:head_close]
      + _ADAPTIVE_HTML_CSS
      + desktop_html[head_close:]
    )
    body_close = desktop_html.lower().rfind("</body>")
    body_open = desktop_html.lower().find("<body")
    body_tag_end = desktop_html.find(">", body_open)

  merged = (
    desktop_html[:body_tag_end + 1]
    + '\n<div id="__desktop_branch__">\n'
    + desktop_body
    + '\n</div>\n<div id="__mobile_branch__" style="display:none;">\n'
    + mobile_body
    + '\n</div>\n'
    + _ADAPTIVE_HTML_SCRIPT
    + desktop_html[body_close:]
  )
  return merged


# Cache for merged adaptive HTML: key -> (desktop_mtime, mobile_mtime, baseurl, dependencies, html)
_adaptive_page_cache: dict[str, tuple[float, float, str | None, _DependencySnapshot, str]] = {}


def html_response_from_path(path: Path, *, not_found_message: str | None = None) -> HTMLResponse:
  if not path.is_file():
    raise HTTPException(404, not_found_message or f"{path.name} not found")

  path_key = str(path)
  try:
    mtime = path.stat().st_mtime
  except OSError:
    raise HTTPException(404, not_found_message or f"{path.name} not found")

  baseurl = get_frontend_baseurl()
  cached = _page_cache.get(path_key)
  if cached is not None:
    cached_mtime, cached_baseurl, cached_dependencies, cached_html = cached
    if cached_mtime == mtime and cached_baseurl == baseurl and _dependencies_unchanged(cached_dependencies):
      return HTMLResponse(cached_html)

  html = path.read_text(encoding="utf-8")
  prepared_html, dependencies = _prepare_html_content(html, source_path=path)
  _page_cache[path_key] = (mtime, baseurl, dependencies, prepared_html)
  return HTMLResponse(prepared_html)


def html_response_from_path_with_mobile(path: Path, *, not_found_message: str | None = None) -> HTMLResponse:
  """Serve HTML with automatic .m.html mobile branch merging."""
  if not path.is_file():
    raise HTTPException(404, not_found_message or f"{path.name} not found")

  path_key = str(path)
  mobile_path = path.with_suffix(".m.html")
  has_mobile = mobile_path.is_file()

  try:
    mtime = path.stat().st_mtime
    mobile_mtime = mobile_path.stat().st_mtime if has_mobile else 0.0
  except OSError:
    raise HTTPException(404, not_found_message or f"{path.name} not found")

  baseurl = get_frontend_baseurl()

  if has_mobile:
    cache_key = f"adaptive:{path_key}"
    cached = _adaptive_page_cache.get(cache_key)
    if cached is not None:
      cached_dmt, cached_mmt, cached_baseurl, cached_dependencies, cached_html = cached
      if (cached_dmt == mtime and cached_mmt == mobile_mtime
          and cached_baseurl == baseurl
          and _dependencies_unchanged(cached_dependencies)):
        return HTMLResponse(cached_html)

    desktop_html = path.read_text(encoding="utf-8")
    mobile_html = mobile_path.read_text(encoding="utf-8")
    merged = merge_desktop_mobile_html(desktop_html, mobile_html)
    prepared_html, dependencies = _prepare_html_content(merged, source_path=path)
    _adaptive_page_cache[cache_key] = (mtime, mobile_mtime, baseurl, dependencies, prepared_html)
    return HTMLResponse(prepared_html)

  # No mobile variant — fall through to standard path
  cached = _page_cache.get(path_key)
  if cached is not None:
    cached_mtime, cached_baseurl, cached_dependencies, cached_html = cached
    if cached_mtime == mtime and cached_baseurl == baseurl and _dependencies_unchanged(cached_dependencies):
      return HTMLResponse(cached_html)

  html = path.read_text(encoding="utf-8")
  prepared_html, dependencies = _prepare_html_content(html, source_path=path)
  _page_cache[path_key] = (mtime, baseurl, dependencies, prepared_html)
  return HTMLResponse(prepared_html)
