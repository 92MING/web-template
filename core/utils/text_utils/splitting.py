

import os
import math
import jieba
import regex as re

from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from .detect import word_count
from ..build_utils import build_cython as _build_cython

_splitting_fast = _build_cython(Path(os.path.join(os.path.dirname(__file__), '_splitting_fast.pyx')))
_c_hard_split_units = _splitting_fast.hard_split_units
_c_pack_spans_balanced = _splitting_fast.pack_spans_balanced


class TextChunk(TypedDict):
    '''按词数切分后的文本块。'''

    text: str
    '''文本块内容。'''

    offset: int
    '''文本块在原始文本中的字符偏移量。'''

    word_count: int
    '''文本块的估算词数。'''


_DEFAULT_SPLIT_PATTERNS = (
    re.compile(r'(?:\r?\n\s*){2,}', re.UNICODE),
    re.compile(r'(?:\r?\n)(?=(?:#{1,6}\s|```|~~~|\|.+\||<(?:div|section|article|aside|nav|main|p|ul|ol|li|table|tr|td|th|pre|code|h[1-6])\b))', re.UNICODE),
    re.compile(r'(?:\r?\n)+', re.UNICODE),
    re.compile(r'(?:[。！？!?]+|…{1,2}|(?<!\d)\.(?!\d))(?:["\'”’」』）\]]*\s*)', re.UNICODE),
    re.compile(r'[；;：:]+(?:\s*)', re.UNICODE),
    re.compile(r'[，,、]+(?:\s*)', re.UNICODE),
    re.compile(r'\s+', re.UNICODE),
)

_CJK_BLOCK_PAT = re.compile(
    r'[\u3400-\u4DBF\u4E00-\u9FFF\u3040-\u30FF\u31F0-\u31FF\uAC00-\uD7AF\u1100-\u11FF\u0E00-\u0E7F]+',
    re.UNICODE,
)
_NON_CJK_TOKEN_PAT = re.compile(
    r'</?[A-Za-z][^>\n]*?>'
    r'|```+'
    r'|~~~+'
    r'|[A-Za-z_][A-Za-z0-9_./:-]*'
    r'|\d+(?:\.\d+)?'
    r'|\|+'
    r'|[{}\[\]()<>]+'
    r'|[:;,=+\-*/\\@#$%^&!?~]+'
    r'|[^\s]',
    re.UNICODE,
)


class _SemanticUnit(TypedDict):
    start: int
    end: int
    word_count: int


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _span_word_count(text: str, start: int, end: int) -> int:
    start, end = _trim_span(text, start, end)
    if start >= end:
        return 0
    return word_count(text[start:end])


def _make_chunk(text: str, start: int, end: int) -> TextChunk | None:
    start, end = _trim_span(text, start, end)
    if start >= end:
        return None
    chunk_text = text[start:end]
    return {
        'text': chunk_text,
        'offset': start,
        'word_count': word_count(chunk_text),
    }


