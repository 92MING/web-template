/**
 * @fileoverview Rich media components entry point.
 *
 * Image galleries, video/audio players, PDF viewers, whiteboards,
 * diagrams, and QR code generators.
 */

import { BuiltinAudioEditor } from "./media/audio-editor.js";
import { BuiltinAudioPlayer } from "./media/audio-player.js";
import { BuiltinCarousel } from "./media/carousel.js";
import { BuiltinDocumentPreviewer } from "./media/document-previewer.js";
import { BuiltinImageGallery } from "./media/image-gallery.js";
import { BuiltinMermaidDiagram } from "./media/mermaid-diagram.js";
import { BuiltinQrCodeDisplay } from "./media/qr-code-display.js";
import { BuiltinVideoEditor } from "./media/video-editor.js";
import { BuiltinVideoPlayer } from "./media/video-player.js";
import { BuiltinWhiteboard } from "./media/whiteboard.js";

export {
  BuiltinAudioEditor, BuiltinAudioPlayer, BuiltinCarousel, BuiltinDocumentPreviewer, BuiltinImageGallery, BuiltinMermaidDiagram, BuiltinQrCodeDisplay, BuiltinVideoEditor, BuiltinVideoPlayer, BuiltinWhiteboard
};

const _REGISTRY = [
  ["builtin-audio-editor", BuiltinAudioEditor],
  ["builtin-audio-player", BuiltinAudioPlayer],
  ["builtin-carousel", BuiltinCarousel],
  ["builtin-document-previewer", BuiltinDocumentPreviewer],
  ["builtin-image-gallery", BuiltinImageGallery],
  ["builtin-mermaid-diagram", BuiltinMermaidDiagram],
  ["builtin-qr-code-display", BuiltinQrCodeDisplay],
  ["builtin-video-editor", BuiltinVideoEditor],
  ["builtin-video-player", BuiltinVideoPlayer],
  ["builtin-whiteboard", BuiltinWhiteboard],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
