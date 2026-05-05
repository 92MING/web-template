import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinProgressBar extends BuiltinBaseElement {
  static properties = {
    value: { type: Number },
    max: { type: Number },
    variant: { type: String },
    label: { type: Boolean },
    height: { type: String },
    _ready: { type: Boolean, state: true },
  };

  static styles = css`:host { display: block; } .wrap { display: flex; align-items: center; gap: 10px; } sl-progress-bar { flex: 1; --height: var(--builtin-progress-height, 8px); } .text { min-width: 36px; text-align: right; color: var(--builtin-color-muted, #6b7280); font-size: 12px; font-weight: 600; }`;

  constructor() {
    super();
    this.max = 100;
    this._ready = false;
  }

  connectedCallback() {
    super.connectedCallback();
    ensureShoelace().then(() => { this._ready = true; });
  }

  render() {
    if (!this._ready) return html``;
    const max = Math.max(1, this.max || 100);
    const pct = Math.min(100, Math.max(0, ((this.value || 0) / max) * 100));
    return html`<div class="wrap" style="--builtin-progress-height:${this.height || "8"}px"><sl-progress-bar value="${pct}"></sl-progress-bar>${this.label ? html`<div class="text">${Math.round(pct)}%</div>` : ""}</div>`;
  }
}