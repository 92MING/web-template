/**
 * @fileoverview Magazine template entry point.
 */

import { BuiltinTplMagazineEditorial } from "./magazine/editorial-layout.js";
import { BuiltinTplMagazineNews } from "./magazine/news-layout.js";

export { BuiltinTplMagazineEditorial, BuiltinTplMagazineNews };

const _REGISTRY = [
  ["builtin-tpl-magazine-editorial", BuiltinTplMagazineEditorial],
  ["builtin-tpl-magazine-news", BuiltinTplMagazineNews],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
