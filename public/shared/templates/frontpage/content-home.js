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
 * @fileoverview Blog/media homepage template.
 *
 * @description Layout for blogs, magazines, and content sites.
 * Includes a featured article, category filters, article grid, sidebar, and newsletter.
 *
 * Attributes:
 *   - title: Site heading shown in the header area
 *   - hero-title: Featured article headline
 *   - hero-subtitle: Featured article description
 *   - featured-articles: Array of article objects { id, title, desc }
 *   - categories: Array of category objects { key, label }
 *   - labels: JSON object to override i18n strings
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - featured: Custom featured article content
 *   - sidebar: Custom sidebar widgets
 *   - footer: Page footer
 */
export class BuiltinTplFrontpageContent extends BuiltinBaseElement {
  static properties = {
    title: { type: String },
    labels: { type: Object, converter: jsonConverter },
        heroTitle: { type: String, attribute: "hero-title" },
    heroSubtitle: { type: String, attribute: "hero-subtitle" },
    featuredArticles: { type: Array, attribute: "featured-articles", converter: jsonConverter },
    categories: { type: Array, converter: jsonConverter },
  };

  static styles = css`
    :host { display: block; line-height: 1.55; }
    h1, h2, h3, h4, p { margin: 0; }
    a { color: var(--builtin-primary, #2563eb); text-decoration: none; }
    .container { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
    .site-header {
      padding: 20px 0;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .site-header .container {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .site-header h1 { font-size: 22px; font-weight: 800; color: var(--builtin-color-text, #111827); }
    .featured { padding: 40px 0; }
    .featured-article {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 28px;
      align-items: center;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      background: var(--builtin-surface, #ffffff);
      cursor: pointer;
      transition: background .15s ease;
    }
    .featured-article:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .featured-image { min-height: 280px; background: var(--builtin-header-bg, #f9fafb); }
    .featured-body { padding: 28px; }
    .featured-body .tag {
      display: inline-block;
      padding: 4px 10px;
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 12px;
    }
    .featured-body h2 { font-size: 26px; margin-bottom: 10px; color: var(--builtin-color-text, #111827); }
    .featured-body p { color: var(--builtin-color-muted, #6b7280); }
    .categories { padding: 20px 0; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .cat-list {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .cat-list li a {
      padding: 6px 14px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      display: inline-block;
      font-size: 13px;
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
    }
    .cat-list li a:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .content-wrap {
      display: grid;
      grid-template-columns: 1fr 280px;
      gap: 28px;
      padding: 32px 0;
    }
    .article-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 20px;
    }
    .article-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      background: var(--builtin-surface, #ffffff);
      transition: background .15s ease;
      cursor: pointer;
    }
    .article-card:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .article-card .thumb { min-height: 150px; background: var(--builtin-header-bg, #f9fafb); }
    .article-card .body { padding: 16px; }
    .article-card h3 { font-size: 16px; margin-bottom: 6px; color: var(--builtin-color-text, #111827); }
    .article-card p { font-size: 13px; color: var(--builtin-color-muted, #6b7280); }
    .sidebar { display: flex; flex-direction: column; gap: 20px; }
    .sidebar-block {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 18px;
      background: var(--builtin-surface, #ffffff);
    }
    .sidebar-block h4 { font-size: 14px; margin-bottom: 12px; color: var(--builtin-color-text, #111827); }
    .tag-cloud { display: flex; flex-wrap: wrap; gap: 8px; }
    .tag-cloud span {
      padding: 4px 10px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      cursor: pointer;
    }
    .tag-cloud span:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
      color: var(--builtin-color-text, #111827);
    }
    .newsletter {
      padding: 40px 0;
      text-align: center;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .newsletter h2 { font-size: 20px; margin-bottom: 8px; color: var(--builtin-color-text, #111827); }
    .newsletter p { color: var(--builtin-color-muted, #6b7280); font-size: 14px; margin-bottom: 16px; }
    .newsletter-form {
      display: inline-flex;
      gap: 10px;
      max-width: 420px;
      width: 100%;
    }
    .newsletter-form input {
      flex: 1 1 auto;
      min-height: 40px;
      padding: 0 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      font: inherit;
    }
    .newsletter-form button {
      min-height: 40px;
      padding: 0 18px;
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
      padding: 24px 0;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }

    @media (max-width: 720px) {
      .container { padding: 0 16px; }
      .site-header .container { flex-direction: column; gap: 10px; align-items: flex-start; }
      .featured-article { grid-template-columns: 1fr; }
      .featured-image { min-height: 200px; }
      .content-wrap { grid-template-columns: 1fr; }
      .article-grid { grid-template-columns: 1fr; }
      .sidebar { order: 1; }
      .newsletter-form { flex-direction: column; }
      .newsletter-form input, .newsletter-form button { width: 100%; min-height: 44px; }
    }
  `;

  constructor() {
    super();
    this.featuredArticles = undefined;
    this.categories = undefined;
  }

