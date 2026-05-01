import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

/**
 * @fileoverview BuiltinCommandPalette — Keyboard-driven command palette with search and navigation.
 *
 * Attributes:
 *   - items: JSON array of { id, label, shortcut, icon, category }
 *   - open: boolean
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-select: Fired when an item is selected. Detail: { id }
 */
export class BuiltinCommandPalette extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
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
    .palette {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 20px 60px rgba(0,0,0,0.18);
      width: 100%; max-width: 640px; max-height: 60vh;
      display: flex; flex-direction: column;
      overflow: hidden;
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
    .list { overflow-y: auto; flex: 1 1 auto; }
    .category {
      padding: 8px 14px 4px;
      font-size: 12px; font-weight: 600; text-transform: uppercase;
      color: var(--builtin-color-muted, #6b7280);
      letter-spacing: 0.05em;
    }
    .item {
      display: flex; align-items: center; gap: 10px;
      padding: 8px 14px; cursor: pointer;
      color: var(--builtin-color-text, #111827);
    }
    .item:hover, .item.active {
      background: var(--builtin-row-hover-bg, #f3f4f6);
    }
    .item-icon {
      width: 20px; height: 20px;
      display: inline-flex; align-items: center; justify-content: center;
      color: var(--builtin-color-muted, #6b7280);
    }
    .item-label { flex: 1; }
    .item-shortcut {
      font-size: 12px; color: var(--builtin-color-muted, #6b7280);
      background: var(--builtin-header-bg, #f9fafb);
      padding: 2px 6px; border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .empty {
      padding: 24px 14px; text-align: center;
      color: var(--builtin-color-muted, #6b7280);
    }
    @media (max-width: 720px) {
      .overlay { padding: 0; align-items: stretch; justify-content: stretch; }
      .palette { max-width: none; max-height: 100vh; border-radius: 0; border: none; }
    }
  `;

  constructor() {
    super();
    this.items = [];
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
        const len = this._filteredItems().length;
        this._activeIndex = (this._activeIndex + 1) % (len || 1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const len = this._filteredItems().length;
        this._activeIndex = (this._activeIndex - 1 + (len || 1)) % (len || 1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const filtered = this._filteredItems();
        if (filtered[this._activeIndex]) {
          this._select(filtered[this._activeIndex].id);
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

  _filteredItems() {
    const q = (this._query || "").toLowerCase().trim();
    if (!q) return this.items || [];
    return (this.items || []).filter(
      (it) =>
        (it.label || "").toLowerCase().includes(q) ||
        (it.category || "").toLowerCase().includes(q)
    );
  }

  _groupedItems() {
    const map = new Map();
    for (const it of this._filteredItems()) {
      const cat = it.category || this._l("commandPalette.general", "General");
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat).push(it);
    }
    return Array.from(map.entries());
  }

  _select(id) {
    this.open = false;
    this.dispatchEvent(
      new CustomEvent("builtin-select", {
        bubbles: true,
        composed: true,
        detail: { id },
      })
    );
  }

  _onInput(e) {
    this._query = e.target.value;
    this._activeIndex = 0;
  }

  _globalIndex(catIndex, itemIndex) {
    let idx = 0;
    const groups = this._groupedItems();
    for (let i = 0; i < catIndex; i++) idx += groups[i][1].length;
    return idx + itemIndex;
  }

  render() {
    const groups = this._groupedItems();
    const hasItems = groups.some((g) => g[1].length);

    return html`
      <div class="overlay ${classMap({ open: this.open })}" @click="${(e) => {
        if (e.target === e.currentTarget) this.open = false;
      }}">
        <div class="palette" role="dialog" aria-modal="true">
          <div class="search">
            <builtin-icon name="search" size="20" variant="outlined"></builtin-icon>
            <input
              type="text"
              .value="${this._query}"
              placeholder="${this._l("commandPalette.search", "Search commands...")}"
              @input="${this._onInput}"
            />
          </div>
          <div class="list">
            ${!hasItems
              ? html`<div class="empty">${this._l("commandPalette.noResults", "No results found.")}</div>`
              : repeat(
                  groups,
                  (g) => g[0],
                  (g, catIndex) => html`
                    <div class="category">${g[0]}</div>
                    ${repeat(
                      g[1],
                      (it) => it.id,
                      (it, itemIndex) => {
                        const globalIdx = this._globalIndex(catIndex, itemIndex);
                        return html`
                          <div
                            class="item ${classMap({ active: globalIdx === this._activeIndex })}"
                            @click="${() => this._select(it.id)}"
                            @mouseenter="${() => { this._activeIndex = globalIdx; }}"
                          >
                            ${it.icon
                              ? html`<span class="item-icon">${unsafeHTML(it.icon)}</span>`
                              : html`<span class="item-icon">
                                  <builtin-icon name="info" size="16" variant="outlined"></builtin-icon>
                                </span>`}
                            <span class="item-label">${it.label}</span>
                            ${it.shortcut ? html`<span class="item-shortcut">${it.shortcut}</span>` : ""}
                          </div>
                        `;
                      }
                    )}
                  `
                )}
          </div>
        </div>
      </div>
    `;
  }
}
