/**
 * @fileoverview Feedback and overlay components entry point.
 */

import { BuiltinAlert } from "./basic/alert.js";
import { BuiltinConfirm } from "./basic/confirm.js";
import { BuiltinCookieBanner } from "./basic/cookie-banner.js";
import { BuiltinDrawer } from "./basic/drawer.js";
import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinModal } from "./basic/modal.js";
import { BuiltinToast } from "./basic/toast.js";
import { BuiltinNotificationBadge } from "./social/notification-badge.js";
import { BuiltinNotificationCenter } from "./social/notification-center.js";

export {
  BuiltinAlert, BuiltinConfirm, BuiltinCookieBanner, BuiltinDrawer,
  BuiltinIcon, BuiltinModal, BuiltinNotificationBadge,
  BuiltinNotificationCenter, BuiltinToast,
};

const _REGISTRY = [
  ["builtin-alert", BuiltinAlert],
  ["builtin-confirm", BuiltinConfirm],
  ["builtin-cookie-banner", BuiltinCookieBanner],
  ["builtin-drawer", BuiltinDrawer],
  ["builtin-icon", BuiltinIcon],
  ["builtin-modal", BuiltinModal],
  ["builtin-notification-badge", BuiltinNotificationBadge],
  ["builtin-notification-center", BuiltinNotificationCenter],
  ["builtin-toast", BuiltinToast],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}