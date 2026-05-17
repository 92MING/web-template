import json
import asyncio
import logging
import audioop

from abc import ABC
from uuid import uuid4
from datetime import datetime
from fractions import Fraction
from pydub import AudioSegment
from functools import cached_property
from threading import Lock
from pydantic import SerializeAsAny, BeforeValidator

from typing import (Any, override, Annotated, TYPE_CHECKING, get_args, TypedDict, 
                    get_origin, TypeVar, Self, Awaitable)
from typing_extensions import Required, TypeForm, NotRequired, Unpack

from av import AudioFrame, VideoFrame

from aiortc import (RTCPeerConnection, RTCDataChannel, RTCSessionDescription)
from aiortc.rtcrtpreceiver import RemoteStreamTrack

from core.utils.data_structs.files import Video
from core.utils.type_utils import getattr_raw
from core.utils.concurrent_utils import run_any_func, is_async_callable
from .config import _AutoDocstringModel, ChatRoomConfig

if TYPE_CHECKING:
    from .room import WebRTCRoom, CandidateInfo

from .tracks import MediaStreamTrack, AudioSendTrack, VideoSendTrack
from .protocol import (
    RTCMediaMsg, WebRTCMsgBase, WebRTCMsg, web_rtc_msg_type_adapter,
    UnknownWebRTCMsgTypeError, UserMsgBase,
    CandidateLeaveReason, CandidateConnectingMsg, CandidateConnectedMsg, CandidateDisconnectedMsg,
    UserRedirectWebRTCMsg, UserMsg, UserMediaMsg, UserMediaMsgChunk,
    UserSetMute, UserSetAdmin, UserAdminForceMute, UserSetDeafen, UserSetCam,
    UserSetName, UserReaction, UserFileRelay, UserKick, UserLeave,
    SpeakerActiveNotify, SpeakerInactiveNotify,
    RenegotiateNeededSignal, RenegotiateAnswerSignal, IceConnectionState,
)

def _tidy_annotate_default_typeddict[T](
    params: dict[str, Any]|None, 
    td_cls: TypeForm[T], 
    allow_extra: bool=False,
    extra_defaults: dict[str, Any]|None=None,
)->T:
    '''Tidy the given params dict according to the given TypedDict class, 
    filling in default values for missing keys.'''
    if params is None:
        params = {}
    tidied_params = {}
    for key, anno in td_cls.__annotations__.items():
        if key in params:
            tidied_params[key] = params.pop(key)
        else:
            if extra_defaults:
                if key in extra_defaults:
                    tidied_params[key] = extra_defaults[key]
                    continue
            while get_origin(anno) in (Required, NotRequired):
                anno = get_args(anno)[0]
            if get_origin(anno) is Annotated:
                anno_args = get_args(anno)
                if len(anno_args) >= 2:
                    default_value = anno_args[1]
                    tidied_params[key] = default_value
    if allow_extra and params:
        tidied_params.update(params)    # type: ignore
    return td_cls(**tidied_params)  # type: ignore

class _CandidateInitParams(TypedDict, total=False):
    room: Required["WebRTCRoom"]
    id: Annotated[str|None, None]
    name: Annotated[str|None, None]
    hidden: Annotated[bool, False]
    is_admin: Annotated[bool, False]
    muted: Annotated[bool, False]
    muted_by: Annotated[str|None, None]
    deafen: Annotated[bool, False]
    disabled: Annotated[bool, False]
    ip: Annotated[str|None, None]
    
class _TidiedCandidateInitParams(TypedDict, total=True):
    room: "WebRTCRoom"
    id: str|None
    name: str|None
    hidden: bool
    is_admin: bool
    muted: bool
    muted_by: str|None
    deafen: bool
    disabled: bool
    ip: str|None
    
def _tidy_default_candidate_init_params(params)->_TidiedCandidateInitParams:
    data = _tidy_annotate_default_typeddict(params, _CandidateInitParams)   # type: ignore
    from .room import WebRTCRoom
    if 'room' not in data or not isinstance(data['room'], WebRTCRoom):
        raise ValueError("Candidate initialization requires a valid 'room' parameter")
    return data     # type: ignore
    
