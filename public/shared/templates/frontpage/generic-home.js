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
 * @fileoverview Generic business/product homepage template.
 *
 * @description Standard frontpage layout suitable for most businesses and products.
 * Includes a hero section, feature grid, testimonial, pricing teaser, and newsletter.
 *
 * Attributes:
 *   - title: Main hero heading
 *   - subtitle: Hero subheading
 *   - labels: JSON object to override i18n strings
 *
 * Slots:
 *   - navbar: Top navigation bar (replaces default `<builtin-navbar>`)
 *   - hero-cta: Custom hero call-to-action content
 *   - features: Custom feature section content
 *   - testimonial: Custom testimonial content
 *   - pricing: Custom pricing section content
 *   - newsletter: Custom newsletter content
 *   - footer: Page footer (replaces default `<builtin-footer>`)
 */
export class BuiltinTplFrontpageGeneric extends BuiltinBaseElement {
  static properties = {
    title: { type: String },
    subtitle: { type: String },
        features: { type: Array, converter: jsonConverter },
    testimonial: { type: Object, converter: jsonConverter },
    pricingPlans: { type: Array, attribute: "pricing-plans", converter: jsonConverter },
    newsletter: { type: Object, converter: jsonConverter },
    labels: { type: Object, converter: jsonConverter },
  };

  static styles = css`
    :host { display: block; line-height: 1.55; }
    h1, h2, h3, p { margin: 0; }
    a { color: var(--builtin-primary, #2563eb); text-decoration: none; }
    .container { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
    .hero {
      padding: 80px 0 60px;
      text-align: center;
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .hero h1 {
      font-size: clamp(28px, 5vw, 48px);
      font-weight: 800;
      margin-bottom: 16px;
      letter-spacing: -0.02em;
      color: var(--builtin-color-text, #111827);
    }
    .hero p {
      font-size: clamp(16px, 2.2vw, 20px);
      color: var(--builtin-color-muted, #6b7280);
      max-width: 640px;
      margin: 0 auto 28px;
    }
    .hero-actions {
      display: inline-flex;
      gap: 12px;
      flex-wrap: wrap;
      justify-content: center;
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
    .features { padding: 60px 0; }
    .section-title { text-align: center; font-size: 28px; font-weight: 700; margin-bottom: 36px; color: var(--builtin-color-text, #111827); }
    .feature-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 24px;
    }
    .feature-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 28px;
      background: var(--builtin-surface, #ffffff);
      transition: background .15s ease;
    }
    .feature-card:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .feature-icon { width: 32px; height: 32px; margin-bottom: 12px; color: var(--builtin-primary, #2563eb); }
    .feature-card h3 { font-size: 18px; margin-bottom: 8px; color: var(--builtin-color-text, #111827); }
    .feature-card p { color: var(--builtin-color-muted, #6b7280); font-size: 14px; }
    .testimonial {
      padding: 60px 0;
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .testimonial-card { max-width: 720px; margin: 0 auto; text-align: center; }
    .testimonial-card blockquote {
      font-size: 20px;
      font-style: italic;
      color: var(--builtin-color-text, #111827);
      margin-bottom: 16px;
    }
    .testimonial-card cite { color: var(--builtin-color-muted, #6b7280); font-size: 14px; }
    .pricing { padding: 60px 0; }
    .pricing-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 20px;
    }
    .pricing-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 28px;
      text-align: center;
      background: var(--builtin-surface, #ffffff);
      transition: background .15s ease;
    }
    .pricing-card:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .pricing-card h3 { font-size: 20px; margin-bottom: 6px; color: var(--builtin-color-text, #111827); }
    .pricing-card .price {
      font-size: 32px;
      font-weight: 800;
      margin: 12px 0;
      color: var(--builtin-primary, #2563eb);
    }
    .pricing-card ul { list-style: none; padding: 0; margin: 16px 0; text-align: left; }
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
    .newsletter {
      padding: 60px 0;
      text-align: center;
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .newsletter h2 { font-size: 24px; margin-bottom: 10px; color: var(--builtin-color-text, #111827); }
    .newsletter p { color: var(--builtin-color-muted, #6b7280); margin-bottom: 20px; }
    .newsletter-form {
      display: inline-flex;
      gap: 10px;
      max-width: 480px;
      width: 100%;
    }
    .newsletter-form input {
      flex: 1 1 auto;
      min-height: 42px;
      padding: 0 14px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      font: inherit;
    }
    .newsletter-form button {
      min-height: 42px;
      padding: 0 20px;
      border-radius: var(--builtin-radius, 6px);
      font-weight: 600;
      cursor: pointer;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      border: 1px solid var(--builtin-primary, #2563eb);
      font: inherit;
    }
    .newsletter-form button:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .page-footer {
      padding: 30px 0;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .logos-strip {
      padding: 32px 0;
      background: var(--builtin-surface, #ffffff);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .logos-strip .label {
      text-align: center;
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--builtin-color-muted, #9ca3af);
      margin-bottom: 16px;
    }
    .logos-row {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      align-items: center;
      gap: 36px;
      opacity: 0.75;
    }
    .logos-row .logo {
      font-weight: 700;
      font-size: 18px;
      color: var(--builtin-color-text, #111827);
      letter-spacing: -0.02em;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .logos-row .logo .dot {
      width: 10px;
      height: 10px;
      border-radius: 3px;
      background: var(--builtin-primary, #2563eb);
      display: inline-block;
    }
    .stats {
      padding: 60px 0;
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 20px;
      text-align: center;
    }
    .stat-num {
      font-size: 36px;
      font-weight: 800;
      color: var(--builtin-primary, #2563eb);
      letter-spacing: -0.02em;
    }
    .stat-label {
      font-size: 13px;
      color: var(--builtin-color-muted, #6b7280);
      margin-top: 4px;
    }
    .cta-band {
      padding: 56px 0;
      text-align: center;
      background: linear-gradient(135deg, var(--builtin-primary, #2563eb), var(--builtin-primary-hover, #1d4ed8));
      color: #fff;
    }
    .cta-band h2 {
      font-size: 28px;
      margin-bottom: 10px;
      color: #fff;
    }
    .cta-band p {
      color: rgba(255,255,255,0.85);
      max-width: 540px;
      margin: 0 auto 22px;
    }
    .cta-band .btn {
      background: #fff;
      color: var(--builtin-primary, #2563eb);
      border-color: #fff;
    }
    .cta-band .btn:hover { background: #f3f4f6; }

    @media (max-width: 720px) {
      .container { padding: 0 16px; }
      .hero { padding: 48px 0 36px; }
      .hero-actions { width: 100%; flex-direction: column; }
      .hero-actions .btn { width: 100%; min-height: 44px; }
      .feature-grid { grid-template-columns: 1fr; }
      .pricing-grid { grid-template-columns: 1fr; }
      .newsletter-form { flex-direction: column; }
      .newsletter-form input, .newsletter-form button { width: 100%; min-height: 44px; }
      .stats-grid { grid-template-columns: repeat(2, 1fr); }
      .logos-row { gap: 20px; }
    }
  `;

