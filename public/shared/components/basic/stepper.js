/**
 * @fileoverview BuiltinStepper — Stepper / wizard navigation web component.
 *
 * @attr {string} steps — JSON array of {label, description}.
 * @attr {number} current — Default 0.
 * @attr {string} direction — `horizontal` | `vertical`.
 * @attr {boolean} clickable — Allow clicking previous steps.
 *
 * @event builtin-step-click — Detail: `{ index }`
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "../lit-base.js";

export class BuiltinStepper extends BuiltinBaseElement {
  static properties = {
    steps: { type: Array },
    current: { type: Number },
    direction: { type: String },
    clickable: { type: Boolean },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; max-width: 100%; overflow: hidden; }
    .stepper {
      display: flex; gap: 0;
      --step-size: 32px;
      width: 100%;
      max-width: 100%;
      min-width: 0;
    }
    .stepper.horizontal {
      overflow-x: auto;
      overflow-y: hidden;
      padding-bottom: 2px;
      scrollbar-width: thin;
      scrollbar-color: var(--builtin-border, #d1d5db) transparent;
    }
    .stepper.horizontal::-webkit-scrollbar { height: 8px; }
    .stepper.horizontal::-webkit-scrollbar-thumb { background: var(--builtin-border, #d1d5db); border-radius: 999px; }
    .stepper.vertical { flex-direction: column; }
    .step {
      display: flex; align-items: center; flex: 1 1 auto; position: relative; min-width: 0;
    }
    .stepper.horizontal .step { flex: 0 0 auto; min-width: min(150px, 42vw); }
    .stepper.vertical .step { flex: none; }
    .step-connector {
      flex: 1 1 auto; height: 2px; background: var(--builtin-border-soft, #e5e7eb);
      margin: 0 8px; min-width: 20px;
      transition: background 0.3s ease;
    }
    .stepper.vertical .step-connector {
      position: absolute; left: 15px; top: 32px;
      width: 2px; height: calc(100% - 24px); margin: 0; min-width: auto;
    }
    .step-connector.active { background: var(--builtin-primary, #2563eb); }
    .step-badge {
      transition: background 0.25s ease, border-color 0.25s ease, color 0.25s ease;
    }
    .step:last-child .step-connector { display: none; }
    .step-badge {
      width: var(--step-size); height: var(--step-size); border-radius: 50%;
      display: inline-flex; align-items: center; justify-content: center;
      font-weight: 650; font-size: 13px; flex-shrink: 0;
      border: 2px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-muted, #6b7280);
    }
    .step-badge.completed {
      background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff;
    }
    .step-badge.current {
      border-color: var(--builtin-primary, #2563eb); color: var(--builtin-primary, #2563eb);
    }
    .step-body { margin-left: 10px; min-width: 0; max-width: 130px; }
    .step-title { font-weight: 650; font-size: 13px; color: var(--builtin-color-text, #111827); overflow-wrap: anywhere; }
    .step-desc { font-size: 12px; color: var(--builtin-color-muted, #6b7280); overflow-wrap: anywhere; }
    .step.clickable { cursor: pointer; }
    .step.clickable:hover .step-title { color: var(--builtin-primary, #2563eb); }
    /* Mobile scrollable dots */
    .dots {
      display: flex; align-items: center; justify-content: center; gap: 10px;
    }
    .dot {
      width: 10px; height: 10px; border-radius: 50%;
      background: var(--builtin-border-soft, #e5e7eb);
    }
    .dot.completed { background: var(--builtin-primary, #2563eb); }
    .dot.current { background: var(--builtin-primary, #2563eb); box-shadow: 0 0 0 3px rgba(37,99,235,0.25); }
    @media (max-width: 720px) {
      .stepper.horizontal { flex-direction: column; }
      .stepper.horizontal .step-connector {
        position: absolute; left: 15px; top: 32px;
        width: 2px; height: calc(100% - 24px); margin: 0; min-width: auto;
      }
      .stepper.horizontal .step { flex: none; }
    }
  `;

  constructor() {
    super();
    this.steps = [];
    this.current = 0;
    this.direction = "horizontal";
  }

  _isClickable(index) {
    return this.clickable && index < this.current;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  render() {
    const steps = Array.isArray(this.steps) ? this.steps : [];
    const current = Number(this.current) || 0;
    const direction = this.direction || "horizontal";
    const isMobile = this._ptMobile;

    if (isMobile && direction === "horizontal") {
      return html`
        <div class="dots">
          ${steps.map((_, idx) => html`
            <div class="dot ${classMap({ completed: idx < current, current: idx === current })}"></div>
          `)}
        </div>
      `;
    }

    return html`
      <div class="stepper ${direction}">
        ${steps.map((step, index) => {
          const completed = index < current;
          const isCurrent = index === current;
          const clickable = this._isClickable(index);
          return html`
            <div class="step ${classMap({ clickable })}" @click=${clickable ? () => this.dispatchEvent(new CustomEvent("builtin-step-click", { detail: { index }, bubbles: true, composed: true })) : null}>
              <div class="step-badge ${classMap({ completed, current: isCurrent })}">
                ${completed ? html`
                  <builtin-icon name="check" size="20" variant="outlined"></builtin-icon>
                ` : String(index + 1)}
              </div>
              <div class="step-body">
                <div class="step-title">${step.label || `${this._l("step", "Step")} ${index + 1}`}</div>
                ${step.description ? html`<div class="step-desc">${step.description}</div>` : null}
              </div>
              <div class="step-connector ${classMap({ active: completed })}"></div>
            </div>
          `;
        })}
      </div>
    `;
  }
}
