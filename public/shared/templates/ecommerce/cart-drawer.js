/**
 * @fileoverview BuiltinTplEcommerceCartDrawer - Shopping cart side panel template (Lit).
 *
 * Attributes:
 *   - open: Drawer visibility (boolean)
 *   - items: JSON array of cart items { id, title, qty, price, image }
 *   - labels: JSON object for i18n overrides
 *
 * Methods:
 *   - openDrawer(): Show the drawer.
 *   - close(): Hide the drawer.
 *
 * Events:
 *   - builtin-update: Quantity changed. Detail: { id, qty }.
 *   - builtin-remove: Item removed. Detail: { id }.
 *   - builtin-checkout: Checkout button clicked.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

export class BuiltinTplEcommerceCartDrawer extends BuiltinBaseElement {
  static get properties() {
    return {
      open: { type: Boolean, reflect: true },
      items: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "[]"); } catch { return []; }
          },
        },
      },
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
    this.open = false;
    this.items = [];
    this.labels = {};
    this._escHandler = (e) => {
      if (e.key === "Escape" && this.open) this.close();
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("keydown", this._escHandler);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._escHandler);
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

  openDrawer() {
    this.open = true;
  }

  close() {
    this.open = false;
  }

  _onMaskClick() {
    this.close();
  }

  _onCloseClick() {
    this.close();
  }

  _onRemove(e) {
    const id = e.currentTarget.dataset.id || "";
    this.dispatchEvent(
      new CustomEvent("builtin-remove", { bubbles: true, composed: true, detail: { id } })
    );
  }

  _onQtyChange(e) {
    const btn = e.currentTarget;
    const action = btn.dataset.action;
    const id = btn.dataset.id || "";
    const currentQty = Number(btn.dataset.qty) || 1;
    const delta = action === "qty-inc" ? 1 : -1;
    const newQty = Math.max(1, currentQty + delta);
    this.dispatchEvent(
      new CustomEvent("builtin-update", {
        bubbles: true,
        composed: true,
        detail: { id, qty: newQty },
      })
    );
  }

  _onCheckout() {
    this.dispatchEvent(new CustomEvent("builtin-checkout", { bubbles: true, composed: true }));
  }

  _computeSubtotal(items) {
    return items
      .reduce((sum, item) => {
        const price = Number(String(item.price).replace(/[^0-9.]/g, "")) || 0;
        const qty = Number(item.qty) || 1;
        return sum + price * qty;
      }, 0)
      .toFixed(2);
  }

  _renderItems(items) {
    if (!items.length) {
      return html`<div class="empty">${this._t("cart.empty")}</div>`;
    }
    return html`
      ${repeat(
        items,
        (item) => item.id,
        (item) => {
          const id = String(item.id ?? "");
          const qty = Number(item.qty) || 1;
          return html`
            <div class="cart-item">
              <div class="item-img">
                ${item.image ? html`<img src="${item.image}" alt="" />` : ""}
              </div>
              <div class="item-info">
                <div class="item-title">${item.title || "Item"}</div>
                <div class="item-price">${item.price || "$0.00"}</div>
                <div class="item-controls">
                  <div class="qty-stepper">
                    <button
                      data-action="qty-dec"
                      data-id="${id}"
                      data-qty="${qty}"
                      aria-label="Decrease"
                      @click=${this._onQtyChange}
                    >
                      −
                    </button>
                    <span class="qty-value">${qty}</span>
                    <button
                      data-action="qty-inc"
                      data-id="${id}"
                      data-qty="${qty}"
                      aria-label="Increase"
                      @click=${this._onQtyChange}
                    >
                      +
                    </button>
                  </div>
                  <button
                    class="remove-btn"
                    data-id="${id}"
                    aria-label="Remove"
                    @click=${this._onRemove}
                  >
                    <builtin-icon name="delete" size="16" variant="outlined"></builtin-icon>
                  </button>
                </div>
              </div>
            </div>
          `;
        }
      )}
    `;
  }

  render() {
    const items = this.items;
    const subtotal = this._computeSubtotal(items);

    return html`
      <div class="drawer-mask" ?hidden=${!this.open} @click=${this._onMaskClick}></div>
      <div
        class="drawer-panel ${this._ptMobile ? "mobile" : ""}"
        role="dialog"
        aria-modal="true"
        ?hidden=${!this.open}
      >
        <div class="drawer-header">
          <h2>${this._t("cart.title")} (${items.length})</h2>
          <button class="drawer-close" @click=${this._onCloseClick} aria-label="Close">
            <builtin-icon name="close" size="20" variant="outlined"></builtin-icon>
          </button>
        </div>
        <div class="drawer-body">${this._renderItems(items)}</div>
        <div class="drawer-footer">
          <div class="subtotal-row">
            <span>${this._t("cart.subtotal")}</span>
            <span>$${subtotal}</span>
          </div>
          <button class="btn btn-primary" @click=${this._onCheckout}>
            ${this._t("cart.checkout")}
          </button>
        </div>
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .drawer-mask {
        position: fixed;
        inset: 0;
        z-index: 9998;
        background: rgba(0, 0, 0, 0.45);
        animation: drawer-mask-in 0.2s ease;
      }
      .drawer-mask[hidden] {
        display: none;
      }
      .drawer-panel {
        position: fixed;
        right: 0;
        top: 0;
        bottom: 0;
        width: 420px;
        max-width: 100%;
        background: var(--builtin-surface, #ffffff);
        z-index: 9999;
        display: flex;
        flex-direction: column;
        transform: translateX(0);
        transition: transform 0.25s ease;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.18);
      }
      .drawer-panel[hidden] {
        transform: translateX(100%);
      }
      .drawer-panel.mobile {
        width: 100%;
        top: auto;
        left: 0;
        right: 0;
        bottom: 0;
        height: calc(100% - 40px);
        border-radius: var(--builtin-radius-lg, 8px) var(--builtin-radius-lg, 8px) 0 0;
      }
      .drawer-panel.mobile[hidden] {
        transform: translateY(100%);
      }
      .drawer-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 18px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        min-height: 56px;
      }
      .drawer-header h2 {
        margin: 0;
        font-size: 16px;
        font-weight: 700;
        color: var(--builtin-color-text);
      }
      .drawer-close {
        border: 0;
        background: transparent;
        padding: 4px;
        min-height: 0;
        color: var(--builtin-color-muted, #6b7280);
        cursor: pointer;
        border-radius: var(--builtin-radius, 6px);
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .drawer-close:hover {
        background: var(--builtin-row-hover-bg, #f3f4f6);
        color: var(--builtin-color-text, #111827);
      }
      .drawer-body {
        flex: 1 1 auto;
        overflow-y: auto;
        padding: 16px 18px;
      }
      .empty {
        text-align: center;
        color: var(--builtin-color-muted, #6b7280);
        padding: 40px 0;
      }
      .cart-item {
        display: flex;
        gap: 14px;
        padding: 14px 0;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      }
      .item-img {
        width: 72px;
        height: 72px;
        background: var(--builtin-header-bg, #f9fafb);
        border-radius: var(--builtin-radius, 6px);
        overflow: hidden;
        flex-shrink: 0;
      }
      .item-img img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .item-info {
        flex: 1 1 auto;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .item-title {
        font-weight: 600;
        font-size: 14px;
        color: var(--builtin-color-text);
      }
      .item-price {
        font-weight: 700;
        color: var(--builtin-primary, #2563eb);
        font-size: 14px;
      }
      .item-controls {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: 4px;
      }
      .qty-stepper {
        display: inline-flex;
        align-items: center;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius, 6px);
        overflow: hidden;
      }
      .qty-stepper button {
        min-height: 30px;
        width: 30px;
        padding: 0;
        border: 0;
        background: var(--builtin-button-bg, #ffffff);
        font-size: 16px;
        cursor: pointer;
        color: var(--builtin-color-text);
      }
      .qty-stepper button:hover {
        background: var(--builtin-button-hover-bg, #f9fafb);
      }
      .qty-value {
        min-width: 36px;
        text-align: center;
        font-size: 13px;
        border-left: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-right: 1px solid var(--builtin-border-soft, #e5e7eb);
        line-height: 30px;
        color: var(--builtin-color-text);
      }
      .remove-btn {
        border: 0;
        background: transparent;
        color: var(--builtin-color-muted, #6b7280);
        font-size: 18px;
        cursor: pointer;
        padding: 2px 6px;
        min-height: 0;
        border-radius: var(--builtin-radius, 6px);
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .remove-btn:hover {
        background: var(--builtin-row-hover-bg, #f3f4f6);
        color: var(--builtin-color-danger, #b91c1c);
      }
      .drawer-footer {
        padding: 16px 18px;
        border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .subtotal-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-weight: 700;
        color: var(--builtin-color-text);
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
      @keyframes drawer-mask-in {
        from {
          opacity: 0;
        }
        to {
          opacity: 1;
        }
      }
    `;
  }
}