  constructor() {
    super();
    this.features = [];
    this.testimonial = undefined;
    this.pricingPlans = [];
    this.newsletter = undefined;
  }

  _hasSlot(name) {
    return Array.from(this.children || []).some((node) => node.slot === name);
  }

  _defaultFeatures() {
    return [
      {
        icon: "thunderbolt",
        title: this._l("feature.fastPerformance.title", "Fast Performance"),
        description: this._l("feature.fastPerformance.desc", "Optimized for speed with minimal overhead and efficient rendering."),
      },
      {
        icon: "safety-certificate",
        title: this._l("feature.secureByDefault.title", "Secure by Default"),
        description: this._l("feature.secureByDefault.desc", "Enterprise-grade security built into every layer of the stack."),
      },
      {
        icon: "link",
        title: this._l("feature.easyIntegration.title", "Easy Integration"),
        description: this._l("feature.easyIntegration.desc", "Drop-in components that work seamlessly with your existing workflow."),
      },
      {
        icon: "customer-service",
        title: this._l("feature.support24_7.title", "24/7 Support"),
        description: this._l("feature.support24_7.desc", "Our team is here around the clock to help you succeed."),
      },
    ];
  }

  _defaultTestimonial() {
    return {
      quote: this._l("testimonial.quote", "This platform transformed how we build and ship products. Highly recommended!"),
      author: this._l("testimonial.author", "Jane Doe, CTO at Acme Corp"),
    };
  }

