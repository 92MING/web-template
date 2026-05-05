import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinSliderRange extends BuiltinBaseElement {
  static properties = {
    min: { type: Number }, max: { type: Number }, step: { type: Number }, value: { type: Number }, values: { type: Array }, labels: { type: Object }, _ready: { type: Boolean, state: true },
  };

  static styles = css`:host { display: block; } .dual { display: grid; gap: 8px; } .labels { display: flex; justify-content: space-between; color: var(--builtin-color-muted, #6b7280); font-size: 11px; }`;

  constructor() {
    super();
    this.min = 0; this.max = 100; this.step = 1; this.value = 0; this.values = null; this._ready = false;
  }

  connectedCallback() { super.connectedCallback(); ensureShoelace().then(() => { this._ready = true; }); }

  _onSingleChange(e) {
    this.value = Number(e.target.value);
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true, composed: true }));
  }

  _onDualChange(index, e) {
    const next = Array.isArray(this.values) ? [...this.values] : [this.min, this.max];
    next[index] = Number(e.target.value);
    if (next[0] > next[1]) next.sort((a, b) => a - b);
    this.values = next;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { values: [...next] }, bubbles: true, composed: true }));
  }

  render() {
    if (!this._ready) return html``;
    if (!Array.isArray(this.values)) {
      return html`<sl-range min="${this.min}" max="${this.max}" step="${this.step}" value="${this.value || 0}" @sl-change=${this._onSingleChange}></sl-range><div class="labels"><span>${this.min}</span><span>${this.max}</span></div>`;
    }
    const low = this.values[0] ?? this.min;
    const high = this.values[1] ?? this.max;
    return html`<div class="dual"><sl-range min="${this.min}" max="${this.max}" step="${this.step}" value="${low}" @sl-change=${(e) => this._onDualChange(0, e)}></sl-range><sl-range min="${this.min}" max="${this.max}" step="${this.step}" value="${high}" @sl-change=${(e) => this._onDualChange(1, e)}></sl-range></div><div class="labels"><span>${low}</span><span>${high}</span></div>`;
  }
}