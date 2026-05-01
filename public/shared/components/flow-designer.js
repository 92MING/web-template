/**
 * @fileoverview BuiltinFlowDesigner — SVG-based node editor with pan, zoom, and port connections.
 *
 * @attr {string} nodes — JSON `[{id, type, x, y, label, inputs, outputs}]`.
 * @attr {string} edges — JSON `[{from, to, fromPort, toPort}]`.
 * @attr {string} labels — JSON i18n overrides.
 * @attr {string} mode — `default` | `compact` (default `default`).
 *
 * @event builtin-change — `{ nodes, edges }`
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinFlowDesigner extends BuiltinBaseElement {
  static properties = {
    nodes: { type: Array },
    edges: { type: Array },
    labels: { type: Object },
    mode: { type: String },
    _pan: { type: Object, state: true },
    _zoom: { type: Number, state: true },
    _draggingNode: { type: String, state: true },
    _dragOffset: { type: Object, state: true },
    _connecting: { type: Object, state: true },
    _mouse: { type: Object, state: true },
  };

  static styles = css`
    :host { display: block; }
    .designer { border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-bg-subtle, #f3f4f6); display: flex; flex-direction: column; }
    .designer.compact { font-size: 12px; }
    .toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); background: var(--builtin-surface, #ffffff); flex-wrap: wrap; }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 10px; border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-surface, #ffffff); border-radius: var(--builtin-radius, 6px); cursor: pointer; color: var(--builtin-color-text, #111827); min-height: 32px; font-size: 13px; }
    .btn:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .btn.primary { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .palette { display: inline-flex; gap: 6px; }
    .canvas { flex: 1 1 auto; position: relative; overflow: hidden; min-height: 400px; cursor: grab; touch-action: none; }
    .canvas:active { cursor: grabbing; }
    .canvas.connecting { cursor: crosshair; }
    .svg-layer { position: absolute; inset: 0; width: 100%; height: 100%; }
    .node { position: absolute; background: var(--builtin-surface, #ffffff); border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); box-shadow: 0 2px 8px rgba(0,0,0,0.06); min-width: 140px; user-select: none; }
    .node.compact { min-width: 110px; }
    .node-header { padding: 8px 10px; font-weight: 650; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); background: var(--builtin-header-bg, #f9fafb); border-radius: var(--builtin-radius, 6px) var(--builtin-radius, 6px) 0 0; display: flex; align-items: center; justify-content: space-between; }
    .node-body { padding: 8px 10px; display: flex; gap: 12px; }
    .ports { display: flex; flex-direction: column; gap: 6px; }
    .ports.left { align-items: flex-start; }
    .ports.right { align-items: flex-end; margin-left: auto; }
    .port { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 11px; color: var(--builtin-color-muted, #6b7280); }
    .port-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--builtin-color-muted, #6b7280); border: 2px solid var(--builtin-surface, #ffffff); box-shadow: 0 0 0 1px var(--builtin-border, #d1d5db); }
    .port:hover .port-dot { background: var(--builtin-primary, #2563eb); }
    .edge-path { fill: none; stroke: var(--builtin-color-muted, #6b7280); stroke-width: 2; }
    .edge-path.active { stroke: var(--builtin-primary, #2563eb); }
    .grid-bg { fill: var(--builtin-bg-subtle, #f3f4f6); }
    .grid-dot { fill: var(--builtin-border-soft, #e5e7eb); }
    .delete-btn { border: 0; background: transparent; padding: 2px; cursor: pointer; color: var(--builtin-color-muted, #9ca3af); display: inline-flex; align-items: center; }
    .delete-btn:hover { color: var(--builtin-danger, #dc2626); }
    @media (max-width: 720px) {
      .toolbar { padding: 6px; }
      .canvas { min-height: 280px; }
      .node { min-width: 120px; }
      .port { font-size: 12px; }
      .port-dot { width: 14px; height: 14px; }
    }
  `;

  constructor() {
    super();
    this.nodes = [];
    this.edges = [];
    this.mode = "default";
    this._pan = { x: 0, y: 0 };
    this._zoom = 1;
    this._draggingNode = null;
    this._dragOffset = { x: 0, y: 0 };
    this._connecting = null;
    this._mouse = { x: 0, y: 0 };
    this._palette = [
      { type: "start", label: "Start", inputs: 0, outputs: 1 },
      { type: "process", label: "Process", inputs: 1, outputs: 1 },
      { type: "decision", label: "Decision", inputs: 1, outputs: 2 },
      { type: "end", label: "End", inputs: 1, outputs: 0 },
    ];
  }

  connectedCallback() {
    super.connectedCallback();
    this._ensureData();
    this._onMouseMove = this._onMouseMove.bind(this);
    this._onMouseUp = this._onMouseUp.bind(this);
    this._onWheel = this._onWheel.bind(this);
    document.addEventListener("mousemove", this._onMouseMove);
    document.addEventListener("mouseup", this._onMouseUp);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("mousemove", this._onMouseMove);
    document.removeEventListener("mouseup", this._onMouseUp);
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _ensureData() {
    if (!Array.isArray(this.nodes)) this.nodes = [];
    if (!Array.isArray(this.edges)) this.edges = [];
  }

  _toSvg(pt) {
    return {
      x: (pt.x - this._pan.x) / this._zoom,
      y: (pt.y - this._pan.y) / this._zoom,
    };
  }

  _fromSvg(pt) {
    return {
      x: pt.x * this._zoom + this._pan.x,
      y: pt.y * this._zoom + this._pan.y,
    };
  }

  _getMouse(e) {
    const rect = this.shadowRoot.querySelector(".canvas")?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  _onMouseDown(e) {
    if (e.target.closest(".node")) return;
    if (e.button === 1 || (e.button === 0 && !this._connecting)) {
      this._panning = true;
      this._panStart = { x: e.clientX, y: e.clientY, px: this._pan.x, py: this._pan.y };
    }
  }

  _onMouseMove(e) {
    const mouse = this._getMouse(e);
    this._mouse = mouse;
    if (this._draggingNode) {
      const svgPt = this._toSvg(mouse);
      const node = this.nodes.find((n) => n.id === this._draggingNode);
      if (node) {
        node.x = svgPt.x - this._dragOffset.x;
        node.y = svgPt.y - this._dragOffset.y;
        this.nodes = this.nodes.slice();
      }
    }
    if (this._panning) {
      const dx = e.clientX - this._panStart.x;
      const dy = e.clientY - this._panStart.y;
      this._pan = { x: this._panStart.px + dx, y: this._panStart.py + dy };
    }
  }

  _onMouseUp() {
    this._draggingNode = null;
    this._panning = false;
    if (this._connecting) {
      this._connecting = null;
    }
  }

  _onWheel(e) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    this._zoom = Math.min(Math.max(this._zoom * delta, 0.3), 3);
  }

  _onNodeMouseDown(e, nodeId) {
    if (e.target.closest(".port")) return;
    const mouse = this._getMouse(e);
    const svgPt = this._toSvg(mouse);
    const node = this.nodes.find((n) => n.id === nodeId);
    if (node) {
      this._draggingNode = nodeId;
      this._dragOffset = { x: svgPt.x - node.x, y: svgPt.y - node.y };
    }
  }

  _onPortMouseDown(e, nodeId, portName, isInput) {
    e.stopPropagation();
    const mouse = this._getMouse(e);
    this._connecting = { from: isInput ? null : nodeId, to: isInput ? nodeId : null, fromPort: isInput ? null : portName, toPort: isInput ? portName : null, x: mouse.x, y: mouse.y };
  }

  _onPortMouseUp(e, nodeId, portName, isInput) {
    e.stopPropagation();
    if (!this._connecting) return;
    if (isInput) {
      if (this._connecting.from && this._connecting.from !== nodeId) {
        this._addEdge(this._connecting.from, nodeId, this._connecting.fromPort, portName);
      }
    } else {
      if (this._connecting.to && this._connecting.to !== nodeId) {
        this._addEdge(nodeId, this._connecting.to, portName, this._connecting.toPort);
      }
    }
    this._connecting = null;
  }

  _addEdge(from, to, fromPort, toPort) {
    const exists = this.edges.some((e) => e.from === from && e.to === to && e.fromPort === fromPort && e.toPort === toPort);
    if (exists) return;
    this.edges = [...this.edges, { from, to, fromPort, toPort }];
    this._emitChange();
  }

  _deleteEdge(index) {
    this.edges = this.edges.filter((_, i) => i !== index);
    this._emitChange();
  }

  _addNode(type) {
    const template = this._palette.find((p) => p.type === type);
    const id = `${type}-${Date.now()}`;
    const svgCenter = this._toSvg({ x: 300, y: 200 });
    const node = {
      id,
      type,
      x: svgCenter.x,
      y: svgCenter.y,
      label: this._l(type, template?.label || type),
      inputs: template?.inputs ?? 1,
      outputs: template?.outputs ?? 1,
    };
    this.nodes = [...this.nodes, node];
    this._emitChange();
  }

  _deleteNode(nodeId) {
    this.nodes = this.nodes.filter((n) => n.id !== nodeId);
    this.edges = this.edges.filter((e) => e.from !== nodeId && e.to !== nodeId);
    this._emitChange();
  }

  _emitChange() {
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { nodes: this.nodes, edges: this.edges }, bubbles: true }));
  }

  _portPos(nodeId, portName, isInput) {
    const el = this.shadowRoot.querySelector(`[data-node="${nodeId}"]`);
    if (!el) return { x: 0, y: 0 };
    const node = this.nodes.find((n) => n.id === nodeId);
    if (!node) return { x: 0, y: 0 };
    const portEl = el.querySelector(`[data-port="${portName}"]`);
    const rect = el.getBoundingClientRect();
    const portRect = portEl ? portEl.getBoundingClientRect() : rect;
    const canvasRect = this.shadowRoot.querySelector(".canvas").getBoundingClientRect();
    const x = (portRect.left + portRect.width / 2 - canvasRect.left - this._pan.x) / this._zoom;
    const y = (portRect.top + portRect.height / 2 - canvasRect.top - this._pan.y) / this._zoom;
    return { x, y };
  }

  _edgePath(fromPt, toPt) {
    const dx = Math.abs(toPt.x - fromPt.x) * 0.5;
    return `M ${fromPt.x} ${fromPt.y} C ${fromPt.x + dx} ${fromPt.y}, ${toPt.x - dx} ${toPt.y}, ${toPt.x} ${toPt.y}`;
  }

  _renderGrid() {
    const size = 20;
    const dots = [];
    for (let x = 0; x < 40; x++) {
      for (let y = 0; y < 30; y++) {
        dots.push(html`<circle cx="${x * size}" cy="${y * size}" r="1" class="grid-dot" />`);
      }
    }
    return html`<g>${dots}</g>`;
  }

  _renderEdges() {
    return this.edges.map((edge, i) => {
      const fromPt = this._portPos(edge.from, edge.fromPort, false);
      const toPt = this._portPos(edge.to, edge.toPort, true);
      return html`
        <path class="edge-path" d="${this._edgePath(fromPt, toPt)}"
          @click=${() => this._deleteEdge(i)} />
      `;
    });
  }

  _renderTempEdge() {
    if (!this._connecting) return null;
    const mouseSvg = this._toSvg(this._mouse);
    let fromPt, toPt;
    if (this._connecting.from) {
      fromPt = this._portPos(this._connecting.from, this._connecting.fromPort, false);
      toPt = mouseSvg;
    } else {
      fromPt = mouseSvg;
      toPt = this._portPos(this._connecting.to, this._connecting.toPort, true);
    }
    return html`<path class="edge-path active" d="${this._edgePath(fromPt, toPt)}" />`;
  }

  _portName(kind, index) {
    return `${kind}-${index}`;
  }

  _renderNodes() {
    return this.nodes.map((node) => {
      const left = node.x * this._zoom + this._pan.x;
      const top = node.y * this._zoom + this._pan.y;
      const inputs = Array.from({ length: node.inputs || 0 }, (_, i) => this._portName("in", i));
      const outputs = Array.from({ length: node.outputs || 0 }, (_, i) => this._portName("out", i));
      return html`
        <div class="node ${this.mode}" data-node="${node.id}"
          style="left:${left}px;top:${top}px;transform:scale(${this._zoom});transform-origin:top left;"
          @mousedown=${(e) => this._onNodeMouseDown(e, node.id)}>
          <div class="node-header">
            <span>${node.label}</span>
            <button class="delete-btn" @click=${() => this._deleteNode(node.id)} title=${this._l("delete", "Delete")}>
              <builtin-icon name="close" size="12" variant="outlined"></builtin-icon>
            </button>
          </div>
          <div class="node-body">
            <div class="ports left">
              ${inputs.map((p) => html`
                <div class="port" data-port="${p}"
                  @mousedown=${(e) => this._onPortMouseDown(e, node.id, p, true)}
                  @mouseup=${(e) => this._onPortMouseUp(e, node.id, p, true)}>
                  <span class="port-dot"></span>
                  <span>${p}</span>
                </div>
              `)}
            </div>
            <div class="ports right">
              ${outputs.map((p) => html`
                <div class="port" data-port="${p}"
                  @mousedown=${(e) => this._onPortMouseDown(e, node.id, p, false)}
                  @mouseup=${(e) => this._onPortMouseUp(e, node.id, p, false)}>
                  <span>${p}</span>
                  <span class="port-dot"></span>
                </div>
              `)}
            </div>
          </div>
        </div>
      `;
    });
  }

  render() {
    this._ensureData();
    return html`
      <div class="designer ${this.mode}">
        <div class="toolbar">
          <div class="palette">
            ${this._palette.map((p) => html`
              <button class="btn" @click=${() => this._addNode(p.type)}>${this._l(p.type, p.label)}</button>
            `)}
          </div>
          <div class="tool-group">
            <button class="btn" @click=${() => this._zoom = Math.min(this._zoom * 1.2, 3)} title=${this._l("zoomIn", "Zoom in")}>
              <builtin-icon name="plus" size="14" variant="outlined"></builtin-icon>
            </button>
            <button class="btn" @click=${() => this._zoom = Math.max(this._zoom / 1.2, 0.3)} title=${this._l("zoomOut", "Zoom out")}>
              <builtin-icon name="minus" size="14" variant="outlined"></builtin-icon>
            </button>
            <button class="btn" @click=${() => { this._zoom = 1; this._pan = { x: 0, y: 0 }; }} title=${this._l("resetView", "Reset view")}>
              <builtin-icon name="undo" size="14" variant="outlined"></builtin-icon>
            </button>
          </div>
          <slot name="toolbar"></slot>
        </div>
        <div class="canvas ${this._connecting ? "connecting" : ""}"
          @mousedown=${this._onMouseDown}
          @wheel=${this._onWheel}>
          <svg class="svg-layer" width="100%" height="100%">
            ${this._renderGrid()}
            ${this._renderEdges()}
            ${this._renderTempEdge()}
          </svg>
          ${this._renderNodes()}
        </div>
      </div>
    `;
  }
}
