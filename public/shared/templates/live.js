/**
 * @fileoverview Live streaming template entry point.
 */

import { BuiltinTplLiveStreamRoom } from "./live/live-stream-room.js";

export { BuiltinTplLiveStreamRoom };

if (!customElements.get("builtin-tpl-live-stream-room")) {
  customElements.define("builtin-tpl-live-stream-room", BuiltinTplLiveStreamRoom);
}
