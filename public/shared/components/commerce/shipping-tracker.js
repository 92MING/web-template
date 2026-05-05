import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinShippingTracker — Visual shipping/delivery timeline.
 *
 * Attributes:
 * - `steps` (JSON): `[{status, label, location, date, completed, active}]`
 * - `labels` (JSON object for local i18n overrides)
 *
 * Mobile: vertical timeline.
 */
export class BuiltinShippingTracker extends BuiltinBaseElement {
  static get properties() {
    return {
      steps: {
        converter: {
          fromAttribute(value) {
            if (!value) return [];
            try {
              return JSON.parse(value);
            } catch (_e) {
              return [];
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
      labels: {
        converter: {
          fromAttribute(value) {
            if (!value) return {};
            try {
              return JSON.parse(value);
            } catch (_e) {
              return {};
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .tracker {
        display: flex;
        align-items: flex-start;
        position: relative;
      }
      .step {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        position: relative;
        padding: 0 8px;
      }
      .step-icon {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 2px solid var(--builtin-border-soft, #e5e7eb);
        background: var(--builtin-surface, #ffffff);
        color: var(--builtin-color-muted, #9ca3af);
        flex-shrink: 0;
        z-index: 1;
      }
      .step-icon.completed {
        background: var(--builtin-primary, #2563eb);
        border-color: var(--builtin-primary, #2563eb);
        color: #fff;
      }
      .step-icon.active {
        border-color: var(--builtin-primary, #2563eb);
        color: var(--builtin-primary, #2563eb);
        box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.15);
      }
      .step-line {
        position: absolute;
        top: 17px;
        left: calc(50% + 18px);
        right: calc(-50% + 18px);
        height: 2px;
        background: var(--builtin-border-soft, #e5e7eb);
        z-index: 0;
      }
      .step:last-child .step-line {
        display: none;
      }
      .step-line.completed {
        background: var(--builtin-primary, #2563eb);
      }
      .step-body {
        margin-top: 10px;
      }
      .step-label {
        font-weight: 650;
        font-size: 13px;
        color: var(--builtin-color-text, #111827);
      }
      .step-location {
        font-size: 12px;
        color: var(--builtin-color-muted, #6b7280);
        margin-top: 2px;
      }
      .step-date {
        font-size: 11px;
        color: var(--builtin-color-muted, #9ca3af);
        margin-top: 2px;
      }
      .step-status {
        font-size: 11px;
        font-weight: 600;
        margin-top: 4px;
        padding: 2px 8px;
        border-radius: 999px;
        background: var(--builtin-primary-soft, #eff6ff);
        color: var(--builtin-primary, #2563eb);
      }
      .empty {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
        padding: 12px 0;
      }
      /* Mobile vertical */
      @media (max-width: 720px) {
        .tracker {
          flex-direction: column;
          align-items: stretch;
          padding-left: 8px;
        }
        .step {
          flex-direction: row;
          align-items: flex-start;
          text-align: left;
          padding: 0 0 24px 0;
        }
        .step:last-child {
          padding-bottom: 0;
        }
        .step-icon {
          width: 32px;
          height: 32px;
        }
        .step-line {
          top: 32px;
          left: 15px;
          right: auto;
          width: 2px;
          height: calc(100% - 8px);
        }
        .step-body {
          margin-top: 0;
          margin-left: 12px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.steps = [];
    this.labels = {};
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name)
            ? String(values[name])
            : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  _stepIconSvg(step) {
    if (step.completed) {
      return html`
        <builtin-icon name="check" size="16" variant="outlined"></builtin-icon>
      `;
    }
    if (step.active) {
      return html`
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
        </svg>
      `;
    }
    return html`
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="5"/>
      </svg>
    `;
  }

  render() {
    const steps = Array.isArray(this.steps) ? this.steps : [];
    return html`
      <div class="tracker">
        ${steps.length === 0
          ? html`<div class="empty">${this._t("shipping.empty")}</div>`
          : steps.map((step, i) => html`
              <div class="step">
                <div class="step-icon ${classMap({ completed: step.completed, active: step.active })}">
                  ${this._stepIconSvg(step)}
                </div>
                <div class="step-line ${classMap({ completed: step.completed })}"></div>
                <div class="step-body">
                  <div class="step-label">${step.label || ""}</div>
                  ${step.location ? html`<div class="step-location">${step.location}</div>` : ""}
                  ${step.date ? html`<div class="step-date">${step.date}</div>` : ""}
                  ${step.status ? html`<div class="step-status">${step.status}</div>` : ""}
                </div>
              </div>
            `)}
      </div>
    `;
  }
}
