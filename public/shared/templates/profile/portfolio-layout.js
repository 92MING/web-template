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
 * @fileoverview Creative portfolio / resume page template.
 *
 * @description A single-page portfolio layout with navbar, hero, about, skills,
 * experience, project grid, contact form, and footer. Great for designers, developers, and creatives.
 *
 * Attributes:
 *   - name: Person or brand name (default: "Alex Morgan")
 *   - title: Job title / tagline (default: "Designer & Developer")
 *   - avatar: Avatar image URL
 *   - bio: About paragraph
 *   - projects: JSON array of projects [{ title, category, desc }]
 *   - skills: JSON array of skill strings
 *   - experiences: JSON array of experiences [{ role, company, period }]
 *   - contact-form: Show contact form (default: true)
 *   - labels: JSON object to override i18n strings
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - projects: Custom project grid content
 *   - contact: Custom contact section content
 *   - footer: Page footer
 *
 * Events:
 *   - builtin-project-click: Fired when a project card is clicked. Detail: { title }
 *   - builtin-skill-click: Fired when a skill tag is clicked. Detail: { skill }
 *   - builtin-contact-submit: Fired when the contact form is submitted. Detail: { name, email, message }
 *
 * Usage example:
 *   ```html
 *   <builtin-tpl-profile-portfolio name="Alex Morgan" title="Full-stack builder.">
 *     <builtin-navbar slot="navbar"></builtin-navbar>
 *     <div slot="projects">...</div>
 *     <div slot="contact">...</div>
 *     <div slot="footer">...</div>
 *   </builtin-tpl-profile-portfolio>
 *   ```
 */
export class BuiltinTplProfilePortfolio extends BuiltinBaseElement {
  static properties = {
    name: { type: String },
    title: { type: String },
    avatar: { type: String },
    bio: { type: String },
    projects: { type: Array, converter: jsonConverter },
    skills: { type: Array, converter: jsonConverter },
    experiences: { type: Array, converter: jsonConverter },
    contactForm: { type: Boolean, attribute: "contact-form" },
        labels: { type: Object, converter: jsonConverter },
  };

  static styles = css`
    :host {
      display: block;
      font-family: inherit;
      color: var(--builtin-color-text, #111827);
      background: var(--builtin-surface, #ffffff);
      line-height: 1.55;
    }
    h1, h2, h3, h4, p { margin: 0; }
    a { color: var(--builtin-primary, #2563eb); text-decoration: none; }
    .container { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
    .navbar {
      padding: 16px 0;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .navbar .container {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .navbar .brand { font-weight: 800; font-size: 18px; }
    .navbar nav { display: flex; gap: 18px; font-size: 14px; }
    .hero {
      padding: 80px 0 60px;
      text-align: center;
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .hero-avatar {
      width: 96px;
      height: 96px;
      border-radius: 50%;
      margin: 0 auto 16px;
      object-fit: cover;
      background: var(--builtin-header-bg, #f9fafb);
      border: 3px solid var(--builtin-surface, #ffffff);
    }
    .hero h1 { font-size: 42px; font-weight: 800; margin-bottom: 10px; }
    .hero p { font-size: 18px; color: var(--builtin-color-muted, #6b7280); }
    .section { padding: 60px 0; }
    .section-title {
      font-size: 22px;
      font-weight: 700;
      margin-bottom: 24px;
      text-align: center;
    }
    .about-text {
      max-width: 640px;
      margin: 0 auto;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 15px;
    }
    .skills {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 10px;
      max-width: 640px;
      margin: 0 auto;
    }
    .skill {
      padding: 6px 14px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      font-size: 13px;
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
    }
    .skill:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .experience-list {
      max-width: 640px;
      margin: 0 auto;
      display: grid;
      gap: 16px;
    }
    .experience-item {
      padding: 16px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
    }
    .experience-item .company { font-weight: 700; font-size: 15px; }
    .experience-item .role { font-size: 13px; color: var(--builtin-color-muted, #6b7280); margin: 2px 0; }
    .experience-item .period { font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .experience-item .desc { font-size: 14px; color: var(--builtin-color-text, #111827); margin-top: 8px; }
    .project-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 24px;
    }
    .project-card {
      position: relative;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      background: var(--builtin-surface, #ffffff);
      min-height: 220px;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      cursor: pointer;
    }
    .project-card .overlay {
      position: absolute;
      inset: 0;
      background: rgba(0,0,0,0.55);
      color: #fff;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      text-align: center;
      padding: 20px;
      opacity: 0;
      transition: opacity .2s ease;
    }
    .project-card:hover .overlay { opacity: 1; }
    .project-card .thumb {
      flex: 1 1 auto;
      background: var(--builtin-header-bg, #f9fafb);
    }
    .project-card .body {
      padding: 16px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .project-card h3 { font-size: 16px; margin-bottom: 4px; }
    .project-card .category {
      font-size: 12px;
      color: var(--builtin-primary, #2563eb);
      margin-bottom: 4px;
    }
    .project-card p { font-size: 13px; color: var(--builtin-color-muted, #6b7280); }
    .contact-form {
      max-width: 520px;
      margin: 0 auto;
      display: grid;
      gap: 14px;
    }
    .contact-form input,
    .contact-form textarea {
      width: 100%;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      font: inherit;
      padding: 10px 12px;
    }
    .contact-form textarea { min-height: 120px; resize: vertical; }
    .contact-form button {
      justify-self: start;
      padding: 10px 22px;
      border-radius: var(--builtin-radius, 6px);
      font-weight: 600;
      cursor: pointer;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      border: 1px solid var(--builtin-primary, #2563eb);
      font: inherit;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .contact-form button:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .page-footer {
      padding: 24px 0;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .icon { width: 18px; height: 18px; vertical-align: middle; }

    @media (max-width: 720px) {
      .container { padding: 0 16px; }
      .hero { padding: 48px 0 40px; }
      .hero h1 { font-size: 28px; }
      .hero p { font-size: 16px; }
      .section { padding: 40px 0; }
      .project-grid { grid-template-columns: 1fr; }
      .contact-form button { width: 100%; justify-self: stretch; }
      .navbar .container { flex-direction: column; gap: 10px; align-items: flex-start; }
    }
  `;

