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

export class BuiltinActivityFeed extends BuiltinBaseElement {
  static properties = {
    items: { type: Array, converter: jsonConverter },
    state: { type: String },
    emptyTitle: { type: String, attribute: "empty-title" },
    emptyDescription: { type: String, attribute: "empty-description" },
    errorTitle: { type: String, attribute: "error-title" },
    errorDescription: { type: String, attribute: "error-description" },
    loadingTitle: { type: String, attribute: "loading-title" },
    loadingDescription: { type: String, attribute: "loading-description" },
  };

  static styles = css`
    :host {
      display: block;
    }
    .feed {
      display: grid;
      gap: 12px;
    }
    .item {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 12px;
      padding: 16px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 16px);
      background: var(--builtin-surface, #ffffff);
    }
    .avatar {
      width: 38px;
      height: 38px;
      border-radius: 12px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: var(--builtin-primary-soft, #eff6ff);
      color: var(--builtin-primary, #2563eb);
      flex-shrink: 0;
    }
    .avatar.notice {
      background: color-mix(in srgb, var(--builtin-warning, #f59e0b) 14%, white);
      color: var(--builtin-warning, #f59e0b);
    }
    .avatar.success {
      background: color-mix(in srgb, var(--builtin-success, #16a34a) 14%, white);
      color: var(--builtin-success, #16a34a);
    }
    .content {
      min-width: 0;
      display: grid;
      gap: 8px;
    }
    .top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .title {
      margin: 0;
      color: var(--builtin-color-text, #111827);
      font-size: 16px;
      font-weight: 700;
    }
    .time {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
      white-space: nowrap;
    }
    .description {
      margin: 0;
      color: var(--builtin-color-muted, #6b7280);
      line-height: 1.6;
      font-size: 14px;
    }
    .meta {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
    }
    .meta-chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 8px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: 999px;
      background: var(--builtin-header-bg, #f9fafb);
    }
    .actions {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 34px;
      padding: 0 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 999px;
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      font: inherit;
      cursor: pointer;
      text-decoration: none;
    }
    .btn:hover {
      background: var(--builtin-button-hover-bg, #f9fafb);
    }
    @media (max-width: 720px) {
      .item {
        padding: 14px;
      }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.state = "ready";
    this.emptyTitle = "";
    this.emptyDescription = "";
    this.errorTitle = "";
    this.errorDescription = "";
    this.loadingTitle = "";
    this.loadingDescription = "";
  }

  _itemSlotName(index) {
    return `item-${index}`;
  }

  _actionSlotName(index) {
    return `item-actions-${index}`;
  }

  _emitAction(item) {
    this.dispatchEvent(new CustomEvent("builtin-item-action", {
      bubbles: true,
      composed: true,
      detail: { item, action: item.action || item.actionLabel },
    }));
  }

  _renderState() {
    if (this.state === "loading") {
      return html`
        <builtin-empty-state
          preset="loading"
          .heading=${this.loadingTitle}
          .description=${this.loadingDescription}
        ></builtin-empty-state>
      `;
    }
    if (this.state === "error") {
      return html`
        <builtin-empty-state
          preset="error"
          .heading=${this.errorTitle}
          .description=${this.errorDescription}
        ></builtin-empty-state>
      `;
    }
    return html`
      <builtin-empty-state
        .heading=${this.emptyTitle}
        .description=${this.emptyDescription}
      ></builtin-empty-state>
    `;
  }

  render() {
    const items = Array.isArray(this.items) ? this.items : [];
    if (this.state === "loading" || this.state === "error" || !items.length) {
      return this._renderState();
    }
    return html`
      <div class="feed">
        ${items.map((item, index) => html`
          <article class="item">
            <div class="avatar ${classMap({ notice: item.tone === "notice", success: item.tone === "success" })}">
              <builtin-icon name="${item.icon || "notification"}" size="18"></builtin-icon>
            </div>
            <div class="content">
              <div class="top">
                <h3 class="title">${item.title || ""}</h3>
                ${item.time ? html`<div class="time">${item.time}</div>` : null}
              </div>
              ${item.description ? html`<p class="description">${item.description}</p>` : null}
              ${Array.isArray(item.meta) && item.meta.length ? html`
                <div class="meta">
                  ${item.meta.map((meta) => html`<span class="meta-chip">${meta}</span>`)}
                </div>
              ` : null}
              <slot name="${this._itemSlotName(index)}"></slot>
              ${(item.actionLabel || item.actionHref) ? html`
                <div class="actions">
                  ${item.actionHref
                    ? html`<a class="btn" href="${item.actionHref}">${item.actionLabel || item.actionHref}</a>`
                    : html`<button type="button" class="btn" @click=${() => this._emitAction(item)}>${item.actionLabel}</button>`}
                  <slot name="${this._actionSlotName(index)}"></slot>
                </div>
              ` : html`<slot name="${this._actionSlotName(index)}"></slot>`}
            </div>
          </article>
        `)}
      </div>
    `;
  }
}