import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

const VIEW_MAP = { month: "dayGridMonth", week: "timeGridWeek", day: "timeGridDay" };

export class BuiltinCalendar extends BuiltinBaseElement {
  static properties = { view: { type: String }, events: { type: Array }, currentDate: { type: String, attribute: "current-date" }, mode: { type: String }, labels: { type: Object } };
  static styles = css`
    :host { display: block; }
    .calendar { min-height: var(--builtin-calendar-height, 520px); border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); padding: 8px; font-size: 13px; }
    .fc { font-size: 13px; color: var(--builtin-color-text, #111827); }
    .fc .fc-view-harness { min-height: calc(var(--builtin-calendar-height, 520px) - 72px) !important; }
    .fc .fc-toolbar { gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
    .fc .fc-toolbar-title { font-size: 16px; font-weight: 700; }
    .fc .fc-button { border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-button-bg, #ffffff); color: var(--builtin-color-text, #111827); border-radius: var(--builtin-radius, 6px); padding: 4px 8px; text-transform: none; box-shadow: none; }
    .fc .fc-button-primary:not(:disabled).fc-button-active, .fc .fc-button-primary:not(:disabled):active { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .fc .fc-scrollgrid, .fc td, .fc th { border-color: var(--builtin-border-soft, #e5e7eb); }
    .fc .fc-col-header-cell, .fc .fc-daygrid-day { background: var(--builtin-surface, #ffffff); }
    .fc .fc-col-header-cell-cushion, .fc .fc-daygrid-day-number { color: var(--builtin-color-text, #111827); text-decoration: none; padding: 4px; }
    .fc .fc-event { border-radius: 4px; border: 0; background: var(--builtin-primary, #2563eb); font-size: 12px; padding: 1px 3px; }
    @media (max-width: 720px) { .fc .fc-toolbar-title { font-size: 14px; } .fc { font-size: 12px; } }
  `;
  constructor() {
    super();
    this.view = "month";
    this.events = [];
    this.mode = "default";
    this._calendar = null;
    this._resizeObserver = null;
    this._intersectionObserver = null;
    this._onWindowResize = () => this._scheduleUpdateSize();
    this._onTabChange = () => this._scheduleUpdateSize(10);
  }
  createRenderRoot() { return this; }
  firstUpdated() { this._initCalendar(); }
  updated(changed) { if (!this._calendar) return; if (changed.has("events")) { this._calendar.removeAllEvents(); this._calendar.addEventSource(this.events || []); } if (changed.has("view")) this._calendar.changeView(VIEW_MAP[this.view] || "dayGridMonth"); if (changed.has("currentDate") && this.currentDate) this._calendar.gotoDate(this.currentDate); this._scheduleUpdateSize(); }
  disconnectedCallback() {
    window.removeEventListener("resize", this._onWindowResize);
    document.removeEventListener("builtin-tab-change", this._onTabChange);
    this._resizeObserver?.disconnect?.();
    this._intersectionObserver?.disconnect?.();
    this._calendar?.destroy?.();
    this._calendar = null;
    super.disconnectedCallback();
  }

  async _initCalendar() {
    const FullCalendar = await ensureVendor("fullcalendar");
    const target = this.renderRoot.querySelector(".calendar");
    if (!target || this._calendar) return;
    this._calendar = new FullCalendar.Calendar(target, {
      initialView: VIEW_MAP[this.view] || "dayGridMonth",
      initialDate: this.currentDate || undefined,
      events: this.events || [],
      headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,timeGridDay" },
      locale: this._ptLang || undefined,
      dateClick: (info) => this.dispatchEvent(new CustomEvent("builtin-date-click", { detail: { date: info.dateStr, day: info.date }, bubbles: true, composed: true })),
      eventClick: (info) => this.dispatchEvent(new CustomEvent("builtin-event-click", { detail: { event: info.event.toPlainObject(), date: info.event.start?.toISOString() }, bubbles: true, composed: true })),
    });
    this._calendar.render();
    this._resizeObserver = new ResizeObserver(() => this._scheduleUpdateSize());
    this._resizeObserver.observe(target);
    this._intersectionObserver = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) this._scheduleUpdateSize(10);
    });
    this._intersectionObserver.observe(this);
    window.addEventListener("resize", this._onWindowResize);
    document.addEventListener("builtin-tab-change", this._onTabChange);
    this._scheduleUpdateSize(12);
  }

  _scheduleUpdateSize(retries = 4) {
    let count = 0;
    const tick = () => {
      this._calendar?.updateSize?.();
      count += 1;
      if (count < retries) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  render() { return html`<style>${this.constructor.styles.cssText}</style><div class="calendar"></div><slot></slot>`; }
}