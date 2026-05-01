/**
 * @fileoverview BuiltinBadge — Simple text/status badge.
 *
 * @attr {string} text — Badge text
 * @attr {string} variant — `default` | `primary` | `success` | `warning` | `error`
 * @attr {boolean} pill — Pill shape (fully rounded)
 * @attr {boolean} dot — Show only a colored dot
 */

import { BuiltinBaseElement, html, css } from "./lit-base.js";

export class BuiltinBadge extends BuiltinBaseElement {
  static properties = {
    text: { type: String },
    variant: { type: String },
    pill: { type: Boolean },
    dot: { type: Boolean },
  };

  static styles = css`
    :host { display: inline-flex; }
    .badge {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 2px 8px; border-radius: 6px; font-size: 12px; font-weight: 600;
      line-height: 1.4; white-space: nowrap;
      border: 1px solid var(--builtin-border-soft);
      background: var(--builtin-surface); color: var(--builtin-color-text);
    }
    .pill { border-radius: 999px; }
    .primary { background: var(--builtin-primary); border-color: var(--builtin-primary); color: #fff; }
    .success { background: #16a34a; border-color: #16a34a; color: #fff; }
    .warning { background: #d97706; border-color: #d97706; color: #fff; }
    .error { background: var(--builtin-color-danger); border-color: var(--builtin-color-danger); color: #fff; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
    .dot.primary { background: var(--builtin-primary); }
    .dot.success { background: #16a34a; }
    .dot.warning { background: #d97706; }
    .dot.error { background: var(--builtin-color-danger); }
  `;

  render() {
    if (this.dot) {
      return html`<span class="dot ${this.variant || ''}"></span>`;
    }
    return html`<span class="badge ${this.variant || ''} ${this.pill ? 'pill' : ''}">${this.text || ''}</span>`;
  }
}
