import secrets
import time
import uuid

from typing import TYPE_CHECKING, Literal

import jwt
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from core.rtc_chat.room import WebRTCRoomCreationRequest, WebRTCRoomJoinRequest, WebRTC_SDP_Type
from core.server.security.jwt import JWT_ALG, JWT_ISSUER, JwtError, get_private_key, get_public_key

if TYPE_CHECKING:
    from core.server.data_types.config import Config


RTC_ROOM_COMPONENT_HTML_PATH = "/shared/components/rtc_room.html"
RTC_ROOM_COMPONENT_MOBILE_HTML_PATH = "/shared/components/rtc_room.m.html"
RTC_ROOM_CREATE_TOKEN_SUB = "rtc-room-create"
RTC_ROOM_JOIN_TOKEN_SUB = "rtc-room-join"


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
    return RTCRoomCreateTokenClaims.model_validate(_decode_claims_token(token, expected_sub=RTC_ROOM_CREATE_TOKEN_SUB))


def verify_room_join_token(token: str) -> RTCRoomJoinTokenClaims:
    return RTCRoomJoinTokenClaims.model_validate(_decode_claims_token(token, expected_sub=RTC_ROOM_JOIN_TOKEN_SUB))


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


def is_rtc_room_enabled(config: "Config | None" = None) -> bool:
    from core.server.data_types.config import Config

    cfg = config or Config.GetConfig()
    return bool(cfg.server_config.enable_rtc_chatroom)


def ensure_rtc_room_enabled(config: "Config | None" = None) -> None:
    if not is_rtc_room_enabled(config):
        raise HTTPException(404, "RTC room service is disabled")


def is_rtc_room_public_path(path: str) -> bool:
    normalized = "/" + str(path or "").lstrip("/")
    return normalized in {
        RTC_ROOM_COMPONENT_HTML_PATH,
        RTC_ROOM_COMPONENT_MOBILE_HTML_PATH,
    }


__all__ = [
    "RTC_ROOM_COMPONENT_HTML_PATH",
    "RTC_ROOM_COMPONENT_MOBILE_HTML_PATH",
    "RTC_ROOM_CREATE_TOKEN_SUB",
    "RTC_ROOM_JOIN_TOKEN_SUB",
    "RTCRoomCreateTokenClaims",
    "RTCRoomJoinTokenClaims",
    "is_rtc_room_enabled",
    "ensure_rtc_room_enabled",
    "is_rtc_room_public_path",
    "create_room_token",
    "create_room_invite_token",
    "verify_room_create_token",
    "verify_room_join_token",
    "build_room_create_request",
    "build_room_join_request",
]