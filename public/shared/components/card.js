/**
 * @fileoverview BuiltinCard - A bordered surface container with optional header, media, body, and footer areas (Lit).
 *
 * Slots:
 *   - header: Card header content
 *   - media: Media/image area
 *   - (default): Card body content
 *   - footer: Card footer content
 *
 * Attributes:
 *   - variant ("default" | "elevated" | "bordered" | "media")
 *   - hover (boolean): Lift card on hover
 *   - padding ("normal" | "compact" | "none"): Body padding density
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinCard extends BuiltinBaseElement {
  static properties = {
    variant: { type: String },
    hover: { type: Boolean },
    padding: { type: String },
    imageFit: { type: String, attribute: "image-fit" },
  };

  static styles = css`
    :host { display: block; }
    .card {
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      overflow: hidden;
      transition: box-shadow 0.15s ease, transform 0.15s ease;
    }
    .card.default { border: 1px solid var(--builtin-border, #d1d5db); }
    .card.elevated {
      border: 1px solid var(--builtin-border, #d1d5db);
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    .card.bordered {
      border: 1px solid var(--builtin-border, #d1d5db);
    }
    .card.media { border: none; }
    .card.hover:hover {
      box-shadow: 0 4px 12px rgba(0,0,0,0.08);
      transform: translateY(-2px);
    }
    .header {
      padding: 14px 16px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
      font-weight: 650;
    }
    .media { display: block; width: 100%; }
    .media ::slotted(img), .media ::slotted(video) { width: 100%; display: block; object-fit: var(--builtin-card-media-fit, cover); }
    .body { color: var(--builtin-color-text, #111827); }
    .builtin-padding-normal { padding: 16px; }
    .builtin-padding-compact { padding: 10px 12px; }
    .builtin-padding-none { padding: 0; }
    .footer {
      padding: 12px 16px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    @media (max-width: 720px) {
      .builtin-padding-normal { padding: 12px; }
      .builtin-padding-compact { padding: 8px 10px; }
      .header { padding: 12px; }
      .footer { padding: 10px 12px; }
    }
  `;

  constructor() {
    super();
    this.variant = "default";
    this.padding = "normal";
    this.imageFit = "cover";
  }

  _slotExists(name) {
    return this.querySelector(`[slot="${name}"]`) !== null;
  }

  render() {
    const variant = this.variant || "default";
    const padding = this.padding || "normal";
    const cardClass = {
      card: true,
      [variant]: true,
      hover: this.hover,
    };
    const paddingClass = `builtin-padding-${padding}`;

    return html`
      <div class="${classMap(cardClass)}">
        ${this._slotExists("header") ? html`<div class="header"><slot name="header"></slot></div>` : ""}
        ${this._slotExists("media") ? html`<div class="media"><slot name="media"></slot></div>` : ""}
        <div class="body ${paddingClass}"><slot></slot></div>
        ${this._slotExists("footer") ? html`<div class="footer"><slot name="footer"></slot></div>` : ""}
      </div>
    `;
  }
}
