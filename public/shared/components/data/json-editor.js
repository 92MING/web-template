import { BuiltinBaseElement, html, css } from "../lit-base.js";
import { ensureVendor } from "../vendor-loader.js";

const PORTAL_THEME_VARS = [
  "--jse-background-color",
  "--jse-text-color",
  "--jse-text-color-inverse",
  "--jse-main-border",
  "--jse-panel-background",
  "--jse-panel-color",
  "--jse-panel-border",
  "--jse-input-background",
  "--jse-input-background-readonly",
  "--jse-input-border",
  "--jse-input-border-focus",
  "--jse-input-color",
  "--jse-modal-background",
  "--jse-modal-code-background",
  "--jse-overlay-background",
  "--jse-button-background",
  "--jse-button-background-highlight",
  "--jse-button-color",
  "--jse-button-primary-background",
  "--jse-button-primary-background-highlight",
  "--jse-button-primary-background-disabled",
  "--jse-button-primary-color",
  "--jse-context-menu-background",
  "--jse-context-menu-background-highlight",
  "--jse-context-menu-color",
  "--jse-context-menu-color-disabled",
  "--jse-context-menu-separator-color",
  "--jse-context-menu-pointer-background",
  "--jse-context-menu-pointer-background-highlight",
  "--jse-context-menu-pointer-color",
  "--jse-context-menu-pointer-hover-background",
  "--jse-tooltip-background",
  "--jse-tooltip-border",
  "--jse-tooltip-color",
  "--jse-tooltip-action-button-background",
  "--jse-tooltip-action-button-color",
  "--jse-controls-box-shadow",
  "--jse-theme-color",
  "--jse-theme-color-highlight",
];

export class BuiltinJsonEditor extends BuiltinBaseElement {
  static properties = {
    value: { type: Object },
    mode: { type: String },
    labels: { type: Object },
  };

