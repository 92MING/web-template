import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinNotificationCenter — Bell-triggered notification dropdown / drawer.
 *
 * Attributes:
 *   - notifications: JSON array of { id, title, message, time, read, type }
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-read: Fired when a notification is marked read. Detail: { id }
 *   - builtin-clear: Fired when all notifications are cleared.
 *   - builtin-click: Fired when a notification is clicked. Detail: { id }
 */
export class BuiltinNotificationCenter extends BuiltinBaseElement {
  static properties = {
    notifications: { type: Array },
    labels: { type: Object },
    _open: { type: Boolean, state: true },
    _panelStyle: { type: String, state: true },
  };

  static styles = css`
    :host { display: inline-block; position: relative; }
    .trigger {
      position: relative; display: inline-flex; align-items: center; justify-content: center;
      background: transparent; border: none; padding: 6px; cursor: pointer;
      color: var(--builtin-color-text, #111827); border-radius: var(--builtin-radius, 6px);
    }
    .trigger:hover { background: var(--builtin-row-hover-bg, #f3f4f6); }
    .badge {
      position: absolute; top: 2px; right: 2px;
      background: var(--builtin-color-danger, #b91c1c); color: #fff;
      font-size: 10px; font-weight: 700; line-height: 1;
      padding: 2px 5px; border-radius: 999px; min-width: 16px; text-align: center;
      display: none;
    }
    .badge.show { display: inline-block; }
    .panel {
      position: fixed; z-index: 2000;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 10px 30px rgba(0,0,0,0.1);
      width: 380px; max-height: 480px; display: none; flex-direction: column; overflow: hidden;
    }
    .panel.open { display: flex; }
    .header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 10px 14px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .header-title { font-weight: 650; font-size: 14px; }
    .header-actions { display: flex; gap: 8px; }
    .header-actions button {
      background: transparent; border: none; padding: 4px 8px; cursor: pointer;
      color: var(--builtin-primary, #2563eb); font-size: 12px; border-radius: var(--builtin-radius, 6px);
    }
    .header-actions button:hover { background: var(--builtin-row-hover-bg, #f3f4f6); }
    .list { overflow-y: auto; flex: 1 1 auto; }
    .group-title {
      padding: 6px 14px; font-size: 12px; font-weight: 600;
      color: var(--builtin-color-muted, #6b7280); text-transform: uppercase; letter-spacing: 0.04em;
    }
    .notif {
      display: flex; gap: 10px; padding: 10px 14px; cursor: pointer;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .notif:hover { background: var(--builtin-row-hover-bg, #f3f4f6); }
    .notif.unread { background: var(--builtin-row-hover-bg, #f9fafb); }
    .notif-dot {
      width: 8px; height: 8px; border-radius: 50%; margin-top: 6px; flex-shrink: 0;
    }
    .notif-dot.info { background: var(--builtin-primary, #2563eb); }
    .notif-dot.success { background: #16a34a; }
    .notif-dot.warning { background: #d97706; }
    .notif-dot.error { background: var(--builtin-color-danger, #b91c1c); }
    .notif-body { flex: 1; min-width: 0; }
    .notif-title { font-weight: 600; font-size: 13px; color: var(--builtin-color-text, #111827); }
    .notif-message { font-size: 13px; color: var(--builtin-color-muted, #6b7280); margin-top: 2px; }
    .notif-time { font-size: 11px; color: var(--builtin-color-muted, #6b7280); margin-top: 4px; }
    .empty {
      padding: 28px 14px; text-align: center; color: var(--builtin-color-muted, #6b7280);
    }
    .drawer-mask {
      position: fixed; inset: 0; z-index: 9998; background: rgba(0,0,0,0.45); display: none;
    }
    .drawer-mask.open { display: block; }
    .drawer-panel {
      position: fixed; top: 0; right: 0; bottom: 0; z-index: 9999;
      background: var(--builtin-surface, #ffffff);
      width: 100%; max-width: 380px;
      transform: translateX(100%); transition: transform 0.25s ease;
      display: flex; flex-direction: column;
      box-shadow: 0 20px 60px rgba(0,0,0,0.18);
    }
    .drawer-panel.open { transform: translateX(0); }
    @media (max-width: 720px) {
      .panel { display: none !important; }
    }
  `;

