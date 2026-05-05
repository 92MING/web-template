/**
 * @fileoverview BuiltinAudioEditor — minimal Gradio-style audio player/trimmer.
 *
 * Look & feel matches a Gradio audio output card: dark rounded card with a
 * bright orange waveform, a single header row (label + download), the waveform
 * with time labels overlaid, and a bottom controls row (volume + speed pill on
 * the left, transport in the centre).
 *
 * Trim mode is opt-in via the ``editable`` boolean attribute. In edit mode the
 * user can drag on the waveform to create a single region (with draggable
 * handles); a small "Trim" pill appears in the header to confirm.
 */

import { BuiltinBaseElement, html, css } from "../lit-base.js";
import WaveSurfer from "../../../vendor/wavesurfer/wavesurfer.esm.js";
import Regions from "../../../vendor/wavesurfer/regions.esm.js";

const RATE_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const REGION_MIN_LEN = 0.05;
const SKIP_SECONDS = 5;

function formatTime(t) {
  if (!Number.isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export class BuiltinAudioEditor extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    label: { type: String },
    editable: { type: Boolean, reflect: true },
    selection: { type: Object },
    playing: { type: Boolean, reflect: true },
    volume: { type: Number },
    playbackRate: { type: Number, attribute: "playback-rate" },
    loop: { type: Boolean },
    autoplay: { type: Boolean },
    downloadName: { type: String, attribute: "download-name" },
    _duration: { type: Number, state: true },
    _currentTime: { type: Number, state: true },
    _muted: { type: Boolean, state: true },
    _ready: { type: Boolean, state: true },
    _error: { type: String, state: true },
  };

  static styles = css`
    :host {
      display: block;
      --ae-orange: #f97316;
      --ae-orange-dark: #c2570c;
      --ae-card-bg: #ffffff;
      --ae-wave-bg: #f3f4f6;
      --ae-text: var(--builtin-color-text, #111827);
      --ae-muted: var(--builtin-color-muted, #6b7280);
      --ae-border: rgba(148, 163, 184, .25);
      color: var(--ae-text);
    }
    :host([data-builtin-theme="dark"]),
    :host-context([data-builtin-theme="dark"]) {
      --ae-card-bg: #1e293b;
      --ae-wave-bg: #0f172a;
      --ae-text: #e2e8f0;
      --ae-muted: #94a3b8;
      --ae-border: rgba(148, 163, 184, .2);
    }
    * { box-sizing: border-box; }

    .card {
      display: grid;
      gap: 12px;
      padding: 16px;
      border-radius: 12px;
      background: var(--ae-card-bg);
      border: 1px solid var(--ae-border);
      box-shadow: 0 1px 2px rgba(0, 0, 0, .04);
      color: var(--ae-text);
    }

    .header {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .header .title {
      flex: 1;
      min-width: 0;
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      font-size: 14px;
    }
    .header .title .name {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .header .actions {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      height: 26px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid var(--ae-border);
      background: rgba(148, 163, 184, .15);
      color: var(--ae-text);
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
    }
    .pill:hover { background: rgba(148, 163, 184, .25); }
    .pill.primary {
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      border-color: transparent;
    }
    .pill.primary:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .icon-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      padding: 0;
      border-radius: 8px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--ae-text);
      cursor: pointer;
    }
    .icon-btn:hover { background: rgba(148, 163, 184, .15); }
    .icon-btn:focus-visible {
      outline: 2px solid var(--builtin-primary, #2563eb);
      outline-offset: 1px;
    }

    .wave-area {
      position: relative;
      height: 88px;
      padding: 8px 10px 22px;
      border-radius: 8px;
      background: var(--ae-wave-bg);
      overflow: hidden;
    }
    .wave {
      width: 100%;
      height: 100%;
    }
    .time {
      position: absolute;
      bottom: 6px;
      font-size: 11px;
      font-variant-numeric: tabular-nums;
      color: var(--ae-muted);
      pointer-events: none;
    }
    .time.left { left: 10px; }
    .time.right { right: 10px; }
    .placeholder, .err {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      color: var(--ae-muted);
    }
    .err { color: #ef4444; }

    .controls {
      display: grid;
      grid-template-columns: auto 1fr auto;
      align-items: center;
      gap: 12px;
    }
    .controls .left,
    .controls .right {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }
    .controls .right { justify-content: flex-end; }
    .controls .center {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }
    .play-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      border: none;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      cursor: pointer;
      box-shadow: 0 2px 6px rgba(37, 99, 235, .35);
    }
    .play-btn:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .play-btn:disabled { opacity: .55; cursor: not-allowed; }
    .skip-btn {
      width: 40px;
      height: 40px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 50%;
      color: var(--ae-text);
      cursor: pointer;
    }
    .skip-btn:hover { background: rgba(148, 163, 184, .15); }
    .skip-btn:disabled { opacity: .4; cursor: not-allowed; }
  `;

  constructor() {
    super();
    this.src = "";
    this.label = "Audio";
    this.editable = false;
    this.selection = null;
    this.playing = false;
    this.volume = 1;
    this.playbackRate = 1;
    this.loop = false;
    this.autoplay = false;
    this.downloadName = "";
    this._duration = 0;
    this._currentTime = 0;
    this._muted = false;
    this._ready = false;
    this._error = "";
    this._ws = null;
    this._regions = null;
    this._region = null;
    this._waveRef = null;
    this._destroyed = false;
    this._onKeyDown = (e) => this._handleKeyDown(e);
    if (!this.hasAttribute("tabindex")) {
      this.setAttribute("tabindex", "0");
    }
  }

  connectedCallback() {
    super.connectedCallback();
    this.addEventListener("keydown", this._onKeyDown);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.removeEventListener("keydown", this._onKeyDown);
    this._destroyWavesurfer();
    this._destroyed = true;
  }

  firstUpdated() {
    this._waveRef = this.renderRoot.querySelector(".wave");
    this._initWavesurfer();
  }

  updated(changed) {
    if (changed.has("src") && this._ws) {
      this._loadSource();
    }
    if (changed.has("editable") && this._ws) {
      this._applyEditable();
    }
    if (changed.has("selection") && this._ws) {
      this._applySelection();
    }
    if (changed.has("volume") && this._ws) {
      this._ws.setVolume(this._muted ? 0 : Math.max(0, Math.min(1, this.volume)));
    }
    if (changed.has("playbackRate") && this._ws) {
      this._ws.setPlaybackRate(this.playbackRate, true);
    }
  }

  // ---- Public API ---------------------------------------------------------

  play() { this._ws?.play(); }
  pause() { this._ws?.pause(); }
  toggle() { this._ws?.playPause(); }
  seek(time) {
    if (!this._ws || !this._duration) return;
    const ratio = Math.max(0, Math.min(1, time / this._duration));
    this._ws.seekTo(ratio);
  }
  setRate(rate) { this.playbackRate = rate; }
  setVolume(v) { this.volume = v; this._muted = false; }

  // ---- WaveSurfer setup ---------------------------------------------------

  _initWavesurfer() {
    if (!this._waveRef || this._ws) return;
    const orange = "#f97316";
    const orangeDark = "#c2570c";
    this._ws = WaveSurfer.create({
      container: this._waveRef,
      waveColor: orange,
      progressColor: orangeDark,
      cursorColor: "rgba(255,255,255,.85)",
      cursorWidth: 1,
      barWidth: 2,
      barGap: 1,
      barRadius: 1,
      height: 72,
      normalize: true,
      interact: true,
      autoplay: false,
    });
    this._ws.on("ready", () => {
      this._ready = true;
      this._error = "";
      this._duration = this._ws.getDuration() || 0;
      this._ws.setVolume(this._muted ? 0 : this.volume);
      this._ws.setPlaybackRate(this.playbackRate, true);
      this._applyEditable();
      this._applySelection();
      if (this.autoplay) {
        this._ws.play().catch(() => { /* autoplay may be blocked */ });
      }
    });
    this._ws.on("play", () => { this.playing = true; this._emit("builtin-play"); });
    this._ws.on("pause", () => { this.playing = false; this._emit("builtin-pause"); });
    this._ws.on("finish", () => {
      if (this.loop) {
        this._ws.setTime(0);
        this._ws.play();
      } else {
        this.playing = false;
        this._emit("builtin-ended");
      }
    });
    this._ws.on("timeupdate", (t) => {
      this._currentTime = t || 0;
      this._emit("builtin-time-change", { time: this._currentTime });
    });
    this._ws.on("error", (err) => {
      this._error = String(err?.message || err || "Audio failed to load");
      this._ready = false;
      this._emit("builtin-error", { error: this._error });
    });
    // NOTE: do NOT call _loadSource() here. updated() will fire with the
    // initial `src` change and handle loading exactly once.
  }

  _destroyWavesurfer() {
    if (this._region) {
      try { this._region.remove(); } catch (_e) { /* noop */ }
      this._region = null;
    }
    if (this._ws) {
      try { this._ws.destroy(); } catch (_e) { /* noop */ }
      this._ws = null;
    }
    this._regions = null;
  }

  _loadSource() {
    if (!this._ws) return;
    this._ready = false;
    this._error = "";
    this._currentTime = 0;
    this._duration = 0;
    if (this._region) {
      try { this._region.remove(); } catch (_e) { /* noop */ }
      this._region = null;
    }
    if (!this.src) return;
    try {
      this._ws.load(this.src);
    } catch (err) {
      this._error = String(err?.message || err);
      this._emit("builtin-error", { error: this._error });
    }
  }

  _applyEditable() {
    if (!this._ws) return;
    if (this.editable && !this._regions) {
      this._regions = this._ws.registerPlugin(Regions.create());
      this._regions.enableDragSelection({
        color: "rgba(249, 115, 22, .25)",
      });
      this._regions.on("region-created", (region) => {
        // Keep only one region — replace any existing.
        if (this._region && this._region !== region) {
          try { this._region.remove(); } catch (_e) { /* noop */ }
        }
        this._region = region;
        this._syncRegionToSelection(region);
      });
      this._regions.on("region-updated", (region) => {
        if (region === this._region) this._syncRegionToSelection(region);
      });
      this._regions.on("region-removed", (region) => {
        if (region === this._region) {
          this._region = null;
          this.selection = null;
          this._emit("builtin-selection-change", null);
        }
      });
    }
    if (!this.editable && this._regions) {
      try {
        this._regions.clearRegions();
      } catch (_e) { /* noop */ }
      this._region = null;
      this.selection = null;
    }
  }

  _applySelection() {
    if (!this._ws || !this._regions || !this.editable) return;
    const sel = this.selection;
    if (!sel || !Number.isFinite(sel.start) || !Number.isFinite(sel.end) || sel.end <= sel.start) {
      if (this._region) {
        try { this._region.remove(); } catch (_e) { /* noop */ }
        this._region = null;
      }
      return;
    }
    const start = Math.max(0, sel.start);
    const end = Math.min(this._duration || sel.end, sel.end);
    if (this._region) {
      // Avoid feedback loops if the region already matches.
      if (Math.abs(this._region.start - start) < 1e-3 && Math.abs(this._region.end - end) < 1e-3) {
        return;
      }
      try {
        this._region.setOptions({ start, end });
        return;
      } catch (_e) { /* fall through and recreate */ }
      try { this._region.remove(); } catch (_e) { /* noop */ }
      this._region = null;
    }
    this._region = this._regions.addRegion({
      start,
      end,
      color: "rgba(249, 115, 22, .25)",
      drag: true,
      resize: true,
    });
  }

  _syncRegionToSelection(region) {
    if (!region) return;
    let { start, end } = region;
    if (end - start < REGION_MIN_LEN) end = start + REGION_MIN_LEN;
    const detail = { start, end };
    this.selection = detail;
    this._emit("builtin-selection-change", detail);
  }

  // ---- UI handlers --------------------------------------------------------

  _toggleMute() {
    this._muted = !this._muted;
    if (this._ws) this._ws.setVolume(this._muted ? 0 : this.volume);
  }

  _cycleRate() {
    const idx = RATE_OPTIONS.indexOf(this.playbackRate);
    const next = RATE_OPTIONS[(idx + 1) % RATE_OPTIONS.length] ?? 1;
    this.playbackRate = next;
  }

  _skip(deltaSeconds) {
    if (!this._ws || !this._duration) return;
    const target = Math.max(0, Math.min(this._duration, this._currentTime + deltaSeconds));
    this.seek(target);
  }

  _trim() {
    if (!this.editable || !this.selection) return;
    this._emit("builtin-trim", { ...this.selection });
  }

  _download() {
    if (!this.src) return;
    const a = document.createElement("a");
    a.href = this.src;
    a.download = this.downloadName || this._inferDownloadName();
    a.rel = "noopener";
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  _inferDownloadName() {
    try {
      const url = new URL(this.src, window.location.href);
      const tail = url.pathname.split("/").pop();
      return tail || "audio";
    } catch (_e) {
      return "audio";
    }
  }

  _handleKeyDown(e) {
    if (e.key !== " " && e.code !== "Space") return;
    // Only respond when the host element itself is focused.
    if (this.shadowRoot?.activeElement) return;
    e.preventDefault();
    this.toggle();
  }

  _emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, {
      detail,
      bubbles: true,
      composed: true,
    }));
  }

  // ---- Render -------------------------------------------------------------

  render() {
    const hasSel = !!(this.editable && this.selection);
    const playable = this._ready && !this._error;
    const totalLabel = formatTime(this._duration);
    const curLabel = formatTime(this._currentTime);
    return html`
      <div class="card">
        <div class="header">
          <div class="title">
            ${this._icon("audio", "outlined", 16)}
            <span class="name" title="${this.label || "Audio"}">${this.label || "Audio"}</span>
          </div>
          <div class="actions">
            ${hasSel ? html`
              <button class="pill primary" type="button" @click=${this._trim} title="Trim to selection">
                Trim
              </button>
            ` : ""}
            <button class="icon-btn" type="button"
                    @click=${this._download}
                    ?disabled=${!this.src}
                    title="Download">
              ${this._icon("download", "outlined", 16)}
            </button>
          </div>
        </div>

        <div class="wave-area">
          <div class="wave"></div>
          ${this._error ? html`<div class="err">${this._error}</div>` : ""}
          ${!this.src && !this._error ? html`<div class="placeholder">No audio</div>` : ""}
          <div class="time left">${curLabel}</div>
          <div class="time right">${totalLabel}</div>
        </div>

        <div class="controls">
          <div class="left">
            <button class="icon-btn" type="button" @click=${this._toggleMute}
                    title=${this._muted ? "Unmute" : "Mute"}>
              ${this._icon(this._muted ? "audio-muted" : "audio", "outlined", 18)}
            </button>
            <button class="pill" type="button" @click=${this._cycleRate} title="Playback speed">
              ${this.playbackRate}x
            </button>
          </div>
          <div class="center">
            <button class="skip-btn" type="button"
                    @click=${() => this._skip(-SKIP_SECONDS)}
                    ?disabled=${!playable}
                    title="Back 5s">
              ${this._icon("step-backward", "outlined", 18)}
            </button>
            <button class="play-btn" type="button"
                    @click=${() => this.toggle()}
                    ?disabled=${!playable}
                    title=${this.playing ? "Pause" : "Play"}>
              ${this._icon(this.playing ? "pause-circle" : "play-circle", "outlined", 24, "#ffffff")}
            </button>
            <button class="skip-btn" type="button"
                    @click=${() => this._skip(SKIP_SECONDS)}
                    ?disabled=${!playable}
                    title="Forward 5s">
              ${this._icon("step-forward", "outlined", 18)}
            </button>
          </div>
          <div class="right"></div>
        </div>
      </div>
    `;
  }
}

if (!customElements.get("builtin-audio-editor")) {
  customElements.define("builtin-audio-editor", BuiltinAudioEditor);
}
