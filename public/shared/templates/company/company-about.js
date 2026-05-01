import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) { if (!value) return undefined; try { return JSON.parse(value); } catch { return undefined; } },
  toAttribute(value) { return JSON.stringify(value); }
};

/**
 * @fileoverview BuiltinTplCompanyAbout - Corporate "About Us" page.
 *
 * @attr {string} companyName - Company name.
 * @attr {string} tagline - Tagline.
 * @attr {string} mission - Mission text.
 * @attr {string} values - JSON array of {icon, title, description}.
 * @attr {string} team - JSON array of {name, role, avatar}.
 * @attr {string} stats - JSON array of {label, value}.
 * @attr {string} history - JSON array of {title, time, description}.
 * @attr {string} labels - JSON i18n overrides.
 */
export class BuiltinTplCompanyAbout extends BuiltinBaseElement {
  static properties = {
    companyName: { type: String },
    tagline: { type: String },
    mission: { type: String },
    values: { type: Array },
    team: { type: Array },
    stats: { type: Array },
    history: { type: Array },
    labels: { type: Object, converter: jsonConverter },
      };

  static styles = css`
    :host { display: block; }
    .hero { padding: 80px 20px; text-align: center; background: var(--builtin-header-bg, #f9fafb); border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .hero h1 { font-size: clamp(28px, 5vw, 44px); font-weight: 800; margin: 0 0 12px; color: var(--builtin-color-text, #111827); }
    .hero p { font-size: 18px; color: var(--builtin-color-muted, #6b7280); margin: 0 0 24px; }
    .container { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
    .section { padding: 50px 0; }
    .section h2 { font-size: 24px; font-weight: 700; margin-bottom: 24px; text-align: center; color: var(--builtin-color-text, #111827); }
    .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
    .stat { text-align: center; padding: 24px; border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px); background: var(--builtin-surface, #ffffff); }
    .stat .num { font-size: 32px; font-weight: 800; color: var(--builtin-primary, #2563eb); }
    .stat .lab { font-size: 13px; color: var(--builtin-color-muted, #6b7280); margin-top: 6px; }
    .team-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
    .member { text-align: center; padding: 20px; border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px); background: var(--builtin-surface, #ffffff); }
    .member img { width: 80px; height: 80px; border-radius: 50%; object-fit: cover; margin-bottom: 10px; }
    .member .n { font-weight: 650; color: var(--builtin-color-text, #111827); }
    .member .r { font-size: 13px; color: var(--builtin-color-muted, #6b7280); }
    @media (max-width: 720px) {
      .stats-row { grid-template-columns: repeat(2, 1fr); }
      .team-grid { grid-template-columns: repeat(2, 1fr); }
      .hero { padding: 48px 16px; }
    }
  `;

  _defaultTeam() {
    return [
      { name: "Alice Johnson", role: "CEO", avatar: "https://i.pravatar.cc/150?img=1" },
      { name: "Bob Smith", role: "CTO", avatar: "https://i.pravatar.cc/150?img=2" },
      { name: "Carol White", role: "Designer", avatar: "https://i.pravatar.cc/150?img=3" },
      { name: "Dan Brown", role: "Engineer", avatar: "https://i.pravatar.cc/150?img=4" },
    ];
  }

  _defaultValues() {
    return [
      { icon: "heart", title: "Integrity", description: "We do the right thing, even when no one is watching." },
      { icon: "team", title: "Collaboration", description: "We achieve more together than alone." },
      { icon: "rocket", title: "Innovation", description: "We constantly push boundaries." },
    ];
  }

  _defaultStats() {
    return [
      { label: "Employees", value: "120+" },
      { label: "Customers", value: "5,000+" },
      { label: "Countries", value: "30+" },
      { label: "Years", value: "8" },
    ];
  }

  _defaultHistory() {
    return [
      { title: "Founded", time: "2016", description: "The company was founded with a vision to change the industry." },
      { title: "Series A", time: "2018", description: "Raised our first round of funding and expanded the team." },
      { title: "Global Launch", time: "2021", description: "Expanded operations to over 30 countries worldwide." },
    ];
  }

  _getTeam() {
    return this.team || (this._defaultTeam());
  }

  _getValues() {
    return this.values || (this._defaultValues());
  }

  _getStats() {
    return this.stats || (this._defaultStats());
  }

  _getHistory() {
    return this.history || (this._defaultHistory());
  }

  _on_cta_click = () => {
    this.dispatchEvent(new CustomEvent("builtin-cta-click", { bubbles: true, composed: true, detail: { action: "contact" } }));
  }

  render() {
    const values = this._getValues();
    const team = this._getTeam();
    const stats = this._getStats();
    const history = this._getHistory();

    return html`
      <builtin-navbar items='[]'></builtin-navbar>
      <section class="hero">
        <h1>${this.companyName || this._l("about.company", "Our Company") }</h1>
        <p>${this.tagline || this._l("about.tagline", "Building the future, together.") }</p>
        <button class="builtin-primary" @click="${this._on_cta_click}">${this._l("about.cta", "Get in touch")}</button>
      </section>
      <div class="container">
        <section class="section">
          <h2>${this._l("about.mission", "Our Mission")}</h2>
          <p style="text-align:center;max-width:640px;margin:0 auto;color:var(--builtin-color-muted);line-height:1.7;">${this.mission || this._l("about.missionText", "To empower teams around the world with tools that make work simpler, faster, and more enjoyable.") }</p>
        </section>
        <section class="section">
          <h2>${this._l("about.values", "Our Values")}</h2>
          <builtin-feature-grid features='${JSON.stringify(values)}'></builtin-feature-grid>
        </section>
        <section class="section">
          <h2>${this._l("about.stats", "By the Numbers")}</h2>
          <div class="stats-row">
            ${stats.map((s) => html`
              <div class="stat">
                <div class="num">${s.value}</div>
                <div class="lab">${s.label}</div>
              </div>
            `)}
          </div>
        </section>
        <section class="section">
          <h2>${this._l("about.history", "Our Journey")}</h2>
          <builtin-timeline items='${JSON.stringify(history)}'></builtin-timeline>
        </section>
        <section class="section">
          <h2>${this._l("about.team", "Meet the Team")}</h2>
          <div class="team-grid">
            ${team.map((m) => html`
              <div class="member">
                <img src="${m.avatar || ""}" alt="${m.name || ""}" />
                <div class="n">${m.name}</div>
                <div class="r">${m.role}</div>
              </div>
            `)}
          </div>
        </section>
      </div>
      <builtin-footer></builtin-footer>
    `;
  }
}