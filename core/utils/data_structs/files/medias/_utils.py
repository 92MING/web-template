"""Utility functions for media file models (ported from thinkthinksyn)."""

import os
import hashlib
import logging

from functools import cache
from shutil import which

_logger = logging.getLogger(__name__)

# ── JSON schema helpers ──────────────────────────────────────────────────────

_default_media_json_schema: dict = {
    'properties': {
        'type': {'title': 'Type', 'type': 'string'},
        'data': {'title': 'Data', 'type': 'string'},
    },
    'required': ['type', 'data'],
    'title': '_MediaModel',
    'type': 'object',
}


def _dump_media_dict(data: str, cls: type) -> dict:
    return {
        'type': cls.__name__.lower(),
        'data': data,
    }

@cache
def _get_media_json_schema(cls: type) -> dict:
    schema = _default_media_json_schema.copy()
    schema['title'] = cls.__name__
    return schema

# ── misc helpers ─────────────────────────────────────────────────────────────
def _hash_md5(data: bytes) -> str:
    m = hashlib.md5()
    m.update(data)
    return m.hexdigest()

def _try_get_from_dict(d: dict, *keys: str):
    for k in keys:
        try:
            return d[k]
        except KeyError:
            continue
    return None

# ── ffmpeg ───────────────────────────────────────────────────────────────────
@cache
def init_ffmpeg():
    """Ensure ffmpeg/ffprobe/ffplay are available.

    If all three are already on PATH, this is a no-op.  Otherwise it tries to
    locate them via ``ffmpeg_downloader`` (must be installed separately) and
    patches *moviepy* and *pydub* to use the discovered paths.
    """

    if which('ffmpeg') and which('ffprobe') and which('ffplay'):
        return

    try:
        import ffmpeg_downloader as ffdl
    except ImportError:
        _logger.warning(
            'ffmpeg not found on PATH and ffmpeg_downloader is not installed. '
            'Audio/Video operations may fail. Run `python scripts/install.py` '
            'to install ffmpeg automatically.'
        )
        return

    ffmpeg_path = ffdl.ffmpeg_path
    ffprobe_path = ffdl.ffprobe_path
    ffplay_path = ffdl.ffplay_path

    if not (ffmpeg_path and ffprobe_path and ffplay_path):
        _logger.warning(
            'ffmpeg_downloader is installed but ffmpeg binaries are missing. '
            'Run `python scripts/install.py` to download them.'
        )
        return

    ffmpeg_dir = ffdl.ffmpeg_dir
    os.environ['FFMPEG_BINARY'] = ffmpeg_path
    os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')

    # patch moviepy
    try:
        import moviepy.config as mpy_config
        mpy_config.FFMPEG_BINARY = ffmpeg_path
    except Exception:
        pass

    # patch pydub
    try:
        from pydub.utils import which as pydub_origin_which
        import pydub.utils

        def pydub_which(cmd):
            if cmd == 'ffmpeg':
                return ffmpeg_path
            return pydub_origin_which(cmd)

        pydub.utils.which = pydub_which
        pydub.utils.get_encoder_name = lambda: ffmpeg_path
        pydub.utils.get_player_name = lambda: ffplay_path
        pydub.utils.get_prober_name = lambda: ffprobe_path
    except Exception:
        pass
