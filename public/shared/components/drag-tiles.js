/**
 * @fileoverview BuiltinDragTiles — Draggable tile grid with resize and remove.
 *
 * @attr {string} items — JSON array `[{id, title, color, size: '1x1'|'1x2'|'2x1'|'2x2'}]`.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-reorder — Fired when items are reordered. Detail: `{ items }`.
 * @event builtin-resize — Fired when a tile is resized. Detail: `{ id, size }`.
 * @event builtin-remove — Fired when a tile is removed. Detail: `{ id }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

const SIZES = ["1x1", "1x2", "2x1", "2x2"];

export class BuiltinDragTiles extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
    labels: { type: Object },
    _dragId: { type: String, state: true },
    _moveId: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
      grid-auto-rows: minmax(120px, auto);
      gap: var(--builtin-gap, 10px);
      padding: var(--builtin-gap, 10px);
    }
    .tile {
      position: relative;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 10px;
      cursor: grab;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.15s ease, box-shadow 0.15s ease;
      user-select: none;
    }
    .tile.dragging {
      opacity: 0.5;
      transform: scale(0.98);
      cursor: grabbing;
    }
    .tile[data-size="1x2"] { grid-row: span 2; }
    .tile[data-size="2x1"] { grid-column: span 2; }
    .tile[data-size="2x2"] { grid-column: span 2; grid-row: span 2; }
    .tile-title {
      font-weight: 600;
      font-size: 14px;
      color: var(--builtin-color-text, #111827);
      word-break: break-word;
    }
    .tile-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 8px;
    }
    .btn-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-surface, #ffffff);
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      color: var(--builtin-color-muted, #6b7280);
      padding: 0;
    }
    .btn-icon:hover { background: var(--builtin-row-hover-bg, #f9fafb); color: var(--builtin-color-text, #111827); }
    .btn-icon.remove:hover { color: var(--builtin-color-danger, #b91c1c); border-color: var(--builtin-color-danger, #b91c1c); }
    .mobile-move {
      display: none;
      position: absolute;
      inset: 0;
      background: var(--builtin-surface, #ffffff);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 10px;
      z-index: 10;
      flex-direction: column;
      gap: 6px;
    }
    .mobile-move.open { display: flex; }
    .move-select {
      padding: 6px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
    }
    @media (max-width: 720px) {
      .grid { grid-template-columns: repeat(2, 1fr); gap: 8px; padding: 8px; }
      .tile[data-size="2x1"] { grid-column: span 2; }
      .tile[data-size="2x2"] { grid-column: span 2; grid-row: span 2; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this._dragId = null;
    this._moveId = null;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _onDragStart(e, id) {
    if (this._ptMobile) {
      e.preventDefault();
      return;
    }
    this._dragId = id;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", id);
  }

  _onDragOver(e, id) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (!this._dragId || this._dragId === id) return;
    const fromIndex = this.items.findIndex((i) => i.id === this._dragId);
    const toIndex = this.items.findIndex((i) => i.id === id);
    if (fromIndex === -1 || toIndex === -1) return;
    const next = [...this.items];
    const [moved] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, moved);
    this.items = next;
  }

  _onDrop(e) {
    e.preventDefault();
    if (this._dragId) {
      this.dispatchEvent(new CustomEvent("builtin-reorder", { detail: { items: this.items }, bubbles: true }));
    }
    this._dragId = null;
  }

  _onDragEnd() {
    this._dragId = null;
  }

  _nextSize(size) {
    const idx = SIZES.indexOf(size);
    return SIZES[(idx + 1) % SIZES.length];
  }

  _onResize(id) {
    const next = this.items.map((i) => {
      if (i.id !== id) return i;
      const size = this._nextSize(i.size || "1x1");
      return { ...i, size };
    });
    const item = next.find((i) => i.id === id);
    this.items = next;
    this.dispatchEvent(new CustomEvent("builtin-resize", { detail: { id, size: item.size }, bubbles: true }));
  }

  _onRemove(id) {
    this.items = this.items.filter((i) => i.id !== id);
    this.dispatchEvent(new CustomEvent("builtin-remove", { detail: { id }, bubbles: true }));
  }

  _openMove(id) {
    this._moveId = this._moveId === id ? null : id;
  }

  _commitMove(id, targetId) {
    if (!targetId || targetId === id) {
      this._moveId = null;
      return;
    }
    const fromIndex = this.items.findIndex((i) => i.id === id);
    const toIndex = this.items.findIndex((i) => i.id === targetId);
    if (fromIndex === -1 || toIndex === -1) {
      this._moveId = null;
      return;
    }
    const next = [...this.items];
    const [moved] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, moved);
    this.items = next;
    this._moveId = null;
    this.dispatchEvent(new CustomEvent("builtin-reorder", { detail: { items: this.items }, bubbles: true }));
  }

  render() {
    return html`
      <div class="grid" @dragover=${(e) => e.preventDefault()} @drop=${this._onDrop}>
        ${repeat(
          this.items,
          (i) => i.id,
          (item) => html`
            <div
              class="tile ${classMap({ dragging: this._dragId === item.id })}"
              data-size="${item.size || "1x1"}"
              draggable="true"
              @dragstart=${(e) => this._onDragStart(e, item.id)}
              @dragover=${(e) => this._onDragOver(e, item.id)}
              @dragend=${this._onDragEnd}
              style="${styleMap({ background: item.color || undefined })}"
            >
              <div class="tile-title">${item.title ?? item.id}</div>
              <div class="tile-actions">
                <button class="btn-icon" @click=${() => this._onResize(item.id)} title="${this._l("resize", "Resize")}">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>
                </button>
                <button class="btn-icon remove" @click=${() => this._onRemove(item.id)} title="${this._l("remove", "Remove")}">
                  <builtin-icon name="delete" size="16" variant="outlined"></builtin-icon>
                </button>
                ${this._ptMobile
                  ? html`
                      <button class="btn-icon" @click=${() => this._openMove(item.id)} title="${this._l("move", "Move")}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>
                      </button>
                    `
                  : null}
              </div>
              ${this._ptMobile && this._moveId === item.id
                ? html`
                    <div class="mobile-move open">
                      <strong>${this._l("moveTo", "Move to")}</strong>
                      <select class="move-select" @change=${(e) => this._commitMove(item.id, e.target.value)}>
                        <option value="">${this._l("selectPosition", "Select position")}</option>
                        ${this.items
                          .filter((i) => i.id !== item.id)
                          .map(
                            (i) => html`<option value="${i.id}">${i.title ?? i.id}</option>`
                          )}
                      </select>
                      <button class="btn-icon" @click=${() => (this._moveId = null)} title="${this._l("close", "Close")}">
                        <builtin-icon name="close" size="16" variant="outlined"></builtin-icon>
                      </button>
                    </div>
                  `
                : null}
            </div>
          `
        )}
      </div>
    `;
  }
}
