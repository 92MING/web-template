/**
 * @fileoverview BuiltinDocumentPreviewer — Document preview for PDF/TXT/MD/CODE/DOC.
 *
 * @attr {string} src — Document URL.
 * @attr {string} type — 'pdf' | 'doc' | 'txt' | 'md' | 'code'.
 * @attr {string} filename — Display filename.
 * @attr {number} page — Current page (paginated docs).
 * @attr {number} zoom — Zoom percentage (default 100).
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-download — Detail: { src, filename }.
 * @event builtin-page-change — Detail: { page }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

export class BuiltinDocumentPreviewer extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    type: { type: String },
    filename: { type: String },
    page: { type: Number },
    zoom: { type: Number },
    labels: { type: Object },
    _content: { type: String, state: true },
    _loading: { type: Boolean, state: true },
    _error: { type: String, state: true },
    _totalPages: { type: Number, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap { border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); background: var(--builtin-surface, #ffffff); overflow: hidden; }
    .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); flex-wrap: wrap; background: var(--builtin-header-bg, #f9fafb); }
    .toolbar-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .toolbar button {
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      min-width: 32px; min-height: 32px; padding: 0 10px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      font: inherit; font-size: 13px; font-weight: 600;
      cursor: pointer;
      transition: background .15s ease, border-color .15s ease, color .15s ease;
    }
    .toolbar button:hover {
      background: var(--builtin-surface, #ffffff);
      border-color: var(--builtin-primary, #2563eb);
      color: var(--builtin-primary, #2563eb);
    }
    .toolbar button:disabled { opacity: .45; cursor: not-allowed; }
    .fname { font-weight: 650; font-size: 14px; color: var(--builtin-color-text, #111827); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .viewer { padding: 16px; min-height: 320px; max-height: 70vh; overflow: auto; background: var(--builtin-surface, #ffffff); }
    .viewer iframe { width: 100%; height: 60vh; border: none; }
    .viewer pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.6; color: var(--builtin-color-text, #111827); }
    .viewer code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 48px; color: var(--builtin-color-muted, #6b7280); text-align: center; }
    .status { padding: 48px; text-align: center; color: var(--builtin-color-muted, #6b7280); }
    @media (max-width: 720px) {
      .viewer { padding: 10px; }
      .fname { max-width: 140px; }
    }
  `;

  constructor() {
    super();
    this.src = "";
    this.type = "txt";
    this.filename = "";
    this.page = 1;
    this.zoom = 100;
    this.labels = {};
    this._content = "";
    this._loading = false;
    this._error = "";
    this._totalPages = 1;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  updated(changed) {
    if (changed.has("src") || changed.has("type")) this._load();
  }

  async _load() {
    if (!this.src) { this._content = ""; return; }
    const t = (this.type || "txt").toLowerCase();
    if (t === "pdf" || t === "doc") { this._content = ""; return; }
    this._loading = true; this._error = "";
    try {
      const res = await fetch(this.src);
      if (!res.ok) throw new Error("Failed to load");
      this._content = await res.text();
    } catch (e) {
      this._error = this._l("preview.error", "Unable to load document");
    } finally {
      this._loading = false;
    }
  }

  _onDownload() {
    this.dispatchEvent(new CustomEvent("builtin-download", { bubbles: true, composed: true, detail: { src: this.src, filename: this.filename } }));
  }

  _onPage(delta) {
    const np = Math.max(1, Math.min(this._totalPages, (this.page || 1) + delta));
    if (np !== this.page) {
      this.page = np;
      this.dispatchEvent(new CustomEvent("builtin-page-change", { bubbles: true, composed: true, detail: { page: np } }));
    }
  }

  _renderViewer() {
    const t = (this.type || "txt").toLowerCase();
    const z = Math.max(25, Math.min(300, this.zoom || 100)) / 100;
    const zoomStyle = `transform: scale(${z}); transform-origin: top left;`;
    if (t === "pdf") {
      return html`<iframe src="${this.src}" style="width:100%;height:60vh;border:none;"></iframe>`;
    }
    if (t === "doc") {
      return html`
        <div class="placeholder">
          <builtin-icon name="file-text" size="48" variant="outlined"></builtin-icon>
          <div>${this._l("preview.docPlaceholder", "DOC preview is not available. Please download to view.")}</div>
          <button @click="${this._onDownload}">${this._l("preview.download", "Download")}</button>
        </div>
      `;
    }
    if (this._loading) return html`<div class="status">${this._l("preview.loading", "Loading...")}</div>`;
    if (this._error) return html`<div class="status">${this._error}</div>`;
    if (t === "code") return html`<pre><code style="${zoomStyle}">${this._content}</code></pre>`;
    return html`<pre style="${zoomStyle}">${this._content}</pre>`;
  }

  render() {
    const t = (this.type || "txt").toLowerCase();
    return html`
      <div class="wrap">
        <div class="toolbar">
          <div class="toolbar-group">
            <span class="fname">${this.filename || this.src || this._l("preview.document", "Document")}</span>
          </div>
          <div class="toolbar-group">
            ${t === "pdf" ? html`
              <button @click="${() => this._onPage(-1)}">←</button>
              <span style="font-size:13px;">${this.page} / ${this._totalPages}</span>
              <button @click="${() => this._onPage(1)}">→</button>
            ` : ""}
            <button @click="${() => this.zoom = Math.max(25, this.zoom - 25)}">−</button>
            <span style="font-size:13px;color:var(--builtin-color-muted);">${this.zoom}%</span>
            <button @click="${() => this.zoom = Math.min(300, this.zoom + 25)}">+</button>
            <button @click="${this._onDownload}">${this._l("preview.download", "Download")}</button>
          </div>
        </div>
        <div class="viewer">${this._renderViewer()}</div>
      </div>
    `;
  }
}
