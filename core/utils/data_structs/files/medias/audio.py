"""Audio model with deferred loading and pydantic support."""
import os

from io import BytesIO
from urllib.parse import urlparse
from pathlib import Path
from typing_extensions import override
from pydantic_core import core_schema
from pydub import AudioSegment
from pydub.silence import split_on_silence as _split_on_silence
from typing import Any, ClassVar, Coroutine, Literal, Self, Sequence, TYPE_CHECKING, TypeAlias, overload

from ....type_utils import bytes_to_base64
from ....concurrent_utils import run_any_func, is_async_callable
from .loader import save_get_file_source, AcceptableFileSource
from ._utils import _hash_md5, _try_get_from_dict, _get_media_json_schema, _dump_media_dict

if TYPE_CHECKING:
    _AudioBase = AudioSegment
else:
    _AudioBase = object

AudioFormat: TypeAlias = Literal["wav", "mp3", "aac", "flac", "opus", "ogg", "m4a", "wma"]
'''Supported non-stream response audio formats.'''
StreamableAudioFormat: TypeAlias = Literal["wav", "opus", "aac", "mp3"]
'''Supported streamable audio formats. Note that this is a subset of `AudioFormat`'''

_SUPPORTED_AUDIO_FORMATS = frozenset({"wav", "mp3", "aac", "flac", "opus", "ogg", "m4a", "wma"})
_AUDIO_FORMAT_ALIASES = {
    'mpeg': 'mp3',
    'x-wav': 'wav',
    'wave': 'wav',
    'x-flac': 'flac',
    'mp4': 'm4a',
    'x-m4a': 'm4a',
    'x-ms-wma': 'wma',
}

