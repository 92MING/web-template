# Frontend Shared Components & Templates — Lit Migration & Expansion

## Design System Requirements (ALL components must comply)
1. **Lit-based**: All components extend `BuiltinBaseElement` from `lit-base.js`
2. **Dark mode**: Use CSS variables (`--builtin-*`) + `this._builtinTheme` state. Always support both themes.
3. **i18n**: Use `this._t('key')` for all user-facing strings. Provide `labels` attribute JSON for overrides.
4. **Mobile**: Use `this._builtinMobile` for conditional rendering + `@media (max-width: 720px)` in CSS.
5. **Icons**: Use `this._icon('name', 'outlined')` or inline SVG where appropriate. Leverage `/icons/` (filled/outlined/twotone).
6. **Flexibility**: Provide `mode` / `preset` attributes + slots for overriding default content.
7. **External libs**: Download to `public/vendor/{lib}/` if needed, then wrap in a `builtin-*` component.

---

## Phase A: Migrate Existing Components to Lit (36 files)

### A1 — Layout & Navigation (10 files)
- [ ] `navbar.js` — Add `mode` (default/transparent/centered), mobile hamburger
- [ ] `sidebar.js` — Add `mode` (fixed/overlay/mini), collapsible groups
- [ ] `breadcrumb.js` — Add `separator` attr, mobile scroll
- [ ] `footer.js` — Add `variant` (simple/multi-column/social-heavy)
- [ ] `drawer.js` — Already flexible, ensure Lit + mobile bottom-sheet
- [ ] `card.js` — Add `variant` (default/elevated/bordered/media), hover lift
- [ ] `tabs.js` — Add `type` (pills/underline/vertical), scrollable on mobile
- [ ] `dropdown.js` — Add `trigger` slot, auto-position
- [ ] `search-bar.js` — Add `mode` (simple/expanded/filter), debounce, suggestions
- [ ] `pagination.js` — Add `type` (numbered/simple/load-more), compact on mobile

### A2 — User, Feedback, Auth (10 files)
- [ ] `avatar.js` — Add `fallback` (initials/icon/image), status dot colors
- [ ] `notification-badge.js` — Add `pulse`, `dot-only` mode
- [ ] `user-menu.js` — Add `sections` JSON, sign-out slot
- [ ] `theme-toggle.js` — Sun/moon icons, sync with system preference option
- [ ] `lang-switcher.js` — Add `display` (dropdown/buttons/native-select)
- [ ] `empty-state.js` — Add `preset` (search/error/404/no-access), action slot
- [ ] `skeleton.js` — Add `shape` (text/circle/rect/card/avatar), shimmer animation
- [ ] `modal.js` — Add `animation` (fade/slide/scale), stackable z-index
- [ ] `toast.js` — Add `position` matrix, pause on hover, action button
- [ ] `confirm.js` — Add `type` (info/warning/danger/success), icon support

### A3 — Data & Forms (9 files)
- [ ] `data-view.js` — Keep all features, add `view` (table/grid/cards), mobile card view
- [ ] `schema-form.js` — Add `layout` (vertical/horizontal/compact), field presets
- [ ] `login-panel.js` — **CRITICAL**: Add `mode` (email/phone/qr/oauth). Presets: `email-password`, `phone-otp`, `qr-scan`, `social-only`, `multi-step`. OAuth buttons slot.
- [ ] `file-uploader.js` — Add `mode` (dropzone/list/avatar), image preview, crop hint
- [ ] `contact-form.js` — Add `preset` (simple/full/support), subject dropdown
- [ ] `newsletter.js` — Add `layout` (inline/stacked/hero), success state
- [ ] `filter-bar.js` — Add `mode` (chips/row/drawer), mobile bottom drawer
- [ ] `stepper.js` — Add `direction` (horizontal/vertical), `clickable` flag
- [ ] `cookie-banner.js` — Add `preset` (simple/detailed), preference slots

