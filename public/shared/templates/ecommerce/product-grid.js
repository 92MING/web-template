/**
 * @fileoverview BuiltinTplEcommerceProductGrid - Product listing / category page template (Lit).
 *
 * Attributes:
 *   - title: Page heading
 *   - products: JSON array of product objects { id, name, title, price, oldPrice, image }
 *   - filters: JSON array of filter groups { label, options[] }
 *   - categories: JSON array of category objects { key, label, labelKey }
 *   - labels: JSON object for i18n overrides
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - footer: Page footer
 *
 * Events:
 *   - builtin-product-click: Product card clicked. Detail: { id, name, price }.
 *   - builtin-add-to-cart: Add-to-cart button clicked. Detail: { id }.
 *   - builtin-filter-change: Filter selection changed. Detail: { filter }.
 */

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

export class BuiltinTplEcommerceProductGrid extends BuiltinBaseElement {
  static get properties() {
    return {
      title: { type: String },
      products: { type: Array, converter: jsonConverter },
      filters: { type: Array, converter: jsonConverter },
      categories: { type: Array, converter: jsonConverter },
            labels: { type: Object, converter: jsonConverter },
      _filtersOpen: { type: Boolean, state: true },
      _activeNav: { type: String, state: true },
      _activeFilters: { type: Object, state: true },
      _sort: { type: String, state: true },
      _loading: { type: Boolean, state: true },
    };
  }

  constructor() {
    super();
    this.title = "Products";
    this.products = [];
    this.filters = [];
    this.categories = [];
    this.labels = {};
    this._filtersOpen = false;
    this._activeNav = "all";
    this._activeFilters = {};
    this._sort = "featured";
    this._loading = false;
    this._loadingTimer = null;
    this._hashHandler = () => this._syncHashCategory(true);
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("hashchange", this._hashHandler);
    this._syncHashCategory(false);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hashchange", this._hashHandler);
    if (this._loadingTimer) window.clearTimeout(this._loadingTimer);
  }

  _onToggleFilters() {
    this._filtersOpen = !this._filtersOpen;
  }

