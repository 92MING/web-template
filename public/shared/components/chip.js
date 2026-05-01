/**
 * @fileoverview BuiltinChip — Tag/chip with optional remove button.
 *
 * @attr {string} text — Chip text
 * @attr {boolean} removable — Show remove button
 * @attr {string} variant — `default` | `primary` | `accent`
 * @event remove — Fired when remove button clicked
 */

import { BuiltinBaseElement, html, css } from "./lit-base.js";

export class BuiltinChip extends BuiltinBaseElement {
  static properties = {
    text: { type: String },
    removable: { type: Boolean },
    variant: { type: String },
  };

  static styles = css`
    :host { display: inline-flex; }
    .chip {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 10px; border-radius: 999px; font-size: 13px; font-weight: 500;
      border: 1px solid var(--builtin-border-soft); background: var(--builtin-surface);
      color: var(--builtin-color-text); user-select: none;
    }
    .primary { background: var(--builtin-primary); border-color: var(--builtin-primary); color: #fff; }
    .accent { background: var(--builtin-accent); border-color: var(--builtin-accent); color: #fff; }
    .remove {
      display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
      width: 16px; height: 16px; border-radius: 50%; border: none; padding: 0; background: none;
      opacity: 0.6; color: inherit; font-size: 14px; line-height: 1;
    }
    .remove:hover { opacity: 1; background: rgba(0,0,0,0.12); }
    .primary .remove:hover, .accent .remove:hover { background: rgba(255,255,255,0.2); }
  `;

  _onRemove() { this.dispatchEvent(new CustomEvent('remove', { bubbles: true, composed: true })); }

  render() {
    return html`
      <span class="chip ${this.variant || ''}">
        ${this.text || ''}
        ${this.removable ? html`<button class="remove" @click=${this._onRemove}>×</button>` : ''}
      </span>`;
  }
}
