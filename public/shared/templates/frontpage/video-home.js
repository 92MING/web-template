import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const DEFAULT_VIDEO_SRC = "/test-media/sample-video.mp4";

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
 * @fileoverview Video platform homepage template.
 *
 * @description Netflix/YouTube-style layout with a hero banner,
 * horizontally scrolling category rows, and thumbnail cards.
 *
 * Attributes:
 *   - title: Hero banner title
 *   - video-src: Hero background video URL
 *   - rows: JSON array of row configs with videos
 *   - labels: JSON object to override i18n strings
 *
 * Slots:
 *   - navbar: Top navigation bar
 *   - hero-media: Custom hero media content
 *   - footer: Page footer
 */
export class BuiltinTplFrontpageVideo extends BuiltinBaseElement {
  static properties = {
    title: { type: String },
    videoSrc: { type: String, attribute: "video-src" },
    rows: { type: Array, converter: jsonConverter },
        labels: { type: Object, converter: jsonConverter },
  };

  static styles = css`
    :host {
      display: block;
      line-height: 1.45;
      color: var(--builtin-color-text, #e5e7eb);
      background: var(--builtin-header-bg, #0f0f0f);
    }
    h1, h2, h3, p { margin: 0; }
    .dark-bar {
      background: var(--builtin-header-bg, #0f0f0f);
      border-bottom: 1px solid var(--builtin-border, #1f2937);
    }
    .hero {
      position: relative;
      min-height: 420px;
      display: flex;
      align-items: flex-end;
      padding: 0 0 40px;
      background: #020617;
      overflow: hidden;
    }
    .hero-video {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      opacity: 0.72;
    }
    .hero::after {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(2,6,23,0.92) 0%, rgba(2,6,23,0.58) 42%, rgba(2,6,23,0.12) 100%),
        linear-gradient(180deg, transparent 0%, rgba(2,6,23,0.88) 100%);
      pointer-events: none;
    }
    .hero-body { position: relative; z-index: 1; padding: 0 40px; max-width: 900px; }
    .hero h1 {
      font-size: clamp(28px, 4vw, 44px);
      font-weight: 800;
      margin-bottom: 12px;
      text-shadow: 0 2px 10px rgba(0,0,0,0.5);
      color: var(--builtin-color-text, #e5e7eb);
    }
    .hero p { font-size: 16px; color: var(--builtin-color-muted, #9ca3af); margin-bottom: 18px; max-width: 560px; }
    .play-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 24px;
      border-radius: var(--builtin-radius, 6px);
      border: 1px solid var(--builtin-border-soft, #4b5563);
      background: var(--builtin-button-bg, #1f2937);
      color: var(--builtin-color-text, #e5e7eb);
      font-weight: 700;
      cursor: pointer;
      font: inherit;
    }
    .play-btn:hover { background: var(--builtin-button-hover-bg, #374151); }
    .play-btn svg { width: 18px; height: 18px; }
    .row { padding: 18px 40px; }
    .row h2 { font-size: 18px; font-weight: 700; margin-bottom: 12px; color: var(--builtin-color-text, #e5e7eb); }
    .row-scroll {
      display: flex;
      gap: 14px;
      overflow-x: auto;
      scroll-snap-type: x mandatory;
      padding-bottom: 10px;
    }
    .row-scroll::-webkit-scrollbar { height: 8px; }
    .row-scroll::-webkit-scrollbar-thumb { background: var(--builtin-border, #374151); border-radius: 4px; }
    .thumb {
      flex: 0 0 auto;
      width: 240px;
      aspect-ratio: 16/9;
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #1f2937);
      border: 1px solid var(--builtin-border-soft, #374151);
      scroll-snap-align: start;
      overflow: hidden;
      position: relative;
      cursor: pointer;
      transition: transform .2s ease, box-shadow .2s ease;
      display: block;
    }
    .thumb-bg {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      color: rgba(255,255,255,0.85);
      font-size: 36px;
      font-weight: 800;
      letter-spacing: -1px;
      text-shadow: 0 2px 8px rgba(0,0,0,0.4);
    }
    .thumb-overlay {
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, transparent 35%, rgba(0,0,0,0.85) 100%);
      pointer-events: none;
    }
    .thumb-duration {
      position: absolute;
      right: 8px;
      top: 8px;
      background: rgba(0,0,0,0.78);
      color: #fff;
      font-size: 11px;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 4px;
      z-index: 1;
    }
    .thumb-meta {
      position: absolute;
      left: 10px;
      right: 10px;
      bottom: 8px;
      z-index: 1;
      color: #fff;
    }
    .thumb-title {
      font-size: 13px;
      font-weight: 600;
      line-height: 1.3;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      text-shadow: 0 1px 4px rgba(0,0,0,0.6);
    }
    .thumb-channel {
      font-size: 11px;
      color: rgba(255,255,255,0.75);
      margin-top: 3px;
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .thumb-channel-dot {
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: currentColor;
      opacity: .6;
    }
    .thumb:hover {
      transform: scale(1.04);
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    }
    .page-footer {
      padding: 24px 40px;
      color: var(--builtin-color-muted, #9ca3af);
      font-size: 13px;
      border-top: 1px solid var(--builtin-border, #374151);
    }

    @media (max-width: 720px) {
      .hero { min-height: 320px; padding: 0 0 28px; }
      .hero-body { padding: 0 16px; }
      .row { padding: 14px 16px; }
      .thumb { width: 160px; }
      .play-btn { width: 100%; justify-content: center; min-height: 44px; }
    }
  `;

