# TikTok Video Clip Generator

Automatically cut the best moments from any video, add TikTok-style subtitles, and receive the clips via Telegram.

## Features

- **Telegram Bot interface** – send a URL from your phone, get clips back
- **All major platforms** – YouTube, TikTok, Instagram, Twitch, Kick, Twitter/X, Reddit, and [many more](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) via yt-dlp
- **Smart highlight detection** using 3 signals:
  - Audio energy peaks (loud = exciting)
  - Keyword density in transcript ("insane", "wait for it", etc.)
  - Scene changes
  - YouTube chapter markers (when available)
- **TikTok-style subtitles** – large bold font, black outline, word-by-word yellow highlighting
- **9:16 portrait format** – ready to post, zoom-cropped from any source aspect ratio
- **Configurable per user** – adjust clip count, min/max duration via bot commands

## Setup

### 1. Install system dependencies

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y ffmpeg

# macOS
brew install ffmpeg
```

### 2. Install Python dependencies

```bash
# Python 3.10+ required
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Create a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy your bot token

### 4. Configure

```bash
cp .env.example .env
# Edit .env and paste your TELEGRAM_BOT_TOKEN
```

### 5. Run

```bash
python bot.py
```

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and usage |
| `/help` | Supported platforms and processing info |
| `/settings` | View your current settings |
| `/set_clips 3` | Set number of clips per video (1-5) |
| `/set_min 15` | Set minimum clip length in seconds (10-30) |
| `/set_max 60` | Set maximum clip length in seconds (30-60) |

## Usage Example

```
You:  https://youtu.be/xxxxx
Bot:  ⬇️ Downloading video...
Bot:  🎙️ Transcribing audio...
Bot:  🔍 Detecting best moments...
Bot:  ✂️ Creating 3 clips...
Bot:  ✅ Done in 2:14! Sending 3 clips...
Bot:  [Clip 1/3 | 0:47 | High energy moment]
Bot:  [Clip 2/3 | 0:32 | keyword]
Bot:  [Clip 3/3 | 1:00 | scene change]
```

## Project Structure

```
TikTok_Videos/
├── bot.py                      # Telegram Bot entry point
├── config.py                   # Configuration loader
├── pipeline/
│   ├── downloader.py           # yt-dlp wrapper
│   ├── transcriber.py          # faster-whisper wrapper
│   ├── highlight_detector.py   # Multi-signal clip detection
│   ├── subtitle_styler.py      # ASS subtitle generator (TikTok style)
│   └── video_editor.py         # FFmpeg clip cutter
├── utils/
│   └── file_utils.py           # Shared helpers
├── requirements.txt
├── .env.example                # Config template (copy to .env)
└── README.md
```

## Processing Times (approximate, CPU-only)

| Video Length | Processing Time |
|---|---|
| 10 minutes | ~2-3 min |
| 30 minutes | ~5-7 min |
| 1 hour | ~10-15 min |

## Security Notes

- Never commit your `.env` file (it's in `.gitignore`)
- The bot only processes URLs sent to it – no scraping
- Temporary files are cleaned up automatically after each job
