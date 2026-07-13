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
