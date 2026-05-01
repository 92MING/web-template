import cv2
import math
import tempfile

from PIL import Image as PILImage
from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence, TypeAlias

from core.utils.data_structs import Audio, Image, Video
from core.utils.text_utils import word_count


def _infer_media_format(value: Audio | Video, *, source: object | None = None) -> str | None:
    '''从 source 路径或 _origin_format 推断媒体文件格式名（如 mp4, wav）。'''
    if source is None:
        source = getattr(value, 'source', None)
    if isinstance(source, Path):
        suffix = source.suffix.lower().lstrip('.')
        if suffix:
            return suffix
    if isinstance(source, str):
        suffix = Path(source.strip()).suffix.lower().lstrip('.')
        if suffix:
            return suffix
    origin = getattr(value, '_origin_format', None)
    if isinstance(origin, str) and origin:
        return origin.lower()
    return None

TokenCountable: TypeAlias = str | Image | Audio | Video | Mapping[str, "TokenCountable"] | Sequence["TokenCountable"]

_IMAGE_MIN_TOKENS = 256
_IMAGE_MAX_TOKENS = 4096
_IMAGE_MIN_PIXELS = 224 * 224
_IMAGE_MAX_PIXELS = 1024 * 1024


def estimate_text_tokens(text: str) -> int:
    return max(0, word_count(text))


def estimate_image_tokens(image: Image) -> int:
    try:
        width = int(image.width)
        height = int(image.height)
    except Exception:
        width = 0
        height = 0

    pixels = width * height
    if pixels <= 0:
        return _IMAGE_MIN_TOKENS
    if pixels <= _IMAGE_MIN_PIXELS:
        return _IMAGE_MIN_TOKENS
    if pixels >= _IMAGE_MAX_PIXELS:
        return _IMAGE_MAX_TOKENS

    ratio = (pixels - _IMAGE_MIN_PIXELS) / float(_IMAGE_MAX_PIXELS - _IMAGE_MIN_PIXELS)
    tokens = _IMAGE_MIN_TOKENS + ratio * (_IMAGE_MAX_TOKENS - _IMAGE_MIN_TOKENS)
    return max(_IMAGE_MIN_TOKENS, min(_IMAGE_MAX_TOKENS, int(round(tokens))))


def estimate_audio_tokens(audio: Audio) -> int:
    try:
        duration = len(audio) / 1000.0
    except Exception:
        duration = 0.0
    duration = max(1.0, duration)
    return int(math.ceil(duration * 12.0))


def estimate_video_tokens(video: Video) -> int:
    try:
        width = int(getattr(video, 'w', 0) or getattr(video, 'width', 0) or 0)
        height = int(getattr(video, 'h', 0) or getattr(video, 'height', 0) or 0)
        dur = getattr(video, 'duration', None)
        duration = float(dur) if dur else 0.0
        frame_count = int(getattr(video, 'n_frames', 0) or 0)
        if duration <= 0:
            fps = getattr(video, 'fps', None)
            if fps and frame_count:
                duration = float(frame_count) / float(fps)
    except Exception:
        width = 0
        height = 0
        duration = 0.0
        frame_count = 0

    frame_count = max(1, frame_count)
    frame_image_tokens = _IMAGE_MIN_TOKENS
    if width > 0 and height > 0:
        try:
            frame_image_tokens = estimate_image_tokens(Image(_blank_image_bytes(width, height)))
        except Exception:
            pixels = width * height
            if pixels > 0:
                if pixels <= _IMAGE_MIN_PIXELS:
                    frame_image_tokens = _IMAGE_MIN_TOKENS
                elif pixels >= _IMAGE_MAX_PIXELS:
                    frame_image_tokens = _IMAGE_MAX_TOKENS
                else:
                    ratio = (pixels - _IMAGE_MIN_PIXELS) / float(_IMAGE_MAX_PIXELS - _IMAGE_MIN_PIXELS)
                    frame_image_tokens = int(round(_IMAGE_MIN_TOKENS + ratio * (_IMAGE_MAX_TOKENS - _IMAGE_MIN_TOKENS)))

    audio_tokens = max(12, int(math.ceil(max(1.0, duration) * 12.0)))
    return max(1, int(math.ceil((frame_count * frame_image_tokens + audio_tokens) / 60.0)))


