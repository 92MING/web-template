/**
 * @fileoverview Shared frontend web components entry point (Lit-based).
 *
 * Eagerly imports every builtin-* component class and registers it with
 * `customElements.define`. Pages can use `<builtin-xxx>` tags directly,
 * and synchronous inline `<script type="module">` blocks following the
 * components.js script tag will see all elements pre-defined.
 *
 * Re-exports each class by name so call sites can:
 *   import { BuiltinToast, BuiltinConfirm } from "/shared/components.js";
 */

export * from "./components/core.js";
export * from "./components/lit-base.js";

import { BuiltinAccordion } from "./components/accordion.js";
import { BuiltinActivityFeed } from "./components/activity-feed.js";
import { BuiltinAdSidebar } from "./components/ad-sidebar.js";
import { BuiltinAiCodeBlock } from "./components/ai-code-block.js";
import { BuiltinAiPromptInput } from "./components/ai-prompt-input.js";
import { BuiltinAiResponseStream } from "./components/ai-response-stream.js";
import { BuiltinAiSuggestionChips } from "./components/ai-suggestion-chips.js";
import { BuiltinAlert } from "./components/alert.js";
import { BuiltinAppShell } from "./components/app-shell.js";
import { BuiltinAudioEditor } from "./components/audio-editor.js";
import { BuiltinAudioPlayer } from "./components/audio-player.js?v=20260501-2";
import { BuiltinAvatar } from "./components/avatar.js";
import { BuiltinBackToTop } from "./components/back-to-top.js";
import { BuiltinBadge } from "./components/badge.js";
import { BuiltinBookingCalendar } from "./components/booking-calendar.js";
import { BuiltinBreadcrumb } from "./components/breadcrumb.js";
import { BuiltinCalendar } from "./components/calendar.js";
import { BuiltinCard } from "./components/card.js";
import { BuiltinCarousel } from "./components/carousel.js";
import { BuiltinChartWrapper } from "./components/chart-wrapper.js";
import { BuiltinChip } from "./components/chip.js";
import { BuiltinCodeEditor } from "./components/code-editor.js";
import { BuiltinColorPicker } from "./components/color-picker.js";
import { BuiltinCommandPalette } from "./components/command-palette.js";
import { BuiltinCommentSection } from "./components/comment-section.js";
import { BuiltinComparisonTable } from "./components/comparison-table.js";
import { BuiltinConfirm } from "./components/confirm.js";
import { BuiltinContactForm } from "./components/contact-form.js";
import { BuiltinCookieBanner } from "./components/cookie-banner.js";
import { BuiltinDanmaku } from "./components/danmaku.js";
import { BuiltinDashboardTiles } from "./components/dashboard-tiles.js";
import { BuiltinDataView } from "./components/data-view.js";
import { BuiltinDatePicker } from "./components/date-picker.js";
import { BuiltinDetailHeader } from "./components/detail-header.js";
import { BuiltinDiffViewer } from "./components/diff-viewer.js";
import { BuiltinDocumentPreviewer } from "./components/document-previewer.js";
import { BuiltinDragTiles } from "./components/drag-tiles.js";
import { BuiltinDragUploadZone } from "./components/drag-upload-zone.js";
import { BuiltinDraggableTabs } from "./components/draggable-tabs.js";
import { BuiltinDrawer } from "./components/drawer.js";
import { BuiltinDropdown } from "./components/dropdown.js";
import { BuiltinEmptyState } from "./components/empty-state.js";
import { BuiltinFeatureGrid } from "./components/feature-grid.js";
import { BuiltinFileBrowser } from "./components/file-browser.js";
import { BuiltinFileBrowserCloud } from "./components/file-browser-cloud.js";
import { BuiltinFileUploader } from "./components/file-uploader.js";
import { BuiltinFilterBar } from "./components/filter-bar.js";
import { BuiltinFlowDesigner } from "./components/flow-designer.js";
import { BuiltinFooter } from "./components/footer.js";
import { BuiltinHeroSection } from "./components/hero-section.js";
import { BuiltinIcon } from "./components/icon.js";
import { BuiltinImageGallery } from "./components/image-gallery.js";
import { BuiltinInputCreditCard } from "./components/input-credit-card.js";
import { BuiltinInputOtp } from "./components/input-otp.js";
import { BuiltinInputTags } from "./components/input-tags.js";
import { BuiltinJsonEditor } from "./components/json-editor.js";
import { BuiltinKanbanBoard } from "./components/kanban-board.js";
import { BuiltinLangSwitcher } from "./components/lang-switcher.js";
import { BuiltinLoginPanel } from "./components/login-panel.js";
import { BuiltinMarkdownEditor } from "./components/markdown-editor.js";
import { BuiltinMemberManagerDrawer } from "./components/member-manager-drawer.js";
import { BuiltinMermaidDiagram } from "./components/mermaid-diagram.js";
import { BuiltinMetadataList } from "./components/metadata-list.js";
import { BuiltinModal } from "./components/modal.js";
import { BuiltinNavbar } from "./components/navbar.js";
import { BuiltinNewsletter } from "./components/newsletter.js";
import { BuiltinNotificationBadge } from "./components/notification-badge.js";
import { BuiltinNotificationCenter } from "./components/notification-center.js";
import { BuiltinPageHeader } from "./components/page-header.js";
import { BuiltinPagination } from "./components/pagination.js";
import { BuiltinPaymentMethodCard } from "./components/payment-method-card.js";
import { BuiltinPricingCard } from "./components/pricing-card.js";
import { BuiltinPricingTable } from "./components/pricing-table.js";
import { BuiltinProductGrid } from "./components/product-grid.js";
import { BuiltinProgressBar } from "./components/progress-bar.js";
import { BuiltinQrCodeDisplay } from "./components/qr-code-display.js";
import { BuiltinRating } from "./components/rating.js";
import { BuiltinRichTextEditor } from "./components/rich-text-editor.js";
import { BuiltinSchemaForm } from "./components/schema-form.js";
import { BuiltinScrollSnapCarousel } from "./components/scroll-snap-carousel.js";
import { BuiltinSearchBar } from "./components/search-bar.js";
import { BuiltinSearchCommandPalette } from "./components/search-command-palette.js";
import { BuiltinShippingTracker } from "./components/shipping-tracker.js";
import { BuiltinSidebar } from "./components/sidebar.js";
import { BuiltinSkeleton } from "./components/skeleton.js";
import { BuiltinSliderRange } from "./components/slider-range.js";
import { BuiltinSocialBlogCard } from "./components/social-blog-card.js";
import { BuiltinSocialLogin } from "./components/social-login.js";
import { BuiltinSpreadsheet } from "./components/spreadsheet.js";
import { BuiltinStatCard } from "./components/stat-card.js";
import { BuiltinStepper } from "./components/stepper.js";
import { BuiltinStickyHeader } from "./components/sticky-header.js";
import { BuiltinTabs } from "./components/tabs.js";
import { BuiltinTagCloud } from "./components/tag-cloud.js";
import { BuiltinTestimonialCard } from "./components/testimonial-card.js";
import { BuiltinTestimonialsCarousel } from "./components/testimonials-carousel.js";
import { BuiltinThemeToggle } from "./components/theme-toggle.js";
import { BuiltinTimePicker } from "./components/time-picker.js";
import { BuiltinTimeline } from "./components/timeline.js";
import { BuiltinToast } from "./components/toast.js";
import { BuiltinToggleGroup } from "./components/toggle-group.js";
import { BuiltinTreeView } from "./components/tree-view.js";
import { BuiltinUserMenu } from "./components/user-menu.js";
import { BuiltinVideoEditor } from "./components/video-editor.js";
import { BuiltinWhiteboard } from "./components/whiteboard.js";
import { BuiltinWordCloud } from "./components/word-cloud.js";

