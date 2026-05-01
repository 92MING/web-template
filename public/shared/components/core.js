/**
 * @fileoverview Core utilities, theming, and shared styles for pt-* web components.
 *
 * ## Theming
 * Call `setSharedTheme(true)` to enable dark mode. Components listen to the
 * `builtin-theme-change` event and inherit CSS variables set on `:root`.
 *
 * ## CSS Variables
 * - `--builtin-primary`, `--builtin-primary-hover`
 * - `--builtin-color-text`, `--builtin-color-muted`, `--builtin-color-danger`
 * - `--builtin-border`, `--builtin-border-soft`
 * - `--builtin-button-bg`, `--builtin-button-hover-bg`
 * - `--builtin-input-bg`, `--builtin-surface`, `--builtin-header-bg`, `--builtin-row-hover-bg`
 * - `--builtin-bg-subtle`
 * - `--builtin-radius`, `--builtin-radius-lg`
 * - `--builtin-font-family`, `--builtin-font-size`
 * - `--builtin-cell-padding`, `--builtin-form-gap`
 */

export const BUILTIN_STYLE_ID = "builtin-shared-component-styles";

export const _LIGHT_VARS = {
  "--builtin-color-text": "#111827",
  "--builtin-color-muted": "#6b7280",
  "--builtin-border": "#d1d5db",
  "--builtin-border-soft": "#e5e7eb",
  "--builtin-button-bg": "#ffffff",
  "--builtin-button-hover-bg": "#f9fafb",
  "--builtin-input-bg": "#ffffff",
  "--builtin-surface": "#ffffff",
  "--builtin-header-bg": "#f9fafb",
  "--builtin-bg-subtle": "#f3f4f6",
  "--builtin-row-hover-bg": "#f9fafb",
  "--builtin-primary": "#2563eb",
  "--builtin-primary-hover": "#1d4ed8",
  "--builtin-primary-soft": "#eff6ff",
  "--builtin-color-danger": "#b91c1c",
  "--builtin-success": "#16a34a",
  "--builtin-danger": "#dc2626",
  "--builtin-radius": "6px",
  "--builtin-radius-lg": "8px",
  "--builtin-font-family": 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  "--builtin-font-size": "14px",
  "--builtin-form-gap": "14px",
  "--builtin-cell-padding": "10px 12px",
};

export const _DARK_VARS = {
  "--builtin-color-text": "#e5e7eb",
  "--builtin-color-muted": "#9ca3af",
  "--builtin-border": "#374151",
  "--builtin-border-soft": "#4b5563",
  "--builtin-button-bg": "#1f2937",
  "--builtin-button-hover-bg": "#374151",
  "--builtin-input-bg": "#111827",
  "--builtin-surface": "#1f2937",
  "--builtin-header-bg": "#111827",
  "--builtin-bg-subtle": "#111827",
  "--builtin-row-hover-bg": "#374151",
  "--builtin-primary": "#3b82f6",
  "--builtin-primary-hover": "#60a5fa",
  "--builtin-primary-soft": "rgba(59, 130, 246, 0.18)",
  "--builtin-color-danger": "#f87171",
  "--builtin-success": "#22c55e",
  "--builtin-danger": "#f87171",
  "--builtin-radius": "6px",
  "--builtin-radius-lg": "8px",
  "--builtin-font-family": 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  "--builtin-font-size": "14px",
  "--builtin-form-gap": "14px",
  "--builtin-cell-padding": "10px 12px",
};

let _currentTheme = "light";

export function setSharedTheme(dark) {
  _currentTheme = dark ? "dark" : "light";
  const vars = dark ? _DARK_VARS : _LIGHT_VARS;
  const root = document.documentElement;
  Object.entries(vars).forEach(([key, value]) => root.style.setProperty(key, value));
  root.dataset.builtinTheme = _currentTheme;
  document.dispatchEvent(new CustomEvent("builtin-theme-change", { detail: { theme: _currentTheme, dark } }));
}

export function getSharedTheme() {
  return _currentTheme;
}

export function asArray(value) {
  if (Array.isArray(value)) return value;
  if (value === undefined || value === null || value === "") return [];
  return [value];
}

export function boolAttr(el, name, fallback = false) {
  if (!el.hasAttribute(name)) return fallback;
  const value = String(el.getAttribute(name) || "").toLowerCase();
  return !["false", "0", "no", "off"].includes(value);
}

