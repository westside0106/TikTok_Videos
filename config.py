from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import load_dotenv


@dataclass
class Config:
    telegram_bot_token: str
    whisper_model: str = "base"
    max_clips_per_video: int = 3
    clip_min_duration: int = 15
    clip_max_duration: int = 60
    output_dir: Path = Path("./output")
    temp_dir: Path = Path("./tmp")
    max_video_duration: int = 3600
    max_file_size_mb: int = 500
    whisper_beam_size: int = 5
    audio_energy_weight: float = 0.4
    keyword_weight: float = 0.3
    scene_change_weight: float = 0.3
    log_level: str = "INFO"
    tiktok_keywords: list = field(default_factory=lambda: [
        "wait", "listen", "actually", "insane", "crazy", "no way",
        "what", "omg", "wow", "legendary", "fail", "win", "sick",
        "bro", "literally", "shocking", "unbelievable", "secret",
        "wait for it", "you won't believe", "insane", "fire", "goat",
        "clutch", "let's go", "no", "yes", "really", "seriously",
        "warte", "krass", "unfassbar", "unmöglich", "ehrlich",
    ])


def load_config() -> Config:
    """Load and validate config from .env file. Raises on missing token."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is required. "
            "Copy .env.example to .env and add your bot token."
        )

    return Config(
        telegram_bot_token=token,
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        max_clips_per_video=int(os.getenv("MAX_CLIPS_PER_VIDEO", 3)),
        clip_min_duration=int(os.getenv("CLIP_MIN_DURATION", 15)),
        clip_max_duration=int(os.getenv("CLIP_MAX_DURATION", 60)),
        output_dir=Path(os.getenv("OUTPUT_DIR", "./output")),
        temp_dir=Path(os.getenv("TEMP_DIR", "./tmp")),
        max_video_duration=int(os.getenv("MAX_VIDEO_DURATION", 3600)),
        max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", 500)),
        whisper_beam_size=int(os.getenv("WHISPER_BEAM_SIZE", 5)),
        audio_energy_weight=float(os.getenv("AUDIO_ENERGY_WEIGHT", 0.4)),
        keyword_weight=float(os.getenv("KEYWORD_WEIGHT", 0.3)),
        scene_change_weight=float(os.getenv("SCENE_CHANGE_WEIGHT", 0.3)),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
