"""
WebRTC 房间通讯协议: 消息类型定义、序列化/反序列化及内部信令.
"""
import asyncio

from uuid import uuid4
from datetime import datetime
from dataclasses import dataclass, field

from pydantic import SerializeAsAny, BeforeValidator, model_serializer, Field, AliasChoices

from typing import Literal, Annotated, TYPE_CHECKING, ClassVar

from av import AudioFrame, VideoFrame

from core.utils.type_utils import getattr_raw, get_pydantic_type_adapter
from .config import _AutoDocstringModel

if TYPE_CHECKING:
    from .candidate import UserCandidate


# region RTCMediaMsg
@dataclass
class RTCMediaMsg:
    '''
    RTC媒体消息封装, 用于在Candidate之间转发音频/视频帧及相关元信息.
    '''
    data: 'bytes | VideoFrame | AudioFrame'
    '''原始媒体数据, 类型取决于`type`.'''
    type: Literal['audio', 'video']
    '''媒体类型: `audio` 或 `video`.'''
    duration_ms: int|None = None
    '''音频帧时长毫秒(仅`audio`消息使用).'''
    time: datetime = field(default_factory=datetime.now)
    '''消息时间戳.'''
    from_candidate: str|None = None
    '''来源candidate id.'''
    
    # audio fields
    is_voice: bool|None = None
    '''
    是否检测为人声(仅`audio`消息使用).
    对`video`消息该字段应为None, 接收方应忽略.
    '''
    
    # video fields
    width: int|None = None
    '''视频宽度(仅`video`消息使用).'''
    height: int|None = None
    '''视频高度(仅`video`消息使用).'''
# endregion

# region WebRTCMsg base & registry
_webrtc_message_types: dict[str, type["WebRTCMsgBase"]] = {}     # {message type -> message class}

class UnknownWebRTCMsgTypeError(ValueError): ...

class WebRTCMsgBase(_AutoDocstringModel):
    '''
    通用的message底层, 包含一个type字段用于区分不同类型的消息.
    json data应包含一个"type"字段, 后端会根据这个字段的值来反序列化成对应的消息类, 例如以下是UserMsg的json data示例:
    ```
    {
        "type": "user_msg",
        "candidate_id": ...,    # uuid4
        "time": "2024-01-01T12:00:00.000Z",
        "text": "Hello, world!"
    }
    ```
    '''
    
    Type: ClassVar[str|None] = None
    '''消息类型, 由子类指定'''
    SubTypePrefix: ClassVar[str|None] = None
    '''当一个消息类型有多个子类型时, 可以使用这个字段指定子type的前缀.'''
    
    candidate_id: str|None = None
    '''发出消息的candidate id(如有)'''
    time: datetime = Field(default_factory=datetime.now)
    '''消息发送时间.'''
    
    def __init_subclass__(
        cls, 
        type: str|None=None,
        sub_type_prefix: str|None=None,
    ):
        super().__init_subclass__()
        curr_prefix = cls.SubTypePrefix or ""
        if type:
            type = type.strip()
            assert type and type not in _webrtc_message_types, f"WebRTCMsg type '{type}' is already registered"
            _webrtc_message_types[type] = cls
            cls.Type = curr_prefix + type
        if sub_type_prefix:
            cls.SubTypePrefix = curr_prefix + sub_type_prefix
        
    @model_serializer(mode='wrap')
    def _serialize(self, handler):
        data = handler(self)
        if self.Type:
            data['type'] = self.Type
        return data
        
    @classmethod
    def GetMsgClass(cls, type: str) -> type["WebRTCMsgBase"]|None:
        '''透過type字符串获取对应的消息类.'''
        return _webrtc_message_types.get(type)
    
def _pre_validate_webrtc_msg(value):
    if isinstance(value, dict):
        type = value.get("type")
        if type and isinstance(type, str):
            if cls := WebRTCMsgBase.GetMsgClass(type):
                return cls.model_validate(value)
            else:
                raise UnknownWebRTCMsgTypeError(f"Unknown WebRTCMsg type: {type}")
        else:
            raise ValueError(f"WebRTCMsg missing valid 'type' field: {value}")
    raise ValueError(f"Invalid WebRTCMsg: {value}")

type WebRTCMsg = SerializeAsAny[Annotated[WebRTCMsgBase, BeforeValidator(_pre_validate_webrtc_msg)]]
web_rtc_msg_type_adapter = get_pydantic_type_adapter(WebRTCMsg)
# endregion

# region connection lifecycle messages
class CandidateConnectingMsg(WebRTCMsgBase, type="user_connecting"):
    '''通知前端有其他用户正在连接的消息, 这个消息通常会在UserConnectedMsg之前发送, 用于提示前端有用户正在加入房间.
    NOTE: 此消息不是redirect msg, 因为这个消息是由后端在接收到用户连接事件时主动发送给其他candidate的.'''
    name: str|None = None
    ip: str|None = None
    
class CandidateConnectedMsg(WebRTCMsgBase, type="user_connected"):
    '''通知前端有其他用户连接的消息.
    NOTE: 此消息不是redirect msg, 因为这个消息是由后端在接收到用户连接事件时主动发送给其他candidate的.'''
    name: str|None = None
    ip: str|None = None

