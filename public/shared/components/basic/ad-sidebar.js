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

import { BuiltinBaseElement, html, css, classMap, repeat } from "../lit-base.js";

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return [];
    try { return JSON.parse(value); } catch { return []; }
  },
  toAttribute(value) { return JSON.stringify(value); },
};

const DISMISS_KEY = "builtin_ad_sidebar_dismissed";

export class BuiltinAdSidebar extends BuiltinBaseElement {
  static properties = {
    placement: { type: String },
    open: { type: Boolean },
    width: { type: String },
    dismissible: {
      type: Boolean,
      converter: {
        fromAttribute(value) { return value !== null && value !== "false"; },
        toAttribute(value) { return value ? "" : "false"; },
      },
    },
    title: { type: String },
    ads: { type: Array, converter: jsonConverter },
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
    .trigger {
      display: inline-flex; align-items: center; gap: 8px;
      min-height: 36px; padding: 0 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer; font: inherit; font-weight: 650;
    }
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
    .ads { display: grid; gap: 10px; }
    .ad-card {
      display: grid; gap: 6px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-header-bg, #f9fafb);
      padding: 10px;
      color: var(--builtin-color-text, #111827);
      text-decoration: none;
    }
    .ad-card img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 4px; background: var(--builtin-border-soft, #e5e7eb); }
    .ad-title { font-weight: 700; font-size: 14px; }
    .ad-desc { color: var(--builtin-color-muted, #6b7280); font-size: 13px; line-height: 1.45; }
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
    this.title = "";
    this.ads = [];
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
    const ads = Array.isArray(this.ads) ? this.ads : [];
    return html`
      ${this.open ? "" : html`
        <button class="trigger" @click=${() => this.openPanel()}>
          <builtin-icon name="notification" size="18" variant="outlined"></builtin-icon>
          <span>${this.title || this._l("ad.advertisement", "Advertisement")}</span>
        </button>
      `}
      <div class="${classMap({ mask: true, open: this.open })}" @click="${() => this.close()}"></div>
      <div class="${classMap({ panel: true, [placement]: true, open: this.open })}" style="--ad-width:${w}">
        <div class="header">
          <span>${this.title || this._l("ad.advertisement", "Advertisement")}</span>
          <button class="close" @click="${() => this._dismiss()}" aria-label="${this._l("ad.close", "Close")}">
            <builtin-icon name="close" size="18" variant="outlined"></builtin-icon>
          </button>
        </div>
        <div class="body">
          <div class="image-slot"><slot name="image"></slot></div>
          <slot name="content"></slot>
          ${ads.length ? html`
            <div class="ads">
              ${repeat(ads, (ad, index) => ad.id || ad.href || ad.title || index, (ad) => html`
                <a class="ad-card" href=${ad.href || "#"} @click=${this._onCta}>
                  ${ad.image ? html`<img src=${ad.image} alt=${ad.title || ""} loading="lazy">` : ""}
                  <span class="ad-title">${ad.title || "Advertisement"}</span>
                  ${ad.description ? html`<span class="ad-desc">${ad.description}</span>` : ""}
                </a>
              `)}
            </div>
          ` : ""}
        </div>
        <div class="cta" @click="${this._onCta}">
          <slot name="cta"></slot>
        </div>
      </div>
    `;
  }
}