### A4 — Content & Marketing (7 files)
- [ ] `timeline.js` — Add `align` (left/right/alternate), mobile single-column
- [ ] `stat-card.js` — Add `trend` (up/down/neutral), sparkline slot
- [ ] `hero-section.js` — Add `preset` (centered/split/full-bleed/video-bg), parallax hint
- [ ] `pricing-card.js` — Add `highlight` mode, feature checklist, billing toggle slot
- [ ] `testimonial-card.js` — Add `style` (card/quote/inline), rating display
- [ ] `feature-grid.js` — Add `layout` (3-col/2-col/4-col/icon-list), mobile stack
- [ ] `breadcrumb.js` — Already in A1

---

## Phase B: Migrate Existing Templates to Lit (25 files)

### B1 — Frontpage + Magazine + Tutorial (9 files)
- [ ] `frontpage/generic-home.js` — Use builtin-navbar, builtin-hero-section, builtin-feature-grid, builtin-footer
- [ ] `frontpage/content-home.js` — Use builtin-card grid, builtin-filter-bar
- [ ] `frontpage/video-home.js` — Use builtin-navbar (dark), horizontal scroll rows
- [ ] `frontpage/shop-home.js` — Use builtin-hero-section, product cards, builtin-footer
- [ ] `frontpage/saas-home.js` — Use builtin-stepper, builtin-pricing-card, builtin-feature-grid
- [ ] `magazine/editorial-layout.js` — Two-column text, pull quote, author bio slot
- [ ] `magazine/news-layout.js` — Marquee ticker, headline + sidebar
- [ ] `tutorial/onboarding-guide.js` — Stepper + illustration slots, skip/next/finish
- [ ] `tutorial/documentation-layout.js` — Collapsible TOC, content slot, anchor nav

### B2 — Form + Video + Ecommerce (8 files)
- [ ] `form/wizard-form.js` — Multi-step with builtin-stepper, validation per step
- [ ] `form/survey-layout.js` — Single or paginated questions, progress bar
- [ ] `video/video-player-page.js` — Player area, info, recommended sidebar, comments
- [ ] `video/video-listing.js` — Filter chips, sort, grid cards, pagination
- [ ] `ecommerce/product-detail.js` — Gallery, variants, qty, add-to-cart, tabs
- [ ] `ecommerce/product-grid.js` — Filters sidebar, sort, grid, pagination
- [ ] `ecommerce/checkout-layout.js` — Address + payment + summary, mobile accordion
- [ ] `ecommerce/cart-drawer.js` — Item list, qty stepper, subtotal, checkout CTA

### B3 — Profile + Chat + Dashboard + Landing (8 files)
- [ ] `profile/personal-profile.js` — Cover, avatar, bio, stats, tabs
- [ ] `profile/portfolio-layout.js` — Hero, skills, project grid, contact
- [ ] `chat/chat-room.js` — Conversation list, message thread, input
- [ ] `chat/message-thread.js` — Bubble list, reply, read receipt
- [ ] `dashboard/analytics-dashboard.js` — KPI row, chart placeholder, table, filters
- [ ] `dashboard/admin-dashboard.js` — Sidebar, widget grid, quick actions
- [ ] `landing/product-launch.js` — Countdown, teaser, early-access form
- [ ] `landing/lead-capture.js` — Hero + form, badges, features, testimonials, FAQ

---

## Phase C: New Advanced Components

### C1 — Auth & Social
- [ ] `social-login.js` — Preset buttons: Google, WeChat, GitHub, Apple, Microsoft. Style variants: filled/outlined/icon-only.

