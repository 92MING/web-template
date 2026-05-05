/**
 * @fileoverview Layout and navigation components entry point.
 *
 * Shell-level building blocks: headers, sidebars, footers, navs, and
 * page-level structural components.
 */

import { BuiltinAppShell } from "./layout/app-shell.js";
import { BuiltinBreadcrumb } from "./layout/breadcrumb.js";
import { BuiltinDraggableTabs } from "./layout/draggable-tabs.js";
import { BuiltinDropdown } from "./layout/dropdown.js";
import { BuiltinFooter } from "./layout/footer.js";
import { BuiltinHeroSection } from "./layout/hero-section.js";
import { BuiltinLangSwitcher } from "./layout/lang-switcher.js";
import { BuiltinLoginPanel } from "./layout/login-panel.js";
import { BuiltinNavbar } from "./layout/navbar.js";
import { BuiltinPageHeader } from "./layout/page-header.js";
import { BuiltinSearchBar } from "./layout/search-bar.js";
import { BuiltinSearchCommandPalette } from "./layout/search-command-palette.js";
import { BuiltinSidebar } from "./layout/sidebar.js";
import { BuiltinUserMenu } from "./layout/user-menu.js";

export {
  BuiltinAppShell, BuiltinBreadcrumb, BuiltinDraggableTabs, BuiltinDropdown, BuiltinFooter, BuiltinHeroSection, BuiltinLangSwitcher, BuiltinLoginPanel, BuiltinNavbar, BuiltinPageHeader, BuiltinSearchBar, BuiltinSearchCommandPalette, BuiltinSidebar, BuiltinUserMenu
};

const _REGISTRY = [
  ["builtin-app-shell", BuiltinAppShell],
  ["builtin-breadcrumb", BuiltinBreadcrumb],
  ["builtin-draggable-tabs", BuiltinDraggableTabs],
  ["builtin-dropdown", BuiltinDropdown],
  ["builtin-footer", BuiltinFooter],
  ["builtin-hero-section", BuiltinHeroSection],
  ["builtin-lang-switcher", BuiltinLangSwitcher],
  ["builtin-login-panel", BuiltinLoginPanel],
  ["builtin-navbar", BuiltinNavbar],
  ["builtin-page-header", BuiltinPageHeader],
  ["builtin-search-bar", BuiltinSearchBar],
  ["builtin-search-command-palette", BuiltinSearchCommandPalette],
  ["builtin-sidebar", BuiltinSidebar],
  ["builtin-user-menu", BuiltinUserMenu],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
