

import fitz

from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar, cast

from ..medias import Image
from .base import PageBasedDocumentMixin


class PDF(PageBasedDocumentMixin):
    '''PDF 媒体模型。'''

    Abstract: ClassVar[bool] = False
    Type: ClassVar[str] = 'pdf'
    TypeNames: ClassVar[tuple[str, ...]] = ('document',)
    Suffixes: ClassVar[tuple[str, ...]] = ('.pdf',)
    MimeTypes: ClassVar[tuple[str, ...]] = ('application/pdf',)

    def __init__(self, source: str | Path | bytes):
        super().__init__(source)
        self._doc: fitz.Document | None = None

    @property
    def page_count(self) -> int:
        return self._ensure_doc().page_count

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def _ensure_doc(self) -> fitz.Document:
        if self._doc is None:
            self._doc = fitz.open(stream=self._load_source_bytes(), filetype='pdf')
        return self._doc

    def to_images(self, dpi: int = 220, format: str = 'png') -> list[Image]:
        doc = self._ensure_doc()
        images: list[Image] = []
        scale = max(1.0, float(dpi) / 72.0)
        matrix = fitz.Matrix(scale, scale)

        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)  # type: ignore
            image_bytes = pix.tobytes(output=format)
            images.append(Image(BytesIO(image_bytes).getvalue()))

        return images

    def extract_page_contents(self, dpi: int = 220, image_format: str = 'png') -> list[list[str | Image]]:
        doc = self._ensure_doc()
        pages: list[list[str | Image]] = []
        scale = max(1.0, float(dpi) / 72.0)

        for page in doc:
            page_items: list[str | Image] = []
            page_dict = page.get_text('dict')  # type: ignore
            blocks = page_dict.get('blocks', []) if isinstance(page_dict, dict) else []

            for block in blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get('type')

                if block_type == 0:
                    lines = block.get('lines', [])
                    text_parts: list[str] = []
                    if isinstance(lines, list):
                        for line in lines:
                            if not isinstance(line, dict):
                                continue
                            spans = line.get('spans', [])
                            line_text = ''.join(
                                cast(str, span.get('text', ''))
                                for span in spans
                                if isinstance(span, dict)
                            ).strip()
                            if line_text:
                                text_parts.append(line_text)
                    text = '\n'.join(text_parts).strip()
                    if text:
                        page_items.append(text)
                    continue

                if block_type == 1:
                    image_bytes = block.get('image')
                    if not isinstance(image_bytes, (bytes, bytearray)):
                        xref = block.get('xref')
                        if isinstance(xref, int) and xref > 0:
                            try:
                                extracted = doc.extract_image(xref)
                                image_bytes = extracted.get('image') if isinstance(extracted, dict) else None
                            except Exception:
                                image_bytes = None

                    if isinstance(image_bytes, (bytes, bytearray)) and image_bytes:
                        page_items.append(Image(bytes(image_bytes)))
                    else:
                        bbox = block.get('bbox')
                        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                            try:
                                rect = fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                                matrix = fitz.Matrix(scale, scale)
                                pix = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)  # type: ignore
                                page_items.append(Image(pix.tobytes(output=image_format)))
                            except Exception:
                                ...

            pages.append(page_items)

        return pages


__all__ = ['PDF']
