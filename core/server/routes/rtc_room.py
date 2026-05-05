import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from core.constants import PUBLIC_DIR
from core.rtc_chat.room import WebRTCRoom, WebRTCRoomCreationResponse, WebRTCRoomJoinResponse
from core.utils.type_utils import AdvancedBaseModel

from ..app import get_resources, internal_path, on_before_app_created, redirect_to_worker
from ..html_injection import html_response_from_path_with_mobile
from ..rtc_room import build_room_create_request, build_room_join_request, ensure_rtc_room_enabled
from ..shared import AppSharedData


RTC_ROOM_COMPONENT_FILE = PUBLIC_DIR / "shared" / "components" / "rtc_room.html"


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


def _register_room_worker(room: WebRTCRoom) -> None:
    shared = AppSharedData.Get()
    shared.update_room_worker(room.id, os.getpid())

    def _unregister() -> None:
        shutting_down = os.getenv("__APP_SHUTTING_DOWN__", "").strip().lower() in {"1", "true", "yes"}
        if not shutting_down:
            shared.delete_room_worker(room.id)

    room.add_on_close_callback(_unregister)


@on_before_app_created
def register_rtc_room_routes(app: FastAPI) -> None:
    rtc_path = lambda path: internal_path(f"rtc_room/{path}")

    @app.get(rtc_path("test-audio/{filename}"))
    async def serve_test_audio(filename: str) -> FileResponse:
        ensure_rtc_room_enabled()
        path = get_resources("test", filename)
        if path is None or not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="audio/mpeg")

    @app.post(rtc_path("create"), response_model=WebRTCRoomCreationResponse)
    async def create_rtc_room(data: RTCRoomCreateRequest, request: Request) -> WebRTCRoomCreationResponse:
        return await _create_rtc_room(data, request)

    @app.post(rtc_path("join"), response_model=WebRTCRoomJoinResponse)
    async def join_rtc_room(data: RTCRoomJoinRequest, request: Request) -> WebRTCRoomJoinResponse:
        return await _join_rtc_room(data, request)

    @app.get(rtc_path("room"), response_class=HTMLResponse)
    async def room_html() -> HTMLResponse:
        ensure_rtc_room_enabled()
        return html_response_from_path_with_mobile(
            RTC_ROOM_COMPONENT_FILE,
            not_found_message="shared/components/rtc_room.html not found",
        )


async def _create_rtc_room(data: RTCRoomCreateRequest, request: Request) -> WebRTCRoomCreationResponse:
    ensure_rtc_room_enabled()
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
    _register_room_worker(room)
    return response


async def _join_rtc_room(data: RTCRoomJoinRequest, request: Request) -> WebRTCRoomJoinResponse:
    ensure_rtc_room_enabled()
    join_request = build_room_join_request(
        token=data.token,
        sdp=data.sdp,
        type=data.type,  # type: ignore[arg-type]
        room_id=data.room_id,
        password=data.password,
        user_name=data.user_name,
        candidate_id=data.candidate_id,
    )
    shared = AppSharedData.Get()
    worker_id = shared.get_room_worker(join_request.room_id)
    if worker_id is not None and worker_id != os.getpid():
        return await redirect_to_worker(worker_id, request, data.model_dump(mode="json"))

    room = WebRTCRoom.GetRoom(join_request.room_id)
    if room is None:
        raise HTTPException(404, f"Room not found: {join_request.room_id}")
    client_ip = request.client.host if request.client else None
    _, response = await WebRTCRoom.Join(join_request, client_ip=client_ip)
    return response


__all__ = ["register_rtc_room_routes"]