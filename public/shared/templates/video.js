/**
 * @fileoverview Video platform template entry point.
 */

import { BuiltinTplVideoListing } from "./video/video-listing.js";
import { BuiltinTplVideoPlatform } from "./video/video-platform.js";
import { BuiltinTplVideoPlayerPage } from "./video/video-player-page.js";

export {
  BuiltinTplVideoListing, BuiltinTplVideoPlatform, BuiltinTplVideoPlayerPage,
};

const _REGISTRY = [
  ["builtin-tpl-video-listing", BuiltinTplVideoListing],
  ["builtin-tpl-video-platform", BuiltinTplVideoPlatform],
  ["builtin-tpl-video-player", BuiltinTplVideoPlayerPage],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
