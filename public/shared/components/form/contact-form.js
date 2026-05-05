/**
 * @fileoverview BuiltinContactForm — A contact form with name, email, subject, and message fields.
 *
 * @element builtin-contact-form
 *
 * @attr {string} preset — `simple` | `full` | `support`.
 * @attr {string} endpoint — URL to POST the form data to. If omitted, emits `builtin-submit` event.
 * @attr {string} submit-label — Label for the submit button.
 *
 * @event builtin-submit — Fired when the form is submitted without an endpoint.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "../lit-base.js";

export class BuiltinContactForm extends BuiltinBaseElement {
  static properties = {
    preset: { type: String },
    endpoint: { type: String },
    submitLabel: { type: String, attribute: "submit-label" },
    labels: { type: Object },
    _errors: { type: Object, state: true },
    _status: { type: String, state: true },
    _statusError: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    * { box-sizing: border-box; }
    .form-wrap {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      padding: 24px;
    }
    form {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--builtin-form-gap, 14px);
    }
    .builtin-field {
      display: grid; gap: 6px; align-content: start; min-width: 0;
    }
    .builtin-field.full-width { grid-column: 1 / -1; }
    .builtin-label { font-weight: 650; color: var(--builtin-color-text, #111827); }
    input, textarea {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit; min-height: 34px; padding: 6px 9px; width: 100%; max-width: 100%; font: inherit; box-sizing: border-box;
    }
    textarea { min-height: 120px; resize: vertical; }
    .builtin-invalid input, .builtin-invalid textarea { border-color: var(--builtin-color-danger, #b91c1c); }
    .builtin-field-error { min-height: 16px; font-size: 12px; color: var(--builtin-color-danger, #b91c1c); }
    .actions {
      grid-column: 1 / -1;
      display: flex; justify-content: flex-end; gap: 8px;
    }
    button[type="submit"] {
      background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff;
      padding: 8px 18px; border-radius: var(--builtin-radius, 6px); cursor: pointer; font: inherit; min-height: 36px;
    }
    button[type="submit"]:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .status { margin-top: 10px; font-size: 13px; display: none; }
    .status.visible { display: block; }
    @media (max-width: 720px) {
      .form-wrap { padding: 16px; }
      form { grid-template-columns: 1fr; }
      .actions { justify-content: stretch; }
      button[type="submit"] { width: 100%; }
    }
  `;

  constructor() {
    super();
    this.preset = "full";
    this._errors = {};
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _fieldLabel(key) {
    const map = {
      name: this._l("contact.name", "Name"),
      email: this._l("contact.email", "Email"),
      subject: this._l("contact.subject", "Subject"),
      message: this._l("contact.message", "Message"),
    };
    return map[key] || key;
  }

  _validate(values) {
    const errors = {};
    if (!values.name || values.name.trim().length < 1) errors.name = this._l("error.nameRequired", "Name is required.");
    if (!values.email || !/^[^\s@]+@[^\s@\.]+\.[^\s@]+$/.test(values.email)) errors.email = this._l("error.emailInvalid", "A valid email is required.");
    if (!values.subject || values.subject.trim().length < 1) errors.subject = this._l("error.subjectRequired", "Subject is required.");
    if (!values.message || values.message.trim().length < 5) errors.message = this._l("error.messageMin", "Message must be at least 5 characters.");
    return errors;
  }

  async _onSubmit(event) {
    event.preventDefault();
    const form = event.target;
    const values = {
      name: form.elements.name?.value || "",
      email: form.elements.email?.value || "",
      subject: form.elements.subject?.value || "",
      message: form.elements.message?.value || "",
    };
    const visibleFields = this._visibleFields();
    const errors = {};
    const base = this._validate(values);
    for (const key of visibleFields) {
      if (base[key]) errors[key] = base[key];
    }
    this._errors = errors;
    if (Object.keys(errors).length > 0) return;

    const endpoint = this.endpoint;
    if (endpoint) {
      try {
        const res = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        this._showStatus(this._l("contact.success", "Message sent successfully."), false);
        form.reset();
      } catch (_err) {
        this._showStatus(this._l("contact.error", "Failed to send message. Please try again."), true);
      }
    } else {
      this.dispatchEvent(new CustomEvent("builtin-submit", { bubbles: true, composed: true, detail: values }));
      this._showStatus(this._l("contact.success", "Message sent successfully."), false);
      form.reset();
    }
  }

  _showStatus(text, isError) {
    this._status = text;
    this._statusError = isError;
    setTimeout(() => { this._status = ""; }, 4000);
  }

  _visibleFields() {
    const p = this.preset || "full";
    if (p === "simple") return ["name", "email", "message"];
    if (p === "support") return ["email", "subject", "message"];
    return ["name", "email", "subject", "message"];
  }

  _fieldClass(key) {
    return classMap({ "builtin-field": true, "full-width": key === "subject" || key === "message", "builtin-invalid": !!this._errors[key] });
  }

  render() {
    const visible = this._visibleFields();
    const submit = this.submitLabel || this._l("contact.send", "Send Message");
    return html`
      <div class="form-wrap">
        <form novalidate @submit=${this._onSubmit}>
          ${visible.includes("name") ? html`
            <div class="${this._fieldClass("name")}">
              <label class="builtin-label" for="name">${this._fieldLabel("name")}</label>
              <input id="name" name="name" type="text" placeholder="${this._l("contact.namePlaceholder", "Your name")}" />
              <div class="builtin-field-error">${this._errors.name || ""}</div>
            </div>
          ` : null}
          ${visible.includes("email") ? html`
            <div class="${this._fieldClass("email")}">
              <label class="builtin-label" for="email">${this._fieldLabel("email")}</label>
              <input id="email" name="email" type="email" placeholder="${this._l("contact.emailPlaceholder", "you@example.com")}" />
              <div class="builtin-field-error">${this._errors.email || ""}</div>
            </div>
          ` : null}
          ${visible.includes("subject") ? html`
            <div class="${this._fieldClass("subject")}">
              <label class="builtin-label" for="subject">${this._fieldLabel("subject")}</label>
              <input id="subject" name="subject" type="text" placeholder="${this._l("contact.subjectPlaceholder", "How can we help?")}" />
              <div class="builtin-field-error">${this._errors.subject || ""}</div>
            </div>
          ` : null}
          ${visible.includes("message") ? html`
            <div class="${this._fieldClass("message")}">
              <label class="builtin-label" for="message">${this._fieldLabel("message")}</label>
              <textarea id="message" name="message" placeholder="${this._l("contact.messagePlaceholder", "Tell us more...")}"></textarea>
              <div class="builtin-field-error">${this._errors.message || ""}</div>
            </div>
          ` : null}
          <div class="actions">
            <button type="submit">${submit}</button>
          </div>
        </form>
        <div class="status ${classMap({ visible: !!this._status, "builtin-error": this._statusError, "builtin-muted": !this._statusError })}">${this._status}</div>
      </div>
    `;
  }
}
