"""Хранилище на SQLite: сессии, каналы, черновики, отложенные, публикации.

Соединение открывается на каждую операцию — этого достаточно для
локального сервера, а SQLite сам разруливает конкурентный доступ.
"""

import json
import os
import sqlite3
import time
import uuid

DB_FILE = "studio.db"
LEGACY_JSON = "data.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token   TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name    TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
    user_id  INTEGER NOT NULL,
    username TEXT NOT NULL,
    title    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, username)
);
CREATE TABLE IF NOT EXISTS drafts (
    id       TEXT PRIMARY KEY,
    user_id  INTEGER NOT NULL,
    title    TEXT NOT NULL DEFAULT '',
    markdown TEXT NOT NULL DEFAULT '',
    updated  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS scheduled (
    id       TEXT PRIMARY KEY,
    user_id  INTEGER NOT NULL,
    markdown TEXT NOT NULL DEFAULT '',
    target   TEXT NOT NULL,
    when_ts  INTEGER NOT NULL,
    status   TEXT NOT NULL DEFAULT 'pending',
    error    TEXT,
    started  INTEGER
);
CREATE TABLE IF NOT EXISTS published (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    target     TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    markdown   TEXT NOT NULL DEFAULT '',
    message_id INTEGER,
    when_ts    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_user ON drafts(user_id, updated DESC);
CREATE INDEX IF NOT EXISTS idx_sched_user ON scheduled(user_id, when_ts);
CREATE INDEX IF NOT EXISTS idx_pub_user ON published(user_id, when_ts DESC);
"""


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _db() as conn:
        conn.executescript(SCHEMA)
    _migrate_legacy_json()


def _migrate_legacy_json():
    """Разовый импорт старого data.json (переименовывается после импорта)."""
    if not os.path.exists(LEGACY_JSON):
        return
    try:
        data = json.load(open(LEGACY_JSON, encoding="utf-8"))
    except (OSError, ValueError):
        return
    with _db() as conn:
        for token, s in data.get("sessions", {}).items():
            conn.execute(
                "INSERT OR IGNORE INTO sessions VALUES (?,?,?,?)",
                (token, s["user_id"], s.get("name", ""), s.get("created", 0)))
        for uid, box in data.get("users", {}).items():
            uid = int(uid)
            for c in box.get("channels", []):
                conn.execute("INSERT OR IGNORE INTO channels VALUES (?,?,?)",
                             (uid, c["username"], c.get("title", "")))
            for d in box.get("drafts", []):
                conn.execute("INSERT OR IGNORE INTO drafts VALUES (?,?,?,?,?)",
                             (d["id"], uid, d.get("title", ""),
                              d.get("markdown", ""), d.get("updated", 0)))
            for p in box.get("scheduled", []):
                if p.get("status") == "sent":
                    conn.execute(
                        "INSERT OR IGNORE INTO published VALUES (?,?,?,?,?,?,?)",
                        (p["id"], uid, p["target"],
                         _title(p.get("markdown", "")), p.get("markdown", ""),
                         None, p.get("when", 0)))
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO scheduled VALUES (?,?,?,?,?,?,?,?)",
                        (p["id"], uid, p.get("markdown", ""), p["target"],
                         p.get("when", 0), p.get("status", "pending"),
                         p.get("error"), p.get("started")))
            for p in box.get("published", []):
                conn.execute(
                    "INSERT OR IGNORE INTO published VALUES (?,?,?,?,?,?,?)",
                    (p.get("id") or uuid.uuid4().hex, uid, p["target"],
                     p.get("title", ""), p.get("markdown", ""),
                     p.get("message_id"), p.get("when", 0)))
    os.replace(LEGACY_JSON, LEGACY_JSON + ".imported")


def _title(markdown: str) -> str:
    line = (markdown.strip().splitlines() or [""])[0]
    return line.lstrip("# ").strip()[:80] or "Без названия"


# ── Сессии ──────────────────────────────────────────

def session_create(user_id: int, name: str) -> str:
    token = uuid.uuid4().hex
    with _db() as conn:
        conn.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                     (token, user_id, name, int(time.time())))
    return token


def session_get(token: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


# ── Каналы ──────────────────────────────────────────

def channels_list(uid: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT username, title FROM channels WHERE user_id=? ORDER BY title",
            (uid,)).fetchall()
    return [dict(r) for r in rows]


def channel_add(uid: int, username: str, title: str):
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO channels VALUES (?,?,?)",
                     (uid, username, title))


def channel_remove(uid: int, username: str):
    with _db() as conn:
        conn.execute("DELETE FROM channels WHERE user_id=? AND username=?",
                     (uid, username))


# ── Черновики ───────────────────────────────────────

def drafts_list(uid: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, title, markdown, updated FROM drafts "
            "WHERE user_id=? ORDER BY updated DESC", (uid,)).fetchall()
    return [dict(r) for r in rows]


def draft_save(uid: int, draft_id: str | None, markdown: str) -> str:
    draft_id = draft_id or uuid.uuid4().hex
    with _db() as conn:
        conn.execute(
            "INSERT INTO drafts VALUES (?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
            "markdown=excluded.markdown, updated=excluded.updated "
            "WHERE drafts.user_id=excluded.user_id",
            (draft_id, uid, _title(markdown), markdown, int(time.time())))
    return draft_id


def draft_delete(uid: int, draft_id: str):
    with _db() as conn:
        conn.execute("DELETE FROM drafts WHERE user_id=? AND id=?", (uid, draft_id))


# ── Отложенные ──────────────────────────────────────

def sched_list(uid: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, markdown, target, when_ts AS `when`, status, error "
            "FROM scheduled WHERE user_id=? ORDER BY when_ts", (uid,)).fetchall()
    return [dict(r) for r in rows]


def sched_add(uid: int, markdown: str, target: str, when: int):
    with _db() as conn:
        conn.execute("INSERT INTO scheduled VALUES (?,?,?,?,?,?,?,?)",
                     (uuid.uuid4().hex, uid, markdown, target, when,
                      "pending", None, None))


def sched_update(uid: int, post_id: str, markdown: str, target: str, when: int) -> bool:
    with _db() as conn:
        cur = conn.execute(
            "UPDATE scheduled SET markdown=?, target=?, when_ts=?, "
            "status='pending', error=NULL WHERE id=? AND user_id=? "
            "AND status IN ('pending','error')",
            (markdown, target, when, post_id, uid))
    return cur.rowcount > 0


def sched_cancel(uid: int, post_id: str):
    with _db() as conn:
        conn.execute("DELETE FROM scheduled WHERE id=? AND user_id=? "
                     "AND status != 'sending'", (post_id, uid))


def sched_take_due(stale_after: int) -> list[dict]:
    """Атомарно забирает назревшие посты (→ sending) и лечит зависшие."""
    now = int(time.time())
    with _db() as conn:
        conn.execute(
            "UPDATE scheduled SET status='error', error='Отправка была прервана. "
            "Проверьте, вышел ли пост в канале, и запланируйте заново.' "
            "WHERE status='sending' AND COALESCE(started, 0) < ?",
            (now - stale_after,))
        rows = conn.execute(
            "SELECT id, user_id, markdown, target FROM scheduled "
            "WHERE status='pending' AND when_ts <= ?", (now,)).fetchall()
        due = [dict(r) for r in rows]
        for post in due:
            conn.execute("UPDATE scheduled SET status='sending', started=? WHERE id=?",
                         (now, post["id"]))
    return due


def sched_finish(post: dict, ok: bool, result: str, message_id=None):
    with _db() as conn:
        if ok:
            conn.execute("DELETE FROM scheduled WHERE id=?", (post["id"],))
            _insert_published(conn, post["user_id"], post["target"],
                              post["markdown"], message_id)
        else:
            conn.execute("UPDATE scheduled SET status='error', error=? WHERE id=?",
                         (result, post["id"]))


# ── Публикации ──────────────────────────────────────

def _insert_published(conn, uid: int, target: str, markdown: str, message_id):
    conn.execute("INSERT INTO published VALUES (?,?,?,?,?,?,?)",
                 (uuid.uuid4().hex, uid, target, _title(markdown), markdown,
                  message_id, int(time.time())))
    conn.execute(
        "DELETE FROM published WHERE user_id=? AND id NOT IN "
        "(SELECT id FROM published WHERE user_id=? ORDER BY when_ts DESC LIMIT 200)",
        (uid, uid))


def published_add(uid: int, target: str, markdown: str, message_id=None):
    with _db() as conn:
        _insert_published(conn, uid, target, markdown, message_id)


def published_list(uid: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, target, title, markdown, message_id, when_ts AS `when` "
            "FROM published WHERE user_id=? ORDER BY when_ts DESC", (uid,)).fetchall()
    return [dict(r) for r in rows]


def published_get(uid: int, post_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT id, target, title, markdown, message_id, when_ts AS `when` "
            "FROM published WHERE user_id=? AND id=?", (uid, post_id)).fetchone()
    return dict(row) if row else None


def published_update_markdown(uid: int, post_id: str, markdown: str):
    with _db() as conn:
        conn.execute("UPDATE published SET markdown=?, title=? WHERE id=? AND user_id=?",
                     (markdown, _title(markdown), post_id, uid))
