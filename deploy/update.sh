#!/usr/bin/env bash
# Перезапуск после доставки кода (вызывается из GitHub Actions после rsync).
set -euo pipefail
cd /opt/markdown-bot

venv/bin/pip install -q -r requirements.txt
chown -R markdown:markdown /opt/markdown-bot

# юниты могли измениться
cp deploy/markdown-bot.service deploy/markdown-studio.service /etc/systemd/system/
systemctl daemon-reload
systemctl restart markdown-bot markdown-studio
sleep 2
systemctl --no-pager --quiet is-active markdown-bot markdown-studio
echo "Deploy OK: $(date -u +%FT%TZ)"
