import { BuiltinIcon } from "../basic/icon.js";
import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

if (!customElements.get("builtin-icon")) customElements.define("builtin-icon", BuiltinIcon);

const DEFAULT_NODES = [
  { id: "start", type: "flow/start", x: 80, y: 120, label: "Start", outputs: 1 },
  { id: "process", type: "flow/process", x: 340, y: 120, label: "Process", inputs: 1, outputs: 1 },
];

const FLOW_NODE_TYPES = new Set();
const FLOW_POPUP_STYLE_ID = "builtin-flow-designer-litegraph-popups";
const FLOW_POPUP_SELECTOR = ".litegraph.litecontextmenu, .litegraph.litesearchbox, .graphdialog";

const NODE_PALETTE = ["#2563eb", "#0891b2", "#16a34a", "#d97706", "#7c3aed", "#dc2626"];

function _safe_count(value) {
  return Math.max(0, Number(value) || 0);
}

export class BuiltinFlowDesigner extends BuiltinBaseElement {
  static properties = {
    nodes: { type: Array },
    edges: { type: Array },
    labels: { type: Object },
    mode: { type: String },
    readonly: { type: Boolean, reflect: true },
  };

  static styles = css`
    :host {
      display: block;
      --flow-canvas-height: var(--builtin-flow-height, clamp(360px, 54vh, 560px));
    }
    .designer {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 48px;
      padding: 8px 10px 8px 12px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    .toolbar-main {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      min-width: 0;
    }
    .mark {
      width: 28px;
      height: 28px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-primary-soft, #eff6ff);
      color: var(--builtin-primary, #2563eb);
      flex: 0 0 auto;
    }
    .title-group { min-width: 0; }
    .title {
      font-size: 13px;
      font-weight: 700;
      line-height: 1.25;
      color: var(--builtin-color-text, #111827);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .summary {
      display: flex;
      gap: 8px;
      margin-top: 2px;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
      line-height: 1.2;
      white-space: nowrap;
    }
    .toolbar-actions {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex: 0 0 auto;
      padding: 3px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
    }
    button {
      width: 30px;
      height: 30px;
      min-height: 30px;
      padding: 0;
      border: 0;
      border-radius: var(--builtin-radius, 6px);
      background: transparent;
      color: var(--builtin-color-muted, #6b7280);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    button:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
      color: var(--builtin-color-text, #111827);
    }
    button:active { transform: translateY(1px); }
    .canvas-shell {
      position: relative;
      min-height: 320px;
      height: var(--flow-canvas-height);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--builtin-surface, #ffffff) 92%, var(--builtin-primary, #2563eb)), var(--builtin-surface, #ffffff));
    }
    canvas {
      display: block;
      width: 100%;
      height: 100%;
      outline: none;
      touch-action: none;
      cursor: grab;
    }
    canvas:active { cursor: grabbing; }
    .empty {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      pointer-events: none;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 72%, transparent);
    }
    @media (max-width: 720px) {
      :host { --flow-canvas-height: var(--builtin-flow-mobile-height, min(72vh, 520px)); }
      .toolbar {
        align-items: stretch;
        flex-direction: column;
        gap: 8px;
        padding: 10px;
      }
      .toolbar-actions {
        width: 100%;
        justify-content: space-between;
      }
      .toolbar-actions button { flex: 1 1 0; }
      .summary { flex-wrap: wrap; white-space: normal; }
      .canvas-shell { min-height: 360px; }
    }
  `;

  constructor() {
    super();
    this.nodes = [];
    this.edges = [];
    this.labels = {};
    this.mode = "default";
    this.readonly = false;
    this._graph = null;
    this._canvas = null;
    this._LiteGraph = null;
    this._resizeObserver = null;
    this._syncGraphHandle = 0;
    this._isSeedingGraph = false;
    this._isSyncingGraph = false;
    this._popupViewportListener = null;
    this._onWindowKeyDown = (event) => this._handle_window_keydown(event);
    this._onCanvasPointerDown = () => this._activate_canvas();
    this._onCanvasFocus = () => this._activate_canvas();
    this._popupFixedClasses = new Set(["litesearchbox", "graphdialog"]);
  }

