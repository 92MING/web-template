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
 * @fileoverview News portal layout.
 *
 * @description Structure: navbar, breaking news ticker bar (simple marquee CSS),
 * main headline + image, secondary stories grid (2 columns),
 * sidebar with latest list + tag cloud, footer.
 *
 * Properties:
 *   - headlines (Array): JSON array of headline objects {title, category, time} for the ticker.
 *   - categories (Array): JSON array of category strings for the tag cloud.
 *   - featuredStory (Object): JSON object {title, excerpt, image?, author, date} for the main headline.
 *   - sideStories (Array): JSON array of {title, summary} for the secondary grid.
 *   - labels (Object): JSON i18n overrides.
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - headline: Main headline content
 *   - sidebar: Custom sidebar widgets
 *   - footer: Page footer
 *
 * Events:
 *   - builtin-article-click: Fired when an article card is clicked. Detail: { title }.
 *   - builtin-category-click: Fired when a category tag is clicked. Detail: { category }.
 */
export class BuiltinTplMagazineNews extends BuiltinBaseElement {
  static properties = {
    headlines: { type: Array, converter: jsonConverter },
    categories: { type: Array, converter: jsonConverter },
    featuredStory: { type: Object, converter: jsonConverter, attribute: "featured-story" },
    sideStories: { type: Array, converter: jsonConverter, attribute: "side-stories" },
    labels: { type: Object, converter: jsonConverter },
      };

  static styles = css`
    :host {
      display: block;
      color: var(--builtin-color-text, #111827);
      font-family: inherit;
    }
    .news-container {
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }
    .navbar {
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border, #d1d5db);
      padding: 0.75rem 1.5rem;
    }
    .ticker {
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      padding: 0.5rem 0;
      overflow: hidden;
      white-space: nowrap;
    }
    .ticker-inner {
      display: inline-block;
      padding-left: 100%;
      animation: marquee 20s linear infinite;
    }
    @keyframes marquee {
      0% { transform: translateX(0); }
      100% { transform: translateX(-100%); }
    }
    .ticker-item {
      display: inline-block;
      padding: 0 2rem;
      font-size: 0.875rem;
      font-weight: 500;
    }
    .main {
      flex: 1;
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 1.5rem;
      padding: 1.5rem;
    }
    .headline {
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }
    .headline ::slotted(img) {
      width: 100%;
      border-radius: var(--builtin-radius-lg, 8px);
      display: block;
    }
    .featured-story {
      cursor: pointer;
      transition: opacity 0.2s;
    }
    .featured-story:hover {
      opacity: 0.85;
    }
    .featured-story img {
      width: 100%;
      border-radius: var(--builtin-radius-lg, 8px);
      display: block;
      margin-bottom: 0.75rem;
    }
    .featured-story h2 {
      margin: 0 0 0.5rem 0;
      font-size: 1.5rem;
      color: var(--builtin-color-text, #111827);
    }
    .featured-story p {
      margin: 0;
      font-size: 1rem;
      color: var(--builtin-color-muted, #6b7280);
    }
    .secondary-stories {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 1rem;
      margin-top: 1rem;
    }
    .story-card {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      padding: 1rem;
      transition: background 0.2s;
      cursor: pointer;
    }
    .story-card:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    .story-card h4 {
      margin: 0 0 0.5rem 0;
      font-size: 0.9375rem;
      color: var(--builtin-color-text, #111827);
    }
    .story-card p {
      margin: 0;
      font-size: 0.8125rem;
      color: var(--builtin-color-muted, #6b7280);
    }
    .sidebar {
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }
    .latest-list {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 1rem;
    }
    .latest-list h3 {
      margin: 0 0 0.75rem 0;
      font-size: 1rem;
      color: var(--builtin-color-text, #111827);
    }
    .latest-list ul {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .latest-list li {
      padding: 0.5rem 0;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      font-size: 0.875rem;
      color: var(--builtin-color-muted, #6b7280);
    }
    .latest-list li:last-child {
      border-bottom: none;
    }
    .tag-cloud {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 1rem;
    }
    .tag-cloud h3 {
      margin: 0 0 0.75rem 0;
      font-size: 1rem;
      color: var(--builtin-color-text, #111827);
    }
    .tags {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .tag {
      background: var(--builtin-header-bg, #f9fafb);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      padding: 0.25rem 0.625rem;
      font-size: 0.75rem;
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      transition: background 0.2s;
    }
    .tag:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    .footer {
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border, #d1d5db);
      padding: 1.5rem;
    }

    @media (max-width: 720px) {
      .main {
        grid-template-columns: 1fr;
        padding: 1rem;
      }
      .headline {
        width: 100%;
      }
      .secondary-stories {
        grid-template-columns: 1fr;
      }
      .sidebar {
        order: 3;
      }
    }
  `;

