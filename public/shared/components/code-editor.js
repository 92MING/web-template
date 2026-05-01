/**
 * @fileoverview BuiltinCodeEditor — Textarea-based code editor with line numbers, syntax highlight, and copy.
 *
 * @element builtin-code-editor
 *
 * @attr {string} value — Source code.
 * @attr {string} language — Highlight language. Default `javascript`.
 * @attr {boolean} line-numbers — Show line numbers.
 * @attr {Object} labels — i18n overrides.
 *
 * @event builtin-change — Fired on edit. Detail: `{ value }`.
 */

import { BuiltinBaseElement, html, css, classMap, unsafeHTML } from "./lit-base.js";

let _hljsLoadPromise = null;
function _ensureHljs() {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (window.hljs) return Promise.resolve(window.hljs);
  if (_hljsLoadPromise) return _hljsLoadPromise;
  _hljsLoadPromise = new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = "/vendor/highlight/highlight.js";
    s.async = true;
    s.onload = () => resolve(window.hljs || null);
    s.onerror = () => resolve(null);
    document.head.appendChild(s);
  });
  return _hljsLoadPromise;
}

export class BuiltinCodeEditor extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    language: { type: String },
    lineNumbers: { type: Boolean, attribute: "line-numbers" },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      position: relative;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-input-bg, #ffffff);
      overflow: hidden;
    }
    .header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 8px 12px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .lang { font-size: 12px; color: var(--builtin-color-muted, #6b7280); font-weight: 650; text-transform: uppercase; }
    .copy-btn {
      display: inline-flex; align-items: center; gap: 6px;
      min-height: 28px; padding: 0 10px; font-size: 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      border-radius: var(--builtin-radius, 6px); cursor: pointer; color: var(--builtin-color-text, #111827);
    }
    .copy-btn:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .editor {
      position: relative;
      display: grid;
      grid-template-columns: 1fr;
      min-height: 160px;
    }
    .editor > textarea, .editor > .highlight {
      grid-area: 1 / 1;
      padding: 12px 12px 12px 56px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      line-height: 1.6;
      white-space: pre;
      overflow: auto;
    }
    .editor > .highlight {
      pointer-events: none;
      z-index: 1;
      color: var(--builtin-color-text, #111827);
      overflow: hidden;
    }
    .editor > .highlight code { background: transparent; padding: 0; }
    .editor > textarea {
      z-index: 2;
      border: 0;
      background: transparent;
      color: transparent;
      caret-color: var(--builtin-color-text, #111827);
      outline: none;
      resize: vertical;
    }
    .line-numbers {
      position: absolute;
      left: 0; top: 0; bottom: 0;
      width: 44px;
      padding: 12px 8px 12px 0;
      text-align: right;
      color: var(--builtin-color-muted, #6b7280);
      background: var(--builtin-header-bg, #f9fafb);
      border-right: 1px solid var(--builtin-border-soft, #e5e7eb);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      line-height: 1.6;
      user-select: none;
      z-index: 3;
      overflow: hidden;
    }
    .line-numbers pre { margin: 0; }
    .no-line-numbers .editor > textarea,
    .no-line-numbers .editor > .highlight {
      padding-left: 12px;
    }
    @media (max-width: 720px) {
      .editor { min-height: 140px; }
      .editor > textarea, .editor > .highlight { font-size: 15px; padding-left: 12px; }
      .line-numbers { display: none; }
    }
  `;

  constructor() {
    super();
    this.value = "";
    this.language = "javascript";
    this.lineNumbers = false;
  }

  connectedCallback() {
    super.connectedCallback();
    if (!window.hljs) {
      _ensureHljs().then(() => this.requestUpdate());
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _hljs() {
    return window.hljs || null;
  }

  _highlighted() {
    const code = this.value || "";
    const hljs = this._hljs();
    if (hljs && this.language) {
      try {
        const result = hljs.highlight(code, { language: this.language, ignoreIllegals: true });
        return result.value;
      } catch (_e) {
        return code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      }
    }
    return code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  _lineNumbersHtml() {
    if (!this.lineNumbers) return "";
    const count = (this.value || "").split("\n").length;
    return Array.from({ length: count }, (_, i) => i + 1).join("\n");
  }

  _onInput(e) {
    this.value = e.target.value;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true }));
  }

  async _copy() {
    try {
      await navigator.clipboard.writeText(this.value || "");
    } catch (_e) {
      const ta = document.createElement("textarea");
      ta.value = this.value || "";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
  }

  _syncScroll(e) {
    const highlight = this.renderRoot.querySelector(".highlight");
    const lineNumbers = this.renderRoot.querySelector(".line-numbers");
    if (highlight) highlight.scrollTop = e.target.scrollTop;
    if (lineNumbers) lineNumbers.scrollTop = e.target.scrollTop;
  }

  render() {
    const showLineNumbers = this.lineNumbers && !this._ptMobile;
    return html`
      <div class="wrap" part="wrap">
        <div class="header" part="header">
          <span class="lang">${this.language || "text"}</span>
          <slot name="header-extra"></slot>
          <button class="copy-btn" @click=${this._copy} title="${this._l("copy", "Copy")}">
            <builtin-icon name="copy" size="14" variant="outlined"></builtin-icon>
            ${this._l("copy", "Copy")}
          </button>
        </div>
        <div class="editor ${classMap({ 'no-line-numbers': !showLineNumbers })}" part="editor">
          ${showLineNumbers ? html`<div class="line-numbers"><pre>${this._lineNumbersHtml()}</pre></div>` : ""}
          <div class="highlight"><code>${unsafeHTML(this._highlighted())}</code></div>
          <textarea
            .value=${this.value}
            @input=${this._onInput}
            @scroll=${this._syncScroll}
            spellcheck="false"
            autocapitalize="off"
            autocomplete="off"
            autocorrect="off"
            part="textarea"
          ></textarea>
        </div>
      </div>
    `;
  }
}
