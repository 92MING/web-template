/**
 * @fileoverview BuiltinCarousel — Smooth transform-based carousel with multi-slide support (Lit).
 *
 * @attr {string} items — JSON array of slide objects { id, content, image, alt }.
 * @attr {number} visible — Number of visible slides (default 1).
 * @attr {number} gap — Gap between slides in px (default 16).
 * @attr {boolean} loop — Enable infinite loop (default false).
 * @attr {boolean} autoPlay — Enable auto-play (default false).
 * @attr {number} autoPlayInterval — Interval in ms (default 4000).
 * @attr {boolean} showDots — Show dot indicators (default true).
 * @attr {boolean} showArrows — Show arrow buttons (default true).
 * @attr {boolean} draggable — Enable mouse/touch drag (default true).
 *
 * @slots
 *   - default: Slotted children (used when items is empty)
 *
 * @events
 *   - builtin-change: Fired when active slide changes. Detail: { index }
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinCarousel extends BuiltinBaseElement {
  static properties = {
    items: { type: Array },
    visible: { type: Number },
    gap: { type: Number },
    loop: { type: Boolean },
    autoPlay: { type: Boolean, attribute: "auto-play" },
    autoPlayInterval: { type: Number, attribute: "auto-play-interval" },
    showDots: { type: Boolean, attribute: "show-dots" },
    showArrows: { type: Boolean, attribute: "show-arrows" },
    draggable: { type: Boolean },
    transition: { type: String },
    labels: { type: Object },
    _activeIndex: { type: Number, state: true },
  };

  static styles = css`
    :host { display: block; }
    .carousel { position: relative; overflow: hidden; }
    .track {
      display: flex;
      transition: transform .35s cubic-bezier(.4, 0, .2, 1);
      will-change: transform;
    }
    .slide {
      flex-shrink: 0;
      box-sizing: border-box;
    }
    .slide img {
      width: 100%;
      height: auto;
      border-radius: var(--builtin-radius-lg, 8px);
      display: block;
      object-fit: cover;
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
      transition: background .15s ease, opacity .15s ease;
    }
    .arrow:hover { background: var(--builtin-row-hover-bg, #f3f4f6); }
    .arrow.disabled { opacity: .35; cursor: not-allowed; }
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
      transition: background .2s ease, transform .2s ease, width .2s ease;
    }
    .dot.active { background: var(--builtin-primary, #2563eb); transform: scale(1.15); }
    .dot-bar {
      width: 16px;
      height: 4px;
      border-radius: 999px;
    }
    .dot-bar.active { width: 24px; }
    .fade .slide {
      position: absolute;
      inset: 0;
      opacity: 0;
      transition: opacity .4s ease;
    }
    .fade .slide.active { opacity: 1; z-index: 1; }
    .fade .track { position: relative; }
    @media (max-width: 720px) {
      .arrow { display: none; }
      .dot { width: 10px; height: 10px; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.visible = 1;
    this.gap = 16;
    this.loop = false;
    this.autoPlay = false;
    this.autoPlayInterval = 4000;
    this.showDots = true;
    this.showArrows = true;
    this.draggable = true;
    this.transition = "slide";
    this.labels = {};
    this._activeIndex = 0;
    this._timer = null;
    this._dragStartX = 0;
    this._dragCurrentX = 0;
    this._isDragging = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this._startAutoPlay();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._stopAutoPlay();
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _slideCount() {
    if (this.items && this.items.length > 0) return this.items.length;
    return Math.max(1, this.querySelectorAll("[data-slide]").length || this.children.length);
  }

  _maxIndex() {
    const count = this._slideCount();
    const visible = Math.max(1, Number(this.visible) || 1);
    if (this.loop) return Math.max(0, count - 1);
    return Math.max(0, count - visible);
  }

  _canGoPrev() {
    return this.loop || this._activeIndex > 0;
  }

  _canGoNext() {
    return this.loop || this._activeIndex < this._maxIndex();
  }

  _goTo(index) {
    const max = this._maxIndex();
    let target = index;
    if (this.loop) {
      const count = this._slideCount();
      target = ((index % count) + count) % count;
    } else {
      target = Math.max(0, Math.min(max, index));
    }
    if (target !== this._activeIndex) {
      this._activeIndex = target;
      this.dispatchEvent(
        new CustomEvent("builtin-change", { bubbles: true, composed: true, detail: { index: target } })
      );
    }
  }

  _dotCount() {
    const count = this._slideCount();
    if (this.loop) return count;
    const visible = Math.max(1, Number(this.visible) || 1);
    return Math.max(1, count - visible + 1);
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

  _startAutoPlay() {
    if (!this.autoPlay) return;
    this._stopAutoPlay();
    this._timer = setInterval(() => {
      const max = this._maxIndex();
      if (this.loop || this._activeIndex < max) {
        this._goTo(this._activeIndex + 1);
      } else if (this.loop) {
        this._goTo(0);
      }
    }, Math.max(1000, this.autoPlayInterval || 4000));
  }

  _stopAutoPlay() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  _onPointerDown(e) {
    if (!this.draggable) return;
    this._isDragging = true;
    this._dragStartX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
    this._dragCurrentX = this._dragStartX;
    this._stopAutoPlay();
  }

  _onPointerMove(e) {
    if (!this._isDragging || !this.draggable) return;
    this._dragCurrentX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
  }

  _onPointerUp() {
    if (!this._isDragging || !this.draggable) return;
    const diff = this._dragStartX - this._dragCurrentX;
    const threshold = 40;
    if (diff > threshold) {
      this._goTo(this._activeIndex + 1);
    } else if (diff < -threshold) {
      this._goTo(this._activeIndex - 1);
    }
    this._isDragging = false;
    this._startAutoPlay();
  }

  render() {
    const useItems = this.items && this.items.length > 0;
    const count = this._slideCount();
    const visible = Math.max(1, Number(this.visible) || 1);
    const gap = Number(this.gap) || 0;
    const widthPct = 100 / visible;
    const gapPx = `${gap}px`;
    const isFade = this.transition === "fade";
    const transformOffset = this._activeIndex * widthPct;

    const allItems = useItems ? this.items : [];
    const loopCloneCount = (this.loop && !isFade) ? Math.max(0, visible - 1) : 0;
    const displayItems = loopCloneCount ? [...allItems, ...allItems.slice(0, loopCloneCount)] : allItems;

    const trackStyle = isFade ? {} : {
      transform: `translateX(-${transformOffset}%)`,
      gap: gapPx,
    };

    const renderSlide = (it, idx) => {
      const isActive = idx === this._activeIndex;
      if (isFade) {
        return html`
          <div class="slide ${classMap({ active: isActive })}" style="width: 100%">
            ${it.image ? html`<img src="${it.image}" alt="${it.alt || ""}" loading="lazy" draggable="false" />` : ""}
            ${it.content ? html`<div>${it.content}</div>` : ""}
          </div>
        `;
      }
      return html`
        <div class="slide" style="width: ${widthPct}%">
          ${it.image ? html`<img src="${it.image}" alt="${it.alt || ""}" loading="lazy" draggable="false" />` : ""}
          ${it.content ? html`<div>${it.content}</div>` : ""}
        </div>
      `;
    };

    return html`
      <div
        class="carousel ${isFade ? "fade" : ""}"
        @mousedown="${this._onPointerDown}"
        @mousemove="${this._onPointerMove}"
        @mouseup="${this._onPointerUp}"
        @mouseleave="${this._onPointerUp}"
        @touchstart="${this._onPointerDown}"
        @touchmove="${this._onPointerMove}"
        @touchend="${this._onPointerUp}"
      >
        <div class="track" style="${styleMap(trackStyle)}" role="region" aria-roledescription="carousel">
          ${useItems
            ? repeat(displayItems, (it, i) => `${it.id || it}-${i}`, (it, i) => renderSlide(it, i))
            : html`<slot></slot>`}
        </div>
        ${this.showArrows && count > (isFade ? 1 : visible) ? html`
          <button
            class="arrow prev ${classMap({ disabled: !this._canGoPrev() })}"
            aria-label="${this._l("carousel.prev", "Previous")}"
            @click="${() => this._onArrowClick(-1)}"
          >
            <builtin-icon name="left" size="20" variant="outlined"></builtin-icon>
          </button>
          <button
            class="arrow next ${classMap({ disabled: !this._canGoNext() })}"
            aria-label="${this._l("carousel.next", "Next")}"
            @click="${() => this._onArrowClick(1)}"
          >
            <builtin-icon name="right" size="20" variant="outlined"></builtin-icon>
          </button>
        ` : ""}
      </div>
      ${this.showDots && count > (isFade ? 1 : visible) ? html`
        <div class="dots">
          ${Array.from({ length: this._dotCount() }, (_, i) => html`
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
