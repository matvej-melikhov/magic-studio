"""Локальный веб-редактор постов (эмуляция будущей Mini App).

Запуск из корня репозитория:  python3 app/server.py
(токен берётся из .env или переменной BOT_TOKEN)
Открыть с телефона: http://<IP-мака-в-Wi-Fi>:8080

HTTP-слой: маршрутизация и сериализация. Доменная логика — в core.py,
данные (сессии, каналы, черновики, отложенные, публикации) — в SQLite
(storage.py, файл studio.db).
"""

import base64
import json
import logging
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import os

import core
import storage
from core import (
    DIST_DIR, DIST_INDEX, EDITOR_FILE, PORT, WEB_DIR,
    ai_stream, api_call, consume_login_code, edit_post, fetch_emoji_image,
    local_ips, s3, scheduler_loop, send_post, store_image,
    verify_channel_admin,
)

log = logging.getLogger("editor-server")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def _session(self) -> dict | None:
        token = self.headers.get("X-Session", "")
        return storage.session_get(token) if token else None

    # Статика PWA: манифест и иконки приложения (+ лендинг вне SPA)
    STATIC_FILES = {
        "/about": ("about.html", "text/html; charset=utf-8"),
        "/manifest.json": ("manifest.json", "application/manifest+json"),
        "/icon-180.png": ("icon-180.png", "image/png"),
        "/icon-512.png": ("icon-512.png", "image/png"),
        "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        "/favicon-64.png": ("favicon-64.png", "image/png"),
    }

    # Хешированные ассеты Vite: имя содержит хеш содержимого — кешируем навечно
    ASSET_TYPES = {
        ".js": "text/javascript", ".css": "text/css", ".map": "application/json",
        ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2",
        ".webp": "image/webp", ".ico": "image/x-icon",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    }

    def _serve_asset(self, rel_path: str) -> bool:
        """Отдаёт файл из dist/assets с длинным кешем. False — файла нет."""
        full = os.path.realpath(os.path.join(DIST_DIR, rel_path.lstrip("/")))
        if not full.startswith(os.path.realpath(DIST_DIR) + os.sep):
            return False  # защита от path traversal
        ext = os.path.splitext(full)[1]
        if ext not in self.ASSET_TYPES:
            return False
        try:
            body = open(full, "rb").read()
        except OSError:
            return False
        self.send_response(200)
        self.send_header("Content-Type", self.ASSET_TYPES[ext])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(body)
        return True

    def _serve_spa(self):
        """index.html React-сборки, при её отсутствии — старый editor.html."""
        for candidate in (DIST_INDEX, EDITOR_FILE):
            try:
                body = open(candidate, "rb").read()
            except OSError:
                continue
            self._send(200, body, "text/html; charset=utf-8")
            return
        self._send(500, b"frontend not found", "text/plain")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_spa()
        elif self.path.startswith("/assets/"):
            if not self._serve_asset(self.path):
                self._send(404, b"not found", "text/plain")
        elif self.path == "/api/emojis":
            session = self._session()
            if not session:
                self._json({"ok": False, "error": "auth"}, 401)
                return
            uid = session["user_id"]
            groups = [{"id": p["id"], "name": p["name"],
                       "emojis": storage.emojis_by_pack(uid, p["id"])}
                      for p in storage.epacks_list(uid)]
            self._json({"ok": True, "groups": groups})
        elif self.path.startswith("/api/emoji/img"):
            # без сессии: <img> не умеет слать заголовки; отдаём только картинку
            emoji_id = (re.search(r"id=(\d{1,32})$", self.path) or [None, ""])[1]
            img = fetch_emoji_image(emoji_id) if emoji_id else None
            if img:
                self._send(200, img[0], img[1])
            else:
                self._send(404, b"emoji not found", "text/plain")
        elif self.path.split("?", 1)[0] in self.STATIC_FILES:
            name, ctype = self.STATIC_FILES[self.path.split("?", 1)[0]]
            # сборка кладёт public/ в dist/; без сборки берём из web/public/
            for base in (DIST_DIR, os.path.join(WEB_DIR, "public")):
                try:
                    self._send(200, open(os.path.join(base, name), "rb").read(), ctype)
                    return
                except OSError:
                    continue
            self._send(404, b"not found", "text/plain")
        elif self.path == "/api/config":
            self._json({"ok": True, "bot": core.BOT_USERNAME})
        elif self.path == "/api/state":
            session = self._session()
            if not session:
                self._json({"ok": False, "error": "auth"}, 401)
                return
            uid = session["user_id"]
            self._json({
                "ok": True,
                "name": session.get("name", ""),
                "channels": storage.channels_list(uid),
                "drafts": storage.drafts_list(uid),
                "scheduled": storage.sched_list(uid),
                "published": storage.published_list(uid),
            })
        elif not self.path.startswith("/api/"):
            # SPA fallback: /editor, /drafts и т.п. при обновлении страницы
            # должны вернуть приложение, роутер сам откроет нужный раздел
            self._serve_spa()
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        try:
            if self.path == "/api/login":
                code = str(self._read_json().get("code", "")).strip()
                entry = consume_login_code(code)
                if not entry:
                    self._json({"ok": False, "error": "Неверный или устаревший код."})
                    return
                token = storage.session_create(entry["user_id"], entry.get("name", ""))
                self._json({"ok": True, "token": token})
                return

            session = self._session()
            if not session:
                self._json({"ok": False, "error": "auth"}, 401)
                return
            uid = session["user_id"]

            if self.path == "/api/upload":
                data = self._read_json()
                blob = base64.b64decode(data["data"])
                name = data.get("name", "image.jpg")
                if s3.configured:
                    ok, result = s3.upload(name, blob)
                    self._json({"ok": ok, "url" if ok else "error": result})
                else:
                    # S3 не настроен — фолбэк на хранилище Telegram
                    ok, result = store_image(uid, name, blob)
                    if ok:
                        self._json({"ok": True, "url": f"tg-file://{result}"})
                    else:
                        self._json({"ok": False, "error": result})
            elif self.path == "/api/preview":
                data = self._read_json()
                ok, result = send_post(data["markdown"], uid)
                self._json({"ok": ok, "error": None if ok else str(result)})
            elif self.path == "/api/publish":
                data = self._read_json()
                target = data.get("target", "").strip()
                allowed = {c["username"] for c in storage.channels_list(uid)}
                if target not in allowed:
                    self._json({"ok": False,
                                "error": "Канал не подключён — добавьте его во вкладке «Каналы»."})
                    return
                ok, result = send_post(data["markdown"], target)
                if ok:
                    storage.published_add(uid, target, data["markdown"],
                                          result.get("message_id"))
                self._json({"ok": ok, "error": None if ok else str(result)})
            elif self.path == "/api/published/update":
                data = self._read_json()
                post = storage.published_get(uid, data.get("id", ""))
                if not post:
                    self._json({"ok": False, "error": "Публикация не найдена."})
                    return
                if not post.get("message_id"):
                    self._json({"ok": False, "error":
                                "Для этого поста не сохранён message_id — "
                                "редактировать можно только новые публикации."})
                    return
                ok, result = edit_post(data.get("markdown", ""),
                                       post["target"], post["message_id"])
                if ok:
                    storage.published_update_markdown(uid, post["id"],
                                                      data.get("markdown", ""))
                self._json({"ok": ok, "error": None if ok else result})
            elif self.path == "/api/channels/add":
                username = self._read_json().get("username", "").strip()
                if username and not username.startswith("@"):
                    username = "@" + username
                if not username:
                    self._json({"ok": False, "error": "Укажите @username канала."})
                    return
                ok, chat = verify_channel_admin(username, uid)
                if not ok:
                    self._json({"ok": False, "error": chat})
                    return
                storage.channel_add(uid, username, chat.get("title", username))
                self._json({"ok": True})
            elif self.path == "/api/channels/remove":
                storage.channel_remove(uid, self._read_json().get("username", ""))
                self._json({"ok": True})
            elif self.path == "/api/drafts/save":
                data = self._read_json()
                draft_id = storage.draft_save(uid, data.get("id"),
                                              data.get("markdown", ""))
                self._json({"ok": True, "id": draft_id})
            elif self.path == "/api/drafts/delete":
                storage.draft_delete(uid, self._read_json().get("id", ""))
                self._json({"ok": True})
            elif self.path == "/api/schedule/add":
                data = self._read_json()
                target = data.get("target", "").strip()
                when = int(data.get("when", 0))
                if not target:
                    self._json({"ok": False, "error": "Укажите канал."})
                    return
                if when <= time.time():
                    self._json({"ok": False, "error": "Время уже прошло."})
                    return
                storage.sched_add(uid, data.get("markdown", ""), target, when)
                self._json({"ok": True})
            elif self.path == "/api/schedule/update":
                data = self._read_json()
                when = int(data.get("when", 0))
                if when <= time.time():
                    self._json({"ok": False, "error": "Время уже прошло."})
                    return
                if storage.sched_update(uid, data.get("id", ""),
                                        data.get("markdown", ""),
                                        data.get("target", "").strip(), when):
                    self._json({"ok": True})
                else:
                    self._json({"ok": False, "error": "Пост не найден или уже отправлен."})
            elif self.path == "/api/ai":
                data = self._read_json()
                text = (data.get("text") or "").strip()
                if not text:
                    self._json({"ok": False, "error": "Пустой запрос."})
                    return
                # потоковый ответ: NDJSON-чанки по мере генерации модели
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    for chunk in ai_stream(data.get("action", ""), text):
                        self.wfile.write(
                            (json.dumps(chunk, ensure_ascii=False) + "\n").encode())
                        self.wfile.flush()
                except OSError:
                    log.info("Клиент оборвал AI-стрим")
                except Exception as e:
                    log.exception("Ошибка AI-стрима")
                    try:
                        self.wfile.write(
                            (json.dumps({"error": str(e)}) + "\n").encode())
                    except OSError:
                        pass
            elif self.path == "/api/schedule/cancel":
                storage.sched_cancel(uid, self._read_json().get("id", ""))
                self._json({"ok": True})
            elif self.path == "/api/schedule/publish_now":
                post = storage.sched_take_now(uid, self._read_json().get("id", ""))
                if not post:
                    self._json({"ok": False,
                                "error": "Пост не найден или уже отправляется."})
                    return
                ok, result = send_post(post["markdown"], post["target"])
                message_id = result.get("message_id") if ok else None
                storage.sched_finish(post, ok, None if ok else str(result),
                                     message_id)
                self._json({"ok": ok, "error": None if ok else str(result)})
            else:
                self._json({"ok": False, "error": "unknown endpoint"}, 404)
        except Exception as e:
            log.exception("Ошибка обработки %s", self.path)
            self._json({"ok": False, "error": str(e)}, 500)


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
    if s3.configured:
        log.info("Картинки: S3 %s/%s", s3.endpoint, s3.bucket)
    else:
        log.info("Картинки: хранилище Telegram (S3 не настроен в .env)")
    log.info("AI-помощник: %s через %s", core.AI_MODEL, core.OLLAMA_URL)
    for ip in local_ips():
        log.info("Открыть на телефоне: http://%s:%d", ip, PORT)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
