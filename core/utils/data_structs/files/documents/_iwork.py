

import gzip
import plistlib
import re
import zipfile

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Iterable, Literal
from xml.etree import ElementTree as ET

from ._legacy_text import extract_best_effort_text
from ._utils import _decode_text_bytes, _normalize_multiline_text

IWorkKind = Literal['pages', 'key']


@dataclass(slots=True)
class IWorkExtractResult:
    preview_pdf: bytes | None = None
    image_blobs: list[bytes] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)
    page_text_blocks: list[list[str]] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _normalize_zip_name(name: str) -> str:
    return name.replace('\\', '/').strip().lower()


def _xml_text(data: bytes) -> str:
    try:
        root = ET.fromstring(data)
    except Exception:
        return ''

    parts: list[str] = []
    for elem in root.iter():
        text = str(elem.text or '').strip()
        if text:
            parts.append(text)
        tail = str(elem.tail or '').strip()
        if tail:
            parts.append(tail)
    return _normalize_multiline_text('\n'.join(parts))


def _local_name(tag: Any) -> str:
    return str(tag or '').split('}', 1)[-1].lower()


def _dedupe_texts(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_multiline_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _page_nodes_for_kind(kind: IWorkKind) -> tuple[str, ...]:
    if kind == 'key':
        return ('slide', 'page', 'master-slide', 'section')
    return ('page', 'section', 'document', 'body')


def _extract_xml_page_blocks(data: bytes, kind: IWorkKind) -> list[list[str]]:
    try:
        root = ET.fromstring(data)
    except Exception:
        return []

    page_blocks: list[list[str]] = []
    page_tags = set(_page_nodes_for_kind(kind))
    text_tags = {
        'p', 't', 'text', 'span', 'string', 'cell', 'title', 'body', 'notes', 'note', 'td',
        'text-storage', 'text-body', 'paragraph', 'layout', 'textbox', 'shape',
    }

    for node in root.iter():
        if _local_name(getattr(node, 'tag', '')) not in page_tags:
            continue
        texts: list[str] = []
        for child in node.iter():
            child_name = _local_name(getattr(child, 'tag', ''))
            if child_name not in text_tags:
                continue
            text = str(getattr(child, 'text', '') or '').strip()
            if text:
                texts.append(text)
            tail = str(getattr(child, 'tail', '') or '').strip()
            if tail:
                texts.append(tail)
        deduped = _dedupe_texts(texts)
        if deduped:
            page_blocks.append(deduped)

    if page_blocks:
        return page_blocks

    whole_text = _xml_text(data)
    return [[whole_text]] if whole_text else []


def _append_unique_blob(blobs: list[bytes], blob: bytes) -> None:
    if blob and blob not in blobs:
        blobs.append(blob)


def _load_metadata_blob(raw: bytes) -> dict[str, str]:
    try:
        parsed = plistlib.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if value not in (None, '')
    }


