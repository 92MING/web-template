import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) { if (!value) return undefined; try { return JSON.parse(value); } catch { return undefined; } },
  toAttribute(value) { return JSON.stringify(value); }
};

/**
 * @fileoverview BuiltinTplVideoPlatform — YouTube-style video platform homepage.
 *
 * @attr {string} videos — JSON array of {id, thumbnail, title, channel, avatar, views, timeAgo, duration}.
 * @attr {string} categories — JSON array of category strings.
 * @attr {string} labels — JSON i18n overrides.
 */
export class BuiltinTplVideoPlatform extends BuiltinBaseElement {
  static properties = {
    videos: { type: Array },
    categories: { type: Array },
    labels: { type: Object, converter: jsonConverter },
    userName: { type: String },
    userAvatar: { type: String },
    sidebarItems: { type: Array },
        _activeCategory: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; }
    .layout { display: flex; }
    .sidebar { width: 220px; flex-shrink: 0; border-right: 1px solid var(--builtin-border-soft, #e5e7eb); min-height: 100vh; background: var(--builtin-surface, #ffffff); }
    .main { flex: 1; min-width: 0; }
    .chips { display: flex; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); overflow-x: auto; scrollbar-width: none; background: var(--builtin-surface, #ffffff); }
    .chips::-webkit-scrollbar { display: none; }
    .chip { padding: 6px 14px; border-radius: 999px; border: 1px solid var(--builtin-border, #d1d5db); background: var(--builtin-button-bg, #ffffff); color: var(--builtin-color-text, #111827); font-size: 13px; cursor: pointer; white-space: nowrap; }
    .chip.active { background: var(--builtin-color-text, #111827); color: #fff; border-color: var(--builtin-color-text, #111827); }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; padding: 16px; }
    .video { cursor: pointer; }
    .thumb { position: relative; aspect-ratio: 16 / 9; border-radius: var(--builtin-radius-lg, 8px); overflow: hidden; background: var(--builtin-header-bg, #f9fafb); }
    .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .duration { position: absolute; bottom: 6px; right: 6px; background: rgba(0,0,0,0.75); color: #fff; font-size: 11px; padding: 2px 5px; border-radius: 4px; }
    .info { display: flex; gap: 10px; margin-top: 10px; }
    .info img { width: 36px; height: 36px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }
    .meta { min-width: 0; }
    .title { font-size: 14px; font-weight: 600; color: var(--builtin-color-text, #111827); line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .sub { font-size: 12px; color: var(--builtin-color-muted, #6b7280); margin-top: 4px; }
    .mobile-nav { display: none; padding: 10px 14px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); background: var(--builtin-surface, #ffffff); }
    @media (max-width: 720px) {
      .sidebar { display: none; }
      .mobile-nav { display: flex; align-items: center; gap: 10px; }
      .grid { grid-template-columns: 1fr; padding: 10px; gap: 14px; }
    }
  `;

  _defaultSidebarItems() {
    return [
      {
        label: this._l("video.menu", "Menu"),
        items: [
          { label: this._l("video.home", "Home"), href: "#", icon: "home" },
          { label: this._l("video.trending", "Trending"), href: "#", icon: "fire" },
          { label: this._l("video.subscriptions", "Subscriptions"), href: "#", icon: "play-square" },
          { label: this._l("video.library", "Library"), href: "#", icon: "folder" },
        ],
      },
    ];
  }

  _defaultCategories() {
    return ["All", "Music", "Gaming", "News", "Live", "Sports"];
  }

  _defaultVideos() {
    return [
      {
        id: "demo-1",
        thumbnail: "https://picsum.photos/seed/v1/640/360",
        title: this._l("video.demo.title1", "Getting Started with VideoHub"),
        channel: this._l("video.demo.channel", "VideoHub Channel"),
        avatar: "https://i.pravatar.cc/150?u=demo",
        views: "1.2M views",
        timeAgo: "2 days ago",
        duration: "10:23",
      },
      {
        id: "demo-2",
        thumbnail: "https://picsum.photos/seed/v2/640/360",
        title: this._l("video.demo.title2", "Top 10 Highlights of the Week"),
        channel: this._l("video.demo.channel", "VideoHub Channel"),
        avatar: "https://i.pravatar.cc/150?u=demo",
        views: "856K views",
        timeAgo: "5 hours ago",
        duration: "8:45",
      },
      {
        id: "demo-3",
        thumbnail: "https://picsum.photos/seed/v3/640/360",
        title: this._l("video.demo.title3", "Live Stream Replay: Q&A Session"),
        channel: this._l("video.demo.channel", "VideoHub Channel"),
        avatar: "https://i.pravatar.cc/150?u=demo",
        views: "324K views",
        timeAgo: "1 week ago",
        duration: "45:12",
      },
    ];
  }

  render() {
    const videos = this.videos || (this._defaultVideos());
    const cats = this.categories || (this._defaultCategories());
    const sidebarItems = this.sidebarItems || (this._defaultSidebarItems());
    const active = this._activeCategory || cats[0] || "All";

    return html`
      <builtin-navbar items='[]'>
        <div slot="brand" style="display:flex;align-items:center;gap:10px;">
          <button class="hamburger" style="display:none;padding:6px;border:1px solid var(--builtin-border);border-radius:6px;background:var(--builtin-button-bg);" @click="${() => {}}">
            <builtin-icon name="menu" size="18" variant="outlined"></builtin-icon>
          </button>
          <span style="font-weight:800;font-size:18px;">${this._l("video.brand", "VideoHub")}</span>
        </div>
        <div slot="actions" style="display:flex;align-items:center;gap:10px;flex:1;max-width:480px;">
          <builtin-search-bar placeholder="${this._l("video.search", "Search videos...")}" style="flex:1;"></builtin-search-bar>
          <builtin-notification-badge count="2"><builtin-icon name="bell" size="20" variant="outlined"></builtin-icon></builtin-notification-badge>
          <builtin-user-menu name="${this.userName || this._l("video.userName", "User") }" avatar="${this.userAvatar || "https://i.pravatar.cc/150?u=vh"}"></builtin-user-menu>
        </div>
      </builtin-navbar>
      <div class="layout">
        <div class="sidebar">
          <builtin-sidebar .items="${sidebarItems}"></builtin-sidebar>
        </div>
        <div class="main">
          <div class="mobile-nav">
            <builtin-icon name="menu" size="20" variant="outlined"></builtin-icon>
            <span style="font-weight:700;">${this._l("video.brand", "VideoHub")}</span>
          </div>
          <div class="chips">
            ${cats.map((c) => html`<button class="chip ${classMap({ active: c === active })}" @click="${() => { this._activeCategory = c; this.dispatchEvent(new CustomEvent("builtin-category-change", { detail: { category: c }, bubbles: true, composed: true })); }}">${c}</button>`)}
          </div>
          <div class="grid">
            ${videos.map((v) => html`
              <div class="video" @click="${() => this.dispatchEvent(new CustomEvent("builtin-video-click", { detail: { id: v.id, title: v.title }, bubbles: true, composed: true }))}">
                <div class="thumb">
                  <img src="${v.thumbnail}" alt="" loading="lazy" />
                  ${v.duration ? html`<span class="duration">${v.duration}</span>` : ""}
                </div>
                <div class="info">
                  <img src="${v.avatar || "https://i.pravatar.cc/150"}" alt="" />
                  <div class="meta">
                    <div class="title">${v.title}</div>
                    <div class="sub">${v.channel || ""} · ${v.views || ""} · ${v.timeAgo || ""}</div>
                  </div>
                </div>
              </div>
            `)}
          </div>
        </div>
      </div>
    `;
  }
}