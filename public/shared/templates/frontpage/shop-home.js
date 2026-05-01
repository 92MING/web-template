import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

/**
 * @fileoverview E-commerce homepage template.
 *
 * @description Product-focused layout with a promo banner, category icons,
 * featured products grid, and promotional sections.
 *
 * Attributes:
 *   - promo-text: Discount/promo headline
 *   - categories: JSON array of category objects
 *   - products: JSON array of product objects
 *   - labels: JSON object to override i18n strings
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - promo: Custom promotional banner content
 *   - footer: Page footer
 */
export class BuiltinTplFrontpageShop extends BuiltinBaseElement {
  static properties = {
    promoText: { type: String },
    categories: { type: Array, converter: jsonConverter },
    products: { type: Array, converter: jsonConverter },
        labels: { type: Object, converter: jsonConverter },
  };

  static styles = css`
    :host { display: block; line-height: 1.55; }
    h1, h2, h3, p { margin: 0; }
    a { color: var(--builtin-primary, #2563eb); text-decoration: none; }
    .container { max-width: 1140px; margin: 0 auto; padding: 0 20px; }
    .promo {
      padding: 48px 0;
      text-align: center;
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .promo h1 { font-size: clamp(24px, 4vw, 40px); font-weight: 800; margin-bottom: 16px; color: var(--builtin-color-text, #111827); }
    .promo p { color: var(--builtin-color-muted, #6b7280); margin-bottom: 20px; }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 22px;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      font-weight: 600;
      cursor: pointer;
      font: inherit;
    }
    .btn:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .btn-primary {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .btn-primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .categories { padding: 28px 0; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .cat-scroll {
      display: flex;
      gap: 16px;
      overflow-x: auto;
      scroll-snap-type: x mandatory;
      padding-bottom: 8px;
    }
    .cat-item {
      flex: 0 0 auto;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      min-width: 80px;
      scroll-snap-align: start;
    }
    .cat-icon {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: var(--builtin-header-bg, #f9fafb);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      display: grid;
      place-items: center;
      transition: background .15s ease;
      color: var(--builtin-color-text, #111827);
    }
    .cat-icon svg { width: 24px; height: 24px; }
    .cat-item:hover .cat-icon { background: var(--builtin-row-hover-bg, #f9fafb); }
    .cat-item span { font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .products { padding: 40px 0; }
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
    }
    .section-header h2 { font-size: 22px; font-weight: 700; color: var(--builtin-color-text, #111827); }
    .product-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 20px;
    }
    .product-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      background: var(--builtin-surface, #ffffff);
      transition: background .15s ease;
      cursor: pointer;
    }
    .product-card:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .product-card .img { min-height: 160px; background: var(--builtin-header-bg, #f9fafb); }
    .product-card .info { padding: 14px; }
    .product-card h3 { font-size: 15px; margin-bottom: 6px; color: var(--builtin-color-text, #111827); }
    .product-card .price { font-weight: 700; color: var(--builtin-primary, #2563eb); }
    .promo-section {
      padding: 48px 0;
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .promo-block {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 32px;
      align-items: center;
    }
    .promo-block .img {
      min-height: 240px;
      background: var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
    }
    .promo-block h3 { font-size: 24px; margin-bottom: 10px; color: var(--builtin-color-text, #111827); }
    .promo-block p { color: var(--builtin-color-muted, #6b7280); margin-bottom: 16px; }
    .page-footer {
      padding: 24px 0;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }

    @media (max-width: 720px) {
      .container { padding: 0 16px; }
      .promo { padding: 36px 0; }
      .cat-scroll { gap: 12px; }
      .product-grid { grid-template-columns: repeat(2, 1fr); gap: 14px; }
      .promo-block { grid-template-columns: 1fr; }
      .promo-block .img { min-height: 180px; }
      .btn { width: 100%; min-height: 44px; }
    }
    @media (max-width: 400px) {
      .product-grid { grid-template-columns: 1fr; }
    }
  `;

  _defaultCategories() {
    return [
      { key: "clothing", label: "Clothing", iconName: "skin" },
      { key: "electronics", label: "Electronics", iconName: "desktop" },
      { key: "home", label: "Home", iconName: "home" },
      { key: "gaming", label: "Gaming", iconName: "play-circle" },
      { key: "books", label: "Books", iconName: "book" },
      { key: "sports", label: "Sports", iconName: "trophy" },
    ];
  }

  _defaultProducts() {
    return [
      { name: "Product A", price: "$29.00" },
      { name: "Product B", price: "$49.00" },
      { name: "Product C", price: "$19.00" },
      { name: "Product D", price: "$89.00" },
      { name: "Product E", price: "$35.00" },
      { name: "Product F", price: "$59.00" },
      { name: "Product G", price: "$15.00" },
      { name: "Product H", price: "$99.00" },
    ];
  }

  render() {
    const promoText = this.promoText || this._l("promo.headline", "Summer Sale \u2014 Up to 50% Off");
    const categories = this.categories?.length ? this.categories : (this._defaultCategories());
    const products = this.products?.length ? this.products : (this._defaultProducts());

    return html`
      <slot name="navbar"><builtin-navbar></builtin-navbar></slot>

      <section class="promo">
        <div class="container">
          <slot name="promo">
            <h1>${promoText}</h1>
            <p>${this._l("promo.desc", "Limited time offers on top-rated products.")}</p>
            <button class="btn btn-primary" @click="${() => this.dispatchEvent(new CustomEvent('builtin-cta-click', { bubbles: true, composed: true, detail: { action: 'shop' } }))}">${this._l("promo.cta", "Shop Now")}</button>
          </slot>
        </div>
      </section>

      ${categories.length ? html`
        <section class="categories">
          <div class="container">
            <div class="cat-scroll">
              ${repeat(categories, (c) => c.key, (c) => html`
                <div class="cat-item">
                  <div class="cat-icon"><builtin-icon name="${c.iconName}" size="24" variant="outlined"></builtin-icon></div>
                  <span>${c.label}</span>
                </div>
              `)}
            </div>
          </div>
        </section>
      ` : nothing}

      ${products.length ? html`
        <section class="products">
          <div class="container">
            <div class="section-header">
              <h2>${this._l("products.title", "Featured Products")}</h2>
              <a href="#">${this._l("products.viewAll", "View all \u2192")}</a>
            </div>
            <div class="product-grid">
              ${repeat(products, (p, i) => i, (p, i) => html`
                <div class="product-card" @click="${() => this.dispatchEvent(new CustomEvent('builtin-product-click', { bubbles: true, composed: true, detail: { name: p.name, price: p.price } }))}" tabindex="0" role="button">
                  <div class="img"></div>
                  <div class="info">
                    <h3>${p.name}</h3>
                    <div class="price">${p.price}</div>
                  </div>
                </div>
              `)}
            </div>
          </div>
        </section>
      ` : nothing}

      <section class="promo-section">
        <div class="container">
          <div class="promo-block">
            <div class="img"></div>
            <div>
              <h3>${this._l("promoSection.title", "New Collection")}</h3>
              <p>${this._l("promoSection.desc", "Discover curated styles hand-picked for the season. Free shipping on orders over $50.")}</p>
              <button class="btn btn-primary" @click="${() => this.dispatchEvent(new CustomEvent('builtin-cta-click', { bubbles: true, composed: true, detail: { action: 'explore' } }))}">${this._l("promoSection.cta", "Explore")}</button>
            </div>
          </div>
        </div>
      </section>

      <slot name="footer"><builtin-footer></builtin-footer></slot>
    `;
  }
}