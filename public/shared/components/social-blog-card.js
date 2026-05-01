/**
 * @fileoverview BuiltinSocialBlogCard — Xiaohongshu/Instagram-style social blog preview card.
 *
 * @attr {string} images — JSON array of image URLs.
 * @attr {string} avatar — Author avatar URL.
 * @attr {string} author — Author name.
 * @attr {string} title — Card title.
 * @attr {string} content — Body text (truncated preview).
 * @attr {number} likes — Like count.
 * @attr {number} comments — Comment count.
 * @attr {number} bookmarks — Bookmark count.
 * @attr {string} tags — JSON array of tag strings.
 * @attr {string} location — Location string.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-like — Detail: { liked }.
 * @event builtin-comment — Detail: {}.
 * @event builtin-bookmark — Detail: { bookmarked }.
 * @event builtin-share — Detail: {}.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinSocialBlogCard extends BuiltinBaseElement {
  static properties = {
    images: { type: Array },
    avatar: { type: String },
    author: { type: String },
    title: { type: String },
    content: { type: String },
    likes: { type: Number },
    comments: { type: Number },
    bookmarks: { type: Number },
    tags: { type: Array },
    location: { type: String },
    heartIcon: { type: String, attribute: "heart-icon" },
    labels: { type: Object },
    _liked: { type: Boolean, state: true },
    _bookmarked: { type: Boolean, state: true },
    _imgIndex: { type: Number, state: true },
    _dblTap: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      overflow: hidden;
    }
    .gallery { position: relative; aspect-ratio: 4 / 3; background: var(--builtin-header-bg, #f9fafb); overflow: hidden; }
    .gallery img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .img-nav {
      position: absolute; top: 50%; transform: translateY(-50%);
      width: 32px; height: 32px; border-radius: 50%;
      background: rgba(0,0,0,0.35); color: #fff; border: none;
      display: inline-flex; align-items: center; justify-content: center;
      cursor: pointer; opacity: 0; transition: opacity .15s ease;
    }
    .gallery:hover .img-nav { opacity: 1; }
    .img-nav.prev { left: 8px; }
    .img-nav.next { right: 8px; }
    .dots {
      position: absolute; bottom: 8px; left: 0; right: 0;
      display: flex; justify-content: center; gap: 6px;
    }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(255,255,255,0.6); cursor: pointer; transition: background .15s ease; }
    .dot.active { background: #ffffff; }
    .heart-anim {
      position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%) scale(0);
      font-size: 64px; color: #fff; text-shadow: 0 2px 10px rgba(0,0,0,0.25);
      animation: heart-pop .5s ease forwards; pointer-events: none;
    }
    @keyframes heart-pop {
      0% { transform: translate(-50%, -50%) scale(0); opacity: 1; }
      50% { transform: translate(-50%, -50%) scale(1.2); opacity: 1; }
      100% { transform: translate(-50%, -50%) scale(1); opacity: 0; }
    }
    .body { padding: 12px; }
    .author-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
    .author-row img { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; }
    .author-name { font-size: 13px; font-weight: 600; color: var(--builtin-color-text, #111827); }
    .title { font-size: 15px; font-weight: 650; margin-bottom: 6px; color: var(--builtin-color-text, #111827); line-height: 1.4; }
    .content { font-size: 13px; color: var(--builtin-color-muted, #6b7280); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .actions { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .action-group { display: flex; align-items: center; gap: 14px; }
    .action {
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 13px; color: var(--builtin-color-muted, #6b7280); cursor: pointer; user-select: none;
      background: transparent; border: none; padding: 0;
    }
    .action:hover { color: var(--builtin-color-text, #111827); }
    .action.active { color: var(--builtin-color-danger, #ef4444); }
    .action.bookmark.active { color: var(--builtin-primary, #2563eb); }
    .tags { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 12px 10px; }
    .tag { font-size: 12px; color: var(--builtin-primary, #2563eb); }
    .loc { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--builtin-color-muted, #6b7280); padding: 0 12px 8px; }
  `;

  constructor() {
    super();
    this.images = [];
    this.avatar = "";
    this.author = "";
    this.title = "";
    this.content = "";
    this.likes = 0;
    this.comments = 0;
    this.bookmarks = 0;
    this.tags = [];
    this.location = "";
    this.heartIcon = "❤";
    this.labels = {};
    this._liked = false;
    this._bookmarked = false;
    this._imgIndex = 0;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _toggleLike() {
    this._liked = !this._liked;
    this.dispatchEvent(new CustomEvent("builtin-like", { bubbles: true, composed: true, detail: { liked: this._liked } }));
  }

  _toggleBookmark() {
    this._bookmarked = !this._bookmarked;
    this.dispatchEvent(new CustomEvent("builtin-bookmark", { bubbles: true, composed: true, detail: { bookmarked: this._bookmarked } }));
  }

  _onDoubleTap() {
    this._dblTap = true;
    if (!this._liked) this._toggleLike();
    setTimeout(() => { this._dblTap = false; }, 600);
  }

  _prevImg() {
    const imgs = this.images || [];
    this._imgIndex = (this._imgIndex - 1 + imgs.length) % Math.max(1, imgs.length);
  }

  _nextImg() {
    const imgs = this.images || [];
    this._imgIndex = (this._imgIndex + 1) % Math.max(1, imgs.length);
  }

  render() {
    const imgs = this.images || [];
    return html`
      <div class="card">
        <div class="gallery" @dblclick="${this._onDoubleTap}">
          ${imgs[this._imgIndex] ? html`<img src="${imgs[this._imgIndex]}" alt="" loading="lazy" />` : ""}
          ${this._dblTap ? html`<div class="heart-anim">${this.heartIcon}</div>` : ""}
          ${imgs.length > 1 ? html`
            <button class="img-nav prev" @click="${(e) => { e.stopPropagation(); this._prevImg(); }}"><builtin-icon name="left" size="16" variant="outlined"></builtin-icon></button>
            <button class="img-nav next" @click="${(e) => { e.stopPropagation(); this._nextImg(); }}"><builtin-icon name="right" size="16" variant="outlined"></builtin-icon></button>
            <div class="dots">
              ${imgs.map((_, i) => html`<div class="dot ${classMap({ active: i === this._imgIndex })}" @click="${(e) => { e.stopPropagation(); this._imgIndex = i; }}"></div>`)}
            </div>
          ` : ""}
        </div>
        <div class="body">
          <div class="author-row">
            ${this.avatar ? html`<img src="${this.avatar}" alt="" />` : html`<builtin-icon name="user" size="28" variant="outlined"></builtin-icon>`}
            <span class="author-name">${this.author || ""}</span>
          </div>
          <div class="title">${this.title || ""}</div>
          <div class="content">${this.content || ""}</div>
        </div>
        ${this.location ? html`
          <div class="loc"><builtin-icon name="environment" size="12" variant="outlined"></builtin-icon>${this.location}</div>
        ` : ""}
        ${this.tags?.length ? html`
          <div class="tags">${this.tags.map((t) => html`<span class="tag">#${t}</span>`)}</div>
        ` : ""}
        <div class="actions">
          <div class="action-group">
            <button class="action ${classMap({ active: this._liked })}" @click="${this._toggleLike}">
              <builtin-icon name="heart" size="18" variant="outlined"></builtin-icon>
              <span>${(this.likes || 0) + (this._liked ? 1 : 0)}</span>
            </button>
            <button class="action" @click="${() => this.dispatchEvent(new CustomEvent('builtin-comment', { bubbles: true, composed: true }))}">
              <builtin-icon name="message" size="18" variant="outlined"></builtin-icon>
              <span>${this.comments || 0}</span>
            </button>
            <button class="action bookmark ${classMap({ active: this._bookmarked })}" @click="${this._toggleBookmark}">
              <builtin-icon name="book" size="18" variant="outlined"></builtin-icon>
              <span>${(this.bookmarks || 0) + (this._bookmarked ? 1 : 0)}</span>
            </button>
          </div>
          <button class="action" @click="${() => this.dispatchEvent(new CustomEvent('builtin-share', { bubbles: true, composed: true }))}">
            <builtin-icon name="share-alt" size="18" variant="outlined"></builtin-icon>
          </button>
        </div>
      </div>
    `;
  }
}
