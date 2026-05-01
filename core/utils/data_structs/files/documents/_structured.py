

import csv
import io
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree as ET

from .base import BaseDocument, LLMDocumentPart
from ._utils import _normalize_multiline_text, _probe_text_bytes, _utf8_normalize_text


def _json_default(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='ignore')
    return str(value)


_MARKDOWN_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$', re.MULTILINE)


def _parse_object_path(path: str | Sequence[str | int]) -> list[str | int]:
    if isinstance(path, Sequence) and not isinstance(path, str):
        return [part for part in path]

    text = str(path).strip()
    if not text:
        return []

    tokens: list[str | int] = []
    buffer: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == '.':
            if buffer:
                token = ''.join(buffer).strip()
                if token:
                    tokens.append(token)
                buffer.clear()
            i += 1
            continue
        if char == '[':
            if buffer:
                token = ''.join(buffer).strip()
                if token:
                    tokens.append(token)
                buffer.clear()
            end = text.find(']', i + 1)
            if end < 0:
                raise ValueError(f'Invalid object path: {path}')
            segment = text[i + 1:end].strip()
            if not segment:
                raise ValueError(f'Invalid object path: {path}')
            if segment.isdigit() or (segment.startswith('-') and segment[1:].isdigit()):
                tokens.append(int(segment))
            elif (segment.startswith("'") and segment.endswith("'")) or (segment.startswith('"') and segment.endswith('"')):
                tokens.append(segment[1:-1])
            else:
                tokens.append(segment)
            i = end + 1
            continue
        buffer.append(char)
        i += 1

    if buffer:
        token = ''.join(buffer).strip()
        if token:
            tokens.append(token)
    return tokens


def _fallback_markdown_to_text(text: str) -> str:
    text = re.sub(r'^```[^\n]*\n?', '', text, flags=re.MULTILINE)
    text = text.replace('```', '\n')
    text = re.sub(r'^\s{0,3}[-*+]\s+', '- ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s{0,3}\d+[.)]\s+', '- ', text, flags=re.MULTILINE)
    text = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', r'[image: \1]', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', text)
    text = re.sub(r'[`*_~>#]+', ' ', text)
    return _normalize_multiline_text(text)


class PlainTextDoc(BaseDocument, ABC):
    '''纯文本类文档底层。'''

    Abstract = True

    def __init__(self, source: str | Path | bytes):
        super().__init__(source)
        self._text_cache: str | None = None
        self._text_encoding: str | None = None

    def probe_text(self) -> tuple[bool, str, str | None]:
        ok, text, encoding = _probe_text_bytes(self.to_bytes())
        if ok:
            self._text_cache = _utf8_normalize_text(text)
            self._text_encoding = encoding
        return ok, text, encoding

    def to_text(self, *, normalize: bool = True) -> str:
        if self._text_cache is None:
            ok, text, encoding = _probe_text_bytes(self.to_bytes())
            if not ok:
                raise ValueError(f'{type(self).__name__} source is not valid textual content.')
            self._text_cache = text
            self._text_encoding = encoding
        text = self._text_cache
        return _normalize_multiline_text(text) if normalize else text

    def lines(self) -> list[str]:
        return self.to_text().splitlines()

    def paragraphs(self) -> list[str]:
        return [part.strip() for part in re.split(r'\n\s*\n+', self.to_text()) if part.strip()]

    def snippet(self, max_chars: int = 240, *, suffix: str = '…') -> str:
        text = ' '.join(line.strip() for line in self.to_text().splitlines() if line.strip())
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max(0, max_chars - len(suffix))].rstrip() + suffix

    async def to_llm(self, *, add_note: str | None = None, **kwargs: Any) -> Sequence[LLMDocumentPart]:
        text = self.to_text()
        if not text:
            return []
        if add_note:
            return [str(add_note).strip(), text]
        return [text]


