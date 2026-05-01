import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinAiPromptInput — auto-growing textarea with submit/stop actions.
 *
 * @element builtin-ai-prompt-input
 *
 * @attr {string} placeholder — Textarea placeholder.
 * @attr {string} value — Current textarea value.
 * @attr {boolean} disabled — Disable input.
 * @attr {boolean} loading — Show stop button instead of submit.
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @slots
 * - file-attach — File attach button area.
 *
 * @event builtin-submit — User pressed submit. detail: {value}
 * @event builtin-stop — User pressed stop. detail: {}
 */
export class BuiltinAiPromptInput extends BuiltinBaseElement {
  static properties = {
    placeholder: { type: String },
    value: { type: String },
    disabled: { type: Boolean },
    loading: { type: Boolean },
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
      display: flex;
      align-items: flex-end;
      gap: 10px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-input-bg, #ffffff);
      padding: 10px 12px;
    }
    .textarea-wrap { flex: 1 1 auto; display: flex; flex-direction: column; }
    textarea {
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      resize: none;
      overflow: hidden;
      min-height: 24px;
      max-height: 200px;
      line-height: 1.5;
      padding: 2px 0;
      width: 100%;
      outline: none;
    }
    textarea::placeholder { color: var(--builtin-color-muted, #9ca3af); }
    textarea:disabled { opacity: 0.6; }
    .actions {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      min-height: 34px;
      padding: 0 12px;
      cursor: pointer;
      font-size: 14px;
    }
    .btn:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .btn:disabled { cursor: not-allowed; opacity: 0.55; }
    .btn-primary {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .btn-primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .btn-danger {
      background: var(--builtin-color-danger, #b91c1c);
      border-color: var(--builtin-color-danger, #b91c1c);
      color: #fff;
    }
    .btn-danger:hover { background: #991b1b; }
    @media (max-width: 720px) {
      .wrap { padding: 12px; gap: 12px; }
      .btn { min-height: 44px; padding: 0 16px; font-size: 16px; }
      textarea { font-size: 16px; }
    }
  `;

  constructor() {
    super();
    this.placeholder = "";
    this.value = "";
    this.disabled = false;
    this.loading = false;
    this.labels = {};
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

  _onInput(e) {
    this.value = e.target.value;
    this._autoGrow(e.target);
  }

  _autoGrow(el) {
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }

  _onKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      this._submit();
    }
  }

  _submit() {
    if (this.disabled || this.loading || !this.value.trim()) return;
    this.dispatchEvent(new CustomEvent("builtin-submit", { detail: { value: this.value.trim() }, bubbles: true }));
  }

  _stop() {
    this.dispatchEvent(new CustomEvent("builtin-stop", { detail: {}, bubbles: true }));
  }

  render() {
    return html`
      <div class="wrap">
        <div class="textarea-wrap">
          <textarea
            .value="${this.value}"
            placeholder="${this.placeholder || this._t("prompt.placeholder")}"
            ?disabled="${this.disabled || this.loading}"
            rows="1"
            @input="${this._onInput}"
            @keydown="${this._onKeydown}"
            aria-label="${this._t("prompt.label")}"
          ></textarea>
        </div>
        <div class="actions">
          <slot name="file-attach"></slot>
          ${this.loading
            ? html`
                <button class="btn btn-danger" @click="${this._stop}" aria-label="${this._t("prompt.stop")}">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="6" width="12" height="12" rx="2"></rect>
                  </svg>
                  ${this._t("prompt.stop")}
                </button>
              `
            : html`
                <button class="btn btn-primary" @click="${this._submit}" ?disabled="${this.disabled || !this.value.trim()}" aria-label="${this._t("prompt.submit")}">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13"></line>
                    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                  </svg>
                  ${this._t("prompt.submit")}
                </button>
              `}
        </div>
      </div>
    `;
  }
}
