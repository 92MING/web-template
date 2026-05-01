/**
 * @fileoverview Word cloud component using wordcloud2.js.
 *
 * Renders an interactive tag cloud on a canvas element.
 *
 * Attributes:
 *   words        - JSON array of [word, weight] pairs, e.g. '["foo", 12], ["bar", 6]]'
 *   shape        - Word placement shape: "circle" | "cardioid" | "diamond" | "square" |
 *                  "triangle" | "triangle-forward" | "pentagon" | "star"
 *   font-family  - Font family for words
 *   clickable    - Whether to emit click events
 *
 * Events:
 *   builtin-word-click - Fired when a word is clicked. detail: { word, weight }
 */

import { BuiltinBaseElement, html, css } from "./lit-base.js";
import "../../vendor/wordcloud2/wordcloud2.min.js";

export class BuiltinWordCloud extends BuiltinBaseElement {
  static get properties() {
    return {
      words: { type: String },
      shape: { type: String },
      fontFamily: { type: String, attribute: "font-family" },
      clickable: { type: Boolean },
      _ptTheme: { type: String, state: true },
      _canvasSize: { type: Object, state: true },
    };
  }

  static get styles() {
    return css`
      :host { display: block; }
      .cloud-wrap {
        position: relative;
        width: 100%;
        height: 100%;
        min-height: 200px;
      }
      canvas {
        display: block;
        width: 100%;
        height: 100%;
      }
    `;
  }

  constructor() {
    super();
    this.words = "[]";
    this.shape = "circle";
    this.fontFamily = "";
    this.clickable = false;
    this._resizeObserver = null;
    this._pendingRender = false;
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
  }

  firstUpdated() {
    this._observeSize();
    this._scheduleRender();
  }

  updated(changed) {
    if (changed.has("words") || changed.has("shape") || changed.has("fontFamily") || changed.has("clickable") || changed.has("_ptTheme")) {
      this._scheduleRender();
    }
  }

  _observeSize() {
    const wrap = this.shadowRoot.querySelector(".cloud-wrap");
    if (!wrap || !window.ResizeObserver) return;
    this._resizeObserver = new ResizeObserver(() => {
      this._scheduleRender();
    });
    this._resizeObserver.observe(wrap);
  }

  _scheduleRender() {
    if (this._pendingRender) return;
    this._pendingRender = true;
    requestAnimationFrame(() => {
      this._pendingRender = false;
      this._renderCloud();
    });
  }

  _parseWords() {
    try {
      const parsed = JSON.parse(this.words);
      if (Array.isArray(parsed)) return parsed;
    } catch {
      // fall through
    }
    return [];
  }

  _renderCloud() {
    const wrap = this.shadowRoot.querySelector(".cloud-wrap");
    const canvas = this.shadowRoot.querySelector("canvas");
    if (!wrap || !canvas || !window.WordCloud) return;

    const list = this._parseWords();
    if (!list.length) return;

    const rect = wrap.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.floor(rect.width));
    const h = Math.max(1, Math.floor(rect.height));

    // Resize canvas for crisp rendering
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";

    const isDark = this._ptTheme === "dark";
    const baseColor = isDark ? "random-light" : "random-dark";
    const bgColor = isDark ? "#1f2937" : "#ffffff";

    const options = {
      list,
      shape: this.shape,
      fontFamily: this.fontFamily || 'Inter, "Heiti TC", "Microsoft JhengHei", sans-serif',
      color: baseColor,
      backgroundColor: bgColor,
      clearCanvas: true,
      gridSize: Math.max(4, Math.floor(Math.min(w, h) / 40)),
      weightFactor: (size) => {
        const max = Math.max(...list.map((i) => (Array.isArray(i) ? i[1] : i.weight)));
        if (!max) return 10;
        return (size / max) * Math.min(w, h) * 0.15 + 10;
      },
      minSize: 10,
      rotateRatio: 0.2,
      ellipticity: 1,
    };

    if (this.clickable) {
      options.click = (item) => {
        const word = Array.isArray(item) ? item[0] : item.word;
        const weight = Array.isArray(item) ? item[1] : item.weight;
        this.dispatchEvent(
          new CustomEvent("builtin-word-click", {
            detail: { word, weight },
            bubbles: true,
            composed: true,
          })
        );
      };
    }

    WordCloud(canvas, options);
  }

  render() {
    return html`
      <div class="cloud-wrap">
        <canvas></canvas>
      </div>
    `;
  }
}
