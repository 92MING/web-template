import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinTimeline - Vertical timeline web component.
 *
 * Attributes:
 * - `items` (JSON array of {time, title, description, dotColor})
 * - `align` (`left` | `right` | `alternate`). Default `left`.
 * - `empty-text` (string): Empty state text override.
 * - `labels` (JSON object for local i18n overrides)
 *
 * Slots:
 * - `item-N`: rendered inside the Nth timeline item.
 */
export class BuiltinTimeline extends BuiltinBaseElement {
  static get properties() {
    return {
      items: {
        converter: {
          fromAttribute(value) {
            if (!value) return [];
            try {
              return JSON.parse(value);
            } catch (_e) {
              return [];
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
      align: { type: String },
      emptyText: { type: String, attribute: "empty-text" },
      labels: {
        converter: {
          fromAttribute(value) {
            if (!value) return {};
            try {
              return JSON.parse(value);
            } catch (_e) {
              return {};
            }
          },
          toAttribute(value) {
            return JSON.stringify(value);
          },
        },
      },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .timeline {
        position: relative;
        padding-left: 24px;
      }
      .timeline::before {
        content: "";
        position: absolute;
        left: 7px;
        top: 6px;
        bottom: 6px;
        width: 2px;
        background: var(--builtin-border-soft, #e5e7eb);
      }
      .timeline-item {
        position: relative;
        padding-bottom: 20px;
      }
      .timeline-item:last-child {
        padding-bottom: 0;
      }
      .timeline-dot {
        position: absolute;
        left: -17px;
        top: 2px;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: var(--builtin-primary, #2563eb);
        border: 2px solid var(--builtin-surface, #ffffff);
        box-shadow: 0 0 0 1px var(--builtin-border-soft, #e5e7eb);
      }
      .timeline-time {
        font-size: 12px;
        color: var(--builtin-color-muted, #6b7280);
        margin-bottom: 2px;
      }
      .timeline-title {
        font-weight: 650;
        font-size: 14px;
        color: var(--builtin-color-text, #111827);
      }
      .timeline-desc {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
        margin-top: 4px;
        line-height: 1.45;
      }
      .slot-wrap {
        margin-top: 6px;
      }
      .empty {
        font-size: 13px;
        color: var(--builtin-color-muted, #6b7280);
        padding: 12px 0;
      }

      /* align right */
      :host([align="right"]) .timeline {
        padding-left: 0;
        padding-right: 24px;
        text-align: right;
      }
      :host([align="right"]) .timeline::before {
        left: auto;
        right: 7px;
      }
      :host([align="right"]) .timeline-dot {
        left: auto;
        right: -17px;
      }

      /* alternate */
      :host([align="alternate"]) .timeline {
        padding-left: 0;
      }
      :host([align="alternate"]) .timeline::before {
        left: 50%;
        margin-left: -1px;
      }
      :host([align="alternate"]) .timeline-item {
        width: 50%;
        position: relative;
        padding-bottom: 20px;
      }
      :host([align="alternate"]) .timeline-item:nth-child(odd) {
        padding-right: 24px;
        text-align: right;
      }
      :host([align="alternate"]) .timeline-item:nth-child(odd) .timeline-dot {
        right: -6px;
        left: auto;
      }
      :host([align="alternate"]) .timeline-item:nth-child(even) {
        margin-left: 50%;
        padding-left: 24px;
        text-align: left;
      }
      :host([align="alternate"]) .timeline-item:nth-child(even) .timeline-dot {
        left: -6px;
      }

      @media (max-width: 720px) {
        .timeline {
          padding-left: 20px !important;
          padding-right: 0 !important;
          text-align: left !important;
        }
        .timeline::before {
          left: 7px !important;
          right: auto !important;
          margin-left: 0 !important;
        }
        .timeline-item {
          width: 100% !important;
          margin-left: 0 !important;
          padding-left: 0 !important;
          padding-right: 0 !important;
          text-align: left !important;
        }
        .timeline-dot {
          left: -15px !important;
          right: auto !important;
          width: 10px;
          height: 10px;
        }
        .timeline-title {
          font-size: 13px;
        }
        .timeline-desc {
          font-size: 12px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.items = [];
    this.align = "left";
    this.emptyText = "";
    this.labels = {};
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = this.labels[key];
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name)
            ? String(values[name])
            : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  _itemSlotName(index) {
    return `item-${index}`;
  }

  render() {
    const items = Array.isArray(this.items) ? this.items : [];
    const rootClasses = { mobile: this._ptMobile };
    return html`
      <div class="timeline ${classMap(rootClasses)}" data-theme="${this._ptTheme}">
        ${repeat(
          items,
          (_item, i) => i,
          (item, index) => html`
            <div class="timeline-item">
              <div
                class="timeline-dot"
                style=${styleMap({
                  background: item.dotColor || "var(--builtin-primary, #2563eb)",
                })}
              ></div>
              ${item.time
                ? html`<div class="timeline-time">${item.time}</div>`
                : ""}
              ${item.title
                ? html`<div class="timeline-title">${item.title}</div>`
                : ""}
              ${item.description
                ? html`<div class="timeline-desc">${item.description}</div>`
                : ""}
              <div class="slot-wrap">
                <slot name="${this._itemSlotName(index)}">${item.content || ""}</slot>
              </div>
            </div>
          `
        )}
        ${items.length === 0
          ? html`<div class="empty">${this.emptyText || this._t("timeline.empty")}</div>`
          : ""}
      </div>
    `;
  }
}
