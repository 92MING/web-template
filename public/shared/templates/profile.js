/**
 * @fileoverview Profile template entry point.
 */

import { BuiltinTplProfilePersonal } from "./profile/personal-profile.js";
import { BuiltinTplProfilePortfolio } from "./profile/portfolio-layout.js";

export { BuiltinTplProfilePersonal, BuiltinTplProfilePortfolio };

const _REGISTRY = [
  ["builtin-tpl-profile-personal", BuiltinTplProfilePersonal],
  ["builtin-tpl-profile-portfolio", BuiltinTplProfilePortfolio],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
