/**
 * @fileoverview Company template entry point.
 */

import { BuiltinTplCompanyAbout } from "./company/company-about.js";
import { BuiltinTplContactUs } from "./company/contact-us.js";

export { BuiltinTplCompanyAbout, BuiltinTplContactUs };

const _REGISTRY = [
  ["builtin-tpl-company-about", BuiltinTplCompanyAbout],
  ["builtin-tpl-contact-us", BuiltinTplContactUs],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
