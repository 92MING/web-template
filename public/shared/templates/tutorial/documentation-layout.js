import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "../../components/lit-base.js";

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
 * @fileoverview Documentation page with sidebar TOC template.
 *
 * @description Structure: navbar, left sidebar with section list,
 * main content area, right mini section list (sticky), footer.
 *
 * Attributes:
 *   - sections: JSON array of sections [{ title, content, id }]
 *   - activeSection: Currently active section id
 *   - labels: JSON object to override i18n strings
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - content: Main documentation content
 *   - footer: Page footer
 *
 * Events:
 *   - builtin-section-change: Dispatched when a section is clicked ({ id })
 */
export class BuiltinTplTutorialDocumentation extends BuiltinBaseElement {
  static properties = {
    sections: { type: Array, converter: jsonConverter },
    activeSection: { type: String },
        labels: { type: Object, converter: jsonConverter },
  };

  static styles = css`
    :host {
      display: block;
      color: var(--builtin-color-text, #111827);
      font-family: inherit;
    }
    .doc-container {
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }
    .navbar {
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border, #d1d5db);
      padding: 0.75rem 1.5rem;
    }
    .doc-body {
      flex: 1;
      display: grid;
      grid-template-columns: 260px 1fr 220px;
      gap: 2rem;
      padding: 2rem 1.5rem;
      max-width: 1280px;
      margin: 0 auto;
      width: 100%;
      box-sizing: border-box;
    }
    .sidebar {
      position: sticky;
      top: 1rem;
      align-self: start;
    }
    .toc {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 1rem;
    }
    .toc-title {
      font-size: 0.875rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--builtin-color-muted, #6b7280);
      margin-bottom: 0.75rem;
    }
    .toc-list {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .section-link {
      display: block;
      padding: 0.375rem 0;
      font-size: 0.9375rem;
      color: var(--builtin-color-text, #111827);
      text-decoration: none;
      border-radius: var(--builtin-radius, 6px);
    }
    .section-link:hover {
      color: var(--builtin-primary, #2563eb);
    }
    .section-link.active {
      color: var(--builtin-primary, #2563eb);
      font-weight: 600;
    }
    .main {
      min-width: 0;
    }
    .main ::slotted([slot="content"]) {
      line-height: 1.7;
    }
    .main ::slotted(h1),
    .main ::slotted(h2),
    .main ::slotted(h3) {
      color: var(--builtin-color-text, #111827);
      margin-top: 1.5rem;
      margin-bottom: 0.75rem;
    }
    .main ::slotted(p) {
      color: var(--builtin-color-text, #111827);
      margin-bottom: 1rem;
    }
    .demo-content h2 {
      color: var(--builtin-color-text, #111827);
      margin-top: 1.5rem;
      margin-bottom: 0.75rem;
    }
    .demo-content p {
      color: var(--builtin-color-text, #111827);
      margin-bottom: 1rem;
      line-height: 1.7;
    }
    .right-rail {
      position: sticky;
      top: 1rem;
      align-self: start;
    }
    .mini-toc {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 1rem;
    }
    .mini-toc-title {
      font-size: 0.875rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--builtin-color-muted, #6b7280);
      margin-bottom: 0.75rem;
    }
    .mini-toc-list {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .mini-toc-list li {
      margin-bottom: 0.25rem;
    }
    .mini-toc-list .section-link {
      font-size: 0.875rem;
      color: var(--builtin-color-muted, #6b7280);
    }
    .mini-toc-list .section-link:hover {
      color: var(--builtin-primary, #2563eb);
    }
    .mini-toc-list .section-link.active {
      color: var(--builtin-primary, #2563eb);
      font-weight: 600;
    }
    .mobile-select-wrap {
      display: none;
      margin-bottom: 1rem;
    }
    .mobile-select {
      width: 100%;
      padding: 0.625rem;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      font-size: 0.9375rem;
      font: inherit;
    }
    .footer {
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border, #d1d5db);
      padding: 1.5rem;
    }

    @media (max-width: 720px) {
      .doc-body {
        grid-template-columns: 1fr;
        padding: 1rem;
        gap: 1rem;
      }
      .sidebar {
        position: static;
        display: none;
      }
      .mobile-select-wrap {
        display: block;
      }
      .right-rail {
        display: none;
      }
    }
  `;

