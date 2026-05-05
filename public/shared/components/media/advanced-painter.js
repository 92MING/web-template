/**
 * @fileoverview BuiltinAdvancedPainter - iframe wrapper for the vendored miniPaint editor.
 *
 * Core image editing is provided by miniPaint (MIT), including layers, selection,
 * brushes, fill, magic wand, filters, and PNG/JPG/JSON import/export.
 *
 * @attr {string} src - miniPaint iframe URL (default `/vendor/minipaint/index.html`).
 * @attr {string} image-src - Optional image URL to insert as the first layer.
 * @attr {string} project-src - Optional miniPaint JSON project URL to load.
 * @attr {string} height - CSS height for the editor viewport (default `640px`).
 * @attr {string} mode - `default` | `embedded` (default `default`).
 *
 * @event builtin-ready - miniPaint APIs are available.
 * @event builtin-import - `{ type, source }`
 * @event builtin-export - `{ dataURL, format, width, height }`
 * @event builtin-project-export - `{ json }`
 */

import { BuiltinBaseElement, html, css } from "../lit-base.js";

const DEFAULT_EDITOR_SRC = "/vendor/minipaint/index.html";
const READY_TIMEOUT_MS = 12000;

function _file_name_from_url(value) {
  try {
    const url = new URL(value, window.location.href);
    return url.pathname.split("/").filter(Boolean).pop() || "image";
  } catch (_err) {
    return "image";
  }
}

