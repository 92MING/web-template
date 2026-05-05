import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

const ACE_MODE_MAP = {
  js: "javascript",
  ts: "typescript",
  py: "python",
  md: "markdown",
  sh: "sh",
  yaml: "yaml",
  yml: "yaml",
};

export class BuiltinCodeEditor extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    language: { type: String },
    lineNumbers: { type: Boolean, attribute: "line-numbers" },
    readonly: { type: Boolean },
    labels: { type: Object },
    height: { type: String },
  };

  static styles = css`
    :host { display: block; }
    .wrap { border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-surface, #ffffff); }
    .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); background: var(--builtin-header-bg, #f9fafb); }
    .lang { font-size: 12px; color: var(--builtin-color-muted, #6b7280); font-weight: 650; text-transform: uppercase; }
    .editor { height: var(--builtin-code-editor-height, 280px); min-height: 180px; width: 100%; }
    button { display: inline-flex; align-items: center; gap: 6px; min-height: 28px; padding: 0 10px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); background: var(--builtin-button-bg, #ffffff); color: var(--builtin-color-text, #111827); cursor: pointer; }
  `;

  constructor() {
    super();
    this.value = "";
    this.language = "javascript";
    this.lineNumbers = false;
    this.readonly = false;
    this.height = "280px";
    this._editor = null;
    this._suppressChange = false;
  }

  createRenderRoot() { return this; }

  firstUpdated() {
    this._initEditor();
  }

  updated(changed) {
    if (!this._editor) return;
    if (changed.has("value") && this._editor.getValue() !== (this.value || "")) {
      this._suppressChange = true;
      this._editor.setValue(this.value || "", -1);
      this._suppressChange = false;
    }
    if (changed.has("language")) this._setMode();
    if (changed.has("lineNumbers")) this._editor.renderer.setShowGutter(!!this.lineNumbers);
    if (changed.has("readonly")) this._editor.setReadOnly(!!this.readonly);
    if (changed.has("height")) this._resizeEditor();
    if (changed.has("_ptTheme")) this._editor.setTheme(this._ptTheme === "dark" ? "ace/theme/dracula" : "ace/theme/github");
  }

  disconnectedCallback() {
    this._editor?.destroy();
    this._editor = null;
    super.disconnectedCallback();
  }

  async _initEditor() {
    const ace = await ensureVendor("ace-builds");
    ace.config.set("basePath", "/vendor/ace-builds/src-min-noconflict");
    const target = this.renderRoot.querySelector(".editor");
    if (!target || this._editor) return;
    this._editor = ace.edit(target);
    target.style.setProperty("--builtin-code-editor-height", this.height || "280px");
    this._editor.setTheme(this._ptTheme === "dark" ? "ace/theme/dracula" : "ace/theme/github");
    this._editor.setValue(this.value || "", -1);
    this._editor.renderer.setShowGutter(!!this.lineNumbers);
    this._editor.setReadOnly(!!this.readonly);
    this._editor.session.setUseWorker(false);
    this._editor.setOptions({ showPrintMargin: false, highlightActiveLine: true, fontSize: "13px", tabSize: 2 });
    this._setMode();
    this._editor.session.on("change", () => {
      if (this._suppressChange) return;
      this.value = this._editor.getValue();
      this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true, composed: true }));
    });
    this._resizeEditor();
  }

  _resizeEditor() {
    const target = this.renderRoot.querySelector(".editor");
    target?.style.setProperty("--builtin-code-editor-height", this.height || "280px");
    requestAnimationFrame(() => this._editor?.resize(true));
  }

  _setMode() {
    const mode = ACE_MODE_MAP[this.language] || this.language || "text";
    this._editor?.session.setMode(`ace/mode/${mode}`);
  }

  async _copy() {
    await navigator.clipboard?.writeText(this.value || "");
  }

  render() {
    return html`
      <style>${this.constructor.styles.cssText}</style>
      <div class="wrap">
        <div class="header"><span class="lang">${this.language || "text"}</span><slot name="header-extra"></slot><button @click=${this._copy}><builtin-icon name="copy" size="14"></builtin-icon>${this._t("copy")}</button></div>
        <div class="editor"></div>
      </div>
    `;
  }
}