def _normalize_audio_format(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().lstrip('.')
    if not normalized:
        return None
    if normalized.startswith('audio/'):
        normalized = normalized.split('/', 1)[1]
    normalized = normalized.split(';', 1)[0]
    normalized = _AUDIO_FORMAT_ALIASES.get(normalized, normalized)
    return normalized if normalized in _SUPPORTED_AUDIO_FORMATS else None

def _infer_audio_format_from_bytes(source: bytes) -> str | None:
    if not source:
        return None
    preview = source[:512]
    if len(preview) >= 12 and preview[:4] == b'RIFF' and preview[8:12] == b'WAVE':
        return 'wav'
    if preview.startswith(b'fLaC'):
        return 'flac'
    if preview.startswith(b'OggS'):
        if b'OpusHead' in preview[:64]:
            return 'opus'
        return 'ogg'
    if preview.startswith(b'ID3'):
        return 'mp3'
    if len(preview) >= 2 and preview[0] == 0xFF and (preview[1] & 0xE0) == 0xE0:
        # ADTS AAC headers are a stricter subset of MPEG frame sync.
        if (preview[1] & 0xF6) == 0xF0:
            return 'aac'
        return 'mp3'
    if len(preview) >= 12 and preview[4:8] == b'ftyp':
        return 'm4a'
    if preview.startswith(b'\x30\x26\xb2\x75\x8e\x66\xcf\x11'):
        return 'wma'
    return None

def _infer_audio_format_from_source(source: Any) -> str | None:
    if isinstance(source, Path):
        return _normalize_audio_format(source.suffix)
    if isinstance(source, str):
        stripped = source.strip()
        if stripped.startswith('data:audio/'):
            return _normalize_audio_format(stripped.split(':', 1)[1].split(';', 1)[0])
        parsed = urlparse(stripped)
        if parsed.scheme and parsed.path:
            return _normalize_audio_format(Path(parsed.path).suffix)
        return _normalize_audio_format(Path(stripped).suffix)
    if isinstance(source, bytes):
        return _infer_audio_format_from_bytes(source)
    if isinstance(source, BytesIO):
        name = getattr(source, 'name', None)
        return _infer_audio_format_from_source(name) or _infer_audio_format_from_bytes(source.getbuffer()[:512])
    return _normalize_audio_format(getattr(source, '_origin_format', None))

def _load_audio_segment(
    source: BytesIO,
    *,
    format_hint: str | None = None,
    frame_rate: int | None = None,
    channels: int | None = None,
    sample_width: int | None = None,
) -> tuple[Any, str | None]:
    buffer = source.getbuffer()
    if len(buffer) <= 0:
        raise ValueError('Audio source is empty.')

    inferred_format = format_hint or _infer_audio_format_from_bytes(buffer[:512])
    load_kwargs: dict[str, Any] = {}
    if inferred_format is not None:
        load_kwargs['format'] = inferred_format
    if frame_rate is not None:
        load_kwargs['frame_rate'] = frame_rate
    if channels is not None:
        load_kwargs['channels'] = channels
    if sample_width is not None:
        load_kwargs['sample_width'] = sample_width
    source.seek(0)
    return AudioSegment.from_file(source, **load_kwargs), inferred_format


# ── AudioSegment attribute set for __getattr__ delegation ─────────────────────

_pydub_attrs: set[str] | None = None

def _get_pydub_attrs() -> set[str]:
    global _pydub_attrs
    if _pydub_attrs is None:
        _pydub_attrs = set(dir(AudioSegment))
        if hasattr(AudioSegment, '__annotations__'):
            _pydub_attrs.update(AudioSegment.__annotations__.keys())
    return _pydub_attrs


# ── _AudioRetWrapper ──────────────────────────────────────────────────────────
class _AudioRetWrapper:
    def __init__(self, f):
        self.f = f
        if hasattr(self.f, '__doc__'):
            self.__doc__ = self.f.__doc__

    def __getattr__(self, name: str):
        return getattr(self.f, name)

    def __is_async_func__(self) -> bool:
        return is_async_callable(self.f)

    @staticmethod
    def _recursive_cast(r):
        if isinstance(r, AudioSegment) and not isinstance(r, Audio):
            new_audio = Audio.__new__(Audio)
            new_audio._source = r
            new_audio._audio = r
            new_audio._loaded = True
            new_audio.start_time = getattr(r, 'start_time', 0.0)
            new_audio._end_time = getattr(r, '_end_time', None)
            return new_audio
        elif isinstance(r, (list, tuple, set)):
            return type(r)(_AudioRetWrapper._recursive_cast(i) for i in r)
        elif isinstance(r, dict):
            return type(r)({k: _AudioRetWrapper._recursive_cast(v) for k, v in r.items()})
        return r

    def __call__(self, *args, **kwargs):
        r = self.f(*args, **kwargs)
        if isinstance(r, Coroutine):
            async def wrapper():
                coro_r = await r
                return _AudioRetWrapper._recursive_cast(coro_r)
            return wrapper()
        return _AudioRetWrapper._recursive_cast(r)


# ── Audio ────────────────────────────────────────────────────────────────────

_AUDIO_OWN_ATTRS = frozenset({
    '_source', '_audio', '_loaded', 'start_time', '_end_time', '_origin_format',
    'Abstract', 'Type', 'TypeNames', 'Suffixes', 'MimePrefixes',
    'load', '_ensure_loaded',
    'end_time', 'frame_size', 'format',
    'to_bytes', 'to_base64', 'to_md5_hash',
    'copy', 'split_on_silence', 'reduce_noise',
    'append', 'prepend', 'CastAudio',
    'pydantic_dump', 'to_llm', 'save',
    '__init__', '__repr__', '__class__', '__dict__',
    '__getattr__', '__getattribute__', '__setattr__',
    '__get_pydantic_core_schema__', '__get_pydantic_json_schema__',
    '__module__', '__doc__', '__weakref__', '__annotations__',
    '__dir__', '__getitem__', '__md5_cache__',
})

class Audio(_AudioBase):
    '''Advanced audio model with deferred loading and pydantic support.

    Available deserialization formats:
     - Path: the path to the audio file
     - str: the path to the audio file / base64 string / URL
     - bytes: the bytes of the audio
     - AudioSegment: the audio segment object
     - dict: keys: voice/sound/audio/data/source/url
    '''

    Abstract: ClassVar[bool] = False
    Type: ClassVar[str] = 'audio'
    TypeNames: ClassVar[tuple[str, ...]] = ('voice', 'sound', 'wav', 'mp3', 'aac', 'flac', 'opus', 'ogg', 'm4a', 'wma')
    Suffixes: ClassVar[tuple[str, ...]] = ('.wav', '.mp3', '.aac', '.flac', '.opus', '.ogg', '.m4a', '.wma')
    MimePrefixes: ClassVar[tuple[str, ...]] = ('data:audio/',)
    MimeTypes: ClassVar[tuple[str, ...]] = ('audio/wav', 'audio/mpeg', 'audio/aac', 'audio/flac', 'audio/opus', 'audio/ogg', 'audio/x-m4a', 'audio/x-wma')

    _source: Any
    _audio: AudioSegment | None
    _loaded: bool
    start_time: float
    _end_time: float | None
    _origin_format: str | None

    def __init__(self, source: 'AcceptableFileSource | AudioSegment | Audio', /, **kwargs: Any):  # type: ignore[type-arg]
        origin_format = _normalize_audio_format(
            kwargs.get('format') or kwargs.get('source_format') or kwargs.get('origin_format')
        )
        if isinstance(source, Audio):
            self._source = source._source
            self._audio = source._audio
            self._loaded = source._loaded
            self.start_time = source.start_time
            self._end_time = source._end_time
            self._origin_format = source._origin_format
            return
        elif isinstance(source, AudioSegment):
            self._source = source
            self._audio = source
            self._loaded = True
            self.start_time = getattr(source, 'start_time', 0.0)
            self._end_time = getattr(source, '_end_time', None)
            self._origin_format = origin_format or _normalize_audio_format(getattr(source, '_origin_format', None))
            return
        else:
            # Quick type compatibility check for FileID sources
            from ..base import _check_source_file_type_compat
        self._source_file_type = _check_source_file_type_compat(self.Type, self.TypeNames, source, self.Suffixes, ('video',))
        self._source = source
        self._audio = None
        self._loaded = False
        self.start_time = 0.0
        self._end_time = None
        self._origin_format = origin_format or _infer_audio_format_from_source(source)

    # ── loading ──────────────────────────────────────────────────────────

    async def load(self) -> Self:
        """Load the audio data from source. Idempotent."""
        if self._loaded:
            return self
        source = self._source

        # Special case: video source – extract audio track
        if getattr(self, '_source_file_type', None) == 'video':
            from .video import Video
            v = Video(source)
            audio_model = v.get_audio_model()
            if audio_model is None:
                raise ValueError('Video source has no audio track to extract.')
            self._audio = audio_model._ensure_loaded()
            self._loaded = True
            return self

        def is_path(source):
            if isinstance(source, Path):
                return source.is_file()
            elif isinstance(source, str) and len(source) < 4096:
                return os.path.isfile(source)
            return False
        
        if is_path(source):
            seg = AudioSegment.from_file(source)
            self._audio = seg
            self._loaded = True
            self._origin_format = self._origin_format or _normalize_audio_format(Path(source).suffix)
            if not self._origin_format:
                self._origin_format = _infer_audio_format_from_source(source)
            return self
        else:        
            data_io = await save_get_file_source(source)  # type: ignore
            self._audio, inferred_format = _load_audio_segment(data_io, format_hint=self._origin_format)
            self._origin_format = self._origin_format or inferred_format
            self._loaded = True
            return self

    def _ensure_loaded(self)->AudioSegment:
        """Synchronously ensure the audio is loaded."""
        if not self._loaded:
            run_any_func(self.load)
        return self._audio  # type: ignore

    # ── AudioSegment delegation ──────────────────────────────────────────

    if not TYPE_CHECKING:
        def __getattr__(self, name: str):
            if name in _AUDIO_OWN_ATTRS or (name.startswith('__') and name.endswith('__')):
                raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
            pydub_attrs = _get_pydub_attrs()
            if name in pydub_attrs:
                audio = self._ensure_loaded()
                attr = getattr(audio, name)
                if callable(attr) and not isinstance(attr, type):
                    return _AudioRetWrapper(attr)
                return attr
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    # ── dunder delegation ────────────────────────────────────────────────

    def __len__(self) -> int:
        """Length in milliseconds, delegated to AudioSegment."""
        return len(self._ensure_loaded())

    # ── properties ───────────────────────────────────────────────────────

    @property
    def end_time(self) -> float:
        return self._end_time if self._end_time is not None else self._ensure_loaded().duration_seconds

    @property
    def frame_size(self) -> int:
        '''Frame size of the audio, in bytes.'''
        a = self._ensure_loaded()
        return a.frame_rate * a.frame_width

    @property
    def format(self) -> str | None:
        return self._origin_format

    # ── core methods ─────────────────────────────────────────────────────

    def to_bytes(self, format: str = 'wav') -> bytes:
        '''Get the data of this audio in bytes format.'''
        buffer = BytesIO()
        self._ensure_loaded().export(buffer, format=format)
        return buffer.getvalue()

    def to_base64(self, format: str = 'wav', url_scheme: bool = False) -> str:
        b64 = bytes_to_base64(self.to_bytes(format=format))
        if url_scheme:
            return f'data:audio/{format.lower()};base64,{b64}'
        return b64

    def to_md5_hash(self, format: str = 'wav') -> str:
        if '__md5_cache__' not in self.__dict__:
            self.__md5_cache__: dict[str, str] = {}
        if format not in self.__md5_cache__:
            self.__md5_cache__[format] = _hash_md5(self.to_bytes(format=format))
        return self.__md5_cache__[format]

    def copy(self) -> Self:
        '''Copy the audio object.'''
        a = self._ensure_loaded()
        new_seg = AudioSegment(a._data, sample_width=a.sample_width, frame_rate=a.frame_rate, channels=a.channels)
        return type(self)(new_seg)

    def split_on_silence(
        self,
        min_silence_len: int = 500,
        silence_threshold: int | None = None,
        keep_silence: int | bool = 100,
        seek_step: int = 1,
    ) -> list[Self]:
        a = self._ensure_loaded()
        threshold_int: int = silence_threshold if silence_threshold is not None else int(2 * a.dBFS)
        if threshold_int == -float("infinity"):  # type: ignore
            threshold_int = -32
        segs = _split_on_silence(a, min_silence_len=min_silence_len, silence_thresh=threshold_int,
                                 keep_silence=keep_silence, seek_step=seek_step)
        return [type(self)(seg) for seg in segs]    # type: ignore

    def reduce_noise(
        self,
        stationary: bool = False,
        prop_decrease: float = 1.0,
        time_constant_s: float = 2.0,
        freq_mask_smooth_hz: int = 500,
        time_mask_smooth_ms: int = 50,
        thresh_n_mult_nonstationary: int = 2,
        sigmoid_slope_nonstationary: int = 10,
        n_std_thresh_stationary: float = 1.5,
        chunk_size: int = 600000,
        padding: int = 30000,
        n_fft: int = 1024,
        win_length: int | None = None,
        hop_length: int | None = None,
    ) -> Self:
        '''Reduce noise in the audio (return a new audio object).'''
        a = self._ensure_loaded()
        audio_arr = a.get_array_of_samples()
        try:
            from noisereduce import reduce_noise as _reduce_noise
        except ImportError:
            raise ImportError('noisereduce package is required for noise reduction. pip install noisereduce')
        reduced_noise = _reduce_noise(
            audio_arr,
            a.frame_rate,
            stationary=stationary,
            prop_decrease=prop_decrease,
            time_constant_s=time_constant_s,
            freq_mask_smooth_hz=freq_mask_smooth_hz,
            time_mask_smooth_ms=time_mask_smooth_ms,
            thresh_n_mult_nonstationary=thresh_n_mult_nonstationary,
            sigmoid_slope_nonstationary=sigmoid_slope_nonstationary,
            n_std_thresh_stationary=n_std_thresh_stationary,
            chunk_size=chunk_size,
            padding=padding,
            n_fft=n_fft,
            win_length=win_length,
            hop_length=hop_length,
        )
        new_audio = AudioSegment(
            reduced_noise.tobytes(),
            frame_rate=a.frame_rate,
            sample_width=a.sample_width,
            channels=a.channels,
        )
        return type(self)(new_audio)

    @override
    def append(
        self,
        seg: 'Audio | AudioSegment | bytes | str',
        crossfade: int = 100,
        noise_reduce: bool = False,
        adjust_dBFS: bool = False,
    ) -> Self:
        a = self._ensure_loaded()
        if isinstance(seg, Audio):
            new_start = min(self.start_time, seg.start_time)
            new_end = max(self.end_time, seg.end_time)
        else:
            new_start = new_end = None  # type: ignore

        if not isinstance(seg, Audio):
            seg = type(self)(seg)
        seg_audio = seg._ensure_loaded()

        if noise_reduce:
            seg = seg.reduce_noise()
            seg_audio = seg._ensure_loaded()

        if adjust_dBFS:
            diff = a.dBFS - seg_audio.dBFS
            if diff != 0:
                seg_audio = seg_audio.apply_gain(diff)

        new_seg = AudioSegment.append(a, seg_audio, crossfade=crossfade)  # type: ignore
        result = type(self)(new_seg)
        if new_start is not None and new_end is not None:
            result.start_time = new_start
            result._end_time = new_end
        return result

    def prepend(
        self,
        seg: 'Audio | AudioSegment | bytes | str',
        crossfade: int = 100,
        noise_reduce: bool = False,
        adjust_dBFS: bool = False,
    ) -> Self:
        a = self._ensure_loaded()
        if isinstance(seg, Audio):
            new_start = min(self.start_time, seg.start_time)
            new_end = max(self.end_time, seg.end_time)
        else:
            new_start = new_end = None  # type: ignore

        if not isinstance(seg, Audio):
            seg = type(self)(seg)
        seg_audio = seg._ensure_loaded()

        if noise_reduce:
            seg = seg.reduce_noise()
            seg_audio = seg._ensure_loaded()

        if adjust_dBFS:
            diff = a.dBFS - seg_audio.dBFS
            if diff != 0:
                seg_audio = seg_audio.apply_gain(diff)

        new_seg = AudioSegment.append(seg_audio, a, crossfade=crossfade)  # type: ignore
        result = type(self)(new_seg)
        if new_start is not None and new_end is not None:
            result.start_time = new_start
            result._end_time = new_end
        return result

    @classmethod
    def CastAudio(cls, audio: 'AudioSegment') -> Self:
        '''Wrap a raw AudioSegment as our Audio.'''
        if isinstance(audio, cls):
            return audio
        return cls(audio)

    def save(self, path: str | Path, *args: Any, format: str | None = None, **kwargs: Any) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fmt = format or target.suffix.lstrip('.').lower() or 'wav'
        a = self._ensure_loaded()
        a.export(str(target), format=fmt, *args, **kwargs)
        return str(target)

    def pydantic_dump(self) -> dict[str, Any]:
        return _dump_media_dict(self.to_base64(), type(self))

    def to_llm(self, **kwargs: Any) -> Sequence['Audio']:
        return [self]
    
    @overload
    def __getitem__(self, millisecond: int) -> 'Self': ...
    @overload
    def __getitem__(self, millisecond: slice) -> 'list[Self]': ...
    
    def __getitem__(self, millisecond: slice | int):
        a = self._ensure_loaded()
        from pydub import AudioSegment as AS_cls
        r = AS_cls.__getitem__(a, millisecond)
        if isinstance(r, (list, tuple)):
            return [type(self)(seg) for seg in r]   # type: ignore
        result = type(self)(r)  # type: ignore
        if isinstance(millisecond, slice):
            start = millisecond.start if millisecond.start is not None else 0
            end = millisecond.stop if millisecond.stop is not None else len(a)
            start = min(start, len(a))
            end = min(end, len(a))
        else:
            start = millisecond
            end = millisecond + 1
        result.start_time = start / 1000
        result._end_time = end / 1000
        return result

    def __repr__(self) -> str:
        if self._loaded and self._audio:
            return f'<{type(self).__name__} duration={self._audio.duration_seconds:.2f}s>'
        return f'<{type(self).__name__} (not loaded)>'

    # ── pydantic integration ─────────────────────────────────────────────

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        def validator(data):
            if isinstance(data, dict):
                type_name = _try_get_from_dict(data, 'type', 'Type')
                if isinstance(type_name, str) and type_name.lower() not in('audio', 'video'):
                    raise ValueError(f'Invalid audio data type: {type_name}')
                data = _try_get_from_dict(data, 'data', 'content', 'audio', 'voice', 'sound', 'source', 'url')
                if not data:
                    raise ValueError('No valid audio data found')

            if isinstance(data, cls):
                return data
            return cls(data)

        def serializer(audio: 'Audio'):
            if not audio._loaded:
                if isinstance(audio._source, (str, Path)):
                    return _dump_media_dict(str(audio._source), cls)
                audio._ensure_loaded()
            return _dump_media_dict(audio.to_base64(), cls)

        validate_schema = core_schema.no_info_after_validator_function(validator, core_schema.any_schema())
        serialize_schema = core_schema.plain_serializer_function_ser_schema(serializer)
        return core_schema.json_or_python_schema(
            json_schema=validate_schema,
            python_schema=validate_schema,
            serialization=serialize_schema,
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, cs, handler):
        return _get_media_json_schema(cls)


# Make isinstance(Audio(...), pydub.AudioSegment) work
def _patch_pydub_isinstance():
    try:
        original_meta = type(AudioSegment)
        if not hasattr(original_meta, '_audio_patched'):
            _orig_instancecheck = original_meta.__instancecheck__

            def __instancecheck__(self, instance):
                if type(instance) is Audio or (hasattr(type(instance), '__mro__') and Audio in type(instance).__mro__):
                    return True
                return _orig_instancecheck(self, instance)  # type: ignore

            original_meta.__instancecheck__ = __instancecheck__ # type: ignore
            original_meta._audio_patched = True  # type: ignore
    except Exception:
        pass


_patch_pydub_isinstance()


__all__ = ['Audio', 'AudioFormat', 'StreamableAudioFormat']
