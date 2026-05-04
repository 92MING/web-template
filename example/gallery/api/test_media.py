# -*- coding: utf-8 -*-
"""Gallery-only test media route."""

import mimetypes
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse

from core.server import Route
from core.server.app import get_resources


class GalleryTestMediaRoute(Route):
    RoutePath = "/test-media/{filename:path}"
    IncludeInSchema = False

    async def get(self, filename: str) -> Any:
        path = get_resources("test", filename)
        if path is None or not path.is_file():
            raise HTTPException(404, "Not found")
        media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)