from typing import ClassVar, Self

from pydantic import BaseModel, Field


class _AutoDocstringModel(BaseModel, use_attribute_docstrings=True): ...


class AudioConfig(_AutoDocstringModel):
    """Audio processing config."""

    audio_sample_rate: int = 16000
    min_silence_ms: int = 1000
    min_voice_ms: int = 200
    mid_silence_ms: int = 500
    max_segment_ms: int = 10000
    min_energy_rms: int = 200


class WebRTCIceServer(_AutoDocstringModel):
    """ICE server config."""

    urls: str | list[str]
    username: str | None = None
    credential: str | None = None


class WebRTCConfiguration(_AutoDocstringModel):
    """WebRTC runtime config."""

    iceServers: list[WebRTCIceServer] | None = None
    bundlePolicy: str = "balanced"

    def to_aiortc_config(self):
        from aiortc import RTCConfiguration, RTCIceServer

        ice_servers: list[RTCIceServer] = []
        for server in self.iceServers or []:
            urls = server.urls if isinstance(server.urls, list) else [server.urls]
            ice_servers.append(
                RTCIceServer(
                    urls=urls,
                    username=server.username,
                    credential=server.credential,
                )
            )
        return RTCConfiguration(iceServers=ice_servers)


class ChatRoomConfig(_AutoDocstringModel):
    """Chat room runtime config singleton."""

    __Instance__: ClassVar[Self | None] = None

    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    rtc_config: WebRTCConfiguration | None = None

    @classmethod
    def SetConfig(cls, config: Self) -> None:
        cls.__Instance__ = config

    @classmethod
    def GetConfig(cls) -> Self:
        if cls.__Instance__ is None:
            cls.__Instance__ = cls()
        return cls.__Instance__


__all__ = [
    "AudioConfig",
    "ChatRoomConfig",
    "WebRTCConfiguration",
    "WebRTCIceServer",
]
