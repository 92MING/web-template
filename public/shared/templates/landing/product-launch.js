import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, nothing } from "../../components/lit-base.js";

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
 * @fileoverview BuiltinTplLandingProductLaunch - Product launch / waitlist page template.
 *
 * Attributes:
 *   - launch-date (string): ISO date string for the countdown timer.
 *   - teaser-content (string): Custom teaser text/HTML.
 *   - logos (Array): JSON array of logo objects {name, color}.
 *   - features (Array): JSON array of feature objects {icon, text}.
 *   - faq-items (Array): JSON array of {question, answer}.
 *   - labels: JSON object to override i18n strings
 *
 * Events:
 *   - builtin-subscribe: Fired when the early-access form is submitted.
 *   - builtin-cta-click: Fired when CTA buttons are clicked.
 *
 * Slots:
 *   - navbar: Custom navbar content
 *   - teaser: Custom teaser / video content
 */
export class BuiltinTplLandingProductLaunch extends BuiltinBaseElement {
  static properties = {
    launchDate: { type: String, attribute: "launch-date" },
    teaserContent: { type: String, attribute: "teaser-content" },
    logos: { type: Array },
    features: { type: Array },
    faqItems: { type: Array, attribute: "faq-items" },
    labels: { type: Object, converter: jsonConverter },
    _timeLeft: { type: Object, state: true },
      };

  static styles = css`
    :host { display: block; }
    .navbar {
      display: flex; align-items: center; justify-content: space-between;
      padding: 16px 24px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .navbar-brand { font-weight: 700; font-size: 18px; color: var(--builtin-color-text, #111827); display: flex; align-items: center; gap: 8px; }
    .hero {
      text-align: center; padding: 56px 24px 40px;
    }
    .hero h1 { font-size: 36px; margin: 0 0 12px; color: var(--builtin-color-text, #111827); }
    .hero p { font-size: 16px; color: var(--builtin-color-muted, #6b7280); max-width: 560px; margin: 0 auto 24px; }
    .countdown { display: flex; justify-content: center; gap: 16px; flex-wrap: wrap; }
    .cd-block { display: flex; flex-direction: column; align-items: center; min-width: 64px; }
    .cd-num { font-size: 32px; font-weight: 700; color: var(--builtin-primary, #2563eb); }
    .cd-unit { font-size: 12px; color: var(--builtin-color-muted, #6b7280); text-transform: uppercase; letter-spacing: .05em; }
    .teaser {
      max-width: 800px; margin: 24px auto; padding: 0 24px;
    }
    .teaser-placeholder {
      width: 100%; aspect-ratio: 16/9; background: var(--builtin-header-bg, #f9fafb);
      border: 2px dashed var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px);
      display: flex; align-items: center; justify-content: center; color: var(--builtin-color-muted, #6b7280);
    }
    .teaser-gradient {
      width: 100%; aspect-ratio: 16/9;
      background: linear-gradient(135deg, var(--builtin-primary, #2563eb), var(--builtin-primary-hover, #1d4ed8));
      border-radius: var(--builtin-radius-lg, 8px);
    }
    .features { max-width: 800px; margin: 0 auto; padding: 24px; }
    .features ul { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 24px; padding: 0; list-style: none; }
    .features li { display: flex; align-items: center; gap: 8px; color: var(--builtin-color-text, #111827); }
    .features li svg { flex-shrink: 0; }
    .subscribe {
      max-width: 480px; margin: 24px auto; padding: 24px;
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff); text-align: center;
    }
    .subscribe h3 { margin: 0 0 12px; }
    .subscribe form { display: flex; gap: 8px; }
    .subscribe input {
      flex: 1 1 auto;
      padding: 10px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      font: inherit;
    }
    .subscribe button {
      padding: 10px 18px;
      border-radius: var(--builtin-radius, 6px);
      font-weight: 600;
      cursor: pointer;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      border: 1px solid var(--builtin-primary, #2563eb);
      font: inherit;
    }
    .subscribe button:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .social-proof {
      display: flex; align-items: center; justify-content: center; gap: 24px; flex-wrap: wrap;
      padding: 24px; color: var(--builtin-color-muted, #6b7280);
    }
    .logo-item {
      width: 80px; height: 28px; border-radius: var(--builtin-radius, 6px);
    }
    .faq-section {
      max-width: 800px; margin: 0 auto; padding: 24px;
    }
    .faq-section h3 {
      font-size: 20px; font-weight: 700; margin-bottom: 16px; color: var(--builtin-color-text, #111827);
    }
    .footer {
      padding: 24px; text-align: center; color: var(--builtin-color-muted, #6b7280); font-size: 12px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .icon { width: 16px; height: 16px; vertical-align: middle; }

    @media (max-width: 720px) {
      .hero h1 { font-size: 28px; }
      .countdown { flex-direction: column; align-items: center; gap: 8px; }
      .cd-block { flex-direction: row; gap: 8px; }
      .features ul { grid-template-columns: 1fr; }
      .subscribe form { flex-direction: column; }
    }
  `;

  constructor() {
    super();
    this._timer = null;
    this._timeLeft = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this._startTimer();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._stopTimer();
  }

  _startTimer() {
    this._stopTimer();
    this._tick();
    this._timer = setInterval(() => this._tick(), 1000);
  }

