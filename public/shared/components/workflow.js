/**
 * @fileoverview Calendar and workflow board components entry point.
 */

import { BuiltinIcon } from "./basic/icon.js";
import { BuiltinBookingCalendar } from "./data/booking-calendar.js";
import { BuiltinCalendar } from "./data/calendar.js";
import { BuiltinFlowDesigner } from "./data/flow-designer.js";
import { BuiltinKanbanBoard } from "./data/kanban-board.js";

export {
  BuiltinBookingCalendar, BuiltinCalendar, BuiltinFlowDesigner,
  BuiltinIcon, BuiltinKanbanBoard,
};

const _REGISTRY = [
  ["builtin-booking-calendar", BuiltinBookingCalendar],
  ["builtin-calendar", BuiltinCalendar],
  ["builtin-flow-designer", BuiltinFlowDesigner],
  ["builtin-icon", BuiltinIcon],
  ["builtin-kanban-board", BuiltinKanbanBoard],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}