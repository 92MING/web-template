# -*- coding: utf-8 -*-
"""Core server package."""

from .request import AdvanceRequest
from .route import ErrorContext, Route, delete, get, head, options, patch, post, put, route, websocket
from .events import *
from .scheduler import *

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
    
    # routes
    "delete", "get", "head", "options", "patch",
    "post", "put", "route", "websocket", "Route",
]
