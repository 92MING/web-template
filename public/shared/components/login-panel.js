/**
 * @fileoverview BuiltinLoginPanel — Login / registration panel web component.
 *
 * @element builtin-login-panel
 *
 * @attr {string} mode — `email-password` | `phone-otp` | `qr-scan` | `social-only` | `multi-step`.
 * @attr {string} endpoint — URL to POST the form data to.
 * @attr {string} title — Panel heading text.
 *
 * @slot oauth — Social / OAuth login buttons.
 * @slot extra — Extra content rendered below the form.
 *
 * @event builtin-submit — Dispatched on form submission.
 * @event builtin-send-otp — Dispatched when requesting OTP.
 * @event builtin-qr-refresh — Dispatched when QR refresh is requested.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

export class BuiltinLoginPanel extends BuiltinBaseElement {
  static properties = {
    mode: { type: String },
    endpoint: { type: String },
    title: { type: String },
    surface: { type: String },
    fields: { type: Array },
    labels: { type: Object },
    _step: { type: Number, state: true },
    _contact: { type: String, state: true },
    _otpSent: { type: Boolean, state: true },
    _qrData: { type: String, state: true },
    _loading: { type: Boolean, state: true },
    _error: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .panel {
      max-width: 400px; margin: 0 auto; padding: 24px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
    }
    .panel.plain {
      max-width: none;
      margin: 0;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
    }
    h2 { margin: 0 0 16px; font-size: 1.25rem; color: var(--builtin-color-text, #111827); }
    .form { display: grid; gap: var(--builtin-form-gap, 14px); }
    .field { display: grid; gap: 6px; }
    .label { font-weight: 650; color: var(--builtin-color-text, #111827); }
    input {
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff); color: inherit; min-height: 34px; padding: 6px 9px; width: 100%; font: inherit;
    }
    .error { min-height: 18px; font-size: 13px; color: var(--builtin-color-danger, #b91c1c); }
    .actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
    .oauth { margin-top: 12px; }
    .extra { margin-top: 12px; }
    .social-only { display: flex; flex-direction: column; align-items: center; gap: 12px; text-align: center; }
    .qr-box {
      width: 180px; height: 180px; margin: 0 auto;
      border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px);
      display: flex; align-items: center; justify-content: center; background: var(--builtin-input-bg, #ffffff);
    }
    .link-btn {
      background: none; border: none; padding: 0; color: var(--builtin-primary, #2563eb); cursor: pointer; font-size: 13px;
    }
    .link-btn:hover { text-decoration: underline; }
    button[type="submit"], .btn-primary {
      background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff;
      padding: 8px 18px; border-radius: var(--builtin-radius, 6px); cursor: pointer; font: inherit; min-height: 36px;
    }
    button[type="submit"]:hover, .btn-primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    @media (max-width: 720px) {
      .panel { max-width: 100%; padding: 16px; border-radius: 0; border-left: 0; border-right: 0; }
      input, button { min-height: 44px; font-size: 16px; }
      .actions { justify-content: stretch; }
      .actions button { width: 100%; }
    }
  `;

  constructor() {
    super();
    this.mode = "email-password";
    this.surface = "panel";
    this.fields = [];
    this._step = 1;
    this._contact = "";
    this._otpSent = false;
    this._qrData = "";
    this._loading = false;
    this._error = "";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _isEmailLike(value) {
    return /^[^\s@]+@[^\s@\.]+\.[^\s@]+$/.test(value);
  }

  _matchingFields(mode, step = null) {
    const fields = Array.isArray(this.fields) ? this.fields : [];
    return fields.filter((field) => {
      const modes = Array.isArray(field.modes) ? field.modes : (field.mode ? [field.mode] : []);
      if (modes.length && !modes.includes(mode)) return false;
      if (field.step == null) return step == null;
      return field.step === step;
    });
  }

  _readFieldValue(form, field) {
    const input = form?.elements?.[field.name];
    if (!input) return field.type === "checkbox" ? !!field.checked : "";
    if (field.type === "checkbox") return !!input.checked;
    return input.value;
  }

  _collectFieldValues(form, mode, step = null) {
    const values = {};
    for (const field of this._matchingFields(mode, step)) {
      values[field.name] = this._readFieldValue(form, field);
    }
    return values;
  }

  _renderField(field) {
    const label = field.label || field.name;
    if (field.type === "select") {
      return html`
        <div class="field">
          <label class="label" for="${field.name}">${label}</label>
          <select id="${field.name}" name="${field.name}" ?required=${!!field.required}>
            ${(field.options || []).map((option) => html`<option value="${option.value}">${option.label}</option>`)}
          </select>
        </div>
      `;
    }
    if (field.type === "textarea") {
      return html`
        <div class="field">
          <label class="label" for="${field.name}">${label}</label>
          <textarea id="${field.name}" name="${field.name}" placeholder="${field.placeholder || ""}" ?required=${!!field.required}></textarea>
        </div>
      `;
    }
    if (field.type === "checkbox") {
      return html`
        <label class="label" style="display:flex;align-items:center;gap:8px;">
          <input name="${field.name}" type="checkbox" ?checked=${!!field.checked} />
          ${label}
        </label>
      `;
    }
    return html`
      <div class="field">
        <label class="label" for="${field.name}">${label}</label>
        <input id="${field.name}" name="${field.name}" type="${field.type || "text"}" placeholder="${field.placeholder || ""}" ?required=${!!field.required} />
      </div>
    `;
  }

  _onEmailPasswordSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const email = (form.elements.email?.value || "").trim();
    const password = form.elements.password?.value || "";
    if (!email || !password) {
      this._error = this._l("login.required", "Email and password are required.");
      return;
    }
    this._error = "";
    const detail = { mode: "email-password", email, password, ...this._collectFieldValues(form, "email-password") };
    this.dispatchEvent(new CustomEvent("builtin-submit", { detail, bubbles: true, composed: true }));
    if (this.endpoint) this._post(detail);
  }

  _onSendOtp() {
    let phone = "";
    if (this.mode === "phone-otp") {
      phone = (this.shadowRoot.querySelector('[name="phone"]')?.value || "").trim();
    } else if (this.mode === "multi-step") {
      phone = this._contact;
    }
    if (!phone) {
      this._error = this._l("login.phoneRequired", "Phone number is required.");
      return;
    }
    this._error = "";
    this._otpSent = true;
    this.dispatchEvent(new CustomEvent("builtin-send-otp", { detail: { phone }, bubbles: true, composed: true }));
  }

  _onPhoneOtpSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const phone = (form.elements.phone?.value || "").trim();
    const code = (form.elements.code?.value || "").trim();
    if (!phone || !code) {
      this._error = this._l("login.codeRequired", "Phone and code are required.");
      return;
    }
    this._error = "";
    const detail = { mode: "phone-otp", phone, code, ...this._collectFieldValues(form, "phone-otp") };
    this.dispatchEvent(new CustomEvent("builtin-submit", { detail, bubbles: true, composed: true }));
    if (this.endpoint) this._post(detail);
  }

  _onQrRefresh() {
    this.dispatchEvent(new CustomEvent("builtin-qr-refresh", { bubbles: true, composed: true }));
  }

  _onMultiStepSubmit(e) {
    e.preventDefault();
    if (this._step === 1) {
      const contact = (e.target.elements.contact?.value || "").trim();
      if (!contact) {
        this._error = this._l("login.contactRequired", "Email or phone is required.");
        return;
      }
      this._error = "";
      this._contact = contact;
      this._step = 2;
      return;
    }
    const password = (e.target.elements.password?.value || "").trim();
    const code = (e.target.elements.code?.value || "").trim();
    const isPhone = !this._isEmailLike(this._contact);
    if (isPhone && !code) {
      this._error = this._l("login.codeRequired", "Code is required.");
      return;
    }
    if (!isPhone && !password) {
      this._error = this._l("login.passwordRequired", "Password is required.");
      return;
    }
    this._error = "";
    const detail = { mode: "multi-step", contact: this._contact, password, code, ...this._collectFieldValues(e.target, "multi-step", 2) };
    this.dispatchEvent(new CustomEvent("builtin-submit", { detail, bubbles: true, composed: true }));
    if (this.endpoint) this._post(detail);
  }

  async _post(detail) {
    this._loading = true;
    try {
      const res = await fetch(this.endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(detail) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      this._error = String(err.message || err);
    } finally {
      this._loading = false;
    }
  }

  render() {
    const mode = this.mode || "email-password";
    const titleText = this.title || this._l("login.title", "Sign in");
    return html`
      <div class="panel ${classMap({ plain: this.surface === "plain" })}">
        <h2>${titleText}</h2>
        ${this._error ? html`<div class="error">${this._error}</div>` : null}
        ${mode === "email-password" ? this._renderEmailPassword() : null}
        ${mode === "phone-otp" ? this._renderPhoneOtp() : null}
        ${mode === "qr-scan" ? this._renderQrScan() : null}
        ${mode === "social-only" ? this._renderSocialOnly() : null}
        ${mode === "multi-step" ? this._renderMultiStep() : null}
        ${mode !== "social-only" ? html`<div class="oauth"><slot name="oauth"></slot></div>` : null}
        <div class="extra"><slot name="extra"></slot></div>
      </div>
    `;
  }

  _renderEmailPassword() {
    const extraFields = this._matchingFields("email-password");
    return html`
      <form class="form" @submit=${this._onEmailPasswordSubmit}>
        <div class="field">
          <label class="label" for="email">${this._l("login.email", "Email")}</label>
          <input id="email" name="email" type="email" placeholder="you@example.com" required />
        </div>
        <div class="field">
          <label class="label" for="password">${this._l("login.password", "Password")}</label>
          <input id="password" name="password" type="password" placeholder="••••••••" required />
        </div>
        ${extraFields.map((field) => this._renderField(field))}
        <div class="actions">
          <button type="submit" class="btn-primary" ?disabled=${this._loading}>${this._loading ? this._l("login.loading", "Loading...") : this._l("login.signIn", "Sign in")}</button>
        </div>
      </form>
    `;
  }

  _renderPhoneOtp() {
    const extraFields = this._matchingFields("phone-otp");
    return html`
      <form class="form" @submit=${this._onPhoneOtpSubmit}>
        <div class="field">
          <label class="label" for="phone">${this._l("login.phone", "Phone")}</label>
          <input id="phone" name="phone" type="tel" placeholder="+1 234 567 890" required />
          <button type="button" class="link-btn" @click=${this._onSendOtp}>${this._l("login.sendCode", "Send code")}</button>
        </div>
        ${this._otpSent ? html`
          <div class="field">
            <label class="label" for="code">${this._l("login.code", "Verification code")}</label>
            <input id="code" name="code" type="text" inputmode="numeric" placeholder="123456" required />
          </div>
        ` : null}
        ${extraFields.map((field) => this._renderField(field))}
        <div class="actions">
          <button type="submit" class="btn-primary" ?disabled=${this._loading || !this._otpSent}>${this._loading ? this._l("login.loading", "Loading...") : this._l("login.verify", "Verify")}</button>
        </div>
      </form>
    `;
  }

  _renderQrScan() {
    return html`
      <div style="text-align:center;">
        <div class="qr-box">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
        </div>
        <p class="builtin-muted" style="font-size:13px;margin-top:8px;">${this._l("login.qrHint", "Scan the QR code with your authenticator app.")}</p>
        <button type="button" class="link-btn" @click=${this._onQrRefresh}>${this._l("login.refresh", "Refresh")}</button>
      </div>
    `;
  }

  _renderSocialOnly() {
    return html`
      <div class="social-only">
        <p>${this._l("login.socialHint", "Sign in with your social account.")}</p>
        <slot name="oauth"></slot>
      </div>
    `;
  }

  _renderMultiStep() {
    if (this._step === 1) {
      const stepOneFields = this._matchingFields("multi-step", 1);
      return html`
        <form class="form" @submit=${this._onMultiStepSubmit}>
          <div class="field">
            <label class="label" for="contact">${this._l("login.emailOrPhone", "Email or phone")}</label>
            <input id="contact" name="contact" type="text" placeholder="you@example.com or +1 234 567 890" required />
          </div>
          ${stepOneFields.map((field) => this._renderField(field))}
          <div class="actions">
            <button type="submit" class="btn-primary">${this._l("login.continue", "Continue")}</button>
          </div>
        </form>
      `;
    }
    const isPhone = !this._isEmailLike(this._contact);
    const stepTwoFields = this._matchingFields("multi-step", 2);
    return html`
      <form class="form" @submit=${this._onMultiStepSubmit}>
        <div class="field">
          <label class="label">${this._l("login.contact", "Contact")}</label>
          <div style="display:flex;align-items:center;gap:8px;">
            <input value="${this._contact}" disabled style="flex:1;" />
            <button type="button" class="link-btn" @click=${() => { this._step = 1; this._otpSent = false; }}>${this._l("login.change", "Change")}</button>
          </div>
        </div>
        ${isPhone ? html`
          <div class="field">
            <label class="label" for="code">${this._l("login.code", "Verification code")}</label>
            <input id="code" name="code" type="text" inputmode="numeric" placeholder="123456" required />
            <button type="button" class="link-btn" @click=${this._onSendOtp}>${this._l("login.sendCode", "Send code")}</button>
          </div>
        ` : html`
          <div class="field">
            <label class="label" for="password">${this._l("login.password", "Password")}</label>
            <input id="password" name="password" type="password" placeholder="••••••••" required />
          </div>
        `}
        ${stepTwoFields.map((field) => this._renderField(field))}
        <div class="actions">
          <button type="submit" class="btn-primary" ?disabled=${this._loading}>${this._loading ? this._l("login.loading", "Loading...") : this._l("login.signIn", "Sign in")}</button>
        </div>
      </form>
    `;
  }
}
