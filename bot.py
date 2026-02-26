"""
TikTok Video Clip Generator - Telegram Bot
==========================================
Send any video URL, get TikTok-ready clips with burned-in subtitles back.

Usage:
  1. Copy .env.example to .env and add your TELEGRAM_BOT_TOKEN
  2. Run: python bot.py
"""
import asyncio
import logging
import re
import time
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError

from config import load_config, Config
from pipeline.downloader import download_video, DownloadError
from pipeline.transcriber import load_whisper_model, transcribe_audio, TranscriptionError
from pipeline.highlight_detector import find_highlights, NoHighlightsError
from pipeline.video_editor import process_all_clips
from utils.file_utils import setup_logging, temp_working_dir, format_duration

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_config(context: ContextTypes.DEFAULT_TYPE, base: Config) -> Config:
    """Merge global config with per-user overrides stored in context.user_data."""
    from dataclasses import replace
    ud = context.user_data or {}
    overrides = {}
    if "max_clips" in ud:
        overrides["max_clips_per_video"] = ud["max_clips"]
    if "clip_min" in ud:
        overrides["clip_min_duration"] = ud["clip_min"]
    if "clip_max" in ud:
        overrides["clip_max_duration"] = ud["clip_max"]
    return replace(base, **overrides) if overrides else base


async def _edit_status(msg, text: str) -> None:
    """Edit a status message, ignoring errors if the text hasn't changed."""
    try:
        await msg.edit_text(text)
    except TelegramError:
        pass


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎬 *TikTok Clip Generator*\n\n"
        "Schick mir einen Video-Link von YouTube, TikTok, Instagram, Twitch, Kick oder "
        "einer anderen unterstützten Plattform.\n\n"
        "Ich finde automatisch die besten Momente und erstelle TikTok-fertige Clips "
        "mit eingebrannten Untertiteln (9:16, 15-60 Sekunden).\n\n"
        "*/help* – Hilfe und unterstützte Plattformen\n"
        "*/settings* – Einstellungen anzeigen\n"
        "*/set\\_clips 3* – Anzahl der Clips ändern (1-5)\n"
        "*/set\\_min 15* – Minimale Clip-Länge in Sekunden\n"
        "*/set\\_max 60* – Maximale Clip-Länge in Sekunden",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *Hilfe*\n\n"
        "*Unterstützte Plattformen:*\n"
        "YouTube, TikTok, Instagram, Twitter/X, Twitch, Kick, Reddit, Facebook "
        "und viele mehr (yt-dlp)\n\n"
        "*Wie es funktioniert:*\n"
        "1. Video herunterladen\n"
        "2. Audio transkribieren (Whisper KI)\n"
        "3. Beste Momente erkennen (Audio-Energie + Keywords)\n"
        "4. Clips schneiden + Untertitel einbrennen\n"
        "5. Clips zurückschicken\n\n"
        "*Verarbeitungszeit:*\n"
        "• 10 Min Video → ~2-3 Min\n"
        "• 1 Std Video → ~10-15 Min\n\n"
        "*Limits:*\n"
        "• Max. Video-Länge: 1 Stunde\n"
        "• Max. Dateigröße: 50 MB pro Clip\n\n"
        "Einfach Video-Link schicken und warten! 🚀",
        parse_mode="Markdown",
    )


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.application.bot_data["config"]
    effective = _get_user_config(context, config)
    ud = context.user_data or {}

    await update.message.reply_text(
        "⚙️ *Deine Einstellungen*\n\n"
        f"Clips pro Video: *{effective.max_clips_per_video}* "
        f"{'(angepasst)' if 'max_clips' in ud else '(Standard)'}\n"
        f"Min. Clip-Länge: *{effective.clip_min_duration}s* "
        f"{'(angepasst)' if 'clip_min' in ud else '(Standard)'}\n"
        f"Max. Clip-Länge: *{effective.clip_max_duration}s* "
        f"{'(angepasst)' if 'clip_max' in ud else '(Standard)'}\n"
        f"Whisper-Modell: *{effective.whisper_model}*\n\n"
        "Ändern mit:\n"
        "• /set\\_clips 3 (1-5)\n"
        "• /set\\_min 20 (10-30)\n"
        "• /set\\_max 45 (30-60)",
        parse_mode="Markdown",
    )


