"""Comprehensive tests for media operations and FileID deferred loading.

Covers:
  - Image: create blank, crop, crop_into, to_bytes, format, size, mode, copy, save
  - Audio: create from WAV, split_on_silence, append, to_bytes, len, copy
  - Video: create from bytes, to_bytes, duration, fps, size, to_base64, save
  - FileID deferred loading for Image, Audio, Video, and documents
  - AcceptableFileSource dict / FileID acceptance
"""


import asyncio
import base64
import os
import sys
import tempfile
import wave

from io import BytesIO
from pathlib import Path
from typing import cast
from unittest import TestCase, main

import numpy as np
from PIL import Image as PILImage
from moviepy.video.VideoClip import ImageClip
from moviepy.audio.io.AudioFileClip import AudioFileClip

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.utils.data_structs import Audio, Image, Video, PDF, PlainText
from core.utils.data_structs.files.base import FileID
from core.utils.data_structs.files.medias.loader import (
    AcceptableFileSource,
    is_acceptable_file_source,
    save_get_file_source,
)


def _await(coro):
    return asyncio.run(coro)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_wav_bytes(duration_sec: float = 0.5, sample_rate: int = 16000) -> bytes:
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    wave_data = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    pcm16 = np.clip(wave_data * 32767, -32768, 32767).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _make_silence_wav_bytes(duration_sec: float = 0.3, sample_rate: int = 16000) -> bytes:
    """Generate pure silence WAV."""
    pcm16 = np.zeros(int(sample_rate * duration_sec), dtype=np.int16)
    buf = BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _make_png_bytes(width: int = 64, height: int = 64) -> bytes:
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :, 1] = 180
    img = PILImage.fromarray(arr, mode='RGB')
    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _make_video_mp4_bytes(duration_sec: float = 0.5) -> bytes:
    img_bytes = _make_png_bytes(64, 64)
    wav_bytes = _make_wav_bytes(duration_sec)
    with tempfile.TemporaryDirectory(prefix='proj_test_') as td:
        td_path = Path(td)
        audio_path = td_path / 'audio.wav'
        video_path = td_path / 'video.mp4'
        audio_path.write_bytes(wav_bytes)

        arr = np.array(PILImage.open(BytesIO(img_bytes)).convert('RGB'))
        clip = ImageClip(arr)
        if hasattr(clip, 'with_duration'):
            clip = clip.with_duration(duration_sec)
        else:
            clip = clip.set_duration(duration_sec)

        audio_clip = AudioFileClip(str(audio_path))
        if hasattr(audio_clip, 'subclipped'):
            audio_clip = audio_clip.subclipped(0, duration_sec)
        else:
            audio_clip = audio_clip.subclip(0, duration_sec)

        if hasattr(clip, 'with_audio'):
            clip = clip.with_audio(audio_clip)
        else:
            clip = clip.set_audio(audio_clip)

        clip.write_videofile(str(video_path), codec='libx264', audio_codec='aac', fps=24, logger=None)
        try:
            clip.close()
        except Exception:
            pass
        try:
            audio_clip.close()
        except Exception:
            pass
        return video_path.read_bytes()


def _make_pdf_bytes() -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((36, 72), 'Media Test PDF')
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class _MemoryFileStorage:
    """In-memory FileStorageProtocol for tests."""
    def __init__(self, data: bytes):
        self._data = data

    async def get_file(self, object_id: str, *, chunk_size: int = 65536):
        for index in range(0, len(self._data), max(1, chunk_size)):
            yield self._data[index:index + max(1, chunk_size)]

    async def put_file(self, data: bytes, category: str, expire: float | None, type: str | None = None, *, object_name: str | None = None) -> str:
        return f'{category}:{type or "raw"}:{len(data)}'

    async def delete_file(self, object_id: str) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════════════
# Image tests
# ═══════════════════════════════════════════════════════════════════════════

