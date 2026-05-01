/**
 * @fileoverview BuiltinConfirm — Promise-based confirmation dialog.
 *
 * @attr {string} title — Dialog title.
 * @attr {string} message — Body message.
 * @attr {string} confirm-label — Confirm button text (default "Confirm").
 * @attr {string} cancel-label — Cancel button text (default "Cancel").
 * @attr {boolean} dangerous — Style confirm button red.
 * @attr {string} type — `info` | `warning` | `danger` | `success`.
 *
 * @method open() — Show dialog and return Promise<boolean>.
 * @method close(confirmed) — Hide dialog and resolve promise.
 *
 * @event builtin-confirm — User confirmed.
 * @event builtin-cancel — User cancelled.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

export class BuiltinConfirm extends BuiltinBaseElement {
  static properties = {
    title: { type: String },
    message: { type: String },
    confirmLabel: { type: String, attribute: "confirm-label" },
    cancelLabel: { type: String, attribute: "cancel-label" },
    dangerous: { type: Boolean },
    type: { type: String },
    labels: { type: Object },
    _open: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .overlay {
      position: fixed; inset: 0; z-index: 9999;
      background: rgba(0,0,0,0.45);
      display: flex; align-items: center; justify-content: center;
      padding: 20px;
      opacity: 0; pointer-events: none;
      transition: opacity 0.15s ease;
    }
    .overlay.open { opacity: 1; pointer-events: auto; }
    .box {
      background: var(--builtin-surface, #fff);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 20px 60px rgba(0,0,0,0.18);
      width: 100%; max-width: 420px;
      display: flex; flex-direction: column;
      transform: translateY(-12px) scale(0.98);
      transition: transform 0.18s ease, opacity 0.18s ease;
      opacity: 0;
    }
    .overlay.open .box { transform: translateY(0) scale(1); opacity: 1; }
    .header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 18px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .header h3 { margin: 0; font-size: 16px; font-weight: 650; color: var(--builtin-color-text, #111827); }
    .close {
      border: 0; background: transparent; padding: 4px; min-height: 0;
      font-size: 20px; line-height: 1; color: var(--builtin-color-muted, #6b7280);
      cursor: pointer; border-radius: var(--builtin-radius, 6px); display: inline-flex; align-items: center; justify-content: center;
    }
    .close:hover { background: var(--builtin-row-hover-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .body { padding: 18px; overflow: auto; color: var(--builtin-color-text, #111827); line-height: 1.5; }
    .footer {
      display: flex; align-items: center; justify-content: flex-end; gap: 8px;
      padding: 12px 18px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .danger {
      background: var(--builtin-color-danger, #b91c1c);
      border-color: var(--builtin-color-danger, #b91c1c);
      color: #fff;
    }
    .danger:hover { background: #991b1b; }
    .icon-wrap {
      display: inline-flex; align-items: center; gap: 10px; margin-bottom: 8px;
    }
    .icon-info { color: #2563eb; }
    .icon-success { color: #16a34a; }
    .icon-warning { color: #d97706; }
    .icon-danger { color: #b91c1c; }
    @media (max-width: 720px) {
      .overlay { padding: 10px; }
      .box { max-width: calc(100vw - 20px); }
    }
  `;

  constructor() {
    super();
    this._resolve = null;
  }

  open() {
    this._open = true;
    return new Promise((resolve) => {
      this._resolve = resolve;
    });
  }

  /**
   * Static convenience for one-shot confirm dialogs.
   *   const ok = await BuiltinConfirm.show({ title, message });
   *
   * Creates a `<builtin-confirm>` element, appends it to `document.body`,
   * awaits the user choice, and removes the element afterwards.
   *
   * @param {{title?: string, message?: string, confirmLabel?: string,
   *          cancelLabel?: string, dangerous?: boolean, type?: string}} [options]
   * @returns {Promise<boolean>} `true` if confirmed, `false` if cancelled.
   */
  static async show(options = {}) {
    const el = document.createElement("builtin-confirm");
    if (options.title) el.title = options.title;
    if (options.message) el.message = options.message;
    if (options.confirmLabel) el.confirmLabel = options.confirmLabel;
    if (options.cancelLabel) el.cancelLabel = options.cancelLabel;
    if (options.dangerous) el.dangerous = true;
    if (options.type) el.type = options.type;
    document.body.appendChild(el);
    try {
      return await el.open();
    } finally {
      if (el.parentNode) el.parentNode.removeChild(el);
    }
  }

  close(confirmed) {
    this._open = false;
    if (this._resolve) {
      this._resolve(confirmed);
      this._resolve = null;
    }
    this.dispatchEvent(new CustomEvent(confirmed ? "builtin-confirm" : "builtin-cancel", { bubbles: true }));
  }

  _iconSvg() {
    const t = this.type || "info";
    const icons = {
      info: html`<builtin-icon name="info-circle" size="22" variant="outlined"></builtin-icon>`,
      success: html`<builtin-icon name="check-circle" size="22" variant="outlined"></builtin-icon>`,
      warning: html`<builtin-icon name="warning" size="22" variant="outlined"></builtin-icon>`,
      danger: html`<builtin-icon name="close-circle" size="22" variant="outlined"></builtin-icon>`,
    };
    return icons[t] || icons.info;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  render() {
    const titleText = this.title || this._l("confirm.title", "Confirm");
    const confirmText = this.confirmLabel || this._l("confirm.confirm", "Confirm");
    const cancelText = this.cancelLabel || this._l("confirm.cancel", "Cancel");
    const typeClass = `icon-${this.type || "info"}`;
    return html`
      <div class="overlay ${classMap({ open: this._open })}" @click=${(e) => { if (e.target === e.currentTarget) this.close(false); }}>
        <div class="box" role="dialog" aria-modal="true">
          <div class="header">
            <h3>${titleText}</h3>
            <button class="close" @click=${() => this.close(false)} aria-label=${this._l("close", "Close")}>
              <builtin-icon name="close" size="20" variant="outlined"></builtin-icon>
            </button>
          </div>
          <div class="body">
            <div class="icon-wrap ${typeClass}">
              ${this._iconSvg()}
              <span>${this.message || ""}</span>
            </div>
          </div>
          <div class="footer">
            <button type="button" @click=${() => this.close(false)}>${cancelText}</button>
            <button type="button" class="${this.dangerous ? "danger" : "builtin-primary"}" @click=${() => this.close(true)}>${confirmText}</button>
          </div>
        </div>
      </div>
    `;
  }
}
