import { BuiltinBaseElement, html, css, unsafeHTML } from "../lit-base.js";

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
    arrowVariant: { type: String, attribute: "arrow-variant" },
    dotVariant: { type: String, attribute: "dot-variant" },
    labels: { type: Object },
    _index: { type: Number, state: true },
    _viewportWidth: { type: Number, state: true },
    _dragOffset: { type: Number, state: true },
    _dragging: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display:block; }
    * { box-sizing: border-box; }
    .carousel {
      position: relative;
      width: 100%;
      min-height: var(--builtin-carousel-height, 260px);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      background: var(--builtin-header-bg, #f9fafb);
      color: var(--builtin-color-text, #111827);
      touch-action: pan-y;
    }
    .viewport { width: 100%; min-height: inherit; overflow: hidden; }
    .track {
      display: flex;
      min-height: inherit;
      gap: var(--builtin-carousel-gap, 16px);
      transition: transform 420ms cubic-bezier(.22, .61, .36, 1);
      will-change: transform;
    }
    .track.none { transition: none; }
    .track.fade { display: block; position: relative; transform: none !important; }
    .track.dragging { transition: none; cursor: grabbing; }
    .item {
      flex: 0 0 calc((100% - (var(--builtin-visible, 1) - 1) * var(--builtin-carousel-gap, 16px)) / var(--builtin-visible, 1));
      min-width: 0;
      min-height: var(--builtin-carousel-height, 260px);
    }
    .track.fade .item {
      position: absolute;
      inset: 0;
      opacity: 0;
      pointer-events: none;
      transition: opacity 320ms ease;
    }
    .track.fade .item.active { opacity: 1; pointer-events: auto; }
    .slide {
      position: relative;
      width: 100%;
      min-height: var(--builtin-carousel-height, 260px);
      display: grid;
      place-items: center;
      overflow: hidden;
      border-radius: var(--builtin-radius-lg, 8px);
      background: linear-gradient(135deg, #dbeafe, #f8fafc 48%, #dcfce7);
      color: #0f172a;
    }
    .slide img {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      object-fit: cover;
    }
    .fallback { position: relative; z-index: 0; font-weight: 700; padding: 24px; text-align: center; }
    img[hidden] { display: none; }
    .nav {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      width: 36px;
      height: 36px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 70%, transparent);
      border-radius: 999px;
      background: color-mix(in srgb, var(--builtin-surface, #fff) 86%, transparent);
      color: var(--builtin-primary, #2563eb);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      z-index: 2;
      box-shadow: 0 8px 20px rgba(15, 23, 42, .14);
    }
    .nav:hover { background: var(--builtin-surface, #fff); }
    .nav.prev { left: 12px; }
    .nav.next { right: 12px; }
    .nav.edge {
      top: 0;
      bottom: 0;
      width: 44px;
      height: auto;
      border-radius: 0;
      transform: none;
      background: color-mix(in srgb, var(--builtin-surface, #fff) 64%, transparent);
      box-shadow: none;
    }
    .nav.edge.prev { left: 0; }
    .nav.edge.next { right: 0; }
    .nav.minimal {
      border-color: transparent;
      background: rgba(15, 23, 42, .34);
      color: #fff;
      box-shadow: none;
    }
    .dots {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 12px;
      display: flex;
      justify-content: center;
      gap: 7px;
      z-index: 2;
    }
    .dot {
      width: 8px;
      height: 8px;
      border: 0;
      border-radius: 999px;
      background: rgba(255, 255, 255, .72);
      box-shadow: 0 0 0 1px rgba(15, 23, 42, .14);
      cursor: pointer;
      padding: 0;
    }
    .dot.active { width: 22px; background: var(--builtin-primary, #2563eb); }
    .dots.line .dot { width: 24px; height: 3px; border-radius: 999px; }
    .dots.line .dot.active { width: 36px; }
    .dots.numbered { bottom: 10px; gap: 4px; }
    .dots.numbered .dot {
      width: auto;
      min-width: 24px;
      height: 22px;
      border-radius: 999px;
      color: #0f172a;
      font-size: 11px;
      font-weight: 700;
      background: rgba(255, 255, 255, .78);
    }
    .dots.numbered .dot.active { color: #fff; background: var(--builtin-primary, #2563eb); }
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
    this.arrowVariant = "floating";
    this.dotVariant = "pill";
    this._index = 0;
    this._viewportWidth = 0;
    this._dragOffset = 0;
    this._dragging = false;
    this._timer = null;
    this._dragStart = null;
    this._resizeObserver = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this._syncAutoplay();
  }

  disconnectedCallback() {
    this._stopAutoplay();
    this._resizeObserver?.disconnect?.();
    this._resizeObserver = null;
    super.disconnectedCallback();
  }

  firstUpdated() {
    const viewport = this.renderRoot.querySelector(".viewport");
    if (!viewport) return;
    this._resizeObserver = new ResizeObserver(() => this._measureViewport());
    this._resizeObserver.observe(viewport);
    this._measureViewport();
  }

  updated(changed) {
    if (changed.has("autoPlay") || changed.has("autoPlayInterval") || changed.has("items")) this._syncAutoplay();
    if (changed.has("items") || changed.has("visible")) this._index = Math.min(this._index, this._maxIndex());
    if (changed.has("visible") || changed.has("gap")) this._measureViewport();
  }

  _measureViewport() {
    const viewport = this.renderRoot.querySelector(".viewport");
    const width = viewport?.clientWidth || this.clientWidth || 0;
    if (width && Math.abs(width - this._viewportWidth) > 0.5) this._viewportWidth = width;
  }

  _slides() {
    return Array.isArray(this.items) && this.items.length
      ? this.items
      : Array.from(this.children).map((child, index) => ({ id: index, content: child.innerHTML }));
  }

  _maxIndex() {
    return Math.max(0, this._slides().length - Math.max(1, Number(this.visible) || 1));
  }

  _go(index) {
    const max = this._maxIndex();
    let next = index;
    if (this.loop) next = max <= 0 ? 0 : (index + max + 1) % (max + 1);
    else next = Math.min(max, Math.max(0, index));
    if (next === this._index) return;
    this._index = next;
    this.dispatchEvent(new CustomEvent("builtin-change", { bubbles: true, composed: true, detail: { index: next } }));
  }

  _next() { this._go(this._index + 1); }
  _prev() { this._go(this._index - 1); }

  _syncAutoplay() {
    this._stopAutoplay();
    if (!this.autoPlay || this._slides().length <= 1) return;
    this._timer = window.setInterval(() => this._next(), Math.max(1200, Number(this.autoPlayInterval) || 4000));
  }

  _stopAutoplay() {
    if (this._timer) window.clearInterval(this._timer);
    this._timer = null;
  }

  _onPointerDown(event) {
    if (!this.draggable) return;
    if (event.target.closest?.("button, a, input, select, textarea")) return;
    this._stopAutoplay();
    this._dragging = true;
    this._dragStart = { x: event.clientX, width: this.getBoundingClientRect().width || 1 };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  _onPointerMove(event) {
    if (!this._dragging || !this._dragStart) return;
    this._dragOffset = event.clientX - this._dragStart.x;
  }

  _onPointerUp() {
    if (!this._dragging || !this._dragStart) return;
    const threshold = Math.min(120, this._dragStart.width * 0.18);
    if (this._dragOffset < -threshold) this._next();
    if (this._dragOffset > threshold) this._prev();
    this._dragging = false;
    this._dragStart = null;
    this._dragOffset = 0;
    this._syncAutoplay();
  }

  render() {
    const slides = this._slides();
    const visible = Math.max(1, Number(this.visible) || 1);
    const gap = Math.max(0, Number(this.gap) || 16);
    const step = this._viewportWidth ? (this._viewportWidth + gap) / visible : 0;
    const translate = `${Math.round((-this._index * step + this._dragOffset) * 1000) / 1000}px`;
    const transition = this.transition || "slide";
    const useFade = transition === "fade" && visible === 1;
    const trackClass = `${this._dragging ? "dragging" : ""} ${useFade ? "fade" : transition === "none" ? "none" : ""}`;
    const arrowVariant = this.arrowVariant || "floating";
    const dotVariant = this.dotVariant || "pill";
    return html`
      <div class="carousel" style="--builtin-visible:${visible};--builtin-carousel-gap:${gap}px" @pointerdown=${this._onPointerDown} @pointermove=${this._onPointerMove} @pointerup=${this._onPointerUp} @pointercancel=${this._onPointerUp}>
        <div class="viewport">
          <div class="track ${trackClass}" style=${useFade ? "" : `transform:translateX(${translate})`}>
            ${slides.map((item, index) => html`<div class="item ${useFade && index === this._index ? "active" : ""}" data-index=${index}><div class="slide">${item.image ? html`<span class="fallback">${item.alt || item.title || "Slide"}</span><img src="${item.image}" alt="${item.alt || ""}" loading="lazy" @error=${(event) => { event.currentTarget.hidden = true; }}>` : html`<div class="fallback">${unsafeHTML(item.content || "")}</div>`}</div></div>`)}
          </div>
        </div>
        ${this.showArrows && slides.length > visible ? html`
          <button class="nav prev ${arrowVariant}" type="button" @pointerdown=${(event) => event.stopPropagation()} @click=${(event) => { event.stopPropagation(); this._prev(); }} aria-label="Previous"><builtin-icon name="left" size="18" variant="outlined"></builtin-icon></button>
          <button class="nav next ${arrowVariant}" type="button" @pointerdown=${(event) => event.stopPropagation()} @click=${(event) => { event.stopPropagation(); this._next(); }} aria-label="Next"><builtin-icon name="right" size="18" variant="outlined"></builtin-icon></button>
        ` : ""}
        ${this.showDots && slides.length > visible ? html`<div class="dots ${dotVariant}">${Array.from({ length: this._maxIndex() + 1 }, (_, index) => html`<button class="dot ${index === this._index ? "active" : ""}" type="button" @pointerdown=${(event) => event.stopPropagation()} @click=${(event) => { event.stopPropagation(); this._go(index); }} aria-label="Slide ${index + 1}">${dotVariant === "numbered" ? index + 1 : ""}</button>`)}</div>` : ""}
      </div>
      <slot style="display:none"></slot>
    `;
  }
}