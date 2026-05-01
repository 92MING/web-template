/**
 * @fileoverview BuiltinSidebar — responsive sidebar with nested sub-menu support (Lit).
 *
 * @attr {string} items — JSON array of groups/sections.
 * @attr {string} mode — "fixed" | "overlay" | "mini"
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @slots
 * - header — Top of the sidebar.
 * - footer — Bottom of the sidebar.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinSidebar extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
    mode: { type: String },
    _expanded: { type: Object, state: true },
    _mobileOpen: { type: Boolean, state: true },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .sidebar-wrap {
      position: fixed;
      top: 0;
      left: 0;
      bottom: 0;
      width: 240px;
      background: var(--builtin-surface, #ffffff);
      border-right: 1px solid var(--builtin-border, #d1d5db);
      display: flex;
      flex-direction: column;
      z-index: 90;
      transition: width 0.2s ease, transform 0.25s ease;
    }
    .sidebar-wrap.mini { width: 64px; }
    .sidebar-wrap.overlay { position: fixed; z-index: 90; }
    .sidebar-header {
      padding: 14px 16px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      min-height: 56px;
      display: flex;
      align-items: center;
    }
    .sidebar-body {
      flex: 1 1 auto;
      overflow-y: auto;
      padding: 8px;
    }
    .sidebar-footer {
      padding: 12px 16px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .group-label {
      font-size: 11px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--builtin-color-muted, #6b7280);
      padding: 12px 8px 6px;
    }
    .sidebar-wrap.mini .group-label { display: none; }
    .nav-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 10px;
      border-radius: var(--builtin-radius, 6px);
      text-decoration: none;
      color: var(--builtin-color-text, #111827);
      font-weight: 500;
      cursor: pointer;
      min-height: 36px;
    }
    .nav-item:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .nav-item.active {
      color: var(--builtin-primary, #2563eb);
      background: rgba(37, 99, 235, 0.08);
    }
    .sub-toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 10px;
      border-radius: var(--builtin-radius, 6px);
      color: var(--builtin-color-text, #111827);
      font-weight: 500;
      cursor: pointer;
      min-height: 36px;
      user-select: none;
    }
    .sub-toggle:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .sub-toggle-icon {
      transition: transform 0.2s ease;
      opacity: 0.7;
    }
    .sub-toggle.expanded .sub-toggle-icon { transform: rotate(90deg); }
    .sub-menu {
      display: grid;
      grid-template-rows: 0fr;
      flex-direction: column;
      gap: 2px;
      padding-left: 12px;
      margin-top: 2px;
      transition: grid-template-rows 0.25s ease;
    }
    .sub-menu.open { grid-template-rows: 1fr; }
    .sub-menu-inner { overflow: hidden; display: flex; flex-direction: column; gap: 2px; }
    .sub-menu .nav-item {
      font-weight: 400;
      font-size: 13px;
      min-height: 32px;
    }
    .mobile-trigger {
      display: none;
      position: fixed;
      top: 12px;
      left: 12px;
      z-index: 95;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      padding: 8px;
      cursor: pointer;
      color: var(--builtin-color-text, #111827);
    }
    .mobile-trigger builtin-icon {
      display: block;
    }
    .mobile-close {
      display: none;
      position: absolute;
      top: 10px;
      right: 10px;
      background: none;
      border: none;
      padding: 6px;
      cursor: pointer;
      color: var(--builtin-color-muted, #6b7280);
      border-radius: var(--builtin-radius, 6px);
    }
    .mobile-close:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .mobile-close builtin-icon {
      display: block;
    }
    .mobile-mask {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.45);
      z-index: 89;
    }
    @media (max-width: 720px) {
      .sidebar-wrap {
        width: 260px;
        transform: translateX(-100%);
      }
      .sidebar-wrap.mobile-open { transform: translateX(0); }
      .mobile-trigger { display: block; }
      .mobile-close { display: block; }
      .mobile-mask.open { display: block; }
      .group-label { display: block; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.mode = "fixed";
    this._expanded = new Set();
    this._mobileOpen = false;
    this.labels = {};
  }

  _t(key, values) {
    if (this.labels && typeof this.labels === "object" && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => (
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        ));
      }
      return text;
    }
    return super._t(key, values);
  }

  _toggleSub(key) {
    const next = new Set(this._expanded);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    this._expanded = next;
  }

  render() {
    const mode = this.mode || "fixed";
    const isMini = mode === "mini";
    const sidebarClass = {
      "sidebar-wrap": true,
      mini: isMini,
      overlay: mode === "overlay",
      "mobile-open": this._mobileOpen,
    };

    return html`
      ${this._ptMobile ? html`
        <button class="mobile-trigger" aria-label="${this._t("sidebar.open")}" @click="${() => { this._mobileOpen = true; }}">
          <builtin-icon name="menu" size="20" variant="outlined"></builtin-icon>
        </button>
        <div class="${classMap({ "mobile-mask": true, open: this._mobileOpen })}" @click="${() => { this._mobileOpen = false; }}"></div>
      ` : ""}
      <aside class="${classMap(sidebarClass)}" role="navigation">
        ${this._ptMobile ? html`
          <button class="mobile-close" aria-label="${this._t("sidebar.close")}" @click="${() => { this._mobileOpen = false; }}">
            <builtin-icon name="close" size="20" variant="outlined"></builtin-icon>
          </button>
        ` : ""}
        <div class="sidebar-header">
          <slot name="header"></slot>
        </div>
        <div class="sidebar-body">
          ${(this.items || []).map((group, gi) => html`
            ${group.label ? html`<div class="group-label">${group.label}</div>` : ""}
            ${(group.items || []).map((item) => {
              if (item.items && item.items.length) {
                const key = `${gi}-${item.label}`;
                const expanded = this._expanded.has(key);
                return html`
                  <div>
                    <div class="sub-toggle ${expanded ? "expanded" : ""}" @click="${() => this._toggleSub(key)}">
                      <span>${item.label}</span>
                      <builtin-icon class="sub-toggle-icon" name="right" size="16" variant="outlined"></builtin-icon>
                    </div>
                    <div class="sub-menu ${expanded ? "open" : ""}">
                      <div class="sub-menu-inner">
                        ${item.items.map((sub) => html`
                          <a href="${sub.href || "#"}" class="${classMap({ "nav-item": true, active: sub.active })}">${sub.label}</a>
                        `)}
                      </div>
                    </div>
                  </div>
                `;
              }
              return html`
                <a href="${item.href || "#"}" class="${classMap({ "nav-item": true, active: item.active })}">${item.label}</a>
              `;
            })}
          `)}
        </div>
        <div class="sidebar-footer">
          <slot name="footer"></slot>
        </div>
      </aside>
    `;
  }
}