  _defaultPricingPlans() {
    return [
      {
        name: this._l("plan.starter.name", "Starter"),
        price: this._l("plan.starter.price", "$9/mo"),
        features: [
          this._l("plan.starter.feature1", "1 project"),
          this._l("plan.starter.feature2", "Basic analytics"),
          this._l("plan.starter.feature3", "Community support"),
        ],
        cta: this._l("plan.starter.cta", "Choose Starter"),
      },
      {
        name: this._l("plan.pro.name", "Pro"),
        price: this._l("plan.pro.price", "$29/mo"),
        features: [
          this._l("plan.pro.feature1", "10 projects"),
          this._l("plan.pro.feature2", "Advanced analytics"),
          this._l("plan.pro.feature3", "Priority support"),
        ],
        cta: this._l("plan.pro.cta", "Choose Pro"),
        primary: true,
      },
      {
        name: this._l("plan.enterprise.name", "Enterprise"),
        price: this._l("plan.enterprise.price", "Custom"),
        features: [
          this._l("plan.enterprise.feature1", "Unlimited projects"),
          this._l("plan.enterprise.feature2", "Dedicated support"),
          this._l("plan.enterprise.feature3", "SLA guarantee"),
        ],
        cta: this._l("plan.enterprise.cta", "Contact Sales"),
      },
    ];
  }

  _defaultNewsletter() {
    return {
      title: this._l("newsletter.title", "Stay in the loop"),
      description: this._l("newsletter.desc", "Get the latest updates and tips delivered to your inbox."),
      placeholder: this._l("newsletter.placeholder", "you@example.com"),
      buttonLabel: this._l("newsletter.button", "Subscribe"),
    };
  }

  _dispatch_cta_click(action, detail = {}) {
    this.dispatchEvent(new CustomEvent("builtin-cta-click", {
      detail: { action, ...detail },
      bubbles: true,
      composed: true,
    }));
  }

  _handle_subscribe(e) {
    e.preventDefault();
    const input = e.target.querySelector('input[type="email"]');
    const email = input?.value?.trim() || "";
    this.dispatchEvent(new CustomEvent("builtin-subscribe", {
      detail: { email },
      bubbles: true,
      composed: true,
    }));
  }

  _renderFeatureCard(feature) {
    return html`
      <div class="feature-card">
        <builtin-icon name="${feature.icon || "appstore"}" size="32" variant="outlined"></builtin-icon>
        <h3>${feature.title || ""}</h3>
        <p>${feature.description || ""}</p>
      </div>
    `;
  }

  _renderPricingCard(plan) {
    return html`
      <div class="pricing-card">
        <h3>${plan.name || ""}</h3>
        <div class="price">${plan.price || ""}</div>
        <ul>
          ${(plan.features || []).map((feature) => html`
            <li><builtin-icon name="check" size="16" variant="outlined"></builtin-icon>${feature}</li>
          `)}
        </ul>
        <button class="btn ${plan.primary ? "btn-primary" : ""}" @click=${() => this._dispatch_cta_click("choose-plan", { plan: plan.name })}>${plan.cta || this._l("cta.learnMore", "Learn More")}</button>
      </div>
    `;
  }

