import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) { if (!value) return undefined; try { return JSON.parse(value); } catch { return undefined; } },
  toAttribute(value) { return JSON.stringify(value); }
};

/**
 * @fileoverview BuiltinTplAuthLogin — Login page with multiple layouts.
 *
 * @attr {string} layout — 'centered' | 'split' | 'fullscreen'.
 * @attr {string} title — Page title.
 * @attr {string} subtitle — Subtitle text.
 * @attr {boolean} loading — Disable inputs and show loading state.
 * @attr {boolean} show-remember-me — Show remember me checkbox.
 * @attr {boolean} show-social-login — Show social login buttons.
 * @attr {string} hero-title — Split layout hero title.
 * @attr {string} hero-desc — Split layout hero description.
 * @attr {string} email-placeholder — Email input placeholder.
 * @attr {string} password-placeholder — Password input placeholder.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @slots
 *   - logo: Custom logo content.
 *   - side: Custom split-screen hero content.
 *   - form: Custom form area content.
 *   - footer: Footer area.
 */
export class BuiltinTplAuthLogin extends BuiltinBaseElement {
  static properties = {
    layout: { type: String },
    title: { type: String },
    subtitle: { type: String },
    loading: { type: Boolean },
    showRememberMe: { type: Boolean, attribute: "show-remember-me" },
    showSocialLogin: { type: Boolean, attribute: "show-social-login" },
    heroTitle: { type: String, attribute: "hero-title" },
    heroDesc: { type: String, attribute: "hero-desc" },
    emailPlaceholder: { type: String, attribute: "email-placeholder" },
    passwordPlaceholder: { type: String, attribute: "password-placeholder" },
    labels: { type: Object, converter: jsonConverter },
      };

  static styles = css`
    :host { display: block; min-height: 100vh; }
    .page { min-height: 100vh; display: flex; }
    .page.centered { align-items: center; justify-content: center; background: var(--builtin-header-bg, #f9fafb); padding: 20px; }
    .page.split { flex-direction: row; }
    .page.fullscreen { position: relative; }
    .side {
      flex: 1; display: flex; align-items: center; justify-content: center;
      background: linear-gradient(135deg, var(--builtin-primary, #2563eb), #1e40af); color: #fff; padding: 40px;
    }
    .side-content { max-width: 420px; }
    .side h2 { font-size: 32px; font-weight: 800; margin: 0 0 12px; }
    .side p { font-size: 16px; opacity: .9; margin: 0; }
    .form-area {
      flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px 20px; background: var(--builtin-surface, #ffffff);
    }
    .card {
      width: 100%; max-width: 420px; background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 12px);
      padding: 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.06);
    }
    .fullscreen .card {
      position: relative; z-index: 2; backdrop-filter: blur(12px);
      background: rgba(255,255,255,0.92); border: 1px solid rgba(255,255,255,0.4);
    }
    .logo { text-align: center; margin-bottom: 20px; }
    .logo h1 { margin: 0 0 6px; font-size: 22px; font-weight: 800; color: var(--builtin-color-text, #111827); }
    .logo p { margin: 0; font-size: 14px; color: var(--builtin-color-muted, #6b7280); }
    .field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
    .field label { font-size: 13px; font-weight: 600; color: var(--builtin-color-text, #111827); }
    .field input {
      padding: 10px 12px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff); color: var(--builtin-color-text, #111827); font: inherit;
    }
    .field input:disabled { opacity: .6; cursor: not-allowed; }
    .actions { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; font-size: 13px; }
    .actions a { color: var(--builtin-primary, #2563eb); text-decoration: none; }
    .submit {
      width: 100%; padding: 12px; border-radius: var(--builtin-radius, 6px); border: none;
      background: var(--builtin-primary, #2563eb); color: #fff; font-weight: 600; cursor: pointer; font: inherit;
    }
    .submit:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .submit:disabled { opacity: .6; cursor: not-allowed; }
    .divider { display: flex; align-items: center; gap: 12px; margin: 18px 0; color: var(--builtin-color-muted, #6b7280); font-size: 13px; }
    .divider::before, .divider::after { content: ''; flex: 1; height: 1px; background: var(--builtin-border-soft, #e5e7eb); }
    .social { display: flex; justify-content: center; gap: 12px; }
    .social-btn {
      display: flex; align-items: center; justify-content: center; gap: 6px;
      padding: 8px 16px; border-radius: var(--builtin-radius, 6px); border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff); color: var(--builtin-color-text, #111827);
      font-weight: 600; cursor: pointer; font: inherit;
    }
    .social-btn:disabled { opacity: .6; cursor: not-allowed; }
    .footer-text { text-align: center; margin-top: 18px; font-size: 13px; color: var(--builtin-color-muted, #6b7280); }
    .footer-text a { color: var(--builtin-primary, #2563eb); text-decoration: none; }
    .bg {
      position: fixed; inset: 0; z-index: 0;
      background: linear-gradient(135deg, #0f172a, #1e3a8a, #312e81);
    }
    @media (max-width: 720px) {
      .page.split { flex-direction: column; }
      .side { min-height: 180px; padding: 24px; }
      .side h2 { font-size: 22px; }
      .card { padding: 24px; }
    }
  `;

