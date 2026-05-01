# -*- coding: utf-8 -*-
"""Public test media routes for gallery/template demos."""

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from core.constants import PUBLIC_DIR

from ...app import get_resources, on_before_app_created


def _resolve_test_media_path(app: FastAPI, filename: str) -> Path | None:
    rel = Path(filename)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        return None
    for raw_public_dir in getattr(app.state, "extra_public_paths", []):
        public_dir = Path(raw_public_dir)
        candidate = (public_dir / "test-media" / rel).resolve()
        try:
            candidate.relative_to((public_dir / "test-media").resolve())
        except Exception:
            continue
        if candidate.is_file():
            return candidate
    public_candidate = PUBLIC_DIR / "test-media" / rel
    if public_candidate.is_file():
        return public_candidate
    return get_resources("test", filename)


@on_before_app_created
def register_test_media_routes(app: FastAPI) -> None:
    @app.get("/test-media/{filename:path}", include_in_schema=False)
    async def serve_test_media(filename: str) -> FileResponse:
        path = _resolve_test_media_path(app, filename)
        if path is None or not path.is_file():
            raise HTTPException(404, "Not found")
        media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)
