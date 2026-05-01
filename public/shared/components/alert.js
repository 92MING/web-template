/**
 * @fileoverview BuiltinAlert — Inline alert/notice banner.
 *
 * @attr {string} text — Alert text (or use default slot)
 * @attr {string} variant — `info` | `success` | `warning` | `error`
 * @attr {boolean} closable — Show close button
 * @attr {string} icon — Optional icon name
 */

import { BuiltinBaseElement, html, css } from "./lit-base.js";

export class BuiltinAlert extends BuiltinBaseElement {
  static properties = {
    text: { type: String },
    variant: { type: String },
    closable: { type: Boolean },
    icon: { type: String },
    _closed: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .alert {
      display: flex; align-items: flex-start; gap: 10px; padding: 12px 16px;
      border-radius: 10px; border: 1px solid; font-size: 14px; line-height: 1.5;
    }
    .content { flex: 1; }
    .close {
      display: inline-flex; align-items: center; justify-content: center;
      width: 24px; height: 24px; border-radius: 6px; border: none; background: none;
      cursor: pointer; font-size: 16px; color: inherit; opacity: 0.6;
    }
    .close:hover { opacity: 1; background: rgba(0,0,0,0.08); }

    .info    { background: #eff6ff; border-color: #bfdbfe; color: #1e40af; }
    .success { background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
    .warning { background: #fffbeb; border-color: #fde68a; color: #92400e; }
    .error   { background: #fef2f2; border-color: #fecaca; color: #991b1b; }

    :host([_pt-theme="dark"]) .info    { background: #172554; border-color: #1e3a8a; color: #bfdbfe; }
    :host([_pt-theme="dark"]) .success { background: #14532d; border-color: #166534; color: #bbf7d0; }
    :host([_pt-theme="dark"]) .warning { background: #78350f; border-color: #92400e; color: #fde68a; }
    :host([_pt-theme="dark"]) .error   { background: #7f1d1d; border-color: #991b1b; color: #fecaca; }
  `;

  _onClose() { this._closed = true; this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true })); }

  render() {
    if (this._closed) return html``;
    const iconName = this.icon || (this.variant === 'error' ? 'exclamation-circle' : this.variant === 'warning' ? 'warning' : this.variant === 'success' ? 'check-circle' : 'info');
    return html`
      <div class="alert ${this.variant || 'info'}">
        <builtin-icon name="${iconName}" size="20" style="margin-top:1px;flex-shrink:0"></builtin-icon>
        <div class="content"><slot>${this.text || ''}</slot></div>
        ${this.closable ? html`<button class="close" @click=${this._onClose}>×</button>` : ''}
      </div>
    `;
  }
}
