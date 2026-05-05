/**
 * @fileoverview BuiltinWhiteboard - Fabric.js whiteboard with drawing, paint and selection tools.
 *
 * @attr {string} tools - Comma-separated tools or `all` (default `all`).
 * @attr {string} stroke-color - Default stroke/fill color (default `#111827`).
 * @attr {number} stroke-width - Default stroke width (default `2`).
 * @attr {string} brush-texture - `solid` | `grain` | `dots` | `hatch` | `grid` (default `solid`).
 * @attr {number} magic-tolerance - Color tolerance for fill / magic selection (default `32`).
 * @attr {number} spray-density - Spray dots per stroke step (default `22`).
 * @attr {string} labels - JSON i18n overrides.
 * @attr {string} mode - `default` | `embedded` (default `default`).
 *
 * @event builtin-export - `{ dataURL, format }`
 */

import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

const DEFAULT_TOOLS = ["select", "pencil", "fill", "rect", "circle", "text", "erase"];
const DRAWING_TOOLS = new Set(["pencil", "erase"]);
const REGION_TOOLS = new Set(["fill"]);
const HISTORY_PROPS = ["globalCompositeOperation", "eraserStroke", "name", "excludeFromExport"];
const HEX_RE = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i;

function _clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function _hex_to_rgb(value) {
  const match = String(value || "").trim().match(HEX_RE);
  if (!match) return null;
  let hex = match[1];
  if (hex.length === 3) {
    hex = hex.split("").map((ch) => ch + ch).join("");
  }
  return [
    parseInt(hex.slice(0, 2), 16),
    parseInt(hex.slice(2, 4), 16),
    parseInt(hex.slice(4, 6), 16),
  ];
}

