import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

const VARIANT_MAP = { default: "neutral", primary: "primary", success: "success", warning: "warning", error: "danger", danger: "danger" };

export class BuiltinBadge extends BuiltinBaseElement {
  static properties = { text: { type: String }, variant: { type: String }, pill: { type: Boolean }, dot: { type: Boolean }, _ready: { type: Boolean, state: true } };
  static styles = css`:host { display:inline-flex; } .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; color: var(--builtin-primary, #2563eb); }`;
  constructor() { super(); this.variant = "default"; this._ready = false; }
  connectedCallback() { super.connectedCallback(); ensureShoelace().then(() => { this._ready = true; }); }
  render() { if (!this._ready) return html``; if (this.dot) return html`<span class="dot"></span>`; return html`<sl-badge variant="${VARIANT_MAP[this.variant || "default"] || "neutral"}" ?pill=${this.pill}>${this.text || ""}<slot></slot></sl-badge>`; }
}