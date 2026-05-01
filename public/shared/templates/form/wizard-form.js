/**
 * @fileoverview BuiltinTplFormWizard - Multi-step wizard form template (Lit).
 *
 * Attributes:
 *   - steps: JSON array of step objects { title, fields[] }
 *   - current: Active step index (number)
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-step-change: Step changed. Detail: { step }.
 *   - builtin-submit: Submit clicked. Detail: { data }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

export class BuiltinTplFormWizard extends BuiltinBaseElement {
  static get properties() {
    return {
            steps: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "[]"); } catch { return []; }
          },
        },
      },
      fields: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "[]"); } catch { return []; }
          },
        },
      },
      current: { type: Number },
      labels: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "{}"); } catch { return {}; }
          },
        },
      },
    };
  }

  constructor() {
    super();
    this.steps = [];
    this.fields = [];
    this.current = 0;
    this.labels = {};
    this._values = {};
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = String(this.labels[key]);
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  willUpdate(changedProperties) {
    if (!this.steps || this.steps.length === 0) {
        this.steps = this._defaultSteps();
      }
      if (!this.fields || this.fields.length === 0) {
        this.fields = this._defaultFields();
      }
    super.willUpdate(changedProperties);
  }

  _defaultSteps() {
    const fields = this._defaultFields();
    return [
      { title: "Personal Info", fields: fields.slice(0, 2) },
      { title: "Work Info", fields: fields.slice(2, 4) },
      { title: "Preferences", fields: fields.slice(4) },
    ];
  }

  _defaultFields() {
    return [
      { name: "fullName", label: "Full Name", type: "text", placeholder: "Enter your full name" },
      { name: "email", label: "Email", type: "email", placeholder: "Enter your email" },
      { name: "company", label: "Company", type: "text", placeholder: "Enter your company" },
      { name: "role", label: "Role", type: "select", options: [{ value: "dev", label: "Developer" }, { value: "manager", label: "Manager" }, { value: "designer", label: "Designer" }] },
      { name: "feedback", label: "Feedback", type: "textarea", placeholder: "Your feedback" },
      { name: "newsletter", label: "Subscribe to newsletter", type: "checkbox", options: [{ value: "yes", label: "Yes, keep me updated" }] },
    ];
  }

  _onStepClick(e) {
    const idx = Number(e.currentTarget.dataset.index);
    if (!Number.isNaN(idx) && idx >= 0 && idx < this.steps.length) {
      this.current = idx;
      this._emitStepChange();
    }
  }

  _onPrev() {
    if (this.current > 0) {
      this.current -= 1;
      this._emitStepChange();
    }
  }

  _onNext() {
    if (this.current < this.steps.length - 1) {
      this.current += 1;
      this._emitStepChange();
    }
  }

  _onSubmit() {
    this.dispatchEvent(
      new CustomEvent("builtin-submit", {
        bubbles: true,
        composed: true,
        detail: { data: { ...this._values } },
      })
    );
  }

  _emitStepChange() {
    this.dispatchEvent(
      new CustomEvent("builtin-step-change", {
        bubbles: true,
        composed: true,
        detail: { step: this.steps[this.current] },
      })
    );
  }

  _onInput(e) {
    const field = e.target.closest("[data-field]");
    if (!field) return;
    this._values[field.dataset.field] = e.target.value;
  }

  _onChange(e) {
    const field = e.target.closest("[data-field]");
    if (!field) return;
    const name = field.dataset.field;
    if (e.target.type === "checkbox") {
      const cbs = this.renderRoot.querySelectorAll(`[data-field="${CSS.escape(name)}"]`);
      this._values[name] = Array.from(cbs)
        .filter((cb) => cb.checked)
        .map((cb) => cb.value);
    } else if (e.target.type === "radio") {
      this._values[name] = e.target.value;
    } else {
      this._values[name] = e.target.value;
    }
  }

  _renderField(field) {
    const name = field.name || "";
    const label = field.label || "";
    const type = field.type || "text";
    const value = this._values[field.name] ?? field.default ?? "";
    const placeholder = field.placeholder || "";
    const required = field.required;

    if (type === "select") {
      return html`
        <label class="field-label">${label}</label>
        <select
          data-field="${name}"
          class="field-input"
          ?required=${required}
          @change=${this._onChange}
        >
          ${repeat(
            field.options || [],
            (opt) => opt.value,
            (opt) => html`
              <option value="${opt.value}" ?selected=${opt.value === value}>
                ${opt.label}
              </option>
            `
          )}
        </select>
      `;
    }

    if (type === "textarea") {
      return html`
        <label class="field-label">${label}</label>
        <textarea
          data-field="${name}"
          class="field-input"
          placeholder="${placeholder}"
          ?required=${required}
          @input=${this._onInput}
        >${value}</textarea>
      `;
    }

    if (type === "radio" || type === "checkbox") {
      return html`
        <fieldset class="field-group">
          <legend class="field-label">${label}</legend>
          ${repeat(
            field.options || [],
            (opt) => opt.value,
            (opt) => {
              const checked =
                type === "checkbox"
                  ? Array.isArray(value) && value.includes(opt.value)
                  : String(value) === String(opt.value);
              return html`
                <label class="choice-label">
                  <input
                    type="${type}"
                    name="${name}"
                    data-field="${name}"
                    value="${opt.value}"
                    ?checked=${checked}
                    ?required=${required}
                    @change=${this._onChange}
                  />
                  <span>${opt.label}</span>
                </label>
              `;
            }
          )}
        </fieldset>
      `;
    }

    return html`
      <label class="field-label">${label}</label>
      <input
        type="${type}"
        data-field="${name}"
        class="field-input"
        placeholder="${placeholder}"
        .value=${value}
        ?required=${required}
        @input=${this._onInput}
      />
    `;
  }

  render() {
    const step = this.steps[this.current];
    const isFirst = this.current === 0;
    const isLast = this.current >= this.steps.length - 1;

    return html`
      <div class="wizard-container">
        ${this.steps.length
          ? html`
              <ul class="stepper">
                ${repeat(
                  this.steps,
                  (s, i) => i,
                  (s, i) => html`
                    <li
                      class="stepper-item ${classMap({
                        active: i === this.current,
                        completed: i < this.current,
                      })}"
                      data-index="${i}"
                      @click=${this._onStepClick}
                    >
                      <span class="stepper-number">${i + 1}</span>
                      <span class="stepper-title">${s.title || ""}</span>
                    </li>
                  `
                )}
              </ul>
            `
          : ""}

        ${step
          ? html`
              <div class="form-step">
                <h3 class="step-title">${step.title || ""}</h3>
                <div class="step-fields">
                  ${repeat(
                    step.fields || [],
                    (f) => f.name,
                    (f) => this._renderField(f)
                  )}
                </div>
              </div>
            `
          : ""}

        <div class="form-actions">
          <button
            type="button"
            class="btn btn-secondary"
            ?disabled=${isFirst}
            @click=${this._onPrev}
          >
            ${this._t("wizard.prev")}
          </button>
          ${isLast
            ? html`
                <button
                  type="button"
                  class="btn btn-primary"
                  @click=${this._onSubmit}
                >
                  ${this._t("wizard.submit")}
                </button>
              `
            : html`
                <button
                  type="button"
                  class="btn btn-primary"
                  @click=${this._onNext}
                >
                  ${this._t("wizard.next")}
                </button>
              `}
        </div>
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .wizard-container {
        display: flex;
        flex-direction: column;
        gap: 16px;
        max-width: 800px;
        margin: 0 auto;
        padding: 16px;
      }
      .stepper {
        display: flex;
        list-style: none;
        padding: 0;
        margin: 0;
        gap: 8px;
        justify-content: space-between;
        border-bottom: 1px solid var(--builtin-border);
        padding-bottom: 12px;
      }
      .stepper-item {
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
        opacity: 0.6;
        flex: 1;
        justify-content: center;
        padding: 8px;
        border-radius: var(--builtin-radius, 6px);
      }
      .stepper-item:hover {
        background: var(--builtin-surface);
      }
      .stepper-item.active {
        opacity: 1;
        font-weight: 600;
      }
      .stepper-item.completed {
        opacity: 0.85;
      }
      .stepper-number {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: var(--builtin-border-soft);
        font-size: 12px;
        flex-shrink: 0;
      }
      .stepper-item.active .stepper-number {
        background: var(--builtin-primary);
        color: #fff;
      }
      .stepper-item.completed .stepper-number {
        background: var(--builtin-button-bg);
        color: #fff;
      }
      .stepper-title {
        font-size: 14px;
        white-space: nowrap;
      }
      .form-step {
        background: var(--builtin-surface);
        border: 1px solid var(--builtin-border-soft);
        border-radius: var(--builtin-radius-lg, 8px);
        padding: 20px;
      }
      .step-title {
        margin: 0 0 16px;
        font-size: 18px;
        color: var(--builtin-color-text);
      }
      .step-fields {
        display: flex;
        flex-direction: column;
        gap: 14px;
      }
      .field-label {
        font-size: 14px;
        margin-bottom: 6px;
        display: block;
        color: var(--builtin-color-text);
      }
      .field-input {
        width: 100%;
        padding: 10px 12px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-header-bg);
        color: var(--builtin-color-text);
        font-size: 14px;
        box-sizing: border-box;
      }
      .field-input:focus {
        outline: 2px solid var(--builtin-primary);
        border-color: var(--builtin-primary);
      }
      textarea.field-input {
        min-height: 100px;
        resize: vertical;
      }
      .field-group {
        border: 1px solid var(--builtin-border-soft);
        border-radius: var(--builtin-radius, 6px);
        padding: 12px;
        margin: 0;
      }
      .choice-label {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
        padding: 4px 0;
        color: var(--builtin-color-text);
        cursor: pointer;
      }
      .form-actions {
        display: flex;
        justify-content: space-between;
        gap: 12px;
      }
      .btn {
        padding: 10px 18px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-button-bg);
        color: var(--builtin-color-text);
        font-size: 14px;
        cursor: pointer;
      }
      .btn:hover:not(:disabled) {
        background: var(--builtin-button-hover-bg);
      }
      .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .btn-primary {
        background: var(--builtin-primary);
        color: #fff;
        border-color: transparent;
      }
      .btn-primary:hover:not(:disabled) {
        filter: brightness(1.1);
      }
      @media (max-width: 720px) {
        .wizard-container {
          padding: 12px;
        }
        .stepper {
          flex-direction: column;
          border-bottom: none;
          border-left: 2px solid var(--builtin-border);
          padding-bottom: 0;
          padding-left: 12px;
          gap: 4px;
        }
        .stepper-item {
          justify-content: flex-start;
          padding: 6px 8px;
        }
        .stepper-title {
          white-space: normal;
        }
        .form-actions {
          flex-direction: column;
        }
        .form-actions .btn {
          width: 100%;
        }
      }
    `;
  }
}