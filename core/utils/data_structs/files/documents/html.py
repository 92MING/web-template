

from typing import Any, ClassVar, Literal, Sequence

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown

from ..medias import Audio, Image, Video
from ._structured import XMLLikedDocument
from .base import LLMDocumentPart
from ._utils import _normalize_multiline_text, _resolve_media_source


class HTML(XMLLikedDocument):
    '''HTML 文档模型。'''

    Abstract: ClassVar[bool] = False
    Type: ClassVar[str] = 'html'
    TypeNames: ClassVar[tuple[str, ...]] = ('htm', 'webpage')
    Suffixes: ClassVar[tuple[str, ...]] = ('.html', '.htm')
    MimeTypes: ClassVar[tuple[str, ...]] = ('text/html',)

    def _extract_media_parts(self, html_text: str) -> list[LLMDocumentPart]:
        soup = BeautifulSoup(html_text, 'html.parser')
        media_parts: list[LLMDocumentPart] = []

        def _append_media(src: str, media_kind: Literal['image', 'audio', 'video']) -> None:
            try:
                resolved = _resolve_media_source(src, self.source)
                if media_kind == 'image':
                    media_parts.append(Image(resolved))
                elif media_kind == 'audio':
                    media_parts.append(Audio(resolved))
                else:
                    media_parts.append(Video(resolved))
            except Exception:
                ...

        for tag in soup.find_all(['img', 'audio', 'video', 'source']):
            if not getattr(tag, 'attrs', None):
                continue
            tag_name = getattr(tag, 'name', '')
            src = tag.get('src') or tag.get('data-src') or tag.get('data-original')
            if not src and tag_name == 'video':
                src = tag.get('poster')
            if not isinstance(src, str) or not src.strip():
                continue
            if tag_name == 'img':
                _append_media(src, 'image')
            elif tag_name == 'audio':
                _append_media(src, 'audio')
            elif tag_name == 'video':
                if src == tag.get('poster'):
                    _append_media(src, 'image')
                else:
                    _append_media(src, 'video')
            elif tag_name == 'source':
                parent_name = getattr(getattr(tag, 'parent', None), 'name', '')
                if parent_name == 'audio':
                    _append_media(src, 'audio')
                elif parent_name == 'video':
                    _append_media(src, 'video')

        return media_parts

    async def to_llm(
        self,
        *,
        short_len_threshold: int = 1024,
        include_media: bool = True,
        **kwargs: Any,
    ) -> Sequence[LLMDocumentPart]:
        html_text = self.source_text().strip()
        if not html_text:
            return []

        if len(html_text) <= int(short_len_threshold):
            parts: list[LLMDocumentPart] = [html_text]
        else:
            soup = BeautifulSoup(html_text, 'html.parser')
            for tag in soup.find_all(['script', 'style', 'noscript', 'template']):
                tag.decompose()
            markdown_text = _normalize_multiline_text(
                html_to_markdown(str(soup), heading_style='ATX', bullets='-')
            )
            if not markdown_text:
                markdown_text = _normalize_multiline_text(soup.get_text('\n'))
            parts = [
                'NOTE: The following content was converted from original HTML to Markdown for readability.\n\n'
                + markdown_text,
            ]

        if include_media:
            media_parts = self._extract_media_parts(html_text)
            if media_parts:
                parts.append('\n\nNOTE: Embedded media extracted from the original HTML are attached below.\n')
                parts.extend(media_parts)
        return parts


__all__ = ['HTML']
