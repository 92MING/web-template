/**
 * @fileoverview Social template entry point.
 */

import { BuiltinTplSocialProfile } from "./social/social-profile.js?v=20260429-4";

export { BuiltinTplSocialProfile };

if (!customElements.get("builtin-tpl-social-profile")) {
  customElements.define("builtin-tpl-social-profile", BuiltinTplSocialProfile);
}