  constructor() {
    super();
    this.contactForm = true;
  }

  _defaultProjects() {
    return [
      { title: this._l("project.alpha", "Project Alpha"), category: this._l("project.alphaCategory", "SaaS"), desc: this._l("project.alphaDesc", "A modern SaaS dashboard.") },
      { title: this._l("project.beta", "Project Beta"), category: this._l("project.betaCategory", "E-commerce"), desc: this._l("project.betaDesc", "E-commerce storefront.") },
      { title: this._l("project.gamma", "Project Gamma"), category: this._l("project.gammaCategory", "Landing Page"), desc: this._l("project.gammaDesc", "Mobile-first landing page.") },
      { title: this._l("project.delta", "Project Delta"), category: this._l("project.deltaCategory", "Real-time"), desc: this._l("project.deltaDesc", "Real-time chat application.") },
    ];
  }

  _defaultSkills() {
    return [
      "HTML", "CSS", "JavaScript", "React", "Node.js", "UI Design"
    ];
  }

  _defaultExperiences() {
    return [
      { role: this._l("experience.role1", "Senior Developer"), company: this._l("experience.company1", "Tech Corp"), period: this._l("experience.period1", "2021 - Present") },
      { role: this._l("experience.role2", "UI Designer"), company: this._l("experience.company2", "Creative Studio"), period: this._l("experience.period2", "2018 - 2021") },
      { role: this._l("experience.role3", "Frontend Intern"), company: this._l("experience.company3", "StartUp Inc"), period: this._l("experience.period3", "2016 - 2018") },
    ];
  }

  _onProjectClick(project) {
    this.dispatchEvent(new CustomEvent("builtin-project-click", {
      detail: { title: project.title },
      bubbles: true,
      composed: true,
    }));
  }

  _onSkillClick(skill) {
    this.dispatchEvent(new CustomEvent("builtin-skill-click", {
      detail: { skill },
      bubbles: true,
      composed: true,
    }));
  }

