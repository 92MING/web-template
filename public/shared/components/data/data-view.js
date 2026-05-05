import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

export class BuiltinDataView extends BuiltinBaseElement {
  static properties = {
    src: { type: String }, data: { type: Array }, columns: { type: Array }, pageSize: { type: Number, attribute: "page-size" }, searchable: { type: Boolean }, selectable: { type: Boolean }, sortable: { type: Boolean }, density: { type: String }, emptyText: { type: String, attribute: "empty-text" }, keyField: { type: String, attribute: "key-field" }, view: { type: String }, serverMode: { type: Boolean, attribute: "server-mode" }, totalItems: { type: Number, attribute: "total-items" }, labels: { type: Object }, _items: { type: Array, state: true },
  };

  static styles = css`
    :host { display: block; }
    * { box-sizing: border-box; }
    .table { min-height: 260px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); }
    .tabulator { background: var(--builtin-surface, #ffffff); border: 0; color: var(--builtin-color-text, #111827); font-size: 13px; }
    .tabulator .tabulator-header { background: var(--builtin-header-bg, #f9fafb); border-bottom-color: var(--builtin-border-soft, #e5e7eb); color: var(--builtin-color-text, #111827); }
    .tabulator .tabulator-header .tabulator-col { background: var(--builtin-header-bg, #f9fafb); border-right-color: var(--builtin-border-soft, #e5e7eb); }
    .tabulator .tabulator-header input { background: var(--builtin-input-bg, #fff); border: 1px solid var(--builtin-border, #d1d5db); color: var(--builtin-color-text, #111827); border-radius: 4px; padding: 3px 5px; }
    .tabulator-row { background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); border-bottom-color: var(--builtin-border-soft, #e5e7eb); }
    .tabulator-row.tabulator-row-even { background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 50%, var(--builtin-surface, #ffffff)); }
    .tabulator-row .tabulator-cell { border-right-color: var(--builtin-border-soft, #e5e7eb); }
    .tabulator .tabulator-footer { background: var(--builtin-header-bg, #f9fafb); border-top-color: var(--builtin-border-soft, #e5e7eb); color: var(--builtin-color-muted, #6b7280); }
  `;

  constructor() {
    super();
    this.data = []; this.pageSize = 20; this.searchable = true; this.selectable = false; this.sortable = true; this.density = "normal"; this.emptyText = "No data"; this.keyField = "id"; this._items = []; this._table = null;
  }

  connectedCallback() { super.connectedCallback(); if (Array.isArray(this.data) && this.data.length) this._items = this.data.slice(); if (this.src) this.load(); }
  firstUpdated() { this._initTable(); }
  updated(changed) { if (changed.has("data") && Array.isArray(this.data)) this.setData(this.data); if (this._table && (changed.has("columns") || changed.has("pageSize") || changed.has("selectable"))) this._table.setOptions(this._options()); }

  async _initTable() {
    const Tabulator = await ensureVendor("tabulator", { css: "/vendor/tabulator/tabulator.min.css" });
    const target = this.renderRoot.querySelector(".table");
    if (!target || this._table) return;
    this._table = new Tabulator(target, { ...this._options(), data: this._items });
    this._table.on("rowClick", (_event, row) => this.dispatchEvent(new CustomEvent("builtin-row-click", { detail: { row: row.getData() }, bubbles: true, composed: true })));
    this._table.on("rowSelectionChanged", (data) => this.dispatchEvent(new CustomEvent("builtin-selection-change", { detail: { rows: data }, bubbles: true, composed: true })));
  }

  _options() {
    return { layout: "fitColumns", height: "auto", pagination: true, paginationSize: this.pageSize || 20, selectableRows: !!this.selectable, placeholder: this.emptyText || "No data", columns: this._columns(), movableColumns: true };
  }

  _columns() {
    const cols = Array.isArray(this.columns) && this.columns.length ? this.columns : this._inferColumns();
    return cols.map((column) => ({ title: column.label || column.title || column.key || column.field, field: column.field || column.key, sorter: this.sortable !== false ? "string" : false, headerFilter: this.searchable ? "input" : false, visible: !column.hidden }));
  }

  _inferColumns() { const first = this._items?.[0] || {}; return Object.keys(first).map((key) => ({ key, label: key })); }
  async load(options = {}) { const response = await fetch(options.url || this.src, options.fetchOptions || {}); const payload = await response.json(); const rows = Array.isArray(payload) ? payload : (payload.items || payload.data || payload.rows || []); this.setData(rows, { columns: options.columns, totalItems: options.totalItems ?? payload.total ?? payload.count ?? rows.length }); this.dispatchEvent(new CustomEvent("builtin-load", { detail: { items: this._items, payload }, bubbles: true, composed: true })); return this._items; }
  refresh() { return this.load(); }
  setData(items, options = {}) { this._items = Array.isArray(items) ? items.slice() : []; if (options.columns) this.columns = options.columns; if (options.totalItems !== undefined) this.totalItems = Number(options.totalItems) || 0; if (this._table) { this._table.setColumns(this._columns()); this._table.replaceData(this._items); } }
  setFilters(filters = {}) { if (!this._table) return; this._table.clearFilter(true); Object.entries(filters).forEach(([field, value]) => { if (value !== "" && value !== null && value !== undefined) this._table.addFilter(field, "like", value); }); this.dispatchEvent(new CustomEvent("builtin-filter", { detail: { filters }, bubbles: true, composed: true })); }
  getSelectedRows() { return this._table?.getSelectedData?.() || []; }
  clearSelection() { this._table?.deselectRow?.(); }
  exportCsv(filename = "data.csv") { this._table?.download?.("csv", filename); this.dispatchEvent(new CustomEvent("builtin-export", { detail: { filename }, bubbles: true, composed: true })); }
  render() { return html`<link rel="stylesheet" href="/vendor/tabulator/tabulator.min.css"><div class="table"></div>`; }
}