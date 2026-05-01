/**
 * @fileoverview BuiltinFileUploader — Drag-and-drop file upload web component.
 *
 * @attr {string} mode — `dropzone` | `list` | `avatar`.
 * @attr {boolean} multiple
 * @attr {string} accept
 * @attr {number} max-size
 * @attr {string} label
 *
 * @event builtin-files — Detail: `{ files: File[] }`
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

export class BuiltinFileUploader extends BuiltinBaseElement {
  static properties = {
    mode: { type: String },
    multiple: { type: Boolean },
    accept: { type: String },
    maxSize: { type: Number, attribute: "max-size" },
    label: { type: String },
    labels: { type: Object },
    _files: { type: Array, state: true },
    _errors: { type: Array, state: true },
    _dragover: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .dropzone {
      border: 2px dashed var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 28px;
      text-align: center;
      background: var(--builtin-surface, #ffffff);
      cursor: pointer;
      transition: border-color .15s, background .15s;
      color: var(--builtin-color-text, #111827);
    }
    .dropzone:hover, .dropzone.dragover {
      border-color: var(--builtin-primary, #2563eb);
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    .dropzone-text { color: var(--builtin-color-muted, #6b7280); }
    .file-list { margin-top: 12px; display: grid; gap: 8px; }
    .file-item {
      display: flex; align-items: center; justify-content: space-between; gap: 10px;
      padding: 8px 10px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
    }
    .file-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
    .file-meta { color: var(--builtin-color-muted, #6b7280); }
    .remove-btn {
      border: 0; background: transparent; color: var(--builtin-color-danger, #b91c1c);
      min-height: 28px; padding: 0 6px; cursor: pointer; font-size: 18px; line-height: 1;
      display: inline-flex; align-items: center; justify-content: center;
    }
    .remove-btn:hover { opacity: .8; }
    .errors { margin-top: 10px; color: var(--builtin-color-danger, #b91c1c); font-size: 12px; }
    input[type="file"] { display: none; }
    .list-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
    .avatar {
      width: 120px; height: 120px; border-radius: 50%;
      border: 2px dashed var(--builtin-border, #d1d5db);
      display: flex; align-items: center; justify-content: center;
      overflow: hidden; cursor: pointer; background: var(--builtin-surface, #ffffff);
      position: relative;
    }
    .avatar:hover { border-color: var(--builtin-primary, #2563eb); background: var(--builtin-row-hover-bg, #f9fafb); }
    .avatar img { width: 100%; height: 100%; object-fit: cover; }
    .avatar-placeholder { color: var(--builtin-color-muted, #6b7280); text-align: center; font-size: 12px; padding: 8px; }
    .add-btn {
      display: inline-flex; align-items: center; gap: 6px;
    }
    @media (max-width: 720px) {
      .dropzone { padding: 36px 16px; width: 100%; }
      .remove-btn { min-height: 36px; padding: 0 10px; }
      .file-item { padding: 10px 12px; }
    }
  `;

  constructor() {
    super();
    this.mode = "dropzone";
    this._files = [];
    this._errors = [];
  }

  _validate(file) {
    if (this.maxSize !== undefined && this.maxSize !== null && file.size > this.maxSize) {
      return this._l("fileTooLarge", `File "${file.name}" exceeds maximum size of ${this._formatBytes(this.maxSize)}.`);
    }
    return null;
  }

  _formatBytes(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  _addFiles(fileList) {
    const added = [];
    this._errors = [];
    for (const file of Array.from(fileList)) {
      const err = this._validate(file);
      if (err) this._errors.push(err);
      else added.push(file);
    }
    if (this.multiple) this._files = [...this._files, ...added];
    else this._files = added.slice(0, 1);
    if (this._files.length || added.length) {
      this.dispatchEvent(new CustomEvent("builtin-files", { detail: { files: [...this._files] }, bubbles: true, composed: true }));
    }
  }

  _removeFile(index) {
    this._files = this._files.filter((_, i) => i !== index);
    this.dispatchEvent(new CustomEvent("builtin-files", { detail: { files: [...this._files] }, bubbles: true, composed: true }));
  }

  _onDrop(e) {
    e.preventDefault();
    this._dragover = false;
    if (e.dataTransfer?.files?.length) this._addFiles(e.dataTransfer.files);
  }

  _onChange(e) {
    const input = e.target;
    if (input.files?.length) {
      this._addFiles(input.files);
      input.value = "";
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  render() {
    const labelText = this.label || this._l("dropzoneLabel", "Drop files here or click to browse");
    const mode = this.mode || "dropzone";

    const fileList = html`
      ${this._files.length ? html`
        <div class="file-list">
          ${repeat(this._files, (file, idx) => html`
            <div class="file-item">
              <span class="file-name" title="${file.name}">${file.name}</span>
              <span class="file-meta">${this._formatBytes(file.size)}</span>
              <button class="remove-btn" @click=${() => this._removeFile(idx)} aria-label=${this._l("remove", "Remove file")}>×</button>
            </div>
          `)}
        </div>
      ` : null}
      ${this._errors.length ? html`<div class="errors">${this._errors.join(" \u2014 ")}</div>` : null}
    `;

    if (mode === "avatar") {
      const hasImage = this._files[0];
      return html`
        <div>
          <div class="avatar"
            @click=${() => this.shadowRoot.querySelector("input")?.click()}
            @dragover=${(e) => { e.preventDefault(); this._dragover = true; }}
            @dragleave=${() => this._dragover = false}
            @drop=${this._onDrop}>
            ${hasImage
              ? html`<img src="${URL.createObjectURL(hasImage)}" alt="avatar" />`
              : html`<div class="avatar-placeholder">${labelText}</div>`}
          </div>
          <input type="file" .accept=${this.accept || null} @change=${this._onChange} />
        </div>
      `;
    }

    if (mode === "list") {
      return html`
        <div>
          <div class="list-header">
            <span class="builtin-muted">${this._l("files", "Files")} (${this._files.length})</span>
            <button class="add-btn builtin-primary" @click=${() => this.shadowRoot.querySelector("input")?.click()}>
              <builtin-icon name="plus" size="20" variant="outlined"></builtin-icon>
              ${this._l("add", "Add")}
            </button>
          </div>
          ${fileList}
          <input type="file" ?multiple=${this.multiple} .accept=${this.accept || null} @change=${this._onChange} />
        </div>
      `;
    }

    // dropzone (default)
    return html`
      <div>
        <div class="dropzone ${classMap({ dragover: this._dragover })}"
          @click=${() => this.shadowRoot.querySelector("input")?.click()}
          @dragover=${(e) => { e.preventDefault(); this._dragover = true; }}
          @dragleave=${() => this._dragover = false}
          @drop=${this._onDrop}>
          <div class="dropzone-text">${labelText}</div>
        </div>
        ${fileList}
        <input type="file" ?multiple=${this.multiple} .accept=${this.accept || null} @change=${this._onChange} />
      </div>
    `;
  }
}
