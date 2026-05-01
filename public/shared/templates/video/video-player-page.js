/**
 * @fileoverview BuiltinTplVideoPlayerPage - Video streaming page template (Lit).
 *
 * Attributes:
 *   - title: Video title
 *   - views: View count string
 *   - channel: Channel name
 *   - subscribers: Subscribers string
 *   - labels: JSON object for i18n overrides
 *   - video: JSON object { title, channel, views, description }
 *   - related-videos: JSON array of { title, channel, duration }
 *   - comments: JSON array of { author, text, time }
 *
 * Events:
 *   - builtin-play: Play button clicked.
 *   - builtin-like: Like button clicked.
 *   - builtin-dislike: Dislike button clicked.
 *   - builtin-share: Share button clicked.
 *   - builtin-subscribe: Subscribe button clicked.
 *   - builtin-video-click: Related video clicked. Detail: { title, channel }.
 *   - builtin-comment-submit: Comment submitted. Detail: { text }.
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - video: Video element override
 *   - sidebar: Extra sidebar content
 *   - comments: Comments section override
 *   - footer: Page footer
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const DEFAULT_VIDEO_SRC = "/test-media/sample-video.mp4";

export class BuiltinTplVideoPlayerPage extends BuiltinBaseElement {
  static get properties() {
    return {
      title: { type: String },
      views: { type: String },
      channel: { type: String },
      subscribers: { type: String },
      src: { type: String },
      labels: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "{}"); } catch { return {}; }
          },
        },
      },
            video: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "null"); } catch { return null; }
          },
        },
      },
      relatedVideos: {
        type: Array,
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "[]"); } catch { return []; }
          },
        },
      },
      comments: {
        type: Array,
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "[]"); } catch { return []; }
          },
        },
      },
    };
  }

  constructor() {
    super();
    this.title = "Video Title";
    this.views = "0 views";
    this.channel = "Channel Name";
    this.subscribers = "0 subscribers";
    this.src = DEFAULT_VIDEO_SRC;
    this.labels = {};
    this.video = null;
    this.relatedVideos = null;
    this.comments = null;
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = String(this.labels[key]);
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  _onPlayClick() {
    this.dispatchEvent(
      new CustomEvent("builtin-play", { bubbles: true, composed: true })
    );
  }

  _onLike() {
    this.dispatchEvent(
      new CustomEvent("builtin-like", { bubbles: true, composed: true })
    );
  }

  _onDislike() {
    this.dispatchEvent(
      new CustomEvent("builtin-dislike", { bubbles: true, composed: true })
    );
  }

  _onShare() {
    this.dispatchEvent(
      new CustomEvent("builtin-share", { bubbles: true, composed: true })
    );
  }

  _onSubscribe() {
    this.dispatchEvent(
      new CustomEvent("builtin-subscribe", { bubbles: true, composed: true })
    );
  }

  _defaultVideo() {
    return {
      title: "Demo Video Title",
      channel: "Demo Channel",
      views: "1.2M views",
      description: "This is a demo video description showcasing the player page template.",
    };
  }

  _defaultRelatedVideos() {
    return [
      { title: "Recommended video one title goes here", channel: "Channel A", duration: "10:24" },
      { title: "Recommended video two", channel: "Channel B", duration: "8:15" },
      { title: "Another recommendation", channel: "Channel C", duration: "12:05" },
      { title: "Fourth recommended video", channel: "Channel D", duration: "6:30" },
    ];
  }

  _defaultComments() {
    return [
      { author: "User One", text: "Great video, thanks for sharing!", time: "2 days ago" },
      { author: "User Two", text: "Very helpful, looking forward to more content.", time: "1 week ago" },
      { author: "User Three", text: "Amazing quality, subscribed!", time: "3 days ago" },
    ];
  }

  _getVideo() {
    if (this.video && typeof this.video === "object") return this.video;
    return this._defaultVideo();
    return { title: this.title, channel: this.channel, views: this.views, description: "" };
  }

  _getRelatedVideos() {
    if (Array.isArray(this.relatedVideos) && this.relatedVideos.length) return this.relatedVideos;
    return this._defaultRelatedVideos();
  }

  _getComments() {
    if (Array.isArray(this.comments) && this.comments.length) return this.comments;
    return this._defaultComments();
  }

  _onRelatedClick(item) {
    this.dispatchEvent(
      new CustomEvent("builtin-video-click", {
        bubbles: true,
        composed: true,
        detail: { title: item.title, channel: item.channel },
      })
    );
  }

  _onCommentSubmit() {
    const input = this.shadowRoot.querySelector(".comment-input");
    const text = input?.value?.trim();
    if (!text) return;
    this.dispatchEvent(
      new CustomEvent("builtin-comment-submit", {
        bubbles: true,
        composed: true,
        detail: { text },
      })
    );
    if (input) input.value = "";
  }

  _renderComments() {
    const comments = this._getComments();
    return html`
      <slot name="comments">
        <div class="comment-form">
          <input
            class="comment-input"
            type="text"
            placeholder="${this._l("video.addComment", "Add a comment...")}"
            @keydown="${(e) => { if (e.key === "Enter") this._onCommentSubmit(); }}"
          />
          <button class="comment-submit" @click="${this._onCommentSubmit}">
            ${this._l("video.post", "Post")}
          </button>
        </div>
        ${comments.map(
          (c) => html`
            <div class="comment">
              <div class="comment-avatar"></div>
              <div class="comment-body">
                <div class="comment-author">${c.author}</div>
                <div class="comment-text">${c.text}</div>
                <div class="comment-time">${c.time}</div>
              </div>
            </div>
          `
        )}
      </slot>
    `;
  }

  _renderRecommended() {
    const recs = this._getRelatedVideos();
    return html`
      ${recs.map(
        (r) => html`
          <div class="rec-card" @click="${() => this._onRelatedClick(r)}">
            <div class="rec-thumb">Thumb</div>
            <div class="rec-info">
              <div class="rec-title">${r.title}</div>
              <div class="rec-meta">${r.channel} · ${r.duration}</div>
            </div>
          </div>
        `
      )}
    `;
  }

  render() {
    const video = this._getVideo();
    const sidebar = html`
      <aside class="sidebar">
        <div class="sidebar-title">${this._t("video.recommended")}</div>
        <div class="rec-list">${this._renderRecommended()}</div>
        <slot name="sidebar"></slot>
      </aside>
    `;

    return html`
      <div class="page">
        <div class="navbar-slot">
          <slot name="navbar"></slot>
        </div>
        <div class="main">
          <div class="primary">
            <div class="video-slot">
              <slot name="video">
                <video class="player-video" src="${this.src || DEFAULT_VIDEO_SRC}" controls preload="metadata"></video>
              </slot>
            </div>
            <div class="info-row">
              <h1 class="video-title">${video.title}</h1>
              <div class="meta-row">
                <span>${video.views}</span>
                <div class="actions">
                  <button class="action-btn" @click=${this._onLike} aria-label="Like">
                    <builtin-icon name="like" size="16" variant="outlined"></builtin-icon>
                    ${this._t("video.like")}
                  </button>
                  <button class="action-btn" @click=${this._onDislike} aria-label="Dislike">
                    <builtin-icon name="dislike" size="16" variant="outlined"></builtin-icon>
                    ${this._t("video.dislike")}
                  </button>
                  <button class="action-btn" @click=${this._onShare} aria-label="Share">
                    <builtin-icon name="share-alt" size="16" variant="outlined"></builtin-icon>
                    ${this._t("video.share")}
                  </button>
                </div>
              </div>
            </div>
            <div class="channel-row">
              <div class="avatar">
                <builtin-icon name="user" size="20" variant="outlined"></builtin-icon>
              </div>
              <div class="channel-info">
                <div class="channel-name">${video.channel}</div>
                <div class="channel-subs">${this.subscribers}</div>
              </div>
              <button class="subscribe-btn" @click=${this._onSubscribe}>
                ${this._t("video.subscribe")}
              </button>
            </div>
            ${video.description
              ? html`<div class="description">${video.description}</div>`
              : ""}
            <div class="comments">
              <div class="section-title">${this._t("video.comments")}</div>
              ${this._renderComments()}
            </div>
            ${this._ptMobile ? sidebar : ""}
          </div>
          ${!this._ptMobile ? sidebar : ""}
        </div>
        <div class="footer-slot">
          <slot name="footer"></slot>
        </div>
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .page {
        display: flex;
        flex-direction: column;
        min-height: 100vh;
      }
      .navbar-slot {
        position: sticky;
        top: 0;
        z-index: 10;
      }
      .main {
        display: flex;
        gap: 20px;
        padding: 16px;
        max-width: 1280px;
        margin: 0 auto;
        width: 100%;
        box-sizing: border-box;
      }
      .primary {
        flex: 1;
        min-width: 0;
      }
      .sidebar {
        width: 340px;
        flex-shrink: 0;
      }
      .video-slot {
        width: 100%;
      }
      .player-video {
        width: 100%;
        aspect-ratio: 16 / 9;
        display: block;
        background: #000;
        border-radius: var(--builtin-radius-lg, 8px);
        object-fit: contain;
      }
      .info-row {
        margin-top: 12px;
      }
      .video-title {
        font-size: 20px;
        font-weight: 600;
        margin: 0 0 8px;
        line-height: 1.3;
        color: var(--builtin-color-text);
      }
      .meta-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 8px;
        color: var(--builtin-color-muted);
        font-size: 14px;
      }
      .actions {
        display: flex;
        gap: 8px;
      }
      .action-btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-surface);
        color: var(--builtin-color-text);
        font-size: 13px;
        cursor: pointer;
      }
      .action-btn:hover {
        background: var(--builtin-row-hover-bg);
      }
      .channel-row {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 14px;
        padding: 12px 0;
        border-top: 1px solid var(--builtin-border-soft);
        border-bottom: 1px solid var(--builtin-border-soft);
      }
      .avatar {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--builtin-border);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 16px;
        color: var(--builtin-color-muted);
        flex-shrink: 0;
      }
      .channel-info {
        flex: 1;
        min-width: 0;
      }
      .channel-name {
        font-weight: 600;
        font-size: 15px;
        color: var(--builtin-color-text);
      }
      .channel-subs {
        font-size: 13px;
        color: var(--builtin-color-muted);
      }
      .subscribe-btn {
        padding: 8px 16px;
        border: none;
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-primary);
        color: #fff;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        flex-shrink: 0;
      }
      .subscribe-btn:hover {
        filter: brightness(1.1);
      }
      .description {
        margin-top: 12px;
        font-size: 14px;
        line-height: 1.5;
        color: var(--builtin-color-text);
        white-space: pre-wrap;
      }
      .comments {
        margin-top: 20px;
      }
      .section-title {
        font-size: 16px;
        font-weight: 600;
        margin: 0 0 12px;
        color: var(--builtin-color-text);
      }
      .comment-form {
        display: flex;
        gap: 8px;
        margin-bottom: 12px;
      }
      .comment-input {
        flex: 1;
        min-width: 0;
        padding: 8px 12px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-surface);
        color: var(--builtin-color-text);
        font-size: 14px;
      }
      .comment-submit {
        padding: 8px 16px;
        border: none;
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-primary);
        color: #fff;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        flex-shrink: 0;
      }
      .comment-submit:hover {
        filter: brightness(1.1);
      }
      .comment {
        display: flex;
        gap: 10px;
        padding: 10px 0;
        border-bottom: 1px solid var(--builtin-border-soft);
      }
      .comment-avatar {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: var(--builtin-border);
        flex-shrink: 0;
      }
      .comment-body {
        flex: 1;
        min-width: 0;
      }
      .comment-author {
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 4px;
        color: var(--builtin-color-text);
      }
      .comment-text {
        font-size: 14px;
        line-height: 1.4;
        color: var(--builtin-color-text);
      }
      .comment-time {
        font-size: 12px;
        color: var(--builtin-color-muted);
        margin-top: 2px;
      }
      .sidebar-title {
        font-size: 16px;
        font-weight: 600;
        margin: 0 0 12px;
        color: var(--builtin-color-text);
      }
      .rec-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .rec-card {
        display: flex;
        gap: 10px;
        cursor: pointer;
      }
      .rec-thumb {
        width: 120px;
        height: 68px;
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-border);
        flex-shrink: 0;
        overflow: hidden;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        color: var(--builtin-color-muted);
      }
      .rec-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .rec-title {
        font-size: 14px;
        font-weight: 500;
        line-height: 1.3;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        color: var(--builtin-color-text);
      }
      .rec-meta {
        font-size: 12px;
        color: var(--builtin-color-muted);
      }
      .footer-slot {
        margin-top: auto;
      }
      @media (max-width: 720px) {
        .main {
          flex-direction: column;
          padding: 12px;
        }
        .sidebar {
          width: 100%;
        }
        .rec-list {
          flex-direction: row;
          overflow-x: auto;
          gap: 12px;
          padding-bottom: 4px;
        }
        .rec-card {
          flex-direction: column;
          width: 160px;
          flex-shrink: 0;
        }
        .rec-thumb {
          width: 100%;
          height: 90px;
        }
        .video-title {
          font-size: 18px;
        }
        .meta-row {
          flex-direction: column;
          align-items: flex-start;
        }
      }
    `;
  }
}