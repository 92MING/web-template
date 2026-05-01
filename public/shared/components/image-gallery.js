/**
 * @fileoverview BuiltinImageGallery — Image gallery with grid, masonry, and carousel layouts.
 *
 * @element builtin-image-gallery
 *
 * @attr {Object} images — JSON array [{src, thumbnail, caption, alt}]
 * @attr {string} layout — `grid` | `masonry` | `carousel`
 * @attr {number} columns — Number of columns for grid (default 3)
 * @attr {string} mode — `default` | `minimal`
 * @attr {Object} labels — JSON object for i18n overrides
 *
 * @slot caption — Override image caption in lightbox
 * @slot empty — Shown when there are no images
 * @slot toolbar — Extra controls in lightbox header
 *
 * @event builtin-open — Detail: `{ index, image }`
 * @event builtin-close — Detail: `{ index, image }`
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinImageGallery extends BuiltinBaseElement {
  static properties = {
    images: { type: Object },
    layout: { type: String },
    columns: { type: Number },
    mode: { type: String },
    labels: { type: Object },
    _lightboxOpen: { type: Boolean, state: true },
    _lightboxIndex: { type: Number, state: true },
    _loaded: { type: Object, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      color: var(--builtin-color-text, #111827);
    }
    .grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(var(--gallery-columns, 3), 1fr);
    }
    .masonry {
      column-count: var(--gallery-columns, 3);
      column-gap: 12px;
    }
    .masonry .item {
      break-inside: avoid;
      margin-bottom: 12px;
    }
    .carousel {
      display: flex;
      gap: 12px;
      overflow-x: auto;
      scroll-snap-type: x mandatory;
      -webkit-overflow-scrolling: touch;
      padding-bottom: 4px;
    }
    .carousel .item {
      flex: 0 0 auto;
      scroll-snap-align: start;
      width: 70%;
      max-width: 400px;
    }
    .item {
      position: relative;
      border-radius: var(--builtin-radius, 6px);
      overflow: hidden;
      cursor: pointer;
      background: var(--builtin-surface-raised, #f3f4f6);
    }
    .item img {
      display: block;
      width: 100%;
      height: auto;
      object-fit: cover;
      transition: opacity 0.2s ease;
    }
    .item img.lazy {
      opacity: 0;
    }
    .item img.loaded {
      opacity: 1;
    }
    .caption {
      padding: 8px;
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      background: var(--builtin-surface, #ffffff);
    }
    .empty {
      display: flex; align-items: center; justify-content: center;
      min-height: 160px;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 14px;
    }

    /* Lightbox */
    .lightbox {
      position: fixed;
      inset: 0;
      z-index: 1000;
      background: rgba(0,0,0,0.9);
      display: flex;
      flex-direction: column;
    }
    .lightbox-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      color: #fff;
    }
    .lightbox-title {
      font-size: 14px;
      opacity: 0.9;
    }
    .lightbox-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .lb-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px; height: 36px;
      border: none;
      background: rgba(255,255,255,0.15);
      color: #fff;
      border-radius: 50%;
      cursor: pointer;
    }
    .lb-btn:hover { background: rgba(255,255,255,0.25); }
    .lb-btn svg {
      width: 18px; height: 18px;
      stroke: currentColor; fill: none;
      stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;
    }
    .lightbox-body {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      overflow: hidden;
    }
    .lightbox-img {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      user-select: none;
    }
    .lightbox-nav {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      width: 44px; height: 44px;
      border: none;
      background: rgba(255,255,255,0.15);
      color: #fff;
      border-radius: 50%;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .lightbox-nav:hover { background: rgba(255,255,255,0.25); }
    .lightbox-nav.prev { left: 12px; }
    .lightbox-nav.next { right: 12px; }
    .lightbox-nav svg {
      width: 20px; height: 20px;
      stroke: currentColor; fill: none;
      stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;
    }
    .lightbox-footer {
      padding: 12px 16px;
      color: #fff;
      font-size: 13px;
      text-align: center;
    }

    @media (max-width: 720px) {
      .grid { grid-template-columns: repeat(var(--gallery-columns-mobile, 2), 1fr); gap: 8px; }
      .masonry { column-count: var(--gallery-columns-mobile, 2); column-gap: 8px; }
      .masonry .item { margin-bottom: 8px; }
      .carousel .item { width: 85%; }
      .lightbox-nav { width: 40px; height: 40px; }
      .lightbox-nav.prev { left: 4px; }
      .lightbox-nav.next { right: 4px; }
    }
    @media (max-width: 480px) {
      .grid { grid-template-columns: 1fr; }
      .masonry { column-count: 1; }
    }
  `;

  constructor() {
    super();
    this.images = [];
    this.layout = "grid";
    this.columns = 3;
    this.mode = "default";
    this._lightboxOpen = false;
    this._lightboxIndex = 0;
    this._loaded = new Set();
    this._observer = null;
    this._touchStartX = 0;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  get _imageList() {
    return Array.isArray(this.images) ? this.images : [];
  }

  firstUpdated() {
    this._setupLazyLoad();
  }

  updated(changed) {
    if (changed.has("layout") || changed.has("images")) {
      this.updateComplete.then(() => this._setupLazyLoad());
    }
  }

  _setupLazyLoad() {
    if (this._observer) {
      this._observer.disconnect();
    }
    const imgs = this.shadowRoot.querySelectorAll("img.lazy");
    if (!imgs.length) return;
    this._observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          const img = entry.target;
          const src = img.dataset.src;
          if (src) {
            img.src = src;
            img.onload = () => {
              img.classList.add("loaded");
              img.classList.remove("lazy");
            };
            img.onerror = () => {
              img.classList.remove("lazy");
            };
          }
          this._observer.unobserve(img);
        }
      }
    }, { rootMargin: "100px" });
    imgs.forEach((img) => this._observer.observe(img));
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._observer) {
      this._observer.disconnect();
      this._observer = null;
    }
  }

  _openLightbox(index) {
    this._lightboxIndex = index;
    this._lightboxOpen = true;
    const image = this._imageList[index];
    this.dispatchEvent(new CustomEvent("builtin-open", { detail: { index, image }, bubbles: true, composed: true }));
    document.body.style.overflow = "hidden";
  }

  _closeLightbox() {
    const index = this._lightboxIndex;
    const image = this._imageList[index];
    this._lightboxOpen = false;
    this.dispatchEvent(new CustomEvent("builtin-close", { detail: { index, image }, bubbles: true, composed: true }));
    document.body.style.overflow = "";
  }

  _prevImage() {
    const len = this._imageList.length;
    if (!len) return;
    this._lightboxIndex = this._lightboxIndex > 0 ? this._lightboxIndex - 1 : len - 1;
  }

  _nextImage() {
    const len = this._imageList.length;
    if (!len) return;
    this._lightboxIndex = this._lightboxIndex < len - 1 ? this._lightboxIndex + 1 : 0;
  }

  _onKeyDown(e) {
    if (!this._lightboxOpen) return;
    if (e.key === "Escape") this._closeLightbox();
    if (e.key === "ArrowLeft") this._prevImage();
    if (e.key === "ArrowRight") this._nextImage();
  }

  _onTouchStart(e) {
    this._touchStartX = e.changedTouches[0].screenX;
  }

  _onTouchEnd(e) {
    const endX = e.changedTouches[0].screenX;
    const diff = this._touchStartX - endX;
    if (Math.abs(diff) > 40) {
      if (diff > 0) this._nextImage();
      else this._prevImage();
    }
  }

  render() {
    const mode = this.mode || "default";
    const list = this._imageList;
    const layout = this.layout || "grid";
    const columns = this.columns || 3;
    const mobileColumns = Math.max(1, Math.min(columns, 2));

    if (!list.length) {
      return html`
        <div class="wrap">
          <div class="empty"><slot name="empty">${this._l("gallery.noImages", "No images to display")}</slot></div>
        </div>
      `;
    }

    const wrapperStyle = styleMap({
      "--gallery-columns": String(columns),
      "--gallery-columns-mobile": String(mobileColumns),
    });

    const renderItem = (img, index) => {
      const thumb = img.thumbnail || img.src;
      const alt = img.alt || img.caption || "";
      return html`
        <div class="item" @click=${() => this._openLightbox(index)}>
          <img class="lazy" data-src="${thumb}" alt="${alt}" loading="lazy" />
          ${img.caption && mode !== "minimal"
            ? html`<div class="caption">${img.caption}</div>`
            : null}
        </div>
      `;
    };

    return html`
      <div class="wrap" @keydown=${this._onKeyDown} tabindex="-1">
        ${layout === "grid"
          ? html`<div class="grid" style="${wrapperStyle}">${repeat(list, (img, i) => renderItem(img, i))}</div>`
          : layout === "masonry"
            ? html`<div class="masonry" style="${wrapperStyle}">${repeat(list, (img, i) => renderItem(img, i))}</div>`
            : html`<div class="carousel">${repeat(list, (img, i) => renderItem(img, i))}</div>`}

        ${this._lightboxOpen
          ? html`
            <div class="lightbox"
              @click=${(e) => { if (e.target === e.currentTarget) this._closeLightbox(); }}
              @touchstart=${this._onTouchStart}
              @touchend=${this._onTouchEnd}
            >
              <div class="lightbox-header">
                <span class="lightbox-title">${this._lightboxIndex + 1} / ${list.length}</span>
                <div class="lightbox-actions">
                  <slot name="toolbar"></slot>
                  <button class="lb-btn" @click=${this._closeLightbox} aria-label="${this._l("gallery.close", "Close")}">
                    <builtin-icon name="close" size="18" variant="outlined"></builtin-icon>
                  </button>
                </div>
              </div>
              <div class="lightbox-body">
                <button class="lightbox-nav prev" @click=${this._prevImage} aria-label="${this._l("gallery.previous", "Previous")}">
                  <builtin-icon name="left" size="20" variant="outlined"></builtin-icon>
                </button>
                <img class="lightbox-img" src="${list[this._lightboxIndex]?.src || ""}" alt="${list[this._lightboxIndex]?.alt || ""}" />
                <button class="lightbox-nav next" @click=${this._nextImage} aria-label="${this._l("gallery.next", "Next")}">
                  <builtin-icon name="right" size="20" variant="outlined"></builtin-icon>
                </button>
              </div>
              <div class="lightbox-footer">
                <slot name="caption">${list[this._lightboxIndex]?.caption || ""}</slot>
              </div>
            </div>
          `
          : null}
      </div>
    `;
  }
}
