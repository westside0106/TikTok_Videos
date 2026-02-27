import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from utils.file_utils import seconds_to_ffmpeg_time, get_file_size_mb

logger = logging.getLogger(__name__)


@dataclass
class ClipResult:
    path: Path
    duration: float
    start_time: float
    end_time: float
    clip_index: int
    file_size_mb: float = 0.0


class VideoEditError(Exception):
    def __init__(self, message: str, stderr: str = "", user_message: str = None):
        self.stderr = stderr
        self.user_message = user_message or "Failed to create video clip."
        super().__init__(message)


def get_video_dimensions(video_path: Path) -> tuple:
    """
    Use ffprobe to get the display width and height of the video.
    Respects rotation metadata: mobile-shot videos (TikTok, Instagram, etc.)
    are often stored as landscape (e.g. 1920x1080) with a 90° or 270° rotate
    tag. We swap w/h in that case so the crop math works correctly.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,tags",
        "-of", "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if streams:
                w = int(streams[0].get("width", 1280))
                h = int(streams[0].get("height", 720))
                # Check the rotate tag (stored as a string like "90", "270", etc.)
                tags = streams[0].get("tags", {})
                rotate = int(tags.get("rotate", tags.get("Rotate", 0)))
                if rotate in (90, 270, -90, -270):
                    logger.debug("Swapping dimensions due to rotation=%d (%dx%d → %dx%d)",
                                 rotate, w, h, h, w)
                    w, h = h, w
                return w, h
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        logger.warning("ffprobe failed: %s", e)
    return 1280, 720  # fallback to common 720p


def calculate_crop_filter(
    src_w: int,
    src_h: int,
    target_w: int = 1080,
    target_h: int = 1920,
) -> str:
    """
    Build FFmpeg scale+crop filter to convert any aspect ratio to target 9:16.
    Strategy: scale up to fill target (zoom crop), then center-crop the excess.
    """
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        # Wider than target: scale by height, then crop width
        scale_h = target_h
        scale_w = int(src_w * target_h / src_h)
    else:
        # Taller or equal: scale by width, then crop height
        scale_w = target_w
        scale_h = int(src_h * target_w / src_w)

    # Center crop
    crop_x = (scale_w - target_w) // 2
    crop_y = (scale_h - target_h) // 2

    return f"scale={scale_w}:{scale_h},crop={target_w}:{target_h}:{crop_x}:{crop_y}"


def build_ffmpeg_command(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    start: float,
    end: float,
    crf: int = 23,
    target_w: int = 1080,
    target_h: int = 1920,
) -> list:
    """
    Build a single-pass FFmpeg command: cut + crop to 9:16 + burn subtitles.
    Uses fast seek (-ss before -i) for speed.
    """
    src_w, src_h = get_video_dimensions(video_path)
    crop_filter = calculate_crop_filter(src_w, src_h, target_w, target_h)

    # Escape ASS path for FFmpeg filter (handle Windows backslashes and colons)
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")

    vf = f"{crop_filter},ass='{ass_escaped}'"

    cmd = [
        "ffmpeg",
        "-y",                              # overwrite output
        "-ss", seconds_to_ffmpeg_time(start),
        "-to", seconds_to_ffmpeg_time(end),
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", str(crf),
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    return cmd


def process_clip(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    start: float,
    end: float,
    max_size_mb: float = 48.0,
) -> ClipResult:
    """
    Create a single clip: cut, crop to 9:16, burn subtitles.
    If the result is over max_size_mb, re-encode at lower quality (crf=28).
    """
    cmd = build_ffmpeg_command(video_path, ass_path, output_path, start, end, crf=23)
    logger.info("Creating clip %.1fs-%.1fs: %s", start, end, output_path.name)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.error("FFmpeg stderr: %s", result.stderr[-2000:])
        raise VideoEditError(
            f"FFmpeg failed with code {result.returncode}",
            stderr=result.stderr,
            user_message="Failed to create clip. The video may be corrupted.",
        )

    # Check file size; re-encode at lower quality if over limit
    size_mb = get_file_size_mb(output_path)
    if size_mb > max_size_mb:
        logger.warning("Clip %.1f MB > limit %.1f MB, re-encoding at lower quality", size_mb, max_size_mb)
        cmd_lq = build_ffmpeg_command(video_path, ass_path, output_path, start, end, crf=28)
        result = subprocess.run(cmd_lq, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise VideoEditError(
                "Low-quality re-encode failed",
                stderr=result.stderr,
                user_message="Failed to compress clip to fit Telegram's file limit.",
            )
        size_mb = get_file_size_mb(output_path)

    return ClipResult(
        path=output_path,
        duration=end - start,
        start_time=start,
        end_time=end,
        clip_index=0,
        file_size_mb=size_mb,
    )


def process_all_clips(
    video_path: Path,
    candidates: list,
    words: list,
    output_dir: Path,
    config,
) -> list:
    """
    Generate all clips from the list of ClipCandidates.
    Returns list of ClipResult for successfully created clips.
    """
    from pipeline.subtitle_styler import generate_ass_file

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, candidate in enumerate(candidates, start=1):
        clip_output = output_dir / f"clip_{i:02d}.mp4"
        ass_output = output_dir / f"clip_{i:02d}.ass"

        try:
            generate_ass_file(
                words=words,
                output_path=ass_output,
                clip_start=candidate.start,
                clip_end=candidate.end,
            )
            clip = process_clip(
                video_path=video_path,
                ass_path=ass_output,
                output_path=clip_output,
                start=candidate.start,
                end=candidate.end,
            )
            clip.clip_index = i
            results.append(clip)
            logger.info("Clip %d/%d done: %.1f MB", i, len(candidates), clip.file_size_mb)

        except (VideoEditError, Exception) as e:
            logger.error("Failed to create clip %d: %s", i, e)

    return results
