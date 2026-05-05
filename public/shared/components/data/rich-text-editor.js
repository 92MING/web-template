import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

export class BuiltinRichTextEditor extends BuiltinBaseElement {
  static properties = { value: { type: String }, labels: { type: Object } };

  static styles = css`
    :host { display: block; }
    .editor { background: var(--builtin-surface, #ffffff); border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; }
    .editor .ql-container { min-height: var(--builtin-rich-editor-height, 180px); font: inherit; }
    builtin-rich-text-editor .ql-toolbar,
    builtin-rich-text-editor .ql-container { border-color: var(--builtin-border, #d1d5db) !important; background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); }
    builtin-rich-text-editor .ql-editor { color: var(--builtin-color-text, #111827); }
    builtin-rich-text-editor .ql-toolbar button,
    builtin-rich-text-editor .ql-toolbar .ql-picker-label,
    builtin-rich-text-editor .ql-toolbar .ql-picker-item { color: var(--builtin-color-text, #111827) !important; }
    builtin-rich-text-editor .ql-toolbar button svg .ql-stroke,
    builtin-rich-text-editor .ql-toolbar .ql-picker-label svg .ql-stroke { stroke: currentColor !important; }
    builtin-rich-text-editor .ql-toolbar button svg .ql-fill,
    builtin-rich-text-editor .ql-toolbar .ql-picker-label svg .ql-fill { fill: currentColor !important; }
    builtin-rich-text-editor .ql-toolbar button:hover,
    builtin-rich-text-editor .ql-toolbar button.ql-active,
    builtin-rich-text-editor .ql-toolbar .ql-picker-label:hover { background: var(--builtin-button-hover-bg, #f9fafb); color: var(--builtin-primary, #2563eb) !important; }
    [data-builtin-theme="dark"] builtin-rich-text-editor .ql-toolbar,
    [data-builtin-theme="dark"] builtin-rich-text-editor .ql-container,
    [data-builtin-theme="dark"] builtin-rich-text-editor .ql-editor { background: var(--builtin-surface, #1f2937); color: var(--builtin-color-text, #e5e7eb); }
    [data-builtin-theme="dark"] builtin-rich-text-editor .ql-toolbar button,
    [data-builtin-theme="dark"] builtin-rich-text-editor .ql-toolbar .ql-picker-label,
    [data-builtin-theme="dark"] builtin-rich-text-editor .ql-toolbar .ql-picker-item { color: var(--builtin-color-text, #e5e7eb) !important; }
  `;

  constructor() {
    super();
    this.value = "";
    this._editor = null;
    this._suppressChange = false;
  }

  createRenderRoot() { return this; }

  firstUpdated() { this._initEditor(); }

  updated(changed) {
    if (!this._editor || this._suppressChange) return;
    if (changed.has("value") && this._editor.root.innerHTML !== (this.value || "")) this._editor.root.innerHTML = this.value || "";
  }

  async _initEditor() {
    const Quill = await ensureVendor("quill", { css: "/vendor/quill/quill.snow.css" });
    const target = this.renderRoot.querySelector(".editor");
    if (!target || this._editor) return;
    this._editor = new Quill(target, { theme: "snow" });
    this._editor.root.innerHTML = this.value || "";
    this._editor.on("text-change", () => {
      this._suppressChange = true;
      this.value = this._editor.root.innerHTML;
      this._suppressChange = false;
      this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true, composed: true }));
    });
  }

  render() { return html`<style>${this.constructor.styles.cssText}</style><div class="editor"></div>`; }
}