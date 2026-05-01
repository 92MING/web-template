/**
 * @fileoverview BuiltinToast — Auto-dismissing notification.
 *
 * @attr {string} message — Text to display.
 * @attr {string} type — `info` | `success` | `warning` | `error`.
 * @attr {number} duration — Milliseconds before auto-dismiss (default 3000).
 * @attr {string} position — `top-right` | `top-left` | `bottom-right` | `bottom-left` | `top-center` | `bottom-center`.
 * @attr {boolean} auto-show — Open immediately on connect.
 *
 * @method show() — Display the toast.
 * @method dismiss() — Hide the toast.
 *
 * @event builtin-show — Toast shown.
 * @event builtin-dismiss — Toast dismissed.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

export class BuiltinToast extends BuiltinBaseElement {
  static properties = {
    message: { type: String },
    type: { type: String },
    duration: { type: Number },
    position: { type: String },
    autoShow: { type: Boolean, reflect: true, attribute: "auto-show" },
    solid: { type: Boolean },
    labels: { type: Object },
    _open: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .toast {
      position: fixed; z-index: 10000;
      background: var(--builtin-surface, #fff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 10px 30px rgba(0,0,0,0.1);
      padding: 12px 16px;
      min-width: 240px; max-width: 420px;
      display: flex; align-items: flex-start; gap: 10px;
      opacity: 0; transform: translateY(-8px);
      transition: opacity 0.2s ease, transform 0.2s ease;
      pointer-events: none;
    }
    .toast.open {
      opacity: 1; transform: translateY(0); pointer-events: auto;
    }
    .toast-message { flex: 1; font-size: 14px; line-height: 1.5; color: var(--builtin-color-text, #111827); }
    .toast-close {
      border: 0; background: transparent; padding: 2px; min-height: 0;
      font-size: 16px; color: var(--builtin-color-muted, #6b7280); cursor: pointer;
      display: inline-flex; align-items: center; justify-content: center;
    }
    .toast-close:hover { color: var(--builtin-color-text, #111827); }
    .border-info { border-left: 4px solid #2563eb; }
    .border-success { border-left: 4px solid #16a34a; }
    .border-warning { border-left: 4px solid #d97706; }
    .border-error { border-left: 4px solid #b91c1c; }
    .solid-info { background: #2563eb; color: #fff; border-color: #2563eb; }
    .solid-info .toast-message { color: #fff; }
    .solid-success { background: #16a34a; color: #fff; border-color: #16a34a; }
    .solid-success .toast-message { color: #fff; }
    .solid-warning { background: #d97706; color: #fff; border-color: #d97706; }
    .solid-warning .toast-message { color: #fff; }
    .solid-error { background: #b91c1c; color: #fff; border-color: #b91c1c; }
    .solid-error .toast-message { color: #fff; }
    .solid .toast-close { color: rgba(255,255,255,0.8); }
    .solid .toast-close:hover { color: #fff; }
    @media (max-width: 720px) {
      .toast {
        min-width: auto;
        width: calc(100vw - 32px);
        max-width: none;
        left: 16px !important; right: 16px !important;
      }
      .toast.open { transform: translateY(0); }
    }
  `;

  constructor() {
    super();
    this.type = "info";
    this.duration = 3000;
    this.position = "top-right";
    this.solid = false;
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.autoShow) this.show();
  }

  _positionStyles() {
    const map = {
      "top-right": { top: "16px", right: "16px" },
      "top-left": { top: "16px", left: "16px" },
      "bottom-right": { bottom: "16px", right: "16px" },
      "bottom-left": { bottom: "16px", left: "16px" },
      "top-center": { top: "16px", left: "50%", transform: "translateX(-50%)" },
      "bottom-center": { bottom: "16px", left: "50%", transform: "translateX(-50%)" },
    };
    return map[this.position] || map["top-right"];
  }

  show() {
    this._open = true;
    this.dispatchEvent(new CustomEvent("builtin-show", { bubbles: true }));
    const dur = Math.max(Number(this.duration) || 3000, 500);
    if (this._timer) clearTimeout(this._timer);
    this._timer = setTimeout(() => this.dismiss(), dur);
  }

  /**
   * Static convenience for one-shot toasts.
   *   BuiltinToast.show("Saved", { type: "success", duration: 2000 });
   *
   * Creates a `<builtin-toast>` element, appends it to `document.body`,
   * triggers `show()`, and auto-removes it after the toast dismisses.
   *
   * @param {string} message
   * @param {{type?: string, duration?: number, position?: string, solid?: boolean}} [options]
   * @returns {BuiltinToast}
   */
  static show(message, options = {}) {
    const el = document.createElement("builtin-toast");
    el.message = message;
    if (options.type) el.type = options.type;
    if (options.duration != null) el.duration = Number(options.duration);
    if (options.position) el.position = options.position;
    if (options.solid) el.solid = true;
    document.body.appendChild(el);
    el.addEventListener("builtin-dismiss", () => {
      setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, 250);
    }, { once: true });
    el.show();
    return el;
  }

  dismiss() {
    if (this._timer) clearTimeout(this._timer);
    this._open = false;
    this.dispatchEvent(new CustomEvent("builtin-dismiss", { bubbles: true }));
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  render() {
    const type = this.type || "info";
    const borderClass = this.solid ? `solid-${type} solid` : `border-${type}`;
    return html`
      <div class="toast ${borderClass} ${classMap({ open: this._open })}" style=${styleMap(this._positionStyles())}>
        <span class="toast-message">${this.message || ""}</span>
        <button class="toast-close" @click=${this.dismiss} aria-label=${this._l("dismiss", "Dismiss")}>
          <builtin-icon name="close" size="16" variant="outlined"></builtin-icon>
        </button>
      </div>
    `;
  }
}
