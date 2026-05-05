import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinPaymentMethodCard — Visual payment method card.
 *
 * Attributes:
 * - `type`: `card` | `paypal` | `alipay` | `wechat`
 * - `last4` (string)
 * - `expiry` (string)
 * - `brand` (string)
 * - `holder` (string)
 * - `labels` (JSON object for local i18n overrides)
 *
 * Events:
 * - `builtin-select` — Fired when the card is clicked to select.
 * - `builtin-delete` — Fired when the delete button is clicked.
 */
export class BuiltinPaymentMethodCard extends BuiltinBaseElement {
  static get properties() {
    return {
      type: { type: String },
      last4: { type: String },
      expiry: { type: String },
      brand: { type: String },
      holder: { type: String },
      labels: {
        converter: {
          fromAttribute(value) {
            if (!value) return {};
            try {
              return JSON.parse(value);
            } catch (_e) {
              return {};
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .card {
        position: relative;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        transition: box-shadow 0.15s ease;
        cursor: pointer;
      }
      .card:hover {
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
      }
      .card.selected {
        border-color: var(--builtin-primary, #2563eb);
        box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2);
      }
      .top {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .brand-icon {
        width: 40px;
        height: 28px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .brand-icon svg {
        width: 100%;
        height: 100%;
      }
      .actions {
        display: inline-flex;
        gap: 8px;
      }
      .icon-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: var(--builtin-radius, 6px);
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        background: var(--builtin-surface, #ffffff);
        color: var(--builtin-color-muted, #6b7280);
        cursor: pointer;
      }
      .icon-btn:hover {
        background: var(--builtin-row-hover-bg, #f9fafb);
        color: var(--builtin-danger, #dc2626);
      }
      .number {
        font-size: 18px;
        font-weight: 600;
        letter-spacing: 0.08em;
        color: var(--builtin-color-text, #111827);
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      }
      .meta {
        display: flex;
        align-items: center;
        gap: 16px;
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
      }
      .meta-item {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .meta-label {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--builtin-color-muted, #9ca3af);
      }
      .meta-value {
        font-weight: 500;
        color: var(--builtin-color-text, #111827);
      }
      @media (max-width: 720px) {
        .card {
          width: 100%;
          padding: 16px;
        }
        .number {
          font-size: 16px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.type = "card";
    this.last4 = "";
    this.expiry = "";
    this.brand = "";
    this.holder = "";
    this.labels = {};
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name)
            ? String(values[name])
            : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  _onSelect(e) {
    if (e.target.closest(".icon-btn")) return;
    this.dispatchEvent(
      new CustomEvent("builtin-select", {
        bubbles: true,
        composed: true,
        detail: { type: this.type, last4: this.last4, brand: this.brand },
      })
    );
  }

  _onDelete(e) {
    e.stopPropagation();
    this.dispatchEvent(
      new CustomEvent("builtin-delete", {
        bubbles: true,
        composed: true,
        detail: { type: this.type, last4: this.last4, brand: this.brand },
      })
    );
  }

  _brandIcon() {
    const brand = (this.brand || "").toLowerCase();
    if (brand === "visa") {
      return html`
        <svg viewBox="0 0 48 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
          <rect width="48" height="32" rx="4" fill="#1a1f71"/>
          <path d="M19.6 22h-3.1l1.9-11.4h3.1L19.6 22zM32.3 10.6l-2.8 11.4h-3l2.9-11.4h2.9zM28.2 10.6l-1.4 5.6-.6-3c-.3-1-.7-1.8-1.2-2.6h-3.2l-.1.4c1.1.5 2 1.2 2.6 2.1l-1.8 6.3h3.1l3-11.4h-2.4zM15.8 10.6c-.7-.2-1.5-.4-2.3-.4-2.6 0-4.4 1.3-4.4 3.1 0 1.4 1.3 2.1 2.3 2.6.9.4 1.3.7 1.3 1.1 0 .6-.8.9-1.5.9-1 0-2-.3-2.7-.5l-.4-.1-.4 2.5c.8.3 1.9.5 3 .5 2.7 0 4.5-1.3 4.5-3.2 0-1.1-.7-1.9-2.2-2.6-.9-.4-1.4-.7-1.4-1.2 0-.4.5-.8 1.4-.8.8 0 1.4.2 1.9.3l.3.1.3-2.3z"/>
        </svg>
      `;
    }
    if (brand === "mastercard") {
      return html`
        <svg viewBox="0 0 48 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
          <rect width="48" height="32" rx="4" fill="#f5f5f5"/>
          <circle cx="18" cy="16" r="8" fill="#eb001b"/>
          <circle cx="30" cy="16" r="8" fill="#f79e1b"/>
          <path d="M24 9.5a8 8 0 0 1 0 13" stroke="#fff" stroke-width="1.2"/>
        </svg>
      `;
    }
    if (brand === "amex") {
      return html`
        <svg viewBox="0 0 48 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
          <rect width="48" height="32" rx="4" fill="#016fd0"/>
          <path d="M8 12h6l2 3 2-3h6v8h-5l-2-3-2 3H8V12z" fill="#fff"/>
        </svg>
      `;
    }
    // Generic card icon
    return html`
      <svg viewBox="0 0 48 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
        <rect width="48" height="32" rx="4" fill="#e5e7eb"/>
        <rect x="4" y="8" width="40" height="6" rx="1" fill="#9ca3af"/>
        <rect x="4" y="20" width="20" height="4" rx="1" fill="#9ca3af"/>
      </svg>
    `;
  }

  _typeIcon() {
    const type = this.type;
    if (type === "paypal") {
      return html`
        <svg viewBox="0 0 48 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
          <rect width="48" height="32" rx="4" fill="#f5f5f5"/>
          <path d="M18 24h-3l1-6c.2-1.2 1.2-2 2.3-2h.7c2.5 0 4.5-1 5-3.5.2-1 .1-1.8-.2-2.5-.5-1.2-1.6-1.8-3.1-1.8h-5l-2 12h4.3z" fill="#003087"/>
          <path d="M30 24h-3l1-6c.2-1.2 1.2-2 2.3-2h.7c2.5 0 4.5-1 5-3.5.2-1 .1-1.8-.2-2.5-.5-1.2-1.6-1.8-3.1-1.8h-5l-2 12h4.3z" fill="#0070e0"/>
        </svg>
      `;
    }
    if (type === "alipay") {
      return html`
        <svg viewBox="0 0 48 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
          <rect width="48" height="32" rx="4" fill="#1677ff"/>
          <text x="24" y="21" text-anchor="middle" fill="#fff" font-size="12" font-weight="700" font-family="sans-serif">Alipay</text>
        </svg>
      `;
    }
    if (type === "wechat") {
      return html`
        <svg viewBox="0 0 48 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
          <rect width="48" height="32" rx="4" fill="#07c160"/>
          <circle cx="17" cy="13" r="3" fill="#fff"/>
          <circle cx="31" cy="13" r="3" fill="#fff"/>
          <path d="M13 20c2 2 6 3 10 0" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
        </svg>
      `;
    }
    return this._brandIcon();
  }

  _maskedNumber() {
    if (this.type !== "card") return "";
    const last4 = this.last4 || "****";
    return `•••• •••• •••• ${last4}`;
  }

  render() {
    const isCard = this.type === "card";
    return html`
      <div
        class="card ${classMap({ selected: false })}"
        @click=${this._onSelect}
      >
        <div class="top">
          <div class="brand-icon">${this._typeIcon()}</div>
          <div class="actions">
            <button
              class="icon-btn"
              aria-label="${this._t("payment.delete")}"
              @click=${this._onDelete}
            >
              <builtin-icon name="delete" size="16" variant="outlined"></builtin-icon>
            </button>
          </div>
        </div>

        ${isCard
          ? html`
              <div class="number">${this._maskedNumber()}</div>
              <div class="meta">
                ${this.holder
                  ? html`
                      <div class="meta-item">
                        <span class="meta-label">${this._t("payment.holder")}</span>
                        <span class="meta-value">${this.holder}</span>
                      </div>
                    `
                  : ""}
                ${this.expiry
                  ? html`
                      <div class="meta-item">
                        <span class="meta-label">${this._t("payment.expiry")}</span>
                        <span class="meta-value">${this.expiry}</span>
                      </div>
                    `
                  : ""}
              </div>
            `
          : html`
              <div class="meta">
                <div class="meta-item">
                  <span class="meta-label">${this._t("payment.type")}</span>
                  <span class="meta-value" style="text-transform:capitalize;">${this.type}</span>
                </div>
              </div>
            `}
      </div>
    `;
  }
}
