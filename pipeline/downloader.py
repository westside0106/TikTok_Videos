import logging
from pathlib import Path
from dataclasses import dataclass, field

import yt_dlp

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    title: str
    duration: float
    url: str
    platform: str
    video_path: Path
    audio_path: Path
    chapters: list = field(default_factory=list)


class DownloadError(Exception):
    """Raised when a download fails or the video exceeds limits."""
    def __init__(self, message: str, user_message: str = None):
        self.user_message = user_message or message
        super().__init__(message)


def get_platform(url: str) -> str:
    """Detect platform name from URL."""
    url_lower = url.lower()
    platforms = {
        "youtube.com": "YouTube",
        "youtu.be": "YouTube",
        "twitch.tv": "Twitch",
        "kick.com": "Kick",
        "tiktok.com": "TikTok",
        "instagram.com": "Instagram",
        "twitter.com": "Twitter/X",
        "x.com": "Twitter/X",
        "reddit.com": "Reddit",
        "facebook.com": "Facebook",
    }
    for domain, name in platforms.items():
        if domain in url_lower:
            return name
    return "Unknown"


def extract_chapters(info: dict) -> list:
    """Parse yt-dlp info dict for chapter markers."""
    chapters = info.get("chapters") or []
    result = []
    for ch in chapters:
        start = ch.get("start_time", 0)
        end = ch.get("end_time", 0)
        if end > start:
            result.append({
                "title": ch.get("title", ""),
                "start_time": float(start),
                "end_time": float(end),
            })
    return result


def _base_ydl_opts() -> dict:
    """Base yt-dlp options that bypass YouTube bot detection."""
    return {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/112.0.0.0 Mobile Safari/537.36"
            ),
        },
    }


def probe_video(url: str, max_duration: int) -> dict:
    """
    Probe URL metadata without downloading. Returns yt-dlp info dict.
    Raises DownloadError if URL is unsupported or duration exceeds limit.
    """
    ydl_opts = {
        **_base_ydl_opts(),
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise DownloadError(
                f"yt-dlp error: {e}",
                user_message="Could not access this video. It may be private, age-restricted, or from an unsupported platform.",
            )

    duration = info.get("duration") or 0
    if duration > max_duration:
        raise DownloadError(
            f"Video too long: {duration}s > {max_duration}s",
            user_message=f"Video is too long ({duration // 60} min). Maximum is {max_duration // 60} minutes.",
        )

    return info


def download_video(url: str, output_dir: Path, max_duration: int) -> VideoInfo:
    """
    Download video and extract audio separately using yt-dlp.
    Returns VideoInfo with paths to both files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Probe first to check duration and get metadata
    info = probe_video(url, max_duration)
    title = info.get("title", "video")
    platform = get_platform(url)
    chapters = extract_chapters(info)

    logger.info("Downloading '%s' from %s (%.0fs)", title, platform, info.get("duration", 0))

    video_tmpl = str(output_dir / "video.%(ext)s")
    audio_tmpl = str(output_dir / "audio.%(ext)s")

    # Download video (max 720p is sufficient since we output 1080x1920 portrait)
    video_opts = {
        **_base_ydl_opts(),
        "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "outtmpl": video_tmpl,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(video_opts) as ydl:
        try:
            ydl.download([url])
        except yt_dlp.utils.DownloadError as e:
            raise DownloadError(f"Download failed: {e}", user_message="Download failed. Please try again.")

    # Extract audio separately for Whisper (much smaller file)
    audio_opts = {
        **_base_ydl_opts(),
        "format": "bestaudio/best",
        "outtmpl": audio_tmpl,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
    }
    with yt_dlp.YoutubeDL(audio_opts) as ydl:
        try:
            ydl.download([url])
        except yt_dlp.utils.DownloadError as e:
            raise DownloadError(f"Audio extraction failed: {e}", user_message="Could not extract audio.")

    # Find the actual downloaded files
    video_path = _find_file(output_dir, "video")
    audio_path = _find_file(output_dir, "audio")

    if not video_path or not video_path.exists():
        raise DownloadError("Video file not found after download.", user_message="Download seems to have failed.")
    if not audio_path or not audio_path.exists():
        raise DownloadError("Audio file not found after extraction.", user_message="Audio extraction failed.")

    logger.info("Downloaded: video=%s audio=%s", video_path.name, audio_path.name)

    return VideoInfo(
        title=title,
        duration=float(info.get("duration", 0)),
        url=url,
        platform=platform,
        video_path=video_path,
        audio_path=audio_path,
        chapters=chapters,
    )


def _find_file(directory: Path, stem: str) -> Path | None:
    """Find a file in directory matching the given stem (any extension)."""
    for f in directory.iterdir():
        if f.stem == stem and f.is_file():
            return f
    return None
