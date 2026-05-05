import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

const VARIANT_MAP = { default: "neutral", primary: "primary", accent: "success" };

export class BuiltinChip extends BuiltinBaseElement {
  static properties = { text: { type: String }, removable: { type: Boolean }, variant: { type: String }, _ready: { type: Boolean, state: true } };
  static styles = css`:host { display:inline-flex; }`;
  constructor() { super(); this.variant = "default"; this._ready = false; }
  connectedCallback() { super.connectedCallback(); ensureShoelace().then(() => { this._ready = true; }); }
  _onRemove() { this.dispatchEvent(new CustomEvent("remove", { bubbles: true, composed: true })); this.dispatchEvent(new CustomEvent("builtin-remove", { bubbles: true, composed: true })); }
  render() { if (!this._ready) return html``; return html`<sl-tag variant="${VARIANT_MAP[this.variant || "default"] || "neutral"}" pill ?removable=${this.removable} @sl-remove=${this._onRemove}>${this.text || ""}<slot></slot></sl-tag>`; }
}