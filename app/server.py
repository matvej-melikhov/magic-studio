"""Локальный веб-редактор постов (эмуляция будущей Mini App).

Запуск из корня репозитория:  python3 app/server.py
(токен берётся из .env или переменной BOT_TOKEN)
Открыть с телефона: http://<IP-мака-в-Wi-Fi>:8080

Данные (сессии, каналы, черновики, отложенные, публикации) — в SQLite
(storage.py, файл studio.db). Старый data.json импортируется автоматически.
"""

import base64
import json
import logging
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

import storage
from env_utils import load_env
from s3_utils import S3Storage

load_env()

s3 = S3Storage()

BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_KEY")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

PORT = int(os.environ.get("PORT", "8080"))
# фронтенд и PWA-статика лежат в web/ рядом с пакетом app/
WEB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
EDITOR_FILE = os.path.join(WEB_DIR, "editor.html")
LOGIN_CODES_FILE = "login_codes.json"

log = logging.getLogger("editor-server")

BOT_USERNAME = ""  # заполняется в main() из getMe

# Плейсхолдер картинки в markdown-черновике
TG_FILE_RE = re.compile(r"tg-file://([A-Za-z0-9_-]+)")

# Одноразовый хостинг-трамплин: перезаливка медиа, которые серверы Telegram
# не могут скачать сами (файлы из хранилища Telegram; S3 — только если
# включён S3_TRAMPOLINE=1, это нужно для недоступных Telegram хостингов
# вроде Selectel; Yandex Object Storage доступен напрямую)
LITTERBOX_API = "https://litterbox.catbox.moe/resources/internals/api.php"
S3_TRAMPOLINE = os.environ.get("S3_TRAMPOLINE", "0") == "1"

# Через сколько секунд зависший «sending» считается прерванным
SENDING_STALE_AFTER = 180

# ── AI-помощник: Ollama ─────────────────────────────
# Без ключа — локальный демон (OLLAMA_URL=http://localhost:11434).
# С OLLAMA_API_KEY — облако ollama.com напрямую, демон не нужен:
#   OLLAMA_URL=https://ollama.com  OLLAMA_API_KEY=<ключ из settings/keys>
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "gemma4:12b-mlx")

# Шпаргалка по rich-формату — общая часть системного промпта
AI_FORMAT_GUIDE = """Ты работаешь с Rich Markdown — форматом постов Telegram (Bot API 10.1).
Доступная разметка:
- Заголовки: # … ###### (шесть уровней)
- **жирный**, _курсив_, ~~зачёркнутый~~, <u>подчёркнутый</u>, ==выделение маркером==, ||спойлер||
- `код в строке` и блоки кода ```язык … ```
- Формулы LaTeX: $x^2$ в строке, $$…$$ блоком (сырой LaTeX, без экранирования)
- Цитаты: > текст; выносная цитата: <aside>текст<cite>Автор</cite></aside>
- Списки: -, 1., чекбоксы - [ ] / - [x]
- Таблицы GFM, разделитель ---, сноски [^1] с определением [^1]: текст
- Свёртка: <details><summary>Заголовок</summary>текст</details>
- Подпись поста: <footer>текст</footer>
- Медиа только блочными строками: ![](https://… "Подпись")
Важно: одиночный перенос строки склеивается в пробел — абзацы разделяй пустой строкой.
Отвечай ТОЛЬКО готовым текстом поста, без пояснений, без обёртки ```markdown."""

AI_PROMPTS = {
    "rewrite": (
        AI_FORMAT_GUIDE + "\n\nЗадача: перепиши присланный фрагмент — сделай его яснее "
        "и живее, сохранив смысл, язык, тон и уже имеющуюся разметку. "
        "Не добавляй ничего от себя и не комментируй."
    ),
    "format": (
        AI_FORMAT_GUIDE + "\n\nЗадача: оформи присланный сырой текст разметкой Rich Markdown. "
        "Сам текст не переписывай. Добавляй разметку только там, где она реально улучшает "
        "читаемость: перечисления — в списки, имена переменных и команд — в `код`, "
        "формулы — в $…$/$$…$$, крупные смысловые части — под заголовки. "
        "Если тексту разметка не нужна — верни его без изменений."
    ),
    "generate": (
        AI_FORMAT_GUIDE + "\n\nЗадача: напиши пост для Telegram-канала по запросу "
        "пользователя. Пиши на языке запроса, структурируй разметкой там, где это уместно.\n"
        "По умолчанию пиши КОРОТКО: 2–3 предложения, без заголовков и списков — "
        "как обычный пост в канале. Развёрнутый длинный текст пиши только если "
        "пользователь прямо просит об этом («подробно», «длинный пост», "
        "«со списком», указывает объём и т.п.)."
    ),
}


