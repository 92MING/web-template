/**
 * @fileoverview E-commerce template entry point.
 */

import { BuiltinTplEcommerceCartDrawer } from "./ecommerce/cart-drawer.js";
import { BuiltinTplEcommerceCheckout } from "./ecommerce/checkout-layout.js";
import { BuiltinTplEcommerceProductDetail } from "./ecommerce/product-detail.js";
import { BuiltinTplEcommerceProductGrid } from "./ecommerce/product-grid.js";

export {
  BuiltinTplEcommerceCartDrawer, BuiltinTplEcommerceCheckout,
  BuiltinTplEcommerceProductDetail, BuiltinTplEcommerceProductGrid,
};

const _REGISTRY = [
  ["builtin-tpl-ecommerce-cart-drawer", BuiltinTplEcommerceCartDrawer],
  ["builtin-tpl-ecommerce-checkout", BuiltinTplEcommerceCheckout],
  ["builtin-tpl-ecommerce-product-detail", BuiltinTplEcommerceProductDetail],
  ["builtin-tpl-ecommerce-product-grid", BuiltinTplEcommerceProductGrid],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
