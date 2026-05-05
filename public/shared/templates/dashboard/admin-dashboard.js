import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, nothing } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

/**
 * @fileoverview BuiltinTplDashboardAdmin - Admin / management dashboard template.
 *
 * Attributes:
 *   - labels: JSON object to override i18n strings
 *
 * Slots:
 *   - sidebar: Sidebar navigation with nav groups
 *   - header: Top header content
 *   - widgets: Custom widget grid content
 *   - footer: Footer content
 */
export class BuiltinTplDashboardAdmin extends BuiltinBaseElement {
  static properties = {
    widgets: { type: Object, converter: jsonConverter },
    labels: { type: Object, converter: jsonConverter },
        _sidebarOpen: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; min-height: 100vh; }
    .layout { display: flex; min-height: 100vh; }
    .sidebar {
      width: 260px; border-right: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff); flex-shrink: 0;
      display: flex; flex-direction: column;
    }
    .sidebar-header {
      padding: 16px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); font-weight: 650;
      display: flex; align-items: center; gap: 8px;
    }
    .sidebar-body { padding: 12px; flex: 1; }
    .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    .topbar {
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 12px 16px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .content { padding: 16px; flex: 1; }
    .widget-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
    .widget {
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff); padding: 16px;
    }
    .widget-title {
      font-weight: 650; margin-bottom: 10px; color: var(--builtin-color-text, #111827);
      display: flex; align-items: center; gap: 6px;
    }
    .widget-value { font-size: 22px; font-weight: 700; color: var(--builtin-primary, #2563eb); }
    .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #22c55e; margin-right: 6px; }
    .status-dot.warn { background: #f59e0b; }
    .status-dot.error { background: #ef4444; }
    .order-item { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .order-item:last-child { border-bottom: none; }
    .quick-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    .quick-actions button {
      padding: 6px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      cursor: pointer;
      font: inherit;
      color: inherit;
    }
    .quick-actions button:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .notification-item { padding: 8px 0; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); font-size: 13px; }
    .notification-item:last-child { border-bottom: none; }
    .calendar-placeholder {
      height: 180px; display: flex; align-items: center; justify-content: center;
      border: 2px dashed var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px);
      color: var(--builtin-color-muted, #6b7280);
    }
    .footer {
      padding: 12px 16px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb); color: var(--builtin-color-muted, #6b7280); font-size: 12px;
    }
    .hamburger {
      display: none;
      padding: 6px 10px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      cursor: pointer;
      align-items: center;
      justify-content: center;
    }
    .icon { width: 16px; height: 16px; vertical-align: middle; }

    @media (max-width: 720px) {
      .sidebar {
        position: fixed; inset: 0 auto 0 0; z-index: 50;
        transform: translateX(-100%); transition: transform .2s ease;
      }
      .sidebar.open { transform: translateX(0); }
      .hamburger { display: inline-flex; }
      .widget-grid { grid-template-columns: 1fr; }
      .topbar { flex-wrap: wrap; }
    }
  `;

  constructor() {
    super();
    this._sidebarOpen = false;
    this.widgets = {};
  }

  _defaultWidgets() {
    return {
      users: { value: "8,420", change: "+120 this week" },
      orders: [
        { id: "#1024", amount: "$120" },
        { id: "#1023", amount: "$85" },
        { id: "#1022", amount: "$240" },
      ],
      servers: [
        { name: "Web", status: "ok" },
        { name: "DB", status: "ok" },
        { name: "Cache", status: "warn" },
      ],
      actions: ["Add User", "New Order", "Export"],
      notifications: [
        { text: "New signup from", highlight: "alice" },
        { text: "Order #1024 shipped" },
        { text: "Server backup completed" },
      ],
      calendar: true,
    };
  }

  _w(key) {
    const custom = this.widgets || {};
    if (custom[key] !== undefined) return custom[key];
    return this._defaultWidgets()[key];
  }

  _toggleSidebar() {
    this._sidebarOpen = !this._sidebarOpen;
  }

  _hasSlot(name) {
    return Array.from(this.children || []).some((node) => node.slot === name);
  }

  _renderWidgetGrid() {
    const users = this._w("users");
    const orders = this._w("orders");
    const servers = this._w("servers");
    const actions = this._w("actions");
    const notifications = this._w("notifications");
    const calendar = this._w("calendar");
    const widgets = [];

    if (users) {
      widgets.push(html`
        <div class="widget">
          <div class="widget-title">
            <builtin-icon name="team" size="16" variant="outlined"></builtin-icon>
            ${this._l("widget.users", "Users")}
          </div>
          <div class="widget-value">${users.value || "0"}</div>
          <div style="margin-top:6px; font-size:12px; color: var(--builtin-color-muted, #6b7280);">${users.change || ""}</div>
        </div>
      `);
    }

    if (Array.isArray(orders) && orders.length) {
      widgets.push(html`
        <div class="widget">
          <div class="widget-title">
            <builtin-icon name="shopping" size="16" variant="outlined"></builtin-icon>
            ${this._l("widget.orders", "Recent Orders")}
          </div>
          ${orders.map((order) => html`
            <div class="order-item"><span>${order.id}</span><span style="color: var(--builtin-color-muted, #6b7280);">${order.amount}</span></div>
          `)}
        </div>
      `);
    }

    if (Array.isArray(servers) && servers.length) {
      widgets.push(html`
        <div class="widget">
          <div class="widget-title">
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
            ${this._l("widget.server", "Server Status")}
          </div>
          ${servers.map((server) => html`
            <div style="margin-top:6px;"><span class="status-dot ${server.status === "warn" ? "warn" : server.status === "error" ? "error" : ""}"></span>${server.name}</div>
          `)}
        </div>
      `);
    }

    if (Array.isArray(actions) && actions.length) {
      widgets.push(html`
        <div class="widget">
          <div class="widget-title">
            <builtin-icon name="thunderbolt" size="16" variant="outlined"></builtin-icon>
            ${this._l("widget.actions", "Quick Actions")}
          </div>
          <div class="quick-actions">
            ${actions.map((action) => html`
              <button type="button" @click="${() => this.dispatchEvent(new CustomEvent('builtin-action', { bubbles: true, composed: true, detail: { action } }))}">${action}</button>
            `)}
          </div>
        </div>
      `);
    }

    if (Array.isArray(notifications) && notifications.length) {
      widgets.push(html`
        <div class="widget">
          <div class="widget-title">
            <builtin-icon name="bell" size="16" variant="outlined"></builtin-icon>
            ${this._l("widget.notifications", "Notifications")}
          </div>
          ${notifications.map((notification) => html`
            <div class="notification-item">${notification.text}${notification.highlight ? html` <strong>${notification.highlight}</strong>` : ""}</div>
          `)}
        </div>
      `);
    }

    if (calendar) {
      widgets.push(html`
        <div class="widget">
          <div class="widget-title">
            <builtin-icon name="calendar" size="16" variant="outlined"></builtin-icon>
            ${this._l("widget.calendar", "Calendar")}
          </div>
          <div class="calendar-placeholder">${this._l("calendar.placeholder", "Calendar Placeholder")}</div>
        </div>
      `);
    }

    if (!widgets.length) return null;
    return html`<div class="widget-grid">${widgets}</div>`;
  }

  render() {
    const widgetGrid = this._renderWidgetGrid();
    const hasFooter = this._hasSlot("footer");
    return html`
      <div class="layout">
        <aside class="sidebar ${classMap({ open: this._sidebarOpen })}">
          <div class="sidebar-header">
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            ${this._l("sidebar.title", "Admin")}
          </div>
          <div class="sidebar-body"><slot name="sidebar"></slot></div>
        </aside>
        <div class="main">
          <div class="topbar">
            <button type="button" class="hamburger" @click=${this._toggleSidebar} aria-label="${this._l("sidebar.toggle", "Toggle sidebar")}">
              <builtin-icon name="menu" size="16" variant="outlined"></builtin-icon>
            </button>
            <div><slot name="header"></slot></div>
          </div>
          <div class="content">
            <slot name="widgets">
              ${widgetGrid}
            </slot>
          </div>
          ${hasFooter ? html`<div class="footer"><slot name="footer"></slot></div>` : nothing}
        </div>
      </div>
    `;
  }
}