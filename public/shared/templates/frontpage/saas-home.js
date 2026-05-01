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
 * @fileoverview SaaS landing page template.
 *
 * @description High-converting layout for software products.
 * Includes hero, trust logos, features, stepper, pricing, testimonials, FAQ, and CTA.
 *
 * Attributes:
 *   - title: Hero headline
 *   - labels: JSON object to override i18n strings
 *   - features: Array of feature objects
 *   - steps: Array of step objects
 *   - pricingPlans: Array of pricing plan objects
 *   - testimonials: Array of testimonial objects
 *   - faqs: Array of FAQ objects
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - hero-media: Product screenshot or demo video
 *   - footer: Page footer
 */
export class BuiltinTplFrontpageSaas extends BuiltinBaseElement {
  static properties = {
    title: { type: String },
    labels: { type: Object, converter: jsonConverter },
        features: { type: Array, converter: jsonConverter },
    steps: { type: Array, converter: jsonConverter },
    pricingPlans: { type: Array, converter: jsonConverter },
    testimonials: { type: Array, converter: jsonConverter },
    faqs: { type: Array, converter: jsonConverter },
  };

  static styles = css`
    :host { display: block; line-height: 1.55; }
    h1, h2, h3, p { margin: 0; }
    a { color: var(--builtin-primary, #2563eb); text-decoration: none; }
    .container { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
    .hero {
      padding: 70px 0 50px;
      text-align: center;
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .hero h1 {
      font-size: clamp(26px, 4.5vw, 44px);
      font-weight: 800;
      margin-bottom: 14px;
      letter-spacing: -0.02em;
      color: var(--builtin-color-text, #111827);
    }
    .hero p {
      font-size: clamp(15px, 2vw, 18px);
      color: var(--builtin-color-muted, #6b7280);
      max-width: 600px;
      margin: 0 auto 24px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 22px;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      font-weight: 600;
      cursor: pointer;
      font: inherit;
    }
    .btn:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .btn-primary {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .btn-primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .hero-media {
      margin-top: 32px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      min-height: 260px;
      background: var(--builtin-surface, #ffffff);
      display: grid;
      place-items: center;
      color: var(--builtin-color-muted, #6b7280);
    }
    .trust {
      padding: 28px 0;
      text-align: center;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .trust p { font-size: 13px; color: var(--builtin-color-muted, #6b7280); margin-bottom: 14px; }
    .logos {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 28px;
      flex-wrap: wrap;
    }
    .logo {
      width: 90px;
      height: 28px;
      background: var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
    }
    .features { padding: 56px 0; }
    .section-title { text-align: center; font-size: 26px; font-weight: 700; margin-bottom: 32px; color: var(--builtin-color-text, #111827); }
    .feature-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 22px;
    }
    .feature-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 24px;
      background: var(--builtin-surface, #ffffff);
      transition: background .15s ease;
    }
    .feature-card:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .feature-card h3 { font-size: 16px; margin-bottom: 6px; color: var(--builtin-color-text, #111827); }
    .feature-card p { color: var(--builtin-color-muted, #6b7280); font-size: 14px; }
    .steps {
      padding: 56px 0;
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .stepper { display: flex; gap: 16px; }
    .step {
      flex: 1;
      text-align: center;
      padding: 24px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      transition: background .15s ease;
    }
    .step:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .step-num {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      display: grid;
      place-items: center;
      font-weight: 700;
      margin: 0 auto 12px;
    }
    .step h3 { font-size: 16px; margin-bottom: 6px; color: var(--builtin-color-text, #111827); }
    .step p { font-size: 14px; color: var(--builtin-color-muted, #6b7280); }
    .pricing { padding: 56px 0; }
    .pricing-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 18px;
    }
    .pricing-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 26px;
      text-align: center;
      background: var(--builtin-surface, #ffffff);
      transition: background .15s ease;
    }
    .pricing-card:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .pricing-card h3 { font-size: 18px; margin-bottom: 6px; color: var(--builtin-color-text, #111827); }
    .pricing-card .price {
      font-size: 30px;
      font-weight: 800;
      margin: 10px 0;
      color: var(--builtin-primary, #2563eb);
    }
    .pricing-card ul { list-style: none; padding: 0; margin: 14px 0; text-align: left; }
    .pricing-card li {
      padding: 6px 0;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 14px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .pricing-card li svg { width: 16px; height: 16px; flex-shrink: 0; color: var(--builtin-primary, #2563eb); }
    .testimonials {
      padding: 56px 0;
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .testi-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 20px;
    }
    .testi-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 22px;
      background: var(--builtin-surface, #ffffff);
      transition: background .15s ease;
    }
    .testi-card:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .testi-card blockquote { font-style: italic; margin-bottom: 12px; color: var(--builtin-color-text, #111827); }
    .testi-card cite { font-size: 13px; color: var(--builtin-color-muted, #6b7280); }
    .faq { padding: 56px 0; }
    .faq details {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      padding: 14px 18px;
      background: var(--builtin-surface, #ffffff);
      margin-bottom: 10px;
      transition: background .15s ease;
    }
    .faq details:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .faq details summary {
      font-weight: 600;
      cursor: pointer;
      list-style: none;
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: var(--builtin-color-text, #111827);
    }
    .faq details summary::after {
      content: "+";
      font-size: 18px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .faq details[open] summary::after { content: "?"; }
    .faq details p { margin-top: 10px; font-size: 14px; color: var(--builtin-color-muted, #6b7280); }
    .cta { padding: 60px 0; text-align: center; }
    .cta h2 { font-size: 28px; margin-bottom: 10px; color: var(--builtin-color-text, #111827); }
    .cta p { color: var(--builtin-color-muted, #6b7280); margin-bottom: 20px; }
    .page-footer {
      padding: 24px 0;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }

    @media (max-width: 720px) {
      .container { padding: 0 16px; }
      .hero { padding: 44px 0 32px; }
      .hero-media { min-height: 180px; }
      .feature-grid { grid-template-columns: 1fr; }
      .stepper { flex-direction: column; }
      .pricing-grid { grid-template-columns: 1fr; }
      .testi-grid { grid-template-columns: 1fr; }
      .btn { width: 100%; min-height: 44px; }
    }
  `;

