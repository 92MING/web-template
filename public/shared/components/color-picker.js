/**
 * @fileoverview BuiltinColorPicker — Color picker with hue/sat box, alpha, hex input and presets.
 *
 * @attr {string} value — Hex color (default `#2563eb`).
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-change — Detail: `{ value }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

const PRESETS = [
  "#ef4444", "#f97316", "#f59e0b", "#84cc16", "#10b981",
  "#06b6d4", "#3b82f6", "#6366f1", "#8b5cf6", "#d946ef",
  "#f43f5e", "#111827", "#6b7280", "#d1d5db", "#ffffff",
];

function hexToRgb(hex) {
  const m = hex.replace("#", "");
  const bigint = parseInt(m.length === 3 ? m.split("").map((c) => c + c).join("") : m, 16);
  if (isNaN(bigint)) return { r: 0, g: 0, b: 0 };
  return { r: (bigint >> 16) & 255, g: (bigint >> 8) & 255, b: bigint & 255 };
}

function rgbToHex(r, g, b) {
  return "#" + [r, g, b].map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0")).join("");
}

function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0, v = max;
  const d = max - min;
  s = max === 0 ? 0 : d / max;
  if (max !== min) {
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    h /= 6;
  }
  return { h, s, v };
}

function hsvToRgb(h, s, v) {
  let r = 0, g = 0, b = 0;
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const t = v * (1 - (1 - f) * s);
  switch (i % 6) {
    case 0: r = v; g = t; b = p; break;
    case 1: r = q; g = v; b = p; break;
    case 2: r = p; g = v; b = t; break;
    case 3: r = p; g = q; b = v; break;
    case 4: r = t; g = p; b = v; break;
    case 5: r = v; g = p; b = q; break;
  }
  return { r: r * 255, g: g * 255, b: b * 255 };
}

export class BuiltinColorPicker extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    labels: { type: Object },
    _hsva: { type: Object, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-width: 260px;
    }
    .box {
      position: relative;
      width: 100%;
      aspect-ratio: 1 / 1;
      border-radius: var(--builtin-radius, 6px);
      overflow: hidden;
      cursor: crosshair;
      touch-action: none;
    }
    .box-bg {
      position: absolute; inset: 0;
      background: linear-gradient(to bottom, transparent, #000),
                  linear-gradient(to right, #fff, transparent);
    }
    .box-hue {
      position: absolute; inset: 0;
    }
    .box-cursor {
      position: absolute;
      width: 14px; height: 14px;
      border: 2px solid #fff;
      border-radius: 50%;
      box-shadow: 0 0 2px rgba(0,0,0,0.5);
      transform: translate(-50%, -50%);
      pointer-events: none;
    }
    .sliders { display: flex; flex-direction: column; gap: 10px; }
    .slider-track {
      position: relative;
      height: 16px;
      border-radius: 999px;
      cursor: pointer;
      touch-action: none;
    }
    .slider-thumb {
      position: absolute;
      top: 50%;
      width: 18px; height: 18px;
      background: #fff;
      border: 2px solid var(--builtin-border, #d1d5db);
      border-radius: 50%;
      transform: translate(-50%, -50%);
      box-shadow: 0 1px 3px rgba(0,0,0,0.15);
      pointer-events: none;
    }
    .hue-track {
      background: linear-gradient(to right, #f00 0%, #ff0 17%, #0f0 33%, #0ff 50%, #00f 67%, #f0f 83%, #f00 100%);
    }
    .alpha-track {
      background-image: linear-gradient(45deg, #ccc 25%, transparent 25%), linear-gradient(-45deg, #ccc 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #ccc 75%), linear-gradient(-45deg, transparent 75%, #ccc 75%);
      background-size: 10px 10px;
      background-position: 0 0, 0 5px, 5px -5px, -5px 0px;
    }
    .alpha-fill {
      position: absolute; inset: 0;
      border-radius: 999px;
    }
    .row {
      display: flex; align-items: center; gap: 8px;
    }
    .preview {
      width: 36px; height: 36px;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border, #d1d5db);
      flex-shrink: 0;
    }
    .hex {
      flex: 1;
      padding: 6px 8px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      font-size: 13px;
      text-transform: uppercase;
    }
    .presets {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 6px;
    }
    .swatch {
      width: 100%;
      aspect-ratio: 1 / 1;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      cursor: pointer;
    }
    .swatch:hover { transform: scale(1.05); }
    @media (max-width: 720px) {
      .wrap { max-width: none; width: 100%; }
      .box { aspect-ratio: 16 / 9; }
      .slider-track { height: 24px; }
      .slider-thumb { width: 26px; height: 26px; }
      .presets { grid-template-columns: repeat(5, 1fr); }
    }
  `;

  constructor() {
    super();
    this.value = "#2563eb";
    this._hsva = { h: 0.6, s: 0.8, v: 0.92, a: 1 };
  }

  connectedCallback() {
    super.connectedCallback();
    this._syncFromValue();
  }

  willUpdate(changed) {
    if (changed.has("value")) {
      this._syncFromValue();
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _syncFromValue() {
    const rgb = hexToRgb(this.value || "#000000");
    const hsv = rgbToHsv(rgb.r, rgb.g, rgb.b);
    this._hsva = { h: hsv.h, s: hsv.s, v: hsv.v, a: 1 };
  }

  _toHex() {
    const rgb = hsvToRgb(this._hsva.h, this._hsva.s, this._hsva.v);
    return rgbToHex(rgb.r, rgb.g, rgb.b);
  }

  _emit() {
    const hex = this._toHex();
    this.value = hex;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: hex }, bubbles: true }));
  }

  _setSatValFromBox(rect, clientX, clientY) {
    const x = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    this._hsva = { ...this._hsva, s: x, v: 1 - y };
    this._emit();
  }

  _onBoxDown(e) {
    const box = this.shadowRoot.querySelector(".box");
    if (!box) return;
    const rect = box.getBoundingClientRect();
    const move = (ev) => this._setSatValFromBox(rect, ev.clientX, ev.clientY);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    this._setSatValFromBox(rect, e.clientX, e.clientY);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  _setHueFromTrack(rect, clientX) {
    const x = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    this._hsva = { ...this._hsva, h: x };
    this._emit();
  }

  _onHueDown(e) {
    const track = this.shadowRoot.querySelector(".hue-track");
    if (!track) return;
    const rect = track.getBoundingClientRect();
    const move = (ev) => this._setHueFromTrack(rect, ev.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    this._setHueFromTrack(rect, e.clientX);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  _onHexInput(e) {
    const v = e.target.value.trim();
    if (/^#[0-9A-Fa-f]{6}$/.test(v)) {
      this.value = v;
      this._syncFromValue();
      this._emit();
    }
  }

  _applyPreset(hex) {
    this.value = hex;
    this._syncFromValue();
    this._emit();
  }

  render() {
    const hueColor = rgbToHex(hsvToRgb(this._hsva.h, 1, 1));
    const currentColor = this._toHex();
    return html`
      <div class="wrap">
        <div class="box" @pointerdown=${this._onBoxDown}>
          <div class="box-hue" style="${styleMap({ background: hueColor })}"></div>
          <div class="box-bg"></div>
          <div class="box-cursor" style="${styleMap({ left: `${this._hsva.s * 100}%`, top: `${(1 - this._hsva.v) * 100}%` })}"></div>
        </div>
        <div class="sliders">
          <div class="slider-track hue-track" @pointerdown=${this._onHueDown}>
            <div class="slider-thumb" style="${styleMap({ left: `${this._hsva.h * 100}%` })}"></div>
          </div>
        </div>
        <div class="row">
          <div class="preview" style="${styleMap({ background: currentColor })}"></div>
          <input class="hex" type="text" .value=${currentColor} @change=${this._onHexInput} />
        </div>
        <div class="presets">
          ${PRESETS.map((hex) => html`<div class="swatch" style="${styleMap({ background: hex })}" @click=${() => this._applyPreset(hex)}></div>`)}
        </div>
      </div>
    `;
  }
}
