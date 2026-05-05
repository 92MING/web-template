/**
 * Gallery shell: persistent top bar (brand + nav + theme + language + random)
 * shared across the components index page and every live template page.
 *
 * Public surface:
 *  - default initialization on DOMContentLoaded
 *  - getGalleryLang(), setGalleryLang(lang)
 *  - mountGalleryPreviewFrame(host, contentNode, options)  (used by index.html)
 */

import { setSharedTheme, getSharedTheme } from "/shared/components/core.js";
import { setI18nCatalog } from "/shared/components/lit-base.js";

// ---------------------------------------------------------------------------
// Constants

const LANG_KEY = "builtin-gallery-lang";
const THEME_KEY = "builtin-gallery-theme";
const SUPPORTED_LANGS = ["en", "zh"];

const NAV_SECTIONS = [
  { href: "/",        key: "navComponents", match: (p) => p === "/" || p === "/index.html" },
  { href: "/pages/",  key: "navTemplates",  match: (p) => p === "/pages" || p === "/pages/" || p.startsWith("/pages/") },
];

const COMPONENT_TABS = [
  { value: "layout", key: "componentTab.layout", titleKey: "componentSection.layout" },
  { value: "navigation", key: "componentTab.navigation", titleKey: "componentSection.navigation" },
  { value: "display", key: "componentTab.display", titleKey: "componentSection.display" },
  { value: "forms", key: "componentTab.forms", titleKey: "componentSection.forms" },
  { value: "feedback", key: "componentTab.feedback", titleKey: "componentSection.feedback" },
  { value: "galleries", key: "componentTab.galleries", titleKey: "componentSection.galleries" },
  { value: "players", key: "componentTab.players", titleKey: "componentSection.players" },
  { value: "ai", key: "componentTab.ai", titleKey: "componentSection.ai" },
  { value: "calendars", key: "componentTab.calendars", titleKey: "componentSection.calendars" },
  { value: "workflow", key: "componentTab.workflow", titleKey: "componentSection.workflow" },
  { value: "visualization", key: "componentTab.visualization", titleKey: "componentSection.visualization" },
  { value: "commerce", key: "componentTab.commerce", titleKey: "componentSection.commerce" },
  { value: "social", key: "componentTab.social", titleKey: "componentSection.social" },
  { value: "editors", key: "componentTab.editors", titleKey: "componentSection.editors" },
  { value: "creative-tools", key: "componentTab.creativeTools", titleKey: "componentSection.creativeTools" },
  { value: "utilities", key: "componentTab.utilities", titleKey: "componentSection.utilities" },
  { value: "cloud", key: "componentTab.cloud", titleKey: "componentSection.cloud" },
];

// Live pages metadata (single source of truth).
const LIVE_PAGE_INFO = {
  "/pages/admin-dashboard.html":     { titleKey: "page.adminDashboard",     categoryKey: "cat.dashboard" },
  "/pages/analytics-dashboard.html": { titleKey: "page.analyticsDashboard", categoryKey: "cat.dashboard" },
  "/pages/blog-article.html":        { titleKey: "page.blogArticle",        categoryKey: "cat.blog" },
  "/pages/cart-drawer.html":         { titleKey: "page.cartDrawer",         categoryKey: "cat.ecommerce" },
  "/pages/chat-room.html":           { titleKey: "page.chatRoom",           categoryKey: "cat.chat" },
  "/pages/checkout-layout.html":     { titleKey: "page.checkoutLayout",     categoryKey: "cat.ecommerce" },
  "/pages/company-about.html":       { titleKey: "page.companyAbout",       categoryKey: "cat.company" },
  "/pages/contact-us.html":          { titleKey: "page.contactUs",          categoryKey: "cat.company" },
  "/pages/content-home.html":        { titleKey: "page.contentHome",        categoryKey: "cat.frontpage" },
  "/pages/documentation-layout.html":{ titleKey: "page.docsLayout",         categoryKey: "cat.tutorial" },
  "/pages/ecommerce-product-grid.html":{ titleKey:"page.productGrid",       categoryKey: "cat.ecommerce" },
  "/pages/editorial-layout.html":    { titleKey: "page.editorial",          categoryKey: "cat.magazine" },
  "/pages/file-manager.html":        { titleKey: "page.fileManager",        categoryKey: "cat.cloud" },
  "/pages/generic-home.html":        { titleKey: "page.genericHome",        categoryKey: "cat.frontpage" },
  "/pages/lead-capture.html":        { titleKey: "page.leadCapture",        categoryKey: "cat.landing" },
  "/pages/live-stream-room.html":    { titleKey: "page.liveStream",         categoryKey: "cat.live" },
  "/pages/login-page.html":          { titleKey: "page.loginPage",          categoryKey: "cat.auth" },
  "/pages/message-thread.html":      { titleKey: "page.messageThread",      categoryKey: "cat.chat" },
  "/pages/news-layout.html":         { titleKey: "page.newsLayout",         categoryKey: "cat.magazine" },
  "/pages/onboarding-guide.html":    { titleKey: "page.onboarding",         categoryKey: "cat.tutorial" },
  "/pages/personal-profile.html":    { titleKey: "page.personalProfile",    categoryKey: "cat.profile" },
  "/pages/portfolio-layout.html":    { titleKey: "page.portfolio",          categoryKey: "cat.profile" },
  "/pages/product-detail.html":      { titleKey: "page.productDetail",      categoryKey: "cat.ecommerce" },
  "/pages/product-launch.html":      { titleKey: "page.productLaunch",      categoryKey: "cat.landing" },
  "/pages/saas-home.html":           { titleKey: "page.saasHome",           categoryKey: "cat.frontpage" },
  "/pages/shop-home.html":           { titleKey: "page.shopHome",           categoryKey: "cat.frontpage" },
  "/pages/social-profile.html":      { titleKey: "page.socialProfile",      categoryKey: "cat.social" },
  "/pages/survey-layout.html":       { titleKey: "page.survey",             categoryKey: "cat.form" },
  "/pages/video-home.html":          { titleKey: "page.videoHome",          categoryKey: "cat.frontpage" },
  "/pages/video-listing.html":       { titleKey: "page.videoListing",       categoryKey: "cat.video" },
  "/pages/video-platform.html":      { titleKey: "page.videoPlatform",      categoryKey: "cat.video" },
  "/pages/video-player.html":        { titleKey: "page.videoPlayer",        categoryKey: "cat.video" },
  "/pages/wizard-form.html":         { titleKey: "page.wizard",             categoryKey: "cat.form" },
};