class Candidate(ABC):
    '''Candidate基类代表一个参与WebRTC room活动的实体.'''
    
    id: str
    name: str|None = None
    room: "WebRTCRoom"
    hidden: bool = False
    is_admin: bool = False
    muted: bool = False
    muted_by: str|None = None
    deafen: bool = False
    cam_on: bool = True
    disabled: bool = False
    join_time: datetime
    reaction: str|None = None
    ip: str|None = None
    
    _started: bool = False
    _closed: bool = False
    
    audio_send_queue: asyncio.Queue[RTCMediaMsg]
    video_send_queue: asyncio.Queue[RTCMediaMsg]
    msg_send_queue: asyncio.Queue[WebRTCMsg]
    _close_lock: Lock
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        init = cls.__init__
        if not hasattr(init, '__post_init_decorated__'):
            def init_wrapper(self, /, **kwargs):
                init(self, **kwargs)
                run_any_func(self.on_created)
            init_wrapper.__post_init_decorated__ = True
            cls.__init__ = init_wrapper
    
    def __init__(self, /, **kwargs: Unpack[_CandidateInitParams]):
        params = _tidy_default_candidate_init_params(kwargs)    # type: ignore
        id = params['id']
        name = params['name']
        room = params['room']
        hidden = params['hidden']
        is_admin = params['is_admin']
        muted = params['muted']
        muted_by = params['muted_by']
        deafen = params['deafen']
        disabled = params['disabled']
        self._close_lock = Lock()
        self.id = id or str(uuid4())
        self.join_time = datetime.now()
        self.room = room    # type: ignore
        self.room.candidates[self.id] = self   # type: ignore
        self.name = name
        self.hidden = hidden
        self.is_admin = is_admin
        self.muted = muted
        self.muted_by = muted_by
        self.deafen = deafen
        self.cam_on = True
        self.disabled = disabled
        self.reaction = None
        self.ip = params.get('ip', None)
        self._started = False
        self._closed = False
        self.audio_send_queue = asyncio.Queue()
        self.video_send_queue = asyncio.Queue()
        self.msg_send_queue = asyncio.Queue()
        
    def __str__(self):
        return f'{self.__class__.__name__}(id={self.id}, name={self.name}, hidden={self.hidden}, is_admin={self.is_admin}, muted={self.muted}, muted_by={self.muted_by}, deafen={self.deafen}, disabled={self.disabled})'
    
    __repr__ = __str__
    
    def __del__(self):
        if not self._closed:
            if is_async_callable(self.close):
                async def close_wrapper():
                    try:
                        await self.close()
                    except:
                        pass
                run_any_func(close_wrapper)
            else:
                try:
                    self.close()    # type: ignore
                except:
                    pass
        
    @cached_property
    def logger(self) -> logging.Logger:
        if len(self.id) == 36 and self.id.count('-') == 4: # uuid4
            suffix = self.id.split('-')[0]
        else:
            suffix = self.id
        suffix = suffix[:8]
        return self.room.logger.getChild(f'{self.__class__.__name__}_{suffix}')
        
    async def start(self):
        if not self._started:
            self._started = True
            await self.on_start()
        
    async def close(self, reason: CandidateLeaveReason='left'):
        if not self._closed:
            self._closed = True
            if self._close_lock.locked():
                return
            with self._close_lock:
                try:
                    await asyncio.wait_for(self.on_close(reason=reason), timeout=1.2)
                except:
                    pass
    
    async def on_created(self):
        if not (self.disabled or self.hidden or self._closed):
            msg = CandidateConnectingMsg(name=self.name, candidate_id=self.id, ip=self.ip)
            coros = []
            for c in self.room.candidates.values():
                if c != self and not (c.disabled or c.hidden):
                    coros.append(c.send_msg(msg))
            if coros:                
                await asyncio.gather(*coros, return_exceptions=True)
    
    async def on_start(self): 
        if not (self.disabled or self.hidden or self._closed):
            msg = CandidateConnectedMsg(name=self.name, candidate_id=self.id, ip=self.ip)
            coros = []
            for c in self.room.candidates.values():
                if c != self and not (c.disabled or c.hidden or c._closed):
                    coros.append(c.send_msg(msg))
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)
        
    async def on_close(self, reason: CandidateLeaveReason='left'): 
        if not (self.disabled or self.hidden):
            msg = CandidateDisconnectedMsg(reason=reason, name=self.name, candidate_id=self.id)
            coros = []
            for c in self.room.candidates.values():
                if c != self and not (c.disabled or c.hidden or c._closed):
                    coros.append(c.send_msg(msg))
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)
        self.room.candidates.pop(self.id, None)
        if self.room.close_room_on_creator_left and self.room.creator == self.id and not self.room._closed:
            self.logger.info(f"Room creator `{self.id}` left, closing room `{self.room.id}` due to close_room_on_creator_left=True")
            asyncio.create_task(self.room.close())
        if self.room.close_when_no_visible_candidate:
            visible_cands = [c for c in self.room.candidates.values() if not (c.disabled or c.hidden or c._closed)]
            if not visible_cands:
                self.logger.info(f"No visible candidates left in the room `{self.room.id}({self.room.__class__.__name__})`, closing room.")
                asyncio.create_task(self.room.close())
    
    async def send_msg(self, data: WebRTCMsg):
        if self.disabled or self._closed:
            return
        await self.msg_send_queue.put(data)
    
    async def send_audio(self, data: AudioFrame|bytes|AudioSegment, from_candidate: str, time: datetime|None=None, is_voice: bool|None=None):
        if self.disabled or self._closed:
            return
        duration_ms = 20
        if isinstance(data, AudioSegment):
            raw = data.raw_data
            sr = data.frame_rate or 16000
            ch = data.channels or 1
            sw = data.sample_width or 2
            n_samples = len(raw) // (sw * ch) if (sw * ch) else 0   # type: ignore
            if n_samples <= 0:
                return
            layout = "mono" if ch == 1 else "stereo"
            frame = AudioFrame(format="s16", layout=layout, samples=n_samples)
            frame.sample_rate = sr
            frame.planes[0].update(raw[:n_samples * sw * ch])   # type: ignore
            frame.pts = 0
            frame.time_base = Fraction(1, sr)
            duration_ms = max(1, int(round((n_samples / sr) * 1000)))
            data = frame   # type: ignore
        elif isinstance(data, AudioFrame):
            sr = int(getattr(data, 'sample_rate', 48000) or 48000)
            if sr > 0:
                duration_ms = max(1, int(round((data.samples / sr) * 1000)))
        elif isinstance(data, bytes):
            sr = ChatRoomConfig.GetConfig().audio_config.audio_sample_rate or 16000
            n_samples = len(data) // 2  # assume s16 mono
            if n_samples <= 0:
                return
            frame = AudioFrame(format="s16", layout="mono", samples=n_samples)
            frame.sample_rate = sr
            frame.planes[0].update(data[:n_samples * 2])
            frame.pts = 0
            frame.time_base = Fraction(1, sr)
            duration_ms = max(1, int(round((n_samples / sr) * 1000)))
            data = frame   # type: ignore
        time = time or datetime.now()
        msg = RTCMediaMsg(data=data, type='audio', from_candidate=from_candidate, time=time, duration_ms=duration_ms, is_voice=is_voice)    # type: ignore
        while self.audio_send_queue.qsize() > 20:
            try:
                self.audio_send_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        await self.audio_send_queue.put(msg)
    
    async def send_video(self, data: VideoFrame|Video|bytes, from_candidate: str, time: datetime|None=None):
        if self.disabled or self._closed:
            return
        width: int|None = None
        height: int|None = None
        if isinstance(data, VideoFrame):
            if str(data.format) != 'yuv420p':
                data = data.reformat(format="yuv420p")
            width = int(data.width)
            height = int(data.height)
        elif isinstance(data, Video):
            data = data.to_bytes()
        time = time or datetime.now()
        msg = RTCMediaMsg(data=data, type='video', width=width, height=height, from_candidate=from_candidate, time=time)    # type: ignore
        while self.video_send_queue.qsize() > 1:
            try:
                self.video_send_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        await self.video_send_queue.put(msg)
    
    async def on_msg(self, msg: WebRTCMsg):
        '''定义当这个Candidate收到消息时的处理逻辑.'''
        ...
        
    async def on_audio(self, audio_data: RTCMediaMsg):
        '''定义当这个Candidate收到音频数据时的处理逻辑.'''
        ...
        
    async def on_video(self, video_data: RTCMediaMsg):
        '''定义当这个Candidate收到视频数据时的处理逻辑.'''
        ...
    
    @classmethod
    def _HasImplementedLoopOnce(cls) -> bool:
        if '__implemented_loop_once__' not in cls.__dict__:
            r = getattr_raw(cls, "loop_once") != getattr_raw(Candidate, "loop_once")
            cls.__implemented_loop_once__ = r
        return cls.__implemented_loop_once__
    
    async def loop_once(self):
        if self.disabled or self._closed:
            return
        if not self._started:
            await self.start()
        async def get_from_queue(q: asyncio.Queue):
            try:
                return await asyncio.wait_for(q.get(), timeout=0.003)
            except asyncio.TimeoutError:
                return None
        
        msg, audio, video = await asyncio.gather(
            get_from_queue(self.msg_send_queue),
            get_from_queue(self.audio_send_queue),
            get_from_queue(self.video_send_queue),
        )
        coros = []
        if msg is not None:
            coros.append(self.on_msg(msg))
        if audio is not None:
            coros.append(self.on_audio(audio))
        if video is not None:
            coros.append(self.on_video(video))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    # region helper methods
    def get_candidate(self, id: str)->"Candidate|None":
        if id == self.id:
             return self
        return self.room.candidates.get(id)
    
    def dump_info(self)->"CandidateInfo":
        from .room import CandidateInfo
        return CandidateInfo(
            id=self.id,
            name=self.name,
            join_time=self.join_time,
            is_admin=self.is_admin,
            muted=self.muted,
            muted_by=self.muted_by,
            deafen=self.deafen,
            cam_on=self.cam_on,
            reaction=self.reaction,
            ip=self.ip,
        )
    # endregion

