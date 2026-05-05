import { BuiltinBaseElement, html, css, classMap } from "../lit-base.js";
import WaveSurfer from "../../../vendor/wavesurfer/wavesurfer.esm.js";

export class BuiltinAudioPlayer extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    playlist: { type: Object },
    mode: { type: String },
    title: { type: String },
    artist: { type: String },
    labels: { type: Object },
    showWaveform: { type: Boolean, attribute: "show-waveform" },
    showSpeed: { type: Boolean, attribute: "show-speed" },
    showLoop: { type: Boolean, attribute: "show-loop" },
    showDownload: { type: Boolean, attribute: "show-download" },
    loop: { type: Boolean },
    speed: { type: Number },
    _currentIndex: { type: Number, state: true },
    _playing: { type: Boolean, state: true },
    _currentTime: { type: Number, state: true },
    _duration: { type: Number, state: true },
    _volume: { type: Number, state: true },
    _showVolumePanel: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display:block; }
    * { box-sizing: border-box; }
    .wrap {
      display: grid;
      gap: 12px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 86%, transparent);
      border-radius: 16px;
      padding: 14px;
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
      gap: 12px;
      min-width: 0;
    }
    .meta-copy {
      min-width: 0;
      display: grid;
      gap: 2px;
    }
    .title {
      font-weight: 760;
      font-size: 1.05rem;
      line-height: 1.25;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .artist {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 0.85rem;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .meta-actions {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .play-state {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex: 0 0 auto;
      background: color-mix(in srgb, var(--builtin-color-muted, #6b7280) 76%, transparent);
    }
    .play-state.playing {
      background: #22c55e;
      box-shadow: 0 0 0 5px rgba(34, 197, 94, .12);
    }
    audio { display: none; }

    .player-body {
      display: grid;
      gap: 10px;
    }
    .track-row {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .track-time {
      font-size: 12px;
      font-variant-numeric: tabular-nums;
      color: var(--builtin-color-text, #111827);
      font-weight: 700;
      white-space: nowrap;
    }
    .track-time.total {
      color: var(--builtin-color-muted, #6b7280);
      font-weight: 600;
    }
    .waveform {
      min-height: 68px;
      border: 1px solid color-mix(in srgb, var(--builtin-border-soft, #e5e7eb) 92%, transparent);
      border-radius: 12px;
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 88%, transparent);
      overflow: hidden;
      padding: 4px;
    }
    input[type="range"] {
      width: 100%;
      min-width: 0;
      accent-color: var(--builtin-primary, #2563eb);
    }

    .control-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-width: 0;
    }
    .control-left,
    .control-right {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }
    .control-center {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .play-btn {
      width: 48px;
      height: 48px;
      border: 0;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, var(--builtin-primary, #2563eb), color-mix(in srgb, var(--builtin-primary, #2563eb) 76%, #60a5fa));
      color: #fff;
      cursor: pointer;
      flex: 0 0 auto;
      box-shadow: 0 10px 20px rgba(37, 99, 235, .22);
    }
    .play-btn:hover { background: var(--builtin-primary-hover, #1d4ed8); }

    .icon-btn,
    .download {
      width: 36px;
      height: 36px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      border-radius: 10px;
      background: color-mix(in srgb, var(--builtin-button-bg, #fff) 92%, transparent);
      color: var(--builtin-color-text, #111827);
      padding: 0;
      font: inherit;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      flex-shrink: 0;
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

    .volume-pop {
      position: relative;
    }
    .volume-panel {
      position: absolute;
      bottom: calc(100% + 8px);
      left: 50%;
      transform: translateX(-50%);
      width: 140px;
      padding: 10px 12px;
      border-radius: 12px;
      background: var(--builtin-surface, #fff);
      border: 1px solid var(--builtin-border, #d1d5db);
      box-shadow: 0 8px 24px rgba(15, 23, 42, .12);
      z-index: 10;
    }
    .volume-panel input[type="range"] {
      width: 100%;
    }

    .speed-btn {
      min-height: 32px;
      padding: 0 10px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      border-radius: 8px;
      background: transparent;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
    }
    .speed-btn.active {
      border-color: var(--builtin-primary, #2563eb);
      color: var(--builtin-primary, #2563eb);
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 8%, var(--builtin-surface, #fff));
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
      .wrap { padding: 12px; border-radius: 14px; }
      .control-bar { gap: 8px; }
      .control-left, .control-right { gap: 4px; }
      .control-center { gap: 8px; }
    }
  `;

  constructor() {
    super();
    this.playlist = [];
    this.mode = "default";
    this.showWaveform = false;
    this.showSpeed = false;
    this.showLoop = false;
    this.showDownload = false;
    this.loop = false;
    this.speed = 1;
    this._currentIndex = 0;
    this._playing = false;
    this._currentTime = 0;
    this._duration = 0;
    this._volume = 1;
    this._showVolumePanel = false;
    this._ws = null;
  }

  firstUpdated() {
    this._bindAudio();
    this._syncWaveform();
  }

  updated(changed) {
    if (changed.has("src") || changed.has("_currentIndex")) this._loadAudio();
    if (changed.has("showWaveform") || changed.has("src") || changed.has("_currentIndex")) {
      if (this.showWaveform) {
        this._destroyWaveform();
        this.updateComplete.then(() => this._syncWaveform());
      } else {
        this._destroyWaveform();
      }
    }
    if (changed.has("loop")) {
      const audio = this._audio();
      if (audio) audio.loop = this.loop;
    }
    if (changed.has("speed")) {
      const audio = this._audio();
      if (audio) audio.playbackRate = Number(this.speed) || 1;
    }
  }

  disconnectedCallback() {
    this._destroyWaveform();
    super.disconnectedCallback();
  }

  _audio() {
    return this.renderRoot.querySelector("audio");
  }

  _bindAudio() {
    const audio = this._audio();
    if (!audio) return;
    audio.volume = this._volume;
    audio.loop = this.loop;
    audio.playbackRate = Number(this.speed) || 1;
    audio.addEventListener("loadedmetadata", () => {
      this._duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    });
    audio.addEventListener("timeupdate", () => {
      this._currentTime = audio.currentTime || 0;
    });
    audio.addEventListener("play", () => {
      this._playing = true;
      this.dispatchEvent(new CustomEvent("builtin-play", { bubbles: true, composed: true }));
    });
    audio.addEventListener("pause", () => {
      this._playing = false;
      this.dispatchEvent(new CustomEvent("builtin-pause", { bubbles: true, composed: true }));
    });
    audio.addEventListener("ended", () => {
      this._playing = false;
      this._next();
    });
  }

  _loadAudio() {
    const audio = this._audio();
    if (!audio) return;
    audio.src = this._currentSrc();
    audio.loop = this.loop;
    audio.playbackRate = Number(this.speed) || 1;
    audio.load();
    this._currentTime = 0;
    this._duration = 0;
    this._destroyWaveform();
    this.updateComplete.then(() => this._syncWaveform());
  }

  _list() {
    return Array.isArray(this.playlist) ? this.playlist : [];
  }

  _current() {
    return this._list()[this._currentIndex] || {};
  }

  _currentSrc() {
    return this._current().src || this.src || "";
  }

  _select(index) {
    this._currentIndex = index;
    this.updateComplete.then(() => this._audio()?.play?.());
  }

  _next() {
    if (this._list().length && this._currentIndex < this._list().length - 1)
      this._select(this._currentIndex + 1);
  }

  _toggle() {
    const audio = this._audio();
    if (!audio) return;
    if (audio.paused) audio.play();
    else audio.pause();
  }

  _seek(event) {
    const audio = this._audio();
    if (!audio) return;
    audio.currentTime = Number(event.target.value) || 0;
    this._currentTime = audio.currentTime;
  }

  _seekBackward() {
    const audio = this._audio();
    if (!audio) return;
    audio.currentTime = Math.max(0, audio.currentTime - 10);
    this._currentTime = audio.currentTime;
  }

  _seekForward() {
    const audio = this._audio();
    if (!audio) return;
    const max = this._duration || audio.duration || Infinity;
    audio.currentTime = Math.min(max, audio.currentTime + 10);
    this._currentTime = audio.currentTime;
  }

  _setVolume(event) {
    const audio = this._audio();
    this._volume = Number(event.target.value);
    if (audio) audio.volume = this._volume;
  }

  _toggleVolumePanel() {
    this._showVolumePanel = !this._showVolumePanel;
  }

  _setSpeed(event) {
    this.speed = Number(event.target.value) || 1;
    const audio = this._audio();
    if (audio) audio.playbackRate = this.speed;
  }

  _cycleSpeed() {
    const values = [0.75, 1, 1.25, 1.5, 2];
    const current = values.findIndex((value) => Number(this.speed) === value);
    const next = values[(current + 1 + values.length) % values.length] || 1;
    this.speed = next;
    const audio = this._audio();
    if (audio) audio.playbackRate = this.speed;
  }

  _toggleLoop() {
    this.loop = !this.loop;
    const audio = this._audio();
    if (audio) audio.loop = this.loop;
  }

  _destroyWaveform() {
    this._ws?.destroy?.();
    this._ws = null;
  }

  _syncWaveform() {
    if (!this.showWaveform) return;
    this._destroyWaveform();
    const container = this.renderRoot.querySelector(".waveform");
    const audio = this._audio();
    if (!container || !audio || !this._currentSrc()) return;
    const dark = this._ptTheme === "dark";
    this._ws = WaveSurfer.create({
      container,
      media: audio,
      height: 60,
      normalize: true,
      barWidth: 2,
      barGap: 1,
      cursorWidth: 1,
      waveColor: dark ? "#64748b" : "#94a3b8",
      progressColor: dark ? "#60a5fa" : "#2563eb",
      cursorColor: dark ? "#f8fafc" : "#1d4ed8",
      interact: true,
    });
  }

  _formatTime(value) {
    const total = Math.max(0, Math.floor(Number(value) || 0));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  }

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
          <div class="meta-actions">
            ${this.showDownload && src
              ? html`<a class="download" href=${src} download title="Download" aria-label="Download"><builtin-icon name="download" size="16" variant="outlined"></builtin-icon></a>`
              : ""}
            <span class="play-state ${this._playing ? "playing" : ""}" aria-hidden="true"></span>
          </div>
        </div>

        <audio preload="metadata" src="${src}"></audio>

        <div class="player-body">
          ${this.showWaveform
            ? html`
              <div class="track-row">
                <span class="track-time">${this._formatTime(this._currentTime)}</span>
                <div class="waveform"></div>
                <span class="track-time total">${this._formatTime(this._duration)}</span>
              </div>
            `
            : html`
              <div class="track-row">
                <span class="track-time">${this._formatTime(this._currentTime)}</span>
                <input type="range" min="0" max="${this._duration || 0}" step="0.01" .value="${String(this._currentTime)}" @input=${this._seek}>
                <span class="track-time total">${this._formatTime(this._duration)}</span>
              </div>
            `}

          <div class="control-bar">
            <div class="control-left">
              <div class="volume-pop">
                <button class="icon-btn" type="button" @click=${this._toggleVolumePanel} aria-label="Volume">
                  <builtin-icon name=${this._volume > 0 ? "sound" : "muted"} size="16" variant="outlined"></builtin-icon>
                </button>
                ${this._showVolumePanel
                  ? html`
                    <div class="volume-panel">
                      <input type="range" min="0" max="1" step="0.01" .value="${String(this._volume)}" @input=${this._setVolume}>
                    </div>
                  `
                  : ""}
              </div>
              ${this.showSpeed
                ? html`<button type="button" class="speed-btn ${Number(this.speed) !== 1 ? "active" : ""}" @click=${this._cycleSpeed}>${this.speed}x</button>`
                : ""}
            </div>

            <div class="control-center">
              <button type="button" class="icon-btn" @click=${this._seekBackward} aria-label="Rewind 10s">
                <builtin-icon name="backward" size="18" variant="outlined"></builtin-icon>
              </button>
              <button class="play-btn" type="button" aria-label="${this._playing ? "Pause" : "Play"}" @click=${this._toggle}>
                ${this._playing
                  ? html`<builtin-icon name="pause" size="20" color="currentColor"></builtin-icon>`
                  : html`<builtin-icon name="play-circle" size="22" color="currentColor"></builtin-icon>`}
              </button>
              <button type="button" class="icon-btn" @click=${this._seekForward} aria-label="Forward 10s">
                <builtin-icon name="forward" size="18" variant="outlined"></builtin-icon>
              </button>
            </div>

            <div class="control-right">
              ${this.showLoop
                ? html`<button type="button" class="icon-btn ${this.loop ? "active" : ""}" title="Loop" aria-label="Loop" @click=${this._toggleLoop}><builtin-icon name="reload" size="16" variant="outlined"></builtin-icon></button>`
                : ""}
            </div>
          </div>
        </div>

        <slot name="extra"></slot>
        ${this._list().length
          ? html`
            <div class="playlist">
              ${this._list().map((entry, index) => html`
                <button class="${classMap({ active: index === this._currentIndex })}" @click=${() => this._select(index)}>
                  <span>${entry.title || entry.src}</span>
                  <span>${index === this._currentIndex ? "Now" : "Queue"}</span>
                </button>
              `)}
            </div>
          `
          : ""}
      </div>
    `;
  }
}
