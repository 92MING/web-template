import { BuiltinBaseElement, html, css, repeat } from "../lit-base.js";
import { BuiltinSchemaForm } from "../form/schema-form.js";

if (!customElements.get("builtin-schema-form")) customElements.define("builtin-schema-form", BuiltinSchemaForm);

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return [];
    try { return JSON.parse(value); } catch { return []; }
  },
  toAttribute(value) { return JSON.stringify(value); },
};

function formatSize(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export class BuiltinAiChatbot extends BuiltinBaseElement {
  static properties = {
    messages: { type: Array, converter: jsonConverter },
    placeholder: { type: String },
    value: { type: String },
    typing: { type: Boolean },
    labels: { type: Object },
    apiBase: { type: String, attribute: "api-base" },
    endpoint: { type: String },
    stream: { type: Boolean },
    memoryLimit: { type: Number, attribute: "memory-limit" },
    systemPrompt: { type: String, attribute: "system-prompt" },
    maxTokens: { type: Number, attribute: "max-tokens" },
    temperature: { type: Number },
    reasoning: { type: Boolean },
    base64Mode: { type: Boolean, attribute: "base64-mode" },
    _messages: { type: Array, state: true },
    _attachments: { type: Array, state: true },
    _generating: { type: Boolean, state: true },
    _settingsOpen: { type: Boolean, state: true },
    _dragActive: { type: Boolean, state: true },
  };

  static styles = css`
    :host { display: block; }
    * { box-sizing: border-box; }
    .chat {
      display: grid;
      grid-template-rows: auto minmax(260px, 1fr) auto;
      min-height: 560px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 20px;
      background: var(--builtin-surface, #ffffff);
      overflow: hidden;
      color: var(--builtin-color-text, #111827);
      box-shadow: 0 20px 44px rgba(15, 23, 42, .08);
    }
    .topbar {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 88%, var(--builtin-surface, #ffffff));
      min-width: 0;
      flex-wrap: wrap;
    }
    .brand { display: flex; align-items: center; gap: 8px; font-weight: 750; min-width: 0; }
    .brand span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .topbar-actions { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; }
    .field { display: inline-flex; align-items: center; gap: 6px; color: var(--builtin-color-muted, #6b7280); font-size: 12px; }
    select, input[type="number"], textarea, .system-input {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff);
      color: inherit;
      font: inherit;
    }
    select, input[type="number"] { min-height: 30px; padding: 0 8px; }
    input[type="checkbox"] { accent-color: var(--builtin-primary, #2563eb); }
    .settings-backdrop {
      position: fixed;
      inset: 0;
      display: grid;
      place-items: center;
      padding: 18px;
      background: rgba(15, 23, 42, .52);
      z-index: 3000;
    }
    .settings-backdrop[hidden] { display: none; }
    .settings-dialog {
      width: min(680px, 100%);
      max-height: min(760px, calc(100vh - 36px));
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      box-shadow: 0 24px 80px rgba(15, 23, 42, .28);
      overflow: hidden;
    }
    .settings-head, .settings-foot {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px 14px;
      background: var(--builtin-header-bg, #f9fafb);
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .settings-foot { border-top: 1px solid var(--builtin-border-soft, #e5e7eb); border-bottom: 0; justify-content: flex-end; }
    .settings-title { font-weight: 750; }
    .settings-body { padding: 16px; overflow: auto; }
    .messages {
      display: grid;
      align-content: start;
      gap: 14px;
      padding: 16px;
      overflow: auto;
      background: linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 45%, transparent), transparent 26%);
    }
    .row { display: flex; gap: 8px; align-items: flex-start; min-width: 0; }
    .row.user { justify-content: flex-end; }
    .avatar {
      width: 28px; height: 28px; border-radius: 50%; flex: 0 0 auto;
      display: inline-flex; align-items: center; justify-content: center;
      background: var(--builtin-header-bg, #f3f4f6);
      color: var(--builtin-color-muted, #6b7280);
    }
    .bubble-wrap { max-width: min(82%, 760px); display: grid; gap: 4px; }
    .bubble {
      padding: 9px 11px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: 8px;
      background: var(--builtin-header-bg, #f9fafb);
      line-height: 1.55;
      font-size: 14px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .user .bubble { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .error .bubble { background: #fef2f2; color: #991b1b; border-color: #fecaca; }
    .meta { color: var(--builtin-color-muted, #6b7280); font-size: 11px; display: flex; gap: 8px; flex-wrap: wrap; }
    .attachments, .pending-list { display: flex; flex-wrap: wrap; gap: 8px; }
    .attachment {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      max-width: min(100%, 260px);
      border: 1px solid color-mix(in srgb, var(--builtin-border-soft, #e5e7eb) 92%, transparent);
      border-radius: 14px;
      padding: 7px 10px;
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 78%, var(--builtin-surface, #ffffff));
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
      min-width: 0;
    }
    .attachment img { width: 38px; height: 38px; object-fit: cover; border-radius: 10px; }
    .attachment-copy {
      display: grid;
      gap: 2px;
      min-width: 0;
      flex: 1 1 auto;
    }
    .attachment .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; color: var(--builtin-color-text, #111827); font-weight: 650; }
    .attachment-meta { color: var(--builtin-color-muted, #6b7280); font-size: 11px; }
    .typing { display: inline-flex; gap: 4px; align-items: center; }
    .typing span { width: 5px; height: 5px; border-radius: 50%; background: currentColor; opacity: .35; animation: dot 1s infinite ease-in-out; }
    .typing span:nth-child(2) { animation-delay: .15s; }
    .typing span:nth-child(3) { animation-delay: .3s; }
    .composer-shell {
      display: grid;
      gap: 10px;
      padding: 12px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 86%, var(--builtin-surface, #ffffff));
    }
    .pending {
      display: grid;
      gap: 8px;
      padding: 10px 12px;
      border: 1px solid color-mix(in srgb, var(--builtin-border-soft, #e5e7eb) 92%, transparent);
      border-radius: 16px;
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 92%, transparent);
    }
    .pending-head,
    .composer-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
    }
    .composer {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: end;
      gap: 10px;
      padding: 12px;
      border: 1px solid color-mix(in srgb, var(--builtin-border-soft, #e5e7eb) 92%, transparent);
      border-radius: 18px;
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 94%, transparent);
      position: relative;
    }
    .composer.drag-active {
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 45%, transparent);
      box-shadow: 0 0 0 4px color-mix(in srgb, var(--builtin-primary, #2563eb) 12%, transparent);
    }
    .composer-dropzone {
      position: absolute;
      inset: 8px;
      border: 2px dashed color-mix(in srgb, var(--builtin-primary, #2563eb) 48%, transparent);
      border-radius: 14px;
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 9%, transparent);
      display: grid;
      place-items: center;
      font-size: 13px;
      font-weight: 700;
      color: var(--builtin-primary, #2563eb);
      pointer-events: none;
    }
    .composer textarea {
      min-height: 56px;
      max-height: 170px;
      resize: vertical;
      padding: 15px 14px;
      width: 100%;
      line-height: 1.35;
      border-radius: 14px;
    }
    .composer-main {
      display: grid;
      gap: 8px;
      min-width: 0;
    }
    .drop-hint {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    button {
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      min-height: 34px; padding: 0 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827); cursor: pointer; font-weight: 650;
    }
    button.primary { border-color: var(--builtin-primary, #2563eb); background: var(--builtin-primary, #2563eb); color: #fff; }
    button.danger { border-color: #ef4444; background: #ef4444; color: #fff; }
    button.icon { width: 40px; padding: 0; border-radius: 12px; }
    .composer .icon,
    .composer .primary,
    .composer .danger {
      min-height: 56px;
      align-self: stretch;
      border-radius: 14px;
    }
    .composer-actions {
      display: inline-flex;
      align-items: stretch;
      gap: 8px;
    }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .file-input { display: none; }
    @keyframes dot { 50% { opacity: 1; transform: translateY(-2px); } }
    @media (max-width: 760px) {
      .chat { min-height: 500px; }
      .composer { grid-template-columns: 1fr; }
      .composer-actions { justify-content: stretch; }
      .composer-actions > * { flex: 1 1 0; }
      .composer .icon,
      .composer .primary,
      .composer .danger { min-height: 44px; }
      .bubble-wrap { max-width: 92%; }
    }
  `;

  constructor() {
    super();
    this.messages = [];
    this.placeholder = "";
    this.value = "";
    this.typing = false;
    this.labels = {};
    this.apiBase = "/ai";
    this.endpoint = "/complete";
    this.stream = true;
    this.memoryLimit = 16;
    this.systemPrompt = "You are a helpful assistant.";
    this.maxTokens = 4096;
    this.temperature = null;
    this.reasoning = false;
    this.base64Mode = false;
    this._messages = [];
    this._attachments = [];
    this._generating = false;
    this._settingsOpen = false;
    this._dragActive = false;
    this._abortController = null;
    this._dragDepth = 0;
  }

  connectedCallback() {
    super.connectedCallback();
    this._messages = Array.isArray(this.messages) && this.messages.length ? [...this.messages] : this._demoMessages();
  }

  updated(changed) {
    if (changed.has("messages") && Array.isArray(this.messages) && this.messages !== this._messages) {
      this._messages = this.messages.length ? [...this.messages] : this._demoMessages();
    }
  }

  _demoMessages() {
    return [
      { role: "assistant", content: "Completion workbench ready. I can stream responses, keep recent chat history, and send text or file attachments.", _time: new Date().toISOString() },
      { role: "user", content: "Show the component status.", _time: new Date().toISOString() },
      { role: "assistant", content: "Use the settings dialog, streaming switch, and upload button to test the completion API.", _time: new Date().toISOString() },
    ];
  }

  _l(key, fallback = "") { return this.labels?.[key] ?? this._t(key) ?? fallback; }
  _apiPath(path) { return typeof window.projAiApiPath === "function" ? window.projAiApiPath(`/ai${path}`) : `${this.apiBase}${path}`; }

  _messageText(message) {
    if (typeof message.content === "string") return message.content;
    return JSON.stringify(message.content, null, 2);
  }

  _role(message) { return message.role === "user" ? "user" : (message.role === "error" ? "error" : "assistant"); }

  async _copy(message) {
    await navigator.clipboard?.writeText(this._messageText(message));
  }

  _removeAttachment(index) {
    this._attachments = this._attachments.filter((_, i) => i !== index);
  }

  _onDragEnter(event) {
    event.preventDefault();
    this._dragDepth += 1;
    this._dragActive = true;
  }

  _onDragLeave(event) {
    event.preventDefault();
    this._dragDepth = Math.max(0, this._dragDepth - 1);
    if (!this._dragDepth) this._dragActive = false;
  }

  _onDrop(event) {
    event.preventDefault();
    this._dragDepth = 0;
    this._dragActive = false;
    this._handleFiles(event.dataTransfer?.files);
  }

  async _handleFiles(files) {
    const next = [...this._attachments];
    for (const file of Array.from(files || [])) {
      next.push(await this._readAttachment(file));
    }
    this._attachments = next;
    if (!this.base64Mode) this._attachments.forEach((item) => this._uploadAttachment(item));
  }

  _readAttachment(file) {
    const isText = /^text\//.test(file.type) || /\.(txt|md|csv|json|py|js|ts|html|css|yaml|yml|log)$/i.test(file.name);
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = String(reader.result || "");
        const type = file.type.startsWith("image/") ? "image" : file.type.startsWith("audio/") ? "audio" : file.type.startsWith("video/") ? "video" : isText ? "text" : "file";
        resolve({ type, name: file.name, size: file.size, mimeType: file.type, dataUrl, base64: dataUrl.split(",")[1] || "", textContent: isText ? String(reader.result || "") : "", rawFile: file, uploadStatus: "pending", file_id: null });
      };
      if (isText) reader.readAsText(file);
      else reader.readAsDataURL(file);
    });
  }

  async _uploadAttachment(attachment) {
    if (!attachment?.rawFile || attachment.uploadStatus === "uploading" || attachment.uploadStatus === "done") return;
    attachment.uploadStatus = "uploading";
    this.requestUpdate();
    try {
      const tokenResponse = await fetch(this._apiPath("/upload_temp_file"), { method: "POST" });
      if (!tokenResponse.ok) throw new Error(`token HTTP ${tokenResponse.status}`);
      const tokenData = await tokenResponse.json();
      const formData = new FormData();
      formData.append("file", attachment.rawFile);
      const uploadResponse = await fetch(tokenData.upload_url, { method: "POST", headers: { Authorization: `Bearer ${tokenData.token}` }, body: formData });
      if (!uploadResponse.ok) throw new Error(`upload HTTP ${uploadResponse.status}`);
      const payload = await uploadResponse.json();
      attachment.file_id = payload.file_id;
      attachment.uploadStatus = "done";
    } catch (error) {
      attachment.uploadStatus = "error";
      attachment.uploadError = error?.message || String(error);
    }
    this.requestUpdate();
  }

  _buildContentParts(text, attachments) {
    if (!attachments.length) return text;
    const parts = [];
    for (const item of attachments) {
      if (item.type === "text") parts.push({ type: "text", text: `[file: ${item.name}]\n${item.textContent}` });
      else if (!this.base64Mode && item.file_id) parts.push({ type: "file", file: item.file_id });
      else if (item.type === "image") parts.push({ type: "image_url", image_url: { url: item.dataUrl } });
      else {
        parts.push({ type: "text", text: `[attachment: ${item.name}] (${formatSize(item.size)})` });
        if (item.base64) parts.push({ type: item.type, data: item.base64 });
      }
    }
    if (text) parts.push({ type: "text", text });
    return parts.length === 1 && parts[0].type === "text" ? parts[0].text : parts;
  }

  _settingsPayload() {
    return {
      max_tokens: Number(this.maxTokens) || 4096,
      stream: this.stream,
      reasoning: this.reasoning,
      temperature: this.temperature === null || this.temperature === undefined || this.temperature === "" ? null : Number(this.temperature),
    };
  }

  _settingsValue() {
    return {
      systemPrompt: this.systemPrompt || "",
      memoryLimit: Number(this.memoryLimit) || 16,
      maxTokens: Number(this.maxTokens) || 4096,
      temperature: this.temperature ?? "",
      stream: !!this.stream,
      reasoning: !!this.reasoning,
      base64Mode: !!this.base64Mode,
    };
  }

  _settingsSchema() {
    return [
      { name: "systemPrompt", label: "System prompt", type: "textarea", span: 2 },
      { name: "memoryLimit", label: "Memory", type: "number", min: 1, max: 64 },
      { name: "maxTokens", label: "Max tokens", type: "number", min: 1 },
      { name: "temperature", label: "Temperature", type: "number", min: 0, max: 2, step: 0.1 },
      { name: "stream", label: "Stream response", type: "checkbox" },
      { name: "reasoning", label: "Reasoning", type: "checkbox" },
      { name: "base64Mode", label: "Send files as base64", type: "checkbox", span: 2 },
    ];
  }

  _applySettings(values = {}) {
    if (Object.prototype.hasOwnProperty.call(values, "systemPrompt")) this.systemPrompt = values.systemPrompt || "";
    if (Object.prototype.hasOwnProperty.call(values, "memoryLimit")) this.memoryLimit = Number(values.memoryLimit) || 16;
    if (Object.prototype.hasOwnProperty.call(values, "maxTokens")) this.maxTokens = Number(values.maxTokens) || 4096;
    if (Object.prototype.hasOwnProperty.call(values, "temperature")) this.temperature = values.temperature === "" || values.temperature === null ? null : Number(values.temperature);
    if (Object.prototype.hasOwnProperty.call(values, "stream")) this.stream = !!values.stream;
    if (Object.prototype.hasOwnProperty.call(values, "reasoning")) this.reasoning = !!values.reasoning;
    if (Object.prototype.hasOwnProperty.call(values, "base64Mode")) this.base64Mode = !!values.base64Mode;
  }

  async _ensureUploads() {
    if (this.base64Mode) return;
    await Promise.all(this._attachments.map((item) => this._uploadAttachment(item)));
  }

  async _send() {
    if (this._generating) return;
    const text = (this.value || "").trim();
    if (!text && !this._attachments.length) return;
    await this._ensureUploads();
    const attachments = this._attachments.map((item) => ({ type: item.type, name: item.name, size: item.size, dataUrl: item.dataUrl, mimeType: item.mimeType }));
    const content = this._buildContentParts(text, this._attachments);
    this._messages = [...this._messages, { role: "user", content, _time: new Date().toISOString(), _attachments: attachments }];
    this.value = "";
    this._attachments = [];
    this.dispatchEvent(new CustomEvent("builtin-ai-chat-send", { detail: { content }, bubbles: true, composed: true }));
    this._requestCompletion();
  }

  async _requestCompletion() {
    const assistant = { role: "assistant", content: "", _time: new Date().toISOString(), _streaming: true };
    this._messages = [...this._messages, assistant];
    this._generating = true;
    this._abortController = new AbortController();
    const history = this._messages.filter((item) => item.role === "user" || item.role === "assistant").slice(-Math.max(1, Number(this.memoryLimit) || 16));
    const body = { ...this._settingsPayload(), messages: [{ role: "system", content: this.systemPrompt || "You are a helpful assistant." }, ...history.map((item) => ({ role: item.role, content: item.content }))] };
    const started = performance.now();
    try {
      if (this.stream) await this._streamCompletion(body, assistant);
      else await this._completeOnce(body, assistant);
      assistant._clientMs = Math.round(performance.now() - started);
      assistant._streaming = false;
    } catch (error) {
      assistant.role = error?.name === "AbortError" ? "assistant" : "error";
      assistant.content = error?.name === "AbortError" ? (assistant.content || "[stopped]") : `Error: ${error?.message || error}`;
      assistant._streaming = false;
    } finally {
      this._generating = false;
      this._abortController = null;
      this.requestUpdate();
    }
  }

  async _completeOnce(body, assistant) {
    const response = await fetch(this._apiPath(this.endpoint || "/complete"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: this._abortController.signal });
    if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`);
    const data = await response.json();
    assistant.content = data.text || data.content || "";
    assistant.elapsed_ms = data.elapsed_ms;
    assistant.token_usage = data.token_usage;
    this.requestUpdate();
  }

  async _streamCompletion(body, assistant) {
    const response = await fetch(this._apiPath(this.endpoint || "/complete"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, stream: true }), signal: this._abortController.signal });
    if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload || payload === "[DONE]") continue;
        try {
          const data = JSON.parse(payload);
          if (data.error) {
            throw new Error(data.error);
          } else if (data.done) {
            assistant.elapsed_ms = data.elapsed_ms;
            assistant.token_usage = data.token_usage;
          } else if (data.type === "think") {
            assistant.thinkContent = `${assistant.thinkContent || ""}${data.data || ""}`;
          } else {
            assistant.content = `${assistant.content || ""}${data.data || data.text || ""}`;
          }
        } catch (_error) {
          assistant.content = `${assistant.content || ""}${payload}`;
        }
      }
      this.requestUpdate();
      await this.updateComplete;
      this._scrollBottom();
    }
  }

  _stop() {
    this._abortController?.abort();
  }

  _closeSettings() {
    this._settingsOpen = false;
  }

  _onKeydown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      this._send();
    }
  }

  _scrollBottom() {
    const messages = this.renderRoot.querySelector(".messages");
    if (messages) messages.scrollTop = messages.scrollHeight;
  }

  _renderAttachment(item, index, removable = false) {
    return html`
      <span class="attachment">
        ${item.type === "image" && item.dataUrl
          ? html`<img src=${item.dataUrl} alt="">`
          : html`<builtin-icon name="file" size="16" variant="outlined"></builtin-icon>`}
        <span class="attachment-copy">
          <span class="name" title=${item.name}>${item.name}</span>
          <span class="attachment-meta">${formatSize(item.size)}${item.uploadStatus ? ` • ${item.uploadStatus}` : ""}</span>
        </span>
        ${removable
          ? html`<button class="icon" style="width:24px;height:24px;min-height:24px;padding:0" title=${this._l("remove", "Remove")} @click=${() => this._removeAttachment(index)}><builtin-icon name="close" size="12" variant="outlined"></builtin-icon></button>`
          : ""}
      </span>
    `;
  }

  render() {
    const messages = this._messages.length ? this._messages : this._demoMessages();
    return html`
      <div class="chat" @dragenter=${this._onDragEnter} @dragover=${(event) => event.preventDefault()} @dragleave=${this._onDragLeave} @drop=${this._onDrop}>
        <div class="topbar">
          <div class="brand"><builtin-icon name="robot" size="18" variant="outlined"></builtin-icon><span>${this._l("chat.title", "AI Chatbot")}</span></div>
          <div class="topbar-actions">
            ${this._generating ? html`<span class="meta">${this._l("chat.generating", "Generating")}</span>` : ""}
            <button class="icon" @click=${() => { this._settingsOpen = !this._settingsOpen; }} title=${this._l("settings", "Settings")}><builtin-icon name="setting" size="16" variant="outlined"></builtin-icon></button>
            <button class="icon" @click=${() => { this._messages = []; }} title=${this._l("clear", "Clear")}><builtin-icon name="delete" size="16" variant="outlined"></builtin-icon></button>
          </div>
        </div>
        <div class="settings-backdrop" ?hidden=${!this._settingsOpen} @click=${() => this._closeSettings()}>
          <div class="settings-dialog" role="dialog" aria-modal="true" aria-label=${this._l("settings", "Settings")} @click=${(event) => event.stopPropagation()}>
            <div class="settings-head"><span class="settings-title">${this._l("settings", "Settings")}</span><button class="icon" @click=${() => this._closeSettings()}><builtin-icon name="close" size="16" variant="outlined"></builtin-icon></button></div>
            <div class="settings-body">
              <builtin-schema-form
                .schema=${this._settingsSchema()}
                .value=${this._settingsValue()}
                columns="2"
                density="comfortable"
                hide-reset
                submit-label="Done"
                @builtin-change=${(event) => this._applySettings(event.detail.values)}
                @builtin-submit=${(event) => { event.preventDefault(); this._applySettings(event.detail.value); this._closeSettings(); }}
              ></builtin-schema-form>
            </div>
          </div>
        </div>
        <div class="messages">
          ${repeat(messages, (message, index) => message.id || `${index}-${message.role}`, (message, index) => html`
            <div class="row ${this._role(message)}">
              ${this._role(message) !== "user" ? html`<span class="avatar"><builtin-icon name="robot" size="16" variant="outlined"></builtin-icon></span>` : ""}
              <div class="bubble-wrap">
                ${message._attachments?.length ? html`<div class="attachments">${message._attachments.map((item) => this._renderAttachment(item))}</div>` : ""}
                ${message.thinkContent ? html`<div class="bubble">${message.thinkContent}</div>` : ""}
                <div class="bubble">${message._streaming && !message.content ? html`<span class="typing"><span></span><span></span><span></span></span>` : this._messageText(message)}</div>
                <div class="meta"><span>${message._time ? new Date(message._time).toLocaleTimeString() : ""}</span>${message.elapsed_ms ? html`<span>${message.elapsed_ms}ms</span>` : ""}<button class="icon" style="width:24px;height:22px;min-height:22px;padding:0" @click=${() => this._copy(message)}><builtin-icon name="copy" size="12" variant="outlined"></builtin-icon></button></div>
              </div>
            </div>
          `)}
          ${this.typing ? html`<div class="row assistant"><span class="avatar"><builtin-icon name="robot" size="16" variant="outlined"></builtin-icon></span><div class="bubble"><span class="typing"><span></span><span></span><span></span></span></div></div>` : ""}
        </div>
        <div class="composer-shell">
          ${this._attachments.length ? html`
            <div class="pending">
              <div class="pending-head">
                <span>${this._l("attachments", "Attachments")}</span>
                <span>${this._attachments.length} ${this._l("items", "item(s)")}</span>
              </div>
              <div class="pending-list">${this._attachments.map((item, index) => this._renderAttachment(item, index, true))}</div>
            </div>
          ` : ""}
          <div class="composer ${this._dragActive ? "drag-active" : ""}">
            ${this._dragActive ? html`<div class="composer-dropzone">${this._l("chat.dropFiles", "Drop files to attach")}</div>` : ""}
            <button class="icon" @click=${() => this.renderRoot.querySelector(".file-input")?.click()} title=${this._l("upload", "Upload")}><builtin-icon name="cloud-upload" size="18" variant="outlined"></builtin-icon></button>
            <input class="file-input" type="file" multiple accept="image/*,audio/*,video/*,.pdf,.txt,.md,.csv,.json,.py,.js,.ts,.html,.css" @change=${(event) => { this._handleFiles(event.target.files); event.target.value = ""; }}>
            <div class="composer-main">
              <textarea .value=${this.value} placeholder=${this.placeholder || this._l("chat.placeholder", "Message AI...")} @input=${(event) => { this.value = event.target.value; }} @keydown=${this._onKeydown}></textarea>
              <div class="composer-meta">
                <span class="drop-hint"><builtin-icon name="file" size="14" variant="outlined"></builtin-icon>${this._l("chat.dropHint", "Drag files here or use upload")}</span>
                <span>${this._l("chat.enterToSend", "Enter to send, Shift+Enter for newline")}</span>
              </div>
            </div>
            <div class="composer-actions">
              ${this._generating ? html`<button class="danger" @click=${this._stop}><builtin-icon name="stop" size="16" variant="outlined"></builtin-icon>${this._l("stop", "Stop")}</button>` : ""}
              <button class="primary" @click=${this._send} ?disabled=${this._generating || (!String(this.value || "").trim() && !this._attachments.length)}><builtin-icon name="send" size="16" variant="outlined"></builtin-icon>${this._l("send", "Send")}</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }
}