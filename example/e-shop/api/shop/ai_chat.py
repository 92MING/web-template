import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from core.server import Route

logger = logging.getLogger("e-shop.ai")


class AiChatRequest(BaseModel):
    message: str


def _fallback_reply(message: str) -> str:
    fallbacks = {
        "price": "Our products are competitively priced with a 7-day no-reason return policy.",
        "shipping": "We usually ship within 24 hours with free express delivery.",
        "after-sales": "We support 7-day no-reason returns, 15-day exchanges, and a one-year warranty.",
    }
    lowered = message.lower()
    for key, reply in fallbacks.items():
        if key in lowered:
            return reply
    return "Hello! I am the e-Shop AI assistant. How can I help you?"


def _has_explicit_ai_config() -> bool:
    if str(os.getenv("__AI_SERVICES_CONFIG__", "") or "").strip():
        return True
    config_dir = Path.cwd() / "config"
    for stem in ("ai_services", "ai_services.dev", "ai_services.prod"):
        for suffix in (".yaml", ".yml", ".json", ".toml"):
            if (config_dir / f"{stem}{suffix}").is_file():
                return True
    return False


class ShopAiChatRoute(Route):
    Tags = "Shop"
    RoutePath = "/api/shop/ai-chat"

    async def post(self, payload: AiChatRequest) -> dict[str, object]:
        message = payload.message
        if not _has_explicit_ai_config():
            return {"reply": _fallback_reply(message)}
        try:
            from core.ai.completion import CompletionService
            service = CompletionService.Default()
            reply = await service.complete(
                messages=[
                    {"role": "system", "content": "You are an e-commerce AI assistant. Answer user questions in a friendly and concise way."},
                    {"role": "user", "content": message},
                ],
                temperature=0.7,
            )
            return {"reply": reply}
        except Exception as exc:
            logger.warning("AI chat failed: %s", exc)
            return {"reply": _fallback_reply(message)}

    async def post_stream(self, payload: AiChatRequest) -> StreamingResponse:
        message = payload.message

        async def _sse():
            if not _has_explicit_ai_config():
                yield f"data: {json.dumps({'text': _fallback_reply(message), 'done': True}, ensure_ascii=False)}\n\n"
                return
            try:
                from core.ai.completion import CompletionService
                service = CompletionService.Default()
                async for chunk in service.stream_complete(
                    messages=[
                        {"role": "system", "content": "You are an e-commerce AI assistant. Answer user questions in a friendly and concise way."},
                        {"role": "user", "content": message},
                    ],
                    temperature=0.7,
                ):
                    text = chunk.get("data", "")
                    if text:
                        yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.warning("AI stream failed: %s", exc)
                yield f"data: {json.dumps({'text': 'Service temporarily unavailable. Please try again later.', 'done': True}, ensure_ascii=False)}\n\n"

        return StreamingResponse(_sse(), media_type="text/event-stream")