class TestImageOperations(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.png_bytes = _make_png_bytes(128, 96)

    def test_create_from_bytes_and_deferred_load(self):
        img = Image(self.png_bytes)
        self.assertFalse(img._loaded)
        w, h = img.size  # triggers lazy load
        self.assertTrue(img._loaded)
        self.assertEqual(w, 128)
        self.assertEqual(h, 96)

    def test_create_blank_via_new(self):
        img = Image.New(200, 100, color=(255, 0, 0))
        self.assertEqual(img.size, (200, 100))
        self.assertEqual(img.mode, 'RGB')

    def test_to_bytes_png_and_jpeg(self):
        img = Image(self.png_bytes)
        png_data = img.to_bytes(format='png')
        self.assertTrue(len(png_data) > 0)
        self.assertTrue(png_data[:4] == b'\x89PNG')

        jpeg_data = img.to_bytes(format='jpeg')
        self.assertTrue(len(jpeg_data) > 0)
        self.assertTrue(jpeg_data[:2] == b'\xff\xd8')

    def test_to_base64_roundtrip(self):
        img = Image(self.png_bytes)
        b64 = img.to_base64(format='png')
        decoded = base64.b64decode(b64)
        self.assertTrue(decoded[:4] == b'\x89PNG')

    def test_to_base64_url_scheme(self):
        img = Image(self.png_bytes)
        url = img.to_base64(format='png', url_scheme=True)
        self.assertTrue(url.startswith('data:image/png;base64,'))

    def test_crop(self):
        img = Image.New(100, 100, color=(0, 255, 0))
        cropped = img.crop((10, 10, 50, 50))
        self.assertEqual(cropped.size, (40, 40))

    def test_crop_into_horizontal(self):
        img = Image.New(200, 100, color=(0, 0, 255))
        pieces = img.crop_into(3, method='horizontal', overlap=0.2)
        self.assertEqual(len(pieces), 3)
        for piece in pieces:
            self.assertIsInstance(piece, Image)
            self.assertTrue(piece._loaded)

    def test_crop_into_vertical(self):
        img = Image.New(100, 200, color=(0, 0, 255))
        pieces = img.crop_into(2, method='vertical', overlap=0.5)
        self.assertEqual(len(pieces), 2)

    def test_copy(self):
        img = Image.New(50, 50)
        copied = img.copy()
        self.assertIsNot(img._image, copied._image)
        self.assertEqual(img.size, copied.size)

    def test_pixel_count_and_channel_count(self):
        img = Image.New(10, 10)
        self.assertEqual(img.pixel_count, 100)
        self.assertEqual(img.channel_count, 3)

    def test_to_md5_hash_deterministic(self):
        img = Image.New(10, 10, color=(1, 2, 3))
        h1 = img.to_md5_hash(format='png')
        h2 = img.to_md5_hash(format='png')
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 32)

    def test_save_to_file(self):
        img = Image.New(32, 32, color=(128, 128, 128))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'test_img.png'
            result = img.save(path)
            self.assertTrue(Path(result).exists())
            self.assertTrue(Path(result).stat().st_size > 0)

    def test_save_to_bytes_io(self):
        img = Image.New(24, 24, color=(32, 64, 128))
        buf = BytesIO()
        result = img.save(buf, format='PNG')
        self.assertIs(result, buf)
        self.assertTrue(buf.getvalue().startswith(b'\x89PNG'))

    def test_pil_delegation_resize(self):
        img = Image.New(100, 100)
        resized = img.resize((50, 50))
        self.assertIsInstance(resized, Image)
        self.assertEqual(resized.size, (50, 50))

    def test_pil_delegation_convert(self):
        img = Image.New(10, 10, mode='RGB')
        rgba = img.convert('RGBA')
        self.assertIsInstance(rgba, Image)
        self.assertEqual(rgba.mode, 'RGBA')

    def test_repr(self):
        img = Image.New(20, 30)
        r = repr(img)
        self.assertIn('20x30', r)
        self.assertIn('Image', r)


