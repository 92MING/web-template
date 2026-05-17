"""Image model with deferred loading and pydantic support."""



import os
import base64
import logging

import numpy as np
import requests

from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar, Literal, Self, Sequence, TYPE_CHECKING, Coroutine, TypeAlias
from pydantic_core import core_schema
from PIL import Image as PILImage, ImageColor as PILImageColor

from ....type_utils import bytes_to_base64
from ....concurrent_utils import run_any_func, is_async_callable

from ...geometry import Box2D, Point2D
from .loader import save_get_file_source, AcceptableFileSource
from ._utils import _hash_md5, _try_get_from_dict, _get_media_json_schema, _dump_media_dict

if TYPE_CHECKING:
    _ImageBase = PILImage.Image
else:
    _ImageBase = object

CommonImgFormat: TypeAlias = Literal['jpg', 'png', 'gif', 'bmp', 'tiff', 'webp']
ImageColorMode: TypeAlias = Literal['rgb', 'rgba', 'l', 'p', '1', 'cmyk']

_logger = logging.getLogger(__name__)

_SVG_RASTERIZE_DPI = 300


def _tidy_color_mode(mode: ImageColorMode) -> str:
    return mode.upper()

def _tidy_format(format: CommonImgFormat | str) -> str:
    if format == 'jpg':
        return 'jpeg'
    return format.lower()


def _resolve_save_format(target: Any, explicit_format: str | None = None) -> str:
    candidate = str(explicit_format or '').strip()
    if not candidate:
        if isinstance(target, (str, os.PathLike)):
            candidate = Path(target).suffix.lstrip('.')
        else:
            name = getattr(target, 'name', None)
            if isinstance(name, (str, os.PathLike)):
                candidate = Path(name).suffix.lstrip('.')
    if not candidate:
        candidate = 'png'
    return _tidy_format(candidate).upper()

def _is_svg(data: str | Path | bytes) -> bool:
    if isinstance(data, Path):
        if not data.is_file():
            return False
        if data.suffix.lower() == '.svg':
            return True
        try:
            with open(data, 'r', encoding='utf-8') as f:
                header = f.read(512)
            if '<svg' in header:
                return True
        except Exception:
            return False
    elif isinstance(data, str):
        if '<svg' in data[:512]:
            return True
    elif isinstance(data, bytes):
        if b'<svg' in data[:512]:
            return True
    return False

def _svg_convert(source: str | Path, format='png') -> bytes:
    import pyvips
    if isinstance(source, Path):
        if not source.is_file():
            raise ValueError(f'SVG file not found: {source}')
        source = str(source.resolve())
        vips_img: pyvips.Image = pyvips.Image.new_from_file(source, access='sequential', dpi=_SVG_RASTERIZE_DPI)  # type: ignore
    elif len(source) < 4096 and os.path.isfile(source):
        vips_img = pyvips.Image.new_from_file(source, access='sequential', dpi=_SVG_RASTERIZE_DPI)  # type: ignore
    else:
        vips_img = pyvips.Image.new_from_buffer(source.encode('utf-8'), '', access='sequential', dpi=_SVG_RASTERIZE_DPI)  # type: ignore
    if not vips_img:
        raise ValueError(f'Failed to load SVG image from `...{source[-64:]}`')  # type: ignore
    return vips_img.write_to_buffer(f'.{format}')  # type: ignore

def _crop_img(
    img: Any,
    region: Box2D,
    return_mode: Literal["bytes", "base64", "image"] = "image",
    color_mode: Literal["unchange", "L", "RGB", "RGBA"] = "unchange",
):
    if isinstance(img, bytes):
        img_obj = PILImage.open(BytesIO(img))
    elif isinstance(img, str):
        if img.startswith("http://") or img.startswith("https://"):
            img_obj = PILImage.open(BytesIO(requests.get(img).content))
        elif os.path.exists(img):
            img_obj = PILImage.open(img)
        else:
            img_obj = PILImage.open(base64.b64decode(img))
    elif isinstance(img, Path):
        img_obj = PILImage.open(img)
    elif isinstance(img, np.ndarray):
        img_obj = PILImage.fromarray(img)
    elif isinstance(img, PILImage.Image):
        img_obj = img
    else:
        raise ValueError("Unexpected image type.")

    if region.mode == "relative":
        region = region.to_absolute(img_obj.size)
    img_obj = img_obj.crop((region.left_top.x, region.left_top.y, region.right_bottom.x, region.right_bottom.y))  # type: ignore
    if color_mode != "unchange":
        img_obj = img_obj.convert(color_mode)

    if return_mode == "bytes":
        buf = BytesIO()
        img_obj.save(buf, format="PNG")
        return buf.getvalue()
    elif return_mode == "base64":
        buf = BytesIO()
        img_obj.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    else:
        return img_obj


