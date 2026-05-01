/**
 * @fileoverview BuiltinAudioEditor — Audio waveform editor/trimmer backed by wavesurfer.js.
 *
 * @attr {string} src — Audio URL.
 * @attr {number} duration — Duration in seconds.
 * @attr {string} waveform — JSON array of amplitude values 0-1 (ignored; wavesurfer decodes automatically).
 * @attr {string} selection — JSON {start, end}.
 * @attr {boolean} playing — Playback state.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-selection-change — Detail: { start, end }.
 * @event builtin-play — Detail: {}.
 * @event builtin-pause — Detail: {}.
 * @event builtin-trim — Detail: { start, end }.
 */

import { BuiltinBaseElement, html, css } from "./lit-base.js";
import WaveSurfer from "../../vendor/wavesurfer/wavesurfer.esm.js";
import Regions from "../../vendor/wavesurfer/regions.esm.js";
import Timeline from "../../vendor/wavesurfer/timeline.esm.js";
import Hover from "../../vendor/wavesurfer/hover.esm.js";

export class BuiltinAudioEditor extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    duration: { type: Number },
    waveform: { type: Array },
    selection: { type: Object },
    playing: { type: Boolean },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .wrap { display: flex; flex-direction: column; gap: 10px; }
    .waveform-wrap {
      background: var(--builtin-header-bg, #f9fafb);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      overflow: hidden;
    }
    .toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .toolbar button {
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      min-height: 32px; padding: 0 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      font: inherit; font-size: 13px; font-weight: 600;
      cursor: pointer;
      transition: background .15s ease, border-color .15s ease, color .15s ease;
    }
    .toolbar button:hover {
      background: var(--builtin-header-bg, #f3f4f6);
      border-color: var(--builtin-primary, #2563eb);
      color: var(--builtin-primary, #2563eb);
    }
    .toolbar button:active { transform: translateY(1px); }
    .time { font-size: 13px; color: var(--builtin-color-muted, #6b7280); font-variant-numeric: tabular-nums; }
    @media (max-width: 720px) {
      .waveform-wrap { --ws-height: 90px; }
    }
  `;

  constructor() {
    super();
    this.src = "";
    this.duration = 0;
    this.waveform = [];
    this.selection = { start: 0, end: 0 };
    this.playing = false;
    this.labels = {};
    this._ws = null;
    this._regions = null;
    this._region = null;
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._destroyWs();
  }

  _destroyWs() {
    if (this._ws) {
      this._ws.destroy();
      this._ws = null;
      this._regions = null;
      this._region = null;
    }
  }

  firstUpdated() {
    requestAnimationFrame(() => this._initWs());
  }

  updated(changed) {
    if (changed.has("src") && this.src) {
      this._destroyWs();
      this._initWs();
    }
    if (changed.has("playing") && this._ws) {
      if (this.playing) this._ws.play();
      else this._ws.pause();
    }
    if (changed.has("selection") && this._region && this._ws?.isReady) {
      if (
        Math.abs(this._region.start - this.selection.start) > 0.001 ||
        Math.abs(this._region.end - this.selection.end) > 0.001
      ) {
        this._region.setOptions({
          start: Math.max(0, this.selection.start),
          end: Math.max(0, this.selection.end),
        });
      }
    }
  }

  _initWs() {
    if (!this.src || !this.shadowRoot) return;
    const container = this.shadowRoot.querySelector("#waveform");
    if (!container) return;

    const ws = WaveSurfer.create({
      container,
      waveColor: "var(--builtin-primary-soft, #93c5fd)",
      progressColor: "var(--builtin-primary, #2563eb)",
      cursorColor: "var(--builtin-primary-hover, #1d4ed8)",
      cursorWidth: 2,
      url: this.src,
      height: 120,
      normalize: true,
    });

    const regions = ws.registerPlugin(Regions.create());
    ws.registerPlugin(Timeline.create());
    ws.registerPlugin(Hover.create());

    ws.on("ready", () => {
      // Force timeline re-render now that wrapper has real dimensions
      ws.emit("redraw");
      const dur = ws.getDuration();
      if (!this.duration && Number.isFinite(dur)) {
        this.duration = dur;
      }
      const sel =
        this.selection && this.selection.end > this.selection.start
          ? this.selection
          : { start: 0, end: Math.min(dur || 1, 1.2) };
      const region = regions.addRegion({
        start: sel.start,
        end: sel.end,
        color: "rgba(37,99,235,0.15)",
        drag: true,
        resize: true,
      });
      region.on("update-end", () => {
        this.selection = { start: region.start, end: region.end };
        this.dispatchEvent(
          new CustomEvent("builtin-selection-change", {
            bubbles: true,
            composed: true,
            detail: { start: region.start, end: region.end },
          })
        );
      });
      this._region = region;
    });

    ws.on("play", () => {
      this.playing = true;
      this.dispatchEvent(new CustomEvent("builtin-play", { bubbles: true }));
    });

    ws.on("pause", () => {
      this.playing = false;
      this.dispatchEvent(new CustomEvent("builtin-pause", { bubbles: true }));
    });

    ws.on("timeupdate", (currentTime) => {
      if (this.selection?.end && currentTime >= this.selection.end) {
        ws.pause();
      }
    });

    this._ws = ws;
    this._regions = regions;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _fmt(t) {
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  _onPlay() {
    if (!this._ws) return;
    this._ws.playPause();
  }

  _onTrim() {
    this.dispatchEvent(
      new CustomEvent("builtin-trim", {
        bubbles: true,
        composed: true,
        detail: { ...(this.selection || { start: 0, end: 0 }) },
      })
    );
  }

  _zoomIn() {
    if (!this._ws) return;
    const current = this._ws.options.minPxPerSec || 10;
    this._ws.zoom(current * 1.3);
  }

  _zoomOut() {
    if (!this._ws) return;
    const current = this._ws.options.minPxPerSec || 10;
    this._ws.zoom(Math.max(10, current / 1.3));
  }

  render() {
    const sel = this.selection || { start: 0, end: 0 };
    const dur = this.duration || 0;
    return html`
      <div class="wrap">
        <div id="waveform" class="waveform-wrap"></div>
        <div class="toolbar">
          <button @click="${this._onPlay}">
            <builtin-icon
              name="${this.playing ? "pause" : "play-circle"}"
              size="18"
              variant="outlined"
            ></builtin-icon>
          </button>
          <button @click="${this._onTrim}">${this._l("audio.trim", "Trim")}</button>
          <button @click="${this._zoomOut}">−</button>
          <button @click="${this._zoomIn}">+</button>
          <span class="time">${this._fmt(sel.start)} — ${this._fmt(sel.end)} / ${this._fmt(dur)}</span>
        </div>
      </div>
    `;
  }
}
