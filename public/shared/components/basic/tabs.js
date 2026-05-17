import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureShoelace } from "../vendor-loader.js";

export class BuiltinTabs extends BuiltinBaseElement {
  static properties = { type: { type: String }, items: { type: Array }, active: { type: String }, labels: { type: Object }, _ready: { type: Boolean, state: true } };
  static styles = css`:host { display: block; } sl-tab-group::part(base) { color: var(--builtin-color-text, #111827); }`;
  constructor() { super(); this.type = "underline"; this.items = []; this.active = ""; this.labels = {}; this._ready = false; }
  connectedCallback() { super.connectedCallback(); ensureShoelace().then(() => { this._ready = true; this._syncPanelSlots(); }); }
  updated() { this._syncPanelSlots(); }
  _panels() { return Array.from(this.querySelectorAll("[data-tab]")); }
  _values() { const panels = this._panels(); return this.items?.length ? this.items.map((item) => item.value) : panels.map((panel) => panel.dataset.tab); }
  _activeValue() { const values = this._values(); return values.includes(this.active) ? this.active : values[0] || ""; }
  _syncPanelSlots() { const active = this._activeValue(); for (const panel of this._panels()) { panel.slot = panel.dataset.tab; panel.hidden = panel.dataset.tab !== active; } }
  _onTabShow(e) { this.active = e.detail.name; this._syncPanelSlots(); this.dispatchEvent(new CustomEvent("builtin-tab-change", { bubbles: true, composed: true, detail: { value: this.active } })); }
  render() {
    if (!this._ready) return html``;
    const values = this._values();
    const active = this._activeValue();
    const placement = this.type === "vertical" ? "start" : "top";
    return html`<sl-tab-group placement="${placement}" activation="auto" @sl-tab-show=${this._onTabShow}>${values.map((value, index) => { const label = this.items?.length ? this.items[index]?.label || value : value; return html`<sl-tab slot="nav" panel="${value}" ?active=${value === active}>${label}</sl-tab>`; })}${values.map((value) => html`<sl-tab-panel name="${value}" ?active=${value === active}><slot name="${value}"></slot></sl-tab-panel>`)}</sl-tab-group>`;
  }
}