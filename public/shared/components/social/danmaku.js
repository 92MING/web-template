/**
 * @fileoverview BuiltinDanmaku - Bilibili-style floating comment overlay.
 *
 * Uses the vendored `danmaku` canvas engine for lane allocation and animation.
 *
 * @attr {Array} comments - JSON array of {id, text, color, size, mode}.
 * @attr {number} speed - Pixels per second (default 120).
 * @attr {string} density - "low" | "normal" | "high" (default "normal").
 * @attr {boolean} paused - Pause animation.
 * @attr {Object} labels - JSON object for i18n overrides.
 *
 * @event builtin-pause - Paused state changed. Detail: { paused }.
 */

import { BuiltinBaseElement, html, css, classMap } from "../lit-base.js";

const DANMAKU_SCRIPT = "/vendor/danmaku/danmaku.canvas.min.js";
let _danmakuLoadPromise = null;

function loadDanmakuScript() {
  if (window.Danmaku) return Promise.resolve(window.Danmaku);
  if (_danmakuLoadPromise) return _danmakuLoadPromise;
  _danmakuLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = DANMAKU_SCRIPT;
    script.onload = () => {
      if (window.Danmaku) resolve(window.Danmaku);
      else reject(new Error("Danmaku library did not expose window.Danmaku"));
    };
    script.onerror = () => reject(new Error("Failed to load Danmaku library"));
    document.head.appendChild(script);
  });
  return _danmakuLoadPromise;
}

