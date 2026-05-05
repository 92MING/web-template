import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinFileBrowser — File and folder browser.
 *
 * Attributes:
 * - `items` (JSON): `[{name, type: 'file'|'folder', size, modified, selected}]`
 * - `view`: `grid` | `list`
 * - `path` (string): Current breadcrumb path (comma or slash separated)
 * - `labels` (JSON object for local i18n overrides)
 *
 * Slots:
 * - `upload-button`: Upload action button.
 *
 * Events:
 * - `builtin-open` — Double-clicked a folder. Detail: `{ item }`
 * - `builtin-select` — Selection changed. Detail: `{ items }`
 * - `builtin-upload` — Upload button clicked. Detail: `{}`
 * - `builtin-delete` — Delete button clicked for selected items. Detail: `{ items }`
 */
export class BuiltinFileBrowser extends BuiltinBaseElement {
  static get properties() {
    return {
      items: {
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
      view: { type: String },
      path: { type: String },
      searchable: { type: Boolean },
      searchPlaceholder: { type: String, attribute: "search-placeholder" },
      sortBy: { type: String, attribute: "sort-by" },
      sortDirection: { type: String, attribute: "sort-direction" },
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
      .browser {
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
        overflow: hidden;
      }
      .toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 10px 12px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        flex-wrap: wrap;
      }
      .breadcrumbs {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
        flex-wrap: wrap;
      }
      .breadcrumb-sep {
        color: var(--builtin-color-muted, #9ca3af);
      }
      .breadcrumb-item {
        cursor: pointer;
        padding: 2px 6px;
        border-radius: var(--builtin-radius, 6px);
      }
      .breadcrumb-item:hover {
        background: var(--builtin-row-hover-bg, #f9fafb);
        color: var(--builtin-color-text, #111827);
      }
      .breadcrumb-item:last-child {
        font-weight: 600;
        color: var(--builtin-color-text, #111827);
        cursor: default;
        background: transparent;
      }
      .actions {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
      }
      .toolbar-left {
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-width: 0;
        flex: 1 1 280px;
      }
      .toolbar-right {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
      }
      .toolbar-controls {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      .search-input,
      .sort-select {
        min-height: 34px;
        padding: 0 10px;
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-input-bg, #ffffff);
        color: inherit;
        font: inherit;
      }
      .search-input {
        min-width: 180px;
      }
      .icon-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: var(--builtin-radius, 6px);
        border: 1px solid var(--builtin-border, #d1d5db);
        background: var(--builtin-surface, #ffffff);
        color: var(--builtin-color-text, #111827);
        cursor: pointer;
      }
      .icon-btn:hover {
        background: var(--builtin-row-hover-bg, #f9fafb);
      }
      .icon-btn.active {
        background: var(--builtin-primary-soft, #eff6ff);
        border-color: var(--builtin-primary, #2563eb);
        color: var(--builtin-primary, #2563eb);
      }
      .danger-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        padding: 6px 10px;
        border-radius: var(--builtin-radius, 6px);
        border: 1px solid var(--builtin-border, #d1d5db);
        background: var(--builtin-surface, #ffffff);
        color: var(--builtin-danger, #dc2626);
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
      }
      .danger-btn:hover {
        background: var(--builtin-danger-soft, #fef2f2);
      }
      .content {
        padding: 8px;
        min-height: 200px;
      }
      /* List view */
      .list-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
      }
      .list-table th {
        text-align: left;
        padding: 8px 10px;
        font-size: 12px;
        font-weight: 600;
        color: var(--builtin-color-muted, #6b7280);
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        white-space: nowrap;
      }
      .list-table td {
        padding: 8px 10px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        color: var(--builtin-color-text, #111827);
        vertical-align: middle;
      }
      .list-table tr:hover td {
        background: var(--builtin-row-hover-bg, #f9fafb);
      }
      .list-table tr.selected td {
        background: var(--builtin-primary-soft, #eff6ff);
      }
      .file-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 20px;
        height: 20px;
        color: var(--builtin-color-muted, #6b7280);
        flex-shrink: 0;
      }
      .file-name {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
      }
      .file-name:hover {
        color: var(--builtin-primary, #2563eb);
      }
      .checkbox {
        width: 16px;
        height: 16px;
        cursor: pointer;
      }
      /* Grid view */
      .grid-view {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
        gap: 12px;
      }
      .grid-item {
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: var(--builtin-radius-lg, 8px);
        padding: 14px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        cursor: pointer;
        position: relative;
        background: var(--builtin-surface, #ffffff);
        transition: box-shadow 0.15s ease;
      }
      .grid-item:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
      }
      .grid-item.selected {
        border-color: var(--builtin-primary, #2563eb);
        background: var(--builtin-primary-soft, #eff6ff);
      }
      .grid-item .file-icon {
        width: 40px;
        height: 40px;
        color: var(--builtin-color-muted, #6b7280);
      }
      .grid-item .file-name {
        font-size: 12px;
        text-align: center;
        word-break: break-word;
        width: 100%;
        justify-content: center;
      }
      .grid-check {
        position: absolute;
        top: 8px;
        left: 8px;
      }
      .meta {
        font-size: 11px;
        color: var(--builtin-color-muted, #9ca3af);
      }
      .item-actions {
        display: inline-flex;
        align-items: center;
        justify-content: flex-end;
        gap: 6px;
      }
      .empty {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
        padding: 24px;
        text-align: center;
      }
      @media (max-width: 720px) {
        .toolbar {
          padding: 8px;
        }
        .grid-view {
          grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
          gap: 8px;
        }
        .grid-item {
          padding: 12px;
          min-height: 100px;
        }
        .list-table th,
        .list-table td {
          padding: 10px 8px;
        }
        .file-name {
          gap: 10px;
        }
        .checkbox {
          width: 20px;
          height: 20px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.items = [];
    this.view = "list";
    this.path = "";
    this.searchable = false;
    this.searchPlaceholder = "";
    this.sortBy = "name";
    this.sortDirection = "asc";
    this.labels = {};
    this._searchQuery = "";
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

  _breadcrumbs() {
    const raw = this.path || "";
    if (!raw) return [this._t("files.home", "Home")];
    return raw.split(/[\/,:]/).filter(Boolean);
  }

  _hasItemActionSlots() {
    return Array.from(this.children || []).some((node) => String(node.slot || "").startsWith("item-action-"));
  }

  _itemActionSlot(item, index) {
    return `item-action-${item.id ?? item.path ?? index}`;
  }

  _visibleItems() {
    const query = this._searchQuery.trim().toLowerCase();
    const direction = this.sortDirection === "desc" ? -1 : 1;
    let items = Array.isArray(this.items) ? this.items.slice() : [];
    if (query) {
      items = items.filter((item) => [item.name, item.size, item.modified, item.type].some((value) => String(value || "").toLowerCase().includes(query)));
    }
    if (this.sortBy) {
      items.sort((left, right) => String(left?.[this.sortBy] ?? "").localeCompare(String(right?.[this.sortBy] ?? ""), undefined, { numeric: true, sensitivity: "base" }) * direction);
    }
    return items;
  }

  _toggleSelect(item, e) {
    if (e) e.stopPropagation();
    item.selected = !item.selected;
    this.requestUpdate();
    const selected = (this.items || []).filter((i) => i.selected);
    this.dispatchEvent(
      new CustomEvent("builtin-select", {
        bubbles: true,
        composed: true,
        detail: { items: selected },
      })
    );
  }

  _onOpen(item) {
    if (item.type === "folder") {
      this.dispatchEvent(
        new CustomEvent("builtin-open", {
          bubbles: true,
          composed: true,
          detail: { item },
        })
      );
    }
  }

  _onBreadcrumb(index, crumb) {
    this.dispatchEvent(
      new CustomEvent("builtin-breadcrumb", {
        bubbles: true,
        composed: true,
        detail: { index, crumb, items: this._breadcrumbs().slice(0, index + 1) },
      })
    );
  }

  _onUpload() {
    this.dispatchEvent(
      new CustomEvent("builtin-upload", {
        bubbles: true,
        composed: true,
        detail: {},
      })
    );
  }

  _onDelete() {
    const selected = (this.items || []).filter((i) => i.selected);
    if (!selected.length) return;
    this.dispatchEvent(
      new CustomEvent("builtin-delete", {
        bubbles: true,
        composed: true,
        detail: { items: selected },
      })
    );
  }

  _folderIcon() {
    return html`
      <builtin-icon name="folder" size="20" variant="outlined"></builtin-icon>
    `;
  }

  _fileIcon() {
    return html`
      <builtin-icon name="file" size="20" variant="outlined"></builtin-icon>
    `;
  }

  _renderList() {
    const items = this._visibleItems();
    const hasItemActions = this._hasItemActionSlots();
    return html`
      <table class="list-table">
        <thead>
          <tr>
            <th style="width:32px;">
              <input
                class="checkbox"
                type="checkbox"
                .checked=${items.length > 0 && items.every((i) => i.selected)}
                @change=${(e) => {
                  const checked = e.target.checked;
                  items.forEach((i) => (i.selected = checked));
                  this.requestUpdate();
                  this.dispatchEvent(
                    new CustomEvent("builtin-select", {
                      bubbles: true,
                      composed: true,
                      detail: { items: items.filter((i) => i.selected) },
                    })
                  );
                }}
              />
            </th>
            <th>${this._t("files.name")}</th>
            <th>${this._t("files.size")}</th>
            <th>${this._t("files.modified")}</th>
            ${hasItemActions ? html`<th style="width:1%;">${this._t("files.actions", "Actions")}</th>` : null}
          </tr>
        </thead>
        <tbody>
          ${items.map((item, index) => html`
            <tr
              class="${classMap({ selected: item.selected })}"
              @dblclick=${() => this._onOpen(item)}
            >
              <td>
                <input
                  class="checkbox"
                  type="checkbox"
                  .checked=${!!item.selected}
                  @change=${(e) => this._toggleSelect(item, e)}
                />
              </td>
              <td>
                <span class="file-name">
                  <span class="file-icon">${item.type === "folder" ? this._folderIcon() : this._fileIcon()}</span>
                  ${item.name || ""}
                </span>
              </td>
              <td>${item.size || "—"}</td>
              <td>${item.modified || "—"}</td>
              ${hasItemActions ? html`<td><div class="item-actions"><slot name="${this._itemActionSlot(item, index)}"></slot></div></td>` : null}
            </tr>
          `)}
          ${items.length === 0 ? html`
            <tr><td colspan="${hasItemActions ? 5 : 4}"><div class="empty">${this._t("files.empty")}</div></td></tr>
          ` : ""}
        </tbody>
      </table>
    `;
  }

  _renderGrid() {
    const items = this._visibleItems();
    const hasItemActions = this._hasItemActionSlots();
    return html`
      <div class="grid-view">
        ${items.map((item, index) => html`
          <div
            class="grid-item ${classMap({ selected: item.selected })}"
            @dblclick=${() => this._onOpen(item)}
            @click=${() => this._toggleSelect(item)}
          >
            <div class="grid-check">
              <input
                class="checkbox"
                type="checkbox"
                .checked=${!!item.selected}
                @change=${(e) => this._toggleSelect(item, e)}
              />
            </div>
            <div class="file-icon">${item.type === "folder" ? this._folderIcon() : this._fileIcon()}</div>
            <span class="file-name">${item.name || ""}</span>
            <span class="meta">${item.size || ""}</span>
            ${hasItemActions ? html`<div class="item-actions"><slot name="${this._itemActionSlot(item, index)}"></slot></div>` : null}
          </div>
        `)}
        ${items.length === 0 ? html`<div class="empty" style="grid-column:1/-1;">${this._t("files.empty")}</div>` : ""}
      </div>
    `;
  }

  render() {
    const crumbs = this._breadcrumbs();
    const selectedCount = (this.items || []).filter((i) => i.selected).length;
    const effectiveView = this._ptMobile ? "list" : this.view;
    return html`
      <div class="browser">
        <div class="toolbar">
          <div class="toolbar-left">
            <div class="breadcrumbs">
              ${crumbs.map((crumb, i) => html`
                ${i > 0 ? html`<span class="breadcrumb-sep">/</span>` : ""}
                <span class="breadcrumb-item" @click=${() => i < crumbs.length - 1 ? this._onBreadcrumb(i, crumb) : null}>${crumb}</span>
              `)}
            </div>
            ${this.searchable ? html`
              <div class="toolbar-controls">
                <input
                  class="search-input"
                  type="search"
                  .value=${this._searchQuery}
                  placeholder="${this.searchPlaceholder || this._t("files.search", "Search files")}" 
                  @input=${(e) => { this._searchQuery = e.target.value; }}
                />
                <select class="sort-select" .value=${this.sortBy} @change=${(e) => { this.sortBy = e.target.value; }}>
                  <option value="name">${this._t("files.sortName", "Sort by name")}</option>
                  <option value="modified">${this._t("files.sortModified", "Sort by modified")}</option>
                  <option value="size">${this._t("files.sortSize", "Sort by size")}</option>
                  <option value="type">${this._t("files.sortType", "Sort by type")}</option>
                </select>
                <select class="sort-select" .value=${this.sortDirection} @change=${(e) => { this.sortDirection = e.target.value; }}>
                  <option value="asc">${this._t("files.sortAsc", "Ascending")}</option>
                  <option value="desc">${this._t("files.sortDesc", "Descending")}</option>
                </select>
              </div>
            ` : null}
          </div>
          <div class="toolbar-right">
            <div class="actions">
            <slot name="upload-button">
              <button class="icon-btn" @click=${this._onUpload} aria-label="${this._t("files.upload")}">
                <builtin-icon name="cloud-upload" size="16" variant="outlined"></builtin-icon>
              </button>
            </slot>
            <button
              class="icon-btn ${classMap({ active: effectiveView === "list" })}"
              @click=${() => (this.view = "list")}
              aria-label="${this._t("files.listView")}"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="8" y1="6" x2="21" y2="6"/>
                <line x1="8" y1="12" x2="21" y2="12"/>
                <line x1="8" y1="18" x2="21" y2="18"/>
                <line x1="3" y1="6" x2="3.01" y2="6"/>
                <line x1="3" y1="12" x2="3.01" y2="12"/>
                <line x1="3" y1="18" x2="3.01" y2="18"/>
              </svg>
            </button>
            <button
              class="icon-btn ${classMap({ active: effectiveView === "grid" })}"
              @click=${() => (this.view = "grid")}
              aria-label="${this._t("files.gridView")}"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="7" height="7"/>
                <rect x="14" y="3" width="7" height="7"/>
                <rect x="14" y="14" width="7" height="7"/>
                <rect x="3" y="14" width="7" height="7"/>
              </svg>
            </button>
            ${selectedCount > 0
              ? html`
                  <button class="danger-btn" @click=${this._onDelete}>
                    <builtin-icon name="delete" size="16" variant="outlined"></builtin-icon>
                    ${this._t("files.delete")} (${selectedCount})
                  </button>
                `
              : ""}
            </div>
          </div>
        </div>
        <div class="content">
          ${effectiveView === "grid" ? this._renderGrid() : this._renderList()}
        </div>
      </div>
    `;
  }
}
