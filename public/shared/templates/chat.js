/**
 * @fileoverview Chat template entry point.
 */

import { BuiltinTplChatRoom } from "./chat/chat-room.js?v=20260501-2";
import { BuiltinTplChatMessageThread } from "./chat/message-thread.js?v=20260501-2";

export { BuiltinTplChatRoom, BuiltinTplChatMessageThread };

const _REGISTRY = [
  ["builtin-tpl-chat-room", BuiltinTplChatRoom],
  ["builtin-tpl-chat-message-thread", BuiltinTplChatMessageThread],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
