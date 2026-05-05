/**
 * @fileoverview Cloud, admin, and workspace management components entry point.
 */

import { BuiltinDashboardTiles } from "./data/dashboard-tiles.js";
import { BuiltinDraggableTabs } from "./layout/draggable-tabs.js";
import { BuiltinFileBrowser } from "./commerce/file-browser.js";
import { BuiltinFileBrowserCloud } from "./commerce/file-browser-cloud.js";
import { BuiltinMemberManagerDrawer } from "./commerce/member-manager-drawer.js";

export {
  BuiltinDashboardTiles, BuiltinDraggableTabs, BuiltinFileBrowser,
  BuiltinFileBrowserCloud, BuiltinMemberManagerDrawer,
};

const _REGISTRY = [
  ["builtin-dashboard-tiles", BuiltinDashboardTiles],
  ["builtin-draggable-tabs", BuiltinDraggableTabs],
  ["builtin-file-browser", BuiltinFileBrowser],
  ["builtin-file-browser-cloud", BuiltinFileBrowserCloud],
  ["builtin-member-manager-drawer", BuiltinMemberManagerDrawer],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}