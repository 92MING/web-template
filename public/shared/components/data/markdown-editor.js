import { BuiltinBaseElement, html, css, unsafeHTML } from "../lit-base.js";
import { ensureScript, ensureStyle, ensureVendor } from "../vendor-loader.js";

export class BuiltinMarkdownEditor extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    mode: { type: String },
    labels: { type: Object },
    _splitRatio: { type: Number, state: true },
  };

  static styles = css`
    builtin-markdown-editor { display: block; }
    builtin-markdown-editor .host { border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); }
    builtin-markdown-editor .layout { display: grid; grid-template-columns: minmax(0, 1fr); }
    builtin-markdown-editor .layout.mode-split { grid-template-columns: minmax(260px, calc(50% - 6px)) 12px minmax(260px, calc(50% - 6px)); }
    builtin-markdown-editor .layout.mode-preview .editor-pane,
    builtin-markdown-editor .layout.mode-edit .preview-pane,
    builtin-markdown-editor .layout.mode-preview .split-divider,
    builtin-markdown-editor .layout.mode-edit .split-divider { display: none; }
    builtin-markdown-editor .layout.mode-split .preview-pane { border-left: 1px solid var(--builtin-border, #d1d5db); }
    builtin-markdown-editor textarea { width: 100%; min-height: 260px; }
    builtin-markdown-editor .editor-pane,
    builtin-markdown-editor .preview-pane { min-width: 0; min-height: 320px; }
    builtin-markdown-editor .split-divider {
      display: none;
      position: relative;
      cursor: col-resize;
      touch-action: none;
      background: linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 72%, transparent), color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 42%, transparent));
    }
    builtin-markdown-editor .layout.mode-split .split-divider { display: block; }
    builtin-markdown-editor .split-divider::before {
      content: "";
      position: absolute;
      inset: 0;
      margin: auto;
      width: 4px;
      height: 64px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, var(--builtin-surface, #ffffff));
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--builtin-border, #d1d5db) 54%, transparent);
    }
    builtin-markdown-editor .split-divider:hover::before,
    builtin-markdown-editor .split-divider:active::before {
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 68%, var(--builtin-surface, #ffffff));
    }
    builtin-markdown-editor .EasyMDEContainer,
    builtin-markdown-editor .CodeMirror,
    builtin-markdown-editor .editor-toolbar { background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); border-color: var(--builtin-border, #d1d5db); }
    builtin-markdown-editor .CodeMirror { background: var(--builtin-surface, #ffffff); color: var(--builtin-color-text, #111827); border-color: var(--builtin-border, #d1d5db); font-family: var(--builtin-font-mono, "Cascadia Code", "Fira Code", Consolas, monospace); font-size: 14px; line-height: 1.65; }
    builtin-markdown-editor .cm-s-easymde .cm-header,
    builtin-markdown-editor .cm-s-easymde .cm-header-1,
    builtin-markdown-editor .cm-s-easymde .cm-header-2,
    builtin-markdown-editor .cm-s-easymde .cm-header-3,
    builtin-markdown-editor .cm-s-easymde .cm-header-4,
    builtin-markdown-editor .cm-s-easymde .cm-header-5,
    builtin-markdown-editor .cm-s-easymde .cm-header-6,
    builtin-markdown-editor .cm-s-easymde .cm-strong,
    builtin-markdown-editor .cm-s-easymde .cm-em,
    builtin-markdown-editor .cm-s-easymde .cm-quote,
    builtin-markdown-editor .cm-s-easymde .cm-link,
    builtin-markdown-editor .cm-s-easymde .cm-url,
    builtin-markdown-editor .cm-s-default .cm-header,
    builtin-markdown-editor .cm-s-default .cm-strong,
    builtin-markdown-editor .cm-s-default .cm-em,
    builtin-markdown-editor .cm-s-default .cm-quote,
    builtin-markdown-editor .cm-s-default .cm-link {
      color: inherit;
      font: inherit;
      font-size: inherit;
      font-style: inherit;
      font-weight: inherit;
      line-height: inherit;
      margin: 0;
      text-decoration: none;
    }
    builtin-markdown-editor .cm-s-easymde .cm-comment { background: transparent; border-radius: 0; }
    builtin-markdown-editor .editor-preview,
    builtin-markdown-editor .editor-preview-side { display: none !important; }
    builtin-markdown-editor .CodeMirror-cursor { border-left-color: var(--builtin-color-text, #111827); }
    builtin-markdown-editor .CodeMirror-selected { background: var(--builtin-primary-soft, #eff6ff); }
    builtin-markdown-editor .CodeMirror-line::selection,
    builtin-markdown-editor .CodeMirror-line > span::selection,
    builtin-markdown-editor .CodeMirror-line > span > span::selection {
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 20%, #ffffff);
      color: var(--builtin-color-text, #111827);
    }
    builtin-markdown-editor .CodeMirror-line::-moz-selection,
    builtin-markdown-editor .CodeMirror-line > span::-moz-selection,
    builtin-markdown-editor .CodeMirror-line > span > span::-moz-selection {
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 20%, #ffffff);
      color: var(--builtin-color-text, #111827);
    }
    builtin-markdown-editor .editor-toolbar button { color: var(--builtin-color-text, #111827) !important; }
    builtin-markdown-editor .editor-toolbar button:hover,
    builtin-markdown-editor .editor-toolbar button.active { background: var(--builtin-button-hover-bg, #f9fafb); border-color: var(--builtin-border, #d1d5db); }
    builtin-markdown-editor .editor-toolbar i.separator { border-color: var(--builtin-border, #d1d5db); }
    builtin-markdown-editor .preview-pane {
      padding: 18px 20px;
      background: linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 55%, var(--builtin-surface, #ffffff)), var(--builtin-surface, #ffffff));
      color: var(--builtin-color-text, #111827);
      overflow: auto;
    }
    builtin-markdown-editor .preview-empty {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 0.95rem;
    }
    builtin-markdown-editor .preview-body {
      display: grid;
      gap: 0.9rem;
      line-height: 1.7;
    }
    builtin-markdown-editor .preview-body > :first-child { margin-top: 0; }
    builtin-markdown-editor .preview-body > :last-child { margin-bottom: 0; }
    builtin-markdown-editor .preview-body h1,
    builtin-markdown-editor .preview-body h2,
    builtin-markdown-editor .preview-body h3,
    builtin-markdown-editor .preview-body h4,
    builtin-markdown-editor .preview-body h5,
    builtin-markdown-editor .preview-body h6 {
      margin: 0;
      color: var(--builtin-color-text, #111827);
      font-weight: 760;
      line-height: 1.2;
    }
    builtin-markdown-editor .preview-body h1 { font-size: 2.2rem; }
    builtin-markdown-editor .preview-body h2 { font-size: 1.7rem; }
    builtin-markdown-editor .preview-body h3 { font-size: 1.35rem; }
    builtin-markdown-editor .preview-body h4 { font-size: 1.12rem; }
    builtin-markdown-editor .preview-body h5,
    builtin-markdown-editor .preview-body h6 { font-size: 1rem; }
    builtin-markdown-editor .preview-body p { margin: 0; }
    builtin-markdown-editor .preview-body a { color: var(--builtin-primary, #2563eb); }
    builtin-markdown-editor .preview-body ul,
    builtin-markdown-editor .preview-body ol {
      margin: 0;
      padding-left: 1.35rem;
    }
    builtin-markdown-editor .preview-body li { margin: 0.2rem 0; }
    builtin-markdown-editor .preview-body pre {
      padding: 14px 16px;
      overflow: auto;
      border-radius: var(--builtin-radius, 6px);
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 72%, var(--builtin-surface, #ffffff));
      margin: 0;
    }
    builtin-markdown-editor .preview-body pre code.hljs {
      display: block;
      padding: 0;
      background: transparent;
    }
    builtin-markdown-editor .preview-body code {
      font-family: var(--builtin-font-mono, "Cascadia Code", "Fira Code", monospace);
    }
    builtin-markdown-editor .preview-body :not(pre) > code {
      padding: 2px 5px;
      border-radius: 4px;
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 72%, var(--builtin-surface, #ffffff));
    }
    builtin-markdown-editor .preview-body blockquote {
      margin: 0;
      padding-left: 14px;
      border-left: 3px solid var(--builtin-primary, #2563eb);
      color: var(--builtin-color-muted, #6b7280);
    }
    builtin-markdown-editor .preview-body table {
      width: 100%;
      border-collapse: collapse;
    }
    builtin-markdown-editor .preview-body th,
    builtin-markdown-editor .preview-body td {
      padding: 7px 9px;
      border: 1px solid var(--builtin-border, #d1d5db);
    }
    builtin-markdown-editor .preview-body th { background: var(--builtin-header-bg, #f9fafb); }
    builtin-markdown-editor .preview-body hr {
      width: 100%;
      margin: 0;
      border: 0;
      border-top: 1px solid var(--builtin-border, #d1d5db);
    }
    builtin-markdown-editor .preview-body .md-mermaid {
      display: block;
      overflow: auto;
      padding: 6px;
      border-radius: var(--builtin-radius, 6px);
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 84%, var(--builtin-header-bg, #f9fafb));
    }
    builtin-markdown-editor .preview-body .md-mermaid svg {
      display: block;
      max-width: 100%;
      margin: 0 auto;
    }
    builtin-markdown-editor .preview-body .md-mermaid-error,
    builtin-markdown-editor .preview-body .md-math-error {
      padding: 10px 12px;
      border-radius: var(--builtin-radius, 6px);
      color: var(--builtin-color-danger, #b91c1c);
      background: color-mix(in srgb, var(--builtin-color-danger, #b91c1c) 10%, var(--builtin-surface, #ffffff));
      font-family: var(--builtin-font-mono, "Cascadia Code", "Fira Code", monospace);
      font-size: 0.92rem;
      white-space: pre-wrap;
    }
    builtin-markdown-editor .preview-body .md-math-inline {
      display: inline-flex;
      align-items: center;
      min-height: 1.4em;
    }
    builtin-markdown-editor .preview-body .md-math-block {
      display: block;
      overflow-x: auto;
      padding: 10px 0;
    }
    builtin-markdown-editor .preview-body .md-math-block mjx-container {
      margin: 0 auto !important;
    }
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-gutters { background: var(--builtin-header-bg, #111827); border-color: var(--builtin-border, #374151); }
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-linenumber { color: var(--builtin-color-muted, #9ca3af); }
    [data-builtin-theme="dark"] builtin-markdown-editor .layout.mode-split .preview-pane { border-left-color: var(--builtin-border, #374151); }
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-selected,
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-focused .CodeMirror-selected {
      background: rgba(96, 165, 250, 0.34);
    }
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-line::selection,
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-line > span::selection,
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-line > span > span::selection,
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-line::-moz-selection,
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-line > span::-moz-selection,
    [data-builtin-theme="dark"] builtin-markdown-editor .CodeMirror-line > span > span::-moz-selection {
      background: rgba(96, 165, 250, 0.34);
      color: #f8fafc;
    }
    [data-builtin-theme="dark"] builtin-markdown-editor .split-divider {
      background: linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #111827) 78%, transparent), color-mix(in srgb, var(--builtin-surface, #1f2937) 52%, transparent));
    }
    [data-builtin-theme="dark"] builtin-markdown-editor .split-divider::before {
      background: color-mix(in srgb, var(--builtin-border, #374151) 84%, var(--builtin-surface, #1f2937));
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--builtin-border, #374151) 54%, transparent);
    }
    [data-builtin-theme="dark"] builtin-markdown-editor .preview-pane {
      background: linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #111827) 70%, var(--builtin-surface, #1f2937)), var(--builtin-surface, #1f2937));
    }
    @media (max-width: 880px) {
      builtin-markdown-editor .layout.mode-split { grid-template-columns: 1fr !important; }
      builtin-markdown-editor .layout.mode-split .preview-pane { border-left: 0; border-top: 1px solid var(--builtin-border, #d1d5db); }
      builtin-markdown-editor .layout.mode-split .split-divider { display: none; }
    }
  `;

  constructor() {
    super();
    this.value = "";
    this.mode = "split";
    this._editor = null;
    this._suppressChange = false;
    this._marked = null;
    this._highlight = null;
    this._mermaid = null;
    this._mathJax = null;
    this._previewAssetsPromise = null;
    this._previewToken = 0;
    this._previewTimer = null;
    this._splitRatio = 0.5;
    this._splitDrag = null;
  }

  createRenderRoot() { return this; }

  firstUpdated() { this._initEditor(); }

  updated(changed) {
    if (this._editor && !this._suppressChange && changed.has("value") && this._editor.value() !== (this.value || "")) {
      this._editor.value(this.value || "");
    }
    if (changed.has("mode")) requestAnimationFrame(() => this._editor?.codemirror?.refresh?.());
    this._schedulePreviewEnhancement();
  }

  connectedCallback() {
    super.connectedCallback();
    if (window.IntersectionObserver) {
      this._visibilityObserver = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && this._editor) {
            requestAnimationFrame(() => this._editor?.codemirror?.refresh?.());
          }
        }
      });
      this._visibilityObserver.observe(this);
    }
  }

  disconnectedCallback() {
    this._visibilityObserver?.disconnect();
    this._stopSplitDrag();
    this._editor?.toTextArea?.();
    this._editor = null;
    super.disconnectedCallback();
  }

  _splitLayoutStyle(mode) {
    if (mode !== "split") return "";
    const leftPercent = Math.max(24, Math.min(76, (Number(this._splitRatio) || 0.5) * 100));
    const rightPercent = 100 - leftPercent;
    return `grid-template-columns:minmax(260px, calc(${leftPercent}% - 6px)) 12px minmax(260px, calc(${rightPercent}% - 6px));`;
  }

  _startSplitDrag(event) {
    if (this.mode !== "split") return;
    const layout = this.renderRoot.querySelector(".layout.mode-split");
    if (!layout) return;
    this._splitDrag = {
      pointerId: event.pointerId,
      rect: layout.getBoundingClientRect(),
      divider: event.currentTarget,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    this._updateSplitRatio(event.clientX);
    event.preventDefault();
  }

  _moveSplitDrag(event) {
    if (this._splitDrag?.pointerId !== event.pointerId) return;
    this._updateSplitRatio(event.clientX);
  }

  _endSplitDrag(event) {
    if (this._splitDrag?.pointerId !== event.pointerId) return;
    this._splitDrag?.divider?.releasePointerCapture?.(event.pointerId);
    this._stopSplitDrag();
    requestAnimationFrame(() => this._editor?.codemirror?.refresh?.());
  }

  _stopSplitDrag() {
    this._splitDrag = null;
  }

  _updateSplitRatio(clientX) {
    const rect = this._splitDrag?.rect || this.renderRoot.querySelector(".layout.mode-split")?.getBoundingClientRect();
    if (!rect?.width) return;
    const raw = (clientX - rect.left) / rect.width;
    this._splitRatio = Math.max(0.24, Math.min(0.76, raw));
  }

  async _initEditor() {
    const EasyMDE = await ensureVendor("easymde", { css: "/vendor/easymde/easymde.min.css" });
    this._marked = await this._ensureMarked();
    this._loadPreviewAssets();
    this.requestUpdate();
    const textarea = this.renderRoot.querySelector("textarea");
    if (!textarea || this._editor) return;
    this._editor = new EasyMDE({
      element: textarea,
      initialValue: this.value || "",
      spellChecker: false,
      status: false,
      autofocus: false,
      sideBySideFullscreen: false,
      toolbar: ["bold", "italic", "heading", "|", "quote", "unordered-list", "ordered-list", "|", "link", "image", "code", "table", "|", "guide"],
    });
    this._editor.codemirror.on("change", () => {
      this._suppressChange = true;
      this.value = this._editor.value();
      this._suppressChange = false;
      const htmlValue = this._previewHtml();
      this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value, html: htmlValue }, bubbles: true, composed: true }));
    });
    // CodeMirror can fail to render content when initialized inside a hidden or
    // zero-dimension container. Refresh repeatedly at staggered timings.
    const refreshCm = () => this._editor?.codemirror?.refresh?.();
    refreshCm();
    requestAnimationFrame(() => {
      refreshCm();
      requestAnimationFrame(() => {
        refreshCm();
        setTimeout(refreshCm, 120);
      });
    });
  }

  async _ensureMarked() {
    const marked = await ensureVendor("marked", { script: "/vendor/marked/marked.min.js", globalName: "marked" });
    if (marked?.parse) {
      this._configureMarked(marked);
      return marked;
    }
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 50));
      if (window.marked?.parse) {
        this._configureMarked(window.marked);
        return window.marked;
      }
    }
    throw new Error("Marked failed to initialize");
  }

  _configureMarked(marked) {
    if (!marked || marked.__builtinMarkdownEditorConfigured) return;

    const blockMath = {
      name: "blockMath",
      level: "block",
      start(src) {
        return src.indexOf("$$");
      },
      tokenizer(src) {
        const match = /^\$\$[ \t]*\n?([\s\S]+?)\n?\$\$(?:\n|$)/.exec(src);
        if (!match) return undefined;
        const text = match[1]?.trim();
        if (!text) return undefined;
        return { type: "blockMath", raw: match[0], text };
      },
      renderer: (token) => `<div class="md-math-block" data-math="${this._escapeAttribute(token.text)}">${this._escapeHtml(token.text)}</div>`,
    };

    const inlineMath = {
      name: "inlineMath",
      level: "inline",
      start(src) {
        return src.indexOf("$");
      },
      tokenizer(src) {
        if (!src.startsWith("$") || src.startsWith("$$")) return undefined;
        let index = 1;
        let escaped = false;
        while (index < src.length) {
          const char = src[index];
          if (char === "\n") return undefined;
          if (!escaped && char === "$") break;
          escaped = char === "\\" && !escaped;
          if (char !== "\\") escaped = false;
          index += 1;
        }
        if (index >= src.length) return undefined;
        const text = src.slice(1, index);
        if (!text.trim() || /^\s|\s$/.test(text)) return undefined;
        return { type: "inlineMath", raw: src.slice(0, index + 1), text };
      },
      renderer: (token) => `<span class="md-math-inline" data-math="${this._escapeAttribute(token.text)}">${this._escapeHtml(token.text)}</span>`,
    };

    marked.use({
      gfm: true,
      breaks: true,
      extensions: [blockMath, inlineMath],
    });
    marked.__builtinMarkdownEditorConfigured = true;
  }

  _loadPreviewAssets() {
    if (this._previewAssetsPromise) return this._previewAssetsPromise;
    ensureStyle("/vendor/highlight/highlight.css", "builtin-vendor-css-/vendor/highlight/highlight.css");
    if (!window.MathJax) {
      window.MathJax = { startup: { typeset: false } };
    } else if (!window.MathJax.startup) {
      window.MathJax.startup = { typeset: false };
    } else if (window.MathJax.startup.typeset === undefined) {
      window.MathJax.startup.typeset = false;
    }
    this._previewAssetsPromise = Promise.allSettled([
      ensureVendor("highlight", { module: "/vendor/highlight/index.js" }),
      ensureVendor("mermaid", { module: "/vendor/mermaid/index.js" }),
      ensureScript("/vendor/mathjax/math_jax.js"),
    ]).then(async ([highlightResult, mermaidResult, mathJaxResult]) => {
      if (highlightResult.status === "fulfilled") this._highlight = highlightResult.value;
      if (mermaidResult.status === "fulfilled") this._mermaid = mermaidResult.value;
      if (mathJaxResult.status === "fulfilled") {
        this._mathJax = window.MathJax;
        await this._ensureMathJaxReady();
      }
      this.requestUpdate();
    });
    return this._previewAssetsPromise;
  }

  async _ensureMathJaxReady() {
    if (!this._mathJax?.startup?.promise) return this._mathJax;
    try {
      await this._mathJax.startup.promise;
    } catch (_error) {
      // Keep the preview usable even if MathJax initialization fails.
    }
    return this._mathJax;
  }

  _schedulePreviewEnhancement() {
    const preview = this.renderRoot.querySelector(".preview-body");
    if (!preview) return;
    const previewToken = ++this._previewToken;
    if (this._previewTimer) clearTimeout(this._previewTimer);
    this._previewTimer = setTimeout(() => {
      this._previewTimer = null;
      void this._enhancePreview(previewToken);
    }, 0);
  }

  async _enhancePreview(previewToken) {
    const preview = this.renderRoot.querySelector(".preview-body");
    if (!preview || previewToken !== this._previewToken) return;
    await this._renderMermaidBlocks(preview, previewToken);
    if (previewToken !== this._previewToken) return;
    this._highlightCodeBlocks(preview);
    if (previewToken !== this._previewToken) return;
    await this._renderMath(preview, previewToken);
  }

  async _renderMermaidBlocks(preview, previewToken) {
    if (!this._mermaid?.render) return;
    const nodes = [...preview.querySelectorAll("pre > code")].filter((node) => /\blanguage-mermaid\b/i.test(node.className));
    if (!nodes.length) return;
    this._mermaid.initialize({
      startOnLoad: false,
      theme: this._ptTheme === "dark" ? "dark" : "default",
      securityLevel: "loose",
    });
    for (const node of nodes) {
      if (previewToken !== this._previewToken) return;
      const pre = node.closest("pre");
      if (!pre) continue;
      try {
        const result = await this._mermaid.render(`markdown-mermaid-${Math.random().toString(36).slice(2)}`, node.textContent || "");
        const svg = typeof result === "string" ? result : result?.svg;
        if (!svg) continue;
        const wrap = document.createElement("div");
        wrap.className = "md-mermaid";
        wrap.innerHTML = svg;
        pre.replaceWith(wrap);
      } catch (error) {
        const fallback = document.createElement("div");
        fallback.className = "md-mermaid-error";
        fallback.textContent = String(error?.message || error);
        pre.replaceWith(fallback);
      }
    }
  }

  _highlightCodeBlocks(preview) {
    if (!this._highlight?.highlightElement) return;
    for (const node of preview.querySelectorAll("pre > code")) {
      if (node.dataset.builtinHighlighted === "true") continue;
      this._highlight.highlightElement(node);
      node.dataset.builtinHighlighted = "true";
    }
  }

  async _renderMath(preview, previewToken) {
    if (!this._mathJax?.tex2chtmlPromise) return;
    await this._ensureMathJaxReady();
    const nodes = preview.querySelectorAll(".md-math-inline, .md-math-block");
    for (const node of nodes) {
      if (previewToken !== this._previewToken) return;
      if (node.dataset.mathRendered === "true") continue;
      try {
        const rendered = await this._mathJax.tex2chtmlPromise(node.dataset.math || "", {
          display: node.classList.contains("md-math-block"),
        });
        node.replaceChildren(rendered);
        node.dataset.mathRendered = "true";
      } catch (error) {
        node.classList.add("md-math-error");
        node.textContent = String(error?.message || error);
      }
    }
  }

  _escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  _escapeAttribute(value) {
    return this._escapeHtml(value).replace(/"/g, "&quot;");
  }

  _previewHtml() {
    return this._marked?.parse?.(this.value || "") || "";
  }

  render() {
    const mode = ["edit", "preview", "split"].includes(this.mode) ? this.mode : "split";
    const previewHtml = this._previewHtml();
    return html`
      <style>${this.constructor.styles.cssText}</style>
      <div class="host">
        <div class="layout mode-${mode}" style=${this._splitLayoutStyle(mode)}>
          <div class="editor-pane"><textarea></textarea></div>
          <div
            class="split-divider"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize editor panes"
            @pointerdown=${this._startSplitDrag}
            @pointermove=${this._moveSplitDrag}
            @pointerup=${this._endSplitDrag}
            @pointercancel=${this._endSplitDrag}
          ></div>
          <div class="preview-pane">
            ${previewHtml
              ? html`<div class="preview-body">${unsafeHTML(previewHtml)}</div>`
              : html`<div class="preview-empty">Nothing to preview yet.</div>`}
          </div>
        </div>
      </div>
    `;
  }
}