  static styles = css`
    builtin-json-editor { display: block; }
    builtin-json-editor .frame {
      padding: 12px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      border-radius: 20px;
      background:
        radial-gradient(circle at top right, color-mix(in srgb, var(--builtin-primary, #2563eb) 10%, transparent), transparent 36%),
        linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 82%, var(--builtin-surface, #ffffff)), var(--builtin-surface, #ffffff));
      box-shadow: 0 18px 36px rgba(15, 23, 42, .08);
    }
    builtin-json-editor .editor {
      min-height: var(--builtin-json-editor-height, 360px);
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      border-radius: 16px;
      overflow: hidden;
      --jse-font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      --jse-font-family-mono: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;
      --jse-font-size-mono: 14px;
      --jse-line-height: 1.5;
      --jse-theme-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 84%, #60a5fa);
      --jse-theme-color-highlight: var(--builtin-primary, #2563eb);
      --jse-background-color: var(--builtin-surface, #ffffff);
      --jse-text-color: var(--builtin-color-text, #111827);
      --jse-text-color-inverse: #f8fafc;
      --jse-main-border: 1px solid var(--builtin-border, #d1d5db);
      --jse-panel-border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      --jse-menu-color: var(--builtin-color-text, #111827);
      --jse-panel-background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 88%, var(--builtin-surface, #ffffff));
      --jse-panel-color: var(--builtin-color-text, #111827);
      --jse-panel-button-background: color-mix(in srgb, var(--builtin-surface, #ffffff) 92%, transparent);
      --jse-panel-button-background-highlight: color-mix(in srgb, var(--builtin-primary, #2563eb) 10%, var(--builtin-surface, #ffffff));
      --jse-panel-button-color: var(--builtin-color-text, #111827);
      --jse-navigation-bar-background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 82%, var(--builtin-surface, #ffffff));
      --jse-navigation-bar-background-highlight: color-mix(in srgb, var(--builtin-primary, #2563eb) 12%, var(--builtin-surface, #ffffff));
      --jse-navigation-bar-dropdown-color: var(--builtin-color-text, #111827);
      --jse-input-background: color-mix(in srgb, var(--builtin-surface, #ffffff) 96%, transparent);
      --jse-input-background-readonly: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 88%, var(--builtin-surface, #ffffff));
      --jse-input-border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      --jse-input-border-focus: color-mix(in srgb, var(--builtin-primary, #2563eb) 56%, transparent);
      --jse-input-color: var(--builtin-color-text, #111827);
      --jse-modal-background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 92%, var(--builtin-surface, #ffffff));
      --jse-modal-code-background: color-mix(in srgb, var(--builtin-header-bg, #f3f4f6) 88%, transparent);
      --jse-overlay-background: rgba(15, 23, 42, .26);
      --jse-tooltip-background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 92%, var(--builtin-surface, #ffffff));
      --jse-tooltip-border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent);
      --jse-tooltip-color: var(--builtin-color-text, #111827);
      --jse-tooltip-action-button-background: var(--builtin-color-text, #111827);
      --jse-tooltip-action-button-color: #f8fafc;
      --jse-context-menu-background: color-mix(in srgb, var(--builtin-color-text, #111827) 92%, #0f172a);
      --jse-context-menu-background-highlight: color-mix(in srgb, var(--builtin-primary, #2563eb) 26%, var(--builtin-color-text, #111827));
      --jse-context-menu-color: #f8fafc;
      --jse-context-menu-color-disabled: color-mix(in srgb, #f8fafc 56%, transparent);
      --jse-context-menu-separator-color: color-mix(in srgb, #f8fafc 18%, transparent);
      --jse-context-menu-pointer-background: color-mix(in srgb, var(--builtin-color-text, #111827) 92%, #0f172a);
      --jse-context-menu-pointer-background-highlight: color-mix(in srgb, var(--builtin-primary, #2563eb) 26%, var(--builtin-color-text, #111827));
      --jse-context-menu-pointer-color: #f8fafc;
      --jse-context-menu-pointer-hover-background: color-mix(in srgb, var(--builtin-primary, #2563eb) 28%, transparent);
      --jse-controls-box-shadow: 0 14px 32px rgba(15, 23, 42, .14);
      --jse-contents-background-color: transparent;
      --jse-hover-background-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 10%, transparent);
      --jse-selection-background-color: var(--builtin-primary-soft, #eff6ff);
      --jse-active-line-background-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 10%, transparent);
      --jse-search-match-color: color-mix(in srgb, #facc15 42%, #ffffff);
      --jse-search-match-active-color: color-mix(in srgb, #f59e0b 52%, #ffffff);
      --jse-collapsed-items-background-color: color-mix(in srgb, var(--builtin-header-bg, #f3f4f6) 90%, var(--builtin-surface, #ffffff));
      --jse-collapsed-items-selected-background-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 18%, var(--builtin-surface, #ffffff));
      --jse-collapsed-items-link-color: var(--builtin-color-muted, #6b7280);
      --jse-collapsed-items-link-color-highlight: var(--builtin-primary, #2563eb);
      --jse-button-background: color-mix(in srgb, var(--builtin-surface, #ffffff) 92%, transparent);
      --jse-button-background-highlight: color-mix(in srgb, var(--builtin-primary, #2563eb) 10%, var(--builtin-surface, #ffffff));
      --jse-button-color: var(--builtin-color-text, #111827);
      --jse-button-primary-background: var(--builtin-primary, #2563eb);
      --jse-button-primary-background-highlight: color-mix(in srgb, var(--builtin-primary, #2563eb) 84%, #60a5fa);
      --jse-button-primary-background-disabled: color-mix(in srgb, var(--builtin-color-muted, #6b7280) 70%, transparent);
      --jse-button-primary-color: #f8fafc;
      --jse-key-color: #1d4ed8;
      --jse-value-color-string: #047857;
      --jse-value-color-number: #b45309;
      --jse-value-color-boolean: #7c3aed;
      --jse-value-color-null: #6b7280;
      --jse-value-color-url: #0f766e;
      --jse-delimiter-color: color-mix(in srgb, var(--builtin-color-muted, #6b7280) 72%, transparent);
      --jse-tag-background: color-mix(in srgb, var(--builtin-color-text, #111827) 18%, transparent);
      --jse-tag-color: #f8fafc;
    }
    builtin-json-editor .jse-menu,
    builtin-json-editor .jse-navigation-bar,
    builtin-json-editor .jse-status-bar {
      color: var(--jse-panel-color) !important;
    }
    builtin-json-editor .jse-menu {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      padding: 10px 12px;
      gap: 8px;
      border-radius: 12px 12px 0 0;
      background:
        linear-gradient(180deg,
          color-mix(in srgb, var(--jse-panel-background) 92%, var(--jse-background-color)),
          color-mix(in srgb, var(--jse-panel-background) 86%, var(--jse-background-color)));
      border-bottom: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 82%, transparent);
    }
    builtin-json-editor .jse-menu button,
    builtin-json-editor .jse-navigation-bar button,
    builtin-json-editor .jse-status-bar button,
    builtin-json-editor .jse-menu .jse-dropdown-button,
    builtin-json-editor .jse-menu .jse-selected,
    builtin-json-editor .jse-menu .jse-button {
      border-radius: 12px;
    }
    builtin-json-editor .jse-menu button,
    builtin-json-editor .jse-navigation-bar button,
    builtin-json-editor .jse-status-bar button,
    builtin-json-editor .jse-menu .jse-dropdown-button,
    builtin-json-editor .jse-menu .jse-selected {
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 88%, transparent) !important;
      box-shadow: none;
    }
    builtin-json-editor .jse-menu .jse-button,
    builtin-json-editor .jse-navigation-bar button,
    builtin-json-editor .jse-status-bar button {
      min-height: 36px;
      padding: 0 13px;
      font-weight: 500;
      letter-spacing: 0.01em;
      background: color-mix(in srgb, var(--jse-button-background) 92%, transparent);
      color: var(--jse-button-color);
      backdrop-filter: blur(12px);
      transition: background-color .16s ease, border-color .16s ease, color .16s ease, box-shadow .16s ease;
    }
    builtin-json-editor .jse-menu .jse-selected,
    builtin-json-editor .jse-menu button:hover,
    builtin-json-editor .jse-navigation-bar button:hover,
    builtin-json-editor .jse-status-bar button:hover {
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 36%, transparent) !important;
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--builtin-primary, #2563eb) 12%, transparent) inset;
    }
    builtin-json-editor .jse-menu .jse-selected {
      background: linear-gradient(135deg,
        color-mix(in srgb, var(--builtin-primary, #2563eb) 86%, #60a5fa),
        color-mix(in srgb, var(--builtin-primary, #2563eb) 72%, #93c5fd)) !important;
      color: var(--jse-text-color-inverse) !important;
      border-color: transparent !important;
      box-shadow: 0 12px 24px color-mix(in srgb, var(--builtin-primary, #2563eb) 18%, transparent);
    }
    builtin-json-editor .jse-menu .jse-button.jse-group-button {
      min-height: 36px;
      padding-inline: 14px;
    }
    builtin-json-editor .jse-menu .jse-separator {
      align-self: stretch;
      width: 1px;
      margin: 2px 4px;
      background: color-mix(in srgb, var(--builtin-border, #d1d5db) 72%, transparent);
      opacity: .85;
    }
    builtin-json-editor .jse-menu .jse-button svg,
    builtin-json-editor .jse-navigation-bar button svg,
    builtin-json-editor .jse-status-bar button svg {
      opacity: .86;
    }
    builtin-json-editor .jse-navigation-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: color-mix(in srgb, var(--jse-navigation-bar-background) 92%, var(--jse-background-color));
      border-bottom: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 82%, transparent);
    }
    builtin-json-editor .jse-navigation-bar-item,
    builtin-json-editor .jse-navigation-bar-edit {
      min-height: 36px;
      display: inline-flex;
      align-items: center;
    }
    builtin-json-editor .jse-navigation-bar-item {
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 84%, transparent);
      background: color-mix(in srgb, var(--jse-button-background) 96%, transparent);
      box-shadow: inset 0 1px 0 color-mix(in srgb, #ffffff 24%, transparent);
    }
    builtin-json-editor .jse-navigation-bar-button,
    builtin-json-editor .jse-navigation-bar-edit {
      background: transparent !important;
      color: var(--jse-panel-color) !important;
    }
    builtin-json-editor .jse-navigation-bar-button {
      border: none !important;
      min-height: 36px;
      padding: 0 14px;
    }
    builtin-json-editor .jse-navigation-bar-arrow {
      padding-inline: 12px 10px;
      border-right: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 74%, transparent);
    }
    builtin-json-editor .jse-navigation-bar-edit {
      margin-left: auto;
      padding-inline: 12px;
      border-radius: 12px;
      border: 1px solid color-mix(in srgb, var(--builtin-border, #d1d5db) 84%, transparent) !important;
      background: color-mix(in srgb, var(--jse-button-background) 94%, transparent) !important;
    }
    builtin-json-editor .jse-navigation-bar-space {
      display: none;
    }
    builtin-json-editor .jse-text-mode .jse-contents,
    builtin-json-editor .jse-text-mode .cm-editor {
      min-height: 0;
      height: 100%;
    }
    builtin-json-editor .jse-text-mode .cm-editor {
      position: relative;
      color: var(--jse-text-color);
      background: transparent;
    }
    builtin-json-editor .jse-text-mode .cm-editor .cm-scroller {
      display: flex !important;
      align-items: flex-start;
      height: 100% !important;
      overflow: auto !important;
      position: relative;
      z-index: 0;
      color: var(--jse-text-color);
      background: transparent;
      overscroll-behavior: contain;
    }
    builtin-json-editor .jse-text-mode .cm-editor .cm-gutters {
      flex-shrink: 0;
      position: sticky;
      left: 0;
      top: 0;
      z-index: 1;
      min-height: 100%;
      padding-block: 8px;
    }
    builtin-json-editor .jse-text-mode .cm-editor .cm-content,
    builtin-json-editor .jse-text-mode .cm-editor .cm-gutter {
      min-height: 100%;
      padding-block: 8px;
    }
    builtin-json-editor .jse-text-mode .cm-editor .cm-content {
      flex: 1 0 auto;
      white-space: pre;
      caret-color: var(--jse-text-color);
    }
    builtin-json-editor .jse-text-mode .cm-editor .cm-line {
      padding-inline: 16px 12px;
    }
    builtin-json-editor .jse-text-mode .cm-editor .cm-gutterElement {
      padding-inline: 10px;
    }
    builtin-json-editor .jse-text-mode .cm-editor .cm-cursorLayer,
    builtin-json-editor .jse-text-mode .cm-editor .cm-selectionLayer {
      pointer-events: none;
      position: absolute;
      inset: 0;
    }
    builtin-json-editor .jse-context-menu-pointer,
    builtin-json-editor .jse-contextmenu,
    builtin-json-editor .jse-dropdown-items,
    builtin-json-editor .jse-navigation-bar-dropdown,
    builtin-json-editor dialog.jse-modal {
      box-shadow: var(--jse-controls-box-shadow);
    }
    [data-builtin-theme="dark"] builtin-json-editor .editor,
    [data-builtin-theme="dark"] builtin-json-editor .frame,
    [data-builtin-theme="dark"] builtin-json-editor .jse-main {
      background: var(--builtin-surface, #1f2937);
      color: var(--builtin-color-text, #e5e7eb);
      --jse-background-color: var(--builtin-surface, #1f2937);
      --jse-text-color: var(--builtin-color-text, #e5e7eb);
      --jse-contents-background-color: var(--builtin-surface, #1f2937);
      --jse-main-border: 1px solid var(--builtin-border, #374151);
      --jse-panel-border: 1px solid var(--builtin-border, #374151);
      --jse-menu-color: var(--builtin-color-text, #e5e7eb);
      --jse-panel-background: var(--builtin-header-bg, #111827);
      --jse-panel-color: var(--builtin-color-text, #e5e7eb);
      --jse-panel-button-background: color-mix(in srgb, var(--builtin-surface, #1f2937) 84%, transparent);
      --jse-panel-button-background-highlight: color-mix(in srgb, var(--builtin-primary, #60a5fa) 18%, var(--builtin-surface, #1f2937));
      --jse-panel-button-color: var(--builtin-color-text, #e5e7eb);
      --jse-navigation-bar-background: var(--builtin-header-bg, #111827);
      --jse-navigation-bar-background-highlight: color-mix(in srgb, var(--builtin-primary, #60a5fa) 20%, var(--builtin-header-bg, #111827));
      --jse-navigation-bar-dropdown-color: var(--builtin-color-text, #e5e7eb);
      --jse-input-background: var(--builtin-input-bg, #111827);
      --jse-input-background-readonly: color-mix(in srgb, var(--builtin-header-bg, #111827) 86%, transparent);
      --jse-input-border: 1px solid var(--builtin-border, #374151);
      --jse-input-border-focus: color-mix(in srgb, var(--builtin-primary, #60a5fa) 60%, transparent);
      --jse-input-color: var(--builtin-color-text, #e5e7eb);
      --jse-modal-background: color-mix(in srgb, var(--builtin-header-bg, #111827) 92%, var(--builtin-surface, #1f2937));
      --jse-modal-code-background: color-mix(in srgb, var(--builtin-surface, #1f2937) 92%, #0f172a);
      --jse-overlay-background: rgba(2, 6, 23, .66);
      --jse-tooltip-background: color-mix(in srgb, var(--builtin-header-bg, #111827) 92%, var(--builtin-surface, #1f2937));
      --jse-tooltip-border: 1px solid var(--builtin-border, #374151);
      --jse-tooltip-color: var(--builtin-color-text, #e5e7eb);
      --jse-tooltip-action-button-background: #e5e7eb;
      --jse-tooltip-action-button-color: #111827;
      --jse-context-menu-background: color-mix(in srgb, var(--builtin-header-bg, #111827) 92%, #020617);
      --jse-context-menu-background-highlight: color-mix(in srgb, var(--builtin-primary, #60a5fa) 30%, var(--builtin-header-bg, #111827));
      --jse-context-menu-color: #f8fafc;
      --jse-context-menu-color-disabled: color-mix(in srgb, #f8fafc 45%, transparent);
      --jse-context-menu-separator-color: color-mix(in srgb, #f8fafc 16%, transparent);
      --jse-context-menu-pointer-background: color-mix(in srgb, var(--builtin-header-bg, #111827) 92%, #020617);
      --jse-context-menu-pointer-background-highlight: color-mix(in srgb, var(--builtin-primary, #60a5fa) 30%, var(--builtin-header-bg, #111827));
      --jse-context-menu-pointer-color: #f8fafc;
      --jse-context-menu-pointer-hover-background: color-mix(in srgb, var(--builtin-primary, #60a5fa) 26%, transparent);
      --jse-hover-background-color: color-mix(in srgb, var(--builtin-primary, #60a5fa) 12%, transparent);
      --jse-selection-background-color: color-mix(in srgb, var(--builtin-primary, #60a5fa) 22%, transparent);
      --jse-active-line-background-color: color-mix(in srgb, var(--builtin-primary, #60a5fa) 16%, transparent);
      --jse-search-match-color: color-mix(in srgb, #facc15 34%, transparent);
      --jse-search-match-active-color: color-mix(in srgb, #f59e0b 44%, transparent);
      --jse-collapsed-items-background-color: color-mix(in srgb, var(--builtin-header-bg, #111827) 86%, var(--builtin-surface, #1f2937));
      --jse-collapsed-items-selected-background-color: color-mix(in srgb, var(--builtin-primary, #60a5fa) 24%, var(--builtin-header-bg, #111827));
      --jse-collapsed-items-link-color: var(--builtin-color-muted, #9ca3af);
      --jse-collapsed-items-link-color-highlight: #bfdbfe;
      --jse-button-background: color-mix(in srgb, var(--builtin-surface, #1f2937) 88%, transparent);
      --jse-button-background-highlight: color-mix(in srgb, var(--builtin-primary, #60a5fa) 18%, var(--builtin-surface, #1f2937));
      --jse-button-color: var(--builtin-color-text, #e5e7eb);
      --jse-button-primary-background: color-mix(in srgb, var(--builtin-primary, #60a5fa) 82%, #2563eb);
      --jse-button-primary-background-highlight: var(--builtin-primary, #60a5fa);
      --jse-button-primary-background-disabled: color-mix(in srgb, var(--builtin-color-muted, #9ca3af) 58%, transparent);
      --jse-button-primary-color: #0f172a;
      --jse-key-color: #93c5fd;
      --jse-value-color-string: #86efac;
      --jse-value-color-number: #fdba74;
      --jse-value-color-boolean: #c4b5fd;
      --jse-value-color-null: #9ca3af;
      --jse-value-color-url: #5eead4;
      --jse-delimiter-color: color-mix(in srgb, var(--builtin-color-muted, #9ca3af) 74%, transparent);
      --jse-tag-background: color-mix(in srgb, var(--builtin-primary, #60a5fa) 30%, transparent);
      --jse-tag-color: #eff6ff;
    }
    [data-builtin-theme="dark"] builtin-json-editor .frame {
      background:
        radial-gradient(circle at top right, color-mix(in srgb, var(--builtin-primary, #60a5fa) 12%, transparent), transparent 36%),
        linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #111827) 92%, var(--builtin-surface, #1f2937)), var(--builtin-surface, #1f2937));
      box-shadow: 0 18px 36px rgba(2, 6, 23, .36);
    }
    [data-builtin-theme="dark"] builtin-json-editor .jse-menu button,
    [data-builtin-theme="dark"] builtin-json-editor .jse-navigation-bar button,
    [data-builtin-theme="dark"] builtin-json-editor .jse-status-bar button,
    [data-builtin-theme="dark"] builtin-json-editor .jse-menu .jse-dropdown-button,
    [data-builtin-theme="dark"] builtin-json-editor .jse-menu .jse-selected {
      border-color: color-mix(in srgb, var(--builtin-border, #374151) 94%, transparent) !important;
    }
    [data-builtin-theme="dark"] builtin-json-editor .jse-menu {
      background:
        linear-gradient(180deg,
          color-mix(in srgb, var(--builtin-header-bg, #111827) 92%, var(--builtin-surface, #1f2937)),
          color-mix(in srgb, var(--builtin-header-bg, #111827) 84%, var(--builtin-surface, #1f2937)));
    }
    [data-builtin-theme="dark"] builtin-json-editor .jse-navigation-bar-item {
      box-shadow: inset 0 1px 0 color-mix(in srgb, #ffffff 8%, transparent);
    }
  `;

