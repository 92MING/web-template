import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../lit-base.js";

/**
 * @fileoverview Avatar image component with fallback initials and optional status dot.
 *
 * @element builtin-avatar
 *
 * @attr {string} src - Image URL.
 * @attr {string} name - Display name used for fallback initials.
 * @attr {number} size - Size in px. Default 40.
 * @attr {string} status - "online" | "away" | "offline".
 * @attr {string} fallback - "initials" | "icon" | "image". Default "initials".
 */
export class BuiltinAvatar extends BuiltinBaseElement {
  static properties = {
    src: { type: String },
    name: { type: String },
    size: { type: Number },
    status: { type: String },
    fallback: { type: String },
    shape: { type: String },
  };

  static styles = css`
    :host {
      display: inline-block;
    }
    .wrap {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      padding: 2px;
      box-sizing: border-box;
      overflow: visible;
    }
    .avatar-core {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      height: 100%;
      border-radius: inherit;
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      font-weight: 600;
      overflow: hidden;
      user-select: none;
    }
    .shape-rounded { border-radius: var(--builtin-radius, 6px); }
    .shape-square { border-radius: 0; }
    .avatar-core img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .status {
      position: absolute;
      bottom: 0;
      right: 0;
      border-radius: 50%;
      border: 2px solid var(--builtin-surface, #ffffff);
    }
    @media (max-width: 720px) {
      .wrap {
        flex-shrink: 0;
      }
    }
  `;

  constructor() {
    super();
    this.size = 40;
    this.fallback = "initials";
    this.shape = "circle";
  }

  _getInitials() {
    return (this.name || "")
      .split(" ")
      .map((n) => n[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }

  _statusColor() {
    switch (this.status) {
      case "online":
        return "#22c55e";
      case "away":
        return "#f59e0b";
      case "offline":
        return "#9ca3af";
      default:
        return "transparent";
    }
  }

  _onImgError(e) {
    e.target.style.display = "none";
  }

  render() {
    const size = this.size || 40;
    const initials = this._getInitials();
    const statusColor = this._statusColor();
    const showStatus = ["online", "away", "offline"].includes(this.status);
    const statusSize = Math.max(8, Math.round(size / 5));
    const fontSize = Math.max(10, Math.round(size * 0.4));
    const iconSize = Math.round(size * 0.5);

    const showImage = this.src && this.fallback !== "icon" && this.fallback !== "initials";
    const showInitials = !showImage && this.fallback !== "icon" && initials;
    const showIcon = !showImage && this.fallback === "icon";

    const shapeClass = this.shape === "rounded" ? "shape-rounded" : this.shape === "square" ? "shape-square" : "";
    return html`
      <div
        class="wrap ${shapeClass}"
        style="${styleMap({
          width: `${size}px`,
          height: `${size}px`,
          fontSize: `${fontSize}px`,
        })}"
        aria-label="${this.name || ""}"
      >
        <span class="avatar-core">
        ${showImage
          ? html`
              <img
                src="${this.src}"
                alt="${this.name || ""}"
                @error="${this._onImgError}"
              />
            `
          : ""}
        ${showIcon
          ? html`
              <builtin-icon name="user" size="${iconSize}" variant="outlined"></builtin-icon>
            `
          : ""}
        ${showInitials ? initials : ""}
        </span>
        ${showStatus
          ? html`
              <span
                class="status"
                style="${styleMap({
                  width: `${statusSize}px`,
                  height: `${statusSize}px`,
                  background: statusColor,
                })}"
              ></span>
            `
          : ""}
      </div>
    `;
  }
}