def estimate_multimodal_tokens(value: TokenCountable) -> int:
    if isinstance(value, str):
        return estimate_text_tokens(value)
    if isinstance(value, Image):
        return estimate_image_tokens(value)
    if isinstance(value, Audio):
        return estimate_audio_tokens(value)
    if isinstance(value, Video):
        return estimate_video_tokens(value)
    if isinstance(value, dict):
        total = 0
        role = value.get('role')
        if isinstance(role, str):
            total += estimate_text_tokens(role)
        if 'content' in value:
            total += estimate_multimodal_tokens(value['content'])
        else:
            for item in value.values():
                total += estimate_multimodal_tokens(item)
        return total
    if isinstance(value, Sequence):
        return sum(estimate_multimodal_tokens(item) for item in value)
    return estimate_text_tokens(str(value))

def compress_image_to_token_budget(image: Image, max_tokens: int) -> Image:
    if max_tokens >= estimate_image_tokens(image):
        return image
    try:
        from PIL import Image as PILImage
    except Exception:
        return image

    try:
        raw_bytes = image.to_bytes()
        with PILImage.open(BytesIO(raw_bytes)) as src:
            pil_img = src.convert('RGB')
            current_pixels = max(1, pil_img.width * pil_img.height)
            target_pixels = _pixels_for_image_tokens(max_tokens)
            ratio = min(1.0, math.sqrt(target_pixels / float(current_pixels)))
            if ratio < 1.0:
                resized = pil_img.resize(
                    (
                        max(1, int(round(pil_img.width * ratio))),
                        max(1, int(round(pil_img.height * ratio))),
                    ),
                    PILImage.Resampling.LANCZOS,
                )
            else:
                resized = pil_img

            for quality in (88, 80, 72, 64):
                buf = BytesIO()
                resized.save(buf, format='JPEG', quality=quality, optimize=True)
                candidate = Image(buf.getvalue())
                if estimate_image_tokens(candidate) <= max_tokens or quality == 64:
                    return candidate
    except Exception:
        return image
    return image


def split_audio_on_silence(audio: Audio, *, target_max_tokens: int | None = None) -> list[Audio]:
    '''Split audio on silence using Audio.split_on_silence, then merge segments shorter than
    1 second with the shorter of their two neighbors.'''
    _MIN_SEGMENT_MS = 1000  # minimum segment length: 1 second

    def _fallback_target_ms() -> int:
        if target_max_tokens and target_max_tokens > 0:
            return max(_MIN_SEGMENT_MS, int((target_max_tokens / 12.0) * 1000))
        return 30000

    def _split_by_budget_windows(source: Audio) -> list[Audio]:
        try:
            total_ms = len(source)
        except Exception:
            try:
                source = Audio(source.to_bytes())
                total_ms = len(source)
            except Exception:
                return [source]
        if total_ms <= 0:
            return [source]
        target_ms = _fallback_target_ms()
        return [source[start:start + target_ms] for start in range(0, total_ms, target_ms)] # type: ignore

    def _materialize_audio(source: Audio) -> Audio:
        try:
            len(source)
            return source
        except Exception:
            try:
                return Audio(source.to_bytes())
            except Exception:
                return source

    # Use the Audio class's own split_on_silence method (wraps pydub, no need to reinvent)
    try:
        raw_parts: list[Audio] = audio.split_on_silence()
    except Exception:
        raw_parts = []
    else:
        materialized_parts: list[Audio] = []
        for part in raw_parts:
            materialized_parts.append(_materialize_audio(part))
        raw_parts = materialized_parts

    needs_budget_fallback = bool(
        target_max_tokens
        and target_max_tokens > 0
        and estimate_audio_tokens(audio) > target_max_tokens
        and len(raw_parts) <= 1
    )

    if not raw_parts or needs_budget_fallback:
        # Fallback: split by fixed duration windows
        raw_parts = _split_by_budget_windows(audio)

    if not raw_parts:
        return [audio]

    # Merge segments that are too short into their shorter neighbor
    merged: list[Audio] = [_materialize_audio(part) for part in raw_parts]
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(merged):
            merged[i] = _materialize_audio(merged[i])
            seg_len = len(merged[i])
            if seg_len > 0 and seg_len < _MIN_SEGMENT_MS and len(merged) > 1:
                prev_len = len(_materialize_audio(merged[i - 1])) if i > 0 else None
                next_len = len(_materialize_audio(merged[i + 1])) if i < len(merged) - 1 else None
                # Pick the shorter neighbor (prefer previous on tie)
                if prev_len is None:
                    merge_idx = i + 1
                elif next_len is None:
                    merge_idx = i - 1
                elif prev_len <= next_len:
                    merge_idx = i - 1
                else:
                    merge_idx = i + 1
                try:
                    if merge_idx < i:
                        # Append current segment to the end of previous
                        merged[merge_idx] = _materialize_audio(merged[merge_idx]).append(_materialize_audio(merged[i]), crossfade=0)
                        merged.pop(i)
                    else:
                        # Prepend current segment before the next
                        merged[merge_idx] = _materialize_audio(merged[i]).append(_materialize_audio(merged[merge_idx]), crossfade=0)
                        merged.pop(i)
                        # After removing i, the merged result is now at position i; don't advance
                    changed = True
                    continue
                except Exception:
                    pass  # keep as-is if merge fails
            i += 1

    if target_max_tokens and target_max_tokens > 0:
        budget_split_parts: list[Audio] = []
        for part in merged:
            if estimate_audio_tokens(part) > target_max_tokens:
                budget_split_parts.extend(_split_by_budget_windows(part))
            else:
                budget_split_parts.append(part)
        merged = budget_split_parts

    return merged if merged else [audio]


