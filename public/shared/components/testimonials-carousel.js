import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinTestimonialsCarousel — Auto-rotating testimonials carousel.
 *
 * Attributes:
 *   - testimonials: JSON array of { quote, author, role, avatar, rating }
 *   - autoPlay: boolean (default true)
 *   - autoPlayInterval: number (default 5000)
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-change: Fired when active slide changes. Detail: { index }
 */
export class BuiltinTestimonialsCarousel extends BuiltinBaseElement {
  static properties = {
    testimonials: { type: Array },
    autoPlay: { type: Boolean, attribute: "auto-play" },
    autoPlayInterval: { type: Number, attribute: "auto-play-interval" },
    labels: { type: Object },
    _activeIndex: { type: Number, state: true },
  };

  static styles = css`
    :host { display: block; }
    .carousel {
      position: relative;
      overflow: hidden;
    }
    .track {
      display: flex;
      overflow-x: auto;
      scroll-snap-type: x mandatory;
      scroll-behavior: smooth;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }
    .track::-webkit-scrollbar { display: none; }
    .slide {
      flex: 0 0 100%;
      scroll-snap-align: start;
      scroll-snap-stop: always;
      padding: 8px;
    }
    .arrow {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      width: 40px;
      height: 40px;
      border-radius: 50%;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      z-index: 2;
    }
    .arrow:hover { background: var(--builtin-row-hover-bg, #f3f4f6); }
    .arrow.prev { left: 8px; }
    .arrow.next { right: 8px; }
    .dots {
      display: flex;
      justify-content: center;
      gap: 8px;
      padding: 12px 0;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      border: none;
      background: var(--builtin-border, #d1d5db);
      cursor: pointer;
      padding: 0;
    }
    .dot.active { background: var(--builtin-primary, #2563eb); }
    .card-wrap {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      padding: 28px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    .quote-mark {
      font-size: 48px;
      line-height: 1;
      color: var(--builtin-primary, #2563eb);
      font-family: Georgia, serif;
    }
    .quote-text {
      font-size: 16px;
      line-height: 1.6;
      color: var(--builtin-color-text, #111827);
    }
    .author-row {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .avatar {
      width: 52px;
      height: 52px;
      border-radius: 50%;
      object-fit: cover;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .fallback {
      width: 52px;
      height: 52px;
      border-radius: 50%;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
      font-size: 18px;
    }
    .author-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .author-name {
      font-weight: 650;
      color: var(--builtin-color-text, #111827);
    }
    .author-role {
      font-size: 13px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .stars {
      display: flex;
      gap: 3px;
      font-size: 18px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .star {
      display: inline-flex;
      color: #f59e0b;
    }
    .star.empty {
      color: var(--builtin-border, #d1d5db);
    }
    @media (max-width: 720px) {
      .arrow { display: none; }
      .dot { width: 10px; height: 10px; }
      .card-wrap { padding: 18px; gap: 12px; }
      .quote-mark { font-size: 36px; }
      .avatar, .fallback { width: 42px; height: 42px; font-size: 15px; }
      .quote-text { font-size: 15px; }
    }
  `;

  constructor() {
    super();
    this.testimonials = [];
    this.autoPlay = true;
    this.autoPlayInterval = 5000;
    this.labels = {};
    this._activeIndex = 0;
    this._timer = null;
    this._avatarErrors = new Set();
  }

