# -*- coding: utf-8 -*-
"""Panel page, vendor static files, server config, and room list routes.
System monitoring APIs live under the system route package.
"""
import copy
import html
import json
import os
import mimetypes
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from core.rtc_chat.room import (
    RoomInfo,
    WebRTCRoom,
)
from core.utils.type_utils import AdvancedBaseModel
from core.server.constants import ADMIN_PANEL_SHARED_DIR, PUBLIC_DIR
from core.server.data_types.config import Config
from ...html_injection import html_response_from_path
from ...app import get_resources, on_before_app_created, ensure_openapi_customization, redirect_to_worker
from ...shared import AppSharedData
from ...translate import get_all_public_translations, get_internal_translation, get_internal_translation_catalog, normalize_language
from .backend import register_backend_panel_routes


_SWAGGER_UI_CSS_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
_SWAGGER_UI_BUNDLE_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"
_SWAGGER_UI_LAYOUT = "BaseLayout"
_SWAGGER_UI_DEFAULT_PARAMETERS: dict[str, Any] = {
    "deepLinking": True,
    "docExpansion": "list",
    "defaultModelsExpandDepth": 1,
    "defaultModelExpandDepth": 1,
    "showExtensions": True,
    "showCommonExtensions": True,
}
_SWAGGER_UI_THEME_STORAGE_KEY = "panel-dark"

def _json_for_html_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

def _internal_admin_path(path: str = "") -> str:
    return Config.GetConfig().server_config.get_internal_admin_path(path)

def _internal_path(path: str = "") -> str:
    return Config.GetConfig().server_config.get_internal_path(path)

def _safe_locale_segment(value: str) -> str:
    text = normalize_language(value)
    if not text or "/" in text or "\\" in text or text.startswith("."):
        raise HTTPException(404, "Locale not found")
    return text

def _safe_locale_category(value: str | None) -> str:
    text = str(value or "default").strip().lower()
    if not text or "/" in text or "\\" in text or text.startswith("."):
        raise HTTPException(404, "Locale category not found")
    return text

def _load_locale_file(category: str | None, lang: str) -> dict[str, Any]:
    language = _safe_locale_segment(lang)
    category_name = _safe_locale_category(category)
    root = PUBLIC_DIR / "locales"
    candidates = []
    if category is not None:
        candidates.append(root / category_name / f"{language}.json")
    candidates.append(root / f"{language}.json")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(500, f"Invalid locale file: {path.name}") from exc
        if not isinstance(payload, dict):
            raise HTTPException(500, f"Locale file must contain an object: {path.name}")
        return payload
    return {}

def _swagger_ui_config_lines(spec_expr: str) -> str:
    config_lines = [
        f"        spec: {spec_expr},",
        '        dom_id: "#swagger-ui",',
        f'        layout: "{_SWAGGER_UI_LAYOUT}",',
    ]
    for key, value in _SWAGGER_UI_DEFAULT_PARAMETERS.items():
        config_lines.append(f"        {key}: {_json_for_html_script(value)},")
    config_lines.extend([
        "        presets: [",
        "            SwaggerUIBundle.presets.apis,",
        "            SwaggerUIBundle.SwaggerUIStandalonePreset,",
        "        ],",
    ])
    return "\n".join(config_lines)

def _resolve_admin_test_html(*parts: str) -> HTMLResponse:
    test_root_path = get_resources("admin-panel", "test")
    if test_root_path is None:
        raise HTTPException(404, "test page not found")
    test_root = test_root_path.resolve()
    relative = Path(*parts)
    candidates: list[Path] = []
    if len(relative.parts) == 1 and relative.suffix == "":
        candidates.append(Path(f"test_{relative.name}.html"))
    candidates.append(relative)
    if relative.suffix == "":
        candidates.append(relative.with_suffix(".html"))
    for rel in candidates:
        try:
            path = (test_root / rel).resolve()
            path.relative_to(test_root)
        except Exception:
            continue
        if path.is_file() and path.suffix.lower() == ".html":
            return html_response_from_path(path, not_found_message=f"admin test page not found: {'/'.join(parts)}")
    raise HTTPException(404, f"Admin test page not found: {'/'.join(parts)}")

