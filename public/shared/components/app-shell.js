import { BuiltinBaseElement, html, css, classMap } from "./lit-base.js";

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try {
      return JSON.parse(value);
    } catch {
      return undefined;
    }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  },
};

export class BuiltinAppShell extends BuiltinBaseElement {
  static properties = {
    eyebrow: { type: String },
    title: { type: String },
    subtitle: { type: String },
    backHref: { type: String, attribute: "back-href" },
    backLabel: { type: String, attribute: "back-label" },
    showBack: { type: Boolean, attribute: "show-back" },
    breadcrumbs: { type: Array, converter: jsonConverter },
    showLang: { type: Boolean, attribute: "show-lang" },
    showTheme: { type: Boolean, attribute: "show-theme" },
    currentLang: { type: String, attribute: "current-lang" },
    langs: { type: Array, converter: jsonConverter },
    userName: { type: String, attribute: "user-name" },
    userEmail: { type: String, attribute: "user-email" },
    userAvatar: { type: String, attribute: "user-avatar" },
    userMenuItems: { type: Array, attribute: "user-menu-items", converter: jsonConverter },
  };

  static styles = css`
    :host {
      display: block;
    }
    .shell {
      max-width: var(--builtin-shell-max-width, 1100px);
      margin: 0 auto;
      padding: var(--builtin-shell-padding, 24px 16px 48px);
      display: grid;
      gap: 20px;
      box-sizing: border-box;
    }
    .header {
      display: grid;
      gap: 14px;
    }
    .topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .nav {
      display: grid;
      gap: 8px;
      min-width: 0;
      flex: 1;
    }
    .back-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      width: fit-content;
      padding: 8px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 999px;
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      text-decoration: none;
      font: inherit;
      font-size: 13px;
    }
    .back-link:hover {
      background: var(--builtin-button-hover-bg, #f9fafb);
    }
    .controls {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .hero {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      padding: 18px 20px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-xl, 24px);
      background: var(--builtin-surface, rgba(255, 255, 255, 0.9));
      box-shadow: 0 18px 60px rgba(15, 23, 42, 0.08);
    }
    .copy {
      min-width: 0;
      flex: 1;
      display: grid;
      gap: 8px;
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--builtin-primary, #2563eb);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .title {
      margin: 0;
      font-size: clamp(28px, 5vw, 54px);
      line-height: 0.96;
      letter-spacing: -0.05em;
      color: var(--builtin-color-text, #111827);
    }
    .subtitle {
      margin: 0;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 15px;
      line-height: 1.7;
      max-width: 52rem;
    }
    .actions {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .body {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .body.has-secondary {
      grid-template-columns: minmax(0, 1fr) minmax(280px, var(--builtin-shell-secondary-width, 340px));
    }
    .main,
    .secondary {
      min-width: 0;
      display: grid;
      gap: 18px;
    }
    @media (max-width: 900px) {
      .body.has-secondary {
        grid-template-columns: 1fr;
      }
    }
    @media (max-width: 720px) {
      .shell {
        padding: var(--builtin-shell-padding-mobile, 16px 12px 32px);
        gap: 16px;
      }
      .hero {
        padding: 16px;
        border-radius: 20px;
      }
      .controls,
      .actions {
        width: 100%;
      }
      .actions {
        justify-content: flex-start;
      }
    }
  `;

  constructor() {
    super();
    this.eyebrow = "";
    this.title = "";
    this.subtitle = "";
    this.backHref = "";
    this.backLabel = "";
    this.showBack = true;
    this.breadcrumbs = [];
    this.showLang = true;
    this.showTheme = true;
    this.currentLang = "zh-cn";
    this.langs = [
      { code: "zh-cn", label: "中" },
      { code: "en", label: "EN" },
    ];
    this.userName = "";
    this.userEmail = "";
    this.userAvatar = "";
    this.userMenuItems = [];
  }

  _hasSlot(name) {
    return Array.from(this.children || []).some((node) => node.slot === name);
  }

  _emitLangChange(e) {
    this.dispatchEvent(new CustomEvent("builtin-lang-change", {
      bubbles: true,
      composed: true,
      detail: { lang: e.detail.lang },
    }));
  }

  _emitUserAction(e) {
    this.dispatchEvent(new CustomEvent("builtin-user-action", {
      bubbles: true,
      composed: true,
      detail: e.detail,
    }));
  }

  render() {
    const hasSecondary = this._hasSlot("secondary");
    const hasControls = this.showLang || this.showTheme || this.userName || this.userEmail || (this.userMenuItems || []).length;
    const hasNav = (this.showBack && this.backHref) || (this.breadcrumbs || []).length;
    return html`
      <div class="shell">
        <header class="header">
          ${(hasNav || hasControls) ? html`
            <div class="topbar">
              <div class="nav">
                ${this.showBack && this.backHref ? html`
                  <a class="back-link" href="${this.backHref}">
                    <builtin-icon name="backward" size="14"></builtin-icon>
                    <span>${this.backLabel}</span>
                  </a>
                ` : null}
                ${(this.breadcrumbs || []).length ? html`<builtin-breadcrumb .items=${this.breadcrumbs}></builtin-breadcrumb>` : null}
              </div>
              ${hasControls ? html`
                <div class="controls">
                  ${this.showLang ? html`
                    <builtin-lang-switcher
                      .langs=${this.langs}
                      .current=${this.currentLang}
                      display="buttons"
                      @lang-change=${(e) => this._emitLangChange(e)}
                    ></builtin-lang-switcher>
                  ` : null}
                  ${this.showTheme ? html`<builtin-theme-toggle></builtin-theme-toggle>` : null}
                  ${(this.userName || this.userEmail || (this.userMenuItems || []).length) ? html`
                    <builtin-user-menu
                      .name=${this.userName}
                      .email=${this.userEmail}
                      .avatar=${this.userAvatar}
                      .items=${this.userMenuItems}
                      @builtin-action=${(e) => this._emitUserAction(e)}
                    ></builtin-user-menu>
                  ` : null}
                </div>
              ` : null}
            </div>
          ` : null}
          <div class="hero">
            <div class="copy">
              ${this.eyebrow ? html`<div class="eyebrow">${this.eyebrow}</div>` : null}
              ${this.title ? html`<h1 class="title">${this.title}</h1>` : null}
              ${this.subtitle ? html`<p class="subtitle">${this.subtitle}</p>` : null}
              <slot name="header-meta"></slot>
            </div>
            <div class="actions"><slot name="actions"></slot></div>
          </div>
        </header>
        <div class="body ${classMap({ "has-secondary": hasSecondary })}">
          <main class="main"><slot></slot></main>
          ${hasSecondary ? html`<aside class="secondary"><slot name="secondary"></slot></aside>` : null}
        </div>
      </div>
    `;
  }
}