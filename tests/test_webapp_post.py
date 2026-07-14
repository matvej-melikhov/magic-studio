"""POST-маршруты webapp: вход, черновики, расписание, публикация, AI."""

import time

import core


def test_post_requires_auth(client):
    for path in ("/api/drafts/save", "/api/publish", "/api/ai"):
        resp = client.post(path, json={})
        assert resp.status_code == 401, path
        assert resp.json() == {"ok": False, "error": "auth"}


def test_login_flow(client, monkeypatch, db):
    monkeypatch.setattr(core, "consume_login_code",
                        lambda code: {"user_id": 7, "name": "Иван"} if code == "123456" else None)
    resp = client.post("/api/login", json={"code": "000000"})
    assert resp.json()["ok"] is False
    resp = client.post("/api/login", json={"code": "123456"})
    body = resp.json()
    assert body["ok"] is True
    # выданный токен реально открывает сессию
    state = client.get("/api/state", headers={"X-Session": body["token"]}).json()
    assert state["name"] == "Иван"


def test_drafts_roundtrip(client, auth):
    token, _ = auth
    h = {"X-Session": token}
    saved = client.post("/api/drafts/save", json={"markdown": "# Привет"}, headers=h).json()
    assert saved["ok"] and saved["id"]
    drafts = client.get("/api/state", headers=h).json()["drafts"]
    assert len(drafts) == 1
    client.post("/api/drafts/delete", json={"id": saved["id"]}, headers=h)
    assert client.get("/api/state", headers=h).json()["drafts"] == []


def test_publish_rejects_foreign_channel(client, auth):
    token, _ = auth
    resp = client.post("/api/publish", json={"target": "@notmine", "markdown": "x"},
                       headers={"X-Session": token})
    body = resp.json()
    assert body["ok"] is False and "не подключён" in body["error"]


def test_publish_ok(client, auth, db, monkeypatch):
    token, uid = auth
    db.channel_add(uid, "@mych", "Мой канал")
    monkeypatch.setattr(core, "send_post", lambda md, tgt: (True, {"message_id": 99}))
    resp = client.post("/api/publish", json={"target": "@mych", "markdown": "# x"},
                       headers={"X-Session": token})
    assert resp.json()["ok"] is True
    pub = client.get("/api/state", headers={"X-Session": token}).json()["published"]
    assert len(pub) == 1 and pub[0]["message_id"] == 99


def test_schedule_validation(client, auth):
    token, _ = auth
    h = {"X-Session": token}
    past = int(time.time()) - 60
    future = int(time.time()) + 3600
    assert client.post("/api/schedule/add", json={"target": "", "when": future},
                       headers=h).json()["error"] == "Укажите канал."
    assert client.post("/api/schedule/add", json={"target": "@c", "when": past},
                       headers=h).json()["error"] == "Время уже прошло."
    assert client.post("/api/schedule/add", json={"target": "@c", "when": future,
                                                  "markdown": "x"},
                       headers=h).json()["ok"] is True
    sched = client.get("/api/state", headers=h).json()["scheduled"]
    assert len(sched) == 1 and sched[0]["status"] == "pending"


def test_ai_stream_ndjson(client, auth, monkeypatch):
    token, _ = auth
    monkeypatch.setattr(core, "ai_stream",
                        lambda action, text, context=None, tone=None, refs=None:
                        iter([{"t": "При"}, {"t": "вет"}, {"done": True}]))
    resp = client.post("/api/ai", json={"action": "rewrite", "text": "hi"},
                       headers={"X-Session": token})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = [l for l in resp.text.splitlines() if l]
    assert len(lines) == 3 and '"done"' in lines[-1]
    # пустой запрос — ошибка без стрима
    resp = client.post("/api/ai", json={"text": "  "}, headers={"X-Session": token})
    assert resp.json()["error"] == "Пустой запрос."


def test_channels_add_verifies_admin(client, auth, monkeypatch):
    token, _ = auth
    monkeypatch.setattr(core, "verify_channel_admin",
                        lambda u, uid: (True, {"title": "Канал"}))
    resp = client.post("/api/channels/add", json={"username": "mych"},
                       headers={"X-Session": token})
    assert resp.json()["ok"] is True
    chans = client.get("/api/state", headers={"X-Session": token}).json()["channels"]
    assert chans[0]["username"] == "@mych"  # @ дописан автоматически
