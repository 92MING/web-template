import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

export class BuiltinVideoPlayer extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    poster: { type: String },
    title: { type: String },
    mode: { type: String },
    sources: { type: Array },
    tracks: { type: Array },
    showQuality: { type: Boolean, attribute: "show-quality" },
    showTransform: { type: Boolean, attribute: "show-transform" },
    showCaptions: { type: Boolean, attribute: "show-captions" },
    showLoop: { type: Boolean, attribute: "show-loop" },
    rotation: { type: Number },
    scale: { type: Number },
    labels: { type: Object },
    _sourceIndex: { type: Number, state: true },
    _videoMountVersion: { type: Number, state: true },
  };

  static styles = css`
    builtin-video-player { display: block; }
    builtin-video-player .wrap {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      overflow: hidden;
    }
    builtin-video-player .meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-header-bg, #f9fafb);
    }
    builtin-video-player .title {
      font-weight: 700;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    builtin-video-player .player-shell {
      position: relative;
      background: #020617;
      overflow: hidden;
    }
    builtin-video-player video,
    builtin-video-player .video-js {
      width: 100%;
      height: auto !important;
      aspect-ratio: 16 / 9;
      display: block;
      background: #020617;
    }
    builtin-video-player .video-js {
      font-size: 14px;
      --vjs-theme-main: var(--builtin-primary, #2563eb);
      --builtin-video-transform: rotate(0deg) scale(1);
    }
    builtin-video-player .video-js .vjs-tech {
      width: 100%;
      height: 100%;
      object-fit: contain;
      transform: var(--builtin-video-transform);
      transform-origin: center;
      transition: transform .18s ease;
    }
    builtin-video-player .video-js .vjs-big-play-button {
      border-color: rgba(255, 255, 255, 0.9);
      background: rgba(15, 23, 42, 0.72);
      border-radius: 999px;
    }
    builtin-video-player .video-js .vjs-control-bar {
      left: 16px;
      right: 16px;
      bottom: 12px;
      width: auto;
      height: 56px;
      align-items: center;
      gap: 4px;
      padding: 6px 8px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 999px;
      background: rgba(35, 40, 42, 0.76);
      box-shadow: 0 14px 38px rgba(0, 0, 0, 0.36);
      backdrop-filter: blur(18px);
    }
    builtin-video-player .video-js.vjs-controls-enabled .vjs-control-bar {
      display: flex;
      visibility: visible;
      opacity: 1;
    }
    builtin-video-player .video-js .vjs-control {
      width: 40px;
      height: 44px;
    }
    builtin-video-player .video-js .vjs-button > .vjs-icon-placeholder::before {
      line-height: 44px;
    }
    builtin-video-player .video-js .vjs-progress-control {
      flex: 1 1 auto;
      min-width: 72px;
    }
    builtin-video-player .video-js .vjs-current-time,
    builtin-video-player .video-js .vjs-duration,
    builtin-video-player .video-js .vjs-time-divider {
      display: block;
      width: auto;
      min-width: 0;
      padding-inline: 4px;
      color: #ffffff;
      line-height: 44px;
      font-size: 12px;
      font-weight: 700;
    }
    builtin-video-player .video-js .vjs-play-progress,
    builtin-video-player .video-js .vjs-volume-level,
    builtin-video-player .video-js .vjs-big-play-button:focus,
    builtin-video-player .video-js:hover .vjs-big-play-button {
      background-color: var(--builtin-primary, #2563eb);
    }
    builtin-video-player .video-js .vjs-subs-caps-button.builtin-hidden {
      display: none;
    }
    builtin-video-player .video-js .builtin-video-seek-controls,
    builtin-video-player .video-js .builtin-video-tools {
      display: flex;
      align-items: center;
      flex: 0 0 auto;
      width: auto !important;
      min-width: max-content;
      height: 100%;
      overflow: visible;
    }
    builtin-video-player .video-js .builtin-video-seek-controls[hidden],
    builtin-video-player .video-js .builtin-video-tools[hidden] {
      display: none;
    }
    builtin-video-player .video-js .builtin-video-seek-button,
    builtin-video-player .video-js .builtin-video-tools-menu-trigger {
      flex: 0 0 auto;
      width: 44px !important;
      min-width: 44px;
      padding: 0;
      color: #f8fafc;
      font-family: inherit;
      font-size: 12px;
      font-weight: 800;
      line-height: 1;
      letter-spacing: 0;
      text-transform: none;
      overflow: hidden;
      text-overflow: clip;
      white-space: nowrap;
    }
    builtin-video-player .video-js .builtin-video-seek-button {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: #ffffff;
    }
    builtin-video-player .video-js .builtin-video-seek-button svg {
      width: 24px;
      height: 24px;
      display: block;
    }
    builtin-video-player .video-js .builtin-video-seek-button .seek-label {
      position: absolute;
      left: 50%;
      top: 54%;
      transform: translate(-50%, -50%);
      font-size: 10px;
      font-weight: 900;
      line-height: 1;
    }
    builtin-video-player .builtin-video-seek-button:hover,
    builtin-video-player .builtin-video-seek-button:focus,
    builtin-video-player .builtin-video-tools-menu-trigger:hover,
    builtin-video-player .builtin-video-tools-menu-trigger:focus,
    builtin-video-player .builtin-video-tools-menu-trigger.is-active {
      color: #ffffff;
      text-shadow: 0 0 12px rgba(255, 255, 255, 0.38);
    }
    builtin-video-player .builtin-video-tools-menu-wrap {
      position: relative;
      display: flex;
      align-items: center;
      height: 100%;
    }
    builtin-video-player .builtin-video-tools-menu-trigger {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 40px;
      border-radius: 999px;
      background: transparent;
    }
    builtin-video-player .builtin-video-tools-menu-icon {
      position: relative;
      display: inline-block;
      width: 4px;
      height: 4px;
      color: currentColor;
      border-radius: 999px;
      background: currentColor;
      box-shadow: 0 -7px 0 currentColor, 0 7px 0 currentColor;
    }
    builtin-video-player .builtin-video-tools-menu {
      position: absolute;
      right: -6px;
      bottom: calc(100% + 10px);
      z-index: 20;
      display: grid;
      gap: 8px;
      width: min(268px, calc(100vw - 24px));
      max-height: min(360px, calc(100vh - 120px));
      overflow: auto;
      padding: 10px;
      border: 1px solid rgba(148, 163, 184, 0.22);
      border-radius: 14px;
      background: rgba(7, 12, 24, 0.94);
      box-shadow: 0 18px 50px rgba(0, 0, 0, 0.38);
      backdrop-filter: blur(16px);
    }
    builtin-video-player .builtin-video-tools-menu[hidden] {
      display: none;
    }
    builtin-video-player .builtin-video-tools-menu-section,
    builtin-video-player .builtin-video-tools-menu-grid {
      display: grid;
      gap: 6px;
    }
    builtin-video-player .builtin-video-tools-menu-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    builtin-video-player .builtin-video-tools-menu-title {
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(226, 232, 240, 0.72);
    }
    builtin-video-player .builtin-video-tools-menu-action {
      min-height: 32px;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 10px;
      background: rgba(15, 23, 42, 0.86);
      color: #f8fafc;
      padding: 0 10px;
      font: inherit;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
    }
    builtin-video-player .builtin-video-tools-menu-action-label,
    builtin-video-player .builtin-video-tools-menu-action-value {
      display: inline-flex;
      align-items: center;
      min-width: 0;
    }
    builtin-video-player .builtin-video-tools-menu-action-value {
      font-size: 11px;
      font-weight: 800;
      color: rgba(226, 232, 240, 0.72);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    builtin-video-player .builtin-video-tools-menu-action.is-active {
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 72%, white);
      background: var(--builtin-primary, #2563eb);
      color: #ffffff;
    }
    builtin-video-player .builtin-video-tools-menu-action.is-active .builtin-video-tools-menu-action-value {
      color: rgba(255, 255, 255, 0.92);
    }
    [data-builtin-theme="dark"] builtin-video-player .video-js .vjs-control-bar {
      background: rgba(35, 40, 42, 0.78);
    }
    @media (max-width: 720px) {
      builtin-video-player .video-js .vjs-control-bar {
        left: 10px;
        right: 10px;
        height: 52px;
      }
      builtin-video-player .video-js .vjs-current-time,
      builtin-video-player .video-js .vjs-duration,
      builtin-video-player .video-js .vjs-time-divider {
        display: none;
      }
      builtin-video-player .builtin-video-tools-menu {
        right: -8px;
        width: min(260px, calc(100vw - 20px));
      }
    }
  `;

  constructor() {
    super();
    this.src = "";
    this.poster = "";
    this.title = "";
    this.mode = "default";
    this.sources = [];
    this.tracks = [];
    this.showQuality = false;
    this.showTransform = false;
    this.showCaptions = false;
    this.showLoop = false;
    this.rotation = 0;
    this.scale = 1;
    this.labels = {};
    this._ready = false;
    this._sourceIndex = 0;
    this._captionsVisible = true;
    this._loopEnabled = false;
    this._videoMountVersion = 0;
    this._menuOpen = false;
    this._player = null;
    this._extraControls = {};
    this._restoreTime = 0;
    this._resumePlayback = false;
    this._detachedRepairVersion = -1;
    this._videoId = `builtin-video-player-${Math.random().toString(36).slice(2)}`;
    this._handleDocumentPointerDown = (event) => {
      if (!this._menuOpen) return;
      const tools = this.querySelector(".builtin-video-tools");
      if (tools?.contains(event.target)) return;
      this._setMenuOpen(false);
    };
  }

  createRenderRoot() { return this; }

  firstUpdated() {
    this._initPlayer();
  }

  updated(changed) {
    if (changed.has("_videoMountVersion")) {
      this._initPlayer();
      return;
    }
    if (changed.has("src") || changed.has("sources") || changed.has("tracks") || changed.has("_sourceIndex")) {
      this._resetPlayer();
      return;
    }
    if (changed.has("showCaptions") || changed.has("_captionsVisible")) {
      this._applyCaptionVisibility();
    }
    if (
      changed.has("showQuality")
      || changed.has("showTransform")
      || changed.has("showCaptions")
      || changed.has("showLoop")
      || changed.has("rotation")
      || changed.has("scale")
      || changed.has("_loopEnabled")
      || changed.has("_menuOpen")
    ) {
      this._applyVideoTransform();
      this._syncControlBarButtons();
    }
  }

  disconnectedCallback() {
    document.removeEventListener("pointerdown", this._handleDocumentPointerDown);
    this._destroyPlayer();
    super.disconnectedCallback();
  }

  _trackList() {
    return Array.isArray(this.tracks) ? this.tracks : [];
  }

  _sourceList() {
    const list = Array.isArray(this.sources) ? this.sources.filter((item) => item?.src) : [];
    return list.length ? list : (this.src ? [{ src: this.src, label: "Auto" }] : []);
  }

  _currentSource() {
    const sources = this._sourceList();
    return sources[this._sourceIndex] || sources[0] || { src: this.src || "" };
  }

  _scaleOptions() {
    return [0.75, 1, 1.25, 1.5];
  }

  _loopState() {
    return !!(this._player?.loop?.() ?? this.querySelector("video")?.loop ?? this._loopEnabled);
  }

  _hasOverflowMenu() {
    return (this.showQuality && this._sourceList().length > 1) || this.showTransform || this.showLoop;
  }

  async _initPlayer() {
    if (this._player) return;
    const restoreTime = this._restoreTime;
    const resumePlayback = this._resumePlayback;
    this._restoreTime = 0;
    this._resumePlayback = false;

    try {
      const videojs = await ensureVendor("videojs", {
        script: "/vendor/videojs/video.min.js",
        css: "/vendor/videojs/video-js.min.css",
        globalName: "videojs",
      });
      const video = this._ensureVideoElement();
      if (!video || !video.isConnected || this._player) return;
      videojs.getPlayer?.(this._videoElementId())?.dispose?.();
      this._player = videojs(video, {
        controls: true,
        preload: "auto",
        responsive: true,
        fluid: false,
        controlBar: {
          children: [
            "playToggle",
            "progressControl",
            "currentTimeDisplay",
            "timeDivider",
            "durationDisplay",
            "volumePanel",
            "subsCapsButton",
            "pictureInPictureToggle",
            "fullscreenToggle",
          ],
        },
      });
      this._player.ready(() => {
        this._ready = true;
        this._loopEnabled = this._loopState();
        if (restoreTime > 0) {
          try {
            this._player.currentTime(Math.min(restoreTime, this._player.duration() || restoreTime));
          } catch (_error) {
            // ignore seek errors while metadata is still settling
          }
        }
        this._applyCaptionVisibility();
        this._applyVideoTransform();
        requestAnimationFrame(() => {
          this._mountSeekButtons();
          this._mountControlBarButtons();
          this._syncControlBarButtons();
          this._schedulePlayerIntegrityCheck();
        });
        document.addEventListener("pointerdown", this._handleDocumentPointerDown);
        if (resumePlayback) this._player.play().catch(() => {});
      });
    } catch (error) {
      this._ready = false;
      this.dispatchEvent(new CustomEvent("builtin-error", { detail: { error }, bubbles: true, composed: true }));
    }
  }

  _destroyPlayer() {
    Object.values(this._extraControls).forEach((element) => element?.remove?.());
    this._extraControls = {};
    this._menuOpen = false;
    this._player?.dispose?.();
    this._player = null;
    this._ready = false;
  }

  _resetPlayer() {
    this._destroyPlayer();
    this._videoMountVersion += 1;
  }

  _schedulePlayerIntegrityCheck() {
    const version = this._videoMountVersion;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!this.isConnected || version !== this._videoMountVersion || !this._player) return;
        const playerElement = this._player.el?.();
        const visibleRoot = this.querySelector(".video-frame .video-js");
        if (playerElement?.isConnected && playerElement === visibleRoot) {
          this._detachedRepairVersion = -1;
          return;
        }
        if (this._detachedRepairVersion === version) return;
        this._detachedRepairVersion = version;
        this._resetPlayer();
      });
    });
  }

  _ensureVideoElement() {
    const frame = this.querySelector(".video-frame");
    if (!frame) return null;
    const existing = frame.querySelector("video");
    if (existing?.id === this._videoElementId()) return existing;

    frame.replaceChildren();
    const current = this._currentSource();
    const video = document.createElement("video");
    video.id = this._videoElementId();
    video.className = "video-js vjs-big-play-centered";
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.src = current.src || "";
    if (this.poster) video.setAttribute("poster", this.poster);
    for (const trackDef of this._trackList()) {
      const track = document.createElement("track");
      track.kind = trackDef.kind || "captions";
      track.label = trackDef.label || "Captions";
      track.srclang = trackDef.srclang || "en";
      track.src = trackDef.src || "";
      if (trackDef.default) track.default = true;
      video.append(track);
    }
    frame.append(video);
    return video;
  }

  _applyCaptionVisibility() {
    const visible = this.showCaptions && this._captionsVisible;
    for (const track of this._textTracks()) {
      if (!["captions", "subtitles"].includes(track.kind)) continue;
      track.mode = visible ? "showing" : "disabled";
    }
    const captionsButton = this._player?.controlBar?.subsCapsButton?.el?.();
    captionsButton?.classList.toggle("builtin-hidden", !(this.showCaptions && this._trackList().length));
  }

  _textTracks() {
    const fromPlayer = this._player?.textTracks?.();
    if (fromPlayer?.length !== undefined) {
      return Array.from({ length: fromPlayer.length }, (_value, index) => fromPlayer[index]).filter(Boolean);
    }
    return Array.from(this.querySelector("video")?.textTracks || []);
  }

  _setSource(index) {
    const video = this.querySelector("video");
    this._restoreTime = this._player?.currentTime?.() ?? video?.currentTime ?? 0;
    this._resumePlayback = !(this._player?.paused?.() ?? video?.paused ?? true);
    this._sourceIndex = Math.max(0, Math.min(this._sourceList().length - 1, Number(index) || 0));
  }

  _cycleSource() {
    const sources = this._sourceList();
    if (sources.length <= 1) return;
    this._setSource((this._sourceIndex + 1) % sources.length);
  }

  _setScale(value) {
    this.scale = Number(value) || 1;
  }

  _cycleScale() {
    const options = this._scaleOptions();
    const currentIndex = Math.max(0, options.indexOf(Number(this.scale) || 1));
    this._setScale(options[(currentIndex + 1) % options.length]);
  }

  _rotate(delta) {
    this.rotation = ((Number(this.rotation) || 0) + delta + 360) % 360;
  }

  _seekBy(delta) {
    if (!this._player) return;
    const duration = this._player.duration?.() || Number.POSITIVE_INFINITY;
    const currentTime = this._player.currentTime?.() || 0;
    const nextTime = Math.max(0, Math.min(duration, currentTime + delta));
    this._player.currentTime(nextTime);
    this._player.userActive?.(true);
  }

  _setCaptionsVisible(visible) {
    this._captionsVisible = !!visible;
    this._applyCaptionVisibility();
  }

  _toggleLoop() {
    const next = !this._loopState();
    this._player?.loop?.(next);
    const video = this.querySelector("video");
    if (video) video.loop = next;
    this._loopEnabled = next;
    this._syncControlBarButtons();
  }

  _toggleOverflowMenu() {
    if (!this._hasOverflowMenu()) return;
    this._setMenuOpen(!this._menuOpen);
  }

  _setMenuOpen(open) {
    this._menuOpen = !!open;
    if (this._menuOpen) this._player?.userActive?.(true);
    this._syncControlBarButtons();
  }

  _videoElementId() {
    return `${this._videoId}-${this._videoMountVersion}`;
  }

  _syncControlBarButtons() {
    if (!this._player) return;
    if (!this._hasOverflowMenu()) this._menuOpen = false;
    this._applyCaptionVisibility();
    this._renderControlBarTools();
  }

  _applyVideoTransform() {
    const transform = `rotate(${Number(this.rotation) || 0}deg) scale(${Number(this.scale) || 1})`;
    this._player?.el?.()?.style.setProperty("--builtin-video-transform", transform);
  }

  _mountControlBarButtons() {
    const controlBar = this._player?.controlBar?.el?.();
    if (!controlBar) return;
    if (this._extraControls.container?.isConnected) {
      this._renderControlBarTools();
      return;
    }

    const container = document.createElement("div");
    container.className = "vjs-control builtin-video-tools";
    const insertBefore = controlBar.querySelector(".vjs-subs-caps-button")
      || controlBar.querySelector(".vjs-picture-in-picture-control")
      || controlBar.querySelector(".vjs-fullscreen-control");
    controlBar.insertBefore(container, insertBefore || null);
    this._extraControls.container = container;
    this._renderControlBarTools();
  }

  _mountSeekButtons() {
    const controlBar = this._player?.controlBar?.el?.();
    if (!controlBar || this._extraControls.seekContainer?.isConnected) return;

    const container = document.createElement("div");
    container.className = "vjs-control builtin-video-seek-controls";
    container.append(
      this._createSeekButton({ direction: "backward", label: "10", title: "Seek backward 10 seconds", delta: -10 }),
      this._createSeekButton({ direction: "forward", label: "10", title: "Seek forward 10 seconds", delta: 10 }),
    );
    const playToggle = controlBar.querySelector(".vjs-play-control");
    playToggle?.after(container);
    if (!playToggle) controlBar.prepend(container);
    this._extraControls.seekContainer = container;
  }

  _createSeekButton({ direction, label, title, delta }) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `vjs-control vjs-button builtin-video-seek-button is-${direction}`;
    button.title = title;
    button.setAttribute("aria-label", title);
    button.innerHTML = `
      <svg viewBox="0 0 18 18" fill="none" aria-hidden="true" focusable="false">
        <path fill="currentColor" d="M1 9c0 2.21.895 4.21 2.343 5.657l1.414-1.414a6 6 0 1 1 8.956-7.956l-1.286 1.286a.25.25 0 0 0 .177.427h4.146a.25.25 0 0 0 .25-.25V2.604a.25.25 0 0 0-.427-.177l-1.438 1.438A8 8 0 0 0 1 9" />
      </svg>
      <span class="seek-label">${label}</span>
    `;
    if (direction === "backward") {
      button.querySelector("svg")?.style.setProperty("transform", "scaleX(-1)");
    }
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      this._seekBy(delta);
    });
    return button;
  }

  _renderControlBarTools() {
    const container = this._extraControls.container;
    if (!container) return;
    container.replaceChildren();
    container.hidden = !this._hasOverflowMenu();
    if (container.hidden) return;

    const menuWrap = document.createElement("div");
    menuWrap.className = "builtin-video-tools-menu-wrap";
    const menuTrigger = document.createElement("button");
    menuTrigger.type = "button";
    menuTrigger.className = `vjs-control vjs-button builtin-video-tools-menu-trigger ${this._menuOpen ? "is-active" : ""}`.trim();
    menuTrigger.title = "Player tools";
    menuTrigger.setAttribute("aria-label", "Player tools");
    menuTrigger.setAttribute("aria-haspopup", "menu");
    menuTrigger.setAttribute("aria-expanded", String(this._menuOpen));
    const menuIcon = document.createElement("span");
    menuIcon.className = "builtin-video-tools-menu-icon";
    menuIcon.setAttribute("aria-hidden", "true");
    menuTrigger.append(menuIcon);
    menuTrigger.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      this._toggleOverflowMenu();
    });

    const menu = document.createElement("div");
    menu.className = "builtin-video-tools-menu";
    menu.hidden = !this._menuOpen;
    for (const section of this._menuSections()) {
      const sectionElement = document.createElement("div");
      sectionElement.className = "builtin-video-tools-menu-section";
      const title = document.createElement("div");
      title.className = "builtin-video-tools-menu-title";
      title.textContent = section.title;
      const grid = document.createElement("div");
      grid.className = "builtin-video-tools-menu-grid";
      for (const item of section.items) {
        const itemButton = document.createElement("button");
        itemButton.type = "button";
        itemButton.className = `builtin-video-tools-menu-action ${item.active ? "is-active" : ""}`.trim();
        const itemLabel = document.createElement("span");
        itemLabel.className = "builtin-video-tools-menu-action-label";
        itemLabel.textContent = item.label;
        itemButton.append(itemLabel);
        if (item.value) {
          const itemValue = document.createElement("span");
          itemValue.className = "builtin-video-tools-menu-action-value";
          itemValue.textContent = item.value;
          itemButton.append(itemValue);
        }
        itemButton.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          this._runMenuAction(item.action);
        });
        grid.append(itemButton);
      }
      sectionElement.append(title, grid);
      menu.append(sectionElement);
    }
    menuWrap.append(menuTrigger, menu);
    container.append(menuWrap);
  }

  _runMenuAction(action) {
    action();
    this._setMenuOpen(false);
  }

  _menuSections() {
    const sections = [];
    if (this.showQuality && this._sourceList().length > 1) {
      sections.push({
        title: "Quality",
        items: this._sourceList().map((source, index) => ({
          label: source.label || source.quality || `${index + 1}`,
          active: index === this._sourceIndex,
          action: () => this._setSource(index),
        })),
      });
    }
    if (this.showTransform) {
      sections.push({
        title: "Rotate",
        items: [
          { label: "Left", value: "-90", action: () => this._rotate(-90) },
          { label: "Right", value: "+90", action: () => this._rotate(90) },
        ],
      });
      sections.push({
        title: "Zoom",
        items: this._scaleOptions().map((value) => ({
          label: `${value}x`,
          value: Number(this.scale) === value ? "Active" : "",
          active: Number(this.scale) === value,
          action: () => this._setScale(value),
        })),
      });
    }
    if (this.showLoop) {
      sections.push({
        title: "Playback",
        items: [{
          label: "Loop",
          value: this._loopState() ? "On" : "Off",
          active: this._loopState(),
          action: () => this._toggleLoop(),
        }],
      });
    }
    return sections;
  }

  render() {
    return html`
      <style>${this.constructor.styles.cssText}</style>
      <div class="wrap ${this.mode || "default"}">
        ${this.title ? html`<div class="meta"><div class="title">${this.title}</div></div>` : ""}
        <div class="player-shell">
          <div class="video-frame"></div>
        </div>
      </div>
    `;
  }
}
