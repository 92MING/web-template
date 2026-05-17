import sys
from types import ModuleType

from core.server import Route
from core.server.plugin import get_plugin_key, get_registered_plugins


class MeetingRouteBase(Route):
    Abstract = True

    def _chatroom_module(self) -> ModuleType:
        plugin_class = next(
            (plugin for plugin in get_registered_plugins() if get_plugin_key(plugin) == "webrtc-chatroom"),
            None,
        )
        if plugin_class is None:
            raise RuntimeError("webrtc-chatroom plugin is not enabled.")
        module = sys.modules.get(plugin_class.__module__)
        if module is None:
            raise RuntimeError("webrtc-chatroom module is not loaded.")
        return module