/**
 * @fileoverview BuiltinVideoEditor — clean in-browser multi-track video editor
 * with a clean video preview and a real ffmpeg.wasm-based export pipeline.
 *
 * Layout (vertical, generous spacing):
 *   ┌──────────────────────────────────────────────────────┐
 *   │ Header: title                                [⬇ Export]│
 *   ├──────────────────────────────────────────────────────┤
 *   │              [   Video preview monitor ]              │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Inspector strip (only when a clip is selected)        │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Transport · Split · Add · Snap · Zoom · Time          │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Timeline (ruler + video/audio/text tracks, scrolls)   │
 *   └──────────────────────────────────────────────────────┘
 *
 * Export pipeline:
 *   - Lazy-imports `/vendor/ffmpeg/index.js` + `/vendor/ffmpeg/util.js` on click.
 *   - Loads ffmpeg-core.js + ffmpeg-core.wasm from /vendor/ffmpeg/.
 *   - For each clip on the `video` track (chronological), trims via `-ss/-t`,
 *     prefers `-c copy`; on failure re-encodes with libx264/aac.
 *   - Concats segments via the concat demuxer into output.mp4 and triggers
 *     a download. Audio/text tracks are ignored in v1 export.
 */

import { BuiltinBaseElement, html, css, nothing } from "../lit-base.js";

// ---------- constants ----------

const TRACK_TYPE_DEFS = [
  { id: "video", label: "Video", height: 44, color: "#3b82f6" },
  { id: "audio", label: "Audio", height: 36, color: "#22c55e" },
  { id: "text", label: "Text", height: 32, color: "#a855f7" },
];
const DEFAULT_TRACKS = [
  { id: "video", type: "video", label: "Video" },
  { id: "audio", type: "audio", label: "Audio" },
];
const SOURCE_VIDEO_ASSET_ID = "source-video";
const SOURCE_AUDIO_ASSET_ID = "source-audio";
const TRACK_HEADER_W = 108;
const RULER_H = 24;
const ZOOM_MIN = 20;
const ZOOM_MAX = 500;
const SNAP_GRID = 0.1;
const SNAP_THRESHOLD_PX = 8;
const TIMELINE_TAIL = 5;
const VIDEO_FILE_EXTENSIONS = new Set(["mp4", "webm", "mov", "m4v", "ogg", "ogv", "mkv"]);
const AUDIO_FILE_EXTENSIONS = new Set(["mp3", "wav", "ogg", "oga", "m4a", "aac", "flac", "webm"]);

// ---------- helpers ----------

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

