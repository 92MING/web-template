'''
chat_room 配置模块。

提供 `_AutoDocstringModel` 基类以及 `ChatRoomConfig` 单例，
替代原 v2 项目中对 `utils.config` 的依赖。
'''


from typing import ClassVar, Self
from pydantic import BaseModel, Field


class _AutoDocstringModel(BaseModel, use_attribute_docstrings=True): ...


class AudioConfig(_AutoDocstringModel):
    '''音频处理配置。'''
    audio_sample_rate: int = 16000
    '''默认采样率 (Hz)。'''
    min_silence_ms: int = 1000
    '''判断语音段结束的最小静音时长 (ms)。'''
    min_voice_ms: int = 200
    '''最小有效语音段时长 (ms)。'''
    mid_silence_ms: int = 500
    '''TTS 段间插入的静音时长 (ms)。'''
    max_segment_ms: int = 10000
    '''单段语音最大时长 (ms)。'''
    min_energy_rms: int = 200
    '''能量 VAD 的最小 RMS 门限。'''


class WebRTCIceServer(_AutoDocstringModel):
    '''ICE server 配置。'''
    urls: str | list[str]
    username: str | None = None
    credential: str | None = None


class WebRTCConfiguration(_AutoDocstringModel):
    '''WebRTC 配置。'''
    iceServers: list[WebRTCIceServer] | None = None
    bundlePolicy: str = 'balanced'

    def to_aiortc_config(self):
        '''转换为 aiortc.RTCConfiguration。'''
        from aiortc import RTCConfiguration, RTCIceServer  # type: ignore
        ice_servers = None
        if self.iceServers:
            ice_servers = []
            for s in self.iceServers:
                urls = s.urls if isinstance(s.urls, list) else [s.urls]
                ice_servers.append(RTCIceServer(urls=urls, username=s.username, credential=s.credential))
        return RTCConfiguration(iceServers=ice_servers or [])


class ChatRoomConfig(_AutoDocstringModel):
    '''Chat room 运行时配置单例。'''

    __Instance__: ClassVar[Self | None] = None

    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    '''音频处理配置。'''
    rtc_config: WebRTCConfiguration | None = None
    '''WebRTC 配置（ICE servers 等）。为 None 时使用 aiortc 默认配置。'''

    @classmethod
    def SetConfig(cls, config: Self):
        cls.__Instance__ = config

    @classmethod
    def GetConfig(cls) -> Self:
        if cls.__Instance__ is None:
            cls.__Instance__ = cls()
        return cls.__Instance__


__all__ = [
    'AudioConfig',
    'WebRTCIceServer',
    'WebRTCConfiguration',
    'ChatRoomConfig',
]
