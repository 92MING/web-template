import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinDiffViewer — line-based diff with side-by-side and inline modes.
 *
 * @element builtin-diff-viewer
 *
 * @attr {string} old-value — Original string.
 * @attr {string} new-value — Updated string.
 * @attr {string} mode — "side-by-side" | "inline" (default "side-by-side").
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @event builtin-change — Mode changed. detail: {mode}
 */
export class BuiltinDiffViewer extends BuiltinBaseElement {
  static properties = {
    oldValue: { type: String, attribute: "old-value" },
    newValue: { type: String, attribute: "new-value" },
    oldText: { type: String, attribute: "old-text" },
    newText: { type: String, attribute: "new-text" },
    mode: { type: String },
    labels: {
      converter: {
        fromAttribute(value) {
          if (!value) return {};
          try { return JSON.parse(value); } catch (_e) { return {}; }
        },
        toAttribute(value) { return JSON.stringify(value); },
      },
    },
  };

  static styles = css`
    :host { display: block; }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .toolbar-group { display: flex; align-items: center; gap: 8px; }
    .diff-wrap {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      overflow: auto;
    }
    .diff-table { width: 100%; border-collapse: collapse; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 13px; }
    .diff-table td, .diff-table th { padding: 4px 10px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); vertical-align: top; white-space: pre-wrap; word-break: break-word; }
    .diff-table th { background: var(--builtin-header-bg, #f9fafb); color: var(--builtin-color-muted, #6b7280); font-weight: 600; text-align: left; position: sticky; top: 0; z-index: 1; }
    .line-num { width: 40px; color: var(--builtin-color-muted, #6b7280); text-align: right; user-select: none; }
    .added { background: rgba(34, 197, 94, 0.12); }
    .removed { background: rgba(239, 68, 68, 0.12); }
    .inline .line-old { text-decoration: line-through; color: var(--builtin-color-danger, #b91c1c); }
    .inline .line-new { color: var(--builtin-primary, #2563eb); }
    .inline-row { display: flex; gap: 8px; padding: 4px 10px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); white-space: pre-wrap; word-break: break-word; }
    .inline-row .tag { width: 24px; text-align: center; font-weight: 700; flex-shrink: 0; }
    .inline-row .tag.add { color: #16a34a; }
    .inline-row .tag.del { color: #dc2626; }
    .inline-row .tag.eq { color: var(--builtin-color-muted, #6b7280); }
    .mode-btn {
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      border-radius: var(--builtin-radius, 6px);
      padding: 4px 10px;
      cursor: pointer;
      min-height: 30px;
      font-size: 12px;
    }
    .mode-btn.active {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    @media (max-width: 720px) {
      .diff-table { font-size: 12px; }
      .diff-table td, .diff-table th { padding: 4px 6px; }
    }
  `;

  constructor() {
    super();
    this.oldValue = "";
    this.newValue = "";
    this.oldText = "";
    this.newText = "";
    this.mode = "side-by-side";
    this.labels = {};
  }

  _t(key, values) {
    if (this.labels && typeof this.labels === "object" && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => (
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        ));
      }
      return text;
    }
    return super._t(key, values);
  }

  _computeDiff() {
    const oldLines = (this.oldValue || this.oldText || "").split("\n");
    const newLines = (this.newValue || this.newText || "").split("\n");
    const result = [];
    let o = 0, n = 0;
    while (o < oldLines.length || n < newLines.length) {
      if (o >= oldLines.length) {
        result.push({ type: "add", oldLine: null, newLine: newLines[n], oldNum: null, newNum: n + 1 });
        n++;
      } else if (n >= newLines.length) {
        result.push({ type: "del", oldLine: oldLines[o], newLine: null, oldNum: o + 1, newNum: null });
        o++;
      } else if (oldLines[o] === newLines[n]) {
        result.push({ type: "eq", oldLine: oldLines[o], newLine: newLines[n], oldNum: o + 1, newNum: n + 1 });
        o++; n++;
      } else {
        // Simple heuristic: if next new line matches current old, it's a deletion
        if (n + 1 < newLines.length && oldLines[o] === newLines[n + 1]) {
          result.push({ type: "add", oldLine: null, newLine: newLines[n], oldNum: null, newNum: n + 1 });
          n++;
        } else if (o + 1 < oldLines.length && oldLines[o + 1] === newLines[n]) {
          result.push({ type: "del", oldLine: oldLines[o], newLine: null, oldNum: o + 1, newNum: null });
          o++;
        } else {
          result.push({ type: "del", oldLine: oldLines[o], newLine: null, oldNum: o + 1, newNum: null });
          result.push({ type: "add", oldLine: null, newLine: newLines[n], oldNum: null, newNum: n + 1 });
          o++; n++;
        }
      }
    }
    return result;
  }

  _setMode(mode) {
    this.mode = mode;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { mode }, bubbles: true }));
  }

  _renderSideBySide(lines) {
    return html`
      <table class="diff-table">
        <thead>
          <tr>
            <th class="line-num">#</th>
            <th>${this._t("diff.old")}</th>
            <th class="line-num">#</th>
            <th>${this._t("diff.new")}</th>
          </tr>
        </thead>
        <tbody>
          ${repeat(lines, (l, i) => i, (l) => html`
            <tr>
              <td class="line-num ${l.type === "del" ? "removed" : ""}">${l.oldNum ?? ""}</td>
              <td class="${l.type === "del" ? "removed" : ""}">${l.oldLine ?? ""}</td>
              <td class="line-num ${l.type === "add" ? "added" : ""}">${l.newNum ?? ""}</td>
              <td class="${l.type === "add" ? "added" : ""}">${l.newLine ?? ""}</td>
            </tr>
          `)}
        </tbody>
      </table>
    `;
  }

  _renderInline(lines) {
    return html`
      <div class="inline">
        ${repeat(lines, (l, i) => i, (l) => html`
          <div class="inline-row ${l.type}">
            <span class="tag ${l.type === "add" ? "add" : l.type === "del" ? "del" : "eq"}">
              ${l.type === "add" ? "+" : l.type === "del" ? "−" : " "}
            </span>
            <span class="${l.type === "del" ? "line-old" : l.type === "add" ? "line-new" : ""}">${l.oldLine ?? l.newLine ?? ""}</span>
          </div>
        `)}
      </div>
    `;
  }

  render() {
    const lines = this._computeDiff();
    const effectiveMode = this._ptMobile ? "inline" : this.mode;

    return html`
      <div class="toolbar">
        <div class="toolbar-group">
          <button class="mode-btn ${effectiveMode === "side-by-side" ? "active" : ""}" @click="${() => this._setMode("side-by-side")}" ?disabled="${this._ptMobile}">
            ${this._t("diff.sideBySide")}
          </button>
          <button class="mode-btn ${effectiveMode === "inline" ? "active" : ""}" @click="${() => this._setMode("inline")}">
            ${this._t("diff.inline")}
          </button>
        </div>
      </div>
      <div class="diff-wrap">
        ${effectiveMode === "side-by-side" ? this._renderSideBySide(lines) : this._renderInline(lines)}
      </div>
    `;
  }
}
