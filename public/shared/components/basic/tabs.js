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
  _onTabShow(e) {
    this.active = e.detail.name;
    this._syncPanelSlots();
    this.dispatchEvent(new CustomEvent("builtin-tab-change", { bubbles: true, composed: true, detail: { value: this.active } }));
    this._scrollTabNav(e.detail.name);
  }
  _scrollTabNav(activeName) {
    requestAnimationFrame(() => {
      const tabGroup = this.renderRoot.querySelector("sl-tab-group");
      if (!tabGroup) return;
      const activeTab = tabGroup.querySelector(`sl-tab[panel="${activeName}"]`);
      if (!activeTab) return;
      const tabs = Array.from(tabGroup.querySelectorAll("sl-tab"));
      const idx = tabs.indexOf(activeTab);
      const scrollContainer = tabGroup.shadowRoot?.querySelector(".tab-group__tabs");
      if (!scrollContainer) return;
      const containerRect = scrollContainer.getBoundingClientRect();
      const tabRect = activeTab.getBoundingClientRect();
      // Auto-scroll right when selecting a tab near the right edge to reveal 1-2 more tabs
      if (tabRect.right > containerRect.right - 80) {
        const targetIdx = Math.min(idx + 2, tabs.length - 1);
        if (targetIdx > idx) {
          const targetTab = tabs[targetIdx];
          const targetRect = targetTab.getBoundingClientRect();
          scrollContainer.scrollBy({ left: targetRect.right - containerRect.right + 20, behavior: "smooth" });
        }
      }
    });
  }
  render() {
    if (!this._ready) return html``;
    const values = this._values();
    const active = this._activeValue();
    const placement = this.type === "vertical" ? "start" : "top";
    return html`<sl-tab-group placement="${placement}" activation="auto" @sl-tab-show=${this._onTabShow}>${values.map((value, index) => { const label = this.items?.length ? this.items[index]?.label || value : value; return html`<sl-tab slot="nav" panel="${value}" ?active=${value === active}>${label}</sl-tab>`; })}${values.map((value) => html`<sl-tab-panel name="${value}" ?active=${value === active}><slot name="${value}"></slot></sl-tab-panel>`)}</sl-tab-group>`;
  }
}