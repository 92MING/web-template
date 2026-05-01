

import re
import base64
import hashlib

from urllib.parse import urlparse
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal, Self, Sequence

from pydantic_core import core_schema

from ....concurrent_utils import run_any_func
from ..medias._utils import _dump_media_dict, _get_media_json_schema, _try_get_from_dict
from ..medias.loader import save_get_file_source
from ..medias import Audio, Image, Video
from ._utils import (
    _decode_text_bytes,
    _iter_zip_file_names,
    _read_zip_mimetype,
    _render_logical_pages_to_images,
)

type LLMDocumentPart = str | Image | Audio | Video

class LLMDocumentMixin(ABC):
    '''可转换为 LLM 输入序列的文档对象。'''

    Abstract: ClassVar[bool] = True
    Type: ClassVar[str]
    TypeNames: ClassVar[tuple[str, ...]]
    Suffixes: ClassVar[tuple[str, ...]] = ()
    MimePrefixes: ClassVar[tuple[str, ...]] = ()
    MimeTypes: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    async def to_llm(self, **kwargs: Any) -> Sequence[LLMDocumentPart]:
        '''将文档转换为适合发送给 LLM 的多模态序列。'''
        raise NotImplementedError


class BaseDocument(LLMDocumentMixin):
    '''文档基类，统一封装 source/bytes/base64/pydantic 行为。'''

    Abstract: ClassVar[bool] = True

    def __init__(self, source: str | Path | bytes):
        self._source = source
        self._bytes_cache: bytes | None = None
        self._zip_names_cache: list[str] | None = None
        self._zip_mimetype_cache: str | None = None
        self._validate_source()

    @property
    def source(self) -> str | Path | bytes:
        return self._source

    @property
    def suffix(self) -> str:
        if isinstance(self.source, Path):
            return self.source.suffix.lower()
        if isinstance(self.source, str):
            source_text = self.source.strip()
            if source_text.startswith('data:'):
                match = re.match(r'^data:([\w.+-]+)/([\w.+-]+)', source_text, re.IGNORECASE)
                if match:
                    return f'.{match.group(2).lower()}'
            parsed = urlparse(source_text)
            if parsed.scheme in {'http', 'https'}:
                return Path(parsed.path).suffix.lower()
            return Path(source_text).suffix.lower()
        return ''

    def _load_source_bytes(self) -> bytes:
        if self._bytes_cache is not None:
            return self._bytes_cache

        data = run_any_func(save_get_file_source, self._source).read()  # type: ignore[arg-type]
        if not data:
            raise ValueError(f'Invalid {type(self).__name__} source. It should be a path/url/bytes/base64 string.')

        self._bytes_cache = data
        return data

    def source_text(self) -> str:
        return _decode_text_bytes(self.to_bytes())

    def _zip_file_names(self) -> list[str]:
        if self._zip_names_cache is None:
            self._zip_names_cache = _iter_zip_file_names(self.to_bytes())
        return self._zip_names_cache

    def _zip_mimetype(self) -> str:
        if self._zip_mimetype_cache is None:
            self._zip_mimetype_cache = _read_zip_mimetype(self.to_bytes())
        return self._zip_mimetype_cache

    def _data_url_mime(self) -> str:
        if self.MimeTypes:
            return self.MimeTypes[0]
        return f'application/{type(self).Type.lower()}'

    def _validate_source(self) -> None:
        from ..base import _check_source_file_type_compat
        _check_source_file_type_compat(self.Type, self.TypeNames, self._source, self.Suffixes)

    @classmethod
    def Load(cls, source: Any) -> Self:
        return cls(source)

    def to_bytes(self, *args: Any, **kwargs: Any) -> bytes:
        return self._load_source_bytes()

    def to_base64(self, url_scheme: bool = False, preserve_source: bool = True, *args: Any, **kwargs: Any) -> str:
        if preserve_source and isinstance(self.source, (str, Path)) and self._bytes_cache is None:
            return str(self.source)
        b64 = base64.b64encode(self.to_bytes()).decode('utf-8')
        if url_scheme:
            mime = self._data_url_mime()
            return f'data:{mime};base64,{b64}'
        return b64

    def to_md5_hash(self, *args: Any, **kwargs: Any) -> str:
        return hashlib.md5(self.to_bytes()).hexdigest()

    def save(self, path: str | Path, *args: Any, **kwargs: Any) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.to_bytes())
        return str(target)

    @classmethod
    def _allowed_type_names(cls) -> set[str]:
        names = {cls.Type.strip().lower(), cls.__name__.strip().lower()}
        names.update(type_name.strip().lower() for type_name in cls.TypeNames if type_name.strip())
        return names

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any):
        def validator(data: Any):
            if isinstance(data, dict):
                media_type = _try_get_from_dict(data, 'type', 'Type', 'media_type')
                if isinstance(media_type, str) and media_type.strip().lower() not in cls._allowed_type_names():
                    raise ValueError(f'Invalid {cls.__name__} data type: {media_type}')
                data = _try_get_from_dict(
                    data,
                    'data',
                    'content',
                    'source',
                    'url',
                    'file',
                    'document',
                    cls.__name__.lower(),
                )
            if not isinstance(data, cls):
                data = cls.Load(data)
            return data

        def serializer(doc: 'BaseDocument'):
            return _dump_media_dict(doc.to_base64(), cls)

        validate_schema = core_schema.no_info_after_validator_function(validator, core_schema.any_schema())
        serialize_schema = core_schema.plain_serializer_function_ser_schema(serializer)
        return core_schema.json_or_python_schema(
            json_schema=validate_schema,
            python_schema=validate_schema,
            serialization=serialize_schema,
        )

    def pydantic_dump(self) -> dict[str, Any]:
        return _dump_media_dict(self.to_base64(), type(self))

    @classmethod
    def __get_pydantic_json_schema__(cls, cs: Any, handler: Any):
        return _get_media_json_schema(cls)


