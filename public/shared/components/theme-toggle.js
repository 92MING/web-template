import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";
import { setSharedTheme, getSharedTheme } from "./lit-base.js";

/**
 * @fileoverview Theme toggle button web component.
 *
 * @element builtin-theme-toggle
 *
 * @attr {number} size - Icon size in px. Default 20.
 * @attr {string} labels - JSON object for i18n overrides.
 *
 * @method render() - Re-renders the component.
 */
export class BuiltinThemeToggle extends BuiltinBaseElement {
  static properties = {
    size: { type: Number },
    labels: { type: Object },
  };

  static styles = css`
    :host {
      display: inline-block;
    }
    button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      padding: 0;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      font: inherit;
    }
    button:hover {
      background: var(--builtin-button-hover-bg, #f9fafb);
    }
    @media (max-width: 720px) {
      button {
        width: 48px;
        height: 48px;
      }
    }
  `;

  constructor() {
    super();
    this.size = 20;
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

  _isDark() {
    return (
      this._ptTheme === "dark" ||
      document.documentElement.dataset.builtinTheme === "dark" ||
      getSharedTheme() === "dark"
    );
  }

  _toggle() {
    setSharedTheme(!this._isDark());
  }

  render() {
    const isDark = this._isDark();
    const size = this.size || 20;
    const label = isDark
      ? this._l("themeToggle.light")
      : this._l("themeToggle.dark");

    return html`
      <button
        type="button"
        aria-label="${label}"
        title="${label}"
        @click="${this._toggle}"
      >
        ${isDark
          ? html`
              <builtin-icon name="sun" size="${size}" variant="outlined"></builtin-icon>
            `
          : html`
              <builtin-icon name="moon" size="${size}" variant="outlined"></builtin-icon>
            `}
      </button>
    `;
  }
}