async def cmd_set_clips(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        n = int(context.args[0])
        if not 1 <= n <= 5:
            raise ValueError
        context.user_data["max_clips"] = n
        await update.message.reply_text(f"✅ Clips pro Video auf {n} gesetzt.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Nutzung: /set_clips 3  (Wert: 1-5)")


async def cmd_set_min(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        s = int(context.args[0])
        if not 10 <= s <= 30:
            raise ValueError
        context.user_data["clip_min"] = s
        await update.message.reply_text(f"✅ Minimale Clip-Länge auf {s}s gesetzt.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Nutzung: /set_min 15  (Wert: 10-30)")


async def cmd_set_max(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        s = int(context.args[0])
        if not 30 <= s <= 60:
            raise ValueError
        context.user_data["clip_max"] = s
        await update.message.reply_text(f"✅ Maximale Clip-Länge auf {s}s gesetzt.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Nutzung: /set_max 60  (Wert: 30-60)")


# ---------------------------------------------------------------------------
# Main URL Handler
# ---------------------------------------------------------------------------

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a video URL: download, transcribe, detect highlights, create clips."""
    url_match = URL_PATTERN.search(update.message.text)
    if not url_match:
        return

    url = url_match.group(0)
    config = context.application.bot_data["config"]
    if "whisper_model" not in context.application.bot_data:
        context.application.bot_data["whisper_model"] = load_whisper_model(config.whisper_model)
    whisper_model = context.application.bot_data["whisper_model"]
    effective_config = _get_user_config(context, config)

    status_msg = await update.message.reply_text("⏳ Verarbeite dein Video...")
    t_start = time.monotonic()

    try:
        with temp_working_dir(effective_config.temp_dir) as job_dir:

            # 1. Download
            await _edit_status(status_msg, "⬇️ Lade Video herunter...")
            video_info = await asyncio.to_thread(
                download_video, url, job_dir, effective_config.max_video_duration
            )
            title_short = video_info.title[:40] + "..." if len(video_info.title) > 40 else video_info.title
            await _edit_status(
                status_msg,
                f"🎙️ Transkribiere Audio...\n_{title_short}_\n"
                f"Dauer: {format_duration(video_info.duration)} • Plattform: {video_info.platform}",
            )

            # 2. Transcribe
            transcript = await asyncio.to_thread(
                transcribe_audio,
                video_info.audio_path,
                whisper_model,
                effective_config.whisper_beam_size,
            )

            # 3. Detect highlights
            await _edit_status(status_msg, "🔍 Erkenne beste Momente...")
            candidates = await asyncio.to_thread(
                find_highlights,
                video_info.audio_path,
                video_info.video_path,
                transcript.words,
                video_info.chapters,
                effective_config,
            )

            # 4. Create clips
            n = len(candidates)
            await _edit_status(status_msg, f"✂️ Erstelle {n} Clip{'s' if n != 1 else ''}...")
            output_dir = effective_config.output_dir / job_dir.name
            clips = await asyncio.to_thread(
                process_all_clips,
                video_info.video_path,
                candidates,
                transcript.words,
                output_dir,
                effective_config,
            )

            # 5. Send clips
            if not clips:
                await _edit_status(status_msg, "⚠️ Keine Clips erstellt. Bitte versuch's mit einem anderen Video.")
                return

            elapsed = time.monotonic() - t_start
            await _edit_status(
                status_msg,
                f"✅ Fertig in {format_duration(elapsed)}! Schicke {len(clips)} Clip(s)...",
            )

            for clip in clips:
                candidate = candidates[clip.clip_index - 1]
                caption = (
                    f"🎬 Clip {clip.clip_index}/{len(clips)} "
                    f"| {format_duration(clip.duration)} "
                    f"| 📍 {format_duration(clip.start_time)}"
                    f"\n💡 {candidate.reason}"
                )
                with open(clip.path, "rb") as f:
                    await update.message.reply_video(
                        video=f,
                        caption=caption,
                        supports_streaming=True,
                    )

    except DownloadError as e:
        logger.warning("Download error for %s: %s", url, e)
        await _edit_status(status_msg, f"❌ Download-Fehler:\n{e.user_message}")
    except TranscriptionError as e:
        logger.warning("Transcription error: %s", e)
        await _edit_status(status_msg, f"❌ Transkriptions-Fehler:\n{e.user_message}")
    except NoHighlightsError as e:
        logger.warning("No highlights: %s", e)
        await _edit_status(status_msg, f"⚠️ {e.user_message}")
    except Exception as e:
        logger.exception("Unexpected error processing %s", url)
        await _edit_status(
            status_msg,
            "❌ Unerwarteter Fehler. Bitte versuch's noch einmal.\n"
            "Wenn das Problem weiterhin besteht, versuch ein anderes Video.",
        )


async def handle_non_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text that isn't a URL."""
    await update.message.reply_text(
        "Schick mir bitte einen Video-Link. Tippe /help für Beispiele."
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler."""
    logger.error("Unhandled exception", exc_info=context.error)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    # Ensure directories exist
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.temp_dir.mkdir(parents=True, exist_ok=True)

    app = Application.builder().token(config.telegram_bot_token).build()

    # Store shared state (whisper model loaded lazily on first use)
    app.bot_data["config"] = config

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("set_clips", cmd_set_clips))
    app.add_handler(CommandHandler("set_min", cmd_set_min))
    app.add_handler(CommandHandler("set_max", cmd_set_max))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(URL_PATTERN), handle_url))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_non_url))
    app.add_error_handler(error_handler)

    logger.info("Bot started. Waiting for messages...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