export class BuiltinDanmaku extends BuiltinBaseElement {
  static properties = {
    comments: { type: Array },
    speed: { type: Number },
    density: { type: String },
    paused: { type: Boolean },
    labels: { type: Object },
    _draft: { type: String, state: true },
    _error: { type: String, state: true },
  };

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      position: relative;
      overflow: hidden;
      min-height: 120px;
    }
    .stage {
      position: relative;
      flex: 1 1 auto;
      min-height: 0;
      overflow: hidden;
      pointer-events: auto;
      line-height: 1.2;
      font-family: var(--builtin-font-family, Inter, ui-sans-serif, system-ui, sans-serif);
    }
    .stage canvas {
      display: block;
    }
    .bar {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px;
      background: rgba(15, 23, 42, 0.72);
      border-top: 1px solid rgba(255,255,255,0.12);
    }
    .bar input {
      min-width: 0;
      flex: 1;
      height: 32px;
      border: 1px solid rgba(255,255,255,0.18);
      border-radius: var(--builtin-radius, 6px);
      background: rgba(255,255,255,0.10);
      color: #fff;
      padding: 0 10px;
      outline: none;
    }
    .bar input::placeholder { color: rgba(255,255,255,0.62); }
    .bar button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 32px;
      height: 32px;
      padding: 0 10px;
      border: 1px solid rgba(255,255,255,0.18);
      border-radius: var(--builtin-radius, 6px);
      background: rgba(255,255,255,0.12);
      color: #fff;
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 650;
    }
    .bar button.send {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
    }
    .error {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
      color: var(--builtin-color-danger, #b91c1c);
      background: rgba(127, 29, 29, 0.16);
      font-size: 13px;
      text-align: center;
    }
  `;

  constructor() {
    super();
    this.comments = [];
    this.speed = 120;
    this.density = "normal";
    this.paused = false;
    this.labels = {};
    this._draft = "";
    this._error = "";
    this._danmaku = null;
    this._timer = null;
    this._resizeObserver = null;
  }

  async updated(changed) {
    if (changed.has("comments") || changed.has("density") || changed.has("_ptTheme")) {
      await this._initDanmaku();
    } else if (changed.has("speed") && this._danmaku) {
      this._danmaku.speed = Math.max(30, Number(this.speed) || 120);
    }
    if (changed.has("paused")) {
      this._syncPaused();
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._stopEmitter();
    this._destroyDanmaku();
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  async _initDanmaku() {
    const stage = this.shadowRoot?.querySelector(".stage");
    if (!stage) return;
    this._stopEmitter();
    this._destroyDanmaku();
    if (!this.comments?.length) return;

    try {
      const Danmaku = await loadDanmakuScript();
      await this.updateComplete;
      this._danmaku = new Danmaku({
        container: stage,
        engine: "canvas",
        speed: Math.max(30, Number(this.speed) || 120),
      });
      this._error = "";
      this._setupResizeObserver(stage);
      this._syncPaused();
      if (!this.paused) this._scheduleEmit(80);
    } catch (err) {
      this._error = String(err?.message || err);
    }
  }

  _destroyDanmaku() {
    if (!this._danmaku) return;
    try {
      this._danmaku.destroy();
    } catch (_err) {
      // Already destroyed or detached; no user-facing recovery needed.
    }
    this._danmaku = null;
  }

  _setupResizeObserver(stage) {
    if (this._resizeObserver) this._resizeObserver.disconnect();
    if (!("ResizeObserver" in window)) return;
    this._resizeObserver = new ResizeObserver(() => {
      if (this._danmaku) this._danmaku.resize();
    });
    this._resizeObserver.observe(stage);
  }

  _densityDelay() {
    switch (this.density) {
      case "low":
        return 1050;
      case "high":
        return 320;
      default:
        return 620;
    }
  }

  _scheduleEmit(initialDelay = null) {
    this._stopEmitter();
    const delay = initialDelay ?? this._densityDelay() + Math.random() * 320;
    this._timer = setTimeout(() => {
      this._emitOne();
      if (!this.paused) this._scheduleEmit();
    }, delay);
  }

  _stopEmitter() {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
  }

  _emitOne() {
    if (!this._danmaku || this.paused || !this.comments?.length) return;
    const comment = this.comments[Math.floor(Math.random() * this.comments.length)] || {};
    const text = String(comment.text || "").trim();
    if (!text) return;
    const size = this._commentSize(comment.size);
    const color = comment.color || (this._ptTheme === "dark" ? "#e5e7eb" : "#ffffff");
    this._danmaku.emit({
      text,
      mode: comment.mode || "rtl",
      style: {
        font: `600 ${size}px ${this._fontFamily()}`,
        fillStyle: color,
        strokeStyle: "rgba(0, 0, 0, 0.46)",
        lineWidth: 3,
        textBaseline: "bottom",
      },
    });
    if (this._danmaku.comments?.length > 200) {
      this._danmaku.comments.splice(0, this._danmaku.comments.length - 120);
    }
  }

  _fontFamily() {
    return getComputedStyle(this).fontFamily || "Inter, ui-sans-serif, system-ui, sans-serif";
  }

  _commentSize(size) {
    if (size === "sm") return 14;
    if (size === "lg") return 24;
    const n = Number(size);
    if (Number.isFinite(n)) return Math.max(12, Math.min(32, n));
    return 18;
  }

  _syncPaused() {
    if (!this._danmaku) return;
    if (this.paused) {
      this._stopEmitter();
    } else {
      this._danmaku.show();
      this._scheduleEmit(80);
    }
  }

  _togglePaused() {
    this.paused = !this.paused;
    this.dispatchEvent(new CustomEvent("builtin-pause", {
      bubbles: true,
      composed: true,
      detail: { paused: this.paused },
    }));
  }

  _emitText(text) {
    if (!this._danmaku) return;
    const cleanText = String(text || "").trim();
    if (!cleanText) return;
    const comment = { text: cleanText, color: this._ptTheme === "dark" ? "#e5e7eb" : "#ffffff" };
    this._danmaku.show();
    this._danmaku.emit({
      text: comment.text,
      mode: "rtl",
      style: {
        font: `600 18px ${this._fontFamily()}`,
        fillStyle: comment.color,
        strokeStyle: "rgba(0, 0, 0, 0.46)",
        lineWidth: 3,
        textBaseline: "bottom",
      },
    });
    this.dispatchEvent(new CustomEvent("builtin-submit", { bubbles: true, composed: true, detail: comment }));
  }

  _send() {
    const text = this._draft;
    this._draft = "";
    this._emitText(text);
  }

  _onInputKeydown(event) {
    if (event.key === "Enter") this._send();
  }

  render() {
    return html`
      <div
        class="${classMap({ stage: true, paused: this.paused })}"
      ></div>
      <div class="bar">
        <button @click="${this._togglePaused}" title="${this._l("danmaku.clickToPause", "Pause/resume")}">
          <builtin-icon name="${this.paused ? "play-circle" : "pause"}" size="18" variant="outlined"></builtin-icon>
        </button>
        <input
          .value="${this._draft}"
          placeholder="${this._l("danmaku.placeholder", "Send a comment")}" 
          @input="${(event) => { this._draft = event.target.value; }}"
          @keydown="${this._onInputKeydown}"
        />
        <button class="send" @click="${this._send}">${this._l("danmaku.send", "Send")}</button>
      </div>
      ${this._error ? html`<div class="error">${this._error}</div>` : null}
    `;
  }
}