  _default_title() {
    return "Welcome back";
  }

  _default_subtitle() {
    return "Sign in to your account";
  }

  _default_hero_title() {
    return "Build faster";
  }

  _default_hero_desc() {
    return "The all-in-one platform to launch, grow, and manage your projects.";
  }

  _default_email_placeholder() {
    return "you@example.com";
  }

  _default_password_placeholder() {
    return "••••••••";
  }

  _on_submit(e) {
    e.preventDefault();
    const form = e.target;
    const email = form.email.value;
    const password = form.password.value;
    const remember_me = form.remember?.checked || false;
    this.dispatchEvent(new CustomEvent("builtin-login", {
      bubbles: true,
      composed: true,
      detail: { email, password, rememberMe: remember_me },
    }));
  }

  _on_social_login(provider) {
    this.dispatchEvent(new CustomEvent("builtin-social-login", {
      bubbles: true,
      composed: true,
      detail: { provider },
    }));
  }

  render() {
    const layout = this.layout || "centered";
    const title = this.title || (this._default_title());
    const subtitle = this.subtitle || (this._default_subtitle());
    const hero_title = this.heroTitle || (this._default_hero_title());
    const hero_desc = this.heroDesc || (this._default_hero_desc());
    const email_placeholder = this.emailPlaceholder || (this._default_email_placeholder());
    const password_placeholder = this.passwordPlaceholder || (this._default_password_placeholder());

    const default_form = html`
      <form @submit="${(e) => this._on_submit(e)}">
        <div class="field">
          <label>${this._l("login.email", "Email")}</label>
          <input name="email" type="email" placeholder="${email_placeholder}" required ?disabled="${this.loading}" />
        </div>
        <div class="field">
          <label>${this._l("login.password", "Password")}</label>
          <input name="password" type="password" placeholder="${password_placeholder}" required ?disabled="${this.loading}" />
        </div>
        <div class="actions">
          ${this.showRememberMe ? html`
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;color:var(--builtin-color-muted);">
              <input name="remember" type="checkbox" ?disabled="${this.loading}" /> ${this._l("login.remember", "Remember me")}
            </label>
          ` : html`<span></span>`}
          <a href="#" @click="${(e) => { e.preventDefault(); this.dispatchEvent(new CustomEvent('builtin-forgot', { bubbles: true, composed: true })); }}">${this._l("login.forgot", "Forgot password?")}</a>
        </div>
        <button class="submit" ?disabled="${this.loading}">${this.loading ? this._l("login.loading", "Signing in...") : this._l("login.submit", "Sign In")}</button>
      </form>
      ${this.showSocialLogin ? html`
        <div class="divider">${this._l("login.or", "or continue with")}</div>
        <div class="social">
          <button class="social-btn" ?disabled="${this.loading}" @click="${() => this._on_social_login("google")}">
            <builtin-icon name="google" size="16"></builtin-icon> Google
          </button>
          <button class="social-btn" ?disabled="${this.loading}" @click="${() => this._on_social_login("github")}">
            <builtin-icon name="github" size="16"></builtin-icon> GitHub
          </button>
          <button class="social-btn" ?disabled="${this.loading}" @click="${() => this._on_social_login("twitter")}">
            <builtin-icon name="twitter" size="16"></builtin-icon> Twitter
          </button>
        </div>
      ` : ""}
      <div class="footer-text">
        ${this._l("login.noAccount", "Don't have an account?")} <a href="#">${this._l("login.register", "Sign up")}</a>
      </div>
    `;

    const form_card = html`
      <div class="card">
        <div class="logo">
          <slot name="logo"><h1>${title}</h1><p>${subtitle}</p></slot>
        </div>
        <slot name="form">${default_form}</slot>
      </div>
    `;

    if (layout === "split") {
      return html`
        <div class="page split">
          <div class="side">
            <div class="side-content">
              <slot name="side">
                <h2>${hero_title}</h2>
                <p>${hero_desc}</p>
              </slot>
            </div>
          </div>
          <div class="form-area">${form_card}</div>
        </div>
      `;
    }

    if (layout === "fullscreen") {
      return html`
        <div class="page fullscreen">
          <div class="bg"></div>
          <div class="form-area" style="position:relative;z-index:2;">${form_card}</div>
        </div>
      `;
    }

    return html`
      <div class="page centered">
        ${form_card}
        <slot name="footer"></slot>
      </div>
    `;
  }
}