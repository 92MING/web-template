/**
 * @fileoverview BuiltinChartWrapper — Chart.js wrapper web component.
 *
 * @element builtin-chart-wrapper
 *
 * @attr {string} type — `line` | `bar` | `pie` | `doughnut` | `radar`
 * @attr {Object} data — Chart.js data object (JSON)
 * @attr {Object} options — Chart.js options object (JSON)
 * @attr {string} mode — `default` | `minimal`
 * @attr {Object} labels — JSON object for i18n overrides
 *
 * @slot header — Content above the chart
 * @slot footer — Content below the chart
 * @slot empty — Shown when there is no data
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

const CHART_SCRIPT = "/vendor/chart/chart.js";
let _chartLoadPromise = null;

function loadChartScript() {
  if (_chartLoadPromise) return _chartLoadPromise;
  if (window.Chart) return Promise.resolve(window.Chart);
  _chartLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = CHART_SCRIPT;
    script.onload = () => resolve(window.Chart);
    script.onerror = () => reject(new Error("Failed to load Chart.js"));
    document.head.appendChild(script);
  });
  return _chartLoadPromise;
}

export class BuiltinChartWrapper extends BuiltinBaseElement {
  static properties = {
    type: { type: String },
    data: { type: Object },
    options: { type: Object },
    mode: { type: String },
    labels: { type: Object },
    _chart: { type: Object, state: true },
    _error: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 16px;
      color: var(--builtin-color-text, #111827);
    }
    .wrap.minimal {
      border: none;
      padding: 0;
      background: transparent;
    }
    .header { margin-bottom: 12px; }
    .footer { margin-top: 12px; }
    .canvas-wrap {
      position: relative;
      width: 100%;
      min-height: 200px;
    }
    canvas { display: block; width: 100% !important; height: auto !important; }
    .empty {
      display: flex; align-items: center; justify-content: center;
      min-height: 200px;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 14px;
    }
    .error {
      display: flex; align-items: center; justify-content: center;
      min-height: 200px;
      color: var(--builtin-color-danger, #b91c1c);
      font-size: 14px;
    }
    @media (max-width: 720px) {
      .wrap { padding: 12px; }
      canvas { max-height: 320px; }
    }
  `;

  constructor() {
    super();
    this.type = "line";
    this.mode = "default";
    this.data = null;
    this.options = null;
    this._resizeObserver = null;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _hasData() {
    return this.data && Array.isArray(this.data.datasets) && this.data.datasets.length > 0;
  }

  async updated(changed) {
    if (changed.has("_ptTheme") && this._chart) {
      this._updateThemeColors();
      this._chart.update("none");
      return;
    }
    if ((changed.has("data") || changed.has("options") || changed.has("type")) && this._hasData()) {
      await this._initChart();
    }
    if (changed.has("data") && !this._hasData()) {
      this._destroyChart();
    }
  }

  _getThemeColors() {
    const isDark = this._ptTheme === "dark";
    return {
      text: isDark ? "#e5e7eb" : "#111827",
      grid: isDark ? "#374151" : "#e5e7eb",
      tooltipBg: isDark ? "#1f2937" : "#ffffff",
      tooltipBorder: isDark ? "#4b5563" : "#d1d5db",
    };
  }

  _updateThemeColors() {
    if (!this._chart) return;
    const colors = this._getThemeColors();
    const opts = this._chart.options;
    if (opts.plugins?.legend?.labels) {
      opts.plugins.legend.labels.color = colors.text;
    }
    if (opts.plugins?.tooltip) {
      opts.plugins.tooltip.backgroundColor = colors.tooltipBg;
      opts.plugins.tooltip.titleColor = colors.text;
      opts.plugins.tooltip.bodyColor = colors.text;
      opts.plugins.tooltip.borderColor = colors.tooltipBorder;
    }
    if (opts.scales) {
      Object.values(opts.scales).forEach((scale) => {
        if (scale.ticks) scale.ticks.color = colors.text;
        if (scale.grid) scale.grid.color = colors.grid;
      });
    }
  }

  _buildOptions() {
    const colors = this._getThemeColors();
    const isMobile = this._ptMobile;
    const baseOptions = {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          display: !isMobile || this.mode !== "minimal",
          labels: { color: colors.text, usePointStyle: true, boxWidth: 8 },
        },
        tooltip: {
          backgroundColor: colors.tooltipBg,
          titleColor: colors.text,
          bodyColor: colors.text,
          borderColor: colors.tooltipBorder,
          borderWidth: 1,
          padding: 10,
          displayColors: true,
        },
      },
      scales: {},
    };

    const needsScales = ["line", "bar", "radar"].includes(this.type);
    if (needsScales) {
      baseOptions.scales = {
        x: {
          ticks: { color: colors.text },
          grid: { color: colors.grid },
        },
        y: {
          ticks: { color: colors.text },
          grid: { color: colors.grid },
        },
      };
    }

    if (isMobile) {
      baseOptions.plugins.legend = { display: false };
    }

    const userOptions = this.options || {};
    return this._deepMerge(baseOptions, userOptions);
  }

  _deepMerge(target, source) {
    const out = { ...target };
    for (const key of Object.keys(source)) {
      if (source[key] && typeof source[key] === "object" && !Array.isArray(source[key])) {
        out[key] = this._deepMerge(out[key] || {}, source[key]);
      } else {
        out[key] = source[key];
      }
    }
    return out;
  }

  async _initChart() {
    try {
      const ChartCtor = await loadChartScript();
      const canvas = this.shadowRoot.querySelector("canvas");
      if (!canvas) return;
      this._destroyChart(canvas, ChartCtor);
      const options = this._buildOptions();
      this._chart = new ChartCtor(canvas, {
        type: this.type || "line",
        data: this.data,
        options,
      });
      this._setupResizeObserver(canvas);
      this._error = "";
    } catch (err) {
      this._error = String(err?.message || err);
    }
  }

  _destroyChart(canvas = this.shadowRoot?.querySelector("canvas"), ChartCtor = window.Chart) {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
    const existing = canvas && ChartCtor?.getChart ? ChartCtor.getChart(canvas) : null;
    if (existing) {
      existing.destroy();
    }
    if (this._chart && this._chart !== existing) {
      this._chart.destroy();
    }
    this._chart = null;
  }

  _setupResizeObserver(canvas) {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
    }
    if ("ResizeObserver" in window) {
      this._resizeObserver = new ResizeObserver(() => {
        if (this._chart) this._chart.resize();
      });
      this._resizeObserver.observe(canvas.parentElement || this);
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._destroyChart();
  }

  render() {
    const mode = this.mode || "default";
    const hasData = this._hasData();

    return html`
      <div class="wrap ${classMap({ minimal: mode === "minimal" })}">
        <div class="header"><slot name="header"></slot></div>
        ${!hasData
          ? html`<div class="empty"><slot name="empty">${this._l("chart.noData", "No data available")}</slot></div>`
          : this._error
            ? html`<div class="error">${this._error}</div>`
            : html`<div class="canvas-wrap"><canvas></canvas></div>`}
        <div class="footer"><slot name="footer"></slot></div>
      </div>
    `;
  }
}
