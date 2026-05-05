import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview BuiltinInputOtp — One-time code input with auto-focus and paste support.
 *
 * @attr {number} length — Number of digits (default 6).
 * @attr {string} value — Current OTP value.
 * @attr {Object} labels — JSON object for i18n overrides.
 *
 * @event builtin-change — Fired on any input change. Detail: `{ value }`
 * @event builtin-complete — Fired when all boxes are filled. Detail: `{ value }`
 */
export class BuiltinInputOtp extends BuiltinBaseElement {
  static properties = {
    length: { type: Number },
    value: { type: String },
    labels: { type: Object },
    _values: { type: Array, state: true },
  };

  static styles = css`
    :host {
      display: block;
    }
    .otp {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: flex-start;
    }
    input {
      width: 40px;
      height: 48px;
      text-align: center;
      font-size: 18px;
      font-weight: 650;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      outline: none;
      caret-color: var(--builtin-primary, #2563eb);
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    input:focus {
      border-color: var(--builtin-primary, #2563eb);
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
    }
    @media (max-width: 720px) {
      input {
        width: 48px;
        height: 56px;
        font-size: 22px;
      }
    }
  `;

  constructor() {
    super();
    this.length = 6;
    this.value = "";
    this._values = [];
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  willUpdate(changed) {
    if (changed.has("value") || changed.has("length")) {
      this._syncValues();
    }
  }

  _syncValues() {
    const len = this.length || 6;
    const arr = new Array(len).fill("");
    const val = (this.value || "").split("");
    for (let i = 0; i < Math.min(val.length, len); i++) {
      arr[i] = val[i];
    }
    this._values = arr;
  }

  _focusInput(index) {
    const el = this.shadowRoot.querySelector(`input[data-index="${index}"]`);
    if (el) {
      el.focus();
      el.select();
    }
  }

  _onInput(index, e) {
    const input = e.target;
    const val = (input.value || "").replace(/[^0-9]/g, "").slice(-1);
    input.value = val;

    const nextValues = [...this._values];
    nextValues[index] = val;
    this._values = nextValues;
    this.value = nextValues.join("");

    this.dispatchEvent(
      new CustomEvent("builtin-change", {
        detail: { value: this.value },
        bubbles: true,
        composed: true,
      })
    );

    if (val && index < (this.length || 6) - 1) {
      this._focusInput(index + 1);
    }

    if (this.value.length === (this.length || 6)) {
      this.dispatchEvent(
        new CustomEvent("builtin-complete", {
          detail: { value: this.value },
          bubbles: true,
          composed: true,
        })
      );
    }
  }

  _onKeydown(index, e) {
    if (e.key === "Backspace" && !e.target.value) {
      e.preventDefault();
      if (index > 0) {
        const prev = index - 1;
        const nextValues = [...this._values];
        nextValues[prev] = "";
        this._values = nextValues;
        this.value = nextValues.join("");
        this._focusInput(prev);
        this.dispatchEvent(
          new CustomEvent("builtin-change", {
            detail: { value: this.value },
            bubbles: true,
            composed: true,
          })
        );
      }
    }
    if (e.key === "ArrowLeft" && index > 0) {
      this._focusInput(index - 1);
    }
    if (e.key === "ArrowRight" && index < (this.length || 6) - 1) {
      this._focusInput(index + 1);
    }
  }

  _onPaste(e) {
    e.preventDefault();
    const paste = (e.clipboardData.getData("text") || "").replace(/[^0-9]/g, "");
    if (!paste) return;

    const len = this.length || 6;
    const arr = new Array(len).fill("");
    for (let i = 0; i < Math.min(paste.length, len); i++) {
      arr[i] = paste[i];
    }
    this._values = arr;
    this.value = arr.join("");

    this.dispatchEvent(
      new CustomEvent("builtin-change", {
        detail: { value: this.value },
        bubbles: true,
        composed: true,
      })
    );

    if (this.value.length === len) {
      this.dispatchEvent(
        new CustomEvent("builtin-complete", {
          detail: { value: this.value },
          bubbles: true,
          composed: true,
        })
      );
    }

    const focusIndex = Math.min(paste.length, len - 1);
    this.updateComplete.then(() => this._focusInput(focusIndex));
  }

  render() {
    const len = this.length || 6;
    return html`
      <div
        class="otp"
        role="group"
        aria-label="${this._l("otp.label", "One-time code")}"
        part="otp"
      >
        ${repeat(
          new Array(len).fill(0),
          (_, i) => i,
          (_, i) => html`
            <input
              type="text"
              inputmode="numeric"
              maxlength="1"
              pattern="[0-9]*"
              data-index="${i}"
              .value="${this._values[i] || ""}"
              aria-label="${this._l("otp.digit", "Digit")} ${i + 1}"
              @input="${(e) => this._onInput(i, e)}"
              @keydown="${(e) => this._onKeydown(i, e)}"
              @paste="${this._onPaste}"
              part="input"
            />
          `
        )}
        <slot></slot>
      </div>
    `;
  }
}