  _categoryFromHref(href) {
    const hash = String(href || "").replace(/^.*#/, "").toLowerCase();
    const cats = this._getCategories();
    if (cats.length) {
      const valid = cats.map((c) => String(c.key || c.id || "").toLowerCase());
      return valid.includes(hash) ? hash : "";
    }
    return ["all", "men", "women", "sale"].includes(hash) ? hash : "";
  }

  _syncHashCategory(showLoading) {
    const next = this._categoryFromHref(window.location.hash || "#all") || "all";
    if (next === this._activeNav) return;
    this._activeNav = next;
    if (showLoading) this._showLoading();
  }

  _onTemplateClick(e) {
    const path = e.composedPath ? e.composedPath() : [];
    const link = path.find((node) => node?.tagName === "A" && node.getAttribute("href"));
    if (!link) return;
    const category = this._categoryFromHref(link.getAttribute("href"));
    if (!category) return;
    e.preventDefault();
    if (window.location.hash !== `#${category}`) {
      window.history.pushState(null, "", `#${category}`);
    }
    this._activeNav = category;
    this._showLoading();
  }

  _showLoading() {
    if (this._loadingTimer) window.clearTimeout(this._loadingTimer);
    this._loading = true;
    this._loadingTimer = window.setTimeout(() => {
      this._loading = false;
      this._loadingTimer = null;
    }, 180);
  }

  _defaultProducts() {
    return Array.from({ length: 8 }, (_, i) => ({
      id: `demo-${i + 1}`,
      name: `${this._l("grid.product", "Product")} ${i + 1}`,
      price: `$${(29 + i * 15).toFixed(2)}`,
      image: "",
      badge: i % 4 === 0 ? "New" : i % 4 === 1 ? "Sale" : undefined,
    }));
  }

  _defaultFilters() {
    return [
      { key: "gender", labelKey: "grid.gender", options: [
        { value: "men", labelKey: "grid.men" },
        { value: "women", labelKey: "grid.women" },
        { value: "unisex", labelKey: "grid.unisex" },
      ] },
      { key: "category", labelKey: "grid.category", options: [
        { value: "Clothing", labelKey: "grid.clothing" },
        { value: "Shoes", labelKey: "grid.shoes" },
        { value: "Accessories", labelKey: "grid.accessories" },
      ] },
      { key: "price", labelKey: "grid.price", options: [
        { value: "under-50", labelKey: "grid.under50" },
        { value: "50-100", labelKey: "grid.50to100" },
        { value: "100-200", labelKey: "grid.100to200" },
        { value: "over-200", labelKey: "grid.over200" },
      ] },
    ];
  }

  _defaultCategories() {
    return [
      { key: "all", labelKey: "grid.all", label: "All" },
      { key: "men", labelKey: "grid.men", label: "Men" },
      { key: "women", labelKey: "grid.women", label: "Women" },
      { key: "sale", labelKey: "grid.sale", label: "Sale" },
    ];
  }

  _getProducts() {
    if (Array.isArray(this.products) && this.products.length) return this.products;
    return this._defaultProducts();
  }

  _getFilters() {
    if (Array.isArray(this.filters) && this.filters.length) return this.filters;
    return this._defaultFilters();
  }

  _getCategories() {
    if (Array.isArray(this.categories) && this.categories.length) return this.categories;
    return this._defaultCategories();
  }

  _filterKey(group) {
    return String(group.key || group.id || group.label || "");
  }

  _optionValue(option) {
    return typeof option === "object" ? String(option.value ?? option.label ?? "") : String(option);
  }

  _optionLabel(option) {
    if (typeof option === "object") {
      return option.labelKey
        ? this._l(option.labelKey, option.label ?? String(option.value ?? ""))
        : String(option.label ?? option.value ?? "");
    }
    return String(option);
  }

  _groupLabel(group) {
    return group.labelKey
      ? this._l(group.labelKey, group.label ?? String(group.key ?? ""))
      : String(group.label ?? group.key ?? "");
  }

  _navLabel(nav) {
    const cats = this._getCategories();
    const cat = cats.find((c) => String(c.key || c.id || "").toLowerCase() === String(nav || "").toLowerCase());
    if (cat) {
      return cat.labelKey
        ? this._l(cat.labelKey, cat.label || String(cat.key || ""))
        : String(cat.label || cat.key || "");
    }
    return this._l(`grid.${nav}`, nav.charAt(0).toUpperCase() + nav.slice(1));
  }

  _onFilterChange(group, option, checked) {
    const groupKey = this._filterKey(group);
    const value = this._optionValue(option);
    const next = { ...this._activeFilters };
    const values = new Set(next[groupKey] || []);
    if (checked) values.add(value);
    else values.delete(value);
    if (values.size) next[groupKey] = Array.from(values);
    else delete next[groupKey];
    this._activeFilters = next;
    this._showLoading();
    this.dispatchEvent(
      new CustomEvent("builtin-filter-change", {
        bubbles: true,
        composed: true,
        detail: { filter: next },
      })
    );
  }

  _onSortChange(e) {
    this._sort = e.target.value || "featured";
    this._showLoading();
  }

  _parsePrice(price) {
    return Number(String(price ?? "").replace(/[^0-9.]/g, "")) || 0;
  }

  _matchesNav(product) {
    if (this._activeNav === "all") return true;
    if (this._activeNav === "sale") return Boolean(product.onSale || product.oldPrice);
    const gender = String(product.gender || "").toLowerCase();
    if (gender === this._activeNav || gender === "unisex") return true;
    const productCategories = Array.isArray(product.categories)
      ? product.categories
      : [product.category].filter(Boolean);
    return productCategories.some((c) => String(c || "").toLowerCase() === this._activeNav);
  }

  _matchesPrice(product, selected) {
    if (!selected?.length) return true;
    const price = this._parsePrice(product.price);
    return selected.some((range) => {
      if (range === "under-50") return price < 50;
      if (range === "50-100") return price >= 50 && price <= 100;
      if (range === "100-200") return price > 100 && price <= 200;
      if (range === "over-200") return price > 200;
      return true;
    });
  }

  _matchesFilters(product) {
    return Object.entries(this._activeFilters || {}).every(([key, selected]) => {
      if (!selected?.length) return true;
      if (key === "price") return this._matchesPrice(product, selected);
      const value = String(product[key] ?? "").toLowerCase();
      return selected.map((item) => String(item).toLowerCase()).includes(value);
    });
  }

  _getVisibleProducts() {
    const products = this._getProducts().filter((product) => this._matchesNav(product) && this._matchesFilters(product));
    const sorted = products.slice();
    if (this._sort === "price-low-high") {
      sorted.sort((a, b) => this._parsePrice(a.price) - this._parsePrice(b.price));
    } else if (this._sort === "price-high-low") {
      sorted.sort((a, b) => this._parsePrice(b.price) - this._parsePrice(a.price));
    } else if (this._sort === "newest") {
      sorted.sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
    }
    return sorted;
  }

  _renderFilters() {
    const groups = this._getFilters();
    return html`
      ${repeat(
        groups,
        (g) => g.label,
        (g) => html`
          <div class="filter-group">
            <div class="filter-label">${this._groupLabel(g)}</div>
            <div class="filter-options">
              ${repeat(
                g.options || [],
                (opt) => this._optionValue(opt),
                (opt) => html`
                  <label class="filter-option">
                    <input
                      type="checkbox"
                      value="${this._optionValue(opt)}"
                      .checked=${Boolean((this._activeFilters[this._filterKey(g)] || []).includes(this._optionValue(opt)))}
                      @change=${(e) => this._onFilterChange(g, opt, e.target.checked)}
                    />
                    <span>${this._optionLabel(opt)}</span>
                  </label>
                `
              )}
            </div>
          </div>
        `
      )}
    `;
  }

  _renderSkeletonCards() {
    return html`
      ${repeat(Array.from({ length: 8 }), (_, i) => i, () => html`
        <div class="product-card skeleton-card" aria-hidden="true">
          <builtin-skeleton shape="card" height="180px"></builtin-skeleton>
          <div class="card-body">
            <builtin-skeleton lines="2"></builtin-skeleton>
          </div>
        </div>
      `)}
    `;
  }

  _renderCards(products) {
    return html`
      ${repeat(
        products,
        (p, i) => i,
        (p) => html`
          <div class="product-card" @click="${() => this.dispatchEvent(new CustomEvent('builtin-product-click', { bubbles: true, composed: true, detail: { id: p.id, name: p.name, price: p.price } }))}">
            <div class="card-img">
              ${p.image ? html`<img src="${p.image}" alt="" />` : ""}
            </div>
            <div class="card-body">
              <h3>${p.name ?? p.title ?? this._l("grid.product", "Product")}</h3>
              <div class="card-price-row">
                <span class="card-price">${p.price || "$0.00"}</span>
                ${p.oldPrice ? html`<span class="card-old">${p.oldPrice}</span>` : ""}
              </div>
              <button class="card-add-btn" @click="${(e) => { e.stopPropagation(); this.dispatchEvent(new CustomEvent('builtin-add-to-cart', { bubbles: true, composed: true, detail: { id: p.id } })); }}">
                ${this._l("grid.addToCart", "Add to Cart")}
              </button>
            </div>
          </div>
        `
      )}
    `;
  }

  render() {
    const products = this._getVisibleProducts();

    return html`
      <div class="page" @click=${this._onTemplateClick}>
        <slot name="navbar"><builtin-navbar></builtin-navbar></slot>
      </div>
      <div class="container">
        <div class="breadcrumb">
          <a href="#all">${this._l("grid.home", "Home")}</a> / <a href="#all">${this._l("grid.shop", "Shop")}</a> /
          <span>${this.title}</span>
        </div>
        <div class="page-header">
          <h1>${this.title}</h1>
          <div class="toolbar">
            <button class="mobile-filter-btn" @click=${this._onToggleFilters}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
              </svg>
              ${this._l("grid.filters", "Filters")}
            </button>
            <select aria-label=${this._l("grid.sort", "Sort")} .value=${this._sort} @change=${this._onSortChange}>
              <option value="featured">${this._l("grid.featured", "Featured")}</option>
              <option value="price-low-high">${this._l("grid.priceLowHigh", "Price: Low to High")}</option>
              <option value="price-high-low">${this._l("grid.priceHighLow", "Price: High to Low")}</option>
              <option value="newest">${this._l("grid.newest", "Newest")}</option>
            </select>
          </div>
        </div>
        <div class="layout">
          <aside class="sidebar ${classMap({ "mobile-open": this._filtersOpen })}" ?hidden=${this._ptMobile && !this._filtersOpen}>
            ${this._renderFilters()}
          </aside>
          <div class="main">
            <div class="result-row">
              <span>${this._l("grid.showing", `Showing ${products.length} results`)}</span>
              <span>${this._navLabel(this._activeNav)}</span>
            </div>
            <div class="product-grid">
              ${this._loading ? this._renderSkeletonCards() : products.length ? this._renderCards(products) : html`<div class="empty">${this._l("grid.empty", "No products found.")}</div>`}
            </div>
            <div class="pagination-wrap">
              <builtin-pagination></builtin-pagination>
            </div>
          </div>
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
      .page {
        display: block;
      }
      .container {
        max-width: 1140px;
        margin: 0 auto;
        padding: 0 20px;
      }
      .breadcrumb {
        padding: 16px 0;
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
      }
      .breadcrumb a {
        color: var(--builtin-color-muted, #6b7280);
        text-decoration: none;
      }
      .breadcrumb a:hover {
        color: var(--builtin-color-text, #111827);
      }
      .page-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 20px;
        flex-wrap: wrap;
      }
      .page-header h1 {
        font-size: 24px;
        font-weight: 700;
        margin: 0;
        color: var(--builtin-color-text);
      }
      .toolbar {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .toolbar select {
        min-height: 36px;
        padding: 0 8px;
        width: auto;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-surface);
        color: var(--builtin-color-text);
      }
      .layout {
        display: grid;
        grid-template-columns: 240px 1fr;
        gap: 28px;
      }
      .sidebar {
        display: flex;
        flex-direction: column;
        gap: 20px;
      }
      .result-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        color: var(--builtin-color-muted, #6b7280);
        font-size: 13px;
        margin-bottom: 12px;
      }
      .filter-group {
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        padding-bottom: 16px;
      }
      .filter-label {
        font-size: 13px;
        font-weight: 650;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        margin-bottom: 10px;
        color: var(--builtin-color-muted, #6b7280);
      }
      .filter-options {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .filter-option {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
        cursor: pointer;
        color: var(--builtin-color-text, #111827);
      }
      .filter-option input {
        width: auto;
        min-height: auto;
        margin: 0;
      }
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
        transition: background 0.15s ease;
        cursor: pointer;
      }
      .product-card.skeleton-card {
        cursor: default;
      }
      .product-card:hover {
        background: var(--builtin-row-hover-bg, #f9fafb);
      }
      .card-img {
        aspect-ratio: 1 / 1;
        background: var(--builtin-header-bg, #f9fafb);
        display: grid;
        place-items: center;
      }
      .card-img img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .card-body {
        padding: 14px;
      }
      .card-body h3 {
        font-size: 15px;
        margin: 0 0 8px;
        color: var(--builtin-color-text);
      }
      .card-price-row {
        display: flex;
        align-items: baseline;
        gap: 8px;
        flex-wrap: wrap;
      }
      .card-price {
        font-weight: 700;
        color: var(--builtin-primary, #2563eb);
      }
      .card-old {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
        text-decoration: line-through;
      }
      .card-add-btn {
        margin-top: 10px;
        width: 100%;
        padding: 8px 14px;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-button-bg, #ffffff);
        color: var(--builtin-color-text, #111827);
        font: inherit;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .card-add-btn:hover {
        background: var(--builtin-button-hover-bg, #f9fafb);
      }
      .pagination-wrap {
        padding: 24px 0;
        display: flex;
        justify-content: center;
      }
      .empty {
        grid-column: 1 / -1;
        min-height: 180px;
        display: grid;
        place-items: center;
        color: var(--builtin-color-muted, #6b7280);
        border: 1px dashed var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius-lg, 8px);
      }
      .mobile-filter-btn {
        display: none;
        padding: 8px 14px;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-button-bg, #ffffff);
        color: var(--builtin-color-text, #111827);
        font: inherit;
        cursor: pointer;
        align-items: center;
        gap: 6px;
      }
      .mobile-filter-btn:hover {
        background: var(--builtin-button-hover-bg, #f9fafb);
      }

      @media (max-width: 720px) {
        .container {
          padding: 0 16px;
        }
        .mobile-filter-btn {
          display: inline-flex;
        }
        .layout {
          grid-template-columns: 1fr;
          gap: 16px;
        }
        .sidebar {
          display: none;
        }
        .sidebar.mobile-open {
          display: flex;
        }
        .product-grid {
          grid-template-columns: repeat(2, 1fr);
          gap: 14px;
        }
        .page-header h1 {
          font-size: 20px;
        }
        .toolbar select {
          flex: 1 1 auto;
        }
      }
      @media (max-width: 400px) {
        .product-grid {
          grid-template-columns: 1fr;
        }
      }
    `;
  }
}