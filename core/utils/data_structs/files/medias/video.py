import os
import base64
import hashlib
import tempfile
import numpy as np

from io import BytesIO
from pathlib import Path
from functools import partial
from pydantic_core import core_schema
from typing import Any, ClassVar, Self, Callable, Sequence, TYPE_CHECKING, TypeAlias, Literal

from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.video.io.ffmpeg_reader import FFMPEG_VideoReader as MoviePyFFMPEGVideoReader
from moviepy.video.VideoClip import VideoClip

from ....concurrent_utils import run_any_func
from .loader import AcceptableFileSource, save_get_file_source
from ._utils import _try_get_from_dict, _get_media_json_schema, _dump_media_dict

if TYPE_CHECKING:
    from .audio import Audio
    from .image import Image

_tempfile_cls: TypeAlias = tempfile._TemporaryFileWrapper

class _FFMPEGTempFileVideoReader(MoviePyFFMPEGVideoReader):
    def __init__(self, file: str|_tempfile_cls, *args, **kwargs):
        self._temp_file = None
        if isinstance(file, _tempfile_cls):
            filename = file.name
            self._temp_file = file
        else:
            filename = file
        super().__init__(filename, *args, **kwargs)
    
    def close(self, delete_lastread=True):
        try:
            super().close(delete_lastread)
            if delete_lastread and self._temp_file:
                tmp = self._temp_file
                self._temp_file = None
                tmp.close()
        except:
            pass
            
_defer_attrs = ('duration', 'end', 'fps', 'size', 'rotation', 'frame_function',)

VideoCommonFormats: TypeAlias = Literal['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', 'wmv']

_VideoTypeCodecMap = {
    'mp4': 'libx264',
    'avi': 'libx264',
    'mov': 'libx264',
    'mkv': 'libx264',
    'webm': 'libvpx-vp9',
    'flv': 'flv',
    'wmv': 'wmv2',
}

def _tidy_video_format(format: str|None, raise_err=True, default='mp4')->VideoCommonFormats:
    if not format:
        return default  # type: ignore
    format = format.lower().strip('. ')
    if format not in _VideoTypeCodecMap:
        if raise_err:
            raise ValueError(f"Unsupported video format: {format}")
        return format   # type: ignore
    return format   # type: ignore

