"""FastAPI-приложение студии: HTTP-слой поверх core.py и storage.py.

Переезд с http.server идёт поэтапно: пока server.py остаётся точкой
входа со старым Handler, здесь набираются те же маршруты один в один.
Форматы ответов сохранены: {"ok": ...} и 401 {"ok": false, "error": "auth"}.
"""

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

import core
import storage

app = FastAPI(title="Magic Studio", docs_url=None, redoc_url=None)

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

NO_STORE = {"Cache-Control": "no-store"}


def _auth_error() -> JSONResponse:
    return JSONResponse({"ok": False, "error": "auth"}, status_code=401,
                        headers=NO_STORE)


def session_required(x_session: str = Header(default="")) -> dict:
    """Сессия из заголовка X-Session; без неё — 401 в формате фронта."""
    session = storage.session_get(x_session) if x_session else None
    if not session:
        raise HTTPException(status_code=401)
    return session


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    if exc.status_code == 401:
        return _auth_error()
    return JSONResponse({"ok": False, "error": str(exc.detail)},
                        status_code=exc.status_code, headers=NO_STORE)


def _serve_spa() -> Response:
    """index.html React-сборки, при её отсутствии — старый editor.html."""
    for candidate in (core.DIST_INDEX, core.EDITOR_FILE):
        if os.path.exists(candidate):
            return FileResponse(candidate, media_type="text/html",
                                headers=NO_STORE)
    return Response("frontend not found", status_code=500,
                    media_type="text/plain")


@app.get("/")
@app.get("/index.html")
def index():
    return _serve_spa()


