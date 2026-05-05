import { BuiltinBaseElement, html, css } from "../lit-base.js";

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

export class BuiltinMetadataList extends BuiltinBaseElement {
  static properties = {
    items: { type: Array, converter: jsonConverter },
    columns: { type: Number },
    compact: { type: Boolean },
  };

  static styles = css`
    :host {
      display: block;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(var(--builtin-metadata-columns, 2), minmax(0, 1fr));
      gap: 12px;
    }
    .item {
      min-width: 0;
      padding: 14px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 12px);
      background: var(--builtin-header-bg, #f9fafb);
      display: grid;
      gap: 6px;
    }
    .item.compact {
      padding: 12px;
      gap: 4px;
    }
    .label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-weight: 700;
    }
    .value {
      color: var(--builtin-color-text, #111827);
      font-size: 16px;
      font-weight: 700;
      word-break: break-word;
    }
    .description {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      line-height: 1.5;
    }
    @media (max-width: 720px) {
      .grid {
        grid-template-columns: 1fr;
      }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.columns = 2;
    this.compact = false;
  }

  render() {
    const items = Array.isArray(this.items) ? this.items : [];
    return html`
      <div class="grid" style="--builtin-metadata-columns:${Math.max(Number(this.columns) || 2, 1)};">
        ${items.map((item) => html`
          <div class="item ${this.compact ? "compact" : ""}">
            <div class="label">
              ${item.icon ? html`<builtin-icon name="${item.icon}" size="14"></builtin-icon>` : null}
              <span>${item.label || ""}</span>
            </div>
            <div class="value">${item.value ?? ""}</div>
            ${item.description ? html`<div class="description">${item.description}</div>` : null}
          </div>
        `)}
      </div>
    `;
  }
}