/**
 * @fileoverview Blog template entry point.
 */

import { BuiltinTplBlogArticle } from "./blog/blog-article.js";

export { BuiltinTplBlogArticle };

if (!customElements.get("builtin-tpl-blog-article")) {
  customElements.define("builtin-tpl-blog-article", BuiltinTplBlogArticle);
}