def _build_swagger_doc_enhancements(*, include_export_tools: bool) -> str:
        full_export_path = _internal_admin_path("panel/api/export/full")
        public_export_path = _internal_admin_path("panel/api/export/public")
        tools_markup = "" if not include_export_tools else f"""
<div class=\"proj-doc-export-tools\">
    <a class=\"proj-doc-export-tools__button\" href=\"{full_export_path}\">导出完整API文档HTML<span class=\"proj-doc-export-tools__meta\">包含所有内部路由、调试路由与未公开 API 的完整文档</span></a>
    <a class=\"proj-doc-export-tools__button proj-doc-export-tools__button--alt\" href=\"{public_export_path}\">导出非内部API文档HTML<span class=\"proj-doc-export-tools__meta\">自动排除所有 internal prefix 路由，仅保留对外 API 文档</span></a>
</div>
"""
        return f"""
<style id=\"proj-openapi-enhancements\">
    :root {{
        --proj-doc-bg: #f3f6fb;
        --proj-doc-surface: rgba(255, 255, 255, 0.94);
        --proj-doc-surface-strong: #ffffff;
        --proj-doc-border: rgba(15, 23, 42, 0.10);
        --proj-doc-text: #0f172a;
        --proj-doc-muted: #475569;
        --proj-doc-shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
    }}
    html.proj-openapi-dark {{
        --proj-doc-bg: #0b1220;
        --proj-doc-surface: rgba(15, 23, 42, 0.92);
        --proj-doc-surface-strong: rgba(15, 23, 42, 0.98);
        --proj-doc-border: rgba(148, 163, 184, 0.20);
        --proj-doc-text: #e2e8f0;
        --proj-doc-muted: #94a3b8;
        --proj-doc-shadow: 0 18px 44px rgba(2, 6, 23, 0.42);
    }}
    html, body {{
        margin: 0;
        background: var(--proj-doc-bg);
        color: var(--proj-doc-text);
    }}
    body.proj-openapi-page {{
        background: var(--proj-doc-bg);
        color: var(--proj-doc-text);
    }}
    body.proj-openapi-page .swagger-ui {{
        color: var(--proj-doc-text);
        font-family: "Segoe UI", "PingFang SC", sans-serif;
        font-size: 12px;
    }}
    body.proj-openapi-page .swagger-ui .topbar {{
        display: none;
    }}
    body.proj-openapi-page .swagger-ui .wrapper {{
        max-width: none;
    }}
    body.proj-openapi-page .swagger-ui > div > .wrapper,
    body.proj-openapi-page .swagger-ui > div > .information-container.wrapper,
    body.proj-openapi-page .swagger-ui > div > .webhooks-container.wrapper {{
        padding: 10px 14px 16px;
    }}
    body.proj-openapi-page .swagger-ui > div > .information-container.wrapper {{
        padding-bottom: 0;
    }}
    body.proj-openapi-page .swagger-ui .scheme-container .schemes.wrapper {{
        padding: 0;
    }}
    body.proj-openapi-page .swagger-ui > div > .webhooks-container.wrapper:empty,
    body.proj-openapi-page .swagger-ui > div > .wrapper:empty {{
        display: none;
    }}
    body.proj-openapi-page .swagger-ui .scheme-container {{
        margin: 0 0 10px;
        padding: 8px 12px;
        border: 1px solid var(--proj-doc-border);
        border-radius: 14px;
        background: var(--proj-doc-surface);
        box-shadow: none;
    }}
    body.proj-openapi-page .swagger-ui .info {{
        margin: 0 0 12px;
    }}
    body.proj-openapi-page .swagger-ui .info .title {{
        margin: 0 0 4px;
        color: var(--proj-doc-text);
        font-size: 22px;
        line-height: 1.1;
    }}
    body.proj-openapi-page .swagger-ui .info .title small {{
        display: inline-flex;
        align-items: center;
        margin: 0 0 0 8px;
        vertical-align: middle;
    }}
    body.proj-openapi-page .swagger-ui .info .title .version,
    body.proj-openapi-page .swagger-ui .info .title .version-stamp {{
        display: inline-flex;
        align-items: center;
        margin: 0;
        line-height: 1;
        vertical-align: middle;
    }}
    body.proj-openapi-page .swagger-ui .info .main {{
        margin: 0 0 6px;
    }}
    body.proj-openapi-page .swagger-ui .info .base-url {{
        margin: 0 0 8px;
        padding: 0;
        color: var(--proj-doc-muted);
        line-height: 1.35;
    }}
    body.proj-openapi-page .swagger-ui .info .description,
    body.proj-openapi-page .swagger-ui .info .markdown,
    body.proj-openapi-page .swagger-ui .info .renderedMarkdown {{
        margin: 0;
    }}
    body.proj-openapi-page .swagger-ui .info p,
    body.proj-openapi-page .swagger-ui .info li,
    body.proj-openapi-page .swagger-ui .markdown p,
    body.proj-openapi-page .swagger-ui .markdown li {{
        margin: 0 0 6px;
        color: var(--proj-doc-muted);
        font-size: 12px;
        line-height: 1.5;
    }}
    body.proj-openapi-page .swagger-ui .opblock-tag-section {{
        margin: 0;
    }}
    body.proj-openapi-page .swagger-ui .opblock-tag {{
        margin: 0;
        padding: 10px 12px 8px;
        border-bottom: 1px solid var(--proj-doc-border);
        color: var(--proj-doc-text);
        font-size: 13px;
        font-weight: 700;
    }}
    body.proj-openapi-page .swagger-ui .opblock {{
        margin: 0 0 8px;
        border-radius: 14px;
        border-width: 1px;
        box-shadow: none;
        overflow: hidden;
    }}
    body.proj-openapi-page .swagger-ui .opblock .opblock-summary {{
        padding: 6px 10px;
        align-items: center;
    }}
    body.proj-openapi-page .swagger-ui .opblock .opblock-summary-method {{
        min-width: 56px;
        padding: 4px 8px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 700;
    }}
    body.proj-openapi-page .swagger-ui .opblock .opblock-summary-path {{
        font-size: 12px;
        font-weight: 700;
    }}
    body.proj-openapi-page .swagger-ui .opblock .opblock-summary-description {{
        color: var(--proj-doc-muted);
        font-size: 11px;
    }}
    body.proj-openapi-page .swagger-ui .opblock .opblock-body {{
        padding: 8px 10px 10px;
        background: var(--proj-doc-surface-strong);
    }}
    body.proj-openapi-page .swagger-ui .parameters-col_description p,
    body.proj-openapi-page .swagger-ui .response-col_description__inner p,
    body.proj-openapi-page .swagger-ui .model {{
        font-size: 11px;
    }}
    body.proj-openapi-page .swagger-ui section.models {{
        margin: 10px 0 0;
        border: 1px solid var(--proj-doc-border);
        border-radius: 14px;
        background: var(--proj-doc-surface);
        box-shadow: none;
    }}
    body.proj-openapi-page .swagger-ui .model-box,
    body.proj-openapi-page .swagger-ui .responses-table,
    body.proj-openapi-page .swagger-ui table tbody tr td,
    body.proj-openapi-page .swagger-ui table tbody tr th {{
        font-size: 11px;
    }}
    body.proj-openapi-page .swagger-ui select,
    body.proj-openapi-page .swagger-ui input[type=text],
    body.proj-openapi-page .swagger-ui textarea {{
        min-height: 30px;
        padding: 6px 8px;
        border-radius: 10px;
    }}
    body.proj-openapi-page .swagger-ui .btn {{
        min-height: 30px;
        padding: 6px 10px;
        border-radius: 10px;
        font-size: 11px;
    }}
    body.proj-openapi-page.proj-openapi-dark .swagger-ui,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .info .title,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .info p,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .info li,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .info .base-url,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .info a,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock-tag,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock-tag small,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .model-title,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .model-title__text,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .model .property.primitive,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .prop-type,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .prop-format,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .responses-inner h4,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .responses-inner h5,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .response-col_status,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .response-col_description,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .response-col_links,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .tab li,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .tab li.active,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui label,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui th,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui td,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .parameter__name,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .parameter__type,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .parameter__in,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .parameter__deprecated,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock .opblock-summary-path,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock .opblock-summary-path__deprecated,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock .opblock-summary-operation-id,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock .opblock-summary-description,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock .opblock-section-header h4,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock .opblock-section-header>label,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock-description-wrapper p,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock-external-docs-wrapper p,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock-title_normal p,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .markdown p,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .markdown li,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .renderedMarkdown p,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .scheme-container .schemes>label,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .servers>label,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .servers-title,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .server-item,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .dialog-ux .modal-ux-header h3,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .dialog-ux .modal-ux-content h4,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .dialog-ux .modal-ux-content p,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .dialog-ux .modal-ux-header .close-modal,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .version-pragma,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .highlight-code>.microlight,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .microlight,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .model-box-control,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .model-hint {{
        color: var(--proj-doc-text);
    }}
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .scheme-container,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui .opblock .opblock-body {{
        background: var(--proj-doc-surface);
    }}
    body.proj-openapi-page.proj-openapi-dark .swagger-ui input[type=text],
    body.proj-openapi-page.proj-openapi-dark .swagger-ui textarea,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui select {{
        background: rgba(15, 23, 42, 0.9);
        color: var(--proj-doc-text);
        border-color: var(--proj-doc-border);
    }}
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .models-control,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-container,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-box,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-box .model-jump-to-path,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-box-control,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models button,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models summary {{
        background: transparent;
        color: var(--proj-doc-text);
        border-color: var(--proj-doc-border);
        box-shadow: none;
    }}
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-container,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-box {{
        background: color-mix(in srgb, var(--proj-doc-surface-strong) 86%, transparent);
    }}
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .models-control,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-box-control,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models button {{
        color: var(--proj-doc-muted);
    }}
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-box-control:focus,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models .model-box-control:hover,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models button:focus,
    body.proj-openapi-page.proj-openapi-dark .swagger-ui section.models button:hover {{
        background: rgba(148, 163, 184, 0.12);
        color: var(--proj-doc-text);
        outline: none;
    }}
    .proj-doc-export-tools {{
        position: fixed;
        right: 14px;
        bottom: 14px;
        z-index: 9999;
        display: flex;
        flex-direction: column;
        gap: 8px;
        align-items: stretch;
    }}
    .proj-doc-export-tools__button {{
        min-width: 184px;
        padding: 10px 12px;
        border-radius: 12px;
        border: 1px solid var(--proj-doc-border);
        background: var(--proj-doc-surface-strong);
        box-shadow: var(--proj-doc-shadow);
        color: var(--proj-doc-text);
        text-decoration: none;
        font: 700 12px/1.3 "Segoe UI", "PingFang SC", sans-serif;
    }}
    .proj-doc-export-tools__button--alt {{
        border-color: rgba(37, 99, 235, 0.22);
    }}
    .proj-doc-export-tools__meta {{
        display: block;
        margin-top: 2px;
        color: var(--proj-doc-muted);
        font-size: 10px;
        font-weight: 500;
    }}
</style>
<script id=\"proj-openapi-theme-sync\">
    (() => {{
        const storageKey = {_json_for_html_script(_SWAGGER_UI_THEME_STORAGE_KEY)};
        const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
        const shouldUseDark = () => {{
            try {{
                const stored = window.localStorage.getItem(storageKey);
                if (stored !== null) return stored !== 'false';
                if (window.location.protocol !== 'file:') return true;
            }} catch (_error) {{
            }}
            return !!(media && media.matches);
        }};
        const applyTheme = () => {{
            const dark = shouldUseDark();
            document.documentElement.classList.toggle('proj-openapi-dark', dark);
            document.body.classList.add('proj-openapi-page');
            document.body.classList.toggle('proj-openapi-dark', dark);
        }};
        applyTheme();
        window.addEventListener('storage', (event) => {{
            if (!event.key || event.key === storageKey) applyTheme();
        }});
        if (media) {{
            const onChange = () => applyTheme();
            if (typeof media.addEventListener === 'function') media.addEventListener('change', onChange);
            else if (typeof media.addListener === 'function') media.addListener(onChange);
        }}
    }})();
</script>
{tools_markup}
"""

