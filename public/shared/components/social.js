/**
 * @fileoverview Communication and social components entry point.
 *
 * Chat, comments, notifications, activity feeds, and social widgets.
 */

import { BuiltinActivityFeed } from "./social/activity-feed.js";
import { BuiltinCommentSection } from "./social/comment-section.js";
import { BuiltinDanmaku } from "./social/danmaku.js";
import { BuiltinNewsletter } from "./social/newsletter.js";
import { BuiltinNotificationBadge } from "./social/notification-badge.js";
import { BuiltinNotificationCenter } from "./social/notification-center.js";
import { BuiltinSocialBlogCard } from "./social/social-blog-card.js";
import { BuiltinSocialLogin } from "./social/social-login.js";

export {
  BuiltinActivityFeed, BuiltinCommentSection, BuiltinDanmaku, BuiltinNewsletter, BuiltinNotificationBadge, BuiltinNotificationCenter, BuiltinSocialBlogCard, BuiltinSocialLogin
};

const _REGISTRY = [
  ["builtin-activity-feed", BuiltinActivityFeed],
  ["builtin-comment-section", BuiltinCommentSection],
  ["builtin-danmaku", BuiltinDanmaku],
  ["builtin-newsletter", BuiltinNewsletter],
  ["builtin-notification-badge", BuiltinNotificationBadge],
  ["builtin-notification-center", BuiltinNotificationCenter],
  ["builtin-social-blog-card", BuiltinSocialBlogCard],
  ["builtin-social-login", BuiltinSocialLogin],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
