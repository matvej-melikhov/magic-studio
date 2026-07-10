#!/usr/bin/env bash
# Первичная настройка сервера (Ubuntu/Debian). Запуск от root:
#   bash deploy/setup.sh https://github.com/<user>/<repo>.git
set -euo pipefail

REPO_URL="${1:?Укажите URL git-репозитория первым аргументом}"
APP_DIR=/opt/markdown-bot

apt-get update -qq
apt-get install -y -qq git python3 python3-venv rsync nginx

id -u markdown &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin markdown

if [ ! -d "$APP_DIR/.git" ]; then
    git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
git config --global --add safe.directory "$APP_DIR"

python3 -m venv venv
venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
    cat > .env <<'EOF'
# Заполните и перезапустите сервисы: systemctl restart markdown-bot markdown-studio
TELEGRAM_KEY=
S3_ENDPOINT=
S3_REGION=
S3_BUCKET=
S3_PUBLIC_BASE=
S3_ACCESS_KEY=
S3_SECRET_KEY=
# AI-помощник (опционально): адрес Ollama и модель
OLLAMA_URL=http://localhost:11434
AI_MODEL=gemma4:12b-mlx
EOF
    echo "!!! Заполните $APP_DIR/.env и выполните: systemctl restart markdown-bot markdown-studio"
fi

chown -R markdown:markdown "$APP_DIR"

cp deploy/markdown-bot.service deploy/markdown-studio.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now markdown-bot markdown-studio

echo "Готово. Редактор: http://$(hostname -I | awk '{print $1}')/"
