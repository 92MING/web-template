import os
import asyncio
import logging
import inspect

from abc import ABC
from uuid import uuid4
from enum import StrEnum
from datetime import datetime
from fastapi import HTTPException
from threading import Lock
from weakref import WeakValueDictionary
from aiortc import RTCSessionDescription
from typing import TYPE_CHECKING, Unpack, ClassVar, Literal, TypeVar, Any, Self, Callable, Awaitable
from pydantic import field_validator, ValidationError, Field, computed_field, SerializeAsAny

from core.utils.concurrent_utils import run_any_func

from .candidate import Candidate, _CandidateInitParams, UserCandidate
from .config import _AutoDocstringModel


# region data types
class CandidateInfo(_AutoDocstringModel):
    id: str
    '''candidate id'''
    name: str|None = None
    '''用户名称(不是unique)'''
    join_time: datetime = Field(default_factory=datetime.now)
    '''加入时间'''
    is_admin: bool = False
    '''是否为管理员用户'''
    muted: bool = False
    ''''是否静音'''
    muted_by: str|None = None
    '''若非None, 表示该用户被管理员强制静音, 值为管理员candidate id.'''
    deafen: bool = False
    '''是否全听'''
    cam_on: bool = True
    '''是否开启摄像头'''
    reaction: str|None = None
    '''用户的reaction'''
    ip: str|None = None
    '''用户的IP地址'''
    
class RoomInfo(_AutoDocstringModel):
    '''这个房间这个时刻的基本信息.'''
    id: str
    '''房间ID'''
    worker: int = Field(default_factory=os.getpid)
    '''正在处理这个房间的worker的pid.'''
    creator: str|None = None
    '''房间创建者的与会者ID.'''
    name: str | None = None
    '''房间名称'''
    description: str | None = None
    '''房间描述'''
    password: str | None = None
    '''房间访问密码'''
    max_participants: int | None = None
    '''房间最大参与人数'''
    start_time: datetime = Field(default_factory=datetime.now)
    '''房间创建时间'''
    candidates: dict[str, CandidateInfo] = Field(default_factory=dict)
    '''房间内的与会者列表'''

    @computed_field
    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

type WebRTC_SDP_Type = Literal["offer", "pranswer", "answer", "rollback"]

def _default_pw_validator(v):
    if isinstance(v, str):
        if not v:
            return None
        assert 1 <= len(v) <= 64, "Password length must be between 1 and 64 characters"
    return v

class _WebRTC_SDP_Data(_AutoDocstringModel):
    sdp: str
    '''SDP描述.'''
    type: WebRTC_SDP_Type

class WebRTCRoomCreationRequest(_WebRTC_SDP_Data):
    '''房间创建请求的参数模型.'''
    room_type: str = 'default'
    '''房间类型.'''
    
    # room configs
    name: str
    '''房间名称.'''
    password: str|None = None
    '''房间访问密码.'''
    description: str|None = None
    '''房间描述'''
    max_participants: int|None = None
    '''房间最大参与人数.'''
    close_when_no_visible_candidate: bool = True
    '''当房间内没有可见的candidate时是否自动关闭房间.'''
    close_room_on_creator_left: bool = True
    '''当房间创建者离开时是否自动关闭房间.'''
    
    user_name: str|None = None
    '''用户名称(不是unique)'''
    candidate_id: str|None = None
    '''唯一的candidate id.'''
    is_admin: bool = True
    '''是否为管理员用户'''

    @field_validator("password", mode="before")
    @classmethod
    def ValidatePassword(cls, v):
        return _default_pw_validator(v)
    
    def to_user_candidate_init_params(self) -> dict[str, Any]:
        return {
            'id': self.candidate_id,
            'name': self.user_name,
            'is_admin': self.is_admin,
        }
    
    def to_room_init_param(self, room_type: type['WebRTCRoom']) -> dict[str, Any]:
        data = self.model_dump()
        room_cls_anno = getattr(room_type, '__annotations__', {})
        possible_keys = set(room_cls_anno.keys())
        room_cls_init = getattr(room_type, '__init__', None)
        init_params = inspect.signature(room_cls_init).parameters # type: ignore
        has_kwargs = False
        for i, p in enumerate(init_params.values()):
            if i == 0:
                continue
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                has_kwargs = True
                break
            possible_keys.add(p.name)
        if has_kwargs:
            return data
        for k in tuple(data.keys()):
            if k not in possible_keys:
                data.pop(k)
        return data

    async def crate_room(self)->tuple["WebRTCRoom", "UserCandidate", 'WebRTCRoomCreationResponse']:
        '''alias of `WebRTCRoom.Create`.'''
        if not (room_cls := WebRTCRoom.GetRoomClass(self.room_type)):
            raise ValueError(f"Unknown room type: {self.room_type}")
        return await room_cls.Create(self)

