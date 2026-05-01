import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) { if (!value) return undefined; try { return JSON.parse(value); } catch { return undefined; } },
  toAttribute(value) { return JSON.stringify(value); }
};

/**
 * @fileoverview BuiltinTplLiveStreamRoom — Live streaming room (Twitch/Bilibili style).
 *
 * @attr {string} streamerName — Streamer name.
 * @attr {string} streamerAvatar — Avatar URL.
 * @attr {string} title — Stream title.
 * @attr {string} category — Category.
 * @attr {number} viewers — Viewer count.
 * @attr {string} chatMessages — JSON array of {author, text, color}.
 * @attr {string} products — JSON array of {id, image, title, price} for product bar.
 * @attr {string} labels — JSON i18n overrides.
 */
export class BuiltinTplLiveStreamRoom extends BuiltinBaseElement {
  static properties = {
    streamerName: { type: String },
    streamerAvatar: { type: String },
    title: { type: String },
    category: { type: String },
    viewers: { type: Number },
    chatMessages: { type: Array },
    products: { type: Array },
    labels: { type: Object, converter: jsonConverter },
        _chatInput: { type: String, state: true },
  };

  static styles = css`
    :host { display: block; background: var(--builtin-surface, #ffffff); }
    .layout { display: grid; grid-template-columns: 1fr 320px; gap: 16px; padding: 16px; max-width: 1400px; margin: 0 auto; }
    .video-area { display: flex; flex-direction: column; gap: 12px; }
    .player {
      position: relative; aspect-ratio: 16 / 9; background: #0f0f0f; border-radius: var(--builtin-radius-lg, 8px); overflow: hidden;
      display: flex; align-items: center; justify-content: center;
    }
    .player .live-badge {
      position: absolute; top: 10px; left: 10px; background: #ef4444; color: #fff; font-size: 11px; font-weight: 700;
      padding: 3px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: .05em;
    }
    .player .play-btn {
      width: 64px; height: 64px; border-radius: 50%; background: rgba(255,255,255,0.15); color: #fff;
      border: 2px solid rgba(255,255,255,0.3); display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
    }
    .streamer-row { display: flex; align-items: center; gap: 12px; }
    .streamer-row img { width: 44px; height: 44px; border-radius: 50%; object-fit: cover; }
    .streamer-row .meta { flex: 1; min-width: 0; }
    .streamer-row .n { font-weight: 700; font-size: 15px; color: var(--builtin-color-text, #111827); }
    .streamer-row .c { font-size: 13px; color: var(--builtin-primary, #2563eb); }
    .streamer-row .v { font-size: 12px; color: var(--builtin-color-muted, #6b7280); }
    .actions { display: flex; gap: 8px; }
    .chat {
      border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff); display: flex; flex-direction: column; height: 480px;
    }
    .chat-header { padding: 10px 12px; border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); font-weight: 650; font-size: 14px; }
    .chat-body { flex: 1; overflow-y: auto; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
    .msg { font-size: 13px; line-height: 1.4; }
    .msg .who { font-weight: 600; }
    .chat-input { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .chat-input input { flex: 1; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px); padding: 8px 10px; font: inherit; background: var(--builtin-input-bg, #ffffff); color: var(--builtin-color-text, #111827); }
    .product-bar { display: flex; gap: 10px; overflow-x: auto; padding: 10px 0; scrollbar-width: none; }
    .product-bar::-webkit-scrollbar { display: none; }
    .p-card { min-width: 140px; width: 140px; border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px); overflow: hidden; cursor: pointer; background: var(--builtin-surface, #ffffff); }
    .p-card img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }
    .p-card .t { font-size: 12px; padding: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--builtin-color-text, #111827); }
    .p-card .pr { font-size: 12px; padding: 0 6px 6px; font-weight: 700; color: var(--builtin-primary, #2563eb); }
    @media (max-width: 720px) {
      .layout { grid-template-columns: 1fr; padding: 10px; }
      .chat { height: 320px; }
    }
  `;

  constructor() {
    super();
    this._chatInput = "";
  }

  _defaultChatMessages() {
    return [
      { author: this._l("live.demo.user1", "Alice"), text: this._l("live.demo.msg1", "Great stream today!"), color: "#ef4444" },
      { author: this._l("live.demo.user2", "Bob"), text: this._l("live.demo.msg2", "When is the giveaway?"), color: "#2563eb" },
      { author: this._l("live.demo.user3", "Carol"), text: this._l("live.demo.msg3", "Love the new setup!"), color: "#16a34a" },
    ];
  }

