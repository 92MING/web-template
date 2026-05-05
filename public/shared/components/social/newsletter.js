/**
 * @fileoverview BuiltinNewsletter — An email subscription component with input and subscribe button.
 *
 * @element builtin-newsletter
 *
 * @attr {string} layout — `inline` | `stacked` | `hero`.
 * @attr {string} title — Heading text above the form.
 * @attr {string} description — Subtitle or helper text.
 * @attr {string} button-label — Label for the subscribe button.
 * @attr {string} endpoint — URL to POST the email to. If omitted, emits `builtin-subscribe` event.
 *
 * @event builtin-subscribe — Detail: `{ email }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "../lit-base.js";

export class BuiltinNewsletter extends BuiltinBaseElement {
  static properties = {
    layout: { type: String },
    title: { type: String },
    description: { type: String },
    buttonLabel: { type: String, attribute: "button-label" },
    endpoint: { type: String },
    labels: { type: Object },
    _success: { type: Boolean, state: true },
    _error: { type: Boolean, state: true },
    _message: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      padding: 24px;
      display: flex; flex-direction: column; gap: 12px;
      color: var(--builtin-color-text, #111827);
    }
    .wrap.hero {
      text-align: center; padding: 40px 24px;
    }
    .title { font-weight: 650; font-size: 18px; color: var(--builtin-color-text, #111827); margin: 0; }
    .wrap.hero .title { font-size: 24px; }
    .desc { font-size: 14px; color: var(--builtin-color-muted, #6b7280); margin: 0; }
    form {
      display: flex; align-items: flex-start; gap: 10px;
    }
    .wrap.stacked form, .wrap.hero form { flex-direction: column; align-items: stretch; }
    .field {
      flex: 1 1 auto; display: flex; flex-direction: column; gap: 4px;
    }
    .field input {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit; min-height: 34px; padding: 6px 9px; width: 100%; font: inherit;
    }
    .builtin-invalid input { border-color: var(--builtin-color-danger, #b91c1c); }
    .field-error { min-height: 16px; font-size: 12px; color: var(--builtin-color-danger, #b91c1c); }
    button[type="submit"] {
      background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff;
      padding: 8px 18px; border-radius: var(--builtin-radius, 6px); cursor: pointer; font: inherit; min-height: 36px; white-space: nowrap;
    }
    button[type="submit"]:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .success { font-size: 14px; color: var(--builtin-color-success, #16a34a); }
    @media (max-width: 720px) {
      .wrap { padding: 16px; }
      form { flex-direction: column; align-items: stretch; }
      button[type="submit"] { width: 100%; }
    }
  `;

  constructor() {
    super();
    this.layout = "inline";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _validate(email) {
    if (!email) return this._l("error.emailRequired", "Email is required.");
    if (!/^[^\s@]+@[^\s@\.]+\.[^\s@]+$/.test(email)) return this._l("error.emailInvalid", "Please enter a valid email address.");
    return "";
  }

  async _onSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const email = (form.elements.email?.value || "").trim();
    const error = this._validate(email);
    if (error) {
      this._error = true;
      this._message = error;
      return;
    }
    this._error = false;
    this._message = "";

    if (this.endpoint) {
      try {
        const res = await fetch(this.endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        this._success = true;
        form.reset();
      } catch (_err) {
        this._message = this._l("subscribe.error", "Subscription failed. Please try again.");
        this._error = true;
      }
    } else {
      this.dispatchEvent(new CustomEvent("builtin-subscribe", { bubbles: true, composed: true, detail: { email } }));
      this._success = true;
      form.reset();
    }
  }

  render() {
    const layout = this.layout || "inline";
    const btnLabel = this.buttonLabel || this._l("subscribe.button", "Subscribe");
    return html`
      <div class="wrap ${layout}">
        ${this.title ? html`<h3 class="title">${this.title}</h3>` : null}
        ${this.description ? html`<p class="desc">${this.description}</p>` : null}
        ${this._success
          ? html`<div class="success">${this._l("subscribe.success", "Thanks for subscribing!")}</div>`
          : html`
            <form novalidate @submit=${this._onSubmit}>
              <div class="field ${classMap({ "builtin-invalid": this._error })}">
                <input name="email" type="email" placeholder="${this._l("subscribe.placeholder", "you@example.com")}" aria-label="${this._l("subscribe.email", "Email address")}" />
                <div class="field-error">${this._message || ""}</div>
              </div>
              <button type="submit">${btnLabel}</button>
            </form>
          `}
      </div>
    `;
  }
}