  render() {
    const title = this.title || this._l("hero.title", "Build Something Amazing");
    const subtitle = this.subtitle || this._l("hero.subtitle", "The all-in-one platform to launch, grow, and manage your business.");
    const features = Array.isArray(this.features) && this.features.length ? this.features : (this._defaultFeatures());
    const testimonial = this.testimonial || (this._defaultTestimonial());
    const pricingPlans = Array.isArray(this.pricingPlans) && this.pricingPlans.length ? this.pricingPlans : (this._defaultPricingPlans());
    const newsletter = this.newsletter || (this._defaultNewsletter());
    const showFeatures = this._hasSlot("features") || features.length > 0;
    const showTestimonial = this._hasSlot("testimonial") || !!testimonial;
    const showPricing = this._hasSlot("pricing") || pricingPlans.length > 0;
    const showNewsletter = this._hasSlot("newsletter") || !!newsletter;

    return html`
      <slot name="navbar"><builtin-navbar></builtin-navbar></slot>

      <section class="hero">
        <div class="container">
          <h1>${title}</h1>
          <p>${subtitle}</p>
          <slot name="hero-cta">
            <div class="hero-actions">
              <button class="btn btn-primary" @click=${() => this._dispatch_cta_click("get-started")}>${this._l("cta.getStarted", "Get Started")}</button>
              <button class="btn" @click=${() => this._dispatch_cta_click("view-demo")}>${this._l("cta.viewDemo", "View Demo")}</button>
            </div>
          </slot>
        </div>
      </section>

      ${html`
        <section class="logos-strip">
          <div class="container">
            <div class="label">${this._l("logos.label", "Trusted by teams at")}</div>
            <div class="logos-row">
              <span class="logo"><span class="dot"></span>Acme</span>
              <span class="logo"><span class="dot" style="background:#10b981"></span>Globex</span>
              <span class="logo"><span class="dot" style="background:#f59e0b"></span>Initech</span>
              <span class="logo"><span class="dot" style="background:#ec4899"></span>Umbrella</span>
              <span class="logo"><span class="dot" style="background:#8b5cf6"></span>Hooli</span>
              <span class="logo"><span class="dot" style="background:#06b6d4"></span>Vehement</span>
            </div>
          </div>
        </section>
      `}

      ${showFeatures ? html`
        <section class="features">
          <div class="container">
            <h2 class="section-title">${this._l("features.title", "Why Choose Us")}</h2>
            <slot name="features">
              <div class="feature-grid">
                ${features.map((feature) => this._renderFeatureCard(feature))}
              </div>
            </slot>
          </div>
        </section>
      ` : nothing}

      ${showTestimonial ? html`
        <section class="testimonial">
          <div class="container">
            <slot name="testimonial">
              <div class="testimonial-card">
                <blockquote>"${testimonial?.quote || ""}"</blockquote>
                <cite>\u2014 ${testimonial?.author || ""}</cite>
              </div>
            </slot>
          </div>
        </section>
      ` : nothing}

      ${html`
        <section class="stats">
          <div class="container">
            <div class="stats-grid">
              <div><div class="stat-num">120k+</div><div class="stat-label">${this._l("stats.users", "Active users")}</div></div>
              <div><div class="stat-num">99.99%</div><div class="stat-label">${this._l("stats.uptime", "Service uptime")}</div></div>
              <div><div class="stat-num">42</div><div class="stat-label">${this._l("stats.countries", "Countries served")}</div></div>
              <div><div class="stat-num">4.9\u2605</div><div class="stat-label">${this._l("stats.rating", "Average rating")}</div></div>
            </div>
          </div>
        </section>
      `}

      ${showPricing ? html`
        <section class="pricing">
          <div class="container">
            <h2 class="section-title">${this._l("pricing.title", "Simple Pricing")}</h2>
            <slot name="pricing">
              <div class="pricing-grid">
                ${pricingPlans.map((plan) => this._renderPricingCard(plan))}
              </div>
            </slot>
          </div>
        </section>
      ` : nothing}

      ${showNewsletter ? html`
        <section class="newsletter">
          <div class="container">
            <slot name="newsletter">
              <h2>${newsletter?.title || ""}</h2>
              <p>${newsletter?.description || ""}</p>
              <form class="newsletter-form" @submit=${(e) => this._handle_subscribe(e)}>
                <input type="email" placeholder="${newsletter?.placeholder || ""}" aria-label="${this._l("newsletter.emailLabel", "Email address")}" />
                <button type="submit">${newsletter?.buttonLabel || ""}</button>
              </form>
            </slot>
          </div>
        </section>
      ` : nothing}

      ${html`
        <section class="cta-band">
          <div class="container">
            <h2>${this._l("finalCta.title", "Ready to get started?")}</h2>
            <p>${this._l("finalCta.desc", "Join thousands of teams already shipping faster with our platform.")}</p>
            <button class="btn" @click=${() => this._dispatch_cta_click("get-started")}>${this._l("finalCta.button", "Start your free trial")}</button>
          </div>
        </section>
      `}

      <slot name="footer"><builtin-footer></builtin-footer></slot>
    `;
  }
}