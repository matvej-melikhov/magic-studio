"""MVP Telegram-бот: принимает markdown (текстом или файлом) и отправляет
его обратно как rich message (Bot API 10.1, sendRichMessage).

Запуск из корня репозитория:  BOT_TOKEN=123:abc python3 app/bot.py
"""

import json
import logging
import os
import sys
import time

import requests

import storage
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
    "/login — код входа в веб-редактор\n"
    "/emoji — коллекции кастомных эмодзи для редактора\n"
    "Сообщение с кастомными эмодзи — сохраню их для вставки в редакторе.\n\n"
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


def _utf16_slice(s: str, offset: int, length: int) -> str:
    """Вырезает кусок строки по офсетам Telegram (они в UTF-16 code units)."""
    b = s.encode("utf-16-le")
    return b[offset * 2:(offset + length) * 2].decode("utf-16-le", "ignore")


# ── Менеджер эмодзи: коллекции с инлайн-кнопками ────
# Состояние диалога: chat_id -> {"awaiting": …, "pending_ids": […]}
emoji_state: dict[int, dict] = {}

MAX_GROUP_NAME = 40


def kb(rows: list) -> dict:
    return {"inline_keyboard": rows}


def manager_view(uid: int) -> tuple[str, dict]:
    """Главный экран менеджера: список групп."""
    rows = [[{"text": f"📁 {g['name']} ({g['count']})",
              "callback_data": f"g:{g['id']}"}]
            for g in storage.egroups_list(uid)]
    ungrouped = len(storage.emojis_by_group(uid, None))
    if ungrouped:
        rows.append([{"text": f"📂 Без группы ({ungrouped})", "callback_data": "g:0"}])
    rows.append([{"text": "➕ Новая группа", "callback_data": "gnew"}])
    text = ("Коллекции эмодзи. Выберите группу для просмотра и правки.\n"
            "Пополнение: просто пришлите сообщение с кастомными эмодзи.")
    return text, kb(rows)


