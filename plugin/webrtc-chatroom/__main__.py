import os
import json
import logging
import secrets
import time
import uuid
from html import escape
from pathlib import Path
from typing import ClassVar, Literal

import jwt
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, ValidationError

from core.server.app import get_resources, redirect_to_worker
from core.server.html_injection import (
    html_response_from_content,
    html_response_from_path,
    html_response_from_path_with_mobile,
    merge_desktop_mobile_html,
)
from core.server.plugin import get_plugin_key
from core.server.security.jwt import JWT_ALG, JWT_ISSUER, JwtError, get_private_key, get_public_key
from core.utils.type_utils import AdvancedBaseModel

from .rtc_chat.config import AudioConfig, ChatRoomConfig, WebRTCConfiguration, WebRTCIceServer
from .rtc_chat.room import (
    RoomInfo,
    WebRTCRoom,
    WebRTCRoomCreationRequest,
    WebRTCRoomCreationResponse,
    WebRTCRoomJoinRequest,
    WebRTCRoomJoinResponse,
    WebRTC_SDP_Type,
    close_all_rooms,
)
from .shared import WebRTCChatroomSharedData


PLUGIN_DIR = Path(__file__).resolve().parent
PLUGIN_PUBLIC_DIR = PLUGIN_DIR / "public"
PLUGIN_ADMIN_DIR = PLUGIN_DIR / "admin"
PLUGIN_SHARED_ID = "webrtc-chatroom"
ROOM_HTML_FILE = PLUGIN_PUBLIC_DIR / "rtc_room.html"
ROOM_MOBILE_HTML_FILE = PLUGIN_PUBLIC_DIR / "rtc_room.m.html"
ROOM_MANAGE_HTML_FILE = PLUGIN_ADMIN_DIR / "room_manage.html"
ROOM_MANAGE_CSS_FILE = PLUGIN_ADMIN_DIR / "rtc-ui-shared.css"
ROOM_TEST_HTML_FILE = PLUGIN_ADMIN_DIR / "test_chatroom.html"
RTC_ROOM_CREATE_TOKEN_SUB = "rtc-room-create"
RTC_ROOM_JOIN_TOKEN_SUB = "rtc-room-join"
logger = logging.getLogger(__name__)


def _normalize_public_path(path: str, fallback: str) -> str:
    text = str(path or "").strip()
    if not text:
        return fallback
    return "/" + text.lstrip("/")


def _normalize_internal_suffix(path: str, fallback: str) -> str:
    text = str(path or "").strip().strip("/")
    return text or fallback


class WebRTCChatroomPluginConfig(BaseModel):
    enabled: bool = False
    public_component_html_path: str = "/shared/components/rtc_room.html"
    public_component_mobile_html_path: str = "/shared/components/rtc_room.m.html"
    room_html_path: str = "/rtc_room/room"
    create_path: str = "/rtc_room/create"
    join_path: str = "/rtc_room/join"
    test_audio_path: str = "/rtc_room/test-audio"
    admin_manage_path: str = "rtc_room/manage"
    admin_test_path: str = "test/chatroom"
    admin_rooms_api_path: str = "api/rooms"
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    rtc_config: WebRTCConfiguration | None = None

    def model_post_init(self, __context) -> None:
        self.public_component_html_path = _normalize_public_path(
            self.public_component_html_path,
            "/shared/components/rtc_room.html",
        )
        self.public_component_mobile_html_path = _normalize_public_path(
            self.public_component_mobile_html_path,
            "/shared/components/rtc_room.m.html",
        )
        self.room_html_path = _normalize_public_path(self.room_html_path, "/rtc_room/room")
        self.create_path = _normalize_public_path(self.create_path, "/rtc_room/create")
        self.join_path = _normalize_public_path(self.join_path, "/rtc_room/join")
        self.test_audio_path = _normalize_public_path(self.test_audio_path, "/rtc_room/test-audio")
        self.admin_manage_path = _normalize_internal_suffix(self.admin_manage_path, "rtc_room/manage")
        self.admin_test_path = _normalize_internal_suffix(self.admin_test_path, "test/chatroom")
        self.admin_rooms_api_path = _normalize_internal_suffix(self.admin_rooms_api_path, "api/rooms")

    def apply_runtime_config(self) -> None:
        ChatRoomConfig.SetConfig(
            ChatRoomConfig(
                audio_config=self.audio_config,
                rtc_config=self.rtc_config,
            )
        )


