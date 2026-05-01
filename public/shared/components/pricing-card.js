import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinPricingCard - Pricing tier card with features and CTA.
 *
 * Attributes:
 * - `name` (string)
 * - `price` (string)
 * - `period` (string)
 * - `featured` (boolean)
 * - `features` (JSON array of feature strings)
 * - `cta-label` (string)
 * - `mode` (`default` | `highlight`). Default `default`.
 * - `labels` (JSON object for local i18n overrides)
 *
 * Slots:
 * - `extra`: Additional content below the feature list.
 *
 * Events:
 * - `builtin-select` - Fired when the CTA button is clicked.
 */
export class BuiltinPricingCard extends BuiltinBaseElement {
  static get properties() {
    return {
      name: { type: String },
      price: { type: String },
      period: { type: String },
      featured: { type: Boolean },
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
      ctaLabel: { type: String, attribute: "cta-label" },
      mode: { type: String },
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
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        position: relative;
        box-sizing: border-box;
      }
      .card.featured {
        border-color: var(--builtin-primary, #2563eb);
        background: var(--builtin-header-bg, #f9fafb);
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
      }
      .card.highlight {
        border-color: var(--builtin-accent, #7c3aed);
        background: var(--builtin-accent-soft, #f5f3ff);
        box-shadow: 0 4px 16px rgba(124, 58, 237, 0.08);
      }
      .badge {
        position: absolute;
        top: -10px;
        right: 16px;
        background: var(--builtin-primary, #2563eb);
        color: #fff;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 4px 10px;
        border-radius: 999px;
      }
      .name {
        font-size: 16px;
        font-weight: 650;
        color: var(--builtin-color-text, #111827);
      }
      .price-row {
        display: flex;
        align-items: baseline;
        gap: 4px;
        color: var(--builtin-color-text, #111827);
      }
      .price {
        font-size: 32px;
        font-weight: 700;
      }
      .period {
        font-size: 14px;
        color: var(--builtin-color-muted, #6b7280);
      }
      .features {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .features li {
        font-size: 14px;
        color: var(--builtin-color-text, #111827);
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .features li svg {
        flex-shrink: 0;
        color: var(--builtin-primary, #2563eb);
      }
      .cta {
        margin-top: 4px;
      }
      .cta button {
        width: 100%;
        cursor: pointer;
        padding: 10px 16px;
        border-radius: var(--builtin-radius, 6px);
        border: 1px solid var(--builtin-border, #d1d5db);
        background: var(--builtin-surface, #ffffff);
        color: var(--builtin-color-text, #111827);
        font-weight: 600;
      }
      .cta button.featured {
        background: var(--builtin-primary, #2563eb);
        border-color: var(--builtin-primary, #2563eb);
        color: #fff;
      }
      .cta button.featured:hover {
        background: var(--builtin-primary-hover, #1d4ed8);
      }
      .cta button.highlight {
        background: var(--builtin-accent, #7c3aed);
        border-color: var(--builtin-accent, #7c3aed);
        color: #fff;
      }
      .cta button.highlight:hover {
        background: var(--builtin-accent-hover, #6d28d9);
      }
      @media (max-width: 720px) {
        .card {
          padding: 20px 16px;
          width: 100%;
        }
        .price {
          font-size: 26px;
        }
        .name {
          font-size: 15px;
        }
        .features li {
          font-size: 13px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.name = "";
    this.price = "";
    this.period = "";
    this.featured = false;
    this.features = [];
    this.ctaLabel = "";
    this.mode = "default";
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

  _onSelect() {
    this.dispatchEvent(
      new CustomEvent("builtin-select", {
        bubbles: true,
        detail: { name: this.name },
      })
    );
  }

  render() {
    const features = Array.isArray(this.features) ? this.features : [];
    const isFeatured = this.featured;
    const isHighlight = this.mode === "highlight";
    const cardClasses = {
      card: true,
      featured: isFeatured,
      highlight: isHighlight,
      mobile: this._ptMobile,
    };
    const btnClasses = {
      featured: isFeatured,
      highlight: isHighlight,
    };
    const ctaText = this.ctaLabel || this._t("pricingCard.select");
    return html`
      <div class="${classMap(cardClasses)}" data-theme="${this._ptTheme}">
        ${isFeatured
          ? html`<span class="badge">${this._t("pricingCard.featured")}</span>`
          : ""}
        ${this.name ? html`<div class="name">${this.name}</div>` : ""}
        <div class="price-row">
          ${this.price ? html`<span class="price">${this.price}</span>` : ""}
          ${this.period ? html`<span class="period">${this.period}</span>` : ""}
        </div>
        ${features.length
          ? html`
              <ul class="features">
                ${repeat(
                  features,
                  (_f, i) => i,
                  (f) => html`
                    <li>
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 16 16"
                        fill="none"
                        xmlns="http://www.w3.org/2000/svg"
                      >
                        <path
                          d="M3 8L6.5 11.5L13 5"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        />
                      </svg>
                      ${f}
                    </li>
                  `
                )}
              </ul>
            `
          : ""}
        <div class="cta">
          <button class="${classMap(btnClasses)}" @click=${this._onSelect}>
            ${ctaText}
          </button>
        </div>
        <slot name="extra"></slot>
      </div>
    `;
  }
}