  constructor() {
    super();
    this.sections = [];
    this.activeSection = "";
  }

  _defaultSections() {
    return [
      { title: "Getting Started", content: "<p>Welcome to the documentation. This guide will help you get up and running quickly.</p>", id: "getting-started" },
      { title: "Core Concepts", content: "<p>Learn about the fundamental ideas and architecture behind the platform.</p>", id: "core-concepts" },
      { title: "API Reference", content: "<p>Explore the available endpoints, parameters, and response formats.</p>", id: "api-reference" },
      { title: "Examples", content: "<p>See practical examples and common patterns for everyday use.</p>", id: "examples" },
    ];
  }

  _effectiveSections() {
    return this.sections?.length ? this.sections : (this._defaultSections());
  }

  _onSectionClick(e) {
    const link = e.target.closest(".section-link");
    if (link) {
      const id = link.dataset.id;
      if (id) {
        this.activeSection = id;
        this.dispatchEvent(
          new CustomEvent("builtin-section-change", {
            detail: { id },
            bubbles: true,
            composed: true,
          })
        );
      }
    }
  }

  _onMobileSelect(e) {
    const id = e.target.value;
    if (id) {
      this.activeSection = id;
      this.dispatchEvent(
        new CustomEvent("builtin-section-change", {
          detail: { id },
          bubbles: true,
          composed: true,
        })
      );
      e.target.value = "";
    }
  }

  _renderSidebar() {
    const sections = this._effectiveSections();
    if (!sections.length) return html``;
    return html`
      <nav class="toc" aria-label="Table of contents" @click=${this._onSectionClick}>
        <div class="toc-title">${this._l("toc.title", "Contents")}</div>
        <ul class="toc-list">
          ${repeat(sections, (s) => s.id, (s) => html`
            <li>
              <a class="section-link ${classMap({ active: s.id === this.activeSection })}"
                 href="#${s.id}"
                 data-id="${s.id}">${s.title}</a>
            </li>
          `)}
        </ul>
      </nav>
    `;
  }

  _renderMiniToc() {
    const sections = this._effectiveSections();
    if (!sections.length) return html``;
    return html`
      <nav class="mini-toc" aria-label="On this page" @click=${this._onSectionClick}>
        <div class="mini-toc-title">${this._l("miniToc.title", "On this page")}</div>
        <ul class="mini-toc-list">
          ${repeat(sections, (s) => s.id, (s) => html`
            <li>
              <a class="section-link ${classMap({ active: s.id === this.activeSection })}"
                 href="#${s.id}"
                 data-id="${s.id}">${s.title}</a>
            </li>
          `)}
        </ul>
      </nav>
    `;
  }

  _renderMobileSelect() {
    const sections = this._effectiveSections();
    return html`
      <select class="mobile-select" aria-label="Jump to section" @change=${this._onMobileSelect}>
        <option value="">${this._l("mobileSelect.placeholder", "Jump to section...")}</option>
        ${repeat(sections, (s) => s.id, (s) => html`
          <option value="${s.id}">${s.title}</option>
        `)}
      </select>
    `;
  }

  _renderMainContent() {
    const sections = this._effectiveSections();
    if (sections.length) {
      const active = sections.find((s) => s.id === this.activeSection) || sections[0];
      if (active) {
        return html`
          <div class="demo-content">
            <h2 id="${active.id}">${active.title}</h2>
            ${unsafeHTML(active.content)}
          </div>
        `;
      }
    }
    return html`<slot name="content"></slot>`;
  }

  render() {
    return html`
      <div class="doc-container">
        <nav class="navbar">
          <slot name="navbar"></slot>
        </nav>

        <div class="doc-body">
          <aside class="sidebar">
            ${this._renderSidebar()}
          </aside>

          <div class="mobile-select-wrap">
            ${this._renderMobileSelect()}
          </div>

          <main class="main">
            ${this._renderMainContent()}
          </main>

          <aside class="right-rail">
            ${this._renderMiniToc()}
          </aside>
        </div>

        <footer class="footer">
          <slot name="footer"></slot>
        </footer>
      </div>
    `;
  }
}