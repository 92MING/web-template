/**
 * @fileoverview Dashboard template entry point.
 */

import { BuiltinTplDashboardAdmin } from "./dashboard/admin-dashboard.js";
import { BuiltinTplDashboardAnalytics } from "./dashboard/analytics-dashboard.js";
import { BuiltinTplDashboardMasterDetail } from "./dashboard/master-detail.js";
import { BuiltinTplDashboardWorkspace } from "./dashboard/workspace-home.js";

export {
  BuiltinTplDashboardAdmin, BuiltinTplDashboardAnalytics,
  BuiltinTplDashboardMasterDetail, BuiltinTplDashboardWorkspace,
};

const _REGISTRY = [
  ["builtin-tpl-dashboard-admin", BuiltinTplDashboardAdmin],
  ["builtin-tpl-dashboard-analytics", BuiltinTplDashboardAnalytics],
  ["builtin-tpl-dashboard-master-detail", BuiltinTplDashboardMasterDetail],
  ["builtin-tpl-dashboard-workspace", BuiltinTplDashboardWorkspace],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