const LIVE_PAGE_PATHS = Object.keys(LIVE_PAGE_INFO);

// ---------------------------------------------------------------------------
// i18n catalog (shell + page titles + page hardcoded labels)

const I18N = {
  en: {
    // shell
    navComponents: "Components",
    navTemplates: "Templates",
    randomShort: "Random",
    randomLong: "Random template",
    languageLabel: "Language",
    themeLightLabel: "Switch to light",
    themeDarkLabel: "Switch to dark",
    backToGallery: "Back to gallery",
    openLive: "Open live page",
    componentsHome: "Component Library",
    componentsHomeSub: "Interactive showcase of every shared component, with live theme + language switching.",
    templatesHome: "Template Gallery",
    templatesHomeSub: "33 ready-to-ship page templates, all built from the same component kit.",
    livePage: "Live preview",
    "componentTab.layout": "Layout",
    "componentTab.navigation": "Navigation",
    "componentTab.display": "Display",
    "componentTab.forms": "Forms",
    "componentTab.feedback": "Feedback",
    "componentTab.galleries": "Galleries",
    "componentTab.players": "Players",
    "componentTab.ai": "AI",
    "componentTab.calendars": "Calendars",
    "componentTab.workflow": "Workflow",
    "componentTab.visualization": "Visualization",
    "componentTab.commerce": "Commerce",
    "componentTab.social": "Social",
    "componentTab.editors": "Editors",
    "componentTab.creativeTools": "Creative",
    "componentTab.utilities": "Utilities",
    "componentTab.cloud": "Cloud",
    "componentSection.layout": "Layout",
    "componentSection.navigation": "Navigation",
    "componentSection.display": "Display",
    "componentSection.forms": "Forms",
    "componentSection.feedback": "Feedback",
    "componentSection.galleries": "Galleries",
    "componentSection.players": "Players",
    "componentSection.ai": "AI Components",
    "componentSection.calendars": "Calendars",
    "componentSection.workflow": "Workflow",
    "componentSection.visualization": "Visualization",
    "componentSection.commerce": "Commerce",
    "componentSection.social": "Social & Content",
    "componentSection.editors": "Editors",
    "componentSection.creativeTools": "Creative Tools",
    "componentSection.utilities": "Utilities",
    "componentSection.cloud": "Cloud & Admin",
    // categories
    "cat.frontpage": "Frontpage",
    "cat.magazine": "Magazine",
    "cat.tutorial": "Tutorial",
    "cat.form": "Form",
    "cat.video": "Video",
    "cat.ecommerce": "E-commerce",
    "cat.profile": "Profile",
    "cat.chat": "Chat",
    "cat.dashboard": "Dashboard",
    "cat.landing": "Landing",
    "cat.auth": "Auth",
    "cat.social": "Social",
    "cat.company": "Company",
    "cat.blog": "Blog",
    "cat.cloud": "Cloud",
    "cat.live": "Live",
    // page titles
    "page.adminDashboard": "Admin Dashboard",
    "page.analyticsDashboard": "Analytics Dashboard",
    "page.blogArticle": "Blog Article",
    "page.cartDrawer": "Cart Drawer",
    "page.chatRoom": "Chat Room",
    "page.checkoutLayout": "Checkout",
    "page.companyAbout": "Company About",
    "page.contactUs": "Contact Us",
    "page.contentHome": "Content Homepage",
    "page.docsLayout": "Documentation",
    "page.productGrid": "Product Grid",
    "page.editorial": "Editorial",
    "page.fileManager": "File Manager",
    "page.genericHome": "Generic Homepage",
    "page.leadCapture": "Lead Capture",
    "page.liveStream": "Live Stream Room",
    "page.loginPage": "Login Page",
    "page.messageThread": "Message Thread",
    "page.newsLayout": "News Layout",
    "page.onboarding": "Onboarding Guide",
    "page.personalProfile": "Personal Profile",
    "page.portfolio": "Portfolio",
    "page.productDetail": "Product Detail",
    "page.productLaunch": "Product Launch",
    "page.saasHome": "SaaS Homepage",
    "page.shopHome": "Shop Homepage",
    "page.socialProfile": "Social Profile",
    "page.survey": "Survey",
    "page.videoHome": "Video Homepage",
    "page.videoListing": "Video Listing",
    "page.videoPlatform": "Video Platform",
    "page.videoPlayer": "Video Player",
    "page.wizard": "Wizard Form",
    // template strings
    "cart.title": "Cart",
    "cart.empty": "Your cart is empty.",
    "cart.subtotal": "Subtotal",
    "cart.checkout": "Checkout",
    "checkout.address": "Address",
    "checkout.apply": "Apply",
    "checkout.card": "Credit card",
    "checkout.city": "City",
    "checkout.cod": "Cash on delivery",
    "checkout.country": "Country",
    "checkout.discountCode": "Discount code",
    "checkout.firstName": "First name",
    "checkout.lastName": "Last name",
    "checkout.orderSummary": "Order summary",
    "checkout.paymentMethod": "Payment method",
    "checkout.paypal": "PayPal",
    "checkout.placeOrder": "Place order",
    "checkout.postalCode": "Postal code",
    "checkout.shipping": "Shipping",
    "checkout.shippingAddress": "Shipping address",
    "checkout.subtotal": "Subtotal",
    "checkout.total": "Total",
    "grid.featured": "Featured",
    "grid.filters": "Filters",
    "grid.home": "Home",
    "grid.newest": "Newest",
    "grid.priceHighLow": "Price: high to low",
    "grid.priceLowHigh": "Price: low to high",
    "grid.shop": "Shop",
    "grid.sort": "Sort",
    "grid.showing": "{count} products",
    "grid.empty": "No products match these filters.",
    "grid.all": "All",
    "grid.men": "Men",
    "grid.women": "Women",
    "grid.sale": "Sale",
    "grid.unisex": "Unisex",
    "grid.gender": "Gender",
    "grid.category": "Category",
    "grid.price": "Price",
    "grid.clothing": "Clothing",
    "grid.shoes": "Shoes",
    "grid.accessories": "Accessories",
    "grid.under50": "Under $50",
    "grid.50to100": "$50-$100",
    "grid.100to200": "$100-$200",
    "grid.over200": "Over $200",
    "grid.product": "Product",
    "listing.all": "All",
    "listing.newest": "Newest",
    "listing.next": "Next",
    "listing.oldest": "Oldest",
    "listing.popular": "Popular",
    "listing.prev": "Previous",
    "listing.scrollLoadMore": "Scroll for more",
    "product.addToCart": "Add to cart",
    "product.buyNow": "Buy now",
    "product.description": "Description",
    "product.noDescription": "No description.",
    "product.noImage": "No image",
    "product.noReviews": "No reviews yet.",
    "product.relatedTitle": "You may also like",
    "product.reviews": "Reviews",
    "product.size": "Size",
    "product.specs": "Specifications",
    "survey.next": "Next",
    "survey.prev": "Previous",
    "survey.submit": "Submit",
    "survey.thanksText": "Thanks for your feedback.",
    "survey.thanksTitle": "Thank you!",
    "video.comments": "Comments",
    "video.dislike": "Dislike",
    "video.like": "Like",
    "video.recommended": "Recommended",
    "video.share": "Share",
    "video.subscribe": "Subscribe",
    "wizard.next": "Next",
    "wizard.prev": "Previous",
    "wizard.submit": "Submit",
    // component strings
    "booking.available": "Available",
    "booking.booked": "Booked",
    "booking.next": "Next",
    "booking.prev": "Previous",
    "booking.resource": "Resource",
    "booking.today": "Today",
    "breadcrumb.navLabel": "Breadcrumb",
    "chips.label": "Chips",
    "code.copy": "Copy",
    "code.plaintext": "Plain text",
    "comparison.feature": "Feature",
    "diff.inline": "Inline",
    "diff.new": "New",
    "diff.old": "Old",
    "diff.sideBySide": "Side by side",
    "danmaku.clickToPause": "Click to pause/resume",
    "drawer.close": "Close",
    "featureGrid.empty": "No features.",
    "files.actions": "Actions",
    "files.delete": "Delete",
    "files.empty": "No files.",
    "files.gridView": "Grid view",
    "files.home": "Home",
    "files.listView": "List view",
    "files.modified": "Modified",
    "files.name": "Name",
    "files.search": "Search files",
    "files.size": "Size",
    "files.sortAsc": "Ascending",
    "files.sortDesc": "Descending",
    "files.sortModified": "Sort by modified",
    "files.sortName": "Sort by name",
    "files.sortSize": "Sort by size",
    "files.sortType": "Sort by type",
    "files.upload": "Upload",
    "payment.delete": "Delete",
    "payment.expiry": "Expires",
    "payment.holder": "Cardholder",
    "payment.type": "Type",
    "pricing.plan": "Plan",
    "pricing.select": "Select",
    "pricingCard.featured": "Featured",
    "pricingCard.select": "Select",
    "prompt.label": "Message",
    "prompt.placeholder": "Type a message...",
    "prompt.stop": "Stop",
    "prompt.submit": "Send",
    "shipping.empty": "No shipping options.",
    "sidebar.close": "Collapse sidebar",
    "sidebar.open": "Expand sidebar",
    "stream.copy": "Copy",
    "stream.title": "Stream",
    "tagCloud.empty": "No tags.",
    "testimonial.rating": "Rating",
    "timeline.empty": "No events.",
    "tree.check": "Check",
    "tree.collapse": "Collapse",
    "tree.expand": "Expand",
    "themeToggle.light": "Switch to light",
    "themeToggle.dark": "Switch to dark",
  },
  zh: {
    navComponents: "组件",
    navTemplates: "模板",
    randomShort: "随机",
    randomLong: "随机模板",
    languageLabel: "语言",
    themeLightLabel: "切换到浅色",
    themeDarkLabel: "切换到深色",
    backToGallery: "返回模板库",
    openLive: "打开完整页面",
    componentsHome: "组件库",
    componentsHomeSub: "全部共享组件的交互演示,支持实时主题和多语言切换。",
    templatesHome: "模板库",
    templatesHomeSub: "33 套即用页面模板,基于同一套组件构建。",
    livePage: "实时预览",
    "componentTab.layout": "布局",
    "componentTab.navigation": "导航",
    "componentTab.display": "展示",
    "componentTab.forms": "表单",
    "componentTab.feedback": "反馈",
    "componentTab.galleries": "图库轮播",
    "componentTab.players": "播放器",
    "componentTab.ai": "AI",
    "componentTab.calendars": "日历",
    "componentTab.workflow": "流程",
    "componentTab.visualization": "可视化",
    "componentTab.commerce": "商业",
    "componentTab.social": "社交内容",
    "componentTab.editors": "编辑器",
    "componentTab.creativeTools": "创作工具",
    "componentTab.utilities": "实用工具",
    "componentTab.cloud": "云与管理",
    "componentSection.layout": "布局",
    "componentSection.navigation": "导航",
    "componentSection.display": "展示",
    "componentSection.forms": "表单",
    "componentSection.feedback": "反馈",
    "componentSection.galleries": "图库轮播",
    "componentSection.players": "播放器",
    "componentSection.ai": "AI 组件",
    "componentSection.calendars": "日历",
    "componentSection.workflow": "流程",
    "componentSection.visualization": "可视化",
    "componentSection.commerce": "商业组件",
    "componentSection.social": "社交与内容",
    "componentSection.editors": "编辑器",
    "componentSection.creativeTools": "创作工具",
    "componentSection.utilities": "实用工具",
    "componentSection.cloud": "云与管理",
    "cat.frontpage": "首页",
    "cat.magazine": "杂志",
    "cat.tutorial": "教程",
    "cat.form": "表单",
    "cat.video": "视频",
    "cat.ecommerce": "电商",
    "cat.profile": "个人主页",
    "cat.chat": "聊天",
    "cat.dashboard": "仪表盘",
    "cat.landing": "落地页",
    "cat.auth": "登录",
    "cat.social": "社交",
    "cat.company": "公司",
    "cat.blog": "博客",
    "cat.cloud": "云盘",
    "cat.live": "直播",
    "page.adminDashboard": "后台管理",
    "page.analyticsDashboard": "数据看板",
    "page.blogArticle": "博客文章",
    "page.cartDrawer": "购物车抽屉",
    "page.chatRoom": "聊天室",
    "page.checkoutLayout": "结账页",
    "page.companyAbout": "关于公司",
    "page.contactUs": "联系我们",
    "page.contentHome": "内容首页",
    "page.docsLayout": "文档中心",
    "page.productGrid": "商品列表",
    "page.editorial": "杂志阅读",
    "page.fileManager": "文件管理",
    "page.genericHome": "通用首页",
    "page.leadCapture": "线索收集",
    "page.liveStream": "直播间",
    "page.loginPage": "登录页",
    "page.messageThread": "消息会话",
    "page.newsLayout": "新闻门户",
    "page.onboarding": "新手引导",
    "page.personalProfile": "个人资料",
    "page.portfolio": "作品集",
    "page.productDetail": "商品详情",
    "page.productLaunch": "新品发布",
    "page.saasHome": "SaaS 首页",
    "page.shopHome": "商城首页",
    "page.socialProfile": "社交资料",
    "page.survey": "问卷调查",
    "page.videoHome": "视频首页",
    "page.videoListing": "视频列表",
    "page.videoPlatform": "视频平台",
    "page.videoPlayer": "视频播放",
    "page.wizard": "向导表单",
    // template strings
    "cart.title": "购物车",
    "cart.empty": "购物车是空的。",
    "cart.subtotal": "小计",
    "cart.checkout": "去结账",
    "checkout.address": "地址",
    "checkout.apply": "应用",
    "checkout.card": "信用卡",
    "checkout.city": "城市",
    "checkout.cod": "货到付款",
    "checkout.country": "国家",
    "checkout.discountCode": "优惠码",
    "checkout.firstName": "名",
    "checkout.lastName": "姓",
    "checkout.orderSummary": "订单摘要",
    "checkout.paymentMethod": "支付方式",
    "checkout.paypal": "PayPal",
    "checkout.placeOrder": "提交订单",
    "checkout.postalCode": "邮编",
    "checkout.shipping": "运费",
    "checkout.shippingAddress": "收货地址",
    "checkout.subtotal": "小计",
    "checkout.total": "合计",
    "grid.featured": "精选",
    "grid.filters": "筛选",
    "grid.home": "首页",
    "grid.newest": "最新",
    "grid.priceHighLow": "价格:高到低",
    "grid.priceLowHigh": "价格:低到高",
    "grid.shop": "商城",
    "grid.sort": "排序",
    "grid.showing": "{count} 件商品",
    "grid.empty": "没有符合筛选条件的商品。",
    "grid.all": "全部",
    "grid.men": "男装",
    "grid.women": "女装",
    "grid.sale": "折扣",
    "grid.unisex": "通用",
    "grid.gender": "性别",
    "grid.category": "分类",
    "grid.price": "价格",
    "grid.clothing": "服装",
    "grid.shoes": "鞋履",
    "grid.accessories": "配件",
    "grid.under50": "$50 以下",
    "grid.50to100": "$50-$100",
    "grid.100to200": "$100-$200",
    "grid.over200": "$200 以上",
    "grid.product": "商品",
    "listing.all": "全部",
    "listing.newest": "最新",
    "listing.next": "下一页",
    "listing.oldest": "最早",
    "listing.popular": "热门",
    "listing.prev": "上一页",
    "listing.scrollLoadMore": "滚动加载更多",
    "product.addToCart": "加入购物车",
    "product.buyNow": "立即购买",
    "product.description": "商品描述",
    "product.noDescription": "暂无描述。",
    "product.noImage": "暂无图片",
    "product.noReviews": "暂无评论。",
    "product.relatedTitle": "你可能也喜欢",
    "product.reviews": "评论",
    "product.size": "尺码",
    "product.specs": "规格参数",
    "survey.next": "下一步",
    "survey.prev": "上一步",
    "survey.submit": "提交",
    "survey.thanksText": "感谢你的反馈。",
    "survey.thanksTitle": "感谢你!",
    "video.comments": "评论",
    "video.dislike": "踩",
    "video.like": "赞",
    "video.recommended": "推荐",
    "video.share": "分享",
    "video.subscribe": "订阅",
    "wizard.next": "下一步",
    "wizard.prev": "上一步",
    "wizard.submit": "提交",
    // component strings
    "booking.available": "可预订",
    "booking.booked": "已预订",
    "booking.next": "下一周",
    "booking.prev": "上一周",
    "booking.resource": "资源",
    "booking.today": "今天",
    "breadcrumb.navLabel": "面包屑",
    "chips.label": "标签",
    "code.copy": "复制",
    "code.plaintext": "纯文本",
    "comparison.feature": "功能",
    "diff.inline": "内嵌",
    "diff.new": "新",
    "diff.old": "旧",
    "diff.sideBySide": "并排",
    "danmaku.clickToPause": "点击暂停/继续",
    "drawer.close": "关闭",
    "featureGrid.empty": "暂无功能项。",
    "files.actions": "操作",
    "files.delete": "删除",
    "files.empty": "没有文件。",
    "files.gridView": "宫格视图",
    "files.home": "我的云盘",
    "files.listView": "列表视图",
    "files.modified": "修改时间",
    "files.name": "名称",
    "files.search": "搜索文件",
    "files.size": "大小",
    "files.sortAsc": "升序",
    "files.sortDesc": "降序",
    "files.sortModified": "按修改时间",
    "files.sortName": "按名称",
    "files.sortSize": "按大小",
    "files.sortType": "按类型",
    "files.upload": "上传",
    "payment.delete": "删除",
    "payment.expiry": "有效期",
    "payment.holder": "持卡人",
    "payment.type": "卡类型",
    "pricing.plan": "套餐",
    "pricing.select": "选择",
    "pricingCard.featured": "推荐",
    "pricingCard.select": "选择",
    "prompt.label": "消息",
    "prompt.placeholder": "输入消息...",
    "prompt.stop": "停止",
    "prompt.submit": "发送",
    "shipping.empty": "暂无配送方式。",
    "sidebar.close": "收起侧栏",
    "sidebar.open": "展开侧栏",
    "stream.copy": "复制",
    "stream.title": "流",
    "tagCloud.empty": "暂无标签。",
    "testimonial.rating": "评分",
    "timeline.empty": "暂无事件。",
    "tree.check": "选中",
    "tree.collapse": "收起",
    "tree.expand": "展开",
    "themeToggle.light": "切换到浅色",
    "themeToggle.dark": "切换到深色",
  },
};