function uid(prefix = "clip") {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function fmtTime(sec) {
  const v = Math.max(0, Number(sec) || 0);
  const m = Math.floor(v / 60);
  const s = Math.floor(v % 60);
  const t = Math.floor((v % 1) * 10);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${t}`;
}

function trackTypeDef(type) {
  return TRACK_TYPE_DEFS.find((t) => t.id === type) || TRACK_TYPE_DEFS[0];
}

function snapValue(value, candidates, threshold) {
  let best = value;
  let bestDiff = threshold;
  for (const c of candidates) {
    const d = Math.abs(value - c);
    if (d < bestDiff) { bestDiff = d; best = c; }
  }
  return best;
}

function mediaTypeFromFile(file) {
  const mime = String(file?.type || "").toLowerCase();
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  const ext = String(file?.name || "").toLowerCase().split(".").pop() || "";
  if (VIDEO_FILE_EXTENSIONS.has(ext)) return "video";
  if (AUDIO_FILE_EXTENSIONS.has(ext)) return "audio";
  return "";
}

// ---------- component ----------

export class BuiltinVideoEditor extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    audioSrc: { type: String, attribute: "audio-src" },
    duration: { type: Number },
    assets: { type: Array },
    tracks: { type: Array },
    cuts: { type: Array },
    currentTime: { type: Number, attribute: "current-time" },
    zoom: { type: Number },
    snap: { type: Boolean },
    labels: { type: Object },
    downloadName: { type: String, attribute: "download-name" },
    title: { type: String },
    _playing: { type: Boolean, state: true },
    _selection: { type: Array, state: true },
    _focusId: { type: String, state: true },
    _menu: { type: Object, state: true },
    _trackMenu: { type: Object, state: true },
    _selectedTrackId: { type: String, state: true },
    _drag: { type: Object, state: true },
    _assetDrag: { type: Object, state: true },
    _dropTarget: { type: String, state: true },
    _assetsCollapsed: { type: Boolean, state: true },
    _assetPreviewRatio: { type: Number, state: true },
    _speedDialog: { type: Object, state: true },
    _exportState: { type: Object, state: true },
  };

  static styles = css`
    :host {
      display: block;
      --ve-playhead: #ef4444;
      --ve-pad: 16px;
      --ve-gap: 12px;
      --ve-asset-max-width: 420px;
      --ve-radius: var(--builtin-radius-lg, 10px);
      --ve-radius-sm: var(--builtin-radius, 6px);
      --ve-border: var(--builtin-border, #e2e8f0);
      --ve-border-soft: var(--builtin-border-soft, #eef0f3);
      --ve-surface: var(--builtin-surface, #ffffff);
      --ve-muted: var(--builtin-color-muted, #6b7280);
      --ve-text: var(--builtin-color-text, #111827);
      --ve-primary: var(--builtin-primary, #2563eb);
      --ve-section-bg: var(--builtin-header-bg, #f8fafc);
    }

    .wrap {
      display: flex;
      flex-direction: column;
      gap: var(--ve-gap);
      padding: var(--ve-pad);
      border: 1px solid var(--ve-border);
      border-radius: var(--ve-radius);
      background: var(--ve-surface);
      color: var(--ve-text);
    }

    /* --- header --- */
    .header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .header .title { margin: 0; font-size: 15px; font-weight: 600; color: var(--ve-text); }
    .header .actions { display: flex; align-items: center; gap: 8px; }

    .btn {
      display: inline-flex; align-items: center; gap: 6px;
      min-height: 32px; padding: 0 12px;
      border: 1px solid var(--ve-border);
      border-radius: var(--ve-radius-sm);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--ve-text);
      font: inherit; font-size: 12px; font-weight: 500;
      cursor: pointer;
      transition: background .12s, border-color .12s, color .12s;
    }
    .btn:hover:not([disabled]) { background: var(--builtin-button-hover-bg, #f3f4f6); border-color: var(--ve-primary); }
    .btn[disabled] { opacity: .45; cursor: not-allowed; }
    .btn.icon-only { padding: 0; width: 32px; justify-content: center; }
    .btn.primary { background: var(--ve-primary); border-color: var(--ve-primary); color: #ffffff; }
    .btn.primary:hover:not([disabled]) { background: color-mix(in srgb, var(--ve-primary) 88%, black); border-color: color-mix(in srgb, var(--ve-primary) 88%, black); }

    .export-pill {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 10px; min-height: 26px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--ve-primary) 14%, transparent);
      color: var(--ve-primary);
      font-size: 11px; font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .export-pill.error { background: color-mix(in srgb, #ef4444 14%, transparent); color: #b91c1c; }
    .spinner {
      width: 12px; height: 12px;
      border: 2px solid currentColor; border-right-color: transparent;
      border-radius: 50%;
      animation: ve-spin .8s linear infinite;
    }
    @keyframes ve-spin { to { transform: rotate(360deg); } }

    /* --- preview --- */
    .preview {
      position: relative;
      width: 100%; margin: 0;
      aspect-ratio: 16 / 9;
      background: #000;
      border-radius: var(--ve-radius-sm);
      overflow: hidden;
    }
    .preview video { display: block; width: 100%; height: 100%; object-fit: contain; transform-origin: 50% 50%; }
    .preview.empty { display: flex; align-items: center; justify-content: center; color: rgba(255,255,255,.72); font-size: 12px; }
    .preview-workspace {
      display: grid;
      grid-template-columns: minmax(180px, min(var(--ve-asset-pane, 33.333%), var(--ve-asset-max-width))) 8px minmax(0, 1fr);
      gap: 0;
      align-items: stretch;
    }
    .preview-workspace > .asset-bin { min-width: 0; }
    .preview-stage { min-width: 0; }
    .split-handle {
      align-self: stretch;
      min-height: 220px;
      width: 8px;
      border: 0;
      border-radius: 999px;
      background: color-mix(in srgb, var(--ve-border) 70%, transparent);
      cursor: col-resize;
      padding: 0;
      touch-action: none;
      transition: background .12s, box-shadow .12s;
    }
    .split-handle:hover, .split-handle.active {
      background: var(--ve-primary);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--ve-primary) 18%, transparent);
    }
    .preview-stage { display: grid; grid-template-columns: minmax(0, 1fr) 42px; gap: 8px; align-items: stretch; }
    .preview-tools {
      display: flex; flex-direction: column; align-items: center; gap: 6px;
      padding: 6px;
      border: 1px solid var(--ve-border-soft);
      border-radius: var(--ve-radius-sm);
      background: var(--ve-section-bg);
    }
    .preview-tools .tool-btn {
      display: inline-flex; align-items: center; justify-content: center;
      width: 30px; height: 30px; padding: 0;
      border: 1px solid transparent; border-radius: var(--ve-radius-sm);
      background: transparent; color: var(--ve-muted); cursor: pointer;
    }
    .preview-tools .tool-btn:hover, .preview-tools .tool-btn.active {
      border-color: var(--ve-primary);
      color: var(--ve-primary);
      background: color-mix(in srgb, var(--ve-primary) 10%, transparent);
    }
    .preview-overlay { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
    .text-layer {
      position: absolute;
      left: 50%; top: 50%;
      transform: translate(-50%, -50%);
      color: #ffffff;
      font-weight: 700;
      text-shadow: 0 2px 8px rgba(0,0,0,.55);
      white-space: pre-wrap;
      text-align: center;
      max-width: 88%;
    }
    .audio-monitor {
      position: fixed;
      left: -1px;
      top: -1px;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
    }

    .asset-bin {
      box-sizing: border-box;
      position: relative;
      display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 8px;
      padding: 10px;
      max-width: var(--ve-asset-max-width);
      height: 100%;
      min-height: 0;
      overflow: hidden;
      border: 1px solid var(--ve-border-soft);
      border-radius: var(--ve-radius-sm);
      background: var(--ve-section-bg);
    }
    .asset-bin.drag-over { border-color: var(--ve-primary); background: color-mix(in srgb, var(--ve-primary) 8%, var(--ve-section-bg)); }
    .asset-bin.drag-invalid { border-color: #ef4444; background: color-mix(in srgb, #ef4444 8%, var(--ve-section-bg)); }
    .asset-bin-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .asset-bin-title { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--ve-text); }
    .asset-bin-title button {
      display: inline-flex; align-items: center; justify-content: center;
      width: 22px; height: 22px; padding: 0;
      border: 1px solid transparent; border-radius: 4px;
      background: transparent; color: var(--ve-muted); cursor: pointer;
    }
    .asset-bin-title button:hover { border-color: var(--ve-border); background: var(--ve-surface); color: var(--ve-primary); }
    .asset-list {
      position: absolute;
      inset: 50px 10px 10px;
      display: grid;
      align-content: start;
      gap: 6px;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 2px;
      border: 1px dashed transparent;
      border-radius: var(--ve-radius-sm);
    }
    .asset-list.drag-over { border-color: var(--ve-primary); background: color-mix(in srgb, var(--ve-primary) 6%, transparent); }
    .asset-list.drag-invalid { border-color: #ef4444; background: color-mix(in srgb, #ef4444 6%, transparent); }
    .asset-chip {
      box-sizing: border-box;
      display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; align-items: center; gap: 7px;
      min-height: 34px; width: 100%;
      padding: 0 10px;
      border: 1px solid var(--ve-border);
      border-radius: var(--ve-radius-sm);
      background: var(--ve-surface);
      color: var(--ve-text);
      cursor: grab;
      font-size: 12px;
    }
    .asset-chip:active { cursor: grabbing; }
    .asset-chip .asset-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .asset-chip .asset-meta { color: var(--ve-muted); font-size: 11px; }

    /* --- inspector strip --- */
    .inspector {
      display: flex; align-items: center; flex-wrap: wrap;
      gap: 10px;
      padding: 8px 12px;
      border: 1px solid var(--ve-border-soft);
      border-radius: var(--ve-radius-sm);
      background: var(--ve-section-bg);
      font-size: 12px;
    }
    .inspector .tag { color: var(--ve-muted); font-weight: 500; }
    .inspector .name { font-weight: 600; color: var(--ve-text); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .inspector .name input {
      background: transparent; border: 1px solid transparent; color: inherit; font: inherit; font-weight: 600;
      padding: 2px 4px; border-radius: 4px; max-width: 160px;
    }
    .inspector .name input:focus, .inspector .name input:hover { border-color: var(--ve-border); background: var(--ve-surface); outline: none; }
    .inspector .times { color: var(--ve-muted); font-variant-numeric: tabular-nums; }
    .inspector .spacer { flex: 1; }
    .inspector-control { display: inline-flex; align-items: center; gap: 6px; color: var(--ve-muted); }
    .inspector-control input[type="number"] { width: 68px; }
    .inspector-control input[type="range"] { width: 86px; accent-color: var(--ve-primary); }
    .inspector-control input[type="color"] { width: 28px; height: 24px; padding: 0; border: 1px solid var(--ve-border); border-radius: 4px; background: transparent; }
    .inspector-text { flex: 1 1 220px; min-width: 180px; }
    .inspector-text textarea {
      width: 100%; min-height: 32px; max-height: 80px;
      resize: vertical;
      border: 1px solid var(--ve-border);
      border-radius: var(--ve-radius-sm);
      background: var(--ve-surface);
      color: var(--ve-text);
      font: inherit;
      padding: 5px 7px;
    }

    /* --- transport / toolbar --- */
    .toolbar {
      display: grid;
      gap: 8px;
    }
    .toolbar-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
    .toolbar .group { display: inline-flex; align-items: center; gap: 4px; }
    .toolbar .time { font-variant-numeric: tabular-nums; color: var(--ve-muted); font-size: 12px; padding: 0 4px; }
    .toolbar .spacer { flex: 1; }
    .toolbar input[type="range"] { width: 100px; accent-color: var(--ve-primary); }
    .toolbar label.snap { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ve-muted); cursor: pointer; user-select: none; }

    /* --- timeline --- */
    .timeline-wrap {
      border: 1px solid var(--ve-border-soft);
      border-radius: var(--ve-radius-sm);
      background: var(--ve-surface);
      overflow: hidden;
    }
    .timeline-scroll { position: relative; overflow-x: auto; overflow-y: hidden; }
    .timeline-grid { position: relative; }

    .ruler {
      position: sticky; top: 0;
      height: ${RULER_H}px;
      background: var(--ve-section-bg);
      border-bottom: 1px solid var(--ve-border-soft);
      z-index: 5; user-select: none;
    }
    .ruler .header-cell {
      position: absolute; left: 0; top: 0; bottom: 0; width: ${TRACK_HEADER_W}px;
      box-sizing: border-box;
      background: var(--ve-section-bg);
      border-right: 1px solid var(--ve-border-soft);
      display: flex; align-items: center; padding: 0 10px;
      font-size: 10px; color: var(--ve-muted); text-transform: uppercase; letter-spacing: .04em;
      z-index: 2;
    }
    .ruler .ticks {
      position: absolute; left: ${TRACK_HEADER_W}px; right: 0; top: 0; bottom: 0;
      cursor: pointer;
      font-variant-numeric: tabular-nums; font-size: 10px; color: var(--ve-muted);
    }
    .ruler .tick { position: absolute; top: 0; bottom: 0; border-left: 1px solid var(--ve-border-soft); }
    .ruler .tick.major { border-left-color: var(--ve-border); }
    .ruler .tick label { position: absolute; left: 4px; top: 4px; }

    .track { position: relative; border-bottom: 1px solid var(--ve-border-soft); }
    .track:last-of-type { border-bottom: none; }
    .track .label {
      position: absolute; left: 0; top: 0; bottom: 0; width: ${TRACK_HEADER_W}px;
      box-sizing: border-box;
      background: var(--ve-section-bg);
      border-right: 1px solid var(--ve-border-soft);
      display: flex; align-items: center; justify-content: space-between; gap: 4px; padding: 0 6px 0 10px;
      font-size: 11px; font-weight: 600; color: var(--ve-muted);
      z-index: 2;
    }
    .track .label-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .inspector-volume { display: inline-flex; align-items: center; gap: 6px; color: var(--ve-muted); }
    .inspector-volume input { width: 90px; accent-color: var(--ve-primary); }
    .track.selected .label { color: var(--ve-primary); background: color-mix(in srgb, var(--ve-primary) 10%, var(--ve-section-bg)); }
    .track .lane { position: absolute; left: ${TRACK_HEADER_W}px; top: 0; bottom: 0; }
    .track.drop-target .lane { outline: 2px solid var(--ve-primary); outline-offset: -2px; }

    .clip {
      position: absolute; top: 4px; bottom: 4px;
      border-radius: 4px;
      cursor: grab; overflow: hidden; user-select: none;
      transition: filter .12s, outline-color .12s;
      display: flex; align-items: center;
      padding: 0 8px;
      font-size: 11px; font-weight: 500; color: #ffffff;
    }
    .clip:hover { filter: brightness(1.06); }
    .clip.dragging { cursor: grabbing; filter: brightness(1.1); z-index: 10; }
    .clip.selected { outline: 2px solid var(--ve-primary); outline-offset: 1px; }
    .clip .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none; flex: 1; }
    .clip .handle {
      position: absolute; top: 0; bottom: 0; width: 5px;
      cursor: ew-resize; background: rgba(0,0,0,.18);
    }
    .clip .handle.left { left: 0; }
    .clip .handle.right { right: 0; }
    .clip .handle:hover { background: rgba(0,0,0,.32); }

    .playhead {
      position: absolute; top: 0; bottom: 0; width: 2px;
      background: var(--ve-playhead);
      pointer-events: none; z-index: 20;
    }
    .playhead .grip {
      position: absolute; top: -2px; left: -5px; width: 12px; height: 12px;
      background: var(--ve-playhead); border-radius: 50%;
      cursor: ew-resize; pointer-events: auto;
    }

    .ctxmenu {
      position: fixed; z-index: 1000; min-width: 160px;
      background: var(--ve-surface); color: var(--ve-text);
      border: 1px solid var(--ve-border); border-radius: var(--ve-radius-sm);
      box-shadow: 0 10px 24px rgba(0,0,0,.18);
      padding: 4px; font-size: 12px;
    }
    .ctxmenu button {
      display: flex; width: 100%; padding: 6px 10px;
      background: none; border: none; color: inherit;
      text-align: left; cursor: pointer; border-radius: 4px; font: inherit;
    }
    .ctxmenu button:hover { background: var(--builtin-button-hover-bg, #f3f4f6); }
    .ctxmenu hr { border: none; border-top: 1px solid var(--ve-border-soft); margin: 4px 2px; }

    .dialog-backdrop {
      position: fixed;
      inset: 0;
      z-index: 1100;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      background: rgba(0,0,0,.42);
    }
    .dialog-panel {
      width: min(360px, 100%);
      border: 1px solid var(--ve-border);
      border-radius: var(--ve-radius);
      background: var(--ve-surface);
      color: var(--ve-text);
      box-shadow: 0 18px 48px rgba(0,0,0,.25);
      padding: 14px;
      display: grid;
      gap: 12px;
    }
    .dialog-title { font-size: 14px; font-weight: 650; }
    .dialog-field { display: grid; gap: 6px; color: var(--ve-muted); font-size: 12px; }
    .dialog-field input {
      min-height: 34px;
      border: 1px solid var(--ve-border);
      border-radius: var(--ve-radius-sm);
      background: var(--builtin-input-bg, #ffffff);
      color: var(--ve-text);
      padding: 0 9px;
      font: inherit;
    }
    .dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }

    :host([data-builtin-theme="dark"]) .clip .handle { background: rgba(255,255,255,.18); }
    :host([data-builtin-theme="dark"]) .clip .handle:hover { background: rgba(255,255,255,.32); }
    @media (max-width: 720px) {
      .preview-workspace { grid-template-columns: 1fr; }
      .preview-workspace > .asset-bin, .preview-stage { margin: 0; }
      .asset-bin { height: auto; min-height: 220px; }
      .asset-list { position: relative; inset: auto; max-height: 230px; }
      .split-handle { display: none; }
      .preview-stage { grid-template-columns: 1fr; }
      .preview-tools { flex-direction: row; }
    }
  `;

  constructor() {
    super();
    this.src = "";
    this.audioSrc = "";
    this.duration = 0;
    this.assets = [];
    this.tracks = [];
    this.cuts = [];
    this.currentTime = 0;
    this.zoom = 80;
    this.snap = true;
    this.labels = {};
    this.downloadName = "video-edit-export.mp4";
    this.title = "";
    this._playing = false;
    this._selection = [];
    this._focusId = "";
    this._menu = null;
    this._trackMenu = null;
    this._selectedTrackId = "video";
    this._drag = null;
    this._assetDrag = null;
    this._dropTarget = "";
    this._assetsCollapsed = false;
    this._assetPreviewRatio = 1 / 3;
    this._speedDialog = null;
    this._exportState = { state: "idle", progress: 0, message: "" };
    this._video = null;
    this._audio = null;
    this._audioContext = null;
    this._audioGain = null;
    this._audioElementSource = null;
    this._audioMixers = new Map();
    this._scroller = null;
    this._ffmpeg = null;
    this._seededSrc = "";
    this._previewClipId = "";
    this._audioClipId = "";
    this._previewTool = "select";
    this._previewDrag = null;
    this._clipboardCuts = [];
    this._raf = 0;
    this._playStartMs = 0;
    this._playStartTime = 0;
    this._syncingMedia = false;
    this._videoEventsBound = false;
    this._onVideoLoadedMetadata = null;
    this._pendingMediaPlay = { video: false, audio: false };
    this._onKeyDown = this._handleKey.bind(this);
    this._onWindowPointerMove = this._onPointerMove.bind(this);
    this._onWindowPointerUp = this._onPointerUp.bind(this);
    this._onDocClick = this._closeMenu.bind(this);
    this._onWheel = this._handleWheel.bind(this);
  }

  // ---- lifecycle ----

  connectedCallback() {
    super.connectedCallback();
    this.tabIndex = this.tabIndex || 0;
    this.addEventListener("keydown", this._onKeyDown);
    window.addEventListener("pointermove", this._onWindowPointerMove);
    window.addEventListener("pointerup", this._onWindowPointerUp);
    document.addEventListener("click", this._onDocClick);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.removeEventListener("keydown", this._onKeyDown);
    window.removeEventListener("pointermove", this._onWindowPointerMove);
    window.removeEventListener("pointerup", this._onWindowPointerUp);
    document.removeEventListener("click", this._onDocClick);
    this._scroller?.removeEventListener("wheel", this._onWheel);
    cancelAnimationFrame(this._raf);
    this._audio?.pause?.();
    this._stopAudioSource();
    try { this._audioContext?.close?.(); } catch (_e) { /* noop */ }
    this._audioContext = null;
    this._audioGain = null;
    this._destroyPlayer();
    try { this._ffmpeg?.terminate?.(); } catch (_e) { /* noop */ }
    this._ffmpeg = null;
  }

  firstUpdated() {
    this._audio = this.renderRoot.querySelector(".audio-monitor");
    this._initPlayer();
    this._scroller = this.renderRoot.querySelector(".timeline-scroll");
    this._scroller?.addEventListener("wheel", this._onWheel, { passive: false });
  }

  updated(changed) {
    if (changed.has("src") && this.hasUpdated) {
      this._seededSrc = "";
      this._destroyPlayer();
      requestAnimationFrame(() => this._initPlayer());
    }
    if (changed.has("zoom")) {
      this.dispatchEvent(new CustomEvent("builtin-zoom-change", { detail: { zoom: this.zoom }, bubbles: true, composed: true }));
    }
  }

  // ---- preview media ----

  async _initPlayer() {
    if (!this.src) return;
    const video = this.renderRoot.querySelector(".preview video");
    if (!video) return;
    this._video = video;
    video.controls = false;
    video.muted = true;
    if (this._videoEventsBound) return;
    this._onVideoLoadedMetadata = () => {
      if (!this.duration || this.duration <= 0) this.duration = video.duration || 0;
      this._maybeSeedSourceClips();
      this._syncPreviewToTimeline(false, true);
    };
    video.addEventListener("loadedmetadata", this._onVideoLoadedMetadata);
    this._videoEventsBound = true;
    if (this.src && !video.currentSrc) video.src = this.src;
    if (video.readyState >= 1) this._onVideoLoadedMetadata();
    requestAnimationFrame(() => this._maybeSeedSourceClips());
  }

  _destroyPlayer() {
    if (this._video && this._videoEventsBound) {
      this._video.removeEventListener("loadedmetadata", this._onVideoLoadedMetadata);
    }
    this._videoEventsBound = false;
    this._video = null;
  }

  // ---- public API ----

  play() {
    if (this._playing) return;
    const dur = this._effectiveDuration();
    if (dur > 0 && this.currentTime >= dur - 0.02) this.currentTime = 0;
    this._playing = true;
    this._playStartMs = performance.now();
    this._playStartTime = this.currentTime;
    this._syncPreviewToTimeline(true, true);
    this._tickPlayback();
    this.dispatchEvent(new CustomEvent("builtin-play", { bubbles: true, composed: true }));
  }
  pause() {
    if (!this._playing) return;
    this._playing = false;
    cancelAnimationFrame(this._raf);
    this._pauseMedia();
    this.dispatchEvent(new CustomEvent("builtin-pause", { bubbles: true, composed: true }));
  }
  seek(time) {
    const dur = this._effectiveDuration();
    const t = clamp(Number(time) || 0, 0, dur || time || 0);
    this.currentTime = t;
    if (this._playing) {
      this._playStartMs = performance.now();
      this._playStartTime = t;
    }
    this._syncPreviewToTimeline(this._playing, true);
    this._autoScroll();
    this.dispatchEvent(new CustomEvent("builtin-time-change", { detail: { time: t }, bubbles: true, composed: true }));
  }

  _tickPlayback() {
    if (!this._playing) return;
    const dur = this._effectiveDuration();
    const nextTime = this._playStartTime + (performance.now() - this._playStartMs) / 1000;
    if (nextTime >= dur) {
      this.currentTime = dur;
      this._syncPreviewToTimeline(false, true);
      this.pause();
      this.dispatchEvent(new CustomEvent("builtin-time-change", { detail: { time: dur }, bubbles: true, composed: true }));
      return;
    }
    this.currentTime = nextTime;
    this._syncPreviewToTimeline(true);
    this._autoScroll();
    this.dispatchEvent(new CustomEvent("builtin-time-change", { detail: { time: nextTime }, bubbles: true, composed: true }));
    this._raf = requestAnimationFrame(() => this._tickPlayback());
  }

  _pauseMedia() {
    this._syncingMedia = true;
    this._video?.pause?.();
    this._stopAudioSource();
    this._syncingMedia = false;
  }

  _syncPreviewToTimeline(shouldPlay, forceSeek = false) {
    const activeVideo = this._activeClipAt("video", this.currentTime);
    const activeAudio = this._activeClipsAt("audio", this.currentTime);
    this._syncVideoClip(activeVideo, shouldPlay, forceSeek);
    this._syncAudioClips(activeAudio, shouldPlay, forceSeek);
  }

  _seekMedia(media, sourceTime, force = false) {
    if (!Number.isFinite(sourceTime)) return;
    const apply = () => {
      const threshold = force ? 0.02 : 0.45;
      if (Math.abs((media.currentTime || 0) - sourceTime) > threshold) {
        try { media.currentTime = sourceTime; } catch (_e) { /* metadata may still be loading */ }
      }
    };
    if (media.readyState >= 1) apply();
    else media.addEventListener("loadedmetadata", apply, { once: true });
  }

  _requestMediaPlay(media, kind) {
    if (!media || !media.paused || this._pendingMediaPlay[kind]) return;
    this._pendingMediaPlay[kind] = true;
    const finish = () => { this._pendingMediaPlay[kind] = false; };
    const promise = media.play?.();
    if (!promise?.then) { finish(); return; }
    promise.then(finish).catch((error) => {
      finish();
      if (error?.name === "AbortError") return;
      this.dispatchEvent(new CustomEvent("builtin-media-play-error", {
        detail: { kind, message: error?.message || String(error) },
        bubbles: true,
        composed: true,
      }));
    });
  }

  _ensureAudioContext() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) throw new Error("Web Audio is not available");
    if (!this._audioContext) {
      this._audioContext = new AudioCtx();
    }
    return this._audioContext;
  }

  _stopAudioSource() {
    this._audio?.pause?.();
    for (const mixer of this._audioMixers.values()) {
      mixer.audio.pause();
    }
  }

  _removeAudioMixer(clipId) {
    const mixer = this._audioMixers.get(clipId);
    if (!mixer) return;
    mixer.audio.pause();
    mixer.audio.removeAttribute("src");
    mixer.audio.load();
    try { mixer.source.disconnect(); } catch (_e) { /* noop */ }
    try { mixer.gain.disconnect(); } catch (_e) { /* noop */ }
    mixer.audio.remove();
    this._audioMixers.delete(clipId);
  }

  _mixerForClip(clip, asset) {
    const context = this._ensureAudioContext();
    let mixer = this._audioMixers.get(clip.id);
    const assetSrc = new URL(asset.src, document.baseURI).href;
    if (!mixer) {
      const audio = document.createElement("audio");
      audio.preload = "metadata";
      audio.className = "audio-monitor";
      audio.muted = false;
      audio.volume = 1;
      const source = context.createMediaElementSource(audio);
      const gain = context.createGain();
      source.connect(gain);
      gain.connect(context.destination);
      this.renderRoot.appendChild(audio);
      mixer = { audio, source, gain, src: "" };
      this._audioMixers.set(clip.id, mixer);
    }
    if (mixer.src !== assetSrc) {
      mixer.audio.src = asset.src;
      mixer.src = assetSrc;
    }
    return mixer;
  }

  _syncVideoClip(clip, shouldPlay, forceSeek = false) {
    const video = this._video;
    if (!video) return;
    if (!clip) {
      if (this._previewClipId || video.currentSrc) {
        this._previewClipId = "";
        this._syncingMedia = true;
        video.pause();
        video.style.visibility = "hidden";
        video.removeAttribute("src");
        video.load();
        this._syncingMedia = false;
      }
      return;
    }
    const asset = this._assetById(clip.assetId);
    if (!asset?.src) return;
    const sourceTime = this._clipSourceTime(clip, this.currentTime);
    const clipChanged = this._previewClipId !== clip.id || video.currentSrc !== new URL(asset.src, document.baseURI).href;
    this._syncingMedia = true;
    if (clipChanged) {
      video.src = asset.src;
      this._previewClipId = clip.id;
    }
    video.style.visibility = "visible";
    this._seekMedia(video, sourceTime, forceSeek || clipChanged);
    video.muted = true;
    video.playbackRate = clamp(Number(clip.speed) || 1, 0.1, 8);
    video.style.transform = `translate(${Number(clip.x) || 0}px, ${Number(clip.y) || 0}px) scale(${clamp(Number(clip.scale) || 1, 0.1, 5)})`;
    video.style.filter = `hue-rotate(${Number(clip.hue) || 0}deg) saturate(${clamp(Number(clip.saturation) || 100, 0, 300)}%) brightness(${clamp(Number(clip.brightness) || 100, 0, 300)}%)`;
    if (shouldPlay) this._requestMediaPlay(video, "video");
    else video.pause();
    this._syncingMedia = false;
  }

  _syncAudioClips(clips, shouldPlay, forceSeek = false) {
    const activeIds = new Set((clips || []).map((clip) => clip.id));
    for (const id of [...this._audioMixers.keys()]) {
      if (!activeIds.has(id)) this._removeAudioMixer(id);
    }
    if (!clips?.length) return;
    let context = null;
    try {
      context = this._ensureAudioContext();
    } catch (error) {
      this.dispatchEvent(new CustomEvent("builtin-media-play-error", {
        detail: { kind: "audio", message: error?.message || String(error) },
        bubbles: true,
        composed: true,
      }));
      return;
    }
    for (const clip of clips) {
      const asset = this._assetById(clip.assetId);
      if (!asset?.src) continue;
      const mixer = this._mixerForClip(clip, asset);
      const sourceTime = this._clipSourceTime(clip, this.currentTime);
      const volume = clamp(Number(clip.volume ?? 1), 0, 1);
      mixer.audio.playbackRate = clamp(Number(clip.speed) || 1, 0.1, 8);
      mixer.gain.gain.setValueAtTime(volume, context.currentTime);
      this._seekMedia(mixer.audio, sourceTime, forceSeek);
      if (shouldPlay) {
        context.resume().catch((error) => {
          this.dispatchEvent(new CustomEvent("builtin-media-play-error", {
            detail: { kind: "audio-context", message: error?.message || String(error) },
            bubbles: true,
            composed: true,
          }));
        });
        this._requestMediaPlay(mixer.audio, `audio:${clip.id}`);
      } else {
        mixer.audio.pause();
      }
    }
  }
  getCuts() { return [...(this.cuts || [])]; }
  setCuts(arr) {
    this.cuts = Array.isArray(arr) ? arr.map((c) => this._normalizeCut(c)) : [];
    this._setSelection(this._selection.filter((id) => this.cuts.some((c) => c.id === id)));
    this._emitCuts();
  }
  addClip(partial = {}) {
    const dur = this._effectiveDuration() || 1;
    const asset = partial.assetId ? this._assetById(partial.assetId) : null;
    const assetLen = Math.max(0.1, Number(asset?.duration) || dur || 1);
    const sourceStart = Math.max(0, Number(partial.sourceStart ?? partial.sourceIn ?? 0) || 0);
    const defaultLen = Math.min(2, assetLen - sourceStart, dur || assetLen);
    const start = Math.max(0, Number(partial.start ?? this.currentTime) || 0);
    const requestedEnd = Number(partial.end ?? start + defaultLen) || (start + 1);
    const end = clamp(requestedEnd, start + 0.1, Math.max(dur, requestedEnd));
    const clip = this._normalizeCut({ ...partial, start, end, sourceStart, sourceEnd: sourceStart + (end - start) });
    this.cuts = [...(this.cuts || []), clip];
    this.dispatchEvent(new CustomEvent("builtin-cut-add", { detail: { clip }, bubbles: true, composed: true }));
    this._emitCuts();
    this._setSelection([clip.id]);
    return clip;
  }
  splitAt(time) {
    const t = Number.isFinite(time) ? time : this.currentTime;
    const targets = (this._selection.length ? this._selection : (this.cuts || []).map((c) => c.id))
      .map((id) => (this.cuts || []).find((c) => c.id === id))
      .filter((c) => c && t > c.start + 0.05 && t < c.end - 0.05);
    if (!targets.length) return;
    const next = [];
    for (const c of (this.cuts || [])) {
      if (targets.includes(c)) {
        const splitSource = this._clipSourceTime(c, t);
        next.push({ ...c, end: t, sourceEnd: splitSource });
        next.push({ ...c, id: uid("clip"), start: t, sourceStart: splitSource, label: `${c.label || "Clip"} (b)` });
      } else {
        next.push(c);
      }
    }
    this.cuts = next;
    this.dispatchEvent(new CustomEvent("builtin-cut-split", { detail: { time: t, cuts: this.cuts }, bubbles: true, composed: true }));
    this._emitCuts();
  }
  deleteClip(id) {
    const ids = Array.isArray(id) ? id : [id];
    for (const cid of ids) {
      this.cuts = (this.cuts || []).filter((c) => c.id !== cid);
      this.dispatchEvent(new CustomEvent("builtin-cut-remove", { detail: { id: cid }, bubbles: true, composed: true }));
    }
    this._setSelection(this._selection.filter((s) => !ids.includes(s)));
    this._emitCuts();
  }
  addTrack(type = "video", afterTrackId = "") {
    const def = trackTypeDef(type);
    const track = { id: uid(def.id), type: def.id, label: def.label, height: def.height, color: def.color, volume: def.id === "audio" ? 1 : undefined };
    const tracks = this._trackList();
    const index = tracks.findIndex((item) => item.id === afterTrackId);
    const next = tracks.slice();
    next.splice(index >= 0 ? index + 1 : next.length, 0, track);
    this.tracks = next;
    this.dispatchEvent(new CustomEvent("builtin-track-add", { detail: { track }, bubbles: true, composed: true }));
    return track;
  }
  setTrackVolume(trackId, volume) {
    const value = clamp(Number(volume), 0, 1);
    this.cuts = (this.cuts || []).map((clip) => clip.track === trackId && this._clipType(clip) === "audio" ? { ...clip, volume: value } : clip);
    this.dispatchEvent(new CustomEvent("builtin-track-volume-change", { detail: { trackId, volume: value }, bubbles: true, composed: true }));
    this._emitCuts();
  }

  updateClip(id, patch = {}) {
    let nextClip = null;
    this.cuts = (this.cuts || []).map((clip) => {
      if (clip.id !== id) return clip;
      nextClip = this._normalizeCut({ ...clip, ...patch });
      return nextClip;
    });
    if (nextClip) {
      this._syncPreviewToTimeline(this._playing, true);
      this._emitCuts();
    }
    return nextClip;
  }

  setClipVolume(id, volume) {
    const value = clamp(Number(volume), 0, 1);
    const mixer = this._audioMixers.get(id);
    if (mixer && this._audioContext) mixer.gain.gain.setValueAtTime(value, this._audioContext.currentTime);
    return this.updateClip(id, { volume: value });
  }

  setClipSpeed(id, speed) {
    const clip = (this.cuts || []).find((item) => item.id === id);
    if (!clip || !["video", "audio"].includes(this._clipType(clip))) return null;
    const value = clamp(Number(speed) || 1, 0.1, 8);
    const sourceLength = Math.max(0.1, (Number(clip.sourceEnd) || 0) - (Number(clip.sourceStart) || 0));
    return this.updateClip(id, { speed: value, end: clip.start + sourceLength / value });
  }

  addTextClip(text = "Text", start = this.currentTime) {
    const track = this._trackList().find((item) => item.type === "text") || this.addTrack("text", this._selectedTrackIdForInsert());
    return this.addClip({
      track: track.id,
      start,
      end: start + 3,
      sourceStart: 0,
      sourceEnd: 3,
      label: text,
      text,
      color: track.color,
      textColor: "#ffffff",
      fontSize: 32,
    });
  }
  renameClip(id, label) {
    const next = (this.cuts || []).map((c) => c.id === id ? { ...c, label } : c);
    this.cuts = next;
    this.dispatchEvent(new CustomEvent("builtin-clip-rename", { detail: { id, label }, bubbles: true, composed: true }));
    this._emitCuts();
  }

  async addFiles(files, trackId = "") {
    const added = [];
    const fileList = Array.from(files || []);
    const validFiles = fileList.filter((file) => mediaTypeFromFile(file));
    const invalidFiles = fileList.filter((file) => !mediaTypeFromFile(file));
    if (invalidFiles.length) this._rejectAssetUpload("invalid-file", invalidFiles);
    for (const file of validFiles) {
      const asset = await this._createAssetFromFile(file);
      if (!asset) continue;
      added.push(asset);
      if (trackId) this._addAssetToTrack(asset, trackId, this.currentTime);
    }
    if (added.length) {
      this.assets = [...(this.assets || []), ...added];
      this.dispatchEvent(new CustomEvent("builtin-assets-add", { detail: { assets: added }, bubbles: true, composed: true }));
    }
    return added;
  }

  _rejectAssetUpload(reason, files = []) {
    const rejected = Array.from(files || []).map((file) => ({ name: file.name || "", type: file.type || "", size: file.size || 0 }));
    this.dispatchEvent(new CustomEvent("builtin-assets-reject", { detail: { reason, files: rejected }, bubbles: true, composed: true }));
  }

  /** Real export via ffmpeg.wasm. Returns the export payload promise. */
  async export() { return this._runExport(); }
  /** Alias kept for backward compatibility — no longer just metadata. */
  async exportEdl() { return this._runExport(); }

  // ---- internals ----

  _normalizeCut(c) {
    const tracks = this._trackList();
    const requestedTrack = c.track || c.trackId;
    const track = tracks.find((t) => t.id === requestedTrack) || tracks.find((t) => t.type === requestedTrack) || tracks[0];
    const td = trackTypeDef(track?.type || "video");
    const start = Math.max(0, Number(c.start) || 0);
    const end = Math.max(start + 0.1, Number(c.end) || (start + 1));
    const sourceStart = Math.max(0, Number(c.sourceStart ?? c.sourceIn ?? 0) || 0);
    const speed = clamp(Number(c.speed) || 1, 0.1, 8);
    const sourceEnd = Math.max(sourceStart + 0.1, Number(c.sourceEnd ?? c.sourceOut ?? (sourceStart + ((end - start) * speed))) || (sourceStart + ((end - start) * speed)));
    const type = track?.type || td.id;
    return {
      id: c.id || uid("clip"),
      start,
      end,
      sourceStart,
      sourceEnd,
      assetId: type === "text" ? "" : (c.assetId || c.asset || this._defaultAssetIdForTrack(track)),
      label: c.label || "Clip",
      track: track?.id || td.id,
      color: c.color || td.color,
      volume: clamp(Number(c.volume ?? 1), 0, 1),
      speed,
      text: c.text ?? c.label ?? "Text",
      fontSize: clamp(Number(c.fontSize) || 32, 8, 160),
      textColor: c.textColor || "#ffffff",
      x: Number(c.x) || 0,
      y: Number(c.y) || 0,
      scale: clamp(Number(c.scale) || 1, 0.1, 5),
      hue: Number(c.hue) || 0,
      saturation: clamp(Number(c.saturation) || 100, 0, 300),
      brightness: clamp(Number(c.brightness) || 100, 0, 300),
    };
  }

  _emitCuts() {
    this.dispatchEvent(new CustomEvent("builtin-cuts-change", { detail: { cuts: this.cuts }, bubbles: true, composed: true }));
  }

  _setSelection(ids) {
    this._selection = Array.from(new Set(ids));
    this._focusId = this._selection[this._selection.length - 1] || "";
    this.dispatchEvent(new CustomEvent("builtin-selection-change", { detail: { items: this._selection }, bubbles: true, composed: true }));
  }

  _effectiveDuration() {
    const explicit = Number(this.duration) || 0;
    const v = this._video?.duration;
    let max = 0;
    for (const c of this.cuts || []) max = Math.max(max, c.end || 0);
    if (explicit > 0) return Math.max(explicit, max);
    if (Number.isFinite(v) && v > 0) return Math.max(v, max);
    return max || 5;
  }

  _timelineDuration() {
    return Math.max(this._effectiveDuration(), this.currentTime || 0) + TIMELINE_TAIL;
  }

  _trackList() {
    const base = Array.isArray(this.tracks) && this.tracks.length ? this.tracks : DEFAULT_TRACKS;
    const normalized = base.map((track) => {
      const type = trackTypeDef(track.type || track.id || "video");
      return {
        id: track.id || uid(type.id),
        type: type.id,
        label: track.label || type.label,
        height: track.height || type.height,
        color: track.color || type.color,
        volume: type.id === "audio" ? clamp(Number(track.volume ?? 1), 0, 1) : undefined,
      };
    });
    for (const clip of this.cuts || []) {
      if (!normalized.some((track) => track.id === clip.track)) {
        const type = trackTypeDef(clip.track);
        normalized.push({ id: clip.track, type: type.id, label: type.label, height: type.height, color: type.color, volume: type.id === "audio" ? 1 : undefined });
      }
    }
    return normalized;
  }

  _visibleTracks() {
    return this._trackList();
  }

  _maybeSeedSourceClips() {
    if (!this.src || this._seededSrc === this.src || (this.cuts || []).length > 0) return;
    const dur = this._effectiveDuration();
    if (!(dur > 0)) return;
    this.tracks = this._trackList();
    const sourceCuts = [
      { id: uid("video"), start: 0, end: dur, sourceStart: 0, sourceEnd: dur, assetId: SOURCE_VIDEO_ASSET_ID, label: "Source video", track: "video" },
      { id: uid("audio"), start: 0, end: dur, sourceStart: 0, sourceEnd: dur, assetId: SOURCE_AUDIO_ASSET_ID, label: this.audioSrc ? "External audio" : "Source audio", track: "audio" },
    ];
    this.cuts = sourceCuts.map((cut) => this._normalizeCut(cut));
    this._seededSrc = this.src;
    this._emitCuts();
  }

  _defaultAssets() {
    const dur = this._effectiveDuration();
    const assets = [];
    if (this.src) assets.push({ id: SOURCE_VIDEO_ASSET_ID, type: "video", src: this.src, name: "Source video", duration: dur });
    if (this.audioSrc || this.src) assets.push({ id: SOURCE_AUDIO_ASSET_ID, type: "audio", src: this.audioSrc || this.src, name: this.audioSrc ? "External audio" : "Source audio", duration: dur });
    return assets;
  }

  _assetList() {
    const custom = Array.isArray(this.assets) ? this.assets : [];
    const byId = new Map();
    for (const asset of [...this._defaultAssets(), ...custom]) {
      if (asset?.id && asset?.src) byId.set(asset.id, asset);
    }
    return [...byId.values()];
  }

  _assetById(id) {
    return this._assetList().find((asset) => asset.id === id);
  }

  _defaultAssetIdForTrack(track) {
    if (track?.type === "audio") return SOURCE_AUDIO_ASSET_ID;
    return SOURCE_VIDEO_ASSET_ID;
  }

  _trackById(id) {
    return this._trackList().find((track) => track.id === id);
  }

  _clipType(clip) {
    return this._trackById(clip.track)?.type || trackTypeDef(clip.track).id;
  }

  _activeClipAt(type, time) {
    return this._activeClipsAt(type, time)[0] || null;
  }

  _activeClipsAt(type, time) {
    return (this.cuts || [])
      .filter((clip) => this._clipType(clip) === type && time >= clip.start && time < clip.end)
      .sort((a, b) => b.start - a.start);
  }

  _clipSourceTime(clip, timelineTime) {
    return (Number(clip.sourceStart) || 0) + Math.max(0, timelineTime - clip.start) * (clamp(Number(clip.speed) || 1, 0.1, 8));
  }

  async _createAssetFromFile(file) {
    if (!file) return null;
    const type = mediaTypeFromFile(file);
    if (!type) return null;
    const src = URL.createObjectURL(file);
    const duration = await this._readMediaDuration(src, type);
    return { id: uid(type), type, src, name: file.name || (type === "video" ? "Video asset" : "Audio asset"), duration };
  }

  _readMediaDuration(src, type) {
    return new Promise((resolve) => {
      const el = document.createElement(type === "video" ? "video" : "audio");
      el.preload = "metadata";
      el.onloadedmetadata = () => resolve(Number.isFinite(el.duration) ? el.duration : 0);
      el.onerror = () => resolve(0);
      el.src = src;
    });
  }

  _addAssetToTrack(asset, trackId, start = this.currentTime) {
    const requestedTrack = this._trackById(trackId);
    const track = requestedTrack?.type === asset.type ? requestedTrack : this._trackList().find((item) => item.type === asset.type) || this.addTrack(asset.type);
    const duration = Math.max(0.1, Number(asset.duration) || this._effectiveDuration() || 1);
    return this.addClip({
      assetId: asset.id,
      track: track.id,
      start,
      end: start + duration,
      sourceStart: 0,
      sourceEnd: duration,
      label: asset.name,
      color: track.color,
    });
  }

  _onAssetDragStart(ev, asset) {
    this._assetDrag = asset;
    ev.dataTransfer.effectAllowed = "copy";
    ev.dataTransfer.setData("text/plain", asset.id);
  }

  _onAssetDragEnd() {
    this._assetDrag = null;
    this._dropTarget = "";
  }

  _assetUploadDragState(dataTransfer) {
    const items = Array.from(dataTransfer?.items || []);
    if (items.length) {
      const fileItems = items.filter((item) => item.kind === "file");
      if (!fileItems.length) return "invalid";
      return fileItems.every((item) => !item.type || item.type.startsWith("video/") || item.type.startsWith("audio/")) ? "valid" : "invalid";
    }
    const files = Array.from(dataTransfer?.files || []);
    if (!files.length) return "invalid";
    return files.every((file) => mediaTypeFromFile(file)) ? "valid" : "invalid";
  }

  _onAssetListDragOver(ev) {
    const state = this._assetUploadDragState(ev.dataTransfer);
    ev.preventDefault();
    ev.stopPropagation();
    ev.dataTransfer.dropEffect = state === "valid" ? "copy" : "none";
    this._dropTarget = state === "valid" ? "asset-list" : "asset-list-invalid";
  }

  async _onAssetListDrop(ev) {
    ev.preventDefault();
    ev.stopPropagation();
    this._dropTarget = "";
    const files = Array.from(ev.dataTransfer?.files || []);
    if (!files.length) {
      this._rejectAssetUpload("unsupported-data");
      return;
    }
    await this.addFiles(files);
  }

  async _onAssetDrop(ev, track) {
    ev.preventDefault();
    ev.stopPropagation();
    this._dropTarget = "";
    this._selectedTrackId = track.id;
    const time = this._pointerTime(ev);
    if (ev.dataTransfer.files?.length) {
      const added = await this.addFiles(ev.dataTransfer.files);
      for (const asset of added) this._addAssetToTrack(asset, track.id, time);
      return;
    }
    const asset = this._assetDrag || this._assetById(ev.dataTransfer.getData("text/plain"));
    if (asset) this._addAssetToTrack(asset, track.id, time);
    this._assetDrag = null;
  }

  _onDropZoneDrag(ev, track) {
    const asset = this._assetDrag;
    if (asset && asset.type !== track.type) return;
    ev.preventDefault();
    this._dropTarget = track.id;
    this._selectedTrackId = track.id;
  }

  _openTrackMenu(ev, trackId) {
    ev.preventDefault();
    ev.stopPropagation();
    this._trackMenu = { x: ev.clientX, y: ev.clientY, trackId: trackId || this._selectedTrackIdForInsert() };
  }

  _selectedTrackIdForInsert() {
    if (this._trackById(this._selectedTrackId)) return this._selectedTrackId;
    const focusedClip = (this.cuts || []).find((clip) => clip.id === this._focusId);
    if (focusedClip && this._trackById(focusedClip.track)) return focusedClip.track;
    return this._trackList().at(-1)?.id || "";
  }

  _trackMenuAction(type) {
    const afterTrackId = this._trackMenu?.trackId || "";
    this._trackMenu = null;
    this.addTrack(type, afterTrackId);
  }

  _laneWidthPx() { return this._timelineDuration() * this._zoom(); }
  _zoom() { return clamp(Number(this.zoom) || 80, ZOOM_MIN, ZOOM_MAX); }

  _autoScroll() {
    if (!this._scroller) return;
    const px = this.currentTime * this._zoom() + TRACK_HEADER_W;
    const sl = this._scroller.scrollLeft;
    const sw = this._scroller.clientWidth;
    if (px < sl + 40) this._scroller.scrollLeft = Math.max(0, px - 80);
    else if (px > sl + sw - 40) this._scroller.scrollLeft = px - sw + 80;
  }

  _snap(time, ignoreId = null) {
    if (!this.snap) return time;
    const z = this._zoom();
    const thr = SNAP_THRESHOLD_PX / z;
    const candidates = [Math.round(time / SNAP_GRID) * SNAP_GRID, this.currentTime, 0, this._effectiveDuration()];
    for (const c of this.cuts || []) {
      if (c.id === ignoreId) continue;
      candidates.push(c.start, c.end);
    }
    return snapValue(time, candidates, thr);
  }

  // ---- pointer interactions ----

  _pointerTime(ev) {
    const lane = this.renderRoot.querySelector(".timeline-grid .lane");
    if (!lane) return 0;
    const rect = lane.getBoundingClientRect();
    return clamp((ev.clientX - rect.left) / this._zoom(), 0, this._timelineDuration());
  }

  _trackFromPoint(x, y) {
    for (const el of this.renderRoot.querySelectorAll(".track")) {
      const rect = el.getBoundingClientRect();
      if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
        return this._trackById(el.dataset.track);
      }
    }
    return null;
  }

  _onClipPointerDown(ev, clip, mode) {
    if (ev.button !== 0) return;
    ev.preventDefault();
    ev.stopPropagation();
    this.focus();
    if (ev.shiftKey) this._setSelection([...this._selection, clip.id]);
    else if (!this._selection.includes(clip.id)) this._setSelection([clip.id]);
    else this._focusId = clip.id;
    this._selectedTrackId = clip.track;
    const lane = this.renderRoot.querySelector(`.track[data-track="${clip.track}"] .lane`);
    if (!lane) return;
    const rect = lane.getBoundingClientRect();
    const startTime = (ev.clientX - rect.left) / this._zoom();
    this._drag = {
      mode, clipId: clip.id, originStart: clip.start, originEnd: clip.end,
      originSourceStart: clip.sourceStart || 0,
      pointerStart: startTime, originTrack: clip.track, moved: false,
    };
  }

  _onPlayheadPointerDown(ev) {
    if (ev.button !== 0) return;
    ev.preventDefault();
    this._drag = { mode: "scrub", pointerStart: this._pointerTime(ev) };
    this.seek(this._pointerTime(ev));
  }

  _onRulerPointerDown(ev) {
    if (ev.button !== 0) return;
    this.seek(this._pointerTime(ev));
    this._drag = { mode: "scrub", pointerStart: this._pointerTime(ev) };
  }

  _onPointerMove(ev) {
    const d = this._drag;
    if (!d) return;
    if (d.mode === "scrub") { this.seek(this._pointerTime(ev)); return; }
    if (d.mode === "asset-preview-resize") {
      const ratio = clamp((ev.clientX - d.rect.left) / Math.max(1, d.rect.width), 0.2, 0.55);
      this._assetPreviewRatio = ratio;
      d.moved = true;
      return;
    }
    if (d.mode === "preview-transform") {
      const dx = ev.clientX - d.pointerX;
      const dy = ev.clientY - d.pointerY;
      this.updateClip(d.clipId, { x: d.originX + dx, y: d.originY + dy });
      d.moved = true;
      return;
    }
    const lane = this.renderRoot.querySelector(`.track[data-track="${d.originTrack}"] .lane`);
    if (!lane) return;
    const rect = lane.getBoundingClientRect();
    const time = (ev.clientX - rect.left) / this._zoom();
    const delta = time - d.pointerStart;
    const dur = this._timelineDuration();
    const next = (this.cuts || []).map((c) => {
      if (c.id !== d.clipId) return c;
      let s = d.originStart;
      let e = d.originEnd;
      let sourceStart = c.sourceStart;
      let sourceEnd = c.sourceEnd;
      let track = c.track;
      if (d.mode === "move") {
        s = clamp(d.originStart + delta, 0, Math.max(0, dur - (d.originEnd - d.originStart)));
        s = this._snap(s, c.id);
        e = s + (d.originEnd - d.originStart);
        const hoverTrack = this._trackFromPoint(ev.clientX, ev.clientY);
        if (hoverTrack && hoverTrack.type === this._clipType(c)) track = hoverTrack.id;
      } else if (d.mode === "trim-start") {
        const minStart = ["video", "audio"].includes(this._clipType(c)) ? d.originStart : 0;
        s = clamp(this._snap(d.originStart + delta, c.id), minStart, d.originEnd - 0.1);
        sourceStart = Math.max(0, d.originSourceStart + ((s - d.originStart) * (Number(c.speed) || 1)));
      } else if (d.mode === "trim-end") {
        const maxEnd = ["video", "audio"].includes(this._clipType(c)) ? d.originEnd : dur;
        e = clamp(this._snap(d.originEnd + delta, c.id), d.originStart + 0.1, maxEnd);
        sourceEnd = d.originSourceStart + ((e - d.originStart) * (Number(c.speed) || 1));
      }
      return { ...c, start: s, end: e, sourceStart, sourceEnd, track, color: this._trackById(track)?.color || c.color };
    });
    this.cuts = next;
    d.moved = true;
  }

  _onPointerUp(_ev) {
    const d = this._drag;
    this._drag = null;
    if (!d) return;
    if (d.mode !== "scrub" && d.moved) this._emitCuts();
  }

  // ---- context menu ----

  _onClipContext(ev, clip) {
    ev.preventDefault();
    ev.stopPropagation();
    if (!this._selection.includes(clip.id)) this._setSelection([clip.id]);
    this._menu = { x: ev.clientX, y: ev.clientY, clipId: clip.id };
  }

  _closeMenu() {
    if (this._menu) this._menu = null;
    if (this._trackMenu) this._trackMenu = null;
  }

  _menuAction(action) {
    const id = this._menu?.clipId;
    this._menu = null;
    if (!id) return;
    const clip = (this.cuts || []).find((c) => c.id === id);
    if (!clip) return;
    if (action === "rename") {
      const label = window.prompt("Clip name", clip.label || "Clip");
      if (label != null) this.renameClip(id, label);
    } else if (action === "duplicate") {
      const dur = this._effectiveDuration();
      const len = clip.end - clip.start;
      const start = clamp(clip.end + 0.05, 0, Math.max(0, dur - len));
      this.addClip({ ...clip, id: undefined, start, end: start + len, label: `${clip.label} copy` });
    } else if (action === "delete") {
      this.deleteClip(id);
    } else if (action === "play") {
      this.seek(clip.start);
      this.play();
    } else if (action?.startsWith("track:")) {
      this._moveClipToTrack(id, action.slice(6));
    }
  }

  _moveClipToTrack(id, trackId) {
    const track = this._trackById(trackId) || this.addTrack(trackId);
    const clip = (this.cuts || []).find((item) => item.id === id);
    if (clip && track.type !== this._clipType(clip)) return;
    const next = (this.cuts || []).map((c) => c.id === id ? { ...c, track: track.id, color: track.color } : c);
    this.cuts = next;
    this.dispatchEvent(new CustomEvent("builtin-clip-move-track", { detail: { id, track: track.id }, bubbles: true, composed: true }));
    this._emitCuts();
  }

  _copySelection() {
    const ids = new Set(this._selection || []);
    this._clipboardCuts = (this.cuts || []).filter((clip) => ids.has(clip.id)).map((clip) => ({ ...clip }));
  }

  _pasteSelection() {
    if (!this._clipboardCuts?.length) return;
    const minStart = Math.min(...this._clipboardCuts.map((clip) => clip.start));
    const pasted = this._clipboardCuts.map((clip) => {
      const start = this.currentTime + (clip.start - minStart);
      const length = clip.end - clip.start;
      return this._normalizeCut({ ...clip, id: uid("clip"), start, end: start + length, label: `${clip.label || "Clip"} copy` });
    });
    this.cuts = [...(this.cuts || []), ...pasted];
    this._setSelection(pasted.map((clip) => clip.id));
    this._emitCuts();
  }

  _promptSpeed(clip) {
    this._speedDialog = { clipId: clip.id, value: String(clip.speed || 1) };
    this.updateComplete.then(() => this.renderRoot.querySelector("#ve-speed-input")?.focus());
  }

  _commitSpeedDialog() {
    const dialog = this._speedDialog;
    if (!dialog) return;
    this.setClipSpeed(dialog.clipId, Number(dialog.value));
    this._speedDialog = null;
  }

  _onSplitHandlePointerDown(ev) {
    if (ev.button !== 0) return;
    const workspace = this.renderRoot.querySelector(".preview-workspace");
    if (!workspace) return;
    ev.preventDefault();
    this._drag = { mode: "asset-preview-resize", rect: workspace.getBoundingClientRect(), moved: false };
  }

  _focusedClipOfType(type) {
    const clip = this._focusId ? (this.cuts || []).find((item) => item.id === this._focusId) : null;
    if (clip && this._clipType(clip) === type) return clip;
    return this._activeClipAt(type, this.currentTime);
  }

  _onPreviewPointerDown(ev) {
    if (ev.button !== 0 || this._previewTool !== "select") return;
    const clip = this._focusedClipOfType("video");
    if (!clip) return;
    ev.preventDefault();
    this._setSelection([clip.id]);
    this._drag = {
      mode: "preview-transform",
      clipId: clip.id,
      pointerX: ev.clientX,
      pointerY: ev.clientY,
      originX: Number(clip.x) || 0,
      originY: Number(clip.y) || 0,
      moved: false,
    };
  }

  _onPreviewWheel(ev) {
    if (!ev.ctrlKey && this._previewTool !== "select") return;
    const clip = this._focusedClipOfType("video");
    if (!clip) return;
    ev.preventDefault();
    const delta = ev.deltaY < 0 ? 0.08 : -0.08;
    this.updateClip(clip.id, { scale: clamp((Number(clip.scale) || 1) + delta, 0.1, 5) });
  }

  // ---- keyboard / wheel ----

  _handleKey(ev) {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(ev.target?.tagName)) return;
    const key = ev.key;
    if ((ev.ctrlKey || ev.metaKey) && (key === "c" || key === "C")) { ev.preventDefault(); this._copySelection(); return; }
    if ((ev.ctrlKey || ev.metaKey) && (key === "v" || key === "V")) { ev.preventDefault(); this._pasteSelection(); return; }
    if (key === " " || key === "Spacebar") { ev.preventDefault(); if (this._playing) this.pause(); else this.play(); return; }
    if (key === "ArrowLeft") { ev.preventDefault(); this.seek(this.currentTime - (ev.shiftKey ? 5 : 1)); return; }
    if (key === "ArrowRight") { ev.preventDefault(); this.seek(this.currentTime + (ev.shiftKey ? 5 : 1)); return; }
    if (key === "s" || key === "S") { ev.preventDefault(); this.splitAt(); return; }
    if (key === "Delete" || key === "Backspace") {
      if (this._selection.length) { ev.preventDefault(); this.deleteClip([...this._selection]); }
      return;
    }
    if ((ev.ctrlKey || ev.metaKey) && (key === "d" || key === "D")) {
      ev.preventDefault();
      for (const id of this._selection) {
        const c = (this.cuts || []).find((x) => x.id === id);
        if (c) {
          const len = c.end - c.start;
          const s = clamp(c.end + 0.05, 0, Math.max(0, this._effectiveDuration() - len));
          this.addClip({ ...c, id: undefined, start: s, end: s + len, label: `${c.label} copy` });
        }
      }
    }
  }

  _handleWheel(ev) {
    if (!ev.ctrlKey) return;
    ev.preventDefault();
    const delta = -Math.sign(ev.deltaY) * 8;
    this.zoom = clamp(this._zoom() + delta, ZOOM_MIN, ZOOM_MAX);
  }

  // ---- ffmpeg export ----

  async _ensureFfmpeg() {
    if (this._ffmpeg) return this._ffmpeg;
    const ffmod = await import("/vendor/ffmpeg/index.js");
    const utilmod = await import("/vendor/ffmpeg/util.js");
    const ffmpeg = new ffmod.FFmpeg();
    ffmpeg.on("log", ({ message }) => { /* eslint-disable-next-line no-console */ console.debug("[ffmpeg]", message); });
    ffmpeg.on("progress", ({ progress }) => {
      const p = Math.max(0, Math.min(1, Number(progress) || 0));
      this._exportState = { ...this._exportState, state: "encoding", progress: p, message: `Encoding ${Math.round(p * 100)}%` };
      this.dispatchEvent(new CustomEvent("builtin-export-progress", { detail: { progress: p }, bubbles: true, composed: true }));
    });
    await ffmpeg.load({
      coreURL: "/vendor/ffmpeg/ffmpeg-core.js",
      wasmURL: "/vendor/ffmpeg/ffmpeg-core.wasm",
    });
    this._ffmpeg = ffmpeg;
    this._fetchFile = utilmod.fetchFile;
    return ffmpeg;
  }

  _triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Caller is responsible for revoking later (we hand the URL out via event).
    return url;
  }

  async _runExport() {
    if (this._exportState.state === "loading" || this._exportState.state === "encoding") return null;
    if (!this.src) {
      const error = new Error("No source video to export");
      this.dispatchEvent(new CustomEvent("builtin-error", { detail: { error }, bubbles: true, composed: true }));
      throw error;
    }
    const segments = (this.cuts || [])
      .filter((c) => this._clipType(c) === "video")
      .slice()
      .sort((a, b) => a.start - b.start)
      .map((c) => {
        const asset = this._assetById(c.assetId) || this._assetById(SOURCE_VIDEO_ASSET_ID);
        return { id: c.id, src: asset?.src || this.src, sourceStart: c.sourceStart || 0, sourceEnd: c.sourceEnd || ((c.sourceStart || 0) + (c.end - c.start)), start: c.start, end: c.end, label: c.label };
      });

    // No video clips → export source unchanged.
    if (segments.length === 0) {
      this._exportState = { state: "loading", progress: 0, message: "Downloading source…" };
      try {
        const resp = await fetch(this.src);
        if (!resp.ok) throw new Error(`Failed to fetch source: ${resp.status}`);
        const blob = await resp.blob();
        const filename = this.downloadName || "video-edit-export.mp4";
        const url = this._triggerDownload(blob, filename);
        const payload = { blob, url, filename, segments: [] };
        this._exportState = { state: "done", progress: 1, message: "Done" };
        this.dispatchEvent(new CustomEvent("builtin-export", { detail: payload, bubbles: true, composed: true }));
        setTimeout(() => { if (this._exportState.state === "done") this._exportState = { state: "idle", progress: 0, message: "" }; }, 2500);
        return payload;
      } catch (error) {
        this._exportState = { state: "error", progress: 0, message: String(error?.message || error) };
        this.dispatchEvent(new CustomEvent("builtin-error", { detail: { error }, bubbles: true, composed: true }));
        throw error;
      }
    }

    try {
      this._exportState = { state: "loading", progress: 0, message: "Loading ffmpeg…" };
      const ffmpeg = await this._ensureFfmpeg();
      // Encode each segment. Try -c copy first; fall back to re-encode.
      const segNames = [];
      for (let i = 0; i < segments.length; i++) {
        const seg = segments[i];
        const inputName = `input${i}.mp4`;
        const name = `seg${i}.mp4`;
        const dur = Math.max(0.05, seg.sourceEnd - seg.sourceStart);
        this._exportState = { state: "encoding", progress: 0, message: `Encoding clip ${i + 1}/${segments.length}…` };
        await ffmpeg.writeFile(inputName, await this._fetchFile(seg.src));
        let ok = false;
        try {
          await ffmpeg.exec([
            "-ss", String(seg.sourceStart), "-i", inputName, "-t", String(dur),
            "-c", "copy", "-avoid_negative_ts", "make_zero", name,
          ]);
          ok = true;
        } catch (_e) { ok = false; }
        if (!ok) {
          // Re-encode fallback for streams that won't concat with -c copy.
          await ffmpeg.exec([
            "-ss", String(seg.sourceStart), "-i", inputName, "-t", String(dur),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            name,
          ]);
        }
        segNames.push(name);
      }

      // Build concat list and concat-demux.
      this._exportState = { state: "encoding", progress: 0, message: "Concatenating…" };
      const listText = segNames.map((n) => `file '${n}'`).join("\n") + "\n";
      await ffmpeg.writeFile("concat.txt", new TextEncoder().encode(listText));
      const outName = "output.mp4";
      try {
        await ffmpeg.exec(["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", outName]);
      } catch (_e) {
        await ffmpeg.exec([
          "-f", "concat", "-safe", "0", "-i", "concat.txt",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
          "-c:a", "aac", "-b:a", "128k",
          outName,
        ]);
      }

      const data = await ffmpeg.readFile(outName);
      const blob = new Blob([data.buffer], { type: "video/mp4" });
      const filename = this.downloadName || "video-edit-export.mp4";
      const url = this._triggerDownload(blob, filename);

      // Cleanup virtual files (best-effort).
      for (const n of [...segNames, ...segments.map((_, i) => `input${i}.mp4`), "concat.txt", outName]) {
        try { await ffmpeg.deleteFile(n); } catch (_e) { /* noop */ }
      }

      const payload = { blob, url, filename, segments };
      this._exportState = { state: "done", progress: 1, message: "Done" };
      this.dispatchEvent(new CustomEvent("builtin-export", { detail: payload, bubbles: true, composed: true }));
      setTimeout(() => { if (this._exportState.state === "done") this._exportState = { state: "idle", progress: 0, message: "" }; }, 2500);
      return payload;
    } catch (error) {
      this._exportState = { state: "error", progress: 0, message: String(error?.message || error) };
      this.dispatchEvent(new CustomEvent("builtin-error", { detail: { error }, bubbles: true, composed: true }));
      throw error;
    }
  }

  // ---- render helpers ----

  _renderRulerTicks() {
    const dur = this._timelineDuration();
    const z = this._zoom();
    const minorEvery = z >= 200 ? 0.1 : z >= 80 ? 0.5 : 1;
    const majorEvery = z >= 80 ? 1 : z >= 40 ? 2 : 5;
    const ticks = [];
    for (let t = 0; t <= dur + 0.0001; t += minorEvery) {
      const isMajor = Math.abs((t / majorEvery) - Math.round(t / majorEvery)) < 0.001;
      const left = t * z;
      ticks.push(html`<div class=${`tick ${isMajor ? "major" : ""}`} style=${`left:${left}px`}>${isMajor ? html`<label>${fmtTime(t)}</label>` : nothing}</div>`);
    }
    return ticks;
  }

  _renderClip(clip) {
    const z = this._zoom();
    const left = clip.start * z;
    const width = Math.max(8, (clip.end - clip.start) * z);
    const selected = this._selection.includes(clip.id);
    const dragging = this._drag?.clipId === clip.id;
    const track = this._trackById(clip.track);
    const bg = clip.color || track?.color || trackTypeDef(this._clipType(clip)).color;
    return html`
      <div class=${`clip ${selected ? "selected" : ""} ${dragging ? "dragging" : ""}`}
           style=${`left:${left}px;width:${width}px;background:${bg}`}
           @pointerdown=${(e) => this._onClipPointerDown(e, clip, "move")}
           @contextmenu=${(e) => this._onClipContext(e, clip)}
           @dblclick=${() => { const label = window.prompt("Clip name", clip.label); if (label != null) this.renameClip(clip.id, label); }}>
        <div class="handle left" @pointerdown=${(e) => this._onClipPointerDown(e, clip, "trim-start")}></div>
        <div class="name">${clip.label || "Clip"}</div>
        <div class="handle right" @pointerdown=${(e) => this._onClipPointerDown(e, clip, "trim-end")}></div>
      </div>
    `;
  }

  _renderTrack(track) {
    const clips = (this.cuts || []).filter((c) => c.track === track.id);
    const width = this._laneWidthPx();
    return html`
      <div class=${`track ${this._dropTarget === track.id ? "drop-target" : ""} ${this._selectedTrackId === track.id ? "selected" : ""}`} data-track=${track.id} style=${`height:${track.height}px`}>
        <div class="label" @pointerdown=${() => { this._selectedTrackId = track.id; }}>
          <span class="label-text">${track.label}</span>
        </div>
        <div class="lane" style=${`width:${width}px;background:color-mix(in srgb, ${track.color} 5%, transparent)`}
             @dragover=${(e) => this._onDropZoneDrag(e, track)}
             @dragleave=${() => { if (this._dropTarget === track.id) this._dropTarget = ""; }}
             @drop=${(e) => this._onAssetDrop(e, track)}
             @pointerdown=${(e) => { if (e.target.classList.contains("lane")) { this.focus(); this._selectedTrackId = track.id; this._setSelection([]); this.seek(this._pointerTime(e)); } }}>
          ${clips.map((c) => this._renderClip(c))}
        </div>
      </div>
    `;
  }

  _renderInspector() {
    const clip = this._focusId ? (this.cuts || []).find((c) => c.id === this._focusId) : null;
    if (!clip) return nothing;
    const track = this._trackById(clip.track);
    const type = track?.type || this._clipType(clip);
    const isAudio = track?.type === "audio";
    const isVideo = type === "video";
    const isText = type === "text";
    const isMedia = isAudio || isVideo;
    const length = (clip.end - clip.start);
    return html`
      <div class="inspector">
        <span class="tag">${this._l("editor.selected", "Selected:")}</span>
        <span class="name"><input type="text" .value=${clip.label || ""} @change=${(e) => this.renameClip(clip.id, e.target.value)}></span>
        <span class="times">${fmtTime(clip.start)} → ${fmtTime(clip.end)} · ${length.toFixed(2)}s</span>
        ${isMedia ? html`
          <button class="btn" type="button" title="Speed" @click=${() => this._promptSpeed(clip)}>
            <builtin-icon name="dashboard" size="14"></builtin-icon>
            <span>${(Number(clip.speed) || 1).toFixed(2)}x</span>
          </button>
        ` : nothing}
        ${isAudio ? html`
          <label class="inspector-volume" title="Clip volume">
            <builtin-icon name="sound" size="14"></builtin-icon>
            <input type="range" min="0" max="1" step="0.01" .value=${String(clip.volume ?? 1)}
                   @input=${(e) => this.setClipVolume(clip.id, e.target.value)}>
          </label>
        ` : nothing}
        ${isVideo ? html`
          <label class="inspector-control" title="X"><span>X</span><input type="number" step="1" .value=${String(Number(clip.x) || 0)} @change=${(e) => this.updateClip(clip.id, { x: Number(e.target.value) })}></label>
          <label class="inspector-control" title="Y"><span>Y</span><input type="number" step="1" .value=${String(Number(clip.y) || 0)} @change=${(e) => this.updateClip(clip.id, { y: Number(e.target.value) })}></label>
          <label class="inspector-control" title="Scale"><span>Scale</span><input type="number" min="0.1" max="5" step="0.05" .value=${String(Number(clip.scale) || 1)} @change=${(e) => this.updateClip(clip.id, { scale: Number(e.target.value) })}></label>
          <label class="inspector-control" title="Hue"><span>Hue</span><input type="range" min="-180" max="180" step="1" .value=${String(Number(clip.hue) || 0)} @input=${(e) => this.updateClip(clip.id, { hue: Number(e.target.value) })}></label>
          <label class="inspector-control" title="Saturation"><span>Sat</span><input type="range" min="0" max="300" step="1" .value=${String(Number(clip.saturation) || 100)} @input=${(e) => this.updateClip(clip.id, { saturation: Number(e.target.value) })}></label>
          <label class="inspector-control" title="Brightness"><span>Bright</span><input type="range" min="0" max="300" step="1" .value=${String(Number(clip.brightness) || 100)} @input=${(e) => this.updateClip(clip.id, { brightness: Number(e.target.value) })}></label>
        ` : nothing}
        ${isText ? html`
          <label class="inspector-text" title="Text content">
            <textarea .value=${clip.text || ""} @input=${(e) => this.updateClip(clip.id, { text: e.target.value, label: e.target.value || "Text" })}></textarea>
          </label>
          <label class="inspector-control" title="Font size"><span>Size</span><input type="number" min="8" max="160" step="1" .value=${String(Number(clip.fontSize) || 32)} @change=${(e) => this.updateClip(clip.id, { fontSize: Number(e.target.value) })}></label>
          <label class="inspector-control" title="Text color"><span>Color</span><input type="color" .value=${clip.textColor || "#ffffff"} @input=${(e) => this.updateClip(clip.id, { textColor: e.target.value })}></label>
        ` : nothing}
        <span class="spacer"></span>
        <button class="btn icon-only" type="button" title=${this._l("editor.delete", "Delete clip")} @click=${() => this.deleteClip(clip.id)}>
          <builtin-icon name="delete" size="14"></builtin-icon>
        </button>
      </div>
    `;
  }

  _renderExportPill() {
    const s = this._exportState;
    if (s.state === "idle") return nothing;
    const cls = s.state === "error" ? "export-pill error" : "export-pill";
    const showSpinner = s.state === "loading" || s.state === "encoding";
    return html`
      <span class=${cls}>
        ${showSpinner ? html`<span class="spinner"></span>` : nothing}
        <span>${s.message}</span>
      </span>
    `;
  }

  _renderAssetBin() {
    const assets = this._assetList();
    return html`
      <div class=${`asset-bin ${this._dropTarget === "asset-list" ? "drag-over" : ""} ${this._dropTarget === "asset-list-invalid" ? "drag-invalid" : ""} ${this._assetsCollapsed ? "collapsed" : ""}`}>
        <div class="asset-bin-head">
          <span class="asset-bin-title">
            <button type="button" title=${this._assetsCollapsed ? "Expand assets" : "Collapse assets"} @click=${() => { this._assetsCollapsed = !this._assetsCollapsed; }}>
              <builtin-icon name=${this._assetsCollapsed ? "right" : "down"} size="14"></builtin-icon>
            </button>
            <span>${this._l("editor.assets", "Assets")}</span>
          </span>
          <button class="btn" type="button" @click=${() => this.renderRoot.querySelector("#ve-file-input")?.click()}>
            <builtin-icon name="upload" size="14"></builtin-icon>
            <span>${this._l("editor.import", "Import")}</span>
          </button>
          <input id="ve-file-input" type="file" accept="video/*,audio/*" multiple hidden @change=${async (e) => { await this.addFiles(e.target.files); e.target.value = ""; }}>
        </div>
        ${this._assetsCollapsed ? nothing : html`
          <div class=${`asset-list ${this._dropTarget === "asset-list" ? "drag-over" : ""} ${this._dropTarget === "asset-list-invalid" ? "drag-invalid" : ""}`}
               @dragover=${(e) => this._onAssetListDragOver(e)}
               @dragleave=${() => { if (this._dropTarget === "asset-list" || this._dropTarget === "asset-list-invalid") this._dropTarget = ""; }}
               @drop=${(e) => this._onAssetListDrop(e)}>
            ${assets.map((asset) => html`
              <div class="asset-chip" draggable="true"
                   @dragstart=${(e) => this._onAssetDragStart(e, asset)}
                   @dragend=${() => this._onAssetDragEnd()}>
                <builtin-icon name=${asset.type === "audio" ? "sound" : "video-camera"} size="14"></builtin-icon>
                <span class="asset-name">${asset.name || asset.src}</span>
                <span class="asset-meta">${asset.duration ? fmtTime(asset.duration) : asset.type}</span>
              </div>
            `)}
          </div>
        `}
      </div>
    `;
  }

  _renderMenu() {
    if (!this._menu) return nothing;
    const { x, y, clipId } = this._menu;
    const clip = (this.cuts || []).find((c) => c.id === clipId);
    if (!clip) return nothing;
    const tracks = this._trackList().filter((track) => track.type === this._clipType(clip));
    return html`
      <div class="ctxmenu" style=${`left:${x}px;top:${y}px`} @click=${(e) => e.stopPropagation()}>
        <button @click=${() => this._menuAction("rename")}>Rename</button>
        <button @click=${() => this._menuAction("duplicate")}>Duplicate</button>
        <button @click=${() => this._menuAction("play")}>Play range</button>
        <hr>
        ${tracks.map((t) => html`<button @click=${() => this._menuAction(`track:${t.id}`)}>Move to ${t.label}${t.id === clip.track ? " ✓" : ""}</button>`)}
        <hr>
        <button @click=${() => this._menuAction("delete")} style="color:#b91c1c">Delete</button>
      </div>
    `;
  }

  _renderTrackMenu() {
    if (!this._trackMenu) return nothing;
    const { x, y } = this._trackMenu;
    return html`
      <div class="ctxmenu" style=${`left:${x}px;top:${y}px`} @click=${(e) => e.stopPropagation()}>
        ${TRACK_TYPE_DEFS.map((type) => html`<button @click=${() => this._trackMenuAction(type.id)}>Add ${type.label} track</button>`)}
      </div>
    `;
  }

  _renderSpeedDialog() {
    if (!this._speedDialog) return nothing;
    const clip = (this.cuts || []).find((item) => item.id === this._speedDialog.clipId);
    return html`
      <div class="dialog-backdrop" @pointerdown=${(e) => { if (e.target === e.currentTarget) this._speedDialog = null; }}>
        <form class="dialog-panel" @submit=${(e) => { e.preventDefault(); this._commitSpeedDialog(); }}>
          <div class="dialog-title">${this._l("editor.speed", "Speed")}</div>
          <label class="dialog-field">
            <span>${clip?.label || this._l("editor.clip", "Clip")}</span>
            <input id="ve-speed-input" type="number" min="0.1" max="8" step="0.05" .value=${this._speedDialog.value}
                   @input=${(e) => { this._speedDialog = { ...this._speedDialog, value: e.target.value }; }}>
          </label>
          <div class="dialog-actions">
            <button class="btn" type="button" @click=${() => { this._speedDialog = null; }}>${this._l("editor.cancel", "Cancel")}</button>
            <button class="btn primary" type="submit">${this._l("editor.apply", "Apply")}</button>
          </div>
        </form>
      </div>
    `;
  }

  _renderTextOverlays() {
    const clips = this._activeClipsAt("text", this.currentTime);
    return html`
      <div class="preview-overlay">
        ${clips.map((clip) => html`
          <div class="text-layer" style=${`transform:translate(calc(-50% + ${Number(clip.x) || 0}px), calc(-50% + ${Number(clip.y) || 0}px)) scale(${clamp(Number(clip.scale) || 1, 0.1, 5)});font-size:${Number(clip.fontSize) || 32}px;color:${clip.textColor || "#ffffff"}`}>
            ${clip.text || clip.label || "Text"}
          </div>
        `)}
      </div>
    `;
  }

  _renderPreviewTools() {
    return html`
      <div class="preview-tools">
        <button class=${`tool-btn ${this._previewTool === "select" ? "active" : ""}`} type="button" title="Select / transform" @click=${() => { this._previewTool = "select"; }}>
          <builtin-icon name="drag" size="16"></builtin-icon>
        </button>
        <button class=${`tool-btn ${this._previewTool === "text" ? "active" : ""}`} type="button" title="Text" @click=${() => { this._previewTool = "text"; this.addTextClip("Text", this.currentTime); }}>
          <builtin-icon name="font-size" size="16"></builtin-icon>
        </button>
      </div>
    `;
  }

  // ---- main render ----

  render() {
    const dur = this._effectiveDuration();
    const timelineDur = this._timelineDuration();
    const z = this._zoom();
    const visibleTracks = this._visibleTracks();
    const playheadLeft = TRACK_HEADER_W + this.currentTime * z;
    const totalWidth = TRACK_HEADER_W + timelineDur * z;
    const tracksHeight = visibleTracks.reduce((a, t) => a + t.height, 0);
    const exporting = this._exportState.state === "loading" || this._exportState.state === "encoding";
    const titleText = this.title || this._l("editor.title", "Video Editor");

    return html`
      <div class="wrap">
        <div class="header">
          <h3 class="title">${titleText}</h3>
          <div class="actions">
            ${this._renderExportPill()}
            <button class="btn primary" type="button"
                    ?disabled=${exporting}
                    @click=${() => this._runExport().catch(() => {})}>
              <builtin-icon name="download" size="14"></builtin-icon>
              <span>${this._l("editor.export", "Export")}</span>
            </button>
          </div>
        </div>

        <div class="preview-workspace" style=${`--ve-asset-pane:${(this._assetPreviewRatio * 100).toFixed(3)}%`}>
          ${this._renderAssetBin()}
          <button class=${`split-handle ${this._drag?.mode === "asset-preview-resize" ? "active" : ""}`} type="button" title="Resize assets and preview" @pointerdown=${(e) => this._onSplitHandlePointerDown(e)}></button>
          <div class="preview-stage">
            <div class="preview" @pointerdown=${(e) => this._onPreviewPointerDown(e)} @wheel=${(e) => this._onPreviewWheel(e)}>
              <video playsinline preload="metadata" controlslist="nodownload noplaybackrate noremoteplayback" disablepictureinpicture></video>
              ${this._renderTextOverlays()}
            </div>
            ${this._renderPreviewTools()}
          </div>
        </div>
        <audio class="audio-monitor" preload="metadata"></audio>

        ${this._renderInspector()}

        <div class="toolbar">
          <div class="toolbar-row">
            <div class="group">
              <button class="btn icon-only" type="button" title="Back 1s" @click=${() => this.seek(Math.max(0, this.currentTime - 1))}>
                <builtin-icon name="step-backward" size="14"></builtin-icon>
              </button>
              <button class="btn icon-only" type="button" title=${this._playing ? "Pause" : "Play"} @click=${() => (this._playing ? this.pause() : this.play())}>
                <builtin-icon name=${this._playing ? "pause" : "play-circle"} size="14"></builtin-icon>
              </button>
              <button class="btn icon-only" type="button" title="Forward 1s" @click=${() => this.seek(Math.min(dur, this.currentTime + 1))}>
                <builtin-icon name="step-forward" size="14"></builtin-icon>
              </button>
            </div>
            <span class="time">${fmtTime(this.currentTime)} / ${fmtTime(dur)}</span>
            <span class="spacer"></span>
            <label class="snap" title="Snap to grid">
              <input type="checkbox" .checked=${!!this.snap} @change=${(e) => { this.snap = e.target.checked; }}>
              <span>${this._l("editor.snap", "Snap")}</span>
            </label>
          </div>
          <div class="toolbar-row">
            <div class="group">
              <button class="btn" type="button" title="Split at playhead (S)" @click=${() => this.splitAt()}>
                <builtin-icon name="scissor" size="14"></builtin-icon>
                <span>${this._l("editor.split", "Split")}</span>
              </button>
              <button class="btn" type="button" title="Add track below selected track" @click=${(e) => this._openTrackMenu(e, "")}>
                <builtin-icon name="plus" size="14"></builtin-icon>
                <span>${this._l("editor.track", "Track")}</span>
              </button>
            </div>
            <span class="spacer"></span>
            <div class="group" title="Zoom">
              <button class="btn icon-only" type="button" @click=${() => { this.zoom = clamp(this._zoom() - 20, ZOOM_MIN, ZOOM_MAX); }}>
                <builtin-icon name="minus" size="12"></builtin-icon>
              </button>
              <input type="range" min=${ZOOM_MIN} max=${ZOOM_MAX} step="5" .value=${String(this._zoom())} @input=${(e) => { this.zoom = Number(e.target.value); }}>
              <button class="btn icon-only" type="button" @click=${() => { this.zoom = clamp(this._zoom() + 20, ZOOM_MIN, ZOOM_MAX); }}>
                <builtin-icon name="plus" size="12"></builtin-icon>
              </button>
            </div>
          </div>
        </div>

        <div class="timeline-wrap">
          <div class="timeline-scroll">
            <div class="timeline-grid" style=${`width:${totalWidth}px`}>
              <div class="ruler">
                <div class="header-cell">${this._l("editor.time", "Time")}</div>
                <div class="ticks" style=${`width:${timelineDur * z}px`} @pointerdown=${(e) => this._onRulerPointerDown(e)}>
                  ${this._renderRulerTicks()}
                </div>
              </div>
              ${visibleTracks.map((t) => this._renderTrack(t))}
              <div class="playhead" style=${`left:${playheadLeft}px;height:${RULER_H + tracksHeight}px`}>
                <div class="grip" @pointerdown=${(e) => this._onPlayheadPointerDown(e)}></div>
              </div>
            </div>
          </div>
        </div>

        ${this._renderMenu()}
        ${this._renderTrackMenu()}
        ${this._renderSpeedDialog()}
      </div>
    `;
  }
}
