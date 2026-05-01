import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinBookingCalendar — Week view resource booking grid.
 *
 * Attributes:
 * - `resources` (JSON): `[{id, name}]`
 * - `bookings` (JSON): `[{resourceId, start, end, title}]`
 * - `labels` (JSON object for local i18n overrides)
 *
 * Events:
 * - `builtin-book` — Clicked an empty slot. Detail: `{ resourceId, start, end }`
 * - `builtin-view` — Clicked a booking. Detail: `{ booking }`
 */
export class BuiltinBookingCalendar extends BuiltinBaseElement {
  static get properties() {
    return {
      resources: {
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
      bookings: {
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
      _cursor: { type: Date, state: true },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .cal {
        border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius-lg, 8px);
        background: var(--builtin-surface, #ffffff);
        overflow: hidden;
      }
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 10px 12px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        flex-wrap: wrap;
      }
      .title {
        font-weight: 650;
        font-size: 15px;
        color: var(--builtin-color-text, #111827);
      }
      .actions {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        padding: 6px 10px;
        border: 1px solid var(--builtin-border, #d1d5db);
        background: var(--builtin-surface, #ffffff);
        border-radius: var(--builtin-radius, 6px);
        cursor: pointer;
        color: var(--builtin-color-text, #111827);
        min-height: 32px;
        font-size: 13px;
      }
      .btn:hover {
        background: var(--builtin-row-hover-bg, #f9fafb);
      }
      .grid-wrap {
        overflow-x: auto;
      }
      .grid {
        display: grid;
        grid-template-columns: 120px repeat(24, minmax(52px, 1fr));
        min-width: 600px;
      }
      .cell {
        padding: 8px;
        border-right: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        font-size: 12px;
        min-height: 56px;
      }
      .cell.header-cell {
        background: var(--builtin-header-bg, #f9fafb);
        font-weight: 600;
        color: var(--builtin-color-muted, #6b7280);
        text-align: center;
        position: sticky;
        left: 0;
        z-index: 1;
      }
      .cell.resource-cell {
        background: var(--builtin-surface, #ffffff);
        font-weight: 600;
        color: var(--builtin-color-text, #111827);
        display: flex;
        align-items: center;
        position: sticky;
        left: 0;
        z-index: 1;
      }
      .cell.hour-cell {
        text-align: center;
        cursor: pointer;
        background: var(--builtin-surface, #ffffff);
      }
      .cell.hour-cell:hover {
        background: var(--builtin-row-hover-bg, #f9fafb);
      }
      .cell.hour-cell.booked {
        background: var(--builtin-primary-soft, #eff6ff);
        cursor: pointer;
      }
      .booking-chip {
        font-size: 11px;
        padding: 4px 8px;
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-primary, #2563eb);
        color: #fff;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      /* Mobile list view */
      .mobile-list {
        display: none;
        padding: 10px;
      }
      .resource-group {
        margin-bottom: 16px;
      }
      .resource-title {
        font-weight: 650;
        font-size: 14px;
        margin-bottom: 8px;
        color: var(--builtin-color-text, #111827);
      }
      .slot-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 8px;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
        font-size: 13px;
        min-height: 44px;
      }
      .slot-row:last-child {
        border-bottom: none;
      }
      .slot-row.booked {
        background: var(--builtin-primary-soft, #eff6ff);
        border-radius: var(--builtin-radius, 6px);
        margin-bottom: 4px;
        border-bottom: none;
      }
      .slot-label {
        color: var(--builtin-color-muted, #6b7280);
      }
      .slot-value {
        font-weight: 500;
        color: var(--builtin-color-text, #111827);
      }
      @media (max-width: 720px) {
        .grid-wrap {
          display: none;
        }
        .mobile-list {
          display: block;
        }
      }
    `;
  }

  constructor() {
    super();
    this.resources = [];
    this.bookings = [];
    this.labels = {};
    this._cursor = new Date();
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

  _weekStart(d) {
    const day = d.getDay();
    const start = new Date(d);
    start.setDate(start.getDate() - day);
    start.setHours(0, 0, 0, 0);
    return start;
  }

  _addDays(date, days) {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d;
  }

  _sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  _bookingsFor(resourceId, hour) {
    return (this.bookings || []).filter((b) => {
      if (b.resourceId !== resourceId) return false;
      const s = new Date(b.start);
      return this._sameDay(s, this._cursor) && s.getHours() === hour;
    });
  }

  _onSlotClick(resourceId, hour) {
    const start = new Date(this._cursor);
    start.setHours(hour, 0, 0, 0);
    const end = new Date(start);
    end.setHours(hour + 1, 0, 0, 0);
    this.dispatchEvent(
      new CustomEvent("builtin-book", {
        bubbles: true,
        composed: true,
        detail: { resourceId, start: start.toISOString(), end: end.toISOString() },
      })
    );
  }

  _onBookingClick(booking) {
    this.dispatchEvent(
      new CustomEvent("builtin-view", {
        bubbles: true,
        composed: true,
        detail: { booking },
      })
    );
  }

  _navigate(delta) {
    const d = new Date(this._cursor);
    d.setDate(d.getDate() + delta * 7);
    this._cursor = d;
  }

  _goToday() {
    this._cursor = new Date();
  }

  _fmtWeek(d) {
    const ws = this._weekStart(d);
    const we = this._addDays(ws, 6);
    const opts = { month: "short", day: "numeric" };
    return `${ws.toLocaleDateString(this._ptLang, opts)} – ${we.toLocaleDateString(this._ptLang, opts)}`;
  }

  _renderGrid() {
    const resources = Array.isArray(this.resources) ? this.resources : [];
    const hours = Array.from({ length: 24 }, (_, i) => i);
    return html`
      <div class="grid-wrap">
        <div class="grid">
          <div class="cell header-cell">${this._t("booking.resource")}</div>
          ${hours.map((h) => html`
            <div class="cell header-cell">${String(h).padStart(2, "0")}:00</div>
          `)}
          ${resources.map((r) => html`
            <div class="cell resource-cell">${r.name || r.id}</div>
            ${hours.map((h) => {
              const bookings = this._bookingsFor(r.id, h);
              const isBooked = bookings.length > 0;
              return html`
                <div
                  class="cell hour-cell ${classMap({ booked: isBooked })}"
                  @click=${isBooked
                    ? () => this._onBookingClick(bookings[0])
                    : () => this._onSlotClick(r.id, h)}
                >
                  ${isBooked
                    ? html`<div class="booking-chip">${bookings[0].title || this._t("booking.booked")}</div>`
                    : ""}
                </div>
              `;
            })}
          `)}
        </div>
      </div>
    `;
  }

  _renderMobileList() {
    const resources = Array.isArray(this.resources) ? this.resources : [];
    const hours = Array.from({ length: 24 }, (_, i) => i);
    return html`
      <div class="mobile-list">
        ${resources.map((r) => html`
          <div class="resource-group">
            <div class="resource-title">${r.name || r.id}</div>
            ${hours.map((h) => {
              const bookings = this._bookingsFor(r.id, h);
              const isBooked = bookings.length > 0;
              const label = `${String(h).padStart(2, "0")}:00`;
              return html`
                <div
                  class="slot-row ${classMap({ booked: isBooked })}"
                  @click=${isBooked
                    ? () => this._onBookingClick(bookings[0])
                    : () => this._onSlotClick(r.id, h)}
                >
                  <span class="slot-label">${label}</span>
                  <span class="slot-value">
                    ${isBooked
                      ? (bookings[0].title || this._t("booking.booked"))
                      : this._t("booking.available")}
                  </span>
                </div>
              `;
            })}
          </div>
        `)}
      </div>
    `;
  }

  render() {
    return html`
      <div class="cal" data-theme="${this._ptTheme}">
        <div class="header">
          <div class="title">${this._fmtWeek(this._cursor)}</div>
          <div class="actions">
            <button class="btn" @click=${() => this._navigate(-1)} aria-label="${this._t("booking.prev")}">
              <builtin-icon name="left" size="16" variant="outlined"></builtin-icon>
            </button>
            <button class="btn" @click=${this._goToday}>${this._t("booking.today")}</button>
            <button class="btn" @click=${() => this._navigate(1)} aria-label="${this._t("booking.next")}">
              <builtin-icon name="right" size="16" variant="outlined"></builtin-icon>
            </button>
          </div>
        </div>
        ${this._ptMobile ? this._renderMobileList() : this._renderGrid()}
      </div>
    `;
  }
}
