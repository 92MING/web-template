/**
 * @fileoverview BuiltinDraggableTabs — Tabs that can be dragged to reorder and closed.
 *
 * @attr {string} items — JSON array of {id, label, closable, icon}.
 * @attr {string} active — Active tab id.
 * @attr {string} type — 'underline' | 'pills' | 'vertical'.
 * @attr {boolean} addable — Show + button.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-tab-change — Detail: { id }.
 * @event builtin-tab-reorder — Detail: { fromIndex, toIndex }.
 * @event builtin-tab-close — Detail: { id }.
 * @event builtin-tab-add — Detail: {}.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

export class BuiltinDraggableTabs extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
    active: { type: String },
    type: { type: String },
    addable: { type: Boolean },
    labels: { type: Object },
    _dragIndex: { type: Number, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap { display: flex; flex-direction: column; }
    .tabs { display: flex; background: var(--builtin-header-bg, #f9fafb); overflow: auto; scrollbar-width: none; gap: 2px; padding: 4px; }
    .tabs::-webkit-scrollbar { display: none; }
    .tab {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 8px 12px; border-radius: var(--builtin-radius, 6px); cursor: pointer;
      white-space: nowrap; user-select: none; font-size: 13px; font-weight: 500;
      color: var(--builtin-color-muted, #6b7280); border: 1px solid transparent; background: transparent;
      transition: background .15s ease, color .15s ease, opacity .15s ease, transform .15s ease;
    }
    .tab:hover { color: var(--builtin-color-text, #111827); background: var(--builtin-row-hover-bg, #f3f4f6); }
    .tab.active { color: var(--builtin-primary, #2563eb); background: var(--builtin-surface, #ffffff); border-color: var(--builtin-border, #d1d5db); }
    .tab.dragging { opacity: .5; transform: scale(0.97); }
    .panels { padding: 12px; animation: builtin-tab-panel-in 0.2s ease; }
    @keyframes builtin-tab-panel-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: translateY(0); } }
    .close {
      display: inline-flex; align-items: center; justify-content: center;
      width: 16px; height: 16px; border-radius: 4px; border: none; background: transparent;
      color: var(--builtin-color-muted, #6b7280); cursor: pointer; padding: 0; font-size: 12px; visibility: hidden;
    }
    .tab:hover .close, .tab.active .close { visibility: visible; }
    .close:hover { background: var(--builtin-border-soft, #e5e7eb); color: var(--builtin-color-danger, #b91c1c); }
    .add { padding: 8px 10px; cursor: pointer; color: var(--builtin-color-muted, #6b7280); border: none; background: transparent; border-radius: var(--builtin-radius, 6px); }
    .add:hover { background: var(--builtin-row-hover-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .panels { padding: 12px; }
    ::slotted([data-tab]) { display: none !important; }
    @media (max-width: 720px) {
      .tab { padding: 8px 10px; }
      .close { visibility: visible; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.active = "";
    this.type = "underline";
    this.addable = false;
    this.labels = {};
    this._dragIndex = -1;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _onDragStart(e, idx) {
    if (this._ptMobile) { e.preventDefault(); return; }
    this._dragIndex = idx;
    e.dataTransfer.effectAllowed = "move";
  }

  _onDragOver(e, idx) {
    e.preventDefault();
    if (this._dragIndex === -1 || this._dragIndex === idx) return;
    const items = [...this.items];
    const [moved] = items.splice(this._dragIndex, 1);
    items.splice(idx, 0, moved);
    this.items = items;
    this.dispatchEvent(new CustomEvent("builtin-tab-reorder", { bubbles: true, composed: true, detail: { fromIndex: this._dragIndex, toIndex: idx } }));
    this._dragIndex = idx;
  }

  _onDragEnd() {
    this._dragIndex = -1;
  }

  _onClose(e, id) {
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("builtin-tab-close", { bubbles: true, composed: true, detail: { id } }));
  }

  render() {
    const items = this.items || [];
    const ids = items.map((i) => i.id);
    let active = this.active || "";
    if (!ids.includes(active)) active = ids[0] || "";

    return html`
      <style>::slotted([data-tab="${active}"]) { display: block !important; }</style>
      <div class="wrap">
        <div class="tabs">
          ${items.map((it, idx) => html`
            <div
              class="tab ${classMap({ active: it.id === active, dragging: idx === this._dragIndex })}"
              draggable="true"
              @dragstart="${(e) => this._onDragStart(e, idx)}"
              @dragover="${(e) => this._onDragOver(e, idx)}"
              @dragend="${this._onDragEnd}"
              @click="${() => { this.active = it.id; this.dispatchEvent(new CustomEvent('builtin-tab-change', { bubbles:true, composed:true, detail:{id:it.id} })); }}"
            >
              ${it.icon ? html`<builtin-icon name="${it.icon}" size="14" variant="outlined"></builtin-icon>` : ""}
              <span>${it.label || it.id}</span>
              ${it.closable !== false ? html`
                <button class="close" @click="${(e) => this._onClose(e, it.id)}">×</button>
              ` : ""}
            </div>
          `)}
          ${this.addable ? html`
            <button class="add" @click="${() => this.dispatchEvent(new CustomEvent('builtin-tab-add', { bubbles:true, composed:true }))}">+</button>
          ` : ""}
        </div>
        <div class="panels"><slot></slot></div>
      </div>
    `;
  }
}
