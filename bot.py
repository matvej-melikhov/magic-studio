"""MVP Telegram-бот: принимает markdown (текстом или файлом) и отправляет
его обратно как rich message (Bot API 10.1, sendRichMessage).

Запуск:  BOT_TOKEN=123:abc python3 bot.py
"""

import json
import logging
import os
import sys
import time

import requests

from env_utils import load_env

load_env()

BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_KEY")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# Лимит Rich Messages: 32768 символов UTF-8 в тексте сообщения
MAX_TEXT_LEN = 32768
# Ограничение на размер принимаемого файла (байт)
MAX_FILE_SIZE = 256 * 1024
ALLOWED_EXTENSIONS = (".md", ".markdown", ".txt")

HELP_TEXT = (
    "Пришлите markdown-текст сообщением или файлом (.md, .markdown, .txt) — "
    "я отправлю его обратно в новом rich-формате Telegram.\n\n"
    "Поддерживается GitHub Flavored Markdown: заголовки, цитаты, ссылки, "
    "формулы ($x^2$ и $$E=mc^2$$), списки, таблицы, сноски и другое.\n\n"
    "/login — код входа в веб-редактор\n\n"
    "Публикация в канал:\n"
    "/post @канал — следующее сообщение или файл уйдёт в канал\n"
    "/post — то же с последним использованным каналом\n"
    "/cancel — отменить публикацию\n"
    "Бот должен быть администратором канала с правом публикации."
)

# Состояние публикации в канал: chat_id -> {"target": str, "pending": bool}
post_state: dict[int, dict] = {}

# Файл с chat_id владельца — используется веб-редактором (server.py)
STATE_FILE = "state.json"
# Одноразовые коды входа в веб-редактор: пишет бот, потребляет server.py
LOGIN_CODES_FILE = "login_codes.json"
LOGIN_CODE_TTL = 600


