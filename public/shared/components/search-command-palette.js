import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

/**
 * @fileoverview BuiltinSearchCommandPalette — Combined search input + command palette.
 *
 * Attributes:
 *   - searchPlaceholder: string
 *   - recent: JSON array of recent items [{ id, label, icon }]
 *   - suggestions: JSON array of suggestion items [{ id, label, icon, category }]
 *   - open: boolean
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-search: Fired when query changes. Detail: { value }
 *   - builtin-select: Fired when an item is selected. Detail: { id }
 */
export class BuiltinSearchCommandPalette extends BuiltinBaseElement {
  static properties = {
    searchPlaceholder: { type: String },
    recent: { type: Array },
    suggestions: { type: Array },
    open: { type: Boolean },
    labels: { type: Object },
    _query: { type: String, state: true },
    _activeIndex: { type: Number, state: true },
  };

  static styles = css`
    :host { display: block; }
    .overlay {
      position: fixed; inset: 0; z-index: 9999;
      background: rgba(0,0,0,0.45);
      display: none; align-items: flex-start; justify-content: center;
      padding: 80px 16px 16px;
    }
    .overlay.open { display: flex; }
    .box {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 20px 60px rgba(0,0,0,0.18);
      width: 100%; max-width: 640px; max-height: 60vh;
      display: flex; flex-direction: column; overflow: hidden;
    }
    .search {
      display: flex; align-items: center; gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .search svg { color: var(--builtin-color-muted, #6b7280); flex-shrink: 0; }
    .search input {
      flex: 1; border: none; background: transparent; outline: none;
      color: var(--builtin-color-text, #111827); font: inherit;
    }
    .section-title {
      padding: 8px 14px 4px;
      font-size: 12px; font-weight: 600; text-transform: uppercase;
      color: var(--builtin-color-muted, #6b7280); letter-spacing: 0.05em;
    }
    .list { overflow-y: auto; flex: 1 1 auto; }
    .item {
      display: flex; align-items: center; gap: 10px;
      padding: 8px 14px; cursor: pointer;
      color: var(--builtin-color-text, #111827);
    }
    .item:hover, .item.active { background: var(--builtin-row-hover-bg, #f3f4f6); }
    .item-icon {
      width: 20px; height: 20px;
      display: inline-flex; align-items: center; justify-content: center;
      color: var(--builtin-color-muted, #6b7280);
    }
    .item-label { flex: 1; }
    .empty {
      padding: 24px 14px; text-align: center;
      color: var(--builtin-color-muted, #6b7280);
    }
    @media (max-width: 720px) {
      .overlay { padding: 0; align-items: stretch; justify-content: stretch; }
      .box { max-width: none; max-height: 100vh; border-radius: 0; border: none; }
    }
  `;

  constructor() {
    super();
    this.searchPlaceholder = "";
    this.recent = [];
    this.suggestions = [];
    this.open = false;
    this.labels = {};
    this._query = "";
    this._activeIndex = 0;
    this._keydownHandler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        this.open = !this.open;
        if (this.open) {
          this._query = "";
          this._activeIndex = 0;
          this.updateComplete.then(() => this._focusInput());
        }
      }
      if (!this.open) return;
      if (e.key === "Escape") {
        this.open = false;
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        const len = this._visibleItems().length;
        this._activeIndex = (this._activeIndex + 1) % (len || 1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const len = this._visibleItems().length;
        this._activeIndex = (this._activeIndex - 1 + (len || 1)) % (len || 1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const items = this._visibleItems();
        if (items[this._activeIndex]) {
          this._select(items[this._activeIndex].id);
        }
      }
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("keydown", this._keydownHandler);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._keydownHandler);
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _focusInput() {
    const input = this.shadowRoot?.querySelector("input");
    if (input) input.focus();
  }

  _visibleItems() {
    const q = (this._query || "").toLowerCase().trim();
    const recent = (this.recent || []).map((it) => ({ ...it, _section: "recent" }));
    const suggestions = (this.suggestions || []).map((it) => ({ ...it, _section: "suggestions" }));
    const all = [...recent, ...suggestions];
    if (!q) return all;
    return all.filter(
      (it) =>
        (it.label || "").toLowerCase().includes(q) ||
        (it.category || "").toLowerCase().includes(q)
    );
  }

  _select(id) {
    this.open = false;
    this.dispatchEvent(
      new CustomEvent("builtin-select", { bubbles: true, composed: true, detail: { id } })
    );
  }

  _onInput(e) {
    const value = e.target.value;
    this._query = value;
    this._activeIndex = 0;
    this.dispatchEvent(
      new CustomEvent("builtin-search", { bubbles: true, composed: true, detail: { value } })
    );
  }

  render() {
    const items = this._visibleItems();
    const recentItems = items.filter((it) => it._section === "recent");
    const suggestionItems = items.filter((it) => it._section === "suggestions");

    return html`
      <div class="overlay ${classMap({ open: this.open })}" @click="${(e) => {
        if (e.target === e.currentTarget) this.open = false;
      }}">
        <div class="box" role="dialog" aria-modal="true">
          <div class="search">
            <builtin-icon name="search" size="20" variant="outlined"></builtin-icon>
            <input
              type="text"
              .value="${this._query}"
              placeholder="${this.searchPlaceholder || this._l("searchCommandPalette.placeholder", "Search...")}"
              @input="${this._onInput}"
            />
          </div>
          <div class="list">
            ${items.length === 0
              ? html`<div class="empty">${this._l("searchCommandPalette.noResults", "No results found.")}</div>`
              : html`
                  ${recentItems.length
                    ? html`
                        <div class="section-title">${this._l("searchCommandPalette.recent", "Recent")}</div>
                        ${repeat(
                          recentItems,
                          (it) => `recent-${it.id}`,
                          (it, idx) => this._renderItem(it, idx)
                        )}
                      `
                    : ""}
                  ${suggestionItems.length
                    ? html`
                        <div class="section-title">${this._l("searchCommandPalette.suggestions", "Suggestions")}</div>
                        ${repeat(
                          suggestionItems,
                          (it) => `sugg-${it.id}`,
                          (it, idx) => this._renderItem(it, recentItems.length + idx)
                        )}
                      `
                    : ""}
                `}
          </div>
        </div>
      </div>
    `;
  }

  _renderItem(it, idx) {
    return html`
      <div
        class="item ${classMap({ active: idx === this._activeIndex })}"
        @click="${() => this._select(it.id)}"
        @mouseenter="${() => { this._activeIndex = idx; }}"
      >
        ${it.icon
          ? html`<span class="item-icon">${unsafeHTML(it.icon)}</span>`
          : html`<span class="item-icon">
              <builtin-icon name="info" size="16" variant="outlined"></builtin-icon>
            </span>`}
        <span class="item-label">${it.label}</span>
      </div>
    `;
  }
}
