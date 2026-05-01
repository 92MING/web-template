import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) { if (!value) return undefined; try { return JSON.parse(value); } catch { return undefined; } },
  toAttribute(value) { return JSON.stringify(value); }
};

/**
 * @fileoverview BuiltinTplBlogArticle — Medium-style blog article reading page.
 *
 * @attr {string} title — Article title.
 * @attr {string} category — Category name.
 * @attr {string} author — Author name.
 * @attr {string} avatar — Author avatar.
 * @attr {string} date — Publish date.
 * @attr {string} readTime — Read time string.
 * @attr {string} cover — Cover image URL.
 * @attr {string} content — Article body (Markdown/HTML).
 * @attr {string} tags — JSON array of tag strings.
 * @attr {string} related — JSON array of {title, image, href}.
 * @attr {string} labels — JSON i18n overrides.
 * @attr {string} author-bio — Author bio text.
 * @attr {boolean} bookmarked — Bookmark state.
 */
export class BuiltinTplBlogArticle extends BuiltinBaseElement {
  static properties = {
    title: { type: String },
    category: { type: String },
    author: { type: String },
    avatar: { type: String },
    date: { type: String },
    readTime: { type: String, attribute: "read-time" },
    cover: { type: String },
    content: { type: String },
    tags: { type: Array },
    related: { type: Array },
    labels: { type: Object, converter: jsonConverter },
    authorBio: { type: String, attribute: "author-bio" },
        bookmarked: { type: Boolean },
  };

  static styles = css`
    :host { display: block; background: var(--builtin-surface, #ffffff); }
    .article { max-width: 720px; margin: 0 auto; padding: 24px 20px 60px; }
    .category { font-size: 12px; font-weight: 700; color: var(--builtin-primary, #2563eb); text-transform: uppercase; letter-spacing: .05em; }
    h1 { font-size: clamp(26px, 4vw, 38px); font-weight: 800; line-height: 1.2; margin: 10px 0 18px; color: var(--builtin-color-text, #111827); }
    .author-row { display: flex; align-items: center; gap: 10px; margin-bottom: 24px; }
    .author-row img { width: 40px; height: 40px; border-radius: 50%; object-fit: cover; }
    .author-row .meta { font-size: 13px; color: var(--builtin-color-muted, #6b7280); }
    .author-row .meta strong { color: var(--builtin-color-text, #111827); }
    .cover { width: 100%; border-radius: var(--builtin-radius-lg, 12px); overflow: hidden; margin-bottom: 28px; }
    .cover img { width: 100%; height: auto; display: block; }
    .body { font-size: 17px; line-height: 1.8; color: var(--builtin-color-text, #111827); }
    .body p { margin: 0 0 18px; }
    .tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .bio { display: flex; gap: 14px; margin-top: 32px; padding: 20px; border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px); background: var(--builtin-header-bg, #f9fafb); }
    .bio img { width: 56px; height: 56px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }
    .related { margin-top: 40px; }
    .related h3 { font-size: 18px; font-weight: 700; margin-bottom: 16px; color: var(--builtin-color-text, #111827); }
    .related-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
    .rel-card { border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px); overflow: hidden; cursor: pointer; background: var(--builtin-surface, #ffffff); }
    .rel-card img { width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }
    .rel-card .t { padding: 10px; font-size: 14px; font-weight: 600; color: var(--builtin-color-text, #111827); line-height: 1.3; }
    @media (max-width: 720px) {
      .related-grid { grid-template-columns: 1fr; }
      .body { font-size: 16px; }
    }
  `;

  _default_avatar() {
    return "https://i.pravatar.cc/150";
  }

  _default_author_bio() {
    return "Writer and storyteller.";
  }

  _default_tags() {
    return ["Design", "Productivity", "Tech"];
  }