def _split_span_by_pattern(text: str, start: int, end: int, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    for match in pattern.finditer(text, start, end):
        split_end = match.end()
        if split_end <= cursor:
            continue
        trimmed = _trim_span(text, cursor, split_end)
        if trimmed[0] < trimmed[1]:
            spans.append(trimmed)
        cursor = split_end

    if cursor < end:
        trimmed = _trim_span(text, cursor, end)
        if trimmed[0] < trimmed[1]:
            spans.append(trimmed)
    return spans


def _pack_spans_balanced(text: str, spans: list[tuple[int, int]], max_word_count: int) -> list[tuple[int, int]]:
    if not spans:
        return []

    span_word_counts = [_span_word_count(text, start, end) for start, end in spans]

    if _c_pack_spans_balanced is not None:
        return _c_pack_spans_balanced(spans, span_word_counts, max_word_count)

    packed: list[tuple[int, int]] = []
    index = 0

    while index < len(spans):
        remaining_word_count = sum(span_word_counts[index:])
        if remaining_word_count <= 0:
            packed.extend(spans[index:])
            break

        remaining_chunk_count = max(1, math.ceil(remaining_word_count / max_word_count))
        target_word_count = min(max_word_count, max(1, math.ceil(remaining_word_count / remaining_chunk_count)))

        current_word_count = 0
        best_end_index = index
        best_word_count = span_word_counts[index]
        best_score = abs(best_word_count - target_word_count)

        for cursor in range(index, len(spans)):
            next_word_count = current_word_count + span_word_counts[cursor]
            if cursor > index and next_word_count > max_word_count:
                break

            current_word_count = next_word_count
            current_score = abs(current_word_count - target_word_count)
            if current_score < best_score or (current_score == best_score and current_word_count > best_word_count):
                best_end_index = cursor
                best_word_count = current_word_count
                best_score = current_score

            if current_word_count >= target_word_count and current_score == 0:
                break

        packed.append((spans[index][0], spans[best_end_index][1]))
        index = best_end_index + 1

    return packed


def _iter_semantic_units(text: str, start: int, end: int) -> list[_SemanticUnit]:
    units: list[_SemanticUnit] = []
    cursor = start

    while cursor < end:
        cjk_match = _CJK_BLOCK_PAT.search(text, cursor, end)
        block_start = cjk_match.start() if cjk_match else end

        if cursor < block_start:
            for match in _NON_CJK_TOKEN_PAT.finditer(text, cursor, block_start):
                token_start, token_end = match.span()
                token_count = word_count(match.group())
                if token_count > 0:
                    units.append({'start': token_start, 'end': token_end, 'word_count': token_count})

        if not cjk_match:
            break

        seg_start, seg_end = cjk_match.span()
        segment = text[seg_start:seg_end]
        has_token = False
        try:
            for _, rel_start, rel_end in jieba.tokenize(segment, mode='default'):
                token_text = segment[rel_start:rel_end]
                token_count = word_count(token_text)
                if token_count <= 0:
                    continue
                has_token = True
                units.append({
                    'start': seg_start + rel_start,
                    'end': seg_start + rel_end,
                    'word_count': token_count,
                })
        except Exception:
            has_token = False

        if not has_token:
            for idx in range(seg_start, seg_end):
                units.append({'start': idx, 'end': idx + 1, 'word_count': word_count(text[idx:idx + 1]) or 1})

        cursor = seg_end

    return units


def _hard_split_span(text: str, start: int, end: int, max_word_count: int) -> list[tuple[int, int]]:
    units = _iter_semantic_units(text, start, end)
    if not units:
        trimmed = _trim_span(text, start, end)
        return [trimmed] if trimmed[0] < trimmed[1] else []

    total_word_count = sum(unit['word_count'] for unit in units)

    if _c_hard_split_units is not None:
        raw = _c_hard_split_units(
            [u['start'] for u in units],
            [u['end'] for u in units],
            [u['word_count'] for u in units],
            max_word_count,
            total_word_count,
        )
        spans: list[tuple[int, int]] = []
        for s, e in raw:
            trimmed = _trim_span(text, s, e)
            if trimmed[0] < trimmed[1]:
                spans.append(trimmed)
        return spans

    chunk_count = max(1, math.ceil(total_word_count / max_word_count))
    target_word_count = min(max_word_count, max(1, math.ceil(total_word_count / chunk_count)))

    spans: list[tuple[int, int]] = []
    unit_index = 0

    while unit_index < len(units):
        remaining_word_count = sum(unit['word_count'] for unit in units[unit_index:])
        remaining_chunk_count = max(1, math.ceil(remaining_word_count / max_word_count))
        dynamic_target = min(max_word_count, max(target_word_count, math.ceil(remaining_word_count / remaining_chunk_count)))

        current_word_count = 0
        best_index = unit_index
        best_word_count = units[unit_index]['word_count']
        best_score = abs(best_word_count - dynamic_target)

        for cursor in range(unit_index, len(units)):
            next_word_count = current_word_count + units[cursor]['word_count']
            if cursor > unit_index and next_word_count > max_word_count:
                break

            current_word_count = next_word_count
            current_score = abs(current_word_count - dynamic_target)
            if current_score < best_score or (current_score == best_score and current_word_count > best_word_count):
                best_index = cursor
                best_word_count = current_word_count
                best_score = current_score

        trimmed = _trim_span(text, units[unit_index]['start'], units[best_index]['end'])
        if trimmed[0] < trimmed[1]:
            spans.append(trimmed)
        unit_index = best_index + 1

    return spans


def _split_span_recursive(
    text: str,
    start: int,
    end: int,
    max_word_count: int,
    pattern_index: int = 0,
) -> list[tuple[int, int]]:
    start, end = _trim_span(text, start, end)
    if start >= end:
        return []

    if _span_word_count(text, start, end) <= max_word_count:
        return [(start, end)]

    for idx in range(pattern_index, len(_DEFAULT_SPLIT_PATTERNS)):
        spans = _split_span_by_pattern(text, start, end, _DEFAULT_SPLIT_PATTERNS[idx])
        if len(spans) <= 1:
            continue

        refined: list[tuple[int, int]] = []
        for sub_start, sub_end in spans:
            if _span_word_count(text, sub_start, sub_end) <= max_word_count:
                refined.append((sub_start, sub_end))
            else:
                refined.extend(_split_span_recursive(text, sub_start, sub_end, max_word_count, idx + 1))

        if refined:
            return _pack_spans_balanced(text, refined, max_word_count)

    return _hard_split_span(text, start, end, max_word_count)


def split_text_by_word_count(text: str, max_word_count: int = 512) -> list[TextChunk]:
    '''按语义边界递归切分文本，并尽量拼接到接近词数上限。

    切分优先级依次为：段落 -> 换行 -> 句子 -> 分号/冒号 -> 逗号顿号 -> 空白。
    若仍无法满足上限，则退化为字符级硬切分。
    '''
    if max_word_count <= 0:
        raise ValueError('max_word_count must be greater than 0.')
    if not text.strip():
        return []

    spans = _split_span_recursive(text, 0, len(text), max_word_count)
    spans = _pack_spans_balanced(text, spans, max_word_count)

    result: list[TextChunk] = []
    for start, end in spans:
        chunk = _make_chunk(text, start, end)
        if chunk is not None:
            result.append(chunk)
    return result


def truncate_text_by_word_count(text: str, max_word_count: int) -> str:
    '''按词数上限语义截断文本。'''
    if max_word_count <= 0:
        return ''
    if word_count(text) <= max_word_count:
        return text.strip()
    chunks = split_text_by_word_count(text, max_word_count=max_word_count)
    return chunks[0]['text'] if chunks else ''


__all__ = ['TextChunk', 'split_text_by_word_count', 'truncate_text_by_word_count']