function _is_probably_json(value) {
  return typeof value === "string" && /^[\s\r\n]*[{[]/.test(value);
}

async function _load_image(source) {
  if (source instanceof HTMLImageElement || source instanceof HTMLCanvasElement) {
    return source;
  }
  return new Promise((resolve, reject) => {
    const image = new Image();
    if (!String(source).startsWith("data:") && !String(source).startsWith("blob:")) {
      image.crossOrigin = "anonymous";
    }
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Failed to load image: ${source}`));
    image.src = source;
  });
}

function _image_dimensions(image) {
  return {
    width: image.naturalWidth || image.videoWidth || image.width,
    height: image.naturalHeight || image.videoHeight || image.height,
  };
}

function _raster_image_to_data_url(image, width, height) {
  if (image instanceof HTMLCanvasElement) {
    return image.toDataURL("image/png");
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  canvas.getContext("2d").drawImage(image, 0, 0, width, height);
  return canvas.toDataURL("image/png");
}

export class BuiltinAdvancedPainter extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    imageSrc: { type: String, attribute: "image-src" },
    projectSrc: { type: String, attribute: "project-src" },
    height: { type: String },
    mode: { type: String },
    labels: { type: Object },
    _ready: { type: Boolean, state: true },
    _error: { type: String, state: true },
  };

  static styles = css`
    :host {
      display: block;
      min-width: 0;
      --advanced-painter-height: 640px;
      --ap-radius: var(--builtin-radius-lg, 8px);
      --ap-border: var(--builtin-border, #d1d5db);
      --ap-surface: var(--builtin-surface, #ffffff);
      --ap-text: var(--builtin-color-text, #111827);
      --ap-muted: var(--builtin-color-muted, #6b7280);
      color: var(--ap-text);
    }
    * {
      box-sizing: border-box;
    }
    .shell {
      display: flex;
      flex-direction: column;
      min-height: 360px;
      border: 1px solid var(--ap-border);
      border-radius: var(--ap-radius);
      background: var(--ap-surface);
      box-shadow: var(--builtin-shadow-sm, 0 1px 2px rgb(15 23 42 / .08));
      overflow: hidden;
    }
    .shell.embedded {
      border: none;
      border-radius: 0;
      box-shadow: none;
    }
    .stage {
      position: relative;
      min-height: 360px;
      height: var(--advanced-painter-height);
      background: #1f2937;
    }
    iframe {
      display: block;
      width: 100%;
      height: 100%;
      border: 0;
      background: #ffffff;
    }
    .overlay {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      padding: 18px;
      background: color-mix(in srgb, var(--ap-surface) 84%, transparent);
      color: var(--ap-muted);
      font-size: 13px;
      font-weight: 650;
      text-align: center;
      pointer-events: none;
    }
    .overlay[hidden] {
      display: none;
    }
    @media (max-width: 720px) {
      .stage {
        min-height: 520px;
      }
    }
  `;

  constructor() {
    super();
    this.src = DEFAULT_EDITOR_SRC;
    this.imageSrc = "";
    this.projectSrc = "";
    this.height = "640px";
    this.mode = "default";
    this.labels = {};
    this._ready = false;
    this._error = "";
    this._readyPromise = null;
    this._readyResolve = null;
    this._readyReject = null;
    this._seedKey = "";
  }

  updated(changed) {
    if ((changed.has("imageSrc") || changed.has("projectSrc")) && this._ready) {
      this._loadInitialContent();
    }
  }

  get editorWindow() {
    return this.shadowRoot?.querySelector("iframe")?.contentWindow || null;
  }

  async waitUntilReady() {
    if (this._ready) return this.editorWindow;
    if (!this._readyPromise) this._createReadyPromise();
    return this._readyPromise;
  }

  async openImage(source = this.imageSrc, name = "") {
    if (!source) return null;
    const win = await this.waitUntilReady();
    const image = await _load_image(source);
    const { width, height } = _image_dimensions(image);
    if (!width || !height) throw new Error("Image dimensions could not be read.");
    const layer_name = name || (typeof source === "string" ? _file_name_from_url(source) : "image");
    const data = image instanceof HTMLCanvasElement || String(source).startsWith("blob:")
      ? _raster_image_to_data_url(image, width, height)
      : image;
    const layer = {
      name: layer_name,
      type: "image",
      data,
      width,
      height,
      width_original: width,
      height_original: height,
    };
    await win.Layers.reset_layers(false);
    win.Layers.Base_gui?.set_size?.(width, height);
    await win.Layers.insert(layer);
    if (Array.isArray(win.State?.layers) && win.State.layers.length > 1) {
      win.State.layers = win.State.layers.slice(-1);
      win.State.layer = win.State.layers[0];
    }
    win.Layers.render?.();
    win.Layers.refresh_gui?.();
    this.dispatchEvent(new CustomEvent("builtin-import", {
      detail: { type: "image", source: typeof source === "string" ? source : layer_name },
      bubbles: true,
      composed: true,
    }));
    return layer;
  }

  async openProject(project = this.projectSrc) {
    if (!project) return null;
    const win = await this.waitUntilReady();
    let json = project;
    if (typeof project === "string") {
      if (_is_probably_json(project)) {
        json = JSON.parse(project);
      } else {
        const response = await fetch(project);
        if (!response.ok) throw new Error(`Failed to load miniPaint project: ${project}`);
        json = await response.json();
      }
    }
    win.FileOpen.load_json(json, false);
    this.dispatchEvent(new CustomEvent("builtin-import", {
      detail: { type: "project", source: typeof project === "string" ? project : "inline" },
      bubbles: true,
      composed: true,
    }));
    return json;
  }

  async exportImage(format = "image/png") {
    const win = await this.waitUntilReady();
    const dim = win.Layers.get_dimensions();
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    canvas.width = dim.width;
    canvas.height = dim.height;
    win.Layers.convert_layers_to_canvas(ctx);
    const dataURL = canvas.toDataURL(format);
    const detail = { dataURL, format, width: dim.width, height: dim.height };
    this.dispatchEvent(new CustomEvent("builtin-export", { detail, bubbles: true, composed: true }));
    return detail;
  }

  async exportProject() {
    const win = await this.waitUntilReady();
    const json = win.FileSave.export_as_json();
    this.dispatchEvent(new CustomEvent("builtin-project-export", {
      detail: { json },
      bubbles: true,
      composed: true,
    }));
    return json;
  }

  _createReadyPromise() {
    this._readyPromise = new Promise((resolve, reject) => {
      this._readyResolve = resolve;
      this._readyReject = reject;
    });
    this._readyPromise.catch(() => {});
  }

  _onFrameLoad() {
    this._ready = false;
    this._error = "";
    this._createReadyPromise();
    const started = performance.now();
    const poll = () => {
      let win = null;
      try {
        win = this.editorWindow;
        if (win?.Layers && win?.FileOpen && win?.FileSave) {
          this._ready = true;
          this._syncThemeToFrame();
          this._injectSpinnerStyles(win);
          this._readyResolve?.(win);
          this.dispatchEvent(new CustomEvent("builtin-ready", { bubbles: true, composed: true }));
          this._loadInitialContent();
          return;
        }
      } catch (err) {
        this._failReady(err);
        return;
      }
      if (performance.now() - started > READY_TIMEOUT_MS) {
        this._failReady(new Error("miniPaint editor did not become ready in time."));
        return;
      }
      window.setTimeout(poll, 80);
    };
    poll();
  }

  _injectSpinnerStyles(win) {
    if (!win || win.__builtinSpinnerStylesInjected) return;
    win.__builtinSpinnerStylesInjected = true;
    try {
      const doc = win.document;
      const style = doc.createElement("style");
      style.textContent = 'input[type="number"]{color-scheme:light!important}input[type="number"]::-webkit-inner-spin-button,input[type="number"]::-webkit-outer-spin-button{opacity:1!important;background:#fff!important;border-radius:2px!important}';
      doc.head.appendChild(style);
      this._enhanceNumberInputs(win);
    } catch (_err) {}
  }

  _enhanceNumberInputs(win) {
    if (!win || win.__builtinNumberInputsEnhanced) return;
    win.__builtinNumberInputsEnhanced = true;
    const doc = win.document;
    const enhance = (input) => {
      if (input.dataset.builtinEnhanced || input.parentElement?.classList?.contains("builtin-number-wrap")) return;
      input.dataset.builtinEnhanced = "true";
      const wrap = doc.createElement("span");
      wrap.className = "builtin-number-wrap";
      wrap.style.cssText = "position:relative;display:inline-block;vertical-align:middle;";
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      input.style.paddingRight = "22px";
      const btnCss = "position:absolute;right:0;width:18px;border:none;background:rgba(255,255,255,0.18);color:#fff;font-size:9px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;";
      const up = doc.createElement("button");
      up.style.cssText = btnCss + "top:0;height:50%;border-bottom:1px solid rgba(0,0,0,0.2);border-radius:0 2px 0 0;";
      up.innerHTML = "&#9650;";
      up.onclick = () => { input.value = (parseFloat(input.value) || 0) + 1; input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); };
      const down = doc.createElement("button");
      down.style.cssText = btnCss + "bottom:0;height:50%;border-radius:0 0 2px 0;";
      down.innerHTML = "&#9660;";
      down.onclick = () => { input.value = (parseFloat(input.value) || 0) - 1; input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); };
      wrap.appendChild(up);
      wrap.appendChild(down);
    };
    doc.querySelectorAll('input[type="number"]').forEach(enhance);
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((m) => {
        m.addedNodes.forEach((node) => {
          if (node.tagName === "INPUT" && node.type === "number") enhance(node);
          if (node.querySelectorAll) node.querySelectorAll('input[type="number"]').forEach(enhance);
        });
      });
    });
    if (doc.body) observer.observe(doc.body, { childList: true, subtree: true });
  }

  _failReady(error) {
    this._error = error?.message || String(error);
    this._ready = false;
    this._readyReject?.(error);
  }

  _syncThemeToFrame() {
    const win = this.editorWindow;
    if (!win) return;
    const root = document.documentElement;
    const body = document.body;
    const explicit = this.getAttribute("theme") || root.dataset.theme || body?.dataset.theme || "";
    const is_dark = explicit === "dark"
      || root.classList.contains("dark")
      || body?.classList.contains("dark")
      || (!explicit && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
    try {
      win.postMessage({
        type: "builtin-minipaint-theme",
        theme: is_dark ? "dark" : "light",
      }, window.location.origin);
    } catch (_err) {
      // Same-origin theme sync is optional; the editor still follows its own theme.
    }
  }

  async _openBlankCanvas(width = 800, height = 600) {
    const win = await this.waitUntilReady();
    if (!win) return;
    try {
      const doc = win.document;
      const logo = doc.querySelector(".logo");
      if (logo) logo.style.display = "none";
      const mobileMenu = doc.querySelector(".mobile_menu");
      if (mobileMenu) mobileMenu.style.display = "none";
    } catch (_err) {}
    await win.Layers.reset_layers(true);
    win.Layers.Base_gui?.set_size?.(width, height);
    if (Array.isArray(win.State?.layers) && win.State.layers.length === 0) {
      const blankCanvas = win.document.createElement("canvas");
      blankCanvas.width = width;
      blankCanvas.height = height;
      const ctx = blankCanvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, width, height);
      const dataURL = blankCanvas.toDataURL("image/png");
      await win.Layers.insert({
        name: "Background",
        type: "image",
        data: dataURL,
        width,
        height,
        width_original: width,
        height_original: height,
      });
    }
    win.Layers.render?.();
    win.Layers.refresh_gui?.();
  }

  async _loadInitialContent() {
    const key = `${this.projectSrc || ""}|${this.imageSrc || ""}`;
    if (!this._ready || this._seedKey === key) return;
    this._seedKey = key;
    try {
      if (this.projectSrc) {
        await this.openProject(this.projectSrc);
      } else if (this.imageSrc) {
        await this.openImage(this.imageSrc);
      } else {
        await this._openBlankCanvas();
      }
    } catch (err) {
      this._error = err?.message || String(err);
    }
  }

  render() {
    const source = this.src || DEFAULT_EDITOR_SRC;
    return html`
      <div class="shell ${this.mode}">
        <div class="stage" style=${`--advanced-painter-height:${this.height || "640px"}`}>
          <iframe
            title=${this._l("iframeTitle", "miniPaint advanced image editor")}
            src=${source}
            allow="camera; clipboard-read; clipboard-write"
            @load=${this._onFrameLoad}
          ></iframe>
          <div class="overlay" ?hidden=${this._ready || this._error}>${this._l("loadingEditor", "Loading editor")}</div>
          <div class="overlay" ?hidden=${!this._error}>${this._error}</div>
        </div>
      </div>
    `;
  }
}
