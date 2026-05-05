import { BuiltinBaseElement, html, css } from "../lit-base.js";

const VARIANT_ICON = { info: "info", success: "check-circle", warning: "warning", error: "exclamation-circle", danger: "exclamation-circle" };

export class BuiltinAlert extends BuiltinBaseElement {
  static properties = {
    text: { type: String },
    variant: { type: String },
    closable: { type: Boolean },
    icon: { type: String },
    _closed: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .alert {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      border: 1px solid var(--alert-border);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--alert-bg);
      color: var(--alert-text);
      padding: 12px 14px;
      font-size: var(--builtin-font-size, 14px);
      line-height: 1.5;
    }
    .content { flex: 1 1 auto; min-width: 0; }
    .close {
      border: 0;
      background: transparent;
      color: inherit;
      cursor: pointer;
      opacity: .75;
      padding: 2px;
      display: inline-flex;
      border-radius: var(--builtin-radius, 6px);
    }
    .close:hover { opacity: 1; background: color-mix(in srgb, var(--alert-text) 10%, transparent); }
    .info { --alert-bg: color-mix(in srgb, var(--builtin-primary, #2563eb) 12%, var(--builtin-surface, #fff)); --alert-border: color-mix(in srgb, var(--builtin-primary, #2563eb) 35%, var(--builtin-border, #d1d5db)); --alert-text: var(--builtin-color-text, #111827); }
    .success { --alert-bg: color-mix(in srgb, #16a34a 12%, var(--builtin-surface, #fff)); --alert-border: color-mix(in srgb, #16a34a 40%, var(--builtin-border, #d1d5db)); --alert-text: var(--builtin-color-text, #111827); }
    .warning { --alert-bg: color-mix(in srgb, #d97706 14%, var(--builtin-surface, #fff)); --alert-border: color-mix(in srgb, #d97706 42%, var(--builtin-border, #d1d5db)); --alert-text: var(--builtin-color-text, #111827); }
    .error, .danger { --alert-bg: color-mix(in srgb, #dc2626 12%, var(--builtin-surface, #fff)); --alert-border: color-mix(in srgb, #dc2626 40%, var(--builtin-border, #d1d5db)); --alert-text: var(--builtin-color-text, #111827); }
  `;

  constructor() {
    super();
    this.variant = "info";
    this._closed = false;
  }

  _onHide() {
    this._closed = true;
    this.dispatchEvent(new CustomEvent("builtin-close", { bubbles: true, composed: true }));
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  render() {
    if (this._closed) return html``;
    const variant = this.variant || "info";
    const iconName = this.icon || VARIANT_ICON[variant] || "info";
    return html`
      <div class="alert ${variant}" role="alert">
        <builtin-icon name="${iconName}" size="20"></builtin-icon>
        <div class="content"><slot>${this.text || ""}</slot></div>
        ${this.closable ? html`<button class="close" @click=${this._onHide} aria-label="Close"><builtin-icon name="close" size="16"></builtin-icon></button>` : ""}
      </div>
    `;
  }
}