# ═══════════════════════════════════════════════════════════════════════════
# Audio tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAudioOperations(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wav_bytes = _make_wav_bytes(1.0)
        cls.silence_bytes = _make_silence_wav_bytes(0.5)
        cls.mp3_bytes = (_PROJECT_ROOT / 'resources' / 'test' / 'test.mp3').read_bytes()

    def test_create_from_bytes_and_deferred_load(self):
        audio = Audio(self.wav_bytes)
        self.assertFalse(audio._loaded)
        length = len(audio)  # triggers lazy load
        self.assertTrue(audio._loaded)
        self.assertGreater(length, 0)

    def test_to_bytes_wav(self):
        audio = Audio(self.wav_bytes)
        data = audio.to_bytes(format='wav')
        self.assertTrue(len(data) > 0)
        self.assertTrue(data[:4] == b'RIFF')

    def test_mp3_bytes_infer_format_and_load(self):
        audio = Audio(self.mp3_bytes)
        self.assertEqual(audio.format, 'mp3')
        self.assertGreater(len(audio), 0)

    def test_empty_bytes_fail_before_native_decoder(self):
        audio = Audio(b'')
        with self.assertRaisesRegex(ValueError, 'empty'):
            len(audio)

    def test_to_base64_roundtrip(self):
        audio = Audio(self.wav_bytes)
        b64 = audio.to_base64(format='wav')
        decoded = base64.b64decode(b64)
        self.assertTrue(decoded[:4] == b'RIFF')

    def test_to_base64_url_scheme(self):
        audio = Audio(self.wav_bytes)
        url = audio.to_base64(format='wav', url_scheme=True)
        self.assertTrue(url.startswith('data:audio/wav;base64,'))

    def test_len_returns_milliseconds(self):
        audio = Audio(self.wav_bytes)
        ms = len(audio)
        # 1 second audio ≈ 1000ms, allow some tolerance
        self.assertGreater(ms, 900)
        self.assertLess(ms, 1200)

    def test_duration_property(self):
        audio = Audio(self.wav_bytes)
        self.assertGreater(audio.end_time, 0)
        self.assertAlmostEqual(audio.end_time, 1.0, delta=0.1)

    def test_frame_size(self):
        audio = Audio(self.wav_bytes)
        self.assertGreater(audio.frame_size, 0)

    def test_split_on_silence(self):
        # Build: tone + silence + tone
        from pydub import AudioSegment
        tone_seg = AudioSegment.from_file(BytesIO(self.wav_bytes), format='wav')
        silence_seg = AudioSegment.from_file(BytesIO(self.silence_bytes), format='wav')
        combined = tone_seg + silence_seg + tone_seg
        combined_audio = Audio(combined)

        chunks = combined_audio.split_on_silence(
            min_silence_len=200,
            silence_threshold=-40,
            keep_silence=50,
        )
        self.assertIsInstance(chunks, list)
        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertIsInstance(chunk, Audio)
            self.assertGreater(len(chunk), 0)

    def test_append(self):
        a1 = Audio(self.wav_bytes)
        a2 = Audio(self.wav_bytes)
        combined = a1.append(a2, crossfade=0)
        self.assertIsInstance(combined, Audio)
        self.assertGreater(len(combined), len(a1))

    def test_copy(self):
        audio = Audio(self.wav_bytes)
        copied = audio.copy()
        self.assertIsInstance(copied, Audio)
        self.assertEqual(len(audio), len(copied))

    def test_to_md5_hash_deterministic(self):
        audio = Audio(self.wav_bytes)
        h1 = audio.to_md5_hash()
        h2 = audio.to_md5_hash()
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 32)

    def test_audio_own_frame_size(self):
        audio = Audio(self.wav_bytes)
        self.assertGreater(audio.frame_size, 0)
        # frame_size = frame_rate * frame_width
        self.assertEqual(audio.frame_size, 16000 * 2)

    def test_audio_own_end_time(self):
        audio = Audio(self.wav_bytes)
        self.assertAlmostEqual(audio.end_time, 1.0, delta=0.1)