def ai_stream(action: str, text: str):
    """Генератор чанков ответа модели: {'t': текст} | {'error': …} | {'done': True}."""
    system = AI_PROMPTS.get(action)
    if not system:
        yield {"error": "Неизвестное действие."}
        return
    headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else {}
    try:
        with requests.post(
            f"{OLLAMA_URL}/api/chat",
            headers=headers,
            json={
                "model": AI_MODEL,
                "stream": True,
                "think": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                "options": {"temperature": 0.7, "num_ctx": 8192},
            },
            stream=True,
            timeout=300,
        ) as resp:
            if not resp.ok:
                yield {"error": f"Ollama: {resp.status_code} {resp.text[:200]}"}
                return
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    yield {"error": f"Ollama: {chunk['error']}"}
                    return
                part = (chunk.get("message") or {}).get("content", "")
                if part:
                    yield {"t": part}
                if chunk.get("done"):
                    break
        yield {"done": True}
    except requests.RequestException as e:
        yield {"error": ("Ollama недоступен — запустите `ollama serve` "
                         f"({e.__class__.__name__})")}


def consume_login_code(code: str) -> dict | None:
    """Проверяет код из login_codes.json (пишет bot.py) и гасит его."""
    try:
        codes = json.load(open(LOGIN_CODES_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = codes.pop(code, None)
    if not entry or entry.get("expires", 0) < time.time():
        return None
    tmp = LOGIN_CODES_FILE + ".tmp"
    json.dump(codes, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, LOGIN_CODES_FILE)
    return entry


def api_call(method: str, files=None, **params):
    if files:
        resp = requests.post(f"{API_URL}/{method}", data=params, files=files, timeout=120)
    else:
        resp = requests.post(f"{API_URL}/{method}", json=params, timeout=60)
    data = resp.json()
    if data.get("ok"):
        return True, data.get("result")
    return False, data.get("description", "unknown error")


def verify_channel_admin(username: str, user_id) -> tuple[bool, str | dict]:
    """Проверяет, что канал существует, бот в нём есть, а user_id — админ."""
    ok, chat = api_call("getChat", chat_id=username)
    if not ok:
        return False, f"Канал не найден или бот не добавлен: {chat}"
    ok, admins = api_call("getChatAdministrators", chat_id=username)
    if not ok:
        return False, f"Не удалось проверить администраторов: {admins}"
    if not any(a.get("user", {}).get("id") == int(user_id) for a in admins):
        return False, "Вы не администратор этого канала."
    return True, chat


def _upload_litterbox(filename: str, blob: bytes) -> tuple[bool, str]:
    try:
        resp = requests.post(
            LITTERBOX_API,
            data={"reqtype": "fileupload", "time": "1h"},
            files={"fileToUpload": (filename, blob)},
            timeout=120,
        )
    except requests.RequestException as e:
        return False, f"litterbox недоступен: {e}"
    if not resp.ok or not resp.text.startswith("http"):
        return False, f"litterbox: {resp.status_code}"
    return True, resp.text.strip()


def _upload_uguu(filename: str, blob: bytes) -> tuple[bool, str]:
    try:
        resp = requests.post(
            "https://uguu.se/upload",
            files={"files[]": (filename, blob)},
            timeout=120,
        )
        data = resp.json()
        url = data["files"][0]["url"]
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        return False, f"uguu недоступен: {e}"
    return True, url


def trampoline_upload(filename: str, blob: bytes) -> tuple[bool, str]:
    """Заливает файл на одноразовый хостинг; при сбое пробует запасной."""
    errors = []
    for uploader in (_upload_litterbox, _upload_uguu):
        ok, result = uploader(filename, blob)
        if ok:
            return True, result
        errors.append(result)
        log.warning("Трамплин не сработал: %s", result)
    return False, "Хостинги-трамплины недоступны: " + "; ".join(errors)


def store_image(chat_id: int, filename: str, blob: bytes) -> tuple[bool, str]:
    """Кладёт картинку в хранилище Telegram, возвращает (ok, file_id|ошибка).

    Файл отправляется документом (без пережатия) в чат пользователя и сразу
    удаляется — file_id остаётся действительным.
    """
    ok, msg = api_call(
        "sendDocument",
        chat_id=chat_id,
        disable_notification=True,
        files={"document": (filename, blob)},
    )
    if not ok:
        return False, msg
    file_id = msg["document"]["file_id"]
    api_call("deleteMessage", chat_id=chat_id, message_id=msg["message_id"])
    return True, file_id


def resolve_media(markdown: str) -> tuple[bool, str]:
    """Готовит медиа к публикации: недоступные для Telegram источники
    (наш S3 и хранилище Telegram) перезаливаются на трамплин."""
    error = None

    def to_trampoline(filename: str, blob: bytes, original: str) -> str:
        nonlocal error
        ok, url = trampoline_upload(filename, blob)
        if not ok:
            error = url
            return original
        return url

    def repl_tg_file(match):
        nonlocal error
        ok, info = api_call("getFile", file_id=match.group(1))
        if not ok:
            error = f"Картинка недоступна: {info}"
            return match.group(0)
        resp = requests.get(f"{FILE_URL}/{info['file_path']}", timeout=120)
        if not resp.ok:
            error = f"Не удалось скачать картинку из Telegram: {resp.status_code}"
            return match.group(0)
        name = os.path.basename(info["file_path"])
        return to_trampoline(name, resp.content, match.group(0))

    resolved = TG_FILE_RE.sub(repl_tg_file, markdown)

    if s3.configured and s3.public_base and S3_TRAMPOLINE:
        s3_url_re = re.compile(re.escape(s3.public_base) + r"/[^\s\)\"]+")

        def repl_s3(match):
            nonlocal error
            url = match.group(0)
            resp = requests.get(url, timeout=120)
            if not resp.ok:
                error = f"Не удалось скачать из S3: {resp.status_code}"
                return url
            return to_trampoline(os.path.basename(url), resp.content, url)

        resolved = s3_url_re.sub(repl_s3, resolved)

    if error:
        return False, error
    return True, resolved


def check_token_leak(sent_message: dict):
    """Проверяет, что исходные URL медиа не попали в доставленное сообщение."""
    if "api.telegram.org/file" in json.dumps(sent_message):
        log.warning(
            "ВНИМАНИЕ: исходный URL медиа (с токеном) виден в отправленном "
            "сообщении! Нужно менять схему хранения картинок."
        )


def send_post(markdown: str, target) -> tuple[bool, str | dict]:
    """Публикует rich-пост. Возвращает (True, Message) или (False, ошибка)."""
    try:
        ok, resolved = resolve_media(markdown)
        if not ok:
            return False, resolved
        ok, result = api_call(
            "sendRichMessage", chat_id=target, rich_message={"markdown": resolved}
        )
        if not ok:
            return False, result
        check_token_leak(result)
        return True, result
    except Exception as e:
        log.exception("send_post %s", target)
        return False, f"Ошибка отправки: {e}"


def edit_post(markdown: str, target, message_id: int) -> tuple[bool, str]:
    """Редактирует уже опубликованный rich-пост."""
    try:
        ok, resolved = resolve_media(markdown)
        if not ok:
            return False, resolved
        ok, result = api_call(
            "editMessageText",
            chat_id=target,
            message_id=message_id,
            rich_message={"markdown": resolved},
        )
        if not ok:
            return False, result
        return True, "ok"
    except Exception as e:
        log.exception("edit_post %s/%s", target, message_id)
        return False, f"Ошибка редактирования: {e}"


def scheduler_loop():
    """Фоновый цикл: публикует отложенные посты, у которых подошло время."""
    while True:
        time.sleep(15)
        try:
            due = storage.sched_take_due(SENDING_STALE_AFTER)
            for post in due:
                # ошибка одного поста не должна ронять обработку остальных
                try:
                    ok, result = send_post(post["markdown"], post["target"])
                except Exception as e:
                    ok, result = False, f"Внутренняя ошибка: {e}"
                message_id = result.get("message_id") if ok else None
                storage.sched_finish(post, ok, "" if ok else str(result), message_id)
                log.info("Отложенный пост %s → %s: %s",
                         post["id"], post["target"], "ok" if ok else result)
        except Exception:
            log.exception("Ошибка планировщика")


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

    # Статика PWA: манифест и иконки приложения
    STATIC_FILES = {
        "/manifest.json": ("manifest.json", "application/manifest+json"),
        "/icon-180.png": ("icon-180.png", "image/png"),
        "/icon-512.png": ("icon-512.png", "image/png"),
    }

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                body = open(EDITOR_FILE, "rb").read()
            except OSError:
                self._send(500, b"editor.html not found", "text/plain")
                return
            self._send(200, body, "text/html; charset=utf-8")
        elif self.path in self.STATIC_FILES:
            name, ctype = self.STATIC_FILES[self.path]
            path = os.path.join(os.path.dirname(EDITOR_FILE), name)
            try:
                self._send(200, open(path, "rb").read(), ctype)
            except OSError:
                self._send(404, b"not found", "text/plain")
        elif self.path == "/api/config":
            self._json({"ok": True, "bot": BOT_USERNAME})
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
            else:
                self._json({"ok": False, "error": "unknown endpoint"}, 404)
        except Exception as e:
            log.exception("Ошибка обработки %s", self.path)
            self._json({"ok": False, "error": str(e)}, 500)


def local_ips() -> list[str]:
    """IP-адреса локальных сетей (VPN-интерфейсы вроде 198.18.x.x отсеиваются)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    lan = [ip for ip in sorted(ips)
           if ip.startswith(("192.168.", "10.")) or
           (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)]
    return lan or ["127.0.0.1"]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not BOT_TOKEN:
        sys.exit("Задайте BOT_TOKEN в .env или переменной окружения.")
    storage.init_db()
    ok, me = api_call("getMe")
    if not ok:
        sys.exit(f"Токен не принят Telegram: {me}")
    global BOT_USERNAME
    BOT_USERNAME = me.get("username", "")
    log.info("Редактор для бота @%s (данные: %s)", BOT_USERNAME, storage.DB_FILE)
    if s3.configured:
        log.info("Картинки: S3 %s/%s", s3.endpoint, s3.bucket)
    else:
        log.info("Картинки: хранилище Telegram (S3 не настроен в .env)")
    log.info("AI-помощник: %s через %s", AI_MODEL, OLLAMA_URL)
    for ip in local_ips():
        log.info("Открыть на телефоне: http://%s:%d", ip, PORT)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