  firstUpdated() {
    this._init_graph();
  }

  updated(changed) {
    if (changed.has("_ptTheme") || changed.has("mode")) this._apply_theme();
    if (this._graph && !this._isSyncingGraph && (changed.has("nodes") || changed.has("edges"))) this._seed_graph();
    if (changed.has("_ptMobile")) this._schedule_resize();
  }

  connectedCallback() {
    super.connectedCallback();
    BuiltinFlowDesigner._instances ??= new Set();
    BuiltinFlowDesigner._instances.add(this);
    window.addEventListener("keydown", this._onWindowKeyDown, true);
  }

  disconnectedCallback() {
    this._resizeObserver?.disconnect?.();
    this._graph?.stop?.();
    this._canvas?.stopRendering?.();
    this._canvas?.canvas?.removeEventListener("pointerdown", this._onCanvasPointerDown, true);
    this._canvas?.canvas?.removeEventListener("focus", this._onCanvasFocus, true);
    window.removeEventListener("keydown", this._onWindowKeyDown, true);
    if (this._popupViewportListener) {
      window.removeEventListener("resize", this._popupViewportListener);
      window.removeEventListener("scroll", this._popupViewportListener);
      this._popupViewportListener = null;
    }
    if (BuiltinFlowDesigner._activeInstance === this) BuiltinFlowDesigner._activeInstance = null;
    BuiltinFlowDesigner._instances?.delete(this);
    this._canvas = null;
    this._graph = null;
    super.disconnectedCallback();
  }

  async _init_graph() {
    const LiteGraph = await ensureVendor("litegraph", { css: "/vendor/litegraph/litegraph.min.css" });
    const canvas = this.renderRoot.querySelector("canvas");
    const shell = this.renderRoot.querySelector(".canvas-shell");
    if (!canvas || !shell || this._graph) return;

    this._LiteGraph = LiteGraph;
    this._register_flow_nodes(LiteGraph);
    this._graph = new LiteGraph.LGraph();
    this._graph.config.align_to_grid = true;
    this._canvas = new LiteGraph.LGraphCanvas(canvas, this._graph, { autoresize: false });
    this._canvas.show_info = false;
    this._canvas.allow_searchbox = !this.readonly;
    this._canvas.read_only = this.readonly;
    this._canvas.background_image = null;
    this._canvas.round_radius = 8;
    this._canvas.connections_width = 2.5;
    this._canvas.render_canvas_border = false;
    this._canvas.onAfterChange = () => this._schedule_graph_sync();
    this._canvas.onNodeMoved = (node) => {
      if (Array.isArray(node?.pos)) {
        node.pos[0] = Math.round(node.pos[0]);
        node.pos[1] = Math.round(node.pos[1]);
      }
      this._schedule_graph_sync();
    };
    canvas.tabIndex = 0;
    canvas.addEventListener("pointerdown", this._onCanvasPointerDown, true);
    canvas.addEventListener("focus", this._onCanvasFocus, true);
    this._wrap_popup_methods();
    this._ensure_popup_bridge();
    this._apply_theme();
    this._seed_graph();
    this._graph.start();
    this._resizeObserver = new ResizeObserver(() => this._schedule_resize());
    this._resizeObserver.observe(shell);
    this._schedule_resize(2);
  }

  _register_flow_nodes(LiteGraph) {
    for (const type of ["flow/start", "flow/process", "flow/decision", "flow/end"]) {
      if (LiteGraph.registered_node_types?.[type] || FLOW_NODE_TYPES.has(type)) continue;
      class FlowNode {
        constructor() {
          this.properties = { label: "" };
        }
        onExecute() {}
      }
      FlowNode.title = type.split("/").pop();
      FlowNode.desc = "Flow node";
      FlowNode.size = [150, 52];
      LiteGraph.registerNodeType(type, FlowNode);
      FLOW_NODE_TYPES.add(type);
    }
  }

