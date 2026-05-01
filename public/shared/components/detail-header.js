import { BuiltinBaseElement, html, css } from './lit-base.js';

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

export class BuiltinDetailHeader extends BuiltinBaseElement {
  static properties = {
    icon: { type: String },
    eyebrow: { type: String },
    title: { type: String },
    description: { type: String },
    meta: { type: Array, converter: jsonConverter },
  };

  static styles = css`
    :host { display: block; }
    .shell {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      padding: 20px;
      display: grid;
      gap: 16px;
    }
    .top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }
    .copy {
      min-width: 0;
      display: grid;
      gap: 10px;
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--builtin-primary, #2563eb);
      font-size: 12px;
      letter-spacing: .14em;
      text-transform: uppercase;
      font-weight: 800;
    }
    .title {
      margin: 0;
      font-size: clamp(1.5rem, 3.2vw, 2.4rem);
      line-height: 1.02;
      letter-spacing: -.04em;
      color: var(--builtin-color-text, #111827);
    }
    .description {
      margin: 0;
      color: var(--builtin-color-muted, #6b7280);
      line-height: 1.65;
      font-size: 0.98rem;
    }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .meta-item {
      padding: 14px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-header-bg, #f9fafb);
      display: grid;
      gap: 4px;
    }
    .meta-label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .meta-value {
      font-size: 0.95rem;
      color: var(--builtin-color-text, #111827);
      word-break: break-word;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    @media (max-width: 720px) {
      .meta-grid { grid-template-columns: 1fr; }
      .shell { padding: 16px; }
    }
  `;

  constructor() {
    super();
    this.icon = '';
    this.eyebrow = '';
    this.title = '';
    this.description = '';
    this.meta = [];
  }

  render() {
    return html`
      <section class="shell">
        <div class="top">
          <div class="copy">
            ${(this.eyebrow || this.icon) ? html`
              <div class="eyebrow">
                ${this.icon ? html`<builtin-icon name="${this.icon}" size="14"></builtin-icon>` : ''}
                ${this.eyebrow}
              </div>
            ` : ''}
            ${this.title ? html`<h2 class="title">${this.title}</h2>` : ''}
            ${this.description ? html`<p class="description">${this.description}</p>` : ''}
          </div>
          <div class="actions"><slot name="actions"></slot></div>
        </div>
        ${this.meta?.length ? html`
          <div class="meta-grid">
            ${this.meta.map((item) => html`
              <div class="meta-item">
                <div class="meta-label">
                  ${item.icon ? html`<builtin-icon name="${item.icon}" size="14"></builtin-icon>` : ''}
                  <span>${item.label || ''}</span>
                </div>
                <div class="meta-value">${item.value ?? ''}</div>
              </div>
            `)}
          </div>
        ` : ''}
      </section>
    `;
  }
}