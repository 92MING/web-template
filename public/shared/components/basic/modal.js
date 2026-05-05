import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinModal extends BuiltinBaseElement {
  static properties = {
    open: { type: Boolean, reflect: true },
    title: { type: String },
    size: { type: String },
    noClose: { type: Boolean, reflect: true, attribute: "no-close" },
    noMaskClose: { type: Boolean, reflect: true, attribute: "no-mask-close" },
    noHeader: { type: Boolean, reflect: true, attribute: "no-header" },
    noFooter: { type: Boolean, reflect: true, attribute: "no-footer" },
    noAnimation: { type: Boolean, reflect: true, attribute: "no-animation" },
    labels: { type: Object },
    _ready: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    sl-dialog::part(panel) {
      width: min(var(--builtin-modal-width, 560px), calc(100vw - 32px));
      max-height: calc(100vh - 32px);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
    }
    sl-dialog[size="small"]::part(panel) { --builtin-modal-width: 420px; }
    sl-dialog[size="medium"]::part(panel) { --builtin-modal-width: 560px; }
    sl-dialog[size="large"]::part(panel) { --builtin-modal-width: 800px; }
    sl-dialog[size="fullscreen"]::part(panel) {
      --builtin-modal-width: 100vw;
      width: 100vw;
      height: 100vh;
      max-height: 100vh;
      border-radius: 0;
    }
    .footer { display: flex; justify-content: flex-end; gap: 8px; }
  `;

  constructor() {
    super();
    this.open = false;
    this.size = "medium";
    this._ready = false;
  }

  connectedCallback() {
    super.connectedCallback();
    ensureShoelace().then(() => { this._ready = true; });
  }

  openModal() {
    this.open = true;
    this.dispatchEvent(new CustomEvent("builtin-open", { bubbles: true, composed: true }));
  }

  close() {
    this.open = false;
    this.dispatchEvent(new CustomEvent("builtin-close", { bubbles: true, composed: true }));
  }

  _onRequestClose(e) {
    if (this.noMaskClose && e.detail?.source === "overlay") e.preventDefault();
    if (this.noClose && (e.detail?.source === "close-button" || e.detail?.source === "keyboard")) e.preventDefault();
  }

  render() {
    if (!this._ready) return html``;
    return html`
      <sl-dialog
        label="${this.title || ""}"
        size="${this.size || "medium"}"
        ?open=${this.open}
        ?no-header=${this.noHeader}
        @sl-request-close=${this._onRequestClose}
        @sl-after-show=${() => this.dispatchEvent(new CustomEvent("builtin-open", { bubbles: true, composed: true }))}
        @sl-after-hide=${() => this.close()}
      >
        <slot></slot>
        ${!this.noFooter ? html`<div slot="footer" class="footer"><slot name="footer"></slot></div>` : ""}
      </sl-dialog>
    `;
  }
}