/**
 * @fileoverview BuiltinAdSidebar — Collapsible advertisement side panel.
 *
 * @attr {string} placement — 'left' | 'right' (default 'right').
 * @attr {boolean} open — Visibility.
 * @attr {string} width — Panel width (default '280px').
 * @attr {boolean} dismissible — Allow permanent dismiss (default true).
 * @attr {string} labels — JSON i18n overrides.
 *
 * @slots
 *   - image: Ad image/media.
 *   - content: Text content.
 *   - cta: Call-to-action button.
 *
 * @event builtin-dismiss — Panel dismissed.
 * @event builtin-click — CTA clicked.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

const DISMISS_KEY = "builtin_ad_sidebar_dismissed";

export class BuiltinAdSidebar extends BuiltinBaseElement {
  static properties = {
    placement: { type: String },
    open: { type: Boolean },
    width: { type: String },
    dismissible: { type: Boolean },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .mask {
      position: fixed; inset: 0; z-index: 9997;
      background: rgba(0,0,0,0.35);
      display: none;
    }
    .mask.open { display: block; }
    .panel {
      position: fixed; top: 0; bottom: 0;
      width: var(--ad-width, 280px);
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      z-index: 9998;
      display: flex; flex-direction: column;
      transition: transform .3s ease;
      box-shadow: 0 10px 40px rgba(0,0,0,0.12);
    }
    .panel.left { left: 0; border-left: none; transform: translateX(-100%); }
    .panel.right { right: 0; border-right: none; transform: translateX(100%); }
    .panel.left.open, .panel.right.open { transform: translateX(0); }
    .header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 12px 14px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .header span { font-weight: 650; font-size: 14px; color: var(--builtin-color-muted, #6b7280); }
    .close {
      border: 0; background: transparent; padding: 4px; min-height: 0;
      color: var(--builtin-color-muted, #6b7280); cursor: pointer; border-radius: var(--builtin-radius, 6px);
      display: inline-flex; align-items: center; justify-content: center;
    }
    .close:hover { background: var(--builtin-row-hover-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .body { flex: 1; overflow-y: auto; padding: 14px; }
    .image-slot { border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; margin-bottom: 12px; }
    .image-slot ::slotted(img) { width: 100%; display: block; }
    .cta { padding: 14px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); }
    @media (max-width: 720px) {
      .panel { width: calc(100% - 48px) !important; }
    }
  `;

  constructor() {
    super();
    this.placement = "right";
    this.open = false;
    this.width = "280px";
    this.dismissible = true;
    this.labels = {};
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _shouldShow() {
    if (!this.dismissible) return true;
    try {
      const dismissed = localStorage.getItem(DISMISS_KEY);
      if (!dismissed) return true;
      const ts = Number(dismissed);
      if (Date.now() - ts < 24 * 60 * 60 * 1000) return false;
    } catch (_e) {}
    return true;
  }

  openPanel() {
    if (!this._shouldShow()) return;
    this.open = true;
  }

  close() {
    this.open = false;
  }

  _dismiss() {
    this.open = false;
    if (this.dismissible) {
      try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (_e) {}
    }
    this.dispatchEvent(new CustomEvent("builtin-dismiss", { bubbles: true, composed: true }));
  }

  _onCta() {
    this.dispatchEvent(new CustomEvent("builtin-click", { bubbles: true, composed: true }));
  }

  render() {
    const placement = this.placement === "left" ? "left" : "right";
    const w = this.width || "280px";
    return html`
      <div class="${classMap({ mask: true, open: this.open })}" @click="${() => this.close()}"></div>
      <div class="${classMap({ panel: true, [placement]: true, open: this.open })}" style="--ad-width:${w}">
        <div class="header">
          <span>${this._l("ad.advertisement", "Advertisement")}</span>
          <button class="close" @click="${() => this._dismiss()}" aria-label="${this._l("ad.close", "Close")}">
            <builtin-icon name="close" size="18" variant="outlined"></builtin-icon>
          </button>
        </div>
        <div class="body">
          <div class="image-slot"><slot name="image"></slot></div>
          <slot name="content"></slot>
        </div>
        <div class="cta" @click="${this._onCta}">
          <slot name="cta"></slot>
        </div>
      </div>
    `;
  }
}
