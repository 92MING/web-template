/**
 * @fileoverview Shared frontend web components entry point (Lit-based).
 *
 * Components are split into category entry points so pages can import only
 * what they need instead of loading 130+ components at once.
 *
 * ## Category entry points
 *   /shared/components/core.js        — Theming utilities & helpers
 *   /shared/components/lit-base.js    — Base class & Lit re-exports
 *   /shared/components/focus-trap.js  — Focus-trap helpers
 *   /shared/components/basic.js       — Legacy broad primitives bundle
 *   /shared/components/layout.js      — Legacy broad layout bundle
 *   /shared/components/form.js        — Form inputs, pickers, uploaders, forms
 *   /shared/components/data.js        — Legacy broad data/tools bundle
 *   /shared/components/media.js       — Legacy broad media/tools bundle
 *   /shared/components/social.js      — Legacy broad social bundle
 *   /shared/components/ai.js          — LLM prompt, stream, code-block, chatbot
 *   /shared/components/commerce.js    — Pricing, products, payments
 *
 * ## Fine-grained category entry points
 *   /shared/components/display.js       — Cards, badges, stats, lists, tables
 *   /shared/components/navigation.js    — Tabs, breadcrumbs, menus, search, nav
 *   /shared/components/feedback.js      — Alerts, toasts, modals, notifications
 *   /shared/components/galleries.js     — Image galleries and carousels
 *   /shared/components/players.js       — Audio/video playback controls
 *   /shared/components/visualization.js — Charts, clouds, QR, diagrams
 *   /shared/components/workflow.js      — Calendars, kanban, flow designers
 *   /shared/components/editors.js       — Code, JSON, markdown, rich text editors
 *   /shared/components/creative-tools.js — Audio/video editors, whiteboard, advanced painter
 *   /shared/components/utilities.js     — Upload zones, previewers, terminals
 *   /shared/components/cloud-admin.js   — File browsers, dashboard tiles, members
 *
 * ## Usage
 * Import everything (backward-compatible, loads all categories):
 *   import { BuiltinToast } from "/shared/components.js";
 *
 * Import only what you need (recommended):
 *   import "/shared/components/basic.js";
 *   import "/shared/components/form.js";
 */

export * from "./components/core.js";
export * from "./components/lit-base.js";
export { trapFocus, releaseFocus, FocusTrapMixin } from "./components/focus-trap.js";

export * from "./components/basic.js";
export * from "./components/layout.js";
export * from "./components/form.js";
export * from "./components/data.js";
export * from "./components/media.js";
export * from "./components/social.js";
export * from "./components/ai.js";
export * from "./components/commerce.js";
