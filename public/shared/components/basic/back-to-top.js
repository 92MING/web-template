import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinBackToTop — Fixed button that smooth-scrolls to top.
 *
 * Attributes:
 *   - threshold: Scroll px to show button (default 300)
 *   - labels: JSON object for i18n overrides
 */
export class BuiltinBackToTop extends BuiltinBaseElement {
  static properties = {
    threshold: { type: Number },
    labels: { type: Object },
    _visible: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .btn {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 900;
      width: 44px;
      height: 44px;
      border-radius: 50%;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      box-shadow: 0 4px 12px rgba(0,0,0,0.1);
      cursor: pointer;
      display: none;
      align-items: center;
      justify-content: center;
      transition: opacity 0.2s ease, transform 0.2s ease;
    }
    .btn.visible {
      display: inline-flex;
    }
    .btn:hover {
      background: var(--builtin-row-hover-bg, #f3f4f6);
      transform: translateY(-2px);
    }
    @media (max-width: 720px) {
      .btn {
        width: 52px;
        height: 52px;
        bottom: 16px;
        right: 16px;
      }
      .btn svg {
        width: 24px;
        height: 24px;
      }
    }
  `;

  constructor() {
    super();
    this.threshold = 300;
    this.labels = {};
    this._visible = false;
    this._onScroll = () => {
      this._visible = window.scrollY > (this.threshold || 300);
    };
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("scroll", this._onScroll, { passive: true });
    this._onScroll();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("scroll", this._onScroll);
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _scrollToTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  render() {
    return html`
      <button
        class="btn ${classMap({ visible: this._visible })}"
        aria-label="${this._l("backToTop.label", "Back to top")}"
        @click="${this._scrollToTop}"
      >
        <builtin-icon name="up" size="20" variant="outlined"></builtin-icon>
      </button>
    `;
  }
}
