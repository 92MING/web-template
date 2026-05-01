import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

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
 * @fileoverview Social media style personal profile template.
 *
 * @description A profile page with cover image, avatar, name, handle, bio, stats,
 * action buttons, tabs, and a timeline with post cards. Ideal for social networks
 * or user directory pages.
 *
 * Attributes:
 *   - name: Display name
 *   - handle: User handle (e.g. "janedoe", shown as @handle)
 *   - avatar: Avatar image URL
 *   - cover: Cover image URL
 *   - bio: Short bio text
 *   - stats: JSON object { followers, following, posts }
 *   - posts: JSON array of post objects { id, content, likes }
 *   - active-tab: Currently active tab id (default: "timeline")
 *   - labels: JSON object to override i18n strings
 *
 * Slots:
 *   - cover: Cover image area
 *   - avatar: Avatar image or component
 *   - timeline: Custom timeline tab content
 *   - about: Custom about tab content
 *   - photos: Custom photos tab content
 *   - friends: Custom friends tab content
 *   - footer: Custom footer content
 *
 * Events:
 *   - builtin-follow { name, following }
 *   - builtin-message { name }
 *   - builtin-post-like { postId }
 *   - builtin-post-click { id }
 *
 * Usage example:
 *   ```html
 *   <builtin-tpl-profile-personal name="Alex Smith" handle="alexsmith">
 *     <img slot="cover" src="cover.jpg" />
 *     <builtin-avatar slot="avatar" src="avatar.jpg"></builtin-avatar>
 *     <div slot="footer">...</div>
 *   </builtin-tpl-profile-personal>
 *   ```
 */
export class BuiltinTplProfilePersonal extends BuiltinBaseElement {
  static properties = {
    name: { type: String },
    handle: { type: String },
    avatar: { type: String },
    cover: { type: String },
    bio: { type: String },
    stats: { type: Object, converter: jsonConverter },
    posts: { type: Array, converter: jsonConverter },
    activeTab: { type: String, attribute: "active-tab" },
    labels: { type: Object, converter: jsonConverter },
        _following: { type: Boolean, state: true },
  };

