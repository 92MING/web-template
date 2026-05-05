import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinInputCreditCard — Credit card input with live preview and brand detection.
 *
 * @attr {string} number — Card number.
 * @attr {string} expiry — Expiry string (MM / YY).
 * @attr {string} cvc — CVC code.
 * @attr {string} name — Cardholder name.
 * @attr {Object} labels — JSON object for i18n overrides.
 *
 * @slot — Extra content rendered below the form.
 *
 * @event builtin-change — Detail: `{ number, expiry, cvc, name, brand }`
 */
export class BuiltinInputCreditCard extends BuiltinBaseElement {
  static properties = {
    number: { type: String },
    expiry: { type: String },
    cvc: { type: String },
    name: { type: String },
    labels: { type: Object },
    _brand: { type: String, state: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    .card-preview {
      background: linear-gradient(
        135deg,
        var(--builtin-primary, #2563eb),
        var(--builtin-primary-hover, #1d4ed8)
      );
      color: #fff;
      border-radius: var(--builtin-radius-lg, 12px);
      padding: 20px;
      max-width: 360px;
      margin-bottom: 16px;
      position: relative;
      overflow: hidden;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    .card-preview::before {
      content: "";
      position: absolute;
      top: -40%;
      right: -20%;
      width: 160px;
      height: 160px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.08);
      pointer-events: none;
    }
    .card-brand {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      height: 24px;
      margin-bottom: 24px;
    }
    .card-number {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
        monospace;
      font-size: 18px;
      letter-spacing: 2px;
      margin-bottom: 20px;
      word-break: keep-all;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .card-row {
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 12px;
    }
    .card-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      opacity: 0.8;
      margin-bottom: 2px;
    }
    .card-value {
      font-size: 13px;
      font-weight: 650;
    }
    .form {
      display: grid;
      gap: var(--builtin-form-gap, 14px);
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--builtin-form-gap, 14px);
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .label {
      font-weight: 650;
      color: var(--builtin-color-text, #111827);
      font-size: 13px;
    }
    input {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      min-height: 34px;
      padding: 6px 9px;
      width: 100%;
      font: inherit;
      outline: none;
      transition: border-color 0.15s ease;
    }
    input:focus {
      border-color: var(--builtin-primary, #2563eb);
    }
    .brand-icon {
      height: 24px;
      width: auto;
      display: block;
    }
    @media (max-width: 720px) {
      .card-preview {
        max-width: 100%;
        padding: 16px;
        margin-bottom: 12px;
      }
      .card-number {
        font-size: 16px;
        margin-bottom: 16px;
      }
      .row {
        grid-template-columns: 1fr;
      }
      input {
        min-height: 44px;
        font-size: 16px;
      }
    }
  `;

  constructor() {
    super();
    this.number = "";
    this.expiry = "";
    this.cvc = "";
    this.name = "";
    this._brand = "";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _detectBrand(num) {
    const n = (num || "").replace(/\s/g, "");
    if (/^4/.test(n)) return "visa";
    if (/^5[1-5]/.test(n)) return "mastercard";
    if (
      /^2(2(2[1-9]|[3-9][0-9])|[3-6][0-9]{2}|7([01][0-9]|20))/.test(n)
    )
      return "mastercard";
    if (/^3[47]/.test(n)) return "amex";
    if (/^62/.test(n)) return "unionpay";
    return "";
  }

  _formatNumber(raw) {
    const digits = (raw || "").replace(/\D/g, "").slice(0, 19);
    const parts = [];
    for (let i = 0; i < digits.length; i += 4) {
      parts.push(digits.slice(i, i + 4));
    }
    return parts.join(" ");
  }

  _formatExpiry(raw) {
    const digits = (raw || "").replace(/\D/g, "").slice(0, 4);
    if (digits.length > 2) return digits.slice(0, 2) + " / " + digits.slice(2);
    return digits;
  }

  _onNumberInput(e) {
    const raw = e.target.value;
    this.number = this._formatNumber(raw);
    this._brand = this._detectBrand(this.number);
    e.target.value = this.number;
    this._emit();
  }

  _onExpiryInput(e) {
    const raw = e.target.value;
    this.expiry = this._formatExpiry(raw);
    e.target.value = this.expiry;
    this._emit();
  }

  _onCvcInput(e) {
    const val = (e.target.value || "").replace(/\D/g, "").slice(0, 4);
    this.cvc = val;
    e.target.value = this.cvc;
    this._emit();
  }

  _onNameInput(e) {
    this.name = e.target.value;
    this._emit();
  }

  _emit() {
    this.dispatchEvent(
      new CustomEvent("builtin-change", {
        detail: {
          number: this.number,
          expiry: this.expiry,
          cvc: this.cvc,
          name: this.name,
          brand: this._brand,
        },
        bubbles: true,
        composed: true,
      })
    );
  }

  _brandSvg() {
    switch (this._brand) {
      case "visa":
        return html`<svg
          class="brand-icon"
          viewBox="0 0 48 16"
          fill="none"
        >
          <path
            d="M17.68 1.5l-4.5 10.5h-2.9L7.2 3.8c-.2-.6-.4-1-.6-1.2-.6-.7-1.5-1-2.4-1.1l.1-.5h4.1c.5 0 1 .3 1.1.9l1.4 6.2L13.5 1.5h3.18zm10.6 7.1c0-2.8-3.9-2.9-3.9-4.2 0-.4.4-.8 1.2-.9.4 0 1.5.1 2.8.5l.5-2.3c-.7-.2-1.6-.4-2.6-.4-2.8 0-4.7 1.5-4.7 3.6 0 1.6 1.4 2.4 2.5 3 1.1.5 1.5.9 1.5 1.3 0 .7-.9 1-1.7 1-1.4 0-2.2-.4-2.8-.6l-.5 2.4c.7.3 1.9.5 3.2.5 2.9 0 4.8-1.4 4.8-3.7l.2-.2zm7.4 3.4h2.3l-2-10.5h-2.1c-.5 0-.9.3-1 .7l-3.6 9.8h2.6l.5-1.4h3.1l.2 1.4zm-2.7-3.3l1.3-3.5.7 3.5h-2zm-10.1-7.2L21.5 9l-.3-4.2c-.1-.6-.6-1.1-1.2-1.3l-3.8-.4 4.6 10.5h3l6.8-10.5h-3.2z"
            fill="#fff"
          />
        </svg>`;
      case "mastercard":
        return html`<svg
          class="brand-icon"
          viewBox="0 0 24 16"
          fill="none"
        >
          <circle cx="6" cy="8" r="6" fill="#eb001b" />
          <circle cx="14" cy="8" r="6" fill="#f79e1b" />
          <path d="M10 3.5a6 6 0 0 0 0 9 6 6 0 0 0 0-9z" fill="#ff5f00" />
        </svg>`;
      case "amex":
        return html`<svg
          class="brand-icon"
          viewBox="0 0 24 16"
          fill="none"
        >
          <rect width="24" height="16" rx="2" fill="#fff" />
          <path
            d="M2 8h4l1.5-2.5L9 8h4V6H9.5L8 3.5 6.5 6H2v2zm0 2h4l1.5-2.5L9 10h4V8H9.5L8 5.5 6.5 8H2v2z"
            fill="#006fcf"
            transform="translate(4,2) scale(0.8)"
          />
        </svg>`;
      case "unionpay":
        return html`<svg
          class="brand-icon"
          viewBox="0 0 24 16"
          fill="none"
        >
          <rect width="24" height="16" rx="2" fill="#e21836" />
          <path d="M4 4h4l2 8h-4z" fill="#00447c" />
          <path d="M10 4h4l-2 8h-4z" fill="#01798a" />
          <path d="M16 4h4l-2 8h-4z" fill="#e21836" />
        </svg>`;
      default:
        return html`<svg
          class="brand-icon"
          viewBox="0 0 24 16"
          fill="none"
        >
          <rect width="24" height="16" rx="2" fill="rgba(255,255,255,0.3)" />
        </svg>`;
    }
  }

  render() {
    const isMobile = this._ptMobile;
    const displayNumber = this.number || "#### #### #### ####";
    const displayExpiry = this.expiry || "MM / YY";
    const displayName =
      this.name || this._l("card.namePlaceholder", "YOUR NAME");

    return html`
      <div class="wrap ${classMap({ mobile: isMobile })}" part="wrap">
        <div class="card-preview" part="preview">
          <div class="card-brand">${this._brandSvg()}</div>
          <div class="card-number">${displayNumber}</div>
          <div class="card-row">
            <div>
              <div class="card-label">
                ${this._l("card.cardholder", "Cardholder")}
              </div>
              <div class="card-value">${displayName}</div>
            </div>
            <div>
              <div class="card-label">
                ${this._l("card.expires", "Expires")}
              </div>
              <div class="card-value">${displayExpiry}</div>
            </div>
          </div>
        </div>
        <div class="form" part="form">
          <div class="field">
            <label class="label" for="cc-number"
              >${this._l("card.number", "Card number")}</label
            >
            <input
              id="cc-number"
              type="text"
              inputmode="numeric"
              .value="${this.number}"
              @input="${this._onNumberInput}"
              placeholder="#### #### #### ####"
              autocomplete="cc-number"
              part="input-number"
            />
          </div>
          <div class="field">
            <label class="label" for="cc-name"
              >${this._l("card.name", "Name on card")}</label
            >
            <input
              id="cc-name"
              type="text"
              .value="${this.name}"
              @input="${this._onNameInput}"
              placeholder="${this._l("card.namePlaceholder", "YOUR NAME")}"
              autocomplete="cc-name"
              part="input-name"
            />
          </div>
          <div class="row">
            <div class="field">
              <label class="label" for="cc-expiry"
                >${this._l("card.expiry", "Expiry (MM / YY)")}</label
              >
              <input
                id="cc-expiry"
                type="text"
                inputmode="numeric"
                .value="${this.expiry}"
                @input="${this._onExpiryInput}"
                placeholder="MM / YY"
                autocomplete="cc-exp"
                part="input-expiry"
              />
            </div>
            <div class="field">
              <label class="label" for="cc-cvc"
                >${this._l("card.cvc", "CVC")}</label
              >
              <input
                id="cc-cvc"
                type="text"
                inputmode="numeric"
                .value="${this.cvc}"
                @input="${this._onCvcInput}"
                placeholder="CVC"
                autocomplete="cc-csc"
                maxlength="4"
                part="input-cvc"
              />
            </div>
          </div>
        </div>
        <slot></slot>
      </div>
    `;
  }
}