  _defaultRows() {
    const titles = {
      trending: [
        "Behind the Scenes: Mountain Expedition",
        "AI Art in 60 Seconds",
        "Why This Recipe Broke the Internet",
        "Drone Footage of Ancient Ruins",
        "Coding Live: Building a Game",
        "The Sound That Changed Music",
      ],
      newReleases: [
        "Episode 12: The Final Twist",
        "Studio Tour with the Crew",
        "First Look at the New Lens",
        "Late Night Talk -- Special Guest",
        "Weekly Wrap: Tech Edition",
        "Unboxing: Limited Edition Set",
      ],
      recommended: [
        "Deep Dive: Ocean Mysteries",
        "30-Day Photography Challenge",
        "Live Concert Highlights",
        "Cooking with Five Ingredients",
        "Quick Workout for Busy People",
        "Stories from the Road",
      ],
    };
    const channels = ["NovaCast", "PixelLab", "Tasteful", "Wanderlens", "DevDiary", "AudioWave"];
    const palettes = [
      ["#7c3aed", "#ec4899"],
      ["#0ea5e9", "#22d3ee"],
      ["#f97316", "#facc15"],
      ["#10b981", "#3b82f6"],
      ["#ef4444", "#f97316"],
      ["#6366f1", "#8b5cf6"],
    ];
    const initials = ["NC", "PL", "TF", "WL", "DD", "AW"];
    const durations = ["4:12", "12:38", "8:05", "22:47", "1:03:22", "5:31"];
    const views = ["1.2M", "312K", "58K", "4.8M", "720K", "96K"];
    const ago = ["2 days ago", "5 days ago", "1 week ago", "3 weeks ago", "1 month ago", "6 hours ago"];

    const makeVideos = (rowKey) => {
      return Array.from({ length: 6 }, (_, idx) => {
        const i = idx % 6;
        const offset = rowKey === "newReleases" ? 1 : rowKey === "recommended" ? 2 : 0;
        const paletteIdx = (i + (rowKey.length % 6)) % 6;
        return {
          title: (titles[rowKey] || titles.trending)[i],
          channel: channels[(i + offset) % 6],
          initial: initials[paletteIdx],
          palette: palettes[paletteIdx],
          duration: durations[i],
          views: views[i],
          ago: ago[i],
        };
      });
    };

    return [
      { key: "trending", label: this._l("row.trending", "Trending"), videos: makeVideos("trending") },
      { key: "newReleases", label: this._l("row.newReleases", "New Releases"), videos: makeVideos("newReleases") },
      { key: "recommended", label: this._l("row.recommended", "Recommended"), videos: makeVideos("recommended") },
    ];
  }

  _videoCard(row, video, idx) {
    const [c1, c2] = video.palette;
    const angle = 90 + (idx % 6) * 35;
    return html`
      <a class="thumb" href="javascript:void(0)" aria-label="${video.title}"
         @click="${() => this.dispatchEvent(new CustomEvent('builtin-video-click', { bubbles: true, composed: true, detail: { title: video.title, channel: video.channel, index: idx } }))}">
        <div class="thumb-bg" style="background:linear-gradient(${angle}deg, ${c1}, ${c2});">${video.initial}</div>
        <span class="thumb-duration">${video.duration}</span>
        <div class="thumb-overlay"></div>
        <div class="thumb-meta">
          <div class="thumb-title">${video.title}</div>
          <div class="thumb-channel">
            <span>${video.channel}</span>
            <span class="thumb-channel-dot"></span>
            <span>${video.views} views</span>
            <span class="thumb-channel-dot"></span>
            <span>${video.ago}</span>
          </div>
        </div>
      </a>
    `;
  }

  render() {
    const title = this.title || this._l("hero.title", "Trending Now");
    const videoSrc = this.videoSrc || DEFAULT_VIDEO_SRC;
    const rows = this.rows?.length ? this.rows : (this._defaultRows());

    return html`
      <div class="dark-bar">
        <slot name="navbar"><builtin-navbar></builtin-navbar></slot>
      </div>

      <section class="hero">
        <video class="hero-video" src="${videoSrc}" autoplay muted loop playsinline></video>
        <div class="hero-body">
          <slot name="hero-media">
            <h1>${title}</h1>
            <p>${this._l("hero.desc", "Watch the most talked-about videos, curated just for you.")}</p>
            <button class="play-btn"
                    @click="${() => this.dispatchEvent(new CustomEvent('builtin-play-hero', { bubbles: true, composed: true }))}">
              <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
              ${this._l("hero.play", "Play")}
            </button>
          </slot>
        </div>
      </section>

      ${repeat(rows, (r) => r.key, (r) => html`
        <section class="row">
          <h2>${r.label}</h2>
          <div class="row-scroll">
            ${(r.videos || []).map((video, i) => this._videoCard(r, video, i))}
          </div>
        </section>
      `)}

      <slot name="footer"><builtin-footer></builtin-footer></slot>
    `;
  }
}