  _defaultHeadlines() {
    return [
      { title: this._l("ticker.0.title", "Breaking: Major event unfolds downtown."), category: this._l("ticker.0.cat", "News"), time: this._l("ticker.0.time", "2h ago") },
      { title: this._l("ticker.1.title", "Sports: Local team clinches playoff spot."), category: this._l("ticker.1.cat", "Sports"), time: this._l("ticker.1.time", "3h ago") },
      { title: this._l("ticker.2.title", "Tech: New framework release announced."), category: this._l("ticker.2.cat", "Tech"), time: this._l("ticker.2.time", "5h ago") },
      { title: this._l("ticker.3.title", "World: Summit concludes with agreement."), category: this._l("ticker.3.cat", "World"), time: this._l("ticker.3.time", "6h ago") },
    ];
  }

  _defaultCategories() {
    return [
      this._l("tag.politics", "Politics"),
      this._l("tag.tech", "Tech"),
      this._l("tag.science", "Science"),
      this._l("tag.health", "Health"),
      this._l("tag.culture", "Culture"),
    ];
  }

  _defaultFeaturedStory() {
    return {
      title: this._l("featured.title", "Main Headline: A Major Story Unfolds"),
      excerpt: this._l("featured.excerpt", "This is the lead story summary that captures the essence of today's top news."),
      image: "",
      author: this._l("featured.author", "Jane Doe"),
      date: this._l("featured.date", "May 1, 2026"),
    };
  }

  _defaultSideStories() {
    return [
      { title: this._l("story.0.title", "Secondary Story One"), summary: this._l("story.0.desc", "A short summary of the secondary news item.") },
      { title: this._l("story.1.title", "Secondary Story Two"), summary: this._l("story.1.desc", "A short summary of another secondary news item.") },
      { title: this._l("story.2.title", "Secondary Story Three"), summary: this._l("story.2.desc", "A short summary of a third secondary news item.") },
    ];
  }

  _defaultLatest() {
    return [
      this._l("latest.0", "Latest article headline one"),
      this._l("latest.1", "Latest article headline two"),
      this._l("latest.2", "Latest article headline three"),
      this._l("latest.3", "Latest article headline four"),
      this._l("latest.4", "Latest article headline five"),
    ];
  }

  _getHeadlines() {
    if (Array.isArray(this.headlines) && this.headlines.length) return this.headlines;
    return this._defaultHeadlines();
  }

  _getCategories() {
    if (Array.isArray(this.categories) && this.categories.length) return this.categories;
    return this._defaultCategories();
  }

  _getFeaturedStory() {
    return this.featuredStory || (this._defaultFeaturedStory());
  }

  _getSideStories() {
    if (Array.isArray(this.sideStories) && this.sideStories.length) return this.sideStories;
    return this._defaultSideStories();
  }

  _getLatest() {
    return this._defaultLatest();
  }

  _on_category_click = (category) => {
    this.dispatchEvent(new CustomEvent("builtin-category-click", { bubbles: true, composed: true, detail: { category } }));
  }

  render() {
    const headlines = this._getHeadlines();
    const categories = this._getCategories();
    const featured = this._getFeaturedStory();
    const sideStories = this._getSideStories();
    const latest = this._getLatest();

    return html`
      <div class="news-container">
        <nav class="navbar">
          <slot name="navbar"></slot>
        </nav>

        <div class="ticker">
          <div class="ticker-inner">
            ${repeat(headlines, (h, i) => i, (h) => html`<span class="ticker-item">${h.title}</span>`)}
          </div>
        </div>

        <div class="main">
          <section class="headline">
            <slot name="headline">
              ${featured ? html`
                <article class="featured-story" @click="${() => this.dispatchEvent(new CustomEvent('builtin-article-click', { bubbles: true, composed: true, detail: { title: featured.title } }))}">
                  ${featured.image ? html`<img src="${featured.image}" alt="${featured.title}" />` : nothing}
                  <h2>${featured.title}</h2>
                  <p>${featured.excerpt}</p>
                </article>
              ` : nothing}
            </slot>
            <div class="secondary-stories">
              ${repeat(sideStories, (s, i) => i, (s) => html`
                <article class="story-card" @click="${() => this.dispatchEvent(new CustomEvent('builtin-article-click', { bubbles: true, composed: true, detail: { title: s.title } }))}">
                  <h4>${s.title}</h4>
                  <p>${s.summary}</p>
                </article>
              `)}
            </div>
          </section>

          <aside class="sidebar">
            <slot name="sidebar"></slot>
            ${latest.length ? html`
              <div class="latest-list">
                <h3>${this._l("latest.title", "Latest")}</h3>
                <ul>
                  ${repeat(latest, (l, i) => i, (l) => html`<li>${l}</li>`)}
                </ul>
              </div>
            ` : nothing}
            ${categories.length ? html`
              <div class="tag-cloud">
                <h3>${this._l("tags.title", "Tags")}</h3>
                <div class="tags">
                  ${repeat(categories, (c) => c, (c) => html`<span class="tag" @click="${() => this._on_category_click(c)}">${c}</span>`)}
                </div>
              </div>
            ` : nothing}
          </aside>
        </div>

        <footer class="footer">
          <slot name="footer"></slot>
        </footer>
      </div>
    `;
  }
}