import { BuiltinBaseElement, html, css, classMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

/**
 * @fileoverview Reusable message list component for chat UIs.
 *
 * @description Renders a scrollable list of message bubbles with avatars,
 * names, timestamps, optional reply references, and read receipts.
 *
 * Attributes:
 *   - messages: JSON array of {id, sender, text, time, self, replyTo, read}
 *   - labels: JSON object to override i18n strings
 *
 * Events:
 *   - builtin-reply: Fired when a message reply action is triggered.
 *   - builtin-load-more: Fired when the user scrolls to the top.
 *
 * Usage example:
 *   ```html
 *   <builtin-tpl-chat-message-thread
 *     messages='[
 *       {"id":1,"sender":"Alice","text":"Hi!","time":"10:00","self":false,"read":true}
 *     ]'>
 *   </builtin-tpl-chat-message-thread>
 *   ```
 */
export class BuiltinTplChatMessageThread extends BuiltinBaseElement {
  static properties = {
    messages: { type: Array, converter: jsonConverter },
    labels: { type: Object, converter: jsonConverter },
    searchQuery: { type: String, attribute: "search-query" },
    historyMode: { type: String, attribute: "history-mode" },
    showActions: { type: Boolean, attribute: "show-actions" },
    activeMessageId: { type: String, attribute: "active-message-id" },
  };

  static styles = css`
    :host {
      display: block;
      font-family: inherit;
      color: var(--builtin-color-text, #111827);
      background: transparent;
      line-height: 1.55;
    }
    .message-list {
      display: flex;
      flex-direction: column;
      gap: 14px;
      max-height: 100%;
      overflow-y: auto;
      padding: 4px 4px 12px;
    }
    .history-marker {
      align-self: center;
      padding: 6px 12px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 78%, transparent);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.02em;
      text-transform: uppercase;
      backdrop-filter: blur(12px);
      position: sticky;
      top: 6px;
      z-index: 1;
    }
    .message.event {
      max-width: 100%;
      align-self: center;
      justify-content: center;
    }
    .message {
      display: flex;
      gap: 10px;
      max-width: 80%;
      position: relative;
    }
    .message.is-active .bubble,
    .message.is-active .attachment-card,
    .message:hover .bubble,
    .message:hover .attachment-card {
      box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
    }
    .message[data-self="true"] {
      align-self: flex-end;
      flex-direction: row-reverse;
    }
    .message[data-self="true"] .bubble {
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      border-bottom-right-radius: 2px;
    }
    .message[data-self="true"] .meta,
    .message[data-self="true"] .message-state,
    .message[data-self="true"] .reactions,
    .message[data-self="true"] .actions { justify-content: flex-end; }
    .message[data-self="true"] .message-state { text-align: right; }
    .message.event .bubble {
      border-style: dashed;
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 92%, transparent);
      color: var(--builtin-color-muted, #6b7280);
      border-radius: 999px;
      padding: 8px 14px;
    }
    .avatar-wrap {
      flex-shrink: 0;
      width: 36px;
      height: 36px;
    }
    .avatar-wrap button {
      border: 0;
      background: transparent;
      padding: 0;
      cursor: pointer;
      border-radius: 50%;
    }
    .content {
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .meta {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      font-size: 12px;
    }
    .sender-name { font-weight: 600; }
    .sender-name.clickable {
      cursor: pointer;
      text-decoration: underline;
      text-decoration-color: transparent;
      transition: text-decoration-color .15s ease;
    }
    .sender-name.clickable:hover {
      text-decoration-color: currentColor;
    }
    .sender-role {
      padding: 2px 6px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 10%, transparent);
      color: var(--builtin-primary, #2563eb);
      font-size: 11px;
      font-weight: 600;
    }
    .time { color: var(--builtin-color-muted, #6b7280); }
    .badge {
      padding: 2px 6px;
      border-radius: 999px;
      background: var(--builtin-header-bg, #f9fafb);
      color: var(--builtin-color-muted, #6b7280);
      font-size: 11px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .bubble {
      padding: 10px 14px;
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-header-bg, #f9fafb);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-bottom-left-radius: 2px;
      word-break: break-word;
      transition: box-shadow .18s ease, transform .18s ease;
    }
    .message-text {
      white-space: pre-wrap;
    }
    .message-text mark,
    .reply-ref mark,
    .attachment-meta mark {
      background: color-mix(in srgb, #facc15 72%, transparent);
      color: inherit;
      padding: 0 2px;
      border-radius: 4px;
    }
    .reply-ref {
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      margin-bottom: 6px;
      padding-left: 8px;
      border-left: 2px solid var(--builtin-border, #d1d5db);
    }
    .message[data-self="true"] .reply-ref {
      border-left-color: rgba(255,255,255,0.5);
      color: rgba(255,255,255,0.85);
    }
    .edited-flag {
      margin-left: 4px;
      font-size: 11px;
      opacity: 0.8;
    }
    .message-state {
      font-size: 11px;
      color: var(--builtin-color-muted, #6b7280);
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .message[data-self="true"] .message-state { color: rgba(255,255,255,0.82); }
    .attachments {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .attachment-card {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 12px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: 14px;
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 90%, transparent);
      color: inherit;
      transition: box-shadow .18s ease, transform .18s ease;
    }
    .attachment-card.clickable {
      cursor: pointer;
    }
    .attachment-card.clickable:hover {
      transform: translateY(-1px);
    }
    .message[data-self="true"] .attachment-card {
      background: rgba(255,255,255,0.14);
      border-color: rgba(255,255,255,0.18);
    }
    .attachment-thumb {
      width: 100%;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      border-radius: 10px;
      background: var(--builtin-header-bg, #f9fafb);
    }
    .attachment-audio {
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: var(--builtin-surface, #ffffff);
    }
    .attachment-head {
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }
    .attachment-icon {
      width: 38px;
      height: 38px;
      border-radius: 12px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 12%, transparent);
      color: var(--builtin-primary, #2563eb);
      flex-shrink: 0;
    }
    .attachment-meta {
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .attachment-title {
      font-size: 13px;
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .attachment-subtitle {
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .message[data-self="true"] .attachment-subtitle {
      color: rgba(255,255,255,0.78);
    }
    .reactions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .reaction-chip {
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 999px;
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      padding: 4px 8px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      font-size: 12px;
      transition: border-color .15s ease, transform .15s ease, background .15s ease;
    }
    .reaction-chip:hover {
      transform: translateY(-1px);
      border-color: var(--builtin-primary, #2563eb);
    }
    .reaction-chip.active {
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 12%, transparent);
      color: var(--builtin-primary, #2563eb);
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 35%, transparent);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .actions button {
      font-size: 12px;
      padding: 5px 10px;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .actions button:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .message[data-self="true"] .actions button {
      background: rgba(255,255,255,0.12);
      border-color: rgba(255,255,255,0.18);
      color: #fff;
    }
    .message[data-self="true"] .actions button:hover {
      background: rgba(255,255,255,0.2);
    }
    .icon { width: 14px; height: 14px; vertical-align: middle; }

    @media (max-width: 720px) {
      .message { max-width: 100%; gap: 8px; }
      .avatar-wrap { width: 28px; height: 28px; }
      .bubble { padding: 8px 12px; font-size: 14px; }
      .meta { font-size: 11px; }
      .attachments { grid-template-columns: 1fr; }
      .actions { gap: 6px; }
      .actions button { padding-inline: 8px; }
    }
  `;

  constructor() {
    super();
    this.searchQuery = "";
    this.historyMode = "thread";
    this.showActions = true;
    this.activeMessageId = "";
    this.messages = [
      {
        id: 1,
        sender: "Alice",
        senderRole: "Admin",
        text: "Hey there! How is it going?",
        time: "10:00",
        self: false,
        read: true,
        category: "Today",
        reactions: [{ emoji: "OK", count: 2, label: "Approved" }],
      },
      {
        id: 2,
        sender: "You",
        text: "Pretty good, thanks! Working on the new components.",
        time: "10:02",
        self: true,
        read: true,
        attachments: [{ id: "file-1", name: "chat-spec.pdf", type: "file", sizeLabel: "2.4 MB" }],
      },
      {
        id: 3,
        sender: "Alice",
        text: "Nice! Let me know when they are ready for review.",
        time: "10:05",
        self: false,
        read: false,
        replyTo: "Working on the new components.",
      },
    ];
  }

  _onScroll(e) {
    const list = e.currentTarget;
    if (list.scrollTop <= 10) {
      this.dispatchEvent(new CustomEvent("builtin-load-more", { bubbles: true, composed: true }));
    }
  }

  _onReply(id) {
    this._emitMessageAction("builtin-reply", { id });
  }

  _emitMessageAction(type, detail) {
    this.dispatchEvent(new CustomEvent(type, {
      detail,
      bubbles: true,
      composed: true,
    }));
  }

  _dispatch(type, detail) {
    this.dispatchEvent(new CustomEvent(type, {
      detail,
      bubbles: true,
      composed: true,
    }));
  }

  _emitMemberOpen(message) {
    if (!message?.sender) return;
    this._dispatch("builtin-member-open", {
      id: message.senderId ?? message.sender,
      sender: message.sender,
      senderRole: message.senderRole,
      status: message.senderStatus,
      message,
    });
  }

  _emitAttachmentOpen(message, attachment) {
    this._dispatch("builtin-attachment-open", {
      messageId: message.id,
      message,
      attachment,
    });
  }

  _onAction(type, message, extra = {}) {
    this._dispatch(type, {
      id: message.id,
      message,
      ...extra,
    });
  }

  _normalizeText(value) {
    return typeof value === "string" ? value : "";
  }

  _searchNeedle() {
    return this._normalizeText(this.searchQuery).trim().toLowerCase();
  }

  _matchesSearch(message) {
    const needle = this._searchNeedle();
    if (!needle) return true;
    const text = [
      message?.sender,
      message?.text,
      message?.replyTo,
      message?.category,
      ...(Array.isArray(message?.attachments) ? message.attachments.flatMap((attachment) => [attachment?.name, attachment?.typeLabel, attachment?.sizeLabel]) : []),
    ]
      .filter((item) => typeof item === "string" && item)
      .join("\n")
      .toLowerCase();
    return text.includes(needle);
  }

  _highlight(text) {
    const source = this._normalizeText(text);
    const needle = this._searchNeedle();
    if (!needle || !source) return source;
    const lower = source.toLowerCase();
    const parts = [];
    let cursor = 0;
    while (cursor < source.length) {
      const next = lower.indexOf(needle, cursor);
      if (next === -1) {
        parts.push(source.slice(cursor));
        break;
      }
      if (next > cursor) {
        parts.push(source.slice(cursor, next));
      }
      parts.push(html`<mark>${source.slice(next, next + needle.length)}</mark>`);
      cursor = next + needle.length;
    }
    return parts;
  }

  _formatAttachmentKind(attachment) {
    const kind = this._normalizeText(attachment?.type || attachment?.kind).toLowerCase();
    if (kind === "image") return this._l("attachment.image", "Image");
    if (kind === "audio") return this._l("attachment.audio", "Voice note");
    if (kind === "video") return this._l("attachment.video", "Video");
    return this._normalizeText(attachment?.typeLabel) || this._l("attachment.file", "File");
  }

  _renderAttachment(message, attachment) {
    const kind = this._normalizeText(attachment?.type || attachment?.kind).toLowerCase();
    const clickable = !!(attachment?.url || attachment?.thumbnail || kind === "audio");
    const classes = classMap({ "attachment-card": true, clickable });
    return html`
      <div class="${classes}" @click=${clickable ? () => this._emitAttachmentOpen(message, attachment) : nothing}>
        ${kind === "image" && attachment?.thumbnail
          ? html`<img class="attachment-thumb" src="${attachment.thumbnail}" alt="${attachment.name || this._l("attachment.preview", "Attachment preview")}" />`
          : ""}
        ${kind === "audio" && attachment?.url
          ? html`
              <div class="attachment-audio" @click=${(event) => event.stopPropagation()}>
                <builtin-audio-player
                  mode="compact"
                  src="${attachment.url}"
                  title="${attachment.name || this._l("attachment.audio", "Voice note")}"
                ></builtin-audio-player>
              </div>
            `
          : ""}
        <div class="attachment-head">
          <div class="attachment-icon">
            <builtin-icon name="paper-clip" size="18" variant="outlined"></builtin-icon>
          </div>
          <div class="attachment-meta">
            <div class="attachment-title">${this._highlight(attachment?.name || this._l("attachment.untitled", "Untitled attachment"))}</div>
            <div class="attachment-subtitle">
              ${this._highlight([this._formatAttachmentKind(attachment), attachment?.sizeLabel, attachment?.durationLabel].filter(Boolean).join(" · "))}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderReactions(message) {
    const reactions = Array.isArray(message?.reactions) ? message.reactions : [];
    if (!reactions.length) return "";
    return html`
      <div class="reactions">
        ${reactions.map((reaction) => html`
          <button
            class="reaction-chip ${classMap({ active: reaction.active })}"
            @click=${(event) => {
              event.stopPropagation();
              this._onAction("builtin-react", message, { reaction });
            }}
          >
            <span>${reaction.emoji || reaction.label || "+"}</span>
            <span>${reaction.count ?? 1}</span>
          </button>
        `)}
      </div>
    `;
  }

  _renderActions(message) {
    if (this.showActions === false || message?.system || message?.kind === "event") {
      return "";
    }
    const actionSpecs = [
      { type: "builtin-reply", key: "action.reply", label: "Reply" },
      { type: "builtin-quote", key: "action.quote", label: "Quote" },
      { type: "builtin-like", key: "action.like", label: message?.liked ? "Liked" : "Like" },
      { type: "builtin-edit", key: "action.edit", label: "Edit", hidden: message?.editable === false },
      { type: "builtin-recall", key: "action.recall", label: "Recall", hidden: message?.recallable === false },
    ].filter((spec) => !spec.hidden);
    return html`
      <div class="actions">
        ${actionSpecs.map((spec) => html`
          <button @click=${(event) => {
            event.stopPropagation();
            this._onAction(spec.type, message);
          }}>
            ${this._l(spec.key, spec.label)}
          </button>
        `)}
      </div>
    `;
  }

  _renderBubble(message) {
    const isRecalled = message?.recalled === true;
    const text = isRecalled
      ? this._l("message.recalled", "This message was recalled")
      : this._normalizeText(message?.text || message?.eventText);
    return html`
      <div class="bubble">
        ${message?.replyTo ? html`<div class="reply-ref">${this._l("reply.prefix", "Re:")} ${this._highlight(message.replyTo)}</div>` : ""}
        <div class="message-text">${this._highlight(text)}</div>
        ${message?.edited && !isRecalled ? html`<span class="edited-flag">${this._l("message.edited", "edited")}</span>` : ""}
        ${Array.isArray(message?.attachments) && message.attachments.length
          ? html`<div class="attachments">${message.attachments.map((attachment) => this._renderAttachment(message, attachment))}</div>`
          : ""}
      </div>
    `;
  }

  _renderMessage(message) {
    const self = message?.self === true;
    const isEvent = message?.kind === "event" || message?.system === true;
    const active = String(this.activeMessageId || "") === String(message?.id || "");
    const messageClasses = classMap({ message: true, event: isEvent, "is-active": active });
    return html`
      <div
        class="${messageClasses}"
        data-self="${self}"
        data-id="${message.id}"
        @click=${() => this._onAction("builtin-message-select", message)}
      >
        ${isEvent
          ? ""
          : html`
              <div class="avatar-wrap">
                <button @click=${(event) => { event.stopPropagation(); this._emitMemberOpen(message); }} aria-label="${this._l("member.open", "Open member details")}">
                  <builtin-avatar size="${this._ptMobile ? 28 : 36}" name="${message.sender}"></builtin-avatar>
                </button>
              </div>
            `}
        <div class="content">
          ${isEvent
            ? ""
            : html`
                <div class="meta">
                  <span
                    class="sender-name ${classMap({ clickable: true })}"
                    @click=${(event) => { event.stopPropagation(); this._emitMemberOpen(message); }}
                  >${this._highlight(message.sender || this._l("message.unknownSender", "Unknown"))}</span>
                  ${message?.senderRole ? html`<span class="sender-role">${this._highlight(message.senderRole)}</span>` : ""}
                  <span class="time">${message.time || ""}</span>
                  ${message?.badge ? html`<span class="badge">${this._highlight(message.badge)}</span>` : ""}
                </div>
              `}
          ${this._renderBubble(message)}
          ${!isEvent ? html`
            ${message?.self
              ? html`
                  <div class="message-state">
                    <span>${message.read ? this._l("read.read", "Read") : this._l("read.sent", "Sent")}</span>
                    ${message?.delivery ? html`<span>${message.delivery}</span>` : ""}
                  </div>
                `
              : ""}
            ${this._renderReactions(message)}
            ${this._renderActions(message)}
          ` : ""}
        </div>
      </div>
    `;
  }

  render() {
    const msgs = Array.isArray(this.messages) ? this.messages.filter((message) => this._matchesSearch(message)) : [];
    let lastCategory = "";

    return html`
      <div class="message-list" @scroll=${this._onScroll}>
        ${repeat(msgs, (m) => m.id, (m) => {
          const category = this._normalizeText(m?.category || m?.dateLabel);
          const showCategory = category && (this.historyMode === "history" || category !== lastCategory);
          lastCategory = category || lastCategory;
          return html`
            ${showCategory ? html`<div class="history-marker">${this._highlight(category)}</div>` : ""}
            ${this._renderMessage(m)}
          `;
        })}
      </div>
    `;
  }
}