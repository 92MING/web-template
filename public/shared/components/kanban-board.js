/**
 * @fileoverview BuiltinKanbanBoard — Kanban board with drag-and-drop cards.
 *
 * @attr {string} columns — JSON `[{id, title, cards: [{id, title, description, tags, color}]}]`.
 * @attr {string} labels — JSON i18n overrides.
 * @attr {string} variant — `default` | `compact` (default `default`).
 *
 * @event builtin-move — `{ cardId, fromColumnId, toColumnId, toIndex }`
 * @event builtin-card-add — `{ columnId, card }`
 * @event builtin-card-delete — `{ columnId, cardId }`
 * @event builtin-column-add — `{ column }`
 * @event builtin-column-delete — `{ columnId }`
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinKanbanBoard extends BuiltinBaseElement {
  static properties = {
    columns: { type: Array },
    labels: { type: Object },
    variant: { type: String },
    _dragCardId: { type: String, state: true },
    _dragFromId: { type: String, state: true },
    _addingColumn: { type: Boolean, state: true },
    _editingCard: { type: Object, state: true },
  };

  static styles = css`
    :host { display: block; }
    .board { display: flex; gap: 12px; overflow-x: auto; padding: 10px; background: var(--builtin-bg-subtle, var(--builtin-header-bg, #f3f4f6)); border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); scrollbar-width: thin; scrollbar-color: var(--builtin-border, #d1d5db) var(--builtin-bg-subtle, var(--builtin-header-bg, #f3f4f6)); }
    .board::-webkit-scrollbar { height: 10px; }
    .board::-webkit-scrollbar-track { background: var(--builtin-bg-subtle, var(--builtin-header-bg, #f3f4f6)); border-radius: 999px; }
    .board::-webkit-scrollbar-thumb { background: var(--builtin-border, #d1d5db); border-radius: 999px; border: 2px solid var(--builtin-bg-subtle, var(--builtin-header-bg, #f3f4f6)); }
    .column { min-width: 260px; width: 260px; background: var(--builtin-surface, #ffffff); border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px); display: flex; flex-direction: column; max-height: 80vh; }
    .column.compact { min-width: 220px; width: 220px; }
    .col-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .col-title { font-weight: 650; font-size: 14px; color: var(--builtin-color-text, #111827); }
    .col-count { font-size: 11px; color: var(--builtin-color-muted, #6b7280); background: var(--builtin-bg-subtle, var(--builtin-header-bg, #f3f4f6)); padding: 2px 6px; border-radius: 999px; }
    .col-actions { display: inline-flex; gap: 4px; }
    .col-actions button { border: 0; background: transparent; padding: 4px; cursor: pointer; color: var(--builtin-color-muted, #6b7280); border-radius: var(--builtin-radius, 6px); display: inline-flex; align-items: center; justify-content: center; }
    .col-actions button:hover { background: var(--builtin-row-hover-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .cards { flex: 1 1 auto; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 8px; }
    .card { background: var(--builtin-surface, #ffffff); border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px); padding: 10px; cursor: grab; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
    .card:active { cursor: grabbing; }
    .card.dragging { opacity: 0.6; }
    .card-title { font-weight: 600; font-size: 13px; margin-bottom: 4px; color: var(--builtin-color-text, #111827); }
    .card-desc { font-size: 12px; color: var(--builtin-color-muted, #6b7280); margin-bottom: 6px; }
    .tags { display: flex; flex-wrap: wrap; gap: 4px; }
    .tag { font-size: 11px; padding: 2px 6px; border-radius: 999px; background: var(--builtin-bg-subtle, var(--builtin-header-bg, #f3f4f6)); color: var(--builtin-color-muted, #6b7280); }
    .add-card { padding: 8px; }
    .add-card button { width: 100%; padding: 8px; border: 1px dashed var(--builtin-border, #d1d5db); background: transparent; border-radius: var(--builtin-radius, 6px); cursor: pointer; color: var(--builtin-color-muted, #6b7280); font-size: 13px; }
    .add-card button:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .drop-zone { min-height: 20px; border: 2px dashed transparent; border-radius: var(--builtin-radius, 6px); }
    .drop-zone.over { border-color: var(--builtin-primary, #2563eb); background: var(--builtin-primary-soft, #eff6ff); }
    .board-actions { display: flex; align-items: center; gap: 8px; min-width: 180px; }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 10px; border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-surface, #ffffff); border-radius: var(--builtin-radius, 6px); cursor: pointer; color: var(--builtin-color-text, #111827); min-height: 32px; }
    .btn:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .btn.primary { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .btn.danger { color: var(--builtin-danger, #dc2626); border-color: var(--builtin-danger, #dc2626); }
    input, textarea { width: 100%; padding: 6px 8px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); font: inherit; }
    .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.35); display: flex; align-items: center; justify-content: center; z-index: 9999; padding: 20px; }
    .modal { background: var(--builtin-surface, #ffffff); border-radius: var(--builtin-radius-lg, 8px); padding: 16px; width: 100%; max-width: 420px; box-shadow: 0 20px 60px rgba(0,0,0,0.18); }
    .modal-header { font-weight: 650; margin-bottom: 10px; color: var(--builtin-color-text, #111827); }
    .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
    .mobile-move { margin-top: 6px; }
    .mobile-move select { width: 100%; padding: 6px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); }
    @media (max-width: 720px) {
      .board { flex-direction: column; overflow-x: hidden; }
      .column { width: 100%; min-width: 0; max-height: none; }
    }
  `;

  constructor() {
    super();
    this.columns = [];
    this.variant = "default";
    this._dragCardId = null;
    this._dragFromId = null;
    this._addingColumn = false;
    this._editingCard = null;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _ensureColumns() {
    if (!Array.isArray(this.columns)) this.columns = [];
  }

  _onDragStart(e, cardId, columnId) {
    this._dragCardId = cardId;
    this._dragFromId = columnId;
    e.dataTransfer.effectAllowed = "move";
    e.target.classList.add("dragging");
  }

  _onDragEnd(e) {
    e.target.classList.remove("dragging");
    this._dragCardId = null;
    this._dragFromId = null;
    this.shadowRoot.querySelectorAll(".drop-zone").forEach((z) => z.classList.remove("over"));
  }

  _onDragOver(e) {
    e.preventDefault();
    e.currentTarget.classList.add("over");
  }

  _onDragLeave(e) {
    e.currentTarget.classList.remove("over");
  }

  _onDrop(e, toColumnId) {
    e.preventDefault();
    e.currentTarget.classList.remove("over");
    const fromId = this._dragFromId;
    const cardId = this._dragCardId;
    if (!fromId || !cardId || fromId === toColumnId) return;
    const fromCol = this.columns.find((c) => c.id === fromId);
    const toCol = this.columns.find((c) => c.id === toColumnId);
    if (!fromCol || !toCol) return;
    const cardIndex = fromCol.cards.findIndex((c) => c.id === cardId);
    if (cardIndex === -1) return;
    const card = fromCol.cards[cardIndex];
    fromCol.cards = fromCol.cards.filter((c) => c.id !== cardId);
    toCol.cards = [...toCol.cards, card];
    this.columns = this.columns.slice();
    this.dispatchEvent(new CustomEvent("builtin-move", {
      detail: { cardId, fromColumnId: fromId, toColumnId: toColumnId, toIndex: toCol.cards.length - 1 },
      bubbles: true,
    }));
  }

  _addCard(columnId, title, description = "", tags = "") {
    const col = this.columns.find((c) => c.id === columnId);
    if (!col) return;
    const card = { id: `${columnId}-card-${Date.now()}`, title, description, tags: tags ? tags.split(",").map((t) => t.trim()) : [], color: "" };
    col.cards = [...col.cards, card];
    this.columns = this.columns.slice();
    this.dispatchEvent(new CustomEvent("builtin-card-add", { detail: { columnId, card }, bubbles: true }));
  }

  _deleteCard(columnId, cardId) {
    const col = this.columns.find((c) => c.id === columnId);
    if (!col) return;
    col.cards = col.cards.filter((c) => c.id !== cardId);
    this.columns = this.columns.slice();
    this.dispatchEvent(new CustomEvent("builtin-card-delete", { detail: { columnId, cardId }, bubbles: true }));
  }

  _addColumn(title) {
    const column = { id: `col-${Date.now()}`, title, cards: [] };
    this.columns = [...this.columns, column];
    this._addingColumn = false;
    this.dispatchEvent(new CustomEvent("builtin-column-add", { detail: { column }, bubbles: true }));
  }

  _deleteColumn(columnId) {
    this.columns = this.columns.filter((c) => c.id !== columnId);
    this.dispatchEvent(new CustomEvent("builtin-column-delete", { detail: { columnId }, bubbles: true }));
  }

  _openCardModal(columnId, card = null) {
    this._editingCard = { columnId, card, title: card?.title || "", description: card?.description || "", tags: (card?.tags || []).join(", ") };
  }

  _saveCard() {
    if (!this._editingCard) return;
    const { columnId, card, title, description, tags } = this._editingCard;
    if (!title.trim()) return;
    if (card) {
      card.title = title;
      card.description = description;
      card.tags = tags ? tags.split(",").map((t) => t.trim()) : [];
      this.columns = this.columns.slice();
    } else {
      this._addCard(columnId, title, description, tags);
    }
    this._editingCard = null;
  }

  _moveCardMobile(columnId, cardId, targetColumnId) {
    if (columnId === targetColumnId) return;
    const fromCol = this.columns.find((c) => c.id === columnId);
    const toCol = this.columns.find((c) => c.id === targetColumnId);
    if (!fromCol || !toCol) return;
    const card = fromCol.cards.find((c) => c.id === cardId);
    if (!card) return;
    fromCol.cards = fromCol.cards.filter((c) => c.id !== cardId);
    toCol.cards = [...toCol.cards, card];
    this.columns = this.columns.slice();
    this.dispatchEvent(new CustomEvent("builtin-move", {
      detail: { cardId, fromColumnId: columnId, toColumnId: targetColumnId, toIndex: toCol.cards.length - 1 },
      bubbles: true,
    }));
  }

  _renderCard(card, columnId) {
    return html`
      <div class="card" draggable="true"
        @dragstart=${(e) => this._onDragStart(e, card.id, columnId)}
        @dragend=${this._onDragEnd}>
        <div class="card-title">${card.title}</div>
        ${card.description ? html`<div class="card-desc">${card.description}</div>` : null}
        ${card.tags?.length ? html`<div class="tags">${card.tags.map((t) => html`<span class="tag">${t}</span>`)}</div>` : null}
        ${this._ptMobile ? html`
          <div class="mobile-move">
            <select @change=${(e) => { if (e.target.value) { this._moveCardMobile(columnId, card.id, e.target.value); e.target.value = ""; } }}>
              <option value="">${this._l("moveTo", "Move to...")}</option>
              ${this.columns.filter((c) => c.id !== columnId).map((c) => html`<option value="${c.id}">${c.title}</option>`)}
            </select>
          </div>
        ` : null}
      </div>
    `;
  }

  render() {
    this._ensureColumns();
    return html`
      <div class="board">
        ${this.columns.map((col) => html`
          <div class="column ${this.variant}">
            <div class="col-header">
              <div style="display:flex;align-items:center;gap:8px;">
                <span class="col-title">${col.title}</span>
                <span class="col-count">${(col.cards || []).length}</span>
              </div>
              <div class="col-actions">
                <button @click=${() => this._openCardModal(col.id)} title=${this._l("addCard", "Add card")}>
                  <builtin-icon name="plus" size="20" variant="outlined"></builtin-icon>
                </button>
                <button class="danger" @click=${() => this._deleteColumn(col.id)} title=${this._l("deleteColumn", "Delete column")}>
                  <builtin-icon name="delete" size="20" variant="outlined"></builtin-icon>
                </button>
              </div>
            </div>
            <div class="cards">
              ${(col.cards || []).map((card) => this._renderCard(card, col.id))}
            </div>
            <div class="drop-zone"
              @dragover=${this._onDragOver}
              @dragleave=${this._onDragLeave}
              @drop=${(e) => this._onDrop(e, col.id)}>
            </div>
            <div class="add-card">
              <button @click=${() => this._openCardModal(col.id)}>+ ${this._l("addCard", "Add card")}</button>
            </div>
          </div>
        `)}
        <div class="board-actions">
          ${this._addingColumn
            ? html`
              <input type="text" placeholder=${this._l("columnName", "Column name")}
                @keydown=${(e) => { if (e.key === "Enter") this._addColumn(e.target.value); if (e.key === "Escape") this._addingColumn = false; }}
                @blur=${(e) => { if (e.target.value.trim()) this._addColumn(e.target.value); else this._addingColumn = false; }}
                autofocus>
            `
            : html`<button class="btn primary" @click=${() => this._addingColumn = true}>
              <builtin-icon name="plus" size="20" variant="outlined"></builtin-icon>
              ${this._l("addColumn", "Add column")}
            </button>`}
          <slot name="actions"></slot>
        </div>
      </div>
      ${this._editingCard ? html`
        <div class="overlay" @click=${() => this._editingCard = null}>
          <div class="modal" @click=${(e) => e.stopPropagation()}>
            <div class="modal-header">${this._editingCard.card ? this._l("editCard", "Edit card") : this._l("newCard", "New card")}</div>
            <input type="text" placeholder=${this._l("title", "Title")} .value=${this._editingCard.title} @input=${(e) => this._editingCard = { ...this._editingCard, title: e.target.value }}>
            <textarea placeholder=${this._l("description", "Description")} rows="3" .value=${this._editingCard.description} @input=${(e) => this._editingCard = { ...this._editingCard, description: e.target.value }}></textarea>
            <input type="text" placeholder=${this._l("tags", "Tags (comma separated)")} .value=${this._editingCard.tags} @input=${(e) => this._editingCard = { ...this._editingCard, tags: e.target.value }}>
            <div class="modal-actions">
              <button class="btn" @click=${() => this._editingCard = null}>${this._l("cancel", "Cancel")}</button>
              <button class="btn primary" @click=${this._saveCard}>${this._l("save", "Save")}</button>
              ${this._editingCard.card ? html`<button class="btn danger" @click=${() => { this._deleteCard(this._editingCard.columnId, this._editingCard.card.id); this._editingCard = null; }}>${this._l("delete", "Delete")}</button>` : null}
            </div>
          </div>
        </div>
      ` : null}
    `;
  }
}
