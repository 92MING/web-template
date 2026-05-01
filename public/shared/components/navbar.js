/**
 * @fileoverview BuiltinNavbar ！ responsive top navigation bar (Lit).
 *
 * @attr {string} brand ！ Text shown when the brand slot is not used.
 * @attr {string} items ！ JSON array of {label, href, active} nav links.
 * @attr {boolean} sticky ！ Stick to the top of the viewport.
 * @attr {string} mode ！ "default" | "transparent" | "centered"
 * @attr {string} labels ！ JSON map for i18n overrides.
 *
 * @slots
 * - brand ！ Left area (logo / text).
 * - actions ！ Right area (buttons, icons, etc.).
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinNavbar extends BuiltinBaseElement {
  static properties = {
    brand: { type: String },
    items: { type: Array },
    sticky: { type: Boolean },
    mode: { type: String },
    _mobileMenuOpen: { type: Boolean, state: true },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .navbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 16px;
      min-height: 56px;
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border, #d1d5db);
      position: relative;
    }
    .navbar.sticky {
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .navbar.transparent {
      background: transparent;
      border-bottom-color: transparent;
    }
    .navbar.centered {
      justify-content: center;
    }
    .navbar.centered .nav-links {
      position: absolute;
      left: 50%;
      transform: translateX(-50%);
    }
    .brand-area {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 700;
      color: var(--builtin-primary, #2563eb);
      font-size: 18px;
      white-space: nowrap;
    }
    .nav-links {
      display: flex;
      align-items: center;
      gap: 4px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .nav-links a {
      display: block;
      padding: 8px 12px;
      border-radius: var(--builtin-radius, 6px);
      text-decoration: none;
      color: var(--builtin-color-text, #111827);
      font-weight: 500;
      white-space: nowrap;
    }
    .nav-links a:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .nav-links a.active {
      color: var(--builtin-primary, #2563eb);
      background: rgba(37, 99, 235, 0.08);
    }
    .actions-area {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-left: auto;
    }
    .hamburger {
      display: none;
      background: none;
      border: none;
      padding: 8px;
      cursor: pointer;
      color: var(--builtin-color-text, #111827);
      border-radius: var(--builtin-radius, 6px);
    }
    .hamburger:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .hamburger builtin-icon {
      display: block;
    }
    .mobile-menu {
      display: none;
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      background: var(--builtin-surface, #ffffff);
      border-bottom: 1px solid var(--builtin-border, #d1d5db);
      padding: 8px;
      flex-direction: column;
      gap: 4px;
      z-index: 99;
      box-shadow: 0 10px 30px rgba(0,0,0,0.08);
    }
    .mobile-menu.open { display: flex; }
    .mobile-menu a {
      padding: 12px 16px;
      border-radius: var(--builtin-radius, 6px);
      text-decoration: none;
      color: var(--builtin-color-text, #111827);
      font-weight: 500;
      display: block;
    }
    .mobile-menu a:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .mobile-menu a.active {
      color: var(--builtin-primary, #2563eb);
      background: rgba(37, 99, 235, 0.08);
    }
    .mobile-actions { padding: 8px 0; }
    @media (max-width: 720px) {
      .nav-links { display: none; }
      .actions-area { display: none; }
      .hamburger { display: inline-flex; align-items: center; justify-content: center; }
      .navbar { padding: 0 12px; }
      .navbar.centered .nav-links { position: static; transform: none; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.mode = "default";
    this._mobileMenuOpen = false;
    this.labels = {};
  }

  _l(key, fallback = "") {
    const override = this.labels?.[key];
    if (override != null) return override;
    if (fallback != null && fallback !== "") return fallback;
    return super._t(key);
  }

  render() {
    const mode = this.mode || "default";
    const navbarClass = {
      navbar: true,
      sticky: this.sticky,
      transparent: mode === "transparent",
      centered: mode === "centered",
    };

    return html`
      <nav class="${classMap(navbarClass)}" role="navigation">
        <div class="brand-area">
          <slot name="brand">${this.brand}</slot>
        </div>
        <ul class="nav-links">
          ${(this.items || []).map((item) => html`
            <li>
              <a href="${item.href || "#"}" class="${classMap({ active: item.active })}">
                ${item.label}
              </a>
            </li>
          `)}
        </ul>
        <div class="actions-area">
          <slot name="actions"></slot>
        </div>
        <button class="hamburger"
                aria-label="${this._l("navbar.toggleMenu", "Toggle menu")}"
                @click="${() => { this._mobileMenuOpen = !this._mobileMenuOpen; }}">
          <builtin-icon name="menu" size="20" variant="outlined"></builtin-icon>
        </button>
        <div class="${classMap({ "mobile-menu": true, open: this._mobileMenuOpen })}">
          ${(this.items || []).map((item) => html`
            <a href="${item.href || "#"}" class="${classMap({ active: item.active })}">
              ${item.label}
            </a>
          `)}
          <div class="mobile-actions">
            <slot name="actions"></slot>
          </div>
        </div>
      </nav>
    `;
  }
}
