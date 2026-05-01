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
 * @fileoverview Magazine long-form article layout.
 *
 * @description Structure: navbar, full-width hero image, article metadata (author, date),
 * multi-column text body (2 columns on desktop), pull quote block, inline image slot,
 * author bio card, related articles grid, footer.
 *
 * Properties:
 *   - title (string): Article title.
 *   - author (string): Author name.
 *   - publish-date (string): Publish date.
 *   - cover-image (string): URL for cover/hero image.
 *   - body-paragraphs (Array): JSON array of paragraph strings.
 *   - pull-quote (string): Pull quote text.
 *   - related-articles (Array): JSON array of {id, title, description}.
 *   - author-bio (string): Author biography HTML/text.
 *   - labels (Object): JSON i18n overrides.
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - hero-image: Full-width hero image
 *   - author-name: Author name in metadata
 *   - publish-date: Publish date in metadata
 *   - pull-quote: Pull quote text
 *   - inline-image: Inline article image
 *   - author-bio: Author biography card
 *   - footer: Page footer
 *
 * Events:
 *   - builtin-article-click: Fired when a related article card is clicked.
 */
export class BuiltinTplMagazineEditorial extends BuiltinBaseElement {
  static properties = {
    title: { type: String },
    author: { type: String },
    publishDate: { type: String, attribute: "publish-date" },
    coverImage: { type: String, attribute: "cover-image" },
    bodyParagraphs: { type: Array, attribute: "body-paragraphs" },
    pullQuote: { type: String, attribute: "pull-quote" },
    relatedArticles: { type: Array, attribute: "related-articles" },
    authorBio: { type: String, attribute: "author-bio" },
    labels: { type: Object, converter: jsonConverter },
      };

  static styles = css`
    :host {
      display: block;
      color: var(--builtin-color-text, #111827);
      font-family: inherit;
    }
    .editorial-container {
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }
    .navbar {
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border, #d1d5db);
      padding: 0.75rem 1.5rem;
    }
    .hero {
      width: 100%;
      max-height: 480px;
      overflow: hidden;
      background: var(--builtin-header-bg, #f9fafb);
    }
    .hero img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .hero ::slotted([slot="hero-image"]) {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .meta {
      padding: 1.5rem;
      text-align: center;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .meta .author {
      color: var(--builtin-primary, #2563eb);
      font-weight: 600;
    }
    .meta .date {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 0.875rem;
      margin-top: 0.25rem;
    }
    .body {
      flex: 1;
      padding: 2rem 1.5rem;
      column-count: 2;
      column-gap: 2rem;
      line-height: 1.7;
      color: var(--builtin-color-text, #111827);
    }
    .body p {
      margin: 0 0 1rem 0;
    }
    .body ::slotted(p) {
      margin: 0 0 1rem 0;
    }
    .pull-quote {
      margin: 2rem 1.5rem;
      padding: 1.5rem;
      border-left: 4px solid var(--builtin-primary, #2563eb);
      background: var(--builtin-surface, #ffffff);
      border-radius: var(--builtin-radius, 6px);
      font-style: italic;
      font-size: 1.125rem;
      color: var(--builtin-color-text, #111827);
    }
    .inline-image {
      margin: 1.5rem;
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .inline-image ::slotted(img) {
      width: 100%;
      display: block;
    }
    .author-bio {
      margin: 1.5rem;
      padding: 1.5rem;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
    }
    .related {
      margin: 1.5rem;
    }
    .related-title {
      font-size: 1.125rem;
      font-weight: 600;
      margin-bottom: 1rem;
      color: var(--builtin-color-text, #111827);
    }
    .related-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1rem;
    }
    .related-card {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      padding: 1rem;
      transition: background 0.2s;
      cursor: pointer;
    }
    .related-card:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    .related-card h4 {
      margin: 0 0 0.5rem 0;
      font-size: 0.9375rem;
      color: var(--builtin-color-text, #111827);
    }
    .related-card p {
      margin: 0;
      font-size: 0.8125rem;
      color: var(--builtin-color-muted, #6b7280);
    }
    .footer {
      background: var(--builtin-header-bg, #f9fafb);
      border-top: 1px solid var(--builtin-border, #d1d5db);
      padding: 1.5rem;
    }

    @media (max-width: 720px) {
      .body {
        column-count: 1;
        padding: 1rem;
      }
      .related-grid {
        grid-template-columns: 1fr;
      }
      .hero {
        max-height: 260px;
      }
      .pull-quote,
      .inline-image,
      .author-bio,
      .related {
        margin-left: 1rem;
        margin-right: 1rem;
      }
    }
  `;

  _defaultBodyParagraphs() {
    return [
      "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.",
      "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
      "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo.",
    ];
  }

  _defaultRelatedArticles() {
    return [
      { id: "1", title: "Related Story One", description: "A brief teaser for the first related article." },
      { id: "2", title: "Related Story Two", description: "A brief teaser for the second related article." },
      { id: "3", title: "Related Story Three", description: "A brief teaser for the third related article." },
    ];
  }

  _defaultAuthorBio() {
    return "Author Name is a senior writer covering technology and design.";
  }

  _getBodyParagraphs() {
    return this.bodyParagraphs || (this._defaultBodyParagraphs());
  }

  _getRelatedArticles() {
    return this.relatedArticles || (this._defaultRelatedArticles());
  }

  _getAuthorBio() {
    return this.authorBio || (this._defaultAuthorBio());
  }

  _on_article_click = (id, title) => {
    this.dispatchEvent(new CustomEvent("builtin-article-click", { bubbles: true, composed: true, detail: { id, title } }));
  }

  render() {
    const bodyParagraphs = this._getBodyParagraphs();
    const related = this._getRelatedArticles();
    const authorBio = this._getAuthorBio();

    return html`
      <div class="editorial-container">
        <nav class="navbar">
          <slot name="navbar"></slot>
        </nav>

        <div class="hero">
          <slot name="hero-image">
            ${this.coverImage ? html`<img src="${this.coverImage}" alt="${this.title || ""}" />` : nothing}
          </slot>
        </div>

        <div class="meta">
          <div class="author"><slot name="author-name">${this.author || this._l("meta.author", "Author Name") }</slot></div>
          <div class="date"><slot name="publish-date">${this.publishDate || this._l("meta.date", "1 Jan 2025") }</slot></div>
        </div>

        <div class="body">
          <slot>
            ${bodyParagraphs.map((p) => html`<p>${p}</p>`)}
          </slot>
        </div>

        <div class="pull-quote">
          <slot name="pull-quote">${this.pullQuote || this._l("pullQuote.default", "A compelling quote that captures the essence of the article.") }</slot>
        </div>

        <div class="inline-image">
          <slot name="inline-image"></slot>
        </div>

        <div class="author-bio">
          <slot name="author-bio">${authorBio}</slot>
        </div>

        <section class="related">
          <div class="related-title">${this._l("related.title", "Related Articles")}</div>
          <div class="related-grid">
            ${repeat(related, (r) => r.id, (r) => html`
              <article class="related-card" @click="${() => this._on_article_click(r.id, r.title)}">
                <h4>${r.title}</h4>
                <p>${r.description}</p>
              </article>
            `)}
          </div>
        </section>

        <footer class="footer">
          <slot name="footer"></slot>
        </footer>
      </div>
    `;
  }
}