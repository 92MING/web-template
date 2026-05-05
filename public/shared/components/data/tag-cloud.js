/**
 * @fileoverview BuiltinTagCloud - Weighted tag cloud component.
 *
 * @attr {Array} tags - JSON array of strings or {text, value, weight, color, href}.
 * @attr {number} min-size - Minimum font size in px.
 * @attr {number} max-size - Maximum font size in px.
 * @attr {boolean} selectable - Allow selecting tags.
 * @attr {boolean} multiple - Allow multiple selected tags.
 * @attr {Array} selected - Selected tag values.
 *
 * @event builtin-tag-select - Detail: { value, tag, selected }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

const TAG_COLORS = [
  "#2563eb",
  "#16a34a",
  "#d97706",
  "#dc2626",
  "#7c3aed",
  "#0891b2",
  "#be123c",
  "#4f46e5",
];

export class BuiltinTagCloud extends BuiltinBaseElement {
  static properties = {
    tags: { type: Array },
    minSize: { type: Number, attribute: "min-size" },
    maxSize: { type: Number, attribute: "max-size" },
    selectable: { type: Boolean },
    multiple: { type: Boolean },
    selected: { type: Array },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .cloud {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 10px;
      padding: 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      min-height: 96px;
    }
    .tag {
      appearance: none;
      border: 1px solid transparent;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      max-width: 100%;
      padding: 5px 10px;
      background: color-mix(in srgb, var(--tag-color) 12%, var(--builtin-surface, #ffffff));
      color: var(--tag-color);
      font-weight: 650;
      line-height: 1.1;
      text-decoration: none;
      cursor: default;
      transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
    }
    .tag.selectable,
    a.tag {
      cursor: pointer;
    }
    .tag.selectable:hover,
    a.tag:hover {
      transform: translateY(-1px);
      border-color: color-mix(in srgb, var(--tag-color) 42%, transparent);
      background: color-mix(in srgb, var(--tag-color) 18%, var(--builtin-surface, #ffffff));
    }
    .tag.selected {
      color: #fff;
      background: var(--tag-color);
      border-color: var(--tag-color);
    }
    .label {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .count {
      font-size: 0.72em;
      opacity: 0.72;
    }
    .empty {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      padding: 18px 0;
      text-align: center;
      width: 100%;
    }
    @media (max-width: 720px) {
      .cloud { gap: 7px; padding: 10px; }
      .tag { max-width: 100%; }
    }
  `;

  constructor() {
    super();
    this.tags = [];
    this.minSize = 12;
    this.maxSize = 28;
    this.selectable = false;
    this.multiple = false;
    this.selected = [];
    this.labels = {};
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _items() {
    return (this.tags || []).map((tag, index) => {
      if (typeof tag === "string") {
        return { text: tag, value: tag, weight: 1, index };
      }
      const text = String(tag.text ?? tag.label ?? tag.value ?? "");
      return {
        ...tag,
        text,
        value: String(tag.value ?? text),
        weight: Number(tag.weight ?? tag.count ?? tag.valueWeight ?? 1) || 1,
        index,
      };
    }).filter((tag) => tag.text);
  }

  _selectedSet() {
    return new Set((this.selected || []).map((value) => String(value)));
  }

  _fontSize(tag, minWeight, maxWeight) {
    const minSize = Number(this.minSize) || 12;
    const maxSize = Math.max(minSize, Number(this.maxSize) || 28);
    if (maxWeight <= minWeight) return (minSize + maxSize) / 2;
    const ratio = (tag.weight - minWeight) / (maxWeight - minWeight);
    return Math.round((minSize + (maxSize - minSize) * ratio) * 10) / 10;
  }

  _color(tag) {
    return tag.color || TAG_COLORS[tag.index % TAG_COLORS.length];
  }

  _toggle(tag) {
    if (!this.selectable) return;
    const selected = this._selectedSet();
    if (selected.has(tag.value)) {
      selected.delete(tag.value);
    } else if (this.multiple) {
      selected.add(tag.value);
    } else {
      selected.clear();
      selected.add(tag.value);
    }
    this.selected = [...selected];
    this.dispatchEvent(new CustomEvent("builtin-tag-select", {
      bubbles: true,
      composed: true,
      detail: { value: tag.value, tag, selected: this.selected },
    }));
  }

  _onKeydown(e, tag) {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    this._toggle(tag);
  }

  _renderTag(tag, minWeight, maxWeight, selectedSet) {
    const isSelected = selectedSet.has(tag.value);
    const content = html`
      <span class="label">${tag.text}</span>
      ${tag.count !== undefined || tag.weight !== 1 ? html`<span class="count">${tag.count ?? tag.weight}</span>` : null}
    `;
    const classes = classMap({
      tag: true,
      selectable: this.selectable,
      selected: isSelected,
    });
    const style = styleMap({
      "--tag-color": this._color(tag),
      fontSize: `${this._fontSize(tag, minWeight, maxWeight)}px`,
    });

    if (tag.href) {
      return html`<a class="${classes}" href="${tag.href}" style="${style}">${content}</a>`;
    }
    return html`
      <button
        type="button"
        class="${classes}"
        style="${style}"
        aria-pressed="${this.selectable ? String(isSelected) : "false"}"
        tabindex="${this.selectable ? "0" : "-1"}"
        @click="${() => this._toggle(tag)}"
        @keydown="${(e) => this._onKeydown(e, tag)}"
      >${content}</button>
    `;
  }

  render() {
    const items = this._items();
    const weights = items.map((tag) => tag.weight);
    const minWeight = Math.min(...weights, 1);
    const maxWeight = Math.max(...weights, 1);
    const selected = this._selectedSet();

    return html`
      <div class="cloud">
        ${items.length
          ? repeat(
            items,
            (tag) => tag.value,
            (tag) => this._renderTag(tag, minWeight, maxWeight, selected),
          )
          : html`<div class="empty">${this._l("tagCloud.empty", "No tags.")}</div>`}
      </div>
    `;
  }
}
