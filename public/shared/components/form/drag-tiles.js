import { BuiltinBaseElement, html, css, repeat, styleMap } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

const SIZES = ["1x1", "1x2", "2x1", "2x2"];

export class BuiltinDragTiles extends BuiltinBaseElement {
  static properties = { items: { type: Array }, labels: { type: Object } };
  static styles = css`:host { display: block; } .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); grid-auto-rows: minmax(120px, auto); gap: var(--builtin-gap, 10px); } .tile { display: flex; flex-direction: column; justify-content: space-between; padding: 10px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); background: var(--builtin-surface, #fff); color: var(--builtin-color-text, #111827); cursor: grab; } .tile[data-size="1x2"] { grid-row: span 2; } .tile[data-size="2x1"] { grid-column: span 2; } .tile[data-size="2x2"] { grid-column: span 2; grid-row: span 2; } .actions { display: flex; gap: 6px; margin-top: 8px; } button { width: 28px; height: 28px; padding: 0; display: inline-grid; place-items: center; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); background: var(--builtin-button-bg, #ffffff); color: var(--builtin-color-text, #111827); cursor: pointer; } button:hover { background: var(--builtin-button-hover-bg, #f9fafb); }`;

  constructor() { super(); this.items = []; this._sortable = null; }
  firstUpdated() { this._initSortable(); }
  updated(changed) { if (changed.has("items")) this._initSortable(); }
  disconnectedCallback() { this._sortable?.destroy?.(); this._sortable = null; super.disconnectedCallback(); }

  async _initSortable() {
    const Sortable = await ensureVendor("sortablejs");
    const grid = this.renderRoot.querySelector(".grid");
    if (!grid || this._sortable) return;
    this._sortable = new Sortable(grid, {
      animation: 150,
      draggable: ".tile",
      onEnd: (event) => {
        const next = [...(this.items || [])];
        const [moved] = next.splice(event.oldIndex, 1);
        next.splice(event.newIndex, 0, moved);
        this.items = next;
        this.dispatchEvent(new CustomEvent("builtin-reorder", { detail: { items: this.items }, bubbles: true, composed: true }));
      },
    });
  }

  _nextSize(size) { return SIZES[(SIZES.indexOf(size) + 1) % SIZES.length] || "1x1"; }
  _resize(id) { const next = this.items.map((item) => item.id === id ? { ...item, size: this._nextSize(item.size || "1x1") } : item); const item = next.find((entry) => entry.id === id); this.items = next; this.dispatchEvent(new CustomEvent("builtin-resize", { detail: { id, size: item.size }, bubbles: true, composed: true })); }
  _remove(id) { this.items = this.items.filter((item) => item.id !== id); this.dispatchEvent(new CustomEvent("builtin-remove", { detail: { id }, bubbles: true, composed: true })); }

  render() { return html`<div class="grid">${repeat(this.items || [], (item) => item.id, (item) => html`<div class="tile" data-size="${item.size || "1x1"}" data-id="${item.id}" style=${styleMap({ background: item.color || undefined })}><div>${item.title ?? item.id}</div><div class="actions"><button @click=${() => this._resize(item.id)}><builtin-icon name="expand" size="16"></builtin-icon></button><button @click=${() => this._remove(item.id)}><builtin-icon name="delete" size="16"></builtin-icon></button></div></div>`)}</div>`; }
}