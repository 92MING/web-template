/**
 * @fileoverview Shared frontend page templates entry point (Lit-based).
 *
 * Templates are grouped by scene so pages import only the category they need
 * instead of loading every template at once.
 *
 * ## Category entry points
 *   /shared/templates/auth.js
 *   /shared/templates/blog.js
 *   /shared/templates/chat.js
 *   /shared/templates/cloud.js
 *   /shared/templates/company.js
 *   /shared/templates/dashboard.js
 *   /shared/templates/ecommerce.js
 *   /shared/templates/form.js
 *   /shared/templates/frontpage.js
 *   /shared/templates/landing.js
 *   /shared/templates/live.js
 *   /shared/templates/magazine.js
 *   /shared/templates/profile.js
 *   /shared/templates/social.js
 *   /shared/templates/tutorial.js
 *   /shared/templates/video.js
 *
 * ## Usage
 * Import everything (backward-compatible, loads all categories):
 *   import { BuiltinTplDashboardAnalytics } from "/shared/templates.js";
 *
 * Import only what you need (recommended):
 *   import "/shared/templates/dashboard.js";
 */

export { BuiltinTplAuthLogin } from "./templates/auth.js";
export { BuiltinTplBlogArticle } from "./templates/blog.js";
export { BuiltinTplChatRoom, BuiltinTplChatMessageThread } from "./templates/chat.js";
export { BuiltinTplFileManager } from "./templates/cloud.js";
export { BuiltinTplCompanyAbout, BuiltinTplContactUs } from "./templates/company.js";
export {
  BuiltinTplDashboardAdmin, BuiltinTplDashboardAnalytics,
  BuiltinTplDashboardMasterDetail, BuiltinTplDashboardWorkspace,
} from "./templates/dashboard.js";
export {
  BuiltinTplEcommerceCartDrawer, BuiltinTplEcommerceCheckout,
  BuiltinTplEcommerceProductDetail, BuiltinTplEcommerceProductGrid,
} from "./templates/ecommerce.js";
export { BuiltinTplFormSurvey, BuiltinTplFormWizard } from "./templates/form.js";
export {
  BuiltinTplFrontpageContent, BuiltinTplFrontpageGeneric,
  BuiltinTplFrontpageSaas, BuiltinTplFrontpageShop, BuiltinTplFrontpageVideo,
} from "./templates/frontpage.js";
export { BuiltinTplLandingLeadCapture, BuiltinTplLandingProductLaunch } from "./templates/landing.js";
export { BuiltinTplLiveStreamRoom } from "./templates/live.js";
export { BuiltinTplMagazineEditorial, BuiltinTplMagazineNews } from "./templates/magazine.js";
export { BuiltinTplProfilePersonal, BuiltinTplProfilePortfolio } from "./templates/profile.js";
export { BuiltinTplSocialProfile } from "./templates/social.js";
export { BuiltinTplTutorialDocumentation, BuiltinTplTutorialOnboarding } from "./templates/tutorial.js";
export {
  BuiltinTplVideoListing, BuiltinTplVideoPlatform, BuiltinTplVideoPlayerPage,
} from "./templates/video.js";

// Backward-compat: re-import for the registry helper and global namespace.
import { BuiltinTplAuthLogin } from "./templates/auth.js";
import { BuiltinTplBlogArticle } from "./templates/blog.js";
import { BuiltinTplChatRoom, BuiltinTplChatMessageThread } from "./templates/chat.js";
import { BuiltinTplFileManager } from "./templates/cloud.js";
import { BuiltinTplCompanyAbout, BuiltinTplContactUs } from "./templates/company.js";
import {
  BuiltinTplDashboardAdmin, BuiltinTplDashboardAnalytics,
  BuiltinTplDashboardMasterDetail, BuiltinTplDashboardWorkspace,
} from "./templates/dashboard.js";
import {
  BuiltinTplEcommerceCartDrawer, BuiltinTplEcommerceCheckout,
  BuiltinTplEcommerceProductDetail, BuiltinTplEcommerceProductGrid,
} from "./templates/ecommerce.js";
import { BuiltinTplFormSurvey, BuiltinTplFormWizard } from "./templates/form.js";
import {
  BuiltinTplFrontpageContent, BuiltinTplFrontpageGeneric,
  BuiltinTplFrontpageSaas, BuiltinTplFrontpageShop, BuiltinTplFrontpageVideo,
} from "./templates/frontpage.js";
import { BuiltinTplLandingLeadCapture, BuiltinTplLandingProductLaunch } from "./templates/landing.js";
import { BuiltinTplLiveStreamRoom } from "./templates/live.js";
import { BuiltinTplMagazineEditorial, BuiltinTplMagazineNews } from "./templates/magazine.js";
import { BuiltinTplProfilePersonal, BuiltinTplProfilePortfolio } from "./templates/profile.js";
import { BuiltinTplSocialProfile } from "./templates/social.js";
import { BuiltinTplTutorialDocumentation, BuiltinTplTutorialOnboarding } from "./templates/tutorial.js";
import {
  BuiltinTplVideoListing, BuiltinTplVideoPlatform, BuiltinTplVideoPlayerPage,
} from "./templates/video.js";

