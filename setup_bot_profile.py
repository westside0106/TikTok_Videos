"""
Telegram Bot Profile Setup
===========================
Run once to configure bot name, description, and slash commands via BotFather API.

Usage:
    python setup_bot_profile.py
"""
import sys
import urllib.request
import urllib.parse
import json
from config import load_config


def api_call(token: str, method: str, payload: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    config = load_config()
    token = config.telegram_bot_token

    # ── 1. Slash-Befehle ──────────────────────────────────────────────────────
    commands = [
        {"command": "start",      "description": "Bot starten & Begrüßung anzeigen"},
        {"command": "help",       "description": "Hilfe & unterstützte Plattformen"},
        {"command": "settings",   "description": "Aktuelle Einstellungen anzeigen"},
        {"command": "set_clips",  "description": "Anzahl Clips setzen, z.B. /set_clips 3 (1–5)"},
        {"command": "set_min",    "description": "Minimale Clip-Länge setzen, z.B. /set_min 15 (10–30 s)"},
        {"command": "set_max",    "description": "Maximale Clip-Länge setzen, z.B. /set_max 60 (30–60 s)"},
    ]
    r = api_call(token, "setMyCommands", {"commands": commands})
    print(f"setMyCommands       → {'✅ OK' if r.get('result') else '❌ ' + str(r)}")

    # ── 2. Kurzbeschreibung (erscheint in der Kontaktliste / Chat-Header) ──────
    short_desc = "Schick mir einen Video-Link oder eine Datei – ich erstelle TikTok-Clips mit Untertiteln."
    r = api_call(token, "setMyShortDescription", {"short_description": short_desc})
    print(f"setMyShortDescription → {'✅ OK' if r.get('result') else '❌ ' + str(r)}")

    # ── 3. Lange Beschreibung (erscheint im leeren Chat vor dem ersten Schreiben) ─
    description = (
        "🎬 TikTok Clip Generator\n\n"
        "Sende mir:\n"
        "• Einen Video-Link (YouTube, TikTok, Instagram, Twitch, Kick, Twitter/X, Reddit …)\n"
        "• Oder direkt eine Videodatei (max. 20 MB)\n\n"
        "Ich analysiere das Video automatisch mit KI, erkenne die besten Momente "
        "und erstelle daraus TikTok-fertige Clips (9:16 Hochformat, 15–60 Sek.) "
        "mit eingebrannten Untertiteln.\n\n"
        "Befehle:\n"
        "/settings – Einstellungen anzeigen\n"
        "/set_clips 3 – Anzahl Clips (1–5)\n"
        "/set_min 15 – Minimale Clip-Länge\n"
        "/set_max 60 – Maximale Clip-Länge"
    )
    r = api_call(token, "setMyDescription", {"description": description})
    print(f"setMyDescription    → {'✅ OK' if r.get('result') else '❌ ' + str(r)}")

    print("\nFertig! Starte einen neuen Chat mit dem Bot um die Änderungen zu sehen.")


if __name__ == "__main__":
    main()