# ═══════════════════════════════════════════════════════════════════════════
# Video tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVideoOperations(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mp4_bytes = _make_video_mp4_bytes(0.5)

    def test_create_from_bytes_deferred(self):
        video = Video(self.mp4_bytes)
        self.assertIsNotNone(video._defer_loader)
        # Accessing duration should trigger deferred load
        dur = video.duration
        self.assertIsNotNone(video.reader)
        self.assertGreater(dur, 0)

    def test_to_bytes_preserves_source_without_loading(self):
        video = Video(self.mp4_bytes)
        data = video.to_bytes()
        self.assertEqual(data, self.mp4_bytes)

    def test_to_bytes_after_load(self):
        video = Video(self.mp4_bytes)
        _ = video.duration  # force load
        data = video.to_bytes()
        self.assertGreater(len(data), 0)

    def test_duration_and_fps(self):
        video = Video(self.mp4_bytes)
        self.assertAlmostEqual(video.duration, 0.5, delta=0.2)
        self.assertGreater(video.fps, 0)

    def test_size(self):
        video = Video(self.mp4_bytes)
        w, h = video.size
        self.assertEqual(w, 64)
        self.assertEqual(h, 64)

    def test_to_base64(self):
        video = Video(self.mp4_bytes)
        b64 = video.to_base64()
        decoded = base64.b64decode(b64)
        self.assertEqual(decoded, self.mp4_bytes)

    def test_to_base64_url_scheme(self):
        video = Video(self.mp4_bytes)
        url = video.to_base64(url_scheme=True)
        self.assertTrue(url.startswith('data:video/'))

    def test_to_md5_hash_deterministic(self):
        video = Video(self.mp4_bytes)
        h1 = video.to_md5_hash()
        h2 = video.to_md5_hash()
        self.assertEqual(h1, h2)

    def test_save_to_file(self):
        video = Video(self.mp4_bytes)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'test_vid.mp4'
            result = video.save(path)
            self.assertTrue(Path(result).exists())
            self.assertTrue(Path(result).stat().st_size > 0)

    def test_load_idempotent(self):
        video = Video(self.mp4_bytes)
        _await(video.load())
        reader1 = video.reader
        _await(video.load())
        reader2 = video.reader
        self.assertIs(reader1, reader2)