  _defaultProducts() {
    return [
      { id: "demo-1", image: "https://picsum.photos/seed/p1/200/200", title: this._l("live.demo.product1", "Gaming Headset"), price: "$59" },
      { id: "demo-2", image: "https://picsum.photos/seed/p2/200/200", title: this._l("live.demo.product2", "Mechanical Keyboard"), price: "$89" },
      { id: "demo-3", image: "https://picsum.photos/seed/p3/200/200", title: this._l("live.demo.product3", "Streaming Mic"), price: "$129" },
    ];
  }

  _sendChat() {
    const text = (this._chatInput || "").trim();
    if (!text) return;
    this.dispatchEvent(new CustomEvent("builtin-chat-send", { bubbles: true, composed: true, detail: { text } }));
    this._chatInput = "";
  }

  _dispatchFollow() {
    const name = this.streamerName || "";
    this.dispatchEvent(new CustomEvent("builtin-follow", { bubbles: true, composed: true, detail: { name } }));
  }

  _dispatchSubscribe() {
    const name = this.streamerName || "";
    this.dispatchEvent(new CustomEvent("builtin-subscribe", { bubbles: true, composed: true, detail: { name } }));
  }

  _dispatchProductClick(id, title, price) {
    this.dispatchEvent(new CustomEvent("builtin-product-click", { bubbles: true, composed: true, detail: { id, title, price } }));
  }

  render() {
    const msgs = this.chatMessages || (this._defaultChatMessages());
    const prods = this.products || (this._defaultProducts());
    const streamerName = this.streamerName || this._l("live.demo.streamer", "Streamer Name") ;
    const streamerAvatar = this.streamerAvatar || "https://i.pravatar.cc/150?u=live";
    const title = this.title || this._l("live.demo.title", "Stream Title") ;
    const category = this.category || this._l("live.demo.category", "Gaming") ;
    const viewers = this.viewers ?? 1234 ;

    return html`
      <builtin-navbar items='[]'>
        <div slot="brand" style="display:flex;align-items:center;gap:10px;">
          <span style="font-weight:800;font-size:16px;">LiveHub</span>
        </div>
      </builtin-navbar>
      <div class="layout">
        <div class="video-area">
          <div class="player">
            <span class="live-badge">${this._l("live.live", "Live")}</span>
            <button class="play-btn"><builtin-icon name="play-circle" size="32" variant="outlined"></builtin-icon></button>
          </div>
          <div class="streamer-row">
            <img src="${streamerAvatar}" alt="" />
            <div class="meta">
              <div class="n">${streamerName}</div>
              <div class="c">${title}</div>
              <div class="v">${category} · ${viewers} ${this._l("live.viewers", "viewers")}</div>
            </div>
            <div class="actions">
              <button class="builtin-primary" @click="${this._dispatchFollow}">${this._l("live.follow", "Follow")}</button>
              <button @click="${this._dispatchSubscribe}">${this._l("live.subscribe", "Subscribe")}</button>
            </div>
          </div>
          <div>
            <div style="font-size:13px;font-weight:650;color:var(--builtin-color-text);margin-bottom:8px;">${this._l("live.products", "Featured Products")}</div>
            <div class="product-bar">
              ${prods.map((p) => html`
                <div class="p-card" @click="${() => this._dispatchProductClick(p.id, p.title, p.price)}">
                  <img src="${p.image || ''}" alt="" loading="lazy" />
                  <div class="t">${p.title}</div>
                  <div class="pr">${p.price}</div>
                </div>
              `)}
            </div>
          </div>
        </div>
        <div class="chat">
          <div class="chat-header">${this._l("live.chat", "Live Chat")}</div>
          <div class="chat-body">
            ${msgs.map((m) => html`
              <div class="msg"><span class="who" style="color:${m.color || 'var(--builtin-color-text)'};">${m.author}:</span> ${m.text}</div>
            `)}
          </div>
          <div class="chat-input">
            <input type="text" .value="${this._chatInput}" @input="${(e) => this._chatInput = e.target.value}" @keydown="${(e) => { if (e.key === 'Enter') this._sendChat(); }}" placeholder="${this._l("live.saySomething", "Say something...")}" />
            <button class="builtin-primary" @click="${this._sendChat}">${this._l("live.send", "Send")}</button>
          </div>
        </div>
      </div>
    `;
  }
}