/**
 * @fileoverview Code and text editor components entry point.
 */

import { BuiltinCodeEditor } from "./data/code-editor.js";
import { BuiltinJsonEditor } from "./data/json-editor.js";
import { BuiltinMarkdownEditor } from "./data/markdown-editor.js";
import { BuiltinRichTextEditor } from "./data/rich-text-editor.js";

export {
  BuiltinCodeEditor, BuiltinJsonEditor, BuiltinMarkdownEditor,
  BuiltinRichTextEditor,
};

const _REGISTRY = [
  ["builtin-code-editor", BuiltinCodeEditor],
  ["builtin-json-editor", BuiltinJsonEditor],
  ["builtin-markdown-editor", BuiltinMarkdownEditor],
  ["builtin-rich-text-editor", BuiltinRichTextEditor],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}