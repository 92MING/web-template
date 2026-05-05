/**
 * @fileoverview AI-related components entry point.
 *
 * LLM prompt inputs, streaming responses, code blocks, and suggestion chips.
 */

import { BuiltinAiCodeBlock } from "./ai/ai-code-block.js";
import { BuiltinAiChatbot } from "./ai/ai-chatbot.js";
import { BuiltinAiPromptInput } from "./ai/ai-prompt-input.js";
import { BuiltinAiResponseStream } from "./ai/ai-response-stream.js";
import { BuiltinAiSuggestionChips } from "./ai/ai-suggestion-chips.js";

export {
  BuiltinAiChatbot, BuiltinAiCodeBlock, BuiltinAiPromptInput, BuiltinAiResponseStream,
  BuiltinAiSuggestionChips,
};

const _REGISTRY = [
  ["builtin-ai-chatbot", BuiltinAiChatbot],
  ["builtin-ai-code-block", BuiltinAiCodeBlock],
  ["builtin-ai-prompt-input", BuiltinAiPromptInput],
  ["builtin-ai-response-stream", BuiltinAiResponseStream],
  ["builtin-ai-suggestion-chips", BuiltinAiSuggestionChips],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}