def _build_swagger_export_html(*, spec: dict[str, Any], title: str) -> str:
    escaped_title = html.escape(title)
    spec_json = _json_for_html_script(spec)
    return f"""<!DOCTYPE html>
<html lang=\"zh-cn\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <title>{escaped_title}</title>
  <link type=\"text/css\" rel=\"stylesheet\" href=\"{_SWAGGER_UI_CSS_URL}\">
    {_build_swagger_doc_enhancements(include_export_tools=False)}
</head>
<body>
  <div id=\"swagger-ui\"></div>
  <script src=\"{_SWAGGER_UI_BUNDLE_URL}\"></script>
  <script>
    const spec = {spec_json};
    window.ui = SwaggerUIBundle({{
{_swagger_ui_config_lines('spec')}
    }});
  </script>
</body>
</html>
"""

def _parse_component_ref(ref: str) -> tuple[str, str] | None:
    if not ref.startswith("#/components/"):
        return None
    parts = ref.split("/")
    if len(parts) != 4:
        return None
    return parts[2], parts[3]

def _collect_component_refs(value: Any, refs: set[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            parsed = _parse_component_ref(ref)
            if parsed is not None:
                refs.add(parsed)
        for nested in value.values():
            _collect_component_refs(nested, refs)
        return
    if isinstance(value, list):
        for item in value:
            _collect_component_refs(item, refs)

def _collect_security_scheme_names(spec: dict[str, Any]) -> set[str]:
    names: set[str] = set()

    def _visit_security_block(block: Any) -> None:
        if not isinstance(block, list):
            return
        for item in block:
            if isinstance(item, dict):
                for key in item.keys():
                    if isinstance(key, str):
                        names.add(key)
    _visit_security_block(spec.get("security"))
    for path_item in spec.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if isinstance(operation, dict):
                _visit_security_block(operation.get("security"))
    return names

def _prune_components_for_spec(spec: dict[str, Any], source_components: dict[str, Any]) -> dict[str, Any]:
    pending_refs: set[tuple[str, str]] = set()
    _collect_component_refs(spec.get("paths", {}), pending_refs)
    _collect_component_refs(spec.get("webhooks", {}), pending_refs)
    kept_components: dict[str, dict[str, Any]] = {}
    processed: set[tuple[str, str]] = set()
    while pending_refs:
        section, name = pending_refs.pop()
        if (section, name) in processed:
            continue
        processed.add((section, name))
        section_items = source_components.get(section)
        if not isinstance(section_items, dict) or name not in section_items:
            continue
        component_value = copy.deepcopy(section_items[name])
        kept_components.setdefault(section, {})[name] = component_value
        nested_refs: set[tuple[str, str]] = set()
        _collect_component_refs(component_value, nested_refs)
        pending_refs.update(nested_refs - processed)
    security_scheme_names = _collect_security_scheme_names(spec)
    if security_scheme_names:
        source_security = source_components.get("securitySchemes")
        if isinstance(source_security, dict):
            kept_security = {
                name: copy.deepcopy(source_security[name])
                for name in security_scheme_names
                if name in source_security
            }
            if kept_security:
                kept_components["securitySchemes"] = kept_security
    return kept_components

def _prune_internal_paths_from_openapi(
    spec: dict[str, Any],
    *,
    internal_path_prefix: str | None = None,
) -> dict[str, Any]:
    prefix = "/" + str(internal_path_prefix or Config.GetConfig().server_config.internal_path_prefix or "/_internal").strip("/")
    prefix_root = prefix.rstrip("/")

    def _is_internal_path(path: str) -> bool:
        normalized = "/" + str(path or "").lstrip("/")
        return normalized == prefix_root or normalized.startswith(prefix_root + "/")

    filtered_paths = {
        path: copy.deepcopy(path_item)
        for path, path_item in spec.get("paths", {}).items()
        if isinstance(path, str) and not _is_internal_path(path)
    }
    pruned_spec = {
        key: copy.deepcopy(value)
        for key, value in spec.items()
        if key not in {"paths", "components", "tags"}
    }
    pruned_spec["paths"] = filtered_paths
    source_components = spec.get("components")
    if isinstance(source_components, dict):
        kept_components = _prune_components_for_spec(pruned_spec, source_components)
        if kept_components:
            pruned_spec["components"] = kept_components
    source_tags = spec.get("tags")
    if isinstance(source_tags, list):
        used_tags: set[str] = set()
        for path_item in filtered_paths.values():
            if not isinstance(path_item, dict):
                continue
            for operation in path_item.values():
                if isinstance(operation, dict):
                    for tag in operation.get("tags") or []:
                        if isinstance(tag, str):
                            used_tags.add(tag)
        kept_tags = [tag for tag in source_tags if isinstance(tag, dict) and tag.get("name") in used_tags]
        if kept_tags:
            pruned_spec["tags"] = kept_tags
    return pruned_spec

def _inject_panel_api_doc_tools(swagger_html: str) -> str:
        return swagger_html.replace("</body>", f"{_build_swagger_doc_enhancements(include_export_tools=True)}\n</body>")
# ══════════════════════════════════════════════════════════════════════════════
# Route registration
# ══════════════════════════════════════════════════════════════════════════════
@on_before_app_created

def register_panel_routes(app: FastAPI):
    ensure_openapi_customization(app)
    register_backend_panel_routes(app)

    def _resolve_static_file(base_dir, file_path: str):
        try:
            base = base_dir.resolve()
            full = (base_dir / file_path).resolve()
            full.relative_to(base)
        except Exception:
            return None
        return full if full.is_file() else None

    def _resolve_html_shared_file(file_path: str):
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
    @app.get(_internal_path("html-assets/{file_path:path}"))

    async def serve_html_assets(file_path: str):
        """Serve shared HTML-layer assets from server/html/shared/."""
        full = _resolve_html_shared_file(file_path)
        if full is None:
            raise HTTPException(404, "File not found")
        media_type, _ = mimetypes.guess_type(str(full))
        return FileResponse(full, media_type=media_type or "application/octet-stream")
    # ---- Panel pages ----
    @app.get(_internal_admin_path("panel"), response_class=HTMLResponse)

    async def panel_html():
        """Management panel."""
        panel_path = get_resources("admin-panel", "panel.html") or Path("panel.html")
        return html_response_from_path(panel_path, not_found_message="panel.html not found")
    @app.get(_internal_admin_path("panel/api"), response_class=HTMLResponse)

    async def panel_api_docs() -> HTMLResponse:
        swagger_response = get_swagger_ui_html(
            openapi_url=_internal_admin_path("openapi.json"),
            title=f"{app.title} - API",
            swagger_ui_parameters=_SWAGGER_UI_DEFAULT_PARAMETERS,
        )
        return HTMLResponse(
            _inject_panel_api_doc_tools(swagger_response.body.decode("utf-8")),
            status_code=swagger_response.status_code,
        )
    @app.get(_internal_admin_path("panel/api/export/full"), response_class=HTMLResponse, include_in_schema=False)

    async def panel_api_docs_export_full() -> HTMLResponse:
        spec = copy.deepcopy(app.openapi())
        html_body = _build_swagger_export_html(
            spec=spec,
            title=f"{app.title} - API 文档",
        )
        return HTMLResponse(
            html_body,
            headers={"Content-Disposition": 'attachment; filename="proj-template-api-docs.html"'},
        )
    @app.get(_internal_admin_path("panel/api/export/public"), response_class=HTMLResponse, include_in_schema=False)

    async def panel_api_docs_export_public() -> HTMLResponse:
        spec = _prune_internal_paths_from_openapi(copy.deepcopy(app.openapi()))
        html_body = _build_swagger_export_html(
            spec=spec,
            title=f"{app.title} - API 文档（非内部路由）",
        )
        return HTMLResponse(
            html_body,
            headers={"Content-Disposition": 'attachment; filename="proj-template-api-docs-no-internal.html"'},
        )
    # ---- Server config ----

    class ServerConfigInfo(AdvancedBaseModel):
        host: str
        """Bind host."""
        port: int
        """Bind port."""
        frontend_baseurl: str | None = None
        """Optional frontend base URL."""
        internal_path_prefix: str
        """Internal path prefix (e.g. /_internal)."""
        expose_ai_service: bool = False
        """Whether public AI service routes are exposed."""
    @app.get(_internal_admin_path("api/server/config"), response_model=ServerConfigInfo)

    async def server_config_info() -> ServerConfigInfo:
        cfg = Config.GetConfig().server_config
        mode = "prod" if os.getenv("PRODUCTION") else "dev"
        return ServerConfigInfo(
            host=cfg.get_host(mode),
            port=cfg.port if cfg.port > 0 else 8000,
            frontend_baseurl=cfg.get_frontend_baseurl(),
            internal_path_prefix=cfg.internal_path_prefix,
            expose_ai_service=cfg.expose_ai_service,
        )
    # ---- Room list (panel needs it) ----
    @app.get(_internal_admin_path("test/ai"), response_class=HTMLResponse)

    async def admin_test_ai_index() -> HTMLResponse:
        return _resolve_admin_test_html("ai")
    @app.get(_internal_admin_path("test/ai/{page_path:path}"), response_class=HTMLResponse)

    async def admin_test_ai_page(page_path: str) -> HTMLResponse:
        return _resolve_admin_test_html("ai", page_path)

    class PaginatedRooms(AdvancedBaseModel):
        items: list[dict]
        """Room items list."""
        total: int
        """Total count."""
        page: int
        """Current page."""
        page_size: int = 10
        """Items per page."""
    @app.get(_internal_admin_path("api/rooms"), response_model=PaginatedRooms)

    async def list_rooms(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100)) -> PaginatedRooms:
        """List all active rooms (paginated)."""
        all_rooms = AppSharedData.Get().get_all_room_info()
        total = len(all_rooms)
        start = (page - 1) * page_size
        items = [r.model_dump() for r in all_rooms[start : start + page_size]]
        return PaginatedRooms(items=items, total=total, page=page, page_size=page_size)
    @app.get(_internal_admin_path("api/rooms/{room_id}"), response_model=RoomInfo)

    async def get_room_detail(room_id: str, request: Request) -> RoomInfo:
        """Return full room details for the requested room."""
        shared = AppSharedData.Get()
        worker_id = shared.get_room_worker(room_id)
        if worker_id is None:
            raise HTTPException(404, f"Room not found: {room_id}")
        if worker_id != os.getpid():
            return await redirect_to_worker(worker_id, request, {"room_id": room_id})
        room = WebRTCRoom.GetRoom(room_id)
        if room is None:
            shared.delete_room_worker(room_id)
            raise HTTPException(404, f"Room not found: {room_id}")
        return room.dump_info()
    @app.delete(_internal_admin_path("api/rooms/{room_id}"))

    async def delete_room(room_id: str, request: Request) -> dict[str, object]:
        """Force-close a room and remove its worker mapping."""
        shared = AppSharedData.Get()
        worker_id = shared.get_room_worker(room_id)
        if worker_id is None:
            raise HTTPException(404, f"Room not found: {room_id}")
        if worker_id != os.getpid():
            return await redirect_to_worker(worker_id, request, {"room_id": room_id})
        room = WebRTCRoom.GetRoom(room_id)
        if room is None:
            shared.delete_room_worker(room_id)
            raise HTTPException(404, f"Room not found: {room_id}")
        await room.close()
        shared.delete_room_worker(room_id)
        return {"ok": True, "id": room_id}
    # ---- UI translation ----

    class TranslateResponse(AdvancedBaseModel):
        translations: dict[str, str | None]
        """key -> translation, None if not found."""

    class AllTranslationsResponse(AdvancedBaseModel):
        translations: dict[str, dict[str, str]]
        """lang -> { key -> translation }"""

    @app.get("/locales/{category}/{lang}.json", response_class=JSONResponse)
    async def public_category_locale(category: str, lang: str) -> dict[str, Any]:
        file_payload = _load_locale_file(category, lang)
        registered_payload = get_all_public_translations(category, lang)
        return {**file_payload, **registered_payload}

    @app.get("/locales/{lang}.json", response_class=JSONResponse)
    async def public_default_locale(lang: str) -> dict[str, Any]:
        file_payload = _load_locale_file(None, lang)
        registered_payload = get_all_public_translations("default", lang)
        return {**file_payload, **registered_payload}

    @app.get(_internal_admin_path("api/ui_translate"), response_model=TranslateResponse)

    async def ui_translate(
        keys: str = Query(..., description="Comma-separated translation keys."),
        lang: str = Query('zh-tw', description="目标语言代码 (en / zh-cn / zh-tw)"),
    ) -> TranslateResponse:
        """Translate UI keys. Multiple keys can be comma-separated."""
        results: dict[str, str | None] = {}
        for key in keys.split(','):
            key = key.strip()
            if key:
                results[key] = get_internal_translation(key, lang)
        return TranslateResponse(translations=results)
    @app.get(_internal_admin_path("api/ui_translate/all"), response_model=AllTranslationsResponse)

    async def ui_translate_all() -> AllTranslationsResponse:
        """Return all available translations."""
        return AllTranslationsResponse(translations=get_internal_translation_catalog())
