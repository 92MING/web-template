import { BuiltinBaseElement, html, css, classMap, styleMap } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try {
      return JSON.parse(value);
    } catch {
      return undefined;
    }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  },
};

export class BuiltinTplChatRoom extends BuiltinBaseElement {
  static properties = {
    chatName: { type: String, attribute: "chat-name" },
    status: { type: String },
    selected: { type: Boolean },
    labels: { type: Object, converter: jsonConverter },
    conversations: { type: Array, converter: jsonConverter },
    messages: { type: Array, converter: jsonConverter },
    members: { type: Array, converter: jsonConverter },
    historyGroups: { type: Array, converter: jsonConverter, attribute: "history-groups" },
    callCards: { type: Array, converter: jsonConverter, attribute: "call-cards" },
    quickEmojis: { type: Array, converter: jsonConverter, attribute: "quick-emojis" },
    draftAttachments: { type: Array, converter: jsonConverter, attribute: "draft-attachments" },
    composerValue: { type: String, attribute: "composer-value" },
    inputPlaceholder: { type: String, attribute: "input-placeholder" },
    searchQuery: { type: String, attribute: "search-query" },
    historyFilter: { type: String, attribute: "history-filter" },
    activeConversationId: { type: String, attribute: "active-conversation-id" },
    activeInfoTab: { type: String, attribute: "active-info-tab" },
    activeCall: { type: Object, converter: jsonConverter, attribute: "active-call" },
    showInfoPanel: { type: Boolean, attribute: "show-info-panel" },
    allowUploads: { type: Boolean, attribute: "allow-uploads" },
    attachmentAccept: { type: String, attribute: "attachment-accept" },
    _searchOpen: { type: Boolean, state: true },
    _infoOpen: { type: Boolean, state: true },
    _uploadModalOpen: { type: Boolean, state: true },
    _replyMessage: { type: Object, state: true },
    _memberDetailOpen: { type: Boolean, state: true },
    _selectedMember: { type: Object, state: true },
    _previewAttachment: { type: Object, state: true },
    _recording: { type: Boolean, state: true },
    _localDraftAttachments: { type: Array, state: true },
  };