  static styles = css`
    :host {
      display: block;
      font-family: inherit;
      color: var(--builtin-color-text, #111827);
      background: var(--builtin-surface, #ffffff);
      line-height: 1.55;
    }
    h1, h2, h3, h4, p { margin: 0; }
    .cover {
      position: relative;
      width: 100%;
      height: 280px;
      background: var(--builtin-header-bg, #f9fafb);
      overflow: hidden;
    }
    .cover img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .cover ::slotted([slot="cover"]) {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .profile-wrap {
      max-width: 960px;
      margin: 0 auto;
      padding: 0 20px;
      position: relative;
    }
    .identity {
      display: flex;
      align-items: flex-end;
      gap: 20px;
      margin-top: -60px;
      position: relative;
      z-index: 2;
    }
    .avatar {
      width: 120px;
      height: 120px;
      border-radius: 50%;
      border: 4px solid var(--builtin-surface, #ffffff);
      background: var(--builtin-header-bg, #f9fafb);
      overflow: hidden;
      flex-shrink: 0;
    }
    .avatar img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .avatar ::slotted([slot="avatar"]) {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .name-bio { padding-bottom: 8px; }
    .name-bio h1 { font-size: 24px; font-weight: 800; }
    .name-bio p { color: var(--builtin-color-muted, #6b7280); font-size: 14px; margin-top: 4px; }
    .name-bio .handle { color: var(--builtin-color-muted, #6b7280); font-size: 13px; margin-top: 2px; }
    .actions {
      display: flex;
      gap: 8px;
      margin-left: auto;
      padding-bottom: 8px;
      flex-wrap: wrap;
    }
    .btn {
      padding: 8px 18px;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border, #d1d5db);
      background: var(--builtin-button-bg, #ffffff);
      color: var(--builtin-color-text, #111827);
      font-weight: 600;
      cursor: pointer;
      font: inherit;
    }
    .btn.primary {
      background: var(--builtin-primary, #2563eb);
      border-color: var(--builtin-primary, #2563eb);
      color: #fff;
    }
    .stats {
      display: flex;
      gap: 28px;
      padding: 20px 0;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .stat { text-align: center; }
    .stat .num { font-weight: 700; font-size: 18px; }
    .stat .lbl { font-size: 12px; color: var(--builtin-color-muted, #6b7280); display: flex; align-items: center; justify-content: center; gap: 4px; }
    .tabs {
      display: flex;
      gap: 6px;
      padding: 12px 0;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
      overflow-x: auto;
    }
    .tab {
      padding: 8px 16px;
      border-radius: var(--builtin-radius, 6px);
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      background: transparent;
      border: 1px solid transparent;
      color: var(--builtin-color-muted, #6b7280);
    }
    .tab[aria-selected="true"] {
      background: var(--builtin-button-bg, #ffffff);
      border-color: var(--builtin-border, #d1d5db);
      color: var(--builtin-color-text, #111827);
    }
    .tab:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .content {
      padding: 24px 0;
      min-height: 200px;
    }
    .post-list { display: flex; flex-direction: column; gap: 16px; }
    .post-card {
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      border-radius: var(--builtin-radius-lg, 8px);
      overflow: hidden;
      cursor: pointer;
      background: var(--builtin-surface, #ffffff);
    }
    .post-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
    .post-image { width: 100%; height: 180px; object-fit: cover; display: block; }
    .post-body { padding: 14px; }
    .post-body h4 { margin: 0 0 6px; font-size: 15px; color: var(--builtin-color-text, #111827); }
    .post-body p { margin: 0; font-size: 13px; color: var(--builtin-color-muted, #6b7280); line-height: 1.5; }
    .like-btn {
      margin-top: 10px;
      padding: 4px 12px;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border-soft, #e5e7eb);
      background: transparent;
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      color: var(--builtin-color-muted, #6b7280);
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .like-btn:hover { background: var(--builtin-button-hover-bg, #f9fafb); }
    .page-footer {
      padding: 24px 0;
      text-align: center;
      color: var(--builtin-color-muted, #6b7280);
      font-size: 13px;
      border-top: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .icon { width: 14px; height: 14px; vertical-align: middle; }

    @media (max-width: 720px) {
      .cover { height: 160px; }
      .identity {
        flex-direction: column;
        align-items: center;
        margin-top: -50px;
        text-align: center;
      }
      .avatar { width: 96px; height: 96px; }
      .name-bio { padding-bottom: 0; }
      .actions { margin-left: 0; padding-bottom: 0; justify-content: center; }
      .stats {
        justify-content: center;
        gap: 18px;
        padding: 14px 0;
      }
      .tab { padding: 8px 12px; font-size: 13px; }
      .profile-wrap { padding: 0 16px; }
    }
  `;

  constructor() {
    super();
    this.activeTab = "timeline";
  }

  _defaultStats() {
    return { followers: 4200, following: 350, posts: 128 };
  }

  _defaultPosts() {
    return [
      {
        id: "post-1",
        content: "Just getting started with this new profile. Excited to share my journey!",
        likes: 12,
      },
      {
        id: "post-2",
        content: "Small details make a huge difference in UI. Here are three things I always check before shipping.",
        likes: 8,
      },
      {
        id: "post-3",
        content: "Coffee and code — the perfect morning combination.",
        likes: 24,
      },
    ];
  }

  _onTabClick(id) {
    this.activeTab = id;
  }

  _onFollowClick() {
    this._following = !this._following;
    this.dispatchEvent(new CustomEvent("builtin-follow", {
      bubbles: true,
      composed: true,
      detail: { name: this.name, following: this._following },
    }));
  }

  _onMessageClick() {
    this.dispatchEvent(new CustomEvent("builtin-message", {
      bubbles: true,
      composed: true,
      detail: { name: this.name },
    }));
  }

  _onPostClick(id) {
    this.dispatchEvent(new CustomEvent("builtin-post-click", {
      bubbles: true,
      composed: true,
      detail: { id },
    }));
  }

  _onPostLike(postId) {
    this.dispatchEvent(new CustomEvent("builtin-post-like", {
      bubbles: true,
      composed: true,
      detail: { postId },
    }));
  }

