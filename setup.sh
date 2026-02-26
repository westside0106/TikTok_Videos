#!/usr/bin/env bash
# =============================================================
# TikTok Video Clip Generator – Server Setup Script
# Ubuntu 22.04 / 24.04  |  Run as root
# Usage:  bash setup.sh
# =============================================================
set -euo pipefail

REPO_URL="https://github.com/westside0106/TikTok_Videos.git"
APP_DIR="/opt/tiktok-bot"
SERVICE_NAME="tiktok-bot"
PYTHON_MIN="3.10"

# ── colours ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERR]${NC}   $*"; exit 1; }

# ── 1. System update + packages ──────────────────────────────
info "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

info "Installing ffmpeg, git, python3..."
apt-get install -y -qq ffmpeg git python3 python3-pip python3-venv curl

# Verify ffmpeg
ffmpeg -version 2>&1 | head -1 && info "ffmpeg OK" || error "ffmpeg install failed"

# ── 2. Clone / update repo ───────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    info "Repo already exists – pulling latest..."
    git -C "$APP_DIR" pull origin main
else
    info "Cloning repository to $APP_DIR..."
    git clone "$REPO_URL" "$APP_DIR"
fi

# ── 3. Python virtual environment ────────────────────────────
info "Setting up Python virtual environment..."
python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"

info "Installing Python dependencies (this may take a few minutes)..."
pip install --upgrade pip -q
pip install -r "$APP_DIR/requirements.txt"

deactivate

# ── 4. .env configuration ────────────────────────────────────
ENV_FILE="$APP_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    warn ".env already exists – skipping (delete it manually to reconfigure)"
else
    info "Creating .env from template..."
    cp "$APP_DIR/.env.example" "$ENV_FILE"

    # Prompt for the bot token
    echo ""
    echo -e "${YELLOW}Enter your Telegram Bot Token (from @BotFather):${NC}"
    read -r -p "Token: " BOT_TOKEN
    if [ -z "$BOT_TOKEN" ]; then
        error "Bot token cannot be empty!"
    fi
    sed -i "s|TELEGRAM_BOT_TOKEN=your_bot_token_here|TELEGRAM_BOT_TOKEN=$BOT_TOKEN|" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    info ".env created and secured (chmod 600)"
fi

# ── 5. Create output / tmp directories ───────────────────────
mkdir -p "$APP_DIR/output" "$APP_DIR/tmp"

# ── 6. systemd service ───────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
info "Installing systemd service..."

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=TikTok Video Clip Generator Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/bot.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

# ── 7. Status check ──────────────────────────────────────────
sleep 3
echo ""
info "=== Service Status ==="
systemctl status "$SERVICE_NAME" --no-pager -l || true

echo ""
info "=== Setup complete! ==="
echo -e "  App dir:   ${GREEN}${APP_DIR}${NC}"
echo -e "  Logs:      ${GREEN}journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "  Restart:   ${GREEN}systemctl restart ${SERVICE_NAME}${NC}"
echo -e "  Stop:      ${GREEN}systemctl stop ${SERVICE_NAME}${NC}"