  _defaultFeatures() {
    return [
      { title: this._l("feature.0.title", "Real-time Sync"), desc: this._l("feature.0.desc", "Collaborate with your team instantly across devices.") },
      { title: this._l("feature.1.title", "Advanced Analytics"), desc: this._l("feature.1.desc", "Insights and dashboards to drive smarter decisions.") },
      { title: this._l("feature.2.title", "Secure API"), desc: this._l("feature.2.desc", "Enterprise-grade endpoints with fine-grained permissions.") },
      { title: this._l("feature.3.title", "Integrations"), desc: this._l("feature.3.desc", "Connect with the tools you already use every day.") },
      { title: this._l("feature.4.title", "Automations"), desc: this._l("feature.4.desc", "Save hours by automating repetitive workflows.") },
      { title: this._l("feature.5.title", "24/7 Support"), desc: this._l("feature.5.desc", "Our team is here to help you succeed at any hour.") },
    ];
  }

  _defaultSteps() {
    return [
      { num: "1", title: this._l("step.0.title", "Connect"), desc: this._l("step.0.desc", "Link your data sources in minutes.") },
      { num: "2", title: this._l("step.1.title", "Configure"), desc: this._l("step.1.desc", "Set up rules and customize your workspace.") },
      { num: "3", title: this._l("step.2.title", "Launch"), desc: this._l("step.2.desc", "Go live and start seeing results immediately.") },
    ];
  }

  _defaultPricingPlans() {
    return [
      { name: this._l("plan.starter.name", "Starter"), price: this._l("plan.starter.price", "$0/mo"), cta: this._l("plan.starter.cta", "Get Started"), action: "plan-starter", primary: false, features: [this._l("plan.starter.feature1", "1 project"), this._l("plan.starter.feature2", "Basic features"), this._l("plan.starter.feature3", "Community support")] },
      { name: this._l("plan.pro.name", "Pro"), price: this._l("plan.pro.price", "$39/mo"), cta: this._l("plan.pro.cta", "Get Started"), action: "plan-pro", primary: true, features: [this._l("plan.pro.feature1", "10 projects"), this._l("plan.pro.feature2", "Advanced features"), this._l("plan.pro.feature3", "Priority support")] },
      { name: this._l("plan.enterprise.name", "Enterprise"), price: this._l("plan.enterprise.price", "Custom"), cta: this._l("plan.enterprise.cta", "Contact Sales"), action: "plan-enterprise", primary: false, features: [this._l("plan.enterprise.feature1", "Unlimited projects"), this._l("plan.enterprise.feature2", "Dedicated support"), this._l("plan.enterprise.feature3", "Custom SLA")] },
    ];
  }

  _defaultTestimonials() {
    return [
      { quote: this._l("testimonial.0.quote", "The best investment we made this year. Onboarding was a breeze."), author: this._l("testimonial.0.author", "Alex R., Head of Engineering") },
      { quote: this._l("testimonial.1.quote", "Our team productivity increased by 40% within the first month."), author: this._l("testimonial.1.author", "Sarah K., Product Lead") },
    ];
  }

  _defaultFaqs() {
    return [
      { q: this._l("faq.0.q", "Can I change plans later?"), a: this._l("faq.0.a", "Yes, you can upgrade or downgrade at any time from your billing settings.") },
      { q: this._l("faq.1.q", "Is there a free trial?"), a: this._l("faq.1.a", "We offer a 14-day free trial with full access to Pro features.") },
      { q: this._l("faq.2.q", "Do you offer refunds?"), a: this._l("faq.2.a", "Yes, within 30 days of purchase if you are not satisfied.") },
      { q: this._l("faq.3.q", "How do I get support?"), a: this._l("faq.3.a", "Reach out via email or chat. Pro and Enterprise plans get priority support.") },
    ];
  }

