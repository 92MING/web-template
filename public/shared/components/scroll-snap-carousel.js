import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinScrollSnapCarousel — CSS scroll-snap horizontal carousel.
 *
 * Attributes:
 *   - items: JSON array of slide objects { id, content, image }
 *   - autoPlay: boolean
 *   - autoPlayInterval: number (default 4000)
 *   - labels: JSON object for i18n overrides
 *
 * Slots:
 *   - default: Slotted children (used when items is empty)
 *
 * Events:
 *   - builtin-change: Fired when active slide changes. Detail: { index }
 */
export class BuiltinScrollSnapCarousel extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
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
    }
    .slide-content {
      padding: 8px;
    }
    .slide img {
      width: 100%;
      height: auto;
      border-radius: var(--builtin-radius-lg, 8px);
      display: block;
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
    @media (max-width: 720px) {
      .arrow { display: none; }
      .dot { width: 10px; height: 10px; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.autoPlay = false;
    this.autoPlayInterval = 4000;
    this.labels = {};
    this._activeIndex = 0;
    this._timer = null;
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
    }, Math.max(1000, this.autoPlayInterval || 4000));
  }

  _stopAutoPlay() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  _goTo(index) {
    const track = this.shadowRoot?.querySelector(".track");
    if (!track) return;
    const count = this._slideCount();
    const clamped = ((index % count) + count) % count;
    track.scrollTo({ left: track.clientWidth * clamped, behavior: "smooth" });
  }

  _slideCount() {
    return (this.items && this.items.length) || this.querySelectorAll("[data-slide]").length || this.children.length || 0;
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

  render() {
    const useItems = this.items && this.items.length > 0;
    const count = useItems ? this.items.length : Math.max(1, this._slideCount());

    return html`
      <div class="carousel">
        <div class="track" role="region" aria-roledescription="carousel">
          ${useItems
            ? repeat(
                this.items,
                (it) => it.id || it,
                (it) => html`
                  <div class="slide">
                    <div class="slide-content">
                      ${it.image ? html`<img src="${it.image}" alt="${it.alt || ""}" loading="lazy" />` : ""}
                      ${it.content ? html`<div>${it.content}</div>` : ""}
                    </div>
                  </div>
                `
              )
            : html`<slot></slot>`}
        </div>
        <button class="arrow prev" aria-label="${this._l("carousel.prev", "Previous")}" @click="${() => this._onArrowClick(-1)}">
          <builtin-icon name="left" size="20" variant="outlined"></builtin-icon>
        </button>
        <button class="arrow next" aria-label="${this._l("carousel.next", "Next")}" @click="${() => this._onArrowClick(1)}">
          <builtin-icon name="right" size="20" variant="outlined"></builtin-icon>
        </button>
      </div>
      <div class="dots">
        ${Array.from({ length: count }, (_, i) => html`
          <button
            class="dot ${classMap({ active: i === this._activeIndex })}"
            aria-label="${this._l("carousel.goTo", "Go to slide")} ${i + 1}"
            @click="${() => this._onDotClick(i)}"
          ></button>
        `)}
      </div>
    `;
  }
}