  static styles = css`
    :host {
      display: flex;
      height: 100vh;
      font-family: inherit;
      color: var(--builtin-color-text, #111827);
      background: var(--builtin-surface, #ffffff);
      line-height: 1.55;
      overflow: hidden;
      position: relative;
    }
    h1, h2, h3, h4, p { margin: 0; }
    button, input, textarea { font: inherit; }
    button { color: inherit; }
    .sidebar {
      width: min(320px, 28vw);
      flex-shrink: 0;
      border-right: 1px solid var(--builtin-border-soft, #e5e7eb);
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.14), transparent 34%),
        linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 92%, #ffffff), var(--builtin-header-bg, #f9fafb));
      display: flex;
      flex-direction: column;
      min-width: 0;
    }
    .sidebar-header {
      padding: 18px 18px 14px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: 14px;
    }
    .sidebar-brand {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    .sidebar-brand-main {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .sidebar-brand-copy {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .sidebar-eyebrow {
      font-size: 11px;
      color: var(--builtin-color-muted, #6b7280);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }
    .sidebar-title {
      font-size: 18px;
      font-weight: 700;
    }
    .sidebar-actions,
    .header-actions,
    .call-stage-actions,
    .member-actions,
    .call-actions,
    .composer-left,
    .composer-right,
    .quick-emoji-list,
    .sidebar-filters,
    .history-filters,
    .conversation-tags,
    .member-tags,
    .call-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .ghost-icon-btn,
    .tab-btn,
    .info-action,
    .dismiss-btn,
    .filter-chip,
    .quick-emoji,
    .member-btn,
    .secondary-btn,
    .primary-btn,
    .composer-send {
      border: 1px solid var(--builtin-border, #d1d5db);
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 90%, transparent);
      border-radius: 12px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: background .15s ease, border-color .15s ease, transform .15s ease;
      padding: 0;
    }
    .ghost-icon-btn:hover,
    .tab-btn:hover,
    .info-action:hover,
    .dismiss-btn:hover,
    .filter-chip:hover,
    .quick-emoji:hover,
    .member-btn:hover,
    .secondary-btn:hover,
    .primary-btn:hover,
    .composer-send:hover {
      transform: translateY(-1px);
      border-color: var(--builtin-primary, #2563eb);
    }
    .ghost-icon-btn,
    .dismiss-btn {
      width: 38px;
      height: 38px;
      flex-shrink: 0;
    }
    .search-card,
    .search-strip {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: 14px;
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 92%, transparent);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.18);
    }
    .search-card input,
    .search-strip input,
    .composer-input {
      flex: 1 1 auto;
      border: none;
      background: transparent;
      color: inherit;
      min-width: 0;
      font: inherit;
      outline: none;
    }
    .filter-chip,
    .quick-emoji,
    .tab-btn,
    .info-action,
    .member-btn,
    .secondary-btn,
    .primary-btn,
    .composer-send {
      padding: 9px 12px;
      font-size: 12px;
      font-weight: 700;
    }
    .filter-chip.active,
    .quick-emoji.active,
    .tab-btn.active {
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 16%, transparent);
      color: var(--builtin-primary, #2563eb);
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 32%, transparent);
    }
    .quick-emoji { font-size: 11px; }
    .conversation-tag,
    .member-tag,
    .call-tag {
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 90%, transparent);
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
      font-weight: 600;
    }
    .conv-list {
      flex: 1 1 auto;
      overflow-y: auto;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .conv-item {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      width: 100%;
      padding: 14px;
      cursor: pointer;
      border: 1px solid transparent;
      border-radius: 18px;
      transition: background .15s ease, border-color .15s ease, transform .15s ease;
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 90%, transparent);
      text-align: left;
    }
    .conv-item:hover {
      background: color-mix(in srgb, var(--builtin-row-hover-bg, #f9fafb) 85%, transparent);
      transform: translateY(-1px);
    }
    .conv-item.active {
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 28%, transparent);
      background: color-mix(in srgb, var(--builtin-primary, #2563eb) 10%, var(--builtin-surface, #ffffff));
      box-shadow: 0 18px 34px rgba(37, 99, 235, 0.10);
    }
    .conv-meta { flex: 1 1 auto; min-width: 0; }
    .conv-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
      min-width: 0;
    }
    .conv-name {
      flex: 1 1 auto;
      min-width: 0;
      font-weight: 600;
      font-size: 14px;
      line-height: 1.4;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .conv-msg {
      font-size: 13px;
      color: var(--builtin-color-muted, #6b7280);
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      margin-bottom: 8px;
    }
    .conv-time {
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
      white-space: nowrap;
      font-weight: 600;
    }
    .conv-tail {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 10px;
      flex: 0 1 96px;
      min-width: 0;
      max-width: 96px;
    }
    .conv-tail .conv-time {
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .conv-unread {
      min-width: 22px;
      min-height: 22px;
      padding: 0 7px;
      border-radius: 999px;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 700;
      flex-shrink: 0;
    }
    .main {
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
      min-width: 0;
      background:
        radial-gradient(circle at top, rgba(37, 99, 235, 0.08), transparent 28%),
        var(--builtin-surface, #ffffff);
    }
    .main-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px 12px;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 92%, transparent);
      backdrop-filter: blur(18px);
    }
    .header-shell,
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .header-info {
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .header-info h2 { font-size: 16px; font-weight: 700; }
    .header-presence {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 12px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .presence-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #22c55e;
      display: inline-block;
    }
    .back-btn {
      display: none;
      padding: 8px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: 12px;
      background: color-mix(in srgb, var(--builtin-button-bg, #ffffff) 90%, transparent);
      cursor: pointer;
      font-size: 13px;
      align-items: center;
      gap: 6px;
    }
    .search-strip { margin: 14px 16px 0; }
    .call-stage {
      margin: 14px 16px 0;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid color-mix(in srgb, var(--builtin-primary, #2563eb) 24%, transparent);
      background: linear-gradient(135deg, rgba(37, 99, 235, 0.10), rgba(6, 182, 212, 0.10));
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 14px;
      align-items: center;
    }
    .call-stage h3 {
      font-size: 15px;
      margin-bottom: 4px;
    }
    .call-stage p {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      margin-bottom: 10px;
    }
    .primary-btn,
    .composer-send {
      border-color: var(--builtin-primary, #2563eb);
      background: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .messages {
      flex: 1 1 auto;
      overflow-y: auto;
      padding: 16px;
      background: transparent;
    }
    .input-area {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 14px 16px 16px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 94%, transparent);
      backdrop-filter: blur(18px);
    }
    .reply-banner,
    .draft-attachments {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .reply-pill,
    .attachment-chip,
    .history-item,
    .member-card,
    .call-card,
    .attachment-preview-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 92%, transparent);
      box-shadow: 0 14px 34px rgba(15, 23, 42, 0.06);
      border-radius: 16px;
    }
    .reply-pill {
      width: 100%;
      padding: 10px 12px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }
    .reply-pill strong,
    .member-name,
    .history-title,
    .call-title { font-size: 13px; }
    .reply-pill p,
    .member-meta,
    .history-meta,
    .call-meta {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 12px;
    }
    .composer-shell {
      display: flex;
      align-items: flex-end;
      gap: 12px;
      padding: 10px 12px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: 20px;
      background: color-mix(in srgb, var(--builtin-surface, #ffffff) 94%, transparent);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.18);
    }
    .composer-main {
      display: flex;
      flex-direction: column;
      gap: 10px;
      flex: 1 1 auto;
      min-width: 0;
    }
    .composer-input {
      min-height: 44px;
      max-height: 140px;
      resize: vertical;
    }
    .composer-bottom {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    .attachment-chip {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      max-width: 100%;
    }
    .attachment-chip-text {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .attachment-chip-title {
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 180px;
    }
    .attachment-chip-meta {
      font-size: 11px;
      color: var(--builtin-color-muted, #6b7280);
    }
    .info-panel {
      width: min(340px, 30vw);
      flex-shrink: 0;
      border-left: 1px solid var(--builtin-border-soft, #e5e7eb);
      background:
        radial-gradient(circle at top right, rgba(34, 197, 94, 0.12), transparent 34%),
        linear-gradient(180deg, color-mix(in srgb, var(--builtin-header-bg, #f9fafb) 94%, #ffffff), var(--builtin-header-bg, #f9fafb));
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      min-width: 0;
      overflow: hidden;
    }
    .panel-tabs {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }
    .panel-body {
      flex: 1 1 auto;
      overflow-y: auto;
      padding-right: 4px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .panel-section {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .panel-section-head,
    .history-head,
    .member-head,
    .call-head,
    .attachment-preview-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }
    .history-item,
    .member-card,
    .call-card,
    .attachment-preview-card {
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .history-item,
    .member-card {
      text-align: left;
      font: inherit;
      width: 100%;
    }
    .history-item,
    .member-card,
    .call-card {
      cursor: pointer;
      transition: transform .15s ease, border-color .15s ease;
    }
    .history-item:hover,
    .member-card:hover,
    .call-card:hover {
      transform: translateY(-1px);
      border-color: color-mix(in srgb, var(--builtin-primary, #2563eb) 24%, transparent);
    }
    .member-btn,
    .secondary-btn,
    .primary-btn,
    .composer-send,
    .info-action {
      padding: 8px 12px;
    }
    .member-btn.danger {
      color: var(--builtin-color-danger, #b91c1c);
      border-color: color-mix(in srgb, var(--builtin-color-danger, #b91c1c) 28%, transparent);
      background: color-mix(in srgb, var(--builtin-color-danger, #b91c1c) 6%, var(--builtin-surface, #ffffff));
    }
    .empty-panel {
      padding: 18px;
      border: 1px dashed var(--builtin-border-soft, #e5e7eb);
      border-radius: 16px;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
    }
    .modal-grid {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 14px;
    }
    .preview-thumb {
      width: 100%;
      border-radius: 16px;
      background: var(--builtin-header-bg, #f9fafb);
      aspect-ratio: 16 / 10;
      object-fit: cover;
    }
    .preview-stat {
      display: flex;
      justify-content: space-between;
      font-size: 13px;
      color: var(--builtin-color-muted, #6b7280);
      gap: 10px;
    }

    @media (max-width: 720px) {
      :host { flex-direction: column; }
      .sidebar {
        width: 100%;
        border-right: none;
        border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      }
      .back-btn { display: inline-flex; }
      .header-actions { overflow-x: auto; }
      .call-stage,
      .modal-grid,
      .composer-shell { grid-template-columns: 1fr; }
      .messages { padding: 12px; }
      .composer-shell { flex-direction: column; align-items: stretch; }
      .composer-send { width: 100%; }
      .info-panel {
        position: absolute;
        inset: 76px 12px 12px;
        width: auto;
        z-index: 3;
        border: 1px solid var(--builtin-border-soft, #e5e7eb);
        border-radius: 24px;
        box-shadow: 0 20px 40px rgba(15, 23, 42, 0.16);
        display: none;
      }
      .info-panel.mobile-open { display: flex; }
    }
  `;

