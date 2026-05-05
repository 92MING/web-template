import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinConfirm extends BuiltinBaseElement {
  static properties = {
    title: { type: String },
    message: { type: String },
    confirmLabel: { type: String, attribute: "confirm-label" },
    cancelLabel: { type: String, attribute: "cancel-label" },
    dangerous: { type: Boolean },
    type: { type: String },
    labels: { type: Object },
    _open: { type: Boolean, state: true },
    _ready: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .message { display: flex; align-items: flex-start; gap: 10px; line-height: 1.5; }
    .footer { display: flex; justify-content: flex-end; gap: 8px; }
  `;

  constructor() {
    super();
    this.type = "info";
    this._open = false;
    this._ready = false;
    this._resolve = null;
  }

  connectedCallback() {
    super.connectedCallback();
    ensureShoelace().then(() => { this._ready = true; });
  }

  open() {
    this._open = true;
    return new Promise((resolve) => { this._resolve = resolve; });
  }

  static async show(options = {}) {
    const el = document.createElement("builtin-confirm");
    Object.assign(el, options);
    document.body.appendChild(el);
    try { return await el.open(); } finally { el.remove(); }
  }

  close(confirmed) {
    this._open = false;
    if (this._resolve) {
      this._resolve(confirmed);
      this._resolve = null;
    }
    this.dispatchEvent(new CustomEvent(confirmed ? "builtin-confirm" : "builtin-cancel", { bubbles: true, composed: true }));
  }

  _l(key, fallback = "") { return this.labels?.[key] ?? this._t(key) ?? fallback; }

  _iconName() {
    return { info: "info-circle", success: "check-circle", warning: "warning", danger: "close-circle" }[this.type || "info"] || "info-circle";
  }

  render() {
    if (!this._ready) return html``;
    const titleText = this.title || this._l("confirm.title", "Confirm");
    const confirmText = this.confirmLabel || this._l("confirm.confirm", "Confirm");
    const cancelText = this.cancelLabel || this._l("confirm.cancel", "Cancel");
    return html`
      <sl-dialog label="${titleText}" ?open=${this._open} @sl-after-hide=${() => { if (this._resolve) this.close(false); }}>
        <div class="message"><builtin-icon name="${this._iconName()}" size="22"></builtin-icon><span>${this.message || ""}</span></div>
        <div slot="footer" class="footer">
          <sl-button @click=${() => this.close(false)}>${cancelText}</sl-button>
          <sl-button variant="${this.dangerous ? "danger" : "primary"}" @click=${() => this.close(true)}>${confirmText}</sl-button>
        </div>
      </sl-dialog>
    `;
  }
}