function detectInitialLang() {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved && SUPPORTED_LANGS.includes(saved)) return saved;
  const nav = (navigator.language || "en").toLowerCase();
  return nav.startsWith("zh") ? "zh" : "en";
}

let _currentLang = detectInitialLang();

function t(key) {
  return I18N[_currentLang]?.[key] ?? I18N.en[key] ?? key;
}

export function getGalleryLang() {
  return _currentLang;
}

export function setGalleryLang(lang) {
  if (!SUPPORTED_LANGS.includes(lang) || lang === _currentLang) return;
  _currentLang = lang;
  localStorage.setItem(LANG_KEY, lang);
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  setI18nCatalog(lang, I18N[lang]);  // notifies all builtin-* components
  refreshShell();
  document.dispatchEvent(new CustomEvent("builtin-gallery-lang-change", { detail: { lang } }));
}

// ---------------------------------------------------------------------------
// Theme

function detectInitialTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "dark" || saved === "light") return saved;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyInitialTheme() {
  setSharedTheme(detectInitialTheme() === "dark");
}

document.addEventListener("builtin-theme-change", (e) => {
  localStorage.setItem(THEME_KEY, e.detail.theme);
});

// ---------------------------------------------------------------------------
// Path / page-info utilities

function normalizePathname(pathname) {
  if (!pathname) return "/";
  if (pathname === "/pages") return "/pages/";
  return pathname;
}