  constructor() {
    super();
    this.selected = false;
    this.conversations = [];
    this.messages = [];
    this.members = [];
    this.historyGroups = [];
    this.callCards = [];
    this.quickEmojis = ["OK", "DONE", "IDEA", "SHIP"];
    this.draftAttachments = [];
    this.composerValue = "";
    this.inputPlaceholder = "";
    this.searchQuery = "";
    this.historyFilter = "all";
    this.activeConversationId = "";
    this.activeInfoTab = "members";
    this.activeCall = null;
    this.showInfoPanel = true;
    this.allowUploads = true;
    this.attachmentAccept = "image/*,audio/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.zip";
    this._searchOpen = false;
    this._infoOpen = false;
    this._uploadModalOpen = false;
    this._replyMessage = null;
    this._memberDetailOpen = false;
    this._selectedMember = null;
    this._previewAttachment = null;
    this._recording = false;
    this._localDraftAttachments = [];
  }

  disconnectedCallback() {
    this._revokeAttachmentUrls(this._localDraftAttachments);
    super.disconnectedCallback();
  }

  _emit(type, detail = {}) {
    this.dispatchEvent(new CustomEvent(type, {
      detail,
      bubbles: true,
      composed: true,
    }));
  }

  _defaultConversations() {
    return [
      {
        id: "launch-room",
        name: this._l("conversation.launch", "Launch Room"),
        subtitle: this._l("conversation.launchSubtitle", "Release checklist, launch assets, and post-ship triage."),
        preview: this._l("conversation.launchPreview", "Pinned: keep the rollout timeline and FAQ in sync."),
        time: "2m",
        unread: 4,
        tags: [this._l("conversation.tagPinned", "Pinned"), this._l("conversation.tagTeam", "Team")],
      },
      {
        id: "support-hub",
        name: this._l("conversation.support", "Support Hub"),
        subtitle: this._l("conversation.supportSubtitle", "Triage queue, escalations, and saved replies."),
        preview: this._l("conversation.supportPreview", "Search history is enabled for the last 90 days."),
        time: "11m",
        unread: 0,
        tags: [this._l("conversation.tagHistory", "History")],
      },
      {
        id: "design-ops",
        name: this._l("conversation.design", "Design Ops"),
        subtitle: this._l("conversation.designSubtitle", "Assets, approvals, and shared media review."),
        preview: this._l("conversation.designPreview", "Voice room live with 6 attendees."),
        time: "1h",
        unread: 1,
        tags: [this._l("conversation.tagCall", "Call live")],
      },
    ];
  }

  _defaultMessages() {
    return [
      {
        id: "msg-1",
        sender: "Mina",
        senderRole: this._l("member.owner", "Owner"),
        text: this._l("message.sample1", "Kickoff doc is ready. I attached the annotated deck and the voice summary for mobile reviewers."),
        time: "09:12",
        category: this._l("history.today", "Today"),
        reactions: [{ emoji: "OK", count: 5, active: true }],
        attachments: [
          { id: "att-1", type: "file", name: "launch-kickoff-v4.pdf", sizeLabel: "3.1 MB" },
          {
            id: "att-2",
            type: "audio",
            name: this._l("attachment.voiceNote", "Voice summary"),
            sizeLabel: "1m 12s",
            durationLabel: "1m 12s",
            url: "https://interactive-examples.mdn.mozilla.net/media/cc0-audio/t-rex-roar.mp3",
          },
        ],
      },
      {
        id: "msg-2",
        sender: "You",
        text: this._l("message.sample2", "I can take the message history indexing and attachment preview pass today."),
        time: "09:16",
        self: true,
        read: true,
        delivery: this._l("delivery.synced", "Synced across devices"),
        edited: true,
        reactions: [{ emoji: "DONE", count: 2 }],
      },
      {
        id: "msg-3",
        sender: "Ops Bot",
        kind: "event",
        eventText: this._l("message.memberLeft", "Nora left the room. Previous files stay searchable for 30 days."),
        time: "09:20",
        category: this._l("history.today", "Today"),
      },
      {
        id: "msg-4",
        sender: "Jules",
        senderRole: this._l("member.admin", "Admin"),
        text: this._l("message.sample3", "Replying here with the mobile capture. The quoted state should stay visible after editing."),
        replyTo: this._l("message.replySeed", "I can take the message history indexing and attachment preview pass today."),
        time: "09:21",
        badge: this._l("message.badgeFollowup", "Follow-up"),
        attachments: [
          {
            id: "att-3",
            type: "image",
            name: "mobile-chat-board.png",
            sizeLabel: "960 KB",
            thumbnail: "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=900&q=80",
          },
        ],
        reactions: [{ emoji: "IDEA", count: 3 }, { emoji: "OK", count: 4 }],
      },
      {
        id: "msg-5",
        sender: "You",
        text: this._l("message.sample4", "Great. I also need the group voice and group video entry states wired in."),
        time: "09:23",
        self: true,
        read: false,
        recallable: true,
        editable: true,
      },
    ];
  }

  _defaultMembers() {
    return [
      {
        id: "mina",
        name: "Mina",
        role: this._l("member.owner", "Owner"),
        status: this._l("member.online", "Online"),
        bio: this._l("member.ownerBio", "Owns launch readiness, moderation, and room permissions."),
        tags: [this._l("member.tagCanKick", "Can kick"), this._l("member.tagCanPin", "Can pin")],
      },
      {
        id: "jules",
        name: "Jules",
        role: this._l("member.admin", "Admin"),
        status: this._l("member.inCall", "In voice call"),
        bio: this._l("member.adminBio", "Keeps docs and mobile QA aligned."),
        tags: [this._l("member.tagReview", "Review lead")],
      },
      {
        id: "nora",
        name: "Nora",
        role: this._l("member.guest", "Guest"),
        status: this._l("member.left", "Left 3m ago"),
        bio: this._l("member.leftBio", "Recently left. History remains accessible for audit."),
        tags: [this._l("member.tagFormer", "Former member")],
      },
    ];
  }

  _defaultHistoryGroups() {
    return [
      {
        id: "all",
        label: this._l("history.all", "All history"),
        count: 1240,
        items: [
          {
            id: "history-1",
            title: this._l("history.item1", "Launch checklist updates"),
            meta: this._l("history.item1Meta", "24 results · attachments · this week"),
            excerpt: this._l("history.item1Excerpt", "Spec, rollout notes, and attachment previews were discussed here."),
          },
          {
            id: "history-2",
            title: this._l("history.item2", "Call summaries"),
            meta: this._l("history.item2Meta", "9 sessions · voice + video"),
            excerpt: this._l("history.item2Excerpt", "All scheduled calls, recordings, and attendee changes."),
          },
        ],
      },
      {
        id: "attachments",
        label: this._l("history.attachments", "Attachments"),
        count: 86,
        items: [
          {
            id: "history-3",
            title: this._l("history.item3", "Design review media"),
            meta: this._l("history.item3Meta", "41 images · 6 voice notes"),
            excerpt: this._l("history.item3Excerpt", "Shared image boards, PDFs, and call snippets."),
          },
        ],
      },
      {
        id: "people",
        label: this._l("history.people", "Member events"),
        count: 17,
        items: [
          {
            id: "history-4",
            title: this._l("history.item4", "Roster changes"),
            meta: this._l("history.item4Meta", "Joins, leaves, kicks, promotions"),
            excerpt: this._l("history.item4Excerpt", "Admin actions and member transitions stay searchable."),
          },
        ],
      },
    ];
  }

