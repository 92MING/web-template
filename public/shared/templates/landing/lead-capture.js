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
 * @fileoverview BuiltinTplLandingLeadCapture - Lead generation / marketing landing page template.
 *
 * Attributes:
 *   - labels: JSON object to override i18n strings
 *   - features (Array): JSON array of feature objects {title, desc}.
 *   - testimonials (Array): JSON array of testimonial objects {quote, author}.
 *   - faqs (Array): JSON array of FAQ objects {question, answer}.
 *
 * Events:
 *   - builtin-lead-submit: Fired when the hero form is submitted. Detail: { email, name }.
 *   - builtin-cta-click: Fired when CTA buttons are clicked. Detail: { action }.
 *
 * Slots:
 *   - navbar: Navbar content
 *   - form: Custom hero form content
 *   - footer: Footer content
 */
export class BuiltinTplLandingLeadCapture extends BuiltinBaseElement {
  static properties = {
    labels: { type: Object, converter: jsonConverter },
        features: { type: Array, converter: jsonConverter },
    testimonials: { type: Array, converter: jsonConverter },
    faqs: { type: Array, converter: jsonConverter },
    _faqOpen: { type: Array, state: true },
  };

  static styles = css`
    :host { display: block; }
    .navbar {
      display: flex; align-items: center; justify-content: space-between;
      padding: 16px 24px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .hero {
      display: grid; grid-template-columns: 1fr 1fr; gap: 32px; align-items: center;
      max-width: 1100px; margin: 0 auto; padding: 48px 24px;
    }
    .hero h1 { font-size: 34px; margin: 0 0 14px; color: var(--builtin-color-text, #111827); line-height: 1.2; }
    .hero p { font-size: 16px; color: var(--builtin-color-muted, #6b7280); margin: 0 0 20px; }
    .hero-form {
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff); padding: 24px;
    }
    .hero-form h3 { margin: 0 0 14px; }
    .builtin-form { display: grid; gap: 14px; }
    .builtin-field { display: grid; gap: 4px; }
    .builtin-label { font-size: 13px; font-weight: 600; }
    .builtin-field input {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      font: inherit;
    }
    .trust {
      display: flex; align-items: center; justify-content: center; gap: 24px; flex-wrap: wrap;
      padding: 24px; color: var(--builtin-color-muted, #6b7280);
    }
    .trust-badge {
      display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-header-bg, #f9fafb); font-size: 12px;
    }
    .benefits {
      max-width: 1100px; margin: 0 auto; padding: 40px 24px;
    }
    .benefits h2 { text-align: center; margin: 0 0 24px; }
    .benefit-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
    .benefit-card {
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff); padding: 20px;
    }
    .benefit-card h4 { margin: 0 0 8px; }
    .testimonials {
      max-width: 1100px; margin: 0 auto; padding: 40px 24px;
    }
    .testimonials h2 { text-align: center; margin: 0 0 24px; }
    .testimonial-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .testimonial-card {
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff); padding: 20px;
    }
    .faq {
      max-width: 720px; margin: 0 auto; padding: 40px 24px;
    }
    .faq h2 { text-align: center; margin: 0 0 24px; }
    .faq-item { border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .faq-button {
      width: 100%; text-align: left; background: none; border: none; padding: 14px 0;
      font-weight: 650; cursor: pointer; display: flex; justify-content: space-between; align-items: center;
      color: var(--builtin-color-text, #111827);
    }
    .faq-button svg { transition: transform .2s ease; }
    .faq-button[aria-expanded="true"] svg { transform: rotate(45deg); }
    .faq-content {
      display: none;
      padding: 0 0 14px; color: var(--builtin-color-muted, #6b7280);
    }
    .faq-content.open { display: block; }
    .cta {
      text-align: center; padding: 56px 24px;
      background: var(--builtin-header-bg, #f9fafb); border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .cta h2 { margin: 0 0 14px; }
    .footer {
      padding: 24px; text-align: center; color: var(--builtin-color-muted, #6b7280); font-size: 12px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .icon { width: 16px; height: 16px; vertical-align: middle; flex-shrink: 0; }

    @media (max-width: 720px) {
      .hero { grid-template-columns: 1fr; }
      .benefit-grid { grid-template-columns: 1fr; }
      .testimonial-grid { grid-template-columns: 1fr; }
      .hero h1 { font-size: 28px; }
    }
  `;

  constructor() {
    super();
    this._faqOpen = [];
  }

  _defaultFeatures() {
    return [
      { title: this._l("benefit.capture", "Capture"), desc: this._l("benefit.captureDesc", "High-converting forms and landing pages that integrate with your stack.") },
      { title: this._l("benefit.nurture", "Nurture"), desc: this._l("benefit.nurtureDesc", "Automated email sequences and smart segmentation.") },
      { title: this._l("benefit.convert", "Convert"), desc: this._l("benefit.convertDesc", "Clear analytics and A/B testing to close more deals.") },
    ];
  }

  _defaultTestimonials() {
    return [
      { quote: this._l("testimonial.1", "Our lead volume doubled in the first month. The setup was incredibly simple."), author: this._l("testimonial.1author", "Alex R., Growth Lead") },
      { quote: this._l("testimonial.2", "Finally a tool that sales and marketing both agree on. Highly recommended."), author: this._l("testimonial.2author", "Jamie T., CMO") },
    ];
  }

