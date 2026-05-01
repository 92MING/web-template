/**
 * @fileoverview BuiltinTabs - Tabbed interface supporting pills, underline and vertical orientations (Lit).
 *
 * Slots:
 *   - (default): Tab panels identified by data-tab="value"
 *
 * Attributes:
 *   - type ("pills" | "underline" | "vertical"): Tab style (default "underline").
 *   - items: JSON array of { label, value } objects for tab buttons.
 *   - active: Value of the currently active tab.
 *
 * Events:
 *   - builtin-tab-change: Fired when the active tab changes. Detail: { value }
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinTabs extends BuiltinBaseElement {
  static properties = {
    type: { type: String },
    items: { type: Array },
    active: { type: String },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      display: flex;
      flex-direction: column;
    }
    .tabs {
      display: flex;
      background: var(--builtin-header-bg, #f9fafb);
      overflow: auto;
      scrollbar-width: none;
    }
    .tabs::-webkit-scrollbar { display: none; }
    .tab-btn {
      background: transparent;
      border: none;
      border-radius: 0;
      padding: 10px 14px;
      white-space: nowrap;
      cursor: pointer;
      color: var(--builtin-color-muted, #6b7280);
      font-weight: 500;
      min-height: auto;
    }
    .tab-btn:hover { color: var(--builtin-color-text, #111827); }
    .panels { padding: 12px; }
    ::slotted([data-tab][hidden]) { display: none !important; }
    .panel-content { animation: builtin-tab-fade-in 0.2s ease; }
    @keyframes builtin-tab-fade-in {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* underline */
    .tabs.underline {
      border-bottom: 1px solid var(--builtin-border, #d1d5db);
    }
    .tabs.underline .tab-btn {
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
    }
    .tabs.underline .tab-btn.active {
      color: var(--builtin-primary, #2563eb);
      border-bottom-color: var(--builtin-primary, #2563eb);
      background: var(--builtin-surface, #ffffff);
    }

    /* pills */
    .tabs.pills {
      gap: 4px;
      padding: 4px;
      border-bottom: none;
    }
    .tabs.pills .tab-btn {
      border-radius: var(--builtin-radius, 6px);
    }
    .tabs.pills .tab-btn.active {
      color: var(--builtin-primary, #2563eb);
      background: rgba(37, 99, 235, 0.08);
    }

    /* vertical */
    .tabs.vertical {
      flex-direction: column;
      border-bottom: none;
      border-right: 1px solid var(--builtin-border, #d1d5db);
      min-width: 160px;
    }
    .tabs.vertical .tab-btn {
      text-align: left;
      border-right: 2px solid transparent;
      margin-right: -1px;
    }
    .tabs.vertical .tab-btn.active {
      color: var(--builtin-primary, #2563eb);
      border-right-color: var(--builtin-primary, #2563eb);
      background: var(--builtin-surface, #ffffff);
    }
    .wrap.vertical {
      flex-direction: row;
    }

    @media (max-width: 720px) {
      .wrap, .wrap.vertical { flex-direction: column; }
      .tabs, .tabs.vertical {
        flex-direction: row;
        border-right: none;
        border-bottom: 1px solid var(--builtin-border, #d1d5db);
        min-width: auto;
      }
      .tab-btn {
        border-right: none !important;
        margin-right: 0 !important;
      }
      .tabs.underline .tab-btn, .tabs.vertical .tab-btn {
        border-bottom: 2px solid transparent;
        margin-bottom: -1px;
      }
      .tabs.underline .tab-btn.active, .tabs.vertical .tab-btn.active {
        border-right-color: transparent !important;
        border-bottom-color: var(--builtin-primary, #2563eb);
      }
    }
  `;

  constructor() {
    super();
    this.type = "underline";
    this.items = [];
    this.active = "";
    this.labels = {};
  }

  _onTabClick = (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    const value = btn.dataset.value;
    if (value === this.active) return;
    this.active = value;
    this.dispatchEvent(new CustomEvent("builtin-tab-change", {
      bubbles: true,
      composed: true,
      detail: { value },
    }));
  };

  render() {
    const items = this.items || [];
    const panels = Array.from(this.querySelectorAll("[data-tab]"));
    const values = items.length ? items.map((i) => i.value) : panels.map((p) => p.dataset.tab);
    let active = this.active || "";
    if (!values.includes(active)) {
      active = values[0] || "";
    }
    for (const panel of panels) {
      panel.hidden = panel.dataset.tab !== active;
    }

    const type = this.type || "underline";
    const wrapClass = { wrap: true, vertical: type === "vertical" };
    const tabsClass = { tabs: true, [type]: true };

    return html`
      <div class="${classMap(wrapClass)}" @click="${this._onTabClick}">
        <div class="${classMap(tabsClass)}">
          ${values.map((v, idx) => {
            const label = items.length ? (items[idx]?.label || v) : v;
            const isActive = v === active;
            return html`
              <button class="${classMap({ "tab-btn": true, active: isActive })}" data-value="${v}">
                ${label}
              </button>
            `;
          })}
        </div>
        <div class="panels">
          <div class="panel-content"><slot></slot></div>
        </div>
      </div>
    `;
  }
}
