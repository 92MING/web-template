/**
 * @fileoverview BuiltinToggleGroup — Exclusive or multi-select toggle button group.
 *
 * @attr {string} items — JSON array `[{label, value, icon}]`.
 * @attr {boolean} multiple — Allow multi-select.
 * @attr {string} values — JSON array of selected values (or single value string when not multiple).
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-change — Detail: `{ values }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

export class BuiltinToggleGroup extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
    multiple: { type: Boolean },
    values: { type: Array },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .group {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 14px;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      transition: background 0.15s, border-color 0.15s, color 0.15s;
      min-height: 36px;
    }
    .btn:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .btn.active {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .btn .icon svg { display: block; }
    @media (max-width: 720px) {
      .group { gap: 8px; }
      .btn { flex: 1 1 auto; min-width: 80px; padding: 10px 12px; font-size: 15px; min-height: 44px; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.multiple = false;
    this.values = [];
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _isSelected(val) {
    if (this.multiple) {
      return (this.values || []).includes(val);
    }
    return this.values === val || (Array.isArray(this.values) && this.values[0] === val);
  }

  _toggle(val) {
    if (this.multiple) {
      const set = new Set(this.values || []);
      if (set.has(val)) set.delete(val);
      else set.add(val);
      this.values = Array.from(set);
    } else {
      this.values = val;
    }
    const detail = { values: this.multiple ? [...this.values] : [this.values] };
    this.dispatchEvent(new CustomEvent("builtin-change", { detail, bubbles: true }));
  }

  render() {
    return html`
      <div class="group" role="group">
        ${repeat(
          this.items || [],
          (item) => item.value,
          (item) => html`
            <button
              class="btn ${classMap({ active: this._isSelected(item.value) })}"
              @click=${() => this._toggle(item.value)}
              aria-pressed="${this._isSelected(item.value)}"
            >
              ${item.icon
                ? html`<span class="icon"><builtin-icon name="${item.icon}" size="16" variant="outlined"></builtin-icon></span>`
                : null}
              ${item.label ?? item.value}
            </button>
          `
        )}
      </div>
    `;
  }
}