export function parseJsonAttribute(el, name, fallback) {
  const raw = el.getAttribute(name);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch (_err) {
    return fallback;
  }
}

export function getByPath(obj, path, fallback = "") {
  if (!path) return fallback;
  const value = String(path).split(".").reduce((current, part) => (
    current && Object.prototype.hasOwnProperty.call(current, part) ? current[part] : undefined
  ), obj);
  return value === undefined || value === null ? fallback : value;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function normalizeColumns(columns, sample = {}) {
  const list = asArray(columns).filter(Boolean);
  if (list.length) {
    return list.map((column) => {
      if (typeof column === "string") return { key: column, label: titleCase(column), sortable: true };
      return Object.assign({ label: titleCase(column.key || ""), sortable: true }, column);
    }).filter((column) => column.key && !column.hidden);
  }
  return Object.keys(sample || {}).map((key) => ({ key, label: titleCase(key), sortable: true }));
}

export function titleCase(value) {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function installSharedStyles(root) {
  if (root.getElementById(BUILTIN_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = BUILTIN_STYLE_ID;
  style.textContent = `
    :host {
      color: var(--builtin-color-text, #111827);
      font-family: var(--builtin-font-family, Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
      font-size: var(--builtin-font-size, 14px);
      display: block;
    }
    * { box-sizing: border-box; }
    button, input, select, textarea { font: inherit; }
    button {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      min-height: 34px;
      padding: 0 10px;
      cursor: pointer;
    }
    button:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    button:disabled { cursor: not-allowed; opacity: .55; }
    input, select, textarea {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      min-height: 34px;
      padding: 6px 9px;
      width: 100%;
    }
    textarea { min-height: 88px; resize: vertical; }
    .builtin-muted { color: var(--builtin-color-muted, #6b7280); }
    .builtin-error { color: var(--builtin-color-danger, #b91c1c); }
    .builtin-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
    .builtin-toolbar-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .builtin-surface { border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); background: var(--builtin-surface, #ffffff); overflow: hidden; }
    .builtin-table-wrap { width: 100%; overflow: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); padding: var(--builtin-cell-padding, 10px 12px); text-align: left; vertical-align: middle; white-space: nowrap; }
    th { background: var(--builtin-header-bg, #f9fafb); color: var(--builtin-color-muted, #374151); font-weight: 650; position: sticky; top: 0; z-index: 1; }
    tr[data-clickable="true"] { cursor: pointer; }
    tr:hover td { background: var(--builtin-row-hover-bg, #f9fafb); }
    .builtin-density-compact { --builtin-cell-padding: 6px 8px; }
    .builtin-density-comfortable { --builtin-cell-padding: 12px 14px; }
    .builtin-cell-truncate { max-width: var(--builtin-truncate-width, 280px); overflow: hidden; text-overflow: ellipsis; }
    .builtin-status { padding: 28px; text-align: center; color: var(--builtin-color-muted, #6b7280); }
    .builtin-pager { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); flex-wrap: wrap; }
    .builtin-sort { border: 0; background: transparent; padding: 0; min-height: 0; color: inherit; display: inline-flex; align-items: center; gap: 6px; }
    .builtin-actions { display: inline-flex; align-items: center; gap: 6px; }
    .builtin-form { display: grid; gap: var(--builtin-form-gap, 14px); }
    .builtin-grid { display: grid; grid-template-columns: repeat(var(--builtin-columns, 1), minmax(0, 1fr)); gap: var(--builtin-form-gap, 14px); }
    .builtin-field { display: grid; gap: 6px; align-content: start; }
    .builtin-label { font-weight: 650; color: var(--builtin-color-text, #111827); }
    .builtin-help { font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .builtin-invalid input, .builtin-invalid select, .builtin-invalid textarea { border-color: var(--builtin-color-danger, #b91c1c); }
    .builtin-field-error { min-height: 16px; font-size: 12px; color: var(--builtin-color-danger, #b91c1c); }
    .builtin-form-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
    .builtin-primary { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .builtin-primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    @media (max-width: 720px) {
      .builtin-grid { grid-template-columns: 1fr; }
      .builtin-toolbar, .builtin-pager { align-items: stretch; }
      .builtin-toolbar-group { width: 100%; }
      .builtin-toolbar-group > * { flex: 1 1 auto; }
    }
  `;
  root.appendChild(style);
}

export function csvCell(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}
