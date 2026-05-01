import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) { if (!value) return undefined; try { return JSON.parse(value); } catch { return undefined; } },
  toAttribute(value) { return JSON.stringify(value); }
};

/**
 * @fileoverview BuiltinTplFileManager - Google Drive-style cloud file manager page.
 */
export class BuiltinTplFileManager extends BuiltinBaseElement {
  static properties = {
    brand: { type: String },
    userName: { type: String },
    userAvatar: { type: String },
    storageUsed: { type: String },
    storageTotal: { type: String },
    storagePercent: { type: Number },
    navItems: { type: Array, converter: jsonConverter },
    items: { type: Array, converter: jsonConverter },
      };

  static styles = css`
    :host { display: block; }
    .layout { display: flex; min-height: 100vh; }
    .sidebar { width: 240px; flex-shrink: 0; border-right: 1px solid var(--builtin-border-soft, #e5e7eb); background: var(--builtin-surface, #ffffff); }
    .main { flex: 1; padding: 20px; min-width: 0; }
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
    .storage { font-size: 13px; color: var(--builtin-color-muted, #6b7280); }
    .storage-bar { width: 160px; height: 6px; background: var(--builtin-border-soft, #e5e7eb); border-radius: 999px; overflow: hidden; margin-top: 4px; }
    .storage-fill { height: 100%; background: var(--builtin-primary, #2563eb); }
    .mobile-bar { display: none; padding: 10px 14px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); background: var(--builtin-surface, #ffffff); }
    @media (max-width: 720px) {
      .sidebar { display: none; }
      .mobile-bar { display: flex; align-items: center; gap: 10px; }
      .main { padding: 10px; }
    }
  `;

  constructor() {
    super();
    this.brand = "CloudDrive";
    this.userName = "User";
    this.userAvatar = "";
    this.storageUsed = "0 GB";
    this.storageTotal = "100 GB";
    this.storagePercent = 35;
    this.navItems = [];
    this.items = [];
  }

  _defaultNavItems() {
    return [
      {
        label: this.brand,
        items: [
          { label: "My Drive", href: "#", icon: "folder" },
          { label: "Shared with me", href: "#", icon: "team" },
          { label: "Recent", href: "#", icon: "clock-circle" },
          { label: "Starred", href: "#", icon: "star" },
          { label: "Trash", href: "#", icon: "delete" },
        ],
      },
    ];
  }

  render() {
    const navItems = this.navItems?.length ? this.navItems : (this._defaultNavItems());
    const items = this.items?.length ? this.items : [];

    return html`
      <builtin-navbar items='[]'>
        <div slot="start" style="display:flex;align-items:center;gap:10px;">
          <span style="font-weight:800;font-size:18px;">${this.brand}</span>
        </div>
        <div slot="end" style="display:flex;align-items:center;gap:10px;">
          <builtin-search-bar placeholder="${this._l("file.search", "Search files...")}" style="width:220px;"></builtin-search-bar>
          <builtin-user-menu name="${this.userName}" avatar="${this.userAvatar}"></builtin-user-menu>
        </div>
      </builtin-navbar>
      <div class="layout">
        <div class="sidebar">
          <builtin-sidebar items='${JSON.stringify(navItems)}'></builtin-sidebar>
        </div>
        <div class="main">
          <div class="mobile-bar">
            <builtin-icon name="menu" size="20" variant="outlined" @click="${() => this.dispatchEvent(new CustomEvent('builtin-toggle-sidebar', { bubbles: true, composed: true }))}"></builtin-icon>
            <span style="font-weight:700;">${this.brand}</span>
          </div>
          <div class="topbar">
            <h2 style="margin:0;font-size:18px;font-weight:700;color:var(--builtin-color-text);">${this._l("file.myDrive", "My Drive")}</h2>
            <div class="storage">
              <div>${this.storageUsed} / ${this.storageTotal} used</div>
              <div class="storage-bar"><div class="storage-fill" style="width: ${this.storagePercent}%"></div></div>
            </div>
          </div>
          <builtin-file-browser-cloud items='${JSON.stringify(items)}'></builtin-file-browser-cloud>
        </div>
      </div>
    `;
  }
}