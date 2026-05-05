/**
 * @fileoverview BuiltinQrCodeDisplay — QR code generator wrapper.
 *
 * @element builtin-qr-code-display
 *
 * @attr {string} value — Text to encode
 * @attr {number} size — Width/height in px (default 200)
 * @attr {string} color — Foreground color (default --builtin-color-text)
 * @attr {string} bg — Background color (default --builtin-surface)
 * @attr {string} logo — Optional image URL to overlay in center
 * @attr {string} mode — `default` | `rounded`
 * @attr {Object} labels — JSON object for i18n overrides
 *
 * @slot overlay — Custom overlay content in center of QR code
 */

import { BuiltinBaseElement, html, css, classMap } from "../lit-base.js";
import QRCode from "../../../vendor/qrcode/index.js";

export class BuiltinQrCodeDisplay extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    size: { type: Number },
    color: { type: String },
    bg: { type: String },
    logo: { type: String },
    mode: { type: String },
    labels: { type: Object },
    _error: { type: String, state: true },
  };

  static styles = css`
    :host { display: inline-block; }
    .wrap {
      position: relative;
      display: inline-block;
      line-height: 0;
      background: var(--builtin-surface, #ffffff);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
    }
    .wrap.rounded { border-radius: var(--builtin-radius-xl, 16px); }
    .qr-target,
    .qr-target canvas,
    .qr-target img,
    .qr-target svg {
      display: block;
      width: 100%;
      height: 100%;
      image-rendering: pixelated;
    }
    .overlay {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      width: 20%;
      height: 20%;
      min-width: 24px; min-height: 24px;
      max-width: 64px; max-height: 64px;
      background: var(--builtin-surface, #ffffff);
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      overflow: hidden;
      border: 2px solid var(--builtin-surface, #ffffff);
    }
    .overlay img {
      width: 100%; height: 100%; object-fit: contain;
    }
    .error {
      color: var(--builtin-color-danger, #b91c1c);
      font-size: 12px;
      padding: 8px;
    }
    @media (max-width: 720px) {
      .wrap { padding: 8px; }
      .qr-target { max-width: 100vw; }
    }
  `;

  constructor() {
    super();
    this.value = "";
    this.size = 200;
    this.mode = "default";
    this._error = "";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  async updated(changed) {
    if (changed.has("value") || changed.has("size") || changed.has("color") || changed.has("bg") || changed.has("mode") || changed.has("_ptTheme") || changed.has("_ptMobile")) {
      if (this.value) await this._generate();
      else this._clearTarget();
    }
  }

  _resolveCssValue(value, fallback) {
    const raw = String(value || fallback).trim();
    const match = raw.match(/^var\(\s*([^,\s)]+)\s*(?:,\s*([^)]+))?\)$/);
    if (!match) return raw;
    const resolved = getComputedStyle(this).getPropertyValue(match[1]).trim();
    return resolved || (match[2]?.trim() || fallback);
  }

  _resolveColor() {
    const rawColor = this.color || "var(--builtin-color-text, #111827)";
    const rawBg = this.bg || "var(--builtin-surface, #ffffff)";
    return {
      color: this._resolveCssValue(rawColor, "#111827"),
      bg: this._resolveCssValue(rawBg, "#ffffff"),
    };
  }

  _clearTarget() {
    const target = this.shadowRoot?.querySelector(".qr-target");
    if (target) target.replaceChildren();
  }

  async _generate() {
    try {
      const QRCodeCtor = await QRCode;
      await this.updateComplete;
      const target = this.shadowRoot.querySelector(".qr-target");
      if (!target) return;
      target.replaceChildren();
      const colors = this._resolveColor();
      const size = Math.min(this.size || 200, this._ptMobile ? window.innerWidth - 32 : Infinity);
      new QRCodeCtor(target, {
        text: this.value,
        width: size,
        height: size,
        colorDark: colors.color,
        colorLight: colors.bg,
        correctLevel: this.logo ? QRCodeCtor.CorrectLevel.H : QRCodeCtor.CorrectLevel.M,
      });
      this._error = "";
    } catch (err) {
      this._error = String(err?.message || err);
      this._clearTarget();
    }
  }

  render() {
    const mode = this.mode || "default";
    const size = Math.min(this.size || 200, this._ptMobile ? window.innerWidth - 32 : Infinity);

    return html`
      <div class="wrap ${classMap({ rounded: mode === "rounded" })}">
        ${this._error
          ? html`<div class="error">${this._error}</div>`
          : html`
            <div class="qr-target" style="width:${size}px;height:${size}px;" role="img" aria-label="${this._l("qrCode.alt", "QR Code")}"></div>
            ${this.logo
              ? html`<div class="overlay"><img src="${this.logo}" alt="" /></div>`
              : html`<div class="overlay"><slot name="overlay"></slot></div>`}
          `}
      </div>
    `;
  }
}