  _defaultCallCards() {
    return [
      {
        id: "call-1",
        mode: "voice",
        title: this._l("call.voiceRoom", "Daily voice room"),
        meta: this._l("call.voiceMeta", "6 attendees · open now"),
        tags: [this._l("call.voice", "Voice"), this._l("call.recorded", "Recorded")],
      },
      {
        id: "call-2",
        mode: "video",
        title: this._l("call.videoRoom", "Launch war room"),
        meta: this._l("call.videoMeta", "Starts in 12 min · agenda attached"),
        tags: [this._l("call.video", "Video"), this._l("call.scheduled", "Scheduled")],
      },
    ];
  }

  _conversationList() {
    return Array.isArray(this.conversations) && this.conversations.length
      ? this.conversations
      : this._defaultConversations();
  }

  _currentConversation() {
    const conversations = this._conversationList();
    if (!conversations.length) return null;
    const activeId = this.activeConversationId || conversations[0]?.id;
    return conversations.find((item) => String(item.id) === String(activeId)) || conversations[0];
  }

  _messageList() {
    const conversation = this._currentConversation();
    if (Array.isArray(conversation?.messages) && conversation.messages.length) {
      return conversation.messages;
    }
    return Array.isArray(this.messages) && this.messages.length ? this.messages : this._defaultMessages();
  }

  _memberList() {
    const conversation = this._currentConversation();
    if (Array.isArray(conversation?.members) && conversation.members.length) {
      return conversation.members;
    }
    return Array.isArray(this.members) && this.members.length ? this.members : this._defaultMembers();
  }

  _historyList() {
    const conversation = this._currentConversation();
    if (Array.isArray(conversation?.historyGroups) && conversation.historyGroups.length) {
      return conversation.historyGroups;
    }
    return Array.isArray(this.historyGroups) && this.historyGroups.length ? this.historyGroups : this._defaultHistoryGroups();
  }

  _callList() {
    const conversation = this._currentConversation();
    if (Array.isArray(conversation?.callCards) && conversation.callCards.length) {
      return conversation.callCards;
    }
    return Array.isArray(this.callCards) && this.callCards.length ? this.callCards : this._defaultCallCards();
  }

  _activeCallCard() {
    return this.activeCall || this._callList()[0] || null;
  }

  _allDraftAttachments() {
    const external = Array.isArray(this.draftAttachments) ? this.draftAttachments : [];
    return [...this._localDraftAttachments, ...external];
  }

  _toggleSearch() {
    this._searchOpen = !this._searchOpen;
  }

  _deselectChat() {
    this.selected = false;
  }

  _setInfoTab(tab) {
    this.activeInfoTab = tab;
    if (this._ptMobile) {
      this._infoOpen = true;
    }
    this._emit("builtin-info-tab-change", { tab, conversation: this._currentConversation() });
  }

  _selectConversation(conversation) {
    this.activeConversationId = conversation?.id ? String(conversation.id) : "";
    this.selected = true;
    this._replyMessage = null;
    this._emit("builtin-conversation-select", { conversation });
  }

  _openMember(member) {
    this._selectedMember = member;
    this._memberDetailOpen = true;
  }

  _closeMemberDetail() {
    this._memberDetailOpen = false;
    this._selectedMember = null;
  }

  _openAttachmentPreview(attachment) {
    this._previewAttachment = attachment;
  }

  _closeAttachmentPreview() {
    this._previewAttachment = null;
  }

  _resolveMemberFromEvent(detail) {
    const members = this._memberList();
    const targetId = String(detail?.id || detail?.message?.senderId || detail?.message?.sender || detail?.sender || "");
    const senderName = String(detail?.sender || detail?.message?.sender || "");
    const match = members.find((member) => {
      const memberIds = [member?.id, member?.user_id, member?.name, member?.nickname]
        .filter(Boolean)
        .map((value) => String(value));
      return memberIds.includes(targetId) || (senderName && memberIds.includes(senderName));
    });
    if (match) {
      return match;
    }
    const message = detail?.message || {};
    return {
      id: targetId || senderName,
      name: senderName || this._l("member.unknown", "Unknown"),
      role: detail?.senderRole || message?.senderRole || "",
      status: detail?.status || message?.senderStatus || this._l("member.online", "Online"),
      bio: message?.text || message?.eventText || this._l("member.detailsCopy", "Use this modal for profile details, moderation actions, and direct-call shortcuts."),
      tags: [],
    };
  }

  _onSearchInput(event) {
    this.searchQuery = event.currentTarget.value;
    this._emit("builtin-search-change", {
      query: this.searchQuery,
      conversation: this._currentConversation(),
    });
  }

  _onComposerInput(event) {
    this.composerValue = event.currentTarget.value;
    this._emit("builtin-draft-change", {
      value: this.composerValue,
      conversation: this._currentConversation(),
    });
  }

  _onHistoryFilter(id) {
    this.historyFilter = id;
    this._emit("builtin-history-filter", {
      id,
      conversation: this._currentConversation(),
    });
  }

  _toggleRecording() {
    this._recording = !this._recording;
    this._emit("builtin-record-toggle", {
      recording: this._recording,
      conversation: this._currentConversation(),
    });
  }

  _onEmoji(emoji) {
    this._emit("builtin-emoji-pick", {
      emoji,
      conversation: this._currentConversation(),
    });
  }

  _onCall(mode, source = "header") {
    this._emit(mode === "video" ? "builtin-video-call" : "builtin-voice-call", {
      mode,
      source,
      conversation: this._currentConversation(),
    });
  }

  _openUploadModal() {
    if (this.allowUploads === false) return;
    this._uploadModalOpen = true;
  }

  _closeUploadModal() {
    this._uploadModalOpen = false;
  }

  _formatFileSize(size) {
    const value = Number(size || 0);
    if (!value) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let amount = value;
    let index = 0;
    while (amount >= 1024 && index < units.length - 1) {
      amount /= 1024;
      index += 1;
    }
    return `${amount.toFixed(amount >= 100 || index === 0 ? 0 : 1)} ${units[index]}`;
  }

  _attachmentType(file) {
    const type = String(file?.type || file?.kind || "").toLowerCase();
    if (type.startsWith("image/")) return "image";
    if (type.startsWith("audio/")) return "audio";
    if (type.startsWith("video/")) return "video";
    return "file";
  }

