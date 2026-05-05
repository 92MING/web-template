/**
 * @fileoverview BuiltinFileBrowserCloud — Google Drive-like cloud file browser.
 *
 * @attr {string} items — JSON array of {id, name, type, size, modified, thumbnail, shared}.
 * @attr {string} view — 'grid' | 'list'.
 * @attr {string} sortBy — 'name' | 'date' | 'size'.
 * @attr {boolean} sortDesc — Sort descending.
 * @attr {string} currentPath — JSON array of folder names.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-navigate — Detail: { id }.
 * @event builtin-select — Detail: { ids }.
 * @event builtin-open — Detail: { id }.
 * @event builtin-action — Detail: { action, ids }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

export class BuiltinFileBrowserCloud extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
    view: { type: String },
    sortBy: { type: String, attribute: "sort-by" },
    sortDesc: { type: Boolean, attribute: "sort-desc" },
    currentPath: { type: Array, attribute: "current-path" },
    rootName: { type: String, attribute: "root-name" },
    hideToolbar: { type: Boolean, attribute: "hide-toolbar" },
    labels: { type: Object },
    _selected: { type: Set, state: true },
  };

  static styles = css`
    :host { display: block; }
    .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
    .toolbar-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .breadcrumb { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--builtin-color-muted, #6b7280); }
    .breadcrumb a { color: var(--builtin-primary, #2563eb); text-decoration: none; cursor: pointer; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }
    .list { display: flex; flex-direction: column; gap: 4px; }
    .item {
      border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff); cursor: pointer; position: relative; overflow: hidden;
      transition: box-shadow .12s ease;
    }
    .item:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
    .item.selected { border-color: var(--builtin-primary, #2563eb); background: rgba(37,99,235,0.04); }
    .grid .item { padding: 12px; text-align: center; }
    .list .item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; }
    .thumb { width: 48px; height: 48px; border-radius: var(--builtin-radius, 6px); background: var(--builtin-header-bg, #f9fafb); display: inline-flex; align-items: center; justify-content: center; overflow: hidden; }
    .grid .thumb { width: 64px; height: 64px; margin-bottom: 8px; }
    .thumb img { width: 100%; height: 100%; object-fit: cover; }
    .name { font-size: 13px; color: var(--builtin-color-text, #111827); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .meta { font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .grid .checkbox { position: absolute; top: 6px; left: 6px; }
    .list .checkbox { position: static; }
    .item { transition: box-shadow .12s ease, background .12s ease; }
    .actions-bar { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
    .toolbar button,
    .toolbar select,
    .actions-bar button {
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      min-height: 32px; padding: 0 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      font: inherit; font-size: 13px; font-weight: 600;
      cursor: pointer;
      transition: background .15s ease, border-color .15s ease, color .15s ease;
    }
    .toolbar button:hover,
    .toolbar select:hover,
    .actions-bar button:hover {
      background: var(--builtin-header-bg, #f3f4f6);
      border-color: var(--builtin-primary, #2563eb);
      color: var(--builtin-primary, #2563eb);
    }
    @media (max-width: 720px) {
      .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.view = "grid";
    this.sortBy = "name";
    this.sortDesc = false;
    this.currentPath = [];
    this.rootName = "";
    this.hideToolbar = false;
    this.labels = {};
    this._selected = new Set();
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _sortedItems() {
    const list = [...(this.items || [])];
    const map = { name: (a, b) => (a.name || "").localeCompare(b.name || ""), date: (a, b) => (a.modified || "").localeCompare(b.modified || ""), size: (a, b) => (a.size || 0) - (b.size || 0) };
    const cmp = map[this.sortBy] || map.name;
    list.sort((a, b) => this.sortDesc ? cmp(b, a) : cmp(a, b));
    return list;
  }

  _toggleSelect(id, e) {
    if (e) e.stopPropagation();
    const next = new Set(this._selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this._selected = next;
    this.dispatchEvent(new CustomEvent("builtin-select", { bubbles: true, composed: true, detail: { ids: Array.from(next) } }));
  }

  _onOpen(item) {
    if (item.type === "folder") {
      this.dispatchEvent(new CustomEvent("builtin-navigate", { bubbles: true, composed: true, detail: { id: item.id } }));
    } else {
      this.dispatchEvent(new CustomEvent("builtin-open", { bubbles: true, composed: true, detail: { id: item.id } }));
    }
  }

  _action(name) {
    this.dispatchEvent(new CustomEvent("builtin-action", { bubbles: true, composed: true, detail: { action: name, ids: Array.from(this._selected) } }));
  }

  _fmtSize(b) {
    if (!b) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
    return `${b.toFixed(1)} ${units[i]}`;
  }

  render() {
    const items = this._sortedItems();
    const path = Array.isArray(this.currentPath) ? this.currentPath : [];
    const isList = this.view === "list";
    const rootLabel = this.rootName || this._l("file.root", "My Drive");
    return html`
      ${!this.hideToolbar ? html`
        <div class="toolbar">
          <div class="toolbar-group">
            <div class="breadcrumb">
              <a @click="${() => this.dispatchEvent(new CustomEvent('builtin-navigate', { bubbles:true, composed:true, detail:{id:null} }))}">${rootLabel}</a>
              ${path.map((p) => html`<span>/</span><span>${p}</span>`)}
            </div>
          </div>
          <div class="toolbar-group">
            <button @click="${() => this._action('newfolder')}">${this._l("file.newFolder", "New Folder")}</button>
            <button @click="${() => this._action('upload')}">${this._l("file.upload", "Upload")}</button>
            <select @change="${(e) => { this.sortBy = e.target.value; }}">
              <option value="name" ?selected="${this.sortBy==='name'}">${this._l("file.name", "Name")}</option>
              <option value="date" ?selected="${this.sortBy==='date'}">${this._l("file.date", "Date")}</option>
              <option value="size" ?selected="${this.sortBy==='size'}">${this._l("file.size", "Size")}</option>
            </select>
            <button @click="${() => this.sortDesc = !this.sortDesc}">${this.sortDesc ? "↓" : "↑"}</button>
            <button @click="${() => this.view = this.view === 'grid' ? 'list' : 'grid'}">${this.view === 'grid' ? '☰' : '⊞'}</button>
          </div>
        </div>
      ` : ""}
      <div class="${isList ? 'list' : 'grid'}">
        ${items.map((it) => {
          const sel = this._selected.has(it.id);
          return html`
            <div class="item ${classMap({ selected: sel })}" @click="${() => this._onOpen(it)}">
              <input type="checkbox" class="checkbox" .checked="${sel}" @click="${(e) => this._toggleSelect(it.id, e)}" />
              <div class="thumb">
                ${it.thumbnail ? html`<img src="${it.thumbnail}" alt="" />` : html`<builtin-icon name="${it.type==='folder'?'folder':'file'}" size="24" variant="outlined"></builtin-icon>`}
              </div>
              <div style="min-width:0;flex:1;">
                <div class="name">${it.name}</div>
                ${isList ? html`<div class="meta">${this._fmtSize(it.size)} · ${it.modified || ''}${it.shared ? ' · Shared' : ''}</div>` : ""}
              </div>
            </div>
          `;
        })}
      </div>
      ${this._selected.size ? html`
        <div class="actions-bar">
          <button @click="${() => this._action('download')}">${this._l("file.download", "Download")}</button>
          <button @click="${() => this._action('rename')}">${this._l("file.rename", "Rename")}</button>
          <button @click="${() => this._action('delete')}">${this._l("file.delete", "Delete")}</button>
          <button @click="${() => this._action('share')}">${this._l("file.share", "Share")}</button>
        </div>
      ` : ""}
    `;
  }
}
