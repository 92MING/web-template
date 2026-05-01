import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

/**
 * @fileoverview Onboarding / tutorial guide template.
 *
 * @description Top progress stepper, illustration area per step,
 * title + description text, Prev/Next buttons, skip link.
 *
 * Attributes:
 *   - steps: JSON array of step objects [{ title, description, image }]
 *   - current: Current step index (default: 0)
 *   - labels: JSON object to override i18n strings
 *
 * Events:
 *   - builtin-step-change: Dispatched when current step changes ({ step })
 *   - builtin-complete: Dispatched when user finishes the last step
 *   - builtin-skip: Dispatched when user clicks skip
 */
export class BuiltinTplTutorialOnboarding extends BuiltinBaseElement {
  static properties = {
    steps: { type: Array, converter: jsonConverter },
    current: { type: Number },
        labels: { type: Object, converter: jsonConverter },
  };

  static styles = css`
    :host {
      display: block;
      color: var(--builtin-color-text, #111827);
      font-family: inherit;
    }
    .onboarding {
      display: flex;
      flex-direction: column;
      align-items: center;
      max-width: 720px;
      margin: 0 auto;
      padding: 2rem 1.5rem;
      gap: 1.5rem;
    }
    .stepper {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      width: 100%;
      justify-content: center;
    }
    .step {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.375rem;
    }
    .step-dot {
      width: 2rem;
      height: 2rem;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.8125rem;
      font-weight: 700;
      background: var(--builtin-surface, #ffffff);
      border: 2px solid var(--builtin-border, #d1d5db);
      color: var(--builtin-color-muted, #6b7280);
      transition: background 0.2s, border-color 0.2s, color 0.2s;
    }
    .step.active .step-dot {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .step.done .step-dot {
      background: var(--builtin-button-bg, #ffffff);
      border-color: var(--builtin-primary, #2563eb);
      color: var(--builtin-primary, #2563eb);
    }
    .step-label {
      font-size: 0.75rem;
      color: var(--builtin-color-muted, #6b7280);
    }
    .step.active .step-label {
      color: var(--builtin-color-text, #111827);
      font-weight: 600;
    }
    .step-connector {
      flex: 1;
      height: 2px;
      background: var(--builtin-border, #d1d5db);
      max-width: 3rem;
    }
    .illustration {
      width: 100%;
      aspect-ratio: 16 / 9;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .illustration img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .illustration ::slotted(img),
    .illustration ::slotted(svg) {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .content {
      text-align: center;
      max-width: 560px;
    }
    .content h2 {
      margin: 0 0 0.5rem 0;
      font-size: 1.5rem;
      color: var(--builtin-color-text, #111827);
    }
    .content p {
      margin: 0;
      font-size: 1rem;
      color: var(--builtin-color-muted, #6b7280);
      line-height: 1.6;
    }
    .actions {
      display: flex;
      gap: 0.75rem;
      width: 100%;
      justify-content: center;
      align-items: center;
    }
    .btn {
      padding: 0.625rem 1.25rem;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      font-size: 0.9375rem;
      cursor: pointer;
      transition: background 0.2s;
      font: inherit;
    }
    .btn:hover {
      background: var(--builtin-button-hover-bg, #f9fafb);
    }
    .btn-primary {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .btn-primary:hover {
      opacity: 0.92;
    }
    .btn:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    .skip {
      font-size: 0.875rem;
      color: var(--builtin-color-muted, #6b7280);
      background: none;
      border: none;
      cursor: pointer;
      text-decoration: underline;
      font: inherit;
    }
    .skip:hover {
      color: var(--builtin-color-text, #111827);
    }
    .dots {
      display: none;
      gap: 0.5rem;
    }
    .dot {
      width: 0.625rem;
      height: 0.625rem;
      border-radius: 50%;
      background: var(--builtin-border, #d1d5db);
      transition: background 0.2s;
    }
    .dot.active {
      background: var(--builtin-primary, #2563eb);
    }

    @media (max-width: 720px) {
      .onboarding {
        padding: 1rem;
        gap: 1rem;
      }
      .stepper {
        display: none;
      }
      .dots {
        display: flex;
      }
      .illustration {
        aspect-ratio: 4 / 3;
      }
      .content h2 {
        font-size: 1.25rem;
      }
      .actions {
        flex-direction: column;
      }
      .btn {
        width: 100%;
      }
    }
  `;

  constructor() {
    super();
    this.steps = [];
    this.current = 0;
  }

  _defaultSteps() {
    return [
      { title: "Welcome", description: "Get started with the platform in just a few steps.", image: "" },
      { title: "Explore", description: "Discover features and tools tailored for your workflow.", image: "" },
      { title: "Customize", description: "Personalize settings to match your preferences.", image: "" },
      { title: "Launch", description: "You're all set. Start building today!", image: "" },
    ];
  }

  _effectiveSteps() {
    return this.steps?.length ? this.steps : (this._defaultSteps());
  }

  _prev() {
    if (this.current > 0) {
      this.current -= 1;
      this.dispatchEvent(
        new CustomEvent("builtin-step-change", {
          detail: { step: this.current },
          bubbles: true,
          composed: true,
        })
      );
    }
  }

  _next() {
    const steps = this._effectiveSteps();
    if (this.current < steps.length - 1) {
      this.current += 1;
      this.dispatchEvent(
        new CustomEvent("builtin-step-change", {
          detail: { step: this.current },
          bubbles: true,
          composed: true,
        })
      );
    } else {
      this.dispatchEvent(new CustomEvent("builtin-complete", { bubbles: true, composed: true }));
    }
  }

  _skip() {
    this.dispatchEvent(new CustomEvent("builtin-skip", { bubbles: true, composed: true }));
  }

  render() {
    const steps = this._effectiveSteps();
    const step = steps[this.current] || { title: "", description: "" };
    const isFirst = this.current === 0;
    const isLast = this.current >= steps.length - 1;
    const count = steps.length || 1;

    return html`
      <div class="onboarding">
        <div class="stepper">
          ${repeat(steps, (s, i) => i, (s, i) => html`
            <div class="step ${classMap({ active: i === this.current, done: i < this.current })}">
              <div class="step-dot">${i < this.current ? html`&#10003;` : i + 1}</div>
              <div class="step-label">${this._l(`step.${i}.title`, s.title || `Step ${i + 1}`)}</div>
            </div>
            ${i < count - 1 ? html`<div class="step-connector"></div>` : ''}
          `)}
        </div>

        <div class="dots">
          ${Array.from({ length: count }, (_, i) => html`
            <span class="dot ${classMap({ active: i === this.current })}"></span>
          `)}
        </div>

        <div class="illustration">
          <slot name="${`illustration-${this.current}`}">
            ${step.image ? html`<img src="${step.image}" alt="">` : ''}
          </slot>
        </div>

        <div class="content">
          <h2>${this._l(`step.${this.current}.title`, step.title || this._l("step.defaultTitle", "Welcome"))}</h2>
          <p>${this._l(`step.${this.current}.desc`, step.description || step.desc || this._l("step.defaultDesc", "Let's get you started."))}</p>
        </div>

        <div class="actions">
          <button class="btn" @click=${this._prev} ?disabled=${isFirst}>${this._l("action.prev", "Prev")}</button>
          <button class="btn btn-primary" @click=${this._next}>
            ${isLast ? this._l("action.finish", "Finish") : this._l("action.next", "Next")}
          </button>
          <button class="skip" @click=${this._skip}>${this._l("action.skip", "Skip")}</button>
        </div>
      </div>
    `;
  }
}