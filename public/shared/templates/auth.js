/**
 * @fileoverview Auth template entry point.
 */

import { BuiltinTplAuthLogin } from "./auth/login-page.js";

export { BuiltinTplAuthLogin };

if (!customElements.get("builtin-tpl-auth-login")) {
  customElements.define("builtin-tpl-auth-login", BuiltinTplAuthLogin);
}
