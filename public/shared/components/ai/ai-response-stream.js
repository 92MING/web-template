import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "../lit-base.js";

/**
 * @fileoverview BuiltinAiResponseStream — streaming text with copy and simple markdown formatting.
 *
 * @element builtin-ai-response-stream
 *
 * @attr {string} content — Streaming text content.
 * @attr {boolean} typing — Show blinking cursor.
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @event builtin-copy — Copy button clicked. detail: {content}
 */
export class BuiltinAiResponseStream extends BuiltinBaseElement {
  static properties = {
    content: { type: String },
    typing: { type: Boolean },
    _visibleContent: { type: String, state: true },
    labels: {
      converter: {
        fromAttribute(value) {
          if (!value) return {};
          try { return JSON.parse(value); } catch (_e) { return {}; }
        },
        toAttribute(value) { return JSON.stringify(value); },
      },
    },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      position: relative;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      padding: 14px 16px;
    }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }
    .title { font-weight: 600; color: var(--builtin-color-text, #111827); }
    .copy-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      min-height: 30px;
      padding: 0 10px;
      cursor: pointer;
      font-size: 12px;
    }
    .copy-btn:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .body {
      line-height: 1.65;
      color: var(--builtin-color-text, #111827);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .body ::slotted(pre), .body pre {
      background: var(--builtin-header-bg, #f9fafb);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      padding: 10px 12px;
      overflow-x: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      margin: 8px 0;
    }
    .body code {
      background: var(--builtin-header-bg, #f9fafb);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: 4px;
      padding: 2px 5px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.92em;
    }
    .body strong { font-weight: 700; }
    .cursor {
      display: inline-block;
      width: 2px;
      height: 1.1em;
      background: var(--builtin-primary, #2563eb);
      vertical-align: text-bottom;
      margin-left: 2px;
      animation: blink 1s step-end infinite;
    }
    @keyframes blink { 50% { opacity: 0; } }
    @media (max-width: 720px) {
      .body { font-size: 16px; }
      .copy-btn { min-height: 36px; padding: 0 12px; font-size: 14px; }
    }
  `;

  constructor() {
    super();
    this.content = "";
    this.typing = false;
    this.labels = {};
    this._visibleContent = "";
    this._typingTimer = null;
  }

  updated(changed) {
    if (changed.has("content") || changed.has("typing")) this._syncTypingEffect();
  }

  disconnectedCallback() {
    clearInterval(this._typingTimer);
    this._typingTimer = null;
    super.disconnectedCallback();
  }

  _syncTypingEffect() {
    clearInterval(this._typingTimer);
    this._typingTimer = null;
    if (!this.typing) {
      this._visibleContent = this.content || "";
      return;
    }
    const source = this.content || "";
    this._visibleContent = "";
    let index = 0;
    this._typingTimer = setInterval(() => {
      index = Math.min(source.length, index + 3);
      this._visibleContent = source.slice(0, index);
      if (index >= source.length) {
        clearInterval(this._typingTimer);
        this._typingTimer = null;
      }
    }, 28);
  }

  _t(key, values) {
    if (this.labels && typeof this.labels === "object" && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => (
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        ));
      }
      return text;
    }
    return super._t(key, values);
  }

  _escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  _formatContent(text) {
    let htmlText = this._escapeHtml(text);
    // Code blocks ```...```
    htmlText = htmlText.replace(/```([\s\S]*?)```/g, (_, code) => {
      return `<pre><code>${code.trim()}</code></pre>`;
    });
    // Inline code `...`
    htmlText = htmlText.replace(/`([^`]+)`/g, (_, code) => {
      return `<code>${code}</code>`;
    });
    // Bold **...**
    htmlText = htmlText.replace(/\*\*([^*]+)\*\*/g, (_, inner) => {
      return `<strong>${inner}</strong>`;
    });
    return htmlText;
  }

  _onCopy() {
    this.dispatchEvent(new CustomEvent("builtin-copy", { detail: { content: this.content }, bubbles: true }));
  }

  render() {
    const text = this.typing ? this._visibleContent : this.content;
    const formatted = this._formatContent(text);
    return html`
      <div class="wrap">
        <div class="header">
          <span class="title">${this._t("stream.title")}</span>
          <button class="copy-btn" @click="${this._onCopy}" aria-label="${this._t("stream.copy")}">
            <builtin-icon name="copy" size="16" variant="outlined"></builtin-icon>
            ${this._t("stream.copy")}
          </button>
        </div>
        <div class="body">${unsafeHTML(formatted)}<span class="cursor" ?hidden="${!this.typing}"></span></div>
      </div>
    `;
  }
}