function currentSection(pathname) {
  return NAV_SECTIONS.find((section) => section.match(pathname)) ?? NAV_SECTIONS[0];
}

function pageInfo(pathname) {
  const path = normalizePathname(pathname);
  const live = LIVE_PAGE_INFO[path];
  if (live) {
    return {
      path,
      isLivePage: true,
      title: t(live.titleKey),
      category: t(live.categoryKey),
      subtitle: t("livePage"),
    };
  }
  const isPagesIndex = path === "/pages/" || path === "/pages/index.html";
  if (isPagesIndex) {
    return {
      path,
      isLivePage: false,
      title: t("templatesHome"),
      category: t("navTemplates"),
      subtitle: t("templatesHomeSub"),
    };
  }
  return {
    path,
    isLivePage: false,
    title: t("componentsHome"),
    category: t("navComponents"),
    subtitle: t("componentsHomeSub"),
  };
}

function randomLivePage(excludePath = "") {
  const exclude = normalizePathname(excludePath);
  const candidates = LIVE_PAGE_PATHS.filter((p) => p !== exclude);
  const source = candidates.length ? candidates : LIVE_PAGE_PATHS;
  return source[Math.floor(Math.random() * source.length)];
}

// ---------------------------------------------------------------------------
// Style injection

const STYLE_ID = "builtin-gallery-shell-style";

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    :root {
      --builtin-shell-height: 64px;
      --builtin-shell-radius: 18px;
      --builtin-shell-border: rgba(148,163,184,0.28);
      --builtin-shell-surface: rgba(255,255,255,0.78);
      --builtin-shell-bg: #f1f5f9;
      --builtin-shell-text: #0f172a;
      --builtin-shell-muted: #64748b;
      --builtin-shell-accent: #2563eb;
      --builtin-shell-accent-soft: rgba(37,99,235,0.12);
      --builtin-shell-shadow: 0 12px 32px rgba(15,23,42,0.10);
      --builtin-shell-divider: rgba(148,163,184,0.32);
    }
    [data-builtin-theme="dark"] {
      --builtin-shell-surface: rgba(15,23,42,0.78);
      --builtin-shell-bg: #0b1220;
      --builtin-shell-text: #e2e8f0;
      --builtin-shell-muted: #94a3b8;
      --builtin-shell-border: rgba(148,163,184,0.18);
      --builtin-shell-shadow: 0 12px 32px rgba(2,6,23,0.42);
      --builtin-shell-accent-soft: rgba(59,130,246,0.18);
      --builtin-shell-divider: rgba(148,163,184,0.18);
    }

    html, body { background: var(--builtin-shell-bg); color: var(--builtin-shell-text); }
    body.builtin-gallery-shell-ready {
      min-height: 100vh;
      padding-top: calc(var(--builtin-shell-height) + 24px);
    }

    .builtin-shell-bar {
      position: fixed;
      top: 12px;
      left: 12px;
      right: 12px;
      z-index: 1200;
      pointer-events: none;
    }
    .builtin-shell-inner {
      pointer-events: auto;
      max-width: 1440px;
      margin: 0 auto;
      min-height: var(--builtin-shell-height);
      box-sizing: border-box;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px 14px;
      padding: 8px 14px;
      border-radius: var(--builtin-shell-radius);
      border: 1px solid var(--builtin-shell-border);
      background: var(--builtin-shell-surface);
      backdrop-filter: blur(20px) saturate(180%);
      -webkit-backdrop-filter: blur(20px) saturate(180%);
      box-shadow: var(--builtin-shell-shadow);
    }
    .builtin-shell-inner > * { min-width: 0; }
    .builtin-shell-spacer { flex: 1 1 auto; min-width: 0; }

    .builtin-shell-brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .builtin-shell-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 6px 10px;
      border-radius: 8px;
      background: var(--builtin-shell-accent-soft);
      color: var(--builtin-shell-accent);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .builtin-shell-copy {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .builtin-shell-copy strong {
      font-size: 14px;
      font-weight: 700;
      color: var(--builtin-shell-text);
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .builtin-shell-copy span {
      font-size: 11px;
      color: var(--builtin-shell-muted);
      line-height: 1.3;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .builtin-shell-nav {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      padding: 4px;
      border-radius: 999px;
      background: var(--builtin-shell-accent-soft);
      justify-self: center;
    }
    .builtin-shell-nav a {
      display: inline-flex;
      align-items: center;
      padding: 7px 16px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 600;
      color: var(--builtin-shell-muted);
      text-decoration: none;
      transition: background 0.15s ease, color 0.15s ease;
      white-space: nowrap;
    }
    .builtin-shell-nav a:hover {
      color: var(--builtin-shell-text);
    }
    .builtin-shell-nav a.active {
      background: var(--builtin-shell-accent);
      color: #fff;
      box-shadow: 0 4px 12px rgba(37,99,235,0.28);
    }

    .builtin-shell-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .builtin-shell-divider {
      width: 1px;
      height: 24px;
      background: var(--builtin-shell-divider);
    }
    .builtin-shell-iconbtn,
    .builtin-shell-langbtn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 36px;
      padding: 0 12px;
      border-radius: 10px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--builtin-shell-muted);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
    }
    .builtin-shell-iconbtn:hover,
    .builtin-shell-langbtn:hover {
      background: var(--builtin-shell-accent-soft);
      color: var(--builtin-shell-text);
    }
    .builtin-shell-iconbtn builtin-icon,
    .builtin-shell-langbtn builtin-icon { display: inline-flex; }

    .builtin-shell-langwrap {
      position: relative;
    }
    .builtin-shell-langmenu {
      position: absolute;
      top: calc(100% + 6px);
      right: 0;
      min-width: 140px;
      padding: 4px;
      border-radius: 12px;
      border: 1px solid var(--builtin-shell-border);
      background: var(--builtin-shell-surface);
      backdrop-filter: blur(18px) saturate(180%);
      -webkit-backdrop-filter: blur(18px) saturate(180%);
      box-shadow: var(--builtin-shell-shadow);
      display: none;
      flex-direction: column;
      gap: 2px;
      z-index: 1300;
    }
    .builtin-shell-langwrap.open .builtin-shell-langmenu { display: flex; }
    .builtin-shell-langmenu button {
      appearance: none;
      border: none;
      background: transparent;
      text-align: left;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      color: var(--builtin-shell-text);
      cursor: pointer;
    }
    .builtin-shell-langmenu button:hover {
      background: var(--builtin-shell-accent-soft);
    }
    .builtin-shell-langmenu button.active {
      background: var(--builtin-shell-accent);
      color: #fff;
    }

    .builtin-gallery-live-stage {
      max-width: 1440px;
      margin: 0 auto;
      padding: 0 clamp(12px,3vw,28px) 48px;
    }
    .builtin-gallery-live-hero {
      margin: 6px 0 18px;
    }
    .builtin-gallery-live-hero .kicker {
      display: inline-flex;
      align-items: center;
      padding: 5px 10px;
      border-radius: 999px;
      background: var(--builtin-shell-accent-soft);
      color: var(--builtin-shell-accent);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .builtin-gallery-live-hero h1 {
      margin: 10px 0 6px;
      font-size: clamp(24px,4vw,40px);
      line-height: 1.05;
      letter-spacing: -0.02em;
      color: var(--builtin-shell-text);
    }
    .builtin-gallery-live-hero p {
      margin: 0;
      color: var(--builtin-shell-muted);
      font-size: 14px;
    }
    .builtin-gallery-live-viewport {
      position: relative;
      overflow: hidden;
      border-radius: 18px;
      border: 1px solid var(--builtin-shell-border);
      background: var(--builtin-shell-surface);
      box-shadow: var(--builtin-shell-shadow);
    }
    .builtin-gallery-live-viewport > * {
      display: block;
      min-height: min(900px, calc(100vh - 220px));
    }

    .builtin-gallery-preview-shell {
      display: flex;
      flex-direction: column;
      min-height: 100%;
      gap: 14px;
      padding: 14px;
      box-sizing: border-box;
    }
    .builtin-gallery-preview-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--builtin-shell-border);
      background: var(--builtin-shell-surface);
    }
    .builtin-gallery-preview-toolbar .copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .builtin-gallery-preview-toolbar .copy strong { font-size: 14px; color: var(--builtin-shell-text); }
    .builtin-gallery-preview-toolbar .copy span { font-size: 12px; color: var(--builtin-shell-muted); }
    .builtin-gallery-preview-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .builtin-gallery-preview-actions a {
      display: inline-flex;
      align-items: center;
      padding: 7px 12px;
      border-radius: 999px;
      background: var(--builtin-shell-accent-soft);
      color: var(--builtin-shell-accent);
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
    }
    .builtin-gallery-preview-stage { flex: 1; min-height: 0; display: flex; }
    .builtin-gallery-preview-viewport {
      width: 100%;
      min-height: min(820px, calc(100vh - 240px));
      border-radius: 14px;
      border: 1px solid var(--builtin-shell-border);
      background: var(--builtin-shell-surface);
      overflow: hidden;
    }
    .builtin-gallery-preview-viewport > * { display: block; min-height: 100%; }

    .builtin-shell-breadcrumb {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      font-weight: 600;
      color: var(--builtin-shell-muted);
      min-width: 0;
      flex: 1 1 auto;
      justify-content: center;
    }
    .builtin-shell-breadcrumb a {
      color: var(--builtin-shell-text);
      text-decoration: none;
      padding: 5px 12px 5px 8px;
      border-radius: 999px;
      transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease;
      white-space: nowrap;
      background: var(--builtin-shell-accent-soft);
      border: 1px solid var(--builtin-shell-divider);
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .builtin-shell-breadcrumb a::before {
      content: "←";
      font-size: 14px;
      line-height: 1;
      display: inline-block;
    }
    .builtin-shell-breadcrumb a:hover {
      background: var(--builtin-shell-accent);
      color: var(--builtin-shell-on-accent, #fff);
      transform: translateX(-2px);
    }
    .builtin-shell-breadcrumb .sep {
      color: var(--builtin-shell-divider);
      flex: 0 0 auto;
    }
    .builtin-shell-breadcrumb .current {
      color: var(--builtin-shell-text);
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }

    @media (max-width: 860px) {
      .builtin-shell-copy { display: none; }
      .builtin-shell-iconbtn .text,
      .builtin-shell-langbtn .text { display: none; }
      .builtin-shell-iconbtn,
      .builtin-shell-langbtn { padding: 0 10px; }
    }
    @media (max-width: 520px) {
      .builtin-shell-badge { display: none; }
      .builtin-shell-divider { display: none; }
      .builtin-shell-actions { gap: 4px; }
      .builtin-shell-bar { left: 8px; right: 8px; top: 8px; }
      .builtin-shell-inner { padding: 6px 10px; gap: 8px; }
    }
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Bar build / refresh

let _barEl = null;

function buildBar() {
  const bar = document.createElement("div");
  bar.className = "builtin-shell-bar";

  const inner = document.createElement("div");
  inner.className = "builtin-shell-inner";

  // Brand
  const brand = document.createElement("div");
  brand.className = "builtin-shell-brand";
  const badge = document.createElement("div");
  badge.className = "builtin-shell-badge";
  badge.dataset.role = "category";
  const copy = document.createElement("div");
  copy.className = "builtin-shell-copy";
  const title = document.createElement("strong");
  title.dataset.role = "title";
  const subtitle = document.createElement("span");
  subtitle.dataset.role = "subtitle";
  copy.append(title, subtitle);
  brand.append(badge, copy);

  // Nav
  const nav = document.createElement("nav");
  nav.className = "builtin-shell-nav";
  nav.dataset.role = "nav";

  // Actions
  const actions = document.createElement("div");
  actions.className = "builtin-shell-actions";

  const random = document.createElement("button");
  random.type = "button";
  random.className = "builtin-shell-iconbtn";
  random.dataset.role = "random";
  random.innerHTML = `<builtin-icon name="reload" size="16" variant="outlined"></builtin-icon><span class="text"></span>`;
  random.addEventListener("click", () => {
    window.location.href = randomLivePage(window.location.pathname);
  });

  const divider1 = document.createElement("div");
  divider1.className = "builtin-shell-divider";

  // Language switcher
  const langWrap = document.createElement("div");
  langWrap.className = "builtin-shell-langwrap";
  const langBtn = document.createElement("button");
  langBtn.type = "button";
  langBtn.className = "builtin-shell-langbtn";
  langBtn.setAttribute("aria-haspopup", "menu");
  langBtn.innerHTML = `<builtin-icon name="global" size="16" variant="outlined"></builtin-icon><span class="text" data-role="lang-label"></span>`;
  const langMenu = document.createElement("div");
  langMenu.className = "builtin-shell-langmenu";
  langMenu.setAttribute("role", "menu");
  for (const code of SUPPORTED_LANGS) {
    const item = document.createElement("button");
    item.type = "button";
    item.dataset.lang = code;
    item.textContent = code === "zh" ? "中文" : "English";
    item.addEventListener("click", () => {
      setGalleryLang(code);
      langWrap.classList.remove("open");
    });
    langMenu.appendChild(item);
  }
  langBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    langWrap.classList.toggle("open");
  });
  document.addEventListener("click", () => langWrap.classList.remove("open"));
  langWrap.append(langBtn, langMenu);

  const divider2 = document.createElement("div");
  divider2.className = "builtin-shell-divider";

  const themeSlot = document.createElement("builtin-theme-toggle");

  actions.append(random, divider1, langWrap, divider2, themeSlot);

  const spacerL = document.createElement("div");
  spacerL.className = "builtin-shell-spacer";
  const spacerR = document.createElement("div");
  spacerR.className = "builtin-shell-spacer";
  inner.append(brand, spacerL, nav, spacerR, actions);
  bar.appendChild(inner);
  return bar;
}

