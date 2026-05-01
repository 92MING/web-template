

from typing import Any, ClassVar, Sequence

from striprtf.striprtf import rtf_to_text

from .base import BaseDocument, LLMDocumentPart
from ._utils import _normalize_multiline_text


class RTF(BaseDocument):
    '''RTF 文档模型。'''

    Abstract: ClassVar[bool] = False
    Type: ClassVar[str] = 'rtf'
    TypeNames: ClassVar[tuple[str, ...]] = ()
    Suffixes: ClassVar[tuple[str, ...]] = ('.rtf',)
    MimeTypes: ClassVar[tuple[str, ...]] = ('application/rtf',)

    async def to_llm(self, *, short_len_threshold: int = 1024, **kwargs: Any) -> Sequence[LLMDocumentPart]:
        raw_text = self.source_text().strip()
        if not raw_text:
            return []
        if len(raw_text) <= int(short_len_threshold):
            return [raw_text]

        plain_text = _normalize_multiline_text(rtf_to_text(raw_text))
        if not plain_text:
            plain_text = raw_text
        return [
            'NOTE: The following content was converted from RTF to markdown-like plain text for readability.\n\n'
            + plain_text,
        ]


__all__ = ['RTF']
