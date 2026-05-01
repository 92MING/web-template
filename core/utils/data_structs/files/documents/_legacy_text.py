

import re

from typing import Iterable

from ._utils import _decode_text_bytes, _normalize_multiline_text


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        normalized = _normalize_multiline_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def extract_best_effort_text(data: bytes, *, min_line_length: int = 4) -> str:
    candidates: list[str] = []

    for decoded in (
        _decode_text_bytes(data),
        data.decode('utf-16le', errors='ignore'),
        data.decode('utf-16be', errors='ignore'),
    ):
        cleaned = ''.join(ch if ch.isprintable() or ch in '\n\r\t' else ' ' for ch in decoded)
        lines = [line.strip() for line in cleaned.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
        candidates.extend(line for line in lines if len(line) >= int(min_line_length))

    ascii_runs = [match.decode('utf-8', errors='ignore') for match in re.findall(rb'[\x20-\x7e\t\r\n]{4,}', data)]
    utf16le_runs = [match.decode('utf-16le', errors='ignore') for match in re.findall(rb'(?:[\x20-\x7e]\x00){4,}', data)]
    candidates.extend(ascii_runs)
    candidates.extend(utf16le_runs)

    return '\n'.join(_dedupe_keep_order(candidates)).strip()


__all__ = ['extract_best_effort_text']