  _theme_values() {
    const styles = getComputedStyle(this);
    const css = (name, fallback) => styles.getPropertyValue(name).trim() || fallback;
    const dark = this._ptTheme === "dark";
    return {
      bg: css("--builtin-surface", dark ? "#1f2937" : "#ffffff"),
      canvasBg: dark ? css("--builtin-bg-subtle", "#111827") : css("--builtin-header-bg", "#f9fafb"),
      nodeBg: dark ? "#1f2937" : "#ffffff",
      nodeBorder: css("--builtin-border", dark ? "#374151" : "#d1d5db"),
      nodeText: css("--builtin-color-text", dark ? "#e5e7eb" : "#111827"),
      muted: css("--builtin-color-muted", dark ? "#9ca3af" : "#6b7280"),
      primary: css("--builtin-primary", dark ? "#3b82f6" : "#2563eb"),
      link: dark ? "#93c5fd" : "#2563eb",
      slotOff: dark ? "#64748b" : "#94a3b8",
      slotOn: dark ? "#60a5fa" : "#2563eb",
    };
  }

  _apply_theme() {
    if (!this._canvas) return;
    const theme = this._theme_values();
    this._canvas.clear_background = true;
    this._canvas.clear_background_color = theme.canvasBg;
    this._canvas.onRenderBackground = (_canvas, ctx) => this._draw_background(ctx, theme.canvasBg);
    this._canvas.node_title_color = theme.nodeText;
    this._canvas.default_link_color = theme.link;
    this._canvas.default_connection_color = {
      input_off: theme.slotOff,
      input_on: theme.slotOn,
      output_off: theme.slotOff,
      output_on: theme.slotOn,
    };
    this._canvas.title_text_font = "600 13px Segoe UI, Inter, Arial";
    this._canvas.inner_text_font = "500 12px Segoe UI, Inter, Arial";
    this._style_nodes();
    this._apply_popup_theme(theme);
    this._defer_popup_layout();
    this._graph?.setDirtyCanvas?.(true, true);
  }

  _draw_background(ctx, color) {
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.restore();
    return true;
  }

  _style_nodes() {
    if (!this._graph) return;
    const theme = this._theme_values();
    this._graph._nodes?.forEach((node, index) => {
      const accent = node.__flow_accent || NODE_PALETTE[index % NODE_PALETTE.length];
      node.color = accent;
      node.bgcolor = theme.nodeBg;
      node.boxcolor = accent;
      node.constructor.title_text_color = theme.nodeText;
      node.constructor.shape = this._LiteGraph?.ROUND_SHAPE;
    });
  }

  _source_nodes() {
    return Array.isArray(this.nodes) && this.nodes.length ? this.nodes : DEFAULT_NODES;
  }