function refreshShell() {
  if (!_barEl) return;
  const path = normalizePathname(window.location.pathname);
  const info = pageInfo(path);
  const section = currentSection(path);

  _barEl.querySelector('[data-role="category"]').textContent = info.category;
  _barEl.querySelector('[data-role="title"]').textContent = info.title;
  _barEl.querySelector('[data-role="subtitle"]').textContent = info.subtitle;

  const nav = _barEl.querySelector('[data-role="nav"]');
  nav.replaceChildren();
  if (info.isLivePage) {
    // On a live template page, replace the section nav with a breadcrumb
    // back to the templates gallery so users can return easily.
    nav.classList.remove("builtin-shell-nav");
    nav.classList.add("builtin-shell-breadcrumb");
    const back = document.createElement("a");
    back.href = "/pages/";
    back.textContent = t("navTemplates");
    back.title = t("backToGallery");
    const sep = document.createElement("span");
    sep.className = "sep";
    sep.textContent = "/";
    const cur = document.createElement("span");
    cur.className = "current";
    cur.textContent = info.title;
    nav.append(back, sep, cur);
  } else {
    nav.classList.remove("builtin-shell-breadcrumb");
    nav.classList.add("builtin-shell-nav");
    for (const item of NAV_SECTIONS) {
      const a = document.createElement("a");
      a.href = item.href;
      a.textContent = t(item.key);
      if (item === section) a.classList.add("active");
      nav.appendChild(a);
    }
  }

  const random = _barEl.querySelector('[data-role="random"]');
  random.querySelector(".text").textContent = t("randomLong");
  random.title = t("randomLong");
  random.setAttribute("aria-label", t("randomLong"));

  const langLabel = _barEl.querySelector('[data-role="lang-label"]');
  langLabel.textContent = _currentLang === "zh" ? "中文" : "English";
  for (const btn of _barEl.querySelectorAll('.builtin-shell-langmenu button')) {
    btn.classList.toggle("active", btn.dataset.lang === _currentLang);
  }

  // Update live-page hero text if present
  const heroKicker = document.querySelector(".builtin-gallery-live-hero .kicker");
  const heroTitle  = document.querySelector(".builtin-gallery-live-hero h1");
  const heroSub    = document.querySelector(".builtin-gallery-live-hero p");
  if (heroKicker) heroKicker.textContent = info.category;
  if (heroTitle)  heroTitle.textContent = info.title;
  if (heroSub)    heroSub.textContent = info.subtitle;

  // Update document title
  document.title = `${info.title} · ${t(section.key)}`;
  refreshComponentGalleryLabels(path);
}

