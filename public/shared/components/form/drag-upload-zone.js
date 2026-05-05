import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

export class BuiltinDragUploadZone extends BuiltinBaseElement {
  static properties = {
    accept: { type: String }, multiple: { type: Boolean }, maxSize: { type: Number, attribute: "max-size" }, uploading: { type: Boolean }, progress: { type: Number }, labels: { type: Object }, _files: { type: Array, state: true },
  };

  static styles = css`
    :host { display: block; }
    .zone { border: 2px dashed var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); padding: 28px; min-height: 148px; display: grid; place-items: center; text-align: center; background: var(--builtin-surface, #ffffff); cursor: pointer; }
    .zone.dz-drag-hover { border-color: var(--builtin-primary, #2563eb); background: var(--builtin-header-bg, #f9fafb); }
    .hint { color: var(--builtin-color-muted, #6b7280); }
    .progress { height: 6px; border-radius: 999px; background: var(--builtin-border-soft, #e5e7eb); overflow: hidden; margin-top: 12px; }
    .bar { height: 100%; background: var(--builtin-primary, #2563eb); }
    .actions { margin-top: 12px; text-align: center; }
  `;

  constructor() {
    super();
    this.accept = "";
    this.multiple = false;
    this.maxSize = 0;
    this.uploading = false;
    this.progress = 0;
    this._files = [];
    this._dropzone = null;
  }

  firstUpdated() { this._initDropzone(); }
  disconnectedCallback() { this._dropzone?.destroy?.(); this._dropzone = null; super.disconnectedCallback(); }

  async _initDropzone() {
    const Dropzone = await ensureVendor("dropzone", { css: "/vendor/dropzone/dropzone.min.css" });
    Dropzone.autoDiscover = false;
    const target = this.renderRoot.querySelector(".zone");
    if (!target || this._dropzone) return;
    this._dropzone = new Dropzone(target, { url: "/", autoProcessQueue: false, uploadMultiple: !!this.multiple, maxFiles: this.multiple ? null : 1, acceptedFiles: this.accept || null, maxFilesize: this.maxSize ? this.maxSize / 1024 / 1024 : null, addRemoveLinks: true, dictDefaultMessage: this._l("upload.hint", "Drag files here or click to upload") });
    this._dropzone.on("addedfile", (file) => {
      if (!this.multiple && this._dropzone.files.length > 1) this._dropzone.removeFile(this._dropzone.files[0]);
      this._files = this._dropzone.files.filter((item) => item.accepted !== false);
      this.dispatchEvent(new CustomEvent("builtin-files-selected", { bubbles: true, composed: true, detail: { files: [...this._files] } }));
    });
    this._dropzone.on("removedfile", (file) => this.dispatchEvent(new CustomEvent("builtin-file-remove", { bubbles: true, composed: true, detail: { file } })));
  }

  _l(key, fallback = "") { return this.labels?.[key] ?? this._t(key) ?? fallback; }
  _upload() { if (this._files.length) this.dispatchEvent(new CustomEvent("builtin-upload", { bubbles: true, composed: true, detail: { files: [...this._files] } })); }

  render() { return html`<div class="zone"><div><slot name="icon"><builtin-icon name="cloud-upload" size="36"></builtin-icon></slot><div class="hint"><slot name="hint">${this._l("upload.hint", "Drag files here or click to upload")}</slot></div></div></div>${this.uploading ? html`<div class="progress"><div class="bar" style="width:${Math.max(0, Math.min(100, this.progress || 0))}%"></div></div>` : ""}${this._files.length && !this.uploading ? html`<div class="actions"><button class="builtin-primary" @click=${this._upload}>${this._l("upload.start", "Upload")}</button></div>` : ""}`; }
}