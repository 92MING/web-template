import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinRating — Star / heart / emoji rating with half-step support.
 *
 * @attr {number} value — Current rating (supports half steps, e.g. 3.5).
 * @attr {number} max — Maximum rating (default 5).
 * @attr {string} icon — `star` | `heart` | `emoji`.
 * @attr {boolean} interactive — Allow click-to-rate.
 * @attr {string} size — `sm` | `md` | `lg`.
 * @attr {Object} labels — JSON object for i18n overrides.
 *
 * @slot — Extra content rendered after the rating icons.
 *
 * @event builtin-rate — Detail: `{ value }`
 */
export class BuiltinRating extends BuiltinBaseElement {
  static properties = {
    value: { type: Number },
    max: { type: Number },
    icon: { type: String },
    interactive: { type: Boolean },
    size: { type: String },
    labels: { type: Object },
    _hoverValue: { type: Number, state: true },
  };

  static styles = css`
    :host {
      display: inline-flex;
    }
    .rating {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .star {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: default;
      line-height: 1;
      flex-shrink: 0;
    }
    .star.interactive {
      cursor: pointer;
    }
    .star > .layer {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .star svg {
      width: 100%;
      height: 100%;
      display: block;
    }
    .empty {
      color: var(--builtin-border, #d1d5db);
    }
    .full {
      color: var(--builtin-rating-fill, #f59e0b);
    }
    .half-mask {
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: 50%;
      overflow: hidden;
    }
    .half-mask .full-inner {
      position: absolute;
      left: 0;
      top: 0;
      width: 200%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--builtin-rating-fill, #f59e0b);
    }
    .size-sm {
      width: 16px;
      height: 16px;
    }
    .size-md {
      width: 24px;
      height: 24px;
    }
    .size-lg {
      width: 32px;
      height: 32px;
    }
    @media (max-width: 720px) {
      .star {
        min-width: 32px;
        min-height: 32px;
      }
      .size-sm {
        width: 24px;
        height: 24px;
      }
      .size-md {
        width: 32px;
        height: 32px;
      }
      .size-lg {
        width: 40px;
        height: 40px;
      }
    }
  `;

  constructor() {
    super();
    this.value = 0;
    this.max = 5;
    this.icon = "star";
    this.interactive = false;
    this.size = "md";
    this._hoverValue = 0;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _iconSvg() {
    switch (this.icon) {
      case "heart":
        return html`<svg
          viewBox="0 0 24 24"
          fill="currentColor"
          stroke="none"
        >
          <path
            d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
          />
        </svg>`;
      case "emoji":
        return html`<svg
          viewBox="0 0 24 24"
          fill="currentColor"
          stroke="none"
        >
          <circle cx="12" cy="12" r="10" />
          <circle cx="9" cy="10" r="1.5" fill="#fff" />
          <circle cx="15" cy="10" r="1.5" fill="#fff" />
          <path
            d="M8 15c1.5 2 3.5 2.5 5 2.5s3.5-.5 5-2.5"
            stroke="#fff"
            stroke-width="1.5"
            fill="none"
            stroke-linecap="round"
          />
        </svg>`;
      case "star":
      default:
        return html`<svg
          viewBox="0 0 24 24"
          fill="currentColor"
          stroke="none"
        >
          <path
            d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"
          />
        </svg>`;
    }
  }

  _renderStar(index) {
    const displayValue = this._hoverValue || this.value || 0;
    const full = Math.floor(displayValue);
    const isFull = index < full;
    const isHalf = !isFull && index < displayValue;
    const sizeClass = `size-${this.size || "md"}`;
    const interactive = this.interactive;

    return html`
      <div
        class="star ${sizeClass} ${classMap({ interactive })}"
        role="${interactive ? "button" : "img"}"
        tabindex="${interactive ? 0 : -1}"
        aria-label="${this._l("rating.label", "Rate")} ${index + 1}"
        @mouseenter="${interactive
          ? () => {
              this._hoverValue = index + 1;
            }
          : null}"
        @mouseleave="${interactive
          ? () => {
              this._hoverValue = 0;
            }
          : null}"
        @click="${interactive ? () => this._onRate(index + 1) : null}"
        @keydown="${interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                this._onRate(index + 1);
              }
            }
          : null}"
      >
        <div class="layer empty">${this._iconSvg()}</div>
        ${isFull
          ? html`<div class="layer full">${this._iconSvg()}</div>`
          : null}
        ${isHalf
          ? html`
              <div class="half-mask">
                <div class="full-inner">${this._iconSvg()}</div>
              </div>
            `
          : null}
      </div>
    `;
  }

  _onRate(val) {
    this.value = val;
    this.dispatchEvent(
      new CustomEvent("builtin-rate", {
        detail: { value: val },
        bubbles: true,
        composed: true,
      })
    );
  }

  render() {
    const max = this.max || 5;
    const stars = [];
    for (let i = 0; i < max; i++) stars.push(i);

    return html`
      <div
        class="rating"
        role="img"
        aria-label="${this._l("rating.value", "Rating")}: ${this.value} / ${max}"
        part="rating"
      >
        ${stars.map((i) => this._renderStar(i))}
        <slot></slot>
      </div>
    `;
  }
}