  _defaultFaqs() {
    return [
      { question: this._l("faq.q1", "Is there a free plan?"), answer: this._l("faq.a1", "Yes, you can use the core features free forever.") },
      { question: this._l("faq.q2", "Can I cancel anytime?"), answer: this._l("faq.a2", "Absolutely. No contracts, no hassle.") },
      { question: this._l("faq.q3", "Do you offer support?"), answer: this._l("faq.a3", "Yes, we offer 24/7 chat and email support for all plans.") },
    ];
  }

  _toggleFaq(i) {
    const next = [...this._faqOpen];
    while (next.length <= i) next.push(false);
    next[i] = !next[i];
    this._faqOpen = next;
  }

  _handleSubmit(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const email = data.get("email") || "";
    const name = data.get("name") || "";
    this.dispatchEvent(new CustomEvent("builtin-lead-submit", {
      detail: { email, name },
      bubbles: true,
      composed: true,
    }));
  }

  _onCtaClick(action) {
    this.dispatchEvent(new CustomEvent("builtin-cta-click", {
      detail: { action },
      bubbles: true,
      composed: true,
    }));
  }

  render() {
    const features = this.features ?? (this._defaultFeatures());
    const testimonials = this.testimonials ?? (this._defaultTestimonials());
    const faqs = this.faqs ?? (this._defaultFaqs());

    return html`
      <nav class="navbar">
        <div style="font-weight:700;">${this._l("brand.name", "Brand")}</div>
        <div><slot name="navbar"></slot></div>
      </nav>
      <section class="hero">
        <div>
          <h1>${this._l("hero.title", "Turn visitors into customers.")}</h1>
          <p>${this._l("hero.subtitle", "The all-in-one platform for lead generation, nurturing, and conversion. No credit card required.")}</p>
          <button type="button" class="builtin-primary" @click=${() => this._onCtaClick("hero-get-started")}>${this._l("hero.cta", "Get Started")}</button>
        </div>
        <div class="hero-form">
          <slot name="form">
            <h3>${this._l("form.title", "Start your free trial")}</h3>
            <form @submit=${this._handleSubmit} class="builtin-form">
              <div class="builtin-field">
                <label class="builtin-label">${this._l("form.name", "Name")}</label>
                <input type="text" name="name" required>
              </div>
              <div class="builtin-field">
                <label class="builtin-label">${this._l("form.email", "Work Email")}</label>
                <input type="email" name="email" required>
              </div>
              <div class="builtin-field">
                <label class="builtin-label">${this._l("form.company", "Company")}</label>
                <input type="text" name="company">
              </div>
              <button type="submit" class="builtin-primary" style="width:100%;">${this._l("form.submit", "Create Account")}</button>
            </form>
          </slot>
        </div>
      </section>
      <section class="trust">
        <div class="trust-badge">
          <builtin-icon name="star" size="16" variant="outlined"></builtin-icon>
          ${this._l("trust.rated", "Rated 4.9/5")}
        </div>
        <div class="trust-badge">
          <builtin-icon name="lock" size="16" variant="outlined"></builtin-icon>
          ${this._l("trust.soc2", "SOC 2 Compliant")}
        </div>
        <div class="trust-badge">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          ${this._l("trust.teams", "10K+ Teams")}
        </div>
        <div class="trust-badge">
          <builtin-icon name="message" size="16" variant="outlined"></builtin-icon>
          ${this._l("trust.support", "24/7 Support")}
        </div>
      </section>
      <section class="benefits">
        <h2>${this._l("benefits.title", "Why teams choose us")}</h2>
        <div class="benefit-grid">
          ${features.map((f) => html`
            <div class="benefit-card">
              <h4>${f.title}</h4>
              <p style="color: var(--builtin-color-muted, #6b7280);">${f.desc}</p>
            </div>
          `)}
        </div>
      </section>
      <section class="testimonials">
        <h2>${this._l("testimonials.title", "Loved by marketers")}</h2>
        <div class="testimonial-grid">
          ${testimonials.map((t) => html`
            <div class="testimonial-card">
              <p>"${t.quote}"</p>
              <div style="margin-top:10px; font-size:12px; color: var(--builtin-color-muted, #6b7280);">— ${t.author}</div>
            </div>
          `)}
        </div>
      </section>
      <section class="faq">
        <h2>${this._l("faq.title", "Frequently Asked Questions")}</h2>
        ${faqs.map((f, i) => html`
          <div class="faq-item">
            <button type="button" class="faq-button" aria-expanded="${this._faqOpen[i] ?? false}" @click=${() => this._toggleFaq(i)}>
              ${f.question}
              <builtin-icon name="plus" size="16" variant="outlined"></builtin-icon>
            </button>
            <div class="faq-content ${classMap({ open: this._faqOpen[i] ?? false })}">${f.answer}</div>
          </div>
        `)}
      </section>
      <section class="cta">
        <h2>${this._l("cta.title", "Ready to grow?")}</h2>
        <p style="color: var(--builtin-color-muted, #6b7280);">${this._l("cta.subtitle", "Join thousands of teams already using our platform.")}</p>
        <button type="button" class="builtin-primary" @click=${() => this._onCtaClick("cta-get-started")}>${this._l("cta.button", "Get Started Now")}</button>
      </section>
      <footer class="footer"><slot name="footer"></slot></footer>
    `;
  }
}