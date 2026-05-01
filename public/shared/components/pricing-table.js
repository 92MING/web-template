import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinPricingTable — Multi-plan pricing comparison table.
 *
 * Attributes:
 * - `plans` (JSON): `[{name, price, period, features: [{label, value, included}], highlighted}]`
 * - `labels` (JSON object for local i18n overrides)
 *
 * Slots:
 * - `billing-toggle`: Monthly/yearly switch or other billing controls.
 *
 * Mobile: horizontal scroll or stacked cards.
 */
export class BuiltinPricingTable extends BuiltinBaseElement {
  static get properties() {
    return {
      plans: {
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
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .toolbar {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 10px;
        margin-bottom: 12px;
      }
      .table-wrap {
        overflow-x: auto;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
      }
      table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        min-width: 520px;
      }
      th, td {
        padding: 14px 18px;
        text-align: center;
        font-size: 14px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-left: 1px solid var(--builtin-border-soft, #e5e7eb);
      }
      th:first-child, td:first-child {
        text-align: left;
        border-left: none;
        position: sticky;
        left: 0;
        z-index: 1;
        background: var(--builtin-surface, #ffffff);
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
        background: var(--builtin-header-bg, #f9fafb);
        z-index: 3;
      }
      thead th.highlight {
        background: var(--builtin-primary-soft, #eff6ff);
        color: var(--builtin-primary, #2563eb);
      }
      tbody td:first-child {
        font-weight: 500;
        color: var(--builtin-color-muted, #6b7280);
      }
      tbody tr:last-child td {
        border-bottom: none;
      }
      .plan-name {
        font-size: 15px;
        font-weight: 650;
      }
      .plan-price {
        font-size: 24px;
        font-weight: 700;
        margin-top: 4px;
      }
      .plan-period {
        font-size: 12px;
        color: var(--builtin-color-muted, #6b7280);
        font-weight: 400;
      }
      td.highlight {
        background: var(--builtin-primary-soft, #eff6ff);
      }
      .check {
        color: var(--builtin-success, #16a34a);
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .cross {
        color: var(--builtin-danger, #dc2626);
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .blank {
        color: var(--builtin-color-muted, #9ca3af);
      }
      .cta-row td {
        padding: 18px;
      }
      .cta-btn {
        cursor: pointer;
        padding: 10px 18px;
        border-radius: var(--builtin-radius, 6px);
        border: 1px solid var(--builtin-border, #d1d5db);
        background: var(--builtin-surface, #ffffff);
        color: var(--builtin-color-text, #111827);
        font-weight: 600;
        font-size: 14px;
      }
      .cta-btn.highlight {
        background: var(--builtin-primary, #2563eb);
        border-color: var(--builtin-primary, #2563eb);
        color: #fff;
      }
      .cta-btn.highlight:hover {
        background: var(--builtin-primary-hover, #1d4ed8);
      }
      /* Mobile stacked cards */
      .cards {
        display: none;
        gap: 16px;
      }
      .card {
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius-lg, 8px);
        padding: 18px;
        background: var(--builtin-surface, #ffffff);
      }
      .card.highlight {
        border-color: var(--builtin-primary, #2563eb);
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
      }
      .card-header {
        text-align: center;
        margin-bottom: 14px;
      }
      .card-name {
        font-weight: 650;
        font-size: 16px;
      }
      .card-price {
        font-size: 28px;
        font-weight: 700;
      }
      .card-period {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
      }
      .card-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        font-size: 14px;
      }
      .card-row:last-child {
        border-bottom: none;
      }
      .card-cta {
        margin-top: 14px;
      }
      .card-cta button {
        width: 100%;
        cursor: pointer;
        padding: 10px;
        border-radius: var(--builtin-radius, 6px);
        border: 1px solid var(--builtin-border, #d1d5db);
        background: var(--builtin-surface, #ffffff);
        color: var(--builtin-color-text, #111827);
        font-weight: 600;
      }
      .card-cta button.highlight {
        background: var(--builtin-primary, #2563eb);
        border-color: var(--builtin-primary, #2563eb);
        color: #fff;
      }
      @media (max-width: 720px) {
        .table-wrap {
          display: none;
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
    this.plans = [];
    this.labels = {};
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

  _renderValue(feature) {
    if (feature.included === true) {
      return html`
        <span class="check">
          <builtin-icon name="check" size="20" variant="outlined"></builtin-icon>
        </span>
      `;
    }
    if (feature.included === false) {
      return html`
        <span class="cross">
          <builtin-icon name="close" size="20" variant="outlined"></builtin-icon>
        </span>
      `;
    }
    if (feature.value !== undefined && feature.value !== null && feature.value !== "") {
      return html`<span>${feature.value}</span>`;
    }
    return html`<span class="blank">—</span>`;
  }

  _onSelect(plan) {
    this.dispatchEvent(
      new CustomEvent("builtin-select", {
        bubbles: true,
        composed: true,
        detail: { plan },
      })
    );
  }

  render() {
    const plans = Array.isArray(this.plans) ? this.plans : [];
    const allFeatureLabels = [];
    const featureSet = new Set();
    plans.forEach((plan) => {
      (plan.features || []).forEach((f) => {
        const key = f.label || f.key;
        if (key && !featureSet.has(key)) {
          featureSet.add(key);
          allFeatureLabels.push({ key, label: f.label || f.key });
        }
      });
    });

    return html`
      <div data-theme="${this._ptTheme}">
        <div class="toolbar">
          <slot name="billing-toggle"></slot>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>${this._t("pricing.plan")}</th>
                ${plans.map((p) => html`
                  <th class="${classMap({ highlight: p.highlighted })}" style="min-width:160px;">
                    <div class="plan-name">${p.name || ""}</div>
                    <div class="plan-price">${p.price || ""}</div>
                    ${p.period ? html`<div class="plan-period">${p.period}</div>` : ""}
                  </th>
                `)}
              </tr>
            </thead>
            <tbody>
              ${allFeatureLabels.map((fl) => html`
                <tr>
                  <td>${fl.label}</td>
                  ${plans.map((p) => {
                    const feature = (p.features || []).find((f) => (f.label || f.key) === fl.key);
                    return html`
                      <td class="${classMap({ highlight: p.highlighted })}">
                        ${feature ? this._renderValue(feature) : html`<span class="blank">—</span>`}
                      </td>
                    `;
                  })}
                </tr>
              `)}
              <tr class="cta-row">
                <td></td>
                ${plans.map((p) => html`
                  <td class="${classMap({ highlight: p.highlighted })}">
                    <button
                      class="cta-btn ${classMap({ highlight: p.highlighted })}"
                      @click=${() => this._onSelect(p)}
                    >
                      ${this._t("pricing.select")}
                    </button>
                  </td>
                `)}
              </tr>
            </tbody>
          </table>
        </div>

        <div class="cards">
          ${plans.map((p) => html`
            <div class="card ${classMap({ highlight: p.highlighted })}">
              <div class="card-header">
                <div class="card-name">${p.name || ""}</div>
                <div class="card-price">${p.price || ""}</div>
                ${p.period ? html`<div class="card-period">${p.period}</div>` : ""}
              </div>
              ${allFeatureLabels.map((fl) => {
                const feature = (p.features || []).find((f) => (f.label || f.key) === fl.key);
                return html`
                  <div class="card-row">
                    <span>${fl.label}</span>
                    <span>${feature ? this._renderValue(feature) : html`<span class="blank">—</span>`}</span>
                  </div>
                `;
              })}
              <div class="card-cta">
                <button
                  class="${classMap({ highlight: p.highlighted })}"
                  @click=${() => this._onSelect(p)}
                >
                  ${this._t("pricing.select")}
                </button>
              </div>
            </div>
          `)}
        </div>
      </div>
    `;
  }
}
