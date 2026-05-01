/**
 * @fileoverview BuiltinDropdown - A dropdown menu component with trigger and menu slots (Lit).
 *
 * Slots:
 *   - trigger: Element that opens the dropdown
 *   - (default): Menu items
 *
 * Attributes:
 *   - open (boolean): Whether the dropdown is visible
 *   - placement ("bottom" | "top" | "left" | "right"): Position relative to trigger
 *   - no-close-on-click (boolean): Prevent closing when clicking inside the menu
 *
 * Events:
 *   - builtin-open: Fired when the dropdown opens
 *   - builtin-close: Fired when the dropdown closes
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinDropdown extends BuiltinBaseElement {
  static properties = {
    open: { type: Boolean },
    placement: { type: String },
    noCloseOnClick: { type: Boolean, attribute: "no-close-on-click" },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: inline-block; position: relative; }
    .trigger { display: inline-flex; cursor: pointer; }
    .menu {
      display: none;
      position: absolute;
      z-index: 1000;
      min-width: 160px;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      box-shadow: 0 4px 12px rgba(0,0,0,0.08);
      padding: 4px 0;
    }
    .menu.open { display: block; }
    .menu.bottom { top: 100%; left: 0; margin-top: 4px; }
    .menu.top { bottom: 100%; left: 0; margin-bottom: 4px; }
    .menu.left { top: 0; right: 100%; margin-right: 4px; }
    .menu.right { top: 0; left: 100%; margin-left: 4px; }
    ::slotted(*) { box-sizing: border-box; }
    @media (max-width: 720px) {
      .menu {
        left: 4px !important;
        right: 4px !important;
        top: 100% !important;
        bottom: auto !important;
        margin: 4px 0 0 0 !important;
        min-width: auto;
        width: calc(100vw - 16px);
      }
    }
  `;

  constructor() {
    super();
    this.open = false;
    this.placement = "bottom";
    this.noCloseOnClick = false;
    this.labels = {};
  }

  _onTriggerClick = (e) => {
    e.stopPropagation();
    this.open = !this.open;
    this.dispatchEvent(new CustomEvent(this.open ? "builtin-open" : "builtin-close", { bubbles: true, composed: true }));
  };

  _onMenuClick = (e) => {
    if (this.noCloseOnClick) return;
    this.open = false;
    this.dispatchEvent(new CustomEvent("builtin-close", { bubbles: true, composed: true }));
  };

  _onDocumentClick = (e) => {
    if (!this.open) return;
    if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
      this.open = false;
      this.dispatchEvent(new CustomEvent("builtin-close", { bubbles: true, composed: true }));
    }
  };

  _onKeydown = (e) => {
    if (e.key === "Escape" && this.open) {
      this.open = false;
      this.dispatchEvent(new CustomEvent("builtin-close", { bubbles: true, composed: true }));
    }
  };

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("click", this._onDocumentClick);
    document.addEventListener("keydown", this._onKeydown);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("click", this._onDocumentClick);
    document.removeEventListener("keydown", this._onKeydown);
  }

  render() {
    const placement = ["bottom", "top", "left", "right"].includes(this.placement) ? this.placement : "bottom";
    const menuClass = {
      menu: true,
      open: this.open,
      [placement]: true,
    };

    return html`
      <div class="trigger" part="trigger" @click="${this._onTriggerClick}">
        <slot name="trigger"></slot>
      </div>
      <div class="${classMap(menuClass)}" part="menu" @click="${this._onMenuClick}">
        <slot></slot>
      </div>
    `;
  }
}
