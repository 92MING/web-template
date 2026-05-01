/**
 * @fileoverview BuiltinDataView — Generic data table/list for CRUD screens, dashboards, admin pages, and search results.
 *
 * @attr {string} src — Fetch data from an endpoint.
 * @attr {string} columns — JSON column definitions.
 * @attr {number} page-size — Client-side page size (default 20).
 * @attr {boolean} searchable — Enable full-table search.
 * @attr {boolean} selectable — Enable row selection.
 * @attr {boolean} sortable — Enable column sorting.
 * @attr {string} density — `compact`, `normal`, or `comfortable`.
 * @attr {string} empty-text — Text shown when no rows.
 * @attr {string} key-field — Unique row id field (default `id`).
 * @attr {string} view — `table` | `grid` | `cards`.
 *
 * @method load(options) — Fetch and display data.
 * @method refresh() — Reload from src.
 * @method setData(items, { columns }) — Set local data.
 * @method setFilters(filters) — Apply column filters.
 * @method getSelectedRows() — Return selected row objects.
 * @method clearSelection() — Unselect all.
 * @method exportCsv(filename) — Download current view as CSV.
 *
 * @event builtin-load — Data loaded successfully.
 * @event builtin-error — Load failed.
 * @event builtin-filter — Filters changed.
 * @event builtin-row-click — A row was clicked.
 * @event builtin-selection-change — Selection changed.
 * @event builtin-export — CSV exported.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";
import { getByPath, normalizeColumns, csvCell } from "./core.js";

export class BuiltinDataView extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    columns: { type: Array },
    pageSize: { type: Number, attribute: "page-size" },
    searchable: { type: Boolean },
    selectable: { type: Boolean },
    sortable: { type: Boolean },
    density: { type: String },
    emptyText: { type: String, attribute: "empty-text" },
    keyField: { type: String, attribute: "key-field" },
    view: { type: String },
    serverMode: { type: Boolean, attribute: "server-mode" },
    totalItems: { type: Number, attribute: "total-items" },
    labels: { type: Object },
    _items: { type: Array, state: true },
    _selected: { type: Object, state: true },
    _filters: { type: Object, state: true },
    _sort: { type: Object, state: true },
    _page: { type: Number, state: true },
    _loading: { type: Boolean, state: true },
    _error: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .builtin-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
    .builtin-toolbar-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .builtin-surface { border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); background: var(--builtin-surface, #ffffff); overflow: hidden; color: var(--builtin-color-text, #111827); }
    .builtin-table-wrap { width: 100%; overflow: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); padding: var(--builtin-cell-padding, 10px 12px); text-align: left; vertical-align: middle; white-space: nowrap; }
    th { background: var(--builtin-header-bg, #f9fafb); color: var(--builtin-color-muted, #374151); font-weight: 650; position: sticky; top: 0; z-index: 1; }
    tr[data-clickable="true"] { cursor: pointer; }
    tr:hover td { background: var(--builtin-row-hover-bg, #f9fafb); }
    .builtin-density-compact { --builtin-cell-padding: 6px 8px; }
    .builtin-density-comfortable { --builtin-cell-padding: 12px 14px; }
    .builtin-cell-truncate { max-width: var(--builtin-truncate-width, 280px); overflow: hidden; text-overflow: ellipsis; }
    .builtin-status { padding: 28px; text-align: center; color: var(--builtin-color-muted, #6b7280); }
    .builtin-pager { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); flex-wrap: wrap; }
    .builtin-sort { border: 0; background: transparent; padding: 0; min-height: 0; color: inherit; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
    .builtin-sort:hover { color: var(--builtin-primary, #2563eb); }
    .builtin-actions { display: inline-flex; align-items: center; gap: 6px; }
    .builtin-primary { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .builtin-primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .grid-view { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; padding: 12px; animation: builtin-dv-fade 0.2s ease; }
    .card-view { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding: 12px; animation: builtin-dv-fade 0.2s ease; }
    @keyframes builtin-dv-fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
    .grid-item, .card-item { border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px); padding: 12px; background: var(--builtin-surface, #ffffff); }
    .card-item { box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
    .item-row { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; padding: 4px 0; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .item-row:last-child { border-bottom: none; }
    .item-key { color: var(--builtin-color-muted, #6b7280); }
    .item-val { color: var(--builtin-color-text, #111827); text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
    @media (max-width: 720px) {
      .builtin-toolbar, .builtin-pager { align-items: stretch; }
      .builtin-toolbar-group { width: 100%; }
      .builtin-toolbar-group > * { flex: 1 1 auto; }
      .grid-view, .card-view { grid-template-columns: 1fr; }
    }
  `;

  constructor() {
    super();
    this.pageSize = 20;
    this.searchable = true;
    this.sortable = true;
    this.density = "normal";
    this.emptyText = "No data";
    this.keyField = "id";
    this.serverMode = false;
    this.totalItems = 0;
    this._items = [];
    this._selected = {};
    this._filters = {};
    this._sort = { key: "", direction: "" };
    this._page = 1;
    this._loading = false;
    this._error = "";
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.src) this.load();
  }

  async load(options = {}) {
    if (!this.src && !options.url) return [];
    this._loading = true;
    this._error = "";
    try {
      const response = await fetch(options.url || this.src, options.fetchOptions || {});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      const rows = Array.isArray(payload) ? payload : (payload.items || payload.data || payload.rows || []);
      this.setData(rows, { columns: options.columns, totalItems: options.totalItems ?? payload.total ?? payload.count ?? rows.length });
      this.dispatchEvent(new CustomEvent("builtin-load", { detail: { items: this._items, payload }, bubbles: true }));
      return this._items;
    } catch (error) {
      this._error = error && error.message ? error.message : String(error);
      this.dispatchEvent(new CustomEvent("builtin-error", { detail: { error }, bubbles: true }));
      return [];
    } finally {
      this._loading = false;
    }
  }

  refresh() {
    return this.load();
  }

  setData(items, options = {}) {
    this._items = Array.isArray(items) ? items.slice() : [];
    if (options.columns) this.columns = options.columns;
    if (options.totalItems !== undefined) this.totalItems = Number(options.totalItems) || 0;
    this._selected = {};
    this._page = 1;
  }

  setFilters(filters = {}) {
    this._filters = { ...filters };
    this._page = 1;
    this._emitFilterChange();
  }

  getSelectedRows() {
    return this._items.filter((item, index) => this._selected[this._rowId(item, index)]);
  }

  clearSelection() {
    this._selected = {};
  }

  exportCsv(filename = "data.csv") {
    const columns = this._visibleColumns();
    const rows = this.serverMode ? this._items : this._filteredSortedItems();
    const csv = [
      columns.map((column) => csvCell(column.label || column.key)).join(","),
      ...rows.map((row) => columns.map((column) => csvCell(this._formatCellText(row, column))).join(",")),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
    this.dispatchEvent(new CustomEvent("builtin-export", { detail: { filename, rows }, bubbles: true }));
  }

  _visibleColumns() {
    const cols = Array.isArray(this.columns) && this.columns.length ? this.columns : [];
    return normalizeColumns(cols, this._items[0]).filter((c) => !c.hidden);
  }

  _rowId(item, index) {
    return String(getByPath(item, this.keyField || "id", index));
  }

  _filteredSortedItems() {
    if (this.serverMode) return this._items.slice();
    const query = String(this._filters.search || "").trim().toLowerCase();
    const columns = this._visibleColumns();
    let rows = this._items.filter((item) => {
      if (!query) return true;
      return columns.some((column) => String(getByPath(item, column.key, "")).toLowerCase().includes(query));
    });
    Object.entries(this._filters).forEach(([key, value]) => {
      if (key === "search" || value === undefined || value === null || value === "") return;
      rows = rows.filter((item) => String(getByPath(item, key, "")) === String(value));
    });
    if (this._sort.key && this._sort.direction) {
      const direction = this._sort.direction === "desc" ? -1 : 1;
      rows = rows.slice().sort((a, b) => {
        const av = getByPath(a, this._sort.key, "");
        const bv = getByPath(b, this._sort.key, "");
        if (typeof av === "number" && typeof bv === "number") return (av - bv) * direction;
        return String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" }) * direction;
      });
    }
    return rows;
  }

  _getCellRawValue(row, column) {
    return typeof column.value === "function" ? column.value(row, column) : getByPath(row, column.key, "");
  }

  _formatCellValue(raw, column) {
    if (column.type === "date" && raw) return new Date(raw).toLocaleDateString();
    if (column.type === "datetime" && raw) return new Date(raw).toLocaleString();
    if (column.type === "boolean") return raw ? this._l("yes", "Yes") : this._l("no", "No");
    if (Array.isArray(raw)) return raw.join(", ");
    if (raw && typeof raw === "object") return JSON.stringify(raw);
    return String(raw ?? "");
  }

  _formatCellText(row, column) {
    const raw = this._getCellRawValue(row, column);
    if (typeof column.exportFormatter === "function") return String(column.exportFormatter(raw, row, column) ?? "");
    return this._formatCellValue(raw, column);
  }

  _renderCell(row, column, index) {
    const raw = this._getCellRawValue(row, column);
    let content = typeof column.formatter === "function" ? column.formatter(raw, row, column) : this._formatCellValue(raw, column);
    if (column.allowHtml && typeof content === "string") {
      content = unsafeHTML(content);
    }
    if (!column.slot) return content;
    return html`<slot name="${column.slot}-${this._rowId(row, index)}">${content}</slot>`;
  }

  _emitFilterChange() {
    this.dispatchEvent(new CustomEvent("builtin-filter", { detail: { filters: { ...this._filters } }, bubbles: true }));
    if (this.serverMode) {
      this.dispatchEvent(new CustomEvent("builtin-query-change", {
        detail: {
          filters: { ...this._filters },
          sort: { ...this._sort },
          page: this._page,
          pageSize: this.pageSize,
          totalItems: this.totalItems,
        },
        bubbles: true,
      }));
    }
  }

  _setPage(nextPage) {
    if (nextPage === this._page) return;
    this._page = nextPage;
    if (this.serverMode) this._emitFilterChange();
  }

  _pageRows() {
    const rows = this._filteredSortedItems();
    const ps = Math.max(Number(this.pageSize) || 20, 1);
    if (this.serverMode) {
      const total = Math.max(Number(this.totalItems) || 0, rows.length);
      const totalPages = Math.max(Math.ceil(total / ps), 1);
      const page = Math.min(Math.max(this._page || 1, 1), totalPages);
      return { rows, total, totalPages, page };
    }
    const totalPages = Math.max(Math.ceil(rows.length / ps), 1);
    const page = Math.min(Math.max(this._page || 1, 1), totalPages);
    const start = (page - 1) * ps;
    return { rows: rows.slice(start, start + ps), total: rows.length, totalPages, page };
  }

  _onSearchInput(e) {
    this._filters = { ...this._filters, search: e.target.value };
    this._page = 1;
    this._emitFilterChange();
  }

  _onSort(key) {
    const next = this._sort.key !== key ? "asc" : (this._sort.direction === "asc" ? "desc" : (this._sort.direction === "desc" ? "" : "asc"));
    this._sort = { key: next ? key : "", direction: next };
    this._page = 1;
    if (this.serverMode) this._emitFilterChange();
  }

  _toggleSelectAll(rows) {
    const allSelected = rows.length > 0 && rows.every((row, idx) => this._selected[this._rowId(row, idx)]);
    const next = { ...this._selected };
    rows.forEach((row, idx) => {
      const id = this._rowId(row, idx);
      if (allSelected) delete next[id];
      else next[id] = true;
    });
    this._selected = next;
    this.dispatchEvent(new CustomEvent("builtin-selection-change", { detail: { rows: this.getSelectedRows() }, bubbles: true }));
  }

  _toggleRow(row, index) {
    const id = this._rowId(row, index);
    const next = { ...this._selected };
    if (next[id]) delete next[id];
    else next[id] = true;
    this._selected = next;
    this.dispatchEvent(new CustomEvent("builtin-selection-change", { detail: { rows: this.getSelectedRows() }, bubbles: true }));
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _sortIcon(key) {
    if (this._sort.key !== key) {
      return html`<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 15l5 5 5-5M7 9l5-5 5 5"/></svg>`;
    }
    if (this._sort.direction === "asc") {
      return html`<builtin-icon name="up" size="20" variant="outlined"></builtin-icon>`;
    }
    return html`<builtin-icon name="down" size="20" variant="outlined"></builtin-icon>`;
  }

  _renderStatus(rows) {
    if (this._loading) return html`<div class="builtin-status">${this._l("loading", "Loading...")}</div>`;
    if (this._error) return html`<div class="builtin-status builtin-error">${this._error}</div>`;
    if (!this._loading && !this._error && rows.length === 0) return html`<div class="builtin-status">${this.emptyText || this._l("noData", "No data")}</div>`;
    return null;
  }

  _renderTable(columns, rows, total, totalPages, page) {
    const allSelected = rows.length > 0 && rows.every((row, idx) => this._selected[this._rowId(row, idx)]);
    return html`
      <div class="builtin-table-wrap">
        <table>
          <thead>
            <tr>
              ${this.selectable ? html`<th style="width:42px;"><input type="checkbox" .checked=${allSelected} @change=${() => this._toggleSelectAll(rows)}></th>` : null}
              ${columns.map((column) => html`
                <th style=${column.width ? styleMap({ width: column.width }) : ""}>
                  ${this.sortable && column.sortable !== false
                    ? html`<button class="builtin-sort" @click=${() => this._onSort(column.key)}>${column.label || column.key} ${this._sortIcon(column.key)}</button>`
                    : (column.label || column.key)}
                </th>
              `)}
              <slot name="head-extra"></slot>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row, index) => html`
              <tr data-clickable="true" @click=${() => this.dispatchEvent(new CustomEvent("builtin-row-click", { detail: { row }, bubbles: true }))}>
                ${this.selectable ? html`<td @click=${(e) => e.stopPropagation()}><input type="checkbox" .checked=${!!this._selected[this._rowId(row, index)]} @change=${() => this._toggleRow(row, index)}></td>` : null}
                ${columns.map((column) => html`<td class="${column.truncate ? "builtin-cell-truncate" : ""}" style=${column.align ? styleMap({ textAlign: column.align }) : ""}>${this._renderCell(row, column, index)}</td>`)}
              </tr>
            `)}
          </tbody>
        </table>
      </div>
      ${this._renderStatus(rows)}
      <div class="builtin-pager">
        <span class="builtin-muted">${total} ${this._l("rows", "rows")} · ${this._l("page", "page")} ${page} / ${totalPages}</span>
        <div class="builtin-actions">
          <button ?disabled=${page <= 1} @click=${() => this._setPage(page - 1)}>${this._l("previous", "Previous")}</button>
          <button ?disabled=${page >= totalPages} @click=${() => this._setPage(page + 1)}>${this._l("next", "Next")}</button>
        </div>
      </div>
    `;
  }

  _renderGrid(columns, rows, total, totalPages, page) {
    return html`
      <div class="grid-view">
        ${rows.map((row, index) => html`
          <div class="grid-item" @click=${() => this.dispatchEvent(new CustomEvent("builtin-row-click", { detail: { row }, bubbles: true }))}>
            ${this.selectable ? html`<div style="text-align:right;margin-bottom:6px;"><input type="checkbox" .checked=${!!this._selected[this._rowId(row, index)]} @change=${() => this._toggleRow(row, index)} @click=${(e) => e.stopPropagation()}></div>` : null}
            ${columns.map((column) => html`
              <div class="item-row">
                <span class="item-key">${column.label || column.key}</span>
                <span class="item-val">${this._renderCell(row, column, index)}</span>
              </div>
            `)}
          </div>
        `)}
      </div>
      ${this._renderStatus(rows)}
      <div class="builtin-pager">
        <span class="builtin-muted">${total} ${this._l("rows", "rows")} · ${this._l("page", "page")} ${page} / ${totalPages}</span>
        <div class="builtin-actions">
          <button ?disabled=${page <= 1} @click=${() => this._setPage(page - 1)}>${this._l("previous", "Previous")}</button>
          <button ?disabled=${page >= totalPages} @click=${() => this._setPage(page + 1)}>${this._l("next", "Next")}</button>
        </div>
      </div>
    `;
  }

  _renderCards(columns, rows, total, totalPages, page) {
    return html`
      <div class="card-view">
        ${rows.map((row, index) => html`
          <div class="card-item" @click=${() => this.dispatchEvent(new CustomEvent("builtin-row-click", { detail: { row }, bubbles: true }))}>
            <div class="card-header">
              <strong>${columns[0] ? this._renderCell(row, columns[0], index) : this._rowId(row, index)}</strong>
              ${this.selectable ? html`<input type="checkbox" .checked=${!!this._selected[this._rowId(row, index)]} @change=${() => this._toggleRow(row, index)} @click=${(e) => e.stopPropagation()}>` : null}
            </div>
            ${columns.slice(1).map((column) => html`
              <div class="item-row">
                <span class="item-key">${column.label || column.key}</span>
                <span class="item-val">${this._renderCell(row, column, index)}</span>
              </div>
            `)}
          </div>
        `)}
      </div>
      ${this._renderStatus(rows)}
      <div class="builtin-pager">
        <span class="builtin-muted">${total} ${this._l("rows", "rows")} · ${this._l("page", "page")} ${page} / ${totalPages}</span>
        <div class="builtin-actions">
          <button ?disabled=${page <= 1} @click=${() => this._setPage(page - 1)}>${this._l("previous", "Previous")}</button>
          <button ?disabled=${page >= totalPages} @click=${() => this._setPage(page + 1)}>${this._l("next", "Next")}</button>
        </div>
      </div>
    `;
  }

  _effectiveView() {
    const v = this.view || "table";
    if (this._ptMobile && v === "table") return "cards";
    return v;
  }

  render() {
    const columns = this._visibleColumns();
    const { rows, total, totalPages, page } = this._pageRows();
    const densityClass = this.density === "compact" ? "builtin-density-compact" : (this.density === "comfortable" ? "builtin-density-comfortable" : "");
    const effectiveView = this._effectiveView();
    return html`
      <div class="${densityClass}">
        <div class="builtin-toolbar">
          <div class="builtin-toolbar-group">
            ${this.searchable ? html`<input type="search" placeholder="${this._l("search", "Search")}" .value=${this._filters.search || ""} @input=${this._onSearchInput}>` : null}
            <slot name="filters"></slot>
          </div>
          <div class="builtin-toolbar-group">
            <button @click=${this.refresh}>${this._l("refresh", "Refresh")}</button>
            <button @click=${() => this.exportCsv()}>${this._l("exportCsv", "Export CSV")}</button>
            <slot name="actions"></slot>
          </div>
        </div>
        <div class="builtin-surface">
          ${effectiveView === "table" ? this._renderTable(columns, rows, total, totalPages, page)
            : effectiveView === "grid" ? this._renderGrid(columns, rows, total, totalPages, page)
            : this._renderCards(columns, rows, total, totalPages, page)}
        </div>
      </div>
    `;
  }
}
