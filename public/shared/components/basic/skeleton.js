import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinSkeleton extends BuiltinBaseElement {
  static properties = {
    shape: { type: String },
    lines: { type: Number },
    width: { type: String },
    height: { type: String },
    _ready: { type: Boolean, state: true },
  };

  static styles = css`:host { display: block; } .wrap { display: grid; gap: 8px; } sl-skeleton { display: block; }`;

  constructor() {
    super();
    this.shape = "text";
    this.lines = 3;
    this._ready = false;
  }

  connectedCallback() {
    super.connectedCallback();
    ensureShoelace().then(() => { this._ready = true; });
  }

  _styleFor(shape, index = 0) {
    if (shape === "circle" || shape === "avatar") {
      const size = this.width || this.height || "40px";
      return `width:${size};height:${size};--border-radius:50%;`;
    }
    if (shape === "card") return `width:${this.width || "100%"};height:${this.height || "120px"};--border-radius:var(--builtin-radius-lg, 8px);`;
    if (shape === "rect") return `width:${this.width || "100%"};height:${this.height || "16px"};--border-radius:var(--builtin-radius, 6px);`;
    const isLast = index === (this.lines || 3) - 1;
    return `width:${isLast && (this.lines || 3) > 1 ? "75%" : "100%"};height:${this.height || "12px"};--border-radius:var(--builtin-radius, 6px);`;
  }

  render() {
    if (!this._ready) return html``;
    const shape = this.shape || "text";
    if (shape === "text") {
      return html`<div class="wrap">${Array.from({ length: Math.max(1, this.lines || 3) }, (_, i) => html`<sl-skeleton effect="sheen" style="${this._styleFor(shape, i)}"></sl-skeleton>`)}</div>`;
    }
    return html`<sl-skeleton effect="sheen" style="${this._styleFor(shape)}"></sl-skeleton>`;
  }
}