import { BuiltinBaseElement, html, css, classMap } from "../lit-base.js";
import WaveSurfer from "../../../vendor/wavesurfer/wavesurfer.esm.js";

export class BuiltinAudioPlayer extends BuiltinBaseElement {
  static properties = {
    src: { type: String }, playlist: { type: Object }, mode: { type: String }, title: { type: String }, artist: { type: String }, labels: { type: Object },
    showWaveform: { type: Boolean, attribute: "show-waveform" }, showSpeed: { type: Boolean, attribute: "show-speed" }, showLoop: { type: Boolean, attribute: "show-loop" }, showDownload: { type: Boolean, attribute: "show-download" }, loop: { type: Boolean }, speed: { type: Number },
    _currentIndex: { type: Number, state: true }, _playing: { type: Boolean, state: true }, _currentTime: { type: Number, state: true }, _duration: { type: Number, state: true }, _volume: { type: Number, state: true },
  };
  static styles = css`
    :host { display:block; }
    * { box-sizing: border-box; }
    .wrap {
      display: grid;
      gap: 16px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 86%, transparent);
      border-radius: 20px;
      padding: 18px;
      background:
        radial-gradient(circle at top right, color-mix(in srgb, var(--builtin-primary, #2563eb) 14%, transparent), transparent 34%),
        linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 88%, var(--builtin-surface, #fff)), var(--builtin-surface, #fff));
      color: var(--builtin-color-text, #111827);
      overflow: hidden;
      box-shadow: 0 18px 40px rgba(15, 23, 42, .08);
    }
    .meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      min-width: 0;
    }
    .meta-copy {
      min-width: 0;
      display: grid;
      gap: 4px;
    }
    .title {
      font-weight: 760;
      font-size: 1.1rem;
      line-height: 1.2;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .artist {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 0.9rem;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .play-state {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      flex: 0 0 auto;
      background: color-mix(in srgb, var(--builtin-color-muted, #6b7280) 76%, transparent);
      box-shadow: 0 0 0 8px color-mix(in srgb, var(--builtin-border, #d1d5db) 18%, transparent);
    }
    .play-state.playing {
      background: #22c55e;
      box-shadow: 0 0 0 6px rgba(34, 197, 94, .12);
    }
    .panel {
      display: grid;
      gap: 12px;
      padding: 14px;
      border-radius: 18px;
      border: 1px solid color-mix(in srgb, var(--builtin-border-soft, #e5e7eb) 90%, transparent);
      background: color-mix(in srgb, var(--builtin-surface, #fff) 76%, var(--builtin-header-bg, #f9fafb));
    }
    .transport {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
      gap: 14px;
      min-width: 0;
    }
    .play-btn {
      width: 60px;
      height: 60px;
      border: 0;
      border-radius: 18px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, var(--builtin-primary, #2563eb), color-mix(in srgb, var(--builtin-primary, #2563eb) 76%, #60a5fa));
      color: #fff;
      cursor: pointer;
      flex: 0 0 auto;
      box-shadow: 0 14px 24px rgba(37, 99, 235, .24);
    }
    .play-btn:hover { background: var(--builtin-primary-hover, #1d4ed8); }
    .play-glyph {
      width: 0;
      height: 0;
      margin-left: 3px;
      border-top: 8px solid transparent;
      border-bottom: 8px solid transparent;
      border-left: 12px solid currentColor;
    }
    .scrub { min-width: 0; display: grid; gap: 8px; }
    .scrub-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .time {
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
      color: var(--builtin-color-text, #111827);
      font-weight: 700;
    }
    .time.total { color: var(--builtin-color-muted, #6b7280); font-weight: 600; }
    .seek { width: 100%; }
    input[type="range"] {
      width: 100%;
      min-width: 0;
      accent-color: var(--builtin-primary, #2563eb);
    }
    audio { display: none; }
    .transport-tail {
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      min-width: 28px;
    }
    .secondary {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 12px;
    }
    .volume-box {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      align-items: center;
      gap: 10px;
      min-width: 0;
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid color-mix(in srgb, var(--builtin-border-soft, #e5e7eb) 92%, transparent);
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 82%, transparent);
    }
    .volume-box builtin-icon {
      color: var(--builtin-color-muted, #6b7280);
    }
    .featurebar {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
    }
    .icon-btn,
    .download {
      width: 42px;
      height: 42px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      border-radius: 12px;
      background: color-mix(in srgb, var(--builtin-button-bg, #fff) 92%, transparent);
      color: var(--builtin-color-text, #111827);
      padding: 0;
      font: inherit;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .icon-btn:hover,
    .download:hover {
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 32%, transparent);
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 8%, var(--builtin-surface, #fff));
    }
    .icon-btn.active {
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 16%, var(--builtin-surface, #fff));
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 42%, transparent);
      color: var(--builtin-primary, #2563eb);
    }
    .waveform {
      min-height: 88px;
      border: 1px solid color-mix(in srgb, var(--builtin-border-soft, #e5e7eb) 92%, transparent);
      border-radius: 16px;
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 88%, transparent);
      overflow: hidden;
      padding: 4px;
    }
    .playlist { display: grid; gap: 8px; }
    .playlist button {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      text-align: left;
      min-height: 42px;
      padding: 0 14px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      border-radius: 14px;
      background: color-mix(in srgb, var(--builtin-button-bg, #fff) 92%, transparent);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
    }
    .playlist button.active {
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 12%, var(--builtin-surface, #fff));
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 44%, transparent);
      color: var(--builtin-primary, #2563eb);
    }
    @media (max-width: 520px) {
      .wrap { padding: 14px; border-radius: 16px; }
      .meta,
      .transport,
      .secondary { grid-template-columns: 1fr; }
      .meta { align-items: stretch; }
      .transport { gap: 10px; }
      .transport-tail { justify-content: flex-start; }
      .featurebar { justify-content: stretch; }
      .featurebar > * { flex: 0 0 auto; }
    }
  `;
  constructor() { super(); this.playlist = []; this.mode = "default"; this.showWaveform = false; this.showSpeed = false; this.showLoop = false; this.showDownload = false; this.loop = false; this.speed = 1; this._currentIndex = 0; this._playing = false; this._currentTime = 0; this._duration = 0; this._volume = 1; this._ws = null; }
  firstUpdated() { this._bindAudio(); this._syncWaveform(); }
  updated(changed) { if (changed.has("src") || changed.has("_currentIndex")) this._loadAudio(); if (changed.has("showWaveform") || changed.has("src") || changed.has("_currentIndex")) this.updateComplete.then(() => this._syncWaveform()); if (changed.has("loop")) { const audio = this._audio(); if (audio) audio.loop = this.loop; } if (changed.has("speed")) { const audio = this._audio(); if (audio) audio.playbackRate = Number(this.speed) || 1; } }
  disconnectedCallback() { this._destroyWaveform(); super.disconnectedCallback(); }
  _audio() { return this.renderRoot.querySelector("audio"); }
  _bindAudio() {
    const audio = this._audio();
    if (!audio) return;
    audio.volume = this._volume;
    audio.loop = this.loop;
    audio.playbackRate = Number(this.speed) || 1;
    audio.addEventListener("loadedmetadata", () => { this._duration = Number.isFinite(audio.duration) ? audio.duration : 0; });
    audio.addEventListener("timeupdate", () => { this._currentTime = audio.currentTime || 0; });
    audio.addEventListener("play", () => { this._playing = true; this.dispatchEvent(new CustomEvent("builtin-play", { bubbles: true, composed: true })); });
    audio.addEventListener("pause", () => { this._playing = false; this.dispatchEvent(new CustomEvent("builtin-pause", { bubbles: true, composed: true })); });
    audio.addEventListener("ended", () => { this._playing = false; this._next(); });
  }
  _loadAudio() { const audio = this._audio(); if (!audio) return; audio.src = this._currentSrc(); audio.loop = this.loop; audio.playbackRate = Number(this.speed) || 1; audio.load(); this._currentTime = 0; this._duration = 0; this._destroyWaveform(); this.updateComplete.then(() => this._syncWaveform()); }
  _list() { return Array.isArray(this.playlist) ? this.playlist : []; }
  _current() { return this._list()[this._currentIndex] || {}; }
  _currentSrc() { return this._current().src || this.src || ""; }
  _select(index) { this._currentIndex = index; this.updateComplete.then(() => this._audio()?.play?.()); }
  _next() { if (this._list().length && this._currentIndex < this._list().length - 1) this._select(this._currentIndex + 1); }
  _toggle() { const audio = this._audio(); if (!audio) return; if (audio.paused) audio.play(); else audio.pause(); }
  _seek(event) { const audio = this._audio(); if (!audio) return; audio.currentTime = Number(event.target.value) || 0; this._currentTime = audio.currentTime; }
  _setVolume(event) { const audio = this._audio(); this._volume = Number(event.target.value); if (audio) audio.volume = this._volume; }
  _setSpeed(event) { this.speed = Number(event.target.value) || 1; const audio = this._audio(); if (audio) audio.playbackRate = this.speed; }
  _cycleSpeed() {
    const values = [0.75, 1, 1.25, 1.5, 2];
    const current = values.findIndex((value) => Number(this.speed) === value);
    const next = values[(current + 1 + values.length) % values.length] || 1;
    this.speed = next;
    const audio = this._audio();
    if (audio) audio.playbackRate = this.speed;
  }
  _toggleLoop() { this.loop = !this.loop; const audio = this._audio(); if (audio) audio.loop = this.loop; }
  _destroyWaveform() { this._ws?.destroy?.(); this._ws = null; }
  _syncWaveform() {
    if (!this.showWaveform || this._ws) return;
    const container = this.renderRoot.querySelector(".waveform");
    const audio = this._audio();
    if (!container || !audio || !this._currentSrc()) return;
    const dark = this._ptTheme === "dark";
    this._ws = WaveSurfer.create({ container, media: audio, height: 68, normalize: true, barWidth: 2, barGap: 1, cursorWidth: 1, waveColor: dark ? "#64748b" : "#94a3b8", progressColor: dark ? "#60a5fa" : "#2563eb", cursorColor: dark ? "#f8fafc" : "#1d4ed8" });
  }
  _formatTime(value) { const total = Math.max(0, Math.floor(Number(value) || 0)); return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`; }
  render() {
    const item = this._current();
    const src = this._currentSrc();
    return html`
      <div class="wrap ${this.mode || "default"}">
        <div class="meta">
          <div class="meta-copy">
            <div class="title"><slot name="title">${item.title || this.title || ""}</slot></div>
            <div class="artist"><slot name="artist">${item.artist || this.artist || ""}</slot></div>
          </div>
          <span class="play-state ${this._playing ? "playing" : ""}" aria-hidden="true"></span>
        </div>
        <audio preload="metadata" src="${src}"></audio>
        <div class="panel">
          <div class="transport">
            <button class="play-btn" type="button" aria-label="${this._playing ? "Pause" : "Play"}" @click=${this._toggle}>
              ${this._playing
                ? html`<builtin-icon name="pause" size="22" color="currentColor"></builtin-icon>`
                : html`<builtin-icon name="play-circle" size="24" color="currentColor"></builtin-icon>`}
            </button>
            <div class="scrub">
              <div class="scrub-top">
                <span class="time">${this._formatTime(this._currentTime)}</span>
                <span class="time total">${this._formatTime(this._duration)}</span>
              </div>
              <input class="seek" type="range" min="0" max="${this._duration || 0}" step="0.01" .value="${String(this._currentTime)}" @input=${this._seek}>
            </div>
            <div class="transport-tail">
              <builtin-icon name=${this._playing ? "audio" : "pause-circle"} size="18" variant="outlined"></builtin-icon>
            </div>
          </div>
          ${this.showWaveform ? html`<div class="waveform"></div>` : ""}
          <div class="secondary">
            <div class="volume-box">
              <builtin-icon name=${this._volume > 0 ? "sound" : "muted"} size="16" variant="outlined"></builtin-icon>
              <input class="volume" type="range" min="0" max="1" step="0.01" .value="${String(this._volume)}" aria-label="Volume" @input=${this._setVolume}>
            </div>
            ${this.showSpeed || this.showLoop || this.showDownload ? html`
              <div class="featurebar">
                ${this.showSpeed ? html`<button type="button" class="icon-btn ${Number(this.speed) !== 1 ? "active" : ""}" title="Playback speed ${this.speed}x" aria-label="Playback speed ${this.speed}x" @click=${this._cycleSpeed}><builtin-icon name="dashboard" size="16" variant="outlined"></builtin-icon></button>` : ""}
                ${this.showLoop ? html`<button type="button" class="icon-btn ${this.loop ? "active" : ""}" title="Loop" aria-label="Loop" @click=${this._toggleLoop}><builtin-icon name="reload" size="16" variant="outlined"></builtin-icon></button>` : ""}
                ${this.showDownload && src ? html`<a class="download" href=${src} download title="Download" aria-label="Download"><builtin-icon name="download" size="16" variant="outlined"></builtin-icon></a>` : ""}
              </div>
            ` : html`<div></div>`}
          </div>
        </div>
        <slot name="extra"></slot>
        ${this._list().length ? html`
          <div class="playlist">
            ${this._list().map((entry, index) => html`
              <button class="${classMap({ active: index === this._currentIndex })}" @click=${() => this._select(index)}>
                <span>${entry.title || entry.src}</span>
                <span>${index === this._currentIndex ? "Now" : "Queue"}</span>
              </button>
            `)}
          </div>
        ` : ""}
      </div>
    `;
  }
}