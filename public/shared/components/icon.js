/**
 * @fileoverview BuiltinIcon — Unified SVG icon loader from /icons/.
 *
 * Loads SVGs from `/icons/{variant}/{name}.svg`, caches them,
 * and normalizes colors so they inherit from CSS `color`.
 *
 * @attr {string} name — Icon file name without .svg (e.g. "user", "home")
 * @attr {string} variant — `outlined` | `filled` | `twotone` (default `outlined`)
 * @attr {number} size — Render size in px (default 20)
 * @attr {string} color — CSS color value. Default inherits from parent text color.
 * @attr {number} rotate — Rotation in degrees
 * @attr {boolean} spin — Infinite spin animation
 *
 * @usage
 *   <builtin-icon name="user" variant="outlined" size="24"></builtin-icon>
 *   <builtin-icon name="home" color="var(--builtin-primary)"></builtin-icon>
 */

import { BuiltinBaseElement, html, css, unsafeHTML } from "./lit-base.js";

const ICON_SVG_CACHE = new Map();

export function normalizeSvg(svgText, color) {
  if (!svgText) return "";
  let s = svgText;
  // Remove XML declaration
  s = s.replace(/<\?xml[^?]*\?>/, "");
  // Remove comments
  s = s.replace(/<!--[\s\S]*?-->/g, "");
  // Remove hard-coded class
  s = s.replace(/class="[^"]*"/g, "");
  // Remove hard-coded width/height so we control via CSS
  s = s.replace(/\swidth="[^"]*"/g, "");
  s = s.replace(/\sheight="[^"]*"/g, "");
  // Replace fill="none" placeholder so we don't overwrite it
  s = s.replace(/fill="none"/g, 'fill="__NONE__"');
  // Remove remaining hard-coded fills
  s = s.replace(/fill="#[^"]*"/g, "");
  s = s.replace(/fill="rgb\([^)]*\)"/g, "");
  s = s.replace(/fill="rgba\([^)]*\)"/g, "");
  // Restore none
  s = s.replace(/fill="__NONE__"/g, 'fill="none"');
  // Inject color on root svg
  const fillAttr = color ? `fill="${color}"` : 'fill="currentColor"';
  if (s.includes("<svg")) {
    s = s.replace(/<svg\s/, `<svg ${fillAttr} `);
    if (!s.includes(`${fillAttr}`)) {
      s = s.replace(/<svg/, `<svg ${fillAttr}`);
    }
  }
  return s.trim();
}

export async function fetchIcon(name, variant = "outlined") {
  const key = `${variant}/${name}`;
  if (ICON_SVG_CACHE.has(key)) return ICON_SVG_CACHE.get(key);
  try {
    const res = await fetch(`/icons/${variant}/${name}.svg`);
    if (!res.ok) return "";
    const text = await res.text();
    ICON_SVG_CACHE.set(key, text);
    return text;
  } catch (_e) {
    return "";
  }
}

export class BuiltinIcon extends BuiltinBaseElement {
  static get properties() {
    return {
      name: { type: String },
      variant: { type: String },
      size: { type: Number },
      color: { type: String },
      rotate: { type: Number },
      spin: { type: Boolean },
      _svg: { type: String, state: true },
    };
  }

  static get styles() {
    return css`
      :host {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        line-height: 1;
        color: var(--builtin-color-text, #111827);
      }
      :host([size="16"]) { width: 16px; height: 16px; }
      :host([size="20"]) { width: 20px; height: 20px; }
      :host([size="24"]) { width: 24px; height: 24px; }
      :host([size="32"]) { width: 32px; height: 32px; }
      :host([size="48"]) { width: 48px; height: 48px; }
      :host([size="64"]) { width: 64px; height: 64px; }
      svg {
        width: 100%;
        height: 100%;
        display: block;
        flex-shrink: 0;
      }
      .spin { animation: builtin-icon-spin 1s linear infinite; }
      @keyframes builtin-icon-spin { 100% { transform: rotate(360deg); } }
    `;
  }

  constructor() {
    super();
    this.variant = "outlined";
    this.size = 20;
    this.rotate = 0;
    this.spin = false;
    this._svg = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  willUpdate(changed) {
    if (changed.has("name") || changed.has("variant")) {
      this._load();
    }
  }

  async _load() {
    if (!this.name) { this._svg = ""; return; }
    const raw = await fetchIcon(this.name, this.variant);
    this._svg = normalizeSvg(raw, this.color);
  }

  render() {
    const styleMap = {};
    if (this.size && ![16, 20, 24, 32, 48, 64].includes(this.size)) {
      styleMap.width = `${this.size}px`;
      styleMap.height = `${this.size}px`;
    }
    if (this.rotate) {
      styleMap.transform = `rotate(${this.rotate}deg)`;
    }
    const cls = this.spin ? "spin" : "";
    return html`
      <div class="${cls}" style="${Object.entries(styleMap).map(([k, v]) => `${k}:${v}`).join(";")}">
        ${unsafeHTML(this._svg || this._fallback())}
      </div>
    `;
  }

  _fallback() {
    // Minimal placeholder so layout doesn't collapse
    return `<svg viewBox="0 0 24 24" style="opacity:0.2"><rect width="24" height="24"/></svg>`;
  }
}