class PageBasedDocumentMixin(BaseDocument, ABC):
    '''具有“页面/幻灯片”概念的文档基类。'''

    Abstract: ClassVar[bool] = True

    @abstractmethod
    def to_images(self, **kwargs: Any) -> list[Image]:
        raise NotImplementedError

    @abstractmethod
    def extract_page_contents(self, **kwargs: Any) -> list[list[LLMDocumentPart]]:
        raise NotImplementedError

    @property
    def page_count(self) -> int:
        try:
            return len(self.extract_page_contents())
        except Exception:
            return 0

    async def to_llm(
        self,
        mode: Literal['mixed', 'image'] = 'mixed',
        *,
        include_page_markers: bool = False,
        page_label: str = 'Page',
        **kwargs: Any,
    ) -> Sequence[LLMDocumentPart]:
        if mode == 'image':
            return self.to_images(**kwargs)
        if mode != 'mixed':
            raise ValueError(f'Unsupported document LLM mode: {mode}')

        parts: list[LLMDocumentPart] = []
        for page_index, page in enumerate(self.extract_page_contents(**kwargs), start=1):
            if include_page_markers:
                parts.append(f'[{page_label} {page_index}]')
            for item in page:
                if isinstance(item, str):
                    text = item.strip()
                    if text:
                        parts.append(text)
                else:
                    parts.append(item)
        return parts


class LogicalPageDocumentMixin(PageBasedDocumentMixin):
    '''使用逻辑页内容近似渲染图片的文档基类。'''

    Abstract: ClassVar[bool] = True

    def to_images(self, **kwargs: Any) -> list[Image]:
        return _render_logical_pages_to_images(self.extract_page_contents(**kwargs))


__all__ = [
    'LLMDocumentPart',
    'LLMDocumentMixin',
    'BaseDocument',
    'PageBasedDocumentMixin',
    'LogicalPageDocumentMixin',
    'Audio',
    'Image',
    'Video',
]
