/**
 * @fileoverview Shared frontend page templates entry point (Lit-based).
 *
 * Imports all builtin-tpl-* template web components and registers them automatically.
 *
 * Usage:
 *   <script type="module" src="/shared/components.js"></script>
 *   <script type="module" src="/shared/templates.js"></script>
 *   <builtin-tpl-frontpage-generic></builtin-tpl-frontpage-generic>
 */

export { BuiltinTplFrontpageGeneric } from "./templates/frontpage/generic-home.js";
export { BuiltinTplFrontpageContent } from "./templates/frontpage/content-home.js";
export { BuiltinTplFrontpageVideo } from "./templates/frontpage/video-home.js";
export { BuiltinTplFrontpageShop } from "./templates/frontpage/shop-home.js";
export { BuiltinTplFrontpageSaas } from "./templates/frontpage/saas-home.js";

export { BuiltinTplMagazineEditorial } from "./templates/magazine/editorial-layout.js";
export { BuiltinTplMagazineNews } from "./templates/magazine/news-layout.js";

export { BuiltinTplTutorialOnboarding } from "./templates/tutorial/onboarding-guide.js?v=20260429-4";
export { BuiltinTplTutorialDocumentation } from "./templates/tutorial/documentation-layout.js";

export { BuiltinTplFormWizard } from "./templates/form/wizard-form.js";
export { BuiltinTplFormSurvey } from "./templates/form/survey-layout.js";

export { BuiltinTplVideoPlayerPage } from "./templates/video/video-player-page.js";
export { BuiltinTplVideoListing } from "./templates/video/video-listing.js";

export { BuiltinTplEcommerceProductDetail } from "./templates/ecommerce/product-detail.js";
export { BuiltinTplEcommerceProductGrid } from "./templates/ecommerce/product-grid.js";
export { BuiltinTplEcommerceCheckout } from "./templates/ecommerce/checkout-layout.js";
export { BuiltinTplEcommerceCartDrawer } from "./templates/ecommerce/cart-drawer.js";

export { BuiltinTplProfilePersonal } from "./templates/profile/personal-profile.js";
export { BuiltinTplProfilePortfolio } from "./templates/profile/portfolio-layout.js";

export { BuiltinTplChatRoom } from "./templates/chat/chat-room.js?v=20260501-2";
export { BuiltinTplChatMessageThread } from "./templates/chat/message-thread.js?v=20260501-2";

export { BuiltinTplDashboardAnalytics } from "./templates/dashboard/analytics-dashboard.js";
export { BuiltinTplDashboardAdmin } from "./templates/dashboard/admin-dashboard.js";
export { BuiltinTplDashboardWorkspace } from "./templates/dashboard/workspace-home.js";
export { BuiltinTplDashboardMasterDetail } from "./templates/dashboard/master-detail.js";

export { BuiltinTplLandingProductLaunch } from "./templates/landing/product-launch.js";
export { BuiltinTplLandingLeadCapture } from "./templates/landing/lead-capture.js";

export { BuiltinTplAuthLogin } from "./templates/auth/login-page.js";
export { BuiltinTplVideoPlatform } from "./templates/video/video-platform.js";
export { BuiltinTplSocialProfile } from "./templates/social/social-profile.js?v=20260429-4";
export { BuiltinTplCompanyAbout } from "./templates/company/company-about.js";
export { BuiltinTplContactUs } from "./templates/company/contact-us.js";
export { BuiltinTplBlogArticle } from "./templates/blog/blog-article.js";
export { BuiltinTplFileManager } from "./templates/cloud/file-manager.js";
export { BuiltinTplLiveStreamRoom } from "./templates/live/live-stream-room.js";

import { BuiltinTplFrontpageGeneric } from "./templates/frontpage/generic-home.js";
import { BuiltinTplFrontpageContent } from "./templates/frontpage/content-home.js";
import { BuiltinTplFrontpageVideo } from "./templates/frontpage/video-home.js";
import { BuiltinTplFrontpageShop } from "./templates/frontpage/shop-home.js";
import { BuiltinTplFrontpageSaas } from "./templates/frontpage/saas-home.js";

