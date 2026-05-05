import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "../lit-base.js";

/**
 * @fileoverview BuiltinAiCodeBlock — syntax-highlighted code block with copy.
 *
 * @element builtin-ai-code-block
 *
 * @attr {string} code — Code string.
 * @attr {string} language — Language identifier.
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @event builtin-copy — Copy button clicked. detail: {code}
 */
export class BuiltinAiCodeBlock extends BuiltinBaseElement {
  static properties = {
    code: { type: String },
    language: { type: String },
    labels: {
      converter: {
        fromAttribute(value) {
          if (!value) return {};
          try { return JSON.parse(value); } catch (_e) { return {}; }
        },
        toAttribute(value) { return JSON.stringify(value); },
      },
    },
    _highlighted: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-header-bg, #f9fafb);
      overflow: hidden;
    }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 12px;
      background: var(--builtin-surface, #ffffff);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .lang { font-size: 12px; font-weight: 600; color: var(--builtin-color-muted, #6b7280); text-transform: uppercase; }
    .copy-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      min-height: 28px;
      padding: 0 10px;
      cursor: pointer;
      font-size: 12px;
    }
    .copy-btn:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .body {
      padding: 12px 14px;
      overflow-x: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      line-height: 1.6;
      color: var(--builtin-color-text, #111827);
    }
    .body pre { margin: 0; background: transparent; }
    @media (max-width: 720px) {
      .body { font-size: 14px; }
      .copy-btn { min-height: 34px; padding: 0 12px; font-size: 14px; }
    }
  `;

  constructor() {
    super();
    this.code = "";
    this.language = "";
    this.labels = {};
    this._highlighted = null;
    this._hlReady = false;
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

  async _tryHighlight() {
    if (!this.code) {
      this._highlighted = null;
      return;
    }
    if (this._hlReady && window.hljs) {
      try {
        const result = window.hljs.highlight(this.code, { language: this.language || "plaintext", ignoreIllegals: true });
        this._highlighted = result.value;
        return;
      } catch (_err) {
        // fallback to plain
      }
    }
    this._highlighted = null;
  }

  async _loadHighlight() {
    if (this._hlReady) return;
    if (!window.hljs) {
      try {
        await import("../../../vendor/highlight/highlight.js");
      } catch (_err) {
        return;
      }
    }
    this._hlReady = true;
    await this._tryHighlight();
  }

  willUpdate(changed) {
    if (changed.has("code") || changed.has("language")) {
      this._tryHighlight();
    }
  }

  connectedCallback() {
    super.connectedCallback();
    this._loadHighlight();
  }

  _escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  _onCopy() {
    this.dispatchEvent(new CustomEvent("builtin-copy", { detail: { code: this.code }, bubbles: true }));
  }

  render() {
    const codeHtml = this._highlighted ?? this._escapeHtml(this.code);
    const lang = this.language || this._t("code.plaintext");
    return html`
      <div class="wrap">
        <div class="header">
          <span class="lang">${lang}</span>
          <button class="copy-btn" @click="${this._onCopy}" aria-label="${this._t("code.copy")}">
            <builtin-icon name="copy" size="16" variant="outlined"></builtin-icon>
            ${this._t("code.copy")}
          </button>
        </div>
        <div class="body"><pre><code>${unsafeHTML(codeHtml)}</code></pre></div>
      </div>
    `;
  }
}
