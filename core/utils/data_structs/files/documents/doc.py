

import tempfile
import zipfile

from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar, cast

from docx import Document as DocxDocument
from docx.document import Document as DocxDocumentType
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from odf import teletype
from odf.opendocument import load as odf_load

from ..medias import Image
from ._hanword import extract_hwp_low_fidelity, extract_hwpx_low_fidelity
from ._iwork import extract_iwork_low_fidelity
from ._legacy_office import convert_legacy_office_bytes, infer_legacy_ole_kind
from .base import LogicalPageDocumentMixin, LLMDocumentPart
from ._utils import _normalize_multiline_text, _table_to_markdown
from .pdf import PDF


class Doc(LogicalPageDocumentMixin):
    '''通用文档模型。

    NOTE: `.docx` / `.odt` 走结构化解析；`.doc` / `.pages` / `.hwp` / `.hwpx` / `.wps`
    会在传入 LLM 时走尽力而为的低保真提取或临时转换，但 `model_dump` / `model_validate`
    仍保持原始 source 数据不变。
    '''

    Abstract: ClassVar[bool] = False
    Type: ClassVar[str] = 'doc'
    TypeNames: ClassVar[tuple[str, ...]] = ('document', 'doc', 'docx', 'pages', 'hwp', 'hwpx', 'wps', 'odt')
    Suffixes: ClassVar[tuple[str, ...]] = ('.doc', '.docx', '.pages', '.hwp', '.hwpx', '.wps', '.odt')
    MimeTypes: ClassVar[tuple[str, ...]] = ('application/vnd.openxmlformats-officedocument.wordprocessingml.document',)

    def __init__(self, source: str | Path | bytes):
        super().__init__(source)
        self._page_cache: list[list[LLMDocumentPart]] | None = None

    def extract_page_contents(self, **kwargs: Any) -> list[list[LLMDocumentPart]]:
        if self._page_cache is not None:
            return self._page_cache

        suffix = self.suffix
        data = self.to_bytes()
        zip_names = self._zip_file_names()
        zip_mimetype = self._zip_mimetype()
        lowered_names = {name.lower() for name in zip_names}
        if suffix == '.docx' or 'word/document.xml' in lowered_names:
            self._page_cache = self._extract_docx_page_contents()
            return self._page_cache
        if suffix == '.odt' or 'opendocument.text' in zip_mimetype:
            self._page_cache = self._extract_odt_page_contents()
            return self._page_cache
        if suffix == '.wps' and 'word/document.xml' in lowered_names:
            self._page_cache = self._extract_docx_page_contents()
            return self._page_cache
        if suffix in {'.doc', '.wps'} or infer_legacy_ole_kind(data) == 'doc':
            self._page_cache = self._extract_legacy_doc_like_contents(suffix or '.doc')
            return self._page_cache
        if suffix == '.pages':
            self._page_cache = self._extract_pages_contents()
            return self._page_cache
        if suffix == '.hwpx' or 'contents/content.hpf' in lowered_names or any(name.startswith('contents/section') for name in lowered_names):
            self._page_cache = self._extract_hwpx_contents()
            return self._page_cache
        if suffix == '.hwp':
            self._page_cache = self._extract_hwp_contents()
            return self._page_cache

        raise ValueError('Unsupported Doc source: supported formats are .doc/.docx/.pages/.hwp/.hwpx/.wps/.odt.')

    def _prepend_note(self, pages: list[list[LLMDocumentPart]], note: str) -> list[list[LLMDocumentPart]]:
        note_text = str(note or '').strip()
        if not note_text:
            return pages
        if not pages:
            return [[note_text]]
        return [[note_text, *pages[0]], *pages[1:]]

    def _assemble_low_fidelity_pages(
        self,
        *,
        note: str,
        text_blocks: list[str] | None = None,
        page_text_blocks: list[list[str]] | None = None,
        image_blobs: list[bytes] | None = None,
        preview_pdf: bytes | None = None,
    ) -> list[list[LLMDocumentPart]]:
        pages: list[list[LLMDocumentPart]]
        if preview_pdf:
            pages = cast(list[list[LLMDocumentPart]], PDF.Load(preview_pdf).extract_page_contents())
        else:
            pages = [[]]

        normalized_page_blocks = [
            [text.strip() for text in blocks if str(text).strip()]
            for blocks in (page_text_blocks or [])
        ]
        normalized_page_blocks = [blocks for blocks in normalized_page_blocks if blocks]

        if normalized_page_blocks:
            if not pages:
                pages = [list(blocks) for blocks in normalized_page_blocks]
            else:
                for page_index, blocks in enumerate(normalized_page_blocks):
                    block_items: list[LLMDocumentPart] = list(blocks)
                    if page_index < len(pages):
                        pages[page_index] = [*block_items, *pages[page_index]]
                    else:
                        pages.append(block_items)

        if text_blocks:
            text = '\n\n'.join(block.strip() for block in text_blocks if str(block).strip()).strip()
            if text:
                if not pages:
                    pages = [[text]]
                elif not normalized_page_blocks and pages[0]:
                    pages[0] = [text, *pages[0]]
                elif not normalized_page_blocks:
                    pages[0].append(text)

        for blob in image_blobs or []:
            try:
                image = Image(blob)
            except Exception:
                continue
            if not pages:
                pages = [[image]]
            else:
                pages[0].append(image)

        normalized_pages = [page for page in pages if page]
        return self._prepend_note(normalized_pages or [['(Empty document)']], note)

    def _extract_legacy_doc_like_contents(self, source_suffix: str) -> list[list[LLMDocumentPart]]:
        result = convert_legacy_office_bytes(self.to_bytes(), kind='doc', source_suffix=source_suffix)
        note = f'NOTE: The original {source_suffix or ".doc"} file was extracted in low-fidelity mode for LLM input via {result.backend}.'
        if result.output_kind == 'docx' and result.converted_bytes:
            pages = Doc.Load(result.converted_bytes).extract_page_contents()
            return self._prepend_note(pages, note)
        if result.output_kind == 'pdf' and result.converted_bytes:
            pages = cast(list[list[LLMDocumentPart]], PDF.Load(result.converted_bytes).extract_page_contents())
            return self._prepend_note(pages, note)
        if result.text_content:
            return [[note, result.text_content]]
        raise ValueError('; '.join(result.warnings) or f'Failed to extract legacy document source: {source_suffix}.')

    def _extract_pages_contents(self) -> list[list[LLMDocumentPart]]:
        result = extract_iwork_low_fidelity(self.to_bytes(), 'pages')
        note = 'NOTE: The original .pages file was extracted in low-fidelity mode for LLM input.'
        return self._assemble_low_fidelity_pages(
            note=note,
            text_blocks=result.text_blocks,
            page_text_blocks=result.page_text_blocks,
            image_blobs=result.image_blobs,
            preview_pdf=result.preview_pdf,
        )

    def _extract_hwpx_contents(self) -> list[list[LLMDocumentPart]]:
        result = extract_hwpx_low_fidelity(self.to_bytes())
        note = 'NOTE: The original .hwpx file was extracted in low-fidelity mode for LLM input.'
        return self._assemble_low_fidelity_pages(
            note=note,
            text_blocks=result.text_blocks,
            page_text_blocks=result.page_text_blocks,
            image_blobs=result.image_blobs,
        )

    def _extract_hwp_contents(self) -> list[list[LLMDocumentPart]]:
        result = extract_hwp_low_fidelity(self.to_bytes())
        note = 'NOTE: The original .hwp file was extracted in low-fidelity mode for LLM input.'
        return self._assemble_low_fidelity_pages(
            note=note,
            text_blocks=result.text_blocks,
            page_text_blocks=result.page_text_blocks,
            image_blobs=result.image_blobs,
        )

    def _extract_docx_page_contents(self) -> list[list[LLMDocumentPart]]:
        doc = DocxDocument(BytesIO(self.to_bytes()))
        r_embed = qn('r:embed')
        w_type = qn('w:type')
        pages: list[list[LLMDocumentPart]] = [[]]

        def _iter_blocks(parent: DocxDocumentType):
            parent_elm = parent.element.body
            for child in parent_elm.iterchildren():
                if child.tag.endswith('}p'):
                    yield Paragraph(child, parent)
                elif child.tag.endswith('}tbl'):
                    yield Table(child, parent)

        def _has_page_break(paragraph: Paragraph) -> bool:
            for node in paragraph._element.iter():
                tag = str(getattr(node, 'tag', ''))
                if tag.endswith('}lastRenderedPageBreak'):
                    return True
                if tag.endswith('}br') and str(node.get(w_type, '')).lower() == 'page':
                    return True
            return False

        def _extract_images(paragraph: Paragraph) -> list[Image]:
            images: list[Image] = []
            seen_ids: set[str] = set()
            for node in paragraph._element.iter():
                tag = str(getattr(node, 'tag', ''))
                if not tag.endswith('}blip'):
                    continue
                embed_id = node.get(r_embed)
                if not embed_id or embed_id in seen_ids:
                    continue
                seen_ids.add(embed_id)
                try:
                    image_part = doc.part.related_parts[embed_id]
                    blob = getattr(image_part, 'blob', None)
                    if blob:
                        images.append(Image(blob))
                except Exception:
                    ...
            return images

        for block in _iter_blocks(doc):
            current_page = pages[-1]
            if isinstance(block, Paragraph):
                text = str(block.text or '').strip()
                if text:
                    current_page.append(text)
                current_page.extend(_extract_images(block))
                if _has_page_break(block) and current_page:
                    pages.append([])
                continue

            rows = [[str(cell.text or '').strip() for cell in row.cells] for row in block.rows]
            table_md = _table_to_markdown(rows)
            if table_md:
                current_page.append(table_md)

        pages = [page for page in pages if page]
        return pages or [['(Empty document)']]

    def _extract_odt_page_contents(self) -> list[list[LLMDocumentPart]]:
        data = self.to_bytes()
        items: list[LLMDocumentPart] = []

        with tempfile.NamedTemporaryFile(delete=False, suffix='.odt') as tmp_file:
            tmp_file.write(data)
            tmp_path = Path(tmp_file.name)

        try:
            odt_doc = odf_load(str(tmp_path))
            doc_text_root = getattr(odt_doc, 'text', None)
            text = _normalize_multiline_text(teletype.extractText(doc_text_root)) if doc_text_root is not None else ''
            if text:
                items.append(text)
        finally:
            tmp_path.unlink(missing_ok=True)

        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                for name in zf.namelist():
                    if name.startswith('Pictures/'):
                        try:
                            items.append(Image(zf.read(name)))
                        except Exception:
                            ...
        except Exception:
            ...

        return [items or ['(Empty document)']]


__all__ = ['Doc']
