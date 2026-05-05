/**
 * @fileoverview Data display and editing components entry point.
 *
 * Tables, charts, calendars, spreadsheets, diff viewers, code editors,
 * and other components that visualise or manipulate structured data.
 */

import { BuiltinBookingCalendar } from "./data/booking-calendar.js";
import { BuiltinCalendar } from "./data/calendar.js";
import { BuiltinChartWrapper } from "./data/chart-wrapper.js";
import { BuiltinCodeEditor } from "./data/code-editor.js";
import { BuiltinComparisonTable } from "./data/comparison-table.js";
import { BuiltinDashboardTiles } from "./data/dashboard-tiles.js";
import { BuiltinDataView } from "./data/data-view.js";
import { BuiltinDetailHeader } from "./data/detail-header.js";
import { BuiltinDiffViewer } from "./data/diff-viewer.js";
import { BuiltinFlowDesigner } from "./data/flow-designer.js";
import { BuiltinJsonEditor } from "./data/json-editor.js?v=20260505-17";
import { BuiltinKanbanBoard } from "./data/kanban-board.js";
import { BuiltinMarkdownEditor } from "./data/markdown-editor.js";
import { BuiltinMetadataList } from "./data/metadata-list.js";
import { BuiltinProgressBar } from "./data/progress-bar.js";
import { BuiltinRichTextEditor } from "./data/rich-text-editor.js";
import { BuiltinSpreadsheet } from "./data/spreadsheet.js";
import { BuiltinStatCard } from "./data/stat-card.js";
import { BuiltinTagCloud } from "./data/tag-cloud.js";
import { BuiltinTerminalEmulator } from "./data/terminal-emulator.js";
import { BuiltinTimeline } from "./data/timeline.js";
import { BuiltinTreeView } from "./data/tree-view.js";
import { BuiltinWordCloud } from "./data/word-cloud.js";

export {
  BuiltinBookingCalendar, BuiltinCalendar, BuiltinChartWrapper, BuiltinCodeEditor, BuiltinComparisonTable, BuiltinDashboardTiles, BuiltinDataView, BuiltinDetailHeader, BuiltinDiffViewer, BuiltinFlowDesigner, BuiltinJsonEditor, BuiltinKanbanBoard, BuiltinMarkdownEditor, BuiltinMetadataList, BuiltinProgressBar, BuiltinRichTextEditor, BuiltinSpreadsheet, BuiltinStatCard, BuiltinTagCloud, BuiltinTerminalEmulator, BuiltinTimeline, BuiltinTreeView, BuiltinWordCloud
};

const _REGISTRY = [
  ["builtin-booking-calendar", BuiltinBookingCalendar],
  ["builtin-calendar", BuiltinCalendar],
  ["builtin-chart-wrapper", BuiltinChartWrapper],
  ["builtin-code-editor", BuiltinCodeEditor],
  ["builtin-comparison-table", BuiltinComparisonTable],
  ["builtin-dashboard-tiles", BuiltinDashboardTiles],
  ["builtin-data-view", BuiltinDataView],
  ["builtin-detail-header", BuiltinDetailHeader],
  ["builtin-diff-viewer", BuiltinDiffViewer],
  ["builtin-flow-designer", BuiltinFlowDesigner],
  ["builtin-json-editor", BuiltinJsonEditor],
  ["builtin-kanban-board", BuiltinKanbanBoard],
  ["builtin-markdown-editor", BuiltinMarkdownEditor],
  ["builtin-metadata-list", BuiltinMetadataList],
  ["builtin-progress-bar", BuiltinProgressBar],
  ["builtin-rich-text-editor", BuiltinRichTextEditor],
  ["builtin-spreadsheet", BuiltinSpreadsheet],
  ["builtin-stat-card", BuiltinStatCard],
  ["builtin-tag-cloud", BuiltinTagCloud],
  ["builtin-terminal-emulator", BuiltinTerminalEmulator],
  ["builtin-timeline", BuiltinTimeline],
  ["builtin-tree-view", BuiltinTreeView],
  ["builtin-word-cloud", BuiltinWordCloud],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
