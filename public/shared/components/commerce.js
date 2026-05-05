/**
 * @fileoverview E-commerce and business components entry point.
 *
 * Pricing, products, payments, shipping, file browsing, and member management.
 */

import { BuiltinFileBrowser } from "./commerce/file-browser.js";
import { BuiltinFileBrowserCloud } from "./commerce/file-browser-cloud.js";
import { BuiltinMemberManagerDrawer } from "./commerce/member-manager-drawer.js";
import { BuiltinPaymentMethodCard } from "./commerce/payment-method-card.js";
import { BuiltinPricingCard } from "./commerce/pricing-card.js";
import { BuiltinPricingTable } from "./commerce/pricing-table.js";
import { BuiltinProductGrid } from "./commerce/product-grid.js";
import { BuiltinShippingTracker } from "./commerce/shipping-tracker.js";

export {
  BuiltinFileBrowser, BuiltinFileBrowserCloud, BuiltinMemberManagerDrawer,
  BuiltinPaymentMethodCard, BuiltinPricingCard, BuiltinPricingTable,
  BuiltinProductGrid, BuiltinShippingTracker,
};

const _REGISTRY = [
  ["builtin-file-browser", BuiltinFileBrowser],
  ["builtin-file-browser-cloud", BuiltinFileBrowserCloud],
  ["builtin-member-manager-drawer", BuiltinMemberManagerDrawer],
  ["builtin-payment-method-card", BuiltinPaymentMethodCard],
  ["builtin-pricing-card", BuiltinPricingCard],
  ["builtin-pricing-table", BuiltinPricingTable],
  ["builtin-product-grid", BuiltinProductGrid],
  ["builtin-shipping-tracker", BuiltinShippingTracker],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
