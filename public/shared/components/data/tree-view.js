import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinTreeView — nested tree with expand/collapse, checkboxes, and drag-and-drop.
 *
 * @element builtin-tree-view
 *
 * @attr {string} items — JSON array of nodes: {id, label, children, checked, expanded}
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @event builtin-toggle — Node expanded/collapsed. detail: {id, expanded}
 * @event builtin-check — Node checked/unchecked. detail: {id, checked}
 * @event builtin-select — Node selected. detail: {id}
 */
export class BuiltinTreeView extends BuiltinBaseElement {
  static properties = {
    items: {
      converter: {
        fromAttribute(value) {
          if (!value) return [];
          try { return JSON.parse(value); } catch (_e) { return []; }
        },
        toAttribute(value) { return JSON.stringify(value); },
      },
    },
    labels: {
      converter: {
        fromAttribute(value) {
          if (!value) return {};
          try { return JSON.parse(value); } catch (_e) { return {}; }
        },
        toAttribute(value) { return JSON.stringify(value); },
      },
    },
    _dragId: { type: String, state: true },
    _dropTargetId: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; user-select: none; }
    .tree { list-style: none; margin: 0; padding: 0; }
    .node {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 5px 8px;
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      min-height: 34px;
      transition: background 0.15s ease;
    }
    .node:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .node.dragging { opacity: 0.4; }
    .node.drop-target { outline: 2px dashed var(--builtin-primary, #2563eb); }
    .toggle {
      border: 0;
      background: transparent;
      padding: 2px;
      min-height: 0;
      color: var(--builtin-color-muted, #6b7280);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: var(--builtin-radius, 6px);
    }
    .toggle:hover { background: var(--builtin-row-hover-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .toggle-placeholder { width: 20px; display: inline-block; }
    .checkbox {
      width: 16px;
      height: 16px;
      accent-color: var(--builtin-primary, #2563eb);
      cursor: pointer;
      flex-shrink: 0;
    }
    .label { flex: 1 1 auto; color: var(--builtin-color-text, #111827); }
    .children {
      list-style: none;
      margin: 0;
      padding: 0 0 0 22px;
    }
    @media (max-width: 720px) {
      .node { min-height: 44px; padding: 8px 10px; gap: 10px; }
      .children { padding-left: 14px; }
      .checkbox { width: 20px; height: 20px; }
      .toggle svg { width: 20px; height: 20px; }
    }
  `;

  constructor() {
    super();
    this.items = [];
    this.labels = {};
    this._dragId = null;
    this._dropTargetId = null;
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

  _cloneItems(items) {
    return (items || []).map((n) => ({ ...n, children: n.children ? this._cloneItems(n.children) : [] }));
  }

  _findNode(items, id) {
    for (const node of items || []) {
      if (node.id === id) return node;
      const found = this._findNode(node.children, id);
      if (found) return found;
    }
    return null;
  }

  _findParent(items, id, parent = null) {
    for (const node of items || []) {
      if (node.id === id) return parent;
      const found = this._findParent(node.children, id, node);
      if (found) return found;
    }
    return null;
  }

  _setCheckedCascade(node, checked) {
    node.checked = checked;
    (node.children || []).forEach((c) => this._setCheckedCascade(c, checked));
  }

  _updateParentCheck(parent) {
    if (!parent || !parent.children) return;
    const checked = parent.children.every((c) => c.checked);
    const indeterminate = !checked && parent.children.some((c) => c.checked);
    parent.checked = checked;
    // indeterminate state is not stored, only checked boolean for simplicity
  }

  _onToggle(e, node) {
    e.stopPropagation();
    node.expanded = !node.expanded;
    this.dispatchEvent(new CustomEvent("builtin-toggle", { detail: { id: node.id, expanded: node.expanded }, bubbles: true }));
    this.requestUpdate();
  }

  _onCheck(e, node) {
    e.stopPropagation();
    const checked = e.target.checked;
    this._setCheckedCascade(node, checked);
    const parent = this._findParent(this.items, node.id);
    if (parent) this._updateParentCheck(parent);
    this.dispatchEvent(new CustomEvent("builtin-check", { detail: { id: node.id, checked }, bubbles: true }));
    this.requestUpdate();
  }

  _onSelect(e, node) {
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("builtin-select", { detail: { id: node.id }, bubbles: true }));
  }

  _onDragStart(e, node) {
    this._dragId = node.id;
    e.dataTransfer.effectAllowed = "move";
    if (e.dataTransfer.setData) e.dataTransfer.setData("text/plain", node.id);
  }

  _onDragOver(e, node) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (this._dragId && this._dragId !== node.id) {
      this._dropTargetId = node.id;
    }
  }

  _onDragLeave(_e, _node) {
    this._dropTargetId = null;
  }

  _onDrop(e, targetNode) {
    e.preventDefault();
    const dragId = this._dragId;
    this._dragId = null;
    this._dropTargetId = null;
    if (!dragId || dragId === targetNode.id) return;

    const dragNode = this._findNode(this.items, dragId);
    const dragParent = this._findParent(this.items, dragId);
    const targetParent = this._findParent(this.items, targetNode.id);
    if (!dragNode) return;

    // Simple reorder: move dragNode after targetNode within same parent
    if (dragParent && targetParent && dragParent.id === targetParent.id) {
      const siblings = dragParent.children;
      const fromIndex = siblings.findIndex((n) => n.id === dragId);
      const toIndex = siblings.findIndex((n) => n.id === targetNode.id);
      if (fromIndex !== -1 && toIndex !== -1) {
        siblings.splice(fromIndex, 1);
        const newIndex = toIndex > fromIndex ? toIndex : toIndex + 1;
        siblings.splice(newIndex, 0, dragNode);
        this.dispatchEvent(new CustomEvent("builtin-change", { detail: { items: this.items }, bubbles: true }));
        this.requestUpdate();
      }
    }
  }

  _onDragEnd() {
    this._dragId = null;
    this._dropTargetId = null;
  }

  _renderNode(node) {
    const hasChildren = (node.children || []).length > 0;
    const isDragging = this._dragId === node.id;
    const isDropTarget = this._dropTargetId === node.id;
    const nodeClasses = {
      node: true,
      dragging: isDragging,
      "drop-target": isDropTarget,
    };

    return html`
      <li>
        <div
          class="${classMap(nodeClasses)}"
          draggable="true"
          @click="${(e) => this._onSelect(e, node)}"
          @dragstart="${(e) => this._onDragStart(e, node)}"
          @dragover="${(e) => this._onDragOver(e, node)}"
          @dragleave="${(e) => this._onDragLeave(e, node)}"
          @drop="${(e) => this._onDrop(e, node)}"
          @dragend="${this._onDragEnd}"
        >
          ${hasChildren
            ? html`
                <button
                  class="toggle"
                  aria-label="${node.expanded ? this._t("tree.collapse") : this._t("tree.expand")}"
                  @click="${(e) => this._onToggle(e, node)}"
                >
                  <builtin-icon name="${node.expanded ? 'down' : 'right'}" size="16" variant="outlined"></builtin-icon>
                </button>
              `
            : html`<span class="toggle-placeholder"></span>`}
          <input
            class="checkbox"
            type="checkbox"
            .checked="${!!node.checked}"
            @change="${(e) => this._onCheck(e, node)}"
            aria-label="${this._t("tree.check", { label: node.label })}"
          />
          <span class="label">${node.label}</span>
        </div>
        ${hasChildren && node.expanded
          ? html`<ul class="children">${(node.children || []).map((c) => this._renderNode(c))}</ul>`
          : ""}
      </li>
    `;
  }

  render() {
    const items = this.items || [];
    return html`<ul class="tree" role="tree">${items.map((node) => this._renderNode(node))}</ul>`;
  }
}