const TPL_MAP = [
  ["builtin-tpl-auth-login", BuiltinTplAuthLogin],
  ["builtin-tpl-blog-article", BuiltinTplBlogArticle],
  ["builtin-tpl-chat-room", BuiltinTplChatRoom],
  ["builtin-tpl-chat-message-thread", BuiltinTplChatMessageThread],
  ["builtin-tpl-file-manager", BuiltinTplFileManager],
  ["builtin-tpl-company-about", BuiltinTplCompanyAbout],
  ["builtin-tpl-contact-us", BuiltinTplContactUs],
  ["builtin-tpl-dashboard-admin", BuiltinTplDashboardAdmin],
  ["builtin-tpl-dashboard-analytics", BuiltinTplDashboardAnalytics],
  ["builtin-tpl-dashboard-master-detail", BuiltinTplDashboardMasterDetail],
  ["builtin-tpl-dashboard-workspace", BuiltinTplDashboardWorkspace],
  ["builtin-tpl-ecommerce-cart-drawer", BuiltinTplEcommerceCartDrawer],
  ["builtin-tpl-ecommerce-checkout", BuiltinTplEcommerceCheckout],
  ["builtin-tpl-ecommerce-product-detail", BuiltinTplEcommerceProductDetail],
  ["builtin-tpl-ecommerce-product-grid", BuiltinTplEcommerceProductGrid],
  ["builtin-tpl-form-survey", BuiltinTplFormSurvey],
  ["builtin-tpl-form-wizard", BuiltinTplFormWizard],
  ["builtin-tpl-frontpage-content", BuiltinTplFrontpageContent],
  ["builtin-tpl-frontpage-generic", BuiltinTplFrontpageGeneric],
  ["builtin-tpl-frontpage-saas", BuiltinTplFrontpageSaas],
  ["builtin-tpl-frontpage-shop", BuiltinTplFrontpageShop],
  ["builtin-tpl-frontpage-video", BuiltinTplFrontpageVideo],
  ["builtin-tpl-landing-lead-capture", BuiltinTplLandingLeadCapture],
  ["builtin-tpl-landing-product-launch", BuiltinTplLandingProductLaunch],
  ["builtin-tpl-live-stream-room", BuiltinTplLiveStreamRoom],
  ["builtin-tpl-magazine-editorial", BuiltinTplMagazineEditorial],
  ["builtin-tpl-magazine-news", BuiltinTplMagazineNews],
  ["builtin-tpl-profile-personal", BuiltinTplProfilePersonal],
  ["builtin-tpl-profile-portfolio", BuiltinTplProfilePortfolio],
  ["builtin-tpl-social-profile", BuiltinTplSocialProfile],
  ["builtin-tpl-tutorial-documentation", BuiltinTplTutorialDocumentation],
  ["builtin-tpl-tutorial-onboarding", BuiltinTplTutorialOnboarding],
  ["builtin-tpl-video-listing", BuiltinTplVideoListing],
  ["builtin-tpl-video-platform", BuiltinTplVideoPlatform],
  ["builtin-tpl-video-player", BuiltinTplVideoPlayerPage],
];

export function defineSharedTemplates() {
  for (const [tag, Class] of TPL_MAP) {
    if (!customElements.get(tag)) customElements.define(tag, Class);
  }
}

defineSharedTemplates();

globalThis.ProjectSharedTemplates = Object.assign({}, globalThis.ProjectSharedTemplates || {}, {
  defineSharedTemplates,
  BuiltinTplAuthLogin, BuiltinTplBlogArticle,
  BuiltinTplChatRoom, BuiltinTplChatMessageThread,
  BuiltinTplFileManager, BuiltinTplCompanyAbout, BuiltinTplContactUs,
  BuiltinTplDashboardAdmin, BuiltinTplDashboardAnalytics, BuiltinTplDashboardMasterDetail, BuiltinTplDashboardWorkspace,
  BuiltinTplEcommerceCartDrawer, BuiltinTplEcommerceCheckout, BuiltinTplEcommerceProductDetail, BuiltinTplEcommerceProductGrid,
  BuiltinTplFormSurvey, BuiltinTplFormWizard,
  BuiltinTplFrontpageContent, BuiltinTplFrontpageGeneric, BuiltinTplFrontpageSaas, BuiltinTplFrontpageShop, BuiltinTplFrontpageVideo,
  BuiltinTplLandingLeadCapture, BuiltinTplLandingProductLaunch,
  BuiltinTplLiveStreamRoom,
  BuiltinTplMagazineEditorial, BuiltinTplMagazineNews,
  BuiltinTplProfilePersonal, BuiltinTplProfilePortfolio,
  BuiltinTplSocialProfile,
  BuiltinTplTutorialDocumentation, BuiltinTplTutorialOnboarding,
  BuiltinTplVideoListing, BuiltinTplVideoPlatform, BuiltinTplVideoPlayerPage,
});
