import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) { if (!value) return undefined; try { return JSON.parse(value); } catch { return undefined; } },
  toAttribute(value) { return JSON.stringify(value); }
};

/**
 * @fileoverview BuiltinTplSocialProfile — LinkedIn/Facebook-style social profile.
 *
 * @attr {string} name — Profile name.
 * @attr {string} headline — Headline text.
 * @attr {string} location — Location string.
 * @attr {string} avatar — Avatar URL.
 * @attr {string} cover — Cover photo URL.
 * @attr {string} stats — JSON {connections, followers}.
 * @attr {string} about — Bio text.
 * @attr {string} skills — JSON array of strings.
 * @attr {string} posts — JSON array of post objects.
 * @attr {string} people-also-viewed — JSON array of people objects.
 * @attr {string} labels — JSON i18n overrides.
 */
export class BuiltinTplSocialProfile extends BuiltinBaseElement {
  static properties = {
    name: { type: String },
    headline: { type: String },
    location: { type: String },
    avatar: { type: String },
    cover: { type: String },
    stats: { type: Object },
    about: { type: String },
    skills: { type: Array },
    posts: { type: Array },
    peopleAlsoViewed: { type: Array, attribute: "people-also-viewed" },
    labels: { type: Object, converter: jsonConverter },
        _connected: { type: Boolean, state: true },
    _bookmarkedPosts: { type: Array, state: true },
  };

  static styles = css`
    :host { display: block; background: var(--builtin-header-bg, #f9fafb); min-height: 100vh; }
    .cover { height: 220px; background: linear-gradient(135deg, var(--builtin-primary, #2563eb), #1e40af); position: relative; }
    .cover img { width: 100%; height: 100%; object-fit: cover; }
    .profile-wrap { max-width: 960px; margin: 0 auto; padding: 0 20px; }
    .profile-card {
      background: var(--builtin-surface, #ffffff); border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px);
      padding: 20px; margin-top: -50px; position: relative;
    }
    .avatar { width: 110px; height: 110px; border-radius: 50%; border: 4px solid var(--builtin-surface, #ffffff); object-fit: cover; background: var(--builtin-header-bg, #f9fafb); }
    .name-row { margin-top: 10px; }
    .name { font-size: 22px; font-weight: 800; color: var(--builtin-color-text, #111827); }
    .headline { font-size: 14px; color: var(--builtin-color-muted, #6b7280); margin-top: 4px; }
    .loc { font-size: 13px; color: var(--builtin-color-muted, #6b7280); margin-top: 4px; display: flex; align-items: center; gap: 4px; }
    .stats { display: flex; gap: 16px; margin-top: 10px; font-size: 13px; color: var(--builtin-primary, #2563eb); font-weight: 600; }
    .actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
    .btn { padding: 8px 18px; border-radius: var(--builtin-radius, 6px); border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-button-bg, #ffffff); color: var(--builtin-color-text, #111827); font-weight: 600; cursor: pointer; font: inherit; }
    .btn.primary { background: var(--builtin-primary, #2563eb); border-color: var(--builtin-primary, #2563eb); color: #fff; }
    .layout { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-top: 20px; }
    .panel {
      background: var(--builtin-surface, #ffffff); border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px); padding: 18px;
    }
    .panel h3 { margin: 0 0 12px; font-size: 16px; color: var(--builtin-color-text, #111827); }
    .skills { display: flex; flex-wrap: wrap; gap: 6px; }
    .right-col { display: flex; flex-direction: column; gap: 16px; }
    .post-actions { display: flex; gap: 16px; margin-top: 10px; }
    .post-actions button { display: flex; align-items: center; gap: 4px; background: none; border: none; color: var(--builtin-color-muted, #6b7280); cursor: pointer; font: inherit; font-size: 13px; font-weight: 600; padding: 4px 8px; border-radius: 4px; }
    .post-actions button:hover { background: var(--builtin-header-bg, #f3f4f6); color: var(--builtin-color-text, #111827); }
    .post-actions button.liked { color: var(--builtin-primary, #2563eb); }
    @media (max-width: 720px) {
      .profile-card { margin-top: -40px; }
      .avatar { width: 80px; height: 80px; }
      .layout { grid-template-columns: 1fr; }
      .cover { height: 140px; }
    }
  `;

  _default_avatar() {
    return "https://i.pravatar.cc/150";
  }

  _defaultPosts() {
    return [
      {
        id: "post-1",
        images: ["https://picsum.photos/600/340?random=4"],
        avatar: "https://i.pravatar.cc/150?u=1",
        author: "Alex Morgan",
        title: "The Future of Web Components",
        content: "Web components are becoming the standard for reusable UI across frameworks...",
        likes: 24,
        comments: 5,
        liked: false,
      },
      {
        id: "post-2",
        images: [],
        avatar: "https://i.pravatar.cc/150?u=2",
        author: "Jordan Lee",
        title: "Design Systems at Scale",
        content: "How we built a design system that serves 50+ product teams...",
        likes: 18,
        comments: 3,
        liked: false,
      },
    ];
  }

