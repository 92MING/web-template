import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinDrawer extends BuiltinBaseElement {
  static properties = {
    open: { type: Boolean },
    placement: { type: String },
    size: { type: String },
    noMaskClose: { type: Boolean, attribute: "no-mask-close" },
    noHeader: { type: Boolean, attribute: "no-header" },
    labels: { type: Object },
    _ready: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    sl-drawer { --sl-z-index-drawer: 2000; }
    sl-drawer::part(panel) { background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); }
    sl-drawer::part(body) { padding: 18px; }
  `;

  constructor() {
    super();
    this.open = false;
    this.placement = "right";
    this.size = "320px";
    this.noMaskClose = false;
    this.labels = {};
    this._ready = false;
  }

  connectedCallback() {
    super.connectedCallback();
    ensureShoelace().then(() => { this._ready = true; });
  }

  openDrawer() {
    this.open = true;
    this.dispatchEvent(new CustomEvent("builtin-open", { bubbles: true, composed: true }));
  }

  close() {
    this.open = false;
    this.dispatchEvent(new CustomEvent("builtin-close", { bubbles: true, composed: true }));
  }

  _onRequestClose(e) {
    if (this.noMaskClose && e.detail?.source === "overlay") e.preventDefault();
  }

  render() {
    if (!this._ready) return html``;
    const placement = ["left", "right", "top", "bottom"].includes(this.placement) ? this.placement : "right";
    return html`
      <sl-drawer
        ?open=${this.open}
        placement="${placement}"
        style="--size:${this.size || "320px"}"
        ?no-header=${this.noHeader}
        @sl-request-close=${this._onRequestClose}
        @sl-after-show=${() => this.dispatchEvent(new CustomEvent("builtin-open", { bubbles: true, composed: true }))}
        @sl-after-hide=${() => this.close()}
      >
        <slot name="title" slot="label"></slot>
        <slot></slot>
      </sl-drawer>
    `;
  }
}