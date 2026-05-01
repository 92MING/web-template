/**
 * @fileoverview BuiltinModal — Generic modal dialog with overlay, header, body (default slot), and footer slot.
 *
 * @attr {boolean} open — Visibility.
 * @attr {string} title — Header text.
 * @attr {string} size — `small` | `medium` | `large` | `fullscreen` (default `medium`).
 * @attr {boolean} no-close — Hide the × button.
 * @attr {boolean} no-mask-close — Disable click-to-close on overlay.
 *
 * @method openModal() — Show the modal.
 * @method close() — Hide the modal.
 *
 * @event builtin-open — Modal opened.
 * @event builtin-close — Modal closed.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

export class BuiltinModal extends BuiltinBaseElement {
  static properties = {
    open: { type: Boolean, reflect: true },
    title: { type: String },
    size: { type: String },
    noClose: { type: Boolean, reflect: true, attribute: "no-close" },
    noMaskClose: { type: Boolean, reflect: true, attribute: "no-mask-close" },
    noHeader: { type: Boolean, reflect: true, attribute: "no-header" },
    noFooter: { type: Boolean, reflect: true, attribute: "no-footer" },
    noAnimation: { type: Boolean, reflect: true, attribute: "no-animation" },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .overlay {
      position: fixed; inset: 0; z-index: 9999;
      background: rgba(0,0,0,0.45);
      display: flex; align-items: center; justify-content: center;
      padding: 20px;
      opacity: 0; pointer-events: none;
      transition: opacity 0.15s ease;
    }
    .overlay.open {
      opacity: 1; pointer-events: auto;
    }
    .box {
      background: var(--builtin-surface, #fff);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 20px 60px rgba(0,0,0,0.18);
      width: 100%;
      max-height: calc(100vh - 40px);
      display: flex; flex-direction: column;
      opacity: 0;
    }
    .box.animate {
      transform: translateY(-12px) scale(0.98);
      transition: transform 0.18s ease, opacity 0.18s ease;
    }
    .overlay.open .box.animate {
      transform: translateY(0) scale(1);
      opacity: 1;
    }
    .overlay.open .box.no-animate { opacity: 1; }
    .box.small { max-width: 420px; }
    .box.medium { max-width: 560px; }
    .box.large { max-width: 800px; }
    .box.fullscreen { max-width: none; border-radius: 0; height: 100%; max-height: 100vh; }
    .header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 18px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .header h3 { margin: 0; font-size: 16px; font-weight: 650; color: var(--builtin-color-text, #111827); }
    .close {
      border: 0; background: transparent; padding: 4px; min-height: 0;
      font-size: 20px; line-height: 1; color: var(--builtin-color-muted, #6b7280);
      cursor: pointer; border-radius: var(--builtin-radius, 6px); display: inline-flex; align-items: center; justify-content: center;
    }
    .close:hover { background: var(--builtin-row-hover-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .body { padding: 18px; overflow: auto; flex: 1 1 auto; color: var(--builtin-color-text, #111827); }
    .footer {
      display: flex; align-items: center; justify-content: flex-end; gap: 8px;
      padding: 12px 18px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    @media (max-width: 720px) {
      .overlay { padding: 10px; }
      .box { max-height: calc(100vh - 20px); }
    }
  `;

  constructor() {
    super();
    this.size = "medium";
    this._escHandler = (e) => {
      if (e.key === "Escape" && this.open && !this.noClose) this.close();
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("keydown", this._escHandler);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._escHandler);
  }

  openModal() {
    this.open = true;
    this.dispatchEvent(new CustomEvent("builtin-open", { bubbles: true }));
  }

  close() {
    this.open = false;
    this.dispatchEvent(new CustomEvent("builtin-close", { bubbles: true }));
  }

  _onOverlayClick(e) {
    if (e.target === e.currentTarget && !this.noMaskClose) this.close();
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  render() {
    const size = this.size || "medium";
    const animate = !this.noAnimation;
    return html`
      <div class="overlay ${classMap({ open: this.open })}" @click=${this._onOverlayClick}>
        <div class="box ${size} ${classMap({ animate, 'no-animate': !animate })}" role="dialog" aria-modal="true">
          ${!this.noHeader ? html`
            <div class="header">
              <h3>${this.title || ""}</h3>
              ${!this.noClose
                ? html`<button class="close" @click=${this.close} aria-label=${this._l("close", "Close")}>
                    <builtin-icon name="close" size="20" variant="outlined"></builtin-icon>
                  </button>`
                : null}
            </div>
          ` : ""}
          <div class="body"><slot></slot></div>
          ${!this.noFooter ? html`<div class="footer"><slot name="footer"></slot></div>` : ""}
        </div>
      </div>
    `;
  }
}