function refreshComponentGalleryLabels(path) {
  if (path !== "/" && path !== "/index.html") return;
  const tabs = document.querySelector("builtin-tabs[active='layout']");
  if (tabs) {
    tabs.items = COMPONENT_TABS.map((item) => ({ value: item.value, label: t(item.key) }));
  }
  for (const item of COMPONENT_TABS) {
    const panel = document.querySelector(`[data-tab="${item.value}"]`);
    const title = panel?.querySelector(".gallery-section-title");
    if (!title) continue;
    const icon = title.querySelector("builtin-icon");
    title.replaceChildren();
    if (icon) title.appendChild(icon);
    title.append(document.createTextNode(` ${t(item.titleKey || item.key)}`));
  }
}

function wrapLivePage() {
  // Intentionally a no-op: live template pages render at full width below the
  // fixed shell bar. Constraining them inside a viewport box previously broke
  // templates with sidebars, fixed headers, or fullscreen layouts.
  return;
}

// ---------------------------------------------------------------------------
// Public preview helper (used by index.html template-preview modal)

export function mountGalleryPreviewFrame(host, contentNode, options = {}) {
  ensureStyles();
  const liveHref = options.liveHref || null;
  const info = liveHref ? pageInfo(liveHref) : {
    title: options.title || options.tagName || "Preview",
    category: options.category || t("navTemplates"),
  };

  const shell = document.createElement("div");
  shell.className = "builtin-gallery-preview-shell";

  const toolbar = document.createElement("div");
  toolbar.className = "builtin-gallery-preview-toolbar";
  const copy = document.createElement("div");
  copy.className = "copy";
  const title = document.createElement("strong");
  title.textContent = info.title;
  const subtitle = document.createElement("span");
  subtitle.textContent = info.category;
  copy.append(title, subtitle);
  const actions = document.createElement("div");
  actions.className = "builtin-gallery-preview-actions";
  if (liveHref) {
    const link = document.createElement("a");
    link.href = liveHref;
    link.textContent = t("openLive");
    actions.appendChild(link);
  }
  toolbar.append(copy, actions);

  const stage = document.createElement("div");
  stage.className = "builtin-gallery-preview-stage";
  const viewport = document.createElement("div");
  viewport.className = "builtin-gallery-preview-viewport";
  viewport.appendChild(contentNode);
  stage.appendChild(viewport);

  shell.append(toolbar, stage);
  host.replaceChildren(shell);
}

// ---------------------------------------------------------------------------
// Init

function init() {
  if (!document.body || document.body.dataset.builtinGalleryShellInitialized === "true") return;
  ensureStyles();
  applyInitialTheme();
  document.documentElement.lang = _currentLang === "zh" ? "zh-CN" : "en";
  setI18nCatalog(_currentLang, I18N[_currentLang]);

  document.body.dataset.builtinGalleryShellInitialized = "true";
  document.body.classList.add("builtin-gallery-shell-ready");

  const bar = buildBar();
  document.body.prepend(bar);
  _barEl = bar;

  const path = normalizePathname(window.location.pathname);
  const info = pageInfo(path);
  if (info.isLivePage) wrapLivePage();

  refreshShell();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}

globalThis.ProjectGalleryShell = Object.assign({}, globalThis.ProjectGalleryShell || {}, {
  mountGalleryPreviewFrame,
  getGalleryLang,
  setGalleryLang,
});