  connectedCallback() {
    super.connectedCallback();
    this._startAutoPlay();
    this._onScroll = () => {
      const track = this.shadowRoot?.querySelector(".track");
      if (!track) return;
      const idx = Math.round(track.scrollLeft / track.clientWidth);
      if (idx !== this._activeIndex) {
        this._activeIndex = idx;
        this.dispatchEvent(
          new CustomEvent("builtin-change", { bubbles: true, composed: true, detail: { index: idx } })
        );
      }
    };
    this.updateComplete.then(() => {
      const track = this.shadowRoot?.querySelector(".track");
      if (track) track.addEventListener("scroll", this._onScroll, { passive: true });
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._stopAutoPlay();
    const track = this.shadowRoot?.querySelector(".track");
    if (track) track.removeEventListener("scroll", this._onScroll);
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _startAutoPlay() {
    if (!this.autoPlay) return;
    this._stopAutoPlay();
    this._timer = setInterval(() => {
      this._goTo(this._activeIndex + 1);
    }, Math.max(1000, this.autoPlayInterval || 5000));
  }

  _stopAutoPlay() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  _goTo(index) {
    const track = this.shadowRoot?.querySelector(".track");
    if (!track) return;
    const count = (this.testimonials || []).length;
    if (!count) return;
    const clamped = ((index % count) + count) % count;
    track.scrollTo({ left: track.clientWidth * clamped, behavior: "smooth" });
  }

  _onArrowClick(delta) {
    this._stopAutoPlay();
    this._goTo(this._activeIndex + delta);
    this._startAutoPlay();
  }

  _onDotClick(idx) {
    this._stopAutoPlay();
    this._goTo(idx);
    this._startAutoPlay();
  }

  _initials(name) {
    return (name || "")
      .split(" ")
      .map((n) => n[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }

  _renderStars(rating) {
    const r = Math.max(0, Math.min(5, Math.round(rating) || 0));
    const stars = [];
    for (let i = 0; i < 5; i++) {
      const filled = i < r;
      stars.push(html`
        <span class="star ${filled ? "" : "empty"}">
          <builtin-icon name="star" size="20" variant="outlined"></builtin-icon>
        </span>
      `);
    }
    return stars;
  }

  render() {
    const t = this.testimonials || [];
    const count = t.length;

    return html`
      <div class="carousel">
        <div class="track" role="region" aria-roledescription="carousel">
          ${repeat(
            t,
            (_, i) => i,
            (item, idx) => html`
              <div class="slide">
                <div class="card-wrap">
                  <div class="quote-mark">&ldquo;</div>
                  ${item.quote ? html`<div class="quote-text">${item.quote}</div>` : ""}
                  <div class="author-row">
                    ${item.avatar && !this._avatarErrors.has(idx)
                      ? html`<img
                          class="avatar"
                          src="${item.avatar}"
                          alt="${item.author || ""}"
                          @error="${() => { this._avatarErrors.add(idx); this.requestUpdate(); }}"
                        />`
                      : ""}
                    ${!item.avatar || this._avatarErrors.has(idx)
                      ? html`<span class="fallback">${this._initials(item.author)}</span>`
                      : ""}
                    <div class="author-info">
                      ${item.author ? html`<div class="author-name">${item.author}</div>` : ""}
                      ${item.role ? html`<div class="author-role">${item.role}</div>` : ""}
                    </div>
                  </div>
                  <div class="stars" aria-label="${this._l("testimonial.rating", "Rating")}">
                    ${this._renderStars(item.rating)}
                  </div>
                </div>
              </div>
            `
          )}
        </div>
        ${count > 1 ? html`
          <button class="arrow prev" aria-label="${this._l("carousel.prev", "Previous")}" @click="${() => this._onArrowClick(-1)}">
            <builtin-icon name="left" size="20" variant="outlined"></builtin-icon>
          </button>
          <button class="arrow next" aria-label="${this._l("carousel.next", "Next")}" @click="${() => this._onArrowClick(1)}">
            <builtin-icon name="right" size="20" variant="outlined"></builtin-icon>
          </button>
        ` : ""}
      </div>
      ${count > 1 ? html`
        <div class="dots">
          ${Array.from({ length: count }, (_, i) => html`
            <button
              class="dot ${classMap({ active: i === this._activeIndex })}"
              aria-label="${this._l("carousel.goTo", "Go to slide")} ${i + 1}"
              @click="${() => this._onDotClick(i)}"
            ></button>
          `)}
        </div>
      ` : ""}
    `;
  }
}