export {
  BuiltinAccordion, BuiltinActivityFeed, BuiltinAdSidebar, BuiltinAiCodeBlock,
  BuiltinAiPromptInput, BuiltinAiResponseStream, BuiltinAiSuggestionChips,
  BuiltinAlert, BuiltinAppShell, BuiltinAudioEditor, BuiltinAudioPlayer,
  BuiltinAvatar, BuiltinBackToTop, BuiltinBadge, BuiltinBookingCalendar,
  BuiltinBreadcrumb, BuiltinCalendar, BuiltinCard, BuiltinCarousel,
  BuiltinChartWrapper, BuiltinChip, BuiltinCodeEditor, BuiltinColorPicker,
  BuiltinCommandPalette, BuiltinCommentSection, BuiltinComparisonTable,
  BuiltinConfirm, BuiltinContactForm, BuiltinCookieBanner, BuiltinDanmaku,
  BuiltinDashboardTiles, BuiltinDataView, BuiltinDatePicker, BuiltinDetailHeader,
  BuiltinDiffViewer, BuiltinDocumentPreviewer, BuiltinDragTiles,
  BuiltinDragUploadZone, BuiltinDraggableTabs, BuiltinDrawer, BuiltinDropdown,
  BuiltinEmptyState, BuiltinFeatureGrid, BuiltinFileBrowser,
  BuiltinFileBrowserCloud, BuiltinFileUploader, BuiltinFilterBar,
  BuiltinFlowDesigner, BuiltinFooter, BuiltinHeroSection, BuiltinIcon,
  BuiltinImageGallery, BuiltinInputCreditCard, BuiltinInputOtp,
  BuiltinInputTags, BuiltinJsonEditor, BuiltinKanbanBoard, BuiltinLangSwitcher,
  BuiltinLoginPanel, BuiltinMarkdownEditor, BuiltinMemberManagerDrawer,
  BuiltinMermaidDiagram, BuiltinMetadataList, BuiltinModal, BuiltinNavbar,
  BuiltinNewsletter, BuiltinNotificationBadge, BuiltinNotificationCenter,
  BuiltinPageHeader, BuiltinPagination, BuiltinPaymentMethodCard,
  BuiltinPricingCard, BuiltinPricingTable, BuiltinProductGrid,
  BuiltinProgressBar, BuiltinQrCodeDisplay, BuiltinRating,
  BuiltinRichTextEditor, BuiltinSchemaForm, BuiltinScrollSnapCarousel,
  BuiltinSearchBar, BuiltinSearchCommandPalette, BuiltinShippingTracker,
  BuiltinSidebar, BuiltinSkeleton, BuiltinSliderRange, BuiltinSocialBlogCard,
  BuiltinSocialLogin, BuiltinSpreadsheet, BuiltinStatCard, BuiltinStepper,
  BuiltinStickyHeader, BuiltinTabs, BuiltinTagCloud, BuiltinTestimonialCard,
  BuiltinTestimonialsCarousel, BuiltinThemeToggle, BuiltinTimePicker,
  BuiltinTimeline, BuiltinToast, BuiltinToggleGroup, BuiltinTreeView,
  BuiltinUserMenu, BuiltinVideoEditor, BuiltinWhiteboard,
  BuiltinWordCloud,
};