class UserCandidate(Candidate):
    '''代表真实用户的Candidate class.'''
    
    label: str = 'default'
    conn: RTCPeerConnection
    channel: RTCDataChannel
    
    audio_send_tracks: dict[str, AudioSendTrack]
    audio_receive_track: RemoteStreamTrack | None = None  
    video_send_tracks: dict[str, VideoSendTrack]
    video_receive_track: RemoteStreamTrack | None = None  
    _renegotiation_lock: asyncio.Lock
    _renegotiation_event: asyncio.Event | None
    
    def __init__(
        self,
        /, 
        label: str = 'default',
        **kwargs: Unpack[_CandidateInitParams],
    ):
        super().__init__(**kwargs)
        config = ChatRoomConfig.GetConfig()
        
        if config.rtc_config:
            self.conn = RTCPeerConnection(configuration=config.rtc_config.to_aiortc_config())
        else:
            self.conn = RTCPeerConnection()
        self.label = label
        
        self.channel = self.conn.createDataChannel(label)
        self.audio_send_tracks: dict[str, AudioSendTrack] = {}
        self.video_send_tracks: dict[str, VideoSendTrack] = {}
        self._initial_tracks_added = False
        self.audio_receive_track = None
        self.video_receive_track = None
        self._audio_speaker_id: str | None = None
        self._audio_speaker_notify_ts: datetime = datetime.min
        self._renegotiation_lock = asyncio.Lock()
        self._renegotiation_event: asyncio.Event | None = None
        self._pending_renegotiation: bool = False
        
        # register event handlers
        self.conn.on("iceconnectionstatechange")(self._on_iceconnectionstatechange)
        self.conn.on("track")(self.on_track)
        def on_channel_message_wrapper(message):
            asyncio.ensure_future(self.on_channel_msg(message))
        self.channel.on("message")(on_channel_message_wrapper)
        def on_channel_open():
            self.logger.info(
                f"DataChannel `{self.label}` opened (id={getattr(self.channel, 'id', None)}, state={getattr(self.channel, 'readyState', None)})."
            )
            if self._pending_renegotiation:
                self._pending_renegotiation = False
                self.logger.info("DataChannel opened — retrying pending renegotiation")
                asyncio.ensure_future(self._trigger_renegotiation())
        self.channel.on("open")(on_channel_open)
        self.channel.on("close")(lambda: self.logger.info(
            f"DataChannel `{self.label}` closed (id={getattr(self.channel, 'id', None)}, state={getattr(self.channel, 'readyState', None)})."
        ))
    
    @override
    async def on_start(self):
        for track in self.audio_send_tracks.values():
            while not track.data_queue.empty():
                try: track.data_queue.get_nowait()
                except asyncio.QueueEmpty: break
        for track in self.video_send_tracks.values():
            while not track.data_queue.empty():
                try: track.data_queue.get_nowait()
                except asyncio.QueueEmpty: break
        for q in (self.audio_send_queue, self.video_send_queue):
            while not q.empty():
                try: q.get_nowait()
                except asyncio.QueueEmpty: break
        await super().on_start()
        for c in list(self.room.candidates.values()):
            if c != self and isinstance(c, UserCandidate) and not c._closed:
                asyncio.create_task(c._add_send_tracks_for(self.id))
    
    @override
    async def on_close(self, reason: 'CandidateLeaveReason' = 'left'):
        my_id = self.id
        for c in list(self.room.candidates.values()):
            if c != self and isinstance(c, UserCandidate) and not c._closed:
                c._remove_send_tracks_for(my_id)
        try:
            await super().on_close(reason=reason)
        except:
            pass
        async def try_f(f):
            try:
                r = f()
                if isinstance(r, Awaitable):
                    await asyncio.wait_for(r, timeout=1.0)
            except:
                pass
        self._closed = True
        coros = []
        coros.append(try_f(self.channel.close))
        for track in self.audio_send_tracks.values():
            coros.append(try_f(track.stop))
        for track in self.video_send_tracks.values():
            coros.append(try_f(track.stop))
        await asyncio.gather(*coros, return_exceptions=True)
        coros = []
        if self.audio_receive_track:
            coros.append(try_f(self.audio_receive_track.stop))
        if self.video_receive_track:
            coros.append(try_f(self.video_receive_track.stop))
        coros.append(try_f(self.conn.close))
        await asyncio.gather(*coros, return_exceptions=True)
    
    async def on_channel_msg(self, message: bytes):
        if self.disabled or self._closed:
            return
        try:
            data = message.decode("utf-8", errors="ignore") if isinstance(message, (bytes, bytearray)) else str(message)
        except:
            msg_for_log = str(message)
            if len(msg_for_log) > 1024:
                msg_for_log = msg_for_log[:512] + '...' + msg_for_log[-512:]
            self.logger.warning(f"Failed to decode message: {msg_for_log}")
            return
        # Intercept renegotiation answer before WebRTCMsg parsing
        try:
            _raw = json.loads(data)
            if isinstance(_raw, dict) and _raw.get('type') == 'renegotiate_offer':
                try:
                    offer = RTCSessionDescription(sdp=_raw['sdp'], type='offer')
                    await self.conn.setRemoteDescription(offer)
                    answer = await self.conn.createAnswer()
                    await self.conn.setLocalDescription(answer)
                    track_map = self._build_track_map()
                    signal = RenegotiateAnswerSignal(sdp=self.conn.localDescription.sdp, track_map=track_map)
                    self.channel.send(signal.model_dump_json())
                    if self._renegotiation_event:
                        self._renegotiation_event.set()
                    self.logger.info("Renegotiation answer sent successfully")
                except Exception as e:
                    self.logger.error(f"Failed to process renegotiate_offer: {type(e).__name__}: {e}")
                return
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        # Normal WebRTCMsg parsing
        try:
            try:
                payload = web_rtc_msg_type_adapter.validate_json(data)
            except UnknownWebRTCMsgTypeError:
                payload_for_log = str(json.loads(data))
                if len(payload_for_log) > 1024:
                    payload_for_log = payload_for_log[:512] + '...' + payload_for_log[-512:]
                self.logger.warning(f"Received message with unknown type: {payload_for_log}")
                return
        except:
            msg_for_log = str(data)
            if len(msg_for_log) > 1024:
                msg_for_log = msg_for_log[:512] + '...' + msg_for_log[-512:]
            self.logger.warning(f"Failed to parse WebRTCMsg: {msg_for_log}")
            return
        if isinstance(payload, UserMsgBase) and payload._HasImplementedOnReceivedFromClient():
            self.logger.debug(f"Received client side msg: {repr(payload)}")
            await payload.on_received_from_client(self)
    
    @override
    async def on_msg(self, data: WebRTCMsg):
        self.logger.debug(f"Forwarding msg to client: {repr(data)}")
        if self.disabled or self._closed:
            return
        try:
            msg_json = data.model_dump_json()
        except Exception as e:
            self.logger.warning(f"Failed to serialize message to JSON: {type(e).__name__}: {e}. Message content: {repr(data)}")
            return
        for _ in range(3):
            try:
                state = getattr(self.channel, "readyState", None)
                self.logger.debug(
                    f"Try send via datachannel `{self.label}` (id={getattr(self.channel, 'id', None)}, state={state}, size={len(msg_json)})."
                )
                if state == "open":
                    self.channel.send(msg_json)
                    self.logger.debug(
                        f"Sent msg via datachannel `{self.label}` (id={getattr(self.channel, 'id', None)})."
                    )
                    return
            except Exception as e:
                self.logger.debug(f"Failed to send msg on datachannel. {type(e).__name__}: {e}")
                return
            await asyncio.sleep(0.03)
        self.logger.warning(f"Drop msg because datachannel is not open (state={getattr(self.channel, 'readyState', None)}): {repr(data)}")
    
    @override
    async def on_audio(self, audio_data: RTCMediaMsg):
        if self.deafen:
            return
        sender = audio_data.from_candidate
        if not sender:
            return
        track = self.audio_send_tracks.get(sender)
        if track is None:
            self.logger.debug(f"on_audio: no send track for sender {sender[:8]}, dropping")
            return
        await track.send(audio_data.data)    # type: ignore
        # Debounced speaker notification via datachannel
        now = datetime.now()
        if audio_data.is_voice and (self._audio_speaker_id != sender or 
            (now - self._audio_speaker_notify_ts).total_seconds() > 0.3):
            self._audio_speaker_id = sender
            self._audio_speaker_notify_ts = now
            try:
                if getattr(self.channel, 'readyState', None) == 'open':
                    notify = SpeakerActiveNotify(candidate_id=sender, duration_ms=audio_data.duration_ms or 20, time=now)
                    self.channel.send(notify.model_dump_json())
            except:
                pass
        elif not audio_data.is_voice and self._audio_speaker_id == sender:
            self._audio_speaker_id = None
            try:
                if getattr(self.channel, 'readyState', None) == 'open':
                    notify = SpeakerInactiveNotify(candidate_id=sender, time=now)
                    self.channel.send(notify.model_dump_json())
            except:
                pass
        
    @override
    async def on_video(self, video_data: RTCMediaMsg):
        sender = video_data.from_candidate
        if not sender:
            return
        track = self.video_send_tracks.get(sender)
        if track is None:
            return
        if isinstance(video_data.data, VideoFrame):
            track.update_format(video_data.data.width, video_data.data.height)
        elif video_data.width and video_data.height:
            track.update_format(int(video_data.width), int(video_data.height))
        await track.send(video_data.data)       # type: ignore
    
    # region per-source track management
    async def _add_send_tracks_for(self, candidate_id: str):
        """Add audio+video send tracks for a source candidate and trigger renegotiation."""
        if candidate_id in self.audio_send_tracks:
            return
        self._create_send_tracks_for(candidate_id)
        self.logger.info(f"Added send tracks for candidate {candidate_id[:8]}, triggering renegotiation")
        await self._trigger_renegotiation()
    
    def _create_send_tracks_for(self, candidate_id: str):
        """Create audio+video send tracks for a source candidate WITHOUT triggering renegotiation."""
        if candidate_id in self.audio_send_tracks:
            return
        a_track = AudioSendTrack()
        v_track = VideoSendTrack()
        self.audio_send_tracks[candidate_id] = a_track
        self.video_send_tracks[candidate_id] = v_track
        self.conn.addTrack(a_track)
        self.conn.addTrack(v_track)
    
    def _remove_send_tracks_for(self, candidate_id: str):
        """Stop and remove send tracks for a source candidate that left."""
        a_track = self.audio_send_tracks.pop(candidate_id, None)
        v_track = self.video_send_tracks.pop(candidate_id, None)
        if a_track:
            try: a_track.stop()
            except: pass
        if v_track:
            try: v_track.stop()
            except: pass
        if a_track or v_track:
            self.logger.info(f"Removed send tracks for candidate {candidate_id[:8]}")
    
    async def _trigger_renegotiation(self):
        """Send renegotiate_needed and wait for browser offer."""
        if self._closed:
            return
        async with self._renegotiation_lock:
            if self._closed:
                return
            try:
                state = getattr(self.channel, 'readyState', None)
                if state != 'open':
                    self.logger.warning(f"Cannot renegotiate: datachannel state={state}, will retry when open")
                    self._pending_renegotiation = True
                    return

                add_transceivers = []
                for t in self.conn.getTransceivers():
                    if t.mid is None and t.sender and t.sender.track:
                        add_transceivers.append({'kind': t.sender.track.kind})

                self._pending_renegotiation = False
                self._renegotiation_event = asyncio.Event()
                signal = RenegotiateNeededSignal(add_transceivers=add_transceivers or None)
                self.channel.send(signal.model_dump_json())
                self.logger.info(f"Sent renegotiate_needed (add_transceivers={len(add_transceivers)}), waiting for client offer")

                try:
                    await asyncio.wait_for(self._renegotiation_event.wait(), timeout=10.0)
                    self.logger.info("Renegotiation completed successfully")
                except asyncio.TimeoutError:
                    self.logger.warning("Renegotiation offer timeout (10s) — no offer received from client")
            except Exception as e:
                self.logger.error(f"Renegotiation failed: {type(e).__name__}: {e}")
            finally:
                self._renegotiation_event = None
    
    def _build_track_map(self) -> dict[str, dict[str, str]]:
        """Build SDP mid -> {candidate_id, kind} mapping."""
        track_map: dict[str, dict[str, str]] = {}
        try:
            for transceiver in self.conn.getTransceivers():
                mid = transceiver.mid
                sender_track = transceiver.sender.track if transceiver.sender else None
                if not mid or not sender_track:
                    continue
                for cid, a_track in self.audio_send_tracks.items():
                    if a_track is sender_track:
                        track_map[mid] = {'candidate_id': cid, 'kind': 'audio'}
                        break
                else:
                    for cid, v_track in self.video_send_tracks.items():
                        if v_track is sender_track:
                            track_map[mid] = {'candidate_id': cid, 'kind': 'video'}
                            break
        except Exception as e:
            self.logger.warning(f"Failed to build track map: {e}")
        return track_map
    # endregion
    
    async def _on_iceconnectionstatechange(self):
        await self.on_iceconnectionstatechange(self.conn.iceConnectionState)    # type: ignore
        
    async def on_iceconnectionstatechange(self, state: IceConnectionState):
        self.logger.info(f"ICE state changed to: `{state}`")
        if state in ("connected", "completed") and not self._initial_tracks_added:
            self._initial_tracks_added = True
            created_any = False
            for c in list(self.room.candidates.values()):
                if c.id != self.id and not c.hidden and not c._closed:
                    if c.id not in self.audio_send_tracks:
                        self._create_send_tracks_for(c.id)
                        created_any = True
            if created_any:
                await self._trigger_renegotiation()
        if state == "failed":
            asyncio.create_task(self.close(reason='error'))
        elif state == 'closed':
            asyncio.create_task(self.close(reason='left'))
    
    def on_track(self, track: RemoteStreamTrack):
        track_kind = track.kind
        if track_kind == "audio":
            self.logger.info(f"Track received: {track_kind}")
            self.audio_receive_track = track
            def on_audio_track_ended_wrapper():
                run_any_func(self.on_track_ended, track)
            track.on("ended")(on_audio_track_ended_wrapper)
        elif track_kind == "video":
            self.logger.info(f"Track received: {track_kind}")
            self.video_receive_track = track
            def on_video_track_ended_wrapper():
                run_any_func(self.on_track_ended, track)
            track.on("ended")(on_video_track_ended_wrapper)
        else:
            self.logger.warning(f"Unknown track kind received: {track_kind}")
    
    async def on_track_ended(self, track: RemoteStreamTrack):
        self.logger.info(f"Track ended: {track.kind}")
    
    @override
    async def loop_once(self):
        if self.disabled or self._closed:
            return
        # Batch-drain ALL items from send queues
        msgs = []
        audios = []
        videos = []
        for q, dest in ((self.msg_send_queue, msgs), (self.audio_send_queue, audios), (self.video_send_queue, videos)):
            while not q.empty():
                try:
                    dest.append(q.get_nowait())
                except asyncio.QueueEmpty:
                    break
        coros_drain = []
        for m in msgs:
            coros_drain.append(self.on_msg(m))
        for a in audios:
            coros_drain.append(self.on_audio(a))
        # Video: keep only the LAST frame per sender to minimize latency
        latest_video: dict[str, 'RTCMediaMsg'] = {}
        for v in videos:
            latest_video[v.from_candidate or ''] = v
        for v in latest_video.values():
            coros_drain.append(self.on_video(v))
        if coros_drain:
            await asyncio.gather(*coros_drain, return_exceptions=True)
        
        coros = []
        curr_time = datetime.now()
        self_id = self.id
        
        min_rms = int(getattr(ChatRoomConfig.GetConfig().audio_config, 'min_energy_rms', 200) or 200)

        def _frame_is_voice(frame: AudioFrame) -> bool:
            try:
                plane = bytes(frame.planes[0])
                if not plane:
                    return False
                rms = audioop.rms(plane, 2)
                return rms >= min_rms
            except Exception:
                return False

        async def recv_audio(audio_receive_track: RemoteStreamTrack):
            try:
                frame = await asyncio.wait_for(audio_receive_track.recv(), timeout=0.02)
            except asyncio.TimeoutError:
                return
            except Exception:
                return
            if not self.muted:
                is_voice = _frame_is_voice(frame)   # type: ignore
                coros = []
                for c in self.room.candidates.values():
                    if c == self or c.disabled or c._closed or c.deafen:
                        continue
                    if isinstance(c, UserCandidate) and c.audio_send_tracks.get(self_id) is not None:
                        # Direct relay path
                        msg = RTCMediaMsg(
                            data=frame, type='audio', from_candidate=self_id,   # type: ignore
                            time=curr_time, duration_ms=20, is_voice=is_voice,
                        )
                        coros.append(c.on_audio(msg))
                    else:
                        coros.append(c.send_audio(frame, from_candidate=self_id, time=curr_time, is_voice=is_voice))    # type: ignore
                if coros:
                    await asyncio.gather(*coros)

        async def recv_video(video_receive_track: RemoteStreamTrack):
            try:
                frame = await asyncio.wait_for(video_receive_track.recv(), timeout=0.005)
            except asyncio.TimeoutError:
                return
            except Exception:
                return
            if isinstance(frame, VideoFrame):
                frame = frame.reformat(format="yuv420p")
            async def send_video_to_all(video_frame: VideoFrame):
                coros = []
                for c in self.room.candidates.values():
                    if c != self and not c.disabled and not c._closed:  
                        coros.append(c.send_video(video_frame, from_candidate=self_id, time=curr_time))
                if coros:
                    await asyncio.gather(*coros, return_exceptions=True)
            
            await send_video_to_all(frame)  # type: ignore
            
        if self.audio_receive_track:
            coros.append(recv_audio(self.audio_receive_track))
        if self.video_receive_track:
            coros.append(recv_video(self.video_receive_track))
        
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)
         
