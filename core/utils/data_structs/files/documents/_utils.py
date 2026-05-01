

import re
import textwrap
import zipfile

from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from typing import Any, Sequence, cast, TYPE_CHECKING
from PIL import Image as PILImage, ImageDraw, ImageFont

if TYPE_CHECKING:
    from .base import LLMDocumentPart
    from ..medias import Image

_TEXT_ENCODINGS = ('utf-8-sig', 'utf-8', 'utf-16', 'utf-16le', 'utf-16be', 'gb18030', 'big5')

def _decode_text_bytes(data: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030', 'big5', 'latin-1'):
        try:
            return data.decode(encoding)
        except Exception:
            ...
    return data.decode('utf-8', errors='ignore')

def _utf8_normalize_text(text: str) -> str:
    return text.encode('utf-8', errors='ignore').decode('utf-8')

def _score_text_candidate(text: str) -> float:
    if not text:
        return 0.0
    total = len(text)
    printable = sum(1 for ch in text if ch.isprintable() or ch in '\n\r\t')
    weird = sum(1 for ch in text if ch == '\ufffd')
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in '\n\r\t')
    text_ratio = printable / max(total, 1)
    weird_ratio = weird / max(total, 1)
    control_ratio = control / max(total, 1)
    return text_ratio - weird_ratio * 3.0 - control_ratio * 4.0

def _probe_text_bytes(data: bytes, *, sample_size: int = 8192) -> tuple[bool, str, str | None]:
    sample = data[:max(1, int(sample_size))]
    if not sample:
        return True, '', 'utf-8'

    low_control_count = sum(1 for b in sample if b < 8 and b not in (0,))
    if low_control_count > max(1, len(sample) // 16):
        return False, '', None

    if sample.count(b'\x00') > max(1, len(sample) // 8):
        encodings = ['utf-16', 'utf-16le', 'utf-16be', 'utf-8-sig', 'utf-8']
    else:
        encodings = list(_TEXT_ENCODINGS)

    candidates: list[tuple[float, str, str]] = []
    if b'\x00' not in sample:
        encodings.append('latin-1')

    for encoding in encodings:
        try:
            text = sample.decode(encoding)
        except Exception:
            continue
        score = _score_text_candidate(text)
        if score > 0.35:
            candidates.append((score, text, encoding))

    if not candidates:
        return False, '', None

    best_score, _text, best_encoding = max(candidates, key=lambda item: item[0])
    if best_score <= 0.35:
        return False, '', None
    try:
        decoded = data.decode(best_encoding)
    except Exception:
        decoded = _decode_text_bytes(data)
    return True, _utf8_normalize_text(decoded), best_encoding

def _normalize_multiline_text(text: str) -> str:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in text.split('\n')]
    normalized: list[str] = []
    last_blank = False
    for line in lines:
        if line.strip():
            normalized.append(line)
            last_blank = False
        elif not last_blank:
            normalized.append('')
            last_blank = True
    return '\n'.join(normalized).strip()

def _markdown_escape(text: Any) -> str:
    return str(text or '').replace('|', '\\|').replace('\r\n', '\n').replace('\r', '\n').strip()

def _table_to_markdown(rows: Sequence[Sequence[Any]]) -> str:
    normalized_rows: list[list[str]] = []
    max_cols = 0
    for row in rows:
        normalized_row = [_markdown_escape(cell) for cell in row]
        normalized_rows.append(normalized_row)
        max_cols = max(max_cols, len(normalized_row))

    if max_cols <= 0:
        return ''

    padded = [row + [''] * (max_cols - len(row)) for row in normalized_rows]
    if not padded:
        padded = [[''] * max_cols]

    header = padded[0]
    separator = ['---'] * max_cols
    body = padded[1:]
    lines = [
        '| ' + ' | '.join(header) + ' |',
        '| ' + ' | '.join(separator) + ' |',
    ]
    for row in body:
        lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(lines).strip()

def _render_logical_pages_to_images(
    pages: Sequence[Sequence["LLMDocumentPart"]],
    *,
    width: int = 1440,
    margin: int = 36,
    background: str = 'white',
) -> list["Image"]:
    font = ImageFont.load_default()
    line_height = 24
    max_text_width = max(200, width - margin * 2)
    approx_chars_per_line = max(20, int(max_text_width / 9))
    out: list["Image"] = []

    for page_items in pages:
        rendered_blocks: list[tuple[str, Any]] = []
        total_height = margin

        for item in page_items:
            if isinstance(item, str):
                text = _normalize_multiline_text(item)
                if not text:
                    continue
                wrapped_lines: list[str] = []
                for raw_line in text.split('\n'):
                    if not raw_line.strip():
                        wrapped_lines.append('')
                        continue
                    wrapped_lines.extend(textwrap.wrap(raw_line, width=approx_chars_per_line) or [''])
                rendered_blocks.append(('text', wrapped_lines))
                total_height += max(line_height, len(wrapped_lines) * line_height) + 18
                continue

            try:
                with PILImage.open(BytesIO(item.to_bytes())) as pil_img:
                    image = pil_img.convert('RGB')
            except Exception:
                continue

            image.thumbnail((max_text_width, 720))
            rendered_blocks.append(('image', image.copy()))
            total_height += image.height + 24

        total_height = max(total_height + margin, 240)
        canvas = PILImage.new('RGB', (width, total_height), color=background)
        draw = ImageDraw.Draw(canvas)
        cursor_y = margin

        for kind, payload in rendered_blocks:
            if kind == 'text':
                for line in cast(list[str], payload):
                    draw.text((margin, cursor_y), line, fill='black', font=font)
                    cursor_y += line_height
                cursor_y += 18
                continue

            image = cast(Any, payload)
            canvas.paste(image, (margin, cursor_y))
            cursor_y += int(image.height) + 24

        buf = BytesIO()
        canvas.save(buf, format='PNG')
        from ..medias import Image
        out.append(Image(buf.getvalue()))

    return out

def _iter_zip_file_names(data: bytes) -> list[str]:
    if not zipfile.is_zipfile(BytesIO(data)):
        return []
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            return zf.namelist()
    except Exception:
        return []

def _read_zip_mimetype(data: bytes) -> str:
    if not zipfile.is_zipfile(BytesIO(data)):
        return ''
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            return zf.read('mimetype').decode('utf-8', errors='ignore').strip().lower()
    except Exception:
        return ''

def _resolve_media_source(raw_src: str, base_source: str | Path | bytes) -> str | Path:
    src = raw_src.strip()
    if not src:
        return src
    if src.startswith('data:'):
        return src
    if re.match(r'^[a-z][a-z0-9+.-]*://', src, re.IGNORECASE):
        return src

    if isinstance(base_source, Path):
        return (base_source.parent / src).resolve()

    if isinstance(base_source, str):
        base_text = base_source.strip()
        if re.match(r'^https?://', base_text, re.IGNORECASE):
            return urljoin(base_text, src)
        if '<' not in base_text and '>' not in base_text:
            base_path = Path(base_text)
            if base_path.suffix:
                return (base_path.parent / src).resolve()

    return src