  _revokeAttachmentUrls(attachments) {
    for (const attachment of attachments || []) {
      if (attachment?._temporaryUrl) {
        URL.revokeObjectURL(attachment._temporaryUrl);
      }
    }
  }

  _mapUploadFile(file) {
    const type = this._attachmentType(file);
    const objectUrl = URL.createObjectURL(file);
    return {
      id: `draft-${Math.random().toString(36).slice(2)}`,
      name: file.name,
      type,
      sizeLabel: this._formatFileSize(file.size),
      url: type === "audio" || type === "video" ? objectUrl : undefined,
      thumbnail: type === "image" ? objectUrl : undefined,
      _temporaryUrl: objectUrl,
      file,
    };
  }

  _onUploadSelected(event) {
    const files = Array.from(event.detail?.files || []);
    this._emit("builtin-attachment-queue", {
      files,
      conversation: this._currentConversation(),
    });
  }

  _onUploadConfirm(event) {
    const files = Array.from(event.detail?.files || []);
    const nextAttachments = files.map((file) => this._mapUploadFile(file));
    this._localDraftAttachments = [...this._localDraftAttachments, ...nextAttachments];
    this._uploadModalOpen = false;
    this._emit("builtin-attachment-upload", {
      files,
      attachments: nextAttachments,
      conversation: this._currentConversation(),
    });
  }

  _removeDraftAttachment(attachment) {
    if (attachment?._temporaryUrl) {
      URL.revokeObjectURL(attachment._temporaryUrl);
    }
    this._localDraftAttachments = this._localDraftAttachments.filter((item) => item !== attachment);
    this._emit("builtin-attachment-remove", {
      attachment,
      conversation: this._currentConversation(),
    });
  }

  _clearReply() {
    this._replyMessage = null;
  }

  _onThreadReply(event) {
    this._replyMessage = event.detail?.message || null;
  }

  _onThreadMemberOpen(event) {
    const member = this._resolveMemberFromEvent(event.detail || {});
    if (member) {
      this._openMember(member);
    }
  }

  _onThreadAttachmentOpen(event) {
    const attachment = event.detail?.attachment || null;
    if (attachment) {
      this._openAttachmentPreview(attachment);
    }
  }

  _sendMessage() {
    this._emit("builtin-send", {
      text: this.composerValue,
      attachments: this._allDraftAttachments(),
      replyTo: this._replyMessage,
      conversation: this._currentConversation(),
    });
  }

  _promoteMember(member) {
    this._emit("builtin-member-promote", {
      member,
      conversation: this._currentConversation(),
    });
  }

  _kickMember(member) {
    this._emit("builtin-member-kick", {
      member,
      conversation: this._currentConversation(),
    });
  }

  _filteredHistoryItems() {
    const groups = this._historyList();
    const filter = this.historyFilter || groups[0]?.id || "all";
    const activeGroup = groups.find((item) => String(item.id) === String(filter)) || groups[0];
    const needle = String(this.searchQuery || "").trim().toLowerCase();
    const items = Array.isArray(activeGroup?.items) ? activeGroup.items : [];
    if (!needle) return items;
    return items.filter((item) => `${item.title || ""} ${item.meta || ""} ${item.excerpt || ""}`.toLowerCase().includes(needle));
  }

  _renderSidebarConversation(conversation) {
    const active = String(this._currentConversation()?.id || "") === String(conversation?.id || "");
    return html`
      <button class="conv-item ${classMap({ active })}" @click=${() => this._selectConversation(conversation)}>
        <builtin-avatar size="44" name="${conversation?.name || "?"}"></builtin-avatar>
        <div class="conv-meta">
          <div class="conv-head">
            <div class="conv-name">${conversation?.name || this._l("conversation.untitled", "Untitled")}</div>
            <div class="conv-time">${conversation?.time || ""}</div>
          </div>
          <div class="conv-msg">${conversation?.preview || conversation?.subtitle || ""}</div>
          ${Array.isArray(conversation?.tags) && conversation.tags.length
            ? html`<div class="conversation-tags">${conversation.tags.map((tag) => html`<span class="conversation-tag">${tag}</span>`)}</div>`
            : ""}
        </div>
        <div class="conv-tail">
          ${conversation?.subtitle ? html`<div class="conv-time">${conversation.subtitle}</div>` : ""}
          ${conversation?.unread ? html`<div class="conv-unread">${conversation.unread}</div>` : ""}
        </div>
      </button>
    `;
  }

  _renderHistoryPanel() {
    const groups = this._historyList();
    const activeId = this.historyFilter || groups[0]?.id || "all";
    const items = this._filteredHistoryItems();
    return html`
      <div class="panel-section">
        <div class="panel-section-head">
          <div>
            <h3>${this._l("history.title", "Search history")}</h3>
            <p>${this._l("history.subtitle", "Messages, files, calls, and member events stay categorized.")}</p>
          </div>
        </div>
        <div class="search-card">
          <builtin-icon name="search" size="16" variant="outlined"></builtin-icon>
          <input type="search" .value=${this.searchQuery || ""} placeholder="${this._l("history.placeholder", "Search messages, attachments, or people")}" @input=${this._onSearchInput}>
        </div>
        <div class="history-filters">
          ${groups.map((group) => html`
            <button class="filter-chip ${classMap({ active: String(group.id) === String(activeId) })}" @click=${() => this._onHistoryFilter(group.id)}>
              ${group.label} ${typeof group.count === "number" ? html`<span>(${group.count})</span>` : ""}
            </button>
          `)}
        </div>
      </div>
      <div class="panel-section">
        ${items.length
          ? items.map((item) => html`
              <button class="history-item" @click=${() => this._emit("builtin-history-open", { item, filter: activeId, conversation: this._currentConversation() })}>
                <div class="history-head">
                  <strong class="history-title">${item.title || this._l("history.result", "History result")}</strong>
                  <span class="history-meta">${item.meta || ""}</span>
                </div>
                <div class="history-meta">${item.excerpt || ""}</div>
              </button>
            `)
          : html`<div class="empty-panel">${this._l("history.empty", "No history items match the current search.")}</div>`}
      </div>
    `;
  }