class DictLikedDocument(PlainTextDoc, ABC):
    '''字典/结构化对象类文档底层。'''

    Abstract = True

    def __init__(self, source: str | Path | bytes):
        super().__init__(source)
        self._data_cache: Any = ...

    @abstractmethod
    def _parse_data(self) -> Any:
        raise NotImplementedError

    def to_data(self) -> Any:
        if self._data_cache is ...:
            self._data_cache = self._parse_data()
        return self._data_cache

    def to_dict(self, *, strict: bool = False) -> dict[str, Any]:
        data = self.to_data()
        if isinstance(data, Mapping):
            return dict(data)
        if strict:
            raise TypeError(f'{type(self).__name__} content is not a mapping.')
        return {'value': data}

    def flatten_items(self, data: Any | None = None, prefix: str = '') -> list[tuple[str, str]]:
        source = self.to_data() if data is None else data
        out: list[tuple[str, str]] = []
        if isinstance(source, Mapping):
            for key, value in source.items():
                next_prefix = f'{prefix}.{key}' if prefix else str(key)
                out.extend(self.flatten_items(value, next_prefix))
        elif isinstance(source, list):
            for index, value in enumerate(source):
                next_prefix = f'{prefix}[{index}]' if prefix else f'[{index}]'
                out.extend(self.flatten_items(value, next_prefix))
        else:
            out.append((prefix or '$', '' if source is None else str(source)))
        return out

    def to_flat_dict(self, data: Any | None = None, prefix: str = '') -> dict[str, str]:
        return {key: value for key, value in self.flatten_items(data=data, prefix=prefix)}

    def get_path(
        self,
        path: str | Sequence[str | int],
        default: Any = None,
        *,
        strict: bool = False,
    ) -> Any:
        current = self.to_data()
        for token in _parse_object_path(path):
            if isinstance(token, int):
                if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
                    index = token
                    if -len(current) <= index < len(current):
                        current = current[index]
                        continue
                if strict:
                    raise KeyError(path)
                return default
            if isinstance(current, Mapping) and token in current:
                current = current[token]
                continue
            if strict:
                raise KeyError(path)
            return default
        return current

    def pretty_text(self) -> str:
        return json.dumps(self.to_data(), ensure_ascii=False, indent=2, default=_json_default)

    async def to_llm(self, *, flatten: bool = False, **kwargs: Any) -> Sequence[LLMDocumentPart]:
        if flatten:
            flat = '\n'.join(f'{key}: {value}' for key, value in self.flatten_items())
            return [flat] if flat else []
        return [self.pretty_text()]


class XMLLikedDocument(PlainTextDoc, ABC):
    '''XML/Markup 类文档底层。'''

    Abstract = True

    def to_element_tree(self) -> ET.Element:
        return ET.fromstring(self.to_text(normalize=False))

    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for elem in self.to_element_tree().iter():
            tag = str(getattr(elem, 'tag', '')).split('}', 1)[-1].lower().strip()
            if not tag:
                continue
            counts[tag] = counts.get(tag, 0) + 1
        return counts

    def find_texts(self, tag: str | None = None, *, limit: int | None = None) -> list[str]:
        target = tag.lower().strip() if isinstance(tag, str) and tag.strip() else None
        out: list[str] = []
        for elem in self.to_element_tree().iter():
            elem_tag = str(getattr(elem, 'tag', '')).split('}', 1)[-1].lower().strip()
            if target and elem_tag != target:
                continue
            text = _normalize_multiline_text(' '.join(part.strip() for part in elem.itertext() if str(part).strip()))
            if not text:
                continue
            out.append(text)
            if limit is not None and len(out) >= max(0, int(limit)):
                break
        return out

    def extract_markup_blocks(self) -> list[str]:
        root = self.to_element_tree()
        blocks: list[str] = []
        block_like_tags = {
            'p', 'div', 'section', 'article', 'item', 'entry', 'title', 'subtitle', 'h1', 'h2', 'h3',
            'h4', 'h5', 'h6', 'li', 'td', 'th', 'cell', 'row', 'paragraph', 'text', 'body', 'summary',
        }
        for elem in root.iter():
            tag = str(getattr(elem, 'tag', '')).split('}', 1)[-1].lower()
            if tag not in block_like_tags:
                continue
            text = ' '.join(part.strip() for part in elem.itertext() if str(part).strip())
            text = _normalize_multiline_text(text)
            if text and text not in blocks:
                blocks.append(text)
        if blocks:
            return blocks
        fallback = _normalize_multiline_text(' '.join(part.strip() for part in root.itertext() if str(part).strip()))
        return [fallback] if fallback else []

    async def to_llm(self, *, include_markup: bool = False, **kwargs: Any) -> Sequence[LLMDocumentPart]:
        blocks = self.extract_markup_blocks()
        if include_markup:
            markup = self.to_text(normalize=False)
            if blocks:
                return [*blocks, 'NOTE: Original markup is attached below.', markup]
            return [markup]
        return blocks


