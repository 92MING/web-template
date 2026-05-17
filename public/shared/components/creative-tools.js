/**
 * @fileoverview Creative editing tools entry point.
 */

import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinAudioEditor } from "./media/audio-editor.js";
import { BuiltinVideoEditor } from "./media/video-editor.js";
import { BuiltinWhiteboard } from "./media/whiteboard.js";

export { BuiltinAudioEditor, BuiltinIcon, BuiltinVideoEditor, BuiltinWhiteboard };

const _REGISTRY = [
  ["builtin-audio-editor", BuiltinAudioEditor],
  ["builtin-icon", BuiltinIcon],
  ["builtin-video-editor", BuiltinVideoEditor],
  ["builtin-whiteboard", BuiltinWhiteboard],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}