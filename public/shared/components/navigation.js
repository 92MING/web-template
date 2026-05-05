/**
 * @fileoverview Navigation components entry point.
 */

import { BuiltinAccordion } from "./basic/accordion.js";
import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinPagination } from "./basic/pagination.js";
import { BuiltinStepper } from "./basic/stepper.js";
import { BuiltinTabs } from "./basic/tabs.js";
import { BuiltinThemeToggle } from "./basic/theme-toggle.js";
import { BuiltinBreadcrumb } from "./layout/breadcrumb.js";
import { BuiltinDropdown } from "./layout/dropdown.js";
import { BuiltinLangSwitcher } from "./layout/lang-switcher.js";
import { BuiltinNavbar } from "./layout/navbar.js";
import { BuiltinSearchBar } from "./layout/search-bar.js";
import { BuiltinSearchCommandPalette } from "./layout/search-command-palette.js";
import { BuiltinSidebar } from "./layout/sidebar.js";
import { BuiltinUserMenu } from "./layout/user-menu.js";

export {
  BuiltinAccordion, BuiltinBreadcrumb, BuiltinDropdown, BuiltinIcon,
  BuiltinLangSwitcher, BuiltinNavbar, BuiltinPagination, BuiltinSearchBar,
  BuiltinSearchCommandPalette, BuiltinSidebar, BuiltinStepper, BuiltinTabs,
  BuiltinThemeToggle, BuiltinUserMenu,
};

const _REGISTRY = [
  ["builtin-accordion", BuiltinAccordion],
  ["builtin-breadcrumb", BuiltinBreadcrumb],
  ["builtin-dropdown", BuiltinDropdown],
  ["builtin-icon", BuiltinIcon],
  ["builtin-lang-switcher", BuiltinLangSwitcher],
  ["builtin-navbar", BuiltinNavbar],
  ["builtin-pagination", BuiltinPagination],
  ["builtin-search-bar", BuiltinSearchBar],
  ["builtin-search-command-palette", BuiltinSearchCommandPalette],
  ["builtin-sidebar", BuiltinSidebar],
  ["builtin-stepper", BuiltinStepper],
  ["builtin-tabs", BuiltinTabs],
  ["builtin-theme-toggle", BuiltinThemeToggle],
  ["builtin-user-menu", BuiltinUserMenu],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}