

import re
import zlib
import zipfile

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from ._legacy_text import extract_best_effort_text
from ._utils import _decode_text_bytes, _normalize_multiline_text

try:
    import olefile  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    olefile = None  # type: ignore[assignment]


@dataclass(slots=True)
class HanwordExtractResult:
    text_blocks: list[str] = field(default_factory=list)
    page_text_blocks: list[list[str]] = field(default_factory=list)
    image_blobs: list[bytes] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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


def _append_unique(target: list[str], value: str) -> None:
    normalized = _normalize_multiline_text(value)
    if normalized and normalized not in target:
        target.append(normalized)


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


def _extract_hwpx_page_blocks(data: bytes) -> list[list[str]]:
    try:
        root = ET.fromstring(data)
    except Exception:
        return []

    page_blocks: list[list[str]] = []
    paragraph_tags = {'p', 't', 'text', 'cell', 'span', 'tbl', 'table'}
    for section in root.iter():
        if _local_name(getattr(section, 'tag', '')) not in {'section', 'page'}:
            continue
        texts: list[str] = []
        for child in section.iter():
            if _local_name(getattr(child, 'tag', '')) not in paragraph_tags:
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
    return page_blocks


def _append_unique_blob(blobs: list[bytes], blob: bytes) -> None:
    if blob and blob not in blobs:
        blobs.append(blob)


def extract_hwpx_low_fidelity(data: bytes) -> HanwordExtractResult:
    result = HanwordExtractResult()
    if not zipfile.is_zipfile(BytesIO(data)):
        fallback_text = extract_best_effort_text(data)
        if fallback_text:
            result.text_blocks.append(fallback_text)
        result.warnings.append('HWPX source is not a valid zip container; using binary text fallback.')
        return result

    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = zf.namelist()
            name_map = {name.replace('\\', '/').lower(): name for name in names}

            for preview_name in ('preview/prvtext.txt', 'preview/prvtext'):
                if preview_name in name_map:
                    _append_unique(result.text_blocks, _decode_text_bytes(zf.read(name_map[preview_name])))

            for preview_image in ('preview/prvimage.png', 'preview/prvimage.jpg', 'preview/prvimage.jpeg'):
                if preview_image in name_map:
                    _append_unique_blob(result.image_blobs, zf.read(name_map[preview_image]))

            for normalized_name, original_name in sorted(name_map.items()):
                if normalized_name.startswith('contents/section') and normalized_name.endswith('.xml'):
                    raw = zf.read(original_name)
                    page_blocks = _extract_hwpx_page_blocks(raw)
                    if page_blocks:
                        result.page_text_blocks.extend(page_blocks)
                        for block in page_blocks:
                            _append_unique(result.text_blocks, '\n\n'.join(block))
                    else:
                        _append_unique(result.text_blocks, _xml_text(raw))
                elif normalized_name.startswith('bindata/') and re.search(r'\.(png|jpe?g|gif|bmp|webp)$', normalized_name):
                    blob = zf.read(original_name)
                    if blob:
                        _append_unique_blob(result.image_blobs, blob)

            if not result.text_blocks:
                for normalized_name, original_name in sorted(name_map.items()):
                    if normalized_name.endswith('.xml'):
                        raw = zf.read(original_name)
                        page_blocks = _extract_hwpx_page_blocks(raw)
                        if page_blocks:
                            result.page_text_blocks.extend(page_blocks)
                            for block in page_blocks:
                                _append_unique(result.text_blocks, '\n\n'.join(block))
                        else:
                            _append_unique(result.text_blocks, _xml_text(raw))
    except Exception as exc:
        result.warnings.append(f'Failed to inspect HWPX: {type(exc).__name__}: {exc}')

    if not result.text_blocks:
        fallback_text = extract_best_effort_text(data)
        if fallback_text:
            result.text_blocks.append(fallback_text)
    result.page_text_blocks = [page for page in (_dedupe_texts(blocks) for blocks in result.page_text_blocks) if page]
    return result


def _read_ole_stream(ole: Any, path_parts: list[str]) -> bytes | None:
    try:
        return ole.openstream(path_parts).read()
    except Exception:
        return None


def extract_hwp_low_fidelity(data: bytes) -> HanwordExtractResult:
    result = HanwordExtractResult()

    if olefile is not None:
        try:
            if olefile.isOleFile(BytesIO(data)):
                with olefile.OleFileIO(BytesIO(data)) as ole:
                    entries = ole.listdir(streams=True, storages=False)
                    for parts in entries:
                        normalized = '/'.join(parts).lower()
                        raw = _read_ole_stream(ole, parts)
                        if not raw:
                            continue

                        if normalized == 'prvtext':
                            _append_unique(result.text_blocks, _decode_text_bytes(raw))
                            continue

                        if normalized == 'prvimage':
                            _append_unique_blob(result.image_blobs, raw)
                            continue

                        if normalized.startswith('bindata/') and re.search(r'\.(png|jpe?g|gif|bmp|webp)$', normalized):
                            _append_unique_blob(result.image_blobs, raw)
                            continue

                        if normalized.startswith('bodytext/section'):
                            section_texts: list[str] = []
                            for candidate in (raw, _try_inflate_raw(raw)):
                                if not candidate:
                                    continue
                                text = extract_best_effort_text(candidate)
                                if text:
                                    _append_unique(result.text_blocks, text)
                                    section_texts.append(text)
                                    break
                            if section_texts:
                                result.page_text_blocks.append(_dedupe_texts(section_texts))
        except Exception as exc:
            result.warnings.append(f'Failed to inspect HWP OLE streams: {type(exc).__name__}: {exc}')

    if not result.text_blocks:
        fallback_text = extract_best_effort_text(data)
        if fallback_text:
            result.text_blocks.append(fallback_text)
    result.page_text_blocks = [page for page in (_dedupe_texts(blocks) for blocks in result.page_text_blocks) if page]

    return result


def _try_inflate_raw(data: bytes) -> bytes | None:
    try:
        return zlib.decompress(data, -15)
    except Exception:
        return None


__all__ = ['HanwordExtractResult', 'extract_hwpx_low_fidelity', 'extract_hwp_low_fidelity']
