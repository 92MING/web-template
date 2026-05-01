/**
 * @fileoverview BuiltinTplEcommerceCheckout - Checkout / payment page template (Lit).
 *
 * Attributes:
 *   - items: JSON array of order items { title, qty, price }
 *   - subtotal: Order subtotal string
 *   - shipping: Shipping cost string
 *   - total: Order total string
 *   - labels: JSON object for i18n overrides
 *
 * Slots:
 *   - navbar: Top navigation bar
 *
 * Events:
 *   - builtin-place-order: Place order clicked. Detail: { items, subtotal, shipping, total }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

export class BuiltinTplEcommerceCheckout extends BuiltinBaseElement {
  static get properties() {
    return {
      items: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "[]"); } catch { return []; }
          },
        },
      },
      subtotal: { type: String },
      shipping: { type: String },
      total: { type: String },
      labels: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "{}"); } catch { return {}; }
          },
        },
      },
    };
  }

  constructor() {
    super();
    this.items = [];
    this.subtotal = "$0.00";
    this.shipping = "$0.00";
    this.total = "$0.00";
    this.labels = {};
    this._summaryOpen = false;
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = String(this.labels[key]);
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  _onToggleSummary() {
    this._summaryOpen = !this._summaryOpen;
  }

  _onPlaceOrder() {
    this.dispatchEvent(
      new CustomEvent("builtin-place-order", {
        bubbles: true,
        composed: true,
        detail: {
          items: this._getItems(),
          subtotal: this.subtotal,
          shipping: this.shipping,
          total: this.total,
        },
      })
    );
  }

  _getItems() {
    if (Array.isArray(this.items) && this.items.length) return this.items;
    return [
      { title: "Product A", qty: 1, price: "$49.00" },
      { title: "Product B", qty: 2, price: "$24.50" },
    ];
  }

  _renderItems(items) {
    return html`
      ${repeat(
        items,
        (item, i) => i,
        (item) => html`
          <div class="summary-item">
            <div class="summary-item-meta">
              <span class="summary-item-title">${item.title || "Item"}</span>
              <span class="muted">× ${Number(item.qty) || 1}</span>
            </div>
            <span class="summary-item-price">${item.price || "$0.00"}</span>
          </div>
        `
      )}
    `;
  }

  render() {
    const items = this._getItems();
    const summaryHidden = this._ptMobile && !this._summaryOpen;

    return html`
      <slot name="navbar"><builtin-navbar></builtin-navbar></slot>

      <div class="container">
        <div class="checkout-wrap">
          <div class="left">
            <section class="section">
              <h2 class="section-title">${this._t("checkout.shippingAddress")}</h2>
              <div class="form">
                <div class="form-row">
                  <div class="field">
                    <label>${this._t("checkout.firstName")}</label>
                    <input type="text" placeholder="Jane" />
                  </div>
                  <div class="field">
                    <label>${this._t("checkout.lastName")}</label>
                    <input type="text" placeholder="Doe" />
                  </div>
                </div>
                <div class="field">
                  <label>${this._t("checkout.address")}</label>
                  <input type="text" placeholder="123 Main St" />
                </div>
                <div class="form-row">
                  <div class="field">
                    <label>${this._t("checkout.city")}</label>
                    <input type="text" placeholder="New York" />
                  </div>
                  <div class="field">
                    <label>${this._t("checkout.postalCode")}</label>
                    <input type="text" placeholder="10001" />
                  </div>
                </div>
                <div class="field">
                  <label>${this._t("checkout.country")}</label>
                  <select>
                    <option>United States</option>
                    <option>Canada</option>
                    <option>United Kingdom</option>
                  </select>
                </div>
              </div>
            </section>

            <section class="section" style="margin-top: 24px;">
              <h2 class="section-title">${this._t("checkout.paymentMethod")}</h2>
              <div class="payment-methods">
                <label class="pay-option">
                  <input type="radio" name="payment" value="card" checked />
                  <span>${this._t("checkout.card")}</span>
                </label>
                <label class="pay-option">
                  <input type="radio" name="payment" value="paypal" />
                  <span>${this._t("checkout.paypal")}</span>
                </label>
                <label class="pay-option">
                  <input type="radio" name="payment" value="cod" />
                  <span>${this._t("checkout.cod")}</span>
                </label>
              </div>
            </section>
          </div>

          <div class="right">
            ${this._ptMobile
              ? html`
                  <button class="mobile-summary-toggle" @click=${this._onToggleSummary}>
                    <span>${this._t("checkout.orderSummary")}</span>
                    <span>${this.total}</span>
                  </button>
                `
              : ""}
            <div class="summary-card">
              ${!this._ptMobile
                ? html`<div class="summary-header">${this._t("checkout.orderSummary")}</div>`
                : ""}
              <div class="summary-body" ?hidden=${summaryHidden}>
                ${this._renderItems(items)}
                <div class="summary-divider"></div>
                <div class="discount-row">
                  <input type="text" placeholder="${this._t("checkout.discountCode")}" />
                  <button class="btn">${this._t("checkout.apply")}</button>
                </div>
                <div class="summary-divider"></div>
                <div class="summary-row muted">
                  <span>${this._t("checkout.subtotal")}</span>
                  <span>${this.subtotal}</span>
                </div>
                <div class="summary-row muted">
                  <span>${this._t("checkout.shipping")}</span>
                  <span>${this.shipping}</span>
                </div>
                <div class="summary-divider"></div>
                <div class="summary-row summary-total">
                  <span>${this._t("checkout.total")}</span>
                  <span>${this.total}</span>
                </div>
                <button class="btn btn-primary" @click=${this._onPlaceOrder}>
                  ${this._t("checkout.placeOrder")}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
        line-height: 1.55;
      }
      .container {
        max-width: 1040px;
        margin: 0 auto;
        padding: 0 20px;
      }
      .checkout-wrap {
        display: grid;
        grid-template-columns: 1fr 360px;
        gap: 32px;
        padding: 28px 0;
      }
      .section-title {
        font-size: 18px;
        font-weight: 700;
        margin-bottom: 16px;
        color: var(--builtin-color-text);
      }
      .form {
        display: grid;
        gap: 14px;
      }
      .form-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 14px;
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .field label {
        font-size: 13px;
        font-weight: 650;
        color: var(--builtin-color-muted, #6b7280);
      }
      .field input,
      .field select {
        width: 100%;
        padding: 10px 12px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-header-bg);
        color: var(--builtin-color-text);
        font-size: 14px;
        box-sizing: border-box;
      }
      .payment-methods {
        display: flex;
        flex-direction: column;
        gap: 10px;
        margin-top: 8px;
      }
      .pay-option {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 14px;
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius, 6px);
        cursor: pointer;
        background: var(--builtin-surface, #ffffff);
      }
      .pay-option:hover {
        background: var(--builtin-row-hover-bg, #f9fafb);
      }
      .pay-option input {
        width: auto;
        min-height: auto;
        margin: 0;
      }
      .summary-card {
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
        overflow: hidden;
      }
      .summary-header {
        padding: 16px 18px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        font-weight: 700;
        color: var(--builtin-color-text);
      }
      .summary-body {
        padding: 16px 18px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .summary-body[hidden] {
        display: none;
      }
      .summary-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .summary-item-meta {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .summary-item-title {
        font-weight: 600;
        color: var(--builtin-color-text);
      }
      .summary-item-price {
        font-weight: 600;
        color: var(--builtin-color-text);
      }
      .summary-divider {
        height: 1px;
        background: var(--builtin-border-soft, #e5e7eb);
        margin: 4px 0;
      }
      .summary-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .summary-total {
        font-size: 18px;
        font-weight: 700;
        color: var(--builtin-color-text);
      }
      .discount-row {
        display: flex;
        gap: 8px;
      }
      .discount-row input {
        flex: 1 1 auto;
        padding: 10px 12px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-header-bg);
        color: var(--builtin-color-text);
        font-size: 14px;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 12px 18px;
        border-radius: var(--builtin-radius, 6px);
        border: 1px solid var(--builtin-border, #d1d5db);
        background: var(--builtin-button-bg, #ffffff);
        color: var(--builtin-color-text, #111827);
        font-weight: 600;
        cursor: pointer;
        font: inherit;
      }
      .btn:hover {
        background: var(--builtin-button-hover-bg, #f9fafb);
      }
      .btn-primary {
        background: var(--builtin-primary, #2563eb);
        border-color: var(--builtin-primary, #2563eb);
        color: #fff;
      }
      .btn-primary:hover {
        background: var(--builtin-primary-hover, #1d4ed8);
      }
      .muted {
        color: var(--builtin-color-muted, #6b7280);
      }
      .mobile-summary-toggle {
        display: none;
        width: 100%;
        padding: 12px 16px;
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-header-bg, #f9fafb);
        color: var(--builtin-color-text, #111827);
        font-weight: 600;
        cursor: pointer;
        margin-bottom: 12px;
        align-items: center;
        justify-content: space-between;
      }

      @media (max-width: 720px) {
        .container {
          padding: 0 16px;
        }
        .checkout-wrap {
          grid-template-columns: 1fr;
          gap: 20px;
          padding: 16px 0;
        }
        .form-row {
          grid-template-columns: 1fr;
        }
        .mobile-summary-toggle {
          display: flex;
        }
        .summary-card {
          order: -1;
        }
        .btn {
          width: 100%;
          min-height: 44px;
        }
      }
    `;
  }
}