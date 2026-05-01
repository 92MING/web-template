/**
 * @fileoverview BuiltinCalendar — Calendar component with month/week/day views.
 *
 * @attr {string} view — `month` | `week` | `day` (default `month`).
 * @attr {string} events — JSON array `[{title, start, end, color, allDay}]`.
 * @attr {string} current-date — ISO date string (default today).
 * @attr {string} mode — `default` | `compact` | `embedded` (default `default`).
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-date-click — Clicked a date cell.
 * @event builtin-event-click — Clicked an event chip.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinCalendar extends BuiltinBaseElement {
  static properties = {
    view: { type: String },
    events: { type: Array },
    currentDate: { type: String, attribute: "current-date" },
    mode: { type: String },
    labels: { type: Object },
    _cursor: { type: Date, state: true },
  };

  static styles = css`
    :host { display: block; }
    .cal { background: var(--builtin-surface, #ffffff); border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; }
    .cal.compact { font-size: 12px; }
    .cal.embedded { border: none; border-radius: 0; }
    .header { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); flex-wrap: wrap; }
    .title { font-weight: 650; font-size: 16px; color: var(--builtin-color-text, #111827); }
    .actions { display: inline-flex; align-items: center; gap: 6px; }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 10px; border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-surface, #ffffff); border-radius: var(--builtin-radius, 6px); cursor: pointer; color: var(--builtin-color-text, #111827); min-height: 32px; }
    .btn:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .btn.primary { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .btn.primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .grid { display: grid; grid-template-columns: repeat(7, 1fr); }
    .cell { min-height: 96px; border-right: 1px solid var(--builtin-border-soft, #e5e7eb); border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); padding: 6px; cursor: pointer; background: var(--builtin-surface, #ffffff); }
    .cell:nth-child(7n) { border-right: none; }
    .cell:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .cell.other { color: var(--builtin-color-muted, #9ca3af); background: var(--builtin-header-bg, #f9fafb); }
    .cell.today { background: var(--builtin-primary-soft, #eff6ff); }
    .day-num { font-weight: 600; font-size: 12px; margin-bottom: 4px; }
    .event { font-size: 11px; padding: 2px 6px; border-radius: var(--builtin-radius, 6px); margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
    .weekdays { display: grid; grid-template-columns: repeat(7, 1fr); background: var(--builtin-header-bg, #f9fafb); border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .weekday { padding: 8px; text-align: center; font-weight: 600; font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .week-grid { display: grid; grid-template-columns: 50px repeat(7, 1fr); }
    .time-label { padding: 4px 6px; text-align: right; font-size: 11px; color: var(--builtin-color-muted, #6b7280); border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); border-right: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .week-cell { min-height: 48px; border-right: 1px solid var(--builtin-border-soft, #e5e7eb); border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); padding: 4px; cursor: pointer; }
    .day-view { padding: 10px; }
    .day-hour { display: flex; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); min-height: 56px; }
    .day-hour-label { width: 50px; padding: 6px; text-align: right; font-size: 11px; color: var(--builtin-color-muted, #6b7280); border-right: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .day-hour-cell { flex: 1; padding: 4px 6px; cursor: pointer; }
    .day-hour-cell:hover { background: var(--builtin-row-hover-bg, #f9fafb); }
    .mobile-list { padding: 10px; }
    .mobile-day { margin-bottom: 12px; }
    .mobile-day-title { font-weight: 650; margin-bottom: 6px; color: var(--builtin-color-text, #111827); }
    .mobile-event { padding: 8px; border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px); margin-bottom: 6px; background: var(--builtin-surface, #ffffff); }
    .slot-area { padding: 8px 12px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); }
    @media (max-width: 720px) {
      .header { padding: 8px; }
      .title { font-size: 14px; }
      .btn { padding: 6px 8px; font-size: 12px; }
      .week-grid { grid-template-columns: 36px repeat(7, 1fr); }
      .time-label { font-size: 10px; }
    }
  `;

  constructor() {
    super();
    this.view = "month";
    this.events = [];
    this.mode = "default";
    this._cursor = new Date();
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.currentDate) {
      const d = new Date(this.currentDate);
      if (!isNaN(d)) this._cursor = d;
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _startOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  _endOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth() + 1, 0);
  }

  _addDays(date, days) {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d;
  }

  _sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  _fmtMonthYear(d) {
    return d.toLocaleDateString(this._ptLang, { year: "numeric", month: "long" });
  }

  _eventsForDay(day) {
    return (this.events || []).filter((ev) => {
      const s = new Date(ev.start);
      return this._sameDay(s, day);
    });
  }

  _onDateClick(day) {
    this.dispatchEvent(new CustomEvent("builtin-date-click", { detail: { date: day.toISOString(), day }, bubbles: true }));
  }

  _onEventClick(ev, day) {
    this.dispatchEvent(new CustomEvent("builtin-event-click", { detail: { event: ev, date: day.toISOString() }, bubbles: true }));
  }

  _navigate(delta) {
    const d = new Date(this._cursor);
    if (this.view === "month") d.setMonth(d.getMonth() + delta);
    else if (this.view === "week") d.setDate(d.getDate() + delta * 7);
    else d.setDate(d.getDate() + delta);
    this._cursor = d;
  }

  _goToday() {
    this._cursor = new Date();
  }

  _weekStart(d) {
    const day = d.getDay();
    return this._addDays(d, -day);
  }

  _renderMonth() {
    const start = this._startOfMonth(this._cursor);
    const startWeek = this._weekStart(start);
    const days = [];
    for (let i = 0; i < 42; i++) days.push(this._addDays(startWeek, i));
    const weekdays = this._l("weekdays", "Sun,Mon,Tue,Wed,Thu,Fri,Sat").split(",");

    return html`
      <div class="weekdays">
        ${weekdays.map((w) => html`<div class="weekday">${w}</div>`)}
      </div>
      <div class="grid">
        ${days.map((day) => {
          const isOther = day.getMonth() !== this._cursor.getMonth();
          const isToday = this._sameDay(day, new Date());
          const evs = this._eventsForDay(day);
          return html`
            <div class="cell ${isOther ? "other" : ""} ${isToday ? "today" : ""}" @click=${() => this._onDateClick(day)}>
              <div class="day-num">${day.getDate()}</div>
              ${evs.map((ev) => html`
                <div class="event" style="background:${ev.color || "var(--builtin-primary-soft, #eff6ff)"};color:${ev.color ? "#fff" : "var(--builtin-primary, #2563eb)"};"
                  @click=${(e) => { e.stopPropagation(); this._onEventClick(ev, day); }}>
                  ${ev.title}
                </div>
              `)}
            </div>
          `;
        })}
      </div>
    `;
  }

  _renderWeek() {
    const weekStart = this._weekStart(this._cursor);
    const days = Array.from({ length: 7 }, (_, i) => this._addDays(weekStart, i));
    const hours = Array.from({ length: 24 }, (_, i) => i);
    const weekdays = this._l("weekdaysShort", "Su,Mo,Tu,We,Th,Fr,Sa").split(",");

    return html`
      <div class="week-grid">
        <div></div>
        ${days.map((day, i) => html`<div class="weekday">${weekdays[i]} ${day.getDate()}</div>`)}
        ${hours.map((h) => html`
          <div class="time-label">${String(h).padStart(2, "0")}:00</div>
          ${days.map((day) => html`
            <div class="week-cell" @click=${() => this._onDateClick(day)}>
              ${this._eventsForDay(day).filter((ev) => {
                const s = new Date(ev.start);
                return !ev.allDay && s.getHours() === h;
              }).map((ev) => html`
                <div class="event" style="background:${ev.color || "var(--builtin-primary-soft, #eff6ff)"};color:${ev.color ? "#fff" : "var(--builtin-primary, #2563eb)"};"
                  @click=${(e) => { e.stopPropagation(); this._onEventClick(ev, day); }}>
                  ${ev.title}
                </div>
              `)}
            </div>
          `)}
        `)}
      </div>
    `;
  }

  _renderDay() {
    const hours = Array.from({ length: 24 }, (_, i) => i);
    const day = this._cursor;
    return html`
      <div class="day-view">
        ${hours.map((h) => html`
          <div class="day-hour" @click=${() => this._onDateClick(day)}>
            <div class="day-hour-label">${String(h).padStart(2, "0")}:00</div>
            <div class="day-hour-cell">
              ${this._eventsForDay(day).filter((ev) => {
                const s = new Date(ev.start);
                return !ev.allDay && s.getHours() === h;
              }).map((ev) => html`
                <div class="event" style="background:${ev.color || "var(--builtin-primary-soft, #eff6ff)"};color:${ev.color ? "#fff" : "var(--builtin-primary, #2563eb)"};"
                  @click=${(e) => { e.stopPropagation(); this._onEventClick(ev, day); }}>
                  ${ev.title}
                </div>
              `)}
            </div>
          </div>
        `)}
      </div>
    `;
  }

  _renderMobileList() {
    const weekStart = this._weekStart(this._cursor);
    const days = Array.from({ length: 7 }, (_, i) => this._addDays(weekStart, i));
    return html`
      <div class="mobile-list">
        ${days.map((day) => {
          const evs = this._eventsForDay(day);
          return html`
            <div class="mobile-day">
              <div class="mobile-day-title">${day.toLocaleDateString(this._ptLang, { weekday: "short", month: "short", day: "numeric" })}</div>
              ${evs.length === 0 ? html`<div style="color:var(--builtin-color-muted, #9ca3af);font-size:12px;">${this._l("noEvents", "No events")}</div>` : null}
              ${evs.map((ev) => html`
                <div class="mobile-event" @click=${() => this._onEventClick(ev, day)}>
                  <div style="font-weight:600;">${ev.title}</div>
                  <div style="font-size:12px;color:var(--builtin-color-muted, #6b7280);">${ev.allDay ? this._l("allDay", "All day") : `${new Date(ev.start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} - ${new Date(ev.end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`}</div>
                </div>
              `)}
            </div>
          `;
        })}
      </div>
    `;
  }

  render() {
    const modeClass = this.mode || "default";
    const effectiveView = this._ptMobile && this.view !== "day" ? "mobile" : this.view;
    return html`
      <div class="cal ${modeClass}">
        <div class="header">
          <div class="title">${this._fmtMonthYear(this._cursor)}</div>
          <div class="actions">
            <button class="btn" @click=${() => this._navigate(-1)} aria-label=${this._l("prev", "Previous")}>
              <builtin-icon name="left" size="20" variant="outlined"></builtin-icon>
            </button>
            <button class="btn primary" @click=${this._goToday}>${this._l("today", "Today")}</button>
            <button class="btn" @click=${() => this._navigate(1)} aria-label=${this._l("next", "Next")}>
              <builtin-icon name="right" size="20" variant="outlined"></builtin-icon>
            </button>
            <select class="btn" .value=${this.view} @change=${(e) => this.view = e.target.value}>
              <option value="month">${this._l("month", "Month")}</option>
              <option value="week">${this._l("week", "Week")}</option>
              <option value="day">${this._l("day", "Day")}</option>
            </select>
            <slot name="header-actions"></slot>
          </div>
        </div>
        ${effectiveView === "month" ? this._renderMonth()
          : effectiveView === "week" ? this._renderWeek()
          : effectiveView === "day" ? this._renderDay()
          : this._renderMobileList()}
        <div class="slot-area"><slot name="footer"></slot></div>
      </div>
    `;
  }
}