import { BuiltinTplMagazineEditorial } from "./templates/magazine/editorial-layout.js";
import { BuiltinTplMagazineNews } from "./templates/magazine/news-layout.js";

import { BuiltinTplTutorialOnboarding } from "./templates/tutorial/onboarding-guide.js?v=20260429-4";
import { BuiltinTplTutorialDocumentation } from "./templates/tutorial/documentation-layout.js";

import { BuiltinTplFormWizard } from "./templates/form/wizard-form.js";
import { BuiltinTplFormSurvey } from "./templates/form/survey-layout.js";

import { BuiltinTplVideoPlayerPage } from "./templates/video/video-player-page.js";
import { BuiltinTplVideoListing } from "./templates/video/video-listing.js";

import { BuiltinTplEcommerceProductDetail } from "./templates/ecommerce/product-detail.js";
import { BuiltinTplEcommerceProductGrid } from "./templates/ecommerce/product-grid.js";
import { BuiltinTplEcommerceCheckout } from "./templates/ecommerce/checkout-layout.js";
import { BuiltinTplEcommerceCartDrawer } from "./templates/ecommerce/cart-drawer.js";

import { BuiltinTplProfilePersonal } from "./templates/profile/personal-profile.js";
import { BuiltinTplProfilePortfolio } from "./templates/profile/portfolio-layout.js";

import { BuiltinTplChatRoom } from "./templates/chat/chat-room.js?v=20260501-2";
import { BuiltinTplChatMessageThread } from "./templates/chat/message-thread.js?v=20260501-2";

import { BuiltinTplDashboardAnalytics } from "./templates/dashboard/analytics-dashboard.js";
import { BuiltinTplDashboardAdmin } from "./templates/dashboard/admin-dashboard.js";
import { BuiltinTplDashboardWorkspace } from "./templates/dashboard/workspace-home.js";
import { BuiltinTplDashboardMasterDetail } from "./templates/dashboard/master-detail.js";

import { BuiltinTplLandingProductLaunch } from "./templates/landing/product-launch.js";
import { BuiltinTplLandingLeadCapture } from "./templates/landing/lead-capture.js";

import { BuiltinTplAuthLogin } from "./templates/auth/login-page.js";
import { BuiltinTplVideoPlatform } from "./templates/video/video-platform.js";
import { BuiltinTplSocialProfile } from "./templates/social/social-profile.js?v=20260429-4";
import { BuiltinTplCompanyAbout } from "./templates/company/company-about.js";
import { BuiltinTplContactUs } from "./templates/company/contact-us.js";
import { BuiltinTplBlogArticle } from "./templates/blog/blog-article.js";
import { BuiltinTplFileManager } from "./templates/cloud/file-manager.js";
import { BuiltinTplLiveStreamRoom } from "./templates/live/live-stream-room.js";

