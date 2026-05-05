import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinTestimonialCard - A testimonial card with quote, author info, avatar, and star rating.
 *
 * Attributes:
 * - `quote` (string)
 * - `author` (string)
 * - `role` (string)
 * - `avatar` (URL to the author's avatar image)
 * - `rating` (number, 1-5)
 * - `variant` (`card` | `quote` | `inline`). Default `card`.
 * - `labels` (JSON object for local i18n overrides)
 */
export class BuiltinTestimonialCard extends BuiltinBaseElement {
  static get properties() {
    return {
      quote: { type: String },
      author: { type: String },
      role: { type: String },
      avatar: { type: String },
      rating: { type: Number },
      variant: { type: String },
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
      _avatarError: { type: Boolean, state: true },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .card {
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
        padding: 28px;
        display: flex;
        flex-direction: column;
        gap: 18px;
      }
      .quote-mark {
        font-size: 48px;
        line-height: 1;
        color: var(--builtin-primary, #2563eb);
        font-family: Georgia, serif;
      }
      .quote-text {
        font-size: 16px;
        line-height: 1.6;
        color: var(--builtin-color-text, #111827);
      }
      .author-row {
        display: flex;
        align-items: center;
        gap: 14px;
      }
      .avatar {
        width: 52px;
        height: 52px;
        border-radius: 50%;
        object-fit: cover;
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        background: var(--builtin-header-bg, #f9fafb);
      }
      .fallback {
        width: 52px;
        height: 52px;
        border-radius: 50%;
        background: var(--builtin-primary, #2563eb);
        color: #fff;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-weight: 600;
        font-size: 18px;
      }
      .author-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .author-name {
        font-weight: 650;
        color: var(--builtin-color-text, #111827);
      }
      .author-role {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
      }
      .stars {
        display: flex;
        gap: 3px;
        font-size: 18px;
        color: var(--builtin-color-muted, #6b7280);
      }
      .star {
        display: inline-flex;
        color: #f59e0b;
      }
      .star.empty {
        color: var(--builtin-border, #d1d5db);
      }

      /* variant quote */
      :host([variant="quote"]) .card {
        border: none;
        background: transparent;
        padding: 20px 0;
      }
      :host([variant="quote"]) .quote-text {
        font-size: 18px;
        font-style: italic;
      }

      /* variant inline */
      :host([variant="inline"]) .card {
        flex-direction: row;
        align-items: center;
        border: none;
        background: transparent;
        padding: 12px 0;
        gap: 12px;
      }
      :host([variant="inline"]) .quote-mark {
        display: none;
      }
      :host([variant="inline"]) .quote-text {
        flex: 1;
        margin: 0;
      }
      :host([variant="inline"]) .author-row {
        flex-direction: column;
        align-items: flex-start;
        gap: 4px;
      }
      :host([variant="inline"]) .author-info {
        gap: 0;
      }

      @media (max-width: 720px) {
        .card {
          padding: 18px;
          gap: 12px;
        }
        .quote-mark {
          font-size: 36px;
        }
        .avatar,
        .fallback {
          width: 42px;
          height: 42px;
          font-size: 15px;
        }
        .quote-text {
          font-size: 15px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.quote = "";
    this.author = "";
    this.role = "";
    this.avatar = "";
    this.rating = 0;
    this.variant = "card";
    this.labels = {};
    this._avatarError = false;
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

  _initials() {
    return (this.author || "")
      .split(" ")
      .map((n) => n[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }

  _renderStars() {
    const r = Math.max(0, Math.min(5, Math.round(this.rating) || 0));
    const stars = [];
    for (let i = 0; i < 5; i++) {
      const filled = i < r;
      stars.push(html`
        <span class="star ${filled ? "" : "empty"}">
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="${filled ? "currentColor" : "none"}"
            stroke="currentColor"
            stroke-width="2"
          >
            <path
              d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"
            />
          </svg>
        </span>
      `);
    }
    return stars;
  }

  render() {
    const cardClasses = { card: true, mobile: this._ptMobile };
    const ratingLabel = this._t("testimonial.rating", {
      rating: this.rating,
      max: 5,
    });
    return html`
      <div class="${classMap(cardClasses)}">
        <div class="quote-mark">&ldquo;</div>
        ${this.quote ? html`<div class="quote-text">${this.quote}</div>` : ""}
        <div class="author-row">
          ${this.avatar && !this._avatarError
            ? html`<img
                class="avatar"
                src="${this.avatar}"
                alt="${this.author}"
                @error=${() => {
                  this._avatarError = true;
                }}
              />`
            : ""}
          ${!this.avatar || this._avatarError
            ? html`<span class="fallback">${this._initials()}</span>`
            : ""}
          <div class="author-info">
            ${this.author
              ? html`<div class="author-name">${this.author}</div>`
              : ""}
            ${this.role
              ? html`<div class="author-role">${this.role}</div>`
              : ""}
          </div>
        </div>
        <div class="stars" aria-label="${ratingLabel}">
          ${this._renderStars()}
        </div>
      </div>
    `;
  }
}