# ── PIL attribute set for __getattr__ delegation ─────────────────────────────

_pil_image_attrs: set[str] | None = None


def _get_pil_image_attrs() -> set[str]:
    global _pil_image_attrs
    if _pil_image_attrs is None:
        _pil_image_attrs = set(dir(PILImage.Image))
        if hasattr(PILImage.Image, '__annotations__'):
            _pil_image_attrs.update(PILImage.Image.__annotations__.keys())
    return _pil_image_attrs


# ── _ImgRetWrapper ───────────────────────────────────────────────────────────

class _ImgRetWrapper:
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
        if isinstance(r, PILImage.Image) and not isinstance(r, Image):
            new_img = Image.__new__(Image)
            new_img._source = r
            new_img._image = r
            new_img._loaded = True
            return new_img
        elif isinstance(r, (list, tuple, set)):
            return type(r)(_ImgRetWrapper._recursive_cast(i) for i in r)
        elif isinstance(r, dict):
            return type(r)({k: _ImgRetWrapper._recursive_cast(v) for k, v in r.items()})
        return r

    def __call__(self, *args, **kwargs):
        r = self.f(*args, **kwargs)
        if isinstance(r, Coroutine):
            async def wrapper():
                coro_r = await r
                return _ImgRetWrapper._recursive_cast(coro_r)
            return wrapper()
        return _ImgRetWrapper._recursive_cast(r)


# ── Image ────────────────────────────────────────────────────────────────────

_IMAGE_OWN_ATTRS = frozenset({
    '_source', '_image', '_loaded',
    'Abstract', 'Type', 'TypeNames', 'Suffixes', 'MimePrefixes',
    'load', '_ensure_loaded',
    'pixel_count', 'channel_count', 'size_in_bytes',
    'tobytes', 'to_bytes', 'to_base64', 'to_md5_hash',
    'copy', 'crop', 'crop_into', 'replace_background', 'New', 'CastPILImage',
    'pydantic_dump', 'to_llm', 'save',
    '__init__', '__repr__', '__class__', '__dict__',
    '__getattr__', '__getattribute__', '__setattr__',
    '__get_pydantic_core_schema__', '__get_pydantic_json_schema__',
    '__module__', '__doc__', '__weakref__', '__annotations__',
    '__dir__',
})


