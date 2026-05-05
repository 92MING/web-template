/**
 * @fileoverview Gallery and carousel components entry point.
 */

import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinCarousel } from "./media/carousel.js";
import { BuiltinImageGallery } from "./media/image-gallery.js";

export { BuiltinCarousel, BuiltinIcon, BuiltinImageGallery };

const _REGISTRY = [
  ["builtin-carousel", BuiltinCarousel],
  ["builtin-icon", BuiltinIcon],
  ["builtin-image-gallery", BuiltinImageGallery],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}