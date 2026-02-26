import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_whisper_model = None


@dataclass
class WordSegment:
    word: str
    start: float
    end: float
    probability: float = 1.0


@dataclass
class TranscriptResult:
    words: list
    language: str
    full_text: str


class TranscriptionError(Exception):
    def __init__(self, message: str, user_message: str = None):
        self.user_message = user_message or "Transcription failed."
        super().__init__(message)


def load_whisper_model(model_size: str = "base"):
    """
    Load faster-whisper model (singleton, cached for the bot's lifetime).
    Uses int8 quantization for CPU efficiency.
    """
    global _whisper_model
    if _whisper_model is None:
        logger.info("Loading Whisper model '%s' (this may take a moment)...", model_size)
        try:
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
            )
            logger.info("Whisper model '%s' loaded successfully.", model_size)
        except Exception as e:
            raise TranscriptionError(f"Failed to load Whisper model: {e}")
    return _whisper_model


def transcribe_audio(audio_path: Path, model, beam_size: int = 5) -> TranscriptResult:
    """
    Transcribe audio file with word-level timestamps.
    Returns TranscriptResult with flat list of WordSegments.
    """
    if not audio_path.exists():
        raise TranscriptionError(
            f"Audio file not found: {audio_path}",
            user_message="Audio file missing. Download may have failed.",
        )

    file_size = audio_path.stat().st_size
    if file_size < 1000:
        raise TranscriptionError(
            "Audio file too small (likely empty).",
            user_message="Could not extract audio from this video.",
        )

    logger.info("Transcribing %s (%.1f MB)...", audio_path.name, file_size / 1024 / 1024)

    try:
        segments, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            beam_size=beam_size,
            vad_filter=True,          # skip silence
            vad_parameters={"min_silence_duration_ms": 500},
        )
    except Exception as e:
        raise TranscriptionError(
            f"Whisper transcription error: {e}",
            user_message="Transcription failed. The audio may be too noisy or silent.",
        )

    words = []
    full_text_parts = []

    for segment in segments:
        if segment.words:
            for word in segment.words:
                words.append(WordSegment(
                    word=word.word,
                    start=word.start,
                    end=word.end,
                    probability=word.probability,
                ))
        full_text_parts.append(segment.text.strip())

    if not words:
        raise TranscriptionError(
            "No words transcribed.",
            user_message="No speech detected in this video. Is there audio?",
        )

    logger.info(
        "Transcribed %d words, language: %s (confidence: %.2f)",
        len(words),
        info.language,
        info.language_probability,
    )

    return TranscriptResult(
        words=words,
        language=info.language,
        full_text=" ".join(full_text_parts),
    )
