/**
 * @fileoverview BuiltinDragUploadZone — Drag-and-drop file upload area with progress.
 *
 * @attr {string} accept — Comma-separated MIME types.
 * @attr {boolean} multiple — Allow multiple files.
 * @attr {number} maxSize — Max file size in bytes.
 * @attr {boolean} uploading — Show progress state.
 * @attr {number} progress — Upload progress 0-100.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @slots
 *   - icon: Upload icon.
 *   - hint: Helper text.
 *
 * @event builtin-files-selected — Files dropped or selected. Detail: { files }.
 * @event builtin-file-remove — File removed. Detail: { file }.
 * @event builtin-upload — Upload confirmed. Detail: { files }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinDragUploadZone extends BuiltinBaseElement {
  static properties = {
    accept: { type: String },
    multiple: { type: Boolean },
    maxSize: { type: Number, attribute: "max-size" },
    uploading: { type: Boolean },
    progress: { type: Number },
    labels: { type: Object },
    _files: { type: Array, state: true },
    _dragOver: { type: Boolean, state: true },
    _error: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .zone {
      border: 2px dashed var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 28px;
      text-align: center;
      background: var(--builtin-surface, #ffffff);
      transition: border-color .2s ease, background .2s ease;
      cursor: pointer;
    }
    .zone.dragover { border-color: var(--builtin-primary, #2563eb); background: var(--builtin-header-bg, #f9fafb); }
    .zone.uploading { cursor: default; }
    .icon { color: var(--builtin-color-muted, #6b7280); margin-bottom: 10px; }
    .hint { font-size: 14px; color: var(--builtin-color-muted, #6b7280); }
    .error { color: var(--builtin-color-danger, #b91c1c); font-size: 13px; margin-top: 8px; }
    .file-list { margin-top: 14px; text-align: left; }
    .file-item {
      display: flex; align-items: center; justify-content: space-between;
      gap: 10px; padding: 8px 10px; border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px); margin-bottom: 8px; background: var(--builtin-surface, #ffffff);
    }
    .file-name { font-size: 13px; color: var(--builtin-color-text, #111827); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .file-size { font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .remove {
      border: 0; background: transparent; padding: 4px; min-height: 0; cursor: pointer;
      color: var(--builtin-color-muted, #6b7280); display: inline-flex; align-items: center;
    }
    .remove:hover { color: var(--builtin-color-danger, #b91c1c); }
    .progress-wrap { margin-top: 12px; }
    .progress-bar {
      height: 6px; border-radius: 999px; background: var(--builtin-border-soft, #e5e7eb); overflow: hidden;
    }
    .progress-fill { height: 100%; background: var(--builtin-primary, #2563eb); transition: width .3s ease; }
    .actions { margin-top: 12px; display: flex; justify-content: center; gap: 8px; }
    input[type="file"] { display: none; }
  `;

  constructor() {
    super();
    this.accept = "";
    this.multiple = false;
    this.maxSize = 0;
    this.uploading = false;
    this.progress = 0;
    this.labels = {};
    this._files = [];
    this._dragOver = false;
    this._error = "";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _fmtSize(b) {
    if (!b) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
    return `${b.toFixed(1)} ${units[i]}`;
  }

  _validate(file) {
    if (this.maxSize && file.size > this.maxSize) {
      return this._l("upload.tooLarge", "File too large");
    }
    if (this.accept) {
      const types = this.accept.split(",").map((t) => t.trim());
      const ok = types.some((t) => {
        if (t.endsWith("/*")) return file.type.startsWith(t.slice(0, -1));
        return file.type === t;
      });
      if (!ok) return this._l("upload.invalidType", "Invalid file type");
    }
    return "";
  }

  _addFiles(fileList) {
    const added = [];
    for (const file of fileList) {
      const err = this._validate(file);
      if (err) { this._error = err; continue; }
      added.push(file);
    }
    if (added.length) {
      this._files = this.multiple ? [...this._files, ...added] : added;
      this._error = "";
      this.dispatchEvent(new CustomEvent("builtin-files-selected", { bubbles: true, composed: true, detail: { files: added } }));
    }
  }

  _onDrop(e) {
    e.preventDefault();
    this._dragOver = false;
    if (this.uploading) return;
    this._addFiles(e.dataTransfer.files);
  }

  _onDragOver(e) {
    e.preventDefault();
    if (!this.uploading) this._dragOver = true;
  }

  _onDragLeave() {
    this._dragOver = false;
  }

  _onInput(e) {
    this._addFiles(e.target.files);
    e.target.value = "";
  }

  _remove(file) {
    this._files = this._files.filter((f) => f !== file);
    this.dispatchEvent(new CustomEvent("builtin-file-remove", { bubbles: true, composed: true, detail: { file } }));
  }

  _upload() {
    if (!this._files.length) return;
    this.dispatchEvent(new CustomEvent("builtin-upload", { bubbles: true, composed: true, detail: { files: this._files } }));
  }

  render() {
    const zoneClass = { zone: true, dragover: this._dragOver, uploading: this.uploading };
    const id = "f-" + Math.random().toString(36).slice(2);
    return html`
      <div
        class="${classMap(zoneClass)}"
        @dragover="${this._onDragOver}"
        @dragleave="${this._onDragLeave}"
        @drop="${this._onDrop}"
        @click="${() => { if (!this.uploading) this.shadowRoot?.getElementById(id)?.click(); }}"
      >
        <input type="file" id="${id}" .accept="${this.accept}" ?multiple="${this.multiple}" @change="${this._onInput}" />
        <div class="icon"><slot name="icon"><builtin-icon name="cloud-upload" size="36" variant="outlined"></builtin-icon></slot></div>
        <div class="hint">
          <slot name="hint">${this._l("upload.hint", "Drag files here or click to upload")}</slot>
        </div>
        ${this._error ? html`<div class="error">${this._error}</div>` : ""}
      </div>
      ${this._files.length ? html`
        <div class="file-list">
          ${this._files.map((f) => html`
            <div class="file-item">
              <span class="file-name">${f.name}</span>
              <span class="file-size">${this._fmtSize(f.size)}</span>
              <button class="remove" @click="${() => this._remove(f)}" ?disabled="${this.uploading}">
                <builtin-icon name="close" size="16" variant="outlined"></builtin-icon>
              </button>
            </div>
          `)}
        </div>
      ` : ""}
      ${this.uploading ? html`
        <div class="progress-wrap">
          <div class="progress-bar"><div class="progress-fill" style="width:${Math.max(0, Math.min(100, this.progress || 0))}%"></div></div>
        </div>
      ` : ""}
      ${this._files.length && !this.uploading ? html`
        <div class="actions">
          <button class="builtin-primary" @click="${this._upload}">${this._l("upload.start", "Upload")}</button>
        </div>
      ` : ""}
    `;
  }
}
