import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinPagination - Pagination controls with Prev/Next and numbered pages.
 *
 * Attributes:
 *   - page: Current page number (1-based)
 *   - total-pages: Total number of pages
 *   - total: Total item count (displayed as "X of Y" on mobile)
 *   - sibling-count: Number of sibling pages around current (default 1)
 *   - type: "numbered" | "simple" | "load-more"
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-page-change: Fired when the page changes. Detail: { page }
 */
export class BuiltinPagination extends BuiltinBaseElement {
  static properties = {
    page: { type: Number },
    totalPages: { type: Number, attribute: "total-pages" },
    total: { type: Number },
    siblingCount: { type: Number, attribute: "sibling-count" },
    type: { type: String },
    labels: { type: Object },
  };

  static styles = css`
    :host {
      display: block;
    }
    .pager {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    button {
      min-width: 34px;
      padding: 0 8px;
      min-height: 34px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      font: inherit;
    }
    button:hover {
      background: var(--builtin-button-hover-bg, #f9fafb);
    }
    button.active {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }
    button.ellipsis {
      cursor: default;
      border-color: transparent;
      background: transparent;
      min-width: auto;
      padding: 0 4px;
    }
    .info {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
      margin-left: 8px;
    }
    .mobile-info {
      display: none;
    }
    @media (max-width: 720px) {
      .desktop {
        display: none;
      }
      .mobile-info {
        display: inline;
      }
      .pager {
        justify-content: space-between;
      }
    }
  `;

  constructor() {
    super();
    this.page = 1;
    this.totalPages = 1;
    this.total = 0;
    this.siblingCount = 1;
    this.type = "numbered";
  }

  _l(key, values, fallback = "") {
    let realValues = values;
    let realFallback = fallback;
    if (typeof values === "string") {
      realValues = undefined;
      realFallback = values;
    }
    if (this.labels && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (realValues && typeof realValues === "object") {
        text = text.replace(
          /\{([a-zA-Z0-9_]+)\}/g,
          (match, name) =>
            Object.prototype.hasOwnProperty.call(realValues, name)
              ? String(realValues[name])
              : match
        );
      }
      return text;
    }
    const translated = this._t(key, realValues);
    return translated || realFallback;
  }

  _range() {
    const current = this.page;
    const total = this.totalPages;
    const sibling = this.siblingCount;
    const boundary = 1;

    const pages = [];
    const left = Math.max(current - sibling, boundary);
    const right = Math.min(current + sibling, total);

    if (left > boundary + 1) {
      pages.push(1);
      if (left > boundary + 2) pages.push("…");
      else pages.push(boundary + 1);
    } else {
      for (let i = boundary; i < left; i++) pages.push(i);
    }

    for (let i = left; i <= right; i++) pages.push(i);

    if (right < total - boundary) {
      if (right < total - boundary - 1) pages.push("…");
      else pages.push(total - 1);
      pages.push(total);
    } else {
      for (let i = right + 1; i <= total; i++) pages.push(i);
    }

    return pages;
  }

  _go(page) {
    if (page === this.page) return;
    if (page < 1 || page > this.totalPages) return;
    this.page = page;
    this.dispatchEvent(
      new CustomEvent("builtin-page-change", {
        bubbles: true,
        composed: true,
        detail: { page },
      })
    );
  }

  render() {
    const current = this.page;
    const total = this.totalPages;
    const hasTotal = this.total > 0;

    if (this.type === "load-more") {
      return html`
        <div class="pager">
          <button
            ?disabled="${current >= total}"
            @click="${() => this._go(current + 1)}"
          >
            ${this._l("pagination.loadMore", "Load more")}
          </button>
          ${hasTotal ? html`<span class="info">${this.total} total</span>` : ""}
        </div>
      `;
    }

    if (this.type === "simple") {
      return html`
        <div class="pager">
          <button ?disabled="${current <= 1}" @click="${() => this._go(current - 1)}">
            ${this._l("pagination.prev", "Prev")}
          </button>
          <span class="mobile-info">${current} / ${total}</span>
          <button ?disabled="${current >= total}" @click="${() => this._go(current + 1)}">
            ${this._l("pagination.next", "Next")}
          </button>
          ${hasTotal && !this._ptMobile
            ? html`<span class="info">${this.total} total</span>`
            : ""}
        </div>
      `;
    }

    const pages = this._range();
    return html`
      <div class="pager">
        <button ?disabled="${current <= 1}" @click="${() => this._go(current - 1)}">
          ${this._l("pagination.prev", "Prev")}
        </button>
        <span class="desktop">
          ${repeat(
            pages,
            (p) => String(p),
            (p) => {
              if (p === "…")
                return html`<button class="ellipsis" disabled>…</button>`;
              return html`<button
                class="${classMap({ active: p === current })}"
                @click="${() => this._go(p)}"
              >
                ${p}
              </button>`;
            }
          )}
        </span>
        <span class="mobile-info">${current} / ${total}</span>
        <button ?disabled="${current >= total}" @click="${() => this._go(current + 1)}">
          ${this._l("pagination.next", "Next")}
        </button>
        ${hasTotal ? html`<span class="info desktop">${this.total} total</span>` : ""}
      </div>
    `;
  }
}
