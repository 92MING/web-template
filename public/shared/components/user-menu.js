import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview User menu dropdown web component.
 *
 * @element builtin-user-menu
 *
 * @attr {string} name - User display name.
 * @attr {string} email - User email address.
 * @attr {string} avatar - URL to avatar image.
 * @attr {string} items - JSON array of { label, href, action } objects.
 * @attr {string} labels - JSON object for i18n overrides.
 *
 * @slot signout - Content for the sign-out area at the bottom of the dropdown.
 *
 * @fires builtin-action - Dispatched when a menu item is clicked with detail `{ action, item }`.
 */
export class BuiltinUserMenu extends BuiltinBaseElement {
  static properties = {
    name: { type: String },
    email: { type: String },
    avatar: { type: String },
    items: { type: Array },
    labels: { type: Object },
    _open: { type: Boolean, state: true },
  };

  static styles = css`
    :host {
      display: inline-block;
      position: relative;
    }
    .trigger {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      min-height: 34px;
      font: inherit;
    }
    .trigger:hover {
      background: var(--builtin-button-hover-bg, #f9fafb);
    }
    .avatar {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 600;
      overflow: hidden;
    }
    .avatar img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .dropdown {
      display: none;
      position: absolute;
      top: calc(100% + 6px);
      right: 0;
      min-width: 200px;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.08);
      z-index: 100;
      overflow: hidden;
    }
    .dropdown.open {
      display: block;
    }
    .dropdown-header {
      padding: 12px 14px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .dropdown-header .name {
      font-weight: 650;
    }
    .dropdown-header .email {
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .menu-item {
      display: block;
      padding: 10px 14px;
      color: var(--builtin-color-text, #111827);
      text-decoration: none;
      cursor: pointer;
      background: none;
      border: none;
      width: 100%;
      text-align: left;
      font: inherit;
    }
    .menu-item:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    .signout {
      padding: 10px 14px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    @media (max-width: 720px) {
      .dropdown {
        position: fixed;
        top: auto;
        bottom: 0;
        left: 0;
        right: 0;
        min-width: auto;
        border-radius: var(--builtin-radius-lg, 8px) var(--builtin-radius-lg, 8px) 0 0;
        box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.12);
      }
      .menu-item {
        padding: 14px 16px;
        font-size: 16px;
      }
      .trigger {
        min-height: 44px;
      }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this._open = false;
  }

  _l(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(
          /\{([a-zA-Z0-9_]+)\}/g,
          (match, name) =>
            Object.prototype.hasOwnProperty.call(values, name)
              ? String(values[name])
              : match
        );
      }
      return text;
    }
    return this._t(key, values);
  }

  _getInitials() {
    return (this.name || "")
      .split(" ")
      .map((n) => n[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }

  _toggle() {
    this._open = !this._open;
    if (this._open) {
      document.addEventListener("click", this._onDocClick);
    } else {
      document.removeEventListener("click", this._onDocClick);
    }
  }

  _onDocClick = (e) => {
    if (!this.shadowRoot.contains(e.target)) {
      this._open = false;
      document.removeEventListener("click", this._onDocClick);
    }
  };

  _onItemClick(item) {
    this.dispatchEvent(
      new CustomEvent("builtin-action", {
        detail: { action: item.action || item.label, item },
        bubbles: true,
        composed: true,
      })
    );
    this._open = false;
    document.removeEventListener("click", this._onDocClick);
  }

  open() {
    this._open = true;
    document.addEventListener("click", this._onDocClick);
  }

  close() {
    this._open = false;
    document.removeEventListener("click", this._onDocClick);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("click", this._onDocClick);
  }

  render() {
    const items = Array.isArray(this.items) ? this.items : [];
    const initials = this._getInitials();
    const hasAvatar = !!this.avatar;

    return html`
      <button
        type="button"
        class="trigger"
        aria-haspopup="true"
        aria-expanded="${this._open}"
        @click="${this._toggle}"
      >
        <span class="avatar">
          ${hasAvatar
            ? html`<img
                src="${this.avatar}"
                alt=""
                loading="lazy"
                @error="${(e) => (e.target.style.display = "none")}"
              />`
            : ""}
          ${!hasAvatar ? initials : ""}
        </span>
        <span class="name">${this.name || ""}</span>
      </button>
      <div class="dropdown ${classMap({ open: this._open })}">
        <div class="dropdown-header">
          <div class="name">${this.name || ""}</div>
          <div class="email">${this.email || ""}</div>
        </div>
        ${repeat(
          items,
          (it, i) => i,
          (it) => html`
            ${it.section
              ? html`
                  <div
                    style="padding: 6px 14px; font-size: 11px; text-transform: uppercase; color: var(--builtin-color-muted, #6b7280); font-weight: 600; letter-spacing: 0.05em;"
                  >
                    ${it.section}
                  </div>
                `
              : html`
                  <a
                    class="menu-item"
                    href="${it.href || "javascript:void(0)"}"
                    @click="${(e) => {
                      if (!it.href) {
                        e.preventDefault();
                        this._onItemClick(it);
                      }
                    }}"
                  >
                    ${it.label || ""}
                  </a>
                `}
          `
        )}
        <div class="signout">
          <slot name="signout"></slot>
        </div>
      </div>
    `;
  }
}