  constructor() {
    super();
    this.notifications = [];
    this.labels = {};
    this._open = false;
    this._onDocClick = (e) => {
      if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
        this._open = false;
        this._panelStyle = "";
      }
    };
    this._onKeydown = (e) => {
      if (e.key === "Escape" && this._open) this._open = false;
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("click", this._onDocClick);
    document.addEventListener("keydown", this._onKeydown);
    window.addEventListener("resize", this._positionPanel);
    window.addEventListener("scroll", this._positionPanel, true);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("click", this._onDocClick);
    document.removeEventListener("keydown", this._onKeydown);
    window.removeEventListener("resize", this._positionPanel);
    window.removeEventListener("scroll", this._positionPanel, true);
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _unreadCount() {
    return (this.notifications || []).filter((n) => !n.read).length;
  }

  _groupByDate(notifs) {
    const groups = new Map();
    for (const n of notifs) {
      const date = this._parseTime(n.time);
      const d = date ? date.toDateString() : this._l("notification.unknownDate", "Earlier");
      if (!groups.has(d)) groups.set(d, []);
      groups.get(d).push(n);
    }
    return Array.from(groups.entries());
  }

  _parseTime(value) {
    if (!value) return null;
    if (value === "now") return new Date();
    const relative = String(value).match(/^(\d+)\s*([smhd])\s*ago$/i);
    if (relative) {
      const amount = Number(relative[1]);
      const unit = relative[2].toLowerCase();
      const scale = { s: 1000, m: 60000, h: 3600000, d: 86400000 }[unit] || 0;
      return new Date(Date.now() - amount * scale);
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  _formatTime(value) {
    const date = this._parseTime(value);
    if (!date) return this._l("notification.unknownDate", "Earlier");
    return date.toLocaleString();
  }

  _positionPanel = () => {
    if (!this._open || this._ptMobile) return;
    const trigger = this.renderRoot.querySelector(".trigger");
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(380, Math.max(280, window.innerWidth - 24));
    const left = Math.min(Math.max(12, rect.left), Math.max(12, window.innerWidth - width - 12));
    const top = Math.min(rect.bottom + 8, Math.max(12, window.innerHeight - 480 - 12));
    this._panelStyle = `left:${left}px;top:${top}px;width:${width}px`;
  };

  _toggleOpen() {
    this._open = !this._open;
    if (this._open) requestAnimationFrame(this._positionPanel);
  }

  _markAllRead() {
    for (const n of this.notifications || []) {
      if (!n.read) {
        n.read = true;
        this.dispatchEvent(
          new CustomEvent("builtin-read", { bubbles: true, composed: true, detail: { id: n.id } })
        );
      }
    }
    this.requestUpdate();
  }

  _clearAll() {
    this.notifications = [];
    this.dispatchEvent(new CustomEvent("builtin-clear", { bubbles: true, composed: true }));
  }

  _onNotifClick(n) {
    if (!n.read) {
      n.read = true;
      this.dispatchEvent(
        new CustomEvent("builtin-read", { bubbles: true, composed: true, detail: { id: n.id } })
      );
    }
    this.dispatchEvent(
      new CustomEvent("builtin-click", { bubbles: true, composed: true, detail: { id: n.id } })
    );
    this._open = false;
  }

  render() {
    const count = this._unreadCount();
    const notifs = this.notifications || [];
    const groups = this._groupByDate(notifs);
    const isMobile = this._ptMobile;

    return html`
      <button class="trigger" aria-label="${this._l("notification.notifications", "Notifications")}" @click="${this._toggleOpen}">
        <builtin-icon name="bell" size="20" variant="outlined"></builtin-icon>
        <span class="badge ${classMap({ show: count > 0 })}">${count > 99 ? "99+" : count}</span>
      </button>

      ${isMobile
        ? html`
          <div class="drawer-mask ${classMap({ open: this._open })}" @click="${() => { this._open = false; }}"></div>
          <div class="drawer-panel ${classMap({ open: this._open })}" role="dialog" aria-modal="true">
            ${this._renderPanelContent(notifs, groups)}
          </div>
        `
        : html`
          <div class="panel ${classMap({ open: this._open })}" style=${this._panelStyle}>
            ${this._renderPanelContent(notifs, groups)}
          </div>
        `}
    `;
  }

  _renderPanelContent(notifs, groups) {
    return html`
      <div class="header">
        <span class="header-title">${this._l("notification.title", "Notifications")}</span>
        <div class="header-actions">
          <button @click="${this._markAllRead}">${this._l("notification.markAllRead", "Mark all read")}</button>
          <button @click="${this._clearAll}">${this._l("notification.clear", "Clear")}</button>
        </div>
      </div>
      <div class="list">
        ${notifs.length === 0
          ? html`<div class="empty">${this._l("notification.empty", "No notifications")}</div>`
          : repeat(
              groups,
              (g) => g[0],
              (g) => html`
                <div class="group-title">${g[0]}</div>
                ${repeat(
                  g[1],
                  (n) => n.id,
                  (n) => html`
                    <div class="notif ${classMap({ unread: !n.read })}" @click="${() => this._onNotifClick(n)}">
                      <div class="notif-dot ${n.type || "info"}"></div>
                      <div class="notif-body">
                        <div class="notif-title">${n.title}</div>
                        ${n.message ? html`<div class="notif-message">${n.message}</div>` : ""}
                        ${n.time ? html`<div class="notif-time">${this._formatTime(n.time)}</div>` : ""}
                      </div>
                    </div>
                  `
                )}
              `
            )}
      </div>
    `;
  }
}
