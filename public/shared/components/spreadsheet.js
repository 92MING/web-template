/**
 * @fileoverview BuiltinSpreadsheet — Editable spreadsheet with basic formulas and XLSX import/export.
 *
 * @attr {string} data — JSON 2D array of values.
 * @attr {string} columns — JSON array of header strings.
 * @attr {string} labels — JSON i18n overrides.
 * @attr {string} mode — `default` | `compact` (default `default`).
 *
 * @event builtin-change — `{ data }`
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinSpreadsheet extends BuiltinBaseElement {
  static properties = {
    data: { type: Array },
    columns: { type: Array },
    labels: { type: Object },
    mode: { type: String },
    _activeCell: { type: Object, state: true },
    _editValue: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .sheet { border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-surface, #ffffff); }
    .toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); flex-wrap: wrap; }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 10px; border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-surface, #ffffff); border-radius: var(--builtin-radius, 6px); cursor: pointer; color: var(--builtin-color-text, #111827); min-height: 32px; }
    .btn:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .btn.primary { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .table-wrap { overflow: auto; max-height: 70vh; }
    table { border-collapse: collapse; width: max-content; min-width: 100%; }
    th, td { border: 1px solid var(--builtin-border-soft, #e5e7eb); padding: 6px 8px; min-width: 80px; font-size: 13px; vertical-align: top; }
    th { background: var(--builtin-header-bg, #f9fafb); font-weight: 650; color: var(--builtin-color-muted, #374151); position: sticky; top: 0; z-index: 1; }
    td { background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); }
    td.active { outline: 2px solid var(--builtin-primary, #2563eb); outline-offset: -2px; }
    td input { width: 100%; border: none; outline: none; background: transparent; font: inherit; padding: 0; color: inherit; }
    .row-header { background: var(--builtin-header-bg, #f9fafb); font-weight: 600; color: var(--builtin-color-muted, #6b7280); text-align: center; min-width: 36px; }
    .formula-bar { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); background: var(--builtin-bg-subtle, #f3f4f6); }
    .formula-bar input { flex: 1; padding: 4px 8px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); }
    .hidden-input { position: absolute; left: -9999px; }
    @media (max-width: 720px) {
      .toolbar { padding: 6px; }
      th, td { min-width: 64px; padding: 8px 10px; font-size: 14px; }
      .table-wrap { max-height: none; }
    }
  `;

  constructor() {
    super();
    this.data = [];
    this.columns = [];
    this.mode = "default";
    this._activeCell = null;
    this._editValue = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this._ensureData();
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _ensureData() {
    if (!Array.isArray(this.data) || this.data.length === 0) {
      this.data = Array.from({ length: 10 }, () => Array(5).fill(""));
    }
    if (!Array.isArray(this.columns) || this.columns.length === 0) {
      this.columns = this.data[0].map((_, i) => this._colName(i));
    }
  }

  _colName(index) {
    let name = "";
    let n = index;
    do {
      name = String.fromCharCode(65 + (n % 26)) + name;
      n = Math.floor(n / 26) - 1;
    } while (n >= 0);
    return name;
  }

  _colIndex(name) {
    let idx = 0;
    for (let i = 0; i < name.length; i++) {
      idx = idx * 26 + (name.charCodeAt(i) - 64);
    }
    return idx - 1;
  }

  _cellRef(ref) {
    const m = ref.match(/^([A-Z]+)(\d+)$/);
    if (!m) return null;
    return { col: this._colIndex(m[1]), row: parseInt(m[2], 10) - 1 };
  }

  _getValue(row, col) {
    const rows = this.data || [];
    if (row < 0 || row >= rows.length) return "";
    const r = rows[row];
    if (!Array.isArray(r) || col < 0 || col >= r.length) return "";
    return r[col];
  }

  _evalCell(row, col, visited = new Set()) {
    const key = `${row},${col}`;
    if (visited.has(key)) return "#CYCLE";
    visited.add(key);
    const raw = String(this._getValue(row, col) ?? "").trim();
    if (!raw.startsWith("=")) return raw;
    const expr = raw.slice(1);
    return this._evalExpr(expr, visited);
  }

  _evalExpr(expr, visited) {
    expr = expr.trim();
    const rangeMatch = expr.match(/^(SUM|AVERAGE|MAX|MIN)\s*\(([^)]+)\)$/i);
    if (rangeMatch) {
      const fn = rangeMatch[1].toUpperCase();
      const range = rangeMatch[2];
      const values = this._rangeValues(range, visited);
      const nums = values.map((v) => parseFloat(v)).filter((n) => !isNaN(n));
      if (nums.length === 0) return "#VALUE";
      if (fn === "SUM") return nums.reduce((a, b) => a + b, 0);
      if (fn === "AVERAGE") return nums.reduce((a, b) => a + b, 0) / nums.length;
      if (fn === "MAX") return Math.max(...nums);
      if (fn === "MIN") return Math.min(...nums);
    }
    const cellMatch = expr.match(/^([A-Z]+\d+)$/);
    if (cellMatch) {
      const ref = this._cellRef(cellMatch[1]);
      if (!ref) return "#REF";
      return this._evalCell(ref.row, ref.col, visited);
    }
    try {
      const safeExpr = expr.replace(/([A-Z]+\d+)(?::([A-Z]+\d+))?/g, (match, start, end) => {
        if (end) return this._rangeValues(match, visited).join(",");
        const ref = this._cellRef(start);
        if (!ref) return "0";
        const v = this._evalCell(ref.row, ref.col, visited);
        const n = parseFloat(v);
        return isNaN(n) ? (v ? `"${v}"` : "0") : String(n);
      });
      const result = new Function("return (" + safeExpr + ")")();
      return result ?? "";
    } catch (_e) {
      return "#ERROR";
    }
  }

  _rangeValues(range, visited) {
    const parts = range.split(":");
    if (parts.length !== 2) return [];
    const start = this._cellRef(parts[0]);
    const end = this._cellRef(parts[1]);
    if (!start || !end) return [];
    const values = [];
    for (let r = Math.min(start.row, end.row); r <= Math.max(start.row, end.row); r++) {
      for (let c = Math.min(start.col, end.col); c <= Math.max(start.col, end.col); c++) {
        values.push(this._evalCell(r, c, new Set(visited)));
      }
    }
    return values;
  }

  _displayValue(row, col) {
    return this._evalCell(row, col);
  }

  _onCellClick(row, col) {
    this._activeCell = { row, col };
    this._editValue = String(this._getValue(row, col) ?? "");
  }

  _onCellDblClick(row, col) {
    this._activeCell = { row, col, editing: true };
    this._editValue = String(this._getValue(row, col) ?? "");
    this.updateComplete.then(() => {
      const input = this.shadowRoot.querySelector(".active input");
      if (input) input.focus();
    });
  }

  _commitEdit() {
    if (!this._activeCell) return;
    const { row, col } = this._activeCell;
    const rows = this.data.map((r) => r.slice());
    if (!rows[row]) rows[row] = [];
    rows[row][col] = this._editValue;
    this.data = rows;
    this._activeCell = { ...this._activeCell, editing: false };
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { data: this.data }, bubbles: true }));
  }

  _onKeyDown(e, row, col) {
    if (e.key === "Enter") {
      e.preventDefault();
      this._commitEdit();
      this._onCellClick(Math.min(row + 1, this.data.length - 1), col);
    } else if (e.key === "Tab") {
      e.preventDefault();
      this._commitEdit();
      this._onCellClick(row, Math.min(col + 1, (this.columns || []).length - 1));
    } else if (e.key === "Escape") {
      this._activeCell = { row, col, editing: false };
      this._editValue = String(this._getValue(row, col) ?? "");
    }
  }

  _addRow() {
    const cols = Math.max((this.columns || []).length, (this.data[0] || []).length);
    this.data = [...this.data, Array(cols).fill("")];
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { data: this.data }, bubbles: true }));
  }

  _addCol() {
    const newCol = this._colName((this.columns || []).length);
    this.columns = [...(this.columns || []), newCol];
    this.data = this.data.map((row) => [...row, ""]);
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { data: this.data }, bubbles: true }));
  }

  async _importXlsx() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".xlsx,.xls,.csv";
    input.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      await this._loadXlsx();
      if (!window.XLSX) return;
      const data = await file.arrayBuffer();
      const workbook = window.XLSX.read(data, { type: "array" });
      const first = workbook.Sheets[workbook.SheetNames[0]];
      const json = window.XLSX.utils.sheet_to_json(first, { header: 1 });
      if (json.length > 0) {
        this.columns = json[0].map((c, i) => String(c || this._colName(i)));
        this.data = json.slice(1);
        this.dispatchEvent(new CustomEvent("builtin-change", { detail: { data: this.data }, bubbles: true }));
      }
    };
    input.click();
  }

  async _exportXlsx() {
    await this._loadXlsx();
    if (!window.XLSX) return;
    const ws = window.XLSX.utils.aoa_to_sheet([this.columns, ...this.data]);
    const wb = window.XLSX.utils.book_new();
    window.XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
    window.XLSX.writeFile(wb, "spreadsheet.xlsx");
  }

  async _loadXlsx() {
    if (window.XLSX) return;
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/vendor/xlsx/xlsx.full.min.js";
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  render() {
    this._ensureData();
    const cols = this.columns || [];
    const rows = this.data || [];
    const activeKey = this._activeCell ? `${this._activeCell.row}-${this._activeCell.col}` : "";
    return html`
      <div class="sheet">
        <div class="toolbar">
          <button class="btn" @click=${this._importXlsx}>
            <builtin-icon name="upload" size="20" variant="outlined"></builtin-icon>
            ${this._l("import", "Import")}
          </button>
          <button class="btn primary" @click=${this._exportXlsx}>
            <builtin-icon name="download" size="20" variant="outlined"></builtin-icon>
            ${this._l("export", "Export")}
          </button>
          <button class="btn" @click=${this._addRow}>+ ${this._l("row", "Row")}</button>
          <button class="btn" @click=${this._addCol}>+ ${this._l("column", "Column")}</button>
          <slot name="toolbar"></slot>
        </div>
        <div class="formula-bar">
          <span>${this._activeCell ? `${this._colName(this._activeCell.col)}${this._activeCell.row + 1}` : ""}</span>
          <input type="text" placeholder=${this._l("formula", "Formula")}
            .value=${this._activeCell && this._activeCell.editing ? this._editValue : (this._activeCell ? this._displayValue(this._activeCell.row, this._activeCell.col) : "")}
            @input=${(e) => { if (this._activeCell?.editing) this._editValue = e.target.value; }}
            @keydown=${(e) => { if (e.key === "Enter") this._commitEdit(); }}
            ?disabled=${!this._activeCell}>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th class="row-header"></th>
                ${cols.map((c) => html`<th>${c}</th>`)}
              </tr>
            </thead>
            <tbody>
              ${rows.map((row, rIdx) => html`
                <tr>
                  <td class="row-header">${rIdx + 1}</td>
                  ${cols.map((_, cIdx) => {
                    const isActive = activeKey === `${rIdx}-${cIdx}`;
                    const isEditing = isActive && this._activeCell?.editing;
                    return html`
                      <td class="${isActive ? "active" : ""}" @click=${() => this._onCellClick(rIdx, cIdx)} @dblclick=${() => this._onCellDblClick(rIdx, cIdx)}>
                        ${isEditing
                          ? html`<input type="text" .value=${this._editValue}
                              @input=${(e) => this._editValue = e.target.value}
                              @keydown=${(e) => this._onKeyDown(e, rIdx, cIdx)}
                              @blur=${this._commitEdit}>`
                          : html`<span>${this._displayValue(rIdx, cIdx)}</span>`}
                      </td>
                    `;
                  })}
                </tr>
              `)}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }
}
