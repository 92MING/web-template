# -*- coding: utf-8 -*-
"""Tests for UI translate endpoints."""

import asyncio
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_DIR = _PROJECT_ROOT / "app"
for _path in (str(_PROJECT_ROOT), str(_APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.server.data_types.config import Config, ServerConfig
from core.server.translate import register_internal_translation
from core.server.routes.panel.main import register_panel_routes


def test_ui_translate_endpoints() -> None:
    Config.SetConfig(Config(server_config=ServerConfig()))
    key = "test.ui.translate.route"
    register_internal_translation(key, 'en', "Hello")
    register_internal_translation(key, 'zh-cn', "你好")
    register_internal_translation(key, 'zh-tw', "你好")

    app = FastAPI()
    register_panel_routes(app)

    async def _run_checks() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            one = await client.get("/_internal/admin/api/ui_translate", params={"keys": key, "lang": "zh-cn"})
            assert one.status_code == 200
            assert one.json()["translations"][key] == "你好"

            all_items = await client.get("/_internal/admin/api/ui_translate/all")
            assert all_items.status_code == 200
            assert all_items.json()["translations"]["en"][key] == "Hello"

    asyncio.run(_run_checks())