class TableSheetLikedDocument(PlainTextDoc, ABC):
    '''表格/工作表类文档底层。'''

    Abstract = True

    @abstractmethod
    def to_sheets(self) -> list[tuple[str, list[list[str]]]]:
        raise NotImplementedError

    def sheet_names(self) -> list[str]:
        return [name for name, _rows in self.to_sheets()]

    def to_rows(self, sheet: int | str = 0) -> list[list[str]]:
        sheets = self.to_sheets()
        if isinstance(sheet, int):
            if not sheets:
                return []
            return sheets[max(0, min(sheet, len(sheets) - 1))][1]
        for name, rows in sheets:
            if name == sheet:
                return rows
        return []

    def infer_header_row(self, sheet: int | str = 0, *, scan_rows: int = 5) -> int:
        rows = self.to_rows(sheet)
        best_index = 0
        best_score = -1
        for index, row in enumerate(rows[:max(1, scan_rows)]):
            non_empty = sum(1 for cell in row if str(cell).strip())
            unique = len({str(cell).strip() for cell in row if str(cell).strip()})
            score = non_empty * 2 + unique
            if score > best_score:
                best_score = score
                best_index = index
        return best_index

    def sheet_to_text(self, sheet_name: str, rows: Sequence[Sequence[Any]], *, delimiter: str = '\t') -> str:
        rendered_rows: list[str] = []
        for row in rows:
            values = [str(cell) if cell is not None else '' for cell in row]
            while values and values[-1] == '':
                values.pop()
            if values:
                rendered_rows.append(delimiter.join(values))
        content = '\n'.join(rendered_rows).strip()
        return f'#{sheet_name}\n{content}'.strip()

    def sheets_to_text(self, *, delimiter: str = '\t') -> str:
        return '\n\n'.join(
            self.sheet_to_text(name, rows, delimiter=delimiter)
            for name, rows in self.to_sheets()
            if rows
        ).strip()

    def to_dicts(self, sheet: int | str = 0) -> list[dict[str, str]]:
        rows = self.to_rows(sheet)
        if not rows:
            return []
        header = [str(cell) for cell in rows[0]]
        out: list[dict[str, str]] = []
        for row in rows[1:]:
            payload: dict[str, str] = {}
            for index, key in enumerate(header):
                if not key:
                    continue
                payload[key] = row[index] if index < len(row) else ''
            if payload:
                out.append(payload)
        return out

    def to_records(self, sheet: int | str = 0, *, header_row: int | None = None) -> list[dict[str, str]]:
        rows = self.to_rows(sheet)
        if not rows:
            return []
        header_index = self.infer_header_row(sheet) if header_row is None else max(0, int(header_row))
        if header_index >= len(rows):
            return []
        header = [str(cell).strip() for cell in rows[header_index]]
        out: list[dict[str, str]] = []
        for row in rows[header_index + 1:]:
            payload: dict[str, str] = {}
            for index, key in enumerate(header):
                if not key:
                    continue
                payload[key] = row[index] if index < len(row) else ''
            if any(str(value).strip() for value in payload.values()):
                out.append(payload)
        return out

    async def to_llm(self, *, delimiter: str = '\t', **kwargs: Any) -> Sequence[LLMDocumentPart]:
        text = self.sheets_to_text(delimiter=delimiter)
        return [text] if text else []


class DelimitedTableDocument(TableSheetLikedDocument, ABC):
    '''CSV/TSV 等分隔文本表格底层。'''

    Abstract = True
    Delimiter: str = ','

    def _dialect(self) -> csv.Dialect | csv.excel:
        sample = self.to_text(normalize=False)[:4096]
        try:
            return csv.Sniffer().sniff(sample, delimiters=',\t;|')
        except Exception:
            delimiter = self.Delimiter

            class _Fallback(csv.excel):
                pass

            _Fallback.delimiter = delimiter  # type: ignore[assignment]
            return _Fallback

    def to_sheets(self) -> list[tuple[str, list[list[str]]]]:
        text = self.to_text(normalize=False)
        reader = csv.reader(io.StringIO(text), dialect=self._dialect())
        rows = [[_utf8_normalize_text(str(cell).strip()) for cell in row] for row in reader]
        rows = [row for row in rows if any(cell for cell in row)]
        return [('Sheet1', rows)]


__all__ = [
    '_json_default',
    '_MARKDOWN_HEADING_RE',
    '_parse_object_path',
    '_fallback_markdown_to_text',
    'PlainTextDoc',
    'DictLikedDocument',
    'XMLLikedDocument',
    'TableSheetLikedDocument',
    'DelimitedTableDocument',
]