  _defaultPeopleAlsoViewed() {
    return [
      { name: "Sam Taylor", title: "Product Designer", avatar: "https://i.pravatar.cc/150?u=3" },
      { name: "Casey Kim", title: "Engineering Manager", avatar: "https://i.pravatar.cc/150?u=4" },
    ];
  }

  render() {
    const s = this.stats || {};
    const avatar = this.avatar || (this._default_avatar());
    const posts = this.posts || (this._defaultPosts());
    const people_also_viewed = this.peopleAlsoViewed || (this._defaultPeopleAlsoViewed());

    return html`
      <div class="cover">${this.cover ? html`<img src="${this.cover}" alt="${this.name ? `${this.name} cover photo` : "Cover photo"}" />` : ""}</div>
      <div class="profile-wrap">
        <div class="profile-card">
          ${avatar ? html`<img class="avatar" src="${avatar}" alt="${this.name || ''}" />` : html`<div class="avatar"></div>`}
          <div class="name-row">
            <div class="name">${this.name || ""}</div>
            <div class="headline">${this.headline || ""}</div>
            ${this.location ? html`<div class="loc"><builtin-icon name="environment" size="12" variant="outlined"></builtin-icon>${this.location}</div>` : ""}
          </div>
          <div class="stats">
            <span>${s.connections || 0} ${this._l("profile.connections", "connections")}</span>
            <span>${s.followers || 0} ${this._l("profile.followers", "followers")}</span>
          </div>
          <div class="actions">
            <button class="btn primary" @click="${() => { this._connected = !this._connected; this.dispatchEvent(new CustomEvent('builtin-connect', { bubbles: true, composed: true, detail: { name: this.name, connected: this._connected } })); }}">${this._l("profile.connect", "Connect")}</button>
            <button class="btn" @click="${() => this.dispatchEvent(new CustomEvent('builtin-message', { bubbles: true, composed: true, detail: { name: this.name } }))}">${this._l("profile.message", "Message")}</button>
          </div>
        </div>
        <div class="layout">
          <div class="left-col">
            <builtin-tabs type="underline" active="posts">
              <div data-tab="posts">
                ${posts.map((post) => html`
                  <div style="margin-bottom:16px;">
                    <builtin-social-blog-card
                      images='${JSON.stringify(post.images || [])}'
                      avatar="${post.avatar || ""}"
                      author="${post.author || ""}"
                      title="${post.title || ""}"
                      content="${post.content || ""}"
                      likes="${post.likes || 0}"
                      comments="${post.comments || 0}"
                    ></builtin-social-blog-card>
                    <div class="post-actions">
                      <button class="${post.liked ? "liked" : ""}" @click="${() => this.dispatchEvent(new CustomEvent('builtin-post-like', { bubbles: true, composed: true, detail: { postId: post.id, liked: !post.liked } }))}">
                        <builtin-icon name="like${post.liked ? "-fill" : ""}" size="16" variant="outlined"></builtin-icon>
                        ${post.liked ? "Liked" : "Like"}
                      </button>
                      <button @click="${() => this.dispatchEvent(new CustomEvent('builtin-post-comment', { bubbles: true, composed: true, detail: { postId: post.id } }))}">
                        <builtin-icon name="comment" size="16" variant="outlined"></builtin-icon>
                        Comment
                      </button>
                      <button @click="${() => this.dispatchEvent(new CustomEvent('builtin-post-share', { bubbles: true, composed: true, detail: { postId: post.id } }))}">
                        <builtin-icon name="share-alt" size="16" variant="outlined"></builtin-icon>
                        Share
                      </button>
                    </div>
                  </div>
                `)}
              </div>
              <div data-tab="about">
                <div class="panel">
                  <h3>${this._l("profile.about", "About")}</h3>
                  <p style="font-size:14px;color:var(--builtin-color-text);line-height:1.6;">${this.about || ""}</p>
                  <div class="skills" style="margin-top:12px;">
                    ${(this.skills || []).map((sk) => html`<builtin-chip text="${sk}"></builtin-chip>`)}
                  </div>
                </div>
              </div>
              <div data-tab="experience"><div class="panel"><h3>${this._l("profile.experience", "Experience")}</h3><p style="color:var(--builtin-color-muted);font-size:13px;">Experience content goes here.</p></div></div>
            </builtin-tabs>
          </div>
          <div class="right-col">
            <div class="panel">
              <h3>${this._l("profile.peopleAlsoViewed", "People also viewed")}</h3>
              <div style="display:flex;flex-direction:column;gap:10px;">
                ${people_also_viewed.map((p) => html`
                  <div style="display:flex;align-items:center;gap:10px;">
                    <builtin-avatar size="36" src="${p.avatar || ""}" name="${p.name || ""}"></builtin-avatar>
                    <div>
                      <div style="font-size:13px;font-weight:600;color:var(--builtin-color-text);">${p.name || ""}</div>
                      <div style="font-size:12px;color:var(--builtin-color-muted);">${p.title || ""}</div>
                    </div>
                  </div>
                `)}
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }
}