import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

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
 * @fileoverview BuiltinTplDashboardAnalytics - Analytics / reporting dashboard template.
 *
 * Attributes:
 *   - labels: JSON object to override i18n strings
 *   - stats: JSON array of stat objects { label, value, change, up }
 *   - table-rows: JSON array of row objects { page, visitors, unique, bounce, time }
 *   - chart-data: JSON object with placeholder chart config
 *   - date-ranges: JSON array of date filter options
 *   - filters: JSON object with current filter values
 *
 * Slots:
 *   - sidebar: Collapsible sidebar navigation
 *   - header: Top header bar content
 *   - chart: Custom chart content
 *   - table: Custom table content
 *   - footer: Footer content
 */
export class BuiltinTplDashboardAnalytics extends BuiltinBaseElement {
  static properties = {
    labels: { type: Object, converter: jsonConverter },
    stats: { type: Array, converter: jsonConverter },
    tableRows: { type: Array, converter: jsonConverter, attribute: "table-rows" },
    chartData: { type: Object, converter: jsonConverter, attribute: "chart-data" },
    dateRanges: { type: Array, converter: jsonConverter, attribute: "date-ranges" },
    filters: { type: Object, converter: jsonConverter },
        _sidebarOpen: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; min-height: 100vh; }
    .layout { display: flex; min-height: 100vh; }
    .sidebar {
      width: 240px;
      border-right: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      flex-shrink: 0;
      display: flex;
      flex-direction: column;
    }
    .sidebar-header {
      padding: 16px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      font-weight: 650;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .sidebar-body { padding: 12px; flex: 1; }
    .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    .topbar {
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 12px 16px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .search { max-width: 320px; width: 100%; }
    .search input {
      width: 100%;
      padding: 8px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      font: inherit;
    }
    .content { padding: 16px; flex: 1; }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
    .stat-card {
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff); padding: 16px;
    }
    .stat-value { font-size: 24px; font-weight: 700; color: var(--builtin-primary, #2563eb); }
    .stat-label { font-size: 12px; color: var(--builtin-color-muted, #6b7280); margin-top: 4px; display: flex; align-items: center; gap: 4px; }
    .stat-change { font-size: 12px; margin-top: 4px; display: flex; align-items: center; gap: 4px; }
    .stat-change.up { color: var(--builtin-success, #16a34a); }
    .stat-change.down { color: var(--builtin-danger, #dc2626); }
    .filters { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
    .filters input, .filters button {
      padding: 6px 10px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      font: inherit;
      cursor: pointer;
    }
    .filters button {
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      border-color: var(--builtin-primary, #2563eb);
      font-weight: 600;
    }
    .chart-area {
      border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff); height: 320px; margin-bottom: 16px;
      display: flex; align-items: center; justify-content: center; position: relative; overflow: auto;
    }
    .chart-grid {
      position: absolute; inset: 0;
      background-image:
        linear-gradient(to right, var(--builtin-border-soft, #e5e7eb) 1px, transparent 1px),
        linear-gradient(to bottom, var(--builtin-border-soft, #e5e7eb) 1px, transparent 1px);
      background-size: 40px 40px; opacity: .6;
    }
    .chart-label { position: relative; z-index: 1; color: var(--builtin-color-muted, #6b7280); }
    .table-wrap { width: 100%; overflow: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); padding: 10px 12px; text-align: left; white-space: nowrap; }
    th { background: var(--builtin-header-bg, #f9fafb); color: var(--builtin-color-muted, #6b7280); font-weight: 650; }
    tr:hover td { background: var(--builtin-row-hover-bg, #f9fafb); }
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
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .chart-area { height: 240px; }
      .topbar { flex-wrap: wrap; }
      .search { max-width: 100%; }
    }
  `;

  constructor() {
    super();
    this._sidebarOpen = false;
  }

  _toggleSidebar() {
    this._sidebarOpen = !this._sidebarOpen;
  }

  _defaultStats() {
    return [
      { label: this._l("stat.users", "Total Users"), value: "12.5K", change: "+8.2%", up: true },
      { label: this._l("stat.revenue", "Revenue"), value: "$84K", change: "+12.5%", up: true },
      { label: this._l("stat.conversion", "Conversion"), value: "3.2%", change: "-0.4%", up: false },
      { label: this._l("stat.orders", "Orders"), value: "1.1K", change: "+5.1%", up: true },
    ];
  }

  _defaultTableRows() {
    return [
      { page: "/home", visitors: "12,345", unique: "8,900", bounce: "32%", time: "2m 14s" },
      { page: "/products", visitors: "8,210", unique: "5,600", bounce: "28%", time: "3m 42s" },
      { page: "/pricing", visitors: "4,500", unique: "3,200", bounce: "45%", time: "1m 50s" },
      { page: "/blog", visitors: "3,800", unique: "2,900", bounce: "38%", time: "4m 05s" },
    ];
  }

  _defaultChartData() {
    return {
      title: this._l("chart.placeholder", "Chart Placeholder"),
    };
  }

  _defaultDateRanges() {
    return [
      { label: this._l("filter.start", "Start"), value: "2024-01-01" },
      { label: this._l("filter.end", "End"), value: "2024-12-31" },
    ];
  }

  render() {
    const stats = (this.stats || this._defaultStats()
      );
    const tableRows = (this.tableRows || this._defaultTableRows()
      );
    const chartData = (this.chartData || this._defaultChartData()
      );
    const dateRanges = (this.dateRanges || this._defaultDateRanges()
      );

    return html`
      <div class="layout">
        <aside class="sidebar ${classMap({ open: this._sidebarOpen })}">
          <div class="sidebar-header">
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>
            ${this._l("sidebar.title", "Analytics")}
          </div>
          <div class="sidebar-body"><slot name="sidebar"></slot></div>
        </aside>
        <div class="main">
          <div class="topbar">
            <button type="button" class="hamburger" @click=${this._toggleSidebar} aria-label="${this._l("sidebar.toggle", "Toggle sidebar")}">
              <builtin-icon name="menu" size="16" variant="outlined"></builtin-icon>
            </button>
            <div class="search"><input type="search" placeholder="${this._l("search.placeholder", "Search...")}" aria-label="${this._l("search.aria", "Search")}"></div>
            <div><slot name="header"></slot></div>
          </div>
          <div class="content">
            <div class="stats">
              ${repeat(stats, (s, i) => i, (s) => html`
                <div class="stat-card">
                  <div class="stat-value">${s.value}</div>
                  <div class="stat-label">${s.label}</div>
                  ${s.change ? html`
                    <div class="stat-change ${s.up ? "up" : "down"}">
                      <builtin-icon name="${s.up ? "arrow-up" : "arrow-down"}" size="14" variant="outlined"></builtin-icon>
                      ${s.change}
                    </div>
                  ` : ""}
                </div>
              `)}
            </div>
            <div class="filters">
              ${repeat(dateRanges, (d, i) => i, (d) => html`
                <input type="date" value="${d.value}">
              `)}
              <button type="button" @click="${() => this.dispatchEvent(new CustomEvent("builtin-apply-filters", { bubbles: true, composed: true, detail: { filters: this.filters || {} } }))}">${this._l("filter.apply", "Apply")}</button>
            </div>
            <div class="chart-area">
              <slot name="chart">
                <div class="chart-grid"></div>
                <div class="chart-label">${chartData.title || this._l("chart.placeholder", "Chart Placeholder")}</div>
              </slot>
            </div>
            <div class="table-wrap">
              <slot name="table">
                <table>
                  <thead>
                    <tr>
                      <th>${this._l("table.page", "Page")}</th>
                      <th>${this._l("table.visitors", "Visitors")}</th>
                      <th>${this._l("table.unique", "Unique")}</th>
                      <th>${this._l("table.bounce", "Bounce")}</th>
                      <th>${this._l("table.time", "Time")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${repeat(tableRows, (r, i) => i, (r) => html`
                      <tr>
                        <td>${r.page}</td>
                        <td>${r.visitors}</td>
                        <td>${r.unique}</td>
                        <td>${r.bounce}</td>
                        <td>${r.time}</td>
                      </tr>
                    `)}
                  </tbody>
                </table>
              </slot>
            </div>
          </div>
          <div class="footer"><slot name="footer"></slot></div>
        </div>
      </div>
    `;
  }
}