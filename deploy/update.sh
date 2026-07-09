#!/usr/bin/env bash
# Обновление приложения (вызывается из GitHub Actions). Запуск от root.
set -euo pipefail
cd /opt/markdown-bot

git fetch origin main
git reset --hard origin/main
venv/bin/pip install -q -r requirements.txt
chown -R markdown:markdown /opt/markdown-bot

# юниты могли измениться
cp deploy/markdown-bot.service deploy/markdown-studio.service /etc/systemd/system/
systemctl daemon-reload
systemctl restart markdown-bot markdown-studio
systemctl --no-pager --quiet is-active markdown-bot markdown-studio
echo "Deployed $(git rev-parse --short HEAD)"
