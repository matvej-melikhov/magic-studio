"""Доменная логика студии: Telegram Bot API, медиа, AI, планировщик.

HTTP-слой живёт в server.py и импортирует всё отсюда. BOT_USERNAME
заполняется сервером при старте (getMe) — читать через core.BOT_USERNAME.
"""

import asyncio
import json
import logging
import os
import re
import socket
import time
import httpx2 as httpx
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
# React-сборка (Vite): если dist/ есть — отдаём SPA, иначе старый editor.html
DIST_DIR = os.path.join(WEB_DIR, "dist")
DIST_INDEX = os.path.join(DIST_DIR, "index.html")
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


# ── Импорт эмодзи-паков по имени/ссылке и каталог ───────────────────
# Ссылка «Поделиться» у пака: t.me/addemoji/<set_name>. Импорт по имени
# не требует премиума — состав отдаёт getStickerSet.
PACK_LINK_RE = re.compile(
    r"^(?:https?://)?t(?:elegram)?\.me/add(?:emoji|stickers)/"
    r"([A-Za-z0-9_]{1,64})/?$")
PACK_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

# Стартовый каталог, пока топ сервиса не накопил данных:
# (set_name из ссылки t.me/addemoji/…, название для витрины)
STARTER_PACKS: list[tuple[str, str]] = [
    ("blockymojis", "Minecraft | @Sendchan"),
    ("MINECRAFTmil", "MINECRAFT @milky_v_main"),
    ("mobminecraft2011_by_fStikBot", "Minecraft mob @olfiww"),
    ("MinecraftAirDsgn", "Майнкрафт от @AirAbout"),
    ("minemojinon", "Minecraft — @emojinon"),
]


def parse_pack_link(text: str) -> str | None:
    """set_name из ссылки t.me/addemoji/… или «голого» имени пака."""
    text = text.strip()
    m = PACK_LINK_RE.match(text)
    if m:
        return m.group(1)
    return text if PACK_NAME_RE.match(text) else None


def import_emoji_pack(uid: int, set_name: str) -> tuple[bool, str]:
    """Импортирует эмодзи-пак целиком. Возвращает (ok, title | ошибка)."""
    ok, st_set = api_call("getStickerSet", name=set_name)
    if not ok:
        return False, f"Пак «{set_name}» не найден: {st_set}"
    if st_set.get("sticker_type") != "custom_emoji":
        return False, f"«{st_set.get('title') or set_name}» — стикеры, а не кастомные эмодзи."
    # alt — привязанный к стикеру эмодзи: rich-markdown требует в alt
    # ровно один эмодзи, произвольный текст ломает отправку
    items = [(s["custom_emoji_id"], s.get("emoji") or "🙂")
             for s in st_set.get("stickers", []) if s.get("custom_emoji_id")]
    if not items:
        return False, f"В паке «{st_set.get('title') or set_name}» нет эмодзи."
    title = st_set.get("title") or set_name
    storage.epack_add(uid, set_name, title, items)
    return True, title


def emoji_catalog(uid: int, limit: int = 10) -> list[dict]:
    """Каталог паков: топ сервиса + стартовый список, с отметкой installed."""
    installed = {p["set_name"] for p in storage.epacks_list(uid)}
    seen: set[str] = set()
    out = []
    for p in storage.epacks_top(limit * 2):
        if p["set_name"] in seen:
            continue
        seen.add(p["set_name"])
        out.append({"set_name": p["set_name"], "title": p["title"],
                    "users": p["users"], "installed": p["set_name"] in installed})
    for name, title in STARTER_PACKS:
        if name not in seen:
            seen.add(name)
            out.append({"set_name": name, "title": title, "users": 0,
                        "installed": name in installed})
    return out[:limit]


