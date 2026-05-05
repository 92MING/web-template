from .shared import *
from .config import *
from .base import ServiceBase
from .completion import CompletionClient, CompletionService, OpenAILikedCompletionClient, ThinkThinkSynCompletionClient
from .embedding import EmbeddingService
from .s2t import S2TService
from .t2s import T2SService


def preload_default_services(
    background: bool = True,
    probe_predefined_clients: bool = False,
    service_kinds: tuple[str, ...] | None = None,
) -> None:
    """Stub: preload default AI services (proj-template placeholder)."""
    pass


def clear_runtime_services(service_kinds: tuple[str, ...] | None = None) -> None:
    """Stub: clear runtime AI services (proj-template placeholder)."""
    pass


def get_predefined_service_kinds() -> list[str]:
    """Stub: return predefined service kinds (proj-template placeholder)."""
    return []
