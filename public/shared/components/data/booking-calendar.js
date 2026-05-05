import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

export class BuiltinBookingCalendar extends BuiltinBaseElement {
  static properties = { resources: { type: Array }, bookings: { type: Array }, labels: { type: Object }, currentDate: { type: String, attribute: "current-date" } };
  static styles = css`:host { display:block; } .calendar { border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-surface, #fff); }`;
  constructor() { super(); this.resources = []; this.bookings = []; this._calendar = null; }
  firstUpdated() { this._initCalendar(); }
  updated(changed) { if (this._calendar && changed.has("bookings")) { this._calendar.removeAllEvents(); this._calendar.addEventSource(this._events()); } }
  disconnectedCallback() { this._calendar?.destroy?.(); this._calendar = null; super.disconnectedCallback(); }
  async _initCalendar() { const FullCalendar = await ensureVendor("fullcalendar"); const target = this.renderRoot.querySelector(".calendar"); if (!target || this._calendar) return; this._calendar = new FullCalendar.Calendar(target, { initialView: "timeGridWeek", initialDate: this.currentDate || undefined, events: this._events(), headerToolbar: { left: "prev,next today", center: "title", right: "timeGridWeek,timeGridDay" }, locale: this._ptLang || undefined, dateClick: (info) => this.dispatchEvent(new CustomEvent("builtin-book", { detail: { start: info.dateStr, end: info.dateStr }, bubbles: true, composed: true })), eventClick: (info) => this.dispatchEvent(new CustomEvent("builtin-view", { detail: { booking: info.event.extendedProps.booking || info.event.toPlainObject() }, bubbles: true, composed: true })) }); this._calendar.render(); }
  _events() { return (this.bookings || []).map((booking) => ({ title: booking.title || this._resourceName(booking.resourceId), start: booking.start, end: booking.end, allDay: booking.allDay, extendedProps: { booking } })); }
  _resourceName(id) { return (this.resources || []).find((resource) => resource.id === id)?.name || id || "Booking"; }
  render() { return html`<div class="calendar"></div>`; }
}