def remember_owner_chat(chat_id: int):
    try:
        state = json.load(open(STATE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if state.get("owner_chat_id") != chat_id:
        state["owner_chat_id"] = chat_id
        json.dump(state, open(STATE_FILE, "w", encoding="utf-8"))


def _save_login_code(code: str, user: dict):
    """Записывает код/токен входа, который потребит server.py; чистит старые."""
    try:
        codes = json.load(open(LOGIN_CODES_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        codes = {}
    now = int(time.time())
    codes = {c: v for c, v in codes.items() if v.get("expires", 0) > now}
    codes[code] = {
        "user_id": user["id"],
        "name": user.get("first_name", ""),
        "expires": now + LOGIN_CODE_TTL,
    }
    tmp = LOGIN_CODES_FILE + ".tmp"
    json.dump(codes, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, LOGIN_CODES_FILE)


def issue_login_code(user: dict) -> str:
    """Одноразовый 6-значный код для ручного входа."""
    import secrets
    code = f"{secrets.randbelow(1000000):06d}"
    _save_login_code(code, user)
    return code


def confirm_login_token(token: str, user: dict) -> bool:
    """Подтверждает вход по deep-link токену из /start <token>."""
    if not (8 <= len(token) <= 64) or not token.replace("-", "").replace("_", "").isalnum():
        return False
    _save_login_code(token, user)
    return True

log = logging.getLogger("markdown-bot")


def api_call(method: str, **params):
    """Вызов метода Bot API. Возвращает (ok, result_or_description)."""
    resp = requests.post(f"{API_URL}/{method}", json=params, timeout=60)
    data = resp.json()
    if data.get("ok"):
        return True, data.get("result")
    return False, data.get("description", "unknown error")


def send_plain(chat_id: int, text: str):
    api_call("sendMessage", chat_id=chat_id, text=text)


def send_rich_markdown(target, markdown: str, user_chat_id: int):
    """Отправляет markdown как rich message в target (чат или @канал).

    Статус и ошибки сообщает пользователю в user_chat_id.
    """
    if len(markdown) > MAX_TEXT_LEN:
        send_plain(
            user_chat_id,
            f"Текст слишком длинный: {len(markdown)} символов, "
            f"лимит rich-сообщений — {MAX_TEXT_LEN}.",
        )
        return

    ok, result = api_call(
        "sendRichMessage", chat_id=target, rich_message={"markdown": markdown}
    )
    if not ok:
        log.warning("sendRichMessage failed: %s", result)
        send_plain(user_chat_id, f"Не удалось оформить сообщение: {result}")
    elif target != user_chat_id:
        send_plain(user_chat_id, f"Опубликовано в {target}.")


def download_document(document: dict) -> str | None:
    """Скачивает документ и возвращает его текст, либо None при ошибке."""
    ok, file_info = api_call("getFile", file_id=document["file_id"])
    if not ok:
        log.warning("getFile failed: %s", file_info)
        return None
    resp = requests.get(f"{FILE_URL}/{file_info['file_path']}", timeout=60)
    if not resp.ok:
        return None
    try:
        return resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def resolve_target(chat_id: int) -> "int | str":
    """Куда отправлять пост: канал, если ожидается публикация, иначе сам чат."""
    state = post_state.get(chat_id)
    if state and state.get("pending"):
        state["pending"] = False
        return state["target"]
    return chat_id


def is_channel_admin(target: str, user_id: int) -> tuple[bool, str]:
    """Проверяет, что отправитель — администратор канала."""
    ok, admins = api_call("getChatAdministrators", chat_id=target)
    if not ok:
        return False, f"Не удалось проверить канал: {admins}"
    if not any(a.get("user", {}).get("id") == user_id for a in admins):
        return False, "Вы не администратор этого канала."
    return True, ""


def handle_post_command(chat_id: int, user_id: int, text: str):
    parts = text.split(maxsplit=1)
    state = post_state.setdefault(chat_id, {})
    if len(parts) > 1:
        target = parts[1].strip()
        if not (target.startswith("@") or target.lstrip("-").isdigit()):
            send_plain(chat_id, "Укажите канал как @username или числовой id.")
            return
        ok, error = is_channel_admin(target, user_id)
        if not ok:
            send_plain(chat_id, error)
            return
        state["target"] = target
    if not state.get("target"):
        send_plain(chat_id, "Канал не задан. Используйте: /post @канал")
        return
    state["pending"] = True
    send_plain(
        chat_id,
        f"Ок, следующее сообщение или файл опубликую в {state['target']}. "
        "Отменить: /cancel",
    )


def handle_message(message: dict):
    chat_id = message["chat"]["id"]
    if message["chat"].get("type") == "private":
        remember_owner_chat(chat_id)
    text = message.get("text")
    document = message.get("document")

    if text:
        if text.startswith("/start"):
            payload = text.split(maxsplit=1)[1].strip() if " " in text else ""
            if payload and payload.startswith("login-") and confirm_login_token(
                    payload, message.get("from", {})):
                send_plain(
                    chat_id,
                    "✅ Вход подтверждён. Вернитесь на вкладку веб-редактора — "
                    "вы уже вошли.",
                )
            else:
                send_plain(chat_id, HELP_TEXT)
        elif text.startswith("/help"):
            send_plain(chat_id, HELP_TEXT)
        elif text.startswith("/login"):
            user = message.get("from", {})
            code = issue_login_code(user)
            send_plain(
                chat_id,
                f"Код входа в веб-редактор: {code}\n"
                "Введите его на странице входа в течение 10 минут.",
            )
        elif text.startswith("/post"):
            handle_post_command(chat_id, message.get("from", {}).get("id", 0), text)
        elif text.startswith("/cancel"):
            post_state.get(chat_id, {}).pop("pending", None)
            send_plain(chat_id, "Публикация отменена.")
        else:
            send_rich_markdown(resolve_target(chat_id), text, chat_id)
        return

    if document:
        name = (document.get("file_name") or "").lower()
        if not name.endswith(ALLOWED_EXTENSIONS):
            send_plain(
                chat_id,
                "Принимаю только текстовые файлы: " + ", ".join(ALLOWED_EXTENSIONS),
            )
            return
        if document.get("file_size", 0) > MAX_FILE_SIZE:
            send_plain(
                chat_id,
                f"Файл слишком большой, лимит {MAX_FILE_SIZE // 1024} КБ.",
            )
            return
        content = download_document(document)
        if content is None:
            send_plain(
                chat_id,
                "Не удалось прочитать файл — нужен текст в кодировке UTF-8.",
            )
            return
        send_rich_markdown(resolve_target(chat_id), content, chat_id)
        return

    send_plain(chat_id, HELP_TEXT)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not BOT_TOKEN:
        sys.exit("Задайте переменную окружения BOT_TOKEN (токен от @BotFather).")

    ok, me = api_call("getMe")
    if not ok:
        sys.exit(f"Токен не принят Telegram: {me}")
    log.info("Запущен бот @%s", me.get("username"))

    offset = 0
    while True:
        try:
            ok, updates = api_call(
                "getUpdates", offset=offset, timeout=50, allowed_updates=["message"]
            )
        except requests.RequestException as e:
            log.warning("getUpdates network error: %s", e)
            continue
        if not ok:
            log.error("getUpdates failed: %s", updates)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if not message:
                continue
            try:
                handle_message(message)
            except Exception:
                log.exception("Ошибка обработки сообщения")


if __name__ == "__main__":
    main()