class AgentCandidate(Candidate):
    ...

# region scheduler base
_all_orchestrator_classes: dict[str, type["SchedulerCandidate"]] = {}

class SchedulerCreationParamData(_AutoDocstringModel):
    key: str
    '''SchedulerCandidate类的注册key.'''
    
    def create(self, room: "WebRTCRoom")->"SchedulerCandidate":
        if not (cls := SchedulerCandidate.GetClass(self.key)):
            raise ValueError(f"No SchedulerCandidate class registered with key '{self.key}'")
        return cls.Create(self, room=room)

def _validate_creation_param(v):
    if isinstance(v, str):
        v = v.strip()
        if v.startswith('{') and v.endswith('}'):
            try:
                v_dict = json.loads(v)
                if isinstance(v_dict, dict):
                    v = v_dict
            except:
                pass
        elif v in _all_orchestrator_classes:
            v = {"key": v}
    if isinstance(v, dict):
        if (key := v.get("key")) and isinstance(key, str):
            if not (cls := SchedulerCandidate.GetClass(key)):
                raise ValueError(f"Invalid SchedulerCreationParamData: no SchedulerCandidate class registered with key '{key}'")
            return cls.CreationRequestType.model_validate(v)  # type: ignore
        else:
            raise ValueError("Invalid SchedulerCreationParamData: missing or invalid 'key'")
    return SchedulerCreationParamData.model_validate(v)

