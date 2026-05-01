import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinEmptyState — Centered empty-state illustration with heading, description, and optional action.
 *
 * @element builtin-empty-state
 *
 * @attr {string} preset - "search" | "error" | "404" | "no-access" | "custom".
 * @attr {string} state - "empty" | "loading" | "error".
 * @attr {string} heading - Heading text.
 * @attr {string} description - Description text.
 * @attr {string} eyebrow - Small caption shown above the heading.
 * @attr {string} caption - Secondary caption shown below the description.
 * @attr {string} icon - Unicode character, emoji, or text to display.
 * @attr {string} action-label - Built-in primary action label.
 * @attr {string} action-href - Built-in primary action href.
 * @attr {string} secondary-action-label - Built-in secondary action label.
 * @attr {string} secondary-action-href - Built-in secondary action href.
 * @attr {string} labels - JSON object for i18n overrides.
 *
 * @slot action - Button or link shown below the description.
 * @slot secondary-action - Secondary button or link.
 */
export class BuiltinEmptyState extends BuiltinBaseElement {
  static properties = {
    preset: { type: String },
    state: { type: String },
    heading: { type: String },
    description: { type: String },
    eyebrow: { type: String },
    caption: { type: String },
    icon: { type: String },
    actionLabel: { type: String, attribute: "action-label" },
    actionHref: { type: String, attribute: "action-href" },
    secondaryActionLabel: { type: String, attribute: "secondary-action-label" },
    secondaryActionHref: { type: String, attribute: "secondary-action-href" },
    labels: { type: Object },
  };

  static styles = css`
    :host {
      display: block;
    }
    .wrap {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 48px 24px;
      color: var(--builtin-color-text, #111827);
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 8px;
      color: var(--builtin-primary, #2563eb);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .icon {
      font-size: 56px;
      line-height: 1;
      color: var(--builtin-color-muted, #6b7280);
      margin-bottom: 16px;
      display: inline-flex;
    }
    .icon builtin-icon {
      width: 56px;
      height: 56px;
    }
    .heading {
      font-size: 18px;
      font-weight: 650;
      margin: 0 0 8px;
    }
    .description {
      font-size: 14px;
      color: var(--builtin-color-muted, #6b7280);
      margin: 0 0 16px;
      max-width: 440px;
      line-height: 1.5;
    }
    .caption {
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      margin: -6px 0 16px;
    }
    .actions {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: center;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      padding: 0 14px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 999px;
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      text-decoration: none;
      font: inherit;
      cursor: pointer;
    }
    .btn.primary {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .spinner {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      border: 3px solid color-mix(in srgb, var(--builtin-primary, #2563eb) 18%, transparent);
      border-top-color: var(--builtin-primary, #2563eb);
      animation: builtin-empty-spin 0.8s linear infinite;
      margin-bottom: 16px;
    }
    .action ::slotted(*) {
      margin-top: 4px;
    }
    @keyframes builtin-empty-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    @media (max-width: 720px) {
      .wrap {
        padding: 32px 16px;
      }
      .icon {
        font-size: 44px;
      }
      .icon builtin-icon {
        width: 44px;
        height: 44px;
      }
      .heading {
        font-size: 16px;
      }
    }
  `;

  constructor() {
    super();
    this.preset = "custom";
    this.state = "empty";
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

  _presetMeta() {
    if (this.state === "loading" || this.preset === "loading") {
      return {
        heading: this.heading || this._l("emptyState.loadingHeading"),
        description: this.description || this._l("emptyState.loadingDescription"),
        icon: this.icon || "loading",
      };
    }
    switch (this.preset) {
      case "search":
        return {
          heading:
            this.heading || this._l("emptyState.searchHeading"),
          description:
            this.description || this._l("emptyState.searchDescription"),
          icon: this.icon || "search",
        };
      case "error":
        return {
          heading:
            this.heading || this._l("emptyState.errorHeading"),
          description:
            this.description || this._l("emptyState.errorDescription"),
          icon: this.icon || "alert",
        };
      case "404":
        return {
          heading:
            this.heading || this._l("emptyState.404Heading"),
          description:
            this.description || this._l("emptyState.404Description"),
          icon: this.icon || "not-found",
        };
      case "no-access":
        return {
          heading:
            this.heading || this._l("emptyState.noAccessHeading"),
          description:
            this.description || this._l("emptyState.noAccessDescription"),
          icon: this.icon || "lock",
        };
      default:
        return {
          heading: this.heading || "",
          description: this.description || "",
          icon: this.icon || "",
        };
    }
  }

  _renderIcon(icon) {
    if (!icon) return "";
    if (icon === "search") {
      return html`
        <div class="icon">
          <builtin-icon name="search" size="56" variant="outlined"></builtin-icon>
        </div>
      `;
    }
    if (icon === "alert") {
      return html`
        <div class="icon">
          <builtin-icon name="warning" size="56" variant="outlined"></builtin-icon>
        </div>
      `;
    }
    if (icon === "not-found") {
      return html`
        <div class="icon">
          <builtin-icon name="block" size="56" variant="outlined"></builtin-icon>
        </div>
      `;
    }
    if (icon === "lock") {
      return html`
        <div class="icon">
          <builtin-icon name="lock" size="56" variant="outlined"></builtin-icon>
        </div>
      `;
    }
    if (icon === "loading") {
      return html`<div class="spinner" aria-hidden="true"></div>`;
    }
    return html`
      <div class="icon">
        <builtin-icon name="${icon}" size="56" variant="outlined"></builtin-icon>
      </div>
    `;
  }

  _emitAction(name) {
    this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true }));
  }

  render() {
    const meta = this._presetMeta();
    return html`
      <div class="wrap">
        ${this.eyebrow ? html`<div class="eyebrow">${this.eyebrow}</div>` : ""}
        ${this._renderIcon(meta.icon)}
        ${meta.heading
          ? html`<h3 class="heading">${meta.heading}</h3>`
          : ""}
        ${meta.description
          ? html`<p class="description">${meta.description}</p>`
          : ""}
        ${this.caption ? html`<div class="caption">${this.caption}</div>` : ""}
        <div class="actions">
          ${this.actionLabel
            ? (this.actionHref
                ? html`<a class="btn primary" href="${this.actionHref}">${this.actionLabel}</a>`
                : html`<button type="button" class="btn primary" @click=${() => this._emitAction("builtin-action")}>${this.actionLabel}</button>`)
            : ""}
          <slot name="action"></slot>
          ${this.secondaryActionLabel
            ? (this.secondaryActionHref
                ? html`<a class="btn" href="${this.secondaryActionHref}">${this.secondaryActionLabel}</a>`
                : html`<button type="button" class="btn" @click=${() => this._emitAction("builtin-secondary-action")}>${this.secondaryActionLabel}</button>`)
            : ""}
          <slot name="secondary-action"></slot>
        </div>
      </div>
    `;
  }
}
