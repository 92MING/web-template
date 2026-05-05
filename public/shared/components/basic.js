/**
 * @fileoverview Basic UI primitive components entry point.
 *
 * Atomic components used by nearly every page: icons, feedback, overlays,
 * navigation helpers, and structural widgets.
 */

import { BuiltinAccordion } from "./basic/accordion.js";
import { BuiltinAdSidebar } from "./basic/ad-sidebar.js";
import { BuiltinAlert } from "./basic/alert.js";
import { BuiltinAvatar } from "./basic/avatar.js";
import { BuiltinBackToTop } from "./basic/back-to-top.js";
import { BuiltinBadge } from "./basic/badge.js";
import { BuiltinCard } from "./basic/card.js";
import { BuiltinChip } from "./basic/chip.js";
import { BuiltinConfirm } from "./basic/confirm.js";
import { BuiltinCookieBanner } from "./basic/cookie-banner.js";
import { BuiltinDrawer } from "./basic/drawer.js";
import { BuiltinEmptyState } from "./basic/empty-state.js";
import { BuiltinFeatureGrid } from "./basic/feature-grid.js";
import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinModal } from "./basic/modal.js";
import { BuiltinPagination } from "./basic/pagination.js";
import { BuiltinRating } from "./basic/rating.js";
import { BuiltinSkeleton } from "./basic/skeleton.js";
import { BuiltinStepper } from "./basic/stepper.js";
import { BuiltinStickyHeader } from "./basic/sticky-header.js";
import { BuiltinTabs } from "./basic/tabs.js";
import { BuiltinTestimonialCard } from "./basic/testimonial-card.js";
import { BuiltinThemeToggle } from "./basic/theme-toggle.js";
import { BuiltinToast } from "./basic/toast.js";
import { BuiltinToggleGroup } from "./basic/toggle-group.js";

export {
  BuiltinAccordion, BuiltinAdSidebar, BuiltinAlert, BuiltinAvatar, BuiltinBackToTop, BuiltinBadge,  BuiltinCard, BuiltinChip, BuiltinConfirm, BuiltinCookieBanner,  BuiltinDrawer, BuiltinEmptyState, BuiltinFeatureGrid,  BuiltinIcon, BuiltinModal, BuiltinPagination,  BuiltinRating, BuiltinSkeleton,  BuiltinStepper, BuiltinStickyHeader, BuiltinTabs,  BuiltinTestimonialCard, BuiltinThemeToggle, BuiltinToast, BuiltinToggleGroup
};

const _REGISTRY = [
  ["builtin-accordion", BuiltinAccordion],
  ["builtin-ad-sidebar", BuiltinAdSidebar],
  ["builtin-alert", BuiltinAlert],
  ["builtin-avatar", BuiltinAvatar],
  ["builtin-back-to-top", BuiltinBackToTop],
  ["builtin-badge", BuiltinBadge],
  ["builtin-card", BuiltinCard],
  ["builtin-chip", BuiltinChip],
  ["builtin-confirm", BuiltinConfirm],
  ["builtin-cookie-banner", BuiltinCookieBanner],
  ["builtin-drawer", BuiltinDrawer],
  ["builtin-empty-state", BuiltinEmptyState],
  ["builtin-feature-grid", BuiltinFeatureGrid],
  ["builtin-icon", BuiltinIcon],
  ["builtin-modal", BuiltinModal],
  ["builtin-pagination", BuiltinPagination],
  ["builtin-rating", BuiltinRating],
  ["builtin-skeleton", BuiltinSkeleton],
  ["builtin-stepper", BuiltinStepper],
  ["builtin-sticky-header", BuiltinStickyHeader],
  ["builtin-tabs", BuiltinTabs],
  ["builtin-testimonial-card", BuiltinTestimonialCard],
  ["builtin-theme-toggle", BuiltinThemeToggle],
  ["builtin-toast", BuiltinToast],
  ["builtin-toggle-group", BuiltinToggleGroup],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