class RTCRoomCreateTokenClaims(BaseModel):
    iss: Literal["proj-template"] = JWT_ISSUER
    sub: Literal["rtc-room-create"] = RTC_ROOM_CREATE_TOKEN_SUB
    jti: str
    iat: int
    exp: int
    room_type: str = "default"
    name: str | None = None
    description: str | None = None
    max_participants: int | None = None
    close_when_no_visible_candidate: bool | None = None
    close_room_on_creator_left: bool | None = None
    user_name: str | None = None
    candidate_id: str | None = None
    password: str | None = None
    is_public: bool = True


class RTCRoomJoinTokenClaims(BaseModel):
    iss: Literal["proj-template"] = JWT_ISSUER
    sub: Literal["rtc-room-join"] = RTC_ROOM_JOIN_TOKEN_SUB
    jti: str
    iat: int
    exp: int
    room_id: str
    password: str | None = None
    user_name: str | None = None
    candidate_id: str | None = None


class RTCRoomCreateRequest(AdvancedBaseModel):
    token: str
    sdp: str
    type: str
    room_type: str | None = None
    name: str | None = None
    description: str | None = None
    max_participants: int | None = None
    close_when_no_visible_candidate: bool | None = None
    close_room_on_creator_left: bool | None = None
    user_name: str | None = None
    candidate_id: str | None = None
    password: str | None = None


class RTCRoomJoinRequest(AdvancedBaseModel):
    token: str | None = None
    sdp: str
    type: str
    room_id: str | None = None
    password: str | None = None
    user_name: str | None = None
    candidate_id: str | None = None


