/**
 * @fileoverview BuiltinProgressBar — Linear progress bar with optional label.
 *
 * @attr {number} value — Current value (0–100)
 * @attr {number} max — Maximum (default 100)
 * @attr {string} variant — `default` | `primary` | `success` | `warning` | `error`
 * @attr {boolean} label — Show percentage text
 * @attr {string} height — Bar height in px (default 8)
 */

import { BuiltinBaseElement, html, css } from "./lit-base.js";

export class BuiltinProgressBar extends BuiltinBaseElement {
  static properties = {
    value: { type: Number },
    max: { type: Number },
    variant: { type: String },
    label: { type: Boolean },
    height: { type: String },
  };

  static styles = css`
    :host { display: block; }
    .wrap { display: flex; align-items: center; gap: 10px; }
    .track {
      flex: 1; overflow: hidden; border-radius: 999px;
      background: var(--builtin-surface); border: 1px solid var(--builtin-border-soft);
    }
    .fill { height: 100%; border-radius: 999px; transition: width 0.4s ease;
      background: var(--builtin-primary); min-width: 4px;
    }
    .success .fill { background: #16a34a; }
    .warning .fill { background: #d97706; }
    .error .fill { background: var(--builtin-color-danger); }
    .text { font-size: 12px; font-weight: 600; color: var(--builtin-color-muted); min-width: 36px; text-align: right; }
  `;

  render() {
    const max = Math.max(1, this.max || 100);
    const pct = Math.min(100, Math.max(0, ((this.value || 0) / max) * 100));
    const h = this.height || '8';
    return html`
      <div class="wrap ${this.variant || ''}">
        <div class="track" style="height:${h}px"><div class="fill" style="width:${pct}%"></div></div>
        ${this.label ? html`<div class="text">${Math.round(pct)}%</div>` : ''}
      </div>
    `;
  }
}
