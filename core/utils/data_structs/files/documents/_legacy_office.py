

import os
import shutil
import subprocess
import tempfile

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Literal

from ._legacy_text import extract_best_effort_text

try:
    import olefile  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    olefile = None  # type: ignore[assignment]

OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
LegacyKind = Literal['doc', 'ppt']
OutputKind = Literal['docx', 'pptx', 'pdf', 'text', 'none']


@dataclass(slots=True)
class ConversionResult:
    output_kind: OutputKind = 'none'
    backend: str = 'none'
    converted_bytes: bytes | None = None
    text_content: str | None = None
    warnings: list[str] = field(default_factory=list)


def is_ole_container(data: bytes) -> bool:
    return data.startswith(OLE_MAGIC)


def infer_legacy_ole_kind(data: bytes) -> str | None:
    if not is_ole_container(data):
        return None
    if olefile is None:
        return None

    try:
        with olefile.OleFileIO(BytesIO(data)) as ole:
            entries = {'/'.join(parts).lower() for parts in ole.listdir(streams=True, storages=False)}
    except Exception:
        return None

    if 'worddocument' in entries or '1table' in entries or '0table' in entries:
        return 'doc'
    if 'powerpoint document' in entries or 'current user' in entries:
        return 'ppt'
    if 'bodytext/section0' in entries or 'prvtext' in entries:
        return 'doc'
    return None


def convert_legacy_office_bytes(data: bytes, *, kind: LegacyKind, source_suffix: str) -> ConversionResult:
    for converter in (_convert_via_soffice, _convert_via_com):
        result = converter(data, kind=kind, source_suffix=source_suffix)
        if result is not None:
            return result

    text = extract_best_effort_text(data)
    if text:
        return ConversionResult(
            output_kind='text',
            backend='text-fallback',
            text_content=text,
            warnings=[f'Fell back to coarse text extraction for legacy {kind} source.'],
        )

    return ConversionResult(
        output_kind='none',
        backend='none',
        warnings=[f'No available backend could extract legacy {kind} source.'],
    )


def _convert_via_com(data: bytes, *, kind: LegacyKind, source_suffix: str) -> ConversionResult | None:
    if os.environ.get('ENABLE_OFFICE_COM', '').strip().lower() not in {'1', 'true', 'yes'}:
        return None
    if os.name != 'nt':
        return None

    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except Exception:
        return None

    with tempfile.TemporaryDirectory(prefix='proj_legacy_office_') as tmp_dir:
        input_path = Path(tmp_dir) / f'input{source_suffix}'
        output_path = Path(tmp_dir) / f'output.{"docx" if kind == "doc" else "pptx"}'
        input_path.write_bytes(data)

        pythoncom.CoInitialize()
        app = None
        doc = None
        try:
            if kind == 'doc':
                app = win32com.client.DispatchEx('Word.Application')
                app.Visible = False
                app.DisplayAlerts = 0
                try:
                    app.AutomationSecurity = 3
                except Exception:
                    ...
                doc = app.Documents.Open(str(input_path), ReadOnly=True, AddToRecentFiles=False, Visible=False)
                doc.SaveAs2(str(output_path), FileFormat=16)
            else:
                app = win32com.client.DispatchEx('PowerPoint.Application')
                doc = app.Presentations.Open(str(input_path), ReadOnly=True, Untitled=False, WithWindow=False)
                doc.SaveAs(str(output_path), 24)

            if output_path.exists() and output_path.stat().st_size > 0:
                return ConversionResult(
                    output_kind='docx' if kind == 'doc' else 'pptx',
                    backend='com',
                    converted_bytes=output_path.read_bytes(),
                )
        except Exception:
            return None
        finally:
            try:
                if doc is not None:
                    doc.Close()
            except Exception:
                ...
            try:
                if app is not None:
                    app.Quit()
            except Exception:
                ...
            try:
                pythoncom.CoUninitialize()
            except Exception:
                ...

    return None


def _convert_via_soffice(data: bytes, *, kind: LegacyKind, source_suffix: str) -> ConversionResult | None:
    soffice = os.environ.get('SOFFICE_PATH') or shutil.which('soffice') or shutil.which('libreoffice')
    if not soffice:
        return None

    conversion_targets: list[tuple[str, OutputKind]] = [('docx' if kind == 'doc' else 'pptx', 'docx' if kind == 'doc' else 'pptx')]
    if kind == 'doc':
        conversion_targets.extend([('pdf', 'pdf'), ('txt', 'text')])
    else:
        conversion_targets.append(('pdf', 'pdf'))

    with tempfile.TemporaryDirectory(prefix='proj_soffice_') as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / f'input{source_suffix}'
        profile_path = tmp_path / 'profile'
        input_path.write_bytes(data)

        for convert_to, output_kind in conversion_targets:
            output_suffix = 'txt' if output_kind == 'text' else output_kind
            output_path = tmp_path / f'input.{output_suffix}'
            if output_path.exists():
                output_path.unlink()

            command = [
                soffice,
                '--headless',
                '--nologo',
                '--nodefault',
                '--nolockcheck',
                '--norestore',
                '--nofirststartwizard',
                f'-env:UserInstallation=file:///{profile_path.as_posix()}',
                '--convert-to',
                convert_to,
                '--outdir',
                str(tmp_path),
                str(input_path),
            ]
            try:
                completed = subprocess.run(command, check=False, capture_output=True, timeout=90)
            except Exception:
                continue

            if completed.returncode != 0:
                continue
            if not output_path.exists() or output_path.stat().st_size <= 0:
                continue

            if output_kind == 'text':
                return ConversionResult(
                    output_kind='text',
                    backend='soffice',
                    text_content=extract_best_effort_text(output_path.read_bytes()),
                )
            return ConversionResult(
                output_kind=output_kind,
                backend='soffice',
                converted_bytes=output_path.read_bytes(),
            )

    return None


__all__ = [
    'ConversionResult',
    'convert_legacy_office_bytes',
    'infer_legacy_ole_kind',
    'is_ole_container',
]
