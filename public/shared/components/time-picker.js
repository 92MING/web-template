/**
 * @fileoverview BuiltinTimePicker — Scrollable time picker with 12h/24h support.
 *
 * @attr {string} value — "HH:MM" or "HH:MM:SS".
 * @attr {string} format — `12h` | `24h` (default `24h`).
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-change — Detail: `{ value }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinTimePicker extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    format: { type: String },
    labels: { type: Object },
    _hour: { type: Number, state: true },
    _minute: { type: Number, state: true },
    _second: { type: Number, state: true },
    _ampm: { type: String, state: true },
  };

  static styles = css`
    :host { display: inline-block; }
    .picker {
      display: inline-flex;
      align-items: stretch;
      gap: 8px;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 10px;
    }
    .column {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
    }
    .label {
      font-size: 11px;
      font-weight: 600;
      color: var(--builtin-color-muted, #6b7280);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .scroll {
      display: flex;
      flex-direction: column;
      gap: 2px;
      max-height: 180px;
      overflow-y: auto;
      padding: 2px;
    }
    .item {
      display: flex;
      align-items: center;
      justify-content: center;
      min-width: 44px;
      height: 32px;
      border-radius: var(--builtin-radius, 6px);
      border: none;
      background: transparent;
      cursor: pointer;
      font-size: 14px;
      color: var(--builtin-color-text, #111827);
      padding: 0 8px;
    }
    .item:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .item.active { background: var(--builtin-primary, #2563eb); color: #fff; }
    .divider {
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      font-weight: 700;
      color: var(--builtin-color-muted, #6b7280);
      padding-top: 18px;
    }
    .ampm {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding-top: 18px;
    }
    .ampm-btn {
      min-width: 44px;
      height: 32px;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      font-size: 13px;
      color: var(--builtin-color-text, #111827);
    }
    .ampm-btn.active { background: var(--builtin-primary, #2563eb); color: #fff; border-color: var(--builtin-primary, #2563eb); }
    @media (max-width: 720px) {
      .picker { padding: 12px; gap: 12px; }
      .item { min-width: 56px; height: 44px; font-size: 16px; }
      .ampm-btn { min-width: 56px; height: 44px; font-size: 15px; }
      .scroll { max-height: 220px; }
      .divider { padding-top: 22px; }
      .ampm { padding-top: 22px; }
    }
  `;

  constructor() {
    super();
    this.value = "";
    this.format = "24h";
    this._hour = 0;
    this._minute = 0;
    this._second = 0;
    this._ampm = "AM";
  }

  connectedCallback() {
    super.connectedCallback();
    this._parseValue(this.value);
  }

  willUpdate(changed) {
    if (changed.has("value")) {
      this._parseValue(this.value);
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _parseValue(v) {
    if (!v) {
      this._hour = 0;
      this._minute = 0;
      this._second = 0;
      this._ampm = "AM";
      return;
    }
    const parts = v.split(":");
    let h = parseInt(parts[0] || "0", 10);
    const m = parseInt(parts[1] || "0", 10);
    const s = parseInt(parts[2] || "0", 10);
    if (this.format === "12h") {
      this._ampm = h >= 12 ? "PM" : "AM";
      h = h % 12 || 12;
    }
    this._hour = h;
    this._minute = m;
    this._second = s;
  }

  _emit() {
    let h = this._hour;
    if (this.format === "12h") {
      if (this._ampm === "PM" && h !== 12) h += 12;
      if (this._ampm === "AM" && h === 12) h = 0;
    }
    const hasSeconds = this.value && this.value.split(":").length === 3;
    const hh = String(h).padStart(2, "0");
    const mm = String(this._minute).padStart(2, "0");
    const ss = String(this._second).padStart(2, "0");
    const value = hasSeconds ? `${hh}:${mm}:${ss}` : `${hh}:${mm}`;
    this.value = value;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value }, bubbles: true }));
  }

  _setHour(h) {
    this._hour = h;
    this._emit();
  }

  _setMinute(m) {
    this._minute = m;
    this._emit();
  }

  _setSecond(s) {
    this._second = s;
    this._emit();
  }

  _setAmPm(a) {
    this._ampm = a;
    this._emit();
  }

  _hourList() {
    if (this.format === "12h") {
      return Array.from({ length: 12 }, (_, i) => i + 1);
    }
    return Array.from({ length: 24 }, (_, i) => i);
  }

  _minuteList() {
    return Array.from({ length: 60 }, (_, i) => i);
  }

  _secondList() {
    return Array.from({ length: 60 }, (_, i) => i);
  }

  render() {
    const hasSeconds = this.value && this.value.split(":").length === 3;
    return html`
      <div class="picker">
        <div class="column">
          <div class="label">${this._l("hour", "Hour")}</div>
          <div class="scroll">
            ${this._hourList().map(
              (h) => html`
                <button class="item ${classMap({ active: this._hour === h })}" @click=${() => this._setHour(h)}>
                  ${String(h).padStart(2, "0")}
                </button>
              `
            )}
          </div>
        </div>
        <div class="divider">:</div>
        <div class="column">
          <div class="label">${this._l("minute", "Min")}</div>
          <div class="scroll">
            ${this._minuteList().map(
              (m) => html`
                <button class="item ${classMap({ active: this._minute === m })}" @click=${() => this._setMinute(m)}>
                  ${String(m).padStart(2, "0")}
                </button>
              `
            )}
          </div>
        </div>
        ${hasSeconds
          ? html`
              <div class="divider">:</div>
              <div class="column">
                <div class="label">${this._l("second", "Sec")}</div>
                <div class="scroll">
                  ${this._secondList().map(
                    (s) => html`
                      <button class="item ${classMap({ active: this._second === s })}" @click=${() => this._setSecond(s)}>
                        ${String(s).padStart(2, "0")}
                      </button>
                    `
                  )}
                </div>
              </div>
            `
          : null}
        ${this.format === "12h"
          ? html`
              <div class="ampm">
                <button class="ampm-btn ${classMap({ active: this._ampm === "AM" })}" @click=${() => this._setAmPm("AM")}>AM</button>
                <button class="ampm-btn ${classMap({ active: this._ampm === "PM" })}" @click=${() => this._setAmPm("PM")}>PM</button>
              </div>
            `
          : null}
      </div>
    `;
  }
}
