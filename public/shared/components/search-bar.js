import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinSearchBar - Search input with debounce, clear button, and optional suggestions.
 *
 * Attributes:
 *   - placeholder: Input placeholder text
 *   - value: Current input value
 *   - debounce: Debounce delay in milliseconds (default 300)
 *   - suggestions: JSON array of suggestion strings/objects
 *   - mode: "simple" | "expanded" | "filter"
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-search: Fired after debounce when the input value changes. Detail: { value }
 *   - builtin-select: Fired when a suggestion is clicked. Detail: { value, index }
 */
export class BuiltinSearchBar extends BuiltinBaseElement {
  static properties = {
    placeholder: { type: String },
    value: { type: String },
    debounce: { type: Number },
    suggestions: { type: Array },
    mode: { type: String },
    labels: { type: Object },
    _open: { type: Boolean, state: true },
  };

  static styles = css`
    :host {
      display: block;
      width: 100%;
    }
    .wrap {
      position: relative;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .icon {
      position: absolute;
      left: 10px;
      color: var(--builtin-color-muted, #6b7280);
      pointer-events: none;
      display: flex;
      align-items: center;
    }
    input {
      padding-left: 34px;
      padding-right: 34px;
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      outline: none;
      font: inherit;
    }
    input:focus {
      border-color: var(--builtin-primary, #2563eb);
    }
    input.expanded {
      padding-top: 10px;
      padding-bottom: 10px;
    }
    .clear {
      position: absolute;
      right: 6px;
      background: transparent;
      border: none;
      color: var(--builtin-color-muted, #6b7280);
      cursor: pointer;
      min-height: auto;
      padding: 2px 6px;
      line-height: 1;
      font-size: 18px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .clear:hover {
      color: var(--builtin-color-text, #111827);
    }
    .suggestions {
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      z-index: 1000;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      margin-top: 4px;
      max-height: 240px;
      overflow: auto;
      display: none;
    }
    .suggestions.open {
      display: block;
    }
    .suggestion {
      padding: 8px 12px;
      cursor: pointer;
      color: var(--builtin-color-text, #111827);
    }
    .suggestion:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    .filter-wrap {
      flex-wrap: wrap;
    }
    @media (max-width: 720px) {
      input {
        min-height: 44px;
        font-size: 16px;
      }
    }
  `;

  constructor() {
    super();
    this.debounce = 300;
    this.suggestions = [];
    this.mode = "simple";
    this._open = false;
    this._debounceTimer = null;
  }

  _l(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(
          /\{([a-zA-Z0-9_]+)\}/g,
          (match, name) =>
            Object.prototype.hasOwnProperty.call(values, name)
              ? String(values[name])
              : match
        );
      }
      return text;
    }
    return this._t(key, values);
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("click", this._onDocClick);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("click", this._onDocClick);
    if (this._debounceTimer) clearTimeout(this._debounceTimer);
  }

  _onDocClick = (e) => {
    if (!this.shadowRoot.contains(e.target)) {
      this._open = false;
    }
  };

  _onInput(e) {
    const raw = e.target.value;
    this.value = raw;
    if (this._debounceTimer) clearTimeout(this._debounceTimer);
    this._debounceTimer = setTimeout(() => {
      this.dispatchEvent(
        new CustomEvent("builtin-search", {
          bubbles: true,
          composed: true,
          detail: { value: raw },
        })
      );
    }, this.debounce || 300);
    this._open = !!(this.suggestions && this.suggestions.length);
  }

  _onClear() {
    this.value = "";
    this._open = false;
    if (this._debounceTimer) clearTimeout(this._debounceTimer);
    this.dispatchEvent(
      new CustomEvent("builtin-search", {
        bubbles: true,
        composed: true,
        detail: { value: "" },
      })
    );
  }

  _onSuggestionClick(index, value) {
    this.value =
      typeof value === "string"
        ? value
        : value.value || value.label || String(value);
    this._open = false;
    this.dispatchEvent(
      new CustomEvent("builtin-select", {
        bubbles: true,
        composed: true,
        detail: { value: this.value, index },
      })
    );
  }

  _suggestionText(s) {
    return typeof s === "string" ? s : s.label || s.value || String(s);
  }

  render() {
    const hasValue = this.value && this.value.length > 0;
    const hasSuggestions = this.suggestions && this.suggestions.length > 0;
    const open = this._open && hasSuggestions;

    return html`
      <div
        class="wrap ${classMap({
          "filter-wrap": this.mode === "filter",
        })}"
      >
        <span class="icon">
          <builtin-icon name="search" size="16" variant="outlined"></builtin-icon>
        </span>
        <input
          type="text"
          part="input"
          .value="${this.value || ""}"
          class="${classMap({ expanded: this.mode === "expanded" })}"
          placeholder="${this.placeholder || this._l("search.placeholder")}"
          autocomplete="off"
          @input="${this._onInput}"
        />
        ${hasValue
          ? html`
              <button
                class="clear"
                part="clear"
                aria-label="${this._l("search.clear")}"
                @click="${this._onClear}"
              >
                <builtin-icon name="close" size="16" variant="outlined"></builtin-icon>
              </button>
            `
          : ""}
        ${hasSuggestions
          ? html`
              <div
                class="suggestions ${classMap({ open })}"
                part="suggestions"
              >
                ${repeat(
                  this.suggestions,
                  (s, i) => i,
                  (s, i) => html`
                    <div
                      class="suggestion"
                      @click="${() => this._onSuggestionClick(i, s)}"
                    >
                      ${this._suggestionText(s)}
                    </div>
                  `
                )}
              </div>
            `
          : ""}
      </div>
    `;
  }
}
