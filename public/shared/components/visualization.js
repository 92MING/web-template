/**
 * @fileoverview Visualization components entry point.
 */

import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinChartWrapper } from "./data/chart-wrapper.js";
import { BuiltinTagCloud } from "./data/tag-cloud.js";
import { BuiltinWordCloud } from "./data/word-cloud.js";
import { BuiltinMermaidDiagram } from "./media/mermaid-diagram.js";
import { BuiltinQrCodeDisplay } from "./media/qr-code-display.js";

export {
  BuiltinChartWrapper, BuiltinIcon, BuiltinMermaidDiagram,
  BuiltinQrCodeDisplay, BuiltinTagCloud, BuiltinWordCloud,
};

const _REGISTRY = [
  ["builtin-chart-wrapper", BuiltinChartWrapper],
  ["builtin-icon", BuiltinIcon],
  ["builtin-mermaid-diagram", BuiltinMermaidDiagram],
  ["builtin-qr-code-display", BuiltinQrCodeDisplay],
  ["builtin-tag-cloud", BuiltinTagCloud],
  ["builtin-word-cloud", BuiltinWordCloud],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}