  _defaultFeaturedArticles() {
    return [
      { id: "1", title: this._l("article.1.title", "Article One"), desc: this._l("article.1.desc", "A short summary of the first article.") },
      { id: "2", title: this._l("article.2.title", "Article Two"), desc: this._l("article.2.desc", "A short summary of the second article.") },
      { id: "3", title: this._l("article.3.title", "Article Three"), desc: this._l("article.3.desc", "A short summary of the third article.") },
      { id: "4", title: this._l("article.4.title", "Article Four"), desc: this._l("article.4.desc", "A short summary of the fourth article.") },
      { id: "5", title: this._l("article.5.title", "Article Five"), desc: this._l("article.5.desc", "A short summary of the fifth article.") },
      { id: "6", title: this._l("article.6.title", "Article Six"), desc: this._l("article.6.desc", "A short summary of the sixth article.") },
    ];
  }

  _defaultCategories() {
    return [
      { key: "all", label: this._l("category.all", "All") },
      { key: "tech", label: this._l("category.tech", "Tech") },
      { key: "design", label: this._l("category.design", "Design") },
      { key: "business", label: this._l("category.business", "Business") },
      { key: "culture", label: this._l("category.culture", "Culture") },
    ];
  }

  _dispatch_article_click(id, title) {
    this.dispatchEvent(new CustomEvent("builtin-article-click", {
      bubbles: true,
      composed: true,
      detail: { id, title },
    }));
  }

  _dispatch_category_click(category) {
    this.dispatchEvent(new CustomEvent("builtin-category-click", {
      bubbles: true,
      composed: true,
      detail: { category },
    }));
  }

  _dispatch_cta_click(action) {
    this.dispatchEvent(new CustomEvent("builtin-cta-click", {
      bubbles: true,
      composed: true,
      detail: { action },
    }));
  }

  render() {
    const title = this.title || this._l("site.title", "Daily Journal");
    const heroTitle = this.heroTitle || this._l("featured.title", "The Future of Web Components");
    const heroSubtitle = this.heroSubtitle || this._l("featured.desc", "Explore how modern standards are reshaping the way we build reusable UI.");
    const featuredArticles = this.featuredArticles ?? (this._defaultFeaturedArticles());
    const categories = this.categories ?? (this._defaultCategories());
    const tags = ["JavaScript", "CSS", "HTML", "Web", "AI", "Design"];

    return html`
      <slot name="navbar">
        <header class="site-header">
          <div class="container">
            <h1>${title}</h1>
            <nav>
              <a href="#" @click=${(e) => { e.preventDefault(); this._dispatch_cta_click("nav-home"); }}>${this._l("nav.home", "Home")}</a> &nbsp;
              <a href="#" @click=${(e) => { e.preventDefault(); this._dispatch_cta_click("nav-articles"); }}>${this._l("nav.articles", "Articles")}</a> &nbsp;
              <a href="#" @click=${(e) => { e.preventDefault(); this._dispatch_cta_click("nav-about"); }}>${this._l("nav.about", "About")}</a>
            </nav>
          </div>
        </header>
      </slot>

      <section class="featured">
        <div class="container">
          <slot name="featured">
            <article class="featured-article" @click=${() => this._dispatch_article_click("featured", heroTitle)}>
              <div class="featured-image"></div>
              <div class="featured-body">
                <span class="tag">${this._l("featured.tag", "Featured")}</span>
                <h2>${heroTitle}</h2>
                <p>${heroSubtitle}</p>
              </div>
            </article>
          </slot>
        </div>
      </section>

      <section class="categories">
        <div class="container">
          <ul class="cat-list">
            ${repeat(categories, (c) => c.key, (c) => html`<li><a href="#" @click=${(e) => { e.preventDefault(); this._dispatch_category_click(c.key); }}>${c.label}</a></li>`)}
          </ul>
        </div>
      </section>

      <div class="container">
        <div class="content-wrap">
          <div class="main">
            <div class="article-grid">
              ${repeat(featuredArticles, (a) => a.id, (a) => html`
                <article class="article-card" @click=${() => this._dispatch_article_click(a.id, a.title)}>
                  <div class="thumb"></div>
                  <div class="body">
                    <h3>${a.title}</h3>
                    <p>${a.desc}</p>
                  </div>
                </article>
              `)}
            </div>
          </div>
          <slot name="sidebar">
            <aside class="sidebar">
              <div class="sidebar-block">
                <h4>${this._l("sidebar.trendingTags", "Trending Tags")}</h4>
                <div class="tag-cloud">
                  ${repeat(tags, (t) => t, (t) => html`<span>${t}</span>`)}
                </div>
              </div>
              <div class="sidebar-block">
                <h4>${this._l("sidebar.about", "About")}</h4>
                <p style="font-size:13px;color:var(--builtin-color-muted, #6b7280);">${this._l("sidebar.aboutDesc", "Curated stories for modern developers and designers.")}</p>
              </div>
            </aside>
          </slot>
        </div>
      </div>

      <section class="newsletter">
        <div class="container">
          <h2>${this._l("newsletter.title", "Subscribe to our newsletter")}</h2>
          <p>${this._l("newsletter.desc", "Weekly digests of the best articles, no spam.")}</p>
          <form class="newsletter-form" @submit=${(e) => { e.preventDefault(); this._dispatch_cta_click("subscribe"); }}>
            <input type="email" placeholder="${this._l("newsletter.placeholder", "you@example.com")}" />
            <button type="submit">${this._l("newsletter.button", "Subscribe")}</button>
          </form>
        </div>
      </section>

      <slot name="footer"><builtin-footer></builtin-footer></slot>
    `;
  }
}