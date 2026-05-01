/**
 * @fileoverview BuiltinAudioPlayer — Custom audio player web component.
 *
 * @element builtin-audio-player
 *
 * @attr {string} src — Audio URL
 * @attr {Object} playlist — JSON array [{title, artist, src}]
 * @attr {string} mode — `default` | `compact`
 * @attr {Object} labels — JSON object for i18n overrides
 *
 * @slot title — Override title display
 * @slot artist — Override artist display
 * @slot extra — Extra content below controls
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinAudioPlayer extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    playlist: { type: Object },
    mode: { type: String },
    title: { type: String },
    artist: { type: String },
    labels: { type: Object },
    _playing: { type: Boolean, state: true },
    _currentTime: { type: Number, state: true },
    _duration: { type: Number, state: true },
    _volume: { type: Number, state: true },
    _muted: { type: Boolean, state: true },
    _currentIndex: { type: Number, state: true },
    _showPlaylist: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      background: var(--builtin-surface, #ffffff);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      padding: 16px;
      color: var(--builtin-color-text, #111827);
    }
    .wrap.compact {
      padding: 10px 12px;
      border-radius: var(--builtin-radius, 6px);
    }
    .info {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
    }
    .meta { flex: 1; min-width: 0; }
    .title {
      font-weight: 650;
      font-size: 14px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .artist {
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .controls {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      min-height: 32px;
      min-width: 32px;
      padding: 0 8px;
      font-size: 13px;
    }
    .btn.primary {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
      min-height: 36px;
      min-width: 36px;
    }
    .btn:hover { opacity: 0.9; }
    .btn svg {
      width: 16px; height: 16px;
      stroke: currentColor; fill: none;
      stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;
    }
    .seek {
      flex: 1;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .seek input[type="range"] {
      flex: 1;
      cursor: pointer;
    }
    .time {
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      font-variant-numeric: tabular-nums;
      min-width: 90px;
      text-align: right;
    }
    .volume {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .volume input[type="range"] {
      width: 80px;
      cursor: pointer;
    }
    .playlist-toggle {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      color: var(--builtin-primary, #2563eb);
      background: none;
      border: none;
      cursor: pointer;
      padding: 4px 0;
    }
    .playlist {
      margin-top: 10px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      padding-top: 8px;
    }
    .playlist-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 8px;
      border-radius: var(--builtin-radius, 6px);
      cursor: pointer;
      font-size: 13px;
    }
    .playlist-item:hover {
      background: var(--builtin-row-hover-bg, #f9fafb);
    }
    .playlist-item.active {
      background: var(--builtin-primary-soft, #eff6ff);
      color: var(--builtin-primary, #2563eb);
      font-weight: 650;
    }
    .playlist-index {
      width: 20px;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
    }
    .extra { margin-top: 10px; }
    @media (max-width: 720px) {
      .wrap { padding: 12px; }
      .controls { gap: 8px; flex-wrap: wrap; }
      .btn { min-height: 44px; min-width: 44px; }
      .btn.primary { min-height: 48px; min-width: 48px; }
      .volume input[type="range"] { width: 60px; }
      .seek { width: 100%; order: 3; }
      .time { min-width: auto; }
    }
  `;

  constructor() {
    super();
    this.src = "";
    this.playlist = [];
    this.mode = "default";
    this.title = "";
    this.artist = "";
    this._playing = false;
    this._currentTime = 0;
    this._duration = 0;
    this._volume = 1;
    this._muted = false;
    this._currentIndex = 0;
    this._showPlaylist = false;
    this._audioRef = null;
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  get _audio() {
    if (!this._audioRef) {
      this._audioRef = this.shadowRoot.querySelector("audio");
    }
    return this._audioRef;
  }

  get _currentSrc() {
    const list = Array.isArray(this.playlist) ? this.playlist : [];
    if (list.length && this._currentIndex >= 0 && this._currentIndex < list.length) {
      return list[this._currentIndex].src;
    }
    return this.src || "";
  }

  get _currentTrack() {
    const list = Array.isArray(this.playlist) ? this.playlist : [];
    if (list.length && this._currentIndex >= 0 && this._currentIndex < list.length) {
      return list[this._currentIndex];
    }
    return null;
  }

  _formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  _onPlay() { this._playing = true; }
  _onPause() { this._playing = false; }
  _onTimeUpdate() { this._currentTime = this._audio?.currentTime || 0; }
  _onLoadedMetadata() { this._duration = this._audio?.duration || 0; }
  _onEnded() { this._next(); }
  _onVolumeChange() {
    const a = this._audio;
    if (!a) return;
    this._volume = a.volume;
    this._muted = a.muted;
  }

  _togglePlay() {
    const a = this._audio;
    if (!a) return;
    if (a.paused) a.play().catch(() => {});
    else a.pause();
  }

  _seek(e) {
    const a = this._audio;
    if (!a) return;
    a.currentTime = Number(e.target.value);
  }

  _setVolume(e) {
    const a = this._audio;
    if (!a) return;
    a.volume = Number(e.target.value);
    a.muted = false;
  }

  _toggleMute() {
    const a = this._audio;
    if (!a) return;
    a.muted = !a.muted;
  }

  _prev() {
    const list = Array.isArray(this.playlist) ? this.playlist : [];
    if (!list.length) return;
    this._currentIndex = this._currentIndex > 0 ? this._currentIndex - 1 : list.length - 1;
    this._playing = false;
    this.updateComplete.then(() => {
      this._audio?.play().catch(() => {});
    });
  }

  _next() {
    const list = Array.isArray(this.playlist) ? this.playlist : [];
    if (!list.length) return;
    this._currentIndex = this._currentIndex < list.length - 1 ? this._currentIndex + 1 : 0;
    this._playing = false;
    this.updateComplete.then(() => {
      this._audio?.play().catch(() => {});
    });
  }

  _selectTrack(index) {
    this._currentIndex = index;
    this._playing = false;
    this.updateComplete.then(() => {
      this._audio?.play().catch(() => {});
    });
  }

  render() {
    const mode = this.mode || "default";
    const track = this._currentTrack;
    const list = Array.isArray(this.playlist) ? this.playlist : [];
    const hasPlaylist = list.length > 0;

    return html`
      <div class="wrap ${classMap({ compact: mode === "compact" })}">
        <audio
          src="${this._currentSrc}"
          ?muted=${this._muted}
          .volume=${this._volume}
          @play=${this._onPlay}
          @pause=${this._onPause}
          @timeupdate=${this._onTimeUpdate}
          @loadedmetadata=${this._onLoadedMetadata}
          @ended=${this._onEnded}
          @volumechange=${this._onVolumeChange}
        ></audio>

        <div class="info">
          <div class="meta">
            <div class="title"><slot name="title">${this.title || track?.title || this._l("audio.unknownTitle", "Unknown title")}</slot></div>
            <div class="artist"><slot name="artist">${this.artist || track?.artist || ""}</slot></div>
          </div>
        </div>

        <div class="controls">
          ${hasPlaylist
            ? html`
              <button class="btn" @click=${this._prev} aria-label="${this._l("audio.previous", "Previous")}">
                <builtin-icon name="step-backward" size="20" variant="outlined"></builtin-icon>
              </button>
            `
            : null}

          <button class="btn primary" @click=${this._togglePlay} aria-label="${this._playing ? this._l("audio.pause", "Pause") : this._l("audio.play", "Play")}">
            ${this._playing
              ? html`<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>`
              : html`<svg viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`}
          </button>

          ${hasPlaylist
            ? html`
              <button class="btn" @click=${this._next} aria-label="${this._l("audio.next", "Next")}">
                <builtin-icon name="step-forward" size="20" variant="outlined"></builtin-icon>
              </button>
            `
            : null}

          <div class="seek">
            <input
              type="range"
              min="0"
              max="${this._duration || 0}"
              step="0.1"
              .value=${this._currentTime}
              @input=${this._seek}
              aria-label="${this._l("audio.seek", "Seek")}"
            />
            <span class="time">${this._formatTime(this._currentTime)} / ${this._formatTime(this._duration)}</span>
          </div>

          <div class="volume">
            <button class="btn" @click=${this._toggleMute} aria-label="${this._muted ? this._l("audio.unmute", "Unmute") : this._l("audio.mute", "Mute")}">
              ${this._muted || this._volume === 0
                ? html`<builtin-icon name="mute" size="20" variant="outlined"></builtin-icon>`
                : html`<builtin-icon name="sound" size="20" variant="outlined"></builtin-icon>`}
            </button>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              .value=${this._muted ? 0 : this._volume}
              @input=${this._setVolume}
              aria-label="${this._l("audio.volume", "Volume")}"
            />
          </div>
        </div>

        ${hasPlaylist
          ? html`
            <button class="playlist-toggle" @click=${() => { this._showPlaylist = !this._showPlaylist; }}>
              <builtin-icon name="unordered-list" size="20" variant="outlined"></builtin-icon>
              ${this._l("audio.playlist", "Playlist")} (${list.length})
            </button>
            ${this._showPlaylist
              ? html`
                <div class="playlist">
                  ${repeat(list, (t, i) => html`
                    <div class="playlist-item ${classMap({ active: i === this._currentIndex })}" @click=${() => this._selectTrack(i)}>
                      <span class="playlist-index">${i + 1}</span>
                      <span>${t.title || this._l("audio.unknownTitle", "Unknown title")}</span>
                      ${t.artist ? html`<span style="margin-left:auto;color:var(--builtin-color-muted,#6b7280);font-size:12px;">${t.artist}</span>` : null}
                    </div>
                  `)}
                </div>
              `
              : null}
          `
          : null}

        <div class="extra"><slot name="extra"></slot></div>
      </div>
    `;
  }
}
