import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinColorPicker extends BuiltinBaseElement {
  static properties = { value: { type: String }, labels: { type: Object }, _ready: { type: Boolean, state: true } };
  static styles = css`:host { display: inline-block; } sl-color-picker::part(base) { font-family: inherit; }`;
  constructor() { super(); this.value = "#2563eb"; this._ready = false; }
  connectedCallback() { super.connectedCallback(); ensureShoelace().then(() => { this._ready = true; }); }
  _onChange(e) { this.value = e.target.value; this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true, composed: true })); }
  render() { if (!this._ready) return html``; return html`<sl-color-picker value="${this.value || "#2563eb"}" format="hex" swatches="#ef4444;#f97316;#f59e0b;#84cc16;#10b981;#06b6d4;#3b82f6;#6366f1;#8b5cf6;#d946ef;#111827;#ffffff" @sl-change=${this._onChange}></sl-color-picker>`; }
}