type CandidateLeaveReason = Literal['left', 'error', 'kick']

class CandidateDisconnectedMsg(WebRTCMsgBase, type="user_disconnected"): 
    '''通知前端有其他用户断开连接的消息.
    NOTE: 此消息不是redirect msg, 因为这个消息是由后端在接收到用户断开连接事件时主动发送给其他candidate的.'''
    name: str|None = None
    reason: CandidateLeaveReason = 'left'
    '''断开连接的原因, 由后端根据实际情况指定.'''
# endregion

# region user message base classes
class UserMsgBase(WebRTCMsgBase):
    @classmethod
    def _HasImplementedOnReceivedFromClient(cls) -> bool:
        if '__implemented_on_received_from_client__' not in cls.__dict__:
            r = getattr_raw(cls, "on_received_from_client") != getattr_raw(UserMsgBase, "on_received_from_client")
            cls.__implemented_on_received_from_client__ = r
        return cls.__implemented_on_received_from_client__
    
    async def on_received_from_client(self, creator: "UserCandidate"):
        '''
        你可以在这里定义后端接受到这个message之后有什么特别的处理逻辑.
        '''
        return
    
class UserRedirectWebRTCMsg(UserMsgBase):
    '''特殊的用户消息类, 当UserCandidate后端收到此类消息时, 会自动转发给房间里其他candidate.'''
    
    async def on_received_from_client(self, creator: "UserCandidate"):
        from .candidate import Candidate
        self.candidate_id = creator.id
        self.time = datetime.now()
        coros = []
        async def try_send_msg(c: Candidate):
            try:
                await c.send_msg(self)
            except Exception as e:
                creator.logger.warning(f"Failed to forward message to candidate {repr(c)}. {type(e).__name__}: {e}")
                
        for c in creator.room.candidates.values():
            if c != creator and not c.disabled:
                coros.append(try_send_msg(c))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)
# endregion

# region text chat room message types
class UserMsg(UserRedirectWebRTCMsg, type="user_msg"):
    '''在文字聊天室内的用户消息.'''
    text: str = ''
    '''用户输入的文本消息.'''
    msg_id: str = Field(default_factory=lambda: str(uuid4()), validation_alias=AliasChoices("msg_id", "id"))
    '''消息ID.'''
    reply_to: str|None = None
    '''回复的msg_id.'''

class UserMediaMsg(UserRedirectWebRTCMsg, type="user_media"):
    '''在文字聊天室内的, 包含一个媒体文件的消息.'''
    filename: str
    filehash: str
    filesize: int
    media_type: Literal['audio', 'image', 'video', 'file']

class UserMediaMsgChunk(UserRedirectWebRTCMsg, type="user_media_chunk"):
    filehash: str
    data: str
    '''base64分片数据'''
    index: int
    finished: bool = False
    
    def __repr__(self):
        data = f'{self.data[:16]}...{self.data[-16:]}' if len(self.data) > 64 else self.data
        return f"UserMediaMsgChunk(data={data}, hash={self.filehash}, index={self.index}, finished={self.finished})"
    
    __str__ = __repr__
# endregion

# region mute / deafen / name change / reaction / admin message types
class UserSetMute(UserRedirectWebRTCMsg, type="user_set_mute"):
    mute: bool = True
    muted_by: str|None = None
    
    async def on_received_from_client(self, creator: "UserCandidate"):
        if creator.muted_by and not self.mute:
            creator.logger.info(f"User {creator.id} cannot unmute because muted_by={creator.muted_by}")
            return
        if creator.muted != self.mute:
            creator.muted = self.mute
            creator.muted_by = None
            return await super().on_received_from_client(creator)

class UserSetAdmin(UserMsgBase, type="user_set_admin"):
    '''管理员设置/取消其他用户管理员身份.'''
    target_id: str
    is_admin: bool = True

    async def on_received_from_client(self, creator: "UserCandidate"):
        if not creator.is_admin:
            return
        target = creator.get_candidate(self.target_id)
        if target is None or target.id == creator.id or target.disabled or target._closed:
            return
        target.is_admin = bool(self.is_admin)
        broadcast = UserSetAdmin(candidate_id=target.id, target_id=target.id, is_admin=target.is_admin)
        coros = []
        for c in creator.room.candidates.values():
            if not (c.disabled or c._closed):
                coros.append(c.send_msg(broadcast))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

class UserAdminForceMute(UserMsgBase, type="user_admin_force_mute"):
    '''管理员强制静音/解除静音目标用户.'''
    target_id: str
    mute: bool = True

    async def on_received_from_client(self, creator: "UserCandidate"):
        if not creator.is_admin:
            return
        target = creator.get_candidate(self.target_id)
        if target is None or target.id == creator.id or target.disabled or target._closed:
            return
        target.muted = bool(self.mute)
        target.muted_by = creator.id if self.mute else None
        broadcast = UserSetMute(candidate_id=target.id, mute=target.muted, muted_by=target.muted_by)
        coros = []
        for c in creator.room.candidates.values():
            if not (c.disabled or c._closed):
                coros.append(c.send_msg(broadcast))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

