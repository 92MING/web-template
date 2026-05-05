/**
 * @fileoverview BuiltinBreadcrumb — breadcrumb trail with separators (Lit).
 *
 * @attr {string} items — JSON array of {label, href}.
 * @attr {string} separator — Separator string (default "/").
 * @attr {string} labels — JSON map for i18n overrides.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

export class BuiltinBreadcrumb extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
    separator: { type: String },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .breadcrumb {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 10px 0;
      overflow-x: auto;
      white-space: nowrap;
      scrollbar-width: none;
    }
    .breadcrumb::-webkit-scrollbar { display: none; }
    .breadcrumb-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }
    .breadcrumb-item a {
      color: var(--builtin-primary, #2563eb);
      text-decoration: none;
      font-weight: 500;
      font-size: 13px;
    }
    .breadcrumb-item a:hover { text-decoration: underline; }
    .breadcrumb-item span {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
    }
    .separator {
      color: var(--builtin-color-muted, #6b7280);
      opacity: 0.6;
      font-size: 12px;
    }
    @media (max-width: 720px) {
      .breadcrumb { padding: 8px 0; }
      .breadcrumb-item a, .breadcrumb-item span { font-size: 14px; }
      .separator { font-size: 14px; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.separator = "/";
    this.labels = {};
  }

  _t(key, values) {
    if (this.labels && typeof this.labels === "object" && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => (
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        ));
      }
      return text;
    }
    return super._t(key, values);
  }

  render() {
    const items = this.items || [];
    const sep = this.separator || "/";
    const navLabel = this._t("breadcrumb.navLabel");

    return html`
      <nav aria-label="${navLabel && navLabel !== "breadcrumb.navLabel" ? navLabel : "Breadcrumb"}">
        <ol class="breadcrumb">
          ${items.map((item, index) => {
            const isLast = index === items.length - 1;
            return html`
              <li class="breadcrumb-item">
                ${index > 0 ? html`<span class="separator" aria-hidden="true">${sep}</span>` : ""}
                ${isLast
                  ? html`<span aria-current="page">${item.label}</span>`
                  : html`<a href="${item.href || "#"}">${item.label}</a>`}
              </li>
            `;
          })}
        </ol>
      </nav>
    `;
  }
}