  _dispatchCta(action) {
    this.dispatchEvent(new CustomEvent("builtin-cta-click", {
      bubbles: true,
      composed: true,
      detail: { action },
    }));
  }

  render() {
    const title = this.title || this._l("hero.title", "Ship faster with our platform");

    const features = this.features ?? (this._defaultFeatures());
    const steps = this.steps ?? (this._defaultSteps());
    const pricing = this.pricingPlans ?? (this._defaultPricingPlans());
    const testimonials = this.testimonials ?? (this._defaultTestimonials());
    const faqs = this.faqs ?? (this._defaultFaqs());

    return html`
      <slot name="navbar"><builtin-navbar></builtin-navbar></slot>

      <section class="hero">
        <div class="container">
          <h1>${title}</h1>
          <p>${this._l("hero.desc", "Everything you need to build, launch, and scale in one place.")}</p>
          <div>
            <button class="btn btn-primary" @click=${() => this._dispatchCta("start-trial")}>${this._l("hero.ctaPrimary", "Start Free Trial")}</button>
            <button class="btn" style="margin-left:10px;" @click=${() => this._dispatchCta("view-demo")}>${this._l("hero.ctaSecondary", "View Demo")}</button>
          </div>
          <slot name="hero-media">
            <div class="hero-media">${this._l("hero.mediaPlaceholder", "Product screenshot / demo")}</div>
          </slot>
        </div>
      </section>

      <section class="trust">
        <div class="container">
          <p>${this._l("trust.label", "Trusted by teams at")}</p>
          <div class="logos">
            <div class="logo"></div>
            <div class="logo"></div>
            <div class="logo"></div>
            <div class="logo"></div>
            <div class="logo"></div>
          </div>
        </div>
      </section>

      <section class="features">
        <div class="container">
          <h2 class="section-title">${this._l("features.title", "Powerful Features")}</h2>
          <div class="feature-grid">
            ${repeat(features, (f, i) => i, (f) => html`
              <div class="feature-card">
                <h3>${f.title}</h3>
                <p>${f.desc}</p>
              </div>
            `)}
          </div>
        </div>
      </section>

      <section class="steps">
        <div class="container">
          <h2 class="section-title">${this._l("steps.title", "How it Works")}</h2>
          <div class="stepper">
            ${repeat(steps, (s, i) => i, (s) => html`
              <div class="step">
                <div class="step-num">${s.num}</div>
                <h3>${s.title}</h3>
                <p>${s.desc}</p>
              </div>
            `)}
          </div>
        </div>
      </section>

      <section class="pricing">
        <div class="container">
          <h2 class="section-title">${this._l("pricing.title", "Pricing")}</h2>
          <div class="pricing-grid">
            ${repeat(pricing, (p, i) => i, (p) => html`
              <div class="pricing-card">
                <h3>${p.name}</h3>
                <div class="price">${p.price}</div>
                <ul>
                  ${repeat(p.features, (f) => f, (f) => html`
                    <li>
                      <builtin-icon name="check" size="16" variant="outlined"></builtin-icon>
                      ${f}
                    </li>
                  `)}
                </ul>
                <button class="btn ${p.primary ? 'btn-primary' : ''}" @click=${() => this._dispatchCta(p.action || "pricing-cta")}>${p.cta}</button>
              </div>
            `)}
          </div>
        </div>
      </section>

      <section class="testimonials">
        <div class="container">
          <h2 class="section-title">${this._l("testimonials.title", "What Customers Say")}</h2>
          <div class="testi-grid">
            ${repeat(testimonials, (t, i) => i, (t) => html`
              <div class="testi-card">
                <blockquote>"${t.quote}"</blockquote>
                <cite>— ${t.author}</cite>
              </div>
            `)}
          </div>
        </div>
      </section>

      <section class="faq">
        <div class="container">
          <h2 class="section-title">${this._l("faq.title", "FAQ")}</h2>
          <div>
            ${repeat(faqs, (f, i) => i, (f) => html`
              <details>
                <summary>${f.q}</summary>
                <p>${f.a}</p>
              </details>
            `)}
          </div>
        </div>
      </section>

      <section class="cta">
        <div class="container">
          <h2>${this._l("cta.title", "Ready to get started?")}</h2>
          <p>${this._l("cta.desc", "Join thousands of teams shipping faster every day.")}</p>
          <button class="btn btn-primary" @click=${() => this._dispatchCta("start-trial")}>${this._l("cta.button", "Start Free Trial")}</button>
        </div>
      </section>

      <slot name="footer"><builtin-footer></builtin-footer></slot>
    `;
  }
}