### C2 — Editors & Productivity
- [ ] `markdown-editor.js` — Split-pane markdown editor (textarea + marked preview). Toolbar: bold, italic, link, code, list.
- [ ] `rich-text-editor.js` — contenteditable-based WYSIWYG with toolbar. Export HTML.
- [ ] `json-editor.js` — Tree-view JSON editor with add/edit/delete nodes. Import/export.
- [ ] `code-editor.js` — Textarea + highlight.js line numbers + language select.
- [ ] `spreadsheet.js` — HTML table-based spreadsheet with formulas (basic + - * /), xlsx import/export using vendor/xlsx.
- [ ] `whiteboard.js` — Fabric.js wrapper: draw, shapes, text, erase, export image.
- [ ] `flow-designer.js` — SVG-based node editor (simplified ReactFlow): add nodes, connect edges, pan/zoom, export JSON.
- [ ] `kanban-board.js` — Drag-and-drop columns with cards. Add/edit/delete column/card.
- [ ] `calendar.js` — Month/week/day views, events as JSON, click to add/edit.
- [ ] `drag-tiles.js` — Sortable grid of tiles (like Windows start menu). Resize, drag, remove.

### C3 — Media & Visualization
- [ ] `audio-player.js` — Custom audio controls: play/pause, seek, volume, playlist.
- [ ] `video-trimmer.js` — Timeline scrubber with in/out handles, preview frame.
- [ ] `chart-wrapper.js` — Wrapper around vendor/chart (Chart.js) with preset configs.
- [ ] `qr-code-display.js` — Wrapper around vendor/qrcode with logo overlay option.
- [ ] `mermaid-diagram.js` — Wrapper around vendor/mermaid: render diagrams from text.