  _default_related() {
    return [
      { title: "Understanding UI Patterns", image: "https://picsum.photos/400/225?random=1" },
      { title: "Accessibility Best Practices", image: "https://picsum.photos/400/225?random=2" },
      { title: "Modern CSS Techniques", image: "https://picsum.photos/400/225?random=3" },
    ];
  }

  render() {
    const avatar = this.avatar || (this._default_avatar());
    const author_bio = this.authorBio || (this._default_author_bio());
    const tags = this.tags || (this._default_tags());
    const related = this.related || (this._default_related());

    return html`
      <builtin-navbar items='[]'>
        <div slot="start">
          <button
            style="padding:6px 10px;border:1px solid var(--builtin-border);border-radius:6px;background:var(--builtin-button-bg);cursor:pointer;"
            @click="${() => this.dispatchEvent(new CustomEvent('builtin-back', { bubbles: true, composed: true }))}"
            aria-label="Back"
          >
            <builtin-icon name="left" size="16" variant="outlined"></builtin-icon> ${this._l("blog.back", "Back")}
          </button>
        </div>
        <div slot="end" style="display:flex;gap:10px;">
          <button
            style="padding:6px 10px;border:1px solid var(--builtin-border);border-radius:6px;background:var(--builtin-button-bg);cursor:pointer;"
            @click="${() => this.dispatchEvent(new CustomEvent('builtin-share', { bubbles: true, composed: true, detail: { title: this.title, url: window.location.href } }))}"
            aria-label="${this._l('share.aria', 'Share')}"
          >
            <builtin-icon name="share-alt" size="16" variant="outlined"></builtin-icon>
          </button>
          <button
            style="padding:6px 10px;border:1px solid var(--builtin-border);border-radius:6px;background:var(--builtin-button-bg);cursor:pointer;"
            @click="${() => { this.bookmarked = !this.bookmarked; this.dispatchEvent(new CustomEvent('builtin-bookmark', { bubbles: true, composed: true, detail: { title: this.title, bookmarked: this.bookmarked } })); }}"
            aria-label="${this.bookmarked ? this._l('bookmark.remove', 'Remove bookmark') : this._l('bookmark.add', 'Add bookmark')}"
          >
            <builtin-icon name="${this.bookmarked ? 'book-fill' : 'book'}" size="16" variant="outlined"></builtin-icon>
          </button>
        </div>
      </builtin-navbar>
      <article class="article">
        <div class="category">${this.category || ""}</div>
        <h1>${this.title || ""}</h1>
        <div class="author-row">
          ${avatar ? html`<img src="${avatar}" alt="${this.author || ''}" />` : ""}
          <div class="meta">
            <div><strong>${this.author || ""}</strong></div>
            <div>${this.date || ""} · ${this.readTime || ""}</div>
          </div>
        </div>
        ${this.cover ? html`<div class="cover"><img src="${this.cover}" alt="${this.title || ''}" /></div>` : ""}
        <div class="body">
          <p>${this.content || ""}</p>
        </div>
        <div class="tags">
          ${tags.map((t) => html`<builtin-chip text="${t}"></builtin-chip>`)}
        </div>
        <div class="bio">
          ${avatar ? html`<img src="${avatar}" alt="${this.author || ''}" />` : ""}
          <div>
            <div style="font-weight:650;color:var(--builtin-color-text);">${this.author || ""}</div>
            <div style="font-size:13px;color:var(--builtin-color-muted);margin-top:4px;">${author_bio}</div>
          </div>
        </div>
        <div class="related">
          <h3>${this._l("blog.related", "Related Articles")}</h3>
          <div class="related-grid">
            ${related.map((r) => html`
              <div class="rel-card">
                <img src="${r.image || ""}" alt="${r.title || ''}" loading="lazy" />
                <div class="t">${r.title || ""}</div>
              </div>
            `)}
          </div>
        </div>
        <div style="margin-top:32px;">
          <builtin-comment-section comments='[]'></builtin-comment-section>
        </div>
      </article>
      <builtin-footer></builtin-footer>
    `;
  }
}