const _REGISTRY = [
  ["builtin-accordion", BuiltinAccordion],
  ["builtin-activity-feed", BuiltinActivityFeed],
  ["builtin-ad-sidebar", BuiltinAdSidebar],
  ["builtin-ai-code-block", BuiltinAiCodeBlock],
  ["builtin-ai-prompt-input", BuiltinAiPromptInput],
  ["builtin-ai-response-stream", BuiltinAiResponseStream],
  ["builtin-ai-suggestion-chips", BuiltinAiSuggestionChips],
  ["builtin-alert", BuiltinAlert],
  ["builtin-app-shell", BuiltinAppShell],
  ["builtin-audio-editor", BuiltinAudioEditor],
  ["builtin-audio-player", BuiltinAudioPlayer],
  ["builtin-avatar", BuiltinAvatar],
  ["builtin-back-to-top", BuiltinBackToTop],
  ["builtin-badge", BuiltinBadge],
  ["builtin-booking-calendar", BuiltinBookingCalendar],
  ["builtin-breadcrumb", BuiltinBreadcrumb],
  ["builtin-calendar", BuiltinCalendar],
  ["builtin-card", BuiltinCard],
  ["builtin-carousel", BuiltinCarousel],
  ["builtin-chart-wrapper", BuiltinChartWrapper],
  ["builtin-chip", BuiltinChip],
  ["builtin-code-editor", BuiltinCodeEditor],
  ["builtin-color-picker", BuiltinColorPicker],
  ["builtin-command-palette", BuiltinCommandPalette],
  ["builtin-comment-section", BuiltinCommentSection],
  ["builtin-comparison-table", BuiltinComparisonTable],
  ["builtin-confirm", BuiltinConfirm],
  ["builtin-contact-form", BuiltinContactForm],
  ["builtin-cookie-banner", BuiltinCookieBanner],
  ["builtin-danmaku", BuiltinDanmaku],
  ["builtin-dashboard-tiles", BuiltinDashboardTiles],
  ["builtin-data-view", BuiltinDataView],
  ["builtin-date-picker", BuiltinDatePicker],
  ["builtin-detail-header", BuiltinDetailHeader],
  ["builtin-diff-viewer", BuiltinDiffViewer],
  ["builtin-document-previewer", BuiltinDocumentPreviewer],
  ["builtin-drag-tiles", BuiltinDragTiles],
  ["builtin-drag-upload-zone", BuiltinDragUploadZone],
  ["builtin-draggable-tabs", BuiltinDraggableTabs],
  ["builtin-drawer", BuiltinDrawer],
  ["builtin-dropdown", BuiltinDropdown],
  ["builtin-empty-state", BuiltinEmptyState],
  ["builtin-feature-grid", BuiltinFeatureGrid],
  ["builtin-file-browser", BuiltinFileBrowser],
  ["builtin-file-browser-cloud", BuiltinFileBrowserCloud],
  ["builtin-file-uploader", BuiltinFileUploader],
  ["builtin-filter-bar", BuiltinFilterBar],
  ["builtin-flow-designer", BuiltinFlowDesigner],
  ["builtin-footer", BuiltinFooter],
  ["builtin-hero-section", BuiltinHeroSection],
  ["builtin-icon", BuiltinIcon],
  ["builtin-image-gallery", BuiltinImageGallery],
  ["builtin-input-credit-card", BuiltinInputCreditCard],
  ["builtin-input-otp", BuiltinInputOtp],
  ["builtin-input-tags", BuiltinInputTags],
  ["builtin-json-editor", BuiltinJsonEditor],
  ["builtin-kanban-board", BuiltinKanbanBoard],
  ["builtin-lang-switcher", BuiltinLangSwitcher],
  ["builtin-login-panel", BuiltinLoginPanel],
  ["builtin-markdown-editor", BuiltinMarkdownEditor],
  ["builtin-member-manager-drawer", BuiltinMemberManagerDrawer],
  ["builtin-mermaid-diagram", BuiltinMermaidDiagram],
  ["builtin-metadata-list", BuiltinMetadataList],
  ["builtin-modal", BuiltinModal],
  ["builtin-navbar", BuiltinNavbar],
  ["builtin-newsletter", BuiltinNewsletter],
  ["builtin-notification-badge", BuiltinNotificationBadge],
  ["builtin-notification-center", BuiltinNotificationCenter],
  ["builtin-page-header", BuiltinPageHeader],
  ["builtin-pagination", BuiltinPagination],
  ["builtin-payment-method-card", BuiltinPaymentMethodCard],
  ["builtin-pricing-card", BuiltinPricingCard],
  ["builtin-pricing-table", BuiltinPricingTable],
  ["builtin-product-grid", BuiltinProductGrid],
  ["builtin-progress-bar", BuiltinProgressBar],
  ["builtin-qr-code-display", BuiltinQrCodeDisplay],
  ["builtin-rating", BuiltinRating],
  ["builtin-rich-text-editor", BuiltinRichTextEditor],
  ["builtin-schema-form", BuiltinSchemaForm],
  ["builtin-scroll-snap-carousel", BuiltinScrollSnapCarousel],
  ["builtin-search-bar", BuiltinSearchBar],
  ["builtin-search-command-palette", BuiltinSearchCommandPalette],
  ["builtin-shipping-tracker", BuiltinShippingTracker],
  ["builtin-sidebar", BuiltinSidebar],
  ["builtin-skeleton", BuiltinSkeleton],
  ["builtin-slider-range", BuiltinSliderRange],
  ["builtin-social-blog-card", BuiltinSocialBlogCard],
  ["builtin-social-login", BuiltinSocialLogin],
  ["builtin-spreadsheet", BuiltinSpreadsheet],
  ["builtin-stat-card", BuiltinStatCard],
  ["builtin-stepper", BuiltinStepper],
  ["builtin-sticky-header", BuiltinStickyHeader],
  ["builtin-tabs", BuiltinTabs],
  ["builtin-tag-cloud", BuiltinTagCloud],
  ["builtin-testimonial-card", BuiltinTestimonialCard],
  ["builtin-testimonials-carousel", BuiltinTestimonialsCarousel],
  ["builtin-theme-toggle", BuiltinThemeToggle],
  ["builtin-time-picker", BuiltinTimePicker],
  ["builtin-timeline", BuiltinTimeline],
  ["builtin-toast", BuiltinToast],
  ["builtin-toggle-group", BuiltinToggleGroup],
  ["builtin-tree-view", BuiltinTreeView],
  ["builtin-user-menu", BuiltinUserMenu],
  ["builtin-video-editor", BuiltinVideoEditor],
  ["builtin-whiteboard", BuiltinWhiteboard],
  ["builtin-word-cloud", BuiltinWordCloud],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
