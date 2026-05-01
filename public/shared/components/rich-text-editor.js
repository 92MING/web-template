/**
 * @fileoverview BuiltinRichTextEditor — contenteditable-based rich text editor with toolbar.
 *
 * @element builtin-rich-text-editor
 *
 * @attr {string} value — HTML content.
 * @attr {Object} labels — i18n overrides.
 *
 * @event builtin-change — Fired on edit with sanitized HTML. Detail: `{ value }`.
 */

import { BuiltinBaseElement, html, css, classMap } from "./lit-base.js";

export class BuiltinRichTextEditor extends BuiltinBaseElement {
  static properties = {
    value: { type: String },
    labels: { type: Object },
    _toolbarOpen: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    .toolbar-wrap { position: relative; }
    .toolbar {
      display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
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
    .toolbar button.active { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .editor {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 0 0 var(--builtin-radius-lg, 8px) var(--builtin-radius-lg, 8px);
      background: var(--builtin-input-bg, #ffffff);
      min-height: 160px; padding: 12px;
      overflow: auto; line-height: 1.6;
    }
    .editor:focus-visible { outline: 2px solid var(--builtin-primary, #2563eb); outline-offset: -2px; }
    .editor p { margin: 0.4em 0; }
    .editor ul, .editor ol { padding-left: 1.4em; margin: 0.4em 0; }
    .editor blockquote { border-left: 4px solid var(--builtin-border, #d1d5db); margin: 0.4em 0; padding-left: 12px; color: var(--builtin-color-muted, #6b7280); }
    .editor pre { background: var(--builtin-header-bg, #f9fafb); padding: 10px; border-radius: var(--builtin-radius, 6px); overflow: auto; }
    .editor code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; background: var(--builtin-header-bg, #f9fafb); padding: 2px 5px; border-radius: 4px; }
    .editor a { color: var(--builtin-primary, #2563eb); }
    .mobile-toggle {
      display: none; width: 100%; justify-content: center;
      padding: 6px; border: 0; background: transparent;
      color: var(--builtin-color-muted, #6b7280); cursor: pointer;
    }
    @media (max-width: 720px) {
      .toolbar {
        display: none; position: absolute; left: 0; right: 0; top: 100%;
        z-index: 10; border: 1px solid var(--builtin-border, #d1d5db);
        border-radius: var(--builtin-radius, 6px); background: var(--builtin-surface, #ffffff);
        box-shadow: 0 8px 24px rgba(0,0,0,0.08);
      }
      .toolbar.open { display: flex; }
      .mobile-toggle { display: flex; }
    }
  `;

  constructor() {
    super();
    this.value = "";
    this._toolbarOpen = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this._debouncedEmit = this._debounce(() => this._emit(), 300);
  }

  firstUpdated() {
    const editor = this.renderRoot.querySelector(".editor");
    if (editor && this.value) editor.innerHTML = this.value;
  }

  updated(changed) {
    if (changed.has("value")) {
      const editor = this.renderRoot.querySelector(".editor");
      if (editor && document.activeElement !== editor && editor.innerHTML !== this.value) {
        editor.innerHTML = this.value || "";
      }
    }
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  _exec(cmd, value = null) {
    this.renderRoot.querySelector(".editor")?.focus();
    document.execCommand(cmd, false, value);
    this._debouncedEmit();
  }

  _emit() {
    const editor = this.renderRoot.querySelector(".editor");
    const html = this._sanitize(editor?.innerHTML || "");
    this.value = html;
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: html }, bubbles: true }));
  }

  _sanitize(dirty) {
    const allowed = new Set([
      "P", "BR", "STRONG", "B", "EM", "I", "U", "S", "STRIKE", "DEL",
      "H1", "H2", "H3", "H4", "H5", "H6",
      "UL", "OL", "LI", "BLOCKQUOTE", "PRE", "CODE", "A",
      "SPAN", "DIV"
    ]);
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<div>${dirty}</div>`, "text/html");
    const walk = (node) => {
      for (let i = node.children.length - 1; i >= 0; i--) {
        const child = node.children[i];
        if (!allowed.has(child.tagName)) {
          while (child.firstChild) node.insertBefore(child.firstChild, child);
          node.removeChild(child);
        } else {
          for (const attr of [...child.attributes]) {
            if (child.tagName === "A" && attr.name === "href") continue;
            child.removeAttribute(attr.name);
          }
          if (child.tagName === "A") {
            const href = child.getAttribute("href") || "";
            if (!/^https?:\/\//.test(href)) child.removeAttribute("href");
          }
          walk(child);
        }
      }
    };
    walk(doc.body.firstChild);
    return doc.body.firstChild.innerHTML;
  }

  _iconSvg(name) {
    const icons = {
      bold: html`<builtin-icon name="bold" size="16" variant="outlined"></builtin-icon>`,
      italic: html`<builtin-icon name="italic" size="16" variant="outlined"></builtin-icon>`,
      underline: html`<builtin-icon name="underline" size="16" variant="outlined"></builtin-icon>`,
      strikethrough: html`<builtin-icon name="strikethrough" size="16" variant="outlined"></builtin-icon>`,
      h1: html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h8"/><path d="M4 18V6"/><path d="M12 18V6"/><path d="M17 12h3"/><path d="M20 18V6"/></svg>`,
      h2: html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h8"/><path d="M4 18V6"/><path d="M12 18V6"/><circle cx="19" cy="16" r="3"/><path d="M21 9c-1.5 0-3.2.8-4 2.1"/></svg>`,
      paragraph: html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 4v16"/><path d="M17 4v16"/><path d="M19 4H9.5a4.5 4.5 0 0 0 0 9H13"/></svg>`,
      link: html`<builtin-icon name="link" size="16" variant="outlined"></builtin-icon>`,
      list: html`<builtin-icon name="unordered-list" size="16" variant="outlined"></builtin-icon>`,
      orderedList: html`<builtin-icon name="ordered-list" size="16" variant="outlined"></builtin-icon>`,
      blockquote: html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V21M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3"/></svg>`,
      code: html`<builtin-icon name="code" size="16" variant="outlined"></builtin-icon>`,
      clear: html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    };
    return icons[name] || "";
  }

  render() {
    const btn = (title, iconName, action, active = false) => html`
      <button type="button" title="${title}" class="${classMap({ active })}" @click=${action}>${this._iconSvg(iconName)}</button>
    `;
    return html`
      <div class="toolbar-wrap">
        <div class="toolbar ${classMap({ open: this._toolbarOpen })}" part="toolbar">
          <slot name="toolbar-before"></slot>
          ${btn(this._l("bold", "Bold"), "bold", () => this._exec("bold"))}
          ${btn(this._l("italic", "Italic"), "italic", () => this._exec("italic"))}
          ${btn(this._l("underline", "Underline"), "underline", () => this._exec("underline"))}
          ${btn(this._l("strikethrough", "Strikethrough"), "strikethrough", () => this._exec("strikeThrough"))}
          ${btn(this._l("heading1", "Heading 1"), "h1", () => this._exec("formatBlock", "H1"))}
          ${btn(this._l("heading2", "Heading 2"), "h2", () => this._exec("formatBlock", "H2"))}
          ${btn(this._l("paragraph", "Paragraph"), "paragraph", () => this._exec("formatBlock", "P"))}
          ${btn(this._l("link", "Link"), "link", () => {
            const url = prompt(this._l("linkUrl", "Enter URL:"), "https://");
            if (url) this._exec("createLink", url);
          })}
          ${btn(this._l("unorderedList", "Unordered list"), "list", () => this._exec("insertUnorderedList"))}
          ${btn(this._l("orderedList", "Ordered list"), "orderedList", () => this._exec("insertOrderedList"))}
          ${btn(this._l("blockquote", "Blockquote"), "blockquote", () => this._exec("formatBlock", "BLOCKQUOTE"))}
          ${btn(this._l("code", "Code"), "code", () => this._exec("formatBlock", "PRE"))}
          ${btn(this._l("clear", "Clear formatting"), "clear", () => this._exec("removeFormat"))}
          <slot name="toolbar-after"></slot>
        </div>
        ${this._ptMobile ? html`
          <button type="button" class="mobile-toggle" @click=${() => { this._toolbarOpen = !this._toolbarOpen; }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>
            ${this._l("toolbar", "Toolbar")}
          </button>
        ` : ""}
      </div>
      <div
        class="editor"
        contenteditable="true"
        @input=${() => this._debouncedEmit()}
        part="editor"
      ></div>
    `;
  }
}
