import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinDatePicker extends BuiltinBaseElement {
  static properties = { value: { type: String }, range: { type: Boolean }, labels: { type: Object }, _ready: { type: Boolean, state: true } };
  static styles = css`:host { display: inline-block; min-width: 180px; } .range { display: flex; gap: 8px; align-items: center; }`;
  constructor() { super(); this.value = ""; this.range = false; this._ready = false; }
  connectedCallback() { super.connectedCallback(); ensureShoelace().then(() => { this._ready = true; }); }
  _l(key, fallback = "") { return this.labels?.[key] ?? this._t(key) ?? fallback; }
  _rangeParts() { const [start = "", end = ""] = String(this.value || "").split(/\s+to\s+|,/i).map((part) => part.trim()); return { start, end }; }
  _emitSingle(e) { this.value = e.target.value; this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true, composed: true })); }
  _emitRange(start, end) { this.value = start && end ? `${start} to ${end}` : start || end || ""; this.dispatchEvent(new CustomEvent("builtin-change", { detail: { start, end }, bubbles: true, composed: true })); }
  render() {
    if (!this._ready) return html``;
    if (!this.range) return html`<sl-input type="date" value="${this.value || ""}" @sl-change=${this._emitSingle}></sl-input>`;
    const { start, end } = this._rangeParts();
    return html`<div class="range"><sl-input type="date" value="${start}" placeholder="${this._l("date.start", "Start")}" @sl-change=${(e) => this._emitRange(e.target.value, this._rangeParts().end)}></sl-input><span>-</span><sl-input type="date" value="${end}" placeholder="${this._l("date.end", "End")}" @sl-change=${(e) => this._emitRange(this._rangeParts().start, e.target.value)}></sl-input></div>`;
  }
}