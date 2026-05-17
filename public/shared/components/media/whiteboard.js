/**
 * @fileoverview BuiltinWhiteboard — Whiteboard wrapper around Fabric.js with drawing tools.
 *
 * @attr {string} tools — Comma-separated tools or `all` (default `all`).
 * @attr {string} stroke-color — Default stroke color (default `#111827`).
 * @attr {number} stroke-width — Default stroke width (default `2`).
 * @attr {string} labels — JSON i18n overrides.
 * @attr {string} mode — `default` | `embedded` (default `default`).
 *
 * @event builtin-export — `{ dataURL, format }`
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

export class BuiltinWhiteboard extends BuiltinBaseElement {
  static properties = {
    tools: { type: String, attribute: "tools" },
    strokeColor: { type: String, attribute: "stroke-color" },
    strokeWidth: { type: Number, attribute: "stroke-width" },
    labels: { type: Object },
    mode: { type: String },
    _activeTool: { type: String, state: true },
    _history: { type: Array, state: true },
    _historyIndex: { type: Number, state: true },
    _loaded: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .board { display: flex; flex-direction: column; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-surface, #ffffff); }
    .board.embedded { border: none; border-radius: 0; }
    .toolbar { display: flex; align-items: center; gap: 6px; padding: 8px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); flex-wrap: wrap; background: var(--builtin-bg-subtle, #f3f4f6); }
    .tool-group { display: inline-flex; align-items: center; gap: 4px; }
    .tool { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-surface, #ffffff); border-radius: var(--builtin-radius, 6px); cursor: pointer; color: var(--builtin-color-text, #111827); }
    .tool:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .tool.active { border-color: var(--builtin-primary, #2563eb); background: var(--builtin-primary-soft, #eff6ff); color: var(--builtin-primary, #2563eb); }
    .tool svg { pointer-events: none; }
    .canvas-wrap { flex: 1 1 auto; position: relative; min-height: 320px; background: var(--builtin-surface, #ffffff); overflow: hidden; }
    .canvas-wrap .canvas-container, .canvas-wrap canvas { display: block; }
    .props { display: inline-flex; align-items: center; gap: 8px; }
    .props input[type="color"] { width: 28px; height: 28px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); padding: 0; background: none; cursor: pointer; }
    .props input[type="range"] { width: 80px; }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 10px; border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-surface, #ffffff); border-radius: var(--builtin-radius, 6px); cursor: pointer; color: var(--builtin-color-text, #111827); min-height: 32px; font-size: 13px; }
    .btn:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .btn.primary { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .btn.danger { color: var(--builtin-danger, #dc2626); border-color: var(--builtin-danger, #dc2626); }
    @media (max-width: 720px) {
      .toolbar { gap: 8px; padding: 8px; }
      .tool { width: 42px; height: 42px; }
      .canvas-wrap { min-height: 240px; }
    }
  `;

  constructor() {
    super();
    this.tools = "all";
    this.strokeColor = "#111827";
    this.strokeWidth = 2;
    this.mode = "default";
    this._activeTool = "select";
    this._history = [];
    this._historyIndex = -1;
    this._loaded = false;
    this._canvas = null;
    this._fabric = null;
    this._draftObject = null;
    this._draftStart = null;
    this._restoringHistory = false;
    this._resizeObserver = null;
    this._onFabricMouseDown = (event) => this._handleFabricMouseDown(event);
    this._onFabricMouseMove = (event) => this._handleFabricMouseMove(event);
    this._onFabricMouseUp = () => this._handleFabricMouseUp();
  }

  connectedCallback() {
    super.connectedCallback();
    this._loadFabric().then(() => {
      this._loaded = true;
      this.requestUpdate();
    });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._canvas) {
      this._canvas.dispose();
      this._canvas = null;
    }
    this._resizeObserver?.disconnect?.();
    this._resizeObserver = null;
  }

  async _loadFabric() {
    this._fabric = await ensureVendor("fabric");
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _toolList() {
    if (this.tools === "all") return ["select", "pen", "rect", "circle", "text", "erase"];
    return this.tools.split(",").map((t) => t.trim()).filter(Boolean);
  }

  firstUpdated() {
    this._initCanvas();
  }

  updated(changed) {
    if (changed.has("_loaded") && this._loaded) {
      this._initCanvas();
    }
    if (changed.has("_activeTool") || changed.has("strokeColor") || changed.has("strokeWidth")) this._syncCanvasTool();
    if (changed.has("_ptTheme") && this._canvas) {
      this._canvas.backgroundColor = this._canvasBackground();
      this._canvas.renderAll();
    }
  }

  _initCanvas() {
    if (!this._loaded || this._canvas) return;
    const wrap = this.shadowRoot.querySelector(".canvas-wrap");
    if (!wrap || !this._fabric) return;
    const canvasEl = document.createElement("canvas");
    wrap.appendChild(canvasEl);
    this._canvas = new this._fabric.Canvas(canvasEl, {
      isDrawingMode: false,
      backgroundColor: this._canvasBackground(),
      preserveObjectStacking: true,
    });
    this._resizeCanvas();
    this._resizeObserver = new ResizeObserver(() => this._resizeCanvas());
    this._resizeObserver.observe(wrap);
    this._canvas.on("mouse:down", this._onFabricMouseDown);
    this._canvas.on("mouse:move", this._onFabricMouseMove);
    this._canvas.on("mouse:up", this._onFabricMouseUp);
    this._canvas.on("path:created", () => this._pushHistory());
    this._canvas.on("object:added", (e) => {
      if (e.target && !e.target._fromHistory) this._pushHistory();
    });
    this._canvas.on("object:modified", () => this._pushHistory());
    this._syncCanvasTool();
    this._pushHistory();
  }

  _canvasBackground() {
    return "#ffffff";
  }

  _resizeCanvas() {
    if (!this._canvas) return;
    const wrap = this.shadowRoot.querySelector(".canvas-wrap");
    if (!wrap) return;
    const w = wrap.clientWidth;
    const h = Math.max(wrap.clientHeight, 320);
    this._canvas.setDimensions({ width: w, height: h });
    this._canvas.calcOffset();
    this._canvas.renderAll();
  }

  _pushHistory() {
    if (!this._canvas || this._restoringHistory) return;
    const json = this._canvas.toJSON();
    const serialized = JSON.stringify(json);
    const current = this._history[this._historyIndex];
    if (current && JSON.stringify(current) === serialized) return;
    const next = this._history.slice(0, this._historyIndex + 1);
    next.push(json);
    if (next.length > 50) next.shift();
    this._history = next;
    this._historyIndex = next.length - 1;
  }

  _undo() {
    if (this._historyIndex <= 0 || !this._canvas) return;
    this._historyIndex -= 1;
    const state = this._history[this._historyIndex];
    this._restoringHistory = true;
    this._canvas.loadFromJSON(state, () => {
      this._restoringHistory = false;
      this._canvas.backgroundColor = this._canvasBackground();
      this._canvas.renderAll();
    });
  }

  _clear() {
    if (!this._canvas) return;
    this._canvas.clear();
    this._canvas.backgroundColor = this._canvasBackground();
    this._pushHistory();
  }

  _exportImage() {
    if (!this._canvas) return;
    const dataURL = this._canvas.toDataURL({ format: "png" });
    this.dispatchEvent(new CustomEvent("builtin-export", { detail: { dataURL, format: "png" }, bubbles: true }));
  }

  exportImage() {
    this._exportImage();
  }

  _setTool(name) {
    this._activeTool = name;
    this._syncCanvasTool();
  }

  _syncCanvasTool() {
    if (!this._canvas) return;
    const name = this._activeTool;
    this._canvas.isDrawingMode = false;
    this._canvas.selection = name === "select";
    this._canvas.defaultCursor = name === "select" ? "default" : name === "pen" ? "crosshair" : "copy";
    this._canvas.hoverCursor = name === "erase" ? "not-allowed" : name === "select" ? "move" : "copy";
    this._canvas.forEachObject((obj) => { obj.selectable = name === "select"; obj.evented = name === "select" || name === "erase"; });
    if (name === "pen") {
      this._canvas.isDrawingMode = true;
      this._canvas.freeDrawingBrush = this._canvas.freeDrawingBrush || new this._fabric.PencilBrush(this._canvas);
      this._canvas.freeDrawingBrush.color = this.strokeColor;
      this._canvas.freeDrawingBrush.width = this.strokeWidth;
    }
    this._canvas.discardActiveObject();
    this._canvas.requestRenderAll();
  }

  _handleFabricMouseDown(event) {
    if (!this._canvas || this._activeTool === "select" || this._activeTool === "pen") return;
    if (this._activeTool === "erase") {
      if (event.target) {
        this._canvas.remove(event.target);
        this._pushHistory();
      }
      return;
    }
    const pointer = event.pointer || this._canvas.getPointer(event.e);
    const color = this.strokeColor;
    const width = this.strokeWidth;
    this._draftStart = pointer;
    if (this._activeTool === "rect") {
      this._draftObject = new this._fabric.Rect({ left: pointer.x, top: pointer.y, width: 1, height: 1, fill: "transparent", stroke: color, strokeWidth: width, selectable: false, evented: false });
    } else if (this._activeTool === "circle") {
      this._draftObject = new this._fabric.Circle({ left: pointer.x, top: pointer.y, radius: 1, fill: "transparent", stroke: color, strokeWidth: width, selectable: false, evented: false });
    } else if (this._activeTool === "text") {
      const obj = new this._fabric.IText(this._l("text", "Text"), { left: pointer.x, top: pointer.y, fill: color, fontSize: 18, selectable: true, evented: true });
      this._canvas.add(obj);
      this._canvas.setActiveObject(obj);
      obj.enterEditing?.();
      this._pushHistory();
      return;
    }
    if (this._draftObject) {
      this._draftObject._fromHistory = true;
      this._canvas.add(this._draftObject);
      this._draftObject._fromHistory = false;
      this._canvas.requestRenderAll();
    }
  }

  _handleFabricMouseMove(event) {
    if (!this._canvas || !this._draftObject || !this._draftStart) return;
    const pointer = event.pointer || this._canvas.getPointer(event.e);
    const start = this._draftStart;
    if (this._draftObject.type === "rect") {
      const left = Math.min(start.x, pointer.x);
      const top = Math.min(start.y, pointer.y);
      this._draftObject.set({ left, top, width: Math.abs(pointer.x - start.x), height: Math.abs(pointer.y - start.y) });
    } else if (this._draftObject.type === "circle") {
      const radius = Math.max(4, Math.hypot(pointer.x - start.x, pointer.y - start.y));
      this._draftObject.set({ left: start.x - radius, top: start.y - radius, radius });
    }
    this._draftObject.setCoords();
    this._canvas.requestRenderAll();
  }

  _handleFabricMouseUp() {
    if (!this._canvas || !this._draftObject) return;
    if ((this._draftObject.width || this._draftObject.radius || 0) < 4 && (this._draftObject.height || this._draftObject.radius || 0) < 4) {
      this._canvas.remove(this._draftObject);
    } else {
      this._draftObject.set({ selectable: this._activeTool === "select", evented: this._activeTool === "select" || this._activeTool === "erase" });
      this._pushHistory();
    }
    this._draftObject = null;
    this._draftStart = null;
    this._canvas.requestRenderAll();
  }

  _toolIcon(name) {
    switch (name) {
      case "select": return html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/></svg>`;
      case "pen": return html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19l7-7 3 3-7 7-3-3z"/><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/><path d="M2 2l7.586 7.586"/><circle cx="11" cy="11" r="2"/></svg>`;
      case "rect": return html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>`;
      case "circle": return html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/></svg>`;
      case "text": return html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/></svg>`;
      case "erase": return html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20H7L3 16C2 15 2 13 3 12L13 2L22 11L20 20Z"/><path d="M17 17L7 7"/></svg>`;
      default: return null;
    }
  }

  render() {
    const tools = this._toolList();
    return html`
      <div class="board ${this.mode}">
        <div class="toolbar">
          <div class="tool-group">
            ${tools.map((t) => html`
              <button class="tool ${this._activeTool === t ? "active" : ""}" title=${this._l(t, t)} @click=${() => this._setTool(t)}>
                ${this._toolIcon(t)}
              </button>
            `)}
          </div>
          <div class="props">
            <input type="color" .value=${this.strokeColor} @input=${(e) => this.strokeColor = e.target.value} title=${this._l("color", "Color")}>
            <input type="range" min="1" max="20" .value=${this.strokeWidth} @input=${(e) => this.strokeWidth = Number(e.target.value)} title=${this._l("width", "Width")}>
          </div>
          <div class="tool-group">
            <button class="btn" @click=${this._undo} title=${this._l("undo", "Undo")}>
              <builtin-icon name="undo" size="14" variant="outlined"></builtin-icon>
            </button>
            <button class="btn danger" @click=${this._clear} title=${this._l("clear", "Clear")}>
              <builtin-icon name="delete" size="14" variant="outlined"></builtin-icon>
            </button>
            <button class="btn primary" @click=${this._exportImage} title=${this._l("export", "Export")}>
              <builtin-icon name="cloud-download" size="14" variant="outlined"></builtin-icon>
            </button>
          </div>
          <slot name="toolbar"></slot>
        </div>
        <div class="canvas-wrap"></div>
      </div>
    `;
  }
}
