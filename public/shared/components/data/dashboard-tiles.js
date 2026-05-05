/**
 * @fileoverview BuiltinDashboardTiles — Draggable dashboard widget grid.
 *
 * @attr {string} tiles — JSON array of {id, title, content, colSpan, rowSpan, color}.
 * @attr {number} columns — Grid columns (default 4).
 * @attr {boolean} editable — Allow edit mode.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-tiles-reorder — Detail: { tiles }.
 * @event builtin-tile-remove — Detail: { id }.
 * @event builtin-tile-add — Detail: {}.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

export class BuiltinDashboardTiles extends BuiltinBaseElement {
  static properties = {
    tiles: { type: Array },
    columns: { type: Number },
    editable: { type: Boolean },
    labels: { type: Object },
    _dragId: { type: String, state: true },
  };

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  static styles = css`
    :host { display: block; }
    .grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(var(--dt-columns, 4), minmax(0, 1fr));
      grid-auto-rows: minmax(120px, auto);
    }
    .tile {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      overflow: hidden;
      display: flex; flex-direction: column;
      transition: box-shadow .15s ease, transform .15s ease, opacity .15s ease;
    }
    .tile:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.06); }
    .tile.dragging { opacity: .55; transform: scale(0.98); }
    .tile-body ::slotted(*) { flex: 1; }
    .tile-header {
      display: flex; align-items: center; justify-content: space-between;
      gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .tile-title { font-weight: 650; font-size: 13px; color: var(--builtin-color-text, #111827); }
    .tile-actions { display: inline-flex; gap: 4px; }
    .tile-actions button {
      border: 0; background: transparent; padding: 4px; min-height: 0; cursor: pointer;
      color: var(--builtin-color-muted, #6b7280); display: inline-flex; align-items: center; justify-content: center; border-radius: 4px;
    }
    .tile-actions button:hover { background: var(--builtin-row-hover-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .tile-body { padding: 12px; flex: 1; }
    .add-tile {
      border: 2px dashed var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      display: flex; align-items: center; justify-content: center;
      min-height: 120px; cursor: pointer; color: var(--builtin-color-muted, #6b7280);
      background: var(--builtin-surface, #ffffff);
    }
    .add-tile:hover { border-color: var(--builtin-primary, #2563eb); color: var(--builtin-primary, #2563eb); background: var(--builtin-header-bg, #f9fafb); }
    @media (max-width: 720px) {
      .grid { grid-template-columns: 1fr !important; }
    }
  `;

  constructor() {
    super();
    this.tiles = [];
    this.columns = 4;
    this.editable = false;
    this.labels = {};
    this._dragId = "";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _onDragStart(e, id) {
    if (this._ptMobile) { e.preventDefault(); return; }
    this._dragId = id;
    e.dataTransfer.effectAllowed = "move";
  }

  _onDragOver(e, id) {
    e.preventDefault();
    if (!this._dragId || this._dragId === id) return;
    const tiles = [...this.tiles];
    const fromIdx = tiles.findIndex((t) => t.id === this._dragId);
    const toIdx = tiles.findIndex((t) => t.id === id);
    if (fromIdx === -1 || toIdx === -1) return;
    const [moved] = tiles.splice(fromIdx, 1);
    tiles.splice(toIdx, 0, moved);
    this.tiles = tiles;
    this.dispatchEvent(new CustomEvent("builtin-tiles-reorder", { bubbles: true, composed: true, detail: { tiles: this.tiles } }));
    this._dragId = id;
  }

  _onDragEnd() {
    this._dragId = "";
  }

  _remove(id) {
    this.dispatchEvent(new CustomEvent("builtin-tile-remove", { bubbles: true, composed: true, detail: { id } }));
  }

  render() {
    const cols = Math.max(1, Math.min(6, Number(this.columns) || 4));
    const tiles = this.tiles || [];
    return html`
      <div class="grid" style="--dt-columns:${cols}">
        ${tiles.map((t) => html`
          <div
            class="tile ${classMap({ dragging: this._dragId === t.id })}"
            style="${styleMap({ gridColumn: t.colSpan ? `span ${Math.min(t.colSpan, cols)}` : undefined, gridRow: t.rowSpan ? `span ${t.rowSpan}` : undefined, borderTop: t.color ? `3px solid ${t.color}` : undefined })}"
            draggable="${this.editable && !this._ptMobile}"
            @dragstart="${(e) => this._onDragStart(e, t.id)}"
            @dragover="${(e) => this._onDragOver(e, t.id)}"
            @dragend="${this._onDragEnd}"
          >
            <div class="tile-header">
              <span class="tile-title">${t.title || ""}</span>
              ${this.editable ? html`
                <div class="tile-actions">
                  <button @click="${() => this._remove(t.id)}" title="${this._l("tile.remove", "Remove")}">
                    <builtin-icon name="close" size="14" variant="outlined"></builtin-icon>
                  </button>
                </div>
              ` : ""}
            </div>
            <div class="tile-body"><slot name="${t.id}">${t.content || ""}</slot></div>
          </div>
        `)}
        ${this.editable ? html`
          <div class="add-tile" @click="${() => this.dispatchEvent(new CustomEvent('builtin-tile-add', { bubbles:true, composed:true }))}">
            <builtin-icon name="plus" size="24" variant="outlined"></builtin-icon>
          </div>
        ` : ""}
      </div>
    `;
  }
}
