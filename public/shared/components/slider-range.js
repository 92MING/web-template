/**
 * @fileoverview BuiltinSliderRange — Single or dual-handle slider.
 *
 * @attr {number} min — Minimum value (default 0).
 * @attr {number} max — Maximum value (default 100).
 * @attr {number} step — Step size (default 1).
 * @attr {number} value — Single handle value.
 * @attr {string} values — JSON array for dual-handle `[min, max]`.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-change — Detail: `{ value }` or `{ values }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinSliderRange extends BuiltinBaseElement {
  static properties = {
    min: { type: Number },
    max: { type: Number },
    step: { type: Number },
    value: { type: Number },
    values: { type: Array },
    labels: { type: Object },
    _dragging: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap { padding: 8px 4px; }
    .track-wrap { position: relative; height: 32px; display: flex; align-items: center; }
    .track {
      position: relative;
      width: 100%;
      height: 6px;
      background: var(--builtin-border-soft, #e5e7eb);
      border-radius: 999px;
      cursor: pointer;
    }
    .fill {
      position: absolute;
      height: 100%;
      background: var(--builtin-primary, #2563eb);
      border-radius: 999px;
    }
    .thumb {
      position: absolute;
      top: 50%;
      width: 18px;
      height: 18px;
      background: #fff;
      border: 2px solid var(--builtin-primary, #2563eb);
      border-radius: 50%;
      transform: translate(-50%, -50%);
      cursor: grab;
      box-shadow: 0 1px 3px rgba(0,0,0,0.12);
      z-index: 2;
    }
    .thumb:active { cursor: grabbing; }
    .thumb::after {
      content: attr(data-value);
      position: absolute;
      top: -24px;
      left: 50%;
      transform: translateX(-50%);
      font-size: 11px;
      font-weight: 600;
      color: var(--builtin-color-text, #111827);
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      padding: 2px 5px;
      border-radius: var(--builtin-radius, 6px);
      white-space: nowrap;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.1s;
    }
    .thumb:hover::after, .thumb.active::after { opacity: 1; }
    .labels {
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      color: var(--builtin-color-muted, #6b7280);
      margin-top: 4px;
    }
    @media (max-width: 720px) {
      .thumb { width: 26px; height: 26px; }
      .track { height: 8px; }
      .thumb::after { top: -28px; font-size: 12px; }
    }
  `;

  constructor() {
    super();
    this.min = 0;
    this.max = 100;
    this.step = 1;
    this.value = 0;
    this.values = null;
    this._dragging = null;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _clamp(v) {
    let val = Math.max(this.min, Math.min(this.max, v));
    if (this.step > 0) {
      val = Math.round((val - this.min) / this.step) * this.step + this.min;
    }
    return parseFloat(val.toFixed(10));
  }

  _pct(v) {
    const range = this.max - this.min || 1;
    return ((v - this.min) / range) * 100;
  }

  _valFromPct(pct) {
    const range = this.max - this.min || 1;
    return this._clamp(this.min + (pct / 100) * range);
  }

  _onTrackClick(e) {
    if (this._dragging) return;
    const track = this.shadowRoot.querySelector(".track");
    if (!track) return;
    const rect = track.getBoundingClientRect();
    const pct = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
    const val = this._valFromPct(pct);
    if (this.values && Array.isArray(this.values)) {
      const distLow = Math.abs(val - this.values[0]);
      const distHigh = Math.abs(val - this.values[1]);
      if (distLow <= distHigh) {
        this.values = [val, this.values[1]];
      } else {
        this.values = [this.values[0], val];
      }
      this.dispatchEvent(new CustomEvent("builtin-change", { detail: { values: [...this.values] }, bubbles: true }));
    } else {
      this.value = val;
      this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true }));
    }
  }

  _startDrag(which, e) {
    e.preventDefault();
    this._dragging = which;
    const track = this.shadowRoot.querySelector(".track");
    if (!track) return;
    const rect = track.getBoundingClientRect();
    const move = (ev) => {
      const pct = Math.max(0, Math.min(100, ((ev.clientX - rect.left) / rect.width) * 100));
      const val = this._valFromPct(pct);
      if (which === "single") {
        this.value = val;
        this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true }));
      } else if (which === "low") {
        const high = this.values?.[1] ?? this.max;
        this.values = [Math.min(val, high), high];
        this.dispatchEvent(new CustomEvent("builtin-change", { detail: { values: [...this.values] }, bubbles: true }));
      } else if (which === "high") {
        const low = this.values?.[0] ?? this.min;
        this.values = [low, Math.max(val, low)];
        this.dispatchEvent(new CustomEvent("builtin-change", { detail: { values: [...this.values] }, bubbles: true }));
      }
    };
    const up = () => {
      this._dragging = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  render() {
    const isDual = this.values && Array.isArray(this.values);
    const low = isDual ? this.values[0] : this.min;
    const high = isDual ? this.values[1] : this.value;
    const lowPct = this._pct(low);
    const highPct = this._pct(high);

    return html`
      <div class="wrap">
        <div class="track-wrap">
          <div class="track" @click=${this._onTrackClick}>
            ${isDual
              ? html`
                  <div class="fill" style="${styleMap({ left: `${lowPct}%`, width: `${highPct - lowPct}%` })}"></div>
                  <div
                    class="thumb ${classMap({ active: this._dragging === "low" })}"
                    style="${styleMap({ left: `${lowPct}%` })}"
                    data-value="${low}"
                    @pointerdown=${(e) => this._startDrag("low", e)}
                  ></div>
                  <div
                    class="thumb ${classMap({ active: this._dragging === "high" })}"
                    style="${styleMap({ left: `${highPct}%` })}"
                    data-value="${high}"
                    @pointerdown=${(e) => this._startDrag("high", e)}
                  ></div>
                `
              : html`
                  <div class="fill" style="${styleMap({ left: "0%", width: `${highPct}%` })}"></div>
                  <div
                    class="thumb ${classMap({ active: this._dragging === "single" })}"
                    style="${styleMap({ left: `${highPct}%` })}"
                    data-value="${high}"
                    @pointerdown=${(e) => this._startDrag("single", e)}
                  ></div>
                `}
          </div>
        </div>
        <div class="labels">
          <span>${this.min}</span>
          <span>${this.max}</span>
        </div>
      </div>
    `;
  }
}
