#!/usr/bin/env bash
# Перезапуск стенда после доставки кода (вызывается из GitHub Actions).
# Использование: update.sh [prod|dev]   (по умолчанию prod)
set -euo pipefail

STAND="${1:-prod}"
case "$STAND" in
    prod) APP_DIR=/opt/markdown-bot;     UNITS="markdown-bot markdown-studio" ;;
    dev)  APP_DIR=/opt/markdown-bot-dev; UNITS="markdown-bot-dev markdown-studio-dev" ;;
    *) echo "Неизвестный стенд: $STAND"; exit 1 ;;
esac

cd "$APP_DIR"
venv/bin/pip install -q -r requirements.txt
chown -R markdown:markdown "$APP_DIR"

# юниты могли измениться
for u in $UNITS; do cp "deploy/$u.service" /etc/systemd/system/; done
systemctl daemon-reload
systemctl restart $UNITS
sleep 2
systemctl --no-pager --quiet is-active $UNITS
echo "Deploy OK [$STAND]: $(date -u +%FT%TZ)"
