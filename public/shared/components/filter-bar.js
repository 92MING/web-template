/**
 * @fileoverview BuiltinFilterBar — Filter pills / dropdown bar web component.
 *
 * @attr {string} mode — `chips` | `row` | `drawer`.
 * @attr {string} filters — JSON array of {key, label, options[], multi}.
 * @attr {string} active — JSON object of selected values.
 *
 * @event builtin-filter-change — Detail: `{ key, values }`
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

export class BuiltinFilterBar extends BuiltinBaseElement {
  static properties = {
    mode: { type: String },
    filters: { type: Array },
    active: { type: Object },
    labels: { type: Object },
    _openKey: { type: String, state: true },
    _drawerOpen: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .bar {
      display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    }
    .filter-wrap { position: relative; }
    .filter-btn {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 0 12px; min-height: 34px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer; font-size: 13px;
    }
    .filter-btn:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .filter-btn.active { border-color: var(--builtin-primary, #2563eb); color: var(--builtin-primary, #2563eb); }
    .dropdown {
      position: absolute; top: calc(100% + 6px); left: 0; z-index: 10;
      min-width: 180px; max-width: 260px;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 6px 18px rgba(0,0,0,.10);
      padding: 6px; display: none;
    }
    .filter-wrap.open .dropdown { display: block; }
    .option {
      display: flex; align-items: center; gap: 8px;
      padding: 7px 8px; border-radius: var(--builtin-radius, 6px);
      cursor: pointer; font-size: 13px; color: var(--builtin-color-text, #111827);
    }
    .option:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .option input { width: auto; min-height: auto; margin: 0; }
    .option-label { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dropdown-actions {
      display: flex; justify-content: flex-end;
      padding: 6px 4px 2px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); margin-top: 4px;
    }
    .dropdown-actions button { font-size: 12px; padding: 0 8px; min-height: 26px; }
    .count {
      display: inline-flex; align-items: center; justify-content: center;
      width: 18px; height: 18px; border-radius: 50%;
      background: var(--builtin-primary, #2563eb); color: #fff; font-size: 10px; font-weight: 700;
    }
    .chips-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .chip {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 10px; border-radius: 999px;
      background: var(--builtin-row-hover-bg, #f3f4f6);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      font-size: 13px; color: var(--builtin-color-text, #111827);
    }
    .chip button {
      border: 0; background: transparent; padding: 0; min-height: auto;
      font-size: 14px; color: var(--builtin-color-muted, #6b7280); cursor: pointer;
    }
    .drawer-overlay {
      position: fixed; inset: 0; z-index: 9998; background: rgba(0,0,0,0.35);
      display: none;
    }
    .drawer-overlay.open { display: block; }
    .drawer {
      position: fixed; left: 0; right: 0; bottom: 0; z-index: 9999;
      background: var(--builtin-surface, #ffffff);
      border-top: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px) var(--builtin-radius-lg, 8px) 0 0;
      padding: 16px; max-height: 60vh; overflow: auto;
      transform: translateY(100%); transition: transform 0.2s ease;
    }
    .drawer.open { transform: translateY(0); }
    .drawer-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .drawer-header h4 { margin: 0; font-size: 16px; }
    .drawer-close { border: 0; background: transparent; padding: 4px; cursor: pointer; }
    .drawer-section { margin-bottom: 12px; }
    .drawer-section-title { font-weight: 650; font-size: 13px; margin-bottom: 6px; color: var(--builtin-color-muted, #6b7280); }
    @media (max-width: 720px) {
      .bar { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px; }
      .filter-btn { white-space: nowrap; }
      .dropdown { left: 0; right: auto; max-width: 220px; }
    }
  `;

  constructor() {
    super();
    this.mode = "row";
    this.filters = [];
    this.active = {};
  }

  connectedCallback() {
    super.connectedCallback();
    this._onDocClick = (e) => {
      if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
        this._openKey = null;
      }
    };
    document.addEventListener("click", this._onDocClick);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._onDocClick) document.removeEventListener("click", this._onDocClick);
  }

  _getActiveValues(key) {
    const vals = this.active?.[key];
    if (Array.isArray(vals)) return vals;
    if (vals === undefined || vals === null) return [];
    return [vals];
  }

  _isActive(key, value) {
    return this._getActiveValues(key).includes(value);
  }

  _toggle(key, optionValue, multi) {
    const current = this._getActiveValues(key);
    let next;
    if (multi) {
      next = current.includes(optionValue) ? current.filter((v) => v !== optionValue) : [...current, optionValue];
    } else {
      next = current.includes(optionValue) ? [] : [optionValue];
      this._openKey = null;
    }
    this.dispatchEvent(new CustomEvent("builtin-filter-change", { detail: { key, values: next }, bubbles: true, composed: true }));
  }

  _clear(key) {
    this.dispatchEvent(new CustomEvent("builtin-filter-change", { detail: { key, values: [] }, bubbles: true, composed: true }));
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _renderRow() {
    return html`
      <div class="bar">
        ${(this.filters || []).map((filter) => {
          const activeValues = this._getActiveValues(filter.key);
          const hasActive = activeValues.length > 0;
          return html`
            <div class="filter-wrap ${classMap({ open: this._openKey === filter.key })}">
              <button class="filter-btn ${classMap({ active: hasActive })}" @click=${(e) => { e.stopPropagation(); this._openKey = this._openKey === filter.key ? null : filter.key; }}>
                ${filter.label || filter.key}
                ${hasActive ? html`<span class="count">${activeValues.length}</span>` : null}
              </button>
              <div class="dropdown">
                ${(filter.options || []).map((opt) => {
                  const value = typeof opt === "string" ? opt : opt.value;
                  const label = typeof opt === "string" ? opt : (opt.label || opt.value);
                  const selected = this._isActive(filter.key, value);
                  return html`
                    <label class="option" @click=${(e) => { e.stopPropagation(); this._toggle(filter.key, value, filter.multi); }}>
                      <input type="${filter.multi ? "checkbox" : "radio"}" .checked=${selected} readonly />
                      <span class="option-label">${label}</span>
                    </label>
                  `;
                })}
                ${hasActive ? html`
                  <div class="dropdown-actions">
                    <button @click=${(e) => { e.stopPropagation(); this._clear(filter.key); }}>${this._l("clear", "Clear")}</button>
                  </div>
                ` : null}
              </div>
            </div>
          `;
        })}
      </div>
    `;
  }

  _renderChips() {
    const chips = [];
    (this.filters || []).forEach((filter) => {
      const vals = this._getActiveValues(filter.key);
      vals.forEach((v) => {
        const opt = (filter.options || []).find((o) => (typeof o === "string" ? o : o.value) === v);
        const label = opt ? (typeof opt === "string" ? opt : (opt.label || opt.value)) : v;
        chips.push({ key: filter.key, value: v, label });
      });
    });
    return html`
      <div class="chips-row">
        ${chips.length === 0 ? html`<span class="builtin-muted">${this._l("noFilters", "No filters applied")}</span>` : null}
        ${chips.map((c) => html`
          <span class="chip">
            ${c.label}
            <button @click=${() => this._toggle(c.key, c.value, true)} aria-label=${this._l("remove", "Remove")}>×</button>
          </span>
        `)}
        ${chips.length > 0 ? html`<button class="filter-btn" @click=${() => { (this.filters || []).forEach((f) => this._clear(f.key)); }}>${this._l("clearAll", "Clear all")}</button>` : null}
      </div>
    `;
  }

  _renderDrawer() {
    return html`
      <div>
        <button class="filter-btn" @click=${() => this._drawerOpen = true}>
          <builtin-icon name="filter" size="20" variant="outlined"></builtin-icon>
          ${this._l("filters", "Filters")}
        </button>
        <div class="drawer-overlay ${classMap({ open: this._drawerOpen })}" @click=${() => this._drawerOpen = false}></div>
        <div class="drawer ${classMap({ open: this._drawerOpen })}">
          <div class="drawer-header">
            <h4>${this._l("filters", "Filters")}</h4>
            <button class="drawer-close" @click=${() => this._drawerOpen = false}>
              <builtin-icon name="close" size="20" variant="outlined"></builtin-icon>
            </button>
          </div>
          ${(this.filters || []).map((filter) => html`
            <div class="drawer-section">
              <div class="drawer-section-title">${filter.label || filter.key}</div>
              ${(filter.options || []).map((opt) => {
                const value = typeof opt === "string" ? opt : opt.value;
                const label = typeof opt === "string" ? opt : (opt.label || opt.value);
                const selected = this._isActive(filter.key, value);
                return html`
                  <label class="option" @click=${() => this._toggle(filter.key, value, filter.multi)}>
                    <input type="${filter.multi ? "checkbox" : "radio"}" .checked=${selected} readonly />
                    <span class="option-label">${label}</span>
                  </label>
                `;
              })}
            </div>
          `)}
        </div>
      </div>
    `;
  }

  render() {
    const mode = this.mode || "row";
    if (mode === "chips") return this._renderChips();
    if (mode === "drawer") return this._renderDrawer();
    return this._renderRow();
  }
}
