import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinInputTags — Tag input with pills, remove buttons and suggestions.
 *
 * @attr {Array} tags — JSON array of tag strings.
 * @attr {Array} suggestions — JSON array of suggestion strings/objects.
 * @attr {number} max — Maximum number of tags allowed.
 * @attr {string} placeholder — Input placeholder.
 * @attr {boolean} disabled — Disable interaction.
 * @attr {Object} labels — JSON object for i18n overrides.
 *
 * @slot — Extra content rendered after the suggestions.
 *
 * @event builtin-add — Detail: `{ tag }`
 * @event builtin-remove — Detail: `{ tag }`
 * @event builtin-change — Detail: `{ tags }`
 */
export class BuiltinInputTags extends BuiltinBaseElement {
  static properties = {
    tags: { type: Array },
    suggestions: { type: Array },
    max: { type: Number },
    placeholder: { type: String },
    disabled: { type: Boolean },
    labels: { type: Object },
    _inputValue: { type: String, state: true },
    _open: { type: Boolean, state: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    .host-wrap {
      position: relative;
    }
    .wrap {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      padding: 6px 8px;
      min-height: 36px;
      transition: border-color 0.15s ease;
    }
    .wrap:focus-within {
      border-color: var(--builtin-primary, #2563eb);
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      background: var(--builtin-primary-soft, #eff6ff);
      color: var(--builtin-primary, #2563eb);
      border: 1px solid var(--builtin-primary-soft, #dbeafe);
      border-radius: var(--builtin-radius, 6px);
      padding: 2px 8px;
      font-size: 13px;
      line-height: 1.5;
      max-width: 100%;
    }
    .pill .remove {
      background: none;
      border: none;
      padding: 0;
      margin: 0;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      color: inherit;
      opacity: 0.7;
      flex-shrink: 0;
    }
    .pill .remove:hover {
      opacity: 1;
    }
    input {
      border: none;
      background: transparent;
      outline: none;
      color: inherit;
      min-width: 60px;
      flex: 1 1 auto;
      font: inherit;
      padding: 2px 0;
    }
    .suggestions {
      position: absolute;
      z-index: 1000;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      margin-top: 4px;
      max-height: 200px;
      overflow: auto;
      display: none;
      min-width: 160px;
      left: 0;
      right: 0;
    }
    .suggestions.open {
      display: block;
    }
    .suggestion {
      padding: 8px 12px;
      cursor: pointer;
      color: var(--builtin-color-text, #111827);
      font-size: 14px;
    }
    .suggestion:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    @media (max-width: 720px) {
      .wrap {
        padding: 8px;
        gap: 8px;
      }
      .pill {
        padding: 4px 10px;
        font-size: 14px;
      }
      input {
        min-height: 32px;
        font-size: 16px;
      }
    }
  `;

  constructor() {
    super();
    this.tags = [];
    this.suggestions = [];
    this.max = 0;
    this.placeholder = "";
    this.disabled = false;
    this._inputValue = "";
    this._open = false;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("click", this._onDocClick);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("click", this._onDocClick);
  }

  _onDocClick = (e) => {
    if (!this.shadowRoot.contains(e.target)) this._open = false;
  };

  _addTag(tag) {
    const trimmed = (tag || "").trim();
    if (!trimmed) return;
    const current = Array.isArray(this.tags) ? this.tags : [];
    if (current.includes(trimmed)) return;
    if (this.max && current.length >= this.max) return;
    const next = [...current, trimmed];
    this.tags = next;
    this._inputValue = "";
    this._open = false;
    this.dispatchEvent(
      new CustomEvent("builtin-add", {
        detail: { tag: trimmed },
        bubbles: true,
        composed: true,
      })
    );
    this.dispatchEvent(
      new CustomEvent("builtin-change", {
        detail: { tags: next },
        bubbles: true,
        composed: true,
      })
    );
  }

  _removeTag(tag) {
    if (this.disabled) return;
    const current = Array.isArray(this.tags) ? this.tags : [];
    const next = current.filter((t) => t !== tag);
    this.tags = next;
    this.dispatchEvent(
      new CustomEvent("builtin-remove", {
        detail: { tag },
        bubbles: true,
        composed: true,
      })
    );
    this.dispatchEvent(
      new CustomEvent("builtin-change", {
        detail: { tags: next },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onInput(e) {
    this._inputValue = e.target.value;
    this._open = !!(
      this.suggestions &&
      this.suggestions.length &&
      this._inputValue
    );
  }

  _onKeydown(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      this._addTag(this._inputValue);
    } else if (e.key === "Backspace" && !this._inputValue) {
      const current = Array.isArray(this.tags) ? this.tags : [];
      if (current.length) {
        this._removeTag(current[current.length - 1]);
      }
    }
  }

  _onSuggestionClick(s) {
    this._addTag(
      typeof s === "string" ? s : s.label || s.value || String(s)
    );
  }

  _filteredSuggestions() {
    if (!this._inputValue) return [];
    const val = this._inputValue.toLowerCase();
    return (this.suggestions || []).filter((s) => {
      const text = (
        typeof s === "string" ? s : s.label || s.value || String(s)
      ).toLowerCase();
      return text.includes(val);
    });
  }

  render() {
    const tags = Array.isArray(this.tags) ? this.tags : [];
    const suggestions = this._filteredSuggestions();
    const showSuggestions = this._open && suggestions.length > 0;

    return html`
      <div class="host-wrap">
        <div class="wrap" part="wrap">
          ${repeat(
            tags,
            (t) => t,
            (t) => html`
              <span class="pill" part="pill">
                ${t}
                <button
                  class="remove"
                  part="remove"
                  ?disabled=${this.disabled}
                  aria-label="${this._l("tags.remove", "Remove")} ${t}"
                  @click="${() => this._removeTag(t)}"
                >
                  <builtin-icon name="close" size="14" variant="outlined"></builtin-icon>
                </button>
              </span>
            `
          )}
          <input
            type="text"
            part="input"
            .value="${this._inputValue}"
            placeholder="${this.placeholder || this._l("tags.placeholder", "Add a tag...")}"
            ?disabled=${this.disabled}
            @input="${this._onInput}"
            @keydown="${this._onKeydown}"
          />
        </div>
        ${showSuggestions
          ? html`
              <div class="suggestions open" part="suggestions">
                ${repeat(
                  suggestions,
                  (s, i) => i,
                  (s) => html`
                    <div
                      class="suggestion"
                      @click="${() => this._onSuggestionClick(s)}"
                    >
                      ${typeof s === "string"
                        ? s
                        : s.label || s.value || String(s)}
                    </div>
                  `
                )}
              </div>
            `
          : null}
        <slot></slot>
      </div>
    `;
  }
}