function _color_distance(a, b) {
  if (!a || !b) return Number.POSITIVE_INFINITY;
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

export class BuiltinWhiteboard extends BuiltinBaseElement {
  static properties = {
    tools: { type: String, attribute: "tools" },
    strokeColor: { type: String, attribute: "stroke-color" },
    strokeWidth: { type: Number, attribute: "stroke-width" },

    magicTolerance: { type: Number, attribute: "magic-tolerance" },
    sprayDensity: { type: Number, attribute: "spray-density" },
    labels: { type: Object },
    mode: { type: String },
    _activeTool: { type: String, state: true },
    _history: { type: Array, state: true },
    _historyIndex: { type: Number, state: true },
    _loaded: { type: Boolean, state: true },
    _selectionSummary: { type: String, state: true },
    _zoom: { type: Number, state: true },
    _backgroundColor: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .board {
      display: flex;
      flex-direction: column;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      background: var(--builtin-surface, #ffffff);
    }
    .board.embedded { border: none; border-radius: 0; }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      flex-wrap: wrap;
      background: var(--builtin-bg-subtle, #f3f4f6);
    }
    .tool-group { display: inline-flex; align-items: center; gap: 4px; flex-wrap: wrap; }
    .tool,
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      color: var(--builtin-color-text, #111827);
    }
    .tool {
      width: 34px;
      height: 34px;
      padding: 0;
    }
    .tool:hover,
    .btn:hover,
    select:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .tool.active {
      border-color: var(--builtin-primary, #2563eb);
      background: var(--builtin-primary-soft, #eff6ff);
      color: var(--builtin-primary, #2563eb);
    }
    .tool svg { pointer-events: none; }
    .canvas-wrap {
      flex: 1 1 auto;
      position: relative;
      min-height: 320px;
      background: var(--wb-bg, #ffffff);
      overflow: hidden;
    }
    .canvas-wrap .canvas-container,
    .canvas-wrap canvas { display: block; }
    .props { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .prop-label { font-size: 11px; color: var(--builtin-color-muted, #6b7280); text-transform: uppercase; letter-spacing: 0.04em; }
    .toolbar-spacer { flex: 1 1 auto; min-width: 8px; }
    .props input[type="color"] {
      width: 28px;
      height: 28px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      padding: 0;
      background: none;
      cursor: pointer;
    }
    .props input[type="range"] { width: 86px; }
    select {
      min-height: 32px;
      max-width: 130px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      padding: 0 8px;
      font-size: 13px;
      cursor: pointer;
    }
    .btn {
      gap: 6px;
      padding: 6px 10px;
      min-height: 32px;
      font-size: 13px;
    }
    .btn.primary {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .btn.danger {
      color: var(--builtin-danger, #dc2626);
      border-color: var(--builtin-danger, #dc2626);
    }
    .status {
      min-width: 104px;
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
    }
    @media (max-width: 720px) {
      .toolbar { gap: 8px; padding: 8px; }
      .tool { width: 42px; height: 42px; }
      .canvas-wrap { min-height: 260px; }
      .props input[type="range"] { width: 74px; }
      .status { flex-basis: 100%; }
    }
  `;

  constructor() {
    super();
    this.tools = "all";
    this.strokeColor = "#111827";
    this.strokeWidth = 1;
    this.magicTolerance = 32;
    this.sprayDensity = 22;
    this.mode = "default";
    this._activeTool = "select";
    this._history = [];
    this._historyIndex = -1;
    this._loaded = false;
    this._selectionSummary = "";
    this._zoom = 100;
    this._backgroundColor = "#ffffff";
    this._canvas = null;
    this._fabric = null;
    this._draftObject = null;
    this._draftStart = null;
    this._region = null;
    this._selectionOverlay = null;
    this._restoringHistory = false;
    this._resizeObserver = null;
    this._isPanning = false;
    this._panLast = null;
    this._onFabricMouseDown = (event) => this._handleFabricMouseDown(event);
    this._onFabricMouseMove = (event) => this._handleFabricMouseMove(event);
    this._onFabricMouseUp = () => this._handleFabricMouseUp();
    this._onWheel = (event) => this._handleWheel(event);
    this._onMouseDownForPan = (event) => this._handleMouseDownForPan(event);
    this._onMouseMoveForPan = (event) => this._handleMouseMoveForPan(event);
    this._onMouseUpForPan = () => this._handleMouseUpForPan();
    this._onKeyDown = (event) => this._handleKeyDown(event);
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
    document.removeEventListener("mousemove", this._onMouseMoveForPan);
    document.removeEventListener("mouseup", this._onMouseUpForPan);
    document.removeEventListener("keydown", this._onKeyDown);
    if (this._canvas) {
      const upper = this._canvas.upperCanvasEl;
      upper?.removeEventListener("wheel", this._onWheel);
      upper?.removeEventListener("mousedown", this._onMouseDownForPan);
      this._canvas.dispose();
      this._canvas = null;
    }
    this._resizeObserver?.disconnect?.();
    this._resizeObserver = null;
  }

  async _loadFabric() {
    this._fabric = await ensureVendor("fabric");
  }

  _toolList() {
    if (this.tools === "all") return DEFAULT_TOOLS;
    return this.tools.split(",").map((tool) => tool.trim()).filter(Boolean);
  }

  firstUpdated() {
    this._initCanvas();
  }

  updated(changed) {
    if (changed.has("_loaded") && this._loaded) this._initCanvas();
    if (changed.has("tools")) {
      const tools = this._toolList();
      if (!tools.includes(this._activeTool)) this._activeTool = tools[0] || "select";
    }
    if (
      changed.has("_activeTool") ||
      changed.has("strokeColor") ||
      changed.has("strokeWidth") ||
      changed.has("sprayDensity")
    ) {
      this._syncCanvasTool();
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
      fireRightClick: true,
      stopContextMenu: true,
    });
    this._resizeCanvas();
    this._resizeObserver = new ResizeObserver(() => this._resizeCanvas());
    this._resizeObserver.observe(wrap);
    this._canvas.on("mouse:down", this._onFabricMouseDown);
    this._canvas.on("mouse:move", this._onFabricMouseMove);
    this._canvas.on("mouse:up", this._onFabricMouseUp);
    this._canvas.on("path:created", (event) => this._handlePathCreated(event));
    this._canvas.on("object:added", (event) => this._handleObjectAdded(event));
    this._canvas.on("object:modified", () => this._pushHistory());
    const upper = this._canvas.upperCanvasEl;
    upper.setAttribute("tabindex", "0");
    upper.addEventListener("wheel", this._onWheel, { passive: false });
    upper.addEventListener("mousedown", this._onMouseDownForPan);
    this._syncCanvasTool();
    this._pushHistory();
    document.addEventListener("keydown", this._onKeyDown);
  }

  _handleKeyDown(event) {
    if (!this._canvas) return;
    const focused = document.activeElement;
    const inWhiteboard = focused === this || this.shadowRoot?.contains(focused) || this.contains(focused);
    if (!inWhiteboard) return;
    if (event.key === "Delete" || event.key === "Backspace" || event.key === "Del") {
      const activeObj = this._canvas.getActiveObject();
      if (activeObj && activeObj !== this._selectionOverlay) {
        if (activeObj.type === "activeSelection") {
          this._canvas.getActiveObjects().forEach((obj) => this._canvas.remove(obj));
        } else {
          this._canvas.remove(activeObj);
        }
        this._canvas.discardActiveObject();
        this._canvas.requestRenderAll();
        this._pushHistory();
      }
      event.preventDefault();
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      if (event.shiftKey) {
        this._redo();
      } else {
        this._undo();
      }
      event.preventDefault();
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
      this._redo();
      event.preventDefault();
    }
  }

  _canvasBackground() {
    return this._backgroundColor || "#ffffff";
  }

  _setBackgroundColor(event) {
    this._backgroundColor = event.target.value;
    if (this._canvas) {
      this._canvas.backgroundColor = this._canvasBackground();
      this._canvas.renderAll();
    }
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
    const json = this._withoutSelectionOverlay(() => this._canvas.toJSON(HISTORY_PROPS));
    const serialized = JSON.stringify(json);
    const current = this._history[this._historyIndex];
    if (current && JSON.stringify(current) === serialized) return;
    const next = this._history.slice(0, this._historyIndex + 1);
    next.push(json);
    if (next.length > 60) next.shift();
    this._history = next;
    this._historyIndex = next.length - 1;
  }

  _withoutSelectionOverlay(callback) {
    if (!this._canvas || !this._selectionOverlay) return callback();
    const overlay = this._selectionOverlay;
    this._selectionOverlay = null;
    this._canvas.remove(overlay);
    try {
      return callback();
    } finally {
      this._selectionOverlay = overlay;
      this._canvas.add(overlay);
      this._canvas.bringToFront(overlay);
    }
  }

  _restoreHistory(state) {
    if (!this._canvas || !state) return;
    this._restoringHistory = true;
    this._clearSelection(false);
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      this._canvas.backgroundColor = this._canvasBackground();
      this._syncCanvasTool();
      this._canvas.renderAll();
      this._canvas.calcOffset();
      this._restoringHistory = false;
    };
    const result = this._canvas.loadFromJSON(state, finish);
    if (result?.then) {
      result.then(finish).catch((error) => {
        this._restoringHistory = false;
        throw error;
      });
    }
  }

  _undo() {
    if (this._historyIndex <= 0 || !this._canvas) return;
    this._historyIndex -= 1;
    this._restoreHistory(this._history[this._historyIndex]);
  }

  _redo() {
    if (this._historyIndex >= this._history.length - 1 || !this._canvas) return;
    this._historyIndex += 1;
    this._restoreHistory(this._history[this._historyIndex]);
  }

  _clear() {
    if (!this._canvas) return;
    this._clearSelection(false);
    this._canvas.clear();
    this._canvas.backgroundColor = this._canvasBackground();
    this._pushHistory();
  }

  _importImage() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file || !this._canvas) return;
      const url = URL.createObjectURL(file);
      try {
        await new Promise((resolve, reject) => {
          this._fabric.Image.fromURL(url, (image) => {
            if (!image) { reject(new Error("Failed to load image")); return; }
            const cw = this._canvas.width;
            const ch = this._canvas.height;
            const scale = Math.min(1, Math.min(cw / (image.width || 1), ch / (image.height || 1)) * 0.85);
            image.set({
              left: cw / 2,
              top: ch / 2,
              originX: "center",
              originY: "center",
              scaleX: scale,
              scaleY: scale,
              selectable: true,
              evented: true,
            });
            image._skipHistory = true;
            this._canvas.add(image);
            image._skipHistory = false;
            this._canvas.setActiveObject(image);
            this._canvas.requestRenderAll();
            this._pushHistory();
            resolve();
          }, { crossOrigin: "anonymous" });
        });
      } finally {
        URL.revokeObjectURL(url);
      }
    };
    input.click();
  }

  _exportImage() {
    if (!this._canvas) return;
    const dataURL = this._withoutSelectionOverlay(() => this._canvas.toDataURL({ format: "png" }));
    this.dispatchEvent(new CustomEvent("builtin-export", { detail: { dataURL, format: "png" }, bubbles: true }));
  }

  exportImage() {
    this._exportImage();
  }

  _setTool(name) {
    this._activeTool = name;
    this._clearDrawingPreview();
    if (name !== "fill") this._clearSelection(false);
    this._syncCanvasTool();
  }

  _syncCanvasTool() {
    if (!this._canvas) return;
    this._clearDrawingPreview();
    const name = this._activeTool;
    this._canvas.isDrawingMode = false;
    this._canvas.selection = name === "select";
    this._canvas.skipTargetFind = DRAWING_TOOLS.has(name);
    this._canvas.defaultCursor = name === "select" ? "default" : DRAWING_TOOLS.has(name) ? "crosshair" : "copy";
    this._canvas.hoverCursor = name === "select" ? "move" : DRAWING_TOOLS.has(name) ? "crosshair" : "copy";
    this._canvas.forEachObject((obj) => {
      if (obj === this._selectionOverlay) return;
      obj.selectable = name === "select";
      obj.evented = name === "select" || name === "fill";
    });
    if (DRAWING_TOOLS.has(name)) {
      this._canvas.isDrawingMode = true;
      this._canvas.freeDrawingBrush = this._createBrush(name);
    }
    this._canvas.discardActiveObject();
    this._canvas.requestRenderAll();
  }

  _createBrush(tool) {
    if (tool === "erase") {
      const brush = new this._fabric.PencilBrush(this._canvas);
      brush.color = "#ffffff";
      brush.width = Math.max(3, this.strokeWidth * 3);
      brush.decimate = 2;
      return brush;
    }
    if (tool === "pencil") {
      const brush = new this._fabric.PencilBrush(this._canvas);
      brush.color = this.strokeColor;
      brush.width = Math.max(0.5, this.strokeWidth * 0.6);
      brush.decimate = 0.1;
      brush.strokeLineCap = "round";
      brush.strokeLineJoin = "round";
      return brush;
    }
    const brush = new this._fabric.PencilBrush(this._canvas);
    brush.color = this.strokeColor;
    brush.width = this.strokeWidth;
    brush.decimate = 0.4;
    return brush;
  }

  _handlePathCreated(event) {
    if (!event.path) return;
    this._clearDrawingPreview();
    requestAnimationFrame(() => this._clearDrawingPreview());
    const path = event.path;
    if (this._activeTool === "erase") {
      path.set({
        globalCompositeOperation: "destination-out",
        eraserStroke: true,
        selectable: false,
        evented: false,
      });
    } else if (this._activeTool === "pencil") {
      path.set({
        strokeWidth: Math.max(0.4, this.strokeWidth * 0.5),
        strokeLineCap: "round",
        strokeLineJoin: "round",
        selectable: false,
        evented: false,
      });
    } else {
      path.set({
        selectable: this._activeTool === "select",
        evented: this._activeTool === "select",
      });
    }
    this._canvas.requestRenderAll();
    this._pushHistory();
  }

  _handleObjectAdded(event) {
    const target = event.target;
    if (
      !target ||
      this._restoringHistory ||
      target._fromHistory ||
      target._skipHistory ||
      target === this._selectionOverlay
    ) return;
    if (target.type === "path" && DRAWING_TOOLS.has(this._activeTool)) return;
    this._pushHistory();
  }

  _handleFabricMouseDown(event) {
    if (!this._canvas) return;
    this._canvas.upperCanvasEl?.focus?.();
    if (this._activeTool === "select" || DRAWING_TOOLS.has(this._activeTool)) return;
    const pointer = event.pointer || this._canvas.getPointer(event.e);
    if (this._activeTool === "fill") {
      this._fillAt(event.target, pointer);
      return;
    }

    const color = this.strokeColor;
    const width = this.strokeWidth;
    this._draftStart = pointer;
    if (this._activeTool === "rect") {
      this._draftObject = new this._fabric.Rect({ left: pointer.x, top: pointer.y, width: 1, height: 1, fill: "transparent", stroke: color, strokeWidth: width, selectable: false, evented: false });
    } else if (this._activeTool === "circle") {
      this._draftObject = new this._fabric.Circle({ left: pointer.x, top: pointer.y, radius: 1, fill: "transparent", stroke: color, strokeWidth: width, selectable: false, evented: false });
    } else if (this._activeTool === "text") {
      const target = this._canvas.findTarget(event.e, true);
      if (target && target.type === "i-text") {
        this._canvas.setActiveObject(target);
        target.enterEditing?.();
        return;
      }
      const obj = new this._fabric.IText(this._l("text", "Text"), { left: pointer.x, top: pointer.y, fill: color, fontSize: 18, selectable: true, evented: true, originX: "left", originY: "top" });
      obj._skipHistory = true;
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
    if (!this._canvas) return;
    if (DRAWING_TOOLS.has(this._activeTool)) {
      this._clearDrawingPreview();
      requestAnimationFrame(() => this._clearDrawingPreview());
      return;
    }
    if (!this._draftObject) return;
    if ((this._draftObject.width || this._draftObject.radius || 0) < 4 && (this._draftObject.height || this._draftObject.radius || 0) < 4) {
      this._canvas.remove(this._draftObject);
    } else {
      this._draftObject.set({ selectable: false, evented: false });
      this._pushHistory();
    }
    this._draftObject = null;
    this._draftStart = null;
    this._canvas.requestRenderAll();
  }

  _clearDrawingPreview() {
    const top = this._canvas?.contextTop;
    const topCanvas = this._canvas?.upperCanvasEl;
    if (!top || !topCanvas) return;
    if (typeof this._canvas.clearContext === "function") {
      this._canvas.clearContext(top);
    } else {
      top.clearRect(0, 0, topCanvas.width, topCanvas.height);
    }
  }

  _handleWheel(event) {
    if (!this._canvas) return;
    event.preventDefault();
    const delta = event.deltaY;
    let zoom = this._canvas.getZoom();
    zoom *= 0.999 ** delta;
    zoom = _clamp(zoom, 0.1, 5);
    this._canvas.zoomToPoint({ x: event.offsetX, y: event.offsetY }, zoom);
    this._zoom = Math.round(zoom * 100);
  }

  _handleMouseDownForPan(event) {
    if (!this._canvas) return;
    if (event.button === 1 || (event.button === 0 && event.altKey)) {
      this._isPanning = true;
      this._panLast = { x: event.clientX, y: event.clientY };
      this._canvas.defaultCursor = "grabbing";
      this._canvas.hoverCursor = "grabbing";
      document.addEventListener("mousemove", this._onMouseMoveForPan);
      document.addEventListener("mouseup", this._onMouseUpForPan);
      event.stopPropagation();
      event.preventDefault();
    }
  }

  _handleMouseMoveForPan(event) {
    if (!this._isPanning || !this._canvas) return;
    const dx = event.clientX - this._panLast.x;
    const dy = event.clientY - this._panLast.y;
    this._canvas.relativePan({ x: dx, y: dy });
    this._panLast = { x: event.clientX, y: event.clientY };
  }

  _handleMouseUpForPan() {
    if (!this._isPanning) return;
    this._isPanning = false;
    this._panLast = null;
    document.removeEventListener("mousemove", this._onMouseMoveForPan);
    document.removeEventListener("mouseup", this._onMouseUpForPan);
    this._syncCanvasTool();
  }

  _zoomIn() {
    if (!this._canvas) return;
    let zoom = this._canvas.getZoom();
    zoom = Math.min(zoom * 1.2, 5);
    this._canvas.zoomToPoint({ x: this._canvas.width / 2, y: this._canvas.height / 2 }, zoom);
    this._zoom = Math.round(zoom * 100);
  }

  _zoomOut() {
    if (!this._canvas) return;
    let zoom = this._canvas.getZoom();
    zoom = Math.max(zoom / 1.2, 0.1);
    this._canvas.zoomToPoint({ x: this._canvas.width / 2, y: this._canvas.height / 2 }, zoom);
    this._zoom = Math.round(zoom * 100);
  }

  _zoomFit() {
    if (!this._canvas) return;
    const objects = this._canvas.getObjects().filter((o) => o !== this._selectionOverlay && o.visible !== false);
    if (objects.length === 0) {
      this._canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
      this._zoom = 100;
      this._canvas.renderAll();
      return;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const obj of objects) {
      const rect = obj.getBoundingRect(true, true);
      minX = Math.min(minX, rect.left);
      minY = Math.min(minY, rect.top);
      maxX = Math.max(maxX, rect.left + rect.width);
      maxY = Math.max(maxY, rect.top + rect.height);
    }
    const padding = 40;
    const contentWidth = maxX - minX + padding * 2;
    const contentHeight = maxY - minY + padding * 2;
    const zoom = Math.min(this._canvas.width / contentWidth, this._canvas.height / contentHeight);
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    this._canvas.setViewportTransform([
      zoom, 0, 0, zoom,
      this._canvas.width / 2 - centerX * zoom,
      this._canvas.height / 2 - centerY * zoom,
    ]);
    this._zoom = Math.round(zoom * 100);
    this._canvas.renderAll();
  }

  async _fillAt(target, pointer) {
    if (!this._canvas) return;
    this._removeSelectionOverlay();
    const region = this._region || this._computeRegion(pointer);
    this._region = null;
    if (!region || region.count === 0) return;
    const totalPixels = region.width * region.height;
    if (region.count > totalPixels * 0.85) return;
    try {
      await this._addRegionFill(region, this.strokeColor);
    } catch (err) {
      console.error("Fill failed:", err);
    }
    this._clearSelection(false);
  }

  _magicSelect(target, pointer) {
    if (!this._canvas) return;
    this._clearSelection(false);
    const region = this._computeRegion(pointer);
    this._region = region;
    if (!region || region.count === 0) return;
    const totalPixels = region.width * region.height;
    if (region.count > totalPixels * 0.85) return;
    const overlayCanvas = this._makeRegionCanvas(region, "rgba(37, 99, 235, 0.22)", "rgba(37, 99, 235, 0.72)");
    const pos = this._pixelToWorld(region.minX, region.minY);
    const lower = this._canvas?.lowerCanvasEl;
    const scaleX = (this._canvas?.getWidth?.() || 1) / (lower?.width || 1);
    const scaleY = (this._canvas?.getHeight?.() || 1) / (lower?.height || 1);
    const overlay = new this._fabric.Image(overlayCanvas, {
      left: pos.x,
      top: pos.y,
      scaleX,
      scaleY,
      selectable: false,
      evented: false,
      excludeFromExport: true,
      name: "magic-selection",
    });
    overlay._skipHistory = true;
    this._selectionOverlay = overlay;
    this._canvas.add(overlay);
    this._canvas.bringToFront(overlay);
    this._selectionSummary = `${region.count}px`;
    this._canvas.requestRenderAll();
  }

  _pointerToPixel(pointer) {
    const vpt = this._canvas?.viewportTransform;
    const lower = this._canvas?.lowerCanvasEl;
    const physW = lower?.width || this._canvas?.getWidth?.() || 1;
    const physH = lower?.height || this._canvas?.getHeight?.() || 1;
    const logW = this._canvas?.getWidth?.() || 1;
    const logH = this._canvas?.getHeight?.() || 1;
    const sx = pointer.x * (vpt?.[0] || 1) + (vpt?.[4] || 0);
    const sy = pointer.y * (vpt?.[3] || 1) + (vpt?.[5] || 0);
    return {
      x: Math.floor(sx * (physW / logW)),
      y: Math.floor(sy * (physH / logH)),
    };
  }

  _pixelToWorld(x, y) {
    const vpt = this._canvas?.viewportTransform;
    const lower = this._canvas?.lowerCanvasEl;
    const physW = lower?.width || this._canvas?.getWidth?.() || 1;
    const physH = lower?.height || this._canvas?.getHeight?.() || 1;
    const logW = this._canvas?.getWidth?.() || 1;
    const logH = this._canvas?.getHeight?.() || 1;
    const sx = x * (logW / physW);
    const sy = y * (logH / physH);
    return {
      x: (sx - (vpt?.[4] || 0)) / (vpt?.[0] || 1),
      y: (sy - (vpt?.[5] || 0)) / (vpt?.[3] || 1),
    };
  }

  _sampleCanvasColor(pointer) {
    const lower = this._canvas?.lowerCanvasEl;
    const ctx = lower?.getContext("2d");
    if (!ctx) return _hex_to_rgb(this.strokeColor);
    const px = this._pointerToPixel(pointer);
    const x = _clamp(Math.round(px.x), 0, lower.width - 1);
    const y = _clamp(Math.round(px.y), 0, lower.height - 1);
    const data = ctx.getImageData(x, y, 1, 1).data;
    return [data[0], data[1], data[2]];
  }

  _clearSelection(render = true) {
    this._region = null;
    this._selectionSummary = "";
    this._removeSelectionOverlay(render);
  }

  _removeSelectionOverlay(render = true) {
    if (!this._canvas || !this._selectionOverlay) return;
    const overlay = this._selectionOverlay;
    this._selectionOverlay = null;
    this._canvas.remove(overlay);
    if (render) this._canvas.requestRenderAll();
  }

  _computeRegion(pointer) {
    const lower = this._canvas?.lowerCanvasEl;
    if (!lower) return null;
    const width = lower.width;
    const height = lower.height;
    const px = this._pointerToPixel(pointer);
    const startX = _clamp(px.x, 0, width - 1);
    const startY = _clamp(px.y, 0, height - 1);
    const snapshot = document.createElement("canvas");
    snapshot.width = width;
    snapshot.height = height;
    const ctx = snapshot.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(lower, 0, 0);
    const image = ctx.getImageData(0, 0, width, height);
    const data = image.data;
    const startIndex = startY * width + startX;
    const startOffset = startIndex * 4;
    const target = [data[startOffset], data[startOffset + 1], data[startOffset + 2], data[startOffset + 3]];
    const visited = new Uint8Array(width * height);
    const mask = new Uint8Array(width * height);
    const stack = [startIndex];
    let count = 0;
    let minX = startX;
    let maxX = startX;
    let minY = startY;
    let maxY = startY;
    while (stack.length) {
      const index = stack.pop();
      if (visited[index]) continue;
      visited[index] = 1;
      const x = index % width;
      const y = Math.floor(index / width);
      const offset = index * 4;
      if (!this._colorWithin(data, offset, target)) continue;
      mask[index] = 1;
      count += 1;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
      if (x > 0) stack.push(index - 1);
      if (x < width - 1) stack.push(index + 1);
      if (y > 0) stack.push(index - width);
      if (y < height - 1) stack.push(index + width);
    }
    return { width, height, mask, count, minX, minY, maxX, maxY };
  }

  _colorWithin(data, offset, target) {
    const tolerance = this.magicTolerance;
    return (
      Math.abs(data[offset] - target[0]) <= tolerance &&
      Math.abs(data[offset + 1] - target[1]) <= tolerance &&
      Math.abs(data[offset + 2] - target[2]) <= tolerance &&
      Math.abs(data[offset + 3] - target[3]) <= Math.max(18, tolerance)
    );
  }

  async _addRegionFill(region, color) {
    const layerCanvas = this._makeRegionCanvas(region, color);
    const dataURL = layerCanvas.toDataURL("image/png");
    const lower = this._canvas?.lowerCanvasEl;
    const scaleX = (this._canvas?.getWidth?.() || 1) / (lower?.width || 1);
    const scaleY = (this._canvas?.getHeight?.() || 1) / (lower?.height || 1);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Image load timeout")), 5000);
      this._fabric.Image.fromURL(dataURL, (image) => {
        clearTimeout(timer);
        if (!image) {
          resolve();
          return;
        }
        const pos = this._pixelToWorld(region.minX, region.minY);
        image.set({
          left: pos.x,
          top: pos.y,
          scaleX,
          scaleY,
          selectable: false,
          evented: false,
          name: "pixel-fill",
        });
        image._skipHistory = true;
        this._canvas.add(image);
        image._skipHistory = false;
        this._canvas.requestRenderAll();
        this._pushHistory();
        resolve();
      });
    });
  }

  _makeRegionCanvas(region, color, edgeColor = "") {
    const width = Math.max(1, region.maxX - region.minX + 1);
    const height = Math.max(1, region.maxY - region.minY + 1);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    const image = ctx.createImageData(width, height);
    const fill = this._parseColor(color);
    const edge = edgeColor ? this._parseColor(edgeColor) : fill;
    for (let y = region.minY; y <= region.maxY; y += 1) {
      for (let x = region.minX; x <= region.maxX; x += 1) {
        const sourceIndex = y * region.width + x;
        if (!region.mask[sourceIndex]) continue;
        const localX = x - region.minX;
        const localY = y - region.minY;
        const dest = (localY * width + localX) * 4;
        const rgba = edgeColor && this._isRegionEdge(region, x, y) ? edge : fill;
        image.data[dest] = rgba[0];
        image.data[dest + 1] = rgba[1];
        image.data[dest + 2] = rgba[2];
        image.data[dest + 3] = rgba[3];
      }
    }
    ctx.putImageData(image, 0, 0);
    return canvas;
  }

  _isRegionEdge(region, x, y) {
    const index = y * region.width + x;
    return (
      x === 0 ||
      y === 0 ||
      x === region.width - 1 ||
      y === region.height - 1 ||
      !region.mask[index - 1] ||
      !region.mask[index + 1] ||
      !region.mask[index - region.width] ||
      !region.mask[index + region.width]
    );
  }

  _parseColor(color) {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, 1, 1);
    const data = ctx.getImageData(0, 0, 1, 1).data;
    return [data[0], data[1], data[2], data[3]];
  }

  _toolIcon(name) {
    switch (name) {
      case "select": return html`<builtin-icon name="select" size="17" variant="outlined"></builtin-icon>`;
      case "pen": return html`<builtin-icon name="highlight" size="17" variant="outlined"></builtin-icon>`;
      case "pencil": return html`<builtin-icon name="edit" size="17" variant="outlined"></builtin-icon>`;
      case "spray": return html`<builtin-icon name="skin" size="17" variant="outlined"></builtin-icon>`;
      case "fill": return html`<builtin-icon name="bg-colors" size="17" variant="outlined"></builtin-icon>`;

      case "rect": return html`<builtin-icon name="border" size="17" variant="outlined"></builtin-icon>`;
      case "circle": return html`<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/></svg>`;
      case "text": return html`<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16"/><path d="M12 6v14"/><path d="M8 20h8"/></svg>`;
      case "erase": return html`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"><path d="M4 15.5 14.5 5a3 3 0 0 1 4.2 0l.3.3a3 3 0 0 1 0 4.2L9.5 19H5.8L4 17.2v-1.7Z"/><path d="M12 7.5 16.5 12"/><path d="M3 21h18"/></svg>`;
      default: return html`<builtin-icon name="tool" size="17" variant="outlined"></builtin-icon>`;
    }
  }

  render() {
    const tools = this._toolList();
    return html`
      <div class="board ${this.mode}">
        <div class="toolbar">
          <div class="tool-group">
            ${tools.map((tool) => html`
              <button class="tool ${this._activeTool === tool ? "active" : ""}" title=${this._l(tool, tool)} aria-label=${this._l(tool, tool)} @click=${() => this._setTool(tool)}>
                ${this._toolIcon(tool)}
              </button>
            `)}
          </div>
          <div class="props">
            <span class="prop-label" title=${this._l("stroke", "Stroke")}>${this._l("stroke", "Stroke")}</span>
            <input type="color" .value=${this.strokeColor} @input=${(e) => { this.strokeColor = e.target.value; }} title=${this._l("color", "Color")}>
            <span class="prop-label" title=${this._l("bg", "Bg")}>${this._l("bg", "Bg")}</span>
            <input type="color" .value=${this._backgroundColor} @input=${this._setBackgroundColor} title=${this._l("bgColor", "Background")}>
            ${this._activeTool !== "fill" ? html`
              <input type="range" min="1" max="36" .value=${this.strokeWidth} @input=${(e) => { this.strokeWidth = Number(e.target.value); }} title=${this._l("width", "Width")}>
            ` : null}
            ${REGION_TOOLS.has(this._activeTool) ? html`
              <input type="range" min="0" max="96" .value=${this.magicTolerance} @input=${(e) => { this.magicTolerance = Number(e.target.value); }} title=${this._l("tolerance", "Tolerance")}>
            ` : null}
          </div>
          <div class="toolbar-spacer"></div>
          <div class="tool-group">
            <button class="btn" @click=${this._undo} ?disabled=${this._historyIndex <= 0} title=${this._l("undo", "Undo")}><builtin-icon name="arrow-left" size="14" variant="outlined"></builtin-icon></button>
            <button class="btn" @click=${this._redo} ?disabled=${this._historyIndex >= this._history.length - 1} title=${this._l("redo", "Redo")}><builtin-icon name="arrow-right" size="14" variant="outlined"></builtin-icon></button>
            <button class="btn danger" @click=${this._clear} title=${this._l("clear", "Clear")}><builtin-icon name="delete" size="14" variant="outlined"></builtin-icon></button>
            <button class="btn" @click=${this._importImage} title=${this._l("import", "Import image")}><builtin-icon name="import" size="14" variant="outlined"></builtin-icon></button>
            <button class="btn primary" @click=${this._exportImage} title=${this._l("export", "Export")}><builtin-icon name="cloud-download" size="14" variant="outlined"></builtin-icon></button>
          </div>
          <div class="tool-group">
            <button class="btn" @click=${this._zoomOut} title=${this._l("zoomOut", "Zoom out")}><builtin-icon name="zoom-out" size="14" variant="outlined"></builtin-icon></button>
            <button class="btn" @click=${this._zoomFit} title=${this._l("zoomFit", "Fit content")}><builtin-icon name="scan" size="14" variant="outlined"></builtin-icon></button>
            <button class="btn" @click=${this._zoomIn} title=${this._l("zoomIn", "Zoom in")}><builtin-icon name="zoom-in" size="14" variant="outlined"></builtin-icon></button>
          </div>
          <span class="status">${this._zoom}%${this._selectionSummary ? ` · ${this._selectionSummary}` : ""}</span>
          <slot name="toolbar"></slot>
        </div>
        <div class="canvas-wrap" style=${`--wb-bg:${this._backgroundColor || "#ffffff"}`}></div>
      </div>
    `;
  }
}
