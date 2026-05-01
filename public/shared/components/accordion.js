/**
 * @fileoverview BuiltinAccordion — Collapsible accordion panel group (Lit).
 *
 * @attr {string} items — JSON array of { title, content, disabled }.
 * @attr {boolean} single — Only one panel open at a time.
 * @attr {string} variant — `default` | `bordered` | `separated` (default `default`).
 * @attr {string} size — `compact` | `default` | `comfortable`.
 *
 * @slots
 *   - default: Panel elements with `data-title` and optional `data-disabled`
 *
 * @event builtin-toggle — Fired when a panel opens/closes. Detail: { index, open }
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

export class BuiltinAccordion extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
    single: { type: Boolean },
    variant: { type: String },
    size: { type: String },
    defaultOpen: { type: Array, attribute: "default-open" },
    labels: { type: Object },
    _openIndices: { type: Set, state: true },
  };

  static styles = css`
    :host { display: block; }
    .accordion { display: flex; flex-direction: column; }
    .panel {
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .accordion.bordered .panel {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      margin-bottom: 8px;
      overflow: hidden;
    }
    .accordion.bordered .panel:last-child { margin-bottom: 0; }
    .accordion.separated .panel {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      margin-bottom: 10px;
      background: var(--builtin-surface, #ffffff);
      overflow: hidden;
    }
    .accordion.separated .panel:last-child { margin-bottom: 0; }

    .header {
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px; width: 100%; background: transparent; border: none;
      color: var(--builtin-color-text, #111827); font: inherit; text-align: left;
      cursor: pointer; transition: background .12s ease;
    }
    .header:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .header.disabled { cursor: not-allowed; opacity: .55; }
    .header.disabled:hover { background: transparent; }

    .size-compact .header { padding: 8px 10px; }
    .size-default .header { padding: 12px 14px; }
    .size-comfortable .header { padding: 16px 18px; }

    .title { font-weight: 650; flex: 1; }
    .size-compact .title { font-size: 13px; }
    .size-default .title { font-size: 14px; }
    .size-comfortable .title { font-size: 15px; }

    .chevron {
      display: inline-flex; align-items: center; justify-content: center;
      transition: transform .2s ease; flex-shrink: 0;
      color: var(--builtin-color-muted, #6b7280);
    }
    .chevron.open { transform: rotate(180deg); }

    .body {
      display: grid; grid-template-rows: 0fr;
      transition: grid-template-rows .25s ease;
    }
    .body.open { grid-template-rows: 1fr; }
    .body-inner { opacity: 0; transition: opacity .2s ease; }
    .body.open .body-inner { opacity: 1; }
    .body-inner {
      overflow: hidden;
      color: var(--builtin-color-text, #111827);
    }
    .size-compact .body-inner { padding: 0 10px 10px; font-size: 13px; }
    .size-default .body-inner { padding: 0 14px 14px; font-size: 14px; }
    .size-comfortable .body-inner { padding: 0 18px 18px; font-size: 14px; }
  `;

  constructor() {
    super();
    this.items = [];
    this.single = false;
    this.variant = "default";
    this.size = "default";
    this.defaultOpen = [];
    this.labels = {};
    this._openIndices = new Set();
  }

  connectedCallback() {
    super.connectedCallback();
    const defaults = Array.isArray(this.defaultOpen) ? this.defaultOpen : [];
    if (defaults.length && this._openIndices.size === 0) {
      this._openIndices = this.single ? new Set([defaults[0]]) : new Set(defaults);
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _isOpen(index) {
    return this._openIndices.has(index);
  }

  _toggle(index, disabled) {
    if (disabled) return;
    const open = this._isOpen(index);
    if (this.single) {
      this._openIndices = open ? new Set() : new Set([index]);
    } else {
      const next = new Set(this._openIndices);
      if (open) next.delete(index);
      else next.add(index);
      this._openIndices = next;
    }
    this.dispatchEvent(
      new CustomEvent("builtin-toggle", { bubbles: true, composed: true, detail: { index, open: !open } })
    );
  }

  _getPanels() {
    if (this.items && this.items.length > 0) {
      return this.items.map((it, idx) => ({
        index: idx,
        title: it.title || "",
        content: it.content || "",
        disabled: !!it.disabled,
      }));
    }
    const slotted = Array.from(this.querySelectorAll("[data-title]"));
    return slotted.map((el, idx) => ({
      index: idx,
      title: el.dataset.title || "",
      content: el.innerHTML,
      disabled: el.dataset.disabled === "true" || el.hasAttribute("data-disabled"),
    }));
  }

  render() {
    const panels = this._getPanels();
    const variant = this.variant || "default";
    const size = this.size || "default";
    const wrapClass = { accordion: true, [variant]: true, [`size-${size}`]: true };

    return html`
      <div class="${classMap(wrapClass)}">
        ${repeat(
          panels,
          (p) => p.index,
          (p) => {
            const isOpen = this._isOpen(p.index);
            return html`
              <div class="panel">
                <button
                  class="header ${classMap({ disabled: p.disabled })}"
                  aria-expanded="${isOpen}"
                  @click="${() => this._toggle(p.index, p.disabled)}"
                >
                  <span class="title">${p.title}</span>
                  <span class="chevron ${classMap({ open: isOpen })}">
                    <builtin-icon name="down" size="16" variant="outlined"></builtin-icon>
                  </span>
                </button>
                <div class="body ${classMap({ open: isOpen })}">
                  <div class="body-inner">${unsafeHTML(p.content)}</div>
                </div>
              </div>
            `;
          }
        )}
      </div>
    `;
  }
}

