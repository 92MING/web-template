import asyncio
import logging

from abc import abstractmethod
from fractions import Fraction
from typing import Final, Literal, override

from aiortc import MediaStreamError
from aiortc import MediaStreamTrack as _MediaStreamTrack
from av import AudioFrame, Packet, VideoFrame
from av.audio.resampler import AudioResampler

_logger = logging.getLogger(__name__)

_STAT_LOG_INTERVAL: Final[int] = 250
_AUDIO_MAX_QUEUE: Final[int] = 10


class MediaStreamTrack(_MediaStreamTrack):
    data_queue: asyncio.Queue

    def __init__(self):
        super().__init__()
        self.data_queue = asyncio.Queue()

    @abstractmethod
    async def recv(self) -> Packet:
        raise NotImplementedError

    async def send(self, data):
        await self.data_queue.put(data)

    async def on_end(self) -> None: ...


class AudioSendTrack(MediaStreamTrack):
    kind: Final[Literal["audio"]] = "audio"

    sample_rate: int
    sample_width: int
    channels: int
    frame_duration_ms: int
    _layout: str
    _time_base: Fraction
    _silence_bytes: bytes
    _current_sender: str | None
    _resampler: AudioResampler

    def __init__(
        self,
        sample_rate: int = 48000,
        sample_width: int = 2,
        channels: int = 1,
        frame_duration_ms: int = 20,
    ):
        super().__init__()
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.samples_per_frame = int(sample_rate * frame_duration_ms / 1000)
        self.bytes_per_frame = self.samples_per_frame * sample_width * channels
        self._timestamp = 0
        self._current_sender = None
        self._layout = "mono" if channels == 1 else "stereo"
        self._time_base = Fraction(1, sample_rate)
        self._silence_bytes = b"\x00" * self.bytes_per_frame
        self._recv_timeout = frame_duration_ms * 3 / 1000
        self._resampler = AudioResampler(format="s16", layout=self._layout, rate=sample_rate)
        self._stat_total = 0
        self._stat_silence = 0
        self._stat_real = 0

    @override
    async def send(self, data: AudioFrame | bytes, sender: str | None = None):
        self._current_sender = sender
        while self.data_queue.qsize() > _AUDIO_MAX_QUEUE:
            try:
                self.data_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        await self.data_queue.put(data)

    @property
    def current_sender(self) -> str | None:
        return self._current_sender

    def _log_stats(self, extra: str = "") -> None:
        if self._stat_total % _STAT_LOG_INTERVAL != 0:
            return
        pct = self._stat_silence / self._stat_total * 100 if self._stat_total else 0
        _logger.info(
            f"[AST stats] total={self._stat_total} real={self._stat_real} "
            f"silence={self._stat_silence} ({pct:.0f}%){extra}"
        )

    @override
    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError

        try:
            data = await asyncio.wait_for(self.data_queue.get(), timeout=self._recv_timeout)
        except asyncio.TimeoutError:
            data = None

        self._stat_total += 1

        if isinstance(data, AudioFrame):
            frames = self._resampler.resample(data)
            if frames:
                out = frames[0]
                out.pts = self._timestamp
                out.time_base = self._time_base
                out.sample_rate = self.sample_rate
                self._timestamp += out.samples
                self._stat_real += 1
                self._log_stats(f" samples={out.samples} rate={out.sample_rate}")
                return out

        self._stat_silence += 1
        self._log_stats()

        frame = AudioFrame(format="s16", layout=self._layout, samples=self.samples_per_frame)
        frame.pts = self._timestamp
        frame.time_base = self._time_base
        frame.sample_rate = self.sample_rate

        if isinstance(data, bytes) and len(data) >= self.bytes_per_frame:
            frame.planes[0].update(data[: self.bytes_per_frame])
        else:
            frame.planes[0].update(self._silence_bytes)

        self._timestamp += self.samples_per_frame
        return frame


class VideoSendTrack(MediaStreamTrack):
    kind: Final[Literal["video"]] = "video"

    width: int
    height: int
    fps: int
    _time_base: Fraction

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
    ):
        super().__init__()
        self.width = width
        self.height = height
        self.fps = fps
        self._time_base = Fraction(1, fps)
        self._timestamp = 0
        self._last_frame: VideoFrame | None = None
        self._last_frame_hold = 0
        self._max_hold_frames = 30

    def update_format(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        if self.width == width and self.height == height:
            return
        self.width = width
        self.height = height
        self._last_frame = None
        self._last_frame_hold = 0

    @override
    async def send(self, data: VideoFrame | bytes):
        while self.data_queue.qsize() > 0:
            try:
                self.data_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        await self.data_queue.put(data)

    def _make_frame(
        self,
        *,
        y_data: bytes | None = None,
        u_data: bytes | None = None,
        v_data: bytes | None = None,
    ) -> VideoFrame:
        y_size = self.width * self.height
        uv_size = y_size // 4
        frame = VideoFrame(width=self.width, height=self.height, format="yuv420p")
        frame.pts = self._timestamp
        frame.time_base = self._time_base
        frame.planes[0].update(y_data if y_data is not None else b"\x00" * y_size)
        frame.planes[1].update(u_data if u_data is not None else b"\x80" * uv_size)
        frame.planes[2].update(v_data if v_data is not None else b"\x80" * uv_size)
        return frame

    @override
    async def recv(self) -> VideoFrame:
        if self.readyState != "live":
            raise MediaStreamError

        try:
            data = await asyncio.wait_for(self.data_queue.get(), timeout=1.0 / self.fps)
        except asyncio.TimeoutError:
            data = None

        if isinstance(data, VideoFrame):
            data.pts = self._timestamp
            data.time_base = self._time_base
            self._last_frame = data
            self._last_frame_hold = 0
            self._timestamp += 1
            return data

        if isinstance(data, bytes):
            y_size = self.width * self.height
            uv_size = y_size // 4
            frame_size = y_size + uv_size * 2
            if len(data) >= frame_size:
                frame = self._make_frame(
                    y_data=data[:y_size],
                    u_data=data[y_size : y_size + uv_size],
                    v_data=data[y_size + uv_size :],
                )
                self._last_frame = frame
                self._last_frame_hold = 0
                self._timestamp += 1
                return frame

        if self._last_frame is not None and self._last_frame_hold < self._max_hold_frames:
            self._last_frame.pts = self._timestamp
            self._last_frame.time_base = self._time_base
            self._last_frame_hold += 1
            self._timestamp += 1
            return self._last_frame

        frame = self._make_frame()
        self._timestamp += 1
        return frame


__all__ = [
    "AudioSendTrack",
    "MediaStreamTrack",
    "VideoSendTrack",
]
