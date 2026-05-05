/**
 * @fileoverview Utility and developer tool components entry point.
 */

import { BuiltinDragUploadZone } from "./form/drag-upload-zone.js";
import { BuiltinDocumentPreviewer } from "./media/document-previewer.js";
import { BuiltinTerminalEmulator } from "./data/terminal-emulator.js";

export { BuiltinDocumentPreviewer, BuiltinDragUploadZone, BuiltinTerminalEmulator };

const _REGISTRY = [
  ["builtin-document-previewer", BuiltinDocumentPreviewer],
  ["builtin-drag-upload-zone", BuiltinDragUploadZone],
  ["builtin-terminal-emulator", BuiltinTerminalEmulator],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}