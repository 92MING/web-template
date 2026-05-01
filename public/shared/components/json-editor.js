/**
 * @fileoverview BuiltinJsonEditor — Tree/code/view JSON editor with expandable nodes.
 *
 * @element builtin-json-editor
 *
 * @attr {Object|string} value — JSON value or JSON string.
 * @attr {string} mode — `tree` | `code` | `view`. Default `tree`.
 * @attr {Object} labels — i18n overrides.
 *
 * @event builtin-change — Fired on edit. Detail: `{ value }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinJsonEditor extends BuiltinBaseElement {
  static properties = {
    value: { type: Object },
    mode: { type: String },
    labels: { type: Object },
    _expanded: { type: Object, state: true },
    _editPath: { type: String, state: true },
    _editValue: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .toolbar {
      display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
      margin-bottom: 8px;
    }
    .toolbar button {
      min-height: 32px; padding: 0 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      border-radius: var(--builtin-radius, 6px); cursor: pointer;
    }
    .toolbar button.active {
      background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff;
    }
    .view-wrap {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      overflow: auto; min-height: 200px; max-height: 70vh;
    }
    .tree { padding: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 13px; }
    .node { display: flex; align-items: center; gap: 6px; padding: 3px 0; flex-wrap: wrap; }
    .node:hover { background: var(--builtin-row-hover-bg, #f9fafb); border-radius: 4px; }
    .indent { display: inline-block; width: 18px; flex-shrink: 0; }
    .key { color: var(--builtin-color-text, #111827); font-weight: 600; }
    .sep { color: var(--builtin-color-muted, #6b7280); }
    .value-string { color: #0f766e; }
    .value-number { color: #1d4ed8; }
    .value-boolean { color: #b45309; }
    .value-null { color: var(--builtin-color-muted, #6b7280); font-style: italic; }
    .expand {
      display: inline-flex; align-items: center; justify-content: center;
      width: 18px; height: 18px; cursor: pointer; flex-shrink: 0;
      color: var(--builtin-color-muted, #6b7280);
    }
    .actions {
      display: inline-flex; align-items: center; gap: 4px; margin-left: auto; opacity: 0;
    }
    .node:hover .actions { opacity: 1; }
    .actions button {
      min-height: 22px; min-width: 22px; padding: 0;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      border-radius: var(--builtin-radius, 6px); cursor: pointer;
      display: inline-flex; align-items: center; justify-content: center;
    }
    .type-icon { display: inline-flex; align-items: center; }
    .bracket { color: var(--builtin-color-muted, #6b7280); }
    .count { color: var(--builtin-color-muted, #6b7280); font-size: 12px; }
    textarea.code {
      width: 100%; min-height: 240px; border: 0; padding: 12px;
      background: var(--builtin-input-bg, #ffffff); color: inherit;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px; line-height: 1.5; resize: vertical; outline: none;
    }
    pre.code {
      margin: 0; padding: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px; line-height: 1.5;
      white-space: pre-wrap; word-break: break-word;
    }
    .inline-input {
      border: 1px solid var(--builtin-primary, #2563eb); border-radius: 4px;
      padding: 2px 6px; font: inherit; min-height: 0;
      background: var(--builtin-input-bg, #ffffff); color: inherit;
    }
    @media (max-width: 720px) {
      .tree { font-size: 15px; }
      .actions { opacity: 1 !important; }
      .actions button { min-height: 32px; min-width: 32px; }
      .node { padding: 6px 0; }
    }
  `;

  constructor() {
    super();
    this.value = {};
    this.mode = "tree";
    this._expanded = new Set();
    this._editPath = "";
    this._editValue = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this._normalizeValue();
  }

  willUpdate(changed) {
    if (changed.has("value")) {
      this._normalizeValue();
    }
  }

  _normalizeValue() {
    if (typeof this.value === "string") {
      try { this.value = JSON.parse(this.value); } catch (_e) { this.value = {}; }
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _getValue() {
    return this.value ?? {};
  }

  _typeOf(v) {
    if (v === null) return "null";
    if (Array.isArray(v)) return "array";
    return typeof v;
  }

  _toggle(path) {
    const next = new Set(this._expanded);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    this._expanded = next;
  }

  _setValue(nextValue) {
    this.value = nextValue;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true }));
  }

  _updateAt(path, updater) {
    const parts = String(path).split(".");
    const next = JSON.parse(JSON.stringify(this._getValue()));
    let cur = next;
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts[i];
      const idx = Number(p);
      cur = Number.isNaN(idx) ? cur[p] : cur[idx];
    }
    const last = parts[parts.length - 1];
    const idx = Number(last);
    const key = Number.isNaN(idx) ? last : idx;
    cur[key] = typeof updater === "function" ? updater(cur[key]) : updater;
    this._setValue(next);
  }

  _deleteAt(path) {
    const parts = String(path).split(".");
    const next = JSON.parse(JSON.stringify(this._getValue()));
    let cur = next;
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts[i];
      const idx = Number(p);
      cur = Number.isNaN(idx) ? cur[p] : cur[idx];
    }
    const last = parts[parts.length - 1];
    const idx = Number(last);
    if (Number.isNaN(idx)) delete cur[last];
    else cur.splice(idx, 1);
    this._setValue(next);
  }

  _addAt(path, type = "string") {
    const val = type === "object" ? {} : type === "array" ? [] : "";
    if (!path) {
      this._setValue(val);
      return;
    }
    this._updateAt(path, (existing) => {
      if (Array.isArray(existing)) return [...existing, val];
      if (existing && typeof existing === "object") {
        const key = this._l("newKey", "newKey");
        return { ...existing, [key]: val };
      }
      return val;
    });
  }

  _startEdit(path, value) {
    this._editPath = path;
    this._editValue = JSON.stringify(value);
  }

  _commitEdit() {
    if (!this._editPath) return;
    let parsed;
    try { parsed = JSON.parse(this._editValue); } catch (_e) { parsed = this._editValue; }
    this._updateAt(this._editPath, parsed);
    this._editPath = "";
    this._editValue = "";
  }

  _cancelEdit() {
    this._editPath = "";
    this._editValue = "";
  }

  _typeIcon(type) {
    const icons = {
      string: html`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>`,
      number: html`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="20" x2="8" y2="10"/><line x1="20" y1="20" x2="16" y2="10"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
      boolean: html`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="M8 12l3 3 5-5"/></svg>`,
      null: html`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="8" y1="15" x2="16" y2="15"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>`,
      object: html`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>`,
      array: html`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="12" y1="8" x2="12" y2="16"/></svg>`,
    };
    return html`<span class="type-icon">${icons[type] || ""}</span>`;
  }

  _renderTreeNode(value, path, depth = 0) {
    const type = this._typeOf(value);
    const isContainer = type === "object" || type === "array";
    const expanded = this._expanded.has(path);
    const isEditing = this._editPath === path;
    const indent = Array.from({ length: depth }, () => html`<span class="indent"></span>`);

    const keyEl = (k) => html`<span class="key">${k}</span>`;
    const actions = html`
      <span class="actions">
        ${isContainer ? html`
          <button title="${this._l("add", "Add")}" @click=${() => this._addAt(path, "string")}>+</button>
        ` : ""}
        <button title="${this._l("edit", "Edit")}" @click=${() => this._startEdit(path, value)}>
          <builtin-icon name="edit" size="12" variant="outlined"></builtin-icon>
        </button>
        ${path ? html`
          <button title="${this._l("delete", "Delete")}" @click=${() => this._deleteAt(path)}>
            <builtin-icon name="delete" size="12" variant="outlined"></builtin-icon>
          </button>
        ` : ""}
      </span>
    `;

    if (!isContainer) {
      return html`
        <div class="node" data-path="${path}">
          ${indent}
          ${this._typeIcon(type)}
          ${path !== "" ? keyEl(path.split(".").pop()) : ""}
          ${path !== "" ? html`<span class="sep">: </span>` : ""}
          ${isEditing ? html`
            <input class="inline-input" .value=${this._editValue}
              @keydown=${(e) => { if (e.key === "Enter") this._commitEdit(); if (e.key === "Escape") this._cancelEdit(); }}
              @blur=${this._commitEdit}
              @input=${(e) => { this._editValue = e.target.value; }}
            />
          ` : html`<span class="value-${type}">${type === "string" ? `"${value}"` : String(value)}</span>`}
          ${actions}
        </div>
      `;
    }

    const entries = type === "array" ? value.map((v, i) => [String(i), v]) : Object.entries(value);
    return html`
      <div class="node" data-path="${path}">
        ${indent}
        <span class="expand" @click=${() => this._toggle(path)}>
          ${expanded
            ? html`<builtin-icon name="down" size="14" variant="outlined"></builtin-icon>`
            : html`<builtin-icon name="right" size="14" variant="outlined"></builtin-icon>`
          }
        </span>
        ${this._typeIcon(type)}
        ${path !== "" ? keyEl(path.split(".").pop()) : ""}
        ${path !== "" ? html`<span class="sep">: </span>` : ""}
        <span class="bracket">${type === "array" ? "[" : "{"}</span>
        ${!expanded ? html`<span class="count">${entries.length} ${this._l("items", "items")}</span>` : ""}
        <span class="bracket">${type === "array" ? "]" : "}"}</span>
        ${actions}
      </div>
      ${expanded ? entries.map(([k, v]) => this._renderTreeNode(v, path ? `${path}.${k}` : k, depth + 1)) : ""}
    `;
  }

  _renderTree() {
    return html`
      <div class="view-wrap tree">
        ${this._renderTreeNode(this._getValue(), "")}
      </div>
    `;
  }

  _renderCode() {
    const text = JSON.stringify(this._getValue(), null, 2);
    return html`
      <div class="view-wrap">
        <textarea class="code" .value=${text} @change=${(e) => {
          try { this._setValue(JSON.parse(e.target.value)); } catch (_err) {}
        }}></textarea>
      </div>
    `;
  }

  _renderView() {
    const text = JSON.stringify(this._getValue(), null, 2);
    return html`<div class="view-wrap"><pre class="code">${text}</pre></div>`;
  }

  render() {
    const mode = this.mode || "tree";
    return html`
      <div class="toolbar" part="toolbar">
        <slot name="toolbar-before"></slot>
        <button class="${mode === "tree" ? "active" : ""}" @click=${() => this.mode = "tree"}>${this._l("tree", "Tree")}</button>
        <button class="${mode === "code" ? "active" : ""}" @click=${() => this.mode = "code"}>${this._l("code", "Code")}</button>
        <button class="${mode === "view" ? "active" : ""}" @click=${() => this.mode = "view"}>${this._l("view", "View")}</button>
        <slot name="toolbar-after"></slot>
      </div>
      ${mode === "tree" ? this._renderTree() : ""}
      ${mode === "code" ? this._renderCode() : ""}
      ${mode === "view" ? this._renderView() : ""}
    `;
  }
}
