/**
 * @fileoverview Lit-based base class and shared utilities for all pt-* components.
 *
 * Provides:
 * - BuiltinBaseElement: LitElement subclass with unified theming, i18n, mobile detection
 * - Icon helper to load SVGs from /icons/
 * - Re-exports of lit core + common directives
 */

// Lit core (bundled)
export {
  LitElement,
  html,
  css,
  svg,
  render,
  unsafeCSS,
  nothing,
  noChange,
} from "../../vendor/lit/lit-all.mjs";

import { LitElement, html, css, nothing } from "../../vendor/lit/lit-all.mjs";
import { setSharedTheme, getSharedTheme } from "./core.js";

function _to_kebab_case(name) {
  return String(name).replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
}

export function repeat(items, key_or_template_fn, template_fn) {
  const list = Array.from(items || []);
  if (typeof template_fn === "function") {
    return list.map((item, index) => template_fn(item, index));
  }
  if (typeof key_or_template_fn === "function") {
    return list.map((item, index) => key_or_template_fn(item, index));
  }
  return list;
}

export function classMap(classes) {
  if (!classes || typeof classes !== "object") {
    return "";
  }
  return Object.entries(classes)
    .filter(([, enabled]) => !!enabled)
    .map(([name]) => name)
    .join(" ");
}

export function styleMap(styles) {
  if (!styles || typeof styles !== "object") {
    return "";
  }
  return Object.entries(styles)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([name, value]) => `${_to_kebab_case(name)}:${String(value)}`)
    .join(";");
}

export function unsafeHTML(value) {
  if (value === null || value === undefined || value === "") {
    return nothing;
  }
  const template = document.createElement("template");
  template.innerHTML = String(value);
  return template.content.cloneNode(true);
}

export function ifDefined(value) {
  return value === null || value === undefined ? nothing : value;
}

export function live(value) {
  return value;
}

export function createRef() {
  return { value: null };
}

export function ref(target) {
  return target;
}

// --- Theme helpers (re-exported from core for convenience) ---
export { setSharedTheme, getSharedTheme };

// --- i18n helpers ---
function currentLang() {
  return document.documentElement.lang || navigator.language || "en";
}

let _i18nCatalog = {};
let _i18nLang = currentLang();

export function setI18nCatalog(lang, catalog) {
  _i18nLang = lang;
  _i18nCatalog = catalog || {};
  document.dispatchEvent(new CustomEvent("builtin-lang-change", { detail: { lang, catalog } }));
}

// Humanize a missing i18n key as a last-resort fallback so the UI never shows
// raw dotted identifiers like "pagination.next". We take the last dot-segment
// and split camelCase into spaced Title Case, e.g. "pagination.loadMore" -> "Load More".
function _humanize_i18n_key(key) {
  const s = String(key);
  const tail = s.includes(".") ? s.slice(s.lastIndexOf(".") + 1) : s;
  if (!tail) return s;
  const spaced = tail
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function t(key, values) {
  let text;
  if (_i18nCatalog[key] !== undefined) {
    text = _i18nCatalog[key];
  } else {
    text = _humanize_i18n_key(key);
  }
  if (values && typeof values === "object") {
    text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => (
      Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
    ));
  }
  return text;
}

// --- Icon loader ---
const ICON_CACHE = new Map();

function normalizeSvg(svg_text, color) {
  if (!svg_text) return "";
  let normalized = svg_text;
  normalized = normalized.replace(/<\?xml[^?]*\?>/, "");
  normalized = normalized.replace(/<!--[\s\S]*?-->/g, "");
  normalized = normalized.replace(/class="[^"]*"/g, "");
  normalized = normalized.replace(/\swidth="[^"]*"/g, "");
  normalized = normalized.replace(/\sheight="[^"]*"/g, "");
  normalized = normalized.replace(/fill="none"/g, 'fill="__NONE__"');
  normalized = normalized.replace(/fill="#[^"]*"/g, "");
  normalized = normalized.replace(/fill="rgb\([^)]*\)"/g, "");
  normalized = normalized.replace(/fill="rgba\([^)]*\)"/g, "");
  normalized = normalized.replace(/fill="__NONE__"/g, 'fill="none"');
  const fill_attr = color ? `fill="${color}"` : 'fill="currentColor"';
  if (normalized.includes("<svg")) {
    normalized = normalized.replace(/<svg\s/, `<svg ${fill_attr} `);
    if (!normalized.includes(fill_attr)) {
      normalized = normalized.replace(/<svg/, `<svg ${fill_attr}`);
    }
  }
  return normalized.trim();
}