def trim_audio_to_token_budget(audio: Audio, max_tokens: int, *, preserve_tail: bool = True) -> Audio:
    if max_tokens <= 0:
        return audio
    if estimate_audio_tokens(audio) <= max_tokens:
        return audio

    try:
        from pydub import AudioSegment
    except Exception:
        return audio

    try:
        raw_bytes = audio.to_bytes()
        audio_format = _infer_media_format(audio)
        segment = AudioSegment.from_file(BytesIO(raw_bytes), format=audio_format or None)
    except Exception:
        return audio

    total_ms = len(segment)
    if total_ms <= 0:
        return audio

    target_ms = max(1000, int(math.floor((max_tokens / 12.0) * 1000.0)))
    if target_ms >= total_ms:
        return audio

    clipped = segment[-target_ms:] if preserve_tail else segment[:target_ms]
    if len(clipped) <= 0:
        return audio

    try:
        buf = BytesIO()
        clipped.export(buf, format='wav')
        candidate = Audio(buf.getvalue())
        if not isinstance(candidate, Audio):
            return audio
        return candidate if estimate_audio_tokens(candidate) <= estimate_audio_tokens(audio) else audio
    except Exception:
        return audio


def split_video_to_token_budget(video: Video, target_max_tokens: int) -> list[Video]:
    if target_max_tokens <= 0:
        return [video]

    total_tokens = estimate_video_tokens(video)
    if total_tokens <= target_max_tokens:
        return [video]

    try:
        import cv2  # type: ignore
    except Exception:
        return [video]

    video_format = _infer_media_format(video) or 'mp4'
    fps_val = getattr(video, 'fps', None)
    fps = float(fps_val) if fps_val else 0.0
    frame_count = int(getattr(video, 'n_frames', 0) or 0)
    dur = getattr(video, 'duration', None)
    duration_seconds = float(dur) if dur else (frame_count / fps if fps > 0 else 0.0)
    if duration_seconds <= 0 or fps <= 0 or frame_count <= 0:
        return [video]

    target_seconds = max(1.0 / fps, duration_seconds * (float(target_max_tokens) / float(total_tokens)))
    target_frames = max(1, int(math.floor(target_seconds * fps)))
    if target_frames >= frame_count:
        return [video]

    return _split_video_by_frames(video, target_frames)