class WebRTCRoomCreationResponse(_WebRTC_SDP_Data):
    '''房间创建响应.'''
    room_info: SerializeAsAny[RoomInfo]
    candidate_info: SerializeAsAny[CandidateInfo]
    track_map: dict[str, dict[str, str]] = {}

class WebRTCRoomNoUserCreationRequest(_AutoDocstringModel):
    '''在不创建初始用户的情况下创建一个空白的房间.'''
    room_type: str = 'default'
    name: str
    password: str|None = None
    description: str|None = None
    max_participants: int|None = None
    close_when_no_visible_candidate: bool = True
    close_room_on_creator_left: bool = True
    
    def to_room_init_param(self, room_type: type['WebRTCRoom']) -> dict[str, Any]:
        data = self.model_dump()
        room_cls_anno = getattr(room_type, '__annotations__', {})
        possible_keys = set(room_cls_anno.keys())
        room_cls_init = getattr(room_type, '__init__', None)
        init_params = inspect.signature(room_cls_init).parameters # type: ignore
        has_kwargs = False
        for i, p in enumerate(init_params.values()):
            if i == 0:
                continue
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                has_kwargs = True
                break
            possible_keys.add(p.name)
        if has_kwargs:
            return data
        for k in tuple(data.keys()):
            if k not in possible_keys:
                data.pop(k)
        return data
    
    def create_room(self)->tuple["WebRTCRoom", 'WebRTCRoomNoUserCreationResponse']:
        if not (room_cls := WebRTCRoom.GetRoomClass(self.room_type)):
            raise ValueError(f"Unknown room type: {self.room_type}")
        return room_cls.NoUserCreate(self)
    
class WebRTCRoomNoUserCreationResponse(_AutoDocstringModel):
    '''无用户创建房间的响应.'''
    room_info: SerializeAsAny[RoomInfo]
    
class WebRTCRoomJoinRequest(_WebRTC_SDP_Data):
    '''房间加入请求.'''
    room_id: str
    password: str|None = None
    user_name: str|None = None
    candidate_id: str|None = None
    
    @field_validator("password", mode="before")
    @classmethod
    def ValidatePassword(cls, v):
        return _default_pw_validator(v)
    
    def to_user_candidate_init_params(self) -> dict[str, Any]:
        return {
            'id': self.candidate_id,
            'name': self.user_name,
            'is_admin': False,
        }

class WebRTCRoomJoinResponse(_WebRTC_SDP_Data):
    room_info: SerializeAsAny[RoomInfo]
    candidate_info: SerializeAsAny[CandidateInfo]
    track_map: dict[str, dict[str, str]] = {}
    
__all__ = [
    'CandidateInfo',
    'RoomInfo',
    "WebRTC_SDP_Type",
    "WebRTCRoomCreationRequest",
    "WebRTCRoomCreationResponse",
    "WebRTCRoomNoUserCreationRequest",
    "WebRTCRoomNoUserCreationResponse",
    "WebRTCRoomJoinRequest",
    "WebRTCRoomJoinResponse",
]
# endregion

# region room
_all_room_classes: dict[str, type["WebRTCRoom"]] = {}
_all_rooms: WeakValueDictionary[str, "WebRTCRoom"] = WeakValueDictionary()

if TYPE_CHECKING:
    class _AllowExtraCandidateInitParams(_CandidateInitParams, extra_items=Any): ...
else:
    _AllowExtraCandidateInitParams = _CandidateInitParams

class DefaultRoomCreationError(StrEnum):
    RoomTypeNotFound = "ROOM_TYPE_NOT_FOUND"
    InvalidCreationParams = "INVALID_CREATION_PARAMS"
    InvalidJoinParams = "INVALID_JOIN_PARAMS"
    FailToCreateCandidate = "FAILED_TO_CREATE_CANDIDATE"
    FailedToCreateAnswer = "FAILED_TO_CREATE_ANSWER"

