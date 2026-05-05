/**
 * @fileoverview Tutorial / documentation template entry point.
 */

import { BuiltinTplTutorialDocumentation } from "./tutorial/documentation-layout.js";
import { BuiltinTplTutorialOnboarding } from "./tutorial/onboarding-guide.js?v=20260429-4";

export { BuiltinTplTutorialDocumentation, BuiltinTplTutorialOnboarding };

const _REGISTRY = [
  ["builtin-tpl-tutorial-documentation", BuiltinTplTutorialDocumentation],
  ["builtin-tpl-tutorial-onboarding", BuiltinTplTutorialOnboarding],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
