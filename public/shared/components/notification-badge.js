import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinNotificationBadge - Badge overlay for an element showing a numeric count.
 *
 * Slots:
 *   - (default): The element to badge (e.g., a bell icon)
 *
 * Attributes:
 *   - count: Number to display
 *   - max: Maximum count before showing "{max}+" (default 99)
 *   - pulse: Boolean to enable a subtle pulse animation
 *   - dot-only: Show only a dot, no number
 */
export class BuiltinNotificationBadge extends BuiltinBaseElement {
  static properties = {
    count: { type: Number },
    max: { type: Number },
    pulse: { type: Boolean },
    dotOnly: { type: Boolean, attribute: "dot-only" },
  };

  static styles = css`
    :host {
      display: inline-block;
      position: relative;
    }
    .badge {
      position: absolute;
      top: -6px;
      right: -6px;
      background: var(--builtin-color-danger, #b91c1c);
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      line-height: 1;
      padding: 2px 5px;
      border-radius: 999px;
      min-width: 18px;
      text-align: center;
      pointer-events: none;
      display: none;
      border: 2px solid var(--builtin-surface, #ffffff);
    }
    .badge.show {
      display: inline-block;
    }
    .badge.dot {
      min-width: auto;
      width: 10px;
      height: 10px;
      padding: 0;
      top: -4px;
      right: -4px;
    }
    @keyframes builtin-pulse {
      0% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.15);
      }
      100% {
        transform: scale(1);
      }
    }
    .pulse {
      animation: builtin-pulse 1.5s infinite ease-in-out;
    }
    @media (max-width: 720px) {
      .badge {
        font-size: 12px;
        padding: 3px 6px;
        min-width: 20px;
        top: -8px;
        right: -8px;
      }
      .badge.dot {
        width: 12px;
        height: 12px;
        top: -6px;
        right: -6px;
      }
    }
  `;

  constructor() {
    super();
    this.count = 0;
    this.max = 99;
    this.pulse = false;
    this.dotOnly = false;
  }

  render() {
    const show = this.count > 0;
    const text = this.count > this.max ? `${this.max}+` : String(this.count);

    return html`
      <slot></slot>
      <span
        class="badge ${classMap({
          show,
          pulse: this.pulse,
          dot: this.dotOnly,
        })}"
        part="badge"
      >
        ${this.dotOnly ? "" : text}
      </span>
    `;
  }
}
