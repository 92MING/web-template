/**
 * @fileoverview BuiltinDrawer — sliding overlay panel (Lit).
 *
 * @attr {boolean} open — Visibility.
 * @attr {string} placement — "left" | "right" | "top" | "bottom" (default "right").
 * @attr {string} size — Width/height (default "320px").
 * @attr {boolean} no-mask-close — Disable click-to-close on the overlay mask.
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @slots
 * - default — Main drawer content.
 * - title — Header title area.
 *
 * @method openDrawer() — Show the drawer.
 * @method close() — Hide the drawer.
 *
 * @event builtin-open — Drawer opened.
 * @event builtin-close — Drawer closed.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinDrawer extends BuiltinBaseElement {
  static properties = {
    open: { type: Boolean },
    placement: { type: String },
    size: { type: String },
    noMaskClose: { type: Boolean, attribute: "no-mask-close" },
    noHeader: { type: Boolean, attribute: "no-header" },
    labels: { type: Object },
  };

  static styles = css`
    :host {
      display: block;
      pointer-events: none;
    }
    .drawer-mask {
      position: fixed;
      inset: 0;
      z-index: 9998;
      background: rgba(0,0,0,0.45);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.25s ease;
    }
    .drawer-mask.open { opacity: 1; pointer-events: auto; }
    .drawer-panel {
      position: fixed;
      background: var(--builtin-surface, #ffffff);
      z-index: 9999;
      display: flex;
      flex-direction: column;
      transition: transform 0.25s ease;
      box-shadow: 0 20px 60px rgba(0,0,0,0.18);
      pointer-events: none;
    }
    .drawer-panel.left {
      left: 0; top: 0; bottom: 0;
      transform: translateX(-100%);
    }
    .drawer-panel.right {
      right: 0; top: 0; bottom: 0;
      transform: translateX(100%);
    }
    .drawer-panel.top {
      top: 0; left: 0; right: 0;
      transform: translateY(-100%);
    }
    .drawer-panel.bottom {
      bottom: 0; left: 0; right: 0;
      transform: translateY(100%);
    }
    .drawer-panel.open {
      transform: translate(0, 0);
      pointer-events: auto;
    }
    .drawer-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 18px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      min-height: 56px;
    }
    .drawer-header:has([slot="title"]:empty) { display: none; }
    .drawer-header ::slotted([slot="title"]),
    .drawer-header h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 650;
    }
    .drawer-close {
      border: 0;
      background: transparent;
      padding: 4px;
      min-height: 0;
      font-size: 22px;
      line-height: 1;
      color: var(--builtin-color-muted, #6b7280);
      cursor: pointer;
      border-radius: var(--builtin-radius, 6px);
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .drawer-close:hover { background: var(--builtin-row-hover-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .drawer-body {
      flex: 1 1 auto;
      overflow-y: auto;
      padding: 18px;
    }
    @keyframes drawer-mask-in { from { opacity: 0; } to { opacity: 1; } }
    @media (max-width: 720px) {
      .drawer-panel { width: calc(100% - 40px) !important; height: calc(100% - 40px) !important; }
    }
  `;

  constructor() {
    super();
    this.open = false;
    this.placement = "right";
    this.size = "320px";
    this.noMaskClose = false;
    this.labels = {};
  }

  _t(key, values) {
    if (this.labels && typeof this.labels === "object" && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => (
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        ));
      }
      return text;
    }
    return super._t(key, values);
  }

  openDrawer() {
    this.open = true;
    this.dispatchEvent(new CustomEvent("builtin-open", { bubbles: true }));
  }

  close() {
    this.open = false;
    this.dispatchEvent(new CustomEvent("builtin-close", { bubbles: true }));
  }

  _onKeydown = (e) => {
    if (e.key === "Escape" && this.open) this.close();
  };

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("keydown", this._onKeydown);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._onKeydown);
  }

  render() {
    const placement = ["left", "right", "top", "bottom"].includes(this.placement) ? this.placement : "right";
    const isVertical = placement === "top" || placement === "bottom";
    const sizeStyle = isVertical
      ? { height: this.size || "320px", width: "100%" }
      : { width: this.size || "320px", height: "100%" };

    const panelClass = {
      "drawer-panel": true,
      [placement]: true,
      open: this.open,
    };

    return html`
      <div class="${classMap({ "drawer-mask": true, open: this.open })}" @click="${(e) => {
        if (e.target === e.currentTarget && !this.noMaskClose) this.close();
      }}"></div>
      <div class="${classMap(panelClass)}" role="dialog" aria-modal="true" style="${styleMap(sizeStyle)}">
        ${!this.noHeader ? html`
          <div class="drawer-header">
            <slot name="title"></slot>
            <button class="drawer-close" aria-label="${this._t("drawer.close")}" @click="${() => this.close()}">
              <builtin-icon name="close" size="20" variant="outlined"></builtin-icon>
            </button>
          </div>
        ` : ""}
        <div class="drawer-body">
          <slot></slot>
        </div>
      </div>
    `;
  }
}
