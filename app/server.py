"""Веб-редактор постов: точка входа.

Запуск из корня репозитория:  python3 app/server.py
(токен берётся из .env или переменной BOT_TOKEN)
Открыть с телефона: http://<IP-мака-в-Wi-Fi>:8080

HTTP-слой — FastAPI-приложение в webapp.py (запускается uvicorn'ом),
доменная логика — core.py, данные — SQLite (storage.py, studio.db).
"""

import logging
import sys
import threading

import uvicorn

import core
import storage
from core import PORT, api_call, local_ips, scheduler_loop
from webapp import app

log = logging.getLogger("editor-server")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not core.BOT_TOKEN:
        sys.exit("Задайте BOT_TOKEN в .env или переменной окружения.")
    storage.init_db()
    ok, me = api_call("getMe")
    if not ok:
        sys.exit(f"Токен не принят Telegram: {me}")
    core.BOT_USERNAME = me.get("username", "")
    log.info("Редактор для бота @%s (данные: %s)", core.BOT_USERNAME, storage.DB_FILE)
    if core.s3.configured:
        log.info("Картинки: S3 %s/%s", core.s3.endpoint, core.s3.bucket)
    else:
        log.info("Картинки: хранилище Telegram (S3 не настроен в .env)")
    log.info("AI-помощник: %s через %s", core.AI_MODEL, core.OLLAMA_URL)
    for ip in local_ips():
        log.info("Открыть на телефоне: http://%s:%d", ip, PORT)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