def trim_video_to_token_budget(video: Video, max_tokens: int, *, preserve_tail: bool = True) -> Video:
    if max_tokens <= 0:
        return video
    if estimate_video_tokens(video) <= max_tokens:
        return video

    budget_with_margin = max(1, int(max_tokens) - 2)

    video_format = _infer_media_format(video) or 'mp4'
    raw_bytes = video.to_bytes()
    read_suffix = f'.{video_format}' if video_format else '.mp4'
    write_suffix = read_suffix if read_suffix in {'.mp4', '.avi', '.mov', '.mkv', '.webm'} else '.mp4'
    tmp_in: Path | None = None
    tmp_out: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=read_suffix) as src_file:
            src_file.write(raw_bytes)
            tmp_in = Path(src_file.name)

        capture = cv2.VideoCapture(str(tmp_in))
        try:
            if not capture.isOpened():
                return video

            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
                return video

            duration_seconds = frame_count / fps
            target_seconds = max(1.0 / fps, duration_seconds * (float(budget_with_margin) / float(max(1, estimate_video_tokens(video)))))
            keep_frame_count = frame_count
            if target_seconds < duration_seconds:
                keep_frame_count = max(1, int(math.floor(target_seconds * fps)))

            frame_image_tokens = _IMAGE_MIN_TOKENS
            current_pixels = max(1, width * height)
            if current_pixels > _IMAGE_MIN_PIXELS:
                if current_pixels >= _IMAGE_MAX_PIXELS:
                    frame_image_tokens = _IMAGE_MAX_TOKENS
                else:
                    ratio = (current_pixels - _IMAGE_MIN_PIXELS) / float(_IMAGE_MAX_PIXELS - _IMAGE_MIN_PIXELS)
                    frame_image_tokens = int(round(_IMAGE_MIN_TOKENS + ratio * (_IMAGE_MAX_TOKENS - _IMAGE_MIN_TOKENS)))

            kept_duration_seconds = max(1.0 / fps, keep_frame_count / fps)
            audio_tokens = max(12, int(math.ceil(max(1.0, kept_duration_seconds) * 12.0)))
            max_frame_budget = max(1, int(budget_with_margin * 60.0) - audio_tokens)
            max_keep_frames = max(1, int(math.floor(max_frame_budget / float(max(1, frame_image_tokens)))))
            keep_frame_count = min(keep_frame_count, max_keep_frames)

            start_frame = max(0, frame_count - keep_frame_count) if preserve_tail else 0
            end_frame = min(frame_count, start_frame + keep_frame_count)

            kept_duration_seconds = max(1.0 / fps, keep_frame_count / fps)
            audio_tokens = max(12, int(math.ceil(max(1.0, kept_duration_seconds) * 12.0)))
            target_frame_tokens = max(1, int(math.floor(max(1, int(budget_with_margin * 60.0) - audio_tokens) / float(keep_frame_count))))
            target_frame_tokens = min(_IMAGE_MAX_TOKENS, max(_IMAGE_MIN_TOKENS, target_frame_tokens))
            target_pixels = _pixels_for_image_tokens(target_frame_tokens)
            resize_ratio = min(1.0, math.sqrt(target_pixels / float(current_pixels)))
            out_width = max(1, int(round(width * resize_ratio)))
            out_height = max(1, int(round(height * resize_ratio)))
            if out_width % 2 != 0:
                out_width = max(2, out_width - 1)
            if out_height % 2 != 0:
                out_height = max(2, out_height - 1)

            fourcc_code = _video_writer_fourcc(write_suffix)
            with tempfile.NamedTemporaryFile(delete=False, suffix=write_suffix) as out_file:
                tmp_out = Path(out_file.name)

            writer = cv2.VideoWriter(
                str(tmp_out),
                fourcc_code,
                fps,
                (out_width, out_height),
            )
            if not writer.isOpened():
                return video

            try:
                capture.set(cv2.CAP_PROP_POS_FRAMES, float(start_frame))
                frame_idx = start_frame
                while frame_idx < end_frame:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    if frame.shape[1] != out_width or frame.shape[0] != out_height:
                        frame = cv2.resize(frame, (out_width, out_height), interpolation=cv2.INTER_AREA)
                    writer.write(frame)
                    frame_idx += 1
            finally:
                writer.release()

            if tmp_out is None or not tmp_out.exists() or tmp_out.stat().st_size <= 0:
                return video
            candidate = Video(tmp_out.read_bytes())
            if not isinstance(candidate, Video):
                return video
            candidate_tokens = estimate_video_tokens(candidate)
            original_tokens = estimate_video_tokens(video)
            if candidate_tokens <= max_tokens:
                return candidate
            if candidate_tokens < original_tokens:
                return trim_video_to_token_budget(candidate, max_tokens, preserve_tail=preserve_tail)
            return video
        finally:
            capture.release()
    except Exception:
        return video
    finally:
        for path in (tmp_in, tmp_out):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    ...

