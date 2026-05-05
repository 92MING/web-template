import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

const PLACEMENT_MAP = { bottom: "bottom-start", top: "top-start", left: "left-start", right: "right-start" };

export class BuiltinDropdown extends BuiltinBaseElement {
  static properties = { open: { type: Boolean }, placement: { type: String }, noCloseOnClick: { type: Boolean, attribute: "no-close-on-click" }, labels: { type: Object }, _ready: { type: Boolean, state: true } };
  static styles = css`
    :host { display: inline-block; }
    sl-dropdown::part(panel) {
      z-index: 1300;
      min-width: 180px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
      overflow: hidden;
    }
    .menu { min-width: 160px; padding: 6px; background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); }
    .menu ::slotted(*) { color: inherit; }
  `;
  constructor() { super(); this.open = false; this.placement = "bottom"; this.noCloseOnClick = false; this.labels = {}; this._ready = false; }
  connectedCallback() { super.connectedCallback(); ensureShoelace().then(() => { this._ready = true; }); }
  _setOpen(open) { if (this.open === open) return; this.open = open; this.dispatchEvent(new CustomEvent(open ? "builtin-open" : "builtin-close", { bubbles: true, composed: true })); }
  render() {
    if (!this._ready) return html``;
    return html`<sl-dropdown ?open=${this.open} placement="${PLACEMENT_MAP[this.placement || "bottom"] || "bottom-start"}" ?stay-open-on-select=${this.noCloseOnClick} @sl-show=${() => this._setOpen(true)} @sl-hide=${() => this._setOpen(false)}><span slot="trigger"><slot name="trigger"></slot></span><div class="menu"><slot></slot></div></sl-dropdown>`;
  }
}