def group_view(uid: int, gid: int) -> tuple[str, dict]:
    """Экран группы: эмодзи-кнопки (тап — удалить) и управление группой."""
    if gid:
        name = next((g["name"] for g in storage.egroups_list(uid)
                     if g["id"] == gid), "?")
    else:
        name = "Без группы"
    emojis = storage.emojis_by_group(uid, gid or None)
    text = (f"«{name}» — {len(emojis)} эмодзи.\n"
            "Нажмите на эмодзи, чтобы удалить его из библиотеки.")
    rows, row = [], []
    for e in emojis:
        row.append({"text": e["alt"], "callback_data": f"ed:{gid}:{e['emoji_id']}"})
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if gid:
        rows.append([{"text": "✏️ Переименовать", "callback_data": f"gr:{gid}"},
                     {"text": "🗑 Удалить группу", "callback_data": f"gd:{gid}"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": "gb"}])
    return text, kb(rows)


def import_keyboard(uid: int) -> dict:
    """Выбор группы для только что присланных эмодзи."""
    rows = [[{"text": f"📁 {g['name']}", "callback_data": f"imp:{g['id']}"}]
            for g in storage.egroups_list(uid)]
    rows.append([{"text": "📂 Без группы", "callback_data": "imp:0"},
                 {"text": "➕ В новую группу", "callback_data": "impnew"}])
    return kb(rows)


def handle_custom_emojis(message: dict) -> bool:
    """Сохраняет кастомные эмодзи из сообщения; True — если они там были."""
    text = message.get("text", "")
    custom = [(e["custom_emoji_id"],
               _utf16_slice(text, e["offset"], e["length"]))
              for e in message.get("entities") or []
              if e.get("type") == "custom_emoji"]
    if not custom:
        return False
    unique: dict[str, str] = {}
    for eid, alt in custom:
        unique.setdefault(eid, alt or "🙂")
    uid = message.get("from", {}).get("id", 0)
    chat_id = message["chat"]["id"]
    storage.emojis_add(uid, list(unique.items()))
    emoji_state[chat_id] = {"pending_ids": list(unique)}
    api_call(
        "sendMessage",
        chat_id=chat_id,
        text=f"Сохранил эмодзи: {len(unique)}. В какую группу их положить?",
        reply_markup=import_keyboard(uid),
    )
    return True


def handle_awaited_text(message: dict) -> bool:
    """Ответ на вопрос бота (название группы); True — если текст обработан."""
    chat_id = message["chat"]["id"]
    st = emoji_state.get(chat_id)
    text = (message.get("text") or "").strip()
    if not st or not st.get("awaiting") or not text or text.startswith("/"):
        return False
    uid = message.get("from", {}).get("id", 0)
    name = text[:MAX_GROUP_NAME]
    awaiting = st.pop("awaiting")
    if awaiting == "newgroup":
        storage.egroup_create(uid, name)
        emoji_state.pop(chat_id, None)
    elif awaiting == "impgroup":
        gid = storage.egroup_create(uid, name)
        storage.emojis_set_group(uid, st.get("pending_ids") or [], gid)
        emoji_state.pop(chat_id, None)
    elif awaiting.startswith("rename:"):
        storage.egroup_rename(uid, int(awaiting.split(":")[1]), name)
        emoji_state.pop(chat_id, None)
    else:
        return False
    view, keyboard = manager_view(uid)
    api_call("sendMessage", chat_id=chat_id, text=view, reply_markup=keyboard)
    return True


def handle_callback(cq: dict):
    """Нажатия инлайн-кнопок менеджера эмодзи."""
    data = cq.get("data", "")
    msg = cq.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    uid = cq.get("from", {}).get("id", 0)
    ack = ""

    def edit(text: str, keyboard: dict | None):
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if keyboard:
            params["reply_markup"] = keyboard
        api_call("editMessageText", **params)

    if data == "gb":
        edit(*manager_view(uid))
    elif data == "gnew":
        emoji_state[chat_id] = {"awaiting": "newgroup"}
        send_plain(chat_id, "Название новой группы?")
    elif data.startswith("g:"):
        edit(*group_view(uid, int(data[2:])))
    elif data.startswith("gr:"):
        emoji_state[chat_id] = {"awaiting": f"rename:{data[3:]}"}
        send_plain(chat_id, "Новое название группы?")
    elif data.startswith("gd:"):
        storage.egroup_delete(uid, int(data[3:]))
        ack = "Группа удалена, её эмодзи — в «Без группы»"
        edit(*manager_view(uid))
    elif data.startswith("ed:"):
        _, gid, eid = data.split(":", 2)
        storage.emoji_delete(uid, eid)
        ack = "Эмодзи удалён из библиотеки"
        edit(*group_view(uid, int(gid)))
    elif data == "impnew":
        st = emoji_state.setdefault(chat_id, {})
        st["awaiting"] = "impgroup"
        send_plain(chat_id, "Название новой группы?")
    elif data.startswith("imp:"):
        st = emoji_state.pop(chat_id, None) or {}
        ids = st.get("pending_ids") or []
        gid = int(data[4:]) or None
        if ids:
            storage.emojis_set_group(uid, ids, gid)
        edit(f"Готово — эмодзи разложены ({len(ids)}). "
             "Они уже доступны в веб-редакторе.", None)
        ack = "Сохранено"
    api_call("answerCallbackQuery", callback_query_id=cq["id"], text=ack)


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
        elif text.startswith("/emoji"):
            uid = message.get("from", {}).get("id", 0)
            view, keyboard = manager_view(uid)
            api_call("sendMessage", chat_id=chat_id, text=view,
                     reply_markup=keyboard)
        elif text.startswith("/post"):
            handle_post_command(chat_id, message.get("from", {}).get("id", 0), text)
        elif text.startswith("/cancel"):
            post_state.get(chat_id, {}).pop("pending", None)
            send_plain(chat_id, "Публикация отменена.")
        else:
            # ответ на вопрос менеджера эмодзи (название группы)?
            if handle_awaited_text(message):
                return
            # сообщение с кастомными эмодзи — импорт в библиотеку редактора,
            # но не тогда, когда пользователь публикует пост через /post
            if not post_state.get(chat_id, {}).get("pending") and \
                    handle_custom_emojis(message):
                return
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
    storage.init_db()
    # меню команд в клиенте Telegram (кнопка «/» слева от поля ввода)
    api_call("setMyCommands", commands=[
        {"command": "emoji", "description": "Коллекции кастомных эмодзи"},
        {"command": "login", "description": "Код входа в веб-редактор"},
        {"command": "post", "description": "Публикация в канал: /post @канал"},
        {"command": "cancel", "description": "Отменить публикацию"},
        {"command": "help", "description": "Справка"},
    ])
    log.info("Запущен бот @%s", me.get("username"))

    offset = 0
    while True:
        try:
            ok, updates = api_call(
                "getUpdates", offset=offset, timeout=50,
                allowed_updates=["message", "callback_query"],
            )
        except requests.RequestException as e:
            log.warning("getUpdates network error: %s", e)
            continue
        if not ok:
            log.error("getUpdates failed: %s", updates)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            try:
                if update.get("callback_query"):
                    handle_callback(update["callback_query"])
                elif update.get("message"):
                    handle_message(update["message"])
            except Exception:
                log.exception("Ошибка обработки обновления")


if __name__ == "__main__":
    main()