  _renderMembersPanel() {
    const members = this._memberList();
    return html`
      <div class="panel-section">
        <div class="panel-section-head">
          <div>
            <h3>${this._l("members.title", "Members")}</h3>
            <p>${this._l("members.subtitle", "Admins, permissions, and leave events live here.")}</p>
          </div>
          <button class="info-action" @click=${() => this._emit("builtin-member-invite", { conversation: this._currentConversation() })}>
            <builtin-icon name="paper-clip" size="16" variant="outlined"></builtin-icon>
            ${this._l("members.invite", "Invite")}
          </button>
        </div>
      </div>
      <div class="panel-section">
        ${members.length
          ? members.map((member) => html`
              <button class="member-card" @click=${() => this._openMember(member)}>
                <div class="member-head">
                  <div style="display:flex;gap:12px;align-items:center;min-width:0;">
                    <builtin-avatar size="42" name="${member.name || member.nickname || member.id || "?"}"></builtin-avatar>
                    <div>
                      <div class="member-name">${member.name || member.nickname || member.id || this._l("member.unknown", "Unknown")}</div>
                      <div class="member-meta">${member.role || ""} · ${member.status || ""}</div>
                    </div>
                  </div>
                  <builtin-icon name="right" size="16" variant="outlined"></builtin-icon>
                </div>
                ${Array.isArray(member.tags) && member.tags.length ? html`<div class="member-tags">${member.tags.map((tag) => html`<span class="member-tag">${tag}</span>`)}</div>` : ""}
                <div class="member-meta">${member.bio || ""}</div>
                <div class="member-actions" @click=${(event) => event.stopPropagation()}>
                  <button class="member-btn" @click=${() => this._promoteMember(member)}>${this._l("members.promote", "Promote")}</button>
                  <button class="member-btn danger" @click=${() => this._kickMember(member)}>${this._l("members.kick", "Kick")}</button>
                </div>
              </button>
            `)
          : html`<div class="empty-panel">${this._l("members.empty", "No members yet.")}</div>`}
      </div>
    `;
  }

  _renderCallsPanel() {
    const calls = this._callList();
    return html`
      <div class="panel-section">
        <div class="panel-section-head">
          <div>
            <h3>${this._l("call.title", "Voice and video rooms")}</h3>
            <p>${this._l("call.subtitle", "Launch group phone and video sessions without leaving the chat shell.")}</p>
          </div>
          <div class="call-actions">
            <button class="info-action" @click=${() => this._onCall("voice", "panel")}>${this._l("call.voice", "Voice")}</button>
            <button class="info-action" @click=${() => this._onCall("video", "panel")}>${this._l("call.video", "Video")}</button>
          </div>
        </div>
      </div>
      <div class="panel-section">
        ${calls.length
          ? calls.map((call) => html`
              <div class="call-card">
                <div class="call-head">
                  <div>
                    <div class="call-title">${call.title || this._l("call.room", "Call room")}</div>
                    <div class="call-meta">${call.meta || ""}</div>
                  </div>
                  <builtin-icon name="${call.mode === "video" ? "video-camera" : "phone"}" size="18" variant="outlined"></builtin-icon>
                </div>
                ${Array.isArray(call.tags) && call.tags.length ? html`<div class="call-tags">${call.tags.map((tag) => html`<span class="call-tag">${tag}</span>`)}</div>` : ""}
                <div class="call-actions">
                  <button class="member-btn" @click=${() => this._emit("builtin-call-open", { call, conversation: this._currentConversation() })}>${this._l("call.open", "Open")}</button>
                  <button class="primary-btn" @click=${() => this._emit("builtin-call-join", { call, conversation: this._currentConversation() })}>${this._l("call.join", "Join")}</button>
                </div>
              </div>
            `)
          : html`<div class="empty-panel">${this._l("call.empty", "No upcoming calls.")}</div>`}
      </div>
    `;
  }

  _renderInfoPanel() {
    const panelClass = classMap({ "info-panel": true, "mobile-open": this._infoOpen });
    return html`
      <aside class="${panelClass}" style=${styleMap({ display: this.showInfoPanel === false && !this._ptMobile ? "none" : undefined })}>
        <slot name="info">
          <div class="panel-tabs">
            <button class="tab-btn ${classMap({ active: this.activeInfoTab === "members" })}" @click=${() => this._setInfoTab("members")}>${this._l("tab.members", "Members")}</button>
            <button class="tab-btn ${classMap({ active: this.activeInfoTab === "history" })}" @click=${() => this._setInfoTab("history")}>${this._l("tab.history", "History")}</button>
            <button class="tab-btn ${classMap({ active: this.activeInfoTab === "calls" })}" @click=${() => this._setInfoTab("calls")}>${this._l("tab.calls", "Calls")}</button>
          </div>
          <div class="panel-body">
            ${this.activeInfoTab === "history" ? this._renderHistoryPanel() : ""}
            ${this.activeInfoTab === "members" ? this._renderMembersPanel() : ""}
            ${this.activeInfoTab === "calls" ? this._renderCallsPanel() : ""}
          </div>
        </slot>
      </aside>
    `;
  }