  constructor() {
    super();
    this.value = {};
    this.mode = "tree";
    this._editor = null;
    this._skip_value_sync = false;
    this._theme_observer = null;
  }

  connectedCallback() {
    super.connectedCallback();
    if (!this._theme_observer) {
      this._theme_observer = new MutationObserver(() => this._syncPortalThemeVars());
      this._theme_observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-builtin-theme"],
      });
    }
  }

  createRenderRoot() { return this; }

  firstUpdated() {
    this._syncPortalThemeVars();
    this._initEditor();
  }

  updated(changed) {
    if (!this._editor) return;
    this._syncPortalThemeVars();
    if (changed.has("value")) {
      if (this._skip_value_sync) {
        this._skip_value_sync = false;
      } else {
        this._editor.updateProps({ content: this._content() });
      }
    }
    if (changed.has("mode")) this._editor.updateProps({ mode: this.mode || "tree" });
  }

  disconnectedCallback() {
    this._theme_observer?.disconnect?.();
    this._theme_observer = null;
    this._editor?.destroy?.();
    this._editor = null;
    super.disconnectedCallback();
  }

  async _initEditor() {
    const createJSONEditor = await ensureVendor("vanilla-jsoneditor");
    const target = this.renderRoot.querySelector(".editor");
    if (!target || this._editor) return;
    this._editor = createJSONEditor({
      target,
      props: {
        content: this._content(),
        mode: this.mode || "tree",
        onChange: (content) => this._onChange(content),
      },
    });
    this._syncPortalThemeVars();
  }

  _syncPortalThemeVars() {
    const source = this.renderRoot.querySelector(".editor") || this.renderRoot.querySelector(".frame");
    if (!source) return;

    const computed = getComputedStyle(source);
    for (const name of PORTAL_THEME_VARS) {
      const value = computed.getPropertyValue(name).trim();
      if (value) document.documentElement.style.setProperty(name, value);
    }
  }

  _content() {
    if (typeof this.value === "string") {
      try { return { json: JSON.parse(this.value) }; } catch (_err) { return { text: this.value }; }
    }
    return { json: this.value ?? {} };
  }

  _onChange(content) {
    this._skip_value_sync = true;
    this.value = content?.json !== undefined ? content.json : content?.text ?? "";
    this.dispatchEvent(new CustomEvent("builtin-change", { detail: { value: this.value }, bubbles: true, composed: true }));
  }

  render() { return html`<style>${this.constructor.styles.cssText}</style><div class="frame"><div class="editor"></div></div>`; }
}