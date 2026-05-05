import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinSocialLogin — Social / OAuth provider buttons.
 *
 * @attr {string} providers — JSON array of {id, label}.
 * @attr {string} variant — `filled` | `outlined` | `icon-only`.
 * @attr {string} direction — `horizontal` | `vertical`.
 * @attr {Object} labels — JSON object for i18n overrides.
 *
 * @slot — Extra content rendered after the provider buttons.
 *
 * @event builtin-login — Detail: `{ provider }`
 */
export class BuiltinSocialLogin extends BuiltinBaseElement {
  static properties = {
    providers: { type: Array },
    variant: { type: String },
    direction: { type: String },
    labels: { type: Object },
  };

  static styles = css`
    :host {
      display: block;
    }
    .container {
      display: flex;
      gap: 10px;
    }
    .container.vertical {
      flex-direction: column;
    }
    .container.horizontal {
      flex-direction: row;
      flex-wrap: wrap;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      font: inherit;
      padding: 8px 16px;
      min-height: 36px;
      border: 1px solid transparent;
      transition: filter 0.15s ease;
      flex: 1 1 auto;
    }
    .btn:hover {
      filter: brightness(0.95);
    }
    .btn.filled {
      color: #fff;
    }
    .btn.outlined {
      background: transparent;
      border-width: 1px;
    }
    .btn.icon-only {
      padding: 8px;
      width: 40px;
      height: 40px;
      flex: 0 0 auto;
    }
    .icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      flex-shrink: 0;
    }
    .icon svg {
      width: 100%;
      height: 100%;
    }
    .label {
      font-size: 14px;
      font-weight: 650;
    }
    @media (max-width: 720px) {
      .container.horizontal {
        flex-direction: column;
      }
      .btn {
        width: 100%;
        min-height: 44px;
        font-size: 16px;
      }
    }
  `;

  constructor() {
    super();
    this.providers = [
      { id: "google", label: "Google" },
      { id: "wechat", label: "WeChat" },
      { id: "github", label: "GitHub" },
      { id: "apple", label: "Apple" },
      { id: "microsoft", label: "Microsoft" },
    ];
    this.variant = "filled";
    this.direction = "horizontal";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _brandColor(id) {
    const isDark = this._ptTheme === "dark";
    switch (id) {
      case "google":
        return "#ea4335";
      case "wechat":
        return "#07c160";
      case "github":
        return isDark ? "#f0f6fc" : "#24292f";
      case "apple":
        return isDark ? "#ffffff" : "#000000";
      case "microsoft":
        return "#2b579a";
      default:
        return "var(--builtin-primary, #2563eb)";
    }
  }

  _brandIcon(id) {
    switch (id) {
      case "google":
        return html`<svg class="icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
          <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
          <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
          <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
        </svg>`;
      case "wechat":
        return html`<svg class="icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M8.7 14.1c-.2 0-.4 0-.6-.1l-1.8 1 .4-1.5c-1.7-.8-2.8-2.3-2.8-3.9 0-2.6 2.6-4.7 5.7-4.7 3.2 0 5.7 2.1 5.7 4.7 0 2.6-2.5 4.7-5.7 4.7-.6 0-1.2-.1-1.8-.2l-.1 1zm8.9 3.8.3 1.2-1.3-.8c-.4 0-.8.1-1.1.1-2.8 0-5.1-1.9-5.1-4.2s2.3-4.2 5.1-4.2 5.1 1.9 5.1 4.2c0 1.5-1 2.8-2.6 3.5l-.4 1.2z"/>
        </svg>`;
      case "github":
        return html`<svg class="icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2C6.48 2 2 6.58 2 12.26c0 4.52 2.87 8.36 6.84 9.71.5.1.68-.22.68-.49 0-.24-.01-.87-.01-1.71-2.78.62-3.37-1.37-3.37-1.37-.45-1.18-1.11-1.5-1.11-1.5-.91-.64.07-.62.07-.62 1 .08 1.53 1.06 1.53 1.06.89 1.57 2.34 1.12 2.91.86.09-.67.35-1.12.63-1.38-2.22-.26-4.55-1.14-4.55-5.06 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.28 2.75 1.05A9.32 9.32 0 0 1 12 6.84c.85.01 1.71.12 2.51.34 1.9-1.32 2.74-1.05 2.74-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.8-4.57 5.06.36.32.68.94.68 1.9 0 1.37-.01 2.48-.01 2.82 0 .27.18.59.69.49C19.14 20.62 22 16.78 22 12.26 22 6.58 17.52 2 12 2z"/>
        </svg>`;
      case "apple":
        return html`<svg class="icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M17.05 20.28c-.98.95-2.05.88-3.08.4-1.09-.5-2.09-.48-3.24 0-1.44.62-2.2.44-3.06-.4C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.74 1.18 0 2.21-.94 3.96-.8 1.35.06 2.5.73 3.24 1.8-2.89 1.78-2.4 5.98.25 7.13-.57 1.5-1.31 2.99-2.53 4.1zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"/>
        </svg>`;
      case "microsoft":
        return html`<svg class="icon" viewBox="0 0 24 24" fill="currentColor">
          <path d="M3 3h8.5v8.5H3V3zm9.5 0H21v8.5h-8.5V3zM3 12.5h8.5V21H3v-8.5zm9.5 0H21V21h-8.5v-8.5z"/>
        </svg>`;
      default:
        return html`<svg class="icon" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="10"/>
        </svg>`;
    }
  }

  _onClick(provider) {
    this.dispatchEvent(
      new CustomEvent("builtin-login", {
        detail: { provider: provider.id },
        bubbles: true,
        composed: true,
      })
    );
  }

  render() {
    const providers = Array.isArray(this.providers) ? this.providers : [];
    const variant = this.variant || "filled";
    const direction = this.direction || "horizontal";
    const isMobile = this._ptMobile;

    return html`
      <div
        class="container ${direction} ${classMap({
          "mobile-stacked": isMobile,
        })}"
        part="container"
      >
        ${repeat(
          providers,
          (p) => p.id,
          (p) => {
            const brandColor = this._brandColor(p.id);
            const isOutlined = variant === "outlined";
            const isIconOnly = variant === "icon-only";
            const styles = styleMap({
              backgroundColor: variant === "filled" ? brandColor : "transparent",
              borderColor: isOutlined ? brandColor : "transparent",
              color: isOutlined ? brandColor : "#fff",
            });
            return html`
              <button
                class="btn ${variant}"
                style="${styles}"
                part="button"
                aria-label="${this._l(`login.${p.id}`, p.label)}"
                @click="${() => this._onClick(p)}"
              >
                ${this._brandIcon(p.id)}
                ${!isIconOnly
                  ? html`<span class="label">${this._l(`login.${p.id}`, p.label)}</span>`
                  : null}
              </button>
            `;
          }
        )}
        <slot></slot>
      </div>
    `;
  }
}
