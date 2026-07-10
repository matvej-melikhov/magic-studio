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

# роутинг стендов (/prod, /dev) — если на сервере установлен nginx.
# reload/restart могут не пройти, пока 80 порт ещё занят старым продом —
# это не ошибка деплоя: nginx поднимется со следующей раскаткой прода
if command -v nginx >/dev/null && [ -d /etc/nginx/sites-available ]; then
    cp deploy/nginx-stands.conf /etc/nginx/sites-available/stands.conf
    ln -sf ../sites-available/stands.conf /etc/nginx/sites-enabled/stands.conf
    rm -f /etc/nginx/sites-enabled/default
    if nginx -t -q 2>/dev/null; then
        systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
    fi
fi

echo "Deploy OK [$STAND]: $(date -u +%FT%TZ)"
