/**
 * @fileoverview BuiltinMermaidDiagram — Mermaid diagram renderer wrapper.
 *
 * @element builtin-mermaid-diagram
 *
 * @attr {string} definition — Mermaid syntax string
 * @attr {string} type — `flowchart` | `sequence` | `class` | `state` | `er` | `gantt`
 * @attr {string} mode — `default` | `compact`
 * @attr {Object} labels — JSON object for i18n overrides
 *
 * @slot header — Content above the diagram
 * @slot actions — Extra actions beside the download button
 * @slot empty — Shown when there is no definition
 */

import { BuiltinBaseElement, html, css, classMap, unsafeHTML } from "../lit-base.js";
import mermaid from "../../../vendor/mermaid/index.js";

export class BuiltinMermaidDiagram extends BuiltinBaseElement {
  static properties = {
    definition: { type: String },
    type: { type: String },
    mode: { type: String },
    labels: { type: Object },
    _svg: { type: String, state: true },
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
    .wrap.compact {
      padding: 8px;
      border-radius: var(--builtin-radius, 6px);
    }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }
    .diagram {
      overflow: auto;
      max-width: 100%;
      background: var(--builtin-surface, #ffffff);
    }
    .diagram svg {
      display: block;
      max-width: 100%;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      font-size: 13px;
      min-height: 32px;
    }
    .btn:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    .btn svg {
      width: 14px; height: 14px;
      stroke: currentColor; fill: none;
      stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;
    }
    .empty {
      display: flex; align-items: center; justify-content: center;
      min-height: 120px;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 14px;
    }
    .error {
      color: var(--builtin-color-danger, #b91c1c);
      font-size: 13px;
      padding: 8px;
    }
    @media (max-width: 720px) {
      .wrap { padding: 12px; }
      .header { margin-bottom: 8px; }
      .diagram { -webkit-overflow-scrolling: touch; }
    }
  `;

  constructor() {
    super();
    this.definition = "";
    this.type = "flowchart";
    this.mode = "default";
    this._svg = "";
    this._error = "";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  async updated(changed) {
    if (changed.has("definition") || changed.has("type") || changed.has("mode") || changed.has("_ptTheme")) {
      if (this.definition) await this._renderDiagram();
      else this._svg = "";
    }
  }

  _prefix() {
    switch (this.type) {
      case "sequence": return "sequenceDiagram";
      case "class": return "classDiagram";
      case "state": return "stateDiagram-v2";
      case "er": return "erDiagram";
      case "gantt": return "gantt";
      default: return "flowchart TD";
    }
  }

  async _renderDiagram() {
    try {
      const id = `mermaid-${Math.random().toString(36).slice(2)}`;
      const trimmed = String(this.definition || "").trim();
      const input = this._hasExplicitDiagramType(trimmed) ? trimmed : `${this._prefix()}\n${trimmed}`;
      mermaid.initialize({
        startOnLoad: false,
        theme: this._ptTheme === "dark" ? "dark" : "default",
        securityLevel: "loose",
      });
      const result = await mermaid.render(id, input);
      const svg = typeof result === "string" ? result : result?.svg;
      if (!svg) throw new Error("Mermaid did not return SVG output");
      this._svg = svg;
      this._error = "";
    } catch (err) {
      this._error = String(err?.message || err);
      this._svg = "";
    }
  }

  _hasExplicitDiagramType(input) {
    return /^(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|stateDiagram-v2|erDiagram|gantt|journey|pie|mindmap|timeline|gitGraph)\b/.test(input);
  }

  _downloadSvg() {
    if (!this._svg) return;
    const blob = new Blob([this._svg], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `diagram-${this.type || "chart"}.svg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  render() {
    const mode = this.mode || "default";
    const hasDef = !!(this.definition || "").trim();

    return html`
      <div class="wrap ${classMap({ compact: mode === "compact" })}">
        <div class="header">
          <slot name="header"></slot>
          <div class="actions">
            <slot name="actions"></slot>
            ${this._svg
              ? html`
                <button class="btn" @click=${this._downloadSvg} aria-label="${this._l("diagram.download", "Download SVG")}">
                  <builtin-icon name="download" size="20" variant="outlined"></builtin-icon>
                  ${this._l("diagram.download", "Download")}
                </button>
              `
              : null}
          </div>
        </div>
        ${!hasDef
          ? html`<div class="empty"><slot name="empty">${this._l("diagram.empty", "No diagram definition provided")}</slot></div>`
          : this._error
            ? html`<div class="error">${this._error}</div>`
            : html`<div class="diagram">${unsafeHTML(this._svg)}</div>`}
      </div>
    `;
  }
}