  _seed_graph() {
    if (!this._graph || !this._LiteGraph) return;
    const LiteGraph = this._LiteGraph;
    const sourceNodes = this._source_nodes();
    const sourceEdges = Array.isArray(this.edges) ? this.edges : [];
    const nodeMap = new Map();

    this._isSeedingGraph = true;
    this._graph.stop?.();
    this._graph.clear();

    sourceNodes.forEach((item, index) => {
      const requestedType = item.type || "flow/process";
      const node = LiteGraph.createNode(requestedType) || LiteGraph.createNode(this._flow_type_for(item));
      if (!node) return;
      const flowType = node.type?.startsWith("flow/") ? node.type : this._flow_type_for(item);
      const flowDefaults = node.type?.startsWith("flow/");
      const defaultInputs = flowDefaults ? (flowType === "flow/start" ? 0 : 1) : (node.inputs?.length || 0);
      const defaultOutputs = flowDefaults ? (flowType === "flow/end" ? 0 : 1) : (node.outputs?.length || 0);
      const inputCount = item.inputs === undefined ? defaultInputs : _safe_count(item.inputs);
      const outputCount = item.outputs === undefined ? defaultOutputs : _safe_count(item.outputs);

      node.title = item.label || item.title || item.id || item.type || "Node";
      node.properties = { ...(node.properties || {}), ...(item.properties || {}) };
      node.pos = [Number(item.x) || 80 + index * 220, Number(item.y) || 100];
      node.__flow_id = item.id;
      node.__flow_accent = item.color || NODE_PALETTE[index % NODE_PALETTE.length];
      this._ensure_slots(node, inputCount, outputCount);
      this._graph.add(node);
      nodeMap.set(item.id ?? String(index), node);
    });

    sourceEdges.forEach((edge) => {
      const from = nodeMap.get(edge.from);
      const to = nodeMap.get(edge.to);
      if (!from || !to) return;
      const fromSlot = this._slot_index(edge.fromPort, false);
      const toSlot = this._slot_index(edge.toPort, true);
      from.connect(Math.min(fromSlot, Math.max(0, (from.outputs?.length || 1) - 1)), to, Math.min(toSlot, Math.max(0, (to.inputs?.length || 1) - 1)));
    });

    this._style_nodes();
    this._graph.start();
    this._schedule_resize(2);
    requestAnimationFrame(() => {
      this._fit_view();
      this._isSeedingGraph = false;
    });
  }

  _flow_type_for(item) {
    const raw = String(item.type || "process").toLowerCase();
    if (["start", "process", "decision", "end"].includes(raw)) return `flow/${raw}`;
    return "flow/process";
  }

  _ensure_slots(node, inputCount, outputCount) {
    while ((node.inputs?.length || 0) < inputCount) node.addInput(`In ${(node.inputs?.length || 0) + 1}`, "");
    while ((node.outputs?.length || 0) < outputCount) node.addOutput(`Out ${(node.outputs?.length || 0) + 1}`, "");
  }

  _slot_index(port, output) {
    if (typeof port === "number") return Math.max(0, port);
    const match = String(port || "").match(output ? /out-(\d+)/i : /in-(\d+)/i);
    return match ? Number(match[1]) : 0;
  }