  render() {
    const currentConversation = this._currentConversation();
    const chatName = this.chatName || currentConversation?.name || this._l("chat.name", "General");
    const status = this.status || currentConversation?.subtitle || this._l("chat.status", "Online");
    const conversations = this._conversationList();
    const messageList = this._messageList();
    const activeCall = this._activeCallCard();
    const draftAttachments = this._allDraftAttachments();

    const sidebarStyles = this._ptMobile ? { display: this.selected ? "none" : "flex" } : {};
    const mainStyles = this._ptMobile ? { display: this.selected ? "flex" : "none" } : {};

    return html`
      <aside class="sidebar" style=${styleMap(sidebarStyles)}>
        <slot name="sidebar">
          <div class="sidebar-header">
            <div class="sidebar-brand">
              <div class="sidebar-brand-main">
                <builtin-avatar size="44" name="${chatName}"></builtin-avatar>
                <div class="sidebar-brand-copy">
                  <div class="sidebar-eyebrow">${this._l("sidebar.eyebrow", "Shared chat template")}</div>
                  <div class="sidebar-title">${this._l("sidebar.title", "Messages")}</div>
                </div>
              </div>
              <div class="sidebar-actions">
                <button class="ghost-icon-btn" title="${this._l("chat.search", "Search")}" @click=${this._toggleSearch}>
                  <builtin-icon name="search" size="16" variant="outlined"></builtin-icon>
                </button>
                <button class="ghost-icon-btn" title="${this._l("members.title", "Members")}" @click=${() => this._setInfoTab("members")}>
                  <builtin-icon name="menu" size="16" variant="outlined"></builtin-icon>
                </button>
              </div>
            </div>
            <div class="search-card">
              <builtin-icon name="search" size="16" variant="outlined"></builtin-icon>
              <input type="search" .value=${this.searchQuery || ""} placeholder="${this._l("sidebar.search", "Search rooms or people")}" @input=${this._onSearchInput}>
            </div>
            <div class="sidebar-filters">
              <button class="filter-chip active">${this._l("sidebar.filterAll", "All")}</button>
              <button class="filter-chip">${this._l("sidebar.filterUnread", "Unread")}</button>
              <button class="filter-chip">${this._l("sidebar.filterTeams", "Groups")}</button>
            </div>
          </div>
          <div class="conv-list">
            ${conversations.map((conversation) => this._renderSidebarConversation(conversation))}
          </div>
        </slot>
      </aside>

      <section class="main" style=${styleMap(mainStyles)}>
        <div class="main-header">
          <slot name="header">
            <div class="header-shell">
              <button class="back-btn" aria-label="${this._l("chat.back", "Back to conversations")}" @click=${this._deselectChat}>
                <builtin-icon name="left" size="16" variant="outlined"></builtin-icon>
                ${this._l("chat.back", "Back")}
              </button>
              <builtin-avatar size="40" name="${chatName}"></builtin-avatar>
              <div class="header-info">
                <h2>${chatName}</h2>
                <div class="header-presence">
                  <span class="presence-dot"></span>
                  <span>${status}</span>
                  <span>·</span>
                  <span>${this._memberList().length} ${this._l("chat.membersOnline", "members visible")}</span>
                </div>
              </div>
            </div>
            <div class="header-actions">
              <button class="ghost-icon-btn" title="${this._l("chat.search", "Search")}" @click=${this._toggleSearch}>
                <builtin-icon name="search" size="16" variant="outlined"></builtin-icon>
              </button>
              <button class="ghost-icon-btn" title="${this._l("tab.history", "History")}" @click=${() => this._setInfoTab("history")}>
                <builtin-icon name="menu" size="16" variant="outlined"></builtin-icon>
              </button>
              <button class="ghost-icon-btn" title="${this._l("call.voice", "Voice")}" @click=${() => this._onCall("voice", "header")}>
                <builtin-icon name="phone" size="16" variant="outlined"></builtin-icon>
              </button>
              <button class="ghost-icon-btn" title="${this._l("call.video", "Video")}" @click=${() => this._onCall("video", "header")}>
                <builtin-icon name="video-camera" size="16" variant="outlined"></builtin-icon>
              </button>
              <button class="ghost-icon-btn" title="${this._l("members.title", "Members")}" @click=${() => this._setInfoTab("members")}>
                <builtin-icon name="menu" size="16" variant="outlined"></builtin-icon>
              </button>
            </div>
          </slot>
        </div>

        ${this._searchOpen || this.searchQuery
          ? html`
              <div class="search-strip">
                <builtin-icon name="search" size="16" variant="outlined"></builtin-icon>
                <input type="search" .value=${this.searchQuery || ""} placeholder="${this._l("chat.searchPlaceholder", "Search this room")}" @input=${this._onSearchInput}>
                <button class="dismiss-btn" @click=${() => { this.searchQuery = ""; this._searchOpen = false; }}>
                  <builtin-icon name="close" size="16" variant="outlined"></builtin-icon>
                </button>
              </div>
            `
          : ""}

        ${activeCall
          ? html`
              <div class="call-stage">
                <div>
                  <h3>${activeCall.title || this._l("call.stageTitle", "Active room")}</h3>
                  <p>${activeCall.meta || this._l("call.stageMeta", "Voice or video session anchored to this conversation.")}</p>
                  ${Array.isArray(activeCall.tags) && activeCall.tags.length ? html`<div class="call-tags">${activeCall.tags.map((tag) => html`<span class="call-tag">${tag}</span>`)}</div>` : ""}
                </div>
                <div class="call-stage-actions">
                  <button class="secondary-btn" @click=${() => this._emit("builtin-call-open", { call: activeCall, conversation: currentConversation })}>${this._l("call.details", "Details")}</button>
                  <button class="primary-btn" @click=${() => this._emit("builtin-call-join", { call: activeCall, conversation: currentConversation })}>${this._l("call.join", "Join call")}</button>
                </div>
              </div>
            `
          : ""}

        <div class="messages">
          <slot name="messages">
            <builtin-tpl-chat-message-thread
              .messages=${messageList}
              .labels=${this.labels}
              .searchQuery=${this.searchQuery}
              history-mode="thread"
              @builtin-reply=${this._onThreadReply}
              @builtin-quote=${this._onThreadReply}
              @builtin-member-open=${this._onThreadMemberOpen}
              @builtin-attachment-open=${this._onThreadAttachmentOpen}
            ></builtin-tpl-chat-message-thread>
          </slot>
        </div>

        <slot name="footer">
          <div class="input-area">
            ${this._replyMessage
              ? html`
                  <div class="reply-banner">
                    <div class="reply-pill">
                      <div>
                        <strong>${this._l("composer.replying", "Replying to")} ${this._replyMessage.sender || this._l("member.unknown", "Unknown")}</strong>
                        <p>${this._replyMessage.text || this._replyMessage.eventText || ""}</p>
                      </div>
                      <button class="dismiss-btn" @click=${this._clearReply}>
                        <builtin-icon name="close" size="16" variant="outlined"></builtin-icon>
                      </button>
                    </div>
                  </div>
                `
              : ""}
            ${draftAttachments.length
              ? html`
                  <div class="draft-attachments">
                    ${draftAttachments.map((attachment) => html`
                      <div class="attachment-chip">
                        <builtin-icon name="paper-clip" size="16" variant="outlined"></builtin-icon>
                        <div class="attachment-chip-text">
                          <div class="attachment-chip-title">${attachment.name || this._l("attachment.untitled", "Untitled attachment")}</div>
                          <div class="attachment-chip-meta">${attachment.sizeLabel || attachment.durationLabel || attachment.type || this._l("attachment.file", "File")}</div>
                        </div>
                        <button class="dismiss-btn" @click=${() => this._removeDraftAttachment(attachment)}>
                          <builtin-icon name="close" size="14" variant="outlined"></builtin-icon>
                        </button>
                      </div>
                    `)}
                  </div>
                `
              : ""}
            <div class="composer-shell">
              <div class="composer-main">
                <textarea class="composer-input" .value=${this.composerValue || ""} placeholder="${this.inputPlaceholder || this._l("chat.placeholder", "Type a message")}" @input=${this._onComposerInput}></textarea>
                <div class="composer-bottom">
                  <div class="composer-left">
                    <button class="ghost-icon-btn" type="button" title="${this._l("chat.attach", "Attach")}" @click=${this._openUploadModal}>
                      <builtin-icon name="paper-clip" size="16" variant="outlined"></builtin-icon>
                    </button>
                    <button class="ghost-icon-btn" type="button" title="${this._l("chat.emoji", "Emoji")}" @click=${() => this._emit("builtin-emoji-open", { conversation: currentConversation })}>
                      <span>:-)</span>
                    </button>
                    <button class="ghost-icon-btn" type="button" title="${this._l("chat.record", "Record")}" @click=${this._toggleRecording}>
                      <span>${this._recording ? "REC" : "MIC"}</span>
                    </button>
                    <button class="ghost-icon-btn" type="button" title="${this._l("call.voice", "Voice")}" @click=${() => this._onCall("voice", "composer")}>
                      <builtin-icon name="phone" size="16" variant="outlined"></builtin-icon>
                    </button>
                    <button class="ghost-icon-btn" type="button" title="${this._l("call.video", "Video")}" @click=${() => this._onCall("video", "composer")}>
                      <builtin-icon name="video-camera" size="16" variant="outlined"></builtin-icon>
                    </button>
                  </div>
                  <div class="composer-right">
                    ${Array.isArray(this.quickEmojis) && this.quickEmojis.length
                      ? html`<div class="quick-emoji-list">${this.quickEmojis.map((emoji) => html`<button class="quick-emoji" @click=${() => this._onEmoji(emoji)}>${emoji}</button>`)}</div>`
                      : ""}
                  </div>
                </div>
              </div>
              <button class="composer-send" type="button" title="${this._l("chat.send", "Send")}" @click=${this._sendMessage}>
                <builtin-icon name="send" size="16" variant="outlined"></builtin-icon>
                ${this._l("chat.send", "Send")}
              </button>
            </div>
          </div>
        </slot>
      </section>

      ${this._renderInfoPanel()}

      <builtin-modal .open=${this._uploadModalOpen} title="${this._l("upload.modalTitle", "Attach files")}" size="large" @builtin-close=${this._closeUploadModal}>
        <div class="modal-grid">
          <builtin-drag-upload-zone
            accept="${this.attachmentAccept || ""}"
            multiple
            @builtin-files-selected=${this._onUploadSelected}
            @builtin-upload=${this._onUploadConfirm}
          ></builtin-drag-upload-zone>
          <div class="attachment-preview-card">
            <div class="attachment-preview-head">
              <strong>${this._l("upload.previewTitle", "Attachment capabilities")}</strong>
              <builtin-icon name="paper-clip" size="16" variant="outlined"></builtin-icon>
            </div>
            <p>${this._l("upload.previewCopy", "Preview files before sending, drag into the room, and keep the resulting bubbles searchable.")}</p>
            <div class="preview-stat"><span>${this._l("upload.previewStat1", "Supports")}</span><span>${this._l("upload.previewStat1Value", "Images, voice, docs, video")}</span></div>
            <div class="preview-stat"><span>${this._l("upload.previewStat2", "Callbacks")}</span><span>${this._l("upload.previewStat2Value", "queue, remove, upload, open")}</span></div>
            <div class="preview-stat"><span>${this._l("upload.previewStat3", "Modes")}</span><span>${this._l("upload.previewStat3Value", "mobile, dark, multilingual")}</span></div>
          </div>
        </div>
        <div slot="footer">
          <button class="secondary-btn" @click=${this._closeUploadModal}>${this._l("close", "Close")}</button>
        </div>
      </builtin-modal>

      <builtin-modal .open=${this._memberDetailOpen} title="${this._selectedMember?.name || this._selectedMember?.sender || this._l("member.details", "Member details")}" size="medium" @builtin-close=${this._closeMemberDetail}>
        <div class="attachment-preview-card">
          <div class="member-head">
            <div style="display:flex;gap:12px;align-items:center;">
              <builtin-avatar size="52" name="${this._selectedMember?.name || this._selectedMember?.sender || "?"}"></builtin-avatar>
              <div>
                <div class="member-name">${this._selectedMember?.name || this._selectedMember?.sender || this._l("member.unknown", "Unknown")}</div>
                <div class="member-meta">${this._selectedMember?.role || this._selectedMember?.senderRole || ""} · ${this._selectedMember?.status || this._l("member.online", "Online")}</div>
              </div>
            </div>
          </div>
          <p>${this._selectedMember?.bio || this._l("member.detailsCopy", "Use this modal for profile details, moderation actions, and direct-call shortcuts.")}</p>
          ${Array.isArray(this._selectedMember?.tags) && this._selectedMember.tags.length ? html`<div class="member-tags">${this._selectedMember.tags.map((tag) => html`<span class="member-tag">${tag}</span>`)}</div>` : ""}
          <div class="member-actions">
            <button class="member-btn" @click=${() => this._emit("builtin-direct-message", { member: this._selectedMember, conversation: currentConversation })}>${this._l("member.message", "Message")}</button>
            <button class="member-btn" @click=${() => this._onCall("voice", "member-modal")}>${this._l("call.voice", "Voice")}</button>
            <button class="member-btn" @click=${() => this._onCall("video", "member-modal")}>${this._l("call.video", "Video")}</button>
            <button class="member-btn danger" @click=${() => this._kickMember(this._selectedMember)}>${this._l("members.kick", "Kick")}</button>
          </div>
        </div>
        <div slot="footer">
          <button class="secondary-btn" @click=${this._closeMemberDetail}>${this._l("close", "Close")}</button>
        </div>
      </builtin-modal>

      <builtin-modal .open=${!!this._previewAttachment} title="${this._previewAttachment?.name || this._l("attachment.preview", "Attachment preview")}" size="large" @builtin-close=${this._closeAttachmentPreview}>
        <div class="modal-grid">
          <div class="attachment-preview-card">
            ${this._previewAttachment?.thumbnail
              ? html`<img class="preview-thumb" src="${this._previewAttachment.thumbnail}" alt="${this._previewAttachment.name || "preview"}">`
              : html`<div class="preview-thumb" style="display:flex;align-items:center;justify-content:center;"><builtin-icon name="paper-clip" size="36" variant="outlined"></builtin-icon></div>`}
            <div class="preview-stat"><span>${this._l("attachment.type", "Type")}</span><span>${this._previewAttachment?.type || this._l("attachment.file", "File")}</span></div>
            <div class="preview-stat"><span>${this._l("attachment.size", "Size")}</span><span>${this._previewAttachment?.sizeLabel || this._previewAttachment?.durationLabel || "-"}</span></div>
          </div>
          <div class="attachment-preview-card">
            <div class="attachment-preview-head">
              <strong>${this._l("attachment.preview", "Attachment preview")}</strong>
              <builtin-icon name="search" size="16" variant="outlined"></builtin-icon>
            </div>
            <p>${this._l("attachment.previewCopy", "Attachment bubbles should expose enough metadata to support click-through preview, history search, and moderation workflows.")}</p>
            ${this._previewAttachment?.url && this._previewAttachment?.type === "audio"
              ? html`<builtin-audio-player mode="compact" src="${this._previewAttachment.url}" title="${this._previewAttachment.name || this._l("attachment.voiceNote", "Voice note")}"></builtin-audio-player>`
              : ""}
          </div>
        </div>
        <div slot="footer">
          <button class="secondary-btn" @click=${this._closeAttachmentPreview}>${this._l("close", "Close")}</button>
        </div>
      </builtin-modal>
    `;
  }
}