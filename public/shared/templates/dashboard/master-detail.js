import { BuiltinBaseElement, html, css, classMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

export class BuiltinTplDashboardMasterDetail extends BuiltinBaseElement {
  static properties = {
    masterTitle: { type: String, attribute: "master-title" },
    masterSubtitle: { type: String, attribute: "master-subtitle" },
    detailTitle: { type: String, attribute: "detail-title" },
    detailSubtitle: { type: String, attribute: "detail-subtitle" },
    masterItems: { type: Array, converter: jsonConverter },
    detailContent: { type: String },
    masterSelectedId: { type: String, attribute: "master-selected-id" },
      };

  static styles = css`
    :host {
      display: block;
    }
    .shell {
      display: grid;
      gap: 16px;
    }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .panel {
      min-width: 0;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-xl, 20px);
      background: var(--builtin-surface, #ffffff);
      overflow: hidden;
      box-shadow: 0 12px 40px rgba(15, 23, 42, 0.06);
    }
    .panel-head {
      padding: 16px 18px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .panel-copy {
      min-width: 0;
      display: grid;
      gap: 6px;
    }
    .panel-title {
      margin: 0;
      color: var(--builtin-color-text, #111827);
      font-size: 18px;
      font-weight: 700;
    }
    .panel-subtitle {
      margin: 0;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      line-height: 1.5;
    }
    .panel-body {
      padding: 18px;
      min-width: 0;
    }
    .master-list {
      display: grid;
      gap: 8px;
    }
    .master-item {
      padding: 12px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      outline: none;
    }
    .master-item:hover, .master-item:focus {
      background: var(--builtin-row-hover-bg, #f9fafb);
      border-color: var(--builtin-border, #d1d5db);
    }
    .master-item.selected {
      border-color: var(--builtin-primary, #2563eb);
      background: rgba(37, 99, 235, 0.06);
    }
    .master-item-title {
      font-weight: 600;
      color: var(--builtin-color-text, #111827);
      font-size: 14px;
    }
    .master-item-subtitle {
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      margin-top: 4px;
    }
    .detail-content {
      color: var(--builtin-color-text, #111827);
      line-height: 1.6;
    }
    @media (max-width: 900px) {
      .layout {
        grid-template-columns: 1fr;
      }
    }
  `;

  constructor() {
    super();
    this.masterTitle = "";
    this.masterSubtitle = "";
    this.detailTitle = "";
    this.detailSubtitle = "";
    this.masterItems = [];
    this.detailContent = "";
    this.masterSelectedId = "";
  }

  _hasSlot(name) {
    return Array.from(this.children || []).some((node) => node.slot === name);
  }

  _defaultMasterItems() {
    return [
      { id: "1", title: "Item 1", subtitle: "Desc" },
      { id: "2", title: "Item 2", subtitle: "Desc" },
      { id: "3", title: "Item 3", subtitle: "Desc" },
      { id: "4", title: "Item 4", subtitle: "Desc" },
    ];
  }

  _defaultDetailContent() {
    return html`
      <div>
        <h3>Detail Title</h3>
        <p>Select an item from the master list to view its details here.</p>
      </div>
    `;
  }

  render() {
    const masterItems = this.masterItems?.length ? this.masterItems : (this._defaultMasterItems());
    const detailContent = this.detailContent || (this._defaultDetailContent());

    return html`
      <div class="shell">
        ${this._hasSlot("toolbar") ? html`<div class="toolbar"><slot name="toolbar"></slot></div>` : nothing}
        <div class="layout">
          <section class="panel">
            <div class="panel-head">
              <div class="panel-copy">
                ${this.masterTitle ? html`<h2 class="panel-title">${this.masterTitle}</h2>` : nothing}
                ${this.masterSubtitle ? html`<p class="panel-subtitle">${this.masterSubtitle}</p>` : nothing}
              </div>
              <slot name="master-actions"></slot>
            </div>
            <div class="panel-body">
              ${masterItems.length ? html`
                <div class="master-list">
                  ${repeat(masterItems, (item) => item.id, (item) => html`
                    <div class="master-item ${classMap({ selected: item.id === this.masterSelectedId })}"
                         @click="${() => { this.masterSelectedId = item.id; this.dispatchEvent(new CustomEvent('builtin-master-select', { bubbles: true, composed: true, detail: { id: item.id } })); }}"
                         @keydown="${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.masterSelectedId = item.id; } }}"
                         tabindex="0"
                         role="button"
                         aria-pressed="${item.id === this.masterSelectedId}">
                      <div class="master-item-title">${item.title}</div>
                      ${item.subtitle ? html`<div class="master-item-subtitle">${item.subtitle}</div>` : nothing}
                    </div>
                  `)}
                </div>
              ` : html`<slot name="master"><builtin-empty-state preset="search"></builtin-empty-state></slot>`}
            </div>
          </section>
          <section class="panel">
            <div class="panel-head">
              <div class="panel-copy">
                ${this.detailTitle ? html`<h2 class="panel-title">${this.detailTitle}</h2>` : nothing}
                ${this.detailSubtitle ? html`<p class="panel-subtitle">${this.detailSubtitle}</p>` : nothing}
              </div>
              <slot name="detail-actions"></slot>
            </div>
            <div class="panel-body">
              ${detailContent ? html`<div class="detail-content">${detailContent}</div>` : html`<slot name="detail"><builtin-empty-state></builtin-empty-state></slot>`}
            </div>
          </section>
        </div>
      </div>
    `;
  }
}