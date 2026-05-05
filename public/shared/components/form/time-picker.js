import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinTimePicker extends BuiltinBaseElement {
  static properties = { value: { type: String }, format: { type: String }, labels: { type: Object }, _ready: { type: Boolean, state: true } };
  static styles = css`:host { display: inline-block; min-width: 140px; }`;
  constructor() { super(); this.value = ""; this.format = "24h"; this._ready = false; }
  connectedCallback() { super.connectedCallback(); ensureShoelace().then(() => { this._ready = true; }); }
  _onChange(e) { this.value = e.target.value; this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true, composed: true })); }
  render() { if (!this._ready) return html``; return html`<sl-input type="time" value="${this.value || ""}" ?hour12=${this.format === "12h"} @sl-change=${this._onChange}></sl-input>`; }
}