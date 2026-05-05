import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

export class BuiltinFileUploader extends BuiltinBaseElement {
  static properties = {
    mode: { type: String }, multiple: { type: Boolean }, accept: { type: String }, maxSize: { type: Number, attribute: "max-size" }, label: { type: String }, labels: { type: Object }, _files: { type: Array, state: true }, _ready: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .dropzone { border: 2px dashed var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); min-height: 128px; padding: 24px; display: grid; place-items: center; text-align: center; cursor: pointer; }
    .dropzone.dz-drag-hover { border-color: var(--builtin-primary, #2563eb); background: var(--builtin-row-hover-bg, #f9fafb); }
    .dz-message { color: var(--builtin-color-muted, #6b7280); }
    .avatar { width: 128px; height: 128px; border-radius: 50%; overflow: hidden; }
    .list { min-height: 68px; align-items: stretch; text-align: left; }
  `;

  constructor() {
    super();
    this.mode = "dropzone";
    this.multiple = false;
    this._files = [];
    this._ready = false;
    this._dropzone = null;
  }

  firstUpdated() { this._initDropzone(); }

  disconnectedCallback() {
    this._dropzone?.destroy?.();
    this._dropzone = null;
    super.disconnectedCallback();
  }

  async _initDropzone() {
    const Dropzone = await ensureVendor("dropzone", { css: "/vendor/dropzone/dropzone.min.css" });
    Dropzone.autoDiscover = false;
    const target = this.renderRoot.querySelector(".dropzone");
    if (!target || this._dropzone) return;
    this._dropzone = new Dropzone(target, {
      url: "/",
      autoProcessQueue: false,
      uploadMultiple: !!this.multiple,
      maxFiles: this.multiple ? null : 1,
      acceptedFiles: this.accept || null,
      maxFilesize: this.maxSize ? this.maxSize / 1024 / 1024 : null,
      addRemoveLinks: true,
      dictDefaultMessage: this.label || this._l("dropzoneLabel", "Drop files here or click to browse"),
    });
    this._dropzone.on("addedfile", (file) => {
      if (!this.multiple && this._dropzone.files.length > 1) this._dropzone.removeFile(this._dropzone.files[0]);
      this._files = this._dropzone.files.filter((item) => item.accepted !== false);
      this._emitFiles();
    });
    this._dropzone.on("removedfile", () => { this._files = this._dropzone.files.filter((item) => item.accepted !== false); this._emitFiles(); });
    this._dropzone.on("error", (_file, message) => this.dispatchEvent(new CustomEvent("builtin-error", { detail: { message }, bubbles: true, composed: true })));
    this._ready = true;
  }

  _l(key, fallback = "") { return this.labels?.[key] ?? this._t(key) ?? fallback; }
  _emitFiles() { this.dispatchEvent(new CustomEvent("builtin-files", { detail: { files: [...this._files] }, bubbles: true, composed: true })); }

  render() { return html`<div class="dropzone ${this.mode === "avatar" ? "avatar" : this.mode === "list" ? "list" : ""}"><div class="dz-message">${this.label || this._l("dropzoneLabel", "Drop files here or click to browse")}</div></div>`; }
}