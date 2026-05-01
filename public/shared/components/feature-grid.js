import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinFeatureGrid - A responsive grid of feature cards with optional header slot.
 *
 * Attributes:
 * - `layout` (`3-col` | `2-col` | `4-col` | `icon-list`). Default `3-col`.
 * - `features` (JSON array of {icon, title, description})
 * - `labels` (JSON object for local i18n overrides)
 *
 * Slots:
 * - `header`: Content rendered above the grid.
 */
export class BuiltinFeatureGrid extends BuiltinBaseElement {
  static get properties() {
    return {
      layout: { type: String },
      features: {
        converter: {
          fromAttribute(value) {
            if (!value) return [];
            try {
              return JSON.parse(value);
            } catch (_e) {
              return [];
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
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
      .wrapper {
        display: flex;
        flex-direction: column;
        gap: 22px;
      }
      .grid {
        display: grid;
        gap: 18px;
      }
      .grid.cols-2 {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .grid.cols-3 {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      .grid.cols-4 {
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }
      .grid.icon-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .feature-card {
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
        padding: 22px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow-wrap: break-word;
        min-width: 0;
        transition: box-shadow 0.15s ease, transform 0.15s ease;
      }
      .feature-card:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        transform: translateY(-2px);
      }
      .grid.icon-list .feature-card {
        flex-direction: row;
        align-items: flex-start;
        border: none;
        background: transparent;
        padding: 8px 0;
        border-radius: 0;
      }
      .feature-icon {
        font-size: 28px;
        line-height: 1;
        color: var(--builtin-primary, #2563eb);
      }
      .grid.icon-list .feature-icon {
        flex-shrink: 0;
        font-size: 24px;
      }
      .feature-title {
        font-weight: 650;
        font-size: 16px;
        color: var(--builtin-color-text, #111827);
      }
      .feature-desc {
        font-size: 14px;
        line-height: 1.55;
        color: var(--builtin-color-muted, #6b7280);
      }
      .empty {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
      }
      @media (max-width: 720px) {
        .grid {
          grid-template-columns: 1fr !important;
        }
        .grid.icon-list {
          grid-template-columns: 1fr !important;
        }
        .feature-card {
          padding: 16px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.layout = "3-col";
    this.features = [];
    this.labels = {};
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

  _gridClass() {
    switch (this.layout) {
      case "2-col":
        return "cols-2";
      case "4-col":
        return "cols-4";
      case "icon-list":
        return "icon-list";
      case "3-col":
      default:
        return "cols-3";
    }
  }

  render() {
    const features = Array.isArray(this.features) ? this.features : [];
    const gridClasses = {
      grid: true,
      [this._gridClass()]: true,
      mobile: this._ptMobile,
    };
    return html`
      <div class="wrapper" data-theme="${this._ptTheme}">
        <div class="header"><slot name="header"></slot></div>
        <div class="${classMap(gridClasses)}">
          ${repeat(
            features,
            (_f, i) => i,
            (f) => html`
              <div class="feature-card">
                ${f.icon
                  ? html`<div class="feature-icon"><builtin-icon name="${f.icon}" size="28" variant="outlined"></builtin-icon></div>`
                  : ""}
                ${f.title ? html`<div class="feature-title">${f.title}</div>` : ""}
                ${f.description
                  ? html`<div class="feature-desc">${f.description}</div>`
                  : ""}
              </div>
            `
          )}
        </div>
        ${features.length === 0
          ? html`<div class="empty">${this._t("featureGrid.empty")}</div>`
          : ""}
      </div>
    `;
  }
}
