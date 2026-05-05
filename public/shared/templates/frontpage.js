/**
 * @fileoverview Frontpage template entry point.
 */

import { BuiltinTplFrontpageContent } from "./frontpage/content-home.js";
import { BuiltinTplFrontpageGeneric } from "./frontpage/generic-home.js";
import { BuiltinTplFrontpageSaas } from "./frontpage/saas-home.js";
import { BuiltinTplFrontpageShop } from "./frontpage/shop-home.js";
import { BuiltinTplFrontpageVideo } from "./frontpage/video-home.js";

export {
  BuiltinTplFrontpageContent, BuiltinTplFrontpageGeneric,
  BuiltinTplFrontpageSaas, BuiltinTplFrontpageShop, BuiltinTplFrontpageVideo,
};

const _REGISTRY = [
  ["builtin-tpl-frontpage-content", BuiltinTplFrontpageContent],
  ["builtin-tpl-frontpage-generic", BuiltinTplFrontpageGeneric],
  ["builtin-tpl-frontpage-saas", BuiltinTplFrontpageSaas],
  ["builtin-tpl-frontpage-shop", BuiltinTplFrontpageShop],
  ["builtin-tpl-frontpage-video", BuiltinTplFrontpageVideo],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
