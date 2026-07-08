"""Локальный веб-редактор постов (эмуляция будущей Mini App).

Запуск:  python3 server.py   (токен берётся из .env или переменной BOT_TOKEN)
Открыть с телефона: http://<IP-мака-в-Wi-Fi>:8080

Картинки хранятся в Telegram: загруженный файл отправляется в чат владельца
с ботом (и сразу удаляется) — остаётся file_id. В markdown картинка живёт
как плейсхолдер tg-file://<file_id>, который резолвится в свежую HTTPS-ссылку
только в момент превью/публикации (file_path действует ~1 час).
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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from env_utils import load_env
from s3_utils import S3Storage

load_env()

s3 = S3Storage()

BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_KEY")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

PORT = int(os.environ.get("PORT", "8080"))
STATE_FILE = "state.json"
DATA_FILE = "data.json"
EDITOR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor.html")

# Данные пользователей и сессии — в data.json:
# {"sessions": {token: {user_id, name}}, "users": {uid: {channels, drafts, …}}}
_data_lock = threading.Lock()

LOGIN_CODES_FILE = "login_codes.json"
EMPTY_USER = {"channels": [], "drafts": [], "scheduled": [], "published": []}


def load_data() -> dict:
    try:
        data = json.load(open(DATA_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("sessions", {})
    data.setdefault("users", {})
    return data


def user_data(data: dict, user_id) -> dict:
    box = data["users"].setdefault(str(user_id), {})
    for key, empty in EMPTY_USER.items():
        box.setdefault(key, [])
    return box


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


def save_data(data: dict):
    tmp = DATA_FILE + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, DATA_FILE)


def log_published(box: dict, target: str, markdown: str):
    title = markdown.strip().splitlines()[0][:80] if markdown.strip() else "(пусто)"
    box["published"].insert(0, {
        "id": uuid.uuid4().hex,
        "target": target,
        "title": title.lstrip("# ").strip(),
        "when": int(time.time()),
    })
    del box["published"][50:]


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

# Плейсхолдер картинки в markdown-черновике
TG_FILE_RE = re.compile(r"tg-file://([A-Za-z0-9_-]+)")

# Одноразовый хостинг-трамплин: серверы Telegram не могут скачивать напрямую
# из сетей Selectel, поэтому при публикации медиа перезаливается на litterbox
# (живёт 1 час — Telegram перехостит картинку у себя в момент отправки)
LITTERBOX_API = "https://litterbox.catbox.moe/resources/internals/api.php"


def trampoline_upload(filename: str, blob: bytes) -> tuple[bool, str]:
    """Заливает файл на litterbox, возвращает (ok, url|ошибка)."""
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
        return False, f"litterbox ответил: {resp.status_code} {resp.text[:200]}"
    return True, resp.text.strip()

log = logging.getLogger("editor-server")

BOT_USERNAME = ""  # заполняется в main() из getMe


def api_call(method: str, files=None, **params):
    if files:
        resp = requests.post(f"{API_URL}/{method}", data=params, files=files, timeout=120)
    else:
        resp = requests.post(f"{API_URL}/{method}", json=params, timeout=60)
    data = resp.json()
    if data.get("ok"):
        return True, data.get("result")
    return False, data.get("description", "unknown error")


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

    if s3.configured and s3.public_base:
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


def send_post(markdown: str, target) -> tuple[bool, str]:
    ok, resolved = resolve_media(markdown)
    if not ok:
        return False, resolved
    ok, result = api_call(
        "sendRichMessage", chat_id=target, rich_message={"markdown": resolved}
    )
    if not ok:
        return False, result
    check_token_leak(result)
    return True, "ok"


def scheduler_loop():
    """Фоновый цикл: публикует отложенные посты, у которых подошло время."""
    while True:
        time.sleep(15)
        try:
            due = []
            with _data_lock:
                data = load_data()
                for uid, box in data["users"].items():
                    for post in box.get("scheduled", []):
                        if post["status"] == "pending" and post["when"] <= time.time():
                            post["status"] = "sending"
                            due.append((uid, post))
                if due:
                    save_data(data)
            for uid, post in due:
                ok, result = send_post(post["markdown"], post["target"])
                with _data_lock:
                    data = load_data()
                    box = user_data(data, uid)
                    for p in box["scheduled"]:
                        if p["id"] == post["id"]:
                            p["status"] = "sent" if ok else "error"
                            if not ok:
                                p["error"] = result
                            else:
                                log_published(box, post["target"], post["markdown"])
                    save_data(data)
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
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def _session(self) -> dict | None:
        """Сессия по заголовку X-Session, либо None."""
        token = self.headers.get("X-Session", "")
        if not token:
            return None
        with _data_lock:
            return load_data()["sessions"].get(token)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                body = open(EDITOR_FILE, "rb").read()
            except OSError:
                self._send(500, b"editor.html not found", "text/plain")
                return
            self._send(200, body, "text/html; charset=utf-8")
        elif self.path == "/api/config":
            self._json({"ok": True, "bot": BOT_USERNAME})
        elif self.path == "/api/state":
            session = self._session()
            if not session:
                self._json({"ok": False, "error": "auth"}, 401)
                return
            with _data_lock:
                data = load_data()
                box = user_data(data, session["user_id"])
                self._json({"ok": True, "name": session.get("name", ""), **box})
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
                token = uuid.uuid4().hex
                with _data_lock:
                    store = load_data()
                    store["sessions"][token] = {
                        "user_id": entry["user_id"], "name": entry.get("name", ""),
                        "created": int(time.time()),
                    }
                    user_data(store, entry["user_id"])
                    save_data(store)
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
                self._json({"ok": ok, "error": None if ok else result})
            elif self.path == "/api/publish":
                data = self._read_json()
                target = data.get("target", "").strip()
                with _data_lock:
                    store = load_data()
                    allowed = {c["username"]
                               for c in user_data(store, uid)["channels"]}
                if target not in allowed:
                    self._json({"ok": False,
                                "error": "Канал не подключён — добавьте его во вкладке «Каналы»."})
                    return
                ok, result = send_post(data["markdown"], target)
                if ok:
                    with _data_lock:
                        store = load_data()
                        log_published(user_data(store, uid), target, data["markdown"])
                        save_data(store)
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
                with _data_lock:
                    store = load_data()
                    box = user_data(store, uid)
                    box["channels"] = [c for c in box["channels"]
                                       if c["username"] != username]
                    box["channels"].append(
                        {"username": username, "title": chat.get("title", username)})
                    save_data(store)
                self._json({"ok": True})
            elif self.path == "/api/channels/remove":
                username = self._read_json().get("username", "")
                with _data_lock:
                    store = load_data()
                    box = user_data(store, uid)
                    box["channels"] = [c for c in box["channels"]
                                       if c["username"] != username]
                    save_data(store)
                self._json({"ok": True})
            elif self.path == "/api/drafts/save":
                data = self._read_json()
                draft_id = data.get("id") or uuid.uuid4().hex
                markdown = data.get("markdown", "")
                title = (markdown.strip().splitlines() or ["Без названия"])[0]
                title = title.lstrip("# ").strip()[:60] or "Без названия"
                with _data_lock:
                    store = load_data()
                    box = user_data(store, uid)
                    box["drafts"] = [d for d in box["drafts"] if d["id"] != draft_id]
                    box["drafts"].insert(0, {
                        "id": draft_id, "title": title,
                        "markdown": markdown, "updated": int(time.time()),
                    })
                    save_data(store)
                self._json({"ok": True, "id": draft_id})
            elif self.path == "/api/drafts/delete":
                draft_id = self._read_json().get("id")
                with _data_lock:
                    store = load_data()
                    box = user_data(store, uid)
                    box["drafts"] = [d for d in box["drafts"] if d["id"] != draft_id]
                    save_data(store)
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
                with _data_lock:
                    store = load_data()
                    box = user_data(store, uid)
                    box["scheduled"].append({
                        "id": uuid.uuid4().hex, "markdown": data.get("markdown", ""),
                        "target": target, "when": when, "status": "pending",
                    })
                    box["scheduled"].sort(key=lambda p: p["when"])
                    save_data(store)
                self._json({"ok": True})
            elif self.path == "/api/schedule/cancel":
                post_id = self._read_json().get("id")
                with _data_lock:
                    store = load_data()
                    box = user_data(store, uid)
                    box["scheduled"] = [p for p in box["scheduled"]
                                        if not (p["id"] == post_id
                                                and p["status"] == "pending")]
                    save_data(store)
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
    ok, me = api_call("getMe")
    if not ok:
        sys.exit(f"Токен не принят Telegram: {me}")
    global BOT_USERNAME
    BOT_USERNAME = me.get("username", "")
    log.info("Редактор для бота @%s", BOT_USERNAME)
    if s3.configured:
        log.info("Картинки: S3 %s/%s", s3.endpoint, s3.bucket)
    else:
        log.info("Картинки: хранилище Telegram (S3 не настроен в .env)")
    for ip in local_ips():
        log.info("Открыть на телефоне: http://%s:%d", ip, PORT)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