class UserFileRelay(UserRedirectWebRTCMsg, type="user_file_relay"):
    '''大文件分布式下载流程的信令消息.'''
    action: str
    target_id: str|None = None
    filehash: str|None = None
    request_id: str|None = None
    transfer_id: str|None = None
    filename: str|None = None
    filesize: int|None = None
    media_type: str|None = None
    chunk_size: int|None = None
    total_chunks: int|None = None
    start_index: int|None = None
    end_index: int|None = None
    index: int|None = None
    data: str|None = None
    missing: list[int]|None = None

    async def on_received_from_client(self, creator: "UserCandidate"):
        self.candidate_id = creator.id
        self.time = datetime.now()
        coros = []
        for c in creator.room.candidates.values():
            if c != creator and not c.disabled:
                coros.append(c.send_msg(self))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)
        
class UserSetName(UserRedirectWebRTCMsg, type="user_set_name"):
    name: str
    
    async def on_received_from_client(self, creator: "UserCandidate"):
        if creator.name != self.name:
            creator.name = self.name
            return await super().on_received_from_client(creator)

class UserSetDeafen(UserRedirectWebRTCMsg, type="user_set_deafen"):
    deafen: bool = True

    async def on_received_from_client(self, creator: "UserCandidate"):
        if creator.deafen != self.deafen:
            creator.deafen = self.deafen
            return await super().on_received_from_client(creator)

class UserSetCam(UserRedirectWebRTCMsg, type="user_set_cam"):
    cam_on: bool = True

    async def on_received_from_client(self, creator: "UserCandidate"):
        if creator.cam_on != self.cam_on:
            creator.cam_on = self.cam_on
            return await super().on_received_from_client(creator)

class UserReaction(UserRedirectWebRTCMsg, type="user_reaction"):
    '''用户设置 emoji reaction.'''
    reaction: str|None = Field(default=None, validation_alias=AliasChoices("reaction", 'emoji'))
    
    async def on_received_from_client(self, creator: "UserCandidate"):
        if creator.reaction != self.reaction:
            creator.reaction = self.reaction
            return await super().on_received_from_client(creator)

class UserKick(UserMsgBase, type="user_kick"):
    '''管理员将指定用户移出房间的指令.'''
    target_id: str

    async def on_received_from_client(self, creator: "UserCandidate"):
        if not creator.is_admin:
            return
        target = creator.get_candidate(self.target_id)
        if target is None:
            return
        if target.id == creator.id:
            return
        if target.is_admin:
            return
        # Notify the kicked user
        kicked_msg = UserKick(
            candidate_id=creator.id,
            target_id=target.id,
            time=datetime.now(),
        )
        await target.send_msg(kicked_msg)
        await asyncio.sleep(0.1)
        await target.close(reason='kick')

class UserLeave(UserMsgBase, type="user_leave"):
    '''用户主动离开房间的指令.'''

    async def on_received_from_client(self, creator: "UserCandidate"):
        await creator.close(reason='left')
# endregion

# region speaker notification
class SpeakerActiveNotify(WebRTCMsgBase, type="speaker_active"):
    '''通知前端某个用户正在说话.'''
    duration_ms: int = 20

class SpeakerInactiveNotify(WebRTCMsgBase, type="speaker_inactive"):
    '''通知前端某个用户停止说话.'''
# endregion

# region WebRTC signaling (internal protocol)
class RenegotiateNeededSignal(WebRTCMsgBase, type="renegotiate_needed"):
    '''WebRTC信令: 通知浏览器服务端添加了新的track, 需要重协商.'''
    add_transceivers: list[dict[str, str]] | None = None

class RenegotiateAnswerSignal(WebRTCMsgBase, type="renegotiate_answer"):
    '''WebRTC信令: 服务端对浏览器offer的answer.'''
    sdp: str
    track_map: dict[str, dict[str, str]] = {}

type IceConnectionState = Literal["checking", "completed", "closed", "failed", "new"]
# endregion

__all__ = [
    'RTCMediaMsg',
    'WebRTCMsgBase',
    'WebRTCMsg',
    'web_rtc_msg_type_adapter',
    'UnknownWebRTCMsgTypeError',
    'UserMsgBase',

    'CandidateLeaveReason',
    'CandidateConnectingMsg',
    'CandidateConnectedMsg',
    'CandidateDisconnectedMsg',
    
    'UserRedirectWebRTCMsg',
    'UserMsg',
    'UserMediaMsg',
    'UserMediaMsgChunk',
    
    'UserSetMute',
    'UserSetAdmin',
    'UserAdminForceMute',
    'UserSetDeafen',
    'UserSetCam',
    'UserSetName',
    'UserReaction',
    'UserFileRelay',
    'UserKick',
    'UserLeave',
    
    'SpeakerActiveNotify',
    'SpeakerInactiveNotify',
    
    'RenegotiateNeededSignal',
    'RenegotiateAnswerSignal',
    'IceConnectionState',
]
