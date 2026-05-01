import { BuiltinBaseElement, html, css, classMap, nothing } from '../../components/lit-base.js';

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

export class BuiltinTplDashboardWorkspace extends BuiltinBaseElement {
  static properties = {
    labels: { type: Object, converter: jsonConverter },
    sidebarOpen: { type: Boolean, state: true },
    widgets: { type: Array },
    projects: { type: Array },
    activities: { type: Array },
      };

  static styles = css`
    :host { display: block; min-height: 100vh; }
    .layout { display: flex; min-height: 100vh; }
    .sidebar {
      width: 260px;
      border-right: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      flex-shrink: 0;
      display: flex;
      flex-direction: column;
    }
    .sidebar-header {
      padding: 16px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .sidebar-body { padding: 12px; flex: 1; }
    .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
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
    .content { padding: 16px; flex: 1; display: grid; gap: 16px; }
    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
      gap: 16px;
      align-items: stretch;
    }
    .hero-panel,
    .profile-panel,
    .stats-panel,
    .tiles-panel {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      overflow: hidden;
    }
    .hero-panel,
    .profile-panel,
    .stats-panel { padding: 20px; }
    .hero-panel ::slotted(.workspace-eyebrow) {
      display: block;
      color: var(--builtin-primary, #2563eb);
      font-weight: 800;
      letter-spacing: .14em;
      text-transform: uppercase;
      font-size: 12px;
      margin-bottom: 14px;
    }
    .hero-panel ::slotted(.workspace-title) {
      display: block;
      margin: 0 0 16px;
      font-size: clamp(28px, 4vw, 48px);
      line-height: .95;
      letter-spacing: -.05em;
      color: var(--builtin-color-text, #111827);
      font-weight: 800;
    }
    .hero-panel ::slotted(.workspace-lead) {
      display: block;
      margin: 0;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 16px;
      line-height: 1.7;
    }
    .hero-panel ::slotted(.workspace-actions) {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 20px;
    }
    .profile-panel ::slotted(.workspace-profile-name) {
      display: block;
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -.04em;
      color: var(--builtin-color-text, #111827);
    }
    .profile-panel ::slotted(.workspace-profile-role) {
      display: block;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 14px;
      margin-top: 6px;
    }
    .profile-panel ::slotted(.workspace-profile-status) {
      display: block;
      margin-top: 14px;
    }
    .stats-panel::before,
    .tiles-panel::before {
      content: '';
      display: block;
    }
    .stats-panel ::slotted(.workspace-stats-grid) {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .tiles-panel { padding: 20px; }
    .tiles-panel ::slotted(.workspace-tile-grid) {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
    }
    .tiles-panel ::slotted(.workspace-tile-grid.teacher-tiles) {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .tiles-panel ::slotted(.workspace-tile) {
      min-height: 160px;
      padding: 20px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      text-decoration: none;
      color: inherit;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform .18s ease, border-color .18s ease;
      box-sizing: border-box;
    }
    .tiles-panel ::slotted(.workspace-tile:hover) {
      transform: translateY(-3px);
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb), transparent 35%);
    }
    .footer {
      padding: 12px 16px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
    }
    .sidebar-section { margin-bottom: 16px; }
    .sidebar-section-title {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--builtin-color-muted, #6b7280);
      margin-bottom: 8px;
      padding: 0 4px;
    }
    .project-list { display: flex; flex-direction: column; gap: 2px; }
    .project-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 8px;
      border-radius: var(--builtin-radius, 6px);
      background: transparent;
      border: none;
      color: inherit;
      font: inherit;
      cursor: pointer;
      text-align: left;
      font-size: 13px;
    }
    .project-item:hover { background: var(--builtin-header-bg, #f9fafb); }
    .activity-list { display: flex; flex-direction: column; gap: 8px; }
    .activity-item { font-size: 12px; padding: 0 4px; }
    .activity-text { color: var(--builtin-color-text, #111827); }
    .activity-time { color: var(--builtin-color-muted, #6b7280); margin-top: 2px; font-size: 11px; }
    .widget-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
    }
    .widget-card {
      min-height: 160px;
      padding: 20px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      color: inherit;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform .18s ease, border-color .18s ease;
      box-sizing: border-box;
      cursor: pointer;
    }
    .widget-card:hover {
      transform: translateY(-3px);
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb), transparent 35%);
    }
    .widget-icon { color: var(--builtin-primary, #2563eb); margin-bottom: 12px; }
    .widget-title { font-weight: 700; font-size: 15px; }
    @media (max-width: 900px) {
      .hero-grid { grid-template-columns: 1fr; }
      .tiles-panel ::slotted(.workspace-tile-grid),
      .tiles-panel ::slotted(.workspace-tile-grid.teacher-tiles) {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .widget-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      .sidebar {
        position: fixed;
        inset: 0 auto 0 0;
        z-index: 50;
        transform: translateX(-100%);
        transition: transform .2s ease;
      }
      .sidebar.open { transform: translateX(0); }
      .hamburger { display: inline-flex; }
      .topbar { flex-wrap: wrap; }
      .stats-panel ::slotted(.workspace-stats-grid),
      .tiles-panel ::slotted(.workspace-tile-grid),
      .tiles-panel ::slotted(.workspace-tile-grid.teacher-tiles) {
        grid-template-columns: 1fr;
      }
      .widget-grid { grid-template-columns: 1fr; }
    }
  `;