class WebRTCRoom[
    CreateT: WebRTCRoomCreationRequest,
    NoUserCreateT: WebRTCRoomNoUserCreationRequest,
    JoinT: WebRTCRoomJoinRequest,
](ABC):
    '''后端一对多RTC连接的管理类.'''
    
    id: str
    name: str|None = None
    description: str|None = None
    password: str|None = None
    max_participants: int|None = None
    start_time: datetime
    creator: str|None = None
    
    candidates: dict[str, Candidate]
    on_close_callbacks: list[Callable[[Self], Any]|Callable[[], Any]]
    close_when_no_visible_candidate: bool = True
    close_room_on_creator_left: bool = True
    
    _closed: bool = False
    _close_lock: Lock
    _loop: asyncio.Task|None = None
    
    if TYPE_CHECKING:
        ClassKey: ClassVar[str] = 'default'
        CreationParamType: type[CreateT]
        NoUserCreationParamType: type[NoUserCreateT]
        JoinParamType: type[JoinT]
    
    # region magic methods
    def __init__(
        self, 
        id: str|None=None,
        name: str|None = None,
        description: str|None = None,
        password: str|None = None,
        max_participants: int|None = None,
        close_when_no_visible_candidate: bool = True,
        close_room_on_creator_left: bool = True,
    ):
        self.id = id or str(uuid4())
        self.name = name
        self.description = description
        self.start_time = datetime.now()
        self.password = password
        self.max_participants = max_participants
        self.on_close_callbacks = []
        self.candidates = {}
        self.close_when_no_visible_candidate = close_when_no_visible_candidate
        self.close_room_on_creator_left = close_room_on_creator_left
        
        self.creator = None
        self.logger = logging.getLogger(f"{self.__class__.__name__}-{self.id.split('-')[0]}")
        self._loop = None
        self._closed = False
        self._close_lock = Lock()
        _all_rooms[self.id] = self
        
    def __del__(self):
        try:
            run_any_func(self.close)
        except:
            pass
    
    def __init_subclass__(cls, key: str, **kwargs):
        super().__init_subclass__(**kwargs)
        def get_cls_args(c):
            if c == WebRTCRoom:
                return WebRTCRoom.__type_params__
            else:
                super_base_args = get_cls_args(c.__bases__[0]) 
                c_type_params = c.__type_params__  
                super_args = c.__orig_bases__[0].__args__   
                super_type_params = c.__bases__[0].__type_params__
                super_type_map = dict(zip(super_type_params, super_args))
                tidied = []
                for a in super_base_args:
                    if isinstance(a, TypeVar):
                        tidied.append(super_type_map.pop(a))
                    else:
                        tidied.append(a)
                for a in c_type_params:
                    if a not in tidied:
                        tidied.append(a)
                return tidied
            
        cls_generic_args = get_cls_args(cls)
        if cls_generic_args:
            ct = cls_generic_args[0]
            nu_ct = cls_generic_args[1] if len(cls_generic_args) > 1 else WebRTCRoomNoUserCreationRequest
            jt = cls_generic_args[2] if len(cls_generic_args) > 2 else WebRTCRoomJoinRequest
            if isinstance(ct, TypeVar):
                cls.CreationParamType = WebRTCRoomCreationRequest   # type: ignore
            else:
                cls.CreationParamType = ct   # type: ignore
            if isinstance(nu_ct, TypeVar):
                cls.NoUserCreationParamType = WebRTCRoomNoUserCreationRequest   # type: ignore
            else:
                cls.NoUserCreationParamType = nu_ct   # type: ignore
            if isinstance(jt, TypeVar):
                cls.JoinParamType = WebRTCRoomJoinRequest   # type: ignore
            else:
                cls.JoinParamType = jt   # type: ignore
        else:
            cls.CreationParamType = WebRTCRoomCreationRequest   # type: ignore
            cls.JoinParamType = WebRTCRoomJoinRequest   # type: ignore
            
        key = key.strip()
        assert key and key not in _all_room_classes, f"Room class key '{key}' is already registered"
        cls.ClassKey = key
        _all_room_classes[key] = cls
    # endregion
    
    # region public methods    
    async def start(self):
        async def run():
            while not self._closed:
                await self.loop_once()
        self._loop = asyncio.create_task(run())
    
    async def loop_once(self):
        async def run_candidate_loop(candidate: Candidate):
            try:
                await candidate.loop_once()
            except Exception as e:
                self.logger.error(f"Error in candidate {candidate.id} loop: {e}", exc_info=True)
        coros = []
        for c in self.candidates.values():
            if not c.disabled:
                coros.append(run_candidate_loop(c))
        if coros:
            await asyncio.gather(*coros)
        else:
            await asyncio.sleep(0.01)
    
    async def _close_callback(self):
        if self.on_close_callbacks:
            coros = []
            for cb in self.on_close_callbacks:
                func_param_count = len(inspect.signature(cb).parameters)
                try:
                    if func_param_count == 0:
                        r = cb()    # type: ignore
                    else:
                        r = cb(self)    # type: ignore
                    if isinstance(r, Awaitable):
                        coros.append(r)
                except Exception as e:
                    self.logger.error(f"Error in on_close callback {cb}: {e}", exc_info=True)
            if coros:
                await asyncio.gather(*coros)
    
    async def close(self):
        '''关闭房间, 断开所有连接并清理资源.'''
        if not self._closed:
            self._closed = True
            if self._close_lock.locked():
                return
            with self._close_lock:
                await self._close_callback()
                if self._loop and not self._loop.done():
                    self._loop.cancel()
                    try:
                        await self._loop
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

                async def _safe_close_candidate(candidate: Candidate):
                    try:
                        await asyncio.wait_for(candidate.close(), timeout=1.5)
                    except Exception:
                        pass

                try:
                    await asyncio.gather(*(_safe_close_candidate(candidate) for candidate in tuple(self.candidates.values())), return_exceptions=True)
                except:
                    pass
                _all_rooms.pop(self.id, None)
    
    def get_candidate(self, candidate_id: str) -> Candidate|None:
        return self.candidates.get(candidate_id)
    
    async def add_candidate[_T: Candidate](
        self, 
        candidate_type: type[_T],
        **kwargs: Unpack[_AllowExtraCandidateInitParams]
    ) -> _T:
        candidate = candidate_type(room=self, **kwargs)  # type: ignore
        self.candidates[candidate.id] = candidate   
        await candidate.start()
        self.logger.info(f"Candidate {candidate} added to room.")
        return candidate
    
    def dump_info(self) -> RoomInfo:
        candidates_info = {cid: c.dump_info() for cid, c in self.candidates.items()}
        return RoomInfo(
            id=self.id,
            creator=self.creator,
            name=self.name,
            description=self.description,
            password=self.password,
            max_participants=self.max_participants,
            start_time=self.start_time,
            candidates=candidates_info,
        )
    
    def add_on_close_callback(self, callback: Callable[[Self], Any]|Callable[[], Any]):
        self.on_close_callbacks.append(callback)
    # endregion
    
    # region class methods
    @staticmethod
    def GetRoomClass(key: str) -> type["WebRTCRoom"]|None:
        return _all_room_classes.get(key.strip())      # type: ignore
    
    @classmethod
    def ValidateCreationParams(cls, params: dict[str, Any]|str) -> CreateT|None:
        try:
            if isinstance(params, str):
                return cls.CreationParamType.model_validate_json(params)  # type: ignore
            else:
                return cls.CreationParamType.model_validate(params)  # type: ignore
        except ValidationError:
            return None
    
    @classmethod
    def ValidateJoinParams(cls, params: dict[str, Any]|str) -> JoinT|None:
        try:
            if isinstance(params, str):
                return cls.JoinParamType.model_validate_json(params)  # type: ignore
            else:
                return cls.JoinParamType.model_validate(params)  # type: ignore
        except ValidationError:
            return None
    
    @classmethod
    async def Create(cls, request: CreateT, client_ip: str | None = None) -> tuple["WebRTCRoom", UserCandidate, WebRTCRoomCreationResponse]:
        '''Create a room and an initial candidate.'''
        if not (cls := WebRTCRoom.GetRoomClass(request.room_type)):
            raise HTTPException(status_code=404, detail=DefaultRoomCreationError.RoomTypeNotFound)
        try:
            room = cls(**request.to_room_init_param(cls))
        except:
            raise HTTPException(status_code=400, detail=DefaultRoomCreationError.InvalidCreationParams)
        await room.start()
        
        try:
            candidate = await room.add_candidate(UserCandidate, **{**request.to_user_candidate_init_params(), 'ip': client_ip}) # type: ignore
        except Exception as _e:
            logging.getLogger(__name__).error(f"Failed to create candidate: {_e}", exc_info=True)
            try:
                await room.close()
            except:
                pass
            raise HTTPException(status_code=400, detail=DefaultRoomCreationError.FailToCreateCandidate)
        
        room.creator = candidate.id
        offer = RTCSessionDescription(sdp=request.sdp, type=request.type)
        await candidate.conn.setRemoteDescription(offer)
        answer = await candidate.conn.createAnswer()
        await candidate.conn.setLocalDescription(answer)
        
        if candidate.conn.localDescription is None:
            raise HTTPException(status_code=500, detail=DefaultRoomCreationError.FailedToCreateAnswer)
        
        resp = WebRTCRoomCreationResponse(
            room_info=room.dump_info(),
            candidate_info=candidate.dump_info(),
            sdp=candidate.conn.localDescription.sdp,
            type=candidate.conn.localDescription.type,  # type: ignore
            track_map=candidate._build_track_map(),
        )
        return room, candidate, resp
    
    @classmethod
    def NoUserCreate(cls, request: NoUserCreateT) -> tuple["WebRTCRoom", WebRTCRoomNoUserCreationResponse]:
        '''Create a room without creating initial candidate.'''
        if not (cls := WebRTCRoom.GetRoomClass(request.room_type)):
            raise HTTPException(status_code=404, detail=DefaultRoomCreationError.RoomTypeNotFound)
        try:
            room = cls(**request.to_room_init_param(cls))
        except:
            raise HTTPException(status_code=400, detail=DefaultRoomCreationError.InvalidCreationParams)
        asyncio.create_task(room.start())
        resp = WebRTCRoomNoUserCreationResponse(room_info=room.dump_info())
        return room, resp
        
    @classmethod
    async def Join(cls, request: JoinT, client_ip: str | None = None)-> tuple[Candidate, WebRTCRoomJoinResponse]:
        room = _all_rooms.get(request.room_id)
        if not room:
            raise HTTPException(status_code=404, detail=DefaultRoomCreationError.RoomTypeNotFound)
        
        if room.password and room.password != request.password:
            raise HTTPException(status_code=403, detail=DefaultRoomCreationError.InvalidJoinParams)
        
        candidate_creation_params = request.to_user_candidate_init_params()
        candidate_creation_params['ip'] = client_ip
        if not (id:= candidate_creation_params.get('id')):
            candidate_creation_params['id'] = id = str(uuid4())
        try:
            candidate = await room.add_candidate(UserCandidate, **candidate_creation_params)
        except Exception as _e:
            logging.getLogger(__name__).error(f"Failed to add candidate during join: {_e}", exc_info=True)
            room.candidates.pop(id, None)
            raise HTTPException(status_code=400, detail=DefaultRoomCreationError.FailToCreateCandidate)
        
        offer = RTCSessionDescription(sdp=request.sdp, type=request.type)
        await candidate.conn.setRemoteDescription(offer)
        answer = await candidate.conn.createAnswer()
        await candidate.conn.setLocalDescription(answer)
        
        if candidate.conn.localDescription is None:
            raise HTTPException(status_code=500, detail=DefaultRoomCreationError.FailedToCreateAnswer)
        
        resp = WebRTCRoomJoinResponse(
            candidate_info=candidate.dump_info(),
            room_info=room.dump_info(),
            sdp=candidate.conn.localDescription.sdp,
            type=candidate.conn.localDescription.type,  # type: ignore
            track_map=candidate._build_track_map(),
        )
        return candidate, resp
    
    @staticmethod
    def GetRoom(room_id: str) -> "WebRTCRoom|None":
        return _all_rooms.get(room_id)

_all_room_classes['default'] = WebRTCRoom

async def close_all_rooms():
    '''Close all rooms.'''
    async def close_room(room: WebRTCRoom):
        try:
            await room.close()
        except:
            pass
    coros = [close_room(room) for room in list(_all_rooms.values())]
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)

__all__ += [
    'DefaultRoomCreationError',
    'WebRTCRoom',
    'close_all_rooms',
]
# endregion