  _stopTimer() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  _tick() {
    const iso = this.launchDate;
    if (!iso) {
      this._timeLeft = null;
      return;
    }
    const target = new Date(iso);
    if (isNaN(target.getTime())) {
      this._timeLeft = null;
      return;
    }
    const diff = target.getTime() - Date.now();
    if (diff <= 0) {
      this._timeLeft = { launched: true };
      this._stopTimer();
      return;
    }
    this._timeLeft = {
      days: Math.floor(diff / 86400000),
      hours: Math.floor((diff % 86400000) / 3600000),
      minutes: Math.floor((diff % 3600000) / 60000),
      seconds: Math.floor((diff % 60000) / 1000),
    };
  }

  _defaultFeatures() {
    return [
      { icon: "check", text: this._l("feature.performance", "Lightning fast performance") },
      { icon: "check", text: this._l("feature.security", "Bank-grade security") },
      { icon: "check", text: this._l("feature.collaboration", "Real-time collaboration") },
      { icon: "check", text: this._l("feature.integrations", "Powerful integrations") },
    ];
  }

  _defaultFaqItems() {
    return [
      { question: this._l("faq.q1", "When will it launch?"), answer: this._l("faq.a1", "Stay tuned for the exact date.") },
      { question: this._l("faq.q2", "Is there a free trial?"), answer: this._l("faq.a2", "Yes, a 14-day free trial will be available at launch.") },
    ];
  }

  _defaultLogos() {
    return [
      { name: "Logo 1", color: "#e5e7eb" },
      { name: "Logo 2", color: "#d1d5db" },
      { name: "Logo 3", color: "#9ca3af" },
      { name: "Logo 4", color: "#6b7280" },
    ];
  }

  _getFeatures() {
    return this.features || (this._defaultFeatures());
  }

  _getFaqItems() {
    return this.faqItems || (this._defaultFaqItems());
  }

  _getLogos() {
    return this.logos || (this._defaultLogos());
  }

  _handle_subscribe = (e) => {
    e.preventDefault();
    const email = this.shadowRoot.querySelector("input[type='email']")?.value?.trim() || "";
    this.dispatchEvent(new CustomEvent("builtin-subscribe", { bubbles: true, composed: true, detail: { email } }));
  }

  _on_cta_click = (action) => {
    this.dispatchEvent(new CustomEvent("builtin-cta-click", { bubbles: true, composed: true, detail: { action } }));
  }

  render() {
    const features = this._getFeatures();
    const logos = this._getLogos();
    const faqItems = this._getFaqItems();

    const countdown = () => {
      if (!this._timeLeft) {
        return html`<div class="countdown"><span>${this._l("countdown.soon", "Coming soon")}</span></div>`;
      }
      if (this._timeLeft.launched) {
        return html`<div class="countdown"><span>${this._l("countdown.launched", "Launched!")}</span></div>`;
      }
      const items = [
        { num: this._timeLeft.days, label: this._l("countdown.days", "Days") },
        { num: this._timeLeft.hours, label: this._l("countdown.hours", "Hours") },
        { num: this._timeLeft.minutes, label: this._l("countdown.mins", "Mins") },
        { num: this._timeLeft.seconds, label: this._l("countdown.secs", "Secs") },
      ];
      return html`
        <div class="countdown">
          ${items.map((i) => html`
            <div class="cd-block">
              <span class="cd-num">${i.num}</span>
              <span class="cd-unit">${i.label}</span>
            </div>
          `)}
        </div>
      `;
    };

    return html`
      <nav class="navbar">
        <slot name="navbar">
          <div class="navbar-brand">
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            ProductName
          </div>
          <div><a href="#" @click="${() => this._on_cta_click("signin")}" style="color:var(--builtin-color-muted, #6b7280); text-decoration:none;">${this._l("nav.signin", "Sign in")}</a></div>
        </slot>
      </nav>
      <section class="hero">
        <h1>${this._l("hero.title", "Something big is coming.")}</h1>
        <p>${this._l("hero.subtitle", "Be the first to experience the next generation of productivity.")}</p>
        ${countdown()}
      </section>
      <section class="teaser">
        <slot name="teaser">
          ${this.teaserContent
            ? html`<div class="teaser-placeholder">${this.teaserContent}</div>`
            : html`<div class="teaser-gradient"></div>`
          }
        </slot>
      </section>
      <section class="features">
        <ul>
          ${features.map((f) => html`
            <li>
              <builtin-icon name="${f.icon || "check"}" size="16" variant="outlined"></builtin-icon>
              ${f.text}
            </li>
          `)}
        </ul>
      </section>
      <section class="subscribe">
        <h3>${this._l("subscribe.title", "Get early access")}</h3>
        <form @submit="${this._handle_subscribe}">
          <input type="email" placeholder="${this._l("subscribe.placeholder", "you@example.com")}" required>
          <button type="submit">${this._l("subscribe.button", "Notify Me")}</button>
        </form>
      </section>
      <section class="social-proof">
        ${logos.map((logo) => html`
          <div class="logo-item" style="background:${logo.color || "var(--builtin-border-soft, #e5e7eb)"}" title="${logo.name || ""}"></div>
        `)}
      </section>
      ${faqItems.length > 0 ? html`
        <section class="faq-section">
          <h3>${this._l("faq.title", "Frequently Asked Questions")}</h3>
          <builtin-accordion items='${JSON.stringify(faqItems.map((f) => ({ title: f.question, content: f.answer })))}'></builtin-accordion>
        </section>
      ` : nothing}
      <footer class="footer">${this._l("footer.copyright", "\u00a9 2024 ProductName. All rights reserved.")}</footer>
    `;
  }
}