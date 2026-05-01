/**
 * @fileoverview BuiltinTplEcommerceProductDetail - Product detail page template (Lit).
 *
 * Attributes:
 *   - title: Product name
 *   - price: Current price
 *   - old-price: Strikethrough original price
 *   - rating: Numeric rating 0-5
 *   - description: Short description
 *   - image: Main image URL
 *   - images: JSON array of gallery URLs
 *   - labels: JSON object for i18n overrides
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - footer: Page footer
 *
 * Events:
 *   - builtin-add-cart: Add to cart clicked. Detail: { quantity, variant }.
 *   - builtin-buy-now: Buy now clicked. Detail: { quantity, variant }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

export class BuiltinTplEcommerceProductDetail extends BuiltinBaseElement {
  static get properties() {
    return {
      title: { type: String },
      price: { type: String },
      oldPrice: { type: String, attribute: "old-price" },
      rating: { type: String },
      description: { type: String },
      image: { type: String },
      images: {
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
    this.title = "Product Name";
    this.price = "$0.00";
    this.oldPrice = "";
    this.rating = "0";
    this.description = "";
    this.image = "";
    this.images = [];
    this.labels = {};
    this._quantity = 1;
    this._selectedVariant = "";
    this._activeTab = "description";
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

  _getImages() {
    if (Array.isArray(this.images) && this.images.length) return this.images;
    return this.image ? [this.image] : [];
  }

  _onTabClick(e) {
    const tab = e.currentTarget.dataset.tab;
    if (tab) this._activeTab = tab;
  }

  _onQtyInc() {
    this._quantity += 1;
  }

  _onQtyDec() {
    if (this._quantity > 1) this._quantity -= 1;
  }

  _onVariantClick(e) {
    this._selectedVariant = e.currentTarget.dataset.value || "";
  }

  _onThumbClick(e) {
    this.image = e.currentTarget.dataset.src || "";
  }

  _onAddCart() {
    this.dispatchEvent(
      new CustomEvent("builtin-add-cart", {
        bubbles: true,
        composed: true,
        detail: { quantity: this._quantity, variant: this._selectedVariant },
      })
    );
  }

  _onBuyNow() {
    this.dispatchEvent(
      new CustomEvent("builtin-buy-now", {
        bubbles: true,
        composed: true,
        detail: { quantity: this._quantity, variant: this._selectedVariant },
      })
    );
  }

  _renderStars(rating) {
    const r = Math.max(0, Math.min(5, Number(rating) || 0));
    return html`
      ${[1, 2, 3, 4, 5].map((i) => {
        const filled = i <= r;
        return html`
          <builtin-icon
            class="star ${filled ? "filled" : ""}"
            name="star"
            size="16"
            variant="outlined"
          ></builtin-icon>
        `;
      })}
    `;
  }

  _renderTabs() {
    const tabs = [
      { key: "description", label: this._t("product.description") },
      { key: "specs", label: this._t("product.specs") },
      { key: "reviews", label: this._t("product.reviews") },
    ];

    const tabContent = () => {
      if (this._activeTab === "description") {
        return html`<p>${this.description || this._t("product.noDescription")}</p>`;
      }
      if (this._activeTab === "specs") {
        return html`
          <table class="specs-table">
            <tr><td>Material</td><td>Premium quality</td></tr>
            <tr><td>Weight</td><td>1.2 kg</td></tr>
            <tr><td>Dimensions</td><td>20 × 15 × 10 cm</td></tr>
            <tr><td>Warranty</td><td>2 years</td></tr>
          </table>
        `;
      }
      return html`<p class="muted">${this._t("product.noReviews")}</p>`;
    };

    if (this._ptMobile) {
      return html`
        <div class="tabs">
          ${tabs.map(
            (t) => html`
              <details class="accordion-item" ?open=${this._activeTab === t.key}>
                <summary @click=${() => { this._activeTab = t.key; }}>${t.label}</summary>
                <div class="accordion-body">${tabContent()}</div>
              </details>
            `
          )}
        </div>
      `;
    }

    return html`
      <div class="tabs">
        <div class="tab-list">
          ${tabs.map(
            (t) => html`
              <button
                class="tab-btn ${this._activeTab === t.key ? "active" : ""}"
                data-tab="${t.key}"
                @click=${this._onTabClick}
              >
                ${t.label}
              </button>
            `
          )}
        </div>
        <div class="tab-panel">${tabContent()}</div>
      </div>
    `;
  }

  _renderRelated() {
    const items = ["Related A", "Related B", "Related C", "Related D"];
    return html`
      ${items.map(
        (name) => html`
          <div class="related-card">
            <div class="related-img"></div>
            <div class="related-info">
              <h4>${name}</h4>
              <div class="related-price">$${Math.floor(Math.random() * 90 + 10)}.00</div>
            </div>
          </div>
        `
      )}
    `;
  }

  render() {
    const images = this._getImages();
    const variants = ["S", "M", "L", "XL"];

    return html`
      <slot name="navbar"><builtin-navbar></builtin-navbar></slot>

      <div class="container">
        <div class="product-wrap">
          <div class="gallery">
            <div class="main-img">
              ${this.image
                ? html`<img src="${this.image}" alt="${this.title}" />`
                : html`<span class="muted">${this._t("product.noImage")}</span>`}
            </div>
            <div class="thumbs">
              ${repeat(
                images,
                (src) => src,
                (src) => html`
                  <button
                    class="thumb ${src === this.image ? "active" : ""}"
                    @click=${this._onThumbClick}
                    data-src="${src}"
                  >
                    <img src="${src}" alt="" />
                  </button>
                `
              )}
            </div>
          </div>
          <div class="info">
            <h1>${this.title}</h1>
            <div class="price-row">
              <span class="price">${this.price}</span>
              ${this.oldPrice ? html`<span class="old-price">${this.oldPrice}</span>` : ""}
            </div>
            <div class="rating">
              ${this._renderStars(this.rating)}
              <span class="muted">(${this.rating})</span>
            </div>
            <p class="desc">${this.description}</p>
            <div class="variants">
              <span class="variant-label">${this._t("product.size")}</span>
              <div class="variant-btns">
                ${variants.map(
                  (v) => html`
                    <button
                      class="variant-btn ${this._selectedVariant === v ? "active" : ""}"
                      @click=${this._onVariantClick}
                      data-value="${v}"
                    >
                      ${v}
                    </button>
                  `
                )}
              </div>
            </div>
            <div class="qty-row">
              <div class="qty-stepper">
                <button @click=${this._onQtyDec} aria-label="Decrease">−</button>
                <input type="text" readonly .value=${this._quantity} />
                <button @click=${this._onQtyInc} aria-label="Increase">+</button>
              </div>
            </div>
            <div class="actions">
              <button class="btn btn-primary" @click=${this._onAddCart}>
                ${this._t("product.addToCart")}
              </button>
              <button class="btn" @click=${this._onBuyNow}>${this._t("product.buyNow")}</button>
            </div>
          </div>
        </div>

        ${this._renderTabs()}

        <div class="related">
          <h2>${this._t("product.relatedTitle")}</h2>
          <div class="related-grid">${this._renderRelated()}</div>
        </div>
      </div>

      <slot name="footer"><builtin-footer></builtin-footer></slot>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
        line-height: 1.55;
      }
      .container {
        max-width: 1140px;
        margin: 0 auto;
        padding: 0 20px;
      }
      .product-wrap {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 40px;
        padding: 32px 0;
      }
      .gallery {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .main-img {
        width: 100%;
        aspect-ratio: 1 / 1;
        background: var(--builtin-header-bg, #f9fafb);
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius-lg, 8px);
        display: grid;
        place-items: center;
        overflow: hidden;
      }
      .main-img img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .thumbs {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }
      .thumb {
        width: 72px;
        height: 72px;
        background: var(--builtin-header-bg, #f9fafb);
        border: 2px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius, 6px);
        cursor: pointer;
        overflow: hidden;
        padding: 0;
      }
      .thumb.active {
        border-color: var(--builtin-primary, #2563eb);
      }
      .thumb img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .info {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .info h1 {
        font-size: clamp(22px, 3vw, 32px);
        font-weight: 700;
        margin: 0;
        color: var(--builtin-color-text);
      }
      .price-row {
        display: flex;
        align-items: baseline;
        gap: 12px;
        flex-wrap: wrap;
      }
      .price {
        font-size: 28px;
        font-weight: 700;
        color: var(--builtin-primary, #2563eb);
      }
      .old-price {
        font-size: 18px;
        color: var(--builtin-color-muted, #6b7280);
        text-decoration: line-through;
      }
      .rating {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 15px;
      }
      .star {
        color: var(--builtin-border);
      }
      .star.filled {
        color: #f59e0b;
      }
      .desc {
        color: var(--builtin-color-muted, #6b7280);
        margin: 0;
      }
      .variants {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .variant-label {
        font-size: 13px;
        font-weight: 650;
        color: var(--builtin-color-muted, #6b7280);
        text-transform: uppercase;
        letter-spacing: 0.4px;
      }
      .variant-btns {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      .variant-btn {
        padding: 8px 14px;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-button-bg, #ffffff);
        color: var(--builtin-color-text, #111827);
        cursor: pointer;
        font: inherit;
        font-size: 13px;
      }
      .variant-btn.active {
        border-color: var(--builtin-primary, #2563eb);
        background: var(--builtin-primary, #2563eb);
        color: #fff;
      }
      .variant-btn:hover:not(.active) {
        background: var(--builtin-button-hover-bg, #f9fafb);
      }
      .qty-row {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .qty-stepper {
        display: inline-flex;
        align-items: center;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius, 6px);
        overflow: hidden;
      }
      .qty-stepper button {
        min-height: 38px;
        width: 38px;
        padding: 0;
        border: 0;
        background: var(--builtin-button-bg, #ffffff);
        font-size: 18px;
        cursor: pointer;
        color: var(--builtin-color-text);
      }
      .qty-stepper button:hover {
        background: var(--builtin-button-hover-bg, #f9fafb);
      }
      .qty-stepper input {
        width: 56px;
        text-align: center;
        border: 0;
        border-left: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-right: 1px solid var(--builtin-border-soft, #e5e7eb);
        min-height: 38px;
        padding: 0;
        background: transparent;
        color: var(--builtin-color-text);
      }
      .actions {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 12px 24px;
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
      .tabs {
        margin-top: 8px;
      }
      .tab-list {
        display: flex;
        gap: 4px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      }
      .tab-btn {
        padding: 10px 16px;
        background: transparent;
        border: 0;
        border-bottom: 2px solid transparent;
        color: var(--builtin-color-muted, #6b7280);
        cursor: pointer;
        font: inherit;
        font-weight: 600;
      }
      .tab-btn.active {
        color: var(--builtin-color-text, #111827);
        border-bottom-color: var(--builtin-primary, #2563eb);
      }
      .tab-panel {
        padding: 20px 0;
      }
      .accordion-item {
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius, 6px);
        margin-bottom: 10px;
        padding: 12px 16px;
        background: var(--builtin-surface, #ffffff);
      }
      .accordion-item summary {
        font-weight: 700;
        cursor: pointer;
        color: var(--builtin-color-text);
      }
      .accordion-body {
        padding-top: 10px;
        color: var(--builtin-color-text);
      }
      .specs-table {
        width: 100%;
        border-collapse: collapse;
      }
      .specs-table td {
        padding: 10px 12px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      }
      .specs-table td:first-child {
        color: var(--builtin-color-muted, #6b7280);
        width: 40%;
      }
      .muted {
        color: var(--builtin-color-muted, #6b7280);
      }
      .related {
        padding: 32px 0;
        border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      }
      .related h2 {
        font-size: 20px;
        font-weight: 700;
        margin-bottom: 16px;
        color: var(--builtin-color-text);
      }
      .related-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 20px;
      }
      .related-card {
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius-lg, 8px);
        overflow: hidden;
        background: var(--builtin-surface, #ffffff);
        cursor: pointer;
      }
      .related-img {
        aspect-ratio: 4 / 3;
        background: var(--builtin-header-bg, #f9fafb);
      }
      .related-info {
        padding: 12px;
      }
      .related-info h4 {
        font-size: 14px;
        margin: 0 0 6px;
        color: var(--builtin-color-text);
      }
      .related-price {
        font-weight: 700;
        color: var(--builtin-primary, #2563eb);
        font-size: 14px;
      }

      @media (max-width: 720px) {
        .container {
          padding: 0 16px;
        }
        .product-wrap {
          grid-template-columns: 1fr;
          gap: 24px;
          padding: 20px 0;
        }
        .main-img {
          aspect-ratio: 16 / 10;
        }
        .actions .btn {
          flex: 1 1 auto;
          min-height: 44px;
        }
        .tab-list {
          display: none;
        }
        .tab-panel {
          display: none;
        }
        .related-grid {
          grid-template-columns: repeat(2, 1fr);
          gap: 14px;
        }
      }
    `;
  }
}