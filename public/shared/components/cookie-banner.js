/**
 * @fileoverview BuiltinCookieBanner — Fixed-bottom cookie consent banner.
 *
 * @element builtin-cookie-banner
 *
 * @attr {string} preset — `simple` | `detailed`.
 * @attr {string} policy-url — URL for the "Learn more" link.
 * @attr {boolean} open — Whether the banner is visible.
 *
 * @slot custom — Override default notice text.
 *
 * @event builtin-accept — Fired when the user accepts.
 * @event builtin-reject — Fired when the user rejects non-essential cookies.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

export class BuiltinCookieBanner extends BuiltinBaseElement {
  static properties = {
    preset: { type: String },
    policyUrl: { type: String, attribute: "policy-url" },
    open: { type: Boolean, reflect: true },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .banner {
      position: fixed;
      bottom: 0; left: 0; right: 0; z-index: 9999;
      background: var(--builtin-surface, #ffffff);
      border-top: 1px solid var(--builtin-border, #d1d5db);
      padding: 16px 24px;
      display: flex; align-items: center; justify-content: space-between; gap: 16px;
      flex-wrap: wrap;
      box-shadow: 0 -4px 12px rgba(0,0,0,0.05);
    }
    .text {
      flex: 1 1 auto;
      font-size: 14px;
      color: var(--builtin-color-text, #111827);
      line-height: 1.5;
    }
    .actions {
      display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    }
    .actions a {
      color: var(--builtin-primary, #2563eb); text-decoration: none; font-size: 14px;
    }
    .actions a:hover { text-decoration: underline; }
    .actions button.builtin-primary {
      background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff;
    }
    .actions button.builtin-primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .actions button.builtin-outline {
      background: transparent; border-color: var(--builtin-border, #d1d5db); color: var(--builtin-color-text, #111827);
    }
    .actions button.builtin-outline:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    @media (max-width: 720px) {
      .banner { flex-direction: column; align-items: stretch; padding: 16px; }
      .actions { flex-direction: column; width: 100%; }
      .actions > * { width: 100%; }
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    const stored = localStorage.getItem("builtin-cookie-consent");
    if (stored) {
      this.open = false;
    } else if (!this.hasAttribute("open")) {
      this.open = true;
    }
  }

  _accept() {
    localStorage.setItem("builtin-cookie-consent", "all");
    this.open = false;
    this.dispatchEvent(new CustomEvent("builtin-accept", { bubbles: true }));
  }

  _reject() {
    localStorage.setItem("builtin-cookie-consent", "essential");
    this.open = false;
    this.dispatchEvent(new CustomEvent("builtin-reject", { bubbles: true }));
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  render() {
    if (!this.open) return html``;
    const isDetailed = this.preset === "detailed";
    return html`
      <div class="banner" role="dialog" aria-live="polite">
        <div class="text">
          <slot name="custom">
            ${this._l("cookie.notice", "We use cookies to improve your experience. By continuing, you agree to our use of cookies.")}
          </slot>
        </div>
        <div class="actions">
          ${this.policyUrl
            ? html`<a href="${this.policyUrl}" target="_blank" rel="noopener">${this._l("cookie.learnMore", "Learn more")}</a>`
            : null}
          ${isDetailed
            ? html`<button class="builtin-outline" @click=${this._reject}>${this._l("cookie.reject", "Reject non-essential")}</button>`
            : null}
          <button class="builtin-primary" @click=${this._accept}>${this._l("cookie.accept", "Accept")}</button>
        </div>
      </div>
    `;
  }
}