  _schedule_resize(retries = 1) {
    let count = 0;
    const tick = () => {
      this._resize_canvas();
      count += 1;
      if (count < retries) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  _resize_canvas() {
    const shell = this.renderRoot.querySelector(".canvas-shell");
    if (!shell || !this._canvas) return;
    const rect = shell.getBoundingClientRect();
    const width = Math.max(320, Math.round(rect.width));
    const height = Math.max(this._ptMobile ? 360 : 320, Math.round(rect.height));
    this._canvas.resize(width, height);
    this._canvas.canvas.style.width = `${width}px`;
    this._canvas.canvas.style.height = `${height}px`;
  }

  _fit_view() {
    if (!this._canvas || !this._graph?._nodes?.length) return;
    const nodes = this._graph._nodes;
    const left = Math.min(...nodes.map((node) => node.pos[0]));
    const top = Math.min(...nodes.map((node) => node.pos[1] - 40));
    const right = Math.max(...nodes.map((node) => node.pos[0] + (node.size?.[0] || 160)));
    const bottom = Math.max(...nodes.map((node) => node.pos[1] + (node.size?.[1] || 80)));
    const width = Math.max(1, right - left);
    const height = Math.max(1, bottom - top);
    const canvas = this._canvas.canvas;

    if (this._ptMobile) {
      const scale = Math.min(1, Math.max(0.8, Math.min((canvas.height - 96) / height, 1)));
      this._canvas.ds.scale = scale;
      this._canvas.ds.offset[0] = this._snap_offset(22 / scale - left, scale);
      this._canvas.ds.offset[1] = this._snap_offset(132 / scale - top, scale);
      this._clear_canvas_state();
      this._canvas.setDirty(true, true);
      return;
    }

    const scale = Math.min(1, Math.max(0.52, Math.min((canvas.width - 72) / width, (canvas.height - 72) / height)));
    this._canvas.ds.scale = scale;
    this._canvas.ds.offset[0] = this._snap_offset(-left + (canvas.width / scale - width) / 2, scale);
    this._canvas.ds.offset[1] = this._snap_offset(-top + (canvas.height / scale - height) / 2, scale);
    this._clear_canvas_state();
    this._canvas.setDirty(true, true);
  }

  _snap_offset(value, scale = this._canvas?.ds?.scale || 1) {
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    const step = 1 / Math.max(1, ratio * Math.max(scale, 0.1));
    return Math.round(value / step) * step;
  }

  _clear_canvas_state() {
    if (!this._canvas) return;
    this._canvas.dragging_rectangle = null;
    this._canvas.dragging_canvas = false;
    this._canvas.selected_group = null;
    this._canvas.selected_group_resizing = false;
    this._canvas.node_dragged = null;
    this._canvas.resizing_node = null;
  }

  _zoom(delta) {
    if (!this._canvas) return;
    const canvas = this._canvas.canvas;
    const next = Math.max(0.35, Math.min(2.2, this._canvas.ds.scale + delta));
    this._canvas.setZoom(next, [canvas.width / 2, canvas.height / 2]);
  }

  _activate_canvas() {
    if (!this._canvas?.canvas) return;
    BuiltinFlowDesigner._activeInstance = this;
    this._canvas.canvas.focus();
    this._defer_popup_layout();
  }

  _handle_window_keydown(event) {
    if (BuiltinFlowDesigner._activeInstance !== this) return;
    if (this.readonly) return;
    const target = event.target;
    if (target?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName)) return;
    if (event.key !== "Delete" && event.key !== "Backspace") return;
    if (!this._delete_selection()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  _delete_selection() {
    const selected = Object.keys(this._canvas?.selected_nodes || {});
    if (!selected.length) return false;
    this._canvas.deleteSelectedNodes();
    this._schedule_graph_sync();
    return true;
  }

  _schedule_graph_sync() {
    if (this._isSeedingGraph || this._syncGraphHandle) return;
    this._syncGraphHandle = requestAnimationFrame(() => {
      this._syncGraphHandle = 0;
      this._sync_from_graph();
    });
  }

  _sync_from_graph() {
    if (!this._graph?._nodes) return;
    const nodes = this._graph._nodes.map((node) => ({
      id: node.__flow_id || String(node.id),
      type: node.type,
      x: Math.round(node.pos[0]),
      y: Math.round(node.pos[1]),
      label: node.title,
      inputs: node.inputs?.length || 0,
      outputs: node.outputs?.length || 0,
      color: node.__flow_accent,
    }));
    const edges = Object.values(this._graph.links || {})
      .filter(Boolean)
      .map((link) => ({
        from: this._graph.getNodeById(link.origin_id)?.__flow_id || String(link.origin_id),
        to: this._graph.getNodeById(link.target_id)?.__flow_id || String(link.target_id),
        fromPort: `out-${link.origin_slot}`,
        toPort: `in-${link.target_slot}`,
      }));

    this._isSyncingGraph = true;
    this.nodes = nodes;
    this.edges = edges;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { nodes, edges }, bubbles: true, composed: true }));
    Promise.resolve().then(() => {
      this._isSyncingGraph = false;
    });
  }

  _wrap_popup_methods() {
    if (!this._canvas || this._canvas.__builtin_popup_wrapped) return;
    const wrap = (name) => {
      const original = this._canvas[name]?.bind(this._canvas);
      if (!original) return;
      this._canvas[name] = (...args) => {
        const scrollX = window.scrollX;
        const scrollY = window.scrollY;
        const result = original(...args);
        if (result instanceof HTMLElement) {
          this._prepare_popup(result, { scrollX, scrollY });
          if (name === "showSearchBox") window.scrollTo({ left: scrollX, top: scrollY, behavior: "instant" });
        }
        this._activate_canvas();
        return result;
      };
    };
    wrap("showSearchBox");
    wrap("processContextMenu");
    this._canvas.__builtin_popup_wrapped = true;
  }

