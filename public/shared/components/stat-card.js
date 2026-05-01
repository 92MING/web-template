import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinStatCard - Dashboard stat card web component.
 *
 * Attributes:
 * - `value` (string|number)
 * - `label` (string)
 * - `change` (string, e.g. "+12%")
 * - `change-type` (`positive` | `negative` | `neutral`)
 * - `icon` (unicode or text)
 * - `labels` (JSON object for local i18n overrides)
 *
 * Slots:
 * - `sparkline`: mini chart area below the change badge.
 */
export class BuiltinStatCard extends BuiltinBaseElement {
  static get properties() {
    return {
      value: { type: String },
      label: { type: String },
      change: { type: String },
      changeType: { type: String, attribute: "change-type" },
      icon: { type: String },
      labels: {
        converter: {
          fromAttribute(value) {
            if (!value) return {};
            try {
              return JSON.parse(value);
            } catch (_e) {
              return {};
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .card {
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
        padding: 18px;
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
      }
      .content {
        flex: 1;
        min-width: 0;
      }
      .value {
        font-size: 28px;
        font-weight: 700;
        color: var(--builtin-color-text, #111827);
        line-height: 1.2;
      }
      .label {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
        margin-top: 4px;
      }
      .change-badge {
        display: inline-block;
        margin-top: 8px;
        font-size: 12px;
        font-weight: 650;
        padding: 2px 8px;
        border-radius: 999px;
        background: var(--builtin-header-bg, #f9fafb);
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
      }
      .icon {
        font-size: 22px;
        color: var(--builtin-color-muted, #6b7280);
        line-height: 1;
        flex-shrink: 0;
      }
      .sparkline {
        margin-top: 10px;
        min-height: 24px;
      }
      @media (max-width: 720px) {
        .card {
          padding: 14px;
        }
        .value {
          font-size: 22px;
        }
        .label {
          font-size: 12px;
        }
        .icon {
          font-size: 18px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.value = "0";
    this.label = "";
    this.change = "";
    this.changeType = "neutral";
    this.icon = "";
    this.labels = {};
  }

  _changeColor() {
    switch (this.changeType) {
      case "positive":
        return "#16a34a";
      case "negative":
        return "var(--builtin-color-danger, #b91c1c)";
      default:
        return "var(--builtin-color-muted, #6b7280)";
    }
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name)
            ? String(values[name])
            : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  render() {
    const cardClasses = { card: true, mobile: this._ptMobile };
    return html`
      <div class="${classMap(cardClasses)}" data-theme="${this._ptTheme}">
        <div class="content">
          <div class="value">${this.value}</div>
          ${this.label ? html`<div class="label">${this.label}</div>` : ""}
          ${this.change
            ? html`<span
                class="change-badge"
                style=${styleMap({ color: this._changeColor() })}
                >${this.change}</span
              >`
            : ""}
          <div class="sparkline"><slot name="sparkline"></slot></div>
        </div>
        ${this.icon ? html`<div class="icon"><builtin-icon name="${this.icon}" size="20" variant="outlined"></builtin-icon></div>` : ""}
      </div>
    `;
  }
}