def extract_iwork_low_fidelity(data: bytes, kind: IWorkKind) -> IWorkExtractResult:
    result = IWorkExtractResult()
    if not zipfile.is_zipfile(BytesIO(data)):
        result.warnings.append(f'{kind} package is not a valid zip container; using binary text fallback.')
        fallback_text = extract_best_effort_text(data)
        if fallback_text:
            result.text_blocks.append(fallback_text)
        return result

    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            name_map = {_normalize_zip_name(name): name for name in zf.namelist()}

            for preview_name in ('quicklook/preview.pdf', 'preview.pdf'):
                if preview_name in name_map:
                    result.preview_pdf = zf.read(name_map[preview_name])
                    break

            image_name_patterns = (
                'quicklook/thumbnail.jpg',
                'quicklook/thumbnail.png',
                'preview.jpg',
                'preview.png',
                'preview-micro.jpg',
                'preview-micro.png',
            )
            for image_name in image_name_patterns:
                if image_name in name_map:
                    blob = zf.read(name_map[image_name])
                    if blob:
                        _append_unique_blob(result.image_blobs, blob)

            for metadata_name in (
                'metadata/buildversionhistory.plist',
                'buildversionhistory.plist',
                'metadata/documentidentifier',
                'metadata/properties.plist',
            ):
                if metadata_name not in name_map:
                    continue
                raw = zf.read(name_map[metadata_name])
                if metadata_name.endswith('.plist'):
                    result.metadata.update(_load_metadata_blob(raw))
                else:
                    text = _normalize_multiline_text(_decode_text_bytes(raw))
                    if text:
                        result.metadata[metadata_name] = text

            candidate_text_entries: list[str] = []
            if kind == 'pages':
                candidate_text_entries.extend([
                    'index.xml',
                    'index.xml.gz',
                    'preview/prvtext.txt',
                ])
            else:
                candidate_text_entries.extend([
                    'index.apxl',
                    'index.apxl.gz',
                    'presentation.apxl',
                    'presentation.apxl.gz',
                    'preview/prvtext.txt',
                ])

            for normalized_name, original_name in name_map.items():
                if normalized_name in candidate_text_entries:
                    raw = zf.read(original_name)
                    if normalized_name.endswith('.gz'):
                        try:
                            raw = gzip.decompress(raw)
                        except Exception:
                            ...
                    if normalized_name.endswith(('.xml', '.apxl', '.gz')):
                        page_blocks = _extract_xml_page_blocks(raw, kind)
                        if page_blocks:
                            result.page_text_blocks.extend(page_blocks)
                            result.text_blocks.extend('\n\n'.join(block) for block in page_blocks)
                            continue
                        text = _xml_text(raw)
                    else:
                        text = _normalize_multiline_text(_decode_text_bytes(raw))
                    if text:
                        result.text_blocks.append(text)

            if not result.text_blocks:
                for normalized_name, original_name in name_map.items():
                    if not normalized_name.endswith(('.xml', '.apxl', '.txt', '.plist', '.gz')):
                        continue
                    try:
                        raw = zf.read(original_name)
                    except Exception:
                        continue
                    if normalized_name.endswith('.gz'):
                        try:
                            raw = gzip.decompress(raw)
                        except Exception:
                            ...
                    if normalized_name.endswith(('.xml', '.apxl', '.gz')):
                        page_blocks = _extract_xml_page_blocks(raw, kind)
                        if page_blocks:
                            result.page_text_blocks.extend(page_blocks)
                            result.text_blocks.extend('\n\n'.join(block) for block in page_blocks)
                            continue
                        text = _xml_text(raw)
                    else:
                        text = _normalize_multiline_text(_decode_text_bytes(raw))
                    if text and not re.fullmatch(r'[\W_]+', text):
                        result.text_blocks.append(text)

                for normalized_name, original_name in name_map.items():
                    if not normalized_name.startswith('data/'):
                        continue
                    if not re.search(r'\.(png|jpe?g|gif|bmp|webp|tiff?)$', normalized_name):
                        continue
                    try:
                        _append_unique_blob(result.image_blobs, zf.read(original_name))
                    except Exception:
                        continue

            if not result.text_blocks and result.preview_pdf is None:
                fallback_text = extract_best_effort_text(data)
                if fallback_text:
                    result.text_blocks.append(fallback_text)
                    result.warnings.append(f'{kind} package fell back to coarse binary text extraction.')
    except Exception as exc:
        result.warnings.append(f'Failed to inspect {kind} package: {type(exc).__name__}: {exc}')
        fallback_text = extract_best_effort_text(data)
        if fallback_text:
            result.text_blocks.append(fallback_text)

    result.text_blocks = _dedupe_texts(result.text_blocks)
    result.page_text_blocks = [page for page in (_dedupe_texts(blocks) for blocks in result.page_text_blocks) if page]
    return result


__all__ = ['IWorkExtractResult', 'extract_iwork_low_fidelity']
