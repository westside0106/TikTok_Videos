import uuid
import logging
import shutil
import re
from pathlib import Path
from contextlib import contextmanager


logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the whole application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS subtitle time format: H:MM:SS.cs"""
    cs = int((seconds % 1) * 100)
    s = int(seconds)
    m = s // 60
    s = s % 60
    h = m // 60
    m = m % 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def seconds_to_ffmpeg_time(seconds: float) -> str:
    """Convert seconds to FFmpeg -ss/-to format: HH:MM:SS.mmm"""
    ms = int((seconds % 1) * 1000)
    s = int(seconds)
    m = s // 60
    s = s % 60
    h = m // 60
    m = m % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


@contextmanager
def temp_working_dir(base: Path):
    """Create a UUID-named temp subdirectory, yield it, delete on exit."""
    job_dir = base / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield job_dir
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.debug("Cleaned up temp dir: %s", job_dir)


def sanitize_filename(name: str, max_len: int = 60) -> str:
    """Strip unsafe characters from a string for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = name.strip(". ")
    return name[:max_len] if name else "video"


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration: 1:32 or 12:05"""
    s = int(seconds)
    m = s // 60
    s = s % 60
    h = m // 60
    m = m % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def check_disk_space(path: Path, min_gb: float = 2.0) -> bool:
    """Return True if at least min_gb GB of free space is available."""
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024 ** 3)
    if free_gb < min_gb:
        logger.warning("Low disk space: %.1f GB free (min: %.1f GB)", free_gb, min_gb)
        return False
    return True


def get_file_size_mb(path: Path) -> float:
    """Return file size in megabytes."""
    return path.stat().st_size / (1024 * 1024)