const TPL_MAP = [
  ["builtin-tpl-frontpage-generic", BuiltinTplFrontpageGeneric],
  ["builtin-tpl-frontpage-content", BuiltinTplFrontpageContent],
  ["builtin-tpl-frontpage-video", BuiltinTplFrontpageVideo],
  ["builtin-tpl-frontpage-shop", BuiltinTplFrontpageShop],
  ["builtin-tpl-frontpage-saas", BuiltinTplFrontpageSaas],
  ["builtin-tpl-magazine-editorial", BuiltinTplMagazineEditorial],
  ["builtin-tpl-magazine-news", BuiltinTplMagazineNews],
  ["builtin-tpl-tutorial-onboarding", BuiltinTplTutorialOnboarding],
  ["builtin-tpl-tutorial-documentation", BuiltinTplTutorialDocumentation],
  ["builtin-tpl-form-wizard", BuiltinTplFormWizard],
  ["builtin-tpl-form-survey", BuiltinTplFormSurvey],
  ["builtin-tpl-video-player", BuiltinTplVideoPlayerPage],
  ["builtin-tpl-video-listing", BuiltinTplVideoListing],
  ["builtin-tpl-ecommerce-product-detail", BuiltinTplEcommerceProductDetail],
  ["builtin-tpl-ecommerce-product-grid", BuiltinTplEcommerceProductGrid],
  ["builtin-tpl-ecommerce-checkout", BuiltinTplEcommerceCheckout],
  ["builtin-tpl-ecommerce-cart-drawer", BuiltinTplEcommerceCartDrawer],
  ["builtin-tpl-profile-personal", BuiltinTplProfilePersonal],
  ["builtin-tpl-profile-portfolio", BuiltinTplProfilePortfolio],
  ["builtin-tpl-chat-room", BuiltinTplChatRoom],
  ["builtin-tpl-chat-message-thread", BuiltinTplChatMessageThread],
  ["builtin-tpl-dashboard-analytics", BuiltinTplDashboardAnalytics],
  ["builtin-tpl-dashboard-admin", BuiltinTplDashboardAdmin],
  ["builtin-tpl-dashboard-workspace", BuiltinTplDashboardWorkspace],
  ["builtin-tpl-dashboard-master-detail", BuiltinTplDashboardMasterDetail],
  ["builtin-tpl-landing-product-launch", BuiltinTplLandingProductLaunch],
  ["builtin-tpl-landing-lead-capture", BuiltinTplLandingLeadCapture],
  ["builtin-tpl-auth-login", BuiltinTplAuthLogin],
  ["builtin-tpl-video-platform", BuiltinTplVideoPlatform],
  ["builtin-tpl-social-profile", BuiltinTplSocialProfile],
  ["builtin-tpl-company-about", BuiltinTplCompanyAbout],
  ["builtin-tpl-contact-us", BuiltinTplContactUs],
  ["builtin-tpl-blog-article", BuiltinTplBlogArticle],
  ["builtin-tpl-file-manager", BuiltinTplFileManager],
  ["builtin-tpl-live-stream-room", BuiltinTplLiveStreamRoom],
];

export function defineSharedTemplates() {
  for (const [tag, Class] of TPL_MAP) {
    if (!customElements.get(tag)) customElements.define(tag, Class);
  }
}

defineSharedTemplates();

globalThis.ProjectSharedTemplates = Object.assign({}, globalThis.ProjectSharedTemplates || {}, {
  defineSharedTemplates,
  BuiltinTplFrontpageGeneric, BuiltinTplFrontpageContent, BuiltinTplFrontpageVideo, BuiltinTplFrontpageShop, BuiltinTplFrontpageSaas,
  BuiltinTplMagazineEditorial, BuiltinTplMagazineNews,
  BuiltinTplTutorialOnboarding, BuiltinTplTutorialDocumentation,
  BuiltinTplFormWizard, BuiltinTplFormSurvey,
  BuiltinTplVideoPlayerPage, BuiltinTplVideoListing,
  BuiltinTplEcommerceProductDetail, BuiltinTplEcommerceProductGrid, BuiltinTplEcommerceCheckout, BuiltinTplEcommerceCartDrawer,
  BuiltinTplProfilePersonal, BuiltinTplProfilePortfolio,
  BuiltinTplChatRoom, BuiltinTplChatMessageThread,
  BuiltinTplDashboardAnalytics, BuiltinTplDashboardAdmin, BuiltinTplDashboardWorkspace, BuiltinTplDashboardMasterDetail,
  BuiltinTplLandingProductLaunch, BuiltinTplLandingLeadCapture,
  BuiltinTplAuthLogin, BuiltinTplVideoPlatform, BuiltinTplSocialProfile, BuiltinTplCompanyAbout, BuiltinTplContactUs,
  BuiltinTplBlogArticle, BuiltinTplFileManager, BuiltinTplLiveStreamRoom,
});
