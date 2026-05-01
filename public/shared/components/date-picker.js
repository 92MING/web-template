/**
 * @fileoverview BuiltinDatePicker — Date picker with optional range selection.
 *
 * @attr {string} value — ISO date string (default empty).
 * @attr {boolean} range — Enable start + end selection.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-change — Detail: `{ value }` or `{ start, end }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinDatePicker extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    range: { type: Boolean },
    labels: { type: Object },
    _open: { type: Boolean, state: true },
    _cursor: { type: Date, state: true },
    _start: { type: String, state: true },
    _end: { type: String, state: true },
  };

  static styles = css`
    :host { display: inline-block; position: relative; }
    .input {
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      font-size: 14px;
      outline: none;
    }
    .input:focus { border-color: var(--builtin-primary, #2563eb); box-shadow: 0 0 0 2px var(--builtin-primary-soft, #eff6ff); }
    .popup {
      position: absolute;
      top: calc(100% + 6px);
      left: 0;
      z-index: 1000;
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      box-shadow: 0 8px 24px rgba(0,0,0,0.10);
      padding: 10px;
      min-width: 280px;
      display: none;
    }
    .popup.open { display: block; }
    .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
    .month-label { font-weight: 650; font-size: 14px; color: var(--builtin-color-text, #111827); }
    .nav {
      display: inline-flex; align-items: center; justify-content: center;
      width: 28px; height: 28px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-surface, #ffffff);
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer; color: var(--builtin-color-muted, #6b7280); padding: 0;
    }
    .nav:hover { background: var(--builtin-row-hover-bg, #f9fafb); color: var(--builtin-color-text, #111827); }
    .weekdays { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; margin-bottom: 4px; }
    .weekday { text-align: center; font-size: 11px; font-weight: 600; color: var(--builtin-color-muted, #6b7280); padding: 4px 0; }
    .days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
    .day {
      display: flex; align-items: center; justify-content: center;
      height: 32px; border-radius: var(--builtin-radius, 6px);
      cursor: pointer; font-size: 13px; color: var(--builtin-color-text, #111827);
      background: transparent; border: none; width: 100%;
    }
    .day:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .day.other { color: var(--builtin-color-muted, #9ca3af); }
    .day.today { font-weight: 700; color: var(--builtin-primary, #2563eb); }
    .day.selected { background: var(--builtin-primary, #2563eb); color: #fff; }
    .day.in-range { background: var(--builtin-primary-soft, #eff6ff); }
    .day.range-start { border-top-right-radius: 0; border-bottom-right-radius: 0; }
    .day.range-end { border-top-left-radius: 0; border-bottom-left-radius: 0; }
    .footer { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .btn-text { padding: 4px 8px; border: none; background: transparent; cursor: pointer; font-size: 12px; color: var(--builtin-primary, #2563eb); border-radius: var(--builtin-radius, 6px); }
    .btn-text:hover { background: var(--builtin-primary-soft, #eff6ff); }
    .mobile-overlay {
      display: none; position: fixed; inset: 0; z-index: 9999;
      background: rgba(0,0,0,0.35); align-items: center; justify-content: center; padding: 16px;
    }
    .mobile-overlay.open { display: flex; }
    .mobile-sheet {
      background: var(--builtin-surface, #ffffff);
      border-radius: var(--builtin-radius-lg, 8px);
      width: 100%; max-width: 360px; max-height: 80vh; overflow: auto;
      padding: 12px;
    }
    @media (max-width: 720px) {
      .popup { display: none !important; }
      .input { font-size: 16px; padding: 10px; }
    }
  `;

  constructor() {
    super();
    this.value = "";
    this.range = false;
    this._open = false;
    this._cursor = new Date();
    this._start = "";
    this._end = "";
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.value) {
      const d = new Date(this.value);
      if (!isNaN(d)) this._cursor = d;
    }
    document.addEventListener("click", this._onDocumentClick);
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _startOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  _addDays(date, days) {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d;
  }

  _sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  _toISODate(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  _fmtMonthYear(d) {
    return d.toLocaleDateString(this._ptLang, { year: "numeric", month: "long" });
  }

  _openPopup() {
    this._open = true;
  }

  _closePopup() {
    this._open = false;
  }

  _onDayClick(day) {
    const iso = this._toISODate(day);
    if (!this.range) {
      this.value = iso;
      this._open = false;
      this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: iso }, bubbles: true }));
      return;
    }
    if (!this._start || (this._start && this._end)) {
      this._start = iso;
      this._end = "";
    } else if (this._start && !this._end) {
      if (iso < this._start) {
        this._end = this._start;
        this._start = iso;
      } else {
        this._end = iso;
      }
      this.value = `${this._start} to ${this._end}`;
      this._open = false;
      this.dispatchEvent(new CustomEvent("builtin-change", { detail: { start: this._start, end: this._end }, bubbles: true }));
    }
  }

  _navigate(delta) {
    const d = new Date(this._cursor);
    d.setMonth(d.getMonth() + delta);
    this._cursor = d;
  }

  _goToday() {
    const today = new Date();
    this._cursor = today;
    const iso = this._toISODate(today);
    if (!this.range) {
      this.value = iso;
      this._open = false;
      this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: iso }, bubbles: true }));
    } else {
      this._start = iso;
      this._end = "";
    }
  }

  _clear() {
    this.value = "";
    this._start = "";
    this._end = "";
    this._open = false;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: this.range ? { start: "", end: "" } : { value: "" }, bubbles: true }));
  }

  _onDocumentClick = (e) => {
    if (!this._open) return;
    if (!this.contains(e.target) && !this.shadowRoot.contains(e.target)) {
      this._closePopup();
    }
  };

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("click", this._onDocumentClick);
  }

  _renderCalendar() {
    const start = this._startOfMonth(this._cursor);
    const weekStart = this._addDays(start, -start.getDay());
    const days = [];
    for (let i = 0; i < 42; i++) days.push(this._addDays(weekStart, i));
    const weekdays = this._l("weekdays", "Sun,Mon,Tue,Wed,Thu,Fri,Sat").split(",");
    const today = new Date();

    return html`
      <div class="header">
        <button class="nav" @click=${() => this._navigate(-1)} aria-label="${this._l("prev", "Previous")}">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <div class="month-label">${this._fmtMonthYear(this._cursor)}</div>
        <button class="nav" @click=${() => this._navigate(1)} aria-label="${this._l("next", "Next")}">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
        </button>
      </div>
      <div class="weekdays">
        ${weekdays.map((w) => html`<div class="weekday">${w}</div>`)}
      </div>
      <div class="days">
        ${days.map((day) => {
          const iso = this._toISODate(day);
          const isOther = day.getMonth() !== this._cursor.getMonth();
          const isToday = this._sameDay(day, today);
          const isSelected = !this.range ? iso === this.value : iso === this._start || iso === this._end;
          const inRange = this.range && this._start && this._end && iso > this._start && iso < this._end;
          const isStart = this.range && iso === this._start;
          const isEnd = this.range && iso === this._end;
          return html`
            <button
              class="day ${isOther ? "other" : ""} ${isToday ? "today" : ""} ${isSelected ? "selected" : ""} ${inRange ? "in-range" : ""} ${isStart ? "range-start" : ""} ${isEnd ? "range-end" : ""}"
              @click=${() => this._onDayClick(day)}
            >
              ${day.getDate()}
            </button>
          `;
        })}
      </div>
      <div class="footer">
        <button class="btn-text" @click=${this._clear}>${this._l("clear", "Clear")}</button>
        <button class="btn-text" @click=${this._goToday}>${this._l("today", "Today")}</button>
      </div>
    `;
  }

  _displayValue() {
    if (this.range) {
      if (this._start && this._end) return `${this._start} – ${this._end}`;
      if (this._start) return `${this._start} – ...`;
      return this.value || "";
    }
    return this.value || "";
  }

  render() {
    const placeholder = this.range ? this._l("selectRange", "Select range") : this._l("selectDate", "Select date");
    return html`
      <input
        class="input"
        type="text"
        .value=${this._displayValue()}
        placeholder="${placeholder}"
        readonly
        @focus=${this._openPopup}
        @click=${this._openPopup}
      />
      ${!this._ptMobile
        ? html`<div class="popup ${classMap({ open: this._open })}">${this._renderCalendar()}</div>`
        : html`
            <div class="mobile-overlay ${classMap({ open: this._open })}" @click=${(e) => { if (e.target === e.currentTarget) this._closePopup(); }}>
              <div class="mobile-sheet">
                ${this._renderCalendar()}
              </div>
            </div>
          `}
    `;
  }
}