# ═══════════════════════════════════════════════════════════════════════════
# FileID deferred loading tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFileIDDeferredLoading(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.png_bytes = _make_png_bytes()
        cls.wav_bytes = _make_wav_bytes()
        cls.mp4_bytes = _make_video_mp4_bytes(0.5)
        cls.pdf_bytes = _make_pdf_bytes()

    def _with_fileid_protocol(self, data: bytes):
        """Context manager that registers a memory storage protocol for 'unit-test'."""
        class _Ctx:
            def __enter__(ctx_self):
                ctx_self._orig = dict(FileID._protocols)
                FileID._protocols.clear()
                FileID.AddProtocol('unit-test', _MemoryFileStorage(data))
                return ctx_self

            def __exit__(ctx_self, *args):
                FileID._protocols.clear()
                FileID._protocols.update(ctx_self._orig)

        return _Ctx()

    def test_image_from_file_id_instance_lazy_load(self):
        with self._with_fileid_protocol(self.png_bytes):
            file_id = FileID(id='img-1', category='unit-test', type='image')
            img = Image(file_id)
            self.assertFalse(img._loaded)
            _await(img.load())
            self.assertTrue(img._loaded)
            self.assertEqual(img.size, (64, 64))

    def test_image_from_file_id_instance(self):
        with self._with_fileid_protocol(self.png_bytes):
            fid = FileID(id='img-2', category='unit-test', type='image')
            img = Image(fid)
            _await(img.load())
            self.assertTrue(img._loaded)
            self.assertEqual(img.size, (64, 64))

    def test_audio_from_file_id_instance_lazy_load(self):
        with self._with_fileid_protocol(self.wav_bytes):
            file_id = FileID(id='aud-1', category='unit-test', type='audio')
            audio = Audio(file_id)
            self.assertFalse(audio._loaded)
            _await(audio.load())
            self.assertTrue(audio._loaded)
            self.assertGreater(len(audio), 0)

    def test_audio_from_file_id_instance(self):
        with self._with_fileid_protocol(self.wav_bytes):
            fid = FileID(id='aud-2', category='unit-test', type='audio')
            audio = Audio(fid)
            _await(audio.load())
            self.assertTrue(audio._loaded)

    def test_video_from_file_id_instance_bytes_access(self):
        with self._with_fileid_protocol(self.mp4_bytes):
            file_id = FileID(id='vid-1', category='unit-test', type='video')
            video = Video(file_id)
            # Video resolves FileID eagerly in __init__ (not deferred)
            # So accessing to_bytes should work
            data = video.to_bytes()
            self.assertGreater(len(data), 0)

    def test_video_from_file_id_instance(self):
        with self._with_fileid_protocol(self.mp4_bytes):
            fid = FileID(id='vid-2', category='unit-test', type='video')
            video = Video(fid)
            dur = video.duration
            self.assertGreater(dur, 0)

    def test_document_from_file_id_instance(self):
        with self._with_fileid_protocol(b'hello from file id doc'):
            file_id = FileID(id='doc-1', category='unit-test', type='plaintext')
            doc = PlainText.Load(file_id)
            self.assertEqual(doc.to_bytes(), b'hello from file id doc')

    def test_document_pdf_from_file_id_instance(self):
        with self._with_fileid_protocol(self.pdf_bytes):
            file_id = FileID(id='pdf-1', category='unit-test', type='pdf')
            pdf = PDF.Load(file_id)
            self.assertEqual(pdf.to_bytes(), self.pdf_bytes)


# ═══════════════════════════════════════════════════════════════════════════
# AcceptableFileSource & loader tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAcceptableFileSource(TestCase):
    def test_is_acceptable_for_standard_types(self):
        self.assertTrue(is_acceptable_file_source(b'data'))
        self.assertTrue(is_acceptable_file_source('some/path'))
        self.assertTrue(is_acceptable_file_source(Path('some/path')))
        self.assertTrue(is_acceptable_file_source(BytesIO(b'data')))

    def test_is_not_acceptable_for_file_id_dict(self):
        self.assertFalse(is_acceptable_file_source({'id': 'abc', 'category': 'cache'}))

    def test_is_acceptable_for_file_id_instance(self):
        fid = FileID(id='abc', category='cache', type='plaintext')
        self.assertTrue(is_acceptable_file_source(fid))

    def test_save_get_file_source_bytes(self):
        result = _await(save_get_file_source(b'hello'))
        self.assertEqual(result.read(), b'hello')

    def test_save_get_file_source_from_path(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
            f.write(b'test file content')
            f.flush()
            path = Path(f.name)
        try:
            result = _await(save_get_file_source(path))
            self.assertEqual(result.read(), b'test file content')
        finally:
            path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# Document deferred / lazy loading tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDocumentDeferredLoading(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdf_bytes = _make_pdf_bytes()

    def test_pdf_lazy_bytes_cache(self):
        pdf = PDF.Load(self.pdf_bytes)
        # First access populates cache
        data = pdf.to_bytes()
        self.assertEqual(data, self.pdf_bytes)
        # Second access uses cache (same result)
        data2 = pdf.to_bytes()
        self.assertEqual(data, data2)

    def test_plaintext_load_from_bytes(self):
        pt = PlainText.Load(b'abc def')
        self.assertEqual(pt.to_bytes(), b'abc def')
        text = pt.source_text()
        self.assertEqual(text, 'abc def')

    def test_document_from_file_path(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='wb') as f:
            f.write(b'path-based doc')
            path = Path(f.name)
        try:
            pt = PlainText.Load(path)
            self.assertEqual(pt.to_bytes(), b'path-based doc')
        finally:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
