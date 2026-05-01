/**
 * @fileoverview BuiltinCommentSection — Full comment thread with replies, likes, timestamps.
 *
 * @attr {string} comments — JSON array of {id, author, avatar, content, time, likes, replies:[...], liked}.
 * @attr {string} sortBy — 'newest' | 'top' | 'oldest'.
 * @attr {string} currentUser — JSON {name, avatar}.
 * @attr {string} labels — JSON i18n overrides.
 *
 * @event builtin-comment — Detail: { text, parentId }.
 * @event builtin-like — Detail: { id, liked }.
 * @event builtin-sort — Detail: { sortBy }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

export class BuiltinCommentSection extends BuiltinBaseElement {
  static properties = {
    comments: { type: Array },
    sortBy: { type: String, attribute: "sort-by" },
    currentUser: { type: Object, attribute: "current-user" },
    maxDepth: { type: Number, attribute: "max-depth" },
    allowDelete: { type: Boolean, attribute: "allow-delete" },
    labels: { type: Object },
    _replyTo: { type: String, state: true },
    _input: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .count { font-size: 14px; font-weight: 650; color: var(--builtin-color-text, #111827); }
    .sort { font-size: 13px; color: var(--builtin-color-muted, #6b7280); background: transparent; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); padding: 4px 8px; cursor: pointer; }
    .comment { display: flex; gap: 10px; margin-bottom: 14px; }
    .avatar { width: 36px; height: 36px; border-radius: 50%; object-fit: cover; flex-shrink: 0; background: var(--builtin-header-bg, #f9fafb); }
    .body { flex: 1; min-width: 0; }
    .author-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .author { font-weight: 650; font-size: 13px; color: var(--builtin-color-text, #111827); }
    .time { font-size: 12px; color: var(--builtin-color-muted, #9ca3af); }
    .text { font-size: 14px; color: var(--builtin-color-text, #111827); line-height: 1.5; word-break: break-word; }
    .actions { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
    .action { font-size: 12px; color: var(--builtin-color-muted, #6b7280); cursor: pointer; background: transparent; border: none; padding: 0; display: inline-flex; align-items: center; gap: 4px; }
    .action:hover { color: var(--builtin-primary, #2563eb); }
    .action.liked { color: var(--builtin-color-danger, #ef4444); }
    .replies { margin-top: 10px; padding-left: 16px; border-left: 2px solid var(--builtin-border-soft, #e5e7eb); animation: builtin-comment-fade 0.2s ease; }
    @keyframes builtin-comment-fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
    .like-anim { animation: builtin-like-bounce 0.3s ease; }
    @keyframes builtin-like-bounce { 0% { transform: scale(1); } 50% { transform: scale(1.3); } 100% { transform: scale(1); } }
    .input-box { display: flex; gap: 10px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .input-box textarea { flex: 1; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); padding: 8px; font: inherit; resize: vertical; min-height: 60px; background: var(--builtin-input-bg, #ffffff); color: var(--builtin-color-text, #111827); }
    .reply-bar { display: flex; align-items: center; justify-content: space-between; font-size: 12px; color: var(--builtin-color-muted, #6b7280); margin-bottom: 6px; }
    @media (max-width: 720px) {
      .comment { gap: 8px; }
      .avatar { width: 32px; height: 32px; }
      .replies { padding-left: 10px; }
    }
  `;

  constructor() {
    super();
    this.comments = [];
    this.sortBy = "newest";
    this.currentUser = {};
    this.maxDepth = 3;
    this.allowDelete = false;
    this.labels = {};
    this._replyTo = "";
    this._input = "";
  }

  _l(key, fallback = "") {
    return this.labels?.[key] ?? this._t(key) ?? fallback;
  }

  _sorted() {
    const list = [...(this.comments || [])];
    if (this.sortBy === "top") list.sort((a, b) => (b.likes || 0) - (a.likes || 0));
    else if (this.sortBy === "oldest") list.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
    else list.sort((a, b) => (b.time || "").localeCompare(a.time || ""));
    return list;
  }

  _like(id, liked) {
    this.dispatchEvent(new CustomEvent("builtin-like", { bubbles: true, composed: true, detail: { id, liked: !liked } }));
  }

  _delete(id) {
    this.dispatchEvent(new CustomEvent("builtin-delete", { bubbles: true, composed: true, detail: { id } }));
  }

  _submit(parentId = "") {
    if (!this._input.trim()) return;
    this.dispatchEvent(new CustomEvent("builtin-comment", { bubbles: true, composed: true, detail: { text: this._input.trim(), parentId } }));
    this._input = "";
    this._replyTo = "";
  }

  _renderComment(c, isReply = false, depth = 0) {
    const maxDepth = Math.max(1, Number(this.maxDepth) || 3);
    const canReply = depth < maxDepth;
    return html`
      <div class="comment">
        <img class="avatar" src="${c.avatar || ''}" alt="" onerror="this.style.display='none'" />
        <div class="body">
          <div class="author-row">
            <span class="author">${c.author || ""}</span>
            <span class="time">${c.time || ""}</span>
          </div>
          <div class="text">${c.content || ""}</div>
          <div class="actions">
            <button class="action ${classMap({ liked: c.liked, 'like-anim': c._justLiked })}" @click="${() => this._like(c.id, c.liked)}">
              <builtin-icon name="heart" size="12" variant="outlined"></builtin-icon> ${c.likes || 0}
            </button>
            ${canReply ? html`<button class="action" @click="${() => { this._replyTo = c.id; }}">${this._l("comment.reply", "Reply")}</button>` : ""}
            ${this.allowDelete ? html`<button class="action" @click="${() => this._delete(c.id)}">${this._l("comment.delete", "Delete")}</button>` : ""}
          </div>
          ${this._replyTo === c.id ? html`
            <div style="margin-top:8px;">
              <div class="reply-bar">
                <span>${this._l("comment.replyingTo", "Replying to")} ${c.author}</span>
                <button class="action" @click="${() => this._replyTo = ''}">${this._l("comment.cancel", "Cancel")}</button>
              </div>
              <textarea .value="${this._input}" @input="${(e) => this._input = e.target.value}" placeholder="${this._l("comment.write", "Write a reply...")}"></textarea>
              <button class="builtin-primary" style="margin-top:6px;" @click="${() => this._submit(c.id)}">${this._l("comment.submit", "Submit")}</button>
            </div>
          ` : ""}
          ${canReply && c.replies?.length ? html`
            <div class="replies">
              ${c.replies.map((r) => this._renderComment(r, true, depth + 1))}
            </div>
          ` : ""}
        </div>
      </div>
    `;
  }

  render() {
    const user = this.currentUser || {};
    return html`
      <div class="header">
        <span class="count">${(this.comments || []).length} ${this._l("comment.comments", "Comments")}</span>
        <select class="sort" @change="${(e) => this.dispatchEvent(new CustomEvent('builtin-sort', { bubbles:true, composed:true, detail:{sortBy:e.target.value} }))}">
          <option value="newest" ?selected="${this.sortBy==='newest'}">${this._l("comment.newest", "Newest")}</option>
          <option value="top" ?selected="${this.sortBy==='top'}">${this._l("comment.top", "Top")}</option>
          <option value="oldest" ?selected="${this.sortBy==='oldest'}">${this._l("comment.oldest", "Oldest")}</option>
        </select>
      </div>
      ${this._sorted().map((c) => this._renderComment(c, false, 0))}
      <div class="input-box">
        <img class="avatar" src="${user.avatar || ''}" alt="" onerror="this.style.display='none'" />
        <div style="flex:1;">
          <textarea .value="${this._input}" @input="${(e) => this._input = e.target.value}" placeholder="${this._l("comment.write", "Write a comment...")}"></textarea>
          <button class="builtin-primary" style="margin-top:6px;" @click="${() => this._submit()}">${this._l("comment.submit", "Submit")}</button>
        </div>
      </div>
    `;
  }
}
