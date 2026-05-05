import { BuiltinBaseElement, html, css } from '../lit-base.js';

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

export class BuiltinPageHeader extends BuiltinBaseElement {
  static properties = {
    icon: { type: String },
    title: { type: String },
    subtitle: { type: String },
    backHref: { type: String, attribute: 'back-href' },
    backLabel: { type: String, attribute: 'back-label' },
    showBack: { type: Boolean, attribute: 'show-back' },
    showLang: { type: Boolean, attribute: 'show-lang' },
    showTheme: { type: Boolean, attribute: 'show-theme' },
    currentLang: { type: String, attribute: 'current-lang' },
    langs: { type: Array, converter: jsonConverter },
  };

  static styles = css`
    :host { display: block; }
    .header {
      display: flex;
      align-items: center;
      gap: 1rem;
      flex-wrap: wrap;
      margin-bottom: 1rem;
      padding: 0.9rem 1rem;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
    }
    .title-wrap {
      min-width: 0;
      flex: 1;
      display: grid;
      gap: 4px;
    }
    .title {
      margin: 0;
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--builtin-color-text, #111827);
    }
    .subtitle {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 0.875rem;
      line-height: 1.5;
    }
    .controls,
    .actions {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      flex-wrap: wrap;
    }
    .controls {
      margin-left: auto;
    }
    .back-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.35rem;
      padding: 0.5rem 0.75rem;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      text-decoration: none;
      font: inherit;
      font-size: 0.875rem;
      box-sizing: border-box;
    }
    .back-link:hover {
      background: var(--builtin-button-hover-bg, #f9fafb);
    }
    @media (max-width: 720px) {
      .header { padding: 0.75rem; }
      .controls {
        margin-left: 0;
        width: 100%;
        justify-content: flex-start;
      }
      .actions {
        width: 100%;
      }
    }
  `;

  constructor() {
    super();
    this.icon = '';
    this.title = '';
    this.subtitle = '';
    this.backHref = '';
    this.backLabel = '';
    this.showBack = true;
    this.showLang = true;
    this.showTheme = true;
    this.currentLang = 'zh-cn';
    this.langs = [
      { code: 'zh-cn', label: '中' },
      { code: 'en', label: 'EN' },
    ];
  }

  _emitLangChange(e) {
    this.dispatchEvent(new CustomEvent('builtin-lang-change', {
      bubbles: true,
      composed: true,
      detail: { lang: e.detail.lang },
    }));
  }

  render() {
    return html`
      <div class="header">
        ${this.icon ? html`<builtin-icon name="${this.icon}" size="24"></builtin-icon>` : ''}
        <div class="title-wrap">
          ${this.title ? html`<h1 class="title">${this.title}</h1>` : ''}
          ${this.subtitle ? html`<div class="subtitle">${this.subtitle}</div>` : ''}
        </div>
        ${this.showBack && this.backHref ? html`
          <a class="back-link" href="${this.backHref}">
            <builtin-icon name="backward" size="14"></builtin-icon>
            <span>${this.backLabel}</span>
          </a>
        ` : ''}
        <div class="controls">
          ${this.showLang ? html`
            <builtin-lang-switcher
              .langs=${this.langs}
              .current=${this.currentLang}
              display="buttons"
              @lang-change=${(e) => this._emitLangChange(e)}
            ></builtin-lang-switcher>
          ` : ''}
          ${this.showTheme ? html`<builtin-theme-toggle></builtin-theme-toggle>` : ''}
        </div>
        <div class="actions"><slot name="actions"></slot></div>
      </div>
    `;
  }
}