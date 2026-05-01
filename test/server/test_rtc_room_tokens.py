# -*- coding: utf-8 -*-
"""Tests for RTC room capability tokens and runtime gating."""

import sys
import unittest

from pathlib import Path

import httpx
from fastapi import FastAPI


_server_dir = Path(__file__).resolve().parent.parent.parent / "app" / "core" / "server"
if str(_server_dir.parent.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent.parent))
if str(_server_dir.parent) not in sys.path:
    sys.path.insert(0, str(_server_dir.parent))


from core.server.app import register_public_fallback
from core.server.data_types.config import Config, LogConfig, ServerConfig, WebRTCRoomConfig
from core.server.routes.rtc_room import register_rtc_room_routes
from core.server.rtc_room import (
    build_room_create_request,
    build_room_join_request,
    create_room_invite_token,
    create_room_token,
    verify_room_create_token,
)
from core.server.security.jwt import ensure_jwt_keys_or_warn


class TestRTCRoomTokenHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_jwt_keys_or_warn(Path(__file__).resolve().parent.parent.parent)

    def test_create_room_token_defaults_and_overrides(self):
        token = create_room_token(
            is_public=False,
            name="Token Owned Room",
            user_name="owner-user",
            close_room_on_creator_left=True,
        )

        claims = verify_room_create_token(token)
        self.assertEqual(claims.exp - claims.iat, 3600)

        request = build_room_create_request(
            token=token,
            sdp="v=0",
            type="offer",
            name="ui-name",
            user_name="ui-user",
            close_room_on_creator_left=False,
        )

        self.assertEqual(request.name, "Token Owned Room")
        self.assertEqual(request.user_name, "owner-user")
        self.assertTrue(request.close_room_on_creator_left)
        self.assertIsNotNone(request.password)

    def test_join_request_prefers_invite_token_values(self):
        invite = create_room_invite_token(
            room_id="room-from-token",
            password="secret-pass",
            user_name="invited-user",
        )

        request = build_room_join_request(
            token=invite,
            sdp="v=0",
            type="offer",
            room_id="room-from-ui",
            password="ui-pass",
            user_name="ui-user",
        )

        self.assertEqual(request.room_id, "room-from-token")
        self.assertEqual(request.password, "secret-pass")
        self.assertEqual(request.user_name, "invited-user")

        public_request = build_room_join_request(
            token=None,
            sdp="v=0",
            type="offer",
            room_id="public-room",
            password=None,
            user_name="public-user",
        )

        self.assertEqual(public_request.room_id, "public-room")
        self.assertEqual(public_request.user_name, "public-user")


class TestRTCRoomDisabledGating(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        ensure_jwt_keys_or_warn(Path(__file__).resolve().parent.parent.parent)

    async def asyncSetUp(self):
        self.cfg = Config(
            server_config=ServerConfig(host="127.0.0.1", port=18999, expose_ai_service=True),
            log_config=LogConfig(log_method=["db"]),
            rtc_room_config=WebRTCRoomConfig(rtc_room_enable=False),
        )
        Config.SetConfig(self.cfg)
        self.app = FastAPI()
        register_rtc_room_routes(self.app)
        register_public_fallback(self.app, self.cfg)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_shared_component_returns_404_when_disabled(self):
        response = await self.client.get("/shared/components/rtc_room.html")
        self.assertEqual(response.status_code, 404)

    async def test_create_route_returns_404_when_disabled(self):
        token = create_room_token(name="Disabled Room")
        response = await self.client.post(
            "/rtc_room/create",
            json={
                "token": token,
                "sdp": "v=0",
                "type": "offer",
            },
        )
        self.assertEqual(response.status_code, 404)