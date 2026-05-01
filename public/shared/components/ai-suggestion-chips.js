import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinAiSuggestionChips — horizontally scrollable suggestion pills.
 *
 * @element builtin-ai-suggestion-chips
 *
 * @attr {string} suggestions — JSON array [{label, icon}]
 * @attr {string} labels — JSON map for i18n overrides.
 *
 * @event builtin-select — Chip clicked. detail: {label, icon}
 */
export class BuiltinAiSuggestionChips extends BuiltinBaseElement {
  static properties = {
    suggestions: {
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
  };

  static styles = css`
    :host { display: block; }
    .scroll {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      padding: 4px 2px;
      scrollbar-width: thin;
      scrollbar-color: var(--builtin-border, #d1d5db) transparent;
    }
    .scroll::-webkit-scrollbar { height: 6px; }
    .scroll::-webkit-scrollbar-thumb { background: var(--builtin-border, #d1d5db); border-radius: 3px; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 9999px;
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      padding: 8px 16px;
      cursor: pointer;
      font-size: 14px;
      transition: background 0.15s ease, border-color 0.15s ease;
      user-select: none;
    }
    .chip:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
      border-color: var(--builtin-primary, #2563eb);
    }
    .chip:active { transform: translateY(1px); }
    .chip svg { width: 16px; height: 16px; flex-shrink: 0; color: var(--builtin-color-muted, #6b7280); }
    @media (max-width: 720px) {
      .scroll {
        gap: 10px;
        scroll-snap-type: x mandatory;
        padding: 6px 2px;
      }
      .chip {
        scroll-snap-align: start;
        padding: 10px 18px;
        font-size: 16px;
        min-height: 44px;
      }
      .chip svg { width: 18px; height: 18px; }
    }
  `;

  constructor() {
    super();
    this.suggestions = [];
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

  _onSelect(item) {
    this.dispatchEvent(new CustomEvent("builtin-select", { detail: { label: item.label, icon: item.icon }, bubbles: true }));
  }

  _iconSvg(name) {
    // Small inline icon map for common suggestion icons
    const map = {
      "sparkle": html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.287 1.288L3 12l5.8 1.9a2 2 0 0 1 1.288 1.287L12 21l1.9-5.8a2 2 0 0 1 1.287-1.288L21 12l-5.8-1.9a2 2 0 0 1-1.288-1.287Z"/></svg>`,
      "message": html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
      "zap": html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
      "code": html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`,
      "send": html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`,
      "help": html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    };
    return map[name] || "";
  }

  render() {
    const items = this.suggestions || [];
    return html`
      <div class="scroll" role="list" aria-label="${this._t("chips.label")}">
        ${repeat(items, (s, i) => i, (s) => html`
          <button class="chip" role="listitem" @click="${() => this._onSelect(s)}" aria-label="${s.label}">
            ${s.icon ? this._iconSvg(s.icon) : ""}
            <span>${s.label}</span>
          </button>
        `)}
      </div>
    `;
  }
}
