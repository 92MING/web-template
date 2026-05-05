import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview Language switcher web component.
 *
 * @element builtin-lang-switcher
 *
 * @attr {string} langs - JSON array of { code, label } objects.
 * @attr {string} current - Currently selected language code.
 * @attr {string} display - "dropdown" | "buttons" | "native-select".
 * @attr {string} labels - JSON object for i18n overrides.
 *
 * @fires lang-change - Dispatched when a language is selected with detail `{ lang }`.
 */
export class BuiltinLangSwitcher extends BuiltinBaseElement {
  static properties = {
    langs: { type: Array },
    current: { type: String },
    display: { type: String },
    labels: { type: Object },
  };

  static styles = css`
    :host {
      display: inline-block;
    }
    .select-wrap {
      display: none;
    }
    .buttons {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .lang-btn {
      padding: 6px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      min-height: 34px;
      font: inherit;
    }
    .lang-btn:hover {
      background: var(--builtin-button-hover-bg, #f9fafb);
    }
    .lang-btn.active {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    select {
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      padding: 0 8px;
      font: inherit;
    }
    @media (max-width: 720px) {
      .select-wrap {
        display: block;
      }
      .buttons {
        display: none;
      }
      select {
        min-height: 44px;
        font-size: 16px;
      }
    }
  `;

  constructor() {
    super();
    this.langs = [];
    this.current = "";
    this.display = "buttons";
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

  _onSelectChange(e) {
    const lang = e.target.value;
    this.current = lang;
    this.dispatchEvent(
      new CustomEvent("lang-change", {
        detail: { lang },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onButtonClick(lang) {
    this.current = lang;
    this.dispatchEvent(
      new CustomEvent("lang-change", {
        detail: { lang },
        bubbles: true,
        composed: true,
      })
    );
  }

  render() {
    const langs = Array.isArray(this.langs) ? this.langs : [];
    const isNative = this.display === "native-select" || this._ptMobile;
    const isDropdown = this.display === "dropdown" && !this._ptMobile;
    const isButtons = this.display === "buttons" && !this._ptMobile;

    return html`
      ${isNative || isDropdown
        ? html`
            <div class="select-wrap" style="${styleMap({ display: isDropdown ? "block" : "" })}">
              <select
                .value="${this.current || ""}"
                @change="${this._onSelectChange}"
                aria-label="${this._l("langSwitcher.label")}"
              >
                ${repeat(
                  langs,
                  (l) => l.code,
                  (l) => html`
                    <option
                      value="${l.code}"
                      ?selected="${l.code === this.current}"
                    >
                      ${l.label || l.code}
                    </option>
                  `
                )}
              </select>
            </div>
          `
        : ""}
      ${isButtons
        ? html`
            <div
              class="buttons"
              role="group"
              aria-label="${this._l("langSwitcher.label")}"
            >
              ${repeat(
                langs,
                (l) => l.code,
                (l) => html`
                  <button
                    class="lang-btn ${classMap({
                      active: l.code === this.current,
                    })}"
                    @click="${() => this._onButtonClick(l.code)}"
                  >
                    ${l.label || l.code}
                  </button>
                `
              )}
            </div>
          `
        : ""}
    `;
  }
}