  constructor() {
    super();
    this.labels = {};
    this.sidebarOpen = false;
    this.widgets = undefined;
    this.projects = undefined;
    this.activities = undefined;
  }

  _defaultWidgets() {
    return [
      { id: 'analytics', type: 'chart', title: this._l('widget.analytics', 'Analytics'), icon: 'bar-chart' },
      { id: 'tasks', type: 'list', title: this._l('widget.tasks', 'Tasks'), icon: 'check-square' },
      { id: 'calendar', type: 'calendar', title: this._l('widget.calendar', 'Calendar'), icon: 'calendar' },
      { id: 'messages', type: 'messages', title: this._l('widget.messages', 'Messages'), icon: 'message' },
    ];
  }

  _defaultProjects() {
    return [
      { id: 'p1', name: this._l('project.alpha', 'Project Alpha') },
      { id: 'p2', name: this._l('project.beta', 'Project Beta') },
      { id: 'p3', name: this._l('project.gamma', 'Project Gamma') },
    ];
  }

  _defaultActivities() {
    return [
      { id: 'a1', text: this._l('activity.login', 'You logged in'), time: '2m ago' },
      { id: 'a2', text: this._l('activity.update', 'System updated'), time: '1h ago' },
      { id: 'a3', text: this._l('activity.newUser', 'New user joined'), time: '3h ago' },
    ];
  }

  _onWidgetClick(widget) {
    this.dispatchEvent(new CustomEvent('builtin-widget-click', {
      detail: { id: widget.id, type: widget.type },
      bubbles: true,
      composed: true,
    }));
  }

  _onProjectClick(project) {
    this.dispatchEvent(new CustomEvent('builtin-project-click', {
      detail: { id: project.id, name: project.name },
      bubbles: true,
      composed: true,
    }));
  }

  toggleSidebar() {
    this.sidebarOpen = !this.sidebarOpen;
  }

  render() {
    const widgets = this.widgets ?? (this._defaultWidgets());
    const projects = this.projects ?? (this._defaultProjects());
    const activities = this.activities ?? (this._defaultActivities());

    return html`
      <div class="layout">
        <aside class="sidebar ${classMap({ open: this.sidebarOpen })}">
          <div class="sidebar-header">
            <builtin-icon name="appstore" size="16"></builtin-icon>
            ${this._l('sidebar.title', 'Workspace')}
          </div>
          <div class="sidebar-body">
            ${projects.length > 0 ? html`
              <div class="sidebar-section">
                <div class="sidebar-section-title">${this._l('sidebar.projects', 'Projects')}</div>
                <div class="project-list">
                  ${projects.map(p => html`
                    <button class="project-item" @click=${() => this._onProjectClick(p)}>
                      <builtin-icon name="folder" size="14"></builtin-icon>
                      <span>${p.name}</span>
                    </button>
                  `)}
                </div>
              </div>
            ` : nothing}
            ${activities.length > 0 ? html`
              <div class="sidebar-section">
                <div class="sidebar-section-title">${this._l('sidebar.activities', 'Recent Activity')}</div>
                <div class="activity-list">
                  ${activities.map(a => html`
                    <div class="activity-item">
                      <div class="activity-text">${a.text}</div>
                      <div class="activity-time">${a.time}</div>
                    </div>
                  `)}
                </div>
              </div>
            ` : nothing}
            <slot name="sidebar"></slot>
          </div>
        </aside>
        <div class="main">
          <div class="topbar">
            <button type="button" class="hamburger" @click=${() => this.toggleSidebar()} aria-label="${this._l('sidebar.toggle', 'Toggle sidebar')}">
              <builtin-icon name="menu" size="16" variant="outlined"></builtin-icon>
            </button>
            <div><slot name="header"></slot></div>
          </div>
          <div class="content">
            <div class="hero-grid">
              <section class="hero-panel"><slot name="hero"></slot></section>
              <section class="profile-panel"><slot name="profile"></slot></section>
            </div>
            <section class="stats-panel"><slot name="stats"></slot></section>
            <section class="tiles-panel">
              ${widgets.length > 0 ? html`
                <div class="widget-grid">
                  ${widgets.map(w => html`
                    <div class="widget-card" @click=${() => this._onWidgetClick(w)}>
                      <div class="widget-icon"><builtin-icon name="${w.icon}" size="24"></builtin-icon></div>
                      <div class="widget-title">${w.title}</div>
                    </div>
                  `)}
                </div>
              ` : html`<slot name="tiles"></slot>`}
            </section>
          </div>
          <div class="footer"><slot name="footer"></slot></div>
        </div>
      </div>
    `;
  }
}