class Image(_ImageBase):
    '''Advanced Image class with deferred loading and pydantic support.'''

    Abstract: ClassVar[bool] = False
    Type: ClassVar[str] = 'image'
    TypeNames: ClassVar[tuple[str, ...]] = ('img', 'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp', 'svg')
    Suffixes: ClassVar[tuple[str, ...]] = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.svg')
    MimePrefixes: ClassVar[tuple[str, ...]] = ('data:image/',)
    MimeTypes: ClassVar[tuple[str, ...]] = ('image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/tiff', 'image/webp', 'image/svg+xml')

    _source: Any
    _image: Any  # PILImage.Image | None
    _loaded: bool

    def __init__(self, source: 'AcceptableFileSource | PILImage.Image | Image', /, **kwargs: Any):  # type: ignore[type-arg]
        if isinstance(source, Image):
            self._source = source._source
            self._image = source._image
            self._loaded = source._loaded
            return
        elif isinstance(source, PILImage.Image):
            self._source = source
            self._image = source
            self._loaded = True
            return
        else:
            from ..base import _check_source_file_type_compat
            _check_source_file_type_compat(self.Type, self.TypeNames, source, self.Suffixes)
        self._source = source
        self._image = None
        self._loaded = False
        # Quick type compatibility check for FileID sources

    # ── loading ──────────────────────────────────────────────────────────

    async def load(self) -> Self:
        """Load the image data from source. Idempotent."""
        if self._loaded:
            return self
        source = self._source
        
        def is_path(source):
            if isinstance(source, Path):
                return source.is_file()
            elif isinstance(source, str) and len(source) < 4096:
                return os.path.isfile(source)
            return False

        if isinstance(source, PILImage.Image):
            self._image = source
        elif _is_svg(source):  # type: ignore
            img_bytes = _svg_convert(source, format='png')  # type: ignore
            self._image = PILImage.open(BytesIO(img_bytes))
        elif is_path(source):
            self._image = PILImage.open(source)
        else:
            data_io = await save_get_file_source(source)  # type: ignore
            self._image = PILImage.open(data_io)
        self._image.load()
        self._loaded = True
        return self

    def _ensure_loaded(self):
        """Synchronously ensure the image is loaded."""
        if not self._loaded:
            run_any_func(self.load)
        return self._image

    # ── PIL delegation ───────────────────────────────────────────────────

    if not TYPE_CHECKING:
        def __getattr__(self, name: str):
            if name in _IMAGE_OWN_ATTRS or (name.startswith('__') and name.endswith('__')):
                raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
            pil_attrs = _get_pil_image_attrs()
            if name in pil_attrs:
                img = self._ensure_loaded()
                attr = getattr(img, name)
                if callable(attr) and not isinstance(attr, type):
                    return _ImgRetWrapper(attr)
                return attr
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    # ── properties that need the real image ──────────────────────────────

    @property
    def size(self) -> tuple[int, int]:
        return self._ensure_loaded().size

    @property
    def mode(self) -> str:
        return self._ensure_loaded().mode

    @property
    def format(self) -> str | None:
        return self._ensure_loaded().format

    @property
    def pixel_count(self) -> int:
        return self.size[0] * self.size[1]

    @property
    def channel_count(self):
        return len(self._ensure_loaded().getbands())

    # ── core methods ─────────────────────────────────────────────────────

    def size_in_bytes(
        self,
        mode: ImageColorMode | None = None,
        format: Literal['pil'] | CommonImgFormat | str | None = None,
    ) -> int:
        return len(self.tobytes(format=format, mode=mode))

    def tobytes(
        self,
        encoder_name: str = "raw",
        *args,
        format: Literal['pil'] | CommonImgFormat | str | None = None,
        mode: ImageColorMode | None = None,
    ) -> bytes:
        img = self._ensure_loaded()
        format = _tidy_format(format) if format else img.format  # type: ignore
        mode = _tidy_color_mode(mode) if mode else img.mode  # type: ignore
        if mode == 'pil':
            return img.tobytes(encoder_name, *args)
        else:
            if not mode:
                mode = 'RGBA' if self.channel_count > 3 else 'RGB'  # type: ignore
            if not format:
                format = 'jpeg' if self.channel_count <= 3 else 'png'
            buf = BytesIO()
            out_img = img.convert(mode) if mode != img.mode else img
            out_img.save(buf, format=format)
            return buf.getvalue()

    to_bytes = tobytes

    def to_base64(
        self,
        format: Literal['pil'] | CommonImgFormat | str | None = None,
        mode: ImageColorMode | None = None,
        url_scheme: bool = False,
    ) -> str:
        fmt = _tidy_format(format) if format else (self._ensure_loaded().format or None)  # type: ignore
        b64 = bytes_to_base64(self.tobytes(format=format, mode=mode))
        if url_scheme and fmt != 'pil':
            if not fmt:
                fmt = 'jpg' if self.channel_count <= 3 else 'png'
            fmt = fmt.lower().strip()
            b64 = f'data:image/{fmt};base64,{b64}'
        return b64

    def to_md5_hash(
        self,
        format: Literal['pil'] | CommonImgFormat | str | None = None,
        mode: ImageColorMode | None = None,
    ) -> str:
        return _hash_md5(self.tobytes(format=format, mode=mode))

    def copy(self) -> Self:
        img = self._ensure_loaded()
        new = self.__class__.__new__(self.__class__)
        new._source = img.copy()
        new._image = new._source
        new._loaded = True
        return new

    def crop(self, region: Box2D) -> Self:
        if not isinstance(region, Box2D):
            img = self._ensure_loaded().crop(region)
            new = self.__class__.__new__(self.__class__)
            new._source = img
            new._image = img
            new._loaded = True
            return new
        img = _crop_img(self._ensure_loaded(), region, return_mode='image')
        new = self.__class__.__new__(self.__class__)
        new._source = img
        new._image = img
        new._loaded = True
        return new

    def crop_into(
        self,
        pieces: int,
        method: Literal['horizontal', 'vertical', 'square'] = 'horizontal',
        overlap: int | float = 0.5,
    ) -> list[Self]:
        assert pieces >= 1, 'pieces must be >= 1'
        if method == 'horizontal':
            max_len = self.size[0]
        elif method == 'vertical':
            max_len = self.size[1]
        else:
            max_len = min(self.size[0], self.size[1])
        assert pieces <= max_len, f'too many pieces: {pieces} > max_len({max_len})'
        if pieces == 1:
            return [self.copy()]

        if method == 'square' and pieces != 1:
            if pieces < 4:
                _logger.warning(f'square mode requires pieces>=4. Got {pieces}. Fallback to horizontal.')
                method = 'horizontal'
            elif pieces % 2 != 0:
                _logger.warning(f'square mode requires even pieces. Got {pieces}. Fallback to horizontal.')
                method = 'horizontal'

        def calc_range(r, n) -> list[tuple[float, float]]:
            x = 2 / (2 * n - ((n - 1) * r))
            ranges = []
            for i in range(n):
                to_l = (i + 1) * x - i * (x * r / 2)
                from_l = max(0.0, to_l - x)
                ranges.append((from_l, to_l))
            return ranges

        if overlap > 1:
            overlap = overlap / max_len

        if method in ('horizontal', 'vertical'):
            r = max(0.0, min(overlap, 1.0))
            ranges = calc_range(r, pieces)
            boxes = []
            for from_l, to_l in ranges:
                boxes.append(Box2D(
                    left_top=Point2D(0.0, from_l) if method == 'horizontal' else Point2D(from_l, 0.0),
                    right_bottom=Point2D(1.0, to_l) if method == 'horizontal' else Point2D(to_l, 1.0),
                    mode='relative',
                ))
            return [self.crop(box) for box in boxes]
        elif method == 'square':
            ratio = self.size[0] / self.size[1]
            n_cols = int((pieces * ratio) ** 0.5)
            n_rows = pieces // n_cols
            r = max(0.0, min(overlap, 1.0))
            col_ranges = calc_range(r, n_cols)
            row_ranges = calc_range(r, n_rows)
            boxes = []
            for row_range in row_ranges:
                for col_range in col_ranges:
                    from_lx, to_lx = col_range
                    from_ly, to_ly = row_range
                    boxes.append(Box2D(
                        left_top=Point2D(from_lx, from_ly),
                        right_bottom=Point2D(to_lx, to_ly),
                        mode='relative',
                    ))
            return [self.crop(box) for box in boxes]
        else:
            raise ValueError(f'Invalid method: {method}')

    def replace_background(
        self,
        background: str | tuple[int, int, int] | tuple[int, int, int, int] | None,
        *,
        tolerance: int = 8,
    ) -> Self:
        """Replace the flat corner background with a color or transparency."""
        if background is None:
            return self.copy()
        img = self._ensure_loaded().convert('RGBA')
        arr = np.array(img)
        if arr.size == 0:
            return self.__class__.CastPILImage(img)

        corners = np.array([
            arr[0, 0, :3],
            arr[0, -1, :3],
            arr[-1, 0, :3],
            arr[-1, -1, :3],
        ])
        values, counts = np.unique(corners, axis=0, return_counts=True)
        corner_rgb = values[int(np.argmax(counts))]
        diff = np.abs(arr[:, :, :3].astype(np.int16) - corner_rgb.astype(np.int16)).max(axis=2)
        mask = diff <= max(0, int(tolerance))

        text = str(background).strip().lower() if isinstance(background, str) else ''
        if text in {'transparent', 'none', 'alpha'}:
            arr[:, :, 3] = np.where(mask, 0, arr[:, :, 3])
            return self.__class__.CastPILImage(PILImage.fromarray(arr, 'RGBA'))

        if isinstance(background, tuple):
            color = tuple(int(max(0, min(255, item))) for item in background)
        else:
            color = PILImageColor.getrgb(str(background))
        if len(color) == 3:
            fill_rgba = (*color, 255)
        else:
            fill_rgba = color[:4]
        arr[mask] = fill_rgba
        out = PILImage.fromarray(arr, 'RGBA')
        if fill_rgba[3] == 255 and np.all(arr[:, :, 3] == 255):
            out = out.convert('RGB')
        return self.__class__.CastPILImage(out)

    @classmethod
    def New(
        cls,
        width: int = 512,
        height: int = 512,
        color: int | tuple[int, int, int] | tuple[int, int, int, int] = (255, 255, 255),
        mode: ImageColorMode | None = None,
    ) -> Self:
        if isinstance(color, int):
            color = (color, color, color)
        if mode:
            pil_mode = _tidy_color_mode(mode)
        else:
            pil_mode = 'RGB' if len(color) == 3 else 'RGBA'
        pil_img = PILImage.new(pil_mode, (width, height), color)
        return cls(pil_img)

    @classmethod
    def FromArray(cls, arr: np.ndarray) -> Self:
        pil_img = PILImage.fromarray(arr)
        return cls(pil_img)
    
    fromarray = FromArray

    @classmethod
    def CastPILImage(cls, img: 'PILImage.Image') -> Self:
        """Wrap a raw PIL Image as our Image."""
        if isinstance(img, cls):
            return img
        return cls(img)

    def save(self, path: str | os.PathLike[str] | Any, *args: Any, **kwargs: Any) -> Any:
        img = self._ensure_loaded()
        fmt = _resolve_save_format(path, kwargs.pop('format', None))
        if isinstance(path, (str, os.PathLike)):
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(target), format=fmt, *args, **kwargs)
            return str(target)
        img.save(path, format=fmt, *args, **kwargs)
        return path

    def pydantic_dump(self) -> dict[str, Any]:
        return _dump_media_dict(self.to_base64(), type(self))

    def to_llm(self, **kwargs: Any) -> Sequence['Image']:
        return [self]

    def __repr__(self):
        if self._loaded and self._image:
            return f'<{type(self).__name__} shape={self._image.size[0]}x{self._image.size[1]} mode={self._image.mode}>'
        return f'<{type(self).__name__} (not loaded)>'

    # ── pydantic integration ─────────────────────────────────────────────

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        def validator(data):
            if isinstance(data, dict):
                data = _try_get_from_dict(data, 'data', 'content', 'img', 'image', 'source', 'url')
            if isinstance(data, cls):
                return data
            return cls(data)    # type: ignore

        def serializer(img: 'Image'):
            if not img._loaded:
                if isinstance(img._source, (str, Path)):
                    return _dump_media_dict(str(img._source), cls)
                img._ensure_loaded()
            if img.channel_count <= 3:
                fmt = 'jpg'
            else:
                fmt = 'png'
            return _dump_media_dict(img.to_base64(format=fmt), cls)

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


# Make isinstance(Image(...), PILImage.Image) work
def _patch_pil_isinstance():
    try:
        original_meta = type(PILImage.Image)
        if not hasattr(original_meta, '_patched'):
            _orig_instancecheck = original_meta.__instancecheck__

            def __instancecheck__(self, instance):
                if type(instance) is Image or (hasattr(type(instance), '__mro__') and Image in type(instance).__mro__):
                    return True
                return _orig_instancecheck(self, instance)  # type: ignore

            original_meta.__instancecheck__ = __instancecheck__ # type: ignore
            original_meta._patched = True  # type: ignore
    except Exception:
        pass


_patch_pil_isinstance()


__all__ = ['Image', 'CommonImgFormat', 'ImageColorMode']
