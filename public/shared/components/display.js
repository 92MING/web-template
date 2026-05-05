/**
 * @fileoverview Display components entry point.
 */

import { BuiltinAvatar } from "./basic/avatar.js";
import { BuiltinBadge } from "./basic/badge.js";
import { BuiltinCard } from "./basic/card.js";
import { BuiltinChip } from "./basic/chip.js";
import { BuiltinEmptyState } from "./basic/empty-state.js";
import { BuiltinFeatureGrid } from "./basic/feature-grid.js";
import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinSkeleton } from "./basic/skeleton.js";
import { BuiltinDataView } from "./data/data-view.js";
import { BuiltinDetailHeader } from "./data/detail-header.js";
import { BuiltinDiffViewer } from "./data/diff-viewer.js";
import { BuiltinMetadataList } from "./data/metadata-list.js";
import { BuiltinProgressBar } from "./data/progress-bar.js";
import { BuiltinSpreadsheet } from "./data/spreadsheet.js";
import { BuiltinStatCard } from "./data/stat-card.js";
import { BuiltinTimeline } from "./data/timeline.js";
import { BuiltinTreeView } from "./data/tree-view.js";

export {
  BuiltinAvatar, BuiltinBadge, BuiltinCard, BuiltinChip, BuiltinDataView,
  BuiltinDetailHeader, BuiltinDiffViewer, BuiltinEmptyState, BuiltinFeatureGrid,
  BuiltinIcon, BuiltinMetadataList, BuiltinProgressBar, BuiltinSkeleton,
  BuiltinSpreadsheet, BuiltinStatCard, BuiltinTimeline, BuiltinTreeView,
};

const _REGISTRY = [
  ["builtin-avatar", BuiltinAvatar],
  ["builtin-badge", BuiltinBadge],
  ["builtin-card", BuiltinCard],
  ["builtin-chip", BuiltinChip],
  ["builtin-data-view", BuiltinDataView],
  ["builtin-detail-header", BuiltinDetailHeader],
  ["builtin-diff-viewer", BuiltinDiffViewer],
  ["builtin-empty-state", BuiltinEmptyState],
  ["builtin-feature-grid", BuiltinFeatureGrid],
  ["builtin-icon", BuiltinIcon],
  ["builtin-metadata-list", BuiltinMetadataList],
  ["builtin-progress-bar", BuiltinProgressBar],
  ["builtin-skeleton", BuiltinSkeleton],
  ["builtin-spreadsheet", BuiltinSpreadsheet],
  ["builtin-stat-card", BuiltinStatCard],
  ["builtin-timeline", BuiltinTimeline],
  ["builtin-tree-view", BuiltinTreeView],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}