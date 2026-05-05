import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinComparisonTable — Product/feature comparison table.
 *
 * Attributes:
 * - `products` (JSON): `[{name, features: {key: value}}]`
 * - `features` (JSON array of row labels): `[{key, label}]`
 * - `labels` (JSON object for local i18n overrides)
 *
 * Mobile: horizontal scroll with card view fallback option.
 */
export class BuiltinComparisonTable extends BuiltinBaseElement {
  static get properties() {
    return {
      products: {
        converter: {
          fromAttribute(value) {
            if (!value) return [];
            try {
              return JSON.parse(value);
            } catch (_e) {
              return [];
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
      features: {
        converter: {
          fromAttribute(value) {
            if (!value) return [];
            try {
              return JSON.parse(value);
            } catch (_e) {
              return [];
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
      labels: {
        converter: {
          fromAttribute(value) {
            if (!value) return {};
            try {
              return JSON.parse(value);
            } catch (_e) {
              return {};
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
      _hoverCol: { type: Number, state: true },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .wrapper {
        overflow-x: auto;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
      }
      table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        min-width: 600px;
      }
      th, td {
        padding: 12px 16px;
        text-align: left;
        font-size: 14px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        white-space: nowrap;
      }
      thead th {
        position: sticky;
        top: 0;
        z-index: 2;
        background: var(--builtin-header-bg, #f9fafb);
        font-weight: 650;
        color: var(--builtin-color-text, #111827);
      }
      thead th:first-child {
        position: sticky;
        left: 0;
        z-index: 3;
        background: var(--builtin-header-bg, #f9fafb);
      }
      tbody td {
        color: var(--builtin-color-text, #111827);
      }
      tbody td:first-child {
        position: sticky;
        left: 0;
        z-index: 1;
        background: var(--builtin-surface, #ffffff);
        font-weight: 600;
        color: var(--builtin-color-muted, #6b7280);
      }
      tbody tr:last-child td {
        border-bottom: none;
      }
      tbody tr:hover td {
        background: var(--builtin-row-hover-bg, #f9fafb);
      }
      tbody td:first-child:hover {
        background: var(--builtin-surface, #ffffff);
      }
      col.hover {
        background: var(--builtin-primary-soft, #eff6ff);
      }
      .bool {
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .bool-yes {
        color: var(--builtin-success, #16a34a);
      }
      .bool-no {
        color: var(--builtin-danger, #dc2626);
      }
      /* Card view for mobile */
      .cards {
        display: none;
        gap: 16px;
        padding: 12px;
      }
      .card {
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius-lg, 8px);
        padding: 16px;
        background: var(--builtin-surface, #ffffff);
      }
      .card-title {
        font-weight: 650;
        font-size: 15px;
        margin-bottom: 10px;
        color: var(--builtin-color-text, #111827);
      }
      .card-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        font-size: 13px;
      }
      .card-row:last-child {
        border-bottom: none;
      }
      .card-label {
        color: var(--builtin-color-muted, #6b7280);
      }
      .card-value {
        color: var(--builtin-color-text, #111827);
        font-weight: 500;
      }
      @media (max-width: 720px) {
        table {
          display: none;
        }
        .wrapper {
          border: none;
          background: transparent;
        }
        .cards {
          display: flex;
          flex-direction: column;
        }
      }
    `;
  }

  constructor() {
    super();
    this.products = [];
    this.features = [];
    this.labels = {};
    this._hoverCol = -1;
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name)
            ? String(values[name])
            : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  _renderBool(value) {
    const isBool = typeof value === "boolean";
    const isYes = isBool ? value : String(value).toLowerCase() === "yes" || String(value).toLowerCase() === "true";
    if (isBool || String(value).toLowerCase() === "no" || String(value).toLowerCase() === "false") {
      return html`
        <span class="bool ${isYes ? "bool-yes" : "bool-no"}">
          ${isYes
            ? html`<builtin-icon name="check" size="20" variant="outlined"></builtin-icon>`
            : html`<builtin-icon name="close" size="20" variant="outlined"></builtin-icon>`}
        </span>
      `;
    }
    return html`<span>${value}</span>`;
  }

  _setHoverCol(index) {
    this._hoverCol = index;
  }

  render() {
    const products = Array.isArray(this.products) ? this.products : [];
    const features = Array.isArray(this.features) ? this.features : [];

    return html`
      <div class="wrapper">
        <table>
          <colgroup>
            <col />
            ${products.map((_, i) => html`<col class="${classMap({ hover: this._hoverCol === i })}" />`)}
          </colgroup>
          <thead>
            <tr>
              <th>${this._t("comparison.feature")}</th>
              ${products.map((p) => html`<th>${p.name || ""}</th>`)}
            </tr>
          </thead>
          <tbody>
            ${features.map((f) => {
              const key = typeof f === "string" ? f : f.key;
              const label = typeof f === "string" ? f : (f.label || f.key);
              return html`
                <tr>
                  <td>${label}</td>
                  ${products.map((p, i) => html`
                    <td
                      @mouseenter=${() => this._setHoverCol(i)}
                      @mouseleave=${() => this._setHoverCol(-1)}
                    >
                      ${this._renderBool(p.features?.[key] ?? "—")}
                    </td>
                  `)}
                </tr>
              `;
            })}
          </tbody>
        </table>

        <div class="cards">
          ${products.map((p) => html`
            <div class="card">
              <div class="card-title">${p.name || ""}</div>
              ${features.map((f) => {
                const key = typeof f === "string" ? f : f.key;
                const label = typeof f === "string" ? f : (f.label || f.key);
                return html`
                  <div class="card-row">
                    <span class="card-label">${label}</span>
                    <span class="card-value">${this._renderBool(p.features?.[key] ?? "—")}</span>
                  </div>
                `;
              })}
            </div>
          `)}
        </div>
      </div>
    `;
  }
}