  render() {
    const name = this.name || this._l("profile.name", "Jane Doe");
    const handle = this.handle || "";
    const bio = this.bio || this._l("profile.bio", "Building things for the web. Loves coffee, code, and cats.");
    const stats = this.stats || (this._defaultStats());
    const posts = this.posts || (this._defaultPosts());
    const avatar = this.avatar || "";
    const cover = this.cover || "";

    const tabs = [
      { id: "timeline", label: this._l("tab.timeline", "Timeline") },
      { id: "about", label: this._l("tab.about", "About") },
      { id: "photos", label: this._l("tab.photos", "Photos") },
      { id: "friends", label: this._l("tab.friends", "Friends") },
    ];

    const tabContent = () => {
      switch (this.activeTab) {
        case "timeline":
          return posts.length > 0
            ? html`
                <div class="post-list">
                  ${posts.map((post) => html`
                    <div class="post-card" @click="${() => this._onPostClick(post.id)}">
                      ${post.image ? html`<img class="post-image" src="${post.image}" alt="" />` : ""}
                      <div class="post-body">
                        ${post.title ? html`<h4>${post.title}</h4>` : ""}
                        <p>${post.content || ""}</p>
                        ${post.likes !== undefined ? html`
                          <button class="like-btn" @click="${(e) => { e.stopPropagation(); this._onPostLike(post.id); }}">
                            <builtin-icon name="heart" size="14" variant="outlined"></builtin-icon>
                            ${post.likes}
                          </button>
                        ` : ""}
                      </div>
                    </div>
                  `)}
                </div>
              `
            : html`<slot name="timeline"><p>${this._l("content.timeline", "Timeline content goes here.")}</p></slot>`;
        case "about":
          return html`<slot name="about"><p>${this._l("content.about", "About content goes here.")}</p></slot>`;
        case "photos":
          return html`<slot name="photos"><p>${this._l("content.photos", "Photos content goes here.")}</p></slot>`;
        case "friends":
          return html`<slot name="friends"><p>${this._l("content.friends", "Friends content goes here.")}</p></slot>`;
        default:
          return html`<p>${this._l("content.timeline", "Timeline content goes here.")}</p>`;
      }
    };

    return html`
      <div class="cover">
        ${cover ? html`<img src="${cover}" alt="" />` : html`<slot name="cover"></slot>`}
      </div>

      <div class="profile-wrap">
        <div class="identity">
          <div class="avatar">
            ${avatar
              ? html`<img src="${avatar}" alt="${name}" />`
              : html`<slot name="avatar"><builtin-avatar size="120" name="${name}"></builtin-avatar></slot>`}
          </div>
          <div class="name-bio">
            <h1>${name}</h1>
            ${handle ? html`<p class="handle">@${handle}</p>` : ""}
            <p>${bio}</p>
          </div>
          <div class="actions">
            <button class="btn primary" @click="${this._onFollowClick}">
              ${this._following ? this._l("btn.unfollow", "Unfollow") : this._l("btn.follow", "Follow")}
            </button>
            <button class="btn" @click="${this._onMessageClick}">
              ${this._l("btn.message", "Message")}
            </button>
          </div>
        </div>

        <div class="stats">
          <div class="stat">
            <div class="num">${stats.posts ?? "0"}</div>
            <div class="lbl">
              <builtin-icon name="file" size="14" variant="outlined"></builtin-icon>
              ${this._l("stat.posts", "Posts")}
            </div>
          </div>
          <div class="stat">
            <div class="num">${stats.followers ?? "0"}</div>
            <div class="lbl">
              <builtin-icon name="team" size="14" variant="outlined"></builtin-icon>
              ${this._l("stat.followers", "Followers")}
            </div>
          </div>
          <div class="stat">
            <div class="num">${stats.following ?? "0"}</div>
            <div class="lbl">
              <builtin-icon name="user-add" size="14" variant="outlined"></builtin-icon>
              ${this._l("stat.following", "Following")}
            </div>
          </div>
        </div>

        <div class="tabs" role="tablist">
          ${repeat(
            tabs,
            (t) => t.id,
            (t) => html`
              <button
                class="tab"
                role="tab"
                aria-selected="${t.id === this.activeTab}"
                @click=${() => this._onTabClick(t.id)}
              >${t.label}</button>
            `
          )}
        </div>

        <div class="content" role="tabpanel">
          ${tabContent()}
        </div>
      </div>

      <div class="page-footer">
        <slot name="footer"><builtin-footer></builtin-footer></slot>
      </div>
    `;
  }
}