class Video(VideoClip):

    Abstract: ClassVar[bool] = False
    Type: ClassVar[str] = 'video'
    TypeNames: ClassVar[tuple[str, ...]] = ('clip', 'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', 'wmv')
    Suffixes: ClassVar[tuple[str, ...]] = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv')
    MimePrefixes: ClassVar[tuple[str, ...]] = ('data:video/',)
    MimeTypes: ClassVar[tuple[str, ...]] = ('video/mp4', 'video/x-msvideo', 'video/quicktime', 'video/x-matroska', 'video/webm', 'video/x-flv', 'video/x-ms-wmv')

    duration: float
    '''The duration of the video clip in seconds.'''
    end: float
    '''The end time of the video clip in seconds.'''
    fps: float
    '''The frames per second of the video clip.'''
    size: tuple[int, int]
    '''The (width, height) of the video clip in pixels.'''
    rotation: int
    '''The rotation of the video clip in degrees.'''
    frame_function: Callable[[float], 'np.ndarray']
    '''A function that takes a time (in seconds) and returns the corresponding frame as a
    numpy array.'''
    
    mask: VideoClip|None = None
    '''A mask video clip for the video clip, if any.'''
    audio: AudioFileClip|None = None
    '''An audio clip for the video clip, if any.
    If you want to get `Audio` object, use `get_audio_model()` method.'''
    
    reader: _FFMPEGTempFileVideoReader|None = None
    '''
    A video clip object that loads video data from a file source.
    NOTE: The video data is loaded lazily when needed. `reader` will 
    be None until the video is actually used.
    '''
    _defer_loader = None
    _origin_format = None
    
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        def validator(data):
            if isinstance(data, dict):
                data = _try_get_from_dict(data, 'data', 'content', 'video', 'clip', 'source', 'url')
            if not isinstance(data, cls):
                data = cls(data)   # type: ignore
            return data
        
        def serializer(video: 'Video'):
            return _dump_media_dict(video.to_base64(), cls)

        validate_schema = core_schema.no_info_after_validator_function(validator, core_schema.any_schema())
        serialize_schema = core_schema.plain_serializer_function_ser_schema(serializer)
        return core_schema.json_or_python_schema(
            json_schema=validate_schema,
            python_schema=validate_schema,
            serialization=serialize_schema
        )
    
    @classmethod
    def __get_pydantic_json_schema__(cls, cs, handler):
        return _get_media_json_schema(cls)
    
    def _defer_init(
        self, 
        reader: _FFMPEGTempFileVideoReader, 
        has_mask: bool=False, 
        audio: bool=True,
        audio_fps: int=44100,
        audio_nbytes: int=2,
        audio_buffersize: int=200000,
    ):
        self.duration = reader.duration
        self.end = reader.duration
        self.fps = reader.fps
        self.size = tuple(reader.size)  # type: ignore
        self.rotation = reader.rotation
        
        if has_mask:
            self.frame_function = lambda t: reader.get_frame(t)[:, :, :3]

            def mask_frame_function(t):
                return reader.get_frame(t)[:, :, 3] / 255.0

            self.mask = VideoClip(is_mask=True, frame_function=mask_frame_function).with_duration(self.duration)
            self.mask.fps = self.fps    # type: ignore
        else:
            self.frame_function = lambda t: reader.get_frame(t)
            
        if audio and reader.infos["audio_found"]:
            self.audio = AudioFileClip(
                reader.filename,
                buffersize=audio_buffersize,
                fps=audio_fps,
                nbytes=audio_nbytes,
            )
        self._defer_loader = None
    
    def _create_defer_loader(
        self,
        source: AcceptableFileSource,
        decode_file:bool=False,
        has_mask: bool=False,
        audio: bool=True,
        audio_buffersize: int=200000,
        target_resolution=None,
        resize_algorithm="bicubic",
        audio_fps=44100,
        audio_nbytes: int=2,
        fps_source="fps",
        pixel_format=None,
    ):
        if isinstance(source, Path):
            source_str = str(source)
        elif isinstance(source, str):
            source_str = source
        else:
            source_str = None
        if source_str and len(source_str) < 1024 and ('.' in source_str[-5:]):
            suffix = source_str.split('.')[-1]
        else:
            suffix = None
        
        if suffix:
            try:
                maybe_format = _tidy_video_format(suffix, raise_err=True, default=None) # type: ignore
            except:
                maybe_format = None
        else:
            maybe_format = None
        self._origin_format = maybe_format
        
        def defer_loader(source):
            video_file = None
            if source_str and len(source_str) < 1024:   # seems like a path
                if not source_str.startswith(('http://', 'https://', 'ftp://', 's3://', 'gs://')):
                    if os.path.exists(source_str):
                        video_file = source_str
            if not video_file:
                file_suffix = f'.{suffix}' if suffix else (f'.{self._origin_format}' if self._origin_format else '.mp4')
                video_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix, mode='wb')
                video_file.write(run_any_func(save_get_file_source, source).read())
                video_file.flush()
                
            self.reader = reader = _FFMPEGTempFileVideoReader(
                video_file,
                decode_file=decode_file,
                pixel_format=pixel_format,  # type: ignore
                target_resolution=target_resolution,
                resize_algo=resize_algorithm,
                fps_source=fps_source,
            )
            self._defer_init(reader, has_mask=has_mask, audio=audio, audio_fps=audio_fps, 
                             audio_nbytes=audio_nbytes, audio_buffersize=audio_buffersize)
            
        return partial(defer_loader, source)

    def __init__(
        self,
        source: AcceptableFileSource | VideoClip,
        decode_file: bool = False,
        has_mask: bool = False,
        audio: bool = True,
        audio_buffersize: int = 200000,
        target_resolution=None,
        resize_algorithm="bicubic",
        audio_fps=44100,
        audio_nbytes: int = 2,
        fps_source="fps",
        pixel_format=None,
        is_mask: bool = False,
    ):
        # Handle VideoClip passthrough
        if isinstance(source, VideoClip):
            VideoClip.__init__(self, is_mask=is_mask)
            self.reader = getattr(source, 'reader', None)
            self._defer_loader = getattr(source, '_defer_loader', None)
            self._origin_format = getattr(source, '_origin_format', None)
            for attr in ('duration', 'end', 'fps', 'size', 'rotation', 'frame_function', 'mask', 'audio'):
                if hasattr(source, attr):
                    try:
                        setattr(self, attr, getattr(source, attr))
                    except Exception:
                        pass
            return
        else:
            # Quick type compatibility check for FileID sources
            from ..base import _check_source_file_type_compat
            _check_source_file_type_compat(self.Type, self.TypeNames, source, self.Suffixes)

        VideoClip.__init__(self, is_mask=is_mask)
        
        # Make a reader
        if not pixel_format:
            pixel_format = "rgba" if has_mask else "rgb24"
        if not self.reader:
            self._defer_loader = self._create_defer_loader(
                source,
                decode_file=decode_file,
                pixel_format=pixel_format,
                target_resolution=target_resolution,
                resize_algorithm=resize_algorithm,
                fps_source=fps_source,
            )
            setattr(self._defer_loader, '__source__', source)
        else:
            self._defer_init(self.reader, has_mask=has_mask, audio=audio, audio_fps=audio_fps, 
                             audio_nbytes=audio_nbytes, audio_buffersize=audio_buffersize)

    def __deepcopy__(self, memo):
        return self.__copy__()

    if not TYPE_CHECKING:
        def __getattr__(self, name):
            if name in _defer_attrs and self._defer_loader and not self.reader:
                self._defer_loader()  # initialize the reader
                if name in self.__dict__:
                    return getattr(self, name)
            raise AttributeError(f"'Video' object has no attribute '{name}'")

        def __getattribute__(self, name):
            if name in _defer_attrs and self._defer_loader and not self.reader:
                self._defer_loader()  # initialize the reader
            return super().__getattribute__(name)

    def get_audio_model(self)->"Audio|None":
        '''
        Get the Audio model object for the audio clip of the video.
        This is different from the `audio` attribute, which is an `AudioFileClip` object.
        '''
        if (am:=getattr(self, '__audio_model__', None)) is None:
            if not self.reader and self._defer_loader:
                self._defer_loader()
            if not self.audio:
                am = None
            else:
                from .audio import Audio
                tmp_file: str = self.reader.filename    # type: ignore
                am = Audio(tmp_file)
            setattr(self, '__audio_model__', am)
        return am
    
    def frames(self, from_time: float=0.0, to_time: float|None=None, step: int=1) -> Sequence["Image"]:
        '''Get frames from the video as a sequence of Image objects.'''
        if not self.reader and self._defer_loader:
            self._defer_loader()
        if to_time is None:
            to_time = self.duration
        times = np.arange(from_time, to_time, step / self.fps)
        from .image import Image
        frames = []
        for t in times:
            frame_array = self.frame_function(t)
            frame_image = Image.FromArray(frame_array)
            frames.append(frame_image)
        return frames

    def close(self):
        self._defer_loader = None
        if self.reader:
            self.reader.close()
            self.reader = None
        try:
            if self.audio:
                self.audio.close()
                self.audio = None
        except AttributeError:  # pragma: no cover
            pass

    def to_bytes(self, format: VideoCommonFormats|None=None)-> bytes:
        if format:
            format = _tidy_video_format(format, raise_err=False)
        
        # not yet loaded, can get from source directly
        if (not format or (format and format==self._origin_format)) and self._defer_loader:
            source: AcceptableFileSource = getattr(self._defer_loader, '__source__', None)  # type: ignore
            if source:
                if isinstance(source, bytes):
                    return source
                elif isinstance(source, Path):
                    if not os.path.exists(source):
                        raise FileNotFoundError(f'File not found: {source}')
                    with open(source, 'rb') as f:
                        return f.read()
                elif isinstance(source, BytesIO):
                    source.seek(0)
                    return source.read()
                elif isinstance(source, str):
                    if len(source) < 1024 and os.path.exists(source):
                        with open(source, 'rb') as f:
                            return f.read()
                    elif source.startswith('data:video/'):
                        comma_idx = source.find(',')
                        if comma_idx != -1:
                            b64_data = source[comma_idx+1:]
                            return base64.b64decode(b64_data)
                    elif len(source) > 2048 and len(source) % 4 == 0 and not (source.startswith(('http://', 'https://', 'ftp://', 's3://', 'gs://'))):
                        try:
                            return base64.b64decode(source)
                        except:
                            pass
        
        raw_inp_format = format
        format = self._origin_format or 'mp4'   # type: ignore
        if ((format and format == self._origin_format) or (not raw_inp_format)) and self.reader:
            temp_file = self.reader._temp_file  # type: ignore
            if not temp_file:
                with open(self.reader.filename, 'rb') as f:     # type: ignore
                    return f.read()
            else:
                with open(temp_file.name, 'rb') as f:    # type: ignore
                    return f.read()
        
        codec = _VideoTypeCodecMap.get(format, None)    # type: ignore
        with tempfile.NamedTemporaryFile(suffix=f'.{format}', delete=False) as tmp_file:
            temp_path = tmp_file.name
        try:
            self.write_videofile(
                temp_path,
                codec=codec,
                logger=None
            )
            with open(temp_path, 'rb') as f:
                return f.read()
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def to_base64(self, format: VideoCommonFormats|None=None, url_scheme: bool=False)->str:
        if format:
            format = _tidy_video_format(format, raise_err=False)
        else:
            if url_scheme:
                if self._origin_format is not None:
                    format = self._origin_format    # type: ignore
                else:
                    format = 'mp4'
        data = self.to_bytes(format=format)
        data = base64.b64encode(data).decode('utf-8')
        if url_scheme:
            return f'data:video/{format};base64,{data}'
        return data
    
    async def load(self) -> Self:
        """Trigger deferred loading. Idempotent."""
        if self._defer_loader and not self.reader:
            self._defer_loader()
        return self

    def to_md5_hash(self, format: VideoCommonFormats | None = None) -> str:
        return hashlib.md5(self.to_bytes(format=format)).hexdigest()

    def save(self, path: str | Path, *args: Any, **kwargs: Any) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fmt = kwargs.pop('format', None) or target.suffix.lstrip('.').lower() or 'mp4'
        fmt = _tidy_video_format(fmt, raise_err=False)
        codec = _VideoTypeCodecMap.get(fmt, None)
        self.write_videofile(str(target), codec=codec, logger=None, *args, **kwargs)
        return str(target)

    def pydantic_dump(self) -> dict[str, Any]:
        return _dump_media_dict(self.to_base64(), type(self))

    def to_llm(self, **kwargs: Any) -> Sequence['Video']:
        return [self]

    @classmethod
    def CastVideoClip(cls, clip: VideoClip) -> Self:
        if isinstance(clip, cls):
            return clip
        return cls(clip)
    
    
