/**
 * @fileoverview Playback components entry point.
 */

import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinAudioPlayer } from "./media/audio-player.js";
import { BuiltinVideoPlayer } from "./media/video-player.js";

export { BuiltinAudioPlayer, BuiltinIcon, BuiltinVideoPlayer };

const _REGISTRY = [
  ["builtin-audio-player", BuiltinAudioPlayer],
  ["builtin-video-player", BuiltinVideoPlayer],
  ["builtin-icon", BuiltinIcon],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}