type SchedulerCreationParam = SerializeAsAny[Annotated[SchedulerCreationParamData, BeforeValidator(_validate_creation_param)]]

class SchedulerCandidate[CT: SchedulerCreationParamData](Candidate):
    
    if TYPE_CHECKING:
        CreationRequestType: type[CT]
    else:
        def __init__(self, /, **kwargs):
            if 'hidden' not in kwargs:
                kwargs['hidden'] = True
            super().__init__(**kwargs)
    
    def __init_subclass__(cls, key: str):
        super().__init_subclass__()
        key = key.strip()
        assert key and key not in _all_orchestrator_classes, f"Orchestrator class key '{key}' is already registered"
        _all_orchestrator_classes[key] = cls
        
        def get_cls_args(c):
            if c == SchedulerCandidate:
                return SchedulerCandidate.__type_params__
            else:
                super_base_args = get_cls_args(c.__bases__[0]) 
                c_type_params = c.__type_params__
                orig_base = c.__orig_bases__[0]
                super_args = getattr(orig_base, "__args__", ()) or ()
                super_type_params = c.__bases__[0].__type_params__
                super_type_map = dict(zip(super_type_params, super_args))
                tidied = []
                for a in super_base_args:
                    if isinstance(a, TypeVar):
                        tidied.append(super_type_map.pop(a, a))
                    else:
                        tidied.append(a)
                for a in c_type_params:
                    if a not in tidied:
                        tidied.append(a)
                return tidied
        
        cls_generic_args = get_cls_args(cls)
        if cls_generic_args:
            ct = cls_generic_args[0]
            if isinstance(ct, TypeVar):
                cls.CreationRequestType = SchedulerCreationParamData   # type: ignore
            else:
                cls.CreationRequestType = ct   # type: ignore
        else:
            cls.CreationRequestType = SchedulerCreationParamData   # type: ignore
    
    @staticmethod
    def GetClass(key: str) -> type["SchedulerCandidate"]|None:
        return _all_orchestrator_classes.get(key)
    
    @classmethod
    def Create(cls, param: CT, room: "WebRTCRoom") -> Self:
        ...
    
    
# endregion

__all__ = [
    'IceConnectionState',
    'RTCMediaMsg',
    'Candidate',
    'UserCandidate',
    'AgentCandidate',
    
    'SchedulerCandidate',
    'SchedulerCreationParamData'
]