  _ensure_popup_bridge() {
    this._ensure_popup_styles();
    if (!BuiltinFlowDesigner._popupObserver) {
      BuiltinFlowDesigner._popupObserver = new MutationObserver((entries) => {
        const instance = BuiltinFlowDesigner._activeInstance || BuiltinFlowDesigner._instances?.values()?.next()?.value;
        if (!instance) return;
        for (const entry of entries) {
          entry.addedNodes.forEach((node) => {
            if (!(node instanceof HTMLElement)) return;
            if (node.matches?.(FLOW_POPUP_SELECTOR)) instance._prepare_popup(node);
            node.querySelectorAll?.(FLOW_POPUP_SELECTOR).forEach((popup) => instance._prepare_popup(popup));
          });
        }
      });
      BuiltinFlowDesigner._popupObserver.observe(document.body, { childList: true, subtree: true });
    }
    if (!this._popupViewportListener) {
      this._popupViewportListener = () => this._clamp_open_popups();
      window.addEventListener("resize", this._popupViewportListener, { passive: true });
      window.addEventListener("scroll", this._popupViewportListener, { passive: true });
    }
    this._defer_popup_layout();
  }

  _ensure_popup_styles() {
    if (document.getElementById(FLOW_POPUP_STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = FLOW_POPUP_STYLE_ID;
    style.textContent = `
      .builtin-flow-popup {
        font-family: Inter, "Segoe UI", Arial, sans-serif !important;
        color: var(--builtin-flow-popup-text, #111827) !important;
        background: var(--builtin-flow-popup-surface, #ffffff) !important;
        background-color: var(--builtin-flow-popup-surface, #ffffff) !important;
        background-image: none !important;
        border: 1px solid var(--builtin-flow-popup-border, #d1d5db) !important;
        border-radius: 14px !important;
        box-shadow: 0 18px 48px rgba(15, 23, 42, 0.28) !important;
        backdrop-filter: blur(18px);
        overflow: hidden !important;
        z-index: 9999 !important;
      }
      .builtin-flow-popup.litegraph.litecontextmenu,
      .builtin-flow-popup.litegraph.litesearchbox,
      .builtin-flow-popup.graphdialog {
        padding: 6px !important;
        min-width: 196px !important;
        background: var(--builtin-flow-popup-surface, #ffffff) !important;
        background-color: var(--builtin-flow-popup-surface, #ffffff) !important;
      }
      .builtin-flow-popup.litegraph.litesearchbox,
      .builtin-flow-popup.graphdialog {
        position: fixed !important;
      }
      .builtin-flow-popup .litemenu-title,
      .builtin-flow-popup .graphcontextmenu-title {
        margin: 0 0 4px !important;
        padding: 6px 10px !important;
        border-radius: 9px !important;
        background: var(--builtin-flow-popup-subtle, #f3f4f6) !important;
        color: var(--builtin-flow-popup-text, #111827) !important;
        font-size: 11px !important;
        font-weight: 700 !important;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .builtin-flow-popup .litemenu-entry,
      .builtin-flow-popup .graphmenu-entry,
      .builtin-flow-popup .lite-search-item {
        position: relative;
        display: block;
        width: 100%;
        margin: 2px 0 !important;
        padding: 8px 10px !important;
        border: 1px solid transparent !important;
        border-radius: 9px !important;
        background: transparent !important;
        color: var(--builtin-flow-popup-text, #111827) !important;
        font-size: 13px !important;
        line-height: 1.25 !important;
        transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
      }
      .builtin-flow-popup .litemenu-entry.has_submenu {
        padding-right: 26px !important;
        border-right: 0 !important;
      }
      .builtin-flow-popup .litemenu-entry .more {
        position: absolute;
        top: 50%;
        right: 10px;
        float: none !important;
        padding-right: 0 !important;
        transform: translateY(-50%);
        opacity: 0.6;
      }
      .builtin-flow-popup .litemenu-entry.separator {
        margin: 4px 0 !important;
        padding: 0 !important;
      }
      .builtin-flow-popup .litemenu-entry:hover,
      .builtin-flow-popup .graphmenu-entry:hover,
      .builtin-flow-popup .lite-search-item:hover,
      .builtin-flow-popup .lite-search-item.selected {
        background: var(--builtin-flow-popup-soft, #eff6ff) !important;
        border-color: var(--builtin-flow-popup-soft-border, #bfdbfe) !important;
        color: var(--builtin-flow-popup-accent, #2563eb) !important;
      }
      .builtin-flow-popup.litegraph.litesearchbox input,
      .builtin-flow-popup.litegraph.litesearchbox select,
      .builtin-flow-popup.graphdialog input,
      .builtin-flow-popup.graphdialog textarea,
      .builtin-flow-popup.graphdialog select {
        width: 100% !important;
        min-height: 38px !important;
        margin: 0 !important;
        padding: 0 11px !important;
        border: 1px solid var(--builtin-flow-popup-border, #d1d5db) !important;
        border-radius: 9px !important;
        background: var(--builtin-flow-popup-input, #ffffff) !important;
        color: var(--builtin-flow-popup-text, #111827) !important;
        font: 500 13px/1.2 Inter, "Segoe UI", Arial, sans-serif !important;
        outline: none !important;
      }
      .builtin-flow-popup.litegraph.litesearchbox .helper {
        margin-top: 6px !important;
        padding-top: 4px !important;
        border-top: 1px solid var(--builtin-flow-popup-border-soft, #e5e7eb) !important;
        max-height: min(40vh, 320px) !important;
      }
      .builtin-flow-popup.graphdialog {
        padding: 10px !important;
        min-width: min(420px, calc(100vw - 24px)) !important;
        max-width: calc(100vw - 24px) !important;
      }
      .builtin-flow-popup.graphdialog button,
      .builtin-flow-popup .btn {
        min-height: 36px !important;
        padding: 0 12px !important;
        border: 1px solid var(--builtin-flow-popup-border, #d1d5db) !important;
        border-radius: 10px !important;
        background: var(--builtin-flow-popup-subtle, #f3f4f6) !important;
        color: var(--builtin-flow-popup-text, #111827) !important;
        font: 600 13px/1 Inter, "Segoe UI", Arial, sans-serif !important;
      }
    `;
    document.head.appendChild(style);
  }

  _apply_popup_theme(theme = this._theme_values()) {
    document.documentElement.style.setProperty("--builtin-flow-popup-surface", theme.bg);
    document.documentElement.style.setProperty("--builtin-flow-popup-input", theme.nodeBg);
    document.documentElement.style.setProperty("--builtin-flow-popup-text", theme.nodeText);
    document.documentElement.style.setProperty("--builtin-flow-popup-border", theme.nodeBorder);
    document.documentElement.style.setProperty("--builtin-flow-popup-border-soft", theme.nodeBorder);
    document.documentElement.style.setProperty("--builtin-flow-popup-subtle", theme.canvasBg);
    document.documentElement.style.setProperty("--builtin-flow-popup-soft", `${theme.primary}1a`);
    document.documentElement.style.setProperty("--builtin-flow-popup-soft-border", `${theme.primary}55`);
    document.documentElement.style.setProperty("--builtin-flow-popup-accent", theme.primary);
  }

  _prepare_popup(popup, position) {
    popup.classList.add("builtin-flow-popup");
    this._normalize_popup_position(popup, position);
    this._apply_popup_theme();
    this._clamp_popup(popup);
  }

  _normalize_popup_position(popup, position) {
    const computed = getComputedStyle(popup);
    const rawLeft = parseFloat(popup.style.left || "") || 0;
    const rawTop = parseFloat(popup.style.top || "") || 0;
    const sourceScrollX = position?.scrollX ?? window.scrollX;
    const sourceScrollY = position?.scrollY ?? window.scrollY;
    const shouldFix = [...this._popupFixedClasses].some((className) => popup.classList.contains(className));

    if (!shouldFix) return;

    if (computed.position !== "fixed") {
      popup.style.left = `${rawLeft - sourceScrollX}px`;
      popup.style.top = `${rawTop - sourceScrollY}px`;
    }
    popup.style.position = "fixed";
  }

  _clamp_open_popups() {
    document.querySelectorAll(FLOW_POPUP_SELECTOR).forEach((popup) => this._prepare_popup(popup));
  }

  _defer_popup_layout() {
    requestAnimationFrame(() => {
      this._clamp_open_popups();
      requestAnimationFrame(() => this._clamp_open_popups());
    });
  }

  _clamp_popup(popup) {
    const computed = getComputedStyle(popup);
    const isFixed = computed.position === "fixed";
    const minLeft = isFixed ? 12 : window.scrollX + 12;
    const minTop = isFixed ? 12 : window.scrollY + 12;
    popup.style.maxWidth = `${Math.max(220, window.innerWidth - 24)}px`;
    popup.style.maxHeight = `${Math.max(160, window.innerHeight - 24)}px`;
    const rect = popup.getBoundingClientRect();
    const rawLeft = parseFloat(popup.style.left || "") || (isFixed ? rect.left : rect.left + window.scrollX);
    const rawTop = parseFloat(popup.style.top || "") || (isFixed ? rect.top : rect.top + window.scrollY);
    const maxLeft = (isFixed ? window.innerWidth : window.scrollX + window.innerWidth) - rect.width - 12;
    const maxTop = (isFixed ? window.innerHeight : window.scrollY + window.innerHeight) - rect.height - 12;
    popup.style.left = `${Math.max(minLeft, Math.min(rawLeft, maxLeft))}px`;
    popup.style.top = `${Math.max(minTop, Math.min(rawTop, maxTop))}px`;
  }

  getData() {
    if (!this._graph?._nodes) return { nodes: this.nodes || [], edges: this.edges || [] };
    const nodes = this._graph._nodes.map((node) => ({
      id: node.__flow_id || String(node.id),
      type: node.type,
      x: Math.round(node.pos[0]),
      y: Math.round(node.pos[1]),
      label: node.title,
    }));
    return { nodes, edges: this.edges || [] };
  }

  _l(key, fallback = "") {
    const override = this.labels?.[key];
    if (override != null) return override;
    if (fallback !== "") return fallback;
    return this._t(`flowDesigner.${key}`);
  }

  render() {
    const nodes = this._source_nodes();
    const edges = Array.isArray(this.edges) ? this.edges : [];
    return html`
      <div class="designer">
        <div class="toolbar">
          <div class="toolbar-main">
            <span class="mark"><builtin-icon name="branches" size="17" variant="outlined"></builtin-icon></span>
            <div class="title-group">
              <div class="title">${this._l("title", "Flow Designer")}</div>
              <div class="summary">
                <span>${nodes.length} ${this._l("nodes", "nodes")}</span>
                <span>${edges.length} ${this._l("edges", "edges")}</span>
              </div>
            </div>
          </div>
          <div class="toolbar-actions" aria-label=${this._l("toolbar", "Flow tools")}>
            <button type="button" @click=${() => this._zoom(-0.12)} title=${this._l("zoomOut", "Zoom out")}>
              <builtin-icon name="zoom-out" size="16" variant="outlined"></builtin-icon>
            </button>
            <button type="button" @click=${() => this._fit_view()} title=${this._l("fit", "Fit")}> 
              <builtin-icon name="fullscreen" size="16" variant="outlined"></builtin-icon>
            </button>
            <button type="button" @click=${() => this._zoom(0.12)} title=${this._l("zoomIn", "Zoom in")}>
              <builtin-icon name="zoom-in" size="16" variant="outlined"></builtin-icon>
            </button>
          </div>
        </div>
        <div class="canvas-shell">
          <canvas aria-label=${this._l("canvas", "Flow canvas")}></canvas>
          ${nodes.length ? null : html`<div class="empty">${this._l("empty", "No nodes")}</div>`}
        </div>
      </div>
    `;
  }
}