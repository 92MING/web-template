import { BuiltinBaseElement, html, css, repeat } from "../lit-base.js";

export class BuiltinSpreadsheet extends BuiltinBaseElement {
  static properties = {
    data: { type: Array },
    columns: { type: Array },
    labels: { type: Object },
    mode: { type: String },
  };

  static styles = css`
    :host { display: block; }
    .sheet {
      height: var(--builtin-spreadsheet-height, 360px);
      min-height: 260px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      overflow: auto;
    }
    table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; font-size: 13px; }
    th, td { min-width: 120px; border-right: 1px solid var(--builtin-border-soft, #e5e7eb); border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    th {
      position: sticky;
      top: 0;
      z-index: 2;
      height: 34px;
      padding: 0 10px;
      background: var(--builtin-header-bg, #f9fafb);
      color: var(--builtin-color-muted, #6b7280);
      text-align: left;
      font-weight: 650;
    }
    td { height: 34px; padding: 0; background: var(--builtin-surface, #ffffff); }
    .cell {
      min-height: 34px;
      padding: 8px 10px;
      box-sizing: border-box;
      outline: none;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .cell:focus {
      position: relative;
      box-shadow: inset 0 0 0 2px var(--builtin-primary, #2563eb);
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 8%, var(--builtin-surface, #ffffff));
    }
    .row-head {
      position: sticky;
      left: 0;
      z-index: 1;
      width: 44px;
      min-width: 44px;
      background: var(--builtin-header-bg, #f9fafb);
      color: var(--builtin-color-muted, #6b7280);
      text-align: center;
      font-variant-numeric: tabular-nums;
    }
    th.row-head { z-index: 3; }
    .toolbar {
      position: sticky;
      bottom: 0;
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      padding: 8px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-surface, #ffffff);
    }
    button {
      min-height: 30px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      padding: 0 10px;
    }
    button:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
  `;

  constructor() {
    super();
    this.data = [];
    this.columns = [];
    this.mode = "default";
    this.labels = {};
  }

  _l(key, fallback = "") { return this.labels?.[key] ?? this._t(key) ?? fallback; }

  _columns() {
    if (Array.isArray(this.columns) && this.columns.length) {
      return this.columns.map((column, index) => {
        if (typeof column === "string") return { key: String(index), label: column, index };
        const key = column.field || column.key || String(index);
        return { key, label: column.label || column.title || key, index };
      });
    }
    const first = this.data?.[0];
    if (first && !Array.isArray(first) && typeof first === "object") {
      return Object.keys(first).map((key, index) => ({ key, label: key, index }));
    }
    const width = Math.max(4, ...(this.data || []).map((row) => Array.isArray(row) ? row.length : 0));
    return Array.from({ length: width }, (_, index) => ({ key: String(index), label: this._columnName(index), index }));
  }

  _rows() { return Array.isArray(this.data) && this.data.length ? this.data : Array.from({ length: 8 }, () => []); }

  _value(row, column) {
    if (Array.isArray(row)) return row[column.index] ?? "";
    if (row && typeof row === "object") return row[column.key] ?? "";
    return "";
  }

  _setCell(rowIndex, column, value) {
    const rows = this._rows().map((row) => Array.isArray(row) ? row.slice() : { ...(row || {}) });
    const row = rows[rowIndex] || [];
    if (Array.isArray(row)) row[column.index] = value;
    else row[column.key] = value;
    rows[rowIndex] = row;
    this.data = rows;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { data: this.data }, bubbles: true, composed: true }));
  }

  _addRow() {
    const columns = this._columns();
    const isObject = this.data?.[0] && !Array.isArray(this.data[0]) && typeof this.data[0] === "object";
    const row = isObject ? Object.fromEntries(columns.map((column) => [column.key, ""])) : Array.from({ length: columns.length }, () => "");
    this.data = [...(this.data || []), row];
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { data: this.data }, bubbles: true, composed: true }));
  }

  _columnName(index) {
    let name = "";
    let value = index;
    do {
      name = String.fromCharCode(65 + (value % 26)) + name;
      value = Math.floor(value / 26) - 1;
    } while (value >= 0);
    return name;
  }

  render() {
    const columns = this._columns();
    const rows = this._rows();
    return html`
      <div class="sheet">
        <table>
          <thead><tr><th class="row-head">#</th>${columns.map((column) => html`<th>${column.label}</th>`)}</tr></thead>
          <tbody>
            ${repeat(rows, (_row, index) => index, (row, rowIndex) => html`
              <tr>
                <td class="row-head">${rowIndex + 1}</td>
                ${columns.map((column) => html`
                  <td><div class="cell" contenteditable="true" @blur=${(event) => this._setCell(rowIndex, column, event.currentTarget.textContent || "")}>${this._value(row, column)}</div></td>
                `)}
              </tr>
            `)}
          </tbody>
        </table>
        <div class="toolbar"><button @click=${this._addRow}>${this._l("spreadsheet.addRow", "Add row")}</button></div>
      </div>
    `;
  }
}