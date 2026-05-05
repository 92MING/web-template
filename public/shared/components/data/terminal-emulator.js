/**
 * @fileoverview BuiltinTerminalEmulator — xterm.js based terminal surface.
 *
 * @attr {string} output — Initial terminal output.
 * @attr {string} prompt — Prompt shown after Enter.
 * @attr {boolean} readonly — Disable typed input handling.
 *
 * @event builtin-command — Detail: { command }.
 */

import { BuiltinBaseElement, html, css } from "../lit-base.js";
import XtermBundle from "../../../vendor/xterm/index.js";

export class BuiltinTerminalEmulator extends BuiltinBaseElement {
  static properties = {
    output: { type: String },
    prompt: { type: String },
    readonly: { type: Boolean },
    labels: { type: Object },
  };

  static styles = css`
    :host { display: block; }
    .wrap {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      background: #0b1020;
    }
    .terminal-host {
      min-height: 260px;
      padding: 8px;
    }
    .status {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 6px 10px;
      background: rgba(255,255,255,0.06);
      color: #cbd5e1;
      font-size: 12px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    @media (max-width: 720px) {
      .terminal-host { min-height: 220px; }
    }
  `;

  constructor() {
    super();
    this.output = "";
    this.prompt = "$ ";
    this.readonly = false;
    this._terminal = null;
    this._fitAddon = null;
    this._command = "";
    this._resizeObserver = null;
  }

  firstUpdated() {
    this._initTerminal();
  }

  updated(changed) {
    if (changed.has("_ptTheme") && this._terminal) {
      this._terminal.options.theme = this._theme();
    }
    if (changed.has("output") && this._terminal) {
      this._resetOutput();
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
    this._terminal?.dispose();
    this._terminal = null;
    this._fitAddon = null;
  }

  _theme() {
    return this._ptTheme === "dark"
      ? { background: "#020617", foreground: "#e2e8f0", cursor: "#93c5fd", selectionBackground: "#1d4ed8" }
      : { background: "#0b1020", foreground: "#e5e7eb", cursor: "#93c5fd", selectionBackground: "#2563eb" };
  }

  _lines() {
    const text = this.output || "Project terminal ready\nType help and press Enter";
    return text.replace(/\r\n/g, "\n").split("\n");
  }

  async _initTerminal() {
    const host = this.shadowRoot?.querySelector(".terminal-host");
    if (!host || this._terminal) return;
    const { Terminal, FitAddon } = await XtermBundle;
    this._terminal = new Terminal({
      convertEol: true,
      cursorBlink: !this.readonly,
      disableStdin: this.readonly,
      fontFamily: "Cascadia Mono, Consolas, ui-monospace, monospace",
      fontSize: 13,
      theme: this._theme(),
      scrollback: 1000,
    });
    this._fitAddon = new FitAddon.FitAddon();
    this._terminal.loadAddon(this._fitAddon);
    this._terminal.open(host);
    this._resetOutput();
    this._terminal.onData((data) => this._onData(data));
    this._resizeObserver = new ResizeObserver(() => this._fitAddon?.fit());
    this._resizeObserver.observe(host);
    requestAnimationFrame(() => this._fitAddon?.fit());
  }

  _resetOutput() {
    if (!this._terminal) return;
    this._terminal.clear();
    for (const line of this._lines()) this._terminal.writeln(line);
    if (!this.readonly) this._terminal.write(this.prompt);
  }

  _onData(data) {
    if (this.readonly || !this._terminal) return;
    if (data === "\r") {
      const command = this._command.trim();
      this._terminal.writeln("");
      this.dispatchEvent(new CustomEvent("builtin-command", { bubbles: true, composed: true, detail: { command } }));
      this._runDemoCommand(command);
      this._command = "";
      this._terminal.write(this.prompt);
      return;
    }
    if (data === "\u007f") {
      if (!this._command) return;
      this._command = this._command.slice(0, -1);
      this._terminal.write("\b \b");
      return;
    }
    if (data >= " " && data !== "\u007f") {
      this._command += data;
      this._terminal.write(data);
    }
  }

  _runDemoCommand(command) {
    if (!this._terminal) return;
    if (!command) return;
    if (command === "help") {
      this._terminal.writeln("Commands: help, status, clear");
      return;
    }
    if (command === "status") {
      this._terminal.writeln("shared components: mounted");
      this._terminal.writeln("xterm.js: active");
      return;
    }
    if (command === "clear") {
      this._terminal.clear();
      return;
    }
    this._terminal.writeln(`command emitted: ${command}`);
  }

  render() {
    return html`
      <div class="wrap">
        <link rel="stylesheet" href="/vendor/xterm/xterm.min.css">
        <div class="status">
          <span>${this.readonly ? "Output" : "Interactive terminal"}</span>
          <span>xterm.js</span>
        </div>
        <div class="terminal-host"></div>
      </div>
    `;
  }
}