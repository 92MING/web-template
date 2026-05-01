/**
 * @fileoverview BuiltinVideoEditor — Video editor timeline UI backed by wavesurfer.js Regions.
 *
 * @attr {string} src — Video URL.
 * @attr {number} duration — Video duration in seconds.
 * @attr {string} cuts — JSON array of {start, end, label}.
 * @attr {number} currentTime — Current playback time.
 * @attr {number} zoom — Timeline zoom level (1 = default).
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-cut-add — Detail: { start, end }.
 * @event builtin-cut-remove — Detail: { index }.
 * @event builtin-cut-update — Detail: { index, start, end }.
 * @event builtin-time-change — Detail: { time }.
 * @event builtin-play — Detail: {}.
 * @event builtin-pause — Detail: {}.
 */

import { BuiltinBaseElement, html, css } from "./lit-base.js";
import WaveSurfer from "../../vendor/wavesurfer/wavesurfer.esm.js";
import Regions from "../../vendor/wavesurfer/regions.esm.js";
import Timeline from "../../vendor/wavesurfer/timeline.esm.js";

export class BuiltinVideoEditor extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    audioSrc: { type: String, attribute: "audio-src" },
    duration: { type: Number },
    cuts: { type: Array },
    currentTime: { type: Number, attribute: "current-time" },
    zoom: { type: Number },
    labels: { type: Object },
    _playing: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .wrap { display: flex; flex-direction: column; gap: 10px; }
    .preview { position: relative; aspect-ratio: 16 / 9; background: #000; border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; display: flex; align-items: center; justify-content: center; }
    .preview video { width: 100%; height: 100%; object-fit: contain; }
    .play-btn {
      position: absolute; width: 56px; height: 56px; border-radius: 50%;
      background: rgba(0,0,0,0.55); color: #fff; border: 2px solid rgba(255,255,255,0.3);
      display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
    }
    .waveform-wrap {
      background: var(--builtin-header-bg, #f9fafb);
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      overflow: hidden;
    }
    .toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .toolbar button:not(.play-btn) {
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
    .toolbar button:not(.play-btn):hover {
      background: var(--builtin-header-bg, #f3f4f6);
      border-color: var(--builtin-primary, #2563eb);
      color: var(--builtin-primary, #2563eb);
    }
    .time { font-size: 13px; color: var(--builtin-color-muted, #6b7280); font-variant-numeric: tabular-nums; }
    @media (max-width: 720px) {
      .waveform-wrap { height: 60px; }
    }
  `;

  constructor() {
    super();
    this.src = "";
    this.duration = 0;
    this.cuts = [];
    this.currentTime = 0;
    this.zoom = 1;
    this.labels = {};
    this._playing = false;
    this._ws = null;
    this._regions = null;
    this._ignoreCutUpdates = false;
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._destroyWs();
  }

  _destroyWs() {
    if (this._cleanupVideoListeners) {
      this._cleanupVideoListeners();
      this._cleanupVideoListeners = null;
    }
    if (this._ws) {
      this._ws.destroy();
      this._ws = null;
      this._regions = null;
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
    if (changed.has("cuts") && this._regions && !this._ignoreCutUpdates) {
      this._syncCutsToRegions();
    }
    if (changed.has("zoom") && this._ws) {
      const base = 10;
      this._ws.zoom(base * Math.max(0.5, this.zoom || 1));
    }
  }

  _bindRegionEvents(region, idx) {
    region.on("update-end", () => {
      this.dispatchEvent(
        new CustomEvent("builtin-cut-update", {
          bubbles: true,
          composed: true,
          detail: {
            index: idx,
            start: region.start,
            end: region.end,
            label: region.content,
          },
        })
      );
    });
    region.on("dblclick", () => {
      region.remove();
      this.dispatchEvent(
        new CustomEvent("builtin-cut-remove", {
          bubbles: true,
          composed: true,
          detail: { index: idx },
        })
      );
    });
  }

  _syncCutsToRegions() {
    if (!this._regions) return;
    this._regions.clearRegions();
    (this.cuts || []).forEach((cut, i) => {
      const region = this._regions.addRegion({
        id: `cut-${i}`,
        start: cut.start,
        end: cut.end,
        color: "rgba(37,99,235,0.2)",
        content: cut.label || "",
        drag: true,
        resize: true,
      });
      this._bindRegionEvents(region, i);
    });
  }

  _initWs() {
    if (!this.src || !this.shadowRoot) return;
    const video = this.shadowRoot.querySelector("video");
    const container = this.shadowRoot.querySelector("#waveform");
    if (!video || !container) return;

    const setup = (dur) => {
      if (!dur || !this.shadowRoot) return;
      if (!this.duration) this.duration = dur;

      const ws = WaveSurfer.create({
        container,
        waveColor: "var(--builtin-border, #d1d5db)",
        progressColor: "var(--builtin-primary-soft, #93c5fd)",
        cursorColor: "var(--builtin-primary-hover, #1d4ed8)",
        cursorWidth: 2,
        url: this.audioSrc || this.src,
        height: 72,
        interact: false,
      });

      const regions = ws.registerPlugin(Regions.create());
      ws.registerPlugin(Timeline.create());

      ws.on("ready", () => {
        // Force timeline re-render now that wrapper has real dimensions
        ws.emit("redraw");
        this._syncCutsToRegions();
        if (this.zoom) {
          ws.zoom(10 * Math.max(0.5, this.zoom));
        }
      });

      ws.on("click", (relativeX) => {
        video.currentTime = relativeX * dur;
      });

      ws.on("error", (err) => {
        console.warn("VideoEditor wavesurfer error:", err);
      });

      // Sync video playback state to wavesurfer cursor
      const onTimeUpdate = () => {
        this.currentTime = video.currentTime;
        if (ws.renderer && dur) {
          ws.renderer.renderProgress(video.currentTime / dur, !video.paused);
        }
        this.dispatchEvent(
          new CustomEvent("builtin-time-change", {
            bubbles: true,
            composed: true,
            detail: { time: video.currentTime },
          })
        );
      };
      const onPlay = () => {
        this._playing = true;
        this.dispatchEvent(new CustomEvent("builtin-play", { bubbles: true }));
      };
      const onPause = () => {
        this._playing = false;
        this.dispatchEvent(new CustomEvent("builtin-pause", { bubbles: true }));
      };

      video.addEventListener("timeupdate", onTimeUpdate);
      video.addEventListener("play", onPlay);
      video.addEventListener("pause", onPause);
      video.addEventListener("ended", onPause);

      this._cleanupVideoListeners = () => {
        video.removeEventListener("timeupdate", onTimeUpdate);
        video.removeEventListener("play", onPlay);
        video.removeEventListener("pause", onPause);
        video.removeEventListener("ended", onPause);
      };

      this._ws = ws;
      this._regions = regions;
    };

    if (video.readyState >= 1 && video.duration) {
      setup(video.duration);
    } else {
      video.addEventListener("loadedmetadata", () => setup(video.duration), { once: true });
    }
  }

  _onPlayToggle() {
    const video = this.shadowRoot?.querySelector("video");
    if (!video) return;
    if (video.paused) {
      video.play();
    } else {
      video.pause();
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _fmt(t) {
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  _addCut() {
    const start = this.currentTime || 0;
    const end = Math.min(this.duration || 0, start + 5);
    if (this._regions) {
      const idx = (this.cuts || []).length;
      const region = this._regions.addRegion({
        id: `cut-${idx}`,
        start,
        end,
        color: "rgba(37,99,235,0.2)",
        content: `Cut ${idx + 1}`,
        drag: true,
        resize: true,
      });
      this._bindRegionEvents(region, idx);
    }
    this.dispatchEvent(
      new CustomEvent("builtin-cut-add", {
        bubbles: true,
        composed: true,
        detail: { start, end },
      })
    );
  }

  _splitAtPlayhead() {
    if (!this._regions || !this.duration) return;
    const t = this.currentTime || 0;
    const list = this._regions.getRegions();
    const target = list.find((r) => t > r.start && t < r.end);
    if (target) {
      const idx = parseInt(String(target.id).replace("cut-", ""), 10);
      if (!Number.isNaN(idx)) {
        const originalEnd = target.end;
        target.setOptions({ end: t });
        this.dispatchEvent(
          new CustomEvent("builtin-cut-update", {
            bubbles: true,
            composed: true,
            detail: { index: idx, start: target.start, end: t },
          })
        );
        const newIdx = idx + 1;
        const region = this._regions.addRegion({
          id: `cut-${newIdx}`,
          start: t,
          end: originalEnd,
          color: "rgba(37,99,235,0.2)",
          content: `Cut ${newIdx + 1}`,
          drag: true,
          resize: true,
        });
        this._bindRegionEvents(region, newIdx);
        this.dispatchEvent(
          new CustomEvent("builtin-cut-add", {
            bubbles: true,
            composed: true,
            detail: { start: t, end: originalEnd },
          })
        );
      }
    }
  }

  render() {
    const dur = Math.max(1, this.duration || 1);
    return html`
      <div class="wrap">
        <div class="preview">
          ${this.src
            ? html`<video
                src="${this.src}"
                preload="metadata"
                @ended="${() => {
                  this._playing = false;
                }}"
              ></video>`
            : ""}
          <button class="play-btn" @click="${this._onPlayToggle}">
            <builtin-icon
              name="${this._playing ? "pause" : "play-circle"}"
              size="28"
              variant="outlined"
            ></builtin-icon>
          </button>
        </div>
        <div class="toolbar">
          <button @click="${this._addCut}">${this._l("editor.addCut", "Add Cut")}</button>
          <button @click="${this._splitAtPlayhead}">${this._l("editor.split", "Split")}</button>
          <span class="time">${this._fmt(this.currentTime || 0)} / ${this._fmt(dur)}</span>
        </div>
        <div id="waveform" class="waveform-wrap"></div>
      </div>
    `;
  }
}