### C4 — Data & Feedback
- [ ] `data-table.js` — Enhanced table with sorting, filtering, resizing, sticky header.
- [ ] `tree-view.js` — Collapsible tree with checkbox support, drag-and-drop.
- [ ] `color-picker.js` — Hue/saturation box + alpha + hex input + preset palette.
- [ ] `date-picker.js` — Calendar popup for single/range selection.
- [ ] `time-picker.js` — Hours/minutes/seconds selector with AM/PM.
- [ ] `rating.js` — Star/heart/emoji rating with half-steps and hover preview.
- [ ] `slider-range.js` — Dual-handle range slider.
- [ ] `toggle-group.js` — Exclusive or multi-select button group.
- [ ] `command-palette.js` — Spotlight-style search modal with keyboard nav.
- [ ] `infinite-scroll.js` — Wrapper that triggers load-more on scroll.
- [ ] `virtual-list.js` — Render large lists efficiently with viewport slicing.
- [ ] `diff-viewer.js` — Side-by-side or inline diff for text/code.
- [ ] `pdf-viewer.js` — Basic page viewer using pdf.js (if available) or iframe fallback.
- [ ] `terminal-emulator.js` — Styled terminal output with ANSI color support.
- [ ] `heatmap-calendar.js` — GitHub-style contribution heatmap.
- [ ] `org-chart.js` — Hierarchical organization chart with expand/collapse.
- [ ] `mind-map.js` — Radial mind map from nested JSON.
- [ ] `presentation-deck.js` — Simple slide deck with arrow keys + fullscreen.
- [ ] `sticky-notes.js` — Draggable colorful notes on a board.
- [ ] `signature-pad.js` — Canvas-based signature capture with clear/export.
- [ ] `image-comparator.js` — Before/after slider overlay on two images.
- [ ] `progress-timeline.js` — Horizontal progress with milestones and tooltips.
- [ ] `notification-center.js` — Bell icon + dropdown panel with grouped notifications.
- [ ] `activity-feed.js` — Stream of events with icons, timestamps, and actions.
- [ ] `chat-bubble.js` — Single message bubble with variants (text/image/file/reply).
- [ ] `payment-method-card.js` — Credit card visual with number mask, brand detection.
- [ ] `shipping-tracker.js` — Visual timeline of shipment statuses.
- [ ] `booking-calendar.js` — Resource booking grid (rooms/seats) with availability.
- [ ] `file-browser.js` — Tree + grid file manager with breadcrumb, upload, preview.
- [ ] `search-facets.js` — Faceted search panel with counts, multi-select, clear.
- [ ] `comparison-table.js` — Feature comparison with sticky headers, highlight column.
- [ ] `pricing-table.js` — Multi-tier pricing table with toggle (monthly/yearly).
- [ ] `testimonials-carousel.js` — Auto-rotating carousel with dots/arrows.
- [ ] `image-gallery.js` — Masonry or grid gallery with lightbox, lazy load.
- [ ] `video-carousel.js` — Horizontal video thumbnails with play preview.
- [ ] `map-pin-cluster.js` — Map placeholder with clustered pin logic (no map lib required).
- [ ] `weather-widget.js` — Weather card with icon, temp, forecast row.
- [ ] `stock-ticker.js` — Scrolling stock prices with up/down indicators.
- [ ] `countdown-timer.js` — Days/hours/minutes/seconds with circle SVG progress.
- [ ] `poll-widget.js` — Voting bar chart with real-time update animation.
- [ ] `quiz-widget.js` — Single or multi-select quiz with score summary.
- [ ] `resizable-panels.js` — Split pane layout with draggable divider.
- [ ] `breadcrumb-steps.js` — Breadcrumb that doubles as clickable step indicator.
- [ ] `fab-menu.js` — Floating action button with radial child buttons.
- [ ] `bottom-sheet.js` — Mobile-first bottom sheet with snap points.
- [ ] `snackbar-queue.js` — Stacked toast notifications with action buttons.
- [ ] `tooltip-advanced.js` — Smart positioned tooltip with HTML content, delay.
- [ ] `popover-confirm.js` — Inline confirmation popover (delete? yes/no).
- [ ] `form-wizard-steps.js` — Wizard with vertical sidebar + form area.
- [ ] `input-otp.js` — 6-digit OTP input with auto-focus and paste support.
- [ ] `input-credit-card.js` — Card number formatting with brand icon.
- [ ] `input-phone.js` — Country select + phone formatting.
- [ ] `input-tags.js` — Tag input with autocomplete and removable pills.
- [ ] `input-slider.js` — Single value slider with label and output.
- [ ] `input-color.js` — Color input with swatches and picker popup.
- [ ] `input-date-range.js` — Two date pickers with preset ranges.
- [ ] `input-autocomplete.js` — Async autocomplete with highlighting and spinner.
- [ ] `input-rich.js` — Contenteditable single-line rich input (mentions, emojis).
- [ ] `comment-thread.js` — Nested comments with reply, like, edit, delete.
- [ ] `review-rating-breakdown.js` — Histogram of 1-5 star ratings.
- [ ] `product-quick-view.js` — Modal product preview with image carousel and ATC.
- [ ] `cart-summary.js` — Inline cart summary with qty update and remove.
- [ ] `wishlist-button.js` — Heart toggle with animation and counter.
- [ ] `share-buttons.js` — Copy link + social share icons with counts.
- [ ] `newsletter-popup.js` — Delayed or exit-intent popup with email form.
- [ ] `cookie-preferences.js` — Detailed cookie category toggles with save.
- [ ] `gdpr-banner.js` — Region-aware GDPR/CCPA banner with preference link.
- [ ] `age-gate.js` — Age verification overlay with date input or simple confirm.
- [ ] `welcome-tour.js` — Highlighted step tour with overlay and arrow pointers.
- [ ] `feedback-widget.js` — Floating smiley/rating button with comment form.
- [ ] `back-to-top.js` — Appears on scroll, smooth scroll to top.
- [ ] `reading-progress.js` — Thin top bar showing scroll progress.
- [ ] `table-of-contents.js` — Auto-generated TOC from heading tags in slot.
- [ ] `anchor-nav.js` — Sticky side nav highlighting current section.
- [ ] `dark-mode-sync.js` — Syncs with OS preference and persists to localStorage.
- [ ] `locale-formatter.js` — Formats numbers, dates, currency, relative time via Intl.
- [ ] `lazy-image.js` — IntersectionObserver-based lazy loading with blur-up.
- [ ] `responsive-iframe.js` — Aspect-ratio wrapper for embeds (video/maps).
- [ ] `typing-indicator.js` — Animated dots showing someone is typing.
- [ ] `online-status.js` — Badge/dot showing network connectivity.
- [ ] `battery-status.js` — Shows battery level with low-battery warning style.
- [ ] `screen-size-badge.js` — Debug badge showing current breakpoint (dev tool).
- [ ] `version-checker.js` — Checks for new app version and prompts refresh.
- [ ] `service-worker-status.js` — Shows offline/online/cache status.
- [ ] `pwa-install-prompt.js` — Custom install prompt for PWA with instructions.
- [ ] `push-notification-toggle.js` — Browser push permission toggle with fallback.
- [ ] ` geolocation-button.js` — Request location with loading/error/success states.
- [ ] `camera-capture.js` — Camera preview + capture button + gallery strip.
- [ ] `barcode-scanner.js` — Camera-based barcode/QR scanner overlay.
- [ ] `nfc-reader.js` — Web NFC read status indicator (if supported).
- [ ] `bluetooth-device-picker.js` — Web Bluetooth device list and connect button.
- [ ] `usb-device-picker.js` — Web USB device picker UI.
- [ ] `serial-terminal.js` — Web Serial port reader/writer UI.
- [ ] `web-rtc-video.js` — Local + remote video placeholders with mute/hangup.
- [ ] `screen-recorder.js` — Screen recording controls with timer and download.
- [ ] `file-converter.js` — Drag files, select output format, convert (UI only).
- [ ] `print-button.js` — Styled print trigger with preview hint.
- [ ] `export-pdf.js` — Trigger browser print-to-PDF with optimized styles.
- [ ] `scroll-snap-carousel.js` — CSS scroll-snap carousel with dots.
- [ ] `parallax-section.js` — Scroll-driven parallax background layer.
- [ ] `sticky-header.js` — Header that shrinks on scroll with backdrop blur.
- [ ] `mega-menu.js` — Full-width dropdown menu with columns and images.
- [ ] `command-bar.js` — CLI-style command input with history and suggestions.
- [ ] `search-command-palette.js` — Cmd+K palette for navigation and actions.
- [ ] `notification-toast-stack.js` — Corner stack with progress bars and undo.
- [ ] `modal-gallery.js` — Fullscreen image gallery with zoom and thumbnails.
- [ ] `video-conference-grid.js` — Video call grid with dominant speaker layout.
- [ ] `whiteboard-collab.js` — Multi-cursor whiteboard placeholder UI.
- [ ] `document-collab.js` — Presence cursors and avatars overlay for editors.
- [ ] `ai-prompt-input.js` — ChatGPT-style prompt input with submit and stop.
- [ ] `ai-response-stream.js` — Streaming text display with typing effect and copy.
- [ ] `ai-code-block.js` — Code block with syntax highlight, copy, and run buttons.
- [ ] `ai-suggestion-chips.js` — Horizontal scrollable suggestion pills.
- [ ] `ai-thinking-indicator.js` — Animated reasoning steps indicator.
- [ ] `model-selector.js` — Dropdown to select AI model with capability tags.
- [ ] `token-counter.js` — Live token/character count with limit warning.
- [ ] `rag-source-panel.js` — Expandable panel showing retrieved document sources.
- [ ] `confidence-badge.js` — Visual indicator for AI confidence level.
- [ ] `feedback-thumbs.js` — Thumbs up/down with optional comment.
- [ ] `regenerate-button.js` — Retry/regenerate with spinner and history dropdown.

---

## Phase D: Update Entry Files
- [ ] `components.js` — Import and register ALL components (old + new)
- [ ] `templates.js` — Import and register ALL templates
- [ ] Delete deprecated files if any