  _onContactSubmit(e) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const data = {
      name: fd.get("name") || "",
      email: fd.get("email") || "",
      message: fd.get("message") || "",
    };
    this.dispatchEvent(new CustomEvent("builtin-contact-submit", {
      detail: data,
      bubbles: true,
      composed: true,
    }));
  }

  render() {
    const name = this.name || this._l("portfolio.name", "Alex Morgan");
    const title = this.title || this._l("portfolio.title", "Designer & Developer");
    const bio = this.bio || this._l("portfolio.bio", "I craft accessible, performant web experiences with a focus on clean design and solid engineering.");
    const skills = this.skills ?? (this._defaultSkills());
    const projects = this.projects ?? (this._defaultProjects());
    const experiences = this.experiences ?? (this._defaultExperiences());

    return html`
      <slot name="navbar">
        <header class="navbar">
          <div class="container">
            <div class="brand">${name}</div>
            <nav>
              <a href="#about">${this._l("nav.about", "About")}</a>
              <a href="#skills">${this._l("nav.skills", "Skills")}</a>
              ${experiences.length > 0 ? html`<a href="#experience">${this._l("nav.experience", "Experience")}</a>` : nothing}
              <a href="#projects">${this._l("nav.projects", "Projects")}</a>
              ${this.contactForm ? html`<a href="#contact">${this._l("nav.contact", "Contact")}</a>` : nothing}
            </nav>
          </div>
        </header>
      </slot>

      <section class="hero">
        <div class="container">
          ${this.avatar ? html`<img class="hero-avatar" src="${this.avatar}" alt="${name}" />` : nothing}
          <h1>${name}</h1>
          <p>${title}</p>
        </div>
      </section>

      <section class="section" id="about">
        <div class="container">
          <h2 class="section-title">${this._l("section.about", "About")}</h2>
          <p class="about-text">${bio}</p>
        </div>
      </section>

      <section class="section" id="skills" style="background:var(--builtin-header-bg,#f9fafb);border-top:1px solid var(--builtin-border-soft,#e5e7eb);border-bottom:1px solid var(--builtin-border-soft,#e5e7eb);">
        <div class="container">
          <h2 class="section-title">${this._l("section.skills", "Skills")}</h2>
          <div class="skills">
            ${skills.map((s) => html`<span class="skill" @click=${() => this._onSkillClick(s)}>${s}</span>`)}
          </div>
        </div>
      </section>

      ${experiences.length > 0 ? html`
        <section class="section" id="experience">
          <div class="container">
            <h2 class="section-title">${this._l("section.experience", "Experience")}</h2>
            <div class="experience-list">
              ${experiences.map((exp) => html`
                <div class="experience-item">
                  <div class="company">${exp.company}</div>
                  <div class="role">${exp.role}</div>
                  <div class="period">${exp.period}</div>
                  ${exp.desc ? html`<div class="desc">${exp.desc}</div>` : nothing}
                </div>
              `)}
            </div>
          </div>
        </section>
      ` : nothing}

      <section class="section" id="projects">
        <div class="container">
          <h2 class="section-title">${this._l("section.projects", "Projects")}</h2>
          <slot name="projects">
            <div class="project-grid">
              ${projects.map((p) => html`
                <article class="project-card" @click=${() => this._onProjectClick(p)}>
                  <div class="thumb"></div>
                  <div class="overlay">
                    <h3>${p.title}</h3>
                    <p>${p.desc}</p>
                  </div>
                  <div class="body">
                    <h3>${p.title}</h3>
                    <div class="category">${p.category}</div>
                    <p>${p.desc}</p>
                  </div>
                </article>
              `)}
            </div>
          </slot>
        </div>
      </section>

      ${this.contactForm ? html`
        <section class="section" id="contact">
          <div class="container">
            <h2 class="section-title">${this._l("section.contact", "Contact")}</h2>
            <slot name="contact">
              <form class="contact-form" @submit=${this._onContactSubmit}>
                <input type="text" name="name" placeholder="${this._l("form.name", "Your name")}" required />
                <input type="email" name="email" placeholder="${this._l("form.email", "you@example.com")}" required />
                <textarea name="message" placeholder="${this._l("form.message", "Message")}" required></textarea>
                <button type="submit">
                  <builtin-icon name="send" size="18" variant="outlined"></builtin-icon>
                  ${this._l("form.send", "Send Message")}
                </button>
              </form>
            </slot>
          </div>
        </section>
      ` : nothing}

      <div class="page-footer">
        <slot name="footer"><builtin-footer></builtin-footer></slot>
      </div>
    `;
  }
}