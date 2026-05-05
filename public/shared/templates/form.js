/**
 * @fileoverview Form template entry point.
 */

import { BuiltinTplFormSurvey } from "./form/survey-layout.js";
import { BuiltinTplFormWizard } from "./form/wizard-form.js";

export { BuiltinTplFormSurvey, BuiltinTplFormWizard };

const _REGISTRY = [
  ["builtin-tpl-form-survey", BuiltinTplFormSurvey],
  ["builtin-tpl-form-wizard", BuiltinTplFormWizard],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