@app.get("/assets/{rel_path:path}")
def assets(rel_path: str):
    full = os.path.realpath(os.path.join(core.DIST_DIR, "assets", rel_path))
    if not full.startswith(os.path.realpath(core.DIST_DIR) + os.sep):
        raise HTTPException(status_code=404)  # защита от path traversal
    ext = os.path.splitext(full)[1]
    if ext not in ASSET_TYPES or not os.path.exists(full):
        raise HTTPException(status_code=404)
    return FileResponse(full, media_type=ASSET_TYPES[ext],
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/config")
def config():
    return JSONResponse({"ok": True, "bot": core.BOT_USERNAME}, headers=NO_STORE)


@app.get("/api/state")
def state(session: dict = Depends(session_required)):
    uid = session["user_id"]
    return JSONResponse({
        "ok": True,
        "name": session.get("name", ""),
        "channels": storage.channels_list(uid),
        "drafts": storage.drafts_list(uid),
        "scheduled": storage.sched_list(uid),
        "published": storage.published_list(uid),
    }, headers=NO_STORE)


@app.get("/api/emojis")
def emojis(session: dict = Depends(session_required)):
    uid = session["user_id"]
    groups = [{"id": p["id"], "name": p["name"],
               "emojis": storage.emojis_by_pack(uid, p["id"])}
              for p in storage.epacks_list(uid)]
    return JSONResponse({"ok": True, "groups": groups}, headers=NO_STORE)


@app.get("/api/emoji/img")
def emoji_img(id: str = ""):
    # без сессии: <img> не умеет слать заголовки; отдаём только картинку
    img = core.fetch_emoji_image(id) if id.isdigit() and len(id) <= 32 else None
    if not img:
        return Response("emoji not found", status_code=404, media_type="text/plain")
    return Response(img[0], media_type=img[1], headers=NO_STORE)


@app.get("/{rest:path}")
def spa_fallback(rest: str):
    # /editor, /drafts и т.п. при обновлении страницы должны вернуть
    # приложение — роутер сам откроет нужный раздел
    path = "/" + rest
    if path in STATIC_FILES:
        name, ctype = STATIC_FILES[path]
        # сборка кладёт public/ в dist/; без сборки берём из web/public/
        for base in (core.DIST_DIR, os.path.join(core.WEB_DIR, "public")):
            full = os.path.join(base, name)
            if os.path.exists(full):
                return FileResponse(full, media_type=ctype, headers=NO_STORE)
        raise HTTPException(status_code=404)
    if path.startswith("/api/"):
        return JSONResponse({"ok": False, "error": "not found"},
                            status_code=404, headers=NO_STORE)
    return _serve_spa()


# ═══ POST: приём JSON-тел как в старом Handler (без pydantic-моделей —
# форматы исторические, валидация точечная) ═══

from fastapi import Body  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
import base64  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402


@app.post("/api/login")
def login(data: dict = Body(...)):
    code = str(data.get("code", "")).strip()
    entry = core.consume_login_code(code)
    if not entry:
        return JSONResponse({"ok": False, "error": "Неверный или устаревший код."},
                            headers=NO_STORE)
    token = storage.session_create(entry["user_id"], entry.get("name", ""))
    return JSONResponse({"ok": True, "token": token}, headers=NO_STORE)


@app.post("/api/upload")
def upload(data: dict = Body(...), session: dict = Depends(session_required)):
    uid = session["user_id"]
    blob = base64.b64decode(data["data"])
    name = data.get("name", "image.jpg")
    if core.s3.configured:
        ok, result = core.s3.upload(name, blob)
        return JSONResponse({"ok": ok, ("url" if ok else "error"): result},
                            headers=NO_STORE)
    # S3 не настроен — фолбэк на хранилище Telegram
    ok, result = core.store_image(uid, name, blob)
    if ok:
        return JSONResponse({"ok": True, "url": f"tg-file://{result}"}, headers=NO_STORE)
    return JSONResponse({"ok": False, "error": result}, headers=NO_STORE)


@app.post("/api/preview")
def preview(data: dict = Body(...), session: dict = Depends(session_required)):
    ok, result = core.send_post(data["markdown"], session["user_id"])
    return JSONResponse({"ok": ok, "error": None if ok else str(result)},
                        headers=NO_STORE)


@app.post("/api/publish")
def publish(data: dict = Body(...), session: dict = Depends(session_required)):
    uid = session["user_id"]
    target = data.get("target", "").strip()
    allowed = {c["username"] for c in storage.channels_list(uid)}
    if target not in allowed:
        return JSONResponse(
            {"ok": False,
             "error": "Канал не подключён — добавьте его во вкладке «Каналы»."},
            headers=NO_STORE)
    ok, result = core.send_post(data["markdown"], target)
    if ok:
        storage.published_add(uid, target, data["markdown"], result.get("message_id"))
    return JSONResponse({"ok": ok, "error": None if ok else str(result)},
                        headers=NO_STORE)


@app.post("/api/published/update")
def published_update(data: dict = Body(...), session: dict = Depends(session_required)):
    uid = session["user_id"]
    post = storage.published_get(uid, data.get("id", ""))
    if not post:
        return JSONResponse({"ok": False, "error": "Публикация не найдена."},
                            headers=NO_STORE)
    if not post.get("message_id"):
        return JSONResponse(
            {"ok": False, "error": "Для этого поста не сохранён message_id — "
             "редактировать можно только новые публикации."}, headers=NO_STORE)
    ok, result = core.edit_post(data.get("markdown", ""), post["target"],
                                post["message_id"])
    if ok:
        storage.published_update_markdown(uid, post["id"], data.get("markdown", ""))
    return JSONResponse({"ok": ok, "error": None if ok else result}, headers=NO_STORE)


@app.post("/api/channels/add")
def channels_add(data: dict = Body(...), session: dict = Depends(session_required)):
    uid = session["user_id"]
    username = data.get("username", "").strip()
    if username and not username.startswith("@"):
        username = "@" + username
    if not username:
        return JSONResponse({"ok": False, "error": "Укажите @username канала."},
                            headers=NO_STORE)
    ok, chat = core.verify_channel_admin(username, uid)
    if not ok:
        return JSONResponse({"ok": False, "error": chat}, headers=NO_STORE)
    storage.channel_add(uid, username, chat.get("title", username))
    return JSONResponse({"ok": True}, headers=NO_STORE)


@app.post("/api/channels/remove")
def channels_remove(data: dict = Body(...), session: dict = Depends(session_required)):
    storage.channel_remove(session["user_id"], data.get("username", ""))
    return JSONResponse({"ok": True}, headers=NO_STORE)


@app.post("/api/drafts/save")
def drafts_save(data: dict = Body(...), session: dict = Depends(session_required)):
    draft_id = storage.draft_save(session["user_id"], data.get("id"),
                                  data.get("markdown", ""))
    return JSONResponse({"ok": True, "id": draft_id}, headers=NO_STORE)


@app.post("/api/drafts/delete")
def drafts_delete(data: dict = Body(...), session: dict = Depends(session_required)):
    storage.draft_delete(session["user_id"], data.get("id", ""))
    return JSONResponse({"ok": True}, headers=NO_STORE)


@app.post("/api/schedule/add")
def schedule_add(data: dict = Body(...), session: dict = Depends(session_required)):
    target = data.get("target", "").strip()
    when = int(data.get("when", 0))
    if not target:
        return JSONResponse({"ok": False, "error": "Укажите канал."}, headers=NO_STORE)
    if when <= time.time():
        return JSONResponse({"ok": False, "error": "Время уже прошло."},
                            headers=NO_STORE)
    storage.sched_add(session["user_id"], data.get("markdown", ""), target, when)
    return JSONResponse({"ok": True}, headers=NO_STORE)


@app.post("/api/schedule/update")
def schedule_update(data: dict = Body(...), session: dict = Depends(session_required)):
    when = int(data.get("when", 0))
    if when <= time.time():
        return JSONResponse({"ok": False, "error": "Время уже прошло."},
                            headers=NO_STORE)
    if storage.sched_update(session["user_id"], data.get("id", ""),
                            data.get("markdown", ""),
                            data.get("target", "").strip(), when):
        return JSONResponse({"ok": True}, headers=NO_STORE)
    return JSONResponse({"ok": False, "error": "Пост не найден или уже отправлен."},
                        headers=NO_STORE)


@app.post("/api/schedule/cancel")
def schedule_cancel(data: dict = Body(...), session: dict = Depends(session_required)):
    storage.sched_cancel(session["user_id"], data.get("id", ""))
    return JSONResponse({"ok": True}, headers=NO_STORE)


@app.post("/api/schedule/publish_now")
def schedule_publish_now(data: dict = Body(...),
                         session: dict = Depends(session_required)):
    post = storage.sched_take_now(session["user_id"], data.get("id", ""))
    if not post:
        return JSONResponse({"ok": False,
                             "error": "Пост не найден или уже отправляется."},
                            headers=NO_STORE)
    ok, result = core.send_post(post["markdown"], post["target"])
    message_id = result.get("message_id") if ok else None
    storage.sched_finish(post, ok, None if ok else str(result), message_id)
    return JSONResponse({"ok": ok, "error": None if ok else str(result)},
                        headers=NO_STORE)


@app.post("/api/ai")
def ai(data: dict = Body(...), session: dict = Depends(session_required)):
    text = (data.get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "Пустой запрос."}, headers=NO_STORE)

    # context — пост целиком с помеченным фрагментом (правка выделенного)
    context = (data.get("context") or "").strip() or None

    def ndjson():
        # потоковый ответ: NDJSON-чанки по мере генерации модели
        for chunk in core.ai_stream(data.get("action", ""), text, context):
            yield (json.dumps(chunk, ensure_ascii=False) + "\n").encode()

    return StreamingResponse(ndjson(), media_type="application/x-ndjson; charset=utf-8",
                             headers=NO_STORE)
