/**
 * @fileoverview Cloud template entry point.
 */

import { BuiltinTplFileManager } from "./cloud/file-manager.js";

export { BuiltinTplFileManager };

if (!customElements.get("builtin-tpl-file-manager")) {
  customElements.define("builtin-tpl-file-manager", BuiltinTplFileManager);
}
