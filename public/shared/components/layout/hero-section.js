import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinHeroSection - Large hero area with title, subtitle, and call-to-action.
 *
 * Attributes:
 * - `preset` (`centered` | `split` | `full-bleed` | `video-bg`). Default `centered`.
 * - `title` (string)
 * - `subtitle` (string)
 * - `align` (`left` | `center`). Default `center`.
 * - `background` (background image URL)
 * - `overlay` (boolean)
 * - `labels` (JSON object for local i18n overrides)
 *
 * Slots:
 * - `cta`: Call-to-action buttons.
 * - `media`: Image or video media.
 */
export class BuiltinHeroSection extends BuiltinBaseElement {
  static get properties() {
    return {
      preset: { type: String },
      title: { type: String },
      subtitle: { type: String },
      align: { type: String },
      background: { type: String },
      overlay: { type: Boolean },
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
      .hero {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        padding: 64px 24px;
        min-height: 320px;
        color: var(--builtin-color-text, #111827);
        background: var(--builtin-header-bg, #f9fafb);
        border-radius: var(--builtin-radius-lg, 8px);
        overflow: hidden;
      }
      .overlay {
        position: absolute;
        inset: 0;
        background: rgba(0, 0, 0, 0.45);
      }
      .content {
        position: relative;
        z-index: 1;
        max-width: 720px;
      }
      .title {
        font-size: 36px;
        font-weight: 700;
        margin: 0 0 12px;
        line-height: 1.2;
        color: inherit;
      }
      .subtitle {
        font-size: 16px;
        color: var(--builtin-color-muted, #6b7280);
        margin: 0 0 24px;
        line-height: 1.5;
      }
      .cta {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        position: relative;
        z-index: 1;
      }
      .media {
        margin-top: 24px;
        position: relative;
        z-index: 1;
        max-width: 100%;
      }

      /* align left */
      :host([align="left"]) .hero {
        align-items: flex-start;
        text-align: left;
      }

      /* preset split */
      :host([preset="split"]) .hero {
        flex-direction: row;
        text-align: left;
        gap: 24px;
        align-items: center;
      }
      :host([preset="split"]) .content {
        flex: 1;
      }
      :host([preset="split"]) .media {
        flex: 1;
        margin-top: 0;
      }

      /* preset full-bleed */
      :host([preset="full-bleed"]) .hero {
        border-radius: 0;
        min-height: 400px;
      }

      /* preset video-bg */
      :host([preset="video-bg"]) .hero {
        border-radius: 0;
        min-height: 400px;
      }
      :host([preset="video-bg"]) .media {
        position: absolute;
        inset: 0;
        margin-top: 0;
        z-index: 0;
        max-width: none;
      }
      :host([preset="video-bg"]) .media ::slotted(*) {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      :host([preset="video-bg"]) .content,
      :host([preset="video-bg"]) .cta {
        z-index: 2;
      }

      @media (max-width: 720px) {
        .hero {
          padding: 40px 16px;
          min-height: 240px;
          align-items: center;
          text-align: center;
        }
        .title {
          font-size: 26px;
        }
        .subtitle {
          font-size: 14px;
        }
        .cta {
          flex-direction: column;
          align-items: stretch;
          width: 100%;
        }
        :host([preset="split"]) .hero {
          flex-direction: column;
        }
        :host([preset="split"]) .media {
          margin-top: 24px;
          width: 100%;
        }
      }
    `;
  }

  constructor() {
    super();
    this.preset = "centered";
    this.title = "";
    this.subtitle = "";
    this.align = "center";
    this.background = "";
    this.overlay = false;
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

  render() {
    const heroClasses = { hero: true, mobile: this._ptMobile };
    const textColor = this.overlay
      ? "#fff"
      : "var(--builtin-color-text, #111827)";
    const subtitleColor = this.overlay
      ? "rgba(255,255,255,0.85)"
      : "var(--builtin-color-muted, #6b7280)";
    const bgStyle = this.background
      ? `url('${this.background}') center/cover no-repeat`
      : "var(--builtin-header-bg, #f9fafb)";
    return html`
      <div
        class="${classMap(heroClasses)}"
        style=${styleMap({
          color: textColor,
          background: bgStyle,
        })}
      >
        ${this.overlay ? html`<div class="overlay"></div>` : ""}
        <div class="content">
          ${this.title ? html`<h1 class="title">${this.title}</h1>` : ""}
          ${this.subtitle
            ? html`<p
                class="subtitle"
                style=${styleMap({ color: subtitleColor })}
              >
                ${this.subtitle}
              </p>`
            : ""}
          <div class="cta"><slot name="cta"></slot></div>
        </div>
        <div class="media"><slot name="media"></slot></div>
      </div>
    `;
  }
}
