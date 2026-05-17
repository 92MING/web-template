# -*- coding: utf-8 -*-
"""Core server package."""

from .request import AdvanceRequest
from .route import ErrorContext, Route, delete, get, head, options, patch, post, put, route, websocket
from .events import *
from .scheduler import *
from .plugin import *

__all__ = [
    # data types
    "AdvanceRequest", "ErrorContext",
    
    # events
    "on_before_app_created", "on_app_created", "on_app_shutdown", "on_uvicorn_close",
    "register_main_process_context_manager", "on_main_process_starts_event", "on_main_process_stops_event",
    "start_main_process_events", "stop_main_process_events",
    
    # scheduler
    "ScheduledTaskHandle", "cancel_scheduled_task", "get_scheduled_tasks",
    "schedule_at", "schedule_daily", "schedule_every", "schedule_interval", "schedule_once",
    "start_scheduler", "stop_scheduler",

    # plugins
    "PluginBase", "MainOnlyPlugin", "WorkerOnlyPlugin", "MainAndWorkerPlugin",
    "PluginRuntimeAction", "PluginRuntimeProcessResult", "PluginRuntimeRequest", "PluginRuntimeResponse",
    "Plugin", "PluginClass", "PluginConfig", "apply_runtime_plugin_action", "clear_plugins", "configure_plugin",
    "configure_plugins", "configure_runtime_plugin_paths", "ensure_plugins", "get_core_module",
    "get_plugin_instance", "get_plugin_key", "get_plugin_paths_from_env", "get_registered_plugins",
    "list_plugin_panels", "load_plugins_from_env", "load_plugins_from_paths", "normalize_plugin_paths", "register_plugin", "render_plugin_panel",
    "register_plugin_panel_routes",
    "set_plugin_paths_env", "start_plugins", "stop_plugins",
    
    # routes
    "delete", "get", "head", "options", "patch",
    "post", "put", "route", "websocket", "Route",
]