__all__ = ['Video']


if __name__ == '__main__':
    import wave
    import numpy as np
    import tempfile
    
    from PIL import Image as PILImage
    from pathlib import Path
    from io import BytesIO
    from moviepy.video.VideoClip import ImageClip
    from moviepy.audio.io.AudioFileClip import AudioFileClip
    
    from .audio import Audio
    
    def _make_audio_wav_bytes(duration_sec: float = 0.5, sample_rate: int = 16000) -> bytes:
        t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
        wave_data = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        pcm16 = np.clip(wave_data * 32767, -32768, 32767).astype(np.int16)

        buf = BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16.tobytes())
        return buf.getvalue()

    def _make_image_png_bytes(width: int = 64, height: int = 64) -> bytes:
        arr = np.zeros((height, width, 3), dtype=np.uint8)
        arr[:, :, 1] = 180
        img = PILImage.fromarray(arr, mode='RGB')
        buf = BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def _make_video_mp4_bytes(image_png_bytes: bytes, audio_wav_bytes: bytes, duration_sec: float = 0.5) -> bytes:
        with tempfile.TemporaryDirectory(prefix='video_test') as td:
            tmp_dir = Path(td)
            image_path = tmp_dir / 'frame.png'
            audio_path = tmp_dir / 'audio.wav'
            video_path = tmp_dir / 'video.mp4'

            image_path.write_bytes(image_png_bytes)
            audio_path.write_bytes(audio_wav_bytes)

            arr = np.array(PILImage.open(BytesIO(image_png_bytes)).convert('RGB'))
            clip = ImageClip(arr)
            if hasattr(clip, 'with_duration'):
                clip = clip.with_duration(duration_sec)
            else:
                clip = clip.set_duration(duration_sec)  # type: ignore[attr-defined]

            audio_clip = AudioFileClip(str(audio_path))
            if hasattr(audio_clip, 'subclipped'):
                audio_clip = audio_clip.subclipped(0, duration_sec)
            else:
                audio_clip = audio_clip.subclip(0, duration_sec)  # type: ignore[attr-defined]

            if hasattr(clip, 'with_audio'):
                clip = clip.with_audio(audio_clip)
            else:
                clip = clip.set_audio(audio_clip)  # type: ignore[attr-defined]

            clip.write_videofile(
                str(video_path),
                codec='libx264',
                audio_codec='aac',
                fps=24,
                logger=None,
            )

            try:
                clip.close()
            except Exception:
                pass
            try:
                audio_clip.close()
            except Exception:
                pass

            return video_path.read_bytes()
    
    audio_bytes = _make_audio_wav_bytes()
    image_bytes = _make_image_png_bytes()
    video_bytes = _make_video_mp4_bytes(image_bytes, audio_bytes)
    video = Video(video_bytes)
    print(f"Video duration: {video.duration}s, fps: {video.fps}, size: {video.size}, rotation: {video.rotation}")