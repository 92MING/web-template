/**
 * @fileoverview BuiltinProductGrid — Taobao-style product grid with bottom recommendation bar.
 *
 * @attr {string} products — JSON array of {id, image, title, price, originalPrice, rating, sales, tags, href}.
 * @attr {number} columns — Grid columns (default 4).
 * @attr {string} mode — 'grid' | 'list' | 'compact'.
 * @attr {string} recommendations — JSON array same format for bottom bar.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-product-click — Detail: { id }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinProductGrid extends BuiltinBaseElement {
  static properties = {
    products: { type: Array },
    columns: { type: Number },
    mode: { type: String },
    recommendations: { type: Array },
    imageAspect: { type: String, attribute: "image-aspect" },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .grid {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(var(--pg-columns, 4), minmax(0, 1fr));
    }
    .list { display: flex; flex-direction: column; gap: 12px; }
    .compact.grid { gap: 10px; }
    .product {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      overflow: hidden;
      cursor: pointer;
      transition: box-shadow .15s ease, transform .15s ease;
    }
    .product:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); transform: translateY(-2px); }
    .list .product { display: flex; align-items: stretch; }
    .thumb {
      position: relative; overflow: hidden;
      background: var(--builtin-header-bg, #f9fafb);
    }
    .list .thumb { width: 140px; min-width: 140px; aspect-ratio: auto !important; }
    .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .info { padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
    .title { font-size: 14px; font-weight: 500; color: var(--builtin-color-text, #111827); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .price-row { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
    .price { font-size: 18px; font-weight: 700; color: var(--builtin-primary, #2563eb); }
    .original { font-size: 12px; color: var(--builtin-color-muted, #9ca3af); text-decoration: line-through; }
    .meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .stars { display: flex; gap: 1px; color: #f59e0b; }
    .tags { display: flex; flex-wrap: wrap; gap: 4px; }
    .tag { font-size: 11px; padding: 2px 6px; border-radius: 999px; background: var(--builtin-header-bg, #f3f4f6); color: var(--builtin-color-muted, #6b7280); }
    .rec-bar { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .rec-title { font-size: 14px; font-weight: 650; margin-bottom: 10px; color: var(--builtin-color-text, #111827); }
    .rec-scroll { display: flex; gap: 10px; overflow-x: auto; scrollbar-width: none; padding-bottom: 4px; }
    .rec-scroll::-webkit-scrollbar { display: none; }
    .rec-item { min-width: 120px; width: 120px; border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px); overflow: hidden; cursor: pointer; background: var(--builtin-surface, #ffffff); }
    .rec-item img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }
    .rec-item .t { font-size: 12px; padding: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--builtin-color-text, #111827); }
    .rec-item .p { font-size: 12px; padding: 0 6px 6px; font-weight: 700; color: var(--builtin-primary, #2563eb); }
    @media (max-width: 720px) {
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
      .list .thumb { width: 100px; min-width: 100px; }
    }
  `;

  constructor() {
    super();
    this.products = [];
    this.columns = 4;
    this.mode = "grid";
    this.recommendations = [];
    this.imageAspect = "1 / 1";
    this.labels = {};
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _renderStars(r) {
    const filled = Math.max(0, Math.min(5, Math.round(r || 0)));
    return Array.from({ length: 5 }, (_, i) => html`
      <span>${i < filled ? "★" : "☆"}</span>
    `);
  }

  _onClick(id) {
    this.dispatchEvent(new CustomEvent("builtin-product-click", { bubbles: true, composed: true, detail: { id } }));
  }

  render() {
    const products = this.products || [];
    const recs = this.recommendations || [];
    const mode = this.mode || "grid";
    const columns = Math.max(1, Math.min(6, Number(this.columns) || 4));
    const isList = mode === "list";
    const gridStyle = isList ? {} : { "--pg-columns": String(columns) };

    return html`
      <div class="${mode} ${isList ? "list" : "grid"}" style="${styleMap(gridStyle)}">
        ${repeat(
          products,
          (p) => p.id,
          (p) => html`
            <div class="product" @click="${() => this._onClick(p.id)}">
              <div class="thumb">
                ${p.image ? html`<img src="${p.image}" alt="${p.title || ""}" loading="lazy" />` : ""}
              </div>
              <div class="info">
                <div class="title">${p.title || ""}</div>
                <div class="price-row">
                  <span class="price">${p.price || ""}</span>
                  ${p.originalPrice ? html`<span class="original">${p.originalPrice}</span>` : ""}
                </div>
                <div class="meta">
                  ${p.rating ? html`<span class="stars">${this._renderStars(p.rating)}</span>` : ""}
                  ${p.sales ? html`<span>${p.sales} sold</span>` : ""}
                </div>
                ${p.tags?.length ? html`
                  <div class="tags">${p.tags.map((t) => html`<span class="tag">${t}</span>`)}</div>
                ` : ""}
              </div>
            </div>
          `
        )}
      </div>
      ${recs.length ? html`
        <div class="rec-bar">
          <div class="rec-title">${this._l("product.recommendations", "Recommended for you")}</div>
          <div class="rec-scroll">
            ${recs.map((r) => html`
              <div class="rec-item" @click="${() => this._onClick(r.id)}">
                ${r.image ? html`<img src="${r.image}" alt="" loading="lazy" />` : ""}
                <div class="t">${r.title || ""}</div>
                <div class="p">${r.price || ""}</div>
              </div>
            `)}
          </div>
        </div>
      ` : ""}
    `;
  }
}