export async function loadIcon(name, variant = "outlined") {
  const key = `${variant}/${name}`;
  if (ICON_CACHE.has(key)) return ICON_CACHE.get(key);
  try {
    const response = await fetch(`/icons/${variant}/${name}.svg`);
    if (!response.ok) return "";
    const svg = await response.text();
    ICON_CACHE.set(key, svg);
    return svg;
  } catch (_err) {
    return "";
  }
}

export function iconHtml(name, variant = "outlined", size = 20, color = "") {
  return html`<builtin-icon name="${name}" variant="${variant}" size="${size}" color="${color || ""}"></builtin-icon>`;
}

// --- Base class ---
export class BuiltinBaseElement extends LitElement {
  static get properties() {
    return {
      _ptTheme: { type: String, state: true },
      _ptLang: { type: String, state: true },
      _ptMobile: { type: Boolean, state: true },
      labels: { type: Object },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
        color: var(--builtin-color-text, #111827);
        font-family: var(--builtin-font-family, Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
        font-size: var(--builtin-font-size, 14px);
      }
      * { box-sizing: border-box; }
      button, input, select, textarea { font: inherit; }
    `;
  }

  constructor() {
    super();
    this._ptTheme = getSharedTheme?.() || "light";
    this._ptLang = _i18nLang;
    this._ptMobile = window.innerWidth <= 720;
    this._onThemeChange = (e) => { this._ptTheme = e.detail.theme; };
    this._onLangChange = (e) => { this._ptLang = e.detail.lang; this.requestUpdate(); };
    this._onResize = () => { this._ptMobile = window.innerWidth <= 720; };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("builtin-theme-change", this._onThemeChange);
    document.addEventListener("builtin-lang-change", this._onLangChange);
    window.addEventListener("resize", this._onResize);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("builtin-theme-change", this._onThemeChange);
    document.removeEventListener("builtin-lang-change", this._onLangChange);
    window.removeEventListener("resize", this._onResize);
  }

  /**
   * Shorthand for i18n translation.
   * Usage: ${this._t('login.title')}
   */
  _t(key, values) {
    return t(key, values);
  }

  /**
   * Localized label with fallback chain: labels override > fallback string > i18n catalog.
   * Usage: ${this._l('search.placeholder', 'Search...')}
   */
  _l(key, fallback) {
    const override = this.labels?.[key];
    if (override != null) return override;
    if (fallback != null && fallback !== "") return fallback;
    return this._t(key);
  }

  /**
   * Return a <builtin-icon> element for synchronous use inside render().
   * Usage: ${this._icon('user', 'outlined', 20)}
   */
  _icon(name, variant = "outlined", size = 20, color = "") {
    return html`<builtin-icon name="${name}" variant="${variant}" size="${size}" color="${color || ""}"></builtin-icon>`;
  }

  /**
   * Async raw SVG loader (rarely needed now; prefer _icon).
   */
  async _loadIconRaw(name, variant = "outlined") {
    const raw = await loadIcon(name, variant);
    return unsafeHTML(normalizeSvg(raw));
  }

  /**
   * Utility to animate an element using Web Animations API.
   * Returns the Animation instance for control.
   */
  _animate(el, keyframes, options = {}) {
    if (!el || !el.animate) return null;
    return el.animate(keyframes, { duration: 300, easing: "ease", fill: "both", ...options });
  }

  /**
   * Fade in an element (typically called after render).
   */
  _fadeIn(el, options = {}) {
    return this._animate(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 200, ...options });
  }

  /**
   * Fade out an element, returns Promise that resolves when done.
   */
  async _fadeOut(el, options = {}) {
    const anim = this._animate(el, [{ opacity: 1 }, { opacity: 0 }], { duration: 200, ...options });
    if (!anim) return;
    await anim.finished;
  }
}