class PaginatedRooms(AdvancedBaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int = 10


def _issue_claims_token(claims: BaseModel) -> str:
    return jwt.encode(claims.model_dump(mode="json"), get_private_key(), algorithm=JWT_ALG)


def _decode_claims_token(token: str, *, expected_sub: Literal["rtc-room-create", "rtc-room-join"]) -> dict[str, object]:
    try:
        decoded = jwt.decode(
            token,
            get_public_key(),
            algorithms=[JWT_ALG],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise JwtError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise JwtError(f"invalid token: {exc}") from exc
    if decoded.get("sub") != expected_sub:
        raise JwtError(f"token sub mismatch: expected {expected_sub}, got {decoded.get('sub')!r}")
    return decoded


def _raise_token_http_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, JwtError):
        raise HTTPException(401, str(exc)) from exc
    raise HTTPException(422, str(exc)) from exc


def _generate_private_room_password() -> str:
    return secrets.token_urlsafe(24)


def create_room_token(
    *,
    expire: int = 3600,
    room_type: str = "default",
    name: str | None = None,
    description: str | None = None,
    max_participants: int | None = None,
    close_when_no_visible_candidate: bool | None = None,
    close_room_on_creator_left: bool | None = None,
    user_name: str | None = None,
    candidate_id: str | None = None,
    password: str | None = None,
    is_public: bool = True,
) -> str:
    now = int(time.time())
    claims = RTCRoomCreateTokenClaims(
        jti=str(uuid.uuid4()),
        iat=now,
        exp=now + int(expire),
        room_type=room_type,
        name=name,
        description=description,
        max_participants=max_participants,
        close_when_no_visible_candidate=close_when_no_visible_candidate,
        close_room_on_creator_left=close_room_on_creator_left,
        user_name=user_name,
        candidate_id=candidate_id,
        password=password,
        is_public=is_public,
    )
    return _issue_claims_token(claims)


def create_room_invite_token(
    *,
    room_id: str,
    expire: int = 3600,
    password: str | None = None,
    user_name: str | None = None,
    candidate_id: str | None = None,
) -> str:
    now = int(time.time())
    claims = RTCRoomJoinTokenClaims(
        jti=str(uuid.uuid4()),
        iat=now,
        exp=now + int(expire),
        room_id=room_id,
        password=password,
        user_name=user_name,
        candidate_id=candidate_id,
    )
    return _issue_claims_token(claims)


def verify_room_create_token(token: str) -> RTCRoomCreateTokenClaims:
    return RTCRoomCreateTokenClaims.model_validate(
        _decode_claims_token(token, expected_sub=RTC_ROOM_CREATE_TOKEN_SUB)
    )


def verify_room_join_token(token: str) -> RTCRoomJoinTokenClaims:
    return RTCRoomJoinTokenClaims.model_validate(
        _decode_claims_token(token, expected_sub=RTC_ROOM_JOIN_TOKEN_SUB)
    )


def build_room_create_request(
    *,
    token: str,
    sdp: str,
    type: WebRTC_SDP_Type,
    room_type: str | None = None,
    name: str | None = None,
    description: str | None = None,
    max_participants: int | None = None,
    close_when_no_visible_candidate: bool | None = None,
    close_room_on_creator_left: bool | None = None,
    user_name: str | None = None,
    candidate_id: str | None = None,
    password: str | None = None,
) -> WebRTCRoomCreationRequest:
    try:
        claims = verify_room_create_token(token)
        resolved_password = claims.password if claims.password is not None else password
        if not claims.is_public and not resolved_password:
            resolved_password = _generate_private_room_password()
        resolved_close_when_no_visible_candidate = (
            claims.close_when_no_visible_candidate
            if claims.close_when_no_visible_candidate is not None
            else (close_when_no_visible_candidate if close_when_no_visible_candidate is not None else True)
        )
        resolved_close_room_on_creator_left = (
            claims.close_room_on_creator_left
            if claims.close_room_on_creator_left is not None
            else (close_room_on_creator_left if close_room_on_creator_left is not None else True)
        )
        payload = {
            "sdp": sdp,
            "type": type,
            "room_type": claims.room_type or room_type or "default",
            "name": claims.name if claims.name is not None else (name or "Room"),
            "description": claims.description if claims.description is not None else description,
            "max_participants": claims.max_participants if claims.max_participants is not None else max_participants,
            "close_when_no_visible_candidate": resolved_close_when_no_visible_candidate,
            "close_room_on_creator_left": resolved_close_room_on_creator_left,
            "user_name": claims.user_name if claims.user_name is not None else user_name,
            "candidate_id": claims.candidate_id if claims.candidate_id is not None else candidate_id,
            "password": resolved_password,
            "is_admin": True,
        }
        return WebRTCRoomCreationRequest.model_validate(payload)
    except (JwtError, ValidationError) as exc:
        _raise_token_http_error(exc)


def build_room_join_request(
    *,
    token: str | None,
    sdp: str,
    type: WebRTC_SDP_Type,
    room_id: str | None = None,
    password: str | None = None,
    user_name: str | None = None,
    candidate_id: str | None = None,
) -> WebRTCRoomJoinRequest:
    try:
        claims = verify_room_join_token(token) if token else None
        resolved_room_id = claims.room_id if claims is not None else room_id
        if not resolved_room_id:
            raise HTTPException(422, "room_id is required when join token is absent")
        payload = {
            "sdp": sdp,
            "type": type,
            "room_id": resolved_room_id,
            "password": claims.password if claims is not None and claims.password is not None else password,
            "user_name": claims.user_name if claims is not None and claims.user_name is not None else user_name,
            "candidate_id": claims.candidate_id if claims is not None and claims.candidate_id is not None else candidate_id,
        }
        return WebRTCRoomJoinRequest.model_validate(payload)
    except (JwtError, ValidationError, HTTPException) as exc:
        _raise_token_http_error(exc)


class WebRTCChatroomPlugin:
    Key: ClassVar[str] = PLUGIN_SHARED_ID
    Name: ClassVar[dict[str, str]] = {
        "zh-cn": "WebRTC Chatroom",
        "zh-tw": "WebRTC Chatroom",
        "en": "WebRTC Chatroom",
    }
    Type: ClassVar[Literal["worker-only"]] = "worker-only"
    Description: ClassVar[dict[str, str]] = {
        "zh-cn": "WebRTC 房间、管理面板与测试页插件。",
        "zh-tw": "WebRTC 房間、管理面板與測試頁插件。",
        "en": "WebRTC room, admin management, and test panel plugin.",
    }
    ConfigType: ClassVar[type[BaseModel]] = WebRTCChatroomPluginConfig

    def __init__(self, config: WebRTCChatroomPluginConfig):
        self.config = config
        self.shared = WebRTCChatroomSharedData(PLUGIN_SHARED_ID)

    @classmethod
    def Create(cls, create_in: str, config=None, core_module=None):
        resolved_config = config if isinstance(config, WebRTCChatroomPluginConfig) else WebRTCChatroomPluginConfig.model_validate(config or {})
        resolved_config.apply_runtime_config()
        return cls(resolved_config)

    def ensure_enabled(self) -> None:
        if not self.config.enabled:
            raise HTTPException(404, "RTC room service is disabled")

    def _admin_path(self, suffix: str) -> str:
        from core.server.data_types.config import Config

        return Config.GetConfig().server_config.get_internal_admin_path(suffix)

    def _room_urls(self) -> dict[str, str]:
        return {
            "room": self.config.room_html_path,
            "create": self.config.create_path,
            "join": self.config.join_path,
            "test_audio": self.config.test_audio_path,
        }

    def _room_urls_script(self) -> str:
        payload = json.dumps(self._room_urls(), ensure_ascii=False).replace("</", "<\\/")
        return (
            "<script data-webrtc-chatroom-urls>\n"
            "(function(){\n"
            f"  var urls = {payload};\n"
            "  window.__RTC_ROOM_URLS__ = Object.assign({}, window.__RTC_ROOM_URLS__ || {}, urls);\n"
            "})();\n"
            "</script>\n"
        )

    def _html_response_from_plugin_path(
        self,
        path: Path,
        *,
        not_found_message: str,
        with_mobile: bool = False,
    ) -> HTMLResponse:
        if not path.is_file():
            raise HTTPException(404, not_found_message)
        html = path.read_text(encoding="utf-8")
        if with_mobile:
            mobile_path = path.with_suffix(".m.html")
            if mobile_path.is_file():
                html = merge_desktop_mobile_html(html, mobile_path.read_text(encoding="utf-8"))
        html = self._room_urls_script() + html
        return html_response_from_content(
            html,
            source_path=path,
            cache_key=f"webrtc-chatroom:{path}:{with_mobile}:{json.dumps(self._room_urls(), sort_keys=True)}",
        )

    def _register_room_worker(self, room: WebRTCRoom) -> None:
        self.shared.update_room_worker(room.id, os.getpid())

        def _unregister() -> None:
            shutting_down = os.getenv("__APP_SHUTTING_DOWN__", "").strip().lower() in {"1", "true", "yes"}
            if not shutting_down:
                self.shared.delete_room_worker(room.id)

        room.add_on_close_callback(_unregister)

    def _pick_least_room_running_worker(self) -> int | None:
        active_worker_pids = self.shared.get_active_workers()
        worker_pids: list[int] = []
        for worker_pid in active_worker_pids:
            if self._worker_is_alive(worker_pid):
                worker_pids.append(worker_pid)
            else:
                self.shared.unregister_worker(worker_pid)
        if os.getpid() not in worker_pids:
            worker_pids.append(os.getpid())
        selected = self.shared.pick_worker(worker_pids, prefer_pid=os.getpid())
        logger.debug(
            "RTC room worker pick active=%s usable=%s selected=%s current=%s",
            active_worker_pids,
            worker_pids,
            selected,
            os.getpid(),
        )
        return selected

    def _worker_is_alive(self, worker_id: int) -> bool:
        from core.server.shared import get_worker_info

        info = get_worker_info(worker_id)
        if info is not None and not info.dead and info.msg_port > 0:
            return True
        if self.shared.get_worker_port(worker_id) is None:
            return False
        try:
            import psutil

            process = psutil.Process(int(worker_id))
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except Exception:
            try:
                os.kill(int(worker_id), 0)
                return True
            except Exception:
                return False

    @staticmethod
    def _worker_process_is_alive(worker_id: int) -> bool:
        try:
            import psutil

            process = psutil.Process(int(worker_id))
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except Exception:
            try:
                os.kill(int(worker_id), 0)
                return True
            except Exception:
                return False

    def _room_worker_unavailable(self, room_id: str, worker_id: int | None) -> bool:
        if worker_id is None or worker_id == os.getpid():
            return False
        if self.shared.get_worker_port(worker_id) is None:
            self.shared.unregister_worker(worker_id)
            self.shared.delete_room_worker(room_id)
            return True
        if not self._worker_process_is_alive(worker_id):
            self.shared.unregister_worker(worker_id)
            self.shared.delete_room_worker(room_id)
            return True
        return False

    @staticmethod
    def _is_worker_redirected_request(request: Request) -> bool:
        return request.headers.get("x-worker-redirected") == "1"

    @staticmethod
    def _is_stale_worker_redirect_error(exc: RuntimeError) -> bool:
        error_text = str(exc)
        return (
            "is not available for redirect" in error_text
            or "is no longer available for redirect" in error_text
            or "connection failed for redirect" in error_text
            or "did not respond within" in error_text
        )

    async def _create_rtc_room(self, data: RTCRoomCreateRequest, request: Request) -> WebRTCRoomCreationResponse:
        self.ensure_enabled()
        preferred_worker = None if self._is_worker_redirected_request(request) else self._pick_least_room_running_worker()
        if preferred_worker is not None and preferred_worker != os.getpid():
            preferred_worker_port = self.shared.get_worker_port(preferred_worker)
            try:
                return await redirect_to_worker(
                    preferred_worker,
                    request,
                    data.model_dump(mode="json"),
                    msg_port=preferred_worker_port,
                )
            except RuntimeError as exc:
                if not self._is_stale_worker_redirect_error(exc):
                    raise
                self.shared.unregister_worker(preferred_worker)
                logger.debug(
                    "RTC room worker redirect skipped target=%s current=%s error=%s",
                    preferred_worker,
                    os.getpid(),
                    exc,
                )

        create_request = build_room_create_request(
            token=data.token,
            sdp=data.sdp,
            type=data.type,  # type: ignore[arg-type]
            room_type=data.room_type,
            name=data.name,
            description=data.description,
            max_participants=data.max_participants,
            close_when_no_visible_candidate=data.close_when_no_visible_candidate,
            close_room_on_creator_left=data.close_room_on_creator_left,
            user_name=data.user_name,
            candidate_id=data.candidate_id,
            password=data.password,
        )
        client_ip = request.client.host if request.client else None
        room, _, response = await WebRTCRoom.Create(create_request, client_ip=client_ip)
        self._register_room_worker(room)
        return response

    async def _join_rtc_room(self, data: RTCRoomJoinRequest, request: Request) -> WebRTCRoomJoinResponse:
        self.ensure_enabled()
        join_request = build_room_join_request(
            token=data.token,
            sdp=data.sdp,
            type=data.type,  # type: ignore[arg-type]
            room_id=data.room_id,
            password=data.password,
            user_name=data.user_name,
            candidate_id=data.candidate_id,
        )
        worker_id = self.shared.get_room_worker(join_request.room_id)
        if self._room_worker_unavailable(join_request.room_id, worker_id):
            worker_id = None
        if worker_id is not None and worker_id != os.getpid():
            try:
                return await redirect_to_worker(
                    worker_id,
                    request,
                    data.model_dump(mode="json"),
                    msg_port=self.shared.get_worker_port(worker_id),
                )
            except RuntimeError as exc:
                if not self._is_stale_worker_redirect_error(exc):
                    raise
                self.shared.unregister_worker(worker_id)
                self.shared.delete_room_worker(join_request.room_id)
                raise HTTPException(404, f"Room not found: {join_request.room_id}") from exc

        room = WebRTCRoom.GetRoom(join_request.room_id)
        if room is None:
            raise HTTPException(404, f"Room not found: {join_request.room_id}")
        client_ip = request.client.host if request.client else None
        _, response = await WebRTCRoom.Join(join_request, client_ip=client_ip)
        return response

    def _register_routes(self, app: FastAPI) -> None:
        state_key = f"_{self.Key}_routes_registered"
        if getattr(app.state, state_key, False):
            return
        setattr(app.state, state_key, True)

        rooms_api_path = self._admin_path(self.config.admin_rooms_api_path)
        room_manage_path = self._admin_path(self.config.admin_manage_path)
        room_manage_asset_base_path = room_manage_path.rsplit("/", 1)[0]
        room_test_path = self._admin_path(self.config.admin_test_path)
        room_page_path = self.config.room_html_path
        room_create_path = self.config.create_path
        room_join_path = self.config.join_path
        room_test_audio_path = self.config.test_audio_path

        @app.get(self.config.public_component_html_path, response_class=HTMLResponse, include_in_schema=False)
        async def webrtc_chatroom_public_room_html() -> HTMLResponse:
            self.ensure_enabled()
            return self._html_response_from_plugin_path(
                ROOM_HTML_FILE,
                not_found_message="webrtc-chatroom/public/rtc_room.html not found",
            )

        @app.get(self.config.public_component_mobile_html_path, response_class=HTMLResponse, include_in_schema=False)
        async def webrtc_chatroom_public_room_mobile_html() -> HTMLResponse:
            self.ensure_enabled()
            return self._html_response_from_plugin_path(
                ROOM_MOBILE_HTML_FILE,
                not_found_message="webrtc-chatroom/public/rtc_room.m.html not found",
            )

        @app.get(room_test_audio_path + "/{filename}")
        async def webrtc_chatroom_test_audio(filename: str) -> FileResponse:
            self.ensure_enabled()
            path = get_resources("test", filename)
            if path is None or not path.is_file():
                raise HTTPException(404, "Not found")
            return FileResponse(path, media_type="audio/mpeg")

        @app.post(room_create_path, response_model=WebRTCRoomCreationResponse)
        async def webrtc_chatroom_create(data: RTCRoomCreateRequest, request: Request) -> WebRTCRoomCreationResponse:
            return await self._create_rtc_room(data, request)

        @app.post(room_join_path, response_model=WebRTCRoomJoinResponse)
        async def webrtc_chatroom_join(data: RTCRoomJoinRequest, request: Request) -> WebRTCRoomJoinResponse:
            return await self._join_rtc_room(data, request)

        @app.get(room_page_path, response_class=HTMLResponse)
        async def webrtc_chatroom_room_html() -> HTMLResponse:
            self.ensure_enabled()
            return self._html_response_from_plugin_path(
                ROOM_HTML_FILE,
                not_found_message="webrtc-chatroom/public/rtc_room.html not found",
                with_mobile=True,
            )

        @app.get(room_manage_path, response_class=HTMLResponse)
        async def webrtc_chatroom_room_manage_html() -> HTMLResponse:
            return self._html_response_from_plugin_path(
                ROOM_MANAGE_HTML_FILE,
                not_found_message="webrtc-chatroom/admin/room_manage.html not found",
            )

        @app.get(room_manage_asset_base_path + "/rtc-ui-shared.css", include_in_schema=False)
        async def webrtc_chatroom_room_manage_css() -> FileResponse:
            if not ROOM_MANAGE_CSS_FILE.is_file():
                raise HTTPException(404, "webrtc-chatroom/admin/rtc-ui-shared.css not found")
            return FileResponse(ROOM_MANAGE_CSS_FILE, media_type="text/css")

        @app.get(room_test_path, response_class=HTMLResponse)
        async def webrtc_chatroom_room_test_html() -> HTMLResponse:
            return self._html_response_from_plugin_path(
                ROOM_TEST_HTML_FILE,
                not_found_message="webrtc-chatroom/admin/test_chatroom.html not found",
            )

        @app.get(rooms_api_path, response_model=PaginatedRooms)
        async def webrtc_chatroom_list_rooms(
            page: int = Query(1, ge=1),
            page_size: int = Query(10, ge=1, le=100),
        ) -> PaginatedRooms:
            all_rooms = []
            for room in self.shared.get_all_room_info():
                room_id = str(room.get("id") or "")
                worker_id = int(room.get("worker") or 0)
                if room_id and worker_id and self._room_worker_unavailable(room_id, worker_id):
                    continue
                all_rooms.append(room)
            total = len(all_rooms)
            start = (page - 1) * page_size
            items = [dict(room) for room in all_rooms[start : start + page_size]]
            return PaginatedRooms(items=items, total=total, page=page, page_size=page_size)

        @app.get(rooms_api_path + "/{room_id}", response_model=RoomInfo)
        async def webrtc_chatroom_get_room_detail(room_id: str, request: Request) -> RoomInfo:
            worker_id = self.shared.get_room_worker(room_id)
            if self._room_worker_unavailable(room_id, worker_id):
                worker_id = None
            if worker_id is None:
                raise HTTPException(404, f"Room not found: {room_id}")
            if worker_id != os.getpid():
                try:
                    return await redirect_to_worker(
                        worker_id,
                        request,
                        {"room_id": room_id},
                        msg_port=self.shared.get_worker_port(worker_id),
                        timeout=2.0,
                    )
                except RuntimeError as exc:
                    if not self._is_stale_worker_redirect_error(exc):
                        raise
                    self.shared.unregister_worker(worker_id)
                    self.shared.delete_room_worker(room_id)
                    raise HTTPException(404, f"Room not found: {room_id}") from exc
            room = WebRTCRoom.GetRoom(room_id)
            if room is None:
                self.shared.delete_room_worker(room_id)
                raise HTTPException(404, f"Room not found: {room_id}")
            return room.dump_info()

        @app.delete(rooms_api_path + "/{room_id}")
        async def webrtc_chatroom_delete_room(room_id: str, request: Request) -> dict[str, object]:
            worker_id = self.shared.get_room_worker(room_id)
            if self._room_worker_unavailable(room_id, worker_id):
                worker_id = None
            if worker_id is None:
                raise HTTPException(404, f"Room not found: {room_id}")
            if worker_id != os.getpid():
                try:
                    return await redirect_to_worker(
                        worker_id,
                        request,
                        {"room_id": room_id},
                        msg_port=self.shared.get_worker_port(worker_id),
                        timeout=2.0,
                    )
                except RuntimeError as exc:
                    if not self._is_stale_worker_redirect_error(exc):
                        raise
                    self.shared.unregister_worker(worker_id)
                    self.shared.delete_room_worker(room_id)
                    raise HTTPException(404, f"Room not found: {room_id}") from exc
            room = WebRTCRoom.GetRoom(room_id)
            if room is None:
                self.shared.delete_room_worker(room_id)
                raise HTTPException(404, f"Room not found: {room_id}")
            await room.close()
            self.shared.delete_room_worker(room_id)
            return {"ok": True, "id": room_id}

    async def on_app_start(self, app: FastAPI) -> None:
        self.config.apply_runtime_config()
        from core.server.shared import AppSharedData

        try:
            msg_port = AppSharedData.Get().get_worker(os.getpid()).msg_port
        except Exception:
            msg_port = None
        self.shared.register_worker(os.getpid(), msg_port=msg_port)
        logger.debug(
            "RTC room worker registered pid=%s port=%s active=%s",
            os.getpid(),
            msg_port,
            self.shared.get_active_workers(),
        )
        self._register_routes(app)

    async def on_app_shutdown(self, app: FastAPI) -> None:
        try:
            await close_all_rooms()
        finally:
            try:
                self.shared.unregister_worker(os.getpid())
            except Exception:
                pass

    async def admin_panel(self) -> str:
        manage_path = escape("/admin/" + self.config.admin_manage_path, quote=True)
        test_path = escape("/admin/" + self.config.admin_test_path, quote=True)
        title = escape(self.Name.get("zh-cn", "WebRTC Chatroom"), quote=True)
        plugin_key = escape(get_plugin_key(self.__class__), quote=True)
        return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; }}
        html, body {{ margin: 0; height: 100%; min-height: 100%; font-family: \"Segoe UI\", \"PingFang SC\", \"Microsoft YaHei\", sans-serif; }}
        body {{ min-height: 100dvh; overflow: hidden; background: #eef3f8; color: #102033; }}
        .shell {{ height: 100%; min-height: 100dvh; display: grid; grid-template-columns: 220px minmax(0, 1fr); }}
    .side {{ padding: 20px 16px; background: linear-gradient(180deg, rgba(15,23,42,0.96), rgba(30,41,59,0.96)); color: #e2e8f0; border-right: 1px solid rgba(148,163,184,0.18); box-sizing: border-box; }}
    .kicker {{ font-size: 11px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; color: #94a3b8; }}
    .title {{ margin-top: 10px; font-size: 24px; font-weight: 700; }}
    .desc {{ margin-top: 10px; font-size: 13px; line-height: 1.7; color: #cbd5e1; }}
    .nav {{ margin-top: 18px; display: grid; gap: 8px; }}
    .nav button {{ width: 100%; border: 0; border-radius: 14px; padding: 12px 14px; text-align: left; background: rgba(148,163,184,0.12); color: inherit; cursor: pointer; font-size: 13px; font-weight: 600; transition: background-color 0.16s ease, transform 0.16s ease; }}
    .nav button:hover {{ background: rgba(99,102,241,0.28); transform: translateX(2px); }}
    .nav button.active {{ background: linear-gradient(135deg, rgba(79,70,229,0.9), rgba(56,189,248,0.8)); color: #fff; }}
        .content {{ min-width: 0; min-height: 0; display: flex; flex-direction: column; background: radial-gradient(circle at top right, rgba(59,130,246,0.12), transparent 32%), #f8fafc; }}
    .toolbar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 18px 22px; border-bottom: 1px solid rgba(148,163,184,0.2); background: rgba(255,255,255,0.74); backdrop-filter: blur(16px); }}
    .toolbar h1 {{ margin: 0; font-size: 18px; font-weight: 700; color: #0f172a; }}
    .toolbar span {{ font-size: 12px; color: #64748b; }}
        iframe {{ flex: 1 1 auto; width: 100%; min-height: 0; border: 0; display: block; background: transparent; }}
    html.dark body {{ background: #020617; color: #e2e8f0; }}
    html.dark .content {{ background: radial-gradient(circle at top right, rgba(59,130,246,0.18), transparent 32%), #0f172a; }}
    html.dark .toolbar {{ background: rgba(15,23,42,0.72); border-bottom-color: rgba(148,163,184,0.12); }}
    html.dark .toolbar h1 {{ color: #f8fafc; }}
    html.dark .toolbar span {{ color: #94a3b8; }}
    @media (max-width: 900px) {{ .shell {{ grid-template-columns: 1fr; }} .side {{ border-right: 0; border-bottom: 1px solid rgba(148,163,184,0.18); }} }}
  </style>
</head>
<body>
  <div class=\"shell\" data-plugin-key=\"{plugin_key}\">
    <aside class=\"side\">
    <div class=\"kicker\">插件</div>
      <div class=\"title\">WebRTC Chatroom</div>
      <div class=\"desc\">房间管理与联调测试已移动到插件内部，和房间 API 一起由插件接管。</div>
      <div class=\"nav\">
        <button type=\"button\" class=\"active\" data-view-url=\"{manage_path}\">房间管理</button>
        <button type=\"button\" data-view-url=\"{test_path}\">聊天测试</button>
      </div>
    </aside>
    <section class=\"content\">
      <div class=\"toolbar\">
        <div>
          <h1 id=\"plugin-panel-title\">房间管理</h1>
          <span id=\"plugin-panel-subtitle\">webrtc-chatroom</span>
        </div>
      </div>
      <iframe id=\"plugin-panel-frame\" src=\"{manage_path}\"></iframe>
    </section>
  </div>
  <script>
    (function() {{
      var buttons = Array.from(document.querySelectorAll('.nav button'));
      var frame = document.getElementById('plugin-panel-frame');
      var title = document.getElementById('plugin-panel-title');
      function select(button) {{
        if (!button || !frame) return;
        buttons.forEach(function(item) {{ item.classList.toggle('active', item === button); }});
        frame.src = button.getAttribute('data-view-url') || 'about:blank';
        title.textContent = button.textContent || 'WebRTC Chatroom';
      }}
      buttons.forEach(function(button) {{
        button.addEventListener('click', function() {{ select(button); }});
      }});
      window.addEventListener('message', function(event) {{
        var data = event && event.data;
        if (!data || typeof data !== 'object') return;
        if (data.type === 'proj-sync' || data.type === 'proj-set-dark') {{
          document.documentElement.classList.toggle('dark', !!data.dark);
        }}
      }});
    }})();
  </script>
</body>
</html>"""


__all__ = [
    "PLUGIN_SHARED_ID",
    "RTC_ROOM_CREATE_TOKEN_SUB",
    "RTC_ROOM_JOIN_TOKEN_SUB",
    "RTCRoomCreateRequest",
    "RTCRoomCreateTokenClaims",
    "RTCRoomJoinRequest",
    "RTCRoomJoinTokenClaims",
    "WebRTCChatroomPlugin",
    "WebRTCChatroomPluginConfig",
    "build_room_create_request",
    "build_room_join_request",
    "create_room_invite_token",
    "create_room_token",
    "verify_room_create_token",
    "verify_room_join_token",
]
