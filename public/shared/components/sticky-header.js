import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinStickyHeader — Header that shrinks and gains shadow/blur on scroll.
 *
 * Attributes:
 *   - threshold: Scroll px to trigger shrink (default 50)
 *   - blur: boolean — enable backdrop-filter blur
 *   - labels: JSON object for i18n overrides
 *
 * Slots:
 *   - default: Header content
 */
export class BuiltinStickyHeader extends BuiltinBaseElement {
  static properties = {
    threshold: { type: Number },
    blur: { type: Boolean },
    labels: { type: Object },
    _shrunk: { type: Boolean, state: true },
  };

  static styles = css`
    :host {
      display: block;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .header {
      background: var(--builtin-surface, #ffffff);
      transition: height 0.25s ease, box-shadow 0.25s ease, background 0.25s ease;
      height: 80px;
      display: flex;
      align-items: center;
    }
    .header.shrunk {
      height: 56px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }
    .header.blur {
      background: rgba(255,255,255,0.75);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
    }
    .header.blur.shrunk {
      background: rgba(255,255,255,0.85);
    }
    .content {
      width: 100%;
      padding: 0 18px;
    }
    @media (max-width: 720px) {
      .header { height: 64px; }
      .header.shrunk { height: 52px; }
      .content { padding: 0 12px; }
    }
  `;

  constructor() {
    super();
    this.threshold = 50;
    this.blur = false;
    this.labels = {};
    this._shrunk = false;
    this._onScroll = () => {
      this._shrunk = window.scrollY > (this.threshold || 50);
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

  render() {
    return html`
      <div class="header ${classMap({ shrunk: this._shrunk, blur: this.blur })}">
        <div class="content">
          <slot></slot>
        </div>
      </div>
    `;
  }
}
