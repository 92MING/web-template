import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "./lit-base.js";

/**
 * @fileoverview BuiltinSkeleton — Animated shimmer placeholder for loading states.
 *
 * @element builtin-skeleton
 *
 * @attr {string} shape - "text" | "circle" | "rect" | "card" | "avatar". Default "text".
 * @attr {number} lines - Number of lines for text variant. Default 3.
 * @attr {string} width - CSS width value.
 * @attr {string} height - CSS height value.
 */
export class BuiltinSkeleton extends BuiltinBaseElement {
  static properties = {
    shape: { type: String },
    lines: { type: Number },
    width: { type: String },
    height: { type: String },
  };

  static styles = css`
    :host {
      display: block;
    }
    .wrap {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .shape,
    .line {
      background: linear-gradient(
        90deg,
        var(--builtin-border-soft, #e5e7eb) 25%,
        var(--builtin-header-bg, #f9fafb) 50%,
        var(--builtin-border-soft, #e5e7eb) 75%
      );
      background-size: 200% 100%;
      animation: builtin-shimmer 1.4s infinite linear;
      border-radius: var(--builtin-radius, 6px);
    }
    .line {
      height: 12px;
      width: 100%;
    }
    .shape {
      max-width: 100%;
    }
    @keyframes builtin-shimmer {
      0% {
        background-position: 200% 0;
      }
      100% {
        background-position: -200% 0;
      }
    }
    @media (max-width: 720px) {
      .shape {
        width: 100% !important;
      }
    }
  `;

  constructor() {
    super();
    this.shape = "text";
    this.lines = 3;
  }

  render() {
    const shape = this.shape || "text";
    const lines = Math.max(1, this.lines || 3);
    const width = this.width || "";
    const height = this.height || "";

    if (shape === "text") {
      return html`
        <div class="wrap">
          ${repeat(
            Array.from({ length: lines }),
            (_, i) => i,
            (_, i) => {
              const isLast = i === lines - 1;
              const lineWidth = isLast && lines > 1 ? "75%" : "100%";
              return html`
                <div
                  class="line"
                  style="${styleMap({ width: lineWidth })}"
                ></div>
              `;
            }
          )}
        </div>
      `;
    }

    const shapeStyle = (() => {
      if (shape === "circle" || shape === "avatar") {
        const size = width || height || "40px";
        return { width: size, height: size, borderRadius: "50%" };
      }
      if (shape === "rect") {
        return {
          width: width || "100%",
          height: height || "16px",
          borderRadius: "var(--builtin-radius, 6px)",
        };
      }
      if (shape === "card") {
        return {
          width: width || "100%",
          height: height || "120px",
          borderRadius: "var(--builtin-radius-lg, 8px)",
        };
      }
      return {};
    })();

    return html`
      <div class="wrap">
        <div class="shape" style="${styleMap(shapeStyle)}"></div>
      </div>
    `;
  }
}
