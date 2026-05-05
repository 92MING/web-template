/**
 * @fileoverview BuiltinSchemaForm — Schema-driven form for settings, profile editors, lightweight CRUD dialogs, and filter panels.
 *
 * @attr {string} schema — JSON field definitions.
 * @attr {string} value — JSON initial values.
 * @attr {string} endpoint — URL to POST the form payload.
 * @attr {string} method — HTTP method (default POST).
 * @attr {number} columns — Number of form columns (default 1).
 * @attr {string} submit-label — Label for the submit button.
 * @attr {string} reset-label — Label for the reset button.
 * @attr {boolean} hide-reset — Hide the reset button.
 * @attr {string} submitting-label — Label shown while submitting.
 * @attr {string} layout — `vertical` | `horizontal` | `compact`.
 * @attr {string} density — `compact` | `normal` | `comfortable`.
 *
 * @method getValue() — Get current form values.
 * @method setValue(name, value) — Set a single field value.
 * @method setValues(values, { silent }) — Set multiple values.
 * @method reset(values) — Reset to initial or given values.
 * @method validate() — Validate and return { ok, errors }.
 * @method setErrors(errors) — Display server-side errors.
 * @method submit() — Validate then POST if endpoint is set.
 *
 * @event builtin-change — Field value changed.
 * @event builtin-submit — Before submission (cancelable).
 * @event builtin-invalid — Validation failed.
 * @event builtin-reset — Form was reset.
 * @event builtin-submit-success — Submission succeeded.
 * @event builtin-submit-error — Submission failed.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "../lit-base.js";
import { asArray, titleCase, escapeHtml } from "../core.js";

export class BuiltinSchemaForm extends BuiltinBaseElement {
  static properties = {
    schema: { type: Array },
    value: { type: Object },
    endpoint: { type: String },
    method: { type: String },
    columns: { type: Number },
    submitLabel: { type: String, attribute: "submit-label" },
    resetLabel: { type: String, attribute: "reset-label" },
    hideReset: { type: Boolean, attribute: "hide-reset" },
    submittingLabel: { type: String, attribute: "submitting-label" },
    layout: { type: String },
    density: { type: String },
    labels: { type: Object },
    _value: { type: Object, state: true },
    _initialValue: { type: Object, state: true },
    _errors: { type: Object, state: true },
    _submitting: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .builtin-form { display: grid; gap: var(--builtin-form-gap, 14px); }
    .builtin-grid {
      display: grid;
      grid-template-columns: repeat(var(--builtin-columns, 1), minmax(0, 1fr));
      gap: var(--builtin-form-gap, 14px);
    }
    .builtin-field { display: grid; gap: 6px; align-content: start; }
    .builtin-label { font-weight: 650; color: var(--builtin-color-text, #111827); }
    .builtin-help { font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .builtin-field-error { min-height: 16px; font-size: 12px; color: var(--builtin-color-danger, #b91c1c); }
    .builtin-form-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
    .builtin-invalid input, .builtin-invalid select, .builtin-invalid textarea { border-color: var(--builtin-color-danger, #b91c1c); }
    input, select, textarea {
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff); color: inherit; min-height: 34px; padding: 6px 9px; width: 100%; font: inherit;
    }
    textarea { min-height: 88px; resize: vertical; }
    button[type="submit"], .btn-primary {
      background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff;
      padding: 8px 18px; border-radius: var(--builtin-radius, 6px); cursor: pointer; font: inherit; min-height: 36px;
    }
    button[type="submit"]:hover, .btn-primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    button:disabled { cursor: not-allowed; opacity: .55; }
    /* layouts */
    .horizontal .builtin-field {
      grid-template-columns: 140px 1fr;
      align-items: center;
    }
    .horizontal .builtin-help,
    .horizontal .builtin-field-error { grid-column: 2; }
    .compact .builtin-field { gap: 4px; }
    .compact .builtin-label { font-size: 12px; }
    .compact input, .compact select, .compact textarea { min-height: 28px; padding: 4px 6px; }
    /* density */
    .density-compact { --builtin-form-gap: 10px; }
    .density-normal { --builtin-form-gap: 14px; }
    .density-comfortable { --builtin-form-gap: 22px; }
    @media (max-width: 720px) {
      .builtin-grid { grid-template-columns: 1fr; }
      .horizontal .builtin-field { grid-template-columns: 1fr; }
      .horizontal .builtin-help, .horizontal .builtin-field-error { grid-column: auto; }
    }
  `;

  constructor() {
    super();
    this.schema = [];
    this.value = {};
    this.columns = 1;
    this.layout = "vertical";
    this.density = "normal";
    this._value = {};
    this._initialValue = {};
    this._errors = {};
  }

  connectedCallback() {
    super.connectedCallback();
    this._value = { ...(this.value || {}) };
    this._initialValue = { ...this._value };
  }

  willUpdate(changed) {
    if (changed.has("value") && this.value) {
      this._value = { ...this._value, ...this.value };
    }
  }

  getValue() {
    const out = {};
    for (const field of this._readSchema()) {
      if (field.default !== undefined && this._value[field.name] === undefined) {
        out[field.name] = field.default;
      }
    }
    return Object.assign(out, this._value);
  }

  setValue(name, value, options = {}) {
    this._value = { ...this._value, [name]: value };
    delete this._errors[name];
    if (!options.silent) this._emitChange(name, value);
  }

  setValues(values = {}, options = {}) {
    this._value = { ...this._value, ...values };
    this._errors = {};
    if (!options.silent) this._emitChange(null, this.getValue());
  }

  reset(values = this._initialValue) {
    this._value = { ...(values || {}) };
    this._errors = {};
    this.dispatchEvent(new CustomEvent("builtin-reset", { detail: { value: this.getValue() }, bubbles: true }));
  }

  setErrors(errors = {}) {
    this._errors = { ...errors };
  }

  validate() {
    const errors = {};
    for (const field of this._readSchema()) {
      if (field.hidden) continue;
      const value = this._fieldValue(field);
      if (field.required && (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length))) {
        errors[field.name] = field.requiredMessage || this._l("required", "Required");
        continue;
      }
      if (field.min !== undefined && Number(value) < Number(field.min)) errors[field.name] = this._l("min", "Minimum is {min}").replace("{min}", field.min);
      if (field.max !== undefined && Number(value) > Number(field.max)) errors[field.name] = this._l("max", "Maximum is {max}").replace("{max}", field.max);
      if (field.pattern && value) {
        const regex = field.pattern instanceof RegExp ? field.pattern : new RegExp(field.pattern);
        if (!regex.test(String(value))) errors[field.name] = field.patternMessage || this._l("invalidFormat", "Invalid format");
      }
      if (typeof field.validate === "function") {
        const result = field.validate(value, this.getValue(), field);
        if (result !== true && result !== undefined && result !== null) errors[field.name] = String(result);
      }
    }
    this._errors = errors;
    const ok = Object.keys(errors).length === 0;
    if (!ok) this.dispatchEvent(new CustomEvent("builtin-invalid", { detail: { errors }, bubbles: true }));
    return { ok, errors };
  }

  async submit() {
    const validation = this.validate();
    if (!validation.ok) return { ok: false, errors: validation.errors };
    const value = this.getValue();
    const submitEvent = new CustomEvent("builtin-submit", { detail: { value, form: this }, bubbles: true, cancelable: true });
    if (!this.dispatchEvent(submitEvent)) return { ok: true, cancelled: true, value };
    if (!this.endpoint) return { ok: true, value };
    this._submitting = true;
    try {
      const response = await fetch(this.endpoint, {
        method: this.method || "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(value),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      this.dispatchEvent(new CustomEvent("builtin-submit-success", { detail: { value, payload }, bubbles: true }));
      return { ok: true, value, payload };
    } catch (error) {
      this.dispatchEvent(new CustomEvent("builtin-submit-error", { detail: { value, error }, bubbles: true }));
      return { ok: false, value, error };
    } finally {
      this._submitting = false;
    }
  }

  _readSchema() {
    const raw = Array.isArray(this.schema) ? this.schema : (Array.isArray(this.schema?.fields) ? this.schema.fields : []);
    return raw
      .map((field) => (typeof field === "string" ? { name: field, label: titleCase(field), type: "text" } : Object.assign({ type: "text", label: titleCase(field.name || "") }, field)))
      .filter((field) => field.name);
  }

  _fieldValue(field) {
    if (this._value[field.name] !== undefined) return this._value[field.name];
    if (field.default !== undefined) return field.default;
    if (field.type === "checkbox" || field.type === "switch") return false;
    if (field.type === "tags") return [];
    return "";
  }

  _coerceValue(field, input) {
    if (field.type === "checkbox" || field.type === "switch") return Boolean(input.checked);
    if (field.type === "number" || field.type === "range") return input.value === "" ? null : Number(input.value);
    if (field.type === "json") {
      try { return JSON.parse(input.value || "null"); } catch (_err) { return input.value; }
    }
    if (field.type === "tags") return input.value.split(",").map((item) => item.trim()).filter(Boolean);
    if (field.multiple && input.selectedOptions) return Array.from(input.selectedOptions).map((option) => option.value);
    return input.value;
  }

  _onFieldInput(field, input) {
    const val = this._coerceValue(field, input);
    this._value = { ...this._value, [field.name]: val };
    delete this._errors[field.name];
    this._emitChange(field.name, val);
  }

  _onFieldChange(field, input) {
    const val = this._coerceValue(field, input);
    this._value = { ...this._value, [field.name]: val };
    delete this._errors[field.name];
    this._emitChange(field.name, val);
    this.requestUpdate();
  }

  _emitChange(name, value) {
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { name, value, values: this.getValue() }, bubbles: true }));
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _onSubmit(e) {
    e.preventDefault();
    this.submit();
  }

  _onReset() {
    this.reset();
  }

  _renderControl(field, value) {
    const name = field.name;
    const disabled = field.disabled;
    const placeholder = field.placeholder || "";
    const onInput = (e) => this._onFieldInput(field, e.target);
    const onChange = (e) => this._onFieldChange(field, e.target);

    if (field.type === "textarea" || field.type === "json") {
      const text = field.type === "json" && typeof value !== "string" ? JSON.stringify(value, null, 2) : (value ?? "");
      return html`<textarea name="${name}" ?disabled=${disabled} placeholder="${placeholder}" rows="${field.rows || 4}" .value=${text} @input=${onInput} @change=${onChange}></textarea>`;
    }

    if (field.type === "select" || field.options) {
      const options = asArray(field.options);
      return html`
        <select name="${name}" ?disabled=${disabled} ?multiple=${field.multiple} @change=${onChange}>
          ${options.map((option) => {
            const opt = typeof option === "string" ? { label: option, value: option } : option;
            const selected = field.multiple ? asArray(value).map(String).includes(String(opt.value)) : String(value) === String(opt.value);
            return html`<option value="${opt.value}" ?selected=${selected}>${opt.label ?? opt.value}</option>`;
          })}
        </select>
      `;
    }

    if (field.type === "checkbox" || field.type === "switch") {
      return html`<input name="${name}" type="checkbox" ?disabled=${disabled} ?checked=${value} @change=${onChange} />`;
    }

    if (field.type === "tags") {
      return html`<input name="${name}" type="text" ?disabled=${disabled} placeholder="${placeholder}" .value=${asArray(value).join(", ")} @input=${onInput} @change=${onChange} />`;
    }

    const type = field.type === "range" ? "range" : (field.type || "text");
    return html`<input name="${name}" type="${type}" ?disabled=${disabled} placeholder="${placeholder}" .value=${value ?? ""} min="${field.min ?? ""}" max="${field.max ?? ""}" step="${field.step ?? ""}" @input=${onInput} @change=${onChange} />`;
  }

  _renderField(field) {
    const value = this._fieldValue(field);
    const error = this._errors[field.name] || "";
    const span = field.span ? `grid-column: span ${Number(field.span)};` : "";
    return html`
      <label class="builtin-field ${error ? "builtin-invalid" : ""}" style="${span}" data-field="${field.name}">
        <span class="builtin-label">${field.label || field.name}${field.required ? " *" : ""}</span>
        ${this._renderControl(field, value)}
        ${field.help ? html`<span class="builtin-help">${field.help}</span>` : null}
        <span class="builtin-field-error">${error}</span>
      </label>
    `;
  }

  render() {
    const fields = this._readSchema().filter((field) => !field.hidden);
    const columns = Math.max(Number(this.columns) || 1, 1);
    const density = this.density || "normal";
    const layout = this.layout || "vertical";
    return html`
      <form class="builtin-form ${layout} density-${density}" novalidate @submit=${this._onSubmit} style="--builtin-columns:${columns}">
        <div class="builtin-grid">
          ${fields.map((field) => this._renderField(field))}
        </div>
        <slot name="extra"></slot>
        <div class="builtin-form-actions">
          <slot name="actions"></slot>
          ${!this.hideReset ? html`<button type="button" @click=${this._onReset}>${this.resetLabel || this._l("reset", "Reset")}</button>` : null}
          <button type="submit" class="btn-primary" ?disabled=${this._submitting}>
            ${this._submitting ? (this.submittingLabel || this._l("submitting", "Submitting...")) : (this.submitLabel || this._l("submit", "Submit"))}
          </button>
        </div>
      </form>
    `;
  }
}
