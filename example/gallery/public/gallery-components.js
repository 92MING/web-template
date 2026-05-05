import "/shared/components/basic.js";
import "/shared/components/layout.js";
import "/shared/components/form.js";
import "/shared/components/data.js?v=20260505-18";
import "/shared/components/display.js";
import "/shared/components/navigation.js";
import "/shared/components/feedback.js";
import "/shared/components/workflow.js";
import "/shared/components/visualization.js";
import "/shared/components/commerce.js";
import "/shared/components/social.js";
import "/shared/components/utilities.js";
import "/shared/components/cloud-admin.js";

import { BuiltinAiChatbot } from "/shared/components/ai/ai-chatbot.js?v=20260505-13";
import { BuiltinAiCodeBlock } from "/shared/components/ai/ai-code-block.js?v=20260505-13";
import { BuiltinAiPromptInput } from "/shared/components/ai/ai-prompt-input.js?v=20260505-13";
import { BuiltinAiResponseStream } from "/shared/components/ai/ai-response-stream.js?v=20260505-13";
import { BuiltinAiSuggestionChips } from "/shared/components/ai/ai-suggestion-chips.js?v=20260505-13";
import { BuiltinCodeEditor } from "/shared/components/data/code-editor.js?v=20260505-13";
import { BuiltinJsonEditor } from "/shared/components/data/json-editor.js?v=20260505-17";
import { BuiltinMarkdownEditor } from "/shared/components/data/markdown-editor.js?v=20260505-19";
import { BuiltinRichTextEditor } from "/shared/components/data/rich-text-editor.js?v=20260505-13";
import { BuiltinAdvancedPainter } from "/shared/components/media/advanced-painter.js";
import { BuiltinAudioPlayer } from "/shared/components/media/audio-player.js?v=20260505-19";
import { BuiltinCarousel } from "/shared/components/media/carousel.js?v=20260505-13";
import { BuiltinImageGallery } from "/shared/components/media/image-gallery.js?v=20260505-13";
import { BuiltinAudioEditor } from "/shared/components/media/audio-editor.js";
import { BuiltinVideoEditor } from "/shared/components/media/video-editor.js";
import { BuiltinVideoPlayer } from "/shared/components/media/video-player.js?v=20260506-10";
import { BuiltinWhiteboard } from "/shared/components/media/whiteboard.js";

const _REGISTRY = [
  ["builtin-ai-chatbot", BuiltinAiChatbot],
  ["builtin-ai-code-block", BuiltinAiCodeBlock],
  ["builtin-ai-prompt-input", BuiltinAiPromptInput],
  ["builtin-ai-response-stream", BuiltinAiResponseStream],
  ["builtin-ai-suggestion-chips", BuiltinAiSuggestionChips],
  ["builtin-advanced-painter", BuiltinAdvancedPainter],
  ["builtin-audio-player", BuiltinAudioPlayer],
  ["builtin-audio-editor", BuiltinAudioEditor],
  ["builtin-carousel", BuiltinCarousel],
  ["builtin-code-editor", BuiltinCodeEditor],
  ["builtin-image-gallery", BuiltinImageGallery],
  ["builtin-json-editor", BuiltinJsonEditor],
  ["builtin-markdown-editor", BuiltinMarkdownEditor],
  ["builtin-rich-text-editor", BuiltinRichTextEditor],
  ["builtin-video-editor", BuiltinVideoEditor],
  ["builtin-video-player", BuiltinVideoPlayer],
  ["builtin-whiteboard", BuiltinWhiteboard],
];

for (const [tag, cls] of _REGISTRY) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
}