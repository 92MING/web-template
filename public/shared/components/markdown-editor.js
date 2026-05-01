/**
 * @fileoverview BuiltinMarkdownEditor — Split/edit/preview markdown editor with toolbar.
 *
 * @element builtin-markdown-editor
 *
 * @attr {string} value — Markdown source.
 * @attr {string} mode — `split` | `edit` | `preview`. Default `split`.
 * @attr {Object} labels — i18n overrides.
 *
 * @event builtin-change — Fired on edit. Detail: `{ value, html }`.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, unsafeHTML } from "./lit-base.js";

let _markedLoadPromise = null;
function _ensureMarked() {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (window.marked) return Promise.resolve(window.marked);
  if (_markedLoadPromise) return _markedLoadPromise;
  _markedLoadPromise = new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = "/vendor/marked/marked.min.js";
    s.async = true;
    s.onload = () => {
      const start = Date.now();
      const tick = () => {
        if (window.marked) resolve(window.marked);
        else if (Date.now() - start > 10000) resolve(null);
        else setTimeout(tick, 100);
      };
      tick();
    };
    s.onerror = () => resolve(null);
    document.head.appendChild(s);
  });
  return _markedLoadPromise;
}

export class BuiltinMarkdownEditor extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    mode: { type: String },
    labels: { type: Object },
    _previewHtml: { type: String, state: true },
    _activeTab: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .toolbar {
      display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
      padding: 8px; border: 1px solid var(--builtin-border, #d1d5db);
      border-bottom: 0; border-radius: var(--builtin-radius-lg, 8px) var(--builtin-radius-lg, 8px) 0 0;
      background: var(--builtin-header-bg, #f9fafb);
    }
    .toolbar button {
      display: inline-flex; align-items: center; justify-content: center;
      min-height: 32px; min-width: 32px; padding: 0 8px;
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      border-radius: var(--builtin-radius, 6px); cursor: pointer;
    }
    .toolbar button:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .editor-wrap {
      display: grid; grid-template-columns: 1fr 1fr;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 0 0 var(--builtin-radius-lg, 8px) var(--builtin-radius-lg, 8px);
      overflow: hidden; min-height: 280px;
    }
    .editor-wrap.single { grid-template-columns: 1fr; }
    .pane {
      display: flex; flex-direction: column;
      min-height: 0;
    }
    .pane + .pane { border-left: 1px solid var(--builtin-border, #d1d5db); }
    .pane-label {
      padding: 6px 10px; font-size: 12px; font-weight: 650;
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      color: var(--builtin-color-muted, #6b7280);
    }
    textarea {
      flex: 1 1 auto; border: 0; padding: 12px;
      background: var(--builtin-input-bg, #ffffff); color: inherit;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 14px; line-height: 1.6; resize: vertical; outline: none;
    }
    .preview {
      flex: 1 1 auto; padding: 12px; overflow: auto;
      background: var(--builtin-surface, #ffffff);
    }
    .preview :is(h1,h2,h3,h4,h5,h6) { margin: 0.6em 0 0.3em; }
    .preview p { margin: 0.4em 0; line-height: 1.6; }
    .preview pre {
      background: var(--builtin-header-bg, #f9fafb);
      padding: 10px; border-radius: var(--builtin-radius, 6px);
      overflow: auto;
    }
    .preview code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      background: var(--builtin-header-bg, #f9fafb); padding: 2px 5px; border-radius: 4px;
    }
    .preview blockquote {
      border-left: 4px solid var(--builtin-border, #d1d5db);
      margin: 0.4em 0; padding-left: 12px; color: var(--builtin-color-muted, #6b7280);
    }
    .preview ul, .preview ol { padding-left: 1.4em; }
    .preview hr { border: 0; border-top: 1px solid var(--builtin-border, #d1d5db); margin: 0.8em 0; }
    .mobile-tabs {
      display: none;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-bottom: 0;
      background: var(--builtin-header-bg, #f9fafb);
    }
    .mobile-tabs button {
      flex: 1; padding: 8px; border: 0; background: transparent;
      color: var(--builtin-color-muted, #6b7280); cursor: pointer;
      border-bottom: 2px solid transparent;
    }
    .mobile-tabs button.active {
      color: var(--builtin-primary, #2563eb);
      border-bottom-color: var(--builtin-primary, #2563eb);
      font-weight: 650;
    }
    @media (max-width: 720px) {
      .editor-wrap { grid-template-columns: 1fr !important; min-height: 220px; }
      .pane + .pane { border-left: 0; border-top: 1px solid var(--builtin-border, #d1d5db); }
      .mobile-tabs { display: flex; }
      .pane { display: none; }
      .pane.active { display: flex; }
    }
  `;

  constructor() {
    super();
    this.value = "";
    this.mode = "split";
    this._activeTab = "edit";
    this._previewHtml = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this._updatePreview();
    if (!window.marked) {
      _ensureMarked().then(() => this._updatePreview());
    }
  }

  willUpdate(changed) {
    if (changed.has("value")) {
      this._updatePreview();
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _getMarked() {
    return window.marked || null;
  }

  async _updatePreview() {
    const marked = this._getMarked();
    if (marked && marked.parse) {
      this._previewHtml = await marked.parse(this.value || "");
    } else {
      this._previewHtml = "";
    }
  }

  _emit() {
    this.dispatchEvent(new CustomEvent("builtin-change", {
      detail: { value: this.value, html: this._previewHtml },
      bubbles: true,
    }));
  }

  _insert(before, after = "") {
    const ta = this.renderRoot.querySelector("textarea");
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const text = this.value || "";
    const selected = text.slice(start, end);
    const replacement = before + selected + after;
    this.value = text.slice(0, start) + replacement + text.slice(end);
    this._updatePreview();
    this._emit();
    requestAnimationFrame(() => {
      ta.focus();
      const cursor = start + before.length + selected.length;
      ta.setSelectionRange(cursor, cursor);
    });
  }

  _onInput(e) {
    this.value = e.target.value;
    this._updatePreview();
    this._emit();
  }

  _iconSvg(name) {
    const icons = {
      bold: html`<builtin-icon name="bold" size="16" variant="outlined"></builtin-icon>`,
      italic: html`<builtin-icon name="italic" size="16" variant="outlined"></builtin-icon>`,
      heading: html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 12h12"/><path d="M6 20V4"/><path d="M18 20V4"/></svg>`,
      link: html`<builtin-icon name="link" size="16" variant="outlined"></builtin-icon>`,
      code: html`<builtin-icon name="code" size="16" variant="outlined"></builtin-icon>`,
      list: html`<builtin-icon name="unordered-list" size="16" variant="outlined"></builtin-icon>`,
      quote: html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V21M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3"/></svg>`,
      hr: html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
    };
    return icons[name] || "";
  }

  render() {
    const mode = this.mode || "split";
    const isMobile = this._ptMobile;
    const showEdit = mode === "edit" || mode === "split";
    const showPreview = mode === "preview" || mode === "split";

    const editActive = !isMobile || mode === "edit" || (mode === "split" && this._activeTab === "edit");
    const previewActive = !isMobile || mode === "preview" || (mode === "split" && this._activeTab === "preview");

    const editPane = html`
      <div class="pane ${classMap({ active: editActive })}" part="edit-pane">
        ${!isMobile ? html`<div class="pane-label">${this._l("edit", "Edit")}</div>` : ""}
        <textarea .value=${this.value} @input=${this._onInput} part="textarea" placeholder="${this._l("placeholder", "Write markdown…")}"></textarea>
      </div>
    `;

    const previewPane = html`
      <div class="pane ${classMap({ active: previewActive })}" part="preview-pane">
        ${!isMobile ? html`<div class="pane-label">${this._l("preview", "Preview")}</div>` : ""}
        <div class="preview">${unsafeHTML(this._previewHtml)}</div>
      </div>
    `;

    const btn = (title, iconName, action) => html`
      <button type="button" title="${title}" @click=${action}>${this._iconSvg(iconName)}</button>
    `;

    return html`
      <div class="toolbar" part="toolbar">
        <slot name="toolbar-before"></slot>
        ${btn(this._l("bold", "Bold"), "bold", () => this._insert("**", "**"))}
        ${btn(this._l("italic", "Italic"), "italic", () => this._insert("*", "*"))}
        ${btn(this._l("heading", "Heading"), "heading", () => this._insert("## ", ""))}
        ${btn(this._l("link", "Link"), "link", () => this._insert("[", "](url)"))}
        ${btn(this._l("code", "Code"), "code", () => this._insert("\n\`\`\`\n", "\n\`\`\`\n"))}
        ${btn(this._l("list", "List"), "list", () => this._insert("\n- ", ""))}
        ${btn(this._l("quote", "Quote"), "quote", () => this._insert("\n> ", ""))}
        ${btn(this._l("hr", "Horizontal rule"), "hr", () => this._insert("\n---\n", ""))}
        <slot name="toolbar-after"></slot>
      </div>
      ${isMobile && mode === "split" ? html`
        <div class="mobile-tabs">
          <button class="${this._activeTab === "edit" ? "active" : ""}" @click=${() => { this._activeTab = "edit"; }}>${this._l("edit", "Edit")}</button>
          <button class="${this._activeTab === "preview" ? "active" : ""}" @click=${() => { this._activeTab = "preview"; }}>${this._l("preview", "Preview")}</button>
        </div>
      ` : ""}
      <div class="editor-wrap ${classMap({ single: mode !== "split" })}" part="editor-wrap">
        ${showEdit ? editPane : ""}
        ${showPreview ? previewPane : ""}
      </div>
    `;
  }
}
