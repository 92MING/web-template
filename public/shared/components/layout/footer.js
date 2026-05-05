/**
 * @fileoverview BuiltinFooter — responsive multi-column footer (Lit).
 *
 * @attr {string} variant — "simple" | "multi-column" | "social-heavy"
 * @attr {string} columns — JSON object of link columns.
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @slots
 * - links — Extra link area (rendered before columns).
 * - social — Social icons area.
 * - bottom — Copyright / legal text at the very bottom.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

export class BuiltinFooter extends BuiltinBaseElement {
  static properties = {
    variant: { type: String },
    columns: { type: Object },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .footer {
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border, #d1d5db);
      padding: 32px 24px 16px;
    }
    .footer-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 24px;
      max-width: 960px;
      margin: 0 auto;
    }
    .footer.simple .footer-grid {
      grid-template-columns: 1fr;
      text-align: center;
    }
    .footer.social-heavy .footer-grid {
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    }
    .footer-column h4 {
      margin: 0 0 10px;
      font-size: 13px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--builtin-color-muted, #6b7280);
    }
    .footer-column ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .footer-column a {
      color: var(--builtin-color-text, #111827);
      text-decoration: none;
      font-size: 14px;
    }
    .footer-column a:hover { color: var(--builtin-primary, #2563eb); text-decoration: underline; }
    .footer-social {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 16px;
      margin: 24px 0 12px;
    }
    .footer-bottom {
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      padding-top: 12px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .footer-links {
      max-width: 960px;
      margin: 0 auto 16px;
    }
    @media (max-width: 720px) {
      .footer { padding: 24px 16px 12px; }
      .footer-grid { grid-template-columns: 1fr !important; gap: 20px; text-align: left; }
      .footer-column h4 { margin-bottom: 8px; }
      .footer-column ul { gap: 8px; }
      .footer-social { gap: 20px; margin: 20px 0 10px; }
      .footer-bottom { font-size: 14px; padding-top: 10px; }
    }
  `;

  constructor() {
    super();
    this.variant = "multi-column";
    this.columns = {};
    this.labels = {};
  }

  render() {
    const variant = this.variant || "multi-column";
    const columnEntries = Object.entries(this.columns || {});
    const footerClass = { footer: true, [variant]: true };

    return html`
      <footer class="${classMap(footerClass)}">
        <div class="footer-links">
          <slot name="links"></slot>
        </div>
        <div class="footer-grid">
          ${columnEntries.map(([title, links]) => html`
            <div class="footer-column">
              <h4>${title}</h4>
              <ul>
                ${(links || []).map((link) => html`
                  <li><a href="${link.href || "#"}">${link.label || ""}</a></li>
                `)}
              </ul>
            </div>
          `)}
        </div>
        <div class="footer-social">
          <slot name="social"></slot>
        </div>
        <div class="footer-bottom">
          <slot name="bottom"></slot>
        </div>
      </footer>
    `;
  }
}
