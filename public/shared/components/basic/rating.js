import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinRating extends BuiltinBaseElement {
  static properties = {
    value: { type: Number },
    max: { type: Number },
    icon: { type: String },
    interactive: { type: Boolean },
    size: { type: String },
    labels: { type: Object },
    _ready: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: inline-flex; }
    sl-rating { --symbol-size: var(--builtin-rating-size, 24px); color: var(--builtin-rating-fill, #f59e0b); }
    sl-rating[size="sm"] { --builtin-rating-size: 16px; }
    sl-rating[size="md"] { --builtin-rating-size: 24px; }
    sl-rating[size="lg"] { --builtin-rating-size: 32px; }
  `;

  constructor() {
    super();
    this.value = 0;
    this.max = 5;
    this.icon = "star";
    this.interactive = false;
    this.size = "md";
    this._ready = false;
  }

  connectedCallback() {
    super.connectedCallback();
    ensureShoelace().then(() => { this._ready = true; });
  }

  _onChange(e) {
    this.value = e.target.value;
    this.dispatchEvent(new CustomEvent("builtin-rate", { detail: { value: this.value }, bubbles: true, composed: true }));
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true, composed: true }));
  }

  render() {
    if (!this._ready) return html``;
    return html`<sl-rating size="${this.size || "md"}" .value=${this.value || 0} .max=${this.max || 5} ?readonly=${!this.interactive} @sl-change=${this._onChange}></sl-rating><slot></slot>`;
  }
}