def _video_writer_fourcc(suffix: str) -> int:
    normalized = suffix.lower()
    if normalized in {'.avi'}:
        return cv2.VideoWriter_fourcc(*'XVID')  # type: ignore[attr-defined]
    return cv2.VideoWriter_fourcc(*'mp4v')  # type: ignore[attr-defined]

def _split_video_by_frames(video: Video, target_frames: int) -> list[Video]:
    try:
        import cv2  # type: ignore
    except Exception:
        return [video]

    video_format = _infer_media_format(video) or 'mp4'
    read_suffix = f'.{video_format}' if video_format else '.mp4'
    write_suffix = read_suffix if read_suffix in {'.mp4', '.avi', '.mov', '.mkv', '.webm'} else '.mp4'
    tmp_in: Path | None = None
    tmp_files: list[Path] = []
    segments: list[Video] = []

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=read_suffix) as src_file:
            src_file.write(video.to_bytes())
            tmp_in = Path(src_file.name)

        capture = cv2.VideoCapture(str(tmp_in))
        try:
            if not capture.isOpened():
                return [video]
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if fps <= 0 or width <= 0 or height <= 0:
                return [video]

            frame_idx = 0
            current_writer = None
            current_path: Path | None = None

            try:
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    if frame_idx % target_frames == 0:
                        if current_writer is not None:
                            current_writer.release()
                            current_writer = None
                            if current_path is not None and current_path.exists() and current_path.stat().st_size > 0:
                                tmp_files.append(current_path)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=write_suffix) as out_file:
                            current_path = Path(out_file.name)
                        current_writer = cv2.VideoWriter(
                            str(current_path),
                            _video_writer_fourcc(write_suffix),
                            fps,
                            (width, height),
                        )
                        if not current_writer.isOpened():
                            return [video]
                    if current_writer is not None:
                        current_writer.write(frame)
                    frame_idx += 1
            finally:
                if current_writer is not None:
                    current_writer.release()
                    if current_path is not None and current_path.exists() and current_path.stat().st_size > 0:
                        tmp_files.append(current_path)
        finally:
            capture.release()

        for path in tmp_files:
            candidate = Video(path.read_bytes())
            if isinstance(candidate, Video):
                segments.append(candidate)
        return segments or [video]
    except Exception:
        return [video]
    finally:
        if tmp_in is not None:
            try:
                tmp_in.unlink(missing_ok=True)
            except Exception:
                ...
        for path in tmp_files:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                ...


def _pixels_for_image_tokens(tokens: int) -> int:
    clamped = max(_IMAGE_MIN_TOKENS, min(_IMAGE_MAX_TOKENS, int(tokens)))
    if clamped <= _IMAGE_MIN_TOKENS:
        return _IMAGE_MIN_PIXELS
    if clamped >= _IMAGE_MAX_TOKENS:
        return _IMAGE_MAX_PIXELS
    ratio = (clamped - _IMAGE_MIN_TOKENS) / float(_IMAGE_MAX_TOKENS - _IMAGE_MIN_TOKENS)
    return int(round(_IMAGE_MIN_PIXELS + ratio * (_IMAGE_MAX_PIXELS - _IMAGE_MIN_PIXELS)))


def _blank_image_bytes(width: int, height: int) -> bytes:
    buf = BytesIO()
    PILImage.new('RGB', (max(1, width), max(1, height)), color=(255, 255, 255)).save(buf, format='PNG')
    return buf.getvalue()


__all__ = [
    'TokenCountable',
    'estimate_text_tokens',
    'estimate_image_tokens',
    'estimate_audio_tokens',
    'estimate_video_tokens',
    'estimate_multimodal_tokens',
    'compress_image_to_token_budget',
    'split_audio_on_silence',
    'split_video_to_token_budget',
    'trim_audio_to_token_budget',
    'trim_video_to_token_budget',
]
