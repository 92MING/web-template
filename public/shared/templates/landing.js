/**
 * @fileoverview Landing page template entry point.
 */

import { BuiltinTplLandingLeadCapture } from "./landing/lead-capture.js";
import { BuiltinTplLandingProductLaunch } from "./landing/product-launch.js";

export { BuiltinTplLandingLeadCapture, BuiltinTplLandingProductLaunch };

const _REGISTRY = [
  ["builtin-tpl-landing-lead-capture", BuiltinTplLandingLeadCapture],
  ["builtin-tpl-landing-product-launch", BuiltinTplLandingProductLaunch],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
