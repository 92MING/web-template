/**
 * @fileoverview BuiltinTplVideoListing - Video browse / discover page template (Lit).
 *
 * Attributes:
 *   - categories: JSON array of category strings/objects { id, label }
 *   - items: JSON array of video objects { title, channel, views, ago, duration, src }
 *   - sort: Current sort value
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-category-change: Category chip clicked. Detail: { category }.
 *   - builtin-sort-change: Sort changed. Detail: { sort }.
 *   - builtin-video-click: Video card clicked. Detail: { title, channel }.
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - footer: Page footer
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const DEFAULT_VIDEO_SRC = "/test-media/sample-video.mp4";

export class BuiltinTplVideoListing extends BuiltinBaseElement {
  static get properties() {
    return {
            categories: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "[]"); } catch { return []; }
          },
        },
      },
      sort: { type: String },
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
    this.categories = [];
    this.sort = "popular";
    this.items = [];
    this.labels = {};
    this._activeCategory = "all";
  }

  _onChipClick(e) {
    const chip = e.currentTarget;
    this._activeCategory = chip.dataset.category;
    this.dispatchEvent(
      new CustomEvent("builtin-category-change", {
        bubbles: true,
        composed: true,
        detail: { category: this._activeCategory },
      })
    );
  }

  _onSortChange(e) {
    this.sort = e.target.value;
    this.dispatchEvent(
      new CustomEvent("builtin-sort-change", {
        bubbles: true,
        composed: true,
        detail: { sort: this.sort },
      })
    );
  }

  _renderChips() {
    const chips = [
      { id: "all", label: this._l("listing.all", "All") },
      ...this.categories.map((c) =>
        typeof c === "string" ? { id: c, label: c } : c
      ),
    ];
    return html`
      ${repeat(
        chips,
        (c) => c.id,
        (c) => html`
          <button
            type="button"
            class="chip ${this._activeCategory === c.id ? "active" : ""}"
            data-category="${c.id}"
            @click=${this._onChipClick}
          >
            ${c.label}
          </button>
        `
      )}
    `;
  }

  _defaultItems() {
    return [
      { title: "Flower close-up sample", channel: "MDN Samples", views: "10K", ago: "2 days ago", duration: "0:05", src: DEFAULT_VIDEO_SRC },
      { title: "Loop-ready video clip", channel: "Open Source", views: "5K", ago: "1 week ago", duration: "0:05", src: DEFAULT_VIDEO_SRC },
      { title: "Short video clip", channel: "Channel C", views: "1M", ago: "3 weeks ago", duration: "0:05", src: DEFAULT_VIDEO_SRC },
      { title: "Tutorial media fixture", channel: "Channel D", views: "120K", ago: "1 month ago", duration: "0:05", src: DEFAULT_VIDEO_SRC },
      { title: "Template playback test", channel: "Channel E", views: "8K", ago: "2 months ago", duration: "0:05", src: DEFAULT_VIDEO_SRC },
      { title: "Reusable sample asset", channel: "Channel F", views: "45K", ago: "3 days ago", duration: "0:05", src: DEFAULT_VIDEO_SRC },
    ];
  }

  _defaultCategories() {
    return ["Music", "Gaming", "Education", "Technology", "Sports"];
  }

  _getItems() {
    if (Array.isArray(this.items) && this.items.length) return this.items;
    return this._defaultItems();
  }

  _renderCard(item) {
    const src = item.src || DEFAULT_VIDEO_SRC;
    return html`
      <div class="video-card" @click="${() => this.dispatchEvent(new CustomEvent('builtin-video-click', { bubbles: true, composed: true, detail: { title: item.title, channel: item.channel } }))}">
        <div class="card-thumb">
          <div class="card-thumb-inner">
            <video src="${src}" muted playsinline preload="metadata"></video>
            <span class="card-thumb-duration">${item.duration || "0:05"}</span>
          </div>
        </div>
        <p class="card-title">${item.title || "Sample video"}</p>
        <span class="card-meta">${item.channel || "Demo"} · ${item.views || "0"} views · ${item.ago || ""}</span>
      </div>
    `;
  }

  render() {
    return html`
      <div class="page">
        <div class="navbar-slot">
          <slot name="navbar"></slot>
        </div>
        <div class="content">
          <div class="toolbar">
            <div class="chips-row">${this._renderChips()}</div>
            <select class="sort-select" aria-label="Sort" .value=${this.sort} @change=${this._onSortChange}>
              <option value="popular">${this._l("listing.popular", "Popular")}</option>
              <option value="newest">${this._l("listing.newest", "Newest")}</option>
              <option value="oldest">${this._l("listing.oldest", "Oldest")}</option>
            </select>
          </div>
          <div class="video-grid">
            ${this._getItems().map((item) => this._renderCard(item))}
          </div>
          <div class="pagination">
            <button class="page-btn">${this._l("listing.prev", "Previous")}</button>
            <button class="page-btn active">1</button>
            <button class="page-btn">2</button>
            <button class="page-btn">3</button>
            <button class="page-btn">${this._l("listing.next", "Next")}</button>
          </div>
          <div class="infinite-placeholder">${this._l("listing.scrollLoadMore", "Scroll to load more")}</div>
        </div>
        <div class="footer-slot">
          <slot name="footer"></slot>
        </div>
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .page {
        display: flex;
        flex-direction: column;
        min-height: 100vh;
      }
      .navbar-slot {
        position: sticky;
        top: 0;
        z-index: 10;
      }
      .content {
        padding: 16px;
        max-width: 1280px;
        margin: 0 auto;
        width: 100%;
        box-sizing: border-box;
      }
      .toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 16px;
      }
      .chips-row {
        display: flex;
        gap: 8px;
        overflow-x: auto;
        flex-wrap: nowrap;
        padding-bottom: 4px;
        scrollbar-width: none;
      }
      .chips-row::-webkit-scrollbar {
        display: none;
      }
      .chip {
        padding: 6px 14px;
        border: 1px solid var(--builtin-border);
        border-radius: 999px;
        background: var(--builtin-surface);
        color: var(--builtin-color-text);
        font-size: 13px;
        cursor: pointer;
        white-space: nowrap;
        flex-shrink: 0;
      }
      .chip:hover {
        background: var(--builtin-row-hover-bg);
      }
      .chip.active {
        background: var(--builtin-primary);
        color: #fff;
        border-color: transparent;
      }
      .sort-select {
        padding: 6px 10px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-surface);
        color: var(--builtin-color-text);
        font-size: 13px;
        cursor: pointer;
        flex-shrink: 0;
      }
      .sort-select:focus {
        outline: 2px solid var(--builtin-primary);
      }
      .video-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
        gap: 16px;
      }
      .video-card {
        display: flex;
        flex-direction: column;
        gap: 8px;
        cursor: pointer;
      }
      .card-thumb {
        width: 100%;
        padding-top: 56.25%;
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-border);
        position: relative;
        overflow: hidden;
      }
      .card-thumb-inner {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .card-thumb video {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
      }
      .card-thumb-duration {
        position: absolute;
        right: 6px;
        bottom: 6px;
        padding: 2px 6px;
        border-radius: 4px;
        background: rgba(0, 0, 0, 0.65);
        color: #fff;
        font-size: 11px;
        font-weight: 600;
      }
      .card-title {
        font-size: 14px;
        font-weight: 500;
        line-height: 1.3;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        margin: 0;
        color: var(--builtin-color-text);
      }
      .card-meta {
        font-size: 12px;
        color: var(--builtin-color-muted);
      }
      .pagination {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 8px;
        margin-top: 24px;
        padding: 12px 0;
      }
      .page-btn {
        padding: 6px 12px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-surface);
        color: var(--builtin-color-text);
        font-size: 13px;
        cursor: pointer;
      }
      .page-btn:hover {
        background: var(--builtin-row-hover-bg);
      }
      .page-btn.active {
        background: var(--builtin-primary);
        color: #fff;
        border-color: transparent;
      }
      .infinite-placeholder {
        text-align: center;
        padding: 20px;
        color: var(--builtin-color-muted);
        font-size: 13px;
        margin-top: 16px;
      }
      .footer-slot {
        margin-top: auto;
      }
      @media (max-width: 720px) {
        .content {
          padding: 12px;
        }
        .toolbar {
          flex-direction: column;
          align-items: stretch;
        }
        .chips-row {
          width: 100%;
        }
        .video-grid {
          grid-template-columns: repeat(2, 1fr);
        }
      }
      @media (max-width: 420px) {
        .video-grid {
          grid-template-columns: 1fr;
        }
      }
    `;
  }
}