# ── Картинки кастомных эмодзи: асинхронно, с кэшем в памяти ─────────
# Кэш: id -> (bytes, content-type). Неудачи помним минуту, чтобы битый id
# не долбил API на каждый рендер, но у браузера был шанс на повтор.
EMOJI_CACHE: dict[str, tuple[bytes, str]] = {}
EMOJI_FAILED: dict[str, float] = {}
EMOJI_FAIL_TTL = 60
EMOJI_TIMEOUT = 10.0
EMOJI_BATCH = 200          # лимит getCustomEmojiStickers на один вызов
_emoji_sem = asyncio.Semaphore(8)   # не больше 8 одновременных скачиваний
_emoji_tasks: dict[str, asyncio.Task] = {}  # single-flight по id
_http: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=EMOJI_TIMEOUT)
    return _http


async def _tg_api(method: str, payload: dict):
    """Асинхронный вызов Bot API: result или None."""
    try:
        resp = await _client().post(f"{API_URL}/{method}", json=payload)
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    return data.get("result") if data.get("ok") else None

async def _tg_download(file_path: str) -> bytes | None:
    try:
        resp = await _client().get(f"{FILE_URL}/{file_path}")
    except httpx.HTTPError:
        return None
    return resp.content if resp.is_success else None


def _sticker_file_id(st: dict) -> str:
    # у анимированных (tgs/webm) берём статичную миниатюру
    if (st.get("is_animated") or st.get("is_video")) and st.get("thumbnail"):
        return st["thumbnail"]["file_id"]
    return st["file_id"]


async def _load_emoji(emoji_id: str, sticker: dict | None) -> tuple[bytes, str] | None:
    """Скачивает одну картинку (метаданные — если не переданы из батча)."""
    async with _emoji_sem:
        if sticker is None:
            stickers = await _tg_api("getCustomEmojiStickers",
                                     {"custom_emoji_ids": [emoji_id]})
            if not stickers:
                EMOJI_FAILED[emoji_id] = time.time()
                return None
            sticker = stickers[0]
        info = await _tg_api("getFile", {"file_id": _sticker_file_id(sticker)})
        blob = await _tg_download(info["file_path"]) if info else None
        ext = os.path.splitext(info["file_path"])[1].lower() if info else ""
        ctype = {".webp": "image/webp", ".png": "image/png",
                 ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext)
        if not blob or not ctype:  # .tgs без миниатюры и прочая экзотика
            EMOJI_FAILED[emoji_id] = time.time()
            return None
        EMOJI_CACHE[emoji_id] = (blob, ctype)
        return EMOJI_CACHE[emoji_id]


def _emoji_task(emoji_id: str, sticker: dict | None) -> asyncio.Task:
    """Одно скачивание на id, сколько бы запросов его ни ждало."""
    task = _emoji_tasks.get(emoji_id)
    if task is None:
        task = asyncio.get_running_loop().create_task(_load_emoji(emoji_id, sticker))
        _emoji_tasks[emoji_id] = task
        task.add_done_callback(lambda _: _emoji_tasks.pop(emoji_id, None))
    return task


async def emoji_image(emoji_id: str) -> tuple[bytes, str] | None:
    """Картинка эмодзи из кэша или из Telegram (single-flight)."""
    if emoji_id in EMOJI_CACHE:
        return EMOJI_CACHE[emoji_id]
    if time.time() - EMOJI_FAILED.get(emoji_id, 0) < EMOJI_FAIL_TTL:
        return None
    # shield: обрыв соединения браузером не должен отменять общую задачу
    return await asyncio.shield(_emoji_task(emoji_id, None))


async def prefetch_emojis(ids: list[str]) -> None:
    """Фоновый прогрев кэша: метаданные всего пака одним вызовом API,
    файлы — параллельно (ограничено семафором)."""
    now = time.time()
    missing = [e for e in ids
               if e not in EMOJI_CACHE and now - EMOJI_FAILED.get(e, 0) >= EMOJI_FAIL_TTL]
    for i in range(0, len(missing), EMOJI_BATCH):
        batch = missing[i:i + EMOJI_BATCH]
        stickers = await _tg_api("getCustomEmojiStickers", {"custom_emoji_ids": batch})
        if stickers is None:
            return
        by_id = {st.get("custom_emoji_id"): st for st in stickers}
        await asyncio.gather(
            *(_emoji_task(e, by_id.get(e)) for e in batch if e in by_id),
            return_exceptions=True)


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
